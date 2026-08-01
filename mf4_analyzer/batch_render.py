"""Headless image rendering for batch-analysis payloads.

The module deliberately uses Matplotlib's object-oriented Agg surface rather
than a process-global plotting state.  Numeric exports remain linear; dB
conversion and reference labelling are display-only concerns here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import matplotlib as mpl
import numpy as np
import pandas as pd
from matplotlib import font_manager, ft2font
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text

from . import db_reference
from .batch_image_options import BatchRenderOptions
from .signal.spectrogram import SpectrogramAnalyzer


_AUTO_SPAN_DB = 30.0
_AUTO_CEILING_PERCENTILE = 99.0
_DISPLAY_DEAD_SPAN_DB = 200.0
_EMPTY_DB_LEVEL = -200.0
_SUPPORTED_KINDS = frozenset({"time", "fft", "fft_time", "order_time"})
_CJK_CONTRACT_TEXT = "单帧振动加速度"
_CJK_FONT_CANDIDATES = (
    # macOS
    "PingFang SC",
    "PingFang HK",
    "Hiragino Sans GB",
    "Hiragino Sans",
    # Windows
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    # Linux and commonly bundled open fonts
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Noto Sans CJK JP",
    "WenQuanYi Micro Hei",
    "Source Han Sans SC",
    # Additional macOS fallbacks
    "Arial Unicode MS",
    "STHeiti",
    "Songti SC",
)


@dataclass(frozen=True)
class BatchRenderContext:
    """Task identity and effective facts rendered inside a batch figure."""

    source_display_name: str = ""
    group: str | int | None = None
    channel: str = ""
    unit: str = ""
    method: str = ""
    task_id: str = ""
    effective_facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effective_facts",
            MappingProxyType(
                {
                    str(key): _freeze_fact_value(value)
                    for key, value in dict(self.effective_facts).items()
                }
            ),
        )


@dataclass(frozen=True)
class BatchSeries:
    """One prepared time-domain curve for a batch figure."""

    x: np.ndarray
    y: np.ndarray
    label: str
    unit: str = ""
    x_unit: str = "s"
    linestyle: str = "-"
    panel: int = 0

    def __post_init__(self) -> None:
        x_values = np.asarray(self.x, dtype=float)
        y_values = np.asarray(self.y, dtype=float)
        if x_values.ndim != 1 or y_values.ndim != 1:
            raise ValueError("BatchSeries x and y must be one-dimensional")
        if x_values.size != y_values.size:
            raise ValueError("BatchSeries x and y must have equal lengths")
        if isinstance(self.panel, bool) or not isinstance(
            self.panel, (int, np.integer)
        ) or self.panel < 0:
            raise ValueError("BatchSeries panel must be a non-negative int")
        if self.linestyle not in {"-", "--"}:
            raise ValueError("BatchSeries linestyle must be '-' or '--'")
        object.__setattr__(self, "x", x_values)
        object.__setattr__(self, "y", y_values)
        object.__setattr__(self, "panel", int(self.panel))


@dataclass(frozen=True)
class BatchTimeFigureSpec:
    """Pure data specification for a grouped time-domain figure."""

    series: tuple[BatchSeries, ...]
    layout: str = "overlay"
    x_source: str = "time"
    x_origin: str = "zero"
    x_label: str = "Time (s)"
    panel_titles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        series = tuple(self.series)
        if not all(isinstance(item, BatchSeries) for item in series):
            raise TypeError("BatchTimeFigureSpec series must contain BatchSeries")
        if self.layout not in {"overlay", "subplot"}:
            raise ValueError("BatchTimeFigureSpec layout must be overlay or subplot")
        if self.x_source not in {"time", "channel"}:
            raise ValueError("BatchTimeFigureSpec x_source must be time or channel")
        if self.x_origin not in {"zero", "absolute"}:
            raise ValueError("BatchTimeFigureSpec x_origin must be zero or absolute")
        object.__setattr__(self, "series", series)
        object.__setattr__(self, "panel_titles", tuple(self.panel_titles))


def render_batch_image(
    payload,
    path,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> Path:
    """Render one existing batch payload and return its output path."""

    render_options = options or BatchRenderOptions()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure = _build_batch_figure(
        payload,
        params=params,
        options=render_options,
        context=context,
        warnings_out=warnings_out,
    )
    canvas = FigureCanvasAgg(figure)
    try:
        print_options = {
            "format": render_options.format,
            "dpi": render_options.dpi,
            "facecolor": figure.get_facecolor(),
            "metadata": _render_metadata(context),
        }
        rc_settings = _batch_font_rc_settings(render_options.format)
        # Cover lazily created tick labels during draw and restore every global
        # rcParam afterwards.  Existing Text artists receive the same actual
        # available family chain explicitly.
        with mpl.rc_context(rc_settings):
            _apply_figure_font_fallback(figure)
            canvas.print_figure(str(target), **print_options)
    finally:
        figure.clear()
    return target


def _build_batch_figure(
    payload,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> Figure:
    """Build a Figure for tests and for :func:`render_batch_image`."""

    render_options = options or BatchRenderOptions()
    with mpl.rc_context(_batch_font_rc_settings(render_options.format)):
        return _build_batch_figure_in_context(
            payload,
            params=params,
            options=render_options,
            context=context,
            warnings_out=warnings_out,
        )


def _build_batch_figure_in_context(
    payload,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> Figure:
    """Create all Figure/Text artists inside the renderer rc context."""

    try:
        kind, data = payload
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be a (kind, data) pair") from exc
    kind = str(kind)
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unsupported batch render kind: {kind}")

    render_options = options or BatchRenderOptions()
    render_params = dict(params or {})
    render_context = context or BatchRenderContext()
    figure = Figure(
        figsize=(
            render_options.width_px / render_options.dpi,
            render_options.height_px / render_options.dpi,
        ),
        dpi=render_options.dpi,
        facecolor="#101418",
    )
    if kind == "time" and isinstance(data, BatchTimeFigureSpec):
        axis = _render_time_spec(figure, data, render_params)
    else:
        axis = figure.add_subplot(111)
        _style_axis(axis)
        if kind == "time":
            _render_time(axis, data, render_params, render_context)
        elif kind == "fft":
            _render_fft(axis, data, render_params, render_context)
        else:
            _render_heatmap(
                figure,
                axis,
                kind,
                data,
                render_params,
                render_context,
                warnings_out,
            )

    _apply_figure_context(figure, axis, kind, render_params, render_context)
    figure.subplots_adjust(left=0.10, right=0.91, bottom=0.13, top=0.84)
    _apply_figure_font_fallback(figure)
    return figure


@lru_cache(maxsize=1)
def _available_cjk_font_families() -> tuple[str, ...]:
    """Return installed candidate families that cover the CJK contract text."""

    entries_by_family: dict[str, list[str]] = {}
    for entry in font_manager.fontManager.ttflist:
        entries_by_family.setdefault(str(entry.name), []).append(str(entry.fname))
    available: list[str] = []
    for family in _CJK_FONT_CANDIDATES:
        if any(
            _font_file_supports_contract(path)
            for path in entries_by_family.get(family, ())
        ):
            available.append(family)
    return tuple(available)


@lru_cache(maxsize=None)
def _font_file_supports_contract(path: str) -> bool:
    try:
        charmap = ft2font.FT2Font(path).get_charmap()
    except (OSError, RuntimeError, ValueError):
        return False
    return all(ord(character) in charmap for character in _CJK_CONTRACT_TEXT)


def _batch_font_family_chain() -> tuple[str, ...]:
    available = _available_cjk_font_families()
    if available:
        return (available[0], "DejaVu Sans")
    return ("DejaVu Sans",)


def _batch_font_rc_settings(image_format: str) -> dict[str, Any]:
    family_chain = list(_batch_font_family_chain())
    settings: dict[str, Any] = {
        "font.family": family_chain,
        "font.sans-serif": family_chain,
        "text.parse_math": False,
        # ASCII hyphen is present in every selected family.  This keeps
        # negative ticks readable even when a CJK font lacks U+2212.
        "axes.unicode_minus": False,
    }
    if image_format == "svg":
        settings["svg.fonttype"] = "none"
    if image_format == "pdf":
        settings["pdf.fonttype"] = 42
    return settings


def _apply_figure_font_fallback(figure: Figure) -> None:
    family_chain = list(_batch_font_family_chain())
    for text_artist in figure.findobj(match=Text):
        text_artist.set_fontfamily(family_chain)


def _style_axis(axis) -> None:
    axis.set_facecolor("#101418")
    axis.tick_params(colors="#d9e1e8")
    axis.xaxis.label.set_color("#e6edf3")
    axis.yaxis.label.set_color("#e6edf3")
    for spine in axis.spines.values():
        spine.set_color("#6b7785")
    axis.grid(True, color="#708090", alpha=0.25, linewidth=0.7)


def _render_time(
    axis,
    data,
    params: Mapping[str, Any],
    context: BatchRenderContext,
) -> None:
    frame = _require_dataframe(data, ("time_s", "series", "value"), "time")
    line_count = 0
    for series, group in frame.groupby("series", sort=False):
        x_values = group["time_s"].to_numpy(dtype=float)
        y_values = group["value"].to_numpy(dtype=float)
        line_style = "--" if str(series) == "filtered" else "-"
        axis.plot(
            x_values,
            y_values,
            linestyle=line_style,
            linewidth=1.5,
            label=str(series),
        )
        line_count += 1
    axis.set_xlabel("Time (s)")
    axis.set_ylabel(_linear_amplitude_label(context.unit))
    if line_count:
        legend = axis.legend(loc="best")
        if legend is not None:
            legend.get_frame().set_alpha(0.75)
    _apply_axis_limits(axis, params)


def _render_time_spec(
    figure: Figure,
    spec: BatchTimeFigureSpec,
    params: Mapping[str, Any],
):
    """Render a grouped time specification and return its primary axis."""

    active = tuple(item for item in spec.series if item.x.size)
    _validate_time_spec_units(active)
    if spec.layout == "subplot":
        return _render_time_spec_subplots(figure, spec, active, params)

    axis = figure.add_subplot(111)
    _style_axis(axis)
    _render_time_spec_panel(axis, active, spec, params)
    return axis


def _validate_time_spec_units(series: tuple[BatchSeries, ...]) -> None:
    x_units = _first_appearance_units(series, "x_unit")
    if len(x_units) > 1:
        raise ValueError("time figure spec has mixed x units")
    y_units = _first_appearance_units(series, "unit")
    if len(y_units) > 2:
        raise ValueError("time figure spec supports at most two y units")


def _first_appearance_units(
    series: tuple[BatchSeries, ...], attribute: str
) -> tuple[str, ...]:
    values: list[str] = []
    for item in series:
        unit = str(getattr(item, attribute))
        if unit not in values:
            values.append(unit)
    return tuple(values)


def _render_time_spec_subplots(
    figure: Figure,
    spec: BatchTimeFigureSpec,
    active: tuple[BatchSeries, ...],
    params: Mapping[str, Any],
):
    panel_ids = tuple(dict.fromkeys(item.panel for item in active)) or (0,)
    panel_series = {
        panel: tuple(item for item in active if item.panel == panel)
        for panel in panel_ids
    }
    axes = []
    for index, panel in enumerate(panel_ids, start=1):
        axis = figure.add_subplot(len(panel_ids), 1, index, sharex=axes[0] if axes else None)
        _style_axis(axis)
        if panel < len(spec.panel_titles):
            axis.set_title(str(spec.panel_titles[panel]), color="#f2f5f7", fontsize=10)
        _render_time_spec_panel(axis, panel_series[panel], spec, params)
        axes.append(axis)

    for axis in axes[:-1]:
        axis.set_xlabel("")
        axis.tick_params(labelbottom=False)
    axes[-1].set_xlabel(spec.x_label)
    _apply_time_spec_shared_x_limits(axes[-1], active, spec, params)
    return axes[-1]


def _render_time_spec_panel(
    axis,
    series: tuple[BatchSeries, ...],
    spec: BatchTimeFigureSpec,
    params: Mapping[str, Any],
) -> None:
    units = _first_appearance_units(series, "unit")
    if len(units) > 2:
        raise ValueError("time figure spec supports at most two y units")
    if len(units) == 2 and not bool(params.get("y_auto", True)) and _valid_pair(
        params.get("y_min"), params.get("y_max")
    ):
        raise ValueError("manual y limits are not supported with dual y units")

    axes_by_unit = {units[0]: axis} if units else {}
    if len(units) == 2:
        right_axis = axis.twinx()
        _style_axis(right_axis)
        axes_by_unit[units[1]] = right_axis

    handles = []
    labels = []
    x_union: list[np.ndarray] = []
    for item in series:
        x_values = _time_spec_x_values(item, spec)
        target_axis = axes_by_unit[item.unit]
        line = target_axis.plot(
            x_values,
            item.y,
            linestyle=item.linestyle,
            linewidth=1.5,
            label=item.label,
        )[0]
        handles.append(line)
        labels.append(item.label)
        finite_x = x_values[np.isfinite(x_values)]
        if finite_x.size:
            x_union.append(finite_x)

    axis.set_xlabel(spec.x_label)
    axis.set_ylabel(_linear_amplitude_label(units[0] if units else ""))
    if len(units) == 2:
        axes_by_unit[units[1]].set_ylabel(_linear_amplitude_label(units[1]))
    if handles:
        legend = axis.legend(handles, labels, loc="best")
        if legend is not None:
            legend.get_frame().set_alpha(0.75)

    if x_union:
        all_x = np.concatenate(x_union)
        axis.set_xlim(float(np.min(all_x)), float(np.max(all_x)))
    if not bool(params.get("x_auto", True)) and _valid_pair(
        params.get("x_min"), params.get("x_max")
    ):
        axis.set_xlim(float(params["x_min"]), float(params["x_max"]))
    if len(units) < 2 and not bool(params.get("y_auto", True)) and _valid_pair(
        params.get("y_min"), params.get("y_max")
    ):
        axis.set_ylim(float(params["y_min"]), float(params["y_max"]))


def _time_spec_x_values(item: BatchSeries, spec: BatchTimeFigureSpec) -> np.ndarray:
    x_values = np.asarray(item.x, dtype=float)
    if spec.x_source != "time" or spec.x_origin != "zero" or not x_values.size:
        return x_values
    return x_values - x_values[0]


def _apply_time_spec_shared_x_limits(
    axis,
    series: tuple[BatchSeries, ...],
    spec: BatchTimeFigureSpec,
    params: Mapping[str, Any],
) -> None:
    if not bool(params.get("x_auto", True)) and _valid_pair(
        params.get("x_min"), params.get("x_max")
    ):
        axis.set_xlim(float(params["x_min"]), float(params["x_max"]))
        return
    finite_values = [
        values[np.isfinite(values)]
        for values in (_time_spec_x_values(item, spec) for item in series)
        if np.any(np.isfinite(values))
    ]
    if finite_values:
        x_values = np.concatenate(finite_values)
        axis.set_xlim(float(np.min(x_values)), float(np.max(x_values)))


def _render_fft(
    axis,
    data,
    params: Mapping[str, Any],
    context: BatchRenderContext,
) -> None:
    frame = _require_dataframe(data, ("frequency_hz", "amplitude"), "fft")
    x_values = frame["frequency_hz"].to_numpy(dtype=float)
    linear_values = frame["amplitude"].to_numpy(dtype=float)
    resolution = _reference_resolution(params)
    weighting = str(params.get("weighting", "None"))
    render_db = _render_in_db("fft", params)
    if render_db:
        y_values = _display_db_values(linear_values, resolution.value)
        y_label = db_reference.format_amplitude_label(
            resolution,
            weighting=weighting,
            output_scale="db",
        )
    else:
        y_values = linear_values
        y_label = _linear_amplitude_label(context.unit)
    axis.plot(x_values, y_values, color="#f2f5f7", linewidth=1.5)
    axis.set_xlabel("Frequency (Hz)")
    axis.set_ylabel(y_label)
    _apply_axis_limits(axis, params)
    if render_db and bool(params.get("y_auto", True)):
        axis.set_ylim(*_auto_db_line_limits(y_values))


def _render_heatmap(
    figure: Figure,
    axis,
    kind: str,
    data,
    params: Mapping[str, Any],
    context: BatchRenderContext,
    warnings_out: list[str] | None = None,
) -> None:
    matrix, x_values, y_values, x_name, y_name, metadata = _extract_heatmap(data)
    resolution = _reference_resolution(params)
    weighting = str(params.get("weighting", "None"))
    render_db = _render_in_db(kind, params)
    if render_db:
        display_matrix = _display_db_values(matrix, resolution.value)
        colorbar_label = db_reference.format_amplitude_label(
            resolution,
            weighting=weighting,
            output_scale="db",
        )
    else:
        display_matrix = np.asarray(matrix, dtype=float)
        colorbar_label = _linear_amplitude_label(context.unit)

    x_extent = _coverage_extent(
        x_values,
        start=metadata.get("coverage_start"),
        end=metadata.get("coverage_end"),
    )
    y_extent = _coverage_extent(y_values)
    if not bool(params.get("z_auto", True)) and _valid_pair(
        params.get("z_floor"), params.get("z_ceiling")
    ):
        color_limits = (float(params["z_floor"]), float(params["z_ceiling"]))
    elif render_db:
        color_limits = _auto_db_color_limits(display_matrix)
    else:
        color_limits = _finite_limits(display_matrix)

    cmap = _resolve_colormap(params, warnings_out)
    image = axis.imshow(
        display_matrix,
        origin="lower",
        aspect="auto",
        interpolation="nearest",
        extent=(x_extent[0], x_extent[1], y_extent[0], y_extent[1]),
        cmap=cmap,
        vmin=color_limits[0],
        vmax=color_limits[1],
    )
    axis.set_xlabel(_axis_label(x_name))
    axis.set_ylabel(_axis_label(y_name))
    _apply_axis_limits(axis, params)
    if bool(params.get("x_auto", True)):
        axis.set_xlim(*x_extent)
    if bool(params.get("y_auto", True)):
        axis.set_ylim(*y_extent)
    colorbar = figure.colorbar(image, ax=axis, pad=0.02)
    colorbar.set_label(colorbar_label, color="#e6edf3")
    colorbar.ax.tick_params(colors="#d9e1e8")
    colorbar.outline.set_edgecolor("#6b7785")


def _resolve_colormap(
    params: Mapping[str, Any], warnings_out: list[str] | None
):
    requested = params.get("cmap", "turbo")
    try:
        return mpl.colormaps.get_cmap(requested)
    except (TypeError, ValueError):
        if warnings_out is not None:
            warnings_out.append(
                f"Invalid colormap {requested!r}; using 'turbo'."
            )
        return mpl.colormaps["turbo"]


def _require_dataframe(data, columns, kind: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"{kind} payload data must be a DataFrame")
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(f"{kind} payload is missing columns: {', '.join(missing)}")
    return data


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
        prefer_channel_metadata=True,
    )


def _render_in_db(kind: str, params: Mapping[str, Any]) -> bool:
    default_mode = "amplitude_db" if kind == "fft_time" else "amplitude"
    amplitude_mode = str(params.get("amplitude_mode", default_mode)).lower()
    amplitude_axis = str(params.get("amp_y", "")).lower()
    return "db" in amplitude_mode or amplitude_axis == "db"


def _display_db_values(amplitude, reference: float) -> np.ndarray:
    linear = np.asarray(amplitude, dtype=float)
    converted = SpectrogramAnalyzer.amplitude_to_db(linear, reference=reference)
    live_mask = np.isfinite(linear) & (linear > 0.0) & np.isfinite(converted)
    if np.any(live_mask):
        live_values = converted[live_mask]
        peak = float(np.max(live_values))
        display_floor = peak - _DISPLAY_DEAD_SPAN_DB
    else:
        display_floor = _EMPTY_DB_LEVEL
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


def _finite_values(values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


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
    left_half = float(positive[0]) / 2.0
    right_half = float(positive[-1]) / 2.0
    return (float(finite[0]) - left_half, float(finite[-1]) + right_half)


def _valid_pair(low, high) -> bool:
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(low_value) and np.isfinite(high_value) and high_value > low_value)


def _apply_axis_limits(axis, params: Mapping[str, Any]) -> None:
    if not bool(params.get("x_auto", True)) and _valid_pair(
        params.get("x_min"), params.get("x_max")
    ):
        axis.set_xlim(float(params["x_min"]), float(params["x_max"]))
    if not bool(params.get("y_auto", True)) and _valid_pair(
        params.get("y_min"), params.get("y_max")
    ):
        axis.set_ylim(float(params["y_min"]), float(params["y_max"]))


def _apply_figure_context(
    figure: Figure,
    axis,
    kind: str,
    params: Mapping[str, Any],
    context: BatchRenderContext,
) -> None:
    method = str(context.method).strip() or {
        "time": "Time",
        "fft": "FFT",
        "fft_time": "FFT vs Time",
        "order_time": "Order",
    }[kind]
    identity_parts = [
        _elide(context.source_display_name, 52),
        _elide(context.group, 38),
    ]
    identity_line = " · ".join(part for part in identity_parts if part)
    analysis_parts = [_elide(context.channel, 56), _elide(method, 28)]
    analysis_line = " · ".join(part for part in analysis_parts if part)
    title = "\n".join(part for part in (identity_line, analysis_line) if part)
    if not title:
        title = method
    figure.suptitle(
        title,
        x=0.10,
        y=0.985,
        ha="left",
        va="top",
        color="#f2f5f7",
        fontsize=12,
        fontweight="normal",
        linespacing=1.15,
    )

    facts = _effective_fact_items(context.effective_facts, params)
    if _render_in_db(kind, params):
        db_label = _rendered_db_label(figure, axis, kind)
        if db_label:
            facts.append(db_label)
    if facts:
        figure.text(
            0.10,
            0.875,
            _elide(" · ".join(facts), 170),
            ha="left",
            va="bottom",
            color="#aeb9c5",
            fontsize=8.5,
        )

    task_id = str(context.task_id).strip()
    footer = "TraceLab batch export"
    if task_id:
        footer = f"Task {_elide(task_id, 72)} · {footer}"
    figure.text(
        0.99,
        0.018,
        footer,
        ha="right",
        va="bottom",
        color="#8e9aa7",
        fontsize=7.5,
    )


def _effective_fact_items(
    effective_facts: Mapping[str, Any],
    params: Mapping[str, Any],
) -> list[str]:
    facts = dict(params)
    facts.update(effective_facts)
    items: list[str] = []
    window = _first_present(facts, "window", "effective_window")
    if window not in (None, ""):
        items.append(f"window={_elide(window, 24)}")
    nfft = _first_present(
        facts,
        "nfft_effective",
        "effective_nfft",
        "nfft",
        "n_fft",
    )
    if nfft not in (None, ""):
        items.append(f"NFFT={_format_fact_value(nfft)}")
    weighting = _first_present(facts, "weighting", "frequency_weighting")
    if weighting not in (None, "", "None", "none"):
        items.append(f"weighting={_elide(weighting, 16)}")
    averaging = _first_present(
        facts,
        "averaging",
        "averaging_mode",
        "average_mode",
        "avg_mode",
    )
    if averaging not in (None, "", "None", "none"):
        items.append(f"averaging={_elide(averaging, 18)}")
    overlap = _first_present(facts, "overlap", "overlap_ratio")
    if overlap not in (None, ""):
        items.append(f"overlap={_format_overlap(overlap)}")
    actual_fs = _first_present(facts, "actual_fs", "effective_fs", "fs")
    if actual_fs not in (None, ""):
        items.append(f"Fs={_format_fact_value(actual_fs)} Hz")
    members = _first_present(facts, "members")
    if members not in (None, ""):
        return [
            *items[:5],
            f"members={_format_fact_value(members)}",
        ]
    return items[:6]


def _first_present(mapping: Mapping[str, Any], *keys: str):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _format_overlap(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _elide(value, 14)
    if np.isfinite(numeric) and 0.0 <= numeric <= 1.0:
        return f"{numeric * 100:g}%"
    return f"{numeric:g}"


def _format_fact_value(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        return f"{float(value):g}"
    return _elide(value, 20)


def _rendered_db_label(figure: Figure, axis, kind: str) -> str:
    if kind == "fft":
        return str(axis.get_ylabel()).strip()
    if len(figure.axes) > 1:
        return str(figure.axes[-1].get_ylabel()).strip()
    return ""


def _linear_amplitude_label(unit: str) -> str:
    normalized_unit = str(unit or "").strip()
    return f"Amplitude ({normalized_unit})" if normalized_unit else "Amplitude"


def _elide(value: Any, limit: int) -> str:
    text = " ".join(("" if value is None else str(value)).split())
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"[:limit]
    return text[: limit - 1].rstrip() + "…"


def _freeze_fact_value(value: Any):
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_fact_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_fact_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_fact_value(item) for item in value)
    return value


def _render_metadata(context: BatchRenderContext | None) -> dict[str, str]:
    render_context = context or BatchRenderContext()
    title_parts = [
        str(render_context.source_display_name).strip(),
        str(render_context.channel).strip(),
        str(render_context.method).strip(),
    ]
    title = " · ".join(part for part in title_parts if part) or "TraceLab batch export"
    return {"Title": title, "Creator": "TraceLab batch renderer"}


def _axis_label(name: str) -> str:
    return {
        "time_s": "Time (s)",
        "frequency_hz": "Frequency (Hz)",
        "order": "Order",
    }.get(str(name), str(name))


__all__ = [
    "BatchRenderContext",
    "BatchRenderOptions",
    "BatchSeries",
    "BatchTimeFigureSpec",
    "render_batch_image",
]
