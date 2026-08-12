"""Visible data refresh and export helpers for the pyqtgraph canvas."""

from __future__ import annotations

import logging
import sys

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref
from .render_profile import (
    DENSE_DISCRETE_BUCKET_BUDGET,
    bucket_width_for,
    classify_render_profile,
    envelope_ink_dev_px,
    source_revision_for,
)

import pyqtgraph as pg

from .ticks_math import _quantize_range_key


_log = logging.getLogger("mf4_analyzer.ui.pg_canvases")


# ---------------------------------------------------------------------------
# Hi-DPI copy/save render (spec §E).
#
# The toolbar 复制为图片 / 保存图片 buttons render the scene at a HIGHER
# scale so the bitmap is DPI-independent and crisp (matplotlib was sharp
# because it rendered at figure DPI, not screen pixels). To keep export
# fast and not slow normal use, the magnification is CAPPED:
#
#   effective_scale = clamp(requested, 1.0, _HIDPI_MAX_WIDTH / base_width)
#
# i.e. we never downscale (floor 1×) and we never let the output width
# exceed _HIDPI_MAX_WIDTH px. For a typical ~1200px workspace a 2× request
# yields ~2400px; a very wide canvas is throttled so width tops out near
# 2560px. One consistent rule, applied in both copy and save paths.
# ---------------------------------------------------------------------------
_HIDPI_COPY_SCALE = 2.0
_HIDPI_MAX_WIDTH = 2560


# ---------------------------------------------------------------------------
# Overlay envelope bucket-cap headroom multiplier (see _effective_pixel_width).
#
# The per-curve bucket cap is sized so the SUMMED displayed-point count across
# all overlay curves lands at K × _AA_OVERLAY_SEGMENT_OFF, i.e. a comfortable
# margin ABOVE the AA-off threshold. K must be > 1 so the summed count stays
# reliably ABOVE the threshold for every channel count in 2..8 (integer
# division otherwise lets the sum dip to or below the threshold and silently
# re-enables AA in exactly the dense overlay we are trying to speed up). K=1.3
# targets summed ≈ 1.3× budget (~9100 pts at the default 7000), comfortably
# inside the 1.2–1.5× band while keeping bucket count far below full
# pixel_width so most of the raster-fill speedup is preserved.
# ---------------------------------------------------------------------------
_OVERLAY_BUCKET_BUDGET_MULT = 1.3


# ---------------------------------------------------------------------------
# Subplot dense-channel bucket cap (满高竖线墙 raster wall in SPLIT mode).
#
# The overlay cap above only governs overlay's shared-rect ViewBox stack. In
# SUBPLOT/SINGLE mode each channel owns a disjoint short row, so a single (or
# few) channel never hits the full-height-stroke wall and keeps full
# pixel_width resolution. But when MANY HIGH-DENSITY wideband channels are
# stacked (e.g. 6 × 129.5 kHz accel, ~1.2 M pts each), every row's per-bucket
# min/max pair paints as a full-height vertical stroke spanning its row, and
# the per-frame raster-fill cost is the SUM over the dense rows — re-showing
# the 6 hidden originals (set_original_lines_visible) repaints all six walls
# at once (~1.1 s baseline, ~1.8 s on the re-show in the field).
#
# A channel is "dense" when its decimation ratio (source_len / pixel_width)
# exceeds _SUBPLOT_DENSE_DECIMATION — i.e. each pixel column already collapses
# many source samples into a min/max wall, so coarsening the bucket count
# cannot lose a visible feature (the wall stays the wall, just with fewer
# strokes). Below that ratio the trace is a thin line, not a fill wall, and is
# left at full resolution (fidelity red line: low-density / single dense
# channels never coarsen).
#
# When >= 2 dense channels are present, each dense row's bucket count is capped
# to _SUBPLOT_DENSE_BUCKET_BUDGET / dense_count (floored at
# _SUBPLOT_DENSE_MIN_BUCKETS so a row never degenerates), so the summed dense
# bucket count is bounded by the budget regardless of channel count. The budget
# is set so a 6-channel dense stack drops from ~6×1270 buckets to ~6×420,
# cutting the raster wall while staying far above the per-row min.
# ---------------------------------------------------------------------------
_SUBPLOT_DENSE_DECIMATION = 8.0
_SUBPLOT_DENSE_BUCKET_BUDGET = 2600
_SUBPLOT_DENSE_MIN_BUCKETS = 350


# ---------------------------------------------------------------------------
# Universal per-line INK BUDGET (墨水量预算) — spec
# docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md §4.1 / §5.
#
# The two caps above key off STATIC density (source_len / pixel_width) or
# channel count. They miss the GENERAL trigger of the expensive frame: the
# amount of VERTICAL INK the envelope has to paint. Every path funnels into ONE
# setData per line in _refresh_visible_data, so the metric is computed there,
# from the envelope that is already in hand (one vectorized diff, near-free):
#
#     ink_dev_px = Σ min(|Δy_i|, y_span) / y_span × row_height_px × dpr
#
# (envelope_ink_dev_px, mf4_analyzer/render_profile.py.)
#
# This REPLACES the retired data_span/y_span "满高竖线墙" wall guard (K = 4.0,
# 1800-bucket ceiling), which measured the wrong axis. 2026-08-08 real-machine
# sweep (Cocoa, dpr 2.0, 1600×950, 1M samples @ 20 kHz): drag p50 by Y ratio
# was 3.9 ms at ratio 9.8 — where the wall guard DID fire — and 106 ms at
# ratio 1.0, where it did not. The cost peak sits exactly at ratio ≈ 1.0, i.e.
# the output of Y auto-fit, because that is where the strokes are longest
# without being clipped away by the viewport. Ink, unlike the ratio, is
# linear in the measured cost across the whole band, and separates the two
# fitted-window cases the ratio cannot tell apart (spec §3.3): a SMOOTH curve
# fitted to its window is 72.7k ink (keep full resolution) while an
# OSCILLATING one is 2042k (coarsen).
#
# _INK_OFF_BUDGET is the per-line ceiling above which the bucket count is cut
# proportionally (spec §4.1 clamp) and the frame is flagged high-ink so the
# idle-AA gate holds AA off. 1.2M device px ≈ a 20 ms interaction frame at the
# measured 16.5 ns/dev px (equivalently 33 ns per logical px at dpr 2.0).
# Anchors on that line: 350 buckets → 461k ink → predicted 15.2 ms, measured
# 17.0 ms; the bucket sweep 1550/1200/800/500/350 measured 64/51/35/23/17 ms.
#
# _INK_MIN_BUCKETS is the floor the proportional cut may never go below, so a
# hugely over-budget line still keeps a recognizable silhouette. It reuses
# _SUBPLOT_DENSE_MIN_BUCKETS' value (350) and its justification, and the same
# measurement backs it: 350 buckets is a 17 ms frame, comfortably inside the
# 30 ms interaction target even at the floor.
#
# Both are CALIBRATIONS, not knobs: the ns/px coefficient is Cocoa @ dpr 2.0.
# Changing either requires updating spec §5 and re-running
# scripts/probe_aa_ink_budget.py on real hardware (an offscreen suite cannot
# measure paint cost); tests/ui/test_pg_timedomain_canvas.py::TestInkBudget
# fences the order of magnitude.
# ---------------------------------------------------------------------------
_INK_OFF_BUDGET = 1_200_000
_INK_MIN_BUCKETS = 350


# ---------------------------------------------------------------------------
# Vector-AA / raster-upgrade admission band (spec §4.2 / §4.3 / §5).
#
# One shared boundary, two consumers: the idle-AA gate refuses vector AA while
# the summed ink of native-AA-path lines exceeds _INK_AA_OFF (re-allowing only
# below _INK_AA_ON), and the dense-raster backend ADMITS a line for the smooth
# pixmap upgrade over the same band — the lines vector AA cannot afford are
# exactly the ones the raster path exists for, and sharing the band keeps the
# two decisions from flapping against each other at the boundary.
#
# Calibration anchors (2026-08-08, Cocoa dpr 2.0): the smooth control is
# ≈145k dev px and its idle AA frame (240–475 ms) is today's accepted
# behavior — it MUST stay allowed, so the band sits above it. The 6ch
# oscillating rows (≈612k/row) and the 1ch fit-Y case (≈4.1M) measured
# 3.6 s and 63 s per AA frame — they must stay blocked. Same calibration
# discipline as the constants above: change spec §5 first, re-measure with
# scripts/probe_aa_ink_budget.py on real hardware.
# ---------------------------------------------------------------------------
_INK_AA_ON = 200_000
_INK_AA_OFF = 300_000


# ---------------------------------------------------------------------------
# High-variation envelope cap (CRC / rolling-counter style channels).
#
# Keep the previous private constant/helper surface for tests and local probes,
# but classify raw samples through RenderProfile. Production paths bind one
# profile per raw channel and choose the width BEFORE envelope generation.
# ---------------------------------------------------------------------------
_HIGH_VARIATION_BUCKET_BUDGET = DENSE_DISCRETE_BUCKET_BUDGET


def high_variation_bucket_width(values, pixel_width: int) -> int:
    """Compatibility wrapper for callers that already hold raw values."""
    arr = np.asarray(values).reshape(-1)
    profile = classify_render_profile(
        np.arange(arr.size, dtype=np.float64),
        arr,
        source_revision=None,
    )
    return bucket_width_for(
        profile, mode="subplot", pixel_width=pixel_width, interactive=False,
    )


def _capped_hidpi_scale(base_width, requested=_HIDPI_COPY_SCALE):
    """Return the effective magnification for a hi-DPI render.

    Clamps ``requested`` to ``[1.0, _HIDPI_MAX_WIDTH / base_width]`` so the
    result never downscales below 1× and the rendered width never exceeds
    ``_HIDPI_MAX_WIDTH``. A non-positive ``base_width`` (degenerate widget)
    falls back to 1× rather than dividing by zero.
    """
    try:
        bw = float(base_width)
    except (TypeError, ValueError):
        return 1.0
    if bw <= 0:
        return 1.0
    eff = max(1.0, float(requested))
    cap = _HIDPI_MAX_WIDTH / bw
    if cap < 1.0:
        # Canvas is already wider than the ceiling — do not magnify (1×),
        # but never downscale the source.
        return 1.0
    return min(eff, cap)


# Degenerate / non-finite y_span bucket. Must NOT be 0: log2(1.0)*30 == 0 is a
# legitimate bucket for normalized / 0-1 flag channels (B4).
_Y_SPAN_DEGENERATE_KEY = -(1 << 30)


def _quantize_y_span_key(y_span: float) -> int:
    """Quantize a Y view span into a stable, change-sensitive bucket index.

    Folded into the per-line refresh cache key so a PURE-Y narrow (box-zoom Y,
    scroll-zoom Y, a stale narrow-Y carried across a view switch) — which leaves
    xlim and the effective bucket width unchanged and would otherwise be gated
    out as a no-op refresh — still invalidates the cache and lets the Y-overflow
    wall guard re-evaluate. Uses a LOG bucket (~2.4 % per step, the natural
    log-2 / 30 grid) so a real Y zoom always crosses a boundary while float
    jitter on a static window stays in one bucket. y_span <= 0 / non-finite
    (degenerate / collapsed handle) maps to ``_Y_SPAN_DEGENERATE_KEY``, which
    is deliberately outside the log2 bucket space so it never collides with
    ``y_span == 1.0`` (B4).
    """
    try:
        ys = float(y_span)
    except (TypeError, ValueError):
        return _Y_SPAN_DEGENERATE_KEY
    if not np.isfinite(ys) or ys <= 0.0:
        return _Y_SPAN_DEGENERATE_KEY
    # ~30 buckets per octave: fine enough to catch any meaningful Y zoom,
    # coarse enough to absorb sub-percent autorange jitter on a static window.
    return int(round(np.log2(ys) * 30.0))


def _finite_x_coverage(values):
    """Return the actual finite X extent bound into a PlotDataItem."""
    try:
        arr = np.asarray(values, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return None
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return (float(np.min(finite)), float(np.max(finite)))


def _legacy_positions_envelope():
    """Return the current legacy-module seam for tests that monkeypatch it."""
    for module_name in (
        "mf4_analyzer.ui.pg_canvases",
        "mf4_analyzer.ui.pg_canvas.canvas",
    ):
        module = sys.modules.get(module_name)
        func = getattr(module, "positions_envelope", None) if module is not None else None
        if func is not None:
            return func
    from mf4_analyzer.signal._envelope_cutils import positions_envelope

    return positions_envelope


class Renderer(_CanvasBackref):
    """Viewport envelope refresh and export behavior.

    All state remains on the owning canvas; this object only owns behavior and
    preserves canvas monkeypatch seams for moved methods.
    """

    _delegate_names = frozenset({
        "_current_pixel_width",
        "_effective_pixel_width",
        "_refresh_visible_data",
        "_build_painter_path",
        "_build_painter_path_loop",
        "_render_path_to_pixmap",
        "grab_pixmap",
        "_grab_widget_scaled",
    })

    def _current_pixel_width(self) -> int:
        """Pixel width of the primary chart area (used as the envelope
        bucket count)."""
        primary = self._primary_xaxis_ax
        if primary is None:
            return self.MAX_PTS
        vb = primary.view_box
        if vb is None:
            return self.MAX_PTS
        try:
            rect = vb.sceneBoundingRect()
            w = int(max(1, rect.width()))
            return w
        except Exception:
            return self.MAX_PTS

    def _effective_pixel_width(self, pixel_width: int,
                               *, source_len=None, dense_count=None) -> int:
        """Envelope bucket count, capped by channel count in OVERLAY mode.

        Background (measured, real HDF 6-channel ~129.5 kHz overlay, 1920 px
        canvas, offscreen ``QWidget.grab()`` median synchronous paint):

          full X + wide Y (auto)        13.0 ms   (~18108 displayed pts)
          narrow Y + X zoom-in (BAD)    58.1 ms   (~19932 displayed pts)
          BAD + buckets capped to 700   29.8 ms   (8400 pts)
          BAD + buckets capped to 350   15.7 ms   (4200 pts)

        Displayed-point count is essentially constant (~20k) across all
        cases, yet paint cost swings 4–5×: in a narrow-Y + X-zoom regime each
        envelope bucket's min/max pair becomes a full-height vertical stroke
        spanning the whole canvas, so the cost is RASTER FILL, linear in the
        NUMBER of vertical strokes (= bucket count), NOT in the data volume.
        Y-clip (design Task 2) does NOT help: on-screen strokes are already
        full-height and Qt clips off-screen segments, so clipping changes
        neither the stroke count nor the on-screen height. Reducing buckets
        (design Task 3) is the only lever that scales the cost down linearly
        (58 → 30 → 16 ms as buckets drop 19932 → 8400 → 4200).

        Overlay's aux ViewBoxes fully overlap at one full-plot rect, so all
        curves repaint as ONE region; the cost ceiling is the SUM of strokes
        across curves. Cap each curve to::

            cap = _AA_OVERLAY_SEGMENT_OFF * K / (2 * curve_count)

        buckets (×2 because positions_envelope emits ~2 samples per bucket: a
        min and a max), with ``K = _OVERLAY_BUCKET_BUDGET_MULT = 1.3``. The
        ``× K`` is the key correction over the original ``/ (2*curve_count)``:
        without it the summed displayed-point count landed exactly AT the
        AA-off threshold (and integer-division truncation could dip BELOW it),
        so the quality gate's ``metric > off_budget`` test could flip AA back
        ON for some channel counts — re-enabling the expensive AA compositing
        in precisely the dense overlay this cap exists to speed up. With
        K=1.3 the summed count sits ~1.3× the threshold for every channel
        count in 2..8, keeping AA reliably OFF while the per-curve bucket cap
        is still far below full ``pixel_width`` so the raster-fill speedup is
        preserved.

        Measured (real HDF, 6-channel overlay, 1920 px, offscreen grab()
        median): uncapped narrow-Y/X-zoom 40.1 ms; original ``/(2N)`` cap
        18.9 ms (summed 7008, AT threshold); K=1.3 cap ~20–22 ms (summed
        ~9098, reliably > 7000) — a small, deliberate paint cost traded for a
        guaranteed-off AA state, still ~2× faster than uncapped.

        SUBPLOT / SINGLE modes keep the full ``pixel_width``: their rows are
        disjoint short device rectangles (and carry DeviceCoordinateCache),
        so the dense-vertical-stroke regime that motivates the cap does not
        arise there — capping them would only coarsen those plots for no
        paint win.
        """
        try:
            pw = int(pixel_width)
        except (TypeError, ValueError):
            return pixel_width
        if pw < 1:
            pw = 1
        if not getattr(self, "_overlay_mode", False):
            # SUBPLOT / SINGLE. Legacy single-arg calls (no density kwargs)
            # keep the full pixel_width — disjoint short rows never hit the
            # full-height-stroke wall on their own. The per-channel
            # dense-stack cap engages ONLY when the refresh loop supplies the
            # channel's source_len AND the count of dense channels: >= 2 dense
            # wideband rows stacked turn the per-frame raster-fill cost into a
            # SUM of full-height walls (the 显示原始 re-show regression). See the
            # _SUBPLOT_DENSE_* docstring above.
            return self._subplot_effective_width(pw, source_len, dense_count)
        curve_count = len(self._channel_lines) if self._channel_lines else 0
        if curve_count <= 0:
            return pw
        try:
            budget = int(self._AA_OVERLAY_SEGMENT_OFF)
        except (TypeError, ValueError, AttributeError):
            return pw
        cap = int(budget * _OVERLAY_BUCKET_BUDGET_MULT / (2 * curve_count))
        return max(1, min(pw, cap))

    @staticmethod
    def _subplot_effective_width(pw: int, source_len, dense_count) -> int:
        """Per-channel subplot bucket cap for the dense-stack raster wall.

        Returns ``pw`` unchanged (no cap) when:
          * no density context was supplied (legacy single-arg call), or
          * this channel is NOT dense (decimation ratio below the threshold —
            it's a thin line, not a fill wall), or
          * fewer than 2 dense channels are stacked (a single/few dense rows
            is the already-fast baseline — coarsening it would only hurt
            fidelity for no paint win).

        Otherwise caps the dense row to
        ``_SUBPLOT_DENSE_BUCKET_BUDGET / dense_count`` buckets, floored at
        ``_SUBPLOT_DENSE_MIN_BUCKETS`` so a row never degenerates, so the
        summed dense bucket count across rows is bounded.
        """
        if source_len is None or dense_count is None:
            return pw
        try:
            slen = int(source_len)
            n_dense = int(dense_count)
        except (TypeError, ValueError):
            return pw
        if n_dense < 2:
            return pw
        # Is THIS channel dense? (decimation = source samples per bucket).
        if pw <= 0 or slen / pw < _SUBPLOT_DENSE_DECIMATION:
            return pw
        cap = int(_SUBPLOT_DENSE_BUCKET_BUDGET / n_dense)
        cap = max(_SUBPLOT_DENSE_MIN_BUCKETS, cap)
        return max(1, min(pw, cap))

    def _refresh_visible_data(self, *, xlim_override=None, interactive=False):
        """Bind one envelope window without mutating the owning ViewBox.

        ``xlim_override`` is a display-buffer window used only by envelope
        generation, range keys, and the refresh signature.  ``interactive``
        selects the RenderProfile's coarse budget and skips settled tail work.
        The returned tuple (also stored as ``_display_x_coverage`` on the
        canvas) is the conservative intersection of actual finite X extents
        successfully bound into all visible PlotDataItems.
        """
        self._refresh_pending = False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            return getattr(self, "_display_x_coverage", None)
        try:
            view_xlim = self._primary_xaxis_ax.get_xlim()
        except Exception:
            return getattr(self, "_display_x_coverage", None)
        if xlim_override is None:
            xlim = (float(view_xlim[0]), float(view_xlim[1]))
        else:
            try:
                x0, x1 = xlim_override
                x0, x1 = float(x0), float(x1)
                if not np.isfinite(x0) or not np.isfinite(x1):
                    raise ValueError("non-finite xlim override")
            except (TypeError, ValueError):
                _log.warning("invalid display-buffer xlim %r", xlim_override)
                return getattr(self, "_display_x_coverage", None)
            xlim = (x1, x0) if x1 < x0 else (x0, x1)
        pixel_width = self._current_pixel_width()
        # Overlay mode caps the bucket count by channel count so the dense
        # narrow-Y vertical-stroke wall stays within the raster-fill budget
        # (see _effective_pixel_width). Subplot/single keep full pixel_width
        # EXCEPT when >= 2 high-density (wideband) channels are stacked, where
        # the per-channel dense cap (keyed off source_len + dense_count) bounds
        # the summed full-height-stroke raster wall — the 显示原始 re-show
        # regression. dense_count is computed up-front so every dense row gets
        # the same per-row budget share.
        overlay = bool(getattr(self, "_overlay_mode", False))
        dense_count = 0
        if not overlay and pixel_width > 0:
            for _n, _entry in self.channel_data.items():
                if _n not in self._channel_lines:
                    continue
                try:
                    _slen = len(_entry[1])
                except Exception:
                    continue
                if _slen / pixel_width >= _SUBPLOT_DENSE_DECIMATION:
                    dense_count += 1
        # Overlay path is channel-count capped (no per-channel kwargs needed);
        # subplot resolves per channel inside the loop.
        overlay_effective_width = self._effective_pixel_width(pixel_width)
        positions_envelope = _legacy_positions_envelope()
        coverage_by_channel = getattr(
            self, "_display_x_coverage_by_channel", None,
        )
        if coverage_by_channel is None:
            coverage_by_channel = {}
            self._display_x_coverage_by_channel = coverage_by_channel
        active_coverages = []
        active_channel_count = 0

        updated_any = False
        last_effective_width = overlay_effective_width
        # Per-frame ink state (reset every refresh): True once ANY line is
        # found over _INK_OFF_BUDGET. The idle-AA gate reads this to hold AA
        # OFF over an ink band.
        frame_ink_high = False
        # Device pixel ratio for the whole canvas: ink is measured in DEVICE
        # pixels so the budget is comparable across machines (dpr 1 vs 2).
        try:
            dpr = float(self._glw.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        # Iterate by COMPOSITE (fid, name) key: the per-line viewport caches
        # (_last_range_key / _line_ink_state) MUST key on the composite key,
        # never the display name, or two same-named channels from different
        # files cross-contaminate — one channel's cache-HIT would suppress the
        # other's refresh and the curve would freeze/vanish on un-check
        # (pyqt-ui/2026-06-11-cache-key-stability-id-reuse-and-param-roundtrip).
        # The display ``name`` is still passed to _quantize_range_key so
        # range_key[0] stays the channel name for existing key-shape consumers.
        composite_items = list(self._channel_lines.composite_items())
        for ck, name, (axis_facade, line_facade) in composite_items:
            entry = self.channel_data.get(ck)
            if entry is None:
                continue
            # Skip curves the user hid via 显示原始/显示滤波后. Their data is
            # still in channel_data, but a hidden PlotDataItem must not be
            # re-enveloped + setData on every pan/zoom tick — that doubled the
            # per-frame work whenever a filter overlay was on (each channel
            # carries a hidden original AND a visible companion, so a hidden
            # original kept getting dragged/recomputed). Re-showing rebinds via
            # set_original_lines_visible / a full re-plot, so nothing is lost.
            try:
                pdi_vis = line_facade.plot_data_item
                if pdi_vis is not None and not pdi_vis.isVisible():
                    continue
            except Exception:
                pass
            active_channel_count += 1
            t, sig, color, _unit = entry

            if overlay:
                effective_width = overlay_effective_width
            else:
                effective_width = self._effective_pixel_width(
                    pixel_width, source_len=len(sig), dense_count=dense_count,
                )
            profiles = self._channel_render_profiles
            profile = profiles.get(ck)
            source_revision = source_revision_for(t, sig)
            if profile is None or profile.source_revision != source_revision:
                profile = classify_render_profile(
                    t, sig,
                    source_revision=source_revision,
                )
                profiles[ck] = profile
            effective_width = bucket_width_for(
                profile,
                mode="overlay" if overlay else "subplot",
                pixel_width=effective_width,
                interactive=bool(interactive),
            )

            # Once the dense raster is ready, pan/zoom ticks are transform
            # only. The cached QGraphicsPixmapItem follows the ViewBox; the
            # authoritative PDI is rebound exactly once by the settled pass.
            dense_entry = self._dense_raster.entry_for(ck)
            cached_coverage = coverage_by_channel.get(ck)
            raster_coverage = (
                (dense_entry.data_rect[0], dense_entry.data_rect[1])
                if dense_entry is not None else None
            )
            if (
                interactive
                and self._raster_backend_eligible(ck)
                and dense_entry is not None
                and self._coverage_contains(cached_coverage, xlim)
                and self._coverage_contains(raster_coverage, xlim)
            ):
                if cached_coverage is not None:
                    active_coverages.append(cached_coverage)
                prev_ink_state = self._line_ink_state.get(ck)
                if prev_ink_state is not None and prev_ink_state[1]:
                    frame_ink_high = True
                last_effective_width = effective_width
                continue

            # Current Y view span for THIS line. Folded (quantized) into the
            # range key so a pure-Y narrow (box-zoom Y / scroll Y / stale narrow
            # Y carried across a view switch) — which leaves xlim and
            # effective_width unchanged — still invalidates the cache and lets
            # the ink budget re-evaluate. get_ylim failure is UNKNOWN, not
            # zero: skip ink recording below so a broken handle cannot persist
            # a fake 0.0 reading that later frames treat as "measured low"
            # (B2). The range key still advances via the degenerate sentinel.
            try:
                _ylo, _yhi = axis_facade.get_ylim()
                y_span = abs(float(_yhi) - float(_ylo))
            except Exception:
                y_span = None
            y_key = _quantize_y_span_key(
                y_span if y_span is not None else float("nan"),
            )

            # Range-key gate: if the key didn't change since the last flush,
            # skip the envelope+setData work entirely. This keeps repeated
            # _flush_pending_refresh() calls with the same xlim/ylim a no-op.
            # y_key is APPENDED to the x-key tuple (not nested) so range_key[0]
            # stays the channel name for existing key-shape consumers.
            range_key = _quantize_range_key(name, xlim, effective_width) + (
                source_revision, y_key, bool(interactive),
            )
            cached_coverage = coverage_by_channel.get(ck)
            if (
                self._last_range_key.get(ck) == range_key
                and cached_coverage is not None
            ):
                # Cache hit: preserve the ink state recorded for this line at
                # the last (un-skipped) flush so a no-op refresh does not clear
                # a still-high ink band (AA must stay off until the geometry
                # actually changes, not until the next real recompute).
                prev_ink_state = self._line_ink_state.get(ck)
                if prev_ink_state is not None and prev_ink_state[1]:
                    frame_ink_high = True
                last_effective_width = effective_width
                active_coverages.append(cached_coverage)
                continue

            is_monotonic = self._channel_is_monotonic.get(ck)
            try:
                env_t, env_s = positions_envelope(
                    t, sig,
                    xlim=xlim,
                    pixel_width=effective_width,
                    is_monotonic=is_monotonic,
                )
            except Exception as exc:
                _log.warning(
                    "positions_envelope failed for %r at xlim=%r: %s",
                    name, xlim, exc,
                )
                continue

            # Ink budget (universal 兜底, see module constants). The envelope is
            # already in hand, so the device-pixel vertical ink this line will
            # paint costs one vectorized diff. Over budget → cut the bucket
            # count proportionally (spec §4.1) and recompute the envelope ONCE
            # at that width (numpy over the visible window, ms-level; only paid
            # in the over-budget case), and flag the frame so AA stays off.
            # Row height is THIS line's own axis (subplot rows are independent).
            # Unknown y_span (get_ylim failed) skips measurement entirely —
            # never invent 0.0 ink (B2).
            try:
                row_height_px = float(
                    axis_facade.view_box.sceneBoundingRect().height()
                )
            except Exception:
                row_height_px = 0.0
            line_ink = None
            if y_span is not None:
                try:
                    line_ink = envelope_ink_dev_px(
                        env_s,
                        y_span=y_span,
                        row_height_px=row_height_px,
                        dpr=dpr,
                    )
                except Exception:
                    line_ink = None
            line_ink_high = False
            if line_ink is not None and line_ink > _INK_OFF_BUDGET:
                capped_width = int(
                    effective_width * _INK_OFF_BUDGET / line_ink
                )
                # Clamp so the cut can only ever REDUCE the bucket count (never
                # raise it above what overlay/subplot already chose) and never
                # coarsen past the silhouette floor.
                capped_width = max(
                    _INK_MIN_BUCKETS, min(capped_width, effective_width),
                )
                if capped_width < effective_width:
                    try:
                        env_t, env_s = positions_envelope(
                            t, sig,
                            xlim=xlim,
                            pixel_width=capped_width,
                            is_monotonic=is_monotonic,
                        )
                    except Exception as exc:
                        _log.warning(
                            "ink-capped positions_envelope failed for %r: %s",
                            name, exc,
                        )
                    else:
                        effective_width = capped_width
                # Even when the width was already at/below the floor we still
                # hold AA off — the ink band is present, just already coarse.
                line_ink_high = True
                frame_ink_high = True

            last_effective_width = effective_width

            try:
                line_facade.plot_data_item.setData(env_t, env_s)
            except Exception as exc:
                _log.warning("PlotDataItem.setData failed for %r: %s", name, exc)
                if self._raster_backend_eligible(ck):
                    self._dense_raster.deactivate_channel(ck)
                previous_coverage = coverage_by_channel.get(ck)
                if previous_coverage is not None:
                    active_coverages.append(previous_coverage)
            else:
                # The recorded ink is the line's PRE-cap demand for this
                # geometry (what the clamp above was derived from), so a
                # cache-HIT frame and the AA gate see the same number the
                # decision was made on. Recorded BEFORE the raster branch:
                # _raster_backend_eligible reads this very entry, and a
                # one-frame-stale read would make the backend choice lag the
                # geometry by a frame — exactly the flap the band's hysteresis
                # exists to prevent. Unknown measurement (ylim/ink failure)
                # leaves any prior record untouched rather than writing 0.0.
                if line_ink is not None:
                    self._line_ink_state[ck] = (float(line_ink), line_ink_high)
                if self._raster_backend_eligible(ck) and not overlay:
                    self._dense_raster.update_channel(
                        ck,
                        axis_facade,
                        line_facade.plot_data_item,
                        env_t,
                        env_s,
                        color=color,
                        source_revision=source_revision,
                        generation=self._interaction_generation,
                        data_rect=(float(xlim[0]), float(xlim[1])),
                    )
                else:
                    self._dense_raster.deactivate_channel(ck)
                self._last_range_key[ck] = range_key
                updated_any = True
                actual_coverage = _finite_x_coverage(env_t)
                if actual_coverage is None:
                    coverage_by_channel.pop(ck, None)
                else:
                    coverage_by_channel[ck] = actual_coverage
                    active_coverages.append(actual_coverage)

        display_coverage = None
        if active_channel_count and len(active_coverages) == active_channel_count:
            coverage_lo = max(item[0] for item in active_coverages)
            coverage_hi = min(item[1] for item in active_coverages)
            if coverage_lo <= coverage_hi:
                display_coverage = (float(coverage_lo), float(coverage_hi))
        self._display_x_coverage = display_coverage

        # Publish the frame's ink state for the idle-AA gate (quality.py).
        self._frame_ink_high = bool(frame_ink_high)

        # Debounced tail work: retick axes and notify listeners only once after
        # rapid drag ticks settle, instead of blocking every mouse-move event.
        signature = (
            float(xlim[0]), float(xlim[1]), int(last_effective_width),
            bool(interactive),
        )
        if not updated_any and signature == self._last_refresh_signature:
            return display_coverage
        self._last_refresh_signature = signature
        if interactive:
            return display_coverage
        self._tick_density_controller._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed()
        self.schedule_idle_quality()
        return display_coverage

    def _build_painter_path(self, t, s) -> QPainterPath:
        """Build a ``QPainterPath`` from envelope output. We work in data
        space here; the eventual blit translates to pixel space via the
        ViewBox's transform. Building the path once per cache key means
        repeated paint events (e.g. cursor overlay) do NOT re-walk the
        envelope arrays.

        Perf (T9): the all-finite case — which is the production hot path,
        since :func:`positions_envelope` bails to the numpy reference on any
        NaN in the visible window — is vectorized through
        ``pyqtgraph.functions.arrayToQPath(x, y, connect='all')``. That
        builds the ``QPainterPath`` from the numpy ``x``/``y`` arrays in C
        (the same QPolygonF→addPolygon fast path ``PlotCurveItem`` uses
        internally), replacing the pure-Python per-point
        ``moveTo``/``lineTo`` loop that dominated the ~10.7 ms pan frame
        (see signal-processing/2026-05-28-component-speedup-does-not-imply-
        end-to-end-target). For all-finite input the resulting path is
        byte-identical to the old loop (1 MoveTo + N-1 LineTo, same
        coordinates, same order).

        The NaN-gap path still goes through :meth:`_build_painter_path_loop`
        unchanged, because ``arrayToQPath``'s ``connect='all'`` would bridge
        the gap with a spurious line and its ``connect='finite'`` backfills
        non-finite samples with their neighbour (extra duplicate elements)
        and drops single-point chunks — neither reproduces the old loop's
        break-the-subpath discontinuity geometry.
        """
        n = min(len(t), len(s))
        if n == 0:
            return QPainterPath()
        t = np.asarray(t)
        s = np.asarray(s)
        # Fast path: >= 2 samples, all finite → vectorized C build.
        # asammdf's min/max envelope over a finite window is finite, so
        # this is the branch the production pan loop takes every frame.
        # We require n >= 2 because arrayToQPath drops a lone point
        # (elementCount 0), whereas the old loop emitted a bare moveTo
        # (elementCount 1) — routing n < 2 through the loop keeps that
        # degenerate single-point geometry byte-identical.
        if n >= 2 and np.isfinite(t[:n]).all() and np.isfinite(s[:n]).all():
            # arrayToQPath needs same-length contiguous float arrays; the
            # envelope output is float64 but slice to n and enforce
            # contiguity defensively (a view of a larger buffer would not
            # be C-contiguous). finiteCheck=False because we just proved
            # finiteness — this skips arrayToQPath's internal isfinite scan.
            x = np.ascontiguousarray(t[:n], dtype=np.float64)
            y = np.ascontiguousarray(s[:n], dtype=np.float64)
            return pg.functions.arrayToQPath(x, y, connect="all",
                                             finiteCheck=False)
        # Slow path: NaN segments present — break the sub-path on each
        # discontinuity, matches asammdf's handling. Byte-identical to the
        # historical loop (T9 preserved this verbatim for gap parity).
        return self._build_painter_path_loop(t, s, n)

    def _build_painter_path_loop(self, t, s, n) -> QPainterPath:
        """Pure-Python per-point builder used only when NaN gaps are
        present. Kept byte-identical to the pre-T9 ``_build_painter_path``
        loop so the discontinuity geometry (bare ``moveTo`` after a gap, no
        element for NaN samples) is preserved exactly.
        """
        path = QPainterPath()
        # Skip NaN segments by breaking the sub-path; matches asammdf's
        # discontinuity handling.
        started = False
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

    def _render_path_to_pixmap(self, path: QPainterPath, color: str, pixel_width: int) -> QPixmap:
        """Render the QPainterPath into a QPixmap once per cache entry.

        Antialiasing is OFF (matches asammdf strategy from design §5.2
        evidence). The pixmap is sized to ``pixel_width × 200`` as a
        proxy chart-area; T6 will plumb the actual ViewBox geometry once
        the overlay/cursor layer lands.
        """
        height = 200
        pix = QPixmap(max(1, pixel_width), height)
        pix.fill(Qt.transparent)
        # Painter on a 1×1 pixmap is a no-op; guard the degenerate case.
        if pix.isNull() or pix.width() < 2 or pix.height() < 2:
            return pix
        try:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing, False)
            pen = QPen()
            try:
                pen.setColor(pg.mkColor(color))
            except Exception:
                pen.setColor(QColor(color))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.end()
        except Exception:
            # Degenerate-rect fallback (pyqt-ui/2026-04-25-tightbbox-
            # survives-offscreen-qt): a 1×1 transparent pixmap is still
            # a valid QPixmap; callers test pix.isNull(), not contents.
            pass
        return pix

    def grab_pixmap(self, scale: float = 1.0) -> QPixmap:
        """Return a ``QPixmap`` snapshot of the canvas.

        ``scale`` (spec §E) renders the scene at a HIGHER resolution for
        crisp, DPI-independent copy/save output. The effective factor is
        capped by ``_capped_hidpi_scale`` (floor 1×, width ceiling
        ``_HIDPI_MAX_WIDTH``) so export stays fast.

        Order of attempts:
        1. ``QWidget.grab()`` on the outer widget (covers GraphicsLayoutWidget
           + any sibling overlays MainWindow may add later). For ``scale`` > 1
           the grabbed bitmap is smoothly magnified to the capped target size.
           This keeps interactive copy to one widget paint instead of a
           screen-size grab plus a second high-DPI render in the click handler.
        2. Direct ``self._glw.grab()`` if the outer grab returned null.
        3. A 1×1 transparent fallback pixmap if both fail.

        Step 3 is the degenerate-rect fallback the
        ``2026-04-25-tightbbox-survives-offscreen-qt`` lesson prescribes:
        callers MUST check ``pix.isNull()`` rather than assuming a
        well-formed image. The degenerate fallback (and the isNull guard
        on every primary attempt) is preserved at ``scale`` > 1 too — we
        never default to a full-canvas-sized guess on a failed grab.
        """
        # Resolve the effective (capped) factor from the OUTER widget's
        # current width — the same surface step 1 grabs. Dense exports keep
        # the current screen rendering state and skip 2× magnification.
        base_w = max(1, int(self.width()))
        affordable = self._quality._export_aa_affordable()
        eff_scale = _capped_hidpi_scale(base_w, scale) if affordable else 1.0

        def _grab_first_good():
            for target in (self._c, getattr(self, "_glw", None)):
                if target is None:
                    continue
                try:
                    pix = self._grab_widget_scaled(target, eff_scale)
                except Exception:
                    pix = None
                if pix is not None and not pix.isNull() and pix.width() > 0 and pix.height() > 0:
                    return pix
            return None

        # Few-channel exports keep the crisp forced-AA path. Dense exports
        # are what-you-see-is-what-you-get and avoid re-enabling AA.
        if affordable:
            with self._quality._curves_antialiased():
                pix = _grab_first_good()
        else:
            pix = _grab_first_good()
        if pix is not None:
            return pix
        # Final fallback: a 1×1 transparent pixmap. Tests gate on
        # geometry, not pixels, so this is acceptable when offscreen Qt
        # cannot realize the widget at all. We do NOT scale this up — a
        # 1×1 degenerate marker stays 1×1 so callers' isNull/size guards
        # behave identically regardless of the requested scale.
        fallback = QPixmap(1, 1)
        fallback.fill(Qt.transparent)
        return fallback

    @staticmethod
    def _grab_widget_scaled(widget, eff_scale: float) -> QPixmap:
        """Grab ``widget`` at ``eff_scale``×.

        At 1× this is exactly ``widget.grab()`` (unchanged legacy path).
        Above 1× the same grabbed bitmap is smoothly scaled to
        ``round(w*scale) × round(h*scale)`` so the copy path avoids a second
        synchronous widget render. Returns a null pixmap when the widget has
        no realizable geometry (caller guards on ``isNull()``).
        """
        # Always grab once first. This is the legacy capture primitive and
        # the realizability probe: if the widget cannot be grabbed (null /
        # zero-size — e.g. offscreen Qt could not realize it), we return
        # that null result so grab_pixmap cascades to its 1×1 degenerate
        # fallback instead of synthesizing a blank full-canvas QImage.
        base = widget.grab()
        if eff_scale <= 1.0:
            return base
        if base is None or base.isNull() or base.width() <= 0 or base.height() <= 0:
            return base
        w = int(widget.width())
        h = int(widget.height())
        if w <= 0 or h <= 0:
            # No geometry to magnify — return the plain grab so the
            # caller's null/size guard runs against the real result.
            return base
        tw = max(1, int(round(w * eff_scale)))
        th = max(1, int(round(h * eff_scale)))
        return base.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
