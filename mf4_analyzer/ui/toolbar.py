"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QWidget,
)

from .. import app_meta
from ..ui_kit.icons import Icons


class Toolbar(QWidget):
    # Left segment
    open_requested = pyqtSignal()
    save_project_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'fft_time' | 'order'
    # Right segment
    acquisition_cockpit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(8)

        # ── left group ──────────────────────────────────────────────────────
        self.btn_add = QPushButton("打开", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setToolTip("打开数据文件或项目（.tlproj）")
        self.btn_save_project = QPushButton("保存项目", self)
        self.btn_save_project.setIcon(Icons.export())
        self.btn_save_project.setToolTip("保存当前会话为 .tlproj 项目")
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.batch())
        self.btn_acquisition_cockpit = QPushButton("Cockpit", self)
        self.btn_acquisition_cockpit.setIcon(Icons.plot())
        self.btn_acquisition_cockpit.setToolTip("打开 Acquisition Cockpit")

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
                  self.btn_acquisition_cockpit,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_order):
            b.setIconSize(QSize(16, 16))

        # left layout
        left = QHBoxLayout()
        left.setSpacing(10)
        for b in (
            self.btn_add,
            self.btn_save_project,
            self.btn_batch,
            self.btn_acquisition_cockpit,
        ):
            left.addWidget(b)

        # Wrap left in a QWidget so it has a concrete sizeHint that the
        # stretch arithmetic can balance against.
        left_widget = QWidget(self)
        left_widget.setLayout(left)
        left_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

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

        self._logo_label = QLabel(self)
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

        lay.addWidget(left_widget)
        lay.addStretch(1)
        lay.addWidget(segment_frame)
        lay.addStretch(1)
        lay.addWidget(right_widget)

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
        self.btn_acquisition_cockpit.clicked.connect(self.acquisition_cockpit_requested)
        for key, b in [('time', self.btn_mode_time),
                       ('fft', self.btn_mode_fft),
                       ('fft_time', self.btn_mode_fft_time),
                       ('order', self.btn_mode_order)]:
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))

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

