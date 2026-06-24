"""DataLoader: reads MF4 / Excel / CSV inputs."""
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from .head_hdf import parse_head_hdf

try:
    from asammdf import MDF

    HAS_ASAMMDF = True
except ImportError:
    HAS_ASAMMDF = False

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


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


def _read_blf_frames(fp):
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
    try:
        for msg in reader:
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


def _assemble_blf_channels(series, units, t0):
    """Fold per-signal ``{name: (abs_t, v)}`` into the shared-time-axis frame.

    Mirrors ``load_mf4``: the longest series (most samples) defines the common
    ``Time`` axis and every other signal is ZOH-resampled onto it. All
    timestamps are shifted to start at zero via ``t0``.
    """
    ref_name = max(series, key=lambda k: series[k][0].size)
    ref_t = np.sort(series[ref_name][0] - t0, kind="stable")
    data = {"Time": ref_t}
    for name, (t, v) in series.items():
        rel_t = t - t0
        order = np.argsort(rel_t, kind="stable")
        data[name] = _zoh_resample(ref_t, rel_t[order], v[order])
    return pd.DataFrame(data), list(data.keys()), units


def _decode_blf_with_dbc(frames, dbc_paths, t0):
    """Decode raw CAN frames into named physical signals using one or more DBCs."""
    try:
        import cantools
    except ImportError as exc:
        raise ImportError(
            "cantools 未安装，无法用 DBC 解码 BLF。请先 pip install cantools"
        ) from exc
    db = cantools.database.Database()
    for path in dbc_paths:
        db.add_dbc_file(str(path))

    # A signal name in more than one message is ambiguous; qualify only those
    # as ``<Message>.<Signal>`` so the common-case unique names stay short.
    sig_owners = defaultdict(set)
    for m in db.messages:
        for s in m.signals:
            sig_owners[s.name].add(m.name)

    t_lists = defaultdict(list)
    v_lists = defaultdict(list)
    units = {}
    for t, aid, payload in frames:
        try:
            msg = db.get_message_by_frame_id(aid)
        except KeyError:
            continue  # frame id not in this DBC
        try:
            decoded = msg.decode(payload, decode_choices=False, allow_truncated=True)
        except TypeError:
            # older cantools without allow_truncated
            try:
                decoded = msg.decode(payload, decode_choices=False)
            except Exception:
                continue
        except Exception:
            continue  # CRC/length/multiplex mismatch on this frame
        for sig_name, value in decoded.items():
            try:
                fval = float(value)
            except (TypeError, ValueError):
                continue  # non-numeric (e.g. unresolved choice string)
            disp = (
                sig_name if len(sig_owners[sig_name]) <= 1
                else f"{msg.name}.{sig_name}"
            )
            t_lists[disp].append(t)
            v_lists[disp].append(fval)
            if disp not in units:
                sig_obj = next((s for s in msg.signals if s.name == sig_name), None)
                units[disp] = str(getattr(sig_obj, "unit", "") or "")

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
    return _assemble_blf_channels(series, units, t0)


def _raw_blf_channels(frames, t0):
    """Database-free fallback: expose each CAN id's payload bytes as channels
    (``0x1F3.byte0`` …). Values are raw bytes (0–255), not engineering units —
    enough to eyeball traffic when no DBC is supplied."""
    by_id_t = defaultdict(list)
    by_id_d = defaultdict(list)
    for t, aid, payload in frames:
        by_id_t[aid].append(t)
        by_id_d[aid].append(payload)

    series = {}
    units = {}
    for aid, payloads in by_id_d.items():
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
    if not series:
        raise ValueError("BLF 帧不含可解析的数据字节")
    return _assemble_blf_channels(series, units, t0)


class DataLoader:
    @staticmethod
    def load_mf4(fp):
        if not HAS_ASAMMDF: raise ImportError("asammdf not installed")
        mdf = MDF(fp)

        # 收集所有通道及其位置信息
        channel_locations = unique_mdf_channel_locations(mdf)

        if not channel_locations:
            mdf.close()
            raise ValueError("No channels")

        max_len, ref_ts, sigs, units = 0, None, {}, {}

        for ch_name, (group_idx, ch_idx) in channel_locations.items():
            try:
                sig = mdf.get(group=group_idx, index=ch_idx)
                if sig.samples is not None and len(sig.samples) > 0 and np.issubdtype(sig.samples.dtype, np.number):
                    s = sig.samples.flatten() if len(sig.samples.shape) > 1 else sig.samples
                    sigs[ch_name] = {'s': np.asarray(s, dtype=np.float64), 't': np.asarray(sig.timestamps, dtype=np.float64)}
                    units[ch_name] = _resolve_channel_unit(mdf, sig, group_idx, ch_idx)
                    if len(sig.timestamps) > max_len:
                        max_len = len(sig.timestamps)
                        ref_ts = sigs[ch_name]['t']
            except Exception as e:
                # 如果带group/index失败，尝试不带参数（兼容旧版本）
                try:
                    sig = mdf.get(ch_name)
                    if sig.samples is not None and len(sig.samples) > 0 and np.issubdtype(sig.samples.dtype, np.number):
                        s = sig.samples.flatten() if len(sig.samples.shape) > 1 else sig.samples
                        sigs[ch_name] = {'s': np.asarray(s, dtype=np.float64), 't': np.asarray(sig.timestamps, dtype=np.float64)}
                        units[ch_name] = _resolve_channel_unit(mdf, sig, group_idx, ch_idx)
                        if len(sig.timestamps) > max_len:
                            max_len = len(sig.timestamps)
                            ref_ts = sigs[ch_name]['t']
                except:
                    pass

        mdf.close()
        if ref_ts is None: raise ValueError("No valid numeric data")

        data = {'Time': ref_ts}
        for ch, d in sigs.items():
            try:
                if len(d['s']) == max_len:
                    data[ch] = d['s']
                elif len(d['t']) > 1 and np.all(np.diff(d['t']) > 0):
                    data[ch] = np.interp(ref_ts, d['t'], d['s'])
            except:
                pass

        return pd.DataFrame(data), list(data.keys()), units

    @staticmethod
    def load_blf(fp, dbc_paths=None):
        """Load a Vector BLF (raw CAN log) as ``(DataFrame, channels, units)``.

        With ``dbc_paths`` (one or more ``.dbc``), frames are decoded into named
        physical signals via cantools. Without a DBC, payload bytes are exposed
        per CAN id (``0x1F3.byte0`` …) so traffic is still viewable. Every signal
        is zero-order-hold resampled onto one shared ``Time`` axis, matching the
        single-time-axis model the other loaders return.

        A2L is deliberately not involved: plain CAN signals decode from a DBC,
        which is a separate, lighter database than the XCP-measurement A2L.
        """
        frames = _read_blf_frames(fp)
        if not frames:
            raise ValueError("BLF 文件没有可读的 CAN 数据帧")
        t0 = min(f[0] for f in frames)
        if dbc_paths:
            return _decode_blf_with_dbc(frames, list(dbc_paths), t0)
        return _raw_blf_channels(frames, t0)

    @staticmethod
    def load_audio_video(fp):
        import av

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

        data = pd.DataFrame({name: col for name, col in zip(names, cols)})
        units = {name: '' for name in names}
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
        return df, list(df.columns), {}

    @staticmethod
    def load_excel(fp):
        kw = {'engine': 'openpyxl'} if HAS_OPENPYXL else {}
        df = pd.read_excel(fp, **kw)
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(how='all').interpolate().ffill().bfill().reset_index(drop=True)
        return df, list(df.columns), {}

    @staticmethod
    def load_hdf(fp):
        hf = parse_head_hdf(fp)
        max_factor = max((f for _, f in hf.ch_order), default=1)
        # 时间轴绝对尺度：delta 是「一个 scan 内交织浮点槽」的间隔，所以一个 scan
        # 跨 delta×per_scan（per_scan = 每 scan 总浮点数 = Σ 所有通道 factor，含被丢的
        # 非 FLOAT32 / 全 NaN 通道——它们仍占二进制槽位），factor-f 通道采样周期
        # = (delta×per_scan)/factor。早先误用 max_factor 代替 per_scan，使时间轴短了
        # per_scan/max_factor 倍、fs 同比偏大（真实文件实测应 ~50 s / 48 kHz，而非
        # ~9 s / 129.5 kHz）。绝对尺度已对标真实文件确认，勿改回 max_factor。
        per_scan = sum(f for _, f in hf.ch_order)

        # 标定 + 丢全 NaN；收集被丢通道名+原因（不静默丢弃）
        live = []
        dropped = []
        for c in hf.channels:
            if c.samples is None:
                # samples=None means non-FLOAT32 impl_type (skipped in demux)
                reason = (f"non-FLOAT32: {c.impl_type}"
                          if c.impl_type and c.impl_type != "FLOAT32"
                          else "no samples (unknown)")
                dropped.append({"name": c.name, "reason": reason})
                continue
            # HEAD FLOAT32 样本本身已是物理工程值；calibration 是元数据，
            # 不可当作对原始样本的乘法增益（旧 bug 会把转角/转速/扭矩放大到
            # 荒唐量级，且 calibration=0 的通道被 ×0 抹零）。仅保留原始 samples，
            # calibration 仍存入 channel_metadata 供显示/参考。
            s = c.samples
            if np.isnan(s).all():
                dropped.append({"name": c.name, "reason": "all-NaN"})
                continue
            live.append((c, s))

        # RPM 源（speed of rotation 且非全 0）
        rpm = next((s for c, s in live
                    if "speed of rotation" in c.quantity.lower()
                    and np.any(s != 0)), None)
        rpm_factor = next((c.factor for c, s in live
                           if "speed of rotation" in c.quantity.lower()
                           and np.any(s != 0)), None)

        def axis(factor, length):
            period = hf.delta * (per_scan / factor)
            return hf.first_value + np.arange(length, dtype=float) * period

        groups = []
        by_factor = {}
        for c, s in live:
            by_factor.setdefault(c.factor, []).append((c, s))

        for factor, items in sorted(by_factor.items(), reverse=True):
            length = items[0][1].size
            t = axis(factor, length)
            data = {"Time": t}
            units = {}
            cmeta = {}
            for c, s in items:
                data[c.name] = s
                units[c.name] = c.unit
                cmeta[c.name] = {
                    "quantity": c.quantity, "unit": c.unit,
                    "calibration": c.calibration,
                    "db_reference": c.db_reference, "moniker": c.moniker,
                    "physical_channel_nbr": c.physical_channel_nbr,
                    "raster_factor": c.factor, "impl_type": c.impl_type,
                    "equalization": c.equalization, "emphasis": c.emphasis,
                }
            # 转速注入：仅注入到含 acceleration 的组、且本组不是转速所在组
            has_acc = any("acceleration" in c.quantity.lower() for c, _ in items)
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
            }
            groups.append({
                "data": pd.DataFrame(data), "channels": list(data.keys()),
                "units": units, "channel_metadata": cmeta,
                "source_metadata": smeta, "label_suffix": f"{factor}x",
            })
        if not groups:
            raise ValueError("HEAD .hdf: no live channels after NaN drop")
        return groups
