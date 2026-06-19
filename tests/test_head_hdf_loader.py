from __future__ import annotations
import numpy as np
import pandas as pd
from mf4_analyzer.io.file_data import FileData


def test_filedata_carries_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0, 2.0], "L": [1.0, 2.0, 3.0]})
    fd = FileData(
        str(tmp_path / "x.hdf"), df, list(df.columns), {"L": "Pa"}, 0,
        source_metadata={"recording_date": "17.04.2026", "scan_mode": "x"},
        channel_metadata={"L": {"quantity": "sound pressure",
                                "db_reference": "2e-005", "calibration": 104.0}},
        label_suffix="24x")
    assert fd.source_metadata["recording_date"] == "17.04.2026"
    assert fd.channel_metadata["L"]["db_reference"] == "2e-005"
    assert fd.label_suffix == "24x"
    assert "24x" in fd.short_name


def test_filedata_backcompat_no_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0], "L": [1.0, 2.0]})
    fd = FileData(str(tmp_path / "y.hdf"), df, list(df.columns), {}, 0)
    assert fd.source_metadata == {}
    assert fd.channel_metadata == {}
