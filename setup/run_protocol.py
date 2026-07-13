"""Load, validate, and run a protocol end-to-end.

Usage:
    python setup/run_protocol.py [options] <gantry.yaml> <deck.yaml> <protocol.yaml>

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

import argparse
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


class _RunProtocolParser(argparse.ArgumentParser):
    """Keep the historical CLI's exit code and stdout usage surface."""

    def error(self, message: str) -> None:
        print(
            "Usage: python setup/run_protocol.py [options] "
            "<gantry.yaml> <deck.yaml> <protocol.yaml>"
        )
        print(f"error: {message}")
        self.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = _RunProtocolParser(
        description=(
            "Validate and run one CubOS protocol. Hardware is used by default; "
            "pass --mock for an explicit offline run."
        ),
    )
    parser.add_argument("gantry_path", help="Gantry YAML path")
    parser.add_argument("deck_path", help="Deck YAML path")
    parser.add_argument("protocol_path", help="Protocol YAML path")
    fluid_group = parser.add_mutually_exclusive_group()
    fluid_group.add_argument(
        "--fluid-state-id",
        type=int,
        help="Resume this existing deck-bound fluid-state ID",
    )
    fluid_group.add_argument(
        "--initial-fluids",
        type=Path,
        help="Create and seed a new fluid state from this YAML file",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run gantry and instruments offline; never connect to hardware",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path (default: CubOS data directory or env override)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    gantry_path = args.gantry_path
    deck_path = args.deck_path
    protocol_path = args.protocol_path

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
    if args.mock:
        print("Running protocol in explicit offline mock mode...")
    else:
        print("Running protocol on hardware...")
    print(SEPARATOR)
    print()

    db_path = args.database or default_database_path()
    data_store = DataStore(db_path)
    campaign_id = None
    linked_fluid_state_id = None
    results = []
    exit_code = 0
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
            mock_mode=args.mock,
            fluid_state_id=args.fluid_state_id,
            initial_fluids=args.initial_fluids,
        )
    except KeyboardInterrupt:
        print("\nAborted by user.")
        exit_code = 130
    except Exception as exc:
        print(f"\nERROR during execution: {exc}")
        traceback.print_exc()
        exit_code = 1
    finally:
        if campaign_id is not None:
            try:
                linked_fluid_state_id = data_store.get_campaign_fluid_state_id(
                    campaign_id
                )
            except Exception as exc:
                print(f"\nWARNING: could not read linked fluid-state ID: {exc}")
        data_store.close()

    result_files = []
    if campaign_id is not None:
        try:
            result_files = export_campaign_results_csvs(
                db_path,
                campaign_id,
                output_dir=project_root / "data" / "results",
            )
        except Exception as exc:
            print(f"\nERROR exporting result CSVs for campaign {campaign_id}: {exc}")
            traceback.print_exc()
            if exit_code == 0:
                exit_code = 1

    print()
    print(SEPARATOR)
    if exit_code == 0:
        print(f"Protocol complete — {len(results)} steps executed.")
    else:
        print(f"Protocol did not complete — {len(results)} steps executed before exit.")
    print(f"Measurement data store: {db_path}")
    if linked_fluid_state_id is not None:
        print(f"Linked fluid state ID: {linked_fluid_state_id}")
    if campaign_id is not None:
        print("Result CSV files:")
        for path in result_files:
            print(f"  {path}")
    print(SEPARATOR)
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
