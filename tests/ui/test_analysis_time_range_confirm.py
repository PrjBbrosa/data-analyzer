"""Compute-time confirm when an unchecked local time-range draft is set."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.ui.main_window import MainWindow


def _win_with_extent(qtbot, hi=10.0):
    win = MainWindow()
    qtbot.addWidget(win)
    win.files = {
        "fid": SimpleNamespace(time_array=np.array([0.0, float(hi)], dtype=float)),
    }
    win.chart_stack.set_mode("fft")
    win.inspector.set_mode("fft")
    return win


def test_draft_is_local_when_unchecked_subset(qapp, qtbot):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    assert win._analysis_time_range_draft_is_local() == pytest.approx((2.0, 4.0))


def test_draft_is_none_when_checked_or_full_extent(qapp, qtbot):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top

    top.set_range_values(2.0, 4.0)
    top.chk_range.setChecked(True)
    assert win._analysis_time_range_draft_is_local() is None

    top.chk_range.setChecked(False)
    top.set_range_values(0.0, 10.0)
    assert win._analysis_time_range_draft_is_local() is None

    top.set_range_values(0.05, 9.95)  # within 1% of span=10
    assert win._analysis_time_range_draft_is_local() is None


def test_offer_local_arms_checkbox(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    asked = []

    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi: asked.append((lo, hi)) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == [(2.0, 4.0)]
    assert top.range_enabled() is True
    assert top.range_values() == pytest.approx((2.0, 4.0))


def test_offer_full_keeps_unchecked(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda lo, hi: "full")
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((2.0, 4.0))


def test_offer_cancel_aborts(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda lo, hi: "cancel")
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert top.range_enabled() is False


def test_offer_skips_dialog_when_already_checked(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.set_range_from_span(2.0, 4.0)
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda lo, hi: asked.append((lo, hi)) or "local",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == []


def test_do_fft_cancel_skips_capture(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda lo, hi: "cancel")
    captured = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda section: captured.append(section),
    )
    win.do_fft()
    assert captured == []


def test_do_fft_local_choice_captures_pane_time_range(qapp, qtbot, monkeypatch):
    win = _win_with_extent(qtbot, hi=10.0)
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(2.0, 4.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda lo, hi: "local")

    # Stop after capture — do not run the real FFT compute path.
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
    win = _win_with_extent(qtbot, hi=10.0)
    win.chart_stack.set_mode("frf")
    win.inspector.set_mode("frf")
    top = win.inspector.top
    top.chk_range.setChecked(False)
    top.set_range_values(1.0, 3.0)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda lo, hi: "cancel")
    captured = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda section: captured.append(section),
    )
    assert win.do_frf() is False
    assert captured == []
