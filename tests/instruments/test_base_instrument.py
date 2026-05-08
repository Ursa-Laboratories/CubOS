import pytest
from instruments.base_instrument import BaseInstrument, InstrumentError


class MockInstrument(BaseInstrument):
    def __init__(
        self,
        name="mock_instrument",
        offset_x=0.0,
        offset_y=0.0,
        depth=0.0,
    ):
        super().__init__(
            name=name,
            offset_x=offset_x,
            offset_y=offset_y,
            depth=depth,
        )
        self.connected = False
        self.healthy = True

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def health_check(self):
        return self.healthy


class BadInstrument(BaseInstrument):
    pass


def test_cannot_instantiate_abc():
    with pytest.raises(TypeError):
        BaseInstrument()


def test_cannot_instantiate_incomplete_subclass():
    with pytest.raises(TypeError):
        BadInstrument()


def test_concrete_implementation():
    instr = MockInstrument()
    assert instr.name == "mock_instrument"

    instr.connect()
    assert instr.connected is True

    instr.disconnect()
    assert instr.connected is False

    assert instr.health_check() is True


def test_handle_error_wraps_exception():
    instr = MockInstrument()
    original_error = ValueError("Something went wrong")

    with pytest.raises(InstrumentError) as exc_info:
        instr.handle_error(original_error, "testing context")

    assert "Something went wrong" in str(exc_info.value)
    assert "testing context" in str(exc_info.value)
    assert exc_info.value.__cause__ is original_error


def test_handle_error_passes_through_instrument_error():
    instr = MockInstrument()
    original_error = InstrumentError("Already an instrument error")

    with pytest.raises(InstrumentError) as exc_info:
        instr.handle_error(original_error, "processing")

    assert exc_info.value is original_error


def test_default_offset_depth():
    """Instruments only carry physical mounting state. Labware-relative
    motion heights live on the protocol command."""
    instr = MockInstrument()
    assert instr.offset_x == 0.0
    assert instr.offset_y == 0.0
    assert instr.depth == 0.0
    assert not hasattr(instr, "measurement_height")
    assert not hasattr(instr, "interwell_scan_height")


def test_custom_offset_and_depth():
    instr = MockInstrument(offset_x=-10.5, offset_y=20.0, depth=-5.0)
    assert instr.offset_x == -10.5
    assert instr.offset_y == 20.0
    assert instr.depth == -5.0
