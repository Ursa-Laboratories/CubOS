# Getting Started

This guide gets CubOS installed and points you to the right setup path. First
time users should follow the YAML workflow: one gantry file, one deck file, and
one protocol file.

## Prerequisites

- Python 3.10 or newer
- `pip`
- Git
- For hardware runs: a GRBL-compatible gantry connected over serial
- For real instruments: the vendor SDKs required by those vendor drivers

If you bought a CubOS system through [ursalabs.ai](https://ursalabs.ai), gantry
controller bring-up should already be handled. If you are setting up your own
machine, normalize controller direction, homing, and WPos reporting with
[Gantry Bring-Up](admin/gantry-bring-up.md) before calibration.

## Installation

```bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Instrument vendor SDKs are optional. Install only the extras for hardware you
actually use, for example:

```bash
pip install -e ".[asmi-vernier]"
```

Customer/proprietary instruments are supplied as normal Python packages that
register CubOS instrument drivers through the `cubos.instrument_registries`
entry point group, or as explicit registry overlay YAMLs listed in
`CUBOS_INSTRUMENT_REGISTRY_PATHS`.

## Setup Path

1. Install CubOS.
2. If you are building your own machine, complete
   [Gantry Bring-Up](admin/gantry-bring-up.md).
3. Calibrate the gantry with [Calibrate Gantry](calibration.md).
4. Place labware and define deck YAML with [Set Up Deck and Labware](deck.md).
5. Validate and run a protocol with
   [Run a Protocol with YAML](protocol-yaml.md).

## Python API

Most operators use YAML files from the command line. Python callers can use:

```python
from protocol_engine.setup import setup_protocol, run_on_hardware
```

See the [API Reference](reference/index.md) for generated module docs.
