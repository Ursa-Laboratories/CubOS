from pathlib import Path

import pytest
import yaml
from cubos.data import DataStore
from cubos.gantry.gantry import Gantry
from cubos.instruments.pipette.exceptions import PipetteTimeoutError
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.protocol_engine.setup import run_on_hardware

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/configs/fluid_state_resume"


@pytest.mark.parametrize("display_name", [None, "Display pipette"])
@pytest.mark.parametrize("failure_type", [PipetteTimeoutError, KeyboardInterrupt])
def test_failed_mock_protocol_retracts_registered_instrument(
    tmp_path, monkeypatch, display_name, failure_type,
):
    config = yaml.safe_load((FIXTURES / "gantry.yaml").read_text())
    if display_name is not None:
        config["instruments"]["pipette"]["name"] = display_name
    gantry_path = tmp_path / "gantry.yaml"
    gantry_path.write_text(yaml.safe_dump(config))
    controller = Gantry(offline=True)
    events = []
    expected_retract = []
    move_to = controller.move_to
    disconnect = controller.disconnect
    failure = failure_type("synthetic dispense failure")

    def record_move(x, y, z, travel_z=None):
        events.append(("move", x, y, z, travel_z))
        return move_to(x, y, z, travel_z=travel_z)

    def fail_dispense(self, *args, **kwargs):
        assert self._offline
        _, x, y, _z, _travel_z = events[-1]
        safe_z = config["cnc"]["safe_z"] + self.effective_depth
        expected_retract.append(("move", x, y, safe_z, safe_z))
        events.append(("failure",))
        raise failure

    def record_disconnect():
        events.append(("disconnect",))
        return disconnect()

    monkeypatch.setattr(controller, "move_to", record_move)
    monkeypatch.setattr(controller, "disconnect", record_disconnect)
    monkeypatch.setattr(OpentronsPipette, "dispense", fail_dispense)
    with DataStore(tmp_path / "state.db") as store:
        with pytest.raises(failure_type) as caught:
            run_on_hardware(
                gantry_path, FIXTURES / "deck.yaml", FIXTURES / "01_load_plate.yaml",
                gantry=controller, mock_mode=True, data_store=store,
                initial_fluids=FIXTURES / "initial_fluids.yaml",
            )
        assert caught.value is failure
        assert expected_retract
        assert events[-3:] == [("failure",), expected_retract[0], ("disconnect",)]
        snapshot = store.get_fluid_snapshot(1)
        assert [op["status"] for op in snapshot["operations"]] == [
            "reconciliation_required",
        ]
        source = store.get_fluid_container(1, "reagents", "A1")
        destination = store.get_fluid_container(1, "assay_plate", "A1")
        assert source["current_volume_ul"] == 1000.0
        assert destination["current_volume_ul"] == 0.0
