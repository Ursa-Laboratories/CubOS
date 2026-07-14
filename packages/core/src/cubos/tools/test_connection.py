"""Test a gantry connection and print a compact diagnostic report.

This script is intended for first-time controller bring-up. It can also be
imported by tests for its report helpers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from cubos.gantry import Gantry


def format_grbl_settings(grbl_settings: dict[str, str]) -> list[str]:
    """Return stable one-line strings for a GRBL settings mapping."""
    return [
        f"{setting} = {value}"
        for setting, value in sorted(
            grbl_settings.items(),
            key=lambda item: int(item[0].removeprefix("$")),
        )
    ]


def build_connection_report(
    *,
    port: str,
    status: str,
    coordinates: dict[str, float],
    healthy: bool,
    grbl_settings: dict[str, str],
    alarm: bool,
) -> str:
    """Build a human-readable connection report."""
    lines = [
        "Connection Report",
        "=================",
        f"Connection: {port}",
        f"Healthy: {'yes' if healthy else 'no'}",
        f"Status: {status}",
        (
            "Coordinates: "
            f"X={coordinates['x']:.3f}, "
            f"Y={coordinates['y']:.3f}, "
            f"Z={coordinates['z']:.3f}"
        ),
        f"Alarm: {'ALARM' if alarm else 'clear'}",
        "GRBL Settings:",
    ]

    formatted_settings = format_grbl_settings(grbl_settings)
    if formatted_settings:
        lines.extend(f"  {line}" for line in formatted_settings)
    else:
        lines.append("  (none reported)")

    return "\n".join(lines)


def _default_config_dir() -> Path:
    """Return the sibling BU-Configs tree when this workspace has it."""
    sibling_config_dir = project_root.parent / "BU-Configs" / "configs"
    if sibling_config_dir.exists():
        return sibling_config_dir
    return project_root / "configs"


def _load_gantry_config(gantry_name: str, *, config_dir: Path | None = None) -> dict[str, Any]:
    """Load a gantry YAML config by name from a config root."""
    config_root = config_dir or _default_config_dir()
    config_path = config_root / "gantry" / f"{gantry_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Gantry config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _collect_connection_info(
    gantry_name: str,
    port: str | None,
    *,
    config_dir: Path | None = None,
) -> str:
    """Connect to the gantry and return a formatted diagnostic report."""
    config = _load_gantry_config(gantry_name, config_dir=config_dir)
    report_port = port or config.get("serial_port", "<auto-scan>")
    gantry = Gantry(config=config)

    grbl_settings: dict[str, str] = {}
    status = "Unknown"
    coordinates = {"x": 0.0, "y": 0.0, "z": 0.0}
    healthy = False
    alarm = False

    try:
        gantry.connect(port=port)
        healthy = gantry.is_healthy()
        coordinates = gantry.get_coordinates()
        status = gantry.get_status()
        alarm = "alarm" in status.lower()
        grbl_settings = gantry.read_grbl_settings()
        report_port = gantry.connected_port() or report_port
    finally:
        gantry.disconnect()

    return build_connection_report(
        port=report_port,
        status=status,
        coordinates=coordinates,
        healthy=healthy,
        grbl_settings=grbl_settings,
        alarm=alarm,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gantry",
        default="cub_xl",
        help="Gantry config name in <config-dir>/gantry/ without the .yaml suffix.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help=(
            "Config root containing gantry/deck/protocol directories. "
            "Defaults to ../BU-Configs/configs when present."
        ),
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Optional serial port override, for example /dev/tty.usbserial-130.",
    )
    args = parser.parse_args()

    try:
        print(_collect_connection_info(args.gantry, args.port, config_dir=args.config_dir))
    except Exception as exc:
        print(f"Connection test failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
