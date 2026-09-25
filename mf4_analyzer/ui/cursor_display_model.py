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
class FrfLiveCursorFacts:
    """One live FRF cursor publication. Qt-free; no ChartStack dependency.

    ``mode`` is ``single``, ``dual``, or ``off``. A complete reading carries
    ``sample``. Dual placement that has only A sets ``awaiting_b`` and
    ``a_frequency_hz`` with ``sample is None``, so a later full/mini toggle
    cannot rebuild the previous B or Δ. ``off`` clears the live cache.
    """

    mode: str = "off"
    sample: FrfCursorSample | None = None
    awaiting_b: bool = False
    a_frequency_hz: float | None = None


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
    # FFT/time mini hides names and keeps the color dot. FRF metrics are
    # different quantities, so mini keeps the short label on each row.
    retain_mini_labels: bool = False
    # Overflow summary noun. Time/FFT stay "channels"; FRF passes "项指标".
    overflow_noun: str = "channels"


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


def cursor_display_channel_from_dual_row(row, *, source_label_resolver=None):
    """Map a DualCursorRow / 7-tuple / existing channel to CursorDisplayChannel.

    Qt-free shared mapping used by both ``pg_canvas.cursor`` and
    ``chart_stack.stack``. Label resolution is imported lazily so this module
    does not cycle with ``plot_helpers`` at import time.
    """
    if isinstance(row, CursorDisplayChannel):
        return row
    if not hasattr(row, "channel_name"):
        name, minimum, maximum, average, delta, unit_suffix, color = row[:7]
        return CursorDisplayChannel(
            identity=name,
            source_label="",
            channel_label=str(name),
            color=str(color or "#111827"),
            unit_suffix=str(unit_suffix or ""),
            delta=delta,
            min_value=minimum,
            max_value=maximum,
            avg_value=average,
        )
    from mf4_analyzer.ui.plot_helpers import resolve_cursor_source_label

    name = str(getattr(row, "label", "") or getattr(row, "channel_name", ""))
    identity = getattr(row, "identity", None)
    source_label, channel_label = resolve_cursor_source_label(
        name, identity, source_label_resolver
    )
    branches = tuple(
        CursorDisplayBranch(
            branch.branch_label,
            min_value=branch.min_value,
            max_value=branch.max_value,
            avg_value=branch.avg,
            delta_value=getattr(branch, "delta", None),
        )
        for branch in getattr(row, "branches", ())
    )
    return CursorDisplayChannel(
        identity=identity,
        source_label=source_label,
        channel_label=channel_label,
        color=str(getattr(row, "color", "#111827") or "#111827"),
        unit_suffix=str(getattr(row, "unit_suffix", "") or ""),
        delta=getattr(row, "delta", None),
        min_value=getattr(row, "min_value", None),
        max_value=getattr(row, "max_value", None),
        avg_value=getattr(row, "avg", None),
        branches=branches,
        diagnostic=str(getattr(row, "status", "") or ""),
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
    "FrfLiveCursorFacts",
    "PinnedCursorSample",
    "_OPTION_NAMES",
    "cursor_display_channel_from_dual_row",
    "enabled_value_fields",
]
