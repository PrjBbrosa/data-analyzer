"""Bottom collapsible task list + progress bar for the batch dialog.

Spec §3.5. Header switches between idle (``▾ N 任务待执行 · M 输出``) and
running (``进度 i/N  [progress bar]  ~Ts 剩余``) modes via
``on_run_started`` / ``on_run_finished``. Body is a list of rows — each
row carries an icon (``⏸/⟳/✓/✗/—``), a ``file · signal · method`` label,
and an optional error tooltip.

Driven by ``BatchProgressEvent`` instances forwarded from
``BatchRunnerThread.progress``. ETA computed as
``(now - run_start) / max(done, 1) * (total - done)``.

The widget is deliberately read-only — it emits no signals.
"""
from __future__ import annotations

import time
from typing import Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from ....batch import BatchProgressEvent


# Icon glyphs per spec §3.5
_ICON_PENDING = "⏸"
_ICON_RUNNING = "⟳"
_ICON_DONE = "✓"
_ICON_FAILED = "✗"
_ICON_CANCELLED = "—"


class TaskListWidget(QWidget):
    """Collapsible header + body of per-task rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchTaskList")

        self._tasks: list[tuple[str, str, str]] = []
        self._icons: list[str] = []
        self._tooltips: list[str] = []
        self._items: list[QListWidgetItem] = []
        self._outputs_per_task: int = 0
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
        self._body.setMaximumHeight(180)
        outer.addWidget(self._body, 1)

        # Initialise mode (idle).
        self._set_running_mode(False)
        self._refresh_header_text()

    # ------------------------------------------------------------------
    # Public read-only accessors
    # ------------------------------------------------------------------
    def row_count(self) -> int:
        return len(self._tasks)

    def row_icon(self, idx: int) -> str:
        return self._icons[idx]

    def row_tooltip(self, idx: int) -> str:
        return self._tooltips[idx]

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
    ) -> None:
        """Replace the body rows with the supplied ``(file, signal, method)``
        tuples. Resets all icons to ⏸ and clears tooltips. Idle header text
        is rebuilt from ``len(tasks)`` and ``outputs_per_task``.
        """
        self._tasks = [tuple(t) for t in tasks]
        self._icons = [_ICON_PENDING] * len(self._tasks)
        self._tooltips = [""] * len(self._tasks)
        self._outputs_per_task = int(outputs_per_task)

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

    def toggle_collapse(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText("▾" if self._expanded else "▸")

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

    def on_run_finished(self, result=None) -> None:  # noqa: ARG002 (UI hook)
        self._running = False
        self._set_running_mode(False)
        self._refresh_header_text()

    def on_event(self, event: BatchProgressEvent) -> None:
        kind = event.kind
        # task_index in events is 1-based (per BatchRunner.run loop)
        idx = (event.task_index or 0) - 1
        if kind == "task_started":
            if 0 <= idx < len(self._icons):
                self._update_row(idx, _ICON_RUNNING)
            self._update_progress(event, completed_inc=False)
        elif kind == "task_done":
            if 0 <= idx < len(self._icons):
                self._update_row(idx, _ICON_DONE)
            self._done_count += 1
            self._update_progress(event, completed_inc=True)
        elif kind == "task_failed":
            if 0 <= idx < len(self._icons):
                self._update_row(idx, _ICON_FAILED, tooltip=event.error or "")
            # Failed tasks bump the visible progress (one task off the queue).
            self._done_count += 1
            self._update_progress(event, completed_inc=True)
        elif kind == "task_cancelled":
            if 0 <= idx < len(self._icons):
                self._update_row(idx, _ICON_CANCELLED, tooltip="已取消")
            # Don't bump done count — cancelled tasks weren't run.
            self._update_progress(event, completed_inc=False)
        elif kind == "run_finished":
            # Final ETA cleanup
            self._eta_label.setText("")
            self._refresh_header_text()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _set_running_mode(self, running: bool) -> None:
        self._idle_label.setVisible(not running)
        self._progress_label.setVisible(running)
        self._progress_bar.setVisible(running)
        self._eta_label.setVisible(running)

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
            outputs = n * self._outputs_per_task
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
