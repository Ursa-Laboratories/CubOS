#!/usr/bin/env python3
"""Submit a CubOS protocol YAML bundle to a CubOS appliance."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .client import (
    ProtocolBundle,
    StationClient,
    StationRequestError,
    api_token_from_sources,
    metadata_from_json,
    print_json,
)

def main() -> int:
    args = parse_args()
    client = StationClient(args.base_url, api_token=api_token_from_sources(args.token_file))
    bundle = ProtocolBundle.from_paths(
        gantry_config=args.gantry,
        deck_config=args.deck,
        protocol_yaml=args.protocol,
    )

    if not args.no_health_check:
        print_json("health", client.health(timeout=args.health_timeout_s))

    try:
        response = client.run_protocol(
            bundle,
            run_id=args.experiment_id,
            mock_mode=args.mock_mode,
            metadata=metadata_from_json(args.metadata_json),
            timeout=args.timeout_s,
            poll_interval=args.poll_interval_s,
        )
    except KeyboardInterrupt:
        client.cancel_run(args.experiment_id)
        raise
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit gantry, deck, and protocol YAMLs to the CubOS /api/v1 run API."
    )
    parser.add_argument("--base-url", required=True, help="CubOS base URL, e.g. http://cub.local:8742")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--gantry", type=Path, required=True)
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.5)
    parser.add_argument("--health-timeout-s", type=float, default=3.0)
    parser.add_argument("--metadata-json")
    token_file = os.environ.get("CUBOS_API_TOKEN_FILE")
    parser.add_argument("--token-file", type=Path, default=Path(token_file) if token_file else None)
    parser.add_argument("--mock-mode", action="store_true")
    parser.add_argument("--no-health-check", action="store_true")
    return parser.parse_args(argv)
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StationRequestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
