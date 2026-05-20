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

## Single-Instrument Flow

For a gantry YAML with one mounted instrument, the flow asks you to place a
calibration block at the front-left origin point and jog the instrument
tip/probe to touch the block top. It assigns X/Y at that physical pose, reads
the block-touch WPos Z as the remaining downward travel to WPos 0, and preserves
the gantry YAML's seeded `cnc.total_z_range` as the calculated Z travel.

The calibrated YAML keeps `cnc.total_z_range` unchanged, writes
`working_volume.z_min: 0.0`, writes `working_volume.z_max` from
`cnc.total_z_range`, and programs `max_travel_z` from that same seeded range.
The block height is used to report the inferred lowest reachable height above
the physical deck, for example `35 mm block - WPos Z 20 mm = 15 mm`.

## Multi-Instrument Flow

For a gantry YAML with multiple mounted instruments, the flow asks you to pick
the left-most/reference instrument and the lowest instrument by number. It sets
the shared deck frame, asks for the calibration block height, then records each
instrument against the same physical block point to compute `offset_x`,
`offset_y`, and `depth`. The calibrated YAML still preserves the seeded
`cnc.total_z_range` and uses it for `working_volume.z_max` and `max_travel_z`.

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
