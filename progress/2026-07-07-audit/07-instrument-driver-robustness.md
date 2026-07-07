# 07 — Instrument driver robustness (no fake data, no hangs, no swallowed typos)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only (vendor SDKs stay lazy/mocked), no commits, regression test per fix.

Scope: `src/instruments/**` and `tests/instruments/**`.

## Fixes

1. **HIGH — misspelled mount-critical YAML fields are silently ignored.** `src/instruments/yaml_schema.py:46` is `extra="allow"` and every vendor driver sinks `**kwargs` (`opentrons.py:51`, `thorlabs.py:48`, `excelitas.py:56`, `kla.py:38`, `admiral.py:80`, ...). A gantry YAML with `dept: 58.0` (typo for `depth`) loads cleanly, the instrument gets `depth=0.0`, every bounds/collision number is 58mm wrong, and `validate_setup.py` passes. The `_RELOCATED_HEIGHT_FIELDS` guard (`yaml_schema.py:8-21`) covers only two legacy keys. Fix: after resolving the driver class, validate extra keys against the driver `__init__` signature (plus an explicit passthrough allowlist if any driver needs one) and fail loading on unconsumed keys with a did-you-mean message. Keep external-registry drivers working (`cubos.instrument_registries` entry points) — signature introspection covers them too.
2. **MEDIUM — KLA/Filmetrics timeouts don't work and disconnect can hang.** `kla.py:140,155`: `stdout.read(1)`/`readline()` block indefinitely — the `time.monotonic() < deadline` loop only advances between reads, so a hung FilmetricsTool.exe blocks `connect()`/`measure()` forever; `disconnect()` (`:94`) calls `wait()` with no timeout. Fix: reader thread + `queue.get(timeout=...)` (or selectors); `wait(timeout)` then `kill()` in disconnect.
3. **MEDIUM — thickness parsing hard-codes `"Polyimide"`.** `kla.py:178`: any other recipe/material yields `thickness_nm=None` silently; `FilmetricsParseError` (`exceptions.py:16`) is defined and exported but never raised anywhere. Fix: make the material label a constructor parameter (YAML-configurable via fix 1's signature validation) and raise `FilmetricsParseError` when no thickness parses.
4. **MEDIUM — Vernier ASMI records a failed sensor read as a real 0.0 N force.** `vernier.py:158-163` (`value = 0.0; if self._device.read(): ...`): the 0.0 enters `readings`, and after baseline correction can mask real contact or spuriously trip `force_limit`. Fix: raise `ASMICommandError` (or bounded retry) when `read()` returns False. Also wrap the connect-time SDK calls (`vernier.py:88-97`: `GoDirect()`, `get_device`, `enable_sensors`) in `ASMIConnectionError` like admiral/thorlabs do, and make `health_check()` (`:128`) catch raw SDK/USB exceptions (its contract is `bool`).
5. **MEDIUM — Excelitas exposure truncation + zombie handshake state.** `excelitas.py:151`: `int(exposure_time * 10)` sends `STM0` for 0.05s (passes the `> 0` check) and silently turns 1.99 into 1.9s — `round()` and reject exposures below 0.1s. `:172-181`: a failed `_handshake()` leaves the port open and `health_check()` (`:107`) returns True (it only tests `is_open`) — close the port on handshake failure. Also check `SIL`/`STM` responses for device NACKs (`:150-152`).
6. **MEDIUM — Thorlabs UVVis: unchecked DLL return codes and raw AttributeErrors.** `thorlabs.py:127,142`: `tlccs_setIntegrationTime`/`tlccs_startScan` rc ignored — a failed scan start surfaces as a misleading `UVVisCCSTimeoutError("Scan not ready after 5.0s")`. Calling `measure()`/`set_integration_time()` before `connect()` → raw `AttributeError: 'NoneType' object has no attribute 'tlccs_...'` (same hole in `kla.py:149`). Fix: check rc on every DLL call; add connected-state guards raising the instrument's own error type (compare `opentrons.py:255`'s clean "Not connected to Arduino").
7. **MEDIUM — pipette accepts negative/over-capacity volumes.** `opentrons.py:172-196`: `mm_travel = volume_ul * mm_to_ul` goes straight to firmware; nothing checks `config.min_volume`/`max_volume` (nor does `protocol_engine/commands/pipette.py`). A `volume_ul: -50` or `5000` on a p300 commands the plunger out of range. Fix: validate in the driver (raise `PipetteCommandError`), offline mode included.
8. **LOW — misc.** `deck/loader.py`-style clarity isn't in scope here, but do fix: `instruments` registry lookup errors should name the type+vendor pair tried and the available pairs (check current message quality while in the file).

## Tests (minimum, all offline/mocked)

- Unknown instrument YAML key → load fails with the key named; known driver kwargs still pass; external-registry driver unaffected.
- KLA: hung-process mock (blocking read) → `FilmetricsCommandError` within the timeout; non-Polyimide recipe → `FilmetricsParseError` (first raise-site test for it).
- Vernier: `read()` False → `ASMICommandError`, never a 0.0 reading; connect-time SDK exception → `ASMIConnectionError`.
- Excelitas: 0.05s exposure rejected; 1.99 rounds to `STM20`; failed handshake → port closed, `health_check()` False.
- Thorlabs: failing `tlccs_startScan` rc → `UVVisCCSError` (not timeout); `measure()` before `connect()` → typed error.
- Opentrons: negative and > max_volume rejected in offline mode.

## Gate

`venv/bin/python -m pytest tests/instruments -q`, then full suite green, then `venv/bin/python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi/indentation.yaml` still PASSes (shipped configs must survive the new extras validation — if one carries a genuinely unknown key, fix the config and say so).
