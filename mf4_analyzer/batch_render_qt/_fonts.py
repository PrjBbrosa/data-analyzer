"""Qt font resolution and CJK glyph/ink proof helpers."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter, QRawFont

from mf4_analyzer.ui.pg_canvas.fonts import _PG_CHART_FONT_FAMILIES


CJK_CONTRACT_TEXT = "单帧振动加速度"
CJK_FONT_CANDIDATES = _PG_CHART_FONT_FAMILIES


def supports_contract_text(font: QFont, text: str = CJK_CONTRACT_TEXT) -> bool:
    raw = QRawFont.fromFont(font)
    if raw.isValid():
        return all(bool(raw.supportsCharacter(character)) for character in text)
    metrics = QFontMetrics(font)
    return all(bool(metrics.inFontUcs4(ord(character))) for character in text)


@lru_cache(maxsize=1)
def resolve_cjk_font() -> QFont | None:
    """Return the first chart-family font covering the contract text."""

    try:
        installed = set(QFontDatabase().families())
    except Exception:
        installed = set()
    for family in CJK_FONT_CANDIDATES:
        if installed and family not in installed:
            continue
        font = QFont(family, 12)
        if supports_contract_text(font):
            return font
    return None


def chart_font(point_size: float = 9.0) -> QFont:
    selected = resolve_cjk_font()
    font = QFont(selected) if selected is not None else QFont()
    font.setPointSizeF(float(point_size))
    return font


def apply_axis_font(axis, point_size: float = 9.0) -> None:
    if axis is None:
        return
    font = chart_font(point_size)
    axis.setStyle(tickFont=font)
    label = getattr(axis, "label", None)
    if label is not None:
        label.setFont(font)


def _ink_pixels(image: QImage, background: QColor) -> int:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4
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
    "CJK_CONTRACT_TEXT",
    "CJK_FONT_CANDIDATES",
    "apply_axis_font",
    "chart_font",
    "header_ink_proof",
    "resolve_cjk_font",
    "supports_contract_text",
]
