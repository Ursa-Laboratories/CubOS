"""Offline tip-rack scan classifier check.

Tune ``scan_tip_rack`` thresholds and orientation against a saved frame
without a protocol run: point it at a captured PNG plus the deck YAML that
defines the rack, and it prints every slot's patch score and classification.

    python -m cubos.tools.tip_scan_check frame.png \\
        --deck deck.yaml --rack tips --mm-per-px 0.12
"""

from __future__ import annotations

import argparse
import sys

from cubos.deck.labware.tip_rack import TipRack
from cubos.deck.loader import load_deck_from_yaml_safe
from cubos.vision.tip_detection import (
    DEFAULT_ABSENT_THRESHOLD,
    DEFAULT_PRESENT_THRESHOLD,
    classify_tip_rack,
    project_tips_to_pixels,
    read_png_grayscale,
    tip_patch_scores,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cubos.tools.tip_scan_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="Captured top-down PNG of the rack.")
    parser.add_argument("--deck", required=True, help="Deck YAML path.")
    parser.add_argument("--rack", required=True, help="Deck key of the TipRack.")
    parser.add_argument("--mm-per-px", type=float, required=True)
    parser.add_argument(
        "--center", type=float, nargs=2, metavar=("X", "Y"),
        help="Deck XY the camera was centered over (default: tip-grid mean).",
    )
    parser.add_argument("--patch-radius-mm", type=float, default=1.0)
    parser.add_argument(
        "--present-threshold", type=float, default=DEFAULT_PRESENT_THRESHOLD,
    )
    parser.add_argument(
        "--absent-threshold", type=float, default=DEFAULT_ABSENT_THRESHOLD,
    )
    parser.add_argument("--flip-x", action="store_true")
    parser.add_argument(
        "--no-flip-y", dest="flip_y", action="store_false",
        help="Disable the default deck-Y-to-image-up flip.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    deck = load_deck_from_yaml_safe(args.deck)
    try:
        rack = deck.resolve_labware(args.rack)
    except KeyError:
        print(f"ERROR: rack {args.rack!r} is not on the deck.", file=sys.stderr)
        return 1
    if not isinstance(rack, TipRack):
        print(
            f"ERROR: {args.rack!r} is a {type(rack).__name__}, not a TipRack.",
            file=sys.stderr,
        )
        return 1

    try:
        image = read_png_grayscale(args.image)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.center is not None:
        center = (args.center[0], args.center[1])
    else:
        center = (
            sum(tip.x for tip in rack.tips.values()) / len(rack.tips),
            sum(tip.y for tip in rack.tips.values()) / len(rack.tips),
        )
    centers = project_tips_to_pixels(
        {tip_id: (tip.x, tip.y) for tip_id, tip in rack.tips.items()},
        center,
        len(image[0]) if image else 0,
        len(image),
        args.mm_per_px,
        flip_x=args.flip_x,
        flip_y=args.flip_y,
    )
    patch_radius_px = max(1, round(args.patch_radius_mm / args.mm_per_px))
    try:
        scores = tip_patch_scores(image, centers, patch_radius_px)
        presence = classify_tip_rack(
            image, centers,
            patch_radius_px=patch_radius_px,
            present_threshold=args.present_threshold,
            absent_threshold=args.absent_threshold,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    counts = {"present": 0, "absent": 0, "uncertain": 0}
    print(f"{'slot':<6} {'px':>7} {'py':>7} {'score':>6}  status")
    for slot_id in rack.tips:
        px, py = centers[slot_id]
        score = scores[slot_id]
        value = presence[slot_id]
        status = (
            "present" if value is True
            else "absent" if value is False
            else "uncertain"
        )
        counts[status] += 1
        score_text = f"{score:.3f}" if score is not None else "  n/a"
        print(f"{slot_id:<6} {px:>7.1f} {py:>7.1f} {score_text:>6}  {status}")
    print(
        f"{counts['present']} present, {counts['absent']} absent, "
        f"{counts['uncertain']} uncertain "
        f"(patch_radius_px={patch_radius_px})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
