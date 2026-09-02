"""HTML-parity, draft-first manager for saved TimeDomain channel configs."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..channel_config import ChannelConfigPreview, ChannelSelectionConfig
from ...ui_kit.control_style import CONTROL_HEIGHTS
from ...ui_kit.dialog_button_defaults import set_unique_default_button
from ...ui_kit.menus import apply_rounded_menu_chrome
from ...ui_kit.widgets import SearchField
from ..channel_config_transfer import (
    TRANSFER_SUFFIX,
    ImportMergeResult,
    merge_import,
    parse_transfer,
    serialize_transfer,
)


def _display_updated(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


class _ConfigRow(QFrame):
    """A 64px sidebar configuration card matching the approved HTML list."""

    clicked = pyqtSignal(str)
    batch_toggled = pyqtSignal(str, bool)
    delete_requested = pyqtSignal(str)

    def __init__(
        self,
        config: ChannelSelectionConfig,
        *,
        active: bool,
        batch_mode: bool,
        checked: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.config_id = config.config_id
        self.setObjectName("channelConfigHtmlConfigRow")
        self.setProperty("active", bool(active))
        self.setProperty("batch", bool(batch_mode))
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(config.name)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        self.checkbox = None
        if batch_mode:
            self.checkbox = QCheckBox(self)
            self.checkbox.setObjectName("channelConfigHtmlCheck")
            self.checkbox.setAccessibleName(f"批量选择 {config.name}")
            self.checkbox.setFixedSize(20, 20)
            self.checkbox.setFocusPolicy(Qt.StrongFocus)
            self.checkbox.setChecked(checked)
            self.checkbox.toggled.connect(
                lambda selected, config_id=config.config_id: self.batch_toggled.emit(
                    config_id, selected
                )
            )
            self.checkbox.installEventFilter(self)
            layout.addWidget(self.checkbox, 0, Qt.AlignVCenter)
        copy = QWidget(self)
        copy.setObjectName("channelConfigHtmlConfigCopy")
        copy.setFocusPolicy(Qt.NoFocus)
        copy_layout = QVBoxLayout(copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(4)
        self.name_label = QLabel(config.name, copy)
        self.name_label.setObjectName("channelConfigHtmlConfigName")
        self.name_label.setToolTip(config.name)
        self.name_label.setWordWrap(False)
        self.meta_label = QLabel(f"更新于 {_display_updated(config.updated_at)}", copy)
        self.meta_label.setObjectName("channelConfigHtmlConfigMeta")
        copy_layout.addWidget(self.name_label)
        copy_layout.addWidget(self.meta_label)
        layout.addWidget(copy, 1)
        self.count_label = QLabel(f"{len(config.channel_names)} CH", self)
        self.count_label.setObjectName("channelConfigHtmlConfigCount")
        layout.addWidget(self.count_label, 0, Qt.AlignVCenter)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.checkbox and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (
                Qt.Key_Delete,
                Qt.Key_Backspace,
                Qt.Key_Up,
                Qt.Key_Down,
                Qt.Key_Return,
                Qt.Key_Enter,
            ):
                self.keyPressEvent(event)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit(self.config_id)
            event.accept()
            return
        if key == Qt.Key_Space:
            if self.checkbox is not None:
                self.checkbox.toggle()
            else:
                self.clicked.emit(self.config_id)
            event.accept()
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_requested.emit(self.config_id)
            event.accept()
            return
        if key in (Qt.Key_Up, Qt.Key_Down):
            self._move_neighbor_focus(-1 if key == Qt.Key_Up else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_neighbor_focus(self, delta: int) -> None:
        host = self.parentWidget()
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            return
        rows = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, _ConfigRow):
                rows.append(widget)
        try:
            current = rows.index(self)
        except ValueError:
            return
        target = current + delta
        if 0 <= target < len(rows):
            rows[target].setFocus(Qt.TabFocusReason)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.config_id)
        super().mouseReleaseEvent(event)


class ChannelConfigManagerDialog(QDialog):
    """Mirror the approved HTML operations; persist only on Save changes."""

    save_requested = pyqtSignal(object)

    CONTROL_HEIGHT = CONTROL_HEIGHTS["base"]
    ICON_SIZE = 36

    def __init__(
        self,
        configs: Iterable[ChannelSelectionConfig],
        *,
        selected_id: str | None = None,
        preview: ChannelConfigPreview | None = None,
        checked_channel_hints: Mapping[str, str] | None = None,
        id_factory: Callable[[], str] | None = None,
        open_file: Callable[[], str] | None = None,
        save_file: Callable[[str], str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("channelConfigManagerHtml")
        self.setWindowTitle("管理通道配置")
        self.setModal(True)
        self.resize(1180, 680)
        self.setMinimumSize(940, 680)

        self._baseline = list(configs)
        self._drafts = list(configs)
        self._preview = preview or ChannelConfigPreview(0, frozenset(), (), frozenset())
        self._checked_channel_hints = {
            str(name): str(unit or "")
            for name, unit in (checked_channel_hints or {}).items()
        }
        self._id_factory = id_factory or self._fallback_id
        self._open_file = open_file or self._open_import_file
        self._save_file = save_file or self._save_export_file
        self._active_id = self._initial_active_id(selected_id)
        self._batch_mode = False
        self._batch_config_ids: set[str] = set()
        self._chosen_channels: set[str] = set()
        self._undo_callback: Callable[[], None] | None = None
        self._closing = False
        self._config_rows: dict[str, _ConfigRow] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_workspace(), 1)
        self._build_toast()
        self._rebuild_all()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and obj in (
                self.config_search,
                self.channel_search,
            ):
                event.accept()
                return True
            if self._handle_channel_table_key(obj, event):
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _fallback_id() -> str:
        import uuid

        return uuid.uuid4().hex

    def _initial_active_id(self, selected_id: str | None) -> str | None:
        valid = {config.config_id for config in self._drafts}
        if selected_id in valid:
            return str(selected_id)
        return self._drafts[0].config_id if self._drafts else None

    def _build_header(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("channelConfigHtmlHeader")
        frame.setFixedHeight(88)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(18)
        copy = QWidget(frame)
        copy_layout = QVBoxLayout(copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(5)
        title = QLabel("通道配置", copy)
        title.setObjectName("channelConfigHtmlTitle")
        subtitle = QLabel(
            "选择一个配置查看并调整通道；保存后，应用时按通道名称匹配当前 View 内的文件。",
            copy,
        )
        subtitle.setObjectName("channelConfigHtmlSubtitle")
        copy_layout.addWidget(title)
        copy_layout.addWidget(subtitle)
        layout.addWidget(copy, 1)
        self.config_summary = QLabel(frame)
        self.config_summary.setObjectName("channelConfigHtmlSummaryToken")
        self.config_summary.setFixedHeight(28)
        self.config_summary.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout.addWidget(self.config_summary, 0, Qt.AlignVCenter)
        self.view_summary = QLabel(frame)
        self.view_summary.setObjectName("channelConfigHtmlSummaryToken")
        self.view_summary.setFixedHeight(28)
        self.view_summary.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout.addWidget(self.view_summary, 0, Qt.AlignVCenter)
        return frame

    def _build_workspace(self) -> QWidget:
        workspace = QWidget(self)
        workspace.setObjectName("channelConfigHtmlWorkspace")
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar, 0)
        layout.addWidget(self._build_detail(), 1)
        return workspace

    def _build_sidebar(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("channelConfigHtmlSidebar")
        panel.setFixedWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tools = QFrame(panel)
        tools.setObjectName("channelConfigHtmlSideTools")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(16, 16, 16, 12)
        tools_layout.setSpacing(11)
        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        side_title = QLabel("已保存配置", tools)
        side_title.setObjectName("channelConfigHtmlSideTitle")
        title_row.addWidget(side_title)
        self.config_count = QLabel(tools)
        self.config_count.setObjectName("channelConfigHtmlCountPill")
        title_row.addWidget(self.config_count)
        title_row.addStretch(1)
        self.btn_import = QPushButton("导入", tools)
        self._control(self.btn_import)
        self.btn_import.clicked.connect(self._import_from_file)
        title_row.addWidget(self.btn_import)
        self.btn_new = QPushButton("＋ 新建", tools)
        self._control(self.btn_new)
        self.btn_new.clicked.connect(self._create_from_checked)
        title_row.addWidget(self.btn_new)
        tools_layout.addLayout(title_row)
        self.config_search = SearchField("搜索配置…", tools)
        self.config_search.setObjectName("channelConfigHtmlConfigSearch")
        self.config_search.textChanged.connect(self._rebuild_config_rows)
        self.config_search.installEventFilter(self)
        tools_layout.addWidget(self.config_search)
        layout.addWidget(tools)

        self.config_scroll = QScrollArea(panel)
        self.config_scroll.setObjectName("channelConfigHtmlConfigScroll")
        self.config_scroll.setWidgetResizable(True)
        self.config_scroll.setFrameShape(QFrame.NoFrame)
        self.config_list = QWidget(self.config_scroll)
        self.config_list.setObjectName("channelConfigHtmlConfigList")
        self.config_list_layout = QVBoxLayout(self.config_list)
        self.config_list_layout.setContentsMargins(8, 8, 8, 8)
        self.config_list_layout.setSpacing(4)
        self.config_list_layout.addStretch(1)
        self.config_scroll.setWidget(self.config_list)
        layout.addWidget(self.config_scroll, 1)

        footer = QFrame(panel)
        footer.setObjectName("channelConfigHtmlSideFooter")
        footer.setFixedHeight(60)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 11, 16, 11)
        footer_layout.setSpacing(8)
        self.btn_batch = QPushButton("批量管理配置", footer)
        self._control(self.btn_batch)
        self.btn_batch.setProperty("role", "quiet")
        self.btn_batch.clicked.connect(self._enter_batch_mode)
        footer_layout.addWidget(self.btn_batch)
        self.batch_actions = QWidget(footer)
        batch_layout = QHBoxLayout(self.batch_actions)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(8)
        self.btn_exit_batch = QPushButton("退出批量", self.batch_actions)
        self._control(self.btn_exit_batch)
        self.btn_exit_batch.clicked.connect(self._exit_batch_mode)
        batch_layout.addWidget(self.btn_exit_batch)
        self.btn_delete_configs = QPushButton("删除所选", self.batch_actions)
        self.btn_delete_configs.setObjectName("channelConfigHtmlDeleteConfigs")
        self.btn_delete_configs.setProperty("role", "danger")
        self._control(self.btn_delete_configs)
        self.btn_delete_configs.clicked.connect(self._delete_batch_configs)
        batch_layout.addWidget(self.btn_delete_configs)
        footer_layout.addWidget(self.batch_actions, 1)
        layout.addWidget(footer)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("channelConfigHtmlDetail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QFrame(panel)
        head.setObjectName("channelConfigHtmlDetailHead")
        head.setMinimumHeight(80)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(20, 15, 20, 15)
        head_layout.setSpacing(12)
        copy = QWidget(head)
        copy_layout = QVBoxLayout(copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.detail_title = QLabel(copy)
        self.detail_title.setObjectName("channelConfigHtmlDetailTitle")
        title_row.addWidget(self.detail_title)
        self.dirty_dot = QLabel(copy)
        self.dirty_dot.setObjectName("channelConfigHtmlDirtyDot")
        self.dirty_dot.setFixedSize(7, 7)
        title_row.addWidget(self.dirty_dot)
        title_row.addStretch(1)
        copy_layout.addLayout(title_row)
        self.detail_meta = QLabel(copy)
        self.detail_meta.setObjectName("channelConfigHtmlDetailMeta")
        copy_layout.addWidget(self.detail_meta)
        head_layout.addWidget(copy, 1)
        self.btn_export = QToolButton(head)
        self.btn_export.setObjectName("channelConfigHtmlExport")
        self.btn_export.setText("导出 ▾")
        self.btn_export.setPopupMode(QToolButton.InstantPopup)
        self._control(self.btn_export)
        self.btn_export.setMenu(self._build_export_menu())
        head_layout.addWidget(self.btn_export)
        self.btn_rename = QPushButton("重命名", head)
        self._control(self.btn_rename)
        self.btn_rename.clicked.connect(self._open_rename_dialog)
        head_layout.addWidget(self.btn_rename)
        self.btn_copy = QPushButton("复制", head)
        self._control(self.btn_copy)
        self.btn_copy.clicked.connect(self._copy_active)
        head_layout.addWidget(self.btn_copy)
        self.btn_delete_config = QPushButton("删除配置", head)
        self.btn_delete_config.setObjectName("channelConfigHtmlDeleteConfig")
        self.btn_delete_config.setProperty("role", "danger")
        self._control(self.btn_delete_config)
        self.btn_delete_config.clicked.connect(self._delete_active_config)
        head_layout.addWidget(self.btn_delete_config)
        layout.addWidget(head)

        preview = QFrame(panel)
        preview.setObjectName("channelConfigHtmlPreview")
        preview.setFixedHeight(58)
        preview_layout = QHBoxLayout(preview)
        preview_layout.setContentsMargins(20, 10, 20, 10)
        preview_layout.setSpacing(9)
        label = QLabel("应用到当前 View", preview)
        label.setObjectName("channelConfigHtmlPreviewLabel")
        preview_layout.addWidget(label)
        self.match_chip = QLabel(preview)
        self.match_chip.setObjectName("channelConfigHtmlMatchChip")
        self.match_chip.setFixedHeight(28)
        preview_layout.addWidget(self.match_chip)
        self.missing_chip = QLabel(preview)
        self.missing_chip.setObjectName("channelConfigHtmlMissingChip")
        self.missing_chip.setFixedHeight(28)
        preview_layout.addWidget(self.missing_chip)
        preview_layout.addStretch(1)
        note = QLabel("缺失通道会跳过，不影响其他通道", preview)
        note.setObjectName("channelConfigHtmlPreviewNote")
        preview_layout.addWidget(note)
        layout.addWidget(preview)

        tools = QFrame(panel)
        tools.setObjectName("channelConfigHtmlChannelTools")
        tools.setFixedHeight(61)
        tools_layout = QHBoxLayout(tools)
        tools_layout.setContentsMargins(20, 12, 20, 12)
        tools_layout.setSpacing(8)
        self.channel_search = SearchField("搜索通道…", tools)
        self.channel_search.setObjectName("channelConfigHtmlChannelSearch")
        self.channel_search.setMaximumWidth(280)
        self.channel_search.textChanged.connect(self._rebuild_channel_rows)
        self.channel_search.installEventFilter(self)
        tools_layout.addWidget(self.channel_search)
        self.btn_select_channels = QPushButton("全选", tools)
        self._control(self.btn_select_channels)
        self.btn_select_channels.clicked.connect(self._select_visible_channels)
        tools_layout.addWidget(self.btn_select_channels)
        self.btn_clear_channels = QPushButton("清除选择", tools)
        self._control(self.btn_clear_channels)
        self.btn_clear_channels.clicked.connect(self._clear_channel_selection)
        tools_layout.addWidget(self.btn_clear_channels)
        self.btn_remove_channels = QPushButton("移除所选", tools)
        self.btn_remove_channels.setObjectName("channelConfigHtmlRemoveChannels")
        self.btn_remove_channels.setProperty("role", "danger")
        self._control(self.btn_remove_channels)
        self.btn_remove_channels.clicked.connect(self._remove_selected_channels)
        tools_layout.addWidget(self.btn_remove_channels)
        tools_layout.addStretch(1)
        self.btn_add_current = QPushButton("＋ 添加当前勾选", tools)
        self._control(self.btn_add_current)
        self.btn_add_current.clicked.connect(self._add_current_checked)
        tools_layout.addWidget(self.btn_add_current)
        layout.addWidget(tools)

        channel_area = QFrame(panel)
        channel_area.setObjectName("channelConfigHtmlChannelArea")
        channel_layout = QVBoxLayout(channel_area)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(0)
        channel_head = QFrame(channel_area)
        channel_head.setObjectName("channelConfigHtmlChannelHead")
        channel_head.setFixedHeight(38)
        channel_head_layout = QHBoxLayout(channel_head)
        channel_head_layout.setContentsMargins(0, 0, 0, 0)
        channel_head_layout.setSpacing(0)
        check_host = QWidget(channel_head)
        check_host.setObjectName("channelConfigHtmlCheckHost")
        check_host.setAttribute(Qt.WA_StyledBackground, True)
        check_host.setAutoFillBackground(False)
        check_host.setFixedWidth(42)
        check_host_layout = QHBoxLayout(check_host)
        check_host_layout.setContentsMargins(0, 0, 0, 0)
        check_host_layout.setSpacing(0)
        self.master_channel = QCheckBox(check_host)
        self.master_channel.setObjectName("channelConfigHtmlCheck")
        self.master_channel.setAttribute(Qt.WA_StyledBackground, True)
        self.master_channel.setAutoFillBackground(False)
        self.master_channel.setAccessibleName("全选当前筛选通道")
        self.master_channel.setFixedSize(20, 20)
        self.master_channel.setFocusPolicy(Qt.StrongFocus)
        self.master_channel.toggled.connect(self._toggle_visible_channels)
        check_host_layout.addWidget(self.master_channel, 0, Qt.AlignCenter)
        channel_head_layout.addWidget(check_host, 0, Qt.AlignVCenter)
        header_name = QLabel("通道名称", channel_head)
        header_name.setObjectName("channelConfigHtmlColumnHead")
        header_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_name.setContentsMargins(8, 0, 0, 0)
        self.channel_name_header = header_name
        channel_head_layout.addWidget(header_name, 1, Qt.AlignVCenter)
        for text, width in (("单位", 92), ("当前 View", 132), ("", 48)):
            header = QLabel(text, channel_head)
            header.setObjectName("channelConfigHtmlColumnHead")
            header.setFixedWidth(width)
            header.setAlignment(Qt.AlignCenter if text else Qt.AlignRight | Qt.AlignVCenter)
            channel_head_layout.addWidget(header)
        channel_layout.addWidget(channel_head)
        self.channel_table = QTableWidget(0, 5, channel_area)
        self.channel_table.setObjectName("channelConfigHtmlChannelTable")
        self.channel_table.setFrameShape(QFrame.NoFrame)
        self.channel_table.setShowGrid(False)
        self.channel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.channel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.channel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.channel_table.setFocusPolicy(Qt.StrongFocus)
        self.channel_table.setTabKeyNavigation(False)
        self.channel_table.installEventFilter(self)
        self.channel_table.horizontalHeader().setVisible(False)
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.verticalHeader().setDefaultSectionSize(49)
        header = self.channel_table.horizontalHeader()
        for column, width in ((0, 42), (2, 92), (3, 132), (4, 48)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            header.resizeSection(column, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        channel_layout.addWidget(self.channel_table, 1)
        self.empty_channels = QLabel("此配置中没有符合条件的通道。", channel_area)
        self.empty_channels.setObjectName("channelConfigHtmlEmpty")
        self.empty_channels.setAlignment(Qt.AlignCenter)
        channel_layout.addWidget(self.empty_channels)
        layout.addWidget(channel_area, 1)

        footer = QFrame(panel)
        footer.setObjectName("channelConfigHtmlDetailFooter")
        footer.setFixedHeight(64)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 12)
        footer_layout.setSpacing(8)
        self.save_state = QLabel(footer)
        self.save_state.setObjectName("channelConfigHtmlSaveState")
        footer_layout.addWidget(self.save_state)
        footer_layout.addStretch(1)
        self.btn_close = QPushButton("关闭", footer)
        self._control(self.btn_close)
        self.btn_close.clicked.connect(self.reject)
        footer_layout.addWidget(self.btn_close)
        self.btn_save = QPushButton("保存更改", footer)
        self.btn_save.setObjectName("channelConfigHtmlSave")
        self.btn_save.setProperty("role", "primary")
        self._control(self.btn_save)
        self.btn_save.clicked.connect(self._emit_save)
        footer_layout.addWidget(self.btn_save)
        layout.addWidget(footer)
        return panel

    def _build_toast(self) -> None:
        self.toast = QFrame(self)
        self.toast.setObjectName("channelConfigHtmlToast")
        toast_layout = QHBoxLayout(self.toast)
        toast_layout.setContentsMargins(14, 6, 9, 6)
        toast_layout.setSpacing(14)
        self.toast_text = QLabel(self.toast)
        toast_layout.addWidget(self.toast_text)
        self.toast_action = QPushButton("撤销", self.toast)
        self.toast_action.setObjectName("channelConfigHtmlToastAction")
        self.toast_action.setFixedHeight(30)
        self.toast_action.clicked.connect(self._run_undo)
        toast_layout.addWidget(self.toast_action)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

    def _build_export_menu(self) -> QMenu:
        menu = apply_rounded_menu_chrome(QMenu(self))
        current = menu.addAction("导出当前配置")
        current.triggered.connect(self._export_current_config)
        all_configs = menu.addAction("导出全部配置")
        all_configs.triggered.connect(self._export_all_configs)
        return menu

    def _export_current_config(self) -> None:
        self._export_to_file(current_only=True)

    def _export_all_configs(self) -> None:
        self._export_to_file(current_only=False)

    def _control(self, control) -> None:
        control.setFixedHeight(self.CONTROL_HEIGHT)
        control.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    @property
    def drafts(self) -> tuple[ChannelSelectionConfig, ...]:
        return tuple(self._drafts)

    @property
    def active_config_id(self) -> str | None:
        return self._active_id

    def config_row_widget(self, config_id: str) -> _ConfigRow | None:
        return self._config_rows.get(str(config_id))

    def is_dirty(self) -> bool:
        return self._drafts != self._baseline

    def mark_saved(
        self, persisted: Iterable[ChannelSelectionConfig], *, active_id: str | None = None
    ) -> None:
        self._baseline = list(persisted)
        self._drafts = list(persisted)
        self._active_id = self._initial_active_id(active_id or self._active_id)
        self._chosen_channels.clear()
        self._batch_config_ids.clear()
        self._undo_callback = None
        self._flash("通道配置已保存", None)
        self._rebuild_all()

    def set_preview(self, preview: ChannelConfigPreview) -> None:
        self._preview = preview
        self._rebuild_all()

    def export_payload(self, *, current_only: bool) -> bytes:
        configs = [self._active_config()] if current_only else list(self._drafts)
        return serialize_transfer(config for config in configs if config is not None)

    def import_payload(self, payload: bytes | str, *, conflict_mode: str = "keep") -> ImportMergeResult:
        parsed = parse_transfer(payload)
        result = merge_import(
            self._drafts,
            parsed.configs,
            conflict_mode=conflict_mode,
            id_factory=self._id_factory,
        )
        self._drafts = list(result.drafts)
        if self._drafts:
            self._active_id = self._drafts[0].config_id
        self._chosen_channels.clear()
        self._flash(
            f"已导入 {result.imported_count} 个配置"
            + (f"，替换 {result.replaced_count} 个" if result.replaced_count else "")
            + (f"，跳过 {result.skipped_count} 个" if result.skipped_count else "")
            + "；保存后生效",
            None,
        )
        self._rebuild_all()
        return result

    def _active_config(self) -> ChannelSelectionConfig | None:
        return next((item for item in self._drafts if item.config_id == self._active_id), None)

    def _visible_configs(self) -> list[ChannelSelectionConfig]:
        query = self.config_search.text().strip().casefold()
        if not query:
            return list(self._drafts)
        return [
            config
            for config in self._drafts
            if query in config.name.casefold()
            or any(query in channel.casefold() for channel in config.channel_names)
        ]

    def _visible_channels(self, config: ChannelSelectionConfig) -> list[str]:
        query = self.channel_search.text().strip().casefold()
        return [
            name for name in config.channel_names if not query or query in name.casefold()
        ]

    def _rebuild_all(self) -> None:
        self._rebuild_config_rows()
        self._rebuild_detail()
        self._sync_chrome()
        set_unique_default_button(self.btn_save, self)

    def _clear_config_list(self) -> None:
        while self.config_list_layout.count():
            item = self.config_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # ``deleteLater`` alone keeps an old card painted until the
                # next deferred-delete sweep, so a batch-mode rebuild can
                # briefly stack its text under the replacement card.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_config_rows(self) -> None:
        self._clear_config_list()
        self._config_rows = {}
        visible = self._visible_configs()
        for config in visible:
            row = _ConfigRow(
                config,
                active=config.config_id == self._active_id,
                batch_mode=self._batch_mode,
                checked=config.config_id in self._batch_config_ids,
                parent=self.config_list,
            )
            row.clicked.connect(self._on_config_row_clicked)
            row.batch_toggled.connect(self._set_batch_config_checked)
            row.delete_requested.connect(self._delete_config)
            self._config_rows[config.config_id] = row
            self.config_list_layout.addWidget(row)
        if not visible:
            empty = QLabel("没有符合条件的配置。", self.config_list)
            empty.setObjectName("channelConfigHtmlEmpty")
            empty.setAlignment(Qt.AlignCenter)
            self.config_list_layout.addWidget(empty)
        self.config_list_layout.addStretch(1)

    def _rebuild_detail(self) -> None:
        config = self._active_config()
        enabled = config is not None
        for control in (
            self.btn_export,
            self.btn_rename,
            self.btn_copy,
            self.btn_delete_config,
            self.channel_search,
            self.btn_select_channels,
            self.btn_clear_channels,
            self.btn_remove_channels,
            self.btn_add_current,
        ):
            control.setEnabled(enabled)
        if config is None:
            self.detail_title.setText("—")
            self.detail_meta.setText("没有可编辑的配置")
            self.match_chip.hide()
            self.missing_chip.hide()
            self.channel_table.setRowCount(0)
            self.empty_channels.show()
            return
        matched = sum(1 for name in config.channel_names if self._preview.matches(name))
        missing = len(config.channel_names) - matched
        self.detail_title.setText(config.name)
        self.detail_title.setToolTip(config.name)
        self.detail_meta.setText(
            f"{len(config.channel_names)} 个通道 · 更新于 {_display_updated(config.updated_at)}"
        )
        self.match_chip.setText(f"●  {matched} 个已匹配")
        self.match_chip.show()
        self.missing_chip.setText(f"●  {missing} 个缺失")
        self.missing_chip.setVisible(bool(missing))
        self._rebuild_channel_rows()

    def _check_cell(
        self, checked: bool, callback, accessible_name: str, channel: str
    ) -> QWidget:
        cell = QWidget(self.channel_table)
        cell.setObjectName("channelConfigHtmlCheckCell")
        cell.setAttribute(Qt.WA_StyledBackground, True)
        cell.setAutoFillBackground(False)
        cell.setFocusPolicy(Qt.NoFocus)
        cell.setProperty("chosen", bool(checked))
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        check = QCheckBox(cell)
        check.setObjectName("channelConfigHtmlCheck")
        check.setAttribute(Qt.WA_StyledBackground, True)
        check.setAutoFillBackground(False)
        check.setAccessibleName(accessible_name)
        check.setFixedSize(20, 20)
        check.setFocusPolicy(Qt.StrongFocus)
        check.setProperty("channelName", channel)
        check.setChecked(checked)
        check.toggled.connect(callback)
        check.installEventFilter(self)
        layout.addWidget(check, 0, Qt.AlignCenter)
        return cell

    def _rebuild_channel_rows(self) -> None:
        config = self._active_config()
        if config is None:
            self.channel_table.setRowCount(0)
            return
        focused = self.focusWidget()
        restore_focus = focused is not None and (
            focused is self.channel_table or self.channel_table.isAncestorOf(focused)
        )
        current_item = self.channel_table.item(self.channel_table.currentRow(), 1)
        restore_name = current_item.text() if current_item is not None else None
        visible = self._visible_channels(config)
        self._chosen_channels.intersection_update(config.channel_names)
        self.channel_table.setRowCount(len(visible))
        for row, channel in enumerate(visible):
            self.channel_table.setCellWidget(
                row,
                0,
                self._check_cell(
                    channel in self._chosen_channels,
                    lambda checked, name=channel: self._set_channel_chosen(name, checked),
                    f"选择 {channel}",
                    channel,
                ),
            )
            name = QTableWidgetItem(channel)
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name.setToolTip(channel)
            name.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.channel_table.setItem(row, 1, name)
            hint = config.unit_hint(channel) or self._preview.unit_for(channel)
            unit = QTableWidgetItem(hint or "—")
            unit.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            unit.setTextAlignment(Qt.AlignCenter)
            if channel in self._preview.inconsistent_unit_names:
                unit.setToolTip("当前 View 中该通道单位不一致，显示第一个非空单位")
            self.channel_table.setItem(row, 2, unit)
            if self._preview.target_file_count == 0:
                status, color = "无可用 View", "#64748b"
            elif self._preview.matches(channel):
                status, color = "●  已匹配", "#527065"
            else:
                status, color = "●  缺失", "#956012"
            match = QTableWidgetItem(status)
            match.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            match.setForeground(QColor(color))
            match.setTextAlignment(Qt.AlignCenter)
            self.channel_table.setItem(row, 3, match)
            remove_cell = QWidget(self.channel_table)
            remove_cell.setObjectName("channelConfigHtmlRemoveCell")
            remove_cell.setFocusPolicy(Qt.NoFocus)
            remove_cell.setProperty("chosen", channel in self._chosen_channels)
            remove_layout = QHBoxLayout(remove_cell)
            remove_layout.setContentsMargins(6, 6, 6, 6)
            remove_layout.setAlignment(Qt.AlignCenter)
            remove = QPushButton("×", remove_cell)
            remove.setObjectName("channelConfigHtmlRemoveOne")
            remove.setAccessibleName(f"从配置移除 {channel}")
            remove.setProperty("channelName", channel)
            remove.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
            remove.setAutoDefault(False)
            remove.setDefault(False)
            remove.clicked.connect(
                lambda _checked=False, name=channel: self._remove_channels((name,))
            )
            remove.installEventFilter(self)
            remove_layout.addWidget(remove)
            self.channel_table.setCellWidget(row, 4, remove_cell)
            if channel in self._chosen_channels:
                for column in range(1, 4):
                    self.channel_table.item(row, column).setBackground(QColor("#edf5ff"))
        self.empty_channels.setVisible(not visible)
        self.channel_table.setVisible(bool(visible))
        selected_visible = sum(1 for name in visible if name in self._chosen_channels)
        previous = self.master_channel.blockSignals(True)
        self.master_channel.setChecked(bool(visible) and selected_visible == len(visible))
        self.master_channel.blockSignals(previous)
        if restore_name in visible:
            blocked = self.channel_table.blockSignals(True)
            self.channel_table.setCurrentCell(visible.index(restore_name), 1)
            self.channel_table.blockSignals(blocked)
            if restore_focus:
                self.channel_table.setFocus(Qt.OtherFocusReason)
        set_unique_default_button(self.btn_save, self)

    def _channel_name_for_widget(self, obj) -> str | None:
        widget = obj
        table = getattr(self, "channel_table", None)
        if table is None:
            return None
        while widget is not None and widget is not table:
            name = widget.property("channelName")
            if name:
                return str(name)
            widget = widget.parentWidget()
        item = table.item(table.currentRow(), 1)
        return item.text() if item is not None else None

    def _handle_channel_table_key(self, obj, event) -> bool:
        table = getattr(self, "channel_table", None)
        if table is None or obj is None:
            return False
        if obj is not table and not table.isAncestorOf(obj):
            return False
        key = event.key()
        channel = self._channel_name_for_widget(obj)
        if key in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return True
        if key == Qt.Key_Space and obj is table:
            if not channel:
                return False
            self._set_channel_chosen(channel, channel not in self._chosen_channels)
            event.accept()
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if not channel:
                return False
            self._remove_channels((channel,))
            event.accept()
            return True
        return False

    def _sync_chrome(self) -> None:
        dirty = self.is_dirty()
        self.dirty_dot.setVisible(dirty)
        self.btn_save.setEnabled(dirty)
        self.config_count.setText(str(len(self._drafts)))
        self.config_summary.setText(f"{len(self._drafts)} 个配置")
        self.view_summary.setText(
            f"当前 View · {self._preview.target_file_count} 个文件"
            if self._preview.target_file_count
            else "当前 View · 无已加入文件"
        )
        self.btn_batch.setVisible(not self._batch_mode)
        self.batch_actions.setVisible(self._batch_mode)
        self.btn_delete_configs.setEnabled(bool(self._batch_config_ids))
        self.btn_delete_configs.setText(
            f"删除 {len(self._batch_config_ids)} 个配置"
            if self._batch_config_ids
            else "删除所选"
        )
        self.btn_clear_channels.setEnabled(bool(self._chosen_channels))
        self.btn_remove_channels.setEnabled(bool(self._chosen_channels))
        self.btn_remove_channels.setText(
            f"移除所选 {len(self._chosen_channels)}"
            if self._chosen_channels
            else "移除所选"
        )
        config = self._active_config()
        if config is None:
            self.save_state.setText("没有配置")
        else:
            state = "修改尚未保存" if dirty else "已保存"
            self.save_state.setText(f"{len(config.channel_names)} 个通道 · {state}")

    def _on_config_row_clicked(self, config_id: str) -> None:
        if self._batch_mode:
            self._set_batch_config_checked(
                config_id, config_id not in self._batch_config_ids
            )
            self._rebuild_config_rows()
            return
        if config_id != self._active_id:
            self._active_id = config_id
            self._chosen_channels.clear()
            self.channel_search.clear()
            self._rebuild_all()

    def _set_batch_config_checked(self, config_id: str, checked: bool) -> None:
        if checked:
            self._batch_config_ids.add(config_id)
        else:
            self._batch_config_ids.discard(config_id)
        self._sync_chrome()

    def _enter_batch_mode(self) -> None:
        self._batch_mode = True
        self._batch_config_ids.clear()
        self._rebuild_all()

    def _exit_batch_mode(self) -> None:
        self._batch_mode = False
        self._batch_config_ids.clear()
        self._rebuild_all()

    def _delete_batch_configs(self) -> None:
        wanted = set(self._batch_config_ids)
        if not wanted:
            return
        if len(wanted) >= len(self._drafts):
            self._flash("不能删除全部配置", None)
            return
        removed = [item for item in self._drafts if item.config_id in wanted]
        self._drafts = [item for item in self._drafts if item.config_id not in wanted]
        if self._active_id in wanted:
            self._active_id = self._drafts[0].config_id
        self._batch_mode = False
        self._batch_config_ids.clear()
        self._chosen_channels.clear()
        self._flash(f"已将 {len(removed)} 个配置标记为删除，保存后生效", None)
        self._rebuild_all()

    def _set_channel_chosen(self, channel: str, checked: bool) -> None:
        if checked:
            self._chosen_channels.add(channel)
        else:
            self._chosen_channels.discard(channel)
        self._rebuild_channel_rows()
        self._sync_chrome()

    def _select_visible_channels(self) -> None:
        config = self._active_config()
        if config is None:
            return
        self._chosen_channels.update(self._visible_channels(config))
        self._rebuild_channel_rows()
        self._sync_chrome()

    def _clear_channel_selection(self) -> None:
        self._chosen_channels.clear()
        self._rebuild_channel_rows()
        self._sync_chrome()

    def _toggle_visible_channels(self, checked: bool) -> None:
        config = self._active_config()
        if config is None:
            return
        visible = self._visible_channels(config)
        if checked:
            self._chosen_channels.update(visible)
        else:
            self._chosen_channels.difference_update(visible)
        self._rebuild_channel_rows()
        self._sync_chrome()

    def _remove_selected_channels(self) -> None:
        self._remove_channels(tuple(self._chosen_channels))

    def _remove_channels(self, channel_names: Iterable[str]) -> None:
        config = self._active_config()
        wanted = set(channel_names)
        if config is None or not wanted:
            return
        old_channels = config.channel_names
        old_hints = config.channel_unit_hints
        remaining = tuple(name for name in old_channels if name not in wanted)
        removed = len(old_channels) - len(remaining)
        if not removed:
            return
        hint_map = dict(old_hints)
        self._replace_active(
            replace(
                config,
                channel_names=remaining,
                channel_unit_hints=tuple(
                    (name, hint_map[name]) for name in remaining if hint_map.get(name)
                ),
            )
        )
        self._chosen_channels.clear()

        def undo() -> None:
            current = self._active_config()
            if current is None or current.config_id != config.config_id:
                return
            self._replace_active(
                replace(
                    current,
                    channel_names=old_channels,
                    channel_unit_hints=old_hints,
                )
            )
            self._flash("已撤销通道移除", None)

        self._flash(f"已从“{config.name}”移除 {removed} 个通道", undo)
        self._rebuild_all()

    def _add_current_checked(self) -> None:
        config = self._active_config()
        if config is None:
            return
        existing = set(config.channel_names)
        additions = [name for name in self._checked_channel_hints if name not in existing]
        if not additions:
            self._flash("当前勾选通道已全部包含在此配置中", None)
            return
        hint_map = dict(config.channel_unit_hints)
        hint_map.update({name: self._checked_channel_hints[name] for name in additions})
        names = (*config.channel_names, *additions)
        self._replace_active(
            replace(
                config,
                channel_names=names,
                channel_unit_hints=tuple(
                    (name, hint_map[name]) for name in names if hint_map.get(name)
                ),
            )
        )
        self._flash(f"已添加当前勾选中的 {len(additions)} 个新通道", None)
        self._rebuild_all()

    def _create_from_checked(self) -> None:
        if not self._checked_channel_hints:
            self._flash("当前没有已勾选通道，无法新建配置", None)
            return
        base, sequence = "未命名配置", 2
        name = base
        taken = {config.name.casefold() for config in self._drafts}
        while name.casefold() in taken:
            name = f"{base} {sequence}"
            sequence += 1
        new = ChannelSelectionConfig.create(
            str(self._id_factory()),
            name,
            tuple(self._checked_channel_hints),
            now="draft",
            channel_unit_hints=self._checked_channel_hints,
        )
        self._drafts.insert(0, new)
        self._active_id = new.config_id
        self._chosen_channels.clear()
        self._rebuild_all()
        self._open_rename_dialog()

    def _rename_active_to(self, name: str) -> bool:
        config = self._active_config()
        name = str(name).strip()
        if config is None or not name:
            return False
        conflict = next(
            (
                item
                for item in self._drafts
                if item.config_id != config.config_id and item.name.casefold() == name.casefold()
            ),
            None,
        )
        if conflict is not None:
            self._flash(f"配置名称已存在：{conflict.name}", None)
            return False
        self._replace_active(replace(config, name=name))
        self._rebuild_all()
        return True

    def _open_rename_dialog(self) -> None:
        config = self._active_config()
        if config is None:
            return
        dialog = QDialog(self)
        dialog.setObjectName("channelConfigHtmlRenameDialog")
        dialog.setWindowTitle("重命名配置")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("重命名配置", dialog)
        title.setObjectName("channelConfigHtmlPopoverTitle")
        copy = QLabel("名称用于配置列表显示，不会修改通道名称。", dialog)
        copy.setObjectName("channelConfigHtmlPopoverCopy")
        layout.addWidget(title)
        layout.addWidget(copy)
        edit = QLineEdit(config.name, dialog)
        edit.setMaxLength(80)
        edit.setFixedHeight(self.CONTROL_HEIGHT)
        layout.addWidget(edit)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("取消", dialog)
        confirm = QPushButton("保存名称", dialog)
        confirm.setProperty("role", "primary")
        self._control(cancel)
        self._control(confirm)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        set_unique_default_button(confirm, dialog)
        edit.returnPressed.connect(dialog.accept)
        edit.selectAll()
        if dialog.exec_() == QDialog.Accepted:
            self._rename_active_to(edit.text())

    def _copy_active(self) -> None:
        config = self._active_config()
        if config is None:
            return
        stem, sequence = f"{config.name} 副本", 2
        name = stem
        taken = {item.name.casefold() for item in self._drafts}
        while name.casefold() in taken:
            name = f"{stem} {sequence}"
            sequence += 1
        copy = ChannelSelectionConfig.create(
            str(self._id_factory()),
            name,
            config.channel_names,
            now="draft",
            channel_unit_hints=config.channel_unit_hints,
        )
        self._drafts.insert(0, copy)
        self._active_id = copy.config_id
        self._chosen_channels.clear()
        self._flash("已复制配置，保存后生效", None)
        self._rebuild_all()

    def _delete_active_config(self) -> None:
        self._delete_config(self._active_id)

    def _delete_config(self, config_id: str | None) -> None:
        config = next(
            (item for item in self._drafts if item.config_id == config_id), None
        )
        if config is None:
            return
        if len(self._drafts) <= 1:
            self._flash("至少需要保留一个配置", None)
            return
        previous_active = self._active_id
        self._drafts = [item for item in self._drafts if item.config_id != config.config_id]
        remaining_ids = {item.config_id for item in self._drafts}
        if previous_active == config.config_id or previous_active not in remaining_ids:
            self._active_id = self._drafts[0].config_id
            self._chosen_channels.clear()
        self._flash(f"已将“{config.name}”标记为删除，保存后生效", None)
        self._rebuild_all()

    def _replace_active(self, replacement: ChannelSelectionConfig) -> None:
        self._drafts = [
            replacement if item.config_id == replacement.config_id else item
            for item in self._drafts
        ]

    def _emit_save(self) -> None:
        if not self.is_dirty():
            return
        empty = next((item for item in self._drafts if not item.channel_names), None)
        if empty is not None:
            self._active_id = empty.config_id
            self._flash(f"“{empty.name}”没有通道；请补充通道或删除该配置", None)
            self._rebuild_all()
            return
        self.save_requested.emit(tuple(self._drafts))

    def _import_from_file(self) -> None:
        path = self._open_file()
        if not path:
            return
        try:
            payload = Path(path).read_bytes()
            parsed = parse_transfer(payload)
        except (OSError, ValueError) as exc:
            self._flash(f"导入失败：{exc}", None)
            return
        mode = self._show_import_preview(path, parsed)
        if mode is None:
            return
        try:
            self.import_payload(payload, conflict_mode=mode)
        except ValueError as exc:
            self._flash(f"导入失败：{exc}", None)

    def _show_import_preview(self, path: str, parsed) -> str | None:
        dialog, combo = self._build_import_preview_dialog(path, parsed)
        return str(combo.currentData()) if dialog.exec_() == QDialog.Accepted else None

    def _build_import_preview_dialog(self, path: str, parsed) -> tuple[QDialog, QComboBox]:
        """Build the approved import-review popover without committing a draft."""
        dialog = QDialog(self)
        dialog.setObjectName("channelConfigHtmlImportDialog")
        dialog.setWindowTitle("确认导入通道配置")
        dialog.setModal(True)
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("确认导入通道配置", dialog)
        title.setObjectName("channelConfigHtmlPopoverTitle")
        copy = QLabel("导入前先核对内容；确认后仍需点击主窗口的“保存更改”。", dialog)
        copy.setObjectName("channelConfigHtmlPopoverCopy")
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)
        conflict_count = sum(
            1
            for item in parsed.configs
            if any(existing.name.casefold() == item.name.casefold() for existing in self._drafts)
        )
        conflict_copy = (
            f"{conflict_count} 个同名配置"
            if conflict_count
            else "无同名冲突"
        )
        file_meta = QLabel(
            f"JSON  ·  {Path(path).name}\nTraceLab v1 · {conflict_copy}", dialog
        )
        file_meta.setObjectName("channelConfigHtmlImportFile")
        file_meta.setWordWrap(True)
        layout.addWidget(file_meta)
        stats = QWidget(dialog)
        stats.setObjectName("channelConfigHtmlImportStats")
        stats_layout = QHBoxLayout(stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)
        for value, label_text in (
            (str(len(parsed.configs)), "个配置"),
            (str(sum(len(item.channel_names) for item in parsed.configs)), "个通道名称"),
        ):
            stat = QFrame(stats)
            stat.setObjectName("channelConfigHtmlImportStat")
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(11, 9, 11, 9)
            stat_layout.setSpacing(4)
            value_label = QLabel(value, stat)
            value_label.setObjectName("channelConfigHtmlImportStatValue")
            label = QLabel(label_text, stat)
            label.setObjectName("channelConfigHtmlImportStatLabel")
            stat_layout.addWidget(value_label)
            stat_layout.addWidget(label)
            stats_layout.addWidget(stat, 1)
        layout.addWidget(stats)
        label = QLabel("遇到同名配置", dialog)
        label.setObjectName("channelConfigHtmlImportLabel")
        layout.addWidget(label)
        combo = QComboBox(dialog)
        combo.setFixedHeight(self.CONTROL_HEIGHT)
        combo.addItem("保留两份，并给导入项追加“（导入）”", "keep")
        combo.addItem("用导入内容替换现有配置", "replace")
        combo.addItem("跳过同名配置", "skip")
        layout.addWidget(combo)
        note = QLabel(
            "传递文件只保存配置名称、通道名称和单位；当前 View 的匹配状态会在导入后重新计算。",
            dialog,
        )
        note.setObjectName("channelConfigHtmlPopoverCopy")
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("取消", dialog)
        confirm = QPushButton("导入配置", dialog)
        confirm.setProperty("role", "primary")
        self._control(cancel)
        self._control(confirm)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        set_unique_default_button(confirm, dialog)
        return dialog, combo

    def _export_to_file(self, *, current_only: bool) -> None:
        try:
            payload = self.export_payload(current_only=current_only)
        except ValueError as exc:
            self._flash(f"导出失败：{exc}", None)
            return
        active = self._active_config()
        stem = active.name if current_only and active else f"TraceLab-{len(self._drafts)}-channel-configs"
        path = self._save_file(f"{stem}{TRANSFER_SUFFIX}")
        if not path:
            return
        try:
            Path(path).write_bytes(payload)
        except OSError as exc:
            self._flash(f"导出失败：{exc}", None)
            return
        suffix = "，包含当前未保存修改" if self.is_dirty() else ""
        self._flash(f"已导出 {1 if current_only else len(self._drafts)} 个配置{suffix}", None)

    def _open_import_file(self) -> str:
        path, _selected = QFileDialog.getOpenFileName(
            self, "导入通道配置", "", "TraceLab 配置 (*.tracelab-config.json *.json)"
        )
        return path

    def _save_export_file(self, filename: str) -> str:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "导出通道配置",
            filename,
            "TraceLab 配置 (*.tracelab-config.json);;JSON (*.json)",
        )
        return path

    def _flash(self, text: str, undo: Callable[[], None] | None) -> None:
        self._undo_callback = undo
        self.toast_text.setText(text)
        self.toast_action.setVisible(undo is not None)
        self.toast.adjustSize()
        self.toast.show()
        self._position_toast()
        self._toast_timer.start(7000)

    def _set_feedback(self, text: str, _level: str = "warning") -> None:
        """Compatibility seam for the host's failed-save notification path."""
        # A persistence error must not silently discard the most recent
        # in-dialog channel-removal undo action.
        self._flash(str(text), self._undo_callback)

    def _run_undo(self) -> None:
        callback = self._undo_callback
        self._undo_callback = None
        self.toast.hide()
        if callback is not None:
            callback()

    def _position_toast(self) -> None:
        self.toast.adjustSize()
        self.toast.move(
            max(12, (self.width() - self.toast.width()) // 2),
            max(12, self.height() - self.toast.height() - 24),
        )

    def _confirm_discard_changes(self) -> bool:
        dialog = QDialog(self)
        dialog.setObjectName("channelConfigHtmlDiscardDialog")
        dialog.setWindowTitle("放弃未保存修改？")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("放弃未保存修改？", dialog)
        title.setObjectName("channelConfigHtmlPopoverTitle")
        copy = QLabel("新建、删除、导入和通道编辑都不会写入本机配置。", dialog)
        copy.setObjectName("channelConfigHtmlPopoverCopy")
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)
        actions = QHBoxLayout()
        actions.addStretch(1)
        keep = QPushButton("继续编辑", dialog)
        discard = QPushButton("放弃修改", dialog)
        discard.setProperty("role", "danger")
        self._control(keep)
        self._control(discard)
        actions.addWidget(keep)
        actions.addWidget(discard)
        layout.addLayout(actions)
        keep.clicked.connect(dialog.reject)
        discard.clicked.connect(dialog.accept)
        set_unique_default_button(keep, dialog)
        return dialog.exec_() == QDialog.Accepted

    def reject(self) -> None:
        if self.is_dirty() and not self._confirm_discard_changes():
            return
        self._closing = True
        super().reject()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self._position_toast()

    def closeEvent(self, event):  # noqa: N802
        if self._closing or not self.is_dirty() or self._confirm_discard_changes():
            event.accept()
        else:
            event.ignore()
