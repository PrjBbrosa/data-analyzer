from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QFontMetrics, QRegion
from PyQt5.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QSizePolicy, QWidget


class _ClippedProgressLabel(QLabel):
    """QLabel whose paint is masked to its contents rect (no overflow into the bar)."""

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # QLabel paints past its rect by default. Mask keeps '%' from landing
        # on the neighbouring progress bar when elision lags a layout pass.
        self.setMask(QRegion(self.contentsRect()))


class ComputeProgressWidget(QWidget):
    """Compact status-bar progress indicator for chart compute / file load work.

    Label and bar sit side-by-side without overlapping.  The widget grows with
    the label up to ``_MAX_WIDTH``; longer text is elided so the fixed-width
    bar stays fully visible.
    """

    _BAR_WIDTH = 160
    # QSS ``border: 1px`` on #computeProgressBar inflates the laid-out slot.
    _BAR_FRAME = 2
    _H_MARGIN = 8
    # Keep a clear gap so '%' ink cannot kiss the rounded bar tip.
    _SPACING = 12
    # Extra slack inside the sizeHint for QSS padding / ClearType overhang.
    # Elision uses the label contentsRect, which already excludes padding —
    # do not subtract this again or the design string elides by 1–2px.
    _TEXT_PAD = 6
    # Wide enough for "加载 1/1 · 读取 CAN 帧 · 100%" at the status-bar font.
    _MAX_WIDTH = 520
    _MIN_LABEL_WIDTH = 72

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("computeProgressWidget")
        self._label_prefix = ""
        self._full_label = ""

        self.label = _ClippedProgressLabel(self)
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
        # Preferred (not Maximum): status-bar permanent widgets with stretch-0
        # neighbours honor sizeHint only when the policy asks for it. Maximum
        # lets the bar keep us at minimumSizeHint while we paint full text.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setVisible(False)

    def _bar_slot_width(self) -> int:
        """Painted progress-bar slot, including QSS border inflation.

        ``setFixedWidth(_BAR_WIDTH)`` is the inner width. A 1px QSS border on
        each side makes the laid-out bar 162px; sizeHint must match or the
        label is 2px short and elides ``32%`` to ``3…``.
        """
        return max(
            self._BAR_WIDTH + self._BAR_FRAME,
            int(self.bar.width() or 0),
        )

    def _chrome_width(self) -> int:
        return (2 * self._H_MARGIN) + self._SPACING + self._bar_slot_width()

    def _text_width(self, text: str) -> int:
        """Advance width for ``text``, with a CJK-safe fallback.

        Some offscreen / substitute-font setups report ``horizontalAdvance`` 0
        for Chinese phase labels; without a fallback Preferred sizeHint
        collapses to the minimum slot and the status bar never grows.
        """
        metrics = QFontMetrics(self.label.font())
        width = metrics.horizontalAdvance(text)
        if width <= 0 and text:
            width = max(
                len(text) * max(1, metrics.averageCharWidth()),
                self._MIN_LABEL_WIDTH,
            )
        return width + self._TEXT_PAD

    def sizeHint(self) -> QSize:
        text = self._full_label or self.label.text() or " "
        label_w = self._text_width(text)
        width = min(
            self._MAX_WIDTH,
            max(
                self._chrome_width() + self._MIN_LABEL_WIDTH,
                self._chrome_width() + label_w,
            ),
        )
        height = max(22, self.label.sizeHint().height(), self.bar.sizeHint().height())
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._chrome_width() + self._MIN_LABEL_WIDTH, 22)

    def _label_text_budget(self) -> int:
        """Pixels available for painted label copy in the current layout."""
        max_budget = self._MAX_WIDTH - self._chrome_width()
        if self.width() <= self._chrome_width():
            return max_budget
        layout_budget = self.width() - self._chrome_width()
        contents = self.label.contentsRect().width()
        # contentsRect already excludes QSS padding-right. Prefer it once the
        # label has a real slot; ignore stub widths that would force "F…".
        if contents >= self._MIN_LABEL_WIDTH:
            layout_budget = min(layout_budget, contents)
        return max(self._MIN_LABEL_WIDTH, min(max_budget, layout_budget))

    def _apply_label_text(self, text: str) -> None:
        self._full_label = str(text)
        self.label.setToolTip(self._full_label)
        self.updateGeometry()
        # setVisible(True) adjustSize()'s to the *previous* sizeHint. When the
        # label grows (phase · percent) under no parent layout, grow ourselves
        # so unit tests / free hosts keep the full string. A layout-managed
        # parent (QStatusBar) owns geometry — we only elide to the slot it
        # gave us. Never leave full un-elided text on a narrow label: QLabel
        # paints past its rect and the '%' lands under the bar chunk.
        parent = self.parentWidget()
        managed = parent is not None and parent.layout() is not None
        if not managed:
            hint = self.sizeHint()
            if self.width() < hint.width():
                self.resize(hint.width(), max(self.height(), hint.height()))
        self._refresh_label_elision()

    def _refresh_label_elision(self) -> None:
        if not self._full_label:
            return
        metrics = QFontMetrics(self.label.font())
        budget = max(1, self._label_text_budget())
        full_w = metrics.horizontalAdvance(self._full_label)
        if full_w <= 0 and self._full_label:
            full_w = max(
                len(self._full_label) * max(1, metrics.averageCharWidth()),
                self._MIN_LABEL_WIDTH,
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
        # Parent may give less than sizeHint; re-elide so the bar stays
        # fully visible without the label ink overlapping it.
        self._refresh_label_elision()
