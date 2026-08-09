"""Analysis column for the compact batch dialog."""
from __future__ import annotations

import math

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from ....analysis_presets import list_builtin_presets
from ....list_text import split_list_text
from ...analysis_preset_slots import preset_slot_bus, read_slot
from .method_buttons import DynamicParamForm, MethodButtonGroup
from .chart_statistics_panel import ChartStatisticsPanel
from .optional_eyebrow import BatchOptionalEyebrow
from .slice_panel import SlicePanel


_METHOD_TO_KIND = {
    "fft": "fft",
    "fft_time": "fft_time",
    "frf": "frf",
    "order_time": "order",
}
_PARAMETER_TITLES = {
    "time": "图片如何合并",
    "fft": "FFT 参数",
    "fft_time": "FFT vs Time 参数",
    "frf": "FRF 估计与显示",
    "order_time": "阶次参数",
}
_SLOT_TO_KEY = {1: "torque", 2: "vibration", 3: "transient", 4: "custom"}
_KEY_TO_SLOT = {value: key for key, value in _SLOT_TO_KEY.items()}
_SPECTROGRAM_METHODS = frozenset({"fft_time", "order_time"})


class _PresetCard(QPushButton):
    """Two-level preset card while keeping ``text()`` as the slot name."""

    # Match the denser single-analysis preset strip while retaining Batch's
    # larger click target and parameter summary.
    _TITLE_POINT_SIZE = 11
    _SUMMARY_POINT_SIZE = 8
    _NORMAL_HEIGHT = 66
    _COMPACT_HEIGHT = 40

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._summary = ""
        self._summary_visible = True
        self.setProperty("textAlignment", "center")
        self.setProperty("compact", False)
        self.setFixedHeight(self._NORMAL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set_summary_text(self, text: str) -> None:
        self._summary = str(text or "")
        self.update()

    def summary_text(self) -> str:
        return self._summary

    def summary_visible(self) -> bool:
        return self._summary_visible

    def set_compact_mode(self, compact: bool) -> None:
        compact = bool(compact)
        self._summary_visible = not compact
        self.setProperty("compact", compact)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setFixedHeight(
            self._COMPACT_HEIGHT if compact else self._NORMAL_HEIGHT
        )
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.text = ""
        if self.isChecked():
            option.state |= QStyle.State_On
        self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
        rect = QRectF(self.rect()).adjusted(8, 5, -8, -5)
        painter.setPen(QColor("#0b73e7" if self.isChecked() else "#111827"))
        painter.setFont(QFont(
            self.font().family(), self._TITLE_POINT_SIZE, QFont.Bold,
        ))
        title_height = 22 if self._summary_visible else rect.height()
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), title_height),
            Qt.AlignHCenter | Qt.AlignVCenter, self.text(),
        )
        if self._summary_visible:
            painter.setPen(QColor("#506d93" if self.isChecked() else "#64748b"))
            painter.setFont(QFont(self.font().family(), self._SUMMARY_POINT_SIZE))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 24, rect.width(), rect.height() - 24),
                Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap, self._summary,
            )
        painter.end()


class AnalysisPanel(QWidget):
    """Method controls, shared spectral slots, and method-owned parameters."""

    methodChanged = pyqtSignal(str)
    paramsChanged = pyqtSignal()
    presetApplied = pyqtSignal(str, object)
    presetStateChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchAnalysisPanel")
        outer = QVBoxLayout(self)
        self._outer_layout = outer
        outer.setContentsMargins(12, 14, 12, 18)
        outer.setSpacing(10)

        method_head = QWidget(self)
        method_head_lay = QHBoxLayout(method_head)
        method_head_lay.setContentsMargins(0, 0, 0, 0)
        method_head_lay.setSpacing(6)
        self._method_title = QLabel("分析方法", method_head)
        self._method_title.setObjectName("BatchSectionTitle")
        method_head_lay.addWidget(self._method_title)
        method_head_lay.addStretch(1)
        method_note = QLabel("决定下面的参数", method_head)
        method_note.setObjectName("BatchSectionNote")
        method_head_lay.addWidget(method_note)
        outer.addWidget(method_head)

        self._method_group = MethodButtonGroup(self)
        outer.addWidget(self._method_group)

        self._preset_host = QWidget(self)
        preset_layout = QVBoxLayout(self._preset_host)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(6)
        head = QHBoxLayout()
        self._preset_title = QLabel("分析预设", self._preset_host)
        self._preset_title.setObjectName("BatchAnalysisChoiceLabel")
        head.addWidget(self._preset_title)
        self._preset_sync_badge = QLabel("与单次分析同步", self._preset_host)
        self._preset_sync_badge.setObjectName("BatchPresetSyncBadge")
        head.addStretch(1)
        head.addWidget(self._preset_sync_badge)
        preset_layout.addLayout(head)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self._preset_buttons: dict[str, _PresetCard] = {}
        for key in ("torque", "vibration", "transient", "custom"):
            button = _PresetCard(self._preset_host)
            button.setObjectName("BatchAnalysisPresetCard")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, preset_key=key: self._apply_slot(preset_key)
            )
            self._preset_group.addButton(button)
            row.addWidget(button, 1)
            self._preset_buttons[key] = button
        preset_layout.addLayout(row)
        outer.addWidget(self._preset_host)

        params_head = QHBoxLayout()
        self._params_title = QLabel("参数", self)
        self._params_title.setStyleSheet("color:#475569;font-size:12px;")
        self._preset_state = QLabel("未应用预设", self)
        self._preset_state.setObjectName("BatchPresetState")
        params_head.addWidget(self._params_title)
        params_head.addStretch(1)
        params_head.addWidget(self._preset_state)
        outer.addLayout(params_head)

        self._param_form = DynamicParamForm(self)
        outer.addWidget(self._param_form)

        self._frf_grouping_host = QWidget(self)
        self._frf_grouping_host.setObjectName("BatchFrfChartGrouping")
        grouping_outer = QVBoxLayout(self._frf_grouping_host)
        grouping_outer.setContentsMargins(0, 0, 0, 0)
        grouping_outer.setSpacing(0)
        self._frf_grouping_eyebrow = BatchOptionalEyebrow(
            "可选 · 图表组织", self._frf_grouping_host,
        )
        grouping_outer.addWidget(self._frf_grouping_eyebrow)
        grouping_row = QWidget(self._frf_grouping_host)
        grouping_lay = QHBoxLayout(grouping_row)
        grouping_lay.setContentsMargins(0, 0, 0, 0)
        grouping_lay.setSpacing(8)
        grouping_lay.addWidget(QLabel("图表组织", grouping_row))
        self._frf_grouping_combo = QComboBox(grouping_row)
        self._frf_grouping_combo.addItem("每对一张", "none")
        self._frf_grouping_combo.addItem("按来源叠加", "source")
        self._frf_grouping_combo.addItem("按输入/输出对叠加", "channel")
        self._frf_grouping_combo.setMinimumWidth(0)
        self._frf_grouping_combo.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed,
        )
        grouping_lay.addWidget(self._frf_grouping_combo, 1)
        grouping_outer.addWidget(grouping_row)
        self._frf_grouping_host.hide()
        outer.addWidget(self._frf_grouping_host)
        self._chart_statistics = ChartStatisticsPanel(self)
        outer.addWidget(self._chart_statistics)
        self._slice = SlicePanel(self)
        outer.addWidget(self._slice)

        self._source_interval_host = QWidget(self)
        self._source_interval_host.setObjectName("BatchSourceInterval")
        source_outer = QVBoxLayout(self._source_interval_host)
        source_outer.setContentsMargins(0, 0, 0, 0)
        source_outer.setSpacing(0)
        self._source_interval_eyebrow = BatchOptionalEyebrow(
            "可选 · 分析区间", self._source_interval_host,
        )
        source_outer.addWidget(self._source_interval_eyebrow)
        source_row_host = QWidget(self._source_interval_host)
        source_row = QHBoxLayout(source_row_host)
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        source_row.addWidget(QLabel("源数据区间", source_row_host))
        self._source_interval_mode = QComboBox(source_row_host)
        self._source_interval_mode.addItem("全时段", "all")
        self._source_interval_mode.addItem("指定区间", "manual")
        self._source_interval_edit = QLineEdit(source_row_host)
        self._source_interval_edit.setPlaceholderText("0.0, 120.0 s")
        self._source_interval_edit.setEnabled(False)
        source_row.addWidget(self._source_interval_mode)
        source_row.addWidget(self._source_interval_edit, 1)
        source_outer.addWidget(source_row_host)
        outer.addWidget(self._source_interval_host)
        outer.addStretch(1)

        self._applying_slot = False
        self._applied_key: str | None = None
        self._applied_snapshot: dict = {}
        self._method_group.methodChanged.connect(self._on_method_changed)
        self._param_form.paramsChanged.connect(self._on_params_changed)
        self._frf_grouping_combo.currentIndexChanged.connect(self._on_params_changed)
        self._chart_statistics.changed.connect(self._on_params_changed)
        self._slice.changed.connect(self._on_params_changed)
        self._source_interval_mode.currentIndexChanged.connect(
            self._sync_source_interval_enabled
        )
        self._source_interval_mode.currentIndexChanged.connect(self.paramsChanged)
        self._source_interval_edit.textChanged.connect(self.paramsChanged)
        preset_slot_bus().changed.connect(self._on_shared_slot_changed)

        self._param_form.set_method(self._method_group.current_method())
        self._sync_source_interval_enabled()
        self._refresh_for_method(clear_selection=True)

    # ------------------------------------------------------------------
    def _kind(self) -> str | None:
        return _METHOD_TO_KIND.get(self.current_method())

    def _builtin_by_key(self) -> dict[str, object]:
        method = self.current_method()
        if method == "time":
            return {}
        presets = tuple(list_builtin_presets(method))
        if method == "frf":
            return dict(zip(("torque", "vibration", "transient"), presets))
        return {item.key: item for item in presets}

    def _slot_payload(self, key: str) -> tuple[str, dict, bool, bool]:
        """Return name, patch, enabled and stored-state for a visible card."""

        kind = self._kind()
        slot = _KEY_TO_SLOT[key]
        if kind is None:
            return key, {}, False, False
        builtins = self._builtin_by_key()
        builtin = key != "custom"
        default_name = "自定义" if key == "custom" else builtins[key].display_name
        stored = read_slot(
            kind, slot, default_name=default_name, builtin=builtin,
            custom=not builtin,
        )
        if stored is not None:
            return stored.name, dict(stored.params), True, True
        if builtin:
            preset = builtins[key]
            return preset.display_name, preset.params_copy(), bool(preset.enabled), False
        return default_name, {}, True, False

    def _refresh_for_method(self, *, clear_selection: bool) -> None:
        method = self.current_method()
        is_time = method == "time"
        self._preset_host.setVisible(not is_time)
        self._source_interval_host.setVisible(method == "fft")
        self._chart_statistics.setVisible(is_time)
        self._slice.setVisible(method in _SPECTROGRAM_METHODS)
        self._slice.set_context(method=method)
        self._params_title.setText(_PARAMETER_TITLES.get(method, "分析参数"))
        self._preset_state.setVisible(not is_time)
        self._frf_grouping_host.setVisible(method == "frf")
        if is_time:
            self._clear_applied(emit=False, dirty=False)
            return
        for key, button in self._preset_buttons.items():
            name, patch, enabled, stored = self._slot_payload(key)
            button.setText(name)
            button.set_summary_text(self._preset_summary(patch, stored=stored))
            button.setEnabled(enabled)
            button.setToolTip("单次分析保存的预设" if stored else "单次分析内建预设")
        if clear_selection:
            self._clear_applied(emit=False, dirty=False)

    @staticmethod
    def _preset_summary(patch: dict, *, stored: bool) -> str:
        if not patch:
            return "未保存参数" if stored else "当前参数 · 手动调整"
        parts: list[str] = []
        window = patch.get("window")
        if window:
            parts.append(str(window))
        duration = patch.get("t_win_s")
        if duration is not None:
            try:
                parts.append(f"{float(duration):g} s")
            except (TypeError, ValueError):
                pass
        if not parts and patch.get("max_order") is not None:
            parts.append(f"最大 {patch['max_order']} 阶")
        return " · ".join(parts) or "单次分析参数"

    def refresh_shared_presets(self) -> None:
        self._refresh_for_method(clear_selection=False)

    def _on_shared_slot_changed(self, kind: str, slot: int) -> None:
        if kind == self._kind():
            self.refresh_shared_presets()
            if self._applied_key == _SLOT_TO_KEY.get(int(slot)):
                # A single-analysis edit changed the saved patch underneath
                # this sheet. The currently displayed values are still the
                # old patch, so retaining a selected card would mislead.
                self._clear_applied(emit=True)

    def _on_method_changed(self, method: str) -> None:
        # The sheet must update the dependent input/output panels and recipe
        # before it recomputes status.  Avoid an intermediate paramsChanged
        # emission from the form while this method-change transaction is still
        # incomplete; the following methodChanged is the authoritative refresh.
        self._param_form.set_method(method, emit=False)
        self._refresh_for_method(clear_selection=True)
        self.methodChanged.emit(method)
        self.presetStateChanged.emit(self.preset_state_text())

    def _on_params_changed(self) -> None:
        if not self._applying_slot and self._applied_snapshot:
            current = self.get_params()
            if any(current.get(key) != value for key, value in self._applied_snapshot.items()):
                self._clear_applied(emit=True)
        self.paramsChanged.emit()

    def _apply_slot(self, key: str) -> None:
        name, patch, enabled, stored = self._slot_payload(key)
        if not enabled:
            return
        if key == "custom" and not stored:
            self._clear_applied(emit=True)
            return
        self._applying_slot = True
        try:
            self._param_form.apply_params(patch)
            current = self.get_params()
            self._applied_snapshot = {
                field: current[field] for field in patch if field in current
            }
            self._applied_key = key
            for item_key, button in self._preset_buttons.items():
                button.setChecked(item_key == key)
            self._preset_state.setText(f"已应用：{name}")
            self._preset_state.setProperty("modified", "false")
        finally:
            self._applying_slot = False
        self.presetApplied.emit(key, dict(patch))
        self.presetStateChanged.emit(self.preset_state_text())
        self.paramsChanged.emit()

    def _clear_applied(self, *, emit: bool, dirty: bool = True) -> None:
        self._applied_key = None
        self._applied_snapshot = {}
        # QButtonGroup refuses to uncheck its final checked button while it is
        # exclusive.  Dirty state deliberately has *no* selected card.
        self._preset_group.setExclusive(False)
        try:
            for button in self._preset_buttons.values():
                button.setChecked(False)
        finally:
            self._preset_group.setExclusive(True)
        self._preset_state.setText(
            "已修改 · 未匹配预设" if dirty else "未应用预设"
        )
        self._preset_state.setProperty("modified", "true" if dirty else "false")
        if emit:
            self.presetStateChanged.emit(self.preset_state_text())

    def _sync_source_interval_enabled(self) -> None:
        self._source_interval_edit.setEnabled(
            self._source_interval_mode.currentData() == "manual"
        )

    # ------------------------------------------------------------------
    def current_method(self) -> str:
        return self._method_group.current_method()

    def set_method(self, method: str) -> None:
        self._method_group.set_method(method)

    def set_grouping_counts(self, *, source_count: int, signal_count: int) -> None:
        self._param_form.set_grouping_counts(
            source_count=source_count, signal_count=signal_count,
        )

    def set_compact_mode(self, compact: bool) -> None:
        side = 12 if compact else 18
        self._outer_layout.setContentsMargins(side, 14, side, 18)
        for button in self._preset_buttons.values():
            button.set_compact_mode(compact)
        self._param_form.set_compact_mode(compact)

    def get_params(self) -> dict:
        params = self._param_form.get_params()
        method = self.current_method()
        if method == "time":
            params.update(self._chart_statistics.get_params())
        elif method == "frf":
            params["render_group_by"] = str(
                self._frf_grouping_combo.currentData() or "none"
            )
        elif method in _SPECTROGRAM_METHODS:
            params.update(self._slice.get_params())
        return params

    def apply_method(self, method: str) -> None:
        self.set_method(method)

    def apply_params(self, params: dict) -> None:
        self._param_form.apply_params(params)
        if isinstance(params, dict) and "render_group_by" in params:
            index = self._frf_grouping_combo.findData(
                str(params.get("render_group_by") or "none")
            )
            if index >= 0:
                self._frf_grouping_combo.setCurrentIndex(index)
        self._chart_statistics.apply_params(params)
        self._slice.apply_params(params)

    def slice_positions_error(self) -> str:
        if self.current_method() not in _SPECTROGRAM_METHODS:
            return ""
        return self._slice.positions_error()

    def set_chart_statistics_x_context(self, *, x_source, x_channel="", unit="s") -> None:
        self._chart_statistics.set_context(x_source=x_source, x_channel=x_channel, unit=unit)

    def set_weighting_options(self, options) -> None:
        self._param_form.set_weighting_options(options)

    def source_interval_widget(self) -> QWidget:
        return self._source_interval_host

    def source_time_range(self) -> tuple[float, float] | None:
        if self.current_method() != "fft" or self._source_interval_mode.currentData() != "manual":
            return None
        try:
            parts = split_list_text(self._source_interval_edit.text())
            if len(parts) != 2:
                return None
            lo, hi = float(parts[0]), float(parts[1])
        except (TypeError, ValueError):
            return None
        return (lo, hi) if math.isfinite(lo) and math.isfinite(hi) and lo < hi else None

    def source_time_range_error(self) -> str:
        if self.current_method() != "fft" or self._source_interval_mode.currentData() != "manual":
            return ""
        parts = split_list_text(self._source_interval_edit.text())
        if len(parts) != 2 or not all(parts):
            return "源数据区间：请输入两个逗号分隔的数字（中英文均可）"
        try:
            lo, hi = (float(item) for item in parts)
        except ValueError:
            return "源数据区间：请输入两个逗号分隔的数字（中英文均可）"
        if not math.isfinite(lo) or not math.isfinite(hi):
            return "源数据区间：请输入有限数字"
        if lo >= hi:
            return "源数据区间：起点必须小于终点"
        return ""

    def apply_source_time_range(self, value) -> None:
        if value is None:
            self._source_interval_mode.setCurrentIndex(0)
            self._source_interval_edit.setText("")
            return
        lo, hi = value
        self._source_interval_mode.setCurrentIndex(1)
        self._source_interval_edit.setText(f"{float(lo):g}, {float(hi):g}")

    def preset_state_text(self) -> str:
        return self._preset_state.text()

    def has_applied_preset(self) -> bool:
        return self._applied_key is not None

    def clear_applied_preset(self) -> None:
        if self._applied_key is not None:
            self._clear_applied(emit=True)
