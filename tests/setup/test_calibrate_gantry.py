"""Tests for setup/calibrate_gantry.py auto-routing and guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

from setup import calibrate_gantry


def _write_gantry(path: Path, instruments_yaml: str) -> Path:
    path.write_text(
        f"""\
serial_port: /dev/ttyUSB0
cnc:
  homing_strategy: standard
  total_z_range: 100.0
  y_axis_motion: head
working_volume:
  x_min: 0.0
  x_max: 400.0
  y_min: 0.0
  y_max: 300.0
  z_min: 0.0
  z_max: 100.0
instruments:
{instruments_yaml}
""",
        encoding="utf-8",
    )
    return path


def _enter_only(prompt: str) -> str:
    return ""


def test_auto_calibration_routes_single_instrument_to_deck_origin(monkeypatch, tmp_path):
    path = _write_gantry(
        tmp_path / "single.yaml",
        "  asmi:\n    type: asmi\n    vendor: vernier\n",
    )
    out_path = tmp_path / "calibrated.yaml"
    calls: list[tuple] = []
    messages: list[str] = []

    def fake_single(*args, **kwargs):
        calls.append(("single", args, kwargs))
        return "single-result"

    def fake_multi(*args, **kwargs):
        calls.append(("multi", args, kwargs))
        return "multi-result"

    monkeypatch.setattr(calibrate_gantry, "run_calibration", fake_single)
    monkeypatch.setattr(calibrate_gantry, "run_multi_instrument_calibration", fake_multi)

    result = calibrate_gantry.run_auto_calibration(
        path,
        output_gantry_path=out_path,
        output=messages.append,
        input_reader=_enter_only,
    )

    assert result == "single-result"
    assert [call[0] for call in calls] == ["single"]
    assert calls[0][1][0] == path.resolve()
    assert calls[0][2]["instrument_name"] == "asmi"
    assert calls[0][2]["z_reference_mode"] == "block"
    assert calls[0][2]["write_gantry_yaml"] is True
    assert calls[0][2]["output_gantry_path"] == out_path.resolve()
    assert any("Chosen flow:" in message for message in messages)
    assert any("single-instrument deck-origin calibration" in message for message in messages)


def test_auto_calibration_routes_multiple_instruments_to_board_calibration(monkeypatch, tmp_path):
    path = _write_gantry(
        tmp_path / "multi.yaml",
        "  left_probe:\n    type: asmi\n    vendor: vernier\n"
        "  camera:\n    type: uv_curing\n    vendor: excelitas\n",
    )
    out_path = tmp_path / "calibrated.yaml"
    calls: list[tuple] = []
    messages: list[str] = []

    def fake_single(*args, **kwargs):
        calls.append(("single", args, kwargs))
        return "single-result"

    def fake_multi(*args, **kwargs):
        calls.append(("multi", args, kwargs))
        return "multi-result"

    monkeypatch.setattr(calibrate_gantry, "run_calibration", fake_single)
    monkeypatch.setattr(calibrate_gantry, "run_multi_instrument_calibration", fake_multi)

    result = calibrate_gantry.run_auto_calibration(
        path,
        output_gantry_path=out_path,
        output=messages.append,
        input_reader=_enter_only,
    )

    assert result == "multi-result"
    assert [call[0] for call in calls] == ["multi"]
    assert calls[0][1][0] == path.resolve()
    assert any("Detected instruments:    2" in message for message in messages)
    assert any("multi-instrument board calibration" in message for message in messages)


def test_auto_calibration_requires_at_least_one_instrument(tmp_path):
    path = _write_gantry(tmp_path / "empty.yaml", "")

    with pytest.raises(ValueError, match="at least one mounted instrument"):
        calibrate_gantry.run_auto_calibration(path, output_gantry_path=tmp_path / "out.yaml")


def test_auto_calibration_prompts_before_overwriting_input(monkeypatch, tmp_path):
    path = _write_gantry(
        tmp_path / "single.yaml",
        "  asmi:\n    type: asmi\n    vendor: vernier\n",
    )
    calls: list[tuple] = []
    responses = iter(["n"])

    monkeypatch.setattr(
        calibrate_gantry,
        "run_calibration",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        calibrate_gantry.run_auto_calibration(
            path,
            output=lambda message: None,
            input_reader=lambda prompt: next(responses),
        )
    assert calls == []


def test_auto_calibration_overwrites_input_after_confirmation(monkeypatch, tmp_path):
    path = _write_gantry(
        tmp_path / "single.yaml",
        "  asmi:\n    type: asmi\n    vendor: vernier\n",
    )
    calls: list[tuple] = []
    responses = iter(["y", ""])

    def fake_single(*args, **kwargs):
        calls.append((args, kwargs))
        return "single-result"

    monkeypatch.setattr(calibrate_gantry, "run_calibration", fake_single)

    result = calibrate_gantry.run_auto_calibration(
        path,
        output=lambda message: None,
        input_reader=lambda prompt: next(responses),
    )

    assert result == "single-result"
    assert calls[0][1]["output_gantry_path"] == path.resolve()


def test_auto_calibration_does_not_prompt_for_explicit_output(monkeypatch, tmp_path):
    path = _write_gantry(
        tmp_path / "single.yaml",
        "  asmi:\n    type: asmi\n    vendor: vernier\n",
    )
    out_path = tmp_path / "existing.yaml"
    out_path.write_text("existing", encoding="utf-8")
    prompts: list[str] = []

    monkeypatch.setattr(
        calibrate_gantry,
        "run_calibration",
        lambda *args, **kwargs: "single-result",
    )

    result = calibrate_gantry.run_auto_calibration(
        path,
        output_gantry_path=out_path,
        output=lambda message: None,
        input_reader=lambda prompt: prompts.append(prompt) or "",
    )

    assert result == "single-result"
    assert prompts == ["Press ENTER to connect to hardware and start calibration, or Ctrl-C to abort: "]
