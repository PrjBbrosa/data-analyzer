"""UltraView ChartStack page package."""
from __future__ import annotations

from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    SLOT_GUTTER,
    content_rect,
    slot_rects,
)
from .page import UltraViewPage
from .preview_store import (
    MAX_PREVIEW_PIXELS,
    MAX_PREVIEW_RAW_EDGE,
    PreviewRecord,
    PreviewStore,
)
from .widgets import (
    BoardGrid,
    CompareRail,
    FocusLayer,
    LibraryRow,
    UnplacedTray,
    UltraViewCard,
    ViewLibraryPanel,
)

__all__ = [
    "BASE_BOARD_SIZE",
    "BOARD_PADDING",
    "CARD_FOOTER_HEIGHT",
    "CARD_HEADER_HEIGHT",
    "MIN_CARD_CHROME_HEIGHT",
    "SLOT_GUTTER",
    "content_rect",
    "slot_rects",
    "MAX_PREVIEW_PIXELS",
    "MAX_PREVIEW_RAW_EDGE",
    "PreviewRecord",
    "PreviewStore",
    "UltraViewPage",
    "BoardGrid",
    "CompareRail",
    "FocusLayer",
    "LibraryRow",
    "UnplacedTray",
    "UltraViewCard",
    "ViewLibraryPanel",
]
