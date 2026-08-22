"""UltraView status-bar hint host.

Presentation-only. ChartStack can later take this widget; Page keeps the
compatibility identity through the widgets façade.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from .._helpers import ULTRAVIEW_HINT_BAR_HEIGHT


class UltraViewHintBar(QFrame):
    """Status-bar hint host. ChartStack can later take this widget."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartHintBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ULTRAVIEW_HINT_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        # Equal 3px vertical padding keeps a 22px inner slot so the styled
        # ``?`` and 11px copy stay centered and unclipped in a 28px strip.
        layout.setContentsMargins(10, 3, 8, 3)
        layout.setSpacing(4)
        self._quickref = QToolButton(self)
        self._quickref.setObjectName("chartHintQuickrefButton")
        self._quickref.setText("?")
        self._quickref.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._quickref.setAutoRaise(True)
        self._quickref.setCursor(Qt.PointingHandCursor)
        self._quickref.setToolTip("操作速查")
        self._quickref.clicked.connect(self.quickref_requested.emit)
        self._context = QLabel("拖卡片移动 · 左键框选 · 右键拖动画布 · Ctrl+滚轮缩放", self)
        self._context.setObjectName("chartHintContext")
        self._context.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._context.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._context.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        self._discovery = QLabel("UltraView 不计算", self)
        self._discovery.setObjectName("chartHintDiscovery")
        self._discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._discovery.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._discovery.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        layout.addWidget(self._quickref, 0, Qt.AlignVCenter)
        layout.addWidget(self._context, 1, Qt.AlignVCenter)
        layout.addWidget(self._discovery, 0, Qt.AlignVCenter)
