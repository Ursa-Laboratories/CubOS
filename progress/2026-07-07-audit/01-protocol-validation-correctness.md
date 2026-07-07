# 01 — Protocol validation correctness (two shipped functional breaks + validator blind spots)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, add a regression test per fix.

## Goal

Make offline validation trustworthy: everything that passes `Protocol.validate()` / `setup/validate_setup.py` must run, and everything unsafe or unresolvable must fail validation with an actionable message.

## Fixes (all verified against current code)

1. **CRITICAL — `serial_transfer` cannot compile at all.** `src/protocol_engine/registry.py:89-95` builds command schemas with `create_model` in registry.py's namespace, but `commands/pipette.py:245-246` annotations are strings (`from __future__ import annotations`) using `Optional`/`List`, unresolvable there. Repro: `ProtocolBuilder().add_command("serial_transfer", {...}).build()` → `PydanticUserError: 'SerialTransferSchema' is not fully defined`. Fix `_build_schema_from_signature` to resolve annotations via `typing.get_type_hints(func)` (or pass the handler's module namespace). Add a registration-time smoke test that instantiates/validates the schema of **every** registered command so this class of break can never ship again.
2. **CRITICAL — protocols containing `pause` or `breakpoint` fail semantic validation.** `src/validation/protocol_semantics.py:1058-1066` `_KNOWN_PIPETTE_COMMANDS` omits them; the dispatcher (`:1380-1391`) routes unknown commands into `_validate_pipette_command`, whose fallback (`:1080-1089`) emits "unknown protocol command". Fix: a no-motion command whitelist the semantic validator skips, and derive the known-command universe from `CommandRegistry.instance().command_names` so the registry and validator cannot drift.
3. **HIGH — ASMI indentation depth is unvalidated on `measure`.** `_validate_asmi_indentation` is called only from `_validate_scan_command` (`protocol_semantics.py:750-758`); `_validate_measure_command` (`:776-873`) has no equivalent, and `src/validation/bounds.py:300-320` emits only safe_z/action_z targets. A `measure` with `indentation_limit_height: -50.0` passes validation while the identical `scan` fails. Fix: run the indentation check (including the `indentation_limit_height <= measurement_height` ordering check that scan gets at `:759-772`) from `_validate_measure_command`, and add the deepest plane (`well.z + indentation_limit_height`) as a bounds target for measure in `bounds.py`.
4. **HIGH — unresolvable measure/scan targets pass validation silently.** `protocol_semantics.py:811-814` (also `:660-661`, `:665-669`, `:801-802`): `except KeyError: return violations` appends nothing — a typo'd position/plate/instrument on `measure`/`scan` validates clean and dies mid-hardware-run. `bounds.py:206-208` returns silently on `coord is None`; `bounds.py:550-551` `continue`s on unknown instrument. Fix: emit a violation for every unresolvable position/plate/instrument, mirroring the `move` path (`:905-911`).
5. **MEDIUM — named `positions` accept wrong arity and NaN.** `src/protocol_engine/yaml_schema.py:70` allows any-length `List[float]`; a 2-element position crashes the validator with a raw `IndexError` at `protocol_semantics.py:900-902` (surfaced as "validation engine failure"); NaN passes and dies mid-run. `ProtocolBuilder.add_position` (`builder.py:152-158`) accepts anything. Fix: constrain the schema to exactly 3 finite floats (validator on the model), apply the same check in `compile_protocol` for builder-supplied positions, and make `_validate_move_waypoints` emit a violation instead of indexing blindly.
6. **MEDIUM — builder/compiler error messages lack context.** `compiler.py:44` lets raw pydantic `ValidationError` (and finding 1's `PydanticUserError`) escape `build()` with no step index/command name; the legacy-field rename hints in `loader.py:16-40` apply only to the YAML path. Fix: wrap compile-time schema errors with step index + command name (share the `_format_loader_exception`-style formatting), so `add_command("scan", {"indentation_limit": 5.0})` gets the same hint YAML users get.

## Tests (minimum)

- Compile-through-registry test for `serial_transfer` (YAML load AND builder), plus the all-commands schema smoke test.
- `pause`/`breakpoint` protocols pass `run_setup_validation` end-to-end.
- `measure` with too-deep `indentation_limit_height` fails offline validation (mirror the scan-side test).
- Typo'd `measure`/`scan` position, unknown plate, unknown instrument each produce a violation (not silence).
- 2-element and NaN named positions produce clean validation errors (no IndexError).

## Gate

`venv/bin/python -m pytest tests/validation tests/protocol_engine -q`, then full `venv/bin/python -m pytest -q` green, then `venv/bin/python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi/indentation.yaml` still PASSes.
