"""Contract tests for :mod:`mf4_analyzer.signal.channel_math`."""

from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal.channel_math import ChannelMath


@pytest.mark.parametrize(
    ("length", "window_size"),
    ((3, 50), (10, 100), (2000, 5000), (1000, 50), (1, 1), (5, 1)),
)
def test_moving_avg_preserves_input_length(length: int, window_size: int) -> None:
    signal = np.arange(length, dtype=float)

    result = ChannelMath.moving_avg(signal, window_size)

    assert result.shape == signal.shape


def test_moving_avg_empty_input_returns_empty_float_array() -> None:
    result = ChannelMath.moving_avg(np.array([], dtype=np.int16), 50)

    assert result.shape == (0,)
    assert result.dtype == np.float64


@pytest.mark.parametrize("window_size", (3, 50))
def test_moving_avg_full_or_oversized_window_returns_whole_signal_mean(
    window_size: int,
) -> None:
    signal = np.array([1, 2, 9], dtype=np.int16)

    result = ChannelMath.moving_avg(signal, window_size)

    np.testing.assert_allclose(result, [4.0, 4.0, 4.0])
    assert result.dtype == np.float64


def test_moving_avg_regular_window_preserves_same_mode_values_and_contract() -> None:
    signal = np.array([1, 2, 3, 4, 5], dtype=np.int16)

    result = ChannelMath.moving_avg(signal, 3)

    np.testing.assert_allclose(result, [1.0, 2.0, 3.0, 4.0, 3.0])
    assert result.shape == signal.shape
    assert result.dtype == np.float64


def test_moving_avg_pins_the_full_window_boundary_semantics() -> None:
    signal = np.array([1, 2, 3, 4, 5], dtype=float)

    below_full_window = ChannelMath.moving_avg(signal, signal.size - 1)
    full_window = ChannelMath.moving_avg(signal, signal.size)

    assert not np.allclose(below_full_window, below_full_window[0])
    np.testing.assert_allclose(full_window, np.full(signal.shape, signal.mean()))


@pytest.mark.parametrize("window_size", (0, -4))
def test_moving_avg_nonpositive_window_behaves_as_unit_window(
    window_size: int,
) -> None:
    signal = np.array([2, 4, 8], dtype=np.int16)

    result = ChannelMath.moving_avg(signal, window_size)

    np.testing.assert_array_equal(result, [2.0, 4.0, 8.0])
    assert result.dtype == np.float64


def test_integral_integer_input_returns_exact_float_trapezoids() -> None:
    time = np.array([0, 1, 2, 3], dtype=np.int64)
    signal = np.array([0, 1, 2, 3], dtype=np.int64)

    result = ChannelMath.integral(time, signal)

    np.testing.assert_array_equal(result, [0.0, 0.5, 2.0, 4.5])
    assert result.shape == signal.shape
    assert result.dtype == np.float64


@pytest.mark.parametrize(
    ("time", "signal", "expected"),
    (([], [], []), ([2], [7], [0.0])),
)
def test_integral_short_input_returns_float_zeros(
    time: list[int], signal: list[int], expected: list[float]
) -> None:
    result = ChannelMath.integral(
        np.asarray(time, dtype=np.int16),
        np.asarray(signal, dtype=np.int16),
    )

    np.testing.assert_array_equal(result, expected)
    assert result.shape == (len(signal),)
    assert result.dtype == np.float64


def test_integral_of_linear_signal_matches_analytic_solution() -> None:
    time = np.linspace(0.0, 2.0, 201)

    result = ChannelMath.integral(time, time)

    np.testing.assert_allclose(result, 0.5 * time**2, rtol=0.0, atol=1e-12)


@pytest.mark.parametrize(
    ("time", "signal"),
    ((np.array([], dtype=float), np.array([], dtype=float)), ([0.0], [3.0])),
)
def test_derivative_rejects_fewer_than_two_samples(time, signal) -> None:
    with pytest.raises(ValueError, match="at least two samples"):
        ChannelMath.derivative(time, signal)


def test_derivative_of_sine_matches_cosine() -> None:
    time = np.linspace(0.0, 2.0 * np.pi, 1001)
    signal = np.sin(time)

    result = ChannelMath.derivative(time, signal)

    np.testing.assert_allclose(result, np.cos(time), rtol=0.0, atol=1e-4)
    assert result.shape == signal.shape
    assert result.dtype == np.float64


def test_scale_preserves_shape_and_applies_factor() -> None:
    signal = np.array([-2, 0, 4], dtype=np.int16)

    result = ChannelMath.scale(signal, 0.5)

    np.testing.assert_array_equal(result, [-1.0, 0.0, 2.0])
    assert result.shape == signal.shape
    assert result.dtype == np.float64


def test_offset_preserves_shape_and_applies_value() -> None:
    signal = np.array([-2, 0, 4], dtype=np.int16)

    result = ChannelMath.offset(signal, 0.25)

    np.testing.assert_array_equal(result, [-1.75, 0.25, 4.25])
    assert result.shape == signal.shape
    assert result.dtype == np.float64
