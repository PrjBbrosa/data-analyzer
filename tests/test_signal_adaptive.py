import numpy as np
import pytest

from mf4_analyzer.signal import (
    assess_speed_for_order,
    ceil_pow2,
    energy_band_fmax,
    resolve_nfft,
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
