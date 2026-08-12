"""D3/D4/A4 exit-side notice formatters + metadata contracts for load diagnostics."""
from __future__ import annotations

import numpy as np
import pytest
from nptdms import ChannelObject, TdmsWriter
from scipy.io import savemat

from mf4_analyzer.io.loader import (
    DataLoader,
    format_fs_estimated_notice,
    format_renamed_channels_notice,
    format_skipped_channels_notice,
    format_skipped_vars_notice,
)
from tests._helpers.head_hdf_factory import write_head_hdf


# ---------------------------------------------------------------- formatters

def test_format_skipped_channels_notice_names_and_dicts():
    assert format_skipped_channels_notice([]) == ""
    assert format_skipped_channels_notice(None) == ""
    plain = format_skipped_channels_notice(["Tol_oben", "Pars"])
    assert "2 个通道未导入" in plain
    assert "Tol_oben" in plain and "Pars" in plain
    typed = format_skipped_channels_notice([
        {"name": "Label", "reason": "non-numeric"},
        {"name": "Empty", "reason": "empty"},
    ])
    assert "2 个通道未导入" in typed
    assert "Label" in typed


def test_format_skipped_vars_notice():
    assert format_skipped_vars_notice([]) == ""
    assert format_skipped_vars_notice(None) == ""
    msg = format_skipped_vars_notice(["notes", "meta"])
    assert "2 个变量未导入" in msg
    assert "notes" in msg


def test_format_fs_estimated_notice_requires_estimate_wording():
    assert format_fs_estimated_notice(False) == ""
    assert format_fs_estimated_notice(None) == ""
    msg = format_fs_estimated_notice(True)
    assert "估算" in msg
    assert "ZFD" in msg
    assert "1 kHz" in msg or "1kHz" in msg or "1000" in msg


def test_format_renamed_channels_notice():
    assert format_renamed_channels_notice([]) == ""
    assert format_renamed_channels_notice(None) == ""
    msg = format_renamed_channels_notice([
        {"original": "Speed", "renamed": "Speed [2]"},
        {"original": "Speed", "renamed": "Speed [3]"},
    ])
    assert msg == "2 个通道重名，已加序号区分"


# ---------------------------------------------------------------- D4 metadata

def test_hdf_renamed_channels_recorded_in_source_metadata(tmp_path):
    n = 4
    dup = lambda s: {
        "name": "Com_Motor_Torque", "factor": 1, "quantity": "torque",
        "unit": "Nm", "calibration": 1.0, "samples": s,
    }
    p = write_head_hdf(
        tmp_path / "dup.hdf", n_scans=n, delta=1.0, start_of_data=4096,
        channels=[dup(np.zeros(n)), dup(np.arange(n, dtype=float))])
    groups = DataLoader.load_hdf(str(p))
    g = next(g for g in groups if "1x" in g["label_suffix"])
    renamed = g["source_metadata"].get("renamed_channels")
    assert renamed, "collision renames must be recorded in source_metadata"
    assert all("original" in r and "renamed" in r for r in renamed)
    assert any(r["original"] == "Com_Motor_Torque" for r in renamed)
    assert format_renamed_channels_notice(renamed)


def test_wwt_duplicate_names_record_renamed_channels(tmp_path):
    from tests.test_wwt_format import _make_header, _make_record

    n = 120
    vals_a = np.arange(n, dtype=np.float64)
    vals_b = vals_a + 10.0
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=vals_a.tobytes())
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=vals_b.tobytes())
    p = tmp_path / "dup.wwt"
    p.write_bytes(_make_header(3) + body)
    groups = DataLoader.load_wwt(str(p))
    assert len(groups) == 1
    g = groups[0]
    renamed = g["source_metadata"].get("renamed_channels")
    assert renamed and len(renamed) == 1
    assert renamed[0]["original"] == "Weg"
    assert renamed[0]["renamed"] != "Weg"
    assert "Weg" in g["channels"]
    assert renamed[0]["renamed"] in g["channels"]


def test_tdms_skipped_and_renamed_enter_source_metadata(tmp_path):
    path = tmp_path / "diag.tdms"
    props = {"wf_increment": 0.1, "wf_start_offset": 0.0}
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject(
                "G1", "Speed", np.array([1.0, 2.0, 3.0]),
                {**props, "unit_string": "rpm"},
            ),
            ChannelObject(
                "G2", "Speed", np.array([4.0, 5.0, 6.0]),
                {**props, "unit_string": "rpm"},
            ),
            ChannelObject(
                "G1", "Label", np.array(["a", "b", "c"]), props,
            ),
        ])

    data, channels, units, fs, smeta = DataLoader.load_tdms(path)
    assert smeta["source_kind"] == "tdms"
    skipped = smeta["skipped_channels"]
    assert skipped, "non-numeric Label must be recorded, not silently continue"
    assert any(
        isinstance(s, dict) and "Label" in str(s.get("name", ""))
        for s in skipped
    )
    assert any(
        isinstance(s, dict) and s.get("reason") == "non-numeric"
        for s in skipped
    )
    renamed = smeta.get("renamed_channels") or []
    assert renamed, "duplicate Speed names must record rename mapping"
    assert format_skipped_channels_notice(skipped)
    assert format_renamed_channels_notice(renamed)
    assert "Time" in channels
    assert data is not None and units is not None
    assert fs is None or isinstance(fs, (int, float))


def test_mat_skipped_string_var_recorded(tmp_path):
    p = tmp_path / "with_skip.mat"
    savemat(str(p), {
        "t": np.arange(8, dtype=float) * 0.001,
        "sig": np.arange(8, dtype=float),
        "notes": np.array(["hello"]),
    })
    groups = DataLoader.load_mat(str(p))
    skipped = groups[0]["source_metadata"]["skipped_vars"]
    assert "notes" in skipped
    assert format_skipped_vars_notice(skipped)


def test_zfd_estimated_notice_text():
    assert "估算" in format_fs_estimated_notice(True)
