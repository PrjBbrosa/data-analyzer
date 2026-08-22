"""UltraView presentation-only Board toolbar façade widget.

Hidden in the live Page; kept as a typed-intent chrome for integrations and
focused tests. Layout labels stay with this family so the widgets façade can
re-export them with identity equality.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import LAYOUT_SLOTS
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome

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
