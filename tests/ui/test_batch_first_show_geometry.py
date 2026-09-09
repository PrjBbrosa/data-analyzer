"""Batch content must reach its final geometry before the first frame."""
import pytest
from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit import load_stylesheet


@pytest.mark.parametrize('method', ['time', 'fft', 'fft_time', 'order_time', 'frf'])
@pytest.mark.parametrize('width,height', [(1080, 760), (1280, 850), (1080, 480)])
def test_batch_content_settles_before_show_returns(
    qapp, qtbot, monkeypatch, method, width, height,
):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui_kit import dialog_geometry

    monkeypatch.setattr(
        dialog_geometry, 'resolve_available_rect',
        lambda **kwargs: dialog_geometry.IntRect(0, 0, 1920, 1080),
    )
    qapp.setStyle('Fusion')
    load_stylesheet(qapp)
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._analysis_panel.set_method(method)
    sheet.resize(width, height)
    widgets = sheet.findChildren(QWidget)

    def geometry():
        result = {}
        for index, widget in enumerate(widgets):
            if widget.isVisibleTo(sheet):
                pos = widget.mapTo(sheet, QPoint(0, 0))
                result[(index, type(widget).__name__, widget.objectName())] = (
                    pos.x(), pos.y(), widget.width(), widget.height(),
                )
        return result

    for _ in range(2):
        pending = []
        QTimer.singleShot(0, lambda: pending.append(True))
        sheet.show()
        # Settling may deliver layout requests, never unrelated timers/input.
        assert not pending
        initial = geometry()
        qtbot.wait(100)
        settled = geometry()
        changes = {key: (value, settled.get(key)) for key, value in initial.items()
                   if settled.get(key) != value}
        assert not changes
        assert initial.keys() == settled.keys()
        assert sheet.method() == method
        for pane in (sheet._input_scroll, sheet._analysis_scroll, sheet._output_scroll):
            assert pane.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
            bar = pane.verticalScrollBar()
            bar.setValue(bar.maximum())
            assert bar.value() == bar.maximum()
            bar.setValue(0)
        sheet.hide()
