# Getting Started

## Two Ways To Use CubOS

There are two entrypoints:

1. **YAML-based** - define your experiment across three YAML config files
   (gantry, deck, protocol) and run it from the command line.
2. **Python API** - import `setup_protocol()` and build experiments
   programmatically. See the [API Reference](reference/index.md) for details.

This guide focuses on the YAML-based workflow.

## Prerequisites

- Python 3.9+
- `pip`
- a GRBL-compatible CNC gantry over serial for hardware runs
- instrument-specific drivers when using real instruments

Hardware motion depends on controller settings and WPos calibration. If the
machine has not been normalized yet, start with
[Gantry Bring-Up](admin/gantry-bring-up.md), then run
[Calibrate Deck Origin](calibration.md).

## Installation

```bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## First Validation

Validate your YAML setup offline before connecting hardware:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

This loads all three configs, checks the protocol's concrete motion targets
against the gantry working volume, validates protocol motion semantics, and
prints PASS/FAIL.

## Calibration

For a real setup, calibrate the gantry YAML before running protocols. With only
an input path, the script prompts before overwriting that file:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
```

To write a calibrated copy, provide `--output-gantry`.

The calibration script counts mounted instruments in the gantry YAML and chooses
the single- or multi-instrument flow. Single-instrument calibration uses a
calibration block at the front-left origin point, assigns X/Y at that physical
pose, and preserves `cnc.factory_z_travel_mm` only as the out-of-box Z travel
safety bound. Calibrated Z bounds come from the measured home-to-block travel
and final homed readback.
Multi-instrument calibration uses a shared block point to compute per-instrument
`offset_x`, `offset_y`, and `depth`.

## Interactive Jog Test

After calibration, run a small jog test and verify physical direction:

```bash
PYTHONPATH=src python setup/hello_world.py \
  --gantry configs/gantry/cub_xl_asmi.yaml
```

Expected directions:

- `+X` moves right
- `+Y` moves back, away from the operator
- `+Z` moves up
- `-Z` moves down

## Running A Protocol

Once validation, calibration, and jog checks pass, connect the gantry and run a
minimal protocol:

```bash
PYTHONPATH=src python setup/run_protocol.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

Move to ASMI indentation or scans only after the minimal move behaves as
expected on hardware.
