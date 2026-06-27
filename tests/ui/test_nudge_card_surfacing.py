"""End-to-end: a hot data situation drives the footer's discovery slot to the
matching nudge, through the real chart card (canvas → HintState → footer)."""
import numpy as np
from PyQt5.QtCore import QCoreApplication, QSettings

from mf4_analyzer.ui import hints
from mf4_analyzer.ui.chart_stack.cards import TimeChartCard, _ChartCard
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


def _fresh(tmp_path, name):
    # Fresh QSettings so a persisted `discovered` set from another run can't
    # retire the nudge under test.
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


def _overlay_rows(n, unit="rpm"):
    t = np.linspace(0.0, 10.0, 4000)
    return [
        (f"ch{i}", True, t, np.sin(t * (i + 1)), "#1769e0", unit, f"fid-{i}")
        for i in range(n)
    ]


def test_crowded_same_unit_overlay_surfaces_coaxis_nudge(qapp, qtbot, tmp_path):
    canvas = TimeDomainCanvasPG()
    card = TimeChartCard(canvas)
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh(tmp_path, "h1.ini"))
    card.set_plot_mode("overlay")

    canvas.plot_channels(_overlay_rows(4), mode="overlay")
    QCoreApplication.processEvents()

    nudge = hints.nudge_hint(card._hint_state())
    assert nudge is not None and nudge.id == "nudge.coaxis"
    assert "共轴" in card._hint_discovery.text()


def test_calm_overlay_shows_no_nudge(qapp, qtbot, tmp_path):
    canvas = TimeDomainCanvasPG()
    card = TimeChartCard(canvas)
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh(tmp_path, "h2.ini"))
    card.set_plot_mode("overlay")

    canvas.plot_channels(_overlay_rows(2), mode="overlay")
    QCoreApplication.processEvents()

    assert hints.nudge_hint(card._hint_state()) is None


def test_dead_colour_window_surfaces_reset_nudge(qapp, qtbot, tmp_path):
    canvas = PgHeatmapCanvas(with_slice=True)
    card = _ChartCard(canvas, chart_mode="fft_time")
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh(tmp_path, "h3.ini"))

    m = np.linspace(-60.0, 0.0, 400).reshape(20, 20)
    canvas.plot_or_update_heatmap(m, (0.0, 1.0), (0.0, 1.0), z_auto=True)
    QCoreApplication.processEvents()
    healthy = hints.nudge_hint(card._hint_state())
    assert healthy is None or healthy.id != "nudge.colorbar_dead"

    # Shove the colour window off the data → dead → the reset nudge fires.
    canvas._img.setLevels((50.0, 60.0))
    canvas.levels_rebased.emit()  # render/inspector rebase → footer refresh
    QCoreApplication.processEvents()

    nudge = hints.nudge_hint(card._hint_state())
    assert nudge is not None and nudge.id == "nudge.colorbar_dead"
    assert "双击" in card._hint_discovery.text()
