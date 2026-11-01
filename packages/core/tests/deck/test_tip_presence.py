from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.tip_rack import TipRack
from cubos.deck.tip_presence import apply_durable_tip_status


def test_durable_tip_snapshot_overlays_known_slots_only():
    rack = TipRack(
        name="tips", rows=1, columns=4, pickup_z=50, tip_length=20,
        tips={f"A{i}": Coordinate3D(x=10 * i, y=20, z=50) for i in range(1, 5)},
        tip_present={"A1": False, "A2": True, "A3": True, "A4": True},
    )
    deck = Deck({"tips": rack})

    apply_durable_tip_status(deck, {"containers": [
        {"rack_key": "tips", "slot_id": "A1", "status": "available"},
        {"rack_key": "tips", "slot_id": "A2", "status": "consumed"},
        {"rack_key": "tips", "slot_id": "A3", "status": "attached"},
        {"rack_key": "tips", "slot_id": "Z9", "status": "available"},
        {"rack_key": "missing", "slot_id": "A4", "status": "consumed"},
    ]})

    assert rack.tip_present == {"A1": True, "A2": False, "A3": False, "A4": True}
