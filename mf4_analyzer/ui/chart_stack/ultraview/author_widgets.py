"""Focused editor widgets for UltraView author-created content.

These widgets intentionally remain ordinary direct children of a Board.  A
paint-only transparent sibling may sit above or below them, but never becomes
their interactive parent.  That preserves native CJK IME delivery and lets the
Page's viewport gesture router distinguish real text input from canvas space.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt5.QtCore import QRect, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase, QInputMethodEvent, QTextOption
from PyQt5.QtWidgets import QFrame, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from mf4_analyzer.ui.ultraview_state import (
    MAX_STICKY_TEXT,
    MAX_TEXT_TEXT,
    BoardBox,
    StickyObject,
    TextObject,
)

from .author_geometry import board_box_to_pixels
from .author_style import DEFAULT_THEME, font_candidates, ink_color, sticky_colors
from .free_grid import GridMetrics


class _BoundedPlainTextEdit(QPlainTextEdit):
    """Plain-text editor that preserves CJK IME while exposing explicit exits."""

    commit_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    ime_committed = pyqtSignal(str)
    limit_reached = pyqtSignal()

    def __init__(self, limit: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._limit = max(1, int(limit))
        self._clamping = False
        self._ime_composing = False
        self.setTabChangesFocus(False)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.textChanged.connect(self._clamp_to_limit)

    def is_ime_composing(self) -> bool:
        return bool(self._ime_composing)

    def set_bounded_text(self, text: object) -> None:
        bounded = str(text or "")[: self._limit]
        self.blockSignals(True)
        try:
            self.setPlainText(bounded)
        finally:
            self.blockSignals(False)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._ime_composing and event.key() in (
            Qt.Key_Escape,
            Qt.Key_Return,
            Qt.Key_Enter,
        ):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & (
            Qt.ControlModifier | Qt.MetaModifier
        ):
            self.commit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        committed = event.commitString()
        self._ime_composing = bool(event.preeditString()) and not committed
        super().inputMethodEvent(event)
        if committed:
            self._ime_composing = False
            self.ime_committed.emit(committed)

    def _clamp_to_limit(self) -> None:
        if self._clamping:
            return
        text = self.toPlainText()
        if len(text) <= self._limit:
            return
        cursor = self.textCursor()
        position = min(cursor.position(), self._limit)
        self._clamping = True
        try:
            self.setPlainText(text[: self._limit])
            cursor = self.textCursor()
            cursor.setPosition(position)
            self.setTextCursor(cursor)
        finally:
            self._clamping = False
        self.limit_reached.emit()


class StickyNoteWidget(QFrame):
    """Bounded, direct-child Sticky editor projected from one ``StickyObject``."""

    text_committed = pyqtSignal(str, str)
    edit_cancelled = pyqtSignal(str)
    ime_committed = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewStickyNote")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self._object_id = ""
        self._original_text = ""
        self._box: BoardBox | None = None
        self._metrics: GridMetrics | None = None
        self._origin_offset = (0.0, 0.0)
        self._theme = DEFAULT_THEME
        self._editor = _BoundedPlainTextEdit(MAX_STICKY_TEXT, self)
        self._editor.setObjectName("ultraViewStickyNoteEditor")
        self._editor.setFrameShape(QFrame.NoFrame)
        self._editor.setPlaceholderText("输入便签内容")
        self._editor.commit_requested.connect(self.commit)
        self._editor.cancel_requested.connect(self.cancel)
        self._editor.ime_committed.connect(self._on_ime_committed)

    def editor(self) -> QPlainTextEdit:
        return self._editor

    def is_editing(self) -> bool:
        return self.isVisible() and bool(self._object_id)

    def object_id(self) -> str:
        return self._object_id

    def current_text(self) -> str:
        return self._editor.toPlainText()

    def apply_object(
        self,
        item: StickyObject,
        metrics: GridMetrics,
        *,
        origin_offset: tuple[float, float] = (0.0, 0.0),
        theme: str = DEFAULT_THEME,
    ) -> None:
        """Project one persisted Sticky without taking mutation ownership."""
        if not isinstance(item, StickyObject):
            raise TypeError("StickyNoteWidget requires a StickyObject")
        self._object_id = item.object_id
        self._original_text = item.text
        self._box = item.box
        self._metrics = metrics
        self._origin_offset = _origin(origin_offset)
        self._theme = str(theme or DEFAULT_THEME)
        self._editor.set_bounded_text(item.text)
        self._apply_palette(item)
        self.update_board_geometry(metrics, origin_offset=self._origin_offset)

    def update_board_geometry(
        self,
        metrics: GridMetrics | None = None,
        *,
        origin_offset: tuple[float, float] | None = None,
    ) -> None:
        if metrics is not None:
            self._metrics = metrics
        if origin_offset is not None:
            self._origin_offset = _origin(origin_offset)
        if self._box is None or self._metrics is None:
            return
        mapped = board_box_to_pixels(
            (self._box.x, self._box.y, self._box.width, self._box.height),
            self._metrics,
            origin_offset=self._origin_offset,
        )
        if mapped is None:
            self.hide()
            return
        x, y, width, height = mapped
        rect = QRect(round(x), round(y), max(1, round(width)), max(1, round(height)))
        self.setGeometry(rect)
        self._editor.setGeometry(self.contentsRect().adjusted(7, 7, -7, -7))
        self.show()

    def begin_edit(self) -> None:
        self._original_text = self._editor.toPlainText()
        self.show()
        self.raise_()
        self._editor.setFocus(Qt.OtherFocusReason)
        self._editor.selectAll()

    def commit(self) -> None:
        if self._object_id:
            text = self._editor.toPlainText()
            self._original_text = text
            self.text_committed.emit(self._object_id, text)

    def cancel(self) -> None:
        self._editor.set_bounded_text(self._original_text)
        object_id = self._object_id
        self.hide_edit()
        if object_id:
            self.edit_cancelled.emit(object_id)

    def hide_edit(self) -> None:
        self.hide()
        self._object_id = ""
        self._box = None
        self._metrics = None

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._editor.setGeometry(self.contentsRect().adjusted(7, 7, -7, -7))

    def _apply_palette(self, item: StickyObject) -> None:
        fill, border, foreground = sticky_colors(item.palette, self._theme)
        self.setStyleSheet(
            "QFrame#ultraViewStickyNote {"
            f"background: rgb({fill[0]}, {fill[1]}, {fill[2]});"
            f"border: 1px solid rgb({border[0]}, {border[1]}, {border[2]});"
            "border-radius: 8px;"
            "}"
            "QPlainTextEdit#ultraViewStickyNoteEditor {"
            "background: transparent; border: none;"
            f"color: rgb({foreground[0]}, {foreground[1]}, {foreground[2]});"
            "}"
        )
        font = QFont(_font_family("sans"))
        font.setPointSize(11 if item.font_size == "auto" else int(item.font_size))
        self._editor.setFont(font)

    def _on_ime_committed(self, text: str) -> None:
        if self._object_id:
            self.ime_committed.emit(self._object_id, text)


class BoardTextEditor(_BoundedPlainTextEdit):
    """Temporary focused text editor, designed to be a Board sibling widget."""

    text_committed = pyqtSignal(str, str)
    edit_cancelled = pyqtSignal(str)
    ime_text_committed = pyqtSignal(str, str)
    focus_lost = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(MAX_TEXT_TEXT, parent)
        self.setObjectName("ultraViewBoardTextEditor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setPlaceholderText("输入文字")
        self.hide()
        self._object_id = ""
        self._original_text = ""
        self._box: BoardBox | None = None
        self._metrics: GridMetrics | None = None
        self._origin_offset = (0.0, 0.0)
        self._theme = DEFAULT_THEME
        self._style: TextObject | None = None
        self.commit_requested.connect(self.commit)
        self.cancel_requested.connect(self.cancel)
        self.ime_committed.connect(self._on_ime_committed)

    def current_text(self) -> str:
        return self.toPlainText()

    def is_editing(self) -> bool:
        return self.isVisible() and self._box is not None

    def object_id(self) -> str:
        return self._object_id

    def begin_edit(
        self,
        *,
        object_id: str,
        box: BoardBox,
        text: str,
        metrics: GridMetrics,
        origin_offset: tuple[float, float] = (0.0, 0.0),
        theme: str = DEFAULT_THEME,
        style: TextObject | None = None,
    ) -> None:
        """Show and focus a temporary editor at a Board-coordinate rectangle."""
        self._object_id = str(object_id or "")
        self._original_text = str(text or "")[:MAX_TEXT_TEXT]
        self._box = box
        self._metrics = metrics
        self._origin_offset = _origin(origin_offset)
        self._theme = str(theme or DEFAULT_THEME)
        self.set_bounded_text(self._original_text)
        self._style = style if isinstance(style, TextObject) else None
        self._apply_style(self._style)
        self.update_board_geometry(metrics, origin_offset=self._origin_offset)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def apply_live_style(self, style: TextObject | None) -> None:
        """Update whole-box editor chrome without restarting the IME session."""
        self._style = style if isinstance(style, TextObject) else None
        self._apply_style(self._style)

    def update_board_geometry(
        self,
        metrics: GridMetrics | None = None,
        *,
        origin_offset: tuple[float, float] | None = None,
    ) -> None:
        if metrics is not None:
            self._metrics = metrics
        if origin_offset is not None:
            self._origin_offset = _origin(origin_offset)
        if self._box is None or self._metrics is None:
            return
        mapped = board_box_to_pixels(
            (self._box.x, self._box.y, self._box.width, self._box.height),
            self._metrics,
            origin_offset=self._origin_offset,
        )
        if mapped is None:
            self.hide()
            return
        x, y, width, height = mapped
        self.setGeometry(round(x), round(y), max(1, round(width)), max(1, round(height)))

    def commit(self) -> None:
        if not self.is_editing():
            return
        text = self.toPlainText()
        object_id = self._object_id
        self._original_text = text
        self._finish()
        self.text_committed.emit(object_id, text)

    def cancel(self) -> None:
        if not self.is_editing():
            return
        object_id = self._object_id
        self.set_bounded_text(self._original_text)
        self._finish()
        self.edit_cancelled.emit(object_id)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if self.is_editing() and not self.is_ime_composing():
            self.focus_lost.emit()

    def _finish(self) -> None:
        self._box = None
        self._metrics = None
        self._style = None
        self.clearFocus()
        self.hide()

    def _apply_style(self, style: TextObject | None) -> None:
        item = style if isinstance(style, TextObject) else None
        font = QFont(_font_family(item.font_role if item else "sans"))
        font.setPointSize(item.font_size if item else 14)
        font.setBold(bool(item.bold) if item else False)
        font.setItalic(bool(item.italic) if item else False)
        font.setUnderline(bool(item.underline) if item else False)
        self.setFont(font)
        foreground = ink_color(item.text_palette if item else "ink", self._theme)
        fill = "transparent"
        if item is not None and item.fill_palette:
            fill_rgb, _border, _foreground = sticky_colors(item.fill_palette, self._theme)
            fill = f"rgb({fill_rgb[0]}, {fill_rgb[1]}, {fill_rgb[2]})"
        self.setStyleSheet(
            "QPlainTextEdit#ultraViewBoardTextEditor {"
            f"color: rgb({foreground[0]}, {foreground[1]}, {foreground[2]});"
            f"background: {fill};"
            "border: 1px solid rgb(53, 99, 232); border-radius: 4px;"
            "padding: 6px;"
            "}"
        )

    def _on_ime_committed(self, text: str) -> None:
        if self.is_editing():
            self.ime_text_committed.emit(self._object_id, text)


def _origin(value: object) -> tuple[float, float]:
    try:
        x, y = value  # type: ignore[misc]
        return float(x), float(y)
    except (TypeError, ValueError):
        return 0.0, 0.0


@lru_cache(maxsize=3)
def _font_family(role: object) -> str:
    available = set(QFontDatabase().families())
    for candidate in font_candidates(role):
        if candidate in available:
            return candidate
    return QFont().defaultFamily()


def is_text_input_widget(widget: QWidget | None) -> bool:
    """True when *widget* is, or lives inside, a line/plain/rich text editor."""
    current = widget
    while current is not None:
        if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return True
        current = current.parentWidget()
    return False


__all__ = ["BoardTextEditor", "StickyNoteWidget", "is_text_input_widget"]
