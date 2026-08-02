"""Build offscreen pyqtgraph report scenes for all batch image payloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetricsF, QImage, QPainter
from PyQt5.QtWidgets import QApplication, QFrame, QWidget

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
    coarsen_nice_step,
    nice_ticks_within,
)

from ._fonts import apply_axis_font, chart_font
from ._models import BatchRenderContext, BatchSeries, BatchTimeFigureSpec
from ._page import add_report_footer, add_report_header
from ._theme import SERIES_COLORS, RenderTheme, render_theme, scaled_fonts


_SUPPORTED_KINDS = frozenset({"time", "fft", "fft_time", "order_time"})
_EMPTY_DB_LEVEL = -200.0
_AUTO_SPAN_DB = 30.0
_AUTO_CEILING_PERCENTILE = 99.0
_DISPLAY_DEAD_SPAN_DB = 200.0
_HIGH_RASTER_TRANSITION_FRACTION = 0.5
_HIGH_RASTER_NORMALIZED_Q90 = 0.001


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
    values = np.asarray(item.x, dtype=float)
    if spec.x_source == "time" and spec.x_origin == "zero" and values.size:
        return values - values[0]
    return values


def _native_time_antialias(profile: RenderProfile, pixel_width: int) -> bool:
    """Preserve smooth-line AA while bounding high-raster export cost."""

    if profile.strategy == "dense_discrete":
        return False
    if profile.source_length <= 2 * max(1, int(pixel_width)):
        return True
    q90 = float(profile.normalized_step_quantiles[2])
    return not (
        profile.transition_fraction >= _HIGH_RASTER_TRANSITION_FRACTION
        and q90 >= _HIGH_RASTER_NORMALIZED_Q90
    )


def _text_of(item) -> str:
    target = getattr(item, "item", item)
    to_plain = getattr(target, "toPlainText", None)
    if callable(to_plain):
        return str(to_plain())
    text = getattr(item, "text", "")
    return str(text)


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
            key = (pixel_width, effective_width, x_range)
            if binding.last_key == key:
                continue
            display_x, display_y = positions_envelope(
                binding.x,
                binding.y,
                xlim=x_range,
                pixel_width=effective_width,
                is_monotonic=binding.profile.monotonic_time,
            )
            binding.curve.setData(
                display_x,
                display_y,
                antialias=_native_time_antialias(
                    binding.profile, effective_width
                ),
            )
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
        # geometry. Rebind only curves whose realized pixel width actually
        # changed; all of this still happens before the sole paint drain.
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
        if app is not None:
            # An AxisItem only learns how much space its tick strings need
            # while painting. Drain that paint here so the resulting text-space
            # change is folded back into the layout; otherwise the caller's own
            # render would be the first paint and would capture the
            # pre-adjustment geometry.
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
        curve = pg.PlotDataItem(
            pen=self._next_pen(item.linestyle, color_key=color_key),
            antialias=profile.strategy != "dense_discrete",
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
        for item in panel_series:
            curve = self._add_curve(owners[item.unit], plot, item, spec)
            local_curves.append(curve)

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

        group = [plot.getAxis("left").label]
        if title_item is not None:
            group.append(title_item)
        if right_axis is not None:
            group.append(right_axis.label)
        if bottom:
            group.append(plot.getAxis("bottom").label)
        self.panel_text_items.append(tuple(group))
        return plot

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
        curve = pg.PlotDataItem(
            x_values,
            y_values,
            pen=self._next_pen("-", fft=True),
            antialias=True,
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
        if not bool(self.params.get("z_auto", True)) and _valid_pair(
            self.params.get("z_floor"), self.params.get("z_ceiling")
        ):
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
            plot.setXRange(
                float(self.params["x_min"]),
                float(self.params["x_max"]),
                padding=0,
            )
        else:
            plot.setXRange(*x_extent, padding=0)
        if not bool(self.params.get("y_auto", True)) and _valid_pair(
            self.params.get("y_min"), self.params.get("y_max")
        ):
            plot.setYRange(
                float(self.params["y_min"]),
                float(self.params["y_max"]),
                padding=0,
            )
        else:
            plot.setYRange(*y_extent, padding=0)

        self.widget.ci.layout.setRowStretchFactor(3, 1)
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
        return 4

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
