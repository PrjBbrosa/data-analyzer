import numpy as np
import pytest

from mf4_analyzer.signal import (
    assess_speed_for_order,
    ceil_pow2,
    energy_band_fmax,
    order_angle_sample_count,
    resolve_nfft,
    resolve_order_nfft,
    revolutions_from_rpm,
)


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
