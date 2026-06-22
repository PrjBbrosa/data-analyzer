"""TimeContextual widget."""
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.icons import Icons


class TimeContextual(QWidget):
    """Time-domain contextual: just the manual replot button.

    Plot-mode and cursor-mode controls have been relocated to the chart
    card toolbar (see chart_stack.TimeChartCard).
    """

    plot_time_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeContextual")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(0)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()
