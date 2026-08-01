"""Precision-Light-derived visual tokens for batch report rendering."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtGui import QColor

from mf4_analyzer._palette import FILE_PALETTES


SERIES_COLORS = FILE_PALETTES[0]


@dataclass(frozen=True)
class RenderTheme:
    name: str
    background: QColor
    plot_background: QColor
    text: str
    muted: str
    subtle: str
    axis: str
    grid: str
    legend_background: str
    fft_line: str
    grid_alpha: float = 0.28
    axis_font_pt: float = 9.0
    panel_title_font_pt: float = 10.0
    header_font_pt: float = 12.0
    facts_font_pt: float = 8.5
    footer_font_pt: float = 7.5


THEMES = {
    "white": RenderTheme(
        "white",
        QColor("#ffffff"),
        QColor("#ffffff"),
        "#273449",
        "#64748b",
        "#8a97a8",
        "#9ca3af",
        "#d8e0ea",
        "#ffffff",
        "#1769e0",
    ),
    "transparent": RenderTheme(
        "transparent",
        QColor(0, 0, 0, 0),
        QColor(0, 0, 0, 0),
        "#273449",
        "#64748b",
        "#8a97a8",
        "#9ca3af",
        "#d8e0ea",
        "#ffffff",
        "#1769e0",
    ),
    "dark": RenderTheme(
        "dark",
        QColor("#101418"),
        QColor("#101418"),
        "#f2f5f7",
        "#aeb9c5",
        "#8e9aa7",
        "#6b7785",
        "#708090",
        "#20262d",
        "#f2f5f7",
    ),
}


def render_theme(background: str) -> RenderTheme:
    try:
        return THEMES[str(background)]
    except KeyError as exc:
        raise ValueError(f"unsupported batch render background: {background}") from exc


__all__ = ["RenderTheme", "SERIES_COLORS", "THEMES", "render_theme"]
