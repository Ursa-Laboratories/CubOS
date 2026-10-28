from pathlib import Path

import pytest

from cubos.protocol_engine.setup_validator import run_setup_validation

FIXTURES = Path(__file__).parents[1] / "fixtures/configs/eight_channel_geometry"


@pytest.mark.parametrize("protocol,passes", [("clear.yaml", True), ("blocked.yaml", False)])
def test_measured_head_is_used_by_setup_validation(protocol, passes):
    result = run_setup_validation(FIXTURES / "gantry.yaml", FIXTURES / "deck.yaml", FIXTURES / protocol)
    assert result.passed is passes, result.output
    if not passes:
        assert "instrument envelope" in result.output
        assert "right X-max rail" in result.output
