"""Tests for the `python -m zoo` monorepo entrypoint."""

from __future__ import annotations

import logging


def test_main_warns_when_compiled_web_assets_are_missing(monkeypatch, tmp_path, caplog):
    from zoo import __main__ as zoo_main

    missing = tmp_path / "web" / "dist"
    monkeypatch.setattr(zoo_main, "FRONTEND_DIST", missing)
    monkeypatch.setattr(
        zoo_main,
        "ZooSettings",
        lambda: type(
            "Settings",
            (),
            {"open_browser": False, "host": "127.0.0.1", "port": 8742},
        )(),
    )
    observed = {}
    monkeypatch.setattr(
        zoo_main.uvicorn,
        "run",
        lambda *args, **kwargs: observed.update({"args": args, "kwargs": kwargs}),
    )

    with caplog.at_level(logging.WARNING):
        zoo_main.main()

    assert "compiled web assets were not found" in caplog.text
    assert observed["args"] == ("zoo.app:create_app",)
    assert observed["kwargs"]["factory"] is True
