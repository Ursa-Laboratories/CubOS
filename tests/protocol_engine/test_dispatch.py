"""Direct unit tests for `inject_runtime_args` — the dispatch boundary
shared by `measure` and `scan`.

The dispatch helper forwards labware-relative offsets under their
protocol-layer names (``measurement_height``, ``indentation_limit_height``)
and injects an absolute reference Z (``well_z``) so closed-loop methods
can compute their own descent geometry from a single anchor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from instruments.base_instrument import BaseInstrument
from protocol_engine.commands._dispatch import inject_runtime_args
from protocol_engine.errors import ProtocolExecutionError
from protocol_engine.runtime import ProtocolContext


class _ClosedLoopInstrument(BaseInstrument):
    """Real-class fake whose `indentation` declares a `gantry` parameter,
    mirroring `ASMI.indentation`.

    `inspect.signature` reads the actual function signature, so a real
    subclass is required — `MagicMock` would expose its synthetic signature
    instead, defeating the gantry-injection branch.
    """

    def __init__(self) -> None:
        super().__init__(
            name="indenter",
            offset_x=0.0, offset_y=0.0, depth=0.0,
        )

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def health_check(self) -> bool: return True

    def indentation(self, gantry, step_size: float = 0.01) -> dict:
        return {"gantry": gantry, "step_size": step_size}

    def measure(self) -> str:
        return "no-gantry"


def _ctx(gantry: object | None = ...) -> ProtocolContext:
    """Build a minimal ProtocolContext with a configurable gantry controller."""
    instrumented_gantry = MagicMock()
    instrumented_gantry.controller = object() if gantry is ... else gantry
    deck = MagicMock()
    return ProtocolContext(gantry=instrumented_gantry, deck=deck)


# ── Gantry injection ──────────────────────────────────────────────────────

def test_injects_gantry_when_method_signature_declares_it():
    instr = _ClosedLoopInstrument()
    sentinel = object()
    ctx = _ctx(gantry=sentinel)

    kwargs = inject_runtime_args(
        instr.indentation, {"step_size": 0.02}, ctx, well_z=0.0,
    )

    assert kwargs["gantry"] is sentinel
    assert kwargs["step_size"] == 0.02


def test_does_not_inject_gantry_when_method_does_not_declare_it():
    """Open-loop methods (no `gantry` parameter) must not receive a
    `gantry` kwarg — would TypeError on the unexpected argument."""
    instr = _ClosedLoopInstrument()
    ctx = _ctx()

    kwargs = inject_runtime_args(instr.measure, {}, ctx, well_z=0.0)

    assert "gantry" not in kwargs


def test_raises_when_method_requires_gantry_but_board_gantry_is_none():
    """Better than the late `AttributeError: 'NoneType'` the closed-loop
    method would otherwise raise inside its first `gantry.move(...)`."""
    instr = _ClosedLoopInstrument()
    ctx = _ctx(gantry=None)

    with pytest.raises(ProtocolExecutionError, match="gantry"):
        inject_runtime_args(instr.indentation, {}, ctx, well_z=0.0)


# ── Labware-relative offset forwarding ───────────────────────────────────

class _ClosedLoopWithRelativeOffsets(BaseInstrument):
    """Mirrors ASMI.indentation: relative offsets + well_z anchor."""

    def __init__(self) -> None:
        super().__init__(
            name="indenter",
            offset_x=0.0, offset_y=0.0, depth=0.0,
        )

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def health_check(self) -> bool: return True

    def indentation(
        self,
        gantry,
        *,
        measurement_height: float,
        indentation_limit_height: float,
        well_z: float,
    ) -> dict:
        return {
            "gantry": gantry,
            "measurement_height": measurement_height,
            "indentation_limit_height": indentation_limit_height,
            "well_z": well_z,
        }


def test_forwards_offsets_and_well_z_when_declared():
    instr = _ClosedLoopWithRelativeOffsets()
    sentinel = object()
    ctx = _ctx(gantry=sentinel)

    kwargs = inject_runtime_args(
        instr.indentation, {}, ctx,
        well_z=70.0, measurement_height=-1.0, indentation_limit_height=-5.0,
    )

    assert kwargs["measurement_height"] == -1.0
    assert kwargs["indentation_limit_height"] == -5.0
    assert kwargs["well_z"] == 70.0
    assert kwargs["gantry"] is sentinel


def test_does_not_forward_offsets_when_method_does_not_declare_them():
    """Open-loop method (no relative-offset parameters) — kwargs stay clean."""
    instr = _ClosedLoopInstrument()
    ctx = _ctx()

    kwargs = inject_runtime_args(
        instr.indentation, {}, ctx,
        well_z=70.0, measurement_height=-1.0,
    )

    assert "measurement_height" not in kwargs
    assert "well_z" not in kwargs
    assert "indentation_limit_height" not in kwargs


def test_runtime_offset_overrides_method_kwargs():
    """Engine value (the YAML scan field, validated by the engine) is
    the source of truth, not whatever ``method_kwargs`` carried."""
    instr = _ClosedLoopWithRelativeOffsets()
    ctx = _ctx()

    kwargs = inject_runtime_args(
        instr.indentation,
        {"measurement_height": 99.0, "indentation_limit_height": 99.0},
        ctx,
        well_z=70.0, measurement_height=-1.0, indentation_limit_height=-5.0,
    )

    assert kwargs["measurement_height"] == -1.0
    assert kwargs["indentation_limit_height"] == -5.0


def test_zero_well_z_forwarded_not_dropped():
    """Boundary case: ``well_z = 0.0`` is a legitimate absolute Z (e.g.
    a labware whose surface is at the deck origin). Pin so a future
    'simplify to truthy check' regression flips this test red."""
    instr = _ClosedLoopWithRelativeOffsets()
    sentinel = object()
    ctx = _ctx(gantry=sentinel)

    kwargs = inject_runtime_args(
        instr.indentation, {}, ctx,
        well_z=0.0, measurement_height=0.0, indentation_limit_height=-1.0,
    )

    assert kwargs["well_z"] == 0.0
    assert kwargs["measurement_height"] == 0.0


def test_indentation_limit_height_omitted_when_caller_passes_none():
    """``indentation_limit_height`` is optional (e.g. ``measure`` and
    open-loop ``scan`` don't supply it). When omitted, the method's
    default kicks in — the helper does NOT inject ``None``."""
    instr = _ClosedLoopWithRelativeOffsets()

    class _OptionalLimit(BaseInstrument):
        def __init__(self) -> None:
            super().__init__(name="x", offset_x=0.0, offset_y=0.0, depth=0.0)
        def connect(self) -> None: ...
        def disconnect(self) -> None: ...
        def health_check(self) -> bool: return True
        def indentation(
            self, gantry, *, measurement_height: float, well_z: float,
            indentation_limit_height: float = -0.1,
        ) -> dict:
            return {"indentation_limit_height": indentation_limit_height}

    optional = _OptionalLimit()
    ctx = _ctx(gantry=object())

    kwargs = inject_runtime_args(
        optional.indentation, {}, ctx,
        well_z=70.0, measurement_height=-1.0,
    )

    assert "indentation_limit_height" not in kwargs


@pytest.mark.parametrize("bad_value", ["", "27.0", "abc", float("nan"), float("inf"), True])
def test_rejects_non_finite_well_z(bad_value):
    """Non-numeric / non-finite values must fail at the dispatch boundary
    rather than slipping through to motion code where they would surface
    as opaque late TypeErrors."""
    instr = _ClosedLoopWithRelativeOffsets()
    ctx = _ctx()

    with pytest.raises(ProtocolExecutionError, match="well_z"):
        inject_runtime_args(
            instr.indentation, {}, ctx, well_z=bad_value,
        )


@pytest.mark.parametrize("bad_value", ["", "abc", float("nan"), float("inf"), True])
def test_rejects_non_finite_measurement_height(bad_value):
    instr = _ClosedLoopWithRelativeOffsets()
    ctx = _ctx()

    with pytest.raises(ProtocolExecutionError, match="measurement_height"):
        inject_runtime_args(
            instr.indentation, {}, ctx,
            well_z=10.0, measurement_height=bad_value,
        )


@pytest.mark.parametrize("bad_value", ["", "abc", float("nan"), float("inf"), True])
def test_rejects_non_finite_indentation_limit_height(bad_value):
    instr = _ClosedLoopWithRelativeOffsets()
    ctx = _ctx()

    with pytest.raises(ProtocolExecutionError, match="indentation_limit_height"):
        inject_runtime_args(
            instr.indentation, {}, ctx,
            well_z=10.0, measurement_height=-1.0,
            indentation_limit_height=bad_value,
        )


def test_required_indentation_limit_height_missing_raises_actionable_error():
    """If a method requires ``indentation_limit_height`` (no default) and
    the engine has no value to inject (i.e. the user omitted it from the
    scan command), surface a ``ProtocolExecutionError`` naming the
    user-facing field. Bare Python ``TypeError`` mid-protocol is
    unactionable."""
    ctx = _ctx(gantry=object())

    class _Required(BaseInstrument):
        def __init__(self) -> None:
            super().__init__(name="x", offset_x=0.0, offset_y=0.0, depth=0.0)
        def connect(self) -> None: ...
        def disconnect(self) -> None: ...
        def health_check(self) -> bool: return True
        def indentation(
            self, gantry, *,
            measurement_height: float,
            indentation_limit_height: float,
            well_z: float,
        ) -> dict:
            return {}

    required = _Required()
    with pytest.raises(ProtocolExecutionError, match="indentation_limit_height"):
        inject_runtime_args(
            required.indentation, {}, ctx,
            well_z=70.0, measurement_height=-1.0,
        )


def test_indentation_limit_height_supplied_to_method_without_it_raises():
    """If the user supplies ``indentation_limit_height`` but the chosen
    method does not declare it, refusing the dispatch beats silently
    dropping the depth bound — a typo like ``method: indent`` (vs
    ``indentation``) would otherwise sail through."""
    instr = _ClosedLoopInstrument()  # indentation(self, gantry, step_size=...)
    ctx = _ctx()

    with pytest.raises(ProtocolExecutionError, match="silently ignored"):
        inject_runtime_args(
            instr.indentation, {}, ctx,
            well_z=70.0, measurement_height=-1.0, indentation_limit_height=-5.0,
        )


def test_method_kwargs_not_mutated():
    """The helper returns a fresh dict; the caller's `method_kwargs` is
    untouched. Important because callers reuse the same dict across loop
    iterations (e.g. scan's per-well loop)."""
    instr = _ClosedLoopWithRelativeOffsets()
    ctx = _ctx()
    original = {"measurement_height": 99.0}
    snapshot = dict(original)

    inject_runtime_args(
        instr.indentation, original, ctx,
        well_z=70.0, measurement_height=-1.0, indentation_limit_height=-5.0,
    )

    assert original == snapshot
