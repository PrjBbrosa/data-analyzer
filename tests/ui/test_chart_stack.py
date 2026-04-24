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


def test_cursor_pill_updates_on_time_signal(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.canvas_time.cursor_info.emit("t=1.0s | Speed=100")
    assert "t=1.0s" in cs.cursor_pill_text()


def test_cursor_pill_hidden_in_fft_mode(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('fft')
    assert not cs.cursor_pill_visible()


def test_stats_strip_update(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.stats_strip.update_stats({
        'ch1': {'min': 0, 'max': 10, 'mean': 5, 'rms': 6, 'std': 2, 'p2p': 10, 'unit': 'V'}
    })
    assert 'ch1' in cs.stats_strip._lbl_summary.text()


def test_stats_strip_toggle(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    assert not cs.stats_strip._panel.isVisible()
    cs.stats_strip.toggle()
    qapp.processEvents()
    assert cs.stats_strip._panel.isVisible()


# ---- TimeChartCard (2026-04-24 UI cleanup) ----

def test_chart_stack_exposes_plot_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.plot_mode() == 'subplot'
    with qtbot.waitSignal(cs.plot_mode_changed, timeout=200) as bl:
        cs.set_plot_mode('overlay')
    assert bl.args == ['overlay']
    assert cs.plot_mode() == 'overlay'


def test_chart_stack_exposes_cursor_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default must be 'off' per spec §8
    assert cs.cursor_mode() == 'off'
    with qtbot.waitSignal(cs.cursor_mode_changed, timeout=200) as bl:
        cs.set_cursor_mode('single')
    assert bl.args == ['single']
    assert cs.cursor_mode() == 'single'


def test_time_chart_card_has_segmented_controls(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, TimeChartCard
    cs = ChartStack()
    qtbot.addWidget(cs)
    # First card in the stack is the time-domain card.
    card = cs.stack.widget(0)
    assert isinstance(card, TimeChartCard)
    # Four buttons on the card toolbar: Subplot, Overlay, Off, Single, Dual
    texts = {b.text() for b in card.findChildren(type(card.btn_subplot))}
    assert {'Subplot', 'Overlay', 'Off', 'Single', 'Dual'} <= texts


def test_time_chart_card_removes_subplots_config_button(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs.stack.widget(0)
    # No QAction on the native nav toolbar should map to 'configure_subplots'.
    native_tb = card.toolbar
    for act in native_tb.actions():
        # The action object name / icon text varies; check both.
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_fft_card_still_has_subplots_button(qapp, qtbot):
    """Only time card strips the button — FFT / Order keep the default toolbar."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # Per spec §3.2 we strip Subplots from ALL cards (tight_layout is the
    # default everywhere). So this test also asserts absence on FFT card.
    fft_card = cs.stack.widget(1)
    for act in fft_card.toolbar.actions():
        assert act.text().lower() not in ('subplots', 'configure subplots')
