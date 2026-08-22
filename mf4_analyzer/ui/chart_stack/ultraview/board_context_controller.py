"""Board and card context UI. Page remains the composition root.

Visible-action facts and QMenu lifetime live here. Zoom math stays on
``ViewportController`` via Page forwarders. Card chrome menus stay on
cards through ``make_context_menu``.
"""
from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QEvent, QPoint
from PyQt5.QtGui import QContextMenuEvent, QCursor
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
from mf4_analyzer.ui.ultraview_state import LAYOUT_MODE_FREE_GRID

from .card_widgets import UltraViewCard
from .chrome_islands import CardContextIsland


BOARD_MENU_OBJECT_NAME = "ultraViewBoardContextMenu"
BOARD_MENU_FIT = "适应内容"
BOARD_MENU_RESET = "100%"
BOARD_MENU_OVERVIEW = "概览"
BOARD_MENU_ARRANGE = "自动排版"
BOARD_MENU_UNDO_ARRANGE = "撤销排版"
BOARD_MENU_COPY = "复制图片"
BOARD_MENU_EXPORT = "导出 PNG"
_BOARD_MENU_CHROME_NAMES = frozenset(
    {
        "ultraViewFreeGridMinimap",
        "ultraViewToolRail",
        "ultraViewBoardIsland",
        "ultraViewStatusIsland",
        "ultraViewGlobalIsland",
        "ultraViewNavigationIsland",
        "ultraViewEmptyBoardHint",
        "ultraViewCardContextIsland",
        "ultraViewGhostOverlay",
        "ultraViewViewportFeedback",
        "ultraViewBoardPopover",
        "ultraViewLayoutPopover",
    }
)


class BoardContextController:
    """Own board context-menu build/popup/close and blank-vs-card hit routing."""

    def __init__(
        self,
        *,
        menu_parent: QWidget,
        board_scroll: QWidget,
        board_host: QWidget,
        free_grid: QWidget,
        grid: QWidget,
        card_context: CardContextIsland,
        is_presentation: Callable[[], bool],
        overview_visible: Callable[[], bool],
        focus_visible: Callable[[], bool],
        drag_active: Callable[[], bool],
        viewport_panning: Callable[[], bool],
        grid_gesture_active: Callable[[], bool],
        free_grid_gesture_active: Callable[[], bool],
        layout_mode: Callable[[], str],
        free_grid_count: Callable[[], int],
        can_undo_arrange: Callable[[], bool],
        close_active_overlay: Callable[..., object],
        zoom_fit: Callable[[], None],
        zoom_reset: Callable[[], None],
        show_overview: Callable[[], None],
        auto_arrange: Callable[[], None],
        undo_arrange: Callable[[], None],
        copy_board: Callable[[], None],
        export_png: Callable[[int], None],
        refresh_author_toolbar: Callable[[], None],
    ) -> None:
        self._menu_parent = menu_parent
        self._board_scroll = board_scroll
        self._board_host = board_host
        self._free_grid = free_grid
        self._grid = grid
        self._card_context = card_context
        self._is_presentation = is_presentation
        self._overview_visible = overview_visible
        self._focus_visible = focus_visible
        self._drag_active = drag_active
        self._viewport_panning = viewport_panning
        self._grid_gesture_active = grid_gesture_active
        self._free_grid_gesture_active = free_grid_gesture_active
        self._layout_mode = layout_mode
        self._free_grid_count = free_grid_count
        self._can_undo_arrange = can_undo_arrange
        self._close_active_overlay = close_active_overlay
        self._zoom_fit = zoom_fit
        self._zoom_reset = zoom_reset
        self._show_overview = show_overview
        self._auto_arrange = auto_arrange
        self._undo_arrange = undo_arrange
        self._copy_board = copy_board
        self._export_png = export_png
        self._refresh_author_toolbar = refresh_author_toolbar
        self._board_context_menu: QMenu | None = None

    def refresh_card_context(self) -> None:
        """Card actions now live on each card; the floating island stays hidden."""
        self._card_context.clear_ref()
        self._refresh_author_toolbar()

    def is_board_context_menu_event(self, watched, event) -> bool:
        if event.type() != QEvent.ContextMenu:
            return False
        if self._board_scroll is None:
            return False
        return watched in {
            self._board_scroll.viewport(),
            self._board_host,
            self._free_grid,
            self._grid,
        }

    def board_context_menu_blocked(self) -> bool:
        return bool(
            self._is_presentation()
            or self._overview_visible()
            or self._focus_visible()
            or self._drag_active()
            or self._viewport_panning()
            or self._grid_gesture_active()
            or self._free_grid_gesture_active()
        )

    def handle_board_context_menu(self, watched, event) -> bool:
        if self.board_context_menu_blocked():
            event.accept()
            return True
        if not self.is_blank_board_context_hit(watched, event):
            return False
        global_pos = event.globalPos() if isinstance(event, QContextMenuEvent) else QCursor.pos()
        self.popup_board_context_menu(global_pos)
        event.accept()
        return True

    def is_blank_board_context_hit(self, watched, event) -> bool:
        widget = self._context_menu_hit_widget(watched, event)
        current = widget
        while current is not None:
            if isinstance(current, (UltraViewCard, CardContextIsland)):
                return False
            name = current.objectName()
            if name in _BOARD_MENU_CHROME_NAMES or name == "ultraViewCard":
                return False
            if current in (
                self._board_host,
                self._free_grid,
                self._grid,
                self._board_scroll.viewport(),
            ):
                break
            current = current.parentWidget()
        return True

    def make_board_context_menu(self) -> QMenu:
        menu = QMenu(self._menu_parent)
        menu.setObjectName(BOARD_MENU_OBJECT_NAME)
        apply_rounded_menu_chrome(menu)
        fit = menu.addAction(BOARD_MENU_FIT)
        fit.triggered.connect(self._on_board_menu_zoom_fit)
        reset = menu.addAction(BOARD_MENU_RESET)
        reset.triggered.connect(self._on_board_menu_zoom_reset)
        overview = menu.addAction(BOARD_MENU_OVERVIEW)
        overview.triggered.connect(self._on_board_menu_overview)
        free_grid = self._layout_mode() == LAYOUT_MODE_FREE_GRID
        placed = self._free_grid_count() if free_grid else 0
        if free_grid and placed >= 2:
            menu.addSeparator()
            arrange = menu.addAction(BOARD_MENU_ARRANGE)
            arrange.triggered.connect(self._on_board_menu_auto_arrange)
            if self._can_undo_arrange():
                undo = menu.addAction(BOARD_MENU_UNDO_ARRANGE)
                undo.triggered.connect(self._on_board_menu_undo_arrange)
        menu.addSeparator()
        copy_act = menu.addAction(BOARD_MENU_COPY)
        copy_act.triggered.connect(self._on_board_menu_copy)
        export_act = menu.addAction(BOARD_MENU_EXPORT)
        export_act.triggered.connect(self._on_board_menu_export)
        return menu

    def popup_board_context_menu(self, global_pos: QPoint) -> None:
        self.close_board_context_menu()
        self._close_active_overlay(restore_focus=False)
        menu = self.make_board_context_menu()
        menu.aboutToHide.connect(self._on_board_context_menu_hidden)
        self._board_context_menu = menu
        menu.popup(global_pos)

    def close_board_context_menu(self) -> None:
        menu = self._board_context_menu
        self._board_context_menu = None
        if menu is None:
            return
        menu.close()
        menu.deleteLater()

    def _context_menu_hit_widget(self, watched, event) -> QWidget | None:
        widget = QApplication.widgetAt(event.globalPos()) if hasattr(event, "globalPos") else None
        if widget is not None:
            return widget
        pos = event.pos() if hasattr(event, "pos") else QPoint()
        child = watched.childAt(pos) if watched is not None else None
        return child if child is not None else watched

    def _on_board_context_menu_hidden(self) -> None:
        menu = self._board_context_menu
        self._board_context_menu = None
        if menu is not None:
            menu.deleteLater()

    def _on_board_menu_zoom_fit(self, _checked: bool = False) -> None:
        self._zoom_fit()

    def _on_board_menu_zoom_reset(self, _checked: bool = False) -> None:
        self._zoom_reset()

    def _on_board_menu_overview(self, _checked: bool = False) -> None:
        self._show_overview()

    def _on_board_menu_auto_arrange(self, _checked: bool = False) -> None:
        self._auto_arrange()

    def _on_board_menu_undo_arrange(self, _checked: bool = False) -> None:
        self._undo_arrange()

    def _on_board_menu_copy(self, _checked: bool = False) -> None:
        self._copy_board()

    def _on_board_menu_export(self, _checked: bool = False) -> None:
        self._export_png(1)
