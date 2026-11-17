"""M5 raw export, recipe replay, and native event replay."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.acquisition_capture.backends import ReplayRecorderBackend
from mf4_analyzer.batch_output import NativeExportError, export_native_samples, write_image
from mf4_analyzer.io.channel_edit_log import replay
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
from mf4_analyzer.signal.channel_math import ChannelMath
from mf4_analyzer.signal.channel_recipe import make_dual, make_single


def _axis(axis_id, values):
    return AxisSpec(axis_id, f"clock-{axis_id}", "time", "s", np.asarray(values, dtype=np.float64))


def _channel(group, index, name, axis_id, raw, **kwargs):
    return ChannelSpec(group, index, name, axis_id, np.asarray(raw), **kwargs)


def _store():
    slow = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    fast = np.array([0.0, 0.05], dtype=np.float64)
    torque = np.array([2 ** 60 + 3, 2 ** 60 + 5, 2 ** 60 + 7], dtype=np.int64)
    speed = np.array([10.0, 12.5], dtype=np.float64)
    return NativeSignalStore.build("mdf:export", (
        _axis("slow", slow),
        _axis("fast", fast),
    ), (
        _channel(0, 1, "Torque", "slow", torque, unit="Nm", validity=np.array([False, True, False])),
        _channel(1, 1, "Speed", "fast", speed, unit="rpm"),
    ))


def _file(store=None):
    store = _store() if store is None else store
    return FileData.from_native_store("/data/steer.mf4", store)


def _read_csv(path):
    lines = [
        line for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return list(csv.DictReader(lines))


def test_long_table_roundtrip_keeps_time_quality_and_integers(tmp_path):
    fd = _file()
    result = export_native_samples(fd, tmp_path / "raw.csv", layout="long")
    assert result.kind == "original_samples"
    assert result.layout == "long"
    rows = _read_csv(result.paths[0])
    torque = [row for row in rows if row["channel"] == "Torque"]
    speed = [row for row in rows if row["channel"] == "Speed"]
    assert len(torque) == 3
    assert len(speed) == 2
    assert [float(row["time"]) for row in torque] == pytest.approx([0.0, 0.1, 0.2])
    assert [row["valid"] for row in torque] == ["1", "0", "1"]
    assert [int(row["value"]) for row in torque] == [2 ** 60 + 3, 2 ** 60 + 5, 2 ** 60 + 7]
    assert float(speed[1]["value"]) == 12.5
    assert "原始测量" not in " ".join(result.notes)


def test_coaxial_groups_do_not_fill_the_other_clock(tmp_path):
    result = export_native_samples(_file(), tmp_path / "groups.csv", layout="coaxial")
    assert result.kind == "original_samples"
    assert len(result.paths) == 2
    tables = {path.stem: _read_csv(path) for path in result.paths}
    slow = next(rows for name, rows in tables.items() if "slow" in name)
    fast = next(rows for name, rows in tables.items() if "fast" in name)
    assert len(slow) == 3
    assert len(fast) == 2
    assert "Speed" not in slow[0]
    assert "Torque" not in fast[0]
    assert all(row["Torque"] for row in slow)


def test_uniform_grid_is_explicit_and_not_called_original(tmp_path):
    with pytest.raises(NativeExportError, match="显式"):
        export_native_samples(_file(), tmp_path / "wide.csv", layout="uniform")
    result = export_native_samples(
        _file(),
        tmp_path / "wide.csv",
        layout="uniform",
        grid={
            "origin": 0.0,
            "fs_hz": 20.0,
            "start": -0.05,
            "stop": 0.1,
            "method": "linear",
            "invalid_policy": "empty",
            "gap_policy": "empty",
        },
    )
    assert result.kind == "derived_uniform_grid"
    text = Path(result.paths[0]).read_text(encoding="utf-8")
    assert "原始测量" not in text
    assert "派生" in text
    rows = _read_csv(result.paths[0])
    by_time = {float(row["time"]): row for row in rows}
    assert by_time[-0.05]["Torque"] == ""
    assert by_time[-0.05]["Speed"] == ""
    assert float(by_time[0.05]["Speed"]) == pytest.approx(12.5)
    assert by_time[0.05]["Torque"] == ""


def test_excel_keeps_big_integers_and_does_not_drop_the_tail(tmp_path):
    path = tmp_path / "raw.xlsx"
    result = export_native_samples(
        _file(), path, layout="long", max_data_rows=2,
    )
    from openpyxl import load_workbook

    book = load_workbook(result.paths[0])
    values = []
    for name in book.sheetnames:
        if name == "说明":
            continue
        sheet = book[name]
        header = [cell.value for cell in sheet[1]]
        value_at = header.index("value")
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[value_at] is not None:
                values.append(row[value_at])
    integers = [item for item in values if isinstance(item, str)]
    assert str(2 ** 60 + 3) in integers
    assert str(2 ** 60 + 7) in integers
    assert any("分片" in note or "行" in note for note in result.notes)
    assert len(values) == 5


def test_png_and_pdf_stay_on_the_render_contract(tmp_path):
    import inspect

    with pytest.raises(NativeExportError, match="PNG|PDF|渲染"):
        export_native_samples(_file(), tmp_path / "plot.png", layout="long")
    with pytest.raises(NativeExportError, match="PNG|PDF|渲染"):
        export_native_samples(_file(), tmp_path / "plot.pdf", layout="long")
    assert "render_batch_image" in inspect.getsource(write_image)


def test_replay_keeps_original_events_and_does_not_build_a_common_grid():
    fd = _file()
    source = ReplayRecorderBackend.source_from_native("/data/steer.mf4", fd)
    assert source.replay_mode == "native_events"
    assert len(source.events) == 5
    torque = [event for event in source.events if event.channel == "Torque"]
    assert [event.record for event in torque] == [0, 1, 2]
    assert [event.time_s for event in torque] == [0.0, 0.1, 0.2]
    assert [event.valid for event in torque] == [True, False, True]
    assert torque[1].value is None
    assert len(source.source_samples) == 4
    assert "公共时间" not in " ".join(source.notices)
    assert not any("shared" in str(source.source_metadata).lower() for _ in (0,))


def test_replay_duplicate_times_reset_and_single_point():
    duplicated = NativeSignalStore.build("mdf:dup", (
        _axis("t", [0.0, 0.0, 0.2]),
    ), (
        _channel(0, 1, "Torque", "t", [1.0, 2.0, 3.0], unit="Nm"),
    ))
    source = ReplayRecorderBackend.source_from_native("/data/dup.mf4", duplicated)
    times = [event.time_s for event in source.events]
    assert times == [0.0, 0.0, 0.2]
    assert [event.record for event in source.events] == [0, 1, 2]

    reset = NativeSignalStore.build("mdf:reset", (
        _axis("t", [0.0, 0.1, 0.0]),
    ), (
        _channel(0, 1, "Torque", "t", [1.0, 2.0, 9.0], unit="Nm"),
    ))
    waiting = ReplayRecorderBackend.source_from_native("/data/reset.mf4", reset)
    assert waiting.replay_mode == "segment_required"
    assert waiting.source_samples == []
    assert len(waiting.events) == 3
    assert any("段" in note for note in waiting.notices)
    chosen = ReplayRecorderBackend.source_from_native("/data/reset.mf4", reset, segment=0)
    assert [event.record for event in chosen.events] == [0, 1]
    assert chosen.replay_mode == "native_events"

    single = NativeSignalStore.build("mdf:one", (
        _axis("t", [1.25]),
    ), (
        _channel(0, 1, "Mark", "t", [4.0], unit="Nm"),
    ))
    one = ReplayRecorderBackend.source_from_native("/data/one.mf4", single)
    assert len(one.events) == 1
    assert one.events[0].time_s == 1.25
    assert any("单点" in note for note in one.notices)


def test_product_replay_entry_still_calls_load_mf4(monkeypatch):
    seen = {}

    def stop(name, path, **kwargs):
        seen["name"] = name
        raise RuntimeError("stop")

    monkeypatch.setattr(
        "mf4_analyzer.acquisition_capture.backends.run_import", stop,
    )
    with pytest.raises(RuntimeError, match="stop"):
        ReplayRecorderBackend.source_from_mf4("steer.mf4")
    assert seen["name"] == "load_mf4"


def test_recipe_inherits_axis_and_does_not_mutate_raw():
    slow_t = np.array([0.0, 1.0, 3.0], dtype=np.float64)
    fast_t = np.array([0.0, 0.5], dtype=np.float64)
    torque = np.array([0.0, 2.0, 8.0], dtype=np.float64)
    store = NativeSignalStore.build("mdf:recipe", (
        _axis("slow", slow_t),
        _axis("fast", fast_t),
    ), (
        _channel(0, 1, "Torque", "slow", torque, unit="Nm"),
        _channel(1, 1, "Speed", "fast", [10.0, 11.0], unit="rpm"),
    ))
    fd = FileData.from_native_store("/data/recipe.mf4", store)
    raw_before = store.channel("Torque").raw.tobytes()
    entry = make_single(
        "d_tq", "Nm/s", "derivative", "Torque", None,
        axis="inherit", representation="physical",
        source_revision=store.revision,
    )
    applied = replay(fd, [entry])
    assert applied[0].applied
    expected = ChannelMath.derivative(slow_t, torque)
    np.testing.assert_allclose(fd.logical_channels["d_tq"]["values"], expected)
    assert store.channel("Torque").raw.tobytes() == raw_before
    assert "d_tq" not in store.public_names()

    crossed = make_dual(
        "sum", "", "add", "Torque", "Speed",
        axis="slow", method="direct", segment=0, representation="physical",
    )
    skipped = replay(fd, [crossed])
    assert not skipped[0].applied
    assert "目标轴" in skipped[0].reason
    assert store.channel("Torque").raw.tobytes() == raw_before

    removed = replay(fd, [{"op": "remove", "names": ["Torque"]}])
    assert removed[0].applied
    assert "Torque" in store.public_names()
    assert "Torque" not in fd.get_signal_channels()
    assert store.channel("Torque").raw.tobytes() == raw_before


def test_recipe_reopen_recomputes_and_reports_source_change():
    store = NativeSignalStore.build("mdf:reopen", (
        _axis("slow", [0.0, 1.0, 2.0]),
    ), (
        _channel(0, 1, "Torque", "slow", [1.0, 3.0, 5.0], unit="Nm"),
    ))
    entry = make_single(
        "scaled", "Nm", "scale", "Torque", 2.0,
        axis="inherit", representation="physical",
        source_revision=store.revision, apply_status="derived_intent",
    )
    first = FileData.from_native_store("/data/reopen.mf4", store)
    replay(first, [entry])
    second = FileData.from_native_store("/data/reopen.mf4", store)
    again = replay(second, [entry.to_dict()])
    assert again[0].applied
    np.testing.assert_array_equal(
        second.logical_channels["scaled"]["values"],
        first.logical_channels["scaled"]["values"],
    )
    stale = make_single(
        "other", "Nm", "abs", "Torque", None,
        axis="inherit", representation="physical",
        source_revision="not-the-current-revision",
    )
    changed = replay(second, [stale])
    assert not changed[0].applied
    assert "来源已变化" in changed[0].reason


def test_known_gap_is_actionable():
    store = NativeSignalStore.build("mdf:gap", (
        _axis("t", [0.0, 0.1, 0.0, 0.1]),
    ), (
        _channel(0, 1, "Torque", "t", [1.0, 2.0, 3.0, 4.0], unit="Nm"),
    ))
    fd = FileData.from_native_store("/data/gap.mf4", store)
    entry = make_single(
        "d_tq", "Nm/s", "derivative", "Torque", None,
        axis="inherit", representation="physical",
    )
    skipped = replay(fd, [entry])
    assert not skipped[0].applied
    assert "缺口" in skipped[0].reason or "段" in skipped[0].reason
    chosen = make_single(
        "d0", "Nm/s", "derivative", "Torque", None,
        axis="inherit", representation="physical", segment=0,
    )
    applied = replay(fd, [chosen])
    assert applied[0].applied
    assert fd.logical_channels["d0"]["values"].shape == (2,)
