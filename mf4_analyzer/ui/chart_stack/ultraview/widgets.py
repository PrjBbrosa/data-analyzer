"""Compatibility re-export façade for UltraView page widgets.

Class families live in sibling modules. Consumers keep importing names from
this module; type identity is the implementation class.
"""
from __future__ import annotations

import qtawesome as qta

from mf4_analyzer.ui.ultraview_state import ULTRAVIEW_PAGE_OBJECT_NAME

from .chrome import ULTRAVIEW_MUTED
from .feedback import (
    FEEDBACK_DISPLACED_OFFSCREEN,
    FEEDBACK_NO_LEGAL_LAYOUT,
    FEEDBACK_OUT_OF_GRID,
    FEEDBACK_SEARCH_BUDGET,
)
from .hint_bar import UltraViewHintBar
from .board_switcher import BoardSwitcher
from .board_toolbar import BoardToolbar, LAYOUT_LABELS_ZH
from .compare_rail import CompareRail, COMPARE_FILTER_LABELS_ZH
from .widgets_common import (
    STATUS_LABELS_ZH,
    _effective_device_pixel_ratio,
    extract_ref_strings,
    make_ref_mime,
)
from .card_widgets import (
    DIMMED_OPACITY,
    DRAG_DIM_OPACITY,
    MISSING_CARD_COPY,
    ORPHANED_CARD_COPY,
    REPLACE_HOVER_MS,
    STALE_CARD_COPY,
    TYPE_CHIP_ICON_ONLY_WIDTH,
    CardViewModel,
    FreeGridCard,
    ReplaceHoverController,
    UltraViewCard,
    preview_image,
)
from .library_widgets import (
    LIBRARY_DEFAULT_WIDTH,
    LIBRARY_HEAD_HEIGHT,
    LIBRARY_MAX_WIDTH,
    LIBRARY_MODE_GROUPS,
    LIBRARY_OVERLAY_HEIGHT,
    LIBRARY_OVERLAY_MIN_HEIGHT,
    LIBRARY_ROW_ACTION_SIZE,
    LIBRARY_ROW_DOT_INSET,
    LIBRARY_ROW_HEIGHT,
    LIBRARY_SEARCH_HEIGHT,
    LIBRARY_SECTION_GAP,
    LIBRARY_SECTION_HEAD_HEIGHT,
    LIBRARY_SECTION_ROW_GAP,
    LIBRARY_SELECTED_ROW_GUTTER,
    TRAY_BODY_MAX_HEIGHT,
    TRAY_ITEM_MIN_HEIGHT,
    UNPLACED_OVERLAY_MIN_HEIGHT,
    UNPLACED_OVERLAY_VISIBLE_ROWS,
    UNPLACED_OVERLAY_WIDTH,
    LibraryRow,
    LibraryRowWidget,
    TrayItem,
    UnplacedTray,
    ViewLibraryPanel,
    coerce_library_row,
)
from .template_board import BoardGrid, EmptySlotWidget
from .board_aux_widgets import (
    BoardOverview,
    BoardScrollArea,
    FocusLayer,
    FreeGridMinimap,
)
from .free_grid_board import FreeGridBoard, _reject_feedback
