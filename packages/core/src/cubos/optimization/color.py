"""Color measurements and perceptual distance for camera-guided optimization."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence


def _triplet(values: Sequence[float], label: str) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} values must be finite")
    return result  # type: ignore[return-value]


def rgb_to_lab(rgb: Sequence[float]) -> tuple[float, float, float]:
    """Convert an sRGB triplet in the 0..255 range to CIE Lab (D65)."""
    red, green, blue = _triplet(rgb, "rgb")
    if any(value < 0 or value > 255 for value in (red, green, blue)):
        raise ValueError("rgb values must be between 0 and 255")

    def linear(value: float) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(red), linear(green), linear(blue))
    x = (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883

    def lab_curve(value: float) -> float:
        delta = 6.0 / 29.0
        return value ** (1.0 / 3.0) if value > delta**3 else value / (3.0 * delta**2) + 4.0 / 29.0

    fx, fy, fz = lab_curve(x), lab_curve(y), lab_curve(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def ciede2000(first: Sequence[float], second: Sequence[float]) -> float:
    """Return the CIEDE2000 perceptual difference between two Lab colors."""
    l1, a1, b1 = _triplet(first, "first Lab color")
    l2, a2, b2 = _triplet(second, "second Lab color")
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2.0
    mean_c7 = mean_c**7
    g = 0.5 * (1.0 - math.sqrt(mean_c7 / (mean_c7 + 25.0**7)))
    a1_prime = (1.0 + g) * a1
    a2_prime = (1.0 + g) * a2
    c1_prime = math.hypot(a1_prime, b1)
    c2_prime = math.hypot(a2_prime, b2)

    def hue(a_value: float, b_value: float) -> float:
        if a_value == 0 and b_value == 0:
            return 0.0
        return math.degrees(math.atan2(b_value, a_value)) % 360.0

    h1_prime = hue(a1_prime, b1)
    h2_prime = hue(a2_prime, b2)
    delta_l = l2 - l1
    delta_c = c2_prime - c1_prime
    if c1_prime * c2_prime == 0:
        delta_h_degrees = 0.0
    else:
        difference = h2_prime - h1_prime
        if difference > 180.0:
            difference -= 360.0
        elif difference < -180.0:
            difference += 360.0
        delta_h_degrees = difference
    delta_h = 2.0 * math.sqrt(c1_prime * c2_prime) * math.sin(
        math.radians(delta_h_degrees / 2.0)
    )
    mean_l = (l1 + l2) / 2.0
    mean_c_prime = (c1_prime + c2_prime) / 2.0
    if c1_prime * c2_prime == 0:
        mean_h = h1_prime + h2_prime
    elif abs(h1_prime - h2_prime) <= 180.0:
        mean_h = (h1_prime + h2_prime) / 2.0
    elif h1_prime + h2_prime < 360.0:
        mean_h = (h1_prime + h2_prime + 360.0) / 2.0
    else:
        mean_h = (h1_prime + h2_prime - 360.0) / 2.0
    t = (
        1.0
        - 0.17 * math.cos(math.radians(mean_h - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * mean_h))
        + 0.32 * math.cos(math.radians(3.0 * mean_h + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * mean_h - 63.0))
    )
    s_l = 1.0 + 0.015 * (mean_l - 50.0) ** 2 / math.sqrt(20.0 + (mean_l - 50.0) ** 2)
    s_c = 1.0 + 0.045 * mean_c_prime
    s_h = 1.0 + 0.015 * mean_c_prime * t
    delta_theta = 30.0 * math.exp(-((mean_h - 275.0) / 25.0) ** 2)
    mean_c_prime7 = mean_c_prime**7
    r_c = 2.0 * math.sqrt(mean_c_prime7 / (mean_c_prime7 + 25.0**7))
    r_t = -r_c * math.sin(math.radians(2.0 * delta_theta))
    l_term = delta_l / s_l
    c_term = delta_c / s_c
    h_term = delta_h / s_h
    return math.sqrt(
        l_term**2 + c_term**2 + h_term**2 + r_t * c_term * h_term
    )


def ciede76(first: Sequence[float], second: Sequence[float]) -> float:
    """Return the Euclidean CIE76 distance between two Lab colors."""
    first_lab = _triplet(first, "first Lab color")
    second_lab = _triplet(second, "second Lab color")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first_lab, second_lab)))


def analyze_color_image(
    image_path: str | Path,
    *,
    roi_fraction: float = 0.5,
    reference_lab: Sequence[float] | None = None,
) -> dict[str, object]:
    """Measure median RGB and Lab in a centered circular image region."""
    if not math.isfinite(roi_fraction) or not 0.0 < roi_fraction <= 1.0:
        raise ValueError("roi_fraction must be greater than 0 and at most 1")
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"color image does not exist: {path}")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Color analysis requires the CubOS camera extra (opencv-python and numpy)."
        ) from exc
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None or frame.ndim != 3 or frame.shape[2] < 3:
        raise ValueError(f"color image is unreadable: {path}")
    height, width = frame.shape[:2]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radius = max(0.5, min(width, height) * roi_fraction / 2.0)
    yy, xx = np.ogrid[:height, :width]
    mask = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
    pixels = frame[mask]
    if not pixels.size:
        raise ValueError("color image ROI contains no pixels")
    blue, green, red = (float(value) for value in np.median(pixels[:, :3], axis=0))
    rgb = (red, green, blue)
    lab = rgb_to_lab(rgb)
    result: dict[str, object] = {
        "image_path": str(path),
        "roi_fraction": roi_fraction,
        "rgb": list(rgb),
        "lab": list(lab),
    }
    if reference_lab is not None:
        target = _triplet(reference_lab, "reference_lab")
        result["reference_lab"] = list(target)
        result["delta_e_00"] = ciede2000(lab, target)
        result["delta_e_76"] = ciede76(lab, target)
    return result
