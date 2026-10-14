"""Crash-readable on-disk storage for versioned CubOS run resources."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from cubos_api.models.runs import RunEvent, RunRecord
from cubos_api.services.yaml_io import atomic_write_text


INPUT_ARTIFACTS = ("gantry.yaml", "deck.yaml", "protocol.yaml")
OUTPUT_ARTIFACTS = ("result.json", "error.txt", "events.jsonl", "run.json")
ALLOWED_ARTIFACTS = frozenset((*INPUT_ARTIFACTS, *OUTPUT_ARTIFACTS))
log = logging.getLogger(__name__)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RunStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Cache only committed sequences to avoid reparsing a growing log per step.
        self._sequence_cache: dict[str, int] = {}
        self._sequence_lock = threading.Lock()

    def run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def exists(self, run_id: str) -> bool:
        return (self.run_dir(run_id) / "run.json").is_file()

    def create(
        self,
        record: RunRecord,
        *,
        gantry_yaml: str,
        deck_yaml: str,
        protocol_yaml: str,
    ) -> RunRecord:
        directory = self.run_dir(record.run_id)
        directory.mkdir(parents=True, exist_ok=False)
        inputs = {
            "gantry.yaml": gantry_yaml,
            "deck.yaml": deck_yaml,
            "protocol.yaml": protocol_yaml,
        }
        for name, content in inputs.items():
            atomic_write_text(directory / name, content)
        record.digests = {
            "gantry_sha256": sha256_text(gantry_yaml),
            "deck_sha256": sha256_text(deck_yaml),
            "protocol_sha256": sha256_text(protocol_yaml),
        }
        record.artifacts = list(INPUT_ARTIFACTS) + ["events.jsonl", "run.json"]
        self.write(record)
        self.append_event(record.run_id, state="queued", message="run accepted")
        return record

    def read(self, run_id: str) -> RunRecord | None:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            return None
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, record: RunRecord) -> None:
        atomic_write_text(
            self.run_dir(record.run_id) / "run.json",
            record.model_dump_json(indent=2) + "\n",
        )

    def append_event(
        self,
        run_id: str,
        *,
        state: str,
        message: str,
        kind: str = "lifecycle",
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        path = self.run_dir(run_id) / "events.jsonl"
        # The execution thread and API cancellation requests share this log.
        with self._sequence_lock:
            last = self._sequence_cache.get(run_id)
            if last is None:
                events = self._read_events(path, repair=True)
                last = max((event.sequence for event in events), default=0)
            event = RunEvent(
                sequence=last + 1,
                timestamp=time.time(),
                state=state,
                message=message,
                kind=kind,
                data=data,
            )
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(event.model_dump_json() + "\n")
            except OSError:
                self._sequence_cache.pop(run_id, None)
                raise
            self._sequence_cache[run_id] = event.sequence
        return event

    def events(self, run_id: str) -> list[RunEvent]:
        with self._sequence_lock:
            return self._read_events(self.run_dir(run_id) / "events.jsonl")

    def _read_events(self, path: Path, *, repair: bool = False) -> list[RunEvent]:
        if not path.is_file():
            return []
        original = content = path.read_bytes()
        lines = content.splitlines(keepends=True)
        events = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                events.append(RunEvent.model_validate_json(line))
            except ValidationError as exc:
                if (
                    index != len(lines) - 1
                    or line.endswith((b"\n", b"\r"))
                    or exc.errors()[0]["type"] != "json_invalid"
                ):
                    raise
                if repair:
                    with path.with_suffix(".jsonl.partial").open("ab") as handle:
                        handle.write(line)
                        handle.flush()
                        os.fsync(handle.fileno())
                    log.warning("Preserved truncated event from %s in %s.partial", path, path)
                content = content[:-len(line)]
        if repair and content and not content.endswith(b"\n"):
            content += b"\n"
        if repair and content != original:
            atomic_write_text(path, content.decode("utf-8"))
        return events

    def write_result(self, record: RunRecord, result: Any) -> None:
        path = self.run_dir(record.run_id) / "result.json"
        atomic_write_text(path, json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
        if "result.json" not in record.artifacts:
            record.artifacts.append("result.json")

    def write_error(self, record: RunRecord, error: str) -> None:
        atomic_write_text(self.run_dir(record.run_id) / "error.txt", error + "\n")
        if "error.txt" not in record.artifacts:
            record.artifacts.append("error.txt")

    def artifact_path(self, run_id: str, name: str) -> Path | None:
        if name not in ALLOWED_ARTIFACTS:
            return None
        path = self.run_dir(run_id) / name
        return path if path.is_file() else None

    def incomplete_records(self) -> Iterable[RunRecord]:
        for path in self.base_dir.glob("*/run.json"):
            try:
                record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.state in {"queued", "running", "cancel_requested"}:
                yield record
