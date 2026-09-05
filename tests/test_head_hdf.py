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


def test_non_float32_channel_skipped_not_fatal(tmp_path):
    """A file with one FLOAT32 + one non-FLOAT32 channel must parse without error.

    The non-FLOAT32 channel's .samples must be None (demux skipped it);
    the FLOAT32 channel must have its samples populated.
    """
    fast = np.arange(4, dtype=float)  # factor 1, 4 scans -> 4 samples
    p = write_head_hdf(
        tmp_path / "mixed.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "L", "factor": 1, "quantity": "sound pressure",
             "unit": "Pa", "calibration": 1.0, "samples": fast},
            {"name": "CAN", "factor": 1, "quantity": "raw",
             "unit": "", "calibration": 1.0, "impl_type": "INT16",
             "samples": np.zeros(4)},
        ])
    hf = parse_head_hdf(p)
    # FLOAT32 channel L must have samples
    l_ch = next(c for c in hf.channels if c.name == "L")
    assert l_ch.samples is not None
    np.testing.assert_allclose(l_ch.samples, fast)
    # INT16 channel CAN must be skipped (samples=None)
    can_ch = next(c for c in hf.channels if c.name == "CAN")
    assert can_ch.samples is None


@pytest.mark.parametrize("n_scans", [0, 1, 3])
@pytest.mark.parametrize("raw_channel", [0, 1, 2])
def test_uint32_bits_are_not_converted_to_float64(tmp_path, n_scans, raw_channel):
    """Unsupported words may look like signaling NaNs, including between floats."""
    factors = [2, 1, 3]
    channels = [
        {"name": f"channel_{i}", "factor": factor, "quantity": "raw",
         "unit": "", "calibration": 1.0,
         "impl_type": "UINT32" if i == raw_channel else "FLOAT32",
         "samples": np.arange(n_scans * factor, dtype=float) + i * 10}
        for i, factor in enumerate(factors)
    ]
    p = write_head_hdf(tmp_path / "raw_bits.hdf", n_scans=n_scans,
                       channels=channels)
    raw = bytearray(p.read_bytes())
    words = np.frombuffer(raw, dtype="<u4", offset=4096).reshape(n_scans, sum(factors))
    offset = sum(factors[:raw_channel])
    words[:, offset:offset + factors[raw_channel]] = 0x7F800001
    p.write_bytes(raw)

    with np.errstate(invalid="raise"):
        hf = parse_head_hdf(p)

    for i, channel in enumerate(hf.channels):
        if i == raw_channel or n_scans == 0:
            assert channel.samples is None
        else:
            assert channel.samples.dtype == np.float64
            assert channel.samples.shape == (n_scans * factors[i],)
            np.testing.assert_array_equal(channel.samples, channels[i]["samples"])


def test_float32_nonfinite_values_remain_observable(tmp_path):
    p = write_head_hdf(
        tmp_path / "nonfinite.hdf", n_scans=4,
        channels=[{"name": "L", "factor": 1, "quantity": "raw", "unit": "",
                   "calibration": 1.0, "samples": np.zeros(4)}],
    )
    # Patch bytes directly: the factory's own float cast would quiet an sNaN.
    bits = np.array([0x7F800001, 0x7FC00000, 0x7F800000, 0xFF800000], dtype="<u4")
    p.write_bytes(p.read_bytes()[:4096] + bits.tobytes())
    with np.errstate(invalid="warn"), pytest.warns(RuntimeWarning, match="invalid value"):
        hf = parse_head_hdf(p)
    samples = hf.channels[0].samples
    assert samples.dtype == np.float64
    np.testing.assert_array_equal(samples, [np.nan, np.nan, np.inf, -np.inf])


def test_all_non_float32_channels_parse_without_error(tmp_path):
    """A file where ALL channels are non-FLOAT32 still parses (samples all None).

    The loader would raise ValueError (no live channels), but the parser itself
    must not raise.
    """
    p = write_head_hdf(
        tmp_path / "alluint.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "CAN1", "factor": 1, "quantity": "raw",
             "unit": "", "calibration": 1.0, "impl_type": "UINT32",
             "samples": np.zeros(4)},
            {"name": "CAN2", "factor": 1, "quantity": "raw",
             "unit": "", "calibration": 1.0, "impl_type": "UINT32",
             "samples": np.zeros(4)},
        ])
    hf = parse_head_hdf(p)
    assert all(c.samples is None for c in hf.channels)


def test_guard_rejects_non_time_data(tmp_path):
    p = write_head_hdf(
        tmp_path / "spec.hdf", n_scans=4, start_of_data=2048,
        kind="Spectrum data",
        channels=[{"name": "L", "factor": 1, "quantity": "x", "unit": "Pa",
                   "calibration": 1.0, "samples": np.zeros(4)}])
    with pytest.raises(NotImplementedError, match="Spectrum data"):
        parse_head_hdf(p)


def _strip_header_line(path, key_prefix: str) -> None:
    """Remove the first header line whose key matches ``key_prefix`` (ASCII)."""
    raw = path.read_bytes()
    # start_of_data still present so the parser can bound the ASCII header
    text = raw[:65536].decode("cp936", errors="replace")
    import re
    m = re.search(r"(?m)^start of data:\s*(\d+)", text)
    assert m is not None
    start = int(m.group(1))
    header = raw[:start].decode("cp936", errors="replace")
    body = raw[start:]
    kept = [
        line for line in header.splitlines()
        if not line.lower().lstrip(";").lstrip("#").lstrip().startswith(key_prefix)
    ]
    new_header = ("\r\n".join(kept) + "\r\n").encode("cp936").ljust(start, b" ")
    path.write_bytes(new_header + body)


def test_missing_ch_order_raises_header_error(tmp_path):
    """A5: missing ``ch order`` is a header-level failure (not silent demux skip)."""
    p = _two_channel_file(tmp_path / "no_order.hdf")
    _strip_header_line(p, "ch order:")
    with pytest.raises(ValueError, match=r"ch order"):
        parse_head_hdf(p)


def test_missing_nbr_of_scans_raises_header_error(tmp_path):
    """A5: missing ``nbr of scans`` is a header-level failure naming that row."""
    p = _two_channel_file(tmp_path / "no_scans.hdf")
    _strip_header_line(p, "nbr of scans:")
    with pytest.raises(ValueError, match=r"nbr of scans"):
        parse_head_hdf(p)
