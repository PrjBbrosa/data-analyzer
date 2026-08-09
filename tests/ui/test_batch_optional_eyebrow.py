"""Batch optional-section eyebrow (Option C soft mid-rule)."""
from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QWidget


def test_optional_eyebrow_exposes_caption(qtbot):
    from mf4_analyzer.ui.drawers.batch.optional_eyebrow import BatchOptionalEyebrow

    brow = BatchOptionalEyebrow("可选 · 导出切片")
    qtbot.addWidget(brow)

    assert brow.objectName() == "BatchOptionalEyebrow"
    assert brow.text() == "可选 · 导出切片"
    labels = [
        w for w in brow.findChildren(QLabel)
        if w.objectName() == "BatchOptionalEyebrowLabel"
    ]
    assert len(labels) == 1
    rules = [
        w for w in brow.findChildren(QWidget)
        if w.objectName() == "BatchOptionalEyebrowRule"
    ]
    assert len(rules) == 2

    brow.setText("可选 · 预处理")
    assert brow.text() == "可选 · 预处理"


def test_addon_panels_carry_unified_optional_eyebrows(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel
    from mf4_analyzer.ui.drawers.batch.chart_statistics_panel import ChartStatisticsPanel
    from mf4_analyzer.ui.drawers.batch.filter_panel import BatchFilterPanel
    from mf4_analyzer.ui.drawers.batch.optional_eyebrow import BatchOptionalEyebrow
    from mf4_analyzer.ui.drawers.batch.slice_panel import SlicePanel

    slice_panel = SlicePanel()
    stats = ChartStatisticsPanel()
    filt = BatchFilterPanel()
    analysis = AnalysisPanel()
    for widget in (slice_panel, stats, filt, analysis):
        qtbot.addWidget(widget)

    assert slice_panel._eyebrow.text() == "可选 · 导出切片"
    assert stats._eyebrow.text() == "可选 · 图内统计"
    assert filt._eyebrow.text() == "可选 · 预处理"
    assert analysis._frf_grouping_eyebrow.text() == "可选 · 图表组织"
    assert analysis._source_interval_eyebrow.text() == "可选 · 分析区间"

    analysis.show()
    qtbot.waitExposed(analysis)

    analysis._method_group.set_method("fft_time")
    assert analysis._slice.isVisibleTo(analysis)
    assert analysis._slice._eyebrow.isVisibleTo(analysis)
    assert isinstance(analysis._slice._eyebrow, BatchOptionalEyebrow)

    analysis._method_group.set_method("time")
    assert analysis._chart_statistics.isVisibleTo(analysis)
    assert analysis._chart_statistics._eyebrow.isVisibleTo(analysis)

    analysis._method_group.set_method("frf")
    assert analysis._frf_grouping_host.isVisibleTo(analysis)
    assert analysis._frf_grouping_eyebrow.isVisibleTo(analysis)

    analysis._method_group.set_method("fft")
    assert analysis._source_interval_host.isVisibleTo(analysis)
    assert analysis._source_interval_eyebrow.isVisibleTo(analysis)
