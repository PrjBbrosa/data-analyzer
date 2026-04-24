"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QSizePolicy, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .canvases import PlotCanvas, TimeDomainCanvas
from .icons import Icons
from .widgets import StatsStrip

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'order': 2}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}

# Two-line hint strings shown in the right-hand region of the chart toolbar.
# Key = current toolbar.mode ('pan' | 'zoom' | '' for idle).
_TOOL_HINTS = {
    'pan': "<b>移动曲线</b><br>左键拖动平移 · 右键拖动缩放坐标轴",
    'zoom': "<b>框选缩放</b><br>拖动鼠标框选矩形区域放大 · Home 键可复位",
    '': "<b>浏览</b><br>鼠标滚轮缩放 · 点击 ✥ 启用平移 · 点击 ⌕ 启用缩放",
}


def _strip_subplots_action(toolbar):
    """Remove the matplotlib 'Configure subplots' button — tight_layout
    is the default in this app so the dialog is not useful."""
    for act in list(toolbar.actions()):
        name = (act.text() or '').lower()
        if 'subplots' in name or 'configure subplots' in name:
            toolbar.removeAction(act)
            return


def _find_action(toolbar, text_lower):
    for act in toolbar.actions():
        if (act.text() or '').strip().lower() == text_lower:
            return act
    return None


def _vline():
    f = QFrame()
    f.setObjectName("chartToolbarSep")
    f.setFixedWidth(1)
    return f


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""

    axis_lock_requested = pyqtSignal(object)  # anchor widget for the popover

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.setObjectName("chartCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self.toolbar = NavigationToolbar(canvas, self)
        self.toolbar.setObjectName("chartToolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        _strip_subplots_action(self.toolbar)

        # Insert an axis-lock button immediately after the Pan action.
        self._axis_lock_btn = QToolButton(self.toolbar)
        self._axis_lock_btn.setIcon(Icons.axis_lock())
        self._axis_lock_btn.setIconSize(QSize(16, 16))
        self._axis_lock_btn.setToolTip("轴锁定")
        self._axis_lock_btn.setAutoRaise(True)
        self._axis_lock_btn.clicked.connect(
            lambda: self.axis_lock_requested.emit(self._axis_lock_btn)
        )
        pan_act = _find_action(self.toolbar, 'pan')
        if pan_act is not None:
            acts = self.toolbar.actions()
            idx = acts.index(pan_act)
            before = acts[idx + 1] if idx + 1 < len(acts) else None
            if before is not None:
                self.toolbar.insertWidget(before, self._axis_lock_btn)
            else:
                self.toolbar.addWidget(self._axis_lock_btn)
        else:
            self.toolbar.addWidget(self._axis_lock_btn)

        # Two-line hint label that fills the remaining toolbar space.
        self._hint_label = QLabel(self.toolbar)
        self._hint_label.setObjectName("chartHint")
        self._hint_label.setTextFormat(Qt.RichText)
        self._hint_label.setWordWrap(True)
        self._hint_label.setMinimumWidth(140)
        self._hint_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._hint_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.toolbar.addWidget(self._hint_label)

        # Only pan/zoom toggling changes the hint; one-shot buttons don't.
        for act in self.toolbar.actions():
            name = (act.text() or '').strip().lower()
            if name in ('pan', 'zoom'):
                act.triggered.connect(self._refresh_hint)

        # Default: activate the pan tool.
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' not in mode:
            self.toolbar.pan()
        self._refresh_hint()

        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)

    # ---- hint handling ----
    def _current_mode_key(self):
        mode = str(getattr(self.toolbar, 'mode', '')).lower()
        if 'pan' in mode:
            return 'pan'
        if 'zoom' in mode:
            return 'zoom'
        return ''

    def _refresh_hint(self, *_):
        key = self._current_mode_key()
        self._hint_label.setText(_TOOL_HINTS.get(key, _TOOL_HINTS['']))


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

        self.btn_subplot = QPushButton("Subplot", self.toolbar)
        self.btn_overlay = QPushButton("Overlay", self.toolbar)
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
        for label, key in [('Off', 'off'), ('Single', 'single'), ('Dual', 'dual')]:
            b = QPushButton(label, self.toolbar)
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
            self._cursor_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
        self._cursor_mode = 'off'
        self._cursor_buttons['off'].setChecked(True)

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
        self.cursor_mode_changed.emit(mode)


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    cursor_mode_changed = pyqtSignal(str)
    axis_lock_requested = pyqtSignal(object)  # anchor widget

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvas(self)
        self.canvas_fft = PlotCanvas(self)
        self.canvas_order = PlotCanvas(self)
        self._time_card = TimeChartCard(self.canvas_time)
        self._fft_card = _ChartCard(self.canvas_fft)
        self._order_card = _ChartCard(self.canvas_order)
        self.stack.addWidget(self._time_card)
        self.stack.addWidget(self._fft_card)
        self.stack.addWidget(self._order_card)
        for card in (self._time_card, self._fft_card, self._order_card):
            card.axis_lock_requested.connect(self.axis_lock_requested)
        lay.addWidget(self.stack, stretch=1)

        # Stats strip mounted at the bottom (Task 2.10)
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)

        # Cursor pill (owned by ChartStack; floats over active canvas)
        self._cursor_pill = QLabel("", self.stack)
        self._cursor_pill.setObjectName("cursorPill")
        self._cursor_pill.setVisible(False)
        self._cursor_dual_pill = QLabel("", self.stack)
        self._cursor_dual_pill.setObjectName("cursorPill")
        self._cursor_dual_pill.setWordWrap(True)
        self._cursor_dual_pill.setVisible(False)
        self.canvas_time.cursor_info.connect(self._on_cursor_info)
        self.canvas_time.dual_cursor_info.connect(self._on_dual_cursor_info)
        self.stack.currentChanged.connect(lambda _i: self._reposition_pills())

        # Relay time-card control signals up to MainWindow consumers.
        self._time_card.plot_mode_changed.connect(self.plot_mode_changed)
        self._time_card.cursor_mode_changed.connect(self.cursor_mode_changed)

    def count(self):
        return self.stack.count()

    def set_mode(self, mode):
        idx = _MODE_TO_INDEX[mode]
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
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

    def full_reset_all(self):
        self.canvas_time.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_order.full_reset()

    def _on_cursor_info(self, text):
        self._cursor_pill.setText(text)
        self._cursor_pill.adjustSize()
        self._cursor_pill.setVisible(self.current_mode() == 'time')
        self._reposition_pills()

    def _on_dual_cursor_info(self, text):
        self._cursor_dual_pill.setText(text)
        self._cursor_dual_pill.adjustSize()
        self._cursor_dual_pill.setVisible(bool(text) and self.current_mode() == 'time')
        self._reposition_pills()

    def _reposition_pills(self):
        visible = self.current_mode() == 'time'
        if not visible:
            self._cursor_pill.setVisible(False)
            self._cursor_dual_pill.setVisible(False)
            return
        card = self.stack.currentWidget()
        h = card.height() if card is not None else self.stack.height()
        pill_h = self._cursor_pill.sizeHint().height()
        self._cursor_pill.move(8, max(h - pill_h - 8, 0))
        if self._cursor_dual_pill.text():
            dh = self._cursor_dual_pill.sizeHint().height()
            self._cursor_dual_pill.move(8, max(h - pill_h - dh - 12, 0))
        self._cursor_pill.raise_()
        self._cursor_dual_pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pills()

    def cursor_pill_text(self):
        return self._cursor_pill.text()

    def cursor_pill_visible(self):
        return self._cursor_pill.isVisible()
