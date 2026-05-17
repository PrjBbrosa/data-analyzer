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
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

if TYPE_CHECKING:
    from can_logger.p0.a2l_probe import MeasurementSummary
    from can_logger.p0.ifdata_xcp import IfDataXcp


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
# Vector/XCP backend — lazy-imports python-can/pyxcp only inside __init__.
# ---------------------------------------------------------------------------


class RecorderBackendUnavailableError(RuntimeError):
    """Raised when a backend cannot run on the current host."""


class RecorderStartError(RuntimeError):
    """Raised when backend start-up fails after construction."""


def _import_can():
    import can  # type: ignore[import-not-found]

    return can


def _import_xcp_master():
    from pyxcp.master import Master  # type: ignore[import-not-found]

    return Master


class VectorXcpRecorderBackend(RecorderBackend):
    """Production Vector + XCP/DAQ recorder backend (Windows-only)."""

    def __init__(
        self,
        *,
        transport: TransportConfig | None = None,
        ifdata: IfDataXcp | None = None,
        measurements: Mapping[str, MeasurementSummary] | None = None,
        **_legacy_kwargs: Any,
    ) -> None:
        if not sys.platform.startswith("win"):
            raise RecorderBackendUnavailableError(
                "Vector/XCP backend is Windows-only and requires Vector hardware. "
                "Use --backend fake or --backend replay on macOS / Linux."
            )
        if ifdata is None:
            raise ValueError("VectorXcpRecorderBackend requires ifdata")
        if measurements is None:
            raise ValueError("VectorXcpRecorderBackend requires measurements")

        self._can = _import_can()
        self._MasterCls = _import_xcp_master()
        self._transport = transport or TransportConfig()
        self._ifdata = ifdata
        self._measurements = measurements
        self._bus: Any | None = None
        self._master: Any | None = None
        self._session: Any | None = None
        self._poll_queue: list[tuple[str, float, float]] = []
        self._rx_count = 0
        self._bus_error_count = 0
        self._queue_overflow_count = 0
        self._last_error: str | None = None
        self._last_frame_monotonic: float | None = None
        self._base_monotonic_s = 0.0
        self._stop_event: threading.Event | None = None
        self._capture_thread: threading.Thread | None = None

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

        bus_kwargs: dict[str, Any] = {
            "interface": "vector",
            "app_name": self._transport.app_name,
            "channel": self._transport.channel,
            "bitrate": self._transport.bitrate,
            "fd": self._transport.can_fd,
        }
        if self._transport.can_fd:
            bus_kwargs["data_bitrate"] = self._transport.data_bitrate
        try:
            self._bus = self._can.Bus(**bus_kwargs)
        except Exception as exc:
            raise RecorderStartError(f"Vector bus open failed: {exc}") from exc

        try:
            self._master = self._MasterCls("can", config={"bus": self._bus})
        except Exception as exc:
            self._shutdown_bus()
            raise RecorderStartError(f"pyxcp Master init failed: {exc}") from exc

        self._session = XcpDaqSession(
            master=self._master,
            ifdata=self._ifdata,
            measurements=self._measurements,
            seed_and_key_dll=self._transport.seed_and_key_dll,
        )
        self._base_monotonic_s = time.monotonic()
        self._session.start(selected)
        self._start_capture_thread()

    def poll(self) -> list[tuple[str, float, float]]:
        out = list(self._poll_queue)
        self._poll_queue.clear()
        return out

    def stop(self) -> BackendStatus:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)
        try:
            if self._session is not None:
                self._session.stop()
        finally:
            self._shutdown_bus()
        return self.status()

    def status(self) -> BackendStatus:
        return BackendStatus(
            started=self._session is not None and self._session.is_running(),
            rx_count=self._rx_count,
            bus_error_count=self._bus_error_count,
            queue_overflow_count=self._queue_overflow_count,
            last_error=self._last_error,
        )

    def last_frame_monotonic(self) -> float | None:
        return self._last_frame_monotonic

    def _start_capture_thread(self) -> None:
        from mf4_analyzer.acquisition_capture.dto_decode import decode_dto

        if self._session is None or self._master is None:
            return
        self._stop_event = threading.Event()

        def capture_loop() -> None:
            daq_map = self._session.daq_map
            if daq_map is None:
                return
            while self._stop_event is not None and not self._stop_event.is_set():
                try:
                    frame = self._read_dto_frame()
                except Exception as exc:
                    self._queue_overflow_count += 1
                    self._last_error = str(exc)
                    time.sleep(0.001)
                    continue
                if frame is None or not frame:
                    time.sleep(0.001)
                    continue
                self._last_frame_monotonic = time.monotonic()
                for sample in decode_dto(
                    frame=bytes(frame),
                    daq_map=daq_map,
                    timestamp_size=self._ifdata.daq_timestamp_size,
                    timestamp_unit_ns=self._session.timestamp_unit_ns,
                    byte_order=self._ifdata.byte_order,
                    base_monotonic_s=self._base_monotonic_s,
                ):
                    self._poll_queue.append(sample)
                    self._rx_count += 1

        self._capture_thread = threading.Thread(
            target=capture_loop,
            name="xcp-capture",
            daemon=True,
        )
        self._capture_thread.start()

    def _read_dto_frame(self) -> bytes | None:
        # PR-4 integration point. pyxcp's Master DTO-reception API varies
        # by version (``master.fetch`` on some forks, ``transport.fetch``
        # or callback-driven on others). We try the documented seam, fall
        # back to None so the capture loop keeps running. The bench-
        # validation runbook (Task 19) records the exact pyxcp version
        # observed on the target Windows host and tightens this method.
        fetch = getattr(self._master, "fetch", None)
        if callable(fetch):
            return fetch(timeout=0.05)
        transport = getattr(self._master, "transport", None)
        transport_fetch = getattr(transport, "fetch", None)
        if callable(transport_fetch):
            return transport_fetch(timeout=0.05)
        return None

    def _shutdown_bus(self) -> None:
        if self._bus is None:
            return
        try:
            self._bus.shutdown()
        except Exception:
            pass
