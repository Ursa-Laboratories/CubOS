"""Architecture guardrails for Zoo's CubOS wrapper boundary."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTERS_ROOT = PROJECT_ROOT / "zoo" / "routers"


def test_zoo_routers_do_not_own_gantry_session_primitives() -> None:
    # NOTE: `threading.Lock` is deliberately allowed in gantry.py as of the
    # backend session-safety hardening pass. It guards two Zoo-level,
    # session-*lifecycle* concerns — not CubOS business/motion logic:
    #   1. `_session_create_lock` serializes `_get_or_create_session()` so two
    #      concurrent `/connect` calls can't each create a session and leak an
    #      open serial port.
    #   2. `_run_state_lock` guards the run-in-progress gate (`begin_run` /
    #      `end_run` / `run_active`) that rejects motion requests with 409
    #      while a protocol run holds CubOS's own session lock, instead of
    #      letting them queue and fire as surprise motion after the run ends.
    # Neither lock wraps calls into CubOS's `Gantry`/`GantrySession` internals
    # (`_gantry`, `_serial_lock`, etc.), which remain forbidden below.
    forbidden = (
        "from gantry import Gantry",
        "from gantry.gantry import Gantry",
        "_gantry:",
        "_gantry =",
        "._gantry",
        "_serial_lock",
    )
    offenders: list[str] = []
    for path in sorted(ROUTERS_ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} contains {token!r}")
    assert offenders == []


def test_protocol_router_does_not_import_legacy_run_protocol() -> None:
    text = (ROUTERS_ROOT / "protocol.py").read_text(encoding="utf-8")
    assert "protocol_engine.setup import run_protocol" not in text


def test_data_router_does_not_embed_cubos_schema_sql() -> None:
    text = (ROUTERS_ROOT / "data.py").read_text(encoding="utf-8")
    forbidden = (
        "import sqlite3",
        "SELECT ",
        "INSERT INTO",
        "asmi_measurements",
        "uvvis_measurements",
        "potentiostat_measurements",
    )
    offenders = [token for token in forbidden if token in text]
    assert offenders == []
