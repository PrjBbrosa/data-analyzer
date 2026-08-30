"""Floating UltraView island chrome.

Global, Board, Status, Navigation, and Card-context islands. They project
local visual state only: the page owns workspace mutation and overlay
placement.
"""
from __future__ import annotations

import qtawesome as qta
from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome

from .chrome_common import (
    UV_MUTED,
    UV_PRESENTATION_ICON,
    _ElidedLabel,
    _InlineNameEditor,
    _icon_button,
    _repolish,
    _set_flag,
    _ultraview_icon_color,
)
from .floating_layout import (
    BOARD_ISLAND_MAX_WIDTH,
    DEFAULT_NAVIGATION_ISLAND_SIZE,
    GLOBAL_ISLAND_WIDTH,
    ISLAND_HEIGHT,
    STATUS_ISLAND_WIDTH,
)


class BoardIsland(QFrame):
    """Current Board identity plus compact menu/new actions.

    The Page supplies the selected board text and owns the actual menu.  This
    keeps confirmation, Board limits, reordering, and workspace mutation out
    of a presentation widget.
    """

    board_menu_requested = pyqtSignal()
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setMaximumWidth(BOARD_ISLAND_MAX_WIDTH)
        self.setProperty("surface", "island")
        self._board_id = ""
        self._rename_editor: _InlineNameEditor | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(2)
        self._name = _ElidedLabel("", self)
        self._name.setObjectName("ultraViewBoardIslandName")
        self._name.setMinimumWidth(48)
        self._name.installEventFilter(self)
        layout.addWidget(self._name, 1)
        self._menu = _icon_button(
            self,
            object_name="ultraViewBoardMenuButton",
            icon=Icons.chevron_down(UV_MUTED),
            tooltip="切换或管理 Board",
            accessible_name="切换或管理当前 Board",
        )
        self._menu.clicked.connect(self.board_menu_requested)
        layout.addWidget(self._menu, 0)
        self._add = _icon_button(
            self,
            object_name="ultraViewBoardAddButton",
            icon=Icons.ultraview_add(UV_MUTED),
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
        new_id = str(board_id or "")
        if self._rename_editor is not None and new_id != self._board_id:
            self._close_inline_rename()
        self._board_id = new_id
        self.setProperty("boardId", self._board_id)
        if self._rename_editor is None:
            self._name.set_full_text(str(name or ""))
        self.setAccessibleName(f"当前 Board：{name or ''}")
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self._name.fontMetrics()
        name_width = min(max(48, metrics.horizontalAdvance(self._name.full_text() or "Board") + 8), 148)
        return QSize(
            min(BOARD_ISLAND_MAX_WIDTH, 8 + name_width + 2 + 32 + 2 + 32 + 4),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, ISLAND_HEIGHT)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._add.setEnabled(bool(enabled))
        self._add.setToolTip(str(reason or "新建 Board"))

    def set_menu_open(self, opened: bool) -> None:
        """Project overlay-open chrome without making the chevron checkable."""
        active = bool(opened)
        _set_flag(self._menu, "panelOpen", active)
        self._menu.setIcon(Icons.chevron_down(_ultraview_icon_color(active=active)))

    def begin_inline_rename(self) -> None:
        """Overlay a line edit on the name; commit emits ``rename_requested``."""
        if self._rename_editor is not None:
            self._rename_editor.setFocus(Qt.OtherFocusReason)
            self._rename_editor.selectAll()
            return
        editor = _InlineNameEditor(self)
        editor.setObjectName("ultraViewBoardIslandRename")
        editor.setFont(self._name.font())
        editor.setText(self._name.full_text())
        editor.setGeometry(self._name.geometry())
        editor.committed.connect(self._on_inline_rename_committed)
        editor.cancelled.connect(self._on_inline_rename_cancelled)
        self._rename_editor = editor
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.OtherFocusReason)
        editor.selectAll()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._name and event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                self.begin_inline_rename()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._rename_editor is not None:
            self._rename_editor.setGeometry(self._name.geometry())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_F2:
            self.begin_inline_rename()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_inline_rename_committed(self, text: str) -> None:
        self._close_inline_rename()
        cleaned = str(text or "").strip()
        if cleaned:
            self.rename_requested.emit(cleaned)

    def _on_inline_rename_cancelled(self) -> None:
        self._close_inline_rename()

    def _close_inline_rename(self) -> None:
        editor = self._rename_editor
        self._rename_editor = None
        if editor is None:
            return
        editor.discard()
        editor.hide()
        editor.deleteLater()

class GlobalIsland(QFrame):
    """Right-top Board-wide display, export and presentation controls."""

    display_requested = pyqtSignal()
    export_requested = pyqtSignal()
    presentation_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGlobalIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._display = _icon_button(
            self,
            object_name="ultraViewGlobalDisplayButton",
            icon=Icons.ultraview_display(UV_MUTED),
            tooltip="显示标题和来源",
            accessible_name="显示标题和来源",
        )
        self._display.setCheckable(True)
        self._display.clicked.connect(self.display_requested)
        layout.addWidget(self._display, 0)
        self._export = _icon_button(
            self,
            object_name="ultraViewGlobalExportButton",
            icon=Icons.export(UV_MUTED),
            tooltip="复制或导出 Board",
            accessible_name="复制或导出 Board",
        )
        self._export.setCheckable(True)
        self._export.clicked.connect(self.export_requested)
        layout.addWidget(self._export, 0)
        self._presentation = _icon_button(
            self,
            object_name="ultraViewGlobalPresentationButton",
            icon=Icons.ultraview_presentation(UV_MUTED),
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
        self.updateGeometry()

    def set_active_panel(self, panel_id: str | None) -> None:
        key = str(panel_id or "")
        for name, button in (("display", self._display), ("export", self._export)):
            is_open = name == key
            blocked = button.blockSignals(True)
            button.setChecked(is_open)
            button.blockSignals(blocked)
            _set_flag(button, "panelOpen", is_open)
            _set_flag(button, "modeActive", False)
            _set_flag(button, "active", False)
        self._display.setIcon(
            Icons.ultraview_display(
                UV_PRESENTATION_ICON if key == "display" else UV_MUTED
            )
        )
        self._export.setIcon(
            Icons.export(UV_PRESENTATION_ICON if key == "export" else UV_MUTED)
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        visible = [
            button
            for button in (self._display, self._export, self._presentation)
            if not button.isHidden()
        ]
        count = max(1, len(visible))
        return QSize(
            min(GLOBAL_ISLAND_WIDTH, 8 + count * 32 + max(0, count - 1) * 2),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _on_presentation_toggled(self, checked: bool) -> None:
        self._sync_presentation(bool(checked))
        self.presentation_toggled.emit(bool(checked))

    def _sync_presentation(self, checked: bool) -> None:
        _set_flag(self._presentation, "active", checked)
        _set_flag(self, "presentation", checked)
        role = "presentationExit" if checked else "icon"
        if self._presentation.property("role") != role:
            self._presentation.setProperty("role", role)
            _repolish(self._presentation)
        self._presentation.setIcon(
            Icons.ultraview_presentation(
                UV_PRESENTATION_ICON if checked else UV_MUTED
            )
        )
        if not checked:
            self._presentation.setDown(False)
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
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._overview = _icon_button(
            self,
            object_name="ultraViewNavOverviewButton",
            icon=Icons.ultraview_overview(UV_MUTED),
            tooltip="查看整板概览",
            accessible_name="查看整板概览",
        )
        self._overview.clicked.connect(self.overview_requested)
        layout.addWidget(self._overview, 0)
        self._zoom_out = _icon_button(
            self,
            object_name="ultraViewNavZoomOutButton",
            icon=Icons.ultraview_zoom_out(UV_MUTED),
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
        zoom_font = QFont(self._zoom_label.font())
        zoom_font.setStyleHint(QFont.Monospace)
        zoom_font.setFixedPitch(True)
        self._zoom_label.setFont(zoom_font)
        layout.addWidget(self._zoom_label, 0)
        self._zoom_in = _icon_button(
            self,
            object_name="ultraViewNavZoomInButton",
            icon=Icons.ultraview_zoom_in(UV_MUTED),
            tooltip="放大画布",
            accessible_name="放大画布",
        )
        self._zoom_in.clicked.connect(self.zoom_in_requested)
        layout.addWidget(self._zoom_in, 0)
        self._fit = _icon_button(
            self,
            object_name="ultraViewNavFitButton",
            icon=Icons.ultraview_fit(UV_MUTED),
            tooltip="适应内容：只缩放画布，不改卡片；最高 300%",
            accessible_name="适应内容：只缩放画布，不改卡片；最高 300%",
        )
        self._fit.clicked.connect(self.zoom_fit_requested)
        layout.addWidget(self._fit, 0)
        self._reset = _icon_button(
            self,
            object_name="ultraViewNavResetButton",
            icon=Icons.ultraview_reset_zoom(UV_MUTED),
            tooltip="恢复 100% 缩放",
            accessible_name="恢复 100% 缩放",
        )
        self._reset.clicked.connect(self.zoom_reset_requested)
        layout.addWidget(self._reset, 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(*DEFAULT_NAVIGATION_ISLAND_SIZE)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

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
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(4)
        self._quickref = _icon_button(
            self,
            object_name="ultraViewStatusHelpButton",
            icon=Icons.ultraview_help(UV_MUTED),
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

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self._message.fontMetrics()
        text_width = min(280, max(96, metrics.horizontalAdvance(self._message.full_text()) + 12))
        return QSize(
            min(STATUS_ISLAND_WIDTH, 4 + 32 + 4 + text_width + 8),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(140, ISLAND_HEIGHT)

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
        _repolish(self._message)

class CardContextIsland(QFrame):
    """One selected-card action strip; it holds a ref, never a card QWidget."""

    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    copy_image_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    more_requested = pyqtSignal(str, str)
    rebind_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    fit_requested = pyqtSignal(str, str)

    _FIT_TOOLTIP = "按原图比例：只收紧当前卡，不移动邻卡"
    _FIT_DISABLED_TOOLTIP = "模板布局的尺寸由模板决定，切到自由网格后可用"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCardContextIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        self.setProperty("orphaned", "false")
        self._section = ""
        self._view_id = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._buttons: dict[str, QToolButton] = {}
        self._orphaned = False
        self._stale = False
        self._fit_enabled = False
        for action, object_name, icon, tooltip in (
            ("open", "ultraViewContextOpenButton", qta.icon("fa5s.external-link-alt", color=UV_MUTED), "打开原 View"),
            ("sync", "ultraViewContextSyncButton", qta.icon("fa5s.sync-alt", color=UV_MUTED), "同步到最新预览"),
            ("focus", "ultraViewContextFocusButton", qta.icon("fa5s.expand", color=UV_MUTED), "临时放大预览"),
            ("fit", "ultraViewContextFitButton", qta.icon("fa5s.vector-square", color=UV_MUTED), self._FIT_TOOLTIP),
            ("more", "ultraViewContextMoreButton", qta.icon("fa5s.ellipsis-v", color=UV_MUTED), "更多卡片操作"),
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
            if action == "sync":
                button.hide()
            self._buttons[action] = button
            layout.addWidget(button, 0)
        self.set_fit_enabled(False)
        self.hide()

    def ref(self) -> tuple[str, str] | None:
        if not self._section or not self._view_id:
            return None
        return self._section, self._view_id

    def button(self, action: str) -> QToolButton | None:
        return self._buttons.get(str(action))

    def show_for(
        self,
        section: str,
        view_id: str,
        *,
        orphaned: bool = False,
        stale: bool = False,
    ) -> None:
        self._section = str(section or "")
        self._view_id = str(view_id or "")
        self.setProperty("section", self._section)
        self.setProperty("viewId", self._view_id)
        self.set_orphaned(orphaned)
        self.set_stale(bool(stale) and not bool(orphaned))
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
        self._orphaned = is_orphaned
        _set_flag(self, "orphaned", is_orphaned)
        if is_orphaned:
            self._buttons["sync"].hide()

    def set_stale(self, stale: bool) -> None:
        self._stale = bool(stale)
        self._buttons["sync"].setVisible(self._stale and not self._orphaned)

    def set_fit_enabled(self, enabled: bool) -> None:
        self._fit_enabled = bool(enabled)
        button = self._buttons.get("fit")
        if button is None:
            return
        button.setEnabled(self._fit_enabled)
        tip = self._FIT_TOOLTIP if self._fit_enabled else self._FIT_DISABLED_TOOLTIP
        button.setToolTip(tip)
        button.setAccessibleName(tip)

    def make_overflow_menu(self, parent: QWidget | None = None) -> QMenu:
        menu = QMenu(parent or self)
        menu.setObjectName("ultraViewCardContextMoreMenu")
        # Every open of the "more" overflow re-creates this menu (callers may
        # also append extra actions/submenus before exec_-ing it); without
        # this it stays parented under the long-lived card-context widget
        # forever, leaking one QMenu (and its children) per open.
        menu.setAttribute(Qt.WA_DeleteOnClose)
        apply_rounded_menu_chrome(menu)
        for action, label in (
            ("copy", "复制本卡图像"),
            ("unplaced", "移到未放置"),
            ("rebind", "重新绑定"),
            ("remove", "从总览移除"),
        ):
            if action == "rebind" and not self._orphaned:
                continue
            item = menu.addAction(label)
            item.setProperty("overflowAction", action)
            item.triggered.connect(self._on_overflow_triggered)
        return menu

    def _on_overflow_triggered(self, _checked: bool = False) -> None:
        sender = self.sender()
        ref = self.ref()
        if sender is None or ref is None:
            return
        action = str(sender.property("overflowAction") or "")
        section, view_id = ref
        emitters = {
            "copy": self.copy_image_requested,
            "unplaced": self.move_to_unplaced_requested,
            "rebind": self.rebind_requested,
            "remove": self.remove_requested,
        }
        signal = emitters.get(action)
        if signal is not None:
            signal.emit(section, view_id)

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
            "sync": self.sync_requested,
            "focus": self.focus_requested,
            "fit": self.fit_requested,
            "more": self.more_requested,
        }
        signal = emitters.get(action)
        if signal is not None:
            signal.emit(section, view_id)
