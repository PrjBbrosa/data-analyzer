"""PinCommands request results: create, dedupe, unpin, close, expand, axis-edit."""
from __future__ import annotations

from dataclasses import replace

from PyQt5.QtCore import QPoint, Qt

from mf4_analyzer.ui.chart_stack.pinning import commands as commands_mod
from mf4_analyzer.ui.chart_stack.pinning.commands import (
    PinCommandResult,
    PinCommands,
    PinnedAxisEdit,
)
from mf4_analyzer.ui.cursor_display_model import PinnedCursorSample
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


def _draft(x=1.25, domain="time", mode="single", **extra):
    payload = {
        "mode": mode,
        "domain": domain,
        "x_unit": "s" if domain == "time" else "Hz",
        "bindings": [{"fid": "f0", "channel": "torque"}],
        "presentation": "full",
        "panel_expanded": False,
    }
    if mode == "single":
        payload["x"] = x
    else:
        payload["ax"] = extra.get("ax", 1.0)
        payload["bx"] = extra.get("bx", 2.0)
    payload.update(extra)
    _collection, intent = next_record(empty_collection(), payload)
    return intent


def _committed(x=1.25, **extra):
    intent = _draft(x=x, **extra)
    collection, record = next_record(empty_collection(), intent)
    return collection, record


def _sample(x=1.25):
    return PinnedCursorSample(domain="time", mode="single", x=x)


def _edit(collection, record, *, generation=(1, 1), bounds=(0.0, 10.0), scope=None):
    return PinnedAxisEdit(
        scope_id=str(scope if scope is not None else collection.scope_id),
        record_id=record.record_id,
        endpoint="x",
        original=record,
        generation=generation,
        visible_bounds=bounds,
        endpoint_global=QPoint(40, 8),
        last_pointer_global=QPoint(40, 8),
    )


def test_create_requests_one_commit_and_intent():
    cmds = PinCommands()
    intent = _draft()
    result = cmds.create_pin(collection=None, intent=intent, sample=_sample())
    assert result.action == "create"
    assert result.mark_intent is True
    assert result.consume_live is True
    assert result.clear_reserved is True
    assert result.collection is not None
    assert len(result.collection.records) == 1
    assert result.record.ordinal == 1
    assert result.record.panel_expanded is False


def test_duplicate_does_not_request_commit_or_intent():
    cmds = PinCommands()
    collection, existing = _committed()
    result = cmds.create_pin(
        collection=collection, intent=_draft(x=existing.x), sample=_sample(),
    )
    assert result.action == "duplicate"
    assert result.mark_intent is False
    assert result.collection is None
    assert result.duplicate_record_id == existing.record_id
    assert result.duplicate_ordinal == existing.ordinal
    assert result.feedback == f"P{existing.ordinal} 已在此位置"
    assert result.consume_live is True


def test_reserved_ordinal_is_reused_on_matching_recapture():
    cmds = PinCommands()
    collection, existing = _committed()
    after_unpin = cmds.unpin(collection, existing)
    result = cmds.create_pin(
        collection=after_unpin.collection,
        intent=existing,
        sample=_sample(existing.x),
        reserved_ordinal=after_unpin.reserved_ordinal,
        reserved_intent=after_unpin.reserved_intent,
    )
    assert result.action == "create"
    assert result.record.ordinal == existing.ordinal
    assert result.mark_intent is True


def test_unpin_and_close_request_collection_update_without_undo():
    cmds = PinCommands()
    collection, existing = _committed()
    unpinned = cmds.unpin(collection, existing)
    assert unpinned.action == "unpin"
    assert unpinned.mark_intent is True
    assert unpinned.collection.records == ()
    assert unpinned.reserved_ordinal == existing.ordinal
    assert unpinned.set_reserved is True
    assert unpinned.live_suppressed is False
    assert unpinned.restore_live is True
    assert unpinned.feedback == f"P{existing.ordinal} 已取消固定"

    collection, existing = _committed()
    closed = cmds.close(collection, existing)
    assert closed.action == "close"
    assert closed.mark_intent is True
    assert closed.collection.records == ()
    assert closed.set_reserved is False
    assert closed.restore_live is False
    assert closed.feedback == f"已关闭 P{existing.ordinal}"

    assert not hasattr(cmds, "undo_close")
    assert not hasattr(cmds, "undo")
    assert not hasattr(commands_mod, "PinUndoStack")
    assert not hasattr(commands_mod, "_ClosedPin")
    assert not hasattr(PinCommandResult, "undo")


def test_toggle_expand_flips_panel_and_requests_intent():
    cmds = PinCommands()
    collection, existing = _committed()
    assert existing.panel_expanded is False
    result = cmds.toggle_panel(collection, existing)
    assert result.action == "toggle"
    assert result.mark_intent is True
    assert result.record.panel_expanded is True
    assert result.collection.records[0].panel_expanded is True
    collapsed = cmds.toggle_panel(result.collection, result.record)
    assert collapsed.record.panel_expanded is False
    only_collapse = cmds.collapse_panel(result.collection, result.record)
    assert only_collapse.action == "collapse"
    assert only_collapse.record.panel_expanded is False
    assert only_collapse.mark_intent is True
    already = cmds.collapse_panel(only_collapse.collection, only_collapse.record)
    assert already.action == "noop"
    assert already.mark_intent is False
    assert already.collection is None


def test_preview_and_cancel_do_not_request_commit():
    cmds = PinCommands()
    collection, record = _committed()
    edit = _edit(collection, record)
    preview = cmds.accumulate_preview_pointer(edit, QPoint(48, 8), Qt.NoModifier)
    assert preview.action == "edit_preview"
    assert preview.mark_intent is False
    assert preview.collection is None
    candidate = replace(record, x=2.5)
    accepted = cmds.accept_preview_candidate(edit, candidate, _sample(2.5))
    assert accepted.mark_intent is False
    assert accepted.collection is None
    assert accepted.preview_intent.x == 2.5


def test_identical_coords_do_not_commit():
    cmds = PinCommands()
    collection, record = _committed()
    edit = _edit(collection, record)
    edit.candidate_intent = record
    edit.candidate_sample = _sample(record.x)
    result = cmds.decide_axis_commit(
        edit,
        collection=collection,
        current_intent=record,
        generation=edit.generation,
        visible_bounds=edit.visible_bounds,
    )
    assert result.action == "edit_noop"
    assert result.mark_intent is False
    assert result.collection is None
    assert result.restore_original is True


def test_successful_commit_requested_once():
    cmds = PinCommands()
    collection, record = _committed()
    edit = _edit(collection, record)
    moved = replace(record, x=3.5)
    edit.candidate_intent = moved
    edit.candidate_sample = _sample(3.5)
    result = cmds.decide_axis_commit(
        edit,
        collection=collection,
        current_intent=record,
        generation=edit.generation,
        visible_bounds=edit.visible_bounds,
    )
    assert result.action == "edit_commit"
    assert result.mark_intent is True
    assert result.collection.records[0].x == 3.5
    assert result.emit_axis_settled is True
    assert result.clear_axis_edit is True


def test_stale_generation_and_scope_are_rejected():
    cmds = PinCommands()
    collection, record = _committed()
    edit = _edit(collection, record, generation=(1, 1))
    edit.candidate_intent = replace(record, x=4.0)
    edit.candidate_sample = _sample(4.0)
    stale_gen = cmds.decide_axis_commit(
        edit,
        collection=collection,
        current_intent=record,
        generation=(9, 9),
        visible_bounds=edit.visible_bounds,
    )
    assert stale_gen.action == "edit_stale"
    assert stale_gen.mark_intent is False
    assert stale_gen.collection is None

    collection = replace(collection, scope_id="other-scope")
    stale_scope = cmds.decide_axis_commit(
        edit,
        collection=collection,
        current_intent=record,
        generation=edit.generation,
        visible_bounds=edit.visible_bounds,
    )
    assert stale_scope.action == "edit_stale"
    assert stale_scope.mark_intent is False


def test_begin_axis_edit_does_not_mark_intent():
    cmds = PinCommands()
    _collection, record = _committed()
    result = cmds.begin_axis_edit(
        scope_id="scope-a",
        record_id=record.record_id,
        endpoint="x",
        original=record,
        generation=(1, 1),
        visible_bounds=(0.0, 10.0),
        endpoint_global=QPoint(10, 4),
        pointer_global=QPoint(10, 4),
    )
    assert result.action == "edit_begin"
    assert result.mark_intent is False
    assert result.start_axis_edit is True
    assert isinstance(result.axis_edit, PinnedAxisEdit)


def test_commands_have_no_qt_signal_emit_surface():
    cmds = PinCommands()
    assert not hasattr(cmds, "intent_changed")
    assert not hasattr(cmds, "pin_feedback")
    assert not hasattr(PinCommands, "intent_changed")
    # Result objects are data, not a second emission path.
    dummy = PinCommandResult(action="noop")
    assert dummy.mark_intent is False
