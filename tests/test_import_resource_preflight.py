"""Read/allocation spies prove preflight safety without exhausting memory."""
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.ascii_format import _decode_lines
from mf4_analyzer.io.csv_format import _read_sniff_lines
from mf4_analyzer.io.zfd_format import ZFDError, load_zfd_groups
from tests.zfd_fixtures import pack_float32_record, pack_time_record, write_zfge2


@pytest.mark.parametrize("reader,limit", [
    (lambda path: _read_sniff_lines(path, 10), 65_536),
    (_decode_lines, 262_144),
])
def test_sniff_reads_bounded_bytes_even_for_long_line(tmp_path, monkeypatch, reader, limit):
    path = tmp_path / "long.txt"
    path.write_bytes(b"Time,signal\n0,1\n" + b"x" * (limit * 2))
    original_open = Path.open
    reads = []

    class ReadSpy:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def read(self, size=-1):
            reads.append(size)
            assert 0 <= size <= limit, "sniff attempted an unbounded read"
            return self.handle.read(size)

    def spy_open(self, *args, **kwargs):
        return ReadSpy(original_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", spy_open)
    assert reader(path) is not None
    assert reads == [limit]


@pytest.mark.parametrize("reader,limit", [
    (lambda path: _read_sniff_lines(path, 10), 65_536),
    (_decode_lines, 262_144),
])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_sniff_preserves_encoding_at_partial_character(tmp_path, reader, limit, encoding):
    path = tmp_path / "partial.txt"
    prefix = "Time,温度\n0,1\n".encode(encoding)
    if encoding == "utf-16":
        # Split a surrogate pair at the byte boundary.
        raw = prefix + "x".encode("utf-16-le") * ((limit - len(prefix) - 2) // 2)
        raw += "😀".encode("utf-16-le")
    else:
        raw = prefix + b"x" * (limit - len(prefix) - 1) + "温".encode("utf-8")
    path.write_bytes(raw)
    lines, detected = reader(path)
    assert detected == encoding
    assert lines[:2] == ["Time,温度", "0,1"]


def _no_arange(*args, **kwargs):
    pytest.fail("time axis allocated before preflight rejection")


@pytest.mark.parametrize("x,count", [(0, 2_147_483_647), (1, 1)])
def test_zfd_no_usable_measurement_never_allocates_axis(tmp_path, monkeypatch, x, count):
    path = write_zfge2(tmp_path / "no-match.zfd", records=[
        pack_time_record(count=count), pack_float32_record(values=[1.0], x=x),
    ])
    monkeypatch.setattr("mf4_analyzer.io.zfd_format.np.arange", _no_arange)
    with pytest.raises(ZFDError, match="没有可导入的测量通道"):
        load_zfd_groups(path)


def test_zfd_valid_prefix_does_not_hide_truncated_later_record(tmp_path, monkeypatch):
    path = write_zfge2(tmp_path / "late-truncated.zfd", records=[
        pack_time_record(count=2), pack_float32_record(values=[1, 2]),
        pack_float32_record(values=[3, 4]),
    ], truncate=1)
    monkeypatch.setattr("mf4_analyzer.io.zfd_format.np.arange", _no_arange)
    with pytest.raises(ZFDError, match="数据区不足"):
        load_zfd_groups(path)


def test_zfd_overflowing_endpoint_fails_before_axis(tmp_path, monkeypatch):
    path = write_zfge2(tmp_path / "overflow.zfd", records=[
        pack_time_record(count=3, dt=1e308), pack_float32_record(values=[1, 2, 3]),
    ])
    monkeypatch.setattr("mf4_analyzer.io.zfd_format.np.arange", _no_arange)
    with pytest.raises(ZFDError, match="时间溢出"):
        load_zfd_groups(path)


def _limits(nbytes, **kwargs):
    from mf4_analyzer.io.import_limits import ImportLimits
    return ImportLimits(max_memory_bytes=nbytes, **kwargs)


@pytest.mark.parametrize("hdf5", [False, True])
def test_mat_budget_rejects_before_materialization(tmp_path, monkeypatch, hdf5):
    from scipy import io
    import h5py
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.mat_format import load_mat_groups

    path = tmp_path / "oversize.mat"
    if hdf5:
        with h5py.File(path, "w", userblock_size=512) as hf:
            hf.create_dataset("signal", shape=(1, 100_000), dtype="f8")
        # A real MATLAB v7.3 header triggers scipy's HDF5 fallback.
        with path.open("r+b") as stream:
            stream.write(b"MATLAB 7.3 MAT-file".ljust(124, b" ") + b"\x00\x02IM")
        monkeypatch.setattr(h5py.Dataset, "__array__", lambda *a, **k: pytest.fail("HDF5 payload read"))
    else:
        io.savemat(path, {"signal": np.arange(100.)})
        monkeypatch.setattr(io, "loadmat", lambda *a, **k: pytest.fail("MAT payload read"))
    with budget_context(_limits(64)), pytest.raises(ImportResourceError):
        load_mat_groups(path)


def test_mat_hdf5_skips_unsupported_metadata_without_reading(tmp_path, monkeypatch):
    import h5py
    from mf4_analyzer.io.mat_format import _collect_h5py

    path = tmp_path / "mixed.mat"
    with h5py.File(path, "w") as hf:
        hf.create_dataset("signal", data=[[1., 2., 3.]])
        hf.create_dataset("text", data=[b"abc", b"def"])
        hf.create_dataset("refs", shape=(1, 3), dtype=h5py.ref_dtype)
        hf.create_dataset("tensor", shape=(2, 2, 2), dtype="f8")
    original = h5py.Dataset.__array__

    def guarded_array(self, *args, **kwargs):
        assert self.name == "/signal", "unsupported dataset materialized"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(h5py.Dataset, "__array__", guarded_array)
    series, skipped, lone = _collect_h5py(path)
    assert [name for name, _ in series] == ["signal"]
    np.testing.assert_array_equal(series[0][1], [1, 2, 3])
    assert set(skipped) == {"text", "refs", "tensor"}
    assert not lone


def test_zfd_budget_fails_before_axis(tmp_path, monkeypatch):
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    path = write_zfge2(tmp_path / "budget.zfd", records=[
        pack_time_record(count=10), pack_float32_record(values=range(10)),
    ])
    monkeypatch.setattr("mf4_analyzer.io.zfd_format.np.arange", _no_arange)
    with budget_context(_limits(path.stat().st_size + 80)), pytest.raises(ImportResourceError):
        load_zfd_groups(path)


def test_wwt_cumulative_zeit_budget_stops_second_axis(tmp_path, monkeypatch):
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.wwt_document import parse_wwt_document
    from tests._helpers import wwt_factory as wwt

    path = wwt.write_wwt_file(tmp_path / "cumulative.wwt", [
        wwt.WwtRecordSpec("Zeit", "first", "s", n=100),
        wwt.WwtRecordSpec("Zeit", "second", "s", n=100),
    ])
    calls = []
    original = np.arange

    def counted_axis(*args, **kwargs):
        calls.append(args[0])
        assert len(calls) == 1, "second axis allocated past cumulative budget"
        return original(*args, **kwargs)

    monkeypatch.setattr("mf4_analyzer.io.wwt_document.np.arange", counted_axis)
    with budget_context(_limits(path.stat().st_size + 100 * 8 * 4)), pytest.raises(ImportResourceError):
        parse_wwt_document(path)
    assert calls == [100]


def test_head_budget_stops_before_demux(tmp_path, monkeypatch):
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.head_hdf import parse_head_hdf
    from tests._helpers.head_hdf_factory import write_head_hdf
    path = write_head_hdf(tmp_path / "budget.hdf", n_scans=4, channels=[
        {"name": "signal", "factor": 1, "samples": np.arange(4.),
         "quantity": "raw", "unit": "", "calibration": 1.0},
    ])
    monkeypatch.setattr("mf4_analyzer.io.head_hdf._demux", lambda *a, **k: pytest.fail("payload read"))
    with budget_context(_limits(64)), pytest.raises(ImportResourceError):
        parse_head_hdf(path)


@pytest.mark.parametrize("format_name", ["zfd", "mat", "wwt", "head"])
def test_format_budget_exact_boundary_and_next_import(tmp_path, format_name):
    from scipy.io import savemat
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.mat_format import load_mat_groups
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.io.head_hdf import parse_head_hdf
    from tests._helpers import wwt_factory as wwt
    from tests._helpers.head_hdf_factory import write_head_hdf

    path = tmp_path / f"boundary.{format_name}"
    if format_name == "zfd":
        write_zfge2(path, records=[pack_time_record(count=8),
                                  pack_float32_record(values=range(8))])
        load = load_zfd_groups
    elif format_name == "mat":
        savemat(path, {"time": np.arange(8.) * 0.25, "signal": np.arange(8.)})
        load = load_mat_groups
    elif format_name == "wwt":
        wwt.write_wwt_file(path, [
            wwt.WwtRecordSpec("Zeit", "Time", "s", n=100),
            wwt.WwtRecordSpec("Real", "signal", values=np.arange(100.)),
            wwt.WwtRecordSpec("Pars", "twice", n=100, formula="k1*2"),
        ], (wwt._single_channel_window(1, "signal", ""),))
        load = load_wwt_document
    else:
        write_head_hdf(path, n_scans=8, channels=[
            {"name": "signal", "factor": 1, "samples": np.arange(8.),
             "quantity": "raw", "unit": "", "calibration": 1.0},
        ])
        load = parse_head_hdf
    with budget_context(_limits(1024 * 1024)) as budget:
        load(path)
        required = budget.used_bytes
    assert required > 0
    with budget_context(_limits(required - 1)), pytest.raises(ImportResourceError):
        load(path)
    # Failure must leave no process-global consumption in the next import.
    with budget_context(_limits(required)):
        load(path)


def test_wwt_formula_checks_actual_leaf_size_before_evaluation(tmp_path, monkeypatch):
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.wwt_document import load_wwt_document, parse_wwt_document
    from tests._helpers import wwt_factory as wwt

    path = wwt.write_wwt_file(tmp_path / "formula.wwt", [
        wwt.WwtRecordSpec("Zeit", "Time", "s", n=100),
        wwt.WwtRecordSpec("Real", "signal", values=np.arange(100.)),
        wwt.WwtRecordSpec("Pars", "twice", n=1, formula="k1*2"),
    ], (wwt._single_channel_window(1, "signal", ""),))
    with budget_context(_limits(1024 * 1024)) as budget:
        parse_wwt_document(path)
        parsed_bytes = budget.used_bytes
    monkeypatch.setattr("mf4_analyzer.io.wwt_formula.evaluate_wwt_formulas",
                        lambda *a, **k: pytest.fail("formula evaluated before admission"))
    with budget_context(_limits(parsed_bytes + 100)), pytest.raises(ImportResourceError, match="formula"):
        load_wwt_document(path)


@pytest.mark.parametrize("format_name", ["v4", "v5"])
def test_mat_supported_variables_keep_values_and_skipped_order(tmp_path, format_name):
    from scipy.io import savemat
    from mf4_analyzer.io.mat_format import load_mat_groups
    path = tmp_path / "metadata.mat"
    values = np.array([[0., 2.], [0.5, 4.], [1., 6.]])
    savemat(path, {"complex": np.array([1j, 2j]), "text": "hello",
                  "matrix": values, "scalar": 3.}, format=format_name[-1])
    group, = load_mat_groups(path)
    np.testing.assert_array_equal(group["data"].to_numpy(), values)
    assert group["source_metadata"]["skipped_vars"] == ["complex", "text", "scalar"]


def test_mat_channel_budget_is_cumulative_before_loadmat(tmp_path, monkeypatch):
    from scipy import io
    from mf4_analyzer.io.import_limits import ImportResourceError, budget_context
    from mf4_analyzer.io.mat_format import load_mat_groups
    path = tmp_path / "wide.mat"
    io.savemat(path, {"first": np.ones((3, 2)), "second": np.ones((3, 2))})
    monkeypatch.setattr(io, "loadmat", lambda *a, **k: pytest.fail("payload read"))
    with budget_context(_limits(1024 * 1024, max_channels=3)), pytest.raises(ImportResourceError):
        load_mat_groups(path)
