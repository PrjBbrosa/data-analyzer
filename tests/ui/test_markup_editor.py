from PyQt5.QtCore import QEvent, QPointF, QRectF, QSettings, Qt
from PyQt5.QtGui import QColor, QKeySequence, QMouseEvent, QPainterPath, QPixmap
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import (
    QAbstractButton,
    QPushButton,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QShortcut,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui import hints
from mf4_analyzer.ui.markup.editor import MarkupEditor


def _pixmap(width=120, height=80, color="#f7f7f7"):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(color))
    return pixmap


def _drag_scene(qtbot, editor, start, end, modifiers=Qt.NoModifier):
    editor.show()
    start_pos = editor._view.mapFromScene(QPointF(*start))
    end_pos = editor._view.mapFromScene(QPointF(*end))
    viewport = editor._view.viewport()
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(start_pos),
            Qt.LeftButton,
            Qt.LeftButton,
            modifiers,
        ),
    )
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(end_pos),
            Qt.NoButton,
            Qt.LeftButton,
            modifiers,
        ),
    )
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(end_pos),
            Qt.LeftButton,
            Qt.NoButton,
            modifiers,
        ),
    )


def _click_scene(qtbot, editor, point):
    editor.show()
    pos = editor._view.mapFromScene(QPointF(*point))
    qtbot.mouseClick(editor._view.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()


def _markup_items(editor):
    return [
        item for item in editor._scene.items()
        if (
            item is not editor._background_item
            and item.data(0) not in {"editor_handle", "crop_overlay"}
            and item.parentItem() is None
        )
    ]


def _first_item(editor, item_type):
    for item in _markup_items(editor):
        if isinstance(item, item_type):
            return item
    raise AssertionError(f"missing {item_type.__name__}")


def _style_panel(editor):
    return editor._style_button.menu().actions()[0].defaultWidget()


def _drag_scene_points(qtbot, editor, start: QPointF, end: QPointF):
    _drag_scene(qtbot, editor, (start.x(), start.y()), (end.x(), end.y()))


def test_initial_scene_uses_source_pixmap_pixel_size(qtbot):
    pixmap = _pixmap(160, 90)

    editor = MarkupEditor(pixmap)
    qtbot.addWidget(editor)

    assert editor._background_item.pixmap().size() == pixmap.size()
    assert editor._scene.sceneRect() == QRectF(0, 0, 160, 90)


def test_apply_crop_rect_resizes_background_and_translates_items(qtbot):
    editor = MarkupEditor(_pixmap(120, 80))
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(20, 30, 40, 25))

    editor.apply_crop_rect(QRectF(10, 15, 70, 50))

    assert editor._background_item.pixmap().size().width() == 70
    assert editor._background_item.pixmap().size().height() == 50
    assert editor._scene.sceneRect() == QRectF(0, 0, 70, 50)
    assert rect_item.pos().x() == -10
    assert rect_item.pos().y() == -15


def test_apply_crop_rect_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap(120, 80))
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(20, 30, 40, 25))

    editor.apply_crop_rect(QRectF(10, 15, 70, 50))
    editor._undo_stack.undo()

    assert editor._background_item.pixmap().size().width() == 120
    assert editor._background_item.pixmap().size().height() == 80
    assert editor._scene.sceneRect() == QRectF(0, 0, 120, 80)
    assert rect_item.pos() == QPointF(0, 0)


def test_render_result_matches_current_background_size(qtbot):
    editor = MarkupEditor(_pixmap(120, 80))
    qtbot.addWidget(editor)
    editor.add_line_item(QRectF(5, 5, 80, 40))
    editor.apply_crop_rect(QRectF(10, 10, 64, 48))

    rendered = editor.render_result()

    assert rendered.size().width() == 64
    assert rendered.size().height() == 48
    assert not rendered.isNull()


def test_finish_and_copy_calls_on_done_with_rendered_pixmap(qtbot):
    seen = []
    editor = MarkupEditor(_pixmap(100, 60), on_done=seen.append)
    qtbot.addWidget(editor)
    editor.add_arrow_item(QRectF(10, 10, 80, 40))

    editor.finish_and_copy()

    assert len(seen) == 1
    assert seen[0].size().width() == 100
    assert seen[0].size().height() == 60


def test_minimum_annotation_tools_create_independent_items(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    items = [
        editor.add_rect_item(QRectF(5, 5, 30, 20)),
        editor.add_line_item(QRectF(10, 15, 80, 20)),
        editor.add_arrow_item(QRectF(15, 20, 90, 45)),
        editor.add_number_item(QRectF(40, 30, 0, 0)),
    ]

    assert len({id(item) for item in items}) == 4
    assert all(item.scene() is editor._scene for item in items)
    assert all(item.zValue() >= 1 for item in items)


def test_drag_rect_tool_creates_undoable_item(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_tool("rect")

    _drag_scene(qtbot, editor, (10, 10), (50, 35))

    assert any(isinstance(item, QGraphicsRectItem) for item in _markup_items(editor))
    editor._undo_stack.undo()
    assert not any(isinstance(item, QGraphicsRectItem) for item in _markup_items(editor))


def test_zoom_controls_change_view_scale_without_changing_render_size(qtbot):
    editor = MarkupEditor(_pixmap(160, 90))
    qtbot.addWidget(editor)
    before = editor._view.transform().m11()

    editor.zoom_in()
    zoomed = editor._view.transform().m11()
    editor.actual_size()
    actual = editor._view.transform().m11()

    assert zoomed > before
    assert actual == 1.0
    assert editor.render_result().size().width() == 160
    assert editor.render_result().size().height() == 90


def test_editor_initial_show_fits_entire_large_image(qtbot):
    editor = MarkupEditor(_pixmap(2400, 1600))
    qtbot.addWidget(editor)
    editor.resize(620, 420)

    editor.show()
    QApplication.processEvents()

    assert editor._view.transform().m11() < 1.0
    assert editor._view.transform().m22() < 1.0


def test_editor_refits_image_when_window_grows_in_fit_mode(qtbot):
    editor = MarkupEditor(_pixmap(2400, 1600))
    qtbot.addWidget(editor)
    editor.resize(620, 420)
    editor.show()
    QApplication.processEvents()
    before = editor._view.transform().m11()

    editor.resize(1240, 840)
    QApplication.processEvents()
    QApplication.processEvents()

    assert editor._view.transform().m11() > before * 1.5


def test_editor_scene_rect_matches_hidpi_pixmap_display_bounds(qtbot):
    pixmap = _pixmap(1000, 600)
    pixmap.setDevicePixelRatio(2.0)

    editor = MarkupEditor(pixmap)
    qtbot.addWidget(editor)

    assert editor._current_pixmap.devicePixelRatioF() == 1.0
    assert editor._background_item.boundingRect() == QRectF(0, 0, 1000, 600)
    assert editor._scene.sceneRect() == editor._background_item.boundingRect()


def test_style_controls_apply_to_new_and_selected_items(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    editor.set_color(QColor("#2563eb"))
    editor.set_stroke_width(8)
    rect_item = editor.add_rect_item(QRectF(5, 5, 30, 20))

    assert rect_item.pen().color().name() == "#2563eb"
    assert rect_item.pen().width() == 8

    rect_item.setSelected(True)
    editor.set_color(QColor("#059669"))
    editor.set_stroke_width(2)

    assert rect_item.pen().color().name() == "#059669"
    assert rect_item.pen().width() == 2


def test_style_controls_are_compact_not_placeholder_buttons(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    style_buttons = [
        button for button in _style_panel(editor).findChildren(QToolButton)
        if button.objectName().startswith(("markupColor_", "markupWidth_"))
    ]

    assert style_buttons
    assert all(button.width() <= 34 for button in style_buttons)
    assert all(button.height() <= 34 for button in style_buttons)
    assert all(button.text() == "" for button in style_buttons)


def test_color_and_width_collapsed_into_style_menu(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    toolbar = editor.findChild(QWidget, "markupEditorToolbar")
    permanent = [
        button for button in toolbar.findChildren(QToolButton)
        if button.objectName().startswith(("markupColor_", "markupWidth_"))
        and button.parent() is toolbar
    ]

    assert permanent == []
    style_btn = editor.findChild(QToolButton, "markupStyleButton")
    assert style_btn is not None
    assert style_btn.menu() is not None
    panel = _style_panel(editor)
    assert panel.findChild(QToolButton, "markupColor_059669") is not None


def test_style_menu_rounding_uses_translucent_background(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    menu = editor.findChild(QToolButton, "markupStyleButton").menu()

    assert menu.objectName() == "markupStyleMenu"
    assert menu.testAttribute(Qt.WA_TranslucentBackground), (
        "rounded QMenu popups need WA_TranslucentBackground, "
        "otherwise the native rectangular backing shows outside the radius"
    )
    flags = menu.windowFlags()
    assert bool(flags & Qt.NoDropShadowWindowHint), (
        "rounded QMenu popups on macOS need NoDropShadowWindowHint, "
        "otherwise the native rectangular shadow can remain behind the radius"
    )
    assert bool(flags & Qt.FramelessWindowHint), (
        "rounded QMenu popups need FramelessWindowHint so the platform frame "
        "does not draw square corners around the transparent shell"
    )


def test_style_menu_still_drives_set_color(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    swatch = _style_panel(editor).findChild(QToolButton, "markupColor_059669")
    assert swatch is not None

    swatch.click()

    assert rect.pen().color().name() == "#059669"


def test_select_tool_drags_existing_item(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(10, 10, 30, 20))
    editor.set_tool("select")

    _drag_scene(qtbot, editor, (20, 20), (55, 45))

    assert rect_item.isSelected()
    assert rect_item.pos().x() >= 30
    assert rect_item.pos().y() >= 20


def test_existing_item_can_be_dragged_even_when_draw_tool_is_active(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(10, 10, 30, 20))
    editor.set_tool("arrow")

    _drag_scene(qtbot, editor, (20, 20), (55, 45))

    assert rect_item.isSelected()
    assert rect_item.pos().x() >= 30
    assert rect_item.pos().y() >= 20


def test_arrow_shape_has_clickable_width(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    arrow = editor.add_arrow_item(QRectF(10, 10, 80, 0))
    assert arrow.shape().contains(QPointF(40, 12))


def test_markup_item_at_uses_fuzzy_tolerance_for_thin_line(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    line = editor.add_line_item(QRectF(20, 20, 60, 0))
    editor.set_zoom(1.0)
    assert editor.markup_item_at(QPointF(40, 24)) is line


def test_near_click_selects_line_under_draw_tool_without_drawing(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    line = editor.add_line_item(QRectF(20, 20, 60, 0))
    editor.set_zoom(1.0)
    editor.set_tool("arrow")
    before = len(_markup_items(editor))
    editor.show()
    pos = editor._view.mapFromScene(QPointF(40, 23))
    qtbot.mouseClick(editor._view.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()
    assert line.isSelected()
    assert len(_markup_items(editor)) == before


def test_handles_shown_under_any_tool_not_only_select(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect.setSelected(True)

    editor.set_tool("pen")
    editor.refresh_handles()

    assert editor._handles


def test_path_and_number_have_scale_handles(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    path = QPainterPath(QPointF(10, 10))
    path.lineTo(40, 40)
    pen_item = editor.add_path_item(path)
    number_item = editor.add_number_item(QRectF(70, 30, 0, 0))

    for item in (pen_item, number_item):
        editor.clear_selection()
        item.setSelected(True)
        editor.refresh_handles()
        handle = next(
            h for h in editor._handles
            if getattr(h, "_target", None) is item and getattr(h, "_role", "") == "scale"
        )
        before = item.scale()
        editor.drag_handle(handle, item.mapToScene(QPointF(120, 90)))
        assert item.scale() > before


def test_number_scale_handle_grows_in_place(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    number = editor.add_number_item(QRectF(40, 30, 0, 0))
    number.setSelected(True)
    editor.refresh_handles()
    handle = next(
        h for h in editor._handles
        if getattr(h, "_target", None) is number and getattr(h, "_role", "") == "scale"
    )
    before_center = number.sceneBoundingRect().center()
    before_width = number.sceneBoundingRect().width()

    editor.drag_handle(handle, handle.pos() + QPointF(20, 20))

    after_center = number.sceneBoundingRect().center()
    assert number.sceneBoundingRect().width() > before_width * 1.8
    assert abs(after_center.x() - before_center.x()) < 0.5
    assert abs(after_center.y() - before_center.y()) < 0.5


def test_scale_handle_preserves_existing_scale_when_dragged_at_handle_position(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    path = QPainterPath(QPointF(10, 10))
    path.lineTo(40, 40)
    item = editor.add_path_item(path)
    item.setScale(2.0)
    item.setSelected(True)
    editor.refresh_handles()
    handle = next(
        h for h in editor._handles
        if getattr(h, "_target", None) is item and getattr(h, "_role", "") == "scale"
    )

    editor.drag_handle(handle, handle.pos())

    assert item.scale() == 2.0


def test_near_line_endpoint_drag_edits_endpoint_not_whole_item(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    line_item = editor.add_line_item(QRectF(20, 20, 80, 0))
    line_item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(
        h for h in editor._handles
        if getattr(h, "_target", None) is line_item and getattr(h, "_role", "") == "p1"
    )
    before_pos = QPointF(line_item.pos())
    before_p1 = QPointF(line_item.line().p1())

    _drag_scene_points(
        qtbot,
        editor,
        handle.pos() + QPointF(10, 0),
        handle.pos() + QPointF(10, 18),
    )

    assert line_item.pos() == before_pos
    assert line_item.line().p1() != before_p1


def test_near_rect_corner_drag_resizes_not_moves(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect_item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(
        h for h in editor._handles
        if getattr(h, "_target", None) is rect_item and getattr(h, "_role", "") == "br"
    )
    before_pos = QPointF(rect_item.pos())
    before_rect = QRectF(rect_item.rect())

    _drag_scene_points(
        qtbot,
        editor,
        handle.pos() + QPointF(-7, -7),
        handle.pos() + QPointF(20, 20),
    )

    assert rect_item.pos() == before_pos
    assert rect_item.rect().right() > before_rect.right()
    assert rect_item.rect().bottom() > before_rect.bottom()


def test_near_scale_handle_drag_scales_path_not_moves(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    path = QPainterPath(QPointF(10, 10))
    path.lineTo(40, 40)
    path_item = editor.add_path_item(path)
    path_item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(
        h for h in editor._handles
        if getattr(h, "_target", None) is path_item and getattr(h, "_role", "") == "scale"
    )
    before_pos = QPointF(path_item.pos())
    before_scale = path_item.scale()

    _drag_scene_points(
        qtbot,
        editor,
        handle.pos() + QPointF(-10, -10),
        handle.pos() + QPointF(35, 35),
    )

    assert path_item.pos() == before_pos
    assert path_item.scale() > before_scale


def test_pen_path_scale_handle_anchors_top_left(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    path = QPainterPath(QPointF(40, 30))
    path.lineTo(80, 60)
    item = editor.add_path_item(path)
    item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(h for h in editor._handles if getattr(h, "_role", "") == "scale")

    before = item.mapToScene(item.boundingRect().topLeft())
    editor.drag_handle(handle, item.mapToScene(QPointF(160, 120)))
    after = item.mapToScene(item.boundingRect().topLeft())

    assert item.scale() > 1.0
    assert abs(after.x() - before.x()) < 1.0
    assert abs(after.y() - before.y()) < 1.0


def test_starting_new_shape_clears_prior_selection(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(5, 5, 18, 12))
    rect.setSelected(True)
    editor.set_tool("rect")

    _drag_scene(qtbot, editor, (60, 55), (95, 72))

    assert not rect.isSelected()


def test_delete_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)

    editor.delete_selected_annotations()

    assert len(_markup_items(editor)) == 0
    editor._undo_stack.undo()
    assert len(_markup_items(editor)) == 1


def test_move_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)

    editor.move_selection_by(7, 3)

    assert rect.pos() == QPointF(7, 3)
    editor._undo_stack.undo()
    assert rect.pos() == QPointF(0, 0)


def test_resize_handle_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    before = QRectF(rect.rect())
    handle = next(h for h in editor._handles if getattr(h, "_role", "") == "br")

    editor._view._resize_handle = handle
    editor._view._resize_before = editor._geometry_snapshot(rect)
    editor.drag_handle(handle, rect.mapToScene(QPointF(80, 70)))
    after = QRectF(rect.rect())
    assert after != before
    editor._view._commit_resize()
    editor._undo_stack.undo()

    assert QRectF(rect.rect()) == before


def test_style_change_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_color(QColor("#2563eb"))
    editor.set_stroke_width(4)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)

    editor.set_color(QColor("#059669"))

    assert rect.pen().color().name() == "#059669"
    editor._undo_stack.undo()
    assert rect.pen().color().name() == "#2563eb"


def test_paste_is_single_undo(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)

    editor.copy_selected_annotations()
    editor.paste_annotations()

    assert len(_markup_items(editor)) == 2
    editor._undo_stack.undo()
    assert len(_markup_items(editor)) == 1


def test_paste_redo_restores_offset_position(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)

    editor.copy_selected_annotations()
    editor.paste_annotations()
    pasted = next(item for item in _markup_items(editor) if item is not rect)
    assert pasted.pos() == QPointF(12, 12)
    editor._undo_stack.undo()
    editor._undo_stack.redo()
    pasted_after_redo = next(item for item in _markup_items(editor) if item is not rect)

    assert pasted_after_redo.pos() == QPointF(12, 12)


def test_number_copy_paste_is_single_undo_and_preserves_label(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    number = editor.add_number_item(QRectF(40, 30, 0, 0))
    number.setSelected(True)

    editor.copy_selected_annotations()
    editor.paste_annotations()

    items = [item for item in _markup_items(editor) if item is not number]
    assert len(items) == 1
    pasted = items[0]
    labels = [
        child.text() for child in pasted.childItems()
        if hasattr(child, "text")
    ]
    assert labels == ["1"]
    editor._undo_stack.undo()
    assert _markup_items(editor) == [number]


def test_paste_with_empty_serialized_clipboard_does_not_add_undo_step(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor._annotation_clipboard = [None]
    before = editor._undo_stack.count()

    assert editor.paste_annotations() == []

    assert editor._undo_stack.count() == before


def test_cursor_reflects_handle_item_and_empty(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_zoom(1.0)
    rect = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    corner = next(h for h in editor._handles if getattr(h, "_role", "") == "br")

    assert editor._cursor_for(corner.pos()) == Qt.SizeFDiagCursor
    assert editor._cursor_for(QPointF(40, 35)) == Qt.SizeAllCursor
    assert editor._cursor_for(QPointF(5, 5)) == Qt.ArrowCursor
    editor.set_tool("rect")
    assert editor._cursor_for(QPointF(5, 5)) == Qt.CrossCursor


def test_cursor_uses_expanded_handle_hit_zone(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    corner = next(h for h in editor._handles if getattr(h, "_role", "") == "br")

    assert editor._cursor_for(corner.pos() + QPointF(-7, -7)) == Qt.SizeFDiagCursor


def test_double_click_text_in_select_tool_reedits(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text = editor.add_text_item(QPointF(20, 20), "peak")
    text.clearFocus()
    text.setSelected(False)
    editor.clear_selection()
    editor.set_tool("select")
    editor.set_zoom(1.0)
    editor.show()
    before = len([
        item for item in _markup_items(editor)
        if isinstance(item, QGraphicsTextItem)
    ])
    pos = editor._view.mapFromScene(QPointF(24, 24))

    qtbot.mouseDClick(editor._view.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()
    after = len([
        item for item in _markup_items(editor)
        if isinstance(item, QGraphicsTextItem)
    ])

    assert text.hasFocus()
    assert text.isSelected()
    assert any(getattr(h, "_target", None) is text for h in editor._handles)
    assert after == before


def test_shift_drag_line_constrains_to_horizontal_or_vertical(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_tool("line")

    _drag_scene(qtbot, editor, (10, 10), (90, 45), modifiers=Qt.ShiftModifier)

    line_item = _first_item(editor, QGraphicsLineItem)
    line = line_item.line()
    assert line.dx() == 0 or line.dy() == 0


def test_drag_crop_tool_resizes_background_and_undo_restores(qtbot):
    editor = MarkupEditor(_pixmap(120, 80))
    qtbot.addWidget(editor)
    editor.set_tool("crop")

    _drag_scene(qtbot, editor, (10, 15), (70, 55))

    assert editor._background_item.pixmap().size().width() == 120
    assert editor._background_item.pixmap().size().height() == 80
    assert editor.active_crop_rect().isValid()

    editor.apply_active_crop()

    assert editor._background_item.pixmap().size().width() == 60
    assert editor._background_item.pixmap().size().height() == 40
    editor._undo_stack.undo()
    assert editor._background_item.pixmap().size().width() == 120
    assert editor._background_item.pixmap().size().height() == 80


def test_markup_items_exclude_number_children_and_crop_overlay(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    number = editor.add_number_item(QRectF(40, 30, 0, 0))
    editor.set_active_crop_rect(QRectF(5, 5, 20, 20))

    items = editor._markup_items()

    assert number in items
    assert all(item.parentItem() is None for item in items)
    assert all(item.data(0) != "crop_overlay" for item in items)
    assert len(items) == 1


def test_crop_does_not_translate_number_children_independently(qtbot):
    editor = MarkupEditor(_pixmap(120, 80))
    qtbot.addWidget(editor)
    number = editor.add_number_item(QRectF(40, 30, 0, 0))
    child_positions = [QPointF(child.pos()) for child in number.childItems()]

    editor.apply_crop_rect(QRectF(10, 15, 70, 50))

    assert [child.pos() for child in number.childItems()] == child_positions
    assert number.sceneBoundingRect().center() == QPointF(30, 15)


def test_click_text_tool_adds_inline_editable_label(qtbot, monkeypatch):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    assert not hasattr(editor, "_get_text_value")
    editor.set_tool("text")

    _click_scene(qtbot, editor, (20, 20))

    text_items = [
        item for item in _markup_items(editor)
        if isinstance(item, QGraphicsTextItem)
    ]
    assert len(text_items) == 1
    assert text_items[0].textInteractionFlags() & Qt.TextEditorInteraction
    assert text_items[0].hasFocus()


def test_text_tool_click_existing_text_reopens_it_without_adding_new_item(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_tool("text")

    _click_scene(qtbot, editor, (20, 20))
    text_item = _first_item(editor, QGraphicsTextItem)
    text_item.setPlainText("peak")
    text_item.clearFocus()
    QApplication.processEvents()
    _click_scene(qtbot, editor, (22, 22))

    text_items = [
        item for item in _markup_items(editor)
        if isinstance(item, QGraphicsTextItem)
    ]
    assert text_items == [text_item]
    assert text_item.hasFocus()


def test_text_tool_drag_existing_text_moves_instead_of_editing(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    text_item.clearFocus()
    editor.set_tool("text")
    before = QPointF(text_item.pos())

    _drag_scene(qtbot, editor, (24, 24), (58, 44))

    assert text_item.pos().x() > before.x() + 25
    assert text_item.pos().y() > before.y() + 15
    assert not text_item.hasFocus()


def test_selected_text_has_resize_handle_that_scales_text(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    text_item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    handle = next(handle for handle in editor._handles if handle._target is text_item)

    editor.drag_handle(handle, text_item.mapToScene(QPointF(120, 80)))

    assert text_item.scale() > 1.0


def test_default_text_font_scales_with_image_and_beats_qt_default(qtbot):
    editor = MarkupEditor(_pixmap(1600, 900))
    qtbot.addWidget(editor)

    text_item = editor.add_text_item(QPointF(20, 20), "peak")

    # ~3.5% of image height, far larger than Qt's ~12px default for a copy
    # grabbed at hi-DPI.
    assert text_item.font().pixelSize() >= 30


def test_empty_text_box_is_discarded_on_focus_out(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_tool("text")

    _click_scene(qtbot, editor, (20, 20))
    text_item = _first_item(editor, QGraphicsTextItem)
    text_item.clearFocus()
    QApplication.processEvents()

    text_items = [
        item for item in _markup_items(editor)
        if isinstance(item, QGraphicsTextItem)
    ]
    assert text_items == []


def test_selected_text_box_can_be_deleted(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    text_item.clearFocus()
    QApplication.processEvents()

    editor.set_tool("select")
    text_item.setSelected(True)
    editor.delete_selected_annotations()

    assert text_item.scene() is None
    assert text_item not in _markup_items(editor)
    # ...and the deletion is undoable.
    editor._undo_stack.undo()
    assert text_item.scene() is editor._scene


def test_text_focus_out_clears_selection_and_leaves_edit_mode(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.show()  # focus events are only delivered to a shown window
    QApplication.processEvents()  # let the window expose before focusing
    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    cursor = text_item.textCursor()
    cursor.select(cursor.Document)
    text_item.setTextCursor(cursor)
    assert text_item.textCursor().hasSelection()

    text_item.clearFocus()
    QApplication.processEvents()

    # The grey highlight band must not persist once the box loses focus...
    assert not text_item.textCursor().hasSelection()
    # ...and the box stops swallowing keys so Delete can remove it.
    assert text_item.textInteractionFlags() == Qt.NoTextInteraction


def test_number_badge_default_font_scales_with_image(qtbot):
    editor = MarkupEditor(_pixmap(1600, 900))
    qtbot.addWidget(editor)

    group = editor.add_number_item(QRectF(40, 30, 0, 0))

    label = next(
        child for child in group.childItems()
        if isinstance(child, QGraphicsSimpleTextItem)
    )
    assert label.font().pixelSize() >= 24


def test_number_counter_survives_undo_without_duplicating(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.add_number_item(QRectF(10, 10, 0, 0))  # 1
    editor.add_number_item(QRectF(30, 10, 0, 0))  # 2
    editor._undo_stack.undo()  # remove the "2" badge
    editor.add_number_item(QRectF(50, 10, 0, 0))  # must be 2 again, not 3

    labels = sorted(
        int(child.text())
        for item in editor._markup_items()
        for child in item.childItems()
        if isinstance(child, QGraphicsSimpleTextItem)
    )
    assert labels == [1, 2]


def test_stroke_width_change_on_text_adds_no_undo_step(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    text_item.clearFocus()
    QApplication.processEvents()
    editor.set_tool("select")
    text_item.setSelected(True)
    before = editor._undo_stack.index()

    editor.set_stroke_width(8)

    assert editor._undo_stack.index() == before


def test_enter_does_not_finish_copy(qtbot):
    calls = []
    editor = MarkupEditor(_pixmap(), on_done=lambda pix: calls.append(pix))
    qtbot.addWidget(editor)
    editor.show()
    QApplication.processEvents()

    qtbot.keyClick(editor, Qt.Key_Return)

    assert calls == []
    assert editor.isVisible()


def test_style_panel_marks_active_color_and_width(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    # Default state: red (#e53935) and width 4 are pre-selected.
    assert editor._color_buttons["#e53935"].isChecked()
    assert editor._width_buttons[4].isChecked()

    editor.set_color(QColor("#2563eb"))
    editor.set_stroke_width(8)

    assert editor._color_buttons["#2563eb"].isChecked()
    assert not editor._color_buttons["#e53935"].isChecked()
    assert editor._width_buttons[8].isChecked()
    assert not editor._width_buttons[4].isChecked()
    # exactly one of each row is highlighted
    assert sum(b.isChecked() for b in editor._color_buttons.values()) == 1
    assert sum(b.isChecked() for b in editor._width_buttons.values()) == 1


def test_delete_arrow_keys_and_copy_paste_operate_on_selection(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect_item = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect_item.setSelected(True)

    editor.move_selection_by(5, 0)
    assert rect_item.pos() == QPointF(5, 0)

    editor.copy_selected_annotations()
    editor.paste_annotations()
    assert len(_markup_items(editor)) == 2
    assert sum(1 for item in _markup_items(editor) if item.isSelected()) == 1

    editor.delete_selected_annotations()
    assert len(_markup_items(editor)) == 1


def test_toolbar_omits_delete_and_single_copy_buttons(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    labels = {
        button.text().replace("&", "").strip()
        for button in editor.findChildren(QAbstractButton)
        if button.text().strip()
    }

    assert "完成复制" in labels
    assert "保存" in labels
    assert labels.isdisjoint({"删除", "垃圾桶", "清除", "复制", "单独复制"})


def test_toolbar_layout_groups_align_roles(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    left = editor.findChild(QWidget, "markupToolbarLeftGroup")
    center = editor.findChild(QWidget, "markupToolbarCenterGroup")
    right = editor.findChild(QWidget, "markupToolbarRightGroup")

    assert left is not None
    assert center is not None
    assert right is not None
    assert editor.findChild(QAbstractButton, "markupCloseButton").parent() is left
    assert editor.findChild(QToolButton, "markupStyleButton").parent() is center
    assert editor.findChild(QAbstractButton, "markupUndoButton").parent() is center
    assert editor.findChild(QAbstractButton, "markupRedoButton").parent() is center
    assert editor.findChild(QAbstractButton, "markupSaveButton").parent() is right
    assert editor.findChild(QAbstractButton, "markupDoneButton").parent() is right
    assert all(
        button.parent() is center
        for button in editor.findChildren(QToolButton)
        if button.objectName().startswith("markupTool_")
    )


def test_close_undo_redo_are_icon_tool_buttons_and_still_work(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    close = editor.findChild(QToolButton, "markupCloseButton")
    undo = editor.findChild(QToolButton, "markupUndoButton")
    redo = editor.findChild(QToolButton, "markupRedoButton")

    for button in (close, undo, redo):
        assert button is not None
        assert button.text() == ""
        assert not button.icon().isNull()

    editor.add_rect_item(QRectF(10, 10, 30, 20))
    assert len(_markup_items(editor)) == 1
    undo.click()
    assert len(_markup_items(editor)) == 0
    redo.click()
    assert len(_markup_items(editor)) == 1


def test_toolbar_icon_buttons_are_large_enough_to_read(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    icon_buttons = [
        button for button in editor.findChildren(QToolButton)
        if button.objectName().startswith("markupTool_")
        or button.objectName() in {
            "markupCloseButton",
            "markupUndoButton",
            "markupRedoButton",
        }
    ]

    assert icon_buttons
    assert all(button.iconSize().width() >= 18 for button in icon_buttons)
    assert all(button.width() >= 36 for button in icon_buttons)


def test_toolbar_uses_icons_and_primary_done_button(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    tool_buttons = editor.findChildren(QToolButton)
    assert tool_buttons
    assert all(not button.icon().isNull() for button in tool_buttons)
    assert all(button.text() == "" for button in tool_buttons)

    done = editor.findChild(QPushButton, "markupDoneButton")
    assert done.property("variant") == "primary"


def test_markup_editor_has_no_dead_arrow_head_method(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    assert not hasattr(MarkupEditor, "_arrow_head")


def test_toolbar_buttons_expose_their_shortcuts(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    tips = {
        name: editor.findChild(QToolButton, name).toolTip()
        for name in (
            "markupCloseButton",
            "markupUndoButton",
            "markupRedoButton",
            "markupStyleButton",
        )
    }
    assert tips["markupCloseButton"] == "关闭 (Esc)"
    assert tips["markupUndoButton"] == "撤销 (Ctrl+Z)"
    assert tips["markupRedoButton"] == "重做 (Ctrl+Y)"
    assert tips["markupStyleButton"] == "样式（颜色 / 线宽） · [ ] 调线宽"


def _standard_binding_texts(standard_key):
    texts = set()
    for seq in QKeySequence.keyBindings(standard_key):
        if seq.isEmpty():
            continue
        portable = seq.toString(QKeySequence.PortableText)
        if portable:
            texts.add(portable)
    return texts


def test_markup_registers_every_qt_undo_redo_binding_once(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    wanted = _standard_binding_texts(QKeySequence.Undo) | _standard_binding_texts(
        QKeySequence.Redo
    )
    found = {}
    for shortcut in editor.findChildren(QShortcut):
        text = shortcut.key().toString(QKeySequence.PortableText)
        if text in wanted:
            found.setdefault(text, []).append(shortcut)
    assert set(found) == wanted
    assert all(len(shortcuts) == 1 for shortcuts in found.values())


def test_markup_text_edit_disables_history_shortcuts(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.show()
    QApplication.processEvents()
    for shortcut in (*editor._undo_shortcuts, *editor._redo_shortcuts):
        assert shortcut.isEnabled()

    text_item = editor.add_text_item(QPointF(20, 20), "peak")
    assert text_item.textInteractionFlags() & Qt.TextEditorInteraction
    for shortcut in (*editor._undo_shortcuts, *editor._redo_shortcuts):
        assert not shortcut.isEnabled()

    text_item.clearFocus()
    QApplication.processEvents()
    for shortcut in (*editor._undo_shortcuts, *editor._redo_shortcuts):
        assert shortcut.isEnabled()


def _temp_hint_settings(tmp_path):
    return QSettings(str(tmp_path / "markup-hints.ini"), QSettings.IniFormat)


def test_first_open_shows_capability_toast_and_retires_it(qtbot, tmp_path):
    settings = _temp_hint_settings(tmp_path)
    assert "markup.capabilities" not in hints.load_discovered(settings)

    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_hint_settings(settings)
    editor.show()
    QApplication.processEvents()

    assert editor._hint_toast is not None
    assert editor._hint_toast.isVisible()
    assert "markup.capabilities" in hints.load_discovered(settings)


def test_capability_toast_not_shown_when_already_discovered(qtbot, tmp_path):
    settings = _temp_hint_settings(tmp_path)
    hints.mark_discovered(settings, "markup.capabilities")

    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_hint_settings(settings)
    editor.show()
    QApplication.processEvents()

    assert editor._hint_toast is None
