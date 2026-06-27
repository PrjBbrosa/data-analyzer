"""DropImportMixin: file drag and drop import for MainWindow.

Dropped files use the same ProjectIOMixin._open_paths dispatch path as the
Open action. The visual overlay is added separately after the functional path.
"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from ._project_io_mixin import DATA_FILE_GLOB


SUPPORTED_DROP_EXTS = {
    tok.lower().lstrip("*") for tok in DATA_FILE_GLOB.split()
} | {".tlproj"}


class DropImportMixin:
    """Domain mixin: file drag and drop import."""

    def _init_drop_import(self):
        self.setAcceptDrops(True)
        self._drop_overlay = None

    def _show_drop_overlay(self):
        central = self.centralWidget()
        if central is None:
            return
        if self._drop_overlay is None:
            self._drop_overlay = _DropOverlay(central)
        self._drop_overlay.setGeometry(central.rect())
        self._drop_overlay.raise_()
        self._drop_overlay.show()

    def _hide_drop_overlay(self):
        if self._drop_overlay is not None:
            self._drop_overlay.hide()

    def _has_supported_urls(self, mime):
        if not mime.hasUrls():
            return False
        for url in mime.urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in SUPPORTED_DROP_EXTS:
                return True
        return False

    def _dropped_paths(self, mime):
        paths = []
        if not mime.hasUrls():
            return paths
        for url in mime.urls():
            path = url.toLocalFile()
            if not path:
                continue
            parsed = Path(path)
            if parsed.is_file() and parsed.suffix.lower() in SUPPORTED_DROP_EXTS:
                paths.append(path)
        return paths

    def dragEnterEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_overlay()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._hide_drop_overlay()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._hide_drop_overlay()
        mime = event.mimeData()
        paths = self._dropped_paths(mime)
        total = (
            sum(1 for url in mime.urls() if url.toLocalFile())
            if mime.hasUrls()
            else 0
        )
        if paths:
            event.acceptProposedAction()
            self._open_paths(paths)
        else:
            event.ignore()
        skipped = total - len(paths)
        if skipped > 0:
            self.toast(f"忽略 {skipped} 个不支持的文件", "warning")


class _DropOverlay(QWidget):
    """Whole-window drop highlight overlay painted without stylesheet fill."""

    _ACCENT = QColor(37, 99, 235)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()

        fill = QColor(self._ACCENT)
        fill.setAlpha(30)
        painter.fillRect(rect, fill)

        pen = QPen(self._ACCENT, 2, Qt.DashLine)
        painter.setPen(pen)
        inset = rect.adjusted(10, 10, -10, -10)
        painter.drawRoundedRect(inset, 12, 12)

        font = QFont(self.font())
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._ACCENT)
        painter.drawText(rect, Qt.AlignCenter, "松手导入文件")
        painter.end()
