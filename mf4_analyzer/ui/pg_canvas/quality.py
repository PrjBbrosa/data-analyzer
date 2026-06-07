"""Interactive and idle quality helpers for the pyqtgraph canvas."""

from __future__ import annotations

from contextlib import contextmanager

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from . import _binding  # noqa: F401

import pyqtgraph as pg


_MISSING = object()


class _CanvasBackref:
    _delegate_names = frozenset()
    _owned_names = frozenset()

    def __init__(self, canvas):
        object.__setattr__(self, "_c", canvas)

    def __getattribute__(self, name):
        if name not in {
            "_c",
            "_delegate_names",
            "_owned_names",
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
        owned_names = object.__getattribute__(self, "_owned_names")
        delegate_names = object.__getattribute__(self, "_delegate_names")
        if name in owned_names or name in delegate_names:
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)


class QualityManager(_CanvasBackref):
    """Curve antialiasing and idle-quality policy.

    Owns the idle-AA timer and hysteresis state. Threshold constants remain on
    the canvas so existing tuning/tests can keep reading and overriding them.
    """

    _owned_names = frozenset({
        "aa_on",
        "density_allowed",
        "density_seeded",
        "timer",
    })

    _delegate_names = frozenset({
        "_collect_curve_items",
        "_set_curves_antialias",
        "_set_curves_cache_mode",
        "disable_interactive_quality",
        "schedule_idle_quality",
        "try_enable_idle_quality",
        "_idle_quality_allowed",
        "_idle_aa_density_ok",
        "_export_aa_affordable",
        "_curves_antialiased",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self.aa_on = False
        self.timer = QTimer(canvas)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.try_enable_idle_quality)
        self.density_allowed = False
        self.density_seeded = False

    def reset_for_rebuild(self):
        """Reset idle-AA runtime state after the curve set is rebuilt."""
        try:
            self.timer.stop()
        except Exception:
            pass
        self.aa_on = False
        self.density_allowed = False
        # Rebuild changes the curve set / point counts, so the next decision
        # must re-seed via the OFF threshold rather than inherit stale state.
        self.density_seeded = False

    def _collect_curve_items(self):
        """Every ``PlotCurveItem`` on the scene; ``[]`` if unreachable."""
        try:
            scene = self._glw.scene()
        except Exception:
            scene = None
        if scene is None:
            return []
        return [it for it in scene.items() if isinstance(it, pg.PlotCurveItem)]

    def _set_curves_antialias(self, on: bool) -> int:
        """Persistently set curve AA without repainting or changing data."""
        n = 0
        for it in self._collect_curve_items():
            try:
                it.opts["antialias"] = bool(on)
                n += 1
            except Exception:
                pass
        return n

    def _set_curves_cache_mode(self, mode) -> None:
        """Set the QGraphicsItem cache mode on every curve item.

        Fix D (2026-05-31): ``DeviceCoordinateCache`` lets hover /
        ``draw_idle`` blit the cached device-coordinate bitmap of the
        overlaid AA curves instead of re-rasterizing them every frame.
        The cache MUST be cleared (``NoCache``) on any range / geometry /
        resize / replot change, all of which converge on
        ``disable_interactive_quality`` (verified callers: _on_xrange_changed,
        reset_view_to_data_extents, the overlay Y-drag, the box-zoom hook,
        wheel zoom, and rebuild's AA reset).
        """
        for it in self._collect_curve_items():
            try:
                it.setCacheMode(mode)
            except Exception:
                pass

    def disable_interactive_quality(self):
        """Force the interactive path back to AA-off and cancel idle upgrade."""
        try:
            self.timer.stop()
        except Exception:
            pass
        if not self.aa_on:
            return
        self._set_curves_antialias(False)
        # Fix D: a stale device-coordinate cache would smear during the
        # pan/zoom that this call precedes. Clear unconditionally so no stale
        # cache survives mode switches.
        self._set_curves_cache_mode(QGraphicsItem.NoCache)
        self.aa_on = False
        try:
            self._glw.update()
        except Exception:
            pass

    def schedule_idle_quality(self):
        """Re-arm the single-shot idle-AA timer after a settled interaction."""
        try:
            self.timer.start()
        except Exception:
            pass

    def try_enable_idle_quality(self):
        """Idle timer slot: enable curve AA once every hands-off gate passes."""
        if self.aa_on:
            return
        if not self._idle_quality_allowed():
            return
        if self._set_curves_antialias(True) > 0:
            # Fix D (RECALIBRATED, subplot-only): DeviceCoordinateCache blits
            # the cached device-coordinate bitmap on subsequent hover /
            # draw_idle repaints instead of re-rasterizing. Measured 15-30x
            # win for SUBPLOT, but no win for OVERLAY where aux ViewBoxes
            # overlap at one full-plot rect.
            if not getattr(self, "_overlay_mode", False):
                self._set_curves_cache_mode(QGraphicsItem.DeviceCoordinateCache)
            self.aa_on = True
            try:
                self._glw.update()
            except Exception:
                pass

    def _idle_quality_allowed(self) -> bool:
        """Return True only while the user is hands-off and density is safe."""
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                return False
        except Exception:
            return False
        if self._overlay_axes.dragging:
            return False
        return self._idle_aa_density_ok()

    def _idle_aa_density_ok(self) -> bool:
        """Hysteresis density gate, branched on overlay vs subplot economics."""
        overlay = bool(getattr(self, "_overlay_mode", False))
        if overlay:
            on_budget = self._AA_OVERLAY_SEGMENT_ON
            off_budget = self._AA_OVERLAY_SEGMENT_OFF
        else:
            on_budget = self._AA_SUBPLOT_SEGMENT_ON
            off_budget = self._AA_SUBPLOT_SEGMENT_OFF

        sums: dict = {}
        total = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                self.density_allowed = False
                return False
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n

        if overlay:
            metric = total
        else:
            metric = max(sums.values()) if sums else 0

        if not self.density_seeded:
            self.density_allowed = metric <= off_budget
            self.density_seeded = True
        elif metric <= on_budget:
            self.density_allowed = True
        elif metric > off_budget:
            self.density_allowed = False
        return bool(self.density_allowed)

    def _export_aa_affordable(self) -> bool:
        """Return whether copy/export can afford forced curve antialiasing."""
        overlay = bool(getattr(self, "_overlay_mode", False))
        off_budget = (
            self._AA_OVERLAY_SEGMENT_OFF if overlay else self._AA_SUBPLOT_SEGMENT_OFF
        )
        sums: dict = {}
        total = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                return False
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n
        metric = total if overlay else (max(sums.values()) if sums else 0)
        return metric <= off_budget

    @contextmanager
    def _curves_antialiased(self):
        """Temporarily enable antialiasing for a grab, then restore it."""
        saved = []
        for it in self._collect_curve_items():
            try:
                saved.append((it, it.opts.get("antialias", False)))
                it.opts["antialias"] = True
            except Exception:
                pass
        try:
            yield
        finally:
            for it, prev in saved:
                try:
                    it.opts["antialias"] = bool(prev)
                except Exception:
                    pass
