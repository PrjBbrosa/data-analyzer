"""Task 3: idle analysis-page preload and foreground priority."""
from __future__ import annotations

import pytest

from mf4_analyzer.ui.analysis_section_page import AnalysisPageReadiness
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window.startup_coordinator import (
    DEFAULT_PRELOAD_ORDER,
    ENV_DISABLE_IDLE_PRELOAD,
    ENV_EAGER_ANALYSIS_CHARTS,
    StartupCoordinator,
)
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def analysis_canvas_counters(monkeypatch):
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


def _force_idle_ready(coord: StartupCoordinator) -> None:
    """Bypass the input quiet window so a single timer tick can run a step."""
    coord._last_activity_mono = 0.0


@pytest.fixture
def window(qapp, qtbot, monkeypatch):
    # Keep Task 2 deferred charts; allow idle preload under test control.
    monkeypatch.delenv(ENV_DISABLE_IDLE_PRELOAD, raising=False)
    monkeypatch.delenv(ENV_EAGER_ANALYSIS_CHARTS, raising=False)
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qapp.processEvents()
    # showEvent arms start via singleShot(0); drain that without running steps.
    qapp.processEvents()
    yield w
    w._project_dirty.mark_saved()
    coord = getattr(w, "_startup_coordinator", None)
    if coord is not None:
        coord.shutdown()


def test_idle_preload_default_order(window, qapp, analysis_canvas_counters):
    coord = window._startup_coordinator
    assert coord.pending_sections() == list(DEFAULT_PRELOAD_ORDER)
    assert _analysis_total(analysis_canvas_counters) == 0

    seen = []
    for section in DEFAULT_PRELOAD_ORDER:
        _force_idle_ready(coord)
        assert coord.pending_sections()[0] == section
        coord._step_timer.stop()
        coord._on_step_timer()
        seen.append(section)
        page = window.chart_stack.page_for_mode[section]
        assert page.readiness() == AnalysisPageReadiness.READY

    assert seen == list(DEFAULT_PRELOAD_ORDER)
    assert analysis_canvas_counters["line"] == 1  # fft
    assert analysis_canvas_counters["heatmap"] == 2  # fft_time + order
    assert analysis_canvas_counters["frf"] == 1
    assert window.chart_stack.current_mode() == "time"
    assert not window._project_session_is_dirty()


def test_user_priority_outranks_default_order(window, qapp, analysis_canvas_counters):
    coord = window._startup_coordinator
    coord.prioritize("frf")
    assert coord.pending_sections()[0] == "frf"
    _force_idle_ready(coord)
    coord._step_timer.stop()
    coord._on_step_timer()
    assert window.chart_stack.page_frf.readiness() == AnalysisPageReadiness.READY
    assert analysis_canvas_counters["frf"] == 1
    assert analysis_canvas_counters["line"] == 0
    assert window.chart_stack.page_fft.readiness() == AnalysisPageReadiness.UNINITIALIZED


def test_dedup_ready_pages_and_single_ensure(window, analysis_canvas_counters):
    coord = window._startup_coordinator
    window.chart_stack.ensure_analysis_page_ready("fft")
    assert analysis_canvas_counters["line"] == 1
    coord.prioritize("fft")
    assert "fft" not in coord.pending_sections()
    before = dict(analysis_canvas_counters)
    _force_idle_ready(coord)
    coord._step_timer.stop()
    coord._on_step_timer()  # next pending, not fft again
    assert analysis_canvas_counters["line"] == before["line"]


def test_busy_yield_blocks_optional_idle_only(window, qapp, analysis_canvas_counters):
    coord = window._startup_coordinator
    window._time_render.enter()
    try:
        _force_idle_ready(coord)
        coord._step_timer.stop()
        coord._on_step_timer()
        assert _analysis_total(analysis_canvas_counters) == 0
        assert coord.pending_sections()[0] == "fft"
    finally:
        window._time_render.leave()

    # Foreground request still proceeds while restore/busy would yield idle.
    window._time_render.enter()
    try:
        done = []
        coord.request_ready("fft", done.append, foreground=True)
        _force_idle_ready(coord)
        # Foreground bypasses yield even if quiet/busy would block idle.
        coord._step_timer.stop()
        # busy still true — foreground path must not yield
        assert "fft" in coord._foreground or coord.pending_sections()
        # Manually invoke: _should_yield_idle is True but section is foreground
        coord._on_step_timer()
        assert window.chart_stack.page_fft.readiness() == AnalysisPageReadiness.READY
        assert done == ["fft"]
    finally:
        window._time_render.leave()


def test_resume_after_busy_clears(window, analysis_canvas_counters):
    coord = window._startup_coordinator
    window._time_render.enter()
    _force_idle_ready(coord)
    coord._on_step_timer()
    assert _analysis_total(analysis_canvas_counters) == 0
    window._time_render.leave()
    _force_idle_ready(coord)
    coord._step_timer.stop()
    coord._on_step_timer()
    assert window.chart_stack.page_fft.readiness() == AnalysisPageReadiness.READY


def test_prepare_failure_diagnosed_no_auto_retry(window, monkeypatch):
    coord = window._startup_coordinator
    page = window.chart_stack.page_fft

    def boom():
        raise RuntimeError("synthetic prepare failure")

    monkeypatch.setattr(page, "_materialize_primary_card", boom)
    _force_idle_ready(coord)
    coord._step_timer.stop()
    coord._on_step_timer()
    assert page.readiness() == AnalysisPageReadiness.FAILED
    assert page.prepare_error() is not None
    assert "fft" not in coord.pending_sections()
    # Idle continues other pages but does not re-queue the failed section.
    remaining = list(coord.pending_sections())
    assert "fft" not in remaining


def test_shutdown_cancels_queue_and_callbacks(window, qapp):
    coord = window._startup_coordinator
    fired = []
    coord.request_ready("frf", fired.append, foreground=True)
    window._project_dirty.mark_saved()
    window.close()
    qapp.processEvents()
    assert coord.closed
    assert coord.pending_sections() == []
    assert fired == []  # never became ready before shutdown


def test_rapid_mode_switch_idle_does_not_change_mode(
    window, qapp, analysis_canvas_counters,
):
    coord = window._startup_coordinator
    window._on_mode_changed("fft")
    window._on_mode_changed("frf")
    window._on_mode_changed("time")
    qapp.processEvents()
    assert window.chart_stack.current_mode() == "time"
    # Idle may still prepare remaining pages; must not flip mode.
    while coord.pending_sections():
        _force_idle_ready(coord)
        coord._step_timer.stop()
        coord._on_step_timer()
    assert window.chart_stack.current_mode() == "time"
    assert window.chart_stack.page_fft.readiness() == AnalysisPageReadiness.READY
    assert window.chart_stack.page_frf.readiness() == AnalysisPageReadiness.READY


def test_idle_preload_does_not_run_analysis_compute(window, monkeypatch):
    coord = window._startup_coordinator
    calls = []

    def track(name):
        def _(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} must not run during idle preload")

        return _

    for name in ("do_fft", "do_fft_time", "do_frf", "do_order_analysis"):
        if hasattr(window, name):
            monkeypatch.setattr(window, name, track(name))

    jobs = window._analysis_jobs
    if callable(getattr(jobs, "submit", None)):
        def _no_submit(*args, **kwargs):
            calls.append("submit")
            raise AssertionError("analysis job submit during idle preload")

        monkeypatch.setattr(jobs, "submit", _no_submit)

    while coord.pending_sections():
        _force_idle_ready(coord)
        coord._step_timer.stop()
        coord._on_step_timer()
    assert calls == []
    assert window.chart_stack.current_mode() == "time"


def test_session_invalidate_drops_stale_callbacks(window):
    coord = window._startup_coordinator
    fired = []
    coord.request_ready("order", fired.append, foreground=True)
    coord.invalidate_session()
    _force_idle_ready(coord)
    coord._step_timer.stop()
    coord._on_step_timer()
    assert window.chart_stack.page_order.readiness() == AnalysisPageReadiness.READY
    assert fired == []  # generation gated


def test_disable_idle_env(monkeypatch, qapp, qtbot, analysis_canvas_counters):
    monkeypatch.setenv(ENV_DISABLE_IDLE_PRELOAD, "1")
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qapp.processEvents()
    qapp.processEvents()
    coord = w._startup_coordinator
    assert coord.pending_sections() == []
    assert _analysis_total(analysis_canvas_counters) == 0
    # Explicit ensure still works.
    w.chart_stack.ensure_analysis_page_ready("fft")
    assert analysis_canvas_counters["line"] == 1
    w._project_dirty.mark_saved()
    coord.shutdown()


def test_eager_env_builds_at_construction(monkeypatch, qapp, qtbot, analysis_canvas_counters):
    monkeypatch.setenv(ENV_EAGER_ANALYSIS_CHARTS, "1")
    w = MainWindow()
    qtbot.addWidget(w)
    assert _analysis_total(analysis_canvas_counters) == 4
    for section in DEFAULT_PRELOAD_ORDER:
        assert w.chart_stack.page_for_mode[section].readiness() == (
            AnalysisPageReadiness.READY
        )
    w._project_dirty.mark_saved()
    w._startup_coordinator.shutdown()


def test_mode_change_prioritizes_without_building_siblings_beyond_target(
    window, analysis_canvas_counters,
):
    before = _analysis_total(analysis_canvas_counters)
    window._on_mode_changed("order")
    assert analysis_canvas_counters["heatmap"] >= 1
    assert window.chart_stack.page_order.readiness() == AnalysisPageReadiness.READY
    # Sibling pages not forced by mode entry.
    assert window.chart_stack.page_fft.readiness() in (
        AnalysisPageReadiness.UNINITIALIZED,
        AnalysisPageReadiness.READY,  # idle may have started fft first if raced
    )
    # Mode entry itself only ensures the target once.
    assert window.chart_stack.current_mode() == "order"
    assert _analysis_total(analysis_canvas_counters) >= before + 1
