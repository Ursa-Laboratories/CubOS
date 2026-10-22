import json
from types import SimpleNamespace

import pytest

from cubos_sila.errors import BackendAuthenticationFailed, BackendError, RunCancelled, RunFailed
from cubos_sila.features import CubStatus, ProtocolExecution


class Status:
    def __init__(self):
        self.command_execution = SimpleNamespace(command_execution_uuid="execution-123")
        self.updates = []
        self.started = False

    def start(self):
        self.started = True

    def update(self, **kwargs):
        self.updates.append(kwargs)


class Intermediate:
    def __init__(self):
        self.values = []

    def send(self, value):
        self.values.append(value)


class Backend:
    def __init__(self, state="succeeded"):
        self.state = state
        self.submissions = []
        self.cursors = []

    async def execute_protocol(self, name, run_id, *, execution_id):
        self.submissions.append((name, run_id, execution_id))
        return {"run_id": run_id, "state": "queued"}

    async def get_plan(self, run_id):
        return [{"index": 0}, {"index": 1}]

    async def get_events(self, run_id, after):
        self.cursors.append(after)
        return [
            {"sequence": 1, "kind": "step", "data": {"index": 0, "substep": "cycle0:fill", "outcome": "completed"}},
            {"sequence": 2, "kind": "step", "data": {"index": 0, "substep": None, "outcome": "completed"}},
            {"sequence": 3, "kind": "step", "data": {"index": 0, "substep": None, "outcome": "completed"}},
            {"sequence": 4, "kind": "step", "data": {"index": 1, "substep": None, "outcome": "skipped"}},
        ]

    async def get_run(self, run_id):
        return {"run_id": run_id, "state": self.state, "error": "controller failed" if self.state == "failed" else None}


async def test_progress_counts_distinct_top_level_steps_only():
    backend = Backend()
    intermediate = Intermediate()
    status = Status()
    result = await ProtocolExecution(backend).execute_protocol(
        "preset", "stable-run", status=status, intermediate=intermediate,
    )
    assert backend.submissions == [("preset", "stable-run", "execution-123")]
    assert intermediate.values[0].run_id == "stable-run"
    assert intermediate.values[0].state == "queued"
    progress = {value.event_sequence: value for value in intermediate.values if value.event_sequence}
    assert progress[1].completed_steps == 0
    assert progress[2].completed_steps == 1
    assert progress[3].completed_steps == 1
    assert progress[4].completed_steps == 2
    assert progress[4].total_steps == 2
    assert status.updates[-1]["progress"] == 1
    assert result[:2] == ("stable-run", "succeeded")
    assert json.loads(result[2])["run_id"] == "stable-run"


@pytest.mark.parametrize("state,error", [("failed", RunFailed), ("cancelled", RunCancelled)])
async def test_terminal_failure_and_cancellation_are_distinct(state, error):
    intermediate = Intermediate()
    with pytest.raises(error, match="stable-run"):
        await ProtocolExecution(Backend(state)).execute_protocol(
            "preset", "stable-run", status=Status(), intermediate=intermediate,
        )
    assert intermediate.values[-1].state == state


async def test_completion_between_polls_drains_the_final_step_events():
    class CompletingBackend(Backend):
        finished = False

        async def get_run(self, run_id):
            self.finished = True
            return await super().get_run(run_id)

        async def get_events(self, run_id, after):
            if not self.finished:
                return []
            return await super().get_events(run_id, after)

    intermediate = Intermediate()
    await ProtocolExecution(CompletingBackend()).execute_protocol(
        "preset", "stable-run", status=Status(), intermediate=intermediate,
    )
    assert intermediate.values[-1].completed_steps == 2
    assert intermediate.values[-1].event_sequence == 4


async def test_status_reports_version_and_unknown_without_inferring_readiness():
    async def observation():
        return {"api_available": True, "version": {"cubos_version": "1.2.3"}, "hardware_connected": None}

    feature = CubStatus(SimpleNamespace(status=observation))
    assert await feature.software_version() == "1.2.3"
    assert await feature.service_available() is True
    assert await feature.hardware_connection_state() == "unknown"
    assert await feature.execution_state() == "unknown"
    assert await feature.active_run_id() == ""


async def test_status_auth_failure_is_a_declared_type():
    async def observation():
        raise BackendError("auth", "API credentials rejected")

    with pytest.raises(BackendAuthenticationFailed):
        await CubStatus(SimpleNamespace(status=observation)).service_available()
