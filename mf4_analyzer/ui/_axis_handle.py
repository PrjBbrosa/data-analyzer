"""Pyqtgraph chart-axis adapter protocols.

``ChartOptionsDialog`` and ``_axis_interaction`` consume the
``AxisHandle`` contract. Runtime callers now pass existing pyqtgraph
handles; raw renderer objects are not wrapped here.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


PG_AXIS_NEUTRAL_COLOR = "#9ca3af"
PG_AXIS_NEUTRAL_WIDTH = 1.0


# ---------------------------------------------------------------------------
# Line protocol + pyqtgraph wrapper
# ---------------------------------------------------------------------------


@runtime_checkable
class LineHandle(Protocol):
    """Renderer-agnostic view of a single curve on an axis.

    Today's ``ChartOptionsDialog`` only reads label/color/visibility and
    writes color. Keep the surface minimal; widen only when a real
    caller needs more.
    """

    def get_label(self) -> str: ...
    def get_color(self) -> str: ...
    def set_color(self, color: str) -> None: ...
    def get_visible(self) -> bool: ...

# ---------------------------------------------------------------------------
# Axis protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AxisHandle(Protocol):
    """Renderer-agnostic axis surface consumed by ``ChartOptionsDialog``
    and ``_axis_interaction``. Signatures are pinned by design §5.3."""

    def get_xlim(self) -> tuple[float, float]: ...
    def set_xlim(self, lo: float, hi: float) -> None: ...
    def get_ylim(self) -> tuple[float, float]: ...
    def set_ylim(self, lo: float, hi: float) -> None: ...
    def autoscale(self, axis: str = "both") -> None: ...
    def set_xscale(self, scale: str) -> None: ...
    def set_yscale(self, scale: str) -> None: ...
    def get_xscale(self) -> str: ...
    def get_yscale(self) -> str: ...
    def get_xlabel(self) -> str: ...
    def set_xlabel(self, label: str) -> None: ...
    def get_ylabel(self) -> str: ...
    def set_ylabel(self, label: str) -> None: ...
    def get_title(self) -> str: ...
    def set_title(self, title: str) -> None: ...
    def grid(self, enabled: bool) -> None: ...
    def is_grid_enabled(self) -> bool: ...
    def get_lines(self) -> list[LineHandle]: ...
    def get_mappables(self) -> list[object]: ...
    def rebuild_legend(self) -> None: ...
    def sync_line_axis_color(self, line: LineHandle, color: str) -> None: ...
    def request_redraw(self) -> None: ...

# ---------------------------------------------------------------------------
# pyqtgraph line + axis wrappers
# ---------------------------------------------------------------------------


class _PgLineHandle:
    """Thin wrapper around a pyqtgraph ``PlotDataItem``.

    ``ChartOptionsDialog`` sees the minimal ``LineHandle`` Protocol. Read
    accessors prefer ``opts['name']`` / ``opts['pen']`` over private
    artist state because the public API surface across pyqtgraph 0.14
    keeps those keys.
    """

    def __init__(self, plot_data_item, *, label_fallback: str | None = None):
        self._pdi = plot_data_item
        # PlotDataItem stores name() but it's empty unless set at
        # construction. Allow a fallback so the axis can pin the
        # user-visible channel name when none was provided to the curve.
        self._label_fallback = label_fallback

    # Read accessors -------------------------------------------------------
    def get_label(self) -> str:
        name = self._pdi.name() if callable(getattr(self._pdi, "name", None)) else None
        if name:
            return str(name)
        if self._label_fallback is not None:
            return self._label_fallback
        return ""

    def get_color(self) -> str:
        pen = self._pdi.opts.get("pen") if hasattr(self._pdi, "opts") else None
        # Pens can be QPen, color string, tuple, or pyqtgraph format.
        try:
            from PyQt5.QtGui import QColor, QPen

            if isinstance(pen, QPen):
                return pen.color().name()
            if isinstance(pen, str):
                return QColor(pen).name()
            if isinstance(pen, (tuple, list)) and len(pen) >= 3:
                return QColor(*pen[:4]).name()
            # Fall through: pyqtgraph mkPen-friendly object — pass
            # through pg.mkColor to extract a QColor.
            import pyqtgraph as pg

            return pg.mkColor(pen).name()
        except Exception:
            return ""

    def get_visible(self) -> bool:
        is_visible = getattr(self._pdi, "isVisible", None)
        return bool(is_visible()) if callable(is_visible) else True

    # Write accessors ------------------------------------------------------
    def set_color(self, color: str) -> None:
        # Use the existing pen's width if possible so we only swap color.
        width = 1.0
        if hasattr(self._pdi, "opts"):
            pen = self._pdi.opts.get("pen")
            try:
                from PyQt5.QtGui import QPen

                if isinstance(pen, QPen):
                    width = max(0.5, float(pen.widthF() or 1.0))
            except Exception:
                pass
        try:
            import pyqtgraph as pg

            self._pdi.setPen(pg.mkPen(color=color, width=width))
        except Exception:
            # Last-resort: rely on setPen accepting a raw color string.
            try:
                self._pdi.setPen(color)
            except Exception:
                pass

    # Escape hatch ---------------------------------------------------------
    @property
    def plot_data_item(self):
        """Raw pyqtgraph ``PlotDataItem`` for owning-canvas sync paths."""
        return self._pdi


class PgAxisHandle:
    """Concrete ``AxisHandle`` for the pyqtgraph TimeDomain canvas.

    Wraps a pyqtgraph ``PlotItem`` (the container that owns one
    ``ViewBox`` plus the four ``AxisItem`` siblings). Delegating to the
    PlotItem rather than the raw ViewBox lets us cover xlim/ylim AND
    label/title/grid/scale in one adapter, matching design §5.3.

    Construction accepts either a positional ``PlotItem`` or the two
    keyword forms used by current callers:

    - ``PgAxisHandle(plot_item=...)`` — preferred new form.
    - ``PgAxisHandle(view_box=..., axis_item=...)`` — kept for
      backward-compat with the T3 stub signature.

    ``get_mappables`` returns ``[]`` for time-domain canvases (design
    §5.3: the ColorMap/ColorScale group of ChartOptionsDialog is
    disabled when there are no mappables, NOT removed).
    """

    def __init__(
        self,
        plot_item=None,
        *,
        view_box=None,
        axis_item=None,
        owner_canvas=None,
        allow_y_grid=True,
    ):
        # Resolve the PlotItem first: it owns the ViewBox + AxisItems and
        # is the only object we need to delegate to. Tolerate the legacy
        # (view_box=, axis_item=) call form by reconstructing the
        # PlotItem from the ViewBox when possible, otherwise store the
        # raw pair so partial test usage still works for non-label methods.
        if plot_item is None and view_box is not None:
            # PlotItem keeps its ViewBox at .vb; use parentItem() as a
            # heuristic for the inverse lookup. Falls back to None when
            # the test constructs a bare ViewBox without a PlotItem.
            parent = getattr(view_box, "parentItem", None)
            plot_item = parent() if callable(parent) else None
        self._plot_item = plot_item
        # Cache the ViewBox; if no PlotItem was given fall back to the
        # explicit view_box kw arg.
        if view_box is not None:
            self._view_box = view_box
        elif plot_item is not None and hasattr(plot_item, "getViewBox"):
            self._view_box = plot_item.getViewBox()
        else:
            self._view_box = None
        self._axis_item = axis_item  # historical compat; not strictly used
        self._owner_canvas = owner_canvas
        self._allow_y_grid = bool(allow_y_grid)
        self._grid_enabled = self._read_grid_enabled()
        self._xscale = self._read_log_scale("x")
        self._yscale = self._read_log_scale("y")
        self._line_items = []
        self._title_changed_callbacks = []

    # Internal helpers -----------------------------------------------------
    def _ax(self, side: str):
        """Return the ``AxisItem`` for ``side`` ('left'|'bottom'|...)."""
        pi = self._plot_item
        if pi is None or not hasattr(pi, "getAxis"):
            return None
        try:
            return pi.getAxis(side)
        except Exception:
            return None

    def _read_grid_enabled(self) -> bool:
        try:
            bottom = self._ax("bottom")
            if bottom is not None and bool(getattr(bottom, "grid", False)):
                return True
            if self._allow_y_grid:
                y_axis = self.y_axis_item()
                if y_axis is not None and bool(getattr(y_axis, "grid", False)):
                    return True
        except Exception:
            pass
        pi = self._plot_item
        ctrl = getattr(pi, "ctrl", None)
        checks = [getattr(ctrl, "xGridCheck", None)]
        if self._allow_y_grid:
            checks.append(getattr(ctrl, "yGridCheck", None))
        for check in checks:
            is_checked = getattr(check, "isChecked", None)
            if callable(is_checked) and is_checked():
                return True
        return False

    def _read_log_scale(self, axis: str) -> str:
        pi = self._plot_item
        ctrl = getattr(pi, "ctrl", None)
        name = "logXCheck" if axis == "x" else "logYCheck"
        check = getattr(ctrl, name, None)
        is_checked = getattr(check, "isChecked", None)
        if callable(is_checked) and is_checked():
            return "log"
        return "linear"

    # Limits ----------------------------------------------------------------
    def get_xlim(self) -> tuple[float, float]:
        vb = self._view_box
        if vb is None or not hasattr(vb, "viewRange"):
            return (0.0, 0.0)
        x_range, _y_range = vb.viewRange()
        return float(x_range[0]), float(x_range[1])

    def set_xlim(self, lo: float, hi: float) -> None:
        vb = self._view_box
        if vb is None or not hasattr(vb, "setXRange"):
            return
        # padding=0 keeps set_xlim as an exact range assignment; otherwise
        # pyqtgraph adds ~2 % padding on top of the requested range.
        vb.setXRange(float(lo), float(hi), padding=0)

    def get_ylim(self) -> tuple[float, float]:
        vb = self._view_box
        if vb is None or not hasattr(vb, "viewRange"):
            return (0.0, 0.0)
        _x_range, y_range = vb.viewRange()
        return float(y_range[0]), float(y_range[1])

    def set_ylim(self, lo: float, hi: float) -> None:
        vb = self._view_box
        if vb is None or not hasattr(vb, "setYRange"):
            return
        vb.setYRange(float(lo), float(hi), padding=0)

    def autoscale(self, axis: str = "both") -> None:
        vb = self._view_box
        if vb is None:
            return
        # ViewBox.enableAutoRange accepts axis flags ('x', 'y',
        # 'both'/'xy'). Treat anything else as a no-op for compatibility
        # with the dialog's loose axis argument handling.
        if not hasattr(vb, "enableAutoRange"):
            return
        if axis == "x":
            vb.enableAutoRange(axis="x")
        elif axis == "y":
            vb.enableAutoRange(axis="y")
        else:
            vb.enableAutoRange()

    # Scales ----------------------------------------------------------------
    def _is_primary_plot_view(self) -> bool:
        pi = self._plot_item
        if pi is None or not hasattr(pi, "getViewBox"):
            return False
        try:
            return self._view_box is pi.getViewBox()
        except Exception:
            return False

    def _plot_data_items(self):
        items = []
        if self._line_items:
            items.extend(self._line_items)
        pi = self._plot_item
        if pi is not None and self._is_primary_plot_view() and hasattr(pi, "listDataItems"):
            try:
                items.extend(list(pi.listDataItems()))
            except Exception:
                pass
        unique = []
        for item in items:
            if item not in unique:
                unique.append(item)
        return unique

    def _apply_data_log_mode(self):
        x_log = self._xscale == "log"
        y_log = self._yscale == "log"
        for item in self._plot_data_items():
            setter = getattr(item, "setLogMode", None)
            if callable(setter):
                try:
                    setter(x_log, y_log)
                except Exception:
                    pass

    def set_xscale(self, scale: str) -> None:
        normalized = "log" if scale == "log" else "linear"
        self._xscale = normalized
        pi = self._plot_item
        if pi is not None and hasattr(pi, "setLogMode") and self._is_primary_plot_view():
            pi.setLogMode(x=(normalized == "log"))
        axis = self.x_axis_item()
        if axis is not None and hasattr(axis, "setLogMode"):
            try:
                axis.setLogMode(normalized == "log")
            except Exception:
                pass
        self._apply_data_log_mode()

    def set_yscale(self, scale: str) -> None:
        normalized = "log" if scale == "log" else "linear"
        self._yscale = normalized
        pi = self._plot_item
        if pi is not None and hasattr(pi, "setLogMode") and self._is_primary_plot_view():
            pi.setLogMode(y=(normalized == "log"))
        axis = self.y_axis_item()
        if axis is not None and hasattr(axis, "setLogMode"):
            try:
                axis.setLogMode(normalized == "log")
            except Exception:
                pass
        self._apply_data_log_mode()

    def get_xscale(self) -> str:
        # Prefer the cached write-through state. If a caller toggled the
        # PlotItem controls directly before constructing the handle, the
        # constructor seeded this value from those checkboxes.
        return self._xscale

    def get_yscale(self) -> str:
        return self._yscale

    # Labels ----------------------------------------------------------------
    def get_xlabel(self) -> str:
        ax = self._ax("bottom")
        if ax is None:
            return ""
        # AxisItem stores its label inside .labelText (a plain string) on
        # 0.14; fall back to introspecting the QGraphicsTextItem for older
        # builds.
        text = getattr(ax, "labelText", None)
        if text:
            return str(text)
        lbl = getattr(ax, "label", None)
        if lbl is not None and hasattr(lbl, "toPlainText"):
            return str(lbl.toPlainText())
        return ""

    def set_xlabel(self, label: str) -> None:
        ax = self._ax("bottom")
        if ax is None:
            return
        ax.setLabel(text=label)

    def get_ylabel(self) -> str:
        ax = self.y_axis_item()
        if ax is None:
            return ""
        text = getattr(ax, "labelText", None)
        if text:
            return str(text)
        lbl = getattr(ax, "label", None)
        if lbl is not None and hasattr(lbl, "toPlainText"):
            return str(lbl.toPlainText())
        return ""

    def set_ylabel(self, label: str) -> None:
        ax = self.y_axis_item()
        if ax is None:
            return
        ax.setLabel(text=label)

    def get_title(self) -> str:
        pi = self._plot_item
        if pi is None:
            return ""
        # PlotItem keeps the title on .titleLabel (a LabelItem). Fall
        # back to its 'text' attribute or the underlying TextItem.
        title_label = getattr(pi, "titleLabel", None)
        if title_label is None:
            return ""
        text = getattr(title_label, "text", "")
        if isinstance(text, str):
            return text
        # LabelItem.text may be an HTML-wrapped string; return as-is so
        # callers can compare on a substring.
        try:
            return str(text)
        except Exception:
            return ""

    def set_title(self, title: str) -> None:
        pi = self._plot_item
        if pi is None or not hasattr(pi, "setTitle"):
            return
        pi.setTitle(title)
        for callback in list(self._title_changed_callbacks):
            try:
                callback(self, str(title))
            except Exception:
                pass

    def add_title_changed_callback(self, callback) -> None:
        if callback not in self._title_changed_callbacks:
            self._title_changed_callbacks.append(callback)

    # Grid ------------------------------------------------------------------
    def grid(self, enabled: bool) -> None:
        pi = self._plot_item
        if pi is None or not hasattr(pi, "showGrid"):
            return
        self._grid_enabled = bool(enabled)
        from mf4_analyzer.ui.pg_canvas import _shared
        _shared.show_major_grid_left_bottom_only(
            pi,
            x=self._grid_enabled,
            y=self._grid_enabled if self._allow_y_grid else False,
            alpha=0.28,
        )

    def is_grid_enabled(self) -> bool:
        try:
            bottom = self._ax("bottom")
            if bottom is not None:
                return bool(getattr(bottom, "grid", False))
        except Exception:
            pass
        return bool(self._grid_enabled)

    def is_autorange(self, axis: str = "x") -> bool:
        vb = self._view_box
        state = getattr(vb, "state", None) if vb is not None else None
        if not isinstance(state, dict):
            return False
        flags = state.get("autoRange") or [False, False]
        idx = 1 if str(axis).lower().startswith("y") else 0
        try:
            return bool(flags[idx])
        except (IndexError, KeyError, TypeError):
            return False

    # Lines + mappables -----------------------------------------------------
    def get_lines(self) -> list[LineHandle]:
        if hasattr(self, "_line_items") and self._line_items:
            return [
                _PgLineHandle(pdi)
                for pdi in list(self._line_items)
                if not hasattr(pdi, "isVisible") or pdi.isVisible()
            ]
        pi = self._plot_item
        if pi is None:
            return []
        # PlotItem.listDataItems() returns PlotDataItems attached to the
        # plot (the curves we drew via pi.plot() or pi.addItem(pdi)).
        items = []
        if hasattr(pi, "listDataItems"):
            try:
                items = list(pi.listDataItems())
            except Exception:
                items = []
        return [
            _PgLineHandle(pdi)
            for pdi in items
            if not hasattr(pdi, "isVisible") or pdi.isVisible()
        ]

    def get_mappables(self) -> list[object]:
        # Time-domain has no images / colorscales; design §5.3 says the
        # mappable list returns empty so the ColorMap/ColorScale group
        # of ChartOptionsDialog disables (not hides) itself.
        return []

    def rebuild_legend(self) -> None:
        pi = self._plot_item
        if pi is None:
            return
        legend = getattr(pi, "legend", None)
        if legend is None:
            add_legend = getattr(pi, "addLegend", None)
            if not callable(add_legend):
                return
            legend = add_legend()
        clear = getattr(legend, "clear", None)
        if callable(clear):
            clear()
        seen: set[str] = set()
        for line in self.get_lines():
            label = line.get_label()
            if not label or label.startswith("_") or label in seen:
                continue
            item = getattr(line, "plot_data_item", line)
            try:
                legend.addItem(item, label)
                seen.add(label)
            except Exception:
                continue

    def sync_line_axis_color(self, line: LineHandle, color: str) -> None:
        try:
            import pyqtgraph as pg
        except Exception:
            return
        axis = self.y_axis_item()
        if axis is None:
            return
        try:
            axis.setPen(
                pg.mkPen(color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
            )
        except Exception:
            pass
        try:
            axis.setTextPen(pg.mkPen(color=color))
        except Exception:
            pass
        owner = getattr(self, "_owner_canvas", None)
        sync = getattr(owner, "_sync_pg_channel_color", None)
        label = ""
        try:
            label = line.get_label()
        except Exception:
            label = ""
        if label and callable(sync):
            sync(label, color)

    def x_axis_item(self):
        return self._ax("bottom")

    def y_axis_item(self):
        if self._axis_item is not None:
            return self._axis_item
        return self._ax("left")

    def add_line_item(self, plot_data_item) -> None:
        if not hasattr(self, "_line_items"):
            self._line_items = []
        if plot_data_item not in self._line_items:
            self._line_items.append(plot_data_item)

    # Redraw ----------------------------------------------------------------
    def request_redraw(self) -> None:
        pi = self._plot_item
        if pi is None:
            return
        # The PlotItem's scene re-renders automatically on data/limit
        # changes; we trigger an explicit update() pass on the scene so
        # the chart-options dialog Apply path sees a frame promptly.
        try:
            scene = pi.scene() if callable(getattr(pi, "scene", None)) else None
            if scene is not None and hasattr(scene, "update"):
                scene.update()
        except Exception:
            pass

    # Escape hatch ---------------------------------------------------------
    @property
    def plot_item(self):
        """Raw pyqtgraph ``PlotItem`` for code that still needs the
        underlying artist. Migration-temporary."""
        return self._plot_item

    @property
    def view_box(self):
        """Raw pyqtgraph ``ViewBox``. Used by interaction helpers and
        the cursor/overlay layer. Migration-temporary."""
        return self._view_box


# ---------------------------------------------------------------------------
# Construction-site dispatcher
# ---------------------------------------------------------------------------


def make_handle(axis_or_handle) -> AxisHandle:
    """Return an existing pyqtgraph chart-axis handle.

    Callers must pass objects that already satisfy ``AxisHandle``; raw
    renderer objects are no longer adapted here.
    """
    if isinstance(axis_or_handle, AxisHandle):
        return axis_or_handle
    raise TypeError(f"unsupported axis object: {type(axis_or_handle).__name__}")
