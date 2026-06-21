"""Auto color-scale span (Phase A1): default 30 dB + single-source window.

The absolute-dB auto colour window historically used a fixed 40 dB span. Noise
analysis mostly wants a 30 dB window, so the default span drops to 30; the
ceiling stays the robust high-percentile anchor. Both the heatmap z_auto path
and the Order render override must resolve through the SAME helper so the two
windows can never drift apart (the recurring compute-vs-display disease).
"""
import numpy as np


def test_auto_db_window_default_span_is_30(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    # A flat ramp [-50, 10]: the 99th-percentile ceiling lands near the top (10).
    m = np.linspace(-50.0, 10.0, 6001).reshape(1, -1)
    vmin, vmax = hc._auto_db_window(m)

    ceiling = hc._robust_db_ceiling(m, hc._AUTO_CEILING_PCT)
    assert vmax == ceiling                       # ceiling unchanged (robust p99)
    assert abs((vmax - vmin) - 30.0) < 1e-9      # default span is 30, not 40
    assert hc._AUTO_SPAN_DB == 30.0              # the module default itself


def test_auto_db_window_is_nan_safe(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    m = np.array([[-30.0, np.nan, -10.0, np.inf, -20.0]])
    vmin, vmax = hc._auto_db_window(m)
    assert np.isfinite(vmin) and np.isfinite(vmax)
    assert abs((vmax - vmin) - hc._AUTO_SPAN_DB) < 1e-9
