# CSV 表头行自动识别 — Implementation Plan

> **For agentic workers (Codex):** 按任务顺序执行，checkbox 跟踪。每任务
> 测试先行（失败 → 实现 → 通过 → commit）。不要动 `tests/test_batch_loader_dispatch.py`
> ——它是"规整 CSV 零行为变化"的守卫。

Date: 2026-07-06
Spec: `docs/analyzer/specs/2026-07-06-csv-header-row-detection-spec.md`

**Goal:** `DataLoader.load_csv` 自动识别非首行表头（winwert 等多行横幅格式），
顺带单位行/BOM/小数逗号支持；规整 CSV 行为零变化。

**Architecture:** 新纯函数模块 `io/csv_format.py`（文本进、`CsvLayout` 出，
无 Qt 无 pandas），`load_csv` 前置嗅探——非平凡布局走新读取路径，否则
原样走 legacy 试错循环。

**Tech Stack:** stdlib `csv`/`re` + pandas（读取侧）。

## Global Constraints

- 命令一律 `.venv/bin/python -m pytest ...`。
- `tests/test_batch_loader_dispatch.py:34-42` 必须不改一字通过。
- 完全解析失败仍抛 `ValueError("Cannot parse CSV")`（`loader.py:588`，
  GUI else 兜底分支依赖此语义）。
- 返回三元组 `(df, channels, units)` 结构不变。
- 嗅探代码全程不得让"原本能读的文件"变得不能读（try/except → legacy）。

---

### Task 1: `csv_format.py` 嗅探模块

**Files:**
- Create: `mf4_analyzer/io/csv_format.py`
- Test: `tests/test_csv_format_sniff.py`（新建）

**Interfaces:**
- Produces: `CsvLayout`（字段见下）与
  `sniff_csv_layout(path, *, max_lines: int = 10) -> CsvLayout | None`。
  Task 2 的 loader 接线消费两者。

- [ ] **Step 1: 写失败测试**

`tests/test_csv_format_sniff.py`：

```python
"""Layout sniffing for CSVs whose channel-name row is not line 0."""
from pathlib import Path

import pytest

from mf4_analyzer.io.csv_format import CsvLayout, sniff_csv_layout


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_plain_csv_is_trivial_or_none(tmp_path):
    p = _write(tmp_path, "plain.csv", "Time,EngSpd\n0.0,100\n0.1,101\n0.2,102\n")
    layout = sniff_csv_layout(p)
    assert layout is None or layout.is_trivial


def test_winwert_rule_header_on_line_1(tmp_path):
    p = _write(
        tmp_path,
        "ww.csv",
        "WinWert Export V2.1;2023-05-17;;\n"
        "Time;MotSpd;MotTrq\n"
        "0.0;100;1.5\n"
        "0.01;101;1.6\n"
        "0.02;102;1.7\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.known_format == "winwert"
    assert layout.header_row == 1
    assert layout.data_row == 2
    assert layout.sep == ";"


def test_winwert_rule_is_case_insensitive(tmp_path):
    p = _write(
        tmp_path,
        "ww2.csv",
        "Export by WINWERT tool\nTime,Sig\n0.0,1\n0.1,2\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None and layout.known_format == "winwert"
    assert layout.header_row == 1


def test_generic_heuristic_header_on_line_2(tmp_path):
    # 两行横幅（单格长文本，列数与数据不一致 → 天然被过滤）
    p = _write(
        tmp_path,
        "banner2.csv",
        "Converted from proprietary format\n"
        "Session 2026-07-06 vehicle=EPS-01\n"
        "Time,SteerTrq,MotSpd\n"
        "0.0,0.1,50\n"
        "0.1,0.2,51\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 2
    assert layout.data_row == 3
    assert layout.units_row is None


def test_generic_heuristic_header_on_line_3(tmp_path):
    p = _write(
        tmp_path,
        "banner3.csv",
        "line one banner\nline two banner\nline three banner\n"
        "Time,Sig\n0.0,1\n0.1,2\n0.2,3\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 3
    assert layout.data_row == 4


def test_units_row_between_header_and_data(tmp_path):
    p = _write(
        tmp_path,
        "units.csv",
        "Time,MotSpd,MotTrq\n"
        "s,rpm,Nm\n"
        "0.0,100,1.5\n"
        "0.1,101,1.6\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 0
    assert layout.units_row == 1
    assert layout.data_row == 2
    assert not layout.is_trivial  # 有单位行 → 非平凡


def test_decimal_comma_with_semicolon_sep(tmp_path):
    p = _write(
        tmp_path,
        "german.csv",
        "Zeit;Drehzahl\n0,0;100,5\n0,1;101,25\n0,2;102,0\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.sep == ";"
    assert layout.decimal == ","


def test_bom_encoding_detected(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("Time,Sig\n0.0,1\n0.1,2\n".encode("utf-8-sig"))
    layout = sniff_csv_layout(p)
    # BOM 文件：要么识别为 utf-8-sig 的平凡布局，要么 None（legacy 需另修 BOM）
    if layout is not None:
        assert layout.encoding == "utf-8-sig"


def test_garbage_returns_none(tmp_path):
    p = tmp_path / "garbage.csv"
    p.write_bytes(bytes(range(256)) * 4)
    assert sniff_csv_layout(p) is None


def test_empty_file_returns_none(tmp_path):
    p = _write(tmp_path, "empty.csv", "")
    assert sniff_csv_layout(p) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_csv_format_sniff.py -v`
Expected: FAIL with `ModuleNotFoundError: mf4_analyzer.io.csv_format`

- [ ] **Step 3: 实现模块**

新建 `mf4_analyzer/io/csv_format.py`：

```python
"""CSV layout sniffing — header-row / units-row / decimal detection.

Some measurement tools export CSVs whose channel-name row is NOT line 0
(banner/metadata lines come first; e.g. the WinWert family puts a banner
on line 0 and channel names on line 1). This module detects the real
layout by content, mirroring the sniff-by-content pattern established
for HEAD .hdf (``io/head_hdf.py::sniff_head_hdf``).

Pure: no Qt, no pandas — text in, layout out. ``sniff_csv_layout``
returning ``None`` (or a trivial layout) means the caller keeps the
untouched legacy pandas path, so plain first-row-header CSVs stay
byte-identical in behavior.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin1")
_SEPARATORS = (",", ";", "\t")
_NUMERIC_DOT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_NUMERIC_COMMA = re.compile(r"^[+-]?\d+,\d*$")
_UNIT_TOKEN = re.compile(r"^\[?[^\d\W][\w/%°µ·²³\-\.]{0,7}\]?$", re.UNICODE)


@dataclass(frozen=True)
class CsvLayout:
    header_row: int
    units_row: int | None
    data_row: int
    sep: str
    encoding: str
    decimal: str
    known_format: str | None

    @property
    def is_trivial(self) -> bool:
        """Matches the legacy assumption (header line 0, no units row,
        dot decimal, no BOM handling needed) — callers keep the legacy
        pandas path for byte-identical behavior."""
        return (
            self.header_row == 0
            and self.units_row is None
            and self.decimal == "."
            and self.encoding != "utf-8-sig"
        )


# Known-format rules: (name, predicate over lowercased sniff lines,
# 0-based header row). One line per tool-specific export format —
# extend here when a new format shows up.
_KNOWN_FORMAT_RULES = (
    ("winwert", lambda lower: bool(lower) and "winwert" in lower[0], 1),
)


def _read_sniff_lines(path: Path, max_lines: int) -> tuple[list[str], str] | None:
    raw = path.read_bytes()[:65536]
    if not raw.strip():
        return None
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()[:max_lines]
        if lines:
            return lines, enc
    return None


def _split(line: str, sep: str) -> list[str]:
    try:
        return next(csv.reader(io.StringIO(line), delimiter=sep))
    except (csv.Error, StopIteration):
        return []


def _pick_separator(lines: list[str]) -> str | None:
    best_sep, best_score = None, 0
    for sep in _SEPARATORS:
        counts = [len(_split(ln, sep)) for ln in lines if ln.strip()]
        multi = [c for c in counts if c > 1]
        if not multi:
            continue
        # score: how many lines agree on the modal multi-column count
        modal = max(set(multi), key=multi.count)
        score = multi.count(modal)
        if score > best_score:
            best_sep, best_score = sep, score
    return best_sep


def _cell_numeric(cell: str) -> bool:
    cell = cell.strip()
    return bool(_NUMERIC_DOT.match(cell) or _NUMERIC_COMMA.match(cell))


def _mostly_numeric(cells: list[str]) -> bool:
    filled = [c for c in cells if c.strip()]
    if len(filled) < 2:
        return False
    numeric = sum(1 for c in filled if _cell_numeric(c))
    return numeric / len(filled) >= 0.6


def _looks_like_units(cells: list[str]) -> bool:
    filled = [c.strip() for c in cells if c.strip()]
    if not filled:
        return False
    unitish = sum(1 for c in filled if _UNIT_TOKEN.match(c))
    return unitish / len(filled) >= 0.5


def _detect_decimal(rows: list[list[str]], data_row: int) -> str:
    cells = [c.strip() for r in rows[data_row : data_row + 3] for c in r if c.strip()]
    comma = sum(1 for c in cells if _NUMERIC_COMMA.match(c))
    dot = sum(1 for c in cells if _NUMERIC_DOT.match(c))
    return "," if comma > dot else "."


def _resolve_below(rows: list[list[str]], header_row: int) -> tuple[int, int | None]:
    """Given a fixed header row, find (data_row, units_row) below it."""
    units_row: int | None = None
    for i in range(header_row + 1, len(rows)):
        if _mostly_numeric(rows[i]):
            return i, units_row
        if units_row is None and _looks_like_units(rows[i]):
            units_row = i
    return header_row + 1, units_row


def sniff_csv_layout(path, *, max_lines: int = 10) -> CsvLayout | None:
    """Detect the real CSV layout from the first ``max_lines`` lines.

    Returns ``None`` when nothing confident was found — callers must
    then fall back to the legacy loading path.
    """
    try:
        read = _read_sniff_lines(Path(path), max_lines)
    except OSError:
        return None
    if read is None:
        return None
    lines, encoding = read
    if len(lines) < 2:
        return None
    sep = _pick_separator(lines)
    if sep is None:
        return None
    rows = [_split(ln, sep) for ln in lines]
    lower = [ln.lower() for ln in lines]

    # 1. Known-format rules win.
    for name, predicate, header_row in _KNOWN_FORMAT_RULES:
        if predicate(lower) and header_row < len(rows):
            data_row, units_row = _resolve_below(rows, header_row)
            return CsvLayout(
                header_row=header_row,
                units_row=units_row,
                data_row=data_row,
                sep=sep,
                encoding=encoding,
                decimal=_detect_decimal(rows, data_row),
                known_format=name,
            )

    # 2. Generic heuristic.
    data_row = next(
        (i for i, r in enumerate(rows) if _mostly_numeric(r)), None
    )
    if data_row is None or data_row == 0:
        # headerless or no data in sniff window — let legacy decide
        if data_row == 0 and encoding == "utf-8-sig":
            # plain BOM file: report it so the loader strips the BOM
            return CsvLayout(0, None, 1, sep, encoding, ".", None)
        return None
    n_cols = len(rows[data_row])
    candidates = [
        i
        for i in range(data_row)
        if not _mostly_numeric(rows[i]) and abs(len(rows[i]) - n_cols) <= 1
    ]
    if not candidates:
        return None
    header_row = candidates[-1]
    units_row = None
    if len(candidates) >= 2 and _looks_like_units(rows[candidates[-1]]):
        header_row = candidates[-2]
        units_row = candidates[-1]
    return CsvLayout(
        header_row=header_row,
        units_row=units_row,
        data_row=data_row,
        sep=sep,
        encoding=encoding,
        decimal=_detect_decimal(rows, data_row),
        known_format=None,
    )
```

注意 `test_units_row_between_header_and_data` 的期望：`Time,MotSpd,MotTrq` /
`s,rpm,Nm` / 数据——candidates = [0, 1]，行 1 `s,rpm,Nm` 匹配 `_looks_like_units`
→ header=0、units=1。而 `test_plain_csv` 只有一行非数值 → candidates=[0]、
units=None、decimal='.'、encoding utf-8 → `is_trivial` 为 True。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_csv_format_sniff.py -v`
Expected: 全 PASS。若个别启发式用例不过，调 `_looks_like_units` /
`_mostly_numeric` 阈值使其通过，**不得**改 known-format 规则语义。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/io/csv_format.py tests/test_csv_format_sniff.py
git commit -m "feat(io): CSV layout sniffing (header/units/decimal detection)"
```

---

### Task 2: `load_csv` 接线

**Files:**
- Modify: `mf4_analyzer/io/loader.py:577-591`（`load_csv` + 新增
  `_load_csv_with_layout`）
- Test: `tests/test_csv_header_loading.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `sniff_csv_layout` / `CsvLayout`。
- Produces: `load_csv` 返回三元组语义不变；units dict 在有单位行时非空。

- [ ] **Step 1: 写失败测试**

`tests/test_csv_header_loading.py`：

```python
"""load_csv end-to-end with non-first-row headers."""
from pathlib import Path

import pytest

from mf4_analyzer.io.loader import DataLoader

REAL_SAMPLES = sorted(
    (Path(__file__).parent / "fixtures" / "csv_formats").glob("*.csv")
)


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_winwert_second_row_header(tmp_path):
    p = _write(
        tmp_path,
        "ww.csv",
        "WinWert Export V2.1;2023-05-17;;\n"
        "Time;MotSpd;MotTrq\n"
        "0.0;100;1.5\n0.01;101;1.6\n0.02;102;1.7\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "MotSpd", "MotTrq"]
    assert len(df) == 3
    assert float(df["MotSpd"].iloc[0]) == 100.0


def test_header_on_row_3_generic(tmp_path):
    p = _write(
        tmp_path,
        "b3.csv",
        "banner line one\nbanner line two\nbanner line three\n"
        "Time,Sig\n0.0,1\n0.1,2\n0.2,3\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "Sig"]
    assert len(df) == 3


def test_units_row_populates_units_dict(tmp_path):
    p = _write(
        tmp_path,
        "units.csv",
        "Time,MotSpd,MotTrq\ns,rpm,Nm\n0.0,100,1.5\n0.1,101,1.6\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "MotSpd", "MotTrq"]
    assert units == {"Time": "s", "MotSpd": "rpm", "MotTrq": "Nm"}
    assert len(df) == 2


def test_decimal_comma_german_export(tmp_path):
    p = _write(
        tmp_path,
        "de.csv",
        "WinWert Export\nZeit;Drehzahl\n0,0;100,5\n0,1;101,25\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Zeit", "Drehzahl"]
    assert abs(float(df["Drehzahl"].iloc[1]) - 101.25) < 1e-9


def test_bom_plain_csv_clean_first_channel(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("Time,Sig\n0.0,1\n0.1,2\n".encode("utf-8-sig"))
    df, channels, units = DataLoader.load_csv(p)
    assert channels[0] == "Time"  # 无 BOM 字符污染


def test_plain_csv_behavior_unchanged(tmp_path):
    # 与 tests/test_batch_loader_dispatch.py 同款输入 — 逐值一致
    p = _write(tmp_path, "plain.csv", "Time,sig\n0,1\n0.1,2\n0.2,3\n")
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "sig"]
    assert units == {}
    assert list(df["sig"]) == [1, 2, 3]


def test_garbage_still_raises_valueerror(tmp_path):
    p = tmp_path / "garbage.csv"
    p.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ValueError, match="Cannot parse CSV"):
        DataLoader.load_csv(p)


def test_time_column_drives_fs_after_detection(tmp_path):
    # 表头识别后，下游 FileData 的 _TIME_NAMES/fs 推断应自动工作
    from mf4_analyzer.io.file_data import FileData

    p = _write(
        tmp_path,
        "ww_fs.csv",
        "winwert banner\nTime,Sig\n0.0,1\n0.1,2\n0.2,3\n0.3,4\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    fd = FileData(str(p), df, channels, units)
    assert abs(fd.fs - 10.0) < 1e-6


@pytest.mark.parametrize("sample", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples_load(sample):
    """真实导出的样例放进 tests/fixtures/csv_formats/ 即自动回归。"""
    df, channels, units = DataLoader.load_csv(sample)
    assert len(channels) >= 1
    assert len(df) > 0
    # 通道名不应是纯数字（那说明表头识别错位）
    assert not all(c.replace(".", "").replace("-", "").isdigit() for c in channels)
```

注意 `FileData` 构造签名以 `mf4_analyzer/io/file_data.py:65` 实际参数为准
（若与上面不符，按实际签名调整测试而非实现）。

- [ ] **Step 2: 建 fixtures 目录**

```bash
mkdir -p tests/fixtures/csv_formats
```

新建 `tests/fixtures/csv_formats/README.md`：

```markdown
# 真实 CSV 样例回归位

把真实测量软件导出的多行表头 CSV（winwert 等）放进本目录，
`tests/test_csv_header_loading.py::test_real_samples_load` 会自动
参数化收集为回归用例。目录为空时收集 0 个用例，不报错。
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_csv_header_loading.py -v`
Expected: winwert/banner/units/decimal 用例 FAIL（通道名错位）；
plain/garbage 用例 PASS（legacy 行为）。

- [ ] **Step 4: 实现 loader 接线**

`loader.py` `load_csv` 改为（保留原 12 行为 legacy 分支，逐字不动）：

```python
    @staticmethod
    def load_csv(fp):
        from mf4_analyzer.io.csv_format import sniff_csv_layout

        layout = None
        try:
            layout = sniff_csv_layout(fp)
        except Exception:
            # Sniffing must never make a loadable file unloadable.
            layout = None
        if layout is not None and not layout.is_trivial:
            return DataLoader._load_csv_with_layout(fp, layout)
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
    def _load_csv_with_layout(fp, layout):
        """Read a CSV whose header is not line 0 (or that carries a
        units row / comma decimal / BOM). Layout comes from
        ``csv_format.sniff_csv_layout``."""
        import csv as _csv
        import io as _io

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
        if len(df.columns) < 1:
            raise ValueError("Cannot parse CSV")

        units = {}
        if layout.units_row is not None:
            try:
                text = Path(fp).read_text(
                    encoding=layout.encoding, errors="replace"
                )
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
                    h.strip(): u.strip()
                    for h, u in zip(header_cells, unit_cells)
                    if h.strip() and u.strip()
                }
            except Exception:
                units = {}

        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(axis=1, how='all').interpolate().dropna()
        if df.empty or len(df.columns) < 1:
            raise ValueError("Cannot parse CSV")
        return df, list(df.columns), units
```

（`Path` 已在 loader.py import 区——若无则补 `from pathlib import Path`。）

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_csv_header_loading.py tests/test_csv_format_sniff.py -v`
Expected: 全 PASS

- [ ] **Step 6: 守卫测试 + 相关套件回归**

Run: `.venv/bin/python -m pytest tests/test_batch_loader_dispatch.py tests/test_batch_runner.py tests/ui/test_drop_import.py tests/ui/test_open_and_save_entry.py -q`
Expected: 全 PASS（`test_batch_loader_dispatch` 一字未改）

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/io/loader.py tests/test_csv_header_loading.py tests/fixtures/csv_formats/
git commit -m "feat(io): load_csv auto-detects non-first-row headers, units row, decimal comma"
```

---

## 收尾验证

- [ ] `.venv/bin/python -m pytest tests/ -q -k "csv"` — 全部 CSV 相关用例 PASS。
- [ ] `.venv/bin/python -m pytest -q` — 全量无新增失败。
- [ ] 手动（有真实样例后）：把真实 winwert 导出放进
  `tests/fixtures/csv_formats/`，重跑 `test_real_samples_load`；在 GUI 拖入
  同文件，确认通道树名称正确、时间轴/fs 正常。若真实文件与合成假设不符
  （分隔符/单位行/编码），只调 `csv_format.py` 的规则表或阈值，加对应用例。
