"""Method-selector button group + dynamic per-method parameter form.

Exposes exactly FOUR method buttons — ``fft``, ``fft_time``,
``order_time``, ``order_track``. ``order_rpm`` was removed by upstream
commit ``cfb301b`` and ``batch.BatchRunner.SUPPORTED_METHODS`` no longer
accepts it; ``fft_time`` was added in Wave 3a so the UI selection stays
in lock-step with the dispatcher (see
``signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md``).

The dynamic parameter form swaps QFormLayout rows on ``set_method`` per
spec §3.3 (minus the dropped ``order_rpm`` column). At the end of
``set_method`` we re-run the visibility helper once to seed the initial
state — required by
``pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md``.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QPushButton, QSpinBox, QWidget,
)


_METHODS: tuple[tuple[str, str], ...] = (
    ("fft", "FFT"),
    ("fft_time", "FFT vs Time"),
    ("order_time", "order_time"),
    ("order_track", "order_track"),
)


class MethodButtonGroup(QWidget):
    """Three exclusive toggle buttons emitting ``methodChanged(str)``."""

    methodChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for key, label in _METHODS:
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, k=key: self.set_method(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            lay.addWidget(btn)
        # Default to FFT.
        self._current = "fft"
        self._buttons["fft"].setChecked(True)

    def set_method(self, method: str) -> None:
        if method not in self._buttons:
            return
        btn = self._buttons[method]
        if not btn.isChecked():
            btn.setChecked(True)
        if method == self._current:
            # Still emit on explicit set so callers/tests observe the call.
            self.methodChanged.emit(method)
            return
        self._current = method
        self.methodChanged.emit(method)

    def current_method(self) -> str:
        return self._current


# ---------------------------------------------------------------------------
# Dynamic parameter form
# ---------------------------------------------------------------------------
_WINDOWS: tuple[str, ...] = ("hanning", "hamming", "blackman", "rectangular")


# Per-method visible field set, taken verbatim from spec §3.3 minus the
# removed ``order_rpm`` column.
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "fft": ("window", "nfft"),
    "fft_time": ("window", "nfft", "overlap", "remove_mean"),
    "order_time": ("window", "nfft", "max_order", "order_res", "time_res"),
    "order_track": ("window", "nfft", "max_order", "target_order"),
}


class DynamicParamForm(QWidget):
    """QFormLayout-backed parameter form whose rows swap per method."""

    paramsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)

        self._labels: dict[str, str] = {
            "window": "窗函数",
            "nfft": "NFFT",
            "max_order": "最大阶次",
            "order_res": "阶次分辨率",
            "time_res": "时间分辨率",
            "target_order": "目标阶次",
            "rpm_factor": "RPM 系数",
            "overlap": "重叠率",
            "remove_mean": "去均值",
        }

        self._widgets: dict[str, QWidget] = {}

        # window — QComboBox
        self._w_window = QComboBox(self)
        self._w_window.addItems(_WINDOWS)
        self._w_window.currentIndexChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["window"] = self._w_window

        # nfft — QSpinBox
        self._w_nfft = QSpinBox(self)
        self._w_nfft.setRange(64, 1 << 20)
        self._w_nfft.setValue(1024)
        self._w_nfft.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["nfft"] = self._w_nfft

        # max_order
        self._w_max_order = QDoubleSpinBox(self)
        self._w_max_order.setRange(0.0, 1000.0)
        self._w_max_order.setDecimals(2)
        self._w_max_order.setValue(20.0)
        self._w_max_order.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["max_order"] = self._w_max_order

        # order_res
        self._w_order_res = QDoubleSpinBox(self)
        self._w_order_res.setRange(0.001, 100.0)
        self._w_order_res.setDecimals(3)
        self._w_order_res.setValue(0.05)
        self._w_order_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["order_res"] = self._w_order_res

        # time_res
        self._w_time_res = QDoubleSpinBox(self)
        self._w_time_res.setRange(0.001, 100.0)
        self._w_time_res.setDecimals(3)
        self._w_time_res.setValue(0.1)
        self._w_time_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["time_res"] = self._w_time_res

        # target_order
        self._w_target_order = QDoubleSpinBox(self)
        self._w_target_order.setRange(0.0, 1000.0)
        self._w_target_order.setDecimals(2)
        self._w_target_order.setValue(2.0)
        self._w_target_order.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["target_order"] = self._w_target_order

        # rpm_factor
        self._w_rpm_factor = QDoubleSpinBox(self)
        self._w_rpm_factor.setRange(0.0001, 10000.0)
        self._w_rpm_factor.setDecimals(4)
        self._w_rpm_factor.setValue(1.0)
        self._w_rpm_factor.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["rpm_factor"] = self._w_rpm_factor

        # overlap — QDoubleSpinBox 0..0.95
        self._w_overlap = QDoubleSpinBox(self)
        self._w_overlap.setRange(0.0, 0.95)
        self._w_overlap.setSingleStep(0.05)
        self._w_overlap.setDecimals(2)
        self._w_overlap.setValue(0.5)
        self._w_overlap.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["overlap"] = self._w_overlap

        # remove_mean — QCheckBox
        self._w_remove_mean = QCheckBox(self)
        self._w_remove_mean.setChecked(True)
        self._w_remove_mean.toggled.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["remove_mean"] = self._w_remove_mean

        # Track current method so set_method works idempotently.
        self._current = "fft"
        self._render_for("fft")

    # ------------------------------------------------------------------
    def set_method(self, method: str) -> None:
        if method not in _METHOD_FIELDS:
            return
        self._current = method
        self._render_for(method)
        # Init-sync per the conditional-visibility-init-sync lesson: do not
        # rely on a downstream signal to seed visible state; emit once.
        self.paramsChanged.emit()

    def visible_field_names(self) -> set[str]:
        out: set[str] = set()
        for name, w in self._widgets.items():
            if not w.isHidden() and self._form.indexOf(w) >= 0:
                out.add(name)
        return out

    def get_params(self) -> dict:
        params: dict = {}
        if "window" in self.visible_field_names():
            params["window"] = self._w_window.currentText()
        if "nfft" in self.visible_field_names():
            params["nfft"] = int(self._w_nfft.value())
        if "max_order" in self.visible_field_names():
            params["max_order"] = float(self._w_max_order.value())
        if "order_res" in self.visible_field_names():
            params["order_res"] = float(self._w_order_res.value())
        if "time_res" in self.visible_field_names():
            params["time_res"] = float(self._w_time_res.value())
        if "target_order" in self.visible_field_names():
            params["target_order"] = float(self._w_target_order.value())
        if "rpm_factor" in self.visible_field_names():
            params["rpm_factor"] = float(self._w_rpm_factor.value())
        if "overlap" in self.visible_field_names():
            params["overlap"] = float(self._w_overlap.value())
        if "remove_mean" in self.visible_field_names():
            params["remove_mean"] = bool(self._w_remove_mean.isChecked())
        return params

    def apply_params(self, params: dict) -> None:
        if not params:
            return
        # window (string)
        if "window" in params:
            txt = str(params["window"])
            idx = self._w_window.findText(txt)
            if idx >= 0:
                self._w_window.setCurrentIndex(idx)
        if "nfft" in params:
            try:
                self._w_nfft.setValue(int(params["nfft"]))
            except (TypeError, ValueError):
                pass
        for key, widget in (
            ("max_order", self._w_max_order),
            ("order_res", self._w_order_res),
            ("time_res", self._w_time_res),
            ("target_order", self._w_target_order),
            ("rpm_factor", self._w_rpm_factor),
        ):
            if key in params:
                try:
                    widget.setValue(float(params[key]))
                except (TypeError, ValueError):
                    pass
        if "overlap" in params:
            try:
                self._w_overlap.setValue(float(params["overlap"]))
            except (TypeError, ValueError):
                pass
        if "remove_mean" in params:
            self._w_remove_mean.setChecked(bool(params["remove_mean"]))

    # ------------------------------------------------------------------
    def _render_for(self, method: str) -> None:
        # Detach all rows. QFormLayout.removeRow deletes the field widget;
        # use takeRow() and reparent the widgets to keep them alive across
        # swaps (so we can re-add them when set_method is called again).
        while self._form.rowCount() > 0:
            taken = self._form.takeRow(0)
            label_item = taken.labelItem
            field_item = taken.fieldItem
            if label_item is not None:
                lw = label_item.widget()
                if lw is not None:
                    lw.setParent(None)
                    lw.deleteLater()
            if field_item is not None:
                fw = field_item.widget()
                if fw is not None:
                    fw.setParent(self)  # detach; keep alive
                    fw.hide()
        for name in _METHOD_FIELDS[method]:
            widget = self._widgets[name]
            self._form.addRow(self._labels[name], widget)
            widget.setHidden(False)
        # Hide widgets not in this method's set so isHidden() honestly
        # reflects visibility for tests / snapshot diffs (per the
        # conditional-visibility paired-field-children lesson).
        active = set(_METHOD_FIELDS[method])
        for name, widget in self._widgets.items():
            if name not in active:
                widget.setHidden(True)
