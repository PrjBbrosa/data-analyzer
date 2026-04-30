"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QSizePolicy, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
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

from .canvases import PlotCanvas, SpectrogramCanvas, TimeDomainCanvas
from .icons import Icons
from .widgets import StatsStrip

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}

# Hint strings shown in the chart toolbar.
# Key = current toolbar.mode ('pan' | 'zoom' | '' for idle).
# Each value is a (title, detail) tuple: title shown inline, detail in tooltip.
_TOOL_HINTS = {
    'pan':  ('移动曲线', '左键拖动平移 · 右键拖动缩放坐标轴'),
    'zoom': ('框选缩放', '拖动鼠标框选矩形区域放大 · Home 键可复位'),
    '':     ('浏览模式', '双击坐标轴可设置范围 · 工具栏可启用 平移 / 缩放 / 保存'),
}

# Bottom hint bar — persistent (always-on) shortcuts.
# Rendered left-aligned in muted gray inside QFrame#chartHintBar.
_BOTTOM_HINT_PERSISTENT = (
    "Ctrl + 滚轮 缩放 X    ·    "
    "Shift + 滚轮 缩放 Y    ·    "
    "双击坐标轴 修改范围"
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

# MDI action-key → qtawesome icon name mapping
_MDI_NAV_ICONS = {
    'home':    'mdi.home',
    'back':    'mdi.arrow-left',
    'forward': 'mdi.arrow-right',
    'pan':     'mdi.cursor-move',
    'zoom':    'mdi.magnify-plus-outline',
    'save':    'mdi.content-save-outline',
}


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


def _vline():
    f = QFrame()
    f.setObjectName("chartToolbarSep")
    f.setFixedWidth(1)
    f.setFixedHeight(20)
    f.setContentsMargins(0, 0, 0, 0)
    return f


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
        self.toolbar = NavigationToolbar(canvas, self)
        self.toolbar.setObjectName("chartToolbar")
        self.toolbar.setIconSize(QSize(18, 18))
        for act in self.toolbar.actions():
            btn = self.toolbar.widgetForAction(act)
            if btn is not None and isinstance(btn, QToolButton):
                btn.setFixedSize(QSize(32, 32))
        if self.toolbar.layout() is not None:
            self.toolbar.layout().setSpacing(8)
        _strip_subplots_action(self.toolbar)

        # Find Save BEFORE i18n changes labels (text is still 'Save' here);
        # the reference stays valid after relabel because we keep the QAction.
        save_act = _find_action(self.toolbar, 'save')

        # Apply Chinese tooltips & drop Back/Forward; this also calls
        # setData(key) on each retained action so subsequent _find_action
        # lookups by english key remain stable across locales.
        from ._toolbar_i18n import apply_chinese_toolbar_labels
        apply_chinese_toolbar_labels(self.toolbar)
        _apply_mdi_icons(self.toolbar, active_key='pan')

        # Insert "copy as image" button right before the matplotlib Save action
        # (or append if save action isn't found). This places it alongside the
        # other matplotlib nav icons so it reads as a sibling action.
        self._copy_btn = QToolButton(self.toolbar)
        self._copy_btn.setIcon(qta.icon('mdi.content-copy', color=_ICON_COLOR))
        self._copy_btn.setIconSize(QSize(18, 18))
        self._copy_btn.setFixedSize(QSize(32, 32))
        self._copy_btn.setToolTip("复制为图片（含游标线和读数）")
        self._copy_btn.setAutoRaise(True)
        self._copy_btn.clicked.connect(self.copy_image_requested)
        if save_act is not None:
            self.toolbar.insertWidget(save_act, self._copy_btn)
        else:
            self.toolbar.addWidget(self._copy_btn)

        # Two-line hint label sits at the LEFT of the toolbar (just after the
        # nav icons). Preferred size policy keeps it tight; matplotlib's own
        # locLabel — already Expanding + AlignRight — naturally takes the
        # remaining slack and pushes the (x, y) readout to the right.
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
            for act in self.toolbar.actions():
                if self.toolbar.widgetForAction(act) is loc_label:
                    loc_action = act
                    break
        if loc_action is not None:
            self.toolbar.insertWidget(loc_action, self._hint_label)
        else:
            self.toolbar.addWidget(self._hint_label)

        if annotations:
            self._install_annotation_controls(loc_action)

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

    def _insert_toolbar_widget(self, loc_action, widget):
        if loc_action is not None:
            self.toolbar.insertWidget(loc_action, widget)
        else:
            self.toolbar.addWidget(widget)

    def _install_annotation_controls(self, loc_action):
        self._insert_toolbar_widget(loc_action, _vline())
        self._annotation_label = QLabel("标注", self.toolbar)
        self._annotation_label.setObjectName("chartAnnotationLabel")
        self._annotation_label.setAlignment(Qt.AlignVCenter)
        self._insert_toolbar_widget(loc_action, self._annotation_label)

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
        self._insert_toolbar_widget(loc_action, self._annotation_btn)

        self._clear_annotation_btn = QPushButton("清除", self.toolbar)
        self._clear_annotation_btn.setIcon(qta.icon('mdi.eraser', color=_ICON_COLOR))
        self._clear_annotation_btn.setIconSize(QSize(14, 14))
        self._clear_annotation_btn.setProperty("role", "chart-choice")
        self._clear_annotation_btn.setFlat(True)
        self._clear_annotation_btn.setToolTip("清除当前图表中的所有标注")
        self._clear_annotation_btn.clicked.connect(self.clear_annotations)
        self._insert_toolbar_widget(loc_action, self._clear_annotation_btn)

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
        # Append separator + plot-mode + separator + cursor-mode into the
        # existing toolbar. Matplotlib's NavigationToolbar2QT is a QToolBar
        # subclass, so addWidget puts things inline after the icon group.
        self.toolbar.addWidget(_vline())

        self.btn_subplot = QPushButton("分屏", self.toolbar)
        self.btn_overlay = QPushButton("叠加", self.toolbar)
        for b in (self.btn_subplot, self.btn_overlay):
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
        self._plot_mode = 'subplot'
        self.btn_subplot.setChecked(True)
        self.btn_subplot.clicked.connect(lambda: self.set_plot_mode('subplot'))
        self.btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))

        self.toolbar.addWidget(_vline())

        self._cursor_buttons = {}
        for label, key in [('游标关', 'off'), ('单游标', 'single'), ('双游标', 'dual')]:
            b = QPushButton(label, self.toolbar)
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
            self._cursor_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
        self._cursor_mode = 'off'
        self._cursor_buttons['off'].setChecked(True)

        # Axis-lock chips on the right edge — only effective during zoom mode.
        # Selection is remembered across mode switches; chips merely grey out
        # when zoom is inactive.
        self.toolbar.addWidget(_vline())
        self._lock_buttons = {}
        for label, key in [('不锁', 'none'), ('锁X', 'x'), ('锁Y', 'y')]:
            b = QPushButton(label, self.toolbar)
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
            self._lock_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_axis_lock(k))
        self._axis_lock = 'none'
        self._lock_buttons['none'].setChecked(True)
        self._sync_lock_enabled()

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

    # ----- axis lock (chip group) -----
    def axis_lock(self):
        return self._axis_lock

    def set_axis_lock(self, key):
        if key not in ('none', 'x', 'y'):
            return
        self._axis_lock = key
        for k, b in self._lock_buttons.items():
            b.setChecked(k == key)
        # Push to canvas only when zoom is the active nav tool — outside zoom
        # the rubber-band lock has no effect anyway, but keeping the canvas
        # state aligned avoids a stale lock if user re-enters zoom.
        if self._is_zoom_active():
            self.canvas.set_axis_lock(key)

    def _is_zoom_active(self):
        return 'zoom' in str(getattr(self.toolbar, 'mode', '')).lower()

    def _sync_lock_enabled(self):
        zoom = self._is_zoom_active()
        for b in self._lock_buttons.values():
            b.setEnabled(zoom)
        # Apply or detach the lock when the user enters/leaves zoom mode.
        self.canvas.set_axis_lock(self._axis_lock if zoom else 'none')

    def _on_nav_mode_toggled(self, *_):
        # Extend base behavior: refresh hint AND chip enabled state.
        super()._on_nav_mode_toggled()
        self._sync_lock_enabled()


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
        self.canvas_time = TimeDomainCanvas(self)
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
        self._time_card.cursor_mode_changed.connect(self.cursor_mode_changed)
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
