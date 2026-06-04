from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def test_chartstack_mounts_tabbar_in_time_card(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    bar = cs.attach_view_tabbar(ViewManager())

    assert isinstance(bar, ViewTabBar)
    card = cs._time_card
    lay = card.layout()
    assert card.view_tabbar is bar
    assert lay.indexOf(bar) == lay.indexOf(card._hint_bar) - 1


def test_chartstack_exposes_cursor_mode(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    cs.set_cursor_mode("single")

    assert cs.cursor_mode() == "single"


def test_tabbar_hidden_outside_time_mode(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    bar = cs.attach_view_tabbar(ViewManager())

    assert bar.isVisible()
    cs.set_mode("fft")
    assert not bar.isVisible()
    cs.set_mode("time")
    assert bar.isVisible()


def test_attach_view_tabbar_initializes_hidden_outside_time_mode(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("fft")

    bar = cs.attach_view_tabbar(ViewManager())

    assert not bar.isVisible()


def test_attach_view_tabbar_is_idempotent(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    first = cs.attach_view_tabbar(ViewManager())
    second = cs.attach_view_tabbar(ViewManager())

    assert second is first
    bars = cs._time_card.findChildren(ViewTabBar)
    assert bars == [first]
