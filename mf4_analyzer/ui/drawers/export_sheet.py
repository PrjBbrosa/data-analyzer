"""Export Excel as top-anchored modal QDialog (Qt.Sheet fallback)."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from ...ui_kit.dialog_geometry import (
    SCREEN_MARGIN,
    clamp_frame_rect,
    fit_window,
    frame_insets_of,
    resolve_available_rect,
)
from ..dialogs import ExportDialog


class ExportSheet(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("导出 Excel")
        self._inner = ExportDialog(self, chs)
        self._inner.setWindowFlags(Qt.Widget)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._inner)
        self._inner.accepted.connect(self.accept)
        self._inner.rejected.connect(self.reject)
        self._inner.setMinimumSize(0, 0)
        fit_window(
            self,
            (320, 400),
            parent=parent,
            content_minimum=(240, 200),
            clamp_width_to_parent=True,
        )

    def showEvent(self, event):
        parent = self.parent()
        if parent is not None:
            pr = parent.geometry()
            available = resolve_available_rect(widget=self, parent=parent)
            insets = frame_insets_of(self)
            x = pr.left() + (pr.width() - self.width()) // 2
            y = pr.top() + 40
            frame = clamp_frame_rect(
                (x, y, self.width() + insets.horizontal, self.height() + insets.vertical),
                available,
                SCREEN_MARGIN,
            )
            self.resize(frame.width - insets.horizontal, frame.height - insets.vertical)
            self.move(frame.x, frame.y)
        super().showEvent(event)

    def get_selected(self):
        return self._inner.get_selected()

    @property
    def chk_time(self):
        return self._inner.chk_time

    @property
    def chk_range(self):
        return self._inner.chk_range
