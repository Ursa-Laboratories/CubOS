"""Durable, deck-associated vial cap state for CubOS.

Mirrors ``cubos.data.tip_state``'s pattern: static vial geometry stays in
deck YAML; the mutable, durable cap state of each capper-managed vial lives
here in SQLite, hung off the *same* ``fluid_state_sessions`` row a
campaign's fluid state uses (``fluid_state_id``). A vial only participates
in durable cap-state tracking when its YAML entry sets ``capped`` (True or
False) explicitly -- a vial with ``capped`` unset is simply not
capper-managed and is skipped by seeding, ``decap``/``cap``, and
``require_uncapped`` preflight checks alike.

Unlike tip slots (which pass through a transient ``reserved`` status while a
pickup/drop is in flight), a vial's durable cap state is always exactly one
of three values: ``capped``, ``uncapped``, or ``reconciliation_required``.
There is no transient state to occupy while a decap/cap operation is
in-flight -- the container keeps its pre-operation status until
``complete_cap_operation`` (physical success) or
``mark_cap_reconciliation_required`` (uncertain outcome) resolves it. The
operation's own two-phase ``started`` -> ``applied``/
``reconciliation_required`` journal (mirroring
``fluid_state``/``tip_state``) is still what protects against concurrent or
crash-interrupted operations; the container row's ``version`` column is the
CAS anchor ``complete_cap_operation`` uses to detect a state change since
the operation began.

Cap operations share the same single-physical-action-at-a-time journal as
fluid transfers and tip operations: a pending decap/cap blocks new fluid/tip
operations and vice versa (checked via ``pending_cap_operations`` /
``fluid_state.pending_operations`` / ``tip_state.pending_tip_operations``),
since only one physical action can be in flight on the shared gantry at a
time.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Optional, TypedDict

from cubos.deck.labware.vial import Vial
from cubos.deck.labware.vial_grid import VialGrid

if TYPE_CHECKING:
    from cubos.deck.deck import Deck

_PENDING_STATUSES = ("started", "reconciliation_required")
_TERMINAL_STATUSES = ("applied", "cancelled", "reconciled")
_OPERATION_TYPES = ("decap", "cap")
_CONTAINER_STATUSES = ("capped", "uncapped", "reconciliation_required")
# operation_type -> (required prior container status, container status after
# a successfully applied operation).
_TRANSITIONS = {
    "decap": ("capped", "uncapped"),
    "cap": ("uncapped", "capped"),
}


class CapStateError(ValueError):
    """Base exception for invalid or unavailable cap state."""


class CapStateNotFoundError(CapStateError):
    """Raised when a requested cap container, operation, or session does not exist."""


class CapStateDeckMismatchError(CapStateError):
    """Raised when a session's persisted cap-container registry no longer matches the deck."""


class CapStateReconciliationRequiredError(CapStateError):
    """Raised when physical and persisted cap state may have diverged."""


class CapStateConflictError(CapStateReconciliationRequiredError):
    """Raised when a vial's cap state changed after an operation was planned."""


class CapContainerSnapshot(TypedDict):
    labware_key: str
    location_id: str
    status: str
    version: int
    updated_at: str


class CapOperationSnapshot(TypedDict):
    id: int
    operation_key: str
    operation_type: str
    labware_key: str
    location_id: str
    status: str
    campaign_id: Optional[int]
    detail: Optional[str]
    created_at: str
    updated_at: str
    applied_at: Optional[str]


class CapStateSnapshot(TypedDict):
    fluid_state_id: int
    containers: list[CapContainerSnapshot]
    operations: list[CapOperationSnapshot]


# ── Target resolution ────────────────────────────────────────────────────


def resolve_cap_target(deck: "Deck", target: str) -> tuple[str, str]:
    """Resolve *target* to a ``(labware_key, location_id)`` cap-container key.

    Only ``Vial`` and ``VialGrid`` labware are cappable; any other resolved
    labware type raises. Mirrors ``fluid_state._canonical_target``'s Vial/
    VialGrid normalization (Vial -> ``location_id=""``, VialGrid -> its
    canonical position id) but is restricted to those two types since a well
    plate well has no cap.
    """
    try:
        resolved = deck.resolve_labware_target(target)
    except KeyError as exc:
        raise CapStateError(f"Unknown cap target {target!r}: {exc}") from exc
    if isinstance(resolved.labware, Vial):
        if resolved.location_id not in (None, "", resolved.labware.name):
            raise CapStateError(
                f"Vial target {resolved.labware_key!r} does not have location "
                f"{resolved.location_id!r}."
            )
        return resolved.labware_key, ""
    if isinstance(resolved.labware, VialGrid):
        if resolved.location_id is None:
            raise CapStateError(
                f"Vial-grid target {resolved.labware_key!r} must include a "
                "position ID."
            )
        try:
            canonical_location_id = resolved.labware.canonicalize_location_id(
                resolved.location_id
            )
        except KeyError as exc:
            raise CapStateError(
                f"Unknown vial-grid position {resolved.location_id!r} on "
                f"{resolved.labware_key!r}."
            ) from exc
        return resolved.labware_key, canonical_location_id
    raise CapStateError(
        f"Target {target!r} resolves to {type(resolved.labware).__name__}, "
        "not a cappable Vial or VialGrid position."
    )


# ── Seeding & resume verification ───────────────────────────────────────────


def seed_cap_state(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    deck: "Deck",
) -> None:
    """Insert one ``cap_containers`` row per vial that declares ``capped``.

    Skips every vial whose YAML entry leaves ``capped`` unset -- those are
    not capper-managed. Initial status is taken from ``capped`` at session
    create time only; the DB row is the durable source of truth afterward.
    """
    for labware_key, location_id, capped in _iter_capped_vials(deck):
        status = "capped" if capped else "uncapped"
        connection.execute(
            "INSERT INTO cap_containers (fluid_state_id, labware_key, "
            "location_id, status) VALUES (?, ?, ?, ?)",
            (fluid_state_id, labware_key, location_id, status),
        )


def verify_cap_container_registry(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    deck: "Deck",
) -> None:
    """Verify the persisted cap-container registry still matches the current deck."""
    expected = {
        (labware_key, location_id)
        for labware_key, location_id, _capped in _iter_capped_vials(deck)
    }
    actual = {
        (row[0], row[1])
        for row in connection.execute(
            "SELECT labware_key, location_id FROM cap_containers "
            "WHERE fluid_state_id = ?",
            (fluid_state_id,),
        )
    }
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise CapStateDeckMismatchError(
            f"Cap state {fluid_state_id} cap-container registry does not "
            f"match its current deck (missing={missing}, unexpected={unexpected})."
        )


def pending_cap_operations(
    connection: sqlite3.Connection,
    fluid_state_id: int,
) -> list[tuple[str, str]]:
    """Return ``(operation_key, status)`` for every pending cap operation."""
    return connection.execute(
        "SELECT operation_key, status FROM cap_operations WHERE fluid_state_id = ? "
        "AND status IN (?, ?) ORDER BY id",
        (fluid_state_id, *_PENDING_STATUSES),
    ).fetchall()


def get_cap_state(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    labware_key: str,
    location_id: str,
) -> Optional[str]:
    """Return one vial's durable cap status, or ``None`` if not capper-managed."""
    row = connection.execute(
        "SELECT status FROM cap_containers WHERE fluid_state_id = ? "
        "AND labware_key = ? AND location_id = ?",
        (fluid_state_id, labware_key, location_id),
    ).fetchone()
    return row[0] if row is not None else None


def get_cap_snapshot(
    connection: sqlite3.Connection,
    fluid_state_id: int,
) -> CapStateSnapshot:
    """Return a deterministic JSON-ready snapshot of one session's cap state."""
    with _read_transaction(connection):
        exists = connection.execute(
            "SELECT 1 FROM fluid_state_sessions WHERE id = ?", (fluid_state_id,),
        ).fetchone()
        if exists is None:
            raise CapStateNotFoundError(f"Fluid state {fluid_state_id} not found.")

        container_rows = connection.execute(
            "SELECT labware_key, location_id, status, version, updated_at "
            "FROM cap_containers WHERE fluid_state_id = ? "
            "ORDER BY labware_key, location_id",
            (fluid_state_id,),
        ).fetchall()
        operation_rows = connection.execute(
            "SELECT id, operation_key, operation_type, labware_key, location_id, "
            "status, campaign_id, detail, created_at, updated_at, applied_at "
            "FROM cap_operations WHERE fluid_state_id = ? ORDER BY id",
            (fluid_state_id,),
        ).fetchall()

    containers: list[CapContainerSnapshot] = [
        {
            "labware_key": row[0],
            "location_id": row[1],
            "status": row[2],
            "version": int(row[3]),
            "updated_at": row[4],
        }
        for row in container_rows
    ]
    operations: list[CapOperationSnapshot] = [
        {
            "id": int(row[0]),
            "operation_key": row[1],
            "operation_type": row[2],
            "labware_key": row[3],
            "location_id": row[4],
            "status": row[5],
            "campaign_id": row[6],
            "detail": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "applied_at": row[10],
        }
        for row in operation_rows
    ]
    return {
        "fluid_state_id": fluid_state_id,
        "containers": containers,
        "operations": operations,
    }


# ── decap / cap journal ──────────────────────────────────────────────────


def begin_cap_operation(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    operation_key: str,
    operation_type: str,
    labware_key: str,
    location_id: str,
    campaign_id: int | None = None,
) -> bool:
    """Preflight and journal a decap/cap operation before physical actuation.

    Returns ``should_execute``: ``False`` means this exact campaign step was
    already applied and must not be replayed.
    """
    _validate_operation_key(operation_key)
    if operation_type not in _OPERATION_TYPES:
        raise CapStateError(
            f"operation_type must be one of {_OPERATION_TYPES}, got "
            f"{operation_type!r}."
        )
    required_status, _next_status = _TRANSITIONS[operation_type]
    with _immediate_transaction(connection):
        _require_session(connection, fluid_state_id)
        _require_campaign_link(connection, fluid_state_id, campaign_id)

        existing = _check_existing_cap_operation(
            connection,
            operation_key,
            fluid_state_id=fluid_state_id,
            operation_type=operation_type,
            labware_key=labware_key,
            location_id=location_id,
            campaign_id=campaign_id,
        )
        if existing is not None:
            return False

        _require_no_pending_cap_operation(connection, fluid_state_id, operation_key)
        _require_no_pending_fluid_operation(connection, fluid_state_id, operation_key)

        container = _cap_container_row(connection, fluid_state_id, labware_key, location_id)
        if container["status"] == "reconciliation_required":
            raise CapStateReconciliationRequiredError(
                f"Cap state for {labware_key}.{location_id} requires operator "
                "reconciliation before it can be decapped/capped again."
            )
        if container["status"] != required_status:
            raise CapStateError(
                f"Cannot {operation_type} {labware_key}.{location_id}: current "
                f"cap state is {container['status']!r}, expected "
                f"{required_status!r}."
            )

        try:
            connection.execute(
                "INSERT INTO cap_operations (fluid_state_id, operation_key, "
                "operation_type, labware_key, location_id, previous_status, "
                "container_version, status, campaign_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)",
                (
                    fluid_state_id,
                    operation_key,
                    operation_type,
                    labware_key,
                    location_id,
                    container["status"],
                    container["version"],
                    campaign_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if pending_cap_operations(connection, fluid_state_id):
                raise CapStateReconciliationRequiredError(
                    f"Fluid state {fluid_state_id} already has a pending cap "
                    "operation."
                ) from exc
            raise
        _touch_session(connection, fluid_state_id)
    return True


def complete_cap_operation(connection: sqlite3.Connection, operation_key: str) -> None:
    """Atomically apply a started decap/cap: container flips to its next status."""
    with _immediate_transaction(connection):
        operation = _cap_operation_row(connection, operation_key)
        if operation["status"] == "applied":
            return
        if operation["status"] != "started":
            raise CapStateReconciliationRequiredError(
                f"Operation {operation_key!r} is {operation['status']} and "
                "cannot be applied automatically."
            )
        _apply_cap_operation(connection, operation, allowed_statuses=("started",))


# ── Reconciliation ───────────────────────────────────────────────────────


def mark_cap_reconciliation_required(
    connection: sqlite3.Connection,
    operation_key: str,
    detail: str,
) -> None:
    """Mark a non-applied cap operation as requiring operator reconciliation."""
    if not isinstance(detail, str) or not detail.strip():
        raise CapStateError("Reconciliation detail must be a non-empty string.")
    with _immediate_transaction(connection):
        operation = _cap_operation_row(connection, operation_key)
        if operation["status"] in _TERMINAL_STATUSES:
            raise CapStateError(
                f"Terminal operation {operation_key!r} ({operation['status']}) "
                "cannot require reconciliation."
            )
        if operation["status"] == "reconciliation_required":
            return

        cursor = connection.execute(
            "UPDATE cap_operations SET status = 'reconciliation_required', "
            "detail = ?, updated_at = datetime('now') "
            "WHERE operation_key = ? AND status = 'started'",
            (detail, operation_key),
        )
        if cursor.rowcount != 1:
            raise CapStateConflictError(
                f"Operation {operation_key!r} changed while marking "
                "reconciliation."
            )
        # Deliberately no version bump here (mirrors
        # tip_state.mark_tip_reconciliation_required): `container_version` on
        # the operation row remains the CAS anchor `_apply_cap_operation`/
        # `_revert_cap_operation`/`_reconcile_cap_operation` use to detect
        # out-of-band changes.
        connection.execute(
            "UPDATE cap_containers SET status = 'reconciliation_required', "
            "updated_at = datetime('now') "
            "WHERE fluid_state_id = ? AND labware_key = ? AND location_id = ?",
            (
                operation["fluid_state_id"],
                operation["labware_key"],
                operation["location_id"],
            ),
        )
        _touch_session(connection, operation["fluid_state_id"])


def resolve_cap_operation(
    connection: sqlite3.Connection,
    operation_key: str,
    resolution: str,
    *,
    detail: str,
    final_status: str | None = None,
) -> None:
    """Resolve an uncertain cap operation with an auditable operator decision.

    ``resolution`` accepts ``applied``, ``not_applied``/``cancelled``, or
    ``partial``/``reconciled``. ``reconciled`` requires an explicit
    *final_status* of ``capped`` or ``uncapped``.
    """
    if not isinstance(detail, str) or not detail.strip():
        raise CapStateError("Operator resolution detail must be a non-empty string.")
    normalized = {
        "applied": "applied",
        "not_applied": "cancelled",
        "not-applied": "cancelled",
        "cancelled": "cancelled",
        "partial": "reconciled",
        "reconciled": "reconciled",
    }.get(resolution)
    if normalized is None:
        raise CapStateError(
            "resolution must be applied, not_applied/cancelled, or "
            "partial/reconciled."
        )

    with _immediate_transaction(connection):
        operation = _cap_operation_row(connection, operation_key)
        if operation["status"] in _TERMINAL_STATUSES:
            if operation["status"] == normalized:
                return
            raise CapStateError(
                f"Operation {operation_key!r} is already terminal with status "
                f"{operation['status']}."
            )
        if operation["status"] not in _PENDING_STATUSES:
            raise CapStateError(
                f"Operation {operation_key!r} cannot be resolved from status "
                f"{operation['status']}."
            )

        if normalized == "applied":
            if final_status is not None:
                raise CapStateError("Applied resolution does not accept final_status.")
            _apply_cap_operation(connection, operation, allowed_statuses=_PENDING_STATUSES)
            return

        if normalized == "cancelled":
            if final_status is not None:
                raise CapStateError("Cancelled resolution does not accept final_status.")
            _revert_cap_operation(connection, operation, detail=detail)
            return

        if final_status not in ("capped", "uncapped"):
            raise CapStateError(
                "Partial reconciliation requires final_status of 'capped' or "
                "'uncapped'."
            )
        _reconcile_cap_operation(
            connection, operation, final_status=final_status, detail=detail,
        )


# ── Internal helpers ─────────────────────────────────────────────────────


def _iter_capped_vials(deck: "Deck") -> Iterator[tuple[str, str, bool]]:
    """Yield ``(labware_key, location_id, capped)`` for every declared vial.

    Skips vials whose ``capped`` field is unset (``None``). Iterates
    ``deck.volume_labware`` -- the same canonical, holder-flattened registry
    ``fluid_state._iter_volume_labware`` uses -- so top-level and nested
    (holder-contained) vials are both covered.
    """
    for labware_key, labware in sorted(deck.volume_labware.items()):
        if isinstance(labware, Vial):
            if labware.capped is not None:
                yield labware_key, "", labware.capped
        elif isinstance(labware, VialGrid):
            for location_id, vial in sorted(labware.vials.items()):
                if vial.capped is not None:
                    yield labware_key, location_id, vial.capped


def _apply_cap_operation(
    connection: sqlite3.Connection,
    operation: dict[str, Any],
    *,
    allowed_statuses: tuple[str, ...],
) -> None:
    fluid_state_id = int(operation["fluid_state_id"])
    _next_status = _TRANSITIONS[operation["operation_type"]][1]
    container = _cap_container_row(
        connection, fluid_state_id, operation["labware_key"], operation["location_id"],
    )
    if int(container["version"]) != int(operation["container_version"]):
        raise CapStateConflictError(
            f"Cap state for {operation['labware_key']}.{operation['location_id']} "
            f"changed after operation {operation['operation_key']!r} began; "
            "reconciliation required."
        )
    cursor = connection.execute(
        "UPDATE cap_containers SET status = ?, version = version + 1, "
        "updated_at = datetime('now') WHERE id = ? AND version = ?",
        (_next_status, container["id"], container["version"]),
    )
    if cursor.rowcount != 1:
        raise CapStateConflictError(
            f"Cap state for {operation['labware_key']}.{operation['location_id']} "
            f"changed while applying operation {operation['operation_key']!r}."
        )
    _set_cap_operation_terminal(
        connection, operation, status="applied", detail=None,
        allowed_statuses=allowed_statuses,
    )


def _revert_cap_operation(
    connection: sqlite3.Connection,
    operation: dict[str, Any],
    *,
    detail: str,
) -> None:
    fluid_state_id = int(operation["fluid_state_id"])
    container = _cap_container_row(
        connection, fluid_state_id, operation["labware_key"], operation["location_id"],
    )
    cursor = connection.execute(
        "UPDATE cap_containers SET status = ?, version = version + 1, "
        "updated_at = datetime('now') WHERE id = ? AND version = ?",
        (operation["previous_status"], container["id"], container["version"]),
    )
    if cursor.rowcount != 1:
        raise CapStateConflictError(
            f"Cap state for {operation['labware_key']}.{operation['location_id']} "
            f"changed while cancelling operation {operation['operation_key']!r}."
        )
    _set_cap_operation_terminal(
        connection, operation, status="cancelled", detail=detail,
        allowed_statuses=_PENDING_STATUSES,
    )


def _reconcile_cap_operation(
    connection: sqlite3.Connection,
    operation: dict[str, Any],
    *,
    final_status: str,
    detail: str,
) -> None:
    fluid_state_id = int(operation["fluid_state_id"])
    container = _cap_container_row(
        connection, fluid_state_id, operation["labware_key"], operation["location_id"],
    )
    cursor = connection.execute(
        "UPDATE cap_containers SET status = ?, version = version + 1, "
        "updated_at = datetime('now') WHERE id = ? AND version = ?",
        (final_status, container["id"], container["version"]),
    )
    if cursor.rowcount != 1:
        raise CapStateConflictError(
            f"Cap state for {operation['labware_key']}.{operation['location_id']} "
            f"changed while reconciling operation {operation['operation_key']!r}."
        )
    _set_cap_operation_terminal(
        connection, operation, status="reconciled", detail=detail,
        allowed_statuses=_PENDING_STATUSES,
    )


def _check_existing_cap_operation(
    connection: sqlite3.Connection,
    operation_key: str,
    *,
    fluid_state_id: int,
    operation_type: str,
    labware_key: str,
    location_id: str,
    campaign_id: int | None,
) -> dict[str, Any] | None:
    cursor = connection.execute(
        "SELECT fluid_state_id, operation_type, status, labware_key, "
        "location_id, campaign_id FROM cap_operations WHERE operation_key = ?",
        (operation_key,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    if int(row[0]) != fluid_state_id:
        raise CapStateError(
            f"Operation key {operation_key!r} belongs to fluid state {row[0]}."
        )
    exact = (
        row[1] == operation_type
        and row[3] == labware_key
        and row[4] == location_id
        and row[5] == campaign_id
    )
    if row[2] == "applied" and exact:
        return {"status": row[2]}
    if row[2] == "applied":
        raise CapStateError(
            f"Applied operation key {operation_key!r} was reused with "
            f"different {operation_type} parameters."
        )
    if row[2] in _PENDING_STATUSES:
        raise CapStateReconciliationRequiredError(
            f"Operation {operation_key!r} is {row[2]}; reconcile physical cap "
            "state before continuing."
        )
    raise CapStateError(
        f"Operation {operation_key!r} was operator-resolved as {row[2]}; start "
        "a new campaign operation rather than reusing its key."
    )


def _require_no_pending_cap_operation(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    operation_key: str,
) -> None:
    pending = pending_cap_operations(connection, fluid_state_id)
    if pending:
        details = ", ".join(f"{key} ({status})" for key, status in pending)
        raise CapStateReconciliationRequiredError(
            f"Fluid state {fluid_state_id} cannot start cap operation "
            f"{operation_key!r} while these cap operations require physical "
            f"reconciliation: {details}."
        )


def _require_no_pending_fluid_operation(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    operation_key: str,
) -> None:
    from . import fluid_state as _fluid_state
    from . import tip_state as _tip_state

    pending = [
        *_fluid_state.pending_operations(connection, fluid_state_id),
        *_tip_state.pending_tip_operations(connection, fluid_state_id),
    ]
    if pending:
        details = ", ".join(f"{key} ({status})" for key, status in pending)
        raise CapStateReconciliationRequiredError(
            f"Fluid state {fluid_state_id} cannot start cap operation "
            f"{operation_key!r} while these fluid/tip operations require "
            f"physical reconciliation: {details}."
        )


def _require_session(connection: sqlite3.Connection, fluid_state_id: int) -> None:
    row = connection.execute(
        "SELECT 1 FROM fluid_state_sessions WHERE id = ?", (fluid_state_id,),
    ).fetchone()
    if row is None:
        raise CapStateNotFoundError(f"Fluid state {fluid_state_id} not found.")


def _require_campaign_link(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    campaign_id: int | None,
) -> None:
    if campaign_id is None:
        raise CapStateError(
            "Durable cap operations require a campaign_id linked to the same "
            "fluid state."
        )
    row = connection.execute(
        "SELECT fluid_state_id FROM campaigns WHERE id = ?", (campaign_id,),
    ).fetchone()
    if row is None:
        raise CapStateError(f"Campaign {campaign_id} not found.")
    if row[0] is None:
        raise CapStateError(f"Campaign {campaign_id} is not linked to a fluid state.")
    if int(row[0]) != fluid_state_id:
        raise CapStateError(
            f"Campaign {campaign_id} is linked to fluid state {row[0]}, not "
            f"{fluid_state_id}."
        )


def _cap_container_row(
    connection: sqlite3.Connection,
    fluid_state_id: int,
    labware_key: str,
    location_id: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        "SELECT id, labware_key, location_id, status, version "
        "FROM cap_containers WHERE fluid_state_id = ? AND labware_key = ? "
        "AND location_id = ?",
        (fluid_state_id, labware_key, location_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise CapStateError(
            f"Vial {labware_key}.{location_id} has no durable cap state in "
            f"state {fluid_state_id}; add `capped: true`/`capped: false` to "
            "its deck YAML entry to opt it into cap-state tracking."
        )
    return dict(zip((column[0] for column in cursor.description), row))


def _cap_operation_row(
    connection: sqlite3.Connection,
    operation_key: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        "SELECT id, fluid_state_id, operation_key, operation_type, labware_key, "
        "location_id, previous_status, container_version, status, campaign_id, "
        "detail FROM cap_operations WHERE operation_key = ?",
        (operation_key,),
    )
    row = cursor.fetchone()
    if row is None:
        raise CapStateNotFoundError(f"Cap operation {operation_key!r} not found.")
    return dict(zip((column[0] for column in cursor.description), row))


def _set_cap_operation_terminal(
    connection: sqlite3.Connection,
    operation: dict[str, Any],
    *,
    status: str,
    detail: str | None,
    allowed_statuses: tuple[str, ...],
) -> None:
    placeholders = ", ".join("?" for _ in allowed_statuses)
    cursor = connection.execute(
        "UPDATE cap_operations SET status = ?, detail = COALESCE(?, detail), "
        "applied_at = CASE WHEN ? = 'applied' THEN datetime('now') ELSE "
        "applied_at END, updated_at = datetime('now') WHERE id = ? AND status "
        f"IN ({placeholders})",
        (status, detail, status, operation["id"], *allowed_statuses),
    )
    if cursor.rowcount != 1:
        raise CapStateConflictError(
            f"Operation {operation['operation_key']!r} changed while "
            "resolving it."
        )
    _touch_session(connection, operation["fluid_state_id"])


def _touch_session(connection: sqlite3.Connection, fluid_state_id: int) -> None:
    connection.execute(
        "UPDATE fluid_state_sessions SET updated_at = datetime('now') WHERE id = ?",
        (fluid_state_id,),
    )


def _validate_operation_key(operation_key: str) -> None:
    if not isinstance(operation_key, str) or not operation_key.strip():
        raise CapStateError("operation_key must be a non-empty string.")


@contextmanager
def _read_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Pin all queries in a logical snapshot to one SQLite read view."""
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        yield
    finally:
        if owns_transaction:
            connection.rollback()


@contextmanager
def _immediate_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Acquire SQLite's writer reservation before reading mutable cap state."""
    if connection.in_transaction:
        raise CapStateError(
            "Cap-state mutation cannot start inside an existing SQLite "
            "transaction; commit or roll back that transaction first."
        )
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


__all__ = [
    "CapContainerSnapshot",
    "CapOperationSnapshot",
    "CapStateConflictError",
    "CapStateDeckMismatchError",
    "CapStateError",
    "CapStateNotFoundError",
    "CapStateReconciliationRequiredError",
    "CapStateSnapshot",
    "begin_cap_operation",
    "complete_cap_operation",
    "get_cap_snapshot",
    "get_cap_state",
    "mark_cap_reconciliation_required",
    "pending_cap_operations",
    "resolve_cap_operation",
    "resolve_cap_target",
    "seed_cap_state",
    "verify_cap_container_registry",
]
