"""TimeContextual widget."""
from copy import deepcopy

from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...analysis_presets import list_builtin_presets
from ...ui_kit.icons import Icons
from ._helpers import CUSTOM_PRESET_SLOTS
from .presets import PresetBar


class _TimePresetBar(PresetBar):
    """Preset bar whose disabled signal types survive every state refresh."""

    def __init__(self, *args, enabled_by_slot: dict[int, bool], **kwargs):
        self._enabled_by_slot = dict(enabled_by_slot)
        super().__init__(*args, **kwargs)

    def _refresh_states(self):
        super()._refresh_states()
        for slot, enabled in self._enabled_by_slot.items():
            button = self._load_btns.get(slot)
            if button is not None:
                button.setEnabled(enabled)


class TimeContextual(QWidget):
    """Time-domain contextual: preprocessing presets plus manual replot.

    Plot-mode and cursor-mode controls have been relocated to the chart
    card toolbar (see chart_stack.TimeChartCard).
    """

    plot_time_requested = pyqtSignal()
    time_preset_applied = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeContextual")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 10)
        root.setSpacing(6)

        self._params: dict = {}
        presets = list_builtin_presets("time")
        builtin_defaults = {
            preset.slot: {
                "display_name": preset.display_name,
                "params": preset.params_copy(),
            }
            for preset in presets
        }
        label = QLabel("时域预处理预设", self)
        label.setStyleSheet("color:#64748b;font-size:11px;")
        root.addWidget(label)
        enabled_by_slot = {
            preset.slot: bool(preset.enabled) for preset in presets
        }
        self.preset_bar = _TimePresetBar(
            "time", self.current_params, self.apply_params, parent=self,
            builtin_defaults=builtin_defaults, default_params={},
            custom_slots=CUSTOM_PRESET_SLOTS,
            enabled_by_slot=enabled_by_slot,
        )
        root.addWidget(self.preset_bar)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()

    def current_params(self) -> dict:
        return deepcopy(self._params)

    def get_params(self) -> dict:
        return self.current_params()

    def apply_params(self, params: dict) -> None:
        if not isinstance(params, dict):
            return
        patch = deepcopy(params)
        if "time_preprocess" in patch and isinstance(
            patch["time_preprocess"], dict
        ):
            current = dict(self._params.get("time_preprocess") or {})
            current.update(patch["time_preprocess"])
            self._params["time_preprocess"] = current
            patch.pop("time_preprocess")
        self._params.update(patch)
        self.time_preset_applied.emit(self.current_params())
