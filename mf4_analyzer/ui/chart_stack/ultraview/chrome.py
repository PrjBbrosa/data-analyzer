"""Lightweight floating presentation widgets for the UltraView canvas.

The widgets in this module deliberately project only local visual state.  They
never receive an ``UltraViewBoardState`` and never mutate the workspace: the
page owns the active panel and translates these typed Qt signals into its
existing coordinator intents.

The module also intentionally does not position the islands relative to cards
or the minimap.  ``floating_layout.py`` / ``UltraViewPage`` own that geometry;
``CanvasHost`` merely provides a stable sibling-overlay host.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from PyQt5.QtCore import QEvent, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui.ultraview_state import ULTRAVIEW_REF_MIME, parse_ref_payload


PANEL_LIBRARY = "library"
PANEL_LAYOUT = "layout"
PANEL_FILTER = "filter"
PANEL_UNPLACED = "unplaced"


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
) -> QToolButton:
    """Create one consistent, keyboard-accessible icon-only control."""
    button = QToolButton(parent)
    button.setObjectName(object_name)
    button.setIcon(icon)
    button.setIconSize(QSize(18, 18))
    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    button.setAutoRaise(True)
    button.setFixedSize(32, 32)
    button.setFocusPolicy(Qt.TabFocus)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    button.setProperty("role", "icon")
    button.setProperty("chrome", "ultraview")
    button.setProperty("active", "false")
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


class CanvasHost(QFrame):
    """A canvas content host with non-layout-participating sibling overlays.

    ``set_canvas_widget`` fills the complete host.  Registered overlays are
    direct children of this host and never enter a layout, so opening a library
    or a popover cannot reflow or resize the board viewport.  The page remains
    responsible for deciding which panel is active and where it should sit.
    """

    overlay_opened = pyqtSignal(str)
    overlay_closed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCanvasHost")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("surface", "canvas")
        self._canvas: QWidget | None = None
        self._overlays: dict[str, QWidget] = {}
        self._overlay_triggers: dict[str, QWidget | None] = {}
        self._overlay_close_on_canvas: dict[str, bool] = {}
        self._active_overlay: str | None = None
        self._dot_tile: QPixmap | None = None

    def canvas_widget(self) -> QWidget | None:
        return self._canvas

    def set_canvas_widget(self, widget: QWidget) -> None:
        """Install the one board content widget below every overlay."""
        if widget is self._canvas:
            return
        if self._canvas is not None:
            self._canvas.removeEventFilter(self)
            self._canvas.hide()
        widget.setParent(self)
        widget.installEventFilter(self)
        widget.show()
        self._canvas = widget
        widget.setGeometry(self.contentsRect())
        widget.lower()

    def register_overlay(
        self,
        overlay_id: str,
        widget: QWidget,
        *,
        trigger: QWidget | None = None,
        close_on_canvas_click: bool = True,
    ) -> None:
        """Register a stable overlay widget without taking ownership of state."""
        key = str(overlay_id)
        if not key:
            raise ValueError("overlay_id must not be empty")
        existing = self._overlays.get(key)
        if existing is not None and existing is not widget:
            raise ValueError(f"overlay already registered: {key}")
        widget.setParent(self)
        widget.setProperty("floatingOverlay", "true")
        widget.setProperty("overlayId", key)
        widget.hide()
        self._overlays[key] = widget
        self._overlay_triggers[key] = trigger
        self._overlay_close_on_canvas[key] = bool(close_on_canvas_click)

    def overlay(self, overlay_id: str) -> QWidget | None:
        return self._overlays.get(str(overlay_id))

    def active_overlay(self) -> str | None:
        return self._active_overlay

    def open_overlay(
        self,
        overlay_id: str,
        rect: QRect | None = None,
        *,
        focus: bool = False,
    ) -> bool:
        """Show one registered overlay, closing any currently active sibling."""
        key = str(overlay_id)
        widget = self._overlays.get(key)
        if widget is None:
            return False
        if self._active_overlay is not None and self._active_overlay != key:
            self.close_active_overlay(restore_focus=False)
        if rect is not None:
            self.set_overlay_geometry(key, rect)
        elif widget.width() <= 0 or widget.height() <= 0:
            hint = widget.sizeHint()
            self.set_overlay_geometry(key, QRect(12, 12, hint.width(), hint.height()))
        self._active_overlay = key
        widget.show()
        widget.raise_()
        _set_flag(widget, "active", True)
        if focus:
            self._focus_first_control(widget)
        self.overlay_opened.emit(key)
        return True

    def close_overlay(self, overlay_id: str, *, restore_focus: bool = True) -> bool:
        key = str(overlay_id)
        widget = self._overlays.get(key)
        if widget is None or self._active_overlay != key:
            return False
        widget.hide()
        _set_flag(widget, "active", False)
        self._active_overlay = None
        self.overlay_closed.emit(key)
        if restore_focus:
            trigger = self._overlay_triggers.get(key)
            if trigger is not None and trigger.isVisible() and trigger.isEnabled():
                trigger.setFocus(Qt.OtherFocusReason)
        return True

    def close_active_overlay(self, *, restore_focus: bool = True) -> bool:
        key = self._active_overlay
        return self.close_overlay(key, restore_focus=restore_focus) if key is not None else False

    def set_overlay_geometry(self, overlay_id: str, rect: QRect) -> QRect:
        """Clamp an externally calculated overlay rectangle into this host."""
        widget = self._overlays.get(str(overlay_id))
        if widget is None:
            raise KeyError(str(overlay_id))
        bounds = self.contentsRect()
        width = max(0, min(int(rect.width()), bounds.width()))
        height = max(0, min(int(rect.height()), bounds.height()))
        max_x = bounds.x() + max(0, bounds.width() - width)
        max_y = bounds.y() + max(0, bounds.height() - height)
        x = min(max(int(rect.x()), bounds.x()), max_x)
        y = min(max(int(rect.y()), bounds.y()), max_y)
        clamped = QRect(x, y, width, height)
        widget.setGeometry(clamped)
        return clamped

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._canvas is not None:
            self._canvas.setGeometry(self.contentsRect())
        for key, overlay in self._overlays.items():
            if overlay.isVisible():
                self.set_overlay_geometry(key, overlay.geometry())

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the one memorable Miro cue once beneath all Qt children."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#e9eff3"))
        if self._dot_tile is None:
            tile = QPixmap(22, 22)
            tile.fill(Qt.transparent)
            dots = QPainter(tile)
            dots.setRenderHint(QPainter.Antialiasing, True)
            dots.setPen(Qt.NoPen)
            dots.setBrush(QColor(60, 82, 104, 42))
            dots.drawEllipse(10, 10, 2, 2)
            dots.end()
            self._dot_tile = tile
        painter.drawTiledPixmap(self.rect(), self._dot_tile)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self.close_active_overlay():
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._close_from_canvas_click()
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._canvas
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            self._close_from_canvas_click()
        return super().eventFilter(watched, event)

    def _close_from_canvas_click(self) -> None:
        key = self._active_overlay
        if key is not None and self._overlay_close_on_canvas.get(key, True):
            self.close_active_overlay()

    @staticmethod
    def _focus_first_control(widget: QWidget) -> None:
        for child in widget.findChildren(QWidget):
            if child.focusPolicy() != Qt.NoFocus and child.isVisible() and child.isEnabled():
                child.setFocus(Qt.OtherFocusReason)
                return
        if widget.focusPolicy() != Qt.NoFocus:
            widget.setFocus(Qt.OtherFocusReason)


class ToolRail(QFrame):
    """The fixed 48 px left rail; Page owns which requested panel opens."""

    panel_requested = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str)

    _PANEL_SPECS: tuple[tuple[str, str, str, Callable[[], QIcon]], ...] = (
        (PANEL_LIBRARY, "Library", "打开 View 库", Icons.ultraview_library),
        (PANEL_LAYOUT, "Layout", "选择 Board 布局", Icons.ultraview_layout),
        (PANEL_FILTER, "Filter", "筛选可对比的 View", Icons.ultraview_filter),
        (PANEL_UNPLACED, "Unplaced", "查看未放置的 View", Icons.ultraview_unplaced),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewToolRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setProperty("surface", "island")
        self.setFixedWidth(48)
        self._buttons: dict[str, QToolButton] = {}
        self._badges: dict[str, QLabel] = {}
        self._active_panel: str | None = None
        self._filter_active = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)
        for index, (panel_id, short_name, tooltip, icon_factory) in enumerate(self._PANEL_SPECS):
            if index == 3:
                divider = QFrame(self)
                divider.setObjectName("ultraViewToolRailDivider")
                divider.setFrameShape(QFrame.HLine)
                divider.setFixedHeight(1)
                root.addWidget(divider, 0)
            button = _icon_button(
                self,
                object_name=f"ultraViewRail{short_name}Button",
                icon=icon_factory(),
                tooltip=tooltip,
                accessible_name=tooltip,
            )
            button.setProperty("panel", panel_id)
            button.clicked.connect(self._on_panel_clicked)
            self._buttons[panel_id] = button
            root.addWidget(button, 0, Qt.AlignHCenter)
            badge = QLabel(self)
            badge.setObjectName(f"ultraViewRail{short_name}Badge")
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            badge.setAlignment(Qt.AlignCenter)
            badge.setMinimumSize(14, 14)
            badge.setProperty("role", "badge")
            badge.hide()
            self._badges[panel_id] = badge
        root.addStretch(1)
        self.set_active_panel(None)

    def panel_button(self, panel_id: str) -> QToolButton | None:
        return self._buttons.get(str(panel_id))

    def active_panel(self) -> str | None:
        return self._active_panel

    def set_active_panel(self, panel_id: str | None) -> None:
        key = str(panel_id) if panel_id is not None else None
        if key not in self._buttons:
            key = None
        self._active_panel = key
        self._sync_button_states()

    def set_filter_active(self, active: bool) -> None:
        """Keep a non-``all`` compare filter discoverable after closing it."""
        self._filter_active = bool(active)
        self._sync_button_states()

    def _sync_button_states(self) -> None:
        for candidate, button in self._buttons.items():
            is_active = candidate == self._active_panel or (
                candidate == PANEL_FILTER and self._filter_active
            )
            _set_flag(button, "active", is_active)
            button.setChecked(candidate == self._active_panel)

    def set_badge(self, panel_id: str, count: int | None) -> None:
        """Set an exact count badge; zero/None intentionally shows no badge."""
        key = str(panel_id)
        badge = self._badges.get(key)
        if badge is None:
            raise KeyError(key)
        try:
            value = max(0, int(count or 0))
        except (TypeError, ValueError):
            value = 0
        badge.setText(str(value))
        badge.setToolTip(f"{value} 个未放置 View" if value else "")
        badge.setAccessibleName(f"未放置 View：{value}" if value else "")
        badge.setVisible(value > 0)
        self._position_badges()

    def badge_text(self, panel_id: str) -> str:
        badge = self._badges.get(str(panel_id))
        return badge.text() if badge is not None else ""

    def set_panel_attention(self, panel_id: str, attention: bool) -> None:
        button = self._buttons.get(str(panel_id))
        if button is None:
            raise KeyError(str(panel_id))
        _set_flag(button, "attention", bool(attention))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_badges()

    def _position_badges(self) -> None:
        for panel_id, badge in self._badges.items():
            button = self._buttons[panel_id]
            if not badge.isHidden():
                x = button.x() + button.width() - badge.width() // 2 - 1
                y = button.y() - badge.height() // 3
                badge.move(x, max(0, y))
                badge.raise_()

    def _on_panel_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        panel_id = str(button.property("panel") or "")
        if panel_id in self._buttons:
            self.panel_requested.emit(panel_id)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(ULTRAVIEW_REF_MIME):
            self.set_panel_attention(PANEL_UNPLACED, True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        try:
            raw = bytes(event.mimeData().data(ULTRAVIEW_REF_MIME)).decode("utf-8")
            ref = parse_ref_payload(json.loads(raw))
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            ref = None
        if ref is None:
            event.ignore()
            return
        self.ref_dropped.emit(ref.section, ref.view_id)
        event.acceptProposedAction()


class BoardIsland(QFrame):
    """Current Board identity plus compact menu/new actions.

    The Page supplies the selected board text and owns the actual menu.  This
    keeps confirmation, Board limits, reordering, and workspace mutation out
    of a presentation widget.
    """

    board_menu_requested = pyqtSignal()
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(40)
        self.setMaximumWidth(240)
        self.setProperty("surface", "island")
        self._board_id = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(2)
        self._name = _ElidedLabel("", self)
        self._name.setObjectName("ultraViewBoardIslandName")
        self._name.setMinimumWidth(48)
        layout.addWidget(self._name, 1)
        self._menu = _icon_button(
            self,
            object_name="ultraViewBoardMenuButton",
            icon=Icons.chevron_down(),
            tooltip="切换或管理 Board",
            accessible_name="切换或管理当前 Board",
        )
        self._menu.clicked.connect(self.board_menu_requested)
        layout.addWidget(self._menu, 0)
        self._add = _icon_button(
            self,
            object_name="ultraViewBoardAddButton",
            icon=Icons.ultraview_add(),
            tooltip="新建 Board",
            accessible_name="新建 Board",
        )
        self._add.clicked.connect(self.create_requested)
        layout.addWidget(self._add, 0)

    def board_id(self) -> str:
        return self._board_id

    def board_name_label(self) -> QLabel:
        return self._name

    def menu_button(self) -> QToolButton:
        return self._menu

    def add_button(self) -> QToolButton:
        return self._add

    def set_current_board(self, board_id: str, name: str) -> None:
        self._board_id = str(board_id or "")
        self.setProperty("boardId", self._board_id)
        self._name.set_full_text(str(name or ""))
        self.setAccessibleName(f"当前 Board：{name or ''}")

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._add.setEnabled(bool(enabled))
        self._add.setToolTip(str(reason or "新建 Board"))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_F2:
            self.rename_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.rename_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class GlobalIsland(QFrame):
    """Right-top Board-wide display, export and presentation controls."""

    display_requested = pyqtSignal()
    export_requested = pyqtSignal()
    presentation_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGlobalIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._display = _icon_button(
            self,
            object_name="ultraViewGlobalDisplayButton",
            icon=Icons.ultraview_display(),
            tooltip="显示标题和来源",
            accessible_name="显示标题和来源",
        )
        self._display.clicked.connect(self.display_requested)
        layout.addWidget(self._display, 0)
        self._export = _icon_button(
            self,
            object_name="ultraViewGlobalExportButton",
            icon=Icons.export(),
            tooltip="复制或导出 Board",
            accessible_name="复制或导出 Board",
        )
        self._export.clicked.connect(self.export_requested)
        layout.addWidget(self._export, 0)
        self._presentation = _icon_button(
            self,
            object_name="ultraViewGlobalPresentationButton",
            icon=Icons.ultraview_presentation(),
            tooltip="进入演示",
            accessible_name="进入演示",
        )
        self._presentation.setCheckable(True)
        self._presentation.toggled.connect(self._on_presentation_toggled)
        layout.addWidget(self._presentation, 0)

    def display_button(self) -> QToolButton:
        return self._display

    def export_button(self) -> QToolButton:
        return self._export

    def presentation_button(self) -> QToolButton:
        return self._presentation

    def set_presentation_checked(self, checked: bool) -> None:
        blocked = self._presentation.blockSignals(True)
        self._presentation.setChecked(bool(checked))
        self._presentation.blockSignals(blocked)
        self._sync_presentation(bool(checked))

    def set_edit_visible(self, visible: bool) -> None:
        self._display.setVisible(bool(visible))
        self._export.setVisible(bool(visible))

    def _on_presentation_toggled(self, checked: bool) -> None:
        self._sync_presentation(bool(checked))
        self.presentation_toggled.emit(bool(checked))

    def _sync_presentation(self, checked: bool) -> None:
        _set_flag(self._presentation, "active", checked)
        self._presentation.setToolTip("退出演示" if checked else "进入演示")
        self._presentation.setAccessibleName("退出演示" if checked else "进入演示")


class NavigationIsland(QFrame):
    """Right-bottom navigation actions; zoom state remains page-owned."""

    overview_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_fit_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewNavigationIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._overview = _icon_button(
            self,
            object_name="ultraViewNavOverviewButton",
            icon=Icons.ultraview_overview(),
            tooltip="查看整板概览",
            accessible_name="查看整板概览",
        )
        self._overview.clicked.connect(self.overview_requested)
        layout.addWidget(self._overview, 0)
        self._zoom_out = _icon_button(
            self,
            object_name="ultraViewNavZoomOutButton",
            icon=Icons.ultraview_zoom_out(),
            tooltip="缩小画布",
            accessible_name="缩小画布",
        )
        self._zoom_out.clicked.connect(self.zoom_out_requested)
        layout.addWidget(self._zoom_out, 0)
        self._zoom_label = QLabel("100%", self)
        self._zoom_label.setObjectName("ultraViewNavZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setMinimumWidth(42)
        self._zoom_label.setAccessibleName("当前画布缩放：100%")
        layout.addWidget(self._zoom_label, 0)
        self._zoom_in = _icon_button(
            self,
            object_name="ultraViewNavZoomInButton",
            icon=Icons.ultraview_zoom_in(),
            tooltip="放大画布",
            accessible_name="放大画布",
        )
        self._zoom_in.clicked.connect(self.zoom_in_requested)
        layout.addWidget(self._zoom_in, 0)
        self._fit = _icon_button(
            self,
            object_name="ultraViewNavFitButton",
            icon=Icons.ultraview_fit(),
            tooltip="画布适应视口",
            accessible_name="画布适应视口",
        )
        self._fit.clicked.connect(self.zoom_fit_requested)
        layout.addWidget(self._fit, 0)
        self._reset = _icon_button(
            self,
            object_name="ultraViewNavResetButton",
            icon=Icons.ultraview_reset_zoom(),
            tooltip="恢复 100% 缩放",
            accessible_name="恢复 100% 缩放",
        )
        self._reset.clicked.connect(self.zoom_reset_requested)
        layout.addWidget(self._reset, 0)

    def zoom_label(self) -> QLabel:
        return self._zoom_label

    def button(self, action: str) -> QToolButton | None:
        return {
            "overview": self._overview,
            "zoom_out": self._zoom_out,
            "zoom_in": self._zoom_in,
            "fit": self._fit,
            "reset": self._reset,
        }.get(str(action))

    def set_zoom_percent(self, percent: int) -> None:
        value = int(percent)
        self._zoom_label.setText(f"{value}%")
        self._zoom_label.setAccessibleName(f"当前画布缩放：{value}%")
        self._zoom_label.setToolTip(f"当前画布缩放：{value}%")


class StatusIsland(QFrame):
    """Compact read-only / help status without a permanent full-width bar."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewStatusIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(4)
        self._quickref = _icon_button(
            self,
            object_name="ultraViewStatusHelpButton",
            icon=Icons.ultraview_help(),
            tooltip="操作速查",
            accessible_name="打开 UltraView 操作速查",
        )
        self._quickref.clicked.connect(self.quickref_requested)
        layout.addWidget(self._quickref, 0)
        self._message = _ElidedLabel("只读预览 · 不计算", self)
        self._message.setObjectName("ultraViewStatusMessage")
        self._message.setMinimumWidth(96)
        layout.addWidget(self._message, 1)
        self.set_status("只读预览 · 不计算")

    def help_button(self) -> QToolButton:
        return self._quickref

    def message_label(self) -> QLabel:
        return self._message

    def set_status(self, text: str, *, level: str = "info") -> None:
        value = str(text or "")
        self._message.set_full_text(value)
        self.setToolTip(value)
        self.setAccessibleName(value)
        self.setProperty("statusLevel", str(level or "info"))
        _repolish(self)


class CardContextIsland(QFrame):
    """One selected-card action strip; it holds a ref, never a card QWidget."""

    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    copy_image_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    more_requested = pyqtSignal(str, str)
    rebind_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCardContextIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setProperty("surface", "island")
        self.setProperty("orphaned", "false")
        self._section = ""
        self._view_id = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._buttons: dict[str, QToolButton] = {}
        for action, object_name, icon, tooltip in (
            ("open", "ultraViewContextOpenButton", Icons.ultraview_open_source(), "打开原 View"),
            ("focus", "ultraViewContextFocusButton", Icons.expand_focus(), "临时放大预览"),
            ("copy", "ultraViewContextCopyButton", Icons.copy_image(), "复制本卡图像"),
            ("unplaced", "ultraViewContextUnplacedButton", Icons.ultraview_move_to_tray(), "移到未放置区"),
            ("more", "ultraViewContextMoreButton", Icons.menu(), "更多卡片操作"),
            ("rebind", "ultraViewContextRebindButton", Icons.rebuild_time(), "重新绑定孤儿 View"),
            ("remove", "ultraViewContextRemoveButton", Icons.close_file(), "从总览移除"),
        ):
            button = _icon_button(
                self,
                object_name=object_name,
                icon=icon,
                tooltip=tooltip,
                accessible_name=tooltip,
            )
            button.setProperty("contextAction", action)
            button.clicked.connect(self._on_action_clicked)
            if action in {"rebind", "remove"}:
                button.hide()
            self._buttons[action] = button
            layout.addWidget(button, 0)
        self.hide()

    def ref(self) -> tuple[str, str] | None:
        if not self._section or not self._view_id:
            return None
        return self._section, self._view_id

    def button(self, action: str) -> QToolButton | None:
        return self._buttons.get(str(action))

    def show_for(self, section: str, view_id: str, *, orphaned: bool = False) -> None:
        self._section = str(section or "")
        self._view_id = str(view_id or "")
        self.setProperty("section", self._section)
        self.setProperty("viewId", self._view_id)
        self.set_orphaned(orphaned)
        if self.ref() is None:
            self.hide()
            return
        self.setAccessibleName(f"当前卡片操作：{self._section} {self._view_id}")
        self.show()
        self.raise_()

    def clear_ref(self) -> None:
        self._section = ""
        self._view_id = ""
        self.setProperty("section", "")
        self.setProperty("viewId", "")
        self.hide()

    def set_orphaned(self, orphaned: bool) -> None:
        is_orphaned = bool(orphaned)
        _set_flag(self, "orphaned", is_orphaned)
        self._buttons["rebind"].setVisible(is_orphaned)
        self._buttons["remove"].setVisible(is_orphaned)

    def _on_action_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        ref = self.ref()
        if ref is None:
            return
        action = str(sender.property("contextAction") or "")
        section, view_id = ref
        emitters = {
            "open": self.open_source_requested,
            "focus": self.focus_requested,
            "copy": self.copy_image_requested,
            "unplaced": self.move_to_unplaced_requested,
            "more": self.more_requested,
            "rebind": self.rebind_requested,
            "remove": self.remove_requested,
        }
        signal = emitters.get(action)
        if signal is not None:
            signal.emit(section, view_id)
