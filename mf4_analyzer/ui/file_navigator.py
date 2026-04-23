"""Left pane: file list (replacing QTabWidget) + channel tree.

Phase 1 skeleton: wraps existing MultiFileChannelWidget unchanged; the
file-list UI and visual redesign land in Phase 2.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from .widgets import MultiFileChannelWidget


class FileNavigator(QWidget):
    file_activated = pyqtSignal(str)           # fid
    file_close_requested = pyqtSignal(str)     # fid
    close_all_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.lbl_files = QLabel("文件 (0)", self)
        lay.addWidget(self.lbl_files)
        # Phase 1: file list is a placeholder; Phase 2 replaces with real list
        self.channel_list = MultiFileChannelWidget(self)
        lay.addWidget(self.channel_list, stretch=1)
        self.channel_list.channels_changed.connect(self.channels_changed)

    # ---- API used by MainWindow --------------------------------------
    def add_file(self, fid, fd):
        self.channel_list.add_file(fid, fd)
        self._refresh_count()

    def remove_file(self, fid):
        self.channel_list.remove_file(fid)
        self._refresh_count()

    def get_checked_channels(self):
        return self.channel_list.get_checked_channels()

    def get_file_data(self, fid):
        return self.channel_list.get_file_data(fid)

    def check_first_channel(self, fid):
        self.channel_list.check_first_channel(fid)

    def _refresh_count(self):
        n = len(self.channel_list._file_items)
        self.lbl_files.setText(f"文件 ({n})")
