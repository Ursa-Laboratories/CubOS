# 02 — Protocol run lifecycle safety (failure leaves hardware safe and errors honest)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per fix. Task 01 has already landed — build on its state.

## Goal

A protocol that fails mid-run must leave the gantry at a safe height, report the root-cause exception, close resources, and never touch real hardware in mock mode.

## Fixes

1. **HIGH — no Z-retract on mid-run failure.** `src/protocol_engine/setup.py:233-241` `finally` only disconnects; `commands/scan.py:202-207` retracts only after the loop completes — a method failure at well B3 leaves the tip at action_z, possibly indented in a sample, and then the serial link is closed. Fix: in `run_on_hardware`'s `finally`, before disconnecting, best-effort raise the mounted instrument to `safe_z` (own try/except so a dead link can't mask the root cause; log loudly if the retract itself fails). Also log the last commanded pose on failure.
2. **MEDIUM — `gantry.disconnect()` raising inside `finally` masks the root-cause exception and skips `data_store.close()`.** `setup.py:234-241`: instruments are wrapped in try/except, gantry is not (`Gantry.disconnect` deliberately re-raises `MillConnectionError`, `gantry.py:110-114`), and `data_store.close()` sits after it. Fix: wrap `gantry.disconnect()` in try/except-log; run `data_store.close()` in a nested `finally`.
3. **MEDIUM — `run_on_hardware(mock_mode=True, gantry=None)` constructs a real hardware `Gantry` and connects.** `setup.py:190-193` builds `Gantry(config=raw_config)` unconditionally; `mock_mode` only affects instruments — a CI/mock run auto-scans serial ports and drives whatever answers. Fix: when `mock_mode=True` and no gantry is supplied, use `Gantry(offline=True)` (mirroring `setup_protocol`'s own pattern at `setup.py:96`).
4. **LOW — `measure` moves hardware before validating argument ordering.** `commands/measure.py:73-80` (`engage_at_labware` descends to action_z) precedes the `indentation_limit_height > measurement_height` check at `:91-100`; `scan.py:126-141` checks before motion. Fix: hoist all argument validation (including the `inject_runtime_args` mis-declaration probe, `_dispatch.py:135-142`) above the descent.
5. **LOW — `breakpoint` blocks forever headless.** `commands/pause.py:46` calls `input()` with no TTY check — a scheduled/headless run hangs holding the serial port. Fix: if `not sys.stdin.isatty()`, log a warning and continue (or raise a clear error — pick one, document it in the command docstring).
6. **LOW — `home` clobbers the serial timeout.** `commands/home.py:30` restores a hard-coded `set_serial_timeout(0.05)` rather than the previous value. Fix: save and restore the actual prior timeout.

## Tests (minimum)

- Mid-scan instrument exception → assert the gantry received a raise-to-safe_z command before disconnect, and the ORIGINAL exception propagates (use offline gantry + failing mock instrument).
- Failing `gantry.disconnect()` in the finally path → root-cause exception preserved, data store closed.
- `run_on_hardware(mock_mode=True, gantry=None)` never constructs a hardware-scanning Gantry.
- `measure` with inverted heights raises BEFORE any motion command is issued (assert on the offline gantry's command log).
- `breakpoint` under a non-TTY stdin does not hang.

## Gate

`venv/bin/python -m pytest tests/protocol_engine tests/setup -q`, then full suite green.
