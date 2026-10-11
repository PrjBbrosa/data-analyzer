"""Explicit requests authorize results; cached values alone do not."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from .test_analysis_view_comparison_regressions import win, prep
from mf4_analyzer.ui.analysis_result_state import bind_result, mark_pending, snapshot_request


def _prepare(win, section):
    page, manager, state, _peer = prep(win, section)
    win._on_analysis_view_switched(section, manager.active, render=False)
    if section == "order":
        ctx = win.inspector.order_ctx
        ctx.combo_rpm_mode.setCurrentIndex(ctx.combo_rpm_mode.findData("manual"))
    return page, state


def test_fft_explicit_cache_hit_creates_binding(win, monkeypatch):
    _page, state = _prepare(win, "fft")
    pane = state.panes[0]
    fid, channel = pane.sources[0]
    key = win._analysis_cache_key_for_view_source("fft", state, pane, 0, fid, channel)
    result = (np.arange(8.0), np.ones(8), np.ones(8))
    win.analysis_caches["fft"].put(key, result)
    assert pane.result_binding is None
    monkeypatch.setattr(win, "_fft_compute_arrays", lambda *a, **k: pytest.fail("cache hit computed"))
    win.do_fft()
    assert pane.result_binding.keys == (key,)
    assert pane.result_binding.request.sources == ((fid, channel),)


def test_fft_partial_success_authorizes_only_successful_source_then_failure_retains_it(win, monkeypatch):
    _page, state = _prepare(win, "fft")
    fids = list(win.files)
    win.navigator.set_checked_channels([(fid, "speed") for fid in fids])
    fetch = win._fft_fetch_signal
    monkeypatch.setattr(win, "_fft_fetch_signal", lambda fid, *a, **k: (None, None) if fid == fids[1] else fetch(fid, *a, **k))
    monkeypatch.setattr(win, "_do_fft_single", lambda: pytest.fail("captured-source failure entered legacy fallback"))
    win.do_fft()
    pane = state.panes[0]
    assert pane.result_binding.request.sources == ((fids[0], "speed"),)
    assert len(pane.result_binding.keys) == 1
    original_keys = pane.result_binding.keys
    monkeypatch.setattr(win, "_fft_fetch_signal", lambda *a, **k: (None, None))
    win.do_fft()
    assert pane.result_binding.keys == original_keys
    assert pane.result_binding.stale


def test_fft_legacy_single_is_bound_and_second_click_reuses_cache(win, monkeypatch, qapp):
    _page, state = _prepare(win, "fft")
    source = state.panes[0].sources[0]
    win._echo_combo_signal(win.inspector.fft_ctx.combo_sig, source)
    qapp.processEvents()
    state.panes[0].sources = []
    monkeypatch.setattr(win, "_capture_active_analysis_view", lambda *a, **k: None)
    calls = []
    compute = win._fft_compute_arrays
    def counted(*args, **kwargs):
        calls.append(True)
        return compute(*args, **kwargs)
    monkeypatch.setattr(win, "_fft_compute_arrays", counted)
    win.do_fft()
    assert state.panes[0].result_binding.request.sources == (source,)
    win.do_fft()
    assert len(calls) == 1


@pytest.mark.parametrize("section", ("fft_time", "order"))
def test_async_candidate_freezes_explicit_request(win, section, monkeypatch):
    _page, state = _prepare(win, section)
    captured = []
    if section == "fft_time":
        monkeypatch.setattr(win._fft_time_coordinator, "request_batch", lambda items: captured.extend(items) or len(items))
        win.do_fft_time()
        context = captured[0]
    else:
        ctx = win.inspector.order_ctx
        ctx.combo_rpm_mode.setCurrentIndex(ctx.combo_rpm_mode.findData("manual"))
        monkeypatch.setattr(win, "_start_order_batch", captured.extend)
        win.do_order_time()
        context = captured[0][1]
    request = context["request_snapshot"]
    assert request.sources == tuple(state.panes[0].sources)
    assert request.revision == state.panes[0].request_revision
    old_window = request.params["window"]
    state.params["window"] = "blackman"
    assert request.params["window"] == old_window


@pytest.mark.parametrize("section", ("fft_time", "order"))
@pytest.mark.parametrize("edited", (False, True))
def test_hidden_completion_binds_only_unedited_request(win, section, edited, monkeypatch):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    bind_result(pane, snapshot_request(state, pane), ("old-applied",))
    captured = []
    if section == "fft_time":
        monkeypatch.setattr(win._fft_time_coordinator, "request_batch", lambda items: captured.extend(items) or len(items))
        win.do_fft_time()
        context = win._fft_time_coordinator._build_context(captured[0])
    else:
        monkeypatch.setattr(win, "_start_order_batch", captured.extend)
        win.do_order_time()
        context = captured[0][1]
    assert context["request_snapshot"].revision == pane.request_revision
    win.analysis_managers[section].new_view(activate=True)
    if edited:
        mark_pending(pane)
        mark_pending(pane)  # returning to the original draft cannot revive it
    result = SimpleNamespace(metadata={"frames": 1}, params=SimpleNamespace(nfft=8))
    if section == "fft_time":
        win._store_analysis_result(section, state.view_id, 0, context["analysis_key"], result)
        win._on_fft_time_render_requested(context, result, False)
    else:
        win._on_order_job_finished(context, result)
    assert pane.result_binding.keys == (("old-applied",) if edited else (context["analysis_key"],))
    assert pane.result_binding.stale is edited
    assert win._analysis_pins[(section, state.view_id, 0)] == set(pane.result_binding.keys)
    assert win.analysis_managers[section].get(win.analysis_managers[section].active).panes[0].result_binding is None


@pytest.mark.parametrize("section", ("fft_time", "order"))
def test_heatmap_explicit_cache_hit_creates_binding_without_job(win, section, monkeypatch):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    fid, channel = pane.sources[0]
    key = win._analysis_cache_key_for_view_source(section, state, pane, 0, fid, channel)
    result = SimpleNamespace(metadata={"frames": 1}, params=SimpleNamespace(nfft=8))
    win.analysis_caches[section].put(key, result)
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *a, **k: pytest.fail("cache hit submitted DSP"))
    monkeypatch.setattr(win, f"_render_{section}_on", lambda *a, **k: None)
    monkeypatch.setattr(win, f"_sync_{section}_effective_facts", lambda *a: None)
    if section == "fft_time":
        win.do_fft_time()
    else:
        win.do_order_time()
    assert pane.result_binding.keys == (key,)
    assert pane.result_binding.request.sources == ((fid, channel),)


@pytest.mark.parametrize("section", ("fft_time", "order"))
def test_async_failure_retains_binding_and_marks_pending(win, section, monkeypatch):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    bind_result(pane, snapshot_request(state, pane), ("old-applied",))
    request = snapshot_request(state, pane)
    ctx = {"view_id": state.view_id, "pane_idx": 0, "pane_token": id(pane), "request_snapshot": request}
    callback = win._on_fft_time_failed if section == "fft_time" else win._on_order_job_failed
    callback(ctx, "computation cancelled")
    assert pane.result_binding.keys == ("old-applied",)
    assert pane.result_binding.stale
    assert pane.request_revision == request.revision + 1


@pytest.mark.parametrize("section", ("fft_time", "order"))
@pytest.mark.parametrize("changed", ("hidden", "edited", "deleted"))
def test_async_failure_does_not_overwrite_unrelated_context(win, section, changed):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    bind_result(pane, snapshot_request(state, pane), ("old-applied",))
    request = snapshot_request(state, pane)
    context = {"view_id": state.view_id, "pane_idx": 0, "pane_token": id(pane), "request_snapshot": request}
    manager = win.analysis_managers[section]
    if changed == "edited":
        mark_pending(pane)
    else:
        manager.new_view(activate=True)
        if changed == "deleted":
            manager.delete_view(manager.views.index(state))
    expected_revision = pane.request_revision + (changed == "hidden")
    win.statusBar.showMessage("Current context")
    callback = win._on_fft_time_failed if section == "fft_time" else win._on_order_job_failed
    callback(context, "Old request failed")
    assert win.statusBar.currentMessage() == "Current context"
    assert pane.result_binding.keys == ("old-applied",)
    assert pane.request_revision == expected_revision


@pytest.mark.parametrize("section", ("fft_time", "order"))
def test_inflight_cancel_keeps_old_result_pending_without_failure_callback(win, section, monkeypatch):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    bind_result(pane, snapshot_request(state, pane), ("old-applied",))
    if section == "fft_time":
        monkeypatch.setattr(win._fft_time_coordinator, "request_batch", lambda items: len(items))
        win.do_fft_time()
    else:
        monkeypatch.setattr(win, "_start_order_batch", lambda jobs: None)
        win.do_order_time()
    win._analysis_jobs.cancel(section)  # service cancels suppress failed callbacks
    assert pane.result_binding.keys == ("old-applied",)
    assert pane.result_binding.stale


@pytest.mark.parametrize("section", ("fft_time", "order"))
def test_heatmap_legacy_single_cache_hit_binds_without_worker(win, section, monkeypatch, qapp):
    _page, state = _prepare(win, section)
    pane = state.panes[0]
    fid, channel = pane.sources[0]
    ctx = win._analysis_ctx(section)
    win._echo_combo_signal(ctx.combo_sig, (fid, channel))
    qapp.processEvents()
    key = win._analysis_cache_key_for_view_source(section, state, pane, 0, fid, channel)
    result = SimpleNamespace(metadata={"frames": 1}, params=SimpleNamespace(nfft=8))
    win.analysis_caches[section].put(key, result)
    pane.sources = []
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *a, **k: pytest.fail("legacy cache hit submitted DSP"))
    monkeypatch.setattr(win, "_render_fft_time_on", lambda *a, **k: None)
    monkeypatch.setattr(win, "_render_order_time", lambda *a, **k: None)
    monkeypatch.setattr(win, f"_sync_{section}_effective_facts", lambda *a: None)
    if section == "fft_time":
        win._do_fft_time_single()
    else:
        win._do_order_time_single()
    assert pane.result_binding.keys == (key,)
    assert pane.result_binding.request.sources == ((fid, channel),)
