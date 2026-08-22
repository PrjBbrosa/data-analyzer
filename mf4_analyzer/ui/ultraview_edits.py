"""Qt-free UltraView selection mutation planning.

Card rect validation lives in ``ultraview_state``; author patches are planned
in ``author_edits``. This module combines them into one accept-or-reject plan
without writing the live Board until ``commit_selection_plan``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    plan_author_delete,
    plan_author_nudge,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_selection import (
    is_locked,
    is_unknown,
    item_id,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    SelectionDeleteIntent,
    SelectionNudgeIntent,
)
from mf4_analyzer.ui.ultraview_state import (
    BoardEditEntry,
    BoardPlacementSnapshot,
    CardPlacement,
    FreeGridPlacement,
    FreeGridRectPlan,
    GridRect,
    ObjectPatch,
    UltraViewBoardState,
    UltraViewRef,
    apply_board_edit_entry,
    capture_board_placement,
    free_grid_placement_for,
    move_to_unplaced,
    plan_free_grid_rects,
    set_free_grid_rects,
)


@dataclass(frozen=True)
class SelectionMutationPlan:
    """One mixed card+author intent: apply entirely or not at all."""

    operation: str
    label: str
    placement_before: BoardPlacementSnapshot | None
    placement_after: BoardPlacementSnapshot | None
    author_patches: tuple[ObjectPatch, ...]
    warnings: tuple[str, ...]
    affected_card_refs: tuple[UltraViewRef, ...]
    affected_author_ids: tuple[str, ...]
    skipped_locked: tuple[str, ...]
    skipped_unknown: tuple[str, ...]
    rejected: bool = False

    def as_entry(self) -> BoardEditEntry | None:
        if self.rejected:
            return None
        before = self.placement_before
        after = self.placement_after
        if before == after:
            before = after = None
        if before is None and not self.author_patches:
            return None
        return BoardEditEntry(self.label, before, after, self.author_patches)


def plan_selection_nudge(
    board: UltraViewBoardState,
    card_refs: Iterable[UltraViewRef],
    author_ids: Iterable[str],
    dx: float,
    dy: float,
) -> SelectionMutationPlan:
    """Plan a mixed nudge. Does not write ``board``."""
    refs = tuple(card_refs)
    ids = tuple(str(object_id) for object_id in author_ids)
    before = capture_board_placement(board)
    parsed: list[tuple[UltraViewRef, GridRect]] = []
    for ref in refs:
        current = free_grid_placement_for(board, ref)
        if current is None:
            continue
        parsed.append(
            (
                ref,
                GridRect(
                    int(round(current.rect.column + dx)),
                    int(round(current.rect.row + dy)),
                    current.rect.column_span,
                    current.rect.row_span,
                ),
            )
        )
    label = "mixed-nudge" if parsed else "author-nudge"
    skipped_locked, skipped_unknown = _skipped_authors(board, ids)
    if parsed:
        rect_plan = plan_free_grid_rects(board, parsed)
        if not rect_plan.accepted:
            return _rejected_nudge(
                label, before, rect_plan.warnings, skipped_locked, skipped_unknown
            )
        placements = _proposed_placements(board, rect_plan)
        after = _placement_after_rects(board, parsed)
    else:
        placements = None
        after = before
    author = plan_author_nudge(board, ids, dx, dy, placements=placements)
    return SelectionMutationPlan(
        operation="nudge",
        label=label,
        placement_before=before,
        placement_after=after,
        author_patches=tuple(author.patches),
        warnings=tuple(author.warnings),
        affected_card_refs=tuple(ref for ref, _rect in parsed),
        affected_author_ids=_updated_author_ids(author.patches),
        skipped_locked=skipped_locked,
        skipped_unknown=skipped_unknown,
        rejected=False,
    )


def plan_selection_delete(
    board: UltraViewBoardState,
    card_refs: Iterable[UltraViewRef],
    author_ids: Iterable[str],
) -> SelectionMutationPlan:
    """Plan a mixed delete. Does not write ``board``."""
    refs = tuple(card_refs)
    ids = tuple(str(object_id) for object_id in author_ids)
    before = capture_board_placement(board)
    staged = _placement_clone(board)
    card_warnings: list[str] = []
    for ref in refs:
        card_warnings.extend(move_to_unplaced(staged, ref))
    if card_warnings:
        return SelectionMutationPlan(
            operation="delete",
            label="mixed-delete",
            placement_before=before,
            placement_after=before,
            author_patches=(),
            warnings=tuple(card_warnings),
            affected_card_refs=(),
            affected_author_ids=(),
            skipped_locked=(),
            skipped_unknown=(),
            rejected=True,
        )
    after = capture_board_placement(staged)
    author = plan_author_delete(board, ids, lost_card_refs=refs)
    return SelectionMutationPlan(
        operation="delete",
        label="mixed-delete" if refs else "author-delete",
        placement_before=before,
        placement_after=after,
        author_patches=tuple(author.patches),
        warnings=tuple(author.warnings),
        affected_card_refs=refs,
        affected_author_ids=_deleted_author_ids(author.patches),
        skipped_locked=(),
        skipped_unknown=(),
        rejected=False,
    )


def commit_selection_plan(board: UltraViewBoardState, plan: SelectionMutationPlan) -> bool:
    """Write an accepted plan once. History and dirty stay with the coordinator."""
    entry = plan.as_entry()
    if entry is None:
        return False
    return apply_board_edit_entry(board, entry, forward=True)


def commit_selection_nudge(
    board: UltraViewBoardState, intent: SelectionNudgeIntent
) -> SelectionMutationPlan:
    plan = plan_selection_nudge(board, intent.card_refs, intent.author_ids, intent.dx, intent.dy)
    if not plan.rejected:
        commit_selection_plan(board, plan)
    return plan


def commit_selection_delete(
    board: UltraViewBoardState, intent: SelectionDeleteIntent
) -> SelectionMutationPlan:
    plan = plan_selection_delete(board, intent.card_refs, intent.author_ids)
    if not plan.rejected:
        commit_selection_plan(board, plan)
    return plan


def _rejected_nudge(
    label: str,
    before: BoardPlacementSnapshot,
    warnings: tuple[str, ...],
    skipped_locked: tuple[str, ...],
    skipped_unknown: tuple[str, ...],
) -> SelectionMutationPlan:
    return SelectionMutationPlan(
        operation="nudge",
        label=label,
        placement_before=before,
        placement_after=before,
        author_patches=(),
        warnings=tuple(warnings),
        affected_card_refs=(),
        affected_author_ids=(),
        skipped_locked=skipped_locked,
        skipped_unknown=skipped_unknown,
        rejected=True,
    )


def _skipped_authors(board, author_ids: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    wanted = set(author_ids)
    locked: list[str] = []
    unknown: list[str] = []
    for item in board.author_objects:
        oid = item_id(item)
        if oid not in wanted:
            continue
        if is_unknown(item):
            unknown.append(oid)
        elif is_locked(item):
            locked.append(oid)
    return tuple(locked), tuple(unknown)


def _updated_author_ids(patches: tuple[ObjectPatch, ...]) -> tuple[str, ...]:
    return tuple(
        patch.object_id
        for patch in patches
        if patch.before is not None and patch.after is not None
    )


def _deleted_author_ids(patches: tuple[ObjectPatch, ...]) -> tuple[str, ...]:
    return tuple(patch.object_id for patch in patches if patch.after is None)


def _proposed_placements(board, rect_plan: FreeGridRectPlan) -> list[FreeGridPlacement]:
    proposed = dict(rect_plan.proposed)
    return [
        FreeGridPlacement(item.ref, proposed.get(item.ref, item.rect))
        for item in board.free_grid
    ]


def _placement_clone(board: UltraViewBoardState) -> UltraViewBoardState:
    return replace(
        board,
        placements=[CardPlacement(item.slot_id, item.ref) for item in board.placements],
        unplaced=list(board.unplaced),
        free_grid=[FreeGridPlacement(item.ref, item.rect) for item in board.free_grid],
        author_objects=list(board.author_objects),
    )


def _placement_after_rects(
    board: UltraViewBoardState, updates: list[tuple[UltraViewRef, GridRect]]
) -> BoardPlacementSnapshot:
    staged = _placement_clone(board)
    set_free_grid_rects(staged, updates)
    return capture_board_placement(staged)
