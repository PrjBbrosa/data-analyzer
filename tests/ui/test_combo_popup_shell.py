"""Every QComboBox dropdown must get the rounded-popup translucent shell.

Regression guard for the "矩形框叠在圆角框后面" bug: the QSS rounds the
inner list, but without WA_TranslucentBackground + frameless / no-shadow
flags on the popup *window*, the square container + native rectangular
shadow leak behind the rounded corners. The shell is applied centrally by
an application event filter (install_combo_popup_shell), so this asserts
the central mechanism covers plain QComboBox AND SearchableComboBox
without any per-call-site opt-in.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox

from mf4_analyzer.ui_kit.combo_popup_shell import (
    install_combo_popup_shell,
    prepare_combo_popup,
    _apply_shell,
)
from mf4_analyzer.ui_kit.widgets.searchable_combo import SearchableComboBox


def _assert_shell(window):
    assert window.testAttribute(Qt.WA_TranslucentBackground), (
        "combo popup window needs WA_TranslucentBackground, else the "
        "square container fill shows behind the rounded list"
    )
    flags = window.windowFlags()
    assert bool(flags & Qt.NoDropShadowWindowHint), (
        "combo popup window needs NoDropShadowWindowHint to drop the "
        "native rectangular shadow"
    )
    assert bool(flags & Qt.FramelessWindowHint), (
        "combo popup window needs FramelessWindowHint so the platform "
        "frame does not draw a square edge"
    )
    ss = window.styleSheet().lower()
    assert "border" in ss and "none" in ss, (
        "combo popup container needs border:none, else QComboBoxPrivateContainer "
        "paints a square frame line outside the rounded list"
    )


def test_plain_combo_popup_gets_shell_on_show(qapp):
    install_combo_popup_shell(qapp)
    combo = QComboBox()
    combo.addItems(["d/dt", "∫dt", "× 系数"])
    combo.show()
    qapp.processEvents()
    try:
        _assert_shell(combo.view().window())
    finally:
        combo.deleteLater()


def test_searchable_combo_popup_gets_shell_on_show(qapp):
    install_combo_popup_shell(qapp)
    combo = SearchableComboBox()
    combo.addItems(["Speed", "Torque"])
    combo.show()
    qapp.processEvents()
    try:
        _assert_shell(combo.view().window())
    finally:
        combo.deleteLater()


def test_prepare_combo_popup_sets_first_frame_view_chrome(qapp):
    combo = QComboBox()
    combo.addItems(["first", "second"])

    prepare_combo_popup(combo)
    view = combo.view()
    viewport = view.viewport()

    _assert_shell(view.window())
    assert view.frameShape() == view.NoFrame
    assert "background-color: #ffffff" in viewport.styleSheet()
    assert viewport.palette().color(viewport.backgroundRole()).name().lower() == "#ffffff"
    combo.deleteLater()


def test_prepare_combo_popup_honors_fixed_popup_width_property(qapp):
    combo = QComboBox()
    combo.setProperty("popupWidth", 260)
    combo.addItems(["short", "a much longer option"])

    prepare_combo_popup(combo)

    assert combo.view().minimumWidth() == 260
    assert combo.view().maximumWidth() == 260
    combo.deleteLater()


def test_install_is_idempotent(qapp):
    first = install_combo_popup_shell(qapp)
    second = install_combo_popup_shell(qapp)
    assert first is second, "install_combo_popup_shell must not stack filters"


def test_apply_shell_is_idempotent(qapp):
    combo = QComboBox()
    window = combo.view().window()
    assert _apply_shell(window) is True
    assert _apply_shell(window) is False, "second apply should be a no-op"
    _assert_shell(window)
    combo.deleteLater()
