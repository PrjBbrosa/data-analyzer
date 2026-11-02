"""Read-only import details, owned by the file card that opened them."""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from ...io.import_diagnostics import get_import_diagnostics, uncovered_legacy_metadata
from ...io.loader import (
    format_dropped_channels_notice, format_renamed_channels_notice,
    format_skipped_channels_notice, format_skipped_vars_notice,
)


_STATE_LABELS = {"complete": "正常导入", "warning": "导入提示", "partial": "部分导入"}
_COUNT_LABELS = {
    "imported_channels": "已导入通道", "declared_channels": "声明通道",
    "skipped_channels": "未导入通道", "parsed_records": "已解析记录",
    "declared_records": "声明记录",
    "sample_count": "采样点数", "count_scope": "计数范围",
}


def import_details_text(sources):
    """Keep group identities visible while deduplicating shared file issues."""
    lines = []
    issues = {}
    for identity, label, metadata in sources:
        source_label = f"{label} [{identity}]"
        lines.append(source_label)
        payload = get_import_diagnostics(metadata)
        legacy = uncovered_legacy_metadata(metadata)
        notices = [
            *(str(warning) for warning in legacy.get("warnings") or ()),
            format_dropped_channels_notice(legacy.get("dropped_channels") or []),
            format_skipped_channels_notice(legacy.get("skipped_channels") or []),
            format_skipped_vars_notice(legacy.get("skipped_vars") or []),
            format_renamed_channels_notice(legacy.get("renamed_channels") or []),
        ]
        if payload is None:
            lines.append("  导入诊断未记录；不代表已确认无异常。")
            # Existing formats can still have useful facts before adoption of
            # the structured schema. Do not label them complete.
            for notice in notices:
                if notice:
                    lines.append(f"  {notice}")
            lines.append("")
            continue
        lines.append(f"  状态：{_STATE_LABELS[payload['state']]}")
        for notice in notices:
            if notice:
                lines.append(f"  {notice}")
        for key, value in payload.get("counts", {}).items():
            if key == "count_scope":
                value = {"file": "整个文件", "group": "当前来源"}.get(value, value)
            lines.append(f"  {_COUNT_LABELS.get(key, key)}：{value}")
        lines.append("")
        for issue in payload["issues"]:
            key = (str(metadata.get("source_path") or metadata.get("source_filename") or ""),
                   json.dumps(issue, ensure_ascii=False, sort_keys=True))
            if key not in issues:
                issues[key] = (issue, [])
            issues[key][1].append(source_label)
    if issues:
        lines.append("异常与处理")
    for index, (issue, owners) in enumerate(issues.values(), 1):
        lines.append(f"{index}. {issue.get('message') or issue['code']}")
        lines.append("   来源：" + "、".join(dict.fromkeys(owners)))
        where = []
        if issue.get("record_index") is not None:
            where.append(f"记录 {int(issue['record_index']) + 1}")
        if issue.get("channel"):
            where.append(f"通道 {issue['channel']}")
        if issue.get("offset") is not None:
            where.append(f"偏移 0x{int(issue['offset']):x}")
        source_rows = issue.get("source_rows") or issue.get("rows")
        if source_rows:
            where.append("原始行 " + ", ".join(map(str, source_rows)))
        if where:
            lines.append("   " + " · ".join(where))
        lines.append("")
    return "\n".join(lines).strip()


class ImportDiagnosticsDialog(QDialog):
    def __init__(self, sources, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入详情")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(640, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("本次读取的结果与异常", self)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setPlainText(import_details_text(sources))
        self._details.setAccessibleName("导入结果与异常明细")
        layout.addWidget(self._details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
