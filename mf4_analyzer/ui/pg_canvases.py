"""Legacy import path for the pyqtgraph time-domain canvas.

Canonical implementation lives in ``mf4_analyzer.ui.pg_canvas.canvas``.
Keep this module as a compatibility shim for chart_stack, tests, packaging
hidden imports, and monkeypatch seams.
"""
from __future__ import annotations

from mf4_analyzer.ui.pg_canvas.annotations import (  # noqa: F401
    AnnotationManager,
    _annotation_pen_cursor,
)
from mf4_analyzer.ui.pg_canvas.canvas import (  # noqa: F401
    TimeDomainCanvasPG,
    _subplot_ylabel_text,
    _view_state_channel_key,
    build_envelope,
    positions_envelope,
)
from mf4_analyzer.ui.pg_canvas.context_menu import (  # noqa: F401
    _add_mouse_mode_toggle_row,
    _add_y_autofit_action,
    _apply_context_widget_i18n,
    _build_grid_submenu,
    _clean_menu_text,
    _find_top_level_action,
    _localize_pg_context_actions,
    _localize_pg_context_menu,
    _reorder_top_level_actions,
    _route_view_all_action,
    _strip_redundant_separators,
    _style_pg_context_menu,
    redesign_pg_context_menu,
)
from mf4_analyzer.ui.pg_canvas.cursor import CursorController  # noqa: F401
from mf4_analyzer.ui.pg_canvas.fonts import (  # noqa: F401
    _apply_pg_axis_font,
    _apply_pg_text_item_font,
    _pg_chart_font,
)
from mf4_analyzer.ui.pg_canvas.overlay_axes import OverlayAxisManager  # noqa: F401
from mf4_analyzer.ui.pg_canvas.quality import QualityManager  # noqa: F401
from mf4_analyzer.ui.pg_canvas.renderer import (  # noqa: F401
    Renderer,
    _HIDPI_COPY_SCALE,
    _HIDPI_MAX_WIDTH,
    _capped_hidpi_scale,
)
from mf4_analyzer.ui.pg_canvas.tick_density import (  # noqa: F401
    TickDensityController,
    _TARGET_X_TICK_EDGE_PAD_PX,
    _TARGET_X_TICK_MIN_COUNT,
    _TARGET_X_TICK_MIN_GAP_PX,
    _TARGET_X_TICK_NICE_FACTORS,
)
from mf4_analyzer.ui.pg_canvas.ticks_math import (  # noqa: F401
    _NICE_STEP_MANTISSAS,
    _adjacent_nice_step,
    _fmt_tick,
    _frame_to_nice,
    _nice_per_div,
    _quantize_range_key,
    _snap_y_to_divisions,
)
from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox  # noqa: F401

__all__ = [
    "TimeDomainCanvasPG",
    "positions_envelope",
    "build_envelope",
    "_ModifierWheelViewBox",
    "_pg_chart_font",
    "_apply_pg_axis_font",
    "_apply_pg_text_item_font",
    "_NICE_STEP_MANTISSAS",
    "_snap_y_to_divisions",
    "_nice_per_div",
    "_adjacent_nice_step",
    "_fmt_tick",
    "_frame_to_nice",
    "_quantize_range_key",
    "_capped_hidpi_scale",
    "_HIDPI_MAX_WIDTH",
    "_HIDPI_COPY_SCALE",
]
