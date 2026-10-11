"""Real-control regressions: display refresh never applies a draft request."""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from .test_analysis_view_comparison_regressions import win
from .test_analysis_view_comparison import _enter

SECTIONS = ('fft', 'fft_time', 'order', 'frf')


def prepare(win, section, monkeypatch):
    page = _enter(win, section)
    ctx = win._analysis_ctx(section)
    state = win.analysis_managers[section].get(0)
    state.params = dict(ctx.current_params())
    state.params['window'] = 'hanning'
    fid = next(iter(win.files))
    state.attached_file_ids = list(win.files)
    state.panes[0].sources = [(fid, 'speed')]
    if section == 'order':
        state.params.update(rpm_mode='manual', manual_rpm=600.)
    if section == 'frf':
        state.panes[0].input_source = (fid, 'speed')
        state.panes[0].output_source = (fid, 'torque')
    win._on_analysis_view_switched(section, 0)
    calls = []
    submit = win._analysis_jobs.submit_batch
    compute = win._fft_compute_arrays

    def counted_submit(*args, **kwargs):
        calls.append(args[0])
        return submit(*args, **kwargs)

    def counted_fft(*args, **kwargs):
        calls.append('fft')
        return compute(*args, **kwargs)

    monkeypatch.setattr(win._analysis_jobs, 'submit_batch', counted_submit)
    monkeypatch.setattr(win, '_fft_compute_arrays', counted_fft)
    return ctx, state, page.pane_canvas(0), calls


def has_picture(section, canvas):
    if section == 'fft':
        return bool(canvas._amp_curves)
    if section == 'frf':
        return canvas._result is not None
    return canvas._matrix_disp is not None


def edit_window(ctx, section, value):
    if section == 'frf':
        ctx.combo_window.setCurrentIndex(ctx.combo_window.findData(value))
    else:
        ctx.combo_win.setCurrentText(value)


def edit_display(ctx, section):
    if section == 'fft':
        ctx.combo_amp_y.setCurrentText('dB')
    elif section in ('fft_time', 'order'):
        ctx.combo_amp_unit.setCurrentText('Linear')
    else:
        ctx.combo_phase_mode.setCurrentIndex(1 - ctx.combo_phase_mode.currentIndex())


def calculate(win, section, qtbot):
    getattr(win, {'fft': 'do_fft', 'fft_time': 'do_fft_time',
                  'order': 'do_order_time', 'frf': 'do_frf'}[section])()
    qtbot.waitUntil(lambda: not win._analysis_jobs.is_running(section), timeout=15000)
    QApplication.processEvents()


@pytest.mark.parametrize('section', SECTIONS)
def test_display_edit_retains_explicit_result_after_compute_edit(win, section, monkeypatch, qtbot):
    ctx, state, canvas, calls = prepare(win, section, monkeypatch)
    assert not has_picture(section, canvas)
    calculate(win, section, qtbot)
    assert has_picture(section, canvas)
    count = len(calls)
    edit_window(ctx, section, 'hamming')
    edit_display(ctx, section)
    QApplication.processEvents()
    assert len(calls) == count
    assert has_picture(section, canvas), 'display edit must keep last explicit result'
    binding = state.panes[0].result_binding
    assert binding is not None and binding.stale
    edit_window(ctx, section, 'hanning')
    QApplication.processEvents()
    assert state.panes[0].result_binding.request is binding.request
    assert state.panes[0].result_binding.keys == binding.keys
    assert binding.stale, 'reverting a draft does not click Calculate'
    calculate(win, section, qtbot)
    assert len(calls) == count, 'explicit Calculate may reuse cache without DSP'
    assert not state.panes[0].result_binding.stale


@pytest.mark.parametrize('section', ('fft', 'fft_time', 'order'))
def test_db_dialog_save_never_starts_first_compute(win, section, monkeypatch, qtbot):
    from mf4_analyzer.ui.db_reference_dialog import DbReferenceDefaultsDialog

    ctx, state, canvas, calls = prepare(win, section, monkeypatch)

    def execute(dialog):
        dialog.show()
        QApplication.processEvents()
        QTest.mouseClick(dialog._btn_save, Qt.LeftButton)
        return dialog.result()

    monkeypatch.setattr(DbReferenceDefaultsDialog, 'exec_', execute)
    win._open_db_reference_dialog(section)
    QApplication.processEvents()
    qtbot.wait(30)
    assert calls == []
    assert not has_picture(section, canvas)


@pytest.mark.parametrize('section', SECTIONS)
def test_other_view_cached_request_does_not_authorize_empty_view(win, section, monkeypatch, qtbot):
    ctx, state, canvas, calls = prepare(win, section, monkeypatch)
    calculate(win, section, qtbot)
    count = len(calls)
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
    draft = AnalysisViewState.from_dict(state.to_dict())
    assert not getattr(draft.panes[0], 'result_binding', None)
    mgr = win.analysis_managers[section]
    draft.view_id += '-draft'
    mgr.views.append(draft)
    mgr.active = len(mgr.views) - 1
    win._on_analysis_view_switched(section, mgr.active)
    canvas = win._analysis_page(section).pane_canvas(0)
    edit_display(win._analysis_ctx(section), section)
    QApplication.processEvents()
    assert len(calls) == count
    assert not has_picture(section, canvas), 'cache presence is not a Calculate action'


@pytest.mark.parametrize('section', SECTIONS)
def test_range_edit_and_view_return_keep_last_result(win, section, monkeypatch, qtbot):
    ctx, state, canvas, calls = prepare(win, section, monkeypatch)
    calculate(win, section, qtbot)
    applied = state.panes[0].result_binding
    count = len(calls)
    win._on_time_range_enabled_changed(True)
    win._apply_user_range_commit((0.2, 2.8))
    edit_display(ctx, section)
    assert state.panes[0].result_binding.request is applied.request
    assert state.panes[0].result_binding.stale
    assert has_picture(section, canvas)
    assert state.panes[0].time_range == (0.2, 2.8)
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
    mgr = win.analysis_managers[section]
    draft = AnalysisViewState.from_dict(state.to_dict())
    draft.view_id += '-new'
    mgr.views.append(draft)
    mgr.active = len(mgr.views) - 1
    win._on_analysis_view_switched(section, mgr.active)
    assert not has_picture(section, canvas)
    mgr.active = 0
    win._on_analysis_view_switched(section, 0)
    QApplication.processEvents()
    assert len(calls) == count
    assert has_picture(section, canvas)
    assert state.panes[0].result_binding.request is applied.request
    assert state.panes[0].result_binding.stale
