"""Precision-Light-derived visual tokens for batch report rendering."""
from __future__ import annotations

from dataclasses import dataclass, replace

from PyQt5.QtGui import QColor, QFont

from mf4_analyzer._palette import FILE_PALETTES


SERIES_COLORS = FILE_PALETTES[0]
# Fixed-pixel exports map theme point sizes onto this CSS reference, not the
# user's screen scale and not the PNG ``dpi`` metadata written after paint.
EXPORT_FONT_DPI = 96.0


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
    # Report pages are exported at 1920×1080 and up, where the 9pt screen-chart
    # scale reads as a few pixels of ink. These are the 100% baseline; the
    # recipe's ``font_scale`` multiplies them (see ``scaled_fonts``).
    axis_font_pt: float = 12.0
    panel_title_font_pt: float = 13.0
    header_font_pt: float = 15.0
    # Channel / analysis row under the identity header (was a bare 9.0 that
    # ignored ``font_scale`` — C1).
    channel_font_pt: float = 9.0
    facts_font_pt: float = 11.0
    footer_font_pt: float = 9.5


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


def scaled_fonts(theme: RenderTheme, scale: float) -> RenderTheme:
    """Return *theme* with every text size multiplied by *scale*."""
    factor = float(scale)
    if factor == 1.0:
        return theme
    return replace(
        theme,
        axis_font_pt=theme.axis_font_pt * factor,
        panel_title_font_pt=theme.panel_title_font_pt * factor,
        header_font_pt=theme.header_font_pt * factor,
        channel_font_pt=theme.channel_font_pt * factor,
        facts_font_pt=theme.facts_font_pt * factor,
        footer_font_pt=theme.footer_font_pt * factor,
    )


def logical_export_dpi() -> float:
    """Logical DPI of the current paint device; 96 when no screen exists."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return EXPORT_FONT_DPI
    screen = app.primaryScreen()
    if screen is None:
        return EXPORT_FONT_DPI
    dpi = float(screen.logicalDotsPerInchX())
    return dpi if dpi > 0.0 else EXPORT_FONT_DPI


def export_pt_to_px(point_size: float) -> float:
    """Convert a theme point size to CSS pixels at :data:`EXPORT_FONT_DPI`."""
    return float(point_size) * EXPORT_FONT_DPI / 72.0


def export_font_px(point_size: float) -> int:
    """Integer device pixels a theme point size occupies at the 96 DPI reference."""
    return max(1, int(round(export_pt_to_px(point_size))))


def export_reference_pt(point_size: float) -> float:
    """Point size that paints *point_size* at 96 DPI on this device.

    AxisItem records ticks at paint time, so the face stays a point size
    (SSAA scales it). Hosts already near 96 CSS-DPI keep the theme size
    verbatim; 144/192 logical DPI is scaled onto the 96 reference.
    """
    dpi = logical_export_dpi()
    if abs(dpi - EXPORT_FONT_DPI) <= 8.0:
        return float(point_size)
    return float(point_size) * EXPORT_FONT_DPI / dpi


def export_css_px(point_size: float) -> str:
    """Rich-text size matching :func:`export_chart_font` on this device."""
    return f"{export_reference_pt(point_size):.4f}pt"


def export_font_device_px(font: QFont) -> float:
    """Device pixels *font* occupies on the current logical DPI."""
    pixel_size = int(font.pixelSize())
    if pixel_size > 0:
        return float(pixel_size)
    point_size = float(font.pointSizeF())
    if point_size <= 0:
        return 0.0
    return point_size * logical_export_dpi() / 72.0


def _base_export_font() -> QFont:
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.qt_chart_fonts import resolve_cjk_font

    resolved = resolve_cjk_font()
    if resolved is not None:
        return QFont(resolved)
    app = QApplication.instance()
    return QFont(app.font() if app is not None else QFont())


def export_chart_font_pt(reference_pt: float) -> QFont:
    """CJK chart face at an already-compensated point size."""
    font = _base_export_font()
    font.setPointSizeF(max(0.1, float(reference_pt)))
    return font


def export_chart_font(point_size: float) -> QFont:
    """Theme point size rendered at the 96 DPI export reference."""
    return export_chart_font_pt(export_reference_pt(point_size))


def apply_export_axis_font(axis, point_size: float) -> None:
    """Pin tick and axis-title faces to the export pixel scale."""
    if axis is None:
        return
    font = export_chart_font(point_size)
    axis.setStyle(tickFont=font)
    label = getattr(axis, "label", None)
    if label is not None:
        label.setFont(font)


__all__ = [
    "EXPORT_FONT_DPI",
    "RenderTheme",
    "SERIES_COLORS",
    "THEMES",
    "apply_export_axis_font",
    "export_chart_font",
    "export_chart_font_pt",
    "export_css_px",
    "export_font_device_px",
    "export_font_px",
    "export_pt_to_px",
    "export_reference_pt",
    "logical_export_dpi",
    "render_theme",
    "scaled_fonts",
]
