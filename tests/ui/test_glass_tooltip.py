import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QWidget

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
