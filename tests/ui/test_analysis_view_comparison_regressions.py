"""Regressions for comparison state, presentation, and project ownership."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from mf4_analyzer.ui.main_window import MainWindow
from .test_frf_main_window import _window_with_pair
from .test_analysis_view_comparison import _enter, _pair, _stamp, _curve_y, _frf_result

@pytest.fixture
def win(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    for n in range(2):
        path = tmp_path / f'source{n}.csv'
        t = np.arange(5000) / 1000
        pd.DataFrame({'time': t, 'speed': np.sin(t * 30), 'torque': np.cos(t * 30)}).to_csv(path, index=False)
        w._load_one(str(path))
    return w

def prep(w, section):
    page = _enter(w, section)
    mgr, a, b = _pair(w, section)
    for state, fid in zip((a, b), w.files):
        _stamp(w, section, state)
        state.attached_file_ids = list(w.files)
        state.panes[0].sources = [(fid, 'speed')]
    return (page, mgr, a, b)

@pytest.mark.parametrize('section', ['fft', 'fft_time', 'order', 'frf'])
def test_close_restores_host_inspector(win, section):
    page, mgr, a, b = prep(win, section)
    a.params['window'] = 'hanning'
    b.params['window'] = 'hamming'
    win.open_comparison(section, a.view_id, b.view_id)
    win.focus_comparison(section, b.view_id, 0)
    assert win._analysis_ctx(section).current_params()['window'] == 'hamming'
    win.close_comparison(section)
    visible = win._analysis_ctx(section).current_params()['window']
    win._capture_active_analysis_view(section)
    assert visible == 'hanning'
    assert a.params['window'] == 'hanning'

@pytest.mark.parametrize('reference', [1.0, 2.0])
def test_fft_each_side_uses_own_display_params(win, reference):
    page, mgr, a, b = prep(win, 'fft')
    a.params['amp_y'] = 'Linear'
    b.params.update(amp_y='dB', db_reference_mode='manual', db_reference=reference)
    for state in (a, b):
        fid, ch = state.panes[0].sources[0]
        key = win._analysis_cache_key_for_view_source('fft', state, state.panes[0], 0, fid, ch)
        win.analysis_caches['fft'].put(key, (np.arange(8.0), np.full(8, 2.0), np.full(8, 2.0)))
    win.open_comparison('fft', a.view_id, b.view_id)
    ya = _curve_y(page.pane_canvas(0))[0]
    yb = _curve_y(page.peer_cards()[0].canvas)[0]
    assert ya == pytest.approx(2.0)
    assert yb == pytest.approx(20 * np.log10(2.0 / reference))

def test_peer_frf_display_edit_only_updates_peer(win, monkeypatch):
    page, mgr, a, b = prep(win, 'frf')
    win.open_comparison('frf', a.view_id, b.view_id)
    win.focus_comparison('frf', b.view_id, 0)
    hits = []
    monkeypatch.setattr(page.pane_canvas(0), 'set_display_params', lambda p: hits.append('host'))
    monkeypatch.setattr(page.peer_cards()[0].canvas, 'set_display_params', lambda p: hits.append('peer'))
    win._on_frf_display_params_changed({'magnitude_scale': 'linear'})
    assert hits == ['peer']

@pytest.mark.parametrize('section', ['fft', 'fft_time', 'order', 'frf'])
def test_peer_full_range_toggle_only_updates_peer(win, section):
    page, mgr, a, b = prep(win, section)
    a.panes[0].time_range = (0.1, 0.8)
    b.panes[0].time_range = (0.2, 0.7)
    win.open_comparison(section, a.view_id, b.view_id)
    win.focus_comparison(section, b.view_id, 0)
    win._on_time_range_enabled_changed(False)
    assert a.panes[0].time_range == (0.1, 0.8)
    assert b.panes[0].time_range is None

def test_peer_frf_capture_uses_peer_camera(win):
    page, mgr, a, b = prep(win, 'frf')
    win.open_comparison('frf', a.view_id, b.view_id)
    win.focus_comparison('frf', b.view_id, 0)
    for canvas, limits in ((page.pane_canvas(0), (1.0, 10.0)), (page.peer_cards()[0].canvas, (20.0, 100.0))):
        canvas.set_result(_frf_result(2.0))
        canvas.set_xlim(*limits)
    expected = page.peer_cards()[0].canvas.get_xlim()
    win._capture_frf_canvas_ranges(b)
    assert b.panes[0].xlim == pytest.approx(expected)

def test_frf_range_revert_reuses_cached_result(qtbot):
    w, fid, state, t = _window_with_pair(qtbot, n=5000)
    _enter(w, 'frf')
    w.inspector.frf_ctx.spin_t_win.setValue(0.3)
    state.params = w.inspector.frf_ctx.current_params()
    state.panes[0].time_range = (0.1, 3.8)
    w._apply_analysis_time_range('frf', state)
    candidate = w._build_frf_candidate(state, 0)
    ctx = w._frf_coordinator._build_context(candidate)
    result = candidate['job'](SimpleNamespace(cancelled=lambda: False, progress=SimpleNamespace(emit=lambda *a: None)))
    w._store_analysis_result('frf', state.view_id, 0, ctx['analysis_key'], result)
    w._on_frf_render_requested(ctx, result, False)
    assert w._frf_cached_result_for_pane(state, state.panes[0]) is result
    w._apply_user_range_commit((0.2, 3.8))
    w._apply_user_range_commit((0.1, 3.8))
    assert w._frf_cached_result_for_pane(state, state.panes[0]) is result

def test_peer_compute_edit_stales_peer_canvas(win, monkeypatch):
    page, mgr, a, b = prep(win, 'fft')
    win.open_comparison('fft', a.view_id, b.view_id)
    win.focus_comparison('fft', b.view_id, 0)
    hits = []
    monkeypatch.setattr(page.pane_canvas(0), 'mark_spectrum_stale', lambda: hits.append('host'))
    monkeypatch.setattr(page.peer_cards()[0].canvas, 'mark_spectrum_stale', lambda: hits.append('peer'))
    win.inspector.fft_ctx.apply_params({'window': 'hamming'})
    win._on_analysis_compute_params_changed('fft', win.inspector.fft_ctx.current_params())
    assert hits and set(hits) == {'peer'}

def test_frf_axis_link_requires_matching_scales(win):
    page, mgr, a, b = prep(win, 'frf')
    a.params['frequency_scale'] = 'log'
    b.params['frequency_scale'] = 'linear'
    win.open_comparison('frf', a.view_id, b.view_id)
    left = page.pane_canvas(0)
    right = page.peer_cards()[0].canvas
    left.set_result(_frf_result(2.0), display_params=a.params)
    right.set_result(_frf_result(2.0), display_params=b.params)
    left.set_xlim(10.0, 100.0)
    right.set_xlim(10.0, 100.0)
    accepted = win.set_comparison_axis_linked('frf', True)
    assert not accepted

@pytest.mark.parametrize('section', ['fft', 'fft_time', 'order', 'frf'])
def test_save_from_time_preserves_hidden_comparison_host(win, tmp_path, section):
    import json
    page, mgr, a, b = prep(win, section)
    a.params['window'] = 'hanning'
    b.params['window'] = 'hamming'
    win.open_comparison(section, a.view_id, b.view_id)
    win.focus_comparison(section, b.view_id, 0)
    win.toolbar._set_mode('time')
    assert a.params['window'] == 'hanning'
    path = tmp_path / 'review.tlproj'
    assert win.save_project(path)
    raw = json.loads(path.read_text())
    saved = raw['analysis_views'][section]['views'][0]['params']['window']
    assert saved == 'hanning'

@pytest.mark.parametrize('section', ['fft_time', 'order'])
def test_background_heatmap_does_not_echo_levels_to_focused_controls(win, section):
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.signal.order import OrderAnalysisParams, OrderTimeResult
    page, mgr, host, peer = prep(win, section)
    for state in (host, peer):
        state.params.update(amplitude_mode='amplitude_db', z_auto=True)
    win.open_comparison(section, host.view_id, peer.view_id)
    ctx = win._analysis_ctx(section)
    ctx.spin_z_floor.setValue(-123.0)
    before = ctx.spin_z_floor.value()
    canvas = page.peer_cards()[0].canvas
    if section == 'fft_time':
        result = SpectrogramResult(times=np.array([0.0, 0.5, 1.0]), frequencies=np.array([0.0, 10.0, 20.0]), amplitude=np.full((3, 3), 1000.0), params=SpectrogramParams(fs=100.0, nfft=100), channel_name='speed', metadata={'frames': 3, 'freq_bins': 3})
        win._render_fft_time_on(canvas, result, peer.params, source=peer.panes[0].sources[0])
    else:
        result = OrderTimeResult(times=np.array([0.0, 0.5, 1.0]), orders=np.array([0.0, 1.0, 2.0]), amplitude=np.full((3, 3), 1000.0), params=OrderAnalysisParams(fs=100.0))
        win._render_order_on(canvas, result, source=peer.panes[0].sources[0])
    assert ctx.spin_z_floor.value() == before

def test_host_completion_uses_host_display_while_peer_focused(win):
    page, mgr, host, peer = prep(win, 'fft_time')
    host.params['amplitude_mode'] = 'amplitude'
    peer.params['amplitude_mode'] = 'amplitude_db'
    win.open_comparison('fft_time', host.view_id, peer.view_id)
    win.focus_comparison('fft_time', peer.view_id, 0)
    params = win._fft_time_completion_display_params(host, {'view_id': host.view_id})
    assert params['amplitude_mode'] == 'amplitude'
    assert not win._completion_updates_focus('fft_time', {'view_id': peer.view_id, 'pane_idx': 1})

@pytest.mark.parametrize('section', ['fft', 'fft_time', 'order', 'frf'])
def test_dynamic_host_pane_rebinds_without_moving_peer_focus(win, section):
    page, mgr, host, peer = prep(win, section)
    win.open_comparison(section, host.view_id, peer.view_id)
    win.focus_comparison(section, peer.view_id, 0)
    win._on_analysis_split(section, True)
    assert win._comparison().canvas_for(section, host.view_id, 1) is page.pane_canvas(1)
    assert win._comparison().focused(section) == (peer.view_id, 0)
    win._on_analysis_split(section, False)
    assert win._comparison().canvas_for(section, host.view_id, 1) is None
    assert win._comparison().focused(section) == (peer.view_id, 0)

def test_axis_scale_edit_disconnects_previously_compatible_pair(win):
    page, mgr, host, peer = prep(win, 'frf')
    win.open_comparison('frf', host.view_id, peer.view_id)
    assert win.set_comparison_axis_linked('frf', True)
    win.focus_comparison('frf', peer.view_id, 0)
    win._on_frf_display_params_changed({'frequency_scale': 'linear'})
    assert not win._comparison().axis_linked('frf')
    assert not page.btn_view_link.isChecked()

def test_levels_lock_resolves_each_sources_auto_reference(win, monkeypatch):
    from mf4_analyzer import db_reference
    page, mgr, host, peer = prep(win, 'fft_time')
    first = host.panes[0].sources[0][0]
    monkeypatch.setattr(win._analysis_context, 'channel_reference_facts', lambda fid, ch: db_reference.ChannelReferenceFacts(quantity='pressure', unit='Pa', metadata_reference=1.0 if fid == first else 2.0))
    for state in (host, peer):
        state.params.update(db_reference_mode='auto', db_reference=1.0)
    win.open_comparison('fft_time', host.view_id, peer.view_id)
    assert not win.set_comparison_levels_locked('fft_time', True)

@pytest.mark.parametrize('section', ['fft_time', 'order'])
def test_colorbar_echo_follows_bound_pane_and_persists(win, section):
    page, mgr, host, peer = prep(win, section)
    win.open_comparison(section, host.view_id, peer.view_id)
    win.focus_comparison(section, peer.view_id, 0)
    ctx = win._analysis_ctx(section)
    before = ctx.current_params()
    page.pane_canvas(0).levels_changed.emit(-10.0, 10.0)
    assert ctx.current_params() == before
    page.peer_cards()[0].canvas.levels_changed.emit(-20.0, 20.0)
    assert peer.params['z_floor'] == -20.0
    assert peer.params['z_ceiling'] == 20.0
    assert peer.params['z_auto'] is False

def test_comparison_orientation_does_not_compress_one_frf_pane(win, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    page, manager, host, peer = prep(win, 'frf')
    host.add_pane()
    peer.add_pane()
    win.open_comparison('frf', host.view_id, peer.view_id)
    win.resize(1500, 950)
    win.show()
    QApplication.processEvents()
    for splitter in (page._split, page._peer_host._split):
        assert splitter.orientation() == Qt.Vertical
        sizes = splitter.sizes()
        assert min(sizes) / sum(sizes) > 0.35
