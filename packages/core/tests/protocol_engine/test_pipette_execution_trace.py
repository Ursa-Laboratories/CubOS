"""Real recorder and liquid journal with offline pipette boundary doubles."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from cubos.protocol_engine.commands import pipette as commands
from cubos.protocol_engine.execution_trace import RunRecorder

from .test_compound_liquid_commands import (
    RecordingPipette,
    _make_context,
    _operations,
    tracked_env,
)


@contextmanager
def recording(store, context, run_id, command):
    with RunRecorder(store, run_id=run_id) as recorder:
        context.execution_trace = recorder
        recorder.records.update_run(run_id, campaign_id=context.campaign_id)
        try:
            with context.trace_scope(command):
                yield recorder
        finally:
            context.execution_trace = None


def test_rinse_semantic_children_and_idempotent_replay(tracked_env):
    deck, store, state_id, campaign_id = tracked_env
    instrument = RecordingPipette()
    context = _make_context(deck, store, state_id, campaign_id, instrument)
    with recording(store, context, "first", "rinse_well"):
        commands.rinse_well(
            context,
            well="plate.A1",
            volume_ul=50,
            cycles=2,
            solution="water",
            mix_repetitions=1,
        )
    rows = store.execution_records.list_steps("first")
    assert [row["command"] for row in rows] == [
        "rinse_well",
        "transfer",
        "transfer.stroke",
        "mix",
        "transfer",
        "transfer.stroke",
        "transfer",
        "transfer.stroke",
        "mix",
        "transfer",
        "transfer.stroke",
    ]
    root = rows[0]
    assert root["parameters"]["resolved"]["source"] == "stock"
    assert root["parameters"]["resolved"]["waste"] == "waste"
    legs = [row for row in rows if row["command"] in {"transfer", "mix"}]
    assert [row["iteration_index"] for row in legs] == [0, 0, 0, 1, 1, 1]
    assert all(
        row["parent_step_execution_id"] == root["step_execution_id"] for row in legs
    )
    keys = [op["operation_key"] for op in _operations(store, state_id)]
    assert any("rinse:cycle0:fill" in key for key in keys)
    before = list(instrument.calls)
    with recording(store, context, "replay", "rinse_well"):
        commands.rinse_well(
            context,
            well="plate.A1",
            volume_ul=50,
            cycles=2,
            solution="water",
            mix_repetitions=1,
        )
    replay = store.execution_records.list_steps("replay")
    assert replay[0]["status"] == "completed"
    assert [row["status"] for row in replay[1:]] == ["skipped"] * 6
    assert instrument.calls == before
    assert context.active_substep is None
    assert [op["operation_key"] for op in _operations(store, state_id)] == keys


def test_corrected_multistroke_settings_and_skip_only_stroke(tracked_env):
    deck, store, state_id, campaign_id = tracked_env
    instrument = RecordingPipette(
        liquid_classes={"aqueous": {"multiplier": 1.01, "offset_ul": 6.23}}
    )
    context = _make_context(
        deck, store, state_id, campaign_id, instrument, command="transfer"
    )
    with recording(store, context, "first", "transfer"):
        commands.transfer(
            context,
            "stock",
            "waste",
            300,
            source_height=-5,
            destination_height=2,
            liquid_class="aqueous",
        )
    rows = store.execution_records.list_steps("first")
    assert len(rows) == 3
    assert rows[0]["status"] == "completed"
    strokes = rows[1:]
    assert [row["command"] for row in strokes] == ["transfer.stroke"] * 2
    assert [row["iteration_index"] for row in strokes] == [0, 1]
    assert sum(
        row["parameters"]["requested_volume_ul"] for row in strokes
    ) == pytest.approx(300)
    assert [
        row["parameters"]["resolved"]["commanded_volume_ul"] for row in strokes
    ] == instrument.aspirate_volumes
    assert all(row["parameters"]["source_height"] == -5 for row in strokes)
    assert all(row["parameters"]["destination_height"] == 2 for row in strokes)
    assert strokes[-1]["parameters"]["blow_out"] is True
    keys = [op["operation_key"] for op in _operations(store, state_id)]
    assert [row["parameters"]["resolved"]["operation_key"] for row in strokes] == keys
    # The first journaled stroke is skipped while the second is newly executed.
    original = store.begin_fluid_transfer

    def partial_replay(*args, **kwargs):
        if "stroke0" in args[1]:
            return False
        return original(*args, **kwargs)

    context.active_step_index = 2
    store.begin_fluid_transfer = partial_replay
    try:
        with recording(store, context, "partial", "transfer"):
            commands.transfer(context, "stock", "waste", 300, liquid_class="aqueous")
    finally:
        store.begin_fluid_transfer = original
    replay = store.execution_records.list_steps("partial")
    assert [row["status"] for row in replay] == ["completed", "skipped", "completed"]
    assert "commanded_volume_ul" not in replay[1]["parameters"]["resolved"]
    assert context.active_substep is None


def test_serial_and_flush_children_keep_existing_journal_keys(tracked_env):
    deck, store, state_id, campaign_id = tracked_env
    instrument = RecordingPipette()
    context = _make_context(
        deck, store, state_id, campaign_id, instrument, command="serial_transfer"
    )
    context.active_substep = "outer"
    with recording(store, context, "serial", "serial_transfer"):
        commands.serial_transfer(context, "stock", "plate", "A", volumes=[20, 30])
    rows = store.execution_records.list_steps("serial")
    transfers = [row for row in rows if row["command"] == "transfer"]
    assert [row["parameters"]["destination"] for row in transfers] == [
        "plate.A1",
        "plate.A2",
    ]
    assert [row["iteration_index"] for row in transfers] == [0, 1]
    assert context.active_substep == "outer"
    assert all(
        "outer" not in op["operation_key"] for op in _operations(store, state_id)
    )
    context.active_step_index = 2
    context.active_step_command = "flush_pipette"
    with recording(store, context, "flush", "flush_pipette"):
        commands.flush_pipette(context, 20, cycles=2, source="stock", waste="waste")
    legs = [
        row
        for row in store.execution_records.list_steps("flush")
        if row["command"] == "transfer"
    ]
    assert [row["iteration_index"] for row in legs] == [0, 1]
    assert all(row["parameters"]["source"] == "stock" for row in legs)
    assert context.active_substep == "outer"
    assert any(
        "outer:flush:cycle0" in op["operation_key"]
        for op in _operations(store, state_id)
    )


def test_legacy_substep_scope_restores_on_error_without_trace_method():
    events = []
    context = SimpleNamespace(
        active_substep="outer", notify_step=lambda event, **kw: events.append(event)
    )
    with pytest.raises(ValueError):
        with commands._substep_scope(context, "inner"):
            assert context.active_substep == "outer:inner"
            raise ValueError("failure")
    assert context.active_substep == "outer"
    assert events == ["step_started", "step_failed"]


def test_tip_trace_uses_journal_selected_slot_and_replayed_extension(tmp_path):
    from cubos.data.data_store import DataStore
    from .test_pipette_commands import _two_tip_rack_context

    context, rack, instrument = _two_tip_rack_context()
    (tmp_path / "tips.yaml").write_text("labware: {}\n")
    with DataStore(":memory:") as store:
        context.data_store = store
        context.fluid_state_id = store.create_fluid_state(
            tmp_path / "tips.yaml", context.deck
        )
        context.campaign_id = store.create_campaign(
            "tips", fluid_state_id=context.fluid_state_id
        )
        context.active_step_index = 0
        context.active_step_command = "pick_up_tip"
        with recording(store, context, "tip", "pick_up_tip"):
            commands.pick_up_tip(context, "tips")
        result = store.execution_records.list_steps("tip")[0]
        assert result["parameters"]["resolved"]["tip_id"] == "A1"
        assert result["parameters"]["resolved"]["tip_position"] == "tips.A1"
        assert result["parameters"]["resolved"]["tip_extension_mm"] == rack.tip_length
        with recording(store, context, "tip-replay", "pick_up_tip"):
            commands.pick_up_tip(context, "tips")
        replay = store.execution_records.list_steps("tip-replay")[0]
        assert replay["status"] == "skipped"
        assert replay["parameters"]["resolved"]["tip_id"] == "A1"
        assert instrument.pick_up_tip.call_count == 1


def test_clear_noop_and_purge_preserve_semantic_boundaries(tracked_env):
    deck, store, state_id, campaign_id = tracked_env
    instrument = RecordingPipette()
    context = _make_context(
        deck, store, state_id, campaign_id, instrument, command="clear_well"
    )
    with recording(store, context, "clear", "clear_well"):
        commands.clear_well(context, "plate.A1")
    rows = store.execution_records.list_steps("clear")
    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"
    assert rows[0]["parameters"]["resolved"]["removal_volume_ul"] == 0
    assert instrument.calls == []
    context.active_step_index = 2
    context.active_step_command = "purge_pipette"
    with recording(store, context, "purge", "purge_pipette"):
        commands.purge_pipette(context, 20, source="stock", waste="waste")
    rows = store.execution_records.list_steps("purge")
    assert [row["command"] for row in rows] == [
        "purge_pipette",
        "transfer",
        "transfer.stroke",
    ]
    assert rows[1]["parameters"]["volume_ul"] == 20
    commands._record_resolved(SimpleNamespace(), ignored=True)
