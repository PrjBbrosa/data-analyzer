from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QSizePolicy, QWidget


class ComputeProgressWidget(QWidget):
    """Compact status-bar progress indicator for chart compute / file load work.

    Label and bar sit side-by-side without overlapping.  The widget grows with
    the label up to ``_MAX_WIDTH``; longer text is elided so the fixed-width
    bar stays fully visible.
    """

    _BAR_WIDTH = 160
    _H_MARGIN = 8
    _SPACING = 8
    # Wide enough for "加载 1/1 · 读取 CAN 帧 · 100%" at the status-bar font.
    _MAX_WIDTH = 520
    _MIN_LABEL_WIDTH = 72

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("computeProgressWidget")
        self._label_prefix = ""
        self._full_label = ""

        self.label = QLabel(self)
        self.label.setObjectName("computeProgressLabel")
        self.label.setTextFormat(Qt.PlainText)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.label.setMinimumWidth(self._MIN_LABEL_WIDTH)
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.bar = QProgressBar(self)
        self.bar.setObjectName("computeProgressBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(self._BAR_WIDTH)
        self.bar.setFixedHeight(8)
        self.bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._H_MARGIN, 0, self._H_MARGIN, 0)
        layout.setSpacing(self._SPACING)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.bar, 0)
        layout.setAlignment(self.bar, Qt.AlignVCenter)

        self.setMaximumWidth(self._MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setVisible(False)

    def _chrome_width(self) -> int:
        return (2 * self._H_MARGIN) + self._SPACING + self._BAR_WIDTH

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.label.font())
        text = self._full_label or self.label.text() or " "
        label_w = metrics.horizontalAdvance(text) + 4
        width = min(
            self._MAX_WIDTH,
            max(self._chrome_width() + self._MIN_LABEL_WIDTH, self._chrome_width() + label_w),
        )
        height = max(22, self.label.sizeHint().height(), self.bar.sizeHint().height())
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._chrome_width() + self._MIN_LABEL_WIDTH, 22)

    def _apply_label_text(self, text: str) -> None:
        self._full_label = str(text)
        self.label.setToolTip(self._full_label)
        self._refresh_label_elision(prefer_max_budget=True)
        self.updateGeometry()

    def _refresh_label_elision(self, *, prefer_max_budget: bool) -> None:
        if not self._full_label:
            return
        metrics = QFontMetrics(self.label.font())
        full_w = metrics.horizontalAdvance(self._full_label) + 4
        max_budget = self._MAX_WIDTH - self._chrome_width()
        if prefer_max_budget:
            # Grow toward the max first so a longer phase label is not elided
            # against the previous, shorter sizeHint width.
            budget = max_budget
        else:
            budget = max(
                self._MIN_LABEL_WIDTH,
                min(max_budget, self.width() - self._chrome_width()),
            )
        if full_w <= budget:
            self.label.setText(self._full_label)
        else:
            self.label.setText(
                metrics.elidedText(self._full_label, Qt.ElideRight, budget)
            )

    def begin(self, label: str, total: int | None = None) -> None:
        self._label_prefix = str(label)
        self._apply_label_text(self._label_prefix)
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
            self._label_prefix = str(label)
        if total <= 0:
            self.bar.setRange(0, 0)
            self._apply_label_text(self._label_prefix)
            self.setVisible(True)
            return

        total_value = int(total)
        current_value = max(0, min(int(current), total_value))
        self.bar.setRange(0, total_value)
        self.bar.setValue(current_value)
        percentage = int(round(100 * current_value / total_value))
        self._apply_label_text(f"{self._label_prefix} · {percentage}%")
        self.setVisible(True)

    def finish(self, label: str | None = None) -> None:
        if label is not None:
            self._apply_label_text(label)
        self.setVisible(False)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # Parent may give less than sizeHint; elide only then so the bar stays
        # fully visible without overlapping the label.
        self._refresh_label_elision(prefer_max_budget=False)
