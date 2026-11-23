# Liquid-Handling Parity with the Opentrons API

This page records what CubOS can and cannot do today relative to the Opentrons
Protocol API's pipetting surface. It is an audit of the code at the time of
writing, not a roadmap commitment. Paths are relative to
`packages/core/src/cubos/`.

Status key: **Yes** (equivalent behavior), **Partial** (present with
differences), **No** (absent), **Different** (intentionally modeled another
way).

Opentrons behavior is described from its public API documentation and is not
re-verified against a running OT-2/Flex. CubOS behavior is read from code and
exercised by the tests named below.

## Command matrix

| Opentrons concept | CubOS | Status | Where |
| --- | --- | --- | --- |
| `pick_up_tip(location)` | `pick_up_tip` with `position`; tracked tip racks, persisted used/available state | Yes | `protocol_engine/commands/pipette.py`, `data/tip_state.py`, `deck/labware/tip_rack.py` |
| Auto next-tip selection | `pick_up_tip` accepts a rack and picks the next available tip | Yes | `protocol_engine/commands/pipette.py` |
| `drop_tip` | `drop_tip` into a `tip_disposal` slot | Yes | `deck/labware/tip_disposal.py` |
| `return_tip` | None. A dropped tip is never returned to its rack well | No | |
| `aspirate(volume, location, rate)` | `aspirate` with `position`, `volume_ul`, normalized `speed` 0-100 | Partial | `commands/pipette.py` |
| `dispense(volume, location, rate, push_out)` | `dispense`; no push-out argument | Partial | `commands/pipette.py` |
| `blow_out` | `blowout`; Picus uses a calibrated `blowout_position` | Yes | `commands/pipette.py`, `instruments/pipette/models.py` |
| `air_gap` | None | No | |
| `touch_tip` | None | No | |
| `mix(repetitions, volume, location, rate)` | `mix` with `cycles`; fixed asp/disp pattern with a 1 mm lift, `blowout_height` | Partial | `instruments/pipette/interface.py` (`mix`), `commands/pipette.py` |
| `prepare_to_aspirate` | Picus `prime`; not a protocol command | Different | `vendors/opentrons.py` (`prime`) |
| Pre-wet (aspirate/dispense before transfer) | None | No | |
| In-liquid delay / `delay()` | `pause` (seconds) between steps only; no dwell inside an aspirate or dispense | Partial | `commands/pause.py` |
| `flow_rate.aspirate/dispense` (uL/s) | Only normalized `speed`; the Opentrons-firmware driver ignores `speed` | No | `vendors/opentrons.py` (note on speed semantics) |
| `well.top(z)` / `well.bottom(z)` | `height` is an offset from the well reference (rim). No bottom-relative form | Partial | `commands/pipette.py` |
| `well.center()`, x/y offsets | `x_offset_mm`, `y_offset_mm` on aspirate, dispense, blowout, mix, tip commands, transfer | Yes | `commands/pipette.py` |
| `transfer` | `transfer` with automatic stroke splitting, dead-volume and overflow preflight, liquid-class correction, durable per-stroke journaling | Partial | `commands/_liquid_transfer.py` (`plan_strokes`, `validate_dead_volume`, `validate_destination_overflow`) |
| `transfer(new_tip=...)` | Tip handling is explicit steps; no policy argument | No | |
| `transfer(mix_before/mix_after)` | Compose `mix` steps by hand | No | |
| `transfer(touch_tip, blow_out, air_gap, disposal_volume)` | None of these arguments | No | |
| `distribute` | `multi_dispense` (one aspirate, several dispenses). Planned-motion capable, not durably journaled | Partial | `commands/pipette.py` (`multi_dispense`), `routing.py` |
| `consolidate` | None | No | |
| Serial dilution (protocol-level recipe) | `serial_transfer` moves a volume list across a plate axis from a source; it does not carry liquid well to well | Different | `commands/pipette.py` (`serial_transfer`) |
| Liquid classes (named transfer properties) | `liquid_class` on `transfer`: multiplier and offset volume correction only | Partial | `instruments/pipette/liquid_class.py` |
| Multichannel (`NozzleLayout`, partial tip) | Not implemented; geometry is under review separately | No | |
| Volume bounds and increments | Per-model min/max and `volume_increment_ul`; Picus drivers quantize, Opentrons driver is continuous | Yes | `instruments/pipette/models.py` |
| Liquid tracking (`load_liquid`, `Well.load_empty`) | Persistent fluid state with composition, dead volume, overflow checks | Yes (stronger) | `data/fluid_state.py`, `docs/fluid-state.md` |

## Labware geometry

Opentrons labware definitions carry per-well `depth`, `totalLiquidVolume`,
`shape` and diameter or x/y dimensions. CubOS:

* `WellPlate` has optional `well_depth`, `capacity_ul`, `working_volume_ul` and
  a free-form `well_attributes` map. `capacity_ul` and `working_volume_ul` are
  uniform for the plate, not per well (`deck/labware/well_plate.py`). The
  plate-level `well_depth` is metadata only; no command uses it for positioning.
* `Vial` has required `height`, `diameter`, `capacity_ul`, `working_volume_ul`
  and `dead_volume_ul` (`deck/labware/vial.py`).
* There is no reservoir type. A multi-well reservoir is modeled as a plate or as
  vials.
* A plate with no `capacity_ul`/`working_volume_ul` is silently untracked for
  volume purposes, whereas a vial always is.

## Run control and recovery

| Capability | CubOS | Where |
| --- | --- | --- |
| Operator cancel | API cancel marks the run `cancel_requested` and issues a GRBL feed-hold interrupt (real hardware only) | `services/api/src/cubos_api/services/run_manager.py` (`cancel`) |
| Pause/resume mid-protocol | Only the `pause` (timed) and `breakpoint` commands; no operator pause of a running protocol | `commands/pause.py` |
| Crash recovery | Two-phase journal (begin, act, complete). Uncertain outcomes require operator reconciliation; pending fluid/tip/cap operations block new ones | `data/fluid_state.py`, `data/tip_state.py`, `docs/fluid-state.md` |
| Resume after interruption | Re-running a campaign skips applied strokes. A transfer preflights only the unapplied remainder | `commands/pipette.py` (`transfer`) |
| Interrupted API runs | Incomplete runs are marked `failed` on server restart | `run_manager.py` (`_recover_interrupted_runs`) |

Opentrons offers pause/resume/stop at the run level and error recovery for
selected command failures. CubOS has no equivalent of in-run recovery; it
provides durable state so a failed run can be reconciled and re-run.

## Routing and planning

Collision-aware routing supports `move`, `pick_up_tip`, `transfer`, `mix`,
`drop_tip`, `capture`, `pause`, `aspirate`, `dispense`, `blowout` and
`multi_dispense` (`protocol_engine/routing.py`, `SUPPORTED_PLANNED_COMMANDS`).
Any other command in a planning-enabled run is rejected before motion with
"routing v1 does not support ...". That includes `serial_transfer`,
`rinse_well`, `flush_pipette`, `purge_pipette` and `clear_well`. New pipette
commands must either be added to routing with planned support or be rejected
cleanly there.

Under planning, state-derived heights are not used; planned moves use the
configured heights.

## Known gaps found by the conformance harness

See `packages/core/tests/protocol_engine/liquid_conformance/`.

* **Fixed:** resuming a partly applied multi-stroke `transfer` preflighted the
  full volume against the already-reduced source and failed spuriously.
* **Fixed:** `pick_up_tip` on an untracked rack did not refuse when a tip was
  already attached.
* **Open:** volume accounting tracks the requested volume while Picus drivers
  quantize to `volume_increment_ul`; the difference is not recorded (strict
  `xfail` in the harness).
* **Open:** a stroke whose journal entry was resolved `not_applied`/cancelled
  cannot be re-attempted under the same key, so a resumed run cannot redo it.

## Simulation timeline

`validation/timeline.py` predicts per-step volumes, tips and duration without
hardware. Its durations use assumed defaults, not measurements, and it models
the commands listed in its module docstring; unknown commands report zero time.
