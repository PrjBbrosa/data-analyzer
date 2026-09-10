"""Batch content must reach its final geometry before the first frame."""
import pytest
from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtWidgets import QSizePolicy, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.dialog_geometry import SCREEN_MARGIN


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


def test_batch_sheet_keeps_1080x760_when_available_screen_is_large(
    qapp, qtbot, monkeypatch,
):
    """1080×760 is the product target only when the work area can hold it.

    Offscreen Qt often reports an 800×600 available screen; production
    ``fit_window`` then clamps to ~780. That clamp is the screen-protection
    contract, not a reason to shrink production type or drop the 1080 target.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui_kit import dialog_geometry

    monkeypatch.setattr(
        dialog_geometry, "resolve_available_rect",
        lambda **kwargs: dialog_geometry.IntRect(0, 0, 1920, 1080),
    )
    old = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.resize(1080, 760)
        sheet.show()
        qtbot.wait(20)
        assert sheet.width() == 1080
        assert sheet.height() <= 760
        assert sheet._footer_host.height() == 50
        assert sheet._footer_progress.isVisible()
        assert sheet._btn_run.isVisible()
    finally:
        sheet.close()
        qapp.setStyleSheet(old)


def test_batch_sheet_clamps_below_1080_on_small_available_screen(
    qapp, qtbot, monkeypatch,
):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui_kit import dialog_geometry

    monkeypatch.setattr(
        dialog_geometry, "resolve_available_rect",
        lambda **kwargs: dialog_geometry.IntRect(0, 0, 800, 600),
    )
    old = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.resize(1080, 760)
        sheet.show()
        qtbot.wait(20)
        assert sheet.width() < 1080
        assert sheet.width() <= 800 - 2 * SCREEN_MARGIN
        run_bottom = sheet._btn_run.mapTo(sheet, QPoint(0, 0)).y() + sheet._btn_run.height()
        assert run_bottom <= sheet.height()
        assert sheet._btn_run.isVisible()
        assert sheet._footer_host.isVisible()
    finally:
        sheet.close()
        qapp.setStyleSheet(old)


def test_batch_sheet_narrow_frf_pair_editor_keeps_field_geometry_on_large_screen(
    qapp, qtbot, monkeypatch,
):
    """FRF pair fields stay usable at the compact 1040-wide target.

    Requires a work area that can actually host 1040×760. A small offscreen
    available rect will clamp the window first; that is covered separately.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui_kit import dialog_geometry

    monkeypatch.setattr(
        dialog_geometry, "resolve_available_rect",
        lambda **kwargs: dialog_geometry.IntRect(0, 0, 1920, 1080),
    )
    old = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.resize(1040, 760)
        sheet.apply_method("frf")
        sheet.show()
        qtbot.wait(20)
        assert sheet.width() == 1040
        stack = sheet._input_panel._target_stack
        assert stack.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
        assert stack.isVisibleTo(sheet)
        assert stack.width() >= 160
        assert sheet._input_panel._frf_pair_editor.width() == stack.width()
    finally:
        sheet.close()
        qapp.setStyleSheet(old)
