"""Shared HTTP status mapping for ``cubos.data`` fluid/tip/cap state errors.

Every ``FluidStateError``/``TipStateError``/``CapStateError`` family follows
the same naming convention (``*NotFoundError``, ``*DeckMismatchError``,
``*ReconciliationRequiredError``, ``*ConflictError``), so a single
name-suffix dispatch covers all three subsystems without importing (and
maintaining) three parallel isinstance chains.
"""

from __future__ import annotations

from fastapi import HTTPException

_CONFLICT_SUFFIXES = (
    "DeckMismatchError",
    "ReconciliationRequiredError",
    "ConflictError",
)


def map_state_exception(exc: Exception) -> HTTPException:
    """Translate a cubos.data state exception into the right HTTP status."""
    name = type(exc).__name__
    if name.endswith("NotFoundError"):
        return HTTPException(404, str(exc))
    if any(name.endswith(suffix) for suffix in _CONFLICT_SUFFIXES):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))
