import numpy as np
import pytest

from mf4_analyzer.signal import (
    AutoNfftDecision,
    assess_speed_for_order,
    canonical_spectrogram_frame_count,
    canonical_spectrogram_frame_starts,
    ceil_pow2,
    energy_band_fmax,
    non_tail_frame_count,
    order_angle_sample_count,
    requested_auto_nfft,
    resolve_auto_nfft,
    resolve_nfft,
    resolve_order_nfft,
    revolutions_from_rpm,
)
from mf4_analyzer.signal.adaptive import (
    segmented_analysis_hop,
    spectrogram_analysis_hop,
)
from mf4_analyzer.signal.fft import FFTAnalyzer
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (191, 256),
        (1500, 2048),
        (2000, 2048),
        (8193, 16384),
    ],
)
def test_ceil_pow2_rounds_up_to_next_power_of_two(value, expected):
    assert ceil_pow2(value) == expected


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_ceil_pow2_rejects_non_positive_inputs(value):
    with pytest.raises(ValueError):
        ceil_pow2(value)


def test_resolve_nfft_uses_target_window_when_data_has_enough_frames():
    assert resolve_nfft(1000, 60000, 1.5, 0.75) == 2048


def test_resolve_nfft_reduces_until_short_record_has_enough_frames():
    assert resolve_nfft(1000, 5002, 1.5, 0.75) == 512


def test_resolve_nfft_low_sample_rate_case_uses_target_window_exactly():
    assert resolve_nfft(96, 5002, 1.5, 0.75) == 256


@pytest.mark.parametrize("overlap", [-0.1, 1.0, np.nan, np.inf])
def test_resolve_nfft_rejects_invalid_overlap(overlap):
    with pytest.raises(ValueError):
        resolve_nfft(1000, 60000, 1.5, overlap)


def test_resolve_nfft_can_resolve_to_floor_for_short_target_window():
    assert resolve_nfft(96, 5002, 0.6, 0.75) == 64


def test_resolve_order_nfft_maps_order_resolution_to_angle_domain_window():
    assert resolve_order_nfft(256, 0.05, 1_000_000) == 8192
    assert resolve_order_nfft(512, 0.10, 1_000_000) == 8192
    assert resolve_order_nfft(256, 0.25, 1_000_000) == 1024


def test_resolve_order_nfft_reduces_for_short_angle_record():
    assert resolve_order_nfft(256, 0.05, 4096) == 1024
    assert resolve_order_nfft(256, 0.05, 12000) == 4096


def test_resolve_order_nfft_uses_order_specific_floor_and_ceiling():
    assert resolve_order_nfft(64, 1.0, 1_000_000) == 256
    assert resolve_order_nfft(1024, 0.01, 10_000_000) == 16384


def test_revolutions_from_rpm_matches_trapezoid_for_constant_speed():
    t = np.arange(1000, dtype=float) / 100.0      # 9.99 s
    rpm = np.full_like(t, 1200.0)                 # 20 rev/s

    revs = revolutions_from_rpm(rpm, t)

    assert revs == pytest.approx(np.trapezoid(np.abs(rpm) / 60.0, t))
    assert revs == pytest.approx(20.0 * t[-1])


def test_revolutions_from_rpm_integrates_a_sweep():
    t = np.arange(2000, dtype=float) / 1000.0     # 2 s
    rpm = np.linspace(1000.0, 3000.0, t.size)     # EPS motor speed sweep

    revs = revolutions_from_rpm(rpm, t)

    assert revs == pytest.approx(np.trapezoid(rpm / 60.0, t))


def test_revolutions_from_rpm_uses_absolute_speed_for_reversals():
    t = np.arange(100, dtype=float) / 100.0
    rpm = np.full_like(t, 600.0)

    assert revolutions_from_rpm(-rpm, t) == pytest.approx(
        revolutions_from_rpm(rpm, t)
    )


def test_revolutions_from_rpm_drops_non_finite_pairs():
    t = np.array([0.0, 1.0, 2.0, 3.0])
    rpm = np.array([60.0, np.nan, 60.0, 60.0])

    # The NaN sample and its timestamp are removed as a pair, so the surviving
    # axis is [0, 2, 3] at 1 rev/s -> 3 revolutions.
    assert revolutions_from_rpm(rpm, t) == pytest.approx(3.0)

    t_bad = np.array([0.0, np.inf, 2.0, 3.0])
    assert revolutions_from_rpm(np.full(4, 60.0), t_bad) == pytest.approx(3.0)


def test_revolutions_from_rpm_skips_non_increasing_steps():
    t = np.array([0.0, 1.0, 1.0, 0.5, 2.0])
    rpm = np.full(5, 60.0)

    # Only dt > 0 contributes: 0->1 (1 s) and 0.5->2 (1.5 s).
    assert revolutions_from_rpm(rpm, t) == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("rpm", "t"),
    [
        ([], []),
        ([1000.0], [0.0]),
        ([np.nan, np.nan], [0.0, 1.0]),
        ([0.0, 0.0, 0.0], [0.0, 1.0, 2.0]),
        ([1000.0, 1000.0], [1.0, 1.0]),
        ([1000.0, 1000.0], [1.0, 0.0]),
    ],
)
def test_revolutions_from_rpm_returns_zero_for_degenerate_input(rpm, t):
    assert revolutions_from_rpm(rpm, t) == 0.0


def test_revolutions_from_rpm_tolerates_mismatched_lengths():
    t = np.arange(5, dtype=float)
    rpm = np.full(3, 60.0)

    # Pairwise truncation to the shorter array: 2 s at 1 rev/s.
    assert revolutions_from_rpm(rpm, t) == pytest.approx(2.0)


def test_order_angle_sample_count_scales_samples_per_rev_by_revolutions():
    t = np.arange(2000, dtype=float) / 1000.0
    rpm = np.linspace(1000.0, 3000.0, t.size)

    revs = revolutions_from_rpm(rpm, t)

    assert order_angle_sample_count(256, rpm, t) == int(round(256 * revs))
    assert order_angle_sample_count(512, rpm, t) == int(round(512 * revs))


@pytest.mark.parametrize(
    ("rpm", "t"),
    [([], []), ([0.0, 0.0], [0.0, 1.0]), ([np.nan, np.nan], [0.0, 1.0])],
)
def test_order_angle_sample_count_floors_at_one_for_degenerate_speed(rpm, t):
    """``1`` keeps ``resolve_order_nfft`` in its valid domain (no raise)."""
    assert order_angle_sample_count(256, rpm, t) == 1
    assert resolve_order_nfft(256, 0.1, order_angle_sample_count(256, rpm, t)) == 256


def test_energy_band_fmax_narrowband_uses_headroom_and_nice_ceil():
    freq = np.arange(0.0, 51.0, 1.0)
    amp = np.zeros_like(freq)
    amp[1] = 10.0

    assert energy_band_fmax(freq, amp) == 5.0


def test_energy_band_fmax_broadband_caps_near_nyquist():
    freq = np.arange(0.0, 51.0, 1.0)
    amp = np.ones_like(freq)

    assert energy_band_fmax(freq, amp) == 50.0


def test_energy_band_fmax_pure_dc_returns_floor_capped_by_nyquist():
    freq = np.arange(0.0, 51.0, 1.0)
    amp = np.zeros_like(freq)
    amp[0] = 100.0

    assert energy_band_fmax(freq, amp) == 2.0


def test_energy_band_fmax_uses_one_two_five_nice_rounding():
    freq = np.array([0.0, 3.0, 100.0])
    amp = np.array([0.0, 1.0, 0.0])

    assert energy_band_fmax(freq, amp) == 20.0


def test_energy_band_fmax_invalid_or_zero_energy_returns_floor():
    freq = np.array([0.0, 1.0, np.nan, np.inf])
    amp = np.array([0.0, 0.0, 10.0, 10.0])

    assert energy_band_fmax(freq, amp) == 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"p": 0.0},
        {"p": -0.1},
        {"p": 1.1},
        {"p": np.nan},
        {"headroom": 0.0},
        {"headroom": -1.0},
        {"headroom": np.nan},
        {"floor_hz": -0.1},
        {"floor_hz": np.nan},
    ],
)
def test_energy_band_fmax_rejects_invalid_parameters(kwargs):
    freq = np.array([0.0, 1.0, 2.0])
    amp = np.array([0.0, 1.0, 0.0])

    with pytest.raises(ValueError):
        energy_band_fmax(freq, amp, **kwargs)


def test_assess_speed_for_order_accepts_steady_unidirectional_rpm():
    ok, message = assess_speed_for_order([1000.0, 1005.0, np.nan, 995.0])

    assert ok is True
    assert message == ""


@pytest.mark.parametrize("rpm", [[], [1000.0], [np.nan, 1000.0], [np.nan]])
def test_assess_speed_for_order_rejects_fewer_than_two_finite_samples(rpm):
    ok, message = assess_speed_for_order(rpm)

    assert ok is False
    assert "\u8f6c\u901f" in message


def test_assess_speed_for_order_rejects_repeated_sign_reversals():
    ok, message = assess_speed_for_order([1000.0, -1000.0, 1000.0, -1000.0, 1000.0])

    assert ok is False
    assert "\u8f6c\u901f" in message


def test_assess_speed_for_order_rejects_too_much_near_zero_rpm():
    rpm = [1000.0] * 7 + [0.0] * 3

    ok, message = assess_speed_for_order(rpm)

    assert ok is False
    assert "\u8f6c\u901f" in message


def _assert_auto_nfft(decision, **expected):
    assert isinstance(decision, AutoNfftDecision)
    for name, value in expected.items():
        actual = getattr(decision, name)
        if name in {"df_hz", "window_s", "fs", "overlap"}:
            if value is None:
                assert actual is None, name
            else:
                assert actual == pytest.approx(value), name
        else:
            assert actual == value, f"{name}: {actual!r} != {value!r}"


@pytest.mark.parametrize(
    ("fs", "n", "t_win", "overlap", "purpose", "expected"),
    [
        (
            1000.0, 60000, 1.5, 0.5, "fft_segmented",
            dict(
                id="M1",
                requested_nfft=4096,
                effective_nfft=4096,
                frames=28,
                df_hz=0.244140625,
                window_s=4.096,
                status="normal",
                reasons=("preferred_4096",),
                degraded=False,
            ),
        ),
        (
            1000.0, 20000, 1.5, 0.5, "fft_segmented",
            dict(
                id="M2",
                requested_nfft=4096,
                effective_nfft=4096,
                frames=8,
                status="normal",
                reasons=("preferred_4096",),
                degraded=False,
            ),
        ),
        (
            1000.0, 10000, 1.5, 0.5, "fft_segmented",
            dict(
                id="M3",
                requested_nfft=4096,
                effective_nfft=4096,
                frames=3,
                status="warning",
                reasons=("preferred_4096", "limited_statistics"),
                degraded=False,
            ),
        ),
        (
            1000.0, 10000, 1.5, 0.5, "fft_time",
            dict(
                id="M4",
                requested_nfft=4096,
                effective_nfft=4096,
                frames=4,
                status="notice",
                reasons=("preferred_4096", "limited_time_frames"),
                degraded=False,
            ),
        ),
        (
            1000.0, 8000, 1.5, 0.5, "fft_time",
            dict(
                id="M5",
                requested_nfft=4096,
                effective_nfft=2048,
                frames=7,
                status="notice",
                reasons=(
                    "preferred_4096",
                    "fft_time_frame_guard",
                    "limited_time_frames",
                ),
                degraded=True,
            ),
        ),
        (
            1000.0, 10000, 1.5, 0.8, "fft_time",
            dict(
                id="M6",
                requested_nfft=4096,
                effective_nfft=4096,
                frames=9,
                status="normal",
                reasons=("preferred_4096",),
                degraded=False,
            ),
        ),
        (
            96.0, 5002, 1.5, 0.75, "fft_segmented",
            dict(
                id="M7",
                requested_nfft=256,
                effective_nfft=256,
                frames=75,
                df_hz=0.375,
                window_s=256 / 96.0,
                status="normal",
                reasons=("low_fs_duration_guard",),
                degraded=False,
            ),
        ),
        (
            1000.0, 3000, 1.5, 0.5, "fft_segmented",
            dict(
                id="M8",
                requested_nfft=4096,
                effective_nfft=2048,
                frames=1,
                status="warning",
                reasons=(
                    "preferred_4096",
                    "short_record_clamp",
                    "limited_statistics",
                ),
                degraded=True,
            ),
        ),
    ],
    ids=lambda value: value["id"] if isinstance(value, dict) and "id" in value else str(value),
)
def test_resolve_auto_nfft_acceptance_matrix(fs, n, t_win, overlap, purpose, expected):
    expected = dict(expected)
    case_id = expected.pop("id")
    decision = resolve_auto_nfft(fs, n, t_win, overlap, purpose=purpose)
    _assert_auto_nfft(
        decision,
        purpose=purpose,
        preferred_nfft=4096,
        fs=fs,
        n_samples=n,
        overlap=overlap,
        **expected,
    )
    assert case_id
    if decision.effective_nfft is not None:
        assert decision.effective_nfft <= n
        assert decision.df_hz == pytest.approx(fs / decision.effective_nfft)


@pytest.mark.parametrize("purpose", ["fft_segmented", "fft_time"])
@pytest.mark.parametrize("n_samples", [1, 32, 63])
def test_resolve_auto_nfft_m10_blocks_short_records(purpose, n_samples):
    decision = resolve_auto_nfft(1000.0, n_samples, 1.5, 0.5, purpose=purpose)
    _assert_auto_nfft(
        decision,
        purpose=purpose,
        effective_nfft=None,
        df_hz=None,
        window_s=None,
        frames=0,
        degraded=None,
        status="blocked",
    )
    assert "insufficient_samples" in decision.reasons
    assert decision.requested_nfft == 4096


@pytest.mark.parametrize("purpose", ["fft_segmented", "fft_time"])
@pytest.mark.parametrize(
    ("fs", "df_hz", "segmented_frames", "time_frames"),
    [
        (10.0, 0.15625, 186, 187),
        (20.0, 0.3125, 186, 187),
    ],
)
def test_resolve_auto_nfft_b1_minimum_floor_low_fs(
    purpose, fs, df_hz, segmented_frames, time_frames,
):
    decision = resolve_auto_nfft(fs, 6000, 1.5, 0.5, purpose=purpose)
    frames = segmented_frames if purpose == "fft_segmented" else time_frames
    _assert_auto_nfft(
        decision,
        purpose=purpose,
        requested_nfft=64,
        effective_nfft=64,
        df_hz=df_hz,
        window_s=64.0 / fs,
        frames=frames,
        status="normal",
        reasons=("low_fs_duration_guard", "minimum_nfft_floor"),
        degraded=False,
    )


@pytest.mark.parametrize("purpose", ["fft_segmented", "fft_time"])
def test_resolve_auto_nfft_b2_short_target_window_floors_to_64(purpose):
    decision = resolve_auto_nfft(96.0, 5002, 0.1, 0.75, purpose=purpose)
    _assert_auto_nfft(
        decision,
        requested_nfft=64,
        effective_nfft=64,
        status="normal",
        degraded=False,
    )
    assert "minimum_nfft_floor" in decision.reasons
    assert decision.status != "blocked"


def test_resolve_auto_nfft_b3_sample_and_frame_thresholds():
    seg_63 = resolve_auto_nfft(1000.0, 63, 1.5, 0.5, purpose="fft_segmented")
    assert seg_63.status == "blocked"
    assert "insufficient_samples" in seg_63.reasons

    for n in (64, 65):
        seg = resolve_auto_nfft(1000.0, n, 1.5, 0.5, purpose="fft_segmented")
        _assert_auto_nfft(
            seg,
            effective_nfft=64,
            frames=1,
            status="warning",
        )
        assert "limited_statistics" in seg.reasons

    time_63 = resolve_auto_nfft(1000.0, 63, 1.5, 0.5, purpose="fft_time")
    assert time_63.status == "blocked"
    assert "insufficient_samples" in time_63.reasons

    time_64 = resolve_auto_nfft(1000.0, 64, 1.5, 0.5, purpose="fft_time")
    assert time_64.status == "blocked"
    assert "insufficient_time_frames" in time_64.reasons
    assert "insufficient_samples" not in time_64.reasons

    time_65 = resolve_auto_nfft(1000.0, 65, 1.5, 0.5, purpose="fft_time")
    assert time_65.status == "blocked"
    assert "insufficient_time_frames" in time_65.reasons
    assert "insufficient_samples" not in time_65.reasons


def test_resolve_auto_nfft_b4_fft_time_tail_frame_boundary():
    blocked = resolve_auto_nfft(1000.0, 128, 1.5, 0.5, purpose="fft_time")
    assert blocked.status == "blocked"
    assert blocked.frames == 0
    assert blocked.effective_nfft is None
    assert "insufficient_time_frames" in blocked.reasons

    ok = resolve_auto_nfft(1000.0, 129, 1.5, 0.5, purpose="fft_time")
    _assert_auto_nfft(
        ok,
        effective_nfft=64,
        frames=4,
        status="notice",
        degraded=True,
    )
    assert "limited_time_frames" in ok.reasons
    starts = canonical_spectrogram_frame_starts(129, 64, 0.5)
    assert len(starts) == 4
    assert int(starts[-1]) == 129 - 64


@pytest.mark.parametrize("purpose", ["fft_segmented", "fft_time"])
def test_resolve_auto_nfft_b5_4096_window_boundary_is_closed(purpose):
    low = resolve_auto_nfft(409.599, 60000, 1.5, 0.5, purpose=purpose)
    high = resolve_auto_nfft(409.6, 60000, 1.5, 0.5, purpose=purpose)
    assert low.requested_nfft == 1024
    assert low.effective_nfft == 1024
    assert "low_fs_duration_guard" in low.reasons
    assert high.requested_nfft == 4096
    assert high.effective_nfft == 4096
    assert high.reasons[0] == "preferred_4096"


def test_resolve_auto_nfft_b6_purpose_ceilings_keep_duration_target():
    segmented = resolve_auto_nfft(10000.0, 1_000_000, 4.0, 0.5, purpose="fft_segmented")
    fft_time = resolve_auto_nfft(10000.0, 1_000_000, 4.0, 0.5, purpose="fft_time")
    assert segmented.duration_target_nfft == 65536
    assert fft_time.duration_target_nfft == 65536
    _assert_auto_nfft(
        segmented,
        requested_nfft=16384,
        effective_nfft=16384,
        reasons=("duration_target", "auto_ceiling"),
        status="normal",
    )
    _assert_auto_nfft(
        fft_time,
        requested_nfft=8192,
        effective_nfft=8192,
        reasons=("duration_target", "auto_ceiling"),
        status="normal",
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fs": float("nan")},
        {"fs": float("inf")},
        {"fs": 0.0},
        {"fs": -10.0},
        {"t_win_s": float("nan")},
        {"t_win_s": 0.0},
        {"t_win_s": -1.5},
        {"overlap": -0.1},
        {"overlap": 0.96},
        {"overlap": 1.0},
        {"overlap": float("nan")},
        {"overlap": float("inf")},
        {"n_samples": 0},
        {"n_samples": -1},
        {"n_samples": 1.5},
        {"n_samples": True},
        {"n_samples": False},
        {"n_samples": None},
        {"n_samples": "64"},
        {"fs": 1e308, "t_win_s": 1e308},
        {"purpose": "order"},
        {"purpose": "single_frame"},
    ],
)
def test_resolve_auto_nfft_b7_rejects_illegal_inputs(kwargs):
    params = {
        "fs": 1000.0,
        "n_samples": 60000,
        "t_win_s": 1.5,
        "overlap": 0.5,
        "purpose": "fft_segmented",
    }
    params.update(kwargs)
    with pytest.raises(ValueError):
        resolve_auto_nfft(
            params["fs"],
            params["n_samples"],
            params["t_win_s"],
            params["overlap"],
            purpose=params["purpose"],
        )


@pytest.mark.parametrize("overlap", [0.0, 0.95])
@pytest.mark.parametrize(
    ("n_samples", "nfft"),
    [
        (4096, 4096),
        (8192, 4096),
        (8193, 4096),
        (10000, 4096),
        (64, 64),
        (130, 64),
    ],
)
def test_frame_counters_match_analyzer_loops_b8(overlap, n_samples, nfft):
    hop = segmented_analysis_hop(nfft, overlap)
    expected_non_tail = 0
    if n_samples >= nfft:
        expected_non_tail = (n_samples - nfft) // hop + 1
        for i in range(expected_non_tail):
            assert i * hop + nfft <= n_samples
        if expected_non_tail:
            assert (expected_non_tail - 1) * hop + nfft <= n_samples
            assert expected_non_tail * hop + nfft > n_samples or (
                (expected_non_tail - 1) * hop + nfft <= n_samples
            )
    assert non_tail_frame_count(n_samples, nfft, overlap) == expected_non_tail

    spec_hop = spectrogram_analysis_hop(nfft, overlap)
    analyzer_starts = SpectrogramAnalyzer._frame_starts(n_samples, nfft, spec_hop)
    owned_starts = canonical_spectrogram_frame_starts(n_samples, nfft, overlap)
    assert np.array_equal(owned_starts, analyzer_starts)
    assert canonical_spectrogram_frame_count(n_samples, nfft, overlap) == len(
        owned_starts
    )
    if owned_starts.size >= 2:
        assert int(owned_starts[-1]) != int(owned_starts[-2])


def test_non_tail_count_matches_averaged_fft_loop():
    n_samples = 10000
    nfft = 4096
    overlap = 0.5
    sig = np.zeros(n_samples, dtype=float)
    freq, _amp, _psd = FFTAnalyzer.compute_averaged_fft(
        sig, 1000.0, "hanning", nfft, overlap,
    )
    assert non_tail_frame_count(n_samples, nfft, overlap) == 3
    hop = segmented_analysis_hop(nfft, overlap)
    n_segments = max((n_samples - nfft) // hop + 1, 1)
    assert n_segments == 3
    assert freq.shape[0] == nfft // 2


def test_auto_nfft_decision_is_frozen_and_does_not_zero_pad():
    decision = resolve_auto_nfft(1000.0, 3000, 1.5, 0.5, purpose="fft_segmented")
    with pytest.raises(Exception):
        decision.effective_nfft = 4096
    assert decision.effective_nfft == 2048
    assert decision.window_s == pytest.approx(2048 / 1000.0)


def test_legacy_resolve_nfft_keeps_historical_24_frame_policy():
    assert resolve_nfft(1000, 60000, 1.5, 0.5) == 2048
    assert resolve_nfft(1000, 20000, 1.5, 0.5) != resolve_auto_nfft(
        1000.0, 20000, 1.5, 0.5, purpose="fft_segmented",
    ).effective_nfft


@pytest.mark.parametrize(
    ("samples_per_rev", "order_res", "n_angle", "expected"),
    [
        (256, 0.05, 1_000_000, 8192),
        (512, 0.10, 1_000_000, 8192),
        (256, 0.25, 1_000_000, 1024),
        (256, 0.05, 4096, 1024),
        (256, 0.05, 12000, 4096),
        (64, 1.0, 1_000_000, 256),
        (1024, 0.01, 10_000_000, 16384),
    ],
)
def test_resolve_order_nfft_characterization_is_frozen(
    samples_per_rev, order_res, n_angle, expected,
):
    assert resolve_order_nfft(samples_per_rev, order_res, n_angle) == expected


def test_requested_auto_nfft_is_data_blind_target():
    assert requested_auto_nfft(1000.0, 1.5, purpose="fft_segmented") == 4096
    assert requested_auto_nfft(96.0, 1.5, purpose="fft_segmented") == 256
    assert requested_auto_nfft(10000.0, 4.0, purpose="fft_time") == 8192


def test_m7_time_fft_auto_does_not_change_order_nfft():
    fft = resolve_auto_nfft(96.0, 5002, 1.5, 0.75, purpose="fft_segmented")
    assert fft.effective_nfft == 256
    assert "low_fs_duration_guard" in fft.reasons
    assert resolve_order_nfft(256, 0.05, 1_000_000) == 8192
    assert resolve_order_nfft(256, 0.05, 4096) == 1024
    assert resolve_order_nfft(64, 1.0, 1_000_000) == 256


def test_frf_auto_nfft_equals_nperseg_not_4096_preference():
    from mf4_analyzer.signal.frf import FrfParams, plan_frf_request

    params = FrfParams(t_win_s=1.5, overlap=0.5, nfft_mode="auto", nfft=None)
    plan = plan_frf_request(n_samples=60000, fs=1000.0, params=params)
    assert plan.nperseg == 1500
    assert plan.nfft == plan.nperseg
    assert plan.nfft != 4096
    manual = FrfParams(t_win_s=1.5, overlap=0.5, nfft_mode="manual", nfft=4096)
    manual_plan = plan_frf_request(n_samples=60000, fs=1000.0, params=manual)
    assert manual_plan.nperseg == 1500
    assert manual_plan.nfft == 4096
