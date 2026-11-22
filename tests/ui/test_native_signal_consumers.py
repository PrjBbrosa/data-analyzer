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


def test_fft_time_request_range_is_resolved_before_quality_rejection():
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin

    time = np.arange(8) / 4.0
    values = np.arange(8, dtype=float)
    invalid = np.zeros(8, dtype=bool)
    invalid[0] = True
    store = NativeSignalStore.build(
        "fft-time",
        (AxisSpec("t", "clk", "time", "s", time),),
        (ChannelSpec(0, 1, "sig", "t", values, unit="Nm", validity=invalid),),
    )
    host = SimpleNamespace(files={"f": FileData.from_native_store("fft.mf4", store)})
    ready = FFTTimeMixin._fft_time_signal_for(
        host, ("f", "sig"), time_range=(0.25, 1.5),
    )
    assert ready[0] == "f"
    assert ready[3] is not None and len(ready[3]) >= 2
    assert float(ready[2][0]) == pytest.approx(0.25)
    blocked = FFTTimeMixin._fft_time_signal_for(host, ("f", "sig"), time_range=None)
    assert blocked == (None, None, None, None, None)
    assert "失效" in str(getattr(host, "_native_prepare_block", ""))

    invalid[2] = True
    inside = NativeSignalStore.build(
        "fft-time-inside",
        (AxisSpec("t", "clk", "time", "s", time),),
        (ChannelSpec(0, 1, "sig", "t", values, unit="Nm", validity=invalid),),
    )
    skipped = []
    job_host = SimpleNamespace(
        files={"f": FileData.from_native_store("fft-inside.mf4", inside)},
        _record_fft_time_skip=lambda reason: skipped.append(reason),
        _normalize_analysis_time_range=lambda value: value,
    )
    job_host._fft_time_signal_for = (
        lambda source, time_range=None: FFTTimeMixin._fft_time_signal_for(
            job_host, source, time_range=time_range,
        )
    )
    result = FFTTimeMixin._build_fft_time_job(
        job_host, 0, "f", "sig", {}, time_range=(0.25, 1.5),
    )
    assert result is None
    assert skipped
    assert skipped[0] != "源通道缺失"
    assert "失效" in skipped[0]


def test_invalid_sample_stays_broken_after_refresh_and_markers_stay_on_their_axis(qapp):
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.ui import time_curve_bindings as bindings
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    time = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    broken = np.array([10.0, 999.0, 30.0, 40.0, 50.0])
    invalid = np.array([False, True, False, False, False])
    left = np.array([1.0, 3.0, 5.0])
    right = np.array([10.0, 30.0, 40.0])
    store = NativeSignalStore.build(
        "display",
        (
            AxisSpec("a", "clk-a", "time", "s", time),
            AxisSpec("b", "clk-b", "time", "s", np.array([1.0, 2.0, 4.0])),
            AxisSpec("c", "clk-c", "time", "s", np.array([1.0, 2.0, 4.0])),
        ),
        (
            ChannelSpec(0, 1, "broken", "a", broken, unit="Nm", validity=invalid),
            ChannelSpec(1, 1, "left", "b", left, unit="Nm"),
            ChannelSpec(2, 1, "right", "c", right, unit="Nm"),
        ),
    )
    fd = FileData.from_native_store("display.mf4", store)
    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    canvas.plot_channels(
        bindings.native_plot_rows(fd, ["broken"], fid="f0"),
        mode="single",
    )
    QCoreApplication.processEvents()
    line = next(canvas._channel_lines.composite_items())[2][1].plot_data_item

    def shows_invalid_value(item):
        y = np.asarray(item.getData()[1], dtype=float)
        return bool(np.any(np.isfinite(y) & np.isclose(y, 999.0)))

    assert not shows_invalid_value(line)
    canvas._refresh_visible_data()
    QCoreApplication.processEvents()
    assert not shows_invalid_value(line)
    raw = next(canvas.channel_data.composite_items())[2][1]
    assert np.any(np.isclose(np.asarray(raw, dtype=float), 999.0))
    stats = next(canvas.get_statistics().composite_items())[2]
    assert stats["max"] == pytest.approx(50.0)

    canvas.plot_channels(
        bindings.native_plot_rows(fd, ["left", "right"], fid="f0"),
        mode="subplot",
    )
    QCoreApplication.processEvents()
    rows = canvas.evaluate_single_cursor(2.0)
    canvas._cursor._sync_native_sample_markers(rows)
    markers = canvas._cursor._native_sample_markers
    seen = []
    for marker in markers:
        _x, y = marker.getData()
        if y is None:
            continue
        values = [float(item) for item in np.asarray(y, dtype=float).reshape(-1) if np.isfinite(item)]
        if values:
            seen.append(values)
    assert sorted(seen) == [[3.0], [30.0]]
    fd.close_source()


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


def test_native_preview_stats_and_export_use_channel_clocks(native_file, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog
    import openpyxl

    from mf4_analyzer.ui.main_window.window import MainWindow

    top = SimpleNamespace(
        range_enabled=lambda: True,
        range_values=lambda: (0.0, 0.2),
    )
    host = SimpleNamespace(
        files={"f": native_file},
        inspector=SimpleNamespace(top=top),
        navigator=SimpleNamespace(get_checked_channels=lambda: []),
        view_manager=SimpleNamespace(
            active=0,
            get=lambda _idx: SimpleNamespace(attached_file_ids=[]),
        ),
        _custom_xaxis_spec=CustomXAxisSpec(),
    )
    time, values = MainWindow._fft_trace_for_source(host, "f", "flagged")
    assert list(time) == pytest.approx([0.0, 0.1, 0.2])
    assert values[0] == pytest.approx(10.0)
    assert np.isnan(values[1])
    assert values[2] == pytest.approx(30.0)

    class _Files:
        def get_file_data(self, _fid):
            return native_file

    stats_host = SimpleNamespace(channel_list=_Files())
    stats_host._native_channel_statistics = (
        lambda fd, channel, enabled, lo, hi: MainWindow._native_channel_statistics(
            stats_host, fd, channel, enabled, lo, hi,
        )
    )
    stats = MainWindow._build_time_statistics(
        stats_host,
        [("f", "flagged", "#000")],
        False,
        0.0,
        1.0,
    )
    row = next(iter(stats.values()))
    assert row["min"] == pytest.approx(10.0)
    assert row["max"] == pytest.approx(30.0)

    labels = [text for text, _payload in MainWindow._build_xaxis_candidates(host)]
    assert any(text.startswith("flagged · ") for text in labels)

    mw = MainWindow()
    notes = []
    mw.files["f"] = native_file
    mw.toast = lambda msg, level="info": notes.append((str(msg), level))
    try:
        wide = tmp_path / "wide.xlsx"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(wide), ""),
        )
        mw._do_export_excel("f", ["grid", "fast"], include_time=True, use_range=False)
        headers = [cell.value for cell in openpyxl.load_workbook(wide).active[1]]
        assert headers == ["channel", "record", "segment", "time", "value", "valid"]

        flagged = tmp_path / "flagged.xlsx"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(flagged), ""),
        )
        mw._do_export_excel("f", ["flagged"], include_time=True, use_range=False)
        sheet = openpyxl.load_workbook(flagged).active
        headers = [cell.value for cell in sheet[1]]
        assert headers == ["channel", "record", "segment", "time", "value", "valid"]
        body = list(sheet.iter_rows(min_row=2, values_only=True))
        assert any(
            row[4] == pytest.approx(20.0) and row[5] in (False, 0)
            for row in body
        )

        dialogs = []
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: dialogs.append(args) or ("", ""),
        )
        mw._do_export_wwt("f", ["fast", "other"], use_range=False)
        assert dialogs == []
        assert "时间轴不同" in notes[-1][0] and "Excel" in notes[-1][0]
        mw._do_export_wwt("f", ["flagged"], use_range=False)
        assert dialogs == []
        assert "失效样本" in notes[-1][0] and "Excel" in notes[-1][0]
    finally:
        mw.files.pop("f", None)
        mw.close()


def test_native_excel_export_keeps_exact_integers_as_text(qapp, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog
    import openpyxl

    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.ui.main_window.window import MainWindow

    raw = np.array([2**53 + 3, 2**53 + 5], dtype=np.int64)
    store = NativeSignalStore.build(
        "wide-int",
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0])),),
        (ChannelSpec(0, 1, "wide", "t", raw, unit="count"),),
    )
    mw = MainWindow()
    mw.files["f"] = FileData.from_native_store(tmp_path / "wide.mf4", store)
    out = tmp_path / "wide.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(out), ""))
    try:
        mw._do_export_excel("f", ["wide"], include_time=True, use_range=False)
        sheet = openpyxl.load_workbook(out).active
        values = [row[4] for row in sheet.iter_rows(min_row=2, values_only=True)]
        assert values == [str(2**53 + 3), str(2**53 + 5)]
    finally:
        mw.files.pop("f", None)
        mw.close()


def test_native_wwt_export_reports_a_failed_channel_instead_of_saving(qapp, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog

    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.io import signal_access
    from mf4_analyzer.io.signal_access import SignalAccessError
    from mf4_analyzer.ui.main_window.window import MainWindow

    store = NativeSignalStore.build(
        "wwt-fail",
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0, 2.0])),),
        (
            ChannelSpec(0, 1, "kept", "t", np.array([1.0, 2.0, 3.0]), unit="Nm"),
            ChannelSpec(0, 2, "broken", "t", np.array([4.0, 5.0, 6.0]), unit="Nm"),
        ),
    )
    mw = MainWindow()
    notes = []
    dialogs = []
    mw.files["f"] = FileData.from_native_store(tmp_path / "wwt.mf4", store)
    mw.toast = lambda msg, level="info": notes.append((str(msg), level))

    real_read = signal_access.read_signal

    def fail_broken(source, channel, *args, **kwargs):
        if channel == "broken":
            raise SignalAccessError("broken 样本不可读")
        return real_read(source, channel, *args, **kwargs)

    monkeypatch.setattr(signal_access, "read_signal", fail_broken)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: dialogs.append(args) or (str(tmp_path / "out.wwt"), ""),
    )
    try:
        mw._do_export_wwt("f", ["kept", "broken"], use_range=False)
        assert dialogs == []
        assert notes
        assert "broken" in notes[-1][0]
        assert notes[-1][1] == "warning"
        assert not (tmp_path / "out.wwt").exists()
    finally:
        mw.files.pop("f", None)
        mw.close()


def _angle_case(n=1000):
    """Independent numeric oracle for the Custom-X display contract.

    The expected X is this angle array. It is not read back from another
    product implementation.
    """
    time = np.arange(n, dtype=float) / float(n)
    signal = np.sin(2.0 * np.pi * 3.0 * time)
    angle = 10.0 + 10.0 * time
    return time, signal, angle


def _write_angle_native(path, time, signal, angle, **extra):
    from asammdf import MDF, Signal

    samples = {
        "sig": signal,
        "angle": angle,
    }
    samples.update(extra)
    mdf = MDF(version="4.10")
    mdf.append([
        Signal(
            samples=np.asarray(values, dtype=float),
            timestamps=np.asarray(time, dtype=float),
            name=name,
            unit="deg" if name == "angle" else "Nm",
        )
        for name, values in samples.items()
    ])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _plot_host(fd, *, fid="f0", x_channel=None, range_enabled=False, range_lo=0.0, range_hi=0.0):
    spec = CustomXAxisSpec()
    if x_channel:
        spec = CustomXAxisSpec(
            mode="channel",
            resolver="per_source_name",
            channel=x_channel,
            label=x_channel,
        )
    return SimpleNamespace(
        channel_list=SimpleNamespace(
            get_file_data=lambda key, owner=fd, owner_fid=fid: (
                owner if key == owner_fid else None
            ),
            checked_axis_groups=lambda: {},
        ),
        files={fid: fd},
        _active_time_curve_bindings=lambda view_idx=None: [],
        _custom_xaxis_spec=spec,
        navigator_order=None,
    )


def _plot_item_xy(canvas):
    for _key, _name, pair in canvas._channel_lines.composite_items():
        data = pair[1].plot_data_item.getData()
        return np.asarray(data[0], dtype=float), np.asarray(data[1], dtype=float)
    pytest.fail("画布没有 PlotDataItem")


def _finite_endpoints(values):
    array = np.asarray([] if values is None else values, dtype=float)
    if array.size == 0:
        return None, None, 0
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return None, None, 0
    return float(finite[0]), float(finite[-1]), int(finite.size)


def test_custom_x_plot_item_uses_angle_on_attach_and_refresh(qapp, tmp_path):
    """R01: the drawn PlotDataItem X is the validated angle, not acquisition time."""
    from mf4_analyzer.ui.main_window.window import MainWindow
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    time, signal, angle = _angle_case()
    path = _write_angle_native(tmp_path / "angle.mf4", time, signal, angle)
    fd = DataLoader.load_mf4_native(str(path))
    canvas = TimeDomainCanvasPG()
    try:
        series = read_signal(fd, "sig")
        raw_time = np.array(series.time, copy=True)
        raw_values = np.array(series.values, copy=True)
        built = MainWindow._build_time_plot_data(
            _plot_host(fd, x_channel="angle"),
            checked=[("f0", "sig", "#1769e0")],
            range_enabled=False,
        )
        rows = [row for row in built.rows if "sig" in str(row[0])]
        assert rows, "sig 没有进入时域行"
        payload_x = np.asarray(rows[0][2], dtype=float)
        canvas.resize(2400, 800)
        canvas.show()
        canvas.plot_channels(built.rows, mode="single", xlabel="angle")
        QCoreApplication.processEvents()
        attach_x, _attach_y = _plot_item_xy(canvas)
        canvas._refresh_visible_data()
        QCoreApplication.processEvents()
        refresh_x, _refresh_y = _plot_item_xy(canvas)
        np.testing.assert_array_equal(np.asarray(series.time), raw_time)
        np.testing.assert_array_equal(np.asarray(series.values), raw_values)
        problems = []
        for label, drawn in (("attach", attach_x), ("refresh", refresh_x)):
            finite = drawn[np.isfinite(drawn)] if drawn.size else drawn
            if finite.size != angle.size or not np.allclose(finite, angle):
                problems.append(
                    f"{label} ends={_finite_endpoints(drawn)} "
                    f"payload_ends={_finite_endpoints(payload_x)}"
                )
        assert not problems, (
            "PlotDataItem X 必须是 angle（首尾 10 与 19.99），实际 "
            + "; ".join(problems)
        )
        assert _finite_endpoints(attach_x)[:2] == pytest.approx((10.0, 19.99))
        assert _finite_endpoints(refresh_x)[:2] == pytest.approx((10.0, 19.99))
        lo, hi = canvas.get_visible_xlim()
        assert lo == pytest.approx(10.0)
        assert hi == pytest.approx(19.99)
        assert "angle" in canvas.axes_list[0].get_xlabel()
        assert series.time.dtype == raw_time.dtype
        assert series.values.dtype == raw_values.dtype
    finally:
        canvas.close()
        fd.close_source()


def _write_channels(path, channels):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    for channel in channels:
        kwargs = {}
        invalidation = channel.get("invalidation")
        if invalidation is not None:
            kwargs["invalidation_bits"] = np.asarray(invalidation, dtype=np.uint8)
        mdf.append(Signal(
            samples=np.asarray(channel["samples"], dtype=float),
            timestamps=np.asarray(channel["timestamps"], dtype=float),
            name=channel["name"],
            unit=channel.get("unit") or "",
            **kwargs,
        ))
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _files_host(files, *, x_channel=None):
    spec = CustomXAxisSpec()
    if x_channel:
        spec = CustomXAxisSpec(
            mode="channel",
            resolver="per_source_name",
            channel=x_channel,
            label=x_channel,
        )
    table = dict(files)
    return SimpleNamespace(
        channel_list=SimpleNamespace(
            get_file_data=lambda key, sources=table: sources.get(key),
            checked_axis_groups=lambda: {},
        ),
        files=table,
        _active_time_curve_bindings=lambda view_idx=None: [],
        _custom_xaxis_spec=spec,
        navigator_order=None,
    )


def _draw(rows, *, mode="single", xlabel="Time (s)"):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(2400, 800)
    canvas.show()
    canvas.plot_channels(list(rows), mode=mode, xlabel=xlabel)
    QCoreApplication.processEvents()
    return canvas


def _curves(canvas):
    found = []
    for _key, name, pair in canvas._channel_lines.composite_items():
        pdi = pair[1].plot_data_item
        x, y = pdi.getData()
        found.append((
            str(name),
            np.asarray(x, dtype=float),
            np.asarray(y, dtype=float),
            pdi,
        ))
    return found


def _refresh_curves(canvas):
    canvas._refresh_visible_data()
    QCoreApplication.processEvents()
    return _curves(canvas)


def _assert_curve_xy(curve, expect_x, expect_y):
    _name, x, y, _pdi = curve
    np.testing.assert_allclose(x, np.asarray(expect_x, dtype=float), equal_nan=True)
    np.testing.assert_allclose(y, np.asarray(expect_y, dtype=float), equal_nan=True)


def test_time_and_custom_x_keep_range_gaps_and_single_points(qapp, tmp_path):
    from mf4_analyzer.ui.main_window.window import MainWindow

    time, signal, angle = _angle_case()
    path = _write_angle_native(tmp_path / "range.mf4", time, signal, angle)
    ranged = DataLoader.load_mf4_native(str(path))
    gap_path = _write_channels(tmp_path / "gaps.mf4", [
        {
            "name": "sig",
            "timestamps": [0.0, 0.1, 0.2, 0.3],
            "samples": [10.0, 20.0, 30.0, 40.0],
            "invalidation": [0, 1, 0, 0],
        },
        {
            "name": "angle",
            "timestamps": [0.0, 0.1, 0.2, 0.3],
            "samples": [5.0, 6.0, 7.0, 8.0],
            "unit": "deg",
        },
        {
            "name": "reset_sig",
            "timestamps": [0.0, 1.0, 0.2],
            "samples": [1.0, 2.0, 3.0],
        },
        {
            "name": "reset_angle",
            "timestamps": [0.0, 1.0, 0.2],
            "samples": [10.0, 11.0, 12.0],
            "unit": "deg",
        },
        {
            "name": "dot",
            "timestamps": [1.5],
            "samples": [4.0],
        },
        {
            "name": "dot_angle",
            "timestamps": [1.5],
            "samples": [42.0],
            "unit": "deg",
        },
        {
            "name": "hole_sig",
            "timestamps": [0.0, 1.0, 2.0],
            "samples": [1.0, 2.0, 3.0],
        },
        {
            "name": "hole_angle",
            "timestamps": [0.0, 1.0, 2.0],
            "samples": [10.0, np.nan, 12.0],
            "unit": "deg",
        },
    ])
    gaps = DataLoader.load_mf4_native(str(gap_path))
    canvases = []
    try:
        selected = np.arange(100, 201)
        for x_channel, expect_x in (
            (None, time[selected]),
            ("angle", angle[selected]),
        ):
            built = MainWindow._build_time_plot_data(
                _plot_host(ranged, x_channel=x_channel),
                checked=[("f0", "sig", "#1769e0")],
                range_enabled=True,
                range_lo=0.10,
                range_hi=0.20,
            )
            binding = built.rows[0][7]["display_binding"]
            np.testing.assert_array_equal(binding.record_indices, selected)
            np.testing.assert_allclose(np.asarray(binding.acquisition_time), time)
            np.testing.assert_allclose(np.asarray(binding.display_time), time)
            canvas = _draw(
                built.rows,
                xlabel="angle" if x_channel else "Time (s)",
            )
            canvases.append(canvas)
            _assert_curve_xy(_curves(canvas)[0], expect_x, signal[selected])
            _assert_curve_xy(_refresh_curves(canvas)[0], expect_x, signal[selected])

        gap_cases = (
            ("sig", None, [0.0, 0.1, 0.2, 0.3], [10.0, np.nan, 30.0, 40.0]),
            ("sig", "angle", [5.0, 6.0, 7.0, 8.0], [10.0, np.nan, 30.0, 40.0]),
            ("reset_sig", None, [0.0, 1.0, np.nan, 0.2], [1.0, 2.0, np.nan, 3.0]),
            ("reset_sig", "reset_angle", [10.0, 11.0, np.nan, 12.0], [1.0, 2.0, np.nan, 3.0]),
            ("dot", None, [1.5], [4.0]),
            ("dot", "dot_angle", [42.0], [4.0]),
            ("hole_sig", "hole_angle", [10.0, np.nan, 12.0], [1.0, np.nan, 3.0]),
        )
        for channel, x_channel, expect_x, expect_y in gap_cases:
            built = MainWindow._build_time_plot_data(
                _files_host({"f0": gaps}, x_channel=x_channel),
                checked=[("f0", channel, "#1769e0")],
                range_enabled=False,
            )
            assert built.rows, channel
            canvas = _draw(built.rows, xlabel=x_channel or "Time (s)")
            canvases.append(canvas)
            curve = _curves(canvas)[0]
            _assert_curve_xy(curve, expect_x, expect_y)
            refreshed = _refresh_curves(canvas)[0]
            _assert_curve_xy(refreshed, expect_x, expect_y)
            if len(expect_x) == 1:
                assert curve[3].opts.get("symbol") == "o"
                assert refreshed[3].opts.get("symbol") == "o"
            if np.isnan(np.asarray(expect_y, dtype=float)).any():
                assert refreshed[3].opts.get("connect") == "finite"
    finally:
        for canvas in canvases:
            canvas.close()
        ranged.close_source()
        gaps.close_source()


def test_same_name_custom_x_curves_stay_on_their_own_source(qapp, tmp_path):
    from mf4_analyzer.ui.main_window.window import MainWindow

    time = np.arange(4, dtype=float) / 4.0
    signal = np.sin(2.0 * np.pi * 3.0 * time)
    left = 10.0 + 10.0 * time
    right = 30.0 + 10.0 * time
    fd_left = DataLoader.load_mf4_native(str(_write_angle_native(
        tmp_path / "left.mf4", time, signal, left,
    )))
    fd_right = DataLoader.load_mf4_native(str(_write_angle_native(
        tmp_path / "right.mf4", time, signal, right,
    )))
    canvas = None
    try:
        built = MainWindow._build_time_plot_data(
            _files_host({"a": fd_left, "b": fd_right}, x_channel="angle"),
            checked=[("a", "sig", "#1769e0"), ("b", "sig", "#dc2626")],
            range_enabled=False,
        )
        canvas = _draw(built.rows, mode="subplot", xlabel="angle")
        curves = _refresh_curves(canvas)
        assert len(curves) == 2
        drawn = sorted(
            (float(curve[1][0]), curve[1]) for curve in curves
        )
        np.testing.assert_allclose(drawn[0][1], left)
        np.testing.assert_allclose(drawn[1][1], right)
    finally:
        if canvas is not None:
            canvas.close()
        fd_left.close_source()
        fd_right.close_source()


def test_custom_x_view_restore_settles_on_angle(qapp, tmp_path):
    from mf4_analyzer.ui.main_window.window import MainWindow

    time, signal, angle = _angle_case()
    fd = DataLoader.load_mf4_native(str(_write_angle_native(
        tmp_path / "restore.mf4", time, signal, angle,
    )))
    canvas = None
    try:
        built = MainWindow._build_time_plot_data(
            _plot_host(fd, x_channel="angle"),
            checked=[("f0", "sig", "#1769e0")],
            range_enabled=False,
        )
        canvas = _draw(built.rows, xlabel="angle")
        assert canvas._quality.timer.interval() == 150
        canvas.restore_visible_xlim((11.0, 18.0), flush=False)
        canvas.restore_visible_ylims({})
        canvas.settle_view_restore()
        QCoreApplication.processEvents()
        assert canvas._quality.timer.interval() == 150
        lo, hi = canvas.get_visible_xlim()
        assert lo == pytest.approx(11.0)
        assert hi == pytest.approx(18.0)
        _name, drawn, _y, _pdi = _curves(canvas)[0]
        finite = drawn[np.isfinite(drawn)]
        assert finite.size
        # Settlement envelopes a 25% X buffer, then clips to the angle union.
        # The samples must still be angle values, not the 0..0.999 clock.
        assert finite[0] == pytest.approx(10.0)
        assert finite[-1] > 18.0
        expected = angle[
            (angle >= float(finite[0]) - 1e-9)
            & (angle <= float(finite[-1]) + 1e-9)
        ]
        np.testing.assert_allclose(finite, expected)
        assert "angle" in canvas.axes_list[0].get_xlabel()
    finally:
        if canvas is not None:
            canvas.close()
        fd.close_source()


def test_duplicate_custom_x_is_not_read_as_a_unique_clock(qapp, tmp_path):
    from mf4_analyzer.ui.main_window.window import MainWindow
    from mf4_analyzer.ui.time_xaxis import CursorXAxisContext

    path = _write_channels(tmp_path / "dup.mf4", [
        {
            "name": "sig",
            "timestamps": [0.0, 1.0, 2.0],
            "samples": [10.0, 20.0, 30.0],
        },
        {
            "name": "angle",
            "timestamps": [0.0, 1.0, 2.0],
            "samples": [1.0, 1.0, 2.0],
            "unit": "deg",
        },
    ])
    fd = DataLoader.load_mf4_native(str(path))
    canvas = None
    try:
        built = MainWindow._build_time_plot_data(
            _files_host({"f0": fd}, x_channel="angle"),
            checked=[("f0", "sig", "#1769e0")],
            range_enabled=False,
        )
        canvas = _draw(built.rows, xlabel="angle")
        _assert_curve_xy(_curves(canvas)[0], [1.0, 1.0, 2.0], [10.0, 20.0, 30.0])
        canvas.set_cursor_x_axis_context(CursorXAxisContext(
            mode="channel", label="angle",
        ))
        custom = canvas.evaluate_single_cursor(1.0)
        # Existing exact-hit rule keeps the first display sample. It must not
        # collapse the repeated angle onto the unique acquisition time 1.0,
        # whose Y is 20.
        assert [float(branch.current_value) for branch in custom[0].branches] == [
            10.0
        ]
        canvas.set_cursor_x_axis_context(CursorXAxisContext(mode="time"))
        clock = canvas.evaluate_single_cursor(1.0)
        assert clock[0].current_value == pytest.approx(20.0)
        assert clock[0].sample_time == pytest.approx(1.0)
    finally:
        if canvas is not None:
            canvas.close()
        fd.close_source()


def test_mismatched_or_empty_bindings_do_not_invent_a_line(qapp, tmp_path):
    from mf4_analyzer.ui.main_window.window import MainWindow

    path = _write_channels(tmp_path / "short.mf4", [
        {
            "name": "sig",
            "timestamps": [0.0, 0.1, 0.2, 0.3, 0.4],
            "samples": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
        {
            "name": "angle",
            "timestamps": [0.0, 0.1],
            "samples": [10.0, 11.0],
            "unit": "deg",
        },
    ])
    fd = DataLoader.load_mf4_native(str(path))
    canvas = None
    empty = None
    try:
        built = MainWindow._build_time_plot_data(
            _files_host({"f0": fd}, x_channel="angle"),
            checked=[("f0", "sig", "#1769e0")],
            range_enabled=False,
        )
        assert any(issue.code == "unaligned" for issue in built.issues)
        assert built.rows == []
        canvas = _draw(built.rows)
        assert _curves(canvas) == []
        empty_built = MainWindow._build_time_plot_data(
            _files_host({"f0": fd}),
            checked=[],
            range_enabled=False,
        )
        assert empty_built.rows == []
        empty = _draw(empty_built.rows)
        assert _curves(empty) == []
        empty.show_empty_hint("当前时间范围内无可绘制数据 · 0/0")
        assert empty._empty_hint_text == "当前时间范围内无可绘制数据 · 0/0"
    finally:
        if canvas is not None:
            canvas.close()
        if empty is not None:
            empty.close()
        fd.close_source()


def _invalid_spike_channel():
    """Fs=1000, N=1000, zeros except index 500 = 1000 with invalidation."""
    count = 1000
    time = np.arange(count, dtype=np.float64) / 1000.0
    samples = np.zeros(count, dtype=np.float64)
    samples[500] = 1000.0
    invalidation = np.zeros(count, dtype=np.uint8)
    invalidation[500] = 1
    return {
        "name": "torque",
        "timestamps": time,
        "samples": samples,
        "invalidation": invalidation,
        "unit": "Nm",
    }


def _spike_filter_payload():
    return {
        "enabled": True,
        "spec": {
            "kind": "low",
            "order": 6,
            "cutoff": 50.0,
            "cutoff_lo": 100.0,
            "cutoff_hi": 2000.0,
        },
        "show_original": True,
        "show_filtered": True,
    }


def _companion_rows(rows):
    found = []
    for row in rows:
        meta = row[7] if len(row) >= 8 and isinstance(row[7], dict) else {}
        if meta.get("companion_of"):
            found.append(row)
    return found


def _sample_at(values, index):
    array = np.asarray([] if values is None else values, dtype=float)
    if array.size <= index:
        return None
    return float(array[index])


def test_invalid_thousand_spike_does_not_enter_the_time_filter(qapp, tmp_path, monkeypatch):
    """R02 production draw: an invalid 1000 pulse must not become a filter peak.

    The numeric oracle is the raw valid samples, which are zero. This does not
    compare the companion against a second call to the current filter.
    """
    from mf4_analyzer.ui.main_window.window import MainWindow

    path = _write_channels(tmp_path / "invalid-spike.mf4", [_invalid_spike_channel()])
    fd = DataLoader.load_mf4_native(str(path))
    canvas = None
    try:
        series = read_signal(fd, "torque")
        raw_values = np.array(series.values, copy=True)
        calls = []
        import mf4_analyzer.signal.filters as filters
        real_apply = filters.apply

        def spy(sig, spec, fs):
            calls.append(np.array(sig, copy=True))
            return real_apply(sig, spec, fs)

        monkeypatch.setattr(filters, "apply", spy)
        assert series.sampling.status == "known"
        assert float(series.sampling.fs_hz) == pytest.approx(1000.0)
        assert bool(np.asarray(series.validity)[500]) is True
        assert raw_values[500] == pytest.approx(1000.0)
        assert np.all(raw_values[np.arange(raw_values.size) != 500] == 0.0)
        host = _files_host({"f0": fd})
        host._filter_suffix = MainWindow._filter_suffix.__get__(host)
        built = MainWindow._build_time_plot_data(
            host,
            checked=[("f0", "torque", "#1769e0")],
            range_enabled=False,
            time_filter=_spike_filter_payload(),
        )
        companions = _companion_rows(built.rows)
        originals = [
            row for row in built.rows
            if "torque" in str(row[0]) and row not in companions
        ]
        assert originals, "原始扭矩曲线必须保留"
        canvas = _draw(built.rows)
        drawn = _curves(canvas)
        drawn_companions = [
            curve for key, curve in zip(
                (item[0] for item in canvas._channel_lines.composite_items()),
                drawn,
            )
            if key in canvas._companion_names or "Hz" in curve[0]
        ]
        if companions or drawn_companions or canvas._companion_names:
            payload_y = companions[0][3] if companions else None
            drawn_y = drawn_companions[0][2] if drawn_companions else None
            pytest.fail(
                "invalid 千值脉冲进入了滤波并留下 companion："
                f"payload[499]={_sample_at(payload_y, 499)!r} "
                f"payload[500]={_sample_at(payload_y, 500)!r} "
                f"drawn[499]={_sample_at(drawn_y, 499)!r} "
                f"drawn[500]={_sample_at(drawn_y, 500)!r} "
                f"companion_names={sorted(canvas._companion_names)!r} "
                f"issues={[getattr(issue, 'detail', '') for issue in built.issues]!r}"
            )
        assert built.issues, "拒绝 companion 时必须给出通道和原因"
        text = " ".join(
            f"{issue.target_channel} {issue.detail}" for issue in built.issues
        )
        assert "torque" in text
        assert ("有效段" in text) or ("缩小" in text)
        original_y = np.asarray(originals[0][3], dtype=float)
        finite = original_y[np.isfinite(original_y)]
        assert finite.size == 999
        assert np.all(finite == 0.0)
        drawn_originals = [curve for curve in drawn if curve not in drawn_companions]
        assert drawn_originals
        drawn_finite = drawn_originals[0][2][np.isfinite(drawn_originals[0][2])]
        assert drawn_finite.size
        assert np.max(np.abs(drawn_finite)) == 0.0
        np.testing.assert_array_equal(np.asarray(series.values), raw_values)
        assert not canvas._companion_names
        assert calls == []
    finally:
        if canvas is not None:
            canvas.close()
        fd.close_source()


def test_valid_segment_far_from_the_spike_filters_to_zero(qapp, tmp_path):
    """A long zero segment that does not reach the invalid pulse stays zero."""
    from mf4_analyzer.ui.main_window.window import MainWindow

    path = _write_channels(tmp_path / "valid-segment.mf4", [_invalid_spike_channel()])
    fd = DataLoader.load_mf4_native(str(path))
    canvas = None
    try:
        series = read_signal(fd, "torque")
        hi = float(series.time[180])
        host = _files_host({"f0": fd})
        host._filter_suffix = MainWindow._filter_suffix.__get__(host)
        built = MainWindow._build_time_plot_data(
            host,
            checked=[("f0", "torque", "#1769e0")],
            range_enabled=True,
            range_lo=float(series.time[0]),
            range_hi=hi,
            time_filter=_spike_filter_payload(),
        )
        companions = _companion_rows(built.rows)
        assert len(companions) == 1
        companion = np.asarray(companions[0][3], dtype=float)
        assert companion.shape == (181,)
        np.testing.assert_array_equal(companion, 0.0)
        canvas = _draw(built.rows)
        drawn = [
            curve for curve in _curves(canvas)
            if "Hz" in curve[0]
        ]
        assert drawn
        finite = drawn[0][2][np.isfinite(drawn[0][2])]
        assert finite.size
        assert np.max(np.abs(finite)) == 0.0
        assert not any(issue.code == "filter_quality" for issue in built.issues)
    finally:
        if canvas is not None:
            canvas.close()
        fd.close_source()


def test_invalid_spike_filter_keeps_custom_x_on_angle(qapp, tmp_path):
    """Filtering must not put the curve back on acquisition time."""
    from mf4_analyzer.ui.main_window.window import MainWindow

    time = np.arange(1000, dtype=np.float64) / 1000.0
    angle = 10.0 + 10.0 * time
    spike = _invalid_spike_channel()
    path = _write_channels(tmp_path / "angle-spike.mf4", [
        spike,
        {
            "name": "angle",
            "timestamps": time,
            "samples": angle,
            "unit": "deg",
        },
    ])
    fd = DataLoader.load_mf4_native(str(path))
    canvas = None
    try:
        host = _files_host({"f0": fd}, x_channel="angle")
        host._filter_suffix = MainWindow._filter_suffix.__get__(host)
        built = MainWindow._build_time_plot_data(
            host,
            checked=[("f0", "torque", "#1769e0")],
            range_enabled=False,
            time_filter=_spike_filter_payload(),
        )
        assert _companion_rows(built.rows) == []
        assert any(issue.code == "filter_quality" for issue in built.issues)
        originals = [
            row for row in built.rows if "torque" in str(row[0])
        ]
        assert originals
        canvas = _draw(built.rows, xlabel="angle")
        drawn = _curves(canvas)
        assert drawn
        assert not any("Hz" in curve[0] for curve in drawn)
        lo, hi, count = _finite_endpoints(drawn[0][1])
        assert count == 1000
        assert lo == pytest.approx(10.0)
        assert hi == pytest.approx(19.99)
        assert not canvas._companion_names
    finally:
        if canvas is not None:
            canvas.close()
        fd.close_source()


def _leaf_counts(widget):
    counts = {}
    root = widget.tree.topLevelItem(0)
    for index in range(root.childCount()):
        child = root.child(index)
        counts[child.text(0)] = child.text(1)
    return counts
