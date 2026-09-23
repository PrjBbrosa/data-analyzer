"""Sky-glass style for StartupSplash and QuickRefPanel only.

Import-safe: module import uses stdlib only. PyQt5 and ctypes are imported
lazily inside functions so the splash child closure stays free of numpy /
ui_kit / MainWindow. Not a general theme framework.
"""
from __future__ import annotations

import sys
from typing import Any, Optional, Tuple

# --- Color contract (晴空蓝白) ----------------------------------------------

PANEL_BASE_RGB: Tuple[int, int, int] = (244, 250, 255)  # #f4faff
GLASS_ALPHA: int = 191  # 75% opacity ≈ 191/255
# CSS blur reference; AppKit / Win32 materials control their own blur radius.
FROST_REFERENCE_PX: int = 25
FALLBACK_GLASS_ALPHA: int = 255  # no sharp background ghosts without native blur
INK_HEX = "#223a58"
SECONDARY_HEX = "#576f8c"
ACCENT_HEX = "#1976e9"
TIP_TITLE_HEX = "#2468ac"
TIP_BODY_HEX = "#405e7c"
BORDER_RGBA: Tuple[int, int, int, int] = (255, 255, 255, 201)
GLOW_TR: Tuple[int, int, int, float] = (73, 142, 252, 0.17)
GLOW_BL: Tuple[int, int, int, float] = (24, 193, 229, 0.10)
SPECTRUM_STOP_HEX: Tuple[str, ...] = (
    "#17b6df",
    "#1e85ed",
    "#5773ed",
    "#23bbd0",
)

# Font roles used by both panels. ``body`` covers mixed CJK/ASCII sentences
# (Home / Pn / digits) with one family + Regular weight; emphasis roles opt in
# to Bold explicitly.
FONT_ROLE_TITLE = "title"
FONT_ROLE_EMPHASIS = "emphasis"
FONT_ROLE_BODY = "body"
FONT_ROLE_CAPTION = "caption"
FONT_ROLE_CREDIT = "credit"
FONT_ROLE_WORDMARK = "wordmark"

_CJK_PROBE = "启动面板操作速查"
_ASCII_PROBE = "Home Pn 12"

# Windows 11 22H2+ build that documents DWMWA_SYSTEMBACKDROP_TYPE.
_DWM_BACKDROP_MIN_BUILD = 22621
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_NONE = 1
_DWMSBT_TRANSIENTWINDOW = 3  # Desktop Acrylic — official enum, not FROST_REFERENCE_PX

# Per-widget native surface bookkeeping (never cache QWidget across processes).
_SURFACE_ATTR = "_qt_panel_style_surface"

_font_family_cache: Optional[str] = None


def glass_alpha(*, fallback: bool = False) -> int:
    return FALLBACK_GLASS_ALPHA if fallback else GLASS_ALPHA


def panel_color(name: str):
    """Return a ``QColor`` for a named panel token (lazy PyQt import)."""
    from PyQt5.QtGui import QColor

    table = {
        "base": QColor(*PANEL_BASE_RGB),
        "ink": QColor(INK_HEX),
        "secondary": QColor(SECONDARY_HEX),
        "accent": QColor(ACCENT_HEX),
        "tip_title": QColor(TIP_TITLE_HEX),
        "tip_body": QColor(TIP_BODY_HEX),
        "border": QColor(*BORDER_RGBA),
    }
    if name not in table:
        raise KeyError(f"unknown panel color: {name!r}")
    return table[name]


def glass_fill_color(*, fallback: bool = False):
    """Panel glass fill; opacity only on the fill, not on text/icons."""
    from PyQt5.QtGui import QColor

    r, g, b = PANEL_BASE_RGB
    return QColor(r, g, b, glass_alpha(fallback=fallback))


def glass_fill_css(*, fallback: bool = False) -> str:
    r, g, b = PANEL_BASE_RGB
    alpha = glass_alpha(fallback=fallback)
    return (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 rgba(255, 255, 255, {alpha}), "
        f"stop:1 rgba({r}, {g}, {b}, {alpha}))"
    )


def paint_panel_fill(painter, rect, radius: float, *, fallback: bool):
    """HTML's white-to-ice surface and two elliptical, localized color washes."""
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QLinearGradient, QPainterPath, QRadialGradient

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    alpha = glass_alpha(fallback=fallback)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(255, 255, 255, alpha))
    gradient.setColorAt(1, glass_fill_color(fallback=fallback))
    painter.fillPath(path, gradient)
    painter.save()
    painter.setClipPath(path)
    painter.translate(rect.topLeft())
    painter.scale(rect.width(), rect.height())
    # Normalized coordinates keep these elliptical instead of wide blue disks.
    for which, x, y, extent in (("tr", 1., 0., .68), ("bl", .02, .8, .57)):
        color = glow_color(which)
        wash = QRadialGradient(x, y, extent)
        wash.setColorAt(0, color)
        clear = QColor(color)
        clear.setAlpha(0)
        wash.setColorAt(1, clear)
        painter.fillRect(QRectF(0, 0, 1, 1), wash)
    painter.restore()
    return path


def spectrum_stop_colors():
    from PyQt5.QtGui import QColor

    return tuple(QColor(h) for h in SPECTRUM_STOP_HEX)


def glow_color(which: str):
    from PyQt5.QtGui import QColor

    if which == "tr":
        r, g, b, a = GLOW_TR
    elif which == "bl":
        r, g, b, a = GLOW_BL
    else:
        raise KeyError(which)
    return QColor(r, g, b, max(0, min(255, int(round(a * 255)))))


# --- Font resolution --------------------------------------------------------


def _installed_families() -> set:
    from PyQt5.QtGui import QFontDatabase

    try:
        return set(QFontDatabase().families())
    except (RuntimeError, TypeError, ValueError):
        return set()


def _font_supports_text(font, text: str) -> bool:
    from PyQt5.QtGui import QFontMetrics, QRawFont

    raw = QRawFont.fromFont(font)
    if raw.isValid():
        return all(bool(raw.supportsCharacter(ch)) for ch in text)
    metrics = QFontMetrics(font)
    return all(bool(metrics.inFontUcs4(ord(ch))) for ch in text)


def _candidate_families() -> Tuple[str, ...]:
    if sys.platform == "win32":
        return (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "微软雅黑",
            "Segoe UI",
        )
    if sys.platform == "darwin":
        return (
            "PingFang SC",
            "Hiragino Sans GB",
            "Heiti SC",
            "STHeiti",
            ".AppleSystemUIFont",
            "Helvetica Neue",
        )
    return (
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "Source Han Sans SC",
        "WenQuanYi Micro Hei",
        "DejaVu Sans",
    )


def resolve_panel_font_family() -> str:
    """Pick a real CJK-capable sans for panel body text (process-local cache)."""
    global _font_family_cache
    if _font_family_cache is not None:
        return _font_family_cache

    from PyQt5.QtGui import QFont

    installed = _installed_families()
    for family in _candidate_families():
        if family not in installed and not family.startswith("."):
            # Still try exactMatch families that may not list under the short name.
            probe = QFont(family)
            if not probe.exactMatch() and family not in installed:
                continue
        font = QFont(family)
        font.setStyleHint(font.SansSerif)
        font.setPixelSize(14)
        font.setWeight(QFont.Normal)
        if not _font_supports_text(font, _CJK_PROBE):
            continue
        if not _font_supports_text(font, _ASCII_PROBE):
            continue
        _font_family_cache = family
        return family

    # Last resort: application / system default, still PreferDefault.
    fallback = QFont()
    fallback.setStyleHint(fallback.SansSerif)
    _font_family_cache = fallback.family() or "Sans Serif"
    return _font_family_cache


def reset_panel_font_family_cache() -> None:
    """Test helper: clear the process-local family cache."""
    global _font_family_cache
    _font_family_cache = None


def panel_font(
    role: str,
    *,
    pixel_size: int,
    bold: bool = False,
):
    """Build a panel ``QFont`` for ``role``.

    Pixel sizes are logical pixels; callers must not multiply by DPR again.
    Drawing and measurement must share this same font object/family.
    """
    from PyQt5.QtGui import QFont

    size = max(1, int(pixel_size))
    if role == FONT_ROLE_WORDMARK:
        # Latin wordmark prefers a geometric display face; falls back to panel.
        font = QFont("Trebuchet MS")
        if not font.exactMatch():
            font = QFont(resolve_panel_font_family())
        font.setPixelSize(size)
        font.setBold(True)
        font.setStyleStrategy(QFont.PreferDefault)
        return font

    family = resolve_panel_font_family()
    font = QFont(family)
    font.setStyleHint(font.SansSerif)
    font.setPixelSize(size)
    # Real Regular vs Bold — do not "fix" Chinese by stripping all bold.
    wants_bold = bold or role in {FONT_ROLE_TITLE, FONT_ROLE_EMPHASIS}
    if wants_bold:
        font.setWeight(QFont.Bold)
        font.setBold(True)
    else:
        font.setWeight(QFont.Normal)
        font.setBold(False)
    font.setStyleStrategy(QFont.PreferDefault)
    return font


def panel_font_metrics(role: str, *, pixel_size: int, bold: bool = False):
    from PyQt5.QtGui import QFontMetrics

    return QFontMetrics(panel_font(role, pixel_size=pixel_size, bold=bold))


def panel_font_family_css() -> str:
    """Quoted family name for scoped QSS ``font-family``."""
    family = resolve_panel_font_family()
    escaped = family.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# --- Native surface (Cocoa material / Windows 11 Acrylic) -------------------


class PanelSurfaceState:
    """Observable result of one apply/release attempt."""

    __slots__ = ("applied", "reason", "fallback", "native")

    def __init__(self, *, applied: bool, reason: str = "", fallback: bool = True):
        self.applied = bool(applied)
        self.reason = str(reason or "")
        self.fallback = bool(fallback) if not applied else False
        self.native = None


def _windows_build_number() -> int:
    if sys.platform != "win32":
        return 0
    try:
        info = sys.getwindowsversion()
        return int(getattr(info, "build", 0) or 0)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _windows_high_contrast_enabled(user32) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        class _HIGHCONTRASTW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        hc = _HIGHCONTRASTW()
        hc.cbSize = ctypes.sizeof(_HIGHCONTRASTW)
        # SPI_GETHIGHCONTRAST = 0x0042
        ok = user32.SystemParametersInfoW(0x0042, hc.cbSize, ctypes.byref(hc), 0)
        if not ok:
            return False
        # HCF_HIGHCONTRASTON = 0x0001
        return bool(hc.dwFlags & 0x0001)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _windows_transparency_enabled() -> bool:
    """Read the user transparency preference; never flip it on for the user."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "EnableTransparency")
            return int(value) != 0
        finally:
            winreg.CloseKey(key)
    except (OSError, ValueError, TypeError):
        # Missing key → assume enabled so we still attempt the API; HRESULT
        # failure will degrade with dwm_failed.
        return True


def _widget_hwnd(widget) -> int:
    try:
        handle = int(widget.winId())
    except (RuntimeError, TypeError, ValueError):
        return 0
    return handle if handle else 0


def _set_system_backdrop(hwnd: int, backdrop: int, *, dwmapi=None) -> Tuple[bool, str]:
    """Call DwmSetWindowAttribute; injectable ``dwmapi`` for macOS unit tests."""
    import ctypes

    if dwmapi is None:
        try:
            dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
            from ctypes import wintypes

            # HWND is pointer-sized; ctypes' implicit int truncates it on Win64.
            dwmapi.DwmSetWindowAttribute.argtypes = (
                wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            )
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        except AttributeError:
            return False, "dwm_failed"

    # Use plain c_int + int HWND so injectable fakes work on non-Windows hosts.
    value = ctypes.c_int(int(backdrop))
    try:
        hr = int(
            dwmapi.DwmSetWindowAttribute(
                int(hwnd),
                int(_DWMWA_SYSTEMBACKDROP_TYPE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False, "dwm_failed"
    if hr != 0:
        return False, "dwm_failed"
    return True, ""


def apply_native_panel_surface(
    widget,
    *,
    force: bool = False,
    dwmapi: Any = None,
    platform: Optional[str] = None,
    build_number: Optional[int] = None,
    high_contrast: Optional[bool] = None,
    transparency_enabled: Optional[bool] = None,
    hwnd: Optional[int] = None,
) -> PanelSurfaceState:
    """Apply native Cocoa glass or Windows 11 transient Acrylic when capable.

    Idempotent. On unsupported platforms / capability failure returns a one-shot
    degradation reason and expects callers to paint the opaque fallback.
    Success of this call is NOT visual acceptance of frosted glass.
    """
    plat = platform if platform is not None else sys.platform
    existing = getattr(widget, _SURFACE_ATTR, None)
    if (
        not force
        and isinstance(existing, PanelSurfaceState)
        and existing.applied
        and not existing.fallback
    ):
        return existing

    if plat == "darwin":
        from PyQt5.QtGui import QGuiApplication

        if QGuiApplication.platformName() == "cocoa":
            from .qt_panel_cocoa import CocoaBackdrop

            if isinstance(existing, PanelSurfaceState) and existing.native is not None:
                existing.native.release()
            try:
                native = CocoaBackdrop(widget)
            except OSError:
                # A missing native runtime is a capability failure, not a
                # reason to keep a translucent surface without any blur.
                state = PanelSurfaceState(applied=False, reason="cocoa_unavailable")
                setattr(widget, _SURFACE_ATTR, state)
                return state
            state = PanelSurfaceState(applied=native.applied, reason=native.reason)
            state.native = native
            setattr(widget, _SURFACE_ATTR, state)
            return state

    if plat != "win32":
        state = PanelSurfaceState(
            applied=False, reason="unsupported_platform", fallback=True
        )
        setattr(widget, _SURFACE_ATTR, state)
        return state

    build = _windows_build_number() if build_number is None else int(build_number)
    if build < _DWM_BACKDROP_MIN_BUILD:
        state = PanelSurfaceState(
            applied=False, reason="unsupported_platform", fallback=True
        )
        setattr(widget, _SURFACE_ATTR, state)
        return state

    if high_contrast is None:
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            high_contrast = _windows_high_contrast_enabled(user32)
        except (AttributeError, OSError):
            high_contrast = False
    if high_contrast:
        state = PanelSurfaceState(
            applied=False, reason="high_contrast", fallback=True
        )
        setattr(widget, _SURFACE_ATTR, state)
        return state

    if transparency_enabled is None:
        transparency_enabled = _windows_transparency_enabled()
    if not transparency_enabled:
        state = PanelSurfaceState(
            applied=False, reason="transparency_disabled", fallback=True
        )
        setattr(widget, _SURFACE_ATTR, state)
        return state

    handle = int(hwnd) if hwnd is not None else _widget_hwnd(widget)
    if not handle:
        state = PanelSurfaceState(applied=False, reason="dwm_failed", fallback=True)
        setattr(widget, _SURFACE_ATTR, state)
        return state

    ok, reason = _set_system_backdrop(
        handle, _DWMSBT_TRANSIENTWINDOW, dwmapi=dwmapi
    )
    if not ok:
        state = PanelSurfaceState(
            applied=False, reason=reason or "dwm_failed", fallback=True
        )
        setattr(widget, _SURFACE_ATTR, state)
        return state

    state = PanelSurfaceState(applied=True, reason="", fallback=False)
    setattr(widget, _SURFACE_ATTR, state)
    return state


def release_native_panel_surface(
    widget,
    *,
    dwmapi: Any = None,
    hwnd: Optional[int] = None,
) -> None:
    """Clear backdrop type when previously applied. Idempotent."""
    existing = getattr(widget, _SURFACE_ATTR, None)
    if isinstance(existing, PanelSurfaceState) and existing.native is not None:
        existing.native.release()
        setattr(widget, _SURFACE_ATTR, PanelSurfaceState(applied=False, reason="released"))
        return
    handle = int(hwnd) if hwnd is not None else _widget_hwnd(widget)
    if handle and isinstance(existing, PanelSurfaceState) and existing.applied:
        _set_system_backdrop(handle, _DWMSBT_NONE, dwmapi=dwmapi)
    setattr(
        widget,
        _SURFACE_ATTR,
        PanelSurfaceState(applied=False, reason="released", fallback=True),
    )


def panel_surface_state(widget) -> Optional[PanelSurfaceState]:
    state = getattr(widget, _SURFACE_ATTR, None)
    return state if isinstance(state, PanelSurfaceState) else None


def uses_opaque_fallback(widget) -> bool:
    state = panel_surface_state(widget)
    if state is None:
        return True
    return bool(state.fallback or not state.applied)


__all__ = [
    "ACCENT_HEX",
    "FALLBACK_GLASS_ALPHA",
    "FONT_ROLE_BODY",
    "FONT_ROLE_CAPTION",
    "FONT_ROLE_CREDIT",
    "FONT_ROLE_EMPHASIS",
    "FONT_ROLE_TITLE",
    "FONT_ROLE_WORDMARK",
    "FROST_REFERENCE_PX",
    "GLASS_ALPHA",
    "GLOW_BL",
    "GLOW_TR",
    "INK_HEX",
    "PANEL_BASE_RGB",
    "PanelSurfaceState",
    "SECONDARY_HEX",
    "SPECTRUM_STOP_HEX",
    "TIP_BODY_HEX",
    "TIP_TITLE_HEX",
    "apply_native_panel_surface",
    "glass_alpha",
    "glass_fill_color",
    "glass_fill_css",
    "glow_color",
    "panel_color",
    "paint_panel_fill",
    "panel_font",
    "panel_font_family_css",
    "panel_font_metrics",
    "panel_surface_state",
    "release_native_panel_surface",
    "reset_panel_font_family_cache",
    "resolve_panel_font_family",
    "spectrum_stop_colors",
    "uses_opaque_fallback",
]
