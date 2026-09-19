"""Pinned-cursor lines, extrema, and axis-edge label geometry.

Receives immutable pin facts/intents only. Does not read MainWindow, does
not resample DSP, and does not join ``iter_transient_overlay_items``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import pyqtgraph as pg
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QLineF, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWIDGETSIZE_MAX,
    QWidget,
)

from ._backref import _CanvasBackref


PINNED_OFFSCREEN_TEXT = "视野外"
PINNED_UNREPRESENTABLE_TEXT = "不可用"

_LABEL_H = 16
_LABEL_CONTENT_MARGINS = (3, 0, 3, 0)
_LABEL_FRAME_ALLOWANCE = 1
_LABEL_GAP = 3
_EDGE_PAD = 2
_TINY_HOST_W = 40
_MAX_LABEL_ROWS = 3
_LINE_Z = 800
_EXTREMA_Z = 850
_LEADER_Z = 790
_TETHER_Z = 795
_TETHER_CLEARANCE = 6.0
_TETHER_STUB = 8.0
_TETHER_PORT_RADIUS = 2.25
_SINGLE_COLOR = "#54749d"
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


_EXTREMA_PEN_CACHE = {}
_EXTREMA_BRUSH_CACHE = {}
_LEADER_PEN = None


def _extrema_pen(alpha):
    key = int(alpha)
    pen = _EXTREMA_PEN_CACHE.get(key)
    if pen is None:
        pen = pg.mkPen(QColor(255, 255, 255, key), width=1.0)
        _EXTREMA_PEN_CACHE[key] = pen
    return pen


def _extrema_brush(color, alpha):
    key = (str(color), int(alpha))
    brush = _EXTREMA_BRUSH_CACHE.get(key)
    if brush is None:
        painted = QColor(color)
        painted.setAlpha(int(alpha))
        brush = pg.mkBrush(painted)
        _EXTREMA_BRUSH_CACHE[key] = brush
    return brush


def _leader_pen():
    global _LEADER_PEN
    if _LEADER_PEN is None:
        color = QColor(_SINGLE_COLOR)
        color.setAlpha(255)
        _LEADER_PEN = QPen(color, 1.5)
    return _LEADER_PEN


def _tether_pen(highlighted=False):
    color = QColor("#607892")
    color.setAlpha(185 if highlighted else 118)
    return QPen(color, 1.0, Qt.DashLine)


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


def axis_label_outer_size(text, fm, *, content_margins=None):
    """Return the painted chip's one canonical device-independent size.

    ``layout_pinned_axis_labels`` and :class:`PinnedAxisLabel` must agree on
    the *outer* rect: the caption's actual advance, the QHBoxLayout margins,
    and the one-pixel painted frame.  ``QFontMetrics`` already reflects the
    current logical DPI, so no second DPR scale may be applied here.
    """
    left, top, right, bottom = (
        _LABEL_CONTENT_MARGINS if content_margins is None else tuple(content_margins)
    )
    frame = _LABEL_FRAME_ALLOWANCE * 2
    width = max(
        18,
        int(fm.horizontalAdvance(str(text))) + left + right + frame,
    )
    # QLabel's single-line size hint follows line spacing rather than only the
    # glyph bounding height; reserving that leading keeps the bottom border
    # from squeezing the real painted caption on platform font substitutions.
    content_height = max(int(fm.height()), int(fm.lineSpacing()))
    height = max(_LABEL_H, content_height + top + bottom + frame)
    return width, height


def axis_label_member_min_width(text, fm, *, content_margins=None):
    """Member-button width uses the same horizontal ink budget as the chip."""
    left, _top, right, _bottom = (
        _LABEL_CONTENT_MARGINS if content_margins is None else tuple(content_margins)
    )
    return max(
        18,
        int(fm.horizontalAdvance(str(text))) + left + right + _LABEL_FRAME_ALLOWANCE * 2,
    )


def _label_width(text, fm, *, content_margins=None):
    return axis_label_outer_size(text, fm, content_margins=content_margins)[0]


def _group_label_text(group):
    """Keep a co-located dual cursor readable without merging A/B identity."""
    if len(group) == 2:
        record_ids = {str(item["record_id"]) for item in group}
        endpoints = {str(item["endpoint"]) for item in group}
        if len(record_ids) == 1 and endpoints == {"a", "b"}:
            return f"P{group[0]['ordinal']}·A/B"
    return cluster_label_text(item["ordinal"] for item in group)


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
class PinnedTetherPort:
    """A candidate exit on the outside of a pinned panel, in canvas pixels."""

    side: str
    point: tuple[float, float]


@dataclass(frozen=True)
class PinnedPanelTether:
    """Transient panel-to-line projection in canvas coordinates only."""

    record_id: str
    endpoints: tuple[str, ...]
    panel_port: tuple[float, float]
    visible: bool = True
    panel_rect: tuple[float, float, float, float] | None = None
    ports: tuple[PinnedTetherPort, ...] = ()
    obstacles: tuple[tuple[float, float, float, float], ...] = ()
    host_rect: tuple[float, float, float, float] | None = None


def _as_rectf(rect):
    if rect is None:
        return None
    if isinstance(rect, QRectF):
        return QRectF(rect)
    if isinstance(rect, QRect):
        return QRectF(rect)
    try:
        x, y, w, h = rect
    except (TypeError, ValueError):
        return None
    return QRectF(float(x), float(y), float(w), float(h))


def _inflate_rect(rect, margin):
    mapped = _as_rectf(rect)
    if mapped is None or not mapped.isValid():
        return None
    return mapped.adjusted(-margin, -margin, margin, margin)


def _point_in_rect(point, rect):
    if rect is None or not rect.isValid():
        return False
    return rect.contains(QPointF(float(point[0]), float(point[1])))


def _segment_hits_rect(p1, p2, rect):
    if rect is None or not rect.isValid():
        return False
    start = QPointF(float(p1[0]), float(p1[1]))
    end = QPointF(float(p2[0]), float(p2[1]))
    if rect.contains(start) or rect.contains(end):
        return True
    line = QLineF(start, end)
    edges = (
        QLineF(rect.topLeft(), rect.topRight()),
        QLineF(rect.topRight(), rect.bottomRight()),
        QLineF(rect.bottomRight(), rect.bottomLeft()),
        QLineF(rect.bottomLeft(), rect.topLeft()),
    )
    hit_point = QPointF()
    for edge in edges:
        hit = line.intersect(edge, hit_point)
        if hit == QLineF.BoundedIntersection:
            return True
    return False


def _path_hits_rects(points, rects):
    if len(points) < 2:
        return any(_point_in_rect(points[0], rect) for rect in rects) if points else False
    for rect in rects:
        for point in points:
            if _point_in_rect(point, rect):
                return True
        for index in range(len(points) - 1):
            if _segment_hits_rect(points[index], points[index + 1], rect):
                return True
    return False


def tether_candidate_ports(panel_rect, *, clearance=_TETHER_CLEARANCE):
    """Return outside ports for a panel rectangle in canvas coordinates."""
    rect = _as_rectf(panel_rect)
    if rect is None or not rect.isValid():
        return ()
    gap = max(_TETHER_PORT_RADIUS + 2.0, float(clearance))
    cx = rect.center().x()
    cy = rect.center().y()
    return (
        PinnedTetherPort("bottom", (cx, rect.bottom() + gap)),
        PinnedTetherPort("left", (rect.left() - gap, cy)),
        PinnedTetherPort("right", (rect.right() + gap, cy)),
        PinnedTetherPort("top", (cx, rect.top() - gap)),
    )


def _stub_end(port, *, length=_TETHER_STUB):
    x, y = port.point
    if port.side == "bottom":
        return (x, y + length)
    if port.side == "top":
        return (x, y - length)
    if port.side == "left":
        return (x - length, y)
    return (x + length, y)


def _blocked_rects(panel_rect, obstacles, *, margin=1.0):
    blocked = []
    for item in (panel_rect,) + tuple(obstacles or ()):
        inflated = _inflate_rect(item, margin)
        if inflated is not None:
            blocked.append(inflated)
    return tuple(blocked)


def _visible_target_y(target_x, host, blocked):
    if host is None or not host.isValid():
        return None
    candidates = []
    for rect in blocked:
        candidates.append(rect.bottom() + _TETHER_CLEARANCE)
        candidates.append(rect.top() - _TETHER_CLEARANCE)
    candidates.extend((
        host.center().y(),
        host.top() + host.height() * 0.38,
        host.top() + host.height() * 0.62,
        host.bottom() - 12.0,
        host.top() + 12.0,
    ))
    for y in candidates:
        point = (float(target_x), float(y))
        if not host.contains(QPointF(*point)):
            continue
        if any(_point_in_rect(point, rect) for rect in blocked):
            continue
        return float(y)
    return None


def _candidate_paths(port, target):
    px, py = port.point
    tx, ty = target
    stub = _stub_end(port)
    return (
        (port.point, (tx, py), target),
        (port.point, (px, ty), target),
        (port.point, stub, (tx, stub[1]), target),
        (port.point, stub, (stub[0], ty), target),
        (port.point, stub, (tx, stub[1]), (tx, ty)),
    )


def route_panel_tether(
    *,
    panel_rect,
    ports,
    obstacles,
    target_xs,
    host_rect,
    share_stub=False,
):
    """Return visible canvas-space polylines that stay outside panel rects.

    ``target_xs`` are canvas X positions on the real cursor line.  The Y is
    chosen so the landing sits on that line *and* outside every blocked panel.
    If no clear route exists, only the first outside port is returned.
    """
    host = _as_rectf(host_rect)
    blocked = _blocked_rects(panel_rect, obstacles)
    port_list = tuple(ports or tether_candidate_ports(panel_rect))
    targets = []
    for target_x in target_xs:
        y = _visible_target_y(target_x, host, blocked)
        if y is None:
            continue
        targets.append((float(target_x), y))
    chosen_port = port_list[0] if port_list else None
    if chosen_port is None:
        return None, ()
    if not targets:
        return chosen_port, ()

    def first_clear(paths_for_port):
        for path in paths_for_port:
            if not _path_hits_rects(path, blocked):
                return path
        return None

    if share_stub and len(targets) > 1:
        for port in port_list:
            stub = _stub_end(port)
            branches = []
            ok = True
            shared = (port.point, stub)
            if _path_hits_rects(shared, blocked):
                continue
            for target in targets:
                branch = first_clear((
                    (stub, (target[0], stub[1]), target),
                    (stub, (stub[0], target[1]), target),
                    (stub, target),
                ))
                if branch is None:
                    ok = False
                    break
                branches.append((port.point,) + branch)
            if ok:
                return port, tuple(branches)
    for port in port_list:
        paths = []
        ok = True
        for target in targets:
            path = first_clear(_candidate_paths(port, target))
            if path is None:
                ok = False
                break
            paths.append(path)
        if ok:
            return port, tuple(paths)
    return chosen_port, ()


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
    # ``key`` and the layout slot are projection details.  Input is always
    # addressed to this stable record/endpoint pair, including co-located A/B.
    members: tuple[tuple[str, str, str, int], ...]


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
    axis_floor=None,
    content_margins=None,
):
    """Place axis-edge chips in a finite band. Never shove infinitely left."""
    left = int(axis_left)
    right = int(axis_right)
    top = int(axis_top)
    height = max(12, int(axis_height))
    width = right - left
    margins = (
        _LABEL_CONTENT_MARGINS if content_margins is None else tuple(content_margins)
    )

    def chip_width(text):
        return axis_label_outer_size(text, fm, content_margins=margins)[0]

    if width < 8 or not endpoints:
        return ()

    tiny = width < _TINY_HOST_W
    visible = [item for item in endpoints if item.get("offscreen") is None]
    left_off = [item for item in endpoints if item.get("offscreen") == "left"]
    right_off = [item for item in endpoints if item.get("offscreen") == "right"]
    unrepresentable = [
        item for item in endpoints if item.get("offscreen") == "unrepresentable"
    ]
    items = []
    if tiny:
        ordinals = tuple(item["ordinal"] for item in endpoints)
        record_ids = tuple(item["record_id"] for item in endpoints)
        text = _group_label_text(endpoints) if len(ordinals) > 1 else (
            endpoints[0]["text"] if endpoints else "P"
        )
        chip_w = min(width, chip_width(text))
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
                (
                    item["record_id"], item["endpoint"], item["text"],
                    item["ordinal"],
                )
                for item in endpoints
            ),
        ))
        return _stamp_stable_keys(tuple(items))

    def _place_group(group, *, kind, offscreen, edge_x=None, row_top=None):
        if not group:
            return None
        ordinals = tuple(item["ordinal"] for item in group)
        record_ids = tuple(item["record_id"] for item in group)
        if kind == "cluster" or len(group) > 1:
            text = _group_label_text(group)
            kind = "cluster"
        else:
            text = group[0]["text"]
            kind = "edge" if offscreen else "pin"
        if offscreen == "left":
            text = f"◀{text}"
        elif offscreen == "right":
            text = f"{text}▶"
        elif offscreen == "unrepresentable":
            text = PINNED_UNREPRESENTABLE_TEXT
        chip_w = chip_width(text)
        true_x = float(group[0]["canvas_x"])
        if edge_x is not None:
            center = float(edge_x)
        else:
            center = true_x
        x = int(round(center - chip_w / 2.0))
        x = max(left + _EDGE_PAD, min(x, right - chip_w - _EDGE_PAD))
        row_top = top if row_top is None else int(row_top)
        rect = (x, row_top, chip_w, height)
        leader = None
        label_cx = x + chip_w / 2.0
        if offscreen is None and abs(label_cx - true_x) > 1.5:
            y0 = float(row_top + height)
            y1 = float(row_top + height - 2)
            leader = (true_x, y0, label_cx, y1)
        members = tuple(
            (
                item["record_id"], item["endpoint"], item["text"],
                item["ordinal"],
            )
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
            chip_width(prev["text"]) / 2.0
            + chip_width(item["text"]) / 2.0
            + _LABEL_GAP
        )
        if abs(item["canvas_x"] - prev["canvas_x"]) <= span:
            groups[-1].append(item)
        else:
            groups.append([item])

    floor = top if axis_floor is None else int(axis_floor)
    max_rows = max(1, min(
        _MAX_LABEL_ROWS, 1 + max(0, top - floor) // (height + _LABEL_GAP),
    ))
    row_rights = [left] * max_rows
    for group in groups:
        base = _place_group(
            group, kind="cluster" if len(group) > 1 else "pin", offscreen=None,
        )
        if base is None:
            continue
        _x, _y, width_hint, _h = base.canvas_rect
        row_index = next(
            (
                index for index, last_right in enumerate(row_rights)
                if base.canvas_rect[0] >= last_right + _LABEL_GAP
            ),
            None,
        )
        if row_index is None:
            # All finite rows are occupied at this X.  Merge only the nearest
            # same-row chip, retaining every record/endpoint as local members
            # instead of replacing them with an inaccessible aggregate.
            row_index = min(
                range(max_rows), key=lambda index: row_rights[index],
            )
            prior = next(
                (
                    item for item in reversed(placed)
                    if item.canvas_rect[1] == top - row_index * (height + _LABEL_GAP)
                ),
                None,
            )
            if prior is not None:
                placed.remove(prior)
                group = [
                    {
                        "record_id": record_id,
                        "endpoint": endpoint,
                        "text": text,
                        "ordinal": ordinal,
                        "canvas_x": prior.true_x,
                        "offscreen": None,
                    }
                    for record_id, endpoint, text, ordinal in prior.members
                ] + list(group)
        row_top = top - row_index * (height + _LABEL_GAP)
        geom = _place_group(
            group, kind="cluster" if len(group) > 1 else "pin",
            offscreen=None, row_top=row_top,
        )
        if geom is None:
            continue
        x, y, w, h = geom.canvas_rect
        x = max(row_rights[row_index] + _LABEL_GAP, x)
        x = min(x, right - w - _EDGE_PAD)
        label_cx = x + w / 2.0
        geom = replace(
            geom,
            canvas_rect=(x, y, w, h),
            leader=(
                None if abs(label_cx - geom.true_x) <= 1.5
                else (geom.true_x, float(y + h), label_cx, float(y + h - 2))
            ),
        )
        placed.append(geom)
        row_rights[row_index] = x + w

    if left_off:
        geom = _place_group(
            left_off, kind="cluster" if len(left_off) > 1 else "edge",
            offscreen="left", edge_x=left + 10,
        )
        if geom is not None:
            placed.insert(0, geom)
    if unrepresentable:
        geom = _place_group(
            unrepresentable,
            kind="cluster" if len(unrepresentable) > 1 else "edge",
            offscreen="unrepresentable",
            edge_x=left + 10,
        )
        if geom is not None:
            placed.insert(1 if left_off else 0, geom)
    if right_off:
        geom = _place_group(
            right_off, kind="cluster" if len(right_off) > 1 else "edge",
            offscreen="right", edge_x=right - 10,
        )
        if geom is not None:
            placed.append(geom)
    return _stamp_stable_keys(tuple(placed))


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
            chip_w = axis_label_outer_size(text, fm)[0]
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


def _stamp_stable_keys(items):
    """Key chips by slot/edge, not member identity (F-P2-7)."""
    stamped = []
    slot = 0
    for geom in items:
        if geom.offscreen == "left":
            key = "edge:left"
        elif geom.offscreen == "right":
            key = "edge:right"
        elif geom.offscreen == "unrepresentable":
            key = "edge:unrepresentable"
        elif geom.key == "tiny":
            key = "tiny"
        else:
            key = f"slot:{slot}"
            slot += 1
        stamped.append(replace(geom, key=key))
    return tuple(stamped)


class PinnedAxisLabel(QFrame):
    """Axis-edge Pn chip with local pointer capture and keyboard routing.

    The label deliberately owns only raw Qt input.  Its controller receives a
    record UUID and endpoint for every semantic action; neither a layout slot
    nor a child-widget ordinal is an identity.
    """

    clicked = pyqtSignal(str)
    panel_requested = pyqtSignal(str, str)
    hover_changed = pyqtSignal(object)
    edit_started = pyqtSignal(str, str, object)
    edit_preview = pyqtSignal(str, str, object, object)
    edit_committed = pyqtSignal(str, str, object, object)
    edit_cancelled = pyqtSignal(str, str)
    nudge_requested = pyqtSignal(str, str, int, object)

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
        self._member_scroll = None
        self._member_host = None
        self._text = ""
        self._press = None
        self._dragged = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*_LABEL_CONTENT_MARGINS)
        lay.setSpacing(2)
        self._caption = QLabel(self)
        self._caption.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._caption.setAlignment(Qt.AlignCenter)
        font = QFont(self._caption.font())
        font.setPointSize(9)
        self._caption.setFont(font)
        lay.addWidget(self._caption)

    def apply_geom(self, geom: PinnedLabelGeom):
        # A geometry refresh must not turn a captured P1·A into whatever
        # happens to occupy this layout slot on the next frame.
        if self._press is not None:
            return
        self._geom = geom
        self._text = geom.text
        self._caption.setText(geom.text)
        self._caption.setVisible(not self._expanded)
        x, y, w, h = geom.canvas_rect
        # The solver already measured this caption with the production font
        # and frame.  Applying a second, larger size here would desync the
        # hit target from the laid-out chip.
        if self._expanded and geom.kind == "cluster" and len(geom.members) > 1:
            self._release_size_constraint()
            self._ensure_members(geom)
            self.setFixedSize(max(16, w), max(12, h))
        else:
            if self._expanded:
                self._expanded = False
                self._caption.setVisible(True)
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

    def pointer_captured(self):
        """Whether a stable record/endpoint owns pointer capture right now."""
        return self._press is not None

    def _tooltip(self, geom):
        if geom.offscreen == "unrepresentable":
            return PINNED_UNREPRESENTABLE_TEXT
        if geom.offscreen:
            return PINNED_OFFSCREEN_TEXT
        if geom.kind == "cluster":
            return " ".join(f"P{item}" for item in geom.ordinals)
        return geom.text

    def _release_size_constraint(self):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

    def _member_min_width(self, button, text):
        fm = QFontMetrics(button.font())
        return axis_label_member_min_width(text, fm)

    def _ensure_members(self, geom):
        if self._buttons and len(self._buttons) == len(geom.members):
            for button, member in zip(self._buttons, geom.members):
                record_id, endpoint, text, _ordinal = member
                button.setText(text)
                button.setProperty("record_id", member[0])
                button.setProperty("endpoint", endpoint)
                button.setMinimumWidth(self._member_min_width(button, text))
            return
        self._clear_members()
        scroll = QScrollArea(self)
        scroll.setObjectName("pinnedAxisLabelMembers")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(False)
        host = QWidget(scroll)
        members_layout = QHBoxLayout(host)
        members_layout.setContentsMargins(0, 0, 0, 0)
        members_layout.setSpacing(2)
        scroll.setWidget(host)
        self.layout().addWidget(scroll)
        self._member_scroll = scroll
        self._member_host = host
        for record_id, endpoint, text, _ordinal in geom.members:
            button = QPushButton(text, host)
            button.setObjectName("pinnedAxisLabelMember")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.TabFocus)
            button.setFixedHeight(_LABEL_H - 2)
            button.setMinimumWidth(self._member_min_width(button, text))
            button.setProperty("record_id", record_id)
            button.setProperty("endpoint", endpoint)
            button.installEventFilter(self)
            members_layout.addWidget(button)
            self._buttons.append(button)

    def _clear_members(self):
        for button in self._buttons:
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self._buttons = []
        scroll = self._member_scroll
        self._member_scroll = None
        self._member_host = None
        if scroll is not None:
            layout = self.layout()
            if layout is not None:
                layout.removeWidget(scroll)
            scroll.hide()
            scroll.setParent(None)
            scroll.deleteLater()

    @staticmethod
    def _event_global_pos(source, event):
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return QPoint(global_pos())
        pos = getattr(event, "pos", None)
        return source.mapToGlobal(pos()) if callable(pos) else QPoint()

    def _target_for(self, source):
        if source in self._buttons:
            record_id = source.property("record_id")
            endpoint = source.property("endpoint")
            if record_id and endpoint:
                return str(record_id), str(endpoint)
            return None, None
        geom = self._geom
        if geom is None or geom.kind == "cluster" or len(geom.members) != 1:
            return None, None
        record_id, endpoint, _text, _ordinal = geom.members[0]
        return str(record_id), str(endpoint)

    def _begin_pointer(self, source, event):
        record_id, endpoint = self._target_for(source)
        if record_id is None or endpoint is None:
            return False
        self.setFocus(Qt.MouseFocusReason)
        self._dragged = False
        self._press = (source, record_id, endpoint, self._event_global_pos(source, event))
        # Direction labels are intentionally toggle-only: their edge position
        # is not the record's data coordinate.
        if self._geom is not None and self._geom.offscreen:
            return True
        self.edit_started.emit(record_id, endpoint, self._press[3])
        try:
            source.grabMouse()
        except RuntimeError:
            # Offscreen and some QPA plugins refuse grabMouse.  The press
            # source still owns the matching move/release we dispatch to it.
            pass
        return True

    def _move_pointer(self, source, event):
        press = self._press
        if press is None or press[0] is not source:
            return False
        global_pos = self._event_global_pos(source, event)
        if not self._dragged:
            distance = QApplication.startDragDistance()
            if abs(global_pos.x() - press[3].x()) <= distance:
                return True
            if self._geom is not None and self._geom.offscreen:
                return True
            self._dragged = True
            self.setCursor(Qt.ClosedHandCursor)
        self.edit_preview.emit(press[1], press[2], global_pos, event.modifiers())
        return True

    def _release_pointer(self, source, event):
        press = self._press
        if press is None or press[0] is not source:
            return False
        global_pos = self._event_global_pos(source, event)
        try:
            source.releaseMouse()
        except RuntimeError:
            pass
        self._press = None
        self.setCursor(Qt.PointingHandCursor)
        # A native or offscreen QPA may coalesce a short drag into its final
        # release.  The release coordinate remains authoritative: do the same
        # threshold classification here that ``_move_pointer`` would have
        # performed, rather than cancelling the provisional edit as a click.
        if (
            not self._dragged
            and not (self._geom is not None and self._geom.offscreen)
            and abs(global_pos.x() - press[3].x())
            > QApplication.startDragDistance()
        ):
            self._dragged = True
        if self._dragged:
            self.edit_committed.emit(
                press[1], press[2], global_pos, event.modifiers(),
            )
        else:
            # ``begin_axis_edit`` snapshots before the threshold so a drag can
            # retain the exact endpoint/capture.  A click never edits X, so it
            # must explicitly cancel that provisional transaction before
            # toggling the panel; otherwise the next label press restores an
            # old collapsed projection over the newly expanded card.
            self.edit_cancelled.emit(press[1], press[2])
            self.panel_requested.emit(press[1], press[2])
            self.clicked.emit(press[1])
        self._dragged = False
        return True

    def _cancel_pointer(self):
        press = self._press
        if press is None:
            return
        self._press = None
        self._dragged = False
        try:
            press[0].releaseMouse()
        except RuntimeError:
            pass
        self.setCursor(Qt.PointingHandCursor)
        self.edit_cancelled.emit(press[1], press[2])

    def enterEvent(self, event):
        super().enterEvent(event)
        geom = self._geom
        if geom is None:
            return
        if geom.kind == "cluster" and len(geom.members) > 1:
            self._expanded = True
            self._caption.setVisible(False)
            self._release_size_constraint()
            self._ensure_members(geom)
            _x, _y, width, height = geom.canvas_rect
            self.setFixedSize(max(16, width), max(12, height))
            self.raise_()
        ids = geom.record_ids
        self.hover_changed.emit(ids[0] if len(ids) == 1 else ids)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._press is not None:
            return
        if self._expanded:
            self._expanded = False
            self._clear_members()
            if self._geom is not None:
                self.apply_geom(self._geom)
        self.hover_changed.emit(None)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._begin_pointer(self, event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._move_pointer(self, event):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._release_pointer(self, event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        record_id, endpoint = self._target_for(self)
        if record_id is not None and endpoint is not None:
            if event.key() == Qt.Key_Escape:
                self._cancel_pointer()
                event.accept()
                return
            if event.key() in (Qt.Key_Left, Qt.Key_Right):
                self.nudge_requested.emit(
                    record_id, endpoint,
                    -1 if event.key() == Qt.Key_Left else 1,
                    self.mapToGlobal(self.rect().center()),
                )
                event.accept()
                return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self._cancel_pointer()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self._cancel_pointer()
        super().hideEvent(event)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched not in self._buttons:
            return super().eventFilter(watched, event)
        etype = event.type()
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._begin_pointer(watched, event):
                event.accept()
                return True
        elif etype == QEvent.MouseMove and self._move_pointer(watched, event):
            event.accept()
            return True
        elif etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._release_pointer(watched, event):
                event.accept()
                return True
        elif etype == QEvent.KeyPress:
            record_id, endpoint = self._target_for(watched)
            if record_id is not None and endpoint is not None:
                if event.key() == Qt.Key_Escape:
                    self._cancel_pointer()
                    event.accept()
                    return True
                if event.key() in (Qt.Key_Left, Qt.Key_Right):
                    self.nudge_requested.emit(
                        record_id, endpoint,
                        -1 if event.key() == Qt.Key_Left else 1,
                        watched.mapToGlobal(watched.rect().center()),
                    )
                    event.accept()
                    return True
        elif etype in (QEvent.FocusOut, QEvent.Hide):
            self._cancel_pointer()
        return super().eventFilter(watched, event)

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
        "_tethers",
        "_highlight_id",
        "_line_items",
        "_leader_items",
        "_tether_items",
        "_tether_port_items",
        "_extrema_items",
        "_item_owners",
        "_layout",
        "_on_layout",
        "_view_hooks",
        "_rebuild_hooks",
        "_projecting",
        "_label_font",
        "_label_probe",
        "_label_size_cache",
        "_geom_timer",
        "_line_highlight",
    })
    _delegate_names = frozenset()

    def __init__(self, canvas, *, kind):
        super().__init__(canvas)
        self._kind = str(kind)
        self._records = ()
        self._tethers = ()
        self._highlight_id = None
        self._line_items = {}
        self._leader_items = []
        self._tether_items = []
        self._tether_port_items = []
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
        self._label_probe = None
        self._label_size_cache = {}
        self._line_highlight = {}
        self._geom_timer = QTimer(canvas)
        self._geom_timer.setSingleShot(True)
        self._geom_timer.setInterval(0)
        self._geom_timer.timeout.connect(self._reproject_geometry)
        self._install_rebuild_hooks()

    def set_layout_callback(self, callback: Callable | None) -> None:
        self._on_layout = callback

    def set_records(self, records) -> None:
        self._records = tuple(records or ())
        self.reproject()

    def set_tethers(self, tethers) -> None:
        """Apply transient panel ports without changing Pin facts or intent."""
        self._tethers = tuple(tethers or ())
        self._sync_tethers()

    def records(self):
        return self._records

    def tether_items(self):
        return tuple(item for item in self._tether_items if _alive(item))

    def tether_port_items(self):
        return tuple(item for item in self._tether_port_items if _alive(item))

    def tether_endpoint_keys_for(self, record_id):
        for tether in self._tethers:
            if tether.visible and str(tether.record_id) == str(record_id):
                return tuple(tether.endpoints)
        return ()

    def layout(self) -> PinnedOverlayLayout:
        return self._layout

    def offscreen_record_ids(self):
        return self._layout.offscreen_ids

    def set_highlight(self, record_id) -> None:
        target = None if record_id in (None, "", (), []) else record_id
        self._highlight_id = target
        self._apply_highlight()
        self._sync_tethers()

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
        self._stop_geom_timer()
        self._disconnect_view_hooks()
        self._remove_items(self._all_managed_items())
        self._line_items = {}
        self._leader_items = []
        self._tether_items = []
        self._tether_port_items = []
        self._extrema_items = []
        self._item_owners = {}
        self._line_highlight = {}

    def clear(self) -> None:
        self._records = ()
        self._tethers = ()
        self._highlight_id = None
        self.clear_items()
        self._destroy_label_probe()
        self._label_size_cache = {}
        self._layout = PinnedOverlayLayout(
            host_rect=None, items=(), offscreen_ids=frozenset(), pending=True,
        )
        callback = self._on_layout
        if callable(callback):
            callback(self._layout)

    def reproject(self, *_args) -> None:
        self._stop_geom_timer()
        self._reproject(full=True)

    def _reproject_geometry(self, *_args) -> None:
        self._reproject(full=False)

    def _stop_geom_timer(self) -> None:
        timer = getattr(self, "_geom_timer", None)
        if _alive(timer):
            timer.stop()

    def _reproject(self, *, full) -> None:
        if self._projecting:
            return
        canvas = self._c
        if not _alive(canvas):
            return
        self._projecting = True
        try:
            if full:
                self._sync_view_hooks()
            host = self._host_rect()
            pending = host is None
            if not self._records:
                if full:
                    self.clear_items()
                else:
                    self._sync_leaders(PinnedOverlayLayout(
                        host_rect=None, items=(), offscreen_ids=frozenset(),
                        pending=pending,
                    ))
                    self._sync_tethers()
                self._layout = PinnedOverlayLayout(
                    host_rect=None if host is None else (
                        host.x(), host.y(), host.width(), host.height()
                    ),
                    items=(),
                    offscreen_ids=frozenset(),
                    pending=pending,
                )
            elif full:
                self._sync_lines()
                self._sync_extrema()
                self._layout = self._build_layout(host)
                self._sync_leaders(self._layout)
                self._sync_tethers()
                self._apply_highlight()
            else:
                self._layout = self._build_layout(host)
                self._sync_leaders(self._layout)
                self._sync_tethers()
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
        if self._projecting:
            return
        timer = self._geom_timer
        if not _alive(timer):
            self._reproject_geometry()
            return
        if not timer.isActive():
            timer.start()

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

    def _physical_x_for_view(self, value):
        view_x = _finite(value)
        if view_x is None:
            return None
        if self._kind != "frf":
            return view_x
        converter = getattr(self._c, "_view_x_to_hz", None)
        if not callable(converter):
            return view_x
        try:
            return _finite(converter(view_x))
        except (RuntimeError, TypeError, ValueError):
            return None

    def bottom_axis_global_to_viewport(self, global_pos):
        """Map an axis-label global X into the bottom data ViewBox.

        Labels live below the data rectangle.  Mapping their Y straight into a
        cursor evaluator makes otherwise valid bottom controls look like a
        miss, so preserve the global X and select a known in-data scene Y.
        ``QGraphicsView.mapToScene`` receives viewport coordinates only.
        """
        canvas = self._c
        glw = getattr(canvas, "_glw", None)
        vb = self._bottom_viewbox()
        if not _alive(glw) or not _alive(vb):
            return None
        try:
            viewport = glw.viewport()
            if not _alive(viewport):
                return None
            raw = viewport.mapFromGlobal(QPoint(global_pos))
            scene = glw.mapToScene(raw)
            rect = vb.sceneBoundingRect()
            if not rect.isValid():
                return None
            return glw.mapFromScene(QPointF(scene.x(), rect.center().y()))
        except (RuntimeError, TypeError, AttributeError, ValueError):
            return None

    def bottom_axis_viewport_pos_for_physical(self, physical_x):
        """Return an in-data viewport point for a persisted physical X."""
        canvas = self._c
        glw = getattr(canvas, "_glw", None)
        vb = self._bottom_viewbox()
        view_x = self._view_x(physical_x)
        if view_x is None or not _alive(glw) or not _alive(vb):
            return None
        try:
            rect = vb.sceneBoundingRect()
            if not rect.isValid():
                return None
            view_y = vb.mapSceneToView(rect.center()).y()
            scene = vb.mapViewToScene(QPointF(view_x, view_y))
            return glw.mapFromScene(scene)
        except (RuntimeError, TypeError, AttributeError, ValueError):
            return None

    def bottom_axis_physical_bounds(self):
        vb = self._bottom_viewbox()
        view_bounds = self._view_range(vb)
        if view_bounds is None:
            return None
        lo = self._physical_x_for_view(view_bounds[0])
        hi = self._physical_x_for_view(view_bounds[1])
        if lo is None or hi is None:
            return None
        return (min(lo, hi), max(lo, hi))

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
            self._line_highlight.pop(key, None)
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
                self._line_highlight.pop(key, None)
            for line in items:
                try:
                    line.setValue(float(view_x))
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
        # A single P line needs enough contrast against dense curves without
        # changing the A/B endpoint or channel-colour contracts.  Selection
        # makes only the single-record chrome blue; dual A/B keep their own
        # established semantic colours.
        if endpoint_key == "x":
            color = "#006bea" if highlighted else _SINGLE_COLOR
            width = 2.25 if highlighted else 1.5
            return _pen(color, alpha=255, width=width)
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
                    pen=[_extrema_pen(point[5]) for point in points],
                    brush=[
                        _extrema_brush(point[2], point[5]) for point in points
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
        fm, margins = self._axis_label_style()
        endpoints = []
        offscreen_ids = set()
        for record in self._records:
            flags = []
            for endpoint in record.endpoints:
                view_x = self._view_x(endpoint.physical_x)
                canvas_x = (
                    self._canvas_x(vb, view_x)
                    if vb is not None and view_x is not None else None
                )
                offscreen = None
                if view_x is None:
                    offscreen = "unrepresentable"
                elif view_range is None:
                    offscreen = "left"
                elif view_x < view_range[0]:
                    offscreen = "left"
                elif view_x > view_range[1]:
                    offscreen = "right"
                flags.append(offscreen)
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
            if flags and all(flag in ("left", "right") for flag in flags):
                offscreen_ids.add(record.record_id)
        label_height = axis_label_outer_size("P", fm, content_margins=margins)[1]
        tiny = host.width() < _TINY_HOST_W or host.height() < label_height + 2
        axis_top = host.bottom() - label_height - 1
        if axis_top < host.top():
            axis_top = host.top()
        items = layout_pinned_axis_labels(
            endpoints,
            axis_left=host.left(),
            axis_right=host.right(),
            axis_top=axis_top,
            axis_height=label_height,
            fm=fm,
            axis_floor=host.top(),
            content_margins=margins,
        )
        return PinnedOverlayLayout(
            host_rect=(host.x(), host.y(), host.width(), host.height()),
            items=items,
            offscreen_ids=frozenset(offscreen_ids),
            pending=False,
            tiny=tiny,
        )

    def _sync_leaders(self, layout: PinnedOverlayLayout) -> None:
        glw = getattr(self._c, "_glw", None)
        canvas = self._c
        wanted = []
        if _alive(glw) and _alive(canvas):
            try:
                scene = glw.scene()
                viewport = glw.viewport()
            except (RuntimeError, TypeError, AttributeError):
                scene = None
                viewport = None
            if scene is not None and _alive(viewport):
                for geom in layout.items:
                    if geom.leader is None:
                        continue
                    x1, y1, x2, y2 = geom.leader
                    try:
                        p1 = glw.mapToScene(
                            viewport.mapFrom(canvas, QPointF(x1, y1).toPoint())
                        )
                        p2 = glw.mapToScene(
                            viewport.mapFrom(canvas, QPointF(x2, y2).toPoint())
                        )
                    except (RuntimeError, TypeError, AttributeError):
                        continue
                    wanted.append((p1, p2, scene))
        while len(self._leader_items) > len(wanted):
            extra = self._leader_items.pop()
            self._remove_items((extra,))
        if not wanted:
            return
        scene = wanted[0][2]
        while len(self._leader_items) < len(wanted):
            item = QGraphicsLineItem()
            item.setPen(_leader_pen())
            item.setZValue(_LEADER_Z)
            try:
                scene.addItem(item)
            except (RuntimeError, TypeError):
                break
            self._leader_items.append(item)
        for item, (p1, p2, _scene) in zip(self._leader_items, wanted):
            if not _alive(item):
                continue
            try:
                item.setLine(p1.x(), p1.y(), p2.x(), p2.y())
                item.setVisible(True)
            except RuntimeError:
                pass

    def _axis_label_style(self):
        """Return polished caption metrics and the widget's content margins."""
        probe = self._ensure_label_probe()
        font = self._label_font
        margins = _LABEL_CONTENT_MARGINS
        if probe is not None:
            try:
                probe.ensurePolished()
                probe._caption.ensurePolished()
                font = probe._caption.font()
                box = probe.layout().contentsMargins()
                margins = (box.left(), box.top(), box.right(), box.bottom())
            except RuntimeError:
                font = self._label_font
        return QFontMetrics(font), margins

    def _ensure_label_probe(self):
        probe = self._label_probe
        if _alive(probe):
            return probe
        canvas = self._c
        if not _alive(canvas):
            self._label_probe = None
            return None
        probe = PinnedAxisLabel(canvas)
        probe.hide()
        probe.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._label_probe = probe
        return probe

    def _destroy_label_probe(self) -> None:
        probe = self._label_probe
        self._label_probe = None
        if not _alive(probe):
            return
        try:
            probe.hide()
            probe.setParent(None)
            probe.deleteLater()
        except RuntimeError:
            pass

    def _sync_tethers(self) -> None:
        """Project expanded panel ports to their visible position line(s).

        Tethers are deliberately independent of label-avoidance leaders:
        labels are laid out in canvas coordinates, while these are supplied by
        the presenter from a live ``CursorPill`` position.  Neither path may
        mutate records, samples, or persisted anchors.  The scene stays under
        the QWidget panels, so visibility comes from routing outside those
        rects rather than from z-order.
        """
        glw = getattr(self._c, "_glw", None)
        canvas = self._c
        host = self._host_rect()
        bottom_vb = self._bottom_viewbox()
        wanted_paths = []
        wanted_ports = []
        if (
            _alive(glw)
            and _alive(canvas)
            and host is not None
            and _alive(bottom_vb)
        ):
            try:
                scene = glw.scene()
                viewport = glw.viewport()
            except (RuntimeError, TypeError, AttributeError):
                scene = None
                viewport = None
            if scene is not None and _alive(viewport):
                records = {str(record.record_id): record for record in self._records}

                def to_scene(point):
                    return glw.mapToScene(
                        viewport.mapFrom(canvas, QPointF(*point).toPoint())
                    )

                for tether in self._tethers:
                    if not tether.visible:
                        continue
                    record = records.get(str(tether.record_id))
                    if record is None:
                        continue
                    endpoints = {
                        str(endpoint.key): endpoint for endpoint in record.endpoints
                    }
                    target_xs = []
                    for endpoint_key in tether.endpoints:
                        endpoint = endpoints.get(str(endpoint_key))
                        if endpoint is None:
                            continue
                        view_x = self._view_x(endpoint.physical_x)
                        target_x = self._canvas_x(bottom_vb, view_x)
                        if (
                            target_x is None
                            or target_x < host.left() - 0.5
                            or target_x > host.right() + 0.5
                        ):
                            continue
                        target_xs.append(float(target_x))
                    host_tuple = tether.host_rect
                    if host_tuple is None:
                        host_tuple = (
                            float(host.x()), float(host.y()),
                            float(host.width()), float(host.height()),
                        )
                    share_stub = (
                        len(tether.endpoints) > 1 and len(target_xs) > 1
                    )
                    port, paths = route_panel_tether(
                        panel_rect=tether.panel_rect,
                        ports=tether.ports,
                        obstacles=tether.obstacles,
                        target_xs=target_xs,
                        host_rect=host_tuple,
                        share_stub=share_stub,
                    )
                    if port is None:
                        try:
                            fallback = (
                                float(tether.panel_port[0]),
                                float(tether.panel_port[1]),
                            )
                        except (TypeError, ValueError, IndexError):
                            continue
                        port = PinnedTetherPort("bottom", fallback)
                    highlighted = self._is_highlighted(str(tether.record_id))
                    tooltip = ""
                    if not paths:
                        missing = len(target_xs) < len(tether.endpoints)
                        tooltip = (
                            PINNED_OFFSCREEN_TEXT if missing
                            else PINNED_UNREPRESENTABLE_TEXT
                        )
                    try:
                        port_scene = to_scene(port.point)
                    except (RuntimeError, TypeError, AttributeError, ValueError):
                        continue
                    wanted_ports.append((port_scene, scene, highlighted, tooltip))
                    for points in paths:
                        try:
                            scene_points = [to_scene(point) for point in points]
                        except (
                            RuntimeError, TypeError, AttributeError, ValueError,
                        ):
                            continue
                        if not scene_points:
                            continue
                        path = QPainterPath(scene_points[0])
                        for scene_point in scene_points[1:]:
                            path.lineTo(scene_point)
                        wanted_paths.append((path, scene, highlighted, ""))

        self._sync_tether_graphics(
            self._tether_items,
            wanted_paths,
            QGraphicsPathItem,
            lambda item, path, highlighted: self._set_tether_path(
                item, path, highlighted,
            ),
        )
        self._sync_tether_graphics(
            self._tether_port_items,
            wanted_ports,
            QGraphicsEllipseItem,
            self._set_tether_port,
        )

    def _sync_tether_graphics(self, items, wanted, item_type, apply) -> None:
        while len(items) > len(wanted):
            self._remove_items((items.pop(),))
        if not wanted:
            return
        scene = wanted[0][1]
        if any(
            not _alive(item) or item.scene() is not scene
            for item in items
        ):
            self._remove_items(tuple(items))
            items.clear()
        while len(items) < len(wanted):
            item = item_type()
            item.setZValue(_TETHER_Z)
            try:
                scene.addItem(item)
            except (RuntimeError, TypeError):
                break
            items.append(item)
        for item, values in zip(items, wanted):
            if not _alive(item):
                continue
            try:
                apply(item, values[0], values[2])
                if len(values) > 3:
                    item.setToolTip(values[3] or "")
                item.setVisible(True)
            except RuntimeError:
                pass

    @staticmethod
    def _set_tether_path(item, path, highlighted) -> None:
        item.setPath(path)
        item.setPen(_tether_pen(highlighted))

    @staticmethod
    def _set_tether_port(item, point, highlighted) -> None:
        radius = _TETHER_PORT_RADIUS
        item.setRect(
            point.x() - radius, point.y() - radius, radius * 2, radius * 2,
        )
        pen = _tether_pen(highlighted)
        item.setPen(pen)
        fill = QColor(pen.color())
        fill.setAlpha(210 if highlighted else 145)
        item.setBrush(pg.mkBrush(fill))

    def _apply_highlight(self) -> None:
        extrema_needed = False
        for (record_id, endpoint_key), items in self._line_items.items():
            highlighted = self._is_highlighted(record_id)
            prev = self._line_highlight.get((record_id, endpoint_key))
            if prev is highlighted:
                continue
            self._line_highlight[(record_id, endpoint_key)] = highlighted
            if prev is None and not highlighted:
                continue
            extrema_needed = True
            for line in items:
                if not _alive(line):
                    continue
                try:
                    line.setPen(self._line_pen(endpoint_key, highlighted))
                except RuntimeError:
                    pass
        if extrema_needed and self._kind == "time" and self._records:
            self._sync_extrema()

    def _all_managed_items(self):
        items = []
        for group in self._line_items.values():
            items.extend(group)
        items.extend(self._leader_items)
        items.extend(self._tether_items)
        items.extend(self._tether_port_items)
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
    "PINNED_UNREPRESENTABLE_TEXT",
    "PinnedAxisLabel",
    "PinnedCursorOverlay",
    "PinnedLabelGeom",
    "PinnedOverlayEndpoint",
    "PinnedOverlayLayout",
    "PinnedOverlayRecord",
    "PinnedPanelTether",
    "PinnedTetherPort",
    "axis_label_member_min_width",
    "axis_label_outer_size",
    "cluster_label_text",
    "layout_pinned_axis_labels",
    "route_panel_tether",
    "tether_candidate_ports",
]
