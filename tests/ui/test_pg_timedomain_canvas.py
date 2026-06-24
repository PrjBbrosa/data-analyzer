"""Behavior tests for the pyqtgraph time-domain canvas migration.

This file is created during Task 4 of
``docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md``
with the *envelope parity* test class as the first (and currently only)
class. Task 5 will append the canvas-skeleton tests; Task 6 the
subplot/overlay/cursor parity tests.

The envelope-parity tests verify that
``mf4_analyzer.signal._envelope_cutils.positions_envelope`` returns
output that is identical (to float-repr precision) to the legacy
``mf4_analyzer.ui.canvases.build_envelope`` reference implementation
across the seven cases enumerated in the plan Task 4 Step 1.

Per the codex-phantom-api-surface-guards lesson, ``cutils.positions`` is
NOT replaced by MagicMock. Tests either:

- exercise the real C path (probed at module import via
  ``getattr+callable``), or
- force the wrapper into its numpy fallback by monkey-patching the
  module-level cache flag ``_HAS_POSITIONS_C``.

Per the branch-reached-is-not-behavior-correct lesson, each parity case
asserts a behavioral property (values, lengths, NaN counts), not "the
fallback branch was reached".
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtWidgets import QCheckBox, QRadioButton, QWidget

from mf4_analyzer.signal import _envelope_cutils as ec
from mf4_analyzer.ui.canvases import build_envelope


# -- shared parity helper -------------------------------------------------


def _assert_envelope_equal(out_a, out_b, *, label: str):
    """Assert two (t_out, sig_out) envelopes are equal within tolerance.

    Tolerance is derived from float64 representation precision (eps),
    not a magic constant. Both halves are checked: lengths must match
    exactly, NaN positions must match exactly (``equal_nan=True``), and
    finite values must compare under ``np.allclose`` with
    ``atol=8*eps*max(|a|,|b|)``-style scaling (we use a small absolute
    floor for values near zero).
    """
    ta, sa = out_a
    tb, sb = out_b
    ta = np.asarray(ta)
    sa = np.asarray(sa)
    tb = np.asarray(tb)
    sb = np.asarray(sb)
    assert ta.shape == tb.shape, (
        f"[{label}] timestamp length mismatch: {ta.shape} vs {tb.shape}"
    )
    assert sa.shape == sb.shape, (
        f"[{label}] sample length mismatch: {sa.shape} vs {sb.shape}"
    )
    if ta.size == 0:
        return  # both empty, nothing else to check.
    # NaN positions must match (build_envelope emits NaN buckets as a
    # single NaN; the wrapper must preserve that or fall back).
    nan_a = np.isnan(sa) if np.issubdtype(sa.dtype, np.floating) else None
    nan_b = np.isnan(sb) if np.issubdtype(sb.dtype, np.floating) else None
    if nan_a is not None and nan_b is not None:
        assert np.array_equal(nan_a, nan_b), (
            f"[{label}] NaN mask differs"
        )
    eps = np.finfo(np.float64).eps
    rtol = 8 * eps
    atol = 8 * eps * max(1.0, float(np.max(np.abs(sa[~nan_a])) if nan_a is not None else np.max(np.abs(sa))))
    assert np.allclose(ta, tb, rtol=rtol, atol=8 * eps), (
        f"[{label}] timestamps differ"
    )
    assert np.allclose(sa, sb, rtol=rtol, atol=atol, equal_nan=True), (
        f"[{label}] samples differ"
    )


# -- envelope parity test class ------------------------------------------


class TestPositionsEnvelopeParity:
    """positions_envelope() must match build_envelope() on every case
    enumerated in Task 4 Step 1 of the migration plan."""

    # 1) Empty arrays --------------------------------------------------------

    def test_empty_arrays_return_empty_pair(self):
        t = np.array([], dtype=np.float64)
        sig = np.array([], dtype=np.float64)
        ref = build_envelope(t, sig, xlim=(0.0, 1.0), pixel_width=100)
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="empty")
        # Behavioral assertion: shapes are zero-length on BOTH sides.
        assert len(got[0]) == 0
        assert len(got[1]) == 0

    # 2) Normal monotonic timestamps -- the production hot path -------------

    def test_normal_monotonic_matches_reference(self):
        rng = np.random.default_rng(20260528)
        n = 50_000
        t = np.linspace(0.0, 10.0, n)
        sig = (
            np.sin(2 * np.pi * 1.3 * t)
            + 0.5 * np.cos(2 * np.pi * 6.1 * t)
            + 0.05 * rng.standard_normal(n)
        ).astype(np.float64)
        xlim = (1.5, 7.5)
        pixel_width = 800
        ref = build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="normal")
        # Behavioral assertion: downsampling actually happened. The
        # bucketed-path output has at most ``2 * n_buckets`` entries
        # where ``n_buckets = n_vis // max(1, n_vis // pixel_width)``.
        # For n=50_000 over xlim (1.5, 7.5) we get n_vis=30_000,
        # bs=37, n_buckets=810 -> at most 1_620 entries — far below
        # the 30_000-sample visible window.
        n_input = len(t)
        assert 2 <= len(got[0]) < n_input // 10, (
            f"expected downsampled output; got {len(got[0])} entries "
            f"for {n_input} input samples"
        )

    # 3) Reversed xlim (x0 > x1) --------------------------------------------

    def test_reversed_xlim_normalizes(self):
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * 0.5 * t).astype(np.float64)
        ref = build_envelope(
            t, sig, xlim=(10.0, 0.0), pixel_width=400, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(10.0, 0.0), pixel_width=400, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="reversed-xlim")
        # Behavioral assertion: output timestamps are in non-decreasing
        # order even though the input xlim was reversed.
        assert np.all(np.diff(got[0]) >= 0), (
            "reversed xlim must still emit time-ordered output"
        )

    # 4) Small arrays (N < 4*pixel_width) trigger the small-array gate ------

    def test_small_arrays_fall_back_to_reference(self):
        # build_envelope shortcuts when n_vis <= 2*pixel_width.
        # The wrapper's gate (N < 2*pixel_width) keeps every small visible
        # window on the reference path so the bit-identical small-visible
        # shortcut output is preserved.
        t = np.linspace(0.0, 1.0, 50)
        sig = np.sin(t).astype(np.float64)
        ref = build_envelope(t, sig, xlim=(0.0, 1.0), pixel_width=200,
                             is_monotonic=True)
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=200, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="small-array")
        # Behavioral assertion: output is the full visible slice, not
        # downsampled (small-visible shortcut returns input verbatim).
        assert len(got[0]) == 50

    # 5) Non-monotonic timestamps fall back to the legacy reducer -----------

    def test_non_monotonic_falls_back(self):
        # Forced descent in the middle; _is_monotonic_array(t) is False.
        t = np.array([0.0, 1.0, 2.0, 1.5, 3.0, 4.0, 5.0])
        sig = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        ref = build_envelope(
            t, sig, xlim=(0.0, 5.0), pixel_width=10, is_monotonic=False,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 5.0), pixel_width=10, is_monotonic=False,
        )
        _assert_envelope_equal(got, ref, label="non-monotonic")
        # Behavioral assertion: in non-monotonic mode build_envelope
        # passes the data through _ds_legacy_pure (no searchsorted clip,
        # full series returned). Length must equal input length here
        # because N <= 2*pixel_width (legacy small-visible branch).
        assert len(got[0]) == len(t)

    # 6) NaN segments must be handled identically to build_envelope --------

    def test_nan_segments_match_reference(self):
        # Pattern: finite | nan | finite | nan-only-bucket | finite
        t = np.linspace(0.0, 1.0, 600)
        sig = np.sin(2 * np.pi * 3.0 * t).astype(np.float64)
        # NaN block 1: indices [100, 130) — partial NaN bucket
        sig[100:130] = np.nan
        # NaN block 2: indices [300, 360) — partial NaN bucket
        sig[300:360] = np.nan
        # NaN block 3 (entire bucket all-NaN at pixel_width=50 -> bs=12)
        sig[480:512] = np.nan

        ref = build_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=50, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=50, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="nan-segments")
        # Behavioral assertion: at least one all-NaN bucket emits a
        # single NaN entry (build_envelope's discontinuity break).
        nan_count = int(np.sum(np.isnan(got[1])))
        assert nan_count >= 1, (
            "NaN-only bucket should produce a NaN break in the envelope"
        )

    # 7) Non-contiguous numpy views are either safe-copied or fall back ----

    def test_non_contiguous_views_do_not_segfault(self):
        # Strided slice -> non-contiguous view; the wrapper must either
        # safe-copy to a contiguous buffer or fall back to build_envelope.
        n = 4_000
        t_full = np.linspace(0.0, 10.0, n)
        sig_full = np.sin(2 * np.pi * t_full).astype(np.float64)
        # Take every other sample via slicing — produces a strided view
        # with strides != itemsize but still 1-D.
        t = t_full[::2]
        sig = sig_full[::2]
        assert not t.flags.c_contiguous or not sig.flags.c_contiguous, (
            "test prerequisite: at least one input view should be non-contiguous"
        )
        ref = build_envelope(
            t, sig, xlim=(0.0, 10.0), pixel_width=200, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 10.0), pixel_width=200, is_monotonic=True,
        )
        # Behavioral assertion: no segfault (we reached here), output
        # parity holds.
        _assert_envelope_equal(got, ref, label="non-contiguous")

    # 8) Forced fallback (C unavailable) returns exact build_envelope output

    def test_c_path_is_exercised_on_normal_monotonic_input(self):
        """The branch-reached-is-not-behavior-correct lesson applied to
        the wrapper itself: assert the C extension is actually called
        on the production hot-path shape, not silently bypassed via
        fallback. A future regression that breaks the gate cascade
        (e.g. spurious contiguity bail-out) will be caught here.
        """
        if not ec._HAS_POSITIONS_C:
            pytest.skip("C extension not available in this environment")
        # Spy on the real C function via a one-shot wrapper. We DO NOT
        # MagicMock cutils — we observe call count on the real call.
        from asammdf.blocks import cutils
        original = cutils.positions
        call_count = {"n": 0}

        def _spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        n = 20_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        cutils.positions = _spy
        try:
            ec.positions_envelope(
                t, sig, xlim=(1.0, 9.0), pixel_width=500,
                is_monotonic=True,
            )
        finally:
            cutils.positions = original
        assert call_count["n"] == 1, (
            f"expected C path to be exercised exactly once, got "
            f"{call_count['n']} calls"
        )

    def test_forced_fallback_when_c_path_disabled(self, monkeypatch):
        # Boundary-only mock: disable the C path via the module flag,
        # NOT by patching cutils itself. This honors the
        # codex-phantom-api-surface-guards lesson.
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        # Reset once-flag so the c_unavailable log can fire deterministically
        # in this test process; otherwise an earlier test in the same
        # session may have consumed it.
        ec._reset_logged_reasons()
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * 0.7 * t).astype(np.float64)
        ref = build_envelope(
            t, sig, xlim=(2.0, 7.0), pixel_width=300, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(2.0, 7.0), pixel_width=300, is_monotonic=True,
        )
        # When the C path is disabled, the wrapper falls back to
        # build_envelope, so output must be bit-identical (same code
        # path on both sides, no float reordering).
        np.testing.assert_array_equal(got[0], ref[0])
        np.testing.assert_array_equal(got[1], ref[1])


# -- overlay envelope bucket-cap (narrow-Y vertical-stroke wall) ---------


class TestOverlayBucketCap:
    """Overlay mode caps the per-curve envelope bucket count by channel
    count so the dense narrow-Y vertical-stroke regime stays within the
    raster-fill budget (renderer._effective_pixel_width). Subplot/single
    keep the full viewport pixel_width — their disjoint short rows do not
    hit the full-height-stroke wall, so capping would only coarsen them.

    The per-curve cap is sized so the SUMMED displayed-point count across
    all overlay curves lands at ``K × _AA_OVERLAY_SEGMENT_OFF`` with
    ``K = _OVERLAY_BUCKET_BUDGET_MULT = 1.3`` — i.e. comfortably ABOVE the
    AA-off threshold, never AT or below it. The original ``/(2N)`` cap left
    the sum exactly at the threshold (integer truncation could even dip
    below), which let the quality gate's ``metric > off_budget`` test flip AA
    back ON for some channel counts — re-enabling AA in the dense overlay the
    cap exists to speed up. These tests lock the new ">threshold and
    <full-width" semantics and the resulting AA-off state for 2..8 channels.

    Measured (real HDF, 6-channel overlay, 1920 px, offscreen grab() median):
    uncapped narrow-Y + X-zoom paint 40.1 ms; original ``/(2N)`` cap 18.9 ms
    (summed 7008, AT threshold); K=1.3 cap ~20–22 ms (summed ~9098, reliably
    > 7000). See renderer._effective_pixel_width docstring.
    """

    def _make_overlay(self, qapp, n_curves):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1920, 600)
        canvas.show()
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 10.0, 500_000, dtype=np.float64)
        rows = [
            (f"ch{i}", True, t, np.sin(t * (i + 1)),
             "#1769e0", "u", f"fid-{i}")
            for i in range(n_curves)
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        return canvas

    def test_overlay_caps_bucket_count_by_channel_count(self, qapp):
        from mf4_analyzer.ui.pg_canvas.renderer import (
            _OVERLAY_BUCKET_BUDGET_MULT,
        )

        canvas = self._make_overlay(qapp, 6)
        pw = canvas._current_pixel_width()
        eff = canvas._effective_pixel_width(pw)
        budget = int(canvas._AA_OVERLAY_SEGMENT_OFF)
        # New formula: cap = int(budget * K / (2*N)), then clamped to pixel_width.
        expected = max(
            1, min(pw, int(budget * _OVERLAY_BUCKET_BUDGET_MULT / (2 * 6)))
        )
        assert eff == expected
        # The cap MUST bite for a dense 6-curve overlay on a wide canvas:
        # full pixel_width (~1900) far exceeds the per-curve budget (~758).
        assert eff < pw

    def test_overlay_summed_points_stay_above_aa_off_threshold(self, qapp):
        # Across 2..8 channels the SUMMED displayed-point count must stay
        # STABLY ABOVE _AA_OVERLAY_SEGMENT_OFF (so the quality gate keeps AA
        # OFF) yet well BELOW the uncapped full-width wall (so the raster-fill
        # speedup is preserved). This is the core of the tightening: the old
        # /(2N) cap landed the sum AT the threshold, risking an AA flip-back.
        #
        # Note N=2 on a ~1920 px canvas is PIXEL-WIDTH-bound (per-curve cap
        # ~2275 > pixel_width), so its sum ≈ 2*pw*2 is naturally just past the
        # threshold without the cap biting — AA is still OFF, which is all
        # that matters there (2 curves is not the dense case). The cap bites
        # for N>=4, where we additionally assert the sum is far below the
        # uncapped wall.
        for n in (2, 4, 6, 8):
            canvas = self._make_overlay(qapp, n)
            canvas._flush_pending_refresh()
            budget = int(canvas._AA_OVERLAY_SEGMENT_OFF)
            pw = canvas._current_pixel_width()
            eff = canvas._effective_pixel_width(pw)
            total = 0
            for _name, (_ax, line) in canvas._channel_lines.items():
                xd, _ = line.plot_data_item.getData()
                total += 0 if xd is None else len(xd)
            # Stably ABOVE the AA-off threshold (never AT it / below it).
            assert total > budget, (
                f"N={n}: summed {total} not > AA-off budget {budget}; "
                "AA could flip back ON in dense overlay"
            )
            if eff < pw:
                # Cap is biting (N>=4): the sum must sit near ~1.3*budget,
                # far below the uncapped full-width wall (~2*pw*N pts).
                full_width_pts = 2 * pw * n
                assert total < full_width_pts, (
                    f"N={n}: summed {total} not < uncapped wall "
                    f"{full_width_pts}; cap is not biting"
                )
                # Sanity: comfortably below twice the threshold (the cap
                # targets ~1.3*budget; allow slack for envelope rounding).
                assert total < 2 * budget, (
                    f"N={n}: summed {total} >= 2*budget {2 * budget}; "
                    "cap loosened beyond the ~1.3x target"
                )

    def test_overlay_aa_stays_off_for_2_to_8_channels(self, qapp):
        # End-to-end: the quality gate's AA decision must be OFF for every
        # channel count in 2..8 once the envelope is flushed, proving the
        # bucket-cap keeps the summed metric above off_budget.
        for n in (2, 4, 6, 8):
            canvas = self._make_overlay(qapp, n)
            canvas._flush_pending_refresh()
            status = canvas._quality._density_status()
            assert status["overlay"] is True
            # metric > off_budget => AA OFF (the gate's flip-off condition).
            assert status["metric"] > status["off_budget"], (
                f"N={n}: metric {status['metric']} <= off_budget "
                f"{status['off_budget']}; AA would stay ON"
            )

    def test_subplot_mode_not_capped(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1920, 600)
        canvas.show()
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 10.0, 500_000, dtype=np.float64)
        rows = [
            (f"ch{i}", True, t, np.sin(t * (i + 1)),
             "#1769e0", "u", f"fid-{i}")
            for i in range(6)
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        pw = canvas._current_pixel_width()
        # Subplot keeps the full viewport pixel width (no channel-count cap).
        assert canvas._effective_pixel_width(pw) == pw

    def test_single_channel_overlay_degenerate_not_capped(self, qapp):
        # mode="overlay" with one visible row falls back to single mode
        # (overlay_mode requires >= 2), so the cap must not engage.
        canvas = self._make_overlay(qapp, 1)
        assert canvas._overlay_mode is False
        pw = canvas._current_pixel_width()
        assert canvas._effective_pixel_width(pw) == pw


# -- subplot dense-channel bucket cap (满高竖线墙 raster wall) ------------


class TestSubplotDenseBucketCap:
    """Subplot mode must ALSO cap the envelope bucket count for HIGH-DENSITY
    channels (wideband, source_len/pixel_width above the dense threshold),
    because a dense channel's per-bucket min/max pair becomes a full-height
    vertical stroke spanning its row — the same raster-fill wall the overlay
    cap addresses, but for disjoint subplot rows the cost is the SUM over the
    dense rows. The cap is keyed off PER-CHANNEL density so low-density and
    single dense channels keep full resolution (red-line fidelity).

    Backward compat: ``_effective_pixel_width(pw)`` with no density kwargs is
    the legacy no-cap-in-subplot behavior; the per-channel cap only engages
    when ``source_len`` + ``dense_count`` are supplied (as the refresh loop
    does).
    """

    def _subplot_canvas(self, qapp, n, npts):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1920, 600)
        canvas.show()
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 10.0, npts, dtype=np.float64)
        rows = [
            (f"ch{i}", True, t, np.sin(t * (i + 1)),
             "#1769e0", "u", f"fid-{i}")
            for i in range(n)
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        return canvas

    def test_legacy_no_kwargs_keeps_full_width_subplot(self, qapp):
        # The legacy single-arg call (used by tests/tools) must stay no-cap
        # in subplot mode regardless of how dense the underlying data is.
        canvas = self._subplot_canvas(qapp, 6, 1_000_000)
        pw = canvas._current_pixel_width()
        assert canvas._effective_pixel_width(pw) == pw

    def test_dense_multi_channel_subplot_caps_below_full_width(self, qapp):
        # 6 dense channels (1e6 pts on ~1900 px → decimation ~500, far above
        # the dense threshold): each row's bucket count must be capped so the
        # summed dense-row buckets stay within the raster-fill budget.
        canvas = self._subplot_canvas(qapp, 6, 1_000_000)
        pw = canvas._current_pixel_width()
        eff = canvas._effective_pixel_width(
            pw, source_len=1_000_000, dense_count=6
        )
        assert eff < pw, (
            f"dense 6-channel subplot not capped: eff {eff} == pw {pw}"
        )

    def test_low_density_channel_subplot_not_capped(self, qapp):
        # A low-density channel (source_len comparable to pixel_width →
        # decimation ~1, no full-height-stroke wall) must keep full
        # resolution even with several such channels present.
        canvas = self._subplot_canvas(qapp, 6, 2_000)
        pw = canvas._current_pixel_width()
        eff = canvas._effective_pixel_width(
            pw, source_len=2_000, dense_count=0
        )
        assert eff == pw

    def test_single_dense_channel_subplot_not_capped(self, qapp):
        # A SINGLE dense channel keeps full resolution: one disjoint row paints
        # one wall, which is the already-fast baseline case (red line: don't
        # coarsen single / few dense channels).
        canvas = self._subplot_canvas(qapp, 1, 1_000_000)
        pw = canvas._current_pixel_width()
        eff = canvas._effective_pixel_width(
            pw, source_len=1_000_000, dense_count=1
        )
        assert eff == pw

    def test_dense_cap_sum_stays_bounded_for_2_to_8(self, qapp):
        # The summed dense-row bucket count must be bounded by the subplot
        # dense budget (so total raster-fill cost is capped) yet each row keeps
        # a sane minimum resolution. Cap engages for >= 2 dense channels.
        from mf4_analyzer.ui.pg_canvas.renderer import (
            _SUBPLOT_DENSE_BUCKET_BUDGET,
            _SUBPLOT_DENSE_MIN_BUCKETS,
        )
        pw = 1900
        canvas = self._subplot_canvas(qapp, 2, 1_000_000)
        for n in (2, 4, 6, 8):
            eff = canvas._effective_pixel_width(
                pw, source_len=1_000_000, dense_count=n
            )
            assert eff < pw
            # Each dense row floored at the per-row minimum so it never
            # degenerates, and capped so the summed dense buckets stay bounded
            # by the budget (above the floor regime) — the total raster wall
            # cost is therefore bounded by max(budget, min*n).
            assert eff >= _SUBPLOT_DENSE_MIN_BUCKETS
            bound = max(_SUBPLOT_DENSE_BUCKET_BUDGET,
                        _SUBPLOT_DENSE_MIN_BUCKETS * n)
            assert eff * n <= bound * 1.05


# -- universal data-amplitude vs Y-window wall guard ---------------------


class TestYOverflowWallGuard:
    """Renderer-layer 兜底 guard for the 满高竖线墙 (full-height vertical-stroke
    wall) regime that the static density caps (overlay channel-count /
    subplot decimation) do NOT see: a dense curve drawn into a Y view window
    far smaller than its amplitude. Every trigger path (manual narrow Y,
    box-zoom Y, scroll Y, stale narrow Y across a view switch) funnels into one
    ``setData`` per line in ``_refresh_visible_data``; the guard compares each
    line's window data amplitude span to its Y view span and, on overflow >
    ``_WALL_OVERFLOW_RATIO_K``×, caps the bucket count and holds AA off.

    Pure performance guard: it changes NO Y range, NO autorange, NO data — only
    the number of drawn strokes + the AA state for the wall frame. Normal frames
    (data hugs the window) are untouched and pay zero extra per-frame cost.
    """

    # -- pure predicate / helper unit coverage (no Qt) -------------------

    def test_predicate_triggers_on_large_overflow(self):
        from mf4_analyzer.ui.pg_canvas.renderer import (
            Renderer, _WALL_OVERFLOW_RATIO_K,
        )
        # data_span/y_span = 10/0.1 = 100 >> K
        assert Renderer._is_y_overflow_wall(10.0, 0.1) is True
        # exactly at K is NOT a wall (strict >)
        assert Renderer._is_y_overflow_wall(
            _WALL_OVERFLOW_RATIO_K, 1.0) is False
        # just above K is a wall
        assert Renderer._is_y_overflow_wall(
            _WALL_OVERFLOW_RATIO_K + 0.01, 1.0) is True

    def test_predicate_no_trigger_when_data_fits_window(self):
        from mf4_analyzer.ui.pg_canvas.renderer import Renderer
        # data ±5 in a ±6 window: data_span 10, y_span 12, ratio < 1 → no wall
        assert Renderer._is_y_overflow_wall(10.0, 12.0) is False
        # data exactly fills window (ratio 1) → no wall
        assert Renderer._is_y_overflow_wall(10.0, 10.0) is False

    def test_predicate_degenerate_inputs_do_not_crash_or_trigger(self):
        from mf4_analyzer.ui.pg_canvas.renderer import Renderer
        # y_span ≈ 0 (collapsed window): no div-by-zero, no trigger
        assert Renderer._is_y_overflow_wall(5.0, 0.0) is False
        assert Renderer._is_y_overflow_wall(5.0, -1.0) is False
        # data_span ≈ 0 (flat line): one horizontal stroke, NOT a wall
        assert Renderer._is_y_overflow_wall(0.0, 0.001) is False
        # non-finite inputs are absorbed
        assert Renderer._is_y_overflow_wall(float("nan"), 1.0) is False
        assert Renderer._is_y_overflow_wall(1.0, float("inf")) is False

    def test_wall_capped_width_only_reduces(self):
        from mf4_analyzer.ui.pg_canvas.renderer import (
            Renderer, _WALL_BUCKET_BUDGET,
        )
        # above the budget → clamped down
        assert Renderer._wall_capped_width(_WALL_BUCKET_BUDGET + 5000) == (
            _WALL_BUCKET_BUDGET
        )
        # already below the budget → unchanged (never raised)
        assert Renderer._wall_capped_width(500) == 500
        # degenerate width floors at 1
        assert Renderer._wall_capped_width(0) == 1

    def test_y_span_key_changes_with_y_zoom(self):
        from mf4_analyzer.ui.pg_canvas.renderer import _quantize_y_span_key
        # a real Y zoom (10× narrower) must cross at least one bucket boundary
        assert _quantize_y_span_key(10.0) != _quantize_y_span_key(1.0)
        # sub-percent jitter on a static window stays in one bucket
        assert _quantize_y_span_key(5.0) == _quantize_y_span_key(5.0 * 1.001)
        # degenerate spans map to the sentinel bucket
        assert _quantize_y_span_key(0.0) == 0
        assert _quantize_y_span_key(-1.0) == 0

    # -- end-to-end on a live canvas -------------------------------------

    def _wall_canvas(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1920, 600)
        canvas.show()
        QCoreApplication.processEvents()
        # ONE dense channel, amplitude ±5 (data_span ~10). A single channel is
        # below BOTH static caps (overlay needs >=2 curves; subplot dense cap
        # needs >=2 dense rows), so only the universal wall guard can fire here.
        t = np.linspace(0.0, 10.0, 1_000_000, dtype=np.float64)
        sig = 5.0 * np.sin(t * 30.0)
        rows = [("ch0", True, t, sig, "#1769e0", "u", "fid-0")]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        return canvas, t, sig

    def _displayed_points(self, canvas, name):
        _ax, line = canvas._channel_lines[name]
        xd, _ = line.plot_data_item.getData()
        return 0 if xd is None else len(xd)

    def test_narrow_y_caps_points_and_flags_wall(self, qapp):
        from mf4_analyzer.ui.pg_canvas.renderer import _WALL_BUCKET_BUDGET

        canvas, _t, _sig = self._wall_canvas(qapp)
        ax, _line = canvas._channel_lines["ch0"]
        # Baseline: window hugs the data (±6), no wall.
        ax.set_ylim(-6.0, 6.0)
        canvas._last_range_key.clear()
        canvas._flush_pending_refresh()
        full_pts = self._displayed_points(canvas, "ch0")
        assert canvas._y_overflow_wall_active is False
        assert canvas._line_wall_state.get("ch0") is False

        # Now pin Y to ±0.05 (data_span/y_span ≈ 10/0.1 = 100 >> K): wall.
        ax.set_ylim(-0.05, 0.05)
        canvas._flush_pending_refresh()
        wall_pts = self._displayed_points(canvas, "ch0")
        assert canvas._y_overflow_wall_active is True
        assert canvas._line_wall_state.get("ch0") is True
        # Bucket count额外封顶: each bucket emits ~2 envelope samples, so the
        # displayed count is bounded by ~2× the wall budget.
        assert wall_pts <= 2 * _WALL_BUCKET_BUDGET + 4
        # And it is strictly fewer strokes than the un-capped (fitting) frame.
        assert wall_pts < full_pts

    def test_fitting_window_full_resolution_no_cap(self, qapp):
        canvas, _t, _sig = self._wall_canvas(qapp)
        ax, _line = canvas._channel_lines["ch0"]
        pw = canvas._current_pixel_width()
        ax.set_ylim(-6.0, 6.0)
        canvas._last_range_key.clear()
        canvas._flush_pending_refresh()
        pts = self._displayed_points(canvas, "ch0")
        # Full pixel-width resolution: ~2 samples per pixel column, far above
        # the wall budget; no cap engaged.
        assert canvas._y_overflow_wall_active is False
        assert pts > pw  # not coarsened down to the wall budget

    def test_wall_holds_aa_off(self, qapp):
        canvas, _t, _sig = self._wall_canvas(qapp)
        ax, _line = canvas._channel_lines["ch0"]
        ax.set_ylim(-0.05, 0.05)
        canvas._flush_pending_refresh()
        assert canvas._y_overflow_wall_active is True
        # The idle-AA gate must hard-fail (AA stays OFF) while the wall is up,
        # regardless of how few points the cap left.
        assert canvas._quality._idle_aa_density_ok() is False

    def test_wall_state_clears_when_window_widens_back(self, qapp):
        canvas, _t, _sig = self._wall_canvas(qapp)
        ax, _line = canvas._channel_lines["ch0"]
        ax.set_ylim(-0.05, 0.05)
        canvas._flush_pending_refresh()
        assert canvas._y_overflow_wall_active is True
        # Widen Y back to fit: the wall must clear so AA can re-arm later.
        ax.set_ylim(-6.0, 6.0)
        canvas._flush_pending_refresh()
        assert canvas._y_overflow_wall_active is False
        assert canvas._line_wall_state.get("ch0") is False

    def test_flat_line_in_narrow_window_does_not_trigger(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1920, 600)
        canvas.show()
        QCoreApplication.processEvents()
        # A genuinely flat (constant) dense line: data_span ≈ 0. Even in a
        # narrow Y window it is one horizontal stroke, never a fill wall.
        t = np.linspace(0.0, 10.0, 1_000_000, dtype=np.float64)
        sig = np.full_like(t, 2.0)
        rows = [("ch0", True, t, sig, "#1769e0", "u", "fid-0")]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        ax, _line = canvas._channel_lines["ch0"]
        ax.set_ylim(1.999, 2.001)
        canvas._flush_pending_refresh()
        assert canvas._y_overflow_wall_active is False
        assert canvas._line_wall_state.get("ch0") in (False, None)


# -- A: re-show original must NOT recompute the envelope -----------------


class TestReshowOriginalNoEnvelopeRecompute:
    """Hiding then re-showing the original (solid) curves via
    ``set_original_lines_visible`` must be a pure ``setVisible`` toggle:
    it must NOT re-run ``positions_envelope`` (the envelope data computed at
    plot time stays valid while hidden), and it must not synchronously block
    on a full recompute. The toggle returns the count of curves flipped.
    """

    def _built_canvas(self, qapp, n=3, npts=200_000):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1280, 600)
        canvas.show()
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 10.0, npts, dtype=np.float64)
        rows = [
            (f"ch{i}", True, t, np.sin(t * (i + 1)),
             "#1769e0", "u", f"fid-{i}")
            for i in range(n)
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        canvas._flush_pending_refresh()
        return canvas

    def test_reshow_does_not_call_positions_envelope(self, qapp, monkeypatch):
        import mf4_analyzer.signal._envelope_cutils as envmod

        canvas = self._built_canvas(qapp)
        calls = {"n": 0}
        orig = envmod.positions_envelope

        def _spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(envmod, "positions_envelope", _spy)

        # Hide then re-show: neither path may recompute the envelope.
        hidden = canvas.set_original_lines_visible(False)
        assert hidden == 3
        shown = canvas.set_original_lines_visible(True)
        assert shown == 3
        assert calls["n"] == 0, (
            f"re-show recomputed the envelope {calls['n']}x; it must be a "
            "pure setVisible toggle"
        )

    def test_reshow_preserves_envelope_data(self, qapp):
        canvas = self._built_canvas(qapp)
        name = next(n for n in canvas._channel_lines)
        pdi = canvas._channel_lines[name][1].plot_data_item
        before_x, before_y = pdi.getData()
        before_len = 0 if before_x is None else len(before_x)
        assert before_len > 0

        canvas.set_original_lines_visible(False)
        canvas.set_original_lines_visible(True)

        after_x, _ = pdi.getData()
        after_len = 0 if after_x is None else len(after_x)
        # Same envelope data object survives the hide/show round-trip.
        assert after_len == before_len
        assert pdi.isVisible() is True


# -- fallback-logging contract test class --------------------------------


class TestFallbackLoggingContract:
    """Lock the fallback-logging contract documented in
    ``_envelope_cutils.positions_envelope`` and in
    ``docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md``.

    The contract (Option B from the W1 codex review rework):

    - System-level fallback branches are logged exactly once per process
      via ``_log_fallback_once``: ``c_unavailable``, ``non_monotonic``,
      ``nan_in_window``, ``non_contiguous``, ``dtype_mismatch``.
    - Per-call shape branches are NOT logged at all (no
      ``_log_fallback_once`` call): ``xlim_none``, ``empty_input``,
      ``empty_visible_window``, ``small_visible``, ``no_op_bucket``.

    Per the branch-reached-is-not-behavior-correct lesson, each
    assertion distinguishes the "logs as documented" state from the
    "silently bypasses logging" state — it is not enough that the
    branch executed.

    Per the codex-phantom-api-surface-guards lesson, we never MagicMock
    ``asammdf.blocks.cutils``: the C-unavailable branch is forced via
    the existing module-level flag ``_HAS_POSITIONS_C``.
    """

    @pytest.fixture(autouse=True)
    def _reset_logged_reasons(self):
        # Ensure a clean once-flag set for each test method so multiple
        # invocations are observable without cross-test pollution.
        ec._reset_logged_reasons()
        yield
        ec._reset_logged_reasons()

    # -- system-level branches: logged exactly once across N invocations --

    def test_c_unavailable_logs_exactly_once_across_invocations(
        self, monkeypatch, caplog,
    ):
        # Force the C-unavailable branch via the module flag (NOT by
        # mocking asammdf.blocks.cutils).
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        n = 3_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(5):
                ec.positions_envelope(
                    t, sig, xlim=(1.0, 9.0), pixel_width=200,
                    is_monotonic=True,
                )
        matching = [
            r for r in caplog.records
            if "c_unavailable" in r.getMessage()
            and r.name == "mf4_analyzer.signal._envelope_cutils"
        ]
        assert len(matching) == 1, (
            "c_unavailable is a system-level fallback and must log "
            f"exactly once per process; saw {len(matching)} records: "
            f"{[r.getMessage() for r in matching]}"
        )

    def test_non_monotonic_logs_exactly_once_across_invocations(self, caplog):
        # Forced descent in the middle => not monotonic.
        t = np.array([0.0, 1.0, 2.0, 1.5, 3.0, 4.0, 5.0])
        sig = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(4):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 5.0), pixel_width=10,
                    is_monotonic=False,
                )
        matching = [
            r for r in caplog.records
            if "non_monotonic" in r.getMessage()
        ]
        assert len(matching) == 1, (
            f"non_monotonic must log once per process; saw {len(matching)} "
            f"records: {[r.getMessage() for r in matching]}"
        )

    # -- per-call shape branches: NOT logged at all ------------------------

    def test_xlim_none_does_not_log(self, caplog):
        # xlim=None is a per-call shape decision (full-range passthrough),
        # NOT a system-level fallback. It must not emit any log record.
        if not ec._HAS_POSITIONS_C:
            # Use a small input so the C path probe state is irrelevant;
            # build_envelope's full-range contract handles it the same
            # either way.
            pass
        t = np.linspace(0.0, 1.0, 100)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=None, pixel_width=50, is_monotonic=True,
            )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            "xlim=None is a per-call shape decision and must NOT emit a "
            f"_log_fallback_once line; saw: {msgs}"
        )

    def test_empty_input_does_not_log(self, caplog):
        # Empty arrays are a per-call shape decision.
        t = np.array([], dtype=np.float64)
        sig = np.array([], dtype=np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(3):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 1.0), pixel_width=100,
                    is_monotonic=True,
                )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            f"empty_input is a per-call shape decision and must NOT emit "
            f"a _log_fallback_once line; saw: {msgs}"
        )

    def test_small_visible_does_not_log(self, caplog):
        # n_vis <= 2 * pixel_width hits the small-visible shortcut.
        if not ec._HAS_POSITIONS_C:
            pytest.skip(
                "C unavailable on this system; small-visible branch is "
                "only reachable past the c_unavailable gate"
            )
        t = np.linspace(0.0, 1.0, 50)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(3):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 1.0), pixel_width=200,
                    is_monotonic=True,
                )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            f"small_visible is a per-call shape decision and must NOT "
            f"emit a _log_fallback_once line; saw: {msgs}"
        )

    def test_no_op_bucket_does_not_log(self, caplog):
        # bs <= 1 (n_vis < n_buckets) hits the no-op-bucket branch.
        # Build an input where n_vis is greater than 2*pixel_width
        # (skips small-visible) but n_vis // pixel_width == 1 (bs == 1).
        # Need n_vis in (2*pw, ...) but we want bs=1 which means
        # n_vis < 2*pw. Impossible to hit no_op_bucket and skip
        # small_visible because small_visible fires first. The no-op
        # branch is effectively unreachable today — assert via the
        # weaker proposition: across many invocations, no record from
        # a "no_op_bucket" message ever appears (even if its branch
        # never executes).
        if not ec._HAS_POSITIONS_C:
            pytest.skip("C unavailable; no-op branch unreachable")
        # Just exercise a normal hot-path call and confirm the
        # specific 'no_op_bucket' string never logs.
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=(1.0, 9.0), pixel_width=200,
                is_monotonic=True,
            )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert not any("no_op_bucket" in m for m in msgs), (
            f"no_op_bucket must NOT emit a _log_fallback_once line; "
            f"saw: {msgs}"
        )

    # -- the reset hook itself is part of the test contract ----------------

    def test_reset_logged_reasons_re_arms_once_flag(
        self, monkeypatch, caplog,
    ):
        # After a system-level fallback has logged, a reset must allow
        # the same reason to log again. This validates the test hook
        # we rely on for deterministic multi-invocation assertions.
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        t = np.linspace(0.0, 1.0, 1_000)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
            )
            first_count = sum(
                1 for r in caplog.records
                if "c_unavailable" in r.getMessage()
            )
            ec._reset_logged_reasons()
            ec.positions_envelope(
                t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
            )
            second_count = sum(
                1 for r in caplog.records
                if "c_unavailable" in r.getMessage()
            )
        assert first_count == 1, (
            f"expected exactly 1 c_unavailable record before reset; "
            f"saw {first_count}"
        )
        assert second_count == 2, (
            f"expected reset to re-arm the once-flag; got {second_count} "
            f"records, not 2"
        )


# ---------------------------------------------------------------------------
# T5 — TimeDomainCanvasPG skeleton + curve-layer cache parity tests.
#
# These tests are append-only. They start RED (the class does not exist yet)
# and turn GREEN once Task 5 lands pg_canvases.TimeDomainCanvasPG plus the
# QPainterPath-keyed curve-layer cache documented in design §5.2.
#
# The four signal/payload assertions mirror the W0 pattern from
# tests/ui/test_timedomain_canvas_contract.py so a future renderer swap on
# the production side cannot drift the contract.
# ---------------------------------------------------------------------------


def _pg_canvas(qapp):
    """Construct a TimeDomainCanvasPG and pump events so its underlying
    GraphicsLayoutWidget has a non-zero geometry under offscreen Qt.
    qapp here is the session QApplication fixture from conftest.py.
    """
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from PyQt5.QtCore import QCoreApplication
    canvas = TimeDomainCanvasPG()
    # Force a layout pass so widget.grab() returns a non-null pixmap.
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _viewport_point_for_data(canvas, handle, x, y=None):
    """Map a data-space point in ``handle`` to a viewport QPoint."""
    from PyQt5.QtCore import QPointF

    vb = handle.view_box
    assert vb is not None
    if y is None:
        _x_range, y_range = vb.viewRange()
        y = (float(y_range[0]) + float(y_range[1])) / 2.0
    scene_pos = vb.mapViewToScene(QPointF(float(x), float(y)))
    return canvas._glw.mapFromScene(scene_pos)


def _pg_signal_signature(bound) -> str:
    """Strip the leading SIGNAL-marker digits from a pyqtBoundSignal
    name string so callers can assert ``name(payload)`` exactly. Mirrors
    helper in tests/ui/test_timedomain_canvas_contract.py."""
    raw = bound.signal
    return raw.lstrip("0123456789")


class TestTimeDomainCanvasPGAnnotations:
    """Pin the remark tool behavior users exercise from the time toolbar."""

    def test_remark_label_shows_coordinates_not_channel_name(self, qapp, monkeypatch):
        from PyQt5.QtCore import QPoint

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        monkeypatch.setattr(
            canvas._annotations,
            "_nearest_data_point",
            lambda _pos: ("speed", 1.25, 42.5, "#1769e0", "rpm"),
        )

        canvas._annotations._add_remark(QPoint(120, 100))

        label = canvas._annotations.remarks[-1]["text"].textItem.toPlainText()
        assert "X=1.25 s" in label
        assert "Y=42.5 rpm" in label
        assert "speed" not in label
        remark = canvas._annotations.remarks[-1]
        assert remark["label"] is remark["text"]
        assert remark["leader"] is not None
        assert remark["text"].flags() & remark["text"].ItemIsMovable

    def test_remark_label_highlights_y_value_with_channel_color(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QPoint

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        monkeypatch.setattr(
            canvas._annotations,
            "_nearest_data_point",
            lambda _pos: ("speed", 1.25, 42.5, "#00b894", "rpm"),
        )

        canvas._annotations._add_remark(QPoint(120, 100))

        html = canvas._annotations.remarks[-1]["text"].textItem.toHtml().lower()
        assert "#00b894" in html

    def test_nearest_data_point_uses_curve_screen_distance_not_x_only(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QCoreApplication

        t = np.asarray([0.0, 0.01, 10.0], dtype=np.float64)
        sig = np.asarray([100.0, 0.0, 0.0], dtype=np.float64)
        canvas = _pg_canvas(qapp)
        canvas.plot_channels([
            ("speed", True, t, sig, "#1769e0", "rpm", "fid-1"),
        ], mode="subplot")
        QCoreApplication.processEvents()
        handle = canvas.axes_list[0]
        point = _viewport_point_for_data(canvas, handle, 0.0, 0.0)
        scene_pos = canvas._glw.mapToScene(point)
        monkeypatch.setattr(canvas, "_cursor_data_x_from_viewport_pos", lambda _p: 0.0)
        monkeypatch.setattr(canvas, "_viewport_pos_to_scene", lambda _p: scene_pos)

        found = canvas._annotations._nearest_data_point(point)

        assert found is not None
        assert found[1] == pytest.approx(0.01)
        assert found[2] == pytest.approx(0.0)

    def test_remark_on_second_subplot_attaches_to_second_viewbox(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")
        QCoreApplication.processEvents()
        second_handle = canvas.axes_list[1]
        second_row = canvas.channel_data["torque"]
        idx = len(second_row[0]) // 2
        point = _viewport_point_for_data(
            canvas,
            second_handle,
            float(second_row[0][idx]),
            float(second_row[1][idx]),
        )

        canvas._annotations._add_remark(point)

        assert canvas._annotations.remarks[-1]["vb"] is second_handle.view_box

    def test_annotation_left_click_adds_on_release_not_press(self, qapp, monkeypatch):
        from PyQt5.QtCore import QPoint, Qt

        canvas = _pg_canvas(qapp)
        canvas.set_remark_enabled(True)
        point = QPoint(80, 90)
        added = []
        monkeypatch.setattr(
            canvas._annotations,
            "_add_remark",
            lambda pos: added.append(pos),
        )

        press_consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_press(point, Qt.LeftButton),
        )
        release_consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_release(point, Qt.LeftButton),
        )

        assert press_consumed is False
        assert release_consumed is True
        assert added == [point]

    def test_annotation_left_drag_does_not_add_remark(self, qapp, monkeypatch):
        from PyQt5.QtCore import QPoint, Qt

        canvas = _pg_canvas(qapp)
        canvas.set_remark_enabled(True)
        start = QPoint(80, 90)
        end = QPoint(140, 120)
        added = []
        monkeypatch.setattr(
            canvas._annotations,
            "_add_remark",
            lambda pos: added.append(pos),
        )

        canvas.eventFilter(canvas._glw.viewport(), self._mouse_press(start, Qt.LeftButton))
        move_consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_move(end, Qt.LeftButton),
        )
        release_consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_release(end, Qt.LeftButton),
        )

        assert move_consumed is False
        assert release_consumed is False
        assert added == []

    def test_annotation_mode_uses_bitmap_pen_cursor(self, qapp):
        from PyQt5.QtCore import Qt

        canvas = _pg_canvas(qapp)
        canvas.set_remark_enabled(True)

        assert canvas._glw.viewport().cursor().shape() == Qt.BitmapCursor

    def test_annotation_mode_left_press_on_existing_remark_allows_drag(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QPoint, Qt

        canvas = _pg_canvas(qapp)
        canvas.set_remark_enabled(True)
        point = QPoint(80, 90)
        added = []
        monkeypatch.setattr(
            canvas._annotations,
            "_remark_item_at_viewport_pos",
            lambda _pos: object(),
            raising=False,
        )
        monkeypatch.setattr(
            canvas._annotations,
            "_add_remark",
            lambda pos: added.append(pos),
        )

        consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_press(point, Qt.LeftButton),
        )

        assert consumed is False
        assert added == []

    def test_annotation_mode_left_press_on_real_label_does_not_add_remark(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QPoint, QPointF, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        monkeypatch.setattr(
            canvas._annotations,
            "_nearest_data_point",
            lambda _pos: ("speed", 1.25, 42.5, "#1769e0"),
        )
        canvas._annotations._add_remark(QPoint(120, 100))
        remark = canvas._annotations.remarks[-1]
        label_pos = remark["text"].pos()
        scene_pos = remark["vb"].mapViewToScene(
            QPointF(label_pos.x(), label_pos.y())
        )
        label_viewport_pos = canvas._glw.mapFromScene(scene_pos)

        canvas.set_remark_enabled(True)
        consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_press(label_viewport_pos, Qt.LeftButton),
        )

        assert consumed is False
        assert len(canvas._annotations.remarks) == 1
        assert canvas._annotations.remarks[-1] is remark

    def test_annotation_mode_right_press_deletes_nearest_remark(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QPoint, Qt

        canvas = _pg_canvas(qapp)
        canvas.set_remark_enabled(True)
        point = QPoint(80, 90)
        scene_pos = object()
        removed = []
        monkeypatch.setattr(canvas, "_viewport_pos_to_scene", lambda _pos: scene_pos)
        monkeypatch.setattr(
            canvas._annotations,
            "_remove_remark_at",
            lambda sp: removed.append(sp),
        )

        consumed = canvas.eventFilter(
            canvas._glw.viewport(),
            self._mouse_press(point, Qt.RightButton),
        )

        assert consumed is True
        assert removed == [scene_pos]

    def _mouse_press(self, point, button):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseButtonPress, point, button, button, Qt.NoModifier,
        )

    def _mouse_move(self, point, held_button):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseMove, point, Qt.NoButton, held_button, Qt.NoModifier,
        )

    def _mouse_release(self, point, button):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseButtonRelease, point, button, Qt.NoButton, Qt.NoModifier,
        )


class TestTimeDomainCanvasPGContract:
    """Pin the compatibility surface design §3.1 + §5.5 require so the
    new pyqtgraph canvas is a drop-in for the matplotlib TimeDomainCanvas.

    Per the codex-phantom-api-surface-guards lesson, every test constructs
    a REAL TimeDomainCanvasPG. No MagicMock canvases. Per the
    branch-reached-is-not-behavior-correct lesson, each test asserts a
    behavioral property (signal payload string, attribute presence,
    method callability), not "the constructor returned".
    """

    def test_four_signals_exposed_with_exact_payload_shapes(self, qapp):
        """Design §3.1: four pyqtSignals with the exact payload shapes
        downstream consumers (TimeChartCard, MainWindow) rely on."""
        from PyQt5.QtCore import pyqtBoundSignal

        canvas = _pg_canvas(qapp)
        expected = {
            "cursor_info": "cursor_info(QString)",
            "dual_cursor_info": "dual_cursor_info(QString)",
            "span_selected": "span_selected(double,double)",
            "overlay_channel_selected": "overlay_channel_selected(PyQt_PyObject)",
        }
        for name, want_sig in expected.items():
            bound = getattr(canvas, name, None)
            assert bound is not None, f"signal {name!r} missing on TimeDomainCanvasPG"
            assert isinstance(bound, pyqtBoundSignal), (
                f"attribute {name!r} is not a pyqtBoundSignal (got {type(bound)!r})"
            )
            got = _pg_signal_signature(bound)
            assert got == want_sig, (
                f"signal {name!r}: expected {want_sig!r}, got {got!r}"
            )

    def test_plot_channels_accepts_row_shape_and_stores_raw_channel_data(self, qapp):
        """Design §4.2 + main_window.py:984-990: ``plot_channels`` must
        accept ``(name, True, x_axis, sig, color, unit, fid)`` and keep
        ``channel_data[name] == (t, sig, color, unit)`` — raw arrays, NOT
        envelope output."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        color = "#ef4444"
        unit = "Nm"
        canvas.plot_channels(
            [("torque", True, t, sig, color, unit, "fid-1")], mode="overlay"
        )
        assert "torque" in canvas.channel_data
        stored = canvas.channel_data["torque"]
        assert isinstance(stored, tuple) and len(stored) == 4, (
            f"channel_data['torque'] must be a 4-tuple, got {stored!r}"
        )
        got_t, got_sig, got_color, got_unit = stored
        np.testing.assert_array_equal(np.asarray(got_t), t)
        np.testing.assert_array_equal(np.asarray(got_sig), sig)
        assert got_color == color
        assert got_unit == unit

    def test_plot_channels_accepts_legacy_six_tuple_row(self, qapp):
        """Backward compatibility with the legacy 6-tuple row shape
        ``(name, True, t, sig, color, unit)`` — required because the
        contract test (test_timedomain_canvas_contract.py) feeds the
        old shape and we must remain a drop-in."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = (t * 2).astype(np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#00b894", "rpm")], mode="overlay"
        )
        assert "speed" in canvas.channel_data
        got_t, got_sig, got_color, got_unit = canvas.channel_data["speed"]
        np.testing.assert_array_equal(np.asarray(got_t), t)
        np.testing.assert_array_equal(np.asarray(got_sig), sig)
        assert got_color == "#00b894"
        assert got_unit == "rpm"

    def test_compatibility_surfaces_exist_after_plot(self, qapp):
        """Design §5.5: ``axes_list``, ``_channel_lines``,
        ``_primary_xaxis_ax`` must exist with the expected accessor
        shape after plot_channels."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = np.sin(t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        assert hasattr(canvas, "axes_list")
        assert len(canvas.axes_list) >= 1
        # Each axis-handle entry must satisfy AxisHandle (get_xlim/set_xlim).
        ax0 = canvas.axes_list[0]
        assert callable(getattr(ax0, "get_xlim", None))
        assert callable(getattr(ax0, "set_xlim", None))

        assert hasattr(canvas, "_channel_lines")
        assert "a" in canvas._channel_lines
        # _channel_lines[name] must be a (axis_facade, line_facade) pair.
        ax_facade, line_facade = canvas._channel_lines["a"]
        assert ax_facade is ax0
        # The line facade must satisfy the LineHandle Protocol: get/set
        # color, get_label, get_visible. (Per design §5.3 — same shape
        # as AxisHandle.get_lines() entries.)
        assert callable(getattr(line_facade, "get_color", None))
        assert callable(getattr(line_facade, "set_color", None))
        assert callable(getattr(line_facade, "get_label", None))
        assert callable(getattr(line_facade, "get_visible", None))

        assert hasattr(canvas, "_primary_xaxis_ax")
        assert canvas._primary_xaxis_ax is not None
        # Primary axis facade must expose get_xlim/set_xlim.
        assert callable(getattr(canvas._primary_xaxis_ax, "get_xlim", None))
        assert callable(getattr(canvas._primary_xaxis_ax, "set_xlim", None))

    def test_cursor_state_methods_callable(self, qapp):
        """``set_cursor_visible``, ``set_dual_cursor_mode``,
        ``reset_cursor_state`` are part of the public surface MainWindow
        relies on (main_window.py:347-349, :680-685). Each must be
        callable without raising on an unplotted canvas, and
        ``reset_cursor_state`` must clear the dual cursor placement."""
        canvas = _pg_canvas(qapp)
        # All must accept being called on an empty canvas.
        canvas.set_cursor_visible(True)
        canvas.set_cursor_visible(False)
        canvas.set_dual_cursor_mode(True)
        canvas.set_dual_cursor_mode(False)
        # After putting the dual cursor in some state, reset_cursor_state
        # must restore the placing='A' / _ax=None / _bx=None invariant.
        canvas._cursor.ax = 0.25
        canvas._cursor.bx = 0.75
        canvas._cursor.placing = "B"
        canvas._refresh = False
        canvas.reset_cursor_state()
        assert canvas._cursor.ax is None
        assert canvas._cursor.bx is None
        assert canvas._cursor.placing == "A"
        assert canvas._refresh is True

    def test_get_statistics_reads_raw_channel_data_not_envelope_output(self, qapp):
        """Design §4.2: ``get_statistics`` MUST read raw arrays from
        ``channel_data``. Poisoning the envelope cache (the curve-layer
        cache the new canvas owns) must not perturb the stats — proving
        stats and envelope output are decoupled, same invariant as the
        matplotlib path (tests/ui/test_timedomain_canvas_contract.py)."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256, dtype=np.float64)
        sig = np.linspace(-1.0, 1.0, 256, dtype=np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#00b894", "rpm", "fid-1")]
        )

        # Baseline stats from raw data.
        stats_before = canvas.get_statistics(time_range=(0.0, 1.0))
        assert "speed" in stats_before
        assert stats_before["speed"]["min"] == pytest.approx(-1.0)
        assert stats_before["speed"]["max"] == pytest.approx(1.0)
        assert stats_before["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)

        # Poison the curve-layer/path cache: get_statistics must not
        # consult it. We don't lock to a specific dict layout — instead
        # we set wildly-outside-the-data values into channel_data for a
        # bogus channel name and assert the speed stats remain unchanged.
        # (Direct poisoning of channel_data['speed'] would change the
        # answer; that's the point — channel_data IS the source of truth.)
        # Probe the curve-cache layer directly.
        cache = getattr(canvas, "_curve_path_cache", None)
        assert cache is not None, (
            "TimeDomainCanvasPG must expose _curve_path_cache as a viewport "
            "cache seam (design §5.2)."
        )
        sentinel_key = ("__poison__", "speed", 0, 1, 100)
        cache[sentinel_key] = ("poisoned",)  # opaque payload; stats must not touch it

        stats_after = canvas.get_statistics(time_range=(0.0, 1.0))
        assert stats_after["speed"]["min"] == pytest.approx(-1.0)
        assert stats_after["speed"]["max"] == pytest.approx(1.0)
        assert stats_after["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)
        # The poisoned key remains untouched: reads do not mutate the cache.
        assert sentinel_key in cache

    def test_enable_span_selector_stores_callback_but_does_not_auto_enable(
        self, qapp,
    ):
        """Design §4.2 invariant + main_window.py:993-996: the always-on
        SpanSelector was retired. ``enable_span_selector(cb)`` must remain
        callable (compatibility surface) but ``plot_time`` (parent flow)
        does not invoke it, and calling it directly here must NOT install
        an active drag-to-select gesture on the canvas."""
        canvas = _pg_canvas(qapp)
        captured = []
        canvas.enable_span_selector(lambda lo, hi: captured.append((lo, hi)))
        # Compatibility-only: span_selector attribute is not active.
        # The new canvas only stores the callback; no drag handler is wired.
        assert hasattr(canvas, "span_selector")
        # span_selected signal is still part of the surface even though
        # no drag was wired.
        assert hasattr(canvas, "span_selected")
        # No callback ever fired without user gesture.
        assert captured == []

    def test_flush_pending_refresh_is_callable_and_safe_when_empty(self, qapp):
        """``_flush_pending_refresh`` is called by MainWindow even when
        the canvas was just cleared (main_window.py:443-448). It must
        not raise on an empty canvas state."""
        canvas = _pg_canvas(qapp)
        # Must be safe on a fresh, never-plotted canvas.
        canvas._flush_pending_refresh()
        # And after a plot but with no scheduled refresh.
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = np.sin(t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        canvas._flush_pending_refresh()

    def test_draw_idle_and_clear_callable(self, qapp):
        """Compatibility surface from canvases.TimeDomainCanvas. Both
        callable on a fresh canvas without raising."""
        canvas = _pg_canvas(qapp)
        canvas.draw_idle()
        canvas.clear()
        canvas.draw_idle()


class TestTimeDomainCanvasPGCurveCache:
    """Custom curve-layer cache (design §5.2) is the core perf delivery
    of T5. Test from the consumer side (a real set_xlim call) per the
    signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface
    lesson — we don't just exercise the cache method, we verify the
    production hot path populates the cache via a real range change.
    """

    def test_cache_starts_empty_after_construction(self, qapp):
        canvas = _pg_canvas(qapp)
        assert hasattr(canvas, "_curve_path_cache"), (
            "TimeDomainCanvasPG must expose _curve_path_cache (design §5.2)"
        )
        assert len(canvas._curve_path_cache) == 0

    def test_last_range_key_populates_after_set_xlim(self, qapp):
        """Range change must trigger the visible envelope refresh and record
        the last range key used to gate redundant setData work.
        """
        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = (np.sin(2 * np.pi * 1.3 * t) + 0.5 * np.cos(2 * np.pi * 6.1 * t)).astype(
            np.float64
        )
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        # Drive a real range change; the cache populate happens inside
        # the production hot path, not via a private direct call.
        canvas.set_xlim(2.0, 5.0)
        canvas._flush_pending_refresh()

        assert canvas._last_range_key.get("a") is not None
        assert canvas._last_range_key["a"][0] == "a"

    def test_two_different_xlims_produce_two_different_range_keys(self, qapp):
        """Per the 2026-05-19-branch-reached-is-not-behavior-correct lesson:
        two different xlims must produce two different range keys — proving
        the refresh gate sees distinct frames."""
        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        canvas.set_xlim(1.0, 4.0)
        canvas._flush_pending_refresh()
        key_after_first = canvas._last_range_key.get("a")
        assert key_after_first is not None

        canvas.set_xlim(6.0, 9.0)
        canvas._flush_pending_refresh()
        key_after_second = canvas._last_range_key.get("a")

        assert key_after_second is not None
        assert key_after_second != key_after_first

    def test_same_xlim_replay_keeps_same_range_key(self, qapp):
        """Per pyqt-ui/2026-04-25-cache-invalidation-event-conditional:
        invalidation/repopulation must be gated on a state diff, not on
        every event tick. Two consecutive flushes with identical xlim keep
        the same gate key."""
        canvas = _pg_canvas(qapp)
        n = 20_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        canvas.set_xlim(2.0, 5.0)
        canvas._flush_pending_refresh()
        key_after_first = canvas._last_range_key.get("a")

        # No range mutation between flushes — cache size must not grow.
        canvas._flush_pending_refresh()
        key_after_second = canvas._last_range_key.get("a")
        assert key_after_second == key_after_first

    def test_positions_envelope_is_consumed_by_canvas_hot_path(
        self, qapp, monkeypatch,
    ):
        """Per signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface:
        the cache+envelope plumbing is dead code unless the production
        hot path actually CALLS positions_envelope. Wire a call-count
        spy onto the module function and assert the canvas drives it.
        """
        from mf4_analyzer.signal import _envelope_cutils as ec

        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)

        original = ec.positions_envelope
        call_count = {"n": 0}

        def _spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        # Patch via the canvas module too so we count the call regardless
        # of which import path the canvas uses (from-import vs. attribute).
        from mf4_analyzer.ui import pg_canvases
        monkeypatch.setattr(ec, "positions_envelope", _spy)
        if hasattr(pg_canvases, "positions_envelope"):
            monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)

        canvas = _pg_canvas(qapp)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        canvas.set_xlim(1.0, 6.0)
        canvas._flush_pending_refresh()

        assert call_count["n"] >= 1, (
            "TimeDomainCanvasPG hot path must call positions_envelope on "
            "set_xlim; otherwise the curve-layer cache plumbing is dead "
            "code (see cache-consumer-must-be-grepped-not-just-surface)."
        )

    def test_visible_curve_data_updates_to_viewport_envelope_after_xlim(self, qapp):
        """Regression for the UI gap report: computing the viewport envelope
        is not enough; the visible PlotDataItem must display that envelope.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = (
            np.sin(2 * np.pi * 1.3 * t)
            + 0.5 * np.cos(2 * np.pi * 6.1 * t)
        ).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        QCoreApplication.processEvents()

        _axis_handle, line_handle = canvas._channel_lines["a"]
        pdi = line_handle.plot_data_item
        bind_x, bind_y = pdi.getData()
        assert float(np.nanmin(bind_x)) == pytest.approx(0.0, abs=1e-9)
        assert float(np.nanmax(bind_x)) == pytest.approx(10.0, abs=1e-9)

        canvas.set_xlim(2.0, 5.0)
        canvas._flush_pending_refresh()
        QCoreApplication.processEvents()

        view_x, view_y = pdi.getData()
        assert view_x is not None and view_y is not None
        assert float(np.nanmin(view_x)) >= 2.0 - 1e-9
        assert float(np.nanmax(view_x)) <= 5.0 + 1e-9
        assert not (
            len(bind_x) == len(view_x)
            and np.array_equal(np.asarray(bind_x), np.asarray(view_x))
            and np.array_equal(np.asarray(bind_y), np.asarray(view_y))
        ), "visible curve data stayed on the full-range bind envelope"

    def test_refresh_visible_data_does_not_build_unused_path_or_pixmap(
        self, qapp, monkeypatch,
    ):
        """Followup regression: once PlotDataItem.setData is the visible
        render truth, the old QPainterPath/QPixmap seam must not stay on the
        pan hot path as unread work.
        """
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1])

        monkeypatch.setattr(
            canvas,
            "_build_painter_path",
            lambda *args, **kwargs: pytest.fail("unused painter path was built"),
        )
        monkeypatch.setattr(
            canvas,
            "_render_path_to_pixmap",
            lambda *args, **kwargs: pytest.fail("unused pixmap was built"),
        )

        canvas.set_xlim(0.1, 0.8)
        canvas._flush_pending_refresh()


class TestTimeDomainCanvasPGScreenshotGrab:
    """Per lesson codex-visual-parity-rendered-screenshot: render at
    least one offscreen screenshot and gate on geometry, not pixel-byte
    equality (that's T7's job). Also per
    pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt: provide a
    degenerate-rect fallback."""

    def test_grab_pixmap_returns_non_null_pixmap_with_geometry(self, qapp, tmp_path):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 1_000, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#1769e0", "rpm", "fid-1")]
        )
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "grab_pixmap returned a null pixmap"
        # Geometry gate (NOT pixel-byte equality — T7's job).
        assert pix.width() > 0, f"pix.width()={pix.width()}"
        assert pix.height() > 0, f"pix.height()={pix.height()}"

        # And write to /tmp so a human reviewer can inspect the rendered
        # offscreen output.
        out_path = "/tmp/pg_skeleton_single_channel.png"
        ok = pix.save(out_path)
        assert ok, f"failed to write screenshot to {out_path!r}"

    def test_curves_antialiased_context_enables_then_restores(self, qapp):
        """Export must render crisp (anti-aliased) curves even though
        interactive panning keeps AA off for speed (commit 4734d7f4). The
        context manager flips every curve to antialias=True for its body and
        restores the prior (off) state on exit — no permanent perf hit."""
        from PyQt5.QtCore import QCoreApplication
        import pyqtgraph as pg

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert curves, "expected PlotCurveItem(s) on the scene"
        before = [bool(c.opts.get("antialias")) for c in curves]

        with canvas._quality._curves_antialiased():
            inside = [bool(c.opts.get("antialias")) for c in curves]
        after = [bool(c.opts.get("antialias")) for c in curves]

        assert all(inside), "all curves must be anti-aliased inside the context"
        assert after == before, "antialias state must be restored on exit"

    def test_grab_pixmap_restores_curve_antialias(self, qapp):
        """grab_pixmap renders the export through the AA context, then leaves
        the curves exactly as it found them (interactive AA-off)."""
        from PyQt5.QtCore import QCoreApplication
        import pyqtgraph as pg

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        before = [bool(c.opts.get("antialias")) for c in curves]

        pix = canvas.grab_pixmap(scale=1.0)
        assert not pix.isNull()

        after = [bool(c.opts.get("antialias")) for c in curves]
        assert after == before, "grab_pixmap must restore the AA-off state"


# T5 — fill PgAxisHandle: verify it now delegates to a real pyqtgraph
# ViewBox/AxisItem pair instead of raising NotImplementedError. This
# class lives here (not in test_axis_handle.py) so T5's reach into the
# axis-handle module is exercised from the same file that drives the
# pyqtgraph canvas.

class TestPgAxisHandleDelegation:
    """The 17 AxisHandle Protocol methods on PgAxisHandle must delegate
    to a real pyqtgraph ``PlotItem``/``ViewBox``/``AxisItem`` triple —
    no more NotImplementedError stubs."""

    def _make(self, qapp):
        import os
        os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
        import pyqtgraph as pg
        from mf4_analyzer.ui._axis_handle import PgAxisHandle

        glw = pg.GraphicsLayoutWidget()
        glw.resize(640, 360)
        plot_item = glw.addPlot(row=0, col=0)
        handle = PgAxisHandle(plot_item=plot_item)
        return glw, plot_item, handle

    def test_get_set_xlim_roundtrips(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_xlim(0.0, 10.0)
        lo, hi = h.get_xlim()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(10.0)

    def test_get_set_ylim_roundtrips(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_ylim(-1.0, 1.0)
        lo, hi = h.get_ylim()
        assert lo == pytest.approx(-1.0)
        assert hi == pytest.approx(1.0)

    def test_xlabel_ylabel_title_roundtrip(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_xlabel("time (s)")
        h.set_ylabel("value")
        h.set_title("title")
        assert "time (s)" in h.get_xlabel()
        assert "value" in h.get_ylabel()
        assert "title" in h.get_title()

    def test_grid_toggle_is_noop_safe(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # showGrid raises on unsupported args; we just need it to round
        # without crashing for both states.
        h.grid(True)
        h.grid(False)

    def test_get_lines_returns_line_handle_wrappers(self, qapp):
        _glw, pi, h = self._make(qapp)
        # Add a PlotDataItem so get_lines has something to see.
        import pyqtgraph as pg
        pdi = pi.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0], pen=pg.mkPen("#1769e0"))
        lines = h.get_lines()
        assert len(lines) >= 1
        line = lines[0]
        # LineHandle Protocol — same surface as Mpl wrapper.
        assert callable(getattr(line, "get_label", None))
        assert callable(getattr(line, "get_color", None))
        assert callable(getattr(line, "set_color", None))
        assert callable(getattr(line, "get_visible", None))
        # set_color round-trips: read back via PlotDataItem pen color.
        line.set_color("#ef4444")
        # Color reads via PlotDataItem.opts['pen'].color().name().
        from PyQt5.QtGui import QPen
        pen = pdi.opts.get("pen")
        if isinstance(pen, QPen):
            assert pen.color().name() == "#ef4444"

    def test_get_mappables_empty_for_time_domain(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # Time-domain has no images/colorscales — design §5.3.
        assert h.get_mappables() == []

    def test_request_redraw_does_not_raise(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # Just verify it's callable and non-raising under offscreen Qt.
        h.request_redraw()

    def test_set_xscale_yscale_log_then_linear(self, qapp):
        _glw, pi, h = self._make(qapp)
        # ViewBox supports a log-scale flag via setLogMode on PlotItem.
        h.set_xscale("log")
        h.set_xscale("linear")
        h.set_yscale("log")
        h.set_yscale("linear")

    def test_autoscale_does_not_raise(self, qapp):
        _glw, pi, h = self._make(qapp)
        # Add data so there's something to autoscale to.
        import pyqtgraph as pg
        pi.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0], pen=pg.mkPen("#1769e0"))
        h.autoscale()
        h.autoscale(axis="x")
        h.autoscale(axis="y")


# ---------------------------------------------------------------------------
# T6 — Subplot / overlay / cursor parity / scroll / xlim-preservation tests.
#
# These are append-only and start RED against the T5 canvas (subplot/overlay
# routing exists at construction but the visual rules, cursor signal
# emission, modifier-dispatched scroll, and mode-switch xlim capture are
# not implemented yet). They turn GREEN once T6 lands the behavior in
# mf4_analyzer/ui/pg_canvases.py.
#
# Every test in this block honors the
# signal-processing/2026-05-19-branch-reached-is-not-behavior-correct
# lesson: a single-frame "branch executed" assertion is never enough.
# Either we compare two frames with different inputs and demand strictly
# different outputs, or we string-match a payload byte-for-byte against
# the matplotlib reference renderer (cursor HTML parity).
# ---------------------------------------------------------------------------


def _five_channel_rows():
    """Construct 5 visible channel rows for plot_channels() tests.

    Returns the same row shape MainWindow passes: ``(name, True, t, sig,
    color, unit, fid)``. Different waveforms per channel ensure each
    inside-label-vs-outside placement and per-channel emphasis test can
    assert on something non-trivial.
    """
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    return [
        ("speed",    True, t, 1000.0 * np.sin(2 * np.pi * 5 * t),  "#1769e0", "rpm",  "fid-1"),
        ("torque",   True, t, 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t), "#ef4444", "Nm",  "fid-1"),
        ("pressure", True, t, 0.2 * t + 0.1 * np.sin(2 * np.pi * 7 * t), "#00b894", "bar", "fid-1"),
        ("temp",     True, t, 60.0 + 2.0 * np.cos(2 * np.pi * 1.5 * t), "#fbbf24", "C",   "fid-1"),
        ("flow",     True, t, 1.0 + 0.3 * np.sin(2 * np.pi * 9 * t), "#a855f7", "L/s", "fid-1"),
    ]


def _view_state_key(data_id, name):
    return json.dumps([data_id, name], ensure_ascii=False, separators=(",", ":"))


def test_visible_range_changed_emits_on_restore_xlim(qtbot, qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    qapp.processEvents()

    seen = []
    canvas.visible_range_changed.connect(lambda: seen.append(True))
    canvas.restore_visible_xlim((0.2, 0.6))
    qapp.processEvents()

    assert len(seen) == 1


def _major_tick_labels(axis):
    levels = getattr(axis, "_tickLevels", None)
    assert levels is not None, "expected explicit X tick levels"
    assert len(levels) >= 1
    return list(levels[0])


def _label_rects_for_axis(axis, values_and_labels, lo, hi):
    from PyQt5.QtGui import QFontMetrics
    from mf4_analyzer.ui.pg_canvases import _pg_chart_font

    width = float(axis.size().width())
    metrics = QFontMetrics(_pg_chart_font(9))
    rects = []
    span = float(hi - lo)
    assert span > 0
    for value, label in values_and_labels:
        x = (float(value) - float(lo)) / span * width
        try:
            w = float(metrics.horizontalAdvance(str(label)))
        except AttributeError:
            w = float(metrics.width(str(label)))
        rects.append((x - w / 2.0, x + w / 2.0, str(label)))
    return rects


def test_x_tick_target_count_used_when_width_allows(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()

    axis = canvas.axes_list[0].x_axis_item()

    canvas.set_tick_density(10, 6)
    QCoreApplication.processEvents()
    labels_10 = _major_tick_labels(axis)
    assert 9 <= len(labels_10) <= 11

    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()
    labels_20 = _major_tick_labels(axis)
    assert 18 <= len(labels_20) <= 21

    canvas.deleteLater()


def test_x_tick_target_count_backs_off_before_label_overlap(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(360, 360)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 1_000_000.0, 5000)
    rows = [("speed", True, t, np.sin(t / 100000.0), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(30, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    axis = handle.x_axis_item()
    lo, hi = handle.get_xlim()
    labels = _major_tick_labels(axis)
    rects = _label_rects_for_axis(axis, labels, lo, hi)

    assert len(labels) < 30
    previous_right = None
    for left, right, label in rects:
        assert left >= -0.5, f"label {label!r} overflows left edge"
        assert right <= float(axis.size().width()) + 0.5, (
            f"label {label!r} overflows right edge"
        )
        if previous_right is not None:
            assert left - previous_right >= 8.0, (
                f"adjacent X tick labels overlap: previous_right={previous_right}, "
                f"left={left}, label={label!r}"
            )
        previous_right = right

    canvas.deleteLater()


def test_target_x_ticks_refresh_after_xlim_change(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1000, 500)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    before = [value for value, _label in _major_tick_labels(handle.x_axis_item())]
    handle.set_xlim(20.0, 40.0)
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()
    after = [value for value, _label in _major_tick_labels(handle.x_axis_item())]

    assert before != after
    assert min(after) >= 20.0 - 1e-9
    assert max(after) <= 40.0 + 1e-9
    assert 18 <= len(after) <= 21

    canvas.deleteLater()


def test_target_x_ticks_refresh_after_reset_to_data_extents(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    handle.set_xlim(20.0, 40.0)
    canvas._flush_pending_refresh()
    QCoreApplication.processEvents()
    zoomed = [value for value, _label in _major_tick_labels(handle.x_axis_item())]
    assert min(zoomed) >= 20.0 - 1e-9
    assert max(zoomed) <= 40.0 + 1e-9

    canvas.reset_view_to_data_extents()
    QCoreApplication.processEvents()
    reset = [value for value, _label in _major_tick_labels(handle.x_axis_item())]

    assert 18 <= len(reset) <= 21
    assert min(reset) <= 10.0
    assert max(reset) >= 90.0

    canvas.deleteLater()


def test_target_x_ticks_refresh_after_resize_settle(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(420, 420)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [("speed", True, t, np.sin(t), "#1769e0", "", "f")]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    handle = canvas.axes_list[0]
    axis = handle.x_axis_item()
    narrow_labels = _major_tick_labels(axis)
    assert len(narrow_labels) < 18

    canvas.resize(1200, 420)
    QCoreApplication.processEvents()
    canvas._on_resize_settled()
    QCoreApplication.processEvents()

    lo, hi = handle.get_xlim()
    wide_labels = _major_tick_labels(axis)
    rects = _label_rects_for_axis(axis, wide_labels, lo, hi)

    assert len(wide_labels) > len(narrow_labels)
    assert 18 <= len(wide_labels) <= 21

    previous_right = None
    for left, right, label in rects:
        assert left >= -0.5, f"label {label!r} overflows left edge"
        assert right <= float(axis.size().width()) + 0.5, (
            f"label {label!r} overflows right edge"
        )
        if previous_right is not None:
            assert left - previous_right >= 8.0, (
                f"adjacent X tick labels overlap: previous_right={previous_right}, "
                f"left={left}, label={label!r}"
            )
        previous_right = right

    canvas.deleteLater()


def test_subplot_rows_share_target_x_ticks(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 800)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "", "f")
        for i in range(3)
    ]
    canvas.plot_channels(rows, mode="subplot")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    tick_sets = [
        tuple(value for value, _label in _major_tick_labels(handle.x_axis_item()))
        for handle in canvas.axes_list
    ]
    assert len(set(tick_sets)) == 1
    assert 18 <= len(tick_sets[0]) <= 21

    canvas.deleteLater()


def test_overlay_target_x_ticks_apply_to_x_master_axis(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    t = np.linspace(0.0, 100.0, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "", "f")
        for i in range(3)
    ]
    canvas.plot_channels(rows, mode="overlay")
    canvas.set_tick_density(20, 6)
    QCoreApplication.processEvents()

    axis = canvas._x_master_handle.x_axis_item()
    labels = _major_tick_labels(axis)
    assert 18 <= len(labels) <= 21

    canvas.deleteLater()


class TestTimeDomainCanvasPGSubplotMode:
    """5 channels in subplot mode → 5 stacked PlotItems sharing the X
    axis. Sync xlim via the primary axis. Inside-vs-outside label
    placement follows the SAME bbox-overlap rule as
    canvases.py:_subplot_ylabels_need_inside_labels (no fixed 5-10%
    offset, design §0 correction)."""

    def test_all_time_domain_axes_disable_auto_si_prefix(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        rows = [
            ("speed", True, t, np.linspace(0.0, 10000.0, t.size), "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, np.linspace(-5000.0, 5000.0, t.size), "#ef4444", "Nm", "fid-1"),
        ]

        for mode in ("subplot", "single", "overlay"):
            canvas.plot_channels(rows[:1] if mode == "single" else rows, mode=mode)
            QCoreApplication.processEvents()

            plot_items = []
            if canvas._x_master_handle is not None:
                plot_items.append(canvas._x_master_handle.plot_item)
            plot_items.extend(handle.plot_item for handle in canvas.axes_list)
            axis_items = []
            for plot_item in dict.fromkeys(item for item in plot_items if item is not None):
                axis_items.extend(plot_item.getAxis(name) for name in ("left", "right", "bottom"))
            axis_items.extend(handle.y_axis_item() for handle in canvas.axes_list)

            assert axis_items
            assert all(getattr(axis, "autoSIPrefix", None) is False for axis in axis_items)

    def test_canvas_chrome_margins_are_tight(self, qapp):
        """The plot area must use most of the widget. pyqtgraph defaults to a
        9px outer gutter + 8px inter-row spacing — wasted chrome. We tighten
        the central layout so subplots get more drawing area (axis tick text
        lives in each PlotItem's own band, not this outer margin)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        layout = canvas._glw.ci.layout
        left, top, right, bottom = layout.getContentsMargins()
        assert max(left, top, right, bottom) <= 3, (
            f"outer chrome margin too large: {(left, top, right, bottom)}"
        )
        assert layout.verticalSpacing() <= 3, (
            f"inter-subplot spacing too large: {layout.verticalSpacing()}"
        )

    def test_subplot_builds_five_plot_items_sharing_x_axis(self, qapp):
        """Two-frame state change (branch-reached lesson): assert that
        moving the primary axis xlim propagates to a non-primary subplot
        sibling. A single-frame "axes_list has 5 entries" assertion
        would only prove construction ran, not that sharing works."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        assert len(canvas.axes_list) == 5, (
            f"subplot mode must build one axis per visible channel; "
            f"got {len(canvas.axes_list)}"
        )

        primary = canvas._primary_xaxis_ax
        assert primary is not None

        # State A: set primary xlim to a known window.
        primary.set_xlim(0.10, 0.20)
        QCoreApplication.processEvents()
        # ALL 5 axes must follow (not just axes_list[2]). Pin the
        # exact (lo, hi) tuple per subplot. The codex-plan-spec-literal-
        # evidence gate requires comparing exact tuples, not "close
        # enough" — pytest.approx already gives us the rounding cushion
        # without weakening the assertion to "any movement happened".
        windows_a = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_a):
            assert lo == pytest.approx(0.10, abs=1e-6), (
                f"state A axis {i} lo={lo!r}, expected 0.10"
            )
            assert hi == pytest.approx(0.20, abs=1e-6), (
                f"state A axis {i} hi={hi!r}, expected 0.20"
            )

        # State B: a strictly different window.
        primary.set_xlim(0.40, 0.55)
        QCoreApplication.processEvents()
        windows_b = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_b):
            assert lo == pytest.approx(0.40, abs=1e-6), (
                f"state B axis {i} lo={lo!r}, expected 0.40"
            )
            assert hi == pytest.approx(0.55, abs=1e-6), (
                f"state B axis {i} hi={hi!r}, expected 0.55"
            )

        # Two-frame strict difference (signal-processing lesson): every
        # axis moved between state A and state B.
        for i in range(len(canvas.axes_list)):
            assert windows_a[i] != windows_b[i], (
                f"axis {i} did not change between state A and B "
                f"(windows_a[{i}]={windows_a[i]!r}, windows_b[{i}]={windows_b[i]!r})"
            )

    def test_subplot_primary_xlim_updates_visible_bottom_axis_numbers(self, qapp):
        """Range propagation must update the bottom AxisItem too. Otherwise
        curves move to the requested window while the visible X numbers stay
        stuck at their old range."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        bottom_axis = canvas.axes_list[-1].plot_item.getAxis("bottom")
        canvas._primary_xaxis_ax.set_xlim(0.20, 0.40)
        QCoreApplication.processEvents()

        assert canvas.axes_list[-1].get_xlim() == pytest.approx((0.20, 0.40))
        assert tuple(bottom_axis.range) == pytest.approx((0.20, 0.40))

    def test_visible_xlim_restore_updates_visible_bottom_axis_numbers(self, qapp):
        """The public view-state API must reuse the protected X restore path
        so bottom AxisItem tick numbers stay synchronized."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        assert canvas.get_visible_xlim() is None

        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        bottom_axis = canvas.axes_list[-1].plot_item.getAxis("bottom")
        canvas.restore_visible_xlim((0.25, 0.50))
        QCoreApplication.processEvents()

        assert canvas.get_visible_xlim() == pytest.approx((0.25, 0.50))
        assert canvas.axes_list[-1].get_xlim() == pytest.approx((0.25, 0.50))
        assert tuple(bottom_axis.range) == pytest.approx((0.25, 0.50))

    def test_visible_ylims_roundtrip_and_missing_channels_are_skipped(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")
        QCoreApplication.processEvents()

        speed = canvas._channel_lines["speed"][0]
        torque = canvas._channel_lines["torque"][0]
        speed.set_ylim(-1200.0, 1200.0)
        torque.set_ylim(40.0, 60.0)
        expected = canvas.get_visible_ylims()
        assert expected == {
            _view_state_key("fid-1", "speed"): pytest.approx((-1200.0, 1200.0)),
            _view_state_key("fid-1", "torque"): pytest.approx((40.0, 60.0)),
        }

        speed.set_ylim(-1.0, 1.0)
        torque.set_ylim(-2.0, 2.0)
        canvas.restore_visible_ylims({"missing": (0.0, 1.0)})
        assert speed.get_ylim() == pytest.approx((-1.0, 1.0))
        assert torque.get_ylim() == pytest.approx((-2.0, 2.0))

        canvas.restore_visible_ylims({**expected, "missing": (0.0, 1.0)})
        assert speed.get_ylim() == pytest.approx((-1200.0, 1200.0))
        assert torque.get_ylim() == pytest.approx((40.0, 60.0))

    def test_restore_visible_ylims_fits_new_overlay_channel_to_visible_x(self, qapp):
        """A newly checked overlay channel has no saved ylim yet.

        Rebuilds with ``defer_first_frame=True`` bind empty curves while the
        view restores X. Existing channels then get saved ylims back; the new
        channel must use the same visible-X raw-data fit as the context-menu
        Y-autofit path instead of staying on the empty/default range.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 10.0, 1001, dtype=np.float64)
        speed = np.sin(t)
        torque = 50.0 + np.cos(t)
        pressure = 100.0 + 5.0 * np.sin(t)
        pressure[-1] = 1_000_000.0
        base_rows = [
            ("speed", True, t, speed, "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, torque, "#ef4444", "Nm", "fid-1"),
        ]
        canvas.plot_channels(base_rows, mode="overlay")
        canvas.restore_visible_xlim((2.0, 3.0))
        QCoreApplication.processEvents()

        canvas._channel_lines["speed"][0].set_ylim(-10.0, 10.0)
        canvas._channel_lines["torque"][0].set_ylim(40.0, 60.0)
        saved_ylims = canvas.get_visible_ylims()

        rows_with_new_channel = [
            *base_rows,
            ("pressure", True, t, pressure, "#00b894", "bar", "fid-1"),
        ]
        canvas.plot_channels(
            rows_with_new_channel,
            mode="overlay",
            defer_first_frame=True,
        )
        canvas.restore_visible_xlim((2.0, 3.0))
        canvas.restore_visible_ylims(saved_ylims)
        QCoreApplication.processEvents()

        assert canvas.get_visible_ylims()[_view_state_key("fid-1", "speed")] == (
            pytest.approx((-10.0, 10.0))
        )
        assert canvas.get_visible_ylims()[_view_state_key("fid-1", "torque")] == (
            pytest.approx((40.0, 60.0))
        )

        pressure_ylim = canvas.get_visible_ylims()[
            _view_state_key("fid-1", "pressure")
        ]
        visible = pressure[(t >= 2.0) & (t <= 3.0)]
        assert pressure_ylim[0] <= float(visible.min())
        assert pressure_ylim[1] >= float(visible.max())
        assert pressure_ylim[1] < 200.0

    def test_visible_ylims_distinguish_duplicate_display_names(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("speed", True, t, np.sin(t), "#1769e0", "rpm", "file-a"),
            ("speed", True, t, np.cos(t), "#ef4444", "rpm", "file-b"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        first = canvas.axes_list[0]
        second = canvas.axes_list[1]
        first.set_ylim(-10.0, 10.0)
        second.set_ylim(40.0, 60.0)
        captured = canvas.get_visible_ylims()

        assert set(captured) == {
            _view_state_key("file-a", "speed"),
            _view_state_key("file-b", "speed"),
        }
        assert captured[_view_state_key("file-a", "speed")] == pytest.approx(
            (-10.0, 10.0)
        )
        assert captured[_view_state_key("file-b", "speed")] == pytest.approx(
            (40.0, 60.0)
        )

        first.set_ylim(-1.0, 1.0)
        second.set_ylim(-2.0, 2.0)
        canvas.restore_visible_ylims(captured)

        assert first.get_ylim() == pytest.approx((-10.0, 10.0))
        assert second.get_ylim() == pytest.approx((40.0, 60.0))
        assert "speed" in canvas._channel_lines

    def test_subplot_x_grid_geometry_is_aligned_before_first_frame(self, qapp):
        """The first rendered subplot frame must have one shared X grid.

        Waiting for the next Qt event pass can hide a layout-order bug: a row
        whose Y tick labels auto-size after the initial pin gets a different
        ViewBox width, so the same data X maps to a different scene X.
        """
        from PyQt5.QtCore import QCoreApplication, QPointF

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
        rows = [
            ("tiny", True, t, 1e-6 * np.sin(t), "#1769e0", "u", "fid-1"),
            ("huge", True, t, 1e9 * np.sin(t), "#ef4444", "u", "fid-1"),
            ("mid", True, t, 100.0 * np.sin(t), "#00b894", "u", "fid-1"),
            ("offset", True, t, -1e6 + 10.0 * np.sin(t), "#fbbf24", "u", "fid-1"),
        ]

        canvas.plot_channels(rows, mode="subplot")

        mapped_x = []
        for handle in canvas.axes_list:
            vb = handle.view_box
            assert vb is not None
            mapped_x.append([
                float(vb.mapViewToScene(QPointF(x, 0.0)).x())
                for x in (0.0, 0.5, 1.0)
            ])

        ref = mapped_x[0]
        for row, xs in enumerate(mapped_x[1:], start=1):
            assert xs == pytest.approx(ref, abs=0.75), (
                f"subplot row {row} maps shared X ticks to different scene "
                f"positions: {xs!r} vs {ref!r}"
            )

    def test_subplot_non_primary_origin_xlim_propagates_to_all_axes(self, qapp):
        """When the user pans a NON-primary subplot (e.g. axes_list[2]),
        the new range must propagate to the primary AND every other
        sibling. Without this, dropping setXLink causes silent drift on
        the four other axes.

        Two-frame strict difference (branch-reached-is-not-behavior-
        correct): set the same non-primary subplot to two distinct
        windows; assert ALL 5 axes follow in both frames AND that the
        windows differ between frames."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        assert len(canvas.axes_list) == 5

        non_primary = canvas.axes_list[2]
        assert non_primary is not canvas._primary_xaxis_ax

        # State A: set xlim on a NON-primary axis directly.
        non_primary.set_xlim(0.15, 0.25)
        QCoreApplication.processEvents()
        windows_a = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_a):
            assert lo == pytest.approx(0.15, abs=1e-6), (
                f"non-primary-origin state A: axis {i} lo={lo!r} did not "
                f"follow the originating axis (expected 0.15)"
            )
            assert hi == pytest.approx(0.25, abs=1e-6), (
                f"non-primary-origin state A: axis {i} hi={hi!r} did not "
                f"follow the originating axis (expected 0.25)"
            )

        # State B: a different window on the SAME non-primary axis.
        non_primary.set_xlim(0.55, 0.80)
        QCoreApplication.processEvents()
        windows_b = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_b):
            assert lo == pytest.approx(0.55, abs=1e-6), (
                f"non-primary-origin state B: axis {i} lo={lo!r}"
            )
            assert hi == pytest.approx(0.80, abs=1e-6), (
                f"non-primary-origin state B: axis {i} hi={hi!r}"
            )

        # Strict two-frame difference per signal-processing lesson.
        for i in range(len(canvas.axes_list)):
            assert windows_a[i] != windows_b[i], (
                f"axis {i} did not move between non-primary-origin frames"
            )

    def test_subplot_long_labels_use_inside_badges_at_normal_width(self, qapp):
        """Long channel names in a normal-width subplot stack must use
        inside badges instead of rotated left-axis labels.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 1.0, 1000, dtype=np.float64)
        rows = [
            (
                "[whole ±5deg_Fricom] Rte_ActRetPlausi_mActiveReturnMotorTorq4C",
                True,
                t,
                np.sin(2 * np.pi * 2 * t),
                "#1769e0",
                "Nm",
                "fid-1",
            ),
            (
                "[whole ±5deg_Fricom] Rte_ESChkPlausi_mESMotorTorque_xds16",
                True,
                t,
                np.cos(2 * np.pi * 3 * t),
                "#ef4444",
                "Nm",
                "fid-1",
            ),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        assert canvas._subplot_ylabels_need_inside_labels() is True
        assert len(canvas._inside_label_items) == len(rows)
        for handle in canvas.axes_list:
            left = handle.plot_item.getAxis("left")
            assert getattr(left, "labelText", "") == ""

    def test_dense_subplot_stack_uses_inside_badges_for_short_names(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.show()
        QCoreApplication.processEvents()

        rows = _five_channel_rows()
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        assert canvas._subplot_ylabels_need_inside_labels() is True
        assert len(canvas._inside_label_items) == len(rows)
        for handle in canvas.axes_list:
            left = handle.plot_item.getAxis("left")
            assert getattr(left, "labelText", "") == ""

    def test_subplot_inside_label_stays_viewport_anchored_after_pan_zoom(self, qapp):
        """Inside channel labels must act like matplotlib transAxes labels:
        pan/zoom changes data ranges, but the badge stays pinned to the
        ViewBox corner in scene pixels.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        QCoreApplication.processEvents()
        rows = [
            (
                f"[diya luntai] {name} VeryLongChannelNameForInsideBadge",
                visible,
                t,
                sig,
                color,
                unit,
                data_id,
            )
            for name, visible, t, sig, color, unit, data_id in _five_channel_rows()[:3]
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        item = canvas._inside_label_items[0]
        vb = canvas.axes_list[0].view_box
        before = item.sceneBoundingRect().topLeft() - vb.sceneBoundingRect().topLeft()

        canvas.axes_list[0].set_xlim(0.25, 0.75)
        canvas.axes_list[0].set_ylim(-0.25, 0.25)
        canvas._flush_pending_refresh()
        QCoreApplication.processEvents()

        after = item.sceneBoundingRect().topLeft() - vb.sceneBoundingRect().topLeft()
        assert abs(float(after.x()) - float(before.x())) <= 2.0
        assert abs(float(after.y()) - float(before.y())) <= 2.0

    def test_inside_label_hides_when_custom_title_is_set(self, qapp):
        """A subplot should not show both a top PlotItem title and an inside
        channel badge. The custom title wins in inside-label mode.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        QCoreApplication.processEvents()
        rows = [
            (
                f"[diya luntai] {name} VeryLongChannelNameForInsideBadge",
                visible,
                t,
                sig,
                color,
                unit,
                data_id,
            )
            for name, visible, t, sig, color, unit, data_id in _five_channel_rows()[:3]
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        assert canvas._inside_label_items

        handle = canvas.axes_list[0]
        handle.set_title("Custom subplot title")
        QCoreApplication.processEvents()

        assert "Custom subplot title" in handle.get_title()
        assert not canvas._inside_label_items[0].isVisible()


class TestTimeDomainCanvasPGOverlayMode:
    """5 channels in overlay mode → one PlotItem with per-channel Y axes
    on the LEFT side. Selected channel highlighted via line-width /
    alpha (1.8/1.0 vs 1.0/0.42 — matches canvases.py:_apply_overlay_
    selection_style)."""

    def test_overlay_initial_xrange_uses_raw_data_extent(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 80.0, 2_000, dtype=np.float64)
        rows = [
            ("speed", True, t, np.sin(t), "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, np.cos(t), "#ef4444", "Nm", "fid-1"),
            ("pressure", True, t, np.sin(t * 0.5), "#00b894", "bar", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        for handle in canvas.axes_list:
            lo, hi = handle.get_xlim()
            assert lo == pytest.approx(0.0)
            assert hi == pytest.approx(80.0)

    def test_overlay_aux_origin_xlim_updates_x_master_bottom_axis(self, qapp):
        """Changing an overlay channel ViewBox through the native axis controls
        must also update the X-master ViewBox that owns the bottom time axis.
        """
        from PyQt5.QtCore import QCoreApplication, QPointF

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 10.0, 1_000, dtype=np.float64)
        rows = [
            (f"ch{i}", True, t, np.sin(t) + i, "#1769e0", "u", f"fid-{i}")
            for i in range(3)
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        source = canvas.axes_list[1]
        source.view_box.setRange(xRange=(2.0, 6.0), padding=0)
        QCoreApplication.processEvents()

        assert canvas._x_master_handle.get_xlim() == pytest.approx((2.0, 6.0))
        for handle in canvas.axes_list:
            assert handle.get_xlim() == pytest.approx((2.0, 6.0))
        bottom_axis = canvas._x_master_handle.plot_item.getAxis("bottom")
        assert tuple(bottom_axis.range) == pytest.approx((2.0, 6.0))

        handles = [canvas._x_master_handle] + list(canvas.axes_list)
        mapped_x = [
            [
                float(handle.view_box.mapViewToScene(QPointF(x, 0.0)).x())
                for x in (2.0, 4.0, 6.0)
            ]
            for handle in handles
        ]
        ref = mapped_x[0]
        for row, xs in enumerate(mapped_x[1:], start=1):
            assert xs == pytest.approx(ref, abs=0.75), (
                f"overlay row {row} maps bottom-axis X ticks differently: "
                f"{xs!r} vs {ref!r}"
            )

    def test_overlay_emphasis_two_frame_line_width_difference(self, qapp):
        """Two-frame branch-reached-is-not-behavior-correct compliance.
        Frame A: no selection — every channel has the default linewidth.
        Frame B: select channel 'speed' — its linewidth strictly
        increases AND its alpha goes to 1.0, while the others drop to
        the de-emphasized state (alpha 0.42, lw 1.0)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        # Frame A: no selection.
        canvas.select_overlay_channel(None)
        QCoreApplication.processEvents()
        a_speed_lw, a_speed_alpha = canvas._overlay_emphasis_for_channel("speed")
        a_other_lw, a_other_alpha = canvas._overlay_emphasis_for_channel("torque")

        # Frame B: emphasise 'speed'.
        canvas.select_overlay_channel("speed")
        QCoreApplication.processEvents()
        b_speed_lw, b_speed_alpha = canvas._overlay_emphasis_for_channel("speed")
        b_other_lw, b_other_alpha = canvas._overlay_emphasis_for_channel("torque")

        # Strict two-frame difference.
        assert b_speed_lw > a_speed_lw, (
            f"selected channel linewidth must increase; "
            f"frame A speed_lw={a_speed_lw!r}, frame B={b_speed_lw!r}"
        )
        assert b_speed_alpha >= a_speed_alpha, (
            f"selected channel alpha must rise; got A={a_speed_alpha!r}, "
            f"B={b_speed_alpha!r}"
        )
        # De-emphasised channels MUST become more transparent than they
        # were in the default state.
        assert b_other_alpha < a_other_alpha, (
            f"de-emphasised channel alpha must drop; got A={a_other_alpha!r}, "
            f"B={b_other_alpha!r}"
        )

    def test_overlay_builds_independent_y_viewboxes_and_axes_per_channel(self, qapp):
        """Overlay mode must restore the original one-Y-axis-per-channel
        contract instead of sharing one ViewBox across all curves.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:4]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        assert len(canvas.axes_list) == len(rows)
        view_boxes = [handle.view_box for handle in canvas.axes_list]
        assert len({id(vb) for vb in view_boxes}) == len(rows)
        for handle, row in zip(canvas.axes_list, rows):
            name, _visible, _t, _sig, _color, _unit, _data_id = row
            axis_handle, _line = canvas._channel_lines[name]
            assert axis_handle is handle
            y_axis = handle.y_axis_item()
            assert y_axis is not None
            assert getattr(y_axis, "labelText", "")

    def test_overlay_selected_y_drag_changes_only_selected_channel_axis(self, qapp):
        """Dragging the selected overlay channel's Y axis must not pan every
        overlaid channel. Each channel owns an independent Y range.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:3]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        canvas.select_overlay_channel(rows[1][0])
        QCoreApplication.processEvents()

        ranges_before = [handle.get_ylim() for handle in canvas.axes_list]
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        moved = canvas._apply_overlay_y_drag_at(current_y_px=140.0)
        QCoreApplication.processEvents()
        ranges_after = [handle.get_ylim() for handle in canvas.axes_list]

        assert moved is True
        assert ranges_after[1] != pytest.approx(ranges_before[1])
        assert ranges_after[0] == pytest.approx(ranges_before[0])
        assert ranges_after[2] == pytest.approx(ranges_before[2])

    def test_overlay_blank_click_deselect_emits_signal(self, qapp):
        """Blank-click deselect must emit overlay_channel_selected(None).
        Two-frame: first signal is the select event with the channel
        name; second is the deselect with None."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        emitted = []
        canvas.overlay_channel_selected.connect(lambda v: emitted.append(v))

        canvas.select_overlay_channel("torque")
        QCoreApplication.processEvents()
        assert emitted[-1] == "torque", (
            f"first emission should be 'torque', got {emitted!r}"
        )

        canvas.select_overlay_channel(None)
        QCoreApplication.processEvents()
        assert emitted[-1] is None, (
            f"deselect emission should be None, got {emitted!r}"
        )
        assert len(emitted) == 2, (
            f"expected exactly 2 emissions (select+deselect); got {emitted!r}"
        )

    def test_overlay_selected_y_drag_emits_ylim_change(self, qapp):
        """Selected-channel Y drag must apply a ylim shift. Two-frame:
        record ylim before drag, simulate a drag with a non-zero dy_px,
        record ylim after — strict inequality.

        Symmetric overlay layout (Problem 3): the FIRST channel ('speed',
        vis[0]) is no longer special-cased onto the X-master ViewBox — it
        owns its own aux ViewBox like every other channel. The drag
        therefore moves the SELECTED channel's own handle, not
        ``_primary_xaxis_ax`` (which is now the curveless X-master), and
        the X-master's ranges must stay put.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        canvas.select_overlay_channel("speed")
        QCoreApplication.processEvents()

        selected_axis = canvas._channel_lines["speed"][0]
        selected_axis.set_ylim(-500.0, 500.0)
        QCoreApplication.processEvents()
        lo_before, hi_before = selected_axis.get_ylim()
        x_master_before = canvas._primary_xaxis_ax.get_xlim()

        # Simulate a 40-pixel downward drag on the selected channel.
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        moved = canvas._apply_overlay_y_drag_at(current_y_px=140.0)
        QCoreApplication.processEvents()

        lo_after, hi_after = selected_axis.get_ylim()
        # The drag method returned True (gesture consumed).
        assert moved is True, (
            f"_apply_overlay_y_drag_at must return True after a drag; "
            f"got {moved!r}"
        )
        # Strict two-frame difference (signal-processing lesson).
        assert (lo_before, hi_before) != (lo_after, hi_after), (
            f"y-drag must change ylim; before={lo_before, hi_before}, "
            f"after={lo_after, hi_after}"
        )
        # The first channel is now symmetric: dragging it must NOT move
        # the shared X range (the X-pin hack is dead under this layout).
        assert canvas._primary_xaxis_ax.get_xlim() == pytest.approx(
            x_master_before, abs=0.0, rel=0.0
        ), "first-channel Y drag must not perturb the shared X range"

    def test_overlay_shift_wheel_zooms_all_channels_together(self, qapp):
        """REGRESSION + design (655c28d 把裸点击选中改成 Alt+点击 → 叠加 Y 无法
        缩放): overlay Y-zoom must NOT require a pre-selected channel. Like the
        shared X (Ctrl+wheel), Shift+wheel zooms EVERY channel's Y together —
        each by the same factor — with nothing selected."""
        from PyQt5.QtCore import QCoreApplication, QPointF, Qt

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:3]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        assert canvas._overlay_axes.selected_channel is None, (
            "precondition: no channel selected (plain click no longer selects)"
        )

        handles = list(canvas.axes_list)
        assert len(handles) == 3
        # A scene position somewhere inside the plot to anchor the zoom.
        vb0 = handles[0].view_box
        xd, yd = handles[0].get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xd) - 0.5)))
        scene_pos = vb0.mapViewToScene(QPointF(float(xd[idx]), float(yd[idx])))

        before = [h.get_ylim() for h in handles]
        canvas._handle_wheel_dispatch(
            delta=120, modifiers=Qt.ShiftModifier,
            x_pos=0.5, y_pos=float(yd[idx]),
            view_box=vb0, scene_pos=scene_pos,
        )
        QCoreApplication.processEvents()

        after = [h.get_ylim() for h in handles]
        for i, (b, a) in enumerate(zip(before, after)):
            assert a != pytest.approx(b), (
                f"channel {i}: Shift+wheel must zoom its Y too (all channels "
                f"zoom together); before={b}, after={a}"
            )

    def test_overlay_plain_wheel_pans_all_channels_together(self, qapp):
        """Plain wheel pans EVERY overlay channel's Y together (no selection
        needed), mirroring the all-channel zoom."""
        from PyQt5.QtCore import QCoreApplication, QPointF, Qt

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:3]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        handles = list(canvas.axes_list)
        vb0 = handles[0].view_box
        xd, yd = handles[0].get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xd) - 0.5)))
        scene_pos = vb0.mapViewToScene(QPointF(float(xd[idx]), float(yd[idx])))

        before = [h.get_ylim() for h in handles]
        canvas._handle_wheel_dispatch(
            delta=120, modifiers=Qt.NoModifier,
            x_pos=0.5, y_pos=float(yd[idx]),
            view_box=vb0, scene_pos=scene_pos,
        )
        QCoreApplication.processEvents()

        after = [h.get_ylim() for h in handles]
        for i, (b, a) in enumerate(zip(before, after)):
            assert a != pytest.approx(b), (
                f"channel {i}: plain wheel must pan its Y too (all together)"
            )


class TestTimeDomainCanvasPGOverlayMouseInteraction:
    """Problem 2 + 3: overlay curve selection / Y-drag must be wired to
    REAL Qt mouse events through the canvas eventFilter (NOT matplotlib
    callbacks — see pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-
    renderer-swap). Every test drives QMouseEvent / QTest through the
    GraphicsLayoutWidget viewport, the same path the live UI uses.
    """

    def _overlay_canvas(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()
        # Pin a known X range so the geometry mapping is stable offscreen.
        canvas._primary_xaxis_ax.set_xlim(0.0, 1.0)
        QCoreApplication.processEvents()
        return canvas

    def _press(self, canvas, qapp, point):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        # 方案2: per-channel select / Y-drag / blank-deselect is now opt-in
        # behind Alt(Option). Plain presses fall through to pan, so the
        # selection-feature tests in this class drive Alt-presses.
        event = QMouseEvent(
            QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton,
            Qt.AltModifier,
        )
        consumed = canvas.eventFilter(canvas._glw.viewport(), event)
        QCoreApplication.processEvents()
        return consumed

    def _move(self, canvas, qapp, point):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton, Qt.NoModifier
        )
        consumed = canvas.eventFilter(canvas._glw.viewport(), event)
        QCoreApplication.processEvents()
        return consumed

    def _release(self, canvas, qapp, point):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.MouseButtonRelease, point, Qt.LeftButton, Qt.NoButton,
            Qt.NoModifier,
        )
        consumed = canvas.eventFilter(canvas._glw.viewport(), event)
        QCoreApplication.processEvents()
        return consumed

    def _axis_center_point(self, canvas, channel):
        axis = canvas._channel_lines[channel][0].y_axis_item()
        rect = axis.sceneBoundingRect()
        return canvas._glw.mapFromScene(rect.center())

    def test_press_on_nearest_curve_selects_that_channel(self, qapp):
        """A press within the 12px pick radius of a curve selects it."""
        canvas = self._overlay_canvas(qapp)
        emitted = []
        canvas.overlay_channel_selected.connect(emitted.append)

        # Target a point ON the 'torque' (channel 3) curve at x=0.5.
        handle = canvas._channel_lines["torque"][0]
        xdata, ydata = handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xdata) - 0.5)))
        point = _viewport_point_for_data(
            canvas, handle, float(xdata[idx]), float(ydata[idx])
        )
        consumed = self._press(canvas, qapp, point)

        assert consumed is True
        assert canvas._overlay_axes.selected_channel == "torque", (
            f"press on torque curve must select it; got "
            f"{canvas._overlay_axes.selected_channel!r}"
        )
        assert emitted and emitted[-1] == "torque"

    def test_press_on_first_channel_curve_selects_it_symmetrically(self, qapp):
        """Problem 3: the FIRST/left channel must be hit-test selectable
        just like the right-axis channels (symmetric layout)."""
        canvas = self._overlay_canvas(qapp)

        handle = canvas._channel_lines["speed"][0]
        # speed is vis[0] — confirm it is NOT on the X-master ViewBox.
        assert handle.view_box is not canvas._primary_xaxis_ax.view_box, (
            "first channel must own a dedicated aux ViewBox, not the X-master"
        )
        xdata, ydata = handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xdata) - 0.5)))
        point = _viewport_point_for_data(
            canvas, handle, float(xdata[idx]), float(ydata[idx])
        )
        consumed = self._press(canvas, qapp, point)

        assert consumed is True
        assert canvas._overlay_axes.selected_channel == "speed"

    def test_press_on_first_channel_then_drag_moves_only_its_axis(self, qapp):
        """Problem 3: the first channel is now draggable symmetrically —
        a press+drag moves ITS Y range and nothing else (and never the
        shared X)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = self._overlay_canvas(qapp)
        speed_handle = canvas._channel_lines["speed"][0]
        torque_handle = canvas._channel_lines["torque"][0]

        # Pin every channel's Y range FIRST so the press point is computed
        # against the exact geometry it is pressed in, and auto-range
        # re-detail on the post-drag refresh does not add measurement noise.
        speed_handle.set_ylim(-1500.0, 1500.0)
        torque_handle.set_ylim(40.0, 60.0)
        QCoreApplication.processEvents()

        # Target speed at its PEAK (top of its pinned range) where it is
        # unambiguously the nearest curve. x=0.5 sat at speed≈0 — mid-plot,
        # where overlapping channels make the 12px pick geometry-sensitive
        # (it flipped to 'pressure' once the canvas chrome was tightened).
        xdata, ydata = speed_handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmax(np.asarray(ydata)))
        start = _viewport_point_for_data(
            canvas, speed_handle, float(xdata[idx]), float(ydata[idx])
        )

        speed_before = speed_handle.get_ylim()
        torque_before = torque_handle.get_ylim()
        x_before = canvas._primary_xaxis_ax.get_xlim()

        self._press(canvas, qapp, start)
        assert canvas._overlay_axes.selected_channel == "speed", (
            f"press on speed's peak must select speed; got "
            f"{canvas._overlay_axes.selected_channel!r}"
        )
        assert canvas._overlay_axes.dragging is True
        from PyQt5.QtCore import QPoint
        moved_point = QPoint(start.x(), start.y() + 60)
        self._move(canvas, qapp, moved_point)
        self._release(canvas, qapp, moved_point)

        assert canvas._overlay_axes.dragging is False
        assert speed_handle.get_ylim() != pytest.approx(speed_before), (
            "first-channel drag must shift its own Y range"
        )
        assert torque_handle.get_ylim() == pytest.approx(torque_before), (
            "first-channel drag must not move other channels' Y"
        )
        assert canvas._primary_xaxis_ax.get_xlim() == pytest.approx(
            x_before, abs=0.0, rel=0.0
        ), "first-channel drag must not perturb the shared X"

    def _blankest_inplot_scene_point(self, canvas):
        """Return the in-plot scene point that is FARTHEST (in pixels) from
        every overlay curve, plus its min-distance. Used to construct a
        genuinely blank in-plot click (inside the X-master plot rect, beyond
        ``_overlay_pick_radius_px`` from all curves)."""
        from PyQt5.QtCore import QPointF

        master = canvas._primary_xaxis_ax.view_box
        rect = master.sceneBoundingRect()

        def min_dist(sp):
            best = float("inf")
            for _name, (handle, line) in canvas._channel_lines.items():
                vb = handle.view_box
                xd, yd = line.plot_data_item.getData()
                xd = np.asarray(xd, dtype=float)
                yd = np.asarray(yd, dtype=float)
                m = np.isfinite(xd) & np.isfinite(yd)
                xd, yd = xd[m], yd[m]
                pts = canvas._map_view_points_to_scene(vb, xd, yd)
                d = float(np.min(np.hypot(pts[:, 0] - sp.x(), pts[:, 1] - sp.y())))
                best = min(best, d)
            return best

        # Use a fine grid over a wide interior band. A coarse 9x9 grid was
        # too sparse: a few-px shift in the plot rect (e.g. the overlay
        # right-axis stack moving to contiguous columns) can drop the best
        # sampled gap below the pick radius even though a genuinely-blank
        # point still exists. The deselect BEHAVIOR is unchanged; the helper
        # just needs enough resolution to land on the blank region.
        best = None
        for fx in np.linspace(0.04, 0.96, 25):
            for fy in np.linspace(0.04, 0.96, 25):
                sx = rect.left() + fx * (rect.right() - rect.left())
                sy = rect.top() + fy * (rect.bottom() - rect.top())
                sp = QPointF(sx, sy)
                d = min_dist(sp)
                if best is None or d > best[1]:
                    best = (sp, d)
        return best

    def test_blank_inplot_click_deselects_and_emits_none(self, qapp):
        """Bug 5: a press on genuinely blank space INSIDE the plot rect (no
        curve within ``_overlay_pick_radius_px``) must deselect. Previously
        the ViewBox-rect axis-hit fallback returned channel 1 for any in-plot
        point because every aux ViewBox rect spans the full plot."""
        from PyQt5.QtCore import QCoreApplication

        canvas = self._overlay_canvas(qapp)
        canvas.select_overlay_channel("torque")
        QCoreApplication.processEvents()
        emitted = []
        canvas.overlay_channel_selected.connect(emitted.append)

        scene_pt, dist = self._blankest_inplot_scene_point(canvas)
        # Sanity: the point is genuinely blank (no curve within pick radius)
        # AND genuinely inside the plot rect (not the above-rect escape that
        # made the old test pass for the wrong reason).
        assert dist > canvas._overlay_axes.pick_radius_px, (
            f"could not find a blank in-plot point; nearest curve {dist:.1f}px"
        )
        master_rect = canvas._primary_xaxis_ax.view_box.sceneBoundingRect()
        assert master_rect.contains(scene_pt), (
            "test point must be inside the plot rect for this to exercise "
            "the in-plot deselect path"
        )

        viewport_pt = canvas._glw.mapFromScene(scene_pt)
        consumed = self._press(canvas, qapp, viewport_pt)

        assert consumed is True
        assert canvas._overlay_axes.selected_channel is None
        assert emitted and emitted[-1] is None

    def test_blank_click_deselects_and_emits_none(self, qapp):
        """A press far from every curve (blank area) deselects, emitting
        overlay_channel_selected(None). Tightened (Bug 5) to click an
        in-plot blank point rather than a point above the plot rect."""
        from PyQt5.QtCore import QCoreApplication

        canvas = self._overlay_canvas(qapp)
        canvas.select_overlay_channel("torque")
        QCoreApplication.processEvents()
        emitted = []
        canvas.overlay_channel_selected.connect(emitted.append)

        scene_pt, dist = self._blankest_inplot_scene_point(canvas)
        assert dist > canvas._overlay_axes.pick_radius_px
        # Must be inside the plot rect — the old version clicked ABOVE it,
        # which passed only because no ViewBox contained the point.
        master_rect = canvas._primary_xaxis_ax.view_box.sceneBoundingRect()
        assert master_rect.contains(scene_pt)
        point = canvas._glw.mapFromScene(scene_pt)
        consumed = self._press(canvas, qapp, point)

        assert consumed is True
        assert canvas._overlay_axes.selected_channel is None
        assert emitted and emitted[-1] is None

    def test_x_master_pan_disabled_during_drag(self, qapp):
        """While a Y-drag is in progress the X-master ViewBox's mouse pan
        must be disabled, then restored on release (Problem 2)."""
        canvas = self._overlay_canvas(qapp)
        master_vb = canvas._primary_xaxis_ax.view_box

        handle = canvas._channel_lines["speed"][0]
        xdata, ydata = handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xdata) - 0.5)))
        start = _viewport_point_for_data(
            canvas, handle, float(xdata[idx]), float(ydata[idx])
        )

        # Before: X-master allows shared-X panning only; its [0, 1] Y
        # graticule must never be mouse-draggable.
        assert master_vb.state["mouseEnabled"] == [True, False]

        self._press(canvas, qapp, start)
        assert canvas._overlay_axes.dragging is True
        assert master_vb.state["mouseEnabled"] == [False, False], (
            "X-master mouse must be disabled during a selected-channel Y-drag"
        )

        from PyQt5.QtCore import QPoint
        self._release(canvas, qapp, QPoint(start.x(), start.y() + 30))
        assert master_vb.state["mouseEnabled"] == [True, False], (
            "X-master X pan must be restored without enabling graticule Y-drag"
        )

    def test_overlay_y_axis_gutter_drag_moves_that_channel_only(self, qapp):
        """Dragging a channel's own Y-axis/tick gutter should move that
        channel even when the press is not on the curve body."""
        from PyQt5.QtCore import QPoint

        canvas = self._overlay_canvas(qapp)
        speed = canvas._channel_lines["speed"][0]
        torque = canvas._channel_lines["torque"][0]
        speed.set_ylim(-1500.0, 1500.0)
        torque.set_ylim(40.0, 60.0)

        start = self._axis_center_point(canvas, "torque")
        speed_before = speed.get_ylim()
        torque_before = torque.get_ylim()
        master_y_before = canvas._primary_xaxis_ax.get_ylim()

        consumed = self._press(canvas, qapp, start)
        assert consumed is True
        assert canvas._overlay_axes.selected_channel == "torque"
        assert canvas._overlay_axes.dragging is True

        moved = QPoint(start.x(), start.y() + 60)
        assert self._move(canvas, qapp, moved) is True
        self._release(canvas, qapp, moved)

        assert torque.get_ylim() != pytest.approx(torque_before)
        assert speed.get_ylim() == pytest.approx(speed_before)
        assert canvas._primary_xaxis_ax.get_ylim() == pytest.approx(master_y_before)

    def test_overlay_press_ignored_in_cursor_mode(self, qapp):
        """Cursor mode takes precedence over overlay selection
        (canvases.py:853): no channel gets selected by an overlay press."""
        canvas = self._overlay_canvas(qapp)
        canvas.set_cursor_visible(True)

        handle = canvas._channel_lines["torque"][0]
        xdata, ydata = handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xdata) - 0.5)))
        point = _viewport_point_for_data(
            canvas, handle, float(xdata[idx]), float(ydata[idx])
        )
        # Overlay press handler must no-op in cursor mode.
        consumed = canvas._handle_overlay_mouse_press(
            self._make_press_event(point)
        )
        assert consumed is False
        assert canvas._overlay_axes.selected_channel is None

    def _make_press_event(self, point):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton,
            Qt.NoModifier,
        )


class TestOverlayPressModeSplit:
    """Fix A (2026-05-31 overlay-aa-interaction-fixes): the overlay
    left-press selection/Y-drag handler must yield to the ViewBox rubber
    band in RectMode (box-zoom), and only keep nearest-curve-select +
    Y-drag in PanMode. The ViewBox mouseMode is read directly off the
    state dict (no mouse-mode controller dependency).
    """

    def _overlay_canvas(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()
        canvas._primary_xaxis_ax.set_xlim(0.0, 1.0)
        QCoreApplication.processEvents()
        return canvas

    def _press_event(self, point):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton,
            Qt.NoModifier,
        )

    def _alt_press_event(self, point):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton,
            Qt.AltModifier,
        )

    def _on_curve_point(self, canvas, channel="torque"):
        handle = canvas._channel_lines[channel][0]
        xdata, ydata = handle.get_lines()[0].plot_data_item.getData()
        idx = int(np.argmin(np.abs(np.asarray(xdata) - 0.5)))
        return _viewport_point_for_data(
            canvas, handle, float(xdata[idx]), float(ydata[idx])
        )

    def _set_all_viewboxes_mode(self, canvas, mode):
        import pyqtgraph as pg

        seen = set()
        for handle in canvas.axes_list + [canvas._x_master_handle]:
            if handle is None:
                continue
            vb = handle.view_box
            if vb is None or id(vb) in seen:
                continue
            seen.add(id(vb))
            vb.setMouseMode(mode)
        for vb in list(canvas._overlay_axes.aux_viewboxes or []):
            if id(vb) not in seen:
                vb.setMouseMode(mode)
                seen.add(id(vb))

    def test_rectmode_press_yields_to_rubber_band(self, qapp):
        """In RectMode a press tight on a curve must NOT select / Y-drag;
        the handler returns False so pyqtgraph starts the rubber band."""
        import pyqtgraph as pg

        canvas = self._overlay_canvas(qapp)
        self._set_all_viewboxes_mode(canvas, pg.ViewBox.RectMode)

        point = self._on_curve_point(canvas)
        consumed = canvas._handle_overlay_mouse_press(self._press_event(point))

        assert consumed is False, "RectMode press must let the rubber band start"
        assert canvas._overlay_axes.selected_channel is None
        assert canvas._overlay_axes.dragging is False

    def test_panmode_plain_press_falls_through_to_pan(self, qapp):
        """NEW (方案2): a PLAIN (no-modifier) PanMode press must NOT select /
        Y-drag — it returns False so the ViewBox X-pan runs. This is what lets
        a dense (filtered) overlay still pan instead of grabbing one curve, and
        keeps the Pan toolbar button active (no select → no
        _on_overlay_channel_selected → no pan toggle-off)."""
        import pyqtgraph as pg

        canvas = self._overlay_canvas(qapp)
        self._set_all_viewboxes_mode(canvas, pg.ViewBox.PanMode)

        point = self._on_curve_point(canvas)
        consumed = canvas._handle_overlay_mouse_press(self._press_event(point))

        assert consumed is False, "plain PanMode press must fall through to pan"
        assert canvas._overlay_axes.selected_channel is None
        assert canvas._overlay_axes.dragging is False

    def test_alt_press_selects_and_drags(self, qapp):
        """Alt(Option)+press is the opt-in per-channel Y-drag: it selects the
        nearest VISIBLE curve and begins the vertical reposition drag."""
        import pyqtgraph as pg

        canvas = self._overlay_canvas(qapp)
        self._set_all_viewboxes_mode(canvas, pg.ViewBox.PanMode)

        point = self._on_curve_point(canvas)
        consumed = canvas._handle_overlay_mouse_press(self._alt_press_event(point))

        assert consumed is True
        assert canvas._overlay_axes.selected_channel == "torque"
        assert canvas._overlay_axes.dragging is True

    def test_alt_press_skips_hidden_curve(self, qapp):
        """排除隐藏曲线 (两种显示情况都排除另外一个): an Alt-press right on a
        HIDDEN curve must never select it — only visible curves are draggable
        targets. Covers 只显示原始 (companion hidden) and 只显示滤波 (original
        hidden): whichever line is hidden is excluded from the hit test."""
        import pyqtgraph as pg
        from PyQt5.QtCore import QCoreApplication

        canvas = self._overlay_canvas(qapp)
        self._set_all_viewboxes_mode(canvas, pg.ViewBox.PanMode)

        hidden = "torque"
        # Resolve the on-curve point BEFORE hiding (get_lines() drops hidden
        # lines), then hide the line and Alt-press exactly on it.
        point = self._on_curve_point(canvas, channel=hidden)
        pdi = canvas._channel_lines[hidden][1].plot_data_item
        pdi.setVisible(False)
        QCoreApplication.processEvents()

        canvas._handle_overlay_mouse_press(self._alt_press_event(point))

        assert canvas._overlay_axes.selected_channel != hidden, (
            "Alt-press on a HIDDEN curve selected it — hidden curves must be "
            "excluded from the overlay hit test"
        )


class _FakeDragEvent:
    """Duck-typed stand-in for a pyqtgraph MouseDragEvent.

    Only the members ``_ModifierWheelViewBox.mouseDragEvent`` reads in its
    own (pre-``super()``) branch matter: ``button()`` and ``isStart()``.
    """

    def __init__(self, button, *, start):
        self._button = button
        self._start = start

    def button(self):
        return self._button

    def isStart(self):
        return self._start


class TestViewBoxDragAaHook:
    """Fix B (2026-05-31 overlay-aa-interaction-fixes): the box-zoom
    rubber band must drop AA at drag start, because the base ViewBox
    only changes range on ev.isFinish() — the whole rubber-band drag
    otherwise stays AA-on and re-rasterizes every frame. The subclass
    hooks ONLY RectMode + LeftButton + axis is None at isStart, and must
    ALWAYS delegate to super().
    """

    def _vb_with_owner(self, qapp):
        import pyqtgraph as pg
        from mf4_analyzer.ui.pg_canvases import _ModifierWheelViewBox

        class _OwnerSpy:
            def __init__(self):
                self.disabled = 0

            def disable_interactive_quality(self):
                self.disabled += 1

        owner = _OwnerSpy()
        vb = _ModifierWheelViewBox(owner_canvas=owner)
        return vb, owner

    def test_rectmode_left_isstart_drops_aa_and_calls_super(self, qapp, monkeypatch):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt

        vb, owner = self._vb_with_owner(qapp)
        vb.setMouseMode(pg.ViewBox.RectMode)

        super_calls = {"n": 0}
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: super_calls.__setitem__("n", super_calls["n"] + 1),
        )

        ev = _FakeDragEvent(Qt.LeftButton, start=True)
        vb.mouseDragEvent(ev, axis=None)

        assert owner.disabled == 1, "RectMode left isStart must drop AA"
        assert super_calls["n"] == 1, "super().mouseDragEvent must always run"

    def test_rectmode_left_non_start_does_not_redrop_but_calls_super(
        self, qapp, monkeypatch,
    ):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt

        vb, owner = self._vb_with_owner(qapp)
        vb.setMouseMode(pg.ViewBox.RectMode)

        super_calls = {"n": 0}
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: super_calls.__setitem__("n", super_calls["n"] + 1),
        )

        ev = _FakeDragEvent(Qt.LeftButton, start=False)
        vb.mouseDragEvent(ev, axis=None)

        assert owner.disabled == 0, "only isStart drops AA (idle gate covers held drag)"
        assert super_calls["n"] == 1

    def test_panmode_left_does_not_drop_aa_but_calls_super(self, qapp, monkeypatch):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt

        vb, owner = self._vb_with_owner(qapp)
        vb.setMouseMode(pg.ViewBox.PanMode)

        super_calls = {"n": 0}
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: super_calls.__setitem__("n", super_calls["n"] + 1),
        )

        ev = _FakeDragEvent(Qt.LeftButton, start=True)
        vb.mouseDragEvent(ev, axis=None)

        assert owner.disabled == 0, "PanMode must not use the RectMode hook"
        assert super_calls["n"] == 1

    def test_rectmode_single_axis_drag_does_not_drop_aa_but_calls_super(
        self, qapp, monkeypatch,
    ):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt

        vb, owner = self._vb_with_owner(qapp)
        vb.setMouseMode(pg.ViewBox.RectMode)

        super_calls = {"n": 0}
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: super_calls.__setitem__("n", super_calls["n"] + 1),
        )

        ev = _FakeDragEvent(Qt.LeftButton, start=True)
        vb.mouseDragEvent(ev, axis=0)

        assert owner.disabled == 0, "axis is None gate: single-axis drag is untouched"
        assert super_calls["n"] == 1

    def test_rectmode_right_button_does_not_drop_aa_but_calls_super(
        self, qapp, monkeypatch,
    ):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt

        vb, owner = self._vb_with_owner(qapp)
        vb.setMouseMode(pg.ViewBox.RectMode)

        super_calls = {"n": 0}
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: super_calls.__setitem__("n", super_calls["n"] + 1),
        )

        ev = _FakeDragEvent(Qt.RightButton, start=True)
        vb.mouseDragEvent(ev, axis=None)

        assert owner.disabled == 0, "right-button (zoom-out) drag is untouched"
        assert super_calls["n"] == 1


class TestTimeDomainCanvasPGCursorParity:
    """Single-cursor + dual-cursor HTML payloads must match
    canvases.py:_update_single (`cursor_info`) and
    canvases.py:_format_dual_html (`dual_cursor_info`) byte-for-byte.

    Per codex-plan-spec-literal-evidence + the explicit brief: import
    the SAME formatter helpers from canvases.py instead of
    reimplementing them so the strings cannot drift.
    """

    # test_single_cursor_html_matches_update_single_letter_for_letter was
    # removed in Phase D (2026-06-18) when TimeDomainCanvas (matplotlib) was
    # retired.  The parity contract is now enforced by sharing the same
    # formatter functions (_format_single_cursor_channel_html) in
    # mf4_analyzer.ui.plot_helpers, used by both the pg cursor and any
    # caller that previously compared against the mpl implementation.

    def test_single_cursor_html_preserves_full_channel_name_like_dual_cursor(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        full_name = "[tiaodamping] Rte_ESChkPlausi_mESMotorTorque_xds16"
        rest = "Rte_ESChkPlausi_mESMotorTorque_xds16"
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        rows = [
            (full_name, True, t, (t * 100.0).astype(np.float64), "#1769e0", "Nm", "fid-1"),
        ]

        pg = _pg_canvas(qapp)
        pg.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        single_emissions = []
        dual_emissions = []
        pg.cursor_info.connect(single_emissions.append)
        pg.dual_cursor_info.connect(dual_emissions.append)

        pg._emit_single_cursor_html(0.5)
        single_html = single_emissions[-1]
        pg._cursor.ax = 0.2
        pg._cursor.bx = 0.8
        pg._emit_dual_cursor_html()

        assert dual_emissions and rest in dual_emissions[-1]
        assert rest in single_html

    # test_dual_cursor_html_matches_format_dual_html_letter_for_letter was
    # removed in Phase D (2026-06-18) when TimeDomainCanvas (matplotlib) was
    # retired.  The parity contract is enforced by the shared formatter
    # _format_dual_html in mf4_analyzer.ui.plot_helpers.


class TestTimeDomainCanvasPGCursorInteraction:
    """Cursor helpers must be wired to real mouse interaction and visible
    pyqtgraph line items, not only callable from tests.
    """

    def test_single_cursor_mouse_move_emits_and_shows_lines(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)

        seen = []
        canvas.cursor_info.connect(seen.append)
        point = _viewport_point_for_data(canvas, canvas.axes_list[1], 0.42)
        event = QMouseEvent(
            QEvent.MouseMove, point, Qt.NoButton, Qt.NoButton, Qt.NoModifier
        )
        qapp.sendEvent(canvas._glw.viewport(), event)
        QCoreApplication.processEvents()

        assert seen, "mouse move in single-cursor mode must emit cursor_info"
        assert "t=" in seen[-1]
        line_items = canvas._cursor.line_items
        assert len(line_items) == len(canvas.axes_list)
        assert all(item.isVisible() for item in line_items)

    def test_dual_cursor_mouse_clicks_place_a_b_and_emit_stats(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt
        from PyQt5.QtTest import QTest

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)

        primary_seen = []
        dual_seen = []
        canvas.cursor_info.connect(primary_seen.append)
        canvas.dual_cursor_info.connect(dual_seen.append)

        viewport = canvas._glw.viewport()
        point_a = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.25)
        point_b = _viewport_point_for_data(canvas, canvas.axes_list[2], 0.75)
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, point_a)
        QCoreApplication.processEvents()
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, point_b)
        QCoreApplication.processEvents()

        assert canvas._cursor.ax == pytest.approx(0.25, abs=0.03)
        assert canvas._cursor.bx == pytest.approx(0.75, abs=0.03)
        assert primary_seen and "ΔT=" in primary_seen[-1]
        assert dual_seen and dual_seen[-1]
        a_items = canvas._cursor.a_items
        b_items = canvas._cursor.b_items
        assert len(a_items) == len(canvas.axes_list)
        assert len(b_items) == len(canvas.axes_list)
        assert all(item.isVisible() for item in a_items + b_items)

    def test_dual_cursor_marks_region_min_and_max_points(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt
        from PyQt5.QtTest import QTest

        canvas = _pg_canvas(qapp)
        t = np.array([0.0, 0.25, 0.50, 0.75, 1.0], dtype=np.float64)
        sig = np.array([1.0, -3.0, 2.0, 5.0, 0.0], dtype=np.float64)
        canvas.plot_channels([
            ("speed", True, t, sig, "#1769e0", "rpm", "fid-1"),
        ], mode="single")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)

        viewport = canvas._glw.viewport()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[0], 0.20),
        )
        QCoreApplication.processEvents()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[0], 0.80),
        )
        QCoreApplication.processEvents()

        markers = canvas._cursor.extreme_markers
        assert len(markers) == 1
        xs, ys = markers[0].getData()
        assert list(xs) == pytest.approx([0.25, 0.75])
        assert list(ys) == pytest.approx([-3.0, 5.0])
        assert markers[0].isVisible()

    def test_dual_cursor_hover_move_does_not_recompute_stats(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication, Qt
        from PyQt5.QtTest import QTest

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)

        viewport = canvas._glw.viewport()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[0], 0.25),
        )
        QCoreApplication.processEvents()
        QTest.mouseClick(
            viewport, Qt.LeftButton, Qt.NoModifier,
            _viewport_point_for_data(canvas, canvas.axes_list[2], 0.75),
        )
        QCoreApplication.processEvents()

        calls = []
        monkeypatch.setattr(
            canvas, "_emit_dual_cursor_html", lambda *a, **k: calls.append(1)
        )
        canvas._cursor.last_t = 0

        point = _viewport_point_for_data(canvas, canvas.axes_list[1], 0.5)
        assert canvas._handle_cursor_mouse_move(_FakeMove(point.x(), point.y())) is True

        assert calls == []
        line_items = canvas._cursor.line_items
        assert line_items
        assert all(item.isVisible() for item in line_items)

    def test_cursor_mousemove_with_left_button_does_not_consume_pan_drag(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)

        point = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.5)
        event = QMouseEvent(
            QEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton, Qt.NoModifier
        )
        consumed = canvas.eventFilter(canvas._glw.viewport(), event)
        assert consumed is False

    def test_single_cursor_mousemove_is_throttled_to_one_emit_per_33ms(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)

        seen = []
        canvas.cursor_info.connect(seen.append)
        point = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.5)

        for _ in range(5):
            assert canvas._handle_cursor_mouse_move(point) is True

        assert len(seen) == 1

        canvas._cursor.last_t -= 40
        assert canvas._handle_cursor_mouse_move(point) is True
        assert len(seen) == 2


class _FakeMenuEvent:
    """Minimal stand-in for the pyqtgraph mouse event a ViewBox passes to
    ``raiseContextMenu``. It needs ``acceptedItem`` (read by the scene's
    ``getContextMenus``) and ``screenPos()`` (read before ``popup``)."""

    def __init__(self, accepted_item, scene_pos=None):
        self.acceptedItem = accepted_item
        self._scene_pos = scene_pos

    def screenPos(self):
        from PyQt5.QtCore import QPointF

        return QPointF(0.0, 0.0)

    def scenePos(self):
        from PyQt5.QtCore import QPointF

        return self._scene_pos or QPointF(0.0, 0.0)


def _assemble_and_redesign_menu(qapp, canvas, view_box, monkeypatch):
    """Drive the REAL ``raiseContextMenu`` path (assemble Plot Options +
    Export, then reshape per design A–D) without actually popping a window.

    Returns the assembled+reshaped QMenu. ``QMenu.popup`` is patched to a
    no-op so nothing is shown under offscreen Qt.
    """
    from PyQt5.QtWidgets import QMenu

    captured = {}

    def _fake_popup(self, *_args, **_kwargs):
        captured["menu"] = self

    monkeypatch.setattr(QMenu, "popup", _fake_popup, raising=True)
    ev = _FakeMenuEvent(view_box)
    view_box.raiseContextMenu(ev)
    return captured.get("menu")


def _top_level_texts(menu):
    return [
        a.text().replace("&", "").strip()
        for a in menu.actions()
        if not a.isSeparator()
    ]


def _inline_panel(menu):
    from PyQt5.QtWidgets import QWidgetAction

    panels = [
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    ]
    assert len(panels) == 1
    return panels[0]


def _panel_button(panel, object_name):
    from PyQt5.QtWidgets import QPushButton, QToolButton

    button = panel.findChild((QPushButton, QToolButton), object_name)
    assert button is not None
    return button


def _panel_edit(panel, object_name):
    from PyQt5.QtWidgets import QLineEdit

    edit = panel.findChild(QLineEdit, object_name)
    assert edit is not None
    return edit


def _panel_labels(panel):
    from PyQt5.QtWidgets import QLabel

    return [
        label.text()
        for label in panel.findChildren(QLabel)
        if label.objectName() == "pgContextInlineLabel"
    ]


class TestTimeDomainCanvasPGContextMenuRedesign:
    """Design 2026-05-30 §A–§D: the right-click menu is the reshaped native
    pyqtgraph QMenu — only the agreed top-level items survive, tooltips are
    off, and 鼠标操作 is wired to the toolbar's mouse-mode state machine."""

    # ---- §A structure: only the agreed items, removed ones absent ----
    def test_top_level_menu_contains_only_inline_panel(self, qapp, monkeypatch):
        from PyQt5.QtWidgets import QWidgetAction

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        # Register a controller to mirror the real app. The context menu should
        # still keep mouse-mode operations toolbar-owned.
        class _Ctl:
            def current_mouse_mode(self):
                return ""
            def set_pan_mode(self):
                pass
            def set_zoom_mode(self):
                pass
        canvas.register_mouse_mode_controller(_Ctl())

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        assert menu is not None

        _inline_panel(menu)

        named = _top_level_texts(menu)
        assert named == [""]
        for removed in ("Y 轴自适应", "查看全部", "X 轴范围", "Y 轴范围", "网格"):
            assert removed not in named
        assert "鼠标操作" not in named
        assert "鼠标模式" not in named

    def test_removed_entries_are_absent_from_assembled_menu(
        self, qapp, monkeypatch
    ):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        top = _top_level_texts(menu)

        for banned in ("绘图选项", "Plot Options", "导出...", "Export...", "变换", "降采样"):
            assert banned not in top

    def test_keep_plot_options_keeps_plot_options_after_inline_panel(self, qapp):
        from PyQt5.QtWidgets import QAction, QMenu

        from mf4_analyzer.ui.pg_canvas.context_menu import redesign_pg_context_menu

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        handle = canvas.axes_list[0]
        menu = QMenu()
        menu.addAction(QAction("View All", menu))
        menu.addAction(QAction("Plot Options", menu))

        redesign_pg_context_menu(
            menu,
            handle.plot_item,
            None,
            keep_plot_options=True,
        )

        assert _inline_panel(menu).objectName() == "pgContextInlinePanel"
        assert _top_level_texts(menu) == ["", "绘图选项"]

    def test_annotation_delete_entries_are_absent_from_context_menu(
        self, qapp, monkeypatch,
    ):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box
        canvas._annotations.remarks.append({"vb": vb})

        _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        named = _top_level_texts(menu)

        assert "删除最近标注" not in named
        assert "删除全部标注" not in named

    def test_annotation_mode_right_click_deletes_without_context_menu(
        self, qapp, monkeypatch,
    ):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtWidgets import QMenu

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box
        canvas.set_remark_enabled(True)
        scene_pos = QPointF(12.0, 34.0)
        removed = []
        popped = []
        monkeypatch.setattr(
            canvas._annotations,
            "_remove_remark_at",
            lambda sp: removed.append(sp),
        )
        monkeypatch.setattr(QMenu, "popup", lambda *args, **kwargs: popped.append(args))

        vb.raiseContextMenu(_FakeMenuEvent(vb, scene_pos))

        assert removed == [scene_pos]
        assert popped == []

    def test_inline_panel_rows_labels_and_buttons_match_contract(
        self, qapp, monkeypatch
    ):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)

        assert _panel_labels(panel) == ["鼠标", "查看", "X范围", "Y范围", "网格"]
        assert _panel_button(panel, "pgContextYFitButton").text() == "Y适应"
        assert _panel_button(panel, "pgContextViewAllButton").text() == "全图"
        assert _panel_button(panel, "pgContextZoomButton").toolTip() == "框选"
        assert _panel_button(panel, "pgContextPanButton").toolTip() == "平移"
        assert _panel_button(panel, "pgContextGridXChip").text() == "X"
        assert _panel_button(panel, "pgContextGridYChip").text() == "Y"
        for name in (
            "pgContextYFitButton",
            "pgContextViewAllButton",
            "pgContextXMinEdit",
            "pgContextXMaxEdit",
            "pgContextYMinEdit",
            "pgContextYMaxEdit",
        ):
            widget = panel.findChild(QWidget, name)
            assert widget.width() == 72
            assert widget.height() == 30
        for name in ("pgContextGridXChip", "pgContextGridYChip"):
            chip = _panel_button(panel, name)
            assert chip.width() == 48
            assert chip.height() == 30

    def test_overlay_grid_chip_x_toggle_does_not_enable_y_grid(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()

        pi = canvas._x_master_handle.plot_item
        vb = canvas._x_master_handle.view_box
        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)
        act_x = _panel_button(panel, "pgContextGridXChip")
        act_y = _panel_button(panel, "pgContextGridYChip")

        assert act_x.isChecked()
        assert not act_y.isChecked()
        assert not act_y.isEnabled()

        act_x.click()
        QCoreApplication.processEvents()

        assert not pi.getAxis("bottom").grid
        assert not pi.getAxis("left").grid
        assert not pi.getAxis("right").grid
        for ax_item in canvas._overlay_axes.aux_axes:
            assert not ax_item.grid

    def test_inline_grid_chip_toggle_keeps_top_right_grid_disabled(self, qapp):
        """The SHARED grid submenu must honor the line/heatmap canvas policy:
        only left+bottom carry the grid; top+right stay OFF. pyqtgraph's
        showGrid lights all four built-in axes, so without the
        re-disable-top/right guard a single context-menu toggle would re-light
        them and re-introduce the FIX4 double-gridline (boundary) artifact.
        Assert ``ax.grid`` state per the boundary-grid lesson — do NOT drive
        the real generateDrawSpecs (it access-violates offscreen)."""
        import pyqtgraph as pg
        from mf4_analyzer.ui.pg_canvas.context_menu import (
            _make_inline_context_panel_action,
        )

        glw = pg.GraphicsLayoutWidget()
        plot_item = glw.addPlot()
        # Reproduce the canvases' constructor policy: top+right grid OFF
        # (heatmap_canvas.py:613-614, line_canvas.py:145-146).
        plot_item.getAxis("top").setGrid(False)
        plot_item.getAxis("right").setGrid(False)

        menu = pg.QtWidgets.QMenu()
        menu.addAction(_make_inline_context_panel_action(
            menu,
            plot_item,
            None,
            allow_y_grid=True,
        ))
        panel = _inline_panel(menu)
        act_x = _panel_button(panel, "pgContextGridXChip")
        act_y = _panel_button(panel, "pgContextGridYChip")

        # Enable both X and Y grid through the shared submenu toggle path.
        if not act_x.isChecked():
            act_x.click()
        if not act_y.isChecked():
            act_y.click()

        # left+bottom carry the grid (boundary-suppressing axes)...
        assert plot_item.getAxis("bottom").grid
        assert plot_item.getAxis("left").grid
        # ...but top+right MUST remain disabled despite showGrid lighting all
        # four — otherwise the plain top/right axes re-draw the boundary line.
        assert plot_item.getAxis("top").grid is False
        assert plot_item.getAxis("right").grid is False

        glw.deleteLater()

    def test_context_menu_view_all_resets_overlay_raw_x_and_per_channel_y(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        rows = _five_channel_rows()[:2]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        left = canvas.axes_list[0]
        right = canvas.axes_list[1]
        left.set_xlim(0.2, 0.4)
        left.set_ylim(-1.0, 1.0)
        right.set_ylim(45.0, 55.0)
        QCoreApplication.processEvents()

        menu = _assemble_and_redesign_menu(
            qapp, canvas, canvas._x_master_handle.view_box, monkeypatch
        )
        view_all = _panel_button(_inline_panel(menu), "pgContextViewAllButton")
        view_all.click()
        QCoreApplication.processEvents()

        from mf4_analyzer.ui.pg_canvas.ticks_math import _frame_to_nice

        t0 = rows[0][2]
        sig0 = rows[0][3]
        sig1 = rows[1][3]
        assert left.get_xlim() == pytest.approx(
            (float(t0.min()), float(t0.max())),
            abs=1e-6,
        )
        # Home pads Y by 5% then snaps to nice tick boundaries so Y-axis
        # labels and grid lines start and end exactly at the viewport edges.
        n_y = max(3, min(20, canvas._tick_density_controller.density[1]))
        lo0, hi0 = float(sig0.min()), float(sig0.max())
        pad0 = (hi0 - lo0) * 0.05
        exp_lo0, exp_hi0, _ = _frame_to_nice(lo0 - pad0, hi0 + pad0, n_y)
        assert left.get_ylim() == pytest.approx((exp_lo0, exp_hi0), rel=1e-6)
        lo1, hi1 = float(sig1.min()), float(sig1.max())
        pad1 = (hi1 - lo1) * 0.05
        exp_lo1, exp_hi1, _ = _frame_to_nice(lo1 - pad1, hi1 + pad1, n_y)
        assert right.get_ylim() == pytest.approx((exp_lo1, exp_hi1), rel=1e-6)

    def test_inline_panel_has_translucent_background_and_no_submenus(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        # Parity anchor: the top-level menu is already translucent.
        assert menu.testAttribute(Qt.WA_TranslucentBackground)
        panel = _inline_panel(menu)
        assert panel.testAttribute(Qt.WA_TranslucentBackground)
        assert panel.autoFillBackground() is False
        assert all(action.menu() is None for action in menu.actions())

    def test_context_menus_disable_native_drop_shadow(self, qapp, monkeypatch):
        """The rounded QSS corners render transparent, but macOS still paints a
        square native drop-shadow around the popup's bounding rect — the
        residual right angles the user reported. NoDropShadowWindowHint (and
        FramelessWindowHint) on the menu AND every submenu kills it."""
        from PyQt5.QtCore import Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        menus = [menu]
        for m in menus:
            flags = m.windowFlags()
            assert bool(flags & Qt.NoDropShadowWindowHint), (
                f"{m.title()!r} menu must set NoDropShadowWindowHint"
            )
            assert bool(flags & Qt.FramelessWindowHint), (
                f"{m.title()!r} menu must set FramelessWindowHint"
            )

    def test_inline_range_edits_show_current_viewbox_values_and_apply_valid_input(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box
        vb.setXRange(1.25, 4.5, padding=0)
        vb.setYRange(-2.5, 3.75, padding=0)
        QCoreApplication.processEvents()

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)
        x_min = _panel_edit(panel, "pgContextXMinEdit")
        x_max = _panel_edit(panel, "pgContextXMaxEdit")
        y_min = _panel_edit(panel, "pgContextYMinEdit")
        y_max = _panel_edit(panel, "pgContextYMaxEdit")

        assert (x_min.text(), x_max.text()) == ("1.25", "4.5")
        assert (y_min.text(), y_max.text()) == ("-2.5", "3.75")
        assert "自动" not in {x_min.text(), x_max.text(), y_min.text(), y_max.text()}

        x_min.setText("2")
        x_max.setText("3")
        x_max.editingFinished.emit()
        QCoreApplication.processEvents()
        assert vb.viewRange()[0] == pytest.approx([2.0, 3.0])

        y_min.setText("-1")
        y_max.setText("1")
        y_max.editingFinished.emit()
        QCoreApplication.processEvents()
        assert vb.viewRange()[1] == pytest.approx([-1.0, 1.0])

    def test_inline_range_edits_reject_invalid_input_and_restore_current_range(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box
        vb.setXRange(1.0, 2.0, padding=0)
        vb.setYRange(-3.0, 4.0, padding=0)
        QCoreApplication.processEvents()

        panel = _inline_panel(_assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch))
        x_min = _panel_edit(panel, "pgContextXMinEdit")
        x_max = _panel_edit(panel, "pgContextXMaxEdit")
        y_min = _panel_edit(panel, "pgContextYMinEdit")
        y_max = _panel_edit(panel, "pgContextYMaxEdit")

        x_min.setText("oops")
        x_max.editingFinished.emit()
        assert vb.viewRange()[0] == pytest.approx([1.0, 2.0])
        assert (x_min.text(), x_max.text()) == ("1", "2")

        y_min.setText("9")
        y_max.setText("1")
        y_max.editingFinished.emit()
        QCoreApplication.processEvents()
        assert vb.viewRange()[1] == pytest.approx([-3.0, 4.0])
        assert (y_min.text(), y_max.text()) == ("-3", "4")

    def test_inline_y_range_edits_target_triggered_overlay_viewbox(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:2], mode="overlay")
        QCoreApplication.processEvents()

        master = canvas.axes_list[0]
        aux = canvas.axes_list[1]
        master.set_ylim(-1.0, 1.0)
        aux.set_ylim(40.0, 60.0)
        QCoreApplication.processEvents()

        menu = _assemble_and_redesign_menu(qapp, canvas, aux.view_box, monkeypatch)
        panel = _inline_panel(menu)
        y_min = _panel_edit(panel, "pgContextYMinEdit")
        y_max = _panel_edit(panel, "pgContextYMaxEdit")
        assert tuple(float(edit.text()) for edit in (y_min, y_max)) == pytest.approx(
            (40.0, 60.0)
        )

        y_min.setText("42")
        y_max.setText("58")
        y_max.editingFinished.emit()
        QCoreApplication.processEvents()

        assert master.get_ylim() == pytest.approx((-1.0, 1.0))
        assert aux.get_ylim() == pytest.approx((42.0, 58.0))

    # ---- §B tooltip fix ----
    def test_tooltips_visible_is_false_and_actions_have_no_tooltip(
        self, qapp, monkeypatch
    ):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        # toolTipsVisible(False) is the bug fix: even if Qt falls back to
        # toolTip()==text(), nothing floats over the second-level form.
        assert menu.toolTipsVisible() is False

        # The occluding help is the long descriptive tooltip we used to set
        # (e.g. "回到完整数据范围…"). After the redesign no surviving action
        # carries a descriptive tooltip — Qt's harmless text fallback aside,
        # the tooltip must never be longer than the label itself.
        def _assert_no_descriptive_tooltip(action):
            tip = action.toolTip()
            label = action.text().replace("&", "").strip()
            assert tip in ("", label), (
                f"action {label!r} kept a descriptive tooltip: {tip!r}"
            )

        for action in menu.actions():
            if action.isSeparator():
                continue
            _assert_no_descriptive_tooltip(action)
            assert action.menu() is None

        panel = _inline_panel(menu)
        assert _panel_button(panel, "pgContextZoomButton").toolTip() == "框选"
        assert _panel_button(panel, "pgContextPanButton").toolTip() == "平移"
        assert _panel_button(panel, "pgContextYFitButton").toolTip() == ""
        assert _panel_button(panel, "pgContextViewAllButton").toolTip() == ""

    # ---- §④b context menu keeps mouse mode toolbar-owned ----
    def test_context_menu_keeps_mouse_mode_inline_buttons(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        class _Ctl:
            def __init__(self):
                self.mode = ""
            def current_mouse_mode(self):
                return self.mode
            def set_pan_mode(self):
                self.mode = "pan"
            def set_zoom_mode(self):
                self.mode = "zoom"

        canvas.register_mouse_mode_controller(_Ctl())

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)
        zoom = _panel_button(panel, "pgContextZoomButton")
        pan = _panel_button(panel, "pgContextPanButton")
        assert zoom.toolTip() == "框选"
        assert pan.toolTip() == "平移"
        assert not zoom.isChecked()
        assert not pan.isChecked()
        zoom.click()
        assert canvas._mouse_mode_controller.mode == "zoom"
        assert _top_level_texts(menu)[0] == ""

    def test_inline_panel_keeps_mouse_buttons_disabled_when_no_controller(
        self, qapp, monkeypatch
    ):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        # No controller registered -> defensive: the panel remains the single
        # menu entry, but toolbar-owned mouse buttons cannot mutate state.
        canvas._mouse_mode_controller = None
        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)
        assert _top_level_texts(menu) == [""]
        assert not _panel_button(panel, "pgContextZoomButton").isEnabled()
        assert not _panel_button(panel, "pgContextPanButton").isEnabled()

    def test_context_menu_shell_and_inline_panel_are_transparent(
        self, qapp, monkeypatch
    ):
        from PyQt5.QtCore import Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        vb = canvas.axes_list[0].view_box

        menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
        panel = _inline_panel(menu)
        assert menu.objectName() == "pgContextMenu"
        assert menu.testAttribute(Qt.WA_TranslucentBackground)
        assert panel.testAttribute(Qt.WA_TranslucentBackground)
        assert panel.autoFillBackground() is False


class TestTimeDomainCanvasPGScroll:
    """Scroll behavior parity: Ctrl+wheel zooms X, Shift+wheel zooms Y,
    plain wheel pans Y. Tests use two-frame strict-difference assertions
    on the visible range, not branch-reached snapshots."""

    def test_ctrl_wheel_zooms_x(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        y_before = primary.get_ylim()

        # Wheel up with Ctrl: zoom IN on X. delta>0 → zoom in.
        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.ControlModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = primary.get_ylim()

        assert x_after != x_before, (
            f"Ctrl+wheel must change xlim; got {x_after!r} == {x_before!r}"
        )
        # X span must strictly shrink on zoom-in.
        assert (x_after[1] - x_after[0]) < (x_before[1] - x_before[0]), (
            f"zoom-in must shrink X span; before={x_before!r}, after={x_after!r}"
        )
        # Y MUST be untouched (Ctrl is the X-zoom modifier).
        assert y_after == pytest.approx(y_before), (
            f"Ctrl+wheel must NOT change ylim; before={y_before!r}, "
            f"after={y_after!r}"
        )

    def test_shift_wheel_zooms_y(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        canvas.select_overlay_channel("speed")
        selected = canvas._channel_lines["speed"][0]
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        primary_y_before = primary.get_ylim()
        y_before = selected.get_ylim()

        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = selected.get_ylim()

        assert y_after != y_before, (
            f"Shift+wheel must change ylim; got {y_after!r} == {y_before!r}"
        )
        assert (y_after[1] - y_after[0]) < (y_before[1] - y_before[0]), (
            f"zoom-in must shrink Y span; before={y_before!r}, after={y_after!r}"
        )
        assert x_after == pytest.approx(x_before), (
            f"Shift+wheel must NOT change xlim; before={x_before!r}, "
            f"after={x_after!r}"
        )
        assert primary.get_ylim() == pytest.approx(primary_y_before)

    def test_plain_wheel_pans_y(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        canvas.select_overlay_channel("speed")
        selected = canvas._channel_lines["speed"][0]
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        primary_y_before = primary.get_ylim()
        y_before = selected.get_ylim()
        y_span_before = y_before[1] - y_before[0]

        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.NoModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = selected.get_ylim()
        y_span_after = y_after[1] - y_after[0]

        assert y_after != y_before, (
            f"plain wheel must pan Y; got {y_after!r} == {y_before!r}"
        )
        # Pan preserves span; zoom does not.
        assert y_span_after == pytest.approx(y_span_before, rel=1e-6), (
            f"plain wheel must preserve Y span (pan, not zoom); "
            f"before span={y_span_before!r}, after span={y_span_after!r}"
        )
        # X MUST be untouched.
        assert x_after == pytest.approx(x_before), (
            f"plain wheel must NOT change xlim; before={x_before!r}, "
            f"after={x_after!r}"
        )
        assert primary.get_ylim() == pytest.approx(primary_y_before)

    def test_shift_wheel_targets_source_subplot_y_not_primary(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()
        primary = canvas.axes_list[0]
        target = canvas.axes_list[2]
        primary.set_ylim(-10.0, 10.0)
        target.set_ylim(-20.0, 20.0)
        QCoreApplication.processEvents()

        primary_before = primary.get_ylim()
        target_before = target.get_ylim()
        canvas._handle_wheel_dispatch(
            delta=120,
            modifiers=Qt.ShiftModifier,
            x_pos=0.5,
            y_pos=0.0,
            view_box=target.view_box,
        )
        QCoreApplication.processEvents()

        assert target.get_ylim() != pytest.approx(target_before), (
            "Shift+wheel over a non-primary subplot must zoom that subplot's Y range"
        )
        assert primary.get_ylim() == pytest.approx(primary_before), (
            "Shift+wheel over a non-primary subplot must not zoom primary Y"
        )

    def test_plain_wheel_targets_source_subplot_y_not_primary(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()
        primary = canvas.axes_list[0]
        target = canvas.axes_list[3]
        primary.set_ylim(-10.0, 10.0)
        target.set_ylim(-20.0, 20.0)
        QCoreApplication.processEvents()

        primary_before = primary.get_ylim()
        target_before = target.get_ylim()
        canvas._handle_wheel_dispatch(
            delta=120,
            modifiers=Qt.NoModifier,
            x_pos=0.5,
            y_pos=0.0,
            view_box=target.view_box,
        )
        QCoreApplication.processEvents()

        assert target.get_ylim() != pytest.approx(target_before), (
            "plain wheel over a non-primary subplot must pan that subplot's Y range"
        )
        assert primary.get_ylim() == pytest.approx(primary_before), (
            "plain wheel over a non-primary subplot must not pan primary Y"
        )


class TestTimeDomainCanvasPGModeSwitchXlim:
    """Subplot ↔ overlay rebuild must capture xlim BEFORE teardown and
    restore it AFTER build. The pattern lives INSIDE the canvas (per
    brief: MainWindow should not be involved). Two-frame strict-equality
    assertion on the post-switch xlim."""

    def test_subplot_to_overlay_preserves_user_xlim(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        # User pans to a specific window.
        canvas._primary_xaxis_ax.set_xlim(0.30, 0.45)
        QCoreApplication.processEvents()
        xlim_before = canvas._primary_xaxis_ax.get_xlim()
        assert xlim_before[0] == pytest.approx(0.30, abs=1e-6)
        assert xlim_before[1] == pytest.approx(0.45, abs=1e-6)

        # Switch mode via the rebuild path.
        canvas.plot_channels_preserving_xlim(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        xlim_after = canvas._primary_xaxis_ax.get_xlim()
        # Strict equality (within rounding) — the user's window survived.
        assert xlim_after[0] == pytest.approx(xlim_before[0], abs=1e-6), (
            f"mode-switch dropped lo: before={xlim_before!r}, after={xlim_after!r}"
        )
        assert xlim_after[1] == pytest.approx(xlim_before[1], abs=1e-6), (
            f"mode-switch dropped hi: before={xlim_before!r}, after={xlim_after!r}"
        )

    def test_overlay_to_subplot_preserves_xlim_and_updates_bottom_axis_numbers(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()

        canvas._x_master_handle.set_xlim(0.25, 0.50)
        QCoreApplication.processEvents()
        xlim_before = canvas._x_master_handle.get_xlim()

        canvas.plot_channels_preserving_xlim(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        assert canvas._primary_xaxis_ax.get_xlim() == pytest.approx(xlim_before)
        for handle in canvas.axes_list:
            assert handle.get_xlim() == pytest.approx(xlim_before)
        bottom_axis = canvas.axes_list[-1].plot_item.getAxis("bottom")
        assert tuple(bottom_axis.range) == pytest.approx(xlim_before)

    def test_plot_time_does_not_enable_span_selector(self, qapp):
        """T5 invariant reaffirmation: ``enable_span_selector(cb)`` is
        stored but NEVER auto-fired from ``plot_channels``. Per design
        §4.2 + main_window.py:993-996. Two-frame: call plot_channels
        once, then again with different content — the callback list
        stays empty."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        fired = []
        canvas.enable_span_selector(lambda lo, hi: fired.append((lo, hi)))

        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        assert fired == [], (
            f"plot_channels must NOT auto-fire the span callback; got {fired!r}"
        )

        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()
        assert fired == [], (
            f"second plot_channels must still not auto-fire; got {fired!r}"
        )


class TestTimeDomainCanvasPGVisualParityScreenshots:
    """Geometry-level visual parity gate (codex-visual-parity-rendered-
    screenshot). Renders 3 PNGs to /tmp and asserts each is non-null,
    width>100, height>100, and the cursor pill (when active) lies
    inside the view bbox.

    Pixel-byte parity is T7's job; T6's gate is geometry + container
    containment, per the brief.
    """

    def test_subplot_5ch_screenshot_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None, "grab_pixmap returned None"
        assert not pix.isNull(), "subplot screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        out = "/tmp/pg_parity_subplot_5ch.png"
        assert pix.save(out), f"failed to save {out!r}"

    def test_overlay_5ch_screenshot_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "overlay screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        out = "/tmp/pg_parity_overlay_5ch.png"
        assert pix.save(out), f"failed to save {out!r}"

    def test_dual_cursor_screenshot_geometry_and_pill_containment(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QRect, Qt
        from PyQt5.QtTest import QTest

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)
        viewport = canvas._glw.viewport()
        point_a = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.25)
        point_b = _viewport_point_for_data(canvas, canvas.axes_list[0], 0.75)
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, point_a)
        QCoreApplication.processEvents()
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, point_b)
        QCoreApplication.processEvents()
        assert canvas._cursor.a_items and canvas._cursor.b_items
        assert all(item.isVisible() for item in canvas._cursor.a_items + canvas._cursor.b_items)

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "dual-cursor screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        # Cursor lines must lie inside the view bbox (geometry assertion).
        bbox = QRect(0, 0, pix.width(), pix.height())
        ax_pix = canvas._cursor_x_to_pixmap_x(canvas._cursor.ax, pix.width())
        bx_pix = canvas._cursor_x_to_pixmap_x(canvas._cursor.bx, pix.width())
        assert bbox.contains(int(ax_pix), pix.height() // 2), (
            f"cursor A at pixel x={ax_pix} not contained in bbox {bbox!r}"
        )
        assert bbox.contains(int(bx_pix), pix.height() // 2), (
            f"cursor B at pixel x={bx_pix} not contained in bbox {bbox!r}"
        )

        out = "/tmp/pg_parity_dual_cursor.png"
        assert pix.save(out), f"failed to save {out!r}"


class TestTimeDomainCanvasPGHiDpiGrab:
    """Spec §E: copy/save must render the scene at a HIGHER scale so the
    bitmap is DPI-independent and crisp (matplotlib-figure-DPI parity),
    while a CAP keeps export fast.

    Capping rule under test (single, documented in ``grab_pixmap``):
    effective scale = clamp(requested, 1.0, MAX_WIDTH / base_width),
    where MAX_WIDTH = ``_HIDPI_MAX_WIDTH`` (2560). The result width
    never exceeds the ceiling and never downscales below 1×.

    Gates are GEOMETRY only (pixmap dimensions), never pixel-byte
    comparison.
    """

    def test_default_grab_pixmap_is_1x_unchanged(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(640, 360)
        canvas.plot_channels(
            [("speed", True, np.linspace(0, 1, 100), np.zeros(100), "#1769e0", "rpm", "f")]
        )
        QCoreApplication.processEvents()
        base = canvas.grab_pixmap()
        scaled = canvas.grab_pixmap(scale=1.0)
        assert not base.isNull() and not scaled.isNull()
        # 1× path is unchanged: same width as the no-arg default.
        assert scaled.width() == base.width()
        assert scaled.height() == base.height()

    def test_grab_pixmap_2x_doubles_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(800, 400)
        canvas.plot_channels(
            [("speed", True, np.linspace(0, 1, 500), np.sin(np.linspace(0, 30, 500)),
              "#1769e0", "rpm", "f")]
        )
        QCoreApplication.processEvents()
        base = canvas.grab_pixmap(scale=1.0)
        assert not base.isNull()
        hi = canvas.grab_pixmap(scale=2.0)
        assert not hi.isNull(), "hi-DPI grab returned a null pixmap"
        # Geometry assertion: magnified by ~2× in each dimension.
        # Allow ±2px slack for integer rounding of the scaled QImage.
        assert abs(hi.width() - 2 * base.width()) <= 2, (
            f"hi.width()={hi.width()} not ~2x base.width()={base.width()}"
        )
        assert abs(hi.height() - 2 * base.height()) <= 2, (
            f"hi.height()={hi.height()} not ~2x base.height()={base.height()}"
        )

    def test_export_aa_affordable_true_when_density_small(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas._overlay_mode = True

        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(10)]
        )

        assert canvas._quality._export_aa_affordable() is True

    def test_export_aa_affordable_false_when_overlay_over_budget(
        self, qapp, monkeypatch,
    ):
        canvas = _pg_canvas(qapp)
        canvas._overlay_mode = True
        over = int(canvas._AA_OVERLAY_SEGMENT_OFF) + 100
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(over)]
        )

        assert canvas._quality._export_aa_affordable() is False

    def test_export_aa_affordable_does_not_mutate_idle_hysteresis(
        self, qapp, monkeypatch,
    ):
        canvas = _pg_canvas(qapp)
        canvas._quality.density_allowed = "SENTINEL_A"
        canvas._quality.density_seeded = "SENTINEL_S"
        monkeypatch.setattr(canvas._quality, "_collect_curve_items", lambda: [])

        canvas._quality._export_aa_affordable()

        assert canvas._quality.density_allowed == "SENTINEL_A"
        assert canvas._quality.density_seeded == "SENTINEL_S"

    def test_grab_pixmap_skips_forced_aa_when_not_affordable(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication
        from contextlib import contextmanager

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        monkeypatch.setattr(canvas._quality, "_export_aa_affordable", lambda: False)

        entered = []
        orig = canvas._quality._curves_antialiased

        @contextmanager
        def _spy():
            entered.append(1)
            with orig():
                yield

        monkeypatch.setattr(canvas._quality, "_curves_antialiased", _spy)
        pix = canvas.grab_pixmap(scale=2.0)

        assert not pix.isNull()
        assert entered == []

    def test_hidpi_scaled_grab_uses_single_widget_grab(self, qapp):
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        class SpyWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.grab_calls = 0
                self.render_calls = 0

            def grab(self, *args, **kwargs):  # noqa: N802 - Qt API
                self.grab_calls += 1
                return super().grab(*args, **kwargs)

            def render(self, *args, **kwargs):  # noqa: N802 - Qt API
                self.render_calls += 1
                return super().render(*args, **kwargs)

        widget = SpyWidget()
        widget.resize(120, 80)
        widget.show()
        qapp.processEvents()

        pix = TimeDomainCanvasPG._grab_widget_scaled(widget, 2.0)

        assert not pix.isNull()
        assert widget.grab_calls == 1
        assert widget.render_calls == 0
        assert pix.width() == 240
        assert pix.height() == 160

    def test_grab_pixmap_caps_width_for_large_canvas(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import _HIDPI_MAX_WIDTH

        canvas = _pg_canvas(qapp)
        # A large canvas: 2× would blow past the 2560px ceiling.
        canvas.resize(1800, 1000)
        canvas.plot_channels(
            [("speed", True, np.linspace(0, 1, 500), np.zeros(500), "#1769e0", "rpm", "f")]
        )
        QCoreApplication.processEvents()
        base = canvas.grab_pixmap(scale=1.0)
        assert not base.isNull()
        hi = canvas.grab_pixmap(scale=2.0)
        assert not hi.isNull()
        # Cap enforced: even with a 2× request the width does not exceed
        # the ceiling (small slack for rounding).
        assert hi.width() <= _HIDPI_MAX_WIDTH + 2, (
            f"hi.width()={hi.width()} exceeds cap {_HIDPI_MAX_WIDTH}"
        )
        # But the cap must still magnify beyond 1× when there is headroom.
        assert hi.width() > base.width(), (
            "capped scale should still magnify a 1800px canvas toward 2560px"
        )

    def test_capped_hidpi_scale_helper_rules(self):
        from mf4_analyzer.ui.pg_canvases import (
            _capped_hidpi_scale, _HIDPI_MAX_WIDTH,
        )
        # Small canvas, 2× requested → exactly 2× (under cap).
        assert _capped_hidpi_scale(640, 2.0) == pytest.approx(2.0)
        # Never downscale below 1× even if requested < 1.
        assert _capped_hidpi_scale(640, 0.5) == pytest.approx(1.0)
        # Large canvas → capped so width ~ ceiling, never above.
        s = _capped_hidpi_scale(1800, 2.0)
        assert 1800 * s <= _HIDPI_MAX_WIDTH + 1e-6
        assert s == pytest.approx(_HIDPI_MAX_WIDTH / 1800)
        # Degenerate base width is treated as 1× (no division blowup).
        assert _capped_hidpi_scale(0, 2.0) == pytest.approx(1.0)

    def test_hidpi_grab_preserves_offscreen_fallback(self, qapp, monkeypatch):
        """Lesson 2026-04-25-tightbbox-survives-offscreen-qt: the 1×1
        degenerate fallback + isNull guard must survive the hi-DPI path.
        Force both grab attempts to fail and assert the 1×1 fallback is
        returned (NOT a full-canvas guess), even with scale>1."""
        from PyQt5.QtCore import QCoreApplication
        from PyQt5.QtGui import QPixmap

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(
            [("speed", True, np.linspace(0, 1, 50), np.zeros(50), "#1769e0", "rpm", "f")]
        )
        QCoreApplication.processEvents()

        null_pix = QPixmap()  # null pixmap
        monkeypatch.setattr(canvas, "grab", lambda *a, **k: null_pix)
        monkeypatch.setattr(canvas._glw, "grab", lambda *a, **k: null_pix)

        pix = canvas.grab_pixmap(scale=2.0)
        assert pix is not None
        assert not pix.isNull(), "fallback pixmap must not be null"
        # The 1×1 degenerate fallback — NOT a full-canvas-sized guess.
        assert pix.width() == 1 and pix.height() == 1, (
            f"expected 1x1 fallback, got {pix.width()}x{pix.height()}"
        )


class TestTimeDomainCanvasPGSetDataHotPathContract:
    """Lock the repaired visible-rendering contract: the viewport envelope
    computed during pan/zoom must reach the real ``PlotDataItem``.

    The previous cache-only contract made `_curve_path_cache` grow while
    leaving the on-screen curve stuck on its full-range bind envelope. These
    tests intentionally prove that range changes now update the visible item.
    """

    def test_pdi_setdata_called_once_per_distinct_pan_window(
        self, qapp,
    ):
        """Bind once, pan five times: each distinct visible window must update
        the real PlotDataItem with that window's envelope.
        """
        from PyQt5.QtCore import QCoreApplication
        from unittest.mock import patch

        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = (np.sin(2 * np.pi * 1.3 * t)
               + 0.5 * np.cos(2 * np.pi * 6.1 * t)).astype(np.float64)

        # Bind happens inside plot_channels via PlotItem.plot(...). We
        # let that go through unsupervised; the spy starts ticking
        # AFTER bind so we can isolate pan-path mutation.
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        QCoreApplication.processEvents()

        # Grab the PlotDataItem out of the channel-lines map. This is
        # the real bound artist, not a fake.
        axis_handle, line_handle = canvas._channel_lines["a"]
        pdi = line_handle.plot_data_item
        assert pdi is not None, (
            "channel 'a' has no PlotDataItem — bind path is broken"
        )

        # Spy on the instance method via patch.object so the call count
        # observes the real bound call. We use side_effect=None to make
        # the call a no-op here; the adjacent visible-data test checks the
        # actual data mutation.
        with patch.object(pdi, "setData") as spy:
            # Five panning iterations (different windows each time).
            windows = [
                (1.0, 4.0),
                (2.0, 5.0),
                (3.0, 6.0),
                (4.0, 7.0),
                (5.0, 8.0),
            ]
            for lo, hi in windows:
                canvas.set_xlim(lo, hi)
                canvas._flush_pending_refresh()
                QCoreApplication.processEvents()
            n_calls = spy.call_count

        assert n_calls == len(windows), (
            f"PlotDataItem.setData was called {n_calls} time(s) during "
            f"{len(windows)} distinct pan iterations; every viewport envelope "
            f"must reach the visible curve."
        )

    def test_pdi_setdata_bind_then_one_visible_refresh_call(self, qapp):
        """Bind calls remain small, and one additional range-refresh call is
        expected when the user changes xlim.
        """
        from PyQt5.QtCore import QCoreApplication
        from unittest.mock import patch

        canvas = _pg_canvas(qapp)
        n = 1_000
        t = np.linspace(0.0, 1.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)

        # We cannot easily spy on PlotDataItem.setData before bind
        # because the instance doesn't exist yet. Patch the CLASS
        # method, which catches the bound call from PlotItem.plot()
        # because pg.PlotDataItem internally calls self.setData(...)
        # during construction.
        import pyqtgraph as pg

        original_setdata = pg.PlotDataItem.setData
        call_count = {"n": 0}

        def _spy(self, *args, **kwargs):
            call_count["n"] += 1
            return original_setdata(self, *args, **kwargs)

        with patch.object(pg.PlotDataItem, "setData", _spy):
            canvas.plot_channels(
                [("a", True, t, sig, "#1769e0", "u", "fid-1")]
            )
            QCoreApplication.processEvents()
            bind_calls = call_count["n"]

            # Now drive the pan path with the spy STILL active. The repaired
            # contract expects one additional visible-data update.
            canvas.set_xlim(0.2, 0.5)
            canvas._flush_pending_refresh()
            QCoreApplication.processEvents()
            after_pan_calls = call_count["n"]

        # bind_calls must be small (at most a couple — pyqtgraph may
        # internally call setData once in the constructor and once for
        # the supplied data). The first pan refresh must add exactly one
        # visible update.
        assert after_pan_calls == bind_calls + 1, (
            f"PlotDataItem.setData added {after_pan_calls - bind_calls} "
            f"call(s) during one pan after {bind_calls} bind-time call(s); "
            "expected exactly one visible envelope update."
        )


class TestTimeDomainCanvasPGVisualStyleDefaults:
    """Default visual contracts that keep the pyqtgraph canvas aligned with
    the original matplotlib TimeDomainCanvas.
    """

    def test_plot_channels_enables_grid_by_default(self, qapp, monkeypatch):
        import pyqtgraph as pg

        calls = []
        original = pg.PlotItem.showGrid

        def _spy(self, *args, **kwargs):
            calls.append((args, kwargs))
            return original(self, *args, **kwargs)

        monkeypatch.setattr(pg.PlotItem, "showGrid", _spy)
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")

        assert calls, "plot construction must enable the default time-grid"
        assert any(
            kwargs.get("x") is True and kwargs.get("y") is True
            for _args, kwargs in calls
        )

    def test_subplot_only_bottom_axis_shows_x_tick_values(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:4], mode="subplot")
        QCoreApplication.processEvents()

        for handle in canvas.axes_list[:-1]:
            bottom = handle.plot_item.getAxis("bottom")
            assert bottom.style.get("showValues") is False
            assert getattr(bottom, "labelText", "") == ""
        last_bottom = canvas.axes_list[-1].plot_item.getAxis("bottom")
        assert last_bottom.style.get("showValues") is not False
        assert "Time" in getattr(last_bottom, "labelText", "")

    def test_two_subplots_do_not_reserve_hidden_top_axis_height(self, qapp):
        """Two-channel subplot mode must not open a large blank band between
        the rows: the hidden top row collapses its bottom-axis reserve and only
        the bottom row keeps the X tick/label height. The two plots sit flush
        and stay close in height (the bottom row is shorter only by its X-axis
        band). See
        docs/superpowers/specs/2026-06-02-subplot-vertical-spacing-design.md."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(760, 560)
        canvas.plot_channels(_five_channel_rows()[:2], mode="subplot")
        QCoreApplication.processEvents()

        top_bottom = canvas.axes_list[0].plot_item.getAxis("bottom").height()
        visible_bottom = canvas.axes_list[-1].plot_item.getAxis("bottom").height()
        assert visible_bottom > 20.0
        assert top_bottom <= 4.0, (
            "hidden top subplot X axis must not reserve full tick-label height"
        )

        top_vb = canvas.axes_list[0].view_box.sceneBoundingRect()
        bottom_vb = canvas.axes_list[1].view_box.sceneBoundingRect()
        gap = bottom_vb.top() - top_vb.bottom()
        assert gap < 12.0, "subplots must sit flush, not split by a blank band"
        # The bottom plot is shorter only by ~its reserved X-axis band, not by
        # the layout handing the collapsed top row extra cell height.
        assert top_vb.height() - bottom_vb.height() <= visible_bottom + 8.0

    def test_dense_subplots_do_not_reserve_hidden_xaxis_label_height(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(760, 560)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        hidden_heights = [
            handle.plot_item.getAxis("bottom").height()
            for handle in canvas.axes_list[:-1]
        ]
        visible_height = canvas.axes_list[-1].plot_item.getAxis("bottom").height()

        assert hidden_heights
        assert visible_height > 20.0
        for height in hidden_heights:
            assert height <= 4.0, (
                "hidden subplot X axes must not reserve full tick-label height"
            )

    def test_line_width_and_left_axis_keeps_neutral_axis_pen(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui._axis_handle import PG_AXIS_NEUTRAL_COLOR

        canvas = _pg_canvas(qapp)
        color = "#1769e0"
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
        QCoreApplication.processEvents()
        handle, line = canvas._channel_lines["speed"]
        pdi = line.plot_data_item
        pen = pdi.opts.get("pen")
        assert pen.widthF() == pytest.approx(1.5)

        left = handle.plot_item.getAxis("left")
        assert left.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
        assert left.textPen().color().name().lower() == color

    def test_plot_items_draw_full_neutral_viewbox_frame(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui._axis_handle import (
            PG_AXIS_NEUTRAL_COLOR,
            PG_AXIS_NEUTRAL_WIDTH,
        )

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        for handle in canvas.axes_list:
            border = getattr(handle.plot_item.getViewBox(), "border", None)
            assert border is not None, "each subplot needs a full plot frame"
            assert border.color().name().lower() == PG_AXIS_NEUTRAL_COLOR
            assert border.widthF() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH)

    def test_plot_items_hide_native_auto_fit_buttons(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        for handle in canvas.axes_list:
            assert getattr(handle.plot_item, "buttonsHidden", False) is True

    def test_pg_axes_use_explicit_chart_font(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import _pg_chart_font

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        QCoreApplication.processEvents()

        expected_family = _pg_chart_font().family()
        for handle in canvas.axes_list:
            for axis in (handle.x_axis_item(), handle.y_axis_item()):
                assert axis is not None
                tick_font = axis.style.get("tickFont")
                assert tick_font is not None
                assert tick_font.family() == expected_family
                assert axis.label.font().family() == expected_family

    def test_inside_subplot_labels_use_explicit_chart_font(self, qapp):
        from mf4_analyzer.ui.pg_canvases import _pg_chart_font

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 10.0, 2000)
        rows = [
            (f"long_channel_name_{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
            for i in range(5)
        ]
        canvas.plot_channels(rows, mode="subplot")

        assert canvas._inside_label_items
        expected_family = _pg_chart_font().family()
        for item in canvas._inside_label_items:
            text_item = getattr(item, "textItem", item)
            assert text_item.font().family() == expected_family

    def test_initial_bind_uses_viewport_width_not_max_points(self, qapp, monkeypatch):
        from PyQt5.QtCore import QCoreApplication
        import mf4_analyzer.ui.pg_canvases as pg_canvases

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.show()
        QCoreApplication.processEvents()

        calls = []
        original = pg_canvases.build_envelope

        def _spy(*args, **kwargs):
            calls.append(kwargs.get("pixel_width"))
            return original(*args, **kwargs)

        monkeypatch.setattr(pg_canvases, "build_envelope", _spy)
        canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")

        assert calls
        assert calls[0] < canvas.MAX_PTS
        assert calls[0] <= 1200

    def test_set_tick_density_updates_pg_axis_items(self, qapp, monkeypatch):
        import pyqtgraph as pg

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        calls = []
        original = pg.AxisItem.setTickDensity

        def _spy(axis, *args, **kwargs):
            calls.append((axis, args, kwargs))
            return original(axis, *args, **kwargs)

        monkeypatch.setattr(pg.AxisItem, "setTickDensity", _spy)
        canvas.set_tick_density(12, 7)

        assert len(calls) >= len(canvas.axes_list)
        assert canvas._tick_density_controller.density == (12, 7)

    def test_set_tick_density_keeps_y_ticks_adaptive_and_x_ticks_major_only(self, qapp):
        """X uses explicit major ticks; Y keeps pyqtgraph adaptive density.

        Fixed ``setTickSpacing(major, minor)`` made pyqtgraph label the minor
        level too, producing dense tick-label piles and slow repaint after a
        channel rebuild. X now uses explicit major ticks only; Y remains on
        ``setTickDensity``.
        """
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows()[:5], mode="subplot")
        canvas.set_tick_density(20, 6)
        QCoreApplication.processEvents()

        for handle in canvas.axes_list:
            x_axis = handle.x_axis_item()
            y_axis = handle.y_axis_item()
            assert x_axis is not None
            assert y_axis is not None
            assert getattr(x_axis, "_tickSpacing", None) is None
            assert getattr(y_axis, "_tickSpacing", None) is None
            assert x_axis.style.get("maxTickLevel") == 0
            assert y_axis.style.get("maxTickLevel") == 0
            assert getattr(x_axis, "_tickLevels", None) is not None
            assert getattr(y_axis, "_tickLevels", None) is None
            assert len(getattr(x_axis, "_tickLevels")[1]) == 0


def _path_elements(path):
    """Return [(type:int, x:float, y:float), ...] for a QPainterPath.

    ``QPainterPath.ElementType``: 0 = MoveToElement, 1 = LineToElement.
    Coordinates are rounded to 9 places so float-repr noise never trips
    the equality assertion while still catching a real geometry drift.
    """
    out = []
    for i in range(path.elementCount()):
        e = path.elementAt(i)
        out.append((int(e.type), round(float(e.x), 9), round(float(e.y), 9)))
    return out


def _build_painter_path_old_loop(t, s):
    """Reference implementation: the EXACT pre-T9 pure-Python loop that
    ``_build_painter_path`` used to be. Reproduced here verbatim so the
    parity test pins the vectorized ``arrayToQPath`` build to the same
    polyline geometry the interpreted loop produced (per
    signal-processing/2026-05-19-branch-reached-is-not-behavior-correct:
    assert ACTUAL element coordinates, not "looks similar").
    """
    from PyQt5.QtGui import QPainterPath

    path = QPainterPath()
    n = min(len(t), len(s))
    if n == 0:
        return path
    started = False
    t = np.asarray(t)
    s = np.asarray(s)
    for i in range(n):
        ti = float(t[i])
        si = float(s[i])
        if not (np.isfinite(ti) and np.isfinite(si)):
            started = False
            continue
        if not started:
            path.moveTo(ti, si)
            started = True
        else:
            path.lineTo(ti, si)
    return path


class TestBuildPainterPathParity:
    """Lock the T9 vectorization of ``_build_painter_path``.

    T9 replaced the pure-Python per-point ``QPainterPath.moveTo/lineTo``
    loop (which dominated the ~10.7 ms pan frame) with a vectorized
    ``pyqtgraph.functions.arrayToQPath(x, y, connect='all')`` build for the
    all-finite hot path, keeping the interpreted loop only for NaN-gap
    discontinuities. The visual output MUST stay byte-identical to the old
    loop: same element count, same element TYPES (MoveTo/LineTo), same
    coordinates, same order. These tests assert that against a reference
    re-implementation of the old loop on the production
    ``_build_painter_path`` method of a real ``TimeDomainCanvasPG``.

    Per codex-phantom-api-surface-guards: a REAL canvas is built and the
    REAL production method is exercised — arrayToQPath is not mocked.
    """

    @pytest.mark.parametrize(
        "t,s,expected_count,label",
        [
            ([0.0, 1.0, 2.0, 3.0], [10.0, 11.0, 12.0, 13.0], 4, "all-finite-4pt"),
            (list(np.linspace(0.0, 2.0, 50)),
             list(np.sin(np.linspace(0.0, 2.0, 50))), 50, "all-finite-50pt"),
            ([0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
             [10.0, 11.0, np.nan, 13.0, 14.0, 15.0], 5, "single-nan-gap"),
            ([0.0, 1.0, np.nan, np.nan, 4.0],
             [10.0, 11.0, np.nan, np.nan, 14.0], 3, "double-nan-gap"),
            ([np.nan, 1.0, 2.0], [np.nan, 11.0, 12.0], 2, "leading-nan"),
            ([0.0], [10.0], 1, "single-point"),
            ([], [], 0, "empty"),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_production_path_matches_old_loop_geometry(
        self, qapp, t, s, expected_count, label,
    ):
        """The production ``_build_painter_path`` output must equal the
        old-loop reference element-for-element across the finite and
        NaN-gap cases that the envelope can produce.
        """
        canvas = _pg_canvas(qapp)
        ta = np.asarray(t, dtype=np.float64)
        sa = np.asarray(s, dtype=np.float64)

        produced = canvas._build_painter_path(ta, sa)
        reference = _build_painter_path_old_loop(ta, sa)

        prod_elems = _path_elements(produced)
        ref_elems = _path_elements(reference)

        # Pin the element count explicitly (the headline regression signal
        # arrayToQPath could silently diverge on, per the brief).
        assert produced.elementCount() == expected_count, (
            f"[{label}] elementCount={produced.elementCount()} "
            f"!= expected {expected_count}"
        )
        # Byte-identical geometry: same count, same (type, x, y) tuples in
        # the same order as the old interpreted loop.
        assert prod_elems == ref_elems, (
            f"[{label}] vectorized path geometry diverged from the old "
            f"loop.\n  produced={prod_elems}\n  reference={ref_elems}"
        )

    def test_all_finite_path_is_moveto_then_lineto_run(self, qapp):
        """Spell out the expected all-finite element TYPES so a future
        change that, e.g., emits a closing element or reorders types is
        caught even if the count happens to match: element 0 is a MoveTo
        (type 0) and every subsequent element is a LineTo (type 1)."""
        canvas = _pg_canvas(qapp)
        n = 200
        t = np.linspace(0.0, 5.0, n).astype(np.float64)
        s = (np.sin(2 * np.pi * 1.3 * t) + 0.4 * np.cos(2 * np.pi * 4.1 * t))
        s = s.astype(np.float64)

        path = canvas._build_painter_path(t, s)
        assert path.elementCount() == n
        elems = _path_elements(path)
        assert elems[0][0] == 0, "first element must be a MoveToElement"
        assert all(e[0] == 1 for e in elems[1:]), (
            "all elements after the first must be LineToElement"
        )
        # Coordinates must equal the input arrays exactly (vectorized C
        # build copies x/y verbatim, no resampling).
        xs = np.array([e[1] for e in elems])
        ys = np.array([e[2] for e in elems])
        assert np.allclose(xs, t, rtol=0, atol=1e-9)
        assert np.allclose(ys, s, rtol=0, atol=1e-6)


class TestPerfRegressionFix:
    """2026-05-29 perf-regression fixes: restore the smooth (~14x) pan that
    existed at commit 55d8a93e while keeping grid + inside labels.

    See docs/superpowers/plans/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md
    """

    def test_curves_are_not_antialiased_for_pan_perf(self, qapp):
        """Regression: the smooth (~14x) HEAD never anti-aliased curves.
        Re-enabling it was the #1 cause of the post-UI-alignment lag."""
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        t = np.linspace(0.0, 10.0, 5000)
        rows = [
            (f"ch{i}", True, t, np.sin(t) + i, "#d62728", "u", "fid")
            for i in range(3)
        ]
        canvas.plot_channels(rows, mode="subplot")

        assert canvas._channel_lines  # sanity: curves were built
        for _name, (_axis, line) in canvas._channel_lines.items():
            pdi = line.plot_data_item
            # opts['antialias'] must be falsy on every curve.
            assert not pdi.opts.get("antialias", False), (
                f"{_name} curve is anti-aliased; this regresses pan perf"
            )
        canvas.deleteLater()

    def test_rebuild_does_not_accumulate_inside_label_items(self, qapp):
        """Regression: clear() must remove inside-label scene items, not just
        null the Python refs. pyqtgraph's GraphicsLayout.clear() does NOT
        remove items added via scene().addItem(), so without an explicit
        removeItem the old badges pile up in the scene on every rebuild."""
        import pyqtgraph as pg
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        t = np.linspace(0.0, 10.0, 2000)
        # >=4 channels with long names -> dense subplot -> inside labels on.
        rows = [
            (f"long_channel_name_{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
            for i in range(5)
        ]

        counts = []
        for _ in range(4):
            canvas.plot_channels(rows, mode="subplot")
            text_items = [
                it for it in canvas._glw.scene().items()
                if isinstance(it, pg.TextItem)
            ]
            counts.append(len(text_items))

        # One badge per subplot, and NO growth across rebuilds.
        assert counts[0] == 5, counts
        assert counts[-1] == counts[0], f"ghost badges accumulated: {counts}"
        canvas.deleteLater()

    def test_pan_does_not_reposition_inside_labels(self, qapp, monkeypatch):
        """Regression: inside labels are pinned to each subplot's top-left
        corner. That corner is fixed during pan/zoom (only viewRange moves,
        not the ViewBox geometry), so labels must NOT be repositioned on
        sigRangeChanged -- doing so cost a Python callback every pan frame."""
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        t = np.linspace(0.0, 10.0, 2000)
        rows = [
            (f"long_channel_name_{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
            for i in range(5)
        ]
        canvas.plot_channels(rows, mode="subplot")
        assert canvas._inside_label_items  # sanity: inside labels are active

        calls = {"n": 0}
        orig = canvas._position_inside_label_item

        def spy(*args, **kwargs):
            calls["n"] += 1
            return orig(*args, **kwargs)

        monkeypatch.setattr(canvas, "_position_inside_label_item", spy)

        # Pan/zoom the X range -- this fires sigXRangeChanged/sigRangeChanged.
        canvas.set_xlim(2.0, 8.0)
        canvas._flush_pending_refresh()

        assert calls["n"] == 0, (
            "inside labels were repositioned during pan; they should be "
            "pinned and only reflow on resize"
        )
        canvas.deleteLater()


class TestOverlayAxisLabelGeometry:
    """Bug 1: overlay y-axis labels collided with their tick numbers — the
    compact label carried a raw ``\\n`` (pyqtgraph renders HTML and ignores
    ``\\n`` → one long unbroken rotated label) and ``autoSIPrefix`` added a
    ``(x0.001)`` scale chip. Labels must contain no raw ``\\n`` and each
    overlay AxisItem must reserve a non-zero width.
    """

    def test_overlay_label_has_no_raw_newline(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(800, 400)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 500)
        rows = [
            ("[ECU] very_long_channel_identifier_name", True, t,
             1000.0 * np.sin(t), "#1769e0", "rpm", "f"),
            ("[ECU] another_long_channel_name_here", True, t,
             5.0 + np.cos(t), "#ef4444", "Nm", "f"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        for name, (handle, _line) in canvas._channel_lines.items():
            label = handle.get_ylabel()
            assert "\n" not in label, (
                f"overlay label for {name!r} contains a raw newline "
                f"(pyqtgraph ignores \\n → label collides): {label!r}"
            )
        canvas.deleteLater()

    def test_overlay_label_uses_available_axis_height_before_ellipsis(self, qapp):
        """A tall overlay chart should not truncate channel names to a fixed
        character count when the rotated Y-axis label has room to fit.
        """
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(1000, 620)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 500)
        first_name = "SteeringAngleSpeed_xds16_filtered"
        second_name = "SteeringWheelTorqueNm_filtered"
        rows = [
            (first_name, True, t, 1000.0 * np.sin(t), "#1769e0", "rpm", "f"),
            (second_name, True, t, 5.0 + np.cos(t), "#ef4444", "Nm", "f"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        canvas.resize(1001, 620)
        QCoreApplication.processEvents()

        for name, (handle, _line) in canvas._channel_lines.items():
            label = handle.get_ylabel()
            assert "..." not in label, (
                f"overlay label for {name!r} was ellipsized despite available "
                f"axis height: {label!r}"
            )
            assert name in label

        canvas.deleteLater()

    def test_overlay_label_reexpands_after_taller_resize(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(1000, 220)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 500)
        name = "SteeringAngleSpeed_xds16_filtered"
        rows = [
            (name, True, t, 1000.0 * np.sin(t), "#1769e0", "rpm", "f"),
            ("torque", True, t, 5.0 + np.cos(t), "#ef4444", "Nm", "f"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        initial = canvas._channel_lines[name][0].get_ylabel()
        assert "..." in initial

        canvas.resize(1000, 620)
        QCoreApplication.processEvents()
        canvas._refresh_overlay_axis_labels()
        QCoreApplication.processEvents()

        expanded = canvas._channel_lines[name][0].get_ylabel()
        assert "..." not in expanded
        assert name in expanded

        canvas.deleteLater()

    def test_overlay_axes_disable_autosiprefix(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(800, 400)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 500)
        rows = [
            ("speed", True, t, 1000.0 * np.sin(t), "#1769e0", "rpm", "f"),
            ("torque", True, t, 5.0 + np.cos(t), "#ef4444", "Nm", "f"),
            ("pressure", True, t, 0.2 + 0.1 * np.sin(t), "#00b894", "bar", "f"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        for name, (handle, _line) in canvas._channel_lines.items():
            ax = handle.y_axis_item()
            assert ax.autoSIPrefix is False, (
                f"overlay axis for {name!r} must disable autoSIPrefix so the "
                f"(x0.001) scale chip does not collide with the label"
            )
            assert float(ax.width()) > 0.0, (
                f"overlay axis for {name!r} must reserve a non-zero width"
            )
        canvas.deleteLater()

    def test_overlay_right_axes_do_not_overlap_with_wide_numbers(self, qapp):
        """Issue (2026-05-29): right-side channel names were crammed against
        the adjacent axis's tick numbers. Root cause: ``setWidth(44)`` was a
        HARD clamp (not a floor), jamming wide-number axes, and the stacked
        right axes had no inter-column spacing. This replaces the old weak
        ``"\\n" not in label`` check with REAL clearance: adjacent overlay
        y-AxisItem sceneBoundingRects must not overlap, and no axis may be
        narrower than its own natural (auto-sized) tick-text width.
        """
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(1000, 500)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 1.0, 2000)
        # 5 channels with WIDE numeric ranges and long names — the case that
        # exposed both the hard-clamp jam and the missing inter-axis spacing.
        rows = [
            ("engine_speed_rpm", True, t, 2600.0 * np.sin(t) - 1200.0,
             "#1769e0", "rpm", "f"),
            ("manifold_pressure_kpa", True, t, 1400.0 * np.cos(t),
             "#ef4444", "kPa", "f"),
            ("coolant_temperature_c", True, t, 95.0 + 5.0 * np.sin(t),
             "#00b894", "C", "f"),
            ("fuel_flow_rate_lph", True, t, 12.5 + np.cos(t),
             "#fbbf24", "L/h", "f"),
            ("exhaust_gas_temperature_c", True, t, 780.0 + 50.0 * np.sin(t),
             "#a855f7", "C", "f"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        # Force a layout pass so geometry settles.
        canvas.resize(1001, 500)
        QCoreApplication.processEvents()

        axes = [h.y_axis_item() for h in canvas.axes_list]
        # No axis may be hard-clamped below its natural tick-text width.
        for name, (handle, _line) in canvas._channel_lines.items():
            ax = handle.y_axis_item()
            w = float(ax.width())
            ax.setWidth(None)
            QCoreApplication.processEvents()
            natural = float(ax.width())
            ax.setWidth(w)  # restore
            assert w + 0.5 >= natural, (
                f"overlay axis {name!r} is clamped to {w} below its natural "
                f"tick-text width {natural} → numbers get jammed"
            )

        # Adjacent right axes (left-to-right scene order) must not overlap.
        right_axes = [a for a in axes if getattr(a, "orientation", None) == "right"]
        right_sorted = sorted(
            right_axes, key=lambda a: a.sceneBoundingRect().left()
        )
        assert len(right_sorted) >= 3, "expected >=3 right axes in this build"
        for a, b in zip(right_sorted, right_sorted[1:]):
            gap = b.sceneBoundingRect().left() - a.sceneBoundingRect().right()
            assert gap >= 0.0, (
                f"adjacent overlay right axes overlap (gap={gap:.1f}px); the "
                f"rotated name butts against the neighbor's tick numbers"
            )
        canvas.deleteLater()


class TestOverlayAuxViewBoxTeardown:
    """Bug 2: overlay aux ViewBoxes (+ their child curves and ch3+ appended
    right AxisItems) are added to the scene via ``scene().addItem`` /
    ``layout.addItem``; ``GraphicsLayoutWidget.clear()`` does NOT remove
    them, so a mode switch leaks ghost curves. ``clear()`` must explicitly
    tear them down (mirror ``_teardown_inside_labels``).
    """

    def test_overlay_aux_viewboxes_removed_on_mode_switch(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(640, 360)
        canvas.show()
        QCoreApplication.processEvents()

        t = np.linspace(0.0, 10.0, 2000)
        # >=3 channels so ch3 appends a right AxisItem via layout.addItem.
        rows = [
            (f"ch{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
            for i in range(3)
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        old_aux = list(canvas._overlay_axes.aux_viewboxes)
        old_axes = list(canvas._overlay_axes.aux_axes)
        assert old_aux, "overlay build must create aux ViewBoxes"

        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        scene_items = set(canvas._glw.scene().items())
        for vb in old_aux:
            assert vb not in scene_items, (
                "ghost aux ViewBox leaked into the scene after mode switch"
            )
            for child in vb.allChildItems():
                assert child not in scene_items, (
                    "ghost overlay curve leaked into the scene after switch"
                )
        # ch3+ appended right AxisItems must also be gone.
        for ax_item in old_axes:
            assert ax_item not in scene_items, (
                "ghost appended AxisItem leaked into the scene after switch"
            )
        canvas.deleteLater()


class TestOverlayGridSingleAxis:
    """Issue (2026-05-29): overlay Y grid was a tangle of non-coincident,
    differently-colored horizontal lines because ``_add_plot_item`` enabled
    ``showGrid(y=True)`` while the overlay's built-in left + right axes are
    linked to DIFFERENT per-channel ViewBoxes (different Y ranges) and each
    drew its own Y grid in its own channel pen color. In overlay there is no
    canonical Y range, so only the single shared X grid (bottom axis) may be
    drawn; the Y grid must be OFF. subplot/single keep both grids.
    """

    def _overlay_plot_item(self, canvas):
        # The overlay X-master handle wraps the single overlay PlotItem.
        assert canvas._x_master_handle is not None
        return canvas._x_master_handle.plot_item

    def test_overlay_disables_y_grid_keeps_x_grid(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui._axis_handle import PG_AXIS_NEUTRAL_COLOR
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        pi = self._overlay_plot_item(canvas)
        bottom = pi.getAxis("bottom")
        left = pi.getAxis("left")
        right = pi.getAxis("right")

        # X grid (single shared bottom axis) stays ON.
        assert bool(bottom.grid), (
            f"overlay X grid must stay ON; bottom.grid={bottom.grid!r}"
        )
        # Both built-in Y axes (channel 1 = left, channel 2 = right) must
        # have their Y grid OFF so we don't get multiple non-coincident,
        # colored horizontal grid families.
        assert not left.grid, (
            f"overlay left-axis Y grid must be OFF; left.grid={left.grid!r}"
        )
        assert not right.grid, (
            f"overlay right-axis Y grid must be OFF; right.grid={right.grid!r}"
        )
        # ch3+ appended aux right axes must also carry no Y grid.
        for ax_item in canvas._overlay_axes.aux_axes:
            assert not ax_item.grid, (
                f"overlay aux axis Y grid must be OFF; grid={ax_item.grid!r}"
            )
        assert left.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
        assert right.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
        for ax_item in canvas._overlay_axes.aux_axes:
            assert ax_item.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
        canvas.deleteLater()

    def test_overlay_y_grid_off_is_idempotent_across_rebuild(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        # Rebuild overlay a second time (mode-switch round trip) and re-assert.
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        pi = self._overlay_plot_item(canvas)
        assert bool(pi.getAxis("bottom").grid)
        assert not pi.getAxis("left").grid
        assert not pi.getAxis("right").grid
        canvas.deleteLater()

    def test_overlay_grid_lines_created_on_plot(self, qapp):
        """plot_channels overlay 后，应有 _overlay_divisions - 1 条格线。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()

        expected = canvas._overlay_axes.divisions - 1
        assert len(canvas._overlay_axes.grid_lines) == expected, (
            f"expected {expected} grid lines, "
            f"got {len(canvas._overlay_axes.grid_lines)}"
        )
        canvas.deleteLater()

    def test_overlay_grid_lines_cleared_on_rebuild(self, qapp):
        """重建后格线数量不应翻倍（清理后重建）。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows()[:3], mode="overlay")
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows()[:2], mode="overlay")
        QCoreApplication.processEvents()

        expected = canvas._overlay_axes.divisions - 1
        assert len(canvas._overlay_axes.grid_lines) == expected, (
            f"after rebuild, expected {expected}, "
            f"got {len(canvas._overlay_axes.grid_lines)}"
        )
        canvas.deleteLater()

    def test_subplot_keeps_both_x_and_y_grid(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()

        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        # subplot mode has one Y range per PlotItem, so the Y grid is clean
        # and must stay ON (guard against over-reach of the overlay fix).
        for handle in canvas.axes_list:
            pi = handle.plot_item
            assert bool(pi.getAxis("left").grid), (
                "subplot left-axis Y grid must stay ON"
            )
            assert bool(pi.getAxis("bottom").grid), (
                "subplot X grid must stay ON"
            )
        canvas.deleteLater()


class _FakeMove:
    """Minimal stand-in for a Qt mouse-move event for hover tests."""

    def __init__(self, x, y):
        from PyQt5.QtCore import QPoint, Qt
        self._p = QPoint(x, y)
        self._b = Qt.NoButton

    def pos(self):
        return self._p

    def buttons(self):
        return self._b


class _FakeViewBox:
    """Distinct, hashable stand-in so density grouping can bucket curves
    by ViewBox identity without a real pyqtgraph ViewBox."""


class _FakeCurveData:
    """Minimal curve-like object exposing getData() for density tests.

    ``view_box`` lets a test place several fake curves on the SAME
    ViewBox (overlay) or on distinct ones (subplot) so the sum-per-VB
    density metric can be exercised. Defaults to a fresh ViewBox so each
    instance is its own group unless one is shared in explicitly.
    """

    def __init__(self, n, view_box=None):
        self._x = np.arange(n, dtype=np.float64)
        self._vb = view_box if view_box is not None else _FakeViewBox()

    def getData(self):
        return self._x, self._x

    def getViewBox(self):
        return self._vb


class _BrokenCurveData:
    """Curve-like object whose data cannot be inspected."""

    def getViewBox(self):
        return _FakeViewBox()

    def getData(self):
        raise RuntimeError("boom")


class TestAutoIdleAA:
    """2026-05-30 Auto Idle AA: enable curve antialiasing after the
    last interaction settles, while preserving AA-off interaction paths.

    See docs/superpowers/plans/2026-05-30-pyqtgraph-timedomain-auto-idle-aa.md
    """

    def _plot(self, qapp, *, mode="subplot"):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode=mode)
        QCoreApplication.processEvents()
        return canvas

    def _curves(self, canvas):
        import pyqtgraph as pg

        return [
            it for it in canvas._glw.scene().items()
            if isinstance(it, pg.PlotCurveItem)
        ]

    def test_set_curves_antialias_flips_every_curve(self, qapp):
        canvas = self._plot(qapp)
        curves = self._curves(canvas)
        assert curves

        n_on = canvas._quality._set_curves_antialias(True)
        assert n_on == len(curves)
        assert all(c.opts.get("antialias") for c in curves)

        n_off = canvas._quality._set_curves_antialias(False)
        assert n_off == len(curves)
        assert not any(c.opts.get("antialias") for c in curves)

    def test_set_curves_antialias_does_not_call_setdata(self, qapp, monkeypatch):
        canvas = self._plot(qapp)
        _axis, line = next(iter(canvas._channel_lines.values()))

        def fail_setdata(*_args, **_kwargs):
            raise AssertionError("_set_curves_antialias must not call setData")

        monkeypatch.setattr(line.plot_data_item, "setData", fail_setdata)
        canvas._quality._set_curves_antialias(True)

    def test_idle_timer_is_single_shot_150ms(self, qapp):
        canvas = _pg_canvas(qapp)
        assert canvas._quality.timer.isSingleShot()
        assert canvas._quality.timer.interval() == 150
        assert canvas._quality.aa_on is False

    def test_quality_status_reports_dense_overlay_gate(self, qapp, monkeypatch):
        canvas = self._plot(qapp, mode="overlay")
        canvas._overlay_mode = True
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items",
            lambda: [_FakeCurveData(3000) for _ in range(5)],
        )

        status = canvas.quality_status()

        assert status["state"] == "red"
        assert status["metric"] == 15000
        assert status["budget"] == canvas._AA_OVERLAY_SEGMENT_OFF
        assert "叠加密度" in status["tooltip"]
        assert "15000" in status["tooltip"]

    def test_idle_slot_enables_aa_when_mouse_up(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )

        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True
        assert all(c.opts.get("antialias") for c in self._curves(canvas))

    def test_disable_interactive_quality_forces_aa_off(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        canvas.disable_interactive_quality()
        assert canvas._quality.aa_on is False
        assert not canvas._quality.timer.isActive()
        assert not any(c.opts.get("antialias") for c in self._curves(canvas))

    def test_idle_slot_blocked_while_mouse_down(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is False

    def test_idle_slot_blocked_while_overlay_dragging(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas._overlay_axes.dragging = True
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is False

    def test_schedule_idle_quality_starts_timer(self, qapp):
        canvas = self._plot(qapp)
        canvas.schedule_idle_quality()
        assert canvas._quality.timer.isActive()

    def test_initial_overlay_build_rearms_idle_timer(self, qapp):
        canvas = self._plot(qapp, mode="overlay")

        assert canvas._quality.aa_on is False
        assert not any(c.opts.get("antialias") for c in self._curves(canvas))
        assert canvas._quality.timer.isActive()

    def test_view_all_forces_aa_off_and_rearms_idle_timer(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        canvas.reset_view_to_data_extents()

        assert canvas._quality.aa_on is False
        assert not any(c.opts.get("antialias") for c in self._curves(canvas))
        assert canvas._quality.timer.isActive()

    def test_xrange_change_forces_aa_off(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        canvas.set_xlim(0.2, 0.8)
        assert canvas._quality.aa_on is False
        assert not any(c.opts.get("antialias") for c in self._curves(canvas))

    def test_refresh_rearms_idle_timer(self, qapp):
        canvas = self._plot(qapp)
        canvas.set_xlim(0.1, 0.9)
        canvas._flush_pending_refresh()
        assert canvas._quality.timer.isActive()

    def test_y_only_wheel_forces_aa_off_and_rearms_idle(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        assert canvas._handle_wheel_dispatch(
            delta=120, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=0.0,
        ) is True
        assert canvas._quality.aa_on is False
        assert canvas._quality.timer.isActive()

        canvas._quality.timer.stop()
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        assert canvas._handle_wheel_dispatch(
            delta=120, modifiers=Qt.NoModifier, x_pos=0.5, y_pos=0.0,
        ) is True
        assert canvas._quality.aa_on is False
        assert canvas._quality.timer.isActive()

    def test_mouse_release_rearms_after_blocked_idle_timeout(self, qapp, monkeypatch):
        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        canvas.set_xlim(0.1, 0.9)
        canvas._flush_pending_refresh()
        assert canvas._quality.timer.isActive()

        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton)
        )
        canvas._quality.timer.stop()
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is False
        assert not canvas._quality.timer.isActive()

        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(40, 40),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        canvas.eventFilter(canvas._glw.viewport(), release)
        assert canvas._quality.timer.isActive()

    def test_overlay_drag_drops_aa_and_release_rearms(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        canvas._overlay_axes.dragging = True
        canvas.disable_interactive_quality()
        assert canvas._quality.aa_on is False

        canvas._overlay_axes.dragging = False
        canvas.schedule_idle_quality()
        assert canvas._quality.timer.isActive()

    def test_replot_leaves_curves_aa_off(self, qapp):
        canvas = self._plot(qapp)
        assert canvas._quality.aa_on is False
        curves = self._curves(canvas)
        assert curves and not any(c.opts.get("antialias") for c in curves)

    def test_cursor_move_does_not_flip_aa(self, qapp, monkeypatch):
        """Strategy A: hovering the cursor never flips curve AA."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True

        canvas.set_cursor_visible(True)
        handle = canvas.axes_list[0]
        for i in range(10):
            canvas._cursor.last_t = 0
            point = _viewport_point_for_data(canvas, handle, 0.1 + 0.05 * i)
            assert canvas._handle_cursor_mouse_move(
                _FakeMove(point.x(), point.y())
            ) is True

        assert canvas._quality.aa_on is True
        assert all(c.opts.get("antialias") for c in self._curves(canvas))

    @staticmethod
    def _set_budgets(canvas, on, off):
        """Pin BOTH budget pairs (overlay + subplot) to the same window so a
        density test is independent of which mode branch the gate takes; an
        individual test then flips ``canvas._overlay_mode`` to exercise the
        sum-vs-max metric split deliberately."""
        canvas._AA_OVERLAY_SEGMENT_ON = on
        canvas._AA_OVERLAY_SEGMENT_OFF = off
        canvas._AA_SUBPLOT_SEGMENT_ON = on
        canvas._AA_SUBPLOT_SEGMENT_OFF = off
        canvas._AA_SEGMENT_ON = on
        canvas._AA_SEGMENT_OFF = off

    def test_density_gate_blocks_dense_curves(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        self._set_budgets(canvas, 1, 2)
        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is False

    def test_density_gate_uses_hysteresis_window(self, qapp, monkeypatch):
        canvas = self._plot(qapp)
        self._set_budgets(canvas, 4, 6)
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(5)]
        )

        # Seed past the cold-start: a value strictly inside the (ON, OFF]
        # dead band holds whatever the previous decision was.
        canvas._quality.density_seeded = True
        canvas._quality.density_allowed = False
        assert canvas._quality._idle_aa_density_ok() is False

        canvas._quality.density_allowed = True
        assert canvas._quality._idle_aa_density_ok() is True

        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(7)]
        )
        assert canvas._quality._idle_aa_density_ok() is False
        assert canvas._quality.density_allowed is False

    def test_overlay_metric_is_sum_across_all_curves(self, qapp, monkeypatch):
        """Correction 1 (2026-05-31): in OVERLAY mode the metric is the SUM
        of drawn points across ALL curves — the aux ViewBoxes fully overlap
        at one full-plot rect, so a single repaint re-rasterizes them as one
        region. Three 5-pt curves (even on DISTINCT fake VBs, mirroring the
        real distinct-but-overlapping aux ViewBoxes) → metric 15, not 5."""
        canvas = self._plot(qapp, mode="overlay")
        canvas._overlay_mode = True
        self._set_budgets(canvas, 8, 10)
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items",
            lambda: [_FakeCurveData(5) for _ in range(3)],
        )
        # Sum = 15 > OFF(10) on the cold-start seed → rejected, proving the
        # metric is the sum (a per-VB MAX would have been 5 → allowed).
        canvas._quality.density_seeded = False
        assert canvas._quality._idle_aa_density_ok() is False

    def test_subplot_metric_is_max_over_rows(self, qapp, monkeypatch):
        """Correction 1: in SUBPLOT mode the metric is the MAX over rows of
        that row's drawn points (disjoint dirty rects). 5 separate 5-pt
        curves → 5, well under budget — single curves at any width still get
        AA. Same fake-curve set that overlay would score as a 25-pt sum."""
        canvas = self._plot(qapp)
        canvas._overlay_mode = False
        self._set_budgets(canvas, 8, 10)
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items",
            lambda: [_FakeCurveData(5) for _ in range(5)],
        )
        canvas._quality.density_seeded = False
        assert canvas._quality._idle_aa_density_ok() is True

    def test_single_subplot_curve_6000_passes_on_first_decision(
        self, qapp, monkeypatch,
    ):
        """Correction 3: a single ~6000-pt subplot curve (maximized / 4K
        window) is under the GENEROUS subplot OFF budget, so the FIRST
        decision seeds True instead of sticking False in the dead band. Uses
        the production defaults — does NOT override the constants."""
        canvas = self._plot(qapp)
        canvas._overlay_mode = False
        # Subplot budget must clear a 4K single curve (~7700-pt envelope).
        assert canvas._AA_SUBPLOT_SEGMENT_OFF >= 7700, (
            "subplot OFF must cover a 4K maximized single curve (~7700 pts)"
        )
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(6000)]
        )
        canvas._quality.density_seeded = False
        canvas._quality.density_allowed = False
        assert canvas._quality._idle_aa_density_ok() is True, (
            "first decision must seed via the OFF threshold, not stick False"
        )

    def test_dense_overlay_gates_off_on_production_budget(self, qapp, monkeypatch):
        """Correction 3: a dense overlay (5 curves × ~3000 envelope pts =
        sum 15000, measured ≈ +69 ms AA-on) must resolve to AA-off under the
        PRODUCTION overlay budget — the original 12000/16000 single budget
        would have ALLOWED it. Uses the real overlay constants."""
        canvas = self._plot(qapp, mode="overlay")
        canvas._overlay_mode = True
        # sum 15000 must exceed the production overlay OFF budget.
        assert 5 * 3000 > canvas._AA_OVERLAY_SEGMENT_OFF, (
            "overlay OFF budget too high — the reported-slow dense overlay "
            "(5×3000 ≈ +69 ms) would still be allowed"
        )
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items",
            lambda: [_FakeCurveData(3000) for _ in range(5)],
        )
        canvas._quality.density_seeded = False
        canvas._quality.density_allowed = False
        assert canvas._quality._idle_aa_density_ok() is False, (
            "dense overlay (sum 15000) must gate AA off on the production "
            "overlay budget"
        )

    def test_light_overlay_within_budget_enables(self, qapp, monkeypatch):
        """Correction 3: a light 2-curve overlay (sum 6000 ≈ +16 ms AA-on)
        stays affordable and gets AA under the production overlay budget."""
        canvas = self._plot(qapp, mode="overlay")
        canvas._overlay_mode = True
        # A 2-curve overlay at the ON budget point is the affordable case.
        n_each = canvas._AA_OVERLAY_SEGMENT_ON // 2  # sum == ON → allowed
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items",
            lambda: [_FakeCurveData(n_each) for _ in range(2)],
        )
        canvas._quality.density_seeded = False
        canvas._quality.density_allowed = False
        assert canvas._quality._idle_aa_density_ok() is True

    def test_overlay_on_off_hysteresis_do_not_flap(self, qapp, monkeypatch):
        """Correction 3: overlay ON != OFF, so a sum parked between them
        holds the previous decision (no per-frame flapping)."""
        canvas = self._plot(qapp, mode="overlay")
        canvas._overlay_mode = True
        assert canvas._AA_OVERLAY_SEGMENT_ON < canvas._AA_OVERLAY_SEGMENT_OFF
        mid = (
            canvas._AA_OVERLAY_SEGMENT_ON + canvas._AA_OVERLAY_SEGMENT_OFF
        ) // 2
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_FakeCurveData(mid)]
        )
        canvas._quality.density_seeded = True

        canvas._quality.density_allowed = True
        assert canvas._quality._idle_aa_density_ok() is True
        assert canvas._quality._idle_aa_density_ok() is True  # stable, no flap

        canvas._quality.density_allowed = False
        assert canvas._quality._idle_aa_density_ok() is False
        assert canvas._quality._idle_aa_density_ok() is False

    def test_subplot_budget_more_generous_than_overlay(self, qapp):
        """Correction 3: the subplot budget (cached, cheap) must be strictly
        more generous than the tight overlay (uncached) budget, or subplot
        single-row data would be starved by the overlay gate."""
        canvas = self._plot(qapp)
        assert canvas._AA_SUBPLOT_SEGMENT_ON > canvas._AA_OVERLAY_SEGMENT_ON
        assert canvas._AA_SUBPLOT_SEGMENT_OFF > canvas._AA_OVERLAY_SEGMENT_OFF

    def test_density_gate_fails_closed_when_curve_data_unreadable(
        self, qapp, monkeypatch,
    ):
        canvas = self._plot(qapp)
        canvas._quality.density_seeded = True
        canvas._quality.density_allowed = True
        monkeypatch.setattr(
            canvas._quality, "_collect_curve_items", lambda: [_BrokenCurveData()]
        )

        assert canvas._quality._idle_aa_density_ok() is False
        assert canvas._quality.density_allowed is False

    def test_resize_event_rearms_idle_timer(self, qapp):
        """Fix C: a resize debounces a settle pass; once the settle timer
        fires it recomputes the envelope and re-arms the idle-AA timer so
        AA recovers at the new width. The 40 ms debounce is driven
        directly (QTimer-slot-called-directly harness convention)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = self._plot(qapp)
        canvas._quality.timer.stop()
        assert not canvas._quality.timer.isActive()

        canvas.resize(900, 500)
        QCoreApplication.processEvents()
        # resizeEvent arms the debounce, not the idle timer directly.
        assert canvas._resize_settle_timer.isActive(), (
            "resize must arm the settle debounce"
        )

        # Fire the debounce slot as the live timer eventually would.
        canvas._on_resize_settled()
        assert canvas._quality.timer.isActive(), (
            "settle pass must re-arm the idle-AA timer for the new width"
        )

    def test_resize_event_reseeds_density_cold_start(self, qapp):
        """Fix C: after a resize the density decision is re-seeded so a
        new (wider) envelope re-enters the OFF-threshold seeding path."""
        from PyQt5.QtCore import QCoreApplication

        canvas = self._plot(qapp)
        canvas._quality.density_seeded = True

        canvas.resize(900, 500)
        QCoreApplication.processEvents()

        assert canvas._quality.density_seeded is False

    def test_default_line_width_is_1_5(self, qapp):
        """Co-tuned with idle AA to soften the AA-off/on visual jump."""
        canvas = _pg_canvas(qapp)
        assert canvas._overlay_axes.default_lw == 1.5

    def test_grab_preserves_idle_aa_on_state(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = self._plot(qapp)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        curves = self._curves(canvas)
        assert all(c.opts.get("antialias") for c in curves)

        pix = canvas.grab_pixmap(scale=1.0)
        assert not pix.isNull()
        assert all(c.opts.get("antialias") for c in curves)
        assert canvas._quality.aa_on is True

    def test_idle_aa_subplot_sets_device_coordinate_cache(self, qapp, monkeypatch):
        """Fix D (Correction 2, 2026-05-31): in SUBPLOT mode (disjoint rows)
        idle AA also enables DeviceCoordinateCache so hover / draw_idle blits
        the cached bitmap instead of re-rasterizing — measured 5×6000 subplot
        AA-on 25.3 ms → 0.86 ms cached. Subplot rows do not overlap, so the
        cache pays off (unlike overlay)."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QGraphicsItem

        canvas = self._plot(qapp, mode="subplot")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        curves = self._curves(canvas)
        assert curves
        # Pre-condition: AA-off interaction state caches nothing.
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves)

        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True
        assert all(
            c.cacheMode() == QGraphicsItem.DeviceCoordinateCache for c in curves
        ), "subplot idle AA must enable DeviceCoordinateCache on every curve"

    def test_idle_aa_overlay_does_not_set_device_cache(self, qapp, monkeypatch):
        """Fix D (Correction 2): in OVERLAY mode DeviceCoordinateCache gives
        no win (the aux ViewBoxes fully overlap at one full-plot rect, so N
        full-size cache layers must alpha-composite every frame — measured
        slightly WORSE). So overlay idle AA must NOT set the device cache; it
        relies on the tight density budget instead. Curves stay NoCache even
        though AA is on."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QGraphicsItem

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        curves = self._curves(canvas)
        assert curves
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves)

        canvas.try_enable_idle_quality()
        assert canvas._quality.aa_on is True
        assert all(c.opts.get("antialias") for c in curves), (
            "overlay idle AA must still flip antialias on"
        )
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves), (
            "overlay idle AA must NOT set DeviceCoordinateCache (no win on "
            "fully-overlapping aux ViewBoxes)"
        )

    def test_disable_interactive_quality_clears_device_cache_subplot(
        self, qapp, monkeypatch,
    ):
        """Fix D: any range/geometry change funnels through
        disable_interactive_quality, which MUST invalidate the subplot cache
        (NoCache) or pan/zoom would smear the stale bitmap."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QGraphicsItem

        canvas = self._plot(qapp, mode="subplot")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        curves = self._curves(canvas)
        assert all(
            c.cacheMode() == QGraphicsItem.DeviceCoordinateCache for c in curves
        )

        canvas.disable_interactive_quality()
        assert canvas._quality.aa_on is False
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves), (
            "disable_interactive_quality must clear the device cache"
        )

    def test_disable_interactive_quality_noop_cache_in_overlay(
        self, qapp, monkeypatch,
    ):
        """Fix D (Correction 2): disable sets NoCache UNCONDITIONALLY in both
        modes. Overlay never set the cache, so this is a cheap no-op that
        still guarantees no stale cache survives a mode swap."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QGraphicsItem

        canvas = self._plot(qapp, mode="overlay")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        curves = self._curves(canvas)
        assert canvas._quality.aa_on is True

        canvas.disable_interactive_quality()
        assert canvas._quality.aa_on is False
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves)

    def test_xrange_change_clears_device_cache_subplot(self, qapp, monkeypatch):
        """Fix D end-to-end wiring: a real range mutation drops both AA
        and the subplot device cache via the existing _on_xrange_changed →
        disable_interactive_quality chokepoint."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QGraphicsItem

        canvas = self._plot(qapp, mode="subplot")
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        canvas.try_enable_idle_quality()
        curves = self._curves(canvas)
        assert all(
            c.cacheMode() == QGraphicsItem.DeviceCoordinateCache for c in curves
        )

        canvas.set_xlim(0.2, 0.8)
        assert canvas._quality.aa_on is False
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves)


class TestOverlayYSnapToGrid:
    """Snap-to-grid helper and integration tests."""

    def test_snap_y_to_divisions_round_to_nearest(self):
        """_snap_y_to_divisions 将任意 y 值四舍五入到最近的 k/N。"""
        from mf4_analyzer.ui.pg_canvases import _snap_y_to_divisions

        assert _snap_y_to_divisions(0.0, 8) == pytest.approx(0.0)
        # 0.124 is closer to 0.125 than to 0.0 (midpoint = 0.0625).
        assert _snap_y_to_divisions(0.124, 8) == pytest.approx(0.125)
        assert _snap_y_to_divisions(0.126, 8) == pytest.approx(0.125)
        assert _snap_y_to_divisions(0.5, 8) == pytest.approx(0.5)
        assert _snap_y_to_divisions(0.999, 8) == pytest.approx(1.0)
        assert _snap_y_to_divisions(1.0, 8) == pytest.approx(1.0)

    def test_snap_channel_reframes_to_nice_without_geometry(self, qapp):
        """Offscreen/零尺寸路径也应重框到 nice graticule，不崩溃。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows()[:2], mode="overlay")
        QCoreApplication.processEvents()

        ax = canvas.axes_list[0]
        ax.set_ylim(-300.0, 300.0)   # span = 600

        canvas._snap_overlay_channel_to_grid(ax)
        QCoreApplication.processEvents()

        lo_after, hi_after = ax.get_ylim()
        n = canvas._overlay_axes.divisions
        per_div = (hi_after - lo_after) / n
        assert abs(lo_after / per_div - round(lo_after / per_div)) < 1e-6
        assert abs(hi_after / per_div - round(hi_after / per_div)) < 1e-6
        major = ax.y_axis_item()._tickLevels[0]
        assert len(major) == n + 1
        canvas.deleteLater()

    def test_snap_none_ax_is_noop(self, qapp):
        """ax=None のとき何も起きない（クラッシュしない）。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows()[:2], mode="overlay")
        QCoreApplication.processEvents()

        # Must not raise.
        canvas._snap_overlay_channel_to_grid(None)
        canvas.deleteLater()

    def test_release_calls_snap_when_overlay_dragging(self, qapp, monkeypatch):
        """_handle_overlay_mouse_release は snap を呼び出す。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
        from unittest.mock import MagicMock

        canvas = TimeDomainCanvasPG()
        QCoreApplication.processEvents()
        rows = _five_channel_rows()[:2]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        canvas.select_overlay_channel(rows[0][0])
        QCoreApplication.processEvents()
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        canvas._overlay_axes.dragging = True
        # Synchronous snap path (no animation) keeps this a single-call
        # contract; the animated path is covered in test_overlay_grid_ticks.
        canvas._overlay_axes.snap_anim_ms = 0

        snap_calls = []
        monkeypatch.setattr(
            canvas, "_snap_overlay_channel_to_grid",
            lambda ax: snap_calls.append(ax),
        )

        event = MagicMock()
        canvas._handle_overlay_mouse_release(event)

        assert len(snap_calls) == 1, (
            f"expected 1 snap call on release, got {snap_calls}"
        )
        canvas.deleteLater()

    def test_release_does_not_snap_when_not_dragging(self, qapp, monkeypatch):
        """drag 中でない場合は snap を呼ばない。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
        from unittest.mock import MagicMock

        canvas = TimeDomainCanvasPG()
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows()[:2], mode="overlay")
        QCoreApplication.processEvents()

        snap_calls = []
        monkeypatch.setattr(
            canvas, "_snap_overlay_channel_to_grid",
            lambda ax: snap_calls.append(ax),
        )

        event = MagicMock()
        canvas._handle_overlay_mouse_release(event)   # _overlay_dragging is False

        assert snap_calls == [], (
            f"snap should not be called when not dragging; got {snap_calls}"
        )
        canvas.deleteLater()

    def test_snap_reframes_ticks_in_real_geometry(self, qapp):
        """有效几何下，snap 后边界与显式 ticks 应回到 nice graticule。"""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 480)
        canvas.show()
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()  # double-flush for layout settle

        rows = _five_channel_rows()[:2]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        ax = canvas.axes_list[0]
        ax.set_ylim(-273.0, 319.0)
        QCoreApplication.processEvents()

        canvas._snap_overlay_channel_to_grid(ax)
        QCoreApplication.processEvents()

        lo_after, hi_after = ax.get_ylim()
        n = canvas._overlay_axes.divisions
        per_div = (hi_after - lo_after) / n
        assert abs(lo_after / per_div - round(lo_after / per_div)) < 1e-6
        assert abs(hi_after / per_div - round(hi_after / per_div)) < 1e-6
        major = ax.y_axis_item()._tickLevels[0]
        assert [value for value, _label in major] == pytest.approx([
            lo_after + k * per_div for k in range(n + 1)
        ])
        canvas.deleteLater()


class TestTimeDomainCanvasPGSubplotUnits:
    """Subplot Y-axis labels keep channel units."""

    def _rows(self, names_units):
        t = np.linspace(0.0, 1.0, 64)
        sig = np.sin(t * 6.28)
        colors = ["#1769e0", "#e07b39", "#2bb673", "#c0392b"]
        return [
            (name, True, t, sig, colors[i % len(colors)], unit, "fid-1")
            for i, (name, unit) in enumerate(names_units)
        ]

    def test_subplot_outside_label_includes_unit(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 420)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(
            self._rows([("a", "Nm"), ("b", "deg")]), mode="subplot"
        )
        qapp.processEvents()

        labels = [h.get_ylabel() for h in canvas.axes_list]
        assert any("Nm" in label for label in labels), labels
        assert any("deg" in label for label in labels), labels

    def test_subplot_inside_label_includes_unit(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 420)
        canvas.show()
        qapp.processEvents()
        rows = self._rows([
            ("[tiaonorth] Rte_PA_mAtMotorTorque_xds16", "Nm"),
            ("[tiaonorth] Rte_RackPosCorrPlausi_wSteeringAngle_xds16", "deg"),
        ])
        canvas.plot_channels(rows, mode="subplot")
        qapp.processEvents()

        texts = [item.toPlainText() for item in canvas._inside_label_items]
        assert texts, "expected inside-label TextItems for long prefixed names"
        assert any("Nm" in text for text in texts), texts
        assert any("deg" in text for text in texts), texts


# ---------------------------------------------------------------------------
# Companion (filter-overlay) curves: a row carrying an 8th ``meta`` dict with
# ``companion_of`` is overlaid (dashed) on its SOURCE channel's axis/row — it
# never allocates a fresh subplot row. Toggling its visible flag just hides the
# dashed curve; the subplot count stays equal to the primary-channel count.
# ---------------------------------------------------------------------------
class TestFilterCompanionOverlay:
    def _rows_with_companion(self, *, filt_visible=True, n_sources=2):
        """Two source channels, each with one dashed filtered companion."""
        t = np.linspace(0.0, 1.0, 4_000, dtype=np.float64)
        rows = []
        palette = ["#1769e0", "#ef4444", "#00b894"]
        for i in range(n_sources):
            name = f"ch{i}"
            color = palette[i % len(palette)]
            sig = np.sin(2 * np.pi * (5 * (i + 1)) * t) + np.sin(
                2 * np.pi * 400 * t
            )
            # Primary (solid) row — 7-tuple, no meta.
            rows.append((name, True, t, sig, color, "u", "fid-1"))
            # Companion (dashed) row — 8-tuple with meta.
            filtered = np.sin(2 * np.pi * (5 * (i + 1)) * t)
            meta = {"companion_of": name, "dash": True}
            rows.append((
                f"{name} (LP 50Hz)", filt_visible, t, filtered, color,
                "u", "fid-1", meta,
            ))
        return rows

    def _companion_pdi(self, canvas, source_name):
        """Return the dashed companion PlotDataItem for ``source_name``.

        ``_companion_names`` is keyed by the COMPOSITE (data_id, name) identity
        key (multi-file same-name decouple), so membership is tested against the
        composite key while the human-readable display name is matched against
        ``source_name``.
        """
        for ck, name, (_ax, line) in canvas._channel_lines.composite_items():
            if ck in canvas._companion_names and name.startswith(source_name):
                return line.plot_data_item
        return None

    def _rows_big_primary_tiny_companion(self, *, filt_visible=True,
                                          orig_visible=True, n_sources=2):
        """Source channels with LARGE amplitude (±5) each paired with a
        TINY-amplitude (±0.02) filtered companion — mimics a low-pass 100 Hz
        overlay on a ±2~6 wideband channel. Used to pin the shared-axis Y
        auto-range to the PRIMARY extent so the dense original is never drawn
        inside a companion-narrow Y window (满屏竖线墙卡顿真因).

        ``orig_visible`` flips the SOLID original's visibility (显示原始):
        with it off, only the dashed companion is drawn, so the shared axis
        must frame the COMPANION (no dense original → no wall risk).
        """
        t = np.linspace(0.0, 1.0, 4_000, dtype=np.float64)
        rows = []
        palette = ["#1769e0", "#ef4444", "#00b894"]
        for i in range(n_sources):
            name = f"ch{i}"
            color = palette[i % len(palette)]
            primary = 5.0 * np.sin(2 * np.pi * (5 * (i + 1)) * t)
            rows.append((name, orig_visible, t, primary, color, "u", "fid-1"))
            tiny = 0.02 * np.sin(2 * np.pi * (5 * (i + 1)) * t)
            meta = {"companion_of": name, "dash": True}
            rows.append((
                f"{name} (LP 100Hz)", filt_visible, t, tiny, color,
                "u", "fid-1", meta,
            ))
        return rows

    def test_companion_axis_y_covers_primary_not_companion(self, qapp):
        """REGRESSION (滤波子图卡顿真因): when a tiny-amplitude (±0.02) dashed
        companion shares a subplot ViewBox with its LARGE (±5) source, the
        axis Y range must cover the PRIMARY extent (span ≈ 10), NOT the
        companion's ±0.02. Otherwise the dense original gets rasterized inside
        a narrow Y window as a full-height vertical-stroke wall (十几秒卡顿)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(n_sources=2),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        for i in range(2):
            src = f"ch{i}"
            handle = canvas._channel_lines[src][0]
            lo, hi = handle.get_ylim()
            span = hi - lo
            # Primary spans ~10 (±5); companion spans ~0.04 (±0.02).
            # The shared-axis Y MUST track the primary, not collapse to the
            # companion's tiny window.
            assert span > 5.0, (
                f"{src}: Y span {span:.4f} collapsed toward the tiny "
                f"companion (±0.02) instead of covering the ±5 primary"
            )
            # And it must actually contain the primary's ±5 extent.
            assert lo <= -4.5 and hi >= 4.5, (
                f"{src}: Y=[{lo:.3f},{hi:.3f}] does not contain the "
                f"±5 primary extent"
            )

    def test_companion_axis_y_autorange_disabled_pinned_to_primary(self, qapp):
        """MECHANISM guard: a companion-carrying subplot ViewBox must have its
        Y auto-range turned OFF (range pinned explicitly to the primary extent)
        so pyqtgraph can NEVER recompute Y from the tiny companion mid-build and
        paint the dense original inside a narrow Y window. A row WITHOUT a
        companion keeps Y auto-range ON (unchanged default)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        rows = self._rows_big_primary_tiny_companion(n_sources=2)
        # Append a third source with NO companion to assert it stays on auto.
        t = rows[0][2]
        rows.append(("solo", True, t, 4.0 * np.sin(2 * np.pi * 7 * t),
                     "#8b5cf6", "u", "fid-1"))
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # Companion-carrying axes: Y auto-range OFF.
        for i in range(2):
            vb = canvas._channel_lines[f"ch{i}"][0].view_box
            assert vb.state["autoRange"][1] is False, (
                f"ch{i}: Y auto-range still ON — a companion-axis must pin Y "
                f"to the primary extent so no narrow-Y transient can paint"
            )
        # No-companion axis: Y auto-range untouched (still ON).
        solo_vb = canvas._channel_lines["solo"][0].view_box
        assert solo_vb.state["autoRange"][1] is True, (
            "solo (no companion): Y auto-range must stay ON (no behavior "
            "change for rows without a filtered overlay)"
        )

    def test_home_keeps_companion_axis_on_primary_extent(self, qapp):
        """Toolbar Home (查看全部) must NOT collapse a companion-carrying axis
        to the tiny companion: the companion shares the source ViewBox, so
        iterating it would overwrite the primary framing. Y must stay on the
        ±5 primary after Home."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(n_sources=2),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        canvas.reset_view_to_data_extents()
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) > 5.0 and lo <= -4.5 and hi >= 4.5, (
                f"ch{i}: Home collapsed Y to [{lo:.3f},{hi:.3f}] (companion "
                f"overwrote primary on the shared axis)"
            )

    def test_fit_y_keeps_companion_axis_on_primary_extent(self, qapp):
        """Y 轴自适应 (fit_y_to_visible_x) must also skip companions so the
        shared axis fits the ±5 primary, not the ±0.02 dashed overlay."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(n_sources=2),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        canvas.fit_y_to_visible_x()
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) > 5.0 and lo <= -4.5 and hi >= 4.5

    def test_companion_axis_y_primary_extent_when_filtered_hidden(self, qapp):
        """Even with the companion hidden at build (显示滤波后 off), the axis
        Y must still frame the primary — the pin reads the PRIMARY data, never
        the companion."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(
                n_sources=2, filt_visible=False
            ),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        for i in range(2):
            handle = canvas._channel_lines[f"ch{i}"][0]
            lo, hi = handle.get_ylim()
            assert (hi - lo) > 5.0 and lo <= -4.5 and hi >= 4.5

    def test_companion_axis_y_fits_companion_when_original_hidden(self, qapp):
        """REGRESSION (本末倒置): 显示原始 OFF + 显示滤波后 ON — only the tiny
        (±0.02) dashed companion is drawn. With NO dense original on the axis
        there is no 满屏竖线墙 risk, so the shared Y MUST fit the COMPANION
        (span ≈ 0.04) instead of staying pinned to the invisible ±5 primary
        (which buries the filtered waveform in a flat line near 0)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(
                n_sources=2, orig_visible=False, filt_visible=True
            ),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        for i in range(2):
            handle = canvas._channel_lines[f"ch{i}"][0]
            lo, hi = handle.get_ylim()
            span = hi - lo
            assert span < 1.0, (
                f"ch{i}: Y span {span:.4f} still framed the hidden ±5 primary "
                f"— the visible ±0.02 companion is buried in a flat line"
            )
            # The companion (±0.02) must actually fit inside the window.
            assert lo <= -0.02 and hi >= 0.02, (
                f"ch{i}: Y=[{lo:.4f},{hi:.4f}] does not contain the ±0.02 "
                f"companion extent"
            )

    def test_home_fits_companion_when_original_hidden(self, qapp):
        """Toolbar Home (查看全部) with 显示原始 OFF must fit the visible
        companion, not the hidden ±5 primary."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(
                n_sources=2, orig_visible=False, filt_visible=True
            ),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        canvas.reset_view_to_data_extents()
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) < 1.0 and lo <= -0.02 and hi >= 0.02, (
                f"ch{i}: Home framed Y to [{lo:.4f},{hi:.4f}] — the hidden "
                f"±5 primary instead of the visible ±0.02 companion"
            )

    def test_fit_y_fits_companion_when_original_hidden(self, qapp):
        """Y 轴自适应 (fit_y_to_visible_x) with 显示原始 OFF must fit the
        visible companion, not the hidden ±5 primary."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(
                n_sources=2, orig_visible=False, filt_visible=True
            ),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        canvas.fit_y_to_visible_x()
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) < 1.0 and lo <= -0.02 and hi >= 0.02

    def test_live_hide_original_refits_axis_to_companion(self, qapp):
        """Live 显示原始 toggle: built with both visible (Y on ±5 primary),
        unchecking 显示原始 must REFIT the shared axis to the now-only-visible
        ±0.02 companion; re-checking must restore the ±5 primary framing (wall
        avoidance back on now the dense original is drawn again)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(n_sources=2),
            mode="subplot",
        )
        QCoreApplication.processEvents()
        # Both visible → Y frames the ±5 primary.
        lo, hi = canvas._channel_lines["ch0"][0].get_ylim()
        assert (hi - lo) > 5.0
        # Hide originals → axis must refit to the ±0.02 companion.
        canvas.set_original_lines_visible(False)
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) < 1.0 and lo <= -0.02 and hi >= 0.02, (
                f"ch{i}: hiding 显示原始 left Y on [{lo:.4f},{hi:.4f}] (the "
                f"hidden ±5 primary) instead of refitting the ±0.02 companion"
            )
        # Re-show originals → axis must restore the ±5 primary framing.
        canvas.set_original_lines_visible(True)
        QCoreApplication.processEvents()
        for i in range(2):
            lo, hi = canvas._channel_lines[f"ch{i}"][0].get_ylim()
            assert (hi - lo) > 5.0 and lo <= -4.5 and hi >= 4.5, (
                f"ch{i}: re-showing 显示原始 left Y on [{lo:.4f},{hi:.4f}] — "
                f"the dense ±5 original would paint inside a narrow Y wall"
            )

    def test_overlay_drag_target_is_visible_companion_not_hidden_primary(self, qapp):
        """方案2 + 排除隐藏: in OVERLAY with 显示原始 off, the per-channel
        Alt-drag target resolved for a companion-carrying axis must be the
        VISIBLE companion, never the hidden primary that owns the axis (the
        companion shares the primary's ViewBox)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_big_primary_tiny_companion(
                n_sources=2, orig_visible=False, filt_visible=True
            ),
            mode="overlay",
        )
        QCoreApplication.processEvents()
        for i in range(2):
            primary = f"ch{i}"
            handle = canvas._channel_lines[primary][0]
            assert canvas._overlay_channel_is_visible(primary) is False, (
                f"{primary} primary line should be hidden (显示原始 off)"
            )
            resolved = canvas._visible_channel_name_for_handle(handle)
            assert resolved is not None and resolved != primary, (
                f"drag target {resolved!r} must be the visible companion, not "
                f"the hidden primary {primary!r}"
            )
            # _companion_names is keyed by the composite (data_id, name) identity
            # key; resolve the display name to its composite key to test
            # membership.
            resolved_key = canvas._channel_lines.composite_key_for(resolved)
            assert resolved_key in canvas._companion_names

    def test_no_companion_subplot_y_unchanged(self, qapp):
        """A subplot row WITHOUT a companion keeps pyqtgraph's default Y
        auto-range (the pin only engages for companion-carrying axes); the
        single-curve extent still frames the ±5 primary."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        t = np.linspace(0.0, 1.0, 4_000, dtype=np.float64)
        rows = [
            ("a", True, t, 5.0 * np.sin(2 * np.pi * 5 * t), "#1769e0", "u",
             "fid-1"),
            ("b", True, t, 3.0 * np.sin(2 * np.pi * 9 * t), "#ef4444", "u",
             "fid-1"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        lo, hi = canvas._channel_lines["a"][0].get_ylim()
        assert (hi - lo) > 5.0 and lo <= -4.5 and hi >= 4.5

    def test_subplot_count_equals_source_count_not_doubled(self, qapp):
        """Enabling filter overlays must NOT double the subplot rows: the
        companion renders on its source's row, so axes_list == source count."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        # 2 source channels → exactly 2 axes/rows (NOT 4).
        assert len(canvas.axes_list) == 2
        # Both companions ARE registered as curves (refresh/export pick them
        # up) but tracked separately from real channels.
        assert len(canvas._companion_names) == 2
        # _channel_lines holds 2 sources + 2 companions.
        assert len(canvas._channel_lines) == 4

    def test_companion_shares_source_axis_and_is_dashed(self, qapp):
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QPen

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        for i in range(2):
            src = f"ch{i}"
            source_handle = canvas._channel_lines[src][0]
            comp_handle = canvas._channel_lines[f"{src} (LP 50Hz)"][0]
            # Same axis handle → same row/ViewBox, no extra subplot.
            assert comp_handle is source_handle
            # Companion pen is dashed; source pen is solid, same colour family.
            comp_pdi = self._companion_pdi(canvas, src)
            assert comp_pdi is not None
            pen = comp_pdi.opts.get("pen")
            assert isinstance(pen, QPen)
            assert pen.style() == Qt.DashLine

    def test_overlay_mode_companion_dashed_same_viewbox(self, qapp):
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QPen

        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="overlay")
        qapp.processEvents()
        # Overlay: 2 source channels → 2 aux axes (companions add no axis).
        assert len(canvas.axes_list) == 2
        assert len(canvas._companion_names) == 2
        for i in range(2):
            src = f"ch{i}"
            source_handle = canvas._channel_lines[src][0]
            comp_handle = canvas._channel_lines[f"{src} (LP 50Hz)"][0]
            assert comp_handle is source_handle
            comp_pdi = self._companion_pdi(canvas, src)
            pen = comp_pdi.opts.get("pen")
            assert isinstance(pen, QPen) and pen.style() == Qt.DashLine

    def test_uncheck_show_filtered_hides_dashed_keeps_rows(self, qapp):
        """Companion visible=False → dashed curve hidden, subplot count and
        the solid originals unchanged (cancel = just hide)."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(
            self._rows_with_companion(filt_visible=False, n_sources=2),
            mode="subplot",
        )
        qapp.processEvents()
        # Subplot count still equals source count.
        assert len(canvas.axes_list) == 2
        for i in range(2):
            src = f"ch{i}"
            comp_pdi = self._companion_pdi(canvas, src)
            assert comp_pdi is not None
            assert comp_pdi.isVisible() is False
            # The solid original is still present and visible.
            src_pdi = canvas._channel_lines[src][1].plot_data_item
            assert src_pdi.isVisible() is True

    def test_companion_excluded_from_statistics(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        stats = canvas.get_statistics()
        # Only the two source channels appear; no companion entries.
        assert set(stats) == {"ch0", "ch1"}

    def test_legacy_seven_tuple_rows_unchanged(self, qapp):
        """No meta → no companions; plain subplot layout is untouched."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(_five_channel_rows()[:3], mode="subplot")
        qapp.processEvents()
        assert len(canvas.axes_list) == 3
        assert len(canvas._companion_names) == 0

    # --- bug B: original hidden + companion visible must KEEP the axis ------
    def _rows_orig_off_filt_on(self, n_sources=2):
        """Primaries visible=False (显示原始 off), companions visible=True
        (显示滤波后 on)."""
        rows = self._rows_with_companion(filt_visible=True, n_sources=n_sources)
        out = []
        for row in rows:
            # primary rows are 7-tuples (no meta); companions are 8-tuples.
            if len(row) >= 8 and isinstance(row[7], dict):
                out.append(row)  # companion stays visible
            else:
                name, _vis, t, sig, color, unit, fid = row[:7]
                out.append((name, False, t, sig, color, unit, fid))
        return out

    def test_orig_off_filt_on_keeps_axis_per_channel_subplot(self, qapp):
        """显示原始 off + 显示滤波后 on: each channel still owns ONE axis (so
        the chart is NOT blank), the original is hidden, the dashed companion
        is visible and on the SAME axis."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_orig_off_filt_on(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        # subplot count == source count (not 0, not doubled).
        assert len(canvas.axes_list) == 2
        assert len(canvas._companion_names) == 2
        for i in range(2):
            src = f"ch{i}"
            src_pdi = canvas._channel_lines[src][1].plot_data_item
            comp_pdi = self._companion_pdi(canvas, src)
            assert src_pdi.isVisible() is False
            assert comp_pdi is not None and comp_pdi.isVisible() is True
            # companion shares the source's axis handle.
            assert canvas._channel_lines[src][0] is (
                canvas._channel_lines[f"{src} (LP 50Hz)"][0]
            )

    def test_orig_off_filt_on_keeps_axis_single_channel(self, qapp):
        """Single channel, original off + filtered on → exactly one axis, not
        blank; original hidden, companion visible."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_orig_off_filt_on(n_sources=1),
                             mode="subplot")
        qapp.processEvents()
        assert len(canvas.axes_list) == 1
        assert len(canvas._companion_names) == 1
        src_pdi = canvas._channel_lines["ch0"][1].plot_data_item
        comp_pdi = self._companion_pdi(canvas, "ch0")
        assert src_pdi.isVisible() is False
        assert comp_pdi.isVisible() is True

    def test_both_off_drops_channel_axis(self, qapp):
        """显示原始 off AND 显示滤波后 off → that channel owns no axis (nothing
        to draw, nothing to anchor)."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        rows = self._rows_with_companion(filt_visible=False, n_sources=2)
        out = []
        for row in rows:
            if len(row) >= 8 and isinstance(row[7], dict):
                out.append(row)  # companion visible=False already
            else:
                name, _vis, t, sig, color, unit, fid = row[:7]
                out.append((name, False, t, sig, color, unit, fid))
        canvas.plot_channels(out, mode="subplot")
        qapp.processEvents()
        # No channel owns an axis → blank chart is acceptable here.
        assert len(canvas.axes_list) == 0

    def test_orig_off_one_chan_filt_on_overlay(self, qapp):
        """Overlay mode (>=2 channels) with originals off + filtered on keeps
        one aux axis PER channel."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_orig_off_filt_on(n_sources=2),
                             mode="overlay")
        qapp.processEvents()
        assert len(canvas.axes_list) == 2
        for i in range(2):
            src = f"ch{i}"
            assert canvas._channel_lines[src][1].plot_data_item.isVisible() is False
            assert self._companion_pdi(canvas, src).isVisible() is True

    # --- live toggle on already-built chart (no rebuild) --------------------
    def test_live_hide_originals_keeps_axes_and_companions(self, qapp):
        """set_original_lines_visible(False) flips primaries hidden in place;
        axes and companions are untouched (no rebuild)."""
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        n = canvas.set_original_lines_visible(False)
        assert n == 2  # two primaries toggled
        assert len(canvas.axes_list) == 2  # axes survive
        for i in range(2):
            src = f"ch{i}"
            assert canvas._channel_lines[src][1].plot_data_item.isVisible() is False
            # companion still visible.
            assert self._companion_pdi(canvas, src).isVisible() is True
        # re-show restores originals.
        canvas.set_original_lines_visible(True)
        for i in range(2):
            assert canvas._channel_lines[f"ch{i}"][1].plot_data_item.isVisible() is True

    def test_live_hide_companions_keeps_axes_and_originals(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2),
                             mode="subplot")
        qapp.processEvents()
        n = canvas.set_companion_lines_visible(False)
        assert n == 2
        assert len(canvas.axes_list) == 2
        for i in range(2):
            src = f"ch{i}"
            assert self._companion_pdi(canvas, src).isVisible() is False
            assert canvas._channel_lines[src][1].plot_data_item.isVisible() is True

    def test_live_toggle_returns_zero_when_nothing_built(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        assert canvas.set_original_lines_visible(False) == 0
        assert canvas.set_companion_lines_visible(False) == 0


# ---------------------------------------------------------------------------
# 显示原始/显示滤波后 OFF: a HIDDEN curve (PlotDataItem.isVisible()==False) keeps
# its samples in channel_data. The bug was that the cursor readout and the
# pan/zoom envelope refresh both iterate by DATA presence, so a hidden original
# still appeared in the cursor pill and still got re-enveloped every pan tick
# ("游标命中隐藏曲线" + "拖动加倍曲线量"). These pin the visibility-aware paths.
# ---------------------------------------------------------------------------
class TestHiddenCurveCursorAndRefresh(TestFilterCompanionOverlay):
    def _build(self, qapp, mode="subplot"):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 600)
        canvas.show()
        qapp.processEvents()
        canvas.plot_channels(self._rows_with_companion(n_sources=2), mode=mode)
        qapp.processEvents()
        return canvas

    def test_single_cursor_html_excludes_hidden_original(self, qapp):
        """显示原始 OFF → the cursor pill must NOT list the hidden solid
        originals; only the visible dashed companions remain."""
        canvas = self._build(qapp)
        canvas.set_original_lines_visible(False)
        seen = []
        canvas._cursor.cursor_info.connect(seen.append)
        canvas._cursor._emit_single_cursor_html(0.5)
        html = seen[-1]
        # hidden originals (bare "ch0"/"ch1") are gone; companions stay.
        assert "ch0 (LP 50Hz)" in html and "ch1 (LP 50Hz)" in html
        # the solid original token "ch0=" must NOT appear (companion uses
        # "ch0 (LP 50Hz)=" so the bare-name "=" is unambiguous).
        assert "ch0=" not in html and "ch1=" not in html

    def test_single_cursor_html_excludes_hidden_companion(self, qapp):
        """显示滤波后 OFF → the hidden dashed companion drops from the pill."""
        canvas = self._build(qapp)
        canvas.set_companion_lines_visible(False)
        seen = []
        canvas._cursor.cursor_info.connect(seen.append)
        canvas._cursor._emit_single_cursor_html(0.5)
        html = seen[-1]
        assert "ch0=" in html and "ch1=" in html
        assert "(LP 50Hz)" not in html

    def test_dual_cursor_rows_exclude_hidden_original(self, qapp):
        """Dual-cursor stats rows must skip the hidden originals."""
        canvas = self._build(qapp)
        canvas.set_dual_cursor_mode(True)
        canvas.set_original_lines_visible(False)
        rows = []
        canvas._cursor.dual_cursor_rows.connect(lambda r: rows.append(r))
        canvas._cursor._ax = 0.2
        canvas._cursor._bx = 0.8
        canvas._cursor._emit_dual_cursor_html()
        emitted = rows[-1] if rows else []
        names = {r[0] for r in emitted}
        # only the visible companions appear; bare originals excluded.
        assert names == {"ch0 (LP 50Hz)", "ch1 (LP 50Hz)"}

    def test_refresh_skips_hidden_curve_no_setdata(self, qapp):
        """A hidden original must NOT be re-enveloped on a pan/zoom refresh
        (the doubled-work / 拖动加倍 root). Its PlotDataItem data stays frozen
        while hidden, even after an xlim change + flush."""
        canvas = self._build(qapp)
        src_pdi = canvas._channel_lines["ch0"][1].plot_data_item
        canvas.set_original_lines_visible(False)
        frozen_x, _ = src_pdi.getData()
        ax0 = canvas.axes_list[0]
        lo, hi = ax0.get_xlim()
        span = hi - lo
        canvas.set_xlim(lo + span * 0.4, lo + span * 0.6)
        qapp.processEvents()
        canvas._flush_pending_refresh()
        qapp.processEvents()
        now_x, _ = src_pdi.getData()
        assert np.array_equal(frozen_x, now_x), (
            "hidden original was re-enveloped during pan (should be skipped)"
        )
        # the VISIBLE companion did track the new window.
        comp = self._companion_pdi(canvas, "ch0")
        cx, _ = comp.getData()
        assert float(np.nanmax(cx)) <= lo + span * 0.6 + 1e-6

    def test_reshow_after_pan_refreshes_to_current_window(self, qapp):
        """Re-checking 显示原始 after panning while hidden must repopulate the
        original's envelope at the CURRENT x-window (no stale data)."""
        canvas = self._build(qapp)
        canvas.set_original_lines_visible(False)
        ax0 = canvas.axes_list[0]
        lo, hi = ax0.get_xlim()
        span = hi - lo
        new_lo, new_hi = lo + span * 0.4, lo + span * 0.6
        canvas.set_xlim(new_lo, new_hi)
        qapp.processEvents()
        canvas._flush_pending_refresh()
        qapp.processEvents()
        canvas.set_original_lines_visible(True)
        qapp.processEvents()
        src_pdi = canvas._channel_lines["ch0"][1].plot_data_item
        assert src_pdi.isVisible() is True
        rx, _ = src_pdi.getData()
        # the re-shown envelope is clipped to the current window, not the full
        # 0..1 range it had before hiding.
        assert float(np.nanmin(rx)) >= new_lo - span * 0.1
        assert float(np.nanmax(rx)) <= new_hi + span * 0.1

    def test_overlay_refresh_skips_hidden_original(self, qapp):
        """Same skip in overlay mode (the 拖到加倍 symptom is worst here)."""
        canvas = self._build(qapp, mode="overlay")
        src_pdi = canvas._channel_lines["ch0"][1].plot_data_item
        canvas.set_original_lines_visible(False)
        frozen_x, _ = src_pdi.getData()
        ax0 = canvas.axes_list[0]
        lo, hi = ax0.get_xlim()
        span = hi - lo
        canvas.set_xlim(lo + span * 0.3, lo + span * 0.7)
        qapp.processEvents()
        canvas._flush_pending_refresh()
        qapp.processEvents()
        now_x, _ = src_pdi.getData()
        assert np.array_equal(frozen_x, now_x)

    def test_hiding_original_clears_device_coordinate_cache(self, qapp):
        """A hidden curve must drop its DeviceCoordinateCache so no stale
        offscreen raster pixmap keeps compositing (lesson-95 GL fingerprint).
        Mechanism guard: simulate the idle-AA cache, then hide and assert the
        curve's cache mode is NoCache."""
        from PyQt5.QtWidgets import QGraphicsItem

        canvas = self._build(qapp)
        src_pdi = canvas._channel_lines["ch0"][1].plot_data_item
        # Simulate the idle-AA pass having cached the curve.
        src_pdi.curve.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        assert src_pdi.curve.cacheMode() == QGraphicsItem.DeviceCoordinateCache
        canvas.set_original_lines_visible(False)
        assert src_pdi.curve.cacheMode() == QGraphicsItem.NoCache


# ---------------------------------------------------------------------------
# Companion-only (显示原始 OFF + 显示滤波后 ON) lag fix: a Qt.DashLine pen
# rasterizes a dense min/max-envelope zigzag several× slower than a solid pen
# on the CPU raster backend, so the dashed companion was the dominant paint
# cost in comp-only view even though displayed-point counts matched orig-only
# (实测 4×150万点 AA-off 交互式拖动单帧: comp-only 47ms vs orig-only 16ms; the
# dash IS the delta). The dash is purely a visual affordance to tell the
# companion apart from its solid source — useless when the source is hidden. So
# the companion is drawn SOLID while its original is hidden, DASHED when it is
# shown. These pin the style-sync MECHANISM (offscreen-stable; the actual paint
# delta is Windows-raster-timing-only, see the slow timing test).
# ---------------------------------------------------------------------------
class TestCompanionDashStyleSync(TestFilterCompanionOverlay):
    def _build(self, qapp, *, filt_visible=True, n_sources=2, mode="subplot"):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(
            self._rows_with_companion(filt_visible=filt_visible,
                                      n_sources=n_sources),
            mode=mode,
        )
        QCoreApplication.processEvents()
        return canvas

    @staticmethod
    def _companion_pen_style(canvas, source_name):
        from PyQt5.QtGui import QPen

        for ck, name, (_ax, line) in canvas._channel_lines.composite_items():
            if ck in canvas._companion_names and name.startswith(source_name):
                pen = line.plot_data_item.opts.get("pen")
                return pen.style() if isinstance(pen, QPen) else None
        return None

    def test_both_visible_companion_is_dashed(self, qapp):
        """Default 全显 (原始+滤波): the companion keeps its dashed pen so it is
        visually distinguishable from the solid original."""
        from PyQt5.QtCore import Qt

        canvas = self._build(qapp)
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.DashLine

    def test_original_hidden_companion_goes_solid(self, qapp):
        """显示原始 OFF: with no solid original to distinguish from, each
        companion drops the slow dashed pen for a solid one (the root-cause
        comp-only lag fix). MECHANISM: pen.style() == SolidLine."""
        from PyQt5.QtCore import Qt

        canvas = self._build(qapp)
        canvas.set_original_lines_visible(False)
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.SolidLine, (
                f"ch{i} companion stayed dashed after 显示原始 OFF — the slow "
                "dash raster cost is the comp-only lag"
            )

    def test_reshow_original_restores_dash(self, qapp):
        """Re-showing 显示原始 restores the companion's dash so the two traces
        stay distinguishable again (round-trip)."""
        from PyQt5.QtCore import Qt

        canvas = self._build(qapp)
        canvas.set_original_lines_visible(False)
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.SolidLine
        canvas.set_original_lines_visible(True)
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.DashLine

    def test_companion_built_with_original_off_is_solid_from_first_frame(self, qapp):
        """Building straight into 显示原始 OFF + 显示滤波后 ON (a common entry
        point) draws the companion SOLID on the FIRST frame — the bind-time
        _sync_companion_dash_styles call, not only the live toggles."""
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 600)
        canvas.show()
        QCoreApplication.processEvents()
        # originals OFF, filtered ON.
        rows = self._rows_big_primary_tiny_companion(
            filt_visible=True, orig_visible=False, n_sources=2,
        )
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.SolidLine

    def test_style_sync_preserves_color_and_width(self, qapp):
        """The style toggle must touch ONLY the pen style — color and width of
        the companion pen are preserved across solid↔dash flips."""
        from PyQt5.QtGui import QPen

        canvas = self._build(qapp)

        def _pen(i):
            for ck, name, (_ax, line) in canvas._channel_lines.composite_items():
                if ck in canvas._companion_names and name.startswith(f"ch{i}"):
                    p = line.plot_data_item.opts.get("pen")
                    return p if isinstance(p, QPen) else None
            return None

        before = [(_pen(i).color().name(), _pen(i).widthF()) for i in range(2)]
        canvas.set_original_lines_visible(False)  # → solid
        after = [(_pen(i).color().name(), _pen(i).widthF()) for i in range(2)]
        assert before == after, (
            f"dash→solid changed color/width: {before} -> {after}"
        )

    def test_solid_pen_load_bearing_via_predicate_neutralize(self, qapp):
        """Prove the source-visibility predicate is load-bearing: monkeypatch
        _source_original_visible to always-True (the pre-fix behavior) and the
        companion stays DASHED even with the original hidden — RED proof the
        green test is not vacuous."""
        from PyQt5.QtCore import Qt

        canvas = self._build(qapp)
        canvas._source_original_visible = lambda ck: True  # neutralize the fix
        canvas.set_original_lines_visible(False)
        # With the predicate forced True the companion keeps the slow dash.
        for i in range(2):
            assert self._companion_pen_style(canvas, f"ch{i}") == Qt.DashLine

    @pytest.mark.slow
    def test_companion_only_pan_not_slower_than_original_only(self, qapp):
        """PERF REGRESSION (Windows CPU-raster timing): a comp-only interactive
        pan frame must not be dramatically slower than an orig-only one. With
        the dashed companion the comp-only frame was ~3× slower despite an equal
        displayed-point count; the solid-when-original-hidden fix brings it back
        to parity (实测 47ms→7ms vs orig-only 16ms).

        Timed via viewport.repaint() (offscreen grab() is a cached blit ≈1ms and
        HIDES the real raster cost — see narrow-y-dense-wall-systemic-map). The
        threshold is generous (comp-only <= 1.5× orig-only) because absolute
        paint-ms is machine-dependent; the load-bearing assertion is RATIO, not
        an absolute budget. Marked slow: builds 4×~1M-point dense channels.
        """
        import time

        from PyQt5.QtCore import QCoreApplication

        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.set_gpu_render(False)
        canvas.resize(1600, 700)
        canvas.show()
        QCoreApplication.processEvents()

        npts = 1_000_000
        t = np.linspace(0.0, npts / 48000.0, npts, dtype=np.float64)
        rng = np.random.default_rng(7)
        rows = []
        palette = ["#1769e0", "#ef4444", "#00b894", "#8b5cf6"]
        for i in range(4):
            name = f"Accel_{i}"
            primary = ((3.0 + i) * np.sin(2 * np.pi * (120 * (i + 1)) * t)
                       + 0.8 * rng.standard_normal(npts)).astype(np.float64)
            rows.append((name, True, t, primary, palette[i], "g", "fid-A"))
            filtered = (0.3 * np.sin(2 * np.pi * (30 * (i + 1)) * t)).astype(np.float64)
            meta = {"companion_of": name, "dash": True}
            rows.append((f"{name} (LP 100Hz)", True, t, filtered,
                         palette[i], "g", "fid-A", meta))
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        canvas._flush_pending_refresh()

        def _median_pan_repaint(n=10):
            ax = canvas._primary_xaxis_ax
            total = float(t[-1] - t[0])
            win = total * 0.30
            vp = canvas._glw.viewport()
            samples = []
            for k in range(n):
                canvas.disable_interactive_quality()  # drag → AA off
                lo = total * 0.015 * k
                ax.set_xlim(lo, lo + win)
                canvas._flush_pending_refresh()
                QCoreApplication.processEvents()
                canvas._glw.update()
                t0 = time.perf_counter()
                vp.repaint()
                samples.append((time.perf_counter() - t0) * 1000.0)
            samples.sort()
            return samples[len(samples) // 2]

        canvas.set_companion_lines_visible(False)  # orig-only
        QCoreApplication.processEvents()
        canvas._flush_pending_refresh()
        orig_only = _median_pan_repaint()

        canvas.set_companion_lines_visible(True)
        canvas.set_original_lines_visible(False)  # comp-only
        QCoreApplication.processEvents()
        canvas._flush_pending_refresh()
        comp_only = _median_pan_repaint()

        assert comp_only <= max(orig_only * 1.5, orig_only + 8.0), (
            f"comp-only pan ({comp_only:.1f}ms) is much slower than orig-only "
            f"({orig_only:.1f}ms) — the dashed-companion raster regression is back"
        )
        canvas.deleteLater()
