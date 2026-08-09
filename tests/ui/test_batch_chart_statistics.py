from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QAbstractSpinBox, QCheckBox


def test_chart_statistics_panel_round_trips_only_when_enabled(qtbot):
    from mf4_analyzer.ui.drawers.batch.chart_statistics_panel import (
        ChartStatisticsPanel,
    )
    from mf4_analyzer.ui.widgets.pill_switch import PillSwitch

    panel = ChartStatisticsPanel()
    qtbot.addWidget(panel)
    panel.show()

    # Main switch is a PillSwitch (drop-in for the old QCheckBox), matching the
    # 预处理/切片 cards; the in-card multi-select checkboxes stay QCheckBox
    # (chip-styled) and auto_range stays the boolean state owner behind a
    # SegmentedChoice.
    assert isinstance(panel.enabled, PillSwitch)
    assert not isinstance(panel.enabled, QCheckBox)
    assert isinstance(panel.maximum, QCheckBox)
    assert isinstance(panel.minimum, QCheckBox)
    assert isinstance(panel.mean, QCheckBox)
    assert isinstance(panel.auto_range, QCheckBox)
    assert panel.auto_range.isHidden() is True
    assert panel._range_mode_choice.bound_combo() is panel._range_mode_combo
    assert panel._range_mode_choice.isVisibleTo(panel) is False  # settings collapsed

    assert panel.get_params() == {}
    # Off by default -> settings area collapses entirely, same as filter/slice.
    assert panel._settings.isHidden()
    assert panel._summary_note.text() == "统计关闭 · 图上不加标注"

    panel.enabled.setChecked(True)
    assert not panel._settings.isHidden()
    assert panel._range_mode_choice.isVisibleTo(panel) is True
    assert tuple(b.text() for b in panel._range_mode_choice.buttons()) == (
        "自动", "手动",
    )
    assert all(
        check.isVisibleTo(panel)
        for check in (panel.maximum, panel.minimum, panel.mean)
    )
    assert panel._summary_note.text() == "全时段 · 最大/最小/平均"
    assert panel.auto_range.isChecked()
    assert panel._range_mode_combo.currentIndex() == 0
    assert panel.range_summary.text() == "全时段"
    assert panel.range_summary.isVisibleTo(panel)
    assert panel.x_min.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert panel.x_max.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert panel.x_min.property("compact") is True
    assert panel.x_max.property("compact") is True

    # Manual mode: spins expand below the segmented control (same range_row).
    panel.auto_range.setChecked(False)
    assert panel._range_mode_combo.currentIndex() == 1
    assert panel.x_min.isVisibleTo(panel)
    assert panel.x_max.isVisibleTo(panel)
    assert panel.range_row.isAncestorOf(panel.x_min)
    assert panel.range_row.isAncestorOf(panel.x_max)
    assert panel.range_summary.isVisibleTo(panel) is False
    # UI path: clicking the 手动 segment flips the same auto_range owner.
    panel.auto_range.setChecked(True)
    panel._range_mode_choice.buttons()[1].click()
    assert panel.auto_range.isChecked() is False
    assert panel._range_mode_combo.currentIndex() == 1
    panel.x_min.setValue(-12.5)
    panel.x_max.setValue(88.0)
    panel.minimum.setChecked(False)
    assert panel._summary_note.text() == "-12.5–88 · 最大/平均"

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
    assert panel._summary_note.text() == "全时段 · 最小"
    assert panel.get_params() == {
        "chart_statistics": {
            "enabled": True, "range_mode": "full",
            "x_min": None, "x_max": None, "metrics": ["min"],
        },
    }

    panel.enabled.setChecked(False)
    assert panel._settings.isHidden()
    assert panel._summary_note.text() == "统计关闭 · 图上不加标注"


def test_apply_params_without_the_key_disables_but_keeps_the_dialed_in_range(qtbot):
    """A missing `chart_statistics` key must not reset the range to auto.

    Our own normalization pops the key entirely once the card is disabled
    (`enabled: False` never round-trips), so a disable -> re-enable cycle
    used to look like "params has no chart_statistics" and reset
    auto_range/x_min/x_max back to their defaults — silently discarding a
    custom range the user had already filled in (design D-D3).
    """
    from mf4_analyzer.ui.drawers.batch.chart_statistics_panel import (
        ChartStatisticsPanel,
    )

    panel = ChartStatisticsPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.enabled.setChecked(True)
    panel.auto_range.setChecked(False)
    panel.x_min.setValue(-80.0)
    panel.x_max.setValue(80.0)
    panel.minimum.setChecked(False)

    # This is what get_params() emits once the switch goes off: no
    # "chart_statistics" key at all (normalize_batch_params pops it too).
    panel.apply_params({})

    assert panel.enabled.isChecked() is False
    # The values the user typed must survive even though the card reads as
    # disabled now.
    assert panel.auto_range.isChecked() is False
    assert panel.x_min.value() == pytest.approx(-80.0)
    assert panel.x_max.value() == pytest.approx(80.0)
    assert panel.minimum.isChecked() is False

    # Re-enabling without touching anything else must reproduce the exact
    # custom range, not silently fall back to "full".
    panel.enabled.setChecked(True)
    assert panel.get_params() == {
        "chart_statistics": {
            "enabled": True, "range_mode": "custom",
            "x_min": -80.0, "x_max": 80.0, "metrics": ["max", "mean"],
        },
    }


@pytest.mark.parametrize("payload", [
    {},
    {"chart_statistics": {
        "enabled": True,
        "range_mode": "custom",
        "x_min": -5.0,
        "x_max": 15.0,
        "metrics": ["min"],
    }},
])
def test_chart_statistics_apply_params_emits_one_changed_and_forwarded_notification(
    qtbot, payload,
):
    """One programmatic statistics apply is one observable parameter transaction."""
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    changed = QSignalSpy(panel._chart_statistics.changed)
    forwarded = QSignalSpy(panel.paramsChanged)

    panel._chart_statistics.apply_params(payload)

    assert len(changed) == 1
    assert len(forwarded) == 1


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
    assert panel._chart_statistics.context.text() == "rack"
    assert panel._chart_statistics._context_unit.text() == "mm"
    assert panel.get_params()["chart_statistics"]["enabled"] is True

    panel.set_method("fft")
    assert panel._chart_statistics.isHidden()


def _statistics_page(*, width=1920, height=1080):
    """A rendered report page whose only red ink is the maximum marker."""
    from mf4_analyzer.batch_image_options import BatchRenderOptions
    from mf4_analyzer.batch_render_qt import (
        BatchRenderContext,
        BatchSeries,
        BatchTimeFigureSpec,
    )
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.batch_statistics import BatchStatisticRow

    x = np.linspace(0.0, 2.0, 601)
    y = np.sin(2 * np.pi * x)
    peak, trough = int(np.argmax(y)), int(np.argmin(y))
    row = BatchStatisticRow(
        series_key="rack", family_key="rack", label="rack", variant="value",
        panel=0, branch_label="全程", direction="", sample_count=int(x.size),
        x_min=float(x[0]), x_max=float(x[-1]),
        minimum=float(y[trough]), maximum=float(y[peak]),
        mean=float(y.mean()),
        argmin_x=float(x[trough]), argmax_x=float(x[peak]),
    )
    scene = build_batch_scene(
        (
            "time",
            BatchTimeFigureSpec(
                (BatchSeries(x, y, "rack", unit="N", series_key="rack"),),
                statistics=(row,),
            ),
        ),
        params={"chart_statistics": {"metrics": ["max", "min"]}},
        options=BatchRenderOptions(width_px=width, height_px=height),
        context=BatchRenderContext(
            source_display_name="stats.mf4", group="g", channel="rack",
            unit="N", method="time", task_id="stats",
        ),
    )
    return scene, float(x[peak]), float(y[peak])


def _red_extent(image: QImage, centre: QPointF) -> tuple[int, int]:
    """Width and height of the red ink in a window around ``centre``."""
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    data = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4
    )[..., :3].astype(np.int16)
    half = 30
    top = int(round(centre.y())) - half
    left = int(round(centre.x())) - half
    window = data[top:top + 2 * half, left:left + 2 * half]
    red, green, blue = window[..., 0], window[..., 1], window[..., 2]
    # Wide enough to exclude the page background, the grid and the blue curve,
    # loose enough that the answer does not hinge on the antialiased rim: the
    # extent below is identical for every cut between 30 and 90.
    mask = (red > 110) & (red - green > 55) & (red - blue > 55)
    assert mask.any(), "no red marker ink near the maximum"
    rows = np.flatnonzero(np.any(mask, axis=1))
    cols = np.flatnonzero(np.any(mask, axis=0))
    return int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)


def test_max_marker_survives_the_export_downscale_at_report_size(qapp):
    """The marker has to still be readable in the delivered 1920x1080 PNG.

    Markers are pxMode symbols, so ``ScatterPlotItem`` draws them at their
    device-pixel size on the export's 3x scratch canvas and the downscale then
    shrinks them: an 18 px symbol measured ~6 px of ink in the PNG, which is
    what "看不清" meant. Measuring the rendered image rather than ``opts``
    is the point — the old style passed every size assertion while rendering
    at a third of it.
    """
    from mf4_analyzer.batch_render_qt._export import render_scene_image

    scene, peak_x, peak_y = _statistics_page()
    try:
        scene.show_and_settle()
        qapp.processEvents()
        markers = [
            item for item in scene.plots[0].vb.addedItems
            if isinstance(item, pg.ScatterPlotItem)
        ]
        assert len(markers) == 2
        brushes = {marker.opts["brush"].color().name() for marker in markers}
        assert brushes == {"#dc2626", "#16a34a"}, "solid red/green fills"
        assert {marker.opts["pen"].color().name() for marker in markers} == {
            "#ffffff"
        }, "white keyline"

        centre = scene.plots[0].vb.mapViewToScene(QPointF(peak_x, peak_y))
        width, height = _red_extent(render_scene_image(scene), centre)
        assert width >= 10 and height >= 10, (
            f"maximum marker rendered {width}x{height} px"
        )
    finally:
        scene.close()
