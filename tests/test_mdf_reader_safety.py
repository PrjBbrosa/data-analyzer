"""Risky native calls always run in a timed, supervised child interpreter."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


def run_child(code, *args):
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code, *map(str, args)],
        env={**os.environ, "PYTHONMALLOC": "debug"}, capture_output=True,
        text=True, timeout=45,
    )
    assert result.returncode == 0, f"child exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    return result.stdout


@pytest.mark.parametrize("shape", [(800, 1), (7, 6), (6, 7), (3, 3), (2, 3, 4), (5,)])
@pytest.mark.parametrize("inverse,dtype,cycles,compression", [
    (False, "<f4", 3, 0), (True, "<u2", 1, 0), (False, "<i2", 7, 2),
])
def test_native_array_values_all_coordinates(tmp_path, shape, inverse, dtype, cycles, compression):
    run_child('''
import ast, sys
import numpy as np
from asammdf import MDF
from tests._helpers.mf4_factory import write_array_mf4
path, expected = write_array_mf4(sys.argv[1], ast.literal_eval(sys.argv[2]),
    inverse=sys.argv[3] == 'True', dtype=sys.argv[4], cycles=int(sys.argv[5]),
    compression=int(sys.argv[6]), fragment_size=64)
with MDF(path) as mdf:
    group = mdf.groups[0]
    # Red on the old runtime before ANY potentially unsafe read. In-bounds
    # wrong layouts reach the value oracle instead of being missed by bounds.
    for channel in group.channels:
        assert channel.byte_offset + (channel.bit_count + 7)//8 <= group.channel_group.samples_byte_nr, channel.name
    for coord in np.ndindex(expected.shape[1:]):
        name = 'matrix' + ''.join(f'[{i}]' for i in coord)
        sig = mdf.get(name)
        np.testing.assert_array_equal(sig.samples, expected[(slice(None), *coord)], err_msg=name)
        assert sig.unit == 'V'
''', tmp_path / "array.mf4", repr(shape), inverse, dtype, cycles, compression)


def test_native_c_readers_inside_crossing_and_outside_record(tmp_path):
    run_child('''
import sys, zlib
from pathlib import Path
from asammdf.blocks import cutils, v4_constants as c
from asammdf.blocks.utils import DataBlockInfo
# Never invoke dangerous C on an unverified binary, including stale mixed installs.
assert getattr(cutils, 'TRACELAB_MDF_SAFETY', None) == 1
data = bytes(range(1, 9)); path = Path(sys.argv[1]); path.write_bytes(data)
block = DataBlockInfo(address=0, block_type=c.DT_BLOCK, original_size=8, compressed_size=8, param=0)
for offset, width, expected in [(1,2,b'\\2\\3\\6\\7'), (2,4,b'\\3\\4\\0\\0\\7\\10\\0\\0'), (6,2,b'\\0'*4), (1608,1,b'\\0'*2)]:
    assert cutils.get_channel_raw_bytes(data,4,offset,width) == expected
    (parallel,) = cutils.get_channel_raw_bytes_parallel(data,4,[(offset,width)],1)
    assert parallel == expected
    ((raw,_),) = cutils.get_channel_raw_bytes_complete([block], [(offset,width,-1)], str(path), 2,4,0,0)
    assert raw == expected
    # The complete path also decodes multiple compressed blocks; keep this tiny
    # instead of allocating the production fast-path threshold (200 MiB).
    packed = [zlib.compress(data[:4]), zlib.compress(data[4:])]
    path.write_bytes(b''.join(packed))
    blocks = [DataBlockInfo(address=0, block_type=c.DZ_BLOCK_DEFLATE, original_size=4, compressed_size=len(packed[0]), param=0),
              DataBlockInfo(address=len(packed[0]), block_type=c.DZ_BLOCK_DEFLATE, original_size=4, compressed_size=len(packed[1]), param=0)]
    ((raw,_),) = cutils.get_channel_raw_bytes_complete(blocks, [(offset,width,-1)], str(path), 2,4,0,0)
    assert raw == expected
    path.write_bytes(data)
''', tmp_path / "records.bin")


@pytest.mark.parametrize("field,value", [("byte_offset", -1), ("byte_offset", 9),
    ("bit_count", 65), ("bit_offset", 8), ("pos_invalidation_bit", 8)])
def test_invalid_fixed_channel_rejected_before_native_read(field, value):
    from types import SimpleNamespace
    from mf4_analyzer.io.mdf_reader import MdfSafetyError, _validate_channel
    channel = SimpleNamespace(channel_type=0, byte_offset=0, bit_offset=0,
        bit_count=8, flags=2, pos_invalidation_bit=0, name="bad")
    group = SimpleNamespace(channel_group=SimpleNamespace(samples_byte_nr=8, invalidation_bytes_nr=1))
    setattr(channel, field, value)
    with pytest.raises(MdfSafetyError):
        _validate_channel(group, channel)


def test_virtual_channel_has_no_fixed_record_offset():
    from types import SimpleNamespace
    from asammdf.blocks import v4_constants as c
    from mf4_analyzer.io.mdf_reader import _validate_channel
    _validate_channel(None, SimpleNamespace(channel_type=c.CHANNEL_TYPE_VIRTUAL))


@pytest.mark.parametrize("metadata_only", [True, False])
def test_array_budget_fails_before_expansion_or_get(tmp_path, metadata_only):
    from asammdf import MDF
    from mf4_analyzer.io.import_limits import ImportLimits, ImportResourceError, budget_context
    from mf4_analyzer.io.mdf_reader import open_mdf
    from tests._helpers.mf4_factory import write_array_mf4
    path, _ = write_array_mf4(tmp_path / "array.mf4", (7, 6))
    calls = []

    def factory(*args, **kwargs):
        calls.append(kwargs)
        return MDF(*args, **kwargs)

    factory.__module__ = "asammdf.mdf"
    with budget_context(ImportLimits(max_channels=10)):
        with pytest.raises(ImportResourceError):
            open_mdf(path, factory, metadata_only=metadata_only)
    assert calls == [{"add_array_components": False, "process_bus_logging": False}]


@pytest.mark.parametrize("metadata_only", [True, False])
@pytest.mark.parametrize("stale", ["python", "native"])
def test_mixed_or_unverified_runtime_never_expands_arrays(tmp_path, monkeypatch, metadata_only, stale):
    import asammdf
    from asammdf.blocks import cutils
    from mf4_analyzer.io.mdf_reader import open_mdf
    from tests._helpers.mf4_factory import write_array_mf4
    path, _ = write_array_mf4(tmp_path / "array.mf4", (6, 7))
    if stale == "python":
        monkeypatch.setattr(asammdf, "__version__", "8.8.32")
    else:
        monkeypatch.delattr(cutils, "TRACELAB_MDF_SAFETY", raising=False)
    with pytest.raises(ImportError, match="verified asammdf"):
        open_mdf(path, asammdf.MDF, metadata_only=metadata_only)


@pytest.mark.parametrize("version", ["2.14", "3.30"])
def test_legacy_mdf_load_and_metadata_keep_identity(tmp_path, version):
    import numpy as np
    from asammdf import MDF, Signal
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
    path = tmp_path / "legacy.mdf"
    with MDF(version=version) as mdf:
        mdf.append([Signal(np.array([1., 2., 3.]), np.array([0., 1., 2.]), name="sig", unit="V")])
        mdf.save(path, overwrite=True)
    frame, channels, units = DataLoader.load_mf4(path)
    np.testing.assert_array_equal(frame["sig"], [1., 2., 3.])
    assert channels == ["Time", "sig"]
    assert units["sig"] == "V"
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    probe, = adapter.probe_sources(str(path))
    loaded, = adapter.load_sources(str(path))
    assert probe.source_id == loaded.source_id


def test_array_metadata_and_loader_values_share_physical_identity(tmp_path):
    run_child('''
import sys
import numpy as np
from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
from tests._helpers.mf4_factory import write_array_mf4
path, expected = write_array_mf4(sys.argv[1], (2,3,4))
adapter = SourceAdapterRegistry.default().adapter_for(str(path))
probe, = adapter.probe_sources(str(path))
frame, channels, units = DataLoader.load_mf4(path)
for coord in np.ndindex(expected.shape[1:]):
    name = 'matrix' + ''.join(f'[{i}]' for i in coord)
    np.testing.assert_array_equal(frame[name], expected[(slice(None), *coord)])
    assert units[name] == probe.units[name] == 'V'
    assert tuple(frame.attrs['source_metadata']['channel_metadata'][name]['physical_occurrence']) == tuple(probe.metadata['channel_metadata'][name]['physical_occurrence'])
''', tmp_path / "array.mf4")


def test_array_probe_never_reads_samples(tmp_path, monkeypatch):
    from asammdf import MDF
    from asammdf.blocks.mdf_v4 import MDF4
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
    from tests._helpers.mf4_factory import write_array_mf4
    path, _ = write_array_mf4(tmp_path / "metadata.mf4", (6, 7))

    def forbidden(*args, **kwargs):
        pytest.fail("metadata probe read sample data")

    monkeypatch.setattr(MDF, "get", forbidden)
    monkeypatch.setattr(MDF4, "get", forbidden)
    probe, = SourceAdapterRegistry.default().probe_sources(path)
    assert len([name for name in probe.channel_names if name.startswith("matrix[")]) == 42


@pytest.mark.parametrize("metadata_only", [True, False])
@pytest.mark.parametrize("defect", ["channel", "block", "coverage", "invalidation"])
def test_bad_metadata_fails_before_get_and_closes(tmp_path, monkeypatch, metadata_only, defect):
    from asammdf import MDF
    from mf4_analyzer.io.mdf_reader import MdfSafetyError, open_mdf
    from tests._helpers.mf4_factory import write_single_channel_mf4
    path = write_single_channel_mf4(tmp_path / "bad.mf4")
    opened = []
    closed = []
    original_close = MDF.close

    def factory(*args, **kwargs):
        mdf = MDF(*args, **kwargs)
        opened.append(mdf)
        group = mdf.groups[0]
        if defect == "channel":
            group.channels[1].byte_offset = 1608
        elif defect == "block":
            group.data_blocks[0].address = mdf._mdf.file_limit + 1
        elif defect == "coverage":
            group.channel_group.cycles_nr += 100
        else:
            group.channels[1].flags |= 2
            group.channels[1].pos_invalidation_bit = 100
        return mdf

    def close(mdf):
        # __del__ also calls close. Never resurrect an object being finalized.
        closed.append(id(mdf))
        original_close(mdf)

    def forbidden(*args, **kwargs):
        pytest.fail("native get entered before layout validation")

    factory.__module__ = "asammdf.mdf"
    monkeypatch.setattr(MDF, "get", forbidden)
    monkeypatch.setattr(MDF, "close", close)
    with pytest.raises(MdfSafetyError):
        open_mdf(path, factory, metadata_only=metadata_only)
    assert opened and id(opened[0]) in closed


def test_full_load_reserves_alignment_before_native_get(tmp_path, monkeypatch):
    from asammdf import MDF
    from mf4_analyzer.io.import_limits import ImportLimits, ImportResourceError, budget_context
    from mf4_analyzer.io.mdf_reader import open_mdf
    from tests._helpers.mf4_factory import write_single_channel_mf4
    path = write_single_channel_mf4(tmp_path / "budget.mf4", samples=range(1000), timestamps=range(1000))
    # Metadata and raw buffers fit; conversion/alignment/frame copies do not.
    with budget_context(ImportLimits(max_memory_bytes=60_000)):
        with pytest.raises(ImportResourceError, match="alignment"):
            open_mdf(path, MDF)
