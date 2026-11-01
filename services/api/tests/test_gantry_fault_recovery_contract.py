"""Exercise recovery snapshots through the API with a real offline session."""

import pytest

from cubos.gantry.session import GantrySession
from cubos_api.app import create_app
from cubos_api.routers import gantry as gantry_router
from tests.api_client import api_request


class Controller:
    def __init__(self):
        self.status = "<Idle|WPos:10,20,30>"
        self.coords = {"x": 10.0, "y": 20.0, "z": 30.0}
        self.calls = []
        self.fault_after_jog = False
        self.active_axis = "z"

    def get_position_info(self):
        return {"coords": self.coords, "work_pos": self.coords, "status": self.status, "raw_status": self.status}

    def get_status(self):
        return self.status

    def get_recovery_status(self):
        return self.status

    def get_recovery_position_info(self):
        return self.get_position_info()

    def _extract_status(self):
        return self.status

    def unlock(self):
        self.calls.append("unlock")

    def home(self):
        self.calls.append("home")
        self.status = "<Idle|WPos:10,20,30>"

    def reset_and_unlock(self):
        self.calls.append("reset_and_unlock")
        self.status = "<Idle|WPos:10,20,30>"

    def reset_and_unlock_for_limit_recovery(self, *, axis, check_cancelled=None):
        if check_cancelled is not None:
            check_cancelled()
        assert axis == self.active_axis
        self.reset_and_unlock()
        self.status = f"<Idle|WPos:10,20,30|Pn:{self.active_axis.upper()}>"
        return []

    def jog_for_limit_recovery(self, *, check_cancelled=None, **kwargs):
        if check_cancelled is not None:
            check_cancelled()
        return self.jog(**kwargs)

    def jog_cancel(self):
        self.calls.append("jog_cancel")

    def jog(self, **delta):
        self.calls.append(("jog", delta))
        if self.fault_after_jog:
            self.status = f"<Alarm|WPos:10,20,30|Pn:{self.active_axis.upper()}>"
            self.fault_after_jog = False
        else:
            self.status = "<Idle|WPos:10,20,30>"


def connected_app(monkeypatch):
    controller = Controller()
    session = GantrySession()
    session._gantry = controller
    session._connected_gantry_config = {
        "working_volume": {"x_min": 0, "x_max": 100, "y_min": 0, "y_max": 100, "z_min": 0, "z_max": 100}
    }
    monkeypatch.setattr(gantry_router, "_session", session)
    return create_app(), controller


def request(app, method, resource, **kwargs):
    return api_request(app, method, f"/api/v1/gantry/{resource}", **kwargs)


def test_fault_snapshot_stays_latched_and_unlock_requires_explicit_home(monkeypatch):
    app, controller = connected_app(monkeypatch)
    assert request(app, "GET", "position").json()["work_z"] == 30
    controller.status = "ALARM:3"
    fault = request(app, "GET", "position").json()
    assert fault["status"] == "ALARM:3"
    assert fault["work_z"] is None

    controller.status = "<Idle|WPos:10,20,30>"
    assert request(app, "GET", "position").json()["status"] == "ALARM:3"
    unlocked = request(app, "POST", "unlock")
    assert unlocked.status_code == 200
    assert unlocked.json()["status"] == "Home required"
    assert unlocked.json()["work_z"] is None
    assert "Home before moving or capturing calibration" in unlocked.json()["calibration_warning"]
    assert request(app, "POST", "jog", json={"z": 0.1}).status_code == 400
    assert request(app, "POST", "move-to-blocking", json={"x": 10, "y": 20, "z": 30}).status_code == 400
    assert controller.calls == ["unlock"]

    homed = request(app, "POST", "home")
    assert homed.status_code == 200
    assert homed.json()["work_z"] == 30
    assert homed.json()["calibration_warning"] is None
    assert controller.calls == ["unlock", "home"]


def test_unlock_check_limits_is_a_conflict_and_preserves_fault_snapshot(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.status = "ALARM:3"
    request(app, "GET", "position")
    controller.status = "[MSG:Check Limits]"
    response = request(app, "POST", "unlock")
    assert response.status_code == 409
    assert "Check Limits" in response.text
    snapshot = request(app, "GET", "position").json()
    assert "ALARM:3" in snapshot["status"]
    assert snapshot["work_z"] is None
    assert controller.calls == ["unlock"]


def test_explicit_bounded_z_recovery_preserves_home_required_snapshot(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.fault_after_jog = True
    assert request(app, "POST", "jog", json={"z": -0.1}).status_code == 200
    assert "Pn:Z" in request(app, "GET", "position").json()["status"]
    response = request(app, "POST", "calibration/recover-limit", json={"z": -0.1})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "recovered"
    assert response.json()["attempts"] == 1
    snapshot = request(app, "GET", "position").json()
    assert snapshot["status"] == "Home required"
    assert snapshot["work_z"] is None
    assert controller.calls.count("reset_and_unlock") == 1
    jogs = [call[1] for call in controller.calls if isinstance(call, tuple)]
    assert len(jogs) == 2
    assert jogs[-1]["z"] == 5
    assert "home" not in controller.calls


def test_recovery_without_matching_failed_jog_or_confirmed_z_pin_does_not_move(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.status = "ALARM:3"
    request(app, "GET", "position")
    assert request(app, "POST", "calibration/recover-limit", json={"z": -0.1}).status_code == 409
    assert request(app, "POST", "calibration/recover-limit", json={"x": -0.1}).status_code == 409
    assert controller.calls == []


def test_authoritative_y_context_is_read_only_and_known_recovery_uses_its_candidate(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.active_axis = "y"
    controller.fault_after_jog = True
    assert request(app, "POST", "jog", json={"y": 0.5}).status_code == 200
    request(app, "GET", "position")
    prior_calls = list(controller.calls)
    response = request(app, "GET", "calibration/recovery-context")
    assert response.status_code == 200
    context = response.json()
    assert context["active_limit_axes"] == ["y"]
    assert context["failed_jog_delta"] == {"x": 0, "y": 0.5, "z": 0}
    assert context["pull_off_delta"] == {"x": 0, "y": -5, "z": 0}
    assert context["eligible"] is True
    assert controller.calls == prior_calls
    recovered = request(app, "POST", "calibration/recover-limit", json=context["failed_jog_delta"])
    assert recovered.status_code == 200
    assert recovered.json()["mode"] == "known_jog"
    assert recovered.json()["commanded_delta"] == {"x": 0, "y": -5, "z": 0}
    assert recovered.json()["failed_delta"] == context["failed_jog_delta"]
    assert controller.calls[-1] == ("jog", {"x": 0.0, "y": -5.0, "z": 0.0, "feed_rate": 100.0})


def test_manual_y_recovery_preserves_honest_history_and_home_requirement(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.active_axis = "y"
    controller.status = "<Alarm|WPos:10,20,30|Pn:Y>"
    context = request(app, "GET", "calibration/recovery-context").json()
    assert context["manual_available"] is True
    assert context["failed_jog_delta"] is None
    assert context["eligible"] is False
    assert controller.calls == []
    response = request(app, "POST", "calibration/recover-limit/manual", json={"axis": "y", "away_direction": -1, "operator_confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "manual"
    assert response.json()["failed_delta"] is None
    assert response.json()["commanded_delta"] == {"x": 0, "y": -1, "z": 0}
    assert request(app, "GET", "position").json()["status"] == "Home required"
    assert controller.calls[-1] == ("jog", {"x": 0.0, "y": -1.0, "z": 0.0, "feed_rate": 100.0})
    assert "home" not in controller.calls


@pytest.mark.parametrize("update", [
    {"axis": "q"}, {"away_direction": 0}, {"away_direction": True},
    {"operator_confirmed": "true"}, {"pull_off_mm": 20}, {"feed_rate": 900},
])
def test_manual_recovery_rejects_ambiguous_or_extra_controls(monkeypatch, update):
    app, controller = connected_app(monkeypatch)
    body = {"axis": "y", "away_direction": -1, "operator_confirmed": True, **update}
    response = request(app, "POST", "calibration/recover-limit/manual", json=body)
    assert response.status_code == 422
    assert controller.calls == []


def test_manual_recovery_without_confirmation_does_not_move(monkeypatch):
    app, controller = connected_app(monkeypatch)
    response = request(app, "POST", "calibration/recover-limit/manual", json={"axis": "y", "away_direction": -1, "operator_confirmed": False})
    assert response.status_code == 400
    assert controller.calls == []


@pytest.mark.parametrize("method,resource,body", [
    ("GET", "calibration/recovery-context", None),
    ("POST", "calibration/recover-limit", {"y": 0.5}),
    ("POST", "calibration/recover-limit/manual", {"axis": "y", "away_direction": -1, "operator_confirmed": True}),
])
def test_recovery_requests_do_not_queue_behind_a_running_protocol(monkeypatch, method, resource, body):
    app, controller = connected_app(monkeypatch)
    gantry_router.begin_run(protocol_file="running.yaml")
    response = request(app, method, resource, json=body)
    assert response.status_code == 409
    assert "busy running a protocol" in response.text
    assert controller.calls == []


@pytest.mark.parametrize("method,resource,body,session_method", [
    ("GET", "calibration/recovery-context", None, "limit_recovery_context"),
    ("POST", "calibration/recover-limit/manual", {"axis": "y", "away_direction": -1, "operator_confirmed": True}, "recover_calibration_limit_manual"),
])
def test_recovery_connection_failure_stays_503_even_if_message_mentions_alarm(monkeypatch, method, resource, body, session_method):
    from cubos.gantry.gantry_driver.exceptions import MillConnectionError

    app, controller = connected_app(monkeypatch)
    def fail(**kwargs):
        raise MillConnectionError("Connection lost while reading a hard limit alarm")
    monkeypatch.setattr(gantry_router.current_session(), session_method, fail)
    response = request(app, method, resource, json=body)
    assert response.status_code == 503
    assert "Controller connection lost" in response.text
    assert controller.calls == []


@pytest.mark.parametrize("blocking", [False, True])
def test_owned_jog_correlation_round_trip_rejects_foreign_and_duplicate_recovery(monkeypatch, blocking):
    app, controller = connected_app(monkeypatch)
    controller.active_axis = "y"
    controller.fault_after_jog = True
    response = request(app, "POST", "jog-blocking" if blocking else "jog", json={"y": 0.25, "jog_id": "open-wizard-1"})
    assert response.status_code == (409 if blocking else 200), response.text
    request(app, "GET", "position")
    context = request(app, "GET", "calibration/recovery-context").json()
    assert context["failed_jog_id"] == "open-wizard-1"
    assert context["failed_jog_delta"] == {"x": 0, "y": 0.25, "z": 0}
    assert context["eligible"]
    assert "jog_id" not in controller.calls[0][1]
    before = list(controller.calls)
    wrong_vector = request(app, "POST", "calibration/recover-limit", json={"y": -0.25, "jog_id": "open-wizard-1"})
    assert wrong_vector.status_code == 409
    assert controller.calls == before

    wrong = request(app, "POST", "calibration/recover-limit", json={"y": 0.25, "jog_id": "foreign-wizard"})
    assert wrong.status_code == 409
    assert controller.calls == before
    recovered = request(app, "POST", "calibration/recover-limit", json={"y": 0.25, "jog_id": "open-wizard-1"})
    assert recovered.status_code == 200, recovered.text
    assert request(app, "GET", "position").json()["status"] == "Home required"
    after = list(controller.calls)
    repeated = request(app, "POST", "calibration/recover-limit", json={"y": 0.25, "jog_id": "open-wizard-1"})
    assert repeated.status_code == 409
    assert controller.calls == after
    assert controller.calls.count("reset_and_unlock") == 1


@pytest.mark.parametrize("route", ["jog", "jog-blocking", "calibration/recover-limit"])
@pytest.mark.parametrize("jog_id", ["", "  ", "x" * 129, 42, True])
def test_invalid_correlation_is_rejected_by_api_before_controller_calls(monkeypatch, route, jog_id):
    app, controller = connected_app(monkeypatch)
    response = request(app, "POST", route, json={"y": 0.25, "jog_id": jog_id})
    assert response.status_code == 422, response.text
    assert not controller.calls


def test_stop_revokes_auto_correlation_while_explicit_legacy_recovery_remains_available(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.active_axis = "y"
    controller.fault_after_jog = True
    assert request(app, "POST", "jog", json={"y": 0.25, "jog_id": "cancelled-wizard"}).status_code == 200
    request(app, "GET", "position")
    assert request(app, "POST", "jog-cancel").status_code == 200
    context = request(app, "GET", "calibration/recovery-context").json()
    assert context["failed_jog_id"] is None
    assert context["eligible"]
    before = list(controller.calls)
    assert request(app, "POST", "calibration/recover-limit", json={"y": 0.25, "jog_id": "cancelled-wizard"}).status_code == 409
    assert controller.calls == before
    legacy = request(app, "POST", "calibration/recover-limit", json={"y": 0.25})
    assert legacy.status_code == 200, legacy.text


def test_fresh_idle_context_retires_auto_correlation_before_later_idle_switch_event(monkeypatch):
    app, controller = connected_app(monkeypatch)
    controller.active_axis = "y"
    assert request(app, "POST", "jog", json={"y": 0.25, "jog_id": "completed-ui-step"}).status_code == 200
    healthy = request(app, "GET", "calibration/recovery-context")
    assert healthy.status_code == 200
    assert healthy.json()["raw_status"].startswith("<Idle")
    controller.status = "<Alarm|Pn:Y>"
    fault = request(app, "GET", "calibration/recovery-context").json()
    assert fault["failed_jog_id"] is None
    assert fault["manual_available"]
    before = list(controller.calls)
    response = request(app, "POST", "calibration/recover-limit", json={"y": 0.25, "jog_id": "completed-ui-step"})
    assert response.status_code == 409
    assert controller.calls == before
