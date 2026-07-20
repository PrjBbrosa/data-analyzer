"""Compact actions for reusable named channel-selection configurations."""
from __future__ import annotations

from collections.abc import Iterable

from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ..channel_config import ChannelSelectionConfig


class ChannelConfigBar(QWidget):
    """Save / pending-config / Apply controls with no apply-on-select behavior."""

    save_requested = pyqtSignal()
    apply_requested = pyqtSignal(str)
    manage_requested = pyqtSignal(object)
    selection_changed = pyqtSignal(object)

    MANAGE_SENTINEL = "__manage_configs__"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.btn_save = QPushButton("保存", self)
        self.btn_save.setObjectName("channelConfigSave")
        self.btn_save.setProperty("role", "tool")
        self.btn_save.setMaximumWidth(52)

        self.combo = QComboBox(self)
        self.combo.setObjectName("channelConfigCombo")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.combo.completer().setFilterMode(Qt.MatchContains)

        self.btn_apply = QPushButton("应用", self)
        self.btn_apply.setObjectName("channelConfigApply")
        self.btn_apply.setProperty("role", "primary")
        self.btn_apply.setMaximumWidth(52)

        layout.addWidget(self.btn_save)
        layout.addWidget(self.combo)
        layout.addWidget(self.btn_apply)

        self._has_checked = False
        self._has_attached = False
        self._last_config_id: str | None = None

        self.btn_save.clicked.connect(self.save_requested)
        self.btn_apply.clicked.connect(self._emit_apply)
        self.combo.currentIndexChanged.connect(self._on_index_changed)

        self.set_configs([])
        self.set_context(has_checked=False, has_attached=False)

    def set_configs(
        self,
        configs: Iterable[ChannelSelectionConfig],
        selected_id: str | None = None,
    ) -> None:
        configs = list(configs)
        selected = selected_id if selected_id is not None else self.selected_config_id()
        blocker = QSignalBlocker(self.combo)
        self.combo.clear()
        self.combo.addItem("选择配置…", None)
        for config in configs:
            count = len(config.channel_names)
            self.combo.addItem(f"{config.name} · {count}", config.config_id)
            idx = self.combo.count() - 1
            self.combo.setItemData(
                idx,
                f"{config.name}\n{count} 个通道\n更新于 {config.updated_at}",
                Qt.ToolTipRole,
            )
        if configs:
            self.combo.insertSeparator(self.combo.count())
        self.combo.addItem("管理配置…", self.MANAGE_SENTINEL)
        selected_idx = self.combo.findData(selected)
        if selected_idx < 0 or selected == self.MANAGE_SENTINEL:
            selected_idx = 0
        self.combo.setCurrentIndex(selected_idx)
        del blocker
        self._last_config_id = self.selected_config_id()
        self._sync_enabled()

    def set_context(self, *, has_checked: bool, has_attached: bool) -> None:
        self._has_checked = bool(has_checked)
        self._has_attached = bool(has_attached)
        self._sync_enabled()

    def selected_config_id(self) -> str | None:
        value = self.combo.currentData()
        if value in (None, self.MANAGE_SENTINEL):
            return None
        return str(value)

    def select_config(self, config_id: str | None) -> None:
        idx = self.combo.findData(config_id)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)

    def set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        self.combo.setProperty("dirty", dirty)
        self.combo.setToolTip(
            "当前勾选与待应用配置不同" if dirty else "选择待应用的通道配置"
        )
        self.combo.style().unpolish(self.combo)
        self.combo.style().polish(self.combo)

    def _on_index_changed(self, _index: int) -> None:
        if self.combo.currentData() == self.MANAGE_SENTINEL:
            selected = self._last_config_id
            blocker = QSignalBlocker(self.combo)
            idx = self.combo.findData(selected)
            self.combo.setCurrentIndex(idx if idx >= 0 else 0)
            del blocker
            self.manage_requested.emit(selected)
            return
        selected = self.selected_config_id()
        self._last_config_id = selected
        self._sync_enabled()
        self.selection_changed.emit(selected)

    def _emit_apply(self) -> None:
        config_id = self.selected_config_id()
        if config_id is not None:
            self.apply_requested.emit(config_id)

    def _sync_enabled(self) -> None:
        self.btn_save.setEnabled(self._has_checked)
        self.btn_apply.setEnabled(
            self._has_attached and self.selected_config_id() is not None
        )
