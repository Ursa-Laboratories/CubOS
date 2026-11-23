"""A verified owned backoff grants one short-lived automatic Home."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from cubos.gantry.session import CalibrationBlockedError, GantryAlarmError, GantryJogCancelledError, GantrySession
from tests.gantry.test_session import CorrelatedRecoveryGantry, _write_gantry


class HomeRecoveryGantry(CorrelatedRecoveryGantry):
    def home(self, *, check_cancelled=None):
        if check_cancelled is not None: check_cancelled()
        self.calls.append(("home", None))
        self.status = "Idle"
        self.coords = {"x": 300.0, "y": 200.0, "z": 80.0}

    def get_calibration_position_info(self):
        return self.get_position_info()


@pytest.fixture
def recovered(tmp_path):
    session = GantrySession(gantry_factory=HomeRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session.prepare_calibration_origin()
    gantry = session._gantry
    gantry.trip_next = True
    session.jog(y=0.25, jog_id="owned-fault")
    session.position()
    result, _ = session.recover_calibration_limit(y=0.25, jog_id="owned-fault")
    assert result.commanded_delta == {"x": 0, "y": -5, "z": 0}
    assert session.position().status == "Home required"
    assert session._recovered_home_permission is not None
    gantry.calls.clear()
    return session, gantry


def test_successful_session_recovery_then_exactly_one_home(recovered):
    session, gantry = recovered
    position = session.home_after_calibration_recovery(jog_id="owned-fault")
    assert position.status == "Idle"
    assert position.work_z == 80
    assert session.calibration_active
    assert sum(name == "home" for name, _ in gantry.calls) == 1
    assert not any(name in ("jog", "move_to", "reset_and_unlock") for name, _ in gantry.calls)
    before = list(gantry.calls)
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert gantry.calls == before


def test_foreign_id_never_authorizes_or_consumes_owned_home(recovered):
    session, gantry = recovered
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="foreign")
    assert not gantry.calls
    assert session.home_after_calibration_recovery(jog_id="owned-fault").status == "Idle"


@pytest.mark.parametrize("action", ["stop", "settings_changed_back", "config_changed_back", "work_coordinates", "jog", "restore", "new_fault"])
def test_intervening_action_irrevocably_revokes_permission(recovered, action):
    session, gantry = recovered
    if action == "stop": session.jog_cancel_interrupt()
    if action == "settings_changed_back":
        session.set_grbl_setting("$23", 1)
        session.set_grbl_setting("$23", 0)
    if action == "config_changed_back":
        original = session.connected_gantry_config
        changed = deepcopy(original)
        changed["cnc"]["factory_z_travel_mm"] += 1
        session.refresh_connected_config("gantry.yaml", changed)
        session.refresh_connected_config("gantry.yaml", original)
    if action == "work_coordinates":
        with pytest.raises(CalibrationBlockedError): session.set_work_coordinates(x=0)
    if action == "jog":
        with pytest.raises(CalibrationBlockedError): session.jog(z=1)
    if action == "restore": session.restore_calibration_soft_limits()
    if action == "new_fault":
        gantry.status = "<Alarm|Pn:Z>"
        session.position()
    gantry.calls.clear()
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not gantry.calls


@pytest.mark.parametrize("status", ["<Idle|Pn:A>", "<Alarm|Pn:Y>", "Run", "Unknown"])
def test_new_physical_state_fails_before_home_and_consumes_permission(recovered, status):
    session, gantry = recovered
    gantry.status = status
    with pytest.raises((CalibrationBlockedError, GantryAlarmError)):
        session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not any(name == "home" for name, _ in gantry.calls)
    assert session._recovered_home_permission is None


def test_permission_expires_before_request(recovered, monkeypatch):
    session, gantry = recovered
    deadline = session._recovered_home_permission["expires_at"]
    monkeypatch.setattr("cubos.gantry.session.time.monotonic", lambda: deadline + 1)
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not gantry.calls


def test_expiry_during_preparation_still_blocks_actual_home(recovered, monkeypatch):
    session, gantry = recovered
    deadline = session._recovered_home_permission["expires_at"]
    now = [deadline - 1]
    monkeypatch.setattr("cubos.gantry.session.time.monotonic", lambda: now[0])
    original = gantry.set_grbl_setting

    def delayed_baseline(*args):
        original(*args)
        now[0] = deadline + 1

    gantry.set_grbl_setting = delayed_baseline
    with pytest.raises(CalibrationBlockedError, match="expired"):
        session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not any(name == "home" for name, _ in gantry.calls)
    assert session.position().status == "Home required"


def test_admitted_home_may_finish_after_ticket_expiry(recovered, monkeypatch):
    session, gantry = recovered
    deadline = session._recovered_home_permission["expires_at"]
    now = [deadline - 1]
    monkeypatch.setattr("cubos.gantry.session.time.monotonic", lambda: now[0])
    original = gantry.home

    def long_home(*, check_cancelled):
        original(check_cancelled=check_cancelled)
        now[0] = deadline + 90

    gantry.home = long_home
    assert session.home_after_calibration_recovery(jog_id="owned-fault").status == "Idle"
    assert sum(name == "home" for name, _ in gantry.calls) == 1


def test_stop_during_fresh_preflight_blocks_home(recovered):
    session, gantry = recovered
    original = gantry.get_calibration_position_info

    def interrupted_read():
        session.jog_cancel_interrupt()
        return original()

    gantry.get_calibration_position_info = interrupted_read
    with pytest.raises(GantryJogCancelledError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not any(name == "home" for name, _ in gantry.calls)


def test_stop_after_home_started_does_not_claim_abort_or_publish_success(recovered):
    session, gantry = recovered
    original = gantry.home

    def home_then_stop(*, check_cancelled):
        original(check_cancelled=check_cancelled)
        session.jog_cancel_interrupt()

    gantry.home = home_then_stop
    with pytest.raises(GantryJogCancelledError, match="may continue"):
        session.home_after_calibration_recovery(jog_id="owned-fault")
    assert sum(name == "home" for name, _ in gantry.calls) == 1
    assert session.position().status == "Home required"


def test_read_only_polling_does_not_create_or_revoke_permission(recovered):
    session, _ = recovered
    session.position()
    session.limit_recovery_context()
    session.read_grbl_settings()
    assert session.home_after_calibration_recovery(jog_id="owned-fault").status == "Idle"


@pytest.mark.parametrize("calibration,correlated,manual", [(False, True, False), (True, False, False), (True, True, True)])
def test_other_recovery_modes_never_grant_automatic_home(tmp_path, calibration, correlated, manual):
    session = GantrySession(gantry_factory=HomeRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    if calibration: session.prepare_calibration_origin()
    gantry = session._gantry
    gantry.trip_next = True
    session.jog(y=0.25, jog_id="owned-fault" if correlated else None)
    session.position()
    if manual: session.recover_calibration_limit_manual(axis="y", away_direction=-1, operator_confirmed=True)
    else: session.recover_calibration_limit(y=0.25, jog_id="owned-fault" if correlated else None)
    assert session._recovered_home_permission is None
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="owned-fault")


def test_scoped_close_before_home_revokes_only_matching_permission(recovered):
    session, gantry = recovered
    session.cancel_home_after_calibration_recovery(jog_id="old-foreign-id")
    assert session._recovered_home_permission is not None
    assert not gantry.calls
    session.cancel_home_after_calibration_recovery(jog_id="owned-fault")
    with pytest.raises(CalibrationBlockedError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert not gantry.calls


def test_scoped_close_during_preflight_denies_home_without_realtime_stop(recovered):
    session, gantry = recovered
    original = gantry.get_calibration_position_info

    def closed_read():
        session.cancel_home_after_calibration_recovery(jog_id="owned-fault")
        return original()

    gantry.get_calibration_position_info = closed_read
    with pytest.raises(GantryJogCancelledError): session.home_after_calibration_recovery(jog_id="owned-fault")
    assert session._active_recovered_home_id is None
    assert not any(name in ("home", "jog_cancel") for name, _ in gantry.calls)


def test_late_scoped_close_after_home_does_not_touch_another_motion(recovered):
    session, gantry = recovered
    session.home_after_calibration_recovery(jog_id="owned-fault")
    gantry.calls.clear()
    epoch = session._recovered_home_generation
    session.cancel_home_after_calibration_recovery(jog_id="owned-fault")
    assert session._recovered_home_generation == epoch
    assert not gantry.calls


def test_intervention_between_revoke_and_epoch_capture_cannot_be_adopted(recovered):
    session, gantry = recovered
    session.prepare_calibration_origin()
    gantry.trip_next = True
    session.jog(y=0.25, jog_id="interleaved-fault")
    session.position()
    original = session._revoke_recovered_home_permission
    intervened = False

    def revoke_then_manual_action():
        nonlocal intervened
        epoch = original()
        if not intervened:
            intervened = True
            session.set_grbl_setting("$23", 1)
        return epoch

    session._revoke_recovered_home_permission = revoke_then_manual_action
    result, _ = session.recover_calibration_limit(y=0.25, jog_id="interleaved-fault")
    assert result.commanded_delta["y"] == -5
    assert session._recovered_home_permission is None


def test_new_input_during_final_recovery_proof_never_mints_permission(recovered):
    session, gantry = recovered
    session.prepare_calibration_origin()
    gantry.trip_next = True
    session.jog(y=0.25, jog_id="second-fault")
    session.position()
    original = gantry.jog_for_limit_recovery

    def active_auxiliary_input(**kwargs):
        original(**kwargs)
        gantry.status = "<Idle|Pn:A>"

    gantry.jog_for_limit_recovery = active_auxiliary_input
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(y=0.25, jog_id="second-fault")
    assert session._recovered_home_permission is None


@pytest.mark.parametrize("method", ["home_after_calibration_recovery", "cancel_home_after_calibration_recovery"])
def test_direct_helpers_reject_missing_id_without_revoking_foreign_permission(recovered, method):
    session, gantry = recovered
    with pytest.raises(ValueError): getattr(session, method)(jog_id=None)
    assert session._recovered_home_permission is not None
    assert not gantry.calls
