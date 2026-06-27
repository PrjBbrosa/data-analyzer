"""DropImportMixin: file drag and drop import for MainWindow.

Dropped files use the same ProjectIOMixin._open_paths dispatch path as the
Open action. The visual overlay is added separately after the functional path.
"""

from pathlib import Path

from PyQt5.QtCore import Qt

from ._project_io_mixin import DATA_FILE_GLOB


SUPPORTED_DROP_EXTS = {
    tok.lower().lstrip("*") for tok in DATA_FILE_GLOB.split()
} | {".tlproj"}


class DropImportMixin:
    """Domain mixin: file drag and drop import."""

    def _init_drop_import(self):
        self.setAcceptDrops(True)
        self._drop_overlay = None

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
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        paths = self._dropped_paths(mime)
        total = sum(1 for url in mime.urls() if url.toLocalFile()) if mime.hasUrls() else 0
        if paths:
            event.acceptProposedAction()
            self._open_paths(paths)
        else:
            event.ignore()
        skipped = total - len(paths)
        if skipped > 0:
            self.toast(f"忽略 {skipped} 个不支持的文件", "warning")
