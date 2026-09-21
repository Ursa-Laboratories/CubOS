"""Concurrency tests for the persistent contents ownership boundary."""

from __future__ import annotations

import threading

import pytest

from cubos_api.services.contents_ownership import (
    ContentsOwnership,
    ContentsOwnershipError,
)


def test_manual_transaction_blocks_while_stateful_run_owns_contents():
    ownership = ContentsOwnership()
    ownership.claim_run("run-1")
    ownership.bind_fluid_state("run-1", 17)

    with pytest.raises(ContentsOwnershipError, match="run 'run-1'"):
        with ownership.manual_transaction():
            pass

    ownership.bind_campaign("run-1", 23)
    assert ownership.snapshot().kind == "campaign"
    assert ownership.snapshot().campaign_id == 23
    ownership.release("other-run")
    assert ownership.snapshot() is not None
    ownership.release("run-1")
    assert ownership.snapshot() is None


def test_manual_transaction_serializes_and_run_cannot_slip_between_check_and_commit():
    ownership = ContentsOwnership()
    entered = threading.Event()
    continue_edit = threading.Event()
    edit_errors: list[Exception] = []
    run_claimed = threading.Event()

    def edit() -> None:
        try:
            with ownership.manual_transaction():
                entered.set()
                assert continue_edit.wait(timeout=2)
        except Exception as exc:  # pragma: no cover - assertion below reports it
            edit_errors.append(exc)

    def run() -> None:
        assert entered.wait(timeout=2)
        ownership.claim_run("run-2")
        run_claimed.set()

    edit_thread = threading.Thread(target=edit)
    run_thread = threading.Thread(target=run)
    edit_thread.start()
    run_thread.start()
    assert not run_claimed.wait(timeout=0.1)
    continue_edit.set()
    edit_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert edit_errors == []
    assert run_claimed.is_set()
    ownership.release("run-2")
    assert ownership.snapshot() is None


def test_legacy_stateless_workflow_does_not_need_contents_claim():
    ownership = ContentsOwnership()
    with ownership.manual_transaction():
        # A legacy run with no selected fluid state has no ownership claim.
        ownership_snapshot = ownership.snapshot()
    assert ownership_snapshot is None


def test_bind_requires_matching_run_and_release_is_idempotent():
    ownership = ContentsOwnership()
    ownership.claim_run("run-1")

    with pytest.raises(ContentsOwnershipError, match="does not own"):
        ownership.bind_fluid_state("run-2", 4)
    with pytest.raises(ContentsOwnershipError, match="does not own"):
        ownership.bind_campaign("run-2", 9)

    ownership.release("run-2")
    ownership.release("run-1")
    ownership.release("run-1")
    assert ownership.snapshot() is None
