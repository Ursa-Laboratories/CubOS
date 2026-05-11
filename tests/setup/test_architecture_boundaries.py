"""Architecture guardrails for setup scripts."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_setup_scripts_do_not_reach_low_level_gantry_driver() -> None:
    """Setup and calibration must go through Gantry, not Mill internals."""
    forbidden = ("gantry_driver", "._mill", "Mill(")
    offenders: list[str] = []

    for path in sorted((PROJECT_ROOT / "setup").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} contains {token!r}")

    assert offenders == []


def test_runtime_code_outside_gantry_package_does_not_import_gantry_driver() -> None:
    """Only the gantry package owns the low-level driver dependency."""
    offenders: list[str] = []
    src_root = PROJECT_ROOT / "src"

    for path in sorted(src_root.rglob("*.py")):
        if (src_root / "gantry") in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if "gantry_driver" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
