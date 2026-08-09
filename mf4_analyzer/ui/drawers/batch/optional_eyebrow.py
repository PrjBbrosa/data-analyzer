"""Soft mid-rule eyebrow for optional Batch subsections.

Option C from ``docs/analyzer/ui-prototypes/2026-08-10-batch-slice-section-separation.html``:
a pale hairline split by a quiet caption so add-on blocks (slice / chart
stats / preprocessing / …) read as secondary without a hard divider.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


class BatchOptionalEyebrow(QWidget):
    """Centered caption between two expanding soft rules."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchOptionalEyebrow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 6)
        lay.setSpacing(8)

        lay.addWidget(self._rule(), 1)
        self._label = QLabel(str(text or ""), self)
        self._label.setObjectName("BatchOptionalEyebrowLabel")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lay.addWidget(self._label, 0)
        lay.addWidget(self._rule(), 1)

    def _rule(self) -> QWidget:
        rule = QWidget(self)
        rule.setObjectName("BatchOptionalEyebrowRule")
        rule.setFixedHeight(1)
        rule.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rule.setAttribute(Qt.WA_StyledBackground, True)
        return rule

    def text(self) -> str:
        return self._label.text()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._label.setText(str(text or ""))


__all__ = ["BatchOptionalEyebrow"]
