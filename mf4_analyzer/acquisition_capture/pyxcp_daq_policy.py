"""Bounded pyxcp DAQ frame policy and deterministic queue diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Any


@dataclass(frozen=True)
class DaqFrame:
    payload: bytes
    arrival_monotonic_s: float
    counter: int
    transport_timestamp: int


@dataclass(frozen=True)
class DaqPolicyDiagnostics:
    frame_depth: int
    frame_high_water: int
    frame_overflow_count: int
    last_frame_monotonic_s: float | None
    # Default preserves compatibility with callers constructing the original
    # four-field snapshot positionally.
    dto_received_count: int = 0


class BoundedDaqPolicy:
    """pyxcp 0.29 ``FrameAcquisitionPolicy``-compatible DAQ ingress.

    ``feed`` must never block the transport listener.  On overflow the oldest
    frame is discarded so preview follows current state; every discard is
    counted and consequently disqualifies a recording acceptance run.
    """

    def __init__(self, *, frame_capacity: int = 4096) -> None:
        if frame_capacity < 1:
            raise ValueError("frame_capacity must be >= 1")
        self.xcp_master: Any | None = None
        self._frames: queue.Queue[DaqFrame] = queue.Queue(maxsize=frame_capacity)
        self._diagnostics_lock = threading.Lock()
        self._dto_received_count = 0
        self._frame_high_water = 0
        self._frame_overflow_count = 0
        self._last_frame_monotonic_s: float | None = None
        self._closed = False

    def feed(self, category: Any, counter: int, timestamp: int, payload: bytes) -> None:
        if self._closed or _category_name(category) != "DAQ":
            return
        arrival = time.monotonic()
        frame = DaqFrame(bytes(payload), arrival, int(counter), int(timestamp))
        overflowed = False
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:  # another consumer won the race
                pass
            else:
                overflowed = True
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                # A producer can win between the drain and retry.  Drop this
                # frame rather than blocking pyxcp's listener.
                overflowed = True
        depth = self._frames.qsize()
        # The queue operations above are strictly non-blocking.  This short
        # metadata critical section makes diagnostics snapshots coherent.
        with self._diagnostics_lock:
            self._dto_received_count += 1
            if overflowed:
                self._frame_overflow_count += 1
            self._last_frame_monotonic_s = arrival
            self._frame_high_water = max(self._frame_high_water, depth)

    def get(self, timeout_s: float = 0.25) -> DaqFrame | None:
        try:
            return self._frames.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def finalize(self) -> None:
        self._closed = True

    def diagnostics(self) -> DaqPolicyDiagnostics:
        with self._diagnostics_lock:
            return DaqPolicyDiagnostics(
                dto_received_count=self._dto_received_count,
                frame_depth=self._frames.qsize(),
                frame_high_water=self._frame_high_water,
                frame_overflow_count=self._frame_overflow_count,
                last_frame_monotonic_s=self._last_frame_monotonic_s,
            )


def _category_name(category: Any) -> str:
    return str(getattr(category, "name", category)).upper()
