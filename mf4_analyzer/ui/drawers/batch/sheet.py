"""BatchSheet — pipeline-style batch dialog (Wave 6: end-to-end runnable).

The pipeline strip and three detail panels are wired into
``_recompute_pipeline_status`` which is called once at __init__ end (per
the conditional-visibility-init-sync lesson) so the badge state is
correct before ``show()``.

Wave 6 adds the bottom task list, the ``BatchRunnerThread`` lifecycle,
lock/unlock during a run, and a closeEvent confirmation that re-routes
through the cancel path. **Unlock is bound to ``QThread.finished``**, not
``finished_with_result`` (spec §6.2): even if ``runner.run()`` raises
before the result signal would have fired, ``QThread.finished`` still
arrives via Qt and the dialog re-enables.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ....batch import AnalysisPreset, BatchOutput, BatchRunner
from ....batch_preset_io import (
    UnsupportedPresetVersion, load_preset_from_json, save_preset_to_json,
)
from ....batch_recipe import normalize_batch_params
from ....batch_validation import (
    ValidationIssue, validate_outputs, validate_recipe,
)
from ....io.source_adapters import DEFAULT_SOURCE_ADAPTER_REGISTRY
from .analysis_panel import AnalysisPanel
from .input_panel import InputPanel, STATE_PATH_PENDING, STATE_PROBING
from .output_panel import OutputPanel
from .pipeline_strip import PipelineStrip
from .runner_thread import BatchRunnerThread
from .task_list import TaskListWidget


_METHOD_LABELS: dict[str, str] = {
    "time": "时域",
    "fft": "FFT",
    "fft_time": "FFT vs Time",
    "order_time": "阶次",
}

_OUTPUT_ISSUE_FIELDS = frozenset({
    "outputs",
    "data_format",
    "image_format",
    "image_size",
    "image_width",
    "image_height",
    "image_pixels",
    "image_dpi",
    "conflict_policy",
    "resume_policy",
})

class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self.resize(1080, 760)
        self._files = files or {}
        self._current_preset = current_preset
        self._base_name = "batch"
        self._base_params: dict = {}
        self._recipe_method = "fft"
        self._applied_control_snapshot: dict = {}
        self._applying_preset = False
        self._scope_source = "free_config"
        self._scope_signal = None
        self._scope_rpm_signal = None
        self._scope_target_pairs: tuple = ()
        self._scope_file_ids: tuple = ()
        self._scope_file_paths: tuple[str, ...] = ()
        self._scope_source_ids: tuple = ()
        self._scope_source_paths: tuple[str, ...] = ()
        self._scope_target_policy = "common"
        self._scope_signals: tuple[str, ...] = ()
        self._scope_rpm_channel = ""
        self._source_registry = DEFAULT_SOURCE_ADAPTER_REGISTRY
        source_context = getattr(parent, "batch_source_context", {}) if parent else {}
        self._source_context = (
            dict(source_context) if isinstance(source_context, dict) else {}
        )

        # Run-state bookkeeping (W6).
        self._running: bool = False
        self._runner_thread: BatchRunnerThread | None = None
        self._last_result = None
        self._close_pending: bool = False
        self._resume_manifest_path: str | None = None
        self._retry_failed_manifest_path: str | None = None

        # W7 toast bookkeeping — populated by ``_toast`` so headless tests
        # can assert deterministically without mocking the parent's toast
        # API. Production paths additionally forward to ``parent.toast`` if
        # the host exposes one (MainWindow does).
        self._last_toast_text: str = ""
        self._last_toast_kind: str = ""

        root = QVBoxLayout(self)

        # Toolbar — W7 wires three buttons:
        #   • 从当前单次填入: enabled iff a current_preset was passed in,
        #     fills the dialog from that preset (spec §6.4 current_single).
        #   • 导入 preset…  : open JSON, load, apply (warns on
        #     UnsupportedPresetVersion / corrupt JSON via toast).
        #   • 导出 preset… : strip runtime fields via dataclasses.replace
        #     and save to JSON (spec §6.3).
        bar = QHBoxLayout()
        bar.addStretch(1)

        self._btn_fill_from_current = QPushButton("从当前单次填入")
        self._btn_fill_from_current.setEnabled(self._current_preset is not None)
        self._btn_fill_from_current.clicked.connect(self._on_fill_from_current)
        bar.addWidget(self._btn_fill_from_current)

        self._btn_import_preset = QPushButton("导入 preset…")
        self._btn_import_preset.clicked.connect(self._on_import_preset)
        bar.addWidget(self._btn_import_preset)

        self._btn_export_preset = QPushButton("导出 preset…")
        self._btn_export_preset.clicked.connect(self._on_export_preset)
        bar.addWidget(self._btn_export_preset)

        root.addLayout(bar)

        # Pipeline strip
        self.strip = PipelineStrip(self)
        root.addWidget(self.strip)

        # Detail row: input | analysis | output
        detail = QWidget(self)
        detail_lay = QHBoxLayout(detail)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(14)

        self._input_panel = InputPanel(
            self, files=self._files, source_registry=self._source_registry,
            source_context=self._source_context,
        )
        self._analysis_panel = AnalysisPanel(self)
        self._analysis_panel.set_weighting_options(
            self._weighting_options_from_parent()
        )
        self._output_panel = OutputPanel(self)
        store = getattr(parent, "db_reference_store", None) if parent else None
        if store is not None:
            self._output_panel.set_reference_catalog(store.snapshot())

        def scrolling_pane(panel: QWidget, name: str) -> QScrollArea:
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            scroll = QScrollArea(detail)
            scroll.setObjectName(name)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setMinimumSize(0, 0)
            scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
            scroll.setStyleSheet(
                f"QScrollArea#{name} {{ border: none; background: transparent; }}"
                f"QScrollArea#{name} > QWidget > QWidget {{ background: #ffffff; }}"
            )
            scroll.setWidget(panel)
            return scroll

        self._input_scroll = scrolling_pane(
            self._input_panel, "BatchInputScroll"
        )
        self._analysis_scroll = scrolling_pane(
            self._analysis_panel, "BatchAnalysisScroll"
        )
        self._output_scroll = scrolling_pane(
            self._output_panel, "BatchOutputScroll"
        )
        detail_lay.addWidget(self._input_scroll, 1)
        detail_lay.addWidget(self._analysis_scroll, 1)
        detail_lay.addWidget(self._output_scroll, 1)
        root.addWidget(detail, 1)

        # W6: Task list (collapsible, below detail row, above footer).
        self._task_list = TaskListWidget(self)
        root.addWidget(self._task_list)

        # Footer (W6): hand-rolled button row so we can swap layouts between
        # idle ([Cancel] [运行]) and running ([中断]) modes. The Ok button is
        # gated on is_runnable() in idle mode (ultrareview bug_018) — without
        # the gate, an empty config + Run would have fallen through to the
        # legacy BatchRunner._resolve_files fallback and processed ALL loaded
        # MainWindow files × every channel.
        self._footer_host = QWidget(self)
        self._footer_lay = QHBoxLayout(self._footer_host)
        self._footer_lay.setContentsMargins(0, 0, 0, 0)
        self._footer_lay.setSpacing(8)
        self._footer_lay.addStretch(1)

        # Idle-mode buttons
        self._btn_cancel = QPushButton("Cancel", self._footer_host)
        self._btn_cancel.clicked.connect(self.reject)
        self._footer_lay.addWidget(self._btn_cancel)

        self._btn_run = QPushButton("运行", self._footer_host)
        self._btn_run.setDefault(True)
        self._btn_run.clicked.connect(self._on_run_clicked)
        self._footer_lay.addWidget(self._btn_run)

        # Running-mode button (hidden until a run starts)
        self._btn_abort = QPushButton("中断", self._footer_host)
        self._btn_abort.clicked.connect(self._on_cancel_clicked)
        self._btn_abort.setVisible(False)
        self._footer_lay.addWidget(self._btn_abort)

        root.addWidget(self._footer_host)

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
        # Drive RPM-row visibility from the method (init-sync below).
        self._analysis_panel.methodChanged.connect(self._input_panel.set_method)
        self._analysis_panel.methodChanged.connect(
            self._output_panel.apply_method_defaults
        )
        self._analysis_panel.methodChanged.connect(self._on_recipe_method_changed)
        self._analysis_panel.paramsChanged.connect(self._recompute_pipeline_status)
        self._analysis_panel.presetApplied.connect(
            self._on_builtin_analysis_preset
        )
        self._output_panel.changed.connect(self._recompute_pipeline_status)
        self._output_panel.resumeRequested.connect(self._on_resume_requested)
        self._output_panel.retryFailedRequested.connect(
            self._on_retry_failed_requested
        )
        self._task_list.artifactOpenRequested.connect(
            self._open_artifact_location
        )

        # Init-sync (per conditional-visibility-init-sync lesson): seed the
        # RPM row before show() so it doesn't flash visible.
        self._input_panel.set_method(self._analysis_panel.current_method())

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
        unavailable_reasons = fl.unavailable_reasons()
        any_failed = fl.has_probe_failed() or bool(unavailable_reasons)
        selected = self._input_panel.selected_signals()
        time_error = self._input_panel.time_range_error()
        if any_pending:
            input_status = "pending"
            input_summary = "正在解析…"
        elif time_error:
            input_status = "warn"
            input_summary = time_error
        elif any_failed:
            # A row in probe_failed must surface as warn even when other
            # config is otherwise complete (ultrareview bug_005). The
            # runner skips failed rows so is_runnable still allows Run.
            input_status = "warn"
            input_summary = unavailable_reasons[0] if unavailable_reasons else (
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
        preflight_issues = self.preflight_issues()
        analysis_issues = tuple(
            issue for issue in preflight_issues
            if issue.field != "time_range"
            and issue.field not in _OUTPUT_ISSUE_FIELDS
        )
        if analysis_issues:
            issue = analysis_issues[0]
            self.strip.set_stage(
                1, "warn", f"{issue.field}: {issue.message}",
            )
        elif not method:
            self.strip.set_stage(1, "warn", "未选择方法")
        else:
            label = _METHOD_LABELS.get(method, method)
            window = params.get("window", "")
            summary = f"{label} · {window}" if window else label
            self.strip.set_stage(1, "ok", summary)

        # OUTPUT
        directory = self._output_panel.directory()
        outputs = self._output_panel.get_outputs()
        export_data = outputs.export_data
        export_image = outputs.export_image
        output_issues = tuple(
            issue for issue in preflight_issues
            if issue.field in _OUTPUT_ISSUE_FIELDS
        )
        if output_issues:
            issue = output_issues[0]
            self.strip.set_stage(
                2, "warn", f"{issue.field}: {issue.message}",
            )
            self._output_panel.set_output_preview(error=issue.message)
        elif not directory or not (export_data or export_image):
            self.strip.set_stage(2, "warn", "目录/导出未配置")
            self._output_panel.set_output_preview(None)
        else:
            parts: list[str] = []
            if export_data:
                parts.append(outputs.data_format.upper())
            if export_image:
                parts.append(outputs.image_format.upper())
            self.strip.set_stage(2, "ok", "+".join(parts))
            if loaded_paths and selected and method:
                try:
                    preview = self._make_runner().preview_outputs(
                        self.get_preset(), directory,
                    )
                except (TypeError, ValueError, OSError) as exc:
                    self._output_panel.set_output_preview(error=str(exc))
                else:
                    self._output_panel.set_output_preview(preview)
            else:
                self._output_panel.set_output_preview(None)

        self._output_panel.update_effective_preview(
            tuple(fl._rows.values()), selected,
            weighting=str(params.get("weighting", "None")),
            target_policy=self.target_policy(),
            target_pairs=(
                self._scope_target_pairs
                if self._scope_target_policy == "exact_pairs" else ()
            ),
        )

        # Gate the Run button on is_runnable() so an empty/partial
        # config cannot reach BatchRunner's legacy fallback (ultrareview
        # bug_018). The __init__'s seed call to this method correctly
        # leaves the run button disabled at first show. While a run is in
        # progress, the run button is hidden behind the 中断 swap, so we
        # only adjust enabled-state in idle mode.
        if not self._running:
            self._btn_run.setEnabled(self.is_runnable())

    def _weighting_options_from_parent(self) -> tuple[str, ...]:
        parent = self.parent()
        inspector = getattr(parent, "inspector", None)
        for ctx_name in ("fft_ctx", "fft_time_ctx", "order_ctx"):
            ctx = getattr(inspector, ctx_name, None)
            combo = getattr(ctx, "combo_weighting", None)
            count = combo.count() if combo is not None else 0
            if count:
                return tuple(combo.itemText(i) for i in range(count))
        return ("None", "A")

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

    def source_ids(self) -> tuple:
        return self._input_panel.source_ids()

    def source_paths(self) -> tuple[str, ...]:
        return self._input_panel.source_paths()

    def target_policy(self) -> str:
        exact_scope_unchanged = (
            self.source_ids(), self.source_paths(), self.selected_signals()
        ) == (
            self._scope_source_ids, self._scope_source_paths, self._scope_signals
        )
        if (
            self._scope_target_policy == "exact_pairs"
            and self._scope_target_pairs
            and exact_scope_unchanged
        ):
            return "exact_pairs"
        return self._input_panel.target_policy()

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
        file_list = self._input_panel._file_list
        policy = self.target_policy()
        if policy == "exact_pairs":
            rows = file_list.loaded_rows()
            unavailable: list[str] = []
            for source_id, signal in self._scope_target_pairs:
                row = next(
                    (
                        item for item in rows
                        if item.source_id == source_id or item.fid == source_id
                    ),
                    None,
                )
                if row is None or signal not in row.channels:
                    unavailable.append(str(signal))
            return tuple(dict.fromkeys(unavailable))

        if policy == "available_per_source":
            available = frozenset().union(
                *(row.channels for row in file_list.loaded_rows())
            )
        else:
            available = file_list.current_intersection()
        return tuple(
            signal for signal in self.selected_signals()
            if signal not in available
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

    def apply_sources(self, source_ids: tuple, source_paths: tuple[str, ...]) -> None:
        self._input_panel.apply_sources(source_ids, source_paths)

    def _on_builtin_analysis_preset(self, _key: str, patch: dict) -> None:
        # AnalysisPanel already applied its owned fields.  OUTPUT owns display
        # scale/axes; partial application deliberately excludes export choices,
        # source scope and dB reference state.
        display_patch = {
            key: value for key, value in dict(patch or {}).items()
            if key not in {"db_reference", "db_reference_mode"}
        }
        self._output_panel.apply_axis_params(display_patch)
        self._recompute_pipeline_status()

    def apply_preset(self, preset: AnalysisPreset) -> None:
        """Fill the dialog from a preset (spec §6.4).

        For ``current_single``: narrow the file list to ``preset.signal[0]``
        and select ``preset.signal[1]``. The captured signal is the only
        one in scope — the user opted in to "this exact analysis".

        For ``free_config``: keep the current file selection (a free_config
        preset is a recipe; file selection is local) but apply the recipe
        fields. Signals not in the current intersection get red-marked via
        ``signals_marked_unavailable`` (spec §4.2).

        ``time_range`` lives in ``preset.params`` (W2/W6 contract); we
        round-trip it into the time-range field so the user sees the
        original window.
        """
        if preset is None:
            return
        method = str(preset.method)
        params = normalize_batch_params(dict(preset.params), method)
        target_pairs = tuple(tuple(pair) for pair in (preset.target_pairs or ()))
        runtime_source_ids = tuple(
            getattr(preset, "source_ids", ()) or preset.file_ids or ()
        )
        runtime_source_paths = tuple(
            getattr(preset, "source_paths", ()) or preset.file_paths or ()
        )
        requested_policy = str(
            getattr(preset, "target_policy", "common") or "common"
        )

        self._applying_preset = True
        try:
            self._base_name = str(preset.name or "batch")
            self._base_params = dict(params)
            self._recipe_method = method
            self._scope_source = str(preset.source or "free_config")
            self._scope_signal = (
                tuple(preset.signal) if preset.signal is not None else None
            )
            self._scope_rpm_signal = (
                tuple(preset.rpm_signal) if preset.rpm_signal is not None else None
            )
            self._scope_target_pairs = target_pairs
            self._scope_target_policy = (
                "exact_pairs" if target_pairs else requested_policy
            )
            self._input_panel.apply_target_policy(self._scope_target_policy)

            if preset.source == "current_single" and preset.signal is not None:
                signal_fid, signal_name = preset.signal
                source_path = runtime_source_paths
                if not source_path:
                    fd = self._files.get(signal_fid)
                    filepath = getattr(fd, "filepath", None)
                    source_path = (str(filepath) if filepath is not None else str(signal_fid),)
                self.apply_sources(
                    source_ids=runtime_source_ids or (signal_fid,),
                    source_paths=source_path,
                )
                self.apply_signals((signal_name,))
            elif target_pairs:
                pair_file_ids = tuple(dict.fromkeys(pair[0] for pair in target_pairs))
                pair_signals = tuple(dict.fromkeys(str(pair[1]) for pair in target_pairs))
                self.apply_sources(
                    source_ids=runtime_source_ids or pair_file_ids,
                    source_paths=runtime_source_paths,
                )
                self.apply_signals(tuple(preset.target_signals or pair_signals))
            else:
                # A reusable free-config preset carries a recipe, not a forced
                # runtime file scope. Keep the dialog's current file selection.
                if runtime_source_ids or runtime_source_paths:
                    self.apply_sources(runtime_source_ids, runtime_source_paths)
                self.apply_signals(tuple(preset.target_signals))

            self.apply_method(method)
            self.apply_params(params)
            if "rpm_factor" in params:
                self._input_panel.apply_rpm_factor(params["rpm_factor"])
            self._input_panel.apply_filter_params(params.get("filter"))
            self._output_panel.apply_axis_params(params)
            self._output_panel.apply_reference_params(params)
            rpm_channel = preset.rpm_channel or (
                preset.rpm_signal[1] if preset.rpm_signal is not None else ""
            )
            self.apply_rpm_channel(rpm_channel)
            self.apply_outputs(preset.outputs)
            self.apply_time_range(params.get("time_range"))
        finally:
            self._applying_preset = False

        self._applied_control_snapshot = self._control_params_snapshot(method)
        self._scope_file_ids = self.file_ids()
        self._scope_file_paths = self.file_paths()
        self._scope_source_ids = self.source_ids()
        self._scope_source_paths = self.source_paths()
        self._scope_signals = self.selected_signals()
        self._scope_rpm_channel = self.rpm_channel()
        self._recompute_pipeline_status()

    def _on_recipe_method_changed(self, method: str) -> None:
        method = str(method)
        if not self._applying_preset and method != self._recipe_method:
            self._base_params = normalize_batch_params(self._base_params, method)
        self._recipe_method = method

    def _control_params_snapshot(self, method: str | None = None) -> dict:
        method_key = str(method or self.method())
        params = dict(self.params())
        axis = self._output_panel.axis_params()
        params.update(axis)
        params.update(self._output_panel.reference_params())
        if method_key == "fft":
            params["amp_y"] = (
                "dB" if axis.get("amplitude_mode") == "amplitude_db" else "Linear"
            )
        params.update(self._input_panel.rpm_params())
        params["filter"] = self._input_panel.filter_params()
        rng = self.time_range()
        if rng is not None:
            params["time_range"] = rng
        return normalize_batch_params(params, method_key)

    def _merged_params(self) -> dict:
        method = self.method()
        merged = normalize_batch_params(self._base_params, method)
        current = self._control_params_snapshot(method)
        baseline = self._applied_control_snapshot
        missing = object()
        for key in set(baseline) | set(current):
            if baseline.get(key, missing) == current.get(key, missing):
                continue
            if key in current:
                merged[key] = current[key]
            else:
                merged.pop(key, None)
        return normalize_batch_params(merged, method)

    # ------------------------------------------------------------------
    # W7: toolbar handlers (preset import / export / fill-from-current)
    # ------------------------------------------------------------------
    def _on_fill_from_current(self) -> None:
        if self._current_preset is None:
            return
        self.apply_preset(self._current_preset)

    def _on_import_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 preset", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            preset = load_preset_from_json(path)
        except UnsupportedPresetVersion as exc:
            self._toast(f"不支持的 preset 版本：{exc}", kind="warning")
            return
        except (ValueError, OSError) as exc:
            self._toast(f"preset 解析失败：{exc}", kind="error")
            return
        if preset is None:
            # load_preset_from_json returns None when the preset
            # references a method no longer in SUPPORTED_METHODS (e.g.
            # legacy order_track presets). Surface a warning and skip.
            self._toast(
                "导入的预设引用了已移除的方法（如 order_track），已跳过。",
                kind="warning",
            )
            return
        self.apply_preset(preset)
        self._toast(f"已加载 preset：{preset.name}", kind="success")

    def _on_export_preset(self) -> None:
        preset = self._build_preset_for_export()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 preset", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            save_preset_to_json(preset, path)
        except OSError as exc:
            self._toast(f"导出失败：{exc}", kind="error")
            return
        self._toast(f"已导出 preset 到：{path}", kind="success")

    def _on_resume_requested(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要恢复的运行清单", "", "JSON (*.json)"
        )
        if not path:
            return
        self._resume_manifest_path = str(path)
        self._retry_failed_manifest_path = None
        outputs = dataclasses.replace(
            self._output_panel.get_outputs(), resume_policy="manifest",
        )
        self._output_panel.apply_outputs(outputs)
        self._output_panel.set_operation_status(
            f"恢复清单：{Path(path).name}"
        )
        self._recompute_pipeline_status()

    def _on_retry_failed_requested(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择失败任务运行清单", "", "JSON (*.json)"
        )
        if not path:
            return
        self._retry_failed_manifest_path = str(path)
        self._resume_manifest_path = None
        outputs = dataclasses.replace(
            self._output_panel.get_outputs(), resume_policy="none",
        )
        self._output_panel.apply_outputs(outputs)
        self._output_panel.set_operation_status(
            f"重试失败：{Path(path).name}"
        )
        self._recompute_pipeline_status()

    def _build_preset_for_export(self) -> AnalysisPreset:
        """Build the recipe-only preset to persist.

        ``save_preset_to_json`` already whitelists the JSON payload; we
        also strip runtime / legacy fields at the source via
        ``dataclasses.replace`` so the export invariant matches spec §6.3
        wording (belt-and-suspenders).
        """
        preset = self.get_preset()
        return dataclasses.replace(
            preset,
            file_ids=(),
            file_paths=(),
            source_ids=(),
            source_paths=(),
            signal=None,
            rpm_signal=None,
            signal_pattern="",
            target_pairs=(),
        )

    def _toast(self, text: str, kind: str = "info") -> None:
        """Surface a toast to the parent (MainWindow has ``toast``).

        Always records ``_last_toast_*`` so headless tests can assert
        without needing a parent to mock. Production paths additionally
        forward to ``parent.toast`` so the user sees the message.
        """
        self._last_toast_text = text
        self._last_toast_kind = kind
        parent = self.parent()
        if parent is not None and hasattr(parent, "toast"):
            try:
                parent.toast(text, kind)
            except Exception:  # noqa: BLE001
                # Toast is purely informational — never let a parent
                # implementation bug break the toolbar action.
                pass

    # ------------------------------------------------------------------
    # Run-time gates
    # ------------------------------------------------------------------
    def is_runnable(self) -> bool:
        fl = self._input_panel._file_list
        for r in fl._rows.values():
            if r.state in (STATE_PATH_PENDING, STATE_PROBING):
                return False
        if fl.unavailable_reasons():
            return False
        if not fl.all_loaded_paths():
            return False
        if not self.selected_signals():
            return False
        if not self.method():
            return False
        if not self.output_dir():
            return False
        if self.preflight_issues():
            return False
        return True

    def preflight_issues(self) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        time_error = self._input_panel.time_range_error()
        if time_error:
            issues.append(ValidationIssue(
                "time_range", "invalid_text", time_error,
            ))
        for reason in self._input_panel._file_list.unavailable_reasons():
            issues.append(ValidationIssue(
                "source", "source_unavailable", str(reason),
            ))
        rows = self._input_panel._file_list.loaded_rows()
        selected = self.selected_signals()
        policy = self.target_policy()
        if policy != "exact_pairs" and selected:
            if policy == "common":
                common = self._input_panel._file_list.current_intersection()
                missing = tuple(signal for signal in selected if signal not in common)
            else:
                union = frozenset().union(*(row.channels for row in rows)) if rows else frozenset()
                missing = tuple(signal for signal in selected if signal not in union)
            if missing:
                issues.append(ValidationIssue(
                    "target_signals", "unavailable_target",
                    "目标信号在所选来源中不可用: " + ", ".join(missing),
                ))
        params = self._merged_params()
        effective_rpm_signal = (
            self._scope_rpm_signal
            if self.rpm_channel() == self._scope_rpm_channel
            else None
        )
        issues.extend(validate_recipe(
            self.method(),
            params,
            rpm_channel=self.rpm_channel(),
            rpm_signal=effective_rpm_signal,
        ))
        rpm_mode = str(params.get("rpm_mode", "channel")).strip().lower()
        if (
            self.method() == "order_time"
            and rpm_mode not in {"manual", "fixed", "手动"}
            and not self.rpm_channel()
            and effective_rpm_signal is None
            and not any(issue.field == "rpm_channel" for issue in issues)
        ):
            issues.append(ValidationIssue(
                "rpm_channel", "missing_rpm_channel",
                "阶次分析的通道转速模式需要 RPM 通道",
            ))
        issues.extend(validate_outputs(self._output_panel.get_outputs()))
        return tuple(issues)

    # ------------------------------------------------------------------
    # Preset assembly
    # ------------------------------------------------------------------
    def _preset_name(self) -> str:
        return "batch"

    # ------------------------------------------------------------------
    # W6: Run / cancel / lock-unlock
    # ------------------------------------------------------------------
    def _build_dry_run_preview(self) -> list[tuple[str, str, str]]:
        """Compute the dry-run task list from UI state ONLY.

        Spec §3.5 / W6 invariant: never call ``BatchRunner._expand_tasks``
        — that path runs ``_resolve_files`` which would ``loader(path)``
        full-load disk files on the UI thread and freeze the dialog. Per
        spec §3.2 disk files use the cached probe set on the file row.

        Policy filtering mirrors preflight: common only lists the true
        intersection; available-per-source lists each valid source/signal
        pair; exact-pair scope is preserved verbatim above.
        """
        preset = self.get_preset()
        method = preset.method or ""
        signals = self.selected_signals()
        rows: list[tuple[str, str, str]] = []

        if preset.target_pairs:
            file_rows = tuple(self._input_panel._file_list._rows.values())
            for source_id, sig in preset.target_pairs:
                fd = self._files.get(source_id)
                label = getattr(fd, "filename", None)
                if not label:
                    match = next(
                        (
                            row for row in file_rows
                            if row.source_id == source_id or row.fid == source_id
                        ),
                        None,
                    )
                    label = getattr(match, "label", None) or str(source_id)
                rows.append((str(label), str(sig), str(method)))
            return rows

        fl = self._input_panel._file_list
        policy = preset.target_policy or "common"
        common = fl.current_intersection() if policy == "common" else frozenset()
        for row in fl.loaded_rows():
            fd = self._files.get(row.source_id)
            label = getattr(fd, "filename", None) or row.label or str(row.source_id)
            for sig in signals:
                if policy == "common" and sig not in common:
                    continue
                if policy == "available_per_source" and sig not in row.channels:
                    continue
                rows.append((str(label), str(sig), str(method)))

        return rows

    def _outputs_per_task(self) -> int:
        outputs = self._output_panel.get_outputs()
        return int(bool(outputs.export_data)) + int(bool(outputs.export_image))

    def _make_runner(self) -> BatchRunner:
        """Build the GUI-free runner with the parent catalog snapshot."""
        store = getattr(self.parent(), "db_reference_store", None)
        if store is not None:
            snapshot = store.snapshot()
            return BatchRunner(
                self._files,
                source_registry=self._source_registry,
                source_context=self._source_context,
                db_reference_catalog=snapshot,
                prefer_channel_metadata=snapshot.prefer_channel_metadata,
            )
        return BatchRunner(
            self._files,
            source_registry=self._source_registry,
            source_context=self._source_context,
        )

    def _on_run_clicked(self) -> None:
        """Idle-mode 运行 handler — synchronously locks the dialog and starts
        the runner thread.

        Reentrance guarantee: ``self._running = True`` and disabling the
        Run button happens **before** ``thread.start()`` so a fast double-
        click cannot launch two threads (W6 invariant 2).
        """
        if self._running:
            return
        if not self.is_runnable():
            return

        # A previous run result must never survive into a new lifecycle. If
        # the worker fails before emitting its result, QThread.finished still
        # unlocks against None rather than presenting stale success/failure.
        self._last_result = None

        # Build the dry-run preview from UI state (no disk loads).
        tasks = self._build_dry_run_preview()
        self._task_list.apply_dry_run(tasks, self._outputs_per_task())

        # Synchronous lock: order matters.
        self._running = True
        self._btn_run.setEnabled(False)
        self.lock_editing()
        self._task_list.on_run_started()

        # Build runner. We pass the parent's loader contract (BatchRunner
        # default loader walks DataLoader.load_mf4) — main_window owns the
        # file map; here we only have the dict already supplied to __init__.
        #
        # dB-reference-defaults Task 10 Part A: this Sheet's Run button is
        # the ONLY live Batch Run path (``MainWindow.open_batch``'s own
        # BatchRunner call is dead code -- ``dlg.exec_()`` never returns
        # Accepted, see the mechanical-passthrough-entry-point-reachability
        # lesson). Mirror the same snapshot pass-through Task 9 already
        # wired there, following the existing
        # ``_weighting_options_from_parent`` precedent: read the catalog
        # store off ``self.parent()`` defensively (direct-construction
        # tests pass ``parent=None``, and any parent lacking the attribute
        # falls back to BatchRunner's no-kwargs factory-catalog default).
        runner = self._make_runner()
        preset = self.get_preset()
        output_dir = self.output_dir()

        thread = BatchRunnerThread(
            runner,
            preset,
            output_dir,
            parent=self,
            resume_manifest=self._resume_manifest_path,
            retry_failed_manifest=self._retry_failed_manifest_path,
        )
        self._runner_thread = thread
        # AutoConnection is correct in production (live event loop). Both
        # signals are object-tagged so qtbot can connect bare callables.
        thread.progress.connect(self._on_runner_progress)
        thread.finished_with_result.connect(self._on_runner_finished_with_result)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _on_cancel_clicked(self) -> None:
        """Running-mode 中断 handler — sets the cancel token and disables
        the abort button so it cannot be clicked twice."""
        if not self._running or self._runner_thread is None:
            return
        self._btn_abort.setEnabled(False)
        self._btn_abort.setText("正在停止…")
        self._runner_thread.request_cancel()

    def _on_runner_progress(self, event) -> None:
        # Forward to the task list (updates icons + progress bar + ETA).
        self._task_list.on_event(event)

    def _on_runner_finished_with_result(self, result) -> None:
        """Stash the BatchRunResult; the actual unlock happens in
        ``_on_thread_finished`` (bound to ``QThread.finished``) per spec
        §6.2 unlock contract."""
        self._last_result = result
        if result is None:
            return
        status = str(getattr(result, "status", "") or "未知")
        facts = [f"运行结果：{status}"]
        run_id = getattr(result, "run_id", None)
        manifest_path = getattr(result, "manifest_path", None)
        if run_id:
            facts.append(f"run_id {run_id}")
        if manifest_path:
            facts.append(f"清单 {Path(manifest_path).name}")
        self._output_panel.set_operation_status(" · ".join(facts))

    def _on_thread_finished(self) -> None:
        """Bound to ``QThread.finished`` — guaranteed to fire by Qt even if
        ``runner.run()`` raised before ``finished_with_result`` would have
        emitted (W6 invariant 1).
        """
        result = self._last_result
        self._task_list.on_run_finished(result)
        self.unlock_editing()
        self._show_result_toast(result)

        # Clean up thread reference.
        thread = self._runner_thread
        self._runner_thread = None
        if thread is not None:
            try:
                thread.deleteLater()
            except Exception:  # noqa: BLE001
                pass

        # If the user requested close mid-run, complete it now.
        if self._close_pending:
            self._close_pending = False
            self.close()

    def _show_result_toast(self, result) -> None:
        """Inline status toast on run completion.

        Only fired when the sheet is currently shown. Headless unit tests
        never call ``show()`` so they bypass the toast entirely (avoids a
        Windows offscreen access violation when the modal opens nested
        under ``qtbot.waitUntil``). A richer toast widget belongs to W7.
        """
        if result is None:
            return
        if not self.isVisible():
            return
        status = getattr(result, "status", "") or ""
        if not status:
            return
        if status == "done":
            QMessageBox.information(self, "批处理完成", "全部任务已完成。")
        elif status == "partial":
            blocked = getattr(result, "blocked", []) or []
            QMessageBox.warning(
                self, "批处理部分完成",
                f"完成，共 {len(blocked)} 个失败任务。",
            )
        elif status == "cancelled":
            QMessageBox.information(self, "批处理已取消", "运行已被用户取消。")
        elif status == "blocked":
            blocked = getattr(result, "blocked", []) or []
            reason = "; ".join(blocked) if blocked else "未知原因"
            QMessageBox.warning(self, "批处理无法运行", f"原因：{reason}")

    def lock_editing(self) -> None:
        """Disable detail panels + swap footer to running mode."""
        self._input_panel.setEnabled(False)
        self._analysis_panel.setEnabled(False)
        self._output_panel.setEnabled(False)
        self._btn_fill_from_current.setEnabled(False)
        self._btn_import_preset.setEnabled(False)
        self._btn_export_preset.setEnabled(False)
        self._btn_cancel.setVisible(False)
        self._btn_run.setVisible(False)
        self._btn_abort.setEnabled(True)
        self._btn_abort.setText("中断")
        self._btn_abort.setVisible(True)

    def unlock_editing(self) -> None:
        """Re-enable detail panels + swap footer back to idle mode.

        Always called from ``_on_thread_finished`` (QThread.finished) so
        the dialog can never get stuck locked.
        """
        self._running = False
        self._input_panel.setEnabled(True)
        self._analysis_panel.setEnabled(True)
        self._output_panel.setEnabled(True)
        self._btn_fill_from_current.setEnabled(self._current_preset is not None)
        self._btn_import_preset.setEnabled(True)
        self._btn_export_preset.setEnabled(True)
        self._btn_abort.setVisible(False)
        self._btn_cancel.setVisible(True)
        self._btn_run.setVisible(True)
        # Re-evaluate Run-button enabled state against current config.
        self._btn_run.setEnabled(self.is_runnable())

    def _open_artifact_location(self, artifact_path: str) -> None:
        """Open an artifact's containing folder after explicit activation."""
        path = Path(str(artifact_path or "")).expanduser()
        if not str(artifact_path or "").strip():
            return
        target = path if path.is_dir() else path.parent
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        if not opened:
            self._toast(f"无法打开输出位置：{target}", kind="warning")

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        """If a run is in progress, prompt for confirmation and route to
        the cancel path; the actual close happens once
        ``_on_thread_finished`` clears ``_running`` (W6 invariant 4).
        """
        if self._running:
            choice = QMessageBox.question(
                self, "确认关闭",
                "批量任务正在运行，关闭将取消剩余任务。要继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice == QMessageBox.Yes:
                self._close_pending = True
                if self._runner_thread is not None:
                    self._runner_thread.request_cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def get_preset(self) -> AnalysisPreset:
        params = self._merged_params()
        # Preserve the long-standing in-memory AnalysisPreset API while the
        # canonical JSON/normalization layer uses one sequence shape (list).
        if isinstance(params.get("time_range"), list):
            params["time_range"] = tuple(params["time_range"])
        outputs = self._output_panel.get_outputs()
        current_scope = (
            self.source_ids(),
            self.source_paths(),
            self.selected_signals(),
        )
        applied_scope = (
            self._scope_source_ids,
            self._scope_source_paths,
            self._scope_signals,
        )
        scope_unchanged = current_scope == applied_scope

        single_scope = (
            len(self.source_ids()) == 1
            and len(self.selected_signals()) == 1
        )
        if self._scope_source == "current_single" and single_scope:
            exact_signal = (self.source_ids()[0], self.selected_signals()[0])
            rpm_signal = self._scope_rpm_signal
            current_rpm = self.rpm_channel()
            if current_rpm != self._scope_rpm_channel:
                rpm_signal = (
                    (exact_signal[0], current_rpm) if current_rpm else None
                )
            current = AnalysisPreset.from_current_single(
                name=self._base_name,
                method=self.method(),
                signal=exact_signal,
                rpm_signal=rpm_signal,
                rpm_channel=current_rpm,
                params=params,
                outputs=outputs,
            )
            return dataclasses.replace(
                current,
                source_ids=self.source_ids(),
                source_paths=self.source_paths(),
                file_ids=self.file_ids(),
                file_paths=self.file_paths(),
            )

        exact_pairs = (
            self._scope_target_pairs
            if self._scope_target_pairs and scope_unchanged else ()
        )
        policy = "exact_pairs" if exact_pairs else self._input_panel.target_policy()

        base = AnalysisPreset.free_config(
            name=self._base_name or self._preset_name(),
            method=self.method(),
            target_signals=self.selected_signals(),
            rpm_channel=self.rpm_channel(),
            params=params,
            outputs=outputs,
            target_policy=policy,
        )
        return dataclasses.replace(
            base,
            source_ids=self.source_ids(),
            source_paths=self.source_paths(),
            file_ids=self.file_ids(),
            file_paths=self.file_paths(),
            target_pairs=exact_pairs,
        )
