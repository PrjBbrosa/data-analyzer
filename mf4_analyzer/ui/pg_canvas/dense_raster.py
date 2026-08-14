"""Smooth cached raster presentation for dense-discrete time traces.

The raw channel and PlotDataItem remain authoritative for cursor/statistics and
export semantics.  This module only replaces the expensive visible vector
stroke with a DPR-aware, data-coordinate QGraphicsPixmapItem after a complete
image has been built.  All scene/QPixmap work stays on the GUI thread.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from weakref import WeakSet

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QObject, Qt, QThread, QTimer
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PyQt5.QtWidgets import QApplication, QGraphicsPixmapItem


# Per-item and aggregate caps keep large/stacked surfaces on native non-AA.
#
# RE-BASELINED 2026-08-08 for the widened, ink-driven admission
# (docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md §4.3 / §5).
# The old 16 MiB item cap was sized for the CRC-counter case (a 1200x700 chart
# retains ~13 MiB at logical 2x) and rejected the single geometry the raster
# upgrade now exists for: one 1920x900 row is 3840x1800 x 4 B ~ 26.4 MiB.
#
# The sizing argument is TILING, not per-item generosity. Subplot rows tile the
# viewport, so however many rows there are, the sum of their images is about
# ONE viewport of device pixels: 1920x1080 @dpr2 -> 3840x2160 x 4 B ~ 31.6 MiB.
# Splitting that viewport into more rows makes each image smaller, never the
# total larger. So:
#
#   * DEFAULT_MAX_ITEM_BYTES must clear the WORST SINGLE ROW, which is the
#     un-split, full-height case (~26.4 MiB above). 36 MiB clears it with room
#     for a taller window without letting one item approach the tiled total.
#   * DEFAULT_MAX_GLOBAL_BYTES must hold a fully tiled viewport (~31.6 MiB)
#     PLUS the build-time peak of the row being rebuilt, where the QImage and
#     the QPixmap converted from it conservatively coexist (2x the item, so up
#     to ~53 MiB for a max-size item). 96 MiB covers ~85 MiB of worst case and
#     stays a real ceiling rather than a formality.
#
# These are spec-backed, not knobs: change spec §5 first. The bands are fenced
# by tests/ui/test_pg_dense_raster.py::test_dense_raster_memory_caps_stay_in_the_spec_band.
DEFAULT_MAX_ITEM_BYTES = 36 * 1024 * 1024
DEFAULT_MAX_GLOBAL_BYTES = 96 * 1024 * 1024

# A cached raster whose data-span / pixel-width is coarser than the current
# view turns one min/max column into a solid rectangle. Two columns is the
# point where the blit is no longer a silhouette preview.
_STRETCH_MIN_COLUMNS = 2.0


def raster_would_stretch(data_span, view_span, pixel_width) -> bool:
    """True when ``view_span`` is narrower than two raster columns."""
    try:
        data_span = float(data_span)
        view_span = float(view_span)
        pixel_width = float(pixel_width)
    except (TypeError, ValueError):
        return True
    if not np.isfinite(data_span) or data_span <= 0.0:
        return True
    if not np.isfinite(view_span) or view_span <= 0.0:
        return True
    if pixel_width < 1.0:
        pixel_width = 1.0
    return view_span < _STRETCH_MIN_COLUMNS * (data_span / pixel_width)


@dataclass(frozen=True)
class DenseRasterEntry:
    composite_key: str
    item: QGraphicsPixmapItem
    view_box: object
    data_rect: tuple[float, float, float, float]
    source_revision: object
    color: str
    generation: int
    memory_bytes: int
    signature: tuple
    native_pen: object


def build_dense_raster_image(
    x,
    y,
    *,
    data_rect,
    logical_size,
    dpr,
    color,
    line_width=1.0,
):
    """Build an at-least-logical-2x transparent image without vector AA."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    if x.size < 2 or x.size != y.size:
        return None
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        # Preserve NaN-gap semantics through the native non-AA fallback.
        return None
    xlo, xhi, ylo, yhi = (float(v) for v in data_rect)
    width, height = (max(1, int(v)) for v in logical_size)
    dpr = max(1.0, float(dpr))
    if xhi <= xlo or yhi <= ylo or width < 16 or height < 16:
        return None
    # A DPR1 screen still gets a real logical-2x image. On DPR2 hardware the
    # native device image already is logical-2x, so adding another 2x then
    # QImage.scaled() would create a 4x intermediate; Cocoa measured that path
    # at ~3.5 s p95. Keeping the pixmap's own DPR lets Qt's device compositor
    # perform the intended smooth downsample during the cheap cached blit.
    raster_dpr = max(2.0, dpr)
    dev_w = max(1, int(round(width * raster_dpr)))
    dev_h = max(1, int(round(height * raster_dpr)))
    image = QImage(dev_w, dev_h, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    px = (x - xlo) / (xhi - xlo) * (image.width() - 1)
    py = (yhi - y) / (yhi - ylo) * (image.height() - 1)
    polyline = pg.functions.arrayToQPolygonF(
        np.ascontiguousarray(px),
        np.ascontiguousarray(py),
    )
    painter = QPainter(image)
    try:
        # Qt's vector AA is the pathological CRC cost. Two translucent,
        # subpixel-offset strokes are rasterized without AA at logical 2x;
        # QGraphicsPixmapItem then performs only a cached smooth blit.
        painter.setRenderHint(QPainter.Antialiasing, False)
        qcolor = QColor(color)
        qcolor.setAlpha(150)
        pen = QPen(qcolor)
        pen.setCosmetic(True)
        # A >1-device-pixel cosmetic pen triggers the same pathological full-
        # height CRC stroker (~1.6 s on Cocoa). Multiple offset 1-pixel passes
        # preserve the native logical width while keeping the fast polyline
        # raster path; DPR sampling merges them into one smooth stroke.
        pen.setWidth(1)
        painter.setPen(pen)
        pass_count = max(2, min(4, int(np.ceil(line_width * raster_dpr))))
        offsets = {
            2: ((-0.5, -0.5), (0.5, 0.5)),
            3: ((-0.5, -0.5), (0.5, -0.5), (0.0, 0.5)),
            4: ((-0.75, 0.0), (0.75, 0.0), (0.0, -0.75), (0.0, 0.75)),
        }[pass_count]
        for offset_x, offset_y in offsets:
            painter.save()
            painter.translate(offset_x, offset_y)
            painter.drawPolyline(polyline)
            painter.restore()
    finally:
        painter.end()
    # Mark the physical image as a logical-size pixmap only after painting.
    # Setting DPR before QPainter construction makes its coordinates logical;
    # feeding the physical px/py values above would then crop/stretch data.
    image.setDevicePixelRatio(raster_dpr)
    return image


class DenseDiscreteRasterLayer(QObject):
    """Per-canvas owner of dense-discrete pixmap items and memory policy."""

    _instances = WeakSet()
    timer_generation_property = "tracelabDenseRasterGeneration"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.entries: dict[str, DenseRasterEntry] = {}
        self.incompatible_keys: set[str] = set()
        self.max_item_bytes = DEFAULT_MAX_ITEM_BYTES
        self.max_global_bytes = DEFAULT_MAX_GLOBAL_BYTES
        self.pending_reason = None
        self._force_rebuild = False
        self.timer = self._new_rebuild_timer()
        self.suppress_timer = self._new_suppress_timer()
        self._instances.add(self)

    def _new_rebuild_timer(self):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_timeout)
        return timer

    def _new_suppress_timer(self):
        timer = QTimer(self)
        # PlotDataItem.viewRangeChanged re-applies its stored pen after the
        # canvas' range slot. A separate zero-delay, generation-gated timer
        # suppresses that pen at the end of the same event-loop turn, before
        # the queued scene repaint, without regenerating the raster.
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_suppress_timeout)
        return timer

    @classmethod
    def global_memory_bytes(cls):
        return sum(
            entry.memory_bytes
            for manager in list(cls._instances)
            for entry in manager.entries.values()
        )

    def _on_gui_thread(self):
        app = QApplication.instance()
        return app is not None and QThread.currentThread() is app.thread()

    def _notify_status(self):
        try:
            self.canvas._quality._emit_quality_status_changed()
        except Exception:
            pass

    def schedule_rebuild(self, reason="view-changed", *, delay_ms=0):
        self.pending_reason = str(reason)
        generation = int(self.canvas._interaction_generation)
        self.timer.setProperty(self.timer_generation_property, generation)
        self.timer.start(max(0, int(delay_ms)))
        self._notify_status()

    def _on_timeout(self):
        timer = self.sender()
        if timer is not self.timer:
            return
        try:
            generation = int(timer.property(self.timer_generation_property))
        except (TypeError, ValueError):
            return
        self.flush_pending(generation)

    def schedule_resuppress(self):
        generation = int(self.canvas._interaction_generation)
        self.suppress_timer.setProperty(
            self.timer_generation_property, generation,
        )
        self.suppress_timer.start(0)
        self._notify_status()

    def _on_suppress_timeout(self):
        timer = self.sender()
        if timer is not self.suppress_timer:
            return
        try:
            generation = int(
                timer.property(self.timer_generation_property)
            )
        except (TypeError, ValueError):
            return
        if generation == int(self.canvas._interaction_generation):
            self.sync_visibility(schedule_missing=False)

    def flush_pending(self, generation):
        if int(generation) != int(self.canvas._interaction_generation):
            return False
        if self.timer.isActive():
            self.timer.stop()
        rebuilt = self.refresh_all(generation)
        self.pending_reason = None
        self._force_rebuild = False
        try:
            self.canvas._quality.reconcile_backend_quality()
        except Exception:
            self._notify_status()
        return rebuilt

    def invalidate_all(self, reason, *, schedule=False):
        self._force_rebuild = True
        self.pending_reason = str(reason)
        if schedule:
            self.schedule_rebuild(reason, delay_ms=0)
        else:
            self._notify_status()

    def entry_for(self, key):
        composite = None
        try:
            composite = self.canvas._channel_lines.composite_key_for(key)
        except Exception:
            pass
        return self.entries.get(composite or key)

    def _entry_pixel_width(self, entry) -> float:
        try:
            pixmap = entry.item.pixmap()
            dpr = max(1.0, float(pixmap.devicePixelRatioF()))
            return max(1.0, float(pixmap.width()) / dpr)
        except Exception:
            return 1.0

    def entry_is_lossy(self, entry, xlim) -> bool:
        """True when transforming ``entry`` into ``xlim`` would fill a column."""
        if entry is None or xlim is None:
            return False
        try:
            view_span = abs(float(xlim[1]) - float(xlim[0]))
            data_span = float(entry.data_rect[1]) - float(entry.data_rect[0])
        except Exception:
            return True
        return raster_would_stretch(
            data_span, view_span, self._entry_pixel_width(entry),
        )

    def drop_lossy_for_xlim(self, xlim) -> bool:
        """Remove rasters that the current X window would stretch into a block.

        Called from the ViewBox X-range path so Ctrl+wheel / box-zoom does
        not keep a transform-only CRC pixmap across a sub-sample window for
        the whole 100 ms quiet interval.
        """
        dropped = False
        for ck, entry in list(self.entries.items()):
            if self.entry_is_lossy(entry, xlim):
                self._remove_entry(ck)
                dropped = True
        if dropped:
            self._notify_status()
        return dropped

    def _dense_visible_keys(self):
        if bool(getattr(self.canvas, "_overlay_mode", False)):
            return []
        keys = []
        for ck, _name, (_axis, line) in self.canvas._channel_lines.composite_items():
            # Admission is the canvas' shared predicate (spec §4.3): dense
            # discrete BY STRATEGY, or any line the ink budget put out of reach
            # of vector AA.
            if not self.canvas._raster_backend_eligible(ck):
                continue
            pdi = getattr(line, "plot_data_item", None)
            try:
                if pdi is not None and pdi.isVisible():
                    keys.append(ck)
            except Exception:
                continue
        return keys

    def quality_status(self):
        keys = self._dense_visible_keys()
        if not keys:
            return {"has_dense": False, "state": None}
        if any(key in self.incompatible_keys for key in keys):
            return {"has_dense": True, "state": "red"}
        if (
            self.timer.isActive()
            or self.pending_reason
            or bool(getattr(self.canvas, "_refresh_pending", False))
            or getattr(self.canvas, "_interaction_state", "idle") != "idle"
        ):
            return {"has_dense": True, "state": "yellow"}
        if all(key in self.entries for key in keys):
            return {"has_dense": True, "state": "green"}
        return {"has_dense": True, "state": "red"}

    def _restore_native(self, ck, entry=None):
        pair = self.canvas._channel_lines.get(ck)
        if pair is None:
            return
        pdi = getattr(pair[1], "plot_data_item", None)
        curve = getattr(pdi, "curve", None)
        if curve is not None:
            try:
                if entry is None:
                    entry = self.entries.get(ck)
                native_pen = (
                    getattr(entry, "native_pen", None)
                    if entry is not None else pdi.opts.get("pen")
                )
                if native_pen is not None:
                    native_pen = QPen(native_pen)
                    pdi.opts["pen"] = native_pen
                    pdi._tracelab_dense_native_pen = QPen(native_pen)
                curve.setVisible(bool(pdi.isVisible()))
                curve.setPen(native_pen)
            except Exception:
                pass

    def _remove_entry(self, ck, *, restore_native=True):
        entry = self.entries.pop(ck, None)
        if entry is not None:
            try:
                entry.view_box.removeItem(entry.item)
            except Exception:
                try:
                    scene = entry.item.scene()
                    if scene is not None:
                        scene.removeItem(entry.item)
                except Exception:
                    pass
        if restore_native:
            self._restore_native(ck, entry)

    def clear(self):
        old_timer = self.timer
        old_suppress_timer = self.suppress_timer
        for timer in (old_timer, old_suppress_timer):
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        # A timeout signal may already be queued. Replacing the QObject plus
        # sender-identity checks in both bound slots prevents it from acting on
        # the next canvas generation even if that old signal is delivered.
        self.timer = self._new_rebuild_timer()
        self.suppress_timer = self._new_suppress_timer()
        for ck in list(self.entries):
            self._remove_entry(ck, restore_native=False)
        self.incompatible_keys.clear()
        self.pending_reason = None
        self._force_rebuild = False

    def _suppress_native(self, pdi, native_pen=None):
        """Keep the PDI visible/bounded while suppressing only its stroke."""
        curve = getattr(pdi, "curve", None)
        if curve is None:
            return
        try:
            if native_pen is not None:
                pdi._tracelab_dense_native_pen = QPen(native_pen)
            # PlotDataItem.viewRangeChanged always replays pdi.opts['pen'].
            # Holding that option at None while ready prevents a synchronous
            # QWidget.grab/export from reintroducing the vector stroke between
            # our range slot and the scene paint. dataBounds and PDI visibility
            # are unchanged; the saved native pen is restored on fallback.
            pdi.opts["pen"] = None
            curve.setVisible(True)
            curve.setPen(None)
        except Exception:
            pass

    def capture_pen_update(self, key):
        """Persist a production line.set_color result before suppressing it."""
        entry = self.entry_for(key)
        if entry is None:
            return
        pair = self.canvas._channel_lines.get(entry.composite_key)
        pdi = getattr(pair[1], "plot_data_item", None) if pair else None
        pen = pdi.opts.get("pen") if pdi is not None else None
        if pen is None:
            return
        native_pen = QPen(pen)
        pdi._tracelab_dense_native_pen = QPen(native_pen)
        self.entries[entry.composite_key] = replace(
            entry,
            native_pen=native_pen,
        )

    def native_pen_for(self, key, pdi=None):
        """Return the effective saved/native pen while pdi.opts is suppressed."""
        entry = self.entry_for(key)
        if pdi is None and entry is not None:
            pair = self.canvas._channel_lines.get(entry.composite_key)
            pdi = getattr(pair[1], "plot_data_item", None) if pair else None
        pen = pdi.opts.get("pen") if pdi is not None else None
        if pen is None and entry is not None:
            pen = entry.native_pen
        if pen is None and pdi is not None:
            pen = getattr(pdi, "_tracelab_dense_native_pen", None)
        return QPen(pen) if pen is not None else None

    def set_native_pen_style(self, key, pdi, style):
        """Mutate a suppressed companion pen and enforce dashed fallback."""
        pen = self.native_pen_for(key, pdi)
        if pen is None:
            return False
        if pen.style() != style:
            pen.setStyle(style)
            pdi.setPen(pen)
            self.capture_pen_update(key)
        if style != Qt.SolidLine and self.entry_for(key) is not None:
            self.deactivate_channel(key)
        return True

    def has_dense_candidates(self):
        return bool(self.entries or self._dense_visible_keys())

    def deactivate_channel(self, key):
        composite = None
        try:
            composite = self.canvas._channel_lines.composite_key_for(key)
        except Exception:
            pass
        self._remove_entry(composite or key)

    def sync_visibility(self, *, schedule_missing=True):
        for ck, _name, (_axis, line) in self.canvas._channel_lines.composite_items():
            pdi = getattr(line, "plot_data_item", None)
            curve = getattr(pdi, "curve", None)
            try:
                visible = bool(pdi.isVisible())
            except Exception:
                visible = False
            entry = self.entries.get(ck)
            dense = self.canvas._raster_backend_eligible(ck)
            if entry is not None:
                entry.item.setVisible(visible)
            if curve is not None:
                curve.setVisible(visible)
                if visible and dense and entry is not None:
                    self._suppress_native(pdi, entry.native_pen)
                else:
                    self._restore_native(ck, entry)
        if schedule_missing and any(
            key not in self.entries for key in self._dense_visible_keys()
        ):
            self.schedule_rebuild("visibility-changed", delay_ms=0)
        else:
            self._notify_status()

    def refresh_all(self, generation):
        if int(generation) != int(self.canvas._interaction_generation):
            return False
        if bool(getattr(self.canvas, "_overlay_mode", False)):
            for ck in list(self.entries):
                self._remove_entry(ck)
            return False
        profiles = self.canvas._channel_render_profiles
        active = set()
        rebuilt = False
        for ck, _name, (axis, line) in self.canvas._channel_lines.composite_items():
            profile = profiles.get(ck)
            # Shared admission predicate (spec §4.3). A missing profile keeps
            # the pre-existing defensive skip: source_revision below reads off
            # it, and an unclassified line has nothing to key a signature on.
            if profile is None or not self.canvas._raster_backend_eligible(ck):
                self.incompatible_keys.discard(ck)
                self._remove_entry(ck)
                continue
            pdi = getattr(line, "plot_data_item", None)
            try:
                visible = bool(pdi is not None and pdi.isVisible())
            except Exception:
                visible = False
            if not visible:
                entry = self.entries.get(ck)
                if entry is not None:
                    entry.item.setVisible(False)
                continue
            active.add(ck)
            try:
                x, y = pdi.getData()
                row = self.canvas.channel_data.get(ck)
                color = row[2]
            except Exception:
                self._remove_entry(ck)
                continue
            rebuilt = self.update_channel(
                ck,
                axis,
                pdi,
                x,
                y,
                color=color,
                source_revision=profile.source_revision,
                generation=generation,
                force=self._force_rebuild,
            ) or rebuilt
        for ck in list(self.entries):
            if ck not in active:
                pair = self.canvas._channel_lines.get(ck)
                if pair is None or not self.canvas._raster_backend_eligible(ck):
                    self._remove_entry(ck)
        self.sync_visibility(schedule_missing=False)
        return rebuilt

    def update_channel(
        self,
        ck,
        axis,
        pdi,
        x,
        y,
        *,
        color,
        source_revision,
        generation,
        data_rect=None,
        force=False,
    ):
        if not self._on_gui_thread():
            self._remove_entry(ck)
            return False
        if int(generation) != int(self.canvas._interaction_generation):
            return False
        view_box = getattr(axis, "view_box", None)
        if view_box is None:
            self._remove_entry(ck)
            return False
        try:
            if axis.get_xscale() == "log" or axis.get_yscale() == "log":
                self.incompatible_keys.add(ck)
                self._remove_entry(ck)
                return False
        except Exception:
            # Unknown scale semantics are safer on the native transform path.
            self.incompatible_keys.add(ck)
            self._remove_entry(ck)
            return False
        self.incompatible_keys.discard(ck)
        try:
            scene_rect = view_box.sceneBoundingRect()
            width = int(round(scene_rect.width()))
            height = int(round(scene_rect.height()))
            ylo, yhi = (float(v) for v in axis.get_ylim())
            dpr = float(self.canvas._glw.devicePixelRatioF())
        except Exception:
            self._remove_entry(ck)
            return False
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        finite_x = x[np.isfinite(x)]
        if finite_x.size < 2:
            self._remove_entry(ck)
            return False
        if data_rect is None:
            xlo, xhi = float(finite_x.min()), float(finite_x.max())
        else:
            xlo, xhi = (float(v) for v in data_rect[:2])
        try:
            view_lo, view_hi = (float(v) for v in axis.get_xlim())
            view_span = abs(view_hi - view_lo)
        except Exception:
            view_span = abs(xhi - xlo)
        sample_span = float(finite_x.max() - finite_x.min())
        rect_span = abs(xhi - xlo)
        if (
            raster_would_stretch(rect_span, view_span, width)
            or raster_would_stretch(sample_span, view_span, width)
            or sample_span > 2.0 * max(rect_span, view_span, 1e-30)
        ):
            # Sub-sample / sub-column zoom: keep the native polyline instead
            # of stamping a min/max column that ViewBox would stretch into a
            # solid colour block.
            self._remove_entry(ck)
            return False
        rect = (xlo, xhi, min(ylo, yhi), max(ylo, yhi))
        qcolor = QColor(color).name()
        old = self.entries.get(ck)
        try:
            pen = pdi.opts.get("pen")
            if pen is None and old is not None:
                pen = old.native_pen
            line_width = float(pen.widthF()) if pen is not None else 1.0
            if pen is not None and pen.style() != Qt.SolidLine:
                self._remove_entry(ck)
                return False
        except Exception:
            line_width = 1.0
        signature = (
            source_revision,
            tuple(round(v, 12) for v in rect),
            width,
            height,
            round(dpr, 3),
            qcolor,
            round(line_width, 2),
        )
        if old is not None and old.signature == signature and not force:
            old.item.setVisible(True)
            self._suppress_native(pdi, old.native_pen)
            return False
        raster_dpr = max(2.0, dpr)
        target_bytes = max(1, int(round(width * raster_dpr))) * max(
            1, int(round(height * raster_dpr))
        ) * 4
        if target_bytes > int(self.max_item_bytes):
            self._remove_entry(ck)
            return False
        # QImage and QPixmap conservatively coexist during conversion; the old
        # retained pixmap is already included in global_memory_bytes().
        build_peak_bytes = target_bytes * 2
        if self.global_memory_bytes() + build_peak_bytes > int(self.max_global_bytes):
            self._remove_entry(ck)
            return False
        image = build_dense_raster_image(
            x,
            y,
            data_rect=rect,
            logical_size=(width, height),
            dpr=dpr,
            color=qcolor,
            line_width=line_width,
        )
        if image is None:
            self._remove_entry(ck)
            return False
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull() or int(generation) != int(self.canvas._interaction_generation):
            return False
        item = old.item if old is not None else QGraphicsPixmapItem()
        if old is None:
            curve = getattr(pdi, "curve", None)
            item.setZValue(float(curve.zValue()) + 0.1 if curve is not None else 0.1)
            item.setTransformationMode(Qt.SmoothTransformation)
            item.setAcceptedMouseButtons(Qt.NoButton)
            try:
                view_box.addItem(item, ignoreBounds=True)
            except TypeError:
                view_box.addItem(item)
        item.setPixmap(pixmap)
        bounds = item.boundingRect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            if old is None:
                try:
                    view_box.removeItem(item)
                except Exception:
                    pass
            self._remove_entry(ck)
            return False
        item.setTransform(QTransform(
            (xhi - xlo) / bounds.width(),
            0.0,
            0.0,
            -(rect[3] - rect[2]) / bounds.height(),
            xlo,
            rect[3],
        ))
        item.setVisible(True)
        native_pen = QPen(pen) if pen is not None else None
        self.entries[ck] = DenseRasterEntry(
            composite_key=ck,
            item=item,
            view_box=view_box,
            data_rect=rect,
            source_revision=source_revision,
            color=qcolor,
            generation=int(generation),
            memory_bytes=int(image.sizeInBytes()),
            signature=signature,
            native_pen=native_pen,
        )
        self._suppress_native(pdi, native_pen)
        return True
