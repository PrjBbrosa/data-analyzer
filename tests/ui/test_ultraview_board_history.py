"""Qt-free and coordinator history for UltraView author objects."""
from __future__ import annotations

from dataclasses import replace

from mf4_analyzer.ui import ultraview_state as uvs
from mf4_analyzer.ui.main_window import MainWindow


def _sticky(object_id: str, *, text: str = "便签") -> uvs.StickyObject:
    return uvs.StickyObject(
        object_id=object_id,
        kind="sticky",
        box=uvs.BoardBox(0, 0, 2, 2),
        text=text,
        palette="yellow",
        shape="square",
        font_size="auto",
    )


def _stroke(object_id: str) -> uvs.StrokeObject:
    return uvs.StrokeObject(
        object_id=object_id,
        kind="stroke",
        points=(uvs.BoardPoint(0, 0), uvs.BoardPoint(1, 1)),
        tool="pen",
        palette="ink",
        width_px_100=3,
    )


def test_author_create_delete_reorder_lock_and_style_patches_round_trip():
    board = uvs.default_board()
    first = uvs.create_author_object(board, _sticky("first"))
    second = uvs.create_author_object(board, _sticky("second"))
    assert first.changed and second.changed
    assert [item.object_id for item in board.author_objects] == ["first", "second"]

    reordered = uvs.reorder_author_object(board, "second", 0)
    styled = uvs.update_author_object(
        board, "second", replace(board.author_objects[0], text="已编辑", palette="blue")
    )
    locked = uvs.set_author_locked(board, "second", True)
    deleted = uvs.delete_author_objects(board, ("first",))
    assert [item.object_id for item in board.author_objects] == ["second"]
    assert board.author_objects[0].locked is True
    assert board.author_objects[0].text == "已编辑"

    for mutation in (deleted, locked, styled, reordered):
        assert uvs.apply_author_patches(board, mutation.patches, forward=False) is True
    assert [item.object_id for item in board.author_objects] == ["first", "second"]
    assert board.author_objects[1].text == "便签"
    for mutation in (reordered, styled, locked, deleted):
        assert uvs.apply_author_patches(board, mutation.patches, forward=True) is True
    assert [item.object_id for item in board.author_objects] == ["second"]


def test_author_patch_failure_is_atomic_and_leaves_board_unchanged():
    board = uvs.default_board()
    assert uvs.create_author_object(board, _sticky("safe")).changed
    before = uvs.board_to_payload(board)
    broken = uvs.ObjectPatch(
        object_id="bad",
        before=None,
        after={"id": "bad", "kind": "sticky", "box": {"x": 0, "y": 0, "width": 0, "height": 1}},
        before_index=None,
        after_index=1,
    )
    assert uvs.apply_author_patches(board, (broken,), forward=True) is False
    assert uvs.board_to_payload(board) == before


def test_eraser_sweep_is_one_board_entry_and_redo_fork_clears_redo(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    board = uv.board
    created = uvs.create_author_object(board, _stroke("one"))
    created2 = uvs.create_author_object(board, _stroke("two"))
    assert uv._commit_author_mutation(board, created, label="stroke")
    assert uv._commit_author_mutation(board, created2, label="stroke")
    erased = uvs.delete_author_objects(board, ("one", "two"))
    assert len(erased.patches) == 2
    assert uv._commit_author_mutation(board, erased, label="eraser")
    history = uv._grid_histories[board.board_id]
    assert isinstance(history.undo[-1], uvs.BoardEditEntry)
    assert len(history.undo[-1].object_patches) == 2

    uv._on_free_grid_undo()
    assert [item.object_id for item in board.author_objects] == ["one", "two"]
    branched = uvs.create_author_object(board, _sticky("branch"))
    assert uv._commit_author_mutation(board, branched, label="create")
    assert history.redo == []


def test_mixed_placement_and_author_entry_undoes_atomically(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    board = uv.board
    ref = uvs.make_ref("time", "mixed-card")
    assert uvs.add_ref(board, ref) == []
    placement_before = uv._placement_snapshot(board)
    created = uvs.create_author_object(board, _sticky("mixed"))
    assert uvs.set_free_grid_rect(board, ref, uvs.GridRect(8, 6, 4, 3)) == []
    assert uv._commit_author_mutation(
        board, created, label="mixed-move", placement_before=placement_before
    )
    assert board.author_objects
    assert uvs.free_grid_placement_for(board, ref).rect.column == 8
    uv._on_free_grid_undo()
    assert board.author_objects == []
    assert uvs.free_grid_placement_for(board, ref).rect.column == 0
    uv._on_free_grid_redo()
    assert [item.object_id for item in board.author_objects] == ["mixed"]
    assert uvs.free_grid_placement_for(board, ref).rect.column == 8


def test_history_is_board_isolated_and_auto_aspect_merge_never_replaces_author_entry(qapp, qtbot):
    from PyQt5.QtGui import QColor, QImage

    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    board = uv.board
    ref = uvs.make_ref("time", "aspect-card")
    uv._apply_add_ref(ref)
    created = uvs.create_author_object(board, _sticky("aspect-note"))
    assert uv._commit_author_mutation(board, created, label="create")
    history = uv._grid_histories[board.board_id]
    author_entry = history.undo[-1]
    assert isinstance(author_entry, uvs.BoardEditEntry)
    image = QImage(800, 200, QImage.Format_ARGB32)
    image.fill(QColor("#336699"))
    uv.store.publish(ref, image, digest="aspect", meta=uvs.PreviewMeta(ref=ref))
    uv._push_preview(ref)
    assert history.undo[-1] == author_entry
    assert history.undo[-1].object_patches[0].after["id"] == "aspect-note"

    other = uvs.create_board(uv._workspace, name="其他")
    assert other is not None
    uvs.set_active_board(uv._workspace, other.board_id)
    isolated = uvs.create_author_object(other, _sticky("other"))
    assert uv._commit_author_mutation(other, isolated, label="create")
    uv._on_free_grid_undo()
    assert other.author_objects == []
    assert [item.object_id for item in board.author_objects] == ["aspect-note"]
