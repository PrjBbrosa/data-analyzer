from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def test_chartstack_mounts_tabbar_in_shared_bottom_dock(qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    bar = cs.attach_view_tabbar(ViewManager())

    assert isinstance(bar, ViewTabBar)
    assert bar.parentWidget() is cs._time_bottom_dock
    assert cs._time_bottom_dock.objectName() == "timeViewBottomDock"
    assert cs._time_card.view_tabbar is None
    lay = cs._time_bottom_dock.layout()
    assert lay.indexOf(bar) < lay.indexOf(cs._time_hint_bar)


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
    assert cs._time_bottom_dock.contentsRect().top() == 0
    assert cs._view_tabbar.geometry().top() == 0

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
