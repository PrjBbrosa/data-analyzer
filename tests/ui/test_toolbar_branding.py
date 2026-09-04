# tests/ui/test_toolbar_branding.py
from PyQt5.QtCore import Qt


def test_no_cockpit_button(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    # The visible Cockpit button was removed; the entry now lives on the logo.
    assert not hasattr(tb, "btn_acquisition_cockpit")


def test_logo_triple_click_opens_cockpit(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    qtbot.addWidget(tb)
    fired = []
    tb.acquisition_cockpit_requested.connect(lambda: fired.append(True))

    qtbot.mouseClick(tb._logo_label, Qt.LeftButton)
    qtbot.mouseClick(tb._logo_label, Qt.LeftButton)
    assert fired == []                       # two clicks must not trigger
    qtbot.mouseClick(tb._logo_label, Qt.LeftButton)
    assert fired == [True]                    # the third consecutive click does


def test_toolbar_shows_logo(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb._logo_label.parentWidget() is tb._right_widget
    pm = tb._logo_label.pixmap()
    assert pm is not None and not pm.isNull()
    assert tb._logo_label.toolTip() == "博世华域转向系统有限公司\n仅限公司内使用"
