from __future__ import annotations

from PyQt5.QtWidgets import QAbstractSpinBox, QFrame


def test_chart_statistics_panel_round_trips_only_when_enabled(qtbot):
    from mf4_analyzer.ui.drawers.batch.chart_statistics_panel import (
        ChartStatisticsPanel,
    )

    panel = ChartStatisticsPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert panel.get_params() == {}
    assert all(
        check.isVisibleTo(panel)
        for check in (panel.maximum, panel.minimum, panel.mean)
    )
    panel.enabled.setChecked(True)
    assert panel._divider.frameShape() == QFrame.HLine
    assert panel._divider.frameShadow() == QFrame.Plain
    assert panel.auto_range.isChecked()
    assert panel.range_summary.text() == "全时段"
    assert panel.x_min.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert panel.x_max.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert panel.x_min.property("compact") is True
    assert panel.x_max.property("compact") is True

    panel.auto_range.setChecked(False)
    assert panel.x_min.isVisibleTo(panel)
    assert panel.x_max.isVisibleTo(panel)
    assert panel.range_row.isAncestorOf(panel.x_min)
    assert panel.range_row.isAncestorOf(panel.x_max)
    panel.x_min.setValue(-12.5)
    panel.x_max.setValue(88.0)
    panel.minimum.setChecked(False)

    assert panel.get_params() == {
        "chart_statistics": {
            "enabled": True, "range_mode": "custom",
            "x_min": -12.5, "x_max": 88.0, "metrics": ["max", "mean"],
        },
    }

    panel.apply_params({"chart_statistics": {
        "enabled": True, "range_mode": "full", "metrics": ["min"],
    }})
    assert panel.auto_range.isChecked()
    assert panel.range_summary.isVisibleTo(panel)
    assert not panel.x_min.isVisibleTo(panel)
    assert panel.get_params() == {
        "chart_statistics": {
            "enabled": True, "range_mode": "full",
            "x_min": None, "x_max": None, "metrics": ["min"],
        },
    }


def test_analysis_panel_shows_statistics_for_time_and_merges_recipe(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_method("time")
    panel._chart_statistics.enabled.setChecked(True)
    panel.set_chart_statistics_x_context(
        x_source="channel", x_channel="rack", unit="mm",
    )

    assert panel._chart_statistics.isVisibleTo(panel)
    assert "rack (mm)" in panel._chart_statistics.context.text()
    assert panel.get_params()["chart_statistics"]["enabled"] is True

    panel.set_method("fft")
    assert panel._chart_statistics.isHidden()
