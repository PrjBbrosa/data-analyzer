from mf4_analyzer.ui.chart_stack import ChartStack


def test_chart_stack_has_three_canvases(qapp):
    cs = ChartStack()
    assert cs.count() == 3


def test_chart_stack_set_mode(qapp):
    cs = ChartStack()
    cs.set_mode('fft')
    assert cs.current_mode() == 'fft'
    cs.set_mode('order')
    assert cs.current_mode() == 'order'
    cs.set_mode('time')
    assert cs.current_mode() == 'time'
