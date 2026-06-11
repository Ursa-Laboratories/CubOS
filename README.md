# CubOS

CubOS is the Python control layer for CNC-based lab automation. It connects a
GRBL gantry, mounted instruments, deck labware, YAML protocols, offline motion
validation, and SQLite-backed experiment data into one operator workflow.

Use CubOS when you need to:

- describe a lab setup with machine, deck, and protocol YAML files
- validate motion targets before hardware moves
- run measurements or liquid-handling steps from reproducible protocols
- store experiment state and measurement data for later analysis
- extend the platform with new instruments or labware definitions

## Safety Model

CubOS can move real hardware. Treat every config or protocol change as a
potential motion change.

- Validate YAML offline before connecting to hardware.
- Calibrate the gantry work frame before trusting real coordinates.
- Keep an E-stop reachable during calibration, jog tests, and protocol runs.
- Start with minimal motion before scans, indentation, or dispensing.

The high-level deck frame is:

- origin: front-left-bottom reachable work volume
- `+X`: operator-right
- `+Y`: back, away from the operator
- `+Z`: up, away from the deck

GRBL may physically home at the back-right-top corner. CubOS keeps that
controller detail behind the gantry boundary and preserves the calibrated G54
work-coordinate frame during protocol `home`.

## Documentation

- [Home](docs/index.md) - CubOS overview and documentation map
- [Getting Started](docs/getting-started.md) - prerequisites and installation
- [Calibration](docs/calibration.md) - gantry calibration and jog checks
- [Configuration](docs/configuration.md) - gantry, deck, and protocol YAML
- [Running a Protocol](docs/protocol.md) - validation, execution, and runtime flow
- [Data](docs/data.md) - SQLite persistence, readers, and CSV export
- [API Reference](docs/reference/index.md) - generated Python API docs

Build the docs locally with:

```bash
pip install -e ".[docs]"
mkdocs build
```
