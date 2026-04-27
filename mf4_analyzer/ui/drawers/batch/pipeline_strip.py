"""Top summary strip: three pipeline-stage cards (INPUT / ANALYSIS / OUTPUT)."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


_STAGE_DEFS = [
    {"index": 1, "title": "INPUT", "color": "#3b82f6"},
    {"index": 2, "title": "ANALYSIS", "color": "#10b981"},
    {"index": 3, "title": "OUTPUT", "color": "#f59e0b"},
]


class PipelineCard(QFrame):
    def __init__(self, stage_def, parent=None):
        super().__init__(parent)
        self._stage_def = stage_def
        self.stage_status = "pending"
        self.setObjectName("PipelineCard")
        self.setStyleSheet(
            f"#PipelineCard {{background:#fff;border:1px solid #cbd5e1;"
            f"border-top:4px solid {stage_def['color']};border-radius:10px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        title = QLabel(f"{stage_def['index']}. {stage_def['title']}")
        title.setStyleSheet(f"color:{stage_def['color']};font-weight:600;font-size:14px;")
        lay.addWidget(title)
        self.summary_label = QLabel("未配置")
        self.summary_label.setStyleSheet("color:#475569;font-size:12px;")
        self.summary_label.setWordWrap(True)
        lay.addWidget(self.summary_label)
        self.badge_label = QLabel("⚠")
        self.badge_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.badge_label.setStyleSheet("color:#f59e0b;")
        title_row = lay.itemAt(0).widget()
        # badge stacked into title row via separate horizontal sub-layout
        # (kept simple here)


class PipelineStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.cards: list[PipelineCard] = []
        for d in _STAGE_DEFS:
            c = PipelineCard(d, self)
            lay.addWidget(c, 1)
            self.cards.append(c)

    def set_stage(self, stage_index: int, status: str, summary_text: str):
        c = self.cards[stage_index]
        c.stage_status = status
        c.summary_label.setText(summary_text)
        badge_map = {"ok": "✓", "warn": "⚠", "pending": "⏸"}
        color_map = {"ok": "#10b981", "warn": "#f59e0b", "pending": "#94a3b8"}
        c.badge_label.setText(badge_map.get(status, "⚠"))
        c.badge_label.setStyleSheet(f"color:{color_map.get(status, '#94a3b8')};")
