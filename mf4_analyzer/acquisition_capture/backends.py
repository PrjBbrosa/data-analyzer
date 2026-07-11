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
import importlib
import queue
import subprocess
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


_PYXCP_IMPORT_PROBE_RESULT: tuple[int, str, str] | None = None


def _format_exit_code(returncode: int) -> str:
    unsigned = returncode & 0xFFFFFFFF
    if returncode < 0 or unsigned > 0x7FFFFFFF:
        return f"{returncode} (0x{unsigned:08X})"
    return str(returncode)


def _compact_probe_output(stdout: str, stderr: str) -> str:
    text = (stderr or stdout or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    detail = lines[0] if lines else "no output"
    if len(detail) > 300:
        return detail[:297] + "..."
    return detail


def _pyxcp_import_probe_command() -> list[str]:
    """Build the production pyxcp import probe command for this runtime."""

    qt_widgets_module = "Py" + "Qt5.QtWidgets"
    xcp_master_module = "py" + "xcp.master"
    probe_code = (
        f"__import__({qt_widgets_module!r}, fromlist=['QApplication'])\n"
        f"__import__({xcp_master_module!r}, fromlist=['Master'])\n"
    )
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pyxcp-import-probe-child"]
    return [sys.executable, "-c", probe_code]


def _run_pyxcp_import_probe() -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            _pyxcp_import_probe_command(),
            capture_output=True,
            text=True,
            # 30s, not 5s: a frozen onedir exe's first cold subprocess launch
            # pays a Windows Defender scan + cold DLL load and can exceed a tight
            # timeout, which would spuriously report Vector/XCP as unavailable.
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"pyxcp import probe timed out after {exc.timeout}s"
    return result.returncode, result.stdout, result.stderr


def _ensure_pyxcp_import_safe() -> None:
    global _PYXCP_IMPORT_PROBE_RESULT
    if _PYXCP_IMPORT_PROBE_RESULT is None:
        _PYXCP_IMPORT_PROBE_RESULT = _run_pyxcp_import_probe()
    returncode, stdout, stderr = _PYXCP_IMPORT_PROBE_RESULT
    if returncode == 0:
        return
    raise RecorderBackendUnavailableError(
        "pyxcp import failed in an isolated probe "
        f"(exit={_format_exit_code(returncode)}): "
        f"{_compact_probe_output(stdout, stderr)}"
    )


def _import_can():
    import can  # type: ignore[import-not-found]

    return can


def _import_xcp_master():
    _ensure_pyxcp_import_safe()
    module = importlib.import_module("py" + "xcp.master")
    return module.Master


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

        self._transport = transport or TransportConfig()
        self._ifdata = ifdata
        self._measurements = measurements
        self._runtime: Any | None = None
        self._master: Any | None = None
        self._session: Any | None = None
        self._policy: Any | None = None
        self._sample_queue: queue.Queue[tuple[str, float, float]] = queue.Queue(
            maxsize=16_384
        )
        self._rx_count = 0
        self._bus_error_count = 0
        self._queue_overflow_count = 0
        self._policy_error_count = 0
        self._unknown_pid_count = 0
        self._decode_error_count = 0
        self._sample_queue_high_water = 0
        self._last_error: str | None = None
        self._last_frame_monotonic: float | None = None
        self._base_monotonic_s = 0.0
        self._stop_event = threading.Event()
        self._decode_thread: threading.Thread | None = None
        self._diagnostics_lock = threading.Lock()
        self._sample_queue_lock = threading.Lock()

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

        self._prepare_for_start()
        try:
            from mf4_analyzer.acquisition_capture.pyxcp_daq_policy import BoundedDaqPolicy
            from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime

            self._policy = BoundedDaqPolicy()
            self._runtime = PyXcpRuntime.open(self._transport, self._ifdata, self._policy)
            self._master = self._runtime.master
        except Exception as exc:
            message = f"pyxcp runtime init failed: {exc}"
            self._cleanup_failed_start(message)
            raise RecorderStartError(message) from exc

        self._session = XcpDaqSession(
            master=self._master,
            ifdata=self._ifdata,
            measurements=self._measurements,
            seed_and_key_dll=self._transport.seed_and_key_dll,
        )
        self._base_monotonic_s = time.monotonic()
        try:
            self._session.start(selected)
            self._start_decode_thread()
        except Exception as exc:
            message = f"Vector/XCP session start failed: {exc}"
            self._cleanup_failed_start(message)
            raise RecorderStartError(message) from exc

    def poll(self) -> list[tuple[str, float, float]]:
        out: list[tuple[str, float, float]] = []
        while True:
            with self._sample_queue_lock:
                try:
                    sample = self._sample_queue.get_nowait()
                except queue.Empty:
                    break
            out.append(sample)
        return out

    def stop(self) -> BackendStatus:
        self._release_resources(clear_policy=False)
        return self.status()

    def status(self) -> BackendStatus:
        policy = self._policy.diagnostics() if self._policy is not None else None
        frame_overflow_count = getattr(policy, "frame_overflow_count", 0)
        with self._diagnostics_lock:
            return BackendStatus(
                started=self._session is not None and self._session.is_running(),
                rx_count=self._rx_count,
                bus_error_count=self._bus_error_count,
                queue_overflow_count=(
                    self._queue_overflow_count + frame_overflow_count
                ),
                last_error=self._last_error,
            )

    def last_frame_monotonic(self) -> float | None:
        with self._diagnostics_lock:
            return self._last_frame_monotonic

    def diagnostics(self) -> dict[str, Any]:
        """Return a coherent, non-destructive Vector/DAQ health snapshot."""

        policy = self._policy.diagnostics() if self._policy is not None else None
        with self._sample_queue_lock:
            sample_queue_depth = self._sample_queue.qsize()
        with self._diagnostics_lock:
            return {
                "started": self._session is not None and self._session.is_running(),
                "last_frame_monotonic_s": self._last_frame_monotonic,
                "last_dto_monotonic_s": getattr(
                    policy,
                    "last_frame_monotonic_s",
                    None,
                ),
                "dto_received_count": getattr(policy, "dto_received_count", 0),
                "samples_emitted_count": self._rx_count,
                # Compatibility alias for the first readiness implementation.
                "decoded_samples": self._rx_count,
                "bus_error_count": self._bus_error_count,
                # pyxcp 0.29.x swallows python-can CanError in recv(), so a
                # zero counter is not proof that the bus was error-free.
                "bus_error_observable": False,
                "bus_state": None,
                "policy_error_count": self._policy_error_count,
                "frame_queue_depth": getattr(policy, "frame_depth", 0),
                "frame_queue_high_water": getattr(policy, "frame_high_water", 0),
                "frame_overflow_count": getattr(policy, "frame_overflow_count", 0),
                "sample_queue_depth": sample_queue_depth,
                "sample_queue_high_water": self._sample_queue_high_water,
                "sample_overflow_count": self._queue_overflow_count,
                "unknown_pid_count": self._unknown_pid_count,
                "decode_error_count": self._decode_error_count,
                "last_error": self._last_error,
            }

    def _start_decode_thread(self) -> None:
        from mf4_analyzer.acquisition_capture.dto_decode import (
            DtoDecodeStatus,
            decode_dto_result,
        )

        if self._session is None or self._policy is None:
            return
        session = self._session
        policy = self._policy
        stop_event = self._stop_event
        base_monotonic_s = self._base_monotonic_s

        def decode_loop() -> None:
            daq_map = session.daq_map
            if daq_map is None:
                return
            while not stop_event.is_set():
                try:
                    frame = policy.get()
                except Exception as exc:
                    with self._diagnostics_lock:
                        self._policy_error_count += 1
                        self._last_error = str(exc)
                    continue
                if frame is None:
                    continue
                arrival_monotonic = frame.arrival_monotonic_s
                try:
                    result = decode_dto_result(
                        frame=frame.payload,
                        daq_map=daq_map,
                        timestamp_size=self._ifdata.daq_timestamp_size,
                        timestamp_unit_ns=session.timestamp_unit_ns,
                        byte_order=self._ifdata.byte_order,
                        base_monotonic_s=base_monotonic_s,
                        frame_arrival_monotonic_s=arrival_monotonic,
                    )
                except Exception as exc:  # keep later valid DTOs flowing
                    with self._diagnostics_lock:
                        self._decode_error_count += 1
                        self._last_error = f"DTO decode failed: {exc}"
                    continue
                if result.status is DtoDecodeStatus.UNKNOWN_PID:
                    with self._diagnostics_lock:
                        self._unknown_pid_count += 1
                        self._last_error = result.error
                    continue
                if result.status is not DtoDecodeStatus.SUCCESS:
                    with self._diagnostics_lock:
                        self._decode_error_count += 1
                        self._last_error = result.error or result.status.value
                    continue
                for sample in result.samples:
                    with self._sample_queue_lock:
                        try:
                            self._sample_queue.put_nowait(sample)
                        except queue.Full:
                            emitted_depth = None
                        else:
                            emitted_depth = self._sample_queue.qsize()
                    if emitted_depth is None:
                        with self._diagnostics_lock:
                            self._queue_overflow_count += 1
                    else:
                        with self._diagnostics_lock:
                            self._rx_count += 1
                            self._last_frame_monotonic = arrival_monotonic
                            self._sample_queue_high_water = max(
                                self._sample_queue_high_water,
                                emitted_depth,
                            )

        self._decode_thread = threading.Thread(
            target=decode_loop,
            name="xcp-daq-decode",
            daemon=True,
        )
        self._decode_thread.start()

    def _prepare_for_start(self) -> None:
        self._release_resources(clear_policy=True)
        with self._sample_queue_lock:
            while True:
                try:
                    self._sample_queue.get_nowait()
                except queue.Empty:
                    break
        with self._diagnostics_lock:
            self._rx_count = 0
            self._bus_error_count = 0
            self._queue_overflow_count = 0
            self._policy_error_count = 0
            self._unknown_pid_count = 0
            self._decode_error_count = 0
            self._sample_queue_high_water = 0
            self._last_error = None
            self._last_frame_monotonic = None
            self._base_monotonic_s = 0.0
        # Each decode thread captures its own event. A late old thread cannot
        # be revived when the new session starts.
        self._stop_event = threading.Event()

    def _release_resources(self, *, clear_policy: bool) -> None:
        self._stop_event.set()
        thread = self._decode_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

        session = self._session
        runtime = self._runtime
        policy = self._policy
        errors: list[str] = []
        try:
            if session is not None:
                session.stop()
        except Exception as exc:
            errors.append(f"session stop failed: {exc}")
        try:
            if runtime is not None:
                runtime.close()
        except Exception as exc:
            errors.append(f"runtime close failed: {exc}")
        if clear_policy and policy is not None:
            try:
                finalize = getattr(policy, "finalize", None)
                if callable(finalize):
                    finalize()
            except Exception as exc:
                errors.append(f"policy finalize failed: {exc}")

        self._session = None
        self._master = None
        self._runtime = None
        self._decode_thread = None
        if clear_policy:
            self._policy = None
        if errors:
            with self._diagnostics_lock:
                self._last_error = "; ".join(errors)

    def _cleanup_failed_start(self, message: str) -> None:
        self._release_resources(clear_policy=True)
        with self._diagnostics_lock:
            self._last_error = message
