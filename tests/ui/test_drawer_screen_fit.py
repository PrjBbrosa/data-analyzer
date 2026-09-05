"""Outer drawer/sheet owns screen fit; inner content can shrink."""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
from mf4_analyzer.ui.drawers.export_sheet import ExportSheet
from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN


def test_export_sheet_fits_compact_work_area(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    host = QWidget()
    host.setGeometry(0, 0, 800, 600)
    qtbot.addWidget(host)
    sheet = ExportSheet(host, ["rpm"])
    qtbot.addWidget(sheet)
    sheet.show()
    qtbot.waitExposed(sheet)
    assert sheet.width() <= 640 - 2 * SCREEN_MARGIN
    assert sheet.height() <= 360 - 2 * SCREEN_MARGIN
    fg = sheet.frameGeometry()
    assert fg.left() >= SCREEN_MARGIN
    assert fg.top() >= SCREEN_MARGIN


def test_channel_editor_drawer_does_not_use_520_floor_off_screen(
    qapp, qtbot, monkeypatch,
):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    host = QWidget()
    host.resize(400, 300)
    qtbot.addWidget(host)
    drawer = ChannelEditorDrawer(host, {}, None)
    qtbot.addWidget(drawer)
    drawer.show()
    qtbot.waitExposed(drawer)
    assert drawer.height() <= 360 - 2 * SCREEN_MARGIN
    assert drawer.width() <= 640 - 2 * SCREEN_MARGIN
