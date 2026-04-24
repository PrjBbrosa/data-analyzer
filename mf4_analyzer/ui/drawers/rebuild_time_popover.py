"""Rebuild-time popover: frameless QDialog with focus-out auto-close."""
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class RebuildTimePopover(QDialog):
    def __init__(self, parent, target_filename, current_fs):
        super().__init__(parent)
        # §8.1: frameless QDialog with manual focus-out close. NOT Qt.Popup
        # because Qt.Popup + child QSpinBox can close when the spin buttons
        # take focus; the dialog must stay open while user edits Fs.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setModal(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("重建时间轴"))
        root.addWidget(QLabel(f"目标：[{target_filename}]"))
        h = QHBoxLayout()
        h.addWidget(QLabel("Fs:"))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(current_fs)
        self.spin_fs.setSuffix(" Hz")
        h.addWidget(self.spin_fs)
        root.addLayout(h)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

    def new_fs(self):
        return self.spin_fs.value()

    def show_at(self, anchor_widget):
        gp = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        self.move(gp)
        self.show()
        self.spin_fs.setFocus()
        self.activateWindow()

    def event(self, ev):
        if ev.type() == QEvent.WindowDeactivate and self.isVisible():
            self.reject()
        return super().event(ev)
