"""Toggle bar with mutually-exclusive 🔒X / 🔒Y buttons.
Emits lock_changed(mode) where mode in {'x', 'y', 'none'}."""
from PyQt5.QtCore import pyqtSignal, QSize
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QToolButton

from .icons import Icons


class AxisLockBar(QWidget):
    lock_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.btn_x = self._make_btn(Icons.lock_x(), "仅缩放 X 轴（左键拖动框选）")
        self.btn_y = self._make_btn(Icons.lock_y(), "仅缩放 Y 轴（左键拖动框选）")
        lay.addWidget(self.btn_x)
        lay.addWidget(self.btn_y)
        lay.addStretch()
        self.btn_x.toggled.connect(lambda v: self._on_toggle('x', v))
        self.btn_y.toggled.connect(lambda v: self._on_toggle('y', v))

    def _make_btn(self, icon, tip):
        b = QToolButton()
        b.setIcon(icon)
        b.setIconSize(QSize(18, 18))
        b.setCheckable(True)
        b.setToolTip(tip)
        b.setObjectName("axisLock")
        return b

    def _on_toggle(self, which, checked):
        if checked:
            other = self.btn_y if which == 'x' else self.btn_x
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
            self.lock_changed.emit(which)
        else:
            if not self.btn_x.isChecked() and not self.btn_y.isChecked():
                self.lock_changed.emit('none')
