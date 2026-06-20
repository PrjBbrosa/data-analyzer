"""ChartStack — the centre-pane QWidget coordinator."""
from PyQt5.QtCore import QEvent, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QFrame, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from ..pg_canvases import TimeDomainCanvasPG
from ..pg_canvas.heatmap_canvas import PgHeatmapCanvas
from ..pg_canvas.line_canvas import PgLineCanvas
from ..widgets import StatsStrip
from ..analysis_section_page import AnalysisSectionPage
from ..analysis_view_state import AnalysisViewState
from ..view_state import ViewManager

from ._helpers import (
    _grab_pixmap_hidpi,
    _pixmap_as_device_pixels,
    _apply_mdi_icons,
    _HIDPI_EXPORT_SCALE,
    _STATS_STRIP_ENABLED,
    _MODE_TO_INDEX,
    _INDEX_TO_MODE,
    _BOTTOM_HINT_PERSISTENT,
)
from .cards import _ChartCard, TimeChartCard
from .cursor_pill import CursorPill
from .toolbar import PgNavigationToolbar


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    cursor_mode_changed = pyqtSignal(str)
    annotation_enabled_changed = pyqtSignal(str, bool)
    image_copied = pyqtSignal(str)  # legacy status text signal
    image_captured = pyqtSignal(QPixmap)  # final pixmap for MainWindow publishing
    # Emitted when the focused time card changes while side-by-side (split) is
    # active. Carries True when the secondary card is focused, False for the
    # primary. MainWindow uses it to route channel-check replots to the right
    # canvas; it is inert (never emitted) outside split mode.
    focus_changed = pyqtSignal(bool)
    home_triggered = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # QSS (ChartStack { border-radius:10px; background:#fff }) only paints on
        # a plain QWidget subclass once WA_StyledBackground is set; without it Qt
        # skips the styled fill/border and the rounded card never renders.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget(self)
        self.stack.setAttribute(Qt.WA_TranslucentBackground, True)
        self.stack.setAttribute(Qt.WA_NoSystemBackground, True)
        self.stack.setAutoFillBackground(False)
        self.canvas_time = TimeDomainCanvasPG(self)
        self._time_card = TimeChartCard(self.canvas_time)
        self._primary_plot_mode = self._time_card.plot_mode()
        self._primary_cursor_mode = self._time_card.cursor_mode()
        self._time_page = QWidget(self.stack)
        self._time_page.setObjectName("timeDomainPage")
        self._time_page.setAttribute(Qt.WA_TranslucentBackground, True)
        self._time_page.setAttribute(Qt.WA_NoSystemBackground, True)
        self._time_page.setAutoFillBackground(False)
        time_lay = QVBoxLayout(self._time_page)
        time_lay.setContentsMargins(0, 0, 0, 0)
        time_lay.setSpacing(0)
        self._time_toolbar = self._time_card.detach_toolbar(self._time_page)
        time_lay.addWidget(self._time_toolbar)
        self._time_split = QSplitter(Qt.Horizontal, self._time_page)
        self._time_split.setObjectName("timeDomainSplit")
        self._time_split.setAttribute(Qt.WA_TranslucentBackground, True)
        self._time_split.setAttribute(Qt.WA_NoSystemBackground, True)
        self._time_split.setAutoFillBackground(False)
        self._time_split.setChildrenCollapsible(False)
        self._time_split.addWidget(self._time_card)
        time_lay.addWidget(self._time_split, stretch=1)
        self._time_bottom_dock = QFrame(self._time_page)
        self._time_bottom_dock.setObjectName("timeViewBottomDock")
        self._time_bottom_dock.setAttribute(Qt.WA_StyledBackground, True)
        self._time_bottom_dock.setAttribute(Qt.WA_TranslucentBackground, True)
        self._time_bottom_dock.setAttribute(Qt.WA_NoSystemBackground, True)
        self._time_bottom_dock.setAutoFillBackground(False)
        dock_lay = QVBoxLayout(self._time_bottom_dock)
        dock_lay.setContentsMargins(0, 0, 0, 0)
        dock_lay.setSpacing(0)
        self._time_hint_bar = self._time_card.detach_bottom_hint_bar(
            self._time_bottom_dock
        )
        self._configure_time_hint_bar()
        dock_lay.addWidget(self._time_hint_bar)
        time_lay.addWidget(self._time_bottom_dock)
        self._secondary_card = None
        # Focus routing (P2 Task 9 Step 5): the focused time card receives
        # channel-check replots while side-by-side is active. Defaults to the
        # primary card; a click on either card switches focus (see
        # _install_focus_filter / eventFilter). Outside split mode the
        # focused card is always the primary and the property is unset.
        self._focused_card = self._time_card
        self._focus_accent = "#2d7ff9"
        self._install_focus_filter(self._time_card)
        # V7 Step 1: the three analysis sections become per-section
        # AnalysisSectionPage instances (QSplitter pane container + per-section
        # ViewTabBar). ChartStack owns the three ViewManagers because V6's
        # ViewTabBar dereferences its manager in __init__ (manager.views_changed
        # .connect + refresh()) and cannot accept None; MainWindow reads them via
        # ``self.chart_stack.analysis_managers`` and owns all routing/compute.
        # ``canvas_fft`` / ``_fft_card`` etc. survive as @property aliases onto
        # pane 0 so the large existing call surface stays unchanged (single-pane
        # behaviour == pre-V7).
        self.analysis_managers = {
            'fft': ViewManager(self, state_factory=AnalysisViewState),
            'fft_time': ViewManager(self, state_factory=AnalysisViewState),
            'order': ViewManager(self, state_factory=AnalysisViewState),
        }

        def _fft_card_factory():
            return _ChartCard(
                PgLineCanvas(self), annotations=True, chart_mode='fft'
            )

        def _fft_time_card_factory():
            return _ChartCard(
                PgHeatmapCanvas(self, with_slice=True),
                annotations=True, chart_mode='fft_time',
            )

        def _order_card_factory():
            canvas = PgHeatmapCanvas(self, with_slice=True)
            canvas.set_default_axis_labels(x_label='Time (s)', y_label='Order')
            # Order slice toggle reads 时间 / 阶次 (Y axis is order). Default
            # to the 阶次 (Y) slice — the common case is "one order's amplitude
            # over time".
            canvas.set_slice_button_labels('时间', '阶次')
            canvas.set_slice_direction('y')
            return _ChartCard(canvas, annotations=True, chart_mode='order')

        self.page_fft = AnalysisSectionPage(
            section='fft', manager=self.analysis_managers['fft'],
            card_factory=_fft_card_factory, parent=self,
        )
        self.page_fft_time = AnalysisSectionPage(
            section='fft_time', manager=self.analysis_managers['fft_time'],
            card_factory=_fft_time_card_factory, parent=self,
        )
        self.page_order = AnalysisSectionPage(
            section='order', manager=self.analysis_managers['order'],
            card_factory=_order_card_factory, parent=self,
        )
        self.stack.addWidget(self._time_page)
        self.stack.addWidget(self.page_fft)
        self.stack.addWidget(self.page_fft_time)
        self.stack.addWidget(self.page_order)
        for page in (self.page_fft, self.page_fft_time, self.page_order):
            page.setAttribute(Qt.WA_TranslucentBackground, True)
            page.setAttribute(Qt.WA_NoSystemBackground, True)
            page.setAutoFillBackground(False)
            self._connect_analysis_card_signals(page._cards[0])
        # The time card's copy button lives on the shared toolbar; route it to
        # the focused pane so 复制为图片 captures whichever pane is focused.
        self._time_card.copy_image_requested.connect(
            lambda: self._copy_card_image(self.focused_card())
        )
        # Shared-toolbar home/save still target the focused pane; pan/zoom and
        # history buttons broadcast to the visible peer toolbar below.
        self._time_toolbar._action_delegate_provider = self._focused_nav_delegate
        self._time_toolbar._peer_toolbars_provider = (
            lambda: [self._secondary_card.toolbar]
            if (self.split_active() and self._secondary_card is not None)
            else []
        )
        self._time_toolbar._save_pixmap_provider = self._combined_split_pixmap
        self._time_toolbar.home_triggered.connect(self.home_triggered.emit)
        # 图表选项 on the shared toolbar opens for the focused pane's canvas.
        self._time_card._options_canvas_provider = self.focused_canvas
        # Mirror the focused pane's pan/zoom state onto the shared toolbar
        # icons. Connected AFTER the primary card's own _on_nav_mode_toggled
        # (bound during _ChartCard.__init__) so this runs LAST in the action's
        # triggered emission and wins — otherwise the card handler would
        # re-assert the primary's icon after a click that forwarded to the
        # secondary. Idempotent; no-op outside split.
        for _key in ('pan', 'zoom'):
            _act = self._time_toolbar._actions_by_key.get(_key)
            if _act is not None:
                _act.triggered.connect(
                    lambda _checked=False: self._sync_shared_nav_highlight()
                )
        self._time_toolbar.mouse_mode_changed.connect(
            lambda *_a: self._sync_shared_nav_highlight()
        )
        lay.addWidget(self.stack, stretch=1)

        # Stats strip retained for later re-enable, but hidden from the UI for now.
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)
        self.stats_strip.setVisible(_STATS_STRIP_ENABLED)

        # Per-pane draggable cursor pills. The primary pill is always present;
        # the secondary pill is created when split view is first opened.
        self._pill = CursorPill(self.stack)
        self._pill.setVisible(False)
        self._pill_secondary = None  # created/destroyed with enter/exit_split
        self._active_cursor_card = self._time_card
        # Pass the SOURCE canvas so the pill picks the right per-pane cursor
        # mode (single/dual formatting) and anchors over the emitting pane.
        self.canvas_time.cursor_info.connect(
            lambda text: self._on_cursor_info(text, self.canvas_time)
        )
        self.canvas_time.dual_cursor_info.connect(
            lambda text: self._on_dual_cursor_info(text, self.canvas_time)
        )
        if hasattr(self.canvas_time, 'dual_cursor_rows'):
            self.canvas_time.dual_cursor_rows.connect(self._pill.set_dual_rows)
        self.stack.currentChanged.connect(lambda _i: self._reposition_pill())

        # Relay time-card control signals up to MainWindow consumers.
        self._time_card.plot_mode_changed.connect(self._on_shared_plot_mode_changed)
        self._time_card.cursor_mode_changed.connect(
            self._on_shared_cursor_mode_changed
        )
        # The time card's annotation relay; analysis cards (pane 0) are wired in
        # _connect_analysis_card_signals during page construction above.
        self._time_card.annotation_enabled_changed.connect(
            lambda enabled: self.annotation_enabled_changed.emit('time', enabled)
        )
        self._time_card.tick_density_changed.connect(
            self._on_card_tick_density_changed
        )

        # Initial sync: stats_strip is currently disabled at the product level.
        self.stats_strip.setVisible(
            _STATS_STRIP_ENABLED and self.current_mode() == 'time'
        )

    # ---- analysis-section page accessors (V7 Step 1) ----
    # The three analysis sections are AnalysisSectionPage instances; pane 0 of
    # each page hosts the legacy single-canvas/card. These @property aliases
    # keep the pre-V7 attribute names (canvas_fft / _fft_card / ...) pointing at
    # pane 0 so MainWindow's render/copy/annotation/tick call surface and the
    # existing test suite stay unchanged while single-pane behaviour is
    # byte-identical to before.
    def _connect_analysis_card_signals(self, card):
        """Wire copy + annotation relays for an analysis pane card.

        Called for pane 0 at construction and (via MainWindow re-wiring) is the
        single place a freshly split pane's card would be hooked. ``_chart_mode``
        is the card's section key ('fft'/'fft_time'/'order')."""
        card.copy_image_requested.connect(
            lambda c=card: self._copy_card_image(c)
        )
        mode = card._chart_mode
        card.annotation_enabled_changed.connect(
            lambda enabled, m=mode: self.annotation_enabled_changed.emit(m, enabled)
        )
        card.tick_density_changed.connect(self._on_card_tick_density_changed)

    def _all_cards(self):
        cards = [self._time_card]
        if self._secondary_card is not None:
            cards.append(self._secondary_card)
        for page in (self.page_fft, self.page_fft_time, self.page_order):
            cards.extend(page._cards)
        return [card for card in cards if card is not None]

    def _on_card_tick_density_changed(self, x, y):
        self.set_tick_density_controls(x, y)
        self.tick_density_changed.emit(int(x), int(y))

    def set_tick_density_controls(self, x, y):
        for card in self._all_cards():
            setter = getattr(card, "set_tick_density_controls", None)
            if callable(setter):
                setter(x, y)

    @property
    def page_for_mode(self):
        return {
            'fft': self.page_fft,
            'fft_time': self.page_fft_time,
            'order': self.page_order,
        }

    @property
    def _fft_card(self):
        return self.page_fft._cards[0]

    @property
    def _fft_time_card(self):
        return self.page_fft_time._cards[0]

    @property
    def _order_card(self):
        return self.page_order._cards[0]

    @property
    def canvas_fft(self):
        return self.page_fft.pane_canvas(0)

    @property
    def canvas_fft_time(self):
        return self.page_fft_time.pane_canvas(0)

    @property
    def canvas_order(self):
        return self.page_order.pane_canvas(0)

    def _configure_time_hint_bar(self):
        # Time-view docked footer. This IS the time card's detached _hint_bar
        # (see detach_bottom_hint_bar), so we re-assert the same edge-anchored
        # layout after clearing it: the rotating row hugs the LEFT edge
        # (stretch=1), the discovery hint hugs the RIGHT edge (提示位置 左右靠边).
        # We only tune the dock margins / height here.
        self._time_hint_bar.setFixedHeight(20)
        lay = self._time_hint_bar.layout()
        while lay.count():
            lay.takeAt(0)
        lay.setContentsMargins(8, 1, 8, 1)
        lay.setSpacing(0)
        lay.addWidget(self._time_card._hint_context, 1)
        lay.addWidget(self._time_card._hint_discovery, 0)

    def count(self):
        return self.stack.count()

    def split_active(self):
        return (
            self._secondary_card is not None
            and self.current_mode() == 'time'
            and self._secondary_card.isVisibleTo(self._time_split)
        )

    def secondary_canvas(self):
        if self._secondary_card is None:
            return None
        return self._secondary_card.canvas

    def focused_card(self):
        """Return the time card that channel-check replots target.

        Outside split mode (or when the secondary card has been hidden), the
        focused card is always the primary ``_time_card``; this keeps the
        non-split behaviour byte-identical. While split is active, the focused
        card follows the last card the user clicked."""
        if not self.split_active():
            return self._time_card
        if self._focused_card is self._secondary_card and self._secondary_card is not None:
            return self._secondary_card
        return self._time_card

    def focused_canvas(self):
        """Canvas of :meth:`focused_card`. Returns the primary time canvas
        whenever split is inactive, so callers that previously wrote to
        ``self.canvas_time`` keep the same target outside compare mode."""
        return self.focused_card().canvas

    def _focused_nav_delegate(self):
        """Toolbar a shared-toolbar nav click should act on, or None.

        While side-by-side is active and the secondary pane is focused, return
        the secondary card's own canvas-bound toolbar so home/pan/zoom/back/
        forward/save operate on the secondary canvas with ITS view history and
        mouse mode. Otherwise None ⇒ the shared (primary) toolbar handles it,
        keeping non-split / primary-focused behaviour byte-identical."""
        if (self.split_active()
                and self._secondary_card is not None
                and self._focused_card is self._secondary_card):
            return self._secondary_card.toolbar
        return None

    def _sync_shared_nav_highlight(self):
        """Repaint the shared toolbar's pan/zoom highlight to match the focused
        pane's current mouse mode.

        Cosmetic only: the shared toolbar object stays bound to the primary
        canvas (its ``mode`` must keep driving the primary's replot mouse-mode
        re-apply), so we only repaint its icon active-state. A later primary
        replot can transiently re-assert the primary's icon; the next focus or
        pan/zoom change corrects it."""
        toolbar = getattr(self, '_time_toolbar', None)
        if toolbar is None:
            return
        target = self.focused_card().toolbar
        mode = str(getattr(target, 'mode', '')).lower()
        key = 'pan' if 'pan' in mode else ('zoom' if 'zoom' in mode else '')
        _apply_mdi_icons(toolbar, active_key=key)

    def _card_for_canvas(self, canvas):
        """Owning time card for a cursor-emitting ``canvas`` (primary fallback)."""
        if (canvas is not None
                and self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            return self._secondary_card
        return self._time_card

    def _combined_split_pixmap(self):
        """Return primary+secondary canvas pixels side-by-side while split."""
        if not self.split_active() or self._secondary_card is None:
            return None
        left = _grab_pixmap_hidpi(self.canvas_time)
        right = _grab_pixmap_hidpi(self._secondary_card.canvas)
        if left is None or right is None or left.isNull() or right.isNull():
            return None
        gap = 8
        out = QPixmap(
            left.width() + gap + right.width(),
            max(left.height(), right.height()),
        )
        out.fill(Qt.white)
        painter = QPainter(out)
        painter.drawPixmap(0, 0, left)
        painter.drawPixmap(left.width() + gap, 0, right)
        painter.end()
        return out

    def _cursor_mode_for_canvas(self, canvas):
        """Per-pane cursor mode ('off'/'single'/'dual') for the pill formatter.

        Mirrors :meth:`plot_mode_for_canvas`: the readout layout depends on the
        mode of the pane that emitted it, not always the primary's."""
        if (canvas is not None
                and self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            return self._secondary_card.cursor_mode()
        return self._primary_cursor_mode

    def cursor_mode_for_canvas(self, canvas):
        """Public per-pane cursor-mode accessor, matching plot_mode_for_canvas."""
        return self._cursor_mode_for_canvas(canvas)

    def _shared_time_controls_follow_secondary(self):
        return (
            self.split_active()
            and self._secondary_card is not None
            and self._focused_card is self._secondary_card
        )

    def _set_shared_plot_mode_silent(self, mode):
        old = self._time_card.blockSignals(True)
        try:
            self._time_card.set_plot_mode(mode)
        finally:
            self._time_card.blockSignals(old)

    def _set_shared_cursor_mode_silent(self, mode):
        old = self._time_card.blockSignals(True)
        try:
            self._time_card.set_cursor_mode(mode)
        finally:
            self._time_card.blockSignals(old)

    def _sync_shared_time_controls_to_focus(self):
        """Reflect the focused pane's state on the shared time toolbar."""
        if self._shared_time_controls_follow_secondary():
            plot_mode = self._secondary_card.plot_mode()
            cursor_mode = self._secondary_card.cursor_mode()
        else:
            plot_mode = self._primary_plot_mode
            cursor_mode = self._primary_cursor_mode
        self._set_shared_plot_mode_silent(plot_mode)
        self._set_shared_cursor_mode_silent(cursor_mode)

    def set_focused_card(self, card):
        """Make ``card`` the focused time card and repaint the focus border.

        No-op outside split mode and when the target is already focused. The
        ``focused`` dynamic property drives the QSS accent border; after every
        change both cards are unpolished/re-polished so the property selector
        re-evaluates (Qt does not re-apply property-keyed rules automatically).
        Emits :attr:`focus_changed` with True when the secondary is focused."""
        if not self.split_active():
            return
        if card not in (self._time_card, self._secondary_card):
            return
        if card is self._focused_card:
            # Still ensure the border reflects current state (e.g. just after
            # enter_split seeded the primary as focused).
            self._refresh_focus_borders()
            self._sync_shared_time_controls_to_focus()
            self._sync_shared_nav_highlight()
            return
        self._focused_card = card
        self._refresh_focus_borders()
        self._sync_secondary_controls_to_focus()
        self._sync_shared_nav_highlight()
        self.focus_changed.emit(card is self._secondary_card)

    def set_focus_accent(self, color):
        """Set the top-line accent color for the currently focused time card."""
        self._focus_accent = color or "#2d7ff9"
        self._refresh_focus_borders()

    def _refresh_focus_borders(self):
        """Sync the ``focused`` dynamic property + repaint for both cards.

        Only highlights while split is active; in single-pane mode neither card
        carries the property so the default ``#chartCard`` border applies."""
        active = self.split_active()
        focused = self._focused_card if active else None
        cards = [self._time_card]
        if self._secondary_card is not None:
            cards.append(self._secondary_card)
        for card in cards:
            want = active and card is focused
            if card.property("focused") != want:
                card.setProperty("focused", want)
            # Visual focus cue is the overlay accent strip (a QSS card border is
            # painted over by the full-bleed canvas). Color = focused view tab.
            marker = getattr(card, "set_focus_marker", None)
            if callable(marker):
                card.set_focus_marker(self._focus_accent if want else None)
            # Keep the dynamic-property polish cycle for any QSS keyed on it.
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def _install_focus_filter(self, card):
        """Watch mouse presses on a time card (and its canvas/viewport) so a
        click anywhere on the card focuses it. Installed once per card; the
        base card already filters its canvas for hint pausing, so stacking a
        second filter here is safe and order-independent.

        Also enables WA_StyledBackground so the #chartCard QSS border (and the
        focused-accent override) paints reliably on the plain QWidget card —
        without it Qt only paints the corners and the straight edges stay
        un-bordered, which would make the focus accent invisible behind the
        margin-0 toolbar/canvas children. The card already declares an explicit
        background-color in QSS, so the flag has no white-bleed side effect."""
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.installEventFilter(self)
        canvas = getattr(card, 'canvas', None)
        if canvas is not None:
            canvas.installEventFilter(self)
            glw = getattr(canvas, '_glw', None)
            viewport = None
            if glw is not None:
                try:
                    viewport = glw.viewport()
                except Exception:
                    viewport = None
            if viewport is not None:
                viewport.installEventFilter(self)

    def _card_for_object(self, obj):
        """Map a filtered object (card, canvas, or canvas viewport) back to its
        owning time card, or None if it belongs to neither time card."""
        for card in (self._time_card, self._secondary_card):
            if card is None:
                continue
            if obj is card:
                return card
            canvas = getattr(card, 'canvas', None)
            if canvas is None:
                continue
            if obj is canvas:
                return card
            glw = getattr(canvas, '_glw', None)
            if glw is not None:
                try:
                    viewport = glw.viewport()
                except Exception:
                    viewport = None
                if viewport is not None and obj is viewport:
                    return card
        return None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self.split_active():
            card = self._card_for_object(obj)
            if card is not None and card is not self._focused_card:
                self.set_focused_card(card)
        return super().eventFilter(obj, event)

    def enter_split(self):
        if self._secondary_card is None:
            canvas = TimeDomainCanvasPG(self)
            self._secondary_card = TimeChartCard(canvas)
            self._secondary_card.detach_toolbar(self._secondary_card).hide()
            self._secondary_card.detach_bottom_hint_bar(self._secondary_card).hide()
            self._set_secondary_time_controls_enabled(False)
            self._secondary_card.copy_image_requested.connect(
                lambda: self._copy_card_image(self._secondary_card)
            )
            self._secondary_card.tick_density_changed.connect(
                self._on_card_tick_density_changed
            )
            # Per-pane control routing (P2 Task 9 1b): the secondary card's
            # own 分屏/叠加/游标 segmented controls act on the SECONDARY canvas,
            # not the primary. Plot-mode flips need a replot of the secondary
            # (re-laid out subplot↔overlay), cursor flips toggle the secondary
            # canvas's cursor directly. We keep these inside ChartStack so the
            # secondary stays self-contained and never disturbs the primary.
            self._secondary_card.plot_mode_changed.connect(
                self._on_secondary_plot_mode_changed
            )
            self._secondary_card.cursor_mode_changed.connect(
                self._on_secondary_cursor_mode_changed
            )
            self._secondary_card.toolbar._peer_toolbars_provider = (
                lambda: [self._time_toolbar] if self.split_active() else []
            )
            self._secondary_card.toolbar.mouse_mode_changed.connect(
                lambda *_a: self._sync_shared_nav_highlight()
            )
            # The secondary pane has its own pill so both split panes can show
            # independent single/dual cursor readouts at the same time.
            if self._pill_secondary is None:
                self._pill_secondary = CursorPill(self.stack)
                self._pill_secondary.setVisible(False)
            canvas.cursor_info.connect(
                lambda text, c=canvas: self._on_cursor_info(text, c)
            )
            canvas.dual_cursor_info.connect(
                lambda text, c=canvas: self._on_dual_cursor_info(text, c)
            )
            if hasattr(canvas, 'dual_cursor_rows'):
                canvas.dual_cursor_rows.connect(self._pill_secondary.set_dual_rows)
            self._time_split.addWidget(self._secondary_card)
            self._install_focus_filter(self._secondary_card)
        self._secondary_card.setVisible(True)
        total = max(2, self._time_split.width())
        left = max(1, total // 2)
        self._time_split.setSizes([left, max(1, total - left)])
        # Entering split (re)seeds focus on the primary card and lights its
        # accent border; the secondary stays unfocused until clicked.
        self._focused_card = self._time_card
        self._refresh_focus_borders()
        self._sync_secondary_controls_to_focus()
        self._sync_shared_nav_highlight()

    def _on_secondary_plot_mode_changed(self, mode):
        """Replot the secondary canvas in the new layout (subplot↔overlay).

        Asks MainWindow to redraw the secondary pane while preserving its
        visible X window (see TimeDomain state-preservation lesson). The
        secondary card is the focused card whenever its controls are live, so
        we route through ``replot_secondary`` rather than disturbing the
        primary. No replot hook → silently no-op (secondary not yet wired)."""
        replot = getattr(self, '_replot_secondary_cb', None)
        if callable(replot):
            replot()

    def _on_secondary_cursor_mode_changed(self, mode):
        """Toggle the secondary canvas's cursor (off/single/dual) in place."""
        if mode == 'off' and self._pill_secondary is not None:
            self._pill_secondary.clear()
        canvas = self._secondary_card.canvas
        canvas.set_cursor_visible(mode != 'off')
        canvas.set_dual_cursor_mode(mode == 'dual')

    def set_secondary_replot_callback(self, cb):
        """MainWindow registers a callable that replots the secondary canvas
        preserving its X window. Used when the secondary card's own plot-mode
        control flips (subplot↔overlay needs a fresh layout)."""
        self._replot_secondary_cb = cb

    def exit_split(self):
        if self._secondary_card is not None:
            self._secondary_card.setVisible(False)
        if self._pill_secondary is not None:
            self._pill_secondary.setVisible(False)
            self._pill_secondary.clear()
        # Back to single pane: drop focus highlighting and reset to primary.
        self._focused_card = self._time_card
        self._refresh_focus_borders()
        # Restore the primary card's controls (single live group again) and
        # disable the now-hidden secondary's.
        self._sync_secondary_controls_to_focus()
        self._sync_shared_nav_highlight()

    def attach_view_tabbar(self, manager):
        from ..view_tabbar import ViewTabBar

        existing = getattr(self, '_view_tabbar', None)
        if existing is not None:
            existing.setVisible(self.current_mode() == 'time')
            return existing

        bar = ViewTabBar(manager, self._time_bottom_dock)
        self._time_bottom_dock.layout().insertWidget(0, bar)
        self._view_tabbar = bar
        bar.setVisible(self.current_mode() == 'time')
        return bar

    def hint_bar_for_mode(self, mode):
        if mode == 'time':
            return self._time_card._hint_bar
        if mode == 'fft':
            return self._fft_card._hint_bar
        if mode == 'fft_time':
            return self._fft_time_card._hint_bar
        if mode == 'order':
            return self._order_card._hint_bar
        raise KeyError(mode)

    def take_hint_bar(self, mode, parent):
        """Move the mode's hint bar to a shared external container."""
        bar = self.hint_bar_for_mode(mode)
        old_parent = bar.parentWidget()
        if old_parent is not None:
            layout = old_parent.layout()
            if layout is not None and layout.indexOf(bar) >= 0:
                layout.removeWidget(bar)
        bar.setParent(parent)
        bar.setVisible(True)
        return bar

    def set_mode(self, mode):
        idx = _MODE_TO_INDEX[mode]
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
        self.stats_strip.setVisible(_STATS_STRIP_ENABLED and mode == 'time')
        bar = getattr(self, '_view_tabbar', None)
        if bar is not None:
            bar.setVisible(mode == 'time')
        self._time_bottom_dock.setVisible(mode == 'time')
        self.mode_changed.emit(mode)

    def current_mode(self):
        return _INDEX_TO_MODE[self.stack.currentIndex()]

    # ----- plot-mode / cursor-mode passthroughs -----
    def plot_mode(self):
        return self._primary_plot_mode

    def set_plot_mode(self, mode):
        if mode not in ('subplot', 'overlay'):
            return
        old_primary = self._primary_plot_mode
        if old_primary == mode:
            if not self._shared_time_controls_follow_secondary():
                self._set_shared_plot_mode_silent(mode)
            return
        self._primary_plot_mode = mode
        if not self._shared_time_controls_follow_secondary():
            self._set_shared_plot_mode_silent(mode)
        self.plot_mode_changed.emit(mode)

    def plot_mode_for_canvas(self, canvas):
        """Return the plot mode ('subplot'/'overlay') of the time card that
        owns ``canvas`` (P2 Task 9 1b).

        Each time pane now carries its OWN 分屏/叠加 state, so a replot must
        read the mode from the card owning the target canvas, not always the
        primary card. Falls back to the primary card's mode for any canvas we
        don't recognise (keeps non-split behaviour byte-identical)."""
        if (self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            return self._secondary_card.plot_mode()
        return self._primary_plot_mode

    def set_plot_mode_for_canvas(self, canvas, mode):
        """Set plot mode on the card that owns ``canvas`` without re-emitting.

        Used by ViewState apply/render paths where the target pane may be the
        secondary compare card. The interactive controls still emit through the
        existing set_plot_mode/_on_shared_plot_mode_changed paths.
        """
        if mode not in ('subplot', 'overlay'):
            return
        if (self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            self._set_secondary_plot_mode_silent(mode)
            return
        self._primary_plot_mode = mode
        if not self._shared_time_controls_follow_secondary():
            self._set_shared_plot_mode_silent(mode)

    def cursor_mode(self):
        return self._primary_cursor_mode

    def set_cursor_mode(self, mode):
        if mode not in ('off', 'single', 'dual'):
            return
        old_primary = self._primary_cursor_mode
        if old_primary == mode:
            if not self._shared_time_controls_follow_secondary():
                self._set_shared_cursor_mode_silent(mode)
            return
        self._primary_cursor_mode = mode
        if not self._shared_time_controls_follow_secondary():
            self._set_shared_cursor_mode_silent(mode)
        self._on_time_cursor_mode_changed(mode)

    def set_cursor_mode_for_canvas(self, canvas, mode):
        """Set cursor mode on the card/canvas owning ``canvas`` without signals."""
        if mode not in ('off', 'single', 'dual'):
            return
        if (self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            self._set_secondary_cursor_mode_silent(mode)
            target = self._secondary_card.canvas
        else:
            self._primary_cursor_mode = mode
            if not self._shared_time_controls_follow_secondary():
                self._set_shared_cursor_mode_silent(mode)
            target = self.canvas_time
        target.set_cursor_visible(mode != 'off')
        target.set_dual_cursor_mode(mode == 'dual')

    def _set_secondary_plot_mode_silent(self, mode):
        if self._secondary_card is None:
            return
        old = self._secondary_card.blockSignals(True)
        try:
            self._secondary_card.set_plot_mode(mode)
        finally:
            self._secondary_card.blockSignals(old)

    def _set_secondary_cursor_mode_silent(self, mode):
        if self._secondary_card is None:
            return
        old = self._secondary_card.blockSignals(True)
        try:
            self._secondary_card.set_cursor_mode(mode)
        finally:
            self._secondary_card.blockSignals(old)

    def _on_shared_plot_mode_changed(self, mode):
        if (
            self.split_active()
            and self._secondary_card is not None
            and self._focused_card is self._secondary_card
        ):
            self._set_secondary_plot_mode_silent(mode)
        else:
            self._primary_plot_mode = mode
        self.plot_mode_changed.emit(mode)

    def _on_shared_cursor_mode_changed(self, mode):
        # Canvas toggling + per-pane cursor_mode write-back is owned by
        # MainWindow._on_cursor_mode_changed (driven by the cursor_mode_changed
        # signal emitted below); applying to both canvases here too would just
        # double-toggle. Keep only the non-split primary bookkeeping.
        if not (self.split_active() and self._secondary_card is not None):
            self._primary_cursor_mode = mode
        self._on_time_cursor_mode_changed(mode)

    def _on_time_cursor_mode_changed(self, mode):
        if mode == 'off':
            self.clear_cursor_pill()
        self.cursor_mode_changed.emit(mode)

    def mark_discovered(self, hint_id):
        for card in (
            self._time_card,
            self._fft_card,
            self._fft_time_card,
            self._order_card,
        ):
            card.mark_discovered(hint_id)

    def set_annotation_enabled(self, mode, enabled, notify=False):
        cards = {
            'time': self._time_card,
            'fft': self._fft_card,
            'fft_time': self._fft_time_card,
            'order': self._order_card,
        }
        card = cards.get(mode)
        if card is not None:
            card.set_annotation_enabled(enabled, notify=notify)

    def full_reset_all(self):
        self.canvas_time.full_reset()
        if self._secondary_card is not None:
            self._secondary_card.canvas.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_fft_time.full_reset()
        self.canvas_order.full_reset()

    def _set_secondary_time_controls_enabled(self, enabled):
        """Enable/disable the secondary card's own split/overlay/cursor
        segmented controls (P2 Task 9 1b).

        Semantics changed from "always disabled" to "enabled while this pane
        is focused": when the compare (secondary) pane is the focused card its
        分屏/叠加/游标 controls drive its OWN canvas, mirroring how the primary
        card's identical controls drive the primary canvas. Outside split, or
        while the primary pane is focused, the secondary's controls are
        disabled so a single active control group is unambiguous."""
        card = self._secondary_card
        if card is None:
            return
        for button in (card.btn_subplot, card.btn_overlay):
            button.setEnabled(enabled)
        for button in card._cursor_buttons.values():
            button.setEnabled(enabled)

    def _sync_secondary_controls_to_focus(self):
        """Keep the visible shared time controls live.

        The secondary card keeps its own state object, but its toolbar is not
        part of the split UI. The primary card's detached toolbar is the shared
        toolbar and routes actions to the focused pane via MainWindow.
        """
        self._set_secondary_time_controls_enabled(False)
        for button in (self._time_card.btn_subplot, self._time_card.btn_overlay):
            button.setEnabled(True)
        for button in self._time_card._cursor_buttons.values():
            button.setEnabled(True)
        self._sync_shared_time_controls_to_focus()

    def _copy_card_image(self, card):
        """Capture the card's canvas for MainWindow to publish. For the
        time-domain card, the floating cursor pill (if visible and overlapping
        the canvas) is composited onto the captured pixmap so the screenshot
        matches what the user sees on screen.

        The canvas is grabbed at a hi-DPI scale (spec §E) for a crisp,
        DPI-independent bitmap; the canvas caps the magnification for
        speed. The cursor pill's position AND size are scaled by the SAME
        effective factor so it still lines up on the magnified bitmap."""
        if (self.current_mode() == 'time'
                and self.split_active()
                and card in (self._time_card, self._secondary_card)):
            pix = self._combined_split_pixmap()
            if pix is not None and not pix.isNull():
                self.image_captured.emit(pix)
            return
        # Analysis sections (fft/fft_time/order) own their own per-section
        # split via AnalysisSectionPage. When the card's page is split, export
        # ALL panes composited side-by-side (grab_combined_pixmap), parallel to
        # the time-domain _combined_split_pixmap branch above. Single-pane falls
        # through to the plain grab below (byte-identical to pre-split copy).
        mode = getattr(card, '_chart_mode', '')
        if mode in ('fft', 'fft_time', 'order'):
            page = self.page_for_mode.get(mode)
            if page is not None and page.pane_count() > 1:
                pix = page.grab_combined_pixmap(scale=_HIDPI_EXPORT_SCALE)
                if pix is not None and not pix.isNull():
                    self.image_captured.emit(_pixmap_as_device_pixels(pix))
                return
        canvas = card.canvas
        pix = _grab_pixmap_hidpi(canvas)
        if pix is None or pix.isNull():
            return
        canvas_w = max(1, int(canvas.width()))
        canvas_h = max(1, int(canvas.height()))
        scale_x = max(1.0, float(pix.width()) / float(canvas_w))
        scale_y = max(1.0, float(pix.height()) / float(canvas_h))
        # Composite the floating pill onto whichever time pane is being copied
        # (primary or the focused secondary); the overlap check below gates it
        # to the case where the pill actually sits over THIS canvas.
        if (self.current_mode() == 'time'
                and self._pill.isVisible()):
            canvas_origin = canvas.mapTo(self.stack, canvas.rect().topLeft())
            pill_geo = self._pill.geometry()
            rel_x = pill_geo.x() - canvas_origin.x()
            rel_y = pill_geo.y() - canvas_origin.y()
            # Draw only when the pill actually overlaps the canvas rect
            # (compare in unscaled canvas-pixel space).
            if (rel_x + pill_geo.width() > 0 and rel_x < canvas.width()
                    and rel_y + pill_geo.height() > 0 and rel_y < canvas.height()):
                painter = QPainter(pix)
                # Scale the pill using the actual normalized bitmap size. On
                # Retina, QPixmap painters use logical DPR coordinates unless
                # the pixmap is normalized first; using the returned bitmap's
                # pixel dimensions keeps the pill inside the exported image.
                target = QRect(
                    int(round(rel_x * scale_x)),
                    int(round(rel_y * scale_y)),
                    int(round(pill_geo.width() * scale_x)),
                    int(round(pill_geo.height() * scale_y)),
                )
                painter.drawPixmap(
                    target,
                    self._grab_pill_scaled(max(scale_x, scale_y)),
                )
                painter.end()
        self.image_captured.emit(pix)

    def _grab_pill_scaled(self, scale):
        """Grab the cursor pill at ``scale``× for crisp compositing.

        At 1× this is a plain ``QPixmap`` grab; above 1× the pill widget is
        re-rendered into a magnified QImage (sharp text, not an upscale)."""
        pill = self._pill
        if scale <= 1.0:
            return pill.grab()
        w = max(1, int(pill.width()))
        h = max(1, int(pill.height()))
        tw = max(1, int(round(w * scale)))
        th = max(1, int(round(h * scale)))
        img = QImage(tw, th, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.scale(scale, scale)
            pill.render(painter)
        finally:
            painter.end()
        return QPixmap.fromImage(img)

    def _pill_for_canvas(self, canvas):
        """Return the CursorPill that should show readouts for ``canvas``."""
        if (self._pill_secondary is not None
                and self._secondary_card is not None
                and canvas is self._secondary_card.canvas):
            return self._pill_secondary
        return self._pill

    def _on_cursor_info(self, text, source=None):
        mode = self._cursor_mode_for_canvas(source)
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        primary, detail = self._format_cursor_info_for_pill(text, mode)
        pill = self._pill_for_canvas(source)
        pill.set_primary(primary)
        if mode == 'single':
            pill.set_detail_html(detail)
        pill.setVisible(self.current_mode() == 'time')
        self._reposition_pill()

    def _format_cursor_info_for_pill(self, text, mode=None):
        from .cursor_pill import _CURSOR_HTML_SEP
        if mode is None:
            mode = self.cursor_mode()
        if mode != 'single' or _CURSOR_HTML_SEP not in (text or ''):
            return text, ''
        parts = [part for part in text.split(_CURSOR_HTML_SEP) if part]
        if len(parts) <= 1:
            return text, ''
        rows = ['<table cellspacing="0" cellpadding="0">']
        for i, part in enumerate(parts[1:]):
            top_pad = '6px' if i > 0 else '0'
            rows.append(
                '<tr><td style="padding-top:'
                f'{top_pad}; padding-bottom:2px; line-height:1.35;">'
                f'{part}</td></tr>'
            )
        rows.append('</table>')
        return parts[0], ''.join(rows)

    def _on_dual_cursor_info(self, text, source=None):
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        pill.set_detail_html(text)
        if self.current_mode() == 'time' and (text or pill.primary_text()):
            pill.setVisible(True)
        self._reposition_pill()

    def _reposition_pill(self):
        if self.current_mode() != 'time':
            self._pill.setVisible(False)
            if self._pill_secondary is not None:
                self._pill_secondary.setVisible(False)
            return
        self._reposition_one_pill(self._pill, self._time_card)
        if self._pill_secondary is not None and self._secondary_card is not None:
            self._reposition_one_pill(self._pill_secondary, self._secondary_card)

    def _reposition_one_pill(self, pill, card):
        """Anchor ``pill`` to ``card``'s canvas top-right corner (or honour
        its user-placed position)."""
        if not pill.isVisible():
            return
        if pill.is_user_placed():
            pw, ph = self.stack.width(), self.stack.height()
            x = max(0, min(pill.x(), pw - pill.width()))
            y = max(0, min(pill.y(), ph - pill.height()))
            pill.move(x, y)
        else:
            canvas = getattr(card, 'canvas', None)
            if canvas is not None:
                origin = canvas.mapTo(self.stack, canvas.rect().topLeft())
                x_right = origin.x() + canvas.width()
                x = min(x_right - pill.width() - 8,
                        self.stack.width() - pill.width())
                pill.move(max(x, 0), origin.y() + 8)
            else:
                w = self.stack.width()
                pill.move(max(w - pill.width() - 8, 0), 8)
        pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pill()

    def clear_cursor_pill(self):
        """Clear pill content and hide it; preserves the user-placed flag so a
        subsequent cursor activation reappears at the spot the user chose."""
        self._pill.clear()
        if self._pill_secondary is not None:
            self._pill_secondary.clear()

    def cursor_pill_snapshot(self):
        """Return the current floating cursor pill UI state.

        The pill content is not part of ViewState; it reflects the last cursor
        hover/readout on the active canvas. Split rendering temporarily applies
        another view through the primary controls, so callers can use this to
        preserve the active readout across that off-screen render.
        """
        return {
            'visible': self._pill.isVisible(),
            'primary': self._pill.primary_text(),
            'detail': self._pill._detail.text(),
            'detail_visible': self._pill.has_detail(),
            'user_placed': self._pill.is_user_placed(),
            'pos': (self._pill.x(), self._pill.y()),
        }

    def restore_cursor_pill_snapshot(self, snapshot):
        if not snapshot:
            return
        self._pill.set_primary(snapshot.get('primary') or '')
        detail = snapshot.get('detail') if snapshot.get('detail_visible') else ''
        self._pill.set_detail_html(detail or '')
        self._pill.mark_user_placed(snapshot.get('user_placed', False))
        pos = snapshot.get('pos')
        if pos is not None:
            self._pill.move(pos[0], pos[1])
        self._pill.setVisible(bool(snapshot.get('visible')) and self.current_mode() == 'time')
        if self._pill.isVisible():
            if not self._pill.is_user_placed():
                self._reposition_pill()
            else:
                self._pill.raise_()

    def cursor_pill_text(self):
        return self._pill.primary_text()

    def cursor_pill_visible(self):
        return self._pill.isVisible()
