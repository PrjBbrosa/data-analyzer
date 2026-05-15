"""Recorder backends for the Acquisition Cockpit capture core.

Spec §Recorder Backend.

The ``RecorderBackend`` interface is intentionally minimal: ``start``,
``stop``, ``status``, ``poll`` (drain newly-available samples), and
``last_frame_monotonic()`` for the watchdog rule in §Health Snapshot.

Three implementations:

- ``FakeRecorderBackend`` — deterministic sine + ramp samples for ≥ 3
  signals. macOS-friendly, used by CLI ``--backend fake`` and by tests.
- ``ReplayRecorderBackend`` — emits samples without Vector deps. Default
  source is a fully-generated synthetic stream so the backend works
  without a checked-in MF4; ``source_samples=`` can be supplied to
  replay an explicit ``[(ts, channel, value), ...]`` script.
- ``VectorXcpRecorderBackend`` — lazy-imports ``python-can`` / ``pyxcp``
  only inside its own constructor; on macOS / Linux it raises a clear
  ``RuntimeError("Vector/XCP backend is Windows-only ...")``. Stage 8
  fleshes it out.

The capture core MUST NOT import python-can or pyxcp at module load —
the lazy imports below preserve macOS-host import safety.
"""

from __future__ import annotations

import math
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


@dataclass
class BackendStatus:
    started: bool
    rx_count: int
    bus_error_count: int
    queue_overflow_count: int
    last_error: str | None = None


@dataclass(frozen=True)
class ReplaySource:
    """MF4-derived replay payload for :class:`ReplayRecorderBackend`."""

    path: Path
    selected: tuple[SelectedMeasurement, ...]
    source_samples: list[tuple[str, float, float]]
    duration_s: float


# ---------------------------------------------------------------------------
# Interface.
# ---------------------------------------------------------------------------


class RecorderBackend(ABC):
    """Pull-based recorder interface.

    Controllers call ``poll()`` on a tight loop to drain available
    samples. This keeps the capture core single-threaded and Qt-free.
    """

    @abstractmethod
    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        """Initialize state for capture. Idempotent: re-calling resets."""

    @abstractmethod
    def stop(self) -> BackendStatus:
        """Stop capture and return final status. Safe to call from any state."""

    @abstractmethod
    def poll(self) -> list[tuple[str, float, float]]:
        """Return all samples produced since the last ``poll()``.

        Each tuple is ``(channel_name, timestamp_s, value)``. ``timestamp_s``
        is in seconds from the start of the recording (not wall-clock).
        """

    @abstractmethod
    def status(self) -> BackendStatus:
        """Return a non-destructive status snapshot."""

    @abstractmethod
    def last_frame_monotonic(self) -> float | None:
        """``time.monotonic()`` of the most-recent sample, or ``None``."""


# ---------------------------------------------------------------------------
# Fake backend — deterministic synthetic stream.
# ---------------------------------------------------------------------------


class FakeRecorderBackend(RecorderBackend):
    """Deterministic synthetic samples for macOS tests / CLI demos.

    Each ``poll`` returns samples covering ``time.monotonic() - last_poll``
    wall-clock seconds, dialled to ``samples_per_second`` per channel.
    The waveform per channel:

    - channel 0: sine at 1 Hz, amplitude 100, offset 1000 (rpm-ish).
    - channel 1: linear ramp 0..1 over each second (throttle-ish).
    - channel 2: square wave at 0.5 Hz, ±5 (steering-ish).
    - additional channels: scaled sine with phase offset per index.

    Forcing warning states: ``force_bus_error()`` and ``force_overflow()``
    increment the counters used by ``RecorderHealth``.
    """

    def __init__(self, *, samples_per_second: float = 100.0) -> None:
        if samples_per_second <= 0:
            raise ValueError("samples_per_second must be positive")
        self._sps = float(samples_per_second)
        self._selected: tuple[SelectedMeasurement, ...] = ()
        self._started = False
        self._t_start_monotonic: float | None = None
        # Tracks ``time.monotonic()`` of the most recent sample we've
        # emitted; ``poll`` synthesizes samples up to ``now``.
        self._emit_cursor: float | None = None
        self._rx_count = 0
        self._bus_error_count = 0
        self._queue_overflow_count = 0
        self._last_frame_monotonic: float | None = None
        self._last_error: str | None = None

    # -- interface -----------------------------------------------------

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        if not selected:
            raise ValueError("FakeRecorderBackend requires ≥ 1 selected measurement")
        self._selected = tuple(selected)
        self._started = True
        now = time.monotonic()
        self._t_start_monotonic = now
        self._emit_cursor = now
        self._rx_count = 0
        self._bus_error_count = 0
        self._queue_overflow_count = 0
        self._last_frame_monotonic = None
        self._last_error = None

    def stop(self) -> BackendStatus:
        self._started = False
        return self.status()

    def poll(self) -> list[tuple[str, float, float]]:
        if not self._started or self._t_start_monotonic is None or self._emit_cursor is None:
            return []
        now = time.monotonic()
        elapsed = now - self._emit_cursor
        if elapsed <= 0:
            return []
        # Number of sample-ticks to emit per channel this poll.
        n = max(1, int(elapsed * self._sps))
        dt = 1.0 / self._sps
        out: list[tuple[str, float, float]] = []
        for k in range(n):
            sample_monotonic = self._emit_cursor + (k + 1) * dt
            if sample_monotonic > now:
                break
            t = sample_monotonic - self._t_start_monotonic
            for idx, m in enumerate(self._selected):
                out.append((m.name, t, self._value_for(idx, t)))
            self._last_frame_monotonic = sample_monotonic
        self._emit_cursor = now
        self._rx_count += len(out)
        return out

    def status(self) -> BackendStatus:
        return BackendStatus(
            started=self._started,
            rx_count=self._rx_count,
            bus_error_count=self._bus_error_count,
            queue_overflow_count=self._queue_overflow_count,
            last_error=self._last_error,
        )

    def last_frame_monotonic(self) -> float | None:
        return self._last_frame_monotonic

    # -- warning-state hooks (for tests) ------------------------------

    def force_bus_error(self, count: int = 1) -> None:
        self._bus_error_count += int(count)

    def force_overflow(self, count: int = 1) -> None:
        self._queue_overflow_count += int(count)

    def force_error(self, message: str) -> None:
        self._last_error = message

    # -- waveform shapes -----------------------------------------------

    @staticmethod
    def _value_for(channel_index: int, t: float) -> float:
        if channel_index == 0:
            return 1000.0 + 100.0 * math.sin(2.0 * math.pi * 1.0 * t)
        if channel_index == 1:
            return (t % 1.0)  # 0..1 ramp each second
        if channel_index == 2:
            return 5.0 if math.sin(2.0 * math.pi * 0.5 * t) >= 0 else -5.0
        # Higher channels: 1 Hz sine with channel-dependent phase/amplitude.
        amp = 10.0 + channel_index
        phase = channel_index * math.pi / 4.0
        return amp * math.sin(2.0 * math.pi * 1.0 * t + phase)


# ---------------------------------------------------------------------------
# Replay backend — scripted stream, no Vector deps.
# ---------------------------------------------------------------------------


class ReplayRecorderBackend(RecorderBackend):
    """Replay a fixed sample script at wall-clock rate.

    If ``source_samples`` is supplied, it is consumed in order with
    each tuple's ``timestamp_s`` interpreted as "seconds from session
    start". Samples are released as ``time.monotonic() - t_start``
    crosses each timestamp.

    If ``source_samples`` is omitted, the backend generates a 2-second
    deterministic stream for the selected measurements (1 Hz sine /
    1 sps each, similar to ``FakeRecorderBackend`` but capped). This
    keeps the backend usable in tests without checking in an MF4
    fixture.

    ``speed_multiplier`` scales replay time: ``2.0`` emits twice as
    fast as the source timestamps; ``0.5`` emits at half speed.
    """

    def __init__(
        self,
        *,
        source_samples: Iterable[tuple[str, float, float]] | None = None,
        synth_duration_s: float = 2.0,
        synth_rate_hz: float = 50.0,
        speed_multiplier: float = 1.0,
    ) -> None:
        self._source = None if source_samples is None else list(source_samples)
        self._synth_duration = float(synth_duration_s)
        self._synth_rate = float(synth_rate_hz)
        self._speed_multiplier = 1.0
        self.speed_multiplier = speed_multiplier
        self._cursor = 0
        self._started = False
        self._t_start: float | None = None
        self._paused_at: float | None = None
        self._rx_count = 0
        self._bus_error_count = 0
        self._queue_overflow_count = 0
        self._last_frame_monotonic: float | None = None
        self._selected: tuple[SelectedMeasurement, ...] = ()

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        if not selected:
            raise ValueError("ReplayRecorderBackend requires ≥ 1 selected measurement")
        self._selected = tuple(selected)
        if self._source is None:
            self._source = self._synthesize(self._selected)
        self._cursor = 0
        self._started = True
        self._t_start = time.monotonic()
        self._paused_at = None
        self._rx_count = 0
        self._last_frame_monotonic = None

    def stop(self) -> BackendStatus:
        self._started = False
        self._paused_at = None
        return self.status()

    def poll(self) -> list[tuple[str, float, float]]:
        if not self._started or self._t_start is None or self._source is None:
            return []
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        now_rel = (now - self._t_start) * self._speed_multiplier
        out: list[tuple[str, float, float]] = []
        while self._cursor < len(self._source):
            ch, ts, val = self._source[self._cursor]
            if ts > now_rel:
                break
            out.append((ch, ts, val))
            self._cursor += 1
        if out:
            self._rx_count += len(out)
            self._last_frame_monotonic = time.monotonic()
        return out

    def status(self) -> BackendStatus:
        return BackendStatus(
            started=self._started,
            rx_count=self._rx_count,
            bus_error_count=self._bus_error_count,
            queue_overflow_count=self._queue_overflow_count,
            last_error=None,
        )

    def last_frame_monotonic(self) -> float | None:
        return self._last_frame_monotonic

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    @speed_multiplier.setter
    def speed_multiplier(self, value: float) -> None:
        value = float(value)
        if value <= 0:
            raise ValueError("speed_multiplier must be positive")
        self._speed_multiplier = value

    @property
    def finished(self) -> bool:
        return self._source is not None and self._cursor >= len(self._source)

    def pause(self) -> None:
        if self._started and self._paused_at is None:
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        if self._started and self._paused_at is not None and self._t_start is not None:
            paused_for = time.monotonic() - self._paused_at
            self._t_start += paused_for
            self._paused_at = None

    # -- MF4 source -----------------------------------------------------

    @classmethod
    def source_from_mf4(cls, path: str | Path) -> ReplaySource:
        """Load an existing MF4 into sorted replay samples.

        This intentionally reuses :meth:`DataLoader.load_mf4` so replay
        follows the same asammdf-backed path as Analyzer file loading.
        Master time columns are excluded from emitted signal samples.
        """
        from mf4_analyzer.io.loader import DataLoader

        source_path = Path(path)
        df, channels, units = DataLoader.load_mf4(str(source_path))
        if "Time" in df.columns:
            time_values = [float(v) for v in df["Time"].tolist()]
        else:
            first_column = df.columns[0]
            time_values = [float(v) for v in df[first_column].tolist()]
        channel_names = [
            ch
            for ch in channels
            if ch not in {"Time", "time"} and ch in df.columns
        ]
        if not channel_names:
            raise ValueError(f"no replayable numeric channels in {source_path}")

        channel_order = {name: idx for idx, name in enumerate(channel_names)}
        source_samples: list[tuple[str, float, float]] = []
        for row_idx, ts in enumerate(time_values):
            if not math.isfinite(ts):
                continue
            for ch in channel_names:
                value = float(df[ch].iloc[row_idx])
                if math.isfinite(value):
                    source_samples.append((ch, ts, value))
        source_samples.sort(key=lambda item: (item[1], channel_order[item[0]]))
        if not source_samples:
            raise ValueError(f"no finite replay samples in {source_path}")

        selected = tuple(
            SelectedMeasurement(name=ch, unit=str(units.get(ch, "") or ""))
            for ch in channel_names
        )
        duration_s = max(ts for _ch, ts, _value in source_samples)
        return ReplaySource(
            path=source_path,
            selected=selected,
            source_samples=source_samples,
            duration_s=float(duration_s),
        )

    # -- synthetic source ----------------------------------------------

    def _synthesize(
        self, selected: Sequence[SelectedMeasurement]
    ) -> list[tuple[str, float, float]]:
        n = max(1, int(self._synth_duration * self._synth_rate))
        dt = 1.0 / self._synth_rate
        out: list[tuple[str, float, float]] = []
        for k in range(n):
            t = (k + 1) * dt
            for idx, m in enumerate(selected):
                value = math.sin(2.0 * math.pi * 1.0 * t + idx) * (10.0 + idx)
                out.append((m.name, t, value))
        return out


# ---------------------------------------------------------------------------
# Vector/XCP stub — lazy-imports python-can/pyxcp only inside __init__.
# ---------------------------------------------------------------------------


class VectorXcpRecorderBackend(RecorderBackend):
    """Lazy / Windows-only Vector + XCP recorder.

    Stage 2 ships only the stub: importing this module on macOS or Linux
    does NOT import ``python-can`` or ``pyxcp`` — the actual import
    happens inside ``__init__``, and on non-Windows hosts ``__init__``
    raises a clear ``RuntimeError`` so the CLI surfaces it cleanly.

    Stage 8 replaces the body with real DAQ wiring after the Windows +
    Vector + powered ECU evidence is appended to ``P0_Runbook.md``.
    """

    def __init__(self, **kwargs: Any) -> None:
        if not sys.platform.startswith("win"):
            raise RuntimeError(
                "Vector/XCP backend is Windows-only and requires Vector hardware. "
                "Use --backend fake or --backend replay on macOS / Linux."
            )
        # Lazy imports: only happen on Windows.
        try:
            import can  # noqa: F401  - python-can
        except ImportError as exc:  # pragma: no cover - Windows-only
            raise RuntimeError(
                "python-can is required for the Vector/XCP backend; install python-can"
            ) from exc
        try:
            import pyxcp  # noqa: F401
        except ImportError as exc:  # pragma: no cover - Windows-only
            raise RuntimeError(
                "pyxcp is required for the Vector/XCP backend; install pyxcp"
            ) from exc
        # Stage 8 will wire the actual session here.
        raise NotImplementedError(
            "VectorXcpRecorderBackend body is gated on P0 hardware evidence "
            "(Stage 8). See docs/analyzer/acquisition/P0_Runbook.md."
        )

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> BackendStatus:  # pragma: no cover
        raise NotImplementedError

    def poll(self) -> list[tuple[str, float, float]]:  # pragma: no cover
        raise NotImplementedError

    def status(self) -> BackendStatus:  # pragma: no cover
        raise NotImplementedError

    def last_frame_monotonic(self) -> float | None:  # pragma: no cover
        raise NotImplementedError
