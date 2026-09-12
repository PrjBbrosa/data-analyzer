"""Single-call FFT preparation reuse preserves facts and compute identity."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin
from tests.ui.test_analysis_multiview_integration import (
    two_file_win,
    _check_speed_in_both,
)


@pytest.mark.parametrize('scenario', ['cached', 'health', 'blocked', 'missing', 'result_miss'])
def test_fft_facts_reuses_prepared_signal_once_per_source(two_file_win, monkeypatch, scenario):
    win = two_file_win
    win.toolbar._set_mode('fft')
    _check_speed_in_both(win)
    win.files[list(win.files)[1]].fs *= 2
    win.do_fft()
    if scenario == 'health':
        win.files[list(win.files)[0]].data['speed'] = 1.
        win.files[list(win.files)[1]].data.loc[0, 'speed'] = np.nan
    elif scenario == 'blocked':
        original_params = win.inspector.fft_ctx.compute_params()
        monkeypatch.setattr(win.inspector.fft_ctx, 'compute_params',
                            lambda: {**original_params, 'avg_mode': '线性平均'})
        monkeypatch.setattr(win, '_pane_time_range_for', lambda *args: (0., .01))
    elif scenario == 'missing':
        win.files.clear()
    elif scenario == 'result_miss':
        monkeypatch.setattr(win, '_pane_time_range_for', lambda *args: (.2, .5))
    calls = []
    groups = []
    keys = []
    fetch = win._fft_fetch_signal
    make_key = win._fft_analysis_cache_key

    def record_fetch(fid, ch, time_range=None, *, params=None):
        calls.append((fid, ch, time_range, params))
        return fetch(fid, ch, time_range=time_range, params=params)

    def record_key(*args):
        key = make_key(*args)
        keys.append(key)
        return key

    def record_groups(value, warnings):
        groups.append((value, warnings))

    monkeypatch.setattr(win, '_fft_fetch_signal', record_fetch)
    monkeypatch.setattr(win, '_fft_analysis_cache_key', record_key)
    monkeypatch.setattr(win.inspector.fft_ctx, 'set_effective_facts_groups', record_groups)
    monkeypatch.setattr(win.inspector.fft_ctx, 'clear_effective_facts',
                        lambda: groups.append(('clear', ())))
    win._sync_fft_effective_facts()
    assert len(calls) == 2
    assert all(call[3] is not None for call in calls)
    first_groups, first_keys = groups[:], keys[:]
    if scenario in ('missing', 'result_miss'):
        assert first_groups == [('clear', ())]
    else:
        assert len(first_groups[0][0]) == 2
    if scenario == 'health':
        assert first_groups[0][0][0][1].is_constant
        assert first_groups[0][0][1][1].nan_count == 1
        assert first_groups[0][1]  # Different source Fs remains visible.
    if scenario == 'blocked':
        assert all(facts is None and lines for _, facts, lines in first_groups[0][0])

    # The legacy helper path fetches again. Its exact facts and cache keys must
    # agree with the borrowed-input path, without running another calculation.
    effective = win._fft_effective_params_for_source

    def legacy_effective(params, fid, ch, time_range, **kwargs):
        return effective(params, fid, ch, time_range)

    monkeypatch.setattr(win, '_fft_effective_params_for_source', legacy_effective)
    calls.clear()
    groups.clear()
    keys.clear()
    win._sync_fft_effective_facts()
    assert len(calls) == 4
    assert groups == first_groups
    assert keys == first_keys


@pytest.mark.parametrize('nfft', [None, 128])
@pytest.mark.parametrize('signal,fs', [
    (None, None), (np.array([]), 100.), (np.array([1.]), 200.),
    (np.ones(512), 100.), (np.array([np.nan, 1., np.inf]), 200.),
])
def test_prepared_effective_params_preserve_empty_short_health_and_nfft(nfft, signal, fs):
    owner = FFTMixin()
    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        return signal, fs

    owner._fft_fetch_signal = fetch
    params = dict(nfft=nfft, avg_mode='线性平均', t_win_s=1.5)
    legacy = owner._fft_effective_params_for_source(params, 'a', 'speed', None)
    borrowed = owner._fft_effective_params_for_source(
        params, 'a', 'speed', None, prepared=(signal, fs),
    )
    assert borrowed == legacy
    assert owner._fft_compute_cache_params(borrowed) == owner._fft_compute_cache_params(legacy)
    assert calls == [1]


@pytest.mark.parametrize('axis', [
    np.arange(128) / 100.,
    np.cumsum(np.tile([.009, .011], 64)),
    np.array([0., np.nan, .02]),
    np.array([0., np.inf, .02]),
])
def test_prepared_fetch_keeps_time_validation_and_local_selection(axis):
    owner = FFTMixin()
    sig = np.arange(len(axis), dtype=float)
    owner.files = {'a': SimpleNamespace(data=pd.DataFrame({'speed': sig}), time_array=axis, fs=100.)}
    params = dict(nfft=None, avg_mode='单帧')
    before = axis.copy()
    if not np.isfinite(axis).all():
        with pytest.raises(ValueError):
            owner._fft_effective_params_for_source(params, 'a', 'speed', None)
        with pytest.raises(ValueError):
            owner._fft_fetch_signal('a', 'speed', time_range=None, params=params)
    else:
        from mf4_analyzer.ui.main_window.analysis_context import AnalysisContext
        context = AnalysisContext(
            inspector=None, chart_stack=None, analysis_managers={},
            db_reference_store=None, files_provider=lambda: owner.files,
        )
        owner._mask_time_range = context.mask_time_range
        prepared = owner._fft_fetch_signal('a', 'speed', time_range=(.2, .5), params=params)
        expected = sig[(axis >= .2) & (axis <= .5)]
        np.testing.assert_array_equal(prepared[0], expected)
        legacy = owner._fft_effective_params_for_source(params, 'a', 'speed', (.2, .5))
        actual = owner._fft_effective_params_for_source(params, 'a', 'speed', (.2, .5), prepared=prepared)
        assert actual == legacy
    np.testing.assert_array_equal(axis, before)
