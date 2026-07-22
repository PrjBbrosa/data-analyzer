"""A focused manager for saved TimeDomain channel configurations."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..channel_config import ChannelSelectionConfig


def _display_updated(value: str) -> str:
    """Keep the timestamp scannable without changing its persisted value."""
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


class ChannelConfigManagerDialog(QDialog):
    """List, find, rename, copy, and batch-delete saved configurations."""

    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(str, str)
    copy_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(object)

    def __init__(
        self,
        configs: Iterable[ChannelSelectionConfig],
        *,
        selected_id: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("channelConfigManager")
        self.setWindowTitle("管理通道配置")
        self.setModal(True)
        self.resize(880, 540)
        self.setMinimumSize(720, 440)

        self._configs: list[ChannelSelectionConfig] = []
        self._selected_ids: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_content(), 1)
        root.addWidget(self._build_footer())

        self.set_configs(configs, selected_ids=(() if selected_id is None else (selected_id,)))

    def _build_header(self):
        frame = QFrame(self)
        frame.setObjectName("channelConfigManagerHeader")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(22, 16, 22, 14)
        layout.setSpacing(3)
        title = QLabel("管理通道配置", frame)
        title.setObjectName("channelConfigManagerTitle")
        subtitle = QLabel(
            "配置保存的是通道名称；应用到当前 View 时会自动匹配已加入的文件。",
            frame,
        )
        subtitle.setObjectName("channelConfigManagerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return frame

    def _build_toolbar(self):
        frame = QFrame(self)
        frame.setObjectName("channelConfigManagerToolbar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(8)
        self.search_edit = QLineEdit(frame)
        self.search_edit.setObjectName("channelConfigManagerSearch")
        self.search_edit.setPlaceholderText("搜索配置名称或通道…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(300)
        self.search_edit.textChanged.connect(self._rebuild_rows)
        layout.addWidget(self.search_edit)

        self.btn_select_all = QPushButton("全选筛选结果", frame)
        self.btn_select_all.setProperty("role", "tool")
        self.btn_select_all.clicked.connect(self._select_all_visible)
        layout.addWidget(self.btn_select_all)
        self.btn_clear = QPushButton("清除选择", frame)
        self.btn_clear.setProperty("role", "tool")
        self.btn_clear.clicked.connect(self._clear_selection)
        layout.addWidget(self.btn_clear)
        layout.addStretch(1)
        self.btn_create = QPushButton("从当前勾选保存", frame)
        self.btn_create.setObjectName("channelConfigManagerCreate")
        self.btn_create.setProperty("role", "primary")
        self.btn_create.clicked.connect(self.create_requested)
        layout.addWidget(self.btn_create)
        return frame

    def _build_content(self):
        content = QWidget(self)
        content.setObjectName("channelConfigManagerContent")
        layout = QGridLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = QTableWidget(0, 4, content)
        self.table.setObjectName("channelConfigManagerTable")
        self.table.setHorizontalHeaderLabels(("", "配置", "通道数", "最后更新"))
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.resizeSection(0, 36)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(2, 76)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.resizeSection(3, 136)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 0, 0)

        detail = QFrame(content)
        detail.setObjectName("channelConfigManagerDetail")
        detail.setMinimumWidth(240)
        detail.setMaximumWidth(280)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(18, 18, 18, 18)
        detail_layout.setSpacing(7)
        eyebrow = QLabel("单项编辑", detail)
        eyebrow.setObjectName("channelConfigManagerEyebrow")
        detail_layout.addWidget(eyebrow)
        self.detail_title = QLabel("未选择配置", detail)
        self.detail_title.setObjectName("channelConfigManagerDetailTitle")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        self.detail_description = QLabel("从左侧选择一个或多个配置。", detail)
        self.detail_description.setObjectName("channelConfigManagerDetailDescription")
        self.detail_description.setWordWrap(True)
        detail_layout.addWidget(self.detail_description)
        detail_layout.addSpacing(8)
        name_label = QLabel("配置名称", detail)
        name_label.setObjectName("channelConfigManagerFieldLabel")
        detail_layout.addWidget(name_label)
        self.name_edit = QLineEdit(detail)
        self.name_edit.setObjectName("channelConfigManagerName")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.returnPressed.connect(self._emit_rename)
        detail_layout.addWidget(self.name_edit)
        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.btn_rename = QPushButton("重命名", detail)
        self.btn_rename.setProperty("role", "tool")
        self.btn_rename.clicked.connect(self._emit_rename)
        actions.addWidget(self.btn_rename)
        self.btn_copy = QPushButton("复制一份", detail)
        self.btn_copy.setProperty("role", "tool")
        self.btn_copy.clicked.connect(self._emit_copy)
        actions.addWidget(self.btn_copy)
        detail_layout.addLayout(actions)
        detail_layout.addStretch(1)
        note = QLabel(
            "删除可同时处理多项；重命名和复制只允许单项，避免误操作。",
            detail,
        )
        note.setObjectName("channelConfigManagerNote")
        note.setWordWrap(True)
        detail_layout.addWidget(note)
        layout.addWidget(detail, 0, 1)
        return content

    def _build_footer(self):
        frame = QFrame(self)
        frame.setObjectName("channelConfigManagerFooter")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(8)
        self.count_label = QLabel(frame)
        self.count_label.setObjectName("channelConfigManagerCount")
        layout.addWidget(self.count_label)
        hint = QLabel("删除后无法从应用内撤销", frame)
        hint.setObjectName("channelConfigManagerHint")
        layout.addWidget(hint)
        layout.addStretch(1)
        self.btn_delete = QPushButton(frame)
        self.btn_delete.setObjectName("channelConfigManagerDelete")
        self.btn_delete.setProperty("role", "destructive")
        self.btn_delete.clicked.connect(self._emit_delete)
        layout.addWidget(self.btn_delete)
        close = QPushButton("关闭", frame)
        close.setProperty("role", "tool")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        return frame

    def set_configs(
        self,
        configs: Iterable[ChannelSelectionConfig],
        *,
        selected_ids: Iterable[str] = (),
    ) -> None:
        self._configs = list(configs)
        valid = {config.config_id for config in self._configs}
        requested = {str(config_id) for config_id in selected_ids}
        self._selected_ids = (requested or self._selected_ids) & valid
        self._rebuild_rows()

    def selected_ids(self) -> tuple[str, ...]:
        return tuple(
            config.config_id
            for config in self._configs
            if config.config_id in self._selected_ids
        )

    def _visible_configs(self) -> list[ChannelSelectionConfig]:
        query = self.search_edit.text().strip().casefold()
        if not query:
            return list(self._configs)
        return [
            config
            for config in self._configs
            if query in config.name.casefold()
            or any(query in channel.casefold() for channel in config.channel_names)
        ]

    def _rebuild_rows(self):
        visible = self._visible_configs()
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(visible))
        for row, config in enumerate(visible):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setData(Qt.UserRole, config.config_id)
            check.setCheckState(
                Qt.Checked if config.config_id in self._selected_ids else Qt.Unchecked
            )
            self.table.setItem(row, 0, check)
            name = QTableWidgetItem(config.name)
            name.setData(Qt.UserRole, config.config_id)
            name.setToolTip("\n".join(config.channel_names))
            self.table.setItem(row, 1, name)
            count = QTableWidgetItem(f"{len(config.channel_names)} 个")
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, count)
            updated = QTableWidgetItem(_display_updated(config.updated_at))
            updated.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, updated)
        del blocker
        self._sync_detail()

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        config_id = str(item.data(Qt.UserRole) or "")
        if not config_id:
            return
        if item.checkState() == Qt.Checked:
            self._selected_ids.add(config_id)
        else:
            self._selected_ids.discard(config_id)
        self._sync_detail()

    def _select_all_visible(self):
        self._selected_ids.update(config.config_id for config in self._visible_configs())
        self._rebuild_rows()

    def _clear_selection(self):
        self._selected_ids.clear()
        self._rebuild_rows()

    def _selected_configs(self) -> list[ChannelSelectionConfig]:
        return [
            config for config in self._configs if config.config_id in self._selected_ids
        ]

    def _sync_detail(self):
        selected = self._selected_configs()
        count = len(selected)
        one = selected[0] if count == 1 else None
        self.count_label.setText(f"已选择 {count} 项")
        self.btn_delete.setText(f"删除所选 {count} 项" if count else "删除所选")
        self.btn_delete.setEnabled(bool(count))
        self.btn_clear.setEnabled(bool(count))
        self.name_edit.setEnabled(one is not None)
        self.btn_rename.setEnabled(one is not None)
        self.btn_copy.setEnabled(one is not None)
        if one is not None:
            self.detail_title.setText(one.name)
            self.detail_description.setText(
                f"{len(one.channel_names)} 个通道 · 最后更新 {_display_updated(one.updated_at)}"
            )
            blocker = QSignalBlocker(self.name_edit)
            self.name_edit.setText(one.name)
            del blocker
        elif count:
            self.detail_title.setText(f"已选择 {count} 项")
            self.detail_description.setText("可批量删除；请只选择一项后重命名或复制。")
            self.name_edit.clear()
        else:
            self.detail_title.setText("未选择配置")
            self.detail_description.setText("从左侧选择一个或多个配置。")
            self.name_edit.clear()

    def _emit_rename(self):
        selected = self._selected_configs()
        if len(selected) != 1:
            return
        name = self.name_edit.text().strip()
        if name and name != selected[0].name:
            self.rename_requested.emit(selected[0].config_id, name)

    def _emit_copy(self):
        selected = self._selected_configs()
        if len(selected) == 1:
            self.copy_requested.emit(selected[0].config_id)

    def _emit_delete(self):
        selected = self.selected_ids()
        if selected:
            self.delete_requested.emit(selected)
