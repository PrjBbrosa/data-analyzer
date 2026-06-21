"""Shared point-remark helpers for pyqtgraph canvases."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QApplication

import pyqtgraph as pg


_ANNOTATION_CURSOR = None
_REMARK_DOT_COLOR = "#dc2626"


@dataclass(slots=True)
class RemarkPoint:
    """Data-space point plus display metadata for a chart remark."""

    vb: object
    x: float
    y: float
    color: str = _REMARK_DOT_COLOR
    unit_x: str = ""
    unit_y: str = ""
    z: float | None = None
    unit_z: str = ""


def _annotation_pen_cursor():
    global _ANNOTATION_CURSOR
    if _ANNOTATION_CURSOR is not None:
        return _ANNOTATION_CURSOR
    pix = QPixmap(24, 24)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(
            QPen(QColor("#1769e0"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawLine(6, 18, 17, 7)
        painter.drawLine(14, 6, 18, 10)
        painter.drawLine(5, 19, 9, 19)
        painter.setPen(
            QPen(QColor("#1e293b"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawEllipse(3, 17, 4, 4)
    finally:
        painter.end()
    _ANNOTATION_CURSOR = QCursor(pix, 5, 19)
    return _ANNOTATION_CURSOR


def _value_with_unit(value: float, unit: str) -> str:
    suffix = f" {escape(str(unit))}" if unit else ""
    return f"{float(value):.4g}{suffix}"


def format_remark_label(point: RemarkPoint) -> str:
    """Return the shared X=/Y=/Z= HTML label for point remarks."""

    y_color = escape(str(point.color or "#1769e0"), quote=True)
    rows = [
        f"<div>X={_value_with_unit(point.x, point.unit_x)}</div>",
        (
            f"<div style='color:{y_color}; font-weight:600;'>"
            f"Y={_value_with_unit(point.y, point.unit_y)}</div>"
        ),
    ]
    if point.z is not None:
        rows.append(f"<div>Z={_value_with_unit(point.z, point.unit_z)}</div>")
    return "".join(rows)


class RemarkArtist:
    """Create and remove the shared remark dot, leader, and draggable label."""

    def add(self, point: RemarkPoint):
        vb = point.vb
        dot = pg.ScatterPlotItem(
            x=[point.x],
            y=[point.y],
            size=8,
            pen=pg.mkPen(_REMARK_DOT_COLOR, width=1.5),
            brush=pg.mkBrush(_REMARK_DOT_COLOR),
            pxMode=True,
        )
        vb.addItem(dot)
        try:
            vrange = vb.viewRange()
            ox = (vrange[0][1] - vrange[0][0]) * 0.06
            oy = (vrange[1][1] - vrange[1][0]) * 0.08
        except Exception:
            ox, oy = 0.0, 0.0
        lx, ly = point.x + ox, point.y + oy
        leader = pg.PlotDataItem(
            x=[point.x, lx],
            y=[point.y, ly],
            pen=pg.mkPen(point.color or _REMARK_DOT_COLOR, width=1.0, style=Qt.DashLine),
        )
        vb.addItem(leader)
        text = pg.TextItem(
            html=format_remark_label(point),
            color=point.color or "#111827",
            fill=pg.mkBrush(255, 255, 255, 210),
            border=pg.mkPen(point.color or "#111827", width=0.8),
        )
        text.setPos(lx, ly)
        text.setFlag(text.ItemIsMovable, True)
        vb.addItem(text)
        remark = {
            "vb": vb,
            "dot": dot,
            "text": text,
            "label": text,
            "leader": leader,
            "data_x": float(point.x),
            "data_y": float(point.y),
            "data_z": None if point.z is None else float(point.z),
        }
        self._connect_leader(remark)
        return remark

    def _connect_leader(self, remark):
        text = remark["text"]
        try:
            text.sigPositionChanged.connect(
                lambda _item, r=remark: self.update_leader(r)
            )
        except Exception:
            orig_item_change = text.itemChange

            def patched_item_change(change, value, _r=remark, _orig=orig_item_change):
                result = _orig(change, value)
                if change == text.ItemPositionHasChanged:
                    self.update_leader(_r)
                return result

            text.itemChange = patched_item_change

    @staticmethod
    def update_leader(remark):
        try:
            text = remark["text"]
            dx, dy = remark["data_x"], remark["data_y"]
            lpos = text.pos()
            lx, ly = float(lpos.x()), float(lpos.y())
            remark["leader"].setData(x=[dx, lx], y=[dy, ly])
        except Exception:
            pass

    @staticmethod
    def remove(remark):
        vb = remark.get("vb")
        if vb is None:
            return
        for item_key in ("dot", "text", "leader"):
            item = remark.get(item_key)
            if item is not None:
                try:
                    vb.removeItem(item)
                except Exception:
                    pass

    def clear(self, remarks):
        for remark in list(remarks):
            self.remove(remark)
        remarks.clear()


class RemarkInteraction:
    """Shared annotation-mode mouse routing for pyqtgraph chart viewports."""

    def __init__(
        self,
        *,
        add_at_viewport_pos,
        remove_at_viewport_pos,
        remark_at_viewport_pos=None,
    ):
        self.enabled = False
        self.press_pos = None
        self.press_dragged = False
        self._add_at_viewport_pos = add_at_viewport_pos
        self._remove_at_viewport_pos = remove_at_viewport_pos
        self._remark_at_viewport_pos = remark_at_viewport_pos

    def set_enabled(self, enabled, *, viewport=None, menu_viewboxes=()):
        self.enabled = bool(enabled)
        self.clear_press_state()
        if viewport is not None:
            try:
                if self.enabled:
                    viewport.setCursor(_annotation_pen_cursor())
                else:
                    viewport.setCursor(Qt.ArrowCursor)
            except Exception:
                pass
        for vb in menu_viewboxes or ():
            try:
                vb.setMenuEnabled(not self.enabled)
            except Exception:
                pass

    def clear_press_state(self):
        self.press_pos = None
        self.press_dragged = False

    @staticmethod
    def drag_threshold():
        try:
            return max(1, int(QApplication.startDragDistance()))
        except Exception:
            return 10

    def handle_mouse_press(self, event):
        if not self.enabled:
            return None
        if event.button() == Qt.RightButton:
            self._remove_at_viewport_pos(event.pos())
            self.clear_press_state()
            return True
        if event.button() != Qt.LeftButton:
            return None
        if self._remark_at_viewport_pos is not None:
            try:
                if self._remark_at_viewport_pos(event.pos()) is not None:
                    self.clear_press_state()
                    return False
            except Exception:
                pass
        self.press_pos = event.pos()
        self.press_dragged = False
        return False

    def handle_mouse_move(self, event):
        if not self.enabled or self.press_pos is None:
            return None
        try:
            if event.buttons() & Qt.LeftButton:
                delta = event.pos() - self.press_pos
                if delta.manhattanLength() >= self.drag_threshold():
                    self.press_dragged = True
        except Exception:
            pass
        return False

    def handle_mouse_release(self, event):
        if not self.enabled or self.press_pos is None:
            return None
        if event.button() != Qt.LeftButton:
            self.clear_press_state()
            return None
        start_pos = self.press_pos
        try:
            delta = event.pos() - start_pos
            moved = delta.manhattanLength() >= self.drag_threshold()
        except Exception:
            moved = self.press_dragged
        dragged = self.press_dragged or moved
        self.clear_press_state()
        if dragged:
            return False
        self._add_at_viewport_pos(event.pos())
        return True


__all__ = [
    "RemarkArtist",
    "RemarkInteraction",
    "RemarkPoint",
    "_annotation_pen_cursor",
    "format_remark_label",
]
