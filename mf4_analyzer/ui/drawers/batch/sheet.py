"""BatchSheet — pipeline-style batch dialog (Wave 5: full detail panels).

The toolbar buttons are the W4 placeholders (W7 wires them). The pipeline
strip and three detail panels are wired into ``_recompute_pipeline_status``
which is called once at __init__ end (per the conditional-visibility-init-sync
lesson) so the badge state is correct before ``show()``.
"""
from __future__ import annotations

import dataclasses

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
)

from ....batch import AnalysisPreset, BatchOutput
from .analysis_panel import AnalysisPanel
from .input_panel import InputPanel, STATE_PATH_PENDING, STATE_PROBING
from .output_panel import OutputPanel
from .pipeline_strip import PipelineStrip


_METHOD_LABELS: dict[str, str] = {
    "fft": "FFT",
    "order_time": "order_time",
    "order_track": "order_track",
}


class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self.resize(1080, 760)
        self._files = files or {}
        self._current_preset = current_preset

        root = QVBoxLayout(self)

        # Toolbar (placeholder buttons, Wave 7 wires)
        bar = QHBoxLayout()
        bar.addStretch(1)
        for label in ("从当前单次填入", "导入 preset…", "导出 preset…"):
            b = QPushButton(label)
            b.setEnabled(False)  # enabled in Wave 7
            bar.addWidget(b)
        root.addLayout(bar)

        # Pipeline strip
        self.strip = PipelineStrip(self)
        root.addWidget(self.strip)

        # Detail row: input | analysis | output
        detail = QWidget(self)
        detail_lay = QHBoxLayout(detail)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(14)

        self._input_panel = InputPanel(self, files=self._files)
        self._analysis_panel = AnalysisPanel(self)
        self._output_panel = OutputPanel(self)
        detail_lay.addWidget(self._input_panel, 1)
        detail_lay.addWidget(self._analysis_panel, 1)
        detail_lay.addWidget(self._output_panel, 1)
        root.addWidget(detail, 1)

        # Footer. Hoist the QDialogButtonBox so _recompute_pipeline_status
        # can toggle the Ok ("运行") button against is_runnable() — without
        # this gate, an empty config + Run falls through to the legacy
        # BatchRunner._resolve_files fallback and processes ALL loaded
        # MainWindow files × every channel (ultrareview bug_018).
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._buttons.button(QDialogButtonBox.Ok).setText("运行")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        # Wire status recomputation. Each signal is independent — we wire all
        # of them so that any sub-control mutation flows into a single
        # recompute pass.
        self._input_panel.changed.connect(self._recompute_pipeline_status)
        self._input_panel._file_list.filesChanged.connect(self._recompute_pipeline_status)
        self._input_panel._file_list.intersectionChanged.connect(
            lambda _intersection: self._recompute_pipeline_status()
        )
        self._input_panel._signal_picker.selectionChanged.connect(
            lambda _sel: self._recompute_pipeline_status()
        )
        self._analysis_panel.methodChanged.connect(
            lambda _m: self._recompute_pipeline_status()
        )
        self._analysis_panel.paramsChanged.connect(self._recompute_pipeline_status)
        self._output_panel.changed.connect(self._recompute_pipeline_status)

        # Init-sync — seed badges with the current default state.
        self._recompute_pipeline_status()

    # ------------------------------------------------------------------
    # Pipeline status recompute
    # ------------------------------------------------------------------
    def _recompute_pipeline_status(self) -> None:
        # INPUT
        fl = self._input_panel._file_list
        loaded_paths = fl.all_loaded_paths()
        any_pending = fl.has_pending_probe()
        any_failed = fl.has_probe_failed()
        selected = self._input_panel.selected_signals()
        if any_pending:
            input_status = "pending"
            input_summary = "正在解析…"
        elif any_failed:
            # A row in probe_failed must surface as warn even when other
            # config is otherwise complete (ultrareview bug_005). The
            # runner skips failed rows so is_runnable still allows Run.
            input_status = "warn"
            input_summary = (
                f"{len(loaded_paths)}文件·{len(selected)}信号"
                if (loaded_paths or selected) else "解析失败"
            )
        elif not loaded_paths or not selected:
            input_status = "warn"
            input_summary = (
                f"{len(loaded_paths)}文件·{len(selected)}信号"
                if (loaded_paths or selected) else "未配置"
            )
        else:
            input_status = "ok"
            input_summary = f"{len(loaded_paths)}文件·{len(selected)}信号"
        self.strip.set_stage(0, input_status, input_summary)

        # ANALYSIS
        method = self._analysis_panel.current_method()
        params = self._analysis_panel.get_params()
        if not method:
            self.strip.set_stage(1, "warn", "未选择方法")
        else:
            label = _METHOD_LABELS.get(method, method)
            window = params.get("window", "")
            summary = f"{label} · {window}" if window else label
            self.strip.set_stage(1, "ok", summary)

        # OUTPUT
        directory = self._output_panel.directory()
        export_data = self._output_panel.export_data()
        export_image = self._output_panel.export_image()
        if not directory or not (export_data or export_image):
            self.strip.set_stage(2, "warn", "目录/导出未配置")
        else:
            fmt = self._output_panel.data_format().upper()
            parts: list[str] = []
            if export_data:
                parts.append(fmt)
            if export_image:
                parts.append("PNG")
            self.strip.set_stage(2, "ok", "+".join(parts))

        # Gate the Run (Ok) button on is_runnable() so an empty/partial
        # config cannot reach BatchRunner's legacy fallback (ultrareview
        # bug_018). The __init__'s seed call to this method correctly
        # leaves the OK button disabled at first show.
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(self.is_runnable())

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------
    def method(self) -> str:
        return self._analysis_panel.current_method()

    def selected_signals(self) -> tuple[str, ...]:
        return self._input_panel.selected_signals()

    def rpm_channel(self) -> str:
        return self._input_panel.rpm_channel()

    def time_range(self):
        return self._input_panel.time_range()

    def file_ids(self) -> tuple:
        return self._input_panel.file_ids()

    def file_paths(self) -> tuple[str, ...]:
        return self._input_panel.file_paths()

    def params(self) -> dict:
        return self._analysis_panel.get_params()

    def output_dir(self) -> str:
        return self._output_panel.directory()

    def export_data(self) -> bool:
        return self._output_panel.export_data()

    def export_image(self) -> bool:
        return self._output_panel.export_image()

    def data_format(self) -> str:
        return self._output_panel.data_format()

    def signals_marked_unavailable(self) -> tuple[str, ...]:
        intersection = self._input_panel._file_list.current_intersection()
        return tuple(
            s for s in self.selected_signals() if s not in intersection
        )

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------
    def apply_method(self, method: str) -> None:
        self._analysis_panel.apply_method(method)

    def apply_signals(self, signals: tuple[str, ...]) -> None:
        self._input_panel.apply_signals(signals)

    def apply_rpm_channel(self, ch: str) -> None:
        self._input_panel.apply_rpm_channel(ch)

    def apply_time_range(self, rng) -> None:
        self._input_panel.apply_time_range(rng)

    def apply_params(self, params: dict) -> None:
        self._analysis_panel.apply_params(params)

    def apply_outputs(self, out: BatchOutput) -> None:
        self._output_panel.apply_outputs(out)

    def apply_files(self, file_ids: tuple, file_paths: tuple[str, ...]) -> None:
        self._input_panel.apply_files(file_ids, file_paths)

    def apply_preset(self, preset: AnalysisPreset) -> None:
        if preset is None:
            return
        self.apply_method(preset.method)
        if preset.target_signals:
            self.apply_signals(tuple(preset.target_signals))
        if preset.rpm_channel:
            self.apply_rpm_channel(preset.rpm_channel)
        if preset.params:
            self.apply_params(dict(preset.params))
        if preset.outputs:
            self.apply_outputs(preset.outputs)
        if preset.file_ids or preset.file_paths:
            self.apply_files(
                tuple(preset.file_ids or ()),
                tuple(preset.file_paths or ()),
            )

    # ------------------------------------------------------------------
    # Run-time gates
    # ------------------------------------------------------------------
    def is_runnable(self) -> bool:
        fl = self._input_panel._file_list
        for r in fl._rows.values():
            if r.state in (STATE_PATH_PENDING, STATE_PROBING):
                return False
        if not fl.all_loaded_paths():
            return False
        if not self.selected_signals():
            return False
        if not self.method():
            return False
        if not self.output_dir():
            return False
        return True

    # ------------------------------------------------------------------
    # Preset assembly
    # ------------------------------------------------------------------
    def _preset_name(self) -> str:
        return "batch"

    def get_preset(self) -> AnalysisPreset:
        # Merge the user-typed time_range field into params so
        # BatchRunner._apply_time_range sees it (ultrareview bug_009).
        # Empty field → no key, so BatchRunner runs the full signal.
        params = dict(self.params())
        rng = self.time_range()
        if rng is not None:
            params["time_range"] = rng
        base = AnalysisPreset.free_config(
            name=self._preset_name(),
            method=self.method(),
            target_signals=self.selected_signals(),
            rpm_channel=self.rpm_channel(),
            params=params,
            outputs=BatchOutput(
                export_data=self.export_data(),
                export_image=self.export_image(),
                data_format=self.data_format(),
            ),
        )
        return dataclasses.replace(
            base,
            file_ids=self.file_ids(),
            file_paths=self.file_paths(),
        )
