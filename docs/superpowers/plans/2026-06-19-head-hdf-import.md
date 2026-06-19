# HEAD `.hdf` 导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 app 能读取 HEAD acoustics datafile format v4 `.hdf` 时域文件，按采样率分组导入为多个 `FileData`，复用现有 FFT/阶次/时频分析。

**Architecture:** 纯解析器 `io/head_hdf.py`（头解析 + 二进制解复用，无 pandas/Qt 依赖）→ 适配层 `DataLoader.load_hdf`（标定、丢 NaN、按 factor 分组、注入转速、转 DataFrame 列表）→ `_load_one` 遍历分组建多个 `FileData`。`FileData` 加 `source_metadata`/`channel_metadata`。下游分析/UI 零改动。

**Tech Stack:** Python 3.12、numpy、pandas、PyQt5、pytest。venv 解释器：`.venv/bin/python`。

## Global Constraints

- 设计依据见 `docs/superpowers/specs/2026-06-19-head-hdf-import-design.md`（含实读确认事实）。
- 仅支持变体：`version 4` / `kind: Time data` / 数据通道 `implementation type FLOAT32` / `byte order Intel` / `scan mode synchronised multiple`。其它变体 → `NotImplementedError` 并打印实际值。
- 头字符串按 **cp936(GBK)** 解码。
- 二进制：小端 FLOAT32；`start of data` 字节偏移起；每 base scan 按 `ch order` 通道序依次写「factor 个 float」，共 `nbr of scans` 次；abscissa（Time）`absc sort: calc` 不存储。
- 标定恒开：每通道 `samples × calibration`。
- 丢弃全 NaN 通道（`np.isnan(a).all()`），保留全 0 通道。
- 采样率公式：`period_factor = delta × (max_factor_in_ch_order / factor)`，`max_factor_in_ch_order` 取自原始 `ch order`（含被丢弃的 NaN 通道）。**绝对值待 HEAD Companion 确认**（候选② 默认；见 spec §7.1）。Task 1–5 与采样率无关，可先做；Task 6/8 用确认后的公式常量。
- 测试运行：`.venv/bin/python -m pytest <path> -q`（pytest.ini 默认 `-m "not slow"`）。
- 提交频繁，每个 Task 末尾提交一次。提交信息用中文 + 末尾两行 Co-Authored-By / Claude-Session（按仓库约定）。

## File Structure

| 文件 | 责任 |
|---|---|
| `tests/_helpers/head_hdf_factory.py`（新建） | 合成最小合法 HEAD v4 文件的测试工厂 |
| `mf4_analyzer/io/head_hdf.py`（新建） | 纯解析器：签名嗅探、头解析、二进制解复用、变体守卫 |
| `mf4_analyzer/io/file_data.py`（改） | `FileData` 增 `source_metadata`/`channel_metadata`/`label_suffix` |
| `mf4_analyzer/io/loader.py`（改） | `DataLoader.load_hdf` 适配层 |
| `mf4_analyzer/io/__init__.py`（改） | 导出 `parse_head_hdf`（按需） |
| `mf4_analyzer/ui/main_window/_project_io_mixin.py`（改） | `.hdf` 分发 + `_register_file_data` 抽取 + 对话框过滤器 |
| `tests/test_head_hdf.py`（新建） | 解析器单测 |
| `tests/test_head_hdf_loader.py`（新建） | 适配层 + FileData 集成单测 |
| `tests/integration/test_head_hdf_realfile.py`（新建） | 真实文件集成测试（缺文件则 skip） |

---

### Task 1: 合成 HEAD 文件工厂

**Files:**
- Create: `tests/_helpers/head_hdf_factory.py`
- Test: `tests/test_head_hdf.py`（仅本任务的工厂自测）

**Interfaces:**
- Produces: `write_head_hdf(path, *, channels, n_scans, delta=3.861e-06, start_of_data=4096, version=4, byte_order="Intel", kind="Time data", scan_mode="synchronised multiple") -> pathlib.Path`。`channels` 为 dict 列表：`{name, factor, quantity, unit, calibration, db_reference="", moniker="", impl_type="FLOAT32", equalization="id", samples: np.ndarray|None}`；`samples` 长度须 == `n_scans*factor`，`None` → 全 NaN。

- [ ] **Step 1: 写工厂**

```python
# tests/_helpers/head_hdf_factory.py
from __future__ import annotations
from pathlib import Path
import numpy as np


def write_head_hdf(path, *, channels, n_scans, delta=3.861e-06,
                   start_of_data=4096, version=4, byte_order="Intel",
                   kind="Time data", scan_mode="synchronised multiple"):
    """Write a minimal HEAD acoustics datafile-format v4 file for tests."""
    L = []
    a = L.append
    a(";"); a("; HEAD acoustics datafile format"); a(";")
    a(f"version:                           {version}")
    a("release:                           6")
    a(f"byte order:                        {byte_order}")
    a(f"kind:                              {kind}")
    a(";#code page:                       936")
    a(f"start of data:                     {start_of_data}")
    a("nbr of abscissa:                   1")
    a(f"nbr of channel:                    {len(channels)}")
    toks = [(f"{c['factor']}*{i}" if c['factor'] != 1 else f"{i}")
            for i, c in enumerate(channels, 1)]
    a("ch order:                          " + ", ".join(toks))
    a("data org:                          a1b1 a2b2")
    a(f"scan mode:                         {scan_mode}")
    a("abscissa definition:               1")
    a("name str:                          Time")
    a("physical quantity:                 time")
    a("physical unit:                     s")
    a("absc sort:                         calc")
    a("first value:                       0")
    a(f"delta value:                       {delta!r}")
    a(f"nbr of scans:                      {n_scans}")
    a("distribution func:                 linear")
    for i, c in enumerate(channels, 1):
        a(f"channel definition:                {i}")
        a(f"name str:                          {c['name']}")
        a(f";#moniker:                         {c.get('moniker', '')}")
        a(f"physical channel nbr:              {i - 1}")
        a(f"physical quantity:                 {c['quantity']}")
        a(f"physical unit:                     {c['unit']}")
        a(f"calibration:                       {c['calibration']!r}")
        a(f";#dB reference:                    {c.get('db_reference', '')}")
        a(f"implementation type:               {c.get('impl_type', 'FLOAT32')}")
        a(f";#equalization:                    {c.get('equalization', 'id')}")
    header = ("\r\n".join(L) + "\r\n").encode("cp936")
    if len(header) > start_of_data:
        raise ValueError("header exceeds start_of_data")
    header = header.ljust(start_of_data, b" ")

    blocks = []
    for c in channels:
        f = c["factor"]
        s = c.get("samples")
        s = (np.full(n_scans * f, np.nan) if s is None
             else np.asarray(s, dtype=float))
        if s.size != n_scans * f:
            raise ValueError(f"{c['name']}: {s.size} != {n_scans*f}")
        blocks.append(s.reshape(n_scans, f))
    body = np.concatenate(blocks, axis=1).astype("<f4").tobytes()
    Path(path).write_bytes(header + body)
    return Path(path)
```

- [ ] **Step 2: 写工厂自测**

```python
# tests/test_head_hdf.py
from __future__ import annotations
import numpy as np
from tests._helpers.head_hdf_factory import write_head_hdf


def _two_channel_file(path, n_scans=4):
    fast = np.arange(n_scans * 2, dtype=float)          # factor 2
    slow = np.arange(n_scans, dtype=float) * 10.0        # factor 1
    return write_head_hdf(
        path, n_scans=n_scans, start_of_data=2048,
        channels=[
            {"name": "L", "factor": 2, "quantity": "sound pressure",
             "unit": "Pa", "calibration": 2.0, "db_reference": "2e-005",
             "moniker": "Audio.Decoded", "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 3.0, "samples": slow},
        ])


def test_factory_writes_signature_and_offset(tmp_path):
    p = _two_channel_file(tmp_path / "synth.hdf")
    raw = p.read_bytes()
    assert b"HEAD acoustics datafile format" in raw[:2048]
    # body floats == sum(factor)*n_scans == (2+1)*4 == 12
    body = raw[2048:]
    assert len(body) == 12 * 4
```

- [ ] **Step 3: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -q`
Expected: PASS（1 passed）

- [ ] **Step 4: 提交**

```bash
git add tests/_helpers/head_hdf_factory.py tests/test_head_hdf.py
git commit -- tests/_helpers/head_hdf_factory.py tests/test_head_hdf.py -m "test(head-hdf): 合成 HEAD v4 文件工厂"
```

---

### Task 2: 解析器 — 签名嗅探 + 头解析

**Files:**
- Create: `mf4_analyzer/io/head_hdf.py`
- Test: `tests/test_head_hdf.py`（追加）

**Interfaces:**
- Produces:
  - `sniff_head_hdf(path) -> bool`：读前 4096 字节，含 `HEAD acoustics datafile format` 返回 True。
  - `@dataclass HeadChannel`: `name:str, factor:int, quantity:str, unit:str, calibration:float, db_reference:str, moniker:str, physical_channel_nbr:int, impl_type:str, equalization:str, emphasis:str, samples: np.ndarray|None=None`。
  - `@dataclass HeadHdfFile`: `version:int, release:str, byte_order:str, kind:str, scan_mode:str, code_page:str, start_of_data:int, n_scans:int, delta:float, first_value:float, recording_date:str, timezone:str, channels: list[HeadChannel], ch_order: list[tuple[int,int]]`（(1-based channel, factor) 存储序）。
  - `parse_head_hdf(path) -> HeadHdfFile`（本任务先填充头/通道元数据，`samples` 留 None；Task 3 填充）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_head_hdf.py
import pytest
from mf4_analyzer.io.head_hdf import sniff_head_hdf, parse_head_hdf


def test_sniff_true_false(tmp_path):
    p = _two_channel_file(tmp_path / "s.hdf")
    assert sniff_head_hdf(p) is True
    bad = tmp_path / "bad.hdf"
    bad.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 100)   # HDF5 magic
    assert sniff_head_hdf(bad) is False


def test_parse_header_fields_and_gbk(tmp_path):
    fast = np.arange(8, dtype=float)
    slow = np.arange(4, dtype=float)
    p = write_head_hdf(
        tmp_path / "g.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "输出轴 x", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.5, "db_reference": "1e-003",
             "moniker": "Audio.Decoded", "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 3.0, "samples": slow},
        ])
    hf = parse_head_hdf(p)
    assert hf.version == 4
    assert hf.byte_order == "Intel"
    assert hf.kind == "Time data"
    assert hf.start_of_data == 2048
    assert hf.n_scans == 4
    assert hf.ch_order == [(1, 2), (2, 1)]
    assert [c.name for c in hf.channels] == ["输出轴 x", "SP"]
    assert hf.channels[0].quantity == "acceleration"
    assert hf.channels[0].calibration == pytest.approx(1.5)
    assert hf.channels[0].db_reference == "1e-003"
    assert hf.channels[0].factor == 2
    assert hf.channels[1].factor == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -q`
Expected: FAIL（`ModuleNotFoundError: mf4_analyzer.io.head_hdf`）

- [ ] **Step 3: 写实现**

```python
# mf4_analyzer/io/head_hdf.py
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
```

> 注：`_kv` 把普通 `key:value` 与 `;#key:value` 都归一化，因此 `moniker`/`dB reference`/`equalization`（`;#` 行）能落到当前 channel 块。`date of recording`/`timezone`/`code page` 也是 `;#` 行，归一化后落入 `top`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py
git commit -- mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py -m "feat(head-hdf): 头解析 + 签名嗅探 + GBK 通道名"
```

---

### Task 3: 解析器 — 二进制解复用

**Files:**
- Modify: `mf4_analyzer/io/head_hdf.py`（在 `parse_head_hdf` 末尾填充 `samples`）
- Test: `tests/test_head_hdf.py`（追加）

**Interfaces:**
- `parse_head_hdf` 返回的每个 `HeadChannel.samples` 为长度 `n_scans*factor` 的 `np.float64` 原生数组（未标定）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_head_hdf.py
def test_demux_native_samples(tmp_path):
    fast = np.arange(8, dtype=float)          # factor 2, n_scans 4 -> [0..7]
    slow = np.array([10., 20., 30., 40.])     # factor 1
    p = write_head_hdf(
        tmp_path / "d.hdf", n_scans=4, start_of_data=2048,
        channels=[
            {"name": "L", "factor": 2, "quantity": "sound pressure",
             "unit": "Pa", "calibration": 1.0, "samples": fast},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0, "samples": slow},
        ])
    hf = parse_head_hdf(p)
    np.testing.assert_allclose(hf.channels[0].samples, fast)
    np.testing.assert_allclose(hf.channels[1].samples, slow)
    assert hf.channels[0].samples.size == 8
    assert hf.channels[1].samples.size == 4
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py::test_demux_native_samples -q`
Expected: FAIL（`samples is None`）

- [ ] **Step 3: 写实现**（在 `parse_head_hdf` 的 `return` 之前插入解复用，并把结果存入 channels）

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py
git commit -- mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py -m "feat(head-hdf): 按 ch order 二进制解复用"
```

---

### Task 4: 解析器 — 变体守卫

**Files:**
- Modify: `mf4_analyzer/io/head_hdf.py`
- Test: `tests/test_head_hdf.py`（追加）

**Interfaces:** `parse_head_hdf` 在不支持的变体上抛 `NotImplementedError`，消息含实际值。

- [ ] **Step 1: 写失败测试**

```python
# 追加
def test_guard_rejects_non_float32(tmp_path):
    p = write_head_hdf(
        tmp_path / "i16.hdf", n_scans=4, start_of_data=2048,
        channels=[{"name": "L", "factor": 1, "quantity": "sound pressure",
                   "unit": "Pa", "calibration": 1.0, "impl_type": "INT16",
                   "samples": np.zeros(4)}])
    with pytest.raises(NotImplementedError, match="INT16"):
        parse_head_hdf(p)


def test_guard_rejects_non_time_data(tmp_path):
    p = write_head_hdf(
        tmp_path / "spec.hdf", n_scans=4, start_of_data=2048,
        kind="Spectrum data",
        channels=[{"name": "L", "factor": 1, "quantity": "x", "unit": "Pa",
                   "calibration": 1.0, "samples": np.zeros(4)}])
    with pytest.raises(NotImplementedError, match="Spectrum data"):
        parse_head_hdf(p)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -k guard -q`
Expected: FAIL（未抛错）

- [ ] **Step 3: 写实现**（在 `parse_head_hdf` 解复用之前、解析完 top/channels 之后加守卫）

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf.py -q`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py
git commit -- mf4_analyzer/io/head_hdf.py tests/test_head_hdf.py -m "feat(head-hdf): 变体守卫"
```

---

### Task 5: FileData 增元数据字段

**Files:**
- Modify: `mf4_analyzer/io/file_data.py:18`
- Test: `tests/test_head_hdf_loader.py`（新建）

**Interfaces:**
- `FileData.__init__(self, fp, df, chs, units, idx=0, *, source_metadata=None, channel_metadata=None, label_suffix="")`。
- 新增属性：`self.source_metadata: dict`、`self.channel_metadata: dict`、`self.label_suffix: str`；当 `label_suffix` 非空，`short_name` 末尾追加 ` ·{suffix}`（用于多组同源文件区分）。
- 现有调用（`FileData(fp, data, chs, units, len(self.files))`）保持兼容（新参数有默认值）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_head_hdf_loader.py
from __future__ import annotations
import numpy as np
import pandas as pd
from mf4_analyzer.io.file_data import FileData


def test_filedata_carries_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0, 2.0], "L": [1.0, 2.0, 3.0]})
    fd = FileData(
        str(tmp_path / "x.hdf"), df, list(df.columns), {"L": "Pa"}, 0,
        source_metadata={"recording_date": "17.04.2026", "scan_mode": "x"},
        channel_metadata={"L": {"quantity": "sound pressure",
                                "db_reference": "2e-005", "calibration": 104.0}},
        label_suffix="24x")
    assert fd.source_metadata["recording_date"] == "17.04.2026"
    assert fd.channel_metadata["L"]["db_reference"] == "2e-005"
    assert fd.label_suffix == "24x"
    assert "24x" in fd.short_name


def test_filedata_backcompat_no_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0], "L": [1.0, 2.0]})
    fd = FileData(str(tmp_path / "y.hdf"), df, list(df.columns), {}, 0)
    assert fd.source_metadata == {}
    assert fd.channel_metadata == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py -q`
Expected: FAIL（`TypeError: unexpected keyword argument`）

- [ ] **Step 3: 写实现**（编辑 `file_data.py` `__init__` 头部）

```python
    def __init__(self, fp, df, chs, units, idx=0, *,
                 source_metadata=None, channel_metadata=None, label_suffix=""):
        self.filepath = Path(fp)
        self.filename = self.filepath.name
        self.short_name = self.filepath.stem[:18]
        self.source_metadata = dict(source_metadata or {})
        self.channel_metadata = dict(channel_metadata or {})
        self.label_suffix = str(label_suffix or "")
        if self.label_suffix:
            self.short_name = f"{self.short_name[:14]} ·{self.label_suffix}"
        self.data = df
        # ... (其余保持不变)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py tests/ -q -k "file_data or head or mf4"`
Expected: PASS（且不破坏现有 FileData 用例）

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/file_data.py tests/test_head_hdf_loader.py
git commit -- mf4_analyzer/io/file_data.py tests/test_head_hdf_loader.py -m "feat(file-data): 增 source/channel 元数据与 label_suffix"
```

---

### Task 6: 适配层 `DataLoader.load_hdf`

**Files:**
- Modify: `mf4_analyzer/io/loader.py`（新增 `load_hdf` 静态方法 + 顶部 `from .head_hdf import parse_head_hdf`）
- Test: `tests/test_head_hdf_loader.py`（追加）

**Interfaces:**
- `DataLoader.load_hdf(fp) -> list[dict]`，每元素：`{"data": pd.DataFrame(含'Time'列), "channels": list[str], "units": dict, "channel_metadata": dict, "source_metadata": dict, "label_suffix": str}`。
- 行为：标定（`samples*calibration`）→ 丢全 NaN 通道 → 按 factor 分组 → 每组建 `Time` 列（`first_value + arange(Nf)*period`，`period = delta*max_factor/factor`，`max_factor` 取 `ch_order` 原始最大）→ 把转速通道（quantity 含 "speed of rotation" 且非全 0）重采样注入到含 "acceleration" 的组。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_head_hdf_loader.py
from mf4_analyzer.io.loader import DataLoader
from tests._helpers.head_hdf_factory import write_head_hdf


def test_load_hdf_groups_by_factor_and_drops_nan(tmp_path):
    n = 4
    acc = np.arange(n * 2, dtype=float)            # factor 2 -> 24x 模拟组
    spd = np.array([100., 110., 120., 130.])       # factor 1 -> 慢组
    nanch = None                                    # factor 2 全 NaN -> 丢弃
    p = write_head_hdf(
        tmp_path / "g.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "MOTOR X", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 2.0, "samples": acc},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0, "samples": spd},
            {"name": "CAN", "factor": 2, "quantity": "raw", "unit": "",
             "calibration": 1.0, "samples": nanch},
        ])
    groups = DataLoader.load_hdf(str(p))
    factors = sorted(g["label_suffix"] for g in groups)
    # 全 NaN 的 factor-2 CAN 被丢；但 MOTOR X 也是 factor-2 → 该组仍在
    assert any("2x" in s for s in factors)
    assert any("1x" in s for s in factors)
    fast = next(g for g in groups if "2x" in g["label_suffix"])
    # 标定生效：MOTOR X 原值 ×2
    np.testing.assert_allclose(
        fast["data"]["MOTOR X"].to_numpy(), acc * 2.0)
    # CAN(全 NaN) 不在通道里
    assert "CAN" not in fast["channels"]
    # 转速注入快组
    assert any("SP" in c for c in fast["channels"])
    # 慢组含 SP 原始
    slow = next(g for g in groups if "1x" in g["label_suffix"])
    np.testing.assert_allclose(slow["data"]["SP"].to_numpy(), spd)
    # 元数据回传
    assert fast["channel_metadata"]["MOTOR X"]["quantity"] == "acceleration"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py::test_load_hdf_groups_by_factor_and_drops_nan -q`
Expected: FAIL（`AttributeError: load_hdf`）

- [ ] **Step 3: 写实现**

```python
# loader.py 顶部 import 区
from .head_hdf import parse_head_hdf

# DataLoader 内新增：
    @staticmethod
    def load_hdf(fp):
        hf = parse_head_hdf(fp)
        max_factor = max((f for _, f in hf.ch_order), default=1)

        # 标定 + 丢全 NaN
        live = []
        for c in hf.channels:
            if c.samples is None:
                continue
            s = c.samples * float(c.calibration)
            if np.isnan(s).all():
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
            period = hf.delta * (max_factor / factor)
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
                "source_filename": Path(fp).name,
            }
            groups.append({
                "data": pd.DataFrame(data), "channels": list(data.keys()),
                "units": units, "channel_metadata": cmeta,
                "source_metadata": smeta, "label_suffix": f"{factor}x",
            })
        if not groups:
            raise ValueError("HEAD .hdf: no live channels after NaN drop")
        return groups
```

> 顶部还需 `from pathlib import Path`（loader.py 暂无，按需加）。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/loader.py tests/test_head_hdf_loader.py
git commit -- mf4_analyzer/io/loader.py tests/test_head_hdf_loader.py -m "feat(head-hdf): load_hdf 适配层（标定/分组/注入转速/元数据）"
```

---

### Task 7: `_load_one` 分发 + 多 FileData + 对话框过滤器

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`（`_load_one` 加 `.hdf` 分支、抽 `_register_file_data`、对话框过滤器加 `*.hdf`）
- Test: `tests/test_head_hdf_loader.py`（追加 — 直接测 `DataLoader.load_hdf` → 多个 `FileData` 构造，避免起 Qt 主窗口）

**Interfaces:** `.hdf` → 每组建一个 `FileData(fp, g["data"], g["channels"], g["units"], idx, source_metadata=g["source_metadata"], channel_metadata=g["channel_metadata"], label_suffix=g["label_suffix"])`。

- [ ] **Step 1: 写失败测试**（仅验证"分组列表能构造出多个带正确时间轴/元数据的 FileData"，UI 装配在集成层手验）

```python
# 追加到 tests/test_head_hdf_loader.py
def test_groups_build_multiple_filedata(tmp_path):
    n = 4
    p = write_head_hdf(
        tmp_path / "m.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "MOTOR X", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0,
             "samples": np.arange(n * 2, dtype=float)},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0,
             "samples": np.array([1., 2., 3., 4.])},
        ])
    groups = DataLoader.load_hdf(str(p))
    fds = [FileData(str(p), g["data"], g["channels"], g["units"], i,
                    source_metadata=g["source_metadata"],
                    channel_metadata=g["channel_metadata"],
                    label_suffix=g["label_suffix"]) for i, g in enumerate(groups)]
    assert len(fds) == 2
    suffixes = {fd.label_suffix for fd in fds}
    assert suffixes == {"2x", "1x"}
    fast = next(fd for fd in fds if fd.label_suffix == "2x")
    # 快组 fs = 1/period, period = delta*max_factor/factor = 1*2/2 = 1 -> fs≈1
    assert fast.fs > 0
    assert fast.channel_metadata["MOTOR X"]["quantity"] == "acceleration"
```

- [ ] **Step 2: 运行确认失败 → 写实现 → 通过**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py::test_groups_build_multiple_filedata -q`（先失败/或直接验 FileData 构造）

实现编辑 `_project_io_mixin.py`：

```python
    # _load_one 内 ext 分支：
            elif ext == '.hdf':
                groups = DataLoader.load_hdf(fp)
                for g in groups:
                    self._register_file_data(
                        fp, g["data"], g["channels"], g["units"],
                        source_metadata=g["source_metadata"],
                        channel_metadata=g["channel_metadata"],
                        label_suffix=g["label_suffix"])
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载: {p.name} → {len(groups)} 组 | 共 {len(self.files)} 文件")
                self.toast(f"已加载 {p.name} · {len(groups)} 组", "success")
                return
```

把现有 114–141 的 FileData 注册体抽成：

```python
    def _register_file_data(self, fp, data, chs, units, *,
                            source_metadata=None, channel_metadata=None,
                            label_suffix=""):
        fid = f"f{self._fc}"; self._fc += 1
        fd = FileData(fp, data, chs, units, len(self.files),
                      source_metadata=source_metadata,
                      channel_metadata=channel_metadata,
                      label_suffix=label_suffix)
        self.files[fid] = fd
        self.navigator.add_file(fid, fd)
        self.canvas_time.invalidate_envelope_cache("file loaded")
        self.canvas_time.invalidate_monotonicity_cache()
        self._fft_time_cache_clear_for_fid(fid)
        self._refresh_channel_dependent_controls()
        if fd.time_array is not None and len(fd.time_array):
            current_hi = self.inspector.top.spin_end.maximum()
            new_hi = max(current_hi, fd.time_array[-1])
            self.inspector.top.set_range_limits(0, new_hi)
            if len(self.files) == 1:
                self.inspector.top.spin_end.setValue(fd.time_array[-1])
        return fd
```

非 `.hdf` 分支改为调用 `_register_file_data(fp, data, chs, units)` 后做原有的 `_update_info`/statusBar/toast。

对话框过滤器（`:33-34` 与 `:81`）加 `*.hdf`：
```python
            "所有支持的文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf *.tlproj);;"
            "项目 (*.tlproj);;数据文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf)",
```

- [ ] **Step 3: 跑现有 smoke/io 测试确认未回归**

Run: `.venv/bin/python -m pytest tests/test_head_hdf_loader.py tests/test_mf4_loader.py -q`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add mf4_analyzer/ui/main_window/_project_io_mixin.py tests/test_head_hdf_loader.py
git commit -- mf4_analyzer/ui/main_window/_project_io_mixin.py tests/test_head_hdf_loader.py -m "feat(head-hdf): _load_one 分发 + 多 FileData 注册 + 对话框过滤"
```

---

### Task 8: 真实文件集成测试 + HEAD Companion 验收

**Files:**
- Create: `tests/integration/test_head_hdf_realfile.py`

**Interfaces:** 缺真实文件则 `pytest.skip`。

- [ ] **Step 1: 写测试**

```python
# tests/integration/test_head_hdf_realfile.py
from __future__ import annotations
import os
import numpy as np
import pytest
from mf4_analyzer.io.loader import DataLoader

REAL = os.environ.get("HEAD_HDF_SAMPLE", "/tmp/head_sample.hdf")


@pytest.mark.skipif(not os.path.exists(REAL), reason="real HEAD sample absent")
def test_real_file_groups_and_counts():
    groups = DataLoader.load_hdf(REAL)
    suff = {g["label_suffix"] for g in groups}
    assert "24x" in suff and "1x" in suff      # 48x(全NaN ch28) 应被丢
    fast = next(g for g in groups if g["label_suffix"] == "24x")
    # 8 个 24x 通道 + 注入转速；样本数 1,188,000
    assert any(c == "L" for c in fast["channels"])
    assert len(fast["data"]) == 49500 * 24
    slow = next(g for g in groups if g["label_suffix"] == "1x")
    assert len(slow["data"]) == 49500
    # 标定后 L 量级合理（±几十 Pa 级，标定 104）
    assert np.nanmax(np.abs(fast["data"]["L"].to_numpy())) > 0
```

- [ ] **Step 2: 运行**

Run: `HEAD_HDF_SAMPLE=/tmp/head_sample.hdf .venv/bin/python -m pytest tests/integration/test_head_hdf_realfile.py -q`
Expected: PASS

- [ ] **Step 3: HEAD Companion 手动验收（记录到 spec §4）**

用 HEAD Companion 打开真实文件，比对：channel `L`/`SP` 的采样率、样本数、标定后数值、录制时长，与 loader 输出一致（重点核 §7.1 采样率读法）。

- [ ] **Step 4: 提交**

```bash
git add tests/integration/test_head_hdf_realfile.py
git commit -- tests/integration/test_head_hdf_realfile.py -m "test(head-hdf): 真实文件集成测试（缺文件 skip）"
```

---

## Self-Review

- **Spec coverage:** §3.1 签名/头解析→Task2；二进制解复用→Task3；变体守卫→Task4；§3.2 标定/丢NaN/分组/注入/元数据→Task6；§3.3 多FileData/分发/过滤→Task7；§3.4 元数据字段→Task5；§4 测试→Task1/8。覆盖完整。
- **采样率开放项**：Task6 用 `period=delta*max_factor/factor`（候选②），Task8 + HEAD Companion 定死；若为候选①则改 `max_factor` 取存活通道最大值（一处常量）。
- **类型一致性:** `parse_head_hdf`/`HeadChannel.samples`/`load_hdf` 返回 dict 列表键名（data/channels/units/channel_metadata/source_metadata/label_suffix）全程一致；`FileData` 新 kwargs 与 Task5 定义一致。
