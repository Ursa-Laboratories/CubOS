import os
import subprocess
import sys
from pathlib import Path


def test_validate_setup_imports_from_source_tree() -> None:
    """The validation tool is importable from the namespaced source tree."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    result = subprocess.run(
        [sys.executable, "-c", "import cubos.tools.validate_setup"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Import failed with stderr:\n"
        f"{result.stderr}"
    )


def test_run_protocol_imports_from_source_tree() -> None:
    """The protocol runner is importable from the namespaced source tree."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    result = subprocess.run(
        [sys.executable, "-c", "import cubos.tools.run_protocol"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Import failed with stderr:\n"
        f"{result.stderr}"
    )


def test_single_instrument_calibration_imports_from_source_tree() -> None:
    """The calibration tool resolves through the CubOS namespace."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
                "import cubos.tools.calibration.single_instrument_calibration",
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
