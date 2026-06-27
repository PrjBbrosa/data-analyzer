"""Hot-path "don't redo work" regression tests.

Each test pins one contract from
docs/superpowers/specs/2026-06-10-timedomain-plot-optimization.md (Wave A).
They assert on CALL COUNTS of internal seams, not on pixels: the
optimizations must make repeated/no-op invocations free without changing
any rendered output (rendered-output parity is covered by the existing
test_pg_timedomain_canvas.py suite).
"""
import numpy as np
import pandas as pd

from mf4_analyzer.io.file_data import FileData
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


def test_propagate_equal_ranges_skips_axis_item_sync(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    canvas._propagate_xlim_to_siblings()  # converge every sibling first

    calls = []
    canvas._sync_x_axis_item_range = lambda *a: calls.append(a)
    canvas._propagate_xlim_to_siblings()
    # All siblings already hold the exact range: zero AxisItem.setRange calls
    # (setRange unconditionally drops the tick picture even for equal values).
    assert calls == []


def test_monotonicity_cached_across_rebuilds(qtbot, qapp, monkeypatch):
    import mf4_analyzer.ui.pg_canvas.overlay_axes as oa

    calls = []
    orig = oa._is_monotonic_array
    monkeypatch.setattr(
        oa, "_is_monotonic_array", lambda t: calls.append(1) or orig(t)
    )

    rows = _rows(2)
    canvas = _make_canvas(qtbot, rows, "subplot")
    assert len(calls) == 2  # first build scans each channel once

    canvas.plot_channels(rows, mode="overlay")  # same arrays, new layout
    assert len(calls) == 2  # rebuild served from the fingerprint cache

    canvas.invalidate_monotonicity_cache()
    canvas.plot_channels(rows, mode="subplot")
    assert len(calls) == 4  # explicit invalidation forces a rescan


def test_disabled_stats_strip_skips_full_array_statistics(monkeypatch):
    import types

    from mf4_analyzer.ui import main_window as mw
    from mf4_analyzer.ui.chart_stack import _STATS_STRIP_ENABLED

    assert _STATS_STRIP_ENABLED is False

    df = pd.DataFrame({
        "time": np.linspace(0.0, 1.0, 16, dtype=np.float64),
        "speed": np.linspace(10.0, 20.0, 16, dtype=np.float64),
    })
    fd = FileData("x.csv", df, list(df.columns), {"speed": "rpm"}, 0)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("stats function should not run when stats strip is disabled")

    for name in ("min", "max", "mean", "sqrt", "std", "ptp"):
        monkeypatch.setattr(mw.np, name, forbidden)

    stats_updates = []

    class FakeCanvas:
        def plot_channels(self, data, mode, xlabel, defer_first_frame=False):
            self.data = data
            self.mode = mode
            self.xlabel = xlabel
            self.defer_first_frame = defer_first_frame

        def set_tick_density(self, x, y):
            self.tick_density = (x, y)

        def invalidate_envelope_cache(self, reason):
            self.invalidated = reason

    fake = types.SimpleNamespace()
    fake.files = {"fid": fd}
    fake.channel_list = types.SimpleNamespace(
        get_checked_channels=lambda: [("fid", "speed", "#1769e0")],
        get_file_data=lambda fid: fake.files.get(fid),
        checked_axis_groups=lambda: {},
    )
    fake.chart_stack = types.SimpleNamespace(
        plot_mode_for_canvas=lambda canvas: "subplot",
        stats_strip=types.SimpleNamespace(update_stats=lambda st: stats_updates.append(st)),
    )
    fake.inspector = types.SimpleNamespace(
        top=types.SimpleNamespace(
            range_enabled=lambda: False,
            range_values=lambda: (0.0, 1.0),
            xaxis_label=lambda: "Time (s)",
            tick_density=lambda: (10, 8),
        ),
        filter_panel=None,
    )
    # The data-assembly logic now lives in the extracted `_build_time_plot_data`
    # helper; bind the real (unbound) methods onto the fake so the seam is
    # exercised end-to-end. With no filter_panel the helper never touches the
    # monkeypatched stats functions.
    fake._build_time_plot_data = types.MethodType(
        mw.MainWindow._build_time_plot_data, fake
    )
    fake._estimate_fs = types.MethodType(mw.MainWindow._estimate_fs, fake)
    fake._filter_suffix = types.MethodType(mw.MainWindow._filter_suffix, fake)
    # The plot path now consults overlay-risk before drawing. Bind the real
    # estimator (subplot mode short-circuits to OK risk without touching any np
    # statistics, so the stats-strip assertion below still holds) plus the
    # risk-banner clear it calls on the non-overlay branch.
    fake._estimate_current_time_overlay_risk = types.MethodType(
        mw.MainWindow._estimate_current_time_overlay_risk, fake
    )
    fake._clear_plot_risk = lambda: None
    fake._overlay_primary = None
    fake._last_plot_mode = None
    fake._last_range_state = None
    # Per-canvas cache-invalidation bookkeeping + the progress-token seam the
    # plot path now opens (returns None → the finally block skips finish).
    fake._last_filter_state_by_canvas = {}
    fake._begin_compute_progress = lambda *_a, **_k: None
    fake._custom_xaxis_fid = None
    fake._custom_xaxis_ch = None
    fake._custom_xlabel = None
    fake._sync_time_range_inputs_from_visible_xlim = lambda: None
    fake.statusBar = types.SimpleNamespace(showMessage=lambda *_args, **_kwargs: None)

    canvas = FakeCanvas()
    mw.MainWindow._plot_time_on_canvas(fake, canvas, update_primary_ui=True)

    assert len(canvas.data) == 1
    assert stats_updates == []


def test_filedata_time_column_shares_memory_with_dataframe():
    df = pd.DataFrame({"time": np.arange(8.0), "a": np.arange(8.0)})
    fd = FileData("x.csv", df, list(df.columns), {}, 0)
    # The float64 time column must be exposed as a view, not an
    # astype(copy=True) duplicate of the full column.
    assert np.shares_memory(fd.time_array, df["time"].to_numpy(copy=False))


def test_preserving_rebuild_skips_full_range_bind_envelope(qtbot, qapp, monkeypatch):
    import mf4_analyzer.ui.pg_canvases as legacy

    calls = []
    orig = legacy.build_envelope
    monkeypatch.setattr(
        legacy, "build_envelope", lambda *a, **k: calls.append(1) or orig(*a, **k)
    )

    rows = _rows(2)
    canvas = _make_canvas(qtbot, rows, "overlay")
    assert len(calls) == 2  # plain plot_channels still binds the first frame

    calls.clear()
    canvas.plot_channels_preserving_xlim(rows, mode="subplot")
    # Deferred bind: the restore+flush right after the build paints the first
    # frame from the viewport envelope; the full-range bind envelope is gone.
    assert calls == []
    for _axis, line in canvas._channel_lines.values():
        xd, _yd = line.plot_data_item.getData()
        assert xd is not None and len(xd) > 0


def test_overlay_uses_single_cursor_line_item(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(3), "overlay")
    items = canvas._cursor._ensure_cursor_items("_cursor_line_items", color="#1769e0")
    # Overlay aux ViewBoxes all share one full-plot rect and one X transform:
    # one line on the X-master covers every channel (was: N identical lines).
    assert len(items) == 1

    canvas.plot_channels(_rows(3), mode="subplot")
    items = canvas._cursor._ensure_cursor_items("_cursor_line_items", color="#1769e0")
    assert len(items) == 3  # subplot keeps one per row (rows do not overlap)
