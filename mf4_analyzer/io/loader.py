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
