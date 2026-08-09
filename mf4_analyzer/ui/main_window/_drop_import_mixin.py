"""DropImportMixin: file drag and drop import for MainWindow.

Dropped files use the same ProjectIOMixin._open_paths dispatch path as the
Open action. The visual overlay is added separately after the functional path.
"""

from ..drop_paths import (
    DropOverlay,
    filter_drop_files,
    has_supported_drop_suffix,
    iter_local_paths,
)
from ._project_io_mixin import DATA_FILE_GLOB


SUPPORTED_DROP_EXTS = {
    tok.lower().lstrip("*") for tok in DATA_FILE_GLOB.split()
} | {".tlproj"}

# Re-export so existing tests / imports of the private overlay name keep working.
_DropOverlay = DropOverlay


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
            self._drop_overlay = DropOverlay(central, message="松手导入文件")
        self._drop_overlay.setGeometry(central.rect())
        self._drop_overlay.raise_()
        self._drop_overlay.show()

    def _hide_drop_overlay(self):
        if self._drop_overlay is not None:
            self._drop_overlay.hide()

    def _has_supported_urls(self, mime):
        return has_supported_drop_suffix(
            iter_local_paths(mime), suffixes=SUPPORTED_DROP_EXTS,
        )

    def _dropped_paths(self, mime):
        return filter_drop_files(
            iter_local_paths(mime), suffixes=SUPPORTED_DROP_EXTS,
        )

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
        total = len(iter_local_paths(mime))
        if paths:
            event.acceptProposedAction()
            self._open_paths(paths)
        else:
            event.ignore()
        skipped = total - len(paths)
        if skipped > 0:
            self.toast(f"忽略 {skipped} 个不支持的文件", "warning")
