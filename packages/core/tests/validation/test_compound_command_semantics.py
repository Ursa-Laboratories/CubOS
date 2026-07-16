"""Static semantic validation for the Feature-05 compound liquid commands.

Covers `_validate_pipette_command`'s ``rinse_well``/``flush_pipette``/
``purge_pipette``/``clear_well`` branches: attached-tip requirement,
explicit-vs-automatic mutual exclusivity, the structural static
candidate-existence check (role/solution defined on the deck at all -- no
initial-fluids seed required), and engage/motion-bounds coverage for
explicit positions. Mirrors ``test_pipette_tip_state.py``'s deck/gantry
fixtures, extended with role/solution vials.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.protocol_engine.protocol import Protocol, ProtocolStep
from cubos.validation.protocol_semantics import validate_protocol_semantics


def _gantry(*, z_max: float = 160.0, safe_z: float = 85.0) -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=z_max,
        working_volume=WorkingVolume(
            x_min=0.0, x_max=300.0, y_min=0.0, y_max=260.0, z_min=0.0, z_max=z_max,
        ),
        safe_z=safe_z,
    )


def _pipette(*, depth: float = 5.0):
    pipette = MagicMock()
    pipette.name = "pipette"
    pipette.offset_x = 0.0
    pipette.offset_y = 0.0
    pipette.depth = depth
    return pipette


def _board() -> InstrumentedGantry:
    return InstrumentedGantry(
        controller=MagicMock(), instruments={"pipette": _pipette()},
    )


def _plate() -> WellPlate:
    return WellPlate(
        name="plate", model_name="test_plate", length=20.0, width=10.0, height=14.0,
        rows=1, columns=1,
        wells={"A1": Coordinate3D(x=90.0, y=30.0, z=12.0)},
        capacity_ul=200.0, working_volume_ul=150.0,
    )


def _stock() -> Vial:
    return Vial(
        name="stock", role="stock", solution="water",
        height=40.0, diameter=20.0,
        location=Coordinate3D(x=60.0, y=30.0, z=35.0),
        capacity_ul=1000.0, working_volume_ul=900.0,
    )


def _waste() -> Vial:
    return Vial(
        name="waste", role="waste",
        height=40.0, diameter=20.0,
        location=Coordinate3D(x=120.0, y=30.0, z=35.0),
        capacity_ul=1000.0, working_volume_ul=900.0,
    )


def _out_of_bounds_vial() -> Vial:
    return Vial(
        name="far_stock", role="stock", solution="water",
        height=40.0, diameter=20.0,
        location=Coordinate3D(x=9999.0, y=30.0, z=35.0),
        capacity_ul=1000.0, working_volume_ul=900.0,
    )


def _deck(*, with_stock=True, with_waste=True, extra=None) -> Deck:
    labware = {"plate": _plate()}
    if with_stock:
        labware["stock"] = _stock()
    if with_waste:
        labware["waste"] = _waste()
    if extra:
        labware.update(extra)
    return Deck(labware)


def _step(index: int, command: str, **args) -> ProtocolStep:
    return ProtocolStep(index=index, command_name=command, handler=lambda *a, **k: None, args=args)


def _protocol(*steps: ProtocolStep) -> Protocol:
    return Protocol(list(steps))


def _without_tip_violations(violations):
    """Drop the "no attached tip" violation for tests focused elsewhere.

    Building a real ``TipRack`` + valid ``pick_up_tip`` step is exercised
    thoroughly in ``test_pipette_tip_state.py``; these tests only care
    about the role/solution structural check and bounds coverage, which
    fire independently of tip-attachment state.
    """
    return [v for v in violations if "attached pipette tip" not in v.message]


# ─── Attached-tip requirement ───────────────────────────────────────────────


def test_rinse_well_without_tip_violates():
    protocol = _protocol(_step(0, "rinse_well", well="plate.A1", volume_ul=25.0, source="stock", waste="waste"))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("requires an attached pipette tip" in v.message for v in violations)


def test_flush_pipette_without_tip_violates():
    protocol = _protocol(_step(0, "flush_pipette", volume_ul=25.0, source="stock", waste="waste"))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("requires an attached pipette tip" in v.message for v in violations)


def test_purge_pipette_without_tip_violates():
    protocol = _protocol(_step(0, "purge_pipette", volume_ul=25.0, source="stock", waste="waste"))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("requires an attached pipette tip" in v.message for v in violations)


def test_clear_well_without_tip_violates():
    protocol = _protocol(_step(0, "clear_well", well="plate.A1", waste="waste"))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("requires an attached pipette tip" in v.message for v in violations)


# ─── Mutual exclusivity: explicit vs automatic ─────────────────────────────


def test_rinse_well_neither_source_nor_solution_violates():
    protocol = _protocol(_step(0, "rinse_well", well="plate.A1", volume_ul=25.0, waste="waste"))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("provide exactly one" in v.message for v in violations)


def test_rinse_well_both_source_and_solution_violates():
    protocol = _protocol(_step(
        0, "rinse_well", well="plate.A1", volume_ul=25.0,
        source="stock", solution="water", waste="waste",
    ))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("provide exactly one" in v.message for v in violations)


def test_flush_pipette_both_source_and_solution_violates():
    protocol = _protocol(_step(
        0, "flush_pipette", volume_ul=25.0, source="stock", solution="water", waste="waste",
    ))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("provide exactly one" in v.message for v in violations)


# ─── Structural static candidate-existence check ───────────────────────────


def test_rinse_well_unknown_solution_violates_without_needing_initial_fluids():
    protocol = _protocol(_step(
        0, "rinse_well", well="plate.A1", volume_ul=25.0, solution="acetone", waste="waste",
    ))
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert any("role='stock'" in v.message for v in violations)


def test_rinse_well_no_waste_role_on_deck_violates():
    protocol = _protocol(_step(
        0, "rinse_well", well="plate.A1", volume_ul=25.0, solution="water",
    ))
    deck = _deck(with_waste=False)
    violations = validate_protocol_semantics(protocol, _board(), deck, _gantry())
    assert any("role='waste'" in v.message for v in violations)


def test_rinse_well_matching_stock_and_waste_on_deck_passes_structurally():
    protocol = _protocol(
        _step(0, "rinse_well", well="plate.A1", volume_ul=25.0, solution="water"),
    )
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert _without_tip_violations(violations) == []


def test_clear_well_no_waste_role_on_deck_violates():
    protocol = _protocol(_step(0, "clear_well", well="plate.A1", solution="water"))
    deck = _deck(with_waste=False)
    violations = validate_protocol_semantics(protocol, _board(), deck, _gantry())
    assert any("role='waste'" in v.message for v in violations)


def test_clear_well_explicit_waste_needs_no_solution():
    protocol = _protocol(
        _step(0, "clear_well", well="plate.A1", waste="waste"),
    )
    violations = validate_protocol_semantics(protocol, _board(), _deck(), _gantry())
    assert _without_tip_violations(violations) == []


# ─── Explicit positions get full engage/motion-bounds coverage ────────────


def test_rinse_well_explicit_source_out_of_bounds_violates():
    deck = _deck(extra={"far_stock": _out_of_bounds_vial()})
    protocol = _protocol(
        _step(0, "rinse_well", well="plate.A1", volume_ul=25.0, source="far_stock", waste="waste"),
    )
    violations = validate_protocol_semantics(protocol, _board(), deck, _gantry())
    assert any("outside working volume" in v.message for v in violations)


def test_rinse_well_automatic_selection_does_not_bounds_check_the_resolved_container():
    """Documented scope gap: automatic selection isn't fed into engage
    bounds checking here (only fluid-volume simulation covers it, and only
    when an initial-fluids seed is supplied -- see
    cubos.validation.fluid_volumes). A deck whose *only* stock candidate is
    unreachable produces no motion-bounds violation at this static layer,
    even though a real run would fail catastrophically."""
    deck = Deck({"plate": _plate(), "far_stock": _out_of_bounds_vial(), "waste": _waste()})
    protocol = _protocol(
        _step(0, "rinse_well", well="plate.A1", volume_ul=25.0, solution="water"),
    )
    violations = validate_protocol_semantics(protocol, _board(), deck, _gantry())
    assert not any("outside working volume" in v.message for v in violations)


def test_clear_well_well_position_always_bounds_checked():
    deck = _deck()
    protocol = _protocol(
        _step(0, "clear_well", well="does.not.exist", waste="waste"),
    )
    violations = validate_protocol_semantics(protocol, _board(), deck, _gantry())
    assert any("cannot be resolved" in v.message for v in violations)
