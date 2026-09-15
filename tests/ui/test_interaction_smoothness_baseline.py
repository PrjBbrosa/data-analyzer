"""T0 input-path baseline for later interaction-cost and transition work.

This is intentionally a final-state regression test, not a timing assertion:
offscreen Qt cannot establish Cocoa paint latency.  It proves that the user
click paths used by the motion probe still reach the existing View and Section
owners before T1--T3 change their projection costs.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from mf4_analyzer.ui.main_window import MainWindow


def _checked_pairs(window):
    return [(fid, channel) for fid, channel, _color in window.navigator.get_checked_channels()]


def _drain(qapp, rounds=4):
    for _ in range(rounds):
        qapp.processEvents()


def test_qtest_view_tab_and_section_toolbar_keep_the_real_target(
    qtbot, qapp, loaded_csv
):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 760)
    window.show()
    qtbot.waitExposed(window)
    window.load_file(loaded_csv)
    _drain(qapp)
    fid = next(iter(window.files))

    window.navigator.set_checked_channels([(fid, "speed")])
    window.plot_time()
    _drain(qapp)
    window._capture_current_view()

    window._on_view_new()
    _drain(qapp)
    window._attach_files_to_focused_view([fid])
    window.navigator.set_checked_channels([(fid, "torque")])
    window.plot_time()
    _drain(qapp)
    window._capture_current_view()
    assert window.view_manager.active == 1

    tabs = window.view_tabbar.tabBar()
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, tabs.tabRect(0).center())
    _drain(qapp)

    assert window.view_manager.active == 0
    assert _checked_pairs(window) == [(fid, "speed")]

    QTest.mouseClick(window.toolbar.btn_mode_fft, Qt.LeftButton)
    _drain(qapp)
    assert window.chart_stack.current_mode() == "fft"

    QTest.mouseClick(window.toolbar.btn_mode_time, Qt.LeftButton)
    _drain(qapp)
    assert window.chart_stack.current_mode() == "time"
    assert window.view_manager.active == 0
    assert _checked_pairs(window) == [(fid, "speed")]
