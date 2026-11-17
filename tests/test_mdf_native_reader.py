"""Native MF4 read, admission, and real broker roundtrip.

The product default stays ``load_mf4``. These tests call the explicit native
entry through the supervised child. A direct function call is not enough.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pytest

from mf4_analyzer.io.import_limits import ImportBudget, ImportLimits, default_limits
from mf4_analyzer.io.import_process import ImportProcessError, run_import


LEDGER_MEMORY = 498_988_944
LEDGER_OUTPUT = 249_494_472
LEDGER_REQUESTED = 638_740_162
LEDGER_CYCLES = 471_652
LEDGER_DATA_CHANNELS = 52
LEDGER_RECORD = 36_601_314
LEDGER_CATALOG = 2_197_504


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_pair(path):
    from asammdf import MDF, Signal

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    time = np.array([0.10, 0.11, 0.12], dtype="<f8")
    burst = np.array([0.0, 100.0, 0.0], dtype="<f8")
    other_t = np.array([0.0, 1.0, 1.0, 2.0], dtype="<f8")
    other = np.array([1.0, 2.0, 9.0, 4.0], dtype="<f8")
    wide_t = np.array([0.0, 1.0, 2.0], dtype="<f8")
    wide = np.array([1, 2**53 + 3, 5], dtype="<i8")
    mdf = MDF(version="4.10")
    mdf.append([
        Signal(burst, time, name="burst", unit="Nm"),
        Signal(np.array([1.0, 1.0, 1.0]), time, name="grid", unit="Nm"),
    ])
    mdf.append([Signal(other, other_t, name="dup", unit="Nm")])
    mdf.append([Signal(wide, wide_t, name="wide", unit="count")])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _oracle(path, group, index):
    from asammdf import MDF

    with MDF(str(path)) as src:
        signal = src.get(
            group=group, index=index, raw=True, ignore_invalidation_bits=True,
        )
        return (
            np.array(signal.samples, copy=True),
            np.array(signal.timestamps, copy=True),
            None if signal.invalidation_bits is None else np.array(signal.invalidation_bits, copy=True),
        )


def test_real_broker_native_matches_raw_oracle_and_keeps_hash(tmp_path):
    path = _write_pair(tmp_path / "测量 数据" / "扭矩 peak.mf4")
    digest = _sha256(path)
    loaded = run_import("load_mf4_native", path)
    assert _sha256(path) == digest
    assert getattr(loaded, "is_native", False) is True
    store = loaded.native_store
    from mf4_analyzer.io.signal_access import read_signal

    series = read_signal(loaded, "burst", representation="raw")
    samples, timestamps, _mask = _oracle(path, 0, 1)
    assert np.array_equal(np.asarray(series.values), samples)
    assert np.array_equal(np.asarray(series.time), timestamps)
    grid = read_signal(loaded, "grid", representation="raw")
    axis = store.axis(store.channel("burst").axis_id).values
    assert axis is store.axis(store.channel("grid").axis_id).values
    series_time = np.asarray(series.time)
    assert series_time is axis or np.shares_memory(series_time, axis)
    assert series_time.flags.writeable is False
    assert np.asarray(series.values).flags.writeable is False
    assert store.channel("burst").physical is store.channel("burst").raw
    assert store.channel("grid").raw.flags.writeable is False
    wide = read_signal(loaded, "wide", representation="raw")
    assert int(np.asarray(wide.values)[1]) == 2**53 + 3
    assert np.asarray(wide.values).dtype == np.dtype("<i8")
    dup = read_signal(loaded, "dup", representation="physical")
    assert np.array_equal(np.asarray(dup.values, dtype=float), [1.0, 2.0, 9.0, 4.0])
    assert np.asarray(grid.time) is not np.asarray(dup.time)
    assert "pickle" not in (tmp_path / "unused").name


def test_bad_native_file_then_real_broker_success(tmp_path):
    good = _write_pair(tmp_path / "ok.mf4")
    bad = tmp_path / "bad.mf4"
    bad.write_bytes(b"this is not an mdf")
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_mf4_native", bad)
    assert caught.value.code == "data_error"
    loaded = run_import("load_mf4_native", good)
    from mf4_analyzer.io.signal_access import read_signal

    series = read_signal(loaded, "burst", representation="raw")
    samples, timestamps, _mask = _oracle(good, 0, 1)
    assert np.array_equal(np.asarray(series.values), samples)
    assert np.array_equal(np.asarray(series.time), timestamps)


def _write_bulky(path):
    """Large enough that native admission exceeds a budget the worker RSS still fits."""
    from asammdf import MDF, Signal

    cycles = 800_000
    timestamps = np.arange(cycles, dtype="<f8") * 1e-4
    signals = [Signal(np.zeros(cycles, dtype="<f8"), timestamps, name=f"ch{index}", unit="Nm")
               for index in range(10)]
    mdf = MDF(version="4.10")
    mdf.append(signals)
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def test_native_resource_refusal_uses_real_broker_without_partial_registration(tmp_path):
    path = _write_bulky(tmp_path / "budget.mf4")
    registered = []
    limits = ImportLimits(max_memory_bytes=240 * 1024 * 1024, max_output_bytes=120 * 1024 * 1024)
    with pytest.raises(ImportProcessError) as caught:
        registered.append(run_import("load_mf4_native", path, limits=limits))
    error = caught.value
    assert error.code == "resource_limit"
    assert error.resource is not None
    assert error.resource.resource_kind == "memory_estimate"
    assert error.resource.numbers_available is True
    assert error.resource.requested is not None
    assert error.resource.requested > limits.max_memory_bytes
    assert registered == []
    assert not list(tmp_path.glob("tracelab-import-*"))


def test_native_cancel_does_not_register_a_partial_store(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process

    path = _write_pair(tmp_path / "cancel.mf4")
    requests = []

    def command(request):
        requests.append(request)
        return [sys.executable, "-c", "import time; time.sleep(30)"]

    monkeypatch.setattr(process, "_worker_command", command)
    registered = []
    started = __import__("time").monotonic()
    with pytest.raises(ImportProcessError) as caught:
        registered.append(run_import(
            "load_mf4_native", path,
            limits=replace(default_limits(), cancel_grace_seconds=0.1),
            cancel_check=lambda: __import__("time").monotonic() - started > 0.15,
        ))
    assert caught.value.code == "cancelled"
    assert registered == []
    assert requests and not requests[0].parent.exists()


def test_anonymous_native_fits_while_shared_axis_still_refuses():
    from types import SimpleNamespace

    from asammdf.blocks import v4_constants as c

    from mf4_analyzer.io.import_limits import ImportResourceError
    from mf4_analyzer.io.mdf_reader import _reserve_native_output, _reserve_shared_output

    def channel(*, master):
        return SimpleNamespace(
            data_type=c.DATA_TYPE_REAL_INTEL,
            bit_count=64,
            channel_type=c.CHANNEL_TYPE_MASTER if master else c.CHANNEL_TYPE_VALUE,
            sync_type=c.SYNC_TYPE_TIME if master else c.SYNC_TYPE_NONE,
            conversion=None,
            flags=0,
            name="time" if master else "sig",
        )

    count = LEDGER_DATA_CHANNELS + 1
    group = SimpleNamespace(
        channels=[channel(master=True), *[channel(master=False) for _ in range(LEDGER_DATA_CHANNELS)]],
        channel_dependencies=[None] * count,
        channel_group=SimpleNamespace(cycles_nr=LEDGER_CYCLES),
    )
    mdf = SimpleNamespace(groups=[group], version="4.10", masters_db={0: 0})
    limits = ImportLimits(max_memory_bytes=LEDGER_MEMORY, max_output_bytes=LEDGER_OUTPUT)
    native = ImportBudget(limits)
    native.reserve(LEDGER_RECORD, label="MDF record buffers")
    native.reserve(LEDGER_CATALOG, label="MDF channel metadata/array expansion")
    _reserve_native_output(mdf, native)
    assert native.used_bytes < LEDGER_MEMORY
    assert native.used_bytes != LEDGER_REQUESTED
    labels = [name for name, _amount, _unit in native._components]
    assert any("native" in name for name in labels)
    assert "MDF shared-axis conversion/alignment/frame" not in labels

    shared = ImportBudget(limits)
    shared.reserve(LEDGER_RECORD, label="MDF record buffers")
    shared.reserve(LEDGER_CATALOG, label="MDF channel metadata/array expansion")
    with pytest.raises(ImportResourceError) as caught:
        _reserve_shared_output(SimpleNamespace(groups=[group]), shared)
    assert caught.value.requested_bytes == LEDGER_REQUESTED
    assert shared.used_bytes == LEDGER_RECORD + LEDGER_CATALOG


def test_low_native_budget_fails_before_channel_get(tmp_path, monkeypatch):
    from asammdf import MDF

    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.loader import DataLoader

    path = _write_pair(tmp_path / "early.mf4")
    calls = []
    original = MDF.get

    def spy(self, *args, **kwargs):
        calls.append(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MDF, "get", spy)
    limits = ImportLimits(max_memory_bytes=4096, max_output_bytes=2048)
    with budget_context(limits):
        with pytest.raises(ImportResourceError) as caught:
            DataLoader.load_mf4_native(str(path))
    assert calls == []
    assert caught.value.resource_kind == "memory_estimate"
    assert caught.value.requested_bytes is not None
    text = str(caught.value)
    assert "638740162" not in text.replace(",", "")


def test_native_transport_checks_shape_sharing_and_rejects_pickle(tmp_path):
    from mf4_analyzer.io.import_transport import read_import_result, write_import_result
    from mf4_analyzer.io.loader import DataLoader

    path = _write_pair(tmp_path / "transport.mf4")
    loaded = DataLoader.load_mf4_native(str(path))
    directory = tmp_path / "sidecar"
    manifest = write_import_result(loaded, directory, request_id="native-request", max_bytes=8_000_000)
    text = manifest.read_text(encoding="utf-8")
    assert "pickle" not in text
    assert '"kind":"native"' in text or '"kind": "native"' in text
    restored = read_import_result(directory, request_id="native-request", max_bytes=8_000_000)
    assert restored.native_store.channel("burst").raw is not loaded.native_store.channel("burst").raw
    assert restored.native_store.axis(restored.native_store.channel("burst").axis_id).values is (
        restored.native_store.axis(restored.native_store.channel("grid").axis_id).values
    )
    assert restored.native_store.channel("burst").physical is restored.native_store.channel("burst").raw
    assert restored.native_store.channel("burst").raw.flags.writeable is False
    assert restored.native_store.channel("wide").raw.dtype == np.dtype("<i8")
    assert int(restored.native_store.channel("wide").raw[1]) == 2**53 + 3
    assert restored.native_store.channel("burst").physical_key.group == 0


def test_group_fragment_is_loaded_once(tmp_path, monkeypatch):
    from asammdf.blocks.mdf_v4 import MDF4

    from mf4_analyzer.io.loader import DataLoader

    path = _write_pair(tmp_path / "reuse.mf4")
    calls = []
    original = MDF4._load_data

    def spy(self, group, *args, **kwargs):
        calls.append(id(group))
        return original(self, group, *args, **kwargs)

    monkeypatch.setattr(MDF4, "_load_data", spy)
    DataLoader.load_mf4_native(str(path))
    assert len(calls) == 3
    assert len(set(calls)) == 3


def test_explicit_adapter_native_call_is_not_the_default_loader(tmp_path):
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    path = _write_pair(tmp_path / "adapter.mf4")
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    assert adapter.loader_name == "load_mf4"
    loaded, = adapter.load_native_sources(path)
    assert loaded.file_data.is_native is True
    from mf4_analyzer.io.signal_access import read_signal

    series = read_signal(loaded.file_data, "burst")
    assert float(np.asarray(series.values)[1]) == pytest.approx(100.0)


def test_enum_channel_shares_raw_across_transport(tmp_path):
    """Enum codes live on the raw buffer. That is not an identity conversion."""
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.import_transport import read_import_result, write_import_result
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.io.source_adapters import canonical_source_path, stable_source_id

    path = tmp_path / "enum.mf4"
    source_id = stable_source_id("mdf", canonical_source_path(path), "root")
    raw = np.array([2, 0, 1], dtype="<i8")
    store = NativeSignalStore.build(
        source_id,
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0, 2.0])),),
        (
            ChannelSpec(0, 0, "torque", "t", np.array([1.0, 2.0, 3.0]), unit="Nm"),
            ChannelSpec(
                0, 1, "state", "t", raw,
                conversion="enum", support_status="enum",
            ),
        ),
    )
    state = store.channel("state")
    assert state.conversion == "enum"
    assert state.physical is state.raw
    loaded = FileData.from_native_store(path, store)
    directory = tmp_path / "enum-sidecar"
    write_import_result(loaded, directory, request_id="enum-request", max_bytes=1_000_000)
    restored = read_import_result(directory, request_id="enum-request", max_bytes=1_000_000)
    restored_state = restored.native_store.channel("state")
    assert restored_state.conversion == "enum"
    assert restored_state.support_status == "enum"
    assert restored_state.physical is restored_state.raw
    assert restored_state.raw.dtype == np.dtype("<i8")
    assert restored_state.raw.tolist() == [2, 0, 1]
    torque = restored.native_store.channel("torque")
    assert torque.conversion == "identity"
    assert torque.physical is torque.raw


def test_repeated_display_names_survive_transport(tmp_path):
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.import_transport import read_import_result, write_import_result
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from mf4_analyzer.io.source_adapters import canonical_source_path, stable_source_id

    path = tmp_path / "same-name.mf4"
    source_id = stable_source_id("mdf", canonical_source_path(path), "root")
    store = NativeSignalStore.build(
        source_id,
        (AxisSpec("t", "clk", "time", "s", np.array([0.0, 1.0])),),
        (
            ChannelSpec(1, 2, "flag", "t", np.array([1.0, 0.0])),
            ChannelSpec(3, 4, "flag", "t", np.array([0.0, 5.0])),
        ),
    )
    assert len(set(store.public_names())) == 2
    loaded = FileData.from_native_store(path, store)
    directory = tmp_path / "same-name-sidecar"
    write_import_result(loaded, directory, request_id="same-name", max_bytes=1_000_000)
    restored = read_import_result(directory, request_id="same-name", max_bytes=1_000_000)
    names = restored.native_store.public_names()
    assert len(names) == 2
    assert len(set(names)) == 2
    values = {
        name: restored.native_store.channel(name).raw.tolist()
        for name in names
    }
    assert sorted(values.values()) == [[0.0, 5.0], [1.0, 0.0]]
