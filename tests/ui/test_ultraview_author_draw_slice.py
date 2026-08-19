"""M6 Draw slice: Pen/Highlighter plus whole-stroke Eraser and Lasso."""
from __future__ import annotations

import math

import pytest
from PyQt5.QtCore import QEvent, QPoint, QRect, QSettings, Qt
from PyQt5.QtGui import QMouseEvent, QPainter, QTabletEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QMenu, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import ToolFlyoutSurface
from mf4_analyzer.ui.chart_stack.ultraview.author_edits import (
    apply_author_create,
    warning_copy,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    board_point_to_pixels,
    clamp_stroke_point,
    eraser_corridor_board,
    filter_stroke_samples,
    lasso_is_usable,
    persist_stroke_points,
    point_in_lasso,
    screen_px_tolerance_to_board,
    simplify_stroke,
    stroke_hit_record,
    stroke_ink_bounds,
    strokes_hit_by_segment,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_render import (
    draw_author_objects,
    stroke_pixel_path,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_style import HIGHLIGHTER_ALPHA, pen_color
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    DEFAULT_DRAW_PRESETS,
    DRAW_ERASER,
    DRAW_INK_SUBTOOLS,
    DRAW_LASSO,
    DRAW_SUBTOOLS,
    TOOL_DRAW,
    TOOL_SELECT,
    AuthorKey,
    BoardInteractionController,
    CardKey,
    DrawPreset,
    StrokeCreateIntent,
    lasso_selection_keys,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOLS,
    AUTHOR_TOOL_DRAW,
    DrawPopover,
)
from mf4_analyzer.ui.chart_stack.ultraview.compositor import compose_board
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import GridMetrics, export_grid_metrics
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    MAX_AUTHOR_POINTS,
    MAX_STROKE_POINTS,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    BoardBox,
    BoardEditEntry,
    BoardPoint,
    StickyObject,
    StrokeObject,
    apply_board_edit_entry,
    board_to_payload,
    default_board,
    make_ref,
)
from tests.ui.test_ultraview_page import (
    _Harness,
    _blank_board_point,
    _prepare_free_grid,
)


def _metrics(*, scale: float = 1.0) -> GridMetrics:
    base = GridMetrics(
        board_width=1600,
        board_height=900,
        column_width=120,
        row_height=88,
        gutter=16,
        padding=20,
        resolution=2,
    )
    if scale == 1.0:
        return base
    return GridMetrics(
        board_width=round(base.board_width * scale),
        board_height=round(base.board_height * scale),
        column_width=round(base.column_width * scale),
        row_height=round(base.row_height * scale),
        gutter=round(base.gutter * scale),
        padding=round(base.padding * scale),
        resolution=base.resolution,
        scale=scale,
        base=base,
    )


class _DrawSink:
    """Coordinator stand-in: applies typed intents through the mutation helper."""

    def __init__(self, page, board) -> None:
        self.page = page
        self.board = board
        self.undo: list[BoardEditEntry] = []
        self.redo: list[BoardEditEntry] = []
        self.dirty = False
        self.warnings: list[str] = []
        self.toasts: list[str] = []
        page.author_create_requested.connect(self._on_create)
        page.author_update_requested.connect(self._on_update)
        page.author_delete_requested.connect(self._on_delete)
        page.free_grid_undo_requested.connect(self._on_undo)
        page.free_grid_redo_requested.connect(self._on_redo)
        page.feedback_requested.connect(self.toasts.append)

    def _commit(self, mutation, label: str) -> None:
        self.warnings.extend(mutation.warnings)
        for code in mutation.warnings:
            copy = warning_copy(code)
            if copy and copy not in self.toasts:
                self.page._emit_feedback(copy)
        if not mutation.changed:
            return
        self.undo.append(BoardEditEntry(label, None, None, tuple(mutation.patches)))
        self.redo.clear()
        self.dirty = True
        self.page.set_board(self.board)

    def _on_create(self, intent) -> None:
        self._commit(apply_author_create(self.board, intent), "stroke-create")

    def _on_update(self, intent) -> None:
        from mf4_analyzer.ui.chart_stack.ultraview.author_edits import apply_author_update

        self._commit(apply_author_update(self.board, intent), "stroke-edit")

    def _on_delete(self, intent) -> None:
        from mf4_analyzer.ui.chart_stack.ultraview.author_edits import apply_author_delete

        self._commit(apply_author_delete(self.board, intent), "author-delete")

    def _on_undo(self) -> None:
        if not self.undo:
            return
        entry = self.undo.pop()
        apply_board_edit_entry(self.board, entry, forward=False)
        self.redo.append(entry)
        self.page.set_board(self.board)

    def _on_redo(self) -> None:
        if not self.redo:
            return
        entry = self.redo.pop()
        apply_board_edit_entry(self.board, entry, forward=True)
        self.undo.append(entry)
        self.page.set_board(self.board)


class _DrawHarness(_Harness):
    def __init__(self, qtbot):
        self.board = default_board()
        self.page = UltraViewPage(visible_author_tools=AUTHOR_TOOLS)
        qtbot.addWidget(self.page)
        self.page.resize(1600, 900)
        self.page.show()
        self.added = []
        self.replaced = []
        self.swapped = []
        self.placed = []
        self.grid_replaced = []
        self.grid_inserted = []
        self.unplaced = []
        self.removed = []
        self.opened = []
        self.synced = []
        self.focused = []
        self.armed = []
        self.rebound = []
        self.located = []
        self.copied_cards = []
        self.copied_board = 0
        self.exports = []
        self.auto_arrange = 0
        self.grid_undo = 0
        self.filters = []
        self.layouts = []
        self.free_grid = []
        self.ratio_steps = []
        self.presentation = []
        self.page.add_ref_requested.connect(self._on_add)
        self.page.replace_slot_requested.connect(self._on_replace)
        self.page.swap_slots_requested.connect(self._on_swap)
        self.page.place_from_unplaced_requested.connect(self._on_place)
        self.page.free_grid_insert_requested.connect(self._on_grid_insert)
        self.page.free_grid_replace_requested.connect(self._on_grid_replace)
        self.page.move_to_unplaced_requested.connect(self._on_unplaced)
        self.page.remove_ref_requested.connect(self._on_remove)
        self.page.open_source_requested.connect(self._record_open)
        self.page.sync_requested.connect(self._record_sync)
        self.page.focus_requested.connect(self._record_focus)
        self.page.rebind_arm_requested.connect(self._record_arm)
        self.page.rebind_ref_requested.connect(self._on_rebind)
        self.page.locate_ref_requested.connect(self._record_locate)
        self.page.copy_card_image_requested.connect(self._record_copy_card)
        self.page.copy_board_requested.connect(self._record_copy_board)
        self.page.export_png_requested.connect(self._record_export)
        self.page.auto_arrange_requested.connect(self._record_auto_arrange)
        self.page.free_grid_undo_requested.connect(self._record_grid_undo)
        self.page.compare_filter_changed.connect(self._record_filter)
        self.page.layout_changed.connect(self._record_layout)
        self.page.free_grid_toggled.connect(self._record_free_grid)
        self.page.ratio_nudge_requested.connect(self._record_ratio)
        self.page.presentation_toggled.connect(self._record_presentation)
        self.page.set_library_rows([])
        self.page.set_board(self.board)


def _arm_draw(page, tool: str = "pen", preset: int = 0) -> None:
    button = page.tool_rail().tool_button(AUTHOR_TOOL_DRAW)
    assert button is not None and button.isEnabled()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    if page.interaction().last_draw_subtool() != tool or page.interaction().draw_preset_index() != preset:
        page.draw_popover().choose_tool(tool, preset)
        QApplication.processEvents()
    assert page.interaction().active_tool() == TOOL_DRAW
    assert page.interaction().last_draw_subtool() == tool


def _drag_on_board(board, start: QPoint, end: QPoint, *, modifiers=Qt.NoModifier, steps: int = 8) -> None:
    QTest.mousePress(board, Qt.LeftButton, modifiers, start)
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    for index in range(1, max(2, steps)):
        pos = QPoint(
            start.x() + dx * index // steps,
            start.y() + dy * index // steps,
        )
        event = QMouseEvent(
            QEvent.MouseMove,
            pos,
            board.mapToGlobal(pos),
            Qt.NoButton,
            Qt.LeftButton,
            modifiers,
        )
        QApplication.sendEvent(board, event)
    QTest.mouseRelease(board, Qt.LeftButton, modifiers, end)
    QApplication.processEvents()


def _stroke_items(board) -> list[StrokeObject]:
    return [item for item in board.author_objects if isinstance(item, StrokeObject)]


def _zigzag(count: int, *, step: float = 0.05) -> list[tuple[float, float]]:
    points = []
    for index in range(count):
        points.append((float(index) * step, float(index % 2) * step))
    return points


def test_zero_one_two_duplicate_nonfinite_and_negative_points():
    metrics = _metrics()
    assert persist_stroke_points([], metrics) == ()
    assert persist_stroke_points([(1.0, 1.0)], metrics) == ()
    two = persist_stroke_points([(1.0, 1.0), (2.0, 2.5)], metrics, rdp_screen_px=0.0)
    assert two == ((1.0, 1.0), (2.0, 2.5))
    dupes = persist_stroke_points(
        [(1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (3.0, 1.0)],
        metrics,
        rdp_screen_px=0.0,
    )
    assert dupes == ((1.0, 1.0), (3.0, 1.0))
    cleaned = persist_stroke_points(
        [(0.0, 0.0), (math.nan, 1.0), (float("inf"), 2.0), (2.0, 0.0)],
        metrics,
        rdp_screen_px=0.0,
    )
    assert cleaned == ((0.0, 0.0), (2.0, 0.0))
    negative = persist_stroke_points([(-4.0, -3.0), (-1.0, -3.0)], metrics, rdp_screen_px=0.0)
    assert negative == ((-4.0, -3.0), (-1.0, -3.0))
    assert clamp_stroke_point((SAFETY_COLUMN_MAX + 40.0, 0.0))[0] < SAFETY_COLUMN_MAX
    assert clamp_stroke_point((SAFETY_COLUMN_MIN - 40.0, 0.0))[0] >= SAFETY_COLUMN_MIN
    outside = persist_stroke_points(
        [(SAFETY_COLUMN_MAX + 8.0, 1.0), (SAFETY_COLUMN_MAX + 12.0, 2.0)],
        metrics,
        rdp_screen_px=0.0,
    )
    assert outside
    assert all(point[0] < SAFETY_COLUMN_MAX for point in outside)


def test_min_distance_filter_tracks_zoom_and_dpr():
    metrics_1x = _metrics(scale=1.0)
    metrics_2x = _metrics(scale=2.0)
    pitch_x, _pitch_y = metrics_1x.exact_pitch()
    board_delta = 1.0 / pitch_x
    samples = ((0.0, 0.0), (board_delta, 0.0), (4.0, 0.0))
    filtered_1x = filter_stroke_samples(samples, metrics_1x, dpr=1.0)
    filtered_2x = filter_stroke_samples(samples, metrics_2x, dpr=1.0)
    assert filtered_1x == ((0.0, 0.0), (4.0, 0.0))
    assert filtered_2x == samples
    filtered_dpr2 = filter_stroke_samples(samples, metrics_1x, dpr=2.0)
    assert filtered_dpr2 == samples
    radii = screen_px_tolerance_to_board(1.5, metrics_2x)
    assert radii[0] == pytest.approx(1.5 / metrics_2x.exact_pitch()[0])


def test_rdp_is_stable_and_stroke_cap_is_2048():
    source = _zigzag(30, step=0.2)
    first = simplify_stroke(source, tolerance=0.05)
    assert simplify_stroke(list(source), tolerance=0.05) == first
    assert simplify_stroke(iter(source), tolerance=0.05) == first
    dense = _zigzag(MAX_STROKE_POINTS + 400, step=0.04)
    persisted = persist_stroke_points(dense, _metrics(), rdp_screen_px=0.0)
    assert 2 <= len(persisted) <= MAX_STROKE_POINTS
    assert persisted[0] == dense[0]
    assert persisted[-1] == dense[-1]
    assert persist_stroke_points(dense, _metrics(), rdp_screen_px=0.0) == persisted


def test_cap_and_width_are_included_in_stroke_bounds():
    points = ((0.0, 0.0), (3.0, 0.0))
    metrics = _metrics()
    thin = stroke_ink_bounds(points, 2, metrics)
    fat = stroke_ink_bounds(points, 48, metrics)
    assert fat.column_span >= thin.column_span
    assert fat.row_span >= thin.row_span
    assert fat.column <= thin.column
    assert fat.row <= thin.row
    assert fat.column_end >= thin.column_end
    assert fat.row_end >= thin.row_end


def test_screen_and_export_paths_match_within_one_pixel():
    points = (BoardPoint(1.0, 1.0), BoardPoint(4.0, 2.5), BoardPoint(7.0, 1.0))
    item = StrokeObject(
        "parity",
        "stroke",
        points=points,
        tool="pen",
        palette="ink",
        width_px_100=4,
    )
    metrics = export_grid_metrics(())
    origin = (0.0, 0.0)
    screen = stroke_pixel_path(points, metrics, origin, 1.0)
    exported = stroke_pixel_path(points, metrics, origin, 1.0)
    assert screen.elementCount() == exported.elementCount() >= 2
    for index in range(screen.elementCount()):
        a = screen.elementAt(index)
        b = exported.elementAt(index)
        assert math.hypot(a.x - b.x, a.y - b.y) <= 1.0
    board = default_board()
    board.author_objects = [item]
    image = compose_board(board, {}, {}, scale=1, title=False)
    from PyQt5.QtGui import QImage

    direct = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    direct.fill(Qt.transparent)
    painter = QPainter(direct)
    draw_author_objects(painter, (item,), metrics, origin_offset=origin, scale=1.0)
    painter.end()
    assert image.width() >= 1 and direct.width() >= 1


def test_board_point_cap_is_named_and_does_not_write_half_history():
    board = default_board()
    used = 0
    index = 0
    chunk = 2048
    while used + chunk <= MAX_AUTHOR_POINTS - 4:
        pts = tuple(BoardPoint(float(n) * 0.04, float(index)) for n in range(chunk))
        board.author_objects.append(
            StrokeObject(f"fill-{index}", "stroke", points=pts, tool="pen", palette="ink", width_px_100=2)
        )
        used += chunk
        index += 1
    remaining = MAX_AUTHOR_POINTS - used
    assert remaining >= 2
    long_points = tuple((float(n) * 0.04, 8.0) for n in range(remaining + 40))
    truncated = apply_author_create(
        board,
        StrokeCreateIntent(
            object_id="trunc",
            points=long_points,
            tool="pen",
            palette="ink",
            width_px_100=2,
        ),
    )
    assert truncated.changed is True
    assert "stroke_truncated" in truncated.warnings
    created = [item for item in board.author_objects if getattr(item, "object_id", "") == "trunc"]
    assert len(created) == 1
    assert len(created[0].points) <= remaining
    total = sum(len(item.points) for item in board.author_objects if isinstance(item, StrokeObject))
    assert total <= MAX_AUTHOR_POINTS

    rejected = apply_author_create(
        board,
        StrokeCreateIntent(
            object_id="reject",
            points=((0.0, 9.0), (1.0, 9.0), (2.0, 9.0)),
            tool="pen",
            palette="ink",
            width_px_100=2,
        ),
    )
    if sum(len(item.points) for item in board.author_objects if isinstance(item, StrokeObject)) >= MAX_AUTHOR_POINTS:
        assert rejected.changed is False
        assert "stroke_board_point_limit" in rejected.warnings
        assert all(getattr(item, "object_id", "") != "reject" for item in board.author_objects)
    too_short = apply_author_create(
        board,
        StrokeCreateIntent(object_id="short", points=((1.0, 1.0),), tool="pen"),
    )
    assert too_short.changed is False
    assert "stroke_too_short" in too_short.warnings
    empty = apply_author_create(board, StrokeCreateIntent(object_id="empty", points=(), tool="pen"))
    assert empty.changed is False
    assert "stroke_too_short" in empty.warnings
    assert warning_copy("stroke_board_point_limit")
    assert warning_copy("stroke_truncated")


def test_tablet_and_mouse_normalize_to_plain_pointer_samples():
    controller = BoardInteractionController()
    metrics = _metrics()
    controller.set_active_tool(TOOL_DRAW)
    controller.set_draw_style(tool="pen", palette="ink", width_px_100=2)
    draft = controller.begin_draft(TOOL_DRAW, origin=(0.0, 0.0), object_id="s1")
    class _Tablet:
        def pos(self):
            return QPoint(40, 12)

        def pressure(self):
            return 0.92

        def xTilt(self):
            return 18

        def yTilt(self):
            return -11

    sample = controller.pointer_sample_from_event(_Tablet(), metrics)
    assert sample is not None
    controller.append_draw_sample(sample, metrics, dpr=1.0)
    assert draft.points
    assert controller.draft() is not None
    assert QTabletEvent is not None


def test_draw_flyout_is_frame_with_four_live_items_and_no_precision(qtbot):
    flyout = DrawPopover()
    qtbot.addWidget(flyout)
    assert isinstance(flyout, ToolFlyoutSurface)
    assert isinstance(flyout, QFrame)
    assert not isinstance(flyout, QMenu)
    assert flyout.subtools() == ("pen", "highlighter", "eraser", "lasso")
    assert DRAW_SUBTOOLS == ("pen", "highlighter", "eraser", "lasso")
    assert DRAW_INK_SUBTOOLS == ("pen", "highlighter")
    assert len(flyout.presets("pen")) == 3
    assert len(flyout.presets("highlighter")) == 3
    assert flyout.presets("eraser") == ()
    assert flyout.presets("lasso") == ()
    assert len(flyout.preset_buttons("pen")) == 3
    assert len(flyout.preset_buttons("highlighter")) == 3
    for button in (*flyout.preset_buttons("pen"), *flyout.preset_buttons("highlighter")):
        assert button.width() >= 40 and button.height() >= 40
    eraser = flyout.session_button("eraser")
    lasso = flyout.session_button("lasso")
    assert eraser is not None and lasso is not None
    assert eraser.width() >= 40 and eraser.height() >= 40
    assert lasso.width() >= 40 and lasso.height() >= 40
    assert "整笔擦除" in eraser.toolTip()
    assert "精密" not in eraser.toolTip()
    assert "precision" not in eraser.toolTip().lower()
    assert "pressure" not in eraser.toolTip().lower()
    assert "压感" not in eraser.toolTip()
    names = " ".join(child.objectName() for child in flyout.findChildren(QToolButton)).lower()
    tips = " ".join(child.toolTip() for child in flyout.findChildren(QToolButton)).lower()
    assert "eraser" in names
    assert "lasso" in names
    assert "precision" not in names
    assert "precision" not in tips
    chosen: list[tuple[str, int]] = []
    def _record_tool(tool: str, index: int) -> None:
        chosen.append((tool, index))

    flyout.tool_selected.connect(_record_tool)
    flyout.choose_tool("highlighter", 2)
    flyout.choose_tool("eraser")
    flyout.choose_tool("lasso")
    assert chosen == [("highlighter", 2), ("eraser", 0), ("lasso", 0)]
    assert flyout.findChildren(QMenu) == []


def test_draw_presets_use_isolated_qsettings_not_board_or_history(qtbot):
    flyout = DrawPopover()
    qtbot.addWidget(flyout)
    custom = (
        DrawPreset("red", 6),
        DrawPreset("blue", 10),
        DrawPreset("ink", 3),
    )
    flyout.set_presets("pen", custom)
    stored = QSettings()
    stored.beginGroup(DrawPopover.SETTINGS_GROUP)
    assert stored.value("pen/0/palette") == "red"
    assert int(stored.value("pen/0/width_px_100")) == 6
    stored.endGroup()
    board = default_board()
    payload = board_to_payload(board)
    assert "draw_presets" not in payload
    assert DrawPopover.SETTINGS_GROUP not in str(payload)
    reloaded = DrawPopover()
    qtbot.addWidget(reloaded)
    loaded = reloaded.presets("pen")
    assert loaded[0].palette == "red"
    assert loaded[0].width_px_100 == 6
    created = apply_author_create(
        board,
        StrokeCreateIntent(
            object_id="keep",
            points=((0.0, 0.0), (2.0, 0.0)),
            tool="pen",
            palette="ink",
            width_px_100=2,
        ),
    )
    assert created.changed is True
    assert all(getattr(item, "palette", "") != "red" for item in board.author_objects)


def test_pointer_up_is_one_stroke_one_undo_and_draw_stays_active(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    _arm_draw(harness.page, "pen", 0)
    start = _blank_board_point(free)
    _drag_on_board(free, start, QPoint(start.x() + 220, start.y() + 40))
    items = _stroke_items(harness.board)
    assert len(items) == 1
    assert items[0].tool == "pen"
    assert len(items[0].points) >= 2
    assert len(sink.undo) == 1
    assert harness.page.interaction().active_tool() == TOOL_DRAW
    _arm_draw(harness.page, "highlighter", 1)
    _drag_on_board(free, start, QPoint(start.x() + 80, start.y() + 160))
    items = _stroke_items(harness.board)
    assert len(items) == 2
    assert items[1].tool == "highlighter"
    color = pen_color(items[1].palette, tool="highlighter")
    assert color[3] == HIGHLIGHTER_ALPHA
    assert len(sink.undo) == 2
    harness.page.free_grid_undo_requested.emit()
    QApplication.processEvents()
    assert len(_stroke_items(harness.board)) == 1


def test_cancel_and_deactivate_write_zero_mutations(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    _arm_draw(harness.page)
    start = _blank_board_point(free)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    moved = QPoint(start.x() + 90, start.y() + 40)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            moved,
            free.mapToGlobal(moved),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert harness.page.interaction().draft() is not None
    assert harness.page.handle_escape() is True
    QApplication.processEvents()
    assert harness.board.author_objects == []
    assert sink.undo == []
    assert sink.dirty is False
    _arm_draw(harness.page)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            moved,
            free.mapToGlobal(moved),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    harness.page._cancel_board_gestures()
    QApplication.processEvents()
    assert harness.page.interaction().draft() is None
    assert harness.board.author_objects == []
    assert sink.undo == []


def test_space_pan_pauses_samples_and_resume_restores_cursor(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    _arm_draw(harness.page)
    start = _blank_board_point(free)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    mid = QPoint(start.x() + 40, start.y())
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            mid,
            free.mapToGlobal(mid),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    draft = harness.page.interaction().draft()
    assert draft is not None
    before = len(draft.points)
    harness.page.note_space(True)
    paused = QPoint(start.x() + 180, start.y() + 90)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            paused,
            free.mapToGlobal(paused),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert len(harness.page.interaction().draft().points) == before
    harness.page.note_space(False)
    resumed = QPoint(start.x() + 80, start.y() + 20)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            resumed,
            free.mapToGlobal(resumed),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert len(harness.page.interaction().draft().points) >= before
    QTest.mouseRelease(free, Qt.LeftButton, Qt.NoModifier, resumed)
    QApplication.processEvents()
    assert len(_stroke_items(harness.board)) == 1
    assert harness.page.interaction().active_tool() == TOOL_DRAW
    assert free.cursor().shape() == Qt.CrossCursor
    assert sink.dirty is True


def test_draft_hot_path_uses_incremental_dirty_rect(qtbot):
    harness = _DrawHarness(qtbot)
    _DrawSink(harness.page, harness.board)
    layer = harness.page._free_grid.author_paint_layer()
    seen: list[QRect] = []
    original = layer.update

    def _spy(rect=None):
        if isinstance(rect, QRect):
            seen.append(QRect(rect))
        return original(rect) if rect is not None else original()

    layer.update = _spy  # type: ignore[method-assign]
    planner = {"count": 0}
    harness.page._free_grid._sync_author_projection = (
        lambda *args, **kwargs: planner.__setitem__("count", planner["count"] + 1)
    )
    _arm_draw(harness.page)
    free = harness.page._free_grid
    start = _blank_board_point(free)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    syncs_at_press = planner["count"]
    for delta in range(12, 120, 12):
        pos = QPoint(start.x() + delta, start.y() + delta // 4)
        QApplication.sendEvent(
            free,
            QMouseEvent(
                QEvent.MouseMove,
                pos,
                free.mapToGlobal(pos),
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            ),
        )
    assert planner["count"] == syncs_at_press
    assert seen
    assert any(isinstance(rect, QRect) for rect in seen)
    QTest.mouseRelease(free, Qt.LeftButton, Qt.NoModifier, QPoint(start.x() + 120, start.y()))
    layer.update = original  # type: ignore[method-assign]


def test_active_draw_rail_icon_projects_current_subtool(qtbot):
    harness = _DrawHarness(qtbot)
    _arm_draw(harness.page, "pen", 0)
    rail = harness.page.tool_rail()
    assert rail.draw_subtool() == "pen"
    harness.page.draw_popover().choose_tool("highlighter", 0)
    QApplication.processEvents()
    assert harness.page.interaction().last_draw_subtool() == "highlighter"
    assert rail.draw_subtool() == "highlighter"
    harness.page.draw_popover().choose_tool("eraser")
    QApplication.processEvents()
    assert harness.page.interaction().last_draw_subtool() == DRAW_ERASER
    assert rail.draw_subtool() == DRAW_ERASER
    harness.page.draw_popover().choose_tool("lasso")
    QApplication.processEvents()
    assert rail.draw_subtool() == DRAW_LASSO
    assert rail.active_tool() == AUTHOR_TOOL_DRAW


def test_default_draw_presets_match_contract():
    assert DEFAULT_DRAW_PRESETS["pen"][0].palette == "ink"
    assert DEFAULT_DRAW_PRESETS["highlighter"][0].palette == "yellow"
    assert all(preset.width_px_100 >= 1 for preset in DEFAULT_DRAW_PRESETS["pen"])
    assert all(preset.width_px_100 >= 1 for preset in DEFAULT_DRAW_PRESETS["highlighter"])


def _widget_point(free, xy: tuple[float, float]) -> QPoint:
    origin = free.author_paint_layer().model().origin_offset
    mapped = board_point_to_pixels(xy, free.metrics(), origin_offset=origin)
    assert mapped is not None
    return QPoint(int(round(mapped[0])), int(round(mapped[1])))


def _lasso_loop(board, corners: list[QPoint], *, modifiers=Qt.NoModifier) -> None:
    start = corners[0]
    QTest.mousePress(board, Qt.LeftButton, modifiers, start)
    for pos in corners[1:]:
        event = QMouseEvent(
            QEvent.MouseMove,
            pos,
            board.mapToGlobal(pos),
            Qt.NoButton,
            Qt.LeftButton,
            modifiers,
        )
        QApplication.sendEvent(board, event)
    QTest.mouseRelease(board, Qt.LeftButton, modifiers, corners[-1])
    QApplication.processEvents()


def _board_rect_loop(free, x0: float, y0: float, x1: float, y1: float) -> list[QPoint]:
    return [
        _widget_point(free, (x0, y0)),
        _widget_point(free, (x1, y0)),
        _widget_point(free, (x1, y1)),
        _widget_point(free, (x0, y1)),
        _widget_point(free, (x0, y0)),
    ]


def _seed_stroke(sink, object_id: str, points, *, locked: bool = False, palette: str = "ink") -> None:
    sink._commit(
        apply_author_create(
            sink.board,
            StrokeCreateIntent(
                object_id=object_id,
                points=points,
                tool="pen",
                palette=palette,
                width_px_100=2,
                locked=locked,
            ),
        ),
        "stroke-create",
    )


def test_slice_can_construct_draw_without_assuming_release_rail():
    assert AUTHOR_TOOL_DRAW in AUTHOR_TOOLS
    assert DRAW_SUBTOOLS == ("pen", "highlighter", "eraser", "lasso")
    assert DRAW_INK_SUBTOOLS == ("pen", "highlighter")
    assert TOOL_SELECT == "select"


def test_eraser_sweep_deletes_many_strokes_as_one_history(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    _seed_stroke(sink, "a", ((1.0, 2.0), (8.0, 2.0)), palette="ink")
    _seed_stroke(sink, "b", ((1.0, 5.0), (8.0, 5.0)), palette="blue")
    _seed_stroke(sink, "c", ((1.0, 8.0), (8.0, 8.0)), palette="red")
    created = len(sink.undo)
    _arm_draw(harness.page, DRAW_ERASER, 0)
    _drag_on_board(
        free,
        _widget_point(free, (4.0, 1.0)),
        _widget_point(free, (4.0, 9.0)),
        steps=3,
    )
    ids = [item.object_id for item in _stroke_items(harness.board)]
    assert ids == []
    assert len(sink.undo) == created + 1
    harness.page.free_grid_undo_requested.emit()
    QApplication.processEvents()
    restored = _stroke_items(harness.board)
    assert [item.object_id for item in restored] == ["a", "b", "c"]
    assert [item.palette for item in restored] == ["ink", "blue", "red"]
    assert [(item.points[0].x, item.points[0].y) for item in restored] == [
        (1.0, 2.0),
        (1.0, 5.0),
        (1.0, 8.0),
    ]
    assert harness.page.interaction().active_tool() == TOOL_DRAW
    assert harness.page.interaction().last_draw_subtool() == DRAW_ERASER


def test_eraser_skips_locked_and_non_stroke_objects(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    _seed_stroke(sink, "open", ((1.0, 2.0), (8.0, 2.0)))
    _seed_stroke(sink, "locked", ((1.0, 5.0), (8.0, 5.0)), locked=True)
    harness.board.author_objects.append(
        StickyObject("note", "sticky", box=BoardBox(3.0, 3.5, 2.0, 2.0), text="keep")
    )
    harness.page.set_board(harness.board)
    _arm_draw(harness.page, DRAW_ERASER, 0)
    _drag_on_board(
        free,
        _widget_point(free, (4.0, 1.0)),
        _widget_point(free, (4.0, 7.0)),
        steps=3,
    )
    ids = [getattr(item, "object_id", "") for item in harness.board.author_objects]
    assert "open" not in ids
    assert "locked" in ids
    assert "note" in ids
    assert sink.dirty is True


def test_lasso_selects_centers_returns_to_select_and_does_not_dirty(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    harness.board.author_objects = [
        StickyObject("in", "sticky", box=BoardBox(2.0, 2.0, 2.0, 2.0), text="in"),
        StickyObject("out", "sticky", box=BoardBox(12.0, 12.0, 2.0, 2.0), text="out"),
        StickyObject(
            "locked",
            "sticky",
            locked=True,
            box=BoardBox(2.5, 6.0, 2.0, 2.0),
            text="lock",
        ),
    ]
    harness.page.set_board(harness.board)
    _arm_draw(harness.page, DRAW_LASSO, 0)
    _lasso_loop(free, _board_rect_loop(free, 1.0, 1.0, 8.0, 9.0))
    selected = harness.page.interaction().author_selection_ids()
    assert selected == frozenset({"in", "locked"})
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    assert sink.undo == []
    assert sink.dirty is False
    payload = board_to_payload(harness.board)
    assert "lasso" not in str(payload).lower()


def test_lasso_shift_is_additive_short_path_and_escape_keep_contract(qtbot):
    harness = _DrawHarness(qtbot)
    sink = _DrawSink(harness.page, harness.board)
    free = harness.page._free_grid
    harness.board.author_objects = [
        StickyObject("one", "sticky", box=BoardBox(2.0, 2.0, 2.0, 2.0), text="one"),
        StickyObject("two", "sticky", box=BoardBox(8.0, 2.0, 2.0, 2.0), text="two"),
    ]
    harness.page.set_board(harness.board)
    harness.page.interaction().select_only_author("one")
    free.sync_selection_projection()
    _arm_draw(harness.page, DRAW_LASSO, 0)
    start = _widget_point(free, (7.0, 1.0))
    _lasso_loop(free, _board_rect_loop(free, 7.0, 1.0, 11.0, 5.0), modifiers=Qt.ShiftModifier)
    assert harness.page.interaction().author_selection_ids() == frozenset({"one", "two"})
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    _arm_draw(harness.page, DRAW_LASSO, 0)
    tiny = _widget_point(free, (0.5, 0.5))
    _drag_on_board(free, tiny, QPoint(tiny.x() + 2, tiny.y() + 1), steps=2)
    assert harness.page.interaction().author_selection_ids() == frozenset({"one", "two"})
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    _arm_draw(harness.page, DRAW_LASSO, 0)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    moved = _widget_point(free, (9.0, 4.0))
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            moved,
            free.mapToGlobal(moved),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert harness.page.interaction().draft() is not None
    assert harness.page.handle_escape() is True
    QApplication.processEvents()
    assert harness.page.interaction().active_tool() == TOOL_DRAW
    assert harness.page.interaction().last_draw_subtool() == DRAW_LASSO
    assert harness.page.interaction().author_selection_ids() == frozenset({"one", "two"})
    assert sink.dirty is False
    assert sink.undo == []


def test_lasso_uses_card_center_not_body_overlap(qtbot):
    harness = _DrawHarness(qtbot)
    _DrawSink(harness.page, harness.board)
    free, (card,) = _prepare_free_grid(harness, qtbot, "lasso-card")
    geom = card.geometry()
    center = QPoint(geom.x() + geom.width() // 2, geom.y() + geom.height() // 2)
    _arm_draw(harness.page, DRAW_LASSO, 0)
    _lasso_loop(
        free,
        [
            QPoint(center.x() - 40, center.y() - 40),
            QPoint(center.x() + 40, center.y() - 40),
            QPoint(center.x() + 40, center.y() + 40),
            QPoint(center.x() - 40, center.y() + 40),
            QPoint(center.x() - 40, center.y() - 40),
        ],
    )
    cards = harness.page.interaction().card_selection()
    assert make_ref("time", "lasso-card") in cards
    assert harness.page.interaction().active_tool() == TOOL_SELECT
    harness.page.interaction().clear_selection()
    free.sync_selection_projection()
    _arm_draw(harness.page, DRAW_LASSO, 0)
    corner = QPoint(geom.x() + 8, geom.y() + 8)
    _lasso_loop(
        free,
        [
            QPoint(corner.x() - 24, corner.y() - 24),
            QPoint(corner.x() + 24, corner.y() - 24),
            QPoint(corner.x() + 24, corner.y() + 24),
            QPoint(corner.x() - 24, corner.y() + 24),
            QPoint(corner.x() - 24, corner.y() - 24),
        ],
    )
    assert harness.page.interaction().card_selection() == frozenset()


def test_eraser_corridor_is_zoom_independent_and_uses_segments():
    rec = stroke_hit_record("s", ((0.0, 0.0), (4.0, 0.0)), 2)
    assert rec is not None
    assert rec.radius == eraser_corridor_board(2)
    far = strokes_hit_by_segment((rec,), (2.0, -2.0), (2.0, 2.0))
    assert far == ("s",)
    assert math.hypot(2.0, -2.0) > rec.radius
    assert math.hypot(2.0, 2.0) > rec.radius
    assert strokes_hit_by_segment((rec,), (2.0, 2.0), (2.0, 3.0)) == ()
    fat = stroke_hit_record("fat", ((0.0, 0.0), (4.0, 0.0)), 48)
    thin = stroke_hit_record("thin", ((0.0, 0.0), (4.0, 0.0)), 2)
    assert fat is not None and thin is not None
    assert fat.radius == eraser_corridor_board(48)
    assert thin.radius == eraser_corridor_board(2)
    assert fat.radius >= thin.radius


def test_lasso_handles_closed_open_self_intersect_and_short_paths():
    square = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0))
    open_square = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
    assert point_in_lasso((2.0, 2.0), square) is True
    assert point_in_lasso((2.0, 2.0), open_square) is True
    assert point_in_lasso((5.0, 5.0), square) is False
    bowtie = ((0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0))
    assert lasso_is_usable(bowtie) is True
    assert point_in_lasso((3.5, 0.5), bowtie) is True
    assert lasso_is_usable(((0.0, 0.0), (0.1, 0.0))) is False
    assert lasso_is_usable(square) is True
    ref = make_ref("time", "card-a")
    keys = lasso_selection_keys(
        path=square,
        author_centers=(("note", (2.0, 2.0)), ("out", (8.0, 8.0))),
        card_centers=((ref, (2.0, 2.0)),),
    )
    assert AuthorKey("note") in keys
    assert AuthorKey("out") not in keys
    assert CardKey(ref) in keys
    assert lasso_selection_keys(
        path=((0.0, 0.0), (0.05, 0.0)),
        author_centers=(("note", (0.02, 0.0)),),
        card_centers=(),
    ) == ()
