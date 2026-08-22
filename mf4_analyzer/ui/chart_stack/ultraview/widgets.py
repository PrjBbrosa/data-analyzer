"""UltraView page widgets façade plus residual switcher/toolbar/hint/compare.

Class families live in sibling modules. Consumers keep importing names from
this module; type identity is the implementation class. HintBar, BoardSwitcher,
BoardToolbar, and CompareRail remain implemented here.
"""
from __future__ import annotations

from typing import Any, Sequence

import qtawesome as qta
from PyQt5.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    COMPARE_FILTERS,
    LAYOUT_SLOTS,
    ULTRAVIEW_PAGE_OBJECT_NAME,
)
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome

from .chrome import ULTRAVIEW_MUTED
from .feedback import (
    FEEDBACK_DISPLACED_OFFSCREEN,
    FEEDBACK_NO_LEGAL_LAYOUT,
    FEEDBACK_OUT_OF_GRID,
    FEEDBACK_SEARCH_BUDGET,
)
from .._helpers import ULTRAVIEW_HINT_BAR_HEIGHT

from .widgets_common import (
    STATUS_LABELS_ZH,
    _effective_device_pixel_ratio,
    extract_ref_strings,
    make_ref_mime,
)
from .card_widgets import (
    DIMMED_OPACITY,
    DRAG_DIM_OPACITY,
    MISSING_CARD_COPY,
    ORPHANED_CARD_COPY,
    REPLACE_HOVER_MS,
    STALE_CARD_COPY,
    TYPE_CHIP_ICON_ONLY_WIDTH,
    CardViewModel,
    FreeGridCard,
    ReplaceHoverController,
    UltraViewCard,
    preview_image,
)
from .library_widgets import (
    LIBRARY_DEFAULT_WIDTH,
    LIBRARY_HEAD_HEIGHT,
    LIBRARY_MAX_WIDTH,
    LIBRARY_MODE_GROUPS,
    LIBRARY_OVERLAY_HEIGHT,
    LIBRARY_OVERLAY_MIN_HEIGHT,
    LIBRARY_ROW_ACTION_SIZE,
    LIBRARY_ROW_DOT_INSET,
    LIBRARY_ROW_HEIGHT,
    LIBRARY_SEARCH_HEIGHT,
    LIBRARY_SECTION_GAP,
    LIBRARY_SECTION_HEAD_HEIGHT,
    LIBRARY_SECTION_ROW_GAP,
    LIBRARY_SELECTED_ROW_GUTTER,
    TRAY_BODY_MAX_HEIGHT,
    TRAY_ITEM_MIN_HEIGHT,
    UNPLACED_OVERLAY_MIN_HEIGHT,
    UNPLACED_OVERLAY_VISIBLE_ROWS,
    UNPLACED_OVERLAY_WIDTH,
    LibraryRow,
    LibraryRowWidget,
    TrayItem,
    UnplacedTray,
    ViewLibraryPanel,
    coerce_library_row,
)
from .template_board import BoardGrid, EmptySlotWidget
from .board_aux_widgets import (
    BoardOverview,
    BoardScrollArea,
    FocusLayer,
    FreeGridMinimap,
)
from .free_grid_board import FreeGridBoard, _reject_feedback

LAYOUT_LABELS_ZH = {
    "split_horizontal": "左右双图",
    "split_vertical": "上下双图",
    "grid_2x2": "2 × 2",
    "hero_left_4": "左主图 + 3 辅图",
    "hero_top_4": "上主图 + 3 辅图",
    "grid_3x2": "3 × 2",
    "grid_3x3": "3 × 3",
    "grid_4x3": "4 × 3",
}

COMPARE_FILTER_LABELS_ZH = {
    COMPARE_FILTER_ALL: "全部",
    "time": "时间轴",
    "frequency": "频率轴",
    "time_freq": "时频轴",
    "order": "阶次轴",
}


class UltraViewHintBar(QFrame):
    """Status-bar hint host. ChartStack can later take this widget."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartHintBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ULTRAVIEW_HINT_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        # Equal 3px vertical padding keeps a 22px inner slot so the styled
        # ``?`` and 11px copy stay centered and unclipped in a 28px strip.
        layout.setContentsMargins(10, 3, 8, 3)
        layout.setSpacing(4)
        self._quickref = QToolButton(self)
        self._quickref.setObjectName("chartHintQuickrefButton")
        self._quickref.setText("?")
        self._quickref.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._quickref.setAutoRaise(True)
        self._quickref.setCursor(Qt.PointingHandCursor)
        self._quickref.setToolTip("操作速查")
        self._quickref.clicked.connect(self.quickref_requested.emit)
        self._context = QLabel("拖卡片移动 · 左键框选 · 右键拖动画布 · Ctrl+滚轮缩放", self)
        self._context.setObjectName("chartHintContext")
        self._context.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._context.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._context.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        self._discovery = QLabel("UltraView 不计算", self)
        self._discovery.setObjectName("chartHintDiscovery")
        self._discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._discovery.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._discovery.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        layout.addWidget(self._quickref, 0, Qt.AlignVCenter)
        layout.addWidget(self._context, 1, Qt.AlignVCenter)
        layout.addWidget(self._discovery, 0, Qt.AlignVCenter)


class BoardSwitcher(QFrame):
    """Presentation-only multi-Board selector.

    The switcher receives immutable-ish Board DTOs from the Page and emits
    typed intents.  It intentionally never mutates a workspace: that keeps
    project state, confirmation policy, and the 20-Board creation limit in the
    state/coordinator owner rather than in a QWidget callback.
    """

    create_requested = pyqtSignal()
    duplicate_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str)
    reorder_requested = pyqtSignal(str, int)
    board_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardSwitcher")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._board_ids: list[str] = []
        self._tab = QTabBar(self)
        self._tab.setObjectName("ultraViewBoardTabs")
        self._tab.setDocumentMode(True)
        self._tab.setUsesScrollButtons(True)
        self._tab.setElideMode(Qt.ElideRight)
        self._tab.setMovable(True)
        self._tab.setExpanding(False)
        self._tab.setTabsClosable(False)
        self._tab.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tab.currentChanged.connect(self._on_current_changed)
        self._tab.tabMoved.connect(self._on_tab_moved)
        self._tab.customContextMenuRequested.connect(self._on_context_menu)
        self._reordering = False
        self._pending_boards: tuple[tuple[Any, ...], str | None] | None = None
        self._flush_boards_timer = QTimer(self)
        self._flush_boards_timer.setSingleShot(True)
        self._flush_boards_timer.timeout.connect(self._end_reordering)

        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewBoardAddButton")
        self._add.setText("+")
        self._add.setToolTip("新建 Board")
        self._add.setAutoRaise(True)
        self._add.clicked.connect(self.create_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 2)
        layout.setSpacing(4)
        layout.addWidget(self._tab, 1)
        layout.addWidget(self._add, 0)

    def tab_bar(self) -> QTabBar:
        return self._tab

    def add_button(self) -> QToolButton:
        return self._add

    def current_board_id(self) -> str | None:
        index = self._tab.currentIndex()
        if 0 <= index < len(self._board_ids):
            return self._board_ids[index]
        return None

    def board_ids(self) -> tuple[str, ...]:
        return tuple(self._board_ids)

    def set_boards(self, boards: Sequence[Any], active_board_id: str | None) -> None:
        """Project the supplied workspace without feeding signals back to it."""
        if self._reordering:
            self._pending_boards = (tuple(boards), active_board_id)
            if not self._flush_boards_timer.isActive():
                self._flush_boards_timer.start(0)
            return
        self._apply_boards(boards, active_board_id)

    def _end_reordering(self) -> None:
        self._reordering = False
        self._flush_pending_boards()

    def _flush_pending_boards(self) -> None:
        pending = self._pending_boards
        self._pending_boards = None
        if pending is None:
            return
        boards, active_board_id = pending
        self._apply_boards(boards, active_board_id)

    def _apply_boards(self, boards: Sequence[Any], active_board_id: str | None) -> None:
        parsed: list[tuple[str, str]] = []
        for index, board in enumerate(boards):
            board_id = str(getattr(board, "board_id", "") or "")
            if not board_id:
                continue
            name = str(getattr(board, "name", "") or f"Board {index + 1}")
            parsed.append((board_id, name))
        prior = self._tab.blockSignals(True)
        try:
            while self._tab.count():
                self._tab.removeTab(0)
            self._board_ids = [board_id for board_id, _name in parsed]
            for board_id, name in parsed:
                tab_index = self._tab.addTab(name)
                self._tab.setTabToolTip(tab_index, name)
                self._tab.setTabData(tab_index, board_id)
            current = self._board_ids.index(active_board_id) if active_board_id in self._board_ids else 0
            self._tab.setCurrentIndex(current if self._board_ids else -1)
        finally:
            self._tab.blockSignals(prior)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._add.setEnabled(bool(enabled))
        self._add.setToolTip(reason or "新建 Board")

    def _board_id_at(self, index: int) -> str | None:
        if 0 <= index < len(self._board_ids):
            return self._board_ids[index]
        return None

    def _on_current_changed(self, index: int) -> None:
        if self._reordering:
            return
        board_id = self._board_id_at(index)
        if board_id is not None:
            self.board_selected.emit(board_id)

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        if not (0 <= from_index < len(self._board_ids) and 0 <= to_index < len(self._board_ids)):
            return
        board_id = self._board_ids.pop(from_index)
        self._board_ids.insert(to_index, board_id)
        self._reordering = True
        try:
            self.reorder_requested.emit(board_id, to_index)
        finally:
            # Leave ``_reordering`` set until the next event-loop turn so a
            # nested ``set_boards`` / ``currentChanged`` cannot tear the bar
            # down while ``tabMoved`` is still on the stack.
            if not self._flush_boards_timer.isActive():
                self._flush_boards_timer.start(0)

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._tab.tabAt(pos)
        board_id = self._board_id_at(index)
        if board_id is None:
            return
        menu = QMenu(self)
        menu.setObjectName("ultraViewBoardMenu")
        apply_rounded_menu_chrome(menu)
        duplicate = menu.addAction("复制 Board")
        rename = menu.addAction("重命名")
        remove = menu.addAction("删除 Board")
        chosen = menu.exec_(self._tab.mapToGlobal(pos))
        if chosen is duplicate:
            self.duplicate_requested.emit(board_id)
        elif chosen is rename:
            title = self._tab.tabText(index)
            text, accepted = QInputDialog.getText(self, "重命名 Board", "名称", text=title)
            if accepted and text.strip():
                self.rename_requested.emit(board_id, text.strip())
        elif chosen is remove:
            board_name = self._tab.tabText(index)
            answer = QMessageBox.question(
                self,
                "删除 Board",
                f"确定删除“{board_name}”吗？其中的 View 引用不会删除源 View。",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Yes:
                self.delete_requested.emit(board_id)


class BoardToolbar(QFrame):
    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    copy_board_requested = pyqtSignal()
    export_png_requested = pyqtSignal(int)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)
    show_card_actions_toggled = pyqtSignal(bool)
    presentation_toggled = pyqtSignal(bool)
    overview_requested = pyqtSignal()
    board_name_changed = pyqtSignal(str)
    free_grid_toggled = pyqtSignal(bool)
    organize_free_grid_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_fit_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._name = QLineEdit(self)
        self._name.setObjectName("ultraViewBoardName")
        self._name.setText("全局对比")
        self._name.setFrame(False)
        self._name.setPlaceholderText("Board 名称")
        self._name.setToolTip("编辑 Board 名称")
        self._name.editingFinished.connect(self._on_name_finished)
        layout.addWidget(self._name, 1)

        self._layout_combo = QComboBox(self)
        self._layout_combo.setObjectName("ultraViewLayoutCombo")
        for layout_id in LAYOUT_SLOTS:
            self._layout_combo.addItem(LAYOUT_LABELS_ZH[layout_id], layout_id)
        self._layout_combo.currentIndexChanged.connect(self._on_layout_index)
        layout.addWidget(self._layout_combo, 0)

        self._free_grid = QToolButton(self)
        self._free_grid.setObjectName("ultraViewFreeGridButton")
        self._free_grid.setText("自由网格")
        self._free_grid.setCheckable(True)
        self._free_grid.setToolTip("切换自由网格（12 列基准网格）")
        self._free_grid.toggled.connect(self._on_free_grid_toggled)
        layout.addWidget(self._free_grid, 0)

        self._organize = QToolButton(self)
        self._organize.setObjectName("ultraViewOrganizeGridButton")
        self._organize.setText("整理")
        self._organize.setToolTip("移除自由网格中的空行")
        self._organize.clicked.connect(self.organize_free_grid_requested)
        self._organize.hide()
        layout.addWidget(self._organize, 0)

        self._copy = QPushButton("复制整板图", self)
        self._copy.setObjectName("ultraViewCopyBoardButton")
        self._copy.clicked.connect(self.copy_board_requested)
        layout.addWidget(self._copy, 0)

        self._export = QToolButton(self)
        self._export.setObjectName("ultraViewExportButton")
        self._export.setText("导出 PNG")
        self._export.setPopupMode(QToolButton.InstantPopup)
        self._export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        export_menu = QMenu(self._export)
        apply_rounded_menu_chrome(export_menu)
        act_1x = export_menu.addAction("导出 PNG 1×")
        act_2x = export_menu.addAction("导出 PNG 2×")
        act_1x.triggered.connect(self._on_export_1x)
        act_2x.triggered.connect(self._on_export_2x)
        self._export.setMenu(export_menu)
        layout.addWidget(self._export, 0)

        self._display = QToolButton(self)
        self._display.setObjectName("ultraViewDisplayButton")
        self._display.setText("显示")
        self._display.setPopupMode(QToolButton.InstantPopup)
        self._display.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._display.setToolTip("显示标题和来源")
        display_menu = QMenu(self._display)
        apply_rounded_menu_chrome(display_menu)
        self._act_titles = display_menu.addAction("显示标题")
        self._act_titles.setCheckable(True)
        self._act_titles.setChecked(True)
        self._act_sources = display_menu.addAction("显示来源")
        self._act_sources.setCheckable(True)
        self._act_sources.setChecked(True)
        self._act_card_actions = display_menu.addAction("常驻显示卡片操作")
        self._act_card_actions.setCheckable(True)
        self._act_card_actions.setChecked(False)
        self._act_titles.toggled.connect(self.show_titles_toggled)
        self._act_sources.toggled.connect(self.show_sources_toggled)
        self._act_card_actions.toggled.connect(self.show_card_actions_toggled)
        self._display.setMenu(display_menu)
        layout.addWidget(self._display, 0)

        self._presentation = QPushButton("演示", self)
        self._presentation.setObjectName("ultraViewPresentationButton")
        self._presentation.setCheckable(True)
        self._presentation.toggled.connect(self.presentation_toggled)
        layout.addWidget(self._presentation, 0)

        self._zoom_out = QToolButton(self)
        self._zoom_out.setObjectName("ultraViewZoomOutButton")
        self._zoom_out.setText("−")
        self._zoom_out.setToolTip("缩小画布")
        self._zoom_out.clicked.connect(self.zoom_out_requested)
        layout.addWidget(self._zoom_out, 0)
        self._zoom_label = QLabel("100%", self)
        self._zoom_label.setObjectName("ultraViewZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setMinimumWidth(42)
        layout.addWidget(self._zoom_label, 0)
        self._zoom_in = QToolButton(self)
        self._zoom_in.setObjectName("ultraViewZoomInButton")
        self._zoom_in.setText("＋")
        self._zoom_in.setToolTip("放大画布")
        self._zoom_in.clicked.connect(self.zoom_in_requested)
        layout.addWidget(self._zoom_in, 0)
        self._zoom_fit = QToolButton(self)
        self._zoom_fit.setObjectName("ultraViewZoomFitButton")
        self._zoom_fit.setText("适应")
        self._zoom_fit.setToolTip("适应内容：图面填满画布，最高 300%")
        self._zoom_fit.clicked.connect(self.zoom_fit_requested)
        layout.addWidget(self._zoom_fit, 0)
        self._zoom_reset = QToolButton(self)
        self._zoom_reset.setObjectName("ultraViewZoomResetButton")
        self._zoom_reset.setText("100%")
        self._zoom_reset.setToolTip("恢复 100% 缩放")
        self._zoom_reset.clicked.connect(self.zoom_reset_requested)
        layout.addWidget(self._zoom_reset, 0)

        self._overview = QPushButton("整板概览", self)
        self._overview.setObjectName("ultraViewBoardOverviewButton")
        self._overview.setToolTip("查看完整 Board；点击卡片可返回阅读位置")
        self._overview.clicked.connect(self.overview_requested)
        layout.addWidget(self._overview, 0)

    def set_board_name(self, name: str) -> None:
        text = name or ""
        if self._name.text() == text:
            return
        blocked = self._name.blockSignals(True)
        self._name.setText(text)
        self._name.blockSignals(blocked)

    def board_name_edit(self) -> QLineEdit:
        return self._name

    def _on_name_finished(self) -> None:
        self.board_name_changed.emit(self._name.text())

    def set_layout_id(self, layout_id: str) -> None:
        index = self._layout_combo.findData(layout_id)
        if index < 0:
            return
        blocked = self._layout_combo.blockSignals(True)
        self._layout_combo.setCurrentIndex(index)
        self._layout_combo.blockSignals(blocked)

    def set_free_grid_enabled(self, enabled: bool) -> None:
        blocked = self._free_grid.blockSignals(True)
        self._free_grid.setChecked(bool(enabled))
        self._free_grid.blockSignals(blocked)
        self._layout_combo.setVisible(not bool(enabled))
        self._organize.setVisible(bool(enabled))

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        if not enabled and self._free_grid.isVisible():
            answer = QMessageBox.question(
                self,
                "切回模板布局",
                "模板会按当前位置顺序重新排列卡片；超出模板容量的卡片会移入未放置区。继续吗？",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                blocked = self._free_grid.blockSignals(True)
                self._free_grid.setChecked(True)
                self._free_grid.blockSignals(blocked)
                return
        self.free_grid_toggled.emit(bool(enabled))

    def zoom_label(self) -> QLabel:
        return self._zoom_label

    def set_zoom_percent(self, percent: int) -> None:
        self._zoom_label.setText(f"{int(percent)}%")

    def set_presentation_checked(self, on: bool) -> None:
        blocked = self._presentation.blockSignals(True)
        self._presentation.setChecked(on)
        self._presentation.setText("退出演示" if on else "演示")
        self._presentation.blockSignals(blocked)

    def set_show_flags(
        self, titles: bool, sources: bool, card_actions: bool = False
    ) -> None:
        blocked = self._act_titles.blockSignals(True)
        self._act_titles.setChecked(bool(titles))
        self._act_titles.blockSignals(blocked)
        blocked = self._act_sources.blockSignals(True)
        self._act_sources.setChecked(bool(sources))
        self._act_sources.blockSignals(blocked)
        blocked = self._act_card_actions.blockSignals(True)
        self._act_card_actions.setChecked(bool(card_actions))
        self._act_card_actions.blockSignals(blocked)

    def set_edit_visible(self, visible: bool) -> None:
        for widget in (
            self._layout_combo,
            self._copy,
            self._export,
            self._display,
        ):
            widget.setVisible(visible)

    def _on_layout_index(self, index: int) -> None:
        layout_id = self._layout_combo.itemData(index)
        if isinstance(layout_id, str) and layout_id:
            self.layout_changed.emit(layout_id)

    def _on_export_1x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(1)

    def _on_export_2x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(2)


class CompareRail(QFrame):
    compare_filter_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCompareRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for filter_id in COMPARE_FILTERS:
            button = QPushButton(COMPARE_FILTER_LABELS_ZH[filter_id], self)
            button.setObjectName("ultraViewCompareButton")
            button.setCheckable(True)
            button.setProperty("filterId", filter_id)
            button.setFocusPolicy(Qt.TabFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(button)
            self._buttons[filter_id] = button
            root.addWidget(button, 0)
        self._buttons[COMPARE_FILTER_ALL].setChecked(True)
        self._group.buttonClicked.connect(self._on_button)
        self._warning = QLabel("", self)
        self._warning.setObjectName("ultraViewAxisWarning")
        self._warning.setWordWrap(True)
        self._warning.hide()
        root.addWidget(self._warning, 0)
        self._filter_id = COMPARE_FILTER_ALL

    def filter_id(self) -> str:
        return self._filter_id

    def set_filter_id(self, filter_id: str) -> None:
        if filter_id not in self._buttons:
            filter_id = COMPARE_FILTER_ALL
        self._filter_id = filter_id
        button = self._buttons[filter_id]
        blocked = button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(blocked)

    def set_axis_warning(self, text: str) -> None:
        self._warning.setText(text)
        self._warning.setVisible(bool(text))

    def _on_button(self, button: QPushButton) -> None:
        filter_id = str(button.property("filterId") or COMPARE_FILTER_ALL)
        if filter_id == self._filter_id:
            return
        self._filter_id = filter_id
        self.compare_filter_changed.emit(filter_id)
