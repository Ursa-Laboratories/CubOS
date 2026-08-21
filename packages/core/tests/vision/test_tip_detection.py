"""Tests for the stdlib tip-rack scan classifier."""

from __future__ import annotations

import struct
import zlib

import pytest

from cubos.vision.tip_detection import (
    _paeth,
    classify_tip_rack,
    project_tips_to_pixels,
    read_png_grayscale,
    tip_patch_scores,
)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _filter_scanline(
    filter_type: int, raw: bytes, previous: bytes, bpp: int,
) -> bytes:
    out = bytearray([filter_type])
    for i, value in enumerate(raw):
        left = raw[i - bpp] if i >= bpp else 0
        up = previous[i]
        up_left = previous[i - bpp] if i >= bpp else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        else:
            predictor = _paeth(left, up, up_left)
        out.append((value - predictor) & 0xFF)
    return bytes(out)


def write_png(
    path,
    scanlines: list[bytes],
    *,
    width: int,
    color_type: int = 0,
    filter_type: int = 0,
    bit_depth: int = 8,
    interlace: int = 0,
) -> str:
    """Write *scanlines* (raw channel bytes per row) as a PNG file."""
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    previous = bytes(stride)
    filtered = bytearray()
    for raw in scanlines:
        assert len(raw) == stride
        filtered += _filter_scanline(filter_type, raw, previous, channels)
        previous = raw
    ihdr = struct.pack(
        ">IIBBBBB", width, len(scanlines), bit_depth, color_type, 0, 0,
        interlace,
    )
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(filtered)))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)
    return str(path)


def write_gray_png(path, rows: list[list[int]], *, filter_type: int = 0) -> str:
    return write_png(
        path,
        [bytes(row) for row in rows],
        width=len(rows[0]),
        filter_type=filter_type,
    )


class TestReadPngGrayscale:

    GRADIENT = [[(x * 7 + y * 13) % 256 for x in range(9)] for y in range(6)]

    def test_grayscale_filter_none_roundtrip(self, tmp_path):
        path = write_gray_png(tmp_path / "g.png", self.GRADIENT)
        assert read_png_grayscale(path) == self.GRADIENT

    @pytest.mark.parametrize("filter_type", [1, 2, 3, 4])
    def test_all_filter_types_reconstruct_identically(
        self, tmp_path, filter_type,
    ):
        path = write_gray_png(
            tmp_path / f"f{filter_type}.png", self.GRADIENT,
            filter_type=filter_type,
        )
        assert read_png_grayscale(path) == self.GRADIENT

    def test_rgb_converts_by_luma(self, tmp_path):
        scanline = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 40, 40, 40])
        path = write_png(
            tmp_path / "rgb.png", [scanline], width=4, color_type=2,
        )
        assert read_png_grayscale(path) == [[
            299 * 255 // 1000, 587 * 255 // 1000, 114 * 255 // 1000, 40,
        ]]

    def test_rgba_ignores_alpha(self, tmp_path):
        scanline = bytes([90, 90, 90, 0, 200, 200, 200, 255])
        path = write_png(
            tmp_path / "rgba.png", [scanline], width=2, color_type=6,
        )
        assert read_png_grayscale(path) == [[90, 200]]

    def test_gray_alpha_ignores_alpha(self, tmp_path):
        scanline = bytes([17, 0, 250, 128])
        path = write_png(
            tmp_path / "ga.png", [scanline], width=2, color_type=4,
        )
        assert read_png_grayscale(path) == [[17, 250]]

    def test_placeholder_png_reads(self, tmp_path):
        from cubos.instruments.camera.placeholder import write_placeholder_png

        path = write_placeholder_png(tmp_path / "p.png", width=20, height=12)
        rows = read_png_grayscale(path)
        assert len(rows) == 12 and len(rows[0]) == 20
        assert rows[0][0] == 255 and rows[6][10] == 96

    def test_non_png_raises(self, tmp_path):
        path = tmp_path / "not.png"
        path.write_bytes(b"definitely not a png")
        with pytest.raises(ValueError, match="not a PNG"):
            read_png_grayscale(path)

    def test_unsupported_bit_depth_raises(self, tmp_path):
        path = tmp_path / "deep.png"
        ihdr = struct.pack(">IIBBBBB", 2, 1, 16, 0, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x01\x00\x02"))
            + _png_chunk(b"IEND", b"")
        )
        with pytest.raises(ValueError, match="bit depth"):
            read_png_grayscale(path)

    def test_interlaced_raises(self, tmp_path):
        path = tmp_path / "adam7.png"
        write_png(path, [bytes([1, 2])], width=2, interlace=1)
        with pytest.raises(ValueError, match="interlaced"):
            read_png_grayscale(path)

    def test_unsupported_color_type_raises(self, tmp_path):
        path = tmp_path / "palette.png"
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"\x00\x01\x02"))
            + _png_chunk(b"IEND", b"")
        )
        with pytest.raises(ValueError, match="color type"):
            read_png_grayscale(path)

    def test_missing_ihdr_raises(self, tmp_path):
        path = tmp_path / "hollow.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IEND", b""))
        with pytest.raises(ValueError, match="IHDR"):
            read_png_grayscale(path)

    def test_truncated_pixel_data_raises(self, tmp_path):
        path = tmp_path / "short.png"
        ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 0, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"\x00\x01\x02"))
            + _png_chunk(b"IEND", b"")
        )
        with pytest.raises(ValueError, match="truncated"):
            read_png_grayscale(path)

    def test_unknown_filter_type_raises(self, tmp_path):
        path = tmp_path / "weird.png"
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes([9, 1, 2])))
            + _png_chunk(b"IEND", b"")
        )
        with pytest.raises(ValueError, match="filter type"):
            read_png_grayscale(path)


class TestProjectTipsToPixels:

    def test_center_tip_lands_on_image_center(self):
        projected = project_tips_to_pixels(
            {"A1": (50.0, 60.0)}, (50.0, 60.0), 101, 81, 0.5,
        )
        assert projected["A1"] == (50.0, 40.0)

    def test_default_orientation_flips_y_only(self):
        projected = project_tips_to_pixels(
            {"A1": (52.0, 63.0)}, (50.0, 60.0), 101, 81, 0.5,
        )
        assert projected["A1"] == (54.0, 34.0)

    def test_flip_x(self):
        projected = project_tips_to_pixels(
            {"A1": (52.0, 60.0)}, (50.0, 60.0), 101, 81, 0.5,
            flip_x=True,
        )
        assert projected["A1"] == (46.0, 40.0)

    def test_no_flip_y(self):
        projected = project_tips_to_pixels(
            {"A1": (50.0, 63.0)}, (50.0, 60.0), 101, 81, 0.5,
            flip_y=False,
        )
        assert projected["A1"] == (50.0, 46.0)

    @pytest.mark.parametrize("mm_per_px", [0, -0.5, "x"])
    def test_invalid_scale_raises(self, mm_per_px):
        with pytest.raises(ValueError, match="mm_per_px"):
            project_tips_to_pixels(
                {"A1": (0.0, 0.0)}, (0.0, 0.0), 10, 10, mm_per_px,
            )


class TestClassifyTipRack:

    IMAGE = [[10] * 30 for _ in range(30)]

    @classmethod
    def setup_class(cls):
        for y in range(3, 8):
            for x in range(3, 8):
                cls.IMAGE[y][x] = 240
        for y in range(12, 17):
            for x in range(12, 17):
                cls.IMAGE[y][x] = 120

    def test_present_absent_uncertain(self):
        result = classify_tip_rack(
            self.IMAGE,
            {
                "bright": (5.0, 5.0),
                "dark": (25.0, 25.0),
                "mid": (14.0, 14.0),
            },
            patch_radius_px=2,
        )
        assert result == {"bright": True, "dark": False, "mid": None}

    def test_out_of_frame_slot_is_uncertain(self):
        result = classify_tip_rack(
            self.IMAGE, {"edge": (0.0, 0.0), "far": (99.0, 5.0)},
            patch_radius_px=2,
        )
        assert result == {"edge": None, "far": None}

    def test_scores_reflect_patch_means(self):
        scores = tip_patch_scores(
            self.IMAGE, {"bright": (5.0, 5.0), "dark": (25.0, 25.0)}, 2,
        )
        assert scores["bright"] == pytest.approx(240 / 255)
        assert scores["dark"] == pytest.approx(10 / 255)

    def test_invalid_patch_radius_raises(self):
        with pytest.raises(ValueError, match="patch_radius_px"):
            tip_patch_scores(self.IMAGE, {"a": (5.0, 5.0)}, 0)

    @pytest.mark.parametrize(
        "present,absent", [(0.4, 0.6), (1.5, 0.2), (0.6, -0.1)],
    )
    def test_invalid_thresholds_raise(self, present, absent):
        with pytest.raises(ValueError, match="threshold"):
            classify_tip_rack(
                self.IMAGE, {"a": (5.0, 5.0)}, patch_radius_px=2,
                present_threshold=present, absent_threshold=absent,
            )


def test_paeth_prefers_up_left_on_tie_break():
    assert _paeth(3, 10, 7) == 7
