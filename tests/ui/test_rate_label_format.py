"""Regression: two rasters at the same rate must carry the same label.

A WWT file whose signals were recorded over different spans splits into
logical sources with the same 1 ms time base but different sample counts.
``FileData.fs`` is ``1 / median(diff(time))``, and that reconstruction lands
either side of 1000.0 depending on the count -- 1000.000000000000796 for the
10450-sample group, 999.999999999999091 for the 9460-sample one.  A bare
``fs >= 1000`` therefore labelled the channel tree's two rasters "1.0 kHz" and
"1000 Hz", which reads as two different sample rates rather than one.
"""
import numpy as np

from mf4_analyzer.ui.widgets._swatches import _fmt_rate


def _reconstructed_fs(n, dt=0.001, t0=0.0):
    """The rate FileData derives for an ``n``-sample axis at ``dt``."""
    t = t0 + np.arange(n, dtype=np.float64) * dt
    return 1.0 / np.median(np.diff(t))


def test_same_nominal_rate_labels_identically_across_sample_counts():
    long_group = _reconstructed_fs(10450)
    short_group = _reconstructed_fs(9460)

    # The float reconstruction really does straddle the boundary.
    assert long_group > 1000.0 > short_group
    assert _fmt_rate(long_group) == _fmt_rate(short_group) == "1.0 kHz"


def test_rate_below_the_boundary_still_reads_in_hz():
    assert _fmt_rate(999.0) == "999 Hz"
    assert _fmt_rate(512.0) == "512 Hz"
    assert _fmt_rate(1.0) == "1 Hz"


def test_boundary_follows_the_value_as_the_hz_branch_would_print_it():
    """A rate the Hz branch would round up to four digits belongs in kHz."""
    assert _fmt_rate(999.4) == "999 Hz"
    assert _fmt_rate(999.6) == "1.0 kHz"


def test_higher_rates_are_unchanged():
    assert _fmt_rate(1024.0) == "1.0 kHz"
    assert _fmt_rate(2500.0) == "2.5 kHz"
    assert _fmt_rate(48000.0) == "48.0 kHz"
