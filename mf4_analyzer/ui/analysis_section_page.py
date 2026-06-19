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

import numpy as np
from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .view_tabbar import ViewTabBar

_FOCUS_ACCENT = "#2d7ff9"

# Slim compare-toggle row chrome. Transparent container (lesson
# no-gray-bg-embedded-widgets): an embedded custom QWidget hosting the
# tabbar + toggles must NOT paint the default platform grey, so the row
# frame stays translucent and only the buttons carry chrome.
_COMPARE_ROW_QSS = """
QWidget#analysisCompareRow {
    background-color: #fbfcff;
    border-top: 1px solid #dbe3ee;
}
QToolButton#analysisCompareToggle {
    min-height: 22px;
    max-height: 22px;
    background: transparent;
    border: 1px solid #d4d8de;
    border-radius: 4px;
    padding: 0 8px;
    color: #5b6471;
    font-size: 11px;
}
QToolButton#analysisCompareToggle:hover { border-color: #b6c6e6; }
QToolButton#analysisCompareToggle:checked {
    background: #eaf2ff;
    border-color: #2d7ff9;
    color: #1f5fd0;
}
QToolButton#analysisCompareToggle:disabled { color: #b8bdc6; }
"""


def _primary_vb(canvas):
    """Return a canvas's MAIN-row ViewBox, tolerant of the two pg canvas shapes.

    PgHeatmapCanvas exposes the single main PlotItem as ``canvas._plot``;
    PgLineCanvas has NO ``_plot`` — it has two fixed rows ``_plot_amp`` +
    ``_plot_time`` (the preview row follows the amp row's X navigation),
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
    # V8: user-driven EDGE toggle of a compare option. Carries the
    # state.compare key ('x_linked' / 'levels_locked') and the new value so
    # MainWindow can write it back onto the active view's state. This is the
    # producer that closes the compare write-back loop (V7 only READ
    # state.compare to drive set_linked). Distinct from ``link_toggled``,
    # which set_linked fires non-edge (every apply, incl. programmatic) — the
    # button's toggled(bool) is a TRUE edge, so the two must not be conflated.
    compare_toggled = pyqtSignal(str, bool)

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
        self._layout_sync_pending = False
        self._cards = [self._make_card()]
        self._split.addWidget(self._cards[0])
        self._split.splitterMoved.connect(
            lambda *_args: self._schedule_heatmap_layout_sync())
        self._toolbar = None
        detach_toolbar = getattr(self._cards[0], 'detach_toolbar', None)
        if callable(detach_toolbar) and getattr(self._cards[0], 'toolbar', None) is not None:
            self._toolbar = detach_toolbar(self)
            lay.addWidget(self._toolbar)
            self._configure_shared_toolbar()
        lay.addWidget(self._split, stretch=1)

        self._focused = 0
        self._previous_focused = 0
        self._linked = False
        self._levels_locked = False
        self.manager.active_changed.connect(self.refresh_focus_style)
        self.manager.views_changed.connect(self.refresh_focus_style)
        # Swallows the toggled(bool) edge during programmatic
        # sync_compare_buttons so state→button seeding never loops back as a
        # compare_toggled write. Set before the buttons are wired.
        self._suppress_compare_edge = False

        # Bottom row: [ViewTabBar ........... 关闭对比窗格 | 联动缩放 | 锁定色阶].
        # The toggles live on THIS page (not inside the shared ViewTabBar,
        # which the time-domain section reuses unchanged).
        self._compare_row = QWidget(self)
        self._compare_row.setObjectName("analysisCompareRow")
        self._compare_row.setAttribute(Qt.WA_StyledBackground, True)
        # 2026-06-13: this bottom row is the analysis section's view-tab bar.
        # Give it the same chrome as the time-domain dock (#timeViewBottomDock):
        # a light #fbfcff bar with a 1px top divider, so the View 1/2/3 tabs
        # read as a real bar instead of floating on the page. An explicit
        # background (not the old WA_TranslucentBackground + transparent QSS)
        # is what paints the bar — WA_StyledBackground keeps it from falling
        # back to the platform grey (lesson no-gray-bg-embedded-widgets).
        self._compare_row.setStyleSheet(_COMPARE_ROW_QSS)
        row = QHBoxLayout(self._compare_row)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(6)

        # ViewTabBar's ctor is (manager, parent) — pass the manager, NOT self.
        # Analysis split adds/removes pane 2 inside the ACTIVE view, unlike
        # TimeDomain's two-View merge/pair semantics.
        self.tabbar = ViewTabBar(
            manager,
            self._compare_row,
            split_action_mode='active_pane',
            active_split_provider=self.pane_count,
            split_action_labels={
                'split': "添加对比窗格",
                'replace': "添加对比窗格",
                'clear': "关闭对比窗格",
            },
        )
        row.addWidget(self.tabbar, 1)

        self.btn_link = self._make_toggle(
            "联动缩放", "两个分屏同步缩放/平移（X 轴，热力图含 Y 轴）")
        self.btn_lock_levels = self._make_toggle(
            "锁定色阶", "两个热力图共用同一色阶范围；拖动一格 colorbar 另一格跟随")
        row.addWidget(self.btn_link, 0)
        row.addWidget(self.btn_lock_levels, 0)
        self.btn_link.toggled.connect(self._on_link_button_toggled)
        self.btn_lock_levels.toggled.connect(self._on_lock_button_toggled)
        # 联动缩放 + 锁定色阶 defaults mirror AnalysisViewState.compare.
        # Seed under suppression so no compare_toggled fires at construction.
        self.sync_compare_buttons(x_linked=True, levels_locked=True)
        self.set_linked(True)
        self.set_levels_locked(True)

        lay.addWidget(self._compare_row)

        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()

    # -- pane management -----------------------------------------------
    def _make_card(self):
        card = self._card_factory()
        # Keep the card eligible for the shared #chartCard chrome. Focus itself
        # is painted by _ChartCard.set_focus_marker(), matching TimeDomain.
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.installEventFilter(self)
        canvas = getattr(card, 'canvas', None)
        if canvas is not None:
            signal = getattr(canvas, 'layout_geometry_changed', None)
            if signal is not None:
                try:
                    signal.connect(self._schedule_heatmap_layout_sync)
                except Exception:
                    pass
            levels_rebased = getattr(canvas, 'levels_rebased', None)
            if levels_rebased is not None:
                try:
                    levels_rebased.connect(self._on_canvas_levels_rebased)
                except Exception:
                    pass
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

    def grab_combined_pixmap(self, scale: float = 2.0):
        """Return every pane's canvas pixels composited side-by-side.

        Single-pane: the lone canvas's ``grab_pixmap(scale)`` (byte-identical
        width to ``pane_canvas(0).grab_pixmap(scale)``). Split: each pane's
        ``grab_pixmap`` laid out left-to-right with a thin white gutter,
        mirroring the time-domain ``chart_stack._combined_split_pixmap`` so
        both export paths read the same. Device-pixel-ratio is normalized to
        1.0 on each grab BEFORE composing so the widths add in real pixels
        (a Retina 2× DPR pixmap would otherwise report half its pixel width
        to ``width()``, mis-sizing the canvas). Null/degenerate grabs are
        skipped; an all-null result returns ``None``.
        """
        from PyQt5.QtGui import QPainter, QPixmap
        from PyQt5.QtCore import Qt

        pixes = []
        for card in self._cards:
            canvas = getattr(card, 'canvas', None)
            if canvas is None:
                continue
            pix = canvas.grab_pixmap(scale=scale)
            if pix is None or pix.isNull():
                continue
            if abs(pix.devicePixelRatioF() - 1.0) >= 1e-9:
                norm = QPixmap.fromImage(pix.toImage())
                norm.setDevicePixelRatio(1.0)
                pix = norm
            pixes.append(pix)
        if not pixes:
            return None
        if len(pixes) == 1:
            return pixes[0]
        gap = max(1, int(round(4 * scale)))
        w = sum(p.width() for p in pixes) + gap * (len(pixes) - 1)
        h = max(p.height() for p in pixes)
        out = QPixmap(w, h)
        out.fill(Qt.white)
        painter = QPainter(out)
        x = 0
        for p in pixes:
            painter.drawPixmap(x, 0, p)
            x += p.width() + gap
        painter.end()
        return out

    def enter_split(self) -> None:
        if len(self._cards) >= 2:
            return
        card = self._make_card()
        self._cards.append(card)
        detach_toolbar = getattr(card, 'detach_toolbar', None)
        if self._toolbar is not None and callable(detach_toolbar):
            hidden_toolbar = detach_toolbar(card)
            hidden_toolbar.hide()
        self._split.addWidget(card)
        total = max(2, self._split.width())
        left = max(1, total // 2)
        self._split.setSizes([left, max(1, total - left)])
        self._configure_shared_toolbar()
        self.set_linked(self._linked)
        self.set_levels_locked(self._levels_locked)
        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        self.tabbar.refresh_split_controls()
        self._schedule_heatmap_layout_sync()

    def _configure_shared_toolbar(self) -> None:
        toolbar = getattr(self, '_toolbar', None)
        if toolbar is None:
            return
        toolbar._action_delegate_provider = self._focused_nav_delegate
        toolbar._peer_toolbars_provider = self._peer_toolbars
        toolbar._save_pixmap_provider = self.grab_combined_pixmap
        if self._cards:
            self._cards[0]._options_canvas_provider = self.focused_canvas

    def _focused_nav_delegate(self):
        if self._focused <= 0 or self._focused >= len(self._cards):
            return None
        return getattr(self._cards[self._focused], 'toolbar', None)

    def _peer_toolbars(self):
        if len(self._cards) < 2:
            return []
        return [
            toolbar for toolbar in (
                getattr(card, 'toolbar', None) for card in self._cards[1:]
            )
            if toolbar is not None
        ]

    def focused_canvas(self):
        return self.pane_canvas(self.focused_index())

    def exit_split(self) -> None:
        if len(self._cards) < 2:
            return
        self.set_linked(False)
        # Tear down level-lock signal wiring before the pane is destroyed.
        self._disconnect_level_lock_handlers(self._heatmap_canvases())
        card = self._cards.pop(1)
        card.removeEventFilter(self)
        card.setParent(None)
        card.deleteLater()
        self.set_focused_index(0)
        self._previous_focused = 0
        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        self.tabbar.refresh_split_controls()
        self._schedule_heatmap_layout_sync()

    def _sync_card_hint_bars(self) -> None:
        """Analysis compare panes do not show per-card shortcut hint bands."""
        show = len(self._cards) == 1
        for card in self._cards:
            bar = getattr(card, '_hint_bar', None)
            if bar is not None:
                bar.setVisible(show)

    # -- focus ----------------------------------------------------------
    def focused_index(self) -> int:
        return self._focused

    def previous_focused_index(self) -> int:
        return self._previous_focused

    def set_focused_index(self, idx: int) -> None:
        idx = max(0, min(idx, len(self._cards) - 1))
        if idx == self._focused:
            self._apply_focus_style()
            return
        self._previous_focused = self._focused
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

    def _active_view_focus_accent(self) -> str:
        try:
            accent = self.manager.get(self.manager.active).tab_color
        except Exception:
            accent = None
        if not accent or not QColor(accent).isValid():
            return _FOCUS_ACCENT
        return accent

    def refresh_focus_style(self, *_args) -> None:
        self._apply_focus_style()

    def _apply_focus_style(self) -> None:
        focus_accent = self._active_view_focus_accent()
        for i, card in enumerate(self._cards):
            focused = i == self._focused and len(self._cards) > 1
            marker = getattr(card, 'set_focus_marker', None)
            if callable(marker):
                marker(focus_accent if focused else None)
            # Drop the legacy per-card focus border so the pyqtgraph data area
            # does not get inset by 1px and the shared #chartCard QSS wins.
            if card.styleSheet():
                card.setStyleSheet("")

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

    # -- compare: locked color levels (spec §6.1) -----------------------
    def _heatmap_canvases(self):
        """Canvases that carry an ImageItem + colorbar (heatmap sections).

        Line sections (FFT) have no ``_img``/``_cbar`` — level locking is a
        no-op there and the toggle button stays hidden.
        """
        out = []
        for card in self._cards:
            canvas = getattr(card, 'canvas', None)
            if canvas is not None and hasattr(canvas, '_img') and \
                    hasattr(canvas, '_cbar'):
                out.append(canvas)
        return out

    def _schedule_heatmap_layout_sync(self) -> None:
        if self._layout_sync_pending:
            return
        self._layout_sync_pending = True
        QTimer.singleShot(0, self.sync_heatmap_layouts)

    def sync_heatmap_layouts(self) -> None:
        """Align plot-area geometry across split analysis panes.

        QSplitter only equalizes the outer cards. Each pyqtgraph PlotItem
        still auto-sizes its title and axes independently, so split panes can
        drift by several pixels. Pin pane-local reserves to shared maxima.
        """
        self._layout_sync_pending = False
        canvases = [
            c for c in self._heatmap_canvases()
            if hasattr(c, 'prepare_split_layout_alignment')
            and hasattr(c, 'heatmap_layout_metrics')
            and hasattr(c, 'apply_split_layout_alignment')
            and hasattr(c, 'recommended_split_title_width')
        ]
        if len(canvases) < 2:
            for c in canvases:
                try:
                    c.reset_split_layout_alignment()
                except Exception:
                    pass
        else:
            title_width = min(c.recommended_split_title_width() for c in canvases)
            for c in canvases:
                c.prepare_split_layout_alignment(title_width)

            metrics = [c.heatmap_layout_metrics() for c in canvases]
            left_width = max(m.get('left_axis_width', 0.0) for m in metrics)
            main_bottom_height = max(
                m.get('main_bottom_axis_height', 0.0) for m in metrics)
            slice_bottom_height = max(
                m.get('slice_bottom_axis_height', 0.0) for m in metrics)

            for c in canvases:
                c.apply_split_layout_alignment(
                    left_axis_width=left_width,
                    main_bottom_axis_height=main_bottom_height,
                    slice_bottom_axis_height=slice_bottom_height,
                )

            metrics = [c.heatmap_layout_metrics() for c in canvases]
            slice_right_reserve = max(
                m.get('slice_right_reserve', 0.0) for m in metrics)
            for c in canvases:
                c.apply_split_layout_alignment(
                    left_axis_width=left_width,
                    main_bottom_axis_height=main_bottom_height,
                    slice_bottom_axis_height=slice_bottom_height,
                    slice_right_reserve=slice_right_reserve,
                )

        line_canvases = [
            c for c in (
                getattr(card, 'canvas', None) for card in self._cards
            )
            if hasattr(c, 'prepare_split_layout_alignment')
            and hasattr(c, 'line_layout_metrics')
            and hasattr(c, 'apply_split_layout_alignment')
            and hasattr(c, 'recommended_split_title_width')
        ]
        if len(line_canvases) < 2:
            for c in line_canvases:
                try:
                    c.reset_split_layout_alignment()
                except Exception:
                    pass
            return

        title_width = min(c.recommended_split_title_width() for c in line_canvases)
        for c in line_canvases:
            c.prepare_split_layout_alignment(title_width)

        metrics = [c.line_layout_metrics() for c in line_canvases]
        left_width = max(m.get('left_axis_width', 0.0) for m in metrics)
        amp_bottom_height = max(
            m.get('amp_bottom_axis_height', 0.0) for m in metrics)
        time_bottom_height = max(
            m.get('time_bottom_axis_height', 0.0) for m in metrics)

        # Right reserves are intentionally NOT cross-synced for line canvases.
        # The time-preview overlay Y-axes (one per extra source) are a per-pane
        # feature that already occupy their own layout columns. Pushing the
        # global-max reserve (spacer + overlay) onto every pane's right SPACER
        # double-counts the overlay width — it shrank both panes' plot areas and
        # inset an overlay-free pane by the other pane's overlay reserve. Each
        # pane keeps the thin frame set by prepare() and is inset only by its
        # OWN overlay axes; the FFT spectrum row (no overlay) stays aligned via
        # the shared left-axis width and bottom-axis heights below.
        for c in line_canvases:
            c.apply_split_layout_alignment(
                left_axis_width=left_width,
                amp_bottom_axis_height=amp_bottom_height,
                time_bottom_axis_height=time_bottom_height,
            )

    def _is_heatmap_section(self) -> bool:
        canvas = getattr(self._cards[0], 'canvas', None)
        return canvas is not None and hasattr(canvas, '_img')

    def set_levels_locked(self, locked: bool) -> None:
        """Lock/unlock a shared color scale across the two heatmap panes.

        On lock: compute the COMBINED min/max across both panes'
        ``_matrix_disp`` and push it to both ``_img`` + ``_cbar`` (wrapped in
        ``blockSignals`` so the programmatic ``setLevels`` cannot masquerade
        as a user drag — M2: ``setLevels`` is silent, but block defensively),
        then subscribe each canvas's ``levels_changed`` (emitted only on a
        real colorbar drag) to ``_on_locked_levels_changed`` so a drag on one
        pane propagates to the other. On unlock: disconnect.

        pg signals expose no "is this slot connected?" query, so re-locking
        disconnects first (guarded by ``try/except TypeError`` for the
        not-connected case) before reconnecting — otherwise repeated locks
        multi-connect and a single drag would fire propagation N times.
        """
        self._levels_locked = bool(locked)
        canvases = self._heatmap_canvases()
        # Always disconnect first (idempotent re-lock + clean unlock).
        self._disconnect_level_lock_handlers(canvases)
        if not self._levels_locked or len(canvases) < 2:
            self._refresh_compare_buttons()
            return
        lo, hi = self._combined_levels(canvases)
        if lo is not None:
            for c in canvases:
                self._set_canvas_levels(c, lo, hi)
        for c in canvases:
            c.levels_changed.connect(self._on_locked_levels_changed)
        self._refresh_compare_buttons()

    def is_levels_locked(self) -> bool:
        return self._levels_locked

    def _disconnect_level_lock_handlers(self, canvases) -> None:
        for c in canvases:
            try:
                c.levels_changed.disconnect(self._on_locked_levels_changed)
            except TypeError:
                pass

    def _on_canvas_levels_rebased(self) -> None:
        if not self._levels_locked:
            return
        canvases = self._heatmap_canvases()
        if len(canvases) < 2:
            return
        if not all(getattr(c, 'has_result', lambda: False)() for c in canvases):
            return
        self.set_levels_locked(True)

    @staticmethod
    def _combined_levels(canvases):
        """Merged (min, max) across every pane's display-space matrix.

        Falls back to each ``_img``'s current levels when a pane has no
        matrix yet (e.g. one pane computed, the other still empty)."""
        los, his = [], []
        for c in canvases:
            lv = c._img.getLevels()
            if lv is not None and lv[0] is not None:
                lo = float(lv[0])
                hi = float(lv[1])
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    los.append(lo)
                    his.append(hi)
                    continue
            m = getattr(c, '_matrix_disp', None)
            if m is not None and np.size(m):
                lo = float(np.nanmin(m))
                hi = float(np.nanmax(m))
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    los.append(lo)
                    his.append(hi)
        if not los:
            return None, None
        return min(los), max(his)

    @staticmethod
    def _set_canvas_levels(canvas, lo, hi) -> None:
        """Programmatically set both the image and colorbar levels, blocking
        signals so the colorbar's ``sigLevelsChanged`` cannot re-enter the
        lock propagation as a phantom drag."""
        canvas._img.setLevels((lo, hi))
        cbar = getattr(canvas, '_cbar', None)
        if cbar is not None:
            cbar.blockSignals(True)
            cbar.setLevels((lo, hi))
            cbar.blockSignals(False)

    def _on_locked_levels_changed(self, lo: float, hi: float) -> None:
        """A user dragged one pane's colorbar while locked → apply the same
        (lo, hi) to ALL heatmap panes (incl. the source, harmlessly). The
        block in ``_set_canvas_levels`` stops the propagated ``setLevels``
        from re-emitting and looping."""
        if not self._levels_locked:
            return
        for c in self._heatmap_canvases():
            self._set_canvas_levels(c, float(lo), float(hi))

    # -- compare toggle buttons -----------------------------------------
    def _make_toggle(self, text, tooltip):
        btn = QToolButton(self._compare_row)
        btn.setObjectName("analysisCompareToggle")
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedHeight(22)
        return btn

    def _on_link_button_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        self.set_linked(on)
        self.compare_toggled.emit('x_linked', bool(on))

    def _on_lock_button_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        self.set_levels_locked(on)
        self.compare_toggled.emit('levels_locked', bool(on))

    def sync_compare_buttons(self, *, x_linked, levels_locked) -> None:
        """State → buttons (NO edge emit).

        Called by MainWindow on view switch / init to seed the toggle states
        from ``state.compare`` without firing ``compare_toggled`` (which would
        write the value straight back, a no-op loop). Guarded by
        ``_suppress_compare_edge`` so the resulting ``toggled`` signals are
        swallowed by the handlers above."""
        self._suppress_compare_edge = True
        try:
            self.btn_link.setChecked(bool(x_linked))
            self.btn_lock_levels.setChecked(bool(levels_locked))
        finally:
            self._suppress_compare_edge = False
        self._refresh_compare_buttons()

    def _refresh_compare_buttons(self) -> None:
        """Visibility/enabled state: compare toggles only matter while split.
        锁定色阶 is heatmap-only (line sections have no colorbar)."""
        split = len(self._cards) > 1
        self.btn_link.setVisible(split)
        self.btn_lock_levels.setVisible(split and self._is_heatmap_section())
