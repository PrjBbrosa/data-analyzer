"""Bounded shared-column table layout planning for the cursor pill.

Pure calculation: the inputs are host budget numbers plus font-measured
widths, the output is one deterministic layout plan (horizontal / grouped /
compact / identity). No Qt objects, no widget lifecycle, no analysis math —
:mod:`cursor_pill` owns actual text measurement, and
:mod:`cursor_display` turns a plan into HTML.

Spec: ``docs/analyzer/specs/2026-09-12-cursor-table-readability-spec.md``
R4 (width budget) and R5 (structure choice). All values are Qt logical
pixels; never multiply by a device pixel ratio here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Sequence

# Absolute ceiling of the outer frame (R4).
_WCAP_ABSOLUTE_MAX = 640.0
# Comfortable lower bound for narrow hosts; strictly obeyed below it (R4).
_WCAP_FLOOR = 360.0
# Preferred fraction of safe width; fitting horizontal tables may exceed it.
_WCAP_RATIO = 0.60

# Cell padding constants, kept in logical px and shared with the renderer so
# measurements and rendered cells use the same envelope.
_VALUE_CELL_PAD_RIGHT = 10.0   # trailing gap after a right-aligned value
_LABEL_PAD_RIGHT = 4.0         # gap between a metric label and its value
_COMPACT_PAIR_GAP = 10.0       # gap between the two pairs on one compact row


def compute_wcap(wsafe: float) -> float:
    """Preferred outer-frame width for a pane safe width ``wsafe``.

    A complete horizontal row may expand to min(640, wsafe).
    """
    return min(wsafe, _WCAP_ABSOLUTE_MAX,
               max(_WCAP_FLOOR, int(_WCAP_RATIO * wsafe)))


@dataclass(frozen=True)
class TableLayoutPlan:
    """One deterministic layout choice shared by all structured cursor modes."""

    kind: str
    # horizontal / grouped: width of every metric column (shared across
    # channels). identity: 0.
    column_width: float
    # Measured and bounded identity/units cell in a horizontal row.
    signal_column_width: float
    # Width budget the name text may use (logical px).
    name_budget: float
    # Maximum name text lines before middle elision (R6).
    name_max_lines: int
    # compact only: shared label column width; 0 otherwise.
    label_column_width: float
    # compact only: shared value column width; 0 otherwise.
    value_column_width: float
    # compact only: pairs per row (1 or 2); 0 otherwise.
    pairs_per_row: int
    # Outer width the table actually needs; never exceeds the content width.
    required_width: float
    # Header rows above the channel rows (1 for horizontal/grouped, 0 else).
    header_rows: int
    # Rendered rows per channel (horizontal counts the name/unit cell as one).
    rows_per_channel: int
    # Number of enabled metric columns (0 for identity).
    metric_column_count: int
    # Explicit direction column for Custom-X; absent for ordinary Time-X.
    branch_column_width: float = 0.0


def choose_table_layout(
    *,
    content_width: float,
    value_envelope_width: float,
    field_labels: Sequence[str],
    field_label_widths: Sequence[float],
    signal_width: float = 0.0,
    branch_width: float = 0.0,
) -> TableLayoutPlan:
    """Pick the structure from actual measured text and the host ceiling.

    ``field_labels`` / ``field_label_widths`` list the enabled metric fields
    in product order (Min, Max, Avg, Δ); disabled fields are already removed
    by the caller so closing a toggle really removes its column. An empty
    field list yields the identity-only name list (R2).
    """
    labels = tuple(field_labels)
    label_widths = tuple(float(w) for w in field_label_widths)
    envelope = max(0.0, float(value_envelope_width))
    content = max(0.0, float(content_width))
    k = len(labels)
    branch = max(0.0, float(branch_width))
    signal = min(260.0, max(0.0, float(signal_width)))
    if k == 0:
        return TableLayoutPlan(
            kind="identity",
            column_width=0.0,
            signal_column_width=0.0,
            name_budget=content,
            name_max_lines=2,
            label_column_width=0.0,
            value_column_width=0.0,
            pairs_per_row=0,
            required_width=0.0,
            header_rows=0,
            rows_per_channel=1,
            metric_column_count=0,
        )

    max_label = max(label_widths) if label_widths else 0.0
    column = max(envelope, max_label) + _VALUE_CELL_PAD_RIGHT

    # Names use their measured width. Long identities are bounded before
    # choosing a structure; short names never inherit an arbitrary 200px floor.
    if signal and signal + branch + k * column <= content:
        return TableLayoutPlan(
            kind="horizontal", column_width=column,
            signal_column_width=signal, name_budget=signal,
            name_max_lines=2, label_column_width=0.0,
            value_column_width=0.0, pairs_per_row=0,
            required_width=signal + branch + k * column,
            header_rows=1, rows_per_channel=1, metric_column_count=k,
            branch_column_width=branch,
        )

    # Shared numeric grid, with identity spanning the grid when a signal
    # column cannot fit. Direction remains a separately budgeted column.
    if branch + k * column <= content:
        return TableLayoutPlan(
            kind="grouped",
            column_width=column,
            signal_column_width=0.0,
            name_budget=branch + k * column,
            name_max_lines=2,
            label_column_width=0.0,
            value_column_width=0.0,
            pairs_per_row=0,
            required_width=branch + k * column,
            header_rows=1,
            rows_per_channel=2,
            metric_column_count=k,
            branch_column_width=branch,
        )

    # 2. Compact grouped table: at most two "label value" pairs per row.
    # The name row spans the pair slots, so its budget is the grid width.
    label_column = max_label + _LABEL_PAD_RIGHT
    value_column = envelope + _VALUE_CELL_PAD_RIGHT
    pair_width = label_column + value_column
    pairs = 2 if branch + 2 * pair_width + _COMPACT_PAIR_GAP <= content else 1
    rows = ceil(k / pairs)
    required = (
        branch + min(pairs, k) * pair_width + (pairs - 1) * _COMPACT_PAIR_GAP
    )
    return TableLayoutPlan(
        kind="compact",
        column_width=0.0,
        signal_column_width=0.0,
        name_budget=required,
        name_max_lines=2,
        label_column_width=label_column,
        value_column_width=value_column,
        pairs_per_row=pairs,
        required_width=required,
        header_rows=0,
        rows_per_channel=1 + rows,
        metric_column_count=k,
        branch_column_width=branch,
    )


__all__ = [
    "TableLayoutPlan",
    "choose_table_layout",
    "compute_wcap",
]
