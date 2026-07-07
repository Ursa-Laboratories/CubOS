# CubOS

CubOS is a Python control layer for CNC-based lab automation. It connects
GRBL gantry motion, mounted instruments, deck labware, YAML protocols, offline
motion validation, and SQLite-backed experiment data into one operator and
developer workflow.

![CubOS gantry demo](docs/images/cubos-demo.gif)

Use CubOS to:

- define gantry, deck, and protocol state in versioned YAML files
- validate concrete motion targets before connecting to hardware
- run reproducible measurement and liquid-handling protocols
- persist experiment state and measurement data for later analysis
- extend the platform with new instruments, labware, and command handlers

CubOS can move real lab hardware. Always validate configs offline, calibrate
the gantry work frame, keep an E-stop reachable, and start with minimal motion
before running scans, indentation, dispensing, or other instrument actions.

## Installation

See [Getting Started](docs/getting-started.md) for full, OS-specific
installation instructions (Windows/macOS/Linux prerequisites, venv setup,
instrument extras, serial port discovery). Docs are the source of truth for
installation steps — this README doesn't duplicate them.

## Quick Start

Validate an example setup without moving hardware:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

For real hardware, calibrate the gantry YAML before running protocols:

```bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
```

After calibration, confirm physical jog direction with the interactive test:

```bash
PYTHONPATH=src python setup/hello_world.py \
  --gantry configs/gantry/cub_xl_asmi.yaml
```

Then run a minimal protocol:

```bash
PYTHONPATH=src python setup/run_protocol.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
```

## How CubOS Is Organized

A runnable experiment is defined by three YAML files:

```text
configs/
  gantry/     # machine envelope, serial port, homing, instruments
  deck/       # labware placement, holder nesting, calibration anchors
  protocol/   # ordered experiment steps
```

The runtime package is split by responsibility:

- `src/gantry/` handles GRBL communication, coordinates, and machine geometry.
- `src/deck/` loads labware definitions and resolves deck positions.
- `src/protocol_engine/` validates and executes protocol commands.
- `src/instruments/` contains instrument drivers, mocks, and registry metadata.
- `data/` provides SQLite persistence and analysis helpers.
- `setup/` contains operator-facing validation, calibration, and run scripts.

UI/API wrappers such as Zoo should use `gantry.session.GantrySession` when they
need a persistent connected gantry. The session owns serial locking, cached
position/status, manual movement guards, calibration soft-limit state, protocol
execution against the connected gantry, campaign creation, and run persistence.

For configuration details, command semantics, and operator procedures, use the
full documentation instead of treating this README as the source of truth.

## Documentation

- [Getting Started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [Calibration](docs/calibration.md)
- [Gantry](docs/gantry.md)
- [Deck](docs/deck.md)
- [Run a Protocol with YAML](docs/protocol-yaml.md)
- [Python Protocols](docs/protocol-python.md)
- [Data](docs/data.md)
- [Gantry Bring-Up](docs/admin/gantry-bring-up.md)
- [Troubleshooting & Recovery](docs/troubleshooting.md)
- [API Reference](docs/reference/index.md)

Build and serve the documentation locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Development

Install developer dependencies and run the test suite:

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
```

For hardware-adjacent changes, also run focused setup validation for the
affected gantry, deck, and protocol combination:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_indentation.yaml
```

Run `mkdocs build --strict` before publishing documentation changes.
