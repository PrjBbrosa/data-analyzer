"""Method-selector button group + dynamic per-method parameter form.

Exposes exactly FOUR method buttons — ``time``, ``fft``, ``fft_time``,
``order_time``. ``order_rpm`` was removed by upstream commit ``cfb301b``
and ``order_track`` was removed 2026-04-28; ``batch.BatchRunner.SUPPORTED_METHODS``
no longer accepts either, and ``fft_time`` was added in Wave 3a so the UI
selection stays in lock-step with the dispatcher (see
``signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md``).

The dynamic parameter form swaps QFormLayout rows on ``set_method`` per
spec §3.3 (minus the dropped ``order_rpm`` / ``order_track`` columns).
At the end of ``set_method`` we re-run the visibility helper once to seed
the initial state — required by
``pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md``.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFormLayout,
    QHBoxLayout, QPushButton, QSizePolicy, QSpinBox, QWidget,
)

from ...widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons


_METHODS: tuple[tuple[str, str], ...] = (
    ("time", "时域"),
    ("fft", "FFT"),
    ("fft_time", "FFT vs Time"),
    ("order_time", "阶次"),
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
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _checked, k=key: self.set_method(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            # Keep all four methods on one compact row while giving the only
            # long label enough space at the supported 288 px pane width.
            lay.addWidget(btn, 2 if key == "fft_time" else 1)
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
_WINDOWS: tuple[str, ...] = (
    "hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop",
)
_WEIGHTINGS: tuple[str, ...] = ("None", "A")


# Per-method visible field set, taken verbatim from spec §3.3 minus the
# removed ``order_rpm`` column.
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "time": (
        "render_group_by", "render_layout", "x_source", "x_channel",
        "x_origin",
    ),
    "fft": (
        "window", "nfft_mode", "nfft", "t_win_s", "overlap",
        "avg_mode", "avg_overlap", "amplitude_definition", "weighting",
    ),
    "fft_time": (
        "window", "nfft_mode", "nfft", "t_win_s", "overlap",
        "remove_mean", "weighting",
    ),
    "order_time": (
        "window", "nfft_mode", "nfft", "max_order", "order_res", "time_res",
        "rpm_mode", "manual_rpm", "samples_per_rev", "weighting",
    ),
}


def _set_form_row_visible(
    form: QFormLayout, field_widget: QWidget, visible: bool,
) -> None:
    """Show or hide both halves of one Qt 5 form row."""
    field_widget.setVisible(visible)
    label = form.labelForField(field_widget)
    if label is not None:
        label.setVisible(visible)


class DynamicParamForm(QWidget):
    """QFormLayout-backed parameter form whose rows swap per method."""

    paramsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)

        # rpm_factor is owned by InputPanel (Wave 2 Task 5) — no entry
        # here on purpose; if a future preset injects an unmapped key it
        # would surface as a KeyError rather than silently rendering as
        # an extra row.
        self._labels: dict[str, str] = {
            "window": "窗函数",
            "nfft_mode": "NFFT 模式",
            "nfft": "NFFT",
            "t_win_s": "窗长",
            "max_order": "最大阶次",
            "order_res": "阶次分辨率",
            "time_res": "时间分辨率",
            "overlap": "重叠率",
            "remove_mean": "去均值",
            "weighting": "频率加权",
            "avg_mode": "平均模式",
            "avg_overlap": "平均重叠",
            "amplitude_definition": "幅值定义",
            "rpm_mode": "RPM 模式",
            "manual_rpm": "手动 RPM",
            "samples_per_rev": "每转样本",
            "render_group_by": "图片分组",
            "render_layout": "图片布局",
            "x_source": "X 轴来源",
            "x_channel": "X 通道",
            "x_origin": "时间原点",
        }

        self._widgets: dict[str, QWidget] = {}

        # window — QComboBox
        self._w_window = QComboBox(self)
        self._w_window.addItems(_WINDOWS)
        self._w_window.currentIndexChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["window"] = self._w_window

        self._w_nfft_mode = QComboBox(self)
        self._w_nfft_mode.addItem("Auto", "auto")
        self._w_nfft_mode.addItem("Fixed", "fixed")
        self._w_nfft_mode.currentIndexChanged.connect(self._sync_nfft_mode)
        self._w_nfft_mode.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["nfft_mode"] = self._w_nfft_mode

        # weighting — mirrors the single-analysis contextual panels.
        self._w_weighting = QComboBox(self)
        self._w_weighting.addItems(_WEIGHTINGS)
        self._w_weighting.setToolTip(
            "A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL"
        )
        self._w_weighting.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["weighting"] = self._w_weighting

        # nfft — QSpinBox
        self._w_nfft = no_buttons(QSpinBox(self))
        self._w_nfft.setRange(64, 1 << 20)
        self._w_nfft.setValue(1024)
        self._w_nfft.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["nfft"] = self._w_nfft

        self._w_t_win_s = no_buttons(CompactDoubleSpinBox(self))
        self._w_t_win_s.setRange(0.001, 3600.0)
        self._w_t_win_s.setDecimals(3)
        self._w_t_win_s.setValue(1.5)
        self._w_t_win_s.setSuffix(" s")
        self._w_t_win_s.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["t_win_s"] = self._w_t_win_s

        # max_order
        self._w_max_order = no_buttons(CompactDoubleSpinBox(self))
        self._w_max_order.setRange(0.0, 1000.0)
        self._w_max_order.setDecimals(2)
        self._w_max_order.setValue(20.0)
        self._w_max_order.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["max_order"] = self._w_max_order

        # order_res
        self._w_order_res = no_buttons(CompactDoubleSpinBox(self))
        self._w_order_res.setRange(0.001, 100.0)
        self._w_order_res.setDecimals(3)
        self._w_order_res.setValue(0.05)
        self._w_order_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["order_res"] = self._w_order_res

        # time_res
        self._w_time_res = no_buttons(CompactDoubleSpinBox(self))
        self._w_time_res.setRange(0.001, 100.0)
        self._w_time_res.setDecimals(3)
        self._w_time_res.setValue(0.1)
        self._w_time_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["time_res"] = self._w_time_res

        # overlap — QDoubleSpinBox 0..0.95
        self._w_overlap = no_buttons(CompactDoubleSpinBox(self))
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

        self._w_avg_mode = QComboBox(self)
        self._w_avg_mode.addItems(["单帧", "线性平均", "峰值保持"])
        self._w_avg_mode.currentTextChanged.connect(self._sync_avg_mode)
        self._w_avg_mode.currentTextChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["avg_mode"] = self._w_avg_mode

        self._w_avg_overlap = no_buttons(QSpinBox(self))
        self._w_avg_overlap.setRange(0, 95)
        self._w_avg_overlap.setValue(50)
        self._w_avg_overlap.setSuffix(" %")
        self._w_avg_overlap.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["avg_overlap"] = self._w_avg_overlap

        self._w_amplitude_definition = QComboBox(self)
        self._w_amplitude_definition.addItem("算法默认", "native")
        self._w_amplitude_definition.addItem("Peak", "peak")
        self._w_amplitude_definition.addItem("RMS", "rms")
        self._w_amplitude_definition.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["amplitude_definition"] = self._w_amplitude_definition

        self._w_rpm_mode = QComboBox(self)
        self._w_rpm_mode.addItem("Channel", "channel")
        self._w_rpm_mode.addItem("Manual", "manual")
        self._w_rpm_mode.currentIndexChanged.connect(self._sync_rpm_mode)
        self._w_rpm_mode.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["rpm_mode"] = self._w_rpm_mode

        self._w_manual_rpm = no_buttons(CompactDoubleSpinBox(self))
        self._w_manual_rpm.setRange(0.001, 1e7)
        self._w_manual_rpm.setDecimals(3)
        self._w_manual_rpm.setValue(1000.0)
        self._w_manual_rpm.setSuffix(" rpm")
        self._w_manual_rpm.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["manual_rpm"] = self._w_manual_rpm

        self._w_samples_per_rev = no_buttons(QSpinBox(self))
        self._w_samples_per_rev.setRange(2, 1 << 20)
        self._w_samples_per_rev.setValue(256)
        self._w_samples_per_rev.valueChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["samples_per_rev"] = self._w_samples_per_rev

        self._w_render_group_by = QComboBox(self)
        self._w_render_group_by.addItem("每任务", "none")
        self._w_render_group_by.addItem("按数据源", "source")
        self._w_render_group_by.addItem("按通道", "channel")
        self._w_render_group_by.currentIndexChanged.connect(
            self._sync_render_group_by
        )
        self._w_render_group_by.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["render_group_by"] = self._w_render_group_by

        self._w_render_layout = QComboBox(self)
        self._w_render_layout.addItem("叠加", "overlay")
        self._w_render_layout.addItem("子图", "subplot")
        self._w_render_layout.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["render_layout"] = self._w_render_layout

        self._w_x_source = QComboBox(self)
        self._w_x_source.addItem("时间", "time")
        self._w_x_source.addItem("通道", "channel")
        self._w_x_source.currentIndexChanged.connect(self._sync_x_source)
        self._w_x_source.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["x_source"] = self._w_x_source

        self._w_x_channel = QComboBox(self)
        self._w_x_channel.addItem("请选择", "")
        self._w_x_channel.currentIndexChanged.connect(
            self._on_x_channel_changed
        )
        self._widgets["x_channel"] = self._w_x_channel
        self._x_channel_candidates_initialized = False
        self._pending_x_channel = ""
        self._x_channel_validation = ""

        self._w_x_origin = QComboBox(self)
        self._w_x_origin.addItem("从零开始", "zero")
        self._w_x_origin.addItem("绝对时间", "absolute")
        self._w_x_origin.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["x_origin"] = self._w_x_origin

        for combo in (
            self._w_render_group_by,
            self._w_render_layout,
            self._w_x_source,
            self._w_x_channel,
            self._w_x_origin,
        ):
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        # Track current method so set_method works idempotently.
        self._current = "fft"
        self._render_for("fft")
        self._sync_nfft_mode()
        self._sync_avg_mode()
        self._sync_rpm_mode()
        self._sync_render_group_by()
        self._sync_x_source()

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

    def _sync_nfft_mode(self, *_args) -> None:
        self._w_nfft.setEnabled(self._w_nfft_mode.currentData() == "fixed")

    def _sync_avg_mode(self, *_args) -> None:
        self._w_avg_overlap.setEnabled(self._w_avg_mode.currentText() != "单帧")

    def _sync_rpm_mode(self, *_args) -> None:
        self._w_manual_rpm.setEnabled(self._w_rpm_mode.currentData() == "manual")

    def _sync_render_group_by(self, *_args) -> None:
        self._w_render_layout.setEnabled(
            self._w_render_group_by.currentData() != "none"
        )

    def _sync_x_source(self, *_args) -> None:
        use_channel = self._w_x_source.currentData() == "channel"
        _set_form_row_visible(self._form, self._w_x_channel, use_channel)
        _set_form_row_visible(self._form, self._w_x_origin, not use_channel)

    def _on_x_channel_changed(self, *_args) -> None:
        selected = str(self._w_x_channel.currentData() or "")
        if selected:
            self._pending_x_channel = selected
            self._x_channel_validation = ""
        self.paramsChanged.emit()

    def x_channel_validation_message(self) -> str:
        return self._x_channel_validation

    def set_x_channel_candidates(
        self, common: Sequence[str], partial: Mapping[str, str],
    ) -> None:
        """Replace the X-channel universe without selecting partial rows."""
        selected = str(
            self._w_x_channel.currentData() or self._pending_x_channel or ""
        )
        common_names = tuple(dict.fromkeys(
            str(name) for name in common if str(name)
        ))
        partial_items = tuple(
            (str(name), str(suffix))
            for name, suffix in partial.items()
            if str(name) and str(name) not in common_names
        )

        previous = self._w_x_channel.blockSignals(True)
        try:
            self._w_x_channel.clear()
            self._w_x_channel.addItem("请选择", "")
            for name in common_names:
                self._w_x_channel.addItem(name, name)
            for name, suffix in partial_items:
                self._w_x_channel.addItem(f"{name} {suffix}".strip(), name)
                item = self._w_x_channel.model().item(
                    self._w_x_channel.count() - 1
                )
                if item is not None:
                    item.setEnabled(False)

            index = self._w_x_channel.findData(selected)
            valid = bool(selected) and selected in common_names
            self._w_x_channel.setCurrentIndex(index if valid else 0)
        finally:
            self._w_x_channel.blockSignals(previous)

        self._x_channel_candidates_initialized = True
        if selected and not valid:
            self._pending_x_channel = ""
            self._x_channel_validation = (
                f"X 通道 {selected} 不是所有已加载数据源的共同通道"
            )
            self.paramsChanged.emit()
        elif valid:
            self._pending_x_channel = selected
            self._x_channel_validation = ""

    def get_params(self) -> dict:
        if self._current == "time":
            params: dict = {}
            group_by = str(self._w_render_group_by.currentData() or "none")
            if group_by != "none":
                params["render_group_by"] = group_by
                layout = str(self._w_render_layout.currentData() or "overlay")
                if layout != "overlay":
                    params["render_layout"] = layout
            x_source = str(self._w_x_source.currentData() or "time")
            if x_source != "time":
                params["x_source"] = x_source
                channel = str(
                    self._w_x_channel.currentData()
                    or self._pending_x_channel
                    or ""
                )
                if channel:
                    params["x_channel"] = channel
            else:
                origin = str(self._w_x_origin.currentData() or "zero")
                if origin != "zero":
                    params["x_origin"] = origin
            return params
        params: dict = {}
        if "window" in self.visible_field_names():
            params["window"] = self._w_window.currentText()
        if "nfft" in self.visible_field_names():
            mode = str(self._w_nfft_mode.currentData() or "auto")
            params["nfft_mode"] = mode
            params["nfft"] = int(self._w_nfft.value()) if mode == "fixed" else None
        if "t_win_s" in self.visible_field_names():
            params["t_win_s"] = float(self._w_t_win_s.value())
        if "max_order" in self.visible_field_names():
            params["max_order"] = float(self._w_max_order.value())
        if "order_res" in self.visible_field_names():
            params["order_res"] = float(self._w_order_res.value())
        if "time_res" in self.visible_field_names():
            params["time_res"] = float(self._w_time_res.value())
        if "overlap" in self.visible_field_names():
            params["overlap"] = float(self._w_overlap.value())
        if "remove_mean" in self.visible_field_names():
            params["remove_mean"] = bool(self._w_remove_mean.isChecked())
        if "weighting" in self.visible_field_names():
            params["weighting"] = self._w_weighting.currentText()
        if "avg_mode" in self.visible_field_names():
            params["avg_mode"] = self._w_avg_mode.currentText()
        if "avg_overlap" in self.visible_field_names():
            params["avg_overlap"] = int(self._w_avg_overlap.value())
        if "amplitude_definition" in self.visible_field_names():
            params["amplitude_definition"] = str(
                self._w_amplitude_definition.currentData() or "native"
            )
        if "rpm_mode" in self.visible_field_names():
            params["rpm_mode"] = str(self._w_rpm_mode.currentData() or "channel")
        if "manual_rpm" in self.visible_field_names():
            params["manual_rpm"] = float(self._w_manual_rpm.value())
        if "samples_per_rev" in self.visible_field_names():
            params["samples_per_rev"] = int(self._w_samples_per_rev.value())
        return params

    def apply_params(self, params: dict) -> None:
        if not params:
            return
        for key, combo in (
            ("render_group_by", self._w_render_group_by),
            ("render_layout", self._w_render_layout),
            ("x_source", self._w_x_source),
            ("x_origin", self._w_x_origin),
        ):
            if key in params:
                index = combo.findData(str(params[key]))
                if index >= 0:
                    combo.setCurrentIndex(index)
        if "x_channel" in params:
            channel = str(params.get("x_channel") or "")
            index = self._w_x_channel.findData(channel)
            item = self._w_x_channel.model().item(index) if index >= 0 else None
            if index >= 0 and item is not None and item.isEnabled():
                self._w_x_channel.setCurrentIndex(index)
                self._pending_x_channel = channel
                self._x_channel_validation = ""
            elif channel and not self._x_channel_candidates_initialized:
                self._pending_x_channel = channel
            elif channel:
                self._pending_x_channel = ""
                self._x_channel_validation = (
                    f"X 通道 {channel} 不是所有已加载数据源的共同通道"
                )
        # window (string)
        if "window" in params:
            txt = str(params["window"])
            idx = self._w_window.findText(txt)
            if idx >= 0:
                self._w_window.setCurrentIndex(idx)
        if "nfft_mode" in params or "nfft" in params:
            raw_nfft = params.get("nfft")
            raw_mode = str(params.get("nfft_mode", "") or "").lower()
            auto = raw_mode in {"auto", "自动"} or raw_nfft in {
                None, "", "auto", "自动",
            }
            mode = "auto" if auto else "fixed"
            index = self._w_nfft_mode.findData(mode)
            if index >= 0:
                self._w_nfft_mode.setCurrentIndex(index)
            if not auto:
                try:
                    self._w_nfft.setValue(int(raw_nfft))
                except (TypeError, ValueError):
                    pass
            self._sync_nfft_mode()
        if "t_win_s" in params:
            try:
                self._w_t_win_s.setValue(float(params["t_win_s"]))
            except (TypeError, ValueError):
                pass
        for key, widget in (
            ("max_order", self._w_max_order),
            ("order_res", self._w_order_res),
            ("time_res", self._w_time_res),
        ):
            if key in params:
                try:
                    widget.setValue(float(params[key]))
                except (TypeError, ValueError):
                    pass
        if "overlap" in params:
            try:
                value = float(params["overlap"])
                self._w_overlap.setValue(value / 100.0 if value > 1.0 else value)
            except (TypeError, ValueError):
                pass
        if "remove_mean" in params:
            self._w_remove_mean.setChecked(bool(params["remove_mean"]))
        if "weighting" in params:
            txt = str(params["weighting"])
            idx = self._w_weighting.findText(txt)
            if idx >= 0:
                self._w_weighting.setCurrentIndex(idx)
        if "avg_mode" in params:
            idx = self._w_avg_mode.findText(str(params["avg_mode"]))
            if idx >= 0:
                self._w_avg_mode.setCurrentIndex(idx)
        if "avg_overlap" in params:
            try:
                value = float(params["avg_overlap"])
                self._w_avg_overlap.setValue(
                    int(round(value * 100.0 if 0.0 <= value <= 1.0 else value))
                )
            except (TypeError, ValueError):
                pass
        if "amplitude_definition" in params:
            idx = self._w_amplitude_definition.findData(
                str(params["amplitude_definition"]).lower()
            )
            if idx >= 0:
                self._w_amplitude_definition.setCurrentIndex(idx)
        if "rpm_mode" in params:
            raw = str(params["rpm_mode"]).lower()
            mode = "manual" if raw in {"manual", "fixed", "手动"} else "channel"
            idx = self._w_rpm_mode.findData(mode)
            if idx >= 0:
                self._w_rpm_mode.setCurrentIndex(idx)
        if "manual_rpm" in params:
            try:
                self._w_manual_rpm.setValue(float(params["manual_rpm"]))
            except (TypeError, ValueError):
                pass
        if "samples_per_rev" in params:
            try:
                self._w_samples_per_rev.setValue(int(params["samples_per_rev"]))
            except (TypeError, ValueError):
                pass
        self._sync_avg_mode()
        self._sync_rpm_mode()
        self._sync_render_group_by()
        self._sync_x_source()

    def set_weighting_options(self, options) -> None:
        values = [str(item) for item in (options or ()) if str(item)]
        if not values:
            values = list(_WEIGHTINGS)
        current = self._w_weighting.currentText()
        self._w_weighting.blockSignals(True)
        try:
            self._w_weighting.clear()
            self._w_weighting.addItems(values)
            target = current if current in values else (
                "None" if "None" in values else values[0]
            )
            idx = self._w_weighting.findText(target)
            if idx >= 0:
                self._w_weighting.setCurrentIndex(idx)
        finally:
            self._w_weighting.blockSignals(False)

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
        self._sync_nfft_mode()
        self._sync_avg_mode()
        self._sync_rpm_mode()
        self._sync_render_group_by()
        self._sync_x_source()
