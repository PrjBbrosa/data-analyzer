"""Hot-path "don't redo work" regression tests.

Each test pins one contract from
docs/superpowers/specs/2026-06-10-timedomain-plot-optimization.md (Wave A).
They assert on CALL COUNTS of internal seams, not on pixels: the
optimizations must make repeated/no-op invocations free without changing
any rendered output (rendered-output parity is covered by the existing
test_pg_timedomain_canvas.py suite).
"""
import numpy as np

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _rows(n=3):
    """Channel rows in the MainWindow shape (name, visible, t, sig, color, unit, fid)."""
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    waves = [
        ("speed", 1000.0 * np.sin(2 * np.pi * 5 * t), "#1769e0", "rpm"),
        ("torque", 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t), "#ef4444", "Nm"),
        ("pressure", 0.2 * t + 0.1 * np.sin(2 * np.pi * 7 * t), "#00b894", "bar"),
        ("temp", 60.0 + 2.0 * np.cos(2 * np.pi * 1.5 * t), "#fbbf24", "C"),
    ]
    return [
        (name, True, t, sig, color, unit, "fid-1")
        for name, sig, color, unit in waves[:n]
    ]


def _make_canvas(qtbot, rows, mode):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    canvas.plot_channels(rows, mode=mode)
    canvas._flush_pending_refresh()
    return canvas


def test_repeated_quality_disable_emits_nothing_and_skips_scene_scan(
    qtbot, qapp, monkeypatch
):
    from mf4_analyzer.ui.pg_canvas.quality import QualityManager

    canvas = _make_canvas(qtbot, _rows(2), "subplot")
    canvas.disable_interactive_quality()  # settle into AA-off once (warm-up)

    emissions = []
    canvas.quality_status_changed.connect(lambda st: emissions.append(st))
    scans = []
    orig = QualityManager._density_status
    monkeypatch.setattr(
        QualityManager,
        "_density_status",
        lambda self: scans.append(1) or orig(self),
    )

    for _ in range(5):
        canvas.disable_interactive_quality()

    # Drag ticks 2..N: AA already off, idle timer already stopped - the
    # status cannot have changed, so no scene traversal and no emission.
    assert emissions == []
    assert scans == []


def test_resize_defers_label_rework_to_settle(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(2), "subplot")
    assert canvas._subplot_label_specs  # precondition: labels exist

    calls = []
    canvas._recheck_subplot_label_placement = lambda: calls.append(1)
    canvas.resize(640, 400)
    qapp.processEvents()
    # resizeEvent itself must NOT tear down / rebuild label TextItems.
    assert calls == []
    canvas._on_resize_settled()
    # The settle pass does it exactly once.
    assert calls == [1]


def test_x_tick_computation_memoized_across_rows_and_ticks(qtbot, qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController

    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    ctrl = canvas._tick_density_controller

    calls = []
    orig = TickDensityController._compute_target_x_ticks
    monkeypatch.setattr(
        TickDensityController,
        "_compute_target_x_ticks",
        lambda self, *a: calls.append(1) or orig(self, *a),
    )

    ctrl.ticks_cache.clear()
    ctrl._apply_target_x_ticks_to_all_axes()
    # 3 subplot rows share one (xlim, axis_width, density) key after axis
    # unification -> at most one real computation.
    assert len(calls) <= 1

    calls.clear()
    ctrl._apply_target_x_ticks_to_all_axes()
    # Identical viewport (a debounce tick with unchanged xlim): pure cache.
    assert calls == []


def test_repeated_flush_with_same_xlim_skips_tail_work(qtbot, qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController

    canvas = _make_canvas(qtbot, _rows(2), "subplot")  # helper already flushed once

    emitted = []
    canvas.xrange_changed.connect(lambda lo, hi: emitted.append((lo, hi)))
    reticks = []
    monkeypatch.setattr(
        TickDensityController,
        "_apply_target_x_ticks_to_all_axes",
        lambda self: reticks.append(1),
    )

    canvas._flush_pending_refresh()
    canvas._flush_pending_refresh()

    # Same xlim + same pixel width + every channel gated by its range key:
    # the tail (retick + xrange/visible_range emits + quality emit) must not run.
    assert emitted == []
    assert reticks == []
