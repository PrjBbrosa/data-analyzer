"""Global QMenu compact density (2026-08-10 Option A)."""
from __future__ import annotations

import re
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu

from mf4_analyzer.ui_kit.menus import add_rounded_submenu, apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.popup_shell import POPUP_SHELL_FLAGS

QSS_PATH = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"


def _global_qmenu_block(qss: str) -> str:
    """Return the global ``QMenu {…}`` body (not ``#pgContextMenu``)."""
    match = re.search(
        r"^QMenu\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.M | re.S,
    )
    assert match is not None, "global QMenu block missing"
    return match.group("body")


def _global_qmenu_item_block(qss: str) -> str:
    match = re.search(
        r"^QMenu::item\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.M | re.S,
    )
    assert match is not None, "global QMenu::item block missing"
    return match.group("body")


def test_global_qmenu_uses_compact_option_a_tokens():
    qss = QSS_PATH.read_text(encoding="utf-8")
    menu = _global_qmenu_block(qss)
    item = _global_qmenu_item_block(qss)

    assert "padding: 4px;" in menu
    assert "border-radius: 10px;" in menu
    assert "min-height: 20px;" in item
    assert "padding: 4px 12px 4px 10px;" in item
    assert "border-radius: 6px;" in item
    assert "padding: 7px 28px 7px 12px;" not in item
    assert re.search(
        r"^QMenu::separator\s*\{[^}]*margin: 4px 8px;", qss, re.M | re.S
    )

    gutter = re.search(
        r'^QMenu\[gutter="check"\]::item\s*\{(?P<body>[^}]*)\}',
        qss,
        flags=re.M | re.S,
    )
    assert gutter is not None
    assert "padding-right: 22px;" in gutter.group("body")


def test_pg_context_menu_keeps_independent_larger_metrics():
    qss = QSS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^QMenu#pgContextMenu::item\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.M | re.S,
    )
    assert match is not None
    body = match.group("body")
    assert "min-height: 30px;" in body
    assert "padding-right: 30px;" in body


def test_rounded_menu_chrome_opt_in_check_gutter(qtbot):
    plain = apply_rounded_menu_chrome(QMenu())
    qtbot.addWidget(plain)
    assert plain.property("gutter") in (None, "")

    checked = apply_rounded_menu_chrome(QMenu(), gutter="check")
    qtbot.addWidget(checked)
    assert checked.property("gutter") == "check"


def _assert_rounded_menu_shell(menu: QMenu) -> None:
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
    assert (flags & POPUP_SHELL_FLAGS) == POPUP_SHELL_FLAGS


def test_rounded_menu_chrome_covers_submenu_added_later(qtbot):
    """``addMenu`` after chrome used to leave a square native backing."""
    menu = apply_rounded_menu_chrome(QMenu())
    qtbot.addWidget(menu)
    submenu = menu.addMenu("自由网格尺寸")
    assert not submenu.testAttribute(Qt.WA_TranslucentBackground)

    menu.aboutToShow.emit()

    _assert_rounded_menu_shell(submenu)


def test_add_rounded_submenu_applies_shell_immediately(qtbot):
    menu = apply_rounded_menu_chrome(QMenu())
    qtbot.addWidget(menu)
    submenu = add_rounded_submenu(menu, "自由网格尺寸")

    _assert_rounded_menu_shell(submenu)
    assert menu.property("gutter") == "check"
