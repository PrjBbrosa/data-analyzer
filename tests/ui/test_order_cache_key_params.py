"""Regression: order cache-key params must include rpm_factor and fs,
so changing either alone produces a different key (no stale cache hit)."""
from mf4_analyzer.ui.main_window._order_mixin import OrderMixin

_BASE = {
    'nfft_effective': 8192, 'nfft_mode': 'auto', 'max_order': 10,
    'order_res': 0.1, 'time_res': 0.05, 'samples_per_rev': 512,
    'rpm_factor': 1.0, 'fs': 100.0,
}


def test_rpm_factor_changes_cache_params():
    a = OrderMixin._order_compute_cache_params(dict(_BASE), None, None)
    b = OrderMixin._order_compute_cache_params(dict(_BASE, rpm_factor=2.0), None, None)
    assert a != b
    assert a['rpm_factor'] == 1.0 and b['rpm_factor'] == 2.0


def test_fs_changes_cache_params():
    a = OrderMixin._order_compute_cache_params(dict(_BASE), None, None)
    b = OrderMixin._order_compute_cache_params(dict(_BASE, fs=200.0), None, None)
    assert a != b
    assert a['fs'] == 100.0 and b['fs'] == 200.0
