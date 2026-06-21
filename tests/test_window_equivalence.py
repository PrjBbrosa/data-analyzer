"""Window equivalence tests: verify get_analysis_window matches scipy reference.

Phase 1 (this file): scipy still installed — tests compare against scipy directly.
Phase 2: scipy removed from .venv — tests compare against frozen golden npz.
"""
import numpy as np
import pytest
from scipy.signal import get_window as _scipy_get_window

from mf4_analyzer.signal.fft import get_analysis_window

_CASES = ['hanning', 'hann', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
_NS = [2, 3, 4, 8, 16, 31, 64, 256, 1024]


def _scipy_ref(name, n):
    key = 'hanning' if name == 'hann' else name
    if key == 'kaiser':
        spec = ('kaiser', 14)
    elif key == 'hanning':
        spec = 'hann'
    else:
        spec = key
    return _scipy_get_window(spec, n, fftbins=False).astype(float)


@pytest.mark.parametrize("name", _CASES)
@pytest.mark.parametrize("n", _NS)
def test_window_matches_scipy(name, n):
    got = get_analysis_window(name, n)
    ref = _scipy_ref(name, n)
    assert got.shape == ref.shape
    np.testing.assert_allclose(got, ref, atol=1e-12, rtol=0)


def test_window_n1_is_unit():
    for name in _CASES:
        np.testing.assert_array_equal(get_analysis_window(name, 1), np.ones(1))


def test_unknown_window_raises():
    with pytest.raises(ValueError):
        get_analysis_window('no_such_window', 16)
