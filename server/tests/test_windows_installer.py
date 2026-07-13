import re
import shutil
import subprocess
from pathlib import Path
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_INSTALLER = ROOT / "installer" / "windows"


def _extract_ini_section(text: str, section: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"[{section}]":
            start = index + 1
            break
    if start is None:
        return ""
    end = start
    while end < len(lines) and not lines[end].strip().startswith("["):
        end += 1
    return "\n".join(lines[start:end])


def test_windows_runtime_uses_venv_and_installs_zoo_and_cubos() -> None:
    install_runtime = (WINDOWS_INSTALLER / "scripts" / "Install-Runtime.ps1").read_text()
    start_zoo = (WINDOWS_INSTALLER / "scripts" / "Start-Zoo.ps1").read_text()

    assert 'Join-Path $InstallDir "venv"' in install_runtime
    assert 'Join-Path $VenvDir "Scripts\\python.exe"' in install_runtime
    assert 'Invoke-LoggedNative $Python @("-m", "venv", $VenvDir)' in install_runtime
    assert '"--upgrade", "pip"' not in install_runtime
    assert '"cubos", "zoo"' in install_runtime

    assert 'Join-Path $InstallDir "venv\\Scripts\\python.exe"' in start_zoo
    assert "& $RuntimePython -m zoo" in start_zoo


def test_windows_runtime_install_reports_visible_progress() -> None:
    """The runtime install is a long, mostly-silent sequence of offline pip
    commands. Without incremental feedback it looks frozen, so Install-Runtime
    must emit a per-phase banner, drive a progress bar, and print a heartbeat
    while a command is still running."""
    install_runtime = (WINDOWS_INSTALLER / "scripts" / "Install-Runtime.ps1").read_text()

    # Numbered per-phase banners with a total-step count.
    assert "Set-TotalSteps" in install_runtime
    assert "function Start-Step" in install_runtime
    assert "[$($script:StepIndex)/$($script:TotalSteps)]" in install_runtime

    # A progress bar the operator (or Inno wizard host) can render.
    assert "Write-Progress" in install_runtime

    # A heartbeat emitted during silent stretches so the step never looks hung.
    assert "still" in install_runtime.lower()
    assert "elapsed" in install_runtime.lower()

    # The step total must match the number of fixed phases (venv, core deps,
    # Zoo/CubOS, verify) plus one step per selected driver group.
    assert "Set-TotalSteps (4 + $SelectedDriverGroups.Count)" in install_runtime
    start_step_calls = install_runtime.count('Start-Step "')
    assert start_step_calls == 5  # 4 fixed phases + the one inside the driver loop


def test_windows_installer_offers_asmi_as_optional_public_driver() -> None:
    iss = (WINDOWS_INSTALLER / "Zoo.iss").read_text()
    build_script = (WINDOWS_INSTALLER / "build-installer.ps1").read_text()
    install_runtime = (WINDOWS_INSTALLER / "scripts" / "Install-Runtime.ps1").read_text()
    runtime_requirements = (WINDOWS_INSTALLER / "runtime-requirements.txt").read_text()
    asmi_requirements = (
        WINDOWS_INSTALLER / "requirements" / "drivers" / "asmi.txt"
    ).read_text()

    assert "ASMI Go Direct driver support" in iss
    asmi_task_line = next(line for line in iss.splitlines() if 'Name: "asmi"' in line)
    assert "unchecked" not in asmi_task_line.lower()

    # Inno Setup task hierarchy is positional: a task at indent level N becomes
    # a child of the nearest preceding level-(N-1) task. Any backslash in a
    # [Tasks] name would (re-)introduce accidental parenting like the ASMI
    # default-selection bug this suite is guarding against.
    tasks_section = _extract_ini_section(iss, "Tasks")
    assert tasks_section
    task_names = re.findall(r'Name:\s*"([^"]+)"', tasks_section)
    assert task_names
    assert all("\\" not in name for name in task_names)

    assert "GetDriverGroups" in iss
    assert "WizardIsTaskSelected('asmi')" in iss
    assert "godirect" not in runtime_requirements.lower()
    assert "godirect>=1.2.1" in asmi_requirements
    assert "$DriverRequirementsDir" in build_script
    assert "requirements\\drivers" in build_script
    assert "$SelectedDriverGroups" in install_runtime


def _requirement_name(spec: str) -> str:
    """Return the PEP 503-normalized distribution name from a requirement line."""
    # Strip inline comments, environment markers, and the extras/version tail.
    spec = spec.split("#", 1)[0].split(";", 1)[0].strip()
    name = re.split(r"[\s<>=!~\[]", spec, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def test_windows_runtime_requirements_cover_core_zoo_dependencies() -> None:
    """The offline installer builds its wheelhouse and venv from
    runtime-requirements.txt and installs cubos/zoo with --no-deps, so every
    core runtime dependency in pyproject.toml must be listed there. A missing
    entry (e.g. ruamel.yaml) is never bundled or installed and only surfaces as
    a ``pip check`` failure on the user's machine."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime_requirements = (
        WINDOWS_INSTALLER / "runtime-requirements.txt"
    ).read_text()

    listed = {
        _requirement_name(line)
        for line in runtime_requirements.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    # cubos is a direct git dependency built and installed as its own wheel
    # (--no-deps), so it is intentionally absent from runtime-requirements.txt.
    required = {
        _requirement_name(dep)
        for dep in project["project"]["dependencies"]
        if _requirement_name(dep) != "cubos"
    }

    missing = required - listed
    assert not missing, (
        "installer/windows/runtime-requirements.txt is missing core Zoo "
        f"dependencies: {sorted(missing)}"
    )


def test_godirect_is_not_a_core_zoo_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    dependencies = "\n".join(project["project"]["dependencies"]).lower()
    optional = project["project"]["optional-dependencies"]

    assert "godirect" not in dependencies
    assert optional["asmi"] == ["godirect>=1.2.1"]


def test_windows_launcher_seeds_only_generic_config_templates() -> None:
    start_zoo = (WINDOWS_INSTALLER / "scripts" / "Start-Zoo.ps1").read_text()

    assert 'Join-Path $ZooDir "configs"' in start_zoo
    assert 'Join-Path $InstallDir "app\\CubOS\\configs"' not in start_zoo
    assert '"gantry\\cub_seed.yaml"' in start_zoo
    assert '"gantry\\cub_xl_seed.yaml"' in start_zoo
    assert '"deck\\cub_deck_example.yaml"' in start_zoo
    assert '"deck\\cubxl_deck_example.yaml"' in start_zoo

    for named_config in (
        "cub_filmetrics",
        "cub_xl_asmi",
        "cub_xl_panda",
        "cub_xl_sterling",
        "asmi_deck",
        "filmetrics_deck",
        "panda_deck",
        "sterling_deck",
    ):
        assert named_config not in start_zoo


@pytest.mark.skipif(
    shutil.which("pwsh") is None, reason="pwsh is not available on PATH"
)
def test_windows_installer_powershell_scripts_are_syntactically_valid() -> None:
    script_paths = sorted(WINDOWS_INSTALLER.glob("**/*.ps1"))
    assert script_paths, "expected at least one .ps1 script under installer/windows"

    for script_path in script_paths:
        escaped_path = str(script_path).replace("'", "''")
        parse_command = (
            "$errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{escaped_path}', [ref]$null, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 "
            "} else { exit 0 }"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", parse_command],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{script_path} failed PowerShell parse validation: "
            f"{result.stderr or result.stdout}"
        )
