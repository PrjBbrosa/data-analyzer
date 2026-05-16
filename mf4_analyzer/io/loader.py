"""DataLoader: reads MF4 / Excel / CSV inputs."""
from collections import defaultdict

import numpy as np
import pandas as pd

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
                    sigs[ch_name] = {'s': np.array(s, float), 't': np.array(sig.timestamps, float)}
                    units[ch_name] = str(getattr(sig, 'unit', '') or '')
                    if len(sig.timestamps) > max_len:
                        max_len = len(sig.timestamps)
                        ref_ts = np.array(sig.timestamps, float)
            except Exception as e:
                # 如果带group/index失败，尝试不带参数（兼容旧版本）
                try:
                    sig = mdf.get(ch_name)
                    if sig.samples is not None and len(sig.samples) > 0 and np.issubdtype(sig.samples.dtype, np.number):
                        s = sig.samples.flatten() if len(sig.samples.shape) > 1 else sig.samples
                        sigs[ch_name] = {'s': np.array(s, float), 't': np.array(sig.timestamps, float)}
                        units[ch_name] = str(getattr(sig, 'unit', '') or '')
                        if len(sig.timestamps) > max_len:
                            max_len = len(sig.timestamps)
                            ref_ts = np.array(sig.timestamps, float)
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
