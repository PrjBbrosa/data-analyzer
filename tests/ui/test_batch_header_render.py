"""Rendered header surfaces must survive the global QWidget/QPushButton QSS."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor

from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui_kit import load_stylesheet


@pytest.fixture
def header(qapp, qtbot):
    old = qapp.styleSheet()
    load_stylesheet(qapp)
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.show()
    sheet.resize(1080, 760)
    qtbot.wait(30)
    yield sheet
    sheet.close()
    qapp.setStyleSheet(old)


def test_method_row_has_one_continuous_surface(header):
    row = header._method_row
    image = row.grab().toImage()
    surface = image.pixelColor(4, 8)
    for child in (header._method_caption, header._method_tabs_host):
        point = child.mapTo(row, QPoint(1, 1))
        assert image.pixelColor(point) == surface


def test_method_selection_and_keyboard_focus_have_visible_feedback(header, qtbot):
    group = header._analysis_panel._method_group
    active = group._buttons["fft"]
    inactive = group._buttons["time"]
    # Sample away from glyphs and the underline: selection has its own surface.
    assert active.grab().toImage().pixelColor(6, 10) != inactive.grab().toImage().pixelColor(6, 10)
    inactive.setFocus(Qt.TabFocusReason)
    qtbot.wait(10)
    focused = inactive.grab().toImage()
    assert focused.pixelColor(inactive.width() // 2, 0) != focused.pixelColor(6, 10)


def test_pipeline_titles_share_neutral_ink(header):
    titles = [card.title_label for card in header.strip.cards]
    colors = [title.palette().color(title.foregroundRole()) for title in titles]
    assert all(color == QColor("#334155") for color in colors)


def test_selected_method_still_responds_visually_when_pressed(header, qtbot):
    active = header._analysis_panel._method_group._buttons["fft"]
    qtbot.mouseMove(active, active.rect().center())
    qtbot.wait(20)
    hover_color = active.grab().toImage().pixelColor(6, 10)
    try:
        qtbot.mousePress(active, Qt.LeftButton, pos=active.rect().center())
        assert active.grab().toImage().pixelColor(6, 10) != hover_color
    finally:
        qtbot.mouseRelease(active, Qt.LeftButton, pos=active.rect().center())
