from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.batch_preprocess import preprocess_batch_signal


def _tone_amplitude(values, fs, frequency):
    values = np.asarray(values, dtype=float)
    spectrum = np.fft.rfft(values)
    freqs = np.fft.rfftfreq(len(values), d=1.0 / float(fs))
    return float(np.abs(spectrum[np.argmin(np.abs(freqs - frequency))]))


def test_preprocess_locks_range_finite_scale_offset_then_remove_mean_order():
    time = np.arange(8, dtype=float) / 8.0
    signal = np.array([100.0, 1.0, np.nan, 3.0, 5.0, 7.0, 9.0, 200.0])
    rpm = np.array([900.0, 1000.0, 1100.0, 1200.0, 1300.0,
                    np.inf, 1500.0, 1600.0])

    result = preprocess_batch_signal(
        signal,
        time,
        8.0,
        {
            "time_range": [0.125, 0.75],
            "time_preprocess": {
                "scale": 2.0,
                "offset": 10.0,
                "remove_mean": True,
                "sample_mode": "original",
                "target_fs": None,
                "decimation_factor": 1,
            },
        },
        rpm=rpm,
    )

    # Range first selects indices 1..6. Finite cleanup then drops index 2
    # (signal NaN) and index 5 (RPM inf), preserving triplet alignment.
    np.testing.assert_allclose(result.time, [0.125, 0.375, 0.5, 0.75])
    np.testing.assert_allclose(result.rpm, [1000.0, 1200.0, 1300.0, 1500.0])
    # scale/offset -> [12, 16, 20, 28], then remove mean -> [-7, -3, 1, 9].
    np.testing.assert_allclose(result.signal, [-7.0, -3.0, 1.0, 9.0])
    np.testing.assert_allclose(result.pre_filter_signal, result.signal)
    assert result.effective["after_time_range_samples"] == 6
    assert result.effective["finite_samples_dropped"] == 2
    assert result.effective["output_samples"] == 4


def test_target_fs_downsampling_is_antialiased_and_reports_actual_fs():
    fs = 1000.0
    target_fs = 200.0
    time = np.arange(4000, dtype=float) / fs
    signal = (
        np.sin(2.0 * np.pi * 40.0 * time)
        + np.sin(2.0 * np.pi * 350.0 * time)
    )

    result = preprocess_batch_signal(
        signal,
        time,
        fs,
        {
            "time_preprocess": {
                "sample_mode": "target_fs",
                "target_fs": target_fs,
            }
        },
    )

    naive = np.interp(result.time, time, signal)
    preserved = _tone_amplitude(result.signal, result.effective_fs, 40.0)
    aliased = _tone_amplitude(result.signal, result.effective_fs, 50.0)
    naive_alias = _tone_amplitude(naive, result.effective_fs, 50.0)

    assert result.effective_fs == pytest.approx(target_fs)
    assert result.effective["sampling"]["anti_alias"]["enabled"] is True
    assert result.effective["sampling"]["anti_alias"]["method"] == "fft_butterworth"
    assert preserved > 10.0 * aliased
    assert aliased < 0.15 * naive_alias


def test_decimate_uses_antialias_path_and_keeps_rpm_on_returned_time_axis():
    fs = 600.0
    time = np.arange(1200, dtype=float) / fs
    signal = np.sin(2.0 * np.pi * 30.0 * time)
    rpm = np.full_like(time, 1800.0)

    result = preprocess_batch_signal(
        signal,
        time,
        fs,
        {
            "time_preprocess": {
                "sample_mode": "decimate",
                "decimation_factor": 3,
            }
        },
        rpm=rpm,
    )

    assert result.effective_fs == pytest.approx(200.0)
    assert result.effective["sampling"]["decimation_factor"] == 3
    assert result.effective["sampling"]["anti_alias"]["enabled"] is True
    assert len(result.signal) == len(result.time) == len(result.rpm)
    np.testing.assert_allclose(result.rpm, 1800.0, atol=1e-9)
    np.testing.assert_allclose(np.diff(result.time), 1.0 / 200.0, atol=1e-12)


def test_user_filter_clamps_after_sampling_and_records_requested_effective_facts():
    fs = 200.0
    time = np.arange(400, dtype=float) / fs
    signal = np.sin(2.0 * np.pi * 10.0 * time)
    requested_spec = {"kind": "low", "order": 4, "cutoff": 9999.0}

    result = preprocess_batch_signal(
        signal,
        time,
        fs,
        {
            "time_preprocess": {
                "sample_mode": "decimate",
                "decimation_factor": 2,
            },
            "filter": {
                "enabled": True,
                "spec": requested_spec,
                "show_original": True,
                "show_filtered": True,
            },
        },
    )

    assert result.effective_fs == pytest.approx(100.0)
    assert result.requested["filter"]["spec"] == requested_spec
    assert result.effective["filter"]["spec"]["cutoff"] == pytest.approx(
        50.0 * (1.0 - 1e-6)
    )
    assert any("钳制" in warning for warning in result.warnings)
    assert not np.array_equal(result.signal, result.pre_filter_signal)


def test_target_user_filter_does_not_scale_or_filter_rpm():
    fs = 200.0
    time = np.arange(400, dtype=float) / fs
    signal = 3.0 + np.sin(2.0 * np.pi * 10.0 * time)
    rpm = np.full_like(time, 1500.0)

    result = preprocess_batch_signal(
        signal,
        time,
        fs,
        {
            "time_preprocess": {
                "scale": 4.0,
                "offset": 20.0,
                "remove_mean": True,
                "sample_mode": "original",
            },
            "filter": {
                "enabled": True,
                "spec": {"kind": "high", "order": 4, "cutoff": 20.0},
            },
        },
        rpm=rpm,
    )

    np.testing.assert_allclose(result.rpm, rpm)
    assert abs(float(np.mean(result.pre_filter_signal))) < 1e-12
    assert not np.array_equal(result.signal, result.pre_filter_signal)


@pytest.mark.parametrize(
    ("time_preprocess", "match"),
    [
        ({"sample_mode": "target_fs", "target_fs": 200.0}, "upsampling"),
        ({"sample_mode": "target_fs", "target_fs": 0.0}, "target_fs"),
        ({"sample_mode": "decimate", "decimation_factor": 0}, "decimation_factor"),
        ({"sample_mode": "decimate", "decimation_factor": 1.5}, "decimation_factor"),
        ({"sample_mode": "mystery"}, "sample_mode"),
    ],
)
def test_invalid_sampling_request_fails_closed(time_preprocess, match):
    fs = 100.0
    time = np.arange(100, dtype=float) / fs

    with pytest.raises(ValueError, match=match):
        preprocess_batch_signal(
            np.ones_like(time),
            time,
            fs,
            {"time_preprocess": time_preprocess},
        )


def test_sampling_requires_strictly_increasing_finite_aligned_time():
    with pytest.raises(ValueError, match="strictly increasing"):
        preprocess_batch_signal(
            [1.0, 2.0, 3.0, 4.0],
            [0.0, 0.1, 0.1, 0.3],
            10.0,
            {
                "time_preprocess": {
                    "sample_mode": "decimate",
                    "decimation_factor": 2,
                }
            },
        )


def test_finite_cleanup_fails_when_fewer_than_two_aligned_samples_remain():
    with pytest.raises(ValueError, match="fewer than 2 finite aligned samples"):
        preprocess_batch_signal(
            [np.nan, 2.0, np.inf],
            [0.0, 0.1, 0.2],
            10.0,
            {},
            rpm=[1000.0, np.nan, 1200.0],
        )
