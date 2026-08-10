"""Left pane: file list (replacing QTabWidget) + channel tree."""
import json

import qtawesome as qta
from PyQt5.QtCore import QMimeData, QPoint, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu,
    QScrollArea, QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from ..ui_kit.icons import Icons
from ..ui_kit.menus import apply_rounded_menu_chrome
from .widgets import INTERNAL_FILE_FIDS_MIME, MultiFileChannelWidget


class _ElidedLabel(QLabel):
    """QLabel that elides its text to fit available width and exposes the full
    string via tooltip when truncation occurs."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text):
        self._full_text = text or ""
        self._apply_elided()

    def full_text(self):
        """The complete (un-elided) string last assigned via ``setText``.

        ``text()`` returns the possibly-elided string actually painted; callers
        and tests that need the logical value should read this instead."""
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elided()

    def _apply_elided(self):
        fm = self.fontMetrics()
        avail = max(0, self.width())
        elided = fm.elidedText(self._full_text, Qt.ElideRight, avail)
        super().setText(elided)
        if elided != self._full_text:
            self.setToolTip(self._full_text)
        else:
            self.setToolTip("")


class _FileRow(QFrame):
    activated = pyqtSignal(str)       # emits primary fid
    close_requested = pyqtSignal(str)  # emits rows_key (filepath_str or fid)
    MIME_TYPE = INTERNAL_FILE_FIDS_MIME

    def __init__(self, fid, fd, parent=None):
        super().__init__(parent)
        # --- fid list (ordered) ---
        self._fids = [fid]
        self._fds = [fd]
        self.fid = fid  # primary fid (backwards compat)
        self._rows_key = fid  # default key; caller may override via _set_rows_key
        self.setObjectName("fileRow")
        self._active = False
        self._drag_start = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        lay = QVBoxLayout()
        # Left inset 14 = former 3px accent stripe + 7 spacing + 4 inner pad,
        # kept so the text column stays put now that the accent frame is gone.
        lay.setContentsMargins(14, 8, 7, 8)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        fp = getattr(fd, "filepath", None)
        if fp is not None:
            full_name = fp.stem
        else:
            full_name = getattr(fd, "filename", "") or getattr(fd, "short_name", "")
        self._lbl_name = _ElidedLabel(full_name)
        self._lbl_name.setObjectName("fileRowName")
        top.addWidget(self._lbl_name, stretch=1)
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24) on the file-row
        # close button. The icon stays 16x16 but the outer chrome was
        # eating ~30px before, dwarfing every other element on the row.
        self._btn_close = QToolButton()
        self._btn_close.setIcon(Icons.close_file())
        self._btn_close.setIconSize(QSize(16, 16))
        self._btn_close.setFixedSize(QSize(24, 24))
        self._btn_close.setToolTip("关闭文件")
        self._btn_close.setAccessibleName("关闭文件")
        self._btn_close.setProperty("role", "icon")
        self._btn_close.setAutoRaise(True)
        self._btn_close.clicked.connect(
            lambda: self.close_requested.emit(self._rows_key)
        )
        top.addWidget(self._btn_close, 0, Qt.AlignVCenter)
        lay.addLayout(top)
        self._lbl_meta = QLabel("")
        self._lbl_meta.setObjectName("fileRowMeta")
        lay.addWidget(self._lbl_meta)
        outer.addLayout(lay, stretch=1)
        self._refresh_meta()

    def _set_rows_key(self, key):
        """Set the key this row emits on close (filepath_str in grouped mode, fid in flat)."""
        self._rows_key = key

    def _refresh_meta(self):
        if len(self._fids) == 1:
            fd = self._fds[0]
            dur = fd.time_array[-1] if fd.time_array is not None and len(fd.time_array) else 0
            self._lbl_meta.setText(
                f"{len(fd.data)} 行 · {fd.fs:.1f} Hz · {dur:.2f} s"
            )
        else:
            # N>1 fids: "N 轨 · fs1k/fs2k Hz · dur s"
            hz_parts = "/".join(f"{fd.fs / 1000:.1f}k" for fd in self._fds)
            max_dur = 0.0
            for fd in self._fds:
                if fd.time_array is not None and len(fd.time_array):
                    max_dur = max(max_dur, fd.time_array[-1])
            self._lbl_meta.setText(
                f"{len(self._fids)} 轨 · {hz_parts} Hz · {max_dur:.2f} s"
            )

    def add_fid(self, fid, fd):
        """Merge a new fid into this group card and refresh the meta label."""
        self._fids.append(fid)
        self._fds.append(fd)
        self._refresh_meta()

    def remove_fid(self, fid):
        """Remove a fid from this group. Returns True if the group is now empty."""
        try:
            idx = self._fids.index(fid)
            self._fids.pop(idx)
            self._fds.pop(idx)
        except ValueError:
            pass
        if self._fids:
            self.fid = self._fids[0]
            self._refresh_meta()
            return False
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = QPoint(event.pos())
            self.activated.emit(self.fid)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            not (event.buttons() & Qt.LeftButton)
            or self._drag_start is None
            or (event.pos() - self._drag_start).manhattanLength()
            < QApplication.startDragDistance()
        ):
            return super().mouseMoveEvent(event)
        self._drag_start = None
        drag = QDrag(self)
        drag.setMimeData(self._build_drag_mime())
        drag.exec_(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _build_drag_mime(self):
        mime = QMimeData()
        mime.setData(
            self.MIME_TYPE,
            json.dumps([str(fid) for fid in self._fids]).encode("utf-8"),
        )
        return mime

    def set_active(self, active):
        self._active = active
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class FileNavigator(QWidget):
    file_activated = pyqtSignal(str)
    file_close_requested = pyqtSignal(str)
    # Physical card close: every logical source in the group, once.
    file_group_close_requested = pyqtSignal(list)
    close_all_requested = pyqtSignal()
    channels_changed = pyqtSignal()
    visibility_changed = pyqtSignal(str, str, bool)
    # Bubbled from the channel tree's 设为左轴 menu: (fid, channel).
    primary_channel_requested = pyqtSignal(str, str)
    channel_context_menu_requested = pyqtSignal()
    # Bubbled from the channel pane's 编辑通道 button.
    channel_editor_requested = pyqtSignal()
    files_attach_requested = pyqtSignal(object)
    files_detach_requested = pyqtSignal(object, str)
    # Item-1 shim: still emitted when attach_on_load flips so older callers
    # (and tests) keep working without knowing about the follow menu.
    auto_attach_changed = pyqtSignal(bool)
    # Stage 1.1: full follow-prefs payload (FollowPrefs dataclass).
    follow_prefs_changed = pyqtSignal(object)
    channel_config_save_requested = pyqtSignal()
    channel_config_apply_requested = pyqtSignal(str)
    channel_config_manage_requested = pyqtSignal(object)
    channel_config_selection_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # QSS (FileNavigator { border-radius:10px; background:#fff }) only paints
        # on a plain QWidget subclass once WA_StyledBackground is set; without it
        # Qt skips the styled fill/border and the rounded card never renders.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        # rows_key -> _FileRow
        # rows_key = filepath_str when label_suffix is non-empty (grouped mode)
        # rows_key = fid when label_suffix is empty (flat mode, backwards compat)
        self._rows = {}
        # fid -> rows_key
        self._fid_to_key = {}
        self._active_fid = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(4)

        splitter = QSplitter(Qt.Vertical, self)
        splitter.setObjectName("navigatorSplitter")
        lay.addWidget(splitter, stretch=1)

        file_area = QWidget(self)
        file_area.setObjectName("fileArea")
        # QWidget#fileArea { background:#fff } needs WA_StyledBackground too,
        # otherwise the inner white surface above the channel splitter is unpainted.
        file_area.setAttribute(Qt.WA_StyledBackground, True)
        file_lay = QVBoxLayout(file_area)
        file_lay.setContentsMargins(8, 0, 8, 8)
        file_lay.setSpacing(4)

        # Header with kebab
        head = QHBoxLayout()
        head.setContentsMargins(10, 6, 6, 4)
        head.setSpacing(8)
        self._lbl_header = QLabel("文件")
        self._lbl_header.setObjectName("paneHeader")
        head.addWidget(self._lbl_header)
        head.addStretch()
        self._lbl_count = QLabel("0")
        self._lbl_count.setObjectName("paneCount")
        head.addWidget(self._lbl_count)
        self.btn_auto_attach = QToolButton()
        self.btn_auto_attach.setObjectName("autoAttachFiles")
        self.btn_auto_attach.setIconSize(QSize(16, 16))
        self.btn_auto_attach.setFixedSize(QSize(24, 24))
        self.btn_auto_attach.setProperty("role", "icon")
        self.btn_auto_attach.setAutoRaise(True)
        # Same chrome as the kebab: icon-only click opens a menu. Do not use
        # InstantPopup+setMenu — that paints the gray dropdown triangle.
        self._follow_menu = apply_rounded_menu_chrome(
            QMenu(self.btn_auto_attach), gutter="check"
        )
        self._act_attach_on_load = self._follow_menu.addAction("新文件加入当前 View")
        self._act_attach_on_load.setCheckable(True)
        self._act_attach_on_load.setChecked(True)
        self._act_inherit_on_new_view = self._follow_menu.addAction(
            "新建 View 继承文件范围"
        )
        self._act_inherit_on_new_view.setCheckable(True)
        self._act_inherit_on_new_view.setChecked(False)
        self._act_fill_on_mode_entry = self._follow_menu.addAction(
            "切换分析时填充空 View"
        )
        self._act_fill_on_mode_entry.setCheckable(True)
        self._act_fill_on_mode_entry.setChecked(False)
        for act in (
            self._act_attach_on_load,
            self._act_inherit_on_new_view,
            self._act_fill_on_mode_entry,
        ):
            act.toggled.connect(self._on_follow_action_toggled)
        self.btn_auto_attach.clicked.connect(self._open_follow_menu)
        self._sync_auto_attach_button()
        head.addWidget(self.btn_auto_attach)
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24) — same as
        # _btn_close above; kebab is admin-only and shouldn't dwarf the
        # "文件" header label.
        self._btn_kebab = QToolButton()
        self._btn_kebab.setIcon(Icons.menu())
        self._btn_kebab.setIconSize(QSize(16, 16))
        self._btn_kebab.setFixedSize(QSize(24, 24))
        self._btn_kebab.setToolTip("文件操作")
        self._btn_kebab.setAccessibleName("文件操作")
        self._btn_kebab.setProperty("role", "icon")
        self._btn_kebab.setAutoRaise(True)
        self._btn_kebab.clicked.connect(self._open_kebab)
        head.addWidget(self._btn_kebab)
        file_lay.addLayout(head)

        # File list (scrollable rows)
        self._file_holder = QWidget()
        self._file_holder.setAutoFillBackground(False)
        self._file_holder.setAttribute(Qt.WA_TranslucentBackground, True)
        self._file_holder.setAttribute(Qt.WA_NoSystemBackground, True)
        self._file_layout = QVBoxLayout(self._file_holder)
        self._file_layout.setContentsMargins(0, 0, 0, 0)
        self._file_layout.setSpacing(2)
        self._file_layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("fileScroll")
        scroll.setAttribute(Qt.WA_StyledBackground, True)
        scroll.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        scroll.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._file_holder)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(150)
        file_lay.addWidget(scroll, stretch=1)
        splitter.addWidget(file_area)

        # Channel tree
        self.channel_list = MultiFileChannelWidget(self)
        self.channel_list.channels_changed.connect(self.channels_changed)
        self.channel_list.visibility_changed.connect(self.visibility_changed)
        self.channel_list.primary_channel_requested.connect(
            self.primary_channel_requested
        )
        self.channel_list.channel_context_menu_requested.connect(
            self.channel_context_menu_requested
        )
        self.channel_list.channel_editor_requested.connect(
            self.channel_editor_requested
        )
        self.channel_list.files_attach_requested.connect(
            self.files_attach_requested
        )
        self.channel_list.files_detach_requested.connect(
            self.files_detach_requested
        )
        config_bar = self.channel_list.config_bar
        config_bar.save_requested.connect(self.channel_config_save_requested)
        config_bar.apply_requested.connect(self.channel_config_apply_requested)
        config_bar.manage_requested.connect(self.channel_config_manage_requested)
        config_bar.selection_changed.connect(
            self.channel_config_selection_changed
        )
        self.channel_list.setMinimumHeight(260)
        splitter.addWidget(self.channel_list)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([260, 520])

    # ---- public API used by MainWindow ----
    def add_file(self, fid, fd):
        label_suffix = getattr(fd, 'label_suffix', '')
        fp = getattr(fd, 'filepath', None)

        if label_suffix and fp is not None:
            # GROUPED MODE: use filepath_str as the rows key
            fp_str = str(fp)
            if fp_str in self._rows:
                # Add to existing group card
                self._rows[fp_str].add_fid(fid, fd)
                self._fid_to_key[fid] = fp_str
            else:
                # Create new group card
                row = _FileRow(fid, fd, self)
                row._set_rows_key(fp_str)
                row.activated.connect(self._activate)
                row.close_requested.connect(self._request_close_group)
                insert_pos = self._file_layout.count() - 1  # before the stretch
                self._file_layout.insertWidget(insert_pos, row)
                self._rows[fp_str] = row
                self._fid_to_key[fid] = fp_str
        else:
            # FLAT MODE: use fid as the rows key (backwards compat)
            row = _FileRow(fid, fd, self)
            row._set_rows_key(fid)
            row.activated.connect(self._activate)
            row.close_requested.connect(self._request_close_group)
            insert_pos = self._file_layout.count() - 1  # before the stretch
            self._file_layout.insertWidget(insert_pos, row)
            self._rows[fid] = row
            self._fid_to_key[fid] = fid

        self.channel_list.add_file(fid, fd)
        self._refresh_header()
        self._activate(fid)

    def refresh_file(self, fid, fd):
        """Refresh channel rows for an existing file without changing cards."""
        self.channel_list.refresh_file(fid, fd)

    def remove_file(self, fid, *, emit=True):
        rows_key = self._fid_to_key.pop(fid, None)
        if rows_key is not None:
            row = self._rows.get(rows_key)
            if row is not None:
                empty = row.remove_fid(fid)
                if empty:
                    self._rows.pop(rows_key)
                    row.setParent(None)
                    row.deleteLater()
        self.channel_list.remove_file(fid, emit=emit)
        if self._active_fid == fid:
            remaining = list(self._fid_to_key.keys())
            new_active = remaining[0] if remaining else None
            self._active_fid = None
            if new_active is not None:
                self._activate(new_active)
            else:
                self.file_activated.emit("")
        self._refresh_header()

    def file_list_count(self):
        """Returns the number of unique source file cards (not fid count)."""
        return len(self._rows)

    def set_active(self, fid):
        self._activate(fid)

    def get_checked_channels(self):
        return self.channel_list.get_checked_channels()

    def set_checked_channels(self, checked):
        self.channel_list.set_checked_channels(checked)

    def get_attached_file_ids(self):
        return self.channel_list.get_attached_file_ids()

    def set_attached_file_ids(self, fids):
        self.channel_list.set_attached_file_ids(fids)

    def auto_attach_enabled(self):
        """Item-1 shim: whether new loads attach into the active context."""
        return self._act_attach_on_load.isChecked()

    def set_auto_attach_enabled(self, enabled):
        """Item-1 shim: update attach_on_load without emitting prefs signals."""
        blocker = QSignalBlocker(self._act_attach_on_load)
        self._act_attach_on_load.setChecked(bool(enabled))
        del blocker
        self._sync_auto_attach_button()

    def follow_prefs(self):
        from .main_window.file_scope_follow import FollowPrefs

        return FollowPrefs(
            attach_on_load=self._act_attach_on_load.isChecked(),
            inherit_on_new_view=self._act_inherit_on_new_view.isChecked(),
            fill_on_mode_entry=self._act_fill_on_mode_entry.isChecked(),
        )

    def set_follow_prefs(self, prefs):
        """Apply FollowPrefs (or duck-typed equivalent) without emitting."""
        blockers = [
            QSignalBlocker(self._act_attach_on_load),
            QSignalBlocker(self._act_inherit_on_new_view),
            QSignalBlocker(self._act_fill_on_mode_entry),
        ]
        self._act_attach_on_load.setChecked(bool(getattr(prefs, "attach_on_load", True)))
        self._act_inherit_on_new_view.setChecked(
            bool(getattr(prefs, "inherit_on_new_view", False))
        )
        self._act_fill_on_mode_entry.setChecked(
            bool(getattr(prefs, "fill_on_mode_entry", False))
        )
        del blockers
        self._sync_auto_attach_button()

    def get_hidden_channels(self):
        return self.channel_list.get_hidden_channels()

    def set_hidden_channels(self, hidden):
        self.channel_list.set_hidden_channels(hidden)

    def get_visible_checked_channels(self):
        return self.channel_list.get_visible_checked_channels()

    def set_channel_visible(self, fid, channel, visible, *, emit=True):
        return self.channel_list.set_channel_visible(
            fid, channel, visible, emit=emit
        )

    def set_time_visibility_available(self, available):
        self.channel_list.set_time_visibility_available(available)

    def projection_role(self):
        return self.channel_list.projection_role()

    def set_projection_role(self, role):
        self.channel_list.set_projection_role(role)

    def set_empty_state_context(self, *, section_label=None, view_name=None):
        self.channel_list.set_empty_state_context(
            section_label=section_label, view_name=view_name
        )

    def get_channel_colors(self):
        return self.channel_list.get_channel_colors()

    def set_channel_colors(self, colors):
        self.channel_list.set_channel_colors(colors)

    def get_file_data(self, fid):
        return self.channel_list.get_file_data(fid)

    def check_first_channel(self, fid):
        self.channel_list.check_first_channel(fid)

    # ---- private slots ----
    def _activate(self, fid):
        if fid == self._active_fid:
            return
        # Deactivate old active row
        if self._active_fid is not None:
            old_key = self._fid_to_key.get(self._active_fid)
            if old_key is not None and old_key in self._rows:
                new_key = self._fid_to_key.get(fid)
                if old_key != new_key:
                    self._rows[old_key].set_active(False)
        self._active_fid = fid
        new_key = self._fid_to_key.get(fid)
        if new_key is not None and new_key in self._rows:
            self._rows[new_key].set_active(True)
        self.file_activated.emit(fid)

    def _on_follow_action_toggled(self, _checked=False):
        prefs = self.follow_prefs()
        self._sync_auto_attach_button()
        self.follow_prefs_changed.emit(prefs)
        # Keep the legacy bool signal in sync with item 1 for older callers.
        self.auto_attach_changed.emit(bool(prefs.attach_on_load))

    def _sync_auto_attach_button(self):
        # Read actions directly so chrome sync never imports main_window.
        flags = (
            self._act_attach_on_load.isChecked(),
            self._act_inherit_on_new_view.isChecked(),
            self._act_fill_on_mode_entry.isChecked(),
        )
        enabled = any(flags)
        count = sum(1 for flag in flags if flag)
        self.btn_auto_attach.setIcon(qta.icon(
            "mdi.link-variant" if enabled else "mdi.link-variant-off",
            color="#4b6078" if enabled else "#8b98aa",
        ))
        self.btn_auto_attach.setToolTip(
            f"已启用 {count} 项文件范围跟随 · 点击调整"
            if enabled
            else "未启用文件范围跟随"
        )
        self.btn_auto_attach.setAccessibleName(self.btn_auto_attach.toolTip())
        self.btn_auto_attach.setProperty("active", enabled)
        self.btn_auto_attach.style().unpolish(self.btn_auto_attach)
        self.btn_auto_attach.style().polish(self.btn_auto_attach)

    def _request_close_group(self, rows_key):
        """Emit one group-close request for ALL fids under ``rows_key``.

        Physical-card close must be atomic: MainWindow aggregates dependencies
        once and either keeps or unloads every logical source together.
        """
        fids = [f for f, k in self._fid_to_key.items() if k == rows_key]
        if not fids:
            return
        self.file_group_close_requested.emit(list(fids))

    # Backwards-compat alias used by existing tests that call _request_close(fid)
    def _request_close(self, fid):
        rows_key = self._fid_to_key.get(fid, fid)
        fids = [f for f, k in self._fid_to_key.items() if k == rows_key]
        if len(fids) > 1:
            self.file_group_close_requested.emit(list(fids))
            return
        target = fids[0] if fids else fid
        self.file_close_requested.emit(target)

    def _open_follow_menu(self):
        """Open the follow prefs menu under the link icon (no dropdown triangle)."""
        btn = self.btn_auto_attach
        gp = btn.mapToGlobal(btn.rect().bottomLeft())
        self._follow_menu.exec_(gp)

    def _open_kebab(self):
        menu = apply_rounded_menu_chrome(QMenu(self))
        act = menu.addAction("全部关闭…")
        act.setEnabled(bool(self._rows))
        gp = self._btn_kebab.mapToGlobal(self._btn_kebab.rect().bottomLeft())
        chosen = menu.exec_(gp)
        if chosen == act:
            # Confirm lives in MainWindow.close_all so dependency preflight
            # and close-all share one product dialog.
            self.close_all_requested.emit()

    def _refresh_header(self):
        self._lbl_count.setText(str(len(self._rows)))
