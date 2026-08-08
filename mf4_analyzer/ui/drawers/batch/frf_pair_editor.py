"""Compact Batch FRF input/output rule editor.

The widget owns only portable authoring intent.  Runtime source/group identity
stays in the neutral resolver; combo/list text is presentation and channel data
is always read from ``Qt.UserRole``.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ....batch_types import FrfPairRule


@dataclass
class _PairGroup:
    host: QFrame
    title: QLabel
    input_combo: QComboBox
    outputs: QListWidget
    remove_button: QPushButton


class FrfPairEditor(QWidget):
    """Edit one-input/many-output portable FRF pairing groups."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchFrfPairEditor")
        self._common: tuple[str, ...] = ()
        self._partial: dict[str, str] = {}
        self._policy = "common"
        self._source_count = 0
        self._groups: list[_PairGroup] = []
        self._applying = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self._groups_layout = QVBoxLayout()
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(6)
        outer.addLayout(self._groups_layout)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self._validation = QLabel(self)
        self._validation.setObjectName("BatchFrfPairValidation")
        self._validation.setWordWrap(True)
        self._validation.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        footer.addWidget(self._validation, 1)
        self._add_button = QPushButton("+ 添加配对组", self)
        self._add_button.setProperty("role", "tool")
        self._add_button.clicked.connect(self.add_group)
        footer.addWidget(self._add_button)
        outer.addLayout(footer)
        self._task_summary = QLabel("待选择 FRF 输入/输出", self)
        self._task_summary.setObjectName("BatchFrfPairFacts")
        self._task_summary.setWordWrap(True)
        outer.addWidget(self._task_summary)
        self.add_group(emit=False)

    def _candidate_items(self) -> tuple[tuple[str, str], ...]:
        items = [(name, name) for name in self._common]
        if self._policy == "available_per_source":
            items.extend(
                (f"{name} {suffix}".strip(), name)
                for name, suffix in self._partial.items()
                if name not in self._common
            )
        return tuple(items)

    @staticmethod
    def _input_value(group: _PairGroup) -> str:
        return str(group.input_combo.currentData(Qt.UserRole) or "")

    @staticmethod
    def _output_values(group: _PairGroup) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.UserRole) or "")
            for item in group.outputs.selectedItems()
            if str(item.data(Qt.UserRole) or "")
        )

    def _populate_group(
        self, group: _PairGroup, input_channel: str, outputs: tuple[str, ...]
    ) -> None:
        candidates = list(self._candidate_items())
        known = {value for _label, value in candidates}
        for value in (input_channel, *outputs):
            if value and value not in known:
                candidates.append((f"{value} · 当前来源不可用", value))
                known.add(value)
        group.input_combo.blockSignals(True)
        group.outputs.blockSignals(True)
        try:
            group.input_combo.clear()
            group.input_combo.addItem("请选择输入", "")
            group.outputs.clear()
            for label, value in candidates:
                group.input_combo.addItem(label, value)
                item = QListWidgetItem(label, group.outputs)
                item.setData(Qt.UserRole, value)
                item.setToolTip(f"通道身份：{value}")
                if value in outputs:
                    item.setSelected(True)
            index = group.input_combo.findData(input_channel, Qt.UserRole)
            group.input_combo.setCurrentIndex(max(0, index))
        finally:
            group.outputs.blockSignals(False)
            group.input_combo.blockSignals(False)

    def add_group(self, _checked=False, *, emit: bool = True) -> int:
        host = QFrame(self)
        host.setObjectName("BatchFrfPairGroup")
        grid = QGridLayout(host)
        grid.setContentsMargins(7, 6, 7, 7)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        title = QLabel(host)
        title.setObjectName("BatchFrfPairGroupTitle")
        remove = QPushButton("删除", host)
        remove.setProperty("role", "tool")
        remove.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        input_combo = QComboBox(host)
        input_combo.setMinimumWidth(0)
        input_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        outputs = QListWidget(host)
        outputs.setSelectionMode(QAbstractItemView.MultiSelection)
        outputs.setFixedHeight(84)
        outputs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid.addWidget(title, 0, 0)
        grid.addWidget(remove, 0, 1, Qt.AlignRight)
        grid.addWidget(QLabel("输入", host), 1, 0)
        grid.addWidget(input_combo, 1, 1)
        grid.addWidget(QLabel("输出（可多选）", host), 2, 0, Qt.AlignTop)
        grid.addWidget(outputs, 2, 1)
        grid.setColumnStretch(1, 1)
        group = _PairGroup(host, title, input_combo, outputs, remove)
        self._groups.append(group)
        self._groups_layout.addWidget(host)
        input_combo.currentIndexChanged.connect(self._on_changed)
        outputs.itemSelectionChanged.connect(self._on_changed)
        remove.clicked.connect(lambda _checked=False, g=group: self._remove_group_object(g))
        self._populate_group(group, "", ())
        self._refresh_titles()
        self._refresh_validation()
        if emit:
            self.changed.emit()
        return len(self._groups) - 1

    def _remove_group_object(self, group: _PairGroup) -> None:
        try:
            index = self._groups.index(group)
        except ValueError:
            return
        self.remove_group(index)

    def remove_group(self, index: int) -> None:
        if len(self._groups) <= 1 or not 0 <= int(index) < len(self._groups):
            return
        group = self._groups.pop(int(index))
        self._groups_layout.removeWidget(group.host)
        group.host.deleteLater()
        self._refresh_titles()
        self._refresh_validation()
        self.changed.emit()

    def _refresh_titles(self) -> None:
        for index, group in enumerate(self._groups, 1):
            group.title.setText(f"配对组 {index}")
            group.remove_button.setEnabled(len(self._groups) > 1)

    def _on_changed(self, *_args) -> None:
        if self._applying:
            return
        self._refresh_validation()
        self.changed.emit()

    def set_channel_universe(
        self,
        common,
        partial,
        *,
        policy: str,
        source_count: int,
    ) -> None:
        snapshots = tuple(
            (self._input_value(group), self._output_values(group))
            for group in self._groups
        )
        self._common = tuple(dict.fromkeys(str(x) for x in common if str(x)))
        self._partial = {
            str(name): str(suffix) for name, suffix in dict(partial or {}).items()
            if str(name)
        }
        self._policy = (
            "available_per_source"
            if str(policy) == "available_per_source" else "common"
        )
        self._source_count = max(0, int(source_count))
        self._applying = True
        try:
            for group, (input_channel, outputs) in zip(self._groups, snapshots):
                self._populate_group(group, input_channel, outputs)
        finally:
            self._applying = False
        self._refresh_validation()

    def set_group_values(self, index: int, input_channel: str, outputs) -> None:
        group = self._groups[int(index)]
        self._applying = True
        try:
            self._populate_group(
                group, str(input_channel or ""),
                tuple(dict.fromkeys(str(x) for x in outputs if str(x))),
            )
        finally:
            self._applying = False
        self._refresh_validation()
        self.changed.emit()

    def apply_rules(self, rules) -> None:
        values = tuple(rules or ())
        while len(self._groups) < max(1, len(values)):
            self.add_group(emit=False)
        while len(self._groups) > max(1, len(values)):
            group = self._groups.pop()
            self._groups_layout.removeWidget(group.host)
            group.host.deleteLater()
        self._applying = True
        try:
            if not values:
                self._populate_group(self._groups[0], "", ())
            for group, value in zip(self._groups, values):
                rule = value if isinstance(value, FrfPairRule) else FrfPairRule(
                    value.get("input_channel", ""),
                    tuple(value.get("output_channels") or ()),
                )
                self._populate_group(group, rule.input_channel, rule.output_channels)
        finally:
            self._applying = False
        self._refresh_titles()
        self._refresh_validation()
        self.changed.emit()

    def _issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        seen: set[tuple[str, str]] = set()
        available = set(self._common)
        if self._policy == "available_per_source":
            available.update(self._partial)
        for index, group in enumerate(self._groups, 1):
            input_channel = self._input_value(group)
            outputs = self._output_values(group)
            if not input_channel:
                issues.append(f"配对组 {index}：请选择输入")
                continue
            if not outputs:
                issues.append(f"配对组 {index}：至少选择一个输出")
                continue
            if self._source_count and input_channel not in available:
                issues.append(
                    f"配对组 {index}：输入 {input_channel} 在当前来源不可用"
                )
            missing_outputs = tuple(value for value in outputs if value not in available)
            if self._source_count and missing_outputs:
                issues.append(
                    f"配对组 {index}：输出 {', '.join(missing_outputs)} "
                    "在当前来源不可用"
                )
            if input_channel in outputs:
                issues.append(f"配对组 {index}：输入与输出不能相同")
            for output in outputs:
                pair = (input_channel, output)
                if pair in seen:
                    issues.append(
                        f"配对组 {index}：{output} / {input_channel} 重复"
                    )
                seen.add(pair)
        return tuple(issues)

    def _refresh_validation(self) -> None:
        issues = self._issues()
        self._validation.setText(issues[0] if issues else "")
        self._validation.setProperty("invalid", bool(issues))
        pairs = sum(len(self._output_values(group)) for group in self._groups)
        if pairs and not issues:
            policy = "按来源可用" if self._policy == "available_per_source" else "全部来源共有"
            self._task_summary.setText(
                f"{pairs} 个方向对 · {self._source_count} 个逻辑来源 · {policy}"
            )
        else:
            self._task_summary.setText(issues[0] if issues else "待选择 FRF 输入/输出")
        self._validation.style().unpolish(self._validation)
        self._validation.style().polish(self._validation)

    def validation_message(self) -> str:
        issues = self._issues()
        return issues[0] if issues else ""

    def rules(self) -> tuple[FrfPairRule, ...]:
        if self._issues():
            return ()
        return tuple(
            FrfPairRule(self._input_value(group), self._output_values(group))
            for group in self._groups
        )

    def selected_channels(self) -> tuple[str, ...]:
        values: list[str] = []
        for group in self._groups:
            for value in (self._input_value(group), *self._output_values(group)):
                if value and value not in values:
                    values.append(value)
        return tuple(values)

    def task_summary_text(self) -> str:
        return self._task_summary.text()

    def group_count(self) -> int:
        return len(self._groups)


__all__ = ["FrfPairEditor"]
