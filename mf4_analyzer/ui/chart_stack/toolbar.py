"""PgNavigationToolbar, ToolbarScrollHost, and _TickDensityPopover."""
from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QAction, QButtonGroup, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from ..chart_defaults import DEFAULT_CHART_TICK_DENSITY
from ._helpers import _grab_pixmap_hidpi


class _TickDensityPopover(QFrame):
    density_changed = pyqtSignal(int, int)

    _DEFAULT = DEFAULT_CHART_TICK_DENSITY
    _PRESETS = {
        "疏": (6, 5),
        "标准": (10, 10),
        "密": DEFAULT_CHART_TICK_DENSITY,
    }

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setObjectName("TickDensityPopover")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedWidth(240)
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._surface = QFrame(self)
        self._surface.setObjectName("TickDensitySurface")
        lay = QVBoxLayout(self._surface)
        lay.setContentsMargins(11, 11, 11, 11)
        lay.setSpacing(9)
        root.addWidget(self._surface)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("刻度密度", self._surface)
        title.setObjectName("tickDensityTitle")
        scope = QLabel("全局", self._surface)
        scope.setObjectName("tickDensityScope")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(scope)
        lay.addLayout(title_row)

        self._preset_host = QFrame(self._surface)
        self._preset_host.setObjectName("tickDensityPresetHost")
        preset_lay = QHBoxLayout(self._preset_host)
        preset_lay.setContentsMargins(0, 0, 0, 0)
        preset_lay.setSpacing(6)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self._preset_buttons = {}
        for label, pair in self._PRESETS.items():
            btn = QPushButton(label, self._preset_host)
            btn.setObjectName("tickDensityPresetButton")
            btn.setCheckable(True)
            btn.setProperty("role", "tick-density-preset")
            btn.clicked.connect(
                lambda _checked=False, p=pair: self.set_density(*p, emit=True)
            )
            self._preset_group.addButton(btn)
            self._preset_buttons[label] = btn
            preset_lay.addWidget(btn)
        lay.addWidget(self._preset_host)

        default_x, default_y = self._DEFAULT
        self._x_row, self._slider_x, self._spin_x = self._build_axis_row(
            "X", 3, 30, default_x
        )
        self._y_row, self._slider_y, self._spin_y = self._build_axis_row(
            "Y", 3, 20, default_y
        )
        lay.addWidget(self._x_row)
        lay.addWidget(self._y_row)

        self._reset_btn = QPushButton(
            f"恢复默认 {default_x} / {default_y}", self._surface
        )
        self._reset_btn.setObjectName("tickDensityResetButton")
        self._reset_btn.clicked.connect(
            lambda: self.set_density(default_x, default_y, emit=True)
        )
        lay.addWidget(self._reset_btn)

        self._slider_x.valueChanged.connect(
            lambda value: self.set_density(value, self._spin_y.value(), emit=True)
        )
        self._slider_y.valueChanged.connect(
            lambda value: self.set_density(self._spin_x.value(), value, emit=True)
        )
        self._spin_x.valueChanged.connect(
            lambda value: self.set_density(value, self._spin_y.value(), emit=True)
        )
        self._spin_y.valueChanged.connect(
            lambda value: self.set_density(self._spin_x.value(), value, emit=True)
        )
        # Seed sliders + activate the matching preset (「密」).
        self.set_density(default_x, default_y, emit=False)

    def _build_axis_row(self, label, minimum, maximum, value):
        row = QFrame(self._surface)
        row.setObjectName("tickDensityAxisRow")
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(0)
        axis_label = QLabel(label, row)
        axis_label.setObjectName("tickDensityAxisLabel")
        slider = QSlider(Qt.Horizontal, row)
        slider.setObjectName("tickDensitySlider")
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        spin = QSpinBox(row)
        spin.setObjectName("tickDensitySpin")
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedWidth(38)
        grid.addWidget(axis_label, 0, 0)
        grid.addWidget(slider, 0, 1)
        grid.addWidget(spin, 0, 2)
        return row, slider, spin

    def density(self):
        return self._spin_x.value(), self._spin_y.value()

    def set_density(self, x, y, *, emit=False):
        if self._updating:
            return
        x = max(3, min(30, int(x)))
        y = max(3, min(20, int(y)))
        self._updating = True
        widgets = (
            self._slider_x, self._spin_x,
            self._slider_y, self._spin_y,
        )
        old = [w.blockSignals(True) for w in widgets]
        try:
            self._slider_x.setValue(x)
            self._spin_x.setValue(x)
            self._slider_y.setValue(y)
            self._spin_y.setValue(y)
        finally:
            for widget, blocked in zip(widgets, old):
                widget.blockSignals(blocked)
            self._updating = False
        self._sync_preset_checks(x, y)
        if emit:
            self.density_changed.emit(x, y)

    def _sync_preset_checks(self, x, y):
        self._preset_group.setExclusive(False)
        try:
            for label, btn in self._preset_buttons.items():
                btn.setChecked(self._PRESETS[label] == (x, y))
                # Programmatic setChecked can leave QSS :checked stale until
                # the next hover; force a polish so 「密」looks activated on open.
                style = btn.style()
                if style is not None:
                    style.unpolish(btn)
                    style.polish(btn)
                btn.update()
        finally:
            self._preset_group.setExclusive(True)


class ToolbarScrollHost(QScrollArea):
    """Clip a chart QToolBar to the viewport and pan-scroll when it overflows.

    The inner bar always lays out at its natural ``sizeHint()`` (or the
    viewport width, whichever is larger), so Qt never creates the QToolBar
    extension/overflow button. Edge buttons and a discrete mouse wheel keep
    every action reachable when no empty drag chrome remains. Empty-chrome
    dragging and horizontal wheel/trackpad deltas remain supported.
    """

    PAN_START_PX = 8
    EDGE_BUTTON_WIDTH = 28
    EDGE_SCROLL_STEP_PX = 128

    def __init__(self, toolbar, parent=None):
        super().__init__(parent)
        self.setObjectName("chartToolbarScrollHost")
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QScrollArea#chartToolbarScrollHost { background: transparent; }"
        )
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.setWidget(toolbar)
        self._press_global = None
        self._press_offset = 0
        self._panning = False
        self._hint_left = self._make_edge_button(
            "‹", "向左查看更多工具", "向左滚动工具栏"
        )
        self._hint_right = self._make_edge_button(
            "›", "向右查看更多工具", "向右滚动工具栏"
        )
        self._hint_left.clicked.connect(self._scroll_left)
        self._hint_right.clicked.connect(self._scroll_right)
        self._install_filters(toolbar)
        self.viewport().installEventFilter(self)
        self.installEventFilter(self)
        self._hint_left.installEventFilter(self)
        self._hint_right.installEventFilter(self)
        self.horizontalScrollBar().valueChanged.connect(self._sync_edge_hints)

    def sizeHint(self):
        bar = self.widget()
        height = 32
        if bar is not None:
            height = max(bar.sizeHint().height(), height)
        return QSize(0, height)

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_inner_toolbar()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_inner_toolbar()

    def wheelEvent(self, event):
        if self._apply_horizontal_wheel(event):
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event):
        if self._handle_pan_move(event.globalPos()):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._handle_pan_release():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._install_filters(child)
            return False
        if etype == QEvent.LayoutRequest and obj is self.widget():
            self.fit_inner_toolbar()
            return False
        if etype == QEvent.Wheel:
            if self._is_descended_from_toolbar(obj) or obj in (
                self,
                self.viewport(),
                self.widget(),
                self._hint_left,
                self._hint_right,
            ):
                if self._apply_horizontal_wheel(event):
                    return True
            return False
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._is_chrome(obj):
                self._arm_pan(event.globalPos())
            return False
        if etype == QEvent.MouseMove and self._press_global is not None:
            if self._handle_pan_move(event.globalPos()):
                return True
            return False
        if etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            return self._handle_pan_release()
        return super().eventFilter(obj, event)

    def fit_inner_toolbar(self):
        """Keep the inner bar at natural width so QToolBar never overflows."""
        bar = self.widget()
        if bar is None:
            return
        hint = bar.sizeHint()
        edge_width = (
            self.EDGE_BUTTON_WIDTH
            if hint.width() > max(0, self.contentsRect().width())
            else 0
        )
        margins = self.viewportMargins()
        if margins.left() != edge_width or margins.right() != edge_width:
            self.setViewportMargins(edge_width, 0, edge_width, 0)
        viewport_w = max(0, self.viewport().width())
        viewport_h = max(0, self.viewport().height())
        target_w = max(hint.width(), viewport_w)
        target_h = max(hint.height(), viewport_h, 1)
        if bar.minimumWidth() != hint.width():
            bar.setMinimumWidth(hint.width())
        if bar.size() != QSize(target_w, target_h):
            bar.resize(target_w, target_h)
        self._sync_edge_hints()

    def ensure_widget_visible(self, widget, xmargin=12):
        if widget is None:
            return
        self.fit_inner_toolbar()
        bar = self.widget()
        if bar is None:
            return
        scroll = self.horizontalScrollBar()
        widget_left = widget.mapTo(bar, QPoint(0, 0)).x()
        wanted_left = max(0, widget_left - xmargin)
        wanted_right = widget_left + widget.width() + xmargin
        visible_left = scroll.value()
        visible_right = visible_left + self.viewport().width()
        if wanted_left < visible_left:
            scroll.setValue(wanted_left)
        elif wanted_right > visible_right:
            scroll.setValue(wanted_right - self.viewport().width())
        self._sync_edge_hints()

    def _install_filters(self, widget):
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def _is_descended_from_toolbar(self, widget):
        bar = self.widget()
        current = widget
        while current is not None:
            if current is bar:
                return True
            current = current.parentWidget()
        return False

    def _is_chrome(self, widget):
        if widget is None or isinstance(widget, QAbstractButton):
            return False
        current = widget
        while current is not None:
            if isinstance(current, QAbstractButton):
                return False
            if current is self.widget() or current is self or current is self.viewport():
                return True
            current = current.parentWidget()
        return False

    def _arm_pan(self, global_pos):
        self._press_global = QPoint(global_pos)
        self._press_offset = self.horizontalScrollBar().value()
        self._panning = False

    def _handle_pan_move(self, global_pos):
        if self._press_global is None:
            return False
        delta_x = global_pos.x() - self._press_global.x()
        if not self._panning:
            if abs(delta_x) < self.PAN_START_PX:
                return False
            self._panning = True
        self.horizontalScrollBar().setValue(self._press_offset - delta_x)
        self._sync_edge_hints()
        return True

    def _handle_pan_release(self):
        was_panning = self._panning
        self._panning = False
        self._press_global = None
        return was_panning

    def _apply_horizontal_wheel(self, event):
        pixel = event.pixelDelta()
        dx = pixel.x()
        if dx == 0:
            angle = event.angleDelta()
            dx = angle.x()
            # A conventional Windows mouse wheel reports only angleDelta().y().
            # Reuse it only for discrete wheel events; a touchpad's vertical
            # pixel gesture remains vertical and is not unexpectedly hijacked.
            if dx == 0 and pixel.isNull():
                dx = angle.y()
        if dx == 0:
            return False
        bar = self.horizontalScrollBar()
        before = bar.value()
        bar.setValue(bar.value() - dx)
        self._sync_edge_hints()
        return bar.value() != before

    def _make_edge_button(self, text, accessible_name, tooltip):
        button = QToolButton(self)
        button.setObjectName("chartToolbarEdgeButton")
        button.setText(text)
        button.setAccessibleName(accessible_name)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        # The scroll host itself is mouse-only; keeping these overlays out of
        # the focus chain also prevents disabling the end arrow from making
        # QScrollArea auto-scroll to an unrelated focused toolbar action.
        button.setFocusPolicy(Qt.NoFocus)
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(320)
        button.setAutoRepeatInterval(90)
        button.setFixedWidth(self.EDGE_BUTTON_WIDTH)
        button.hide()
        return button

    def _scroll_left(self, _checked=False):
        self._scroll_by(-self.EDGE_SCROLL_STEP_PX)

    def _scroll_right(self, _checked=False):
        self._scroll_by(self.EDGE_SCROLL_STEP_PX)

    def _scroll_by(self, delta):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() + int(delta))
        self._sync_edge_hints()

    def _sync_edge_hints(self, *_args):
        bar = self.horizontalScrollBar()
        rect = self.contentsRect()
        height = max(1, rect.height())
        edge_width = self.EDGE_BUTTON_WIDTH
        self._hint_left.setGeometry(rect.left(), rect.top(), edge_width, height)
        self._hint_right.setGeometry(
            max(rect.left(), rect.right() - edge_width + 1),
            rect.top(),
            edge_width,
            height,
        )
        overflow = bar.maximum() > 0
        self._hint_left.setVisible(overflow)
        self._hint_right.setVisible(overflow)
        self._hint_left.setEnabled(overflow and bar.value() > 0)
        self._hint_right.setEnabled(overflow and bar.value() < bar.maximum())
        if overflow:
            self._hint_left.raise_()
            self._hint_right.raise_()


class PgNavigationToolbar(QToolBar):
    """Navigation toolbar for pyqtgraph chart canvases.

    Goals (Task 7 production switch):

    1. Same six action keys (``home``/``back``/``forward``/``pan``/``zoom``/``save``)
       in the same left-to-right order so ``_find_action`` /
       ``_install_nav_shortcuts`` / ``_apply_mdi_icons`` /
       ``apply_chinese_toolbar_labels`` keep working unchanged.
    2. English action text on construction so ``apply_chinese_toolbar_labels``
       still matches by lowercased text (it calls ``act.setData(key)`` on each
       match, after which all downstream lookups use ``act.data()``).
    3. ``mode`` string attribute that mirrors the established toolbar mode
       semantics: empty string when idle, ``'pan'`` or ``'zoom'`` when the
       respective tool is active. Mutually exclusive — selecting one drops
       the other. Tests that read ``str(toolbar.mode).lower()`` keep passing.
    4. ``pan()`` / ``zoom()`` methods that toggle the tool just like
       the previous chart toolbar did (no-op repeat call deactivates).
    5. ``locLabel`` exists only as a compatibility attribute; _ChartCard
       removes toolbar coordinate readouts from the visible action row.
    6. ``home()`` triggers an autoRange on the primary view box; ``back()`` /
       ``forward()`` pop/push view history (xlim+ylim tuples per axis);
       ``save()`` opens a file dialog and writes a grabbed pixmap.

    Not goals:

    - Re-implementing the old renderer's full view-stack semantics (history of all
      axes, blit ghosts, etc). The minimum that keeps the contract tests AND
      the renderer-swap path functional is enough.
    """

    # Match the legacy mode string semantics: '' when idle.
    _MODE_NONE = ''
    _MODE_PAN = 'pan'
    _MODE_ZOOM = 'zoom'

    # Design D: emitted whenever the pan/box-select mouse mode changes via
    # ANY entry (toolbar button or the right-click 鼠标操作 submenu). _ChartCard
    # listens so the hint label + MDI icon active-state refresh, and the
    # right-click menu reads current_mouse_mode() so its checkmark matches.
    mouse_mode_changed = pyqtSignal(str)
    home_triggered = pyqtSignal()

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        # The retired toolbar exposed `.mode` as a str-coercible empty value.
        # We mirror with a plain string; tests do
        # `str(toolbar.mode).lower()` so a bare str works without surprises.
        self.mode = self._MODE_NONE
        # Split-mode action routing: when set to a callable, a user toolbar-
        # button CLICK is forwarded to the toolbar it returns (the focused
        # pane's own canvas-bound toolbar) instead of running on this one.
        # Internal method calls (_ChartCard defaulting to pan, overlay-select
        # handoff) invoke the methods directly and bypass this, so only the
        # six nav buttons' user clicks forward. None ⇒ no forwarding.
        self._action_delegate_provider = None
        # Split-mode peer routing: pan/zoom/back/forward should apply to this
        # toolbar and any visible peer pane toolbar without changing focus.
        self._peer_toolbars_provider = None
        self._save_pixmap_provider = None
        # View history: a single stack
        # of view snapshots plus a pointer into it. ``back()`` decrements the
        # pointer, ``forward()`` increments it, and a brand-new gesture
        # truncates everything past the pointer before appending. Each entry
        # is keyed by CHANNEL NAME (not the live axis handle) so a snapshot
        # survives a plot_channels rebuild that swaps the ViewBox objects.
        # Entry shape: {channel_name: (xlim, ylim)}.
        self._view_stack: list = []
        self._view_pointer: int = -1
        self._view_stack_max = 32
        # Guard set True while restoring (back/forward/home) so the range-
        # change signal those restores fire does NOT re-push a history entry.
        self._restoring = False
        # Debounce so one continuous drag coalesces to a single history push.
        # sigRangeChangedManually fires many times during a drag; we (re)start
        # this timer on each and commit once it settles.
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(180)
        self._history_timer.timeout.connect(self._commit_pending_view)
        # Live (ViewBox, handler) connections to sigRangeChangedManually, so
        # we can disconnect before re-binding to fresh ViewBoxes on rebuild
        # (pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle).
        self._range_conns: list = []
        # Compatibility only. _ChartCard hides/removes toolbar coordinates;
        # pyqtgraph hover details are surfaced elsewhere.
        self.locLabel = QLabel("", self)

        # Build the six actions in the established order so _action_keys()
        # and the ordering-pinning contract test
        # (test_time_chart_card_toolbar_action_keys_ordering_pan_before_zoom)
        # see the same sequence as before the renderer swap.
        self._actions_by_key = {}
        for key, label in (
            ('home', 'Home'),
            ('back', 'Back'),
            ('forward', 'Forward'),
            ('pan', 'Pan'),
            ('zoom', 'Zoom'),
            ('save', 'Save'),
        ):
            act = QAction(label, self)
            # The Chinese i18n pass matches by lowercased text BEFORE setting
            # data, so leaving english text here is the right move.
            self.addAction(act)
            self._actions_by_key[key] = act
        # Wire each action to its handler. We connect by closure so
        # apply_chinese_toolbar_labels can re-tooltip the QAction without
        # disturbing the slot.
        # Route through _click_* wrappers (not the methods directly) so a
        # USER click can be forwarded to the focused pane's toolbar in split
        # mode, while internal method calls stay on this toolbar.
        self._actions_by_key['home'].triggered.connect(self._click_home)
        self._actions_by_key['back'].triggered.connect(self._click_back)
        self._actions_by_key['forward'].triggered.connect(self._click_forward)
        self._actions_by_key['pan'].triggered.connect(self._click_pan)
        self._actions_by_key['zoom'].triggered.connect(self._click_zoom)
        self._actions_by_key['save'].triggered.connect(self._click_save)
        # Do not add locLabel to the toolbar. The attribute is retained for
        # compatibility with old callers, but coordinates are no longer
        # rendered in the top action row.

    # ----- internal helpers ------------------------------------------------
    def _primary_view_box(self):
        """Return the pyqtgraph ``ViewBox`` driving the primary axis (the one
        whose xlim drives the viewport-aware refresh). Falls back to the
        first ViewBox in ``axes_list`` if ``_primary_xaxis_ax`` is unset.
        """
        canvas = self._canvas
        primary = getattr(canvas, '_primary_xaxis_ax', None)
        if primary is None:
            axes_list = getattr(canvas, 'axes_list', None) or []
            if not axes_list:
                return None
            primary = axes_list[0]
        return getattr(primary, 'view_box', None)

    def _view_boxes(self):
        boxes = []
        for ax in getattr(self._canvas, 'axes_list', None) or []:
            vb = getattr(ax, 'view_box', None)
            if vb is not None and vb not in boxes:
                boxes.append(vb)
        # Bug 3 (overlay): the aux ViewBoxes in axes_list are all
        # setMouseEnabled(False); the ACTUAL mouse-capture surface in
        # overlay mode is the X-master ViewBox, which is not in axes_list.
        # Include it so Rect/Pan mode reaches the surface the user drags on.
        if getattr(self._canvas, '_overlay_mode', False):
            master = getattr(self._canvas, '_x_master_handle', None)
            master_vb = getattr(master, 'view_box', None) if master else None
            if master_vb is not None and master_vb not in boxes:
                boxes.append(master_vb)
        if not boxes:
            primary = self._primary_view_box()
            if primary is not None:
                boxes.append(primary)
        return boxes

    def _set_all_mouse_modes(self, mode):
        for vb in self._view_boxes():
            try:
                vb.setMouseMode(mode)
            except Exception:
                continue

    def apply_current_mouse_mode(self):
        """Re-apply the toolbar's current mouse mode to the live ViewBoxes.

        Bug 3: ``plot_channels`` builds NEW ViewBoxes (default PanMode), so
        after any replot/mode-switch the toolbar still reads ``zoom`` while
        the fresh ViewBoxes are PanMode → box-zoom silently dead. The canvas
        invokes this (registered via ``register_replot_callback``) at the end
        of every rebuild. Idempotent and guarded.
        """
        import pyqtgraph as pg

        target = pg.ViewBox.RectMode if self.mode == self._MODE_ZOOM else pg.ViewBox.PanMode
        self._set_all_mouse_modes(target)

    def _snapshot_view(self):
        """Snapshot the current view keyed by CHANNEL NAME, not by the live
        axis handle, so the entry survives a ``plot_channels`` rebuild that
        swaps the ViewBox objects for fresh ones.

        Returns ``{channel_name: (xlim, ylim)}``. On restore we resolve the
        channel back to its (possibly rebuilt) axis handle via the canvas's
        ``_channel_lines`` map.
        """
        canvas = self._canvas
        snap = {}
        channel_lines = getattr(canvas, '_channel_lines', None) or {}
        for name, pair in channel_lines.items():
            try:
                axis_handle = pair[0]
            except Exception:
                continue
            if axis_handle is None:
                continue
            try:
                snap[name] = (axis_handle.get_xlim(), axis_handle.get_ylim())
            except Exception:
                continue
        return snap

    def _restore_view(self, snap):
        """Apply a name-keyed snapshot, resolving each channel to its CURRENT
        axis handle via ``_channel_lines`` (the handle may be a fresh object
        after a rebuild). Wrapped in the ``_restoring`` guard by the caller so
        the resulting range-change signals do not re-push history."""
        if not snap:
            return
        canvas = self._canvas
        channel_lines = getattr(canvas, '_channel_lines', None) or {}
        for name, (xlim, ylim) in snap.items():
            pair = channel_lines.get(name)
            if not pair:
                continue
            axis_handle = pair[0]
            if axis_handle is None:
                continue
            try:
                axis_handle.set_xlim(*xlim)
                axis_handle.set_ylim(*ylim)
            except Exception:
                continue

    # ----- view history ----------------------------------------------------
    def rebind_history_capture(self):
        """Re-bind the manual-range capture hook to the live ViewBoxes.

        ``plot_channels`` builds NEW ViewBoxes each rebuild; the old
        ``sigRangeChangedManually`` connections point at destroyed objects.
        Disconnect them first, then reconnect to the current view boxes
        (cite pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle). Also
        seeds a baseline history entry the first time a chart is built so
        ``back()`` has a return target before any gesture.
        """
        self._disconnect_range_listeners()
        for vb in self._view_boxes():
            sig = getattr(vb, 'sigRangeChangedManually', None)
            if sig is None:
                continue
            try:
                sig.connect(self._on_manual_range_changed)
                self._range_conns.append((vb, self._on_manual_range_changed))
            except Exception:
                continue
        # Seed a baseline once, after the very first build, so back() works
        # even before the user performs any gesture.
        if not self._view_stack:
            snap = self._snapshot_view()
            if snap:
                self._view_stack = [snap]
                self._view_pointer = 0

    def _disconnect_range_listeners(self):
        for vb, handler in self._range_conns:
            try:
                vb.sigRangeChangedManually.disconnect(handler)
            except Exception:
                pass
        self._range_conns = []

    def _on_manual_range_changed(self, *_args):
        """A user-driven range change (pan/zoom drag, wheel) fired. Restart
        the debounce so a continuous gesture coalesces to one history push.
        Ignored while restoring a history entry."""
        if self._restoring:
            return
        self._history_timer.start()

    def _commit_pending_view(self):
        """Append the current view as a new history entry. A new gesture
        truncates any forward history past the pointer (matplotlib model)."""
        if self._restoring:
            return
        snap = self._snapshot_view()
        if not snap:
            return
        # Truncate forward history, then append.
        if self._view_pointer < len(self._view_stack) - 1:
            del self._view_stack[self._view_pointer + 1:]
        self._view_stack.append(snap)
        # Cap memory: drop the oldest frame, shifting the pointer.
        if len(self._view_stack) > self._view_stack_max:
            overflow = len(self._view_stack) - self._view_stack_max
            del self._view_stack[:overflow]
        self._view_pointer = len(self._view_stack) - 1

    def _channel_data_x_union(self):
        canvas = self._canvas
        bounds = []
        for row in getattr(canvas, 'channel_data', {}).values():
            try:
                t_values = row[0]
            except Exception:
                continue
            try:
                import numpy as np

                arr = np.asarray(t_values, dtype=float)
                finite = arr[np.isfinite(arr)]
                if finite.size:
                    bounds.append((float(finite.min()), float(finite.max())))
            except Exception:
                continue
        if not bounds:
            return None
        return min(lo for lo, _hi in bounds), max(hi for _lo, hi in bounds)

    # ----- public surface --------------------------------------------------
    def home(self, *_args):
        """Autoscale back to data extents using a deterministic shared-X policy.

        Prefer the canvas-level reset helper when present. Older canvases do
        not expose that helper, so the fallback keeps per-axis Y autoscale but
        pins every axis X range to the union of live raw channel time ranges.
        """
        canvas = self._canvas
        # Home is a deliberate view change → record the resulting view as a
        # new history entry after the home reset. Guard
        # the reset itself so the range signals it fires don't double-push.
        self._restoring = True
        try:
            sync = getattr(canvas, "reset_view_to_data_extents", None)
            if callable(sync):
                sync()
            else:
                x_union = self._channel_data_x_union()
                for ax in getattr(canvas, 'axes_list', None) or []:
                    vb = getattr(ax, 'view_box', None)
                    if vb is None or not hasattr(vb, 'autoRange'):
                        continue
                    try:
                        vb.autoRange()
                    except Exception:
                        continue
                if x_union is not None:
                    for ax in getattr(canvas, 'axes_list', None) or []:
                        try:
                            ax.set_xlim(*x_union)
                        except Exception:
                            continue
        finally:
            self._restoring = False
        self._commit_pending_view()

    def back(self, *_args):
        """Step to the previous view in the history stack."""
        if self._view_pointer <= 0:
            return
        self._view_pointer -= 1
        self._restoring = True
        try:
            self._restore_view(self._view_stack[self._view_pointer])
        finally:
            self._restoring = False

    def forward(self, *_args):
        """Step to the next view in the history stack."""
        if self._view_pointer >= len(self._view_stack) - 1:
            return
        self._view_pointer += 1
        self._restoring = True
        try:
            self._restore_view(self._view_stack[self._view_pointer])
        finally:
            self._restoring = False

    def pan(self, *_args):
        """Toggle pan mode. Idempotent within mode; mutually exclusive with
        zoom — switching to pan from zoom drops zoom first.
        """
        import pyqtgraph as pg

        if self.mode == self._MODE_PAN:
            # Second call toggles OFF.
            self.mode = self._MODE_NONE
            # pyqtgraph default ViewBox.PanMode is 3; set it explicitly so
            # toggling off leaves every subplot in a sane mouse mode.
            self._set_all_mouse_modes(pg.ViewBox.PanMode)
            self.mouse_mode_changed.emit(self.mode)
            return
        # Switching INTO pan from idle or zoom.
        self.mode = self._MODE_PAN
        self._set_all_mouse_modes(pg.ViewBox.PanMode)
        self.mouse_mode_changed.emit(self.mode)

    def zoom(self, *_args):
        """Toggle zoom (rectangle-drag) mode. Mirror semantics of pan()."""
        import pyqtgraph as pg

        if self.mode == self._MODE_ZOOM:
            self.mode = self._MODE_NONE
            self._set_all_mouse_modes(pg.ViewBox.PanMode)
            self.mouse_mode_changed.emit(self.mode)
            return
        self.mode = self._MODE_ZOOM
        self._set_all_mouse_modes(pg.ViewBox.RectMode)
        self.mouse_mode_changed.emit(self.mode)

    # ----- shared mouse-mode controller surface (design D) -----------------
    # The right-click 鼠标操作 submenu drives these DETERMINISTIC setters (not
    # the pan()/zoom() toggles) so a menu click always lands on the requested
    # mode rather than flipping it off. Both paths mutate the SAME ``self.mode``
    # + ViewBoxes and emit ``mouse_mode_changed`` → single source of truth.

    def current_mouse_mode(self):
        """Return the current mouse mode string: ``'pan'`` / ``'zoom'`` /
        ``''`` (idle). Read by the right-click menu to set its checkmark."""
        return self.mode

    def set_pan_mode(self):
        """Set pan mode unconditionally (idempotent). Used by the menu."""
        import pyqtgraph as pg

        changed = self.mode != self._MODE_PAN
        self.mode = self._MODE_PAN
        self._set_all_mouse_modes(pg.ViewBox.PanMode)
        if changed:
            self.mouse_mode_changed.emit(self.mode)

    def set_zoom_mode(self):
        """Set box-select zoom mode unconditionally (idempotent)."""
        import pyqtgraph as pg

        changed = self.mode != self._MODE_ZOOM
        self.mode = self._MODE_ZOOM
        self._set_all_mouse_modes(pg.ViewBox.RectMode)
        if changed:
            self.mouse_mode_changed.emit(self.mode)

    def _peers(self):
        provider = self._peer_toolbars_provider
        if provider is None:
            return []
        try:
            peers = provider() or []
        except Exception:
            return []
        return [toolbar for toolbar in peers if toolbar is not None and toolbar is not self]

    def set_mouse_mode(self, mode):
        """Set mouse mode on this toolbar only; callers handle peer broadcast."""
        if mode == self._MODE_ZOOM:
            self.set_zoom_mode()
        elif mode == self._MODE_PAN:
            self.set_pan_mode()
        else:
            self.mode = self._MODE_NONE
            self.apply_current_mouse_mode()
            self.mouse_mode_changed.emit(self.mode)

    def set_mouse_mode_broadcast(self, mode):
        """Set this toolbar's mouse mode once, then mirror it to peer panes."""
        if mode == self._MODE_ZOOM:
            self.set_zoom_mode()
        else:
            self.set_pan_mode()
        for toolbar in self._peers():
            toolbar.set_mouse_mode(self.mode)

    def save_figure(self, *_args):
        """Open a Save-As dialog and write the canvas grab to disk.

        Renders at a hi-DPI scale (spec §E) so the saved image is crisp;
        the canvas caps the magnification internally for speed.
        """
        canvas = self._canvas
        if not hasattr(canvas, 'grab_pixmap'):
            return
        # Use the package-namespace QFileDialog so monkeypatch on
        # "mf4_analyzer.ui.chart_stack.QFileDialog" is honoured
        # (lesson: refactor/2026-06-18-monkeypatch-anchor-survives-module-to-package).
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.chart_stack')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        path, _filter = _QFileDialog.getSaveFileName(
            self, "保存图片", "", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        )
        if not path:
            return
        pix = None
        provider = self._save_pixmap_provider
        if callable(provider):
            try:
                pix = provider()
            except Exception:
                pix = None
        if pix is None or pix.isNull():
            pix = _grab_pixmap_hidpi(canvas)
        if pix is None or pix.isNull():
            return
        ok = False
        try:
            ok = bool(pix.save(path))
        except Exception:
            ok = False
        if not ok:
            QMessageBox.warning(self, "保存失败", f"无法保存图片到：\n{path}")
            return

    # ----- split-mode action routing (forward clicks to focused pane) ------
    def _delegate(self):
        """Toolbar a user click should run on, or None to run on self.

        Returns the provider's toolbar only when it is a *different* toolbar,
        so a missing/identity provider degrades to normal (self) behaviour.
        """
        provider = self._action_delegate_provider
        if provider is None:
            return None
        try:
            target = provider()
        except Exception:
            return None
        if target is None or target is self:
            return None
        return target

    def _click_home(self, *_a):
        (self._delegate() or self).home()
        self.home_triggered.emit()

    def _click_back(self, *_a):
        self.back()
        for toolbar in self._peers():
            toolbar.back()

    def _click_forward(self, *_a):
        self.forward()
        for toolbar in self._peers():
            toolbar.forward()

    def _click_pan(self, *_a):
        self.pan()
        for toolbar in self._peers():
            toolbar.set_mouse_mode(self.mode)

    def _click_zoom(self, *_a):
        self.zoom()
        for toolbar in self._peers():
            toolbar.set_mouse_mode(self.mode)

    def _click_save(self, *_a):
        self.save_figure()
