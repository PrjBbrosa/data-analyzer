import pytest


def test_default_stats_visible_iff_time_mode(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    assert cs.stats_strip.isVisible() == (cs.current_mode() == 'time')


def test_stats_hidden_in_fft_fft_time_order_modes(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    for mode in ('fft', 'fft_time', 'order'):
        cs.set_mode(mode)
        assert cs.stats_strip.isVisible() is False, f"{mode} should hide stats"


def test_stats_visible_after_returning_to_time(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('fft')
    assert cs.stats_strip.isVisible() is False
    cs.set_mode('time')
    assert cs.stats_strip.isVisible() is True


def test_no_channel_label_after_return(qtbot):
    """S2-T4: update_stats({}) on return to time shows '— 无通道 —'."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('fft')
    cs.set_mode('time')
    cs.stats_strip.update_stats({})
    assert cs.stats_strip._lbl_summary.text() == "— 无通道 —"
