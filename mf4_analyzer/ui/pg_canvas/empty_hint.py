"""Shared "nothing to show yet" overlay for the analysis canvases.

``PgLineCanvas`` and ``PgHeatmapCanvas`` both need a centred grey label while a
source and parameters are selected but the result cache has not been filled.
The two implementations were byte-identical apart from which PlotItem they hang
the label on (line: the amplitude row of its two-row stack; heatmap: the map),
so the difference is absorbed by a ``viewbox_getter`` callback rather than left
as a fork.

The canvases keep owning ``_empty_hint_item`` / ``_empty_hint_text`` -- several
tests and ``ui/main_window`` read those attributes directly -- so this overlay
writes them back through a small setter pair instead of hiding the state.

Not used by ``canvas.py`` (time domain): its hint is a scene-level item on the
GraphicsLayoutWidget with no reposition-on-range-change, a genuinely different
overlay that this package deliberately leaves alone.
"""
from __future__ import annotations

import pyqtgraph as pg


_HINT_TEXT_COLOR = '#6b7280'
_HINT_FILL = (255, 255, 255, 220)
_HINT_BORDER_COLOR = '#d1d5db'
# Above every plotted curve/image so the hint is never painted under data that
# happens to still be on the plot when the hint goes up.
_HINT_Z = 1000


def make_hint_item() -> pg.TextItem:
    """Build the centred grey hint label (text filled in by the caller)."""
    hint = pg.TextItem(
        '',
        color=_HINT_TEXT_COLOR,
        fill=pg.mkBrush(*_HINT_FILL),
        border=pg.mkPen(_HINT_BORDER_COLOR, width=1),
        anchor=(0.5, 0.5),
    )
    hint.setZValue(_HINT_Z)
    return hint


def _reposition_signals(vb):
    return (vb.sigResized, vb.sigRangeChanged)


class EmptyHintOverlay:
    """Show/hide a centred hint label on one ViewBox, following its range.

    ``viewbox_getter`` is called on every operation rather than captured once:
    the canvases build their PlotItems in ``__init__`` but the overlay is
    constructed alongside, and re-reading keeps this correct if a canvas ever
    swaps its plot out.

    ``on_state`` receives ``(item, text)`` after every change so the owning
    canvas can mirror the pair onto itself.
    """

    def __init__(self, *, viewbox_getter, reposition_slot, on_state):
        self._viewbox_getter = viewbox_getter
        self._reposition_slot = reposition_slot
        self._on_state = on_state
        self._item = None
        self._text = ''

    @property
    def item(self):
        return self._item

    @property
    def text(self) -> str:
        return self._text

    def _publish(self) -> None:
        self._on_state(self._item, self._text)

    def show(self, text) -> None:
        self._text = str(text or '')
        # Publish before touching pyqtgraph, matching the original ordering:
        # the canvas's text attribute was assigned on line one of the method.
        self._publish()
        if not self._text:
            self.clear()
            return
        vb = self._viewbox_getter()
        if self._item is None:
            self._item = make_hint_item()
        self._item.setText(self._text)
        if self._item.scene() is None:
            vb.addItem(self._item, ignoreBounds=True)
        self._item.setVisible(True)
        # Disconnect first: show() is called repeatedly (every cache miss), and
        # without the release each call would add another receiver and every
        # range change would then run the reposition N times.
        for sig in _reposition_signals(vb):
            try:
                sig.disconnect(self._reposition_slot)
            except (TypeError, RuntimeError):
                pass
            try:
                sig.connect(self._reposition_slot)
            except Exception:
                pass
        self._publish()
        self.reposition()

    def reposition(self, *_args) -> None:
        if self._item is None or not self._text:
            return
        try:
            vb = self._viewbox_getter()
            rect = vb.sceneBoundingRect()
            self._item.setPos(vb.mapSceneToView(rect.center()))
        except Exception:
            pass

    def clear(self) -> None:
        self._text = ''
        if self._item is None:
            self._publish()
            return
        vb = self._viewbox_getter()
        for sig in _reposition_signals(vb):
            try:
                sig.disconnect(self._reposition_slot)
            except (TypeError, RuntimeError):
                pass
        try:
            vb.removeItem(self._item)
        except Exception:
            pass
        self._item = None
        self._publish()


__all__ = ['EmptyHintOverlay', 'make_hint_item']
