"""Task 2: deferred analysis chart construction (explicit ensure, no idle preload)."""
from __future__ import annotations

import pytest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.analysis_section_page import (
    AnalysisPageReadiness,
    AnalysisSectionPage,
)
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.view_state import ViewManager


def _make_manager():
    return ViewManager(state_factory=AnalysisViewState)


class _CountingCard:
    """Minimal card whose canvas class instances are countable via monkeypatch."""

    def __new__(cls, canvas_cls):
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = canvas_cls(w)
        w._chart_mode = "fft"
        w._focus_marker_color = None
        w.toolbar = None

        def set_focus_marker(color):
            w._focus_marker_color = color

        w.set_focus_marker = set_focus_marker
        return w


@pytest.fixture
def analysis_canvas_counters(monkeypatch):
    """Count analysis canvas constructions (line / heatmap / frf)."""
    counts = {"line": 0, "heatmap": 0, "frf": 0}
    line_init = PgLineCanvas.__init__
    heat_init = PgHeatmapCanvas.__init__
    frf_init = PgFrfCanvas.__init__

    def _line(self, *args, **kwargs):
        counts["line"] += 1
        return line_init(self, *args, **kwargs)

    def _heat(self, *args, **kwargs):
        counts["heatmap"] += 1
        return heat_init(self, *args, **kwargs)

    def _frf(self, *args, **kwargs):
        counts["frf"] += 1
        return frf_init(self, *args, **kwargs)

    monkeypatch.setattr(PgLineCanvas, "__init__", _line)
    monkeypatch.setattr(PgHeatmapCanvas, "__init__", _heat)
    monkeypatch.setattr(PgFrfCanvas, "__init__", _frf)
    return counts


def _analysis_total(counts):
    return counts["line"] + counts["heatmap"] + counts["frf"]


def test_analysis_section_page_defaults_to_eager(qapp):
    builds = {"n": 0}

    def factory():
        builds["n"] += 1
        return _CountingCard(PgLineCanvas)

    page = AnalysisSectionPage(
        section="fft", manager=_make_manager(), card_factory=factory,
    )
    assert page.readiness() == AnalysisPageReadiness.READY
    assert page.pane_count() == 1
    assert builds["n"] == 1
    assert page.pane_canvas(0) is not None
    page.deleteLater()


def test_deferred_page_container_exists_without_chart(qapp):
    builds = {"n": 0}

    def factory():
        builds["n"] += 1
        return _CountingCard(PgLineCanvas)

    page = AnalysisSectionPage(
        section="fft",
        manager=_make_manager(),
        card_factory=factory,
        defer_charts=True,
    )
    assert page.readiness() == AnalysisPageReadiness.UNINITIALIZED
    assert page.pane_count() == 0
    assert page.peek_pane_canvas(0) is None
    assert page.peek_cards() == []
    assert builds["n"] == 0
    assert page.tabbar is not None
    assert page.manager is not None
    page.deleteLater()


def test_deferred_page_ensure_ready_builds_once(qapp):
    builds = {"n": 0}

    def factory():
        builds["n"] += 1
        return _CountingCard(PgLineCanvas)

    page = AnalysisSectionPage(
        section="fft",
        manager=_make_manager(),
        card_factory=factory,
        defer_charts=True,
    )
    page.ensure_ready()
    assert page.readiness() == AnalysisPageReadiness.READY
    assert page.pane_count() == 1
    assert builds["n"] == 1
    canvas = page.pane_canvas(0)
    page.ensure_ready()
    assert builds["n"] == 1
    assert page.pane_canvas(0) is canvas
    page.deleteLater()


def test_chart_stack_defaults_eager_analysis_charts(qapp, analysis_canvas_counters):
    cs = ChartStack()
    assert _analysis_total(analysis_canvas_counters) == 4  # fft+fft_time+frf+order
    assert cs.page_fft.readiness() == AnalysisPageReadiness.READY
    assert cs.canvas_fft is not None
    cs.deleteLater()


def test_chart_stack_deferred_creates_zero_analysis_canvases(
    qapp, analysis_canvas_counters,
):
    cs = ChartStack(defer_analysis_charts=True)
    assert _analysis_total(analysis_canvas_counters) == 0
    for page in (cs.page_fft, cs.page_fft_time, cs.page_frf, cs.page_order):
        assert page.readiness() == AnalysisPageReadiness.UNINITIALIZED
        assert page.pane_count() == 0
        assert page.peek_pane_canvas(0) is None
    assert cs.peek_analysis_canvas("fft") is None
    cs.deleteLater()


def test_chart_stack_ensure_builds_and_binds_once(qapp, analysis_canvas_counters):
    cs = ChartStack(defer_analysis_charts=True)
    assert _analysis_total(analysis_canvas_counters) == 0
    cs.ensure_analysis_page_ready("fft")
    assert analysis_canvas_counters["line"] == 1
    assert cs.page_fft.readiness() == AnalysisPageReadiness.READY
    first = cs.canvas_fft
    cs.ensure_analysis_page_ready("fft")
    assert analysis_canvas_counters["line"] == 1
    assert cs.canvas_fft is first
    cs.deleteLater()


def test_main_window_startup_builds_zero_analysis_canvases(
    qapp, qtbot, analysis_canvas_counters,
):
    w = MainWindow()
    qtbot.addWidget(w)
    assert _analysis_total(analysis_canvas_counters) == 0
    for section in ("fft", "fft_time", "frf", "order"):
        page = w.chart_stack.page_for_mode[section]
        assert page.readiness() == AnalysisPageReadiness.UNINITIALIZED
        assert page.pane_count() == 0
    # Time domain still present.
    assert w.canvas_time is not None
    assert w.chart_stack.current_mode() == "time"


def test_main_window_explicit_ensure_builds_each_section_once(
    qapp, qtbot, analysis_canvas_counters,
):
    w = MainWindow()
    qtbot.addWidget(w)
    assert _analysis_total(analysis_canvas_counters) == 0

    w.chart_stack.ensure_analysis_page_ready("fft")
    assert analysis_canvas_counters["line"] == 1
    w.chart_stack.ensure_analysis_page_ready("fft_time")
    assert analysis_canvas_counters["heatmap"] == 1
    w.chart_stack.ensure_analysis_page_ready("frf")
    assert analysis_canvas_counters["frf"] == 1
    w.chart_stack.ensure_analysis_page_ready("order")
    assert analysis_canvas_counters["heatmap"] == 2
    assert _analysis_total(analysis_canvas_counters) == 4

    before = dict(analysis_canvas_counters)
    for section in ("fft", "fft_time", "frf", "order"):
        w.chart_stack.ensure_analysis_page_ready(section)
    assert analysis_canvas_counters == before


def test_deferred_tick_density_applies_latest_on_ensure(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.chart_stack.page_fft.pane_count() == 0

    w.inspector.top.spin_xt.setValue(7)
    w.inspector.top.spin_yt.setValue(9)
    w._update_all_tick_density_pair(7, 9)

    w.chart_stack.ensure_analysis_page_ready("fft")
    canvas = w.chart_stack.peek_analysis_canvas("fft")
    assert canvas is not None
    assert canvas._bottom_tick_target == 7
    assert canvas._time_divisions == 9


def test_ensure_does_not_change_current_mode_or_dirty(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.chart_stack.current_mode() == "time"
    dirty_before = w._project_session_is_dirty()

    w.chart_stack.ensure_analysis_page_ready("fft")
    w.chart_stack.ensure_analysis_page_ready("frf")

    assert w.chart_stack.current_mode() == "time"
    assert w._project_session_is_dirty() == dirty_before


def test_chart_stack_binds_primary_card_signals_once(qapp, analysis_canvas_counters):
    cs = ChartStack(defer_analysis_charts=True)
    calls = {"n": 0}
    original = cs._connect_analysis_card_signals

    def _counting(card):
        calls["n"] += 1
        return original(card)

    cs._connect_analysis_card_signals = _counting
    cs.ensure_analysis_page_ready("fft")
    cs.ensure_analysis_page_ready("fft")
    assert calls["n"] == 1
    assert analysis_canvas_counters["line"] == 1
    cs.deleteLater()


def test_mode_switch_ensures_target_without_building_siblings(
    qapp, qtbot, analysis_canvas_counters,
):
    w = MainWindow()
    qtbot.addWidget(w)
    assert _analysis_total(analysis_canvas_counters) == 0

    w._on_mode_changed("fft")
    qapp.processEvents()
    assert analysis_canvas_counters["line"] == 1
    assert analysis_canvas_counters["heatmap"] == 0
    assert analysis_canvas_counters["frf"] == 0
    assert w.chart_stack.current_mode() == "fft"
    assert w.chart_stack.page_fft.readiness() == AnalysisPageReadiness.READY
    assert w.chart_stack.page_frf.readiness() == AnalysisPageReadiness.UNINITIALIZED
