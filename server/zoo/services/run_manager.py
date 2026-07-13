"""Single-owner asynchronous execution for versioned CubOS runs."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from zoo.config import ZooSettings, get_settings
from zoo.models.runs import RunRecord, RunSubmission
from zoo.services.run_store import RunStore, sha256_text
from zoo.services.yaml_io import resolve_config_path


log = logging.getLogger(__name__)


class RunConflictError(RuntimeError):
    pass


class RunPolicyError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    cubos_result_fields = ("status", "steps_executed", "campaign_id")
    if any(hasattr(value, name) for name in cubos_result_fields):
        return {
            name: _jsonable(getattr(value, name))
            for name in cubos_result_fields
            if hasattr(value, name)
        }
    if hasattr(value, "__dict__") and vars(value):
        return {
            str(key): _jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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


def _mock_execute(*, gantry_path: Path, deck_path: Path, protocol_path: Path) -> Any:
    from protocol_engine.setup import setup_protocol

    protocol, context = setup_protocol(
        str(gantry_path),
        str(deck_path),
        str(protocol_path),
        gantry=None,
        mock_mode=True,
    )
    context.gantry.connect_instruments()
    try:
        return protocol.execute(context)
    finally:
        context.gantry.disconnect_instruments()


class RunManager:
    def __init__(self, settings: ZooSettings):
        self.settings = settings
        self.store = RunStore(settings.ensure_run_dir())
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        for record in self.store.incomplete_records():
            record.state = "failed"
            record.finished_at = time.time()
            record.error = "server restarted before the run reached a terminal state"
            self.store.write_error(record, record.error)
            self.store.append_event(record.run_id, state="failed", message=record.error)
            self.store.write(record)

    def submit(self, submission: RunSubmission) -> RunRecord:
        run_id = submission.run_id or uuid.uuid4().hex
        with self._lock:
            if self._active_run_id is not None:
                raise RunConflictError(f"server busy with run {self._active_run_id!r}")
            if self.store.exists(run_id) or self.store.run_dir(run_id).exists():
                raise RunConflictError(f"run {run_id!r} already exists")

            gantry_yaml, deck_yaml, protocol_yaml = self._resolve_bundle(submission)
            self._validate_bundle(gantry_yaml, deck_yaml, protocol_yaml)
            record = RunRecord(
                run_id=run_id,
                state="queued",
                created_at=time.time(),
                mock_mode=submission.mock_mode,
                metadata=submission.metadata,
            )
            self.store.create(
                record,
                gantry_yaml=gantry_yaml,
                deck_yaml=deck_yaml,
                protocol_yaml=protocol_yaml,
            )
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
        return self.store.read(run_id)

    def events(self, run_id: str):
        return self.store.events(run_id)

    def cancel(self, run_id: str) -> RunRecord:
        from zoo.routers import gantry as gantry_router

        with self._lock:
            record = self.store.read(run_id)
            if record is None:
                raise KeyError(run_id)
            if record.state in {"succeeded", "failed", "cancelled"}:
                raise RunConflictError(f"run {run_id!r} is already {record.state}")
            if self._active_run_id != run_id:
                raise RunConflictError(f"run {run_id!r} is not active")
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

    def _execute(self, run_id: str) -> None:
        from zoo.routers import gantry as gantry_router

        record = self.store.read(run_id)
        if record is None:
            return
        directory = self.store.run_dir(run_id)
        record.state = "running"
        record.started_at = time.time()
        self.store.append_event(run_id, state="running", message="execution started")
        self.store.write(record)

        gate_acquired = False
        try:
            gantry_router.begin_run(protocol_file="protocol.yaml")
            gate_acquired = True
            if record.mock_mode:
                raw_result = _mock_execute(
                    gantry_path=directory / "gantry.yaml",
                    deck_path=directory / "deck.yaml",
                    protocol_path=directory / "protocol.yaml",
                )
            else:
                raw_result = gantry_router.run_protocol_on_session(
                    gantry_path=str(directory / "gantry.yaml"),
                    deck_path=str(directory / "deck.yaml"),
                    protocol_path=str(directory / "protocol.yaml"),
                    gantry_file="gantry.yaml",
                    deck_file="deck.yaml",
                    protocol_file="protocol.yaml",
                    db_path=self.settings.data_db_path,
                )
            result = _jsonable(raw_result)
            record = self.store.read(run_id) or record
            record.state = "succeeded"
            record.result = result
            record.finished_at = time.time()
            self.store.write_result(record, result)
            self.store.append_event(run_id, state="succeeded", message="execution completed")
            self.store.write(record)
        except Exception as exc:  # noqa: BLE001 - persist complete failure details
            log.exception("CubOS run %s failed", run_id)
            record = self.store.read(run_id) or record
            cancelled = record.state == "cancel_requested"
            record.state = "cancelled" if cancelled else "failed"
            record.finished_at = time.time()
            record.error = f"{type(exc).__name__}: {exc}"
            self.store.write_error(record, traceback.format_exc())
            self.store.append_event(
                run_id,
                state=record.state,
                message=record.error,
            )
            self.store.write(record)
        finally:
            if gate_acquired:
                gantry_router.end_run()
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None


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
