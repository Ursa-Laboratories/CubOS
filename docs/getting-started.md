# Getting Started

This guide gets CubOS installed and points you to the right setup path. First
time users should follow the YAML workflow: one gantry file, one deck file, and
one protocol file.

## Setup Path

1. Install CubOS.
2. Prefer working in a browser over a terminal? Most of the steps below can
   also be done point-and-click in the [Operator UI](operator-ui.md).
3. If you are building your own machine, complete
   [Gantry Bring-Up](admin/gantry-bring-up.md).
4. Create your gantry YAML from the right seed config and define your
   mounted instruments with [Set Up Gantry YAML](gantry-setup.md).
5. Calibrate the gantry with [Calibrate Gantry](calibration.md).
6. Place labware and define deck YAML with [Set Up Deck and Labware](deck.md).
7. Validate and run a protocol with
   [Run a Protocol with YAML](protocol-yaml.md).
8. If something goes wrong along the way, see
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
- Verify, from Git Bash or PowerShell:
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
  .\.venv\Scripts\Activate.ps1
  ```

Then upgrade pip and install CubOS. Pip may print a notice that a newer version
is available; the first command below performs that update without depending on
the version numbers shown in the notice.

```bash
python -m pip install --upgrade pip
python -m pip install -e "packages/core[dev]"
python -m pip install -e services/api
```

The first install is the CubOS runtime (`cubos`); the second is the
`cubos_api` server that powers the [Operator UI](operator-ui.md). If you
plan to work only from the terminal with YAML files, the `services/api`
install is optional — but it is required before `python -m cubos_api` will
work. Note that `services/api` needs Python 3.11+ (the core package alone
works on 3.10).

### Build the Operator UI (browser app)

The `cubos_api` server serves the Operator UI's compiled web assets from
`apps/operator-web/dist/`. That folder is not checked into the repository —
build it once with Node.js:

1. Install [Node.js 20 LTS or newer](https://nodejs.org) (it includes
   `npm`).
2. From the repository root:

   ```bash
   cd apps/operator-web
   npm ci
   npm run build
   cd ../..
   ```

Skip this if you work only from the terminal. If you start
`python -m cubos_api` without building, the server still runs (the HTTP API
works), but it logs `compiled web assets were not found` and the browser
shows **404 Not Found** at `http://127.0.0.1:8742`. After building, start
`python -m cubos_api` again — the server only looks for the assets at
startup. Re-run `npm run build` whenever you pull changes that touch
`apps/operator-web/`.

### Instrument extras

Instrument vendor SDKs are optional — install only the extras for hardware
you actually use. The extras currently defined in
`packages/core/pyproject.toml`:

| Extra | Installs | For |
|---|---|---|
| `dev` | `pytest` | Running the test suite |
| `docs` | `mkdocs`, `mkdocs-gen-files`, `mkdocstrings[python]`, `pymdown-extensions` | Building this documentation site |
| `asmi-vernier` (alias `asmi`) | `godirect` | Vernier Go Direct force sensor (ASMI instrument) |
| `potentiostat-admiral` (alias `potentiostat`) | `SquidstatPyLibrary` | Admiral Instruments SquidStat potentiostat |

For example, to work on an ASMI setup:

```bash
python -m pip install -e "packages/core[asmi-vernier]"
```

Instrument types without a dedicated extra (`filmetrics`, `pipette`,
`uv_curing`, `uvvis_ccs`, `camera`) don't require an extra vendor SDK install
beyond CubOS's base dependencies.

Customer/proprietary instruments ship as normal Python packages — install the
package with `python -m pip install`, and its instruments become available in
the gantry YAML like any built-in type.
