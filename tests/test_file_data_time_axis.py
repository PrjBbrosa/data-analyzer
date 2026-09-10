from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData, TimeAxisProvenance
from mf4_analyzer.signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE


def _jittered_file(*, n=64, fs=500.0, name="jitter.csv"):
    nominal_dt = 1.0 / fs
    dts = np.resize(np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), n - 1)
    time = np.concatenate(([0.0], np.cumsum(dts)))
    frame = pd.DataFrame({"time": time, "sig": np.arange(n, dtype=float)})
    return FileData(name, frame, list(frame.columns), {"sig": ""})


def test_auto_nonuniform_rebuild_stamps_auto_rebuilt_provenance():
    fd = _jittered_file()
    original_fs = float(fd.fs)
    original_source = fd._time_source
    jitter = fd.time_axis_relative_jitter()
    arr = np.asarray(fd.time_array, dtype=float)
    nominal_dt = 1.0 / original_fs
    expected_jitter = float(
        np.max(np.abs(np.diff(arr) - nominal_dt)) / nominal_dt
    )

    assert jitter == pytest.approx(expected_jitter)
    assert jitter > DEFAULT_TIME_JITTER_TOLERANCE
    assert fd.is_time_axis_uniform() is False
    assert fd.time_axis_provenance is None

    suggested = fd.suggested_fs_from_time_axis()
    fd.rebuild_time_axis(suggested, reason="auto_nonuniform")

    assert fd._time_source == "auto_rebuilt"
    assert fd.is_time_axis_uniform() is True
    provenance = fd.time_axis_provenance
    assert isinstance(provenance, TimeAxisProvenance)
    assert provenance.reason == "auto_nonuniform"
    assert provenance.method == "median_dt"
    assert provenance.original_fs == pytest.approx(original_fs)
    assert provenance.original_time_source == original_source
    assert provenance.estimated_fs == pytest.approx(float(suggested))
    assert provenance.relative_jitter == pytest.approx(expected_jitter)
    assert provenance.dt_min == pytest.approx(float(np.min(np.diff(arr))))
    assert provenance.dt_max == pytest.approx(float(np.max(np.diff(arr))))
    assert provenance.n_samples == len(arr)
    assert provenance.applied_at


def test_manual_rebuild_keeps_manual_time_source():
    fd = _jittered_file()
    fd.rebuild_time_axis(250.0, reason="manual")
    assert fd._time_source == "manual"
    assert fd.time_axis_provenance.reason == "manual"
    assert fd.time_axis_provenance.estimated_fs == pytest.approx(250.0)


def test_consecutive_rebuilds_record_the_immediate_previous_axis():
    fd = _jittered_file()
    first_fs = float(fd.fs)
    fd.rebuild_time_axis(200.0, reason="auto_nonuniform")
    assert fd.time_axis_provenance.original_fs == pytest.approx(first_fs)
    fd.rebuild_time_axis(400.0, reason="manual")
    assert fd._time_source == "manual"
    assert fd.time_axis_provenance.reason == "manual"
    assert fd.time_axis_provenance.original_fs == pytest.approx(200.0)
    assert fd.time_axis_provenance.original_time_source == "auto_rebuilt"


def test_project_restore_reason_does_not_force_manual_time_source():
    fd = _jittered_file()
    fd._time_source = "auto_rebuilt"
    fd.rebuild_time_axis(1000.0, reason="project_restore")
    assert fd._time_source == "auto_rebuilt"
    assert fd.time_axis_provenance.reason == "project_restore"


def test_provenance_round_trips_through_dict():
    fd = _jittered_file()
    fd.rebuild_time_axis(fd.suggested_fs_from_time_axis(), reason="auto_nonuniform")
    restored = TimeAxisProvenance.from_dict(fd.time_axis_provenance.to_dict())
    assert restored == fd.time_axis_provenance
    assert TimeAxisProvenance.from_dict(None) is None


def test_verified_zfd_fs_keeps_existing_time_and_nonzero_t0():
    t0, dt, n = 1.5, 2.0, 3
    time = t0 + np.arange(n, dtype=float) * dt
    frame = pd.DataFrame({"Time": time, "sig": [1.0, 2.0, 3.0]})
    fd = FileData(
        "x.zfd",
        frame,
        list(frame.columns),
        {"sig": ""},
        source_metadata={"zfd_import": {"time_step_s": dt}},
    )
    assert fd.time_array[0] == pytest.approx(1.5)
    assert fd.time_array[-1] == pytest.approx(5.5)
    assert fd.fs == pytest.approx(0.5)
    assert fd._time_source == "column"


def test_time_array_assignment_and_rebuild_bump_revision():
    frame = pd.DataFrame({"sig": np.arange(8, dtype=float)})
    fd = FileData("rev.csv", frame, ["sig"], {}, fs=1000.0)
    assert fd.time_axis_revision >= 1
    first = fd.time_axis_revision
    token = fd.source_instance_token
    assert token == id(fd)

    same_extent = np.arange(8, dtype=float) / 1000.0
    same_extent[1] += 1e-6
    fd.time_array = same_extent
    assert fd.time_axis_revision == first + 1
    assert float(fd.time_array[0]) == pytest.approx(0.0)
    assert float(fd.time_array[-1]) == pytest.approx(same_extent[-1])

    reused = fd.time_array
    reused[2] += 1e-6
    fd.time_array = reused
    assert fd.time_axis_revision == first + 2

    fd.rebuild_time_axis(500.0, reason="manual")
    assert fd.time_axis_revision == first + 3
    assert fd.source_instance_token == token

    other = FileData("other.csv", frame.copy(), ["sig"], {}, fs=1000.0)
    assert other.source_instance_token != token


def test_verified_zfd_fs_applies_to_one_point_time_column():
    frame = pd.DataFrame({"Time": [3.0], "sig": [7.0]})
    fd = FileData(
        "one.zfd",
        frame,
        list(frame.columns),
        {"sig": ""},
        source_metadata={"zfd_import": {"time_step_s": 0.004}},
    )
    assert fd.fs == pytest.approx(250.0)
    assert fd.time_array[0] == pytest.approx(3.0)
    assert fd._time_source == "column"
