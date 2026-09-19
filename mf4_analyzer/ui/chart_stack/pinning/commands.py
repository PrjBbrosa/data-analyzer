"""Pin request logic. Returns command results; never writes collection or emits.

Temporary axis-edit state lives here conceptually. Persistent collection
writes and ``intent_changed`` stay on the controller façade.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from PyQt5.QtCore import QPoint, Qt

from ...cursor_display_model import PinnedCursorSample
from ...pinned_cursor_facts import _finite
from ...pinned_cursor_state import (
    PinnedCursorCollection,
    PinnedCursorIntent,
    captures_equal,
    coords_equal,
    empty_collection,
    next_record,
    remove_record,
)


@dataclass
class PinnedAxisEdit:
    """Uncommitted bottom-handle edit owned by exactly one canvas owner."""

    scope_id: str
    record_id: str
    endpoint: str
    original: PinnedCursorIntent
    generation: tuple
    visible_bounds: tuple[float, float]
    endpoint_global: QPoint
    last_pointer_global: QPoint
    effective_dx: float = 0.0
    pending_global: QPoint | None = None
    candidate_intent: PinnedCursorIntent | None = None
    candidate_sample: PinnedCursorSample | None = None


@dataclass(frozen=True)
class PinCommandResult:
    """Immutable request for the controller to apply.

    ``mark_intent`` is the only way a command asks for ``intent_changed``.
    Commands never emit that signal themselves.
    """

    action: str
    mark_intent: bool = False
    collection: PinnedCursorCollection | None = None
    record: PinnedCursorIntent | None = None
    sample: object | None = None
    feedback: str | None = None
    duplicate_record_id: str | None = None
    duplicate_ordinal: int | None = None
    reserved_ordinal: int | None = None
    reserved_intent: object = None
    set_reserved: bool = False
    clear_reserved: bool = False
    live_suppressed: bool | None = None
    dual_hidden_placement: object = None
    set_dual_hidden_placement: bool = False
    consume_live: bool = False
    restore_live: bool = False
    restore_placement: dict | None = None
    axis_edit: PinnedAxisEdit | None = None
    clear_axis_edit: bool = False
    restore_original: bool = False
    emit_axis_settled: bool = False
    start_axis_edit: bool = False
    preview_intent: PinnedCursorIntent | None = None
    preview_sample: object | None = None


class PinCommands:
    """Create / dedupe / unpin / close / expand / axis-edit decisions."""

    @staticmethod
    def endpoint_value(intent, endpoint):
        if intent is None:
            return None
        if intent.mode == "single" and endpoint == "x":
            return _finite(intent.x)
        if intent.mode == "dual" and endpoint == "a":
            return _finite(intent.ax)
        if intent.mode == "dual" and endpoint == "b":
            return _finite(intent.bx)
        return None

    @staticmethod
    def with_endpoint_value(intent, endpoint, value):
        value = _finite(value)
        if value is None:
            return None
        if intent.mode == "single" and endpoint == "x":
            return replace(intent, x=value)
        if intent.mode == "dual" and endpoint == "a":
            return replace(intent, ax=value)
        if intent.mode == "dual" and endpoint == "b":
            return replace(intent, bx=value)
        return None

    @staticmethod
    def sample_endpoint_value(sample, endpoint):
        if sample is None:
            return None
        if endpoint == "x":
            return _finite(getattr(sample, "x", None))
        if endpoint == "a":
            return _finite(getattr(sample, "ax", None))
        if endpoint == "b":
            return _finite(getattr(sample, "bx", None))
        return None

    @staticmethod
    def axis_bounds_equal(left, right) -> bool:
        return (
            isinstance(left, tuple) and isinstance(right, tuple)
            and len(left) == 2 and len(right) == 2
            and coords_equal(left[0], right[0])
            and coords_equal(left[1], right[1])
        )

    def find_duplicate(self, collection, intent):
        if collection is None:
            return None
        for existing in collection.records:
            if captures_equal(existing, intent):
                return existing
        return None

    def commit_record(
        self, collection, intent, *, reserved_ordinal=None, reserved_intent=None,
    ):
        if collection is None:
            collection = empty_collection()
        reserved = reserved_ordinal
        if (
            reserved is not None
            and reserved_intent is not None
            and captures_equal(reserved_intent, intent)
            and all(item.ordinal != reserved for item in collection.records)
        ):
            record = replace(
                intent,
                record_id=str(uuid4()),
                ordinal=int(reserved),
            )
            collection = replace(
                collection,
                records=collection.records + (record,),
            )
            return collection, record
        return next_record(collection, intent)

    def create_pin(
        self,
        *,
        collection,
        intent,
        sample=None,
        reserved_ordinal=None,
        reserved_intent=None,
    ) -> PinCommandResult:
        duplicate = self.find_duplicate(collection, intent)
        if duplicate is not None:
            return PinCommandResult(
                action="duplicate",
                record=duplicate,
                duplicate_record_id=duplicate.record_id,
                duplicate_ordinal=duplicate.ordinal,
                feedback=f"P{duplicate.ordinal} 已在此位置",
                consume_live=True,
                mark_intent=False,
            )
        collection, record = self.commit_record(
            collection, intent,
            reserved_ordinal=reserved_ordinal,
            reserved_intent=reserved_intent,
        )
        return PinCommandResult(
            action="create",
            collection=collection,
            record=record,
            sample=sample,
            clear_reserved=True,
            consume_live=True,
            live_suppressed=True,
            mark_intent=True,
        )

    def unpin(self, collection, intent) -> PinCommandResult:
        if collection is None or intent is None:
            return PinCommandResult(action="reject", mark_intent=False)
        restore_placement = None
        if intent.mode == "dual":
            restore_placement = {"ax": intent.ax, "bx": intent.bx}
        return PinCommandResult(
            action="unpin",
            collection=remove_record(collection, intent.record_id),
            record=intent,
            reserved_ordinal=intent.ordinal,
            reserved_intent=intent,
            set_reserved=True,
            live_suppressed=False,
            dual_hidden_placement=intent,
            set_dual_hidden_placement=True,
            restore_live=True,
            restore_placement=restore_placement,
            mark_intent=True,
            feedback=f"P{intent.ordinal} 已取消固定",
        )

    def close(self, collection, intent) -> PinCommandResult:
        if collection is None or intent is None:
            return PinCommandResult(action="reject", mark_intent=False)
        return PinCommandResult(
            action="close",
            collection=remove_record(collection, intent.record_id),
            record=intent,
            mark_intent=True,
            feedback=f"已关闭 P{intent.ordinal}",
        )

    def toggle_panel(self, collection, intent) -> PinCommandResult:
        if collection is None or intent is None:
            return PinCommandResult(action="reject", mark_intent=False)
        updated = replace(
            intent, panel_expanded=intent.panel_expanded is not True,
        )
        collection = replace(
            collection,
            records=tuple(
                updated if item.record_id == intent.record_id else item
                for item in collection.records
            ),
        )
        return PinCommandResult(
            action="toggle",
            collection=collection,
            record=updated,
            mark_intent=True,
        )

    def begin_axis_edit(
        self,
        *,
        scope_id,
        record_id,
        endpoint,
        original,
        generation,
        visible_bounds,
        endpoint_global,
        pointer_global,
    ) -> PinCommandResult:
        edit = PinnedAxisEdit(
            scope_id=str(scope_id),
            record_id=str(record_id),
            endpoint=str(endpoint),
            original=original,
            generation=generation,
            visible_bounds=visible_bounds,
            endpoint_global=QPoint(endpoint_global),
            last_pointer_global=QPoint(pointer_global),
        )
        return PinCommandResult(
            action="edit_begin",
            axis_edit=edit,
            start_axis_edit=True,
            mark_intent=False,
        )

    def accumulate_preview_pointer(self, edit, global_pos, modifiers) -> PinCommandResult:
        global_pos = QPoint(global_pos)
        delta = global_pos.x() - edit.last_pointer_global.x()
        if modifiers & Qt.ShiftModifier:
            delta *= 0.1
        edit.effective_dx += float(delta)
        edit.last_pointer_global = global_pos
        edit.pending_global = QPoint(
            int(round(edit.endpoint_global.x() + edit.effective_dx)),
            edit.endpoint_global.y(),
        )
        return PinCommandResult(action="edit_preview", axis_edit=edit, mark_intent=False)

    def accept_preview_candidate(self, edit, candidate, sample) -> PinCommandResult:
        if candidate is None:
            return PinCommandResult(action="edit_preview", axis_edit=edit, mark_intent=False)
        edit.candidate_intent = candidate
        edit.candidate_sample = sample
        return PinCommandResult(
            action="edit_preview",
            axis_edit=edit,
            preview_intent=candidate,
            preview_sample=sample,
            mark_intent=False,
        )

    def axis_edit_is_valid(
        self, edit, *, scope_id, current_intent, generation, visible_bounds,
    ) -> bool:
        if edit is None:
            return False
        if str(scope_id or "") != edit.scope_id:
            return False
        if current_intent is None or current_intent.domain != edit.original.domain:
            return False
        if not coords_equal(
            self.endpoint_value(current_intent, edit.endpoint),
            self.endpoint_value(edit.original, edit.endpoint),
        ):
            return False
        if generation != edit.generation:
            return False
        return self.axis_bounds_equal(visible_bounds, edit.visible_bounds)

    def decide_axis_commit(
        self,
        edit,
        *,
        collection,
        current_intent,
        generation,
        visible_bounds,
    ) -> PinCommandResult:
        if not self.axis_edit_is_valid(
            edit,
            scope_id=str(getattr(collection, "scope_id", "") or ""),
            current_intent=current_intent,
            generation=generation,
            visible_bounds=visible_bounds,
        ):
            return PinCommandResult(
                action="edit_stale",
                record=edit.original if edit is not None else None,
                clear_axis_edit=True,
                restore_original=True,
                emit_axis_settled=True,
                mark_intent=False,
            )
        candidate = edit.candidate_intent
        sample = edit.candidate_sample
        original = edit.original
        if candidate is None or sample is None or coords_equal(
            self.endpoint_value(candidate, edit.endpoint),
            self.endpoint_value(original, edit.endpoint),
        ):
            return PinCommandResult(
                action="edit_noop",
                record=original,
                clear_axis_edit=True,
                restore_original=True,
                emit_axis_settled=True,
                mark_intent=False,
            )
        updated = replace(
            collection,
            records=tuple(
                candidate if item.record_id == edit.record_id else item
                for item in collection.records
            ),
        )
        return PinCommandResult(
            action="edit_commit",
            collection=updated,
            record=candidate,
            sample=sample,
            clear_axis_edit=True,
            emit_axis_settled=True,
            mark_intent=True,
        )

    def decide_nudge_commit(
        self, *, collection, original, endpoint, candidate, sample,
    ) -> PinCommandResult:
        if candidate is None or sample is None or coords_equal(
            self.endpoint_value(candidate, endpoint),
            self.endpoint_value(original, endpoint),
        ):
            return PinCommandResult(action="edit_noop", mark_intent=False)
        updated = replace(
            collection,
            records=tuple(
                candidate if item.record_id == original.record_id else item
                for item in collection.records
            ),
        )
        return PinCommandResult(
            action="edit_commit",
            collection=updated,
            record=candidate,
            sample=sample,
            mark_intent=True,
        )

    def requested_endpoint(self, intent, endpoint, raw_value, bounds):
        value = _finite(raw_value)
        if value is None or bounds is None:
            return None
        value = max(bounds[0], min(value, bounds[1]))
        return self.with_endpoint_value(intent, endpoint, value)

    def accept_endpoint_sample(self, requested, endpoint, sample):
        if requested is None or sample is None:
            return None, None
        accepted = self.sample_endpoint_value(sample, endpoint)
        candidate = self.with_endpoint_value(requested, endpoint, accepted)
        if candidate is None:
            return None, None
        return candidate, sample
