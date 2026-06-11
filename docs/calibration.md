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

![Calibration block aligned to a board placement marker](images/calibration-block-marker.webp){ width="420" }

![Board placement markers used during calibration](images/calibration-marks.webp){ width="520" }

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

![Single instrument touching the calibration block](images/single-instrument-calibration-block.webp){ width="420" }

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
5. Place the first calibration block on the leftmost board mark for the red
   reference instrument.

   ![Red reference instrument touching the block at the leftmost mark](images/leftmost-red-instrument-block.webp){ width="420" }

6. Jog the red reference instrument to touch the first block.
7. Move the calibration block to the center board mark.

   ![Calibration block moved to the center board mark](images/center-calibration-block.webp){ width="520" }

8. Jog each remaining instrument to the shared center reference point as
   prompted.
9. For pipette setups, jog the pipette to the center reference point on the
   block when prompted.
10. Let the script compute `offset_x`, `offset_y`, and `depth` for each
   instrument.
11. Review the summary and calibrated YAML path.

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
