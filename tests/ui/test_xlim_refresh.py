"""Tests for the xlim-debounce / viewport refresh wiring on TimeDomainCanvas.

Phase 1 items 2 + 5 of the time-domain plot performance plan:
  - xlim_changed schedules ONE coalesced QTimer refresh
  - button_release_event flushes a pending refresh immediately
  - _refresh_visible_data updates Line2D.set_data WITHOUT rebuilding axes
  - cache invalidation forces a recompute on the next refresh
  - statistics are read from the original (t, sig) — never from envelope
  - non-monotonic custom-x falls back to the legacy reducer through the
    refresh path (envelope cache must not poison non-monotonic streams)
"""
from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.ui.canvases import TimeDomainCanvas


# -----------------------------------------------------------------
# helpers
# -----------------------------------------------------------------


def _make_canvas(qapp):
    """Construct a TimeDomainCanvas under the offscreen QApplication."""
    cv = TimeDomainCanvas()
    # Make sure the figure has a sensible bbox so pixel_width derivation
    # in _refresh_visible_data sees a non-trivial canvas.
    cv.resize(1200, 600)
    return cv


def _spike_signal(n=20_000, spike_idx=None, spike_amp=10.0,
                  rng_seed=0):
    rng = np.random.default_rng(rng_seed)
    t = np.linspace(0.0, 10.0, n)
    sig = rng.standard_normal(n).astype(np.float64) * 0.1
    if spike_idx is None:
        spike_idx = (n * 11) // 19
    sig[spike_idx] = spike_amp
    return t, sig


def _plot_two_channels(cv):
    """Build a small 2-channel overlay plot via plot_channels."""
    t1, s1 = _spike_signal(n=20_000, spike_idx=8_500, spike_amp=4.0)
    t2, s2 = _spike_signal(n=20_000, spike_idx=12_500, spike_amp=-4.0,
                           rng_seed=1)
    ch_list = [
        ("[A] sig1", True, t1, s1, "#1769e0", "g", "fidA"),
        ("[A] sig2", True, t2, s2, "#dc2626", "g", "fidA"),
    ]
    cv.plot_channels(ch_list, mode='overlay')
    return ch_list


# -----------------------------------------------------------------
# debounce / coalesce / flush
# -----------------------------------------------------------------


def test_xlim_changed_schedules_one_timer(qapp):
    """Multiple rapid xlim_changed fires coalesce to a single pending refresh."""
    cv = _make_canvas(qapp)
    _plot_two_channels(cv)

    # Drain any plot_channels-triggered scheduling.
    cv._refresh_pending = False
    if cv._refresh_timer.isActive():
        cv._refresh_timer.stop()

    fake_ax = cv._primary_xaxis_ax
    # Fire three xlim_changed callbacks in rapid succession.
    for _ in range(3):
        cv._on_xlim_changed(fake_ax)

    # Exactly one pending refresh; timer is active, has not fired yet.
    assert cv._refresh_pending is True
    assert cv._refresh_timer.isActive() is True


def test_button_release_flushes_pending_timer(qapp):
    """button_release_event must drain a pending refresh immediately."""
    cv = _make_canvas(qapp)
    _plot_two_channels(cv)
    # Start a pending refresh.
    cv._refresh_pending = False
    if cv._refresh_timer.isActive():
        cv._refresh_timer.stop()
    cv._on_xlim_changed(cv._primary_xaxis_ax)
    assert cv._refresh_pending is True
    assert cv._refresh_timer.isActive() is True

    # Synthesize a button_release_event with no axis-lock context. The
    # canvas's _on_release first runs _flush_pending_refresh(), then
    # short-circuits because self._axis_lock is None.
    fake_event = SimpleNamespace(
        inaxes=cv._primary_xaxis_ax, xdata=None, ydata=None, button=1
    )
    cv._on_release(fake_event)

    # Pending state cleared, timer stopped, refresh executed.
    assert cv._refresh_pending is False
    assert cv._refresh_timer.isActive() is False


def test_rubber_band_release_flushes_post_zoom_refresh(qapp):
    """An axis-lock rubber-band release must end with no pending QTimer.

    Regression for B-1: ``_on_release`` historically called
    ``_flush_pending_refresh`` BEFORE invoking ``ax.set_xlim(...)`` on the
    rubber-band branch. The set_xlim then fired ``xlim_changed`` and
    scheduled a fresh 40 ms debounce, leaving a pending timer behind and
    deferring the post-zoom envelope frame. The fix must ensure that
    after ``_on_release`` returns, both ``_refresh_pending`` is False and
    ``_refresh_timer.isActive()`` is False, AND the line data reflects
    the NEW xlim's envelope (i.e. ``_refresh_visible_data`` ran AFTER
    ``set_xlim``, not before).
    """
    cv = _make_canvas(qapp)
    _plot_two_channels(cv)
    primary = cv._primary_xaxis_ax

    # Start at the full range so the rubber-band zoom is genuinely a
    # different xlim and the envelope output is forced to change.
    primary.set_xlim(0.0, 10.0)
    cv._refresh_visible_data()
    # Drain anything that scheduling might have produced.
    cv._refresh_pending = False
    if cv._refresh_timer.isActive():
        cv._refresh_timer.stop()

    # Snapshot one line's xdata at the full xlim — this must change
    # after the rubber-band zoom commits the new xlim AND the refresh
    # is flushed. If the bug is present, the refresh runs BEFORE
    # set_xlim, so xdata still reflects the full range.
    line_name, (_ax, line) = next(iter(cv._channel_lines.items()))
    xdata_full_range = line.get_xdata().copy()

    # Configure the canvas as if the user had:
    #   1) set_axis_lock('x')
    #   2) pressed the left button at x=2.0 inside the primary axis
    cv._axis_lock = 'x'
    cv._rb_start = (2.0, 0.0)
    cv._rb_ax = primary
    # No need to materialize a Rectangle patch — _cancel_rb tolerates None.
    cv._rb_patch = None

    # Simulate the release at x=4.0: this reaches the rubber-band
    # branch, runs ax.set_xlim(2.0, 4.0), and (with the bug) leaves
    # a freshly scheduled 40 ms timer pending.
    fake_release = SimpleNamespace(
        inaxes=primary, xdata=4.0, ydata=0.0, button=1
    )
    cv._on_release(fake_release)

    # Acceptance: the new xlim took effect.
    new_lo, new_hi = primary.get_xlim()
    assert (new_lo, new_hi) == (2.0, 4.0), (
        f"rubber-band did not commit the new xlim: got ({new_lo}, {new_hi})"
    )

    # Acceptance: no pending QTimer survives the release. Both must hold.
    assert cv._refresh_pending is False, (
        "_on_release left _refresh_pending=True; the post-zoom xlim_changed "
        "scheduled a debounce that was never flushed"
    )
    assert cv._refresh_timer.isActive() is False, (
        "_on_release left a pending QTimer active; the post-zoom envelope "
        "frame is being held back behind the 40 ms debounce window"
    )

    # Acceptance: the line data reflects the new xlim's envelope, i.e.
    # _refresh_visible_data ran AFTER set_xlim. With the bug the envelope
    # call ran BEFORE set_xlim and xdata still spans the full range.
    xdata_after = line.get_xdata()
    assert not np.array_equal(xdata_full_range, xdata_after), (
        "line xdata is unchanged after the rubber-band zoom — refresh ran "
        "BEFORE set_xlim so the post-zoom envelope was never applied"
    )
    if len(xdata_after) > 0:
        assert xdata_after.min() >= 2.0 - 1e-9, (
            f"xdata leaks below the new xlim lower edge: min={xdata_after.min()}"
        )
        assert xdata_after.max() <= 4.0 + 1e-9, (
            f"xdata leaks above the new xlim upper edge: max={xdata_after.max()}"
        )


def test_refresh_visible_data_uses_set_data_not_rebuild(qapp):
    """_refresh_visible_data must call line.set_data, never recreate lines."""
    cv = _make_canvas(qapp)
    _plot_two_channels(cv)
    primary = cv._primary_xaxis_ax

    # Snapshot of axes & lines.
    n_axes_before = len(cv.axes_list)
    line_ids_before = {n: id(L) for n, (_, L) in cv._channel_lines.items()}
    n_lines_per_axis_before = [len(ax.lines) for ax in cv.axes_list]
    xdata_before = next(iter(cv._channel_lines.values()))[1].get_xdata().copy()

    # Zoom into a tighter range to provoke a different envelope output.
    primary.set_xlim(2.0, 4.0)
    cv._refresh_visible_data()

    # Same number of axes and lines; line identities unchanged.
    assert len(cv.axes_list) == n_axes_before
    assert [len(ax.lines) for ax in cv.axes_list] == n_lines_per_axis_before
    line_ids_after = {n: id(L) for n, (_, L) in cv._channel_lines.items()}
    assert line_ids_before == line_ids_after, (
        "viewport refresh should NOT replace Line2D objects"
    )

    # Line data did change (set_data was called).
    xdata_after = next(iter(cv._channel_lines.values()))[1].get_xdata()
    # Envelope output for a 2-second window should differ from full-range.
    assert not np.array_equal(xdata_before, xdata_after), (
        "set_data did not mutate xdata after xlim change"
    )
    # Final xdata stays inside the requested xlim (envelope window-only).
    if len(xdata_after) > 0:
        assert xdata_after.min() >= 2.0 - 1e-9
        assert xdata_after.max() <= 4.0 + 1e-9


def test_invalidate_envelope_cache_forces_miss(qapp):
    """After invalidate_envelope_cache(), the next refresh recomputes."""
    cv = _make_canvas(qapp)
    _plot_two_channels(cv)
    primary = cv._primary_xaxis_ax

    # Prime cache via one refresh at a known xlim.
    primary.set_xlim(1.0, 5.0)
    cv._refresh_visible_data()
    # Force a hit: same xlim → no new miss.
    misses_before = cv._envelope_cache_misses
    cv._refresh_visible_data()
    misses_after_hit = cv._envelope_cache_misses
    assert misses_after_hit == misses_before, "expected cache hits on repeat"

    # Now invalidate and confirm next refresh produces fresh misses.
    cv.invalidate_envelope_cache("test invalidation")
    cv._refresh_visible_data()
    misses_after_invalidation = cv._envelope_cache_misses
    assert misses_after_invalidation > misses_after_hit, (
        "invalidate_envelope_cache did not cause a recompute on next refresh"
    )


def test_statistics_unchanged_across_refresh(qapp):
    """Statistics must be identical before and after a viewport refresh.

    Regression for the statistics-vs-envelope invariant: get_statistics()
    reads the original (t, sig) buffers stashed in self.channel_data,
    which the refresh path must NOT overwrite with envelope output.
    """
    cv = _make_canvas(qapp)
    ch_list = _plot_two_channels(cv)
    primary = cv._primary_xaxis_ax

    stats_before = cv.get_statistics(time_range=None)

    # Refresh at a narrow viewport — envelope is materially different
    # from the raw arrays in this regime.
    primary.set_xlim(3.0, 3.5)
    cv._refresh_visible_data()
    primary.set_xlim(0.0, 10.0)
    cv._refresh_visible_data()

    stats_after = cv.get_statistics(time_range=None)
    assert stats_before.keys() == stats_after.keys()
    for ch in stats_before:
        for key in ("min", "max", "mean", "rms", "std", "p2p"):
            assert stats_before[ch][key] == stats_after[ch][key], (
                f"statistic {key!r} drifted across refresh on {ch!r}"
            )


def test_non_monotonic_custom_x_falls_back_through_refresh(qapp):
    """Non-monotonic custom x must still render through the refresh path.

    The refresh path goes _envelope_cached → _envelope, which checks
    monotonicity internally and falls back to _ds_legacy. We assert the
    pipeline survives a non-monotonic stream without raising and without
    poisoning the cache for the monotonic siblings.
    """
    cv = _make_canvas(qapp)
    n = 5_000
    t_mono = np.linspace(0.0, 1.0, n)
    sig_mono = np.sin(2 * np.pi * 3 * t_mono)
    t_nm = t_mono.copy()
    t_nm[1_000:1_300] = t_nm[1_000:1_300][::-1]
    sig_nm = np.cos(2 * np.pi * 3 * t_mono)

    ch_list = [
        ("[A] mono", True, t_mono, sig_mono, "#1769e0", "g", "fidA"),
        ("[A] nm",   True, t_nm,   sig_nm,   "#dc2626", "g", "fidB"),
    ]
    cv.plot_channels(ch_list, mode='overlay')
    primary = cv._primary_xaxis_ax

    # No raise on either xlim change.
    primary.set_xlim(0.2, 0.8)
    cv._refresh_visible_data()
    primary.set_xlim(0.0, 1.0)
    cv._refresh_visible_data()

    # Both lines still hold finite samples.
    for name, (_ax, line) in cv._channel_lines.items():
        xd = line.get_xdata()
        yd = line.get_ydata()
        assert len(xd) == len(yd) and len(xd) > 0, f"empty line {name!r}"
