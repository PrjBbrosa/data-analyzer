"""Idle analysis-page preload and foreground readiness scheduling (Task 3).

Owns only: pending queue, one-shot timer, interaction quiet window, and
shutdown/generation state. Page readiness stays on ``AnalysisSectionPage``;
ChartStack still owns bind; View/Inspector/AnalysisContext keep user state.

Idle preload never changes Section/View, selection, dirty, or camera, and
never runs analysis compute or file IO. Foreground consumers call
:meth:`request_ready` (or ChartStack.ensure directly) — busy yield only
blocks *optional* idle steps.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from PyQt5.QtCore import QEvent, QObject, QTimer, Qt
from PyQt5.QtWidgets import QApplication

logger = logging.getLogger(__name__)

ENV_DISABLE_IDLE_PRELOAD = "TRACELAB_DISABLE_IDLE_PRELOAD"
ENV_EAGER_ANALYSIS_CHARTS = "TRACELAB_EAGER_ANALYSIS_CHARTS"

DEFAULT_PRELOAD_ORDER = ("fft", "fft_time", "frf", "order")
INPUT_QUIET_MS = 200
STEP_GAP_MS = 25
# First kick after the window has had a chance to paint / accept input.
START_DELAY_MS = 0


def _env_truthy(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def idle_preload_disabled() -> bool:
    """Dev diagnostic: skip automatic idle preload (explicit ensure still works)."""
    return _env_truthy(ENV_DISABLE_IDLE_PRELOAD)


def eager_analysis_charts() -> bool:
    """Dev diagnostic: construct analysis charts at ChartStack init (eager)."""
    return _env_truthy(ENV_EAGER_ANALYSIS_CHARTS)


class StartupCoordinator(QObject):
    """MainWindow-owned scheduler for deferred analysis chart pages."""

    def __init__(self, window, *, parent=None):
        super().__init__(parent if parent is not None else window)
        self._window = window
        self._closed = False
        self._started = False
        self._idle_enabled = not idle_preload_disabled()
        self._queue: list[str] = []
        self._queued: set[str] = set()
        self._generation = 0
        self._last_activity_mono = 0.0
        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._on_step_timer)
        self._pending_callbacks: dict[str, list[tuple[int, Callable]]] = {}
        self._foreground: set[str] = set()
        self._last_step_ms: Optional[float] = None
        self._app_filter_installed = False

    # -- public ------------------------------------------------------------
    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def last_step_ms(self) -> Optional[float]:
        """Most recent whole-page ensure duration (ms), or None. Not a Windows budget gate."""
        return self._last_step_ms

    def pending_sections(self) -> list[str]:
        return list(self._queue)

    def start(self) -> None:
        """Arm idle preload after the first interactive event-loop turn.

        Preload completion is never treated as 'app available'.
        """
        if self._closed or self._started:
            return
        self._started = True
        self._install_activity_filter()
        self.note_activity()
        if not self._idle_enabled:
            return
        stack = getattr(self._window, "chart_stack", None)
        if stack is None or not getattr(stack, "_defer_analysis_charts", False):
            return
        for section in DEFAULT_PRELOAD_ORDER:
            self._enqueue(section, front=False)
        self._schedule(START_DELAY_MS)

    def shutdown(self) -> None:
        """Cancel queue and forbid further callbacks (window closing)."""
        if self._closed:
            return
        self._closed = True
        self._step_timer.stop()
        self._queue.clear()
        self._queued.clear()
        self._pending_callbacks.clear()
        self._foreground.clear()
        self._remove_activity_filter()

    def invalidate_session(self) -> None:
        """Drop pending on_ready closures after project A→B / session reset.

        Prepared charts may remain; only generation-gated callbacks are voided.
        """
        self._generation += 1
        self._pending_callbacks.clear()
        self._foreground.clear()

    def prioritize(self, section: str) -> None:
        """User-requested section jumps to the front of the idle queue."""
        section = str(section)
        if section not in DEFAULT_PRELOAD_ORDER:
            return
        if self._page_ready(section):
            self._drop_from_queue(section)
            return
        self._enqueue(section, front=True)
        if self._started and not self._closed and self._idle_enabled:
            self._schedule(0)

    def request_ready(
        self,
        section: str,
        on_ready: Optional[Callable[[str], None]] = None,
        *,
        foreground: bool = False,
    ) -> None:
        """Ensure ``section`` is ready; optional callback when it becomes ready.

        ``foreground=True`` bypasses idle busy/quiet yield so restore/export/
        UltraView/mode-entry dependencies are not starved by ``restore=busy``.
        Does not block with nested event loops — schedules a one-shot step.
        """
        section = str(section)
        if self._closed:
            return
        if self._page_ready(section):
            if on_ready is not None:
                on_ready(section)
            return
        if on_ready is not None:
            self._pending_callbacks.setdefault(section, []).append(
                (self._generation, on_ready)
            )
        if foreground:
            self._foreground.add(section)
        self._enqueue(section, front=True)
        if not self._started:
            # Explicit consumers may run before start(); still serve them.
            self._started = True
            self._install_activity_filter()
        self._schedule(0)

    def note_activity(self) -> None:
        self._last_activity_mono = time.monotonic()

    # -- event filter (interaction quiet window) ---------------------------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if self._closed:
            return False
        et = event.type()
        if et in (
            QEvent.KeyPress,
            QEvent.KeyRelease,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonDblClick,
            QEvent.Wheel,
            QEvent.TabletPress,
        ):
            self.note_activity()
        elif et == QEvent.MouseMove:
            buttons = getattr(event, "buttons", None)
            if callable(buttons) and int(buttons()) != 0:
                self.note_activity()
        return False

    # -- internals ---------------------------------------------------------
    def _install_activity_filter(self) -> None:
        if self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._app_filter_installed = True

    def _remove_activity_filter(self) -> None:
        if not self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._app_filter_installed = False

    def _enqueue(self, section: str, *, front: bool) -> None:
        if section in self._queued:
            if front and self._queue and self._queue[0] != section:
                self._queue = [s for s in self._queue if s != section]
                self._queue.insert(0, section)
            return
        if self._page_ready(section):
            return
        self._queued.add(section)
        if front:
            self._queue.insert(0, section)
        else:
            self._queue.append(section)

    def _drop_from_queue(self, section: str) -> None:
        if section in self._queued:
            self._queued.discard(section)
            self._queue = [s for s in self._queue if s != section]

    def _schedule(self, delay_ms: int) -> None:
        if self._closed:
            return
        if self._step_timer.isActive():
            self._step_timer.stop()
        self._step_timer.start(max(0, int(delay_ms)))

    def _on_step_timer(self) -> None:
        if self._closed:
            return
        if not self._queue:
            self._maybe_mark_preload_complete()
            return

        section = self._queue[0]
        foreground = section in self._foreground

        if not foreground and self._should_yield_idle():
            # Never 0 ms-spin while busy; wait for quiet + idle gap.
            self._schedule(max(INPUT_QUIET_MS, STEP_GAP_MS))
            return

        self._queue.pop(0)
        self._queued.discard(section)
        self._foreground.discard(section)

        if self._page_ready(section):
            self._fire_callbacks(section)
            self._schedule(STEP_GAP_MS if self._queue else 0)
            return

        stack = getattr(self._window, "chart_stack", None)
        if stack is None:
            return
        t0 = time.perf_counter()
        try:
            stack.ensure_analysis_page_ready(section)
        except Exception as exc:
            logger.exception(
                "startup preload ensure failed for section=%s: %s", section, exc,
            )
            # Leave page in failed readiness (page owner); no auto infinite retry.
            self._schedule(STEP_GAP_MS if self._queue else 0)
            return
        finally:
            self._last_step_ms = (time.perf_counter() - t0) * 1000.0

        try:
            from mf4_analyzer.startup_timing import mark_page_ready

            mark_page_ready(section, step_ms=self._last_step_ms)
        except Exception:
            pass

        self._fire_callbacks(section)
        if self._queue:
            self._schedule(STEP_GAP_MS)
        else:
            self._maybe_mark_preload_complete()

    def _fire_callbacks(self, section: str) -> None:
        pending = self._pending_callbacks.pop(section, [])
        if not pending or self._closed:
            return
        gen = self._generation
        for cb_gen, callback in pending:
            if cb_gen != gen:
                continue
            try:
                callback(section)
            except Exception:
                logger.exception(
                    "startup ready callback failed for section=%s", section,
                )

    def _maybe_mark_preload_complete(self) -> None:
        if self._closed or self._queue:
            return
        # All default sections ready (or failed/skipped) — optional timing mark.
        try:
            from mf4_analyzer.startup_timing import mark_preload_complete

            mark_preload_complete(
                last_step_ms=self._last_step_ms,
                order=list(DEFAULT_PRELOAD_ORDER),
            )
        except Exception:
            pass

    def _page_ready(self, section: str) -> bool:
        stack = getattr(self._window, "chart_stack", None)
        if stack is None:
            return False
        page = stack.peek_analysis_page(section)
        if page is None:
            return False
        return bool(page.is_ready())

    def _should_yield_idle(self) -> bool:
        """True when optional idle must not start a new page construct."""
        window = self._window
        if window is None:
            return True

        # Input quiet window.
        quiet_s = INPUT_QUIET_MS / 1000.0
        if (time.monotonic() - self._last_activity_mono) < quiet_s:
            return True

        app = QApplication.instance()
        if app is not None:
            if app.activeModalWidget() is not None:
                return True
            if int(app.mouseButtons()) != Qt.NoButton:
                return True

        gate = getattr(window, "_time_render", None)
        if gate is not None and getattr(gate, "busy", False):
            return True

        in_restore = getattr(window, "_project_session_in_restore", None)
        if callable(in_restore) and in_restore():
            return True
        if getattr(window, "_opening_project", False):
            return True
        if getattr(window, "_restoring_project", False):
            return True

        jobs = getattr(window, "_analysis_jobs", None)
        if jobs is not None:
            for section in DEFAULT_PRELOAD_ORDER:
                try:
                    if jobs.is_busy(section):
                        return True
                except Exception:
                    pass

        # Import / compute progress also means the GUI is occupied.
        if getattr(window, "_active_compute_progress_token", None) is not None:
            return True

        return False
