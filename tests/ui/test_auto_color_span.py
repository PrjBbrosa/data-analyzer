"""Auto color-scale window: 30 dB below the percentile, +5 dB headroom.

The floor stays a fixed 30 dB under the robust percentile. The ceiling is
that percentile plus 5 dB, capped at the finite maximum. Heatmap, Order and
the batch renderer's finite-data branch all resolve through ``_auto_db_window``.
"""
import numpy as np


def test_auto_db_window_default_span_is_30(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    # A flat ramp [-50, 10]: the percentile sits just under the maximum, so
    # the ceiling caps at the maximum and the floor stays 30 dB below p99.
    m = np.linspace(-50.0, 10.0, 6001).reshape(1, -1)
    vmin, vmax = hc._auto_db_window(m)

    anchor = hc._robust_db_ceiling(m, hc._AUTO_CEILING_PCT)
    assert vmax == float(np.max(m))
    assert abs(vmin - (anchor - hc._AUTO_SPAN_DB)) < 1e-9
    assert hc._AUTO_SPAN_DB == 30.0
    assert hc._AUTO_CEILING_HEADROOM_DB == 5.0


def test_auto_db_window_is_nan_safe(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    m = np.array([[-30.0, np.nan, -10.0, np.inf, -20.0]])
    vmin, vmax = hc._auto_db_window(m)
    anchor = hc._robust_db_ceiling(m, hc._AUTO_CEILING_PCT)
    finite_peak = float(np.max(m[np.isfinite(m)]))
    assert np.isfinite(vmin) and np.isfinite(vmax)
    assert vmin == anchor - hc._AUTO_SPAN_DB
    assert vmax == min(finite_peak, anchor + hc._AUTO_CEILING_HEADROOM_DB)
