# Calibration

Use `setup/calibrate_gantry.py` for gantry calibration. It reads one gantry
YAML file, detects the mounted instruments, selects the single- or
multi-instrument flow, and writes calibrated values back to YAML.

Calibration moves hardware and can update work coordinates and GRBL soft-limit
travel settings. Keep the E-stop reachable and clear the deck before starting.

## Before You Start

1. Turn on the gantry and controller.
2. Connect the gantry to the computer over USB/serial.
3. Make sure mounted instruments, cables, fixtures, and samples have clear
   travel paths.
4. Confirm the gantry YAML has the correct `serial_port`,
   `cnc.factory_z_travel_mm`, and mounted `instruments`.
5. Put the calibration block and any board placement markers within reach.

!!! note "Image placeholder: calibration block"
    Add a photo of the calibration block here.

!!! note "Image placeholder: placement markers on the board"
    Add a photo showing the board placement markers here.

## Run Calibration

To calibrate in place, run:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
```

The script asks before overwriting the input file. To write a calibrated copy:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py \
  configs/gantry/cub_xl_sterling_3_instrument.yaml \
  --output-gantry configs/gantry/cub_xl_sterling_3_instrument_calibrated.yaml
```

The preflight shows the input file, output file, detected instruments, and the
chosen flow before it connects to hardware.

## Jog Controls

During calibration:

- arrow keys jog X/Y
- `X` jogs `+Z` up
- `Z` jogs `-Z` down
- number keys change step size
- Enter confirms the current step
- `Q` aborts

If a jog trips a hard limit, CubOS soft-resets, unlocks GRBL, and attempts a
small pull-off opposite the failed jog direction. Stop and reset the controller
if recovery fails.

## Single-Instrument Calibration

Use this flow when the gantry YAML has one mounted instrument.

1. Start `setup/calibrate_gantry.py`.
2. Confirm the single-instrument flow in the preflight.
3. Place the calibration block at the front-left origin reference point.
4. Jog the instrument tip or probe until it touches the top of the block.
5. Confirm the touch point when prompted.
6. Let the script home and measure the usable work volume.
7. Review the summary and calibrated YAML path.

!!! note "Image placeholder: single instrument touching calibration block"
    Add a close-up of the instrument tip touching the calibration block here.

The script saves the deck-frame working volume, preserves
`cnc.factory_z_travel_mm` as the factory safety bound, and writes
`cnc.calibration_block_height_mm` from the prompted block height. If
`grbl_settings.homing_pull_off` is configured, GRBL max travel values include
that pull-off reserve.

## Multi-Instrument Calibration

Use this flow when the gantry YAML has more than one mounted instrument.

1. Start `setup/calibrate_gantry.py`.
2. Confirm the multi-instrument flow in the preflight.
3. Select the leftmost/reference instrument when prompted.
4. Select the lowest instrument when prompted.
5. Place the first calibration block at the shared reference point.
6. Jog the leftmost/reference instrument to touch the first block.
7. Jog each remaining instrument to the shared reference point as prompted.
8. For pipette setups, jog the pipette to the center reference point on the
   block when prompted.
9. Let the script compute `offset_x`, `offset_y`, and `depth` for each
   instrument.
10. Review the summary and calibrated YAML path.

!!! note "Image placeholder: multi instrument leftmost instrument touching first calibration block"
    Add the reference-instrument touch photo here.

!!! note "Image placeholder: multi instrument pipette touching center reference point on block"
    Add the pipette center-reference touch photo here.

## WPos And Soft Limits

Calibration uses GRBL WPos in the CubOS deck frame. It sets `$10=0` before
homing so status reports contain WPos.

`working_volume` is usable deck/WPos space after homing pull-off.
`grbl_settings.max_travel_x/y/z` mirrors GRBL `$130/$131/$132` and includes
the `$27` pull-off reserve. Do not add the pull-off reserve to
`working_volume`.

Example with `$27=10` and homed WPos `Z=91`:

```yaml
working_volume:
  z_max: 91.0
grbl_settings:
  homing_pull_off: 10.0
  max_travel_z: 101.0
```

## Interactive Jog Test

After calibration, run the interactive deck-frame jog check:

```bash
PYTHONPATH=src python setup/hello_world.py \
  --gantry configs/gantry/cub_xl_asmi.yaml
```

Expected directions:

- `+X` moves right
- `+Y` moves back, away from the operator
- `+Z` moves up
- `-Z` moves down

Once calibration and the jog test are complete, continue to
[Configuration](configuration.md).
