"""UltraView card action bar: remove affordance, alignment, and narrow LOD."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QPoint, QSize, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox, QToolButton, QWidget

import mf4_analyzer.ui.chart_stack.ultraview.widgets as ultraview_widgets
from mf4_analyzer.ui.chart_stack.ultraview.viewport import LOD_FULL, LOD_TITLE_ONLY
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    CardViewModel,
    FreeGridBoard,
    FreeGridCard,
    UltraViewCard,
)
from mf4_analyzer.ui.ultraview_state import (
    STATUS_MISSING,
    FreeGridPlacement,
    GridBounds,
    GridRect,
    UltraViewRef,
)
from mf4_analyzer.ui_kit import load_stylesheet

_REMOVE_TIP = "从当前 Board 移除（不删除源 View）"
_FULL_ACTIONS = ("open", "focus", "fit", "remove", "more")
_COMPACT_ACTIONS = ("open", "focus", "remove", "more")
_SIZE_100 = QSize(512, 288)
_SIZE_66 = QSize(338, 190)


def _prepare_app(qapp) -> None:
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)


def _model(**overrides) -> CardViewModel:
    payload = dict(
        slot_id="slot-0",
        section="time",
        view_id="view-1",
        title="View 1",
        status=STATUS_MISSING,
        # These card-local chrome tests exercise the fully exposed action bar.
        # The workspace default itself is covered by Page/state tests.
        show_card_actions=True,
    )
    payload.update(overrides)
    return CardViewModel(**payload)


def _make_card(qtbot, qapp, *, free_grid: bool = False, size: QSize = _SIZE_100):
    _prepare_app(qapp)
    card = FreeGridCard(_model()) if free_grid else UltraViewCard(_model())
    qtbot.addWidget(card)
    card.resize(size)
    card.show()
    qtbot.waitExposed(card)
    qapp.processEvents()
    return card


def _header(card: UltraViewCard) -> QWidget:
    header = card.findChild(QWidget, "ultraViewCardHeader")
    assert header is not None
    return header


def _visible_actions(card: UltraViewCard) -> list[str]:
    bar = card.action_bar()
    return [
        button.property("contextAction")
        for button in bar.findChildren(QToolButton)
        if button.isVisible()
    ]


def _button_header_dy(button: QToolButton, header: QWidget) -> int:
    header_cy = header.contentsRect().center().y()
    button_c = button.mapTo(header, button.rect().center())
    return abs(int(button_c.y()) - int(header_cy))


def _assert_action_centers(card: UltraViewCard, actions) -> None:
    header = _header(card)
    card.layout().activate()
    header.layout().activate()
    QApplication.processEvents()
    for action in actions:
        button = card.action_button(action)
        assert button is not None and button.isVisible(), action
        assert _button_header_dy(button, header) <= 1, (
            action,
            button.mapTo(header, button.rect().center()).y(),
            header.contentsRect().center().y(),
            header.height(),
            card.action_bar().height(),
            card.action_bar().sizeHint().height(),
        )


def _tab_object_names(card: UltraViewCard) -> list[str]:
    names: list[str] = []
    seen: set[int] = set()
    widget = card
    for _ in range(64):
        widget = widget.nextInFocusChain()
        ident = id(widget)
        if ident in seen:
            break
        seen.add(ident)
        if widget is card or card.isAncestorOf(widget):
            policy = widget.focusPolicy()
            if policy & Qt.TabFocus and widget.isVisible() and widget.isEnabled():
                names.append(widget.objectName())
    return names


@pytest.mark.parametrize("free_grid", (False, True))
def test_action_order_includes_remove_button(qtbot, qapp, free_grid):
    card = _make_card(qtbot, qapp, free_grid=free_grid)
    assert _visible_actions(card) == list(_FULL_ACTIONS)
    remove = card.action_button("remove")
    assert remove is not None
    assert remove.objectName() == "ultraViewCardRemoveButton"
    assert isinstance(remove, QToolButton)
    assert remove.focusPolicy() == Qt.TabFocus
    assert not remove.icon().isNull()


@pytest.mark.parametrize("free_grid", (False, True))
def test_remove_tooltip_and_accessible_name_are_exact(qtbot, qapp, free_grid):
    card = _make_card(qtbot, qapp, free_grid=free_grid)
    remove = card.action_button("remove")
    assert remove is not None
    assert remove.toolTip() == _REMOVE_TIP
    assert remove.accessibleName() == _REMOVE_TIP


def test_card_action_bar_uses_font_awesome_and_marks_existing_remove_as_danger(
    qtbot, qapp, monkeypatch
):
    """Only presentation changes: action order and typed signal contracts stay put."""
    assert hasattr(ultraview_widgets, "qta")
    calls: list[str] = []
    real_icon = ultraview_widgets.qta.icon

    def record_icon(name, *args, **kwargs):
        calls.append(str(name))
        return real_icon(name, *args, **kwargs)

    monkeypatch.setattr(ultraview_widgets.qta, "icon", record_icon)
    card = _make_card(qtbot, qapp)

    assert set(calls) >= {
        "fa5s.external-link-alt",
        "fa5s.expand",
        "fa5s.vector-square",
        "fa5s.trash-alt",
        "fa5s.ellipsis-v",
    }
    assert _visible_actions(card) == list(_FULL_ACTIONS)
    remove = card.action_button("remove")
    assert remove is not None
    assert remove.property("danger") == "true"
    stylesheet = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert '[role="cardAction"][danger="true"]' not in stylesheet


def test_unpinned_card_actions_only_show_on_hover_or_keyboard_focus(qtbot, qapp):
    card = _make_card(qtbot, qapp)
    card.apply_model(replace(card.model(), show_card_actions=False))
    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    qapp.processEvents()
    assert card.action_bar().isHidden()

    QApplication.sendEvent(card, QEvent(QEvent.Enter))
    qapp.processEvents()
    assert card.action_bar().isVisible()

    QApplication.sendEvent(card, QEvent(QEvent.Leave))
    card.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    assert card.action_bar().isVisible()

    card.clearFocus()
    qapp.processEvents()
    qapp.processEvents()
    assert card.action_bar().isHidden()


@pytest.mark.parametrize("free_grid", (False, True))
def test_remove_click_emits_existing_signal_without_other_mutations(
    qtbot, qapp, monkeypatch, free_grid
):
    card = _make_card(qtbot, qapp, free_grid=free_grid)
    removed: list[tuple[str, str]] = []
    other: list[tuple[str, str, str]] = []
    boxes: list[QMessageBox] = []
    real_init = QMessageBox.__init__

    def _spy_init(self, *args, **kwargs):
        boxes.append(self)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(QMessageBox, "__init__", _spy_init)
    card.remove_ref_requested.connect(lambda s, v: removed.append((s, v)))
    card.open_source_requested.connect(lambda s, v: other.append(("open", s, v)))
    card.move_to_unplaced_requested.connect(lambda s, v: other.append(("tray", s, v)))
    card.autofit_requested.connect(lambda s, v: other.append(("fit", s, v)))
    card.focus_requested.connect(lambda s, v: other.append(("focus", s, v)))
    card.sync_requested.connect(lambda s, v: other.append(("sync", s, v)))
    card.rebind_arm_requested.connect(lambda s, v: other.append(("rebind", s, v)))

    QTest.mouseClick(card.action_button("remove"), Qt.LeftButton)
    qapp.processEvents()

    assert removed == [("time", "view-1")]
    assert other == []
    assert boxes == []
    assert qapp.activeModalWidget() is None


@pytest.mark.parametrize("size", (_SIZE_66, _SIZE_100))
def test_action_buttons_center_in_header_contents_rect(qtbot, qapp, size):
    card = _make_card(qtbot, qapp, size=size)
    bar = card.action_bar()
    assert bar.height() == bar.sizeHint().height()
    assert bar.minimumSizeHint().height() == bar.sizeHint().height()
    _assert_action_centers(card, _FULL_ACTIONS)


def test_action_button_centers_survive_optional_dpr2(qtbot, qapp):
    card = _make_card(qtbot, qapp)
    handle = card.windowHandle()
    if handle is None:
        pytest.skip("offscreen card has no QWindow")
    try:
        handle.setDevicePixelRatio(2.0)
    except Exception:
        pytest.skip("offscreen backend rejected DPR 2.0")
    card.resize(_SIZE_100)
    qapp.processEvents()
    if abs(handle.devicePixelRatio() - 2.0) > 0.01:
        pytest.skip("offscreen DPR stayed at 1.0")
    _assert_action_centers(card, _FULL_ACTIONS)


def test_title_only_lod_keeps_open_focus_remove(qtbot, qapp):
    card = _make_card(qtbot, qapp)
    card.apply_lod(LOD_TITLE_ONLY, show_title=True, show_source=True)
    qapp.processEvents()
    assert card.action_bar().isVisible()
    assert _visible_actions(card) == list(_COMPACT_ACTIONS)
    remove = card.action_button("remove")
    assert remove is not None and remove.isVisible()
    fit = card.action_button("fit")
    assert fit is not None and not fit.isVisible()
    more = card.action_button("more")
    assert more is not None and more.isVisible()
    _assert_action_centers(card, _COMPACT_ACTIONS)


def test_narrow_width_keeps_remove_visible(qtbot, qapp):
    card = _make_card(qtbot, qapp, size=QSize(140, 96))
    card.apply_lod(LOD_TITLE_ONLY, show_title=True, show_source=True)
    qapp.processEvents()
    remove = card.action_button("remove")
    assert remove is not None
    assert remove.isVisible()
    assert remove.objectName() == "ultraViewCardRemoveButton"
    assert "remove" in _visible_actions(card)
    assert "open" in _visible_actions(card)
    assert "focus" in _visible_actions(card)


def test_narrow_width_omits_title_before_remove(qtbot, qapp):
    card = _make_card(qtbot, qapp, size=QSize(140, 96))
    qapp.processEvents()
    remove = card.action_button("remove")
    assert remove is not None and remove.isVisible()
    assert not card._title.isVisible() or card._title.width() <= 8


def test_more_menu_does_not_duplicate_header_open_focus_or_remove(qtbot, qapp):
    card = _make_card(qtbot, qapp)
    remove = card.action_button("remove")
    assert remove is not None and remove.isVisible()
    menu = card.make_context_menu()
    texts = [action.text() for action in menu.actions() if action.text()]
    assert "打开原 View" not in texts
    assert "临时放大" not in texts
    assert not any("移除" in text for text in texts)
    assert remove.isVisible()
    assert "ultraViewCardRemoveButton" in _tab_object_names(card)


def test_full_lod_restore_shows_fit_again(qtbot, qapp):
    card = _make_card(qtbot, qapp)
    card.apply_lod(LOD_TITLE_ONLY, show_title=True, show_source=True)
    qapp.processEvents()
    assert not card.action_button("fit").isVisible()
    card.apply_lod(LOD_FULL, show_title=True, show_source=True)
    card.resize(_SIZE_100)
    qapp.processEvents()
    assert _visible_actions(card) == list(_FULL_ACTIONS)


def test_workspace_extent_remaps_runtime_geometry_without_mutating_placement(
    qtbot, qapp
):
    """The Page may grow a workspace; GridRect identity stays canonical."""
    _prepare_app(qapp)
    board = FreeGridBoard()
    qtbot.addWidget(board)
    ref = UltraViewRef("time", "view-1")
    placement = FreeGridPlacement(ref, GridRect(0, 0, 4, 3))
    board.set_free_grid((placement,), {ref: _model()})
    board.set_workspace_extent(GridBounds(-4, -4, 24, 56))
    board.show()
    qtbot.waitExposed(board)
    qapp.processEvents()

    card = board.card_for("time", "view-1")
    assert card is not None
    assert board.workspace_extent() == GridBounds(-4, -4, 24, 56)
    assert board._placements[ref].rect == GridRect(0, 0, 4, 3)
    assert card.geometry().x() > board.metrics().padding
    assert board.width() > board.metrics().board_width
    assert board.grid_anchor_at(card.geometry().center()).column == pytest.approx(
        2.0, abs=0.02
    )


def test_workspace_gesture_signal_has_a_single_active_lifetime(qtbot, qapp):
    _prepare_app(qapp)
    board = FreeGridBoard()
    qtbot.addWidget(board)
    board.resize(320, 220)
    board.show()
    qtbot.waitExposed(board)
    seen: list[tuple[bool, object]] = []

    def _record(active, global_pos) -> None:
        seen.append((bool(active), global_pos))

    board.workspace_gesture_changed.connect(_record)

    QTest.mousePress(board, Qt.LeftButton, pos=board.rect().center())
    QTest.mouseMove(board, board.rect().center() + QPoint(12, 8))
    QTest.mouseRelease(board, Qt.LeftButton, pos=board.rect().center() + QPoint(12, 8))
    qapp.processEvents()

    assert seen
    assert seen[0][0] is True
    assert seen[-1] == (False, None)
