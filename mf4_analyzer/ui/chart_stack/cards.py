"""_ChartCard and TimeChartCard widget classes."""
from PyQt5.QtCore import QEvent, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (
    QAction, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

import qtawesome as qta

from ...ui_kit.icons import Icons
from .. import hints
from ..file_navigator import _ElidedLabel
from ..pg_canvases import TimeDomainCanvasPG
from ..pg_canvas.heatmap_canvas import PgHeatmapCanvas
from ..pg_canvas.line_canvas import PgLineCanvas

from ._helpers import (
    _strip_subplots_action,
    _find_action,
    _apply_mdi_icons,
    _install_nav_shortcuts,
    _install_button_shortcut,
    _vline,
    _ICON_COLOR,
    _ICON_ACTIVE,
    _TOOLBAR_COMPACT_WIDTH,
)
from .toolbar import PgNavigationToolbar, _TickDensityPopover
from .cursor_pill import _QualityStatusIndicator


class _TimePlotDiagnosticsPill(QFrame):
    """Compact, card-owned summary for partially rendered TimeDomain plots.

    The widget deliberately lives above the canvas widget instead of inside
    the pyqtgraph scene: panning/zooming must never move the diagnostic.  Its
    summary is always one line; details are disclosed only when requested.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timePlotDiagnosticsPill")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#timePlotDiagnosticsPill {"
            "background:#fff7e6;border:1px solid #f0b44d;"
            "border-radius:9px;}"
            "QToolButton#timePlotDiagnosticsButton {"
            "border:0;background:transparent;color:#7a4b00;"
            "font-weight:600;padding:3px 7px;text-align:left;}"
            "QLabel#timePlotDiagnosticsDetails {"
            "color:#65420c;padding:0 8px 6px 8px;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._button = QToolButton(self)
        self._button.setObjectName("timePlotDiagnosticsButton")
        self._button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.clicked.connect(self._toggle_details)
        self._details = QLabel("", self)
        self._details.setObjectName("timePlotDiagnosticsDetails")
        self._details.setTextFormat(Qt.PlainText)
        self._details.setWordWrap(True)
        self._details.hide()
        layout.addWidget(self._button)
        layout.addWidget(self._details)
        self.hide()

    def set_diagnostics(self, *, attempted, successful, details):
        attempted = max(0, int(attempted))
        successful = max(0, min(int(successful), attempted))
        details = tuple(str(item) for item in details if str(item).strip())
        failed = max(0, attempted - successful)
        if failed == 0 or not details:
            self._details.hide()
            self.hide()
            return
        self._button.setText(
            f"⚠ 已绘制 {successful}/{attempted} · {failed} 条未绘制"
        )
        self._details.setText("\n".join(f"• {item}" for item in details))
        self._details.hide()
        self.show()
        self.adjustSize()

    def _toggle_details(self):
        self._details.setVisible(self._details.isHidden())
        self.adjustSize()
        parent = self.parentWidget()
        reposition = getattr(parent, "_position_time_diagnostics", None)
        if callable(reposition):
            reposition()


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""

    copy_image_requested = pyqtSignal()  # emitted when the toolbar copy btn is clicked
    annotation_enabled_changed = pyqtSignal(bool)
    tick_density_changed = pyqtSignal(int, int)
    quickref_requested = pyqtSignal()

    def __init__(self, canvas, parent=None, annotations=False, chart_mode=''):
        super().__init__(parent)
        self.setObjectName("chartCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self.canvas.installEventFilter(self)
        try:
            viewport = canvas._glw.viewport()
        except Exception:
            viewport = None
        self._canvas_viewport = viewport
        if viewport is not None:
            viewport.installEventFilter(self)
        self._chart_mode = chart_mode
        self._annotation_enabled = False
        self._hint_settings = QSettings()
        self._recent_context_hint_ids = set()
        self._context_hint_index = 0
        self._context_hint_signature = ()
        # Round-robin start offset into the rotation lap, read once per session
        # so a fresh open does not always lead with the same anchor. Lazily
        # resolved (and advanced) from _hint_settings on first use.
        self._rotation_start = None
        self._hint_rotation_paused = False
        # Variable-dwell rotation: a single-shot timer that re-arms itself with
        # the CURRENT hint's dwell after each advance (replaces the old fixed
        # 10s interval). High-priority/anchor hints linger; low-frequency tips
        # get a short turn each lap.
        self._hint_rotation_timer = QTimer(self)
        self._hint_rotation_timer.setSingleShot(True)
        self._hint_rotation_timer.timeout.connect(self._advance_context_hint)
        # Pick the pyqtgraph-aware shim for supported chart canvases. The shim
        # exposes the exact same six action keys + mode/pan/zoom surface so
        # downstream helpers (i18n, MDI icons, shortcuts, _find_action) keep
        # working unchanged.
        if isinstance(canvas, (TimeDomainCanvasPG, PgHeatmapCanvas, PgLineCanvas)):
            self.toolbar = PgNavigationToolbar(canvas, self)
            # Bug 3: re-apply the toolbar's current pan/zoom mode to the
            # ViewBoxes that plot_channels rebuilds, so box-zoom survives a
            # replot/mode-switch (fresh ViewBoxes default to PanMode).
            register = getattr(canvas, 'register_replot_callback', None)
            if callable(register):
                register(self.toolbar.apply_current_mouse_mode)
                # Task 1: re-bind the view-history capture hook to the fresh
                # ViewBoxes each rebuild creates, and seed a baseline view so
                # back() has somewhere to return to. Registered AFTER the mode
                # re-apply so the capture sees the fully-built axes_list.
                register(self.toolbar.rebind_history_capture)
            # Design D: make the toolbar the canvas's single mouse-mode
            # controller so the right-click 鼠标操作 submenu and the toolbar
            # share one state machine. The menu reads current_mouse_mode() for
            # its checkmark and calls set_pan_mode()/set_zoom_mode() on click.
            reg_mode = getattr(canvas, 'register_mouse_mode_controller', None)
            if callable(reg_mode):
                reg_mode(self.toolbar)
            reg_copy = getattr(canvas, 'register_copy_image_handler', None)
            if callable(reg_copy):
                reg_copy(self.copy_image_requested.emit)
            # When the menu (or any path) changes the mode, refresh the
            # toolbar icon active-state + bottom hint, and let TimeChartCard
            # flip its axis-lock chips, exactly as a toolbar-button click would.
            self.toolbar.mouse_mode_changed.connect(self._on_mouse_mode_changed)
        else:
            raise TypeError(
                f"unsupported canvas type for toolbar: {type(canvas).__name__}"
            )
        context_menu_requested = getattr(canvas, 'context_menu_requested', None)
        if context_menu_requested is not None:
            context_menu_requested.connect(
                lambda: self.mark_discovered("chart.right_click_menu")
            )
        manual_zoom_changed = getattr(canvas, 'manual_zoom_changed', None)
        if manual_zoom_changed is not None:
            manual_zoom_changed.connect(self.set_transient_zoom_hint)
        # Hidden-gesture discovery wiring. Each canvas exposes a signal that
        # fires the first time the user performs the gesture; we mark the
        # matching discovery echo (so its rotating-pool tip retires) and flash a
        # one-shot confirmation in the footer. Mirrors the context-menu wiring
        # above. getattr-guarded so canvases without the signal are unaffected.
        self._wire_discovery_signal(
            canvas, 'slice_picked', 'spectrogram.slice_pick')
        self._wire_discovery_signal(
            canvas, 'divider_adjusted', 'spectrogram.divider')
        self._wire_discovery_signal(
            canvas, 'levels_changed', 'spectrogram.colorbar')
        self._wire_discovery_signal(
            canvas, 'time_source_selected', 'fft.preview_source')
        slice_hint_requested = getattr(canvas, 'slice_hint_requested', None)
        if slice_hint_requested is not None:
            slice_hint_requested.connect(self._on_slice_hint_requested)
        # Refresh situational nudges when the data situation changes: a chart
        # rebuild (time: channel count / units / amplitude) or a render-time
        # colour-level rebase (heatmap: dead colour window). getattr-guarded so
        # canvases lacking the signal are unaffected.
        for sig_name in ('chart_rebuilt', 'levels_rebased'):
            sig = getattr(canvas, sig_name, None)
            if sig is not None:
                sig.connect(self._refresh_bottom_hint)
        self.toolbar.setObjectName("chartToolbar")
        self.toolbar.setIconSize(QSize(18, 18))
        for act in self.toolbar.actions():
            btn = self.toolbar.widgetForAction(act)
            if btn is not None and isinstance(btn, QToolButton):
                btn.setFixedSize(QSize(32, 32))
        if self.toolbar.layout() is not None:
            self.toolbar.layout().setSpacing(8)
        self._toolbar_compact = None
        _strip_subplots_action(self.toolbar)
        self._remove_toolbar_loc_label()
        self._toolbar_leading_spacer = QWidget(self.toolbar)
        self._toolbar_leading_spacer.setObjectName("chartToolbarLeadingSpacer")
        self._toolbar_leading_spacer.setAttribute(Qt.WA_TranslucentBackground, True)
        self._toolbar_leading_spacer.setAttribute(Qt.WA_NoSystemBackground, True)
        self._toolbar_leading_spacer.setAutoFillBackground(False)
        self._toolbar_leading_spacer.setFixedWidth(4)
        first_action = self.toolbar.actions()[0] if self.toolbar.actions() else None
        self._toolbar_leading_spacer_action = (
            self.toolbar.insertWidget(first_action, self._toolbar_leading_spacer)
            if first_action is not None else self.toolbar.addWidget(self._toolbar_leading_spacer)
        )

        # Find Save BEFORE i18n changes labels (text is still 'Save' here);
        # the reference stays valid after relabel because we keep the QAction.
        save_act = _find_action(self.toolbar, 'save')

        # Apply Chinese tooltips & drop Back/Forward; this also calls
        # setData(key) on each retained action so subsequent _find_action
        # lookups by english key remain stable across locales.
        from .._toolbar_i18n import apply_chinese_toolbar_labels
        apply_chinese_toolbar_labels(self.toolbar)
        _install_nav_shortcuts(self, self.toolbar)
        _apply_mdi_icons(self.toolbar, active_key='pan')

        # Insert app-level chart actions right before the Save action (or append
        # if save action isn't found). This keeps them beside the nav icons.
        self._options_btn = QToolButton(self.toolbar)
        self._options_btn.setObjectName("chartOptionsButton")
        self._options_btn.setIcon(qta.icon('mdi.tune-vertical', color=_ICON_COLOR))
        self._options_btn.setIconSize(QSize(18, 18))
        self._options_btn.setFixedSize(QSize(32, 32))
        self._options_btn.setToolTip("图表选项")
        self._options_btn.setAutoRaise(True)
        self._options_btn.clicked.connect(self.open_chart_options)
        self._copy_btn = QToolButton(self.toolbar)
        self._copy_btn.setIcon(qta.icon('mdi.content-copy', color=_ICON_COLOR))
        self._copy_btn.setIconSize(QSize(18, 18))
        self._copy_btn.setFixedSize(QSize(32, 32))
        self._copy_btn.setToolTip("复制为图片（含游标线和读数）")
        self._copy_btn.setAutoRaise(True)
        self._copy_btn.clicked.connect(self.copy_image_requested)
        self.copy_image_requested.connect(
            lambda: self.mark_discovered("chart.copy_image")
        )
        self._tick_density_popover = _TickDensityPopover(self)
        self._tick_density_popover.density_changed.connect(
            self._on_tick_density_changed
        )
        self._tick_density_btn = QToolButton(self.toolbar)
        self._tick_density_btn.setObjectName("chartTickDensityButton")
        self._tick_density_btn.setIcon(
            qta.icon('ri.ruler-2-line', color=_ICON_COLOR)
        )
        self._tick_density_btn.setIconSize(QSize(18, 18))
        self._tick_density_btn.setFixedSize(QSize(32, 32))
        self._tick_density_btn.setToolTip("刻度密度 X10 / Y10")
        self._tick_density_btn.setFocusPolicy(Qt.NoFocus)
        self._tick_density_btn.setAutoRaise(True)
        self._tick_density_btn.clicked.connect(self._show_tick_density_popover)
        self._tick_density_sep = _vline()
        if save_act is not None:
            self.toolbar.insertWidget(save_act, self._copy_btn)
            self.toolbar.insertWidget(save_act, self._tick_density_sep)
            self.toolbar.insertWidget(save_act, self._tick_density_btn)
            self.toolbar.insertWidget(save_act, self._options_btn)
        else:
            self.toolbar.addWidget(self._copy_btn)
            self.toolbar.addWidget(self._tick_density_sep)
            self.toolbar.addWidget(self._tick_density_btn)
            self.toolbar.addWidget(self._options_btn)

        self._loc_action = None

        if annotations:
            zoom_act = _find_action(self.toolbar, 'zoom')
            self._install_compact_annotation_control_after(zoom_act)
            annotation_act = self._toolbar_action_for_widget(
                self._annotation_btn
            )
            self._install_compact_clear_annotation_control_after(annotation_act)

        # Only pan/zoom toggling changes the hint; one-shot buttons don't.
        # Subclasses (TimeChartCard) listen to this same signal to flip the
        # axis-lock chip group enabled state.
        # Match by act.data() (set by apply_chinese_toolbar_labels) first so
        # the hookup survives matplotlib locale/text changes; fall back to
        # english text for any action that wasn't relabeled.
        for act in self.toolbar.actions():
            name = act.data() if act.data() else (act.text() or '').strip().lower()
            if name in ('pan', 'zoom'):
                act.triggered.connect(self._on_nav_mode_toggled)

        # Bottom hint bar. Sits BELOW the canvas so it does not jostle the
        # toolbar layout. The old static persistent label is RETIRED: the base
        # gestures are now the highest-weight, longest-dwell entries of the
        # rotating pool (hints.rotation_hints), so the left slot is a single
        # rotating row whose text matches the active section. The right slot is
        # the discovery ("this exists") hint.
        #
        # 提示位置 (left / right edges): the rotating row hugs the LEFT edge and
        # the discovery hint hugs the RIGHT edge, with the empty gap between them
        # in the middle (no centered group, no separator). Hint text is
        # length-capped at the registry (hints.HINT_MAX_WIDTH) so the two slots
        # fit side by side on a normal-width bar. When the bar is too narrow for
        # both, the left rotating row (Preferred + ElideRight, min 0) yields width
        # first and elides, so the right discovery row is never pushed off the bar.
        self._hint_bar = QFrame(self)
        self._hint_bar.setObjectName("chartHintBar")
        self._hint_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._hint_bar.setFixedHeight(22)
        bar_lay = QHBoxLayout(self._hint_bar)
        bar_lay.setContentsMargins(4, 2, 4, 2)
        bar_lay.setSpacing(0)
        self._hint_context = _ElidedLabel("", self._hint_bar)
        self._hint_context.setObjectName("chartHintContext")
        self._hint_context.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # _ElidedLabel defaults to Ignored (collapses to 0); Preferred + stretch
        # lets the left slot own the whole left span (left-aligned text, empty
        # gap to its right) yet still shrink to min-0 and elide under a narrow bar.
        self._hint_context.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._flash_hint_timer = QTimer(self)
        self._flash_hint_timer.setSingleShot(True)
        self._flash_hint_timer.setInterval(2500)
        self._flash_hint_timer.timeout.connect(self._restore_rotating_hint)
        if hasattr(self.canvas, 'overlay_y_needs_selection'):
            self.canvas.overlay_y_needs_selection.connect(
                self._on_overlay_y_needs_selection
            )
        self._hint_discovery = QLabel("", self._hint_bar)
        self._hint_discovery.setObjectName("chartHintDiscovery")
        self._hint_discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Minimum (not Maximum): the discovery slot must never shrink below its
        # full text. Pinned to the right edge, it stays firm while the left
        # rotating row (stretch=1, min-0) absorbs all the shrink and elides — so
        # a long left hint can never squeeze the discovery row off the bar.
        self._hint_discovery.setSizePolicy(
            QSizePolicy.Minimum, QSizePolicy.Preferred
        )
        self._hint_quickref_btn = QToolButton(self._hint_bar)
        self._hint_quickref_btn.setObjectName("chartHintQuickrefButton")
        self._hint_quickref_btn.setText("?")
        self._hint_quickref_btn.setAutoRaise(True)
        self._hint_quickref_btn.setCursor(Qt.PointingHandCursor)
        self._hint_quickref_btn.setToolTip("操作速查 (?)")
        self._hint_quickref_btn.clicked.connect(self.quickref_requested.emit)
        # Two edge-anchored slots, no centered group / separator: the rotating
        # gesture row hugs the LEFT edge (stretch=1, so it owns the whole left
        # span and elides there if too long), the discovery row hugs the RIGHT
        # edge. A long left row can never squeeze the right row off the bar.
        bar_lay.addWidget(self._hint_quickref_btn, 0, Qt.AlignVCenter)
        bar_lay.addWidget(self._hint_context, 1)
        bar_lay.addWidget(self._hint_discovery, 0)

        # Default: activate the pan tool.
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' not in mode:
            self.toolbar.pan()
        # _refresh_hint -> _set_context_hint arms the single-shot rotation timer
        # with the first hint's dwell, so no explicit fixed-interval start here.
        self._refresh_hint()

        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)
        lay.addWidget(self._hint_bar)

        # Split-focus marker: a thin accent strip overlaid on the TOP of the
        # card, raised above the canvas. A QSS border on the card is unreliable
        # here — the full-bleed pyqtgraph canvas paints over it (observed: top
        # stays white) — so we use a real overlay widget instead. It is card
        # chrome, so image export (which grabs canvas pixels) never includes it.
        self._focus_bar = QWidget(self)
        self._focus_bar.setObjectName("chartFocusBar")
        self._focus_bar.setFixedHeight(3)
        self._focus_bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._focus_bar.hide()

        self._quality_indicator = None
        self._quality_indicator_position_pending = False
        quality_signal = getattr(self.canvas, "quality_status_changed", None)
        quality_status = getattr(self.canvas, "quality_status", None)
        if quality_signal is not None and callable(quality_status):
            self._quality_indicator = _QualityStatusIndicator(self)
            quality_signal.connect(self._set_quality_status)
            self._set_quality_status(quality_status())

        self._time_diagnostics = (
            _TimePlotDiagnosticsPill(self) if chart_mode == 'time' else None
        )
        self._time_diagnostics_position_pending = False

    def _position_focus_bar(self):
        bar = getattr(self, "_focus_bar", None)
        if bar is not None:
            bar.setGeometry(0, 0, self.width(), bar.height())

    def _position_quality_indicator(self):
        indicator = getattr(self, "_quality_indicator", None)
        canvas = getattr(self, "canvas", None)
        if indicator is None or canvas is None:
            return
        canvas_rect = canvas.geometry()
        margin = 6
        x = canvas_rect.right() - indicator.width() - margin + 1
        y = canvas_rect.bottom() - indicator.height() - margin + 1
        indicator.move(max(0, x), max(0, y))
        indicator.raise_()

    def _position_time_diagnostics(self):
        pill = getattr(self, "_time_diagnostics", None)
        canvas = getattr(self, "canvas", None)
        if pill is None or canvas is None or pill.isHidden():
            return
        canvas_rect = canvas.geometry()
        margin = 6
        max_width = max(160, canvas_rect.width() - (margin * 2))
        pill.setMaximumWidth(min(520, max_width))
        pill.adjustSize()
        x = canvas_rect.left() + margin
        y = canvas_rect.bottom() - pill.height() - margin + 1
        pill.move(max(0, x), max(0, y))
        pill.raise_()

    def _schedule_time_diagnostics_position(self):
        pill = getattr(self, "_time_diagnostics", None)
        if pill is None or pill.isHidden():
            return
        if getattr(self, "_time_diagnostics_position_pending", False):
            return
        self._time_diagnostics_position_pending = True
        QTimer.singleShot(0, self._flush_time_diagnostics_position)

    def _flush_time_diagnostics_position(self):
        self._time_diagnostics_position_pending = False
        try:
            self._position_time_diagnostics()
        except RuntimeError:
            # A queued reposition can outlive the card during application exit.
            pass

    def set_time_plot_diagnostics(self, *, attempted, successful, details):
        """Show a partial-render summary, or clear it after full success."""
        pill = getattr(self, "_time_diagnostics", None)
        if pill is None:
            return
        pill.set_diagnostics(
            attempted=attempted,
            successful=successful,
            details=details,
        )
        self._position_time_diagnostics()
        self._schedule_time_diagnostics_position()

    def _schedule_quality_indicator_position(self):
        indicator = getattr(self, "_quality_indicator", None)
        if indicator is None:
            return
        if getattr(self, "_quality_indicator_position_pending", False):
            return
        self._quality_indicator_position_pending = True
        QTimer.singleShot(0, self._flush_quality_indicator_position)

    def _flush_quality_indicator_position(self):
        self._quality_indicator_position_pending = False
        try:
            self._position_quality_indicator()
        except RuntimeError:
            # The queued singleShot can fire after Qt has already torn down the
            # canvas/card C++ object; there is nothing left to position.
            pass

    def _set_quality_status(self, status):
        indicator = getattr(self, "_quality_indicator", None)
        if indicator is None:
            return
        indicator.set_quality_status(status)
        self._position_quality_indicator()

    def set_focus_marker(self, color):
        """Show a top accent strip in ``color`` (the focused split pane), or
        hide it when ``color`` is falsy. The strip overlays the canvas top."""
        bar = getattr(self, "_focus_bar", None)
        if bar is None:
            return
        if color:
            bar.setStyleSheet(
                f"background-color:{color};"
                "border-top-left-radius:11px;border-top-right-radius:11px;"
            )
            self._position_focus_bar()
            bar.raise_()
            bar.show()
        else:
            bar.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_toolbar()
        self._position_focus_bar()
        self._position_quality_indicator()
        self._schedule_quality_indicator_position()
        self._position_time_diagnostics()
        self._schedule_time_diagnostics_position()
        bar = getattr(self, "_focus_bar", None)
        if bar is not None and bar.isVisible():
            bar.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_responsive_toolbar()
        self._position_quality_indicator()
        self._schedule_quality_indicator_position()
        self._position_time_diagnostics()
        self._schedule_time_diagnostics_position()
        bar = getattr(self, "_focus_bar", None)
        if bar is not None and bar.isVisible():
            self._position_focus_bar()
            bar.raise_()

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            self.set_hint_rotation_paused(True)
        elif etype in (QEvent.MouseButtonRelease, QEvent.Leave):
            self.set_hint_rotation_paused(False)
        canvas = getattr(self, "canvas", None)
        if obj is canvas and etype in (
            QEvent.Resize, QEvent.Show, QEvent.LayoutRequest
        ):
            self._position_quality_indicator()
            self._schedule_quality_indicator_position()
            self._position_time_diagnostics()
            self._schedule_time_diagnostics_position()
        elif obj is getattr(self, "_canvas_viewport", None) and etype in (
            QEvent.Resize, QEvent.Show
        ):
            self._schedule_quality_indicator_position()
            self._schedule_time_diagnostics_position()
        return super().eventFilter(obj, event)

    def detach_toolbar(self, parent):
        """Remove the card toolbar from this card layout and reparent it."""
        self.layout().removeWidget(self.toolbar)
        self.toolbar.setParent(parent)
        return self.toolbar

    def _remove_toolbar_loc_label(self):
        loc_label = getattr(self.toolbar, "locLabel", None)
        if loc_label is None:
            return
        loc_label.setObjectName("chartLocLabel")
        for act in list(self.toolbar.actions()):
            if self.toolbar.widgetForAction(act) is loc_label:
                self.toolbar.removeAction(act)
                break
        loc_label.hide()

    def detach_bottom_hint_bar(self, parent):
        """Remove the bottom hint bar from this card layout and reparent it."""
        self.layout().removeWidget(self._hint_bar)
        self._hint_bar.setParent(parent)
        return self._hint_bar

    def _sync_responsive_toolbar(self):
        if not self.toolbar.isVisible():
            return
        width = self.toolbar.width()
        if width <= 0:
            return
        compact = width < _TOOLBAR_COMPACT_WIDTH
        if compact == self._toolbar_compact:
            return
        self._toolbar_compact = compact
        self.toolbar.updateGeometry()

    def _insert_toolbar_widget(self, loc_action, widget):
        if loc_action is not None:
            self.toolbar.insertWidget(loc_action, widget)
        else:
            self.toolbar.addWidget(widget)

    def _insert_right_toolbar_widget(self, loc_action, widget):
        # Insert at the card's right-control zone. Passing ``None`` appends
        # to the toolbar after the navigation/copy/save actions.
        self._insert_toolbar_widget(loc_action, widget)

    def _insert_toolbar_widget_after(self, after_action, widget):
        actions = self.toolbar.actions()
        if after_action in actions:
            index = actions.index(after_action)
            if index + 1 < len(actions):
                self.toolbar.insertWidget(actions[index + 1], widget)
                return
        self.toolbar.addWidget(widget)

    def _toolbar_action_for_widget(self, widget):
        for action in self.toolbar.actions():
            if self.toolbar.widgetForAction(action) is widget:
                return action
        return None

    def _install_compact_annotation_control_after(self, after_action):
        self._annotation_btn = QToolButton(self.toolbar)
        self._annotation_btn.setObjectName("chartAnnotationButton")
        self._annotation_btn.setIcon(Icons.annotate(QColor(_ICON_COLOR)))
        self._annotation_btn.setIconSize(QSize(18, 18))
        self._annotation_btn.setFixedSize(QSize(32, 32))
        self._annotation_btn.setCheckable(True)
        self._annotation_btn.setAutoRaise(True)
        self._annotation_btn.setToolTip("标注：开启后左键添加标注；右键删除最近标注")
        self._annotation_btn.setProperty("compactAnnotation", True)
        self._annotation_btn.clicked.connect(
            lambda checked=False: self.set_annotation_enabled(checked)
        )
        self._insert_toolbar_widget_after(after_action, self._annotation_btn)

    def _install_compact_clear_annotation_control_after(self, after_action):
        self._clear_annotation_btn = QToolButton(self.toolbar)
        self._clear_annotation_btn.setObjectName("chartAnnotationClearButton")
        self._clear_annotation_btn.setIcon(
            qta.icon('mdi.eraser', color=_ICON_COLOR)
        )
        self._clear_annotation_btn.setIconSize(QSize(18, 18))
        self._clear_annotation_btn.setFixedSize(QSize(32, 32))
        self._clear_annotation_btn.setAutoRaise(True)
        self._clear_annotation_btn.setToolTip("清除当前图表中的所有标注")
        self._clear_annotation_btn.clicked.connect(self.clear_annotations)
        self._insert_toolbar_widget_after(after_action, self._clear_annotation_btn)

    def annotation_enabled(self):
        return self._annotation_enabled

    def set_annotation_enabled(self, enabled, notify=True):
        self._annotation_enabled = bool(enabled)
        if hasattr(self.canvas, 'set_remark_enabled'):
            self.canvas.set_remark_enabled(self._annotation_enabled)
        btn = getattr(self, '_annotation_btn', None)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(self._annotation_enabled)
            icon_color = _ICON_ACTIVE if self._annotation_enabled else _ICON_COLOR
            if btn.property("compactAnnotation"):
                btn.setIcon(Icons.annotate(QColor(icon_color)))
            else:
                btn.setText("关闭" if self._annotation_enabled else "开启")
                btn.setIcon(qta.icon('mdi.map-marker-plus-outline', color=icon_color))
            btn.blockSignals(False)
        if notify:
            self.annotation_enabled_changed.emit(self._annotation_enabled)
        self._refresh_bottom_hint()

    def clear_annotations(self):
        canvas = self.canvas
        if not hasattr(canvas, 'clear_remarks'):
            return
        # 一键清空全部标注不可撤销；仅当图表里确有标注时才拦一道，
        # 空图直接静默清空，避免高频误触时的无谓弹窗。
        count = self._current_remark_count(canvas)
        if count > 0 and not self._confirm_clear_annotations(count):
            return
        canvas.clear_remarks()

    def _current_remark_count(self, canvas):
        counter = getattr(canvas, 'remark_count', None)
        if not callable(counter):
            return 0
        try:
            return int(counter())
        except Exception:
            return 0

    def _confirm_clear_annotations(self, count):
        box = QMessageBox(self)
        box.setWindowTitle('清除标注')
        box.setIcon(QMessageBox.Question)
        box.setText(f'确定清除当前图表的 {count} 个标注？')
        box.setInformativeText('清除后无法撤销。')
        clear = box.addButton('清除标注', QMessageBox.DestructiveRole)
        cancel = box.addButton('取消', QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        return box.clickedButton() is clear

    def open_chart_options(self):
        # In split mode the primary card's options button is the shared
        # toolbar's; ChartStack points _options_canvas_provider at the focused
        # canvas so 图表选项 opens for whichever pane is focused. Default: own
        # canvas (every analysis card and the non-split time card).
        provider = getattr(self, '_options_canvas_provider', None)
        canvas = provider() if callable(provider) else self.canvas
        opener = getattr(canvas, 'open_chart_options_dialog', None)
        if opener is not None:
            return opener()
        return False

    def _show_tick_density_popover(self):
        pop = self._tick_density_popover
        if pop.isVisible():
            pop.hide()
            return
        pos = self._tick_density_btn.mapToGlobal(
            self._tick_density_btn.rect().bottomLeft()
        )
        pop.move(pos.x(), pos.y() + 4)
        pop.show()
        pop.raise_()
        self._tick_density_btn.clearFocus()

    def _on_tick_density_changed(self, x, y):
        self.set_tick_density_controls(x, y)
        self.tick_density_changed.emit(int(x), int(y))

    def set_tick_density_controls(self, x, y):
        self._tick_density_popover.set_density(x, y, emit=False)
        self._tick_density_btn.setToolTip(f"刻度密度 X{int(x)} / Y{int(y)}")

    def _on_mouse_mode_changed(self, *_):
        """Design D: a mouse-mode change driven by the right-click 鼠标操作
        submenu (or any non-button path) routes through the SAME refresh as a
        toolbar-button toggle, so the icon active-state, hint text, and (in
        TimeChartCard) the axis-lock chips all reflect the new state. The
        toolbar buttons already fire ``_on_nav_mode_toggled`` via their action
        ``triggered``; this keeps the menu path symmetric without a parallel
        UI-sync codepath."""
        self._on_nav_mode_toggled()

    def _on_nav_mode_toggled(self, *_):
        """Hook subclasses can extend; base only refreshes the hint text."""
        self._refresh_hint()

    # ---- hint handling ----
    def _current_mode_key(self):
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' in mode:
            return 'pan'
        if 'zoom' in mode:
            return 'zoom'
        return ''

    # HintState fields the canvas may supply as situational nudge signals.
    _NUDGE_SIGNAL_KEYS = frozenset({
        "channel_count", "same_unit", "has_axis_group",
        "amp_disparate", "colorbar_dead", "clipped",
        "db_reference_mode", "db_reference_value",
        "db_reference_source_resolvable",
    })

    def _nudge_signals(self):
        """Pull situational signals from the canvas (getattr-guarded), filtered
        to the known HintState fields so an unexpected key can't break it.

        Two independent producers feed this: an optional ``canvas.nudge_signals()``
        callable (the pre-existing time/heatmap situational signals), and an
        optional plain ``canvas.db_reference_nudge_facts`` dict attribute
        (dB-reference-defaults nudge, spec 2026-07-12 S5 / A17) stamped by
        ``AnalysisMixin._stamp_db_reference_nudge_facts`` at render time --
        additive metadata, not a render/behavior signal."""
        getter = getattr(getattr(self, "canvas", None), "nudge_signals", None)
        raw = {}
        if callable(getter):
            try:
                raw = dict(getter() or {})
            except Exception:
                raw = {}
        facts = getattr(getattr(self, "canvas", None), "db_reference_nudge_facts", None)
        if isinstance(facts, dict):
            if "mode" in facts:
                raw["db_reference_mode"] = facts["mode"]
            if "value" in facts:
                raw["db_reference_value"] = facts["value"]
            if "source_resolvable" in facts:
                raw["db_reference_source_resolvable"] = facts["source_resolvable"]
        return {k: v for k, v in raw.items() if k in self._NUDGE_SIGNAL_KEYS}

    def _hint_state(self):
        return hints.HintState(
            mode=self._chart_mode,
            mouse_mode=self._current_mode_key(),
            chart_kind=self._chart_mode,
            annotation_on=self.annotation_enabled(),
            discovered=hints.load_discovered(self._hint_settings),
            recently_used=frozenset(self._recent_context_hint_ids),
            **self._nudge_signals(),
        )

    def _rotation_candidates(self):
        """The rotating-row pool for the current state: section base-gesture
        anchors merged with context tips, weight-ordered, with use/discovery
        decay (hints.rotation_hints)."""
        return hints.rotation_hints(self._hint_state())

    def refresh_nudge_state(self):
        """Public hook: force an immediate footer refresh from the card's
        current ``HintState``.

        Existing situational nudges refresh live because their canvas fires
        a signal the card already listens to (``chart_rebuilt`` /
        ``levels_rebased``). The dB-reference-defaults nudge (spec S5 / A17)
        is instead stamped as a plain attribute by ``AnalysisMixin.
        _stamp_db_reference_nudge_facts`` from outside any canvas signal (a
        signal-changed / mode-committed / value-committed handler), so it
        calls this after every stamp to keep the visible footer from lagging
        behind the just-updated facts -- same effect as
        ``_refresh_bottom_hint``, just under a public name for cross-module
        callers."""
        self._refresh_bottom_hint()

    def _refresh_bottom_hint(self, *_):
        state = self._hint_state()
        # A situational nudge (data-condition-gated) takes the discovery slot
        # while its condition holds; otherwise fall back to the discovery queue.
        nudge = hints.nudge_hint(state)
        if nudge is not None:
            self._hint_discovery.setText(nudge.text)
        else:
            discovery = hints.discovery_hint(state)
            self._hint_discovery.setText(discovery.text if discovery else '')
        self._set_context_hint(reset=True)

    def _rotation_start_offset(self):
        """The session's round-robin start offset (resolved + advanced once)."""
        if self._rotation_start is None:
            self._rotation_start = hints.next_rotation_start(self._hint_settings)
        return self._rotation_start

    def _set_context_hint(self, reset=False):
        candidates = self._rotation_candidates()
        signature = tuple(hint.id for hint in candidates)
        if reset or signature != self._context_hint_signature:
            # Enter the lap at the persisted offset instead of always index 0,
            # so the footer does not lead with the same anchor every open.
            self._context_hint_index = (
                self._rotation_start_offset() % len(candidates)
                if candidates else 0
            )
            self._context_hint_signature = signature
        if not candidates:
            self._hint_context.setText('')
            self._hint_rotation_timer.stop()
            return
        index = self._context_hint_index % len(candidates)
        current = candidates[index]
        self._hint_context.setText(current.text)
        self._arm_rotation_timer(current)

    def _arm_rotation_timer(self, hint):
        """(Re)start the single-shot rotation timer with this hint's dwell, so
        the next advance happens after a variable, priority-derived delay."""
        if self._hint_rotation_paused:
            return
        self._hint_rotation_timer.start(hints.rotation_dwell_ms(hint))

    def flash_hint(self, text):
        """Show a transient context hint, then restore the rotating hint."""
        self._hint_context.setText(str(text))
        # Hold the flash for its full window: pause the rotation timer so a
        # variable-dwell advance cannot overwrite the flash mid-display. The
        # flash timer's timeout (_set_context_hint(reset=True)) re-arms rotation.
        self._hint_rotation_timer.stop()
        self._flash_hint_timer.start()

    def set_transient_zoom_hint(self, on):
        """Show or clear the analysis-canvas transient-zoom footer hint."""
        self._flash_hint_timer.stop()
        if bool(on):
            self.set_hint_rotation_paused(True)
            self._hint_context.setText("临时缩放 · 重算 / 查看全部将回到设定范围")
            return
        self.set_hint_rotation_paused(False)
        self._set_context_hint(reset=True)

    def _advance_context_hint(self):
        if self._hint_rotation_paused:
            return
        candidates = self._rotation_candidates()
        if not candidates:
            self._set_context_hint()
            return
        if len(candidates) <= 1:
            # Single hint: keep it shown and re-arm so a state change is still
            # picked up on the next tick.
            self._context_hint_signature = tuple(h.id for h in candidates)
            self._context_hint_index = 0
            self._hint_context.setText(candidates[0].text)
            self._arm_rotation_timer(candidates[0])
            return
        self._context_hint_index = (self._context_hint_index + 1) % len(candidates)
        self._context_hint_signature = tuple(hint.id for hint in candidates)
        self._set_context_hint()

    def set_hint_rotation_paused(self, paused):
        paused = bool(paused)
        was_paused = self._hint_rotation_paused
        self._hint_rotation_paused = paused
        if paused:
            # Freeze the footer while the user reads / drags so it does not jump.
            self._hint_rotation_timer.stop()
        elif was_paused:
            # Resume: re-arm against the currently shown hint's dwell.
            candidates = self._rotation_candidates()
            if candidates:
                index = self._context_hint_index % len(candidates)
                self._arm_rotation_timer(candidates[index])

    def mark_context_hint_used(self, hint_id):
        self._recent_context_hint_ids.add(hint_id)
        self._refresh_bottom_hint()

    def set_hint_settings(self, settings):
        self._hint_settings = settings
        # New store → re-resolve the rotation start from it on next use.
        self._rotation_start = None
        self._refresh_bottom_hint()

    def mark_discovered(self, hint_id):
        hints.mark_discovered(self._hint_settings, hint_id)
        self._refresh_bottom_hint()

    def _wire_discovery_signal(self, canvas, signal_name, echo_id):
        """Connect a canvas hidden-gesture signal to discovery + flash, if the
        canvas exposes it. Bound QObject methods are used instead of lambdas so
        Qt disconnects them when the card is destroyed."""
        signal = getattr(canvas, signal_name, None)
        if signal is None:
            return
        slot = {
            'slice_picked': self._on_slice_picked_discovered,
            'divider_adjusted': self._on_divider_adjusted_discovered,
            'levels_changed': self._on_levels_changed_discovered,
            'time_source_selected': self._on_time_source_selected_discovered,
        }.get(signal_name)
        if slot is not None:
            signal.connect(slot)

    def _on_slice_picked_discovered(self):
        self._discover_gesture('spectrogram.slice_pick')

    def _on_divider_adjusted_discovered(self):
        self._discover_gesture('spectrogram.divider')

    def _on_levels_changed_discovered(self, *_):
        self._discover_gesture('spectrogram.colorbar')

    def _on_time_source_selected_discovered(self, *_):
        self._discover_gesture('fft.preview_source')

    def _on_slice_hint_requested(self, text):
        self.flash_hint(text)

    def _restore_rotating_hint(self):
        self._set_context_hint(reset=True)

    def _on_overlay_y_needs_selection(self):
        self.flash_hint("先选中一个通道，再用 Shift+滚轮缩放纵向")

    def _discover_gesture(self, echo_id):
        """Record a first-time gesture: persist its discovery id (so the
        matching rotating tip retires across sessions) and flash a one-shot
        confirmation in the footer."""
        already = echo_id in hints.load_discovered(self._hint_settings)
        self.mark_discovered(echo_id)
        if not already:
            tip = hints.flash_tip(echo_id)
            if tip:
                self.flash_hint(tip)

    def _refresh_hint(self, *_):
        key = self._current_mode_key()
        _apply_mdi_icons(self.toolbar, active_key=key)
        self._refresh_bottom_hint()


class TimeChartCard(_ChartCard):
    """Time-domain chart card: inherits base nav toolbar, appends
    segmented controls for plot mode (Subplot/Overlay) and cursor mode
    (Off/Single/Dual)."""

    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent, chart_mode='time')
        if self.toolbar.layout() is not None:
            self.toolbar.layout().setSpacing(4)
        zoom_act = _find_action(self.toolbar, 'zoom')
        self._install_compact_annotation_control_after(zoom_act)
        annotation_act = self._toolbar_action_for_widget(self._annotation_btn)
        self._install_compact_clear_annotation_control_after(annotation_act)
        # Right-align time-only controls with the same spacer pattern used by
        # annotation controls on analysis cards.
        loc_action = getattr(self, '_loc_action', None)
        self._time_separators = []
        self._time_controls_spacer = QWidget(self.toolbar)
        self._time_controls_spacer.setObjectName("chartTimeControlsSpacer")
        self._time_controls_spacer.setAttribute(Qt.WA_StyledBackground, True)
        self._time_controls_spacer.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self._insert_right_toolbar_widget(loc_action, self._time_controls_spacer)

        sep = _vline()
        self._time_separators.append(sep)
        self._insert_right_toolbar_widget(loc_action, sep)

        self.btn_subplot = QPushButton("分屏", self.toolbar)
        self.btn_overlay = QPushButton("叠加", self.toolbar)
        for b in (self.btn_subplot, self.btn_overlay):
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self._insert_right_toolbar_widget(loc_action, b)
        self._plot_mode = 'subplot'
        self.btn_subplot.setChecked(True)
        self.btn_subplot.clicked.connect(lambda: self.set_plot_mode('subplot'))
        self.btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))

        sep = _vline()
        self._time_separators.append(sep)
        self._insert_right_toolbar_widget(loc_action, sep)

        self._cursor_buttons = {}
        for label, key in [('游标关', 'off'), ('单游标', 'single'), ('双游标', 'dual')]:
            b = QPushButton(label, self.toolbar)
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self._insert_right_toolbar_widget(loc_action, b)
            self._cursor_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
        self._cursor_mode = 'off'
        self._cursor_buttons['off'].setChecked(True)

        # Overlay-selection hook: when a single curve is selected in overlay
        # mode, force the nav toolbar OUT of pan/zoom so a blank-area click can
        # clear the selection without being eaten by a pan
        # press. Deselect intentionally does NOT restore the previous mode —
        # the user re-engages pan via Ctrl+G if they want it back.
        if hasattr(self.canvas, 'overlay_channel_selected'):
            self.canvas.overlay_channel_selected.connect(
                self._on_overlay_channel_selected
            )

        self._time_button_labels = [
            (self.btn_subplot, '分屏', '分'),
            (self.btn_overlay, '叠加', '叠'),
            (self._cursor_buttons['off'], '游标关', '关'),
            (self._cursor_buttons['single'], '单游标', '单'),
            (self._cursor_buttons['dual'], '双游标', '双'),
        ]
        # Tooltips are populated by _install_button_shortcut below so they
        # carry the "(Ctrl+N)" suffix; no plain-text setToolTip needed here.
        self._time_toolbar_compact = None

        # Card-wide Ctrl+1..5 shortcuts for the segmented controls.
        self._time_button_shortcuts = []
        button_by_key = {
            'btn_subplot':   self.btn_subplot,
            'btn_overlay':   self.btn_overlay,
            'cursor_off':    self._cursor_buttons['off'],
            'cursor_single': self._cursor_buttons['single'],
            'cursor_dual':   self._cursor_buttons['dual'],
        }
        from ._helpers import _TIME_CARD_SHORTCUTS
        for key, label, shortcut in _TIME_CARD_SHORTCUTS:
            btn = button_by_key.get(key)
            if btn is None:
                continue
            self._time_button_shortcuts.append(
                _install_button_shortcut(self, btn, label, shortcut, key)
            )
        self._time_annotation_shortcut = _install_button_shortcut(
            self,
            self._annotation_btn,
            "标注：左键添加，右键删除最近一处",
            "Ctrl+M",
            "annotation",
        )
        self.view_tabbar = None
        self._sync_responsive_toolbar()

    def _sync_responsive_toolbar(self):
        super()._sync_responsive_toolbar()
        labels = getattr(self, '_time_button_labels', None)
        if not labels:
            return
        self._time_toolbar_compact = False
        for button, full, _short in labels:
            button.setText(full)
            text_width = button.fontMetrics().horizontalAdvance(full)
            button_width = max(52, text_width + 24)
            button.setFixedWidth(button_width)
        for sep in self._time_separators:
            sep.setVisible(True)
        self.toolbar.updateGeometry()

    # ----- plot mode -----
    def plot_mode(self):
        return self._plot_mode

    def set_plot_mode(self, mode):
        if mode not in ('subplot', 'overlay') or mode == self._plot_mode:
            return
        self._plot_mode = mode
        self.btn_subplot.setChecked(mode == 'subplot')
        self.btn_overlay.setChecked(mode == 'overlay')
        self._refresh_bottom_hint()
        self.plot_mode_changed.emit(mode)

    # ----- cursor mode -----
    def cursor_mode(self):
        return self._cursor_mode

    def set_cursor_mode(self, mode):
        if mode not in ('off', 'single', 'dual') or mode == self._cursor_mode:
            return
        self._cursor_mode = mode
        for k, b in self._cursor_buttons.items():
            b.setChecked(k == mode)
        # Cursor mode is part of HintState, so refresh the bottom context
        # label whenever it flips.
        self._refresh_bottom_hint()
        self.cursor_mode_changed.emit(mode)

    def _hint_state(self):
        return hints.HintState(
            mode='time',
            plot_mode=getattr(self, '_plot_mode', 'subplot'),
            cursor_mode=getattr(self, '_cursor_mode', 'off'),
            mouse_mode=self._current_mode_key(),
            chart_kind='time',
            annotation_on=self.annotation_enabled(),
            discovered=hints.load_discovered(self._hint_settings),
            recently_used=frozenset(self._recent_context_hint_ids),
            **self._nudge_signals(),
        )

    # ----- overlay-selection nav handoff -----
    def _on_overlay_channel_selected(self, name):
        """Switch the nav toolbar to idle while a curve is selected.

        Pan / zoom would otherwise eat the next blank-area click and prevent
        deselect. We do NOT restore the previous mode on deselect — the user
        can re-engage pan (Ctrl+G) or zoom (Ctrl+B) explicitly. Called with
        ``name=None`` on deselect; that path is a no-op.
        """
        if not name:
            return
        mode = self._current_mode_key()
        if mode == 'pan':
            self.toolbar.pan()
        elif mode == 'zoom':
            self.toolbar.zoom()
        self._refresh_hint()
