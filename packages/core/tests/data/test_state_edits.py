import sqlite3

import pytest
from cubos.data import DataStore, FluidStateConflictError, FluidStateError
from cubos.deck.loader import load_deck_from_yaml_safe


@pytest.fixture
def editable_state(tmp_path):
    from tests.data.test_cap_state import DECK_YAML

    path = tmp_path / 'deck.yaml'
    path.write_text(DECK_YAML + """
  tip_rack:
    load_name: ursa_tip_rack
    name: test_tip_rack
    tip_length: 59.3
    pickup_z: 64.7
    drop_z: 34.0
    calibration:
      a1: {x: 210.0, y: 230.0}
      a2: {x: 218.5, y: 230.0}
""")
    with DataStore(tmp_path / 'state.db') as store:
        state = store.create_fluid_state(path, load_deck_from_yaml_safe(path))
        store.seed_fluid(state, 'stock', 100, {'a': 70, 'b': 30})
        campaign = store.create_campaign('edit test', fluid_state_id=state)
        yield store, state, campaign


def test_correct_volume_preserves_mixture_and_rejects_stale_edit(editable_state):
    store, state, _ = editable_state
    before = store.get_fluid_container(state, 'stock', '')
    store.correct_fluid_volume(state, 'stock', '', 90, before['version'])
    changed = store.get_fluid_container(state, 'stock', '')
    assert changed['current_volume_ul'] == 90
    assert changed['composition'] == {'a': 63, 'b': 27}
    with pytest.raises(FluidStateConflictError, match='refresh'):
        store.correct_fluid_volume(state, 'stock', '', 80, before['version'])
    assert store.get_fluid_container(state, 'stock', '') == changed


@pytest.mark.parametrize('volume', [-1, float('nan'), float('inf'), 501])
def test_invalid_volume_correction_is_atomic(editable_state, volume):
    store, state, _ = editable_state
    before = store.get_fluid_snapshot(state)
    version = store.get_fluid_container(state, 'stock', '')['version']
    with pytest.raises(FluidStateError):
        store.correct_fluid_volume(state, 'stock', '', volume, version)
    assert store.get_fluid_snapshot(state) == before


def test_correction_to_zero_and_from_empty(editable_state):
    store, state, _ = editable_state
    for volume, composition in [(0, {}), (20, {'unknown': 20})]:
        current = store.get_fluid_container(state, 'stock', '')
        store.correct_fluid_volume(state, 'stock', '', volume, current['version'])
        assert store.get_fluid_container(state, 'stock', '')['composition'] == composition


def test_correction_blocks_pending_operation(editable_state):
    store, state, campaign = editable_state
    store.begin_fluid_transfer(state, 'pending', 'stock', '', 'waste', '', 10, campaign_id=campaign)
    before = store.get_fluid_snapshot(state)
    version = store.get_fluid_container(state, 'stock', '')['version']
    with pytest.raises(FluidStateError, match='pending'):
        store.correct_fluid_volume(state, 'stock', '', 90, version)
    assert store.get_fluid_snapshot(state) == before


def test_clear_notes_is_scoped_and_preserves_operation_state(editable_state):
    store, state, campaign = editable_state
    store.begin_cap_operation(state, 'cap-note', 'decap', 'stock', '', campaign_id=campaign)
    store.resolve_cap_operation('cap-note', 'applied', detail='[operator] done')
    store.begin_fluid_transfer(state, 'fluid-note', 'stock', '', 'waste', '', 10, campaign_id=campaign)
    store.resolve_fluid_operation('fluid-note', 'applied', detail='[operator] done')
    store.begin_pick_up_tip(state, 'tip-note', 'tip_rack', 'A1', 59.3, campaign_id=campaign)
    store.resolve_tip_operation('tip-note', 'applied', detail='tip note')
    before = store.get_fluid_snapshot(state)
    path = before['deck_path']
    other = store.create_fluid_state(path, load_deck_from_yaml_safe(path))
    store.begin_cap_operation(
        other, 'other-note', 'decap', 'stock', '',
        campaign_id=store.create_campaign('other', fluid_state_id=other),
    )
    store.resolve_cap_operation('other-note', 'applied', detail='keep this note')
    with pytest.raises(FluidStateError):
        store.clear_operation_notes(other + 1)
    assert store.get_fluid_snapshot(state) == before
    store.clear_operation_notes(state)
    assert store.get_fluid_snapshot(state)['operations'][0]['detail'] is None
    assert store.get_cap_snapshot(state)['operations'][0]['detail'] is None
    assert store.get_tip_snapshot(state)['operations'][0]['detail'] is None
    assert store.get_cap_snapshot(other)['operations'][0]['detail'] == 'keep this note'
    assert store.get_cap_state(state, 'stock', '') == 'uncapped'
    assert store.get_fluid_snapshot(state)['containers'] == before['containers']
    store.clear_operation_notes(state)
    assert store.get_fluid_snapshot(state)['operations'][0]['status'] == 'applied'


def test_interrupted_transfer_rolls_back_on_journal_failure(editable_state):
    store, state, campaign = editable_state
    store.begin_fluid_transfer(state, 'interrupted', 'stock', '', 'waste', '', 10, campaign_id=campaign)
    before = store.get_fluid_snapshot(state)
    store._conn.execute("""
        CREATE TEMP TRIGGER reject_estimate BEFORE UPDATE ON fluid_operations
        WHEN NEW.status = 'reconciled'
        BEGIN SELECT RAISE(ABORT, 'write failed'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match='write failed'):
        store.finish_interrupted_transfer('interrupted', 'aspirate')
    assert store.get_fluid_snapshot(state) == before


def test_invalid_interrupted_action_and_operation(editable_state):
    store, state, campaign = editable_state
    with pytest.raises(FluidStateError, match='action'):
        store.finish_interrupted_transfer('missing', 'invalid')
    store.begin_fluid_mix(state, 'mix', 'stock', 10, 1, 50, campaign_id=campaign)
    with pytest.raises(FluidStateError, match='transfer operation'):
        store.finish_interrupted_transfer('mix', 'aspirate')


@pytest.mark.parametrize('resolution', ['applied', 'not_applied', 'partial'])
def test_tip_and_cap_resolutions_need_no_notes(editable_state, resolution):
    store, state, campaign = editable_state
    store.begin_cap_operation(state, 'cap', 'decap', 'stock', '', campaign_id=campaign)
    cap_options = {'final_status': 'uncapped'} if resolution == 'partial' else {}
    store.resolve_cap_operation('cap', resolution, **cap_options)
    store.begin_pick_up_tip(state, 'tip', 'tip_rack', 'A1', 59.3, campaign_id=campaign)
    tip_options = {'final_slot_status': 'available'} if resolution == 'partial' else {}
    store.resolve_tip_operation('tip', resolution, **tip_options)
    assert store.get_cap_snapshot(state)['operations'][0]['detail'] is None
    assert store.get_tip_snapshot(state)['operations'][0]['detail'] is None


def test_clear_notes_rolls_back_all_domains_on_write_failure(editable_state):
    store, state, campaign = editable_state
    store.begin_fluid_transfer(state, 'fluid', 'stock', '', 'waste', '', 10, campaign_id=campaign)
    store.resolve_fluid_operation('fluid', 'applied', detail='fluid note')
    store.begin_cap_operation(state, 'cap', 'decap', 'stock', '', campaign_id=campaign)
    store.resolve_cap_operation('cap', 'applied', detail='cap note')
    before = store.get_fluid_snapshot(state)
    store._conn.execute("""
        CREATE TEMP TRIGGER reject_clear BEFORE UPDATE ON cap_operations
        BEGIN SELECT RAISE(ABORT, 'write failed'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match='write failed'):
        store.clear_operation_notes(state)
    assert store.get_fluid_snapshot(state) == before
    assert store.get_cap_snapshot(state)['operations'][0]['detail'] == 'cap note'
