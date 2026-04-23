"""Tests for the Inspector skeleton (Phase 1) and section widgets (Phase 2)."""
from mf4_analyzer.ui.inspector import Inspector


def test_inspector_constructs(qapp):
    insp = Inspector()
    assert insp is not None


def test_inspector_switch_mode_changes_contextual(qapp):
    insp = Inspector()
    insp.set_mode('time')
    assert insp.contextual_widget_name() == 'time'
    insp.set_mode('fft')
    assert insp.contextual_widget_name() == 'fft'
    insp.set_mode('order')
    assert insp.contextual_widget_name() == 'order'


# ---- Task 2.3: PersistentTop ----

def test_persistent_top_xaxis_mode_toggle(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    assert pt.xaxis_mode() == 'time'
    pt.set_xaxis_mode('channel')
    assert pt.xaxis_mode() == 'channel'
    assert pt._combo_xaxis_ch.isEnabled()


def test_persistent_top_apply_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    with qtbot.waitSignal(pt.xaxis_apply_requested, timeout=200):
        pt.btn_apply_xaxis.click()
