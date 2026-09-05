"""Analysis time preparation must never alter the imported time axis."""
import numpy as np
import pytest

from mf4_analyzer.analysis_time_axis import prepare_analysis_time_axis


def test_rebuild_preserves_source_and_absolute_selection_origin():
    original = np.array([12.0, 12.009, 12.02, 12.029, 12.04])
    before = original.copy()
    axis, fs, facts = prepare_analysis_time_axis(original, 100.0)
    np.testing.assert_array_equal(original, before)
    np.testing.assert_allclose(axis, 12 + np.arange(5) / 100)
    assert not np.shares_memory(axis, original)
    assert fs == pytest.approx(100)
    assert facts['scope'] == 'analysis'
    assert facts['reason'] == 'auto_nonuniform'
    assert facts['relative_jitter'] == pytest.approx(.1)


@pytest.mark.parametrize('axis', [[], [17.0], [17, 17.01, 17.02]])
def test_short_or_uniform_axis_is_not_rebuilt(axis):
    result, fs, facts = prepare_analysis_time_axis(axis, 100)
    np.testing.assert_array_equal(result, axis)
    assert fs == 100
    assert facts is None


@pytest.mark.parametrize('axis', [[0, np.nan], [0, np.inf], [[0, 1]]])
def test_invalid_time_rejected_without_hiding_it(axis):
    with pytest.raises(ValueError):
        prepare_analysis_time_axis(axis, 100)


def test_explicit_rate_is_analysis_only_and_keeps_origin():
    axis, fs, facts = prepare_analysis_time_axis([4, 4.01, 4.02], 100, target_fs=200)
    np.testing.assert_allclose(axis, [4, 4.005, 4.01])
    assert fs == 200
    assert facts['reason'] == 'manual'


def test_neutral_preparation_imports_without_gui():
    import subprocess
    import sys
    subprocess.run([
        sys.executable, '-c',
        'import sys; import mf4_analyzer.analysis_time_axis; '
        'assert not any(k.startswith(("PyQt5", "mf4_analyzer.ui")) for k in sys.modules)',
    ], check=True)


def test_nonmonotonic_rebuild_keeps_length_origin_and_original_values():
    original = np.array([8., 8.01, 8.005, 8.02])
    before = original.copy()
    axis, fs, facts = prepare_analysis_time_axis(original, 100)
    assert len(axis) == len(original)
    assert axis[0] == original[0]
    assert np.all(np.diff(axis) > 0)
    assert facts['reason'] == 'auto_nonuniform'
    np.testing.assert_array_equal(original, before)
