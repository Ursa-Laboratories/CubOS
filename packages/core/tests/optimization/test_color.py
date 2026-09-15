import pytest

from cubos.optimization import ciede2000, ciede76, rgb_to_lab


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ],
)
def test_ciede2000_matches_reference_pairs(first, second, expected):
    assert ciede2000(first, second) == pytest.approx(expected, abs=0.0001)


def test_rgb_to_lab_matches_d65_black_white_and_red():
    assert rgb_to_lab((0, 0, 0)) == pytest.approx((0, 0, 0), abs=0.001)
    assert rgb_to_lab((255, 255, 255)) == pytest.approx((100, 0, 0), abs=0.02)
    assert rgb_to_lab((255, 0, 0)) == pytest.approx(
        (53.2408, 80.0925, 67.2032), abs=0.02
    )


def test_ciede76_is_euclidean_lab_distance():
    assert ciede76((10, 20, 30), (13, 24, 30)) == 5


def test_color_inputs_are_strictly_bounded():
    with pytest.raises(ValueError, match="between 0 and 255"):
        rgb_to_lab((256, 0, 0))
    with pytest.raises(ValueError, match="exactly three"):
        ciede2000((1, 2), (1, 2, 3))
