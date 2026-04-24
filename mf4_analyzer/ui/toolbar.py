"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class Toolbar(QWidget):
    # Left segment
    file_add_requested = pyqtSignal()
    channel_editor_requested = pyqtSignal()
    export_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'order'
    # Right segment
    cursor_reset_requested = pyqtSignal()
    axis_lock_requested = pyqtSignal(object)  # anchor QPushButton for popover

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        # placeholder buttons; real layout comes in Phase 4
        self.btn_add = QPushButton("＋ 添加文件", self)
        self.btn_edit = QPushButton("🔧 编辑通道", self)
        self.btn_export = QPushButton("📥 导出", self)
        self.btn_mode_time = QPushButton("时域", self)
        self.btn_mode_fft = QPushButton("FFT", self)
        self.btn_mode_order = QPushButton("阶次", self)
        self.btn_cursor_reset = QPushButton("⌖", self)
        self.btn_axis_lock = QPushButton("🔒", self)
        for b in (self.btn_add, self.btn_edit, self.btn_export,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_order,
                  self.btn_cursor_reset, self.btn_axis_lock):
            lay.addWidget(b)
        lay.addStretch()
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for key, b in [('time', self.btn_mode_time), ('fft', self.btn_mode_fft), ('order', self.btn_mode_order)]:
            b.setCheckable(True)
            b.setProperty("segment", key)
            self._mode_group.addButton(b)
        self.btn_mode_time.setChecked(True)
        self._current_mode = 'time'
        self._wire()

    def _wire(self):
        self.btn_add.clicked.connect(self.file_add_requested)
        self.btn_edit.clicked.connect(self.channel_editor_requested)
        self.btn_export.clicked.connect(self.export_requested)
        for key, b in [('time', self.btn_mode_time), ('fft', self.btn_mode_fft), ('order', self.btn_mode_order)]:
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
        self.btn_cursor_reset.clicked.connect(self.cursor_reset_requested)
        self.btn_axis_lock.clicked.connect(lambda: self.axis_lock_requested.emit(self.btn_axis_lock))

    def _set_mode(self, mode):
        if mode == self._current_mode:
            return
        self._current_mode = mode
        # Sync checked state in case this was called programmatically
        mapping = {'time': self.btn_mode_time, 'fft': self.btn_mode_fft, 'order': self.btn_mode_order}
        if mode in mapping:
            mapping[mode].setChecked(True)
        self.mode_changed.emit(mode)

    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self.btn_edit.setEnabled(has_file)
        self.btn_export.setEnabled(has_file)
        is_time = (mode == 'time')
        self.btn_cursor_reset.setEnabled(has_file and is_time)
        self.btn_axis_lock.setEnabled(has_file and is_time)

    def current_mode(self):
        return self._current_mode
