"""Tip-rack presence classification from a top-down camera frame.

Pure stdlib on purpose: the classifier must run (and be tested) without
OpenCV/numpy installed, mirroring ``camera.placeholder``'s stdlib PNG
writer. A loaded tip reads as a bright region against the dark empty
socket, so per-slot classification is a mean-intensity score over a small
patch centered on the slot's projected pixel location, with an uncertain
band between the absent and present thresholds. Uncertain slots are the
caller's problem — CubOS treats them fail-safe as not pickable.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 4: 2, 6: 4}

DEFAULT_PRESENT_THRESHOLD = 0.55
DEFAULT_ABSENT_THRESHOLD = 0.35


def read_png_grayscale(path: str | Path) -> list[list[int]]:
    """Read an 8-bit non-interlaced PNG as rows of 0-255 luma values.

    Supports grayscale, grayscale+alpha, RGB, and RGBA color types (alpha is
    ignored; RGB converts by Rec. 601 luma), which covers everything the
    camera vendors and the offline placeholder writer emit.
    """
    data = Path(path).read_bytes()
    if data[:8] != _PNG_SIGNATURE:
        raise ValueError(f"{path} is not a PNG file.")

    header: Optional[tuple[int, int, int]] = None
    idat = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        tag = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if bit_depth != 8:
                raise ValueError(
                    f"{path}: unsupported PNG bit depth {bit_depth}; only 8 "
                    "is supported."
                )
            if color_type not in _CHANNELS_BY_COLOR_TYPE:
                raise ValueError(
                    f"{path}: unsupported PNG color type {color_type}."
                )
            if interlace != 0:
                raise ValueError(f"{path}: interlaced PNGs are not supported.")
            header = (width, height, _CHANNELS_BY_COLOR_TYPE[color_type])
        elif tag == b"IDAT":
            idat.extend(payload)
        elif tag == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path}: PNG has no IHDR chunk.")

    width, height, channels = header
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    if len(raw) < height * (stride + 1):
        raise ValueError(f"{path}: PNG pixel data is truncated.")

    rows: list[list[int]] = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        _unfilter_scanline(filter_type, line, previous, channels, path)
        previous = line
        if channels == 1:
            rows.append(list(line))
        elif channels == 2:
            rows.append([line[2 * x] for x in range(width)])
        else:
            rows.append([
                (299 * line[channels * x]
                 + 587 * line[channels * x + 1]
                 + 114 * line[channels * x + 2]) // 1000
                for x in range(width)
            ])
    return rows


def _unfilter_scanline(
    filter_type: int,
    line: bytearray,
    previous: bytearray,
    bpp: int,
    path: str | Path,
) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(bpp, len(line)):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif filter_type == 2:
        for i in range(len(line)):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif filter_type == 3:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + (left + previous[i]) // 2) & 0xFF
    elif filter_type == 4:
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
    else:
        raise ValueError(f"{path}: unknown PNG filter type {filter_type}.")


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def project_tips_to_pixels(
    tips_mm: Mapping[str, tuple[float, float]],
    center_mm: tuple[float, float],
    image_width: int,
    image_height: int,
    mm_per_px: float,
    *,
    flip_x: bool = False,
    flip_y: bool = True,
) -> dict[str, tuple[float, float]]:
    """Project deck-frame tip XY coordinates onto image pixel coordinates.

    The camera's optical center is assumed to sit over *center_mm* at the
    image center. ``flip_y`` defaults to True because deck +Y (away from the
    operator) maps to image up (decreasing row index) for a camera mounted
    upright over the deck; both flips are per-rig calibration choices.
    """
    if not isinstance(mm_per_px, (int, float)) or mm_per_px <= 0:
        raise ValueError(f"mm_per_px must be a positive number, got {mm_per_px!r}.")
    center_px_x = (image_width - 1) / 2
    center_px_y = (image_height - 1) / 2
    projected: dict[str, tuple[float, float]] = {}
    for slot_id, (x_mm, y_mm) in tips_mm.items():
        dx = (x_mm - center_mm[0]) / mm_per_px
        dy = (y_mm - center_mm[1]) / mm_per_px
        projected[slot_id] = (
            center_px_x + (-dx if flip_x else dx),
            center_px_y + (-dy if flip_y else dy),
        )
    return projected


def tip_patch_scores(
    image: list[list[int]],
    centers: Mapping[str, tuple[float, float]],
    patch_radius_px: int,
) -> dict[str, Optional[float]]:
    """Return each slot's normalized (0-1) mean patch intensity.

    A slot whose patch is not fully inside the frame scores ``None`` — the
    camera did not actually see it.
    """
    if patch_radius_px < 1:
        raise ValueError(
            f"patch_radius_px must be >= 1, got {patch_radius_px!r}."
        )
    height = len(image)
    width = len(image[0]) if height else 0
    scores: dict[str, Optional[float]] = {}
    for slot_id, (px, py) in centers.items():
        x0 = int(round(px)) - patch_radius_px
        y0 = int(round(py)) - patch_radius_px
        x1 = int(round(px)) + patch_radius_px
        y1 = int(round(py)) + patch_radius_px
        if x0 < 0 or y0 < 0 or x1 >= width or y1 >= height:
            scores[slot_id] = None
            continue
        total = 0
        for y in range(y0, y1 + 1):
            row = image[y]
            for x in range(x0, x1 + 1):
                total += row[x]
        count = (2 * patch_radius_px + 1) ** 2
        scores[slot_id] = total / count / 255.0
    return scores


def classify_tip_rack(
    image: list[list[int]],
    centers: Mapping[str, tuple[float, float]],
    *,
    patch_radius_px: int,
    present_threshold: float = DEFAULT_PRESENT_THRESHOLD,
    absent_threshold: float = DEFAULT_ABSENT_THRESHOLD,
) -> dict[str, Optional[bool]]:
    """Classify per-slot tip presence: True/False, or None when uncertain.

    ``None`` covers both an ambiguous score (between the thresholds) and a
    slot outside the frame; callers must treat it fail-safe as not pickable.
    """
    if not (0.0 <= absent_threshold <= present_threshold <= 1.0):
        raise ValueError(
            "thresholds must satisfy 0 <= absent_threshold <= "
            f"present_threshold <= 1, got absent={absent_threshold!r} "
            f"present={present_threshold!r}."
        )
    result: dict[str, Optional[bool]] = {}
    for slot_id, score in tip_patch_scores(
        image, centers, patch_radius_px,
    ).items():
        if score is None:
            result[slot_id] = None
        elif score >= present_threshold:
            result[slot_id] = True
        elif score <= absent_threshold:
            result[slot_id] = False
        else:
            result[slot_id] = None
    return result
