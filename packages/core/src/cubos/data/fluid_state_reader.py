"""Strictly read-only access to persisted CubOS fluid state.

This reader is intended for external visualization and analysis processes. It
opens an existing database in SQLite read-only mode and never runs CubOS schema
creation or migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from .fluid_state import (
    FluidStateSnapshot,
    FluidStateSummary,
    get_fluid_snapshot,
    list_fluid_states,
)


class FluidStateReader:
    """Read fluid state from an existing CubOS database without mutating it."""

    def __init__(self, db_path: str | Path) -> None:
        resolved = Path(db_path).expanduser().resolve()
        uri = f"{resolved.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 1000")
        except BaseException:
            connection.close()
            raise
        self._conn = connection

    def list_fluid_states(self) -> list[FluidStateSummary]:
        """Return deterministic summaries for all persisted fluid states."""
        return list_fluid_states(self._conn)

    def get_fluid_snapshot(self, fluid_state_id: int) -> FluidStateSnapshot:
        """Return one deterministic JSON-ready fluid-state snapshot."""
        return get_fluid_snapshot(self._conn, fluid_state_id)

    def close(self) -> None:
        """Close the read-only SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "FluidStateReader":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


__all__ = ["FluidStateReader"]
