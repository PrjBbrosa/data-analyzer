"""chart_stack package — same-named package replacing chart_stack.py.

Re-exports the full public surface so all import paths are zero-change.
"""
# Monkeypatch anchor: tests patch "mf4_analyzer.ui.chart_stack.QFileDialog".
# Importing QFileDialog here so the name exists in THIS namespace, making it
# the target monkeypatch expects. The actual call in toolbar.save_figure()
# uses a sys.modules lookup so it picks up this namespace's binding.
from PyQt5.QtWidgets import QFileDialog  # noqa: F401 — monkeypatch anchor
# Sub-module re-exports (all public names used by application code + tests)
from ._helpers import (
    _apply_mdi_icons,
    _MDI_NAV_ICONS,
    _BOTTOM_HINT_PERSISTENT,
    _STATS_STRIP_ENABLED,
    _HIDPI_EXPORT_SCALE,
    _grab_pixmap_hidpi,
    _pixmap_as_device_pixels,
    _format_mini_html,
    _strip_subplots_action,
    _find_action,
    _install_nav_shortcuts,
    _install_button_shortcut,
    _vline,
    _ICON_COLOR,
    _ICON_ACTIVE,
    _TOOLBAR_COMPACT_WIDTH,
    _QT_WIDGETSIZE_MAX,
    _NAV_SHORTCUTS,
    _TIME_CARD_SHORTCUTS,
    _MODE_TO_INDEX,
    _INDEX_TO_MODE,
)
from .cursor_pill import (
    CursorPill,
    _QualityStatusIndicator,
    _CURSOR_HTML_SEP,
)
from .toolbar import (
    PgNavigationToolbar,
    _TickDensityPopover,
)
from .cards import (
    _ChartCard,
    TimeChartCard,
)
from .stack import ChartStack

__all__ = [
    # Application-level public names
    "ChartStack",
    # Test-imported names
    "CursorPill",
    "TimeChartCard",
    "_ChartCard",
    "_CURSOR_HTML_SEP",
    "_apply_mdi_icons",
    "_MDI_NAV_ICONS",
    "_BOTTOM_HINT_PERSISTENT",
    "_STATS_STRIP_ENABLED",
    # Additional helpers (re-exported for completeness)
    "PgNavigationToolbar",
    "_TickDensityPopover",
    "_QualityStatusIndicator",
    "_grab_pixmap_hidpi",
    "_pixmap_as_device_pixels",
    "_format_mini_html",
    "_strip_subplots_action",
    "_find_action",
    "_install_nav_shortcuts",
    "_install_button_shortcut",
    "_vline",
    "_HIDPI_EXPORT_SCALE",
    "_ICON_COLOR",
    "_ICON_ACTIVE",
    "_TOOLBAR_COMPACT_WIDTH",
    "_QT_WIDGETSIZE_MAX",
    "_NAV_SHORTCUTS",
    "_TIME_CARD_SHORTCUTS",
    "_MODE_TO_INDEX",
    "_INDEX_TO_MODE",
]
