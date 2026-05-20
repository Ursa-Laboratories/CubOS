# CubOS

CubOS is the Python control layer for a CNC-based lab platform. It combines:

- Gantry motion control for GRBL-based hardware
- Instrument drivers for measurement and liquid handling
- YAML-defined protocols for experiment execution
- Offline validation before real hardware moves
- SQLite-backed experiment persistence and analysis utilities

This site is set up as a practical operator and developer wiki:

- The narrative guides are written manually where operator knowledge matters.
- The API reference is generated from the Python package tree at build time.

## Quick Start

Install the project in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[docs,dev]
```

Run a safe offline validation first:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

## What To Read First

- [Getting Started](getting-started.md) for installation and first commands
- [Configuration](configuration.md) for the three YAML surfaces
- [Calibrate Deck Origin](calibration.md) for the operator calibration flow
- [Protocol](protocol.md) for how protocol execution is assembled and validated
- [Data](data.md) for persistence and analysis helpers
- [Gantry Bring-Up](admin/gantry-bring-up.md) for controller direction,
  homing, and WPos admin work
- [API Reference](reference/index.md) for generated module docs
