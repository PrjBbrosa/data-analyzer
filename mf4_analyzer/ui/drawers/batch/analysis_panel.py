"""Analysis column for the batch dialog.

Composes ``MethodButtonGroup`` + ``DynamicParamForm``. Re-emits
``methodChanged(str)`` and ``paramsChanged()`` for the BatchSheet to wire
into ``_recompute_pipeline_status()``.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from .method_buttons import DynamicParamForm, MethodButtonGroup


class AnalysisPanel(QWidget):
    methodChanged = pyqtSignal(str)
    paramsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchAnalysisPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("ANALYSIS")
        title.setStyleSheet("color:#10b981;font-weight:600;font-size:13px;")
        outer.addWidget(title)

        self._method_group = MethodButtonGroup(self)
        outer.addWidget(self._method_group)

        params_title = QLabel("参数（按方法动态显示）")
        params_title.setStyleSheet("color:#475569;font-size:12px;")
        outer.addWidget(params_title)

        self._param_form = DynamicParamForm(self)
        outer.addWidget(self._param_form, 1)

        # Wiring: method change drives form re-render and re-broadcasts
        self._method_group.methodChanged.connect(self._on_method_changed)
        self._param_form.paramsChanged.connect(self.paramsChanged.emit)

        # Seed initial state to current method (defaults to 'fft').
        self._param_form.set_method(self._method_group.current_method())

    def _on_method_changed(self, method: str) -> None:
        self._param_form.set_method(method)
        self.methodChanged.emit(method)

    # ------------------------------------------------------------------
    def current_method(self) -> str:
        return self._method_group.current_method()

    def set_method(self, method: str) -> None:
        self._method_group.set_method(method)

    def get_params(self) -> dict:
        return self._param_form.get_params()

    def apply_method(self, method: str) -> None:
        self.set_method(method)

    def apply_params(self, params: dict) -> None:
        self._param_form.apply_params(params)
