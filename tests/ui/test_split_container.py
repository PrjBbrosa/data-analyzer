from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
import numpy as np


def _shown_chart_stack(qtbot):
    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.resize(1000, 620)
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
    assert cs._time_split.count() == 2
    left, right = cs._time_split.sizes()
    assert left > 0
    assert right > 0

    cs.exit_split()

    assert cs.split_active() is False


def test_attach_view_tabbar_stays_on_primary_time_card_inside_splitter(qtbot):
    cs = _shown_chart_stack(qtbot)

    bar = cs.attach_view_tabbar(ViewManager())
    cs.enter_split()

    assert cs.stack.widget(0) is cs._time_split
    assert cs._time_split.widget(0) is cs._time_card
    assert cs._time_card.view_tabbar is bar
    assert bar.parentWidget() is cs._time_card
    assert cs._secondary_card.view_tabbar is None
    lay = cs._time_card.layout()
    assert lay.indexOf(bar) == lay.indexOf(cs._time_card._hint_bar) - 1


def test_mode_switching_uses_wrapped_time_page(qtbot):
    cs = _shown_chart_stack(qtbot)

    assert cs.current_mode() == "time"
    assert cs.stack.currentWidget() is cs._time_split

    cs.set_mode("fft")
    assert cs.current_mode() == "fft"
    assert cs.stack.currentWidget() is cs._fft_card

    cs.set_mode("time")
    assert cs.current_mode() == "time"
    assert cs.stack.currentWidget() is cs._time_split

    cs.set_plot_mode("overlay")
    assert cs.plot_mode() == "overlay"
    cs.set_cursor_mode("single")
    assert cs.cursor_mode() == "single"


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
