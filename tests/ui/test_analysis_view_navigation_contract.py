"""Page navigation and remembered pair chrome use the production wiring."""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui_kit import load_stylesheet
from .test_analysis_view_comparison_regressions import win, prep
from .test_analysis_view_comparison import _arm_compute_spies
from .test_analysis_comparison_state_contract import _click_canvas
from .test_analysis_comparison_tabs import _render_swatch_sides


SECTIONS = ("fft", "fft_time", "order", "frf")


def _setup(win, section, qtbot, panes=(1, 1)):
    load_stylesheet(QApplication.instance())
    page, manager, a, b = prep(win, section)
    manager.new_view(activate=False)
    c = manager.get(2)
    for state, count in zip((a, b), panes):
        if count == 2:
            state.add_pane()
            state.panes[1].sources = list(state.panes[0].sources)
    a.params["window"] = "hanning"
    b.params["window"] = "hamming"
    manager.set_color(0, "#dc2626")
    manager.set_color(1, "#16a34a")
    manager.set_color(2, "#2563eb")
    win.resize(1600, 1000)
    win.show()
    assert win.open_comparison(section, a.view_id, b.view_id)
    qtbot.waitUntil(lambda: page.peer_cards()[0].isVisible())
    return page, manager, a, b, c


def _click_tab(page, state, qtbot):
    tabs = page.tabbar.tabBar()
    index = page.manager.views.index(state)
    QApplication.processEvents()
    point = tabs.tabRect(index).center()
    if tabs.isTabVisible(index):
        assert tabs.tabAt(point) == index
        QTest.mouseClick(tabs, Qt.LeftButton, pos=point)
    else:
        # Two heatmap panes can retire non-active tabs into the real overflow.
        QTest.mouseClick(page.tabbar._overflow, Qt.LeftButton)
        popup = page.tabbar._overflow_popup
        row = next(button for button in popup._row_name_buttons
                   if button.property("viewId") == state.view_id)
        QTest.mouseClick(row, Qt.LeftButton)
    QApplication.processEvents()
    _assert_selection(page, state, qtbot)


def _assert_selection(page, state, qtbot):
    index = page.manager.views.index(state)
    assert page.manager.active == index
    assert page.tabbar.tabBar().currentIndex() == index
    assert page.tabbar._marker_view_id == state.view_id
    qtbot.waitUntil(lambda: not page.tabbar._marker_driver.is_active())


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("panes", [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_tabs_open_own_page_and_restore_pair(win, section, panes, qtbot, monkeypatch):
    page, manager, a, b, c = _setup(win, section, qtbot, panes)
    calls = _arm_compute_spies(monkeypatch, win)
    comp = win._comparison()
    _click_canvas(page.peer_cards()[-1].canvas)
    assert comp.focused(section) == (b.view_id, panes[1] - 1)
    _assert_selection(page, a, qtbot)
    _click_tab(page, a, qtbot)
    assert comp.focused(section) == (b.view_id, panes[1] - 1)
    for state in (b, c, b, a):
        _click_tab(page, state, qtbot)
        assert comp.peer_of(section, a.view_id) == b.view_id
        if state is a:
            assert comp.displayed(section) == (a.view_id, b.view_id)
            assert len(page.peer_cards()) == panes[1]
        else:
            assert comp.displayed(section) is None
            assert page.peer_cards() == []
        assert page.pane_count() == len(state.panes)
    assert a.params["window"] == "hanning"
    assert b.params["window"] == "hamming"
    assert calls == []


@pytest.mark.parametrize("section", SECTIONS)
def test_overflow_and_shortcut_navigate_to_peer_page(win, section, qtbot):
    page, manager, a, b, _c = _setup(win, section, qtbot)
    page._compare_row.setFixedWidth(500)
    QApplication.processEvents()
    QTest.mouseClick(page.tabbar._overflow, Qt.LeftButton)
    popup = page.tabbar._overflow_popup
    assert popup.isVisible()
    row = next(button for button in popup._row_name_buttons
               if button.property("viewId") == b.view_id)
    QTest.mouseClick(row, Qt.LeftButton)
    _assert_selection(page, b, qtbot)
    assert not page.peer_cards()
    assert page.tabbar._overflow_rows()[0].partner_color == b.tab_color
    # The same dispatcher is connected to the section's numbered shortcuts.
    win._switch_view_for_active_section(0)
    _assert_selection(page, a, qtbot)
    win._switch_view_for_active_section(1)
    _assert_selection(page, b, qtbot)
    assert not page.peer_cards()


@pytest.mark.parametrize("section", SECTIONS)
def test_inactive_relations_survive_module_and_project_reopen(win, section, qtbot, tmp_path):
    page, manager, a, b, c = _setup(win, section, qtbot)
    _click_tab(page, c, qtbot)
    win.toolbar._set_mode("time")
    win.toolbar._set_mode(section)
    assert page.tabbar._partner_color_for(0) == b.tab_color
    project = tmp_path / "inactive-pair.tlproj"
    assert win.save_project(project)
    win.open_project(project)
    win.toolbar._set_mode(section)
    page = win._analysis_page(section)
    manager = win.analysis_managers[section]
    a, b, c = manager.views
    _assert_selection(page, c, qtbot)
    assert not page.peer_cards()
    assert page.tabbar._partner_color_for(0) == b.tab_color
    _click_tab(page, a, qtbot)
    assert win._comparison().displayed(section) == (a.view_id, b.view_id)
    _click_tab(page, c, qtbot)
    win._on_analysis_delete(section, manager.views.index(b))
    assert win._comparison().peer_of(section, a.view_id) is None
    assert page.tabbar._partner_color_for(0) is None


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("ratio", [1, 2])
def test_inactive_host_keeps_real_half_swatch_and_overflow_relation(win, section, ratio, qtbot):
    page, manager, a, b, c = _setup(win, section, qtbot)
    _click_tab(page, c, qtbot)
    assert not page.peer_cards()
    assert page.tabbar._partner_color_for(0) == b.tab_color
    assert _render_swatch_sides(page.tabbar, 0, ratio) == (a.tab_color, b.tab_color)
    assert _render_swatch_sides(page.tabbar, 1, ratio) == (b.tab_color, b.tab_color)
    assert page.tabbar._overflow_rows()[0].partner_color == b.tab_color
    manager.set_color(1, "#8844cc")
    manager.rename(1, "Independent B")
    manager.reorder(1, 2)
    assert page.tabbar._partner_color_for(0) == "#8844cc"
    _click_tab(page, a, qtbot)
    win.close_comparison(section)
    assert page.tabbar._partner_color_for(0) is None


@pytest.mark.parametrize("section", SECTIONS)
def test_direct_activation_captures_peer_and_does_not_bounce_to_host(win, section, qtbot):
    page, manager, a, b, _c = _setup(win, section, qtbot)
    _click_canvas(page.peer_cards()[0].canvas)
    manager.set_active(1)
    _assert_selection(page, b, qtbot)
    assert not win._comparison().is_open(section)
    assert win._analysis_ctx(section).current_params()["window"] == "hamming"


@pytest.mark.parametrize("section", SECTIONS)
def test_peer_own_pair_and_explicit_reverse_relation_are_one_level(win, section, qtbot):
    page, manager, a, b, c = _setup(win, section, qtbot)
    assert win.open_comparison(section, b.view_id, c.view_id)
    _click_tab(page, a, qtbot)
    assert win._comparison().displayed(section) == (a.view_id, b.view_id)
    _click_tab(page, b, qtbot)
    assert win._comparison().displayed(section) == (b.view_id, c.view_id)
    assert page.tabbar._partner_color_for(0) == b.tab_color
    assert page.tabbar._partner_color_for(1) == c.tab_color
    assert win.open_comparison(section, b.view_id, a.view_id)
    _click_tab(page, a, qtbot)
    _click_tab(page, b, qtbot)
    assert win._comparison().displayed(section) == (b.view_id, a.view_id)
    assert len(page.peer_cards()) == 1
    win._on_analysis_delete(section, 0)
    assert not win._comparison().relations_payload(section)
    assert all(page.tabbar._partner_color_for(i) is None for i in range(len(manager.views)))


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
@pytest.mark.parametrize("direct", [False, True])
def test_pending_peer_editor_is_captured_before_navigation(win, section, direct, qtbot, monkeypatch):
    page, manager, a, b, c = _setup(win, section, qtbot)
    calls = _arm_compute_spies(monkeypatch, win)
    _click_canvas(page.peer_cards()[0].canvas)
    editor = win._analysis_ctx(section).spin_db_ref
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "3.25")
    if direct:
        manager.set_active(2)
    else:
        _click_tab(page, c, qtbot)
    QApplication.processEvents()
    assert b.params["db_reference"] == 3.25
    assert a.params["db_reference"] != 3.25
    _click_tab(page, b, qtbot)
    assert editor.value() == 3.25
    assert calls == []
