"""Axis lock popover: frameless QDialog replacing the old toolbar strip."""
from PyQt5.QtCore import Qt, QEvent, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QDialog, QLabel, QRadioButton, QVBoxLayout,
)


class AxisLockPopover(QDialog):
    lock_changed = pyqtSignal(str)  # 'none' | 'x' | 'y'

    def __init__(self, parent=None, current='none'):
        super().__init__(parent)
        self.setObjectName("PopoverSurface")
        # §8.1: frameless QDialog with WindowDeactivate → close. NOT Qt.Popup.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("轴锁（按方向拖选缩放）"))
        self._grp = QButtonGroup(self)
        for key, label in [('none', '无'), ('x', 'X 轴'), ('y', 'Y 轴')]:
            rb = QRadioButton(label, self)
            rb.setProperty("lock_key", key)
            if key == current:
                rb.setChecked(True)
            self._grp.addButton(rb)
            root.addWidget(rb)
            rb.toggled.connect(
                lambda checked, k=key: self.lock_changed.emit(k) if checked else None
            )

    def show_at(self, anchor):
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(gp)
        self.show()
        self.activateWindow()

    def event(self, ev):
        if ev.type() == QEvent.WindowDeactivate and self.isVisible():
            self.close()
        return super().event(ev)
