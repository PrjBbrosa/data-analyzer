"""TimeContextual widget."""
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.icons import Icons
from ..widgets.record_curve_list import RecordCurveList


class TimeContextual(QWidget):
    """Time-domain contextual: replot action plus record-only visibility.

    The time domain has no analysis parameters of its own, so this widget
    deliberately owns no preset bar (the former 时域预处理预设 row snapshotted
    a dict no render path ever read). The state that *does* describe a time
    plot lives elsewhere and stays there:

    - 横坐标来源 / 时间范围 → ``PersistentTop``;
    - 滤波 → the range card's filter panel;
    - 分屏 / 叠加 / 光标模式 → the chart card toolbar
      (``chart_stack.TimeChartCard``);
    - record-only 辅助线可见性 → current ``ViewState.hidden_curve_binding_ids``.
    """

    plot_time_requested = pyqtSignal()
    record_curve_visibility_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeContextual")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 10)
        root.setSpacing(6)

        self._record_curves = RecordCurveList(self)
        self._record_curves.setVisible(False)
        self._record_curves.visibility_toggled.connect(
            self.record_curve_visibility_toggled
        )
        root.addWidget(self._record_curves)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()

    def set_record_curves(self, rows) -> None:
        self._record_curves.set_rows(rows)
