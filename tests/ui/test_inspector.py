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


# ---- Task 2.4: TimeContextual ----

def test_time_contextual_plot_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import TimeContextual
    tc = TimeContextual()
    with qtbot.waitSignal(tc.plot_time_requested, timeout=200):
        tc.btn_plot.click()


# ---- Task 2.5: FFTContextual ----

def test_fft_contextual_defaults(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    p = fc.get_params()
    assert p['window'] in ('hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop')
    assert 'nfft' in p
    assert 0 <= p['overlap'] <= 0.9
    assert isinstance(p['autoscale'], bool)


def test_fft_contextual_fft_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    with qtbot.waitSignal(fc.fft_requested, timeout=200):
        fc.btn_fft.click()


# ---- Task 2.6: OrderContextual ----

def test_order_contextual_params(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    p = oc.get_params()
    for k in ('max_order', 'order_res', 'time_res', 'rpm_res', 'nfft'):
        assert k in p
    assert oc.target_order() > 0


def test_order_contextual_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    with qtbot.waitSignal(oc.order_time_requested, timeout=200):
        oc.btn_ot.click()
    with qtbot.waitSignal(oc.order_rpm_requested, timeout=200):
        oc.btn_or.click()
    with qtbot.waitSignal(oc.order_track_requested, timeout=200):
        oc.btn_ok.click()


def test_inspector_no_longer_exposes_mode_signals(qapp):
    """Spec §9: after 2026-04-24 cleanup, Inspector no longer relays
    plot_mode_changed / cursor_mode_changed — those are on ChartStack now."""
    insp = Inspector()
    assert not hasattr(insp, 'plot_mode_changed')
    assert not hasattr(insp, 'cursor_mode_changed')
