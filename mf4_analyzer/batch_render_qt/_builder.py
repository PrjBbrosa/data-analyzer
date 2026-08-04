"""Build offscreen pyqtgraph report scenes for all batch image payloads."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QFrame, QGraphicsTextItem, QWidget

from mf4_analyzer import db_reference
from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_style import RenderStyle, render_style_from_params
from mf4_analyzer.signal._envelope_cutils import positions_envelope
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
from mf4_analyzer.qt_plot_helpers import (
    hide_native_auto_button,
    show_major_grid_left_bottom_only,
)
from mf4_analyzer.render_profile import (
    RenderProfile,
    bucket_width_for,
    classify_render_profile,
    source_revision_for,
)
from ..ui_kit.ticks_math import (
    _fmt_tick,
    _frame_to_nice,
    _nice_per_div,
    coarsen_nice_step,
    nice_ticks_within,
)
from ..batch_statistics import display_x

from ._fonts import apply_axis_font, chart_font
from ._models import (
    BatchRenderContext,
    BatchSeries,
    BatchSlicePlan,
    BatchTimeFigureSpec,
    plan_heatmap_slice,
)
from ._page import add_report_footer, add_report_header
from ._palette import slice_palette
from ._theme import SERIES_COLORS, RenderTheme, render_theme, scaled_fonts


_SUPPORTED_KINDS = frozenset({"time", "fft", "fft_time", "order_time"})
_EMPTY_DB_LEVEL = -200.0
_AUTO_SPAN_DB = 30.0
_AUTO_CEILING_PERCENTILE = 99.0
_DISPLAY_DEAD_SPAN_DB = 200.0


def _finite_values(values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


def _valid_pair(low, high) -> bool:
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return False
    return bool(
        np.isfinite(low_value)
        and np.isfinite(high_value)
        and high_value > low_value
    )


def _linear_amplitude_label(unit: str) -> str:
    normalized = str(unit or "").strip()
    return f"Amplitude ({normalized})" if normalized else "Amplitude"


def _render_in_db(kind: str, params: Mapping[str, Any]) -> bool:
    if kind not in {"fft", "fft_time", "order_time"}:
        return False
    default_mode = "amplitude_db" if kind == "fft_time" else "amplitude"
    amplitude_mode = str(params.get("amplitude_mode", default_mode)).lower()
    amplitude_axis = str(params.get("amplitude_axis", "linear")).lower()
    legacy_axis = str(params.get("amp_y", "")).lower()
    return "db" in amplitude_mode or amplitude_axis == "db" or legacy_axis == "db"


def _reference_resolution(params: Mapping[str, Any]):
    existing = params.get("db_reference_resolution")
    if isinstance(existing, db_reference.DbReferenceResolution):
        return existing
    migrated = db_reference.migrate_legacy_reference_params(params)
    return db_reference.resolve_db_reference(
        mode=migrated.get("db_reference_mode", "auto"),
        manual_value=migrated.get("db_reference"),
        facts=db_reference.ChannelReferenceFacts(quantity="", unit=""),
        user_catalog=(),
        system_catalog=db_reference.FACTORY_CATALOG_V1,
    )


def _rendered_db_fact(kind: str, params: Mapping[str, Any]) -> str:
    if not _render_in_db(kind, params):
        return ""
    resolution = _reference_resolution(params)
    return db_reference.format_amplitude_label(
        resolution,
        weighting=str(params.get("weighting", "None")),
        output_scale="db",
    )


def _auto_db_color_limits(values) -> tuple[float, float]:
    finite = _finite_values(values)
    if finite.size == 0:
        return (_EMPTY_DB_LEVEL - _AUTO_SPAN_DB, _EMPTY_DB_LEVEL)
    ceiling = float(np.percentile(finite, _AUTO_CEILING_PERCENTILE))
    return (ceiling - _AUTO_SPAN_DB, ceiling)


def _finite_limits(values) -> tuple[float, float]:
    finite = _finite_values(values)
    if finite.size == 0:
        return (0.0, 1.0)
    low = float(np.min(finite))
    high = float(np.max(finite))
    if not high > low:
        pad = max(abs(low) * 0.05, 0.5)
        low -= pad
        high += pad
    return (low, high)


def _coverage_extent(values, *, start=None, end=None) -> tuple[float, float]:
    centers = np.asarray(values, dtype=float).reshape(-1)
    finite = centers[np.isfinite(centers)]
    if finite.size == 0:
        return (0.0, 1.0)
    if _valid_pair(start, end):
        return (float(start), float(end))
    finite = np.sort(finite)
    if finite.size == 1:
        center = float(finite[0])
        half_step = max(abs(center) * 0.01, 0.5)
        return (center - half_step, center + half_step)
    spacing = np.diff(finite)
    positive = spacing[np.isfinite(spacing) & (spacing > 0.0)]
    if positive.size == 0:
        center = float(finite[0])
        half_step = max(abs(center) * 0.01, 0.5)
        return (center - half_step, center + half_step)
    return (
        float(finite[0]) - float(positive[0]) / 2.0,
        float(finite[-1]) + float(positive[-1]) / 2.0,
    )


def _data_axis_extent(values) -> tuple[float, float]:
    """Match the foreground frequency/order endpoint semantics."""

    finite = np.asarray(values, dtype=float).reshape(-1)
    finite = finite[np.isfinite(finite)]
    if finite.size >= 2:
        return float(np.min(finite)), float(np.max(finite))
    # A one-row image still needs a non-degenerate QRectF to remain visible.
    return _coverage_extent(finite)


def _axis_label(name: str) -> str:
    normalized = str(name or "").strip().lower()
    labels = {
        "time": "Time (s)",
        "time_s": "Time (s)",
        "frequency": "Frequency (Hz)",
        "frequency_hz": "Frequency (Hz)",
        "order": "Order",
    }
    return labels.get(normalized, str(name or ""))


# pyqtgraph 0.14's AxisItem.resizeEvent anchors a bottom title at
# ``height - boundingRect().height() + nudge`` with ``nudge = 5``. Mirrored
# here so the offset below is applied from the same base every time instead of
# compounding across the repeated layout passes in ``show_and_settle``.
_PG_AXIS_LABEL_NUDGE_PX = 5.0


def _space_bottom_axis_label(plot, font_pt: float, *, overhang: bool = True):
    """Return a callback that keeps the x-axis title off the tick numbers.

    pyqtgraph reserves only ``label.boundingRect().height() * 0.8`` for an axis
    title and then anchors it to the bottom of that box, so the bottom title
    ends up sitting on the tick row with barely a pixel of air.

    The title is nudged down *without touching the axis height*: growing the
    axis (document margin or ``setHeight``) would take the space out of the
    plot area, and a smaller plot changes how much of a curve renders as
    near-vertical stair-steps — enough to move the supersampling stroke-weight
    ratio that ``tests/test_batch_render_qt_ssaa.py`` pins. A QGraphicsItem is
    not clipped to its parent, so the title simply overhangs into the empty
    band above the page footer, exactly as pyqtgraph's own 5px nudge already
    does.
    """
    axis = plot.getAxis("bottom")
    label = getattr(axis, "label", None)
    if label is None:
        return None
    extra = max(6.0, float(font_pt) * 0.9)
    base_axis_height = None

    def reposition(*_args) -> None:
        if not axis.isVisible() or not str(axis.labelText or "").strip():
            return
        nonlocal base_axis_height
        if not overhang:
            if base_axis_height is None:
                base_axis_height = float(axis.height())
            axis.setHeight(base_axis_height + extra)
        rect = label.boundingRect()
        base_y = float(axis.size().height() - rect.height())
        label.setPos(
            label.pos().x(),
            base_y + (_PG_AXIS_LABEL_NUDGE_PX + extra if overhang else 0.0),
        )

    if not overhang:
        reposition.runs_after_tick_density = True
    plot.vb.sigResized.connect(reposition)
    return reposition


def _extract_heatmap(data):
    if isinstance(data, pd.DataFrame):
        if "amplitude" not in data.columns or len(data.columns) < 3:
            raise ValueError("heatmap DataFrame must contain two axes and amplitude")
        x_name = str(data.columns[0])
        y_name = str(data.columns[1])
        pivot = data.pivot(index=y_name, columns=x_name, values="amplitude")
        return (
            pivot.to_numpy(dtype=float),
            pivot.columns.to_numpy(dtype=float),
            pivot.index.to_numpy(dtype=float),
            x_name,
            y_name,
            {},
        )

    required = ("x", "y", "matrix", "x_name", "y_name")
    missing = [name for name in required if not hasattr(data, name)]
    if missing:
        raise TypeError(f"heatmap payload is missing attributes: {', '.join(missing)}")
    x_values = np.asarray(data.x, dtype=float)
    y_values = np.asarray(data.y, dtype=float)
    x_major = np.asarray(data.matrix, dtype=float)
    expected = (x_values.size, y_values.size)
    if x_major.shape != expected:
        raise ValueError(
            f"heatmap matrix shape {x_major.shape} does not match x/y {expected}"
        )
    metadata = getattr(data, "metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    return (
        x_major.T,
        x_values,
        y_values,
        str(data.x_name),
        str(data.y_name),
        dict(metadata),
    )


def _axis_unit(name: str) -> str:
    """Return just the unit of an axis, e.g. ``"s"``, ``"Hz"``, ``""`` (order)."""
    label = _axis_label(name)
    if "(" in label and ")" in label:
        return label.split("(", 1)[1].split(")", 1)[0].strip()
    return ""


def _slice_curve_values(matrix, axis: str, index: int) -> np.ndarray:
    """Return the amplitude curve for one slice pick.

    ``matrix`` is the display matrix as ``_extract_heatmap`` hands it over:
    **row-major, rows = Y (frequency/order), columns = X (time)** — see the
    ``x_major.T`` there. So fixing a *time* takes a column and the curve runs
    along Y, while fixing a *frequency/order* takes a row and the curve runs
    along X. Identical to the single-file canvas' ``_apply_slice``
    (``m[:, idx]`` / ``m[idx, :]``).
    """
    values = np.asarray(matrix, dtype=float)
    if str(axis).strip().lower() == "time":
        return values[:, int(index)]
    return values[int(index), :]


def _slice_visible_mask(coords, low: float, high: float) -> np.ndarray:
    """Mask coordinate centers inside the visible range, nearest as fallback.

    Copied from ``ui/pg_canvas/heatmap_canvas.py`` (``_slice_visible_mask``);
    ``ui/`` must not be importable from the batch renderer, a boundary
    ``renderer_import_policy`` and ``tests/test_batch_render_import_boundary.py``
    keep.
    """
    array = np.asarray(coords, dtype=float)
    finite = np.isfinite(array)
    if array.size == 0:
        return finite
    low, high = sorted((float(low), float(high)))
    mask = finite & (array >= low) & (array <= high)
    if np.any(mask):
        return mask
    valid = np.flatnonzero(finite)
    if valid.size == 0:
        return mask
    target = (low + high) / 2.0
    nearest = valid[int(np.argmin(np.abs(array[valid] - target)))]
    mask = np.zeros(array.shape, dtype=bool)
    mask[nearest] = True
    return mask


# Widest dynamic range a real measurement slice can plausibly span. Bins more
# than this far below the slice's top are numerically-dead artifacts: the 0 Hz
# DC bin, zeroed by de-mean and/or A-weighting (gain == 0 at f == 0), then
# floored by ``amplitude_to_db`` to ``20*log10(np.finfo(float).tiny)`` ≈
# -6153 dB. A 24-bit acquisition has only ~144 dB of range, so 200 dB only ever
# catches such dead bins, never real signal (e.g. a deep anti-resonance notch).
#
# Copied — not imported — from ``ui/pg_canvas/heatmap_canvas.py`` (the
# ``_SLICE_MAX_SPAN_DB`` / ``_slice_amp_bounds`` pair around line 385) because
# the batch renderer may not import ``mf4_analyzer.ui``.
_SLICE_MAX_SPAN_DB = 200.0


def _slice_amp_bounds(values):
    """Robust ``(lo, hi)`` for the slice amplitude *view* axis, or ``None``.

    Display-only: the curve is always drawn in full; this only picks the Y
    *view* range. The top is the literal max (a line plot should show real
    peaks, unlike the colour window). The bottom ignores numerically-dead bins
    sitting more than ``_SLICE_MAX_SPAN_DB`` below the top, so a single DC bin
    floored to ≈ -6153 dB can no longer crush the real -40..-60 dB signal into
    a thin band at the top of the panel. NaN/inf-safe. Returns ``None`` when
    there is no finite spread to fit.
    """
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return None
    high = float(np.max(finite))
    real = finite[finite >= high - _SLICE_MAX_SPAN_DB]
    low = float(np.min(real)) if real.size else high
    if high <= low:
        return None
    return low, high


def _nice_amp_range(low: float, high: float, divisions: int):
    """Round ``[low, high]`` outward onto whole nice steps, or ``None``.

    Deliberately **not** ``_frame_to_nice``: that helper forces exactly ``n``
    equal divisions (oscilloscope graticule semantics, ``top = bottom + n *
    per_div``) on top of a step that ``_nice_per_div`` already rounded up, and
    the two compound into a mostly-empty axis. At the repository default
    ``tick_density_y = 10`` it turns ``[-99.11, -34.38]`` into ``[-100, 0]`` —
    35% of the panel height wasted, the curve squashed into the lower half.

    Taking only the *step* from ``_nice_per_div`` and rounding each end outward
    on its own gives ``[-100, -30]`` (8% wasted) with equally tidy tick values.
    Design D19/D19b.
    """
    try:
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        return None
    span = high - low
    if not math.isfinite(span) or span <= 0:
        return None
    step = _nice_per_div(span / max(1, int(divisions))) or span
    if not math.isfinite(step) or step <= 0:
        return None
    bottom = math.floor(low / step) * step
    top = math.ceil(high / step) * step
    if not top > bottom:
        return None
    return bottom, top


def _slice_dimension_title(plan: BatchSlicePlan, x_name: str, y_name: str) -> str:
    """Legend column head naming the *fixed* dimension."""
    if plan.axis == "time":
        return "固定时间"
    return "固定阶次" if _axis_label(y_name) == "Order" else "固定频率"


def _format_slice_position(value: float, unit: str) -> str:
    """Legend/label text for one landed position, e.g. ``5.00 s``, ``620.0 Hz``."""
    if unit == "s":
        return f"{value:.2f} s"
    if unit:
        return f"{value:.1f} {unit}"
    return f"{value:.2f}"


# The swatch cell's content and the gap the label cell puts before its text.
# Both live in the HTML below; measuring a row means measuring these too. The
# swatch is spelled twice because the entity is what the HTML parser wants and
# the character is what ``QFontMetricsF`` can measure. A plain space would not
# do for either: the parser collapses runs of them.
_SLICE_LEGEND_SWATCH_HTML = "&nbsp;&nbsp;"
_SLICE_LEGEND_SWATCH_TEXT = chr(0xA0) * 2  # what the entity parses to
_SLICE_LEGEND_LABEL_GAP = 7.0
# Air between the slice row's plot area and the legend card parked beside it.
_SLICE_LEGEND_GUTTER_GAP = 8.0


def _page_right_limit(widget) -> float:
    """Scene x the page's content may reach.

    ``ci`` fills the view, so the printable right edge is its own right edge
    less the layout's right margin — the same margin every row's plot is laid
    out against, and therefore the line an overlay drawn straight onto the
    scene has to respect on its own.
    """
    try:
        return float(widget.ci.sceneBoundingRect().right()) - float(
            widget.ci.layout.getContentsMargins()[2]
        )
    except Exception:  # pragma: no cover - defensive, no known trigger
        return float(widget.sceneRect().right())


def _slice_legend_row_label(pick, unit: str) -> str:
    """The one row of legend text ``pick`` contributes."""
    label = _format_slice_position(pick.value, unit)
    return f"{label}·夹取" if pick.clamped else label


def _slice_legend_content_width(
    plan: BatchSlicePlan,
    *,
    title: str,
    unit: str,
    title_pt: float,
    body_pt: float,
) -> float:
    """Content width the legend's own strings need (design D-B3).

    ``_StatisticsCard`` passes ``content_width`` straight to
    ``QTextDocument.setTextWidth`` *and* builds its frame from it, so a
    hard-coded number is a promise about text nobody measured. The rows carry
    ``white-space:nowrap``, so an undersized width does not wrap the label —
    the document simply lays out wider than the frame and the overflow is
    painted outside the card, which is how ``3000.0 Hz`` ended up cropped by
    the page edge at the hard-coded 86 px.

    Measured against the same point sizes the HTML declares, since both are
    multiples of ``axis_font_pt`` and drift apart the moment one of them is
    edited alone.
    """
    body = QFontMetricsF(chart_font(body_pt))
    title_font = chart_font(title_pt)
    title_font.setBold(True)  # the heading declares font-weight:600
    swatch = float(body.width(_SLICE_LEGEND_SWATCH_TEXT))
    rows = max(
        (
            swatch
            + _SLICE_LEGEND_LABEL_GAP
            + float(body.width(_slice_legend_row_label(pick, unit)))
            for pick in plan.picks
        ),
        default=0.0,
    )
    return max(rows, float(QFontMetricsF(title_font).width(title)))


def _slice_legend_html(
    plan: BatchSlicePlan,
    palette: tuple[str, ...],
    *,
    title: str,
    unit: str,
    title_pt: float,
    body_pt: float,
) -> str:
    """Colour-swatch legend for the gutter beside the slice row (design §5.5)."""
    rows = []
    for pick, color in zip(plan.picks, palette):
        label = _slice_legend_row_label(pick, unit)
        rows.append(
            '<tr>'
            f'<td style="background-color:{color}; padding:0px 0px;">'
            f'{_SLICE_LEGEND_SWATCH_HTML}</td>'
            '<td style="padding:1px 0px 1px '
            f'{_SLICE_LEGEND_LABEL_GAP:.0f}px; white-space:nowrap;">'
            f'{label}</td></tr>'
        )
    return (
        f'<div style="font-size:{title_pt:.2f}pt; font-weight:600; '
        f'color:#64748b; padding-bottom:3px;">{title}</div>'
        '<table cellspacing="0" cellpadding="0" '
        f'style="font-size:{body_pt:.2f}pt; border-collapse:collapse; '
        f'color:#172033;">{"".join(rows)}</table>'
    )


def _slice_clamp_warning(
    plan: BatchSlicePlan, low: float, high: float, unit: str
) -> str | None:
    """One warning covering every out-of-range and merged position, or ``None``.

    Out-of-range positions never fail a run (design D12): a batch that mixes
    file lengths would otherwise go red across the board.
    """
    clamped = plan.clamped_picks
    if not clamped and not plan.merged:
        return None
    suffix = f" {unit}" if unit else ""
    parts = []
    if clamped:
        requested = ", ".join(f"{pick.requested:.3f}" for pick in clamped)
        landed = ", ".join(f"{pick.value:.3f}" for pick in clamped)
        parts.append(
            f"切片位置 {requested}{suffix} 超出数据范围 "
            f"[{low:.3f}, {high:.3f}]{suffix}，已取 {landed}{suffix}"
        )
    if plan.merged:
        total = len(plan.picks) + plan.merged
        parts.append(f"{total} 个位置夹取后合并为 {len(plan.picks)} 个")
    return "slice.position_clamped: " + "；".join(parts)


# pyqtgraph measures every tick string with ``QPainter.boundingRect`` against
# this probe rect (AxisItem.generateDrawSpecs); reusing it keeps our own
# measurement on the same footing as the one that ends up on the canvas.
_TICK_TEXT_PROBE = QRectF(0.0, 0.0, 100.0, 100.0)


def _axis_tick_texts(axis) -> list[str]:
    """Return the tick strings ``axis`` would draw right now.

    ``setTicks`` parks explicit labels on ``_tickLevels``, which is what
    ``generateDrawSpecs`` reads back; an axis still on pyqtgraph's automatic
    ticker has to be asked for its values and their formatting instead.
    """
    levels = getattr(axis, "_tickLevels", None)
    if levels:
        return [
            str(text)
            for level in levels
            for _value, text in level
            if str(text)
        ]
    try:
        span = float(axis.boundingRect().height())
        if span <= 0.0:
            return []
        low, high = float(axis.range[0]), float(axis.range[1])
        scale = float(axis.autoSIPrefixScale) * float(axis.scale)
        texts: list[str] = []
        for spacing, values in axis.tickValues(low, high, span):
            texts.extend(
                str(text)
                for text in axis.tickStrings(list(values), scale, spacing)
                if str(text)
            )
        return texts
    except Exception:
        return []


def _left_axis_width_for_ticks(axis) -> float:
    """Width ``axis`` needs for the tick strings it is carrying *now*.

    ``AxisItem.width()`` cannot answer this. Its automatic width comes from
    ``AxisItem.textWidth``, and that attribute is only ever refreshed from
    inside ``generateDrawSpecs`` — i.e. while painting. ``_apply_tick_density``
    installs the final tick strings after the last paint in
    ``show_and_settle``, so a width read back at alignment time describes
    whichever strings were drawn last; on an axis that has never been painted
    it is pyqtgraph's initial ``textWidth = 30``, which is where a pinned
    57.4 px left axis came from against the 95.4 px the same ticks get when
    nothing pins them. Measuring the strings makes the answer independent of
    paint history.

    The arithmetic deliberately mirrors ``AxisItem._updateWidth``: ``setWidth``
    stores a *fixed* width that bypasses that method entirely, so everything it
    would have added — tick text offset, outward tick length, and the rotated
    label's allowance — has to be included here or the label lands on top of
    the numbers.
    """
    if not axis.isVisible():
        return 0.0
    style = axis.style
    if not style.get("showValues", True):
        return 0.0
    font = style.get("tickFont")
    if font is None:
        label_item = getattr(axis, "label", None)
        font = label_item.font() if label_item is not None else chart_font()
    metrics = QFontMetricsF(font)
    width = max(
        (
            float(
                metrics.boundingRect(
                    _TICK_TEXT_PROBE, Qt.AlignCenter, text
                ).width()
            )
            for text in _axis_tick_texts(axis)
        ),
        default=0.0,
    )
    width += float(style["tickTextOffset"][0])
    width += float(max(0, style["tickLength"]))
    label = getattr(axis, "label", None)
    if label is not None and label.isVisible():
        # ``_updateWidth`` calls the bounding rect an overestimate and takes
        # 80% of it; matching that keeps a pinned axis the same width the
        # unpinned one would have chosen.
        width += float(label.boundingRect().height()) * 0.8
    return width


def _slice_alignment_callback(layout, main_plot, slice_plot, *, right_reserve=0.0):
    """Return a callback that squares the slice row's plot area with the map's.

    Two asymmetries have to be cancelled for the two rows to read as one
    stacked chart:

    * The heatmap row spends its right-hand width on the colorbar, so the
      slice's ViewBox would otherwise run further right. The slice's (already
      value-less, frame-only) right axis absorbs the difference — the same
      trick as ``_set_slice_right_spacer`` in the single-file canvas — which
      also empties the gutter the legend then sits in.
    * The two left axes carry different quantities (frequency/order against
      amplitude), so their tick strings measure differently.

    Every invocation re-measures both left axes from the tick strings they
    hold at that moment (``_left_axis_width_for_ticks``) and pins the wider of
    the two onto both. Measuring the strings rather than reading
    ``axis.width()`` is what keeps this correct once ``_apply_tick_density``
    swaps the tick strings late in ``show_and_settle``: a width read back from
    the axis reports the last *painted* strings, so the pin would freeze the
    row at a stale — typically far too narrow — width and never recover, since
    a pinned axis no longer resizes when its labels grow. ``align`` is tagged
    ``runs_after_tick_density`` so ``show_and_settle`` re-runs it once the
    final strings are in place.

    The right-hand reserve is corrected *relatively* — by how far the two rows'
    right-hand chrome currently disagrees — rather than by clearing the spacer
    and re-measuring. A ``QGraphicsWidget`` size hint reaches the enclosing
    layout through a posted LayoutRequest, so a cleared spacer is not
    guaranteed to be reflected in the very next ``activate()``; a residual
    correction converges regardless of which pass the geometry came from, and
    settles to a no-op once the two edges meet. Bound to ``sigResized`` on both
    rows with a re-entry guard so the re-layouts it performs cannot recurse.

    ``right_reserve`` is the *floor* under that gutter — the legend's width plus
    its gap. Below it the colorbar alone decides the reserve, as before.
    """
    state = {"busy": False}

    def activate() -> None:
        layout.invalidate()
        layout.activate()

    def right_chrome(plot) -> float:
        """Width the plot spends right of its ViewBox (axis, colorbar, label)."""
        return float(
            plot.sceneBoundingRect().right() - plot.vb.sceneBoundingRect().right()
        )

    def align(*_args) -> None:
        if state["busy"]:
            return
        state["busy"] = True
        try:
            left_axes = (main_plot.getAxis("left"), slice_plot.getAxis("left"))
            target = max(_left_axis_width_for_ticks(axis) for axis in left_axes)
            if target > 0.0:
                for axis in left_axes:
                    axis.setWidth(target)
            activate()
            # The legend lives in that right-hand gutter, so the gutter has to
            # be wide enough to hold it. Buying the width on the *map* row is
            # what makes it available to both: its frame-only right axis is the
            # only piece of its right-hand chrome we own — the colorbar stays
            # anchored to the page's right edge, and the ViewBox column, the
            # sole expanding one, gives the space up. The slice row is then
            # squared against the widened chrome by the same correction as
            # before, so ``right_reserve`` costs the two rows equally and the
            # left/right edges stay together.
            shortfall = float(right_reserve) - right_chrome(main_plot)
            if shortfall > 0.5:
                main_right = main_plot.getAxis("right")
                main_right.setWidth(max(1.0, float(main_right.width()) + shortfall))
                activate()
            right_axis = slice_plot.getAxis("right")
            delta = right_chrome(main_plot) - right_chrome(slice_plot)
            if abs(delta) > 0.5:
                right_axis.setWidth(max(1.0, float(right_axis.width()) + delta))
                activate()
        except Exception:
            pass
        finally:
            state["busy"] = False

    align.runs_after_tick_density = True
    main_plot.vb.sigResized.connect(align)
    slice_plot.vb.sigResized.connect(align)
    return align


def _resolve_heatmap_colormap(
    params: Mapping[str, Any], warnings_out: list[str] | None
) -> tuple[pg.ColorMap, np.ndarray]:
    requested = params.get("cmap", "turbo")
    try:
        color_map = pg.colormap.get(str(requested))
    except Exception:
        color_map = None
    if color_map is None:
        if warnings_out is not None:
            warnings_out.append(
                f"Invalid colormap {requested!r}; using 'turbo'."
            )
        color_map = pg.colormap.get("turbo")
    if color_map is None:  # pragma: no cover - bundled pg 0.14 has turbo
        raise RuntimeError("pyqtgraph turbo colormap is unavailable")
    lut = color_map.getLookupTable(0.0, 1.0, 256, alpha=True)
    return color_map, np.asarray(lut, dtype=np.ubyte)


class _SmoothImageItem(pg.ImageItem):
    """Batch-local equivalent of the single-file bilinear ImageItem."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._smooth_transform = False

    def set_smooth_transform(self, enabled: bool) -> None:
        self._smooth_transform = bool(enabled)
        self.update()

    def paint(self, painter, *args):
        previous = painter.testRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._smooth_transform)
        try:
            return super().paint(painter, *args)
        finally:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, previous)


def _display_db_values(amplitude, reference: float) -> np.ndarray:
    linear = np.asarray(amplitude, dtype=float)
    converted = SpectrogramAnalyzer.amplitude_to_db(linear, reference=reference)
    display_floor = max(
        _EMPTY_DB_LEVEL,
        float(np.max(converted[np.isfinite(converted)])) - _DISPLAY_DEAD_SPAN_DB
        if np.any(np.isfinite(converted))
        else _EMPTY_DB_LEVEL,
    )
    finite = np.where(np.isfinite(converted), converted, display_floor)
    return np.maximum(finite, display_floor)


def _auto_db_line_limits(values) -> tuple[float, float]:
    finite = _finite_values(values)
    if finite.size == 0:
        return (_EMPTY_DB_LEVEL - _AUTO_SPAN_DB, _EMPTY_DB_LEVEL)
    ceiling = float(np.percentile(finite, _AUTO_CEILING_PERCENTILE))
    top = max(ceiling, float(np.max(finite)))
    bottom = ceiling - _AUTO_SPAN_DB
    if not top > bottom:
        top = bottom + 1.0
    return (bottom, top)


def _require_dataframe(data, columns, kind: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"{kind} payload must be a pandas DataFrame")
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(f"{kind} payload missing columns: {', '.join(missing)}")
    return data


def _first_appearance_units(
    series: tuple[BatchSeries, ...], attribute: str
) -> tuple[str, ...]:
    values: list[str] = []
    for item in series:
        value = str(getattr(item, attribute))
        if value not in values:
            values.append(value)
    return tuple(values)


def _validate_time_spec_units(series: tuple[BatchSeries, ...]) -> None:
    if len(_first_appearance_units(series, "x_unit")) > 1:
        raise ValueError("time figure spec has mixed x units")
    if len(_first_appearance_units(series, "unit")) > 2:
        raise ValueError("time figure spec supports at most two y units")


def _time_x(item: BatchSeries, spec: BatchTimeFigureSpec) -> np.ndarray:
    return display_x(item.x, x_source=spec.x_source, x_origin=spec.x_origin)


def _text_of(item) -> str:
    target = getattr(item, "item", item)
    to_plain = getattr(target, "toPlainText", None)
    if callable(to_plain):
        return str(to_plain())
    text = getattr(item, "text", "")
    return str(text)


class _StatisticsCard(pg.GraphicsObject):
    """Rounded report overlay with the same quiet hierarchy as CursorPill."""

    def __init__(
        self,
        html: str,
        *,
        content_width: float,
        body_font_pt: float,
        background: QColor,
        border: QColor,
        text_color: QColor,
    ) -> None:
        super().__init__()
        self.body_font_pt = float(body_font_pt)
        self._background = QColor(background)
        self._border = QColor(border)
        self._padding = 9.0
        self._radius = 9.0
        self._text = QGraphicsTextItem(self)
        self._text.setDefaultTextColor(QColor(text_color))
        self._text.setFont(chart_font(self.body_font_pt))
        self._text.document().setDocumentMargin(0.0)
        self._text.setHtml(html)
        self._text.document().setTextWidth(float(content_width))
        self._text.setPos(self._padding, self._padding)
        text_rect = self._text.boundingRect()
        self._bounds = QRectF(
            0.0, 0.0,
            float(content_width) + 2.0 * self._padding,
            float(text_rect.height()) + 2.0 * self._padding,
        )

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        return QRectF(self._bounds)

    def toPlainText(self) -> str:  # noqa: N802 (Qt API)
        return self._text.toPlainText()

    def paint(self, painter, _option, _widget=None) -> None:
        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            shadow = self._bounds.adjusted(1.5, 2.0, 1.5, 2.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(15, 23, 42, 20))
            painter.drawRoundedRect(shadow, self._radius, self._radius)
            rect = self._bounds.adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setPen(QPen(self._border, 1.0))
            painter.setBrush(self._background)
            painter.drawRoundedRect(rect, self._radius, self._radius)
        finally:
            painter.restore()


def _visible_text_rect(item) -> QRectF | None:
    if item is None or not item.isVisible():
        return None
    if not _text_of(item).strip():
        return None
    rect = item.sceneBoundingRect()
    return QRectF(rect) if rect.isValid() and not rect.isEmpty() else None


def _axis_tick_text_records(axis) -> list[tuple[QRectF, str]]:
    if axis is None or not axis.isVisible():
        return []
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        generated = axis.generateDrawSpecs(painter)
    except Exception:
        return []
    finally:
        painter.end()
    if not generated:
        return []
    records: list[tuple[QRectF, str]] = []
    for rect, _flags, value in generated[2]:
        scene_rect = axis.mapRectToScene(rect)
        if scene_rect.isValid() and not scene_rect.isEmpty():
            records.append((QRectF(scene_rect), str(value)))
    return records


@dataclass
class _TimeCurveBinding:
    curve: Any
    plot: Any
    x: np.ndarray
    y: np.ndarray
    profile: RenderProfile
    mode: str
    last_key: tuple[Any, ...] | None = None


@dataclass
class BuiltBatchScene:
    widget: pg.GraphicsLayoutWidget
    plots: tuple[Any, ...]
    curves: tuple[Any, ...]
    auxiliary_views: tuple[Any, ...]
    page_labels: tuple[Any, ...]
    panel_titles: tuple[str, ...]
    panel_text_items: tuple[tuple[Any, ...], ...]
    legend: Any
    options: BatchRenderOptions
    theme: RenderTheme
    style: RenderStyle = field(default_factory=RenderStyle)
    image_item: Any = None
    colorbar: Any = None
    display_matrix: np.ndarray | None = None
    heatmap_lut: np.ndarray | None = None
    heatmap_levels: tuple[float, float] | None = None
    heatmap_rect: QRectF | None = None
    slice_plan: BatchSlicePlan | None = None
    slice_plot: Any = None
    slice_curves: tuple[Any, ...] = field(default_factory=tuple)
    slice_marker_lines: tuple[Any, ...] = field(default_factory=tuple)
    slice_legend: Any = None
    _layout_callbacks: tuple[Any, ...] = field(default_factory=tuple)
    _sync_callbacks: tuple[Any, ...] = field(default_factory=tuple)
    _time_curve_bindings: tuple[_TimeCurveBinding, ...] = field(default_factory=tuple)
    _closed: bool = False

    @staticmethod
    def _view_pixel_width(plot) -> int:
        """Return the realized output width that governs display buckets."""

        try:
            width = float(plot.vb.sceneBoundingRect().width())
        except Exception:
            width = 0.0
        if not np.isfinite(width) or width < 1.0:
            try:
                width = float(plot.vb.width())
            except Exception:
                width = 0.0
        return max(1, int(round(width)))

    def _bind_time_display_envelopes(self) -> None:
        """Bind display-only time envelopes after output geometry is realized."""

        for binding in self._time_curve_bindings:
            pixel_width = self._view_pixel_width(binding.plot)
            x_range = tuple(float(value) for value in binding.plot.vb.viewRange()[0])
            effective_width = bucket_width_for(
                binding.profile,
                mode=binding.mode,
                pixel_width=pixel_width,
                interactive=False,
            )
            # Key on what the envelope actually consumes. ``pixel_width`` only
            # feeds ``bucket_width_for`` above; it never reaches
            # ``positions_envelope``, so two widths that bucket the same
            # produce byte-identical display data. Including it made the guard
            # miss on one-pixel axis jitter — pinning wider tick strings grows
            # the left axis by a pixel — and pay for a full O(n) envelope pass
            # over the raw channel to recompute the same result.
            key = (effective_width, x_range)
            if binding.last_key == key:
                continue
            display_x, display_y = positions_envelope(
                binding.x,
                binding.y,
                xlim=x_range,
                pixel_width=effective_width,
                is_monotonic=binding.profile.monotonic_time,
            )
            binding.curve.setData(display_x, display_y)
            binding.last_key = key

    def show_and_settle(self) -> None:
        if self._closed:
            raise RuntimeError("batch render scene is already closed")
        self.widget.resize(self.options.width_px, self.options.height_px)
        self.widget.show()
        layout = self.widget.ci.layout
        layout.invalidate()
        layout.activate()
        for callback in self._layout_callbacks:
            callback()
        layout.invalidate()
        layout.activate()
        self._bind_time_display_envelopes()
        for callback in self._sync_callbacks:
            callback()
        layout.invalidate()
        layout.activate()
        app = QApplication.instance()
        self._fit_axis_labels()
        layout.invalidate()
        layout.activate()
        # Axis tick widths and dual-Y nice ranges can adjust the final ViewBox
        # geometry. Rebind only curves whose effective bucket width or view
        # range actually changed; all of this happens before the first drain.
        self._bind_time_display_envelopes()
        for plot in self.plots:
            try:
                plot.vb.updateAutoRange()
            except Exception:
                pass
        # Only now are the view ranges final — an auto-ranged panel still reads
        # 0..1 before this point, and ticks pinned from that would fall outside
        # the finished plot.
        self._apply_tick_density()
        # Nothing changes the tick strings after this point, and a callback
        # that *sizes* an axis from them has to be the one to run last: the
        # slice row's left-axis alignment pins a fixed width, and a pinned axis
        # stops re-measuring itself, so a pin taken before the swap would hold
        # the row at the width of labels that no longer exist. Only callbacks
        # that opt in re-run here — pages without a slice row keep their exact
        # previous callback sequence, and with it their byte-identical output.
        for callback in self._layout_callbacks:
            if getattr(callback, "runs_after_tick_density", False):
                callback()
        if app is not None:
            # Two drains, and the second one is load-bearing for stacked
            # subplots: an AxisItem only learns its true height once its tick
            # strings have been measured in a paint, and
            # ``settle_subplot_layout`` sizes the shared bottom row from
            # ``bottom_axis.height()``. Without this second pass the axis
            # QPicture recorded here does not match a fresh recording of the
            # settled geometry, which the subplot export-determinism test in
            # tests/test_batch_render_qt.py catches. (For overlay pages the
            # second pass is a no-op — rendering is byte-identical without it.)
            # The rebind below is cheap: it is keyed on the effective bucket
            # width, so it only recomputes when bucketing actually changed.
            app.processEvents()
            layout.invalidate()
            layout.activate()
            self._bind_time_display_envelopes()
            app.processEvents()

    def _fit_axis_labels(self) -> None:
        """Shrink a Y-axis label that is longer than its own panel is tall.

        The left/right axis labels are drawn rotated, so their text length eats
        panel *height*. A tall page split into eight panels leaves ~115px each,
        which the report text scale can outgrow — and two neighbouring labels
        that each overflow their panel collide. Shrink only the offending
        label; ticks, titles and the other panels keep the requested size.
        """
        for plot in self.plots:
            try:
                available = float(plot.vb.sceneBoundingRect().height())
            except Exception:
                continue
            if available <= 1.0:
                continue
            for side in ("left", "right"):
                axis = plot.getAxis(side)
                if axis is None or not axis.isVisible():
                    continue
                label = getattr(axis, "label", None)
                if label is None or not str(axis.labelText or "").strip():
                    continue
                self._shrink_label_to_fit(label, available - 2.0)

    @staticmethod
    def _shrink_label_to_fit(label, available: float) -> None:
        point_size = float(label.font().pointSizeF())
        for _attempt in range(12):
            if float(label.boundingRect().width()) <= available or point_size <= 6.0:
                return
            point_size = max(6.0, point_size - 1.0)
            label.setFont(chart_font(point_size))

    def _apply_tick_density(self) -> None:
        """Pin every value axis to the recipe's requested number of divisions.

        pyqtgraph's adaptive tick chooser targets on-screen chart widths, which
        leaves a 1920px report page with ~9 X labels no matter how much room
        there is. Each axis is pinned from its own realized view range, so a
        manually entered range keeps its exact bounds.
        """
        metrics = QFontMetricsF(chart_font(self.theme.axis_font_pt))
        for plot in self.plots:
            for side, divisions, index in (
                ("bottom", self.style.tick_density_x, 0),
                ("left", self.style.tick_density_y, 1),
                ("right", self.style.tick_density_y, 1),
            ):
                axis = plot.getAxis(side)
                if axis is None or not axis.isVisible():
                    continue
                if not axis.style.get("showValues", True):
                    # Stacked subplots hide values on every axis but the
                    # bottom one; the analysis frame does the same for its
                    # decorative top/right edges.
                    continue
                view = axis.linkedView()
                if view is None:
                    continue
                try:
                    lo, hi = view.viewRange()[index]
                except Exception:
                    continue
                ticks = self._fit_axis_ticks(
                    axis, float(lo), float(hi), divisions, metrics, index == 0
                )
                if ticks is None:
                    continue
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([ticks, []])

    @staticmethod
    def _axis_extent_px(axis, horizontal: bool) -> float:
        try:
            rect = axis.boundingRect()
        except Exception:
            return 0.0
        return float(rect.width() if horizontal else rect.height())

    def _fit_axis_ticks(
        self, axis, lo, hi, divisions, metrics, horizontal: bool
    ):
        """Return ``[(value, label), …]`` coarsened until the labels fit."""
        per_div, values = nice_ticks_within(lo, hi, divisions)
        if per_div is None or len(values) < 2:
            return None
        extent = self._axis_extent_px(axis, horizontal)
        for _attempt in range(6):
            labels = [_fmt_tick(value, per_div) for value in values]
            if extent <= 1.0 or self._labels_fit(labels, metrics, extent, horizontal):
                return list(zip((float(value) for value in values), labels))
            coarser, values = coarsen_nice_step(per_div, lo, hi)
            if coarser is None or len(values) < 2:
                return None
            per_div = coarser
        return None

    @staticmethod
    def _labels_fit(labels, metrics, extent: float, horizontal: bool) -> bool:
        if len(labels) < 2:
            return True
        if horizontal:
            needed = max(metrics.width(text) for text in labels) + 12.0
        else:
            needed = metrics.height() + 4.0
        return needed * len(labels) <= extent

    def texts(self) -> list[str]:
        values = [_text_of(item) for item in self.page_labels]
        for plot in self.plots:
            title = getattr(plot, "titleLabel", None)
            if title is not None and _text_of(title).strip():
                values.append(_text_of(title))
            for side in ("left", "right", "bottom", "top"):
                axis = plot.getAxis(side)
                label = getattr(axis, "label", None)
                if label is not None and _text_of(label).strip():
                    values.append(_text_of(label))
        for group in self.panel_text_items:
            for item in group:
                text = _text_of(item)
                if text.strip() and text not in values:
                    values.append(text)
        return values

    def adjacent_text_overlaps(self) -> list[tuple[int, int, str, str]]:
        overlaps = []
        panel_records: list[list[tuple[QRectF, str]]] = []
        for plot, items in zip(self.plots, self.panel_text_items):
            records: list[tuple[QRectF, str]] = []
            for item in items:
                rect = _visible_text_rect(item)
                if rect is not None:
                    records.append((rect, _text_of(item)))
            for side in ("left", "right", "bottom", "top"):
                records.extend(_axis_tick_text_records(plot.getAxis(side)))
            panel_records.append(records)
        for index in range(len(self.panel_text_items) - 1):
            upper = panel_records[index]
            lower = panel_records[index + 1]
            for rect_a, text_a in upper:
                for rect_b, text_b in lower:
                    intersection = rect_a.intersected(rect_b)
                    if intersection.width() > 0.5 and intersection.height() > 0.5:
                        overlaps.append(
                            (index, index + 1, text_a, text_b)
                        )
        return overlaps

    def plot_scene_rect(self) -> QRectF:
        if not self.plots:
            return QRectF()
        rect = QRectF(self.plots[0].sceneBoundingRect())
        for plot in self.plots[1:]:
            rect = rect.united(plot.sceneBoundingRect())
        return rect

    def plot_rect_in_widget(self) -> QRect:
        scene_rect = self.plot_scene_rect()
        viewport_rect = self.widget.mapFromScene(scene_rect).boundingRect()
        origin = self.widget.viewport().mapTo(self.widget, QPoint(0, 0))
        viewport_rect.translate(origin)
        return viewport_rect.intersected(self.widget.rect())

    def plot_ink_pixel_count(self) -> int:
        image = QImage(
            self.options.width_px,
            self.options.height_px,
            QImage.Format_ARGB32_Premultiplied,
        )
        image.fill(self.theme.background)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.widget.render(painter)
        painter.end()
        crop = image.copy(self.plot_rect_in_widget()).convertToFormat(
            QImage.Format_RGBA8888
        )
        ptr = crop.bits()
        ptr.setsize(crop.byteCount())
        pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(
            crop.height(), crop.width(), 4
        )
        background = np.array(
            [
                self.theme.background.red(),
                self.theme.background.green(),
                self.theme.background.blue(),
                self.theme.background.alpha(),
            ],
            dtype=np.uint8,
        )
        return int(np.count_nonzero(np.any(pixels != background, axis=2)))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.widget.close()
        self.widget.deleteLater()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()


class _SceneBuilder:
    def __init__(
        self,
        *,
        options: BatchRenderOptions,
        context: BatchRenderContext,
        params: Mapping[str, Any],
        theme: RenderTheme,
        style: RenderStyle | None = None,
    ):
        self.options = options
        self.context = context
        self.params = dict(params)
        self.theme = theme
        self.style = style or render_style_from_params(self.params)
        self.widget = self._new_widget()
        self.plots: list[Any] = []
        self.curves: list[Any] = []
        self.auxiliary_views: list[Any] = []
        self.page_labels: list[Any] = []
        self.panel_titles: list[str] = []
        self.panel_text_items: list[tuple[Any, ...]] = []
        self.layout_callbacks: list[Any] = []
        self.sync_callbacks: list[Any] = []
        self.time_curve_bindings: list[_TimeCurveBinding] = []
        self.legend = None
        self.image_item = None
        self.colorbar = None
        self.display_matrix = None
        self.heatmap_lut = None
        self.heatmap_levels = None
        self.heatmap_rect = None
        self.slice_plan = None
        self.slice_plot = None
        self.slice_curves: list[Any] = []
        self.slice_marker_lines: list[Any] = []
        self.slice_legend = None
        self._color_index = 0
        self._series_colors: dict[str, str] = {}

    def _new_widget(self) -> pg.GraphicsLayoutWidget:
        widget = pg.GraphicsLayoutWidget()
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        widget.setFrameShape(QFrame.NoFrame)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget.setFocusPolicy(Qt.NoFocus)
        widget.setStyleSheet("border: 0; background: transparent;")
        widget.viewport().setAutoFillBackground(False)
        widget.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        if self.theme.name == "transparent":
            widget.setAttribute(Qt.WA_TranslucentBackground, True)
            widget.setBackground(None)
        else:
            widget.setBackground(self.theme.background)
        # Extra right breathing room protects the final right-axis tick/label
        # from clipping in dual-Y report pages (the crop is not the authority;
        # the full batch PNG must retain the complete axis).
        widget.ci.setContentsMargins(12, 10, 28, 10)
        widget.ci.setSpacing(2)
        return widget

    def _new_plot(self, row: int, *, grid_alpha: float | None = None):
        plot = self.widget.addPlot(row=row, col=0)
        hide_native_auto_button(plot)
        plot.hideButtons()
        plot.setMenuEnabled(False)
        plot.vb.setMenuEnabled(False)
        plot.setMouseEnabled(x=False, y=False)
        plot.vb.setMouseEnabled(x=False, y=False)
        plot.vb.setBorder(pg.mkPen(self.theme.axis, width=1.0))
        show_major_grid_left_bottom_only(
            plot,
            alpha=self.theme.grid_alpha if grid_alpha is None else grid_alpha,
        )
        for side in ("left", "right", "bottom", "top"):
            axis = plot.getAxis(side)
            axis.setPen(pg.mkPen(self.theme.axis, width=1.0))
            axis.setTextPen(pg.mkPen(self.theme.muted))
            axis.setStyle(maxTickLevel=0)
            axis.enableAutoSIPrefix(False)
            apply_axis_font(axis, self.theme.axis_font_pt)
        plot.hideAxis("right")
        plot.hideAxis("top")
        self.plots.append(plot)
        return plot

    def _apply_legend_font(self, legend) -> None:
        """Keep legend entries on the same text scale as the axes."""
        try:
            legend.setLabelTextSize(f"{self.theme.axis_font_pt:g}pt")
        except Exception:
            pass

    def _apply_analysis_frame(self, plot) -> None:
        """Match the existing full neutral-axis frame."""

        plot.vb.setBorder(None)
        plot.vb.border = None
        for side in ("top", "right"):
            plot.showAxis(side)
            axis = plot.getAxis(side)
            axis.setStyle(showValues=False, tickLength=0, maxTickLevel=0)
            axis.setLabel("")
            axis.setGrid(False)
        plot.getAxis("top").setHeight(1)
        plot.getAxis("right").setWidth(1)

    def _register_bottom_label_spacing(self, plot, *, overhang: bool = True) -> None:
        """Give this panel's x-axis title air, on every layout pass."""

        reposition = _space_bottom_axis_label(
            plot, self.theme.axis_font_pt, overhang=overhang,
        )
        if reposition is not None:
            self.layout_callbacks.append(reposition)

    def _next_pen(self, linestyle: str, *, fft=False, color_key: str | None = None):
        if fft:
            color = self.theme.fft_line
        elif color_key is not None and color_key in self._series_colors:
            color = self._series_colors[color_key]
        else:
            color = SERIES_COLORS[self._color_index % len(SERIES_COLORS)]
            self._color_index += 1
            if color_key is not None:
                self._series_colors[color_key] = color
        style = Qt.DashLine if linestyle == "--" else Qt.SolidLine
        pen = pg.mkPen(
            color=color,
            width=self.options.line_width,
            style=style,
        )
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        return pen

    def _add_curve(
        self,
        owner,
        plot,
        item: BatchSeries,
        spec: BatchTimeFigureSpec,
    ):
        label = str(item.label)
        normalized = label.casefold()
        color_key = "__dataframe_source__" if normalized in {
            "original", "filtered"
        } else None
        for suffix in (" · original", " · filtered"):
            if normalized.endswith(suffix):
                color_key = label[: -len(suffix)]
                break
        x_values = _time_x(item, spec)
        profile = classify_render_profile(
            x_values,
            item.y,
            source_revision_for(x_values, item.y),
        )
        # Curves stay aliased here on purpose. Smoothing is the exporter's job
        # (_export.py supersamples the whole page), and pyqtgraph's per-curve
        # antialiasing costs whatever the samples happen to look like — it
        # drops PlotCurveItem's drawLines fast path, which measured 15x slower
        # than supersampling on a five-panel channel-vs-channel page.
        curve = pg.PlotDataItem(
            pen=self._next_pen(item.linestyle, color_key=color_key),
            antialias=False,
            name=str(item.label),
        )
        owner.addItem(curve)
        self.curves.append(curve)
        self.time_curve_bindings.append(
            _TimeCurveBinding(
                curve=curve,
                plot=plot,
                x=x_values,
                y=item.y,
                profile=profile,
                mode=spec.layout,
            )
        )
        return curve

    def _add_time_panel(
        self,
        *,
        row: int,
        panel_series: tuple[BatchSeries, ...],
        spec: BatchTimeFigureSpec,
        title: str,
        bottom: bool,
        add_legend: bool,
    ):
        units = _first_appearance_units(panel_series, "unit")
        if len(units) > 2:
            raise ValueError("time figure spec supports at most two y units")
        if (
            len(units) == 2
            and not bool(self.params.get("y_auto", True))
            and _valid_pair(self.params.get("y_min"), self.params.get("y_max"))
        ):
            raise ValueError("manual y limits are not supported with dual y units")
        plot = self._new_plot(row)
        title_item = None
        if title:
            # Keep panel semantics without consuming a separate PlotItem title
            # row. The single-file TimeDomain subplot uses an inside label for
            # dense stacks; matching that geometry keeps every ViewBox's
            # effective height and auto-range padding aligned.
            title_item = pg.TextItem(
                text=str(title),
                color=self.theme.text,
                anchor=(0, 0),
                fill=pg.mkBrush(self.theme.plot_background.red(),
                                self.theme.plot_background.green(),
                                self.theme.plot_background.blue(), 220),
            )
            title_item.setFont(chart_font(self.theme.panel_title_font_pt))
            plot.scene().addItem(title_item)
            title_item.setZValue(1000)

            def position_title(*_args, _plot=plot, _item=title_item) -> None:
                rect = _plot.vb.sceneBoundingRect()
                _item.setPos(rect.left() + 4.0, rect.top() + 3.0)

            plot.vb.sigResized.connect(position_title)
            self.layout_callbacks.append(position_title)
        self.panel_titles.append(str(title))
        plot.setLabel("left", _linear_amplitude_label(units[0] if units else ""))
        plot.setLabel("bottom", spec.x_label if bottom else "")
        if bottom:
            self._register_bottom_label_spacing(plot)
        if not bottom:
            bottom_axis = plot.getAxis("bottom")
            bottom_axis.setStyle(showValues=False, tickLength=0, maxTickLevel=0)
            bottom_axis.setHeight(1)
        owners = {units[0]: plot.vb} if units else {}
        right_axis = None
        if len(units) == 2:
            plot.showAxis("right")
            right_axis = plot.getAxis("right")
            right_axis.setLabel(_linear_amplitude_label(units[1]))
            apply_axis_font(right_axis, self.theme.axis_font_pt)
            right_view = pg.ViewBox(enableMenu=False)
            right_view.setMouseEnabled(x=False, y=False)
            plot.scene().addItem(right_view)
            right_axis.linkToView(right_view)
            right_view.setXLink(plot.vb)
            self.auxiliary_views.append(right_view)
            owners[units[1]] = right_view

            def sync_right(
                *_args, _plot=plot, _view=right_view
            ) -> None:
                _view.setGeometry(_plot.vb.sceneBoundingRect())
                _view.linkedViewChanged(_plot.vb, _view.XAxis)

            plot.vb.sigResized.connect(sync_right)
            self.layout_callbacks.append(sync_right)

        local_curves = []
        curves_by_key = {}
        for item in panel_series:
            curve = self._add_curve(owners[item.unit], plot, item, spec)
            local_curves.append(curve)
            curves_by_key[item.series_key] = curve

        if units and local_curves and not title:
            left_color = local_curves[0].opts["pen"].color().name()
            plot.getAxis("left").setLabel(
                _linear_amplitude_label(units[0]), color=left_color
            )
            if right_axis is not None:
                right_index = next(
                    index
                    for index, item in enumerate(panel_series)
                    if item.unit == units[1]
                )
                right_color = local_curves[right_index].opts["pen"].color().name()
                right_axis.setLabel(
                    _linear_amplitude_label(units[1]), color=right_color
                )
                right_axis.setPen(pg.mkPen(right_color, width=1.0))
                right_axis.setTextPen(pg.mkPen(right_color))

        if bool(self.params.get("y_auto", True)) and len(panel_series) > 1:
            # Existing TimeDomain semantics differ by overlay shape: the main
            # dual-Y view remains auto-ranged while auxiliary axes are snapped
            # to the shared nice graticule; a raw+filtered companion pair
            # shares one main view which is itself snapped.
            nice_targets = []
            if len(units) == 1:
                same_axis_values = _finite_values(
                    np.concatenate([item.y for item in panel_series])
                )
                nice_targets.append(
                    (plot.vb, plot.getAxis("left"), same_axis_values)
                )
            elif len(units) == 2 and right_axis is not None:
                nice_targets.append((owners[units[1]], right_axis, None))
                primary_values = np.concatenate(
                    [item.y for item in panel_series if item.unit == units[0]]
                )
                finite_primary = _finite_values(primary_values)
                if finite_primary.size:
                    def settle_primary(
                        *_args,
                        _view=plot.vb,
                        _axis=plot.getAxis("left"),
                        _values=finite_primary,
                        _divisions=self.style.tick_density_y,
                    ) -> None:
                        bottom_y, top_y, ticks = _frame_to_nice(
                            float(np.min(_values)), float(np.max(_values)), _divisions
                        )
                        per_div = (top_y - bottom_y) / _divisions
                        _view.enableAutoRange(axis="y", enable=False)
                        _view.setYRange(bottom_y, top_y, padding=0)
                        _axis.setTicks(
                            [[(value, _fmt_tick(value, per_div)) for value in ticks], []]
                        )

                    self.sync_callbacks.append(settle_primary)
            for view, axis, values in nice_targets:
                def settle_nice(
                    *_args,
                    _view=view,
                    _axis=axis,
                    _values=values,
                    _divisions=self.style.tick_density_y,
                ) -> None:
                    if _values is None or not _values.size:
                        _view.enableAutoRange(axis="y", enable=True)
                        _view.updateAutoRange()
                        lo, hi = _view.viewRange()[1]
                    else:
                        lo = float(np.min(_values))
                        hi = float(np.max(_values))
                        pad = (hi - lo) * 0.05 if hi > lo else abs(lo) * 0.05 or 1.0
                        lo, hi = lo - pad, hi + pad
                    bottom_y, top_y, ticks = _frame_to_nice(lo, hi, _divisions)
                    per_div = (top_y - bottom_y) / _divisions
                    _view.enableAutoRange(axis="y", enable=False)
                    _view.setYRange(bottom_y, top_y, padding=0)
                    _axis.setStyle(maxTickLevel=0)
                    _axis.setTicks(
                        [[(value, _fmt_tick(value, per_div)) for value in ticks], []]
                    )

                self.sync_callbacks.append(settle_nice)

        if add_legend and local_curves:
            legend = plot.addLegend(offset=(10, 8))
            legend.setBrush(pg.mkBrush(self.theme.legend_background))
            legend.setPen(pg.mkPen(self.theme.grid, width=0.8))
            self._apply_legend_font(legend)
            for curve, item in zip(local_curves, panel_series):
                legend.addItem(curve, str(item.label))
            self.legend = legend

        statistic_items = self._add_time_statistics(
            plot, spec, panel_series[0].panel if panel_series else 0, curves_by_key,
        )

        group = [plot.getAxis("left").label]
        if title_item is not None:
            group.append(title_item)
        if right_axis is not None:
            group.append(right_axis.label)
        if bottom:
            group.append(plot.getAxis("bottom").label)
        group.extend(statistic_items)
        self.panel_text_items.append(tuple(group))
        return plot

    def _add_time_statistics(self, plot, spec, panel, curves_by_key):
        """Paint precomputed statistic rows or one pane-local diagnostic card."""
        diagnostic = next((item for item in spec.diagnostics if item.panel == panel), None)
        rows = tuple(item for item in spec.statistics if item.panel == panel)
        if diagnostic is None and not rows:
            return ()
        scale = float(self.theme.axis_font_pt) / 12.0
        title_pt = self.theme.axis_font_pt * 1.04
        body_pt = self.theme.axis_font_pt * 0.84
        muted_pt = self.theme.axis_font_pt * 0.76
        if diagnostic is not None:
            text = (
                f'<div style="font-size:{title_pt:.2f}pt; font-weight:600; color:#991b1b;">{diagnostic.title}</div>'
                '<div style="height:4px;"></div>'
                f'<div style="font-size:{body_pt:.2f}pt; color:#7f1d1d;">{diagnostic.message}</div>'
                f'<div style="font-size:{muted_pt:.2f}pt; color:#b91c1c; padding-top:3px;">{diagnostic.suggestion}</div>'
            )
            card = _StatisticsCard(
                text,
                content_width=360.0 * scale,
                body_font_pt=body_pt,
                background=QColor(255, 247, 247, 242),
                border=QColor("#fecaca"),
                text_color=QColor("#7f1d1d"),
            )
        else:
            chart_config = self.params.get("chart_statistics") or {}
            metrics = tuple(chart_config.get("metrics") or ("max", "min", "mean"))
            columns = tuple(
                (key, title, attribute)
                for key, title, attribute in (
                    ("max", "最大值", "maximum"),
                    ("min", "最小值", "minimum"),
                    ("mean", "样本平均", "mean"),
                )
                if key in metrics
            )
            all_x = [
                value for item in rows for value in (item.x_min, item.x_max)
                if value is not None
            ]
            x_unit = next(
                (item.x_unit for item in spec.series if item.x_unit), "s",
            )
            # The card used to show only the *actual* data span, which looks
            # identical whether that span came from "auto" or from a custom
            # request that silently failed to apply — the exact ambiguity
            # that let a ±80 mm request produce a full-range statistic
            # without anyone noticing (design D-D1). Spell out which mode
            # produced the numbers, then still report the actual span.
            range_mode = str(
                chart_config.get("range_mode", "full") or "full"
            ).strip().lower()
            requested_lo = requested_hi = None
            if range_mode == "custom":
                try:
                    requested_lo = float(chart_config["x_min"])
                    requested_hi = float(chart_config["x_max"])
                except (KeyError, TypeError, ValueError):
                    requested_lo = requested_hi = None
            mode_fact = (
                f"设定 {requested_lo:.4g} ~ {requested_hi:.4g} {x_unit}"
                if requested_lo is not None and requested_hi is not None
                else "全时段"
            )
            actual_fact = (
                f"实际 {min(all_x):.4g} ~ {max(all_x):.4g} {x_unit}"
                if all_x else ""
            )
            range_fact = "　" + " · ".join(
                part for part in (mode_fact, actual_fact) if part
            )
            header_cells = "".join(
                f'<th style="padding:1px 5px; text-align:right; white-space:nowrap; '
                f'color:{"#b91c1c" if key == "max" else "#15803d" if key == "min" else "#64748b"};">{title}</th>'
                for key, title, _attr in columns
            )
            row_cells = []
            for item in rows[:6]:
                def fmt(value):
                    return "—" if value is None else f"{value:.4g}"
                values = "".join(
                    '<td style="padding:2px 6px; text-align:right;">'
                    f'{fmt(getattr(item, attribute))}</td>'
                    for _key, _title, attribute in columns
                )
                row_cells.append(
                    '<tr>'
                    '<td style="padding:2px 5px; text-align:left; white-space:nowrap; font-weight:600; color:#334155;">'
                    f'{item.direction or item.branch_label}</td>{values}'
                    '<td style="padding:2px 1px 2px 5px; text-align:right; white-space:nowrap; color:#64748b;">'
                    f'N={item.sample_count}</td></tr>'
                )
            if len(rows) > 6:
                row_cells.append(
                    '<tr><td colspan="5" style="padding:2px 6px;">'
                    f'+{len(rows) - 6} 条</td></tr>'
                )
            text = (
                f'<div style="font-size:{title_pt:.2f}pt; font-weight:600; color:#172033; padding-bottom:4px;">图内统计'
                f'<span style="font-size:{muted_pt:.2f}pt; font-weight:400; color:#64748b;">{range_fact}</span></div>'
                '<table cellspacing="0" cellpadding="0" '
                f'style="font-size:{body_pt:.2f}pt; border-collapse:collapse; color:#172033;">'
                '<tr><th style="padding:1px 5px; text-align:left; white-space:nowrap; color:#64748b;">路径</th>'
                f'{header_cells}'
                '<th style="padding:1px 1px 1px 5px; text-align:right; color:#64748b;">样本数</th></tr>'
                f'{"".join(row_cells)}</table>'
            )
            card = _StatisticsCard(
                text,
                content_width=342.0 * scale,
                body_font_pt=body_pt,
                background=QColor(255, 255, 255, 238),
                border=QColor("#d8e0eb"),
                text_color=QColor("#172033"),
            )
            for item in rows:
                curve = curves_by_key.get(item.series_key)
                if curve is None:
                    continue
                marker_specs = []
                if "max" in metrics and item.argmax_x is not None and item.maximum is not None:
                    marker_specs.append(((item.argmax_x, item.maximum), "#dc2626"))
                if "min" in metrics and item.argmin_x is not None and item.minimum is not None:
                    marker_specs.append(((item.argmin_x, item.minimum), "#16a34a"))
                # Solid dot with a white keyline, matching the single-file
                # cursor readout (ui/pg_canvas/cursor.py). The near-white
                # filled ring this replaced read as a smudge once the export's
                # supersampling shrank it.
                for point, color in marker_specs:
                    marker = pg.ScatterPlotItem(
                        symbol="o", size=11.0 * scale,
                        pen=pg.mkPen("#ffffff", width=1.6 * scale),
                        brush=pg.mkBrush(color),
                    )
                    marker.addPoints([{"pos": point}])
                    marker.setZValue(1200)
                    curve.getViewBox().addItem(marker)
        card.setZValue(2000)
        plot.scene().addItem(card)

        def position_card(*_args, _plot=plot, _card=card):
            rect = _plot.vb.sceneBoundingRect()
            _card.setPos(
                rect.right() - 8.0 - _card.boundingRect().width(),
                rect.top() + 8.0,
            )

        plot.vb.sigResized.connect(position_card)
        self.layout_callbacks.append(position_card)
        return (card,)

    def _apply_time_ranges(
        self, spec: BatchTimeFigureSpec, active: tuple[BatchSeries, ...]
    ) -> None:
        finite_x = [
            values[np.isfinite(values)]
            for values in (_time_x(item, spec) for item in active)
            if np.any(np.isfinite(values))
        ]
        if not bool(self.params.get("x_auto", True)) and _valid_pair(
            self.params.get("x_min"), self.params.get("x_max")
        ):
            x_range = (float(self.params["x_min"]), float(self.params["x_max"]))
        elif finite_x:
            all_x = np.concatenate(finite_x)
            x_range = (float(np.min(all_x)), float(np.max(all_x)))
        else:
            x_range = (0.0, 1.0)
        for plot in self.plots:
            plot.setXRange(*x_range, padding=0)

        if len(_first_appearance_units(active, "unit")) < 2 and not bool(
            self.params.get("y_auto", True)
        ) and _valid_pair(self.params.get("y_min"), self.params.get("y_max")):
            for plot in self.plots:
                plot.setYRange(
                    float(self.params["y_min"]),
                    float(self.params["y_max"]),
                    padding=0,
                )

    def build_time(self, data) -> int:
        if isinstance(data, BatchTimeFigureSpec):
            spec = data
        else:
            frame = _require_dataframe(data, ("time_s", "series", "value"), "time")
            items = []
            for name, group in frame.groupby("series", sort=False):
                items.append(
                    BatchSeries(
                        x=group["time_s"].to_numpy(dtype=float),
                        y=group["value"].to_numpy(dtype=float),
                        label=str(name),
                        unit=self.context.unit,
                        linestyle="--" if str(name) == "filtered" else "-",
                    )
                )
            spec = BatchTimeFigureSpec(tuple(items))
        active = tuple(item for item in spec.series if item.x.size)
        _validate_time_spec_units(active)
        if spec.layout == "subplot":
            panel_ids = tuple(dict.fromkeys(item.panel for item in active)) or (0,)
            for index, panel in enumerate(panel_ids):
                panel_series = tuple(item for item in active if item.panel == panel)
                title = (
                    str(spec.panel_titles[panel])
                    if panel < len(spec.panel_titles)
                    else (str(panel_series[0].label) if panel_series else "")
                )
                self._add_time_panel(
                    row=3 + index,
                    panel_series=panel_series,
                    spec=spec,
                    title=title,
                    bottom=index == len(panel_ids) - 1,
                    add_legend=False,
                )
                self.widget.ci.layout.setRowStretchFactor(3 + index, 1)
                self.widget.ci.layout.setRowPreferredHeight(3 + index, 100.0)

            def settle_subplot_layout(*_args) -> None:
                layout = self.widget.ci.layout
                for row in range(3, 3 + len(panel_ids)):
                    layout.setRowStretchFactor(row, 1)
                    layout.setRowPreferredHeight(row, 100.0)
                layout.invalidate()
                layout.activate()
                # Only the last row carries the shared X axis, so an equal row
                # height leaves its plot area shorter than every panel above
                # it. Pay for the axis out of the row's preferred height so all
                # panels end up with the same drawing area — and so the rotated
                # Y label of the bottom panel has as much room as the others.
                last_plot = self.plots[-1]
                bottom_axis = last_plot.getAxis("bottom")
                axis_height = float(bottom_axis.height()) if bottom_axis else 0.0
                if axis_height > 1.0:
                    layout.setRowPreferredHeight(
                        3 + len(panel_ids) - 1, 100.0 + axis_height
                    )
                    layout.invalidate()
                    layout.activate()
                left_axes = [plot.getAxis("left") for plot in self.plots]
                for axis in left_axes:
                    axis.setWidth(None)
                max_width = max((float(axis.width()) for axis in left_axes), default=0.0)
                if max_width > 0.0:
                    for axis in left_axes:
                        axis.setWidth(max_width)
                layout.invalidate()
                layout.activate()

            self.layout_callbacks.append(settle_subplot_layout)
            footer_row = 3 + len(panel_ids)
        else:
            self._add_time_panel(
                row=3,
                panel_series=active,
                spec=spec,
                title="",
                bottom=True,
                add_legend=len(active) > 1,
            )
            self.widget.ci.layout.setRowStretchFactor(3, 1)
            footer_row = 4
        self._apply_time_ranges(spec, active)
        return footer_row

    def build_fft(self, data) -> int:
        frame = _require_dataframe(data, ("frequency_hz", "amplitude"), "fft")
        x_values = frame["frequency_hz"].to_numpy(dtype=float)
        linear_values = frame["amplitude"].to_numpy(dtype=float)
        resolution = _reference_resolution(self.params)
        render_db = _render_in_db("fft", self.params)
        if render_db:
            y_values = _display_db_values(linear_values, resolution.value)
            y_label = db_reference.format_amplitude_label(
                resolution,
                weighting=str(self.params.get("weighting", "None")),
                output_scale="db",
            )
        else:
            y_values = linear_values
            y_label = _linear_amplitude_label(self.context.unit)
        plot = self._new_plot(3, grid_alpha=0.25)
        self._apply_analysis_frame(plot)
        plot.setLabel("bottom", "Frequency (Hz)")
        plot.setLabel("left", y_label)
        self._register_bottom_label_spacing(plot)
        # Aliased for the same reason as the time curves: the exporter
        # supersamples the page.
        curve = pg.PlotDataItem(
            x_values,
            y_values,
            pen=self._next_pen("-", fft=True),
            antialias=False,
            name=str(self.context.channel or "Channel"),
        )
        plot.addItem(curve)
        self.curves.append(curve)
        legend = plot.addLegend(offset=(8, 8))
        legend.setBrush(pg.mkBrush(self.theme.legend_background))
        legend.setPen(pg.mkPen(self.theme.grid, width=0.8))
        self._apply_legend_font(legend)
        legend.addItem(curve, str(self.context.channel or "Channel"))
        self.legend = legend
        finite_x = _finite_values(x_values)
        if not bool(self.params.get("x_auto", True)) and _valid_pair(
            self.params.get("x_min"), self.params.get("x_max")
        ):
            x_range = (float(self.params["x_min"]), float(self.params["x_max"]))
        elif finite_x.size:
            x_range = (float(np.min(finite_x)), float(np.max(finite_x)))
        else:
            x_range = (0.0, 1.0)
        plot.setXRange(*x_range, padding=0)
        if not bool(self.params.get("y_auto", True)) and _valid_pair(
            self.params.get("y_min"), self.params.get("y_max")
        ):
            plot.setYRange(
                float(self.params["y_min"]),
                float(self.params["y_max"]),
                padding=0,
            )
        elif render_db:
            plot.setYRange(*_auto_db_line_limits(y_values), padding=0)
        else:
            plot.enableAutoRange(axis="y", enable=True)
        self.widget.ci.layout.setRowStretchFactor(3, 1)
        self.panel_titles.append("")
        self.panel_text_items.append(
            (plot.getAxis("left").label, plot.getAxis("bottom").label)
        )
        return 4

    def build_heatmap(
        self,
        kind: str,
        data,
        warnings_out: list[str] | None,
    ) -> int:
        matrix, x_values, y_values, x_name, y_name, metadata = _extract_heatmap(
            data
        )
        plan = plan_heatmap_slice(x_values, y_values, self.params)
        self.slice_plan = plan
        render_db = _render_in_db(kind, self.params)
        if render_db:
            resolution = _reference_resolution(self.params)
            # Match the foreground canvas: the display matrix retains the analyzer's
            # complete dB result; only ColorBarItem levels clamp colours.
            display_matrix = np.asarray(
                SpectrogramAnalyzer.amplitude_to_db(
                    matrix, reference=resolution.value
                ),
                dtype=float,
            )
            colorbar_label = db_reference.format_amplitude_label(
                resolution,
                weighting=str(self.params.get("weighting", "None")),
                output_scale="db",
            )
        else:
            display_matrix = np.asarray(matrix, dtype=float)
            colorbar_label = _linear_amplitude_label(self.context.unit)

        x_extent = _coverage_extent(
            x_values,
            start=metadata.get("coverage_start"),
            end=metadata.get("coverage_end"),
        )
        y_extent = _data_axis_extent(y_values)
        rect = QRectF(
            x_extent[0],
            y_extent[0],
            x_extent[1] - x_extent[0],
            y_extent[1] - y_extent[0],
        )
        manual_z = bool(
            not bool(self.params.get("z_auto", True))
            and _valid_pair(
                self.params.get("z_floor"), self.params.get("z_ceiling")
            )
        )
        if manual_z:
            levels = (
                float(self.params["z_floor"]),
                float(self.params["z_ceiling"]),
            )
        elif render_db:
            levels = _auto_db_color_limits(display_matrix)
        else:
            levels = _finite_limits(display_matrix)

        color_map, lut = _resolve_heatmap_colormap(self.params, warnings_out)
        plot = self._new_plot(3, grid_alpha=0.25)
        self._apply_analysis_frame(plot)
        plot.setLabel("bottom", _axis_label(x_name))
        plot.setLabel("left", _axis_label(y_name))
        self._register_bottom_label_spacing(plot, overhang=not plan.enabled)

        image_item = _SmoothImageItem(axisOrder="row-major")
        interpolation = str(self.params.get("interp", "bilinear")).lower()
        image_item.set_smooth_transform(
            interpolation in {"bilinear", "bicubic", "hanning"}
        )
        image_item.setImage(display_matrix, autoLevels=False)
        image_item.setRect(rect)
        plot.addItem(image_item)

        colorbar = pg.ColorBarItem(
            values=levels,
            colorMap=color_map,
            label=colorbar_label,
            interactive=False,
            colorMapMenu=False,
        )
        colorbar.setImageItem(image_item, insert_in=plot)
        colorbar.setAcceptedMouseButtons(Qt.NoButton)
        colorbar.vb.setMouseEnabled(x=False, y=False)
        colorbar.vb.setMenuEnabled(False)
        for side in ("left", "right"):
            axis = colorbar.getAxis(side)
            axis.setPen(pg.mkPen(self.theme.axis, width=1.0))
            axis.setTextPen(pg.mkPen(self.theme.muted))
            axis.enableAutoSIPrefix(False)
            axis.setStyle(maxTickLevel=0)
            apply_axis_font(axis, self.theme.axis_font_pt)

        if not bool(self.params.get("x_auto", True)) and _valid_pair(
            self.params.get("x_min"), self.params.get("x_max")
        ):
            main_x_range = (
                float(self.params["x_min"]),
                float(self.params["x_max"]),
            )
        else:
            main_x_range = tuple(float(value) for value in x_extent)
        plot.setXRange(*main_x_range, padding=0)
        if not bool(self.params.get("y_auto", True)) and _valid_pair(
            self.params.get("y_min"), self.params.get("y_max")
        ):
            main_y_range = (
                float(self.params["y_min"]),
                float(self.params["y_max"]),
            )
        else:
            main_y_range = tuple(float(value) for value in y_extent)
        plot.setYRange(*main_y_range, padding=0)

        self.panel_titles.append("")
        self.panel_text_items.append(
            (
                plot.getAxis("left").label,
                plot.getAxis("bottom").label,
                colorbar.getAxis("left").label,
            )
        )
        self.image_item = image_item
        self.colorbar = colorbar
        self.display_matrix = display_matrix
        self.heatmap_lut = lut
        self.heatmap_levels = tuple(float(value) for value in levels)
        self.heatmap_rect = QRectF(rect)

        if not plan.enabled:
            # Slice off: not one extra item, not one extra row. Existing
            # spectrogram presets must keep producing byte-identical PNGs.
            self.widget.ci.layout.setRowStretchFactor(3, 1)
            return 4

        palette = slice_palette(plan.axis)
        # The *fixed* dimension is the one the picks index into; the curve then
        # runs along the other one. See ``_slice_curve_values`` for the matrix
        # orientation this depends on.
        fixed_values = x_values if plan.axis == "time" else y_values
        fixed_unit = _axis_unit(x_name if plan.axis == "time" else y_name)
        curve_name = y_name if plan.axis == "time" else x_name
        curve_coords = np.asarray(
            y_values if plan.axis == "time" else x_values, dtype=float
        )
        curve_range = main_y_range if plan.axis == "time" else main_x_range

        # Marker lines on the image. Vertical when a time is fixed, horizontal
        # when a frequency/order is fixed. Each colour line rides on a wider
        # white one: under turbo a pure red or blue disappears entirely over
        # part of the map (design D16). Widths are fixed pixels tuned for the
        # 1920px page and do not scale with ``image_size``, exactly like
        # ``theme.axis`` (design D17).
        angle = 90.0 if plan.axis == "time" else 0.0
        for pick, color in zip(plan.picks, palette):
            for width, pen_color, depth in ((5.2, "#ffffff", 900.0), (2.6, color, 901.0)):
                line = pg.InfiniteLine(
                    pos=pick.value,
                    angle=angle,
                    movable=False,
                    pen=pg.mkPen(pen_color, width=width),
                )
                line.setZValue(depth)
                plot.addItem(line, ignoreBounds=True)
                self.slice_marker_lines.append(line)

        slice_plot = self._new_plot(4, grid_alpha=0.25)
        self._apply_analysis_frame(slice_plot)
        slice_plot.setLabel("bottom", _axis_label(curve_name))
        # One amplitude caliber for the whole page: the slice reads the same
        # display matrix the image does, so it reuses the colorbar's label.
        slice_plot.setLabel("left", colorbar_label)
        self._register_bottom_label_spacing(slice_plot, overhang=True)

        mask = _slice_visible_mask(curve_coords, *curve_range)
        visible_x = curve_coords[mask]
        visible_values = []
        # Design D-B6: 3+ overlaid curves in one 322px panel read as clutter
        # at full weight. Thinning (not fading — translucency on a white
        # background just goes grey and reads worse) buys back some
        # separation. Two curves keep the page's normal weight.
        curve_line_width = float(self.options.line_width)
        if len(plan.picks) >= 3:
            curve_line_width *= 0.85
        for pick, color in zip(plan.picks, palette):
            values = _slice_curve_values(display_matrix, plan.axis, pick.index)
            visible = np.asarray(values, dtype=float)[mask]
            visible_values.append(visible)
            curve = pg.PlotDataItem(
                visible_x,
                visible,
                pen=pg.mkPen(color, width=curve_line_width),
                antialias=False,
            )
            slice_plot.addItem(curve)
            self.slice_curves.append(curve)

        slice_plot.setXRange(*curve_range, padding=0)
        if manual_z:
            # A hand-entered z window survives verbatim — no nice rounding —
            # the same promise ``nice_ticks_within`` already makes for manual
            # axis ranges (design D20).
            slice_plot.setYRange(*self.heatmap_levels, padding=0)
        else:
            stacked = (
                np.concatenate(visible_values) if visible_values else np.empty(0)
            )
            bounds = _slice_amp_bounds(stacked)
            amp_range = (
                None
                if bounds is None
                else _nice_amp_range(*bounds, self.style.tick_density_y)
            )
            if amp_range is None:
                slice_plot.enableAutoRange(axis="y", enable=True)
            else:
                slice_plot.setYRange(*amp_range, padding=0)

        legend_title = _slice_dimension_title(plan, x_name, y_name)
        legend_title_pt = self.theme.axis_font_pt * 0.88
        legend_body_pt = self.theme.axis_font_pt * 0.84
        legend = _StatisticsCard(
            _slice_legend_html(
                plan,
                palette,
                title=legend_title,
                unit=fixed_unit,
                title_pt=legend_title_pt,
                body_pt=legend_body_pt,
            ),
            # Measured, not budgeted: a fixed 86 px could not hold ``1500.0 Hz``
            # and the surplus was painted past the page edge (design D-B3).
            content_width=_slice_legend_content_width(
                plan,
                title=legend_title,
                unit=fixed_unit,
                title_pt=legend_title_pt,
                body_pt=legend_body_pt,
            ),
            body_font_pt=legend_body_pt,
            background=QColor(255, 255, 255, 238),
            border=QColor("#d8e0eb"),
            text_color=QColor("#172033"),
        )
        legend.setZValue(2000)
        slice_plot.scene().addItem(legend)
        self.slice_legend = legend

        def position_legend(
            *_args, _plot=slice_plot, _bar=colorbar, _card=legend,
            _widget=self.widget,
        ):
            # The gutter the colorbar occupies is empty on the slice row — the
            # X-alignment spacer keeps it that way — so the legend costs zero
            # data area (design D18).
            rect = _plot.vb.sceneBoundingRect()
            try:
                left = float(_bar.sceneBoundingRect().left())
            except Exception:
                left = float(rect.right()) + _SLICE_LEGEND_GUTTER_GAP
            left = max(left, float(rect.right()) + 6.0)
            # The colorbar's left edge only bounds the card from one side, and
            # a card measured to its content can be wider than the colorbar.
            # The page margin is the edge that actually crops, so it wins.
            # Read per call, not captured: the widget is still at its default
            # size while the scene is being built and only reaches the export
            # size in ``show_and_settle``.
            limit = _page_right_limit(_widget) - float(
                _card.boundingRect().width()
            )
            _card.setPos(min(left, limit), rect.top())

        slice_plot.vb.sigResized.connect(position_legend)
        self.layout_callbacks.append(position_legend)
        self.layout_callbacks.append(
            _slice_alignment_callback(
                self.widget.ci.layout,
                plot,
                slice_plot,
                right_reserve=(
                    float(legend.boundingRect().width()) + _SLICE_LEGEND_GUTTER_GAP
                ),
            )
        )

        warning = _slice_clamp_warning(
            plan,
            float(np.min(fixed_values)),
            float(np.max(fixed_values)),
            fixed_unit,
        )
        if warning is not None and warnings_out is not None:
            warnings_out.append(warning)

        # 6 : 3 — the slice row carries up to four overlaid curves, so it needs
        # more than a token strip (design §5.1). QGraphicsGridLayout hands out
        # preferred height first and only shares the remainder by stretch, so
        # the ratio has to be stated twice to actually land (the same pairing
        # the stacked-subplot path uses).
        self.widget.ci.layout.setRowStretchFactor(3, 6)
        self.widget.ci.layout.setRowStretchFactor(4, 3)
        self.widget.ci.layout.setRowPreferredHeight(3, 600.0)
        self.widget.ci.layout.setRowPreferredHeight(4, 300.0)
        self.panel_titles.append("")
        self.panel_text_items.append(
            (
                slice_plot.getAxis("left").label,
                slice_plot.getAxis("bottom").label,
            )
        )
        self.slice_plot = slice_plot
        return 5

    def finish(self, *, kind: str, footer_row: int) -> BuiltBatchScene:
        footer = add_report_footer(
            self.widget,
            row=footer_row,
            context=self.context,
            theme=self.theme,
        )
        self.page_labels.append(footer)
        return BuiltBatchScene(
            widget=self.widget,
            plots=tuple(self.plots),
            curves=tuple(self.curves),
            auxiliary_views=tuple(self.auxiliary_views),
            page_labels=tuple(self.page_labels),
            panel_titles=tuple(self.panel_titles),
            panel_text_items=tuple(self.panel_text_items),
            legend=self.legend,
            options=self.options,
            theme=self.theme,
            style=self.style,
            image_item=self.image_item,
            colorbar=self.colorbar,
            display_matrix=self.display_matrix,
            heatmap_lut=self.heatmap_lut,
            heatmap_levels=self.heatmap_levels,
            heatmap_rect=self.heatmap_rect,
            slice_plan=self.slice_plan,
            slice_plot=self.slice_plot,
            slice_curves=tuple(self.slice_curves),
            slice_marker_lines=tuple(self.slice_marker_lines),
            slice_legend=self.slice_legend,
            _layout_callbacks=tuple(self.layout_callbacks),
            _sync_callbacks=tuple(self.sync_callbacks),
            _time_curve_bindings=tuple(self.time_curve_bindings),
        )


def build_batch_scene(
    payload,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> BuiltBatchScene:
    """Build one four-kind batch report scene without writing a file."""
    try:
        kind, data = payload
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be a (kind, data) pair") from exc
    kind = str(kind)
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unsupported batch render kind: {kind}")
    render_options = options or BatchRenderOptions()
    render_context = context or BatchRenderContext()
    render_params = dict(params or {})
    style = render_style_from_params(render_params)
    # Scale before the header/footer labels are added so page text and axis
    # text stay on one ruler.
    theme = scaled_fonts(render_theme(render_options.background), style.font_scale)
    builder = _SceneBuilder(
        options=render_options,
        context=render_context,
        params=render_params,
        theme=theme,
        style=style,
    )
    builder.page_labels.extend(
        add_report_header(
            builder.widget,
            kind=kind,
            params=render_params,
            context=render_context,
            theme=theme,
            extra_facts=(_rendered_db_fact(kind, render_params),),
        )
    )
    try:
        if kind == "time":
            footer_row = builder.build_time(data)
        elif kind == "fft":
            footer_row = builder.build_fft(data)
        else:
            footer_row = builder.build_heatmap(kind, data, warnings_out)
        return builder.finish(kind=kind, footer_row=footer_row)
    except BaseException:
        builder.widget.close()
        builder.widget.deleteLater()
        raise


__all__ = ["BuiltBatchScene", "build_batch_scene"]
