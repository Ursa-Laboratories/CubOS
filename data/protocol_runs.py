"""Persistence helpers for CubOS protocol runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deck.deck import Deck
from deck.loader import load_deck_from_yaml_safe
from gantry.loader import load_gantry_from_yaml_safe

from .data_store import DataStore


def register_deck_labware(
    data_store: DataStore,
    campaign_id: int,
    deck: Deck,
) -> None:
    """Register top-level and nested deck labware for a campaign."""
    for labware_key, labware in deck.labware.items():
        _register_labware_path(data_store, campaign_id, labware_key, labware)


def create_campaign_for_protocol_run(
    data_store: DataStore,
    *,
    gantry_path: str | Path,
    deck_path: str | Path,
    gantry_file: str,
    deck_file: str,
    protocol_file: str,
) -> int:
    """Create a campaign and register deck labware for a protocol run."""
    gantry_config = load_gantry_from_yaml_safe(gantry_path)
    deck = load_deck_from_yaml_safe(
        deck_path,
        factory_z_travel_mm=gantry_config.factory_z_travel_mm,
    )
    campaign_id = data_store.create_campaign(
        description=(
            f"Zoo protocol run: gantry={gantry_file}, deck={deck_file}, "
            f"protocol={protocol_file}"
        ),
        deck_config=deck_file,
        gantry_config=gantry_file,
        protocol_config=protocol_file,
    )
    register_deck_labware(data_store, campaign_id, deck)
    return campaign_id


def _register_labware_path(
    data_store: DataStore,
    campaign_id: int,
    labware_key: str,
    labware: Any,
) -> None:
    try:
        data_store.register_labware(campaign_id, labware_key, labware)
    except TypeError:
        pass

    for child_name, child in getattr(labware, "contained_labware", {}).items():
        _register_labware_path(
            data_store,
            campaign_id,
            f"{labware_key}.{child_name}",
            child,
        )
