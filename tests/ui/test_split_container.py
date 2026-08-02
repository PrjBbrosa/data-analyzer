from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
import numpy as np


def _shown_chart_stack(qtbot):
    # 1400 matches the width MainWindow tests use. At 1000 the stack is
    # narrower than a two-pane split's minimum, so entering split grows this
    # top-level window mid-layout and Qt hands the extra pixels out by size
    # hint — the panes land uneven for a reason that cannot happen inside the
    # real window, where the stack never resizes itself.
    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.resize(1400, 620)
    stack.show()
    qtbot.waitExposed(stack)
    return stack


def test_split_shows_two_panes(qtbot):
    cs = _shown_chart_stack(qtbot)

    assert cs.split_active() is False
    assert cs.secondary_canvas() is None

    cs.enter_split()

    assert cs.split_active() is True
    assert cs.secondary_canvas() is not None
    assert cs.stack.widget(0) is cs._time_page
    assert cs._time_toolbar.parentWidget() is cs._time_page
    assert cs._time_split.count() == 2
    left, right = cs._time_split.sizes()
    assert left > 0
    assert right > 0
    assert not cs._secondary_card.toolbar.isVisibleTo(cs._time_split)

    cs.exit_split()

    assert cs.split_active() is False


def test_attach_view_tabbar_stays_in_shared_bottom_dock_outside_splitter(qtbot):
    cs = _shown_chart_stack(qtbot)

    bar = cs.attach_view_tabbar(ViewManager())
    cs.enter_split()

    assert cs.stack.widget(0) is cs._time_page
    assert cs._time_split.widget(0) is cs._time_card
    assert cs._time_split.widget(1) is cs._secondary_card
    assert cs._time_card.view_tabbar is None
    assert cs._secondary_card.view_tabbar is None
    assert bar.parentWidget() is cs._time_bottom_dock
    assert cs._time_bottom_dock.isVisibleTo(cs)
    lay = cs._time_bottom_dock.layout()
    assert lay.indexOf(bar) < lay.indexOf(cs._time_hint_bar)


def test_mode_switching_uses_wrapped_time_page(qtbot):
    cs = _shown_chart_stack(qtbot)

    assert cs.current_mode() == "time"
    assert cs.stack.currentWidget() is cs._time_page

    cs.set_mode("fft")
    assert cs.current_mode() == "fft"
    # V7: the FFT stacked widget is now the AnalysisSectionPage; the card is
    # pane 0 of that page.
    assert cs.stack.currentWidget() is cs.page_fft
    assert cs._fft_card is cs.page_fft._cards[0]

    cs.set_mode("time")
    assert cs.current_mode() == "time"
    assert cs.stack.currentWidget() is cs._time_page

    cs.set_plot_mode("overlay")
    assert cs.plot_mode() == "overlay"
    cs.set_cursor_mode("single")
    assert cs.cursor_mode() == "single"


def test_analysis_split_uses_one_shared_toolbar_and_equal_widths(qtbot, qapp):
    cs = _shown_chart_stack(qtbot)
    cs.set_mode("fft")
    page = cs.page_fft

    page.enter_split()
    qapp.processEvents()

    assert page.pane_count() == 2
    assert page._toolbar.parentWidget() is page
    assert page._cards[0].toolbar is page._toolbar
    assert page._toolbar.isVisibleTo(page)
    assert not page._cards[1].toolbar.isVisibleTo(page)
    left, right = page._split.sizes()
    assert abs(left - right) <= 2


def test_secondary_time_controls_disabled_until_focus_routing(qtbot):
    cs = _shown_chart_stack(qtbot)

    cs.enter_split()
    secondary = cs._secondary_card

    assert not secondary.btn_subplot.isEnabled()
    assert not secondary.btn_overlay.isEnabled()
    assert all(not button.isEnabled() for button in secondary._cursor_buttons.values())


def test_full_reset_all_clears_secondary_canvas(qtbot):
    cs = _shown_chart_stack(qtbot)
    cs.enter_split()
    canvas = cs.secondary_canvas()
    x = np.linspace(0.0, 1.0, 20)
    canvas.plot_channels(
        [("secondary", True, x, np.sin(x), "#2d7ff9", "", "f1")],
        mode="subplot",
    )
    assert canvas.axes_list
    assert canvas._channel_lines

    cs.full_reset_all()

    assert canvas.axes_list == []
    assert canvas._channel_lines == {}
