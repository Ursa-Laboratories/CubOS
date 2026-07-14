"""First-run interactive deck-origin gantry jog test.

Loads an explicit gantry YAML, homes the CNC gantry without rewriting WPos, then
lets the operator jog in the CubOS deck frame while displaying position.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from cubos.gantry import Gantry, load_gantry_from_yaml_safe
from cubos.gantry.errors import CommandExecutionError, StatusReturnError
from cubos.gantry.origin import validate_deck_origin_minima
from cubos.tools.keyboard_input import flush_stdin, read_keypress

STEP = 1.0

CONTROLS_LEGEND = """
Controls:
  Arrow LEFT/RIGHT  — Move X axis (±1mm)
  Arrow UP/DOWN     — Move Y axis (+/-1mm)
  Z                 — Move Z down (-1mm)
  X                 — Move Z up (+1mm)
  Q                 — Quit
"""


def print_position(coords: dict) -> None:
    print(f"  Position -> X: {coords['x']:.1f}  Y: {coords['y']:.1f}  Z: {coords['z']:.1f}")


def _looks_like_startup_alarm(gantry: Gantry) -> bool:
    try:
        status = gantry.get_status()
    except StatusReturnError as exc:
        status = str(exc)
    except CommandExecutionError as exc:
        status = str(exc)
    return "alarm" in str(status).lower()


def _looks_like_soft_limit_jog_rejection(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "error:15",
            "travel exceeded",
            "jog target exceeds machine travel",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gantry",
        type=Path,
        required=True,
        help="Path to calibrated deck-origin gantry YAML",
    )
    args = parser.parse_args()
    gantry_path = args.gantry.resolve()
    if not gantry_path.is_file():
        print(f"ERROR: Gantry config not found: {gantry_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 50)
    print("  CubOS — Hello World")
    print("  First-run deck-origin jog test")
    print("=" * 50)

    config = load_gantry_from_yaml_safe(gantry_path)
    validate_deck_origin_minima(config)
    print(f"\nLoaded: {gantry_path}")

    gantry = Gantry(config=config)

    t0 = time.monotonic()
    print("\nConnecting to gantry...")
    gantry.connect()
    print(f"Connected in {time.monotonic() - t0:.1f}s")

    healthy = gantry.is_healthy()
    if not healthy and not _looks_like_startup_alarm(gantry):
        print("Error: Gantry is not healthy. Check the connection and try again.")
        gantry.disconnect()
        sys.exit(1)
    if not healthy:
        print("Controller is in startup alarm; homing clears it.")

    print("Connected successfully.")

    try:
        input("\nPress ENTER to home the gantry...")
        print("Homing... (this may take a moment)")
        gantry.home()
        print("Homing complete.")
        flush_stdin()

        coords = gantry.get_coordinates()
        print_position(coords)
        print(CONTROLS_LEGEND)

        while True:
            key = read_keypress()

            try:
                if key == "LEFT":
                    gantry.jog(x=-STEP)
                elif key == "RIGHT":
                    gantry.jog(x=STEP)
                elif key == "UP":
                    gantry.jog(y=STEP)
                elif key == "DOWN":
                    gantry.jog(y=-STEP)
                elif key == "Z":
                    gantry.jog(z=-STEP)
                elif key == "X":
                    gantry.jog(z=STEP)
                elif key == "Q":
                    print("\nExiting...")
                    break
                else:
                    continue
            except (CommandExecutionError, StatusReturnError) as exc:
                if not _looks_like_soft_limit_jog_rejection(exc):
                    raise
                print(
                    "GRBL rejected that jog because it exceeds current travel. "
                    "Try the other direction or home/recheck the calibrated bounds."
                )
                continue
            coords = gantry.get_coordinates()
            print_position(coords)

    except KeyboardInterrupt:
        print("\nInterrupted — stopping motion...")
        gantry.stop()
    finally:
        print("Disconnecting...")
        gantry.disconnect()
        print("Done.")


if __name__ == "__main__":
    main()
