"""PgNavigationToolbar and _TickDensityPopover."""
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QAction, QButtonGroup, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
    QSpinBox, QToolBar, QVBoxLayout,
)

from ._helpers import _grab_pixmap_hidpi


class _TickDensityPopover(QFrame):
    density_changed = pyqtSignal(int, int)

    _PRESETS = {
        "疏": (6, 5),
        "标准": (10, 10),
        "密": (20, 15),
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

        self._x_row, self._slider_x, self._spin_x = self._build_axis_row(
            "X", 3, 30, 10
        )
        self._y_row, self._slider_y, self._spin_y = self._build_axis_row(
            "Y", 3, 20, 10
        )
        lay.addWidget(self._x_row)
        lay.addWidget(self._y_row)

        self._reset_btn = QPushButton("恢复默认 10 / 10", self._surface)
        self._reset_btn.setObjectName("tickDensityResetButton")
        self._reset_btn.clicked.connect(lambda: self.set_density(10, 10, emit=True))
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
        self.set_density(10, 10, emit=False)

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
        finally:
            self._preset_group.setExclusive(True)


class PgNavigationToolbar(QToolBar):
    """Drop-in stand-in for ``matplotlib.backends.backend_qt5agg.NavigationToolbar2QT``
    when the underlying canvas is a ``TimeDomainCanvasPG`` (pyqtgraph), not a
    matplotlib ``FigureCanvas``.

    Goals (Task 7 production switch):

    1. Same six action keys (``home``/``back``/``forward``/``pan``/``zoom``/``save``)
       in the same left-to-right order so ``_find_action`` /
       ``_install_nav_shortcuts`` / ``_apply_mdi_icons`` /
       ``apply_chinese_toolbar_labels`` keep working unchanged.
    2. English action text on construction so ``apply_chinese_toolbar_labels``
       still matches by lowercased text (it calls ``act.setData(key)`` on each
       match, after which all downstream lookups use ``act.data()``).
    3. ``mode`` string attribute that mirrors matplotlib's ``toolbar.mode``
       semantics: empty string when idle, ``'pan'`` or ``'zoom'`` when the
       respective tool is active. Mutually exclusive — selecting one drops
       the other. Tests that read ``str(toolbar.mode).lower()`` keep passing.
    4. ``pan()`` / ``zoom()`` methods that toggle the tool just like
       matplotlib's NavigationToolbar2QT does (no-op repeat call deactivates).
    5. ``locLabel`` exists only as a compatibility attribute; _ChartCard
       removes toolbar coordinate readouts from the visible action row.
    6. ``home()`` triggers an autoRange on the primary view box; ``back()`` /
       ``forward()`` pop/push view history (xlim+ylim tuples per axis);
       ``save()`` opens a file dialog and writes a grabbed pixmap.

    Not goals:

    - Re-implementing matplotlib's full view-stack semantics (history of all
      axes, blit ghosts, etc). The minimum that keeps the contract tests AND
      the renderer-swap path functional is enough.
    """

    # Match matplotlib's _Mode enum string semantics: '' when idle.
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
        # NavigationToolbar2QT exposes `.mode` as `_Mode.NONE` (str-coercible
        # to ''). We mirror with a plain string; tests do
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
        # View history (matplotlib NavigationToolbar2 model): a single stack
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

        # Build the six actions in matplotlib's order so _action_keys()
        # and the ordering-pinning contract test
        # (test_time_chart_card_toolbar_action_keys_ordering_pan_before_zoom)
        # see the same sequence as the matplotlib toolbar produced.
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

    # ----- view history (matplotlib NavigationToolbar2 parity) -------------
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

    # ----- public surface (matplotlib NavigationToolbar2QT parity) --------
    def home(self, *_args):
        """Autoscale back to data extents using a deterministic shared-X policy.

        Prefer the canvas-level reset helper when present. Older canvases do
        not expose that helper, so the fallback keeps per-axis Y autoscale but
        pins every axis X range to the union of live raw channel time ranges.
        """
        canvas = self._canvas
        # Home is a deliberate view change → record the resulting view as a
        # new history entry (matplotlib pushes after the home reset). Guard
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
            # Second call toggles OFF (matplotlib parity).
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
        try:
            pix.save(path)
        except Exception:
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
