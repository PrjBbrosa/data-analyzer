"""UltraView presentation-only multi-Board selector.

Receives Board DTOs from Page and emits typed intents. It never mutates a
workspace: project state, confirmation policy, and the 20-Board limit stay
on the state/coordinator owner.
"""
from __future__ import annotations

from typing import Any, Sequence

from PyQt5.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTabBar,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome


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
