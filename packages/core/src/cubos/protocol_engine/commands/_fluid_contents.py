"""Resolve authoritative contents for measurements in tracked fluid runs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping

from cubos.deck.deck import DeckLabwareTarget

from ..errors import ProtocolExecutionError

if TYPE_CHECKING:
    from ..runtime import ProtocolContext


FluidContents = list[dict[str, Any]]
FluidContentsIndex = dict[tuple[str, str], FluidContents]


def _target_identity(target: DeckLabwareTarget) -> tuple[str, str]:
    return target.labware_key, target.location_id or ""


def resolve_measurement_target(
    context: ProtocolContext,
    position: str,
) -> DeckLabwareTarget:
    """Resolve a persistence target through the deck's canonical registry."""
    try:
        return context.deck.resolve_labware_target(position)
    except (KeyError, ValueError) as exc:
        raise ProtocolExecutionError(
            f"Cannot resolve measurement target {position!r}: {exc}"
        ) from exc


def tracked_fluid_contents(
    context: ProtocolContext,
    targets: Iterable[DeckLabwareTarget],
) -> FluidContentsIndex | None:
    """Snapshot authoritative contents for one measure or scan command.

    ``None`` means durable fluid tracking is not active and callers should use
    the legacy campaign labware ledger.  An active fluid-state context is
    checked before motion so a missing state, campaign mismatch, duplicate
    container, or absent target cannot leave an unpersisted physical
    measurement behind.

    The returned list shape is compatible with existing experiment ``contents``
    consumers.  Each authoritative composition component becomes one
    ``{"source": ..., "volume_ul": ...}`` entry.
    """
    fluid_state_id = context.fluid_state_id
    if fluid_state_id is None:
        return None

    missing = []
    if context.data_store is None:
        missing.append("data_store")
    if context.campaign_id is None:
        missing.append("campaign_id")
    if missing:
        raise ProtocolExecutionError(
            "Durable fluid measurement context is incomplete: fluid_state_id "
            f"is set but {', '.join(missing)} is missing. No motion was attempted."
        )

    try:
        linked_state_id = context.data_store.get_campaign_fluid_state_id(
            context.campaign_id,
        )
        if linked_state_id != fluid_state_id:
            raise ValueError(
                f"campaign {context.campaign_id} is linked to fluid state "
                f"{linked_state_id!r}, not {fluid_state_id}"
            )
        snapshot = context.data_store.get_fluid_snapshot(fluid_state_id)
    except Exception as exc:
        raise ProtocolExecutionError(
            "Cannot read authoritative fluid contents for measurement: "
            f"{type(exc).__name__}: {exc}. No motion was attempted."
        ) from exc

    if not isinstance(snapshot, Mapping):
        raise ProtocolExecutionError(
            "Authoritative fluid state is corrupt: snapshot must be a mapping. "
            "No motion was attempted."
        )
    containers = snapshot.get("containers")
    if not isinstance(containers, list):
        raise ProtocolExecutionError(
            "Authoritative fluid state is corrupt: snapshot containers must be "
            "a list. No motion was attempted."
        )

    # ``get_fluid_snapshot`` is the public integrity boundary: it validates
    # decoded composition and volume totals. This command layer only indexes
    # canonical identities and adapts the composition to the established
    # experiment-contents shape.
    container_index: FluidContentsIndex = {}
    try:
        for container in containers:
            identity = (container["labware_key"], container["location_id"])
            composition = container["composition"]
            if identity in container_index:
                raise ValueError(f"duplicate container identity {identity!r}")
            if not isinstance(composition, Mapping):
                raise TypeError(f"composition for {identity!r} is not a mapping")
            container_index[identity] = [
                {"source": component, "volume_ul": float(amount_ul)}
                for component, amount_ul in sorted(composition.items())
                if float(amount_ul) > 0
            ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolExecutionError(
            "Authoritative fluid state is corrupt: invalid container snapshot "
            f"({type(exc).__name__}: {exc}). No motion was attempted."
        ) from exc

    requested: FluidContentsIndex = {}
    for target in targets:
        identity = _target_identity(target)
        try:
            requested[identity] = container_index[identity]
        except KeyError as exc:
            target_name = (
                f"{target.labware_key}.{target.location_id}"
                if target.location_id
                else target.labware_key
            )
            raise ProtocolExecutionError(
                f"Authoritative fluid state {fluid_state_id} has no container "
                f"for measurement target {target_name!r}. No motion was attempted."
            ) from exc
    return requested


def contents_for_target(
    contents_index: FluidContentsIndex,
    target: DeckLabwareTarget,
) -> FluidContents:
    """Return preflighted tracked contents for a canonical target."""
    return contents_index[_target_identity(target)]
