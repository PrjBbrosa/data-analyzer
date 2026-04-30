"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QWidget,
)

from .icons import Icons


class Toolbar(QWidget):
    # Left segment
    file_add_requested = pyqtSignal()
    channel_editor_requested = pyqtSignal()
    export_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'fft_time' | 'order'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(8)

        # ── left group ──────────────────────────────────────────────────────
        self.btn_add = QPushButton("添加文件", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        self.btn_add.setProperty("role", "primary")
        self.btn_edit = QPushButton("编辑通道", self)
        self.btn_edit.setIcon(Icons.edit_channels())
        self.btn_export = QPushButton("导出", self)
        self.btn_export.setIcon(Icons.export())
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.export())

        # ── center mode segment ─────────────────────────────────────────────
        self.btn_mode_time = QPushButton("时域", self)
        self.btn_mode_time.setIcon(Icons.mode_time())
        self.btn_mode_fft = QPushButton("FFT", self)
        self.btn_mode_fft.setIcon(Icons.mode_fft())
        self.btn_mode_fft_time = QPushButton("FFT vs Time", self)
        self.btn_mode_fft_time.setIcon(Icons.mode_fft_time())
        self.btn_mode_order = QPushButton("阶次", self)
        self.btn_mode_order.setIcon(Icons.mode_order())

        for b in (self.btn_add, self.btn_edit, self.btn_export, self.btn_batch,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_order):
            b.setIconSize(QSize(16, 16))

        # left layout
        left = QHBoxLayout()
        left.setSpacing(10)
        for b in (self.btn_add, self.btn_edit, self.btn_export, self.btn_batch):
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

        # ── toolbar layout: left-widget | stretch | segment | stretch | mirror ──
        # A mirror spacer of the same fixed width as left_widget ensures the
        # segment_frame sits exactly at the horizontal midpoint.
        mirror = QWidget(self)
        mirror.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        lay.addWidget(left_widget)
        lay.addStretch(1)
        lay.addWidget(segment_frame)
        lay.addStretch(1)
        lay.addWidget(mirror)

        self.btn_mode_time.setChecked(True)
        self._current_mode = 'time'

        # Keep mirror width in sync with left_widget after layout is settled.
        self._left_widget = left_widget
        self._mirror = mirror
        self._wire()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_mirror()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_mirror()

    def _sync_mirror(self):
        """Keep the right-side mirror spacer the same width as left_widget."""
        w = self._left_widget.sizeHint().width()
        self._mirror.setFixedWidth(max(w, 1))

    def _wire(self):
        self.btn_add.clicked.connect(self.file_add_requested)
        self.btn_edit.clicked.connect(self.channel_editor_requested)
        self.btn_export.clicked.connect(self.export_requested)
        self.btn_batch.clicked.connect(self.batch_requested)
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
        self.btn_edit.setEnabled(has_file)
        self.btn_export.setEnabled(has_file)
        self.btn_batch.setEnabled(True)

    def current_mode(self):
        return self._current_mode
