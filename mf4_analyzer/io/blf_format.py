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


def _assemble_blf_channels(series, units, t0, progress_callback=None):
    """Fold per-signal ``{name: (abs_t, v)}`` into the shared-time-axis frame.

    Mirrors ``load_mf4``: the longest series (most samples) defines the common
    ``Time`` axis and every other signal is ZOH-resampled onto it. All
    timestamps are shifted to start at zero via ``t0``.
    """
    ref_name = max(series, key=lambda k: series[k][0].size)
    ref_t = np.sort(series[ref_name][0] - t0, kind="stable")
    data = {"Time": ref_t}
    total_series = max(1, len(series))
    report_step = max(1, total_series // 80)
    _emit_progress(progress_callback, 0, total_series)
    for index, (name, (t, v)) in enumerate(series.items(), 1):
        rel_t = t - t0
        order = np.argsort(rel_t, kind="stable")
        data[name] = _zoh_resample(ref_t, rel_t[order], v[order])
        if index % report_step == 0 or index == total_series:
            _emit_progress(progress_callback, index, total_series)
    return pd.DataFrame(data), list(data.keys()), units


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


def _probe_blf_dbc_frames(frames, dbc_paths, progress_callback=None):
    db = _load_dbc_database(dbc_paths)
    frame_ids = {aid for _t, aid, _payload in frames}
    matched_frame_ids = set()
    matched_frame_count = 0
    decoded_frame_count = 0
    decoded_signal_count = 0
    signal_names = set()

    total_frames = max(1, len(frames))
    step = max(1, total_frames // 80)
    _emit_progress(progress_callback, 0, total_frames)
    for index, (_t, aid, payload) in enumerate(frames, 1):
        try:
            msg = db.get_message_by_frame_id(aid)
        except KeyError:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index, total_frames)
            continue
        matched_frame_count += 1
        matched_frame_ids.add(aid)
        decoded = _decode_can_payload(msg, payload)
        if not decoded:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index, total_frames)
            continue
        numeric_values = _numeric_decoded_values(decoded)
        if not numeric_values:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index, total_frames)
            continue
        decoded_frame_count += 1
        decoded_signal_count += len(numeric_values)
        signal_names.update(sig_name for sig_name, _value in numeric_values)
        if index % step == 0 or index == total_frames:
            _emit_progress(progress_callback, index, total_frames)

    return BlfDbcProbe(
        dbc_paths=tuple(str(p) for p in dbc_paths),
        total_frame_count=len(frames),
        total_frame_id_count=len(frame_ids),
        matched_frame_count=matched_frame_count,
        matched_frame_id_count=len(matched_frame_ids),
        decoded_frame_count=decoded_frame_count,
        decoded_signal_count=decoded_signal_count,
        signal_names=tuple(sorted(signal_names)),
    )


def _decode_blf_with_dbc(frames, dbc_paths, t0, progress_callback=None):
    """Decode raw CAN frames into named physical signals using one or more DBCs."""
    db = _load_dbc_database(dbc_paths)

    # A signal name in more than one message is ambiguous; qualify only those
    # as ``<Message>.<Signal>`` so the common-case unique names stay short.
    sig_owners = defaultdict(set)
    for m in db.messages:
        for s in m.signals:
            sig_owners[s.name].add(m.name)

    t_lists = defaultdict(list)
    v_lists = defaultdict(list)
    units = {}
    total_frames = max(1, len(frames))
    step = max(1, total_frames // 80)
    _emit_progress(progress_callback, 0, 1000)
    for index, (t, aid, payload) in enumerate(frames, 1):
        try:
            msg = db.get_message_by_frame_id(aid)
        except KeyError:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index * 850 // total_frames, 1000)
            continue  # frame id not in this DBC
        decoded = _decode_can_payload(msg, payload)
        if not decoded:
            if index % step == 0 or index == total_frames:
                _emit_progress(progress_callback, index * 850 // total_frames, 1000)
            continue  # CRC/length/multiplex mismatch on this frame
        for sig_name, fval in _numeric_decoded_values(decoded):
            disp = (
                sig_name if len(sig_owners[sig_name]) <= 1
                else f"{msg.name}.{sig_name}"
            )
            t_lists[disp].append(t)
            v_lists[disp].append(fval)
            if disp not in units:
                sig_obj = next((s for s in msg.signals if s.name == sig_name), None)
                units[disp] = str(getattr(sig_obj, "unit", "") or "")
        if index % step == 0 or index == total_frames:
            _emit_progress(progress_callback, index * 850 // total_frames, 1000)

    if not t_lists:
        raise ValueError(
            "选中的 DBC 与该 BLF 不匹配：没有任何帧被解码成功。\n"
            "请确认 DBC 是否对应这条总线，或重新打开时跳过 DBC、以原始字节查看。"
        )
    series = {
        name: (
            np.asarray(t_lists[name], dtype=np.float64),
            np.asarray(v_lists[name], dtype=np.float64),
        )
        for name in t_lists
    }
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
