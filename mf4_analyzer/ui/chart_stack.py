"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QEvent, QRectF, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction, QAbstractSpinBox, QButtonGroup, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter,
    QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
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


def _format_mini_html(rows):
    """Mini dual-cursor: one row per channel — colored dot + name + △ only."""
    from html import escape
    parts = ['<table cellspacing="0" cellpadding="0" style="font-size:11px;">']
    for i, row in enumerate(rows):
        if len(row) >= 7:
            ch, _mn, _mx, _avg, delta, u, color = row[:7]
        else:
            ch, _mn, _mx, _avg, delta, u = row[:6]
            color = '#111827'
        if ']' in ch and ch.startswith('['):
            ch = ch.split(']', 1)[-1].strip()
        top_pad = '5px' if i > 0 else '0'
        mono = "font-family:'SF Mono',Menlo,Consolas,monospace;"
        parts.append(
            f'<tr><td style="padding-top:{top_pad};">'
            f'<span style="color:{color};">●</span></td>'
            f'<td style="padding-left:4px; color:{color}; font-weight:600; padding-top:{top_pad};">'
            f'{escape(ch)}</td>'
            f'<td style="padding-left:8px; color:{color}; {mono} padding-top:{top_pad};">'
            f'△&nbsp;{delta:.4g}{escape(u)}</td></tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


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
        lay.setContentsMargins(10, 7, 22, 8)
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
        self._mode = "full"
        self._dual_rows = []
        self._toggle_btn = QPushButton("−", self)
        self._toggle_btn.setObjectName("cursorPillToggle")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.setCursor(Qt.ArrowCursor)
        self._toggle_btn.clicked.connect(self._toggle_mode)
        self._toggle_btn.raise_()

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
        self._dual_rows = []
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        btn_w = self._toggle_btn.width()
        self._toggle_btn.move(self.width() - btn_w - 4, 4)

    def _toggle_mode(self):
        self._mode = "mini" if self._mode == "full" else "full"
        self._toggle_btn.setText("+" if self._mode == "mini" else "−")
        self._refresh_detail()
        self.adjustSize()

    def set_dual_rows(self, rows):
        self._dual_rows = rows or []
        self._refresh_detail()
        if self._dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()

    def _refresh_detail(self):
        if not self._dual_rows:
            return
        from .canvases import _format_dual_html
        html = _format_dual_html(self._dual_rows) if self._mode == "full" else _format_mini_html(self._dual_rows)
        if html:
            self._detail.setText(html)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setVisible(False)


class _QualityStatusIndicator(QFrame):
    """Small hoverable AA status dot overlaid on the chart card chrome."""

    _COLORS = {
        "green": QColor("#22c55e"),
        "yellow": QColor("#f59e0b"),
        "red": QColor("#ef4444"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartQualityIndicator")
        self.setFixedSize(20, 20)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._state = "red"
        self.set_quality_status({
            "state": "red",
            "tooltip": "抗锯齿未激活：无曲线",
        })

    def set_quality_status(self, status):
        state = str((status or {}).get("state") or "red")
        if state not in self._COLORS:
            state = "red"
        self._state = state
        self.setProperty("qualityState", state)
        self.setToolTip(str((status or {}).get("tooltip") or "抗锯齿状态未知"))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(5.0, 5.0, -5.0, -5.0)
            painter.setBrush(self._COLORS.get(self._state, self._COLORS["red"]))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.0))
            painter.drawEllipse(rect)
        finally:
            painter.end()

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import qtawesome as qta

from ..ui_kit.icons import Icons
from . import hints
from .pg_canvases import TimeDomainCanvasPG
from .pg_canvas.heatmap_canvas import PgHeatmapCanvas
from .pg_canvas.line_canvas import PgLineCanvas
from .widgets import StatsStrip
from .analysis_section_page import AnalysisSectionPage
from .analysis_view_state import AnalysisViewState
from .view_state import ViewManager

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}

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

# Chart nav shortcuts use Ctrl.
# The wheel modifiers (Ctrl+wheel / Shift+wheel) intentionally STAY Ctrl/Shift.
_NAV_SHORTCUTS = hints.NAV_SHORTCUTS

# Time-card segmented controls — Ctrl+digit shortcuts (left-hand reachable).
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


class _TickDensityPopover(QFrame):
    density_changed = pyqtSignal(int, int)

    _PRESETS = {
        "疏": (6, 5),
        "标准": (10, 8),
        "密": (20, 14),
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
            "Y", 3, 20, 8
        )
        lay.addWidget(self._x_row)
        lay.addWidget(self._y_row)

        self._reset_btn = QPushButton("恢复默认 10 / 8", self._surface)
        self._reset_btn.setObjectName("tickDensityResetButton")
        self._reset_btn.clicked.connect(lambda: self.set_density(10, 8, emit=True))
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
        self.set_density(10, 8, emit=False)

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
        path, _filter = QFileDialog.getSaveFileName(
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


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""

    copy_image_requested = pyqtSignal()  # emitted when the toolbar copy btn is clicked
    annotation_enabled_changed = pyqtSignal(bool)
    tick_density_changed = pyqtSignal(int, int)

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
        self._hint_rotation_paused = False
        self._hint_rotation_timer = QTimer(self)
        self._hint_rotation_timer.setInterval(10000)
        self._hint_rotation_timer.timeout.connect(self._advance_context_hint)
        # Pick the matplotlib NavigationToolbar2QT for matplotlib canvases
        # and the pyqtgraph-aware shim for TimeDomainCanvasPG. The shim
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
            # When the menu (or any path) changes the mode, refresh the
            # toolbar icon active-state + bottom hint, and let TimeChartCard
            # flip its axis-lock chips, exactly as a toolbar-button click would.
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
        self._remove_toolbar_loc_label()

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
        self._tick_density_btn.setToolTip("刻度密度 X10 / Y8")
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

        # Bottom hint bar (Persistent + Context layers). Sits BELOW the canvas
        # so it does not jostle the toolbar layout. The persistent label is
        # always populated; the context label updates via _refresh_bottom_hint
        # whenever pan/zoom toggles or (in subclasses) cursor mode changes.
        self._hint_bar = QFrame(self)
        self._hint_bar.setObjectName("chartHintBar")
        self._hint_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._hint_bar.setFixedHeight(22)
        bar_lay = QHBoxLayout(self._hint_bar)
        bar_lay.setContentsMargins(4, 2, 4, 2)
        bar_lay.setSpacing(0)
        self._hint_persistent = QLabel(_BOTTOM_HINT_PERSISTENT, self._hint_bar)
        self._hint_persistent.setObjectName("chartHintPersistent")
        self._hint_persistent.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._hint_context = QLabel("", self._hint_bar)
        self._hint_context.setObjectName("chartHintContext")
        self._hint_context.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._flash_hint_timer = QTimer(self)
        self._flash_hint_timer.setSingleShot(True)
        self._flash_hint_timer.setInterval(2500)
        self._flash_hint_timer.timeout.connect(
            lambda: self._set_context_hint(reset=True)
        )
        if hasattr(self.canvas, 'overlay_y_needs_selection'):
            self.canvas.overlay_y_needs_selection.connect(
                lambda: self.flash_hint("先选中一个通道，再用 Shift+滚轮缩放纵向")
            )
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
        bar = getattr(self, "_focus_bar", None)
        if bar is not None and bar.isVisible():
            bar.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_responsive_toolbar()
        self._position_quality_indicator()
        self._schedule_quality_indicator_position()
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
        elif obj is getattr(self, "_canvas_viewport", None) and etype in (
            QEvent.Resize, QEvent.Show
        ):
            self._schedule_quality_indicator_position()
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
        if hasattr(self.canvas, 'clear_remarks'):
            self.canvas.clear_remarks()

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

    def flash_hint(self, text):
        """Show a transient context hint, then restore the rotating hint."""
        self._hint_context.setText(str(text))
        self._flash_hint_timer.start()

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
        zoom_act = _find_action(self.toolbar, 'zoom')
        self._install_compact_annotation_control_after(zoom_act)
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
        # mode, force the matplotlib nav toolbar OUT of pan/zoom so a blank-
        # area click can clear the selection without being eaten by a pan
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvasPG(self)
        self._time_card = TimeChartCard(self.canvas_time)
        self._primary_plot_mode = self._time_card.plot_mode()
        self._primary_cursor_mode = self._time_card.cursor_mode()
        self._time_page = QWidget(self.stack)
        self._time_page.setObjectName("timeDomainPage")
        time_lay = QVBoxLayout(self._time_page)
        time_lay.setContentsMargins(0, 0, 0, 0)
        time_lay.setSpacing(0)
        self._time_toolbar = self._time_card.detach_toolbar(self._time_page)
        time_lay.addWidget(self._time_toolbar)
        self._time_split = QSplitter(Qt.Horizontal, self._time_page)
        self._time_split.setObjectName("timeDomainSplit")
        self._time_split.setChildrenCollapsible(False)
        self._time_split.addWidget(self._time_card)
        time_lay.addWidget(self._time_split, stretch=1)
        self._time_bottom_dock = QFrame(self._time_page)
        self._time_bottom_dock.setObjectName("timeViewBottomDock")
        self._time_bottom_dock.setAttribute(Qt.WA_StyledBackground, True)
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
        self._time_hint_bar.setFixedHeight(20)
        lay = self._time_hint_bar.layout()
        while lay.count():
            lay.takeAt(0)
        lay.setContentsMargins(8, 1, 8, 1)
        lay.setSpacing(0)
        for label in (
            self._time_card._hint_persistent,
            self._time_card._hint_discovery,
            self._time_card._hint_context,
        ):
            label.setAlignment(Qt.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(self._time_card._hint_persistent, 0)
        lay.addWidget(self._time_card._hint_discovery, 0)
        lay.addWidget(self._time_card._hint_context, 0)
        lay.addStretch(1)

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
        from .view_tabbar import ViewTabBar

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
        from PyQt5.QtCore import QRect
        from PyQt5.QtGui import QPainter
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
