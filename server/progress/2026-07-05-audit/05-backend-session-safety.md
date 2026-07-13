# Backend session safety — connect/run guards on the shared GantrySession

**Context:** Zoo's `zoo/routers/gantry.py` holds a module-level CubOS `GantrySession` (`_session`). CubOS source is at `/Users/alexchan/Documents/Ursa/CubOS` (installed editable — read it to verify semantics, do not modify it). Tests: `.venv/bin/python -m pytest tests/ -q` with the existing recorder-style `FakeSession`. Keep routers thin.

## 1. MAJOR — `POST /connect` while already connected leaks serial + strands disabled soft limits (`gantry.py:534-546`)

CubOS `GantrySession.connect` (session.py:133-170) replaces `self._gantry` **without disconnecting the previous one** and unconditionally resets `_calibration_restore_soft_limits = False`. Re-POSTing `/connect` mid-session: (a) orphans the previous serial connection; (b) if mid-calibration with soft limits disabled, clears the restore flag without re-enabling them — controller left permanently unguarded.

**Fix:** in Zoo's `connect()` handler, when `session.connected` is true, return `HTTPException(409, "Gantry already connected; disconnect first")`. Test: FakeSession with `connected=True` → POST /connect → 409, `connect` not called.

## 2. MAJOR — no run-in-progress guard; motion requests queue on the session lock and fire later (`protocol.py:219-251`, `gantry.py:319-368`)

`session.run_protocol` holds the session lock for the whole run (hours). Zoo motion endpoints are sync `def`s that block on that lock: a `/home` or second `/run` during a run blocks a threadpool thread, then **executes after the run finishes** — surprise motion. Enough queued requests exhaust the AnyIO threadpool (~40), starving even `/api/protocol/cancel` and `/position`.

**Fix (Zoo-level, keep it thin):**
- Add a module-level run gate in `zoo/routers/gantry.py`: `_run_state = {"active": False, "campaign_id": None, "protocol_file": None}` plus a `threading.Lock`. Expose helpers `begin_run(...)` / `end_run()` / `run_active()`.
- `POST /api/protocol/run`: acquire the gate (409 `"A protocol run is already in progress"` if active); set it before calling `run_protocol_on_session`, clear in `finally`.
- Motion endpoints that would queue behind a run (`home`, `jog`, `jog-blocking`, `move-to`, `move-to-blocking`, and the four calibration endpoints) return 409 `"Gantry is busy running a protocol"` while `run_active()`. **Do NOT gate** `/feed-hold`, `/jog-cancel`, `/api/protocol/cancel`, `/position`, `/status`, `/unlock`, `/reset-unlock`, `/disconnect` — those are the operator's stop/recovery/observability paths.
- Add `GET /api/protocol/run-status` returning `{"active": bool, "protocol_file": str|null}`.
- Keep this task **backend-only**: the frontend integration of `run-status` is covered by prompt file `10-protocol-run-flow.md`.

Tests: run active → `/home` 409, `/feed-hold` still 200, second `/run` 409, `run-status` reflects state, gate cleared after run raises.

## 3. MINOR — `_get_or_create_session` race (`gantry.py:163-167`)

Check-then-set on the module global without a lock; two concurrent `/connect` calls can each create a session and leak one open serial port. **Fix:** module-level `threading.Lock` around creation. Note: `tests/test_architecture_boundaries.py` greps router source for `threading.Lock` — read that test first and update its allowlist/assertion deliberately (the guard is against business-logic locking; session-lifecycle locking is legitimate — adjust the test with a comment).

## 4. MINOR — lifespan reaches into private global (`zoo/app.py:27`)

`app.py` writes `gantry._session = None` directly. **Fix:** add `reset_session()` in `zoo/routers/gantry.py`; call it from lifespan.

**Done when:** all four items implemented, new tests pass, full backend suite passes, frontend tests pass, and `tests/test_architecture_boundaries.py` still passes (with any deliberate, commented adjustment).
