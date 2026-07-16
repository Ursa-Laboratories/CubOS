"""Deterministic YAML output helpers for the PANDA-BEAR importer.

No timestamps, sorted keys, stable float formatting -- two runs against the
same snapshot + resolutions must produce byte-identical files.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )


def render_with_header(header_lines: list[str], data: dict) -> str:
    header = "".join((f"# {line}\n" if line else "#\n") for line in header_lines)
    return header + "\n" + dump_yaml(data)


def write_yaml_with_header(path: Path, header_lines: list[str], data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_with_header(header_lines, data), encoding="utf-8")
