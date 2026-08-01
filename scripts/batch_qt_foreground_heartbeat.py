#!/usr/bin/env python3
"""Foreground Gate 4.5 heartbeat probe for the real Qt batch renderer.

This is an operator-facing acceptance probe, not a unit-test renderer.  It
loads a real source, runs the production ``BatchRunnerThread`` until at least
20 PNG files have been published, and samples the GUI event loop with a 50 ms
``QTimer``.  The visible status window is intentionally small so the operator
can drag it and hover its tooltip while rendering is in progress.

Foreground macOS example::

    TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
      '/Users/donghang/Downloads/data analyzer/.venv/bin/python' \
      scripts/batch_qt_foreground_heartbeat.py \
      --output-dir /tmp/tracelab-gate45

An offscreen run can validate wiring and JSON structure, but it is not
foreground evidence and must not be reported as Gate 4.5 acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = Path(
    "/Users/donghang/Downloads/data analyzer/testdoc/X04C_Ripple.mf4"
)
TIMER_INTERVAL_MS = 50
MAX_GAP_BUDGET_MS = 200.0
MIN_PNG_COUNT = 20
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real BatchRunnerThread/Qt batch renderer while measuring "
            "a 50 ms GUI-thread heartbeat."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"real MF4/CSV source (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="parent directory for a unique Gate 4.5 run directory",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=MIN_PNG_COUNT,
        help=f"PNG target; values below {MIN_PNG_COUNT} are rejected",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help="request cancellation if the batch has not completed in time",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="report path (default: <unique-run-dir>/gate45-heartbeat.json)",
    )
    return parser


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _configuration_failure(message: str, *, source: Path | None = None) -> int:
    payload = {
        "gate": "batch_qt_foreground_heartbeat",
        "pass": False,
        "configuration_error": str(message),
        "source": str(source) if source is not None else None,
        "timestamp_utc": _utc_now(),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 2


def _eligible_channels(file_data) -> list[str]:
    """Return finite one-dimensional numeric signals in source order."""

    import numpy as np

    eligible: list[str] = []
    seen: set[str] = set()
    for raw_name in file_data.get_signal_channels():
        name = str(raw_name)
        # MDF time masters commonly arrive as ``t [group:raster]`` and are not
        # covered by FileData's exact-name time filter.  They are X axes, not
        # representative target signals for this render stress run.
        if re.fullmatch(r"t\s*\[\d+:\d+\]", name, flags=re.IGNORECASE):
            continue
        if name in seen or name not in file_data.data.columns:
            continue
        seen.add(name)
        try:
            values = file_data.data[name].to_numpy(copy=False)
            if np.iscomplexobj(values):
                continue
            numeric = np.asarray(values, dtype=float)
        except (TypeError, ValueError, OverflowError):
            continue
        if numeric.ndim != 1 or numeric.size < 2:
            continue
        if int(np.count_nonzero(np.isfinite(numeric))) < 2:
            continue
        eligible.append(name)
    return eligible


def _run_qt(args: argparse.Namespace, settings_dir: Path) -> int:
    # Configure DPI and settings before QApplication construction.  This probe
    # does not instantiate MainWindow/Inspector, but both Qt settings formats
    # are still diverted so no future status-widget change can leak state into
    # MF4Analyzer/DataAnalyzer.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import (
        QCoreApplication,
        QEvent,
        QObject,
        QSettings,
        QThread,
        QTimer,
        Qt,
        pyqtSlot,
    )
    from PyQt5.QtWidgets import (
        QApplication,
        QLabel,
        QProgressBar,
        QToolTip,
        QVBoxLayout,
        QWidget,
    )

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_dir))
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(settings_dir))
    QCoreApplication.setOrganizationName("TraceLabGate45")
    QCoreApplication.setApplicationName(f"BatchQtHeartbeat-{os.getpid()}")
    for attribute_name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        attribute = getattr(Qt, attribute_name, None)
        if attribute is not None:
            QCoreApplication.setAttribute(attribute, True)

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    import mf4_analyzer.batch_render_qt as qt_renderer
    from mf4_analyzer.io.source_adapters import DEFAULT_SOURCE_ADAPTER_REGISTRY
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    loaded_sources = tuple(
        DEFAULT_SOURCE_ADAPTER_REGISTRY.load_sources(args.source)
    )
    candidates = [
        (source, _eligible_channels(source.file_data))
        for source in loaded_sources
    ]
    candidates = [candidate for candidate in candidates if candidate[1]]
    if not candidates:
        raise ValueError("source has no finite numeric signal with at least 2 samples")
    source, channels = max(candidates, key=lambda candidate: len(candidate[1]))
    source_id = source.source_id
    file_data = source.file_data

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir / f"gate45-heartbeat-{run_stamp}-{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    report_path = args.report_json or (run_dir / "gate45-heartbeat.json")

    class StatusWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.tooltip_event_count = 0
            self.tooltip_hover_response_count = 0
            self.mouse_move_event_count = 0
            self.move_event_count = 0
            self.setWindowTitle("TraceLab · Batch Qt Gate 4.5")
            self.setMinimumWidth(520)
            self.setToolTip(
                "拖动此窗口并悬停查看 tooltip；heartbeat 正在监测 GUI 事件循环。"
            )
            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(10)
            self.title = QLabel("真实 BatchRunnerThread · Qt PNG heartbeat", self)
            self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
            self.detail = QLabel(
                "运行中请持续拖动窗口，并将鼠标悬停在本行确认 tooltip 响应。",
                self,
            )
            self.detail.setToolTip(
                "Gate 4.5 交互探针：若 tooltip 或拖动连续冻结，请记录为人工失败。"
            )
            self.detail.setMouseTracking(True)
            self.installEventFilter(self)
            self.detail.installEventFilter(self)
            self.status = QLabel("正在准备真实数据…", self)
            self.progress = QProgressBar(self)
            self.progress.setRange(0, int(args.count))
            self.progress.setValue(0)
            layout.addWidget(self.title)
            layout.addWidget(self.detail)
            layout.addWidget(self.status)
            layout.addWidget(self.progress)

        def eventFilter(self, watched, event):
            if event.type() == QEvent.ToolTip:
                self.tooltip_event_count += 1
            elif watched is self.detail and event.type() == QEvent.MouseMove:
                self.mouse_move_event_count += 1
                if event.buttons() == Qt.NoButton:
                    QToolTip.showText(
                        event.globalPos(), self.detail.toolTip(), self.detail
                    )
                    self.tooltip_hover_response_count += 1
            elif watched is self and event.type() == QEvent.Move:
                self.move_event_count += 1
            return super().eventFilter(watched, event)

    window = StatusWindow()
    window.show()

    render_gui_thread_checks: list[bool] = []
    original_builder = qt_renderer.build_batch_scene

    def traced_builder(*builder_args, **builder_kwargs):
        render_gui_thread_checks.append(QThread.currentThread() is app.thread())
        return original_builder(*builder_args, **builder_kwargs)

    qt_renderer.build_batch_scene = traced_builder

    class Controller(QObject):
        def __init__(self) -> None:
            super().__init__(window)
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.PreciseTimer)
            self.heartbeat.setInterval(TIMER_INTERVAL_MS)
            self.heartbeat.timeout.connect(self._on_heartbeat)
            self.timeout = QTimer(self)
            self.timeout.setSingleShot(True)
            self.timeout.timeout.connect(self._on_timeout)
            self.ticks: list[float] = []
            self.started_monotonic: float | None = None
            self.thread: BatchRunnerThread | None = None
            self.pending_result = None
            self.cycle = 0
            self.thread_started_count = 0
            self.thread_finished_count = 0
            self.results: list[dict[str, Any]] = []
            self.png_paths: list[str] = []
            self.progress_events: list[dict[str, Any]] = []
            self.errors: list[str] = []
            self.timed_out = False
            self.finalized = False
            self.exit_code = 2

        @pyqtSlot()
        def start(self) -> None:
            self.started_monotonic = time.perf_counter()
            self.ticks = [self.started_monotonic]
            self.heartbeat.start()
            self.timeout.start(max(1, round(float(args.timeout_seconds) * 1000.0)))
            self._start_cycle()

        def _preset_for(self, cycle_channels: list[str]):
            outputs = BatchOutput(
                export_data=False,
                export_image=True,
                image_format="png",
                image_size="1920x1080",
                image_width=1920,
                image_height=1080,
                image_dpi=144,
                image_background="white",
                image_line_width=1.5,
                conflict_policy="auto_number",
                write_manifest=False,
            )
            preset = AnalysisPreset.free_config(
                name="Gate 4.5 foreground heartbeat",
                method="time",
                target_signals=tuple(cycle_channels),
                target_policy="exact_pairs",
                params={
                    "render_group_by": "none",
                    "render_layout": "overlay",
                    "x_source": "time",
                    "x_origin": "zero",
                },
                outputs=outputs,
            )
            return replace(
                preset,
                target_pairs=tuple((source_id, name) for name in cycle_channels),
                source_ids=(source_id,),
                source_paths=(),
            )

        def _start_cycle(self) -> None:
            remaining = int(args.count) - len(self.png_paths)
            if remaining <= 0:
                self._finalize()
                return
            self.cycle += 1
            cycle_channels = channels[: min(len(channels), remaining)]
            preset = self._preset_for(cycle_channels)
            runner = BatchRunner({source_id: file_data})
            self.pending_result = None
            self.thread = BatchRunnerThread(runner, preset, run_dir)
            self.thread.progress.connect(self._on_progress)
            self.thread.finished_with_result.connect(self._on_result)
            self.thread.finished.connect(self._on_thread_finished)
            self.thread_started_count += 1
            window.status.setText(
                f"第 {self.cycle} 轮 · {len(cycle_channels)} 张 · "
                f"累计 {len(self.png_paths)}/{args.count}"
            )
            self.thread.start()

        @pyqtSlot()
        def _on_heartbeat(self) -> None:
            self.ticks.append(time.perf_counter())

        @pyqtSlot(object)
        def _on_progress(self, event) -> None:
            event_record = {
                "kind": str(getattr(event, "kind", "")),
                "task_index": getattr(event, "task_index", None),
                "total": getattr(event, "total", None),
                "signal": getattr(event, "signal", None),
                "error": getattr(event, "error", None),
            }
            self.progress_events.append(event_record)
            if event_record["kind"] == "task_started":
                window.status.setText(
                    f"第 {self.cycle} 轮 · {event_record['signal']} · "
                    f"累计 {len(self.png_paths)}/{args.count}"
                )
            terminal = {
                "task_done", "task_failed", "task_cancelled",
                "task_skipped", "task_resumed",
            }
            completed = sum(
                record["kind"] in terminal for record in self.progress_events
            )
            window.progress.setValue(min(int(args.count), completed))

        @pyqtSlot(object)
        def _on_result(self, result) -> None:
            self.pending_result = result

        @pyqtSlot()
        def _on_thread_finished(self) -> None:
            self.thread_finished_count += 1
            QTimer.singleShot(0, self._consume_finished_thread)

        @pyqtSlot()
        def _consume_finished_thread(self) -> None:
            thread = self.thread
            result = self.pending_result
            if result is None:
                self.errors.append(f"cycle {self.cycle}: thread finished without result")
            else:
                item_records = []
                for item in result.items:
                    item_records.append({
                        "signal": str(item.signal),
                        "status": str(item.status),
                        "image_path": item.image_path,
                        "message": str(item.message or ""),
                    })
                    if item.status == "done" and item.image_path:
                        self.png_paths.append(str(item.image_path))
                    elif item.status != "done":
                        self.errors.append(
                            f"{item.signal}: {item.status}: {item.message}"
                        )
                self.results.append({
                    "cycle": self.cycle,
                    "status": str(result.status),
                    "blocked": [str(value) for value in result.blocked],
                    "items": item_records,
                })
                if result.status != "done":
                    self.errors.extend(str(value) for value in result.blocked)
            self.png_paths = list(dict.fromkeys(self.png_paths))
            window.progress.setValue(min(int(args.count), len(self.png_paths)))
            if thread is not None:
                thread.deleteLater()
            self.thread = None
            self.pending_result = None
            if self.errors or self.timed_out:
                self._finalize()
            elif len(self.png_paths) >= int(args.count):
                self._finalize()
            else:
                QTimer.singleShot(0, self._start_cycle)

        @pyqtSlot()
        def _on_timeout(self) -> None:
            self.timed_out = True
            self.errors.append(
                f"timeout after {float(args.timeout_seconds):g} seconds"
            )
            window.status.setText("超时：正在请求 worker 安全取消…")
            if self.thread is not None:
                self.thread.request_cancel()

        def _finalize(self) -> None:
            if self.finalized:
                return
            if self.thread is not None and self.thread.isRunning():
                return
            self.finalized = True
            self.heartbeat.stop()
            self.timeout.stop()
            finished_monotonic = time.perf_counter()
            self.ticks.append(finished_monotonic)
            gaps_ms = [
                (right - left) * 1000.0
                for left, right in zip(self.ticks, self.ticks[1:])
            ]
            max_gap_ms = max(gaps_ms) if gaps_ms else None

            png_records = []
            for raw_path in self.png_paths:
                path = Path(raw_path)
                exists = path.is_file()
                size = path.stat().st_size if exists else 0
                valid_signature = False
                if exists and size >= len(PNG_SIGNATURE):
                    with path.open("rb") as stream:
                        valid_signature = stream.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
                png_records.append({
                    "path": str(path),
                    "exists": exists,
                    "bytes": size,
                    "valid_png_signature": valid_signature,
                })

            item_statuses = [
                item["status"]
                for result in self.results
                for item in result["items"]
            ]
            all_png_valid = bool(png_records) and all(
                record["exists"]
                and record["bytes"] > len(PNG_SIGNATURE)
                and record["valid_png_signature"]
                for record in png_records
            )
            worker_ok = (
                self.thread_started_count == self.thread_finished_count
                and bool(self.results)
                and all(result["status"] == "done" for result in self.results)
                and bool(item_statuses)
                and all(status == "done" for status in item_statuses)
                and not self.errors
                and not self.timed_out
            )
            renderer_thread_ok = (
                len(render_gui_thread_checks) >= int(args.count)
                and all(render_gui_thread_checks)
            )
            heartbeat_ok = (
                max_gap_ms is not None
                and max_gap_ms <= MAX_GAP_BUDGET_MS
            )
            png_ok = len(png_records) >= int(args.count) and all_png_valid
            passed = worker_ok and renderer_thread_ok and heartbeat_ok and png_ok

            report = {
                "gate": "batch_qt_foreground_heartbeat",
                "pass": passed,
                "platform": os.environ.get("QT_QPA_PLATFORM", ""),
                "foreground_claimed": False,
                "source": str(args.source),
                "source_id": str(source_id),
                "available_numeric_channel_count": len(channels),
                "selected_channels": channels[: min(len(channels), int(args.count))],
                "output_dir": str(run_dir),
                "report_json": str(report_path),
                "requested_png_count": int(args.count),
                "published_png_count": len(png_records),
                "pngs": png_records,
                "heartbeat": {
                    "timer_interval_ms": TIMER_INTERVAL_MS,
                    "budget_ms": MAX_GAP_BUDGET_MS,
                    "tick_count": len(self.ticks),
                    "elapsed_ms": (
                        (finished_monotonic - self.started_monotonic) * 1000.0
                        if self.started_monotonic is not None else None
                    ),
                    "max_gap_ms": max_gap_ms,
                    "over_100ms_count": sum(gap > 100.0 for gap in gaps_ms),
                    "over_budget_count": sum(
                        gap > MAX_GAP_BUDGET_MS for gap in gaps_ms
                    ),
                    "pass": heartbeat_ok,
                },
                "worker": {
                    "thread_started_count": self.thread_started_count,
                    "thread_finished_count": self.thread_finished_count,
                    "timed_out": self.timed_out,
                    "errors": list(dict.fromkeys(self.errors)),
                    "cycles": self.results,
                    "pass": worker_ok,
                },
                "renderer": {
                    "facade": "mf4_analyzer.batch_render",
                    "backend": "mf4_analyzer.batch_render_qt",
                    "scene_build_count": len(render_gui_thread_checks),
                    "all_scene_builds_on_gui_thread": (
                        bool(render_gui_thread_checks)
                        and all(render_gui_thread_checks)
                    ),
                    "pass": renderer_thread_ok,
                },
                "qsettings": {
                    "isolated": True,
                    "path": str(settings_dir),
                },
                "interaction": {
                    "tooltip_event_count": window.tooltip_event_count,
                    "tooltip_hover_response_count": (
                        window.tooltip_hover_response_count
                    ),
                    "mouse_move_event_count": window.mouse_move_event_count,
                    "window_move_event_count": window.move_event_count,
                },
                "timestamp_utc": _utc_now(),
                "operator_note": (
                    "Only a live cocoa run with observed drag/tooltip response may be "
                    "accepted as foreground Gate 4.5 evidence."
                ),
            }
            try:
                _write_json_atomic(report_path, report)
            except Exception as exc:  # noqa: BLE001 - report failure is a hard gate
                report["pass"] = False
                report["report_write_error"] = str(exc)
                passed = False
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            self.exit_code = 0 if passed else 1
            window.status.setText(
                "PASS · 请保存前台拖动/tooltip观察记录"
                if passed else "FAIL · 详见 JSON"
            )
            window.progress.setValue(min(int(args.count), len(png_records)))
            QTimer.singleShot(1000, app.quit)

    controller = Controller()
    try:
        QTimer.singleShot(0, controller.start)
        app.exec_()
        return controller.exit_code
    finally:
        qt_renderer.build_batch_scene = original_builder


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.source = args.source.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    if args.report_json is not None:
        args.report_json = args.report_json.expanduser().resolve()
    if int(args.count) < MIN_PNG_COUNT:
        return _configuration_failure(
            f"--count must be at least {MIN_PNG_COUNT}", source=args.source
        )
    if float(args.timeout_seconds) <= 0:
        return _configuration_failure(
            "--timeout-seconds must be positive", source=args.source
        )
    if not args.source.is_file():
        return _configuration_failure(
            f"source does not exist: {args.source}", source=args.source
        )

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tracelab-gate45-settings-") as tmp:
            return _run_qt(args, Path(tmp))
    except Exception as exc:  # noqa: BLE001 - machine-readable probe boundary
        return _configuration_failure(
            f"{type(exc).__name__}: {exc}", source=args.source
        )


if __name__ == "__main__":
    raise SystemExit(main())
