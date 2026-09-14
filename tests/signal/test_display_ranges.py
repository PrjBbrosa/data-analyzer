import numpy as np
import pytest

from mf4_analyzer.signal.display_ranges import line_amplitude_limits, visible_line_values


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_limits_preserve_linear_units_and_deep_db(dtype):
    values = np.array([0, 100, 200, 900, 1000], dtype=dtype)
    assert line_amplitude_limits(values, amplitude_mode='amplitude') == (-50, 1050)
    assert line_amplitude_limits(values * 2, amplitude_mode='amplitude') == (-100, 2100)
    assert line_amplitude_limits([-300, -40, -20], amplitude_mode='amplitude_db') == (-314, -6)
    assert line_amplitude_limits(visible_line_values(np.arange(5), values, (3, 4)), amplitude_mode='amplitude') == (895, 1005)


@pytest.mark.parametrize('values,mode,expected', [([], 'amplitude', None), ([np.nan, np.inf], 'amplitude_db', None), ([0], 'amplitude', (-1, 1)), ([-20], 'amplitude_db', (-21, -19)), ([-20], 'amplitude', (-21, -19))])
def test_empty_and_constant(values, mode, expected):
    assert line_amplitude_limits(values, amplitude_mode=mode) == expected


def test_visible_intersections_and_breaks():
    assert sorted(visible_line_values([0, 10], [0, 100], (2, 4))) == [20, 40]
    assert visible_line_values([0, 5, 10], [0, np.nan, 100], (2, 4)).size == 0
    assert visible_line_values([0, 10], [0, 100], (2, 4), valid_mask=[True, False]).size == 0
    assert line_amplitude_limits([-6000, -300, 0], amplitude_mode='amplitude_db', valid_mask=[False, True, True]) == (-315, 15)


@pytest.mark.parametrize('x,y,mask', [([0], [0, 1], None), ([[0]], [[1]], None), ([0], [1], [True, False])])
def test_shape_errors(x, y, mask):
    with pytest.raises(ValueError):
        visible_line_values(x, y, (0, 1), valid_mask=mask)


def test_amplitude_shape_errors():
    with pytest.raises(ValueError):
        line_amplitude_limits([[1]], amplitude_mode='amplitude')
    with pytest.raises(ValueError):
        line_amplitude_limits([1], amplitude_mode='amplitude', valid_mask=[True, False])


def test_extreme_finite_limits_remain_finite_and_cover_data():
    limits = line_amplitude_limits([-1e308, 1e308], amplitude_mode='amplitude')
    assert limits == pytest.approx((-1.1e308, 1.1e308))
    largest = np.finfo(float).max
    for values in ([largest], [-largest], [largest / 2, largest], [-largest, -largest / 2]):
        lo, hi = line_amplitude_limits(values, amplitude_mode='amplitude')
        assert np.isfinite(lo) and np.isfinite(hi)
        assert lo <= min(values) <= max(values) <= hi
        assert lo < hi
