"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QWidget,
)

from .. import app_meta
from ..ui_kit.icons import Icons


def _make_sep(parent):
    sep = QFrame(parent)
    sep.setFrameShape(QFrame.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet("background: #eef2f7; border: none;")
    return sep


class _LogoLabel(QLabel):
    """Brand logo that doubles as a hidden Cockpit entry.

    Three rapid left-clicks emit :pyattr:`triple_clicked`. The gesture is
    deliberately undiscoverable — the cursor and tooltip are unchanged, so
    the logo looks and behaves exactly like a static brand mark.

    Qt promotes the second press of a fast sequence into a
    ``mouseDoubleClickEvent`` (not a second ``mousePressEvent``), so we count
    both event kinds. A single-shot timer keyed to the platform double-click
    interval resets the counter once the clicks stop, so only *consecutive*
    clicks accumulate toward the gesture.
    """

    triple_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clicks = 0
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear)

    def _clear(self):
        self._clicks = 0

    def _register_click(self):
        self._clicks += 1
        if self._clicks >= 3:
            self._clicks = 0
            self._reset_timer.stop()
            self.triple_clicked.emit()
        else:
            self._reset_timer.start(QApplication.doubleClickInterval())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._register_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._register_click()
        super().mouseDoubleClickEvent(event)


class Toolbar(QWidget):
    # Left segment
    open_requested = pyqtSignal()
    save_project_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'fft_time' | 'order'
    # Right segment
    acquisition_cockpit_requested = pyqtSignal()
    # Panel toggle signals
    nav_panel_toggled = pyqtSignal()
    inspector_panel_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        # ── panel toggle buttons ─────────────────────────────────────────────
        self.btn_toggle_nav = QPushButton(self)
        self.btn_toggle_nav.setIcon(Icons.panel_left())
        self.btn_toggle_nav.setIconSize(QSize(16, 16))
        self.btn_toggle_nav.setCheckable(True)
        self.btn_toggle_nav.setProperty("role", "panel-toggle")
        self.btn_toggle_nav.setToolTip("收起/展开左侧导航")
        self.btn_toggle_nav.setFixedSize(28, 22)

        self.btn_toggle_inspector = QPushButton(self)
        self.btn_toggle_inspector.setIcon(Icons.panel_right())
        self.btn_toggle_inspector.setIconSize(QSize(16, 16))
        self.btn_toggle_inspector.setCheckable(True)
        self.btn_toggle_inspector.setProperty("role", "panel-toggle")
        self.btn_toggle_inspector.setToolTip("收起/展开右侧检查器")
        self.btn_toggle_inspector.setFixedSize(28, 22)

        # ── left group ──────────────────────────────────────────────────────
        self.btn_add = QPushButton("打开", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setToolTip("打开数据文件或项目（.tlproj）")
        self.btn_save_project = QPushButton("保存项目", self)
        self.btn_save_project.setIcon(Icons.save_disk())
        self.btn_save_project.setToolTip("保存当前会话为 .tlproj 项目")
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.batch())

        # ── center mode segment ─────────────────────────────────────────────
        self.btn_mode_time = QPushButton("时域", self)
        self.btn_mode_time.setIcon(Icons.mode_time())
        self.btn_mode_fft = QPushButton("FFT", self)
        self.btn_mode_fft.setIcon(Icons.mode_fft())
        self.btn_mode_fft_time = QPushButton("FFT vs Time", self)
        self.btn_mode_fft_time.setIcon(Icons.mode_fft_time())
        self.btn_mode_order = QPushButton("阶次", self)
        self.btn_mode_order.setIcon(Icons.mode_order())

        for b in (self.btn_add, self.btn_save_project, self.btn_batch,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_order):
            b.setIconSize(QSize(16, 16))

        # left layout
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        for b in (
            self.btn_add,
            self.btn_save_project,
            self.btn_batch,
        ):
            left.addWidget(b)

        # Wrap left in a QWidget so it has a concrete sizeHint that the
        # stretch arithmetic can balance against.
        left_widget = QWidget(self)
        left_widget.setLayout(left)
        left_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        left_widget.setObjectName("toolbarLeftGroup")

        # center layout inside a framed segment widget
        center = QHBoxLayout()
        center.setSpacing(0)
        segment_frame = QFrame(self)
        segment_frame.setObjectName("modeSegment")
        segment_frame.setLayout(center)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for key, b in [('time', self.btn_mode_time),
                       ('fft', self.btn_mode_fft),
                       ('fft_time', self.btn_mode_fft_time),
                       ('order', self.btn_mode_order)]:
            b.setCheckable(True)
            b.setProperty("segment", key)
            self._mode_group.addButton(b)
            center.addWidget(b)

        # ── right layout ────────────────────────────────────────────────────
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)

        self._logo_label = _LogoLabel(self)
        self._logo_label.setToolTip("博世华域转向系统有限公司")
        _logo_src = QPixmap(str(app_meta.asset_path("branding", "bosch_hasco_logo.png")))
        if not _logo_src.isNull():
            _app = QApplication.instance()
            _dpr = _app.devicePixelRatio() if _app is not None else 1.0
            _dpr = _dpr if _dpr and _dpr >= 1.0 else 1.0
            _scaled = _logo_src.scaledToWidth(int(190 * _dpr), Qt.SmoothTransformation)
            _scaled.setDevicePixelRatio(_dpr)
            self._logo_label.setPixmap(_scaled)
        right.addWidget(self._logo_label)

        # A right widget of the same fixed width as left_widget keeps the
        # segment_frame exactly centered while hosting right-aligned controls.
        right_widget = QWidget(self)
        right_widget.setLayout(right)
        right_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        right_widget.setObjectName("toolbarRightGroup")

        lay.addWidget(self.btn_toggle_nav)
        lay.addWidget(_make_sep(self))
        lay.addWidget(left_widget)
        lay.addStretch(1)
        lay.addWidget(segment_frame)
        lay.addStretch(1)
        lay.addWidget(right_widget)
        lay.addWidget(_make_sep(self))
        lay.addWidget(self.btn_toggle_inspector)

        self.btn_mode_time.setChecked(True)
        self._current_mode = 'time'

        # Keep mirror width in sync with left_widget after layout is settled.
        self._left_widget = left_widget
        self._right_widget = right_widget
        self._wire()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_mirror()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_mirror()

    def _sync_mirror(self):
        """Keep the right-side control host the same width as left_widget."""
        w = self._left_widget.sizeHint().width()
        self._right_widget.setFixedWidth(max(w, 1))

    def _wire(self):
        self.btn_add.clicked.connect(self.open_requested)
        self.btn_save_project.clicked.connect(self.save_project_requested)
        self.btn_batch.clicked.connect(self.batch_requested)
        # Hidden Cockpit entry: triple-click the brand logo (see _LogoLabel).
        self._logo_label.triple_clicked.connect(self.acquisition_cockpit_requested)
        for key, b in [('time', self.btn_mode_time),
                       ('fft', self.btn_mode_fft),
                       ('fft_time', self.btn_mode_fft_time),
                       ('order', self.btn_mode_order)]:
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
        self.btn_toggle_nav.clicked.connect(self.nav_panel_toggled)
        self.btn_toggle_inspector.clicked.connect(self.inspector_panel_toggled)

    def _set_mode(self, mode):
        if mode == self._current_mode:
            return
        self._current_mode = mode
        # Sync checked state in case this was called programmatically
        mapping = {
            'time': self.btn_mode_time,
            'fft': self.btn_mode_fft,
            'fft_time': self.btn_mode_fft_time,
            'order': self.btn_mode_order,
        }
        if mode in mapping:
            mapping[mode].setChecked(True)
        self.mode_changed.emit(mode)

    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self.btn_save_project.setEnabled(has_file)
        self.btn_batch.setEnabled(True)

    def current_mode(self):
        return self._current_mode

    def set_nav_open(self, open: bool):
        """Sync the nav toggle button checked state (checked = panel hidden)."""
        self.btn_toggle_nav.setChecked(not open)

    def set_inspector_open(self, open: bool):
        """Sync the inspector toggle button checked state (checked = panel hidden)."""
        self.btn_toggle_inspector.setChecked(not open)

