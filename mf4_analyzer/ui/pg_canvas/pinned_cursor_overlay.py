"""Pinned-cursor lines, extrema, and axis-edge label geometry.

Receives immutable pin facts/intents only. Does not read MainWindow, does
not resample DSP, and does not join ``iter_transient_overlay_items``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pyqtgraph as pg
from PyQt5 import sip
from PyQt5.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsLineItem,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ._backref import _CanvasBackref


PINNED_OFFSCREEN_TEXT = "视野外"

_LABEL_H = 16
_LABEL_GAP = 3
_EDGE_PAD = 2
_TINY_HOST_W = 40
_LINE_Z = 800
_EXTREMA_Z = 850
_LEADER_Z = 790
_SINGLE_COLOR = "#7090be"
_A_COLOR = "#2563eb"
_B_COLOR = "#dc2626"
_MIN_COLOR = "#16a34a"
_MAX_COLOR = "#dc2626"
_FAINT_ALPHA = 110
_HIGHLIGHT_ALPHA = 220


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _alive(item):
    if item is None:
        return False
    try:
        return not sip.isdeleted(item)
    except RuntimeError:
        return False


def _pen(color, *, alpha, width=1.0, style=Qt.DashLine):
    painted = QColor(color)
    painted.setAlpha(int(alpha))
    return pg.mkPen(painted, width=width, style=style)


def cluster_label_text(ordinals):
    """Compact cluster copy: consecutive ``P3–P7``, otherwise ``+N``."""
    values = tuple(sorted({int(item) for item in ordinals if int(item) >= 1}))
    if not values:
        return "+0"
    if len(values) == 1:
        return f"P{values[0]}"
    consecutive = all(
        values[index] + 1 == values[index + 1]
        for index in range(len(values) - 1)
    )
    if consecutive:
        return f"P{values[0]}–P{values[-1]}"
    return f"+{len(values)}"


def _label_width(text, fm):
    return max(18, int(fm.horizontalAdvance(str(text))) + 8)


@dataclass(frozen=True)
class PinnedOverlayEndpoint:
    key: str
    physical_x: float
    label: str


@dataclass(frozen=True)
class PinnedOverlayRecord:
    record_id: str
    ordinal: int
    mode: str
    domain: str
    endpoints: tuple[PinnedOverlayEndpoint, ...]
    extrema: tuple = ()


@dataclass(frozen=True)
class PinnedLabelGeom:
    key: str
    kind: str
    record_ids: tuple[str, ...]
    ordinals: tuple[int, ...]
    text: str
    canvas_rect: tuple[int, int, int, int]
    true_x: float
    leader: tuple[float, float, float, float] | None
    offscreen: str | None
    endpoint: str
    members: tuple[tuple[str, str, int], ...]


@dataclass(frozen=True)
class PinnedOverlayLayout:
    host_rect: tuple[int, int, int, int] | None
    items: tuple[PinnedLabelGeom, ...]
    offscreen_ids: frozenset
    pending: bool
    tiny: bool = False


def layout_pinned_axis_labels(
    endpoints,
    *,
    axis_left,
    axis_right,
    axis_top,
    axis_height,
    fm,
):
    """Place axis-edge chips in a finite band. Never shove infinitely left."""
    left = int(axis_left)
    right = int(axis_right)
    top = int(axis_top)
    height = max(12, int(axis_height))
    width = right - left
    if width < 8 or not endpoints:
        return ()

    tiny = width < _TINY_HOST_W
    visible = [item for item in endpoints if item.get("offscreen") is None]
    left_off = [item for item in endpoints if item.get("offscreen") == "left"]
    right_off = [item for item in endpoints if item.get("offscreen") == "right"]
    items = []
    if tiny:
        ordinals = tuple(item["ordinal"] for item in endpoints)
        record_ids = tuple(item["record_id"] for item in endpoints)
        text = cluster_label_text(ordinals) if len(ordinals) > 1 else (
            endpoints[0]["text"] if endpoints else "P"
        )
        chip_w = min(width, _label_width(text, fm))
        rect = (left + _EDGE_PAD, top, chip_w, height)
        items.append(PinnedLabelGeom(
            key="tiny",
            kind="cluster" if len(record_ids) > 1 else "pin",
            record_ids=record_ids,
            ordinals=ordinals,
            text=text,
            canvas_rect=rect,
            true_x=float(left + chip_w / 2),
            leader=None,
            offscreen=None,
            endpoint="",
            members=tuple(
                (item["record_id"], item["text"], item["ordinal"])
                for item in endpoints
            ),
        ))
        return tuple(items)

    def _place_group(group, *, kind, offscreen, edge_x=None):
        if not group:
            return None
        ordinals = tuple(item["ordinal"] for item in group)
        record_ids = tuple(item["record_id"] for item in group)
        if kind == "cluster" or len(group) > 1:
            text = cluster_label_text(ordinals)
            kind = "cluster"
        else:
            text = group[0]["text"]
            kind = "edge" if offscreen else "pin"
        if offscreen == "left":
            text = f"◀{text}"
        elif offscreen == "right":
            text = f"{text}▶"
        chip_w = _label_width(text, fm)
        true_x = float(group[0]["canvas_x"])
        if edge_x is not None:
            center = float(edge_x)
        else:
            center = true_x
        x = int(round(center - chip_w / 2.0))
        x = max(left + _EDGE_PAD, min(x, right - chip_w - _EDGE_PAD))
        rect = (x, top, chip_w, height)
        leader = None
        label_cx = x + chip_w / 2.0
        if offscreen is None and abs(label_cx - true_x) > 1.5:
            y0 = float(top + height)
            y1 = float(top + height - 2)
            leader = (true_x, y0, label_cx, y1)
        members = tuple(
            (item["record_id"], item["text"], item["ordinal"])
            for item in group
        )
        key = (
            f"{kind}:{','.join(record_ids)}:{offscreen or group[0]['endpoint']}"
        )
        return PinnedLabelGeom(
            key=key,
            kind=kind,
            record_ids=record_ids,
            ordinals=ordinals,
            text=text,
            canvas_rect=rect,
            true_x=true_x,
            leader=leader,
            offscreen=offscreen,
            endpoint="" if kind == "cluster" else group[0]["endpoint"],
            members=members,
        )

    placed = []
    visible_sorted = sorted(
        visible,
        key=lambda item: (item["canvas_x"], item["ordinal"], item["endpoint"]),
    )
    groups = []
    for item in visible_sorted:
        if not groups:
            groups.append([item])
            continue
        prev = groups[-1][-1]
        span = (
            _label_width(prev["text"], fm) / 2.0
            + _label_width(item["text"], fm) / 2.0
            + _LABEL_GAP
        )
        if abs(item["canvas_x"] - prev["canvas_x"]) <= span:
            groups[-1].append(item)
        else:
            groups.append([item])

    last_right = left
    for group in groups:
        geom = _place_group(
            group, kind="cluster" if len(group) > 1 else "pin", offscreen=None,
        )
        if geom is None:
            continue
        x, y, w, h = geom.canvas_rect
        if x < last_right + _LABEL_GAP:
            x = last_right + _LABEL_GAP
        if x + w > right - _EDGE_PAD:
            # Finite band: collapse remaining into this chip rather than
            # shoving earlier labels past the left edge.
            x = max(left + _EDGE_PAD, right - w - _EDGE_PAD)
        geom = PinnedLabelGeom(
            key=geom.key,
            kind=geom.kind,
            record_ids=geom.record_ids,
            ordinals=geom.ordinals,
            text=geom.text,
            canvas_rect=(x, y, w, h),
            true_x=geom.true_x,
            leader=(
                None if abs((x + w / 2.0) - geom.true_x) <= 1.5
                else (geom.true_x, float(y + h), x + w / 2.0, float(y + h - 2))
            ),
            offscreen=geom.offscreen,
            endpoint=geom.endpoint,
            members=geom.members,
        )
        placed.append(geom)
        last_right = x + w

    placed = _merge_overlapping_labels(
        placed, fm=fm, left=left, right=right, top=top, height=height,
    )

    if left_off:
        geom = _place_group(
            left_off, kind="cluster" if len(left_off) > 1 else "edge",
            offscreen="left", edge_x=left + 10,
        )
        if geom is not None:
            placed.insert(0, geom)
    if right_off:
        geom = _place_group(
            right_off, kind="cluster" if len(right_off) > 1 else "edge",
            offscreen="right", edge_x=right - 10,
        )
        if geom is not None:
            placed.append(geom)
    return tuple(placed)


def _merge_overlapping_labels(placed, *, fm, left, right, top, height):
    """Collapse chips that still overlap after the bounded shift pass."""
    if len(placed) < 2:
        return placed
    changed = True
    while changed:
        changed = False
        merged = []
        for geom in placed:
            if not merged:
                merged.append(geom)
                continue
            prev = merged[-1]
            if prev.offscreen or geom.offscreen:
                merged.append(geom)
                continue
            px, _py, pw, _ph = prev.canvas_rect
            gx, _gy, gw, _gh = geom.canvas_rect
            if gx >= px + pw + _LABEL_GAP:
                merged.append(geom)
                continue
            record_ids = prev.record_ids + geom.record_ids
            ordinals = prev.ordinals + geom.ordinals
            members = prev.members + geom.members
            text = cluster_label_text(ordinals)
            chip_w = _label_width(text, fm)
            true_x = (prev.true_x + geom.true_x) / 2.0
            x = int(round(true_x - chip_w / 2.0))
            x = max(left + _EDGE_PAD, min(x, right - chip_w - _EDGE_PAD))
            label_cx = x + chip_w / 2.0
            leader = None
            if abs(label_cx - true_x) > 1.5:
                leader = (
                    true_x, float(top + height),
                    label_cx, float(top + height - 2),
                )
            merged[-1] = PinnedLabelGeom(
                key=f"cluster:{','.join(record_ids)}:",
                kind="cluster",
                record_ids=record_ids,
                ordinals=ordinals,
                text=text,
                canvas_rect=(x, top, chip_w, height),
                true_x=true_x,
                leader=leader,
                offscreen=None,
                endpoint="",
                members=members,
            )
            changed = True
        placed = merged
    return placed


class PinnedAxisLabel(QFrame):
    """Axis-edge Pn chip. Click raises the pill; hover expands a cluster."""

    clicked = pyqtSignal(str)
    hover_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pinnedAxisLabel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._geom = None
        self._highlighted = False
        self._expanded = False
        self._buttons = []
        self._text = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 0, 3, 0)
        lay.setSpacing(2)
        self._caption = QLabel(self)
        self._caption.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._caption.setAlignment(Qt.AlignCenter)
        font = QFont(self._caption.font())
        font.setPointSize(9)
        self._caption.setFont(font)
        lay.addWidget(self._caption)

    def apply_geom(self, geom: PinnedLabelGeom):
        self._geom = geom
        self._text = geom.text
        self._caption.setText(geom.text)
        self._caption.setVisible(not self._expanded)
        x, y, w, h = geom.canvas_rect
        if self._expanded and geom.kind == "cluster" and len(geom.members) > 1:
            self._ensure_members(geom)
            self.adjustSize()
        else:
            self._clear_members()
            self.setFixedSize(max(16, w), max(12, h))
        self.setToolTip(self._tooltip(geom))
        self.update()

    def set_highlighted(self, highlighted):
        self._highlighted = bool(highlighted)
        self.update()

    def record_ids(self):
        if self._geom is None:
            return ()
        return self._geom.record_ids

    def geom(self):
        return self._geom

    def _tooltip(self, geom):
        if geom.offscreen:
            return PINNED_OFFSCREEN_TEXT
        if geom.kind == "cluster":
            return " ".join(f"P{item}" for item in geom.ordinals)
        return geom.text

    def _ensure_members(self, geom):
        if self._buttons and len(self._buttons) == len(geom.members):
            for button, member in zip(self._buttons, geom.members):
                button.setText(member[1])
                button.setProperty("record_id", member[0])
            return
        self._clear_members()
        for record_id, text, _ordinal in geom.members:
            button = QPushButton(text, self)
            button.setObjectName("pinnedAxisLabelMember")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(_LABEL_H - 2)
            button.setProperty("record_id", record_id)
            button.clicked.connect(self._emit_member_clicked)
            self.layout().addWidget(button)
            self._buttons.append(button)

    def _clear_members(self):
        for button in self._buttons:
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self._buttons = []

    def _emit_member_clicked(self):
        button = self.sender()
        record_id = button.property("record_id") if button is not None else None
        if record_id:
            self.clicked.emit(str(record_id))

    def enterEvent(self, event):
        super().enterEvent(event)
        geom = self._geom
        if geom is None:
            return
        if geom.kind == "cluster" and len(geom.members) > 1:
            self._expanded = True
            self._caption.setVisible(False)
            self._ensure_members(geom)
            self.adjustSize()
            self.raise_()
        ids = geom.record_ids
        self.hover_changed.emit(ids[0] if len(ids) == 1 else ids)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._expanded:
            self._expanded = False
            self._clear_members()
            if self._geom is not None:
                self.apply_geom(self._geom)
        self.hover_changed.emit(None)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._geom is not None:
            if not self._expanded:
                record_id = self._geom.record_ids[0] if self._geom.record_ids else ""
                if record_id:
                    self.clicked.emit(record_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            if self._highlighted:
                painter.setBrush(QColor("#dceaff"))
                painter.setPen(QPen(QColor("#729ee0"), 1.0))
            else:
                painter.setBrush(QColor("#f1f6fd"))
                painter.setPen(QPen(QColor("#bed0e9"), 1.0))
            painter.drawRoundedRect(rect, 4.0, 4.0)
        finally:
            painter.end()


class PinnedCursorOverlay(_CanvasBackref):
    """Per-canvas pin marker collaborator (lines, extrema, label layout)."""

    _owned_names = frozenset({
        "_kind",
        "_records",
        "_highlight_id",
        "_line_items",
        "_leader_items",
        "_extrema_items",
        "_item_owners",
        "_layout",
        "_on_layout",
        "_view_hooks",
        "_rebuild_hooks",
        "_projecting",
        "_label_font",
    })
    _delegate_names = frozenset()

    def __init__(self, canvas, *, kind):
        super().__init__(canvas)
        self._kind = str(kind)
        self._records = ()
        self._highlight_id = None
        self._line_items = {}
        self._leader_items = []
        self._extrema_items = []
        self._item_owners = {}
        self._layout = PinnedOverlayLayout(
            host_rect=None, items=(), offscreen_ids=frozenset(), pending=True,
        )
        self._on_layout = None
        self._view_hooks = []
        self._rebuild_hooks = []
        self._projecting = False
        self._label_font = QFont()
        self._label_font.setPointSize(9)
        self._install_rebuild_hooks()

    def set_layout_callback(self, callback: Callable | None) -> None:
        self._on_layout = callback

    def set_records(self, records) -> None:
        self._records = tuple(records or ())
        self.reproject()

    def records(self):
        return self._records

    def layout(self) -> PinnedOverlayLayout:
        return self._layout

    def offscreen_record_ids(self):
        return self._layout.offscreen_ids

    def set_highlight(self, record_id) -> None:
        target = None if record_id in (None, "", (), []) else record_id
        self._highlight_id = target
        self._apply_highlight()

    def highlight_id(self):
        return self._highlight_id

    def iter_lines(self):
        for items in self._line_items.values():
            for item in items:
                if _alive(item):
                    yield item

    def lines_for(self, record_id, endpoint=None):
        out = []
        for (rid, key), items in self._line_items.items():
            if rid != record_id:
                continue
            if endpoint is not None and key != endpoint:
                continue
            out.extend(item for item in items if _alive(item))
        return out

    def extrema_items(self):
        return tuple(item for item in self._extrema_items if _alive(item))

    def host_rect(self):
        mapped = self._host_rect()
        if mapped is None or not mapped.isValid() or mapped.width() <= 1:
            return None
        return mapped

    def clear_items(self) -> None:
        self._disconnect_view_hooks()
        self._remove_items(self._all_managed_items())
        self._line_items = {}
        self._leader_items = []
        self._extrema_items = []
        self._item_owners = {}

    def clear(self) -> None:
        self._records = ()
        self._highlight_id = None
        self.clear_items()
        self._layout = PinnedOverlayLayout(
            host_rect=None, items=(), offscreen_ids=frozenset(), pending=True,
        )
        callback = self._on_layout
        if callable(callback):
            callback(self._layout)

    def reproject(self, *_args) -> None:
        if self._projecting:
            return
        canvas = self._c
        if not _alive(canvas):
            return
        self._projecting = True
        try:
            self._sync_view_hooks()
            host = self._host_rect()
            pending = host is None
            if not self._records:
                self.clear_items()
                self._layout = PinnedOverlayLayout(
                    host_rect=None if host is None else (
                        host.x(), host.y(), host.width(), host.height()
                    ),
                    items=(),
                    offscreen_ids=frozenset(),
                    pending=pending,
                )
            else:
                self._sync_lines()
                self._sync_extrema()
                self._layout = self._build_layout(host)
                self._sync_leaders(self._layout)
                self._apply_highlight()
            callback = self._on_layout
            if callable(callback):
                callback(self._layout)
        finally:
            self._projecting = False

    def _install_rebuild_hooks(self) -> None:
        canvas = self._c
        if self._kind == "time":
            signal = getattr(canvas, "chart_rebuilt", None)
        else:
            signal = getattr(canvas, "layout_geometry_changed", None)
        if signal is None:
            return
        signal.connect(self.reproject)
        self._rebuild_hooks.append(signal)

    def _sync_view_hooks(self) -> None:
        current = []
        for vb in self._line_viewboxes():
            if not _alive(vb):
                continue
            current.append(vb)
        attached = {id(item[0]) for item in self._view_hooks}
        needed = {id(vb) for vb in current}
        if attached == needed and self._view_hooks:
            return
        self._disconnect_view_hooks()
        for vb in current:
            try:
                vb.sigXRangeChanged.connect(self._on_view_geometry_changed)
                vb.sigResized.connect(self._on_view_geometry_changed)
            except (RuntimeError, TypeError, AttributeError):
                continue
            self._view_hooks.append((vb, vb.sigXRangeChanged, vb.sigResized))

    def _disconnect_view_hooks(self) -> None:
        for vb, xrange_signal, resized_signal in self._view_hooks:
            if not _alive(vb):
                continue
            for signal in (xrange_signal, resized_signal):
                try:
                    signal.disconnect(self._on_view_geometry_changed)
                except (RuntimeError, TypeError, AttributeError):
                    pass
        self._view_hooks = []

    def _on_view_geometry_changed(self, *_args) -> None:
        self.reproject()

    def _line_viewboxes(self):
        if self._kind == "frequency":
            plot = getattr(self._c, "_plot_amp", None)
            vb = getattr(plot, "vb", None)
            return [vb] if _alive(vb) else []
        if self._kind == "frf":
            return [
                plot.vb for plot in (getattr(self._c, "plots", None) or ())
                if _alive(getattr(plot, "vb", None))
            ]
        if getattr(self._c, "_overlay_mode", False):
            handle = getattr(self._c, "_x_master_handle", None)
            vb = getattr(handle, "view_box", None)
            if _alive(vb):
                return [vb]
        boxes = []
        for handle in getattr(self._c, "axes_list", None) or ():
            if getattr(handle, "placeholder", False):
                continue
            vb = getattr(handle, "view_box", None)
            if _alive(vb):
                boxes.append(vb)
        return boxes

    def _extrema_handles(self):
        handles = []
        for handle in getattr(self._c, "axes_list", None) or ():
            if getattr(handle, "placeholder", False):
                continue
            if getattr(handle, "view_box", None) is None:
                continue
            handles.append(handle)
        return handles

    def _bottom_viewbox(self):
        boxes = self._line_viewboxes()
        if not boxes:
            return None
        if self._kind == "frf":
            return boxes[-1]
        if self._kind == "frequency":
            return boxes[0]
        best = boxes[0]
        best_bottom = self._scene_rect(best)
        for vb in boxes[1:]:
            rect = self._scene_rect(vb)
            if rect is None:
                continue
            if best_bottom is None or rect.bottom() > best_bottom.bottom():
                best = vb
                best_bottom = rect
        return best

    def _scene_rect(self, vb):
        if not _alive(vb):
            return None
        try:
            rect = vb.sceneBoundingRect()
        except (RuntimeError, TypeError, AttributeError):
            return None
        if rect is None or rect.isNull() or rect.width() <= 1 or rect.height() <= 1:
            return None
        return rect

    def _map_scene_rect_to_canvas(self, scene_rect):
        glw = getattr(self._c, "_glw", None)
        canvas = self._c
        if not _alive(glw) or not _alive(canvas) or scene_rect is None:
            return None
        try:
            top_left = glw.mapFromScene(scene_rect.topLeft())
            bottom_right = glw.mapFromScene(scene_rect.bottomRight())
            view_rect = QRect(
                int(min(top_left.x(), bottom_right.x())),
                int(min(top_left.y(), bottom_right.y())),
                max(1, int(abs(bottom_right.x() - top_left.x()))),
                max(1, int(abs(bottom_right.y() - top_left.y()))),
            )
            mapped = QRect(
                glw.mapTo(canvas, view_rect.topLeft()),
                glw.mapTo(canvas, view_rect.bottomRight()),
            ).intersected(canvas.rect())
        except (RuntimeError, TypeError, AttributeError, ValueError):
            return None
        if not mapped.isValid() or mapped.width() <= 1 or mapped.height() <= 1:
            return None
        return mapped

    def _host_rect(self):
        if self._kind == "frequency":
            provider = getattr(self._c, "frequency_cursor_host_rect", None)
            if callable(provider):
                try:
                    rect = provider()
                except (RuntimeError, TypeError, AttributeError):
                    rect = None
                if isinstance(rect, QRect) and rect.isValid() and rect.width() > 1:
                    return QRect(rect)
                return None
        if self._kind == "frf":
            provider = getattr(self._c, "frequency_cursor_host_rect", None)
            if callable(provider):
                try:
                    rect = provider()
                except (RuntimeError, TypeError, AttributeError):
                    rect = None
                if isinstance(rect, QRect) and rect.isValid() and rect.width() > 1:
                    return QRect(rect)
        boxes = self._line_viewboxes()
        mapped = None
        for vb in boxes:
            part = self._map_scene_rect_to_canvas(self._scene_rect(vb))
            if part is None:
                continue
            mapped = part if mapped is None else mapped.united(part)
        return mapped

    def _view_x(self, physical):
        value = _finite(physical)
        if value is None:
            return None
        if self._kind == "frf":
            converter = getattr(self._c, "_hz_to_view_x", None)
            if not callable(converter):
                return value
            try:
                return _finite(converter(value))
            except (TypeError, ValueError):
                return None
        return value

    def _canvas_x(self, vb, view_x):
        glw = getattr(self._c, "_glw", None)
        canvas = self._c
        value = _finite(view_x)
        if value is None or not _alive(vb) or not _alive(glw) or not _alive(canvas):
            return None
        try:
            scene_pt = vb.mapViewToScene(QPointF(value, 0.0))
            view_pt = glw.mapFromScene(scene_pt)
            if hasattr(view_pt, "toPoint"):
                view_pt = view_pt.toPoint()
            canvas_pt = glw.mapTo(canvas, view_pt)
        except (RuntimeError, TypeError, AttributeError, ValueError):
            return None
        return float(canvas_pt.x())

    def _view_range(self, vb):
        if not _alive(vb):
            return None
        try:
            lo, hi = vb.viewRange()[0]
        except (RuntimeError, TypeError, AttributeError, ValueError, IndexError):
            return None
        lo = _finite(lo)
        hi = _finite(hi)
        if lo is None or hi is None or hi <= lo:
            return None
        return lo, hi

    def _endpoint_color(self, key):
        if key == "a":
            return _A_COLOR
        if key == "b":
            return _B_COLOR
        return _SINGLE_COLOR

    def _sync_lines(self) -> None:
        boxes = self._line_viewboxes()
        wanted = {}
        for record in self._records:
            for endpoint in record.endpoints:
                view_x = self._view_x(endpoint.physical_x)
                if view_x is None:
                    continue
                wanted[(record.record_id, endpoint.key)] = (view_x, endpoint.key)
        stale = [key for key in self._line_items if key not in wanted]
        for key in stale:
            self._remove_items(self._line_items.pop(key, ()))
        for key, (view_x, endpoint_key) in wanted.items():
            items = [
                item for item in self._line_items.get(key, ()) if _alive(item)
            ]
            if len(items) != len(boxes) or any(
                self._item_owners.get(id(item)) is not vb
                for item, vb in zip(items, boxes)
            ):
                self._remove_items(items)
                items = []
                for vb in boxes:
                    line = self._make_line(vb, endpoint_key)
                    if line is not None:
                        items.append(line)
                self._line_items[key] = items
            highlighted = self._is_highlighted(key[0])
            for line in items:
                try:
                    line.setValue(float(view_x))
                    line.setPen(self._line_pen(endpoint_key, highlighted))
                    line.setVisible(True)
                except (RuntimeError, TypeError, ValueError):
                    pass

    def _make_line(self, vb, endpoint_key):
        if not _alive(vb):
            return None
        line = pg.InfiniteLine(
            pos=0.0, angle=90, movable=False,
            pen=self._line_pen(endpoint_key, False),
        )
        line.setZValue(_LINE_Z)
        line.setVisible(False)
        try:
            vb.addItem(line, ignoreBounds=True)
        except (RuntimeError, TypeError, AttributeError):
            return None
        self._item_owners[id(line)] = vb
        return line

    def _line_pen(self, endpoint_key, highlighted):
        alpha = _HIGHLIGHT_ALPHA if highlighted else _FAINT_ALPHA
        width = 1.5 if highlighted else 1.0
        return _pen(self._endpoint_color(endpoint_key), alpha=alpha, width=width)

    def _is_highlighted(self, record_id):
        target = self._highlight_id
        if target is None:
            return False
        if isinstance(target, (tuple, list, set, frozenset)):
            return record_id in target
        return record_id == target

    def _sync_extrema(self) -> None:
        if self._kind != "time":
            self._remove_items(self._extrema_items)
            self._extrema_items = []
            return
        handles = self._extrema_handles()
        options = None
        getter = getattr(self._c, "cursor_display_options", None)
        if callable(getter):
            options = getter()
        show_min = True if options is None else bool(options.show_min_point)
        show_max = True if options is None else bool(options.show_max_point)
        channel_lines = getattr(self._c, "_channel_lines", None)
        if not handles or (not show_min and not show_max):
            self._remove_items(self._extrema_items)
            self._extrema_items = []
            return
        if len(self._extrema_items) != len(handles) or any(
            not _alive(item) for item in self._extrema_items
        ):
            self._remove_items(self._extrema_items)
            markers = []
            for handle in handles:
                vb = handle.view_box
                marker = pg.ScatterPlotItem(size=8)
                marker.setZValue(_EXTREMA_Z)
                marker.setVisible(False)
                try:
                    vb.addItem(marker, ignoreBounds=True)
                except (RuntimeError, TypeError, AttributeError):
                    continue
                self._item_owners[id(marker)] = vb
                markers.append(marker)
            self._extrema_items = markers
        points_by_handle = {id(handle): [] for handle in handles}
        for record in self._records:
            emphasized = self._is_highlighted(record.record_id)
            for fact in record.extrema or ():
                identity = getattr(fact, "identity", None)
                pair = None
                if channel_lines is not None:
                    try:
                        pair = channel_lines.get(identity)
                    except (TypeError, AttributeError):
                        pair = None
                handle = pair[0] if pair is not None else None
                if handle is None:
                    continue
                bucket = points_by_handle.setdefault(id(handle), [])
                size = 10 if emphasized else 8
                alpha = _HIGHLIGHT_ALPHA if emphasized else _FAINT_ALPHA
                if show_min:
                    bucket.append((
                        fact.min_x, fact.min_y, _MIN_COLOR, "o", size, alpha,
                    ))
                if show_max:
                    bucket.append((
                        fact.max_x, fact.max_y, _MAX_COLOR, "d", size, alpha,
                    ))
        for marker, handle in zip(self._extrema_items, handles):
            points = points_by_handle.get(id(handle), [])
            if not points:
                try:
                    marker.setData([], [])
                    marker.setVisible(False)
                except RuntimeError:
                    pass
                continue
            try:
                marker.setData(
                    [point[0] for point in points],
                    [point[1] for point in points],
                    symbol=[point[3] for point in points],
                    size=[point[4] for point in points],
                    pen=[
                        pg.mkPen(QColor(255, 255, 255, point[5]), width=1.0)
                        for point in points
                    ],
                    brush=[
                        pg.mkBrush(self._brush_color(point[2], point[5]))
                        for point in points
                    ],
                )
                marker.setVisible(True)
            except (RuntimeError, TypeError, ValueError):
                pass

    @staticmethod
    def _brush_color(color, alpha):
        painted = QColor(color)
        painted.setAlpha(int(alpha))
        return painted

    def _build_layout(self, host) -> PinnedOverlayLayout:
        if host is None:
            ids = frozenset(record.record_id for record in self._records)
            return PinnedOverlayLayout(
                host_rect=None, items=(), offscreen_ids=ids, pending=True,
            )
        vb = self._bottom_viewbox()
        view_range = self._view_range(vb) if vb is not None else None
        fm = QFontMetrics(self._label_font)
        endpoints = []
        offscreen_ids = set()
        for record in self._records:
            for endpoint in record.endpoints:
                view_x = self._view_x(endpoint.physical_x)
                canvas_x = self._canvas_x(vb, view_x) if vb is not None else None
                offscreen = None
                if view_x is None or view_range is None or canvas_x is None:
                    offscreen = "left"
                elif view_x < view_range[0]:
                    offscreen = "left"
                elif view_x > view_range[1]:
                    offscreen = "right"
                if offscreen is not None:
                    offscreen_ids.add(record.record_id)
                endpoints.append({
                    "record_id": record.record_id,
                    "ordinal": record.ordinal,
                    "endpoint": endpoint.key,
                    "text": endpoint.label,
                    "canvas_x": (
                        host.left() if canvas_x is None else float(canvas_x)
                    ),
                    "offscreen": offscreen,
                })
        tiny = host.width() < _TINY_HOST_W or host.height() < _LABEL_H + 2
        axis_top = host.bottom() - _LABEL_H - 1
        if axis_top < host.top():
            axis_top = host.top()
        items = layout_pinned_axis_labels(
            endpoints,
            axis_left=host.left(),
            axis_right=host.right(),
            axis_top=axis_top,
            axis_height=_LABEL_H,
            fm=fm,
        )
        return PinnedOverlayLayout(
            host_rect=(host.x(), host.y(), host.width(), host.height()),
            items=items,
            offscreen_ids=frozenset(offscreen_ids),
            pending=False,
            tiny=tiny,
        )

    def _sync_leaders(self, layout: PinnedOverlayLayout) -> None:
        self._remove_items(self._leader_items)
        self._leader_items = []
        glw = getattr(self._c, "_glw", None)
        canvas = self._c
        if not _alive(glw) or not _alive(canvas):
            return
        scene = getattr(glw, "scene", lambda: None)()
        if scene is None:
            return
        for geom in layout.items:
            if geom.leader is None:
                continue
            x1, y1, x2, y2 = geom.leader
            try:
                p1 = glw.mapToScene(canvas.mapTo(glw, QPointF(x1, y1).toPoint()))
                p2 = glw.mapToScene(canvas.mapTo(glw, QPointF(x2, y2).toPoint()))
            except (RuntimeError, TypeError, AttributeError):
                continue
            item = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
            color = QColor(_SINGLE_COLOR)
            color.setAlpha(_FAINT_ALPHA)
            item.setPen(QPen(color, 1.0))
            item.setZValue(_LEADER_Z)
            try:
                scene.addItem(item)
            except (RuntimeError, TypeError):
                continue
            self._leader_items.append(item)

    def _apply_highlight(self) -> None:
        for (record_id, endpoint_key), items in self._line_items.items():
            highlighted = self._is_highlighted(record_id)
            for line in items:
                if not _alive(line):
                    continue
                try:
                    line.setPen(self._line_pen(endpoint_key, highlighted))
                except RuntimeError:
                    pass
        if self._kind == "time" and self._records:
            self._sync_extrema()

    def _all_managed_items(self):
        items = []
        for group in self._line_items.values():
            items.extend(group)
        items.extend(self._leader_items)
        items.extend(self._extrema_items)
        return items

    def _remove_items(self, items) -> None:
        for item in list(items or ()):
            owner = self._item_owners.pop(id(item), None)
            if not _alive(item):
                continue
            try:
                item.setVisible(False)
            except RuntimeError:
                continue
            removed = False
            try:
                if owner is None:
                    getter = getattr(item, "getViewBox", None)
                    owner = getter() if callable(getter) else None
                if owner is not None:
                    owner.removeItem(item)
                    removed = True
            except (RuntimeError, TypeError, AttributeError):
                pass
            if not removed:
                try:
                    scene = item.scene()
                    if scene is not None:
                        scene.removeItem(item)
                except (RuntimeError, TypeError, AttributeError):
                    pass


__all__ = [
    "PINNED_OFFSCREEN_TEXT",
    "PinnedAxisLabel",
    "PinnedCursorOverlay",
    "PinnedLabelGeom",
    "PinnedOverlayEndpoint",
    "PinnedOverlayLayout",
    "PinnedOverlayRecord",
    "cluster_label_text",
    "layout_pinned_axis_labels",
]
