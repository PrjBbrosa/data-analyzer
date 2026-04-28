from mf4_analyzer.ui.chart_stack import ChartStack


def test_chart_stack_has_three_canvases(qapp):
    cs = ChartStack()
    # Four canvases after Task 3 (time / fft / fft_time / order); test name kept for git history.
    assert cs.count() == 4


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
    # Five segmented buttons on the card toolbar (post-i18n labels):
    # 分屏 / 叠加 / 游标关 / 单游标 / 双游标
    texts = {b.text() for b in card.findChildren(type(card.btn_subplot))}
    assert {'分屏', '叠加', '游标关', '单游标', '双游标'} <= texts


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


def test_fft_card_also_strips_subplots_button(qapp, qtbot):
    """Subplots action is stripped from every card since tight_layout is the default."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    fft_card = cs.stack.widget(1)
    for act in fft_card.toolbar.actions():
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_set_plot_mode_noop_does_not_emit(qapp, qtbot):
    """set_plot_mode with the current mode should not re-emit."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default is 'subplot'; calling with 'subplot' again should not emit.
    assert cs.plot_mode() == 'subplot'
    # qtbot.waitSignal with timeout=50 and check=[] — use a different approach:
    received = []
    cs.plot_mode_changed.connect(lambda m: received.append(m))
    cs.set_plot_mode('subplot')
    assert received == []
    # sanity: a real change does still emit
    cs.set_plot_mode('overlay')
    assert received == ['overlay']


def test_set_cursor_mode_noop_does_not_emit(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.cursor_mode() == 'off'
    received = []
    cs.cursor_mode_changed.connect(lambda m: received.append(m))
    cs.set_cursor_mode('off')
    assert received == []
    cs.set_cursor_mode('dual')
    assert received == ['dual']


def test_chart_stack_exposes_fft_time_card(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.set_mode('fft_time')

    assert stack.current_mode() == 'fft_time'
    assert stack.canvas_fft_time is not None
    assert stack.stack.currentWidget() is stack._fft_time_card


# ---- Task 5: SpectrogramCanvas rendering, cursor, hover ----

def test_spectrogram_canvas_plots_main_and_slice(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2, 0.3]),
        frequencies=np.array([10.0, 20.0, 30.0]),
        amplitude=np.array([[1, 2, 3], [2, 4, 6], [1, 3, 5]], dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8, window='hanning', overlap=0.5),
        channel_name='demo',
        unit='V',
    )

    canvas.plot_result(result, amplitude_mode='amplitude', cmap='viridis')

    assert len(canvas.fig.axes) >= 2
    assert canvas.selected_index() == 0


def test_spectrogram_canvas_applies_dynamic_and_freq_range(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    # Magnitudes spanning ~120 dB.
    amp = np.array([[1e-6, 1e-3], [1e-3, 1.0], [1.0, 0.1]], dtype=np.float32)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 100.0, 200.0]),
        amplitude=amp,
        params=SpectrogramParams(fs=400.0, nfft=8, db_reference=1.0),
        channel_name='demo',
    )

    canvas.plot_result(
        result,
        amplitude_mode='amplitude_db',
        cmap='turbo',
        z_auto=False,
        z_floor=-60.0,
        z_ceiling=0.0,
        freq_range=(0.0, 150.0),
    )

    im = canvas._ax_spec.images[0]
    vmin, vmax = im.get_clim()
    assert (vmax - vmin) == 60.0          # z_floor=-60 / z_ceiling=0 applied
    assert canvas._ax_spec.get_ylim()[1] <= 150.0  # freq_range applied


def test_spectrogram_canvas_emits_cursor_info_on_hover(qtbot):
    import numpy as np
    from matplotlib.backend_bases import MouseEvent
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.0, 0.1, 0.2]),
        frequencies=np.array([0.0, 50.0, 100.0]),
        amplitude=np.ones((3, 3), dtype=np.float32),
        params=SpectrogramParams(fs=200.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')
    canvas.draw()

    seen = []
    canvas.cursor_info.connect(seen.append)

    # Synthesize hover at data coords (t=0.1, f=50).
    ax = canvas._ax_spec
    x_pix, y_pix = ax.transData.transform((0.1, 50.0))
    evt = MouseEvent('motion_notify_event', canvas, x_pix, y_pix)
    evt.inaxes = ax
    evt.xdata = 0.1
    evt.ydata = 50.0
    canvas._on_motion(evt)

    assert seen, "cursor_info should fire on hover"
    assert '0.1' in seen[-1] or 't=0.1' in seen[-1]


# ---- Task 9: SpectrogramCanvas export pixmaps ----

def test_spectrogram_canvas_export_pixmaps(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 20.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')

    assert not canvas.grab_full_view().isNull()
    assert not canvas.grab_main_chart().isNull()


# ---- Task 2.7: Chinese segmented buttons + idle hint ----

def test_time_card_segmented_buttons_chinese(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    card = cs._time_card
    assert card.btn_subplot.text() == '分屏'
    assert card.btn_overlay.text() == '叠加'
    assert card._cursor_buttons['off'].text() == '游标关'
    assert card._cursor_buttons['single'].text() == '单游标'
    assert card._cursor_buttons['dual'].text() == '双游标'
    assert card._lock_buttons['none'].text() == '不锁'
    assert card._lock_buttons['x'].text() == '锁X'
    assert card._lock_buttons['y'].text() == '锁Y'


def test_tool_hints_idle_mentions_dblclick():
    from mf4_analyzer.ui.chart_stack import _TOOL_HINTS
    # _TOOL_HINTS values are (title, detail) tuples since MDI icon refactor;
    # the '双击坐标轴' phrase lives in the detail string (index 1).
    assert '双击坐标轴' in _TOOL_HINTS[''][1]


# ---- Bottom hint bar (Persistent + Context layers) ----

def test_bottom_hint_bar_persistent_always_present(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        # Bar exists, is visible, and the persistent label spells the three
        # always-on shortcuts.
        assert card._hint_bar is not None
        assert card._hint_persistent is not None
        text = card._hint_persistent.text()
        assert "Ctrl" in text
        assert "Shift" in text
        assert "双击坐标轴" in text


def test_bottom_hint_bar_context_pan_default(qapp):
    """Default after construction is pan mode → context label = pan hint."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    assert "平移模式" in card._hint_context.text()


def test_bottom_hint_bar_context_switches_with_cursor_mode(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    # cursor=single → 单游标 hint
    card.set_cursor_mode('single')
    assert "单游标" in card._hint_context.text()
    # cursor=dual → 双游标 hint
    card.set_cursor_mode('dual')
    assert "双游标" in card._hint_context.text()
    # cursor=off → fall back to current toolbar mode hint (pan by default)
    card.set_cursor_mode('off')
    assert "平移模式" in card._hint_context.text()


def test_bottom_hint_bar_spectrogram_hint(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    fft_time = cs._fft_time_card
    # Spectrogram card defaults to pan mode (toolbar.pan() in base init), so
    # the toolbar-mode hint wins. Force toolbar mode off to surface the
    # spectrogram-specific hint and confirm the override path.
    fft_time.toolbar.mode = ''  # type: ignore[attr-defined]
    fft_time._refresh_bottom_hint()
    assert "谱图" in fft_time._hint_context.text()


def test_bottom_hint_bar_idle_for_base_card_with_no_mode(qapp):
    """Plain _ChartCard (e.g. fft / order) with no toolbar mode shows empty."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._fft_card
    card.toolbar.mode = ''  # type: ignore[attr-defined]
    card._refresh_bottom_hint()
    assert card._hint_context.text() == ''


def test_bottom_hint_bar_constants_exposed():
    """Module-level dict MUST expose the documented context keys verbatim."""
    from mf4_analyzer.ui.chart_stack import (
        _BOTTOM_HINT_CONTEXT, _BOTTOM_HINT_PERSISTENT,
    )
    assert "Ctrl" in _BOTTOM_HINT_PERSISTENT
    assert "Shift" in _BOTTOM_HINT_PERSISTENT
    assert "双击坐标轴" in _BOTTOM_HINT_PERSISTENT
    for key in ('pan', 'zoom', 'cursor_single', 'cursor_dual',
                'spectrogram', 'idle'):
        assert key in _BOTTOM_HINT_CONTEXT
    assert _BOTTOM_HINT_CONTEXT['idle'] == ''


def test_bottom_hint_bar_does_not_break_existing_top_hint(qapp):
    """Sanity: existing in-toolbar _hint_label remains untouched."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    # Default mode is pan → top hint label paints '移动曲线' title.
    assert "移动曲线" in card._hint_label.text()
