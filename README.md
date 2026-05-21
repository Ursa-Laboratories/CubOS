# CubOS

CubOS is the Python control layer for CNC-based lab automation. It connects a
GRBL gantry, mounted instruments, deck labware, YAML protocols, offline motion
validation, and SQLite-backed experiment data into one operator workflow.

Use CubOS when you want to:

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
- Start with a minimal move protocol before scans, indentation, or dispensing.

The high-level deck frame is:

- origin: front-left-bottom reachable work volume
- `+X`: operator-right
- `+Y`: back, away from the operator
- `+Z`: up, away from the deck

GRBL homing may physically move to the opposite back-right-top corner. CubOS
keeps that controller detail behind the gantry boundary and preserves the
calibrated G54 work-coordinate frame during protocol `home`.

## Quick Start

~~~bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
~~~

Validate an example setup without moving hardware:

~~~bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
~~~

Run a protocol after calibration and hardware checks:

~~~bash
PYTHONPATH=src python setup/run_protocol.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_move_a1.yaml
~~~

## Configuration Files

A runnable experiment is defined by three YAML files:

~~~text
configs/
  gantry/      # machine envelope, serial port, homing, instruments
  deck/        # labware placement, holder nesting, calibration anchors
  protocol/    # ordered experiment steps
~~~

### Gantry

Gantry config defines the physical machine and mounted instruments:

~~~yaml
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 87.0
  safe_z: 85.0

working_volume:
  x_min: 0.0
  x_max: 399.0
  y_min: 0.0
  y_max: 280.0
  z_min: 0.0
  z_max: 87.0

instruments:
  asmi:
    type: asmi
    vendor: vernier
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
~~~

`gantry_type` selects built-in machine-family validation. For `cub_xl`,
setup validation rejects commanded instrument points or known travel segments
that would hit the fixed right X-max rail.

`cnc.safe_z` is the absolute deck-frame travel ceiling used for inter-labware
travel and first-well scan entry. If omitted, it defaults to
`working_volume.z_max`.

### Deck

Deck config defines labware and calibration anchors. Well plates use two-point
calibration; vials and holders use fixed locations or nested contained labware.

~~~yaml
labware:
  plate:
    load_name: sbs_96_wellplate
    name: asmi_96_well
    model_name: asmi_96_well
    calibration:
      a1: { x: 347.0, y: 42.0, z: 30.0 }
      a2: { x: 338.0, y: 42.0, z: 30.0 }
    x_offset: -9.0
    y_offset: 9.0
~~~

Labware `height` is the physical outer dimension. It is not a shortcut for a Z
reference point; Z comes from calibration anchors or fixed locations.

### Protocol

Protocol config defines the ordered experiment steps:

~~~yaml
positions:
  park_position: [360.0, 260.0, 85.0]

protocol:
  - home:
  - move:
      instrument: asmi
      position: plate.A1
~~~

Common commands include `home`, `move`, `scan`, `measure`, `pause`,
and the pipette command set.

Deck targets can reference top-level labware such as `plate.A1` or nested
holder paths such as `plate_holder.plate.A1`. `scan.plate` accepts a
top-level or nested target that resolves to a `WellPlate`.

Protocol motion heights are labware-relative command arguments:

- `measurement_height`: action plane for `measure` and `scan`
- `interwell_scan_height`: between-wells travel plane for `scan`
- `indentation_limit_height`: ASMI deepest descent plane

Positive values are above the calibrated labware surface; negative values are
below it. Inter-labware travel still uses the gantry's absolute `safe_z`.

## Calibration

Use the wrapper script as the operator entrypoint:

~~~bash
PYTHONPATH=src python setup/calibrate_gantry.py configs/gantry/cub_xl_asmi.yaml
~~~

With only an input path, the script prompts before overwriting that gantry YAML.
To write a calibrated copy:

~~~bash
PYTHONPATH=src python setup/calibrate_gantry.py \
  configs/gantry/cub_xl_asmi.yaml \
  --output-gantry configs/gantry/cub_xl_asmi_calibrated.yaml
~~~

During calibration jogs, hard-limit alarms use CubOS' reusable limit recovery:
soft reset, unlock, pull off opposite the failed jog, and retry up to five
times before aborting.

See the docs for the full operator tutorial:

After calibration, run:

~~~bash
PYTHONPATH=src python setup/hello_world.py \
  --gantry configs/gantry/cub_xl_asmi.yaml
~~~

Use the jog test to confirm physical direction before running protocols.

## Optional Instrument Extras

Core dependencies stay small. Vendor SDKs are installed only when needed:

~~~bash
# Vernier GoDirect ASMI force sensor
pip install -e ".[asmi]"

# Admiral Instruments SquidStat potentiostat
pip install -e ".[potentiostat]"
~~~

Instrument drivers import optional SDKs lazily and raise clear errors if the
required extra is missing.

## Python API

~~~python
from protocol_engine.setup import setup_protocol
from protocol_engine.setup_validation import run_setup_validation

validation = run_setup_validation(
    gantry_path="configs/gantry/cub_xl_asmi.yaml",
    deck_path="configs/deck/asmi_deck.yaml",
    protocol_path="configs/protocol/asmi_move_a1.yaml",
)
if not validation.passed:
    raise RuntimeError(validation.output)

protocol, context = setup_protocol(
    gantry_path="configs/gantry/cub_xl_asmi.yaml",
    deck_path="configs/deck/asmi_deck.yaml",
    protocol_path="configs/protocol/asmi_move_a1.yaml",
    mock_mode=True,
)

protocol.run(context)
~~~

## Data Persistence

Campaign state can be stored in SQLite through `data.DataStore`. Measurement
commands can log into a `ProtocolContext` when `data_store` and
`campaign_id` are provided.

## Development

Install developer dependencies, run the tests, and build docs locally:

~~~bash
pip install -e ".[dev,docs]"
PYTHONPATH=src pytest tests/
mkdocs serve
~~~

For focused hardware-adjacent changes, validate the affected setup explicitly:

~~~bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/cub_xl_asmi.yaml \
  configs/deck/asmi_deck.yaml \
  configs/protocol/asmi_indentation.yaml
~~~

## Documentation

- [Getting Started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [Gantry](docs/gantry.md)
- [Deck](docs/deck.md)
- [Protocol](docs/protocol.md)
- [Calibration](docs/calibration.md)
- [Data](docs/data.md)
- [Gantry Bring-Up](docs/admin/gantry-bring-up.md)
