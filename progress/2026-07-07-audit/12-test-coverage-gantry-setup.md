# 12 — Test coverage sweep: gantry driver/session + setup scripts

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits. **Runs LAST (with 13): tests pin FINAL post-fix behavior.** Tasks 01–09 and 11 have landed — some scenarios below may already be covered by their regression tests; audit first (`pytest --cov`), then fill only the real gaps. Do not weaken or delete existing assertions to make tests pass; if a test reveals a genuine bug, fix the bug.

Baseline coverage (pre-audit): `setup/hello_world.py` 0%, `setup/home_gantry_config.py` 0%, `src/gantry/offline.py` 0%, `setup/validate_setup.py` 40%, `setup/keyboard_input.py` 41%, `src/gantry/session.py` 54%, `src/gantry/gantry_driver/driver.py` 55%.

## Part 1 — a reusable fake-serial GRBL double

Build a small `FakeGrblSerial` test double in `tests/` (e.g. `tests/gantry/fake_serial.py`) implementing the pyserial surface `Mill` uses (`is_open, port, timeout, open, close, write, read, read_all, readline, readlines, flushInput, flushOutput, flush, in_waiting`) with scriptable behaviors:
- responses split across arbitrary packet boundaries (byte-level chunking),
- real GRBL framing: `ok\r\n`, `error:N\r\n`, `ALARM:N` push lines, `<Idle|...>`/`<Run|...>`/`<Hold:0|...>`/`<Alarm|...>` status reports with WPos/MPos/WCO,
- state transitions for `$H`, `$X`, `!`, `~`, `0x85`, `$J=`, `$$`/`$N` settings echo.
This is NOT the full simulator from the design doc — just enough to exercise `driver.py` without mocking `_read_serial`.

## Part 2 — driver/session scenarios that must be covered (post-fix semantics)

- Split-packet and truncated-mid-number status reads (framing discards/reassembles; never a wrong coordinate).
- `stop()`/`feed_hold_realtime` + `resume()` against Hold state; jog-cancel; jog `error:8` tolerance (`driver.py` drops buffer-full jogs silently — pin that behavior deliberately or make it loud, whichever task 04 chose).
- Real-casing alarms mid-move (`<Alarm|`, `ALARM:1` push) and `is_healthy()` with pushed alarm lines.
- `connect()` boot-alarm early-return path (config read/WPos enforcement deferred, restored by `prepare_for_protocol_run`).
- Reconnect lifecycle (`homed`/`_wco`/`config` reset), session double-connect, `home()` alarm-retry.
- `feed_hold_interrupt` while another thread is mid-`move_to` (no shared-reader desync — write-only path).
- `session.move_to` background worker: `_move_error` publication and reset across two sequential moves (one rejected out-of-bounds, one good).
- Calibration finalize-failure → soft-limit restore behavior (task 04's chosen semantics).

## Part 3 — setup-script coverage

- `setup/hello_world.py` (0%): factor the loop for testability if needed; cover happy jog path, soft-limit-rejected jog guidance, boot-alarm path, KeyboardInterrupt cleanup (uses `gantry.stop()`/`jog_cancel`).
- `setup/home_gantry_config.py` (0%): what it does today, argument errors, happy path with fake gantry.
- `setup/validate_setup.py` (40%): CLI arg handling, PASS and FAIL outputs, exit codes.
- `setup/keyboard_input.py` (41%): arrow/ESC/multi-byte sequences, flush_stdin, the post-task-05 ESC semantics.
- `setup/run_protocol.py` (post task 03): failure-path export, exit codes.
- `src/gantry/offline.py`: cover it if task 04 kept it; if task 04 deleted it, skip.

## Targets & gate

Every module named above ≥80% (driver.py and session.py ≥75% given hardware-only branches — use `# pragma: no cover` ONLY for lines that literally require a physical port). `venv/bin/python -m pytest -q` fully green; report before/after coverage numbers for each named module (`venv/bin/python -m pytest -q --cov=src --cov=setup --cov-report=term`).
