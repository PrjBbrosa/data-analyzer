"""Visible data refresh and export helpers for the pyqtgraph canvas."""

from __future__ import annotations

import logging
import sys

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from . import _binding  # noqa: F401

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


_MISSING = object()


class _CanvasBackref:
    _delegate_names = frozenset()

    def __init__(self, canvas):
        object.__setattr__(self, "_c", canvas)

    def __getattribute__(self, name):
        if name not in {
            "_c",
            "_delegate_names",
            "__dict__",
            "__class__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
        }:
            delegate_names = object.__getattribute__(self, "_delegate_names")
            if name in delegate_names:
                canvas = object.__getattribute__(self, "_c")
                value = getattr(canvas, "__dict__", {}).get(name, _MISSING)
                if value is not _MISSING:
                    return value
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)


class Renderer(_CanvasBackref):
    """Viewport envelope refresh and export behavior.

    All state remains on the owning canvas; this object only owns behavior and
    preserves canvas monkeypatch seams for moved methods.
    """

    _delegate_names = frozenset({
        "_current_pixel_width",
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

    def _refresh_visible_data(self):
        """Recompute and display the viewport envelope for every channel."""
        self._refresh_pending = False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            return
        try:
            xlim = self._primary_xaxis_ax.get_xlim()
        except Exception:
            return
        pixel_width = self._current_pixel_width()
        positions_envelope = _legacy_positions_envelope()

        for name, (axis_facade, line_facade) in list(self._channel_lines.items()):
            entry = self.channel_data.get(name)
            if entry is None:
                continue
            t, sig, color, _unit = entry

            # Range-key gate: if the key didn't change since the last flush,
            # skip the envelope+setData work entirely. This keeps repeated
            # _flush_pending_refresh() calls with the same xlim a no-op.
            range_key = _quantize_range_key(name, xlim, pixel_width)
            if self._last_range_key.get(name) == range_key:
                continue

            is_monotonic = self._channel_is_monotonic.get(name)
            try:
                env_t, env_s = positions_envelope(
                    t, sig,
                    xlim=xlim,
                    pixel_width=pixel_width,
                    is_monotonic=is_monotonic,
                )
            except Exception as exc:
                _log.warning(
                    "positions_envelope failed for %r at xlim=%r: %s",
                    name, xlim, exc,
                )
                continue

            self._last_range_key[name] = range_key

            try:
                line_facade.plot_data_item.setData(env_t, env_s)
            except Exception as exc:
                _log.warning("PlotDataItem.setData failed for %r: %s", name, exc)

        # Debounced tail work: retick axes and notify listeners only once after
        # rapid drag ticks settle, instead of blocking every mouse-move event.
        self._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed()
        self._refresh = True
        self.schedule_idle_quality()

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

        # Few-channel exports keep the crisp forced-AA path. Dense exports are
        # what-you-see-is-what-you-get and avoid re-enabling AA for all curves.
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
