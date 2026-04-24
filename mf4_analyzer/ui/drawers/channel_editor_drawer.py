"""Channel editor as a right-side slide-in drawer (v1 baseline: fixed panel)."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from ..dialogs import ChannelEditorDialog


class ChannelEditorDrawer(QDialog):
    """
    Wraps ChannelEditorDialog's content in a window anchored to the right edge
    of the parent. v1: modal QDialog positioned to the right side of the parent
    window (baseline, no slide-in animation). Phase 4 may add animation.
    """
    applied = pyqtSignal(dict, set)  # new_channels, removed_channels

    def __init__(self, parent, fd):
        super().__init__(parent)
        self.setObjectName("DrawerSurface")
        self.setWindowTitle(f"通道编辑 — {fd.filename}")
        self.setModal(True)
        self._inner = ChannelEditorDialog(self, fd)
        self._inner.setWindowFlags(Qt.Widget)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        self._inner.accepted.connect(self._on_applied)
        self._inner.rejected.connect(self.reject)
        h = max(520, parent.height() - 80) if parent else 520
        self.resize(420, h)

    def showEvent(self, event):
        if self.parent() is not None:
            pr = self.parent().geometry()
            self.move(pr.right() - self.width(), pr.top() + 40)
        super().showEvent(event)

    def _on_applied(self):
        self.applied.emit(self._inner.new_channels, self._inner.removed_channels)
        self.accept()
