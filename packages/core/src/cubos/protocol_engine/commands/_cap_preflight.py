"""``require_uncapped`` preflight for liquid-handling commands.

Explicit, opt-in preflight only -- this module never moves the gantry and
never injects a `decap` step. A protocol author names which deck targets
must be durably tracked ``uncapped`` before a `transfer`/compound command's
motion begins (typically the same strings already passed as `source`/
`destination`/`waste`); if any named target is `capped` or its cap state is
unknown (`reconciliation_required`, or the vial was never registered for
cap tracking), the command fails before any motion or fluid-state
journaling with a clear, actionable error naming exactly which vial needs
`decap` first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from ..errors import ProtocolExecutionError

if TYPE_CHECKING:
    from ..runtime import ProtocolContext


def require_uncapped(
    context: "ProtocolContext",
    positions: Optional[Iterable[str]],
    *,
    command_label: str,
) -> None:
    """Raise unless every position in *positions* is durably tracked uncapped.

    A no-op when *positions* is ``None``/empty. Vials never registered for
    cap-state tracking (no `capped:` field in their deck YAML) are silently
    accepted -- `require_uncapped` only constrains capper-managed vessels.
    """
    if not positions:
        return
    if context.fluid_state_id is None or context.data_store is None:
        raise ProtocolExecutionError(
            f"{command_label} `require_uncapped` was given but durable fluid "
            "tracking (context.fluid_state_id/data_store) is not active -- "
            "there is no durable cap state to check."
        )
    for position in positions:
        try:
            target = context.deck.resolve_labware_target(position)
        except (KeyError, ValueError) as exc:
            raise ProtocolExecutionError(
                f"{command_label} require_uncapped: cannot resolve {position!r} "
                f"on the deck: {exc}"
            ) from exc
        location_id = target.location_id or ""
        try:
            status = context.data_store.get_cap_state(
                context.fluid_state_id, target.labware_key, location_id,
            )
        except Exception as exc:
            raise ProtocolExecutionError(
                f"{command_label} require_uncapped: failed to read cap state "
                f"for {position!r}: {type(exc).__name__}: {exc}"
            ) from exc
        if status is None:
            continue
        if status != "uncapped":
            raise ProtocolExecutionError(
                f"{command_label} requires {position!r} to be uncapped before "
                f"motion, but its durable cap state is {status!r}. Run `decap` "
                f"on {position!r} first."
            )
