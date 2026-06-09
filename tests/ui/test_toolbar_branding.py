# tests/ui/test_toolbar_branding.py
def test_cockpit_button_in_left_cluster(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb.btn_acquisition_cockpit.parentWidget() is tb._left_widget


def test_toolbar_shows_logo(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb._logo_label.parentWidget() is tb._right_widget
    pm = tb._logo_label.pixmap()
    assert pm is not None and not pm.isNull()
