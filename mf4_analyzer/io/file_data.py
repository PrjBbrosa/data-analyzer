"""FileData: per-file in-memory channel container."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .._palette import FILE_PALETTES
from .channel_frame import frame_get_column, frame_row_count


# Authoritative set of channel names treated as the time master.
# Compared case-insensitively. Used both internally by FileData and by
# UI probe paths (e.g. mf4_analyzer.ui.drawers.batch.input_panel) so the
# filter stays consistent across loaded-file and disk-probe code paths.
_TIME_NAMES = frozenset({
    'time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)',
})

# Display budgets for the file's short label (``short_name``). The plain
# (no-suffix) base fits within ``_SHORT_NAME_BUDGET``; when a ``label_suffix``
# is appended the elided base is held within ``_SHORT_NAME_BUDGET_WITH_SUFFIX``
# so the total ``"<base> ·<suffix>"`` stays compact. These match the historical
# ``stem[:18]`` / ``stem[:14]`` head-truncation widths so existing layouts keep
# the same overall label length.
_SHORT_NAME_BUDGET = 18
_SHORT_NAME_BUDGET_WITH_SUFFIX = 14

# Single code-point ellipsis used as the middle marker (NOT three dots) so the
# elided label stays exactly ``budget`` code points wide.
_MIDDLE_ELLIPSIS = "…"  # …

TIME_AXIS_REBUILD_REASONS = frozenset({
    "auto_nonuniform",
    "manual",
    "project_restore",
})
TIME_AXIS_PROVENANCE_METHOD = "median_dt"


def middle_ellipsis(text, budget):
    """Shorten ``text`` to at most ``budget`` code points, eliding the MIDDLE.

    Unlike head-truncation (``text[:budget]``), this keeps BOTH a leading and a
    trailing segment joined by a single ``…`` so the differentiating tail of an
    over-long, common-prefixed filename survives (the multi-file same-name root
    cause was head-truncation collapsing two distinct files to one label).

    Contract:
        * ``len(text) <= budget`` (or a too-small budget) -> ``text`` is returned
          BYTE-IDENTICAL (no ellipsis is ever introduced when not needed).
        * otherwise the result is exactly ``budget`` code points: a leading
          segment, ``…``, and a trailing segment, with the trailing segment
          given the extra code point when ``budget - 1`` is odd so the
          differentiating tail is favored.
        * code-point based (``str`` slicing), so multi-byte / CJK names are
          counted by character, never split mid-codepoint.

    ``budget`` below 3 cannot hold ``head + … + tail`` meaningfully, so the
    function degrades to plain head-truncation (``text[:budget]``) there.
    """
    s = str(text)
    if budget is None or budget < 0:
        return s
    if len(s) <= budget:
        return s
    if budget < 3:
        # Not enough room for head + ellipsis + tail; fall back to head cut.
        return s[:budget]
    keep = budget - 1  # code points kept around the single-char ellipsis
    head = keep // 2
    tail = keep - head  # favors the differentiating tail when keep is odd
    return f"{s[:head]}{_MIDDLE_ELLIPSIS}{s[-tail:] if tail else ''}"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z",
    )


def _optional_float(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def time_axis_spacing_stats(time_array, fs):
    """Return ``(relative_jitter, dt_min, dt_max)`` or ``None``.

    ``relative_jitter`` is ``max|dt - 1/fs| / (1/fs)``, the same quantity
    ``FileData.is_time_axis_uniform`` compares to the spectrogram tolerance.
    """
    if time_array is None:
        return None
    arr = np.asarray(time_array, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        return None
    sample_rate = _optional_float(fs)
    if sample_rate is None or sample_rate <= 0:
        return None
    dt = np.diff(arr)
    if dt.size == 0:
        return None
    nominal_dt = 1.0 / sample_rate
    relative_jitter = float(np.max(np.abs(dt - nominal_dt)) / nominal_dt)
    return relative_jitter, float(np.min(dt)), float(np.max(dt))


@dataclass(frozen=True)
class TimeAxisProvenance:
    """Frozen snapshot of the axis that was replaced by a rebuild."""

    reason: str
    method: str
    original_fs: float | None
    original_time_source: str
    estimated_fs: float | None
    relative_jitter: float | None
    dt_min: float | None
    dt_max: float | None
    n_samples: int
    applied_at: str

    def to_dict(self):
        return {
            "reason": self.reason,
            "method": self.method,
            "original_fs": self.original_fs,
            "original_time_source": self.original_time_source,
            "estimated_fs": self.estimated_fs,
            "relative_jitter": self.relative_jitter,
            "dt_min": self.dt_min,
            "dt_max": self.dt_max,
            "n_samples": int(self.n_samples),
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_dict(cls, payload):
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            return None
        try:
            n_samples = int(payload.get("n_samples") or 0)
        except (TypeError, ValueError):
            n_samples = 0
        return cls(
            reason=str(payload.get("reason") or ""),
            method=str(payload.get("method") or TIME_AXIS_PROVENANCE_METHOD),
            original_fs=_optional_float(payload.get("original_fs")),
            original_time_source=str(payload.get("original_time_source") or ""),
            estimated_fs=_optional_float(payload.get("estimated_fs")),
            relative_jitter=_optional_float(payload.get("relative_jitter")),
            dt_min=_optional_float(payload.get("dt_min")),
            dt_max=_optional_float(payload.get("dt_max")),
            n_samples=n_samples,
            applied_at=str(payload.get("applied_at") or ""),
        )


def build_time_axis_provenance(
    time_array,
    original_fs,
    estimated_fs,
    *,
    reason,
    original_time_source,
    n_samples=None,
    applied_at=None,
):
    """Snapshot the current axis before ``fs`` / ``time_array`` are overwritten."""
    stats = time_axis_spacing_stats(time_array, original_fs)
    if stats is None:
        relative_jitter = dt_min = dt_max = None
    else:
        relative_jitter, dt_min, dt_max = stats
    if n_samples is None:
        if time_array is None:
            n_samples = 0
        else:
            n_samples = int(np.asarray(time_array).size)
    return TimeAxisProvenance(
        reason=str(reason),
        method=TIME_AXIS_PROVENANCE_METHOD,
        original_fs=_optional_float(original_fs),
        original_time_source=str(original_time_source or ""),
        estimated_fs=_optional_float(estimated_fs),
        relative_jitter=relative_jitter,
        dt_min=dt_min,
        dt_max=dt_max,
        n_samples=int(n_samples),
        applied_at=str(applied_at or _utc_now_iso()),
    )


class FileData:
    def __init__(self, fp, df, chs, units, idx=0, *, fs=None,
                 source_metadata=None, channel_metadata=None, label_suffix=""):
        self.filepath = Path(fp)
        self.filename = self.filepath.name
        self.source_metadata = dict(source_metadata or {})
        self.channel_metadata = dict(channel_metadata or {})
        self.label_suffix = str(label_suffix or "")
        # Middle-ellipsis (NOT head-truncation) so two long filenames that share
        # a long common prefix keep their DIFFERENTIATING tail in the label. The
        # tail matters for human disambiguation; channel IDENTITY is the
        # composite (data_id, name) key on the canvas, so the label is display
        # only and a collision here is now cosmetic, not a data-loss bug.
        stem = self.filepath.stem
        if self.label_suffix:
            base = middle_ellipsis(stem, _SHORT_NAME_BUDGET_WITH_SUFFIX)
            self.short_name = f"{base} ·{self.label_suffix}"
        else:
            self.short_name = middle_ellipsis(stem, _SHORT_NAME_BUDGET)
        self.data = df
        self.channels = chs
        self.channel_units = units
        self.file_index = idx
        self.time_array = None
        self.fs = 1000.0
        self._time_source = 'auto'  # 'auto', 'column', 'generated'
        self.time_axis_provenance = None

        if fs is not None:
            self.fs = float(fs)
            self.time_array = np.arange(frame_row_count(df), dtype=float) / self.fs
            self._time_source = 'audio'
        else:
            # 尝试从列名识别时间列
            for ch in chs:
                if ch.lower() in _TIME_NAMES:
                    self.time_array = np.asarray(
                        frame_get_column(df, ch), dtype=float,
                    )
                    if len(self.time_array) > 1:
                        dt = np.median(np.diff(self.time_array))
                        if dt > 0:
                            self.fs = 1.0 / dt
                            self._time_source = 'column'
                    break

            # 如果没有时间列，根据采样率生成
            if self.time_array is None:
                self.time_array = np.arange(frame_row_count(df), dtype=float) / self.fs
                self._time_source = 'generated'

    def rebuild_time_axis(self, fs, *, reason='manual'):
        """Rebuild ``time_array`` as ``arange(n) / fs``.

        ``reason`` is keyword-only so duck-typed fakes that only accept
        ``(self, new_fs)`` keep working at call sites that inspect the
        signature or catch ``TypeError``. Snapshot provenance from the
        current axis *before* overwrite so two consecutive rebuilds record
        the immediate neighbor, not the original original.
        """
        n = len(self.data)
        snapshot = build_time_axis_provenance(
            self.time_array,
            self.fs,
            fs,
            reason=reason,
            original_time_source=str(self._time_source or ""),
            n_samples=n,
        )
        self.fs = fs
        self.time_array = np.arange(n, dtype=float) / fs
        if reason == 'manual':
            self._time_source = 'manual'
        elif reason == 'auto_nonuniform':
            self._time_source = 'auto_rebuilt'
        self.time_axis_provenance = snapshot

    def is_audio_source(self):
        """True iff this file was imported from an audio/video track."""
        return self.source_metadata.get('source_kind') == 'audio'

    def is_time_axis_uniform(self, tolerance=None):
        """Pre-flight predicate matching SpectrogramAnalyzer._validate_time_axis.

        Returns ``True`` iff the analyzer's compute step would NOT raise
        ``non-uniform time axis: ...`` for the current ``time_array`` at
        the current ``self.fs``. The decision rule mirrors
        :func:`mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer._validate_time_axis`
        exactly:

          * length < 2  -> ``True`` (degenerate, defer to caller's
            ``len(sig) < 2`` guard).
          * any ``dt <= 0`` -> ``False`` (non-monotonic, the extreme
            non-uniform case).
          * ``max|dt - 1/fs| / (1/fs) > tolerance`` -> ``False``.
          * otherwise ``True`` (the analyzer would accept).

        ``tolerance`` defaults to
        :data:`mf4_analyzer.signal.spectrogram.DEFAULT_TIME_JITTER_TOLERANCE`
        (the analyzer's own kwarg default). Do NOT hardcode a different
        threshold here -- the whole point of this predicate is that the
        UI pre-flight and the worker's validator agree.

        Used by ``MainWindow.do_fft`` and ``MainWindow.do_fft_time`` to
        route non-uniform inputs through ``_show_rebuild_popover``
        BEFORE dispatching the FFT worker, eliminating the
        worker-failed -> popover -> retry round-trip (lesson 2026-04-26
        non-uniform fft pre-flight).
        """
        if tolerance is None:
            # Imported here to avoid a hard dep at import-time / cycle risk.
            from ..signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE
            tolerance = DEFAULT_TIME_JITTER_TOLERANCE
        t = self.time_array
        if t is None:
            return True
        arr = np.asarray(t, dtype=float)
        if arr.ndim != 1 or arr.size < 2:
            return True
        fs = _optional_float(self.fs)
        if fs is None or fs <= 0:
            # No nominal_dt is meaningful; defer rebuild to the caller.
            return False
        stats = time_axis_spacing_stats(arr, fs)
        if stats is None:
            return True
        relative_jitter, dt_min, _dt_max = stats
        if dt_min <= 0:
            return False
        return relative_jitter <= float(tolerance)

    def time_axis_relative_jitter(self):
        """Return ``max|dt-1/fs|/(1/fs)`` for the current axis, or ``None``."""
        stats = time_axis_spacing_stats(self.time_array, self.fs)
        if stats is None:
            return None
        return stats[0]

    def suggested_fs_from_time_axis(self):
        """Best-effort Fs estimate from the existing ``time_array``.

        Returns the median dt's reciprocal when the axis has at least 2
        samples and a positive median dt; otherwise falls back to the
        current ``self.fs``. The caller (rebuild popover) uses this as
        the seed value, so the user only has to confirm rather than
        retype Fs from scratch when the axis is non-uniform but has a
        clear central tendency.

        The median (not mean) is used because non-uniform MF4 timestamp
        streams typically have rare large gaps that would otherwise pull
        a mean estimate off the true sampling rate.
        """
        t = self.time_array
        if t is None:
            return float(self.fs)
        arr = np.asarray(t, dtype=float)
        if arr.size < 2:
            return float(self.fs)
        dt = np.diff(arr)
        # Drop non-positive gaps so a non-monotonic axis still yields a
        # sensible estimate from the well-ordered majority.
        positive = dt[dt > 0]
        if positive.size == 0:
            return float(self.fs)
        median_dt = float(np.median(positive))
        if not np.isfinite(median_dt) or median_dt <= 0:
            return float(self.fs)
        return 1.0 / median_dt

    def get_signal_channels(self):
        return [c for c in self.channels if c.lower() not in _TIME_NAMES]

    def get_prefixed_channel(self, ch):
        return f"[{self.short_name}] {ch}"

    def get_color_palette(self):
        return FILE_PALETTES[self.file_index % len(FILE_PALETTES)]
