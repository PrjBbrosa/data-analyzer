"""AnalysisSectionPage: one analysis section's page in the ChartStack.

Layout (spec §4):
    [card pane 0 | card pane 1?]   <- QSplitter(Horizontal)
    [ViewTabBar]                   <- per-section instance

Pane semantics: split lives INSIDE the active view (state.panes), unlike
the time-domain split_pairs pairing. Focus routing mirrors the
time-domain _focused_card pattern (chart_stack.py:1986-2040): click a
pane → it becomes the target for source assignment.

V6 delivers the standalone, testable container only. V7 wires it into
ChartStack/MainWindow (state capture/apply, tabbar signal handling).
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .view_tabbar import ViewTabBar

_FOCUS_ACCENT = "#2d7ff9"


def _primary_vb(canvas):
    """Return a canvas's MAIN-row ViewBox, tolerant of the two pg canvas shapes.

    PgHeatmapCanvas exposes the single main PlotItem as ``canvas._plot``;
    PgLineCanvas has NO ``_plot`` — it has two fixed rows ``_plot_amp`` +
    ``_plot_psd`` (the PSD row is already XLinked to amp at construction),
    so linking the two canvases' AMP ViewBoxes propagates to the whole line
    figure. A naive ``canvas._plot.vb`` AttributeErrors on the line canvas.
    """
    plot = getattr(canvas, '_plot', None)
    if plot is None:
        plot = getattr(canvas, '_plot_amp', None)
    return plot.vb if plot is not None else None


class AnalysisSectionPage(QWidget):
    focus_changed = pyqtSignal(int)          # focused pane index
    link_toggled = pyqtSignal(bool)

    def __init__(self, *, section: str, manager, card_factory, parent=None):
        super().__init__(parent)
        self.section = section
        self.manager = manager
        self._card_factory = card_factory

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._split = QSplitter(Qt.Horizontal, self)
        self._split.setChildrenCollapsible(False)
        self._cards = [self._make_card()]
        self._split.addWidget(self._cards[0])
        lay.addWidget(self._split, stretch=1)

        # ViewTabBar's ctor is (manager, parent) — pass the manager, NOT self.
        self.tabbar = ViewTabBar(manager, self)
        lay.addWidget(self.tabbar)

        self._focused = 0
        self._linked = False
        self._apply_focus_style()

    # -- pane management -----------------------------------------------
    def _make_card(self):
        card = self._card_factory()
        # WA_StyledBackground so the #chartCard focus border actually paints
        # on the plain QWidget card; without it Qt paints only the rounded
        # corners and the straight edges stay un-bordered, hiding the accent
        # behind the margin-0 canvas child (lesson
        # 2026-06-04-dynamic-property-border-needs-styledbackground-and-padding).
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.installEventFilter(self)
        canvas = getattr(card, 'canvas', None)
        if canvas is not None:
            canvas.installEventFilter(self)
            glw = getattr(canvas, '_glw', None)
            if glw is not None:
                try:
                    viewport = glw.viewport()
                except Exception:
                    viewport = None
                if viewport is not None:
                    viewport.installEventFilter(self)
        return card

    def pane_count(self) -> int:
        return len(self._cards)

    def pane_canvas(self, idx: int):
        return self._cards[idx].canvas

    def enter_split(self) -> None:
        if len(self._cards) >= 2:
            return
        card = self._make_card()
        self._cards.append(card)
        self._split.addWidget(card)
        half = max(1, self._split.width() // 2)
        self._split.setSizes([half, half])
        self.set_linked(self._linked)
        self._apply_focus_style()

    def exit_split(self) -> None:
        if len(self._cards) < 2:
            return
        self.set_linked(False)
        card = self._cards.pop(1)
        card.removeEventFilter(self)
        card.setParent(None)
        card.deleteLater()
        self.set_focused_index(0)
        self._apply_focus_style()

    # -- focus ----------------------------------------------------------
    def focused_index(self) -> int:
        return self._focused

    def set_focused_index(self, idx: int) -> None:
        idx = max(0, min(idx, len(self._cards) - 1))
        if idx == self._focused:
            self._apply_focus_style()
            return
        self._focused = idx
        self._apply_focus_style()
        self.focus_changed.emit(idx)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and len(self._cards) > 1:
            idx = self._index_for_object(obj)
            if idx is not None:
                self.set_focused_index(idx)
        return super().eventFilter(obj, event)

    def _index_for_object(self, obj):
        """Map a filtered object (card, its canvas, or canvas viewport) back to
        its pane index, mirroring chart_stack._card_for_object. The
        isAncestorOf fallback catches any deeper child that bubbled a press."""
        for i, card in enumerate(self._cards):
            if obj is card:
                return i
            canvas = getattr(card, 'canvas', None)
            if canvas is not None:
                if obj is canvas:
                    return i
                glw = getattr(canvas, '_glw', None)
                if glw is not None:
                    try:
                        viewport = glw.viewport()
                    except Exception:
                        viewport = None
                    if viewport is not None and obj is viewport:
                        return i
            if isinstance(obj, QWidget) and card.isAncestorOf(obj):
                return i
        return None

    def _apply_focus_style(self) -> None:
        for i, card in enumerate(self._cards):
            accent = (_FOCUS_ACCENT if (i == self._focused and
                                        len(self._cards) > 1) else "transparent")
            # padding insets the layout content rect so the margin-0 canvas
            # child stops overpainting the 1px ring (same lesson as
            # WA_StyledBackground above).
            card.setStyleSheet(
                f"QWidget#chartCard {{ border: 1px solid {accent}; "
                f"padding: {1 if accent != 'transparent' else 0}px; }}"
            )

    # -- compare: linked zoom (spec §6.1) --------------------------------
    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)
        if len(self._cards) < 2:
            return
        c0 = self._cards[0].canvas
        c1 = self._cards[1].canvas
        vb0 = _primary_vb(c0)
        vb1 = _primary_vb(c1)
        if vb0 is None or vb1 is None:
            return
        if self._linked:
            vb1.setXLink(vb0)
            # Heatmaps compare on BOTH axes (spec §6.1); line sections X only.
            # _img is the heatmap's ImageItem — absent on PgLineCanvas.
            if hasattr(c0, '_img') and hasattr(c1, '_img'):
                vb1.setYLink(vb0)
        else:
            vb1.setXLink(None)
            vb1.setYLink(None)
        self.link_toggled.emit(self._linked)

    def is_linked(self) -> bool:
        return self._linked
