"""Font helpers for pyqtgraph axis and text items."""

from __future__ import annotations

from PyQt5.QtGui import QFont, QFontDatabase, QFontInfo
from PyQt5.QtWidgets import QApplication


_PG_CHART_FONT_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
)
_PG_CHART_FONT_CACHE = {}


def _pg_chart_font(point_size=9):
    """Return the explicit font used by pyqtgraph axis/scene text."""
    cache_key = int(point_size)
    cached = _PG_CHART_FONT_CACHE.get(cache_key)
    if cached is not None:
        return QFont(cached)
    try:
        families = set(QFontDatabase().families())
    except Exception:
        families = set()
    for family in _PG_CHART_FONT_FAMILIES:
        font = QFont(family, point_size)
        if family in families:
            _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
        if families:
            continue
        try:
            info = QFontInfo(font)
            resolved = info.family()
            if info.exactMatch() or resolved in _PG_CHART_FONT_FAMILIES:
                _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
                return font
        except Exception:
            _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
    app = QApplication.instance()
    font = QFont(app.font() if app is not None else QFont())
    font.setPointSize(point_size)
    _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
    return font


def _apply_pg_axis_font(axis, point_size=9):
    if axis is None:
        return
    font = _pg_chart_font(point_size)
    try:
        axis.setStyle(tickFont=font)
    except Exception:
        pass
    label = getattr(axis, "label", None)
    if label is not None:
        try:
            label.setFont(font)
        except Exception:
            pass


def _apply_pg_text_item_font(item, point_size=9):
    if item is None:
        return
    font = _pg_chart_font(point_size)
    target = getattr(item, "textItem", item)
    try:
        target.setFont(font)
    except Exception:
        pass


def apply_global_chart_font(app=None):
    """Set the application default font FAMILY to the resolved CJK chart family,
    preserving the existing point size, so pyqtgraph graphics items (TextItem,
    and axes without an explicit tickFont) stop falling back to the platform
    default (SimSun on Windows). Family-only change keeps widget metrics stable.
    """
    app = app or QApplication.instance()
    if app is None:
        return
    family = _pg_chart_font().family()
    base = app.font()
    if base.family() != family:
        base.setFamily(family)
        app.setFont(base)


__all__ = [
    "_pg_chart_font",
    "_apply_pg_axis_font",
    "_apply_pg_text_item_font",
    "apply_global_chart_font",
]
