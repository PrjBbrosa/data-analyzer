"""Left pane: file list (replacing QTabWidget) + channel tree."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from .icons import Icons
from .widgets import MultiFileChannelWidget


class _FileRow(QFrame):
    activated = pyqtSignal(str)
    close_requested = pyqtSignal(str)

    def __init__(self, fid, fd, parent=None):
        super().__init__(parent)
        self.fid = fid
        self.setObjectName("fileRow")
        self._active = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)
        self._accent = QFrame(self)
        self._accent.setObjectName("fileAccent")
        self._accent.setFixedWidth(3)
        outer.addWidget(self._accent)

        lay = QVBoxLayout()
        lay.setContentsMargins(4, 7, 7, 7)
        lay.setSpacing(3)
        top = QHBoxLayout()
        self._lbl_name = QLabel(fd.short_name)
        self._lbl_name.setObjectName("fileRowName")
        top.addWidget(self._lbl_name, stretch=1)
        self._btn_close = QToolButton()
        self._btn_close.setIcon(Icons.close_file())
        self._btn_close.setIconSize(QSize(13, 13))
        self._btn_close.setToolTip("关闭文件")
        self._btn_close.setProperty("role", "tool")
        self._btn_close.setAutoRaise(True)
        self._btn_close.clicked.connect(lambda: self.close_requested.emit(self.fid))
        top.addWidget(self._btn_close)
        lay.addLayout(top)
        dur = fd.time_array[-1] if len(fd.time_array) else 0
        self._lbl_meta = QLabel(
            f"{len(fd.data)} 行 · {fd.fs:.1f} Hz · {dur:.2f} s"
        )
        self._lbl_meta.setObjectName("fileRowMeta")
        lay.addWidget(self._lbl_meta)
        outer.addLayout(lay, stretch=1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.fid)
        super().mousePressEvent(event)

    def set_active(self, active):
        self._active = active
        self.setProperty("active", "true" if active else "false")
        self._accent.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._accent.style().unpolish(self._accent)
        self._accent.style().polish(self._accent)


class FileNavigator(QWidget):
    file_activated = pyqtSignal(str)
    file_close_requested = pyqtSignal(str)
    close_all_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}        # fid -> _FileRow
        self._active_fid = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        splitter = QSplitter(Qt.Vertical, self)
        splitter.setObjectName("navigatorSplitter")
        lay.addWidget(splitter, stretch=1)

        file_area = QWidget(self)
        file_area.setObjectName("fileArea")
        file_lay = QVBoxLayout(file_area)
        file_lay.setContentsMargins(0, 0, 0, 0)
        file_lay.setSpacing(4)

        # Header with kebab
        head = QHBoxLayout()
        self._lbl_header = QLabel("文件")
        self._lbl_header.setObjectName("paneHeader")
        head.addWidget(self._lbl_header)
        head.addStretch()
        self._lbl_count = QLabel("0")
        self._lbl_count.setObjectName("paneCount")
        head.addWidget(self._lbl_count)
        self._btn_kebab = QToolButton()
        self._btn_kebab.setIcon(Icons.menu())
        self._btn_kebab.setIconSize(QSize(16, 16))
        self._btn_kebab.setToolTip("文件操作")
        self._btn_kebab.setProperty("role", "tool")
        self._btn_kebab.setAutoRaise(True)
        self._btn_kebab.clicked.connect(self._open_kebab)
        head.addWidget(self._btn_kebab)
        file_lay.addLayout(head)

        # File list (scrollable rows)
        self._file_holder = QWidget()
        self._file_layout = QVBoxLayout(self._file_holder)
        self._file_layout.setContentsMargins(0, 0, 0, 0)
        self._file_layout.setSpacing(2)
        self._file_layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("fileScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._file_holder)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(150)
        file_lay.addWidget(scroll, stretch=1)
        splitter.addWidget(file_area)

        # Channel tree
        self.channel_list = MultiFileChannelWidget(self)
        self.channel_list.channels_changed.connect(self.channels_changed)
        self.channel_list.setMinimumHeight(260)
        splitter.addWidget(self.channel_list)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([260, 520])

    # ---- public API used by MainWindow ----
    def add_file(self, fid, fd):
        row = _FileRow(fid, fd, self)
        row.activated.connect(self._activate)
        row.close_requested.connect(self._request_close)
        insert_pos = self._file_layout.count() - 1  # before the stretch
        self._file_layout.insertWidget(insert_pos, row)
        self._rows[fid] = row
        self.channel_list.add_file(fid, fd)
        self._refresh_header()
        self._activate(fid)

    def remove_file(self, fid):
        row = self._rows.pop(fid, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        self.channel_list.remove_file(fid)
        if self._active_fid == fid:
            new_active = next(iter(self._rows), None)
            self._active_fid = None  # force _activate to re-emit
            if new_active is not None:
                self._activate(new_active)
            else:
                # No files left; still notify MainWindow so Inspector resets
                self.file_activated.emit("")
        self._refresh_header()

    def file_list_count(self):
        return len(self._rows)

    def set_active(self, fid):
        self._activate(fid)

    def get_checked_channels(self):
        return self.channel_list.get_checked_channels()

    def get_file_data(self, fid):
        return self.channel_list.get_file_data(fid)

    def check_first_channel(self, fid):
        self.channel_list.check_first_channel(fid)

    # ---- private slots ----
    def _activate(self, fid):
        if fid == self._active_fid:
            return
        if self._active_fid in self._rows:
            self._rows[self._active_fid].set_active(False)
        self._active_fid = fid
        if fid in self._rows:
            self._rows[fid].set_active(True)
        self.file_activated.emit(fid)

    def _request_close(self, fid):
        self.file_close_requested.emit(fid)

    def _open_kebab(self):
        menu = QMenu(self)
        act = menu.addAction("全部关闭…")
        act.setEnabled(bool(self._rows))
        gp = self._btn_kebab.mapToGlobal(self._btn_kebab.rect().bottomLeft())
        chosen = menu.exec_(gp)
        if chosen == act:
            ans = QMessageBox.question(
                self, "确认", f"关闭全部 {len(self._rows)} 文件?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self.close_all_requested.emit()

    def _refresh_header(self):
        self._lbl_count.setText(str(len(self._rows)))
