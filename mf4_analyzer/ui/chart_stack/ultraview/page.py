"""Standalone UltraView page: View library, board grid, cards, overflow tray.

The page is a view. Coordinator / test harness apply intents by mutating
``UltraViewBoardState`` and calling ``set_board``. This module does not import
MainWindow or analysis compute entry points.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QMenu,
    QShortcut,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    STATUS_ORPHANED,
    UltraViewBoardState,
    UltraViewRef,
    axis_consistency_facts,
    board_to_payload,
    card_matches_compare_filter,
    default_board,
    derive_preview_status,
    first_empty_slot,
    layout_slots,
    membership_set,
    parse_ref_payload,
    placement_for,
    slot_occupant,
)

from .widgets import (
    LIBRARY_DEFAULT_WIDTH,
    BoardGrid,
    BoardToolbar,
    CardViewModel,
    CompareRail,
    FocusLayer,
    LibraryRow,
    UltraViewHintBar,
    UnplacedTray,
    ViewLibraryPanel,
    coerce_library_row,
    preview_image,
)


class UltraViewPage(QWidget):
    add_ref_requested = pyqtSignal(str, str)
    replace_slot_requested = pyqtSignal(str, str, str)
    swap_slots_requested = pyqtSignal(str, str)
    place_from_unplaced_requested = pyqtSignal(str, str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    copy_board_requested = pyqtSignal()
    copy_card_image_requested = pyqtSignal(str, str)
    export_png_requested = pyqtSignal(int)
    presentation_toggled = pyqtSignal(bool)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)
    rebind_ref_requested = pyqtSignal(str, str, str, str)
    locate_ref_requested = pyqtSignal(str, str)
    compare_filter_changed = pyqtSignal(str)
    quickref_requested = pyqtSignal()
    selection_changed = pyqtSignal(str, str)
    board_name_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._board = default_board()
        self._previews: dict[UltraViewRef, Any] = {}
        self._statuses: dict[UltraViewRef, str] = {}
        self._ref_exists: dict[UltraViewRef, bool] = {}
        self._selected: UltraViewRef | None = None
        self._replacement_slot: str | None = None
        self._replacement_ref: UltraViewRef | None = None
        self._compare_filter = COMPARE_FILTER_ALL
        self._drag_kind: str | None = None
        self._presentation = False
        self._library_visible = True
        self._prev_unplaced_count: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setObjectName("ultraViewSplitter")
        self._library = ViewLibraryPanel(self._splitter)
        self._board_column = QFrame(self._splitter)
        self._board_column.setObjectName("ultraViewBoardColumn")
        self._board_column.setAttribute(Qt.WA_StyledBackground, True)
        column = QVBoxLayout(self._board_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._toolbar = BoardToolbar(self._board_column)
        self._rail = CompareRail(self._board_column)
        self._grid = BoardGrid(self._board_column)
        self._tray = UnplacedTray(self._board_column)
        column.addWidget(self._toolbar, 0)
        column.addWidget(self._rail, 0)
        column.addWidget(self._grid, 1)
        column.addWidget(self._tray, 0)
        self._splitter.addWidget(self._library)
        self._splitter.addWidget(self._board_column)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([LIBRARY_DEFAULT_WIDTH, 1200])
        root.addWidget(self._splitter, 1)

        self._hint_bar = UltraViewHintBar(self)
        self._hint_bar.quickref_requested.connect(self.quickref_requested.emit)
        root.addWidget(self._hint_bar, 0)

        self._focus = FocusLayer(self)
        self._focus.hide()

        self._library.add_requested.connect(self.request_add)
        self._library.locate_requested.connect(self._on_locate)
        self._library.drag_started.connect(self._on_drag_started)
        self._library.drag_finished.connect(self._on_drag_finished)

        self._toolbar.layout_changed.connect(self.layout_changed)
        self._toolbar.ratio_nudge_requested.connect(self.ratio_nudge_requested)
        self._toolbar.add_clicked.connect(self._on_toolbar_add)
        self._toolbar.copy_board_requested.connect(self.copy_board_requested)
        self._toolbar.export_png_requested.connect(self.export_png_requested)
        self._toolbar.show_titles_toggled.connect(self.show_titles_toggled)
        self._toolbar.show_sources_toggled.connect(self.show_sources_toggled)
        self._toolbar.presentation_toggled.connect(self._on_presentation_button)
        self._toolbar.board_name_changed.connect(self.board_name_changed)

        self._rail.compare_filter_changed.connect(self._on_compare_filter)

        self._grid.add_clicked.connect(self._on_empty_slot)
        self._grid.ref_dropped.connect(self._on_ref_dropped)
        self._grid.open_source_requested.connect(self.open_source_requested)
        self._grid.focus_requested.connect(self._on_focus)
        self._grid.rebind_arm_requested.connect(self._on_rebind_arm)
        self._grid.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        self._grid.remove_ref_requested.connect(self.remove_ref_requested)
        self._grid.copy_card_image_requested.connect(self.copy_card_image_requested)
        self._grid.selected.connect(self._on_card_selected)
        self._grid.drag_started.connect(self._on_drag_started)
        self._grid.drag_finished.connect(self._on_drag_finished)

        self._tray.place_requested.connect(self._on_tray_place)
        self._tray.remove_requested.connect(self.remove_ref_requested)
        self._tray.locate_requested.connect(self._on_locate)
        self._tray.rebind_arm_requested.connect(self._on_rebind_arm)
        self._tray.move_to_unplaced_dropped.connect(self._on_tray_drop)
        self._tray.drag_started.connect(self._on_drag_started)
        self._tray.drag_finished.connect(self._on_drag_finished)

        self._focus.open_source_requested.connect(self.open_source_requested)
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.setContext(Qt.WidgetWithChildrenShortcut)
        self._esc.activated.connect(self._on_escape_shortcut)
        self.set_board(self._board)

    def hint_bar(self) -> QWidget:
        return self._hint_bar

    def library_panel(self) -> ViewLibraryPanel:
        return self._library

    def board_grid(self) -> BoardGrid:
        return self._grid

    def unplaced_tray(self) -> UnplacedTray:
        return self._tray

    def compare_rail(self) -> CompareRail:
        return self._rail

    def board_toolbar(self) -> BoardToolbar:
        return self._toolbar

    def focus_layer(self) -> FocusLayer:
        return self._focus

    def board(self) -> UltraViewBoardState:
        return self._board

    def board_payload(self) -> dict[str, Any]:
        return board_to_payload(self._board)

    def compare_filter(self) -> str:
        return self._compare_filter

    def set_compare_filter(self, filter_id: str) -> None:
        wanted = str(filter_id or COMPARE_FILTER_ALL)
        self._compare_filter = wanted
        self._rail.set_filter_id(wanted)
        self._refresh_projection()

    def show_focus(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        record = self._previews.get(ref) if ref is not None else None
        title = getattr(record, "title", "") if record is not None else view_id
        image = preview_image(record)
        self._focus.setGeometry(self.rect())
        self._focus.show_ref(section, view_id, title or view_id, image)

    def replacement_slot(self) -> str | None:
        return self._replacement_slot

    def replacement_ref(self) -> tuple[str, str] | None:
        if self._replacement_ref is None:
            return None
        return self._replacement_ref.section, self._replacement_ref.view_id

    def selected_ref(self) -> tuple[str, str] | None:
        if self._selected is None:
            return None
        return self._selected.section, self._selected.view_id

    def is_library_visible(self) -> bool:
        return self._library_visible

    def is_presentation_active(self) -> bool:
        return self._presentation

    def card_widget(self, section: str, view_id: str):
        return self._grid.card_for(section, view_id)

    def slot_widget(self, slot_id: str):
        return self._grid.slot_widget(slot_id)

    def set_library_visible(self, visible: bool) -> None:
        self._library_visible = bool(visible)
        self._library.setVisible(self._library_visible and not self._presentation)

    def set_presentation_active(self, active: bool) -> None:
        self._presentation = bool(active)
        self._toolbar.set_presentation_checked(self._presentation)
        self._library.setVisible(self._library_visible and not self._presentation)
        self._toolbar.set_edit_visible(not self._presentation)
        self._rail.setVisible(not self._presentation)
        self._tray.title_bar().setVisible(True)
        if self._presentation:
            self._tray.body().setVisible(False)
        else:
            self._tray.body().setVisible(self._tray.is_expanded())

    def set_library_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        coerced = [coerce_library_row(row) for row in rows]
        self._library.set_rows(coerced)
        self._library.set_on_board(membership_set(self._board))

    def set_preview(self, ref: UltraViewRef | Mapping[str, Any], record_like: Any) -> None:
        parsed = ref if isinstance(ref, UltraViewRef) else parse_ref_payload(ref)
        if parsed is None:
            return
        self._previews[parsed] = record_like
        self._refresh_projection()

    def set_ref_status(
        self,
        ref: UltraViewRef | Mapping[str, Any],
        status: str,
        ref_exists: bool,
    ) -> None:
        parsed = ref if isinstance(ref, UltraViewRef) else parse_ref_payload(ref)
        if parsed is None:
            return
        self._statuses[parsed] = str(status)
        self._ref_exists[parsed] = bool(ref_exists)
        self._refresh_projection()

    def set_board(self, board: UltraViewBoardState) -> None:
        prev = self._prev_unplaced_count
        self._board = board
        n_unplaced = len(board.unplaced)
        if n_unplaced > 0 and (prev is None or prev == 0):
            self._tray.set_expanded(True)
        self._prev_unplaced_count = n_unplaced
        if self._replacement_ref is not None and self._replacement_ref not in membership_set(board):
            self._replacement_ref = None
            self._replacement_slot = None
        elif self._replacement_slot and self._replacement_slot not in layout_slots(board.layout_id):
            self._replacement_slot = None
        self._toolbar.set_board_name(board.name)
        self._toolbar.set_layout_id(board.layout_id)
        self._toolbar.set_show_flags(board.show_titles, board.show_sources)
        self._library.set_on_board(membership_set(board))
        self._refresh_projection()

    def request_add(self, section: str, view_id: str) -> None:
        self._emit_add(section, view_id)

    def arm_replacement(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None or self._board is None:
            return
        if ref not in membership_set(self._board):
            return
        placement = placement_for(self._board, ref)
        self._replacement_ref = ref
        self._replacement_slot = None if placement is None else placement.slot_id
        self._library.focus_search()
        self.rebind_arm_requested.emit(section, view_id)
        self._refresh_projection()

    def clear_replacement_arm(self) -> None:
        if self._replacement_slot is None and self._replacement_ref is None:
            return
        self._replacement_slot = None
        self._replacement_ref = None
        self._refresh_projection()

    def reset_sheet_session(self) -> None:
        """Leave focus / replacement / presentation before the tool window closes."""
        if self._focus.isVisible():
            self._focus.close_layer()
        self.clear_replacement_arm()
        if self._presentation:
            self.set_presentation_active(False)
            self.presentation_toggled.emit(False)

    def _on_escape_shortcut(self) -> None:
        self.handle_escape()

    def handle_escape(self) -> bool:
        if self._focus.isVisible():
            self._focus.close_layer()
            return True
        if self._replacement_slot is not None or self._replacement_ref is not None:
            self.clear_replacement_arm()
            return True
        if self._presentation:
            self.set_presentation_active(False)
            self.presentation_toggled.emit(False)
            return True
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu) and popup.isVisible():
            popup.close()
            return True
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._focus.setGeometry(self.rect())

    def _on_drag_started(self, kind: str) -> None:
        self._drag_kind = kind

    def _on_drag_finished(self) -> None:
        self._drag_kind = None

    def _on_toolbar_add(self) -> None:
        selected = self._library.selected_ref()
        if selected is None:
            self._library.focus_search()
            return
        self._emit_add(selected[0], selected[1])

    def _on_empty_slot(self, _slot_id: str) -> None:
        selected = self._library.selected_ref()
        if selected is None:
            self._library.focus_search()
            return
        self._emit_add(selected[0], selected[1])

    def _on_locate(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self._select_ref(ref)
        self.locate_ref_requested.emit(section, view_id)

    def _on_card_selected(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self._select_ref(ref)

    def _on_focus(self, section: str, view_id: str) -> None:
        self.focus_requested.emit(section, view_id)
        self.show_focus(section, view_id)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        self.arm_replacement(section, view_id)

    def _on_presentation_button(self, checked: bool) -> None:
        self.set_presentation_active(checked)
        self.presentation_toggled.emit(checked)

    def _on_compare_filter(self, filter_id: str) -> None:
        self._compare_filter = filter_id
        self.compare_filter_changed.emit(filter_id)
        self._refresh_projection()

    def _on_tray_place(self, section: str, view_id: str) -> None:
        slot = first_empty_slot(self._board)
        if slot is None:
            return
        self.place_from_unplaced_requested.emit(slot, section, view_id)

    def _on_tray_drop(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if placement_for(self._board, ref) is not None:
            self.move_to_unplaced_requested.emit(section, view_id)

    def _on_ref_dropped(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        kind = self._drag_kind
        if self._replacement_ref is not None or self._replacement_slot:
            if ref in membership_set(self._board) and kind == "library":
                self._on_locate(section, view_id)
                return
            if ref not in membership_set(self._board) or kind in (None, "library"):
                if ref in membership_set(self._board):
                    self._on_locate(section, view_id)
                    return
                self._finish_armed_replacement(section, view_id)
                return
        in_tray = ref in self._board.unplaced
        placed = placement_for(self._board, ref)
        if kind == "library" or (kind is None and placed is None and not in_tray):
            if ref in membership_set(self._board):
                self._on_locate(section, view_id)
                return
            occupant = slot_occupant(self._board, slot_id)
            if occupant is None:
                self.add_ref_requested.emit(section, view_id)
            else:
                self.replace_slot_requested.emit(slot_id, section, view_id)
            return
        if kind == "tray" or (kind is None and in_tray):
            self.place_from_unplaced_requested.emit(slot_id, section, view_id)
            return
        if placed is not None:
            if placed.slot_id == slot_id:
                self._select_ref(ref)
                return
            self.swap_slots_requested.emit(placed.slot_id, slot_id)
            return
        if in_tray:
            self.place_from_unplaced_requested.emit(slot_id, section, view_id)
            return
        occupant = slot_occupant(self._board, slot_id)
        if occupant is None:
            self.add_ref_requested.emit(section, view_id)
        else:
            self.replace_slot_requested.emit(slot_id, section, view_id)

    def _emit_add(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref in membership_set(self._board):
            self._on_locate(section, view_id)
            return
        if self._replacement_ref is not None or self._replacement_slot:
            self._finish_armed_replacement(section, view_id)
            return
        self.add_ref_requested.emit(section, view_id)

    def _finish_armed_replacement(self, section: str, view_id: str) -> None:
        old = self._replacement_ref
        slot = self._replacement_slot
        self.clear_replacement_arm()
        if old is not None and self._status_for(old) == STATUS_ORPHANED:
            self.rebind_ref_requested.emit(
                old.section, old.view_id, section, view_id
            )
            return
        if slot:
            self.replace_slot_requested.emit(slot, section, view_id)

    def _select_ref(self, ref: UltraViewRef) -> None:
        self._selected = ref
        self._library.set_selected(ref.section, ref.view_id)
        if ref in self._board.unplaced:
            self._tray.set_expanded(True)
        self._refresh_projection()
        self.selection_changed.emit(ref.section, ref.view_id)

    def _status_for(self, ref: UltraViewRef) -> str:
        if ref in self._statuses:
            return self._statuses[ref]
        exists = self._ref_exists.get(ref, True)
        record = self._previews.get(ref)
        image_valid = preview_image(record) is not None
        captured = getattr(record, "captured_digest", None) if record is not None else None
        return derive_preview_status(exists, image_valid, captured, None)

    def _library_row_for(self, ref: UltraViewRef):
        for row in self._library.row_widgets():
            item = row.row()
            if item.section == ref.section and item.view_id == ref.view_id:
                return item
        return None

    def _chrome_value(
        self,
        ref: UltraViewRef,
        *,
        lib_attr: str,
        record_attr: str,
        default: str = "",
    ) -> str:
        live = self._ref_exists.get(ref, True)
        lib = self._library_row_for(ref)
        record = self._previews.get(ref)
        lib_val = str(getattr(lib, lib_attr, "") or "") if lib is not None else ""
        rec_val = (
            str(getattr(record, record_attr, "") or "") if record is not None else ""
        )
        if live:
            return lib_val or rec_val or default
        return rec_val or lib_val or default

    def _title_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(
            ref, lib_attr="name", record_attr="title", default=ref.view_id
        )

    def _color_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(ref, lib_attr="tab_color", record_attr="tab_color")

    def _source_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(
            ref, lib_attr="source_summary", record_attr="source_summary"
        )

    def _axis_for(self, ref: UltraViewRef) -> str | None:
        record = self._previews.get(ref)
        if record is None:
            return None
        kind = getattr(record, "axis_kind", None)
        return str(kind) if kind else None

    def _refresh_projection(self) -> None:
        models: dict[str, CardViewModel | None] = {}
        axis_records = []
        for slot_id in layout_slots(self._board.layout_id):
            ref = slot_occupant(self._board, slot_id)
            if ref is None:
                models[slot_id] = None
                continue
            record = self._previews.get(ref)
            status = self._status_for(ref)
            axis_kind = self._axis_for(ref)
            x_unit = str(getattr(record, "x_unit", "") or "") if record is not None else ""
            raw_range = getattr(record, "x_range", None) if record is not None else None
            x_range = None
            if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
                try:
                    x_range = (float(raw_range[0]), float(raw_range[1]))
                except (TypeError, ValueError):
                    x_range = None
            if axis_kind:
                axis_records.append(
                    {"axis_kind": axis_kind, "x_unit": x_unit, "x_range": x_range}
                )
            models[slot_id] = CardViewModel(
                slot_id=slot_id,
                section=ref.section,
                view_id=ref.view_id,
                title=self._title_for(ref),
                tab_color=self._color_for(ref),
                status=status,
                source_summary=self._source_for(ref),
                axis_kind=axis_kind,
                x_unit=x_unit,
                x_range=x_range,
                image=preview_image(record),
                selected=self._selected == ref,
                dimmed=not card_matches_compare_filter(axis_kind, self._compare_filter),
                replacement_armed=(
                    self._replacement_ref == ref
                    or self._replacement_slot == slot_id
                ),
                show_title=bool(self._board.show_titles),
                show_source=bool(self._board.show_sources),
            )
        self._grid.set_grid(self._board.layout_id, self._board.primary_ratio, models)
        titles = {}
        colors = {}
        statuses = {}
        for ref in self._board.unplaced:
            key = (ref.section, ref.view_id)
            titles[key] = self._title_for(ref)
            colors[key] = self._color_for(ref)
            statuses[key] = self._status_for(ref)
        self._tray.set_refs(
            self._board.unplaced,
            titles=titles,
            colors=colors,
            statuses=statuses,
            armed=self._replacement_ref,
        )
        facts = axis_consistency_facts(axis_records)
        warnings = []
        if facts.unit_inconsistent_kinds:
            warnings.append("量纲不一致")
        if facts.range_inconsistent_kinds:
            warnings.append("X 范围不一致")
        self._rail.set_axis_warning(" · ".join(warnings))
        self._focus.setGeometry(self.rect())
