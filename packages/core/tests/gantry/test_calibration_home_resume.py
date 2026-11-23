"""Home resumes manual calibration; optional return replays only taught motion."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
import yaml

from cubos.gantry.errors import MillConnectionError
from cubos.gantry.session import CalibrationBlockedError, GantryAlarmError, GantryJogCancelledError, GantrySession
from tests.gantry.test_session import FakeGantry


SETUP = dict(instrument="pipette", tip_attached=True, tip_length_mm=40.0, block_height_mm=35.0)
CONFIRMED = dict(fixture_confirmed=True, clearance_confirmed=True, path_clear=True)
RETURN = dict(setup_unchanged=True, path_clear=True)
FRAME = {"G54": [-405.0, -400.0, -90.0], "G92": [0.0, 0.0, 0.0], "TLO": [0.0]}


class ResumeGantry(FakeGantry):
    def __init__(self, config=None):
        super().__init__(config)
        self.frame = deepcopy(FRAME)
        self.grbl_settings.update({"$3": "0", "$13": "0", "$20": "1", "$21": "1", "$23": "0", "$27": "1", "$100": "800", "$101": "800", "$102": "800", "$110": "2000", "$111": "2000", "$112": "1000", "$130": "406", "$131": "401", "$132": "91"})
        self.home_pose = {"x": 405.0, "y": 400.0, "z": 90.0}

    def home(self):
        super().home()
        self.status = "Idle"
        self.coords = dict(self.home_pose)

    def read_calibration_frame(self):
        self.calls.append(("read_calibration_frame", None))
        return deepcopy(self.frame)

    def soft_limits_enabled(self):
        return self.grbl_settings["$20"] == "1"

    def set_soft_limits_enabled(self, enabled):
        self.grbl_settings["$20"] = "1" if enabled else "0"

    def get_calibration_position_info(self):
        return {"coords": dict(self.coords), "work_pos": dict(self.coords), "status": self.status,
                "raw_status": self.status if self.status.startswith("<") else f"<{self.status}|WPos:{self.coords['x']},{self.coords['y']},{self.coords['z']}>"}

    def jog_for_calibration(self, *, check_cancelled, **kwargs):
        check_cancelled()
        return self.jog(**kwargs)


@pytest.fixture
def runtime(tmp_path):
    body = {"serial_port": "/dev/test", "gantry_type": "genmitsu_4040_pro_max",
            "cnc": {"factory_z_travel_mm": 90},
            "working_volume": {"x_min": 0, "x_max": 405, "y_min": 0, "y_max": 400, "z_min": 0, "z_max": 90},
            "grbl_settings": {"homing_pull_off": 1},
            "instruments": {"pipette": {"type": "pipette", "vendor": "sartorius", "model": "picus", "offset_x": 0, "offset_y": 0, "depth": 0}}}
    path = tmp_path / "gantry.yaml"
    path.write_text(yaml.safe_dump(body))
    session = GantrySession(gantry_factory=ResumeGantry, sleep=lambda _: None)
    session.connect(path, filename=path.name)
    session.prepare_calibration_origin()
    return session, session._gantry


def teach(session, deltas=None):
    ids = []
    for index, delta in enumerate(deltas or [{"x": -10}, {"y": -20}, {"z": -5}]):
        jog_id = f"owned-{index}"
        session.jog_blocking(**delta, jog_id=jog_id)
        ids.append(jog_id)
    return session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=ids)["token"]


def test_station_scale_taught_path_replays_exact_corners_without_geometry(runtime):
    session, gantry = runtime
    route = [{"x": -100}] * 4 + [{"y": -100}] * 4 + [{"z": -50}, {"z": -20}]
    token = teach(session, route)
    taught = [kwargs for name, kwargs in gantry.calls if name == "jog"]
    assert not gantry.config["instruments"]["pipette"].get("motion_envelope")
    gantry.calls.clear()
    result = session.home_and_resume_calibration(token=token)
    assert result["hover_available"]
    assert sum(name == "home" for name, _ in gantry.calls) == 1
    assert not any(name == "jog" for name, _ in gantry.calls)
    gantry.calls.clear()
    result = session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    replay = [kwargs for name, kwargs in gantry.calls if name == "jog"]
    assert [{key: value for key, value in item.items() if key != "feed_rate"} for item in replay] == [{key: value for key, value in item.items() if key != "feed_rate"} for item in taught]
    assert all(item["feed_rate"] == (500 if item["z"] else 1000) for item in replay)
    assert result["position"].work_x == 5
    assert result["position"].work_y == 0
    assert result["position"].work_z == 20
    assert not any(name == "home" for name, _ in gantry.calls)
    before = list(gantry.calls)
    with pytest.raises(CalibrationBlockedError):
        session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    assert gantry.calls == before


@pytest.mark.parametrize("change", ["frame", "settings", "home", "config"])
def test_changed_proof_allows_home_but_not_hover_replay(runtime, change):
    session, gantry = runtime
    token = teach(session)
    if change == "frame": gantry.frame["G54"][0] += 1
    if change == "settings": gantry.grbl_settings["$100"] = "801"
    if change == "home": gantry.home_pose["x"] -= 1
    if change == "config": session._connected_gantry_config["instruments"]["pipette"]["depth"] = 1
    gantry.calls.clear()
    result = session.home_and_resume_calibration(token=token)
    assert result["position"].status == "Idle"
    assert not result["hover_available"]
    assert not any(name == "jog" for name, _ in gantry.calls)


def test_expired_checkpoint_never_traps_manual_home_resume(runtime):
    session, gantry = runtime
    result = session.home_and_resume_calibration(token="expired")
    assert not result["hover_available"]
    assert result["position"].status == "Idle"
    assert session.calibration_active


@pytest.mark.parametrize("field,value", [("tip_length_mm", 41), ("tip_attached", False), ("block_height_mm", 36), ("setup_unchanged", False), ("path_clear", False)])
def test_changed_setup_cannot_send_first_replay_segment(runtime, field, value):
    session, gantry = runtime
    token = teach(session)
    session.home_and_resume_calibration(token=token)
    gantry.calls.clear()
    with pytest.raises((ValueError, CalibrationBlockedError)):
        session.return_to_calibration_hover(token=token, **(SETUP | RETURN | {field: value}))
    assert not any(name == "jog" for name, _ in gantry.calls)


def test_stop_during_per_leg_fresh_read_cannot_adopt_new_generation(runtime):
    session, gantry = runtime
    token = teach(session)
    session.home_and_resume_calibration(token=token)
    original = gantry.get_calibration_position_info
    count = 0

    def read():
        nonlocal count
        count += 1
        if count == 2:
            session.jog_cancel_interrupt()
        return original()

    gantry.get_calibration_position_info = read
    gantry.calls.clear()
    with pytest.raises(GantryJogCancelledError):
        session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    assert not any(name == "jog" for name, _ in gantry.calls)


def test_unrelated_jog_or_wrong_owned_id_cannot_be_registered(runtime):
    session, _ = runtime
    session.jog_blocking(x=-10, jog_id="another-client")
    with pytest.raises(CalibrationBlockedError):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["wizard-only"])
    session.jog(x=-1)
    with pytest.raises(CalibrationBlockedError):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["another-client"])


def test_late_old_token_cancel_does_not_revoke_new_checkpoint(runtime):
    session, _ = runtime
    old = teach(session)
    session.prepare_calibration_origin()
    new = teach(session)
    session.cancel_calibration_hover(old)
    assert session.home_and_resume_calibration(token=new)["hover_available"]


@pytest.mark.parametrize("delta", [{"x": 1}, {"y": -401}, {"z": -91}])
def test_taught_endpoints_outside_homed_usable_volume_never_register(runtime, delta):
    session, _ = runtime
    session.jog_blocking(**delta, jog_id="outside-usable")
    with pytest.raises(CalibrationBlockedError, match="usable travel"):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["outside-usable"])


@pytest.mark.parametrize("status", ["<Idle|Pn:A>", "<Idle|Pn:Z>", "<Alarm|Pn:Y>"])
def test_active_inputs_block_home_and_return_before_motion(runtime, status):
    session, gantry = runtime
    token = teach(session)
    gantry.status = status
    gantry.get_calibration_position_info = lambda: {"status": status, "raw_status": status, "work_pos": dict(gantry.coords)}
    gantry.calls.clear()
    with pytest.raises(GantryAlarmError): session.home_and_resume_calibration(token=token)
    assert not any(name in ("home", "jog") for name, _ in gantry.calls)


@pytest.mark.parametrize("action", ["stop", "setting", "move", "work_coordinates", "disconnect"])
def test_invalidating_actions_never_resurrect_a_frozen_checkpoint(runtime, action):
    session, gantry = runtime
    token = teach(session)
    if action == "stop": session.jog_cancel_interrupt()
    if action == "setting": session.set_grbl_setting("$110", 1500)
    if action == "move": session.move_to_blocking(x=100, y=100, z=50)
    if action == "work_coordinates": session.set_work_coordinates(x=1)
    if action == "disconnect": session.disconnect()
    assert session._hover_checkpoint is None


def test_taught_axis_switches_and_reversals_are_not_simplified(runtime):
    session, gantry = runtime
    route = [{"x": -30}, {"y": -20}, {"x": 10}, {"z": -15}, {"y": 5}]
    token = teach(session, route)
    session.home_and_resume_calibration(token=token)
    gantry.calls.clear()
    session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    replay = [kwargs for name, kwargs in gantry.calls if name == "jog"]
    assert [{axis: item[axis] for axis in "xyz"} for item in replay] == [{axis: delta.get(axis, 0) for axis in "xyz"} for delta in route]


@pytest.mark.parametrize("failure", ["unknown", "cancelled", "alarm"])
def test_failed_or_cancelled_teaching_cannot_register(runtime, failure):
    from cubos.gantry.errors import JogAcceptanceUnknownError

    session, gantry = runtime
    session.jog_blocking(x=-10, jog_id="owned-first")
    if failure == "cancelled":
        session.jog_cancel_interrupt()
    else:
        error = JogAcceptanceUnknownError("missing own ACK") if failure == "unknown" else GantryAlarmError("ALARM:3")
        gantry.jog_for_calibration = Mock(side_effect=error)
        with pytest.raises(type(error)):
            session.jog_blocking(y=-10, jog_id="failed-step")
    with pytest.raises((CalibrationBlockedError, GantryAlarmError)):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned-first"])


def test_frozen_checkpoint_survives_only_the_expected_limit_fault_until_verified_home(runtime):
    session, gantry = runtime
    token = teach(session)
    session._latch_alarm_locked("ALARM:3; Pn:Y")
    assert session._hover_checkpoint["token"] == token
    assert session._calibration_taught_path is None
    gantry.status = "Idle"
    gantry.coords["y"] -= 5
    result = session.home_and_resume_calibration(token=token)
    assert result["hover_available"]


@pytest.mark.parametrize("stage", ["registration", "record", "home_proof", "return_proof"])
def test_connection_loss_never_publishes_or_reuses_checkpoint(runtime, stage):
    session, gantry = runtime
    failure = MillConnectionError("USB unavailable")
    if stage == "registration":
        gantry.read_calibration_frame = Mock(side_effect=failure)
        operation = session.prepare_calibration_origin
    elif stage == "record":
        session.jog_blocking(x=-10, jog_id="owned-first")
        gantry.read_calibration_frame = Mock(side_effect=failure)
        operation = lambda: session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned-first"])
    else:
        token = teach(session)
        if stage == "return_proof": session.home_and_resume_calibration(token=token)
        gantry.read_calibration_frame = Mock(side_effect=failure)
        operation = (lambda: session.home_and_resume_calibration(token=token)) if stage == "home_proof" else (lambda: session.return_to_calibration_hover(token=token, **SETUP, **RETURN))
    with pytest.raises(MillConnectionError) as caught:
        operation()
    assert caught.value is failure
    assert session._hover_checkpoint is None


def test_multi_tool_has_manual_home_resume_but_no_hover_registration(runtime):
    session, gantry = runtime
    session._connected_gantry_config["instruments"]["other"] = {"type": "camera", "vendor": "usb"}
    assert not session.home_and_resume_calibration()["hover_available"]
    session.jog_blocking(x=-10, jog_id="owned-first")
    with pytest.raises(CalibrationBlockedError, match="one deck-frame tool"):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned-first"])


def test_matching_token_cancel_stops_its_active_segment_and_never_sends_next(runtime):
    session, gantry = runtime
    token = teach(session)
    session.home_and_resume_calibration(token=token)
    gantry.calls.clear()

    def partial_jog(*, check_cancelled, **kwargs):
        gantry.calls.append(("jog", kwargs))
        gantry.coords["x"] += kwargs["x"] / 2
        session.cancel_calibration_hover(token)
        check_cancelled()

    gantry.jog_for_calibration = partial_jog
    with pytest.raises(GantryJogCancelledError):
        session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    assert sum(name == "jog_cancel" for name, _ in gantry.calls) == 1
    assert sum(name == "jog" for name, _ in gantry.calls) == 1
    assert session._hover_active_token is None
    assert session._hover_checkpoint is None


def test_late_old_token_cannot_stop_a_new_active_motion(runtime):
    session, gantry = runtime
    session._hover_active_token = "new-active-token"
    original = (session._hover_generation, session._jog_cancel_generation)
    gantry.calls.clear()
    session.cancel_calibration_hover("old-token")
    assert not gantry.calls
    assert (session._hover_generation, session._jog_cancel_generation) == original


def test_registered_hover_survives_correlated_limit_pull_off_home_and_explicit_return(runtime):
    session, gantry = runtime
    token = teach(session)
    normal_jog = gantry.jog_for_calibration

    def trip_after_ack(*, check_cancelled, **kwargs):
        check_cancelled()
        gantry.jog(**kwargs)
        gantry.status = "<Alarm|Pn:Y>"

    gantry.jog_for_calibration = trip_after_ack
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(y=0.25, jog_id="owned-limit-step")
    assert session.limit_recovery_context().failed_jog_id == "owned-limit-step"
    assert session._hover_checkpoint["token"] == token

    def reset(*, axis, check_cancelled):
        check_cancelled()
        assert axis == "y"
        gantry.calls.append(("guarded_reset", axis))
        gantry.status = "<Idle|Pn:Y>"

    def pull_off(*, check_cancelled, **kwargs):
        check_cancelled()
        gantry.jog(**kwargs)
        gantry.status = "Idle"

    gantry.reset_and_unlock_for_limit_recovery = reset
    gantry.jog_for_limit_recovery = pull_off
    result, _ = session.recover_calibration_limit(y=0.25, jog_id="owned-limit-step")
    assert result.pull_off_delta == {"x": 0, "y": -5, "z": 0}
    assert session.position().status == "Home required"
    assert session._hover_checkpoint["token"] == token
    gantry.jog_for_calibration = normal_jog
    resumed = session.home_and_resume_calibration(token=token)
    assert resumed["hover_available"]
    assert resumed["position"].status == "Idle"
    returned = session.return_to_calibration_hover(token=token, **SETUP, **RETURN)
    assert returned["position"].work_x == 395
    assert returned["position"].work_y == 380
    assert returned["position"].work_z == 85
    assert sum(name == "guarded_reset" for name, _ in gantry.calls) == 1


@pytest.mark.parametrize("report_inches", [None, "1"])
def test_unknown_or_inches_report_units_never_register_hover(runtime, report_inches):
    session, gantry = runtime
    session.jog_blocking(x=-10, jog_id="owned-step")
    if report_inches is None: gantry.grbl_settings.pop("$13")
    else: gantry.grbl_settings["$13"] = report_inches
    with pytest.raises(CalibrationBlockedError, match="settings"):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned-step"])
    assert session._hover_checkpoint is None


@pytest.mark.parametrize("bad_pose", [None, {"x": float("nan"), "y": 0, "z": 0}])
def test_record_requires_fresh_finite_idle_pose(runtime, bad_pose):
    session, gantry = runtime
    session.jog_blocking(x=-10, jog_id="owned")
    gantry.get_calibration_position_info = lambda: {"status": "Idle", "raw_status": "<Idle>", "work_pos": bad_pose}
    with pytest.raises(CalibrationBlockedError, match="fresh Idle"):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned"])
    assert session._hover_checkpoint is None


def test_registration_cannot_resurrect_after_stop_during_record(runtime):
    session, gantry = runtime
    session.jog_blocking(x=-10, jog_id="owned")
    original = gantry.read_calibration_frame

    def frame():
        session.jog_cancel_interrupt()
        return original()

    gantry.read_calibration_frame = frame
    with pytest.raises((CalibrationBlockedError, GantryJogCancelledError)):
        session.record_calibration_hover(**SETUP, **CONFIRMED, jog_ids=["owned"])
    assert session._hover_checkpoint is None


def test_frame_connection_failure_after_home_propagates_unchanged(runtime):
    session, gantry = runtime
    token = teach(session)
    failure = MillConnectionError("lost frame transport")
    original = gantry.read_calibration_frame
    calls = 0

    def frame():
        nonlocal calls
        calls += 1
        if calls == 2: raise failure
        return original()

    gantry.read_calibration_frame = frame
    with pytest.raises(MillConnectionError) as caught:
        session.home_and_resume_calibration(token=token)
    assert caught.value is failure
    assert session._hover_checkpoint is None


def test_direct_missing_confirmation_never_reads_pose_or_sends_motion(runtime):
    session, gantry = runtime
    session.jog_blocking(x=-10, jog_id="owned")
    gantry.calls.clear()
    with pytest.raises(ValueError, match="Confirm"):
        session.record_calibration_hover(**SETUP, **(CONFIRMED | {"path_clear": False}), jog_ids=["owned"])
    assert not gantry.calls
