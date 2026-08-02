"""Compatibility façade for chart fonts now owned by a UI-neutral module."""
from __future__ import annotations

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.qt_chart_fonts import (
    CHART_FONT_FAMILIES,
    _CHART_FONT_CACHE,
    apply_axis_font,
    apply_text_item_font,
    chart_font,
)


_PG_CHART_FONT_FAMILIES = CHART_FONT_FAMILIES
_PG_CHART_FONT_CACHE = _CHART_FONT_CACHE
_pg_chart_font = chart_font
_apply_pg_axis_font = apply_axis_font
_apply_pg_text_item_font = apply_text_item_font


def apply_global_chart_font(app=None):
    """Set the application default family without changing widget metrics."""
    app = app or QApplication.instance()
    if app is None:
        return
    family = chart_font().family()
    base = app.font()
    if base.family() != family:
        base.setFamily(family)
        app.setFont(base)


__all__ = [
    "_PG_CHART_FONT_FAMILIES",
    "_pg_chart_font",
    "_apply_pg_axis_font",
    "_apply_pg_text_item_font",
    "apply_global_chart_font",
]
