"""The automatic Home route requires the authoritative recovered jog ID."""
from unittest.mock import Mock

import pytest

from cubos.gantry.session import CalibrationBlockedError, GantryJogCancelledError, GantryPositionSnapshot
from cubos_api.app import create_app
from cubos_api.routers import gantry as router
from tests.api_client import api_request
from tests.test_gantry_router import FakeSession


@pytest.fixture
def session(monkeypatch):
    session = FakeSession()
    session.home_after_calibration_recovery = Mock(return_value=GantryPositionSnapshot(connected=True, status="Idle", work_x=300, work_y=200, work_z=80))
    monkeypatch.setattr(router, "_session", session)
    return session


def test_exact_recovered_id_is_delegated_to_core(session):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/home-after-recovery", json={"jog_id": "owned-recovered"})
    assert response.status_code == 200
    assert response.json()["work_z"] == 80
    session.home_after_calibration_recovery.assert_called_once_with(jog_id="owned-recovered")


@pytest.mark.parametrize("body", [{}, {"jog_id": ""}, {"jog_id": " "}, {"jog_id": 123}, {"jog_id": "x" * 129}, {"jog_id": "owned", "x": 1}])
def test_missing_or_invalid_capability_cannot_reach_controller(session, body):
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/home-after-recovery", json=body)
    assert response.status_code == 422
    session.home_after_calibration_recovery.assert_not_called()


@pytest.mark.parametrize("failure,code", [(CalibrationBlockedError("Use manual Home"), 400), (GantryJogCancelledError("Already started Home may continue"), 409)])
def test_refused_or_cancelled_home_is_non_success(session, failure, code):
    session.home_after_calibration_recovery.side_effect = failure
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/home-after-recovery", json={"jog_id": "owned"})
    assert response.status_code == code


def test_close_revocation_is_scoped_without_issuing_home(session):
    session.cancel_home_after_calibration_recovery = Mock()
    response = api_request(create_app(), "POST", "/api/v1/gantry/calibration/home-after-recovery/cancel", json={"jog_id": "old-owned"})
    assert response.status_code == 200
    session.cancel_home_after_calibration_recovery.assert_called_once_with(jog_id="old-owned")
    session.home_after_calibration_recovery.assert_not_called()
