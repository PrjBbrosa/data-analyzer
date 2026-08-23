"""Shared UltraView widget presentation helpers.

Polish/flag/elide widgets and the mime drag bridge. Board hosts receive
explicit Page ports instead of walking ``parentWidget()``. Library geometry,
card copy strings, planner logging, and board hosts stay with their owners.
"""
from __future__ import annotations

import json
import math
from typing import Callable

from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QMimeData, QPoint, Qt
from PyQt5.QtGui import QColor, QDrag, QPainter
from PyQt5.QtWidgets import QLabel, QSizePolicy, QWidget

from mf4_analyzer.ui.ultraview_state import (
    SECTION_LABELS_ZH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_REF_MIME,
    parse_ref_payload,
)

STATUS_LABELS_ZH = {
    "fresh": "最新",
    STATUS_STALE: "源已变化",
    STATUS_MISSING: "尚无可用结果",
    STATUS_ORPHANED: "源已删除",
}


class BoardPagePorts:
    """Explicit Page callbacks injected when Page constructs a Board.

    Standalone Board tests leave every field ``None``; product Page binds the
    live methods after tray, rail, and PointerRouter exist.
    """

    __slots__ = (
        "notify_canvas_click",
        "clear_card_selection",
        "handle_card_double_click",
        "is_unplaced_drop_target",
        "begin_connector_geometry",
        "sync_page_tool_cursor",
        "unset_viewport_cursor",
        "is_panning",
        "space_down",
        "draw_create_armed",
    )

    def __init__(self) -> None:
        self.notify_canvas_click: Callable[[], None] | None = None
        self.clear_card_selection: Callable[[], bool] | None = None
        self.handle_card_double_click: Callable[[str, str], None] | None = None
        self.is_unplaced_drop_target: Callable[[QPoint], bool] | None = None
        self.begin_connector_geometry: Callable[..., None] | None = None
        self.sync_page_tool_cursor: Callable[[], None] | None = None
        self.unset_viewport_cursor: Callable[[], None] | None = None
        self.is_panning: Callable[[], bool] | None = None
        self.space_down: Callable[[], bool] | None = None
        self.draw_create_armed: Callable[[], bool] | None = None

    def bind(self, **ports) -> None:
        for name, value in ports.items():
            if name not in self.__slots__:
                raise TypeError(f"unknown board page port: {name}")
            setattr(self, name, value)


def _effective_device_pixel_ratio(widget: QWidget) -> float:
    """Return a usable DPR without retaining a deleted Qt wrapper."""
    try:
        value = float(widget.devicePixelRatioF())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 1.0
    return value if math.isfinite(value) and value > 0.0 else 1.0


def _union_pixel_rect(rects) -> tuple[float, float, float, float] | None:
    boxes = [tuple(rect) for rect in rects if rect is not None]
    if not boxes:
        return None
    x0 = min(float(rect[0]) for rect in boxes)
    y0 = min(float(rect[1]) for rect in boxes)
    x1 = max(float(rect[0]) + float(rect[2]) for rect in boxes)
    y1 = max(float(rect[1]) + float(rect[3]) for rect in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def _run_ultraview_drag(source: QWidget, mime: QMimeData, action, finished) -> None:
    """Run QDrag without parenting it to a widget that drop handlers may destroy.

    Drop mutations refresh the library/grid/tray while ``exec_`` is still on
    the stack. Parenting the drag to ``source`` and emitting from a deleted
    wrapper both abort via qFatal. A stable window host plus ``sip.isdeleted``
    keeps the nested loop from tearing down its own source.
    """
    host = source.window() if source is not None else None
    if host is None or sip.isdeleted(host):
        host = source
    drag = QDrag(host)
    drag.setMimeData(mime)
    try:
        drag.exec_(action)
    finally:
        try:
            if source is not None and not sip.isdeleted(source):
                finished()
        except RuntimeError:
            # The wrapper can lose its C++ object between the sip check and
            # emit; never let that escape a Qt virtual (qFatal).
            pass

def make_ref_mime(section: str, view_id: str) -> QMimeData:
    mime = QMimeData()
    payload = json.dumps(
        {"section": section, "view_id": view_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    mime.setData(ULTRAVIEW_REF_MIME, QByteArray(payload.encode("utf-8")))
    return mime


def extract_ref_strings(mime: QMimeData | None) -> tuple[str, str] | None:
    """Copy ``section`` / ``view_id`` out of ``QMimeData`` immediately.

    Callers must not keep ``mime`` for a queued callback. Invalid payloads
    return ``None``.
    """
    if mime is None or not mime.hasFormat(ULTRAVIEW_REF_MIME):
        return None
    try:
        raw = bytes(mime.data(ULTRAVIEW_REF_MIME)).decode("utf-8")
        payload = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    section = payload.get("section")
    view_id = payload.get("view_id")
    if not isinstance(section, str) or not isinstance(view_id, str):
        return None
    section_copy = str(section)
    view_id_copy = str(view_id)
    if parse_ref_payload({"section": section_copy, "view_id": view_id_copy}) is None:
        return None
    return section_copy, view_id_copy

def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _set_flag(widget: QWidget, name: str, on: bool) -> None:
    widget.setProperty(name, "true" if on else "false")
    _repolish(widget)

def _elide(label: QLabel, text: str) -> None:
    metrics = label.fontMetrics()
    label.setText(metrics.elidedText(text, Qt.ElideRight, max(0, label.width())))
    label.setToolTip(text if metrics.horizontalAdvance(text) > label.width() else "")

def _full_tooltip(name: str, section: str, source_summary: str, status: str) -> str:
    section_label = SECTION_LABELS_ZH.get(section, section)
    status_label = STATUS_LABELS_ZH.get(status, status)
    lines = [name or view_fallback(section, ""), f"{section_label} · {source_summary}".strip(" ·")]
    if status_label:
        lines.append(status_label)
    return "\n".join(line for line in lines if line)


def view_fallback(section: str, view_id: str) -> str:
    return view_id or SECTION_LABELS_ZH.get(section, section)

def _accept_ultraview_drag(event) -> bool:
    mime = event.mimeData()
    if mime is not None and mime.hasFormat(ULTRAVIEW_REF_MIME):
        event.acceptProposedAction()
        return True
    event.ignore()
    return False

class _ColorDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#94a3b8")
        self.setFixedSize(8, 8)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color) if color else QColor("#94a3b8")
        if not self._color.isValid():
            self._color = QColor("#94a3b8")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


class _ElideLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        super().setText(text)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        _elide(self, self._full)
