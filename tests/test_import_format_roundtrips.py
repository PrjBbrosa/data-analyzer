"""Real files through real parser children and detached result transport.

Each case covers success, corrupt input, child-side output admission and retry.
Crash/cancel/timeout supervision is shared and covered in test_import_process;
do not repeat native crash injection for every decoder here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import wave

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io import import_process
from mf4_analyzer.io.import_limits import ImportLimits
from mf4_analyzer.io.import_process import ImportProcessError, run_import
from mf4_analyzer.io.loader import DataLoader


# Fixed allowance for native-library startup, independent of machine free RAM.
# All generated payloads are small; the rejection gate lowers output only so
# it tests the real child's transport rather than an incidental RSS kill.
_LIMITS = ImportLimits(max_memory_bytes=1024 ** 3, max_output_bytes=16 * 1024 ** 2,
                       timeout_seconds=30., cancel_grace_seconds=.2)
_KINDS = ("csv", "ascii", "excel", "tdms", "wwt-document", "wwt-groups",
          "zfd", "mat-v5", "mat-v73", "head", "wav", "blf", "asc")


@dataclass
class _Case:
    method: str
    path: Path
    check: object
    kwargs: dict | None = None


def _equal(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12, equal_nan=True)


def _check_tabular(value, *, units):
    frame, channels, got_units = value[:3]
    assert isinstance(frame, pd.DataFrame)
    assert channels == ["Time", "Signal"]
    assert got_units == units
    _equal(frame["Time"], [1.5, 1.75, 2., 2.25])
    _equal(frame["Signal"], [2., np.nan, 6., 8.])
    metadata = frame.attrs["source_metadata"]
    assert metadata["time_column"] == "Time"
    assert metadata["import_diagnostics"]["state"] == "partial"


def _check_can(value):
    from mf4_analyzer.io.channel_frame import ChannelFrame

    frame, channels, units = value
    assert isinstance(frame, ChannelFrame)
    assert frame.is_lazy() and frame.zoh_materialization_count() == 0
    assert frame.materialized_column_names() == ("Time",)
    assert set(channels) == {"Time", "EngineSpeed", "Throttle", "Speed"}
    assert units == {"EngineSpeed": "rpm", "Throttle": "%", "Speed": "km/h"}
    # The EngineData raster has three samples and wins the existing longest
    # reference tie. Speed is offset by 0.05 s and must remain lazy until read.
    _equal(frame.get_column("Time"), [0., .125, .25])
    _equal(frame.get_column("EngineSpeed"), [800., 900., 1000.])
    _equal(frame.get_column("Throttle"), [10., 14.8, 20.])
    _equal(frame.get_column("Speed"), [20., 20., 21.])
    assert frame.zoh_materialization_count() == 1


def _case(tmp_path, kind):
    # Spaces and non-ASCII characters also exercise request path transport.
    root = tmp_path / "测量 files"
    root.mkdir()
    if kind in {"csv", "excel"}:
        if kind == "csv":
            path = root / "input.csv"
            path.write_text("Time,Signal\nms,N\n1500,2\n1750,broken\n2000,6\n2250,8\n")
            return _Case("load_csv", path, lambda value: _check_tabular(value, units={"Time": "s", "Signal": "N"}))
        pytest.importorskip("openpyxl")
        path = root / "input.xlsx"
        pd.DataFrame({"Time": [1.5, 1.75, 2., 2.25], "Signal": [2., "broken", 6., 8.]}).to_excel(path, index=False)
        return _Case("load_excel", path, lambda value: _check_tabular(value, units={}))

    if kind == "ascii":
        from tests.test_ascii_loader import _fixed_width_text

        path = root / "fixed.asc"
        path.write_text(_fixed_width_text())
        def check(value):
            frame, channels, units, fs, metadata = value
            assert channels == ["Load", "Speed"]
            assert units == {"Load": "Nm", "Speed": "rpm"}
            _equal(frame["Load"], np.arange(8))
            _equal(frame["Speed"], np.arange(8) * 10)
            assert fs == 2000. and metadata["ascii_kind"] == "fixed_width"
            assert metadata["time_axis_origin"] == "format_sampling_rate"
        return _Case("load_ascii", path, check)

    if kind == "tdms":
        tdms = pytest.importorskip("nptdms")
        path = root / "groups.tdms"
        timing = {"wf_increment": .25, "wf_start_offset": 1.5}
        with tdms.TdmsWriter(path) as writer:
            writer.write_segment([
                tdms.ChannelObject("A", "Signal", np.array([2., np.nan, 6., 8.]), {**timing, "unit_string": "N"}),
                tdms.ChannelObject("B", "Signal", np.array([4., 5., 6., 7.]), {**timing, "unit_string": "V"}),
            ])
        def check(value):
            frame, channels, units, fs, metadata = value
            assert channels == ["Time", "A.Signal", "B.Signal"] and fs is None
            assert units == {"A.Signal": "N", "B.Signal": "V"}
            _equal(frame["Time"], [1.5, 1.75, 2., 2.25])
            _equal(frame["A.Signal"], [2., np.nan, 6., 8.])
            _equal(frame["B.Signal"], [4., 5., 6., 7.])
            assert metadata["import_diagnostics"]["state"] == "partial"
        return _Case("load_tdms", path, check)

    if kind.startswith("wwt-"):
        from tests._helpers import wwt_factory as wwt
        from mf4_analyzer.io.wwt_document import WwtLoadResult

        a = np.arange(128.) * .25 - 2.
        a[10] = np.nan
        b = np.arange(100.) + 10.
        path = wwt.write_wwt_file(root / "groups.wwt", [
            wwt.WwtRecordSpec("Zeit", "TimeA", "s", n=128, dt=.01, t0=2.),
            wwt.WwtRecordSpec("Real", "Signal", "N", values=a),
            wwt.WwtRecordSpec("Pars", "Abs", "N", n=999, formula="abs(k1)"),
            wwt.WwtRecordSpec("Zeit", "TimeB", "s", n=100, dt=.02, t0=5.),
            wwt.WwtRecordSpec("Real", "Signal", "V", values=b),
        ], (wwt._single_channel_window(1, "Signal", "N"),))
        def check(value):
            if kind == "wwt-document":
                assert isinstance(value, WwtLoadResult)
                groups = value.groups
                records = value.document.records
                assert len(value.document.windows) == 1
                assert value.document.path == path
                assert [r.index for r in records] == list(range(5))
                assert records[2].formula == "abs(k1)" and records[2].declared_n == 999
                assert records[2].axis_record == 0
                _equal(records[2].values, np.abs(a))
                assert not records[1].values.flags.writeable
                for group in groups:
                    assert group["source_metadata"]["wwt_record_store"] is records
                assert value.document.groups[0] is groups[0]
            else:
                assert isinstance(value, list)
                groups = value
            assert len(groups) == 2
            assert len({g["label_suffix"] for g in groups}) == 2
            assert [g["source_metadata"]["zeit_record_indices"] for g in groups] == [(0,), (3,)]
            assert groups[0]["channel_metadata"]["Signal"]["record_index"] == 1
            assert groups[1]["channel_metadata"]["Signal"]["record_index"] == 4
            assert groups[0]["units"]["Signal"] == "N" and groups[1]["units"]["Signal"] == "V"
            _equal(groups[0]["data"]["Time"], 2. + np.arange(128) * .01)
            _equal(groups[1]["data"]["Time"], 5. + np.arange(100) * .02)
            _equal(groups[0]["data"]["Signal"], a)
            _equal(groups[0]["data"]["Abs"], np.abs(a))
            _equal(groups[1]["data"]["Signal"], b)
        return _Case("load_wwt_document" if kind == "wwt-document" else "load_wwt", path, check)

    if kind == "zfd":
        from tests.zfd_fixtures import write_minimal_zfd
        path = write_minimal_zfd(root / "input.zfd", count=8, dt=.25, t0=2., values=range(8), name="Signal", unit="N")
        def check(value):
            group, = value
            assert group["channels"] == ["Time", "Signal"] and group["units"] == {"Signal": "N"}
            _equal(group["data"]["Time"], 2. + np.arange(8) * .25)
            _equal(group["data"]["Signal"], np.arange(8))
            assert group["channel_metadata"]["Signal"]["record_index"] == 1
        return _Case("load_zfd", path, check)

    if kind.startswith("mat-"):
        path = root / "groups.mat"
        arrays = {"time": 1. + np.arange(5) * .25, "SignalA": np.arange(5.) + 11.,
                  "time_s": 3. + np.arange(3) * .5, "SignalB": np.arange(3.) + 21.}
        if kind == "mat-v5":
            from scipy.io import savemat
            savemat(path, arrays)
        else:
            h5py = pytest.importorskip("h5py")
            with h5py.File(path, "w", userblock_size=512) as hf:
                for name, values in arrays.items():
                    hf.create_dataset(name, data=values.reshape(1, -1))
            with path.open("r+b") as stream:
                stream.write(b"MATLAB 7.3 MAT-file".ljust(124, b" ") + b"\x00\x02IM")
        def check(value):
            assert len(value) == 2 and len({g["label_suffix"] for g in value}) == 2
            by_signal = {next(c for c in g["channels"] if c != "Time"): g for g in value}
            for signal, time in (("SignalA", "time"), ("SignalB", "time_s")):
                group = by_signal[signal]
                _equal(group["data"]["Time"], arrays[time])
                _equal(group["data"][signal], arrays[signal])
                assert group["units"] == {signal: ""}
                assert group["channel_metadata"][signal]["mat_variable"] == signal
                assert group["source_metadata"]["mat_version"] == ("v5" if kind == "mat-v5" else "v7.3")
        return _Case("load_mat", path, check)

    if kind == "head":
        from tests._helpers.head_hdf_factory import write_head_hdf
        path = write_head_hdf(root / "groups.hdf", n_scans=4, delta=.01, first_value=1.25, channels=[
            {"name": "Signal", "factor": 2, "samples": np.arange(8.), "quantity": "raw", "unit": "N", "calibration": 1.},
            {"name": "Signal", "factor": 1, "samples": np.arange(4.) + 10., "quantity": "raw", "unit": "V", "calibration": 1.},
        ])
        def check(value):
            assert [g["label_suffix"] for g in value] == ["2x", "1x"]
            for group, n, dt, unit, offset in zip(value, (8, 4), (.015, .03), ("N", "V"), (0., 10.)):
                assert group["units"] == {"Signal": unit}
                _equal(group["data"]["Time"], 1.25 + np.arange(n) * dt)
                _equal(group["data"]["Signal"], np.arange(n) + offset)
                assert group["source_metadata"]["factor"] == n // 4
                assert group["channel_metadata"]["Signal"]["raster_factor"] == n // 4
        return _Case("load_hdf", path, check)

    if kind == "wav":
        pytest.importorskip("av")
        path = root / "stereo.wav"
        pcm = (np.arange(256, dtype=np.int16).reshape(128, 2) - 128) * 100
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(pcm.astype("<i2").tobytes())
        def check(value):
            frame, channels, units, fs, metadata = value
            assert channels == ["L", "R"] and units == {"L": "Pa", "R": "Pa"}
            assert fs == 8000. and metadata["channels"] == 2
            np.testing.assert_array_equal(frame.to_numpy(), pcm.astype(np.float32) / np.float32(32768.))
            assert all(dtype == np.dtype("f4") for dtype in frame.dtypes)
        return _Case("load_audio_video", path, check)

    assert kind in {"blf", "asc"}
    pytest.importorskip("can")
    pytest.importorskip("cantools")
    from tests._helpers.blf_factory import write_sample_asc, write_sample_blf, write_two_message_dbc
    writer = write_sample_blf if kind == "blf" else write_sample_asc
    # Binary-exact primary raster avoids the fixture writer truncating a
    # decimal 0.2-second delta to 199,999,999 ns in BLF integer timestamps.
    path = writer(root / f"input.{kind}", n=3, dt=.125)
    dbc = write_two_message_dbc(root / "signals.dbc")
    return _Case("load_blf", path, _check_can, {"dbc_paths": [str(dbc)]})


@pytest.mark.parametrize("kind", _KINDS)
def test_real_child_format_success_bad_budget_and_retry(tmp_path, monkeypatch, kind):
    case = _case(tmp_path, kind)
    digest = hashlib.sha256(case.path.read_bytes()).digest()
    spawned = []
    command = import_process._worker_command
    def record_spawn(request):
        spawned.append(request)
        return command(request)
    monkeypatch.setattr(import_process, "_worker_command", record_spawn)
    def parent_parser_forbidden(*args, **kwargs):
        pytest.fail("a parser ran in the parent instead of the real import child")
    monkeypatch.setattr(DataLoader, case.method, parent_parser_forbidden)

    case.check(run_import(case.method, case.path, kwargs=case.kwargs, limits=_LIMITS))
    assert len(spawned) == 1
    bad = tmp_path / ("corrupt" + case.path.suffix)
    bad.write_bytes(b"not a measurement container\n")
    with pytest.raises(ImportProcessError) as failure:
        run_import(case.method, bad, kwargs=case.kwargs, limits=_LIMITS)
    # Still exercise resource failure and a following normal file even if the
    # corrupt reader exposes a classification bug; report that at the end.
    with pytest.raises(ImportProcessError) as budget:
        run_import(case.method, case.path, kwargs=case.kwargs,
                   limits=replace(_LIMITS, max_output_bytes=1024))
    assert budget.value.code == "resource_limit"
    assert len(spawned) == 3, "budget failure must occur in a real child, not argument serialization"
    case.check(run_import(case.method, case.path, kwargs=case.kwargs, limits=_LIMITS))
    assert len(spawned) == 4
    assert all(not request.parent.exists() for request in spawned)
    assert hashlib.sha256(case.path.read_bytes()).digest() == digest
    assert failure.value.code == "data_error", failure.value.detail


@pytest.mark.parametrize("kind", ["blf", "asc"])
def test_real_can_frame_request_transport_keeps_lazy_decode(tmp_path, monkeypatch, kind):
    from mf4_analyzer.io.can_frames import CanFrameBatch
    case = _case(tmp_path, kind)
    def forbidden(*args, **kwargs):
        pytest.fail("CAN read/probe/decode must run only in actual parser children")
    for method in ("read_blf_frames", "load_blf_frames", "probe_blf_dbc_frames"):
        monkeypatch.setattr(DataLoader, method, forbidden)
    frames = run_import("read_blf_frames", case.path, limits=_LIMITS)
    assert isinstance(frames, CanFrameBatch) and frames.warnings == ()
    assert len(frames) == 6 and frames[0][1] == 0x123
    _equal([f[0] - frames[0][0] for f in frames], [0., .05, .125, .175, .25, .3])
    # Send the actual first child's result through argument transport to the
    # next child; no dense pandas conversion or parent decoding is permitted.
    _check_can(run_import("load_blf_frames", case.path,
                         kwargs={**case.kwargs, "frames": frames}, limits=_LIMITS))
    probe = run_import("probe_blf_dbc_frames", case.path,
                       kwargs={**case.kwargs, "frames": frames}, limits=_LIMITS)
    assert probe.total_frame_count == 6 and probe.total_frame_id_count == 2
    assert probe.matched_frame_count == 6 and probe.matched_frame_id_count == 2
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle", "Speed"}


def test_real_asc_fallback_warnings_survive_child_transport(tmp_path, monkeypatch):
    from tests.test_asc_can_loader import _write_early_unsupported_asc
    from mf4_analyzer.io.can_frames import CanFrameBatch
    path = _write_early_unsupported_asc(tmp_path / "fallback.asc")
    def forbidden(*args, **kwargs):
        pytest.fail("ASC fallback ran in the parent")
    monkeypatch.setattr(DataLoader, "read_blf_frames", forbidden)
    frames = run_import("read_blf_frames", path, limits=_LIMITS)
    assert isinstance(frames, CanFrameBatch) and len(frames) == 1
    assert frames.warnings and all(isinstance(w, str) and w for w in frames.warnings)
    assert frames[0][1:] == (0x123, bytes(range(1, 9)))
