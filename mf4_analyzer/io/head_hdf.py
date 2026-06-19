"""Parser for HEAD acoustics datafile format v4 (.hdf) time-data files."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_SIG = b"HEAD acoustics datafile format"


def sniff_head_hdf(path) -> bool:
    with open(path, "rb") as fh:
        return _SIG in fh.read(4096)


@dataclass
class HeadChannel:
    name: str
    factor: int
    quantity: str = ""
    unit: str = ""
    calibration: float = 1.0
    db_reference: str = ""
    moniker: str = ""
    physical_channel_nbr: int = -1
    impl_type: str = "FLOAT32"
    equalization: str = ""
    emphasis: str = ""
    samples: np.ndarray | None = None


@dataclass
class HeadHdfFile:
    version: int
    release: str
    byte_order: str
    kind: str
    scan_mode: str
    code_page: str
    start_of_data: int
    n_scans: int
    delta: float
    first_value: float
    recording_date: str
    timezone: str
    channels: list = field(default_factory=list)
    ch_order: list = field(default_factory=list)


def _kv(line: str):
    """Split 'key: value' (also ';#key: value'); return (key, value) or None."""
    m = re.match(r"^;?#?\s*([^:]+?):\s*(.*)$", line)
    if not m:
        return None
    return m.group(1).strip().lower(), m.group(2).strip()


def _parse_ch_order(s: str):
    out = []
    for t in re.split(r"[,\s]+", s.strip()):
        if not t:
            continue
        if "*" in t:
            f, ch = t.split("*")
            out.append((int(ch), int(f)))
        else:
            out.append((int(t), 1))
    return out


def parse_head_hdf(path) -> HeadHdfFile:
    raw = Path(path).read_bytes()
    # start of data is needed to bound the ASCII header; find it first.
    head_probe = raw[:65536].decode("cp936", errors="replace")
    m = re.search(r"(?m)^start of data:\s*(\d+)", head_probe)
    if not m:
        raise ValueError("missing 'start of data' header field")
    start = int(m.group(1))
    text = raw[:start].decode("cp936", errors="replace")
    lines = text.splitlines()

    top = {}
    abscissa = {}
    channels = []
    cur = None
    section = "top"
    for line in lines:
        kv = _kv(line)
        if kv is None:
            continue
        key, val = kv
        if key == "abscissa definition":
            section = "abscissa"
            continue
        if key == "channel definition":
            section = "channel"
            cur = HeadChannel(name="", factor=1)
            channels.append(cur)
            continue
        if section == "channel" and cur is not None:
            if key == "name str":
                cur.name = val
            elif key == "physical quantity":
                cur.quantity = val
            elif key == "physical unit":
                cur.unit = val
            elif key == "calibration":
                cur.calibration = float(val) if val else 1.0
            elif key == "db reference":
                cur.db_reference = val
            elif key == "moniker":
                cur.moniker = val
            elif key == "physical channel nbr":
                cur.physical_channel_nbr = int(val) if val else -1
            elif key == "implementation type":
                cur.impl_type = val
            elif key == "equalization":
                cur.equalization = val
            elif key == "emphasis":
                cur.emphasis = val
        elif section == "abscissa":
            abscissa[key] = val
        else:
            top[key] = val

    ch_order = _parse_ch_order(top.get("ch order", ""))
    # apply factors from ch order onto channels (1-based)
    factor_by_ch = {ch: f for ch, f in ch_order}
    for i, c in enumerate(channels, 1):
        c.factor = factor_by_ch.get(i, 1)

    # --- variant guards ---
    if int(top.get("version", "0") or 0) != 4:
        raise NotImplementedError(f"unsupported version: {top.get('version')!r}")
    if top.get("kind", "") != "Time data":
        raise NotImplementedError(f"unsupported kind: {top.get('kind')!r}")
    if top.get("byte order", "") != "Intel":
        raise NotImplementedError(f"unsupported byte order: {top.get('byte order')!r}")
    for c in channels:
        if c.impl_type and c.impl_type != "FLOAT32":
            raise NotImplementedError(
                f"unsupported implementation type: {c.impl_type!r} ({c.name})")

    # --- binary demux (insert before building HeadHdfFile) ---
    per_scan = sum(f for _, f in ch_order)
    n = int(abscissa.get("nbr of scans", "0") or 0)
    if per_scan and n:
        floats = np.frombuffer(raw[start:start + n * per_scan * 4], dtype="<f4")
        mat = floats.reshape(n, per_scan).astype(np.float64)
        col = 0
        offsets = {}
        for ch, f in ch_order:        # storage order
            offsets[ch] = (col, f)
            col += f
        for i, c in enumerate(channels, 1):
            o, f = offsets.get(i, (None, c.factor))
            if o is None:
                continue
            c.samples = mat[:, o:o + f].reshape(-1)

    return HeadHdfFile(
        version=int(top.get("version", "0") or 0),
        release=top.get("release", ""),
        byte_order=top.get("byte order", ""),
        kind=top.get("kind", ""),
        scan_mode=top.get("scan mode", ""),
        code_page=top.get("code page", ""),
        start_of_data=start,
        n_scans=int(abscissa.get("nbr of scans", "0") or 0),
        delta=float(abscissa.get("delta value", "0") or 0.0),
        first_value=float(abscissa.get("first value", "0") or 0.0),
        recording_date=top.get("date of recording", ""),
        timezone=top.get("timezone", ""),
        channels=channels,
        ch_order=ch_order,
    )
