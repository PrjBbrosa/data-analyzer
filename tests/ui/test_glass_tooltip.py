import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit.dialog_geometry import IntRect, SCREEN_MARGIN, as_rect
from mf4_analyzer.ui_kit.glass_tooltip import (
    _GlassTooltipPopup,
    _TooltipEventFilter,
)


def _discard_popup():
    popup = _GlassTooltipPopup._instance
    if popup is not None and not sip.isdeleted(popup):
        sip.delete(popup)
    _GlassTooltipPopup._instance = None


@pytest.fixture(autouse=True)
def clean_popup_singleton():
    _discard_popup()
    yield
    _discard_popup()


def test_popup_singleton_recreates_deleted_qt_object(qapp):
    popup = _GlassTooltipPopup.instance()
    sip.delete(popup)

    assert _GlassTooltipPopup._instance is None

    replacement = _GlassTooltipPopup.instance()

    assert replacement is not popup
    assert not sip.isdeleted(replacement)


def test_hide_event_ignores_deleted_popup_without_recreating(qapp):
    popup = _GlassTooltipPopup.instance()
    sip.delete(popup)

    event_filter = _TooltipEventFilter()
    watched = QWidget()

    assert event_filter.eventFilter(watched, QEvent(QEvent.Hide)) is False
    assert _GlassTooltipPopup._instance is None


def test_long_tooltip_stays_inside_injected_work_area(qapp, qtbot, monkeypatch):
    available = IntRect(0, 0, 800, 600)
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: available,
    )
    popup = _GlassTooltipPopup.instance()
    qtbot.addWidget(popup)
    text = "C:/" + ("很长路径段" * 24) + "/file.mf4"
    popup.show_for(text, QPoint(760, 560))
    qapp.processEvents()
    frame = as_rect(popup.frameGeometry())
    safe = available.adjusted(
        SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
    )
    assert safe.contains_rect(frame)
    assert popup._label.text()
