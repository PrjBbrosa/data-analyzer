"""ChannelFrame contract for lazy BLF tables (V8H-A05, V8H-A06)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

can = pytest.importorskip("can", reason="python-can not installed (win32-gated)")
cantools = pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.io.channel_frame import (  # noqa: E402
    ChannelFrame,
    UnsupportedChannelFrameOperation,
)
from mf4_analyzer.io.loader import DataLoader  # noqa: E402
from mf4_analyzer.io import blf_format  # noqa: E402
from tests._helpers.blf_factory import write_sample_blf, write_two_message_dbc  # noqa: E402


def _load_sample(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)
    return DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])


def test_load_blf_returns_channel_frame(tmp_path):
    data, _channels, _units = _load_sample(tmp_path)

    assert isinstance(data, ChannelFrame)
    assert data.is_channel_frame is True
    assert isinstance(data, blf_format.LazyZohFrame)


def test_single_column_access_does_not_materialize_other_zoh(tmp_path, monkeypatch):
    calls = []
    real = blf_format._zoh_resample

    def spy(ref_t, t, v):
        calls.append(1)
        return real(ref_t, t, v)

    monkeypatch.setattr(blf_format, "_zoh_resample", spy)
    data, _channels, _units = _load_sample(tmp_path)

    before = data.zoh_materialization_count()
    speed = data.get_column("Speed")
    after = data.zoh_materialization_count()
    materialized = set(data.materialized_column_names())

    assert before == 0
    assert after == 1
    assert len(calls) == 1
    assert "Speed" in materialized
    assert "Throttle" not in materialized
    transmitted = {20.0, 21.0, 22.0, 23.0, 24.0}
    assert set(np.unique(np.round(speed, 6))).issubset(transmitted)


def test_to_pandas_matches_small_existing_dataframe(tmp_path):
    data, channels, _units = _load_sample(tmp_path)
    pdf = data.to_pandas()
    alt = data.to_dataframe()

    assert list(pdf.columns) == list(channels)
    assert list(alt.columns) == list(channels)
    assert pdf["Time"].iloc[0] == pytest.approx(0.0)
    assert np.all(np.diff(pdf["Time"].to_numpy()) >= 0)
    assert pdf["EngineSpeed"].iloc[0] == pytest.approx(800.0)
    assert pdf["EngineSpeed"].max() == pytest.approx(1200.0)
    pd.testing.assert_frame_equal(pdf, alt)
    assert pdf["EngineSpeed"].dtype == np.float64
    assert pdf["Time"].dtype == np.float64


def test_load_blf_dataframe_materializes_only_when_opted_in(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)
    frame, channels, units = DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])
    pdf, pdf_channels, pdf_units = DataLoader.load_blf_dataframe(
        str(blf), dbc_paths=[str(dbc)],
    )

    assert isinstance(frame, ChannelFrame)
    assert isinstance(pdf, pd.DataFrame)
    assert pdf_channels == channels
    assert pdf_units == units
    pd.testing.assert_frame_equal(frame.to_pandas(), pdf)


def test_drop_columns_is_column_only_and_row_drop_raises(tmp_path):
    data, _channels, _units = _load_sample(tmp_path)
    dropped = data.drop_columns(["Throttle"])

    assert "Throttle" not in dropped.column_names()
    assert "EngineSpeed" in dropped.column_names()
    assert "Speed" in dropped.column_names()

    with pytest.raises(UnsupportedChannelFrameOperation, match="column"):
        data.drop(axis=0)
    with pytest.raises(UnsupportedChannelFrameOperation):
        data.drop(labels=[0], axis=0)
    with pytest.raises(UnsupportedChannelFrameOperation, match="inplace"):
        data.drop(columns=["Throttle"], inplace=True)


def test_duplicate_display_names_do_not_collapse_via_dict():
    t = np.array([0.0, 1.0])
    v1 = np.array([1.0, 2.0])
    frame = blf_format.LazyZohFrame(
        t,
        {"sig": (t, v1)},
        ["Time", "sig", "sig"],
    )

    names = list(frame.column_names())
    assert names == ["Time", "sig", "sig"]
    assert len(dict.fromkeys(names)) == 2
    pdf = frame.to_pandas()
    assert list(pdf.columns) == ["Time", "sig", "sig"]
    assert pdf.shape[1] == 3


def test_empty_single_point_nonfinite_and_t0_behavior_is_frozen():
    empty_t = np.array([], dtype=np.float64)
    empty = blf_format.LazyZohFrame(empty_t, {"A": (empty_t, empty_t)}, ["Time", "A"])
    assert empty.row_count() == 0
    assert np.isnan(empty.get_column("A")).all()

    t1 = np.array([5.0])
    v1 = np.array([42.0])
    single, channels, _units = blf_format._assemble_blf_channels(
        {"A": (t1, v1)}, {"A": "u"}, t0=5.0,
    )
    assert channels == ["Time", "A"]
    assert list(single.get_column("Time")) == pytest.approx([0.0])
    assert list(single.get_column("A")) == pytest.approx([42.0])

    t = np.array([1.0, 2.0, 3.0])
    v = np.array([np.nan, np.inf, -np.inf])
    nonfinite, _chs, _units = blf_format._assemble_blf_channels(
        {"A": (t, v)}, {"A": "u"}, t0=1.0,
    )
    values = nonfinite.get_column("A")
    assert np.isnan(values[0])
    assert np.isposinf(values[1])
    assert np.isneginf(values[2])

    shifted, _chs, _units = blf_format._assemble_blf_channels(
        {"A": (np.array([10.0, 11.0]), np.array([1.0, 2.0]))},
        {"A": "u"},
        t0=10.0,
    )
    assert list(shifted.get_column("Time")) == pytest.approx([0.0, 1.0])


def test_lazy_zoh_frame_remains_import_alias():
    from mf4_analyzer.io.blf_format import LazyZohFrame

    assert LazyZohFrame is blf_format.LazyZohFrame
    assert issubclass(LazyZohFrame, ChannelFrame)


def test_channel_frame_module_does_not_import_ui_or_renderer():
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import json
import sys
import mf4_analyzer.io.channel_frame
blocked = sorted(
    name for name in sys.modules
    if name == 'mf4_analyzer.ui'
    or name.startswith('mf4_analyzer.ui.')
    or name.startswith('mf4_analyzer.batch_render')
    or name == 'mf4_analyzer.ui.pg_canvas'
)
print(json.dumps(blocked))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
