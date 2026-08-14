"""BLF/DBC reading and decoding for :class:`~mf4_analyzer.io.loader.DataLoader`.

Split out of ``loader.py`` unchanged: ``DataLoader`` keeps the public
``read_blf_frames`` / ``load_blf_frames`` / ``load_blf`` / ``probe_blf_dbc_frames``
/ ``probe_blf_dbc`` facade and delegates the work down here.

``can`` and ``cantools`` stay lazily imported inside the functions that need
them, so importing this module never requires the optional CAN stack.
"""
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BlfDbcProbe:
    """Lightweight compatibility summary for one BLF against one DBC set."""

    dbc_paths: tuple[str, ...]
    total_frame_count: int
    total_frame_id_count: int
    matched_frame_count: int
    matched_frame_id_count: int
    decoded_frame_count: int
    decoded_signal_count: int
    signal_names: tuple[str, ...]

    @property
    def is_match(self) -> bool:
        return self.decoded_frame_count > 0 and bool(self.signal_names)

    @property
    def decoded_frame_ratio(self) -> float:
        if self.total_frame_count <= 0:
            return 0.0
        return self.decoded_frame_count / self.total_frame_count

    @property
    def matched_frame_id_ratio(self) -> float:
        if self.total_frame_id_count <= 0:
            return 0.0
        return self.matched_frame_id_count / self.total_frame_id_count

    @property
    def strength(self) -> str:
        if not self.is_match:
            return "none"
        if self.matched_frame_id_ratio >= 0.8 and self.decoded_frame_ratio >= 0.8:
            return "strong"
        return "weak"


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
_PROBE_DECODE_CAP = 8192


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


class LazyZohFrame:
    """DataFrame-shaped view over sparse CAN series with on-demand ZOH.

    ``Time`` is materialized at construction. Other columns stay as
    ``(t, v)`` event series until first read, then ZOH onto ``Time`` and
    cache. Derived-channel writes (``frame[name] = arr``) store already-
    aligned arrays. This keeps FileData / export / plot access patterns
    (``columns``, ``len``, ``[name].to_numpy()``, ``drop``) while avoiding
    an ``n_signals × n_longest`` table at import.
    """

    is_channel_frame = True

    def __init__(self, ref_t, series, column_names):
        self._ref_t = np.asarray(ref_t, dtype=np.float64)
        self._series = dict(series)
        self._column_names = list(column_names)
        self._cache = {"Time": self._ref_t}

    @property
    def columns(self):
        return pd.Index(self._column_names)

    def __len__(self):
        return int(self._ref_t.size)

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

    def drop(self, labels=None, axis=0, *, columns=None, **_kwargs):
        cols = columns if columns is not None else (labels if axis == 1 else None)
        if cols is None:
            return self
        if isinstance(cols, str):
            cols = (cols,)
        drop_set = set(cols)
        names = [name for name in self._column_names if name not in drop_set]
        kept_series = {
            name: pair for name, pair in self._series.items() if name in names
        }
        out = LazyZohFrame(self._ref_t, kept_series, names)
        out._cache = {
            name: arr for name, arr in self._cache.items() if name in names
        }
        return out

    def _materialize(self, name):
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if name == "Time":
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
    column_names = ["Time", *prepared.keys()]
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


def _signal_display_meta(msg, sig_owners):
    meta = {}
    for sig in msg.signals:
        name = sig.name
        disp = (
            name if len(sig_owners.get(name, ())) <= 1
            else f"{msg.name}.{name}"
        )
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


def _probe_decode_indices(frames, cap=_PROBE_DECODE_CAP):
    """Sample frames for payload decode; always include the first of each ID."""
    n = len(frames)
    if n <= cap:
        return range(n)
    chosen = []
    seen = set()
    for i, (_t, aid, _payload) in enumerate(frames):
        if aid in seen:
            continue
        seen.add(aid)
        chosen.append(i)
        if len(chosen) >= cap:
            return chosen
    chosen_set = set(chosen)
    extras = np.linspace(0, n - 1, cap, dtype=np.int64)
    for i in extras:
        ii = int(i)
        if ii in chosen_set:
            continue
        chosen.append(ii)
        chosen_set.add(ii)
        if len(chosen) >= cap:
            break
    if len(chosen) < cap:
        step = max(1, n // cap)
        for i in range(0, n, step):
            if i in chosen_set:
                continue
            chosen.append(i)
            chosen_set.add(i)
            if len(chosen) >= cap:
                break
    return sorted(chosen)


def _scale_probe_count(sample_count, sample_n, total_n):
    if sample_n <= 0:
        return 0
    if sample_n >= total_n:
        return int(sample_count)
    return int(round(sample_count * total_n / sample_n))


def _probe_blf_dbc_frames(frames, dbc_paths, progress_callback=None):
    db = _load_dbc_database(dbc_paths)
    lookup = _cached_message_lookup(db)
    frame_ids = set()
    matched_frame_ids = set()
    matched_frame_count = 0

    total_frames = len(frames)
    progress_total = max(1, total_frames)
    step = max(1, progress_total // 80)
    _emit_progress(progress_callback, 0, progress_total)
    for index, (_t, aid, _payload) in enumerate(frames, 1):
        frame_ids.add(aid)
        if lookup(aid) is not None:
            matched_frame_count += 1
            matched_frame_ids.add(aid)
        if index % step == 0 or index == total_frames:
            _emit_progress(progress_callback, index, progress_total)

    indices = _probe_decode_indices(frames)
    sample_n = total_frames if isinstance(indices, range) else len(indices)
    sample_decoded = 0
    sample_signal_events = 0
    signal_names = set()
    decode_total = max(1, sample_n)
    decode_step = max(1, decode_total // 80)
    for decode_index, frame_index in enumerate(indices, 1):
        _t, aid, payload = frames[frame_index]
        msg = lookup(aid)
        if msg is None:
            if decode_index % decode_step == 0 or decode_index == decode_total:
                _emit_progress(progress_callback, progress_total, progress_total)
            continue
        decoded = _decode_can_payload(msg, payload)
        if not decoded:
            continue
        numeric_values = _numeric_decoded_values(decoded)
        if not numeric_values:
            continue
        sample_decoded += 1
        sample_signal_events += len(numeric_values)
        signal_names.update(sig_name for sig_name, _value in numeric_values)
        if decode_index % decode_step == 0 or decode_index == decode_total:
            _emit_progress(progress_callback, progress_total, progress_total)

    return BlfDbcProbe(
        dbc_paths=tuple(str(p) for p in dbc_paths),
        total_frame_count=total_frames,
        total_frame_id_count=len(frame_ids),
        matched_frame_count=matched_frame_count,
        matched_frame_id_count=len(matched_frame_ids),
        decoded_frame_count=_scale_probe_count(
            sample_decoded, sample_n, total_frames,
        ),
        decoded_signal_count=_scale_probe_count(
            sample_signal_events, sample_n, total_frames,
        ),
        signal_names=tuple(sorted(signal_names)),
    )


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
                disp = (
                    sig_name if len(sig_owners[sig_name]) <= 1
                    else f"{msg.name}.{sig_name}"
                )
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
