# Zoo Windows Installer

This directory builds a Windows installer for an operator-facing Zoo runtime.
The installer is intentionally local and self-contained: it installs a private
Python runtime, creates an app-local virtual environment, installs Zoo/CubOS
packages from an offline wheelhouse, copies
the checked-out Zoo and CubOS `main` sources into the app directory, launches
Zoo from the copied Zoo source so the prebuilt frontend is available, and seeds
the operator config folder from CubOS configs on first launch.
The bundled Python installer is retained inside the app directory so `Start Zoo`
can repair a missing private runtime without requiring Python on the operator
machine.

## What The Installer Targets

- Zoo repo: `https://github.com/Ursa-Laboratories/Zoo.git`, branch `main`
- CubOS repo: `https://github.com/Ursa-Laboratories/CubOS.git`, branch `main`
- Runtime: app-local Python 3.11
- Virtual environment: `%LOCALAPPDATA%\Programs\UrsaLabs\Zoo\venv`
- Bundled Python installer: `%LOCALAPPDATA%\Programs\UrsaLabs\Zoo\installers\python-installer.exe`
- User config directory: `%LOCALAPPDATA%\UrsaLabs\Zoo\configs`
- User data database: `%LOCALAPPDATA%\UrsaLabs\Zoo\data\panda_data.db`
- Logs: `%LOCALAPPDATA%\UrsaLabs\Zoo\logs`

The generated installer does not require Python, Node.js, Git, or internet
access on the operator machine.

During install, the wizard lists optional public hardware drivers that can be
installed from the bundled wheelhouse. ASMI support is selected by default and
installs the public `godirect` package. Proprietary drivers, such as UV-Vis
vendor packages, are not offered by this installer.

## Packaging Machine Requirements

Run the build on a Windows x64 machine with:

- Git
- Python 3.11
- Node.js/npm compatible with the frontend lockfile
- Inno Setup 6
- Internet access for cloning repos, downloading wheels, and downloading the
  Python installer

## Build

From the Zoo checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\windows\build-installer.ps1
```

The output is written under:

```text
installer\windows\build\dist\
```

The same build can be run from GitHub Actions through the `Windows Installer`
workflow. The workflow builds on `windows-latest` and uploads the generated
installer as the `zoo-windows-installer` artifact. It runs on pull requests
that touch the installer/runtime surface. Every push to `main` builds the
installer, assigns an automatic version `0.1.<workflow run number>`, and
publishes the `.exe` to a GitHub Release tagged `v0.1.<workflow run number>`.

Useful overrides:

```powershell
.\installer\windows\build-installer.ps1 `
  -ZooRepoUrl https://github.com/Ursa-Laboratories/Zoo.git `
  -CubOSRepoUrl https://github.com/Ursa-Laboratories/CubOS.git `
  -Branch main `
  -AppVersion 0.1.123 `
  -BuildPythonPath "C:\Python311\python.exe" `
  -PythonVersion 3.11.9 `
  -InnoCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

When the script runs in GitHub Actions, the workflow passes
`-ZooSourceDir "$env:GITHUB_WORKSPACE"` so the installer is built from the
checked-out Zoo commit. CubOS is still cloned from `main`.

## Operator Shortcuts

The installer creates Start Menu shortcuts for:

- `Start Zoo`
- `Zoo Configs`
- `Zoo Logs`
- `Export Diagnostics`

`Start Zoo` binds to `127.0.0.1:8742`, opens the browser, and writes a log file.
On first launch, if the user config directory has no YAML files, the launcher
copies the bundled CubOS configs into `%LOCALAPPDATA%\UrsaLabs\Zoo\configs`.

## Validation Checklist

Before handing the installer to an operator:

1. Build the installer on a clean Windows packaging machine.
2. Install it on a clean Windows test VM with no Python, Node.js, or Git on
   `PATH`.
3. Launch `Start Zoo` and confirm `http://127.0.0.1:8742` opens.
4. Confirm `%LOCALAPPDATA%\UrsaLabs\Zoo\configs` contains seeded CubOS config
   YAMLs.
5. Confirm `%LOCALAPPDATA%\Programs\UrsaLabs\Zoo\Python\python.exe` exists.
6. Confirm `%LOCALAPPDATA%\Programs\UrsaLabs\Zoo\venv\Scripts\python.exe`
   exists and can import `zoo`, `gantry`, `deck`, and `protocol_engine`.
7. If ASMI support was selected, confirm the runtime venv can import
   `godirect`.
8. Confirm the gantry and ASMI hardware are not connected during UI-only smoke
   testing, or keep the machine clear and E-stop reachable during hardware
   tests.
9. Use `Export Diagnostics` and verify the zip includes build info, logs,
   configs, and Python package information.

Hardware-touching actions such as connect, home, jog, calibration, and protocol
runs still require normal lab clearance.
