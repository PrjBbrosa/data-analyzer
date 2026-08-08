"""Interactive and idle quality helpers for the pyqtgraph canvas."""

from __future__ import annotations

from contextlib import contextmanager

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg

from .renderer import _INK_AA_OFF, _INK_AA_ON, _SUBPLOT_DENSE_DECIMATION


class QualityManager(_CanvasBackref):
    """Curve antialiasing and idle-quality policy.

    Owns the idle-AA timer and hysteresis state. Threshold constants remain on
    the canvas so existing tuning/tests can keep reading and overriding them.
    """

    _owned_names = frozenset({
        "aa_on",
        "density_allowed",
        "density_seeded",
        "ink_allowed",
        "ink_seeded",
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
        # Ink-sum hysteresis state (spec §4.2), mirrors density_allowed /
        # density_seeded above but tracks the SUMMED per-line ink of the
        # native-AA-path lines rather than displayed point count.
        self.ink_allowed = False
        self.ink_seeded = False
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
        self.ink_allowed = False
        self.ink_seeded = False
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

    def _raster_covered_curve_items(self):
        """Visible raster-backed curves fully replaced by a ready raster."""
        try:
            if self._dense_raster.quality_status().get("state") != "green":
                return set()
        except Exception:
            return set()
        covered = set()
        try:
            entries = self._channel_lines.composite_items()
        except Exception:
            return covered
        for ck, _name, (_axis, line) in entries:
            # Shared admission predicate (spec §4.3): dense-discrete by
            # strategy, or a line the ink budget admitted to the raster path.
            if not self._raster_backend_eligible(ck):
                continue
            pdi = getattr(line, "plot_data_item", None)
            try:
                if (
                    pdi is not None
                    and pdi.isVisible()
                    and self._dense_raster.entry_for(ck) is not None
                ):
                    covered.add(pdi.curve)
            except Exception:
                continue
        return covered

    def _native_aa_curve_items(self):
        covered = self._raster_covered_curve_items()
        return [it for it in self._collect_curve_items() if it not in covered]

    def _frame_native_ink_total(self) -> float:
        """Sum this frame's per-line ink for lines still on the native-AA
        paint path (spec §4.2 / renderer ``_line_ink_state``).

        Excludes lines whose curve is already covered by a settled
        dense-raster entry (``_raster_covered_curve_items`` — the raster
        upgrade already replaced their paint cost, so their recorded ink must
        not keep blocking AA for the rest of the frame) and lines whose
        ``PlotDataItem`` is not currently visible. Matched by COMPOSITE
        ``(data_id, name)`` identity, never the display name, for the same
        multi-file-same-name reason the renderer's own per-line cache uses
        composite keys.
        """
        ink_state = getattr(self, "_line_ink_state", None)
        if not ink_state:
            return 0.0
        covered = self._raster_covered_curve_items()
        pdi_by_ck = {}
        try:
            entries = self._channel_lines.composite_items()
        except Exception:
            entries = ()
        for ck, _name, (_axis, line) in entries:
            pdi_by_ck[ck] = getattr(line, "plot_data_item", None)
        total = 0.0
        for ck, _name, state in ink_state.composite_items():
            try:
                ink = float(state[0])
            except (TypeError, IndexError, ValueError):
                continue
            pdi = pdi_by_ck.get(ck)
            try:
                if pdi is not None and not pdi.isVisible():
                    continue
            except Exception:
                pass
            try:
                if pdi is not None and pdi.curve in covered:
                    continue
            except Exception:
                pass
            total += ink
        return total

    def _set_curves_antialias(self, on: bool) -> int:
        """Persistently set curve AA without repainting or changing data."""
        n = 0
        covered = self._raster_covered_curve_items() if on else set()
        for it in self._collect_curve_items():
            try:
                enabled = bool(on and it not in covered)
                it.opts["antialias"] = enabled
                if not on or enabled:
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
        items = (
            self._collect_curve_items()
            if mode == QGraphicsItem.NoCache
            else self._native_aa_curve_items()
        )
        for it in items:
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

    def reconcile_backend_quality(self):
        """Drop latched native AA when a raster backend becomes unavailable."""
        if self._high_raster_cost_status()["blocked"] and self.aa_on:
            self.disable_interactive_quality()
            return
        self._emit_quality_status_changed()

    def try_enable_idle_quality(self):
        """Idle timer slot: enable curve AA once every hands-off gate passes."""
        if not self._idle_quality_allowed():
            # The affordability backend can change while idle (for example a
            # ready dense raster can fall back after a memory-cap change).
            # Do not leave native AA from the former green state latched on.
            if self.aa_on:
                self.disable_interactive_quality()
            else:
                self._emit_quality_status_changed()
            return
        if self.aa_on:
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
        # RenderProfile is derived from the RAW channel, before any envelope
        # cap.  A dense-discrete/CRC trace can be capped to only ~700 displayed
        # points and still cost hundreds of milliseconds to re-rasterize with
        # AA under a ViewBox transform.  The displayed-point density metric is
        # therefore not a safe affordability proxy for this strategy.
        if self._high_raster_cost_status()["blocked"]:
            self.density_allowed = False
            return False
        # Universal ink budget (spec §4.2): sum the per-line vertical ink of
        # every line still on the native-AA path (raster-covered lines are
        # excluded by _frame_native_ink_total — their paint cost was already
        # replaced by the raster upgrade, so one high-ink raster-covered line
        # must not keep blocking AA for the rest of the frame). Double-
        # threshold hysteresis, same shape as the point-count density gate
        # below: a sum parked in the (_INK_AA_ON, _INK_AA_OFF] dead band holds
        # whatever the previous decision was instead of flapping every frame.
        # AND'd with the point-count gate below, not a replacement for it —
        # "too many points" is still a real, orthogonal constraint.
        total_ink = self._frame_native_ink_total()
        if not self.ink_seeded:
            self.ink_allowed = total_ink <= _INK_AA_OFF
            self.ink_seeded = True
        elif total_ink <= _INK_AA_ON:
            self.ink_allowed = True
        elif total_ink > _INK_AA_OFF:
            self.ink_allowed = False
        if not self.ink_allowed:
            self.density_allowed = False
            return False
        if self._overlay_density_pressure_status()["blocked"]:
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
        # Export owns its own non-mutating affordability decision.  Do not let
        # the idle hysteresis state opt a dense-discrete curve back into the
        # temporary forced-AA context used by grab_pixmap().
        if self._high_raster_cost_status()["blocked"]:
            return False
        # Same ink ceiling as the idle-AA gate (spec §4.2), one-shot: export
        # has no hysteresis state to seed or hold, it decides fresh on every
        # call, so this is a plain comparison against _INK_AA_OFF (no ON/OFF
        # dead band, no self.ink_allowed/ink_seeded mutation).
        if self._frame_native_ink_total() > _INK_AA_OFF:
            return False
        if self._overlay_density_pressure_status()["blocked"]:
            return False
        dense_status = self._dense_raster.quality_status()
        if dense_status.get("has_dense") and not self._native_aa_curve_items():
            # Pure dense-raster export stays WYSIWYG and avoids magnifying the
            # screen cache solely because its native-AA metric is empty.
            return False
        status = self._density_status()
        if status["error"]:
            return False
        return status["metric"] <= status["off_budget"]

    def _high_raster_cost_status(self):
        """Describe visible curves that need the raster backend but lack it.

        Membership is the canvas' shared admission predicate (spec §4.3), keyed
        by the same composite ``(data_id, name)`` identity as
        ``_channel_lines``: a dense-discrete profile, or a line whose measured
        ink puts vector AA out of reach.  Either way, until a ready raster
        covers it the curve is on native non-AA and must block the AA gate.
        Visibility matters: a dormant curve retained by the selection-delta
        path must not block AA for the curves that are actually painted.
        """
        covered_curves = self._raster_covered_curve_items()
        lines = getattr(self, "_channel_lines", None)
        labels = []
        if lines is None or not hasattr(lines, "composite_items"):
            return {"blocked": False, "count": 0, "labels": ()}
        try:
            entries = list(lines.composite_items())
        except Exception:
            return {"blocked": False, "count": 0, "labels": ()}
        for composite_key, display_name, pair in entries:
            try:
                pdi = pair[1].plot_data_item
                if pdi is not None and not pdi.isVisible():
                    continue
            except Exception:
                continue
            if self._raster_backend_eligible(composite_key):
                if getattr(pdi, "curve", None) in covered_curves:
                    continue
                labels.append(str(display_name))
        return {
            "blocked": bool(labels),
            "count": len(labels),
            "labels": tuple(labels),
        }

    def _overlay_density_pressure_status(self):
        """Describe visible overlay curves whose raw density makes AA costly."""
        if not bool(getattr(self, "_overlay_mode", False)):
            return {"blocked": False, "count": 0, "labels": ()}
        try:
            pixel_width = self._current_pixel_width()
            if pixel_width is None or float(pixel_width) <= 0:
                return {"blocked": False, "count": 0, "labels": ()}
            pixel_width = float(pixel_width)
        except Exception:
            return {"blocked": False, "count": 0, "labels": ()}

        try:
            entries = list(self._channel_lines.composite_items())
        except Exception:
            return {"blocked": False, "count": 0, "labels": ()}

        labels = []
        for composite_key, display_name, pair in entries:
            try:
                pdi = pair[1].plot_data_item
                if pdi is None or not pdi.isVisible():
                    continue
                row = self.channel_data.get(composite_key)
                sample_count = len(row[1])
                if sample_count / pixel_width >= _SUBPLOT_DENSE_DECIMATION:
                    labels.append(str(display_name))
            except Exception:
                continue
        return {
            "blocked": len(labels) >= 2,
            "count": len(labels),
            "labels": tuple(labels),
        }

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
        items = self._native_aa_curve_items()
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
        native_items = self._native_aa_curve_items()
        density = self._density_status()
        raster_cost = self._high_raster_cost_status()
        dense_raster = self._dense_raster.quality_status()
        pressure = self._overlay_density_pressure_status()
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
        if raster_cost["blocked"]:
            if dense_raster["state"] == "green":
                return {
                    **base,
                    "state": "green",
                    "render_path": "dense-raster",
                    "high_raster_curve_count": raster_cost["count"],
                    "tooltip": "平滑曲线已完成（高分辨率缓存）",
                }
            if dense_raster["state"] == "yellow":
                return {
                    **base,
                    "state": "yellow",
                    "render_path": "dense-raster",
                    "high_raster_curve_count": raster_cost["count"],
                    "tooltip": "平滑曲线正在生成（高分辨率缓存）",
                }
            labels = list(raster_cost["labels"])
            preview = "、".join(labels[:2])
            if len(labels) > 2:
                preview += f" 等 {len(labels)} 条"
            return {
                **base,
                "state": "red",
                "render_path": "native-non-aa",
                "block_reason": "high-raster-cost",
                "high_raster_curve_count": raster_cost["count"],
                "tooltip": (
                    f"抗锯齿未激活：高光栅成本曲线 {preview}"
                    "（密集离散跳变）"
                ),
            }
        if pressure["blocked"]:
            return {
                **base,
                "state": "red",
                "render_path": "native-non-aa",
                "block_reason": "overlay-density-pressure",
                "overlay_dense_curve_count": pressure["count"],
                "tooltip": "抗锯齿未激活：叠加高密度曲线达到性能门禁",
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
        actual_on = bool(native_items)
        for it in native_items:
            try:
                actual_on = actual_on and bool(it.opts.get("antialias", False))
            except Exception:
                actual_on = False
        if self.aa_on and actual_on:
            if dense_raster["state"] == "green":
                return {
                    **base,
                    "state": "green",
                    "render_path": "dense-raster+native-aa",
                    "tooltip": "高分辨率平滑缓存；其他曲线抗锯齿已完成",
                }
            return {
                **base,
                "state": "green",
                "tooltip": "抗锯齿已完成",
            }
        if dense_raster["state"] == "green" and not native_items:
            return {
                **base,
                "state": "green",
                "render_path": "dense-raster",
                "tooltip": "平滑曲线已完成（高分辨率缓存）",
            }
        if dense_raster["state"] == "yellow":
            return {
                **base,
                "state": "yellow",
                "render_path": "dense-raster",
                "tooltip": "平滑曲线正在生成（高分辨率缓存）",
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
        for it in self._native_aa_curve_items():
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
