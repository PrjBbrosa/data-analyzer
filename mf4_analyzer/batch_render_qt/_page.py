"""Report-page labels, facts and footer composition."""
from __future__ import annotations

import html
from typing import Any, Mapping

import numpy as np

from ..batch_grouping import is_human_group
from ._fonts import chart_font
from ._models import BatchRenderContext
from ._theme import RenderTheme


_DEFAULT_METHOD = {
    "time": "Time",
    "fft": "FFT",
    "fft_time": "FFT vs Time",
    "frf": "FRF",
    "order_time": "Order",
}


def _elide(value: Any, limit: int) -> str:
    text = " ".join(("" if value is None else str(value)).split())
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"[:limit]
    return text[: limit - 1].rstrip() + "…"


def _first_present(mapping: Mapping[str, Any], *keys: str):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _format_fact_value(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        return f"{float(value):g}"
    return _elide(value, 20)


def _format_overlap(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _elide(value, 14)
    if np.isfinite(numeric) and 0.0 <= numeric <= 1.0:
        return f"{numeric * 100:g}%"
    return f"{numeric:g}"


def effective_fact_items(
    effective_facts: Mapping[str, Any], params: Mapping[str, Any]
) -> list[str]:
    facts = dict(params)
    facts.update(effective_facts)
    items: list[str] = []
    estimator = _first_present(facts, "estimator")
    if estimator not in (None, ""):
        items.append(str(estimator).upper())
    window = _first_present(facts, "window", "effective_window")
    if window not in (None, ""):
        items.append(f"window={_elide(window, 24)}")
    nfft = _first_present(
        facts, "nfft_effective", "effective_nfft", "nfft", "n_fft"
    )
    if nfft not in (None, ""):
        items.append(f"NFFT={_format_fact_value(nfft)}")
    weighting = _first_present(facts, "weighting", "frequency_weighting")
    if weighting not in (None, "", "None", "none"):
        items.append(f"weighting={_elide(weighting, 16)}")
    averaging = _first_present(
        facts, "averaging", "averaging_mode", "average_mode", "avg_mode"
    )
    if averaging not in (None, "", "None", "none"):
        items.append(f"averaging={_elide(averaging, 18)}")
    overlap = _first_present(facts, "overlap", "overlap_ratio")
    if overlap not in (None, ""):
        items.append(f"overlap={_format_overlap(overlap)}")
    actual_fs = _first_present(facts, "actual_fs", "effective_fs", "fs")
    segments = _first_present(facts, "segments", "segment_count")
    if segments not in (None, ""):
        items.append(f"segments={_format_fact_value(segments)}")
    if actual_fs not in (None, ""):
        items.append(f"Fs={_format_fact_value(actual_fs)} Hz")
    members = _first_present(facts, "members")
    if members not in (None, ""):
        return [*items[:5], f"members={_format_fact_value(members)}"]
    return items[:7]


def _add_label(widget, *, row, text, color, point_size, bold=False, justify="left"):
    item = widget.addLabel(
        html.escape(str(text)),
        row=row,
        col=0,
        color=color,
        size=f"{point_size:g}pt",
        bold=bold,
        justify=justify,
    )
    item.item.setFont(chart_font(point_size))
    return item


def add_report_header(
    widget,
    *,
    kind: str,
    params: Mapping[str, Any],
    context: BatchRenderContext,
    theme: RenderTheme,
    extra_facts: tuple[str, ...] = (),
) -> list:
    method = str(context.method).strip() or _DEFAULT_METHOD[kind]
    group_part = (
        _elide(context.group, 38) if is_human_group(context.group) else ""
    )
    identity = " · ".join(
        part
        for part in (
            _elide(context.source_display_name, 52),
            group_part,
        )
        if part
    )
    # The method name is redundant with the chart itself (the axes already say
    # whether this is time, spectrum or order), and on grouped renders — where
    # the context carries no single channel — it degenerated into a lone
    # lowercase ``time`` floating under the title.  Only the channel earns this
    # row; without one the row is not drawn at all.
    analysis = _elide(context.channel, 56)
    if not identity:
        identity = method
    labels = [
        _add_label(
            widget,
            row=0,
            text=identity,
            color=theme.text,
            point_size=theme.header_font_pt,
        ),
    ]
    if analysis:
        labels.append(
            _add_label(
                widget,
                row=1,
                text=analysis,
                color=theme.muted,
                point_size=theme.channel_font_pt,
            )
        )
    facts = effective_fact_items(context.effective_facts, params)
    facts.extend(str(value).strip() for value in extra_facts if str(value).strip())
    facts_text = _elide(" · ".join(facts), 170)
    if facts_text:
        labels.append(
            _add_label(
                widget,
                row=2,
                text=facts_text,
                color=theme.muted,
                point_size=theme.facts_font_pt,
            )
        )
    return labels


def add_report_footer(
    widget, *, row: int, context: BatchRenderContext, theme: RenderTheme
):
    footer = "TraceLab batch export"
    return _add_label(
        widget,
        row=row,
        text=footer,
        color=theme.subtle,
        point_size=theme.footer_font_pt,
        justify="right",
    )


def render_metadata(context: BatchRenderContext | None) -> dict[str, str]:
    context = context or BatchRenderContext()
    title = " · ".join(
        part
        for part in (
            str(context.source_display_name).strip(),
            str(context.channel).strip(),
            str(context.method).strip(),
        )
        if part
    ) or "TraceLab batch export"
    return {"Title": title, "Creator": "TraceLab batch renderer"}


__all__ = [
    "add_report_footer",
    "add_report_header",
    "effective_fact_items",
    "render_metadata",
]
