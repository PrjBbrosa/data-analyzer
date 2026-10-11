"""A previous attempt's diagnostic must not lock out the current FRF request."""
import pytest

from mf4_analyzer.ui.main_window._frf_mixin import FrfPreflightError
from .test_frf_main_window import _window_with_pair
from .test_analysis_view_comparison import _enter


def _restored_error(qtbot):
    win, fid, state, _time = _window_with_pair(qtbot, n=10000)
    _enter(win, 'frf')
    state.panes[0].time_range = (-1.0, 9.0)
    win._apply_analysis_time_range('frf', state)
    assert win._recompute_restored_frf_view(state.view_id) == 0
    assert '超出当前来源' in win.inspector.frf_ctx.validation_message()
    return win, fid, state


def test_full_range_clears_old_error_and_button_dispatches(qtbot, monkeypatch):
    win, _fid, state = _restored_error(qtbot)
    ctx = win.inspector.frf_ctx
    requested = []
    monkeypatch.setattr(win._frf_coordinator, 'request', requested.append)
    win.inspector.top.set_range_enabled(False)
    assert state.panes[0].time_range is None
    assert ctx.validation_message() == ''
    assert ctx.btn_compute.isEnabled()
    ctx.btn_compute.click()
    assert len(requested) == 1
    assert callable(requested[0]['job'])
    assert requested[0]['view_id'] == state.view_id


@pytest.mark.parametrize('choice', ['full', 'cancel'])
def test_restore_error_allows_manual_range_confirmation(qtbot, monkeypatch, choice):
    win, _fid, state = _restored_error(qtbot)
    asked, requested = [], []

    def choose(*args):
        asked.append(args)
        return choice

    monkeypatch.setattr(win, '_ask_use_local_time_range', choose)
    monkeypatch.setattr(win._frf_coordinator, 'request', requested.append)
    ctx = win.inspector.frf_ctx
    assert ctx.btn_compute.isEnabled()
    ctx.btn_compute.click()
    assert len(asked) == 1
    assert len(requested) == (1 if choice == 'full' else 0)
    assert state.panes[0].time_range == (None if choice == 'full' else (-1.0, 9.0))


def test_corrected_selected_range_clears_error_without_computing(qtbot, monkeypatch):
    win, _fid, state = _restored_error(qtbot)
    requested = []
    monkeypatch.setattr(win._frf_coordinator, 'request', requested.append)
    win._apply_user_range_commit((1.0, 8.0))
    assert state.panes[0].time_range == (1.0, 8.0)
    assert win.inspector.frf_ctx.validation_message() == ''
    assert win.inspector.frf_ctx.btn_compute.isEnabled()
    assert requested == []


@pytest.mark.parametrize('comparison', [False, True])
def test_other_view_with_same_parameters_does_not_inherit_error(qtbot, monkeypatch, comparison):
    win, fid, a = _restored_error(qtbot)
    mgr = win.analysis_managers['frf']
    index = mgr.new_view(activate=False)
    b = mgr.get(index)
    b.params = dict(win.inspector.frf_ctx.current_params())
    b.attached_file_ids = [fid]
    b.panes[0].input_source = (fid, 'input')
    b.panes[0].output_source = (fid, 'output')
    requested = []
    monkeypatch.setattr(win._frf_coordinator, 'request', requested.append)
    if comparison:
        win.open_comparison('frf', a.view_id, b.view_id)
        win.focus_comparison('frf', b.view_id, 0)
    else:
        mgr.set_active(index)
    ctx = win.inspector.frf_ctx
    assert ctx.validation_message() == ''
    assert ctx.btn_compute.isEnabled()
    assert requested == []
    # A background failure cannot replace the newly focused request's status.
    win._on_frf_failed({'view_id': a.view_id, 'pane_idx': 0}, FrfPreflightError('旧 View 错误'))
    assert ctx.validation_message() == ''


def test_split_focus_does_not_inherit_error(qtbot, monkeypatch):
    win, fid, state = _restored_error(qtbot)
    win._on_analysis_split('frf', True)
    state.panes[1].input_source = (fid, 'input')
    state.panes[1].output_source = (fid, 'output')
    state.panes[1].time_range = None
    requested = []
    monkeypatch.setattr(win._frf_coordinator, 'request', requested.append)
    win._analysis_page('frf').set_focused_index(1)
    ctx = win.inspector.frf_ctx
    assert ctx.validation_message() == ''
    assert ctx.btn_compute.isEnabled()
    assert requested == []


@pytest.mark.parametrize('invalid_pair', ['same', 'missing', 'unavailable'])
def test_current_pair_problem_takes_priority_over_old_diagnostic(qtbot, invalid_pair):
    win, fid, _state = _restored_error(qtbot)
    ctx = win.inspector.frf_ctx
    if invalid_pair == 'unavailable':
        ctx.set_channel_candidates([('input', (fid, 'input'))])
        expected = '来源不可用'
    else:
        # Programmatic projection deliberately suppresses user-edit handlers.
        old = ctx.combo_output.blockSignals(True)
        try:
            ctx.set_output_source((fid, 'input') if invalid_pair == 'same' else None)
        finally:
            ctx.combo_output.blockSignals(old)
        ctx._refresh_validation()
        expected = '不能相同' if invalid_pair == 'same' else '请选择输入和输出'
    assert not ctx.btn_compute.isEnabled()
    assert expected in ctx.validation_message()


def test_display_only_change_preserves_diagnostic_and_retry(qtbot):
    win, _fid, _state = _restored_error(qtbot)
    ctx = win.inspector.frf_ctx
    message = ctx.validation_message()
    ctx.combo_frequency_scale.setCurrentIndex(1)
    assert ctx.validation_message() == message
    assert ctx.btn_compute.isEnabled()


def test_same_request_projection_keeps_diagnostic(qtbot):
    win, _fid, state = _restored_error(qtbot)
    ctx = win.inspector.frf_ctx
    before = ctx.validation_message()
    win._apply_frf_sources(state)
    assert ctx.validation_message() == before
    assert ctx.btn_compute.isEnabled()


def test_changing_pair_clears_previous_attempt(qtbot):
    win, fid, state = _restored_error(qtbot)
    ctx = win.inspector.frf_ctx
    ctx.swap_sources()
    assert state.panes[0].input_source == (fid, 'output')
    assert state.panes[0].output_source == (fid, 'input')
    assert ctx.validation_message() == ''
    assert ctx.btn_compute.isEnabled()


def test_retried_preflight_error_does_not_submit_worker(qtbot, monkeypatch):
    win, _fid, _state = _restored_error(qtbot)
    win.inspector.top.set_range_enabled(False)
    ctx = win.inspector.frf_ctx
    # The source is ten seconds long; this cannot fit two complete segments.
    ctx.spin_t_win.setValue(20.0)
    submitted = []
    monkeypatch.setattr(win._analysis_jobs, 'submit', lambda *a, **k: submitted.append(k))
    ctx.btn_compute.click()
    assert ctx.validation_message()
    message = ctx.validation_message()
    assert ctx.btn_compute.isEnabled()
    ctx.btn_compute.click()
    assert ctx.validation_message() == message
    assert submitted == []
