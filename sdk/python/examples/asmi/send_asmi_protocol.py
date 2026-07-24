#!/usr/bin/env python3
"""ASMI example sender built on the supported CubOS appliance client."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import csv
import json
import os
from pathlib import Path
import re
from typing import Any

HERE = Path(__file__).resolve().parent

from cubos_client import (
    ProtocolBundle,
    StationClient,
    StationRequestError,
    api_token_from_sources,
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
        health = client.health(timeout=args.health_timeout_s)
        print(json.dumps({"health": health}, indent=2, sort_keys=True))

    response = client.run_protocol(
        bundle,
        run_id=args.experiment_id,
        mock_mode=args.mock_mode,
        timeout=args.timeout_s,
        poll_interval=args.poll_interval_s,
    )
    if args.output_csv:
        write_csv(
            args.output_csv,
            response,
            run_id=args.experiment_id,
            wells=protocol_wells(bundle.protocol_yaml, bundle.deck_config),
        )
        print(f"wrote CSV: {args.output_csv}")
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit local ASMI YAML inputs to the CubOS /api/v1 run API."
    )
    parser.add_argument("--base-url", default="http://cub.local:8742")
    parser.add_argument("--experiment-id", default="asmi-protocol")
    parser.add_argument("--gantry", type=Path, default=HERE / "gantry_config.yaml")
    parser.add_argument("--deck", type=Path, default=HERE / "deck_config.yaml")
    parser.add_argument("--protocol", type=Path, default=HERE / "protocol.yaml")
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.5)
    parser.add_argument("--health-timeout-s", type=float, default=3.0)
    token_file = os.environ.get("CUBOS_API_TOKEN_FILE")
    parser.add_argument("--token-file", type=Path, default=Path(token_file) if token_file else None)
    parser.add_argument("--output-csv", type=Path, default=HERE / "asmi_result.csv")
    parser.add_argument("--mock-mode", action="store_true")
    parser.add_argument("--no-health-check", action="store_true")
    return parser.parse_args(argv)


def write_csv(path: Path, response: Mapping[str, Any], *, run_id: str, wells: list[str]) -> Path:
    rows = csv_rows(response, run_id=run_id, wells=wells)
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    preferred = [
        "run_id",
        "well",
        "sample_index",
        "timestamp_s",
        "z_position_mm",
        "raw_force_n",
        "corrected_force_n",
        "direction",
    ]
    extras = sorted({key for row in rows for key in row if key not in preferred})
    fieldnames = [key for key in preferred if any(key in row for row in rows)] + extras
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def csv_rows(response: Mapping[str, Any], *, run_id: str, wells: list[str]) -> list[dict[str, Any]]:
    payloads = station_payloads(
        response,
        preferred_keys=(
            "measurements",
            "z_positions",
            "raw_forces",
            "corrected_forces",
            "sample_timestamps",
        ),
    )
    rows: list[dict[str, Any]] = []
    for payload_index, payload in enumerate(payloads):
        well = payload_well(payload) or at(wells, payload_index)
        for sample_index, sample in enumerate(asmi_samples(payload)):
            rows.append({"run_id": run_id, "well": well, "sample_index": sample_index, **sample})
    if rows:
        return rows
    return [{"run_id": run_id, "well": ",".join(wells), **flatten(response)}]


def asmi_samples(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []

    measurements = payload.get("measurements")
    if isinstance(measurements, list):
        return [
            {
                "timestamp_s": sample.get("timestamp"),
                "z_position_mm": sample.get("z_mm"),
                "raw_force_n": sample.get("raw_force_n"),
                "corrected_force_n": sample.get("corrected_force_n"),
                "direction": sample.get("direction", "down"),
            }
            for sample in measurements
            if isinstance(sample, Mapping)
        ]

    z_positions = payload.get("z_positions") or []
    raw_forces = payload.get("raw_forces") or []
    corrected_forces = payload.get("corrected_forces") or []
    timestamps = payload.get("sample_timestamps") or []
    directions = payload.get("directions") or []
    count = max(len(z_positions), len(raw_forces), len(corrected_forces), len(timestamps), len(directions))
    return [
        {
            "timestamp_s": at(timestamps, index),
            "z_position_mm": at(z_positions, index),
            "raw_force_n": at(raw_forces, index),
            "corrected_force_n": at(corrected_forces, index),
            "direction": at(directions, index),
        }
        for index in range(count)
    ]


def station_payloads(value: Any, *, preferred_keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            found.extend(station_payloads(item, preferred_keys=preferred_keys))
    elif isinstance(value, Mapping):
        if any(key in value for key in preferred_keys):
            found.append(value)
        else:
            for child in value.values():
                found.extend(station_payloads(child, preferred_keys=preferred_keys))
    return found


def protocol_wells(protocol_yaml: str, deck_yaml: str = "") -> list[str]:
    explicit_wells = [
        match.group(1).upper()
        for match in re.finditer(r"\bposition:\s*plate\.([A-Ha-h][1-9][0-2]?)\b", protocol_yaml)
    ]
    scanned_wells: list[str] = []
    deck_shapes = deck_plate_shapes(deck_yaml)
    for match in re.finditer(r"\bscan:\s*(?P<body>.*?)(?=\n\s*-\s+\w+:|\Z)", protocol_yaml, re.DOTALL):
        body = match.group("body")
        plate_match = re.search(r"\bplate:\s*([A-Za-z_][\w.-]*)\b", body)
        if plate_match:
            scanned_wells.extend(plate_wells(deck_shapes.get(plate_match.group(1), (8, 12))))
    return explicit_wells + scanned_wells


def deck_plate_shapes(deck_yaml: str) -> dict[str, tuple[int, int]]:
    shapes: dict[str, tuple[int, int]] = {}
    labware_match = re.search(r"(?ms)^labware:\s*\n(?P<body>.*)", deck_yaml)
    if not labware_match:
        return shapes
    for match in re.finditer(
        r"(?ms)^  (?P<name>[A-Za-z_][\w.-]*):\s*\n(?P<body>.*?)(?=^  [A-Za-z_][\w.-]*:\s*\n|\Z)",
        labware_match.group("body"),
    ):
        body = match.group("body")
        rows = _int_yaml_field(body, "rows")
        columns = _int_yaml_field(body, "columns")
        if rows is not None and columns is not None:
            shapes[match.group("name")] = (rows, columns)
    return shapes


def _int_yaml_field(block: str, field: str) -> int | None:
    match = re.search(rf"(?m)^\s+{re.escape(field)}:\s*(\d+)\s*$", block)
    return int(match.group(1)) if match else None


def plate_wells(shape: tuple[int, int]) -> list[str]:
    rows, columns = shape
    return [
        f"{chr(ord('A') + row_index)}{column}"
        for row_index in range(rows)
        for column in range(1, columns + 1)
    ]


def payload_well(payload: Mapping[str, Any]) -> str | None:
    for key in ("well", "target_well"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.upper()
    position = payload.get("position")
    if isinstance(position, str):
        match = re.search(r"\bplate\.([A-Ha-h][1-9][0-2]?)\b", position)
        if match:
            return match.group(1).upper()
    return None


def flatten(value: Any, *, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            result.update(flatten(child, prefix=child_prefix))
        return result
    if isinstance(value, list):
        return {prefix: json.dumps(value)}
    return {prefix: value}


def at(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StationRequestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
