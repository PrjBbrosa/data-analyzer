"""BLF/DBC reading and decoding for :class:`~mf4_analyzer.io.loader.DataLoader`.

Split out of ``loader.py`` unchanged: ``DataLoader`` keeps the public
``read_blf_frames`` / ``load_blf_frames`` / ``load_blf`` / ``load_blf_dataframe``
/ ``probe_blf_dbc_frames`` / ``probe_blf_dbc`` facade and delegates the work
down here. ``load_blf`` returns a :class:`~mf4_analyzer.io.channel_frame.ChannelFrame`.

``can`` and ``cantools`` stay lazily imported inside the functions that need
them, so importing this module never requires the optional CAN stack.
"""
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .channel_frame import ChannelFrame, UnsupportedChannelFrameOperation


@dataclass(frozen=True)
class BlfDbcProbe:
    """DBC compatibility summary with exact facts, sample facts, and estimates.

    Exact fields come from a full ID scan (no payload decode). Sample fields
    come from a bounded statistical decode. Estimates are optional and must
    not be presented as exact frame counts.

    ``discovery_decoded_count`` is a *separate* budget: the first frame of
    each arbitration id, decoded only to learn which signal names this DBC
    can produce. It deliberately stays out of every ratio — a coverage
    sample is not a statistical one.
    """

    dbc_paths: tuple[str, ...]
    total_frame_count: int
    total_frame_id_count: int
    matched_frame_count: int | None
    matched_frame_id_count: int
    decode_sample_count: int
    sampled_matched_frame_count: int
    decoded_sample_count: int
    signal_names: tuple[str, ...]
    sampling_strategy: str
    sampling_complete: bool
    estimate_unavailable_reason: str | None = None
    discovery_decoded_count: int = 0

    @property
    def sample_match_ratio(self) -> float:
        if self.decode_sample_count <= 0:
            return 0.0
        return self.sampled_matched_frame_count / self.decode_sample_count

    @property
    def sample_decode_success_ratio(self) -> float:
        if self.decode_sample_count <= 0:
            return 0.0
        return self.decoded_sample_count / self.decode_sample_count

    @property
    def estimated_decoded_frame_ratio(self) -> float | None:
        if (
            not self.sampling_complete
            or self.estimate_unavailable_reason
            or self.decode_sample_count <= 0
        ):
            return None
        return self.sample_decode_success_ratio

    @property
    def is_match(self) -> bool:
        """True when either sample proved this DBC decodes real signals.

        The statistical sample answers "how much of the log decodes"; the
        discovery sample answers "does anything decode at all". A DBC that
        only defines a low-frequency id never lands in the statistical
        sample of a large log, so requiring it there rejected valid DBCs.
        """
        decoded = self.decoded_sample_count + self.discovery_decoded_count
        return decoded > 0 and bool(self.signal_names)

    @property
    def matched_frame_id_ratio(self) -> float:
        if self.total_frame_id_count <= 0:
            return 0.0
        return self.matched_frame_id_count / self.total_frame_id_count

    @property
    def strength(self) -> str:
        if not self.is_match:
            return "none"
        if (
            self.matched_frame_id_ratio >= 0.8
            and self.sample_decode_success_ratio >= 0.8
        ):
            return "strong"
        return "weak"

    @property
    def decoded_frame_count(self) -> int:
        """Deprecated estimate. Do not use for UI display or candidate ranking."""
        ratio = self.estimated_decoded_frame_ratio
        if ratio is None:
            return 0
        if self.decode_sample_count >= self.total_frame_count:
            return int(self.decoded_sample_count)
        return int(round(ratio * self.total_frame_count))

    @property
    def decoded_frame_ratio(self) -> float:
        """Deprecated. Use ``sample_decode_success_ratio`` or the estimate."""
        ratio = self.estimated_decoded_frame_ratio
        return 0.0 if ratio is None else float(ratio)

    @property
    def decoded_signal_count(self) -> int:
        """Deprecated. Unique discovered signal names, not a scaled event count."""
        return len(self.signal_names)


def _emit_progress(progress_callback, current, total):
    """Best-effort progress reporting for long-running loaders.

    Loader callbacks are informational only: a delayed or failed status-bar
    repaint must never make a valid data import fail.
    """
    if not callable(progress_callback):
        return
    try:
        progress_callback(int(current), max(1, int(total)))
    except Exception:
        pass


def _estimate_byte_progress(
    frame_index: int,
    total_bytes: int,
    *,
    bytes_per_frame_hint: int = 128,
) -> int:
    """Synthetic byte position when ``reader.file.tell()`` is unavailable.

    Caps below ``total_bytes`` so the final emit can still mark completion.
    """
    total_bytes = max(1, int(total_bytes))
    hint = max(1, int(bytes_per_frame_hint))
    est_frames = max(1, total_bytes // hint)
    if frame_index <= 0:
        return 0
    if frame_index >= est_frames:
        return max(0, total_bytes - 1)
    return max(1, (int(frame_index) * (total_bytes - 1)) // est_frames)


def _sample_reader_byte_progress(
    reader,
    frame_index: int,
    total_bytes: int,
    last_reported: int,
    progress_callback,
    *,
    bytes_per_frame_hint: int = 128,
) -> int:
    """Prefer ``tell()``; fall back to a frame-based byte estimate.

    Text-mode readers (CANoe ASC) disable ``tell()`` during ``for`` iteration
    (``OSError: telling position disabled by next() call``). Without a
    fallback the status bar stays frozen for the entire read.
    """
    byte_pos = None
    file_obj = getattr(reader, "file", None)
    if file_obj is not None:
        try:
            byte_pos = int(file_obj.tell())
        except (AttributeError, OSError, TypeError, ValueError):
            byte_pos = None
    if byte_pos is None:
        byte_pos = _estimate_byte_progress(
            frame_index,
            total_bytes,
            bytes_per_frame_hint=bytes_per_frame_hint,
        )
    byte_pos = min(max(0, byte_pos), max(1, int(total_bytes)))
    if byte_pos > last_reported:
        _emit_progress(progress_callback, byte_pos, total_bytes)
        return byte_pos
    return last_reported


def _read_blf_frames(fp, progress_callback=None):
    """Read a Vector BLF into a list of ``(timestamp, arbitration_id, data)``.

    Uses python-can's ``BLFReader`` — pure file parsing, no Vector hardware or
    driver required. Error/remote frames carry no signal payload and are dropped.
    """
    try:
        from can.io import BLFReader
    except ImportError as exc:
        raise ImportError(
            "python-can 未安装，无法读取 BLF 文件。请先 pip install python-can"
        ) from exc
    frames = []
    reader = BLFReader(str(fp))
    report_progress = callable(progress_callback)
    total_bytes = 1
    if report_progress:
        try:
            total_bytes = int(
                getattr(reader, "file_size", 0) or Path(fp).stat().st_size
            )
        except (OSError, TypeError, ValueError):
            total_bytes = 1
        total_bytes = max(1, total_bytes)
    last_reported = 0
    if report_progress:
        _emit_progress(progress_callback, 0, total_bytes)
    try:
        for frame_index, msg in enumerate(reader, 1):
            # ``tell()`` can be surprisingly expensive on compressed BLF
            # streams.  Sample by frame count first; never poll the reader when
            # no caller consumes progress.
            if report_progress and (
                frame_index == 1 or frame_index % 512 == 0
            ):
                last_reported = _sample_reader_byte_progress(
                    reader,
                    frame_index,
                    total_bytes,
                    last_reported,
                    progress_callback,
                    bytes_per_frame_hint=64,
                )
            if msg.is_error_frame or msg.is_remote_frame:
                continue
            frames.append(
                (float(msg.timestamp), int(msg.arbitration_id), bytes(msg.data))
            )
    finally:
        stop = getattr(reader, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
    if report_progress:
        _emit_progress(progress_callback, total_bytes, total_bytes)
    return frames


# Payload decode during DBC probe is only a match-strength sample. ID overlap
# still scans every frame. Keep this a count of frames, not a wall-time knob.
# The cap is charged *per sample*: the statistical sample and the discovery
# sample each get their own budget, so a large log cannot starve discovery
# (P0-1 — sharing one budget silently dropped every low-frequency signal).
_PROBE_DECODE_CAP = 8192


# Name of the shared time axis every assembled CAN frame carries. Reserved:
# a DBC signal of the same name must be qualified before it reaches the frame.
_TIME_AXIS_NAME = "Time"


def _zoh_resample(ref_t, t, v):
    """Zero-order-hold (previous-sample) resample of ``(t, v)`` onto ``ref_t``.

    CAN signals are event-based and piecewise-constant: a signal holds its last
    transmitted value until the next frame updates it. Linear interpolation
    (what ``load_mf4`` uses) would invent ramps between frames and corrupt
    status/enum signals, so we hold instead. ``ref_t`` before the first sample
    flat-holds the first value — matching MF4's end-extrapolation rather than
    emitting NaN. ``t`` must be sorted ascending.
    """
    t = np.asarray(t, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    if t.size == 0:
        return np.full(np.shape(ref_t), np.nan, dtype=np.float64)
    idx = np.clip(np.searchsorted(t, ref_t, side="right") - 1, 0, t.size - 1)
    return v[idx]


def _timestamp_fingerprint(t):
    n = t.size
    if n == 0:
        return (0, 0.0, 0.0, 0.0)
    mid = n // 2
    return (n, float(t[0]), float(t[-1]), float(t[mid]))


def _intern_series_timestamps(series):
    """Reuse equal timestamp arrays so later ZOH can skip identical axes."""
    interned = {}
    by_fp = {}
    for name, (t, v) in series.items():
        t_arr = t if isinstance(t, np.ndarray) and t.dtype == np.float64 else np.asarray(
            t, dtype=np.float64,
        )
        v_arr = v if isinstance(v, np.ndarray) and v.dtype == np.float64 else np.asarray(
            v, dtype=np.float64,
        )
        fp = _timestamp_fingerprint(t_arr)
        existing = by_fp.get(fp)
        if existing is None:
            by_fp[fp] = t_arr
            match = t_arr
        elif existing is t_arr or np.array_equal(existing, t_arr):
            match = existing
        else:
            match = t_arr
        interned[name] = (match, v_arr)
    return interned


def _sorted_time_values(t, v, t0, cache):
    """Shift by ``t0`` and sort if needed, caching the permutation per ``t``."""
    cached = cache.get(id(t))
    if cached is None:
        rel = np.asarray(t, dtype=np.float64) - t0
        if rel.size > 1 and np.any(np.diff(rel) < 0):
            order = np.argsort(rel, kind="stable")
            cached = (rel[order], order)
        else:
            cached = (rel, None)
        cache[id(t)] = cached
    rel_sorted, order = cached
    v_arr = v if isinstance(v, np.ndarray) and v.dtype == np.float64 else np.asarray(
        v, dtype=np.float64,
    )
    if order is None:
        return rel_sorted, v_arr
    return rel_sorted, v_arr[order]


def _can_skip_zoh(ref_t, t):
    """Identity mapping is safe when ``t`` is the reference axis without ties."""
    if t is not ref_t:
        return False
    if t.size <= 1:
        return True
    return not bool(np.any(np.diff(t) == 0))


class LazyZohFrame(ChannelFrame):
    """Column-frame view over sparse CAN series with on-demand ZOH.

    ``Time`` is materialized at construction. Other columns stay as
    ``(t, v)`` event series until first read, then ZOH onto ``Time`` and
    cache. Derived-channel writes (``frame[name] = arr``) store already-
    aligned arrays. FileData / plot access patterns (``columns``, ``len``,
    ``[name].to_numpy()``) stay available; unimplemented pandas row
    operations raise instead of silently succeeding.

    Columns are addressed by name, so names must be unique and none may
    shadow the ``Time`` axis. Both are rejected at construction rather than
    silently collapsing two series into one column; ``_decode_blf_with_dbc``
    is responsible for qualifying ambiguous DBC signal names before they
    reach here.
    """

    is_channel_frame = True

    def __init__(self, ref_t, series, column_names):
        self._ref_t = np.asarray(ref_t, dtype=np.float64)
        self._series = dict(series)
        self._column_names = list(column_names)
        self._reject_ambiguous_columns()
        self._cache = {_TIME_AXIS_NAME: self._ref_t}
        self._zoh_materializations = 0

    def _reject_ambiguous_columns(self):
        seen = set()
        duplicates = []
        for name in self._column_names:
            if name in seen and name not in duplicates:
                duplicates.append(name)
            seen.add(name)
        if duplicates:
            raise ValueError(
                "ChannelFrame 不支持重复列名（按名字取列会静默丢弃其中一份）: "
                + ", ".join(repr(name) for name in duplicates)
            )
        if _TIME_AXIS_NAME in self._series:
            raise ValueError(
                f"信号名 {_TIME_AXIS_NAME!r} 与共享时间轴冲突；"
                "请在解码时消歧为 <Message>.<Signal>"
            )

    def column_names(self):
        return tuple(self._column_names)

    def has_column(self, name):
        return name in self._column_names

    def get_column(self, name):
        values = np.asarray(self._materialize(name), dtype=np.float64)
        # The cache is shared with every other reader (and with the Time
        # axis itself), so hand out a read-only view — same guarantee the
        # ``frame[name]`` Series path already gave. Copy before mutating.
        view = values.view()
        view.setflags(write=False)
        return view

    def drop_columns(self, names):
        if isinstance(names, str):
            names = (names,)
        drop_set = set(names)
        kept = [name for name in self._column_names if name not in drop_set]
        kept_series = {
            name: pair for name, pair in self._series.items() if name in kept
        }
        out = LazyZohFrame(self._ref_t, kept_series, kept)
        out._cache = {
            name: arr for name, arr in self._cache.items() if name in kept
        }
        return out

    def row_count(self):
        return int(self._ref_t.size)

    def to_pandas(self):
        arrays = [self._materialize(name) for name in self._column_names]
        if not arrays:
            return pd.DataFrame(columns=self._column_names)
        stacked = np.column_stack([np.asarray(arr, dtype=np.float64) for arr in arrays])
        return pd.DataFrame(stacked, columns=list(self._column_names))

    def is_lazy(self):
        """True only while some column is still an unmaterialized series.

        This reports *this frame's* state, not the class's capability: once
        every column has been read the frame is as dense as a DataFrame and
        callers deciding whether to pay for materialization must see that.
        """
        return any(name not in self._cache for name in self._column_names)

    def materialized_column_names(self):
        return tuple(name for name in self._column_names if name in self._cache)

    def zoh_materialization_count(self):
        return int(self._zoh_materializations)

    @property
    def columns(self):
        return pd.Index(self._column_names)

    def __len__(self):
        return self.row_count()

    def __bool__(self):
        return True

    @property
    def empty(self):
        return self._ref_t.size == 0

    def keys(self):
        return self.columns

    def __iter__(self):
        return iter(self._column_names)

    def __getitem__(self, key):
        if isinstance(key, list):
            return pd.DataFrame({name: self._materialize(name) for name in key})
        return pd.Series(self._materialize(key), name=key)

    def __setitem__(self, key, value):
        arr = np.asarray(value, dtype=np.float64).reshape(-1)
        if arr.size != self._ref_t.size:
            raise ValueError(
                f"column {key!r} length {arr.size} does not match Time "
                f"({self._ref_t.size})"
            )
        self._cache[key] = arr
        if key not in self._column_names:
            self._column_names.append(key)

    def drop(self, labels=None, axis=0, *, columns=None, **kwargs):
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise UnsupportedChannelFrameOperation(
                f"ChannelFrame.drop does not support pandas keyword {unknown!r}; "
                "use drop_columns() for column removals"
            )
        if columns is not None:
            return self.drop_columns(columns)
        if axis == 1:
            return self.drop_columns(labels)
        raise UnsupportedChannelFrameOperation(
            "ChannelFrame.drop only supports column drops; use drop_columns() "
            "or drop(columns=...). Row drop is not supported"
        )

    def _materialize(self, name):
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if name == _TIME_AXIS_NAME:
            self._cache[name] = self._ref_t
            return self._ref_t
        pair = self._series.get(name)
        if pair is None:
            raise KeyError(name)
        t, v = pair
        if _can_skip_zoh(self._ref_t, t):
            arr = v
        else:
            arr = _zoh_resample(self._ref_t, t, v)
            self._zoh_materializations += 1
        self._cache[name] = arr
        return arr


def _assemble_blf_channels(series, units, t0, progress_callback=None):
    """Fold per-signal ``{name: (abs_t, v)}`` into a shared-time-axis frame.

    Mirrors ``load_mf4``: the longest series (most samples) defines the common
    ``Time`` axis and every other signal is ZOH-resampled onto it. All
    timestamps are shifted to start at zero via ``t0``. ZOH itself is deferred
    until a column is read so import does not allocate the dense table.
    """
    interned = _intern_series_timestamps(series)
    ref_name = max(interned, key=lambda k: interned[k][0].size)
    sort_cache = {}
    prepared = {}
    total_series = max(1, len(interned))
    report_step = max(1, total_series // 80)
    _emit_progress(progress_callback, 0, total_series)
    for index, (name, (t, v)) in enumerate(interned.items(), 1):
        prepared[name] = _sorted_time_values(t, v, t0, sort_cache)
        if index % report_step == 0 or index == total_series:
            _emit_progress(progress_callback, index, total_series)
    ref_t = prepared[ref_name][0]
    column_names = [_TIME_AXIS_NAME, *prepared.keys()]
    frame = LazyZohFrame(ref_t, prepared, column_names)
    return frame, column_names, units


def _load_dbc_database(dbc_paths):
    try:
        import cantools
    except ImportError as exc:
        raise ImportError(
            "cantools 未安装，无法用 DBC 解码 BLF。请先 pip install cantools"
        ) from exc
    db = cantools.database.Database()
    for path in dbc_paths:
        db.add_dbc_file(str(path))
    return db


def _decode_can_payload(msg, payload):
    try:
        return msg.decode(payload, decode_choices=False, allow_truncated=True)
    except TypeError:
        # older cantools without allow_truncated
        try:
            return msg.decode(payload, decode_choices=False)
        except Exception:
            return None
    except Exception:
        return None


def _numeric_decoded_values(decoded):
    values = []
    for sig_name, value in decoded.items():
        try:
            fval = float(value)
        except (TypeError, ValueError):
            continue
        values.append((sig_name, fval))
    return values


def _cached_message_lookup(db):
    """Resolve each unique arbitration id through cantools once."""
    getter = db.get_message_by_frame_id
    cache = {}
    missing = object()

    def lookup(aid):
        aid = int(aid)
        hit = cache.get(aid, missing)
        if hit is not missing:
            return hit
        try:
            msg = getter(aid)
        except KeyError:
            msg = None
        cache[aid] = msg
        return msg

    return lookup


def _display_signal_name(msg_name, sig_name, sig_owners):
    """Qualify a DBC signal name only when the bare name would be ambiguous.

    Ambiguous means either "defined by more than one message" or "collides
    with the shared time axis" — an unqualified ``Time`` signal would be
    silently replaced by the axis when the frame is assembled.
    """
    if sig_name == _TIME_AXIS_NAME or len(sig_owners.get(sig_name, ())) > 1:
        return f"{msg_name}.{sig_name}"
    return sig_name


def _signal_display_meta(msg, sig_owners):
    meta = {}
    for sig in msg.signals:
        name = sig.name
        disp = _display_signal_name(msg.name, name, sig_owners)
        meta[name] = (disp, str(getattr(sig, "unit", "") or ""))
    return meta


def _message_is_multiplexed(msg):
    checker = getattr(msg, "is_multiplexed", None)
    if not callable(checker):
        return bool(checker)
    try:
        return bool(checker())
    except ValueError:
        return True


def _discovery_probe_indices(frames, cap=_PROBE_DECODE_CAP):
    """First frame of each arbitration ID. Not a statistical sample.

    Answers "which signal names can this DBC produce at all", which is why
    it carries its own ``cap`` and never contributes to a decode ratio.
    """
    chosen = []
    seen_ids = set()
    for index, (_timestamp, arbitration_id, _payload) in enumerate(frames):
        if arbitration_id in seen_ids:
            continue
        seen_ids.add(arbitration_id)
        chosen.append(index)
        if len(chosen) >= cap:
            break
    return tuple(chosen)


def _statistical_probe_indices(frames, cap=_PROBE_DECODE_CAP):
    """Deterministic front/mid/tail sample used for match and decode ratios."""
    n = len(frames)
    if n <= 0:
        return ()
    if n <= cap:
        return tuple(range(n))
    bounds = (0, n // 3, (2 * n) // 3, n)
    per_region = cap // 3
    remainder = cap - (3 * per_region)
    chosen = []
    seen = set()
    for region_index, (start, end) in enumerate(zip(bounds, bounds[1:])):
        span = end - start
        if span <= 0:
            continue
        count = min(span, per_region + (1 if region_index < remainder else 0))
        if count <= 0:
            continue
        if count == 1:
            index = start + span // 2
            if index not in seen:
                seen.add(index)
                chosen.append(index)
            continue
        for step in range(count):
            index = start + (step * (span - 1)) // (count - 1)
            if index in seen:
                continue
            seen.add(index)
            chosen.append(index)
    if len(chosen) < cap:
        extras = np.linspace(0, n - 1, cap, dtype=np.int64)
        for raw in extras:
            index = int(raw)
            if index in seen:
                continue
            seen.add(index)
            chosen.append(index)
            if len(chosen) >= cap:
                break
    return tuple(sorted(chosen))


def _probe_decode_indices(frames, cap=_PROBE_DECODE_CAP):
    """Deprecated alias for the statistical sample. Discovery is separate."""
    return _statistical_probe_indices(frames, cap=cap)


# Probe progress runs on a fixed 0..1000 scale split into real sub-intervals:
# the full ID scan, then the bounded statistical decode, then discovery.
# 1000 is emitted exactly once, after the BlfDbcProbe exists — an early 100%
# is indistinguishable from "done" to every caller (same rule the ASC reader
# follows).
_PROBE_PROGRESS_TOTAL = 1000
_PROBE_SCAN_PROGRESS_END = 500
_PROBE_SAMPLE_PROGRESS_END = 900
_PROBE_DECODE_PROGRESS_END = 990


def _empty_blf_dbc_probe(dbc_paths, total_frames, *, reason, **overrides):
    values = {
        "dbc_paths": tuple(str(path) for path in dbc_paths),
        "total_frame_count": int(total_frames),
        "total_frame_id_count": 0,
        "matched_frame_count": None,
        "matched_frame_id_count": 0,
        "decode_sample_count": 0,
        "sampled_matched_frame_count": 0,
        "decoded_sample_count": 0,
        "signal_names": (),
        "sampling_strategy": "incomplete",
        "sampling_complete": False,
        "estimate_unavailable_reason": reason,
    }
    values.update(overrides)
    return BlfDbcProbe(**values)


def _probe_blf_dbc_frames(frames, dbc_paths, progress_callback=None, cancel_check=None):
    total_frames = len(frames)
    dbc_paths = tuple(str(path) for path in dbc_paths)

    def cancelled():
        return callable(cancel_check) and bool(cancel_check())

    if cancelled():
        return _empty_blf_dbc_probe(
            dbc_paths, total_frames, reason="cancelled",
        )
    if total_frames <= 0:
        # Nothing to conclude from, in either direction. Say so rather than
        # returning a "complete" probe whose every number is zero.
        return _empty_blf_dbc_probe(
            dbc_paths, total_frames, reason="no_frames",
        )

    db = _load_dbc_database(dbc_paths)
    lookup = _cached_message_lookup(db)
    frame_ids = set()
    matched_frame_ids = set()
    matched_frame_count = 0

    step = max(1, total_frames // 80)
    _emit_progress(progress_callback, 0, _PROBE_PROGRESS_TOTAL)
    try:
        for index, (_timestamp, arbitration_id, _payload) in enumerate(frames, 1):
            if cancelled():
                return _empty_blf_dbc_probe(
                    dbc_paths, total_frames, reason="cancelled",
                )
            frame_ids.add(arbitration_id)
            if lookup(arbitration_id) is not None:
                matched_frame_count += 1
                matched_frame_ids.add(arbitration_id)
            if index % step == 0 or index == total_frames:
                _emit_progress(
                    progress_callback,
                    (_PROBE_SCAN_PROGRESS_END * index) // total_frames,
                    _PROBE_PROGRESS_TOTAL,
                )
    except IndexError:
        return _empty_blf_dbc_probe(
            dbc_paths, total_frames, reason="truncated_sample",
        )

    statistical = _statistical_probe_indices(frames)
    statistical_set = set(statistical)
    complete_scan = total_frames <= _PROBE_DECODE_CAP
    sampling_strategy = (
        "complete" if complete_scan else "stratified_front_mid_tail"
    )
    sample_matched = 0
    sample_decoded = 0
    signal_names = set()
    sampling_complete = True
    reason = None
    decode_total = max(1, len(statistical))
    decode_step = max(1, decode_total // 80)

    for decode_index, frame_index in enumerate(statistical, 1):
        if cancelled():
            sampling_complete = False
            reason = "cancelled"
            break
        try:
            _timestamp, arbitration_id, payload = frames[frame_index]
        except IndexError:
            sampling_complete = False
            reason = "truncated_sample"
            break
        if not isinstance(payload, (bytes, bytearray)):
            sampling_complete = False
            reason = "corrupt_sample"
            break
        msg = lookup(arbitration_id)
        if msg is not None:
            sample_matched += 1
            decoded = _decode_can_payload(msg, payload)
            if decoded:
                numeric_values = _numeric_decoded_values(decoded)
                if numeric_values:
                    sample_decoded += 1
                    signal_names.update(
                        sig_name for sig_name, _value in numeric_values
                    )
        if decode_index % decode_step == 0 or decode_index == decode_total:
            _emit_progress(
                progress_callback,
                _PROBE_SCAN_PROGRESS_END + (
                    (_PROBE_SAMPLE_PROGRESS_END - _PROBE_SCAN_PROGRESS_END)
                    * decode_index
                ) // decode_total,
                _PROBE_PROGRESS_TOTAL,
            )

    # Discovery pass: independent budget, own cap, names only.  Skipped when
    # the statistical sample already covered every frame — that is the only
    # case where discovery can add nothing, and it keeps the O(n) scan inside
    # the branch that actually consumes it instead of running per candidate.
    discovery_decoded = 0
    if sampling_complete and not complete_scan:
        discovery = [
            frame_index for frame_index in _discovery_probe_indices(frames)
            if frame_index not in statistical_set
        ]
        discovery_total = max(1, len(discovery))
        discovery_step = max(1, discovery_total // 40)
        for position, frame_index in enumerate(discovery, 1):
            if cancelled():
                break
            try:
                _timestamp, arbitration_id, payload = frames[frame_index]
            except IndexError:
                break
            if position % discovery_step == 0 or position == discovery_total:
                _emit_progress(
                    progress_callback,
                    _PROBE_SAMPLE_PROGRESS_END + (
                        (_PROBE_DECODE_PROGRESS_END - _PROBE_SAMPLE_PROGRESS_END)
                        * position
                    ) // discovery_total,
                    _PROBE_PROGRESS_TOTAL,
                )
            if not isinstance(payload, (bytes, bytearray)):
                continue
            msg = lookup(arbitration_id)
            if msg is None:
                continue
            decoded = _decode_can_payload(msg, payload)
            if not decoded:
                continue
            numeric_values = _numeric_decoded_values(decoded)
            if numeric_values:
                discovery_decoded += 1
                signal_names.update(
                    sig_name for sig_name, _value in numeric_values
                )

    if not sampling_complete:
        return BlfDbcProbe(
            dbc_paths=dbc_paths,
            total_frame_count=total_frames,
            total_frame_id_count=len(frame_ids),
            matched_frame_count=matched_frame_count,
            matched_frame_id_count=len(matched_frame_ids),
            decode_sample_count=0,
            sampled_matched_frame_count=0,
            decoded_sample_count=0,
            signal_names=tuple(sorted(signal_names)),
            sampling_strategy="incomplete",
            sampling_complete=False,
            estimate_unavailable_reason=reason,
        )

    probe = BlfDbcProbe(
        dbc_paths=dbc_paths,
        total_frame_count=total_frames,
        total_frame_id_count=len(frame_ids),
        matched_frame_count=matched_frame_count,
        matched_frame_id_count=len(matched_frame_ids),
        decode_sample_count=len(statistical),
        sampled_matched_frame_count=sample_matched,
        decoded_sample_count=sample_decoded,
        signal_names=tuple(sorted(signal_names)),
        sampling_strategy=sampling_strategy,
        sampling_complete=True,
        estimate_unavailable_reason=None,
        discovery_decoded_count=discovery_decoded,
    )
    # 100% means "the result exists", not "a phase finished".
    _emit_progress(
        progress_callback, _PROBE_PROGRESS_TOTAL, _PROBE_PROGRESS_TOTAL,
    )
    return probe


def _decode_blf_with_dbc(frames, dbc_paths, t0, progress_callback=None):
    """Decode raw CAN frames into named physical signals using one or more DBCs."""
    db = _load_dbc_database(dbc_paths)
    lookup = _cached_message_lookup(db)

    # A signal name in more than one message is ambiguous; qualify only those
    # as ``<Message>.<Signal>`` so the common-case unique names stay short.
    sig_owners = defaultdict(set)
    for m in db.messages:
        for s in m.signals:
            sig_owners[s.name].add(m.name)

    meta_cache = {}
    mux_cache = {}
    times_shared = {}
    shared_key_for = {}
    t_lists = defaultdict(list)
    v_lists = defaultdict(list)
    units = {}
    total_frames = max(1, len(frames))
    step = max(1, total_frames // 80)
    _emit_progress(progress_callback, 0, 1000)
    for index, (t, aid, payload) in enumerate(frames, 1):
        msg = lookup(aid)
        if msg is None:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index * 850 // total_frames, 1000)
            continue  # frame id not in this DBC
        decoded = _decode_can_payload(msg, payload)
        if not decoded:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index * 850 // total_frames, 1000)
            continue  # CRC/length/multiplex mismatch on this frame
        numeric_values = _numeric_decoded_values(decoded)
        if not numeric_values:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index * 850 // total_frames, 1000)
            continue
        msg_id = id(msg)
        layout = meta_cache.get(msg_id)
        if layout is None:
            layout = _signal_display_meta(msg, sig_owners)
            meta_cache[msg_id] = layout
        multiplexed = mux_cache.get(msg_id)
        if multiplexed is None:
            multiplexed = _message_is_multiplexed(msg)
            mux_cache[msg_id] = multiplexed
        share_times = (not multiplexed) and (len(numeric_values) == len(layout))
        if share_times:
            t_shared = times_shared.get(msg_id)
            if t_shared is None:
                t_shared = []
                times_shared[msg_id] = t_shared
            t_shared.append(t)
        for sig_name, fval in numeric_values:
            meta = layout.get(sig_name)
            if meta is None:
                disp = _display_signal_name(msg.name, sig_name, sig_owners)
                unit = ""
            else:
                disp, unit = meta
            v_lists[disp].append(fval)
            if share_times:
                shared_key_for[disp] = msg_id
            else:
                t_lists[disp].append(t)
            if disp not in units:
                units[disp] = unit
        if index % step == 0 or index == total_frames:
            _emit_progress(progress_callback, index * 850 // total_frames, 1000)

    if not v_lists:
        raise ValueError(
            "选中的 DBC 与该 BLF 不匹配：没有任何帧被解码成功。\n"
            "请确认 DBC 是否对应这条总线，或重新打开时跳过 DBC、以原始字节查看。"
        )
    shared_arrays = {
        msg_id: np.asarray(ts, dtype=np.float64)
        for msg_id, ts in times_shared.items()
    }
    series = {}
    for name, vals in v_lists.items():
        msg_id = shared_key_for.get(name)
        if msg_id is not None and shared_arrays[msg_id].size == len(vals):
            t_arr = shared_arrays[msg_id]
        else:
            t_arr = np.asarray(t_lists[name], dtype=np.float64)
        series[name] = (t_arr, np.asarray(vals, dtype=np.float64))
    return _assemble_blf_channels(
        series,
        units,
        t0,
        progress_callback=lambda current, total: _emit_progress(
            progress_callback,
            850 + (150 * current) // max(1, total),
            1000,
        ),
    )


def _raw_blf_channels(frames, t0, progress_callback=None):
    """Database-free fallback: expose each CAN id's payload bytes as channels
    (``0x1F3.byte0`` …). Values are raw bytes (0–255), not engineering units —
    enough to eyeball traffic when no DBC is supplied."""
    by_id_t = defaultdict(list)
    by_id_d = defaultdict(list)
    total_frames = max(1, len(frames))
    frame_step = max(1, total_frames // 80)
    _emit_progress(progress_callback, 0, 1000)
    for index, (t, aid, payload) in enumerate(frames, 1):
        by_id_t[aid].append(t)
        by_id_d[aid].append(payload)
        if index % frame_step == 0 or index == total_frames:
            _emit_progress(
                progress_callback,
                (500 * index) // total_frames,
                1000,
            )

    series = {}
    units = {}
    total_ids = max(1, len(by_id_d))
    id_step = max(1, total_ids // 80)
    for index, (aid, payloads) in enumerate(by_id_d.items(), 1):
        ts = np.asarray(by_id_t[aid], dtype=np.float64)
        width = max((len(d) for d in payloads), default=0)
        prefix = f"0x{aid:X}"
        for b in range(width):
            name = f"{prefix}.byte{b}"
            vals = np.fromiter(
                (d[b] if b < len(d) else np.nan for d in payloads),
                dtype=np.float64, count=len(payloads),
            )
            series[name] = (ts, vals)
            units[name] = ""
        if index % id_step == 0 or index == total_ids:
            _emit_progress(
                progress_callback,
                500 + (250 * index) // total_ids,
                1000,
            )
    if not series:
        raise ValueError("BLF 帧不含可解析的数据字节")

    def map_assembly(current, total):
        if current > 0:
            _emit_progress(
                progress_callback,
                750 + (200 * current) // max(1, total),
                1000,
            )

    result = _assemble_blf_channels(
        series,
        units,
        t0,
        progress_callback=map_assembly,
    )
    _emit_progress(progress_callback, 1000, 1000)
    return result
