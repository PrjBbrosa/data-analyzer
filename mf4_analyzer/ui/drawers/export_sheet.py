"""Export Excel as top-anchored modal QDialog (Qt.Sheet fallback)."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from ..dialogs import ExportDialog


class ExportSheet(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("导出 Excel")
        self._inner = ExportDialog(self, chs)
        self._inner.setWindowFlags(Qt.Widget)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._inner)
        self._inner.accepted.connect(self.accept)
        self._inner.rejected.connect(self.reject)
        self.resize(320, 400)

    def showEvent(self, event):
        if self.parent() is not None:
            pr = self.parent().geometry()
            self.move(pr.left() + (pr.width() - self.width()) // 2, pr.top() + 40)
        super().showEvent(event)

    def get_selected(self):
        return self._inner.get_selected()

    @property
    def chk_time(self):
        return self._inner.chk_time

    @property
    def chk_range(self):
        return self._inner.chk_range
