"""A6: spectrogram time-axis rebuild returns auditable warnings."""
from __future__ import annotations

import numpy as np
import pytest

from types import SimpleNamespace

import pandas as pd

from mf4_analyzer.batch import BatchRunner
from mf4_analyzer.batch_compute import (
    compute_fft_time_spectro,
    compute_prepared_frf,
    prepare_frf_task,
    suggest_fs_from_time_axis,
    uniform_time_axis_for_spectrogram,
)
from mf4_analyzer.batch_manifest import load_batch_manifest
from mf4_analyzer.io import FileData


def test_uniform_time_axis_for_spectrogram_returns_rebuild_warning():
    fs = 500.0
    n = 128
    nominal_dt = 1.0 / fs
    dts = np.resize(np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), n - 1)
    time = np.concatenate(([0.0], np.cumsum(dts)))
    rebuilt_fs = float(suggest_fs_from_time_axis(time, fs))

    new_time, new_fs, warnings = uniform_time_axis_for_spectrogram(time, fs, n)

    assert new_fs == pytest.approx(rebuilt_fs)
    assert new_fs != pytest.approx(fs)
    np.testing.assert_allclose(new_time, np.arange(n, dtype=float) / rebuilt_fs)
    assert len(warnings) == 1
    assert "自动重建" in warnings[0]
    assert "relative_jitter=" in warnings[0]
    assert f"Fs={rebuilt_fs:g}" in warnings[0]


def test_uniform_time_axis_for_spectrogram_uniform_input_has_empty_warnings():
    fs = 1000.0
    time = np.arange(64, dtype=float) / fs
    new_time, new_fs, warnings = uniform_time_axis_for_spectrogram(time, fs, 64)
    np.testing.assert_allclose(new_time, time)
    assert new_fs == pytest.approx(fs)
    assert warnings == ()


def _jittered_time(n, fs):
    nominal_dt = 1.0 / fs
    dts = np.resize(np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), n - 1)
    return np.concatenate(([0.0], np.cumsum(dts)))


def test_uniform_time_axis_for_spectrogram_records_time_axis_facts():
    fs = 500.0
    n = 128
    time = _jittered_time(n, fs)
    rebuilt_fs = float(suggest_fs_from_time_axis(time, fs))
    result = uniform_time_axis_for_spectrogram(time, fs, n)
    facts = result.time_axis
    assert facts["reason"] == "auto_nonuniform"
    assert facts["method"] == "median_dt"
    assert facts["original_fs"] == pytest.approx(fs)
    assert facts["estimated_fs"] == pytest.approx(rebuilt_fs)
    assert facts["relative_jitter"] > 0
    assert facts["n_samples"] == n


def test_fft_time_spectro_metadata_includes_time_axis():
    fs = 500.0
    n = 256
    time = _jittered_time(n, fs)
    sig = np.sin(2 * np.pi * 40.0 * (np.arange(n, dtype=float) / fs))
    spectro = compute_fft_time_spectro(
        sig, time, fs, {"nfft": 64, "window": "hanning", "overlap": 0.5},
        channel_name="sig",
    )
    facts = spectro.metadata["time_axis"]
    assert facts["reason"] == "auto_nonuniform"
    assert facts["estimated_fs"] == pytest.approx(float(spectro.metadata["effective_fs"]))


def _frf_file(*, time_source="column", jitter=False, fs=100.0, samples=400):
    time = np.arange(samples, dtype=float) / fs
    if jitter:
        time = time.copy()
        time[100:] += 0.02
    command = np.sin(2.0 * np.pi * 5.0 * (np.arange(samples, dtype=float) / fs))
    response = 2.0 * command
    return SimpleNamespace(
        data=pd.DataFrame({"command": command, "response": response}),
        time_array=time,
        fs=fs,
        _time_source=time_source,
        channel_units={"command": "V", "response": "N"},
        channel_metadata={},
    )


def _frf_params():
    return {
        "estimator": "h1",
        "window": "hanning",
        "periodic_window": True,
        "t_win_s": 0.5,
        "overlap": 0.5,
        "nfft_mode": "auto",
        "detrend": "none",
    }


def test_prepare_frf_task_accepts_auto_rebuilt_and_rejects_generated():
    accepted = prepare_frf_task(
        _frf_file(time_source="auto_rebuilt"),
        "command",
        "response",
        _frf_params(),
    )
    assert accepted.warnings == ()
    assert accepted.time_axis is None

    with pytest.raises(ValueError, match="真实时间轴"):
        prepare_frf_task(
            _frf_file(time_source="generated"),
            "command",
            "response",
            _frf_params(),
        )


def test_prepare_frf_task_records_time_axis_facts_on_rebuild():
    prepared = prepare_frf_task(
        _frf_file(jitter=True), "command", "response", _frf_params(),
    )
    assert prepared.warnings
    assert "自动重建" in prepared.warnings[0]
    facts = prepared.time_axis
    assert facts["reason"] == "auto_nonuniform"
    assert facts["method"] == "median_dt"
    assert facts["original_time_source"] == "column"
    computed = compute_prepared_frf(prepared)
    merged = BatchRunner._frf_effective_facts(prepared, computed)
    assert merged["time_axis"]["reason"] == "auto_nonuniform"


def test_fft_time_manifest_records_effective_facts_time_axis(tmp_path):
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput
    import dataclasses

    fs = 500.0
    n = 2048
    time = _jittered_time(n, fs)
    sig = np.sin(2 * np.pi * 40.0 * (np.arange(n, dtype=float) / fs))
    frame = pd.DataFrame({"Time": time, "sig": sig})
    fd = FileData(tmp_path / "jittered.mf4", frame, list(frame.columns), {}, idx=0)
    rebuilt_fs = float(suggest_fs_from_time_axis(time, fs))
    preset = AnalysisPreset.free_config(
        name="batch fft_time jittered provenance",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": fd.fs, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].effective_params["time_axis"]["reason"] == "auto_nonuniform"
    assert result.items[0].effective_params["time_axis"]["estimated_fs"] == pytest.approx(
        rebuilt_fs
    )
    manifest = load_batch_manifest(result.manifest_path)
    entry = next(
        row for row in manifest["entries"] if row.get("task_id") == result.items[0].task_id
    )
    assert entry["effective_facts"]["time_axis"]["reason"] == "auto_nonuniform"
    assert entry["effective_facts"]["time_axis"]["method"] == "median_dt"
