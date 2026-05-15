"""Bounded ring buffer with watermark transitions.

Spec §Threshold Contract (ring buffer rows).

The capture core MUST stay Qt-free (Stage 2 brief), so this module ships
its own lightweight observer ``Signal`` (``connect`` / ``emit``). Stage 4's
Qt window adapts it to ``pyqtSignal`` by subscribing a slot via
``watermark_changed.connect``. The contract is identical: subscribers are
called synchronously with a single ``WatermarkLevel`` argument.

The "auto-stop after 5 s of >=95%" rule needs an external time source so
the capture controller drives the sustain check; the ring buffer itself
only reports level transitions and exposes a ``red_drop_since`` timestamp
that the controller polls.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Literal

from mf4_analyzer.acquisition_capture import thresholds

WatermarkLevel = Literal["green", "yellow_low", "red", "red_drop", "red_drop_sustained"]

# Order matters: transitions emit when this index changes.
_LEVEL_ORDER: tuple[WatermarkLevel, ...] = (
    "green",
    "yellow_low",
    "red",
    "red_drop",
    "red_drop_sustained",
)


class Signal:
    """Tiny synchronous observer with a ``connect`` / ``emit`` API.

    Mirrors enough of ``pyqtSignal`` that Stage 4 can bridge with one
    adapter. Connect is thread-safe (lock-guarded list mutation);
    emission is synchronous and re-raises subscriber exceptions so bugs
    don't get swallowed.
    """

    def __init__(self) -> None:
        self._subs: list[Callable[..., None]] = []
        self._lock = threading.Lock()

    def connect(self, slot: Callable[..., None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(slot)

        def _disconnect() -> None:
            with self._lock:
                try:
                    self._subs.remove(slot)
                except ValueError:
                    pass

        return _disconnect

    def emit(self, *args, **kwargs) -> None:
        with self._lock:
            subs = list(self._subs)
        for slot in subs:
            slot(*args, **kwargs)


def _watermark_for(fill_pct: float) -> WatermarkLevel:
    if fill_pct < thresholds.RING_BUFFER_GREEN_MAX_PCT:
        return "green"
    if fill_pct < thresholds.RING_BUFFER_YELLOW_LOW_MAX_PCT:
        return "yellow_low"
    if fill_pct < thresholds.RING_BUFFER_RED_MAX_PCT:
        return "red"
    if fill_pct < thresholds.RING_BUFFER_RED_DROP_MAX_PCT:
        # 85..95 — drop oldest sample, count in dropped_frames (caller).
        return "red_drop"
    return "red_drop_sustained"


class RingBuffer:
    """Fixed-capacity ring with watermark signal and drop accounting.

    Items are arbitrary tuples (the capture path uses
    ``(monotonic_ts, channel_name, value)``); the buffer is byte-shape
    agnostic. ``put`` and ``drain`` are thread-safe.

    Watermark transitions emit ``watermark_changed`` exactly once per
    band crossing. Going 49 -> 51 emits ``yellow_low``; 51 -> 49 emits
    ``green``; 49 -> 49 emits nothing.
    """

    def __init__(self, capacity: int = thresholds.DEFAULT_RING_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self._capacity = capacity
        self._items: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._dropped_frames = 0
        self._max_depth = 0
        self._level: WatermarkLevel = "green"
        self._red_drop_since: float | None = None
        self.watermark_changed = Signal()

    # ------------------------------------------------------------------
    # Basic queue interface.
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def level_pct(self) -> float:
        with self._lock:
            return 100.0 * len(self._items) / self._capacity

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def max_depth(self) -> int:
        return self._max_depth

    @property
    def watermark(self) -> WatermarkLevel:
        return self._level

    @property
    def red_drop_since(self) -> float | None:
        """Monotonic time we first entered ``red_drop`` (or higher), or None."""
        return self._red_drop_since

    def red_drop_sustained_for(self, *, now: float | None = None) -> float:
        """Seconds the buffer has been in ``red_drop`` continuously.

        Returns 0.0 if the buffer is not currently in ``red_drop``.
        """
        if self._red_drop_since is None:
            return 0.0
        if now is None:
            now = time.monotonic()
        return max(0.0, now - self._red_drop_since)

    # ------------------------------------------------------------------
    # Producer / consumer.
    # ------------------------------------------------------------------

    def put(self, item) -> None:
        dropped = False
        with self._lock:
            if len(self._items) == self._capacity:
                # Drop oldest. deque.maxlen would do this implicitly,
                # but we want to count drops explicitly.
                self._items.popleft()
                self._dropped_frames += 1
                dropped = True
            self._items.append(item)
            depth = len(self._items)
            if depth > self._max_depth:
                self._max_depth = depth
            fill_pct = 100.0 * depth / self._capacity
        self._update_level(fill_pct)
        # Mark dropped silently — controller reads ``dropped_frames``.
        del dropped  # documented for readers

    def drain(self) -> list:
        """Atomically pop everything and reset the level to ``green``."""
        with self._lock:
            items = list(self._items)
            self._items.clear()
        self._update_level(0.0)
        return items

    # ------------------------------------------------------------------
    # Internal level transitions.
    # ------------------------------------------------------------------

    def _update_level(self, fill_pct: float) -> None:
        new_level = _watermark_for(fill_pct)
        if new_level == self._level:
            return
        previous = self._level
        self._level = new_level
        # Track ``red_drop`` entry / exit time for the 5 s sustain rule.
        red_drop_active = new_level in {"red_drop", "red_drop_sustained"}
        prev_red_drop = previous in {"red_drop", "red_drop_sustained"}
        if red_drop_active and not prev_red_drop:
            self._red_drop_since = time.monotonic()
        elif not red_drop_active and prev_red_drop:
            self._red_drop_since = None
        self.watermark_changed.emit(new_level)
