"""Compact actions for reusable named channel-selection configurations."""
from __future__ import annotations

from collections.abc import Iterable

from PyQt5.QtCore import QSignalBlocker, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from ..channel_config import ChannelSelectionConfig
from ...ui_kit.combo_popup_shell import prepare_combo_popup


CONFIG_NAME_ROLE = Qt.UserRole + 1
CHANNEL_COUNT_ROLE = Qt.UserRole + 2
ITEM_KIND_ROLE = Qt.UserRole + 3


class _ChannelConfigItemDelegate(QStyledItemDelegate):
    """Draw the compact config picker as an aligned two-column list."""

    def sizeHint(self, option, index):  # noqa: N802
        kind = index.data(ITEM_KIND_ROLE)
        if kind == "separator":
            return QSize(option.rect.width(), 10)
        if kind == "config":
            return QSize(option.rect.width(), 44)
        return QSize(option.rect.width(), 38)

    def paint(self, painter, option, index):  # noqa: N802
        kind = index.data(ITEM_KIND_ROLE)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        if kind == "separator":
            painter.setPen(QColor("#dfe5ee"))
            painter.drawLine(rect.left() + 12, rect.center().y(), rect.right() - 12, rect.center().y())
            painter.restore()
            return

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        surface = rect.adjusted(4, 2, -4, -2)
        if selected or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#dbeafe") if selected else QColor("#f1f5f9"))
            painter.drawRoundedRect(surface, 7, 7)

        title = str(index.data(CONFIG_NAME_ROLE) or index.data(Qt.DisplayRole) or "")
        if kind == "config":
            count = int(index.data(CHANNEL_COUNT_ROLE) or 0)
            title_rect = surface.adjusted(10, 0, -78, 0)
            count_rect = surface.adjusted(0, 0, -12, 0)
            font = QFont(option.font)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor("#0f3f8f") if selected else QColor("#1f2937"))
            painter.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, title)
            meta_font = QFont(option.font)
            meta_font.setPointSizeF(max(8.5, meta_font.pointSizeF() - 1))
            painter.setFont(meta_font)
            painter.setPen(QColor("#1769e0") if selected else QColor("#64748b"))
            painter.drawText(count_rect, Qt.AlignVCenter | Qt.AlignRight, f"{count} 个通道")
        else:
            font = QFont(option.font)
            font.setWeight(QFont.Medium)
            painter.setFont(font)
            painter.setPen(QColor("#475569"))
            painter.drawText(surface.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, title)
        painter.restore()


class _ChannelConfigComboBox(QComboBox):
    """A bottom-bar selector whose menu expands into the available space."""

    def showPopup(self):  # noqa: N802
        self._sync_popup_geometry()
        prepare_combo_popup(self)
        super().showPopup()
        QTimer.singleShot(0, self._move_popup_above_anchor)

    def _sync_popup_geometry(self):
        """Keep the shared popup shell wide enough without creating a scroll trap."""
        view = self.view()
        visible_rows = min(self.count(), self.maxVisibleItems())
        row_heights = [
            max(1, view.sizeHintForRow(index))
            for index in range(visible_rows)
        ]
        # The shared shell gives the viewport a 6px inset on both edges plus
        # a 1px border. A fixed visible-row height prevents Qt's native combo
        # container from stretching rows to fill a tall available area (and
        # then clipping the
        # management action below a scrollbar).
        height = 14 + sum(row_heights)
        view.setMinimumHeight(height)
        view.setMaximumHeight(height)

    def _move_popup_above_anchor(self):
        popup = self.view().window()
        if popup is None or not popup.isVisible():
            return
        anchor = self.mapToGlobal(self.rect().topLeft())
        popup.move(anchor.x(), anchor.y() - popup.height())


class ChannelConfigBar(QWidget):
    """Save / pending-config / Apply controls with no apply-on-select behavior."""

    save_requested = pyqtSignal()
    apply_requested = pyqtSignal(str)
    manage_requested = pyqtSignal(object)
    selection_changed = pyqtSignal(object)

    MANAGE_SENTINEL = "__manage_configs__"
    ACTION_WIDTH = 64
    # 28px controls + 2px host inset (channel_tree) share the 30px View rail.
    # Keep the 22px base text box and only tighten vertical padding; do not
    # drop to the 24px compact track.
    CONTROL_HEIGHT = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.setFixedHeight(self.CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_save = QPushButton("保存", self)
        self.btn_save.setObjectName("channelConfigSave")
        # Save is a peer action to Apply here, not icon-sized toolbar chrome.
        self.btn_save.setProperty("role", "primary")
        self.btn_save.setFixedWidth(self.ACTION_WIDTH)
        self.btn_save.setFixedHeight(self.CONTROL_HEIGHT)
        self.btn_save.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.combo = _ChannelConfigComboBox(self)
        self.combo.setObjectName("channelConfigCombo")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMinimumWidth(132)
        self.combo.setFixedHeight(self.CONTROL_HEIGHT)
        self.combo.setMaxVisibleItems(8)
        self.combo.setProperty("popupStyle", "channel-config")
        self.combo.setProperty("popupMinWidth", 320)
        self.combo.setItemDelegate(_ChannelConfigItemDelegate(self.combo))
        self.combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.combo.completer().setFilterMode(Qt.MatchContains)

        self.btn_apply = QPushButton("应用", self)
        self.btn_apply.setObjectName("channelConfigApply")
        self.btn_apply.setProperty("role", "primary")
        self.btn_apply.setFixedWidth(self.ACTION_WIDTH)
        self.btn_apply.setFixedHeight(self.CONTROL_HEIGHT)
        self.btn_apply.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout.addWidget(self.btn_save, 0)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.btn_apply, 0)

        self._has_checked = False
        self._has_attached = False
        self._last_config_id: str | None = None

        self.btn_save.clicked.connect(self.save_requested)
        self.btn_apply.clicked.connect(self._emit_apply)
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        self.combo.editTextChanged.connect(self._sync_enabled)

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
        self.combo.addItem("选配置…", None)
        self.combo.setItemData(0, "placeholder", ITEM_KIND_ROLE)
        for config in configs:
            count = len(config.channel_names)
            # The selected state needs only the name.  The popup delegate
            # still renders the channel count in a dedicated right column.
            self.combo.addItem(config.name, config.config_id)
            idx = self.combo.count() - 1
            self.combo.setItemData(idx, config.name, CONFIG_NAME_ROLE)
            self.combo.setItemData(idx, count, CHANNEL_COUNT_ROLE)
            self.combo.setItemData(idx, "config", ITEM_KIND_ROLE)
            self.combo.setItemData(
                idx,
                f"{config.name}\n{count} 个通道\n更新于 {config.updated_at}",
                Qt.ToolTipRole,
            )
        if configs:
            self.combo.insertSeparator(self.combo.count())
            self.combo.setItemData(self.combo.count() - 1, "separator", ITEM_KIND_ROLE)
        self.combo.addItem("管理通道配置…", self.MANAGE_SENTINEL)
        self.combo.setItemData(self.combo.count() - 1, "manage", ITEM_KIND_ROLE)
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
        index = self.combo.currentIndex()
        if index < 0 or self.combo.currentText() != self.combo.itemText(index):
            return None
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
