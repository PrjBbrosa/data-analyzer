"""Mf4Writer — buffered-chunks-then-finalize MVP backed by asammdf.

Spec §Recorder Backend channel-naming rule: every MF4 channel name MUST
equal the A2L measurement ``name`` verbatim (no prefix, no suffix,
no transliteration). Review ``expected_channels`` round-trips depend on
this contract; the writer-spike report (sibling .md file under
``docs/analyzer/acquisition/reports/``) pins the rule.

The MVP strategy is "buffer per-channel arrays in memory, finalize once
on close". asammdf 8.x does support incremental ``append`` followed by
``save``, but the rolling-append form serializes one ``Signal`` per
``append`` call which would create one MF4 channel-group per call —
breaking the channel-naming contract. So we accumulate samples in
per-channel ``list[float]`` and call ``MDF.append(...)`` once with a
single Signal list at close time, then ``MDF.save(...)``.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement

try:
    from asammdf import MDF, Signal
    HAS_ASAMMDF = True
except ImportError:  # pragma: no cover - asammdf is a hard dep, kept for parity
    HAS_ASAMMDF = False


class Mf4WriterError(RuntimeError):
    """Raised on writer / file-IO failure. CLI maps this to non-zero exit."""


class Mf4Writer:
    """In-memory buffered MF4 writer.

    Lifecycle:

    - ``__init__(path, selected)`` — registers channel slots; the file
      itself is created on ``close()``.
    - ``append(channel_name, timestamp, value)`` — pushes one sample.
      Unknown channel names raise immediately (this is a programmer
      bug — the controller MUST only forward samples for the
      ``selected`` set).
    - ``finalize()`` — flushes buffered samples to disk via
      ``MDF.append + MDF.save``, closes the MDF, returns the written
      ``Path``. After ``finalize`` the writer is closed; calling
      ``append`` again raises.
    """

    def __init__(
        self,
        output_path: str | Path,
        selected: Sequence[SelectedMeasurement],
    ) -> None:
        if not HAS_ASAMMDF:
            raise Mf4WriterError("asammdf is not installed; cannot write MF4")
        if not selected:
            raise Mf4WriterError("at least one selected measurement required")
        self._path = Path(output_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._selected = tuple(selected)
        # Per-channel buffers keyed by A2L name (verbatim — channel-naming
        # contract). Preserves selection order at finalize time.
        self._buffers: dict[str, dict[str, list[float]]] = {
            m.name: {"ts": [], "val": []} for m in self._selected
        }
        self._units: dict[str, str] = {m.name: m.unit for m in self._selected}
        self._write_count = 0
        self._closed = False
        self._first_write_monotonic: float | None = None
        self._last_write_monotonic: float | None = None

    # ------------------------------------------------------------------
    # Hot-path append.
    # ------------------------------------------------------------------

    def append(self, channel_name: str, timestamp: float, value: float) -> None:
        if self._closed:
            raise Mf4WriterError("writer is closed; cannot append")
        try:
            buf = self._buffers[channel_name]
        except KeyError as exc:
            raise Mf4WriterError(
                f"channel {channel_name!r} not in selected set "
                f"({sorted(self._buffers)})"
            ) from exc
        buf["ts"].append(float(timestamp))
        buf["val"].append(float(value))
        self._write_count += 1
        now = time.monotonic()
        if self._first_write_monotonic is None:
            self._first_write_monotonic = now
        self._last_write_monotonic = now

    def append_batch(self, samples: Iterable[tuple[str, float, float]]) -> None:
        """Bulk-append helper used by ``CaptureController.drain``.

        Each tuple is ``(channel_name, timestamp, value)``.
        """
        for ch, ts, val in samples:
            self.append(ch, ts, val)

    # ------------------------------------------------------------------
    # Finalize.
    # ------------------------------------------------------------------

    def finalize(self) -> Path:
        """Flush buffered samples, close the MDF, return the written path."""
        if self._closed:
            raise Mf4WriterError("writer already finalized")
        try:
            mdf = MDF(version="4.10")
            signals = []
            for m in self._selected:
                buf = self._buffers[m.name]
                ts = np.asarray(buf["ts"], dtype=float)
                vals = np.asarray(buf["val"], dtype=float)
                if ts.size == 0:
                    # asammdf rejects empty Signal — emit a single
                    # placeholder sample at t=0 so the channel name is
                    # still present (channel-naming contract). Review
                    # diagnostics will surface "zero samples" as a
                    # post-record warning, not a writer failure.
                    ts = np.array([0.0])
                    vals = np.array([0.0])
                signals.append(
                    Signal(
                        samples=vals,
                        timestamps=ts,
                        name=m.name,
                        unit=self._units.get(m.name, ""),
                    )
                )
            mdf.append(signals, comment="acquisition_capture session")
            mdf.save(str(self._path), overwrite=True)
            mdf.close()
        except Mf4WriterError:
            raise
        except Exception as exc:  # noqa: BLE001 - we wrap any asammdf failure
            raise Mf4WriterError(f"failed to finalize MF4 at {self._path}: {exc}") from exc
        self._closed = True
        return self._path

    # ------------------------------------------------------------------
    # Introspection.
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def write_count(self) -> int:
        return self._write_count

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self._selected)

    def stats(self) -> dict[str, Any]:
        return {
            "write_count": self._write_count,
            "channels": list(self.channel_names),
            "closed": self._closed,
            "path": str(self._path),
        }
