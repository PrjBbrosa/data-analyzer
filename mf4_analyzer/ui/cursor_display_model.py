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
    # Display-only formatted number texts without the unit (R2). Empty when
    # the value is missing or the caller did not provide the display layer.
    min_text: str = ""
    max_text: str = ""
    avg_text: str = ""
    delta_text: str = ""

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
class CursorTableRow:
    """One display row within a channel; values carry no unit or HTML."""

    branch_label: str = ""
    metric_texts: tuple[str, ...] = ()
    diagnostic: str = ""


@dataclass(frozen=True)
class CursorDisplayBlock:
    identity: object
    qualified_label: str
    channel_label: str
    color: str
    visible_rows: tuple[CursorDisplayRow, ...]
    tooltip_rows: tuple[CursorDisplayRow, ...]
    diagnostic: str = ""
    # Display-only extras for the shared table (R1/R2): unit-less formatted
    # values in enabled-field order plus the channel's own unit text.
    metric_texts: tuple[str, ...] = ()
    unit_text: str = ""
    table_rows: tuple[CursorTableRow, ...] = ()


@dataclass(frozen=True)
class FrequencyCursorChannel:
    """Neutral FFT cursor readout. A/B are independent of time-domain stats."""

    identity: object
    source_label: str
    channel_label: str
    color: str = "#111827"
    unit_suffix: str = ""
    value: float | None = None
    delta_to_primary: float | None = None
    a_value: float | None = None
    b_value: float | None = None
    delta_ab: float | None = None

    @property
    def qualified_label(self) -> str:
        source = str(self.source_label or "").strip()
        channel = str(self.channel_label or "").strip()
        return f"{source} / {channel}" if source else channel


@dataclass(frozen=True)
class FrfCursorPoint:
    """One FRF sample at a snapped physical frequency. Never log10(view-x)."""

    frequency_hz: float
    magnitude: float | None = None
    phase_deg: float | None = None
    coherence: float | None = None


@dataclass(frozen=True)
class FrfCursorSample:
    """FRF cursor facts. Frequencies are always Hz, never log10.

    Single mode fills the top-level frequency/magnitude/phase/coherence
    fields. Dual mode fills ``a`` / ``b`` plus signed B−A deltas using the
    current owner definition (no extra angle wrap).
    """

    frequency_hz: float | None = None
    magnitude: float | None = None
    phase_deg: float | None = None
    coherence: float | None = None
    magnitude_unit: str = ""
    a: FrfCursorPoint | None = None
    b: FrfCursorPoint | None = None
    delta_frequency_hz: float | None = None
    delta_magnitude: float | None = None
    delta_phase_deg: float | None = None
    delta_coherence: float | None = None


@dataclass(frozen=True)
class CursorExtremaFact:
    """Time-domain dual-cursor min/max marker fact already computed by the owner."""

    identity: object
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class PinnedCursorSample:
    """Runtime cache of pin facts. Not persisted.

    Carries owner identity, binding generation, data revision, the actual
    sampled coordinates, structured channel or FRF facts, and extrema when
    the time-domain owner already computed them for markers.
    """

    owner_identity: object = None
    binding_generation: int | None = None
    data_revision: int | None = None
    domain: str = ""
    mode: str = ""
    x: float | None = None
    ax: float | None = None
    bx: float | None = None
    channels: tuple[CursorDisplayChannel | FrequencyCursorChannel, ...] = ()
    frf_sample: FrfCursorSample | None = None
    extrema: tuple[CursorExtremaFact, ...] = ()
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
    # Actual displayed columns: Value for single, enabled stats for dual,
    # one priority stat for dual mini, or empty for identity-only display.
    metric_labels: tuple[str, ...] = ()


def enabled_value_fields(options: CursorDisplayOptions | None):
    """Return enabled value fields in the product order Min, Max, Avg, Δ.

    Δ maps to time-X channel field ``delta``; custom-X branch rows remap
    that token to ``delta_value``.  ``None`` keeps the legacy compatibility
    formatter's historical Min/Max/Avg-only result.
    """
    if options is None:
        return (
            ("Min", "min_value"),
            ("Max", "max_value"),
            ("Avg", "avg_value"),
        )
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
    "CursorExtremaFact",
    "CursorTableRow",
    "CursorPresentation",
    "FrequencyCursorChannel",
    "FrfCursorPoint",
    "FrfCursorSample",
    "PinnedCursorSample",
    "_OPTION_NAMES",
    "enabled_value_fields",
]
