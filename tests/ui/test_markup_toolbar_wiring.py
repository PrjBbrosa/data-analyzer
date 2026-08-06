"""Wiring snapshot for the markup editor's toolbar and style panel.

Spec: docs/analyzer/specs/2026-08-04-chartstack-markup-slimming-design.md (D-D4).

``_build_toolbar`` is 156 lines of imperative widget construction whose output
nothing asserted: button identity, order, initial checked state and — most
fragile of all — which callback each ``clicked`` signal reaches. Extracting it
into ``toolbar.py`` means re-doing that wiring by hand, and a swapped connect
would not show up in any existing test.

So this file pins the inventory and every connection before the move, and must
stay green afterwards without edits. Captured on ``main`` @ ``ab19622f``.

Geometry is asserted only where it is a deliberate hit-target choice (the 44px
tool buttons); appearance beyond that is left to real-render checks.
"""
import pytest

from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QAbstractButton,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui.markup.editor import MarkupEditor


def _pixmap(width=200, height=160, color="#f7f7f7"):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(color))
    return pixmap


@pytest.fixture
def editor(qapp, qtbot):
    ed = MarkupEditor(_pixmap())
    qtbot.addWidget(ed)
    return ed


@pytest.fixture
def toolbar(editor):
    bar = editor.findChild(QWidget, "markupEditorToolbar")
    assert bar is not None
    return bar


@pytest.fixture
def style_panel(editor):
    menu = editor._style_button.menu()
    assert isinstance(menu, QMenu)
    assert menu.objectName() == "markupStyleMenu"
    assert len(menu.actions()) == 1
    panel = menu.actions()[0].defaultWidget()
    assert panel.objectName() == "markupStylePanel"
    return panel


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

# (objectName, text, checkable, initially checked)
EXPECTED_BUTTONS = [
    ("markupCloseButton", "", False, False),
    ("markupStyleButton", "", False, False),
    ("markupColor_e53935", "", True, True),
    ("markupColor_f97316", "", True, False),
    ("markupColor_eab308", "", True, False),
    ("markupColor_059669", "", True, False),
    ("markupColor_2563eb", "", True, False),
    ("markupColor_111827", "", True, False),
    ("markupWidth_2", "", True, False),
    ("markupWidth_4", "", True, True),
    ("markupWidth_6", "", True, False),
    ("markupWidth_8", "", True, False),
    ("markupTool_select", "", True, True),
    ("markupTool_crop", "", True, False),
    ("markupTool_arrow", "", True, False),
    ("markupTool_line", "", True, False),
    ("markupTool_rect", "", True, False),
    ("markupTool_pen", "", True, False),
    ("markupTool_text", "", True, False),
    ("markupTool_number", "", True, False),
    ("markupUndoButton", "", False, False),
    ("markupRedoButton", "", False, False),
    ("markupSaveButton", "保存", False, False),
    ("markupDoneButton", "完成复制", False, False),
]

EXPECTED_TOOLTIPS = {
    "markupCloseButton": "关闭 (Esc)",
    "markupStyleButton": "样式（颜色 / 线宽） · [ ] 调线宽",
    "markupUndoButton": "撤销 (Ctrl+Z)",
    "markupRedoButton": "重做 (Ctrl+Y)",
    "markupTool_select": "选择 (S)",
    "markupTool_crop": "裁剪 (C)",
    "markupTool_arrow": "箭头 (A)",
    "markupTool_line": "直线 (L)",
    "markupTool_rect": "矩形 (R)",
    "markupTool_pen": "画笔 (P)",
    "markupTool_text": "文字 (T)",
    "markupTool_number": "序号 (N)",
    "markupColor_e53935": "红色",
    "markupColor_f97316": "橙色",
    "markupColor_eab308": "黄色",
    "markupColor_059669": "绿色",
    "markupColor_2563eb": "蓝色",
    "markupColor_111827": "黑色",
    "markupWidth_2": "2px",
    "markupWidth_4": "4px",
    "markupWidth_6": "6px",
    "markupWidth_8": "8px",
}

EXPECTED_GROUPS = {
    "markupToolbarLeftGroup": ["markupCloseButton"],
    "markupToolbarCenterGroup": [
        "markupStyleButton",
        "markupTool_select", "markupTool_crop", "markupTool_arrow",
        "markupTool_line", "markupTool_rect", "markupTool_pen",
        "markupTool_text", "markupTool_number",
        "markupUndoButton", "markupRedoButton",
    ],
    "markupToolbarRightGroup": ["markupSaveButton", "markupDoneButton"],
}


def test_toolbar_button_inventory_and_initial_state(toolbar):
    found = [
        (b.objectName(), b.text(), b.isCheckable(), b.isChecked())
        for b in toolbar.findChildren(QAbstractButton)
    ]
    assert found == EXPECTED_BUTTONS


def test_every_button_keeps_its_tooltip(toolbar):
    found = {
        b.objectName(): b.toolTip()
        for b in toolbar.findChildren(QAbstractButton)
        if b.toolTip()
    }
    assert found == EXPECTED_TOOLTIPS


@pytest.mark.parametrize("group,children", sorted(EXPECTED_GROUPS.items()))
def test_toolbar_groups_keep_their_children_in_order(toolbar, group, children):
    """Left/centre/right grouping plus in-group order is the visible layout."""
    widget = toolbar.findChild(QWidget, group)
    assert widget is not None
    layout = widget.layout()
    assert [
        layout.itemAt(i).widget().objectName() for i in range(layout.count())
    ] == children


def test_tool_buttons_are_mutually_exclusive(toolbar, editor):
    """A QButtonGroup with exclusive=True is what stops two tools reading as
    active at once."""
    checked = [
        b for b in toolbar.findChildren(QToolButton)
        if b.objectName().startswith("markupTool_") and b.isChecked()
    ]
    assert [b.objectName() for b in checked] == ["markupTool_select"]

    editor._tool_buttons["rect"].click()

    checked = [
        b for b in toolbar.findChildren(QToolButton)
        if b.objectName().startswith("markupTool_") and b.isChecked()
    ]
    assert [b.objectName() for b in checked] == ["markupTool_rect"]


def test_tool_buttons_share_the_forty_four_pixel_hit_target(toolbar):
    for b in toolbar.findChildren(QToolButton):
        if b.objectName().startswith("markupTool_") or b.objectName() in {
            "markupCloseButton", "markupUndoButton", "markupRedoButton"
        }:
            assert (b.width(), b.height()) == (44, 44), b.objectName()


def test_editor_exposes_the_button_registries_the_sync_helpers_use(editor):
    assert sorted(editor._tool_buttons) == sorted(editor.TOOLS)
    assert sorted(editor._color_buttons) == [
        "#059669", "#111827", "#2563eb", "#e53935", "#eab308", "#f97316"]
    assert sorted(editor._width_buttons) == [2, 4, 6, 8]


def test_save_and_done_are_push_buttons_not_tool_buttons(toolbar):
    for name in ("markupSaveButton", "markupDoneButton"):
        assert isinstance(toolbar.findChild(QAbstractButton, name), QPushButton)


# ---------------------------------------------------------------------------
# Wiring -- what each clicked signal actually reaches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "select", "crop", "arrow", "line", "rect", "pen", "text", "number"])
def test_each_tool_button_selects_its_own_tool(editor, tool):
    """The lambda default-argument capture in the build loop is easy to get
    wrong -- every button would end up selecting the last tool."""
    editor.set_tool("select")
    editor._tool_buttons[tool].click()
    assert editor._tool == tool


@pytest.mark.parametrize("hexname", [
    "#e53935", "#f97316", "#eab308", "#059669", "#2563eb", "#111827"])
def test_each_colour_button_applies_its_own_colour(editor, hexname):
    editor.set_color(QColor("#000000"))
    editor._color_buttons[hexname].click()
    assert editor._color.name().lower() == hexname


@pytest.mark.parametrize("width", [2, 4, 6, 8])
def test_each_width_button_applies_its_own_width(editor, width):
    editor.set_stroke_width(1)
    editor._width_buttons[width].click()
    assert editor._stroke_width == width


def test_style_choices_close_the_popup(editor, style_panel):
    menu = editor._style_button.menu()
    editor._color_buttons["#2563eb"].click()
    assert not menu.isVisible()
    editor._width_buttons[8].click()
    assert not menu.isVisible()


def test_undo_and_redo_buttons_drive_the_undo_stack(editor, toolbar):
    from PyQt5.QtCore import QRectF
    editor.add_rect_item(QRectF(1, 2, 10, 10))
    assert editor._undo_stack.count() == 1

    toolbar.findChild(QAbstractButton, "markupUndoButton").click()
    assert editor._undo_stack.index() == 0

    toolbar.findChild(QAbstractButton, "markupRedoButton").click()
    assert editor._undo_stack.index() == 1


def test_close_button_closes_the_editor(editor, toolbar, qtbot):
    editor.show()
    toolbar.findChild(QAbstractButton, "markupCloseButton").click()
    assert not editor.isVisible()


def test_done_button_runs_the_copy_callback(qapp, qtbot):
    captured = []
    ed = MarkupEditor(_pixmap(), on_done=captured.append)
    qtbot.addWidget(ed)

    toolbar = ed.findChild(QWidget, "markupEditorToolbar")
    toolbar.findChild(QAbstractButton, "markupDoneButton").click()

    assert len(captured) == 1
    assert not captured[0].isNull()


def test_save_button_reaches_save_result(editor, toolbar, monkeypatch):
    calls = []
    monkeypatch.setattr(MarkupEditor, "_get_save_path",
                        lambda self: calls.append("asked") or "")

    toolbar.findChild(QAbstractButton, "markupSaveButton").click()

    assert calls == ["asked"]


# ---------------------------------------------------------------------------
# Style panel sync
# ---------------------------------------------------------------------------

def test_style_panel_reflects_the_active_colour_and_width(editor):
    editor.set_color(QColor("#059669"))
    editor.set_stroke_width(6)

    assert editor._color_buttons["#059669"].isChecked()
    assert not editor._color_buttons["#e53935"].isChecked()
    assert editor._width_buttons[6].isChecked()
    assert not editor._width_buttons[4].isChecked()


def test_style_button_shows_a_swatch_icon(editor):
    assert not editor._style_button.icon().isNull()
    assert (editor._style_button.iconSize().width(),
            editor._style_button.iconSize().height()) == (54, 24)


def test_style_menu_is_a_transparent_shell_around_the_rounded_panel(editor, style_panel):
    """The rounded surface lives on the panel; the menu must stay transparent
    or a square backing pokes out past the corners (see ui_kit popup shell)."""
    from PyQt5.QtCore import Qt

    menu = editor._style_button.menu()
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    assert menu.windowFlags() & Qt.FramelessWindowHint
    assert menu.windowFlags() & Qt.NoDropShadowWindowHint
    assert "background: transparent" in menu.styleSheet()
    assert style_panel.testAttribute(Qt.WA_StyledBackground)
    assert "border-radius: 10px" in style_panel.styleSheet()


def test_style_button_opens_the_menu_on_instant_popup(editor):
    assert editor._style_button.popupMode() == QToolButton.InstantPopup
