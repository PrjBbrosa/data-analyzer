"""Numeric IPC fidelity and hostile-result boundaries; no native crash injection."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.import_transport import (
    ImportTransportError,
    ImportTransportLimitError,
    read_import_result,
    write_import_result,
)
from mf4_analyzer.io.loader import DataLoader

BUDGET = 16 * 1024 * 1024


def roundtrip(value, directory, budget=BUDGET):
    manifest = write_import_result(value, directory, request_id="request-中文", max_bytes=budget)
    assert manifest == directory / "manifest.json"
    return read_import_result(directory, request_id="request-中文", max_bytes=budget)


def assert_same(left, right):
    assert type(left) is type(right)
    if isinstance(left, np.ndarray):
        assert left.dtype == right.dtype
        assert left.flags.writeable == right.flags.writeable
        np.testing.assert_array_equal(left, right)
    elif isinstance(left, pd.DataFrame):
        pd.testing.assert_frame_equal(left, right)
        assert_same(left.attrs, right.attrs)
    elif is_dataclass(left):
        for field in fields(left):
            assert_same(getattr(left, field.name), getattr(right, field.name))
    elif isinstance(left, dict):
        assert list(left) == list(right)
        for key in left:
            assert_same(left[key], right[key])
    elif isinstance(left, (tuple, list)):
        assert len(left) == len(right)
        for a, b in zip(left, right):
            assert_same(a, b)
    elif isinstance(left, float) and np.isnan(left):
        assert np.isnan(right)
    else:
        assert left == right


def test_real_csv_loader_tuple(tmp_path):
    source = tmp_path / "测量.csv"
    source.write_text("Time,Torque\n0,1\n0.01,2\n0.02,3\n", encoding="utf-8")
    value = DataLoader.load_csv(source)
    assert_same(value, roundtrip(value, tmp_path / "transport"))


def test_real_mat_group_list(tmp_path):
    from scipy.io import savemat

    source = tmp_path / "groups.mat"
    savemat(source, {"t": np.arange(100) * .01, "Torque": np.arange(100.)})
    value = DataLoader.load_mat(source)
    assert isinstance(value, list)
    assert_same(value, roundtrip(value, tmp_path / "transport"))


def test_real_mdf_metadata_probe_and_scalar_load(tmp_path):
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry, _probe_mdf
    from tests._helpers.mf4_factory import write_single_channel_mf4

    path = write_single_channel_mf4(tmp_path / "scalar.mf4")
    adapter = SourceAdapterRegistry.default().adapter_for(path)
    value = _probe_mdf(str(path), adapter)
    assert_same(value, roundtrip(value, tmp_path / "probe"))
    value = DataLoader.load_mf4(path)
    assert_same(value, roundtrip(value, tmp_path / "samples"))


def test_real_dbc_probe_dataclass(tmp_path):
    from tests._helpers.blf_factory import write_two_message_dbc

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    value = DataLoader.probe_blf_dbc_frames([(0., 0x123, bytes(8))], [str(dbc)])
    assert_same(value, roundtrip(value, tmp_path / "probe"))


def test_dataframe_serialization_does_not_deepcopy_attrs(tmp_path, monkeypatch):
    frame = pd.DataFrame({"Time": np.arange(10.), "Signal": np.arange(10.)})
    samples = np.arange(100.)
    frame.attrs["record_arrays"] = [samples]

    def forbidden(*args, **kwargs):
        pytest.fail("creating Series may copy all record-store arrays")

    monkeypatch.setattr(pd.DataFrame, "_ixs", forbidden)
    out = roundtrip((frame, samples), tmp_path / "transport")
    assert out[0].attrs["record_arrays"][0] is out[1]


def test_real_wwt_document_keeps_catalog_references(tmp_path):
    from tests._helpers import wwt_factory as wwt

    value = DataLoader.load_wwt_document(wwt.channel_xy_with_auxiliaries(tmp_path / "layout.wwt"))
    result = roundtrip(value, tmp_path / "transport")
    assert_same(value, result)
    store = result.groups[0]["source_metadata"]["wwt_record_store"]
    assert store is result.document.records
    assert [r.index for r in result.document.records] == [r.index for r in value.document.records]


def test_actual_can_loader_stays_lazy_and_preserves_time_identity(tmp_path, monkeypatch):
    from mf4_analyzer.io import blf_format

    frames = [(10. + i, 0x100, bytes([i])) for i in range(6)]
    frames += [(10., 0x200, b"\x04"), (13., 0x200, b"\x08")]
    value = DataLoader.load_blf_frames(frames)
    frame = value[0]
    original_zoh = blf_format._zoh_resample

    def forbidden(*args):
        pytest.fail("transport materialized a CAN channel")

    monkeypatch.setattr(blf_format, "_zoh_resample", forbidden)
    result = roundtrip(value, tmp_path / "transport")
    out = result[0]
    assert type(out) is type(frame)
    assert_same(value[1:], result[1:])
    assert out.is_lazy()
    assert out.zoh_materialization_count() == 0
    assert out.materialized_column_names() == ("Time",)
    assert any(t is out._ref_t for t, _ in out._series.values())
    monkeypatch.setattr(blf_format, "_zoh_resample", original_zoh)
    for name in frame.column_names():
        np.testing.assert_array_equal(frame.get_column(name), out.get_column(name))


def test_request_dictionary_bytes_and_composite_keys(tmp_path):
    value = {"kwargs": {"frames": [(1., 0x123, b"\0\xff\x01"), (2., 4, b"")]},
             ("source-a", "Torque"): {"unit": "N·m"},
             ("source-b", "Torque"): [None, True, float("nan"), float("inf")]}
    assert_same(value, roundtrip(value, tmp_path / "transport"))


@pytest.mark.parametrize("warning_batch", [False, True])
def test_many_raw_can_frames_use_numeric_payloads_not_json_samples(tmp_path, warning_batch):
    from mf4_analyzer.io.can_frames import CanFrameBatch

    frames = [(i * .001, i % 4096, i.to_bytes(8, "little")) for i in range(120_000)]
    if warning_batch:
        frames = CanFrameBatch(frames, warnings=("ASC fallback 保留原诊断",))
    directory = tmp_path / "transport"
    result = roundtrip({"frames": frames}, directory, budget=64 * 1024 * 1024)
    assert result == {"frames": frames}
    assert type(result["frames"]) is type(frames)
    if warning_batch:
        assert result["frames"].warnings == frames.warnings
    assert (directory / "manifest.json").stat().st_size < 4096
    assert len(list(directory.glob("*.npy"))) == 3


def test_empty_can_batch_keeps_warnings(tmp_path):
    from mf4_analyzer.io.can_frames import CanFrameBatch

    result = roundtrip(CanFrameBatch(warnings=("no frames retained",)), tmp_path / "transport")
    assert type(result) is CanFrameBatch
    assert result == []
    assert result.warnings == ("no frames retained",)


def test_packed_can_budget_rejected_before_column_allocation(tmp_path, monkeypatch):
    frames = [(i * .001, i, b"12345678") for i in range(100)]
    monkeypatch.setattr(np, "empty", lambda *a, **k: pytest.fail("allocation before CAN budget check"))
    with pytest.raises(ImportTransportLimitError):
        roundtrip(frames, tmp_path / "transport", budget=4096)


def test_shared_arrays_detached_and_shapes_dtypes_gaps(tmp_path):
    axis = np.arange(9, dtype=">f8")[::2]
    axis.setflags(write=False)
    value = (axis, {("source", "Time"): axis},
             np.array([np.nan, np.inf, -np.inf, -1e300]),
             np.empty((0, 3), dtype=np.int16), np.array(3, dtype=np.uint64),
             np.asfortranarray(np.arange(12).reshape(3, 4)))
    directory = tmp_path / "transport"
    result = roundtrip(value, directory)
    assert result[0] is result[1][("source", "Time")]
    shutil.rmtree(directory)
    assert_same(value, result)
    assert all(not isinstance(x, np.memmap) for x in result if isinstance(x, np.ndarray))


def test_frame_columns_attrs_and_index_are_preserved(tmp_path):
    frame = pd.DataFrame({0: np.array([1, 2], dtype=np.int16), 1: [np.nan, 4.]})
    frame.columns = pd.Index([("source-a", "Time"), ("source-b", "Time")], tupleize_cols=False)
    frame.index = pd.Index(["sample-a", "sample-b"], name="row")
    frame.attrs = {"time_column": ("source-a", "Time"), "diagnostics": ("partial",)}
    assert_same(frame, roundtrip(frame, tmp_path / "transport"))


def alter_manifest(directory, edit):
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    edit(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("change", [
    lambda m: m.update(version=999),
    lambda m: m.update(request_id="other"),
    lambda m: m["files"][0].update(path="../outside.npy"),
    lambda m: m["files"][0].update(path="/tmp/outside.npy"),
    lambda m: m["files"][0].update(shape=[2**62]),
    lambda m: m["files"][0].update(dtype="|O"),
    lambda m: m["files"][0].update(nbytes=1),
    lambda m: m["nodes"][0].update(kind="arbitrary-class"),
    lambda m: m.update(root={"ref": 999999}),
])
def test_corrupt_manifest_rejected(tmp_path, change):
    directory = tmp_path / "transport"
    roundtrip(np.arange(5.), directory)
    alter_manifest(directory, change)
    with pytest.raises(ImportTransportError):
        read_import_result(directory, request_id="request-中文", max_bytes=BUDGET)


@pytest.mark.parametrize("damage", ["missing", "truncated", "payload", "symlink"])
def test_payload_corruption(tmp_path, damage):
    directory = tmp_path / "transport"
    roundtrip(np.arange(5.), directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    payload = directory / manifest["files"][0]["path"]
    if damage == "missing":
        payload.unlink()
    elif damage == "symlink":
        outside = tmp_path / "outside.npy"
        payload.rename(outside)
        payload.symlink_to(outside)
    else:
        data = bytearray(payload.read_bytes())
        if damage == "truncated":
            del data[-1:]
        else:
            data[-1] ^= 1
        payload.write_bytes(data)
    with pytest.raises(ImportTransportError):
        read_import_result(directory, request_id="request-中文", max_bytes=BUDGET)


def test_result_directory_cannot_redirect_outside_task(tmp_path):
    outside = tmp_path / "outside"
    roundtrip(np.arange(5.), outside)
    directory = tmp_path / "redirected"
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImportTransportError, match="symlink"):
        read_import_result(directory, request_id="request-中文", max_bytes=BUDGET)
    with pytest.raises(ImportTransportError, match="symlink"):
        write_import_result(None, directory, request_id="other", max_bytes=BUDGET)


def test_budget_is_checked_before_array_load(tmp_path, monkeypatch):
    directory = tmp_path / "transport"
    roundtrip(np.arange(10000.), directory)
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("allocated before budget validation"))
    with pytest.raises(ImportTransportLimitError):
        read_import_result(directory, request_id="request-中文", max_bytes=1000)


@pytest.mark.parametrize("value", [np.array([object()], dtype=object), object(), {1, 2}])
def test_unsupported_does_not_publish(tmp_path, value):
    directory = tmp_path / "transport"
    with pytest.raises(ImportTransportError):
        write_import_result(value, directory, request_id="a", max_bytes=BUDGET)
    assert not (directory / "manifest.json").exists()


def test_low_write_budget_no_success_prefix(tmp_path):
    directory = tmp_path / "transport"
    with pytest.raises(ImportTransportLimitError):
        write_import_result([np.arange(20.), np.arange(10000.)], directory,
                            request_id="a", max_bytes=1000)
    assert not (directory / "manifest.json").exists()
    assert not list(directory.iterdir())


def test_disk_failure_cleans_only_owned_files(tmp_path, monkeypatch):
    directory = tmp_path / "transport"
    directory.mkdir()
    existing = directory / "parent-owned.txt"
    existing.write_text("keep")

    def disk_full(stream, array, **kwargs):
        stream.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", disk_full)
    with pytest.raises(OSError, match="disk full"):
        write_import_result(np.arange(5.), directory, request_id="a", max_bytes=BUDGET)
    assert list(directory.iterdir()) == [existing]
    assert existing.read_text() == "keep"


def test_manifest_published_last_and_existing_result_not_overwritten(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_transport as transport

    directory = tmp_path / "transport"
    replace = transport.os.replace
    calls = []

    def check_atomic(source, target):
        assert not target.exists()
        manifest = json.loads(source.read_text())
        assert all((directory / f["path"]).exists() for f in manifest["files"])
        calls.append(target)
        replace(source, target)

    monkeypatch.setattr(transport.os, "replace", check_atomic)
    value = np.arange(5.)
    roundtrip(value, directory)
    assert calls == [directory / "manifest.json"]
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ImportTransportError, match="already published"):
        write_import_result(np.arange(10.), directory, request_id="other", max_bytes=BUDGET)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_exact_disk_budget_boundary(tmp_path):
    value = b"x" * 4096
    directory = tmp_path / "transport"
    roundtrip(value, directory)
    exact = sum(p.stat().st_size for p in directory.iterdir())
    assert read_import_result(directory, request_id="request-中文", max_bytes=exact) == value
    with pytest.raises(ImportTransportLimitError):
        read_import_result(directory, request_id="request-中文", max_bytes=exact - 1)
    assert roundtrip(value, tmp_path / "exact", budget=exact) == value
    with pytest.raises(ImportTransportLimitError):
        roundtrip(value, tmp_path / "under", budget=exact - 1)


def test_cycle_and_deep_metadata_rejected(tmp_path):
    cycle = []
    cycle.append(cycle)
    with pytest.raises(ImportTransportError, match="cyclic"):
        roundtrip(cycle, tmp_path / "cycle")
    nested = []
    for _ in range(100):
        nested = [nested]
    with pytest.raises(ImportTransportLimitError, match="depth"):
        roundtrip(nested, tmp_path / "deep")


def test_oversized_missing_and_broken_manifest(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_transport as transport

    directory = tmp_path / "transport"
    directory.mkdir()
    with pytest.raises(ImportTransportError):
        read_import_result(directory, request_id="a", max_bytes=BUDGET)
    manifest = directory / "manifest.json"
    manifest.write_text("{broken")
    with pytest.raises(ImportTransportError):
        read_import_result(directory, request_id="a", max_bytes=BUDGET)
    monkeypatch.setattr(transport, "_MAX_MANIFEST", 100)
    manifest.write_bytes(b" " * 101)
    with pytest.raises(ImportTransportLimitError):
        read_import_result(directory, request_id="a", max_bytes=BUDGET)


def test_bytes_use_one_sidecar_and_preserve_loaded_cache(tmp_path):
    from mf4_analyzer.io.blf_format import LazyZohFrame

    payloads = [bytes([n % 256]) for n in range(1000)]
    directory = tmp_path / "bytes"
    assert roundtrip(payloads, directory) == payloads
    assert len(list(directory.glob("*.bin"))) == 1
    time = np.arange(5.)
    frame = LazyZohFrame(time, {"slow": (time[::2], time[::2])}, ["Time", "slow"])
    frame.get_column("slow")
    frame["derived"] = time * 2
    out = roundtrip(frame, tmp_path / "cache")
    assert out.materialized_column_names() == frame.materialized_column_names()
    assert out.zoh_materialization_count() == frame.zoh_materialization_count()
    for name in frame.column_names():
        np.testing.assert_array_equal(frame.get_column(name), out.get_column(name))


def test_enum_channels_keep_shared_raw_and_reject_an_identity_lie(tmp_path):
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    time = np.arange(4, dtype=np.float64) / 100.0
    shared = np.array([0, 1, 0, 1], dtype=np.uint8)
    physical = np.array([0.0, 2.0, 0.0, 2.0])
    channels = [
        ChannelSpec(
            group=0, index=index, original_name=f"state{index}", axis_id="t",
            raw=shared, unit="", conversion="enum", support_status="enum",
        )
        for index in range(12)
    ]
    channels.append(ChannelSpec(
        group=0, index=20, original_name="scaled", axis_id="t",
        raw=shared.astype(np.float64), unit="Nm", physical=physical, conversion="library",
    ))
    store = NativeSignalStore.build(
        "enum-source",
        [AxisSpec("t", "clk", "time", "s", time)],
        channels,
    )
    source = FileData.from_native_store("enum.mf4", store)
    loaded = roundtrip(source, tmp_path / "enum")
    restored = loaded.native_store
    raws = [restored.channel(f"state{index}").raw for index in range(12)]
    assert all(array is raws[0] for array in raws)
    for index in range(12):
        channel = restored.channel(f"state{index}")
        assert channel.conversion == "enum"
        assert channel.support_status == "enum"
        assert channel.physical is channel.raw
        np.testing.assert_array_equal(channel.raw, shared)
    scaled = restored.channel("scaled")
    assert scaled.conversion == "library"
    assert scaled.physical is not scaled.raw
    assert restored.axis("t").sampling.status == "known"
    assert restored.axis("t").sampling.fs_hz == pytest.approx(100.0)

    directory = tmp_path / "tamper"
    write_import_result(source, directory, request_id="request-中文", max_bytes=BUDGET)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def _lie(node):
        if isinstance(node, dict):
            if node.get("conversion") == "enum" and node.get("physical_mode") == "shared":
                node["physical_mode"] = "identity"
                return True
            return any(_lie(value) for value in node.values())
        if isinstance(node, list):
            return any(_lie(value) for value in node)
        return False

    assert _lie(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ImportTransportError, match="identity physical must share raw"):
        read_import_result(directory, request_id="request-中文", max_bytes=BUDGET)


def test_module_does_not_import_qt_or_native_parsers():
    code = """
import sys
from mf4_analyzer.io.import_transport import write_import_result, read_import_result
for name in sys.modules:
    assert not name.startswith(('PyQt', 'PySide', 'mf4_analyzer.ui', 'asammdf', 'av.', 'h5py'))
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
