"""Tests for ``OrderAnalyzer._orders`` sub-bin pseudo-order floor.

These tests pin the contract added in plan
``2026-04-28-fft-order-head-parity.md`` Task 3.3:

* The legacy two-arg call signature is preserved (backwards compat).
* When ``fs``/``nfft``/``rpm`` are passed, orders below the FFT bin
  resolution at peak |RPM| are dropped from the output grid.
* When |RPM| is high enough that ``df * 60 / rpm_max <= order_res``,
  no floor is applied and the legacy grid is returned.
"""
from __future__ import annotations

import numpy as np

from mf4_analyzer.signal.order import OrderAnalyzer


def test_orders_legacy_call_unchanged():
    """Legacy two-arg call must keep returning the full grid."""
    o = OrderAnalyzer._orders(20.0, 0.1)
    assert len(o) == 200
    assert np.isclose(o[0], 0.1)
    assert np.isclose(o[-1], 20.0)


def test_orders_with_subbin_floor_drops_low_orders():
    """At fs=100, nfft=1024, max|RPM|=10 -> df*60/RPM = 0.0977*60/10 = 0.586;
    so the floor must drop orders 0.1, 0.2, 0.3, 0.4, 0.5."""
    rpm = np.array([0, 10, 10, 10])  # max|RPM|=10 -> floor = 0.586
    o = OrderAnalyzer._orders(20.0, 0.1, fs=100.0, nfft=1024, rpm=rpm)
    assert o[0] >= 0.5, f"floor failed; first order is {o[0]} (expected >= 0.5)"
    assert o[0] >= 0.586 - 1e-9
    assert o[-1] == 20.0


def test_orders_with_high_rpm_no_floor_kicks_in():
    """At max|RPM|=600 -> df*60/RPM = 0.0098, below order_res 0.1, so no
    floor is applied."""
    rpm = np.array([0, 600, 600])
    o = OrderAnalyzer._orders(20.0, 0.1, fs=100.0, nfft=1024, rpm=rpm)
    assert np.isclose(o[0], 0.1)
