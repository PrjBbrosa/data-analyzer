# tests/test_head_hdf.py
from __future__ import annotations
import numpy as np
from tests._helpers.head_hdf_factory import write_head_hdf


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
