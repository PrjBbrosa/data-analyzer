"""Real worker and project-open coverage for persisted heatmap browsing intent."""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def viewport_win(qapp, qtbot, tmp_path):
    time = np.arange(4096, dtype=float) / 1024.
    path = tmp_path / 'viewport-source.csv'
    pd.DataFrame({
        'time': time,
        'speed': np.full(time.shape, 1200.),
        'torque': 10. + np.sin(2. * np.pi * 40. * time),
    }).to_csv(path, index=False)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(path))
    return win


def _compute(win, section, qtbot):
    win.toolbar._set_mode(section)
    fid = next(iter(win.files))
    win._attach_files_to_active_context([fid])
    ctx = win._analysis_ctx(section)
    win._echo_combo_signal(ctx.combo_sig, (fid, 'torque'))
    if section == 'order':
        win._echo_combo_signal(ctx.combo_rpm, (fid, 'speed'))
        win.do_order_time()
    else:
        ctx.apply_params({'nfft': 256})
        win.do_fft_time()
    canvas = win._analysis_page(section).pane_canvas(0)
    qtbot.waitUntil(lambda: canvas.has_result() and not win._analysis_jobs.is_running(section), timeout=20000)
    return canvas


def _save_user_x_home_y(win, section, canvas):
    canvas.reset_view_to_data_extents()
    xlim, _ylim = canvas.capture_xy_viewport()
    width = xlim[1] - xlim[0]
    canvas._plot.setXRange(xlim[0] + width * .2, xlim[1] - width * .2, padding=0)
    canvas._emit_viewport_intent('user', ('x',))
    mgr = win.analysis_managers[section]
    state = mgr.get(mgr.active)
    assert state.panes[0].viewport_origin == {'x': 'user', 'y': 'home'}
    return state, canvas.capture_xy_viewport()


def _watch_worker_submission(win, monkeypatch):
    submissions = []
    original = win._analysis_jobs.submit_batch
    def submit(*args, **kwargs):
        submissions.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(win._analysis_jobs, 'submit_batch', submit)
    return submissions


@pytest.mark.parametrize('section', ['fft_time', 'order'])
def test_heatmap_cold_worker_restore_preserves_axis_origins(viewport_win, qtbot, monkeypatch, section):
    win = viewport_win
    canvas = _compute(win, section, qtbot)
    state, saved = _save_user_x_home_y(win, section, canvas)
    win.analysis_caches[section].clear()
    assert not win.analysis_caches[section]._store
    canvas.full_reset()
    submissions = _watch_worker_submission(win, monkeypatch)
    getattr(win, f'_recompute_restored_{section}_view')(state.view_id)
    qtbot.waitUntil(lambda: canvas.has_result() and not win._analysis_jobs.is_running(section), timeout=20000)
    assert submissions, 'cold restoration must submit an actual worker batch'
    assert win.analysis_caches[section]._store
    assert state.panes[0].viewport_origin == {'x': 'user', 'y': 'home'}
    actual = canvas.capture_xy_viewport()
    assert actual[0] == pytest.approx(saved[0])
    assert actual[1] == pytest.approx(saved[1])


def test_project_open_recomputes_heatmap_and_preserves_axis_origins(viewport_win, qtbot, tmp_path, monkeypatch):
    win = viewport_win
    canvas = _compute(win, 'fft_time', qtbot)
    _state, saved = _save_user_x_home_y(win, 'fft_time', canvas)
    path = tmp_path / 'viewport-session.tlproj'
    win.save_project(path)
    restored = MainWindow()
    qtbot.addWidget(restored)
    assert not restored.analysis_caches['fft_time']._store
    submissions = _watch_worker_submission(restored, monkeypatch)
    restored.open_project(path)
    canvas = restored._analysis_page('fft_time').pane_canvas(0)
    qtbot.waitUntil(lambda: canvas.has_result() and not restored._analysis_jobs.is_running('fft_time'), timeout=20000)
    assert submissions, 'opening the saved project must regenerate its heatmap'
    mgr = restored.analysis_managers['fft_time']
    pane = mgr.get(mgr.active).panes[0]
    assert pane.viewport_origin == {'x': 'user', 'y': 'home'}
    actual = canvas.capture_xy_viewport()
    assert actual[0] == pytest.approx(saved[0])
    assert actual[1] == pytest.approx(saved[1])
