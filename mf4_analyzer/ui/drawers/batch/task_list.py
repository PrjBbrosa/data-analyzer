"""Bottom collapsible task list + progress bar for the batch dialog.

Spec §3.5. Header switches between idle (``▾ N 任务待执行 · M 输出``) and
running (``进度 i/N  [progress bar]  ~Ts 剩余``) modes via
``on_run_started`` / ``on_run_finished``. Body is a list of rows — each
row carries an icon (``⏸/⟳/✓/✗/—``), a ``file · signal · method`` label,
and an optional error tooltip.

Driven by ``BatchProgressEvent`` instances forwarded from
``BatchRunnerThread.progress``. ETA computed as
``(now - run_start) / max(done, 1) * (total - done)``.

The widget emits an artifact-open request only after explicit row activation;
it never opens an external application by itself.
"""
from __future__ import annotations

import time
from typing import Sequence

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ....batch import BatchProgressEvent


# Icon glyphs per spec §3.5
_ICON_PENDING = "⏸"
_ICON_RUNNING = "⟳"
_ICON_DONE = "✓"
_ICON_FAILED = "✗"
_ICON_CANCELLED = "—"
_ICON_SKIPPED = "↷"
_ICON_RESUMED = "↻"
_BODY_MAX_HEIGHT = 120


class TaskListWidget(QWidget):
    """Collapsible header + body of per-task rows."""

    artifactOpenRequested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchTaskList")

        self._tasks: list[tuple[str, str, str]] = []
        self._icons: list[str] = []
        self._tooltips: list[str] = []
        self._items: list[QListWidgetItem] = []
        self._artifact_paths: list[tuple[str, str]] = []
        self._terminal_indices: set[int] = set()
        self._outputs_per_task: int = 0
        self._artifact_count: int | None = None
        self._expanded: bool = True

        # Run-state bookkeeping
        self._running: bool = False
        self._run_start: float = 0.0
        self._done_count: int = 0
        self._total: int = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # --- Header ---------------------------------------------------------
        self._header = QFrame(self)
        self._header.setObjectName("BatchTaskListHeader")
        head_lay = QHBoxLayout(self._header)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(8)

        # Toggle button doubles as the ▾/▸ disclosure arrow + the idle text.
        self._toggle_btn = QPushButton("▾", self._header)
        self._toggle_btn.setObjectName("BatchTaskListToggle")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self.toggle_collapse)
        head_lay.addWidget(self._toggle_btn, 0)

        # Idle label — visible when not running.
        self._idle_label = QLabel("0 任务待执行 · 0 输出", self._header)
        self._idle_label.setObjectName("BatchTaskListIdleLabel")
        head_lay.addWidget(self._idle_label, 0)

        # Running widgets — hidden when idle.
        self._progress_label = QLabel("进度 0/0", self._header)
        self._progress_label.setObjectName("BatchTaskListProgressLabel")
        head_lay.addWidget(self._progress_label, 0)

        self._progress_bar = QProgressBar(self._header)
        self._progress_bar.setObjectName("BatchTaskListProgressBar")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedWidth(160)
        head_lay.addWidget(self._progress_bar, 0)

        self._eta_label = QLabel("", self._header)
        self._eta_label.setObjectName("BatchTaskListETALabel")
        head_lay.addWidget(self._eta_label, 0)

        head_lay.addStretch(1)
        outer.addWidget(self._header)

        # --- Body -----------------------------------------------------------
        self._body = QListWidget(self)
        self._body.setObjectName("BatchTaskListBody")
        self._body.setMaximumHeight(_BODY_MAX_HEIGHT)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._body.itemDoubleClicked.connect(self._on_item_activated)
        outer.addWidget(self._body, 1)

        # Initialise mode (idle).
        self._set_running_mode(False)
        self._refresh_header_text()
        self._sync_body_visibility()

    # ------------------------------------------------------------------
    # Public read-only accessors
    # ------------------------------------------------------------------
    def row_count(self) -> int:
        return len(self._tasks)

    def row_icon(self, idx: int) -> str:
        return self._icons[idx]

    def row_tooltip(self, idx: int) -> str:
        return self._tooltips[idx]

    def row_artifact_paths(self, idx: int) -> tuple[str, str]:
        return self._artifact_paths[idx]

    def header_text(self) -> str:
        if self._running:
            parts = [self._progress_label.text()]
            if self._eta_label.text():
                parts.append(self._eta_label.text())
            return " ".join(parts)
        return self._idle_label.text()

    def progress_value(self) -> int:
        return int(self._progress_bar.value())

    def is_expanded(self) -> bool:
        return self._expanded

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------
    def apply_dry_run(
        self,
        tasks: Sequence[tuple[str, str, str]],
        outputs_per_task: int,
        *,
        artifact_count: int | None = None,
    ) -> None:
        """Replace the body rows with the supplied ``(file, signal, method)``
        tuples. Resets all icons to ⏸ and clears tooltips. Idle header text
        is rebuilt from ``len(tasks)`` and ``outputs_per_task``.
        """
        self._tasks = [tuple(t) for t in tasks]
        self._icons = [_ICON_PENDING] * len(self._tasks)
        self._tooltips = [""] * len(self._tasks)
        self._artifact_paths = [("", "")] * len(self._tasks)
        self._terminal_indices = set()
        self._outputs_per_task = int(outputs_per_task)
        self._artifact_count = (
            None if artifact_count is None else int(artifact_count)
        )

        self._body.clear()
        self._items = []
        for fname, sig, method in self._tasks:
            item = QListWidgetItem(self._format_row(_ICON_PENDING, fname, sig, method))
            self._body.addItem(item)
            self._items.append(item)

        # Reset run-state for a fresh dry-run
        self._running = False
        self._done_count = 0
        self._total = len(self._tasks)
        self._set_running_mode(False)
        self._refresh_header_text()
        self._sync_body_visibility()

    def toggle_collapse(self) -> None:
        if not self._tasks:
            return
        self._expanded = not self._expanded
        self._sync_body_visibility()

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
    def on_run_started(self) -> None:
        self._running = True
        self._run_start = time.monotonic()
        self._done_count = 0
        if self._total <= 0:
            self._total = max(1, len(self._tasks))
        self._set_running_mode(True)
        self._progress_bar.setValue(0)
        self._refresh_header_text()

    def on_run_finished(self, result=None) -> None:
        if result is not None and str(getattr(result, "status", "")) == "blocked":
            blocked = tuple(getattr(result, "blocked", ()) or ())
            message = str(blocked[0]) if blocked else "运行意外结束"
            for idx, icon in enumerate(tuple(self._icons)):
                if icon == _ICON_RUNNING:
                    self._update_row(idx, _ICON_FAILED, tooltip=message)
                    if idx not in self._terminal_indices:
                        self._terminal_indices.add(idx)
                        self._done_count += 1
            total = self._total or len(self._tasks)
            if total > 0:
                pct = int(round(self._done_count * 100.0 / total))
                self._progress_bar.setValue(max(0, min(100, pct)))
        elif result is not None:
            self._apply_result_warning_tooltips(result)
        self._running = False
        self._set_running_mode(False)
        self._refresh_header_text()

    def _apply_result_warning_tooltips(self, result) -> None:
        """Attach per-item (or run-level) warnings to completed rows.

        Consumer-only: does not invent progress events. Failed/cancelled
        tooltips already set by ``on_event`` are left alone.
        """
        from .preview_dialog import format_batch_run_warnings

        items = list(getattr(result, "items", None) or ())
        for idx, task in enumerate(self._tasks):
            if not (0 <= idx < len(self._icons)):
                continue
            if self._icons[idx] not in (_ICON_DONE, _ICON_RESUMED, _ICON_SKIPPED):
                continue
            if self._tooltips[idx]:
                continue
            fname, sig, method = task
            matched = None
            for item in items:
                if (
                    str(getattr(item, "file_name", "") or "") == str(fname)
                    and str(getattr(item, "signal", "") or "") == str(sig)
                    and str(getattr(item, "method", "") or "") == str(method)
                ):
                    matched = item
                    break
            if matched is None and idx < len(items):
                matched = items[idx]
            raw_warnings = (
                getattr(matched, "warnings", None) if matched is not None else None
            )
            if not raw_warnings:
                raw_warnings = getattr(result, "warnings", None) or ()
            text = format_batch_run_warnings(raw_warnings, style="block")
            if text:
                self._update_row(idx, self._icons[idx], tooltip=text)

    def on_event(self, event: BatchProgressEvent) -> None:
        kind = event.kind
        # task_index in events is 1-based (per BatchRunner.run loop)
        idx = (event.task_index or 0) - 1
        if kind == "task_started":
            if 0 <= idx < len(self._icons):
                self._update_row(idx, _ICON_RUNNING)
            self._update_progress(event, completed_inc=False)
        elif kind == "task_done":
            self._finish_task(idx, _ICON_DONE, event)
        elif kind == "task_failed":
            self._finish_task(
                idx, _ICON_FAILED, event,
                tooltip=event.error or event.message or "",
            )
        elif kind == "task_cancelled":
            self._finish_task(
                idx, _ICON_CANCELLED, event,
                tooltip=event.message or "已取消",
            )
        elif kind == "task_skipped":
            self._finish_task(
                idx, _ICON_SKIPPED, event,
                tooltip=event.message or "已跳过",
            )
        elif kind == "task_resumed":
            self._finish_task(
                idx, _ICON_RESUMED, event,
                tooltip=event.message or "已恢复",
            )
        elif kind == "run_finished":
            # Final ETA cleanup
            self._eta_label.setText("")
            self._refresh_header_text()

    def _finish_task(self, idx, icon, event, *, tooltip="") -> None:
        if not (0 <= idx < len(self._icons)):
            self._update_progress(event, completed_inc=False)
            return
        self._update_row(idx, icon, tooltip=tooltip)
        self._artifact_paths[idx] = (
            str(event.data_path or ""), str(event.image_path or ""),
        )
        if idx not in self._terminal_indices:
            self._terminal_indices.add(idx)
            self._done_count += 1
        self._update_progress(event, completed_inc=True)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        idx = self._body.row(item)
        if not (0 <= idx < len(self._artifact_paths)):
            return
        data_path, image_path = self._artifact_paths[idx]
        path = image_path or data_path
        if path:
            self.artifactOpenRequested.emit(path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _set_running_mode(self, running: bool) -> None:
        self._idle_label.setVisible(not running)
        self._progress_label.setVisible(running)
        self._progress_bar.setVisible(running)
        self._eta_label.setVisible(running)

    def _sync_body_visibility(self) -> None:
        has_tasks = bool(self._tasks)
        body_visible = has_tasks and self._expanded
        self._body.setVisible(body_visible)
        self._toggle_btn.setEnabled(has_tasks)
        self._toggle_btn.setText("▾" if body_visible else "▸")
        self.updateGeometry()

    def _refresh_header_text(self) -> None:
        if self._running:
            total = self._total or 0
            self._progress_label.setText(f"进度 {self._done_count}/{total}")
            # ETA — only meaningful after the first completed task.
            if self._done_count > 0 and total > self._done_count:
                elapsed = max(time.monotonic() - self._run_start, 0.0)
                avg = elapsed / max(self._done_count, 1)
                remaining = avg * (total - self._done_count)
                self._eta_label.setText(f"~{int(round(remaining))}s 剩余")
            else:
                self._eta_label.setText("")
        else:
            n = len(self._tasks)
            outputs = (
                n * self._outputs_per_task
                if self._artifact_count is None else self._artifact_count
            )
            self._idle_label.setText(f"{n} 任务待执行 · {outputs} 输出")

    def _update_row(
        self,
        idx: int,
        icon: str,
        tooltip: str | None = None,
    ) -> None:
        self._icons[idx] = icon
        if tooltip is not None:
            self._tooltips[idx] = tooltip
        fname, sig, method = self._tasks[idx]
        item = self._items[idx]
        item.setText(self._format_row(icon, fname, sig, method))
        if self._tooltips[idx]:
            item.setToolTip(self._tooltips[idx])
        else:
            item.setToolTip("")

    def _update_progress(
        self,
        event: BatchProgressEvent,
        *,
        completed_inc: bool,  # noqa: ARG002 (kept for clarity at call site)
    ) -> None:
        total = event.total or self._total or len(self._tasks)
        if total <= 0:
            self._progress_bar.setValue(0)
        else:
            pct = int(round(self._done_count * 100.0 / total))
            self._progress_bar.setValue(max(0, min(100, pct)))
        self._total = total
        self._refresh_header_text()

    @staticmethod
    def _format_row(icon: str, fname: str, sig: str, method: str) -> str:
        return f"{icon}  {fname} · {sig} · {method}"
