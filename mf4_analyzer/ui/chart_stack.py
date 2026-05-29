"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction, QFileDialog, QFrame, QLabel, QPushButton, QSizePolicy,
    QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)


class CursorPill(QFrame):
    """Draggable floating pill with a primary line (time / A·B / ΔT) and an
    optional detail block (per-channel Min/Max/Avg/△ as RichText). The
    user can drag it anywhere inside the canvas area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cursorPill")
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
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
        return self._detail.isVisible() and bool(self._detail.text())

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
from .canvases import PlotCanvas, SpectrogramCanvas, TimeDomainCanvas
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
_BOTTOM_HINT_PERSISTENT = (
    "Ctrl + 滚轮 缩放 X    ·    "
    "Shift + 滚轮 缩放 Y    ·    "
    "双击图面 图表选项"
)

# Bottom hint bar — context layer.
# Key = _ChartCard._context_hint_key(); empty string means show nothing.
_BOTTOM_HINT_CONTEXT = {
    'pan':           '平移模式：左键拖动平移 · 右键拖动缩放',
    'zoom':          '框选模式：拖出矩形放大 · Esc 取消 · Home 复位',
    'cursor_single': '单游标：点击放置游标线 · 拖动数据卡到合适位置',
    'cursor_dual':   '双游标：第 1 次点击放置 A · 第 2 次放置 B · 显示 ΔT 与统计',
    'spectrogram':   '点击谱图任一时刻可在下方查看该帧频率切片',
    'idle':          '',
}

# Icon colour tokens (match Precision Light palette)
_ICON_COLOR  = '#374151'
_ICON_ACTIVE = '#2563eb'
_TOOLBAR_COMPACT_WIDTH = 1500
_QT_WIDGETSIZE_MAX = 16777215

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
_NAV_SHORTCUTS = {
    'home': 'Alt+R',
    'back': 'Alt+Z',
    'forward': 'Alt+Shift+Z',
    'pan': 'Alt+G',
    'zoom': 'Alt+B',
}

# Time-card segmented controls — Alt+digit shortcuts (left-hand reachable).
# Keys mirror the attribute names so the install helper can locate the button.
_TIME_CARD_SHORTCUTS = (
    ('btn_subplot',           '分屏',   'Alt+1'),
    ('btn_overlay',           '叠加',   'Alt+2'),
    ('cursor_off',            '游标关', 'Alt+3'),
    ('cursor_single',         '单游标', 'Alt+4'),
    ('cursor_dual',           '双游标', 'Alt+5'),
)


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
    """Replace each retained action's icon with its MDI equivalent."""
    for act in toolbar.actions():
        key = act.data() if act.data() else (act.text() or '').strip().lower()
        icon_name = _MDI_NAV_ICONS.get(key)
        if icon_name is None:
            continue
        color = _ICON_ACTIVE if key == active_key else _ICON_COLOR
        act.setIcon(qta.icon(icon_name, color=color))


def _install_nav_shortcuts(card, toolbar):
    for key, shortcut in _NAV_SHORTCUTS.items():
        act = _find_action(toolbar, key)
        if act is None:
            continue
        seq = QKeySequence(shortcut)
        act.setShortcut(seq)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        tip = act.toolTip() or act.text()
        native = seq.toString(QKeySequence.NativeText)
        if native and native not in tip:
            act.setToolTip(f"{tip} ({native})")
        card.addAction(act)


def _install_button_shortcut(card, button, label, shortcut):
    """Attach a card-wide QShortcut to a QPushButton and annotate its tooltip.

    Buttons created from QPushButton don't have a setShortcutContext like
    QAction; the QShortcut wired here fires when the focus is anywhere
    inside the card subtree (Qt.WidgetWithChildrenShortcut).
    """
    from PyQt5.QtWidgets import QShortcut

    seq = QKeySequence(shortcut)
    sc = QShortcut(seq, card)
    sc.setContext(Qt.WidgetWithChildrenShortcut)
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
            return
        # Switching INTO pan from idle or zoom.
        self.mode = self._MODE_PAN
        self._set_all_mouse_modes(pg.ViewBox.PanMode)

    def zoom(self, *_args):
        """Toggle zoom (rectangle-drag) mode. Mirror semantics of pan()."""
        import pyqtgraph as pg

        if self.mode == self._MODE_ZOOM:
            self.mode = self._MODE_NONE
            self._set_all_mouse_modes(pg.ViewBox.PanMode)
            return
        self.mode = self._MODE_ZOOM
        self._set_all_mouse_modes(pg.ViewBox.RectMode)

    def save_figure(self, *_args):
        """Open a Save-As dialog and write the canvas grab to disk."""
        canvas = self._canvas
        if not hasattr(canvas, 'grab_pixmap'):
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "保存图片", "", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        )
        if not path:
            return
        pix = canvas.grab_pixmap()
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

    def __init__(self, canvas, parent=None, annotations=False):
        super().__init__(parent)
        self.setObjectName("chartCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self._annotation_enabled = False
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
        else:
            self.toolbar = NavigationToolbar(canvas, self)
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
        bar_lay.addWidget(self._hint_persistent)
        bar_lay.addStretch(1)
        bar_lay.addWidget(self._hint_context)

        # Default: activate the pan tool.
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' not in mode:
            self.toolbar.pan()
        self._refresh_hint()

        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)
        lay.addWidget(self._hint_bar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_toolbar()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_responsive_toolbar()

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

    def clear_annotations(self):
        if hasattr(self.canvas, 'clear_remarks'):
            self.canvas.clear_remarks()

    def open_chart_options(self):
        opener = getattr(self.canvas, 'open_chart_options_dialog', None)
        if opener is not None:
            return opener()
        return False

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

    def _context_hint_key(self):
        """Return the key into ``_BOTTOM_HINT_CONTEXT`` for the bottom-bar
        right label. Base mapping: pan/zoom → those keys, otherwise 'idle'.
        Subclasses override to inject 'cursor_single' / 'cursor_dual' /
        'spectrogram' when the toolbar is not actively in pan/zoom."""
        mode = self._current_mode_key()
        return mode if mode in ('pan', 'zoom') else 'idle'

    def _refresh_bottom_hint(self, *_):
        key = self._context_hint_key()
        text = _BOTTOM_HINT_CONTEXT.get(key, '')
        self._hint_context.setText(text)

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
        super().__init__(canvas, parent)
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
                _install_button_shortcut(self, btn, label, shortcut)
            )

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
        # Cursor mode is one of the keys consulted by _context_hint_key,
        # so refresh the bottom-hint context label whenever it flips.
        self._refresh_bottom_hint()
        self.cursor_mode_changed.emit(mode)

    def _context_hint_key(self):
        # Explicit cursor placement takes precedence over the always-on pan
        # default — when the user enables single / dual cursor, the bottom
        # context label should reflect THAT, not the resident pan mode.
        # NB: base __init__ calls _refresh_hint() before TimeChartCard's own
        # init sets _cursor_mode; getattr fallback keeps that path safe.
        cm = getattr(self, '_cursor_mode', 'off')
        if cm == 'single':
            return 'cursor_single'
        if cm == 'dual':
            return 'cursor_dual'
        return super()._context_hint_key()

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
        super().__init__(canvas, parent, annotations=annotations)

    def _context_hint_key(self):
        toolbar_key = self._current_mode_key()
        if toolbar_key in ('pan', 'zoom'):
            return toolbar_key
        return 'spectrogram'


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    cursor_mode_changed = pyqtSignal(str)
    annotation_enabled_changed = pyqtSignal(str, bool)
    image_copied = pyqtSignal(str)  # status text for the main window

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
        self._fft_card = _ChartCard(self.canvas_fft, annotations=True)
        self._fft_time_card = SpectrogramChartCard(
            self.canvas_fft_time, annotations=True,
        )
        self._order_card = _ChartCard(self.canvas_order, annotations=True)
        self.stack.addWidget(self._time_card)
        self.stack.addWidget(self._fft_card)
        self.stack.addWidget(self._fft_time_card)
        self.stack.addWidget(self._order_card)
        for card in (self._time_card, self._fft_card, self._fft_time_card, self._order_card):
            card.copy_image_requested.connect(
                lambda c=card: self._copy_card_image(c)
            )
        lay.addWidget(self.stack, stretch=1)

        # Stats strip mounted at the bottom (Task 2.10)
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)

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

        # Initial sync: stats_strip shows iff default mode is 'time'.
        self.stats_strip.setVisible(self.current_mode() == 'time')

    def count(self):
        return self.stack.count()

    def set_mode(self, mode):
        idx = _MODE_TO_INDEX[mode]
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
        self.stats_strip.setVisible(mode == 'time')
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
        self.canvas_fft.full_reset()
        self.canvas_fft_time.full_reset()
        self.canvas_order.full_reset()

    def _copy_card_image(self, card):
        """Copy the card's canvas to the clipboard. For the time-domain card,
        the floating cursor pill (if visible and overlapping the canvas) is
        composited onto the captured pixmap so the screenshot matches what
        the user sees on screen."""
        from PyQt5.QtGui import QPainter
        from PyQt5.QtWidgets import QApplication
        canvas = card.canvas
        pix = canvas.grab()
        if (card is self.stack.currentWidget()
                and card is self._time_card
                and self._pill.isVisible()):
            canvas_origin = canvas.mapTo(self.stack, canvas.rect().topLeft())
            pill_geo = self._pill.geometry()
            rel_x = pill_geo.x() - canvas_origin.x()
            rel_y = pill_geo.y() - canvas_origin.y()
            # Draw only when the pill actually overlaps the canvas rect.
            if (rel_x + pill_geo.width() > 0 and rel_x < pix.width()
                    and rel_y + pill_geo.height() > 0 and rel_y < pix.height()):
                painter = QPainter(pix)
                painter.drawPixmap(rel_x, rel_y, self._pill.grab())
                painter.end()
        QApplication.clipboard().setPixmap(pix)
        self.image_copied.emit("已复制图为图片")

    def _on_cursor_info(self, text):
        self._pill.set_primary(text)
        self._pill.setVisible(self.current_mode() == 'time')
        self._reposition_pill()

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
            card = self.stack.currentWidget()
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

    def cursor_pill_text(self):
        return self._pill.primary_text()

    def cursor_pill_visible(self):
        return self._pill.isVisible()
