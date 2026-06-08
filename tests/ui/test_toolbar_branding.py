# tests/ui/test_toolbar_branding.py
def test_cockpit_button_in_left_cluster(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb.btn_acquisition_cockpit.parentWidget() is tb._left_widget
