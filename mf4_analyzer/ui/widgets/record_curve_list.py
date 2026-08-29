"""Presentation-only list of WinWert record-only auxiliary curves.

The widget emits ``binding_id + visible``. MainWindow owns ViewState writes.
"""
from __future__ import annotations

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.icons import Icons


class RecordCurveList(QWidget):
    visibility_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("recordCurveList")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(4)
        heading = QLabel("WinWert 原始记录")
        heading.setObjectName("recordCurveHeading")
        root.addWidget(heading)
        self._rows_host = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        root.addWidget(self._rows_host)
        self._row_widgets: list[QWidget] = []

    def set_rows(self, rows) -> None:
        for widget in self._row_widgets:
            self._rows_layout.removeWidget(widget)
            widget.deleteLater()
        self._row_widgets = []
        for row in rows or ():
            widget = _RecordCurveRow(
                binding_id=str(row.get("binding_id") or ""),
                name=str(row.get("name") or ""),
                color=str(row.get("color") or "#64748b"),
                visible=bool(row.get("visible", True)),
                parent=self._rows_host,
            )
            widget.visibility_toggled.connect(self.visibility_toggled)
            self._rows_layout.addWidget(widget)
            self._row_widgets.append(widget)
        self.setVisible(bool(self._row_widgets))


class _RecordCurveRow(QWidget):
    visibility_toggled = pyqtSignal(str, bool)

    def __init__(self, *, binding_id, name, color, visible, parent=None):
        super().__init__(parent)
        self.setObjectName("recordCurveRow")
        self._binding_id = str(binding_id)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setObjectName("recordCurveSwatch")
        parsed = QColor(color)
        if not parsed.isValid():
            parsed = QColor("#64748b")
        swatch.setStyleSheet(
            f"background-color: {parsed.name()}; border-radius: 5px;"
        )
        layout.addWidget(swatch, 0, Qt.AlignVCenter)
        text = QWidget(self)
        text_lay = QVBoxLayout(text)
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(0)
        title = QLabel(name or self._binding_id)
        title.setObjectName("recordCurveName")
        source = QLabel("WinWert 原始记录")
        source.setObjectName("recordCurveSource")
        source.setStyleSheet("color: #64748b;")
        text_lay.addWidget(title)
        text_lay.addWidget(source)
        layout.addWidget(text, 1)
        self._eye = QToolButton(self)
        self._eye.setObjectName("recordCurveEye")
        self._eye.setAutoRaise(True)
        self._eye.setCheckable(True)
        self._eye.setChecked(bool(visible))
        self._eye.setIconSize(QSize(16, 16))
        self._sync_eye()
        self._eye.toggled.connect(self._on_toggled)
        layout.addWidget(self._eye, 0, Qt.AlignVCenter)
        self.setFixedHeight(28)

    def _sync_eye(self) -> None:
        visible = self._eye.isChecked()
        self._eye.setIcon(Icons.eye_open() if visible else Icons.eye_closed())
        self._eye.setToolTip("显示" if visible else "隐藏")
        self._eye.setAccessibleName(
            "显示原始记录" if visible else "隐藏原始记录"
        )

    def _on_toggled(self, visible: bool) -> None:
        self._sync_eye()
        self.visibility_toggled.emit(self._binding_id, bool(visible))
