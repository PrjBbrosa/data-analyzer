"""Semantic roles and shared visual tokens for ordinary Qt controls.

This is deliberately a low-level module: it knows only how a Qt widget
exposes dynamic properties and style repolishing.  Product pages remain the
owners of action semantics, layouts, icons, and business state.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol


CONTROL_ROLES = (
    "primary",
    "secondary",
    "quiet",
    "icon",
    "danger",
    "choice",
)
"""The only standard semantic roles for generic action controls."""

CONTROL_COLORS: Mapping[str, str] = MappingProxyType({
    "CONTROL_ACCENT": "#1769E0",
    "CONTROL_ACCENT_HI": "#2D7FF9",
    "CONTROL_ACCENT_DARK": "#135ABD",
    "CONTROL_ACCENT_BORDER": "#0F5FD2",
    "CONTROL_ACCENT_WASH": "#EDF5FF",
    "CONTROL_ACCENT_INK": "#0F3F8F",
    "CONTROL_SURFACE_TOP": "#FFFFFF",
    "CONTROL_SURFACE_BOTTOM": "#F8FAFD",
    "CONTROL_LINE": "#D5DEEA",
    "CONTROL_LINE_HOVER": "#AFC4DF",
    "CONTROL_TEXT": "#253247",
    "CONTROL_TEXT_MUTED": "#64748B",
    "CONTROL_DANGER": "#B42335",
    "CONTROL_DANGER_WASH": "#FFF2F3",
    "CONTROL_DISABLED_BG": "#F3F5F8",
    "CONTROL_DISABLED_LINE": "#E2E7EE",
    "CONTROL_ACCENT_LINE_SOFT": "#A9C9F2",
    "CONTROL_TRACK": "#EEF1F6",
    "CONTROL_TRACK_LINE": "#DDE3EC",
    "CONTROL_SELECT_LINE": "#CDD8E8",
    "CONTROL_TEXT_ON_SELECT": "#12437F",
    "CONTROL_SELECT_HOVER_TOP": "#F5FAFF",
    "CONTROL_SELECT_HOVER_BOTTOM": "#D5E8FF",
})
"""Canonical control palette; QSS and hand-painted controls read this map."""

CONTROL_HEIGHTS: Mapping[str, int] = MappingProxyType({
    "compact": 24,
    "base": 32,
    "cta": 36,
})
"""The three outer-height tracks shared by ordinary controls."""

CONTROL_HEIGHT_EXCEPTIONS: Mapping[str, str] = MappingProxyType({
    "QToolButton#inspectorCollapser": "section header chrome, not an action button",
    'QPushButton[role="preset-load"]': "preset-slot interaction has applied and filled states",
    "Toolbar QPushButton[segment]": "global analysis-mode selector retains its mode-zone geometry",
    "QWidget#BatchMethodGroup QPushButton[batchMethod]": "Batch analysis-mode selector",
    "QWidget#cockpitModeSegment QPushButton[cockpitMode]": "Cockpit global-mode selector",
    'QWidget#sliceDirToggle QPushButton[role="slice-seg"]': "in-plot slice-axis control",
    'QFrame#TickDensitySurface QPushButton[role="tick-density-preset"]': "chart-toolbar popout control",
    'QWidget#chartToolbar QPushButton[role="chart-choice"]': "chart-toolbar mode control",
    "QPushButton#channelConfigSave": "TimeDomain navigator rail matches the 28px ViewTabBar, not the 32px base track",
    "QPushButton#channelConfigApply": "TimeDomain navigator rail matches the 28px ViewTabBar, not the 32px base track",
    "QComboBox#channelConfigCombo": "TimeDomain navigator rail matches the 28px ViewTabBar, not the 32px base track",
})
"""Narrow, documented control geometries deliberately outside the three tracks."""


def control_content_min_height(
    size: str,
    *,
    vertical_padding: int,
    border_width: int = 1,
) -> int:
    """Return the QSS ``min-height`` content value for an outer height track.

    Qt applies QSS ``min-height`` to the content box, then adds top/bottom
    padding and borders.  Keeping that conversion here prevents every QSS
    selector from growing a hand-maintained copy of the height arithmetic.
    """
    if size not in CONTROL_HEIGHTS:
        choices = ", ".join(CONTROL_HEIGHTS)
        raise ValueError(f"Unknown control size {size!r}; expected one of: {choices}")
    if vertical_padding < 0 or border_width < 0:
        raise ValueError("vertical_padding and border_width must be non-negative")
    content_height = CONTROL_HEIGHTS[size] - 2 * (vertical_padding + border_width)
    if content_height <= 0:
        raise ValueError("padding and border leave no usable control content height")
    return content_height


_CONTROL_HEIGHT_QSS_TOKENS = {
    "CONTROL_H_COMPACT": f"{CONTROL_HEIGHTS['compact']}px",
    "CONTROL_H_BASE": f"{CONTROL_HEIGHTS['base']}px",
    "CONTROL_H_CTA": f"{CONTROL_HEIGHTS['cta']}px",
    # Existing control geometries use these padding families.  The names make
    # their chrome explicit while the values continue to derive solely from
    # CONTROL_HEIGHTS via ``control_content_min_height``.
    "CONTROL_H_COMPACT_BUTTON_CONTENT": (
        f"{control_content_min_height('compact', vertical_padding=2)}px"
    ),
    "CONTROL_H_COMPACT_STANDARD_BUTTON_CONTENT": (
        f"{control_content_min_height('compact', vertical_padding=4)}px"
    ),
    "CONTROL_H_COMPACT_FLAT_CONTENT": (
        f"{control_content_min_height('compact', vertical_padding=0)}px"
    ),
    # Qt's icon-only QToolButton size-hint algorithm adds its own icon chrome.
    # The calibrated 19px content floor keeps a 16px glyph within a fixed
    # 24px compact caller without inflating its outer box.
    "CONTROL_H_ICON_HINT_CONTENT": f"{CONTROL_HEIGHTS['compact'] - 5}px",
    "CONTROL_H_BASE_BUTTON_CONTENT": (
        f"{control_content_min_height('base', vertical_padding=4)}px"
    ),
    "CONTROL_H_BASE_INPUT_CONTENT": (
        f"{control_content_min_height('base', vertical_padding=3)}px"
    ),
    "CONTROL_H_BASE_FLAT_CONTENT": (
        f"{control_content_min_height('base', vertical_padding=0)}px"
    ),
    "CONTROL_H_CTA_BUTTON_CONTENT": (
        f"{control_content_min_height('cta', vertical_padding=4)}px"
    ),
    "CONTROL_H_CTA_FLAT_CONTENT": (
        f"{control_content_min_height('cta', vertical_padding=0)}px"
    ),
}

CONTROL_QSS_TOKENS: Mapping[str, str] = MappingProxyType({
    **CONTROL_COLORS,
    **_CONTROL_HEIGHT_QSS_TOKENS,
    # Shared surface colors (3+ sites) and local interaction-state families.
    # Keep exact RGB values; do not grow an anonymous palette in style.qss.
    "BATCH_FOOTER_LINK": "#086dda",
    "BATCH_TOOLBAR_PRESSED_TEXT": "#0f172a",
    "BATCH_METHOD_PRESSED": "#0f4ea9",
    "BATCH_METHOD_HOVER_TEXT": "#164d91",
    "VIEW_MENU_NAME_HOVER": "#164fae",
    "BATCH_RESULT_SUCCESS": "#168065",
    "VIEW_MENU_NAME": "#17243a",
    "VIEW_MENU_ACTION_HOVER_TEXT": "#174f9f",
    "CHART_EDGE_HOVER_TEXT": "#175db5",
    "VIEW_MENU_CURRENT_TEXT": "#2259aa",
    "BATCH_RESULT_SELECTED_TEXT": "#225b9c",
    "BATCH_METHOD_TEXT": "#335780",
    "VIEW_MENU_ACTION_TEXT": "#344860",
    "RECENT_CLEAR_TEXT": "#52677f",
    "CHART_EDGE_TEXT": "#58708f",
    "VIEW_MENU_CLOSE_TEXT": "#7a899d",
    "BATCH_RESULT_WARNING": "#94641b",
    "VIEW_MENU_ACTION_HOVER_BORDER": "#9eb8df",
    "BATCH_RESULT_ERROR": "#a44541",
    "VIEW_MENU_DANGER_HOVER_TEXT": "#a62537",
    "VIEW_MENU_DISABLED_TEXT": "#a6b0be",
    "RECENT_CLEAR_DISABLED_TEXT": "#a6b1bf",
    "CHART_EDGE_HOVER_BORDER": "#a9c5ea",
    "VIEW_MENU_DANGER_TEXT": "#bf3447",
    "CHART_EDGE_DISABLED_TEXT": "#c4ceda",
    "VIEW_MENU_CLOSE_DISABLED_TEXT": "#c5ced8",
    "POPUP_SCROLL_HANDLE": "#c5d0dc",
    "VIEW_MENU_ACTION_BORDER": "#c6d2df",
    "BATCH_METHOD_HOVER_BG": "#d0e4ff",
    "CHART_EDGE_BORDER": "#d5e0ec",
    "VIEW_MENU_DANGER_HOVER_BORDER": "#d88691",
    "BATCH_RESULT_LIST_BORDER": "#dce7f5",
    "VIEW_MENU_CURRENT_BG": "#dce9ff",
    "VIEW_MENU_DISABLED_BORDER": "#dde4ec",
    "VIEW_MENU_CLOSE_HOVER_BORDER": "#dfa0a9",
    "RECENT_CLEAR_HOVER_BORDER": "#dfabb2",
    "CHART_EDGE_PRESSED_BG": "#dfeeff",
    "VIEW_MENU_DANGER_BORDER": "#e2aeb5",
    "VIEW_MENU_CLOSE_FOCUS_BORDER": "#e5a8b0",
    "CHANNEL_TABLE_SELECTED_BG": "#e8f1fb",
    "BATCH_RESULT_SELECTED_BG": "#e9f2ff",
    "VIEW_MENU_SELECTED_BG": "#edf4ff",
    "BATCH_TOOLBAR_HOVER_BG": "#f1f4f8",
    "VIEW_MENU_DISABLED_BG": "#f2f5f8",
    "RECENT_CLEAR_HOVER_BG": "#fff4f5",
    "SURFACE_DISABLED_BG": "#f2f4f7",
    "SURFACE_MUTED_BORDER": "#d7dee8",
    "SURFACE_ACTION_BLUE": "#0b73e7",
    "SURFACE_SELECTED_PALE_BLUE": "#e8f1ff",
    "SURFACE_WARNING_TEXT": "#b45309",
    "SURFACE_BLUE_GREY_BORDER": "#d7e2f0",
    "SURFACE_STRONG_TEXT": "#26344a",
    "SURFACE_DANGER_BG": "#fff0f2",
    "SURFACE_DANGER_ACTIVE": "#dc3f52",
    "SURFACE_COOL_BG": "#edf1f6",
    "SURFACE_COOL_BORDER": "#dbe4ef",
    "SURFACE_ACCENT_PALE_BG": "#eaf2ff",
    "SURFACE_WARNING_BG": "#fffbeb",
    "SURFACE_WARNING_BORDER": "#fde68a",
    "SURFACE_WARNING_DARK_TEXT": "#92400e",
    "SURFACE_DARK_TEXT": "#1e293b",
})
"""QSS placeholders derived from :data:`CONTROL_COLORS` and height tracks."""

# Exact interaction accents used by Batch self-painted cards while enabled.
# Disabled paint must not emit these RGB values — QStyle chrome can disable
# itself, but hand-drawn title / radio / formula ink does not.
PAINTED_CARD_ACCENT = "#0b73e7"
PAINTED_GROUPING_RADIO = "#1769e0"
PAINTED_GROUPING_TITLE = "#0f56bd"


def _parse_hex_rgb(color: str) -> tuple[int, int, int]:
    text = str(color).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #RRGGBB, got {color!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def mix_hex_colors(color: str, toward: str, amount: float) -> str:
    """Blend ``color`` toward ``toward``. ``amount`` is the toward weight."""
    weight = min(1.0, max(0.0, float(amount)))
    src = _parse_hex_rgb(color)
    dst = _parse_hex_rgb(toward)
    mixed = tuple(round(a + (b - a) * weight) for a, b in zip(src, dst))
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def painted_state_hex(
    *,
    enabled: bool,
    checked: bool,
    accent: str,
    idle: str,
    disabled_checked: str | None = None,
    disabled_idle: str | None = None,
) -> str:
    """Resolve hand-painted ink from effective enabled × checked."""
    if enabled:
        return accent if checked else idle
    if checked:
        return disabled_checked or CONTROL_COLORS["CONTROL_TEXT_ON_SELECT"]
    return disabled_idle or CONTROL_COLORS["CONTROL_TEXT_MUTED"]


def painted_semantic_hex(color: str, *, enabled: bool) -> str:
    """Keep category hue when enabled; lower contrast when disabled."""
    if enabled:
        return color
    return mix_hex_colors(color, CONTROL_COLORS["CONTROL_TEXT_MUTED"], 0.62)


class _QtStyle(Protocol):
    def unpolish(self, widget: object) -> None: ...

    def polish(self, widget: object) -> None: ...


class _ControlWidget(Protocol):
    def setProperty(self, name: str, value: object) -> bool: ...

    def style(self) -> _QtStyle: ...

    def update(self) -> None: ...


def _require_member(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        choices = ", ".join(allowed)
        raise ValueError(f"Unknown control {label} {value!r}; expected one of: {choices}")


def set_control_role(
    widget: _ControlWidget,
    role: str,
    *,
    size: str | None = None,
) -> None:
    """Set validated semantic properties and refresh the widget's QSS state.

    This helper deliberately does not write geometry, text, icons, or business
    state.  It only marks semantics and causes Qt to re-evaluate QSS.
    """
    _require_member(role, CONTROL_ROLES, "role")
    if size is not None:
        _require_member(size, tuple(CONTROL_HEIGHTS), "size")

    widget.setProperty("role", role)
    if size is not None:
        widget.setProperty("controlSize", size)

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
