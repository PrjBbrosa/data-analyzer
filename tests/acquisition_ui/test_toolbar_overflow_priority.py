"""Narrow-width layout contracts for the Acquisition Cockpit."""

from PyQt5.QtWidgets import QApplication, QSplitter

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def test_mode_segment_demoted_last_at_960(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(960, 600)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()
    window._recompute_toolbar_overflow()
    demoted = {
        widget.objectName(): bool(widget.property("cockpitOverflowHidden"))
        for widget, _action in window._toolbar_overflow_items
    }
    if any(demoted.values()):
        assert demoted["cockpitTransportStatusChip"] or not demoted[
            "cockpitModeSegment"
        ]
        assert not demoted["cockpitModeSegment"]
    window.close()


def test_center_minimum_width_at_960(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(960, 600)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()
    assert window._center.width() >= 300
    window.close()


def test_side_panels_can_be_drag_collapsed_like_analyzer(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 760)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()

    splitter = window.findChild(QSplitter, "cockpitSplitter")
    assert splitter is not None
    # B-4: two-column body — left navigator + center workspace. The right
    # health pane was relocated to the top strip / bottom facts, so only the
    # left navigator is drag-collapsible around a fixed center.
    assert splitter.count() == 2
    assert splitter.isCollapsible(0) is True
    assert splitter.isCollapsible(1) is False

    splitter.setSizes([0, 900])
    QApplication.processEvents()
    sizes = splitter.sizes()

    assert sizes[0] == 0
    assert sizes[1] >= 900
    window.close()
