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


def _logical_image(widget):
    image = widget.grab().toImage()
    # Widget geometry is logical; Retina grabs contain device pixels.
    if image.devicePixelRatio() != 1.0:
        image = image.scaled(widget.size())
    return image


def _button_image(button):
    return _logical_image(button.parentWidget()).copy(button.geometry())


def test_method_row_has_one_continuous_surface(header):
    row = header._method_row
    image = _logical_image(row)
    surface = image.pixelColor(8, 8)
    assert surface == QColor("#e3efff")
    assert image.pixelColor(1, 8) == QColor("#1769dd")
    for child in (header._method_caption, header._method_tabs_host):
        # The step badge is now blue; sample the transparent gap beside it.
        x = header._method_step_number.width() + 4 if child is header._method_caption else 1
        point = child.mapTo(row, QPoint(x, 1))
        assert image.pixelColor(point) == surface


def test_method_accent_persists_after_selection(header, qtbot):
    group = header._analysis_panel._method_group
    group._buttons["order_time"].click()
    header._footer_status.setFocus()
    qtbot.waitUntil(lambda: header._method_row.property("guidance") == "engaged")
    assert header._method_row.height() == 40
    assert _logical_image(header._method_row).pixelColor(8, 8) == QColor("#e3efff")
    active = group._buttons["order_time"]
    qtbot.waitUntil(lambda: group._selection_pill.geometry() == active.geometry())
    painted = _button_image(active)
    # Match the single-file toolbar: a light vertical gradient and blue ink.
    top = painted.pixelColor(6, 5)
    bottom = painted.pixelColor(6, active.height() - 5)
    assert top.lightness() > bottom.lightness()
    assert bottom.blue() > bottom.red()
    assert _logical_image(header._method_row).pixelColor(20, 0) == QColor("#cbd5e1")


def test_method_selection_and_keyboard_focus_have_visible_feedback(header, qtbot):
    group = header._analysis_panel._method_group
    active = group._buttons["time"]
    inactive = group._buttons["fft"]
    # Sample away from glyphs and the underline: selection has its own surface.
    assert _button_image(active).pixelColor(6, 10) != _button_image(inactive).pixelColor(6, 10)
    inactive.setFocus(Qt.TabFocusReason)
    qtbot.wait(10)
    focused = _button_image(inactive)
    assert focused.pixelColor(inactive.width() // 2, 0) != focused.pixelColor(6, 10)


def test_pipeline_stages_have_distinct_accents_on_neutral_surface(header):
    assert header.strip.height() == 40
    for card, badge, ink in zip(
        header.strip.cards,
        ("#64748b", "#009b78", "#ed8500"),
        ("#475569", "#007d65", "#ad5c00"),
    ):
        assert _logical_image(card.number_label).pixelColor(3, 10) == QColor(badge)
        assert card.title_label.palette().color(card.title_label.foregroundRole()) == QColor(ink)
        point = card.title_label.mapTo(header.strip, QPoint(0, 0))
        assert _logical_image(header.strip).pixelColor(point) == QColor("#f5f7fa")
        assert card.summary_label.palette().color(card.summary_label.foregroundRole()) == QColor("#64748b")


def test_selected_method_still_responds_visually_when_pressed(header, qtbot):
    active = header._analysis_panel._method_group._buttons["time"]
    qtbot.mouseMove(active, active.rect().center())
    qtbot.wait(20)
    hover_color = _button_image(active).pixelColor(6, 10)
    try:
        qtbot.mousePress(active, Qt.LeftButton, pos=active.rect().center())
        assert _button_image(active).pixelColor(6, 10) != hover_color
    finally:
        qtbot.mouseRelease(active, Qt.LeftButton, pos=active.rect().center())
