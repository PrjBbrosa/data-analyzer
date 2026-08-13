from pathlib import Path

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def _host_clickables(host):
    layout = host.layout()
    buttons = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if isinstance(widget, QAbstractButton) and not widget.isHidden():
            buttons.append(widget)
    return buttons


def test_chartstack_mounts_tabbar_in_shared_bottom_dock(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    bar = cs.attach_view_tabbar(ViewManager())
    rail = cs.findChild(QWidget, "timeViewRail")

    assert isinstance(bar, ViewTabBar)
    assert rail is not None
    assert bar.parentWidget() is rail
    assert rail.parentWidget() is cs._time_bottom_dock
    assert cs._time_bottom_dock.objectName() == "timeViewBottomDock"
    assert cs._time_card.view_tabbar is None
    lay = cs._time_bottom_dock.layout()
    assert lay.indexOf(rail) < lay.indexOf(cs._time_hint_bar)
    assert cs.ultraview_entry is rail.findChild(QWidget, "ultraViewEntry")
    assert _host_clickables(rail)[-1] is cs.ultraview_entry


def test_chartstack_time_tabbar_shows_quiet_section_anchor(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    bar = cs.attach_view_tabbar(ViewManager())

    anchor = bar.findChild(QWidget, "viewSectionAnchor")
    label = bar.findChild(QLabel, "viewSectionAnchorLabel")
    assert anchor is not None
    assert label is not None
    assert label.text() == "时域"
    assert anchor.accessibleName() == "当前区域：时域"


def test_time_bottom_dock_has_compare_row_chrome(qtbot):
    """TimeDomain dock must paint the same light bar + top rule as analysis.

    Must be a QWidget (not QFrame): QFrame + QSS border-top insets
    contentsRect by 1px and shifts the hairline vs analysisCompareRow.
    """
    cs = ChartStack()
    qtbot.addWidget(cs)
    dock = cs._time_bottom_dock

    assert isinstance(dock, QWidget)
    assert type(dock) is QWidget  # not QFrame
    assert not dock.testAttribute(Qt.WA_TranslucentBackground)
    assert dock.testAttribute(Qt.WA_StyledBackground)
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    # The dock block itself carries the top divider (not only the hint bar).
    dock_block = qss.split("QWidget#timeViewBottomDock {", 1)[1].split("}", 1)[0]
    assert "border-top: 1px solid #dbe3ee;" in dock_block
    assert "background-color: #fbfcff;" in dock_block


def test_time_bottom_dock_top_hairline_matches_analysis_contents_inset(qtbot):
    """Hairline geometry parity: both chrome hosts keep contentsRect.top == 0."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 700)
    cs.show()
    qtbot.waitExposed(cs)
    cs.attach_view_tabbar(ViewManager())

    cs.set_mode("time")
    QApplication.processEvents()
    rail = cs.findChild(QWidget, "timeViewRail")
    assert cs._time_bottom_dock.contentsRect().top() == 0
    assert rail.geometry().top() == 0
    assert cs._view_tabbar.geometry().top() == 0
    assert rail.height() == 28
    assert cs.ultraview_entry.height() <= 28
    margins = rail.layout().contentsMargins()
    assert abs(
        cs.ultraview_entry.geometry().right()
        - (rail.width() - margins.right() - 1)
    ) <= 2
    assert _host_clickables(rail)[-1] is cs.ultraview_entry

    cs.set_mode("fft")
    QApplication.processEvents()
    row = cs.page_fft._compare_row
    assert row.contentsRect().top() == 0
    assert cs.page_fft.tabbar.geometry().top() == 0


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
    bars = cs._time_bottom_dock.findChildren(ViewTabBar)
    assert bars == [first]
    rails = cs._time_bottom_dock.findChildren(QWidget, "timeViewRail")
    assert rails == [cs.findChild(QWidget, "timeViewRail")]
    docks = [
        widget
        for widget in cs._time_bottom_dock.findChildren(QWidget, "ultraViewEntry")
    ]
    assert docks == [cs.ultraview_entry]


def test_time_ultraview_dock_stays_enabled_at_view_cap(qtbot):
    manager = ViewManager(max_views=2)
    manager.new_view()
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    bar = cs.attach_view_tabbar(manager)
    QApplication.processEvents()

    plus = bar.findChild(QPushButton, "viewTabPlus")
    assert not plus.isEnabled()
    assert cs.ultraview_entry.isEnabled()
    assert bar.findChild(QWidget, "ultraViewEntry") is None


def test_ultraview_page_has_no_source_dock(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.attach_view_tabbar(ViewManager())
    page = cs.page_ultraview
    assert page.findChild(QWidget, "ultraViewEntry") is None
    assert page.findChild(QWidget, "ultraViewEntrySeparator") is None


def _mapped_rect(host, widget):
    top_left = widget.mapTo(host, widget.rect().topLeft())
    return widget.rect().translated(top_left)


def _pump_rail(qtbot):
    QApplication.processEvents()
    qtbot.wait(20)
    QApplication.processEvents()


def _assert_dock_right_anchor(host, dock):
    margins = host.layout().contentsMargins()
    assert abs(dock.geometry().right() - (host.width() - margins.right() - 1)) <= 2
    assert host.height() == 28
    assert dock.height() <= 28
    assert _host_clickables(host)[-1] is dock
    assert dock.accessibleName() == "打开 UltraView"
    assert "只读对照" in dock.toolTip()


@pytest.mark.parametrize("merged", [False, True])
@pytest.mark.parametrize("width", [1100, 420])
def test_time_rail_state_matrix_keeps_dock_as_right_anchor(qtbot, merged, width):
    manager = ViewManager()
    if merged:
        manager.new_view()
        manager.set_active(0)
        manager.set_split(1)
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 640)
    cs.show()
    qtbot.waitExposed(cs)
    bar = cs.attach_view_tabbar(manager)
    rail = cs.findChild(QWidget, "timeViewRail")
    rail.setFixedWidth(width)
    _pump_rail(qtbot)

    dock = cs.ultraview_entry
    clear = bar._split_clear
    assert dock.isVisible()
    _assert_dock_right_anchor(rail, dock)
    assert bar.tabBar().isTabVisible(manager.active)
    assert bar._plus.isVisible()
    assert bar.rect().contains(bar._plus.geometry())

    if merged:
        assert clear.isVisible()
        assert clear.text() == "✕ 取消合并"
        assert clear.parentWidget() is bar
        clear_rect = _mapped_rect(rail, clear)
        dock_rect = _mapped_rect(rail, dock)
        assert clear_rect.right() <= dock_rect.left()
        assert not clear_rect.intersects(dock_rect)
    else:
        assert not clear.isVisible()


def test_repeat_attach_does_not_duplicate_open_signal(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    hits = []

    def _record_open():
        hits.append(True)

    cs.open_ultraview_requested.connect(_record_open)
    manager = ViewManager()
    cs.attach_view_tabbar(manager)
    cs.attach_view_tabbar(manager)
    cs.set_mode("fft")
    cs.set_mode("time")
    cs.ultraview_entry.click()
    assert hits == [True]


def test_time_rail_overflow_keeps_current_tab_and_dock(qtbot):
    manager = ViewManager()
    while manager.new_view() != -1:
        pass
    manager.set_active(len(manager.views) - 1)
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 640)
    cs.show()
    qtbot.waitExposed(cs)
    bar = cs.attach_view_tabbar(manager)
    rail = cs.findChild(QWidget, "timeViewRail")
    rail.setFixedWidth(420)
    _pump_rail(qtbot)

    tabs = bar.tabBar()
    assert tabs.isTabVisible(manager.active)
    assert bar.overflow_indices()
    assert manager.active not in bar.overflow_indices()
    assert bar._plus.isVisible()
    assert not bar._plus.isEnabled()
    assert cs.ultraview_entry.isEnabled()
    _assert_dock_right_anchor(rail, cs.ultraview_entry)


@pytest.mark.parametrize(
    "page_attr, split, expect_link, expect_lock",
    [
        ("page_fft", False, False, False),
        ("page_fft", True, True, False),
        ("page_frf", True, True, False),
        ("page_fft_time", True, True, True),
        ("page_order", True, True, True),
    ],
)
@pytest.mark.parametrize("width", [1100, 520])
def test_analysis_rail_state_matrix_on_chart_stack(
    qtbot, page_attr, split, expect_link, expect_lock, width,
):
    mode_by_page = {
        "page_fft": "fft",
        "page_fft_time": "fft_time",
        "page_frf": "frf",
        "page_order": "order",
    }
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 700)
    cs.show()
    qtbot.waitExposed(cs)
    page = getattr(cs, page_attr)
    cs.set_mode(mode_by_page[page_attr])
    if split:
        page.enter_split()
    host = page._compare_row
    host.setFixedWidth(width)
    _pump_rail(qtbot)

    dock = page.ultraview_entry
    sep = page.ultraview_separator
    clear = page.tabbar._split_clear
    assert dock.isVisible()
    assert sep.isVisible()
    assert _host_clickables(host)[-1] is dock
    assert clear.isVisible() is split
    if split:
        assert clear.text() == "✕ 关闭对比窗格"
        assert clear.parentWidget() is page.tabbar
    assert page.btn_link.isVisible() is expect_link
    assert page.btn_lock_levels.isVisible() is expect_lock
    _assert_dock_right_anchor(host, dock)

    order = []
    if split:
        order.append(clear)
    if expect_link:
        order.append(page.btn_link)
    if expect_lock:
        order.append(page.btn_lock_levels)
    order.extend([sep, dock])
    rects = [_mapped_rect(host, widget) for widget in order]
    for left, right in zip(rects, rects[1:]):
        assert left.right() <= right.left()
        assert not left.intersects(right)
    assert page.tabbar.tabBar().isTabVisible(page.manager.active)
