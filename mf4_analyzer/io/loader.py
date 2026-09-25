"""DataLoader: reads MF4 / Excel / CSV-like inputs."""
from collections import defaultdict
from collections.abc import Mapping
import importlib.util
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Public shared-axis column. A signal may also be named this; that collision
# is renamed and is never itself the time identity.
MF4_PUBLIC_TIME_COLUMN = "Time"

# Discoverability only — find_spec does not prove a native library is usable.
# Real format paths call ensure_* / import the engine and keep missing vs
# broken vs data-error outcomes distinct.
HAS_ASAMMDF = importlib.util.find_spec("asammdf") is not None
HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None
HAS_XLRD = importlib.util.find_spec("xlrd") is not None

# Populated by ensure_mdf(); tests may monkeypatch this attribute directly.
MDF = None


def _pandas():
    """Import pandas on first format path that needs a DataFrame."""
    import pandas as pd
    return pd


def ensure_mdf():
    """Load asammdf.MDF into this module, or raise a precise ImportError."""
    global MDF
    if MDF is not None:
        return MDF
    if importlib.util.find_spec("asammdf") is None:
        raise ImportError("asammdf not installed")
    try:
        from asammdf import MDF as _MDF
    except ImportError as exc:
        raise ImportError("asammdf not installed") from exc
    except Exception as exc:
        raise ImportError(
            f"asammdf is present but failed to import: {exc}"
        ) from exc
    MDF = _MDF
    return MDF


def __getattr__(name: str):
    # Keep ``mf4_analyzer.io.loader.BlfDbcProbe`` resolvable without pulling
    # blf_format (and its pandas import) into blank-startup import closure.
    if name == "BlfDbcProbe":
        from .blf_format import BlfDbcProbe
        return BlfDbcProbe
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _valid_mdf_channel_name(name):
    name = str(name)
    return bool(name.strip()) and not name.startswith('$')


def _channel_name_at(mdf, loc, fallback):
    group_idx, ch_idx = loc
    try:
        name = mdf.groups[group_idx].channels[ch_idx].name
    except Exception:
        name = fallback
    name = str(name or fallback)
    return name if _valid_mdf_channel_name(name) else str(fallback)


def _source_qualified_name_at(mdf, loc, base_name):
    group_idx, ch_idx = loc
    try:
        source = mdf.groups[group_idx].channels[ch_idx].source
        source_path = str(getattr(source, "path", "") or "")
    except Exception:
        source_path = ""
    return f"{source_path}.{base_name}" if source_path else ""


def _blank_time_facts():
    return {
        "input_count": None,
        "prepared_count": None,
        "nonfinite_time_removed": 0,
        "duplicate_time_removed": 0,
        "time_regression_count": 0,
        "input_range": None,
        "skip_reason": None,
    }


def _prepare_mdf_time_series(timestamps, samples):
    """Prepare one numeric series for the shared axis and return ``(prepared, facts)``.

    ``prepared`` is ``(time, values)`` or ``None``. A backward step is
    ``time-regression`` and is not sorted back together. Exact duplicate
    timestamps keep the last sample. Shape and length are checked before any
    numeric cast; nothing is flattened with ``reshape(-1)``.
    """
    facts = _blank_time_facts()
    time_axis = np.asarray(timestamps)
    values = np.asarray(samples)
    if (
        values.ndim != 1
        or time_axis.ndim != 1
        or getattr(values.dtype, "names", None)
        or getattr(values.dtype, "kind", "") == "c"
    ):
        facts["skip_reason"] = "non-1d"
        facts["input_count"] = int(values.size) if values.ndim > 0 else None
        return None, facts
    if values.size == 0 or time_axis.size == 0:
        facts["skip_reason"] = "empty"
        facts["input_count"] = int(values.size)
        return None, facts
    facts["input_count"] = int(values.size)
    if time_axis.size != values.size:
        facts["skip_reason"] = "length-mismatch"
        return None, facts
    if not np.issubdtype(values.dtype, np.number):
        facts["skip_reason"] = "non-numeric"
        return None, facts

    time_f = np.asarray(time_axis, dtype=np.float64)
    values_f = np.asarray(values, dtype=np.float64)
    finite_time = np.isfinite(time_f)
    facts["nonfinite_time_removed"] = int(np.count_nonzero(~finite_time))
    time_f = time_f[finite_time]
    values_f = values_f[finite_time]
    if time_f.size == 0:
        facts["skip_reason"] = "unusable-time"
        return None, facts
    facts["input_range"] = [float(np.min(time_f)), float(np.max(time_f))]
    if time_f.size > 1:
        steps = np.diff(time_f)
        facts["time_regression_count"] = int(np.count_nonzero(steps < 0))
        if facts["time_regression_count"]:
            facts["skip_reason"] = "time-regression"
            return None, facts
        keep_last = np.empty(time_f.size, dtype=bool)
        keep_last[-1] = True
        keep_last[:-1] = time_f[:-1] != time_f[1:]
        facts["duplicate_time_removed"] = int(time_f.size - np.count_nonzero(keep_last))
        time_f = time_f[keep_last]
        values_f = values_f[keep_last]
    facts["prepared_count"] = int(time_f.size)
    facts["input_range"] = [float(time_f[0]), float(time_f[-1])]
    return (time_f, values_f), facts


def prepare_shared_time_series(timestamps, samples):
    """Return ``(time, values)`` or ``None`` for shared-axis import.

    See :func:`_prepare_mdf_time_series` for the rejection rules. Duplicate
    timestamps keep the last sample. A backward step is rejected rather than
    sorted.
    """
    prepared, _facts = _prepare_mdf_time_series(timestamps, samples)
    return prepared


def _is_mdf_time_master(channel, version):
    """True for the group's time master, which is the X axis rather than a signal.

    MDF 2/3 masters are the time channel. MDF 4 time masters are
    ``MASTER`` / ``VIRTUAL_MASTER`` with ``sync_type == TIME``. An angle or
    distance master stays a signal.
    """
    if channel is None:
        return False
    kind = getattr(channel, "channel_type", None)
    text = str(version or "")
    if text.startswith("2") or text.startswith("3"):
        return kind == 1
    if kind not in (2, 3):
        return False
    return getattr(channel, "sync_type", None) == 1


def _mdf_channel_block(mdf, group_idx, ch_idx):
    try:
        return mdf.groups[group_idx].channels[ch_idx]
    except (AttributeError, IndexError, TypeError):
        return None


def _skip_mdf_channel(skipped, name, reason):
    skipped.append({"name": str(name), "reason": reason})


def _read_mdf_signal(mdf, ch_name, group_idx, ch_idx):
    """Read one physical ``(group, index)`` channel.

    Only file and asammdf parse failures become ``unreadable``. A display-name
    retry is intentionally absent: the same name can point at a different
    physical channel. ``ValueError`` and ``RuntimeError`` propagate.
    """
    del ch_name
    from asammdf.blocks.utils import MdfException

    try:
        return mdf.get(group=group_idx, index=ch_idx)
    except (OSError, MdfException):
        return None


def _format_name_list(names):
    unique = []
    for name in names:
        text = str(name)
        if text not in unique:
            unique.append(text)
    if not unique:
        return ""
    shown = "、".join(unique[:3])
    if len(unique) > 3:
        return f"{shown} 等 {len(unique)} 个通道"
    return shown


def _ranges_overlap(left, right):
    return not (left[1] < right[0] or right[1] < left[0])


def _alignment_channel(name, occurrence, facts, **extra):
    item = {
        "name": str(name),
        "physical_occurrence": [int(occurrence[0]), int(occurrence[1])],
        "input_count": facts.get("input_count"),
        "prepared_count": facts.get("prepared_count"),
        "nonfinite_time_removed": int(facts.get("nonfinite_time_removed") or 0),
        "duplicate_time_removed": int(facts.get("duplicate_time_removed") or 0),
        "time_regression_count": int(facts.get("time_regression_count") or 0),
        "input_range": facts.get("input_range"),
        "outside_reference_count": None,
        "endpoint_fill_count": None,
        "alignment": "skipped",
        "skip_reason": facts.get("skip_reason"),
    }
    item.update(extra)
    return item


def _mf4_alignment_warnings(items):
    """At most three file-level sentences. Full counts stay in ``items``."""
    warnings = []
    dup_names = [
        item["name"] for item in items if item["duplicate_time_removed"]
    ]
    dup_points = sum(item["duplicate_time_removed"] for item in items)
    nonfinite = sum(item["nonfinite_time_removed"] for item in items)
    prep = []
    if dup_points:
        prep.append(
            f"重复时间戳保留最后值（{_format_name_list(dup_names)}，合并 {dup_points} 点）"
        )
    if nonfinite:
        prep.append(f"移除了 {nonfinite} 个非有限时间点")
    if prep:
        warnings.append("时间整理：" + "；".join(prep))

    linear = [item["name"] for item in items if item["alignment"] == "linear"]
    lost = [
        item["name"]
        for item in items
        if item["outside_reference_count"]
    ]
    filled = [
        item["name"]
        for item in items
        if item["endpoint_fill_count"]
    ]
    cover = []
    if linear:
        cover.append(f"已按公共时间轴重采样（{_format_name_list(linear)}）")
    if lost:
        cover.append(f"{_format_name_list(lost)} 的部分时间范围未保留")
    if filled:
        cover.append(
            f"{_format_name_list(filled)} 使用了端点填充，填充部分不是原始测量"
        )
    if cover:
        warnings.append("；".join(cover))

    reason_text = {
        "time-regression": "因时间回退未导入",
        "single-sample": "因只有单点未并入",
        "no-time-overlap": "与公共轴没有重叠而未导入",
    }
    skip_bits = []
    for reason, text in reason_text.items():
        names = [
            item["name"]
            for item in items
            if item["alignment"] == "skipped" and item["skip_reason"] == reason
        ]
        if names:
            skip_bits.append(f"{_format_name_list(names)} {text}")
    if skip_bits:
        warnings.append("无法对齐：" + "；".join(skip_bits))
    return warnings[:3]


def _raise_unusable_mf4(skipped):
    logger.warning("MF4 import skipped every channel: %s", skipped)
    shown = skipped[:3]
    detail = "；".join(
        f"{entry['name']}（{entry['reason']}）" for entry in shown
    )
    extra = f" 等 {len(skipped)} 个通道" if len(skipped) > 3 else ""
    raise ValueError(f"没有可导入的数值通道：{detail}{extra}")


def _load_mf4_channels(mdf, channel_locations):
    version = getattr(mdf, "version", "")
    signal_names = []
    for ch_name, occurrence in channel_locations.items():
        group_idx, ch_idx = occurrence
        block = _mdf_channel_block(mdf, group_idx, ch_idx)
        if _is_mdf_time_master(block, version):
            continue
        signal_names.append((str(ch_name), (int(group_idx), int(ch_idx))))
    public_names, renamed = assign_mf4_public_signal_names(signal_names)
    skipped = []
    pending = []
    channel_metadata = {}
    for ch_name, occurrence in channel_locations.items():
        group_idx, ch_idx = occurrence
        block = _mdf_channel_block(mdf, group_idx, ch_idx)
        if _is_mdf_time_master(block, version):
            continue
        occurrence_key = (int(group_idx), int(ch_idx))
        ch_name = public_names[occurrence_key]
        source = getattr(block, "source", None) if block is not None else None
        channel_metadata[ch_name] = {
            "physical_occurrence": occurrence_key,
            "unit": None,
            "source_path": str(getattr(source, "path", "") or ""),
        }
        sig = _read_mdf_signal(mdf, ch_name, group_idx, ch_idx)
        if sig is None:
            _skip_mdf_channel(skipped, ch_name, "unreadable")
            continue
        samples = np.asarray([] if sig.samples is None else sig.samples)
        if samples.ndim != 1 or getattr(samples.dtype, "names", None):
            if samples.size == 0 and samples.ndim <= 1 and not getattr(samples.dtype, "names", None):
                _skip_mdf_channel(skipped, ch_name, "empty")
            else:
                _skip_mdf_channel(skipped, ch_name, "non-1d")
            continue
        if samples.size == 0:
            _skip_mdf_channel(skipped, ch_name, "empty")
            continue
        if getattr(samples.dtype, "kind", "") == "c":
            _skip_mdf_channel(skipped, ch_name, "non-1d")
            continue
        if not np.issubdtype(samples.dtype, np.number):
            _skip_mdf_channel(skipped, ch_name, "non-numeric")
            continue
        prepared, facts = _prepare_mdf_time_series(sig.timestamps, samples)
        record = {
            "name": ch_name,
            "occurrence": (int(group_idx), int(ch_idx)),
            "prepared": prepared,
            "facts": facts,
            "unit": _resolve_channel_unit(mdf, sig, group_idx, ch_idx),
        }
        pending.append(record)
        if prepared is None:
            _skip_mdf_channel(skipped, ch_name, facts["skip_reason"] or "unusable-time")

    usable = [record for record in pending if record["prepared"] is not None]
    if not usable:
        _raise_unusable_mf4(skipped)

    multi = [record for record in usable if record["prepared"][0].size >= 2]
    singles = [record for record in usable if record["prepared"][0].size < 2]
    if not multi:
        anchor = float(singles[0]["prepared"][0][0])
        if any(float(record["prepared"][0][0]) != anchor for record in singles[1:]):
            logger.warning(
                "MF4 single-sample channels disagree in time: %s",
                [(record["name"], float(record["prepared"][0][0])) for record in singles],
            )
            raise ValueError("单点通道时间不一致，无法在当前共享时间轴下合并")
        reference = singles[0]
    else:
        reference = multi[0]
        for record in multi[1:]:
            if record["prepared"][0].size > reference["prepared"][0].size:
                reference = record

    ref_t = reference["prepared"][0]
    ref_range = (float(ref_t[0]), float(ref_t[-1]))
    data = {MF4_PUBLIC_TIME_COLUMN: ref_t}
    loaded_units = {}
    alignment_items = []
    for record in pending:
        facts = record["facts"]
        prepared = record["prepared"]
        if prepared is None:
            alignment_items.append(
                _alignment_channel(record["name"], record["occurrence"], facts)
            )
            continue
        channel_time, values = prepared
        if multi and record is not reference and values.size < 2:
            facts = dict(facts)
            facts["skip_reason"] = "single-sample"
            _skip_mdf_channel(skipped, record["name"], "single-sample")
            alignment_items.append(
                _alignment_channel(record["name"], record["occurrence"], facts)
            )
            continue
        channel_range = (float(channel_time[0]), float(channel_time[-1]))
        if record is not reference and not _ranges_overlap(channel_range, ref_range):
            facts = dict(facts)
            facts["skip_reason"] = "no-time-overlap"
            _skip_mdf_channel(skipped, record["name"], "no-time-overlap")
            alignment_items.append(_alignment_channel(
                record["name"],
                record["occurrence"],
                facts,
                outside_reference_count=int(channel_time.size),
            ))
            continue
        outside = int(np.count_nonzero(
            (channel_time < ref_range[0]) | (channel_time > ref_range[1])
        ))
        endpoint_fill = int(np.count_nonzero(
            (ref_t < channel_range[0]) | (ref_t > channel_range[1])
        ))
        same_clock = (
            channel_time.shape == ref_t.shape
            and np.array_equal(channel_time, ref_t)
        )
        if same_clock:
            aligned = values
            how = "identity"
        else:
            aligned = np.interp(ref_t, channel_time, values)
            how = "linear"
        data[record["name"]] = aligned
        loaded_units[record["name"]] = record["unit"]
        channel_metadata[record["name"]]["unit"] = record["unit"]
        alignment_items.append(_alignment_channel(
            record["name"],
            record["occurrence"],
            facts,
            outside_reference_count=outside,
            endpoint_fill_count=endpoint_fill,
            alignment=how,
            skip_reason=None,
        ))

    if len(data) == 1:
        _raise_unusable_mf4(skipped)

    pd = _pandas()
    frame = pd.DataFrame(data)
    frame.attrs["source_metadata"] = {
        "source_kind": "mdf",
        "time_column": MF4_PUBLIC_TIME_COLUMN,
        "skipped_channels": skipped,
        "warnings": _mf4_alignment_warnings(alignment_items),
        "renamed_channels": renamed,
        "channel_metadata": channel_metadata,
        "mf4_alignment": {
            "policy": "shared-longest-axis-v1",
            "reference_occurrence": [
                int(reference["occurrence"][0]),
                int(reference["occurrence"][1]),
            ],
            "output_range": [ref_range[0], ref_range[1]],
            "channels": alignment_items,
        },
    }
    return frame, list(data.keys()), loaded_units


def unique_mdf_channel_locations(mdf):
    """Return display names mapped to unique MDF physical channel locations.

    asammdf exposes a source-path display name (``A_side.sig``) and the raw
    channel name (``sig``) for the same ``(group, index)`` occurrence. Collapse
    those aliases, but keep source-qualified names when the raw name is truly
    ambiguous across multiple physical channels.
    """
    loc_keys = {}
    loc_order = []
    for name, occurrences in mdf.channels_db.items():
        name = str(name)
        if not _valid_mdf_channel_name(name):
            continue
        for loc in occurrences:
            loc = tuple(loc)
            if loc not in loc_keys:
                loc_keys[loc] = []
                loc_order.append(loc)
            loc_keys[loc].append(name)

    base_locations = defaultdict(list)
    for loc in loc_order:
        base_name = _channel_name_at(mdf, loc, loc_keys[loc][0])
        base_locations[base_name].append(loc)

    channel_locations = {}
    for loc in loc_order:
        base_name = _channel_name_at(mdf, loc, loc_keys[loc][0])
        if len(base_locations[base_name]) == 1:
            display_name = base_name
        else:
            display_name = (
                _source_qualified_name_at(mdf, loc, base_name)
                or next(
                    (name for name in loc_keys[loc] if name != base_name),
                    base_name,
                )
            )
        if display_name in channel_locations:
            display_name = f"{display_name} [{loc[0]}:{loc[1]}]"
        channel_locations[display_name] = loc
    return channel_locations


def assign_mf4_public_signal_names(named_occurrences):
    """Return ``(public_by_occurrence, renamed_channels)`` for MF4 signals.

    Only a display name that is exactly :data:`MF4_PUBLIC_TIME_COLUMN` is
    renamed. Every original signal name and that axis name are reserved
    first; a taken ``Time [group:channel]`` gains a stable `` [n]`` suffix.
    Input order does not change the result, and the map does not depend on
    which samples later load. Time masters are not entries.
    """
    entries = []
    for name, occurrence in named_occurrences:
        group, channel = occurrence
        entries.append((str(name), (int(group), int(channel))))
    reserved = {name for name, _occurrence in entries}
    reserved.add(MF4_PUBLIC_TIME_COLUMN)
    public = {}
    renamed = []
    for name, occurrence in sorted(entries, key=lambda item: (item[1], item[0])):
        if name != MF4_PUBLIC_TIME_COLUMN:
            public[occurrence] = name
            continue
        candidate = f"Time [{occurrence[0]}:{occurrence[1]}]"
        if candidate in reserved or candidate in public.values():
            suffix = 2
            while True:
                suffixed = f"{candidate} [{suffix}]"
                if suffixed not in reserved and suffixed not in public.values():
                    candidate = suffixed
                    break
                suffix += 1
        public[occurrence] = candidate
        reserved.add(candidate)
        renamed.append({
            "original": name,
            "renamed": candidate,
            "physical_occurrence": [occurrence[0], occurrence[1]],
        })
    renamed.sort(key=lambda item: (
        item["physical_occurrence"][0],
        item["physical_occurrence"][1],
        item["renamed"],
    ))
    return public, renamed


def format_dropped_channels_notice(dropped):
    """Human-facing notice for channels dropped during load (non-FLOAT32 /
    all-NaN, recorded in ``source_metadata['dropped_channels']``).

    Returns ``""`` when nothing was dropped so the caller can gate the toast;
    otherwise a ``"N 个通道未导入：a、b"`` summary. Keeps the drop visible to
    the user instead of only living in metadata."""
    dropped = dropped or []
    if not dropped:
        return ""
    names = "、".join(str(d.get("name", "?")) for d in dropped)
    return f"{len(dropped)} 个通道未导入：{names}"


def _notice_names(entries):
    """Normalize str / ``{name: ...}`` load-skip entries into display names."""
    names = []
    for entry in entries or []:
        if isinstance(entry, Mapping):
            names.append(str(entry.get("name", "?")))
        else:
            names.append(str(entry))
    return names


def format_skipped_channels_notice(skipped):
    """Human-facing notice for WWT/TDMS ``skipped_channels`` (names or
    ``{name, reason}`` dicts). Empty → ``""`` so callers can gate the toast."""
    names = _notice_names(skipped)
    if not names:
        return ""
    return f"{len(names)} 个通道未导入：" + "、".join(names)


def format_skipped_vars_notice(skipped):
    """Human-facing notice for MAT ``skipped_vars``. Empty → ``""``."""
    names = _notice_names(skipped)
    if not names:
        return ""
    return f"{len(names)} 个变量未导入：" + "、".join(names)


def format_fs_estimated_notice(fs_estimated):
    """ZFD ``fs_estimated`` toast. Must contain 「估算」 when True; else ``""``."""
    if not fs_estimated:
        return ""
    return "⚠️ ZFD 时基无效，按 1 kHz 估算显示"


def format_renamed_channels_notice(renamed):
    """Summary for collision renames recorded in ``renamed_channels``.

    Exact product copy: ``N 个通道重名，已加序号区分``. Empty → ``""``."""
    renamed = renamed or []
    if not renamed:
        return ""
    return f"{len(renamed)} 个通道重名，已加序号区分"


def _resolve_channel_unit(mdf, sig, group_idx, ch_idx):
    """Return a channel unit, falling back to the MDF conversion block."""
    unit = str(getattr(sig, 'unit', '') or '')
    if unit:
        return unit
    try:
        channel = mdf.groups[group_idx].channels[ch_idx]
    except Exception:
        return ''
    conversion = getattr(channel, 'conversion', None)
    conv_unit = (
        str(getattr(conversion, 'unit', '') or '')
        if conversion is not None
        else ''
    )
    if conv_unit:
        return conv_unit
    return str(getattr(channel, 'unit', '') or '')


AUDIO_VIDEO_EXTS = {
    '.mp4', '.mov', '.mkv', '.m4v',
    '.mp3', '.m4a', '.aac', '.wav', '.flac',
}

# Product default for decoded audio/video tracks. PCM containers do not
# carry a sound-pressure calibration; this is an explicit NVH convention
# so the channel tree shows a unit and Auto dB reference can resolve to
# 20 µPa via ``is_audio_source`` (see ``db_reference`` R2). It is not a
# claim that sample values are already in pascals.
AUDIO_DEFAULT_UNIT = 'Pa'

CSV_LIKE_EXTS = {'.asc', '.csv', '.fdc'}

# Sentinel matched by ProjectIOMixin when re-raising empty CAN-log reads.
# Keep loader raises and mixin ``in str(exc)`` checks on the same constant.
NO_CAN_FRAMES_MESSAGE = "CAN 日志没有可读的数据帧"


class DataLoader:
    @staticmethod
    def read_blf_frames(fp, progress_callback=None, *, warning_callback=None):
        """Read one Vector CAN log (BLF / CANoe ASC) into reusable raw frames.

        Import coordinators that need to validate a DBC before decoding can
        keep these frames only for the current file, avoiding a second full
        reader pass.  Callers must treat the returned tuples as immutable.

        ``warning_callback``, when given, receives a single user-facing
        string if the CANoe ASC reader had to fall back to python-can
        (P1-2). It is only ever invoked for the ``.asc`` path; raw BLF reads
        have no equivalent fallback concept.
        """
        from .blf_format import _read_blf_frames

        if Path(fp).suffix.lower() == ".asc":
            from .asc_can_format import _read_asc_frames
            frames = _read_asc_frames(
                fp,
                progress_callback=progress_callback,
                warning_callback=warning_callback,
            )
        else:
            frames = _read_blf_frames(fp, progress_callback=progress_callback)
        if not frames:
            raise ValueError(NO_CAN_FRAMES_MESSAGE)
        return frames

    @staticmethod
    def probe_blf_dbc_frames(frames, dbc_paths, progress_callback=None, cancel_check=None):
        """Probe a DBC set against already-read CAN-log frames."""
        from .blf_format import _probe_blf_dbc_frames

        if not frames:
            raise ValueError(NO_CAN_FRAMES_MESSAGE)
        return _probe_blf_dbc_frames(
            frames,
            list(dbc_paths or []),
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    @staticmethod
    def load_blf_frames(frames, dbc_paths=None, progress_callback=None):
        """Decode a CAN-log frame list into a :class:`~mf4_analyzer.io.channel_frame.ChannelFrame`.

        This is the same semantic path as :meth:`load_blf`; a batch importer
        supplies its already-read frame list rather than reading the log again.
        Call :meth:`load_blf_dataframe` when a pandas ``DataFrame`` is required.
        """
        from .blf_format import _decode_blf_with_dbc, _raw_blf_channels

        if not frames:
            raise ValueError(NO_CAN_FRAMES_MESSAGE)
        t0 = min(frame[0] for frame in frames)
        if dbc_paths:
            return _decode_blf_with_dbc(
                frames,
                list(dbc_paths),
                t0,
                progress_callback=progress_callback,
            )
        return _raw_blf_channels(
            frames,
            t0,
            progress_callback=progress_callback,
        )

    @staticmethod
    def load_tdms(fp):
        """Load waveform-based NI TDMS data into the shared time-axis contract.

        TDMS permits each channel to carry its own waveform timing properties.
        This loader requires those properties instead of guessing a sample rate;
        the longest timed numeric signal becomes the reference axis and other
        timed signals are linearly resampled just as ``load_mf4`` does.
        """
        try:
            from nptdms import TdmsFile
        except ImportError as exc:
            raise ImportError(
                "nptdms is not installed; install the application's TDMS dependency"
            ) from exc

        def waveform_time(properties, sample_count):
            try:
                increment = float(properties["wf_increment"])
            except (KeyError, TypeError, ValueError):
                return None
            if not np.isfinite(increment) or increment <= 0:
                return None
            try:
                offset = float(properties.get("wf_start_offset", 0.0))
            except (TypeError, ValueError):
                return None
            if not np.isfinite(offset):
                return None
            return offset + increment * np.arange(sample_count, dtype=np.float64)

        tdms = TdmsFile.read(str(fp))
        raw_channels = []
        skipped = []
        name_counts = defaultdict(int)
        for group in tdms.groups():
            group_name = str(group.name or "Group")
            for channel in group.channels():
                values = np.asarray(channel[:])
                ch_label = str(channel.name or "Channel")
                display_skip = (
                    f"{group_name}.{ch_label}"
                    if group_name and group_name != "Group"
                    else ch_label
                )
                if values.ndim != 1:
                    skipped.append({"name": display_skip, "reason": "non-1d"})
                    continue
                if values.size == 0:
                    skipped.append({"name": display_skip, "reason": "empty"})
                    continue
                if not np.issubdtype(values.dtype, np.number):
                    skipped.append({"name": display_skip, "reason": "non-numeric"})
                    continue
                base_name = ch_label
                name_counts[base_name] += 1
                raw_channels.append({
                    "group": group_name,
                    "base_name": base_name,
                    "values": values.astype(np.float64, copy=False),
                    "time": waveform_time(channel.properties, values.size),
                    "unit": str(channel.properties.get("unit_string", "") or ""),
                })

        if not raw_channels:
            raise ValueError("TDMS file has no non-empty numeric channels")

        untimed = [entry["base_name"] for entry in raw_channels if entry["time"] is None]
        if untimed:
            raise ValueError(
                "TDMS numeric channels have no waveform timing metadata: "
                + ", ".join(untimed)
            )

        reference = max(raw_channels, key=lambda entry: entry["values"].size)
        reference_time = reference["time"]
        data = {"Time": reference_time}
        units = {}
        used_names = {"Time"}
        renamed = []
        for index, entry in enumerate(raw_channels, 1):
            base_name = entry["base_name"]
            preferred = (
                base_name
                if name_counts[base_name] == 1
                else f"{entry['group']}.{base_name}"
            )
            display_name = preferred
            if display_name in used_names:
                display_name = f"{display_name} [{index}]"
            if display_name != base_name:
                renamed.append({"original": base_name, "renamed": display_name})
            used_names.add(display_name)

            channel_time = entry["time"]
            values = entry["values"]
            if np.array_equal(channel_time, reference_time):
                data[display_name] = values
            else:
                data[display_name] = np.interp(reference_time, channel_time, values)
            units[display_name] = entry["unit"]

        smeta = {
            "source_kind": "tdms",
            "source_filename": Path(fp).name,
            "skipped_channels": skipped,
            "renamed_channels": renamed,
        }
        pd = _pandas()
        return pd.DataFrame(data), list(data.keys()), units, None, smeta

    @staticmethod
    def load_mf4(fp):
        """Load numeric MF4/MDF channels onto one shared ``Time`` column.

        The longest prepared numeric series is the reference axis. Other
        series are copied only when their timestamps match that axis, and
        otherwise linearly interpolated when the ranges overlap. Duplicate
        timestamps keep the last sample. A backward step, a single sample on
        a longer axis, and a channel with no time overlap are skipped and
        recorded. Diagnostics live on
        ``DataFrame.attrs['source_metadata']``, including ``time_column``
        (exact axis identity) and ``renamed_channels`` when a signal occupied
        that name. Time masters are the X axis and are not signal columns.
        """
        mdf = ensure_mdf()(fp)
        try:
            channel_locations = unique_mdf_channel_locations(mdf)
            if not channel_locations:
                raise ValueError("No channels")
            return _load_mf4_channels(mdf, channel_locations)
        finally:
            mdf.close()

    @staticmethod
    def load_blf(fp, dbc_paths=None, progress_callback=None):
        """Load a Vector CAN log (BLF / CANoe ASC) as a ChannelFrame.

        Returns ``(frame, channels, units)`` where ``frame`` is a
        :class:`~mf4_analyzer.io.channel_frame.ChannelFrame` (currently a
        lazy ZOH implementation). It is not a pandas ``DataFrame``. Use
        :meth:`load_blf_dataframe` to opt in to full-table materialization.

        With ``dbc_paths`` (one or more ``.dbc``), frames are decoded into named
        physical signals via cantools. Without a DBC, payload bytes are exposed
        per CAN id (``0x1F3.byte0`` …) so traffic is still viewable. Signal
        columns zero-order-hold onto one shared ``Time`` axis when read.

        A2L is deliberately not involved: plain CAN signals decode from a DBC,
        which is a separate, lighter database than the XCP-measurement A2L.
        """
        from .blf_format import _emit_progress

        def map_read(current, total):
            _emit_progress(
                progress_callback,
                (400 * current) // max(1, total),
                1000,
            )

        def map_decode(current, total):
            _emit_progress(
                progress_callback,
                400 + (600 * current) // max(1, total),
                1000,
            )

        frames = DataLoader.read_blf_frames(fp, progress_callback=map_read)
        return DataLoader.load_blf_frames(
            frames,
            dbc_paths=dbc_paths,
            progress_callback=map_decode,
        )

    @staticmethod
    def load_blf_dataframe(fp, dbc_paths=None, progress_callback=None):
        """Load a CAN log and materialize every column into a pandas DataFrame.

        Prefer :meth:`load_blf` when only some channels will be read. This
        entry point exists for callers that need pandas row semantics and
        accept the ZOH expansion cost.
        """
        data, channels, units = DataLoader.load_blf(
            fp,
            dbc_paths=dbc_paths,
            progress_callback=progress_callback,
        )
        pd = _pandas()
        if hasattr(data, "to_pandas"):
            data = data.to_pandas()
        elif not isinstance(data, pd.DataFrame):
            raise TypeError(
                "load_blf_dataframe expected a ChannelFrame or pandas DataFrame, "
                f"got {type(data)!r}"
            )
        return data, channels, units

    @staticmethod
    def probe_blf_dbc(fp, dbc_paths, progress_callback=None, cancel_check=None):
        """Return a lightweight compatibility probe for a BLF and DBC path list."""
        from .blf_format import _emit_progress

        def map_read(current, total):
            _emit_progress(
                progress_callback,
                (500 * current) // max(1, total),
                1000,
            )

        def map_probe(current, total):
            _emit_progress(
                progress_callback,
                500 + (500 * current) // max(1, total),
                1000,
            )

        frames = DataLoader.read_blf_frames(fp, progress_callback=map_read)
        return DataLoader.probe_blf_dbc_frames(
            frames,
            dbc_paths,
            progress_callback=map_probe,
            cancel_check=cancel_check,
        )

    @staticmethod
    def load_audio_video(fp):
        try:
            import av
        except ImportError as exc:
            from .source_adapters import optional_native_import_message

            raise ImportError(
                optional_native_import_message("av", adapter_key="media")
            ) from exc

        container = av.open(str(fp))
        stream = None
        container_name = ''
        codec_name = ''
        fs = None
        chunks = None

        def channel_count_from(*objects):
            for obj in objects:
                if obj is None:
                    continue
                channels = getattr(obj, 'channels', None)
                if isinstance(channels, int) and channels > 0:
                    return int(channels)
                try:
                    count = len(channels)
                except Exception:
                    count = 0
                if count > 0:
                    return int(count)
            return 0

        def resampled_frames(result):
            if result is None:
                return ()
            if isinstance(result, (list, tuple)):
                return result
            return (result,)

        def append_frame(frame):
            nonlocal chunks, fs
            arr = np.asarray(frame.to_ndarray(), dtype=np.float32)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.ndim != 2:
                arr = arr.reshape(1, -1)
            if chunks is None:
                chunks = [[] for _ in range(arr.shape[0])]
            elif arr.shape[0] != len(chunks) and arr.shape[1] == len(chunks):
                arr = arr.T
            take = min(len(chunks), arr.shape[0])
            for ci in range(take):
                chunks[ci].append(arr[ci].astype(np.float32, copy=False))
            if fs is None:
                sample_rate = getattr(frame, 'sample_rate', None)
                if sample_rate:
                    fs = float(sample_rate)

        try:
            streams = list(container.streams.audio)
            if not streams:
                raise ValueError("文件不含音轨")
            stream = streams[0]
            codec_context = getattr(stream, 'codec_context', None)
            layout = getattr(stream, 'layout', None) or getattr(codec_context, 'layout', None)
            fs = getattr(stream, 'rate', None) or getattr(codec_context, 'rate', None)
            fs = float(fs) if fs else None
            container_name = str(getattr(getattr(container, 'format', None), 'name', '') or '')
            codec_name = str(getattr(codec_context, 'name', '') or '')
            expected_channels = channel_count_from(stream, codec_context, layout)
            if expected_channels > 0:
                chunks = [[] for _ in range(expected_channels)]

            resampler_kwargs = {'format': 'fltp'}
            if layout is not None:
                resampler_kwargs['layout'] = layout
            resampler = av.AudioResampler(**resampler_kwargs)

            for frame in container.decode(stream):
                for out_frame in resampled_frames(resampler.resample(frame)):
                    append_frame(out_frame)
            for out_frame in resampled_frames(resampler.resample(None)):
                append_frame(out_frame)
        finally:
            container.close()

        if chunks is None:
            chunks = []
        cols = [
            np.concatenate(parts).astype(np.float32, copy=False)
            if parts else np.zeros(0, dtype=np.float32)
            for parts in chunks
        ]
        n = min((len(col) for col in cols), default=0)
        cols = [col[:n].astype(np.float32, copy=False) for col in cols]
        n_ch = len(cols)

        if n_ch == 1:
            names = ['audio']
        elif n_ch == 2:
            names = ['L', 'R']
        else:
            names = [f'ch{i}' for i in range(n_ch)]

        pd = _pandas()
        data = pd.DataFrame({name: col for name, col in zip(names, cols)})
        units = {name: AUDIO_DEFAULT_UNIT for name in names}
        fs = float(fs or 0.0)
        if fs <= 0.0:
            # No usable sample rate from the container/codec/frames. Returning
            # fs=0 would make FileData build a time axis as arange(n)/0 -> inf
            # and silently corrupt every downstream analysis. Fail loudly so
            # _load_one surfaces it instead.
            raise ValueError("无法确定音频采样率（文件未提供有效的采样率）")
        source_metadata = {
            'source_kind': 'audio',
            'container': container_name,
            'codec': codec_name,
            'fs': fs,
            'channels': n_ch,
        }
        return data, names, units, fs, source_metadata

    @staticmethod
    def load_csv(fp):
        from mf4_analyzer.io.csv_format import sniff_csv_layout

        layout = None
        try:
            layout = sniff_csv_layout(fp)
        except Exception:
            layout = None
        if layout is not None and not layout.is_trivial:
            return DataLoader._load_csv_with_layout(fp, layout)

        pd = _pandas()
        df = None
        for enc in ['utf-8', 'gbk', 'latin1']:
            for sep in [',', ';', '\t']:
                try:
                    df = pd.read_csv(fp, encoding=enc, sep=sep)
                    if len(df.columns) > 1: break
                except:
                    continue
            if df is not None and len(df.columns) > 1: break
        if df is None: raise ValueError("Cannot parse CSV")
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(axis=1, how='all').interpolate().dropna()
        if df.empty or len(df.columns) < 1:
            raise ValueError("Cannot parse CSV")
        return df, list(df.columns), {}

    @staticmethod
    def load_ascii(fp):
        """Load a tabular ASCII file, retaining detector evidence."""
        from mf4_analyzer.io.asc_can_format import sniff_canoe_asc
        from mf4_analyzer.io.ascii_format import has_time_column, sniff_fixed_width_ascii

        if sniff_canoe_asc(fp):
            raise ValueError(
                "该 .asc 是 CANoe CAN 总线日志：请配 DBC 按 CAN 日志流程解码"
                "（主窗口打开或批处理导入均可）"
            )

        layout = sniff_fixed_width_ascii(fp)
        if layout is None:
            try:
                data, channels, units = DataLoader.load_csv(fp)
            except ValueError as exc:
                raise ValueError("Cannot detect a supported ASCII table layout") from exc
            if not has_time_column(channels):
                raise ValueError("ASCII file has no time column or verified sampling rate")
            return data, channels, units, None, {
                "source_kind": "ascii", "ascii_kind": "delimited", "ascii_confidence": "high",
            }

        header_line = Path(fp).read_text(encoding=layout.encoding, errors="replace").splitlines()
        raw_headers = [header_line[layout.header_row][a:b].strip() for a, b in layout.colspecs]
        channels, seen = [], set()
        for index, raw in enumerate(raw_headers, 1):
            base = raw or f"Column{index}"
            name, suffix = base, 2
            while name in seen:
                name = f"{base}_{suffix}"; suffix += 1
            seen.add(name); channels.append(name)
        units = {}
        if layout.units_row is not None:
            for name, (a, b) in zip(channels, layout.colspecs):
                unit = header_line[layout.units_row][a:b].strip()
                if unit:
                    units[name] = unit
        pd = _pandas()
        data = pd.read_fwf(fp, colspecs=list(layout.colspecs), skiprows=layout.data_row,
                           header=None, names=channels, encoding=layout.encoding)
        for channel in channels:
            data[channel] = pd.to_numeric(data[channel], errors="coerce")
        if data.empty or data.notna().all(axis=1).sum() == 0:
            raise ValueError("Cannot parse fixed-width ASCII data")
        fs = 1.0 / layout.sample_interval if layout.sample_interval else None
        if fs is None and not has_time_column(channels):
            raise ValueError("ASCII file has no time column or verified sampling rate")
        return data, channels, units, fs, {
            "source_kind": "ascii", "ascii_kind": "fixed_width",
            "ascii_confidence": layout.confidence, "ascii_data_row": layout.data_row,
        }

    @staticmethod
    def _load_csv_with_layout(fp, layout):
        import csv as _csv
        import io as _io

        pd = _pandas()
        skiprows = list(range(layout.header_row))
        if layout.units_row is not None:
            skiprows.append(layout.units_row)

        try:
            df = pd.read_csv(
                fp,
                encoding=layout.encoding,
                sep=layout.sep,
                skiprows=skiprows,
                header=0,
                decimal=layout.decimal,
            )
        except Exception as exc:
            raise ValueError("Cannot parse CSV") from exc

        units = {}
        if layout.units_row is not None:
            try:
                text = Path(fp).read_text(encoding=layout.encoding, errors="replace")
                lines = text.splitlines()
                header_cells = next(
                    _csv.reader(
                        _io.StringIO(lines[layout.header_row]),
                        delimiter=layout.sep,
                    )
                )
                unit_cells = next(
                    _csv.reader(
                        _io.StringIO(lines[layout.units_row]),
                        delimiter=layout.sep,
                    )
                )
                units = {
                    header.strip(): unit.strip()
                    for header, unit in zip(header_cells, unit_cells)
                    if header.strip() and unit.strip()
                }
            except Exception:
                units = {}

        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(axis=1, how='all').interpolate().dropna()
        if df.empty or len(df.columns) < 1:
            raise ValueError("Cannot parse CSV")
        return df, list(df.columns), units

    @staticmethod
    def load_excel(fp):
        extension = Path(fp).suffix.lower()
        if extension == '.xlsx':
            if not HAS_OPENPYXL:
                raise ImportError("openpyxl is required to read .xlsx files")
            try:
                import openpyxl  # noqa: F401 - verify + freeze-scan declaration
            except ImportError as exc:
                raise ImportError("openpyxl is required to read .xlsx files") from exc
            except Exception as exc:
                raise ImportError(
                    f"openpyxl is present but failed to import: {exc}"
                ) from exc
            engine = 'openpyxl'
        elif extension == '.xls':
            if not HAS_XLRD:
                raise ImportError("xlrd is required to read legacy .xls files")
            try:
                import xlrd  # noqa: F401 - verify + freeze-scan declaration
            except ImportError as exc:
                raise ImportError("xlrd is required to read legacy .xls files") from exc
            except Exception as exc:
                raise ImportError(
                    f"xlrd is present but failed to import: {exc}"
                ) from exc
            engine = 'xlrd'
        else:
            raise ValueError(f"unsupported Excel extension: {extension or '<none>'}")
        pd = _pandas()
        df = pd.read_excel(fp, engine=engine)
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(how='all').interpolate().ffill().bfill().reset_index(drop=True)
        return df, list(df.columns), {}

    @staticmethod
    def load_wwt(fp):
        """WinWert .wwt：返回与 load_hdf 同形状的 groups 列表。"""
        from .wwt_format import load_wwt_groups
        return load_wwt_groups(fp)

    @staticmethod
    def load_wwt_document(fp):
        """WinWert .wwt：正文分组 + 显示块/公式文档，只读一次文件。"""
        from .wwt_document import load_wwt_document as _load_wwt_document
        return _load_wwt_document(fp)

    @staticmethod
    def load_zfd(fp):
        """ZFGE2 .zfd（ZwickRoell/TestRunPRO）：返回与 load_hdf 同形状的 groups。"""
        from .zfd_format import load_zfd_groups
        return load_zfd_groups(fp)

    @staticmethod
    def load_mat(fp):
        """MATLAB .mat：返回与 load_hdf 同形状的 groups 列表。"""
        from .mat_format import load_mat_groups
        return load_mat_groups(fp)

    @staticmethod
    def load_hdf(fp):
        from .head_hdf import full_channel_name as head_full_channel_name, parse_head_hdf

        hf = parse_head_hdf(fp)
        max_factor = max((f for _, f in hf.ch_order), default=1)
        # 时间轴绝对尺度：delta 是「一个 scan 内交织浮点槽」的间隔，所以一个 scan
        # 跨 delta×per_scan（per_scan = 每 scan 总浮点数 = Σ 所有通道 factor，含被丢的
        # 非 FLOAT32 / 全 NaN 通道——它们仍占二进制槽位），factor-f 通道采样周期
        # = (delta×per_scan)/factor。早先误用 max_factor 代替 per_scan，使时间轴短了
        # per_scan/max_factor 倍、fs 同比偏大（真实文件实测应 ~50 s / 48 kHz，而非
        # ~9 s / 129.5 kHz）。绝对尺度已对标真实文件确认，勿改回 max_factor。
        per_scan = sum(f for _, f in hf.ch_order)

        # 标定 + 丢全 NaN；收集被丢通道名+原因（不静默丢弃）。带 1-based 文件内
        # 序号 idx：HEAD 的 name str 截断到 16 字符会让物理不同的通道塌成同名，
        # 序号是最后的消歧兜底（moniker / physical_channel_nbr 实测常为同值）。
        # 正常路径已不靠它——full_channel_name 从 `ext name str` 取回了全名。
        live = []
        dropped = []
        for idx, c in enumerate(hf.channels, 1):
            if c.samples is None:
                # samples=None means non-FLOAT32 impl_type (skipped in demux)
                reason = (f"non-FLOAT32: {c.impl_type}"
                          if c.impl_type and c.impl_type != "FLOAT32"
                          else "no samples (unknown)")
                dropped.append(
                    {"name": head_full_channel_name(c), "reason": reason}
                )
                continue
            # HEAD FLOAT32 样本本身已是物理工程值；calibration 是元数据，
            # 不可当作对原始样本的乘法增益（旧 bug 会把转角/转速/扭矩放大到
            # 荒唐量级，且 calibration=0 的通道被 ×0 抹零）。仅保留原始 samples，
            # calibration 仍存入 channel_metadata 供显示/参考。
            s = c.samples
            if np.isnan(s).all():
                dropped.append(
                    {"name": head_full_channel_name(c), "reason": "all-NaN"}
                )
                continue
            live.append((idx, c, s))

        # RPM 源（speed of rotation 且非全 0）
        rpm = next((s for _i, c, s in live
                    if "speed of rotation" in c.quantity.lower()
                    and np.any(s != 0)), None)
        rpm_factor = next((c.factor for _i, c, s in live
                           if "speed of rotation" in c.quantity.lower()
                           and np.any(s != 0)), None)

        def axis(factor, length):
            period = hf.delta * (per_scan / factor)
            return hf.first_value + np.arange(length, dtype=float) * period

        groups = []
        by_factor = {}
        for idx, c, s in live:
            by_factor.setdefault(c.factor, []).append((idx, c, s))

        for factor, items in sorted(by_factor.items(), reverse=True):
            length = items[0][2].size
            t = axis(factor, length)
            data = {"Time": t}
            units = {}
            cmeta = {}
            renamed = []
            for idx, c, s in items:
                # 组内去重：`name str` 截断出的同名（如 4 个 Com_Motor_Torque）
                # 不能用同一 dict 键——否则后者覆盖前者、真实数据被全 0 通道盖掉。
                # full_channel_name 走 `ext name str`，已经把这类碰撞在源头解开；
                # 下面两级兜底留给真同名（同一信号采两路）和无 ext 行的老文件：
                # 先退回带来源标记的完整 ext 名（天然唯一），再退回文件内序号。
                preferred = head_full_channel_name(c)
                name = preferred
                if name in data:
                    qualified = (c.ext_name or "").strip()
                    if qualified and qualified not in data:
                        name = qualified
                    else:
                        name = f"{name} [{idx}]"
                        while name in data:
                            name = f"{name}_"
                    renamed.append({"original": preferred, "renamed": name})
                data[name] = s
                units[name] = c.unit
                cmeta[name] = {
                    "quantity": c.quantity, "unit": c.unit,
                    "calibration": c.calibration,
                    "db_reference": c.db_reference, "moniker": c.moniker,
                    # 原始 `name str`（16 字符截断值）留档：老工程文件按它存过
                    # 通道键，排查「通道对不上」时要能查回去。
                    "head_name_str": c.name, "ext_name": c.ext_name,
                    "physical_channel_nbr": c.physical_channel_nbr,
                    "raster_factor": c.factor, "impl_type": c.impl_type,
                    "equalization": c.equalization, "emphasis": c.emphasis,
                }
            # 转速注入：仅注入到含 acceleration 的组、且本组不是转速所在组
            has_acc = any("acceleration" in c.quantity.lower() for _i, c, _s in items)
            if rpm is not None and has_acc and factor != rpm_factor:
                rpm_t = axis(rpm_factor, rpm.size)
                inj = np.interp(t, rpm_t, rpm)
                data["SP (rpm-injected)"] = inj
                units["SP (rpm-injected)"] = "deg/s"
                cmeta["SP (rpm-injected)"] = {"quantity": "speed of rotation",
                                              "raster_factor": factor,
                                              "injected": True}
            smeta = {
                "recording_date": hf.recording_date, "timezone": hf.timezone,
                "version": hf.version, "release": hf.release,
                "kind": hf.kind, "scan_mode": hf.scan_mode,
                "code_page": hf.code_page, "delta": hf.delta,
                "n_scans": hf.n_scans, "max_factor": max_factor,
                "per_scan": per_scan,
                "source_filename": Path(fp).name,
                "dropped_channels": dropped,
                "renamed_channels": renamed,
            }
            if hf.warnings:
                smeta["warnings"] = list(hf.warnings)
            pd = _pandas()
            groups.append({
                "data": pd.DataFrame(data), "channels": list(data.keys()),
                "units": units, "channel_metadata": cmeta,
                "source_metadata": smeta, "label_suffix": f"{factor}x",
            })
        if not groups:
            raise ValueError("HEAD .hdf: no live channels after NaN drop")
        return groups
