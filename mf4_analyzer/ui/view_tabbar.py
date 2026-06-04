"""Excel-style time-domain View tab bar.

The widget renders the ViewManager state and emits user intent only. It does
not mutate the manager directly, leaving capture/apply and manager operations to
the integration layer.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QWidget,
)

from .view_state import MAX_VIEWS


class ViewTabBar(QWidget):
    switch_requested = pyqtSignal(int)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(int)
    rename_requested = pyqtSignal(int, str)
    duplicate_requested = pyqtSignal(int)
    color_requested = pyqtSignal(int)
    reorder_requested = pyqtSignal(int, int)
    split_requested = pyqtSignal(int)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setObjectName("viewTabBar")
        self._manager = manager
        self._suppress = False
        self._rename_editor = None
        self._rename_index = -1
        self._suppress_switch_after_reorder = False
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)

        self._tabs = QTabBar(self)
        self._tabs.setObjectName("viewTabs")
        self._tabs.setMovable(True)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setDrawBase(False)
        self._tabs.setShape(QTabBar.RoundedSouth)
        self._tabs.setFixedHeight(26)
        self._tabs.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarDoubleClicked.connect(self._on_double_clicked)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        self._tabs.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tabs, 0)

        self._plus = QPushButton("+", self)
        self._plus.setObjectName("viewTabPlus")
        self._plus.setToolTip("新建 View")
        self._plus.setFixedSize(24, 22)
        self._plus.clicked.connect(self._on_plus_clicked)
        layout.addWidget(self._plus, 0)
        layout.addStretch(1)

        manager.views_changed.connect(self.refresh)
        manager.active_changed.connect(self._sync_active)
        self.refresh()

    def count(self) -> int:
        return self._tabs.count()

    def tabBar(self) -> QTabBar:
        return self._tabs

    def refresh(self) -> None:
        self._suppress = True
        try:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for view in self._manager.views:
                idx = self._tabs.addTab(_tab_color_icon(view.tab_color), view.name)
                self._tabs.setTabData(idx, view.tab_color)
                self._tabs.setTabToolTip(idx, view.name)
            self._set_current_index(self._manager.active)
        finally:
            self._suppress = False
        self._update_plus_state()

    def _sync_active(self, idx: int) -> None:
        self._suppress = True
        try:
            self._set_current_index(idx)
        finally:
            self._suppress = False

    def _set_current_index(self, idx: int) -> None:
        if 0 <= idx < self._tabs.count():
            self._tabs.setCurrentIndex(idx)

    def _update_plus_state(self) -> None:
        can_add = len(self._manager.views) < MAX_VIEWS
        self._plus.setEnabled(can_add)
        self._plus.setToolTip("新建 View" if can_add else "View 数量已达上限")

    def _on_current_changed(self, idx: int) -> None:
        if self._suppress or idx < 0:
            return
        if self._suppress_switch_after_reorder:
            self._suppress_switch_after_reorder = False
            return
        self.switch_requested.emit(idx)

    def _on_plus_clicked(self) -> None:
        if not self._plus.isEnabled():
            return
        self.new_requested.emit()

    def _on_double_clicked(self, idx: int) -> None:
        if not self._is_valid_tab(idx):
            return
        self._begin_inline_rename(idx)

    def _begin_inline_rename(self, idx: int) -> None:
        self._finish_inline_rename(accepted=False)
        self._rename_index = idx
        editor = QLineEdit(self._tabs)
        editor.setObjectName("viewTabRenameEditor")
        editor.setText(self._tabs.tabText(idx))
        editor.selectAll()
        editor.setGeometry(self._tabs.tabRect(idx).adjusted(3, 2, -3, -2))
        editor.returnPressed.connect(
            lambda: self._finish_inline_rename(accepted=True)
        )
        editor.installEventFilter(self)
        self._rename_editor = editor
        editor.show()
        editor.setFocus(Qt.MouseFocusReason)

    def _finish_inline_rename(self, *, accepted: bool) -> None:
        editor = self._rename_editor
        if editor is None:
            return
        idx = self._rename_index
        text = editor.text()
        self._rename_editor = None
        self._rename_index = -1
        editor.removeEventFilter(self)
        editor.hide()
        editor.deleteLater()
        if accepted and self._is_valid_tab(idx):
            self.rename_requested.emit(idx, text)

    def eventFilter(self, watched, event):
        if watched is self._rename_editor:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._finish_inline_rename(accepted=False)
                return True
            if event.type() == QEvent.FocusOut:
                self._finish_inline_rename(accepted=True)
                return False
        return super().eventFilter(watched, event)

    def _on_context_menu(self, pos) -> None:
        idx = self._tabs.tabAt(pos)
        if not self._is_valid_tab(idx):
            return

        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        duplicate_action = menu.addAction("复制此 View")
        color_action = menu.addAction("改标签颜色...")
        menu.addSeparator()
        split_action = menu.addAction("与此 View 并排")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.setEnabled(len(self._manager.views) > 1)

        chosen = menu.exec_(self._tabs.mapToGlobal(pos))
        if chosen is None or not chosen.isEnabled():
            return
        if chosen is rename_action:
            self._begin_inline_rename(idx)
        elif chosen is duplicate_action:
            self.duplicate_requested.emit(idx)
        elif chosen is color_action:
            self.color_requested.emit(idx)
        elif chosen is split_action:
            self.split_requested.emit(idx)
        elif chosen is delete_action:
            self.delete_requested.emit(idx)

    def _on_tab_moved(self, from_idx: int, to_idx: int) -> None:
        if not self._suppress:
            self._suppress_switch_after_reorder = True
            QTimer.singleShot(0, self._clear_reorder_switch_suppression)
            self._emit_reorder(from_idx, to_idx)

    def _emit_reorder(self, from_idx: int, to_idx: int) -> None:
        if from_idx == to_idx:
            return
        self.reorder_requested.emit(from_idx, to_idx)

    def _clear_reorder_switch_suppression(self) -> None:
        self._suppress_switch_after_reorder = False

    def _is_valid_tab(self, idx: int) -> bool:
        return 0 <= idx < self._tabs.count()


def _tab_color_icon(hex_color: str) -> QIcon:
    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#2d7ff9")

    pixmap = QPixmap(QSize(12, 12))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(color.darker(115), 1))
    painter.setBrush(color)
    painter.drawRoundedRect(1, 3, 10, 6, 2, 2)
    painter.end()
    return QIcon(pixmap)
