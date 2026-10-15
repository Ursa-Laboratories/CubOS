"""Single-owner asynchronous execution for versioned CubOS runs."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
import tempfile
import threading
import time
from datetime import datetime
import uuid
from pathlib import Path
from typing import Any

import yaml

from cubos.data import DataStore
from cubos.data.record_metadata import sanitize
from cubos.deck import load_deck_from_yaml
from cubos.deck.errors import DeckLoaderError

from cubos_api.config import CubOSSettings, get_settings
from cubos_api.models.runs import RunRecord, RunSubmission
from cubos_api.models.state import RunStateSelection
from cubos_api.services.run_store import RunStore, sha256_text
from cubos_api.services.step_observer import RunStoreStepObserver
from cubos_api.services.yaml_io import resolve_config_path


log = logging.getLogger(__name__)


class RunConflictError(RuntimeError):
    pass


class RunPolicyError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    cubos_result_fields = ("status", "steps_executed", "campaign_id", "results")
    if any(hasattr(value, name) for name in cubos_result_fields) and not isinstance(value, dict):
        return sanitize({name: _jsonable(getattr(value, name)) for name in cubos_result_fields if hasattr(value, name)})
    return sanitize(value)


def _check_protocol_policy(
    protocol_yaml: str,
    *,
    allowed_commands: set[str],
    allowed_instruments: set[str],
) -> None:
    try:
        document = yaml.safe_load(protocol_yaml)
    except yaml.YAMLError as exc:
        raise RunPolicyError(f"protocol YAML is not parseable: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("protocol"), list):
        raise RunPolicyError("protocol YAML must contain a top-level protocol list")
    if not document["protocol"]:
        raise RunPolicyError("protocol list must not be empty")

    for index, step in enumerate(document["protocol"]):
        if not isinstance(step, dict) or len(step) != 1:
            raise RunPolicyError(f"step {index} must be a single-command mapping")
        command, body = next(iter(step.items()))
        if allowed_commands and command not in allowed_commands:
            raise RunPolicyError(f"step {index}: command {command!r} is not allowed")
        if isinstance(body, dict):
            instrument = body.get("instrument")
            if allowed_instruments and instrument is not None and instrument not in allowed_instruments:
                raise RunPolicyError(f"step {index}: instrument {instrument!r} is not allowed")


def _mock_execute(
    *,
    gantry_path: Path,
    deck_path: Path,
    protocol_path: Path,
    step_observer: Any | None = None,
    data_store: Any | None = None,
) -> Any:
    from cubos.protocol_engine.setup import setup_protocol

    protocol, context = setup_protocol(
        str(gantry_path),
        str(deck_path),
        str(protocol_path),
        gantry=None,
        mock_mode=True,
        step_observer=step_observer,
        data_store=data_store,
    )
    context.gantry.connect_instruments()
    try:
        return protocol.execute(context)
    finally:
        context.gantry.disconnect_instruments()


class RunManager:
    def __init__(self, settings: CubOSSettings):
        self.settings = settings
        self.store = RunStore(settings.ensure_run_dir())
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._bundles: dict[str, tuple[str, str, str]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        from cubos.protocol_engine.execution_trace import recover_abandoned_runs
        store = DataStore(self.settings.data_db_path) if Path(self.settings.data_db_path).expanduser().is_file() else None
        try:
            if store is not None:
                recover_abandoned_runs(store)
            for record in self.store.incomplete_records():
                if store is None or store.execution_records.get_run(record.run_id) is None:
                    record.state = "failed"
                    record.finished_at = None
                    record.core_status = "interrupted"
                    record.error = "execution interrupted; completion time unknown"
                    record.recovered_at = datetime.now().astimezone().isoformat()
                    self.store.write(record)
        finally:
            if store is not None:
                store.close()

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active_run_id

    def submit(self, submission: RunSubmission) -> RunRecord:
        run_id = submission.run_id or uuid.uuid4().hex
        with self._lock:
            if self._active_run_id is not None:
                raise RunConflictError(f"server busy with run {self._active_run_id!r}")
            if self.store.exists(run_id) or self.store.run_dir(run_id).exists():
                raise RunConflictError(f"run {run_id!r} already exists")

            with self._read_records() as records:
                if records is not None and records.get_run(run_id) is not None:
                    raise RunConflictError(f"run {run_id!r} already exists in the experiment database")
            gantry_yaml, deck_yaml, protocol_yaml = self._resolve_bundle(submission)
            self._validate_bundle(gantry_yaml, deck_yaml, protocol_yaml)
            fluid_state_id = self._resolve_run_state(deck_yaml, submission.state)
            record = RunRecord(
                run_id=run_id,
                state="queued",
                created_at=time.time(),
                mock_mode=submission.mock_mode,
                metadata=submission.metadata,
                fluid_state_id=fluid_state_id,
            )
            self.store.create(
                record,
                gantry_yaml=gantry_yaml,
                deck_yaml=deck_yaml,
                protocol_yaml=protocol_yaml,
            )
            self._bundles[run_id] = (gantry_yaml, deck_yaml, protocol_yaml)
            self._cancel_events[run_id] = threading.Event()
            self._active_run_id = run_id

        thread = threading.Thread(
            target=self._execute,
            args=(run_id,),
            name=f"cubos-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return record

    def get(self, run_id: str) -> RunRecord | None:
        record = self.store.read(run_id)
        if record is None:
            return None
        with self._read_records() as records:
            traced = records.get_run(run_id) if records is not None else None
        if traced:
            record.core_status = traced["status"]
            previous_state = record.state
            record.state = {"completed": "succeeded", "interrupted": "failed", "paused": "running"}.get(traced["status"], traced["status"])
            # API state includes output publication; core_status reports the
            # already committed physical/runtime outcome independently.
            record.artifacts_pending = (self.active_run_id == run_id and previous_state in {"queued", "running", "cancel_requested"} and traced["status"] in {"completed", "failed", "cancelled", "interrupted"})
            if record.artifacts_pending:
                record.state = "cancel_requested" if previous_state == "cancel_requested" else "running"
            elif previous_state == "cancel_requested" and traced["status"] == "running":
                record.state = "cancel_requested"
            record.metadata = traced["metadata"]
            record.recording_errors = traced.get("recording_errors") or []
            record.recovered_at = traced.get("recovered_at")
            for field, source in (("started_at", "started_at"), ("finished_at", "ended_at")):
                value = traced.get(source)
                setattr(record, field, datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None)
        return record

    @contextmanager
    def _read_records(self):
        from cubos.data.execution_records import ExecutionRecords
        path = Path(self.settings.data_db_path).expanduser().resolve()
        try:
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        except sqlite3.OperationalError:
            if not path.exists():
                yield None
                return
            raise
        try:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='protocol_runs'").fetchone()
            yield ExecutionRecords(connection) if exists else None
        finally:
            connection.close()

    def steps(self, run_id: str, *, after_sequence: int = 0, limit: int = 100):
        with self._read_records() as records:
            return records.list_steps(run_id, after_sequence=after_sequence, limit=limit) if records is not None else []

    def events(self, run_id: str):
        return self.store.events(run_id)

    def cancel(self, run_id: str) -> RunRecord:
        from cubos_api.routers import gantry as gantry_router

        with self._lock:
            record = self.store.read(run_id)
            if record is None:
                raise KeyError(run_id)
            if record.state in {"succeeded", "failed", "cancelled"}:
                raise RunConflictError(f"run {run_id!r} is already {record.state}")
            if self._active_run_id != run_id:
                raise RunConflictError(f"run {run_id!r} is not active")
            self._cancel_events[run_id].set()
            record.state = "cancel_requested"
            self.store.append_event(
                run_id,
                state="cancel_requested",
                message="operator requested cancellation",
            )
            self.store.write(record)

        if not record.mock_mode:
            gantry_router.request_feed_hold_interrupt()
        return record

    def _resolve_bundle(self, submission: RunSubmission) -> tuple[str, str, str]:
        if submission.gantry_config is not None:
            assert submission.deck_config is not None
            assert submission.protocol_yaml is not None
            return submission.gantry_config, submission.deck_config, submission.protocol_yaml

        assert submission.gantry_file is not None
        assert submission.deck_file is not None
        assert submission.protocol_file is not None
        base = self.settings.configs_dir
        paths = (
            resolve_config_path(base, "gantry", submission.gantry_file),
            resolve_config_path(base, "deck", submission.deck_file),
            resolve_config_path(base, "protocol", submission.protocol_file),
        )
        for path in paths:
            if not path.is_file():
                raise RunPolicyError(f"configuration file not found: {path.name}")
        return tuple(path.read_text(encoding="utf-8") for path in paths)  # type: ignore[return-value]

    def _validate_bundle(self, gantry_yaml: str, deck_yaml: str, protocol_yaml: str) -> None:
        _check_protocol_policy(
            protocol_yaml,
            allowed_commands=set(self.settings.allowed_commands),
            allowed_instruments=set(self.settings.allowed_instruments),
        )
        expected_gantry = self.settings.expected_gantry_sha256
        if expected_gantry and sha256_text(gantry_yaml) != expected_gantry:
            raise RunPolicyError("gantry configuration digest does not match the device pin")
        expected_deck = self.settings.expected_deck_sha256
        if expected_deck and sha256_text(deck_yaml) != expected_deck:
            raise RunPolicyError("deck configuration digest does not match the device pin")

    def _resolve_run_state(
        self, deck_yaml: str, state: RunStateSelection | None
    ) -> int | None:
        """Create or resume the run's fluid state, ahead of hardware execution.

        Returns ``None`` for a stateless run (``state`` omitted entirely —
        every run submitted before Feature 07 keeps behaving exactly as it
        did). ``cubos.data`` state exceptions (not-found, deck-fingerprint
        mismatch, reconciliation-required) propagate unchanged so the router
        can map each to a distinct HTTP status.
        """
        if state is None:
            return None

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(deck_yaml)
                tmp_path = Path(tmp.name)
            try:
                deck = load_deck_from_yaml(tmp_path)
            except DeckLoaderError as exc:
                raise RunPolicyError(f"cannot load run deck: {exc}") from exc

            store = DataStore(self.settings.data_db_path)
            try:
                if state.initial_state is not None:
                    fluids = {
                        key: {
                            "volume_ul": item.volume_ul,
                            "composition": item.composition,
                        }
                        for key, item in state.initial_state.fluids.items()
                    }
                    return store.create_fluid_state(
                        str(tmp_path),
                        deck,
                        label=state.initial_state.label,
                        initial_fluids=fluids,
                    )
                assert state.fluid_state_id is not None
                return store.resume_fluid_state(
                    state.fluid_state_id, str(tmp_path), deck
                )
            finally:
                store.close()
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _projection_error(self, run_id: str, exc: Exception, data_store=None) -> None:
        log.error("Run %s API projection failed (%s)", run_id, type(exc).__name__)
        if data_store is not None:
            try:
                traced = data_store.execution_records.get_run(run_id)
                if traced is not None:
                    errors = list(traced.get("recording_errors") or [])
                    errors.append({"type": type(exc).__name__, "stage": "api_projection", "message_omitted": True})
                    data_store.execution_records.update_run(run_id, recording_errors=errors)
            except Exception:
                log.error("Run %s projection failure could not be recorded", run_id)

    def _execute(self, run_id: str) -> None:
        from cubos.protocol_engine.execution_trace import RunRecorder, ProtocolCancelled
        from cubos.yaml_utils import frozen_yaml_sources

        data_store = None
        record = None
        try:
            record = self.store.read(run_id)
            if record is None:
                return
            directory = self.store.run_dir(run_id)
            bundle = self._bundles.pop(run_id)
            sources = {directory / name: content for name, content in zip(("gantry.yaml", "deck.yaml", "protocol.yaml"), bundle)}
            data_store = DataStore(self.settings.data_db_path)
            record.state = "running"
            record.started_at = time.time()
            try:
                self.store.append_event(run_id, state="running", message="execution started")
                self.store.write(record)
            except Exception as exc:
                self._projection_error(run_id, exc)
            observer = RunStoreStepObserver(self.store, run_id)
            metadata = {"user_metadata": record.metadata, "lifecycle_scope": "api_session",
                        "requested_mock_mode": record.mock_mode,
                        "requested_setup": {name: yaml.safe_load(content) for name, content in
                                            zip(("gantry.yaml", "deck.yaml", "protocol.yaml"), bundle)}}
            with RunRecorder(data_store, run_id=run_id, metadata=metadata, cancel_event=self._cancel_events[run_id]), frozen_yaml_sources(sources):
                raw_result = self._dispatch(record, directory, observer, data_store)
            record.state = "succeeded"
            record.result = _jsonable(raw_result)
            record.finished_at = time.time()
            try:
                self.store.write_result(record, record.result)
                self.store.append_event(run_id, state="succeeded", message="execution completed")
                self.store.write(record)
            except Exception as exc:
                self._projection_error(run_id, exc, data_store)
        except Exception as exc:
            log.error("CubOS run %s failed (%s)", run_id, type(exc).__name__)
            if record is not None:
                record.state = "cancelled" if isinstance(exc, ProtocolCancelled) else "failed"
                record.finished_at = time.time()
                record.error = type(exc).__name__
                try:
                    self.store.write_error(record, record.error)
                    self.store.append_event(run_id, state=record.state, message=record.error)
                    self.store.write(record)
                except Exception as projection_exc:
                    self._projection_error(run_id, projection_exc, data_store)
        finally:
            try:
                if data_store is not None:
                    data_store.close()
            finally:
                with self._lock:
                    self._bundles.pop(run_id, None)
                    self._cancel_events.pop(run_id, None)
                    if self._active_run_id == run_id:
                        self._active_run_id = None

    def _dispatch(self, record, directory, step_observer, data_store):
        from cubos_api.routers import gantry as gantry_router
        run_id = record.run_id
        gate_acquired = False
        try:
            gantry_router.begin_run(protocol_file="protocol.yaml")
            gate_acquired = True
            if record.mock_mode:
                raw_result = _mock_execute(
                    gantry_path=directory / "gantry.yaml",
                    deck_path=directory / "deck.yaml",
                    protocol_path=directory / "protocol.yaml",
                    step_observer=step_observer,
                    data_store=data_store,
                )
            else:
                # Manual bring-up handles (Camera view preview, lighting) hold
                # the vendor device open; the run's own instruments must be
                # able to claim it.
                from cubos_api.routers.instruments import reset_manual_instruments
                reset_manual_instruments()
                raw_result = gantry_router.run_protocol_on_session(
                    gantry_path=str(directory / "gantry.yaml"),
                    deck_path=str(directory / "deck.yaml"),
                    protocol_path=str(directory / "protocol.yaml"),
                    gantry_file="gantry.yaml",
                    deck_file="deck.yaml",
                    protocol_file="protocol.yaml",
                    db_path=self.settings.data_db_path,
                    fluid_state_id=record.fluid_state_id,
                    step_observer=step_observer,
                )
            return raw_result

        finally:
            if gate_acquired:
                gantry_router.end_run()


_manager: RunManager | None = None
_manager_lock = threading.Lock()


def get_run_manager() -> RunManager:
    global _manager
    with _manager_lock:
        settings = get_settings()
        desired = settings.run_dir.expanduser().resolve()
        if _manager is None or _manager.store.base_dir != desired:
            _manager = RunManager(settings)
        return _manager


def reset_run_manager() -> None:
    global _manager
    with _manager_lock:
        _manager = None
