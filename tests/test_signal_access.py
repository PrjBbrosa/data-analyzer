"""M1 read_signal and the explicit native FileData / adapter branch.

Product ``load_mf4`` stays the default. These tests never call it and never
expect ``DataLoader.load_mf4_native``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData, JobSourceHold, LegacyAxisUnavailable
from mf4_analyzer.io.native_signal_store import (
    AxisSpec,
    ChannelSpec,
    NativeSignalStore,
    SourceClosedError,
)
from mf4_analyzer.io.signal_access import (
    IndexSpan,
    SignalAccessError,
    TimeSpan,
    read_signal,
)
from mf4_analyzer.io.source_adapters import (
    SourceAdapterRegistry,
    SourceUnavailableError,
    canonical_source_path,
    stable_source_id,
)
from mf4_analyzer.io import source_adapters as adapters_module


class _CompareSpy(np.ndarray):
    """Records full-array ordering comparisons that would build a boolean mask."""

    def __new__(cls, values):
        base = np.asarray(values, dtype=np.float64).copy()
        base.setflags(write=False)
        obj = base.view(cls)
        obj._ops = []
        return obj

    def __array_finalize__(self, obj):
        if obj is not None:
            self._ops = getattr(obj, "_ops", [])

    def _record(self):
        self._ops.append(int(self.shape[0]))

    def __ge__(self, other):
        self._record()
        return np.ndarray.__ge__(self, other)

    def __le__(self, other):
        self._record()
        return np.ndarray.__le__(self, other)

    def __gt__(self, other):
        self._record()
        return np.ndarray.__gt__(self, other)

    def __lt__(self, other):
        self._record()
        return np.ndarray.__lt__(self, other)


def _native_file(path, axes, channels, source_id):
    store = NativeSignalStore.build(source_id, axes, channels)
    return FileData.from_native_store(path, store), store


def _pair(path):
    source_id = stable_source_id("mdf", canonical_source_path(path), "root")
    time = _CompareSpy([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    raw = np.arange(8, dtype=np.int64)
    raw.setflags(write=False)
    fd, store = _native_file(
        path,
        (AxisSpec("master", "ecu", "time", "s", time),),
        (ChannelSpec(0, 1, "torque", "master", raw, unit="Nm"),),
        source_id,
    )
    return fd, store, time, raw


def test_default_mdf_adapter_still_names_load_mf4():
    adapter = SourceAdapterRegistry.default().adapter_for("sample.mf4")
    assert adapter.loader_name == "load_mf4"


def test_native_filedata_refuses_shared_axis_fields_and_hides_no_table(tmp_path):
    path = tmp_path / "native.mf4"
    fd, store, _time, _raw = _pair(path)
    assert fd.is_native is True
    assert fd.native_store is store
    for attribute in ("time_array", "fs", "data", "time_axis_revision"):
        with pytest.raises(LegacyAxisUnavailable, match=attribute):
            getattr(fd, attribute)
    with pytest.raises(LegacyAxisUnavailable, match="data"):
        len(fd.data)
    with pytest.raises(LegacyAxisUnavailable, match="rebuild_time_axis"):
        fd.rebuild_time_axis(10.0)
    blobs = [value for value in vars(fd).values() if isinstance(value, np.ndarray)]
    assert blobs == []
    assert all(array.ndim == 1 for array in store.owned_arrays())
    assert fd.get_signal_channels() == ["torque"]


def test_contiguous_span_is_a_readonly_slice_without_a_full_mask(tmp_path):
    fd, _store, time, raw = _pair(tmp_path / "slice.mf4")
    time._ops.clear()
    series = read_signal(fd, "torque", TimeSpan(0.2, 0.5))
    assert series.public_name == "torque"
    assert series.unit == "Nm"
    assert series.representation == "physical"
    assert series.values.dtype == np.int64
    assert series.values.tolist() == [2, 3, 4, 5]
    assert series.time.tolist() == pytest.approx([0.2, 0.3, 0.4, 0.5])
    assert np.shares_memory(series.values, raw)
    assert np.shares_memory(series.time, time)
    assert series.values.flags.owndata is False
    assert series.values.flags.writeable is False
    assert series.time.flags.writeable is False
    assert series.index_start == 2 and series.index_stop == 6
    assert series.sample_index is None
    assert series.revision == fd.native_store.revision
    assert all(length != len(time) for length in time._ops)
    with pytest.raises(ValueError):
        series.values[0] = 0


def test_nonmonotonic_and_duplicate_reads_keep_sample_order(tmp_path):
    source_id = stable_source_id("mdf", canonical_source_path(tmp_path / "order.mf4"), "root")
    time = _CompareSpy([0.0, 1.0, 0.4, 0.4])
    raw = np.array([10, 20, 30, 40], dtype=np.int64)
    fd, _store = _native_file(
        tmp_path / "order.mf4",
        (AxisSpec("master", "ecu", "time", "s", time),),
        (ChannelSpec(0, 1, "torque", "master", raw, unit="Nm"),),
        source_id,
    )
    full = read_signal(fd, "torque")
    assert full.values.tolist() == [10, 20, 30, 40]
    assert full.time.tolist() == pytest.approx([0.0, 1.0, 0.4, 0.4])
    assert [(item.start, item.stop) for item in full.segments] == [(0, 2), (2, 4)]
    assert full.sampling.status == "unknown"
    assert full.sampling.fs_hz is None

    time._ops.clear()
    picked = read_signal(fd, "torque", TimeSpan(0.0, 0.5))
    assert picked.values.tolist() == [10, 30, 40]
    assert picked.sample_index.tolist() == [0, 2, 3]
    assert all(length != 4 for length in time._ops)

    both = read_signal(fd, "torque", TimeSpan(0.4, 0.4), segment=1)
    assert both.values.tolist() == [30, 40]
    assert both.index_start == 2 and both.index_stop == 4
    with pytest.raises(SignalAccessError, match="segment"):
        read_signal(fd, "torque", segment=3)


def test_empty_and_single_point_are_deterministic(tmp_path):
    source_id = stable_source_id("mdf", canonical_source_path(tmp_path / "short.mf4"), "root")
    empty_fd, _store = _native_file(
        tmp_path / "empty.mf4",
        (AxisSpec("t", "clk", "time", "s", np.array([], dtype=np.float64)),),
        (ChannelSpec(0, 1, "sig", "t", np.array([], dtype=np.int64)),),
        source_id,
    )
    empty = read_signal(empty_fd, "sig")
    assert empty.values.shape == (0,)
    assert empty.values.dtype == np.int64
    assert empty.sampling.status == "unknown"
    assert empty.segments == ()

    one_id = stable_source_id("mdf", canonical_source_path(tmp_path / "one.mf4"), "root")
    one_fd, _store = _native_file(
        tmp_path / "one.mf4",
        (AxisSpec("t", "clk", "time", "s", np.array([1.25])),),
        (ChannelSpec(0, 1, "sig", "t", np.array([7], dtype=np.int64)),),
        one_id,
    )
    one = read_signal(one_fd, "sig")
    assert one.time.tolist() == pytest.approx([1.25])
    assert int(one.values[0]) == 7
    assert one.sampling.status == "unknown"
    assert one.sampling.fs_hz is None
    missed = read_signal(one_fd, "sig", TimeSpan(0.0, 1.0))
    assert missed.values.shape == (0,)


def test_index_span_and_raw_representation_do_not_cast_int64(tmp_path):
    fd, _store, _time, raw = _pair(tmp_path / "raw.mf4")
    series = read_signal(fd, "torque", IndexSpan(1, 4), "raw")
    assert series.representation == "raw"
    assert series.values.dtype == np.int64
    assert series.values.tolist() == [1, 2, 3]
    assert np.shares_memory(series.values, raw)
    assert series.values.flags.owndata is False


def test_channel_lookup_uses_only_exact_names_and_known_mappings(tmp_path):
    source_id = stable_source_id("mdf", canonical_source_path(tmp_path / "names.mf4"), "root")
    axis = AxisSpec(
        "master", "ecu", "time", "s",
        np.array([0.0, 0.1, 0.2, 0.3]),
    )
    fd, store = _native_file(
        tmp_path / "names.mf4",
        (axis,),
        (
            ChannelSpec(0, 1, "Time", "master", np.array([10, 20, 30, 40])),
            ChannelSpec(1, 2, "Time", "master", np.array([1, 2, 3, 4])),
            ChannelSpec(0, 3, "sig", "master", np.array([4, 3, 2, 1])),
        ),
        source_id,
    )
    assert read_signal(fd, "Time [0:1]").values.tolist() == [10, 20, 30, 40]
    assert read_signal(fd, (1, 2)).values.tolist() == [1, 2, 3, 4]
    token = store.channel("sig").physical_key.token
    assert read_signal(fd, token).values.tolist() == [4, 3, 2, 1]
    with pytest.raises(SignalAccessError, match="Time"):
        read_signal(fd, "Time")
    with pytest.raises(SignalAccessError, match="sig"):
        read_signal(fd, "SIG")
    with pytest.raises(SignalAccessError):
        read_signal(fd, "si")
    with pytest.raises(TypeError):
        read_signal(fd, 1.5)
    with pytest.raises(SignalAccessError, match="representation"):
        read_signal(fd, "sig", representation="float")
    with pytest.raises(TypeError):
        read_signal(fd, "sig", span=(0.0,))


def test_enum_physical_is_rejected_and_raw_codes_remain(tmp_path):
    source_id = stable_source_id("mdf", canonical_source_path(tmp_path / "enum.mf4"), "root")
    fd, _store = _native_file(
        tmp_path / "enum.mf4",
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0])),),
        (ChannelSpec(
            0, 1, "state", "t", np.array([2, 0], dtype=np.int64),
            conversion="enum", support_status="enum",
        ),),
        source_id,
    )
    raw = read_signal(fd, "state", representation="raw")
    assert raw.values.dtype == np.int64
    assert raw.values.tolist() == [2, 0]
    with pytest.raises(SignalAccessError, match="枚举"):
        read_signal(fd, "state", representation="physical")


def test_source_close_and_job_hold_share_one_store(tmp_path):
    fd, store, _time, raw = _pair(tmp_path / "hold.mf4")
    hold = fd.job_hold()
    assert isinstance(hold, JobSourceHold)
    assert hold.file_data is fd
    assert hold.native_store is store
    series = read_signal(hold, "torque", IndexSpan(0, 2), "raw")
    assert np.shares_memory(series.values, raw)
    assert series.values.flags.owndata is False
    fd.close_source()
    with pytest.raises(SourceClosedError):
        read_signal(hold, "torque")
    with pytest.raises(SourceClosedError):
        read_signal(fd, "torque")


def test_native_payload_branch_keeps_root_id_and_skips_the_shared_table(tmp_path, monkeypatch):
    path = tmp_path / "payload.mf4"
    source_id = stable_source_id("mdf", canonical_source_path(path), "root")
    store = NativeSignalStore.build(
        source_id,
        (AxisSpec("slow", "a", "time", "s", np.array([0.0, 1.0])),
         AxisSpec("fast", "b", "time", "s", np.arange(5) / 10.0)),
        (
            ChannelSpec(0, 1, "torque", "slow", np.array([1.0, 2.0]), unit="Nm"),
            ChannelSpec(1, 1, "speed", "fast", np.arange(5), unit="rpm"),
        ),
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("native payload called the legacy loader")

    monkeypatch.setattr(adapters_module, "run_import", boom)
    monkeypatch.setattr(adapters_module, "frame_row_count", boom)
    adapter = SourceAdapterRegistry.default().adapter_for(path)
    loaded = adapter.load_native_payload(path, store)[0]
    assert loaded.group_id == "root"
    assert loaded.source_id == source_id
    assert loaded.file_data.native_store is store
    descriptor = adapters_module._descriptor_from_loaded(
        loaded, adapter_key="mdf", probe_cost="metadata",
    )
    assert descriptor.fs is None
    assert descriptor.metadata["sample_count"] is None
    assert descriptor.metadata["layout"] == "native"
    assert descriptor.metadata["channel_sample_counts"] == {"torque": 2, "speed": 5}
    assert descriptor.channel_names == ("torque", "speed")
    csv_adapter = SourceAdapterRegistry.default().adapter_for("plain.csv")
    with pytest.raises(SourceUnavailableError):
        csv_adapter.load_native_payload(path, store)


def test_legacy_formats_do_not_gain_a_fake_sampling_rate(tmp_path):
    generated = FileData(
        tmp_path / "plain.csv",
        pd.DataFrame({"torque": [1.0, 2.0, 3.0]}),
        ["torque"],
        {"torque": "Nm"},
        source_metadata={"source_kind": "csv"},
    )
    assert generated.fs == pytest.approx(1000.0)
    series = read_signal(generated, "torque")
    assert series.values.tolist() == pytest.approx([1.0, 2.0, 3.0])
    assert series.unit == "Nm"
    assert series.sampling.status == "unknown"
    assert series.sampling.fs_hz is None

    unknown = FileData(
        tmp_path / "ascii.asc",
        pd.DataFrame({"Time": [0.0], "force": [4.0]}),
        ["Time", "force"],
        {"force": "N"},
        source_metadata={"source_kind": "ascii", "verified_sample_rate": None},
    )
    one = read_signal(unknown, "force")
    assert one.time.tolist() == pytest.approx([0.0])
    assert one.sampling.status == "unknown"
    assert one.sampling.fs_hz is None

    measured = FileData(
        tmp_path / "sheet.csv",
        pd.DataFrame({"Time": [1.5, 1.6, 1.7], "torque": [3.0, 4.0, 5.0]}),
        ["Time", "torque"],
        {"torque": "Nm"},
        source_metadata={"source_kind": "csv"},
    )
    timed = read_signal(measured, "torque", TimeSpan(1.6, 1.7))
    assert timed.time.tolist() == pytest.approx([1.6, 1.7])
    assert timed.values.tolist() == pytest.approx([4.0, 5.0])
    assert timed.sampling.status == "known"
    assert timed.sampling.fs_hz == pytest.approx(10.0)

    estimated = FileData(
        tmp_path / "run.zfd",
        pd.DataFrame({"Zeit": [0.0, 0.001, 0.002], "force": [1.0, 2.0, 3.0]}),
        ["Zeit", "force"],
        {"force": "N"},
        source_metadata={
            "source_kind": "zfd",
            "fs_estimated": True,
            "zfd_import": {"time_step_s": 0.001},
        },
    )
    zfd = read_signal(estimated, "force")
    assert zfd.time.tolist() == pytest.approx([0.0, 0.001, 0.002])
    assert zfd.sampling.status == "estimated"
    assert zfd.sampling.fs_hz == pytest.approx(1000.0)
    with pytest.raises(SignalAccessError, match="force"):
        read_signal(estimated, "FORCE")


def test_neighbor_halo_keeps_bracketing_samples_outside_the_span():
    store = NativeSignalStore.build(
        "rpm",
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0, 2.0])),),
        (ChannelSpec(0, 1, "n_motor", "t", np.array([100.0, 200.0, 300.0]), unit="rpm"),),
    )
    fd = FileData.from_native_store("rpm.mf4", store)
    series = read_signal(
        fd, "n_motor", span=TimeSpan(0.2, 1.8), neighbor_halo=1,
    )
    assert series.time.tolist() == pytest.approx([0.0, 1.0, 2.0])
    clipped = read_signal(fd, "n_motor", span=TimeSpan(0.2, 1.8))
    assert clipped.time.tolist() == pytest.approx([1.0])


def test_native_facts_do_not_invent_a_file_level_axis():
    from mf4_analyzer.batch_export_size import source_size_facts
    from mf4_analyzer.io.signal_access import known_sampling_hz
    from mf4_analyzer.ui.main_window.analysis_time_range import axis_facts_from_files

    fast = np.arange(5) / 1000.0
    slow = np.array([0.0, 1.0, 2.0])
    store = NativeSignalStore.build(
        "mixed",
        (
            AxisSpec("fast", "clk-a", "time", "s", fast),
            AxisSpec("slow", "clk-b", "time", "s", slow),
        ),
        (
            ChannelSpec(0, 1, "torque", "fast", np.arange(5.0), unit="Nm"),
            ChannelSpec(1, 1, "n_motor", "slow", np.array([100.0, 200.0, 300.0]), unit="rpm"),
        ),
    )
    fd = FileData.from_native_store("mixed.mf4", store)
    with pytest.raises(LegacyAxisUnavailable):
        _ = fd.fs
    assert known_sampling_hz(fd, "torque") == pytest.approx(1000.0)
    assert known_sampling_hz(fd, "n_motor") == pytest.approx(1.0)
    facts = axis_facts_from_files({"f": fd}, [("f", "torque"), ("f", "n_motor")])
    assert facts[("f", "torque")][2] == 5
    assert facts[("f", "n_motor")][2] == 3
    assert facts[("f", "torque")][5] != facts[("f", "n_motor")][5]
    mixed = source_size_facts(fd)
    assert mixed["sample_count"] == 5
    assert mixed["sample_rate"] is None
    torque = source_size_facts(fd, "torque")
    assert torque["sample_rate"] == pytest.approx(1000.0)
    assert torque["sample_count"] == 5
