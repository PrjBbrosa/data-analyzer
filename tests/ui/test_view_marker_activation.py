"""ViewTabBar marker motion: direct UI interpolates, program syncs snap."""

from PyQt5.QtCore import QEvent, QPoint, QRectF, Qt
from PyQt5.QtGui import QHoverEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from mf4_analyzer.ui.analysis_section_page import AnalysisSectionPage
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import (
    MAX_VIEWS,
    TIME_DOMAIN_MAX_VIEWS,
    ViewManager,
)
from mf4_analyzer.ui.view_tabbar import (
    ViewTabBar,
    tab_close_hit_rect,
    tab_marker_rect,
)
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, duration_ms

from tests.ui.test_analysis_section_page import _FakeCard
from tests.ui.test_view_tabbar import (
    _advance_marker,
    _between,
    _hover_icon_slot,
    _measure,
    _motion_shown_bar,
    _open_overflow_popup,
    _resize_to_budget,
    _shown_bar,
    _signal_lists,
    _wide_bar,
)


def _click_tab_body(tabs, idx):
    rect = tabs.tabRect(idx)
    slot = tab_close_hit_rect(tabs, idx)
    point = rect.center()
    if slot.isValid() and slot.contains(point):
        point = QPoint(rect.right() - 6, rect.center().y())
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, point)
    QApplication.processEvents()


def _wire_switch(manager, bar):
    bar.switch_requested.connect(manager.set_active)


def _armed_user_target(bar):
    return getattr(bar, "_user_marker_view_id", None)


def test_generic_viewtabbar_stays_policy_off(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=0)

    assert bar.motion_policy() == POLICY_OFF
    assert not bar.motion_policy().interpolates()
    assert bar.tabBar().property("paintedMarker") in (None, "false")


def test_chartstack_and_analysis_page_enable_light_after_construction(qtbot):
    time_manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    time_manager.new_view()
    cs = ChartStack()
    qtbot.addWidget(cs)
    time_bar = cs.attach_view_tabbar(time_manager)

    assert time_bar.motion_policy() == POLICY_LIGHT
    assert cs.page_fft.tabbar.motion_policy() == POLICY_LIGHT
    assert cs.page_fft_time.tabbar.motion_policy() == POLICY_LIGHT
    assert cs.page_frf.tabbar.motion_policy() == POLICY_LIGHT
    assert cs.page_order.tabbar.motion_policy() == POLICY_LIGHT
    assert cs.analysis_managers["fft"].max_views == MAX_VIEWS
    assert time_manager.max_views == TIME_DOMAIN_MAX_VIEWS

    isolated = ViewTabBar(ViewManager())
    qtbot.addWidget(isolated)
    assert isolated.motion_policy() == POLICY_OFF


def test_analysis_section_page_constructor_enables_light(qtbot):
    manager = ViewManager(state_factory=AnalysisViewState, max_views=MAX_VIEWS)
    page = AnalysisSectionPage(
        section="fft",
        manager=manager,
        card_factory=_FakeCard,
    )
    qtbot.addWidget(page)

    assert page.tabbar.motion_policy() == POLICY_LIGHT
    assert manager.max_views == MAX_VIEWS


def test_direct_click_interpolates_on_stable_view_id_not_name_or_ordinal(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    manager.rename(0, "Same")
    manager.rename(1, "Same")
    QApplication.processEvents()
    target_id = manager.get(1).view_id
    armed = []

    def _capture(idx):
        armed.append(_armed_user_target(bar))
        manager.set_active(idx)

    bar.switch_requested.connect(_capture)
    start = QRectF(bar._marker_rect)

    _click_tab_body(bar.tabBar(), 1)

    assert armed == [target_id]
    assert manager.active == 1
    assert manager.views[manager.active].view_id == target_id
    assert bar._marker_view_id == target_id
    assert bar._marker_driver.is_active()
    assert duration_ms("view_marker", POLICY_LIGHT) == 140
    assert bar._marker_driver.clock().duration() == 140
    assert bar._marker_rect.height() == 2
    _advance_marker(bar, 35)
    assert bar._marker_rect != start
    assert _between(bar._marker_rect.x(), start.x(), tab_marker_rect(bar.tabBar().tabRect(1)).x())
    assert _armed_user_target(bar) in (None, "")


def test_manager_set_active_snaps_without_user_target(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    switches = []
    bar.switch_requested.connect(switches.append)
    target = tab_marker_rect(bar.tabBar().tabRect(2))

    manager.set_active(2)
    QApplication.processEvents()

    assert switches == []
    assert manager.active == 2
    assert bar._marker_view_id == manager.get(2).view_id
    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == target
    assert bar._marker_rect.height() == 2


def test_rejected_user_switch_does_not_leave_target_for_later_program_sync(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    switches = []
    bar.switch_requested.connect(switches.append)
    before = QRectF(bar._marker_rect)

    _click_tab_body(bar.tabBar(), 1)

    assert switches == [1]
    assert manager.active == 0
    assert _armed_user_target(bar) in (None, "")
    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == before

    manager.set_active(1)
    QApplication.processEvents()

    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == tab_marker_rect(bar.tabBar().tabRect(1))
    assert bar._marker_view_id == manager.get(1).view_id


def test_business_correction_snaps_to_confirmed_view(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)

    def _correct(idx):
        del idx
        manager.set_active(2)

    bar.switch_requested.connect(_correct)
    _click_tab_body(bar.tabBar(), 1)

    assert manager.active == 2
    assert _armed_user_target(bar) in (None, "")
    assert not bar._marker_driver.is_active()
    assert bar._marker_view_id == manager.get(2).view_id
    assert bar._marker_rect == tab_marker_rect(bar.tabBar().tabRect(2))


def test_rapid_reverse_clicks_continue_from_displayed_position_without_queue(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    switches = []
    bar.switch_requested.connect(switches.append)
    _wire_switch(manager, bar)
    start = QRectF(bar._marker_rect)
    mid_target = tab_marker_rect(bar.tabBar().tabRect(1))
    end_target = tab_marker_rect(bar.tabBar().tabRect(2))

    _click_tab_body(bar.tabBar(), 1)
    assert bar._marker_driver.is_active()
    _advance_marker(bar, 35)
    mid = QRectF(bar._marker_rect)
    assert mid != start
    assert mid != mid_target
    assert _between(mid.x(), start.x(), mid_target.x())
    assert mid.height() == 2

    _click_tab_body(bar.tabBar(), 2)
    assert switches == [1, 2]
    assert manager.active == 2
    assert QRectF(bar._marker_driver.clock().startValue()) == mid
    assert bar._marker_driver.target() == end_target
    assert bar._marker_driver.is_active()
    assert bar._marker_driver.clock().duration() == 140

    _advance_marker(bar, 140)
    assert bar._marker_rect == end_target
    assert not bar._marker_driver.is_active()


def test_overflow_menu_switch_that_reenters_strip_snaps(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    bar.set_motion_policy(POLICY_LIGHT)
    _wire_switch(manager, bar)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    hidden = bar.overflow_indices()
    assert hidden
    target = hidden[-1]
    target_id = manager.views[target].view_id
    target_name = manager.views[target].name
    assert not bar.tabBar().isTabVisible(target)

    popup = _open_overflow_popup(bar)
    name_btn = next(
        btn
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
        if btn.text() == target_name
    )
    qtbot.mouseClick(name_btn, Qt.LeftButton)
    QApplication.processEvents()

    assert manager.active == target
    assert manager.views[manager.active].view_id == target_id
    assert bar.tabBar().isTabVisible(target)
    assert target not in bar.overflow_indices()
    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == tab_marker_rect(bar.tabBar().tabRect(target))
    assert not bar.tabBar().usesScrollButtons()


def test_compact_labels_still_activate_by_view_id(qtbot):
    manager, bar = _wide_bar(qtbot, count=10)
    bar.set_motion_policy(POLICY_LIGHT)
    _wire_switch(manager, bar)
    roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, (roomy + compact) // 2)
    assert bar.is_compact()
    target_id = manager.get(3).view_id
    assert bar.tabBar().tabText(3) == "4"
    assert bar.tabBar().tabToolTip(3) == manager.views[3].name

    _click_tab_body(bar.tabBar(), 3)

    assert manager.views[manager.active].view_id == target_id
    assert bar._marker_view_id == target_id
    assert bar.tabBar().tabText(3) == "4"


def test_marker_does_not_steal_input_or_change_hit_rects(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    _wire_switch(manager, bar)
    tabs = bar.tabBar()
    before_size = bar.size()
    before_card = bar.height()
    marker = tab_marker_rect(tabs.tabRect(1))
    point = marker.center().toPoint()
    assert tabs.tabRect(1).contains(point)
    assert bar.findChild(QWidget, "viewTabMarker") is None

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, point)
    QApplication.processEvents()

    assert manager.active == 1
    assert bar.size() == before_size
    assert bar.height() == before_card
    for idx in range(tabs.count()):
        hit = tab_close_hit_rect(tabs, idx)
        assert hit.isValid()
        assert tabs.tabRect(idx).contains(hit.center())
    assert not tabs.testAttribute(Qt.WA_TransparentForMouseEvents)


def test_chartstack_user_click_interpolates_and_program_snaps(qtbot):
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    manager.new_view()
    manager.new_view()
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 700)
    cs.show()
    qtbot.waitExposed(cs)
    bar = cs.attach_view_tabbar(manager)
    _wire_switch(manager, bar)
    QApplication.processEvents()
    card_geo = cs._time_card.geometry()
    assert bar.motion_policy() == POLICY_LIGHT
    assert bar.tabBar().property("paintedMarker") == "true"

    manager.set_active(2)
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == tab_marker_rect(bar.tabBar().tabRect(2))

    _click_tab_body(bar.tabBar(), 1)
    assert manager.active == 1
    assert bar._marker_driver.is_active()
    assert bar._marker_driver.clock().duration() == 140
    assert cs._time_card.geometry() == card_geo
    assert not bar.tabBar().usesScrollButtons()


def test_analysis_page_user_click_interpolates_and_program_snaps(qtbot):
    manager = ViewManager(state_factory=AnalysisViewState, max_views=MAX_VIEWS)
    manager.new_view()
    manager.new_view()
    page = AnalysisSectionPage(
        section="fft",
        manager=manager,
        card_factory=_FakeCard,
    )
    qtbot.addWidget(page)
    page.resize(900, 500)
    page.show()
    qtbot.waitExposed(page)
    bar = page.tabbar
    _wire_switch(manager, bar)
    QApplication.processEvents()
    assert bar.motion_policy() == POLICY_LIGHT

    manager.set_active(2)
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()

    _click_tab_body(bar.tabBar(), 0)
    assert manager.active == 0
    assert bar._marker_driver.is_active()
    assert bar._marker_rect.height() == 2


def test_time_and_analysis_caps_come_from_manager_not_a_unified_constant(qtbot):
    time_manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    while time_manager.new_view() != -1:
        pass
    time_bar = ViewTabBar(time_manager)
    qtbot.addWidget(time_bar)
    time_bar.set_motion_policy(POLICY_LIGHT)
    time_bar.show()
    QApplication.processEvents()
    assert len(time_manager.views) == TIME_DOMAIN_MAX_VIEWS
    assert time_manager.max_views == TIME_DOMAIN_MAX_VIEWS
    assert not time_bar._plus.isEnabled()
    assert time_manager.new_view() == -1

    analysis_manager = ViewManager(
        state_factory=AnalysisViewState, max_views=MAX_VIEWS,
    )
    while analysis_manager.new_view() != -1:
        pass
    page = AnalysisSectionPage(
        section="order",
        manager=analysis_manager,
        card_factory=_FakeCard,
    )
    qtbot.addWidget(page)
    page.show()
    QApplication.processEvents()
    assert len(analysis_manager.views) == MAX_VIEWS
    assert analysis_manager.max_views == MAX_VIEWS
    assert not page.tabbar._plus.isEnabled()
    assert analysis_manager.new_view() == -1
    assert TIME_DOMAIN_MAX_VIEWS != MAX_VIEWS


def test_last_view_cannot_close_and_close_all_keeps_default(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    bar.delete_requested.connect(manager.delete_view)
    bar.close_all_requested.connect(manager.reset_to_single_default)
    only = ViewManager()
    only_bar = ViewTabBar(only)
    qtbot.addWidget(only_bar)
    only_bar.set_motion_policy(POLICY_LIGHT)
    only_bar.show()
    QApplication.processEvents()

    assert not only_bar._views_closable()
    only.delete_view(0)
    assert len(only.views) == 1
    only_bar.delete_requested.emit(0)
    QApplication.processEvents()
    assert len(only.views) == 1

    bar.close_all_requested.emit()
    QApplication.processEvents()
    assert len(manager.views) == 1
    assert manager.active == 0
    assert manager.views[0].name == "View 1"
    assert not bar._marker_driver.is_active()


def test_switched_swatch_still_requires_pointer_reentry_before_close(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    _wire_switch(manager, bar)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.sendEvent(
        tabs,
        QHoverEvent(QEvent.HoverMove, slot.center(), slot.center()),
    )
    QApplication.processEvents()

    assert manager.active == 1
    assert tabs.hover_index() == -1
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()
    assert deleted == []

    body = tabs.tabRect(1).center()
    assert not slot.contains(body)
    QApplication.sendEvent(
        tabs, QHoverEvent(QEvent.HoverMove, body, slot.center())
    )
    QApplication.sendEvent(
        tabs, QHoverEvent(QEvent.HoverMove, slot.center(), body)
    )
    QApplication.processEvents()
    assert tabs.hover_index() == 1

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()
    assert deleted == [1]
    assert switched == [1]
    assert renamed == []
    assert reordered == []


def test_add_close_reorder_and_restore_snap_even_under_light_policy(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    _wire_switch(manager, bar)
    _click_tab_body(bar.tabBar(), 1)
    assert bar._marker_driver.is_active()

    manager.new_view()
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()
    assert bar._marker_view_id == manager.get(manager.active).view_id

    _click_tab_body(bar.tabBar(), 0)
    assert bar._marker_driver.is_active()
    manager.delete_view(1)
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()

    _click_tab_body(bar.tabBar(), 1)
    _advance_marker(bar, 35)
    assert bar._marker_driver.is_active()
    bar.reorder_requested.connect(manager.reorder)
    bar.tabBar().moveTab(0, 2)
    bar._resync_after_reorder()
    bar._clear_reorder_switch_suppression()
    bar._pending_reorder_resync = False
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()

    current = bar.tabBar().currentIndex()
    other = next(
        idx
        for idx in range(bar.tabBar().count())
        if idx != current and bar.tabBar().isTabVisible(idx)
    )
    _click_tab_body(bar.tabBar(), other)
    assert bar._marker_driver.is_active()
    manager.reset_to_single_default()
    QApplication.processEvents()
    assert len(manager.views) == 1
    assert not bar._marker_driver.is_active()
    assert bar._marker_view_id == manager.get(0).view_id


def test_hide_resize_and_off_policy_restore_static_marker_without_driver(qtbot):
    manager, bar = _motion_shown_bar(qtbot, count=3, active=0)
    _wire_switch(manager, bar)
    _click_tab_body(bar.tabBar(), 1)
    assert bar._marker_driver.is_active()
    assert bar.tabBar().property("paintedMarker") == "true"

    bar.resize(bar.width() + 80, bar.height())
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()
    assert bar._marker_rect == tab_marker_rect(bar.tabBar().tabRect(1))

    _click_tab_body(bar.tabBar(), 2)
    assert bar._marker_driver.is_active()
    bar.hide()
    QApplication.processEvents()
    assert not bar._marker_driver.is_active()

    bar.show()
    QApplication.processEvents()
    bar.set_motion_policy(POLICY_OFF)
    assert bar.tabBar().property("paintedMarker") == "false"
    assert not bar._marker_rect.isValid()
    assert not bar._marker_driver.is_active()
    manager.set_active(0)
    QApplication.processEvents()
    assert not bar._marker_rect.isValid()
    assert not bar._marker_driver.is_active()
