"""One-shot gantry homing from a gantry YAML file.

This script homes the controller only. It does not assign or rewrite work
coordinates; use ``setup/calibrate_gantry.py`` for deck-origin WPos
calibration.

Loads a gantry config, connects, runs the configured standard GRBL homing
sequence (``$H``), then disconnects.

Usage::

    python setup/home_gantry_config.py --gantry configs/gantry/cub_xl_asmi.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from gantry import Gantry, load_gantry_from_yaml_safe  # noqa: E402
from gantry.origin import validate_deck_origin_minima  # noqa: E402


def run_homing(gantry_path: Path) -> None:
    """Home the gantry without changing work coordinates.

    Args:
        gantry_path: Path to a validated gantry YAML file.
    """
    config = load_gantry_from_yaml_safe(gantry_path)
    validate_deck_origin_minima(config)

    gantry = Gantry(config=config)
    try:
        gantry.connect()
        gantry.home()
    finally:
        gantry.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Connect, run configured homing, and disconnect without changing WPos."
        )
    )
    parser.add_argument(
        "--gantry",
        type=Path,
        required=True,
        help="Path to deck-origin gantry YAML",
    )
    args = parser.parse_args()

    gantry_path = args.gantry.resolve()
    if not gantry_path.is_file():
        print(f"ERROR: Gantry config not found: {gantry_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {gantry_path}")
    try:
        run_homing(gantry_path)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
