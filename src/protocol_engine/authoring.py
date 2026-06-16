"""Python authoring helpers for CubOS protocols."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compiler import CommandCall, compile_protocol
from .protocol import Protocol

_UNSET = object()


def _row_labels(rows: str | Iterable[str]) -> list[str]:
    if isinstance(rows, str):
        row_spec = rows.strip().upper()
        if ":" in row_spec:
            start, end = [part.strip() for part in row_spec.split(":", 1)]
            if len(start) != 1 or len(end) != 1:
                raise ValueError("Row ranges must look like 'A:D'.")
            if ord(end) < ord(start):
                raise ValueError("Row ranges must be ascending.")
            return [chr(row) for row in range(ord(start), ord(end) + 1)]
        if "," in row_spec:
            labels = [part.strip() for part in row_spec.split(",")]
            if not all(label for label in labels):
                raise ValueError("Row list contains an empty label.")
            return labels
        if not row_spec:
            raise ValueError("Rows cannot be empty.")
        return [row_spec]
    return [str(row).strip().upper() for row in rows]


def wells(
    plate: str,
    *,
    rows: str | Iterable[str],
    columns: Iterable[int | str],
) -> list[str]:
    """Return row-major well targets such as ``plate.A1`` through ``plate.D6``."""
    row_labels = _row_labels(rows)
    column_labels = [str(column) for column in columns]
    return [
        f"{plate}.{row_label}{column_label}"
        for row_label in row_labels
        for column_label in column_labels
    ]


class ProtocolBuilder:
    """Build a ``Protocol`` from Python while preserving YAML semantics."""

    def __init__(self) -> None:
        self._calls: list[CommandCall] = []
        self._positions: dict[str, Any] = {}

    def home(self) -> "ProtocolBuilder":
        return self.command("home")

    def move(
        self,
        *,
        instrument: str,
        position: Any,
        travel_z: Any = _UNSET,
    ) -> "ProtocolBuilder":
        args = {"instrument": instrument, "position": position}
        if travel_z is not _UNSET:
            args["travel_z"] = travel_z
        return self.command("move", args)

    def measure(
        self,
        *,
        instrument: str,
        position: str,
        measurement_height: float,
        method: Any = _UNSET,
        indentation_limit_height: Any = _UNSET,
        method_kwargs: Any = _UNSET,
    ) -> "ProtocolBuilder":
        args: dict[str, Any] = {
            "instrument": instrument,
            "position": position,
            "measurement_height": measurement_height,
        }
        if method is not _UNSET:
            args["method"] = method
        if indentation_limit_height is not _UNSET:
            args["indentation_limit_height"] = indentation_limit_height
        if method_kwargs is not _UNSET:
            args["method_kwargs"] = method_kwargs
        return self.command("measure", args)

    def scan(
        self,
        *,
        plate: str,
        instrument: str,
        method: str,
        measurement_height: float,
        interwell_scan_height: float,
        indentation_limit_height: Any = _UNSET,
        delay_s: Any = _UNSET,
        method_kwargs: Any = _UNSET,
    ) -> "ProtocolBuilder":
        args: dict[str, Any] = {
            "plate": plate,
            "instrument": instrument,
            "method": method,
            "measurement_height": measurement_height,
            "interwell_scan_height": interwell_scan_height,
        }
        if indentation_limit_height is not _UNSET:
            args["indentation_limit_height"] = indentation_limit_height
        if delay_s is not _UNSET:
            args["delay_s"] = delay_s
        if method_kwargs is not _UNSET:
            args["method_kwargs"] = method_kwargs
        return self.command("scan", args)

    def pause(
        self,
        seconds: float,
        *,
        reason: Any = _UNSET,
    ) -> "ProtocolBuilder":
        args: dict[str, Any] = {"seconds": seconds}
        if reason is not _UNSET:
            args["reason"] = reason
        return self.command("pause", args)

    def position(
        self,
        name: str,
        coordinates: Iterable[float],
    ) -> "ProtocolBuilder":
        self._positions[name] = list(coordinates)
        return self

    def positions(self, positions: Mapping[str, Any]) -> "ProtocolBuilder":
        for name, coordinates in positions.items():
            self._positions[name] = deepcopy(coordinates)
        return self

    def command(
        self,
        command: str,
        args: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "ProtocolBuilder":
        command_args = dict(args or {})
        duplicate_args = set(command_args) & set(kwargs)
        if duplicate_args:
            duplicates = ", ".join(sorted(duplicate_args))
            raise ValueError(f"Duplicate arguments for {command!r}: {duplicates}")
        command_args.update(kwargs)
        self._calls.append(CommandCall(command=command, args=deepcopy(command_args)))
        return self

    def build(self, *, source_path: str | Path | None = None) -> Protocol:
        return compile_protocol(
            self._calls,
            positions=self._positions,
            source_path=source_path,
        )
