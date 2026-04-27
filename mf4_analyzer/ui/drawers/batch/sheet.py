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

from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from ....batch import AnalysisPreset, BatchOutput, BatchRunner
from ....batch_preset_io import (
    UnsupportedPresetVersion, load_preset_from_json, save_preset_to_json,
)
from .analysis_panel import AnalysisPanel
from .input_panel import InputPanel, STATE_PATH_PENDING, STATE_PROBING
from .output_panel import OutputPanel
from .pipeline_strip import PipelineStrip
from .runner_thread import BatchRunnerThread
from .task_list import TaskListWidget


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

        # Run-state bookkeeping (W6).
        self._running: bool = False
        self._runner_thread: BatchRunnerThread | None = None
        self._last_result = None
        self._close_pending: bool = False

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

        self._input_panel = InputPanel(self, files=self._files)
        self._analysis_panel = AnalysisPanel(self)
        self._output_panel = OutputPanel(self)
        detail_lay.addWidget(self._input_panel, 1)
        detail_lay.addWidget(self._analysis_panel, 1)
        detail_lay.addWidget(self._output_panel, 1)
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
        self._analysis_panel.paramsChanged.connect(self._recompute_pipeline_status)
        self._output_panel.changed.connect(self._recompute_pipeline_status)

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

        # Gate the Run button on is_runnable() so an empty/partial
        # config cannot reach BatchRunner's legacy fallback (ultrareview
        # bug_018). The __init__'s seed call to this method correctly
        # leaves the run button disabled at first show. While a run is in
        # progress, the run button is hidden behind the 中断 swap, so we
        # only adjust enabled-state in idle mode.
        if not self._running:
            self._btn_run.setEnabled(self.is_runnable())

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

        if preset.source == "current_single":
            # Narrow the file list to the captured fid first so the picker
            # universe is rebuilt against only that file. Empty file_paths
            # — current_single never carries a disk-only path.
            if preset.signal is not None:
                signal_fid, signal_name = preset.signal
                self.apply_files(file_ids=(signal_fid,), file_paths=())
                self.apply_signals((signal_name,))
            self.apply_method(preset.method)
            self.apply_params(dict(preset.params))
            # Restore the InputPanel-owned rpm_factor field (Step 5.4).
            if "rpm_factor" in preset.params:
                self._input_panel.apply_rpm_factor(preset.params["rpm_factor"])
            self.apply_rpm_channel(preset.rpm_channel or "")
        else:
            # free_config: KEEP current files (the file selection is local
            # to this dialog session per spec §6.4). Apply the recipe.
            self.apply_signals(tuple(preset.target_signals))
            self.apply_method(preset.method)
            self.apply_params(dict(preset.params))
            # Restore the InputPanel-owned rpm_factor field (Step 5.4).
            if "rpm_factor" in preset.params:
                self._input_panel.apply_rpm_factor(preset.params["rpm_factor"])
            self.apply_rpm_channel(preset.rpm_channel or "")

        # Outputs apply in both paths.
        self.apply_outputs(preset.outputs)

        # time_range round-trip — both sources carry it through params.
        if "time_range" in preset.params:
            self.apply_time_range(preset.params["time_range"])

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
            signal=None,
            rpm_signal=None,
            signal_pattern="",
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

    # ------------------------------------------------------------------
    # W6: Run / cancel / lock-unlock
    # ------------------------------------------------------------------
    def _build_dry_run_preview(self) -> list[tuple[str, str, str]]:
        """Compute the dry-run task list from UI state ONLY.

        Spec §3.5 / W6 invariant: never call ``BatchRunner._expand_tasks``
        — that path runs ``_resolve_files`` which would ``loader(path)``
        full-load disk files on the UI thread and freeze the dialog. Per
        spec §3.2 disk files use the cached probe set on the file row.

        We append a row even when a signal is missing from a file. The
        runner will emit ``task_failed`` with ``missing signal: …`` at run
        time — UI does not pre-judge.
        """
        method = self.method() or ""
        signals = self.selected_signals()
        rows: list[tuple[str, str, str]] = []

        # Loaded files (file_ids → FileData via self._files)
        for fid in self._input_panel.file_ids():
            fd = self._files.get(fid)
            label = getattr(fd, "filename", None) or str(fid)
            for sig in signals:
                rows.append((str(label), str(sig), str(method)))

        # Disk-only paths (cached probe set lives on the FileListWidget row).
        fl = self._input_panel._file_list
        for path in self._input_panel.file_paths():
            row = fl._rows.get(path)
            label = getattr(row, "label", None) or path
            # Strip any state badge ("  …" / "  ⚠") that _render_row appends.
            for trailing in ("  …", "  ⚠"):
                if label.endswith(trailing):
                    label = label[: -len(trailing)]
            for sig in signals:
                rows.append((str(label), str(sig), str(method)))

        return rows

    def _outputs_per_task(self) -> int:
        return int(bool(self.export_data())) + int(bool(self.export_image()))

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
        runner = BatchRunner(self._files)
        preset = self.get_preset()
        output_dir = self.output_dir()

        thread = BatchRunnerThread(runner, preset, output_dir, parent=self)
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
        self._btn_abort.setVisible(False)
        self._btn_cancel.setVisible(True)
        self._btn_run.setVisible(True)
        # Re-evaluate Run-button enabled state against current config.
        self._btn_run.setEnabled(self.is_runnable())

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
        # Merge the user-typed time_range field into params so
        # BatchRunner._apply_time_range sees it (ultrareview bug_009).
        # Empty field → no key, so BatchRunner runs the full signal.
        params = dict(self.params())
        # InputPanel-owned rpm_factor (Wave 2 Task 5) — DynamicParamForm no
        # longer carries it, so we merge from the InputPanel here.
        params.update(self._input_panel.rpm_params())
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
