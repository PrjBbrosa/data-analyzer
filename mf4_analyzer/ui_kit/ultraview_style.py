"""The isolated UltraView visual contract.

UltraView has a deliberately richer surface hierarchy than the rest of the
Analyzer, so these values do not belong in :mod:`control_style`.  This is the
single source for both QSS placeholders and QPainter consumers; it prevents
the canvas and its floating chrome drifting into two near-identical palettes.

Regular selected / current-tool / open-panel chrome uses the blue system.
Amber is reserved for true attention (unplaced, stale, sync, risk). Analysis
category washes stay on their own roles and are not a selected-state.
"""
from __future__ import annotations

from types import MappingProxyType


ULTRAVIEW_PALETTE = MappingProxyType(
    {
        "canvas": "#F7F8F7",
        "canvas_deep": "#E9EFF1",
        "canvas_dot": "rgba(44, 82, 93, 43)",
        "canvas_line": "rgba(38, 74, 86, 26)",
        "glow_teal": "rgba(31, 104, 128, 28)",
        "glow_selected": "rgba(66, 98, 255, 22)",
        "glow_mist": "rgba(36, 105, 124, 18)",
        "surface": "rgba(255, 255, 254, 232)",
        "surface_frost": "rgba(255, 255, 254, 118)",
        "surface_frost_edge": "rgba(255, 255, 255, 166)",
        "surface_solid": "#FFFEFD",
        "surface_soft": "#EDF2F2",
        "surface_tint": "#E9F1F3",
        "ink": "#183039",
        "muted": "#66787E",
        "quiet": "#87969A",
        "line": "rgba(50, 86, 97, 59)",
        "line_strong": "rgba(42, 78, 89, 94)",
        "brand": "#24697C",
        "brand_deep": "#174F5E",
        "selected": "#4262FF",
        "selected_ink": "#314EE8",
        "selected_wash": "#E9EDFF",
        "selected_hover": "#DDE3FF",
        "selected_line": "#BDC9FF",
        "success": "#198565",
        "warning": "#DC861F",
        "danger": "#C94F4A",
        "danger_wash": "#FBEDEC",
        "time": "#3D79EF",
        "time_wash": "#F5F8FF",
        "time_line": "#A6C0F5",
        "fft": "#8B5FD5",
        "fft_wash": "#F8F5FD",
        "fft_line": "#BBA5E3",
        "fft_time": "#00A998",
        "fft_time_wash": "#F2FAF8",
        "fft_time_line": "#8BCDC3",
        "frf": "#E28735",
        "frf_wash": "#FFF9F2",
        "frf_line": "#EFC494",
        "order": "#B75B4D",
        "order_wash": "#FCF6F4",
        "order_line": "#D9ABA3",
        # Safety / collision wall. Not a regular selected-state colour.
        "copper": "#BE594C",
        # Legacy name kept so older call sites and warning-adjacent paint
        # still resolve. Regular chrome must not use this as a selected fill.
        "amber": "#E58F32",
    }
)

# Compatibility alias. New code should use ULTRAVIEW_PALETTE / ultraview_color.
ULTRAVIEW_TITANIUM = ULTRAVIEW_PALETTE


ULTRAVIEW_QSS_TOKENS = MappingProxyType(
    {
        "UV_CANVAS": ULTRAVIEW_PALETTE["canvas"],
        "UV_CANVAS_DEEP": ULTRAVIEW_PALETTE["canvas_deep"],
        "UV_SURFACE": ULTRAVIEW_PALETTE["surface"],
        "UV_FROST": ULTRAVIEW_PALETTE["surface_frost"],
        "UV_FROST_EDGE": ULTRAVIEW_PALETTE["surface_frost_edge"],
        "UV_SURFACE_SOLID": ULTRAVIEW_PALETTE["surface_solid"],
        "UV_SURFACE_SOFT": ULTRAVIEW_PALETTE["surface_soft"],
        "UV_SURFACE_TINT": ULTRAVIEW_PALETTE["surface_tint"],
        "UV_INK": ULTRAVIEW_PALETTE["ink"],
        "UV_MUTED": ULTRAVIEW_PALETTE["muted"],
        "UV_QUIET": ULTRAVIEW_PALETTE["quiet"],
        "UV_LINE": ULTRAVIEW_PALETTE["line"],
        "UV_LINE_STRONG": ULTRAVIEW_PALETTE["line_strong"],
        "UV_BRAND": ULTRAVIEW_PALETTE["brand"],
        "UV_BRAND_DEEP": ULTRAVIEW_PALETTE["brand_deep"],
        "UV_SELECTED": ULTRAVIEW_PALETTE["selected"],
        "UV_SELECTED_INK": ULTRAVIEW_PALETTE["selected_ink"],
        "UV_SELECTED_WASH": ULTRAVIEW_PALETTE["selected_wash"],
        "UV_SELECTED_HOVER": ULTRAVIEW_PALETTE["selected_hover"],
        "UV_SELECTED_LINE": ULTRAVIEW_PALETTE["selected_line"],
        "UV_SUCCESS": ULTRAVIEW_PALETTE["success"],
        "UV_WARNING": ULTRAVIEW_PALETTE["warning"],
        "UV_DANGER": ULTRAVIEW_PALETTE["danger"],
        "UV_DANGER_WASH": ULTRAVIEW_PALETTE["danger_wash"],
        "UV_TIME": ULTRAVIEW_PALETTE["time"],
        "UV_TIME_WASH": ULTRAVIEW_PALETTE["time_wash"],
        "UV_TIME_LINE": ULTRAVIEW_PALETTE["time_line"],
        "UV_FFT": ULTRAVIEW_PALETTE["fft"],
        "UV_FFT_WASH": ULTRAVIEW_PALETTE["fft_wash"],
        "UV_FFT_LINE": ULTRAVIEW_PALETTE["fft_line"],
        "UV_FFT_TIME": ULTRAVIEW_PALETTE["fft_time"],
        "UV_FFT_TIME_WASH": ULTRAVIEW_PALETTE["fft_time_wash"],
        "UV_FFT_TIME_LINE": ULTRAVIEW_PALETTE["fft_time_line"],
        "UV_FRF": ULTRAVIEW_PALETTE["frf"],
        "UV_FRF_WASH": ULTRAVIEW_PALETTE["frf_wash"],
        "UV_FRF_LINE": ULTRAVIEW_PALETTE["frf_line"],
        "UV_ORDER": ULTRAVIEW_PALETTE["order"],
        "UV_ORDER_WASH": ULTRAVIEW_PALETTE["order_wash"],
        "UV_ORDER_LINE": ULTRAVIEW_PALETTE["order_line"],
    }
)


def ultraview_color(role: str) -> str:
    """Return one named UltraView paint/QSS color, failing loudly if mistyped."""
    return ULTRAVIEW_PALETTE[str(role)]


def titanium_color(role: str) -> str:
    """Compatibility alias for :func:`ultraview_color`."""
    return ultraview_color(role)


__all__ = [
    "ULTRAVIEW_PALETTE",
    "ULTRAVIEW_QSS_TOKENS",
    "ULTRAVIEW_TITANIUM",
    "titanium_color",
    "ultraview_color",
]
