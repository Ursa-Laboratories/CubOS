"""Tests for the tip_scan_check offline classifier CLI."""

from __future__ import annotations

import pytest

from cubos.deck.loader import load_deck_from_yaml_safe
from cubos.tools.tip_scan_check import main
from cubos.vision.tip_detection import project_tips_to_pixels

from .vision.test_tip_detection import write_gray_png

IMAGE_SIZE = 200

DECK_YAML = """\
labware:
  tips:
    load_name: ursa_tip_rack
    name: tips
    tip_length: 59.3
    pickup_z: 64.7
    drop_z: 34.0
    calibration:
      a1: {x: 210.0, y: 230.0}
      a2: {x: 218.5, y: 230.0}

  vial:
    type: vial
    name: vial
    model_name: v
    height: 40.0
    diameter: 15.0
    location: {x: 40.0, y: 5.0, z: 20.0}
    capacity_ul: 500.0
    working_volume_ul: 400.0
"""


@pytest.fixture()
def deck_yaml(tmp_path):
    path = tmp_path / "deck.yaml"
    path.write_text(DECK_YAML, encoding="utf-8")
    return path


@pytest.fixture()
def rack_image(tmp_path, deck_yaml):
    """Render the loaded rack's geometry with every tip present except A2."""
    rack = load_deck_from_yaml_safe(deck_yaml).labware["tips"]
    center = (
        sum(tip.x for tip in rack.tips.values()) / len(rack.tips),
        sum(tip.y for tip in rack.tips.values()) / len(rack.tips),
    )
    centers = project_tips_to_pixels(
        {tip_id: (tip.x, tip.y) for tip_id, tip in rack.tips.items()},
        center, IMAGE_SIZE, IMAGE_SIZE, 1.0,
    )
    rows = [[10] * IMAGE_SIZE for _ in range(IMAGE_SIZE)]
    for tip_id, (px, py) in centers.items():
        if tip_id == "A2":
            continue
        for y in range(round(py) - 3, round(py) + 4):
            for x in range(round(px) - 3, round(px) + 4):
                rows[y][x] = 240
    return write_gray_png(tmp_path / "scan.png", rows)


def _run(image, deck, *extra):
    return main([
        str(image), "--deck", str(deck), "--rack", "tips",
        "--mm-per-px", "1.0", "--patch-radius-mm", "2.0", *extra,
    ])


def test_prints_scores_and_counts(deck_yaml, rack_image, capsys):
    assert _run(rack_image, deck_yaml) == 0
    out = capsys.readouterr().out
    assert "A1" in out and "present" in out
    assert "29 present, 1 absent, 0 uncertain" in out


def test_explicit_center_shifts_projection(deck_yaml, rack_image, capsys):
    assert _run(rack_image, deck_yaml, "--center", "150.0", "230.0") == 0
    out = capsys.readouterr().out
    assert out.strip().endswith("(patch_radius_px=2)")
    assert "29 present" not in out


def test_unknown_rack_errors(deck_yaml, rack_image, capsys):
    code = main([
        str(rack_image), "--deck", str(deck_yaml), "--rack", "ghost",
        "--mm-per-px", "1.0",
    ])
    assert code == 1
    assert "not on the deck" in capsys.readouterr().err


def test_non_tip_rack_errors(deck_yaml, rack_image, capsys):
    code = main([
        str(rack_image), "--deck", str(deck_yaml), "--rack", "vial",
        "--mm-per-px", "1.0",
    ])
    assert code == 1
    assert "not a TipRack" in capsys.readouterr().err


def test_unreadable_image_errors(deck_yaml, tmp_path, capsys):
    bogus = tmp_path / "bogus.png"
    bogus.write_bytes(b"nope")
    assert _run(bogus, deck_yaml) == 1
    assert "PNG" in capsys.readouterr().err


def test_bad_thresholds_error(deck_yaml, rack_image, capsys):
    code = _run(
        rack_image, deck_yaml,
        "--present-threshold", "0.2", "--absent-threshold", "0.5",
    )
    assert code == 1
    assert "threshold" in capsys.readouterr().err
