"""Shared UltraView chrome presentation helpers.

Palette, polish/flag helpers, and the inline name widgets used by more than
one chrome family. Rail geometry, board-popover math, layout thumbs, and
canvas DPR/dot pitch stay with their owners.
"""
from __future__ import annotations

from PyQt5.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui_kit.ultraview_style import titanium_color


UV_CANVAS = QColor(titanium_color("canvas"))
UV_CANVAS_DEEP = QColor(titanium_color("canvas_deep"))
UV_DOT = QColor(44, 82, 93, 43)
UV_GRID = QColor(38, 74, 86, 26)
UV_GLOW_TEAL = QColor(31, 104, 128, 28)
UV_GLOW_SELECTED = QColor(66, 98, 255, 22)
UV_GLOW_MIST = QColor(36, 105, 124, 18)
UV_PAPER = QColor(titanium_color("surface_solid"))
UV_BRAND = QColor(titanium_color("brand"))
UV_BRAND_DEEP = QColor(titanium_color("brand_deep"))
UV_SELECTED = QColor(titanium_color("selected"))
UV_SELECTED_INK = QColor(titanium_color("selected_ink"))
UV_SELECTED_WASH = QColor(titanium_color("selected_wash"))
UV_DANGER = QColor(titanium_color("danger"))
UV_WASH = QColor(titanium_color("surface_tint"))
UV_LINE = QColor(50, 86, 97, 59)
UV_LINE_STRONG = QColor(42, 78, 89, 94)
UV_FROST = QColor(255, 255, 254, 118)
UV_INK = QColor(titanium_color("ink"))
UV_MUTED = QColor(titanium_color("muted"))
UV_PRESENTATION_ICON = UV_SELECTED
# Compatibility seam for the card module.  Keep only this import alias while
# widgets moves to the role palette; all paint decisions above use ``UV_*``.
ULTRAVIEW_MUTED = UV_MUTED

def _ultraview_icon_color(*, active: bool) -> QColor:
    """Rest icons stay muted; current-tool / open-panel icons pick up selected blue."""
    return QColor(UV_SELECTED if active else UV_MUTED)

def _repolish(widget: QWidget) -> None:
    """Refresh QSS after a dynamic-property state change."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _set_flag(widget: QWidget, name: str, enabled: bool) -> None:
    """Use string properties so QSS attribute selectors are stable in PyQt5."""
    value = "true" if enabled else "false"
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    _repolish(widget)


def _icon_button(
    parent: QWidget,
    *,
    object_name: str,
    icon: QIcon,
    tooltip: str,
    accessible_name: str,
    size: int = 32,
    icon_size: int = 18,
) -> QToolButton:
    """Create one consistent, keyboard-accessible icon-only control."""
    button = QToolButton(parent)
    button.setObjectName(object_name)
    button.setIcon(icon)
    button.setIconSize(QSize(icon_size, icon_size))
    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    button.setAutoRaise(True)
    button.setAutoFillBackground(False)
    button.setAttribute(Qt.WA_StyledBackground, True)
    button.setFixedSize(size, size)
    button.setFocusPolicy(Qt.TabFocus)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    button.setProperty("role", "icon")
    button.setProperty("chrome", "ultraview")
    button.setProperty("active", "false")
    button.setProperty("modeActive", "false")
    button.setProperty("panelOpen", "false")
    button.setProperty("primaryFill", "false")
    return button

class _ElidedLabel(QLabel):
    """A label which retains full text for accessible name and tooltip use."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self._apply_text()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_text()

    def _apply_text(self) -> None:
        metrics = self.fontMetrics()
        available = max(0, self.width())
        self.setText(metrics.elidedText(self._full_text, Qt.ElideRight, available))
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)


class _InlineNameEditor(QLineEdit):
    """Transient in-place name field. Enter/blur commit; Esc cancel."""

    committed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrame(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._settled = False
        self._armed = False
        self.returnPressed.connect(self._emit_committed)
        QTimer.singleShot(0, self._arm)

    def _arm(self) -> None:
        self._armed = True

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._emit_cancelled()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if self._armed:
            self._emit_committed()

    def _emit_committed(self) -> None:
        if self._settled:
            return
        self._settled = True
        self.committed.emit(self.text())

    def _emit_cancelled(self) -> None:
        if self._settled:
            return
        self._settled = True
        self.cancelled.emit()

    def discard(self) -> None:
        """Suppress commit/cancel while the host tears the editor down."""
        self._settled = True
