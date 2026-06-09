# Gantry Calibration

Use `setup/calibrate_gantry.py` as the only user-facing calibration entrypoint.
It reads a gantry YAML, counts mounted instruments, chooses the single- or
multi-instrument flow, and writes calibrated values back to YAML.

## Run Guided Calibration

With only an input gantry path, calibration prompts before overwriting that file:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
```

To write a calibrated copy instead, provide an explicit output path. Explicit
outputs do not get an extra overwrite prompt from the wrapper:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py \
  configs/gantry/cub_xl_sterling_3_instrument.yaml \
  --output-gantry configs/gantry/cub_xl_sterling_3_instrument_calibrated.yaml
```

The wrapper preflights the input/output paths, lists detected instruments, and
asks for confirmation before connecting to hardware.

During jog steps:

- arrow keys jog X/Y
- `X` jogs `+Z` up
- `Z` jogs `-Z` down
- number keys change jog step size
- Enter confirms the current calibration step
- `Q` aborts

If a jog trips a hard limit, CubOS soft-resets and unlocks GRBL, then pulls off
opposite the failed jog direction. The pull-off retries up to five times before
aborting and requiring a controller/E-stop reset.

## WPos, MPos, And Homing Pull-Off

Calibration math uses deck-origin WPos, not raw GRBL MPos. CubOS sets `$10=0`
before calibration homing so status reports contain WPos. If a controller is
left in MPos reporting, the homed pose can look offset by WCO and the `$27`
pull-off distance, which makes soft limits look smaller than the physical
machine span.

`working_volume` is the usable deck/WPos range after the machine has homed and
pulled off the switches. GRBL `$130/$131/$132` and YAML
`grbl_settings.max_travel_x/y/z` are controller soft-limit spans and include
the homing pull-off reserve outside the user-visible deck range.

For example, with `$27=10` and a calibrated homed WPos of
`X=386 Y=250.5 Z=91`, the YAML should save:

```yaml
working_volume:
  x_max: 386.0
  y_max: 250.5
  z_min: 0.0
  z_max: 91.0
grbl_settings:
  status_report: 0
  homing_pull_off: 10.0
  max_travel_x: 396.0
  max_travel_y: 260.5
  max_travel_z: 101.0
```

Changing `$27` changes the controller soft-limit spans. Re-run calibration or
recompute `max_travel_*` after changing a machine's homing pull-off.

## Single-Instrument Flow

For a gantry YAML with one mounted instrument, the flow asks you to place a
calibration block at the front-left origin point and jog the instrument
tip/probe to touch the block top. It assigns X/Y at that physical pose, reads
the first homed Z and block-touch Z, then sets the block touch to
the prompted calibration block height. The calibrated YAML writes that value to
`cnc.calibration_block_height_mm`.

The calibrated YAML keeps `cnc.factory_z_travel_mm` unchanged as the
out-of-box safety travel. It writes `working_volume.z_max` from the final homed
readback, uses the factory travel only to decide whether deck bottom is safely
reachable, and programs `max_travel_z` as `z_max - z_min` plus the machine's
`$27` homing pull-off reserve.

## Multi-Instrument Flow

For a gantry YAML with multiple mounted instruments, the flow asks you to pick
the left-most/reference instrument and the lowest instrument by number. It sets
the shared deck frame, asks for the calibration block height, then records each
instrument against the same physical block point to compute `offset_x`,
`offset_y`, and `depth`. The calibrated YAML writes the prompted block height to
`cnc.calibration_block_height_mm` and still preserves
`cnc.factory_z_travel_mm`; calibrated Z bounds come from the block touch and
final homed readback. Controller `max_travel_*` values add the same `$27`
pull-off reserve used by the single-instrument flow.

## After Calibration

Validate the calibrated gantry with a deck and protocol before running real
protocols:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/<calibrated>.yaml \
  configs/deck/<deck>.yaml \
  configs/protocol/<protocol>.yaml
```

Calibration can move hardware, change work coordinates, and program soft-limit
travel settings. Keep E-stop reachable and validate slowly on hardware.
