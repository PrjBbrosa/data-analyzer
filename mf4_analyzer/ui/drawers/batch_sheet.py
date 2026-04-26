"""Batch analysis dialog with current-single and free-config presets."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...batch import AnalysisPreset, BatchOutput


class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self.resize(460, 560)
        self._files = files
        self._current_preset = current_preset

        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self._current_tab = self._build_current_tab()
        self._custom_tab = self._build_custom_tab()
        self.tabs.addTab(self._current_tab, "当前单次")
        self.tabs.addTab(self._custom_tab, "自由配置")
        if self._current_preset is None:
            self.tabs.setTabEnabled(0, False)
            self.tabs.setCurrentIndex(1)
        root.addWidget(self.tabs)

        output_group = QGroupBox("输出")
        output_form = QFormLayout(output_group)
        self.edit_output = QLineEdit(str(Path.home() / "Desktop" / "mf4_batch_output"))
        btn_browse = QPushButton("选择…")
        btn_browse.clicked.connect(self._choose_output_dir)
        row = QHBoxLayout()
        row.addWidget(self.edit_output, 1)
        row.addWidget(btn_browse)
        output_form.addRow("目录:", row)
        self.chk_data = QCheckBox("导出数据")
        self.chk_data.setChecked(True)
        self.chk_image = QCheckBox("生成图片")
        self.chk_image.setChecked(True)
        checks = QHBoxLayout()
        checks.addWidget(self.chk_data)
        checks.addWidget(self.chk_image)
        output_form.addRow(checks)
        self.combo_format = QComboBox()
        self.combo_format.addItems(["csv", "xlsx"])
        output_form.addRow("数据格式:", self.combo_format)
        root.addWidget(output_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("运行")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_current_tab(self):
        w = QWidget(self)
        lay = QVBoxLayout(w)
        if self._current_preset is None:
            label = QLabel("暂无可复用的单次分析。先运行一次 FFT 或阶次计算，或切到“自由配置”。")
            label.setWordWrap(True)
            lay.addWidget(label)
        else:
            p = self._current_preset
            text = (
                f"名称: {p.name}\n"
                f"方法: {p.method}\n"
                f"信号: {p.signal}\n"
                f"RPM: {p.rpm_channel or '-'}"
            )
            label = QLabel(text)
            label.setWordWrap(True)
            lay.addWidget(label)
        lay.addStretch(1)
        return w

    def _build_custom_tab(self):
        w = QWidget(self)
        lay = QVBoxLayout(w)

        source = QGroupBox("任务")
        form = QFormLayout(source)
        self.edit_name = QLineEdit("custom batch")
        form.addRow("名称:", self.edit_name)
        self.combo_method = QComboBox()
        self.combo_method.addItems(["fft", "order_time", "order_rpm", "order_track"])
        form.addRow("方法:", self.combo_method)
        self.edit_pattern = QLineEdit()
        self.edit_pattern.setPlaceholderText("留空=所有信号；支持包含匹配或正则")
        form.addRow("信号匹配:", self.edit_pattern)
        self.combo_rpm = QComboBox()
        self.combo_rpm.addItem("自动识别", "")
        for ch in self._all_channels():
            self.combo_rpm.addItem(ch, ch)
        form.addRow("RPM通道:", self.combo_rpm)
        lay.addWidget(source)

        params = QGroupBox("参数")
        pf = QFormLayout(params)
        self.combo_window = QComboBox()
        self.combo_window.addItems(["hanning", "flattop", "hamming", "blackman", "kaiser", "bartlett"])
        pf.addRow("窗函数:", self.combo_window)
        self.spin_nfft = QSpinBox()
        self.spin_nfft.setRange(128, 262144)
        self.spin_nfft.setValue(1024)
        pf.addRow("NFFT:", self.spin_nfft)
        self.spin_max_order = QDoubleSpinBox()
        self.spin_max_order.setRange(0.1, 1000)
        self.spin_max_order.setValue(20)
        pf.addRow("最大阶次:", self.spin_max_order)
        self.spin_order_res = QDoubleSpinBox()
        self.spin_order_res.setRange(0.001, 10)
        self.spin_order_res.setDecimals(3)
        self.spin_order_res.setValue(0.1)
        pf.addRow("阶次分辨率:", self.spin_order_res)
        self.spin_time_res = QDoubleSpinBox()
        self.spin_time_res.setRange(0.001, 10)
        self.spin_time_res.setDecimals(3)
        self.spin_time_res.setValue(0.05)
        pf.addRow("时间分辨率:", self.spin_time_res)
        self.spin_rpm_res = QDoubleSpinBox()
        self.spin_rpm_res.setRange(0.1, 10000)
        self.spin_rpm_res.setValue(10)
        pf.addRow("RPM分辨率:", self.spin_rpm_res)
        self.spin_target = QDoubleSpinBox()
        self.spin_target.setRange(0.001, 1000)
        self.spin_target.setValue(1)
        pf.addRow("目标阶次:", self.spin_target)
        self.spin_rpm_factor = QDoubleSpinBox()
        self.spin_rpm_factor.setRange(-1e6, 1e6)
        self.spin_rpm_factor.setDecimals(6)
        self.spin_rpm_factor.setValue(1)
        pf.addRow("RPM系数:", self.spin_rpm_factor)
        lay.addWidget(params)
        lay.addStretch(1)
        return w

    def _all_channels(self):
        seen = []
        for fd in self._files.values():
            for ch in fd.get_signal_channels():
                if ch not in seen:
                    seen.append(ch)
        return seen

    def _choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.edit_output.text())
        if path:
            self.edit_output.setText(path)

    def output_dir(self):
        return self.edit_output.text().strip()

    def _outputs(self):
        return BatchOutput(
            export_data=self.chk_data.isChecked(),
            export_image=self.chk_image.isChecked(),
            data_format=self.combo_format.currentText(),
        )

    def get_preset(self):
        if self.tabs.currentIndex() == 0 and self._current_preset is not None:
            return replace(self._current_preset, outputs=self._outputs())
        rpm_channel = self.combo_rpm.currentData() or ""
        params = {
            "window": self.combo_window.currentText(),
            "nfft": self.spin_nfft.value(),
            "max_order": self.spin_max_order.value(),
            "order_res": self.spin_order_res.value(),
            "time_res": self.spin_time_res.value(),
            "rpm_res": self.spin_rpm_res.value(),
            "target_order": self.spin_target.value(),
            "rpm_factor": self.spin_rpm_factor.value(),
        }
        return AnalysisPreset.free_config(
            name=self.edit_name.text().strip() or "custom batch",
            method=self.combo_method.currentText(),
            signal_pattern=self.edit_pattern.text().strip(),
            rpm_channel=rpm_channel,
            params=params,
            outputs=self._outputs(),
        )
