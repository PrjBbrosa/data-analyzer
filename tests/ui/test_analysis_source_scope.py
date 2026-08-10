"""Stage 1 analysis View source-scope contracts (spec A1–A15 mapping).

Pure helpers live in ``analysis_source_scope``; projection/close contracts
exercise MainWindow only where live projection must be asserted.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
from mf4_analyzer.ui.view_state import ViewManager, ViewState


def _csv(path, channels=("sig", "rpm", "in", "out")):
    t = np.linspace(0.0, 1.0, 64)
    df = pd.DataFrame({"time": t})
    for name in channels:
        df[name] = np.sin(2 * np.pi * 3 * t)
    df.to_csv(path, index=False)
    return str(path)


# ---------------------------------------------------------------------------
# Pure state / helper contracts (A1, A2, A8, A10 helpers)
# ---------------------------------------------------------------------------


def test_analysis_view_default_attachment_is_explicitly_empty():
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState

    state = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert state.attached_file_ids == []
    payload = state.to_dict()
    assert payload["schema"] == 7
    assert payload["attached_file_ids"] == []
    restored = AnalysisViewState.from_dict(payload)
    assert restored.attached_file_ids == []


def test_schema6_analysis_view_derives_attachment_from_all_pane_roles():
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState

    payload = {
        "schema": 6,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [
            {
                "sources": [["f1", "a"], ["f2", "b"]],
                "rpm_source": ["f3", "rpm"],
            },
            {
                "sources": [["f2", "c"]],
                "input_source": ["f4", "in"],
                "output_source": ["f4", "out"],
            },
        ],
    }
    state = AnalysisViewState.from_dict(payload)
    assert state.attached_file_ids == ["f1", "f2", "f3", "f4"]

    explicit_empty = AnalysisViewState.from_dict({
        "schema": 7,
        "name": "Empty",
        "tab_color": "#2d7ff9",
        "attached_file_ids": [],
        "panes": [{"sources": [["f1", "a"]]}],
    })
    assert explicit_empty.attached_file_ids == []


def test_duplicate_deep_copies_attachment_with_new_view_id():
    manager = ViewManager(state_factory=AnalysisViewState)
    original = manager.get(0)
    original.attached_file_ids = ["f1", "f2"]
    original.panes[0].sources = [("f1", "sig")]
    original_id = original.view_id

    idx = manager.duplicate(0)
    copied = manager.get(idx)
    assert copied.attached_file_ids == ["f1", "f2"]
    assert copied.view_id != original_id
    copied.attached_file_ids.append("f3")
    assert original.attached_file_ids == ["f1", "f2"]


def test_detach_analysis_files_filters_one_view_roles():
    from mf4_analyzer.ui.main_window.analysis_source_scope import (
        detach_analysis_files,
    )

    state = AnalysisViewState(name="FFT", tab_color="#2d7ff9")
    state.attached_file_ids = ["f1", "f2", "f3"]
    state.panes = [
        PaneState(sources=[("f1", "a"), ("f2", "b")]),
        PaneState(
            sources=[("f3", "c")],
            rpm_source=("f2", "rpm"),
            input_source=("f1", "in"),
            output_source=("f1", "out"),
        ),
    ]
    impact = detach_analysis_files(state, ["f2"])
    assert state.attached_file_ids == ["f1", "f3"]
    assert state.panes[0].sources == [("f1", "a")]
    assert state.panes[1].sources == [("f3", "c")]
    assert state.panes[1].rpm_source is None
    # FRF pair: either endpoint matching f1 would clear pair; f2 only hits rpm
    assert state.panes[1].input_source == ("f1", "in")
    assert impact.removed_fids == ["f2"]
    assert impact.cleared_roles


def test_detach_analysis_files_clears_full_frf_pair_when_either_end_matches():
    from mf4_analyzer.ui.main_window.analysis_source_scope import (
        detach_analysis_files,
    )

    state = AnalysisViewState(name="FRF", tab_color="#2d7ff9")
    state.attached_file_ids = ["f1", "f2"]
    state.panes[0].input_source = ("f1", "in")
    state.panes[0].output_source = ("f1", "out")
    detach_analysis_files(state, ["f1"])
    assert state.panes[0].input_source is None
    assert state.panes[0].output_source is None
    assert state.attached_file_ids == ["f2"]


def test_collect_source_uses_indexes_time_and_analysis_roles():
    from mf4_analyzer.ui.main_window.analysis_source_scope import (
        collect_source_uses,
    )

    time_views = [
        ViewState(
            name="T1",
            tab_color="#111",
            attached_file_ids=["f1", "f2"],
            checked=[("f1", "a")],
            view_id="tv1",
        ),
    ]
    fft = ViewManager(state_factory=AnalysisViewState)
    fft.get(0).name = "F1"
    fft.get(0).view_id = "av1"
    fft.get(0).attached_file_ids = ["f1"]
    fft.get(0).panes[0].sources = [("f1", "a"), ("f1", "b")]
    uses = collect_source_uses(
        "f1",
        time_views=time_views,
        analysis_managers={"fft": fft},
    )
    roles = {(u.domain, u.role, u.channel) for u in uses}
    assert ("time", "attachment", None) in roles or any(
        u.domain == "time" and u.role == "attachment" for u in uses
    )
    assert any(u.domain == "fft" and u.role == "signal" for u in uses)


def test_collect_source_uses_indexes_exact_x_without_attachment():
    from mf4_analyzer.ui.main_window.analysis_source_scope import (
        collect_source_uses,
    )
    from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec, EXACT_SOURCE

    time_views = [
        ViewState(
            name="T-exact",
            tab_color="#111",
            attached_file_ids=[],
            checked=[],
            view_id="tv-x",
            axis_opts={
                "x_axis": CustomXAxisSpec(
                    mode="channel",
                    resolver=EXACT_SOURCE,
                    source_fid="f1",
                    channel="xpos",
                    label="xpos",
                ).to_axis_opts(),
            },
        ),
    ]
    uses = collect_source_uses("f1", time_views=time_views)
    assert uses
    assert any(u.role == "x_axis" and u.channel == "xpos" for u in uses)


def test_collect_source_uses_indexes_overlay_and_frf_signature():
    from mf4_analyzer.ui.main_window.analysis_source_scope import (
        collect_source_uses,
    )

    time_views = [
        ViewState(
            name="T-overlay",
            tab_color="#111",
            attached_file_ids=[],
            checked=[],
            view_id="tv-o",
            overlay_primary=("f1", "torque"),
            axis_opts={
                "frf_source_signature": {
                    "input": ["f1", "in"],
                    "output": ["f2", "out"],
                    "effective_time_range": [0.0, 1.0],
                },
            },
        ),
    ]
    uses_f1 = collect_source_uses("f1", time_views=time_views)
    roles_f1 = {u.role for u in uses_f1}
    assert "overlay_primary" in roles_f1
    assert "input" in roles_f1
    uses_f2 = collect_source_uses("f2", time_views=time_views)
    assert any(u.role == "output" and u.channel == "out" for u in uses_f2)


# ---------------------------------------------------------------------------
# Live projection contracts (require product wiring)
# ---------------------------------------------------------------------------


@pytest.fixture
def win_two(qapp, qtbot, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    a = _csv(tmp_path / "a.csv")
    b = _csv(tmp_path / "b.csv")
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(a)
    win._load_one(b)
    fid_a, fid_b = list(win.files)
    return win, fid_a, fid_b


def _picker_fids(ctx):
    combo = ctx.combo_sig
    return [
        combo.itemData(i)[0]
        for i in range(combo.count())
        if combo.itemData(i) is not None
    ]


def test_each_section_picker_uses_its_own_active_view_attachment(win_two):
    win, fid_a, fid_b = win_two
    # Detach from time so legacy time-scoped pickers would go empty / A-only.
    win._detach_files_from_focused_view([fid_b])

    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft_time = win.analysis_managers["fft_time"]
    fft_time.get(0).attached_file_ids = [fid_a]
    order = win.analysis_managers["order"]
    order.get(0).attached_file_ids = [fid_a, fid_b]
    frf = win.analysis_managers["frf"]
    frf.get(0).attached_file_ids = [fid_b]

    win._refresh_analysis_candidates()

    assert set(_picker_fids(win.inspector.fft_ctx)) == {fid_b}
    assert set(_picker_fids(win.inspector.fft_time_ctx)) == {fid_a}
    assert set(_picker_fids(win.inspector.order_ctx)) == {fid_a, fid_b}
    frf_combo = win.inspector.frf_ctx.combo_input
    frf_fids = {
        frf_combo.itemData(i)[0]
        for i in range(frf_combo.count())
        if frf_combo.itemData(i) is not None
    }
    assert frf_fids == {fid_b}


def test_time_view_switch_does_not_change_any_analysis_picker_or_source(win_two):
    win, fid_a, fid_b = win_two
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft.get(0).panes[0].sources = [(fid_b, "sig")]
    win._refresh_analysis_candidates("fft")
    before_picker = _picker_fids(win.inspector.fft_ctx)
    before_sources = copy.deepcopy(fft.get(0).panes[0].sources)

    win._on_view_new()
    win._attach_files_to_focused_view([fid_a])
    win._switch_view(0)

    assert _picker_fids(win.inspector.fft_ctx) == before_picker
    assert fft.get(0).panes[0].sources == before_sources


def test_fft_projection_never_writes_time_view_checked(win_two):
    win, fid_a, fid_b = win_two
    time_state = win.view_manager.get(0)
    time_state.checked = [(fid_a, "sig")]
    win._project_view_controls(0)

    win.chart_stack.set_mode("fft")
    win.navigator.set_projection_role("fft_sources")
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_a, fid_b]
    win._refresh_analysis_candidates("fft")
    win.navigator.set_checked_channels([(fid_b, "sig")])
    # Route checkbox change through the same handler production uses.
    if hasattr(win, "_ch_changed"):
        win._ch_changed()

    assert time_state.checked == [(fid_a, "sig")]
    assert (fid_b, "sig") in [
        tuple(s) for s in fft.get(0).panes[0].sources
    ] or win.navigator.get_checked_channels()


def test_new_view_is_empty_in_fft_fft_time_frf_and_order(win_two):
    win, fid_a, _fid_b = win_two
    for section in ("fft", "fft_time", "frf", "order"):
        mgr = win.analysis_managers[section]
        mgr.get(0).attached_file_ids = [fid_a]
        mgr.get(0).panes[0].sources = [(fid_a, "sig")]
        mgr.get(0).params = {"nfft": 9999}
        win._on_analysis_new(section)
        state = mgr.get(mgr.active)
        assert state.attached_file_ids == [], section
        assert state.panes[0].sources == [], section
        assert state.panes[0].input_source is None, section
        assert state.panes[0].output_source is None, section
        assert state.panes[0].rpm_source is None, section


def test_mode_switch_applies_target_active_view_before_capture(win_two, qtbot):
    win, fid_a, fid_b = win_two
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft.get(0).panes[0].sources = [(fid_b, "sig")]
    fft.get(0).params = {"nfft": 2048, "nfft_mode": "fixed"}

    # Poison live Inspector with a different NFFT while still in time mode.
    win.inspector.fft_ctx.apply_params({"nfft": 512, "nfft_mode": "fixed"})
    assert win.inspector.fft_ctx.get_params().get("nfft") == 512

    win._on_mode_changed("fft")
    qtbot.waitUntil(
        lambda: win.chart_stack.current_mode() == "fft"
        and win.inspector.fft_ctx.get_params().get("nfft") == 2048,
        timeout=1000,
    )

    assert win.navigator.get_attached_file_ids() == [fid_b]
    assert set(_picker_fids(win.inspector.fft_ctx)) == {fid_b}
    live_nfft = win.inspector.fft_ctx.get_params().get("nfft")
    state_nfft = fft.get(0).params.get("nfft")
    assert live_nfft == 2048
    assert state_nfft == 2048


def test_local_analysis_detach_clears_active_fft_canvas(win_two, monkeypatch, qtbot):
    win, fid_a, fid_b = win_two
    monkeypatch.setattr(win, "_confirm_analysis_detach", lambda *a, **k: True)
    win.chart_stack.set_mode("fft")
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft.get(0).panes[0].sources = [(fid_b, "sig")]
    win._project_analysis_attachments("fft", fft.get(0))
    win.navigator.set_checked_channels([(fid_b, "sig")])
    win.do_fft()
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert canvas.has_result()

    win._detach_files_from_active_context([fid_b], label="b.csv")
    qtbot.wait(20)
    assert fid_b not in fft.get(0).attached_file_ids
    assert fft.get(0).panes[0].sources == []
    assert canvas.has_result() is False


def test_local_analysis_detach_does_not_touch_sibling_or_other_section(
    win_two, monkeypatch,
):
    win, fid_a, fid_b = win_two
    monkeypatch.setattr(win, "_confirm_analysis_detach", lambda *a, **k: True)
    fft = win.analysis_managers["fft"]
    fft.new_view()
    v0, v1 = fft.get(0), fft.get(1)
    v0.attached_file_ids = [fid_a, fid_b]
    v0.panes[0].sources = [(fid_b, "sig")]
    v1.attached_file_ids = [fid_a, fid_b]
    v1.panes[0].sources = [(fid_b, "sig")]
    order = win.analysis_managers["order"]
    order.get(0).attached_file_ids = [fid_b]
    order.get(0).panes[0].sources = [(fid_b, "sig")]
    sibling_before = copy.deepcopy(v1.to_dict())
    order_before = copy.deepcopy(order.get(0).to_dict())

    fft.set_active(0)
    win.chart_stack.set_mode("fft")
    win._detach_files_from_active_context([fid_b], label="b.csv")

    assert fid_b not in v0.attached_file_ids
    assert v1.to_dict() == sibling_before
    assert order.get(0).to_dict() == order_before


def test_local_detach_does_not_invalidate_shared_fid_cache(win_two, monkeypatch):
    win, fid_a, fid_b = win_two
    called = []

    def _boom(fid):
        called.append(fid)

    monkeypatch.setattr(win, "_invalidate_all_analysis_caches_for_fid", _boom)
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_a, fid_b]
    win.chart_stack.set_mode("fft")
    win._detach_files_from_active_context([fid_b], label="b.csv")
    assert called == []


def test_global_close_with_dependencies_defaults_to_cancel(win_two, monkeypatch):
    win, fid_a, fid_b = win_two
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft.get(0).panes[0].sources = [(fid_b, "sig")]

    monkeypatch.setattr(
        win,
        "_confirm_global_file_close",
        lambda *a, **k: False,
    )
    win._close(fid_b)
    assert fid_b in win.files
    assert fft.get(0).attached_file_ids == [fid_b]
    assert fft.get(0).panes[0].sources == [(fid_b, "sig")]


def test_global_close_defaults_cancel_for_exact_x_only_dependency(
    win_two, monkeypatch,
):
    from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec, EXACT_SOURCE

    win, fid_a, fid_b = win_two
    # No attachment / checked / analysis refs — only exact custom X.
    time_state = win.view_manager.get(0)
    time_state.attached_file_ids = [fid_a]
    time_state.checked = [(fid_a, "sig")]
    time_state.axis_opts = {
        "x_axis": CustomXAxisSpec(
            mode="channel",
            resolver=EXACT_SOURCE,
            source_fid=fid_b,
            channel="sig",
            label="sig",
        ).to_axis_opts(),
    }
    confirms = []

    def _confirm(uses, **kwargs):
        confirms.append(list(uses))
        return False

    monkeypatch.setattr(win, "_confirm_global_file_close", _confirm)
    win._close(fid_b)
    assert fid_b in win.files
    assert confirms and any(u.role == "x_axis" for u in confirms[0])
    assert time_state.axis_opts["x_axis"]["fid"] == fid_b


def test_close_files_group_is_atomic_on_cancel_and_confirm(win_two, monkeypatch):
    win, fid_a, fid_b = win_two
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_a]
    fft.get(0).panes[0].sources = [(fid_a, "sig")]
    confirms = []

    def _confirm(uses, **kwargs):
        confirms.append((list(uses), kwargs.get("files")))
        return False

    monkeypatch.setattr(win, "_confirm_global_file_close", _confirm)
    win._close_files([fid_a, fid_b])
    assert fid_a in win.files and fid_b in win.files
    assert len(confirms) == 1
    assert set(confirms[0][1]) == {fid_a, fid_b}

    confirms.clear()
    monkeypatch.setattr(
        win,
        "_confirm_global_file_close",
        lambda uses, **kwargs: confirms.append(kwargs.get("files")) or True,
    )
    win._close_files([fid_a, fid_b])
    assert fid_a not in win.files and fid_b not in win.files
    assert len(confirms) == 1


def test_close_files_group_emits_one_aggregated_toast_and_reset(
    win_two, monkeypatch,
):
    """A 2-fid physical-file group must surface one summary, not N.

    Regression coverage for the group-close feedback fan-out: before the
    fix, ``_close_files`` looped over ``_close`` unchanged and each call
    fired its own toast + statusBar + full plot-state reset.
    """
    win, fid_a, fid_b = win_two
    monkeypatch.setattr(win, "_confirm_global_file_close", lambda *a, **k: True)
    toasts = []
    monkeypatch.setattr(
        win, "toast", lambda msg, level="info": toasts.append((msg, level))
    )
    resets = []
    orig_reset = win._reset_plot_state

    def _tracked_reset(*a, **k):
        resets.append((a, k))
        return orig_reset(*a, **k)

    monkeypatch.setattr(win, "_reset_plot_state", _tracked_reset)

    win._close_files([fid_a, fid_b])

    assert fid_a not in win.files and fid_b not in win.files
    close_toasts = [t for t in toasts if t[0].startswith("已关闭")]
    assert len(close_toasts) == 1
    msg, level = close_toasts[0]
    assert "2" in msg and "个来源" in msg
    assert level == "info"
    assert len(resets) == 1
    assert win.statusBar.currentMessage() == "已关闭 2 个来源 | 剩余 0 文件"


def test_close_files_single_member_group_keeps_itemized_toast(
    win_two, monkeypatch,
):
    """The navigator routes even an ordinary (non-grouped) file's own close
    button through ``_close_files`` with a 1-fid list. That common case must
    keep ``_close``'s itemized, filename-bearing toast rather than the
    group summary wording."""
    win, fid_a, fid_b = win_two
    name_a = win.files[fid_a].short_name
    monkeypatch.setattr(win, "_confirm_global_file_close", lambda *a, **k: True)
    toasts = []
    monkeypatch.setattr(
        win, "toast", lambda msg, level="info": toasts.append((msg, level))
    )
    resets = []
    orig_reset = win._reset_plot_state

    def _tracked_reset(*a, **k):
        resets.append((a, k))
        return orig_reset(*a, **k)

    monkeypatch.setattr(win, "_reset_plot_state", _tracked_reset)

    win._close_files([fid_a])

    assert fid_a not in win.files and fid_b in win.files
    close_toasts = [t for t in toasts if t[0].startswith("已关闭")]
    assert len(close_toasts) == 1
    assert close_toasts[0] == (f"已关闭 {name_a}", "info")
    assert len(resets) == 1
    assert win.statusBar.currentMessage() == f"已关闭 | 剩余 {len(win.files)} 文件"


def test_explicit_global_cascade_cleans_every_reference_and_cache(
    win_two, monkeypatch,
):
    win, fid_a, fid_b = win_two
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [fid_b]
    fft.get(0).panes[0].sources = [(fid_b, "sig")]
    invalidated = []

    monkeypatch.setattr(
        win,
        "_confirm_global_file_close",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        win,
        "_invalidate_all_analysis_caches_for_fid",
        lambda fid: invalidated.append(fid),
    )
    win._close(fid_b)
    assert fid_b not in win.files
    assert fid_b not in fft.get(0).attached_file_ids
    assert fft.get(0).panes[0].sources == []
    assert invalidated == [fid_b]


def test_project_missing_source_blocks_overwrite_save_by_default(
    win_two, tmp_path, monkeypatch,
):
    win, _fid_a, _fid_b = win_two
    path = tmp_path / "degraded.tlproj"
    win._project_path = str(path)
    health = getattr(win, "_project_restore_health", None)
    assert health is not None
    health.degraded = True
    health.dropped_analysis_refs = [("fft", "vid", 0, "signal")]

    monkeypatch.setattr(
        win,
        "_confirm_degraded_project_save",
        lambda *a, **k: False,
    )
    saved = []
    monkeypatch.setattr(
        win,
        "_write_project_document",
        lambda *a, **k: saved.append(True),
    )
    result = win.save_project(path)
    assert result is False
    assert saved == []
    assert health.degraded is True
