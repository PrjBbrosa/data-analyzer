"""Qt-free cursor-result DTOs and option snapshots.

Presentation HTML, the settings popover, and QSettings persistence stay in
``chart_stack.cursor_display``; ``pg_canvas`` imports this module only.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CursorDisplayOptions:
    show_max_point: bool = True
    show_min_point: bool = True
    show_max_value: bool = True
    show_min_value: bool = True
    show_avg_value: bool = True
    show_delta_value: bool = True


_OPTION_NAMES = tuple(item.name for item in fields(CursorDisplayOptions))


@dataclass(frozen=True)
class CursorDisplayBranch:
    label: str
    current_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    delta_value: float | None = None


@dataclass(frozen=True)
class CursorDisplayChannel:
    identity: object
    source_label: str
    channel_label: str
    color: str = "#111827"
    unit_suffix: str = ""
    current_value: float | None = None
    delta: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    branches: tuple[CursorDisplayBranch, ...] = ()
    diagnostic: str = ""

    @property
    def qualified_label(self) -> str:
        source = str(self.source_label or "").strip()
        channel = str(self.channel_label or "").strip()
        return f"{source} / {channel}" if source else channel


@dataclass(frozen=True)
class CursorDisplayRow:
    label: str
    value: str
    role: str = "value"


@dataclass(frozen=True)
class CursorDisplayBlock:
    identity: object
    qualified_label: str
    color: str
    visible_rows: tuple[CursorDisplayRow, ...]
    tooltip_rows: tuple[CursorDisplayRow, ...]
    diagnostic: str = ""


@dataclass(frozen=True)
class CursorPresentation:
    blocks: tuple[CursorDisplayBlock, ...]
    html: str
    tooltip: str
    layout_category: str
    cursor_mode: str
    x_mode: str
    mini: bool
    omit_visible_source_prefix: bool = False


def enabled_value_fields(options: CursorDisplayOptions):
    """Return enabled value fields in the product order Min, Max, Avg, Δ.

    Δ maps to time-X channel field ``delta``; custom-X branch rows remap
    that token to ``delta_value``.
    """
    return tuple(
        item for item, enabled in (
            (("Min", "min_value"), options.show_min_value),
            (("Max", "max_value"), options.show_max_value),
            (("Avg", "avg_value"), options.show_avg_value),
            (("Δ", "delta"), options.show_delta_value),
        )
        if enabled
    )


__all__ = [
    "CursorDisplayBlock",
    "CursorDisplayBranch",
    "CursorDisplayChannel",
    "CursorDisplayOptions",
    "CursorDisplayRow",
    "CursorPresentation",
    "_OPTION_NAMES",
    "enabled_value_fields",
]
