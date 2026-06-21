"""Backwards-compatibility re-export shim for mf4_analyzer.ui.canvases.

Phase D (2026-06-18): the legacy canvas classes (TimeDomainCanvas,
PlotCanvas) and their renderer-only helpers have been retired. Pure signal-math
helpers moved to ``mf4_analyzer.signal.envelope``; pure UI-formatting helpers
moved to ``mf4_analyzer.ui.plot_helpers``.

This module re-exports all previously public symbols so any remaining
``from mf4_analyzer.ui.canvases import ...`` statements continue to resolve
without modification.

Color constants and chart-keyword re-exports remain here because they are
referenced directly from test_canvas_compactness and from historical
configuration paths that may have loaded with this module in the past.
"""

from .._chart_kw import (
    CHART_TIGHT_LAYOUT_KW,
    AXIS_HIT_MARGIN_PX,
)

from mf4_analyzer.signal.envelope import (
    build_envelope,
    _is_monotonic_array,
    _ds_legacy_pure,
    _BUILD_ENVELOPE_LEGACY_MAX_PTS,
)

from mf4_analyzer.ui.plot_helpers import (
    _split_prefixed_label,
    _compact_axis_label,
    _middle_ellipsis,
    _set_series_ylabel,
    _format_single_cursor_channel_html,
    _format_dual_html,
    _interp_cursor_value,
)

# Color constants re-exported for any consumer that imported them from here.
CHART_FACE = '#ffffff'
AXIS_TEXT = '#475569'
AXIS_LINE = '#cbd5e1'
GRID_LINE = '#d7dee8'
PRIMARY = '#1769e0'
DANGER = '#dc2626'

__all__ = [
    # chart keyword constants
    'CHART_TIGHT_LAYOUT_KW',
    'AXIS_HIT_MARGIN_PX',
    # color constants
    'CHART_FACE',
    'AXIS_TEXT',
    'AXIS_LINE',
    'GRID_LINE',
    'PRIMARY',
    'DANGER',
    # signal envelope helpers
    'build_envelope',
    '_is_monotonic_array',
    '_ds_legacy_pure',
    '_BUILD_ENVELOPE_LEGACY_MAX_PTS',
    # UI formatting helpers
    '_split_prefixed_label',
    '_compact_axis_label',
    '_middle_ellipsis',
    '_set_series_ylabel',
    '_format_single_cursor_channel_html',
    '_format_dual_html',
    '_interp_cursor_value',
]
