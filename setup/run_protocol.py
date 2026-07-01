"""Load, validate, and run a protocol end-to-end.

Usage:
    python setup/run_protocol.py <gantry.yaml> <deck.yaml> <protocol.yaml>

Example:
    python setup/run_protocol.py \\
        ../BU-Configs/configs/gantry/cub_xl_asmi.yaml \\
        ../BU-Configs/configs/deck/asmi_deck.yaml \\
        ../BU-Configs/configs/protocol/asmi/move_a1.yaml

Steps:
    1. Validate all configs and bounds (offline, no hardware)
    2. Load gantry config and create gantry
    3. Connect to gantry
    4. Clear any startup alarm
    5. Connect instruments
    6. Run the protocol
    7. Disconnect
"""

import sys
import traceback
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from data import (
    DataStore,
    create_campaign_for_protocol_run,
    default_database_path,
    export_campaign_results_csvs,
)
from protocol_engine.setup import run_on_hardware
from protocol_engine.setup_validator import run_setup_validation

SEPARATOR = "-" * 60


def main() -> None:
    if len(sys.argv) != 4:
        print("Usage: python setup/run_protocol.py <gantry.yaml> <deck.yaml> <protocol.yaml>")
        print()
        print("Example:")
        print("  python setup/run_protocol.py \\")
        print("    ../BU-Configs/configs/gantry/cub_xl_asmi.yaml \\")
        print("    ../BU-Configs/configs/deck/asmi_deck.yaml \\")
        print("    ../BU-Configs/configs/protocol/asmi/move_a1.yaml")
        sys.exit(1)

    gantry_path, deck_path, protocol_path = sys.argv[1:4]

    # Phase 1: Validate (offline, before touching hardware)
    result = run_setup_validation(gantry_path, deck_path, protocol_path)
    print(result.output)
    if not result.passed:
        print("\nAborting — validation did not pass.")
        sys.exit(1)

    # Phase 2: Run on hardware via the shared orchestration path.
    # run_on_hardware owns the full lifecycle: construct gantry, re-load and
    # validate configs, connect, prepare, connect instruments, health check,
    # execute, and disconnect in finally.
    print()
    print(SEPARATOR)
    print("Running protocol on hardware...")
    print(SEPARATOR)
    print()

    db_path = default_database_path()
    data_store = DataStore(db_path)
    try:
        campaign_id = create_campaign_for_protocol_run(
            data_store,
            gantry_path=gantry_path,
            deck_path=deck_path,
            gantry_file=gantry_path,
            deck_file=deck_path,
            protocol_file=protocol_path,
            description=(
                f"Protocol run: gantry={gantry_path}, deck={deck_path}, "
                f"protocol={protocol_path}"
            ),
        )
        results = run_on_hardware(
            gantry_path,
            deck_path,
            protocol_path,
            data_store=data_store,
            campaign_id=campaign_id,
        )
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nERROR during execution: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        data_store.close()

    result_files = export_campaign_results_csvs(
        db_path,
        campaign_id,
        output_dir=project_root / "data" / "results",
    )

    print()
    print(SEPARATOR)
    print(f"Protocol complete — {len(results)} steps executed.")
    print(f"Measurement data store: {db_path}")
    print("Result CSV files:")
    for path in result_files:
        print(f"  {path}")
    print(SEPARATOR)


if __name__ == "__main__":
    main()
