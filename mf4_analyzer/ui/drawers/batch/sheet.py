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
import tempfile

from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ....batch import AnalysisPreset, BatchOutput, BatchRunner
from ....batch_preset_io import (
    UnsupportedPresetVersion, load_preset_from_json, save_preset_to_json,
)
from ....batch_recipe import TIME_RENDER_DEFAULTS, normalize_batch_params
from ....batch_validation import (
    ValidationIssue, validate_outputs, validate_recipe,
)
from ....io.source_adapters import DEFAULT_SOURCE_ADAPTER_REGISTRY
from ...batch_settings import BatchPanelPrefs, BatchPanelPrefsStore
from ._geometry import fit_dialog_to_available_screen
from .analysis_panel import AnalysisPanel
from .input_panel import InputPanel, STATE_PATH_PENDING, STATE_PROBING
from .output_panel import OutputPanel
from .pipeline_strip import PipelineStrip
from .preview_dialog import BatchPreviewDialog
from .runner_thread import BatchPreviewThread, BatchRunnerThread
from .task_list import TaskListWidget


_METHOD_LABELS: dict[str, str] = {
    "time": "时域",
    "fft": "FFT",
    "fft_time": "FFT vs Time",
    "order_time": "阶次",
}

_DB_REFERENCE_SECTION_BY_METHOD: dict[str, str] = {
    "fft": "fft",
    "fft_time": "fft_time",
    "order_time": "order",
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
    "image_background",
    "image_line_width",
    "conflict_policy",
    "resume_policy",
})

_PIPELINE_RECOMPUTE_DEBOUNCE_MS = 150


def _analysis_issue_summary(issue: ValidationIssue, method: str) -> str:
    """Return a compact, user-facing stage summary for recipe issues."""

    label = _METHOD_LABELS.get(method, method or "分析")
    detail = {
        "rpm_channel": "RPM 通道未配置",
        "x_channel": "X 通道未配置",
        "fs": "采样率无效",
        "nfft": "NFFT 参数无效",
        "x_range": "X 范围无效",
        "y_range": "Y 范围无效",
        "z_range": "色阶范围无效",
        "slice": "切片位置无效",
        "slice_positions": "切片位置无效",
    }.get(issue.field, "参数待完善")
    return f"{label} · {detail}"


def _output_issue_summary(issue: ValidationIssue) -> str:
    """Keep backend output field names out of the compact pipeline strip."""

    return {
        "outputs": "未选择导出内容",
        "data_format": "数据导出设置待完善",
        "image_format": "图片导出设置待完善",
        "image_size": "图片尺寸设置待完善",
        "image_width": "图片尺寸设置待完善",
        "image_height": "图片尺寸设置待完善",
        "image_pixels": "图片尺寸设置待完善",
    }.get(issue.field, "导出设置待完善")


def _blocked_issue_reason(issue: ValidationIssue) -> str:
    """Translate validation details for the single-line footer status."""

    if issue.field in _OUTPUT_ISSUE_FIELDS:
        return (
            "请至少选择数据文件或图片"
            if issue.field == "outputs" else "请检查导出设置"
        )
    return {
        "rpm_channel": "请选择 RPM 通道",
        "time_range": "请检查时间范围",
        "x_channel": "请选择 X 通道",
        "fs": "请检查采样率",
        "nfft": "请检查 NFFT 参数",
        "slice": "请检查切片位置",
        "slice_positions": "请检查切片位置",
    }.get(issue.field, "请检查分析参数")

class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None, prefs_store=None):
        """``prefs_store`` is the injection seam for
        :class:`~mf4_analyzer.ui.batch_settings.BatchPanelPrefsStore`; tests
        MUST pass one backed by an isolated ``QSettings(IniFormat)`` so the
        dialog's open/close cycle cannot read or write the real user config.
        """
        super().__init__(parent)
        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.setInterval(_PIPELINE_RECOMPUTE_DEBOUNCE_MS)
        self._recompute_timer.timeout.connect(self._recompute_pipeline_status)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self._files = files or {}
        self._current_preset = current_preset
        self._prefs_store = (
            prefs_store if prefs_store is not None else BatchPanelPrefsStore()
        )
        self._base_name = "batch"
        self._base_params: dict = {}
        self._recipe_method = "fft"
        self._applied_control_snapshot: dict = {}
        self._applying_preset = False
        self._applying_analysis_preset = False
        self._analysis_preset_output_snapshot: dict | None = None
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
        self._x_channel_common: tuple[str, ...] = ()
        self._x_channel_partial: dict[str, str] = {}
        self._source_registry = DEFAULT_SOURCE_ADAPTER_REGISTRY
        source_context = getattr(parent, "batch_source_context", {}) if parent else {}
        self._source_context = (
            dict(source_context) if isinstance(source_context, dict) else {}
        )

        # Run-state bookkeeping (W6).
        self._running: bool = False
        self._runner_thread: BatchRunnerThread | None = None
        self._last_result = None
        # Preview state is deliberately separate from run/preset state.
        self._preview_thread: BatchPreviewThread | None = None
        self._preview_result = None
        self._preview_dialog: BatchPreviewDialog | None = None
        self._preview_temp: tempfile.TemporaryDirectory | None = None
        self._preview_close_pending: bool = False
        self._close_pending: bool = False

        # W7 toast bookkeeping — populated by ``_toast`` so headless tests
        # can assert deterministically without mocking the parent's toast
        # API. Production paths additionally forward to ``parent.toast`` if
        # the host exposes one (MainWindow does).
        self._last_toast_text: str = ""
        self._last_toast_kind: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar — W7 wires three buttons:
        #   • 从当前单次填入: enabled iff a current_preset was passed in,
        #     fills the dialog from that preset (spec §6.4 current_single).
        #   • 导入方案…  : open JSON, load, apply (warns on
        #     UnsupportedPresetVersion / corrupt JSON via toast).
        #   • 导出方案… : strip runtime fields via dataclasses.replace
        #     and save to JSON (spec §6.3).
        self._toolbar_host = QWidget(self)
        self._toolbar_host.setObjectName("BatchCompactToolbar")
        # 36px, down from 50: the three preset buttons are secondary chrome,
        # so a toolbar-scoped QSS rule drops them to min-height 24 (+4 padding
        # +2 border = 30) and the 3px margins land the row exactly on 36.
        # The strip keeps its own row below — the two rows carry different
        # things (方案 I/O vs. pipeline state) and stay separate.
        self._toolbar_host.setFixedHeight(36)
        bar = QHBoxLayout(self._toolbar_host)
        bar.setContentsMargins(14, 3, 14, 3)
        bar.setSpacing(7)
        self._toolbar_title = QLabel("批处理分析", self._toolbar_host)
        self._toolbar_title.setObjectName("BatchToolbarTitle")
        bar.addWidget(self._toolbar_title)
        bar.addStretch(1)

        self._btn_fill_from_current = QPushButton("从当前单次同步")
        self._btn_fill_from_current.setEnabled(self._current_preset is not None)
        self._btn_fill_from_current.clicked.connect(self._on_fill_from_current)
        bar.addWidget(self._btn_fill_from_current)

        self._btn_import_preset = QPushButton("导入方案…")
        self._btn_import_preset.clicked.connect(self._on_import_preset)
        bar.addWidget(self._btn_import_preset)

        self._btn_export_preset = QPushButton("导出方案…")
        self._btn_export_preset.clicked.connect(self._on_export_preset)
        bar.addWidget(self._btn_export_preset)

        root.addWidget(self._toolbar_host)

        # Pipeline strip — its own row, slimmed from 62px to 40px.
        self.strip = PipelineStrip(self)
        root.addWidget(self.strip)

        # Detail row: input | analysis | output
        detail = QWidget(self)
        detail.setObjectName("BatchCompactWorkspace")
        detail_lay = QHBoxLayout(detail)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(0)
        self._detail_host = detail
        self._detail_lay = detail_lay

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

        def scrolling_pane(
            panel: QWidget, name: str, background: str, *, last: bool = False,
        ) -> QScrollArea:
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            scroll = QScrollArea(detail)
            scroll.setObjectName(name)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setMinimumSize(0, 0)
            scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
            right_border = "0" if last else "1px solid #dbe4ef"
            scroll.setStyleSheet(
                f"QScrollArea#{name} {{ border:0; border-right:{right_border};"
                f" background:{background}; }}"
                f"QScrollArea#{name} QWidget#qt_scrollarea_viewport {{"
                f" background:{background}; }}"
                f"QScrollArea#{name} > QWidget > QWidget {{"
                f" background:{background}; }}"
            )
            scroll.setWidget(panel)
            return scroll

        self._input_scroll = scrolling_pane(
            self._input_panel, "BatchInputScroll", "#ffffff",
        )
        self._analysis_scroll = scrolling_pane(
            self._analysis_panel, "BatchAnalysisScroll", "#fcfefd",
        )
        self._output_scroll = scrolling_pane(
            self._output_panel, "BatchOutputScroll", "#fffdfa", last=True,
        )
        detail_lay.addWidget(self._input_scroll, 29)
        detail_lay.addWidget(self._analysis_scroll, 39)
        detail_lay.addWidget(self._output_scroll, 32)
        root.addWidget(detail, 1)

        # Keep the task model for runner events and testable artifact facts,
        # but remove the old lower task-list surface from the product layout.
        # The compact footer below is its only visible projection.
        self._task_list = TaskListWidget(self)
        self._task_list.hide()

        # Fixed status footer: one compact status/progress projection plus
        # the required close/run/cancel actions.  The run gate remains the
        # same: an incomplete sheet cannot reach BatchRunner's legacy file
        # fallback and accidentally analyse every loaded file/channel.
        self._footer_host = QWidget(self)
        self._footer_host.setObjectName("BatchCompactFooter")
        self._footer_host.setFixedHeight(50)
        self._footer_lay = QHBoxLayout(self._footer_host)
        # 5px, not 7: the footer action buttons carry QSS min-height 30 plus
        # 4px padding and a 1px border on each side, so their real minimum
        # height is 40. 5 + 40 + 5 lands exactly on the 50px host — at 7 the
        # layout's minimum (54) overflowed the host and Qt silently pinned
        # the buttons to the top, leaving a lopsided 7px/3px gap.
        self._footer_lay.setContentsMargins(16, 5, 14, 5)
        self._footer_lay.setSpacing(8)
        self._footer_state_dot = QLabel(self._footer_host)
        self._footer_state_dot.setObjectName("BatchFooterStateDot")
        self._footer_state_dot.setFixedSize(8, 8)
        self._footer_lay.addWidget(self._footer_state_dot)
        self._footer_status = QLabel("待配置", self._footer_host)
        self._footer_status.setObjectName("BatchFooterStatus")
        self._footer_lay.addWidget(self._footer_status)
        self._footer_task_summary = QLabel("等待运行", self._footer_host)
        self._footer_task_summary.setObjectName("BatchFooterTaskSummary")
        self._footer_lay.addWidget(self._footer_task_summary, 1)
        self._footer_progress = QProgressBar(self._footer_host)
        self._footer_progress.setObjectName("BatchFooterProgress")
        self._footer_progress.setRange(0, 1)
        self._footer_progress.setValue(0)
        self._footer_progress.setTextVisible(False)
        self._footer_progress.setMinimumWidth(130)
        self._footer_progress.setMaximumWidth(180)
        self._footer_lay.addWidget(self._footer_progress)

        # Idle-mode buttons
        self._btn_cancel = QPushButton("关闭", self._footer_host)
        self._btn_cancel.clicked.connect(self.reject)
        self._footer_lay.addWidget(self._btn_cancel)

        self._btn_preview = QPushButton("预览", self._footer_host)
        self._btn_preview.setToolTip("生成正式渲染链路的代表最终图")
        self._btn_preview.setProperty("role", "accent")
        self._btn_preview.clicked.connect(self._on_preview_clicked)
        self._footer_lay.addWidget(self._btn_preview)

        self._btn_run = QPushButton("运行", self._footer_host)
        self._btn_run.setDefault(True)
        self._btn_run.setProperty("role", "primary")
        self._btn_run.clicked.connect(self._on_run_clicked)
        self._footer_lay.addWidget(self._btn_run)

        # Running-mode button (hidden until a run starts)
        self._btn_abort = QPushButton("中断", self._footer_host)
        self._btn_abort.setProperty("role", "destructive")
        self._btn_abort.clicked.connect(self._on_cancel_clicked)
        self._btn_abort.setVisible(False)
        self._footer_lay.addWidget(self._btn_abort)

        root.addWidget(self._footer_host)

        # Wire status recomputation. Each signal is independent — we wire all
        # of them so that any sub-control mutation flows into a single
        # recompute pass.
        self._input_panel.changed.connect(self._on_input_scope_changed)
        self._input_panel._file_list.filesChanged.connect(
            self._schedule_pipeline_recompute
        )
        self._input_panel._file_list.intersectionChanged.connect(
            lambda _intersection: self._schedule_pipeline_recompute()
        )
        self._input_panel._signal_picker.selectionChanged.connect(
            lambda _sel: self._schedule_pipeline_recompute()
        )
        # Drive RPM-row visibility from the method (init-sync below).
        self._analysis_panel.methodChanged.connect(self._input_panel.set_method)
        self._analysis_panel.methodChanged.connect(
            self._output_panel.apply_method_defaults
        )
        self._analysis_panel.methodChanged.connect(self._on_recipe_method_changed)
        self._analysis_panel.methodChanged.connect(
            lambda _m: self._schedule_pipeline_recompute()
        )
        self._analysis_panel.paramsChanged.connect(self._sync_x_axis_context)
        self._analysis_panel.paramsChanged.connect(self._schedule_pipeline_recompute)
        self._analysis_panel.presetApplied.connect(
            self._on_builtin_analysis_preset
        )
        self._output_panel.changed.connect(self._on_output_controls_changed)
        self._output_panel.restore_defaults_requested.connect(
            self._on_restore_output_defaults
        )
        self._output_panel.db_reference_control.manage_requested.connect(
            self._open_shared_db_reference_manager
        )
        self._task_list.artifactOpenRequested.connect(
            self._open_artifact_location
        )
        self._input_panel.channelUniverseChanged.connect(
            self._on_channel_universe_changed
        )

        # Init-sync (per conditional-visibility-init-sync lesson): seed the
        # RPM row before show() so it doesn't flash visible.
        self._input_panel.set_method(self._analysis_panel.current_method())
        self._input_panel._refresh_signal_universe()
        self._sync_x_axis_context()

        # Remembered display preferences land on top of the hard-coded
        # defaults, and strictly BEFORE any ``apply_preset``: nothing applies
        # a preset during __init__, so a preset the user actively pulls in
        # later (从当前单次同步 / 导入方案…) always wins over this memory.
        self._restore_panel_prefs()

        # Init-sync — seed badges with the current default state.
        self._recompute_pipeline_status()
        self._compact_mode: bool | None = None
        self._apply_compact_mode(self.width() <= 1180)

        # Initial size: intersect the 1080x760 target with the available
        # screen so a small laptop display never clips the footer's run/
        # preview/close actions off-screen (plan §3 改动 A). Deliberately
        # last in __init__, after every sub-panel exists, since it only
        # changes the dialog's own geometry.
        self._fit_to_available_screen(parent, 1080, 760)

    def _fit_to_available_screen(self, parent, target_w: int, target_h: int) -> None:
        """Thin forwarder to the shared clamp so ``BatchSheet`` and
        ``BatchPreviewDialog`` (``preview_dialog.py``) share one
        implementation instead of drifting apart."""
        fit_dialog_to_available_screen(
            self, parent, target_w, target_h, min_w=640, min_h=480,
        )

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # Belt-and-suspenders: Qt can still reposition/resize a modal after
        # the constructor's clamp (e.g. centering it over ``parent``), which
        # on a small screen can push the bottom back off-screen even though
        # __init__ sized it correctly. Clamp the actual frame geometry back
        # into the available screen once more, now that a real screen is
        # guaranteed to be associated with the window.
        screen = None
        try:
            screen = QApplication.screenAt(self.geometry().center())
        except Exception:
            screen = None
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        x = max(avail.left(), min(frame.left(), avail.right() - frame.width()))
        y = max(avail.top(), min(frame.top(), avail.bottom() - frame.height()))
        if x != frame.left() or y != frame.top():
            self.move(x, y)

    def _apply_compact_mode(self, compact: bool) -> None:
        compact = bool(compact)
        if getattr(self, "_compact_mode", None) is compact:
            return
        self._compact_mode = compact
        self._input_panel.set_compact_mode(compact)
        self._analysis_panel.set_compact_mode(compact)
        self._output_panel.set_compact_mode(compact)
        side = 12 if compact else 18
        self._footer_lay.setContentsMargins(side, 5, 14, 5)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if hasattr(self, "_analysis_panel"):
            self._apply_compact_mode(event.size().width() <= 1180)

    def _present_footer(
        self, state: str, *, done: int = 0, total: int = 1,
        task_count: int | None = None, reason: str = "",
    ) -> None:
        """Project one runner/configuration state into the fixed footer."""
        state = str(state or "blocked")
        maximum = max(1, int(total or 1))
        value = min(maximum, max(0, int(done or 0)))
        count = maximum if task_count is None else max(0, int(task_count))
        labels = {
            "ready": "配置就绪",
            "blocked": "待配置",
            "running": "运行中",
            "cancelling": "正在停止…",
            "done": "已完成",
            "partial": "部分完成",
            "cancelled": "已取消",
        }
        if state == "ready":
            task_text = "点击运行后生成任务"
            value, maximum = 0, 1
        elif state == "blocked":
            task_text = reason or "请选择文件、信号和输出目录"
            value, maximum = 0, 1
        else:
            task_text = f"{value}/{count} 任务"
        self._footer_status.setText(labels.get(state, state))
        self._footer_task_summary.setText(task_text)
        self._footer_progress.setRange(0, maximum)
        self._footer_progress.setValue(value)
        self._footer_state_dot.setProperty("state", state)
        self._footer_state_dot.style().unpolish(self._footer_state_dot)
        self._footer_state_dot.style().polish(self._footer_state_dot)

    # ------------------------------------------------------------------
    # Pipeline status recompute
    # ------------------------------------------------------------------
    def _on_input_scope_changed(self) -> None:
        self._refresh_x_channel_candidates()
        self._schedule_pipeline_recompute()

    def _schedule_pipeline_recompute(self) -> None:
        self._recompute_timer.start()

    def _recompute_pipeline_status(self) -> None:
        self._recompute_timer.stop()
        # INPUT
        fl = self._input_panel._file_list
        loaded_paths = fl.all_loaded_paths()
        any_pending = fl.has_pending_probe()
        unavailable_reasons = fl.unavailable_reasons()
        any_failed = fl.has_probe_failed() or bool(unavailable_reasons)
        selected = self._input_panel.selected_signals()
        self._analysis_panel.set_grouping_counts(
            source_count=len(fl.loaded_rows()), signal_count=len(selected),
        )
        time_error = self._time_range_error()
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
                f"{len(loaded_paths)} 文件 · {len(selected)} 信号"
                if (loaded_paths or selected) else "解析失败"
            )
        elif not loaded_paths or not selected:
            input_status = "warn"
            input_summary = (
                f"{len(loaded_paths)} 文件 · {len(selected)} 信号"
                if (loaded_paths or selected) else "未配置"
            )
        else:
            input_status = "ok"
            input_summary = f"{len(loaded_paths)} 文件 · {len(selected)} 信号"
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
                1, "warn", _analysis_issue_summary(issue, method),
            )
        elif not method:
            self.strip.set_stage(1, "warn", "未选择方法")
        else:
            label = _METHOD_LABELS.get(method, method)
            window = params.get("window", "")
            if method == "time":
                grouping = {
                    "none": "每项单独",
                    "source": "按数据源分组",
                    "channel": "按信号分组",
                }.get(str(params.get("render_group_by", "none")), "每项单独")
                summary = f"{label} · {grouping}"
            else:
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
                2, "warn", _output_issue_summary(issue),
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
            output_summary = " + ".join(parts)
            if loaded_paths and selected and method:
                try:
                    preview = self._make_runner().preview_outputs(
                        self.get_preset(), directory,
                    )
                except (TypeError, ValueError, OSError) as exc:
                    self._output_panel.set_output_preview(error=str(exc))
                else:
                    self._output_panel.set_output_preview(preview)
                    output_summary += f" · {preview.artifact_count} 个文件"
            else:
                self._output_panel.set_output_preview(None)
            self.strip.set_stage(2, "ok", output_summary)

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
            runnable = self.is_runnable(issues=preflight_issues)
            self._btn_run.setEnabled(runnable)
            self._btn_preview.setEnabled(runnable)
            blocked_reason = "请选择文件、信号和输出目录"
            if preflight_issues:
                blocked_reason = _blocked_issue_reason(preflight_issues[0])
            self._present_footer(
                "ready" if runnable else "blocked", reason=blocked_reason,
            )

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

    def _x_range_crops_time(self) -> bool:
        """Whether the X range doubles as the time-domain data window.

        ``time_range`` masks the TIME array in ``batch_preprocess``. That is
        only what the X range means while X *is* time; once the user puts a
        channel on X (rack travel in mm), the same numbers would crop the run
        by seconds using millimetres and silently empty the task. In that mode
        the X range stays a pure display window (``x_min``/``x_max``).
        """
        return str(self.params().get("x_source", "time")) != "channel"

    def time_range(self):
        method = self.method()
        if method == "fft":
            return self._analysis_panel.source_time_range()
        if method == "time" and self._x_range_crops_time():
            axis = self._output_panel.axis_params()
            if axis.get("x_auto", True):
                return None
            return (axis["x_min"], axis["x_max"])
        return None

    def _time_range_error(self) -> str:
        if self.method() == "fft":
            return self._analysis_panel.source_time_range_error()
        if self.method() == "time":
            axis = self._output_panel.axis_params()
            if axis.get("x_auto", True):
                return ""
            if float(axis["x_min"]) >= float(axis["x_max"]):
                return "坐标 X：最小值必须小于最大值"
        return ""

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
        method = self.method()
        if method == "fft":
            self._analysis_panel.apply_source_time_range(rng)
        elif method == "time":
            if rng is None:
                self._output_panel.apply_axis_params({"x_auto": True})
            else:
                self._output_panel.apply_axis_params({
                    "x_auto": False, "x_min": rng[0], "x_max": rng[1],
                })

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
        self._applying_analysis_preset = True
        try:
            self._output_panel.apply_axis_params(display_patch)
        finally:
            self._applying_analysis_preset = False
        self._analysis_preset_output_snapshot = self._output_controls_snapshot()
        self._schedule_pipeline_recompute()

    def _output_controls_snapshot(self) -> dict:
        return {
            "axes": self._output_panel.axis_params(),
            "reference": self._output_panel.reference_params(),
            "render_style": self._output_panel.render_style_params(),
            "outputs": dataclasses.asdict(self._output_panel.get_outputs()),
        }

    # ------------------------------------------------------------------
    # Remembered display preferences (QSettings). Plan:
    # docs/analyzer/plans/2026-08-02-batch-settings-persistence-plan.md
    # ------------------------------------------------------------------
    def _restore_panel_prefs(self) -> None:
        """Apply the remembered display preferences to the output panel.

        Only what the store persists is touched — directory, render style and
        the export block. Files, target signals, RPM channel/factor, axes and
        analysis parameters are never remembered, so a panel opened against a
        new data source starts clean (plan 2.1).

        ``apply_directory`` writes the line edit, whose ``textChanged``
        re-emits ``OutputPanel.changed``; the ``_applying_analysis_preset``
        flag keeps that from being read as a user edit and clearing a freshly
        applied analysis card.
        """
        prefs = self._prefs_store.load()
        self._applying_analysis_preset = True
        try:
            # An empty remembered directory means "never chosen" — leave the
            # panel's own default in place rather than blanking the field.
            if prefs.directory:
                self._output_panel.apply_directory(prefs.directory)
            self._output_panel.apply_open_folder_after_run(
                prefs.open_folder_after_run
            )
            self._output_panel.apply_render_style_params(prefs.render_style)
            self._output_panel.apply_outputs(prefs.as_output())
        finally:
            self._applying_analysis_preset = False

    def _panel_prefs(self) -> BatchPanelPrefs:
        snapshot = self._output_controls_snapshot()
        # ``snapshot["outputs"]`` is a full ``dataclasses.asdict`` including
        # runtime fields; BatchPanelPrefs whitelists them back out.
        return BatchPanelPrefs(
            directory=self._output_panel.directory(),
            render_style=snapshot["render_style"],
            outputs=snapshot["outputs"],
            open_folder_after_run=self._output_panel.open_folder_after_run(),
        )

    def _persist_panel_prefs(self) -> None:
        """Write the current display preferences.

        Called from ``done`` (every close path) and right after a run starts —
        never from ``_on_output_controls_changed``, which fires on every
        keystroke and spin-box tick.
        """
        self._prefs_store.save(self._panel_prefs())

    def _on_restore_output_defaults(self) -> None:
        """恢复默认: forget the stored preferences and reset the panel.

        Both halves are required — resetting the widgets alone would be undone
        by the next ``_persist_panel_prefs``, and clearing the key alone would
        not visibly change anything until the dialog is reopened.
        """
        self._prefs_store.clear()
        self._applying_analysis_preset = True
        try:
            self._output_panel.restore_defaults()
        finally:
            self._applying_analysis_preset = False
        if self._analysis_preset_output_snapshot is not None:
            # Re-baseline instead of leaving a stale comparison behind: an
            # applied analysis card owns axes, not display preferences, so it
            # must survive this reset without going deaf to the next real edit.
            self._analysis_preset_output_snapshot = self._output_controls_snapshot()
        self._schedule_pipeline_recompute()
        self._toast("已恢复导出默认设置", kind="success")

    def _on_output_controls_changed(self) -> None:
        if (
            not self._applying_analysis_preset
            and self._analysis_panel.has_applied_preset()
            and self._analysis_preset_output_snapshot is not None
            and self._output_controls_snapshot()
            != self._analysis_preset_output_snapshot
        ):
            self._analysis_panel.clear_applied_preset()
            self._analysis_preset_output_snapshot = None
        self._schedule_pipeline_recompute()

    def _db_reference_host(self):
        """Return the owning MainWindow without coupling BatchSheet to it."""
        host = self.parentWidget()
        while host is not None:
            if callable(getattr(host, "_open_db_reference_dialog", None)):
                return host
            host = host.parentWidget()
        return None

    def _open_shared_db_reference_manager(self) -> None:
        """Open the same global dB-reference manager as single-file views."""
        host = self._db_reference_host()
        if host is None:
            return
        section = _DB_REFERENCE_SECTION_BY_METHOD.get(self.method(), "fft")
        host._open_db_reference_dialog(
            section,
            view_control=self._output_panel.db_reference_control,
            on_catalog_saved=self._on_batch_db_reference_catalog_saved,
            on_view_mode_committed=self._on_batch_db_reference_view_mode_committed,
        )

    def _on_batch_db_reference_catalog_saved(self) -> None:
        """Refresh the Batch resolver after the shared catalog is saved."""
        host = self._db_reference_host()
        store = getattr(host, "db_reference_store", None) if host else None
        snapshot = getattr(store, "snapshot", None)
        if callable(snapshot):
            self._output_panel.set_reference_catalog(snapshot())
        self._schedule_pipeline_recompute()

    def _on_batch_db_reference_view_mode_committed(self, mode: str) -> None:
        """Apply the dialog's current-view mode to Batch, never Inspector."""
        self._output_panel.db_reference_control.set_mode(mode)
        self._on_output_controls_changed()

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
            # ``apply_preset`` is a full-recipe boundary.  Canonical time
            # recipes omit default-valued sparse fields, so materialize those
            # defaults for the controls here.  ``apply_params`` itself remains
            # incremental for built-in presets and other partial patches.
            control_params = (
                {**TIME_RENDER_DEFAULTS, **params}
                if method == "time"
                else params
            )
            self.apply_params(control_params)
            if "rpm_factor" in params:
                self._input_panel.apply_rpm_factor(params["rpm_factor"])
            self._input_panel.apply_filter_params(params.get("filter"))
            self._output_panel.apply_axis_params(params)
            self._output_panel.apply_reference_params(params)
            self._output_panel.apply_render_style_params(params)
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
        self._schedule_pipeline_recompute()

    def _on_recipe_method_changed(self, method: str) -> None:
        method = str(method)
        if not self._applying_preset and method != self._recipe_method:
            self._base_params = normalize_batch_params(self._base_params, method)
        self._recipe_method = method
        self._sync_x_axis_context()

    def _on_channel_universe_changed(
        self, common: tuple, partial: dict,
    ) -> None:
        self._x_channel_common = tuple(str(name) for name in common if str(name))
        self._x_channel_partial = {
            str(name): str(suffix)
            for name, suffix in partial.items()
            if str(name)
        }
        self._refresh_x_channel_candidates()
        self._sync_x_axis_context()

    def _custom_x_compatible_rows(self, channel: str) -> tuple:
        """Return logical sources where a custom X can pair with a target.

        ``available_per_source`` deliberately treats a multi-rate container as
        multiple logical sources. An X channel is eligible only in rows that
        contain both that channel and at least one selected target.
        """
        rows = tuple(self._input_panel._file_list.loaded_rows())
        if self.target_policy() != "available_per_source":
            return tuple(row for row in rows if channel in row.channels)
        selected = frozenset(self.selected_signals())
        if not selected:
            return tuple(row for row in rows if channel in row.channels)
        return tuple(
            row for row in rows
            if channel in row.channels and selected.intersection(row.channels)
        )

    def _refresh_x_channel_candidates(self) -> None:
        partial_selectable: tuple[str, ...] = ()
        if self.target_policy() == "available_per_source":
            selected = frozenset(self.selected_signals())
            compatible_channels = {
                str(channel)
                for row in self._input_panel._file_list.loaded_rows()
                if not selected or selected.intersection(row.channels)
                for channel in row.channels
            }
            partial_selectable = tuple(
                name for name in self._x_channel_partial
                if name in compatible_channels
            )
        self._analysis_panel._param_form.set_x_channel_candidates(
            self._x_channel_common,
            self._x_channel_partial,
            partial_selectable=partial_selectable,
        )

    def _x_channel_units(self, channel: str) -> tuple[str, ...]:
        units: set[str] = set()
        for row in self._custom_x_compatible_rows(channel):
            metadata = dict(getattr(row, "metadata", {}) or {})
            channel_metadata = metadata.get("channel_metadata") or {}
            facts = dict(channel_metadata.get(channel) or {})
            unit = facts.get("unit") or dict(
                getattr(row, "units", {}) or {}
            ).get(channel, "")
            clean = str(unit or "").strip()
            # Missing/blank units are still source facts.  Dropping them would
            # make ("", "rpm") look uniformly rpm and publish a false axis
            # unit instead of rejecting the mixed-source recipe.
            units.add(clean)
        return tuple(sorted(units))

    def _sync_x_axis_context(self, *_args) -> None:
        if self.method() != "time":
            return
        params = self.params()
        if str(params.get("x_source", "time")) != "channel":
            self._output_panel.set_x_axis_context(label="Time", unit="s")
            self._analysis_panel.set_chart_statistics_x_context(x_source="time", unit="s")
            return
        channel = str(params.get("x_channel") or "").strip()
        units = self._x_channel_units(channel) if channel else ()
        unit = units[0] if len(units) == 1 else ""
        self._output_panel.set_x_axis_context(
            label=channel or "X", unit=unit,
        )
        self._analysis_panel.set_chart_statistics_x_context(
            x_source="channel", x_channel=channel, unit=unit,
        )

    def _control_params_snapshot(self, method: str | None = None) -> dict:
        method_key = str(method or self.method())
        params = dict(self.params())
        axis = self._output_panel.axis_params()
        params.update(axis)
        params.update(self._output_panel.reference_params())
        params.update(self._output_panel.render_style_params())
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
            self, "导入方案", "", "JSON (*.json)"
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
            self, "导出方案", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            save_preset_to_json(preset, path)
        except OSError as exc:
            self._toast(f"导出失败：{exc}", kind="error")
            return
        self._toast(f"已导出方案到：{path}", kind="success")

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
    def is_runnable(
        self, *, issues: tuple[ValidationIssue, ...] | None = None,
    ) -> bool:
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
        if (self.preflight_issues() if issues is None else issues):
            return False
        return True

    def preflight_issues(self) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        time_error = self._time_range_error()
        if time_error:
            issues.append(ValidationIssue(
                "time_range", "invalid_text", time_error,
            ))
        slice_error = self._analysis_panel.slice_positions_error()
        if slice_error:
            issues.append(ValidationIssue(
                "slice_positions", "invalid_text", slice_error,
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
        if (
            self.method() == "order_time"
            and not self.rpm_channel()
            and effective_rpm_signal is None
            and not any(issue.field == "rpm_channel" for issue in issues)
        ):
            issues.append(ValidationIssue(
                "rpm_channel", "missing_rpm_channel",
                "阶次分析的通道转速模式需要 RPM 通道",
            ))
        x_channel = str(params.get("x_channel") or "").strip()
        if (
            self.method() == "time"
            and str(params.get("x_source", "time")) == "channel"
            and x_channel
        ):
            compatible_rows = self._custom_x_compatible_rows(x_channel)
            if (
                policy == "available_per_source"
                and selected
                and not compatible_rows
            ):
                issues.append(ValidationIssue(
                    "x_channel", "unavailable_x_channel",
                    "X channel is unavailable for the selected target signals",
                ))
            elif len(self._x_channel_units(x_channel)) > 1:
                issues.append(ValidationIssue(
                    "x_channel", "mixed_x_units",
                    "X channel units differ across matching sources",
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
    def _build_dry_run_preview(
        self, preset: AnalysisPreset | None = None,
    ) -> list[tuple[str, str, str]]:
        """Compute the dry-run task list from UI state ONLY.

        Spec §3.5 / W6 invariant: never call ``BatchRunner._expand_tasks``
        — that path runs ``_resolve_files`` which would ``loader(path)``
        full-load disk files on the UI thread and freeze the dialog. Per
        spec §3.2 disk files use the cached probe set on the file row.

        Policy filtering mirrors preflight: common only lists the true
        intersection; available-per-source lists each valid source/signal
        pair; exact-pair scope is preserved verbatim above.
        """
        preset = preset or self.get_preset()
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
        params = dict(preset.params or {})
        x_channel = str(params.get("x_channel") or "").strip()
        needs_custom_x = (
            method == "time"
            and str(params.get("x_source", "time") or "time") == "channel"
            and bool(x_channel)
        )
        for row in fl.loaded_rows():
            fd = self._files.get(row.source_id)
            label = getattr(fd, "filename", None) or row.label or str(row.source_id)
            for sig in signals:
                if policy == "common" and sig not in common:
                    continue
                if policy == "available_per_source" and sig not in row.channels:
                    continue
                if (
                    policy == "available_per_source"
                    and needs_custom_x
                    and x_channel not in row.channels
                ):
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

        runner = self._make_runner()
        preset = self.get_preset()
        output_dir = self.output_dir()
        preview = runner.preview_outputs(preset, output_dir)

        # Build rows from cached UI state; the visible output count comes
        # from the runner's group-aware planner.
        tasks = self._build_dry_run_preview(preset)
        self._task_list.apply_dry_run(
            tasks,
            self._outputs_per_task(),
            artifact_count=preview.artifact_count,
        )

        # Synchronous lock: order matters.
        self._running = True
        self._btn_run.setEnabled(False)
        self.lock_editing()
        self._task_list.on_run_started()
        total = max(1, len(tasks))
        self._present_footer(
            "running", done=0, total=total, task_count=len(tasks),
        )

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
        thread = BatchRunnerThread(
            runner,
            preset,
            output_dir,
            parent=self,
        )
        self._runner_thread = thread
        # AutoConnection is correct in production (live event loop). Both
        # signals are object-tagged so qtbot can connect bare callables.
        thread.progress.connect(self._on_runner_progress)
        thread.finished_with_result.connect(self._on_runner_finished_with_result)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

        # Persist here as well as on close: a long run that ends in a crash
        # (or a force-quit while it works) would otherwise lose the settings
        # the user just tuned for exactly this export.
        self._persist_panel_prefs()

    def _representative_channel_gap_message(self, group) -> str:
        """Name the reason no planned group can show the selected channels.

        "预览不可用" on its own sent a user hunting: his HDF had been split by
        sample rate into four logical sources and the channels he picked lived
        in only two of them, which nothing on screen said.  Report the source
        that was planned and, when that file really did split, how far.
        """

        detail = ""
        subject = "代表分组"
        if group.group_by == "source":
            subject = "代表来源"
            base = str(group.display_name or "").strip()
            siblings = sum(
                1 for path in self._input_panel.source_paths()
                if base and Path(str(path)).name == base
            )
            if siblings > 1:
                detail = f"；该文件按采样率拆成了 {siblings} 个子来源"
        return (
            f"预览不可用：{subject} {group.display_name} 不含所选通道{detail}"
        )

    def _on_preview_clicked(self) -> None:
        """No-load-plan, then immediately render the first formal group."""
        if self._running or self._preview_thread is not None or not self.is_runnable():
            return
        runner = self._make_runner()
        preset = self.get_preset()
        try:
            plan = runner.preview_outputs(
                preset,
                self.output_dir(),
                # One physical file can expand into several logical sources, so
                # the first planned group is not necessarily one that holds the
                # selected channels.  Planning is no-load; hand the planner the
                # probe result the input panel already has.
                source_channels=self._input_panel.source_channel_sets(),
            )
        except Exception as exc:  # noqa: BLE001
            self._toast(f"预览不可用：{exc}", kind="warning")
            return
        group = plan.representative_group
        if group is None:
            self._toast("预览不可用：没有可生成的代表输出", kind="warning")
            return
        if not group.channel_available:
            self._toast(
                self._representative_channel_gap_message(group), kind="warning",
            )
            return
        dialog = self._preview_dialog
        if dialog is None:
            dialog = BatchPreviewDialog(self)
            dialog.regenerate_requested.connect(self._start_preview_render)
            dialog.run_all_requested.connect(self._run_all_from_preview)
            dialog.cancel_requested.connect(self._cancel_preview)
            dialog.finished.connect(self._cleanup_preview_temp)
            self._preview_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._preview_plan = (runner, preset, group)
        self._start_preview_render()

    def _start_preview_render(self) -> None:
        if self._preview_thread is not None:
            return
        runner, preset, group = getattr(self, "_preview_plan", (None, None, None))
        if runner is None or group is None:
            return
        self._cleanup_preview_temp()
        self._preview_temp = tempfile.TemporaryDirectory(prefix="tracelab-batch-preview-")
        dialog = self._preview_dialog
        if dialog is None:
            return
        dialog.set_loading(
            f"{group.display_name} · 代表输出 {group.ordinal} / {group.total_groups} · "
            f"将读取 {group.required_source_count} 个来源"
        )
        self._preview_result = None
        self._btn_preview.setEnabled(False)
        thread = BatchPreviewThread(
            runner, preset, group.group_id, self._preview_temp.name, parent=self,
        )
        self._preview_thread = thread
        thread.finished_with_result.connect(self._on_preview_finished_with_result)
        # The only preview unlock/cleanup boundary is QThread.finished.
        thread.finished.connect(self._on_preview_thread_finished)
        thread.start()

    def _cancel_preview(self) -> None:
        if self._preview_thread is not None:
            self._preview_thread.request_cancel()

    def _on_preview_finished_with_result(self, result) -> None:
        self._preview_result = result

    def _on_preview_thread_finished(self) -> None:
        thread = self._preview_thread
        self._preview_thread = None
        if thread is not None:
            thread.deleteLater()
        dialog = self._preview_dialog
        if dialog is not None:
            result = self._preview_result
            if str(getattr(result, "status", "")) == "cancelled":
                dialog.set_cancelled()
            else:
                dialog.set_result(result)
        if not self._running:
            self._btn_preview.setEnabled(self.is_runnable())
        if self._preview_close_pending:
            self._preview_close_pending = False
            self.close()

    def _cleanup_preview_temp(self, *_args) -> None:
        if self._preview_thread is not None:
            return
        temp = self._preview_temp
        self._preview_temp = None
        if temp is not None:
            temp.cleanup()

    def _run_all_from_preview(self) -> None:
        dialog = self._preview_dialog
        if dialog is not None:
            dialog.accept()
        self._cleanup_preview_temp()
        self._on_run_clicked()

    def _on_cancel_clicked(self) -> None:
        """Running-mode 中断 handler — sets the cancel token and disables
        the abort button so it cannot be clicked twice."""
        if not self._running or self._runner_thread is None:
            return
        self._btn_abort.setEnabled(False)
        self._btn_abort.setText("正在停止…")
        self._present_footer(
            "cancelling",
            done=self._footer_progress.value(),
            total=self._footer_progress.maximum(),
            task_count=self._task_list.row_count(),
        )
        self._runner_thread.request_cancel()

    def _on_runner_progress(self, event) -> None:
        # Keep the legacy task model current for programmatic artifact facts;
        # the visible compact footer deliberately exposes only aggregate state.
        self._task_list.on_event(event)
        total = max(1, int(getattr(event, "total", 0) or 1))
        task_index = max(0, int(getattr(event, "task_index", 0) or 0))
        kind = str(getattr(event, "kind", "") or "")
        completed = kind in {
            "task_done", "task_failed", "task_cancelled", "task_skipped",
            "task_resumed",
        }
        progress = task_index if completed else max(0, task_index - 1)
        self._footer_progress.setRange(0, total)
        self._footer_progress.setValue(max(self._footer_progress.value(), progress))
        if kind != "run_finished":
            self._footer_task_summary.setText(
                f"{self._footer_progress.value()}/{total} 任务"
            )

    def _on_runner_finished_with_result(self, result) -> None:
        """Stash the BatchRunResult; the actual unlock happens in
        ``_on_thread_finished`` (bound to ``QThread.finished``) per spec
        §6.2 unlock contract."""
        self._last_result = result
        if result is None:
            return

    def _on_thread_finished(self) -> None:
        """Bound to ``QThread.finished`` — guaranteed to fire by Qt even if
        ``runner.run()`` raised before ``finished_with_result`` would have
        emitted (W6 invariant 1).
        """
        result = self._last_result
        self._task_list.on_run_finished(result)
        self.unlock_editing()
        status = str(getattr(result, "status", "") or "未知")
        labels = {
            "done": "已完成",
            "partial": "部分完成",
            "cancelled": "已取消",
            "blocked": "未运行",
        }
        total = max(1, self._task_list.row_count())
        done = min(total, max(0, self._task_list._done_count))
        if status == "done":
            done = total
        self._present_footer(
            status if status in labels else labels.get(status, status),
            done=done, total=total, task_count=self._task_list.row_count(),
        )
        self._show_result_toast(result)
        self._maybe_open_output_folder(result)

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
            degraded_count = int(
                getattr(result, "degraded_count", 0) or 0
            )
            if degraded_count and not blocked:
                QMessageBox.information(
                    self,
                    "批处理降级完成",
                    f"完成，共 {degraded_count} 个任务仅导出数据文件。",
                )
            else:
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

    def _maybe_open_output_folder(self, result) -> None:
        """完成后打开输出文件夹: fires once, right after the (blocking) result
        toast has been dismissed -- opening Explorer underneath a modal
        QMessageBox would just fight it for focus.

        Only for a run that actually produced (``done``) or attempted
        (``partial``) output; ``cancelled`` / ``blocked`` never had a real
        output pass, so there is nothing worth revealing.
        """
        if result is None:
            return
        if not self._output_panel.open_folder_after_run():
            return
        status = str(getattr(result, "status", "") or "")
        if status not in {"done", "partial"}:
            return
        target_dir = self.output_dir()
        if not target_dir or not Path(target_dir).expanduser().is_dir():
            return
        self._open_artifact_location(target_dir)

    def lock_editing(self) -> None:
        """Disable detail panels + swap footer to running mode."""
        self._input_panel.setEnabled(False)
        self._analysis_panel.setEnabled(False)
        self._output_panel.setEnabled(False)
        self._btn_fill_from_current.setEnabled(False)
        self._btn_import_preset.setEnabled(False)
        self._btn_export_preset.setEnabled(False)
        self._btn_cancel.setVisible(False)
        self._btn_preview.setVisible(False)
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
        self._btn_preview.setVisible(True)
        self._btn_run.setVisible(True)
        # Re-evaluate Run-button enabled state against current config.
        self._btn_run.setEnabled(self.is_runnable())
        self._btn_preview.setEnabled(self.is_runnable())

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
        if self._preview_thread is not None:
            self._preview_close_pending = True
            self._cancel_preview()
            event.ignore()
            return
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
        # Normal-close branch only; the run-in-progress branch above ignores
        # the event and comes back through here once the runner has stopped.
        self._persist_panel_prefs()
        super().closeEvent(event)

    def done(self, result):  # noqa: N802 (Qt API)
        """Persist the display preferences on the way out.

        ``closeEvent`` alone would miss the dialog's PRIMARY exit: 关闭 is
        wired straight to ``QDialog.reject`` and Esc does the same, and neither
        raises a ``QCloseEvent`` at all. ``done`` is the funnel both of those
        reach.

        Both hooks are kept because neither covers the other. ``QDialog``
        only re-routes a close event into ``reject()`` while the dialog is
        *visible*, so closing a never-shown sheet stops at ``closeEvent``;
        conversely a visible close runs both, writing the same snapshot twice,
        which is harmless.
        """
        self._persist_panel_prefs()
        super().done(result)

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
