# Getting Started

This guide gets CubOS installed and points you to the right setup path. First
time users should follow the YAML workflow: one gantry file, one deck file, and
one protocol file.

## Setup Path

1. Install CubOS.
2. If you are building your own machine, complete
   [Gantry Bring-Up](admin/gantry-bring-up.md).
3. Calibrate the gantry with [Calibrate Gantry](calibration.md).
4. Place labware and define deck YAML with [Set Up Deck and Labware](deck.md).
5. Validate and run a protocol with
   [Run a Protocol with YAML](protocol-yaml.md).
6. If something goes wrong along the way, see
   [Troubleshooting & Recovery](troubleshooting.md).

## Prerequisites

CubOS needs Python 3.10+ and Git installed first. **All shell commands
elsewhere in these docs assume a Unix-like shell.** On Windows, install
[Git for Windows](https://git-scm.com/download/win) (it bundles **Git
Bash**) and run every command in these docs from a Git Bash window — or
translate the command to PowerShell yourself. Where a step differs on
Windows, both are shown below.

### Windows

- Install [Git for Windows](https://git-scm.com/download/win). Use the Git
  Bash it installs for the commands in these docs.
- Install [Python 3.10 or newer](https://www.python.org/downloads/windows/).
  During setup, check "Add python.exe to PATH".
- Verify, from Git Bash:
  ```bash
  python --version
  git --version
  ```

### macOS

- Install [Homebrew](https://brew.sh) if you don't have it, then:
  ```bash
  brew install python@3.11 git
  ```
- Use the Homebrew `python3`, not the older system Python.

### Linux

- Install Python 3.10+ and Git with your distro's package manager, e.g. on
  Debian/Ubuntu:
  ```bash
  sudo apt install python3 python3-venv python3-pip git
  ```

For all platforms, you'll also need:

- For hardware runs: a GRBL-compatible gantry connected over serial. We
  currently support the
  [Genmitsu 3018-PROVer V2](https://www.sainsmart.com/products/genmitsu-3018-prover-v2-upgraded-semi-assembled-cnc-router-kit)
  (Cub) and the
  [ProverXL 4030 V2](https://www.sainsmart.com/products/proverxl-4030-v2)
  (CubXL), but CubOS should work with any GRBL controller that has homing
  switches.
- For real instruments: the vendor SDKs required by those vendor drivers
  (see [Instrument extras](#instrument-extras) below).

If you bought a CubOS system through [ursalabs.ai](https://ursalabs.ai), gantry
controller bring-up should already be handled. If you are setting up your own
machine, normalize controller direction, homing, and WPos reporting with
[Gantry Bring-Up](admin/gantry-bring-up.md) before calibration.

## Installation

```bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
```

Activate the virtual environment:

- **macOS / Linux:**
  ```bash
  source .venv/bin/activate
  ```
- **Windows, Git Bash:**
  ```bash
  source .venv/Scripts/activate
  ```
- **Windows, PowerShell:**
  ```powershell
  .venv\Scripts\activate
  ```

Then install CubOS:

```bash
pip install -U pip
pip install -e ".[dev]"
```

### Instrument extras

Instrument vendor SDKs are optional — install only the extras for hardware
you actually use. The extras currently defined in `pyproject.toml`:

| Extra | Installs | For |
|---|---|---|
| `dev` | `pytest` | Running the test suite |
| `docs` | `mkdocs`, `mkdocs-gen-files`, `mkdocstrings[python]`, `pymdown-extensions` | Building this documentation site |
| `asmi-vernier` (alias `asmi`) | `godirect` | Vernier Go Direct force sensor (ASMI instrument) |
| `potentiostat-admiral` (alias `potentiostat`) | `SquidstatPyLibrary` | Admiral Instruments SquidStat potentiostat |

For example, to work on an ASMI setup:

```bash
pip install -e ".[asmi-vernier]"
```

Instrument types without a dedicated extra (`filmetrics`, `pipette`,
`uv_curing`, `uvvis_ccs`, `camera`) don't require an extra vendor SDK install
beyond CubOS's base dependencies — see
[Defining instrument drivers](protocol-yaml.md#defining-instrument-drivers)
for the YAML for each.

Customer/proprietary instruments are supplied as normal Python packages that
register CubOS instrument drivers through the `cubos.instrument_registries`
entry point group, or as explicit registry overlay YAMLs listed in
`CUBOS_INSTRUMENT_REGISTRY_PATHS`.
