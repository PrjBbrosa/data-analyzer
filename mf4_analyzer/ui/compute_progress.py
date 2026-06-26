from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QSizePolicy, QWidget


class ComputeProgressWidget(QWidget):
    """Compact status-bar progress indicator for chart compute work."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("computeProgressWidget")

        self.label = QLabel(self)
        self.label.setObjectName("computeProgressLabel")

        self.bar = QProgressBar(self)
        self.bar.setObjectName("computeProgressBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(160)
        self.bar.setFixedHeight(8)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setVisible(False)

    def begin(self, label: str, total: int | None = None) -> None:
        self.label.setText(label)
        if total is None or total <= 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, int(total))
            self.bar.setValue(0)
        self.setVisible(True)

    def set_progress(
        self,
        current: int,
        total: int,
        label: str | None = None,
    ) -> None:
        if label is not None:
            self.label.setText(label)
        if total <= 0:
            self.bar.setRange(0, 0)
            self.setVisible(True)
            return

        total_value = int(total)
        current_value = max(0, min(int(current), total_value))
        self.bar.setRange(0, total_value)
        self.bar.setValue(current_value)
        self.setVisible(True)

    def finish(self, label: str | None = None) -> None:
        if label is not None:
            self.label.setText(label)
        self.setVisible(False)
