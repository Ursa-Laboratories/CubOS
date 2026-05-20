import os
import subprocess
import sys
from pathlib import Path


def test_validate_setup_imports_from_project_root_without_src_on_path() -> None:
    """Regression test for module import path errors in setup scripts."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, "-c", "import setup.validate_setup"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Import failed with stderr:\n"
        f"{result.stderr}"
    )


def test_run_protocol_imports_from_project_root_without_src_on_path() -> None:
    """Ensure run_protocol imports correctly in script-style execution."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, "-c", "import setup.run_protocol"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Import failed with stderr:\n"
        f"{result.stderr}"
    )


def test_single_instrument_calibration_imports_from_project_root_without_src_on_path() -> None:
    """Ensure local setup package wins over any installed third-party setup package."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import setup.calibration.single_instrument_calibration",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Import failed with stderr:\n"
        f"{result.stderr}"
    )
