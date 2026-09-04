from PyQt5.QtWidgets import QLabel

from mf4_analyzer.ui.chart_stack.cards import TimeChartCard
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG


def test_set_time_axis_provenance_shows_and_hides(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    card = TimeChartCard(canvas)
    qtbot.addWidget(card)

    chip = card._time_axis_chip
    assert isinstance(chip, QLabel)
    assert chip.objectName() == "timeAxisProvenanceChip"
    assert chip.isHidden()

    card.set_time_axis_provenance("已重采样 Fs≈500 Hz", "原 Fs≈480 Hz")
    assert not chip.isHidden()
    assert chip.text() == "已重采样 Fs≈500 Hz"
    assert "480" in chip.toolTip()

    card.set_time_axis_provenance(None)
    assert chip.isHidden()
    assert chip.text() == ""
