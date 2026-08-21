# Task: line-break tip verification for pick_up_tip / drop_tip

Implement Phase 1 of progress/2026-08-21-tip-detection-scope/SCOPE.md. TDD mode: every new/changed core line must be covered by tests (CI diff-cover gate >= 90%). Minimal comments (docstrings where the file already uses them; no inline narration). Do not touch anything outside the files listed below.

## 1. Shared line-break parse — packages/core/src/cubos/instruments/controllers/pawduino.py

Add a module-level function:

```python
def parse_line_break_response(response: str) -> bool:
```

Move the body of `PawduinoCapper._parse_line_break_response` (packages/core/src/cubos/instruments/capper/vendors/pawduino.py) here verbatim in behavior, but raise `ValueError` (not CapperSensorFault) for unparseable/missing `value1`. Tolerates quoted and unquoted keys, `OK:` prefix, `{...}` body. Returns True iff `value1 == 1`.

Then rewrite `PawduinoCapper._parse_line_break_response` to delegate: call `parse_line_break_response` and re-raise `ValueError` as `CapperSensorFault(str(exc))`. Keep the existing staticmethod signature so capper tests keep passing. Also add `_CMD_LINE_BREAK = 7` is already in the capper file — leave it there; additionally define `CMD_LINE_BREAK = 7` as a module constant in pawduino.py and have the capper use the shared constant (drop its local `_CMD_LINE_BREAK`).

## 2. Pipette interface — packages/core/src/cubos/instruments/pipette/interface.py

Add a non-abstract method on `PipetteInstrument`:

```python
def read_tip_present(self) -> bool | None:
    """Return whether a tip is physically attached, or None when this
    pipette has no tip-presence sensor."""
    return None
```

## 3. Opentrons vendor — packages/core/src/cubos/instruments/pipette/vendors/opentrons.py

Implement `read_tip_present`:
- offline: return `self._has_tip`.
- online: `response = self._send_command(CMD_LINE_BREAK)` (import the shared constant from controllers.pawduino), then `parse_line_break_response(response)`; wrap `ValueError` in `PipetteCommandError`. Attached tip breaks the beam at the tool head, so beam-broken == tip present.

Do NOT touch sartorius.py (it inherits the None default).

## 4. Command changes — packages/core/src/cubos/protocol_engine/commands/pipette.py

### pick_up_tip

New signature:

```python
def pick_up_tip(context, position, speed=50.0, verify_tip=True,
                verify_retries=1, verify_slot_advance=3) -> None
```

Semantics (document in the docstring, matching the file's existing docstring style):

- When `verify_tip` is true and `pipette.read_tip_present()` returns non-None, every physical pickup is verified by the sensor. A pipette without a sensor (None) skips verification silently. `verify_tip=False` disables it.
- Validate `verify_retries >= 0` and `verify_slot_advance >= 0` (ints, reject bools), else ProtocolExecutionError.
- Per-slot attempt: engage + `pipette.pick_up_tip(speed)`; if verifying, read the sensor; on False, re-engage and re-pick the same slot up to `verify_retries` extra times, re-reading after each.
- Slot verified dry (still False after retries):
  - If the caller named an explicit slot (`"tips.A1"`): tracked -> resolve the journal operation via `context.data_store.resolve_tip_operation(operation_key, "reconciled", detail=..., final_slot_status="consumed")`; untracked -> `rack.mark_tip_used(tip_id)`. Then raise ProtocolExecutionError naming the slot ("no tip detected after N attempts").
  - Rack-level request (`"tips"`): consume the slot the same way, then advance to the next available slot — at most `verify_slot_advance` advances total; exceeding it (or no tips left) raises ProtocolExecutionError. Detail strings must say e.g. `"line-break verify: no tip detected after 2 attempts"`.
- Slot advance under tracking uses one durable operation per attempted slot. Key scheme: the first attempt keeps the plain `context.fluid_operation_key("pick_up_tip")`; each advance wraps the begin/execute in a substep scope suffix `pickup:slot{N}` (N = 1-based advance index) using the same save/restore of `context.active_substep` that `transfer` does (or `_substep_scope` — but note `_substep_scope` emits step notifications; prefer plain save/restore here to avoid noise). Each new attempt calls `context.data_store.begin_pick_up_tip(...)` with `slot_id=None` so the DB picks the next available slot.
- Resume replay: before calling `begin_pick_up_tip` for an attempt, check the durable journal for the attempt's operation key (pattern: `_leg_already_applied` — read `context.data_store.get_tip_snapshot(context.fluid_state_id)["operations"]`):
  - status `applied` -> restore extension (`pipette.set_attached_tip_extension` with the op's `tip_extension_mm`), notify step_skipped with the `_ALREADY_APPLIED` reason, return (the whole command is done).
  - status `reconciled` or `cancelled` -> this attempt was a dry slot on the prior run; skip to the next attempt key without touching hardware (counts against `verify_slot_advance`).
  - otherwise -> call begin normally (pending statuses surface through begin's own error path as today).
- Sensor read exceptions propagate through the existing `except BaseException` handler (mark uncertain + raise). Keep all existing behavior for the non-verify path byte-for-byte: same errors, same skip messages, same completion flow.
- After a verified (or unverified) success: unchanged tail — set extension, `rack.mark_tip_used`, `complete_pick_up_tip`.

### drop_tip

New signature: `def drop_tip(context, position, speed=50.0, verify_tip=True) -> None`.

After `pipette.drop_tip(speed)` succeeds: if verifying and the sensor is available, read it; `True` (beam still broken — tip still attached) means the drop failed physically: tracked -> `_mark_tip_uncertain(context, operation_key, ...)` with a clear detail and raise ProtocolExecutionError; untracked -> raise ProtocolExecutionError. Do not call `complete_drop_tip` and do not `clear_attached_tip_extension` on that path. Sensor read errors propagate through the existing BaseException handler.

### _summaries

Update `pick_up_tip`/`drop_tip` summary formatters in `_summaries.py` ONLY if they break on the new args (they take the args dict; check). Do not otherwise change them.

## 5. Tests

Extend `packages/core/tests/protocol_engine/test_pipette_commands.py` following its existing fixture/mocking style (read it first). Cover at minimum:
- sensor unsupported (returns None): verify skipped, behavior identical to today.
- verify_tip=False: sensor never read.
- verify success first read.
- dry then success on same-slot retry (verify_retries=1): pipette.pick_up_tip called twice, one op, completed.
- explicit slot dry after retries: tracked -> resolve_tip_operation called with final_slot_status='consumed', ProtocolExecutionError raised; untracked -> mark_tip_used + raise.
- rack-level dry slot then success on next slot (tracked): first op resolved consumed, second op begun with slot_id=None and completed; `context.active_substep` restored afterward.
- rack-level advance budget exhausted -> ProtocolExecutionError.
- replay: journal snapshot contains attempt-0 key applied -> hardware untouched, extension restored; attempt-0 reconciled + attempt-1 applied -> hardware untouched, extension restored.
- invalid verify_retries / verify_slot_advance rejected.
- drop_tip verify: clear beam -> normal completion; still-broken -> mark_tip_uncertain + raise, complete_drop_tip not called; unsupported sensor -> normal.

Add tests in `packages/core/tests/instruments/controllers/` (see existing files there) for `parse_line_break_response` (quoted, unquoted, 0/1, garbage -> ValueError, missing value1 -> ValueError), and in `packages/core/tests/instruments/pipette/` for `OpentronsPipette.read_tip_present` offline both states + online via a fake link (see how existing pipette vendor tests fake the link) + ValueError -> PipetteCommandError. Also one test that the capper's `_parse_line_break_response` still raises `CapperSensorFault` on garbage.

## 6. Verification gates (run these, all must pass)

```
PYTHONPATH=$PWD/packages/core/src /Users/alexchan/Documents/Ursa/CubOS/.venv/bin/python -m pytest packages/core/tests/protocol_engine/test_pipette_commands.py packages/core/tests/instruments -q
PYTHONPATH=$PWD/packages/core/src /Users/alexchan/Documents/Ursa/CubOS/.venv/bin/python -m pytest packages/core/tests -q
```

Do not commit. Leave the working tree dirty for review.
