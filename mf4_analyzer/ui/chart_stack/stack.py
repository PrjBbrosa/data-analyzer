"""ChartStack — the centre-pane QWidget coordinator."""
import json
import logging
from functools import partial

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from ..pg_canvases import TimeDomainCanvasPG
from ..pg_canvas.heatmap_canvas import PgHeatmapCanvas
from ..pg_canvas.frf_canvas import PgFrfCanvas
from ..pg_canvas.line_canvas import PgLineCanvas
from ..widgets import StatsStrip
from ..analysis_section_page import AnalysisSectionPage
from ..analysis_view_state import AnalysisViewState
from ..view_state import ViewManager
from .ultraview.page import UltraViewPage

from ._helpers import (
    _grab_pixmap_hidpi,
    _pixmap_as_device_pixels,
    _apply_mdi_icons,
    _HIDPI_EXPORT_SCALE,
    _STATS_STRIP_ENABLED,
    STATUS_HINT_BAR_HEIGHT,
    _MODE_TO_INDEX,
    _INDEX_TO_MODE,
    _BOTTOM_HINT_PERSISTENT,
)
from .cards import _ChartCard, FrequencyCursorCard, FrfChartCard, TimeChartCard
from .cursor_pill import (
    CursorPill,
    format_cursor_info,
    format_single_cursor_variants,
    mini_single_cursor_part,
    plain_single_cursor_tooltip_line,
    single_cursor_channel_color,
    strip_html,
)
from .cursor_display import (
    CursorDisplayBranch,
    CursorDisplayChannel,
    CursorDisplayOptions,
    CursorDisplaySettingsStore,
    build_cursor_presentation,
)
from ..plot_helpers import _split_prefixed_label, dual_row_is_custom_x
from .toolbar import PgNavigationToolbar
from ...ui_kit.qt_lifecycle import as_weak_callable
from ..channel_drag import INTERNAL_CHANNEL_MIME, decode_channel_drag

logger = logging.getLogger(__name__)


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    cursor_mode_changed = pyqtSignal(str)
    analysis_cursor_mode_changed = pyqtSignal(str, object, str)
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
    quickref_requested = pyqtSignal()
    add_to_ultraview_requested = pyqtSignal(str, str)
    open_ultraview_requested = pyqtSignal()
    open_ultraview_unplaced_requested = pyqtSignal()
    # Time-domain channel MIME drop. ``zone`` is ``plot`` or ``xaxis``.
    # Carries (canvas, (fid, channel), zone); MainWindow owns View writes.
    channel_drop_requested = pyqtSignal(object, object, str)

    def __init__(self, parent=None, *, cursor_settings=None):
        super().__init__(parent)
        self._cursor_display_store = CursorDisplaySettingsStore(cursor_settings)
        self._cursor_display_options = self._cursor_display_store.load()
        self._cursor_rows_by_canvas = {}
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
        self.canvas_time.set_cursor_display_options(self._cursor_display_options)
        self._time_card.set_cursor_display_options(self._cursor_display_options)
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
        # QWidget (not QFrame): analysisCompareRow is a QWidget, and QFrame +
        # QSS border-top insets contentsRect by frameWidth (1px), which pushed
        # the TimeDomain hairline/content 1px off the analysis sections.
        self._time_bottom_dock = QWidget(self._time_page)
        self._time_bottom_dock.setObjectName("timeViewBottomDock")
        # Same chrome contract as AnalysisSectionPage's #analysisCompareRow:
        # an explicit light fill + top divider. WA_TranslucentBackground /
        # transparent QSS suppress both the fill and the border (and the
        # quiet-anchor 1px rule inside), which is why TimeDomain looked bare
        # next to FFT/Order. WA_StyledBackground keeps the QSS fill from
        # falling back to platform grey.
        self._time_bottom_dock.setAttribute(Qt.WA_StyledBackground, True)
        self._time_bottom_dock.setAttribute(Qt.WA_TranslucentBackground, False)
        self._time_bottom_dock.setAttribute(Qt.WA_NoSystemBackground, False)
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
        # Per-section analysis ViewManagers. Cap is MAX_VIEWS (12);
        # time-domain uses TIME_DOMAIN_MAX_VIEWS (24) on MainWindow's
        # view_manager. ViewTabBar reads the instance cap.
        from ..view_state import MAX_VIEWS
        self.analysis_managers = {
            'fft': ViewManager(
                self, state_factory=AnalysisViewState, max_views=MAX_VIEWS,
            ),
            'fft_time': ViewManager(
                self, state_factory=AnalysisViewState, max_views=MAX_VIEWS,
            ),
            'frf': ViewManager(
                self, state_factory=AnalysisViewState, max_views=MAX_VIEWS,
            ),
            'order': ViewManager(
                self, state_factory=AnalysisViewState, max_views=MAX_VIEWS,
            ),
        }

        def _fft_card_factory():
            return FrequencyCursorCard(
                PgLineCanvas(self), annotations=True, chart_mode='fft'
            )

        def _fft_time_card_factory():
            return _ChartCard(
                PgHeatmapCanvas(self, with_slice=True),
                annotations=True, chart_mode='fft_time',
            )

        def _frf_card_factory():
            return FrfChartCard(PgFrfCanvas(self))

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
        self.page_frf = AnalysisSectionPage(
            section='frf', manager=self.analysis_managers['frf'],
            card_factory=_frf_card_factory, parent=self,
        )
        self.page_order = AnalysisSectionPage(
            section='order', manager=self.analysis_managers['order'],
            card_factory=_order_card_factory, parent=self,
        )
        self.stack.addWidget(self._time_page)
        self.stack.addWidget(self.page_fft)
        self.stack.addWidget(self.page_fft_time)
        self.stack.addWidget(self.page_frf)
        self.stack.addWidget(self.page_order)
        # Host slot for UltraViewPage. Not a live workspace mode:
        # ChartStack.set_mode rejects 'ultraview'. The page stays in the
        # stack so UltraViewSheet can return it on close.
        self.page_ultraview = UltraViewPage(self)
        self.stack.addWidget(self.page_ultraview)
        self.page_ultraview.quickref_requested.connect(self.quickref_requested.emit)
        for page in (
            self.page_fft, self.page_fft_time, self.page_frf, self.page_order,
        ):
            page.setAttribute(Qt.WA_TranslucentBackground, True)
            page.setAttribute(Qt.WA_NoSystemBackground, True)
            page.setAutoFillBackground(False)
            self._connect_analysis_card_signals(page._cards[0])
            page.tabbar.add_to_ultraview_requested.connect(
                self.add_to_ultraview_requested.emit
            )
            self._wire_ultraview_entry(page.ultraview_entry)
        # The time card's copy button lives on the shared toolbar; route it to
        # the focused pane so 复制为图片 captures whichever pane is focused.
        self._time_card.copy_image_requested.connect(self._copy_focused_card_image)
        # Shared-toolbar home/save still target the focused pane; pan/zoom and
        # history buttons broadcast to the visible peer toolbar below.
        self._time_toolbar._action_delegate_provider = as_weak_callable(
            self._focused_nav_delegate
        )
        self._time_toolbar._peer_toolbars_provider = as_weak_callable(
            self._secondary_peer_toolbars
        )
        self._time_toolbar._save_pixmap_provider = as_weak_callable(
            self._combined_split_pixmap
        )
        self._time_toolbar.home_triggered.connect(self.home_triggered.emit)
        # 图表选项 on the shared toolbar opens for the focused pane's canvas.
        self._time_card._options_canvas_provider = as_weak_callable(
            self.focused_canvas
        )
        # Mirror the focused pane's pan/zoom state onto the shared toolbar
        # icons. Connected AFTER the primary card's own _on_nav_mode_toggled
        # (bound during _ChartCard.__init__) so this runs LAST in the action's
        # triggered emission and wins — otherwise the card handler would
        # re-assert the primary's icon after a click that forwarded to the
        # secondary. Idempotent; no-op outside split.
        for _key in ('pan', 'zoom'):
            _act = self._time_toolbar._actions_by_key.get(_key)
            if _act is not None:
                _act.triggered.connect(self._sync_shared_nav_highlight)
        self._time_toolbar.mouse_mode_changed.connect(
            self._sync_shared_nav_highlight
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
        self._pill.display_mode_changed.connect(
            partial(self._on_cursor_pill_display_mode_changed, source=self.canvas_time)
        )
        self._pill_secondary = None  # created/destroyed with enter/exit_split
        self._active_cursor_card = self._time_card
        # Pass the SOURCE canvas so the pill picks the right per-pane cursor
        # mode (single/dual formatting) and anchors over the emitting pane.
        self.canvas_time.cursor_info.connect(
            lambda text: self._on_cursor_info(text, self.canvas_time)
        )
        self.canvas_time.single_cursor_rows.connect(
            partial(self._on_single_cursor_rows, source=self.canvas_time)
        )
        self.canvas_time.dual_cursor_info.connect(
            lambda text: self._on_dual_cursor_info(text, self.canvas_time)
        )
        if hasattr(self.canvas_time, 'dual_cursor_rows'):
            self.canvas_time.dual_cursor_rows.connect(
                lambda rows: self._on_dual_cursor_rows(rows, self.canvas_time)
            )
        self.stack.currentChanged.connect(self._reposition_pill)

        # Relay time-card control signals up to MainWindow consumers.
        self._time_card.plot_mode_changed.connect(self._on_shared_plot_mode_changed)
        self._time_card.cursor_mode_changed.connect(
            self._on_shared_cursor_mode_changed
        )
        self._time_card.cursor_display_options_changed.connect(
            partial(
                self._on_cursor_display_options_changed,
                source_card=self._time_card,
            )
        )
        self._time_card.cursor_display_popover_geometry_changed.connect(
            partial(
                self._on_cursor_display_popover_geometry_changed,
                source_card=self._time_card,
            )
        )
        # The time card's annotation relay; analysis cards (pane 0) are wired in
        # _connect_analysis_card_signals during page construction above.
        self._time_card.annotation_enabled_changed.connect(
            lambda enabled: self.annotation_enabled_changed.emit('time', enabled)
        )
        self._time_card.tick_density_changed.connect(
            self._on_card_tick_density_changed
        )
        self._time_card.quickref_requested.connect(self.quickref_requested.emit)

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
        is the card's section key ('fft'/'fft_time'/'frf'/'order')."""
        card.copy_image_requested.connect(
            lambda c=card: self._copy_card_image(c)
        )
        mode = card._chart_mode
        card.annotation_enabled_changed.connect(
            lambda enabled, m=mode: self.annotation_enabled_changed.emit(m, enabled)
        )
        card.tick_density_changed.connect(self._on_card_tick_density_changed)
        card.quickref_requested.connect(self.quickref_requested.emit)
        if mode in {'fft', 'frf'} and hasattr(card, 'cursor_mode_changed'):
            card.cursor_mode_changed.connect(
                lambda cursor_mode, m=mode, c=card.canvas:
                self.analysis_cursor_mode_changed.emit(m, c, cursor_mode)
            )
        canvas = getattr(card, 'canvas', None)
        if (canvas is not None and hasattr(canvas, 'cursor_info')
                and not isinstance(canvas, PgHeatmapCanvas)):
            canvas.cursor_info.connect(
                lambda text, c=canvas: self._on_cursor_info(text, c)
            )
        if canvas is not None and hasattr(canvas, 'dual_cursor_info'):
            canvas.dual_cursor_info.connect(
                lambda text, c=canvas: self._on_dual_cursor_info(text, c)
            )
        if canvas is not None and hasattr(canvas, 'frequency_cursor_rows'):
            canvas.frequency_cursor_rows.connect(
                partial(self._on_frequency_cursor_rows, source=canvas)
            )

    def _all_cards(self):
        cards = [self._time_card]
        if self._secondary_card is not None:
            cards.append(self._secondary_card)
        for page in (
            self.page_fft, self.page_fft_time, self.page_frf, self.page_order,
        ):
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
            'frf': self.page_frf,
            'order': self.page_order,
        }

    @property
    def _fft_card(self):
        return self.page_fft._cards[0]

    @property
    def _fft_time_card(self):
        return self.page_fft_time._cards[0]

    @property
    def _frf_card(self):
        return self.page_frf._cards[0]

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
    def canvas_frf(self):
        return self.page_frf.pane_canvas(0)

    @property
    def canvas_order(self):
        return self.page_order.pane_canvas(0)

    def _configure_time_hint_bar(self):
        # Time-view docked footer. This IS the time card's detached _hint_bar
        # (see detach_bottom_hint_bar), so we re-assert the same edge-anchored
        # layout after clearing it: the rotating row hugs the LEFT edge
        # (stretch=1), the discovery hint hugs the RIGHT edge (提示位置 左右靠边).
        self._configure_status_hint_bar(self._time_hint_bar)
        lay = self._time_hint_bar.layout()
        while lay.count():
            lay.takeAt(0)
        lay.addWidget(self._time_card._hint_quickref_btn, 0, Qt.AlignVCenter)
        lay.addWidget(self._time_card._hint_context, 1, Qt.AlignVCenter)
        lay.addWidget(self._time_card._hint_discovery, 0, Qt.AlignVCenter)

    @staticmethod
    def _configure_status_hint_bar(bar):
        """Shared chrome for a hint bar hosted in SurfaceStatusBar."""
        bar.setFixedHeight(STATUS_HINT_BAR_HEIGHT)
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = bar.layout()
        if lay is None:
            return
        # Left inset clears SurfaceStatusBar's 8px border-radius so the ``?``
        # circle is not clipped into a fake glyph remnant. Vertical padding
        # stays tight so a 26px strip plus the status bar's 1px border still
        # fits inside the 32px pill — a 28px strip painted over the bottom
        # hairline and made the gray frame vanish under the hint.
        lay.setContentsMargins(10, 2, 8, 2)
        lay.setSpacing(4)

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

    def _copy_focused_card_image(self, *_args):
        self._copy_card_image(self.focused_card())

    def _copy_secondary_card_image(self, *_args):
        self._copy_card_image(self._secondary_card)

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
        for card in self._all_cards():
            if getattr(card, 'canvas', None) is canvas:
                return card
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
        if isinstance(canvas, (PgLineCanvas, PgFrfCanvas)):
            card = self._card_for_canvas(canvas)
            getter = getattr(card, 'cursor_mode', None)
            if callable(getter):
                return getter()
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
                viewport.setAcceptDrops(True)
                viewport.setAccessibleName("时域绘图区")
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
        etype = event.type()
        if etype in (
            QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop,
        ):
            if self._handle_time_channel_drag(obj, event):
                return True
        if etype == QEvent.MouseButtonPress and self.split_active():
            card = self._card_for_object(obj)
            if card is not None and card is not self._focused_card:
                self.set_focused_card(card)
        return super().eventFilter(obj, event)

    def _handle_time_channel_drag(self, obj, event):
        """Route a channel MIME drag over a time card. Returns True if consumed."""
        if self.current_mode() != "time":
            return False
        card = self._card_for_object(obj)
        if card is None:
            return False
        etype = event.type()
        if etype == QEvent.DragLeave:
            self._clear_channel_drop_highlights()
            return True
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(INTERNAL_CHANNEL_MIME):
            return False
        key = decode_channel_drag(bytes(mime.data(INTERNAL_CHANNEL_MIME)))
        if key is None:
            return False
        if etype in (QEvent.DragEnter, QEvent.DragMove):
            zone = self._channel_drop_zone(card, obj, event)
            self._set_channel_drop_highlight(card, zone)
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return True
        if etype == QEvent.Drop:
            zone = self._channel_drop_zone(card, obj, event)
            canvas = getattr(card, "canvas", None)
            self._clear_channel_drop_highlights()
            event.setDropAction(Qt.CopyAction)
            event.accept()
            if canvas is not None:
                self.channel_drop_requested.emit(canvas, key, zone)
            return True
        return False

    def xaxis_drop_rect(self, canvas):
        """Viewport-local QRect of the bottom-most visible X AxisItem, or None."""
        if canvas is None:
            return None
        glw = getattr(canvas, "_glw", None)
        if glw is None:
            return None
        seen = set()
        bottom_rects = []
        handles = list(getattr(canvas, "axes_list", []) or [])
        master = getattr(canvas, "_x_master_handle", None)
        if master is not None:
            handles.append(master)
        plot_items = []
        for handle in handles:
            plot_item = getattr(handle, "plot_item", None)
            if plot_item is not None and plot_item not in plot_items:
                plot_items.append(plot_item)
        layout = getattr(glw, "ci", None)
        items = getattr(layout, "items", None) or {}
        for item in list(items.keys()):
            if hasattr(item, "getAxis") and item not in plot_items:
                plot_items.append(item)
        for plot_item in plot_items:
            self._collect_bottom_axis_scene_rects(plot_item, bottom_rects, seen)
        if not bottom_rects:
            return None
        scene_rect = max(bottom_rects, key=lambda rect: rect.bottom())
        try:
            top_left = glw.mapFromScene(scene_rect.topLeft())
            bottom_right = glw.mapFromScene(scene_rect.bottomRight())
        except Exception:
            return None
        x = int(min(top_left.x(), bottom_right.x()))
        y = int(min(top_left.y(), bottom_right.y()))
        width = max(1, int(abs(bottom_right.x() - top_left.x())))
        height = max(1, int(abs(bottom_right.y() - top_left.y())))
        mapped = QRect(x, y, width, height)
        try:
            view_rect = glw.viewport().rect()
            mapped = mapped.intersected(view_rect)
            # AxisItem.sceneBoundingRect() can cover the whole plot because
            # it paints the X grid. Reject that as an X drop zone.
            if mapped.height() > max(80, int(view_rect.height() * 0.28)):
                return None
        except Exception:
            pass
        if mapped.isNull() or mapped.height() <= 0:
            return None
        return mapped

    @staticmethod
    def _collect_bottom_axis_scene_rects(plot_item, bottom_rects, seen):
        """Use the PlotItem grid cell, not AxisItem.sceneBoundingRect.

        pyqtgraph's bottom AxisItem bounding rect includes the linked ViewBox
        so it can paint the X grid; that would make the whole plot an X-drop
        zone. The layout cell is the actual tick/label band.
        """
        layout = getattr(plot_item, "layout", None)
        axis_items = []
        if layout is not None:
            try:
                rows = int(layout.rowCount())
                cols = int(layout.columnCount())
            except Exception:
                rows = cols = 0
            for row in range(rows):
                for col in range(cols):
                    try:
                        item = layout.itemAt(row, col)
                    except Exception:
                        item = None
                    if getattr(item, "orientation", None) == "bottom":
                        axis_items.append(item)
        if not axis_items:
            getter = getattr(plot_item, "getAxis", None)
            if callable(getter):
                axis_items.append(getter("bottom"))
        mapper = getattr(plot_item, "mapRectToScene", None)
        for axis in axis_items:
            if axis is None or id(axis) in seen:
                continue
            seen.add(id(axis))
            try:
                geom = axis.geometry()
                if callable(mapper):
                    scene_rect = mapper(geom)
                else:
                    scene_rect = axis.sceneBoundingRect()
            except Exception:
                continue
            if scene_rect is None or scene_rect.isNull() or scene_rect.height() <= 1:
                continue
            bottom_rects.append(scene_rect)

    def _channel_drop_zone(self, card, watched, event):
        canvas = getattr(card, "canvas", None)
        if canvas is None:
            return "plot"
        glw = getattr(canvas, "_glw", None)
        viewport = None
        if glw is not None:
            try:
                viewport = glw.viewport()
            except Exception:
                viewport = None
        pos = event.pos()
        if not isinstance(pos, QPoint):
            pos = pos.toPoint() if hasattr(pos, "toPoint") else QPoint(int(pos.x()), int(pos.y()))
        if viewport is not None and watched is not viewport:
            pos = viewport.mapFrom(watched, pos)
        x_rect = self.xaxis_drop_rect(canvas)
        if x_rect is not None and x_rect.adjusted(0, -4, 0, 6).contains(pos):
            return "xaxis"
        return "plot"

    def _set_channel_drop_highlight(self, card, zone):
        x_rect = None
        if zone == "xaxis":
            x_rect = self.xaxis_drop_rect(getattr(card, "canvas", None))
        for other in (self._time_card, self._secondary_card):
            if other is None:
                continue
            setter = getattr(other, "set_channel_drop_zone", None)
            if not callable(setter):
                continue
            if other is card:
                setter(zone, x_rect)
            else:
                setter("")

    def _clear_channel_drop_highlights(self):
        for card in (self._time_card, self._secondary_card):
            if card is None:
                continue
            setter = getattr(card, "set_channel_drop_zone", None)
            if callable(setter):
                setter("")

    def enter_split(self):
        if self._secondary_card is None:
            canvas = TimeDomainCanvasPG(self)
            self._secondary_card = TimeChartCard(canvas)
            canvas.set_cursor_display_options(self._cursor_display_options)
            self._secondary_card.set_cursor_display_options(
                self._cursor_display_options
            )
            self._secondary_card.detach_toolbar(self._secondary_card).hide()
            self._secondary_card.detach_bottom_hint_bar(self._secondary_card).hide()
            self._set_secondary_time_controls_enabled(False)
            self._secondary_card.copy_image_requested.connect(
                self._copy_secondary_card_image
            )
            self._secondary_card.tick_density_changed.connect(
                self._on_card_tick_density_changed
            )
            self._secondary_card.quickref_requested.connect(
                self.quickref_requested.emit
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
            self._secondary_card.cursor_display_options_changed.connect(
                partial(
                    self._on_cursor_display_options_changed,
                    source_card=self._secondary_card,
                )
            )
            self._secondary_card.cursor_display_popover_geometry_changed.connect(
                partial(
                    self._on_cursor_display_popover_geometry_changed,
                    source_card=self._secondary_card,
                )
            )
            self._secondary_card.toolbar._peer_toolbars_provider = as_weak_callable(
                self._primary_peer_toolbars
            )
            self._secondary_card.toolbar.mouse_mode_changed.connect(
                self._sync_shared_nav_highlight
            )
            # The secondary pane has its own pill so both split panes can show
            # independent single/dual cursor readouts at the same time.
            if self._pill_secondary is None:
                self._pill_secondary = CursorPill(self.stack)
                self._pill_secondary.setVisible(False)
                self._pill_secondary.display_mode_changed.connect(
                    partial(
                        self._on_cursor_pill_display_mode_changed,
                        source=canvas,
                    )
                )
            canvas.cursor_info.connect(
                lambda text, c=canvas: self._on_cursor_info(text, c)
            )
            canvas.single_cursor_rows.connect(
                partial(self._on_single_cursor_rows, source=canvas)
            )
            canvas.dual_cursor_info.connect(
                lambda text, c=canvas: self._on_dual_cursor_info(text, c)
            )
            if hasattr(canvas, 'dual_cursor_rows'):
                canvas.dual_cursor_rows.connect(
                    lambda rows, c=canvas: self._on_dual_cursor_rows(rows, c)
                )
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
        control flips (subplot↔overlay needs a fresh layout). Bound methods
        are held weakly so ChartStack cannot keep MainWindow alive."""
        self._replot_secondary_cb = as_weak_callable(cb)

    def _primary_peer_toolbars(self):
        return [self._time_toolbar] if self.split_active() else []

    def _secondary_peer_toolbars(self):
        if self.split_active() and self._secondary_card is not None:
            return [self._secondary_card.toolbar]
        return []

    def exit_split(self):
        if self._secondary_card is not None:
            self._secondary_card.close_cursor_display_popover()
            self._secondary_card.setVisible(False)
            self._cursor_rows_by_canvas.pop(self._secondary_card.canvas, None)
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

    def _emit_open_ultraview(self, _checked=False):
        self.open_ultraview_requested.emit()

    def _emit_open_ultraview_unplaced(self):
        self.open_ultraview_unplaced_requested.emit()

    def set_ultraview_has_content(self, has_content: bool) -> None:
        """Project the workspace-content marker onto every source View rail."""
        entries = (
            getattr(self, "ultraview_entry", None),
            getattr(getattr(self, "page_fft", None), "ultraview_entry", None),
            getattr(getattr(self, "page_fft_time", None), "ultraview_entry", None),
            getattr(getattr(self, "page_frf", None), "ultraview_entry", None),
            getattr(getattr(self, "page_order", None), "ultraview_entry", None),
        )
        for entry in entries:
            setter = getattr(entry, "set_has_content", None)
            if callable(setter):
                setter(has_content)

    def set_ultraview_unplaced_count(self, count: int) -> None:
        """Project the active Board's unplaced count onto every View rail."""
        entries = (
            getattr(self, "ultraview_entry", None),
            getattr(getattr(self, "page_fft", None), "ultraview_entry", None),
            getattr(getattr(self, "page_fft_time", None), "ultraview_entry", None),
            getattr(getattr(self, "page_frf", None), "ultraview_entry", None),
            getattr(getattr(self, "page_order", None), "ultraview_entry", None),
        )
        for entry in entries:
            setter = getattr(entry, "set_unplaced_count", None)
            if callable(setter):
                setter(count)

    def _wire_ultraview_entry(self, button):
        """Connect a View-rail Dock click once; repeat calls are no-ops."""
        if button is None:
            return
        wired = getattr(self, '_wired_ultraview_entries', None)
        if wired is None:
            self._wired_ultraview_entries = wired = set()
        token = id(button)
        if token in wired:
            return
        button.clicked.connect(self._emit_open_ultraview)
        badge = getattr(button, "badge_clicked", None)
        if badge is not None:
            badge.connect(self._emit_open_ultraview_unplaced)
        wired.add(token)

    def attach_view_tabbar(self, manager):
        from ..view_tabbar import ViewTabBar
        from ..widgets.ultraview_entry import (
            ENTRY_HEIGHT,
            UltraViewEntryButton,
            UltraViewRailFitter,
            make_ultraview_separator,
        )

        existing = getattr(self, '_view_tabbar', None)
        if existing is not None:
            existing.setVisible(self.current_mode() == 'time')
            return existing

        dock = self._time_bottom_dock
        host = QWidget(dock)
        host.setObjectName("timeViewRail")
        # Keep the rail transparent so #timeViewBottomDock's rounded fill
        # remains the only bottom-corner paint (ChartStack radius 7px).
        host.setAttribute(Qt.WA_StyledBackground, True)
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAutoFillBackground(False)
        host.setStyleSheet("QWidget#timeViewRail { background-color: transparent; }")
        host.setFixedHeight(ENTRY_HEIGHT)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rail = QHBoxLayout(host)
        rail.setContentsMargins(0, 0, 8, 0)
        rail.setSpacing(6)

        bar = ViewTabBar(manager, host, section='time')
        rail.addWidget(bar, 1)
        sep = make_ultraview_separator(host)
        entry = UltraViewEntryButton(host)
        rail.addWidget(sep, 0, Qt.AlignVCenter)
        rail.addWidget(entry, 0, Qt.AlignVCenter)

        dock.layout().insertWidget(0, host)
        # A child created under an already-visible dock starts explicitly
        # hidden; insertWidget will not auto-show it (unlike a ViewTabBar
        # that used to be inserted directly).
        host.show()
        self._time_view_rail = host
        self._view_tabbar = bar
        self.ultraview_separator = sep
        self.ultraview_entry = entry
        self._ultraview_rail_fitter = UltraViewRailFitter(
            host=host, tabbar=bar, entry=entry, extra_widgets=(),
        )
        bar.setVisible(self.current_mode() == 'time')
        bar.add_to_ultraview_requested.connect(self.add_to_ultraview_requested.emit)
        self._wire_ultraview_entry(entry)
        return bar

    def hint_bar_for_mode(self, mode):
        if mode not in _MODE_TO_INDEX or mode == 'ultraview':
            mode = 'time'
        if mode == 'time':
            return self._time_card._hint_bar
        if mode == 'fft':
            return self._fft_card._hint_bar
        if mode == 'fft_time':
            return self._fft_time_card._hint_bar
        if mode == 'frf':
            return self._frf_card._hint_bar
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
        self._configure_status_hint_bar(bar)
        return bar

    def set_mode(self, mode):
        if mode == 'ultraview':
            logger.warning(
                "ChartStack.set_mode('ultraview') is not a live workspace "
                "mode; page_ultraview remains the UltraView sheet host"
            )
            return
        if mode not in _MODE_TO_INDEX:
            mode = 'time'
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
        return _INDEX_TO_MODE.get(self.stack.currentIndex(), 'time')

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
            for card in (self._time_card, self._secondary_card):
                if card is not None:
                    card.close_cursor_display_popover()
            self.clear_cursor_pill()
        self.cursor_mode_changed.emit(mode)

    def mark_discovered(self, hint_id):
        for card in (
            self._time_card,
            self._fft_card,
            self._fft_time_card,
            self._frf_card,
            self._order_card,
        ):
            card.mark_discovered(hint_id)

    def set_annotation_enabled(self, mode, enabled, notify=False):
        cards = {
            'time': self._time_card,
            'fft': self._fft_card,
            'fft_time': self._fft_time_card,
            'frf': self._frf_card,
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
        self.canvas_frf.full_reset()
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

    def grab_presentation_pixmap(self, target, *, scale=1.0):
        """Grab canvas pixels plus the overlapping cursor pill.

        Copy-to-clipboard uses hi-DPI ``scale``; UltraView uses ``1.0``.
        Does not touch the clipboard. Time-domain split copy still uses
        ``_combined_split_pixmap`` and does not go through this helper.
        Multi-pane analysis pages keep ``grab_combined_pixmap``.
        """
        canvas, page = self._presentation_canvas_and_page(target)
        if page is not None and callable(getattr(page, "pane_count", None)):
            try:
                pane_count = int(page.pane_count())
            except (TypeError, RuntimeError):
                pane_count = 0
            if pane_count > 1:
                grab_combined = getattr(page, "grab_combined_pixmap", None)
                if not callable(grab_combined):
                    return None
                pix = grab_combined(scale=scale)
                if pix is None or pix.isNull():
                    return None
                return _pixmap_as_device_pixels(pix)
            if canvas is None and pane_count == 1:
                canvas = page.pane_canvas(0)
        if canvas is None:
            return None
        pix = _grab_pixmap_hidpi(canvas, requested=scale)
        if pix is None or pix.isNull():
            return None
        self._composite_cursor_pill_onto(pix, canvas)
        return pix

    def _presentation_canvas_and_page(self, target):
        mode = getattr(target, "_chart_mode", "")
        if hasattr(target, "canvas") and mode:
            canvas = target.canvas
            page = None
            if mode in ("fft", "fft_time", "frf", "order"):
                page = self.page_for_mode.get(mode)
            return canvas, page
        if callable(getattr(target, "pane_count", None)):
            return None, target
        canvas = target
        card = self._card_for_canvas(canvas)
        mode = getattr(card, "_chart_mode", "") if card is not None else ""
        page = None
        if mode in ("fft", "fft_time", "frf", "order"):
            page = self.page_for_mode.get(mode)
        return canvas, page

    def _composite_cursor_pill_onto(self, pix, canvas):
        """Paint the overlapping cursor pill onto ``pix`` in bitmap space."""
        pill = self._pill_for_canvas(canvas)
        if pill is None or pix is None or pix.isNull():
            return
        try:
            if not pill.isVisible():
                return
            canvas_w = max(1, int(canvas.width()))
            canvas_h = max(1, int(canvas.height()))
        except RuntimeError:
            return
        scale_x = max(1.0, float(pix.width()) / float(canvas_w))
        scale_y = max(1.0, float(pix.height()) / float(canvas_h))
        try:
            canvas_origin = canvas.mapTo(self.stack, canvas.rect().topLeft())
        except (RuntimeError, TypeError):
            return
        pill_geo = pill.geometry()
        rel_x = pill_geo.x() - canvas_origin.x()
        rel_y = pill_geo.y() - canvas_origin.y()
        if not (rel_x + pill_geo.width() > 0 and rel_x < canvas.width()
                and rel_y + pill_geo.height() > 0 and rel_y < canvas.height()):
            return
        painter = QPainter(pix)
        target = QRect(
            int(round(rel_x * scale_x)),
            int(round(rel_y * scale_y)),
            int(round(pill_geo.width() * scale_x)),
            int(round(pill_geo.height() * scale_y)),
        )
        painter.drawPixmap(
            target,
            self._grab_pill_scaled(max(scale_x, scale_y), pill),
        )
        painter.end()

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
        pix = self.grab_presentation_pixmap(card, scale=_HIDPI_EXPORT_SCALE)
        if pix is not None and not pix.isNull():
            self.image_captured.emit(pix)

    def _grab_pill_scaled(self, scale, pill=None):
        """Grab the cursor pill at ``scale``× for crisp compositing.

        At 1× this is a plain ``QPixmap`` grab; above 1× the pill widget is
        re-rendered into a magnified QImage (sharp text, not an upscale)."""
        if pill is None:
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

    def _cursor_source_on_screen(self, source):
        """True when the emitting canvas belongs to the currently visible section.

        Off-screen analysis canvases share the primary pill via
        ``_pill_for_canvas``, so their empty-readout emits must not clear a
        time-domain dual-cursor pill. ``source is None`` is the historical
        primary-time-canvas call and is treated as on-screen.
        """
        if source is None:
            return True
        card = self._card_for_canvas(source)
        if card is self._secondary_card:
            return self.current_mode() == 'time'
        return getattr(card, '_chart_mode', None) == self.current_mode()

    def _cursor_pill_visible_for_mode(self, mode=None, source=None):
        mode = self.current_mode() if mode is None else mode
        if mode == 'time':
            return True
        if mode in {'fft', 'frf'}:
            card = self._card_for_canvas(source)
            getter = getattr(card, 'cursor_mode', None)
            return bool(callable(getter) and getter() != 'off')
        return False

    def _update_pill_content(self, pill, card, update):
        """Run ``update`` (a content mutation that may resize ``pill``) and then
        settle geometry: user-placed pills keep their pre-update right edge and
        top (clamped to the stack), default pills re-anchor to ``card``'s canvas.

        This is the single seam every size-changing cursor readout must pass
        through so single/dual switching never drifts or overflows the parent.
        """
        was_user_placed = pill.is_user_placed()
        old_right = pill.x() + pill.width()
        old_top = pill.y()
        update()
        if not pill.isVisible():
            return
        if was_user_placed:
            pill.move_preserving_right_edge(old_right, old_top)
            pill.raise_()
        else:
            self._reposition_one_pill(pill, card)

    def _on_cursor_info(self, text, source=None):
        if not self._cursor_source_on_screen(source):
            return
        mode = self._cursor_mode_for_canvas(source)
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)
        if not text:
            self._update_pill_content(pill, card, pill.clear)
            return
        if mode == 'single':
            # Compatibility callers may emit only ``cursor_info``. Drop an
            # older empty-dual cache so the pill's mini toggle does not revive
            # that stale projection. The live canvas emits single_cursor_rows
            # immediately after this signal and repopulates the cache.
            cache_source = self.canvas_time if source is None else source
            self._cursor_rows_by_canvas.pop(cache_source, None)

        def update():
            if mode == 'single':
                primary, detail, mini_detail, tooltip = (
                    self._format_single_cursor_variants_for_pill(text)
                )
                pill.set_primary(primary)
                pill.set_single_detail_html(detail, mini_detail, tooltip)
            else:
                primary, _detail = self._format_cursor_info_for_pill(text, mode)
                pill.set_primary(primary)
            pill.setVisible(
                self._cursor_pill_visible_for_mode(self.current_mode(), source)
            )

        self._update_pill_content(pill, card, update)

    # ---- readout formatting (implemented in cursor_pill.py) ----
    # Thin delegates: the formatting itself is pure text processing and lives
    # next to the widget it feeds. Only the `mode` default is resolved here,
    # because that is the one part that reads live state.

    def _format_cursor_info_for_pill(self, text, mode=None):
        if mode is None:
            mode = self.cursor_mode()
        return format_cursor_info(text, mode)

    def _format_single_cursor_variants_for_pill(self, text):
        return format_single_cursor_variants(text)

    def _mini_single_cursor_part(self, part, top_pad):
        return mini_single_cursor_part(part, top_pad)

    def _plain_single_cursor_tooltip_line(self, part):
        return plain_single_cursor_tooltip_line(part)

    def _single_cursor_channel_color(self, part):
        return single_cursor_channel_color(part)

    def _strip_html(self, value):
        return strip_html(value)

    def _on_dual_cursor_info(self, text, source=None):
        if not self._cursor_source_on_screen(source):
            return
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)

        def update():
            pill.set_detail_html(text)
            if (self._cursor_pill_visible_for_mode(self.current_mode(), source)
                    and (text or pill.primary_text())):
                pill.setVisible(True)

        self._update_pill_content(pill, card, update)

    def _on_dual_cursor_rows(self, rows, source=None):
        if not self._cursor_source_on_screen(source):
            return
        source = self.canvas_time if source is None else source
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        channels = tuple(self._cursor_display_channel_from_dual(row) for row in rows)
        x_mode = (
            "custom"
            if any(dual_row_is_custom_x(row) for row in rows)
            else self._cursor_x_mode(source, channels)
        )
        self._cursor_rows_by_canvas[source] = ("dual", x_mode, channels)
        self._refresh_cursor_projection(source)

    def _on_single_cursor_rows(self, rows, source=None):
        if not self._cursor_source_on_screen(source):
            return
        source = self.canvas_time if source is None else source
        self._active_cursor_card = self._card_for_canvas(source)
        channels = tuple(rows or ())
        self._cursor_rows_by_canvas[source] = (
            "single",
            self._cursor_x_mode(source, channels),
            channels,
        )
        self._refresh_cursor_projection(source)

    def _cursor_x_mode(self, source, channels):
        if any(getattr(channel, "branches", ()) for channel in channels):
            return "custom"
        cursor = getattr(source, "_cursor", None)
        checker = getattr(cursor, "_is_custom_x_cursor", None)
        return "custom" if callable(checker) and checker() else "time"

    def _cursor_display_channel_from_dual(self, row):
        if not hasattr(row, "channel_name"):
            name, minimum, maximum, average, delta, unit_suffix, color = row[:7]
            return CursorDisplayChannel(
                identity=name,
                source_label="",
                channel_label=str(name),
                color=str(color or "#111827"),
                unit_suffix=str(unit_suffix or ""),
                delta=delta,
                min_value=minimum,
                max_value=maximum,
                avg_value=average,
            )
        name = str(getattr(row, "label", "") or getattr(row, "channel_name", ""))
        identity = getattr(row, "identity", None)
        source_label, channel_label = self._cursor_identity_labels(identity, name)
        branches = tuple(
            CursorDisplayBranch(
                branch.branch_label,
                min_value=branch.min_value,
                max_value=branch.max_value,
                avg_value=branch.avg,
            )
            for branch in getattr(row, "branches", ())
        )
        return CursorDisplayChannel(
            identity=identity,
            source_label=source_label,
            channel_label=channel_label,
            color=str(getattr(row, "color", "#111827") or "#111827"),
            unit_suffix=str(getattr(row, "unit_suffix", "") or ""),
            delta=getattr(row, "delta", None),
            min_value=getattr(row, "min_value", None),
            max_value=getattr(row, "max_value", None),
            avg_value=getattr(row, "avg", None),
            branches=branches,
            diagnostic=str(getattr(row, "status", "") or ""),
        )

    def _cursor_identity_labels(self, identity, display_name):
        prefix, channel_label = _split_prefixed_label(str(display_name))
        source_label = prefix[1:-1] if prefix else ""
        parsed = identity
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except (TypeError, ValueError):
                parsed = None
        if isinstance(parsed, (tuple, list)) and len(parsed) == 2:
            source_label = str(parsed[0])
        return source_label, str(channel_label)

    def _refresh_cursor_projection(self, source):
        cached = self._cursor_rows_by_canvas.get(source)
        if cached is None:
            return
        cursor_mode, x_mode, channels = cached
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)
        projection = build_cursor_presentation(
            channels,
            self._cursor_display_options,
            cursor_mode=cursor_mode,
            x_mode=x_mode,
            mini=pill.display_mode() == "mini",
        )

        def update():
            pill.set_display_projection(projection)
            if self.current_mode() == 'time' and (
                channels or pill.primary_text()
            ):
                pill.setVisible(True)

        self._update_pill_content(pill, card, update)

    def _on_cursor_pill_display_mode_changed(self, _mode, *, source):
        self._refresh_cursor_projection(source)

    def cursor_display_options(self):
        return self._cursor_display_options

    def _on_cursor_display_options_changed(self, options, *, source_card=None):
        if not isinstance(options, CursorDisplayOptions):
            raise TypeError("options must be CursorDisplayOptions")
        self._cursor_display_options = options
        self._cursor_display_store.save(options)
        for card in (self._time_card, self._secondary_card):
            if card is not None:
                card.set_cursor_display_options(options)
        for canvas in (self.canvas_time, self.secondary_canvas()):
            if canvas is not None:
                canvas.set_cursor_display_options(options)
        if source_card is not None:
            for card in (self._time_card, self._secondary_card):
                if card is not None and card is not source_card:
                    card.close_cursor_display_popover()
        for canvas in tuple(self._cursor_rows_by_canvas):
            self._refresh_cursor_projection(canvas)

    def _on_cursor_display_popover_geometry_changed(
        self, geometry, *, source_card
    ):
        canvas = getattr(source_card, "canvas", None)
        pill = self._pill_for_canvas(canvas)
        if geometry is None:
            pill.restore_after_avoidance()
            if pill.isVisible():
                pill.raise_()
            return
        for card in (self._time_card, self._secondary_card):
            if card is not None and card is not source_card:
                card.close_cursor_display_popover()
        pill.avoid_global_rect(geometry, gap=8)
        if pill.isVisible():
            pill.raise_()

    def _on_frequency_cursor_rows(self, rows, source=None):
        """Render FFT A/B values through the pill's reversible row contract."""
        if not self._cursor_source_on_screen(source):
            return
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)

        def update():
            pill.set_frequency_dual_rows(rows)
            if (
                self._cursor_pill_visible_for_mode(self.current_mode(), source)
                and (rows or pill.primary_text())
            ):
                pill.setVisible(True)

        self._update_pill_content(pill, card, update)

    def _reposition_pill(self):
        current = self.current_mode()
        active_canvas = getattr(self._active_cursor_card, 'canvas', None)
        if not self._cursor_pill_visible_for_mode(current, active_canvas):
            self._pill.setVisible(False)
            if self._pill_secondary is not None:
                self._pill_secondary.setVisible(False)
            return
        if current != 'time':
            active_mode = getattr(self._active_cursor_card, '_chart_mode', None)
            if active_mode != current:
                self._pill.setVisible(False)
                if self._pill_secondary is not None:
                    self._pill_secondary.setVisible(False)
                return
            if self._pill_secondary is not None:
                self._pill_secondary.setVisible(False)
            self._reposition_one_pill(self._pill, self._active_cursor_card)
            return
        self._reposition_one_pill(self._pill, self._time_card)
        if self._pill_secondary is not None and self._secondary_card is not None:
            self._reposition_one_pill(self._pill_secondary, self._secondary_card)

    def _reposition_one_pill(self, pill, card):
        """Anchor ``pill`` to ``card``'s canvas top-right corner (or honour
        its user-placed position)."""
        if not pill.isVisible():
            return
        safe = pill.safe_rect()
        if pill.is_user_placed():
            x = max(safe.left(), min(pill.x(), safe.right() - pill.width() + 1))
            y = max(safe.top(), min(pill.y(), safe.bottom() - pill.height() + 1))
            pill.move(x, y)
        else:
            canvas = getattr(card, 'canvas', None)
            if canvas is not None:
                origin = canvas.mapTo(self.stack, canvas.rect().topLeft())
                x_right = origin.x() + canvas.width()
                x = min(x_right - pill.width() - 8,
                        safe.right() - pill.width() + 1)
                y = origin.y() + 8
            else:
                x = safe.right() - pill.width() + 1
                y = safe.top()
            pill.move(
                max(safe.left(), x),
                max(safe.top(), min(y, safe.bottom() - pill.height() + 1)),
            )
        pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pill()

    def clear_cursor_pill(self):
        """Clear pill content and hide it; preserves the user-placed flag so a
        subsequent cursor activation reappears at the spot the user chose."""
        for card in (self._time_card, self._secondary_card):
            if card is not None:
                card.close_cursor_display_popover()
        self._pill.clear()
        if self._pill_secondary is not None:
            self._pill_secondary.clear()
        self._cursor_rows_by_canvas.clear()

    def closeEvent(self, event):
        for card in (self._time_card, self._secondary_card):
            if card is not None:
                card.close_cursor_display_popover()
        self.clear_cursor_pill()
        super().closeEvent(event)

    def cursor_pill_snapshot(self):
        """Return the current floating cursor pill UI state.

        The pill content is not part of ViewState; it reflects the last cursor
        hover/readout on the active canvas. Split rendering temporarily applies
        another view through the primary controls, so callers can use this to
        preserve the active readout across that off-screen render.
        """
        snapshot = self._pill.snapshot()
        snapshot.update({
            'visible': self._pill.isVisible(),
            'primary': self._pill.primary_text(),
            'detail': self._pill.detail_text(),
            'detail_visible': self._pill.has_detail(),
            'user_placed': self._pill.is_user_placed(),
            'pos': (self._pill.x(), self._pill.y()),
        })
        return snapshot

    def restore_cursor_pill_snapshot(self, snapshot):
        if not snapshot:
            return
        self._pill.restore_snapshot(snapshot)
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

    def cursor_pill_fingerprint(self, canvas=None):
        """Stable dual-cursor readout fingerprint, or ``None`` if hidden.

        ``canvas`` selects the primary or split-secondary pill. Hidden pills
        are not a source change.
        """
        try:
            pill = self._pill_for_canvas(canvas)
        except (TypeError, RuntimeError):
            return None
        if pill is None:
            return None
        try:
            if not pill.isVisible():
                return None
            primary = ""
            getter = getattr(pill, "primary_text", None)
            if callable(getter):
                primary = getter() or ""
            detail = ""
            has_detail = getattr(pill, "has_detail", None)
            detail_text = getattr(pill, "detail_text", None)
            if callable(has_detail) and has_detail() and callable(detail_text):
                detail = detail_text() or ""
            return (primary, detail)
        except RuntimeError:
            return None
