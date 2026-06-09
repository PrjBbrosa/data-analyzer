"""Channel editor as a left-anchored slide-in drawer (v1 baseline: fixed panel)."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout

from ..dialogs import ChannelEditorDialog


class ChannelEditorDrawer(QDialog):
    """
    Wraps ChannelEditorDialog's content in a window anchored to the LEFT edge
    of the parent — right next to the channel/file navigator dock — so the
    editor opens close to the channels it affects (the old build anchored to
    the right edge, which the user found too far away). v1: modal QDialog,
    no slide-in animation.
    """

    # (fid, new_channels, removed_channels). The fid is whichever file the
    # user had selected in the dialog's top file combo at accept time — NOT
    # necessarily the originally-active file, since the dialog lets the user
    # switch files before applying.
    applied = pyqtSignal(str, dict, set)
    export_requested = pyqtSignal(str, list, bool, bool)

    # Width matches the narrow "方案 A" layout; the inner dialog scrolls when
    # content overflows, so a modest height is fine.
    PANEL_WIDTH = 336
    LEFT_OFFSET = 12  # px gap from the parent's left edge / navigator dock

    def __init__(self, parent, files, active_fid):
        super().__init__(parent)
        self.setObjectName("DrawerSurface")
        self._inner = ChannelEditorDialog(self, files, active_fid)
        title = self._inner.windowTitle() or "通道编辑"
        self.setWindowTitle(title.replace("通道编辑 - ", "通道编辑 — "))
        self.setModal(True)
        self._inner.setWindowFlags(Qt.Widget)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        self._inner.accepted.connect(self._on_applied)
        self._inner.rejected.connect(self.reject)
        self._inner.export_requested.connect(self.export_requested)
        h = max(520, parent.height() - 80) if parent else 520
        self.resize(self.PANEL_WIDTH, h)

    def showEvent(self, event):
        parent = self.parent()
        if parent is not None:
            pr = parent.geometry()
            x = pr.left() + self.LEFT_OFFSET
            y = pr.top() + 40
            # Clamp to the available screen so the drawer never spills off the
            # left/right or below the screen bottom.
            screen = QApplication.screenAt(pr.center()) or QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                x = max(avail.left(), min(x, avail.right() - self.width()))
                y = max(avail.top(), min(y, avail.bottom() - self.height()))
            self.move(x, y)
        super().showEvent(event)

    def _on_applied(self):
        self.applied.emit(
            self._inner.current_fid,
            self._inner.new_channels,
            self._inner.removed_channels,
        )
        self.accept()
