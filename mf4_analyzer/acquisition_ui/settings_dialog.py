"""Standalone Settings dialog for Acquisition Cockpit threshold overrides."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_capture.vector_hw_probe import (
    test_xcp_connection,
    vector_hw_probe,
)


@dataclass(frozen=True)
class _TestConnectionResult:
    ok: bool
    level: Literal["green", "red"]
    message: str


@dataclass(frozen=True)
class _FieldSpec:
    key: str
    label: str
    suffix: str = ""
    decimals: int = 1
    storage_per_display_unit: float = 1.0
    storage_kind: str = "float"
    minimum: float = 0.0
    maximum: float = 1_000_000.0
    step: float = 1.0
    integer_editor: bool = False

    def to_display(self, value: float | int) -> float:
        return float(value) / self.storage_per_display_unit

    def from_display(self, value: float | int) -> float | int:
        storage_value = float(value) * self.storage_per_display_unit
        if self.storage_kind == "int":
            return int(round(storage_value))
        return storage_value


_GB = 1024 ** 3
_MB = 1024 ** 2

_FIELD_SPECS = (
    _FieldSpec(
        "CAN_LOAD_GREEN_MAX_PCT", "CAN 负载 green-max", " %", maximum=100.0
    ),
    _FieldSpec(
        "CAN_LOAD_YELLOW_MAX_PCT", "CAN 负载 yellow-max", " %", maximum=100.0
    ),
    _FieldSpec(
        "DAQ_SLOT_GREEN_MAX_PCT", "DAQ 槽位 green-max", " %", maximum=100.0
    ),
    _FieldSpec(
        "DAQ_SLOT_YELLOW_MAX_PCT", "DAQ 槽位 yellow-max", " %", maximum=100.0
    ),
    _FieldSpec(
        "DISK_FREE_GREEN_MIN_BYTES",
        "磁盘剩余 green-min",
        " GB",
        decimals=2,
        storage_per_display_unit=_GB,
        storage_kind="int",
        maximum=10_000.0,
        step=0.5,
    ),
    _FieldSpec(
        "DISK_FREE_YELLOW_MIN_BYTES",
        "磁盘剩余 yellow-min",
        " GB",
        decimals=2,
        storage_per_display_unit=_GB,
        storage_kind="int",
        maximum=10_000.0,
        step=0.5,
    ),
    _FieldSpec(
        "RECORD_DURATION_GREEN_MIN_S",
        "估算时长 green-min",
        " h",
        decimals=2,
        storage_per_display_unit=3600.0,
        maximum=10_000.0,
        step=0.25,
    ),
    _FieldSpec(
        "RECORD_DURATION_YELLOW_MIN_S",
        "估算时长 yellow-min",
        " h",
        decimals=2,
        storage_per_display_unit=3600.0,
        maximum=10_000.0,
        step=0.25,
    ),
    _FieldSpec(
        "SAMPLE_EVENTS_GREEN_MAX_PER_S",
        "样本事件 green-max",
        " k/s",
        decimals=1,
        storage_per_display_unit=1000.0,
        maximum=1_000.0,
        step=1.0,
    ),
    _FieldSpec(
        "SAMPLE_EVENTS_YELLOW_MAX_PER_S",
        "样本事件 yellow-max",
        " k/s",
        decimals=1,
        storage_per_display_unit=1000.0,
        maximum=1_000.0,
        step=1.0,
    ),
    _FieldSpec(
        "RING_BUFFER_GREEN_MAX_PCT",
        "Ring buffer green-max",
        " %",
        maximum=100.0,
    ),
    _FieldSpec(
        "RING_BUFFER_YELLOW_LOW_MAX_PCT",
        "Ring buffer yellow-low-max",
        " %",
        maximum=100.0,
    ),
    _FieldSpec(
        "RING_BUFFER_RED_MAX_PCT",
        "Ring buffer red-max",
        " %",
        maximum=100.0,
    ),
    _FieldSpec(
        "RING_BUFFER_RED_DROP_MAX_PCT",
        "Ring buffer red-drop-max",
        " %",
        maximum=100.0,
    ),
    _FieldSpec(
        "RING_BUFFER_AUTO_STOP_SUSTAIN_S",
        "Ring buffer auto-stop sustain",
        " s",
        decimals=1,
        maximum=600.0,
        step=0.5,
    ),
    _FieldSpec(
        "DROPPED_FRAMES_YELLOW_MAX_PER_WINDOW",
        "丢帧 yellow-max/window",
        storage_kind="int",
        maximum=1_000_000,
        integer_editor=True,
    ),
    _FieldSpec(
        "DROPPED_FRAMES_RED_PER_10S",
        "丢帧 red/10s",
        storage_kind="int",
        maximum=1_000_000,
        integer_editor=True,
    ),
    _FieldSpec(
        "DROPPED_FRAMES_PROMPT_TOTAL",
        "丢帧 prompt-total",
        storage_kind="int",
        maximum=1_000_000,
        integer_editor=True,
    ),
    _FieldSpec(
        "DISK_FREE_AUTO_STOP_BYTES",
        "磁盘 auto-stop",
        " MB",
        decimals=1,
        storage_per_display_unit=_MB,
        storage_kind="int",
        maximum=10_000.0,
        step=10.0,
    ),
    _FieldSpec(
        "HEALTH_POLL_INTERVAL_S",
        "健康轮询间隔",
        " ms",
        decimals=0,
        storage_per_display_unit=0.001,
        maximum=60_000.0,
        step=50.0,
    ),
    _FieldSpec(
        "REC_LAST_RX_YELLOW_MIN_S",
        "REC last-rx yellow-min",
        " s",
        decimals=2,
        maximum=60.0,
        step=0.1,
    ),
    _FieldSpec(
        "REC_LAST_RX_RED_MIN_S",
        "REC last-rx red-min",
        " s",
        decimals=2,
        maximum=60.0,
        step=0.1,
    ),
    _FieldSpec(
        "XCP_YELLOW_TIMEOUTS",
        "XCP yellow timeouts",
        storage_kind="int",
        maximum=1_000_000,
        integer_editor=True,
    ),
    _FieldSpec(
        "XCP_RED_TIMEOUTS",
        "XCP red timeouts",
        storage_kind="int",
        maximum=1_000_000,
        integer_editor=True,
    ),
    _FieldSpec(
        "CONNECTION_TIMEOUT_S",
        "连接超时",
        " s",
        decimals=1,
        maximum=600.0,
        step=0.5,
    ),
    _FieldSpec(
        "DEFAULT_CAN_BITRATE_BPS",
        "默认 CAN bitrate",
        " bps",
        storage_kind="int",
        minimum=1,
        maximum=2_000_000_000,
        step=10_000,
        integer_editor=True,
    ),
)

_SPECS_BY_KEY = {spec.key: spec for spec in _FIELD_SPECS}


class TransportTabWidget(QWidget):
    """Vector transport controls for the Stage 8 cockpit path."""

    _BITRATES = (125_000, 250_000, 500_000, 1_000_000)
    _DATA_BITRATES = (2_000_000, 4_000_000, 5_000_000, 8_000_000)

    def __init__(
        self,
        transport: TransportConfig,
        *,
        ifdata: object | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ifdata = ifdata
        layout = QFormLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(8)

        self.app_combo = QComboBox(self)
        self.app_combo.setEditable(True)
        self.app_combo.addItems(["Python", "CANalyzer", "CANoe"])
        self._set_combo_text(self.app_combo, transport.app_name)
        layout.addRow("Vector Application", self.app_combo)

        self.channel_spin = QSpinBox(self)
        self.channel_spin.setRange(0, 15)
        self.channel_spin.setValue(transport.channel)
        layout.addRow("Channel", self.channel_spin)

        self.can_fd_check = QCheckBox("CAN-FD", self)
        self.can_fd_check.setChecked(transport.can_fd)
        layout.addRow("", self.can_fd_check)

        self.bitrate_combo = QComboBox(self)
        self._populate_rate_combo(self.bitrate_combo, self._BITRATES, transport.bitrate)
        layout.addRow("Bitrate", self.bitrate_combo)

        self.data_bitrate_combo = QComboBox(self)
        self._populate_rate_combo(
            self.data_bitrate_combo,
            self._DATA_BITRATES,
            transport.data_bitrate,
        )
        self.data_bitrate_combo.setEnabled(transport.can_fd)
        layout.addRow("Data bitrate", self.data_bitrate_combo)

        self.sample_point_spin = QDoubleSpinBox(self)
        self.sample_point_spin.setRange(50.0, 90.0)
        self.sample_point_spin.setDecimals(1)
        self.sample_point_spin.setSuffix(" %")
        self.sample_point_spin.setValue(transport.sample_point)
        layout.addRow("Sample point", self.sample_point_spin)

        self.fd_sample_point_spin = QDoubleSpinBox(self)
        self.fd_sample_point_spin.setRange(50.0, 90.0)
        self.fd_sample_point_spin.setDecimals(1)
        self.fd_sample_point_spin.setSuffix(" %")
        self.fd_sample_point_spin.setValue(transport.fd_sample_point)
        self.fd_sample_point_spin.setEnabled(transport.can_fd)
        layout.addRow("FD sample point", self.fd_sample_point_spin)

        self.timeout_spin = QSpinBox(self)
        self.timeout_spin.setRange(100, 10_000)
        self.timeout_spin.setSuffix(" ms")
        self.timeout_spin.setValue(int(transport.timeout_s * 1000))
        layout.addRow("Timeout", self.timeout_spin)

        seed_row = QWidget(self)
        seed_layout = QHBoxLayout(seed_row)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(6)
        self.seed_key_line = QLineEdit(self)
        self.seed_key_line.setText(transport.seed_and_key_dll or "")
        self.seed_key_browse = QPushButton("Browse", self)
        seed_layout.addWidget(self.seed_key_line, 1)
        seed_layout.addWidget(self.seed_key_browse)
        layout.addRow("Seed&&Key DLL", seed_row)

        self.test_btn = QPushButton("Test Connection", self)
        self.test_btn.setObjectName("transportTestConnectionButton")
        layout.addRow("", self.test_btn)
        layout.addRow(
            "",
            QLabel(
                "Test Connection 会先检查 Vector driver/app/channel，再做 XCP CONNECT。",
                self,
            ),
        )

        self.can_fd_check.toggled.connect(self.data_bitrate_combo.setEnabled)
        self.can_fd_check.toggled.connect(self.fd_sample_point_spin.setEnabled)
        self.seed_key_browse.clicked.connect(self._browse_seed_key)
        self._sync_test_button_enabled()

    def current_transport(self) -> TransportConfig:
        seed_key = self.seed_key_line.text().strip() or None
        return TransportConfig(
            app_name=self.app_combo.currentText().strip() or "Python",
            channel=self.channel_spin.value(),
            can_fd=self.can_fd_check.isChecked(),
            bitrate=int(self.bitrate_combo.currentData()),
            data_bitrate=int(self.data_bitrate_combo.currentData()),
            sample_point=float(self.sample_point_spin.value()),
            fd_sample_point=float(self.fd_sample_point_spin.value()),
            timeout_s=self.timeout_spin.value() / 1000.0,
            seed_and_key_dll=seed_key,
        )

    def _sync_test_button_enabled(self) -> None:
        if not sys.platform.startswith("win"):
            self.test_btn.setEnabled(False)
            self.test_btn.setToolTip("Vector 仅在 Windows 可用")
            return
        if self._ifdata is None:
            self.test_btn.setEnabled(False)
            self.test_btn.setToolTip("请先选择 A2L 文件 -- XCP 连接测试需要 CAN ID / MAX_DTO 信息")
            return
        self.test_btn.setEnabled(True)
        self.test_btn.setToolTip("执行 Vector 硬件检查和 XCP CONNECT/DISCONNECT")

    def _browse_seed_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Seed&Key DLL",
            "",
            "DLL (*.dll);;All (*)",
        )
        if path:
            self.seed_key_line.setText(path)

    @classmethod
    def _populate_rate_combo(
        cls,
        combo: QComboBox,
        values: tuple[int, ...],
        current: int,
    ) -> None:
        candidates = values if current in values else (*values, current)
        for value in candidates:
            combo.addItem(f"{value // 1000} k", value)
        idx = combo.findData(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        idx = combo.findText(text)
        if idx < 0:
            combo.addItem(text)
            idx = combo.findText(text)
        combo.setCurrentIndex(idx)


class SettingsDialog(QDialog):
    """Modal v1 settings dialog for threshold overrides.

    The coordinator can instantiate this dialog, connect ``settings_saved``,
    and refresh cockpit panels after ``exec_()`` returns accepted.
    """

    settings_saved = pyqtSignal(dict)
    settings_reset = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_path: Path | None = None,
        transport: TransportConfig | None = None,
        ifdata: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_path = (
            Path(settings_path) if settings_path is not None else None
        )
        self._editors: dict[str, QAbstractSpinBox] = {}
        self._transport = transport or TransportConfig()
        self._ifdata = ifdata
        self._test_connection_box: QMessageBox | None = None

        self.setModal(True)
        self.setWindowTitle("Cockpit Settings")
        self.setMinimumWidth(560)
        self.setObjectName("acquisitionSettingsDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("settingsTabs")
        self._tabs.addTab(self._build_threshold_tab(), "预检阈值")
        self.transport_widget = TransportTabWidget(
            self._transport,
            ifdata=self._ifdata,
            parent=self,
        )
        self.transport_widget.test_btn.clicked.connect(self._on_test_connection)
        self._tabs.addTab(self.transport_widget, "传输 / Transport")
        root.addWidget(self._tabs, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._reset_button = QPushButton("还原默认", self)
        self._reset_button.setObjectName("settingsResetButton")
        self._cancel_button = QPushButton("取消", self)
        self._cancel_button.setObjectName("settingsCancelButton")
        self._save_button = QPushButton("保存", self)
        self._save_button.setObjectName("settingsSaveButton")
        self._save_button.setDefault(True)
        footer.addWidget(self._reset_button)
        footer.addStretch(1)
        footer.addWidget(self._cancel_button)
        footer.addWidget(self._save_button)
        root.addLayout(footer)

        self._reset_button.clicked.connect(self.reset_to_defaults)
        self._cancel_button.clicked.connect(self.reject)
        self._save_button.clicked.connect(self.save)

        self._apply_values(self._initial_values())

    def editor_for_key(self, key: str) -> QAbstractSpinBox:
        """Return the editor for tests/coordinator tooling."""
        return self._editors[key]

    def values(self) -> dict[str, float | int]:
        """Return editor values in thresholds.py storage units."""
        result: dict[str, float | int] = {}
        for key, editor in self._editors.items():
            result[key] = _SPECS_BY_KEY[key].from_display(editor.value())
        return result

    def current_transport(self) -> TransportConfig:
        return self.transport_widget.current_transport()

    def open_tab(self, name: str) -> None:
        lowered = name.lower()
        for idx in range(self._tabs.count()):
            if lowered in self._tabs.tabText(idx).lower():
                self._tabs.setCurrentIndex(idx)
                return

    def _on_test_connection(self) -> None:
        result = self._run_test_connection_for_test()
        self._show_test_connection_result(result)

    def _show_test_connection_result(self, result: _TestConnectionResult) -> None:
        box = QMessageBox(self)
        box.setWindowModality(Qt.WindowModal)
        box.setWindowTitle("Test Connection")
        box.setText(result.message)
        box.setIcon(QMessageBox.Information if result.ok else QMessageBox.Warning)
        self._test_connection_box = box
        if self.isVisible():
            box.open()

    def _run_test_connection_for_test(self) -> _TestConnectionResult:
        if self._ifdata is None:
            return _TestConnectionResult(
                ok=False,
                level="red",
                message="请先选择 A2L 文件 -- XCP 连接测试需要 CAN ID / MAX_DTO 信息",
            )

        transport = self.current_transport()
        hw = vector_hw_probe(transport)
        if not hw.ok:
            return _TestConnectionResult(
                ok=False,
                level="red",
                message=f"硬件检查失败：{hw.error}",
            )

        xcp = test_xcp_connection(transport, self._ifdata)
        if not xcp.ok:
            return _TestConnectionResult(
                ok=False,
                level="red",
                message=f"XCP 连接失败：{xcp.error}",
            )

        return _TestConnectionResult(
            ok=True,
            level="green",
            message=(
                f"OK · driver {hw.driver_version} · "
                f"CONNECT/GET_STATUS · {xcp.latency_ms} ms"
            ),
        )

    def save(self) -> None:
        values = self.values()
        thresholds.save_user_settings(
            {"version": thresholds.SETTINGS_VERSION, "thresholds": values},
            path=self._settings_path,
        )
        thresholds.apply_overrides(values)
        self.settings_saved.emit(dict(values))
        self.accept()

    def reset_to_defaults(self) -> None:
        thresholds.save_user_settings(
            {"version": thresholds.SETTINGS_VERSION, "thresholds": {}},
            path=self._settings_path,
        )
        thresholds.reset_defaults()
        self._apply_values(self._default_values())
        self.settings_reset.emit()

    def _build_threshold_tab(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        form_host = QWidget(scroll)
        form = QFormLayout(form_host)
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)

        for spec in _FIELD_SPECS:
            editor = self._make_editor(spec)
            self._editors[spec.key] = editor
            form.addRow(spec.label, editor)

        scroll.setWidget(form_host)
        page_layout.addWidget(scroll)
        return page

    def _make_editor(self, spec: _FieldSpec) -> QAbstractSpinBox:
        if spec.integer_editor:
            editor = QSpinBox(self)
            editor.setRange(int(spec.minimum), int(spec.maximum))
            editor.setSingleStep(max(1, int(spec.step)))
        else:
            editor = QDoubleSpinBox(self)
            editor.setRange(float(spec.minimum), float(spec.maximum))
            editor.setDecimals(spec.decimals)
            editor.setSingleStep(float(spec.step))
        editor.setObjectName(f"thresholdEditor_{spec.key}")
        editor.setSuffix(spec.suffix)
        editor.setKeyboardTracking(False)
        return editor

    def _initial_values(self) -> dict[str, float | int]:
        values = self._default_values()
        values.update(thresholds.load_user_settings(path=self._settings_path))
        return values

    def _default_values(self) -> dict[str, float | int]:
        return {
            key: getattr(thresholds, key)
            for key in thresholds.VALID_THRESHOLD_KEYS
        }

    def _apply_values(self, values: dict[str, float | int]) -> None:
        for spec in _FIELD_SPECS:
            display_value = spec.to_display(values[spec.key])
            if spec.integer_editor:
                self._editors[spec.key].setValue(int(round(display_value)))
            else:
                self._editors[spec.key].setValue(display_value)


__all__ = ["SettingsDialog"]
