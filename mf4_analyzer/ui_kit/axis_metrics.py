"""Paint-history-free measurement and pinning of pyqtgraph left axes.

Why this lives in ``ui_kit`` rather than beside a canvas: both the
interactive canvases (``mf4_analyzer.ui.pg_canvas.*``) and the offscreen
batch renderer (``mf4_analyzer.batch_render_qt._builder``) have to answer
the same question — "how wide does this left ``AxisItem`` have to be for the
tick strings it is carrying right now?" — and ``ui_kit`` is the only layer
both are already allowed to import (``_builder`` reaches for
``..ui_kit.ticks_math`` today). Putting it under ``ui/pg_canvas/`` would
drag ``mf4_analyzer/ui/__init__.py`` — and therefore ``MainWindow`` — into
the batch render path, which currently never imports it.

Constraint: nothing here may be reachable from ``mf4_analyzer.signal``
(see ``tests/test_signal_no_gui_import.py``); this module imports PyQt5.
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QFontMetricsF

from mf4_analyzer.qt_chart_fonts import chart_font


__all__ = [
    "TICK_TEXT_PROBE",
    "activate_item_layouts",
    "axis_tick_font",
    "axis_tick_texts",
    "left_axis_width_for_ticks",
    "pin_left_axes_to_common_width",
]


# pyqtgraph measures every tick string with ``QPainter.boundingRect`` against
# this probe rect (AxisItem.generateDrawSpecs); reusing it keeps our own
# measurement on the same footing as the one that ends up on the canvas.
TICK_TEXT_PROBE = QRectF(0.0, 0.0, 100.0, 100.0)


def axis_tick_texts(axis) -> list[str]:
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


def axis_tick_font(axis, fallback_pt: float):
    font = axis.style.get("tickFont")
    if font is None:
        label_item = getattr(axis, "label", None)
        font = label_item.font() if label_item is not None else chart_font(fallback_pt)
    return font


def left_axis_width_for_ticks(axis) -> float:
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
    metrics = QFontMetricsF(axis_tick_font(axis, 9.0))
    width = max(
        (
            float(
                metrics.boundingRect(
                    TICK_TEXT_PROBE, Qt.AlignCenter, text
                ).width()
            )
            for text in axis_tick_texts(axis)
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


def activate_item_layouts(items) -> None:
    """Invalidate + activate the ``QGraphicsLayout`` of each graphics item.

    An ``AxisItem``'s realized geometry is assigned by the layout of the
    ``PlotItem`` that owns it, NOT by the enclosing ``GraphicsLayout``'s grid.
    Activating only ``glw.ci.layout`` therefore re-flows the rows without ever
    re-sizing the axis cell inside them, which is why callers must pass every
    ``PlotItem`` alongside ``ci``. Mirrors the traversal in
    ``heatmap_canvas._activate_graphics_layout``.
    """
    for item in items:
        if item is None:
            continue
        layout = getattr(item, "layout", None)
        if layout is None:
            continue
        try:
            layout.invalidate()
            layout.activate()
        except Exception:
            pass


def pin_left_axes_to_common_width(axes, *, layout_owners=()) -> float:
    """Pin every axis in ``axes`` to one width and return it (0.0 = no-op).

    The target is ``max(max(font_metric_need, realized_width) for axis)``.

    Both terms are load-bearing:

    * the font-metric term is the first-paint lower bound — it is the only
      one that is right before anything has been painted, when
      ``AxisItem.textWidth`` is still pyqtgraph's constructor default of 30;
    * the realized ``width()`` term keeps an axis pyqtgraph has already sized
      from never being narrowed below what it is currently drawing.

    Deliberately NOT preceded by a ``setWidth(None)`` release-and-remeasure.
    ``setWidth`` only moves size *hints*; ``QGraphicsWidget.width()`` reports
    realized geometry and does not change until the owning layout is
    activated, so releasing and immediately reading back returns the width
    that was already pinned — the pin becomes a fixed point of itself and can
    never grow. Measuring the strings sidesteps the whole dance.

    Tradeoff, matching the batch renderer's existing semantics: because
    ``width()`` participates in the max, pinning is monotonically
    non-decreasing — an axis does NOT shrink back when its labels get shorter.
    Re-tightening would require releasing the pin AND fully activating the
    layouts before measuring; if that is ever wanted it needs its own
    regression coverage.
    """
    axes = [axis for axis in axes if axis is not None]
    if not axes:
        return 0.0
    target = 0.0
    for axis in axes:
        try:
            needed = float(left_axis_width_for_ticks(axis))
        except Exception:
            needed = 0.0
        try:
            realized = float(axis.width())
        except Exception:
            realized = 0.0
        target = max(target, needed, realized)
    if target <= 0.0:
        return 0.0
    for axis in axes:
        try:
            axis.setWidth(target)
        except Exception:
            pass
    activate_item_layouts(layout_owners)
    return target
