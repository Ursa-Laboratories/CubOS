"""Hardware test script for WPos enforcement changes on a Genmitsu desktop CNC.

This script validates the changes from the 'Standardize coordinate system on WPos'
commit by running against a real, physically connected mill. It tests:

1. Connection enforces WPos mode ($10=0) and absolute positioning (G90)
2. current_coordinates() returns WPos consistently
3. Post-homing coordinate validation works
4. Small moves report correct WPos values

Usage:
    python tests/hardware/test_wpos_enforcement.py [--port /dev/ttyUSB0] [--skip-homing]
"""

import argparse
import sys
import time

from gantry.coordinates import Coordinates
from gantry.gantry_driver.driver import Mill
from gantry.gantry_driver.exceptions import StatusReturnError, LocationNotFound


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"

results = []


def record(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((name, passed))
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def record_skip(name: str, reason: str):
    results.append((name, None))
    print(f"  [{SKIP}] {name} — {reason}")


def test_wpos_mode_enforced(mill: Mill):
    """Verify $10 is set to 0 (WPos reporting) after connection."""
    print("\n--- Test: WPos mode enforced on connect ---")
    config_val = mill.config.get("$10", None)
    record(
        "$10 config is '0'",
        config_val == "0",
        f"$10={config_val}",
    )


def test_status_returns_wpos(mill: Mill):
    """Verify that status query contains WPos, not MPos."""
    print("\n--- Test: Status reports WPos ---")
    mill.ser_mill.write(b"?")
    time.sleep(0.3)
    status = mill._read_serial()
    has_wpos = "WPos:" in status
    has_mpos = "MPos:" in status
    record("Status contains WPos", has_wpos, f"status={status[:80]}")
    record("Status does NOT contain MPos", not has_mpos)


def test_current_coordinates_returns_valid(mill: Mill):
    """Verify current_coordinates() succeeds and returns a Coordinates object."""
    print("\n--- Test: current_coordinates() returns valid WPos ---")
    try:
        coords = mill.current_coordinates()
        is_coords = isinstance(coords, Coordinates)
        record(
            "current_coordinates() returns Coordinates",
            is_coords,
            f"{coords}",
        )
        record(
            "Coordinates are finite numbers",
            all(abs(getattr(coords, a)) < 1000 for a in ("x", "y", "z")),
            f"x={coords.x}, y={coords.y}, z={coords.z}",
        )
    except LocationNotFound:
        record("current_coordinates() returns Coordinates", False, "LocationNotFound raised")


def test_absolute_positioning(mill: Mill):
    """Verify mill is in G90 (absolute) mode by checking parser state."""
    print("\n--- Test: Absolute positioning (G90) enforced ---")
    try:
        state = mill.execute_command("$G")
        has_g90 = "g90" in str(state).lower()
        record("Parser state includes G90", has_g90, f"state={state}")
    except Exception as e:
        record("Parser state includes G90", False, str(e))


def test_small_move_wpos(mill: Mill):
    """Do a small relative move and confirm WPos updates accordingly."""
    print("\n--- Test: Small move updates WPos correctly ---")
    try:
        before = mill.current_coordinates()
        # Move 1mm in X from current position
        target_x = before.x - 1.0
        mill.execute_command(f"G90 G01 X{target_x} Y{before.y} Z{before.z} F500")
        # Wait for move to complete
        time.sleep(3)
        after = mill.current_coordinates()
        delta_x = abs(after.x - target_x)
        record(
            "WPos X updated after 1mm move",
            delta_x < 0.1,
            f"expected X≈{target_x}, got X={after.x}, delta={delta_x:.3f}",
        )
        # Move back
        mill.execute_command(f"G90 G01 X{before.x} Y{before.y} Z{before.z} F500")
        time.sleep(3)
        restored = mill.current_coordinates()
        delta_restore = abs(restored.x - before.x)
        record(
            "WPos restored after return move",
            delta_restore < 0.1,
            f"expected X≈{before.x}, got X={restored.x}",
        )
    except Exception as e:
        record("WPos X updated after 1mm move", False, str(e))


def test_homing_and_validation(mill: Mill):
    """Home the mill and verify post-homing coordinate validation passes."""
    print("\n--- Test: Homing + post-homing coordinate validation ---")
    try:
        mill.home()
        coords = mill.current_coordinates()
        within_tol = (
            abs(coords.x) < 10.0
            and abs(coords.y) < 10.0
            and abs(coords.z) < 10.0
        )
        record(
            "Post-homing coords near origin",
            within_tol,
            f"{coords}",
        )
        record("home() completed without error", True)
    except StatusReturnError as e:
        record("Post-homing coords near origin", False, str(e))
    except Exception as e:
        record("home() completed without error", False, str(e))


def print_summary():
    print("\n" + "=" * 60)
    total = len(results)
    passed = sum(1 for _, p in results if p is True)
    failed = sum(1 for _, p in results if p is False)
    skipped = sum(1 for _, p in results if p is None)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped out of {total}")
    if failed > 0:
        print("\nFailed tests:")
        for name, p in results:
            if p is False:
                print(f"  - {name}")
    print("=" * 60)
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Hardware test for WPos enforcement")
    parser.add_argument("--port", type=str, default=None, help="Serial port (auto-detect if omitted)")
    parser.add_argument("--skip-homing", action="store_true", help="Skip the homing test (if mill is already homed)")
    args = parser.parse_args()

    print("=" * 60)
    print("WPos Enforcement Hardware Test — Genmitsu Desktop CNC")
    print("=" * 60)

    # Connect
    print("\nConnecting to mill...")
    mill = Mill(port=args.port)
    mill.connect(port=args.port)
    print(f"Connected on {mill.ser_mill.port}")

    # Run tests that don't require homing first
    test_wpos_mode_enforced(mill)
    test_status_returns_wpos(mill)
    test_absolute_positioning(mill)
    test_current_coordinates_returns_valid(mill)

    # Homing test
    if args.skip_homing:
        record_skip("Homing + post-homing validation", "skipped via --skip-homing")
    else:
        print("\n** Homing will move the machine. Make sure the area is clear. **")
        confirm = input("Proceed with homing? [y/N]: ").strip().lower()
        if confirm == "y":
            test_homing_and_validation(mill)
        else:
            record_skip("Homing + post-homing validation", "user declined")

    # Small move test (only if homed or user already homed)
    if mill.homed or args.skip_homing:
        print("\n** Small move test will jog X by 1mm and back. **")
        confirm = input("Proceed with small move test? [y/N]: ").strip().lower()
        if confirm == "y":
            test_small_move_wpos(mill)
        else:
            record_skip("Small move WPos test", "user declined")
    else:
        record_skip("Small move WPos test", "mill not homed")

    # Summary
    all_passed = print_summary()

    # Cleanup
    print("\nDisconnecting...")
    mill.stop()

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
