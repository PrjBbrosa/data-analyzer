"""Selection toolbar contract: author-only, bounds, icon-first, flyouts."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt
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
    ShapeObject,
    StickyObject,
    default_board,
    make_ref,
)
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.ultraview_style import ULTRAVIEW_QSS_TOKENS
from tests.ui.test_ultraview_page import (
    FakePreview,
    _Harness,
    _image,
    _prepare_free_grid,
    _select_card,
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


def test_panel_and_mode_states_keep_titanium_amber_gradient_tokens():
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_START"] == "#3C8495"
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_END"] == "#F0A44C"
    assert ULTRAVIEW_QSS_TOKENS["UV_RAIL_ACTIVE_HOVER"] == "#2F7181"


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
    assert start != end
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert "UV_RAIL_ACTIVE_START" in qss
    assert "qlineargradient" in qss
    del host
