"""Manual corrections to estimated contents and optional operation notes."""

from __future__ import annotations

import sqlite3

from .fluid_state import (
    FluidStateConflictError,
    _container_row,
    _decode_composition,
    _finite_nonnegative,
    _format_target,
    _immediate_transaction,
    _normalize_composition,
    _require_no_pending_operation,
    _require_state,
    _update_container,
    _validate_replacement_volume,
)


def correct_fluid_volume(
    connection: sqlite3.Connection, fluid_state_id: int, labware_key: str,
    location_id: str, volume_ul: float, expected_version: int,
) -> None:
    """Set a measured volume, preserving existing mixture proportions."""
    volume = _finite_nonnegative(volume_ul, "volume_ul")
    with _immediate_transaction(connection):
        _require_state(connection, fluid_state_id)
        _require_no_pending_operation(connection, fluid_state_id, "volume correction")
        row = _container_row(connection, fluid_state_id, labware_key, location_id)
        if row["version"] != expected_version:
            raise FluidStateConflictError("Container changed; refresh before saving the volume.")
        target = _format_target(labware_key, location_id)
        _validate_replacement_volume(row, volume, target, action="Correction")
        previous = float(row["current_volume_ul"])
        composition = _decode_composition(row["composition_json"], previous, target=target)
        replacement = (
            _normalize_composition(
                {name: amount * volume / previous for name, amount in composition.items()}, volume,
            )
            if previous > 0 else _normalize_composition(None, volume)
        )
        _update_container(connection, row, volume, replacement, operation_key="volume correction")
        connection.execute(
            "UPDATE fluid_state_sessions SET updated_at = datetime('now') WHERE id = ?",
            (fluid_state_id,),
        )


def clear_operation_notes(connection: sqlite3.Connection, fluid_state_id: int) -> None:
    """Clear free-text notes without changing journal identities or outcomes."""
    with _immediate_transaction(connection):
        _require_state(connection, fluid_state_id)
        for table in ("fluid_operations", "tip_operations", "cap_operations"):
            connection.execute(
                f"UPDATE {table} SET detail = NULL WHERE fluid_state_id = ?",
                (fluid_state_id,),
            )
