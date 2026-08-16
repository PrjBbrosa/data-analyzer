"""The isolated Titanium Amber visual contract for UltraView.

UltraView has a deliberately richer surface hierarchy than the rest of the
Analyzer, so these values do not belong in :mod:`control_style`.  This is the
single source for both QSS placeholders and QPainter consumers; it prevents
the canvas and its floating chrome drifting into two near-identical palettes.
"""
from __future__ import annotations

from types import MappingProxyType


ULTRAVIEW_TITANIUM = MappingProxyType(
    {
        "canvas": "#F7F8F7",
        "canvas_deep": "#E9EFF1",
        "canvas_dot": "rgba(44, 82, 93, 43)",
        "canvas_line": "rgba(38, 74, 86, 26)",
        "glow_teal": "rgba(31, 104, 128, 41)",
        "glow_amber": "rgba(238, 151, 58, 33)",
        "glow_copper": "rgba(197, 76, 64, 20)",
        "surface": "rgba(255, 255, 254, 232)",
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
        "amber": "#E58F32",
        # A bright, mid-tone active rail avoids a near-black capsule while
        # preserving a white glyph at small (18 px) icon sizes.
        "rail_active_start": "#3C8495",
        "rail_active_end": "#F0A44C",
        "rail_active_hover": "#2F7181",
        "copper": "#BE594C",
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
    }
)


ULTRAVIEW_QSS_TOKENS = MappingProxyType(
    {
        "UV_CANVAS": ULTRAVIEW_TITANIUM["canvas"],
        "UV_CANVAS_DEEP": ULTRAVIEW_TITANIUM["canvas_deep"],
        "UV_SURFACE": ULTRAVIEW_TITANIUM["surface"],
        "UV_SURFACE_SOLID": ULTRAVIEW_TITANIUM["surface_solid"],
        "UV_SURFACE_SOFT": ULTRAVIEW_TITANIUM["surface_soft"],
        "UV_SURFACE_TINT": ULTRAVIEW_TITANIUM["surface_tint"],
        "UV_INK": ULTRAVIEW_TITANIUM["ink"],
        "UV_MUTED": ULTRAVIEW_TITANIUM["muted"],
        "UV_QUIET": ULTRAVIEW_TITANIUM["quiet"],
        "UV_LINE": ULTRAVIEW_TITANIUM["line"],
        "UV_LINE_STRONG": ULTRAVIEW_TITANIUM["line_strong"],
        "UV_BRAND": ULTRAVIEW_TITANIUM["brand"],
        "UV_BRAND_DEEP": ULTRAVIEW_TITANIUM["brand_deep"],
        "UV_AMBER": ULTRAVIEW_TITANIUM["amber"],
        "UV_RAIL_ACTIVE_START": ULTRAVIEW_TITANIUM["rail_active_start"],
        "UV_RAIL_ACTIVE_END": ULTRAVIEW_TITANIUM["rail_active_end"],
        "UV_RAIL_ACTIVE_HOVER": ULTRAVIEW_TITANIUM["rail_active_hover"],
        "UV_COPPER": ULTRAVIEW_TITANIUM["copper"],
        "UV_SUCCESS": ULTRAVIEW_TITANIUM["success"],
        "UV_WARNING": ULTRAVIEW_TITANIUM["warning"],
        "UV_DANGER": ULTRAVIEW_TITANIUM["danger"],
        "UV_DANGER_WASH": ULTRAVIEW_TITANIUM["danger_wash"],
        "UV_TIME": ULTRAVIEW_TITANIUM["time"],
        "UV_TIME_WASH": ULTRAVIEW_TITANIUM["time_wash"],
        "UV_TIME_LINE": ULTRAVIEW_TITANIUM["time_line"],
        "UV_FFT": ULTRAVIEW_TITANIUM["fft"],
        "UV_FFT_WASH": ULTRAVIEW_TITANIUM["fft_wash"],
        "UV_FFT_LINE": ULTRAVIEW_TITANIUM["fft_line"],
        "UV_FFT_TIME": ULTRAVIEW_TITANIUM["fft_time"],
        "UV_FFT_TIME_WASH": ULTRAVIEW_TITANIUM["fft_time_wash"],
        "UV_FFT_TIME_LINE": ULTRAVIEW_TITANIUM["fft_time_line"],
        "UV_FRF": ULTRAVIEW_TITANIUM["frf"],
        "UV_FRF_WASH": ULTRAVIEW_TITANIUM["frf_wash"],
        "UV_FRF_LINE": ULTRAVIEW_TITANIUM["frf_line"],
        "UV_ORDER": ULTRAVIEW_TITANIUM["order"],
        "UV_ORDER_WASH": ULTRAVIEW_TITANIUM["order_wash"],
        "UV_ORDER_LINE": ULTRAVIEW_TITANIUM["order_line"],
    }
)


def titanium_color(role: str) -> str:
    """Return one named UltraView paint/QSS color, failing loudly if mistyped."""
    return ULTRAVIEW_TITANIUM[str(role)]


__all__ = ["ULTRAVIEW_QSS_TOKENS", "ULTRAVIEW_TITANIUM", "titanium_color"]
