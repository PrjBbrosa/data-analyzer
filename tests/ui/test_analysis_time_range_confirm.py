"""Compute-time confirm: real drafts, aggregated preflight, atomic commit."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui.main_window import MainWindow


def _emit_spin_text_edited(spin, text=None):
    edit = spin.lineEdit()
    if edit is None:
        return
    if text is not None:
        edit.setText(text)
    edit.textEdited.emit(edit.text())


def _user_commit_range(top, lo, hi):
    """Typed start/end commit. ``set_range_values`` is not a user draft."""
    top.chk_range.setChecked(False)
    top.spin_start.setValue(float(lo))
    top.spin_end.setValue(float(hi))
    _emit_spin_text_edited(top.spin_start)
    _emit_spin_text_edited(top.spin_end)
    return top.flush_pending_range_edit(emit=True)


def _user_type_invalid_minus(top):
    top.set_range_limits(-100.0, 100.0)
    top.chk_range.setChecked(False)
    _emit_spin_text_edited(top.spin_start, "-")
    assert not top.spin_start.hasAcceptableInput()


def _register_span(win, name, duration, *, n=None, channel="sig"):
    count = n if n is not None else max(int(duration * 10) + 1, 2)
    time = np.linspace(0.0, float(duration), count)
    frame = pd.DataFrame({channel: np.sin(time)})
    before = set(win.files)
    fd = win._register_file_data(
        f"{name}.csv",
        frame,
        [channel],
        {},
        fs=float(count - 1) / float(duration),
    )
    fd.time_array = time
    fid = next(item for item in win.files if item not in before)
    return fid, time


def _enter_fft(win, fids):
    win.toolbar._set_mode("fft")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("fft", list(fids))
    mgr = win.analysis_managers["fft"]
    win._project_analysis_attachments("fft", mgr.get(mgr.active))


def _tick_fft_sources(win, keys):
    win.navigator.set_checked_channels(list(keys))
    win._ch_changed()


def _fft_ready_win(qtbot, hi=10.0, n=101):
    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_span(win, "src", hi, n=n)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    return win, fid


def _split_fft_panes(win, fid, *, pane1_source=None):
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    source = (fid, "sig")
    state.panes[0].sources = [source]
    state.panes[1].sources = [pane1_source or source]
    state.panes[0].time_range = None
    state.panes[1].time_range = None
    win._capture_analysis_sources = lambda *args, **kwargs: None
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    return state, page


def test_draft_is_local_when_unchecked_subset(qapp, qtbot):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    top.set_range_values(0.0, 10.0)
    assert win._analysis_time_range_draft_is_local() is None

    _user_commit_range(top, 2.0, 4.0)
    assert win._analysis_time_range_draft_is_local() == pytest.approx((2.0, 4.0))


def test_programmatic_set_range_values_does_not_prompt(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append((a, k)) or "local",
    )
    assert win._analysis_time_range_draft_is_local() is None
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == []


def test_draft_is_none_when_checked_or_full_extent(qapp, qtbot):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top

    top.set_range_from_span(2.0, 4.0)
    assert win._analysis_time_range_draft_is_local() is None

    top.chk_range.setChecked(False)
    top.set_range_values(0.0, 10.0)
    assert win._analysis_time_range_draft_is_local() is None

    # Retired 1% plotted-extent heuristic: a quiet spin rewrite is not a draft.
    top.set_range_values(0.05, 9.95)
    assert win._analysis_time_range_draft_is_local() is None

    _user_commit_range(top, 0.0, 10.0)
    assert win._analysis_time_range_draft_is_local() is None


def test_offer_local_arms_checkbox(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    asked = []

    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: asked.append((lo, hi, conflicts)) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked[0][0] == pytest.approx(2.0)
    assert asked[0][1] == pytest.approx(4.0)
    assert asked[0][2][0]["kind"] == "draft"
    assert top.range_enabled() is True
    assert top.range_values() == pytest.approx((2.0, 4.0))
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range == pytest.approx((2.0, 4.0))
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_offer_full_keeps_unchecked(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((0.0, 10.0))
    assert state.panes[0].time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None

    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append(True) or "cancel",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == []


def test_offer_cancel_aborts(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "cancel")
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((2.0, 4.0))
    assert state.panes[0].time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ).range == pytest.approx((2.0, 4.0))


def test_offer_skips_dialog_when_already_checked(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    top.set_range_from_span(2.0, 4.0)
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append((a, k)) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == []


def test_do_fft_cancel_skips_capture(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "cancel")
    captured = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda section: captured.append(section),
    )
    win.do_fft()
    assert captured == []


def test_do_fft_local_choice_captures_pane_time_range(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")

    def _capture(section):
        mgr = win.analysis_managers[section]
        state = mgr.get(mgr.active)
        win._capture_analysis_time_range(section, state)
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(win, "_capture_active_analysis_view", _capture)
    with pytest.raises(RuntimeError, match="stop-after-capture"):
        win.do_fft()

    assert top.range_enabled() is True
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range == pytest.approx((2.0, 4.0))


def test_do_frf_cancel_returns_false(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    win.chart_stack.set_mode("frf")
    win.inspector.set_mode("frf")
    top = win.inspector.top
    _user_commit_range(top, 1.0, 3.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "cancel")
    captured = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda section: captured.append(section),
    )
    assert win.do_frf() is False
    assert captured == []


def test_invalid_draft_does_not_normalize_and_proceed(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    signature = win._analysis_source_signature_for_pane("fft", pane, state)
    win._analysis_context.time_range.apply_user_edit(
        "fft", state.view_id, 0, (5.0, 1.0), signature
    )
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert pane.time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None

    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert pane.time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 10.0))


def test_multi_pane_cancel_submits_zero_jobs(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    state, page = _split_fft_panes(win, fid)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    win._analysis_context.time_range.apply_user_edit(
        "fft", state.view_id, 1, (3.0, 4.0), sig1
    )
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: asked.append(conflicts) or "cancel",
    )
    computed = []
    stored = []
    monkeypatch.setattr(
        win, "_fft_compute_arrays", lambda *a, **k: computed.append(1)
    )
    monkeypatch.setattr(
        win, "_store_analysis_result", lambda *a, **k: stored.append(1)
    )
    win.do_fft()
    assert len(asked) == 1
    assert {item["pane_idx"] for item in asked[0]} == {0, 1}
    assert computed == []
    assert stored == []
    assert state.panes[0].time_range is None
    assert state.panes[1].time_range is None
    assert list(win.analysis_caches["fft"]._store) == []


def test_source_change_during_confirm_does_not_commit(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    other, _time = _register_span(win, "other", 12.0, n=121)
    _enter_fft(win, [fid, other])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None

    def _change_then_local(*_a, **_k):
        _tick_fft_sources(win, [(other, "sig")])
        return "local"

    monkeypatch.setattr(win, "_ask_use_local_time_range", _change_then_local)
    captured = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda section: captured.append(section),
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert captured == []
    assert state.panes[0].time_range is None


def test_unfocused_pane_does_not_read_shared_spinbox(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    state, page = _split_fft_panes(win, fid)
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    win._analysis_context.time_range.apply_user_edit(
        "fft", state.view_id, 1, (3.0, 4.0), sig1
    )
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert state.panes[0].time_range == pytest.approx((1.0, 2.0))
    assert state.panes[1].time_range == pytest.approx((3.0, 4.0))
    assert win._pane_time_range_for("fft", 0) == pytest.approx((1.0, 2.0))
    assert win._pane_time_range_for("fft", 1) == pytest.approx((3.0, 4.0))
    assert win.inspector.top.range_values() == pytest.approx((1.0, 2.0))
    assert win.inspector.top.range_enabled() is True


def test_local_choice_only_touches_conflicting_panes(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    state, page = _split_fft_panes(win, fid)
    state.panes[1].time_range = (0.5, 0.8)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    win._analysis_context.time_range.note_enabled(
        "fft", state.view_id, 1, (0.5, 0.8), sig1
    )
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert state.panes[0].time_range == pytest.approx((1.0, 2.0))
    assert state.panes[1].time_range == pytest.approx((0.5, 0.8))


def test_needs_review_full_clears_enabled_adjust_keeps_it(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    other, _time = _register_span(win, "short", 4.0, n=41)
    _enter_fft(win, [fid, other])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win.inspector.top.set_range_from_span(6.0, 9.0)
    win._capture_analysis_time_range("fft", state, pane_idx=0)
    _tick_fft_sources(win, [(other, "sig")])
    intent = win._analysis_context.time_range.intent_for(
        "fft", state.view_id, 0, enabled_range=state.panes[0].time_range,
    )
    assert intent.needs_review is True
    assert state.panes[0].time_range == pytest.approx((6.0, 9.0))

    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: asked.append(conflicts) or "adjust",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert asked[0][0]["kind"] == "review"
    assert state.panes[0].time_range == pytest.approx((6.0, 9.0))

    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert state.panes[0].time_range is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 4.0))


def test_ask_dialog_defaults_to_cancel_and_full_is_not_destructive(
    qapp, qtbot, monkeypatch
):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    recorded = {}

    def fake_exec(box):
        recorded["text"] = box.text()
        recorded["default"] = box.defaultButton().text()
        recorded["roles"] = {
            button.text(): box.buttonRole(button) for button in box.buttons()
        }
        recorded["enabled"] = {
            button.text(): button.isEnabled() for button in box.buttons()
        }
        box.defaultButton().click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    choice = win._ask_use_local_time_range(
        2.0,
        4.0,
        [
            {
                "pane_idx": 0,
                "kind": "draft",
                "range": (2.0, 4.0),
                "display_range": (0.0, 10.0),
            }
        ],
    )
    assert choice == "cancel"
    assert "你调整了时间范围为 2–4 秒，但尚未启用" in recorded["text"]
    assert recorded["default"] == "取消"
    assert recorded["roles"]["用选定范围"] == QMessageBox.AcceptRole
    assert recorded["roles"]["用全时段"] != QMessageBox.DestructiveRole
    assert recorded["roles"]["取消"] == QMessageBox.RejectRole
    assert recorded["enabled"]["用选定范围"] is True


def test_ask_dialog_disables_local_for_invalid_draft(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    recorded = {}

    def fake_exec(box):
        recorded["enabled"] = {
            button.text(): button.isEnabled() for button in box.buttons()
        }
        recorded["labels"] = [button.text() for button in box.buttons()]
        box.defaultButton().click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    win._ask_use_local_time_range(
        5.0,
        1.0,
        [
            {
                "pane_idx": 0,
                "kind": "invalid_draft",
                "range": (5.0, 1.0),
                "display_range": (0.0, 10.0),
            }
        ],
    )
    assert recorded["enabled"]["用选定范围"] is False
    assert "用全时段" in recorded["labels"]
    assert "取消" in recorded["labels"]


def test_ask_review_dialog_copy_and_buttons(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot, hi=10.0)
    recorded = {}

    def fake_exec(box):
        recorded["text"] = box.text()
        recorded["labels"] = [button.text() for button in box.buttons()]
        recorded["default"] = box.defaultButton().text()
        recorded["roles"] = {
            button.text(): box.buttonRole(button) for button in box.buttons()
        }
        box.defaultButton().click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    choice = win._ask_use_local_time_range(
        6.0,
        9.0,
        [
            {
                "pane_idx": 0,
                "kind": "review",
                "range": (6.0, 9.0),
                "display_range": (0.0, 4.0),
            }
        ],
    )
    assert choice == "cancel"
    assert "使用新来源全时段" in recorded["labels"]
    assert "返回调整" in recorded["labels"]
    assert "取消" in recorded["labels"]
    assert recorded["default"] == "取消"
    assert recorded["roles"]["使用新来源全时段"] != QMessageBox.DestructiveRole


def test_restore_recompute_ignores_draft_and_blocks_invalid_enabled(
    qapp, qtbot, monkeypatch
):
    win, fid = _fft_ready_win(qtbot, hi=10.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append(True) or "local",
    )
    computed = []
    monkeypatch.setattr(
        win, "_fft_compute_arrays", lambda *a, **k: computed.append("ran")
    )
    state.panes[0].time_range = (0.0, 0.0)
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append(msg))
    win._recompute_restored_fft_view(state.view_id)
    assert asked == []
    assert computed == []
    assert any("时间范围" in msg for msg in toasts)
    assert state.panes[0].time_range == (0.0, 0.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None


def test_fft_time_job_omitted_range_uses_pane_not_shared_draft(
    qapp, qtbot, monkeypatch
):
    win, fid = _fft_ready_win(qtbot, hi=1.0, n=1000)
    win.toolbar._set_mode("fft_time")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("fft_time", [fid])
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft_time", True)
    state.panes[0].sources = [(fid, "sig")]
    state.panes[1].sources = [(fid, "sig")]
    _user_commit_range(win.inspector.top, 0.20, 0.30)
    seen = []

    from mf4_analyzer.signal import spectrogram as spectrogram_mod

    class DummyResult:
        pass

    def fake_compute(
        sig,
        time,
        params,
        channel_name="",
        unit="",
        progress_callback=None,
        cancel_token=None,
    ):
        seen.append((len(sig), float(time[0]), float(time[-1])))
        return DummyResult()

    class DummyProgress:
        def emit(self, *args):
            pass

    class DummyWorker:
        progress = DummyProgress()

        @staticmethod
        def cancelled():
            return False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    job, _ctx = win._build_fft_time_job(
        1, fid, "sig", win.inspector.fft_time_ctx.get_params(),
    )
    assert job(DummyWorker()) is not None
    full_t = np.asarray(win.files[fid].time_array, dtype=float)
    full_sig = np.asarray(win.files[fid].data["sig"].to_numpy(copy=False), dtype=float)
    assert seen[-1] == pytest.approx(
        (len(full_sig), float(full_t[0]), float(full_t[-1]))
    )

    state.panes[1].time_range = (0.75, 1.0)
    job, _ctx = win._build_fft_time_job(
        1, fid, "sig", win.inspector.fft_time_ctx.get_params(),
    )
    assert job(DummyWorker()) is not None
    mask = (full_t >= 0.75) & (full_t <= 1.0)
    assert seen[-1] == pytest.approx(
        (int(mask.sum()), float(full_t[mask][0]), float(full_t[mask][-1]))
    )


# -- T2 coverage / multi-pane transaction (A03/A04) --------------------------

def test_outside_source_draft_cannot_be_offered_as_valid_local(
    qapp, qtbot, monkeypatch,
):
    """Migrated review probe + A03: 0–10 source, 20–30 draft is not local."""
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    top.set_range_limits(-100.0, 100.0)
    _user_commit_range(top, 20.0, 30.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    seen = []

    def choose(lo, hi, conflicts):
        seen.extend(conflicts)
        return "local"

    monkeypatch.setattr(win, "_ask_use_local_time_range", choose)
    allowed = win._offer_analysis_time_range_before_compute("fft")
    assert allowed is False, seen
    assert state.panes[0].time_range is None
    assert seen
    assert all(item.get("kind") != "draft" for item in seen)
    assert any(item.get("kind") == "uncovered_draft" for item in seen)
    draft = win._analysis_context.time_range.draft_for("fft", state.view_id, 0)
    assert draft is not None
    assert draft.range == pytest.approx((20.0, 30.0))


def test_outside_source_draft_full_and_cancel(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    top.set_range_limits(-100.0, 100.0)
    _user_commit_range(top, 20.0, 30.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "cancel")
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert state.panes[0].time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ).range == pytest.approx((20.0, 30.0))

    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert state.panes[0].time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None
    assert top.range_enabled() is False


def test_partial_overflow_draft_cannot_be_offered_as_valid_local(
    qapp, qtbot, monkeypatch,
):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    top.set_range_limits(-100.0, 100.0)
    _user_commit_range(top, 5.0, 15.0)
    seen = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: seen.extend(conflicts or ()) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert seen
    assert any(item.get("kind") == "uncovered_draft" for item in seen)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range is None


def test_fft_overlay_envelope_does_not_make_shared_local_valid(
    qapp, qtbot, monkeypatch,
):
    win, fid_a = _fft_ready_win(qtbot, hi=10.0)
    fid_b, _time = _register_span(win, "high", 10.0, n=101)
    win.files[fid_b].time_array = np.linspace(20.0, 30.0, 101)
    _enter_fft(win, [fid_a, fid_b])
    _tick_fft_sources(win, [(fid_a, "sig"), (fid_b, "sig")])
    top = win.inspector.top
    top.set_range_limits(-100.0, 100.0)
    _user_commit_range(top, 8.0, 22.0)
    seen = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: seen.extend(conflicts or ()) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert any(item.get("kind") == "uncovered_draft" for item in seen)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range is None


def test_uncovered_draft_checkbox_does_not_enable(qapp, qtbot):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    top.set_range_limits(-100.0, 100.0)
    _user_commit_range(top, 20.0, 30.0)
    top.chk_range.setChecked(True)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range is None
    assert top.range_enabled() is False
    draft = win._analysis_context.time_range.draft_for("fft", state.view_id, 0)
    assert draft is not None
    assert draft.range == pytest.approx((20.0, 30.0))


def test_fft_overlay_checkbox_does_not_write_uncovered_envelope(qapp, qtbot):
    win, fid_a = _fft_ready_win(qtbot, hi=10.0)
    fid_b, _time = _register_span(win, "high", 10.0, n=101)
    win.files[fid_b].time_array = np.linspace(20.0, 30.0, 101)
    _enter_fft(win, [fid_a, fid_b])
    _tick_fft_sources(win, [(fid_a, "sig"), (fid_b, "sig")])
    top = win.inspector.top
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None
    top.chk_range.setChecked(True)
    assert state.panes[0].time_range is None
    assert top.range_enabled() is False


def test_two_pane_second_invalid_writes_neither(qapp, qtbot):
    win, fid = _fft_ready_win(qtbot)
    state, _page = _split_fft_panes(win, fid)
    sig0 = win._analysis_source_signature_for_pane("fft", state.panes[0], state)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    ok = win._commit_analysis_time_range_choice(
        "fft",
        state,
        [
            {
                "pane_idx": 0,
                "kind": "draft",
                "range": (1.0, 2.0),
                "display_range": (0.0, 10.0),
                "signature": sig0,
            },
            {
                "pane_idx": 1,
                "kind": "draft",
                "range": (8.0, 2.0),
                "display_range": (0.0, 10.0),
                "signature": sig1,
            },
        ],
        "local",
    )
    assert ok is False
    assert state.panes[0].time_range is None
    assert state.panes[1].time_range is None


def test_two_pane_second_uncovered_writes_neither(qapp, qtbot):
    win, fid = _fft_ready_win(qtbot)
    state, _page = _split_fft_panes(win, fid)
    sig0 = win._analysis_source_signature_for_pane("fft", state.panes[0], state)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    ok = win._commit_analysis_time_range_choice(
        "fft",
        state,
        [
            {
                "pane_idx": 0,
                "kind": "draft",
                "range": (1.0, 2.0),
                "display_range": (0.0, 10.0),
                "signature": sig0,
            },
            {
                "pane_idx": 1,
                "kind": "draft",
                "range": (20.0, 30.0),
                "display_range": (0.0, 10.0),
                "signature": sig1,
            },
        ],
        "local",
    )
    assert ok is False
    assert state.panes[0].time_range is None
    assert state.panes[1].time_range is None


def test_two_pane_offer_mixed_local_writes_neither(qapp, qtbot, monkeypatch):
    win, fid = _fft_ready_win(qtbot)
    state, page = _split_fft_panes(win, fid)
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    win._analysis_context.time_range.apply_user_edit(
        "fft", state.view_id, 1, (20.0, 30.0), sig1
    )
    seen = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi, conflicts=None: seen.extend(conflicts or ()) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert state.panes[0].time_range is None
    assert state.panes[1].time_range is None
    assert {item["pane_idx"] for item in seen} == {0, 1}


def test_two_pane_source_change_during_dialog_writes_neither(
    qapp, qtbot, monkeypatch,
):
    win, fid = _fft_ready_win(qtbot)
    other, _time = _register_span(win, "other", 12.0, n=121)
    _enter_fft(win, [fid, other])
    state, page = _split_fft_panes(win, fid)
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    sig1 = win._analysis_source_signature_for_pane("fft", state.panes[1], state)
    win._analysis_context.time_range.apply_user_edit(
        "fft", state.view_id, 1, (3.0, 4.0), sig1
    )

    def _change_then_local(*_a, **_k):
        state.panes[1].sources = [(other, "sig")]
        return "local"

    monkeypatch.setattr(win, "_ask_use_local_time_range", _change_then_local)
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert state.panes[0].time_range is None
    assert state.panes[1].time_range is None


def test_ask_dialog_disables_local_for_uncovered_draft(qapp, qtbot, monkeypatch):
    win, _fid = _fft_ready_win(qtbot)
    recorded = {}

    def fake_exec(box):
        recorded["text"] = box.text()
        recorded["enabled"] = {
            button.text(): button.isEnabled() for button in box.buttons()
        }
        box.defaultButton().click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    win._ask_use_local_time_range(
        20.0,
        30.0,
        [
            {
                "pane_idx": 0,
                "kind": "uncovered_draft",
                "range": (20.0, 30.0),
                "display_range": (0.0, 10.0),
                "errors": ("source ('src', 'sig') does not cover requested range",),
            }
        ],
    )
    assert recorded["enabled"]["用选定范围"] is False
    assert "20–30" in recorded["text"] or "20-30" in recorded["text"]


# -- T1 migrated review probes (real user text / checkbox / capture) ---------

def test_real_user_edit_updates_draft_status(qapp, qtbot):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    _user_commit_range(top, 2.0, 4.0)
    assert top.range_intent_status_text() == "范围已调整，尚未启用"
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    draft = win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    )
    assert draft is not None
    assert draft.range == pytest.approx((2.0, 4.0))


def test_invalid_draft_checkbox_must_not_replace_it_with_full(qapp, qtbot):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    _user_commit_range(top, 8.0, 2.0)
    top.chk_range.setChecked(True)
    state = win.analysis_managers["fft"].get(
        win.analysis_managers["fft"].active
    )
    assert state.panes[0].time_range != (0.0, 10.0)
    assert state.panes[0].time_range is None
    assert top.range_enabled() is False
    draft = win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    )
    assert draft is not None
    assert draft.valid is False
    assert top.range_intent_status_text() == "范围无效，无法用于计算"


@pytest.mark.parametrize(
    "sequence",
    ("focus_out_then_compute", "compute_direct", "return_then_compute"),
)
def test_intermediate_invalid_text_is_not_silently_full(
    qapp, qtbot, monkeypatch, sequence,
):
    win, _fid = _fft_ready_win(qtbot)
    top = win.inspector.top
    _user_type_invalid_minus(top)
    if sequence == "focus_out_then_compute":
        top.spin_start.editingFinished.emit()
    elif sequence == "return_then_compute":
        top.spin_start.editingFinished.emit()
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append((a, k)) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is False
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert state.panes[0].time_range is None
    draft = win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    )
    assert draft is not None
    assert draft.valid is False
    assert "-" in top.spin_start.lineEdit().text()
    assert not top.spin_start.hasAcceptableInput()
    if sequence != "compute_direct":
        assert asked  # dialog may run; local must not proceed


def test_enabled_full_precision_survives_no_edit_capture(qapp, qtbot):
    win, fid = _fft_ready_win(qtbot, hi=10.00049)
    top = win.inspector.top
    top.chk_range.setChecked(True)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    before = state.panes[0].time_range
    assert before is not None
    assert before[1] == pytest.approx(10.00049)
    win._capture_analysis_time_range("fft", state)
    assert state.panes[0].time_range == before
    time_axis = np.asarray(win.files[fid].time_array, dtype=float)
    lo, hi = state.panes[0].time_range
    kept = time_axis[(time_axis >= lo) & (time_axis <= hi)]
    assert kept.size
    assert float(kept[-1]) == pytest.approx(float(time_axis[-1]))
