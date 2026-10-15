"""Durable protocol execution records, independent of advisory observers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import inspect
import logging
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any
import uuid

from cubos.data.record_metadata import digest, error_details, sanitize, software_identity

log = logging.getLogger(__name__)
_ACTIVE: ContextVar[Any] = ContextVar('cubos_execution_trace', default=None)
_LOCAL_LOCKS: set[str] = set()
_LOCAL_LOCK_GUARD = threading.Lock()


class RecordingError(RuntimeError):
    """An execution record could not be committed; no action should be replayed."""


class ProtocolCleanupError(RuntimeError):
    """Owned protocol cleanup failed after execution."""


class ProtocolCancelled(Exception):
    """Cancellation observed at an engine execution boundary."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def current_trace():
    return _ACTIVE.get()


class RunLock:
    def __init__(self, database: str | Path, run_id: str):
        path = Path(database).expanduser().resolve()
        self.key = str(path) + ':' + run_id
        self.path = path.parent / '.run-locks' / (hashlib.sha256(self.key.encode()).hexdigest() + '.lock')
        self.handle = None

    def acquire(self) -> bool:
        with _LOCAL_LOCK_GUARD:
            if self.key in _LOCAL_LOCKS:
                return False
            _LOCAL_LOCKS.add(self.key)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open('a+b')
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                if not self.handle.read(1):
                    self.handle.write(b'0')
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.release()
            return False

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        with _LOCAL_LOCK_GUARD:
            _LOCAL_LOCKS.discard(self.key)


def recover_abandoned_runs(store) -> list[str]:
    recovered = []
    if str(store.db_path) == ':memory:':
        return recovered
    offset = 0
    while rows := store.execution_records.list_runs(limit=100, offset=offset):
        offset += len(rows)
        for row in rows:
            if row['status'] not in {'queued', 'running'}:
                continue
            owner = row['metadata'].get('owner', {})
            if owner.get('host') != socket.gethostname() or owner.get('database') != str(Path(store.db_path).expanduser().resolve()):
                continue
            lock = RunLock(store.db_path, row['run_id'])
            if lock.acquire():
                try:
                    store.execution_records.recover_run(row['run_id'], utc_now())
                    recovered.append(row['run_id'])
                finally:
                    lock.release()
    return recovered


def bound_args(handler, context, args):
    try:
        bound = inspect.signature(handler).bind(context, **args)
        bound.apply_defaults()
        first = next(iter(bound.arguments), None)
        return {k: v for k, v in bound.arguments.items() if k != first}
    except (ValueError, TypeError):
        return dict(args)


def protocol_metadata(protocol) -> dict:
    plan = [{'index': s.index, 'command': s.command_name,
             'args': sanitize(bound_args(s.handler, None, s.args) if hasattr(s, 'handler') else s.args),
             'requested_args': sanitize(s.args),
             'source': {'path': str(protocol.source_path) if protocol.source_path else None,
                        'pointer': f'/protocol/{s.index}/{s.command_name}' if getattr(protocol, 'source_bytes', None) is not None else f'/plan/{s.index}'}}
            for s in protocol.steps]
    source = getattr(protocol, 'source_bytes', None)
    return {'source': str(protocol.source_path) if protocol.source_path else None,
            'content_sha256': getattr(protocol, 'source_sha256', None) if source is not None else digest(plan),
            'hash_kind': 'source_bytes' if source is not None else 'sanitized_plan_v1',
            'snapshot': getattr(protocol, 'source_snapshot', None), 'plan': plan,
            'plan_sha256': digest(plan)}


def context_metadata(context) -> dict:
    components = {}
    gantry = context.gantry
    instances = getattr(gantry, 'instruments', {})
    if not isinstance(instances, dict):
        instances = {}
    for name, instrument in instances.items():
        attrs = vars(instrument) if hasattr(instrument, '__dict__') else {}
        offline = attrs.get('_offline', attrs.get('offline'))
        components[name] = {'offline': offline if isinstance(offline, bool) else None,
                            'mount': sanitize({k: attrs.get(k) for k in ('name', 'offset_x', 'offset_y', 'depth')}),
                            'driver': type(instrument).__module__ + '.' + type(instrument).__name__}
    board = getattr(gantry, 'controller', None)
    attrs = vars(board) if hasattr(board, '__dict__') else {}
    offline = attrs.get('_offline', attrs.get('offline'))
    values = [v['offline'] for v in components.values()] + [offline if isinstance(offline, bool) else None]
    mode = 'unknown' if None in values else ('simulated' if all(values) else 'hardware' if not any(values) else 'mixed')
    connected = getattr(context, 'connections_observed', False) is True
    if False in values and not connected:
        mode = 'unknown'
    labware = getattr(context.deck, 'labware', {})
    if not isinstance(labware, dict):
        labware = {}
    return {'execution_mode': mode, 'connection_observation': 'lifecycle_completed' if connected else 'unknown', 'components': {'gantry': {'offline': values[-1]}, 'instruments': components},
            'setup_snapshot': {'gantry': sanitize(context.gantry_config),
                               'positions': sanitize(context.positions),
                               'deck': sanitize(labware),
                               'safe_z': sanitize(getattr(gantry, 'safe_z', None)),
                               'captured_at': utc_now(),
                               'fluid_state_id': context.fluid_state_id}}


class RunRecorder:
    def __init__(self, data_store, *, run_id=None, metadata=None, cancel_event=None):
        self.store = data_store
        self.records = data_store.execution_records
        self.run_id = run_id or uuid.uuid4().hex
        self.metadata = {'record_version': 1, 'software': software_identity(), **(metadata or {})}
        self.cancel_event = cancel_event
        self.errors: list[dict] = []
        self.cleanup_errors: list[dict] = []
        self.stack: list[dict] = []
        self.lock = None
        self.token = None
        self.protocol = None

    @property
    def active_step_id(self):
        return self.stack[-1]['id'] if self.stack else None

    def __enter__(self):
        if str(self.store.db_path) != ':memory:':
            self.lock = RunLock(self.store.db_path, self.run_id)
            if not self.lock.acquire():
                raise RecordingError('Run execution ownership unavailable')
        self.metadata['owner'] = {'host': socket.gethostname(),
                                  'database': str(Path(self.store.db_path).expanduser().resolve()),
                                  'session': uuid.uuid4().hex}
        self.started_at, self.started_ns = utc_now(), time.monotonic_ns()
        try:
            self.records.create_run(self.run_id, metadata=sanitize(self.metadata), started_at=self.started_at)
            self.token = _ACTIVE.set(self)
        except BaseException:
            if self.lock:
                self.lock.release()
            raise
        return self

    def update_metadata(self, **kwargs):
        self.metadata.update(sanitize(kwargs))
        self.records.update_run(self.run_id, metadata=self.metadata)

    def recording_error(self, exc):
        self.errors.append(error_details(exc, stage='recording'))
        log.error('Run %s recording failed (%s)', self.run_id, type(exc).__name__)

    def cleanup_error(self, exc):
        self.cleanup_errors.append(error_details(exc, stage='cleanup'))

    def check_cancelled(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise ProtocolCancelled('Cancellation observed before next command')
        if self.errors:
            raise RecordingError('Run recording is incomplete; next command was not started')

    def attach(self, context, protocol):
        self.protocol = protocol
        self.update_metadata(protocol=protocol_metadata(protocol), **context_metadata(context))
        if context.campaign_id is not None:
            self.records.update_run(self.run_id, campaign_id=context.campaign_id)

    def resolved(self, **values):
        if self.stack and self.active_step_id and not self.errors:
            frame = self.stack[-1]
            frame['parameters'].setdefault('resolved', {}).update(sanitize(values))
            try:
                self.records.update_step_parameters(frame['id'], frame['parameters'])
            except Exception as exc:
                self.recording_error(exc)

    def skipped(self, reason):
        if self.stack:
            self.stack[-1]['skip'] = {'kind': 'skipped', 'stage': 'preflight', 'reason': sanitize(reason)}

    @contextmanager
    def step(self, command, parameters=None, *, iteration_index=None, source=None):
        outer = not self.stack
        if outer:
            self.check_cancelled()
        parent = self.active_step_id
        if source is None:
            source = self.stack[-1]['source'] if self.stack else {}
        frame = {'id': uuid.uuid4().hex, 'parameters': sanitize(parameters or {}),
                 'source': source, 'skip': None}
        started_at, started_ns = utc_now(), time.monotonic_ns()
        if self.errors:
            frame['id'] = None
        else:
            try:
                self.records.start_step(frame['id'], self.run_id, parent_step_execution_id=parent,
                                        command=command, source=sanitize(source), parameters=frame['parameters'],
                                        iteration_index=iteration_index, started_at=started_at)
            except Exception as exc:
                self.recording_error(exc)
                frame['id'] = None
                if outer:
                    raise RecordingError('Step start could not be persisted') from exc
        self.stack.append(frame)
        error = None
        try:
            yield frame
        except BaseException as exc:
            error = exc
            raise
        finally:
            ended_at, duration_ns = utc_now(), time.monotonic_ns() - started_ns
            status = ('cancelled' if isinstance(error, (ProtocolCancelled, KeyboardInterrupt)) else
                      'failed' if error is not None else 'skipped' if frame['skip'] else 'completed')
            details = error_details(error) if error else frame['skip']
            try:
                if frame['id']:
                    self.records.finish_step(frame['id'], status=status, ended_at=ended_at,
                                             duration_ns=duration_ns, details=details)
            except Exception as exc:
                self.recording_error(exc)
            finally:
                self.stack.pop()
        if outer and self.errors:
            raise RecordingError('Command returned but execution recording is incomplete')

    def __exit__(self, exc_type, exc, tb):
        status = ('cancelled' if isinstance(exc, (ProtocolCancelled, KeyboardInterrupt)) else
                  'failed' if exc is not None or self.errors or self.cleanup_errors else 'completed')
        details = error_details(exc) if exc else None
        if isinstance(exc, RecordingError) or (exc is None and self.errors):
            details = {'kind': 'recording_failure'}
        if self.cleanup_errors:
            details = {**(details or {'kind': 'cleanup_failure'}), 'cleanup_errors': self.cleanup_errors}
        finish_error = None
        try:
            self.records.finish_run(self.run_id, status=status, ended_at=utc_now(),
                                    duration_ns=time.monotonic_ns()-self.started_ns,
                                    details=details, recording_errors=self.errors)
        except Exception as error:
            self.recording_error(error)
            finish_error = error
        finally:
            if self.token is not None:
                _ACTIVE.reset(self.token)
            if self.lock:
                self.lock.release()
        if exc is None and self.cleanup_errors:
            raise ProtocolCleanupError('Protocol cleanup failed; see run details')
        if exc is None and (finish_error or self.errors):
            raise RecordingError('Run recording is incomplete') from finish_error
        return False


@contextmanager
def protocol_recording(protocol, context):
    from cubos.data import DataStore, register_deck_labware
    active = current_trace()
    if active:
        if isinstance(context.data_store, DataStore) and context.data_store is not active.store:
            left, right = str(context.data_store.db_path), str(active.store.db_path)
            if ':memory:' in (left, right) or Path(left).expanduser().resolve() != Path(right).expanduser().resolve():
                raise RecordingError('Nested execution must use the same experiment database')
        previous = context.execution_trace
        previous_protocol = active.protocol
        previous_store = context.data_store
        previous_campaign = context.campaign_id
        try:
            context.execution_trace = active
            if not isinstance(context.data_store, DataStore):
                context.data_store = active.store
            ensure_campaign(context)
            context.run_id = active.run_id
            if previous_protocol is None:
                active.attach(context, protocol)
            else:
                active.protocol = protocol
            yield active
        finally:
            context.execution_trace = previous
            active.protocol = previous_protocol
            if previous_store is not context.data_store:
                context.data_store = previous_store
                context.campaign_id = previous_campaign
        return
    if context.data_store is not None and not isinstance(context.data_store, DataStore):
        yield None
        return
    owns_store = context.data_store is None
    if owns_store:
        context.data_store = DataStore()
    try:
        with RunRecorder(context.data_store, metadata={'lifecycle_scope': 'prepared_context'}) as recorder:
            context.execution_trace = recorder
            context.run_id = recorder.run_id
            ensure_campaign(context)
            recorder.attach(context, protocol)
            yield recorder
    finally:
        context.execution_trace = None
        if owns_store:
            context.data_store.close()
            context.data_store = None
            context.campaign_id = None


def ensure_campaign(context):
    from cubos.data import DataStore, register_deck_labware
    if isinstance(context.data_store, DataStore) and context.campaign_id is None:
        context.campaign_id = context.data_store.create_campaign(description='Protocol execution')
        if type(context.deck).__module__.startswith('cubos.'):
            register_deck_labware(context.data_store, context.campaign_id, context.deck)


def recorded_run(scope):
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            from cubos.data import DataStore
            from cubos.data.data_store import DataStore as CoreDataStore
            from cubos.yaml_utils import frozen_yaml_sources, read_yaml_source
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            store = values.get('data_store')
            if store is not None and not isinstance(store, CoreDataStore):
                return function(*args, **kwargs)
            active = current_trace()
            owned_store = active is None and store is None
            store = active.store if active else store or (DataStore(values['db_path']) if values.get('db_path') is not None else DataStore())
            if not isinstance(store, CoreDataStore):
                return function(*args, **kwargs)
            @contextmanager
            def recording():
                if active:
                    yield active
                else:
                    with RunRecorder(store, metadata={'lifecycle_scope': scope}) as recorder:
                        yield recorder
            try:
                with recording() as recorder:
                    bundle = {}
                    for key in ('gantry_path', 'deck_path', 'protocol_path'):
                        path = values.get(key)
                        if isinstance(path, (str, Path)):
                            try:
                                bundle[str(Path(path).resolve())] = read_yaml_source(path)
                            except FileNotFoundError:
                                pass
                    import yaml
                    snapshots = {key: yaml.safe_load(raw) for key, raw in bundle.items()}
                    updates = {'requested_setup': sanitize(snapshots)}
                    if 'mock_mode' in values:
                        updates['requested_mock_mode'] = values['mock_mode']
                    recorder.update_metadata(**updates)
                    with frozen_yaml_sources(bundle):
                        return function(*args, **kwargs)
            finally:
                if owned_store:
                    store.close()
        return wrapped
    return decorate
