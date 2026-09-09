"""Flat three-stage summary strip for the compact batch workflow."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget


_STAGE_DEFS = (
    {"index": 2, "title": "文件与目标"},
    {"index": 3, "title": "分析参数"},
    {"index": 4, "title": "输出"},
)


class PipelineCard(QFrame):
    """One flat stage cell; status changes facts, not the information shape."""

    def __init__(self, stage_def, *, last: bool = False, parent=None):
        super().__init__(parent)
        self._stage_def = stage_def
        self.stage_status = "pending"
        self.setObjectName("BatchPipelineStage")
        self.setProperty("stageIndex", int(stage_def["index"]))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14 if last else 0, 0)
        layout.setSpacing(7)

        self.number_label = QLabel(f"{int(stage_def['index']):02d}", self)
        self.number_label.setObjectName("BatchPipelineNumber")
        self.number_label.setFixedSize(22, 22)
        self.number_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.number_label)

        self.title_label = QLabel(str(stage_def["title"]), self)
        self.title_label.setObjectName("BatchPipelineTitle")
        layout.addWidget(self.title_label)

        self.summary_label = QLabel("未配置", self)
        self.summary_label.setObjectName("BatchPipelineFact")
        self.summary_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self.summary_label, 1)
        if not last:
            divider = QFrame(self)
            divider.setObjectName("BatchPipelineDivider")
            divider.setFixedSize(1, 16)
            layout.addWidget(divider, 0, Qt.AlignVCenter)

        # Kept for API compatibility with older tests/callers. The compact
        # strip communicates state through the fact text.
        self.badge_label = QLabel("", self)
        self.badge_label.hide()


class PipelineStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchPipelineStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.cards: list[PipelineCard] = []
        for index, definition in enumerate(_STAGE_DEFS):
            card = PipelineCard(
                definition, last=index == len(_STAGE_DEFS) - 1, parent=self,
            )
            layout.addWidget(card, (29, 39, 32)[index])
            self.cards.append(card)

    def set_stage(self, stage_index: int, status: str, summary_text: str):
        card = self.cards[stage_index]
        card.stage_status = status
        card.setProperty("stageStatus", str(status))
        card.summary_label.setText(str(summary_text))
        card.style().unpolish(card)
        card.style().polish(card)
