"""Canonical container roles for automatic liquid-handling selection.

A container's ``role`` (``Vial.role``) is generic, machine-agnostic metadata
-- no machine-name branches ever key off of it. It exists so protocol
commands (``cubos.protocol_engine.commands._liquid_selection``) can select a
stock or waste container deterministically from ``solution=``/role alone,
without embedding a specific vial ID or legacy DB service in protocol code.

Extending the set of recognized roles is a one-line change here -- every
place that validates a ``role`` field imports ``KNOWN_CONTAINER_ROLES`` from
this module, so it stays the single source of truth.
"""

from __future__ import annotations

STOCK = "stock"
WASTE = "waste"
PROCESS = "process"
RINSE = "rinse"

KNOWN_CONTAINER_ROLES = frozenset({STOCK, WASTE, PROCESS, RINSE})

__all__ = [
    "KNOWN_CONTAINER_ROLES",
    "PROCESS",
    "RINSE",
    "STOCK",
    "WASTE",
]
