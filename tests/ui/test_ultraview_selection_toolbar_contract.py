"""Selection toolbar contract: author-only, bounds, icon-first, flyouts."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QMenu, QToolButton, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import (
    FormatChoiceFlyout,
    SelectionToolbar,
    ShapePopover,
    StickyPopover,
    ToolFlyoutSurface,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    board_box_to_pixels,
    pixels_to_board_point,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_selection import (
    FORBIDDEN_TOOLBAR_WORDS,
    resolve_selection_capabilities,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import AuthorKey, CardKey
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_DRAW,
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_STICKY,
    PANEL_FILTER,
    PANEL_LAYOUT,
    PANEL_LIBRARY,
    PANEL_UNPLACED,
    RELEASE_AUTHOR_TOOLS,
    ToolRail,
)
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    GridRect,
    ShapeObject,
    StickyObject,
    TextObject,
    default_board,
    make_ref,
    set_free_grid_rect,
)
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.ultraview_style import ULTRAVIEW_QSS_TOKENS
from tests.ui.test_ultraview_page import (
    FakePreview,
    _Harness,
    _blank_board_point,
    _drag_card,
    _image,
    _prepare_free_grid,
    _select_card,
    _send_mouse_move,
)


def _refresh(page) -> None:
    page._refresh_author_toolbar()
    QApplication.processEvents()


def test_card_selection_does_not_show_author_property_toolbar(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "card-0")
    ref = make_ref("time", "card-0")
    harness.page.set_preview(ref, FakePreview(ref=ref, image=_image(), axis_kind="time"))
    _select_card(card)
    _refresh(harness.page)
    toolbar = harness.page.selection_toolbar()
    assert not toolbar.isVisible()
    caps = harness.page._selection_capabilities()
    assert caps.kind == "card"
    assert caps.controls == ()


def test_card_hover_reveals_existing_action_bar_and_leave_hides_it(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "hover-0")
    card.apply_model(replace(card.model(), show_card_actions=False))
    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    QApplication.processEvents()
    assert card.action_bar().isHidden()
    QApplication.sendEvent(card, QEvent(QEvent.Enter))
    QApplication.processEvents()
    assert card.action_bar().isVisible()
    actions = [
        button.property("contextAction")
        for button in card.action_bar().findChildren(QToolButton)
        if button.isVisible()
    ]
    assert set(actions) >= {"open", "focus", "remove", "more"}
    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    QApplication.processEvents()
    assert card.action_bar().isHidden()


def test_card_action_preference_keeps_hover_bar_visible(qtbot):
    harness = _Harness(qtbot)
    from tests.ui.test_ultraview_page import _set_card_actions_pinned

    _set_card_actions_pinned(harness)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "pref-0")
    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    QApplication.processEvents()
    assert card.action_bar().isVisible()


def test_author_selection_shows_toolbar_near_bounds(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "tb-0")
    top = StickyObject("note-top", "sticky", box=BoardBox(2.0, 2.0, 3.0, 2.0), text="上")
    bottom = StickyObject("note-bot", "sticky", box=BoardBox(2.0, 18.0, 3.0, 2.0), text="下")
    harness.board.author_objects = [top, bottom]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    harness.page.interaction().select_only_author("note-top")
    free.sync_selection_projection()
    _refresh(harness.page)
    assert toolbar.isVisible()
    y_top = toolbar.y()
    harness.page.interaction().select_only_author("note-bot")
    free.sync_selection_projection()
    _refresh(harness.page)
    y_bot = toolbar.y()
    assert y_top != y_bot
    assert not (y_top == 56 and y_bot == 56)
    assert toolbar.height() == 48


def test_toolbar_contains_no_forbidden_word_labels(qtbot):
    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    note = StickyObject("n", "sticky", box=BoardBox(1, 1, 3, 2), text="a")
    shape = ShapeObject("s", "shape", box=BoardBox(1, 1, 4, 3), shape="rectangle")
    board = default_board()
    board.author_objects = [note, shape]
    for key in (AuthorKey("n"), AuthorKey("s")):
        caps = resolve_selection_capabilities(board, (key,))
        toolbar.apply_capabilities(caps)
        toolbar.show()
        assert toolbar.forbidden_visible_words() == ()
        for text in toolbar.visible_button_texts():
            assert text not in FORBIDDEN_TOOLBAR_WORDS


def test_sticky_click_opens_anchored_large_swatch_flyout(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "n-0")
    harness.page._tool_rail.set_creation_enabled(True)
    sticky_btn = harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert sticky_btn is not None
    QTest.mouseClick(sticky_btn, Qt.LeftButton)
    QApplication.processEvents()
    flyout = harness.page.sticky_popover()
    assert flyout.isVisible()
    buttons = flyout.palette_buttons()
    assert len(buttons) == 16
    assert buttons[0].width() >= 48
    assert 128 <= flyout.width() <= 140
    texts = [child.text() for child in flyout.findChildren(QToolButton) if child.text()]
    assert "固定连续创建" not in texts
    assert any(text == "Stack" for text in texts)


def test_shapes_click_opens_combined_shape_connector_flyout(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "s-0")
    harness.page._tool_rail.set_creation_enabled(True)
    shapes_btn = harness.page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert shapes_btn is not None
    QTest.mouseClick(shapes_btn, Qt.LeftButton)
    QApplication.processEvents()
    flyout = harness.page.shape_popover()
    assert flyout.isVisible()
    kinds = {button.property("catalogKind") for button in flyout.cell_buttons()}
    assert {"line", "arrow", "elbow_arrow", "rectangle", "oval"} <= kinds
    assert "block_arrow" not in kinds
    texts = " ".join(button.text() for button in flyout.findChildren(QToolButton))
    assert "更多形状" not in texts
    assert "固定连续创建" not in texts


def test_draw_click_opens_icon_preset_flyout(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "p-0")
    harness.page._tool_rail.set_creation_enabled(True)
    draw_btn = harness.page.tool_rail().tool_button(AUTHOR_TOOL_DRAW)
    assert draw_btn is not None
    QTest.mouseClick(draw_btn, Qt.LeftButton)
    QApplication.processEvents()
    flyout = harness.page.draw_popover()
    assert flyout.isVisible()
    assert flyout.session_button("eraser") is not None
    assert flyout.session_button("lasso") is not None
    body = " ".join(child.text() for child in flyout.findChildren(QWidget) if hasattr(child, "text"))
    assert "不做像素擦除" not in body


def test_existing_panel_action_inventory_is_unchanged(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    assert tuple(rail._buttons) == (PANEL_LIBRARY, PANEL_LAYOUT, PANEL_FILTER, PANEL_UNPLACED)
    assert RELEASE_AUTHOR_TOOLS == (
        "select",
        AUTHOR_TOOL_STICKY,
        "text",
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    )
    assert rail.tool_button("connector") is None
    assert rail.tool_button(AUTHOR_TOOL_DRAW) is not None
    assert rail.free_grid_button() is not None
    assert rail.sync_all_button() is not None


def test_selection_toolbar_y_follows_author_bounds_not_fixed_56(qtbot):
    test_author_selection_shows_toolbar_near_bounds(qtbot)


def test_mixed_card_kinds_spine_is_card():
    board = default_board()
    time_ref = make_ref("time", "t")
    fft_ref = make_ref("fft", "f")
    caps = resolve_selection_capabilities(
        board,
        (CardKey(time_ref), CardKey(fft_ref)),
        axis_kinds={time_ref: "time", fft_ref: "fft"},
    )
    assert caps.kind == "card"
    assert caps.controls == ()
    assert caps.can_duplicate is False


def test_card_single_select_clicks_emit_existing_page_signals(qtbot):
    harness = _Harness(qtbot)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "act-0")
    ref = make_ref("time", "act-0")
    harness.page.set_preview(ref, FakePreview(ref=ref, image=_image(), axis_kind="time"))
    card.apply_model(replace(card.model(), show_card_actions=True))
    QApplication.processEvents()
    open_btn = card.action_button("open")
    focus_btn = card.action_button("focus")
    fit_btn = card.action_button("fit")
    assert open_btn is not None and focus_btn is not None and fit_btn is not None
    QTest.mouseClick(open_btn, Qt.LeftButton)
    QTest.mouseClick(focus_btn, Qt.LeftButton)
    QApplication.processEvents()
    assert harness.opened == [("time", "act-0")]
    assert harness.focused == [("time", "act-0")]
    assert not harness.page.selection_toolbar().isVisible()


def test_more_menu_contains_delete_and_resident_controls_do_not(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "more-0")
    note = StickyObject("note-more", "sticky", box=BoardBox(2.0, 2.0, 3.0, 2.0), text="便签")
    harness.board.author_objects = [note]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("note-more")
    free.sync_selection_projection()
    _refresh(harness.page)
    toolbar = harness.page.selection_toolbar()
    caps = resolve_selection_capabilities(harness.board, (AuthorKey("note-more"),))
    assert "delete" not in {control.key for control in caps.controls}
    assert toolbar.button("delete") is None
    more = toolbar.more_button()
    QTest.mouseClick(more, Qt.LeftButton)
    QApplication.processEvents()
    menu = QApplication.activePopupWidget()
    assert isinstance(menu, QMenu)
    labels = [action.text() for action in menu.actions()]
    assert "删除" in labels
    menu.close()


def test_sticky_and_shape_flyouts_shrink_to_content(qtbot):
    sticky = StickyPopover()
    shapes = ShapePopover()
    for widget in (sticky, shapes):
        qtbot.addWidget(widget)
        widget.show()
        widget.adjustSize()
    assert isinstance(sticky, ToolFlyoutSurface)
    assert 128 <= sticky.width() <= 140
    inner = shapes.findChild(QFrame, "ultraViewToolFlyoutInner")
    assert inner is not None


def test_format_picker_opens_instead_of_silent_cycle(qtbot):
    picker = FormatChoiceFlyout()
    qtbot.addWidget(picker)
    chosen: list[object] = []
    picker.choice_selected.connect(chosen.append)
    picker.present_labels((("yellow", "黄"), ("blue", "蓝")), current="yellow")
    picker.adjustSize()
    picker.show()
    chips = [
        child
        for child in picker.findChildren(QToolButton)
        if child.property("choiceValue") == "blue"
    ]
    assert chips
    QTest.mouseClick(chips[0], Qt.LeftButton)
    QApplication.processEvents()
    assert chosen == ["blue"]


def test_panel_and_mode_states_keep_selected_blue_tokens():
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED"] == "#4262FF"
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED_WASH"] == "#E9EDFF"
    assert ULTRAVIEW_QSS_TOKENS["UV_SELECTED_HOVER"] == "#DDE3FF"


def test_mode_and_panel_buttons_render_start_and_end_pixels(qtbot, qapp):
    load_stylesheet(qapp)
    host = QFrame()
    host.setObjectName("ultraViewToolRail")
    host.setAttribute(Qt.WA_StyledBackground, True)
    button = QToolButton(host)
    button.setProperty("chrome", "ultraview")
    button.setProperty("role", "icon")
    button.setProperty("primaryFill", "true")
    button.setAttribute(Qt.WA_StyledBackground, True)
    button.setAutoFillBackground(True)
    button.setFixedSize(46, 46)
    qtbot.addWidget(host)
    host.resize(80, 80)
    button.move(8, 8)
    host.show()
    button.show()
    QApplication.processEvents()
    button.style().unpolish(button)
    button.style().polish(button)
    host.style().unpolish(host)
    host.style().polish(host)
    QApplication.processEvents()
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    button.render(painter)
    painter.end()
    start = QColor(image.pixelColor(8, 8))
    end = QColor(image.pixelColor(button.width() - 9, button.height() - 9))
    assert start.blue() >= start.red()
    assert end.blue() >= end.red()
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert "UV_SELECTED_WASH" in qss
    del host


def _visible_control_keys(toolbar: SelectionToolbar) -> tuple[str, ...]:
    keys = []
    for index in range(toolbar._body_layout.count()):
        widget = toolbar._body_layout.itemAt(index).widget()
        if isinstance(widget, QToolButton) and widget.isVisible():
            key = widget.property("formatKey")
            if key:
                keys.append(str(key))
    return tuple(keys)


def test_same_selection_refresh_reuses_toolbar_buttons_and_geometry(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "id-0")
    text = TextObject("t-id", "text", box=BoardBox(4.0, 8.0, 4.0, 2.0), text="Hello")
    harness.board.author_objects = [text]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("t-id")
    free.sync_selection_projection()
    _refresh(harness.page)
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    font = toolbar.button("font_role")
    size = toolbar.button("font_size")
    assert font is not None and size is not None
    before_rect = QRect(toolbar.geometry())
    before_hint = toolbar.sizeHint()
    before_keys = _visible_control_keys(toolbar)
    before_dividers = toolbar.group_dividers()
    font_rect = QRect(font.geometry())
    size_rect = QRect(size.geometry())
    divider_xs = tuple(divider.mapTo(toolbar, divider.rect().topLeft()).x() for divider in before_dividers)
    assert font.x() < size.x()
    assert not any(font.geometry().right() < x < size.x() for x in divider_xs)
    _refresh(harness.page)
    assert toolbar.button("font_role") is font
    assert toolbar.button("font_size") is size
    assert QRect(toolbar.geometry()) == before_rect
    assert toolbar.sizeHint() == before_hint
    assert _visible_control_keys(toolbar) == before_keys
    assert toolbar.group_dividers() == before_dividers
    assert QRect(font.geometry()) == font_rect
    assert QRect(size.geometry()) == size_rect


def test_picker_open_same_schema_refresh_does_not_rebuild_or_collapse(qtbot, qapp):
    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(1182, 768)
    QApplication.processEvents()
    free, _cards = _prepare_free_grid(harness, qtbot, "pick-0")
    text = TextObject("t1", "text", box=BoardBox(4.0, 8.0, 4.0, 2.0), text="Hello")
    harness.board.author_objects = [text]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("t1")
    free.sync_selection_projection()
    _refresh(harness.page)
    toolbar = harness.page.selection_toolbar()
    picker = harness.page.format_picker()
    font = toolbar.button("font_role")
    assert font is not None
    QTest.mouseClick(font, Qt.LeftButton)
    QApplication.processEvents()
    assert picker.isVisible()
    before_overlay = harness.page.canvas_host().active_overlay()
    before_key = harness.page._format_picker_key
    before_toolbar = QRect(toolbar.geometry())
    before_picker = QRect(picker.geometry())
    before_content = picker.content_size()
    before_choices = sum(
        1
        for child in picker.findChildren(QToolButton)
        if child.isVisible() and child.property("choiceValue") is not None
    )
    before_keys = _visible_control_keys(toolbar)
    QApplication.processEvents()
    _refresh(harness.page)
    QApplication.processEvents()
    assert harness.page.canvas_host().active_overlay() == before_overlay
    assert harness.page._format_picker_key == before_key == "font_role"
    assert picker.isVisible() is True
    assert QRect(toolbar.geometry()) == before_toolbar
    assert QRect(picker.geometry()) == before_picker
    assert picker.content_size() == before_content
    assert before_choices == 3
    assert _visible_control_keys(toolbar) == before_keys
    assert toolbar.button("font_role") is font
    QTest.mouseClick(font, Qt.LeftButton)
    QApplication.processEvents()
    assert picker.isVisible() is False
    assert harness.page._format_picker_key == ""
    assert QRect(toolbar.geometry()) == before_toolbar


def _host_rect(page, widget) -> QRect:
    origin = widget.mapTo(page._canvas_host, QPoint(0, 0))
    return QRect(origin, widget.size())


def _inflate(rect: QRect, margin: int) -> QRect:
    return rect.adjusted(-margin, -margin, margin, margin)


def test_minimap_avoids_bottom_right_card_selection_or_folds(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1600, 900)
    _prepare_free_grid(harness, qtbot, "mini-br")
    ref = make_ref("time", "mini-br")
    assert set_free_grid_rect(harness.board, ref, GridRect(16, 12, 8, 6)) == []
    harness.page.set_board(harness.board)
    harness.page.set_board_zoom(1.6)
    QApplication.processEvents()
    scroll = harness.page.board_scroll_area()
    scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    QApplication.processEvents()
    card = harness.page.card_widget("time", "mini-br")
    assert card is not None
    _select_card(card)
    _refresh(harness.page)
    harness.page._refresh_minimap()
    QApplication.processEvents()
    minimap = harness.page.free_grid_minimap()
    bounds = harness.page._selection_bounds_in_host()
    assert bounds is not None
    handles = _inflate(bounds, 18)
    toolbar = harness.page.selection_toolbar()
    if not minimap.isVisible():
        return
    mini = _host_rect(harness.page, minimap)
    assert not mini.intersects(handles)
    if toolbar.isVisible():
        assert not mini.intersects(_host_rect(harness.page, toolbar))


def test_minimap_hides_during_card_move_and_restores_after_release(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1600, 900)
    _free, (card,) = _prepare_free_grid(harness, qtbot, "mini-g")
    harness.page.set_board_zoom(1.6)
    QApplication.processEvents()
    _select_card(card)
    harness.page._refresh_minimap()
    QApplication.processEvents()
    minimap = harness.page.free_grid_minimap()
    assert minimap.isVisible()
    start = QPoint(40, 40)
    end = QPoint(120, 90)
    _drag_card(card, start, end, release=False)
    QApplication.processEvents()
    assert not minimap.isVisible()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)
    QApplication.processEvents()
    harness.page._refresh_minimap()
    QApplication.processEvents()
    bounds = harness.page._selection_bounds_in_host()
    if minimap.isVisible():
        mini = _host_rect(harness.page, minimap)
        if bounds is not None:
            assert not mini.intersects(_inflate(bounds, 18))
    else:
        assert harness.page._minimap_geometry_gesture_active() is False


def test_minimap_folds_during_author_geometry_gesture(qtbot):
    harness = _Harness(qtbot)
    harness.page.resize(1600, 900)
    free, _cards = _prepare_free_grid(harness, qtbot, "mini-auth")
    harness.page.set_board_zoom(1.0)
    blank = _blank_board_point(free)
    origin = pixels_to_board_point(
        (float(blank.x()), float(blank.y())),
        free.metrics(),
        origin_offset=free._workspace_origin_offset(),
    )
    assert origin is not None
    note = StickyObject(
        "geo-note",
        "sticky",
        box=BoardBox(origin[0], origin[1], 3.0, 2.0),
        text="便签",
    )
    harness.board.author_objects = [note]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page._refresh_minimap()
    QApplication.processEvents()
    facts = free.interaction_facts()
    assert facts["author_geometry_active"] is False
    mapped = board_box_to_pixels(
        (note.box.x, note.box.y, note.box.width, note.box.height),
        free.metrics(),
        origin_offset=free._workspace_origin_offset(),
    )
    assert mapped is not None
    start = QPoint(int(mapped[0] + mapped[2] / 2), int(mapped[1] + mapped[3] / 2))
    end = QPoint(start.x() + 24, start.y())
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(free, end)
    QApplication.processEvents()
    assert free.interaction_facts()["author_geometry_active"] is True
    assert harness.page._minimap_geometry_gesture_active() is True
    harness.page._sync_minimap_placement()
    QApplication.processEvents()
    minimap = harness.page.free_grid_minimap()
    assert not minimap.isVisible()
    QTest.mouseRelease(free, Qt.LeftButton, Qt.NoModifier, end)
    QApplication.processEvents()
    harness.page._refresh_minimap()
    QApplication.processEvents()
    assert free.interaction_facts()["author_geometry_active"] is False
