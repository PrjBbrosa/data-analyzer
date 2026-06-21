"""Window equivalence tests: verify get_analysis_window matches frozen golden reference.

Golden reference (tests/data/window_golden.npz) was generated from scipy
while scipy was still installed. Tests no longer import scipy.
"""
import os

import numpy as np
import pytest

from mf4_analyzer.signal.fft import get_analysis_window

_GOLDEN = np.load(os.path.join(os.path.dirname(__file__), "data", "window_golden.npz"))
_CASES = ['hanning', 'hann', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
_NS = [2, 3, 4, 8, 16, 31, 64, 256, 1024]


@pytest.mark.parametrize("name", _CASES)
@pytest.mark.parametrize("n", _NS)
def test_window_matches_golden(name, n):
    got = get_analysis_window(name, n)
    ref = _GOLDEN[f"{name}_{n}"]
    assert got.shape == ref.shape
    np.testing.assert_allclose(got, ref, atol=1e-12, rtol=0)


def test_window_n1_is_unit():
    for name in _CASES:
        np.testing.assert_array_equal(get_analysis_window(name, 1), np.ones(1))


def test_unknown_window_raises():
    with pytest.raises(ValueError):
        get_analysis_window('no_such_window', 16)
