"""M4 analysis-input contract. Same-axis passthrough, anti-aliased downsample, and integer-ratio alignment."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from mf4_analyzer.analysis_signal_prepare import prepare_signal
from mf4_analyzer.analysis_time_axis import prepare_analysis_time_axis
from mf4_analyzer.signal.fft import one_sided_amplitude
from mf4_analyzer.signal.frf import FrfParams, compute_frf


def _digest(values) -> str:
    array = np.asarray(values)
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def test_frozen_designs_name_order_cutoff_and_the_supported_ratio():
    from mf4_analyzer.analysis_signal_prepare import (
        frozen_antialias_design, frozen_frf_alignment,
    )

    design = frozen_antialias_design()
    assert design["order"] == 8
    assert design["cutoff_ratio"] == 0.9
    assert design["padding"] == "odd_reflect"
    assert design["delay_compensation"] == 0
    assert design["stopband_db"] >= 60.0
    alignment = frozen_frf_alignment()
    assert alignment["origin"] == "shared_start"
    assert alignment["ratio"] == "integer_lower_fs"
    assert alignment["fractional_delay"] == "unsupported"
    assert alignment["min_input_fs_band"] == (0.05, 0.30)


def test_same_axis_passthrough_converts_float_and_keeps_original_bytes():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    raw = np.array([1, 3, 5, 7], dtype=np.int64)
    time = np.array([0.0, 0.01, 0.02, 0.03])
    raw_hash = _digest(raw)
    time_hash = _digest(time)
    prepared = prepare_signal(
        raw, time, fs=100.0, source_id="src", physical_id="phys",
        source_revision="rev-1", segment="0", policy="native",
    )
    assert prepared.status == "ready"
    assert prepared.method == "same_axis_passthrough"
    assert prepared.values.dtype == np.float64
    np.testing.assert_array_equal(prepared.values, [1.0, 3.0, 5.0, 7.0])
    np.testing.assert_array_equal(prepared.time, time)
    assert prepared.time is not time
    assert _digest(raw) == raw_hash
    assert _digest(time) == time_hash
    assert prepared.original_values_hash == raw_hash
    assert prepared.original_time_hash == time_hash
    assert prepared.input_count == 4
    assert prepared.output_count == 4
    assert prepared.source_fs == 100.0
    assert prepared.target_fs == 100.0
    assert prepared.policy_version
    assert prepared.bytes_charged == prepared.values.nbytes + prepared.time.nbytes
    freq, amp = one_sided_amplitude(
        np.asarray(prepared.values), prepared.source_fs, win="hanning", remove_mean=True,
    )
    core_freq, core_amp = one_sided_amplitude(
        raw.astype(np.float64), 100.0, win="hanning", remove_mean=True,
    )
    np.testing.assert_array_equal(freq, core_freq)
    np.testing.assert_array_equal(amp, core_amp)


def test_native_uniform_fft_matches_core_on_original_samples():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    fs = 1024.0
    count = 1024
    time = np.arange(count) / fs
    samples = np.sin(2.0 * np.pi * 32.0 * time)
    prepared = prepare_signal(samples, time, fs=fs, policy="native")
    assert prepared.status == "ready"
    assert prepared.method == "same_axis_passthrough"
    native_freq, native_amp = one_sided_amplitude(
        prepared.values, fs, win="hanning", remove_mean=True,
    )
    core_freq, core_amp = one_sided_amplitude(
        samples, fs, win="hanning", remove_mean=True,
    )
    np.testing.assert_array_equal(native_freq, core_freq)
    np.testing.assert_array_equal(native_amp, core_amp)


def test_native_nonuniform_does_not_rebuild_time_by_index():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    time = np.array([0.0, 0.01, 0.02, 0.05, 0.06])
    values = np.arange(time.size, dtype=float)
    prepared = prepare_signal(values, time, fs=100.0, policy="native")
    rebuilt, _fs, _facts = prepare_analysis_time_axis(time, 100.0)
    assert prepared.status == "rejected"
    assert prepared.method != "legacy_index_rebuild"
    assert prepared.values is None
    assert prepared.time is None
    assert "序号" in prepared.reason or "native" in prepared.reason
    assert not np.allclose(time, rebuilt)


def test_legacy_nonuniform_keeps_index_rebuild_and_original_samples():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    time = np.array([0.0, 0.01, 0.02, 0.05, 0.06])
    values = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    before = values.copy()
    prepared = prepare_signal(values, time, fs=100.0, policy="legacy")
    rebuilt, rebuilt_fs, _facts = prepare_analysis_time_axis(time, 100.0)
    assert prepared.status == "ready"
    assert prepared.method == "legacy_index_rebuild"
    np.testing.assert_array_equal(prepared.values, before)
    np.testing.assert_allclose(prepared.time, rebuilt)
    assert prepared.target_fs == pytest.approx(rebuilt_fs)
    assert prepared.requested_range == (float(time[0]), float(time[-1]))
    assert prepared.effective_range[0] == pytest.approx(float(rebuilt[0]))
    np.testing.assert_array_equal(values, before)


def test_explicit_uniform_computes_new_values_and_times():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    time = np.array([0.0, 1.0, 3.0])
    values = np.array([0.0, 10.0, 20.0])
    prepared = prepare_signal(
        values, time, fs=None, policy="native", intent="explicit_uniform",
        value_kind="continuous", target_fs=1.0, origin=0.0,
    )
    assert prepared.status == "ready"
    assert prepared.method == "explicit_linear_uniform"
    np.testing.assert_allclose(prepared.time, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(prepared.values, [0.0, 10.0, 15.0, 20.0])
    assert prepared.output_count != prepared.input_count
    assert prepared.provenance["value_source"] == "linear_interpolation"
    assert prepared.provenance["time_source"] == "origin_plus_k_over_fs"
    assert prepared.provenance["bandwidth_claim"] is False
    assert _digest(values) == prepared.original_values_hash


def test_explicit_uniform_downsample_rejects_the_stopband():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    source_fs = 4000.0
    target_fs = 500.0
    count = 4000
    time = np.arange(count) / source_fs
    stop = np.sin(2.0 * np.pi * 1500.0 * time)
    keep = np.sin(2.0 * np.pi * 40.0 * time)
    blocked = prepare_signal(
        stop, time, fs=source_fs, policy="native", intent="explicit_uniform",
        value_kind="continuous", target_fs=target_fs, origin=0.0,
    )
    passed = prepare_signal(
        keep, time, fs=source_fs, policy="native", intent="explicit_uniform",
        value_kind="continuous", target_fs=target_fs, origin=0.0,
    )
    assert blocked.status == "ready"
    assert blocked.method == "antialiased_downsample"
    assert blocked.provenance["delay_compensation"] == 0
    stop_rms = float(np.sqrt(np.mean(np.square(blocked.values))))
    source_rms = float(np.sqrt(np.mean(np.square(stop))))
    assert 20.0 * np.log10(stop_rms / source_rms) <= -60.0
    keep_rms = float(np.sqrt(np.mean(np.square(passed.values))))
    assert abs(20.0 * np.log10(keep_rms / source_rms)) <= 1.0
    assert np.array_equal(stop, np.sin(2.0 * np.pi * 1500.0 * time))


def test_known_gap_is_not_bridged():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    time = np.array([0.0, 0.1, 0.2, 1.0, 1.1])
    values = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    prepared = prepare_signal(
        values, time, policy="native", intent="explicit_uniform",
        value_kind="continuous", target_fs=10.0, origin=0.0,
        gaps=((0.2, 1.0),),
    )
    assert prepared.status == "rejected"
    assert prepared.values is None
    assert "缺口" in prepared.reason


def test_nonfinite_samples_are_rejected_and_do_not_mutate_inputs():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    values = np.array([1.0, np.nan, 3.0, 4.0])
    time = np.arange(4, dtype=float) / 10.0
    before = values.copy()
    prepared = prepare_signal(values, time, fs=10.0, policy="native")
    assert prepared.status == "rejected"
    assert prepared.quality == "nonfinite"
    assert prepared.values is None
    assert np.isnan(values[1]) and np.isnan(before[1])
    np.testing.assert_array_equal(values[[0, 2, 3]], before[[0, 2, 3]])


def test_invalid_mask_blocks_passthrough_until_a_finite_segment_is_requested():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    values = np.array([1.0, 2.0, 9.0, 4.0, 5.0])
    time = np.arange(5, dtype=float)
    invalid = np.array([False, False, True, False, False])
    blocked = prepare_signal(
        values, time, fs=1.0, policy="native", invalid=invalid,
    )
    assert blocked.status == "rejected"
    assert blocked.values is None
    chosen = prepare_signal(
        values, time, fs=1.0, policy="native", invalid=invalid,
        quality_policy="longest_finite_segment",
    )
    assert chosen.status == "ready"
    np.testing.assert_array_equal(chosen.values, [1.0, 2.0])
    np.testing.assert_array_equal(chosen.time, [0.0, 1.0])
    assert chosen.requested_range == (0.0, 4.0)
    assert chosen.effective_range == (0.0, 1.0)


def test_pair_rejects_equal_length_with_different_timestamps():
    from mf4_analyzer.analysis_signal_prepare import prepare_pair

    count = 16
    left_time = np.arange(count) / 100.0
    right_time = left_time + 0.05
    left = np.sin(left_time)
    right = np.cos(right_time)
    prepared = prepare_pair(
        left, left_time, right, right_time,
        left_fs=100.0, right_fs=100.0, policy="native",
    )
    assert prepared.status != "ready"
    assert prepared.relationship == "time_relationship_required"
    assert prepared.left is None or prepared.left.values is None
    assert prepared.right is None or prepared.right.values is None
    assert prepared.alignment_facts["resampled"] is False
    assert "length" in prepared.alignment_facts["rejected_proof"]


def test_pair_same_clock_passthrough_matches_core_frf():
    from mf4_analyzer.analysis_signal_prepare import prepare_pair

    fs = 1000.0
    count = 800
    time = np.arange(count) / fs
    stimulus = np.sin(2.0 * np.pi * 50.0 * time)
    response = 2.0 * np.roll(stimulus, 4)
    prepared = prepare_pair(
        stimulus, time, response, time, left_fs=fs, right_fs=fs, policy="native",
    )
    assert prepared.status == "ready"
    assert prepared.relationship == "same_axis"
    assert prepared.method == "same_axis_passthrough"
    params = FrfParams(
        estimator="h1", t_win_s=0.2, overlap=0.0, nfft_mode="auto",
        window="hanning", periodic_window=True, detrend="none",
    )
    via_prepare = compute_frf(
        prepared.left.values, prepared.right.values, fs=fs, params=params,
        input_time=prepared.left.time, output_time=prepared.right.time,
    )
    direct = compute_frf(
        stimulus, response, fs=fs, params=params,
        input_time=time, output_time=time,
    )
    np.testing.assert_array_equal(via_prepare.transfer, direct.transfer)
    np.testing.assert_array_equal(via_prepare.coherence, direct.coherence)


def test_integer_ratio_alignment_is_ready_and_other_ratios_stay_unsupported():
    from mf4_analyzer.analysis_signal_prepare import prepare_pair

    left_time = np.arange(800) / 1000.0
    right_time = np.arange(200) / 250.0
    tone = np.sin(2.0 * np.pi * 20.0 * left_time)
    slow = np.sin(2.0 * np.pi * 20.0 * right_time)
    prepared = prepare_pair(
        tone, left_time, slow, right_time,
        left_fs=1000.0, right_fs=250.0, policy="native",
        align_then_compute=True,
    )
    assert prepared.status == "ready"
    assert prepared.method == "antialiased_lower_fs"
    assert prepared.alignment_facts["resampled"] is True
    assert prepared.alignment_facts["ratio"] == 4
    assert len(prepared.left.values) == len(prepared.right.values)
    assert prepared.left.target_fs == pytest.approx(250.0)

    odd_right = np.arange(48) / 300.0
    rejected = prepare_pair(
        np.sin(left_time), left_time, np.cos(odd_right), odd_right,
        left_fs=1000.0, right_fs=300.0, policy="native",
        align_then_compute=True,
    )
    assert rejected.status == "unsupported"
    assert rejected.alignment_facts["resampled"] is False
    assert "整数" in rejected.reason
    assert rejected.left is None


def test_fs_reinterpret_does_not_resample_or_overwrite_the_original_axis():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    values = np.array([1.0, 2.0, 4.0, 8.0])
    time = np.array([10.0, 10.1, 10.4, 10.9])
    native = prepare_signal(
        values, time, fs=5.0, policy="native", intent="reinterpret_fs",
    )
    assert native.status != "ready"
    assert native.values is None
    legacy = prepare_signal(
        values, time, fs=5.0, policy="legacy", intent="reinterpret_fs",
    )
    assert legacy.status == "ready"
    assert legacy.method == "fs_reinterpret"
    np.testing.assert_array_equal(legacy.values, values)
    np.testing.assert_allclose(legacy.time, 10.0 + np.arange(4) / 5.0)
    assert legacy.time is not time
    np.testing.assert_array_equal(time, [10.0, 10.1, 10.4, 10.9])
    assert legacy.provenance["resamples_values"] is False
    assert legacy.requested_range != legacy.effective_range or legacy.time[1] != time[1]


def test_state_zoh_holds_and_does_not_infer_state_from_integers():
    from mf4_analyzer.analysis_signal_prepare import prepare_signal

    time = np.array([0.0, 1.0, 2.0])
    values = np.array([4, 8, 1], dtype=int)
    implied = prepare_signal(
        values, time, policy="native", intent="explicit_uniform",
        target_fs=2.0, origin=0.0,
    )
    assert implied.status == "rejected"
    assert "状态" in implied.reason or "连续" in implied.reason
    held = prepare_signal(
        values, time, policy="native", intent="explicit_uniform",
        value_kind="state", target_fs=2.0, origin=0.0,
    )
    assert held.status == "ready"
    assert held.method == "explicit_zoh"
    np.testing.assert_allclose(held.time, [0.0, 0.5, 1.0, 1.5, 2.0])
    np.testing.assert_array_equal(held.values, [4.0, 4.0, 8.0, 8.0, 1.0])


def test_linear_alignment_does_not_extend_outside_coverage():
    from mf4_analyzer.analysis_signal_prepare import prepare_order_speed

    signal_time = np.array([0.0, 0.5, 1.0, 1.5])
    rpm_time = np.array([0.0, 1.0])
    rpm = np.array([600.0, 1800.0])
    prepared = prepare_order_speed(
        signal_time, rpm, rpm_time, rpm_factor=1.0, rpm_unit="rpm",
        rpm_source=("motor", "n_motor"), require_full_coverage=True,
    )
    assert prepared.status == "rejected"
    assert prepared.quality == "coverage"
    assert prepared.values is None
    clamped = np.interp(signal_time, rpm_time, rpm)
    assert prepared.values is None or not np.array_equal(prepared.values, clamped)


def test_equal_count_different_timestamps_align_inside_coverage_without_changing_identity():
    from mf4_analyzer.analysis_signal_prepare import prepare_order_speed

    signal_time = np.linspace(0.01, 0.99, 8)
    rpm_time = np.linspace(0.0, 1.0, 8)
    rpm = 1000.0 + 100.0 * rpm_time
    identity = ("recording-a", "n_motor")
    prepared = prepare_order_speed(
        signal_time, rpm, rpm_time, rpm_factor=2.0, rpm_unit="rpm",
        rpm_source=identity,
    )
    assert prepared.status == "ready"
    expected = 2.0 * (1000.0 + 100.0 * signal_time)
    np.testing.assert_allclose(prepared.values, expected)
    assert not np.allclose(prepared.values, rpm * 2.0)
    assert prepared.provenance["rpm_source"] == ("recording-a", "n_motor")
    other = prepare_order_speed(
        signal_time, rpm, rpm_time, rpm_factor=2.0, rpm_unit="rpm",
        rpm_source=("recording-a", "n_other"),
    )
    assert other.provenance["rpm_source"] == ("recording-a", "n_other")
    assert other.provenance["rpm_source"] != prepared.provenance["rpm_source"]


def test_order_speed_checks_unit_and_factor_before_alignment():
    from mf4_analyzer.analysis_signal_prepare import prepare_order_speed

    signal_time = np.linspace(0.0, 1.0, 5)
    rpm = np.linspace(600.0, 1800.0, 5)
    rejected = prepare_order_speed(
        signal_time, rpm, signal_time, rpm_factor=1.0, rpm_unit="rad/s",
        rpm_source=("motor", "n_motor"),
    )
    assert rejected.status == "rejected"
    assert rejected.quality == "unit"
    assert rejected.values is None
    bad_factor = prepare_order_speed(
        signal_time, rpm, signal_time, rpm_factor=float("nan"), rpm_unit="rpm",
        rpm_source=("motor", "n_motor"),
    )
    assert bad_factor.status == "rejected"
    assert bad_factor.values is None


def test_manual_rpm_stays_an_explicit_constant():
    from mf4_analyzer.analysis_signal_prepare import prepare_order_speed

    prepared = prepare_order_speed(
        np.linspace(0.0, 1.0, 6), None, None, manual_rpm=900.0,
        rpm_source=None,
    )
    assert prepared.status == "ready"
    assert prepared.method == "manual_constant"
    np.testing.assert_array_equal(prepared.values, np.full(6, 900.0))
    assert prepared.provenance["rpm_source"] is None


def test_cache_key_includes_method_and_prepare_bytes_are_preflighted():
    from mf4_analyzer.analysis_signal_prepare import (
        PrepareByteLedger,
        preflight_prepare,
        prepare_cache_key,
        prepare_signal,
    )

    time = np.arange(8) / 8.0
    values = np.arange(8, dtype=float)
    ready = prepare_signal(values, time, fs=8.0, policy="native")
    other = prepare_signal(
        values, time, fs=8.0, policy="legacy", intent="reinterpret_fs",
    )
    params = {"window": "hanning", "nfft": 8}
    assert prepare_cache_key(ready, params) != prepare_cache_key(other, params)
    assert prepare_cache_key(ready, params) == prepare_cache_key(ready, dict(params))
    changed = dict(params, nfft=16)
    assert prepare_cache_key(ready, params) != prepare_cache_key(ready, changed)
    decision = preflight_prepare(sample_count=10_000, byte_limit=100)
    assert decision["admitted"] is False
    assert decision["estimated_bytes"] > 100
    blocked = prepare_signal(
        values, time, fs=8.0, policy="native", byte_limit=8,
    )
    assert blocked.status == "rejected"
    assert blocked.quality == "byte_limit"
    assert blocked.values is None
    ledger = PrepareByteLedger(limit=ready.bytes_charged)
    assert ledger.charge(ready.bytes_charged) is True
    assert ledger.charge(1) is False
    assert ledger.used == ready.bytes_charged


def test_native_loader_does_not_index_rebuild_a_uniform_channel(tmp_path):
    from mf4_analyzer.analysis_signal_prepare import load_native_channel
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.io.native_signal_store import (
        AxisSpec,
        ChannelSpec,
        NativeSignalStore,
    )

    fs = 100.0
    time = np.arange(16) / fs
    samples = np.sin(time)
    store = NativeSignalStore.build(
        "native-src",
        [AxisSpec("t0", "clock", "time", "s", time, fs_status="known", fs_hz=fs)],
        [ChannelSpec(0, 0, "torque", "t0", samples, unit="Nm")],
    )
    fd = FileData.from_native_store(str(tmp_path / "native.mf4"), store)
    prepared = load_native_channel(fd, "torque")
    assert prepared.status == "ready"
    assert prepared.method == "same_axis_passthrough"
    np.testing.assert_array_equal(prepared.values, samples)
    uneven = time.copy()
    uneven[8] += 0.02
    uneven_store = NativeSignalStore.build(
        "native-gap",
        [AxisSpec("t0", "clock", "time", "s", uneven, fs_status="known", fs_hz=fs)],
        [ChannelSpec(0, 0, "torque", "t0", samples, unit="Nm")],
    )
    uneven_fd = FileData.from_native_store(str(tmp_path / "uneven.mf4"), uneven_store)
    rejected = load_native_channel(uneven_fd, "torque")
    assert rejected.status == "rejected"
    assert rejected.values is None
    rebuilt, _fs, _facts = prepare_analysis_time_axis(uneven, fs)
    assert rejected.time is None or not np.allclose(rejected.time, rebuilt)


@pytest.mark.parametrize('dtype,value,exact', [
    ('i8', 2**53-1, True), ('i8', 2**53, True), ('i8', 2**53+1, False),
    ('i8', 2**53+2, True), ('i8', 2**53+3, False), ('i8', 2**53+5, False),
    ('i8', -(2**53+1), False), ('i8', -(2**53+2), True),
    ('i8', -(2**63), True), ('i8', 2**63-1, False),
    ('u8', 2**64-1, False), ('u8', 2**64-2048, True),
])
def test_native_integer_float64_representation(dtype, value, exact):
    raw = np.array([value, value], dtype=dtype)
    before = raw.tobytes()
    prepared = prepare_signal(raw, np.array([0., 1.]), fs=1.)
    assert (prepared.status == 'ready') is exact
    if exact:
        assert all(int(v) == value for v in prepared.values)
        assert prepared.provenance['compute_dtype'] == 'float64'
    else:
        assert prepared.quality == 'integer_precision'
        assert 'float64' in prepared.reason
        assert prepared.values is None
    assert raw.tobytes() == before


def test_native_precision_checks_only_requested_samples_and_keeps_legacy_policy():
    raw = np.array([2**53+3, 2, 3], dtype=np.int64)
    selected = prepare_signal(raw, np.arange(3.), fs=1., requested_range=(1., 2.))
    assert selected.status == 'ready'
    np.testing.assert_array_equal(selected.values, [2., 3.])
    assert prepare_signal(raw, np.arange(3.), fs=1., policy='legacy').status == 'ready'


@pytest.mark.parametrize('wide_side', ['left', 'right'])
def test_cross_rate_alignment_preserves_integer_precision_admission(wide_side, monkeypatch):
    from mf4_analyzer.analysis_signal_prepare import prepare_pair
    left = np.ones(1024, dtype=np.int64)
    right = np.ones(512, dtype=np.int64)
    (left if wide_side == 'left' else right)[100] = 2**53 + 3
    calls = []
    def observed_filter(values, spec, fs):
        calls.append(True)
        return values
    monkeypatch.setattr('mf4_analyzer.analysis_signal_prepare.apply_filter', observed_filter)
    pair = prepare_pair(left, np.arange(1024.) / 128,
                        right, np.arange(512.) / 64,
                        left_fs=128, right_fs=64, align_then_compute=True)
    assert pair.status == 'rejected'
    assert 'float64' in pair.reason
    assert pair.left is None and pair.right is None
    assert not calls
