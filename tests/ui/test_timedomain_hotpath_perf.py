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
import pytest

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


def test_raw_x_bounds_scan_shared_axis_once_per_plot_generation(
    qtbot, qapp, monkeypatch,
):
    """Million-point shared HDF time axes must not be rescanned per row/event."""
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    rows = _rows(3)

    scans = []
    original = canvas._scan_finite_x_bounds
    monkeypatch.setattr(
        canvas,
        "_scan_finite_x_bounds",
        lambda values: scans.append(id(values)) or original(values),
    )

    canvas.plot_channels(rows, mode="subplot")
    assert len(scans) == 1

    for offset in np.linspace(0.0, 0.4, 8):
        canvas._buffered_xlim((offset, offset + 0.4))
    assert len(scans) == 1, "pan/settle must consume cached raw-X bounds"

    canvas.plot_channels(rows, mode="subplot")
    assert len(scans) == 2, "a new plot generation performs one fresh scan"


def test_raw_x_bounds_cache_preserves_finite_union_semantics(qtbot, qapp):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    shared = np.array([np.nan, -2.0, 1.0, np.nan], dtype=np.float64)
    later = np.array([5.0, np.nan, 8.0], dtype=np.float64)
    all_nan = np.array([np.nan, np.nan], dtype=np.float64)
    rows = [
        ("a", True, shared, np.arange(4.0), "#1769e0", "u", "fid"),
        ("b", True, shared, np.arange(4.0), "#ef4444", "u", "fid"),
        ("c", True, later, np.arange(3.0), "#00b894", "u", "fid"),
        ("d", True, all_nan, np.arange(2.0), "#fbbf24", "u", "fid"),
    ]

    canvas.plot_channels(rows, mode="subplot")

    assert canvas._data_x_union() == pytest.approx((-2.0, 8.0))


def test_resize_burst_cancels_data_refresh_until_one_final_settle(
    qtbot, qapp, monkeypatch,
):
    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    canvas._refresh_timer.start(1000)
    canvas._coarse_timer.start(1000)
    canvas._pending_coarse_xlim = (0.2, 0.8)

    canvas.resize(640, 390)
    qapp.processEvents()

    assert not canvas._refresh_timer.isActive()
    assert not canvas._coarse_timer.isActive()
    assert canvas._pending_coarse_xlim is None
    assert canvas._resize_settle_timer.isActive()

    settled = []
    monkeypatch.setattr(
        canvas,
        "_settle_visible_data",
        lambda generation: settled.append(generation) or True,
    )
    canvas._on_resize_settled()

    assert settled == [canvas._interaction_generation]
    assert not canvas._refresh_timer.isActive(), (
        "resize quiet-window completion must not arm a second data timer"
    )


def test_view_gesture_cancels_unfinished_resize_quiet_window(qtbot, qapp):
    """Resize settling must not race an immediately following pan gesture."""
    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    canvas._resize_settle_timer.start(canvas._RESIZE_SETTLE_MS)

    canvas._begin_view_interaction()

    assert not canvas._resize_settle_timer.isActive()
    canvas._end_view_interaction()


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


def test_range_burst_defers_ticks_and_range_signals_until_one_settle(
    qtbot, qapp, monkeypatch
):
    from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController

    canvas = _make_canvas(qtbot, _rows(1), "overlay")
    vb = canvas._primary_xaxis_ax.view_box
    reticks = []
    xrange_emits = []
    visible_emits = []
    monkeypatch.setattr(
        TickDensityController,
        "_apply_target_x_ticks_to_all_axes",
        lambda self: reticks.append(1),
    )
    canvas.xrange_changed.connect(lambda lo, hi: xrange_emits.append((lo, hi)))
    canvas.visible_range_changed.connect(lambda: visible_emits.append(1))

    canvas._begin_view_interaction()
    latest = None
    for i in range(5):
        latest = (0.05 * i, 0.55 + 0.05 * i)
        vb.setXRange(*latest, padding=0)
        qtbot.wait(50)
        assert reticks == []
        assert xrange_emits == []
        assert visible_emits == []
    canvas._end_view_interaction()
    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 40)

    assert reticks == [1]
    assert xrange_emits == [latest]
    assert visible_emits == [1]


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
        def plot_channels(
            self, data, mode, xlabel, defer_first_frame=False,
            progress_callback=None, render_context_key=None,
            full_rebuild_reason=None,
        ):
            self.data = data
            self.mode = mode
            self.xlabel = xlabel
            self.defer_first_frame = defer_first_frame
            self.render_context_key = render_context_key
            self.full_rebuild_reason = full_rebuild_reason

        def try_apply_selection_delta(self, data, *, mode, render_context_key=None):
            self.delta_attempt = (data, mode, render_context_key)
            return {"applied": False, "reason": "no-render-model"}

        def set_tick_density(self, x, y):
            self.tick_density = (x, y)

        def invalidate_envelope_cache(self, reason):
            self.invalidated = reason

    fake = types.SimpleNamespace()
    fake.files = {"fid": fd}
    fake.channel_list = types.SimpleNamespace(
        get_checked_channels=lambda: [("fid", "speed", "#1769e0")],
        get_visible_checked_channels=lambda: [("fid", "speed", "#1769e0")],
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
    fake._time_axis_label = lambda _unit=None: "Time (s)"
    fake._set_time_plot_diagnostics = lambda *_args, **_kwargs: None
    fake._sync_time_range_inputs_from_visible_xlim = lambda: None
    fake.statusBar = types.SimpleNamespace(showMessage=lambda *_args, **_kwargs: None)

    canvas = FakeCanvas()
    mw.MainWindow._plot_time_on_canvas(fake, canvas, update_primary_ui=True)

    assert len(canvas.data) == 1
    assert canvas.delta_attempt[1] == "subplot"
    assert canvas.full_rebuild_reason == "no-render-model"
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


def test_mainwindow_crc_uncheck_recheck_and_eye_toggle_use_selection_delta(
    qtbot, qapp, tmp_path,
):
    from unittest.mock import patch
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.main_window import MainWindow

    path = tmp_path / "crc-selection.csv"
    n = 5727
    pd.DataFrame({
        "Time": np.arange(n, dtype=np.float64) / 100.0,
        "EPS_CRC1": (np.arange(n) % 256).astype(np.float64),
    }).to_csv(path, index=False)

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1400, 800)
    window.show()
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([str(path)], ""),
    ):
        window.load_files()
    qapp.processEvents()

    window.chart_stack.set_plot_mode_for_canvas(window.canvas_time, "overlay")
    fid = next(iter(window.files))
    file_item = window.channel_list._file_items[fid]
    crc_item = next(
        file_item.child(i)
        for i in range(file_item.childCount())
        if file_item.child(i).data(0, Qt.UserRole)[2] == "EPS_CRC1"
    )
    crc_item.setCheckState(0, Qt.Checked)
    qapp.processEvents()

    canvas = window.canvas_time
    assert canvas._selection_mode == "overlay"
    display_name = window.files[fid].get_prefixed_channel("EPS_CRC1")
    pair = canvas._channel_lines[display_name]
    pdi = pair[1].plot_data_item
    view_box = pair[0].view_box
    canvas.set_xlim(10.0, 20.0)
    xlim = canvas.get_visible_xlim()
    generation = canvas._interaction_generation

    crc_item.setCheckState(0, Qt.Unchecked)
    qapp.processEvents()
    assert pdi.isVisible() is False
    assert canvas._interaction_generation == generation

    crc_item.setCheckState(0, Qt.Checked)
    qapp.processEvents()
    assert canvas._channel_lines[display_name][1].plot_data_item is pdi
    assert canvas._channel_lines[display_name][0].view_box is view_box
    assert canvas.get_visible_xlim() == pytest.approx(xlim)

    window.channel_list._on_item_clicked(crc_item, 2)
    qapp.processEvents()
    assert pdi.isVisible() is False
    window.channel_list._on_item_clicked(crc_item, 2)
    qapp.processEvents()
    assert canvas._channel_lines[display_name][1].plot_data_item is pdi
    assert canvas._channel_lines[display_name][0].view_box is view_box
    assert canvas.get_visible_xlim() == pytest.approx(xlim)
