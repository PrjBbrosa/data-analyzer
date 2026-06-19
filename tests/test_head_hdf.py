# tests/test_head_hdf.py
from __future__ import annotations
import numpy as np
from tests._helpers.head_hdf_factory import write_head_hdf
import pytest
from mf4_analyzer.io.head_hdf import sniff_head_hdf, parse_head_hdf


def _two_channel_file(path, n_scans=4):
    fast = np.arange(n_scans * 2, dtype=float)          # factor 2
    slow = np.arange(n_scans, dtype=float) * 10.0        # factor 1
    return write_head_hdf(
        path, n_scans=n_scans, start_of_data=2048,
        channels=[
            {"name": "L", "factor": 2, "quantity": "sound pressure",
             "unit": "Pa", "calibration": 2.0, "db_reference": "2e-005",
             "moniker": "Audio.Decoded", "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 3.0, "samples": slow},
        ])


def test_factory_writes_signature_and_offset(tmp_path):
    p = _two_channel_file(tmp_path / "synth.hdf")
    raw = p.read_bytes()
    assert b"HEAD acoustics datafile format" in raw[:2048]
    # body floats == sum(factor)*n_scans == (2+1)*4 == 12
    body = raw[2048:]
    assert len(body) == 12 * 4


def test_sniff_true_false(tmp_path):
    p = _two_channel_file(tmp_path / "s.hdf")
    assert sniff_head_hdf(p) is True
    bad = tmp_path / "bad.hdf"
    bad.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 100)   # HDF5 magic
    assert sniff_head_hdf(bad) is False


def test_parse_header_fields_and_gbk(tmp_path):
    fast = np.arange(8, dtype=float)
    slow = np.arange(4, dtype=float)
    p = write_head_hdf(
        tmp_path / "g.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "输出轴 x", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.5, "db_reference": "1e-003",
             "moniker": "Audio.Decoded", "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 3.0, "samples": slow},
        ])
    hf = parse_head_hdf(p)
    assert hf.version == 4
    assert hf.byte_order == "Intel"
    assert hf.kind == "Time data"
    assert hf.start_of_data == 2048
    assert hf.n_scans == 4
    assert hf.ch_order == [(1, 2), (2, 1)]
    assert [c.name for c in hf.channels] == ["输出轴 x", "SP"]
    assert hf.channels[0].quantity == "acceleration"
    assert hf.channels[0].calibration == pytest.approx(1.5)
    assert hf.channels[0].db_reference == "1e-003"
    assert hf.channels[0].factor == 2
    assert hf.channels[1].factor == 1


def test_demux_native_samples(tmp_path):
    fast = np.arange(8, dtype=float)          # factor 2, n_scans 4 -> [0..7]
    slow = np.array([10., 20., 30., 40.])     # factor 1
    p = write_head_hdf(
        tmp_path / "d.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "L", "factor": 2, "quantity": "sound pressure",
             "unit": "Pa", "calibration": 1.0, "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0, "samples": slow},
        ])
    hf = parse_head_hdf(p)
    np.testing.assert_allclose(hf.channels[0].samples, fast)
    np.testing.assert_allclose(hf.channels[1].samples, slow)
    assert hf.channels[0].samples.size == 8
    assert hf.channels[1].samples.size == 4


def test_guard_rejects_non_float32(tmp_path):
    p = write_head_hdf(
        tmp_path / "i16.hdf", n_scans=4, start_of_data=2048,
        channels=[{"name": "L", "factor": 1, "quantity": "sound pressure",
                   "unit": "Pa", "calibration": 1.0, "impl_type": "INT16",
                   "samples": np.zeros(4)}])
    with pytest.raises(NotImplementedError, match="INT16"):
        parse_head_hdf(p)


def test_guard_rejects_non_time_data(tmp_path):
    p = write_head_hdf(
        tmp_path / "spec.hdf", n_scans=4, start_of_data=2048,
        kind="Spectrum data",
        channels=[{"name": "L", "factor": 1, "quantity": "x", "unit": "Pa",
                   "calibration": 1.0, "samples": np.zeros(4)}])
    with pytest.raises(NotImplementedError, match="Spectrum data"):
        parse_head_hdf(p)
