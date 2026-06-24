"""Interactive and idle quality helpers for the pyqtgraph canvas."""

from __future__ import annotations

from contextlib import contextmanager

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg


class QualityManager(_CanvasBackref):
    """Curve antialiasing and idle-quality policy.

    Owns the idle-AA timer and hysteresis state. Threshold constants remain on
    the canvas so existing tuning/tests can keep reading and overriding them.
    """

    _owned_names = frozenset({
        "aa_on",
        "density_allowed",
        "density_seeded",
        "last_emitted_status",
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
        self.last_emitted_status = None

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
        self.last_emitted_status = None
        self._emit_quality_status_changed()

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
        timer_was_active = False
        try:
            timer_was_active = self.timer.isActive()
            self.timer.stop()
        except Exception:
            pass
        if not self.aa_on:
            # Hot path: after the first pan/zoom tick AA is already off and
            # the idle timer is stopped. quality_status() walks the scene, so
            # rebuild it only when cancelling a pending idle upgrade changed
            # the reader-facing state from yellow to red.
            if timer_was_active:
                self._emit_quality_status_changed()
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
        self._emit_quality_status_changed()

    def schedule_idle_quality(self):
        """Re-arm the single-shot idle-AA timer after a settled interaction."""
        try:
            self.timer.start()
        except Exception:
            pass
        self._emit_quality_status_changed()

    def try_enable_idle_quality(self):
        """Idle timer slot: enable curve AA once every hands-off gate passes."""
        if self.aa_on:
            self._emit_quality_status_changed()
            return
        if not self._idle_quality_allowed():
            self._emit_quality_status_changed()
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
        self._emit_quality_status_changed()

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
        # Universal Y-overflow wall guard: while any line is drawn data≫window
        # (full-height vertical-stroke 满高竖线墙, see renderer module constants)
        # the idle timer must NOT re-arm AA — the expensive AA compositing over a
        # raster-fill wall is exactly the cost this guard exists to avoid. The
        # bucket cap already coarsened the strokes; holding AA off keeps the
        # frame cheap until the user widens Y. Reuses the existing density gate
        # (no new AA pathway) by hard-failing it for the wall frame.
        if getattr(self, "_y_overflow_wall_active", False):
            self.density_allowed = False
            return False
        status = self._density_status()
        if status["error"]:
            self.density_allowed = False
            return False
        metric = status["metric"]
        on_budget = status["on_budget"]
        off_budget = status["off_budget"]

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
        status = self._density_status()
        if status["error"]:
            return False
        return status["metric"] <= status["off_budget"]

    def _density_status(self):
        overlay = bool(getattr(self, "_overlay_mode", False))
        if overlay:
            on_budget = int(self._AA_OVERLAY_SEGMENT_ON)
            off_budget = int(self._AA_OVERLAY_SEGMENT_OFF)
        else:
            on_budget = int(self._AA_SUBPLOT_SEGMENT_ON)
            off_budget = int(self._AA_SUBPLOT_SEGMENT_OFF)
        sums: dict = {}
        total = 0
        items = self._collect_curve_items()
        for it in items:
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                return {
                    "overlay": overlay,
                    "metric": 0,
                    "on_budget": on_budget,
                    "off_budget": off_budget,
                    "curve_count": len(items),
                    "error": True,
                }
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n
        metric = total if overlay else (max(sums.values()) if sums else 0)
        return {
            "overlay": overlay,
            "metric": int(metric),
            "on_budget": on_budget,
            "off_budget": off_budget,
            "curve_count": len(items),
            "error": False,
        }

    def quality_status(self):
        """Return the reader-facing AA status for the chart quality dot."""
        items = self._collect_curve_items()
        density = self._density_status()
        base = {
            "metric": density["metric"],
            "budget": density["off_budget"],
            "curve_count": density["curve_count"],
            "overlay": density["overlay"],
        }
        if not items:
            return {
                **base,
                "state": "red",
                "tooltip": "抗锯齿未激活：无曲线",
            }
        if density["error"]:
            return {
                **base,
                "state": "red",
                "tooltip": "抗锯齿未激活：曲线密度不可读取",
            }
        label = "叠加密度" if density["overlay"] else "曲线密度"
        if density["metric"] > density["off_budget"]:
            return {
                **base,
                "state": "red",
                "tooltip": (
                    f"抗锯齿未激活：{label} "
                    f"{density['metric']} > {density['off_budget']}"
                ),
            }
        actual_on = True
        for it in items:
            try:
                actual_on = actual_on and bool(it.opts.get("antialias", False))
            except Exception:
                actual_on = False
        if self.aa_on and actual_on:
            return {
                **base,
                "state": "green",
                "tooltip": "抗锯齿已完成",
            }
        try:
            timer_active = self.timer.isActive()
        except Exception:
            timer_active = False
        if timer_active or bool(getattr(self, "_refresh_pending", False)):
            return {
                **base,
                "state": "yellow",
                "tooltip": "抗锯齿等待空闲刷新",
            }
        return {
            **base,
            "state": "red",
            "tooltip": "抗锯齿未激活",
        }

    def _emit_quality_status_changed(self):
        try:
            status = self.quality_status()
            if status == self.last_emitted_status:
                return
            self.last_emitted_status = status
            self.quality_status_changed.emit(status)
        except Exception:
            pass

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
