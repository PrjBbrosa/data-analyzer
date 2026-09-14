"""T0 freeze: current section-entry side effects, not the T1–T3 optimizations.

These snapshots lock today's capture / projection / preview / history / dirty
contracts so later presentation work cannot skip ``plot_time()`` or
``_apply_active_analysis_context()`` without a failing assertion. They do not
implement retained-canvas reveal, progress-pump narrowing, or prepared-input
reuse.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PyQt5 import sip

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import window as window_mod
from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs

from tests.ui.test_analysis_multiview_integration import (
    _check_speed_in_both,
    _seed_active_analysis_attachments,
)


# ---------------------------------------------------------------------------
# Fixtures / tiny copies (do not pytest_plugins the integration module)
# ---------------------------------------------------------------------------

@pytest.fixture
def two_file_win(qapp, loaded_csv, tmp_path, qtbot):
    """MainWindow with two loaded CSV files (same channel names)."""
    import pandas as pd

    t = np.linspace(0, 1.0, 1000)
    df2 = pd.DataFrame({
        "time": t,
        "speed": 800 * np.sin(2 * np.pi * 7 * t),
        "torque": 40 + 3 * np.cos(2 * np.pi * 4 * t),
    })
    p2 = tmp_path / "sample2.csv"
    df2.to_csv(p2, index=False)

    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(loaded_csv)
    win._load_one(str(p2))
    assert len(win.files) == 2
    return win


def _flush(qapp, rounds=8):
    """Drain 0 ms mode-entry timers without treating sleep as settle proof."""
    for _ in range(int(rounds)):
        qapp.processEvents()


def _switch(win, qapp, mode):
    win.toolbar._set_mode(mode)
    _flush(qapp)
    return win.chart_stack.current_mode()


def _pair(value):
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return (str(value[0]), str(value[1]))
    return (str(value),)


def _finite_pair(value):
    if value is None:
        return None
    try:
        lo, hi = value
    except (TypeError, ValueError):
        return None
    lo, hi = float(lo), float(hi)
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None
    return (lo, hi)


def _approx_range(value, places=6):
    pair = _finite_pair(value)
    if pair is None:
        return None
    return (round(pair[0], places), round(pair[1], places))


def _array_digest(values):
    arr = np.asarray(values)
    if arr.size == 0:
        return {"n": 0, "min": None, "max": None, "head": None, "tail": None}
    finite = arr[np.isfinite(arr)]
    return {
        "n": int(arr.size),
        "min": None if finite.size == 0 else float(finite.min()),
        "max": None if finite.size == 0 else float(finite.max()),
        "head": float(arr.flat[0]) if np.isfinite(arr.flat[0]) else None,
        "tail": float(arr.flat[-1]) if np.isfinite(arr.flat[-1]) else None,
    }


def _curve_snapshot(curve):
    entry = getattr(curve, "_spectrum_entry", None) or {}
    try:
        x, y = curve.getData()
    except Exception:
        x = getattr(curve, "xData", None)
        y = getattr(curve, "yData", None)
    color = None
    try:
        color = curve.opts["pen"].color().name()
    except Exception:
        pass
    return {
        "source": _pair((entry.get("fid"), entry.get("channel")))
        if entry.get("fid") is not None else None,
        "label_is_not_key": True,
        "id": id(curve),
        "color": color,
        "x": _array_digest(x if x is not None else []),
        "y": _array_digest(y if y is not None else []),
    }


def _time_curve_snapshot(canvas):
    rows = []
    lines = getattr(canvas, "_channel_lines", None)
    if lines is None or not hasattr(lines, "composite_items"):
        return rows
    for ck, _label, payload in lines.composite_items():
        handle, line = payload if isinstance(payload, tuple) else (None, payload)
        pdi = getattr(line, "plot_data_item", None) or line
        x = y = None
        try:
            x, y = pdi.getData()
        except Exception:
            pass
        rows.append({
            "source": ck,
            "x": _array_digest(x if x is not None else []),
            "y": _array_digest(y if y is not None else []),
        })
    return rows


def _history_capability(card):
    toolbar = getattr(card, "toolbar", None)
    if toolbar is None:
        return {"can_back": False, "can_forward": False, "stack_len": 0, "pointer": 0}
    stack = list(getattr(toolbar, "_view_stack", []) or [])
    pointer = int(getattr(toolbar, "_view_pointer", 0) or 0)
    return {
        "can_back": pointer > 0,
        "can_forward": pointer < max(0, len(stack) - 1),
        "stack_len": len(stack),
        "pointer": pointer,
    }


def _quality_pending(canvas):
    status = {}
    getter = getattr(canvas, "quality_status", None)
    if callable(getter):
        try:
            status = dict(getter() or {})
        except Exception:
            status = {}
    pending = False
    settle = getattr(canvas, "_aa_settle_pending", None)
    if callable(settle):
        try:
            pending = bool(settle())
        except Exception:
            pending = False
    return {
        "pending": pending,
        "state": status.get("state"),
        "block_reason": status.get("block_reason"),
    }


def _ultraview_refs(win):
    uv = getattr(win, "_ultraview", None)
    if uv is None:
        return {"current": None, "bound": []}
    current = getattr(uv, "_sync_current_ref", None)
    bound = []
    binder = getattr(uv, "bound_ref_for", None)
    canvases = [getattr(win, "canvas_time", None)]
    page = getattr(getattr(win, "chart_stack", None), "page_fft", None)
    if page is not None:
        for idx in range(int(getattr(page, "pane_count", lambda: 0)())):
            canvases.append(page.pane_canvas(idx))
    for canvas in canvases:
        if canvas is None or not callable(binder):
            continue
        try:
            ref = binder(canvas)
        except Exception:
            ref = None
        if ref is None:
            continue
        bound.append({
            "section": getattr(ref, "section", None),
            "view_id": getattr(ref, "view_id", None),
        })
    return {
        "current": None if current is None else {
            "section": getattr(current, "section", None),
            "view_id": getattr(current, "view_id", None),
        },
        "bound": bound,
    }


def _job_pending(win):
    jobs = getattr(win, "_analysis_jobs", None)
    if jobs is None:
        return {}
    out = {}
    for section in ("fft", "fft_time", "order", "frf", "restore"):
        try:
            out[section] = {
                "busy": bool(jobs.is_busy(section)),
                "running": bool(jobs.is_running(section)),
                "progress_token": jobs.progress_token(section) is not None,
            }
        except Exception:
            out[section] = {"busy": False, "running": False, "progress_token": False}
    return out


def _pin_snapshot(win):
    pins = getattr(win, "_analysis_pins", None)
    if pins is None:
        return []
    rows = []
    for (section, view_id, pane_idx), keys in sorted(
        getattr(pins, "_slots", {}).items(),
        key=lambda item: (item[0][0], item[0][2]),
    ):
        rows.append({
            "section": section,
            "pane_idx": int(pane_idx),
            "n_keys": len(keys),
            "key_fids": sorted({str(key[0]) for key in keys if isinstance(key, tuple) and key}),
        })
    return rows


def _pane_snapshot(pane):
    return {
        "sources": [_pair(src) for src in list(pane.sources or [])],
        "time_range": _approx_range(pane.time_range),
        "xlim": _approx_range(pane.xlim),
        "ylim": _approx_range(pane.ylim),
        "viewport_origin": dict(pane.viewport_origin or {}),
        "cursor_mode": pane.cursor_mode,
        "cursor_placement": pane.cursor_placement,
    }


def _fft_canvas_snapshot(canvas):
    amp = [_curve_snapshot(curve) for curve in list(getattr(canvas, "_amp_curves", []) or [])]
    preview = [_curve_snapshot(curve) for curve in list(getattr(canvas, "_time_curves", []) or [])]
    viewport = None
    capture = getattr(canvas, "capture_xy_viewport", None)
    if callable(capture):
        try:
            viewport = capture()
        except Exception:
            viewport = None
    cursor = {
        "mode": canvas.cursor_mode() if hasattr(canvas, "cursor_mode") else None,
        "placement": canvas.snapshot_cursor_placement()
        if hasattr(canvas, "snapshot_cursor_placement") else None,
    }
    return {
        "has_result": bool(getattr(canvas, "has_result", lambda: False)()),
        "stale": bool(getattr(canvas, "is_spectrum_stale", lambda: False)()),
        "amp": amp,
        "preview": preview,
        "viewport": None if viewport is None else (
            _approx_range(viewport[0]), _approx_range(viewport[1])
        ),
        "cursor": cursor,
        "quality": _quality_pending(canvas),
        "curve_ids": [row["id"] for row in amp],
    }


def _time_canvas_snapshot(canvas):
    if canvas is None:
        return None
    return {
        "xlim": _approx_range(
            canvas.get_visible_xlim() if hasattr(canvas, "get_visible_xlim") else None
        ),
        "curves": _time_curve_snapshot(canvas),
        "quality": _quality_pending(canvas),
        "cursor_mode": getattr(canvas, "cursor_mode", lambda: None)()
        if callable(getattr(canvas, "cursor_mode", None)) else None,
    }


def _cache_hits(win, section, state):
    cache = win.analysis_caches.get(section)
    if cache is None or state is None:
        return []
    rows = []
    for pane_idx, pane in enumerate(state.panes):
        for fid, ch in pane.sources:
            key = win._analysis_cache_key(section, fid, ch, pane_idx=pane_idx)
            result = cache.get(key)
            nfft = None
            length = None
            facts = getattr(result, "effective", None) if result is not None else None
            if result is not None:
                freq = result[0] if isinstance(result, tuple) else None
                if freq is not None:
                    length = int(np.asarray(freq).size)
                if facts is not None:
                    nfft = getattr(facts, "nfft", None)
            rows.append({
                "source": _pair((fid, ch)),
                "pane_idx": pane_idx,
                "hit": result is not None,
                "nfft": nfft,
                "result_length": length,
            })
    return rows


def presentation_snapshot(win):
    """Comparable section-entry snapshot. Excludes timings, animation geometry,
    and the current toolbar Section identity. Source identity stays composite.
    """
    stack = win.chart_stack
    time_views = []
    for idx, state in enumerate(win.view_manager.views):
        time_views.append({
            "index": idx,
            "attached": list(state.attached_file_ids),
            "checked": [_pair(item) for item in list(state.checked or [])],
            "xlim": _approx_range(state.xlim),
            "cursor_mode": state.cursor_mode,
            "overlay_primary": _pair(state.overlay_primary),
        })
    analysis = {}
    for section, mgr in win.analysis_managers.items():
        views = []
        for state in mgr.views:
            views.append({
                "attached": list(state.attached_file_ids),
                "params": dict(state.params or {}),
                "compare": dict(state.compare or {}),
                "panes": [_pane_snapshot(pane) for pane in state.panes],
            })
        analysis[section] = {
            "active": mgr.active,
            "views": views,
        }
    fft_page = stack.page_fft
    fft_canvases = [
        _fft_canvas_snapshot(fft_page.pane_canvas(idx))
        for idx in range(fft_page.pane_count())
    ]
    fft_state = None
    if win.analysis_managers["fft"].views:
        fft_state = win.analysis_managers["fft"].get(
            win.analysis_managers["fft"].active
        )
    ctx = win.inspector.fft_ctx
    navigator_checked = [
        _pair((fid, ch)) for fid, ch, *_rest in win.navigator.get_checked_channels()
    ]
    colors = {
        json.dumps(list(_pair(key)), ensure_ascii=False): value
        for key, value in (win.navigator.get_channel_colors() or {}).items()
    }
    units = {}
    for fid, fd in win.files.items():
        for name, unit in (getattr(fd, "channel_units", None) or {}).items():
            units[json.dumps([str(fid), str(name)], ensure_ascii=False)] = unit
    fft_card = fft_page._cards[0] if fft_page.pane_count() else None
    time_card = getattr(stack, "_time_card", None)
    draft = None
    if fft_state is not None:
        ctrl = win._analysis_context.time_range
        raw = ctrl.draft_for("fft", fft_state.view_id, 0)
        if raw is not None:
            draft = {
                "range": _approx_range(raw.range),
                "valid": bool(raw.valid),
                "origin": getattr(raw, "origin", None),
            }
    facts = {
        "text": ctx.effective_facts_text() if hasattr(ctx, "effective_facts_text") else "",
        "stale": bool(ctx.effective_facts_is_stale())
        if hasattr(ctx, "effective_facts_is_stale") else False,
    }
    return {
        "time_views": time_views,
        "analysis": analysis,
        "time_canvas": _time_canvas_snapshot(getattr(win, "canvas_time", None)),
        "time_secondary": _time_canvas_snapshot(stack.secondary_canvas())
        if stack.split_active() else None,
        "fft_canvases": fft_canvases,
        "fft_live_params": dict(ctx.current_params()),
        "fft_cache": _cache_hits(win, "fft", fft_state),
        "navigator_checked": navigator_checked,
        "channel_colors": colors,
        "channel_units": units,
        "range_enabled": bool(win.inspector.top.range_enabled()),
        "range_values": _approx_range(
            win.inspector.top.range_values()
            if win.inspector.top.range_enabled() else None
        ),
        "range_draft": draft,
        "diagnostics": facts,
        "pins": _pin_snapshot(win),
        "jobs": _job_pending(win),
        "dirty": bool(win._project_session_is_dirty()),
        "ultraview": _ultraview_refs(win),
        "history": {
            "time": _history_capability(time_card),
            "fft": _history_capability(fft_card),
        },
        "restore_pending": sorted(
            (section, str(view_id))
            for section, view_id in getattr(win, "_analysis_restore_pending", set())
        ),
        "fft_signature_hit": (
            win._fft_last_render_sig == win._fft_render_signature()
            if getattr(win, "_fft_last_render_sig", None) is not None
            else None
        ),
    }


def _assert_history_still_walks(card, canvas, axis="amp"):
    toolbar = card.toolbar
    before = _history_capability(card)
    assert before["stack_len"] >= 1
    if not before["can_back"]:
        return before
    if axis == "amp":
        vb = canvas._plot_amp.vb
    else:
        vb = canvas._plot_time.vb
    now = tuple(vb.viewRange()[0])
    toolbar.back()
    back = tuple(vb.viewRange()[0])
    assert back != pytest.approx(now, abs=1e-6)
    assert _history_capability(card)["can_forward"]
    toolbar.forward()
    assert tuple(vb.viewRange()[0]) == pytest.approx(now, abs=1e-6)
    return _history_capability(card)


def _seed_time_zoom(win, qapp, xlim=(0.20, 0.55)):
    fid = list(win.files.keys())[0]
    win.navigator.set_checked_channels([(fid, "speed")])
    qapp.processEvents()
    win.plot_time()
    _flush(qapp)
    win.canvas_time.restore_visible_xlim(xlim)
    _flush(qapp)
    win._capture_focused_view()
    card = win.chart_stack._time_card
    card.toolbar.rebind_history_capture()
    card.toolbar._commit_pending_view()
    return fid


def _spy_submits(win, monkeypatch):
    submitted = []
    original = win._analysis_jobs.submit_batch

    def spy(section, jobs, *, replace=False):
        submitted.append((section, len(list(jobs)), replace))
        return original(section, jobs, replace=replace)

    monkeypatch.setattr(win._analysis_jobs, "submit_batch", spy)
    return submitted


# ---------------------------------------------------------------------------
# 1. Zoomed time-domain ↔ FFT round trip
# ---------------------------------------------------------------------------

def test_zoomed_time_fft_round_trip_preserves_manual_ranges_and_origin(
    two_file_win, qapp
):
    win = two_file_win
    _seed_time_zoom(win, qapp, xlim=(0.20, 0.55))
    time_xlim = _approx_range(win.canvas_time.get_visible_xlim())
    assert time_xlim == pytest.approx((0.20, 0.55), abs=1e-3)

    _switch(win, qapp, "fft")
    _seed_active_analysis_attachments(win)
    _check_speed_in_both(win)
    win.do_fft()
    _flush(qapp)
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert canvas.has_result()
    canvas._plot_amp.setXRange(40.0, 120.0, padding=0)
    canvas._emit_viewport_intent()
    _flush(qapp)
    fft_viewport = canvas.capture_xy_viewport()
    fft_state = win.analysis_managers["fft"].get(0)
    origin_before = dict(fft_state.panes[0].viewport_origin)
    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute
    before = presentation_snapshot(win)

    _switch(win, qapp, "time")
    assert _approx_range(win.canvas_time.get_visible_xlim()) == pytest.approx(
        time_xlim, abs=1e-3
    )
    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)

    # Time↔FFT currently reprojects the navigator, so curve *objects* may
    # rebuild from cache. Freeze ranges/origin/cache/no-compute, not identity.
    assert canvas.has_result()
    assert compute_calls["n"] == 0
    restored = canvas.capture_xy_viewport()
    assert restored is not None
    assert restored[0] == pytest.approx(fft_viewport[0], abs=1e-3)
    assert fft_state.panes[0].viewport_origin == origin_before
    assert after["jobs"]["fft"]["busy"] is False
    assert after["time_canvas"]["xlim"] == pytest.approx(time_xlim, abs=1e-3)
    assert all(row["hit"] for row in after["fft_cache"]) or all(
        row["hit"] for row in before["fft_cache"]
    )


# ---------------------------------------------------------------------------
# 2. Dual pane, different sources and ranges
# ---------------------------------------------------------------------------

def test_fft_dual_pane_round_trip_preserves_both_panes(two_file_win, qapp):
    win = two_file_win
    _switch(win, qapp, "fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.10, 0.30)
    state.panes[1].sources = [(fids[1], "speed")]
    state.panes[1].time_range = (0.60, 0.90)
    win._apply_active_analysis_context("fft")
    win.do_fft()
    _flush(qapp)

    page = win.chart_stack.page_fft
    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    assert c0.has_result() and c1.has_result()
    c0._plot_amp.setXRange(10.0, 40.0, padding=0)
    c0._emit_viewport_intent()
    c1._plot_amp.setXRange(50.0, 90.0, padding=0)
    c1._emit_viewport_intent()
    _flush(qapp)
    v0 = c0.capture_xy_viewport()
    v1 = c1.capture_xy_viewport()
    ids0 = list(c0._amp_curves)
    ids1 = list(c1._amp_curves)
    before = presentation_snapshot(win)

    _switch(win, qapp, "time")
    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)

    state = mgr.get(mgr.active)
    assert [_pair(src) for src in state.panes[0].sources] == [(str(fids[0]), "speed")]
    assert [_pair(src) for src in state.panes[1].sources] == [(str(fids[1]), "speed")]
    assert _approx_range(state.panes[0].time_range) == pytest.approx((0.10, 0.30), abs=1e-6)
    assert _approx_range(state.panes[1].time_range) == pytest.approx((0.60, 0.90), abs=1e-6)
    assert c0._amp_curves == ids0
    assert c1._amp_curves == ids1
    assert c0.capture_xy_viewport()[0] == pytest.approx(v0[0], abs=1e-3)
    assert c1.capture_xy_viewport()[0] == pytest.approx(v1[0], abs=1e-3)
    assert after["fft_canvases"][0]["has_result"] is True
    assert after["fft_canvases"][1]["has_result"] is True
    assert after["analysis"]["fft"]["views"][0]["panes"][0]["sources"] != (
        after["analysis"]["fft"]["views"][0]["panes"][1]["sources"]
    )
    assert before["fft_canvases"][0]["curve_ids"] == after["fft_canvases"][0]["curve_ids"]
    assert before["fft_canvases"][1]["curve_ids"] == after["fft_canvases"][1]["curve_ids"]


# ---------------------------------------------------------------------------
# 3. Global color / unit / data change while away
# ---------------------------------------------------------------------------

def test_global_color_unit_data_change_while_away_is_snapshot_stable(
    two_file_win, qapp
):
    win = two_file_win
    _switch(win, qapp, "fft")
    _check_speed_in_both(win)
    win.do_fft()
    _flush(qapp)
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    n_curves = len(canvas._amp_curves)
    fids = list(win.files.keys())
    fid = fids[0]
    original = np.asarray(win.files[fid].data["speed"].to_numpy(copy=True))
    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute

    _switch(win, qapp, "time")
    win.navigator.set_channel_colors({(fid, "speed"): "#ff00aa"})
    win.files[fid].channel_units["speed"] = "N·m"
    win.files[fid].data["speed"] = win.files[fid].data["speed"] + 12.5
    _flush(qapp)

    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)
    assert after["channel_colors"][json.dumps([str(fid), "speed"])] == "#ff00aa"
    assert after["channel_units"][json.dumps([str(fid), "speed"])] == "N·m"
    assert canvas.has_result()
    assert len(canvas._amp_curves) == n_curves
    assert compute_calls["n"] == 0
    mutated = np.asarray(win.files[fid].data["speed"].to_numpy(copy=False))
    assert mutated.shape == original.shape
    assert not np.allclose(mutated, original)
    assert after["jobs"]["fft"]["busy"] is False
    # Time re-entry currently rebuilds FFT from cache; new pens follow navigator.
    returned_colors = {
        curve.opts["pen"].color().name() for curve in canvas._amp_curves
    }
    assert "#ff00aa" in returned_colors


# ---------------------------------------------------------------------------
# 4. Uncomputed preview: no compute submit
# ---------------------------------------------------------------------------

def test_uncomputed_preview_round_trip_does_not_submit_compute(
    two_file_win, qapp, monkeypatch
):
    win = two_file_win
    submitted = _spy_submits(win, monkeypatch)
    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute

    _switch(win, qapp, "fft")
    _seed_active_analysis_attachments(win)
    win.navigator.set_checked_channels([])
    qapp.processEvents()
    win.inspector.fft_ctx.combo_sig.setCurrentIndex(0)
    _flush(qapp)
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert canvas.has_result() is False
    assert len(canvas._amp_curves) == 0
    assert len(canvas._time_curves) == 1
    before = presentation_snapshot(win)

    _switch(win, qapp, "order")
    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)

    assert submitted == []
    assert compute_calls["n"] == 0
    assert after["fft_canvases"][0]["has_result"] is False
    assert after["fft_canvases"][0]["stale"] is False
    assert len(canvas._time_curves) == 1
    assert after["jobs"]["fft"]["busy"] is False
    assert after["analysis"]["fft"]["views"][0]["attached"] == (
        before["analysis"]["fft"]["views"][0]["attached"]
    )


# ---------------------------------------------------------------------------
# 5. Follow-prefs empty View
# ---------------------------------------------------------------------------

def test_follow_prefs_empty_view_on_and_off(two_file_win, qapp):
    win = two_file_win
    fid = list(win.files.keys())[0]
    fft = win.analysis_managers["fft"]
    assert fft.get(0).attached_file_ids == []

    win.navigator.set_follow_prefs(FollowPrefs(False, False, False))
    _switch(win, qapp, "fft")
    off_snap = presentation_snapshot(win)
    assert off_snap["analysis"]["fft"]["views"][0]["attached"] == []

    _switch(win, qapp, "time")
    win.navigator.set_follow_prefs(FollowPrefs(False, False, True))
    _switch(win, qapp, "fft")
    on_snap = presentation_snapshot(win)
    assert fid in on_snap["analysis"]["fft"]["views"][0]["attached"]

    fft.get(0).attached_file_ids = [fid]
    _switch(win, qapp, "time")
    _switch(win, qapp, "fft")
    assert fft.get(0).attached_file_ids == [fid]


# ---------------------------------------------------------------------------
# 6. Range draft vs committed range
# ---------------------------------------------------------------------------

def test_uncommitted_range_draft_is_distinct_from_committed_pane_range(
    two_file_win, qapp
):
    win = two_file_win
    _switch(win, qapp, "fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    pane.sources = [(fids[0], "speed")]
    assert pane.time_range is None
    signature = win._analysis_source_signature_for_pane("fft", pane, state)
    ctrl = win._analysis_context.time_range
    ctrl.apply_user_edit("fft", state.view_id, 0, (0.20, 0.40), signature)
    top = win.inspector.top
    top._mark_user_range_edit("start", "0.15")
    top._mark_user_range_edit("end", "0.45")
    query = top.query_range_edit()
    assert query.status != "unchanged"
    draft_before = ctrl.draft_for("fft", state.view_id, 0)
    assert draft_before is not None
    assert draft_before.range == pytest.approx((0.20, 0.40))
    committed_before = pane.time_range

    _switch(win, qapp, "time")
    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    draft_after = ctrl.draft_for("fft", state.view_id, 0)
    # Current leave-capture: range checkbox stays off, so pane.time_range is
    # not committed, and both the inspector in-progress edit and the
    # controller draft are dropped. Freeze that split so later work cannot
    # silently promote a draft into a committed range.
    assert committed_before is None
    assert pane.time_range is None
    assert draft_after is None
    assert after["range_draft"] is None
    assert top.query_range_edit().status == "unchanged"


# ---------------------------------------------------------------------------
# 7. Switch during project restore
# ---------------------------------------------------------------------------

def test_section_switch_during_project_restore_keeps_token_and_does_not_steal_capture(
    two_file_win, qapp
):
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.navigator.set_checked_channels([(fid, "speed")])
    win.plot_time()
    _flush(qapp)
    win._capture_focused_view()
    time_state = win.view_manager.get(win.view_manager.active)
    checked_before = [_pair(item) for item in list(time_state.checked or [])]
    fft = win.analysis_managers["fft"]
    restore_token = object()
    win._analysis_jobs.set_progress_token("restore", restore_token)
    win._analysis_restore_pending.add(("fft", fft.get(0).view_id))
    win._opening_project = True
    win._restoring_project = True

    stolen = []
    real_capture = win._capture_focused_view

    def capturing():
        stolen.append(True)
        return real_capture()

    win._capture_focused_view = capturing
    begun = win._begin_compute_progress("FFT 计算中")
    assert begun is restore_token
    _switch(win, qapp, "fft")
    assert fft.get(0).attached_file_ids == []
    _switch(win, qapp, "time")

    win._opening_project = False
    win._restoring_project = False
    after = presentation_snapshot(win)
    time_state = win.view_manager.get(win.view_manager.active)
    assert stolen == []
    assert [_pair(item) for item in list(time_state.checked or [])] == checked_before
    assert win._restore_progress_token() is restore_token
    assert ("fft", fft.get(0).view_id) in {
        (section, view_id) for section, view_id in win._analysis_restore_pending
    }
    assert after["jobs"]["restore"]["progress_token"] is True
    win._analysis_jobs.clear_progress_token("restore")
    win._analysis_restore_pending.clear()


# ---------------------------------------------------------------------------
# 8. Rapid time → fft → order → time
# ---------------------------------------------------------------------------

def test_rapid_time_fft_order_time_final_mode_and_view_identity_win(
    two_file_win, qapp
):
    win = two_file_win
    fid = _seed_time_zoom(win, qapp)
    time_id = win.view_manager.get(win.view_manager.active).view_id
    fft_id = win.analysis_managers["fft"].get(0).view_id
    order_id = win.analysis_managers["order"].get(0).view_id
    time_xlim = _approx_range(win.canvas_time.get_visible_xlim())

    win.toolbar._set_mode("fft")
    win.toolbar._set_mode("order")
    win.toolbar._set_mode("time")
    _flush(qapp)

    assert win.chart_stack.current_mode() == "time"
    assert win.view_manager.get(win.view_manager.active).view_id == time_id
    assert win.analysis_managers["fft"].get(0).view_id == fft_id
    assert win.analysis_managers["order"].get(0).view_id == order_id
    assert _approx_range(win.canvas_time.get_visible_xlim()) == pytest.approx(
        time_xlim, abs=1e-3
    )
    after = presentation_snapshot(win)
    assert [row for row in after["time_views"] if row["index"] == 0][0]["checked"]
    assert (str(fid), "speed") in after["navigator_checked"]
    assert after["jobs"]["fft"]["busy"] is False
    assert after["jobs"]["order"]["busy"] is False


# ---------------------------------------------------------------------------
# 9. Close while a deferred callback is still pending
# ---------------------------------------------------------------------------

def test_close_while_deferred_section_callback_pending_does_not_mutate_destroyed(
    two_file_win, qapp, monkeypatch
):
    win = two_file_win
    _seed_time_zoom(win, qapp)
    pending = []
    real_single_shot = window_mod.QTimer.singleShot

    def capturing_single_shot(msec, *args):
        fn = args[0] if args else None
        if int(msec) == 0 and callable(fn):
            pending.append(fn)
            return None
        return real_single_shot(msec, *args)

    monkeypatch.setattr(window_mod.QTimer, "singleShot", capturing_single_shot)
    win.toolbar._set_mode("fft")
    assert pending, "mode entry must post a 0 ms callback"

    mutated = []
    real_enter = win._enter_fft_mode

    def guarded_enter():
        if sip.isdeleted(win):
            mutated.append("deleted-window")
            return None
        return real_enter()

    win._enter_fft_mode = guarded_enter
    win._project_dirty.mark_saved()
    win.close()
    errors = []
    for fn in list(pending):
        try:
            fn()
        except RuntimeError as exc:
            errors.append(exc)
    _flush(qapp)
    assert errors == []
    assert "deleted-window" not in mutated


def test_fft_history_survives_section_round_trip(two_file_win, qapp):
    win = two_file_win
    _switch(win, qapp, "fft")
    _check_speed_in_both(win)
    win.do_fft()
    _flush(qapp)
    page = win.chart_stack.page_fft
    canvas = page.pane_canvas(0)
    card = page._cards[0]
    card.toolbar.rebind_history_capture()
    canvas._plot_amp.setXRange(20.0, 80.0, padding=0)
    canvas._emit_viewport_intent()
    card.toolbar._commit_pending_view()
    assert _history_capability(card)["can_back"] is True
    before = presentation_snapshot(win)

    # Order does not reproject the time navigator, so this is the retained
    # FFT canvas path that T1 must keep history-walkable.
    _switch(win, qapp, "order")
    _switch(win, qapp, "fft")
    after = presentation_snapshot(win)
    assert after["history"]["fft"]["can_back"] is True
    _assert_history_still_walks(card, canvas, axis="amp")
    assert canvas.has_result()
    assert after["fft_canvases"][0]["has_result"] is True
    assert after["dirty"] == before["dirty"]
    assert after["pins"] == before["pins"]
    assert after["ultraview"]["current"] == before["ultraview"]["current"]


def test_time_section_entry_still_invokes_preserving_xlim(two_file_win, qapp):
    win = two_file_win
    _seed_time_zoom(win, qapp)
    _switch(win, qapp, "fft")
    calls = []
    original = win._plot_time_preserving_xlim

    def spy(**kwargs):
        calls.append("plot")
        return original(**kwargs)

    win._plot_time_preserving_xlim = spy
    _switch(win, qapp, "time")
    assert calls == ["plot"]


def test_warm_fft_round_trip_does_not_submit_jobs(two_file_win, qapp, monkeypatch):
    win = two_file_win
    submitted = _spy_submits(win, monkeypatch)
    _switch(win, qapp, "fft")
    _check_speed_in_both(win)
    win.do_fft()
    _flush(qapp)
    submitted.clear()
    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute
    _switch(win, qapp, "order")
    _switch(win, qapp, "fft")
    assert submitted == []
    assert compute_calls["n"] == 0
    snap = presentation_snapshot(win)
    assert snap["jobs"]["fft"]["busy"] is False
    assert all(row["hit"] for row in snap["fft_cache"])
    assert all(row["result_length"] not in (None, 0) for row in snap["fft_cache"])
    # Result length is read from the cached frequency axis, not inferred
    # from the 1000-sample input CSV.
    for row in snap["fft_cache"]:
        assert row["result_length"] != 1000
