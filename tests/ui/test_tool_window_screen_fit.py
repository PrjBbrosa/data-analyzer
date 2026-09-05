"""Tool-window screen fit: Batch/UltraView share geometry without extra Board fits."""
from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QWidget

from mf4_analyzer.ui.drawers.batch._geometry import fit_dialog_to_available_screen
from mf4_analyzer.ui.drawers.ultraview.sheet import UltraViewSheet
from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN


def test_tool_window_helper_caps_to_compact_work_area(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    fit_dialog_to_available_screen(dialog, None, 1080, 760, min_w=640, min_h=480)
    assert dialog.width() <= 640 - 2 * SCREEN_MARGIN
    assert dialog.height() <= 360 - 2 * SCREEN_MARGIN


def test_ultraview_present_fits_board_once(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 1280, 800),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )

    class _Page(QWidget):
        def __init__(self):
            super().__init__()
            self.fits = 0

        def fit_on_open(self):
            self.fits += 1

    page = _Page()
    sheet = UltraViewSheet(None, page)
    qtbot.addWidget(sheet)
    sheet.present()
    qtbot.waitExposed(sheet)
    assert page.fits == 1
    sheet.show()
    qapp.processEvents()
    assert page.fits == 1
