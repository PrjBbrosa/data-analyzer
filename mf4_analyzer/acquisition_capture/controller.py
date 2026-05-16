"""CaptureController — single-threaded start/poll/stop/flush orchestrator.

Wires the recorder backend to the ring buffer and the writer, watches
the auto-stop predicates, and produces the ``SessionSummary`` sidecar
on stop.

Stays Qt-free: Stage 4 drives ``poll_step()`` from a ``QTimer``, while
the CLI drives it from a ``while True`` loop. The hot path itself does
no IO; ``finalize`` is the only call that touches disk.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import RecorderBackend
from mf4_analyzer.acquisition_capture.ring_buffer import RingBuffer
from mf4_analyzer.acquisition_capture.session import SessionConfig, SessionSummary
from mf4_analyzer.acquisition_capture.writer import Mf4Writer, Mf4WriterError

logger = logging.getLogger(__name__)


class CaptureController:
    """Drives the capture loop.

    Usage::

        ctrl = CaptureController(config, backend)
        ctrl.start()
        while ctrl.running:
            ctrl.poll_step()
        summary = ctrl.stop()

    The CLI honors ``config.duration_s`` and Ctrl-C; Stage 4 wires
    ``poll_step()`` to a QTimer instead.
    """

    def __init__(
        self,
        config: SessionConfig,
        backend: RecorderBackend,
        *,
        writer: Mf4Writer | None = None,
        ring: RingBuffer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._backend = backend
        self._writer = writer or Mf4Writer(config.output_mf4, config.selected)
        self._ring = ring or RingBuffer(capacity=config.ring_capacity)
        self._clock = clock
        self._running = False
        self._auto_stop = False
        self._t_start: float | None = None
        self._t_stop: float | None = None
        self._warnings: list[str] = []
        self._segments: list[dict[str, object]] = []
        self._current_segment_start: float | None = None
        self._current_segment_label: str | None = None

    # ------------------------------------------------------------------
    # Properties.
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def ring(self) -> RingBuffer:
        return self._ring

    @property
    def writer(self) -> Mf4Writer:
        return self._writer

    @property
    def config(self) -> SessionConfig:
        return self._config

    @property
    def auto_stopped(self) -> bool:
        return self._auto_stop

    @property
    def elapsed_s(self) -> float:
        if self._t_start is None:
            return 0.0
        end = self._t_stop if self._t_stop is not None else self._clock()
        return max(0.0, end - self._t_start)

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            raise RuntimeError("CaptureController already running")
        self._backend.start(self._config.selected)
        self._t_start = self._clock()
        self._t_stop = None
        self._running = True
        self._auto_stop = False
        self._warnings.clear()
        self._segments.clear()
        self._current_segment_start = 0.0
        self._current_segment_label = None

    def poll_step(self) -> int:
        """One iteration of the capture loop.

        Returns the number of samples drained to the writer this step.
        Safe to call when not running (returns 0).
        """
        if not self._running:
            return 0
        # 1. Drain backend into ring buffer.
        new_samples = self._backend.poll()
        for sample in new_samples:
            self._ring.put(sample)
        # 2. Drain ring into writer.
        buffered = self._ring.drain()
        if buffered:
            try:
                self._writer.append_batch(buffered)
            except Mf4WriterError as exc:
                self._warnings.append(f"writer error: {exc}")
                self._auto_stop = True
                self._stop_locked()
                return 0
        # 3. Auto-stop predicates.
        self._check_auto_stop()
        # 4. Duration cap (CLI-side, optional).
        if self._config.duration_s is not None:
            if self.elapsed_s >= self._config.duration_s:
                self._stop_locked()
        # 5. Segment marker (optional).
        if self._config.segment_seconds is not None and self._current_segment_start is not None:
            since_seg = self.elapsed_s - self._current_segment_start
            if since_seg >= self._config.segment_seconds:
                self._close_current_segment(self.elapsed_s)
                self._current_segment_start = self.elapsed_s
                self._current_segment_label = None
        return len(buffered)

    def mark_segment(self, label: str | None = None) -> None:
        """Close the current segment and start a new labeled segment."""
        if not self._running or self._current_segment_start is None:
            return
        now_s = self.elapsed_s
        self._close_current_segment(now_s)
        self._current_segment_start = now_s
        clean_label = label.strip() if label is not None else ""
        self._current_segment_label = clean_label or None

    def stop(self) -> SessionSummary:
        """Stop the backend, drain the ring, finalize the writer.

        Returns the populated ``SessionSummary``. The sidecar JSON is
        written by the caller (CLI / Stage 5 review modal) so callers
        can decide where it lives.
        """
        if self._running:
            self._stop_locked()
        return self._build_summary()

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    def _check_auto_stop(self) -> None:
        sustained = self._ring.red_drop_sustained_for(now=self._clock())
        if sustained >= thresholds.RING_BUFFER_AUTO_STOP_SUSTAIN_S:
            self._warnings.append(
                f"ring buffer ≥ 95% for {sustained:.1f}s — auto-stop"
            )
            self._auto_stop = True
            self._stop_locked()

    def _stop_locked(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            backend_status = self._backend.stop()
        except Exception as exc:  # noqa: BLE001 - keep saving on backend error
            self._warnings.append(f"backend.stop() failed: {exc}")
            backend_status = self._backend.status()
        self._t_stop = self._clock()
        # Final drain.
        final = self._ring.drain()
        if final:
            try:
                self._writer.append_batch(final)
            except Mf4WriterError as exc:
                self._warnings.append(f"final drain failed: {exc}")
        # Finalize MF4. Writer raises Mf4WriterError on disk failure;
        # CLI maps that to non-zero exit.
        if not self._writer.is_closed:
            try:
                self._writer.finalize()
            except Mf4WriterError as exc:
                # Surface to the caller — finalize failure is the one
                # condition where capture is considered failed.
                logger.error("MF4 finalize failed: %s", exc)
                self._warnings.append(f"finalize failed: {exc}")
                raise
        # Close any open segment.
        if self._current_segment_start is not None:
            self._close_current_segment(self.elapsed_s)
            self._current_segment_start = None
            self._current_segment_label = None
        # Pass backend bus/overflow counters through.
        self._backend_final_status = backend_status

    def _close_current_segment(self, end_ts: float) -> None:
        if self._current_segment_start is None:
            return
        segment: dict[str, object] = {
            "start_ts": float(self._current_segment_start),
            "end_ts": float(end_ts),
        }
        if self._current_segment_label is not None:
            segment["label"] = self._current_segment_label
        self._segments.append(segment)

    def _build_summary(self) -> SessionSummary:
        status = getattr(self, "_backend_final_status", None) or self._backend.status()
        return SessionSummary(
            duration_s=float(self.elapsed_s),
            rx_count=int(status.rx_count),
            write_count=int(self._writer.write_count),
            queue_overflow_count=int(status.queue_overflow_count),
            bus_error_count=int(status.bus_error_count),
            dropped_frames=int(self._ring.dropped_frames),
            max_queue_depth=int(self._ring.max_depth),
            segments=list(self._segments),
            output_mf4=str(self._writer.path),
            auto_stop=bool(self._auto_stop),
            # Spec §Persistence Contract: diagnostic strings that used to
            # split between ``problems[]`` and ``warnings[]`` all fold
            # into ``warnings[]`` (single field, same semantics).
            warnings=list(self._warnings),
        )
