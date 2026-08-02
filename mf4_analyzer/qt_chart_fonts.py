"""Qt chart font resolution shared by foreground and batch renderers.

This module intentionally sits outside :mod:`mf4_analyzer.ui`: the batch
renderer may construct pyqtgraph scenes, but importing it must not construct
or import the application's main-window graph.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QFontInfo, QFontMetrics, QImage, QPainter,
    QRawFont,
)
from PyQt5.QtWidgets import QApplication


CHART_FONT_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
)
CJK_CONTRACT_TEXT = "单帧振动加速度"
CJK_FONT_CANDIDATES = CHART_FONT_FAMILIES
# Keyed by the exact requested size: the batch report's font scale produces
# fractional point sizes, and truncating the key would hand 12.6pt callers a
# cached 12.0pt font.
_CHART_FONT_CACHE: dict[float, QFont] = {}


def supports_contract_text(font: QFont, text: str = CJK_CONTRACT_TEXT) -> bool:
    raw = QRawFont.fromFont(font)
    if raw.isValid():
        return all(bool(raw.supportsCharacter(character)) for character in text)
    metrics = QFontMetrics(font)
    return all(bool(metrics.inFontUcs4(ord(character))) for character in text)


@lru_cache(maxsize=1)
def resolve_cjk_font() -> QFont | None:
    """Return the first chart family covering the CJK rendering contract."""
    try:
        installed = set(QFontDatabase().families())
    except Exception:
        installed = set()
    for family in CHART_FONT_FAMILIES:
        if installed and family not in installed:
            continue
        font = QFont(family, 12)
        if supports_contract_text(font):
            return font
    return None


def chart_font(point_size: float = 9.0) -> QFont:
    """Return the resolved explicit font for pyqtgraph text and axis items."""
    cache_key = round(float(point_size), 2)
    cached = _CHART_FONT_CACHE.get(cache_key)
    if cached is not None:
        return QFont(cached)
    try:
        families = set(QFontDatabase().families())
    except Exception:
        families = set()
    for family in CHART_FONT_FAMILIES:
        font = QFont(family, int(point_size))
        font.setPointSizeF(float(point_size))
        if family in families:
            _CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
        if families:
            continue
        try:
            info = QFontInfo(font)
            if info.exactMatch() or info.family() in CHART_FONT_FAMILIES:
                _CHART_FONT_CACHE[cache_key] = QFont(font)
                return font
        except Exception:
            _CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
    app = QApplication.instance()
    font = QFont(app.font() if app is not None else QFont())
    font.setPointSizeF(float(point_size))
    _CHART_FONT_CACHE[cache_key] = QFont(font)
    return font


def apply_axis_font(axis, point_size: float = 9.0) -> None:
    if axis is None:
        return
    font = chart_font(point_size)
    axis.setStyle(tickFont=font)
    label = getattr(axis, "label", None)
    if label is not None:
        label.setFont(font)


def apply_text_item_font(item, point_size: float = 9.0) -> None:
    if item is None:
        return
    target = getattr(item, "textItem", item)
    target.setFont(chart_font(point_size))


def _ink_pixels(image: QImage, background: QColor) -> int:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4,
    )
    reference = np.array(
        [background.red(), background.green(), background.blue(), background.alpha()],
        dtype=np.uint8,
    )
    return int(np.count_nonzero(np.any(pixels != reference, axis=2)))


def _render_header(font: QFont, text: str) -> QImage:
    image = QImage(640, 72, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    painter.setPen(QColor("#273449"))
    painter.setFont(font)
    painter.drawText(QRect(12, 4, 616, 60), Qt.AlignLeft | Qt.AlignVCenter, text)
    painter.end()
    return image


def header_ink_proof(font: QFont, text: str = CJK_CONTRACT_TEXT) -> dict[str, object]:
    background = QColor("#ffffff")
    rendered = _render_header(font, text)
    empty = _render_header(font, "")
    ink_pixels = _ink_pixels(rendered, background)
    empty_ink_pixels = _ink_pixels(empty, background)
    return {
        "font": font.family(),
        "supports": supports_contract_text(font, text),
        "ink_pixels": ink_pixels,
        "empty_ink_pixels": empty_ink_pixels,
        "pass": bool(
            supports_contract_text(font, text)
            and ink_pixels > empty_ink_pixels + 120
        ),
    }


__all__ = [
    "CHART_FONT_FAMILIES",
    "CJK_CONTRACT_TEXT",
    "CJK_FONT_CANDIDATES",
    "apply_axis_font",
    "apply_text_item_font",
    "chart_font",
    "header_ink_proof",
    "resolve_cjk_font",
    "supports_contract_text",
]
