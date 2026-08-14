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
})
"""QSS placeholders derived from :data:`CONTROL_COLORS` and height tracks."""


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
