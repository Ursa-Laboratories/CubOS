from __future__ import annotations

from textwrap import dedent

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.protocol_engine.builder import ProtocolBuilder
from cubos.protocol_engine.engage import (
    EngagePositionError,
    resolve_engage_height,
    resolve_step_args,
)
from cubos.protocol_engine.errors import ProtocolExecutionError, ProtocolLoaderError
from cubos.protocol_engine.runtime import ProtocolContext
from cubos.protocol_engine.setup_validator import run_setup_validation

from ..validation.test_fluid_volumes import (
    VALIDATOR_DECK_YAML,
    VALIDATOR_FLUIDS_YAML,
    VALIDATOR_GANTRY_YAML,
)


def _deck(vial_depth=15.0, plate_depth=10.0, other_depth=15.0) -> Deck:
    def vial(name, x, depth):
        return Vial(
            name=name, height=40.0, diameter=20.0, inner_depth=depth,
            location=Coordinate3D(x=x, y=5.0, z=50.0),
            capacity_ul=2000.0, working_volume_ul=1500.0,
        )

    plate = WellPlate(
        name="plate", model_name="t", rows=1, columns=2,
        wells={"A1": Coordinate3D(x=70.0, y=20.0, z=30.0),
               "A2": Coordinate3D(x=79.0, y=20.0, z=30.0)},
        well_depth=plate_depth,
    )
    bare = WellPlate(
        name="bare", model_name="t", rows=1, columns=1,
        wells={"A1": Coordinate3D(x=10.0, y=20.0, z=30.0)},
    )
    return Deck({
        "v": vial("v", 5.0, vial_depth), "w": vial("w", 30.0, other_depth),
        "plate": plate, "bare": bare,
    })


def test_bottom_offset_becomes_rim_relative_height():
    deck = _deck()
    assert resolve_engage_height(
        deck, "v", height=0.0, from_bottom_mm=2.0, from_top_mm=None,
    ) == pytest.approx(-13.0)
    assert resolve_engage_height(
        deck, "plate.A1", height=None, from_bottom_mm=1.5, from_top_mm=None,
    ) == pytest.approx(-8.5)


def test_top_offset_is_the_rim_relative_height():
    assert resolve_engage_height(
        _deck(), "v", height=0.0, from_bottom_mm=None, from_top_mm=-3.0,
    ) == -3.0


def test_unused_opt_in_returns_height_untouched():
    assert resolve_engage_height(
        None, "v", height=4.0, from_bottom_mm=None, from_top_mm=None,
    ) == 4.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"from_bottom_mm": 1.0, "from_top_mm": -1.0}, "only one"),
        ({"from_bottom_mm": 1.0, "height": 2.0}, "do not combine"),
        ({"from_bottom_mm": -0.5}, ">= 0"),
        ({"from_bottom_mm": float("nan")}, "finite"),
        ({"from_top_mm": True}, "finite"),
    ],
)
def test_invalid_combinations_rejected(kwargs, match):
    base = {"height": 0.0, "from_bottom_mm": None, "from_top_mm": None}
    with pytest.raises(EngagePositionError, match=match):
        resolve_engage_height(_deck(), "v", **{**base, **kwargs})


def test_missing_depth_and_unsupported_labware_are_named():
    deck = _deck()
    with pytest.raises(EngagePositionError, match="no well_depth"):
        resolve_engage_height(deck, "bare.A1", height=0.0, from_bottom_mm=1.0, from_top_mm=None)
    with pytest.raises(EngagePositionError, match="cannot resolve"):
        resolve_engage_height(deck, "ghost", height=0.0, from_bottom_mm=1.0, from_top_mm=None)
    no_depth = Deck({"v": Vial(
        name="v", height=40.0, diameter=20.0, location=Coordinate3D(x=0, y=0, z=50.0),
        capacity_ul=100.0, working_volume_ul=50.0,
    )})
    with pytest.raises(EngagePositionError, match="inner_depth"):
        resolve_engage_height(no_depth, "v", height=0.0, from_bottom_mm=1.0, from_top_mm=None)


def test_step_args_for_each_command_shape():
    deck = _deck()
    assert resolve_step_args(
        "aspirate", {"position": "v", "volume_ul": 5.0, "from_bottom_mm": 2.0}, deck,
    ) == {"position": "v", "volume_ul": 5.0, "height": -13.0}
    out = resolve_step_args("transfer", {
        "source": "v", "destination": "plate.A1", "volume_ul": 5.0,
        "source_from_bottom_mm": 1.0, "destination_from_top_mm": -2.0,
    }, deck)
    assert out["source_height"] == -14.0 and out["destination_height"] == -2.0
    assert not any("from_" in key for key in out)
    out = resolve_step_args("serial_transfer", {
        "source": "v", "plate": "plate", "axis": "A", "volumes": [1.0],
        "destination_from_bottom_mm": 1.0,
    }, deck)
    assert out["destination_height"] == -9.0
    out = resolve_step_args("multi_dispense", {
        "source": "v", "destinations": ["v", "w"], "volumes": [1.0, 1.0],
        "destination_from_bottom_mm": 1.0,
    }, deck)
    assert out["destination_height"] == -14.0


def test_multi_dispense_destinations_with_different_depths_rejected():
    with pytest.raises(EngagePositionError, match="different depths"):
        resolve_step_args("multi_dispense", {
            "source": "v", "destinations": ["v", "w"], "volumes": [1.0, 1.0],
            "destination_from_bottom_mm": 1.0,
        }, _deck(other_depth=12.0))


def test_commands_without_opt_in_pass_through_unchanged():
    args = {"position": "v", "volume_ul": 5.0, "height": 1.0}
    assert resolve_step_args("aspirate", args, None) == args
    assert resolve_step_args("home", {}, None) == {}


def test_protocol_resolution_is_idempotent_and_leaves_plain_protocols_alone():
    deck = _deck()
    plain = ProtocolBuilder().add_command("pause", seconds=1.0).build()
    assert plain.with_resolved_engage_positions(deck) is plain
    protocol = ProtocolBuilder().add_command(
        "aspirate", position="v", volume_ul=5.0, from_bottom_mm=2.0,
    ).build()
    resolved = protocol.with_resolved_engage_positions(deck)
    assert resolved.steps[0].args["height"] == -13.0
    assert "from_bottom_mm" not in resolved.steps[0].args
    assert resolved.with_resolved_engage_positions(deck) is resolved
    assert protocol.steps[0].args["from_bottom_mm"] == 2.0


class _Pipette:
    def __init__(self):
        self.attached_tip_extension = 10.0
        self.calls = []

    def aspirate(self, volume_ul, speed=50.0):
        self.calls.append(("aspirate", volume_ul))


class _Gantry:
    def __init__(self):
        self.moves = []

    def move(self, instrument, position):
        self.moves.append(position)


def _context(deck, planning=False):
    class _PlanDeck(Deck):
        @property
        def planning_enabled(self):
            return planning

    plan_deck = _PlanDeck({key: deck[key] for key in deck})
    return ProtocolContext(gantry=_Gantry(), deck=plan_deck)


def test_handler_refuses_unresolved_opt_in_under_planning():
    from cubos.protocol_engine.commands.pipette import aspirate

    with pytest.raises(ProtocolExecutionError, match="resolved before motion planning"):
        aspirate(_context(_deck(), planning=True), position="v", volume_ul=5.0, from_bottom_mm=1.0)


def test_handler_reports_engage_errors_as_execution_errors():
    from cubos.protocol_engine.commands.pipette import aspirate

    with pytest.raises(ProtocolExecutionError, match="no well_depth"):
        aspirate(_context(_deck()), position="bare.A1", volume_ul=5.0, from_bottom_mm=1.0)


def test_protocol_execute_resolves_before_running_steps():
    from cubos.protocol_engine.commands import pipette as commands

    deck = _deck()
    protocol = ProtocolBuilder().add_command(
        "multi_dispense", source="v", destinations=["v"], volumes=[1.0],
        source_from_bottom_mm=1.0, destination_from_bottom_mm=2.0,
    ).build()
    seen = {}
    original = protocol.steps[0].handler

    def spy(context, **kwargs):
        seen.update(kwargs)

    protocol._steps[0].handler = spy
    protocol.execute(_context(deck))
    protocol._steps[0].handler = original
    assert seen["source_height"] == -14.0
    assert seen["destination_height"] == -13.0
    assert "source_from_bottom_mm" not in seen
    assert commands  # module imported for registration


DEPTH_DECK = VALIDATOR_DECK_YAML.replace(
    "    diameter: 20.0\n", "    diameter: 20.0\n    inner_depth: 30.0\n", 1,
)


def _validate(tmp_path, steps, deck=DEPTH_DECK):
    paths = {}
    for name, text in {
        "gantry": VALIDATOR_GANTRY_YAML, "deck": deck,
        "protocol": "protocol:\n" + dedent(steps),
        "fluids": VALIDATOR_FLUIDS_YAML,
    }.items():
        paths[name] = tmp_path / f"{name}.yaml"
        paths[name].write_text(text, encoding="utf-8")
    return run_setup_validation(
        paths["gantry"], paths["deck"], paths["protocol"],
        initial_fluids_path=paths["fluids"],
    )


def test_setup_validation_accepts_in_bounds_bottom_offset(tmp_path):
    result = _validate(tmp_path, """\
      - pick_up_tip:
          position: tips.A1
      - transfer:
          source: source
          destination: dest
          volume_ul: 100
          source_from_bottom_mm: 3.0
          destination_from_top_mm: 5.0
    """)
    assert result.passed, result.output
    assert "source_height=-27.0" in result.output


@pytest.mark.parametrize(
    "field", ["source_from_bottom_mm: 90.0", "source_from_top_mm: 60.0", "source_height: 60.0"],
)
def test_resolved_engage_height_is_bounds_checked_like_height(tmp_path, field):
    result = _validate(tmp_path, f"""\
      - pick_up_tip:
          position: tips.A1
      - transfer:
          source: source
          destination: dest
          volume_ul: 100
          {field}
    """)
    assert not result.passed
    assert "violates z_max=80.0" in result.errors[0]


def test_setup_validation_reports_missing_depth(tmp_path):
    result = _validate(tmp_path, """\
      - pick_up_tip:
          position: tips.A1
      - transfer:
          source: source
          destination: dest
          volume_ul: 100
          source_from_bottom_mm: 3.0
    """, deck=VALIDATOR_DECK_YAML)
    assert not result.passed
    assert "inner_depth" in result.output


def test_setup_protocol_wraps_engage_errors(tmp_path):
    from cubos.protocol_engine.setup import setup_protocol

    for name, text in (("g", VALIDATOR_GANTRY_YAML), ("d", VALIDATOR_DECK_YAML)):
        (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    protocol = ProtocolBuilder().add_command(
        "aspirate", position="source", volume_ul=5.0, from_bottom_mm=1.0,
    ).build()
    with pytest.raises(ProtocolLoaderError, match="Engage position error"):
        setup_protocol(tmp_path / "g.yaml", tmp_path / "d.yaml", protocol, mock_mode=True)
