"""Toolbar, style popup and icon painting for the markup editor.

Construction only. The builders take the editor explicitly and wire each button
straight to the editor method it drives, so the connect targets stay visible in
one place instead of being buried in a 150-line __init__ tail.

Button creation order, group membership and connect targets are pinned by
``tests/ui/test_markup_toolbar_wiring.py`` -- the inventory is what the user
sees left-to-right, so keep additions in their intended position rather than
appending.
"""
from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

import qtawesome as qta

# Tool button labels, keyed by the tool id. The shortcut hint appended to each
# tooltip is the tool id's first letter (see _build_toolbar).
_TOOL_LABELS = {
    "select": "选择",
    "crop": "裁剪",
    "arrow": "箭头",
    "line": "直线",
    "rect": "矩形",
    "pen": "画笔",
    "text": "文字",
    "number": "序号",
}

_PALETTE = (
    ("红色", "#e53935"),
    ("橙色", "#f97316"),
    ("黄色", "#eab308"),
    ("绿色", "#059669"),
    ("蓝色", "#2563eb"),
    ("黑色", "#111827"),
)

_STROKE_WIDTHS = (2, 4, 6, 8)


# ---------------------------------------------------------------------------
# Stylesheets
# ---------------------------------------------------------------------------

def compact_tool_button_qss() -> str:
    return (
        "QToolButton {"
        "padding: 0px;"
        "border: 1px solid #c9d6ea; border-radius: 6px;"
        "background: #ffffff;"
        "}"
        "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
        # Selected tool: solid accent fill behind the white (contrast) glyph.
        "QToolButton:checked { background: #1769e0; border-color: #1769e0; }"
    )


def color_button_qss() -> str:
    # Same rounded chip as the tools; selected swatch gets a blue ring
    # (not a fill) so the colour stays readable.
    return (
        "QToolButton {"
        "padding: 0px;"
        "border: 1px solid #c9d6ea; border-radius: 6px;"
        "background: #ffffff;"
        "}"
        "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
        "QToolButton:checked { border: 2px solid #1769e0; background: #eaf2ff; }"
    )


# Icon painting deliberately stays on MarkupEditor. ``_icon_canvas`` reads
# ``icon_device_pixel_ratio`` from the editor module's globals, and
# tests/ui/test_color_swatch_hidpi.py monkeypatches it there to fake a 2x
# screen. Moving the painters here would silently strand that patch -- a
# re-export copies the binding, not the scope -- so the builders below call
# back through ``editor._color_icon`` / ``editor._width_icon`` instead.


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def build_toolbar(editor) -> QWidget:
    """Build the editor's toolbar row and register its buttons on ``editor``.

    Sets ``editor._style_button`` and ``editor._tool_buttons`` (and, via
    :func:`build_style_panel`, the colour/width registries) because the editor's
    sync helpers refresh those widgets when the active tool or style changes.
    """
    toolbar = QWidget(editor)
    toolbar.setObjectName("markupEditorToolbar")
    layout = QGridLayout(toolbar)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(0)

    def make_group(name: str):
        group = QWidget(toolbar)
        group.setObjectName(name)
        group_layout = QHBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(6)
        return group, group_layout

    left_group, left_layout = make_group("markupToolbarLeftGroup")
    center_group, center_layout = make_group("markupToolbarCenterGroup")
    right_group, right_layout = make_group("markupToolbarRightGroup")

    close_btn = QToolButton(left_group)
    close_btn.setObjectName("markupCloseButton")
    close_btn.setText("")
    close_btn.setIcon(qta.icon("ph.x", color="#dc2626"))
    close_btn.setIconSize(QSize(24, 24))
    close_btn.setToolTip("关闭 (Esc)")
    close_btn.setAutoRaise(True)
    close_btn.setFixedSize(QSize(44, 44))
    close_btn.setStyleSheet(
        "QToolButton#markupCloseButton {"
        "padding: 0px;"
        "border: 1px solid #f2b8b8; border-radius: 6px;"
        "background: #fffafa;"
        "}"
        "QToolButton#markupCloseButton:hover {"
        "background: #fee2e2; border-color: #dc2626;"
        "}"
    )
    close_btn.clicked.connect(editor.close)
    left_layout.addWidget(close_btn)

    editor._style_button = QToolButton(center_group)
    editor._style_button.setObjectName("markupStyleButton")
    editor._style_button.setToolTip("样式（颜色 / 线宽） · [ ] 调线宽")
    editor._style_button.setAutoRaise(True)
    editor._style_button.setIconSize(QSize(54, 24))
    editor._style_button.setFixedSize(QSize(76, 44))
    editor._style_button.setPopupMode(QToolButton.InstantPopup)
    editor._style_button.setStyleSheet(compact_tool_button_qss())
    style_menu = QMenu(editor._style_button)
    style_menu.setObjectName("markupStyleMenu")
    # Match the rounded-popup shell contract: QSS radius needs a transparent
    # menu window, and macOS needs native frame/shadow disabled so no square
    # backing remains behind the rounded style panel.
    style_menu.setWindowFlags(
        style_menu.windowFlags()
        | Qt.FramelessWindowHint
        | Qt.NoDropShadowWindowHint
    )
    style_menu.setAttribute(Qt.WA_TranslucentBackground, True)
    # Make the menu a transparent shell: the rounded surface lives on the
    # inner panel below. Otherwise the global QMenu rule paints a square
    # white rect (radius 12 > padding) that pokes past the rounded corners.
    style_menu.setStyleSheet(
        "QMenu#markupStyleMenu { background: transparent; border: none; padding: 0px; }"
    )
    style_action = QWidgetAction(style_menu)
    style_action.setDefaultWidget(build_style_panel(editor, style_menu))
    style_menu.addAction(style_action)
    editor._style_button.setMenu(style_menu)
    center_layout.addWidget(editor._style_button)
    editor._refresh_style_button_icon()

    tool_group = QButtonGroup(toolbar)
    tool_group.setExclusive(True)
    editor._tool_buttons = {}
    for tool in editor.TOOLS:
        active = tool == editor._tool
        button = QToolButton(center_group)
        button.setText("")
        button.setIcon(editor._tool_icon(tool, active))
        button.setIconSize(QSize(24, 24))
        button.setToolTip(f"{_TOOL_LABELS[tool]} ({tool[0].upper()})")
        button.setObjectName(f"markupTool_{tool}")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFixedSize(QSize(44, 44))
        button.setStyleSheet(compact_tool_button_qss())
        button.clicked.connect(
            lambda checked=False, name=tool: editor.set_tool(name)
        )
        if active:
            button.setChecked(True)
        tool_group.addButton(button)
        center_layout.addWidget(button)
        editor._tool_buttons[tool] = button

    undo_btn = QToolButton(center_group)
    undo_btn.setObjectName("markupUndoButton")
    undo_btn.setText("")
    undo_btn.setIcon(qta.icon("ph.arrow-counter-clockwise", color="#374151"))
    undo_btn.setIconSize(QSize(24, 24))
    undo_btn.setToolTip("撤销 (Ctrl+Z)")
    undo_btn.setAutoRaise(True)
    undo_btn.setFixedSize(QSize(44, 44))
    undo_btn.setStyleSheet(compact_tool_button_qss())
    undo_btn.clicked.connect(editor._undo_stack.undo)
    center_layout.addWidget(undo_btn)

    redo_btn = QToolButton(center_group)
    redo_btn.setObjectName("markupRedoButton")
    redo_btn.setText("")
    redo_btn.setIcon(qta.icon("ph.arrow-clockwise", color="#374151"))
    redo_btn.setIconSize(QSize(24, 24))
    redo_btn.setToolTip("重做 (Ctrl+Y)")
    redo_btn.setAutoRaise(True)
    redo_btn.setFixedSize(QSize(44, 44))
    redo_btn.setStyleSheet(compact_tool_button_qss())
    redo_btn.clicked.connect(editor._undo_stack.redo)
    center_layout.addWidget(redo_btn)

    save_btn = QPushButton("保存", right_group)
    save_btn.setObjectName("markupSaveButton")
    save_btn.clicked.connect(editor.save_result)
    right_layout.addWidget(save_btn)

    done_btn = QPushButton("完成复制", right_group)
    done_btn.setObjectName("markupDoneButton")
    done_btn.setProperty("variant", "primary")
    done_btn.setStyleSheet(
        "QPushButton#markupDoneButton {"
        "background: #1769e0; color: white; border: none;"
        "border-radius: 6px; padding: 6px 14px; font-weight: 600;"
        "}"
        "QPushButton#markupDoneButton:hover { background: #0f5ec8; }"
    )
    done_btn.clicked.connect(editor.finish_and_copy)
    right_layout.addWidget(done_btn)

    layout.addWidget(left_group, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
    layout.addWidget(center_group, 0, 1, Qt.AlignCenter)
    layout.addWidget(right_group, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 0)
    layout.setColumnStretch(2, 1)
    return toolbar


def build_style_panel(editor, menu) -> QWidget:
    """Build the colour/width panel shown inside the style button's popup.

    Registers ``editor._color_buttons`` / ``editor._width_buttons`` so
    ``_sync_style_panel`` can tick the active choices.
    """
    panel = QWidget()
    panel.setObjectName("markupStylePanel")
    # The panel is the only visible surface inside the transparent menu
    # shell, so it carries the rounded background/border itself.
    panel.setAttribute(Qt.WA_StyledBackground, True)
    panel.setStyleSheet(
        "QWidget#markupStylePanel {"
        "background: #ffffff;"
        "border: 1px solid #c9d6ea;"
        "border-radius: 10px;"
        "}"
    )
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(12, 10, 12, 12)
    outer.setSpacing(8)

    editor._color_buttons = {}
    color_row = QHBoxLayout()
    color_row.setSpacing(8)
    for name, color in _PALETTE:
        button = QToolButton(panel)
        button.setObjectName(f"markupColor_{color[1:]}")
        button.setIcon(editor._color_icon(QColor(color)))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(name)
        button.setAutoRaise(True)
        button.setCheckable(True)
        button.setFixedSize(QSize(30, 30))
        button.setStyleSheet(color_button_qss())
        button.clicked.connect(
            lambda checked=False, c=color, m=menu: (
                editor.set_color(QColor(c)),
                m.hide(),
            )
        )
        color_row.addWidget(button)
        editor._color_buttons[color.lower()] = button
    outer.addLayout(color_row)

    editor._width_buttons = {}
    width_row = QHBoxLayout()
    width_row.setSpacing(8)
    for width in _STROKE_WIDTHS:
        button = QToolButton(panel)
        button.setObjectName(f"markupWidth_{width}")
        button.setIcon(editor._width_icon(width))
        button.setIconSize(QSize(24, 18))
        button.setToolTip(f"{width}px")
        button.setAutoRaise(True)
        button.setCheckable(True)
        button.setFixedSize(QSize(34, 30))
        button.setStyleSheet(compact_tool_button_qss())
        button.clicked.connect(
            lambda checked=False, w=width, m=menu: (
                editor.set_stroke_width(w),
                m.hide(),
            )
        )
        width_row.addWidget(button)
        editor._width_buttons[width] = button
    outer.addLayout(width_row)
    editor._sync_style_panel()
    return panel
