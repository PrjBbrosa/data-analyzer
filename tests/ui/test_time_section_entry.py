"""Section entry keeps time plotting but does not pump a global event queue."""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, qapp, tmp_path):
    t = np.linspace(0, 2, 1000)
    path = tmp_path / 'section.csv'
    pd.DataFrame({'time': t, 'torque': np.sin(t * 10)}).to_csv(path, index=False)
    win = MainWindow()
    qtbot.addWidget(win)
    win.load_file(str(path))
    fid = next(iter(win.files))
    win.navigator.set_checked_channels([(fid, 'torque')])
    win.plot_time()
    qapp.processEvents()
    yield win
    win._project_dirty.mark_saved()


@pytest.mark.parametrize('section_entry', [False, True])
def test_entry_progress_and_plot_side_effects(window, monkeypatch, section_entry):
    win = window
    begins, finishes, built = [], [], []
    begin = win._begin_compute_progress
    finish = win._finish_compute_progress
    build = win._build_time_plot_data

    def start(*args, **kwargs):
        begins.append(kwargs.get('process_events', True))
        return begin(*args, **kwargs)

    def end(*args, **kwargs):
        finishes.append(kwargs['token'])
        return finish(*args, **kwargs)

    def prepare(*args, **kwargs):
        built.append(True)
        return build(*args, **kwargs)

    monkeypatch.setattr(win, '_begin_compute_progress', start)
    monkeypatch.setattr(win, '_finish_compute_progress', end)
    monkeypatch.setattr(win, '_build_time_plot_data', prepare)
    win.canvas_time.restore_visible_xlim((0.4, 1.2))
    win._plot_time_preserving_xlim(section_entry=section_entry)
    assert begins == [not section_entry]
    assert len(finishes) == 1 and built == [True]
    assert win._active_compute_progress_token is None
    assert win._safe_capture_primary_xlim() == pytest.approx((0.4, 1.2))
    assert len(list(win.canvas_time._channel_lines.composite_items())) == 1


def test_rapid_section_entry_coalesces_and_drops_hidden_target(window, qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window, '_plot_time_preserving_xlim', lambda **kw: calls.append(kw))
    for mode in ('fft', 'time', 'fft', 'time', 'order'):
        window._on_mode_changed(mode)
    qapp.processEvents()
    assert calls == []
    for mode in ('time', 'fft', 'time'):
        window._on_mode_changed(mode)
    qapp.processEvents()
    assert calls == [{'section_entry': True}]


def test_entry_drops_replaced_view_even_with_same_id(window, qapp, monkeypatch):
    from copy import deepcopy
    calls = []
    monkeypatch.setattr(window, '_plot_time_preserving_xlim', lambda **kw: calls.append(kw))
    window._on_mode_changed('fft')
    window._on_mode_changed('time')
    idx = window.view_manager.active
    window.view_manager.views[idx] = deepcopy(window.view_manager.views[idx])
    qapp.processEvents()
    assert calls == []


def test_section_entry_failure_releases_progress_and_render_gate(window, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("preparation failed")

    monkeypatch.setattr(window, '_build_time_plot_data', fail)
    with pytest.raises(ValueError, match="preparation failed"):
        window._plot_time_preserving_xlim(section_entry=True)
    assert window._active_compute_progress_token is None
    assert not window._time_render.busy


def test_close_cancels_pending_section_entry(window, qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window, '_plot_time_preserving_xlim', lambda **kw: calls.append(kw))
    window._on_mode_changed('fft')
    window._on_mode_changed('time')
    window._project_dirty.mark_saved()
    window.close()
    qapp.processEvents()
    assert calls == []


def test_section_callback_waits_for_outer_render(window, qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window, '_plot_time_preserving_xlim', lambda **kw: calls.append(kw))
    window._on_mode_changed('fft')
    window._on_mode_changed('time')
    with window._time_render_scope():
        qapp.processEvents()
        assert calls == []
        assert window._time_render.pending_section_view is not None
    qapp.processEvents()
    assert calls == [{'section_entry': True}]
