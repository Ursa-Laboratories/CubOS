"""Simple CLI helpers for exporting CubOS SQLite data to CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

from cubos.data.data_reader import DataReader


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export campaign/experiment data from CubOS SQLite database.",
    )
    parser.add_argument(
        "--db-path",
        default="data/databases/panda_data.db",
        help="Path to SQLite database file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    campaign_parser = subparsers.add_parser(
        "campaign-experiments",
        help="Get experiment IDs for a campaign.",
    )
    campaign_parser.add_argument("campaign_id", type=int)
    campaign_parser.add_argument("--csv", help="Optional output CSV path.")

    experiment_parser = subparsers.add_parser(
        "experiment-all",
        help="Get all measurements for an experiment (instrument-agnostic).",
    )
    experiment_parser.add_argument("experiment_id", type=int)
    experiment_parser.add_argument("--csv", help="Optional output CSV path.")

    instrument_parser = subparsers.add_parser(
        "experiment-instrument",
        help="Get measurements for an experiment filtered by instrument.",
    )
    instrument_parser.add_argument("experiment_id", type=int)
    instrument_parser.add_argument(
        "instrument",
        help="Instrument name: uvvis, filmetrics, camera, asmi",
    )
    instrument_parser.add_argument("--csv", help="Optional output CSV path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    with DataReader(db_path=args.db_path) as reader:
        if args.command == "campaign-experiments":
            df = reader.get_experiment_ids_dataframe(args.campaign_id)
        elif args.command == "experiment-all":
            df = reader.get_experiment_measurements_dataframe(args.experiment_id)
        elif args.command == "experiment-instrument":
            df = reader.get_experiment_measurements_by_instrument_dataframe(
                args.experiment_id,
                args.instrument,
            )
        else:  # pragma: no cover
            parser.error(f"Unknown command: {args.command}")
            return 2

        if args.csv:
            output = reader.export_dataframe_to_csv(df, args.csv)
            print(f"Wrote CSV: {Path(output).resolve()}")
            return 0

        if df.empty:
            print("No rows found.")
            return 0
        print(df.to_string(index=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
