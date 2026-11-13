"""UltraView card action bar: remove affordance, alignment, and narrow LOD."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QObject, QPoint, QSize, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox, QStackedWidget, QToolButton, QWidget

import mf4_analyzer.ui.chart_stack.ultraview.widgets as ultraview_widgets
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import handle_visual_rects
from mf4_analyzer.ui.chart_stack.ultraview.viewport import LOD_FULL, LOD_TITLE_ONLY
from mf4_analyzer.ui.chart_stack.ultraview.viewport_router import ViewportGestureRouter
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
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DPR_UNAUDITED_CODE = 78


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


def _card_dpr_child_env(target_dpr: float) -> dict[str, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(_REPO_ROOT)
    env["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    env["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    env["QT_SCALE_FACTOR"] = str(target_dpr)
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")
    if abs(target_dpr - 1.0) < 0.01:
        env.pop("QT_SCREEN_SCALE_FACTORS", None)
    return env


def _run_card_dpr_child(target_dpr: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--dpr-child", str(target_dpr)],
        cwd=str(_REPO_ROOT),
        env=_card_dpr_child_env(target_dpr),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _actual_dpr_readings(card, app) -> dict[str, float | None]:
    handle = card.windowHandle()
    screen = app.primaryScreen()
    return {
        "widget": float(card.devicePixelRatioF()),
        "window": None if handle is None else float(handle.devicePixelRatio()),
        "screen": None if screen is None else float(screen.devicePixelRatio()),
    }


def _chosen_actual_dpr(readings: dict[str, float | None]) -> float:
    for key in ("window", "widget", "screen"):
        value = readings[key]
        if value is not None:
            return float(value)
    raise AssertionError(f"no DPR reading available; {readings}")


def _probe_card_dpr(target_dpr: float) -> None:
    """Fresh-process widget path: configure DPR before QApplication exists."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    if QApplication.instance() is not None:
        raise SystemExit("fresh QApplication required before DPR configuration")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication([])
    _prepare_app(app)
    card = UltraViewCard(_model())
    card.resize(_SIZE_100)
    card.show()
    app.processEvents()
    readings = _actual_dpr_readings(card, app)
    report = {"target_dpr": target_dpr, "readings": readings}
    actual = _chosen_actual_dpr(readings)
    report["actual_dpr"] = actual
    if abs(actual - target_dpr) > 0.05:
        report["status"] = "UNAUDITED"
        print(json.dumps(report, sort_keys=True))
        raise SystemExit(_DPR_UNAUDITED_CODE)
    _assert_action_centers(card, _FULL_ACTIONS)
    pixmap = card.grab()
    pix_dpr = float(pixmap.devicePixelRatioF() or 1.0)
    logical = card.size()
    report.update(
        {
            "status": "ok",
            "pixmap_dpr": pix_dpr,
            "logical": [logical.width(), logical.height()],
            "physical": [pixmap.width(), pixmap.height()],
        }
    )
    assert abs(pix_dpr - actual) < 0.05, report
    expected_w = int(round(logical.width() * actual))
    expected_h = int(round(logical.height() * actual))
    assert abs(pixmap.width() - expected_w) <= 1, report
    assert abs(pixmap.height() - expected_h) <= 1, report
    print(json.dumps(report, sort_keys=True))


@pytest.mark.parametrize("target_dpr", (1.0, 2.0))
def test_action_button_centers_in_fresh_app_dpr(target_dpr):
    result = _run_card_dpr_child(target_dpr)
    if abs(target_dpr - 2.0) < 0.01 and result.returncode == _DPR_UNAUDITED_CODE:
        pytest.skip(
            "UNAUDITED: platform did not apply DPR 2.0 to a fresh QApplication; "
            f"stdout={result.stdout.strip()!r}"
        )
    assert result.returncode == 0, (
        f"DPR {target_dpr} widget child failed rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "ok"
    assert abs(float(payload["actual_dpr"]) - target_dpr) <= 0.05


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
    assert board.width() == board._workspace_size(board.metrics()).width()
    assert board.workspace_extent() == GridBounds(-4, -4, 24, 56)
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


def test_right_press_during_left_gesture_cancels_without_changing_the_model(qtbot):
    from tests.ui.test_ultraview_gesture_preview import (
        MOVER_BLUE,
        _placement_signature,
        _prepare_colored_board,
    )

    board = _prepare_colored_board(qtbot, ("right-cancel", MOVER_BLUE))
    card = board.card_for("time", "right-cancel")
    before = _placement_signature(board)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, QPoint(24, 24))
    assert board.gesture().is_armed()
    QTest.mousePress(card, Qt.RightButton, Qt.NoModifier, QPoint(30, 30))
    assert not board.gesture().is_armed()
    assert board.gesture().session() is None
    assert _placement_signature(board) == before
    QTest.mouseRelease(card, Qt.RightButton, Qt.NoModifier, QPoint(30, 30))
    assert _placement_signature(board) == before


class _IdleViewport:
    def is_panning(self) -> bool:
        return False

    def pan_button(self) -> int:
        return int(Qt.LeftButton)


def _refuse_pan(*_args):
    return False


def _ignore_pan(*_args) -> None:
    return None


def _text_field_idle() -> bool:
    return False


class _AcceptButtonlessMove(QObject):
    """Stop the move before a card child can propagate it to the card frame."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.MouseMove and not event.buttons():
            self.count += 1
            event.accept()
            return True
        return False


def _selected_board(qtbot, qapp):
    _prepare_app(qapp)
    board = FreeGridBoard()
    qtbot.addWidget(board)
    ref = UltraViewRef("time", "view-1")
    board.set_free_grid(
        (FreeGridPlacement(ref, GridRect(0, 0, 4, 3)),),
        {ref: _model()},
    )
    board.show()
    qtbot.waitExposed(board)
    qapp.processEvents()
    board.select_only("time", "view-1")
    qapp.processEvents()
    card = board.card_for("time", "view-1")
    assert card is not None and card.model().selected
    return board, card, ref


def _send_buttonless(widget: QWidget, local: QPoint) -> None:
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.MouseMove,
            local,
            widget.mapToGlobal(local),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )


def test_buttonless_move_over_card_children_sets_resize_cursor_without_the_frame(
    qtbot, qapp
):
    board, card, _ref = _selected_board(qtbot, qapp)
    image = card.findChild(QWidget, "ultraViewCardImage")
    header = card.findChild(QWidget, "ultraViewCardHeader")
    footer = card.findChild(QWidget, "ultraViewCardFooter")
    assert image is not None and header is not None and footer is not None
    assert image.hasMouseTracking()
    assert header.hasMouseTracking()
    assert footer.hasMouseTracking()
    swallow = _AcceptButtonlessMove()
    image.installEventFilter(swallow)
    header.installEventFilter(swallow)
    footer.installEventFilter(swallow)
    router = ViewportGestureRouter(
        canvas_host=board,
        viewport=_IdleViewport(),
        begin_pan=_refuse_pan,
        update_pan=_ignore_pan,
        end_pan=_refuse_pan,
        zoom_wheel=_refuse_pan,
        pinch=_refuse_pan,
        note_space=_ignore_pan,
        text_field_has_focus=_text_field_idle,
        parent=board,
    )
    router.install()
    try:
        before = board.cursor().shape()
        assert before == Qt.ArrowCursor
        east = QPoint(card.width() - 4, card.height() // 2)
        assert image.geometry().contains(east)
        _send_buttonless(image, image.mapFrom(card, east))
        assert board.cursor().shape() == Qt.SizeHorCursor
        assert image.cursor().shape() == Qt.SizeHorCursor
        assert not card.testAttribute(Qt.WA_SetCursor)
        center = QPoint(card.width() // 2, card.height() // 2)
        _send_buttonless(image, image.mapFrom(card, center))
        assert board.cursor().shape() == before
        assert image.cursor().shape() == before
        north = QPoint(card.width() // 2, 3)
        assert header.geometry().contains(north)
        _send_buttonless(header, header.mapFrom(card, north))
        assert board.cursor().shape() == Qt.SizeVerCursor
        assert header.cursor().shape() == Qt.SizeVerCursor
        _send_buttonless(image, image.mapFrom(card, center))
        assert board.cursor().shape() == before
        south = QPoint(card.width() // 2, card.height() - 4)
        assert footer.geometry().contains(south)
        _send_buttonless(footer, footer.mapFrom(card, south))
        assert board.cursor().shape() == Qt.SizeVerCursor
        assert footer.cursor().shape() == Qt.SizeVerCursor
        _send_buttonless(image, QPoint(-10000, -10000))
        assert board.cursor().shape() == before
        assert swallow.count >= 5
    finally:
        router.uninstall()


def test_bubbled_move_keeps_the_resize_cursor(qtbot, qapp):
    """An unaccepted move reaches the canvas stack. That must not drop the cursor."""
    stack = QStackedWidget()
    stack.setObjectName("ultraViewBoardCanvasStack")
    qtbot.addWidget(stack)
    board, card, _ref = _selected_board(qtbot, qapp)
    stack.addWidget(board)
    stack.resize(900, 700)
    stack.show()
    qapp.processEvents()
    router = ViewportGestureRouter(
        canvas_host=stack,
        viewport=_IdleViewport(),
        begin_pan=_refuse_pan,
        update_pan=_ignore_pan,
        end_pan=_refuse_pan,
        zoom_wheel=_refuse_pan,
        pinch=_refuse_pan,
        note_space=_ignore_pan,
        text_field_has_focus=_text_field_idle,
        parent=stack,
    )
    router.install()
    try:
        east = QPoint(card.width() - 4, card.height() // 2)
        _send_buttonless(card, east)
        qapp.processEvents()
        assert board.cursor().shape() == Qt.SizeHorCursor
        assert card.cursor().shape() == Qt.SizeHorCursor
    finally:
        router.uninstall()


def test_press_six_px_outside_selected_card_starts_resize_not_marquee(qtbot, qapp):
    board, card, ref = _selected_board(qtbot, qapp)
    geom = card.geometry()
    outside = QPoint(geom.right() + 6, geom.center().y())
    assert not geom.contains(outside)
    QTest.mousePress(board, Qt.LeftButton, Qt.NoModifier, outside)
    session = board.gesture().session()
    assert session is not None and session.handle == "e"
    assert board.gesture().marquee() is None
    assert ref in board.gesture().selection()
    assert board.cursor().shape() == Qt.SizeHorCursor
    QTest.mouseRelease(board, Qt.LeftButton, Qt.NoModifier, outside)
    assert ref in board.gesture().selection()


def test_quarter_zoom_corner_of_the_visible_handle_still_starts_resize(qtbot, qapp):
    board, card, ref = _selected_board(qtbot, qapp)
    board.set_zoom(0.25)
    qapp.processEvents()
    card = board.card_for("time", "view-1")
    assert card is not None
    geom = card.geometry()
    assert min(geom.width(), geom.height()) < 48
    box = (geom.x(), geom.y(), geom.width(), geom.height())
    hx, hy, width, height = handle_visual_rects(box)["se"]
    corner = QPoint(hx + width - 1, hy + height - 1)
    assert not geom.contains(corner)
    QTest.mousePress(board, Qt.LeftButton, Qt.NoModifier, corner)
    session = board.gesture().session()
    assert session is not None and session.handle == "se"
    assert board.gesture().marquee() is None
    assert ref in board.gesture().selection()
    QTest.mouseRelease(board, Qt.LeftButton, Qt.NoModifier, corner)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dpr-child":
        _probe_card_dpr(float(sys.argv[2]))
    else:
        raise SystemExit("usage: test_ultraview_card_actions.py --dpr-child RATIO")
