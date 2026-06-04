"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QEvent, QRectF, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction, QFileDialog, QFrame, QLabel, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

# Hi-DPI copy/save scale (spec §E). The TimeDomainCanvasPG caps the
# effective magnification internally (floor 1×, width ceiling 2560px) so
# both the toolbar 保存图片 and 复制为图片 paths request the same factor and
# export stays fast.
_HIDPI_EXPORT_SCALE = 2.0
_CURSOR_PILL_RADIUS = 9.0
_CURSOR_PILL_BG = QColor(255, 255, 255, 235)
_CURSOR_PILL_BORDER = QColor("#d8e0eb")


def _pixmap_as_device_pixels(pixmap):
    if pixmap is None or pixmap.isNull():
        return pixmap
    copy = QPixmap(pixmap)
    if abs(copy.devicePixelRatioF() - 1.0) < 1e-9:
        return copy
    normalized = QPixmap.fromImage(copy.toImage())
    normalized.setDevicePixelRatio(1.0)
    return normalized


def _grab_pixmap_hidpi(canvas, requested=_HIDPI_EXPORT_SCALE):
    """Grab a hi-DPI pixmap from ``canvas``.

    Preference order, each step guarded by ``isNull()``:
    1. ``grab_pixmap(scale=requested)`` — the pyqtgraph time canvas's
       capped hi-DPI render.
    2. ``grab_pixmap()`` — a ``grab_pixmap`` without the scale kwarg.
    3. ``canvas.grab()`` — every ``QWidget`` (matplotlib fft/order
       canvases lack ``grab_pixmap`` entirely; this preserves their
       pre-existing 1× copy behavior).
    Returns ``None`` only when no path yields a non-null pixmap.
    """
    grab_px = getattr(canvas, "grab_pixmap", None)
    if grab_px is not None:
        try:
            pix = grab_px(scale=requested)
        except TypeError:
            pix = grab_px()
        except Exception:
            pix = None
        if pix is not None and not pix.isNull():
            return _pixmap_as_device_pixels(pix)
    # Fallback for canvases without grab_pixmap (matplotlib) or a null
    # grab_pixmap result: plain QWidget grab.
    try:
        pix = canvas.grab()
        if pix is not None and not pix.isNull():
            return _pixmap_as_device_pixels(pix)
    except Exception:
        pass
    return None


class CursorPill(QFrame):
    """Draggable floating pill with a primary line (time / A·B / ΔT) and an
    optional detail block (per-channel Min/Max/Avg/△ as RichText). The
    user can drag it anywhere inside the canvas area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cursorPill")
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(4)
        self._primary = QLabel("", self)
        self._primary.setObjectName("cursorPillPrimary")
        self._primary.setTextFormat(Qt.RichText)
        self._primary.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail = QLabel("", self)
        self._detail.setObjectName("cursorPillDetail")
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail.setVisible(False)
        lay.addWidget(self._primary)
        lay.addWidget(self._detail)
        self._drag_offset = None
        # User-positioned flag — true after first manual drag, so resize events
        # respect the chosen spot instead of snapping back to default corner.
        self._user_placed = False

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(_CURSOR_PILL_BG)
            painter.setPen(QPen(_CURSOR_PILL_BORDER, 1.0))
            painter.drawRoundedRect(rect, _CURSOR_PILL_RADIUS, _CURSOR_PILL_RADIUS)
        finally:
            painter.end()

    def primary_text(self):
        return self._primary.text()

    def set_primary(self, text):
        self._primary.setText(text)
        self.adjustSize()

    def set_detail_html(self, html):
        if html:
            self._detail.setText(html)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setVisible(False)
        self.adjustSize()

    def has_detail(self):
        return not self._detail.isHidden() and bool(self._detail.text())

    def clear(self):
        self._primary.clear()
        self._detail.clear()
        self._detail.setVisible(False)
        self.setVisible(False)

    def mark_user_placed(self, value=True):
        self._user_placed = bool(value)

    def is_user_placed(self):
        return self._user_placed

    # ---- drag handling ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            parent = self.parentWidget()
            new_top_left = self.mapToParent(e.pos() - self._drag_offset)
            if parent is not None:
                pw, ph = parent.width(), parent.height()
                x = max(0, min(new_top_left.x(), pw - self.width()))
                y = max(0, min(new_top_left.y(), ph - self.height()))
                self.move(x, y)
            else:
                self.move(new_top_left)
            self._user_placed = True
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import qtawesome as qta

from ..ui_kit.icons import Icons
from .canvases import PlotCanvas, SpectrogramCanvas
from . import hints
from .pg_canvases import TimeDomainCanvasPG
from .widgets import StatsStrip

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}

# Hint strings shown in the chart toolbar.
# Key = current toolbar.mode ('pan' | 'zoom' | '' for idle).
# Each value is a (title, detail) tuple: title shown inline, detail in tooltip.
_TOOL_HINTS = {
    'pan':  ('移动曲线', '左键拖动平移 · 右键拖动缩放坐标轴'),
    'zoom': ('框选缩放', '拖动鼠标框选矩形区域放大 · Home 键可复位'),
    '':     ('浏览模式', '双击图面打开图表选项 · 工具栏可启用 平移 / 缩放 / 保存'),
}

# Bottom hint bar — persistent (always-on) shortcuts.
# Rendered left-aligned in muted gray inside QFrame#chartHintBar.
# Context-layer copy is selected at runtime by hints.context_hints().
_BOTTOM_HINT_PERSISTENT = "    ·    ".join(hints.persistent_hints())

# Icon colour tokens (match Precision Light palette)
_ICON_COLOR  = '#374151'
_ICON_ACTIVE = '#2563eb'
_TOOLBAR_COMPACT_WIDTH = 1500
_QT_WIDGETSIZE_MAX = 16777215
_STATS_STRIP_ENABLED = False
_CURSOR_HTML_SEP = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'

# MDI action-key → qtawesome icon name mapping
_MDI_NAV_ICONS = {
    'home':    'mdi.home',
    'back':    'mdi.arrow-left',
    'forward': 'mdi.arrow-right',
    'pan':     'mdi.cursor-move',
    'zoom':    'mdi.magnify-plus-outline',
    'save':    'mdi.content-save-outline',
}

# Chart nav shortcuts use Alt (not Ctrl): the app has NO QMenuBar so Alt
# never collides with a menu mnemonic, and Alt+Z frees Ctrl+Z for app undo.
# The wheel modifiers (Ctrl+wheel / Shift+wheel) intentionally STAY Ctrl/Shift.
_NAV_SHORTCUTS = hints.NAV_SHORTCUTS

# Time-card segmented controls — Alt+digit shortcuts (left-hand reachable).
# Keys mirror the attribute names so the install helper can locate the button.
_TIME_CARD_SHORTCUTS = hints.TIME_CARD_SHORTCUTS


def _strip_subplots_action(toolbar):
    """Remove the matplotlib 'Configure subplots' button — tight_layout
    is the default in this app so the dialog is not useful."""
    for act in list(toolbar.actions()):
        name = (act.text() or '').lower()
        if 'subplots' in name or 'configure subplots' in name:
            toolbar.removeAction(act)
            return


def _find_action(toolbar, key_lower):
    """Match by act.data() first (i18n-stable), then by act.text()."""
    for act in toolbar.actions():
        if act.data() == key_lower or (act.text() or '').strip().lower() == key_lower:
            return act
    return None


def _apply_mdi_icons(toolbar, active_key=''):
    """Replace nav icons and flag the active button for QSS highlighting."""
    for act in toolbar.actions():
        key = act.data() if act.data() else (act.text() or '').strip().lower()
        icon_name = _MDI_NAV_ICONS.get(key)
        if icon_name is None:
            continue
        is_active = key == active_key
        color = _ICON_ACTIVE if is_active else _ICON_COLOR
        act.setIcon(qta.icon(icon_name, color=color))
        btn = toolbar.widgetForAction(act)
        if isinstance(btn, QToolButton):
            btn.setProperty("navActive", bool(is_active))
            btn.style().unpolish(btn)
            btn.style().polish(btn)


def _install_nav_shortcuts(card, toolbar):
    for key, shortcut in _NAV_SHORTCUTS.items():
        act = _find_action(toolbar, key)
        if act is None:
            continue
        shortcut = hints.shortcut_tooltip(key) or shortcut
        seq = QKeySequence(shortcut)
        act.setShortcut(seq)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        tip = act.toolTip() or act.text()
        native = seq.toString(QKeySequence.NativeText)
        if native and native not in tip:
            act.setToolTip(f"{tip} ({native})")
        act.triggered.connect(
            lambda _checked=False, c=card: c.mark_discovered("toolbar.shortcuts_exist")
        )
        card.addAction(act)


def _install_button_shortcut(card, button, label, shortcut, action_key=None):
    """Attach a card-wide QShortcut to a QPushButton and annotate its tooltip.

    Buttons created from QPushButton don't have a setShortcutContext like
    QAction; the QShortcut wired here fires when the focus is anywhere
    inside the card subtree (Qt.WidgetWithChildrenShortcut).
    """
    from PyQt5.QtWidgets import QShortcut

    shortcut = hints.shortcut_tooltip(action_key) or shortcut
    seq = QKeySequence(shortcut)
    sc = QShortcut(seq, card)
    sc.setContext(Qt.WidgetWithChildrenShortcut)
    sc.activated.connect(
        lambda c=card: c.mark_discovered("toolbar.shortcuts_exist")
    )
    sc.activated.connect(button.click)
    native = seq.toString(QKeySequence.NativeText)
    button.setToolTip(f"{label} ({native})" if native else label)
    return sc


def _vline():
    f = QFrame()
    f.setObjectName("chartToolbarSep")
    f.setFixedWidth(1)
    f.setFixedHeight(20)
    f.setContentsMargins(0, 0, 0, 0)
    return f


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
    5. ``locLabel`` (QLabel) populated at the END of the action sequence so
       the existing ``_ChartCard`` code that finds and relocates it next to
       the hint label keeps working unchanged.
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

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        # NavigationToolbar2QT exposes `.mode` as `_Mode.NONE` (str-coercible
        # to ''). We mirror with a plain string; tests do
        # `str(toolbar.mode).lower()` so a bare str works without surprises.
        self.mode = self._MODE_NONE
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
        # locLabel must exist because _ChartCard.__init__ does
        # `getattr(self.toolbar, 'locLabel', None)` and inserts it next to
        # the hint label. We populate it but don't wire mouse-move updates
        # in this revision; pyqtgraph emits hover via its own SignalProxy
        # path and that wiring is out of scope for the production switch.
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
        self._actions_by_key['home'].triggered.connect(self.home)
        self._actions_by_key['back'].triggered.connect(self.back)
        self._actions_by_key['forward'].triggered.connect(self.forward)
        self._actions_by_key['pan'].triggered.connect(self.pan)
        self._actions_by_key['zoom'].triggered.connect(self.zoom)
        self._actions_by_key['save'].triggered.connect(self.save_figure)
        # Append locLabel as the final widget — matplotlib does the same and
        # _ChartCard relocates it via toolbar.removeAction + insertAction so
        # it sits to the right of the hint label. Must be the last action.
        self.addWidget(self.locLabel)

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

    def save_figure(self, *_args):
        """Open a Save-As dialog and write the canvas grab to disk.

        Renders at a hi-DPI scale (spec §E) so the saved image is crisp;
        the canvas caps the magnification internally for speed.
        """
        canvas = self._canvas
        if not hasattr(canvas, 'grab_pixmap'):
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "保存图片", "", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        )
        if not path:
            return
        pix = _grab_pixmap_hidpi(canvas)
        if pix is None or pix.isNull():
            return
        try:
            pix.save(path)
        except Exception:
            return


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""

    copy_image_requested = pyqtSignal()  # emitted when the toolbar copy btn is clicked
    annotation_enabled_changed = pyqtSignal(bool)

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
        if viewport is not None:
            viewport.installEventFilter(self)
        self._chart_mode = chart_mode
        self._annotation_enabled = False
        self._hint_settings = QSettings()
        self._recent_context_hint_ids = set()
        self._context_hint_index = 0
        self._context_hint_signature = ()
        self._hint_rotation_paused = False
        self._hint_rotation_timer = QTimer(self)
        self._hint_rotation_timer.setInterval(10000)
        self._hint_rotation_timer.timeout.connect(self._advance_context_hint)
        # Pick the matplotlib NavigationToolbar2QT for matplotlib canvases
        # and the pyqtgraph-aware shim for TimeDomainCanvasPG. The shim
        # exposes the exact same six action keys + locLabel + mode/pan/zoom
        # surface so all downstream helpers (i18n, MDI icons, shortcuts,
        # _find_action) keep working unchanged.
        if isinstance(canvas, TimeDomainCanvasPG):
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
            # When the menu (or any path) changes the mode, refresh the
            # toolbar's icon active-state + hint, and let TimeChartCard flip
            # its axis-lock chips, exactly as a toolbar-button click would.
            self.toolbar.mouse_mode_changed.connect(self._on_mouse_mode_changed)
        else:
            self.toolbar = NavigationToolbar(canvas, self)
        context_menu_requested = getattr(canvas, 'context_menu_requested', None)
        if context_menu_requested is not None:
            context_menu_requested.connect(
                lambda: self.mark_discovered("chart.right_click_menu")
            )
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

        # Find Save BEFORE i18n changes labels (text is still 'Save' here);
        # the reference stays valid after relabel because we keep the QAction.
        save_act = _find_action(self.toolbar, 'save')

        # Apply Chinese tooltips & drop Back/Forward; this also calls
        # setData(key) on each retained action so subsequent _find_action
        # lookups by english key remain stable across locales.
        from ._toolbar_i18n import apply_chinese_toolbar_labels
        apply_chinese_toolbar_labels(self.toolbar)
        _install_nav_shortcuts(self, self.toolbar)
        _apply_mdi_icons(self.toolbar, active_key='pan')

        # Insert app-level chart actions right before the matplotlib Save action
        # (or append if save action isn't found). This places them alongside the
        # other matplotlib nav icons so they read as sibling actions.
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
        if save_act is not None:
            self.toolbar.insertWidget(save_act, self._options_btn)
            self.toolbar.insertWidget(save_act, self._copy_btn)
        else:
            self.toolbar.addWidget(self._options_btn)
            self.toolbar.addWidget(self._copy_btn)

        # Two-line hint label sits at the LEFT of the toolbar. Matplotlib's
        # native locLabel is moved next to it with a fixed width so (x, y)
        # updates cannot push the right-side chart controls around.
        self._hint_label = QLabel(self.toolbar)
        self._hint_label.setObjectName("chartHint")
        self._hint_label.setTextFormat(Qt.RichText)
        self._hint_label.setWordWrap(True)
        self._hint_label.setMinimumWidth(180)
        self._hint_label.setFixedHeight(28)
        self._hint_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._hint_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        loc_label = getattr(self.toolbar, 'locLabel', None)
        loc_action = None
        if loc_label is not None:
            loc_label.setObjectName("chartLocLabel")
            loc_label.setMinimumWidth(190)
            loc_label.setMaximumWidth(190)
            loc_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            loc_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for act in self.toolbar.actions():
                if self.toolbar.widgetForAction(act) is loc_label:
                    loc_action = act
                    break
        if loc_action is not None:
            hint_action = self.toolbar.insertWidget(loc_action, self._hint_label)
            self.toolbar.removeAction(loc_action)
            self.toolbar.insertAction(hint_action, loc_action)
        else:
            self.toolbar.addWidget(self._hint_label)
        self._loc_action = None

        if annotations:
            self._install_annotation_controls(None)

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

        # Bottom hint bar (Persistent + Context layers). Sits BELOW the canvas
        # so it does not jostle the toolbar layout. The persistent label is
        # always populated; the context label updates via _refresh_bottom_hint
        # whenever pan/zoom toggles or (in subclasses) cursor mode changes.
        self._hint_bar = QFrame(self)
        self._hint_bar.setObjectName("chartHintBar")
        self._hint_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._hint_bar.setFixedHeight(22)
        from PyQt5.QtWidgets import QHBoxLayout
        bar_lay = QHBoxLayout(self._hint_bar)
        bar_lay.setContentsMargins(4, 2, 4, 2)
        bar_lay.setSpacing(0)
        self._hint_persistent = QLabel(_BOTTOM_HINT_PERSISTENT, self._hint_bar)
        self._hint_persistent.setObjectName("chartHintPersistent")
        self._hint_persistent.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._hint_context = QLabel("", self._hint_bar)
        self._hint_context.setObjectName("chartHintContext")
        self._hint_context.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._hint_discovery = QLabel("", self._hint_bar)
        self._hint_discovery.setObjectName("chartHintDiscovery")
        self._hint_discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar_lay.addWidget(self._hint_persistent)
        bar_lay.addStretch(1)
        bar_lay.addWidget(self._hint_discovery)
        bar_lay.addWidget(self._hint_context)

        # Default: activate the pan tool.
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' not in mode:
            self.toolbar.pan()
        self._refresh_hint()
        self._hint_rotation_timer.start()

        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)
        lay.addWidget(self._hint_bar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_toolbar()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_responsive_toolbar()

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            self.set_hint_rotation_paused(True)
        elif etype in (QEvent.MouseButtonRelease, QEvent.Leave):
            self.set_hint_rotation_paused(False)
        return super().eventFilter(obj, event)

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
        self._hint_label.setMinimumWidth(0 if compact else 180)
        self._hint_label.setMaximumWidth(0 if compact else _QT_WIDGETSIZE_MAX)
        self._hint_label.setVisible(not compact)
        loc_label = getattr(self.toolbar, 'locLabel', None)
        if loc_label is not None:
            loc_width = 0 if compact else 190
            loc_label.setMinimumWidth(loc_width)
            loc_label.setMaximumWidth(loc_width)
            loc_label.setVisible(not compact)
        self.toolbar.updateGeometry()

    def _insert_toolbar_widget(self, loc_action, widget):
        if loc_action is not None:
            self.toolbar.insertWidget(loc_action, widget)
        else:
            self.toolbar.addWidget(widget)

    def _insert_right_toolbar_widget(self, loc_action, widget):
        # Insert at the card's right-control zone. Passing ``None`` appends
        # after the fixed loc/hint labels; TimeDomain uses the same path.
        self._insert_toolbar_widget(loc_action, widget)

    def _install_annotation_controls(self, loc_action):
        self._annotation_spacer = QWidget(self.toolbar)
        self._annotation_spacer.setObjectName("chartAnnotationSpacer")
        self._annotation_spacer.setAttribute(Qt.WA_StyledBackground, True)
        self._annotation_spacer.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self._insert_right_toolbar_widget(loc_action, self._annotation_spacer)

        self._insert_right_toolbar_widget(loc_action, _vline())
        self._annotation_label = QLabel("标注", self.toolbar)
        self._annotation_label.setObjectName("chartAnnotationLabel")
        self._annotation_label.setAlignment(Qt.AlignVCenter)
        self._insert_right_toolbar_widget(loc_action, self._annotation_label)

        self._annotation_btn = QPushButton("开启", self.toolbar)
        self._annotation_btn.setIcon(
            qta.icon('mdi.map-marker-plus-outline', color=_ICON_COLOR)
        )
        self._annotation_btn.setIconSize(QSize(14, 14))
        self._annotation_btn.setCheckable(True)
        self._annotation_btn.setProperty("role", "chart-choice")
        self._annotation_btn.setFlat(True)
        self._annotation_btn.setToolTip("开启后左键添加标注；右键删除最近标注")
        self._annotation_btn.clicked.connect(
            lambda checked=False: self.set_annotation_enabled(checked)
        )
        self._insert_right_toolbar_widget(loc_action, self._annotation_btn)

        self._clear_annotation_btn = QPushButton("清除", self.toolbar)
        self._clear_annotation_btn.setIcon(qta.icon('mdi.eraser', color=_ICON_COLOR))
        self._clear_annotation_btn.setIconSize(QSize(14, 14))
        self._clear_annotation_btn.setProperty("role", "chart-choice")
        self._clear_annotation_btn.setFlat(True)
        self._clear_annotation_btn.setToolTip("清除当前图表中的所有标注")
        self._clear_annotation_btn.clicked.connect(self.clear_annotations)
        self._insert_right_toolbar_widget(loc_action, self._clear_annotation_btn)

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
            btn.setText("关闭" if self._annotation_enabled else "开启")
            icon_color = _ICON_ACTIVE if self._annotation_enabled else _ICON_COLOR
            btn.setIcon(qta.icon('mdi.map-marker-plus-outline', color=icon_color))
            btn.blockSignals(False)
        if notify:
            self.annotation_enabled_changed.emit(self._annotation_enabled)
        self._refresh_bottom_hint()

    def clear_annotations(self):
        if hasattr(self.canvas, 'clear_remarks'):
            self.canvas.clear_remarks()

    def open_chart_options(self):
        opener = getattr(self.canvas, 'open_chart_options_dialog', None)
        if opener is not None:
            return opener()
        return False

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

    def _hint_state(self):
        return hints.HintState(
            mode=self._chart_mode,
            mouse_mode=self._current_mode_key(),
            chart_kind=self._chart_mode,
            annotation_on=self.annotation_enabled(),
            discovered=hints.load_discovered(self._hint_settings),
            recently_used=frozenset(self._recent_context_hint_ids),
        )

    def _refresh_bottom_hint(self, *_):
        discovery = hints.discovery_hint(self._hint_state())
        self._hint_discovery.setText(discovery.text if discovery else '')
        self._set_context_hint(reset=True)

    def _set_context_hint(self, reset=False):
        candidates = hints.context_hints(self._hint_state())
        signature = tuple(hint.id for hint in candidates)
        if reset or signature != self._context_hint_signature:
            self._context_hint_index = 0
            self._context_hint_signature = signature
        if not candidates:
            self._hint_context.setText('')
            return
        index = self._context_hint_index % len(candidates)
        self._hint_context.setText(candidates[index].text)

    def _advance_context_hint(self):
        if self._hint_rotation_paused:
            return
        candidates = hints.context_hints(self._hint_state())
        if len(candidates) <= 1:
            self._set_context_hint()
            return
        self._context_hint_index = (self._context_hint_index + 1) % len(candidates)
        self._context_hint_signature = tuple(hint.id for hint in candidates)
        self._set_context_hint()

    def set_hint_rotation_paused(self, paused):
        self._hint_rotation_paused = bool(paused)

    def mark_context_hint_used(self, hint_id):
        self._recent_context_hint_ids.add(hint_id)
        self._refresh_bottom_hint()

    def set_hint_settings(self, settings):
        self._hint_settings = settings
        self._refresh_bottom_hint()

    def mark_discovered(self, hint_id):
        hints.mark_discovered(self._hint_settings, hint_id)
        self._refresh_bottom_hint()

    def _refresh_hint(self, *_):
        key = self._current_mode_key()
        title, detail = _TOOL_HINTS.get(key, _TOOL_HINTS[''])
        color = _ICON_ACTIVE if key else _ICON_COLOR
        self._hint_label.setText(f'<b style="color:{color}">{title}</b>')
        self._hint_label.setToolTip(f'{title}\n{detail}')
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
        # Right-align time-only controls with the same locLabel insertion
        # point used by annotation controls on analysis cards.
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
        # mode, force the matplotlib nav toolbar OUT of pan/zoom so a blank-
        # area click can clear the selection without being eaten by a pan
        # press. Deselect intentionally does NOT restore the previous mode —
        # the user re-engages pan via Alt+G if they want it back.
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
        # carry the "(Alt+N)" suffix; no plain-text setToolTip needed here.
        self._time_toolbar_compact = None

        # Card-wide Alt+1..5 shortcuts for the segmented controls.
        self._time_button_shortcuts = []
        button_by_key = {
            'btn_subplot':   self.btn_subplot,
            'btn_overlay':   self.btn_overlay,
            'cursor_off':    self._cursor_buttons['off'],
            'cursor_single': self._cursor_buttons['single'],
            'cursor_dual':   self._cursor_buttons['dual'],
        }
        for key, label, shortcut in _TIME_CARD_SHORTCUTS:
            btn = button_by_key.get(key)
            if btn is None:
                continue
            self._time_button_shortcuts.append(
                _install_button_shortcut(self, btn, label, shortcut, key)
            )
        self.view_tabbar = None

    def mount_view_tabbar(self, bar):
        """Mount the ViewTabBar between the canvas and bottom hint bar."""
        bar.setParent(self)
        lay = self.layout()
        lay.insertWidget(lay.indexOf(self._hint_bar), bar)
        self.view_tabbar = bar

    def _sync_responsive_toolbar(self):
        super()._sync_responsive_toolbar()
        labels = getattr(self, '_time_button_labels', None)
        if not labels:
            return
        compact = self.toolbar.width() < _TOOLBAR_COMPACT_WIDTH
        if compact == self._time_toolbar_compact:
            return
        self._time_toolbar_compact = compact
        for button, full, short in labels:
            button.setText(short if compact else full)
            if compact:
                button.setMinimumWidth(0)
                button.setMaximumWidth(44)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(_QT_WIDGETSIZE_MAX)
        for sep in self._time_separators:
            sep.setVisible(not compact)
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
        )

    # ----- overlay-selection nav handoff -----
    def _on_overlay_channel_selected(self, name):
        """Switch the matplotlib nav toolbar to idle while a curve is selected.

        Pan / zoom would otherwise eat the next blank-area click and prevent
        deselect. We do NOT restore the previous mode on deselect — the user
        can re-engage pan (Alt+G) or zoom (Alt+B) explicitly. Called with
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


class SpectrogramChartCard(_ChartCard):
    """Spectrogram (FFT vs Time) chart card. Adds a spectrogram-specific
    bottom-bar hint when the toolbar isn't in pan/zoom — guides the user to
    click on the spectrogram to surface the per-frame frequency slice."""

    def __init__(self, canvas, parent=None, annotations=False):
        super().__init__(
            canvas,
            parent,
            annotations=annotations,
            chart_mode='fft_time',
        )


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

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvasPG(self)
        self.canvas_fft = PlotCanvas(self)
        self.canvas_fft_time = SpectrogramCanvas(self)
        self.canvas_order = PlotCanvas(self)
        self._time_card = TimeChartCard(self.canvas_time)
        self._time_split = QSplitter(Qt.Horizontal, self.stack)
        self._time_split.setObjectName("timeDomainSplit")
        self._time_split.setChildrenCollapsible(False)
        self._time_split.addWidget(self._time_card)
        self._secondary_card = None
        # Focus routing (P2 Task 9 Step 5): the focused time card receives
        # channel-check replots while side-by-side is active. Defaults to the
        # primary card; a click on either card switches focus (see
        # _install_focus_filter / eventFilter). Outside split mode the
        # focused card is always the primary and the property is unset.
        self._focused_card = self._time_card
        self._install_focus_filter(self._time_card)
        self._fft_card = _ChartCard(
            self.canvas_fft,
            annotations=True,
            chart_mode='fft',
        )
        self._fft_time_card = SpectrogramChartCard(
            self.canvas_fft_time, annotations=True,
        )
        self._order_card = _ChartCard(
            self.canvas_order,
            annotations=True,
            chart_mode='order',
        )
        self.stack.addWidget(self._time_split)
        self.stack.addWidget(self._fft_card)
        self.stack.addWidget(self._fft_time_card)
        self.stack.addWidget(self._order_card)
        for card in (self._time_card, self._fft_card, self._fft_time_card, self._order_card):
            card.copy_image_requested.connect(
                lambda c=card: self._copy_card_image(c)
            )
        lay.addWidget(self.stack, stretch=1)

        # Stats strip retained for later re-enable, but hidden from the UI for now.
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)
        self.stats_strip.setVisible(_STATS_STRIP_ENABLED)

        # Single draggable cursor pill (owned by ChartStack; floats over the
        # active canvas card). Default position is the top-right corner so it
        # stays clear of Y-axis labels and the typical data-of-interest area;
        # the user can drag it elsewhere — see CursorPill.mark_user_placed.
        self._pill = CursorPill(self.stack)
        self._pill.setVisible(False)
        self.canvas_time.cursor_info.connect(self._on_cursor_info)
        self.canvas_time.dual_cursor_info.connect(self._on_dual_cursor_info)
        self.stack.currentChanged.connect(lambda _i: self._reposition_pill())

        # Relay time-card control signals up to MainWindow consumers.
        self._time_card.plot_mode_changed.connect(self.plot_mode_changed)
        self._time_card.cursor_mode_changed.connect(
            self._on_time_cursor_mode_changed
        )
        for mode, card in (
            ('fft', self._fft_card),
            ('fft_time', self._fft_time_card),
            ('order', self._order_card),
        ):
            card.annotation_enabled_changed.connect(
                lambda enabled, m=mode: self.annotation_enabled_changed.emit(m, enabled)
            )

        # Initial sync: stats_strip is currently disabled at the product level.
        self.stats_strip.setVisible(
            _STATS_STRIP_ENABLED and self.current_mode() == 'time'
        )

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
            return
        self._focused_card = card
        self._refresh_focus_borders()
        self.focus_changed.emit(card is self._secondary_card)

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
            # Dynamic-property QSS selectors need an explicit unpolish/polish
            # to re-evaluate (see lesson: action-button-on-group-title).
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
            self._set_secondary_time_controls_enabled(False)
            self._secondary_card.copy_image_requested.connect(
                lambda: self._copy_card_image(self._secondary_card)
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

    def exit_split(self):
        if self._secondary_card is not None:
            self._secondary_card.setVisible(False)
        # Back to single pane: drop focus highlighting and reset to primary.
        self._focused_card = self._time_card
        self._refresh_focus_borders()

    def attach_view_tabbar(self, manager):
        from .view_tabbar import ViewTabBar

        existing = getattr(self, '_view_tabbar', None)
        if existing is not None:
            existing.setVisible(self.current_mode() == 'time')
            return existing

        bar = ViewTabBar(manager, self._time_card)
        self._time_card.mount_view_tabbar(bar)
        self._view_tabbar = bar
        bar.setVisible(self.current_mode() == 'time')
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
        self.mode_changed.emit(mode)

    def current_mode(self):
        return _INDEX_TO_MODE[self.stack.currentIndex()]

    # ----- plot-mode / cursor-mode passthroughs -----
    def plot_mode(self):
        return self._time_card.plot_mode()

    def set_plot_mode(self, mode):
        self._time_card.set_plot_mode(mode)

    def cursor_mode(self):
        return self._time_card.cursor_mode()

    def set_cursor_mode(self, mode):
        self._time_card.set_cursor_mode(mode)

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
        card = self._secondary_card
        if card is None:
            return
        for button in (card.btn_subplot, card.btn_overlay):
            button.setEnabled(enabled)
        for button in card._cursor_buttons.values():
            button.setEnabled(enabled)

    def _copy_card_image(self, card):
        """Capture the card's canvas for MainWindow to publish. For the
        time-domain card, the floating cursor pill (if visible and overlapping
        the canvas) is composited onto the captured pixmap so the screenshot
        matches what the user sees on screen.

        The canvas is grabbed at a hi-DPI scale (spec §E) for a crisp,
        DPI-independent bitmap; the canvas caps the magnification for
        speed. The cursor pill's position AND size are scaled by the SAME
        effective factor so it still lines up on the magnified bitmap."""
        from PyQt5.QtCore import QRect
        from PyQt5.QtGui import QPainter
        canvas = card.canvas
        pix = _grab_pixmap_hidpi(canvas)
        if pix is None or pix.isNull():
            return
        canvas_w = max(1, int(canvas.width()))
        canvas_h = max(1, int(canvas.height()))
        scale_x = max(1.0, float(pix.width()) / float(canvas_w))
        scale_y = max(1.0, float(pix.height()) / float(canvas_h))
        if (card is self._time_card
                and self.current_mode() == 'time'
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
        from PyQt5.QtGui import QImage, QPainter, QPixmap
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

    def _on_cursor_info(self, text):
        primary, detail = self._format_cursor_info_for_pill(text)
        self._pill.set_primary(primary)
        if self.cursor_mode() == 'single':
            self._pill.set_detail_html(detail)
        self._pill.setVisible(self.current_mode() == 'time')
        self._reposition_pill()

    def _format_cursor_info_for_pill(self, text):
        if self.cursor_mode() != 'single' or _CURSOR_HTML_SEP not in (text or ''):
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

    def _on_dual_cursor_info(self, text):
        self._pill.set_detail_html(text)
        if self.current_mode() == 'time' and (text or self._pill.primary_text()):
            self._pill.setVisible(True)
        self._reposition_pill()

    def _reposition_pill(self):
        if self.current_mode() != 'time':
            self._pill.setVisible(False)
            return
        if self._pill.is_user_placed():
            # Re-clamp into the visible area in case the window shrank.
            pw, ph = self.stack.width(), self.stack.height()
            x = max(0, min(self._pill.x(), pw - self._pill.width()))
            y = max(0, min(self._pill.y(), ph - self._pill.height()))
            self._pill.move(x, y)
        else:
            # Default anchor: top-right of the canvas area (under the toolbar)
            # with an 8 px inset so the pill never covers toolbar buttons.
            card = self._time_card
            w = card.width() if card is not None else self.stack.width()
            y_top = 8
            if card is not None and hasattr(card, 'canvas'):
                origin = card.canvas.mapTo(self.stack, card.canvas.rect().topLeft())
                y_top = origin.y() + 8
            self._pill.move(max(w - self._pill.width() - 8, 0), y_top)
        self._pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pill()

    def clear_cursor_pill(self):
        """Clear pill content and hide it; preserves the user-placed flag so a
        subsequent cursor activation reappears at the spot the user chose."""
        self._pill.clear()

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
