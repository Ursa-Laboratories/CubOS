# Fluid State Tracking

CubOS can save the fluid contents of wells and vials in its SQLite database,
then resume that state in a later protocol run. A fluid state is associated
with the deck YAML that created it, so CubOS can reject a resume attempt made
with a different deck configuration.

Fluid tracking is optional. Protocols that do not create or resume a fluid
state continue to run without tracked contents.

## Prepare the deck and initial fluids

Give each volume-bearing labware item a stable key in the deck YAML. For
example, a reagent grid might be named `reagents` and a well plate
`assay_plate`. Protocol endpoints then use addresses such as
`reagents.buffer` or `assay_plate.A1`.

Aliases are convenient protocol names, but CubOS persists canonical
positions. If `buffer` is an alias for `A1`, a protocol may use
`reagents.buffer` while the saved state records `reagents.A1`.

Create an initial-fluids YAML file containing the starting volume and
composition of each non-empty location:

```yaml
fluids:
  reagents.buffer:
    volume_ul: 1000.0
    composition:
      buffer: 1000.0
  reagents.dye:
    volume_ul: 200.0
    composition:
      dye: 200.0
```

For every location, `volume_ul` must equal the sum of the component volumes.
Locations omitted from the seed start empty.

## Create a state

Use your own calibrated gantry and deck YAML files and your own reviewed
protocol. The first run creates and seeds a deck-linked state and prints its
numeric ID:

```bash
python setup/run_protocol.py \
  /path/to/gantry.yaml \
  /path/to/deck.yaml \
  /path/to/first-protocol.yaml \
  --database /path/to/cubos.db \
  --initial-fluids /path/to/initial-fluids.yaml
```

By default, this command connects to the configured gantry and instruments.
Add `--mock` to run it offline. Validate the exact gantry, deck, and protocol
files before running them:

```bash
python setup/validate_setup.py \
  /path/to/gantry.yaml \
  /path/to/deck.yaml \
  /path/to/first-protocol.yaml \
  /path/to/initial-fluids.yaml   # optional
```

When the optional initial-fluids YAML is supplied, validation also simulates
every `transfer`/`serial_transfer`/`mix` step against those starting volumes:
pipette-model volume bounds, vial `dead_volume_ul` floors, and destination
`working_volume_ul` overflow are all checked offline, so a protocol that
would fail its liquid-safety preflight mid-run fails here instead. Containers
not named in the file are treated as starting empty.

## Resume a state

Use the same database, the same deck configuration, and the ID printed by the
first run:

```bash
python setup/run_protocol.py \
  /path/to/gantry.yaml \
  /path/to/deck.yaml \
  /path/to/next-protocol.yaml \
  --database /path/to/cubos.db \
  --fluid-state-id STATE_ID
```

CubOS applies successful transfers and mixes to the persisted state. A mix is
journaled but does not change the tracked total volume or composition.

## Interrupted operations

During a tracked transfer, CubOS estimates the effect of the last dispatched
liquid action if execution is interrupted (for example by a feed hold):

- Before aspiration is dispatched, neither container changes.
- Once aspiration is dispatched, the source decreases by the requested volume.
- Once dispense is dispatched, the destination also increases by that volume.
- Later strokes and protocol steps are not counted or executed after the error.

For example, a 10 µL aspiration interrupted before dispensing leaves a source
that started at 100 µL estimated at 90 µL. Its destination is unchanged. The
error still stops execution. These are assumed amounts, not measured amounts.
The operation history exposes the assumed action. A partial transfer is never
replayed automatically; start a new run after inspecting the pipette and
correcting any discrepancy. A completed or assumed dispense is skipped when
that exact campaign operation is explicitly rerun.

In **State**, use **Correct volume** beside a container to enter its actual
volume. No operator name or reason is required. Corrections preserve mixture
proportions; adding volume to an empty container records an unknown composition.
The API rejects stale edits, invalid volumes, and corrections during a run or
while another operation is pending.

**Clear all notes** removes saved free-text notes for the selected state across
liquid, tip, and cap operations. It preserves operation outcomes and quantities.
Reconciliation also works without notes. Existing API clients may still supply
optional operator/reason text.

These estimates cover caught interruptions in tracked transfers and commands
that compose them. Standalone aspirate/dispense and multi-dispense still have
their existing tracking restrictions. Process loss, bookkeeping-write failures,
and unresolved tip/cap operations still require manual reconciliation, without
mandatory operator notes.

HTTP clients can use `PATCH /api/v1/fluid-states/{id}/volume` with
`labware_key`, `location_id`, `volume_ul`, and the container's `expected_version`,
and `DELETE /api/v1/fluid-states/{id}/notes`. The Python client exposes
`correct_fluid_volume` and `clear_operation_notes`.

The repository's fluid-state YAML files under
`tests/fixtures/configs/fluid_state_resume/` contain fake coordinates and an
offline `/dev/null` gantry. They exist only for automated tests and are not
supported hardware configurations or operator examples.
