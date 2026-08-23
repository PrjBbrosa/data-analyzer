"""UltraView workspace mutation owner: Board, history, and projection close.

MainWindow still talks to ``UltraViewCoordinator``. This controller is the
single workspace/history/funnel owner; the coordinator constructs one instance
and keeps façade delegates. Capture, PreviewStore, and sidecar live on
``UltraViewCaptureCoordinator``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from PyQt5 import sip
from PyQt5.QtWidgets import QWidget

from ...ultraview_core.author_ops import (
    apply_board_edit_entry,
    board_edit_entry_byte_cost,
)
from ...ultraview_core.board_ops import (
    active_board,
    add_ref,
    apply_board_placement,
    apply_free_grid_preset,
    capture_board_placement,
    create_board,
    delete_board,
    duplicate_board,
    free_grid_default_span,
    free_grid_placement_for,
    free_grid_to_template,
    mark_workspace_mutated,
    membership_set,
    move_to_unplaced,
    nudge_ratio,
    organize_free_grid,
    place_from_unplaced,
    place_free_grid_from_unplaced,
    placement_for,
    rebind_ref,
    remove_ref,
    rename_board,
    reorder_board,
    replace_free_grid_ref,
    replace_slot,
    set_active_board,
    set_free_grid_rect,
    set_free_grid_rects,
    set_layout,
    set_presentation_flags,
    set_workspace_show_card_actions,
    swap_slots,
    template_to_free_grid,
)
from ...ultraview_core.model import (
    DEFAULT_BOARD_NAME,
    LAYOUT_MODE_FREE_GRID,
    MAX_UI_BOARDS,
    AuthorMutationResult,
    BoardEditEntry,
    BoardPlacementSnapshot,
    GridAnchor,
    GridRect,
    UltraViewBoardState,
    UltraViewRef,
    UltraViewWorkspaceState,
    best_template_for,
    layout_slots,
    parse_ref_payload,
)
from ..ultraview_edits import (
    SelectionMutationPlan,
    plan_selection_delete,
    plan_selection_nudge,
)
from ..chart_stack.ultraview.author_edits import (
    apply_author_create,
    apply_author_delete,
    apply_author_intent,
    apply_author_update,
    re_resolve_connector_endpoints,
    warning_copy,
)
from ..chart_stack.ultraview.author_tools import (
    AuthorAlignIntent,
    AuthorBatchStyleIntent,
    AuthorDistributeIntent,
    AuthorDuplicateIntent,
    AuthorLockIntent,
    AuthorNudgeIntent,
    AuthorPasteIntent,
    AuthorZOrderIntent,
    ConnectorCreateIntent,
    ConnectorUpdateIntent,
    SelectionDeleteIntent,
    SelectionNudgeIntent,
    ShapeCreateIntent,
    ShapeUpdateIntent,
    TextCreateIntent,
    TextUpdateIntent,
)
from ..chart_stack.ultraview.feedback import (
    MEMBERSHIP_CAP,
    PLACED_CAP_STILL_UNPLACED,
    PLACED_CAP_TO_TRAY,
    REMOVED_FROM_BOARD,
    text_for_key,
)
from ..chart_stack.ultraview.card_fit import (
    REASON_NO_PREVIEW,
    REASON_NO_SPACE,
    CardFitFacts,
    fit_rect_for_aspect,
    solve_card_fit,
)
from ..chart_stack.ultraview.free_grid import (
    LAYOUT_ARRANGE,
    plan_auto_arrange,
    screen_grid_metrics,
)
from ..chart_stack.ultraview.layouts import (
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
)


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except (RuntimeError, TypeError):
        return True


_PLACEMENT_HISTORY_CAP = 100
_BOARD_HISTORY_BYTE_BUDGET = 32 * 1024 * 1024


@dataclass(frozen=True)
class _GridHistoryEntry:
    before: BoardPlacementSnapshot
    after: BoardPlacementSnapshot
    kind: str = ""


@dataclass
class _GridHistory:
    # Keep the historical name/type around for placement callers.  Schema-5
    # authoring entries share this per-Board owner so a mixed move is one undo.
    undo: list[_GridHistoryEntry | BoardEditEntry]
    redo: list[_GridHistoryEntry | BoardEditEntry]
    undo_bytes: int = 0
    redo_bytes: int = 0


@dataclass(frozen=True)
class _PendingAutoAspect:
    board_id: str
    ref: UltraViewRef
    inserted_rect: GridRect
    layout_revision: int
    merge_add: bool = True


def _visible_widget_height(widget) -> int:
    if widget is None or not _alive(widget) or widget.isHidden():
        return 0
    return max(0, int(widget.height()))


class UltraViewWorkspaceController:
    """Own workspace/Board mutation, history, and the projection-close funnel."""

    def __init__(
        self,
        workspace: UltraViewWorkspaceState,
        *,
        is_inactive: Callable[[], bool],
        refresh_projection: Callable[[], None],
        toast: Callable[[str, str], None],
        page: Callable[[], Any],
        preview_fit_image_size: Callable[[UltraViewRef], tuple[int, int] | None],
        on_active_board_changed: Callable[[], None],
    ) -> None:
        self._workspace = workspace
        self._is_inactive = is_inactive
        self._refresh_projection = refresh_projection
        self._toast_impl = toast
        self._page_impl = page
        self._preview_fit_image_size_impl = preview_fit_image_size
        self._on_active_board_changed = on_active_board_changed
        self._grid_histories: dict[str, _GridHistory] = {}
        self._pending_auto_aspect: dict[tuple[str, UltraViewRef], _PendingAutoAspect] = {}
        self._layout_revision: dict[str, int] = {}

    @property
    def board(self) -> UltraViewBoardState:
        return active_board(self._workspace)

    @property
    def workspace(self) -> UltraViewWorkspaceState:
        return self._workspace

    @property
    def grid_histories(self):
        """Compatibility view owned by this controller."""
        return self._grid_histories

    @property
    def pending_auto_aspect(self):
        """Compatibility view owned by this controller."""
        return self._pending_auto_aspect

    @property
    def layout_revision(self):
        """Compatibility view owned by this controller."""
        return self._layout_revision

    def replace_workspace(self, workspace: UltraViewWorkspaceState) -> None:
        """Swap the live workspace object. Does not copy history or Board state."""
        self._workspace = workspace

    def _inactive(self) -> bool:
        return bool(self._is_inactive())

    def refresh_page(self) -> None:
        """Ask the façade to republish the immutable projection snapshot."""
        self._refresh_projection()

    def _toast(self, message: str, level: str) -> None:
        self._toast_impl(message, level)

    def page(self):
        return self._page_impl()

    def _preview_fit_image_size(self, ref: UltraViewRef) -> tuple[int, int] | None:
        return self._preview_fit_image_size_impl(ref)

    def _prioritize_sidecar_queue(self) -> None:
        self._on_active_board_changed()

    def _after_board_mutation(self) -> None:
        if self._inactive():
            return
        mark_workspace_mutated(self._workspace)
        self.refresh_page()

    def _apply_add_ref(
        self, ref: UltraViewRef, *, preferred_anchor: GridAnchor | None = None
    ) -> None:
        if self._inactive():
            return
        page = self.page()
        board = active_board(self._workspace)
        if ref in membership_set(board):
            if page is not None:
                page.select_ref(ref)
            return
        image_size = self._preview_fit_image_size(ref)
        span = None
        if board.layout_mode == LAYOUT_MODE_FREE_GRID:
            span = self._insert_span_for_ref(board, ref)
        before = self._placement_snapshot(board)
        warnings = add_ref(
            board, ref, preferred_anchor=preferred_anchor, span=span
        )
        if warnings and warnings[0] == "membership_limit":
            self._toast(text_for_key(MEMBERSHIP_CAP), "warning")
            return
        placed_in_tray = (
            board.layout_mode == LAYOUT_MODE_FREE_GRID and ref in board.unplaced
        )
        if placed_in_tray:
            self._toast(text_for_key(PLACED_CAP_TO_TRAY), "info")
        self._commit_grid_change(board, before, [])
        if (
            board.layout_mode == LAYOUT_MODE_FREE_GRID
            and image_size is None
        ):
            item = free_grid_placement_for(board, ref)
            if item is not None:
                self._register_pending_auto_aspect(board, ref, item.rect)

    def _on_add_ref(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            page = self.page()
            anchor = (
                page.current_free_grid_insert_anchor() if page is not None else None
            )
            self._apply_add_ref(ref, preferred_anchor=anchor)

    def _on_replace_slot(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        replace_slot(board, slot_id, ref)
        self._commit_grid_change(board, before, [])

    def _on_rebind_ref(
        self,
        old_section: str,
        old_view_id: str,
        new_section: str,
        new_view_id: str,
    ) -> None:
        old_ref = parse_ref_payload({"section": old_section, "view_id": old_view_id})
        new_ref = parse_ref_payload({"section": new_section, "view_id": new_view_id})
        if old_ref is None or new_ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        rebind_ref(board, old_ref, new_ref)
        self._cancel_pending_for_ref(board.board_id, old_ref)
        self._commit_grid_change(board, before, [])

    def _on_swap_slots(self, slot_a: str, slot_b: str) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        swap_slots(board, slot_a, slot_b)
        self._commit_grid_change(board, before, [])

    def _on_place_from_unplaced(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        place_from_unplaced(board, slot_id, ref)
        self._commit_grid_change(board, before, [])

    def _on_place_free_grid_from_unplaced(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        page = self.page()
        anchor = (
            page.current_free_grid_insert_anchor() if page is not None else None
        )
        board = active_board(self._workspace)
        self._place_unplaced_on_free_grid(
            board, ref, preferred_anchor=anchor
        )

    def _on_free_grid_insert(
        self, section: str, view_id: str, anchor: GridAnchor
    ) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        page = self.page()
        if ref in membership_set(board):
            if page is not None:
                page.select_ref(ref)
            return
        if ref in board.unplaced:
            self._place_unplaced_on_free_grid(
                board, ref, preferred_anchor=anchor
            )
            return
        self._apply_add_ref(ref, preferred_anchor=anchor)

    def _on_free_grid_replace(
        self,
        target_section: str,
        target_view_id: str,
        source_section: str,
        source_view_id: str,
    ) -> None:
        target = parse_ref_payload({"section": target_section, "view_id": target_view_id})
        new_ref = parse_ref_payload({"section": source_section, "view_id": source_view_id})
        if target is None or new_ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        warnings = replace_free_grid_ref(board, target, new_ref)
        if not warnings:
            self._cancel_pending_for_ref(board.board_id, target)
        self._commit_grid_change(board, before, warnings)

    def _on_move_to_unplaced(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        move_to_unplaced(board, ref)
        self._commit_grid_change(board, before, [], lost_cards=(ref,))

    def _on_remove_ref(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        if ref not in membership_set(board):
            return
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        warnings = remove_ref(board, ref)
        self._commit_grid_change(board, before, warnings, lost_cards=(ref,))
        if not warnings:
            self._toast(text_for_key(REMOVED_FROM_BOARD), "info")

    def _on_layout(self, layout_id: str) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        warnings = set_layout(board, str(layout_id))
        self._cancel_pending_for_board(board.board_id)
        self._bump_layout_revision(board.board_id)
        self._toast_layout_warnings(warnings)
        if not self._record_grid_transition(board, before):
            self._after_board_mutation()

    def _on_ratio_nudge(self, steps: int) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        nudge_ratio(board, int(steps))
        self._commit_grid_change(board, before, [])

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if enabled and board.layout_mode != LAYOUT_MODE_FREE_GRID:
            template_to_free_grid(board)
        elif not enabled and board.layout_mode == LAYOUT_MODE_FREE_GRID:
            free_grid_to_template(board, best_template_for(len(board.free_grid)))
        else:
            return
        self._cancel_pending_for_board(board.board_id)
        self._bump_layout_revision(board.board_id)
        if not self._record_grid_transition(board, before):
            self._after_board_mutation()

    def _on_free_grid_geometry(
        self,
        section: str,
        view_id: str,
        column: int,
        row: int,
        column_span: int,
        row_span: int,
        _reason: str,
    ) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        wanted = GridRect(int(column), int(row), int(column_span), int(row_span))
        current = free_grid_placement_for(board, ref)
        if current is None:
            return
        span_changed = (
            current.rect.column_span != wanted.column_span
            or current.rect.row_span != wanted.row_span
        )
        warnings = set_free_grid_rect(board, ref, wanted)
        if not warnings and span_changed:
            self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_group_geometry(self, updates) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        parsed: list[tuple[UltraViewRef, GridRect]] = []
        for item in tuple(updates or ()):
            if not isinstance(item, (tuple, list)) or len(item) != 6:
                return
            section, view_id, column, row, column_span, row_span = item
            ref = parse_ref_payload({"section": section, "view_id": view_id})
            if ref is None:
                return
            parsed.append(
                (
                    ref,
                    GridRect(int(column), int(row), int(column_span), int(row_span)),
                )
            )
        if not parsed:
            return
        current = {item.ref: item.rect for item in board.free_grid}
        span_changed = [
            ref
            for ref, wanted in parsed
            if current.get(ref) is not None
            and (
                current[ref].column_span != wanted.column_span
                or current[ref].row_span != wanted.row_span
            )
        ]
        warnings = set_free_grid_rects(board, parsed)
        if not warnings:
            for ref in span_changed:
                self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_preset(self, section: str, view_id: str, preset: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if not any(item_ref == ref for item_ref, _rect in before.free_grid):
            return
        warnings = apply_free_grid_preset(board, ref, preset)
        if not warnings:
            self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_autofit(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        if board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return
        item = free_grid_placement_for(board, ref)
        if item is None:
            return
        image_size = self._preview_fit_image_size(ref)
        facts = self._card_fit_facts_for(board, item, image_size)
        result = solve_card_fit(facts)
        if result.reason == REASON_NO_PREVIEW:
            self._toast("没有可用预览，无法按原图比例调整", "warning")
            return
        if result.reason == REASON_NO_SPACE:
            self._toast("附近空间不足", "warning")
            return
        if not result.improved or result.candidate == item.rect:
            return
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        warnings = set_free_grid_rects(board, ((ref, result.candidate),))
        self._commit_grid_change(board, before, warnings)

    def _card_fit_facts_for(
        self,
        board: UltraViewBoardState,
        item,
        image_size: tuple[int, int] | None,
    ) -> CardFitFacts:
        occupied = tuple(
            other.rect for other in board.free_grid if other.ref != item.ref
        )
        header, footer, margin_x, margin_y, orphan = self._live_card_fit_chrome(
            item.ref
        )
        return CardFitFacts(
            image_logical_size=image_size,
            current_rect=item.rect,
            metrics=screen_grid_metrics(board.free_grid),
            header_height=header,
            footer_height=footer,
            image_margin_x=margin_x,
            image_margin_y=margin_y,
            occupied=occupied,
            orphan_height=orphan,
        )

    def _live_card_fit_chrome(
        self, ref: UltraViewRef
    ) -> tuple[int, int, int, int, int]:
        """Header/footer/orphan heights and image margins from the live card.

        Falls back to CARD_* constants when the widget is missing (headless
        tests) so occupied-neighbour rejection still applies.
        """
        defaults = (
            CARD_HEADER_HEIGHT,
            CARD_FOOTER_HEIGHT,
            CARD_IMAGE_PADDING,
            CARD_IMAGE_PADDING,
            0,
        )
        page = self.page()
        if page is None:
            return defaults
        card = page.card_widget(ref.section, ref.view_id)
        if card is None or not _alive(card):
            return defaults
        image = card.findChild(QWidget, "ultraViewCardImage")
        header = card.findChild(QWidget, "ultraViewCardHeader")
        footer = card.findChild(QWidget, "ultraViewCardFooter")
        orphan = card.findChild(QWidget, "ultraViewCardOrphanBar")
        if image is None or not _alive(image):
            return defaults
        contents = image.contentsRect()
        if image.width() >= 2 and contents.width() >= 1:
            margin_x = max(0, int(contents.x()))
            margin_y = max(0, int(contents.y()))
        else:
            margin_x = CARD_IMAGE_PADDING
            margin_y = CARD_IMAGE_PADDING
        return (
            _visible_widget_height(header),
            _visible_widget_height(footer),
            margin_x,
            margin_y,
            _visible_widget_height(orphan),
        )

    def _on_organize_free_grid(self) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if not organize_free_grid(board):
            self._record_grid_transition(board, before)

    def _on_auto_arrange_free_grid(self) -> None:
        if self._inactive():
            return
        board = active_board(self._workspace)
        if board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return
        if len(board.free_grid) < 2:
            self._toast("卡片不足", "info")
            return
        before = self._placement_snapshot(board)
        plan = plan_auto_arrange(
            tuple(board.free_grid),
            layout_revision=self._current_layout_revision(board.board_id),
        )
        if not plan.accepted:
            self._toast("无法排入安全区", "warning")
            return
        updates = plan.committed_updates()
        if not updates:
            self._toast("已是紧凑布局", "info")
            return
        warnings = set_free_grid_rects(board, updates)
        if warnings:
            self._toast_grid_warnings(warnings)
            return
        self._cancel_pending_for_board(board.board_id)
        self._bump_layout_revision(board.board_id)
        self._commit_grid_change(board, before, [], kind=LAYOUT_ARRANGE)
        self._toast("已排版", "info")

    def _can_undo_auto_arrange(self) -> bool:
        if self._inactive():
            return False
        board = active_board(self._workspace)
        history = self._grid_histories.get(board.board_id)
        return bool(
            history is not None
            and history.undo
            and isinstance(history.undo[-1], _GridHistoryEntry)
            and history.undo[-1].kind == LAYOUT_ARRANGE
        )

    def _grid_history(self, board: UltraViewBoardState) -> _GridHistory:
        return self._grid_histories.setdefault(board.board_id, _GridHistory([], []))

    @staticmethod
    def _placement_snapshot(board: UltraViewBoardState) -> BoardPlacementSnapshot:
        return capture_board_placement(board)

    def _record_grid_transition(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
        *,
        kind: str = "",
    ) -> bool:
        after = self._placement_snapshot(board)
        if after == before:
            return False
        history = self._grid_history(board)
        self._push_history_undo(
            history, _GridHistoryEntry(before, after, kind=str(kind or ""))
        )
        self._clear_history_redo(history)
        self._clear_pending_merge_flags()
        self._after_board_mutation()
        return True

    def _commit_author_mutation(
        self,
        board: UltraViewBoardState,
        mutation: AuthorMutationResult,
        *,
        label: str,
        placement_before: BoardPlacementSnapshot | None = None,
    ) -> bool:
        """Record an already-applied author mutation as one atomic Board edit.

        State owns object validation and mutation; this owner alone decides
        history, dirty state, and the redo fork.  Passing a placement snapshot
        turns a card+author gesture into a single undo entry.
        """
        if not mutation.changed:
            return False
        placement_after = (
            self._placement_snapshot(board) if placement_before is not None else None
        )
        entry = BoardEditEntry(
            str(label or "author-edit"),
            placement_before,
            placement_after,
            tuple(mutation.patches),
        )
        return self._record_board_edit(board, entry)

    def _record_board_edit(
        self, board: UltraViewBoardState, entry: BoardEditEntry
    ) -> bool:
        """Push a reversible author/mixed edit and preserve an existing API."""
        if board_edit_entry_byte_cost(entry) > _BOARD_HISTORY_BYTE_BUDGET:
            # State limits prevent normal strokes reaching this path.  Keeping
            # the edit is safer than a surprise rollback; it simply cannot be
            # retained as an undoable history entry.
            self._after_board_mutation()
            return False
        history = self._grid_history(board)
        self._push_history_undo(history, entry)
        self._clear_history_redo(history)
        # A delayed first-preview aspect correction must only merge into the
        # preceding placement insertion, never replace a newer author patch.
        self._clear_pending_merge_flags()
        self._after_board_mutation()
        return True

    def _on_author_create(self, intent) -> None:
        board = active_board(self._workspace)
        mutation = apply_author_create(board, intent)
        if isinstance(intent, TextCreateIntent):
            label = "text-create"
        elif isinstance(intent, ShapeCreateIntent):
            label = "shape-create"
        elif isinstance(intent, ConnectorCreateIntent):
            label = "connector-create"
        else:
            label = "sticky-create"
        self._publish_author_mutation(board, mutation, label=label)

    def _on_author_update(self, intent) -> None:
        board = active_board(self._workspace)
        mutation = apply_author_update(board, intent)
        if isinstance(intent, TextUpdateIntent):
            label = "text-edit"
        elif isinstance(intent, ShapeUpdateIntent):
            label = "shape-edit"
        elif isinstance(intent, ConnectorUpdateIntent):
            label = "connector-edit"
        else:
            label = "sticky-edit"
        self._publish_author_mutation(board, mutation, label=label)

    def _on_author_delete(self, intent) -> None:
        board = active_board(self._workspace)
        mutation = apply_author_delete(board, intent)
        self._publish_author_mutation(board, mutation, label="author-delete")

    def _on_author_batch(self, intent) -> None:
        board = active_board(self._workspace)
        if isinstance(intent, SelectionDeleteIntent):
            self._on_selection_delete(board, intent)
            return
        if isinstance(intent, SelectionNudgeIntent):
            self._on_selection_nudge(board, intent)
            return
        mutation = apply_author_intent(board, intent)
        labels = {
            AuthorBatchStyleIntent: "author-style",
            AuthorAlignIntent: "author-align",
            AuthorDistributeIntent: "author-distribute",
            AuthorDuplicateIntent: "author-duplicate",
            AuthorLockIntent: "author-lock",
            AuthorZOrderIntent: "author-z-order",
            AuthorNudgeIntent: "author-nudge",
            AuthorPasteIntent: "author-paste",
        }
        self._publish_author_mutation(
            board, mutation, label=labels.get(type(intent), "author-batch")
        )

    def _on_selection_delete(self, board, intent: SelectionDeleteIntent) -> None:
        self._commit_selection_mutation(
            board, plan_selection_delete(board, intent.card_refs, intent.author_ids)
        )

    def _on_selection_nudge(self, board, intent: SelectionNudgeIntent) -> None:
        self._commit_selection_mutation(
            board,
            plan_selection_nudge(
                board, intent.card_refs, intent.author_ids, intent.dx, intent.dy
            ),
        )

    def _commit_selection_mutation(
        self, board, plan: SelectionMutationPlan
    ) -> None:
        if plan.rejected:
            self._toast_grid_warnings(list(plan.warnings))
            return
        for code in plan.warnings:
            self._toast(warning_copy(str(code).split(":", 1)[0]), "warning")
        entry = plan.as_entry()
        if entry is None:
            return
        if not apply_board_edit_entry(board, entry, forward=True):
            return
        self._record_board_edit(board, entry)

    def _publish_author_mutation(
        self,
        board,
        mutation,
        *,
        label: str,
        placement_before=None,
    ) -> None:
        for code in mutation.warnings:
            self._toast(warning_copy(code), "warning")
        if mutation.changed:
            self._commit_author_mutation(
                board, mutation, label=label, placement_before=placement_before
            )

    @staticmethod
    def _history_entry_byte_cost(entry: _GridHistoryEntry | BoardEditEntry) -> int:
        if isinstance(entry, BoardEditEntry):
            return board_edit_entry_byte_cost(entry)
        return board_edit_entry_byte_cost(
            BoardEditEntry(entry.kind, entry.before, entry.after, ())
        )

    def _push_history_undo(
        self, history: _GridHistory, entry: _GridHistoryEntry | BoardEditEntry
    ) -> None:
        history.undo.append(entry)
        history.undo_bytes += self._history_entry_byte_cost(entry)
        while history.undo and (
            len(history.undo) > _PLACEMENT_HISTORY_CAP
            or history.undo_bytes > _BOARD_HISTORY_BYTE_BUDGET
        ):
            removed = history.undo.pop(0)
            history.undo_bytes -= self._history_entry_byte_cost(removed)

    def _push_history_redo(
        self, history: _GridHistory, entry: _GridHistoryEntry | BoardEditEntry
    ) -> None:
        history.redo.append(entry)
        history.redo_bytes += self._history_entry_byte_cost(entry)

    def _clear_history_redo(self, history: _GridHistory) -> None:
        history.redo.clear()
        history.redo_bytes = 0

    def _pop_history_undo(
        self, history: _GridHistory
    ) -> _GridHistoryEntry | BoardEditEntry:
        entry = history.undo.pop()
        history.undo_bytes -= self._history_entry_byte_cost(entry)
        return entry

    def _pop_history_redo(
        self, history: _GridHistory
    ) -> _GridHistoryEntry | BoardEditEntry:
        entry = history.redo.pop()
        history.redo_bytes -= self._history_entry_byte_cost(entry)
        return entry

    def _commit_grid_change(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
        warnings: list[str],
        *,
        lost_cards=(),
        kind: str = "",
    ) -> None:
        if warnings:
            self._toast_grid_warnings(warnings)
            return
        mutation = re_resolve_connector_endpoints(board, lost_card_refs=lost_cards)
        for code in mutation.warnings:
            self._toast(warning_copy(code), "warning")
        if mutation.changed:
            self._commit_author_mutation(
                board,
                mutation,
                label=str(kind or "connector-retarget"),
                placement_before=before,
            )
            return
        self._record_grid_transition(board, before, kind=kind)

    def _toast_grid_warnings(self, warnings: list[str]) -> None:
        codes = {item.split(":", 1)[0] for item in warnings}
        if "grid_collision" in codes:
            self._toast("目标位置与其他卡片重叠", "warning")
            return
        if "invalid_grid_rect" in codes:
            self._toast("目标超出安全区", "warning")
            return
        if "grid_full" in codes:
            self._toast(text_for_key(PLACED_CAP_STILL_UNPLACED), "info")
            return
        if "membership_limit" in codes:
            self._toast(text_for_key(MEMBERSHIP_CAP), "warning")
            return
        if warnings:
            self._toast(str(warnings[0]), "warning")

    def _toast_layout_warnings(self, warnings: list[str]) -> None:
        for item in warnings:
            code, _, detail = item.partition(": ")
            if code == "tray_refilled":
                self._toast(f"已从托盘补位 {detail} 张", "info")
            elif code == "layout_overflow":
                self._toast(f"{detail} 张已移入未放置", "info")

    def _discard_stale_grid_history(self, history: _GridHistory) -> None:
        history.undo.clear()
        history.redo.clear()
        history.undo_bytes = 0
        history.redo_bytes = 0

    @staticmethod
    def _apply_grid_snapshot(
        board: UltraViewBoardState,
        snapshot: BoardPlacementSnapshot,
    ) -> bool:
        return apply_board_placement(board, snapshot)

    def _on_free_grid_undo(self) -> None:
        board = active_board(self._workspace)
        history = self._grid_histories.get(board.board_id)
        if history is None or not history.undo:
            return
        entry = self._pop_history_undo(history)
        restored = (
            self._apply_grid_snapshot(board, entry.before)
            if isinstance(entry, _GridHistoryEntry)
            else apply_board_edit_entry(board, entry, forward=False)
        )
        if not restored:
            self._push_history_undo(history, entry)
            return
        self._cancel_pending_for_board(board.board_id)
        self._push_history_redo(history, entry)
        self._after_board_mutation()

    def _on_free_grid_redo(self) -> None:
        board = active_board(self._workspace)
        history = self._grid_histories.get(board.board_id)
        if history is None or not history.redo:
            return
        entry = self._pop_history_redo(history)
        restored = (
            self._apply_grid_snapshot(board, entry.after)
            if isinstance(entry, _GridHistoryEntry)
            else apply_board_edit_entry(board, entry, forward=True)
        )
        if not restored:
            self._push_history_redo(history, entry)
            return
        self._cancel_pending_for_board(board.board_id)
        self._push_history_undo(history, entry)
        self._after_board_mutation()

    def _insert_span_for_ref(
        self, board: UltraViewBoardState, ref: UltraViewRef
    ) -> tuple[int, int] | None:
        image_size = self._preview_fit_image_size(ref)
        if image_size is None:
            return None
        return self._fitted_insert_span(board, image_size)

    def _insert_span_for_drag(
        self, section: str, view_id: str
    ) -> tuple[int, int] | None:
        if self._inactive():
            return None
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return None
        return self._insert_span_for_ref(active_board(self._workspace), ref)

    def _place_unplaced_on_free_grid(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        *,
        preferred_anchor: GridAnchor | None,
    ) -> None:
        span = self._insert_span_for_ref(board, ref)
        before = self._placement_snapshot(board)
        warnings = place_free_grid_from_unplaced(
            board, ref, preferred_anchor=preferred_anchor, span=span
        )
        self._commit_grid_change(board, before, warnings)
        if warnings:
            return
        if span is None:
            item = free_grid_placement_for(board, ref)
            if item is not None:
                self._register_pending_auto_aspect(board, ref, item.rect)

    def _fitted_insert_span(
        self, board: UltraViewBoardState, image_size: tuple[int, int]
    ) -> tuple[int, int]:
        column_span, row_span = free_grid_default_span(board)
        max_rect = GridRect(0, 0, column_span, row_span)
        fitted = fit_rect_for_aspect(
            max_rect, image_size, screen_grid_metrics(board.free_grid)
        )
        return (fitted.column_span, fitted.row_span)

    def _current_layout_revision(self, board_id: str) -> int:
        return int(self._layout_revision.get(str(board_id), 0))

    def _bump_layout_revision(self, board_id: str) -> None:
        key = str(board_id)
        self._layout_revision[key] = self._current_layout_revision(key) + 1

    def _register_pending_auto_aspect(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        inserted_rect: GridRect,
    ) -> None:
        self._pending_auto_aspect[(board.board_id, ref)] = _PendingAutoAspect(
            board_id=board.board_id,
            ref=ref,
            inserted_rect=inserted_rect,
            layout_revision=self._current_layout_revision(board.board_id),
            merge_add=True,
        )

    def _cancel_pending_for_ref(self, board_id: str, ref: UltraViewRef) -> None:
        self._pending_auto_aspect.pop((str(board_id), ref), None)

    def _cancel_pending_for_board(self, board_id: str) -> None:
        key = str(board_id)
        self._pending_auto_aspect = {
            token_key: token
            for token_key, token in self._pending_auto_aspect.items()
            if token.board_id != key
        }

    def _clear_pending_merge_flags(self) -> None:
        self._pending_auto_aspect = {
            token_key: replace(token, merge_add=False) if token.merge_add else token
            for token_key, token in self._pending_auto_aspect.items()
        }

    def _clear_placement_runtime(self) -> None:
        self._grid_histories.clear()
        self._pending_auto_aspect.clear()
        self._layout_revision.clear()

    def _drop_board_placement_runtime(self, board_id: str) -> None:
        key = str(board_id)
        self._grid_histories.pop(key, None)
        self._layout_revision.pop(key, None)
        self._cancel_pending_for_board(key)

    def _maybe_apply_pending_auto_aspect(self, ref: UltraViewRef) -> None:
        if self._inactive():
            return
        matching = [
            token
            for token in tuple(self._pending_auto_aspect.values())
            if token.ref == ref
        ]
        for token in matching:
            self._apply_one_pending_auto_aspect(token)

    def _apply_one_pending_auto_aspect(self, token: _PendingAutoAspect) -> None:
        self._pending_auto_aspect.pop((token.board_id, token.ref), None)
        board = next(
            (
                item
                for item in self._workspace.boards
                if item.board_id == token.board_id
            ),
            None,
        )
        if board is None or board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return
        if token.layout_revision != self._current_layout_revision(board.board_id):
            return
        item = free_grid_placement_for(board, token.ref)
        if item is None:
            return
        if (
            item.rect.column_span != token.inserted_rect.column_span
            or item.rect.row_span != token.inserted_rect.row_span
        ):
            return
        image_size = self._preview_fit_image_size(token.ref)
        if image_size is None:
            return
        cap = GridRect(
            item.rect.column,
            item.rect.row,
            token.inserted_rect.column_span,
            token.inserted_rect.row_span,
        )
        wanted = fit_rect_for_aspect(
            cap, image_size, screen_grid_metrics(board.free_grid)
        )
        if wanted == item.rect:
            return
        warnings = set_free_grid_rect(board, token.ref, wanted)
        if warnings:
            return
        after = self._placement_snapshot(board)
        if token.merge_add:
            history = self._grid_histories.get(board.board_id)
            if (
                history is not None
                and history.undo
                and isinstance(history.undo[-1], _GridHistoryEntry)
            ):
                last = history.undo[-1]
                replacement = _GridHistoryEntry(
                    last.before, after, kind=last.kind
                )
                history.undo[-1] = replacement
                history.undo_bytes += (
                    self._history_entry_byte_cost(replacement)
                    - self._history_entry_byte_cost(last)
                )
                self._clear_history_redo(history)
        self._after_board_mutation()

    def _on_board_name(self, name: str) -> None:
        if self._inactive():
            return
        cleaned = str(name or "").strip() or DEFAULT_BOARD_NAME
        board = active_board(self._workspace)
        if board.name == cleaned:
            return
        warnings = rename_board(self._workspace, board.board_id, cleaned)
        if warnings:
            for warning in warnings:
                logger.warning("UltraView board rename: %s", warning)
            return
        self._after_board_mutation()

    def _on_create_board(self) -> None:
        if create_board(self._workspace) is None:
            self._toast("最多创建 20 个 Board", "info")
            return
        self._after_board_mutation()

    def _on_duplicate_board(self, board_id: str) -> None:
        if len(self._workspace.boards) >= MAX_UI_BOARDS:
            self._toast("最多创建 20 个 Board", "info")
            return
        if duplicate_board(self._workspace, board_id) is not None:
            self._after_board_mutation()

    def _on_rename_board(self, board_id: str, name: str) -> None:
        if not rename_board(self._workspace, board_id, name):
            self._after_board_mutation()

    def _on_delete_board(self, board_id: str) -> None:
        warnings = delete_board(self._workspace, board_id)
        if warnings and warnings[0] == "last_board_retained":
            self._toast("至少保留一个 Board", "info")
            return
        self._drop_board_placement_runtime(str(board_id))
        self._after_board_mutation()

    def _on_reorder_board(self, board_id: str, index: int) -> None:
        warnings = reorder_board(self._workspace, board_id, index)
        # Success is ``[]``. Do not refresh on success: QTabBar already moved
        # the tab, and rebuilding inside ``tabMoved`` crashes. Failure resyncs
        # from workspace; BoardSwitcher defers that rebuild off the signal.
        if warnings:
            self._after_board_mutation()

    def _on_select_board(self, board_id: str) -> None:
        if not set_active_board(self._workspace, board_id):
            self._prioritize_sidecar_queue()
            self._after_board_mutation()

    def _on_show_titles(self, checked: bool) -> None:
        set_presentation_flags(active_board(self._workspace), show_titles=checked)
        self._after_board_mutation()

    def _on_show_sources(self, checked: bool) -> None:
        set_presentation_flags(active_board(self._workspace), show_sources=checked)
        self._after_board_mutation()

    def _on_show_card_actions(self, checked: bool) -> None:
        set_workspace_show_card_actions(self._workspace, checked)
        # This preference only changes UltraView chrome.  Do not route it
        # through board mutation/capture/viewport paths.
        self.refresh_page()

    def _on_shift_slot(self, section: str, view_id: str, delta: int) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        placement = placement_for(board, ref)
        if placement is None:
            return
        slots = layout_slots(board.layout_id)
        try:
            index = slots.index(placement.slot_id)
        except ValueError:
            return
        target = slots[(index + int(delta)) % len(slots)]
        before = self._placement_snapshot(board)
        swap_slots(board, placement.slot_id, target)
        self._commit_grid_change(board, before, [])

    def _on_set_primary(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        placement = placement_for(board, ref)
        if placement is None:
            return
        slots = layout_slots(board.layout_id)
        primary = "primary" if "primary" in slots else slots[0]
        if placement.slot_id == primary:
            return
        before = self._placement_snapshot(board)
        swap_slots(board, placement.slot_id, primary)
        self._commit_grid_change(board, before, [])
