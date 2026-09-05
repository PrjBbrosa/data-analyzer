"""Source data remains original across analysis jobs and effective facts."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def source_window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    t = 12 + np.arange(2048) / 100
    t[1::2] += .001
    y = np.sin(np.arange(2048) * .2)
    fd = FileData('/tmp/analysis-isolation.mf4', pd.DataFrame({'time': t, 'sig': y, 'out': 2*y}),
                  ['time', 'sig', 'out'], {'sig': 'V', 'out': 'V'}, 0)
    fd.fs = 100.
    win.files['f1'] = fd
    win._active = 'f1'
    return win, fd, t.copy(), y.copy()


def assert_original(fd, t, y):
    np.testing.assert_array_equal(fd.time_array, t)
    np.testing.assert_array_equal(fd.data['sig'].values, y)
    assert fd.fs == 100
    assert fd._time_source == 'column'
    assert fd.time_axis_provenance is None


def test_fft_range_and_cached_facts_are_analysis_only(source_window):
    win, fd, original_t, original_y = source_window
    params = win.inspector.fft_ctx.compute_params()
    params.update(nfft=256, nfft_mode='fixed')
    rng = (13, 18)
    sig, fs = win._fft_fetch_signal('f1', 'sig', time_range=rng, params=params)
    mask = (original_t >= 13) & (original_t <= 18)
    np.testing.assert_array_equal(sig, original_y[mask])
    params['analysis_time_axis'] = win._fft_time_facts_for_source('f1', 'sig', rng, params)
    result = win._fft_compute_arrays(sig, fs, params)
    assert result.effective.time_axis['scope'] == 'analysis'
    win._publish_analysis_effective_facts(win.inspector.fft_ctx, result.effective, fid='f1', sig=sig)
    assert '仅本次分析' in win.inspector.fft_ctx.lbl_effective_facts.text()
    win._refresh_time_axis_provenance_chips()
    assert win.chart_stack._time_card._time_axis_chip.isHidden()
    assert_original(fd, original_t, original_y)


def test_spectrogram_job_preserves_source_origin_and_cached_facts(source_window):
    win, fd, original_t, original_y = source_window
    params = win.inspector.fft_time_ctx.compute_params()
    params.update(fs=100, nfft=64, nfft_mode='fixed')
    built = win._build_fft_time_job(0, 'f1', 'sig', params, time_range=(13, 18))
    job, ctx = built
    result = job(SimpleNamespace(progress=SimpleNamespace(emit=lambda *_: None), cancelled=lambda: False))
    assert result.times[0] >= 13
    assert result.effective.time_axis['scope'] == 'analysis'
    assert result.effective.time_axis['n_samples'] == int(((original_t >= 13)&(original_t <= 18)).sum())
    prepared, _ = win._fft_time_effective_params_for_source(params, 'f1', 'sig', (13, 18))
    assert win._fft_time_analysis_cache_key('f1', 'sig', prepared, (13, 18)) == win._fft_time_analysis_cache_key('f1', 'sig', ctx['params'], (13, 18))
    assert_original(fd, original_t, original_y)


def test_manual_analysis_time_axis_is_not_exposed_or_restored(source_window):
    """Time repairs are automatic; legacy manual Fs must not survive in a View."""
    win, fd, original_t, original_y = source_window
    for section in ('fft', 'fft_time', 'order'):
        ctx = win._analysis_ctx(section)
        assert not hasattr(ctx, 'btn_rebuild')
        assert 'analysis_time_fs' not in ctx.compute_params()
        # Old projects may carry this retired field. Restoring them must not
        # retain a hidden frequency override in subsequent calculations.
        ctx.apply_params({'analysis_time_fs': 200.0})
        assert 'analysis_time_fs' not in ctx.compute_params()
    assert not hasattr(win.inspector, 'rebuild_time_requested')
    assert_original(fd, original_t, original_y)


def test_order_effective_params_use_local_time_axis_frequency(source_window, monkeypatch):
    """Order cache facts use the same automatic time-axis repair as compute."""
    win, fd, original_t, original_y = source_window
    captured = {}
    monkeypatch.setattr(
        win, '_order_sig_for', lambda *_args, **_kwargs: (fd.time_array, original_y),
    )
    monkeypatch.setattr(
        win, '_order_rpm_for',
        lambda *_args, **_kwargs: np.full(len(original_y), 1200.0),
    )
    monkeypatch.setattr(
        win, '_resolve_order_effective_params',
        lambda params, _rpm, _time: captured.setdefault('params', params),
    )

    result = win._order_effective_params_for_source(
        {'fs': 200.0}, 'f1', 'sig', None, None,
    )

    expected_fs = 1.0 / np.median(np.diff(original_t))
    assert result['fs'] == pytest.approx(expected_fs)
    assert captured['params']['fs'] == pytest.approx(expected_fs)
    assert_original(fd, original_t, original_y)


def test_frf_job_reports_processing_without_touching_either_source_signal(source_window):
    win, fd, original_t, original_y = source_window
    manager = win.analysis_managers['frf']
    state = manager.get(manager.active)
    state.panes[0].input_source = ('f1', 'sig')
    state.panes[0].output_source = ('f1', 'out')
    win.inspector.frf_ctx.spin_t_win.setValue(.5)
    candidate = win._build_frf_candidate(state, 0)
    result = candidate['job'](SimpleNamespace(
        progress=SimpleNamespace(emit=lambda *_: None), cancelled=lambda: False))
    assert result.effective.time_axis['scope'] == 'analysis'
    assert result.effective.max_time_difference == 0
    assert result.effective.time_start == pytest.approx(original_t[0])
    np.testing.assert_array_equal(fd.data['out'].values, 2*original_y)
    assert_original(fd, original_t, original_y)
