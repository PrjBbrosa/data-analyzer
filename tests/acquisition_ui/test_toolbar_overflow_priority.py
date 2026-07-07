"""Narrow-width layout contracts for the Acquisition Cockpit."""

from PyQt5.QtWidgets import QApplication

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
