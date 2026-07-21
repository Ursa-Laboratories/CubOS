"""Optional ``--tools-json`` override for the documented default tool offsets.

Accepts the same shape as PANDA-BEAR's own
``src/panda_lib/hardware/grbl_cnc_mill/tools.json``: a list of
``{"name": ..., "x": ..., "y": ..., "z": ...}`` objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .constants import ToolOffset


class ToolsJsonError(ValueError):
    """Raised for a malformed tools.json override file."""


def load_tool_offsets(path: str | Path) -> Mapping[str, ToolOffset]:
    resolved = Path(path)
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolsJsonError(f"Cannot read tools.json override at {resolved}: {exc}") from exc
    if not isinstance(raw, list):
        raise ToolsJsonError(f"tools.json override at {resolved} must be a list of tool entries.")

    offsets: dict[str, ToolOffset] = {}
    for entry in raw:
        if not isinstance(entry, dict) or not {"name", "x", "y", "z"} <= set(entry):
            raise ToolsJsonError(
                f"tools.json entry {entry!r} must have `name`, `x`, `y`, `z`."
            )
        offsets[str(entry["name"])] = ToolOffset(
            x=float(entry["x"]), y=float(entry["y"]), z=float(entry["z"]),
        )
    return offsets
