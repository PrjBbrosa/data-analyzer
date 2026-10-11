"""Analysis comparison relationship projection uses the shared tab painter."""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar, tab_swatch_visual_rect
from mf4_analyzer.ui_kit import load_stylesheet


def _analysis_bar(qtbot, *, count=3, panes=1):
    manager = ViewManager(state_factory=AnalysisViewState)
    for _ in range(count - 1):
        manager.new_view()
    manager.set_active(0)
    manager.set_color(0, "#dc2626")
    manager.set_color(1, "#16a34a")
    relation = {}

    def partner_index(index):
        peer_id = relation.get(manager.get(index).view_id)
        return next((i for i, view in enumerate(manager.views)
                     if view.view_id == peer_id), None)

    bar = ViewTabBar(
        manager, section="fft", split_action_mode="active_pane",
        split_action_labels={"split": "添加同参数窗格", "clear": "关闭同参数窗格"},
        active_split_provider=lambda: panes,
        comparison_partner_provider=partner_index,
        comparison_open_provider=lambda: bool(relation),
    )
    qtbot.addWidget(bar)
    bar.resize(800, 30)
    bar.show()
    QApplication.processEvents()
    return manager, bar, relation


def _render_swatch_sides(bar, index, ratio):
    tabs = bar.tabBar()
    tabs.clear_interaction_state()
    image = QPixmap(round(tabs.width() * ratio), round(tabs.height() * ratio))
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.transparent)
    tabs.render(image)
    image = image.toImage()
    rect = tab_swatch_visual_rect(tabs, index)
    y = round((rect.top() + 3) * ratio)
    return tuple(image.pixelColor(round(x * ratio), y).name()
                 for x in (rect.left() + 2, rect.left() + 7))


@pytest.mark.parametrize("ratio", [1, 2])
def test_analysis_relation_paints_host_halves_and_solid_peer(qtbot, qapp, ratio):
    old_style = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        manager, bar, relation = _analysis_bar(qtbot)
        relation[manager.get(0).view_id] = manager.get(1).view_id
        bar.refresh_comparison_presentation()
        assert _render_swatch_sides(bar, 0, ratio) == ("#dc2626", "#16a34a")
        assert _render_swatch_sides(bar, 1, ratio) == ("#16a34a", "#16a34a")
        assert manager._split_pairs == {}
        relation.clear()
        bar.refresh_comparison_presentation()
        assert _render_swatch_sides(bar, 0, ratio) == ("#dc2626", "#dc2626")
    finally:
        qapp.setStyleSheet(old_style)


def test_relation_tracks_identity_through_color_rename_reorder_and_delete(qtbot):
    manager, bar, relation = _analysis_bar(qtbot)
    host_id, peer_id = manager.get(0).view_id, manager.get(1).view_id
    relation[host_id] = peer_id
    bar.refresh_comparison_presentation()
    manager.set_color(1, "#2563eb")
    manager.rename(1, "Independent B")
    manager.reorder(1, 2)
    assert bar._partner_color_for(0) == "#2563eb"
    assert bar._partner_color_for(2) is None
    rows = bar._overflow_rows()
    assert rows[0].partner_color == "#2563eb"
    assert rows[2].name == "Independent B"
    assert rows[2].view_id == peer_id
    manager.delete_view(2)
    assert bar._partner_color_for(0) is None
    assert bar._overflow_rows()[0].partner_color is None
    assert manager._split_pairs == {}


def test_relation_refresh_updates_open_overflow_without_switching(qtbot, monkeypatch):
    manager, bar, relation = _analysis_bar(qtbot, count=10)
    bar.resize(340, 30)
    QApplication.processEvents()
    assert bar.overflow_indices()
    bar._on_overflow_clicked()
    popup = bar._overflow_popup
    assert popup.isVisible()
    projected = []
    original = popup.populate

    def record(rows):
        projected.append(rows)
        original(rows)

    monkeypatch.setattr(popup, "populate", record)
    relation[manager.get(0).view_id] = manager.get(1).view_id
    bar.refresh_comparison_presentation()
    assert projected[-1][0].partner_color == "#16a34a"
    relation.clear()
    bar.refresh_comparison_presentation()
    assert projected[-1][0].partner_color is None
    assert manager.active == 0
    bar._close_overflow_popup()


@pytest.mark.parametrize("panes", [1, 2])
@pytest.mark.parametrize("index", [0, 1])
def test_independent_compare_precedes_explicit_host_pane_action(qtbot, monkeypatch, panes, index):
    manager, bar, _relation = _analysis_bar(qtbot, panes=panes)
    manager.rename(0, "Host A")
    emitted = []
    bar.split_requested.connect(emitted.append)
    bar.clear_split_requested.connect(emitted.append)

    def choose(menu, *_args):
        actions = menu.actions()
        compare_index = next(i for i, action in enumerate(actions)
                             if action.text().startswith("与"))
        pane_index = next(i for i, action in enumerate(actions)
                          if "同参数窗格" in action.text())
        action = actions[pane_index]
        assert compare_index < pane_index
        assert "Host A" in action.text()
        assert "共享分析参数" in action.toolTip()
        assert action.isEnabled() == (index == manager.active)
        return action

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", choose)
    bar._on_context_menu(bar.tabBar().tabRect(index).center())
    assert emitted == ([0] if index == 0 else [])


def test_split_clear_names_host_even_when_peer_focused(qtbot):
    manager, bar, relation = _analysis_bar(qtbot, panes=2)
    manager.rename(0, "Host A")
    relation[manager.get(0).view_id] = manager.get(1).view_id
    bar.set_split_focus(True)
    bar.refresh_comparison_presentation()
    assert "Host A" in bar._split_clear.toolTip()
    assert "Host A" in bar._split_clear.accessibleName()
    assert "同参数窗格" in bar._split_clear.toolTip()
    assert "当前" not in bar._split_clear.toolTip()


@pytest.mark.parametrize("section", ["fft", "fft_time", "order", "frf"])
@pytest.mark.parametrize("panes", [1, 2])
def test_narrow_comparison_rail_keeps_active_tab_hittable(qtbot, qapp, section, panes):
    from mf4_analyzer.ui.chart_stack import ChartStack

    old_style = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        stack = ChartStack()
        qtbot.addWidget(stack)
        stack.resize(1100, 700)
        stack.show()
        stack.set_mode(section)
        page = stack.page_for_mode[section]
        manager = page.manager
        manager.new_view(activate=False)
        if panes == 2:
            page.enter_split()
        page.show_comparison_peer(manager.get(0).view_id, manager.get(1).view_id, panes)
        page._compare_row.setFixedWidth(490)
        tabs = page.tabbar.tabBar()
        qtbot.waitUntil(
            lambda: tabs.tabRect(manager.active).intersected(tabs.rect()).width()
            == tabs.tabRect(manager.active).width(), timeout=2000)
        rect = tabs.tabRect(manager.active)
        assert tabs.isTabVisible(manager.active)
        assert rect.intersected(tabs.rect()).width() == rect.width(), (tabs.rect(), rect)
        assert tabs.tabAt(rect.center()) == manager.active
        assert tabs.rect().contains(tab_swatch_visual_rect(tabs, manager.active))
        options = page.btn_compare_options
        if panes == 2 or section in {"fft_time", "order"}:
            assert options.isVisible()
        menu = options.menu()
        menu.aboutToShow.emit()
        visible_actions = [action for action in menu.actions() if action.isVisible()]
        assert len(visible_actions) == (5 if panes == 2 and section in {"fft_time", "order"}
                                        else 3 if panes == 2 else 3 if section in {"fft_time", "order"} else 2)
        linked = []
        page.comparison_display_toggled.connect(lambda *args: linked.append(args))
        action = next(action for action in visible_actions if action.text() == "联动两 View")
        action.trigger()
        assert linked == [("axis_linked", True)]
        page._compare_row.setFixedWidth(1100)
        qtbot.wait(80)
        assert not options.isVisible()
        assert page.btn_view_link.isVisible()
        assert page.btn_view_link.isChecked()
    finally:
        qapp.setStyleSheet(old_style)
