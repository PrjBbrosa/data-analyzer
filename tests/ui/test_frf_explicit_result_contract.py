"""FRF cache availability never substitutes for explicit result acceptance."""
from dataclasses import replace
import threading
import time as clock_time

import pytest
from PyQt5.QtWidgets import QApplication

from .test_frf_main_window import (
    _frf_section_with_real_job, _window_with_pair, _result,
)


def _cache_other_request(win, state, result):
    old = state.params['t_win_s']
    state.params['t_win_s'] = 0.4
    key = win._frf_cache_key_for_pane(state, state.panes[0])
    state.params['t_win_s'] = old
    other = replace(result, transfer=result.transfer * 7)
    win.analysis_caches['frf'].put(key, other)
    return key, other


def test_compute_draft_cache_hit_does_not_publish(qtbot, monkeypatch):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    key, other = _cache_other_request(win, state, result)
    submit = []
    monkeypatch.setattr(win._analysis_jobs, 'submit', lambda *a, **k: submit.append(a))
    ctx.spin_t_win.setValue(0.4)
    QApplication.processEvents()
    assert win.canvas_frf._result is result
    assert ctx.effective_facts_is_stale()
    assert context['analysis_key'] in win._pinned_keys_for_section('frf')
    assert submit == []
    assert win.do_frf() is False
    assert win.canvas_frf._result is other
    assert not ctx.effective_facts_is_stale()
    assert submit == []


def test_draft_revert_and_display_preserve_pending_result(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    _cache_other_request(win, state, result)
    ctx.spin_t_win.setValue(0.4)
    ctx.apply_params({'magnitude_scale': 'linear'}, emit_changes=True)
    assert win.canvas_frf._result is result
    assert win.canvas_frf.state() == 'stale'
    ctx.spin_t_win.setValue(0.3)
    assert win.canvas_frf._result is result
    assert ctx.effective_facts_is_stale()


def test_uncomputed_pane_cannot_borrow_public_cache(qtbot):
    win, fid, state, time = _window_with_pair(qtbot, n=5000)
    win.toolbar._set_mode('frf')
    ctx = win.inspector.frf_ctx
    ctx.spin_t_win.setValue(0.3)
    state.params = ctx.current_params()
    key = win._frf_cache_key_for_pane(state, state.panes[0])
    win.analysis_caches['frf'].put(key, _result(time, 1000))
    win._render_frf_view_from_cache(state)
    assert not win.canvas_frf.has_result()
    assert not ctx.effective_facts_text()


def test_switch_restores_published_result_not_draft(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    _cache_other_request(win, state, result)
    ctx.spin_t_win.setValue(0.4)
    win._on_analysis_new('frf')
    win._on_analysis_switch('frf', 0)
    assert win.canvas_frf._result is result
    assert ctx.spin_t_win.value() == 0.4
    assert ctx.effective_facts_is_stale()


def test_late_completion_after_edit_does_not_replace_bound_result(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    candidate = win._build_frf_candidate(state, 0)
    pending = win._frf_coordinator._build_context(candidate)
    other = replace(result, transfer=result.transfer * 9)
    ctx.spin_t_win.setValue(0.4)
    ctx.spin_t_win.setValue(0.3)
    win._on_frf_render_requested(pending, other, False)
    assert win.canvas_frf._result is result
    assert ctx.effective_facts_is_stale()


def test_changed_pair_keeps_published_context_across_restore(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    ctx.set_input_source((fid, 'output'))
    ctx.set_output_source((fid, 'input'))
    win._on_analysis_new('frf')
    win._on_analysis_switch('frf', 0)
    assert win.canvas_frf._result is result
    assert win.canvas_frf._context['input_source'] == (fid, 'input')
    assert win.canvas_frf._context['output_source'] == (fid, 'output')
    assert ctx.effective_facts_is_stale()


def test_failed_explicit_request_keeps_previous_result_pending(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    win._on_frf_failed(context, ValueError('synthetic retry failure'))
    assert win.canvas_frf._result is result
    assert state.panes[0].result_binding.stale
    assert ctx.effective_facts_is_stale()


def test_hidden_completion_binds_origin_without_changing_focused_canvas(qtbot):
    win, fid, state, time = _window_with_pair(qtbot, n=5000)
    win.toolbar._set_mode('frf')
    ctx = win.inspector.frf_ctx
    ctx.spin_t_win.setValue(0.3)
    state.params = ctx.current_params()
    candidate = win._build_frf_candidate(state, 0)
    context = win._frf_coordinator._build_context(candidate)
    result = _result(time, 1000)
    win._on_analysis_new('frf')
    win._store_analysis_result('frf', state.view_id, 0, context['analysis_key'], result)
    win._on_frf_render_requested(context, result, False)
    assert not win.canvas_frf.has_result()
    assert state.panes[0].result_binding.keys == (context['analysis_key'],)
    win._on_analysis_switch('frf', 0)
    assert win.canvas_frf._result is result


def test_invalidated_bound_cache_does_not_show_another_request(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    _cache_other_request(win, state, result)
    win.analysis_caches['frf'].invalidate_fid(fid)
    win._render_frf_view_from_cache(state)
    assert not win.canvas_frf.has_result()
    assert not ctx.effective_facts_text()


def test_rejected_completion_releases_only_its_new_pin(qtbot):
    win, fid, state, time, ctx, accepted, result = _frf_section_with_real_job(qtbot)
    ctx.spin_t_win.setValue(0.4)
    candidate = win._build_frf_candidate(state, 0)
    pending = win._frf_coordinator._build_context(candidate)
    other = replace(result, transfer=result.transfer * 9)
    # The coordinator writes cache before publishing. A superseding edit at
    # that boundary must not leave the rejected key pinned as a current result.
    win._store_analysis_result('frf', state.view_id, 0, pending['analysis_key'], other)
    ctx.spin_t_win.setValue(0.5)
    win._on_frf_render_requested(pending, other, False)
    assert win.canvas_frf._result is result
    assert win._pinned_keys_for_section('frf') == {accepted['analysis_key']}


@pytest.mark.parametrize('deleted', [False, True])
def test_background_failure_does_not_replace_current_status(qtbot, monkeypatch, deleted):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    win._on_analysis_new('frf')
    if deleted:
        win._on_analysis_delete('frf', 0)
    win.statusBar.showMessage('current view status')
    toasts = []
    monkeypatch.setattr(win, 'toast', lambda *args: toasts.append(args))
    win._on_frf_failed(context, ValueError('old request failed'))
    assert win.statusBar.currentMessage() == 'current view status'
    assert toasts == []


def test_completion_after_leaving_section_preserves_current_status(qtbot):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    win.toolbar._set_mode('time')
    win.statusBar.showMessage('time view status')
    win._on_frf_render_requested(context, result, False)
    assert state.panes[0].result_binding is not None
    assert win.statusBar.currentMessage() == 'time view status'


def test_cancelled_explicit_retry_keeps_previous_binding_pending(qtbot, monkeypatch):
    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    started = threading.Event()
    saw_cancel = []
    failed = []
    original_build = win._build_frf_candidate

    def slow_job(worker):
        started.set()
        for _ in range(3000):
            if worker.cancelled():
                saw_cancel.append(True)
                return result
            clock_time.sleep(0.001)
        return result

    def build_candidate(*args, **kwargs):
        candidate = original_build(*args, **kwargs)
        candidate['job'] = slow_job
        return candidate

    monkeypatch.setattr(win, '_build_frf_candidate', build_candidate)
    win._frf_coordinator.failed.connect(lambda *args: failed.append(args))
    try:
        assert win.do_frf(force=True)
        qtbot.waitUntil(started.is_set, timeout=5000)
        win._analysis_jobs.cancel('frf')
        qtbot.waitUntil(lambda: not win._analysis_jobs.is_running('frf'), timeout=5000)
        assert saw_cancel == [True]
        assert failed == []
        assert win.canvas_frf._result is result
        assert state.panes[0].result_binding.stale
        assert ctx.effective_facts_is_stale()
        win._render_frf_view_from_cache(state)
        assert win.canvas_frf._result is result
        assert win.canvas_frf.state() == 'stale'
    finally:
        win._analysis_jobs.shutdown()


def test_invalid_explicit_retry_keeps_previous_binding_pending(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window._frf_mixin import FrfPreflightError

    win, fid, state, time, ctx, context, result = _frf_section_with_real_job(qtbot)
    submitted = []

    def reject_candidate(*args, **kwargs):
        raise FrfPreflightError('synthetic invalid retry')

    monkeypatch.setattr(win, '_build_frf_candidate', reject_candidate)
    monkeypatch.setattr(win._analysis_jobs, 'submit', lambda *args, **kwargs: submitted.append(args))
    assert not win.do_frf(force=True)
    assert submitted == []
    assert win.canvas_frf._result is result
    assert state.panes[0].result_binding.stale
    assert ctx.effective_facts_is_stale()
