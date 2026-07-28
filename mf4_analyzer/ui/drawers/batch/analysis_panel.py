"""Analysis column for the batch dialog.

Composes ``MethodButtonGroup`` + ``DynamicParamForm``. Re-emits
``methodChanged(str)`` and ``paramsChanged()`` for the BatchSheet to wire
into ``_recompute_pipeline_status()``.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QRadioButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ....analysis_presets import list_builtin_presets
from .method_buttons import DynamicParamForm, MethodButtonGroup


class AnalysisPanel(QWidget):
    methodChanged = pyqtSignal(str)
    paramsChanged = pyqtSignal()
    presetApplied = pyqtSignal(str, object)  # key, full shared partial patch

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchAnalysisPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("ANALYSIS")
        title.setStyleSheet("color:#10b981;font-weight:600;font-size:13px;")
        outer.addWidget(title)

        self._method_title = QLabel("分析方法", self)
        self._method_title.setObjectName("BatchAnalysisChoiceLabel")
        outer.addWidget(self._method_title)

        self._method_group = MethodButtonGroup(self)
        outer.addWidget(self._method_group)

        self._preset_title = QLabel("分析预设", self)
        self._preset_title.setObjectName("BatchAnalysisChoiceLabel")
        outer.addWidget(self._preset_title)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(6)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self._preset_buttons: dict[str, QRadioButton] = {}
        for key, label in (
            ("torque", "频率"), ("vibration", "均衡"),
            ("transient", "时间"), ("custom", "自定义"),
        ):
            button = QRadioButton(label, self)
            button.setObjectName("BatchAnalysisPresetOption")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, preset_key=key: self._apply_builtin(preset_key)
            )
            self._preset_group.addButton(button)
            preset_row.addWidget(button, 1)
            self._preset_buttons[key] = button
        self._preset_buttons["custom"].setChecked(True)
        outer.addLayout(preset_row)

        params_title = QLabel("参数（按方法动态显示）")
        params_title.setStyleSheet("color:#475569;font-size:12px;")
        outer.addWidget(params_title)

        self._param_form = DynamicParamForm(self)
        outer.addWidget(self._param_form, 1)

        # Wiring: method change drives form re-render and re-broadcasts
        self._method_group.methodChanged.connect(self._on_method_changed)
        self._applying_builtin = False
        self._param_form.paramsChanged.connect(self._on_params_changed)

        # Seed initial state to current method (defaults to 'fft').
        self._param_form.set_method(self._method_group.current_method())
        self._refresh_preset_applicability()

    def _on_method_changed(self, method: str) -> None:
        self._param_form.set_method(method)
        self._refresh_preset_applicability()
        self._select_preset_button("custom")
        self.methodChanged.emit(method)

    def _on_params_changed(self) -> None:
        if not self._applying_builtin:
            self._select_preset_button("custom")
        self.paramsChanged.emit()

    def _select_preset_button(self, key: str) -> None:
        for name, button in self._preset_buttons.items():
            button.setChecked(name == key)

    def _refresh_preset_applicability(self) -> None:
        presets = {
            preset.key: preset
            for preset in list_builtin_presets(self.current_method())
        }
        for key in ("torque", "vibration", "transient"):
            preset = presets[key]
            button = self._preset_buttons[key]
            button.setEnabled(bool(preset.enabled))
            button.setToolTip(preset.blurb)

    def _apply_builtin(self, key: str) -> None:
        if key == "custom":
            self._select_preset_button("custom")
            return
        preset = next(
            (item for item in list_builtin_presets(self.current_method()) if item.key == key),
            None,
        )
        if preset is None or not preset.enabled:
            return
        patch = preset.params_copy()
        self._applying_builtin = True
        try:
            self._param_form.apply_params(patch)
            self._select_preset_button(key)
        finally:
            self._applying_builtin = False
        self.presetApplied.emit(key, patch)
        self.paramsChanged.emit()

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

    def set_weighting_options(self, options) -> None:
        self._param_form.set_weighting_options(options)
