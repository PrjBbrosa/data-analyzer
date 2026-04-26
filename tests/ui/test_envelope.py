"""TDD tests for viewport-aware envelope downsampling on TimeDomainCanvas.

Covers Phase 1 items 1, 4, 6 of the time-domain plot performance report:
  - _envelope() viewport min/max bucketing
  - LRU envelope cache with quantized xlim key
  - Monotonicity cache for custom x-axis arrays
  - Statistics invariance vs. envelope output

These tests are written BEFORE the implementation (TDD iron law).
"""
import numpy as np
import pytest

from mf4_analyzer.ui.canvases import TimeDomainCanvas


# -----------------------------------------------------------------
# helpers
# -----------------------------------------------------------------


def _make_canvas(qapp):
    return TimeDomainCanvas()


def _spike_signal(n=200_000, spike_idx=None, spike_amp=10.0,
                  rng_seed=0):
    """Uniformly-sampled noisy signal with one narrow spike."""
    rng = np.random.default_rng(rng_seed)
    t = np.linspace(0.0, 10.0, n)
    sig = rng.standard_normal(n).astype(np.float64) * 0.1
    if spike_idx is None:
        spike_idx = (n * 11) // 19  # interior, deterministic, never 0/N-1
    sig[spike_idx] = spike_amp
    return t, sig


# -----------------------------------------------------------------
# _envelope correctness
# -----------------------------------------------------------------


def test_envelope_preserves_narrow_spike_in_full_view(qapp):
    """A single-sample spike must survive a full-view envelope."""
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=200_000, spike_idx=123_457, spike_amp=10.0)
    pixel_width = 1200
    xlim = (t[0], t[-1])
    td, sd = cv._envelope(t, sig, xlim=xlim, pixel_width=pixel_width)

    # Output must be much smaller than input but still expose the spike's value.
    assert len(td) <= 4 * pixel_width
    assert len(td) < len(t)
    assert np.isclose(np.max(sd), 10.0, atol=1e-9), (
        "spike amplitude lost during envelope downsampling"
    )


def test_envelope_two_points_per_bucket_ordered_by_time(qapp):
    """Each bucket emits min and max ordered along the time axis."""
    cv = _make_canvas(qapp)
    n = 10_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 50 * t)
    pixel_width = 200
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=pixel_width)

    # Time-ordered (non-decreasing).
    assert np.all(np.diff(td) >= 0), "envelope output not time-ordered"
    # Roughly 2 samples per pixel bucket (we allow flexibility for de-dupe
    # and the integer-floor bucket-count rounding inside `_envelope`,
    # which can produce slightly more than `pixel_width` actual buckets
    # when `n_vis` is not divisible by `bs`).
    assert len(td) <= 2 * pixel_width + max(8, pixel_width // 100)
    # Each bucket-pair should still cover a useful fraction of pixels.
    assert len(td) >= pixel_width  # at least ~1 per pixel


def test_envelope_visible_window_only(qapp):
    """Envelope only considers samples within the visible xlim."""
    cv = _make_canvas(qapp)
    n = 20_000
    t = np.linspace(0.0, 10.0, n)
    sig = np.zeros(n)
    # Place a giant spike OUTSIDE the visible xlim. It must not appear.
    sig[100] = 1e6
    # Place a smaller, but unmistakable, spike INSIDE the visible xlim.
    inside_idx = 15_000
    sig[inside_idx] = 7.5
    xlim = (t[10_000], t[-1])
    td, sd = cv._envelope(t, sig, xlim=xlim, pixel_width=400)
    assert np.max(sd) < 1e5, "out-of-view spike leaked into envelope output"
    assert np.isclose(np.max(sd), 7.5, atol=1e-9)
    # All output times stay within the visible window.
    assert td.min() >= xlim[0] - 1e-12
    assert td.max() <= xlim[1] + 1e-12


def test_envelope_small_visible_returns_raw_slice(qapp):
    """When visible-point-count <= 2 * pixel_width, return the raw slice."""
    cv = _make_canvas(qapp)
    n = 800
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 4 * t)
    pixel_width = 1200  # 2*1200 = 2400 > n => raw slice expected
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=pixel_width)
    assert len(td) == n
    np.testing.assert_array_equal(td, t)
    np.testing.assert_array_equal(sd, sig)


# -----------------------------------------------------------------
# Edge cases (Phase B item D — code-review should-fix items)
# -----------------------------------------------------------------


def test_envelope_xlim_entirely_outside_data_range(qapp):
    """xlim wholly outside the data domain → empty arrays, no exception."""
    cv = _make_canvas(qapp)
    n = 5_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 5 * t)
    # xlim past the right edge: no overlap with data.
    td, sd = cv._envelope(t, sig, xlim=(2.0, 3.0), pixel_width=400)
    assert len(td) == 0
    assert len(sd) == 0


def test_envelope_xlim_zero_width_returns_at_most_one_sample(qapp):
    """xlim[0] == xlim[1] → at most one visible sample, no exception."""
    cv = _make_canvas(qapp)
    n = 5_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 5 * t)
    x_pin = float(t[2_500])
    td, sd = cv._envelope(t, sig, xlim=(x_pin, x_pin), pixel_width=400)
    # searchsorted with side='left' / side='right' on a single equal value
    # may return either 0 (no samples) or 1 (the matched sample). Both
    # are acceptable; the contract is "no crash, bounded output".
    assert len(td) <= 1
    assert len(sd) <= 1


def test_envelope_zero_length_signal(qapp):
    """Length-0 signal → empty arrays, no exception."""
    cv = _make_canvas(qapp)
    t = np.array([], dtype=np.float64)
    sig = np.array([], dtype=np.float64)
    td, sd = cv._envelope(t, sig, xlim=(0.0, 1.0), pixel_width=400)
    assert len(td) == 0
    assert len(sd) == 0


def test_envelope_single_sample_signal(qapp):
    """Length-1 signal → no exception, sensible output."""
    cv = _make_canvas(qapp)
    t = np.array([0.5])
    sig = np.array([7.0])
    # xlim covers the lone sample.
    td, sd = cv._envelope(t, sig, xlim=(0.0, 1.0), pixel_width=400)
    assert len(td) == 1
    assert sd[0] == 7.0
    # xlim entirely outside the lone sample.
    td2, sd2 = cv._envelope(t, sig, xlim=(2.0, 3.0), pixel_width=400)
    assert len(td2) == 0


def test_envelope_all_nan_signal_no_runtime_warning(qapp):
    """All-NaN signal must not emit a NumPy RuntimeWarning."""
    import warnings
    cv = _make_canvas(qapp)
    n = 4_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.full(n, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=200)
    # Output should be NaN-only (the polyline has no finite samples to
    # connect; consumers see a hidden line, which is the correct visual).
    assert len(sd) > 0
    assert np.all(np.isnan(sd))


def test_envelope_inf_values_handled(qapp):
    """+inf and -inf samples must surface through argmin/argmax without crash.

    Documented behavior: inf is finite for argmin/argmax purposes (NumPy
    treats it as a comparable extremum), so a bucket containing +inf
    yields +inf for its max, and a bucket containing -inf yields -inf
    for its min. NaN is the only value that triggers the all-NaN branch.
    """
    cv = _make_canvas(qapp)
    n = 4_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 5 * t)
    sig[1_000] = np.inf
    sig[3_000] = -np.inf
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=200)
    # Both extrema must propagate to the output.
    assert np.any(np.isposinf(sd)), "+inf was not preserved through envelope"
    assert np.any(np.isneginf(sd)), "-inf was not preserved through envelope"


def test_envelope_n_vis_just_above_two_pixel_width(qapp):
    """Single-sample bucket regime: n_vis just above 2*pixel_width.

    With n_vis = 2*pixel_width + 1 and pixel_width small, bs = 1 and
    each bucket holds a single sample — both argmin and argmax point at
    the same index, so the bucket emits one sample, not two.
    """
    cv = _make_canvas(qapp)
    pixel_width = 100
    n = 2 * pixel_width + 1   # 201
    t = np.linspace(0.0, 1.0, n)
    sig = np.linspace(-1.0, 1.0, n)
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]),
                          pixel_width=pixel_width)
    # We are above the small-visible shortcut. Each unit-width bucket
    # has a single sample → one output per bucket.
    assert len(td) <= 2 * pixel_width + max(8, pixel_width // 100)
    assert len(td) >= pixel_width
    # Time-ordered.
    assert np.all(np.diff(td) >= 0)


# -----------------------------------------------------------------
# NaN handling
# -----------------------------------------------------------------


def test_envelope_all_nan_bucket_emits_nan_break(qapp):
    """A bucket whose samples are entirely NaN must produce a NaN break."""
    cv = _make_canvas(qapp)
    n = 4000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 10 * t)
    # NaN out the middle ~25% so at least one full bucket lands all-NaN.
    sig[1500:2500] = np.nan
    pixel_width = 50  # ~50 buckets across n=4000 → ~80 samples/bucket
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=pixel_width)
    # Some output sample must be NaN to break the line.
    assert np.any(np.isnan(sd)), "all-NaN bucket did not preserve a NaN break"


def test_envelope_partial_nan_bucket_uses_nanargmin_max(qapp):
    """Partially-NaN bucket extracts finite extrema."""
    cv = _make_canvas(qapp)
    n = 1200
    t = np.linspace(0.0, 1.0, n)
    sig = np.zeros(n)
    sig[10] = -3.0
    sig[20] = 4.0
    # NaN-out a few samples in the same bucket as the extrema.
    sig[5] = np.nan
    sig[25] = np.nan
    # Force a single bucket spanning the whole range so we test extraction.
    pixel_width = 1  # 1 bucket
    # n > 2*pixel_width=2, so envelope path is taken (not raw slice).
    td, sd = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=pixel_width)
    # The bucket must surface both finite extrema (not NaN).
    finite = sd[np.isfinite(sd)]
    assert finite.size >= 2
    assert np.isclose(finite.min(), -3.0)
    assert np.isclose(finite.max(), 4.0)


# -----------------------------------------------------------------
# non-monotonic fallback to legacy _ds
# -----------------------------------------------------------------


def test_envelope_non_monotonic_falls_back_to_ds(qapp):
    """Non-monotonic x → fall back to legacy full-series _ds()."""
    cv = _make_canvas(qapp)
    n = 30_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 5 * t)
    # Shuffle a chunk to break monotonicity.
    perm = np.arange(n)
    perm[5000:5200] = perm[5000:5200][::-1]
    t_nm = t[perm]
    sig_nm = sig[perm]
    # Reference output of legacy _ds (no xlim/pixel_width supplied).
    td_legacy, sd_legacy = cv._ds(t_nm, sig_nm)
    td_env, sd_env = cv._envelope(t_nm, sig_nm, xlim=(t.min(), t.max()),
                                  pixel_width=1200)
    np.testing.assert_array_equal(td_env, td_legacy)
    np.testing.assert_array_equal(sd_env, sd_legacy)


# -----------------------------------------------------------------
# LRU cache with quantized xlim
# -----------------------------------------------------------------


def test_envelope_cache_hit_with_subpixel_xlim_jitter(qapp):
    """Sub-pixel xlim jitter during pan must hit the same cache entry."""
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=50_000)
    pixel_width = 1200
    span = t[-1] - t[0]
    # Two xlims that differ by far less than the bucket width.
    xlim_a = (1.0, 5.0)
    bucket_w = (xlim_a[1] - xlim_a[0]) / pixel_width
    jitter = bucket_w * 0.01  # 1% of one bucket width
    xlim_b = (1.0 + jitter, 5.0 + jitter)

    cv.invalidate_envelope_cache("test reset")
    # Public envelope lookup with cache key (data_id, channel_name, xlim, pw).
    key_args = dict(data_id="fid_1", channel_name="ch_a", pixel_width=pixel_width)

    out_a = cv._envelope_cached(t, sig, xlim=xlim_a, **key_args)
    misses_after_a = cv._envelope_cache_misses
    out_b = cv._envelope_cached(t, sig, xlim=xlim_b, **key_args)
    misses_after_b = cv._envelope_cache_misses
    # No new miss when jitter is sub-bucket — xlim is quantized to the bucket.
    assert misses_after_b == misses_after_a, (
        "sub-pixel xlim jitter caused an unexpected cache miss"
    )
    # Outputs must match (cache hit returns the same arrays).
    np.testing.assert_array_equal(out_a[0], out_b[0])
    np.testing.assert_array_equal(out_a[1], out_b[1])


def test_envelope_cache_miss_for_distinct_views(qapp):
    """Different xlims (beyond quantization) must miss."""
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=50_000)
    pixel_width = 1200
    cv.invalidate_envelope_cache("test reset")
    key_args = dict(data_id="fid_1", channel_name="ch_a", pixel_width=pixel_width)
    cv._envelope_cached(t, sig, xlim=(0.0, 5.0), **key_args)
    misses_after_first = cv._envelope_cache_misses
    cv._envelope_cached(t, sig, xlim=(5.0, 10.0), **key_args)
    misses_after_second = cv._envelope_cache_misses
    assert misses_after_second == misses_after_first + 1


def test_envelope_cache_lru_capacity(qapp):
    """Cache must cap entries to avoid unbounded memory growth."""
    cv = _make_canvas(qapp)
    cap = cv._envelope_cache_capacity
    assert cap >= 16  # sanity: capacity is a small int
    t, sig = _spike_signal(n=10_000)
    cv.invalidate_envelope_cache("reset")
    # Insert 2*cap distinct entries.
    for i in range(2 * cap):
        cv._envelope_cached(t, sig, xlim=(float(i), float(i + 1)),
                             data_id="fid", channel_name=f"ch{i}",
                             pixel_width=600)
    assert len(cv._envelope_cache) <= cap


def test_envelope_cache_invalidate_all(qapp):
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=10_000)
    cv._envelope_cached(t, sig, xlim=(0.0, 5.0), data_id="f", channel_name="c",
                         pixel_width=400)
    assert len(cv._envelope_cache) > 0
    cv.invalidate_envelope_cache("file closed")
    assert len(cv._envelope_cache) == 0


def test_envelope_cache_invalidate_filtered(qapp):
    """Invalidate only entries for a given data_id (or channel)."""
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=5_000)
    cv.invalidate_envelope_cache("reset")
    cv._envelope_cached(t, sig, xlim=(0.0, 5.0), data_id="A", channel_name="c1",
                         pixel_width=400)
    cv._envelope_cached(t, sig, xlim=(0.0, 5.0), data_id="B", channel_name="c1",
                         pixel_width=400)
    assert len(cv._envelope_cache) == 2
    cv.invalidate_envelope_cache("file A closed", data_id="A")
    # Only B's entry survives.
    assert len(cv._envelope_cache) == 1


# -----------------------------------------------------------------
# Monotonicity cache
# -----------------------------------------------------------------


def test_monotonicity_cache_hit_then_invalidate(qapp):
    cv = _make_canvas(qapp)
    t = np.linspace(0.0, 1.0, 50_000)

    # First call computes and stores result.
    res1 = cv._is_monotonic(t, custom_xaxis_fid="fid", custom_xaxis_ch="ch")
    assert res1 is True
    # Second call should hit cache (no recomputation marker).
    misses_before = cv._monotonicity_cache_misses
    res2 = cv._is_monotonic(t, custom_xaxis_fid="fid", custom_xaxis_ch="ch")
    misses_after = cv._monotonicity_cache_misses
    assert res2 is True
    assert misses_after == misses_before, "monotonicity cache miss on hit"

    # Invalidate and confirm a recompute.
    cv.invalidate_monotonicity_cache(custom_xaxis_fid="fid",
                                      custom_xaxis_ch="ch")
    cv._is_monotonic(t, custom_xaxis_fid="fid", custom_xaxis_ch="ch")
    assert cv._monotonicity_cache_misses == misses_after + 1


def test_monotonicity_cache_detects_non_monotonic(qapp):
    cv = _make_canvas(qapp)
    t = np.linspace(0.0, 1.0, 1000)
    t_nm = t.copy()
    t_nm[400:600] = t_nm[400:600][::-1]
    res = cv._is_monotonic(t_nm, custom_xaxis_fid="x", custom_xaxis_ch="y")
    assert res is False


# -----------------------------------------------------------------
# F-1 follow-up: _envelope must consume the monotonicity cache so the
# refresh path stops re-running np.diff(t) on every viewport change.
# Shape (b): plot_channels populates a parallel _channel_is_monotonic
# dict; _refresh_visible_data → _envelope_cached → _envelope reads it.
# -----------------------------------------------------------------


def _patch_monotonic_counter(monkeypatch):
    """Wrap canvases._is_monotonic_array with a counter; return [counter_box]."""
    from mf4_analyzer.ui import canvases as _cv_mod
    counter = {"n": 0}
    real_fn = _cv_mod._is_monotonic_array

    def _wrapped(t):
        counter["n"] += 1
        return real_fn(t)

    monkeypatch.setattr(_cv_mod, "_is_monotonic_array", _wrapped)
    return counter


def _build_default_axis_canvas(qapp):
    """Build a canvas with one plotted channel on a default monotonic time axis.

    Mirrors the production wiring: plot_channels populates
    `_channel_data_id` and `_channel_lines`, and (after F-1 fix) also
    `_channel_is_monotonic`. We do not exercise xlim_changed here —
    we drive `_refresh_visible_data` directly so the test stays
    deterministic without a Qt event loop.
    """
    cv = TimeDomainCanvas()
    cv.resize(1200, 600)
    n = 30_000
    t = np.linspace(0.0, 10.0, n)
    sig = np.sin(2 * np.pi * 3.0 * t)
    ch_list = [
        ("ch_default", True, t, sig, "#1769e0", "g", "fidA"),
    ]
    cv.plot_channels(ch_list, mode='overlay')
    return cv, t, sig


def test_envelope_does_not_rescan_monotonicity_for_default_time_axis(
        qapp, monkeypatch):
    """Repeated viewport refreshes must NOT re-run np.diff(t) per call.

    F-1: today _envelope calls the uncached _is_monotonic_array on every
    invocation. After the fix, plot_channels caches monotonicity per
    channel, _envelope_cached / _envelope reads the cached boolean, and
    repeated _refresh_visible_data calls touch the scan AT MOST ONCE
    (the initial build inside plot_channels).
    """
    cv, t, sig = _build_default_axis_canvas(qapp)

    counter = _patch_monotonic_counter(monkeypatch)

    # Several distinct xlim windows — each forces an envelope cache miss
    # so _envelope runs. With the F-1 fix, the cached monotonicity flag
    # short-circuits the in-_envelope scan.
    primary_ax = cv._primary_xaxis_ax
    for x0, x1 in [(0.0, 1.0), (1.0, 5.0), (2.5, 7.5), (3.0, 9.0), (4.0, 6.0)]:
        primary_ax.set_xlim(x0, x1)
        cv._refresh_visible_data()

    # Strict assertion: the wrapped uncached helper must not be called
    # from the refresh path at all (the cached flag is consulted instead).
    # We allow up to 1 invocation in case the implementation chooses to
    # populate _channel_is_monotonic via _is_monotonic_array directly.
    assert counter["n"] <= 1, (
        f"_is_monotonic_array was called {counter['n']} times across 5 "
        f"viewport refreshes; the cache is not being consumed on the hot path"
    )


def test_invalidate_monotonicity_cache_forces_recompute(qapp, monkeypatch):
    """After invalidate_monotonicity_cache(), the next refresh re-derives.

    F-1: a no-arg invalidation clears the per-channel monotonicity dict
    too, so the following _envelope_cached call must call the uncached
    helper exactly once to repopulate.
    """
    cv, t, sig = _build_default_axis_canvas(qapp)

    counter = _patch_monotonic_counter(monkeypatch)

    primary_ax = cv._primary_xaxis_ax
    # Prime the (now-cached) flag with one refresh.
    primary_ax.set_xlim(0.0, 5.0)
    cv._refresh_visible_data()
    n_after_prime = counter["n"]

    # Full-clear invalidation must wipe the per-channel monotonicity flag.
    cv.invalidate_monotonicity_cache()

    primary_ax.set_xlim(1.0, 4.0)
    cv._refresh_visible_data()
    n_after_recompute = counter["n"]

    assert n_after_recompute == n_after_prime + 1, (
        f"expected exactly one re-scan after invalidation; saw "
        f"{n_after_recompute - n_after_prime} (prime={n_after_prime}, "
        f"recompute={n_after_recompute})"
    )


def test_envelope_uses_cache_per_custom_xaxis_key(qapp, monkeypatch):
    """Per-channel monotonicity flag is reused across many refreshes.

    F-1: with a custom-x source channel (monotonic by construction here),
    the refresh path scans np.diff(t) AT MOST ONCE across many viewport
    changes. A targeted invalidation (custom_xaxis_fid='fidB') re-arms
    the per-channel flag and the next refresh re-scans exactly once.
    """
    cv = TimeDomainCanvas()
    cv.resize(1200, 600)
    n = 25_000
    # Custom-x style: monotonic but not the default time grid.
    t = np.linspace(0.0, 100.0, n) + 1e-3 * np.linspace(0.0, 1.0, n)
    sig = np.cos(2 * np.pi * 2.0 * np.linspace(0.0, 1.0, n))
    ch_list = [
        ("[B] custom_x_ch", True, t, sig, "#dc2626", "rpm", "fidB"),
    ]
    cv.plot_channels(ch_list, mode='overlay')

    counter = _patch_monotonic_counter(monkeypatch)

    primary_ax = cv._primary_xaxis_ax
    for x0, x1 in [(10.0, 50.0), (20.0, 60.0), (30.0, 70.0), (40.0, 80.0)]:
        primary_ax.set_xlim(x0, x1)
        cv._refresh_visible_data()

    # No re-scan within the first burst: the per-channel flag was cached
    # by plot_channels.
    assert counter["n"] == 0, (
        f"_is_monotonic_array was called {counter['n']} times during "
        f"refreshes against a single channel"
    )

    # Targeted invalidation by fid (matches main_window's site-2a contract
    # at file close). After this, the per-channel flag must be cleared so
    # the next refresh re-derives.
    cv.invalidate_monotonicity_cache(custom_xaxis_fid="fidB")

    primary_ax.set_xlim(15.0, 55.0)
    cv._refresh_visible_data()
    assert counter["n"] == 1, (
        f"expected exactly one rescan after fid-targeted invalidation; "
        f"saw {counter['n']}"
    )


# -----------------------------------------------------------------
# Backwards-compatible _ds
# -----------------------------------------------------------------


def test_ds_without_kwargs_keeps_legacy_behaviour(qapp):
    cv = _make_canvas(qapp)
    n = 30_000
    t = np.linspace(0.0, 1.0, n)
    sig = np.sin(2 * np.pi * 5 * t)
    # Legacy: bucketed full-series min/max reduction. The legacy bucket
    # arithmetic does not guarantee a strict MAX_PTS upper bound (it
    # rounds the bucket size down) — we just require substantial
    # downsampling vs. the input.
    td, sd = cv._ds(t, sig)
    assert len(td) > 0
    assert len(td) < n  # downsampled
    assert len(td) <= 2 * cv.MAX_PTS  # at most 2 indices per bucket


def test_ds_with_xlim_delegates_to_envelope(qapp):
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=200_000, spike_idx=123_457, spike_amp=12.0)
    td, sd = cv._ds(t, sig, xlim=(t[0], t[-1]), pixel_width=1200)
    # Envelope path: spike must survive in full view.
    assert np.isclose(np.max(sd), 12.0, atol=1e-9)


# -----------------------------------------------------------------
# Statistics invariance — CRITICAL invariant
# -----------------------------------------------------------------


def test_statistics_unchanged_when_envelope_is_used(qapp, monkeypatch):
    """Statistics must use the real selected data, not the envelope output."""
    cv = _make_canvas(qapp)
    t, sig = _spike_signal(n=50_000, spike_idx=12_345, spike_amp=5.0)
    # Plug data into the canvas as plot_channels would, but bypass plotting
    # so this test stays focused on numeric invariance.
    cv.channel_data["ch_a"] = (t, sig, "#000000", "")

    # Stats over the full series (no time_range) computed from the original.
    stats_full = cv.get_statistics(time_range=None)["ch_a"]

    # Force envelope to be used between calls — this should NOT change stats.
    _ = cv._envelope(t, sig, xlim=(t[0], t[-1]), pixel_width=1200)
    stats_again = cv.get_statistics(time_range=None)["ch_a"]

    for k in ("min", "max", "mean", "rms", "std", "p2p"):
        assert stats_full[k] == stats_again[k], (
            f"statistic {k!r} drifted after envelope was used"
        )

    # Sanity: stats must reflect ORIGINAL extrema, not envelope-clipped values.
    assert np.isclose(stats_full["max"], np.max(sig))
    assert np.isclose(stats_full["min"], np.min(sig))
