"""M3 consumers for a native FileData already in hand.

Time domain, cursor, statistics and Custom-X read ``read_signal``. A legacy
table keeps its existing row pairing and cursor snap. These tests do not
switch the product open path to native.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.signal_access import read_signal
from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec, resolve_custom_xaxis


def _require(module, name):
    fn = getattr(module, name, None)
    if not callable(fn):
        pytest.fail(f"{module.__name__}.{name} 未实现")
    return fn


def _f64(values):
    return np.asarray(values, dtype="<f8")


def _write_native(path):
    from asammdf import MDF, Signal

    groups = {
        "dot": (_f64([1.0]), _f64([9.0]), None),
        "burst": (_f64([0.10, 0.11, 0.12]), _f64([0.0, 100.0, 0.0]), None),
        "grid": (_f64([0.0, 0.25, 0.5, 0.75, 1.0]), _f64([1.0, 1.0, 1.0, 1.0, 1.0]), None),
        "fast": (_f64([0.0, 0.25, 0.5, 0.75, 1.0]), _f64([0.0, 1.0, 2.0, 3.0, 4.0]), None),
        "anchor": (_f64([0.0, 1.0, 2.0]), _f64([0.0, 0.0, 0.0]), None),
        "other": (_f64([0.0, 1.0, 3.0]), _f64([0.0, 0.0, 30.0]), None),
        "dup": (_f64([0.0, 1.0, 1.0, 2.0]), _f64([1.0, 2.0, 9.0, 4.0]), None),
        "flagged": (
            _f64([0.0, 0.1, 0.2, 0.3]),
            _f64([10.0, 20.0, 30.0, 40.0]),
            np.array([0, 1, 0, 1], dtype=np.uint8),
        ),
        "reset": (_f64([0.0, 2.0, 1.0]), _f64([1.0, 2.0, 3.0]), None),
        "far": (_f64([20.0, 21.0, 22.0]), _f64([1.0, 2.0, 3.0]), None),
        "pair": (_f64([1.0, 1.01]), _f64([10.0, 14.0]), None),
    }
    mdf = MDF(version="4.10")
    for name, (timestamps, samples, invalidation) in groups.items():
        kwargs = {}
        if invalidation is not None:
            kwargs["invalidation_bits"] = invalidation
        mdf.append([Signal(
            samples=np.asarray(samples),
            timestamps=np.asarray(timestamps, dtype=float),
            name=name,
            unit="Nm",
            **kwargs,
        )])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


@pytest.fixture(scope="module")
def native_file(tmp_path_factory):
    path = _write_native(tmp_path_factory.mktemp("native-m3") / "anonymous.mf4")
    fd = DataLoader.load_mf4_native(str(path))
    yield fd
    fd.close_source()


def test_product_open_stays_on_load_mf4():
    adapter = SourceAdapterRegistry.default().adapter_for("sample.mf4")
    assert adapter.loader_name == "load_mf4"
    assert callable(DataLoader.load_mf4_native)
    assert callable(getattr(adapter, "load_native_sources", None))


def test_native_peak_reaches_plot_cursor_and_stats(native_file, qapp):
    from mf4_analyzer.ui import time_curve_bindings as bindings
    from mf4_analyzer.ui.main_window.window import MainWindow
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    native_plot_rows = _require(bindings, "native_plot_rows")
    fd = native_file
    series = read_signal(fd, "burst")
    host = SimpleNamespace(
        channel_list=SimpleNamespace(
            get_file_data=lambda fid: fd if fid == "f0" else None,
            checked_axis_groups=lambda: {},
        ),
        files={"f0": fd},
        _active_time_curve_bindings=lambda view_idx=None: [],
    )
    try:
        built = MainWindow._build_time_plot_data(
            host,
            checked=[("f0", "burst", "#1769e0")],
            range_enabled=False,
        )
    except Exception as exc:
        pytest.fail(f"native 时域取数失败: {type(exc).__name__}: {exc}")
    burst_rows = [row for row in built.rows if "burst" in str(row[0])]
    assert burst_rows, "丢峰通道没有进入时域行"
    plotted_t = np.asarray(burst_rows[0][2], dtype=float)
    plotted_y = np.asarray(burst_rows[0][3], dtype=float)
    assert np.any(np.isclose(plotted_t, 0.11))
    assert np.any(np.isclose(plotted_y, 100.0))
    assert np.shares_memory(plotted_y, series.values)

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    canvas.plot_channels(
        native_plot_rows(fd, ["burst"], fid="f0"),
        mode="single",
    )
    QCoreApplication.processEvents()
    stored = _channel_arrays(canvas)
    assert np.any(np.isclose(stored[1], 100.0))
    assert np.shares_memory(stored[1], series.values)

    reading = canvas._cursor.evaluate_single_cursor(0.11)
    assert reading
    assert reading[0].current_value == pytest.approx(100.0)
    assert reading[0].sample_time == pytest.approx(0.11)
    assert reading[0].content_revision == fd.native_store.revision
    stats = _stats_row(canvas)
    assert stats["max"] == pytest.approx(100.0)
    assert stats.get("weighting") == "有效样本"

    _zero_displayed_curve(canvas)
    canvas.axes_list[0].view_box.setXRange(0.10, 0.105, padding=0)
    QCoreApplication.processEvents()
    zoomed = canvas._cursor.evaluate_single_cursor(0.11)
    assert zoomed[0].current_value == pytest.approx(100.0)
    assert zoomed[0].sample_time == pytest.approx(0.11)
    assert _stats_row(canvas)["max"] == pytest.approx(100.0)
    assert zoomed[0].content_revision == reading[0].content_revision


def test_native_cursor_uses_raw_points_not_the_display_line(native_file, qapp):
    from mf4_analyzer.ui import time_curve_bindings as bindings
    from mf4_analyzer.ui import time_xaxis as axis
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    query = _require(axis, "query_native_cursor")
    pair = read_signal(native_file, "pair")
    nearest = query(pair, 1.005)
    assert nearest.status == "sample"
    assert nearest.value == pytest.approx(10.0)
    assert nearest.sample_time == pytest.approx(1.0)
    assert nearest.delta_s == pytest.approx(-0.005)
    assert "线性插值" not in nearest.text
    assert "Δt" in nearest.text

    linear = query(pair, 1.005, mode="linear")
    assert linear.status == "interpolated"
    assert linear.value == pytest.approx(12.0)
    assert "线性插值" in linear.text

    assert query(pair, 2.0).status == "none"
    assert "无数据" in query(pair, 2.0).text

    dot = query(read_signal(native_file, "dot"), 1.0)
    assert dot.value == pytest.approx(9.0)
    assert query(read_signal(native_file, "dot"), 1.1).status == "none"

    dup = query(read_signal(native_file, "dup"), 1.0)
    assert dup.status == "multiple"
    assert dup.record_indices == (1, 2)
    assert "序号" in dup.text

    flagged = query(read_signal(native_file, "flagged"), 0.1)
    assert flagged.status == "none"
    stats = _require(axis, "native_sample_statistics")
    flagged_stats = stats(read_signal(native_file, "flagged"))
    assert flagged_stats["max"] == pytest.approx(30.0)
    assert flagged_stats["valid_count"] == 2
    assert flagged_stats["invalid_count"] == 2

    native_plot_rows = _require(bindings, "native_plot_rows")
    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    canvas.plot_channels(native_plot_rows(native_file, ["pair"], fid="f0"), mode="single")
    QCoreApplication.processEvents()
    canvas._cursor._emit_single_cursor_html(1.005)
    QCoreApplication.processEvents()
    marker = canvas._cursor._native_sample_markers[0]
    xs, ys = marker.getData()
    assert xs[0] == pytest.approx(1.0)
    assert ys[0] == pytest.approx(10.0)
    assert xs[0] != pytest.approx(1.005)


def test_native_single_point_is_not_auto_checked(native_file, qtbot):
    from mf4_analyzer.ui.widgets.channel_tree import MultiFileChannelWidget

    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f0", native_file)
    widget.set_attached_file_ids(["f0"])
    widget.check_first_channel("f0")
    checked = {channel for _fid, channel, _color in widget.get_checked_channels()}
    assert "dot" not in checked
    assert "burst" in checked
    leaves = _leaf_counts(widget)
    assert leaves["dot"] == "1"
    assert leaves["burst"] == "3"
    header = widget.tree.topLevelItem(0).text(1)
    assert "通道" in header
    assert "行" not in header


def test_equal_length_time_shift_is_not_custom_x_sync(native_file, tmp_path):
    import pandas as pd

    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.ui import time_xaxis as axis

    spec = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="anchor",
    )
    shifted = resolve_custom_xaxis(
        target_fid="f0",
        target_channel="other",
        files={"f0": native_file},
        spec=spec,
    )
    assert not shifted.ready
    assert shifted.issue is not None
    assert shifted.issue.code == "time_relationship_required"

    aligned = resolve_custom_xaxis(
        target_fid="f0",
        target_channel="fast",
        files={"f0": native_file},
        spec=CustomXAxisSpec(
            mode="channel", resolver="per_source_name", channel="grid",
        ),
    )
    assert aligned.ready
    np.testing.assert_array_equal(aligned.x_values, [1.0, 1.0, 1.0, 1.0, 1.0])

    table = FileData(
        tmp_path / "table.csv",
        pd.DataFrame({
            "Time": [0.0, 1.0, 2.0],
            "angle": [10.0, 20.0, 30.0],
            "signal": [1.0, 2.0, 3.0],
        }),
        ["Time", "angle", "signal"],
        {"angle": "deg", "signal": "Nm"},
        source_metadata={"source_kind": "csv"},
    )
    legacy = resolve_custom_xaxis(
        target_fid="t",
        target_channel="signal",
        files={"t": table},
        spec=CustomXAxisSpec(
            mode="channel", resolver="per_source_name", channel="angle",
        ),
    )
    assert legacy.ready
    np.testing.assert_array_equal(legacy.x_values, [10.0, 20.0, 30.0])
    assert legacy.issue is None


def test_legacy_cursor_still_snaps_with_searchsorted(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    t = np.asarray([0.0, 1.0], dtype=float)
    y = np.asarray([10.0, 14.0], dtype=float)
    canvas.plot_channels(
        [("signal", True, t, y, "#1769e0", "Nm", "fid-legacy")],
        mode="single",
    )
    QCoreApplication.processEvents()
    reading = canvas._cursor.evaluate_single_cursor(0.5)
    assert reading[0].current_value == pytest.approx(14.0)
    assert getattr(reading[0], "read_mode", "") in {"", "legacy"}


def test_native_span_is_the_union_of_channel_clocks(native_file):
    from mf4_analyzer.ui import time_xaxis as axis

    span = _require(axis, "acquisition_span")(native_file)
    assert span is not None
    assert span[0] == pytest.approx(0.0)
    assert span[1] == pytest.approx(22.0)


def test_closed_native_source_does_not_accept_a_late_cursor_write(native_file, qapp, tmp_path):
    from mf4_analyzer.ui import time_curve_bindings as bindings
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    native_plot_rows = _require(bindings, "native_plot_rows")

    path = _write_native(tmp_path / "late.mf4")
    fd = DataLoader.load_mf4_native(str(path))
    series = read_signal(fd, "burst")
    before = np.array(series.values, copy=True)
    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    canvas.plot_channels(native_plot_rows(fd, ["burst"], fid="f0"), mode="single")
    QCoreApplication.processEvents()
    fd.close_source()
    reading = canvas._cursor.evaluate_single_cursor(0.11)
    assert reading
    assert reading[0].current_value is None
    assert "无数据" in reading[0].diagnostic
    assert np.array_equal(series.values, before)
    assert not series.values.flags.writeable


def test_time_copy_mentions_native_samples_and_keeps_import_retry_text():
    from mf4_analyzer.ui.hints import all_hints, hint_text
    from mf4_analyzer.ui.quickref import QUICKREF

    texts = "\n".join(hint.text for hint in all_hints())
    assert "内存预估可重新检查" in texts
    assert "只加倍时限" in texts
    native = hint_text("time.native_samples")
    assert native
    assert "原始采样" in native
    assert "包络" in native
    joined = "\n".join(
        f"{row.desc}\n{row.sub or ''}"
        for group in QUICKREF
        for row in group.rows
    )
    assert "内存预估" in joined
    time_row = next(
        row for group in QUICKREF for row in group.rows if row.desc == "时域"
    )
    assert "原始采样" in (time_row.sub or "")
    assert "单点" in (time_row.sub or "")


def _channel_arrays(canvas):
    for _key, _name, row in canvas.channel_data.composite_items():
        return row[0], row[1]
    pytest.fail("画布没有通道数据")


def _stats_row(canvas):
    for _key, _name, row in canvas.get_statistics().composite_items():
        return row
    pytest.fail("没有统计行")


def _zero_displayed_curve(canvas):
    for _key, _name, pair in canvas._channel_lines.composite_items():
        pair[1].plot_data_item.setData(
            np.asarray([0.0, 1.0]), np.asarray([0.0, 0.0]),
        )
        return
    pytest.fail("没有可显示曲线")


def _leaf_counts(widget):
    counts = {}
    root = widget.tree.topLevelItem(0)
    for index in range(root.childCount()):
        child = root.child(index)
        counts[child.text(0)] = child.text(1)
    return counts
