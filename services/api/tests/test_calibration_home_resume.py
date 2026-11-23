"""The API accepts no client pose or implicit recovery/hover confirmation."""
from unittest.mock import Mock

import pytest

from cubos.gantry.session import GantryPositionSnapshot, GantryJogCancelledError
from cubos_api.app import create_app
from cubos_api.routers import gantry as router
from tests.api_client import api_request
from tests.test_gantry_router import FakeSession


SETUP = dict(instrument="pipette", tip_attached=True, tip_length_mm=40, block_height_mm=35)
RECORD = dict(**SETUP, fixture_confirmed=True, clearance_confirmed=True, path_clear=True, jog_ids=["owned-step"])
RETURN = dict(**SETUP, token="server-token", setup_unchanged=True, path_clear=True)


@pytest.fixture
def session(monkeypatch):
    session = FakeSession()
    position = GantryPositionSnapshot(connected=True, status="Idle", work_x=1, work_y=2, work_z=3)
    session.record_calibration_hover = Mock(return_value={"token": "server-token", "position": position})
    session.home_and_resume_calibration = Mock(return_value={"position": position, "hover_available": False, "blocked_reason": "Approach manually."})
    session.return_to_calibration_hover = Mock(return_value={"position": position})
    session.cancel_calibration_hover = Mock()
    monkeypatch.setattr(router, "_session", session)
    return session


def test_record_uses_server_pose_and_passes_owned_ids(session):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/hover", json=RECORD)
    assert response.status_code == 200
    assert response.json()["token"] == "server-token"
    assert response.json()["position"]["work_x"] == 1
    session.record_calibration_hover.assert_called_once_with(**RECORD)


def test_home_without_token_preserves_manual_fallback(session):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/home-resume", json={})
    assert response.status_code == 200
    assert not response.json()["hover_available"]
    session.home_and_resume_calibration.assert_called_once_with(token=None)


def test_return_requires_explicit_token_and_renewed_setup_confirmation(session):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/return-hover", json=RETURN)
    assert response.status_code == 200
    session.return_to_calibration_hover.assert_called_once_with(**RETURN)


def test_cancel_is_scoped_to_token_and_does_not_send_motion(session):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/hover/cancel", json={"token": "old-token"})
    assert response.status_code == 200
    session.cancel_calibration_hover.assert_called_once_with("old-token")
    session.return_to_calibration_hover.assert_not_called()
    session.home_and_resume_calibration.assert_not_called()


@pytest.mark.parametrize("patch", [{"x": 10}, {"fixture_confirmed": 1}, {"path_clear": False}, {"clearance_confirmed": "true"}, {"jog_ids": []}, {"tip_length_mm": -1}, {"block_height_mm": 0}])
def test_unproven_record_requests_never_reach_core(session, patch):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/hover", json=RECORD | patch)
    assert response.status_code == 422
    session.record_calibration_hover.assert_not_called()


@pytest.mark.parametrize("patch", [{"x": 10}, {"setup_unchanged": 1}, {"path_clear": False}, {"token": ""}])
def test_unconfirmed_return_never_reaches_core(session, patch):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/return-hover", json=RETURN | patch)
    assert response.status_code == 422
    session.return_to_calibration_hover.assert_not_called()


def test_cancelled_return_is_non_success(session):
    session.return_to_calibration_hover.side_effect = GantryJogCancelledError("Return cancelled")
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/return-hover", json=RETURN)
    assert response.status_code == 409
