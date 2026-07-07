# 05 — Calibration motion safety (abort actually stops, recorded reads are settled)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per fix. Task 04 has landed (driver has `feed_hold_realtime`/`resume`, `jog_cancel` semantics unchanged). The working tree has **uncommitted in-flight edits to these exact files** (calibration prompts + tests) — build on top, never revert.

Scope: `setup/calibration/single_instrument_calibration.py`, `setup/calibration/multi_instrument_calibration.py`, `setup/hello_world.py`, `setup/keyboard_input.py`, tests under `tests/setup/`.

## Fixes

1. **HIGH — aborting calibration (Q / Ctrl-C) never stops in-flight motion.** `single_instrument_calibration.py:764-765` raises KeyboardInterrupt on Q; the `finally` blocks (`single:1206-1214`, `multi:865-873`) only restore soft limits and `gantry.disconnect()`. GRBL `$J=` jogs are non-blocking and queue in the planner (`driver.py:412-415`); closing the port does not stop them — the gantry keeps driving after the script prints "Aborted." (`hello_world.py:109-111` already does this right with `gantry.stop()`.) Fix: in the abort/exception paths of `_interactive_jog_to_reference` and both flows' `finally`, send `gantry.jog_cancel()` (0x85 flushes queued jogs) before disconnecting.
2. **HIGH — ENTER can confirm a coordinate read mid-motion, silently corrupting the origin/touch point.** `single:766-772` calls `get_coordinates()` immediately on ENTER; same hazard for the per-jog WPos echo (`single:822-825`), the block touch (`multi:637`), and each per-instrument touch (`multi:758`). The helper already exists — `_wait_until_idle_if_available` (`multi:384-405`) — but is only used after retracts. Fix: wait for Idle before EVERY `get_coordinates()` whose value is displayed for confirmation or recorded into the calibration.
3. **MEDIUM — the multi-instrument flow runs almost entirely with soft limits disabled.** `multi:557-562` disables `$20` before Step 1 and only re-enables at the very end (`multi:791`/finally); the single flow restores immediately after the origin jog (`single:1018-1021`). Fix: restore `$20=1` after Step 1 in the multi flow too.
4. **MEDIUM — buffered keypresses replay as real jogs.** `flush_stdin`'s own contract says to call it after every blocking operation (`keyboard_input.py:172-177`), but the multi flow calls it once (`multi:563`) — keys drummed during the re-home (`multi:594`), the automated center move (`multi:599`), or retracts (`multi:765-770`) are consumed by the next jog session as motion. `hello_world.py` never flushes after its ~30s homing (`:78-86`). Fix: flush at the top of `_interactive_jog_to_reference` (one place fixes every call site) and after hello_world's homing.
5. **MEDIUM — the in-flight diff reworded a dead function; the live multi-flow prompt contradicts the docs.** `_prompt_z_reference_height` (`multi:286-306`) is never called (zero call sites); the multi flow uses single's `_prompt_block_height` (`multi:517-523`), whose new wording ("or a deck feature such as the top of a well plate") contradicts `docs/calibration.md:153-156` ("Every instrument must touch the same physical point... use the calibration block"). Fix: wire the multi-specific prompt into the multi flow (or parametrize `_prompt_block_height`) and delete the dead copy.
6. **MEDIUM — `hello_world.py` breaks on first contact with reality.** (a) The jog loop (`:85-107`) has no error handling: after `$H` the machine sits at back-right-top, so the first `RIGHT`/`UP`/`X` press exceeds travel → GRBL `error:15` → uncaught `CommandExecutionError` traceback (`driver.py:447-448`). Handle it like `single:828-843` ("jog exceeds travel; try the other direction"). (b) `:68-71` exits with "Gantry is not healthy. Check the connection" on the normal power-on alarm (homing-enabled GRBL boots into Alarm; connect deliberately leaves it, `driver.py:247-253`) — detect the alarm case and proceed to the homing prompt ("controller is in startup alarm — homing clears it").
7. **LOW — bare ESC hangs the jog UI.** `keyboard_input.py:67-69` blocks on `sys.stdin.read(2)` after `\x1b` and swallows the next two keys; multi-byte sequences (PgUp) leave a stray `~`. Fix: short `select` timeout after ESC; treat a lone ESC as jog-cancel. Also give feedback on unknown keys in the jog loop (`single:819-820` currently silent) — print the key legend.

## Tests (minimum)

Use a scripted fake gantry + injected key sequences (existing tests in `tests/setup/test_calibrate_*.py` show the pattern — note they carry uncommitted edits):
- Q and KeyboardInterrupt during jog → `jog_cancel` issued before disconnect (both flows).
- ENTER after a jog → an idle-wait precedes the recorded `get_coordinates` (all four capture sites).
- Multi flow: soft limits re-enabled after Step 1; flush called before each jog session.
- Multi flow uses the multi-specific height prompt text.
- hello_world: soft-limit-rejected jog prints guidance and continues; boot-alarm proceeds to homing path.
- Lone ESC doesn't hang and cancels the jog.

## Gate

`venv/bin/python -m pytest tests/setup -q`, then full suite green.
