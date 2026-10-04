"""Source data remains original across analysis jobs and effective facts."""
import threading
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


def test_obsolete_fft_time_completion_does_not_render_current_request(
    source_window, monkeypatch,
):
    """A 0.5 s job must not paint once the live request is already 1.0 s.

    ``tests/ui/test_fft_time_coordinator.py`` drops a finished job only after
    ``request_batch(replace=True)`` bumps the coordinator generation. Editing
    the window without submitting a new batch never enters that gate. Admission
    belongs to ``MainWindow._on_fft_time_render_requested``.
    """
    win, fd, original_t, original_y = source_window
    state = win.analysis_managers['fft_time'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    win.toolbar._set_mode('fft_time')
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': None, 'nfft_mode': 'auto', 't_win_s': 0.5})
    state.params = ctx.current_params()
    built = win._build_fft_time_job(
        0, 'f1', 'sig', ctx.compute_params(), time_range=None,
    )
    assert built is not None
    job, old = built
    old['view_id'] = state.view_id
    result = job(SimpleNamespace(
        progress=SimpleNamespace(emit=lambda *_args: None),
        cancelled=lambda: False,
    ))
    ctx.apply_params({'nfft': None, 'nfft_mode': 'auto', 't_win_s': 1.0})
    win._on_analysis_compute_params_changed('fft_time', ctx.compute_params())
    assert old['params']['t_win_s'] != ctx.compute_params()['t_win_s']
    assert_original(fd, original_t, original_y)
    rendered = []
    monkeypatch.setattr(
        win, '_render_fft_time_on',
        lambda *args, **kwargs: rendered.append(args),
    )
    win._on_fft_time_render_requested(old, result, False)
    assert not rendered, 'obsolete compute completion must not render as current'


def _finish_fft_time_job(win, pane_idx=0, time_range=None):
    ctx = win.inspector.fft_time_ctx
    built = win._build_fft_time_job(
        pane_idx, 'f1', 'sig', ctx.compute_params(), time_range=time_range,
    )
    assert built is not None
    job, old = built
    state = win.analysis_managers['fft_time'].get(
        win.analysis_managers['fft_time'].active
    )
    old['view_id'] = state.view_id
    old['pane_idx'] = pane_idx
    old['time_range'] = time_range
    result = job(SimpleNamespace(
        progress=SimpleNamespace(emit=lambda *_args: None),
        cancelled=lambda: False,
    ))
    return state, old, result


def _spy_fft_time_render(win, monkeypatch):
    rendered = []
    monkeypatch.setattr(
        win, '_render_fft_time_on',
        lambda *args, **kwargs: rendered.append((args, kwargs)),
    )
    return rendered


def test_fft_time_compute_edit_without_submit_rejects_old_completion(
    source_window, monkeypatch,
):
    """Changing the request and not clicking compute must not accept the old job."""
    win, fd, original_t, original_y = source_window
    state = win.analysis_managers['fft_time'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    win.toolbar._set_mode('fft_time')
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': 64, 'nfft_mode': 'fixed', 't_win_s': 0.5})
    state.params = ctx.current_params()
    _state, old, result = _finish_fft_time_job(win)
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs, 'submit_batch',
        lambda *args, **kwargs: submitted.append(args),
    )
    # 128 is not a combo item, so it would leave the request unchanged.
    # Overlap is a real compute field and does not submit a new job.
    ctx.apply_params({'overlap': 0.25})
    win._on_analysis_compute_params_changed('fft_time', ctx.compute_params())
    assert old['params']['overlap'] != ctx.compute_params()['overlap']
    rendered = _spy_fft_time_render(win, monkeypatch)
    win._on_fft_time_render_requested(old, result, False)
    assert not rendered
    assert submitted == []
    assert_original(fd, original_t, original_y)


def test_fft_time_source_change_rejects_old_completion(source_window, monkeypatch):
    win, *_rest = source_window
    state = win.analysis_managers['fft_time'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    win.toolbar._set_mode('fft_time')
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': 64, 'nfft_mode': 'fixed'})
    state.params = ctx.current_params()
    _state, old, result = _finish_fft_time_job(win)
    state.panes[0].sources = [('f1', 'out')]
    rendered = _spy_fft_time_render(win, monkeypatch)
    win._on_fft_time_render_requested(old, result, False)
    assert not rendered


def test_fft_time_recreated_pane_rejects_old_completion(source_window, monkeypatch):
    """Closing pane 2 and creating the same index is a new pane, not the old one."""
    win, *_rest = source_window
    win.toolbar._set_mode('fft_time')
    state = win.analysis_managers['fft_time'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    win._on_analysis_split('fft_time', True)
    state.panes[1].sources = [('f1', 'sig')]
    old_pane = state.panes[1]
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': 64, 'nfft_mode': 'fixed', 't_win_s': 0.5})
    state.params = ctx.current_params()
    _state, old, result = _finish_fft_time_job(win, pane_idx=1)
    old['pane_token'] = id(old_pane)
    win._on_analysis_split('fft_time', False)
    win._on_analysis_split('fft_time', True)
    state.panes[1].sources = [('f1', 'sig')]
    assert id(state.panes[1]) != id(old_pane)
    rendered = _spy_fft_time_render(win, monkeypatch)
    win._on_fft_time_render_requested(old, result, False)
    assert not rendered


def test_fft_time_display_edit_uses_latest_intent_without_dsp(
    source_window, monkeypatch,
):
    win, *_rest = source_window
    state = win.analysis_managers['fft_time'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    win.toolbar._set_mode('fft_time')
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': 64, 'nfft_mode': 'fixed', 't_win_s': 0.5})
    state.params = ctx.current_params()
    _state, old, result = _finish_fft_time_job(win)
    assert old['render_params'].get('amplitude_mode') != 'amplitude'
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs, 'submit_batch',
        lambda *args, **kwargs: submitted.append(args),
    )
    ctx.apply_params({'amplitude_mode': 'amplitude'})
    state.params = ctx.current_params()
    rendered = _spy_fft_time_render(win, monkeypatch)
    win._on_fft_time_render_requested(old, result, False)
    assert rendered
    passed = rendered[0][0][2]
    assert passed['amplitude_mode'] == 'amplitude'
    assert submitted == []


def test_fft_time_deleted_view_close_all_and_unloaded_source_do_not_publish(
    source_window, monkeypatch,
):
    win, *_rest = source_window
    win.toolbar._set_mode('fft_time')
    mgr = win.analysis_managers['fft_time']
    state = mgr.get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    ctx = win.inspector.fft_time_ctx
    ctx.apply_params({'nfft': 64, 'nfft_mode': 'fixed'})
    state.params = ctx.current_params()
    _state, old, result = _finish_fft_time_job(win)
    key = win._fft_time_current_cache_key(state, state.panes[0], 0)
    old['analysis_key'] = key
    win._store_analysis_result('fft_time', state.view_id, 0, key, result)
    rendered = _spy_fft_time_render(win, monkeypatch)

    removed = state.view_id
    mgr.new_view()
    win._on_analysis_delete('fft_time', 0)
    win._on_fft_time_render_requested(old, result, False)
    assert not rendered
    assert key not in win._pinned_keys_for_section('fft_time')

    # Close-all replaces every View. The dispatch id must not come back.
    live = mgr.get(mgr.active)
    live.panes[0].sources = [('f1', 'sig')]
    live.params = ctx.current_params()
    _state, closed, closed_result = _finish_fft_time_job(win)
    closed_id = live.view_id
    closed_key = win._fft_time_current_cache_key(live, live.panes[0], 0)
    closed['analysis_key'] = closed_key
    win._store_analysis_result('fft_time', closed_id, 0, closed_key, closed_result)
    mgr.new_view()
    for item in list(mgr.views):
        win._forget_analysis_view('fft_time', item.view_id, len(item.panes))
    mgr.reset_to_single_default()
    win._on_fft_time_render_requested(closed, closed_result, False)
    assert not rendered
    assert closed_key not in win._pinned_keys_for_section('fft_time')
    assert removed != mgr.get(0).view_id

    # Unloaded source: do not write the released file back onto the pane.
    current = mgr.get(0)
    current.attached_file_ids = ['f1']
    current.panes[0].sources = [('f1', 'sig')]
    current.params = ctx.current_params()
    _state, unloaded, unloaded_result = _finish_fft_time_job(win)
    del win.files['f1']
    win._on_fft_time_render_requested(unloaded, unloaded_result, False)
    assert not rendered


def test_obsolete_order_completion_does_not_render_current_request(
    source_window, qtbot, monkeypatch,
):
    """Real order queue: change the request before the old job finishes."""
    win, fd, original_t, original_y = source_window
    win.toolbar._set_mode('order')
    state = win.analysis_managers['order'].get(0)
    state.attached_file_ids = ['f1']
    state.panes[0].sources = [('f1', 'sig')]
    ctx = win.inspector.order_ctx
    ctx.set_rpm_mode('manual')
    state.params = ctx.current_params()
    built = win._build_order_job(0, 'f1', 'sig', None, warn=False)
    assert built is not None
    job, job_ctx = built
    started = threading.Event()
    release = threading.Event()

    def gated(worker):
        started.set()
        assert release.wait(5)
        return job(worker)

    rendered = []
    monkeypatch.setattr(
        win, '_render_order_time', lambda *args, **kwargs: rendered.append(args),
    )
    monkeypatch.setattr(
        win, '_render_order_on', lambda *args, **kwargs: rendered.append(args),
    )
    win._analysis_jobs.submit_batch('order', [(gated, job_ctx)])
    qtbot.waitUntil(started.is_set, timeout=5000)
    ctx.spin_mo.setValue(int(ctx.spin_mo.value()) + 1)
    assert_original(fd, original_t, original_y)
    release.set()
    qtbot.waitUntil(lambda: not win._analysis_jobs.is_busy('order'), timeout=15000)
    assert not rendered, 'obsolete order completion must not render as current'
    assert win.analysis_caches['order'].get(job_ctx['analysis_key']) is not None


_DISPLAY_PRESET_CASES = (
    ('fft', 'amp_y', 'dB'),
    ('fft_time', 'amplitude_mode', 'amplitude'),
    ('order', 'amplitude_mode', 'Amplitude'),
)


def _seed_display_facts(win, section):
    ctx = win._analysis_ctx(section)
    facts = {'fs': 100.0, 'nfft': 64, 'nfft_requested': 64, 'df': 1.0}
    state = win.analysis_managers[section].get(0)
    state.attached_file_ids = ['f1']
    if section == 'order':
        # RPM mode emits a compute edit, and that commit reads the live
        # signal combo. Set the pane source after that commit.
        ctx.set_rpm_mode('manual')
    state.panes[0].sources = [('f1', 'sig')]
    state.params = ctx.current_params()
    ctx.set_effective_facts(facts)
    pane = state.panes[0]
    if section == 'fft':
        sig = win.files['f1'].data['sig'].values
        effective = win._resolve_fft_effective_params(
            ctx.compute_params(), len(sig), 100.0,
        )
        cached = win._fft_compute_arrays(sig, 100.0, effective)
        key = win._analysis_cache_key('fft', 'f1', 'sig', pane_idx=0)
        win.analysis_caches['fft'].put(key, cached)
    else:
        # The render/sync key includes the pane RPM source. Seeding None
        # misses once Order is in manual mode with a pane binding.
        key = win._analysis_cache_key(
            section, 'f1', 'sig',
            rpm_source=pane.rpm_source if section == 'order' else None,
            pane_idx=0,
        )
        win.analysis_caches[section].put(
            key, SimpleNamespace(
                effective=facts, metadata={'frames': 1},
                params=SimpleNamespace(nfft=64),
            ),
        )
    return ctx, facts


@pytest.mark.parametrize(('section', 'field', 'value'), _DISPLAY_PRESET_CASES)
def test_display_only_preset_keeps_section_facts_current(
    source_window, monkeypatch, section, field, value,
):
    win, *_rest = source_window
    win.toolbar._set_mode(section)
    monkeypatch.setattr(win, '_render_fft_time_on', lambda *args, **kwargs: None)
    monkeypatch.setattr(win, '_render_order_on', lambda *args, **kwargs: None)
    monkeypatch.setattr(win, '_render_order_time', lambda *args, **kwargs: None)
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs, 'submit_batch',
        lambda *args, **kwargs: submitted.append(section),
    )
    ctx, _facts = _seed_display_facts(win, section)
    before = ctx.effective_facts_text()
    assert '实际 Fs' in before
    # Preset slots store the collect surface. current_params() keeps FFT-time
    # overlap as a fraction, and the loader would turn that into 0%.
    payload = dict(ctx._collect_preset())
    payload[field] = value
    ctx.preset_bar._write(4, 'Display only', payload)
    ctx.preset_bar._load(4)
    assert ctx.display_params()[field] == value
    assert not ctx.effective_facts_is_stale()
    assert '实际 Fs' in ctx.effective_facts_text()
    assert submitted == []


@pytest.mark.parametrize('section', ('fft', 'fft_time', 'order'))
def test_compute_preset_marks_facts_stale_without_submitting(
    source_window, monkeypatch, section,
):
    win, *_rest = source_window
    win.toolbar._set_mode(section)
    monkeypatch.setattr(win, '_render_fft_time_on', lambda *args, **kwargs: None)
    monkeypatch.setattr(win, '_render_order_on', lambda *args, **kwargs: None)
    monkeypatch.setattr(win, '_render_order_time', lambda *args, **kwargs: None)
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs, 'submit_batch',
        lambda *args, **kwargs: submitted.append(section),
    )
    ctx, _facts = _seed_display_facts(win, section)
    payload = dict(ctx._collect_preset())
    if section == 'order':
        payload['max_order'] = int(payload.get('max_order') or 20) + 1
    elif section == 'fft':
        payload['window'] = 'hamming' if payload.get('window') != 'hamming' else 'hann'
    else:
        payload['t_win_s'] = float(payload.get('t_win_s') or 0.5) + 0.25
    ctx.preset_bar._write(4, 'Compute change', payload)
    ctx.preset_bar._load(4)
    assert ctx.effective_facts_is_stale()
    text = ctx.effective_facts_text()
    assert '（已过期）' in text
    assert '实际 Fs' in text
    assert submitted == []


def test_fft_time_compute_revert_restores_current_facts(source_window, monkeypatch):
    win, *_rest = source_window
    win.toolbar._set_mode('fft_time')
    monkeypatch.setattr(win, '_render_fft_time_on', lambda *args, **kwargs: None)
    ctx, _facts = _seed_display_facts(win, 'fft_time')
    state = win.analysis_managers['fft_time'].get(0)
    original = float(ctx.compute_params()['t_win_s'])
    ctx.apply_params({'t_win_s': original + 0.25})
    win._on_analysis_compute_params_changed('fft_time', ctx.compute_params())
    assert ctx.effective_facts_is_stale()
    assert '实际 Fs' in ctx.effective_facts_text()
    ctx.apply_params({'t_win_s': original})
    win._on_analysis_compute_params_changed('fft_time', ctx.compute_params())
    assert state.params['t_win_s'] == pytest.approx(original)
    assert not ctx.effective_facts_is_stale()
    assert '实际 Fs' in ctx.effective_facts_text()


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
