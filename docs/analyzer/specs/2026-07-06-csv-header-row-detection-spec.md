# CSV 表头行自动识别 Spec

Date: 2026-07-06
Status: Approved for implementation
Plan: `docs/analyzer/plans/2026-07-06-csv-header-row-detection-implementation.md`

## 背景

部分 CSV 由其他测量软件转换导出，**通道名不在第一行**（可能在第二/三/四行，
前面是元数据横幅行）。已知一种格式：第一行含关键字 `winwert`（大小写不定），
通道名在第二行。

现状（2026-07-06 核实）：

- CSV 解析唯一入口 `DataLoader.load_csv`（`mf4_analyzer/io/loader.py:577-591`，
  12 行）。GUI（`_project_io_mixin.py:243-244` else 兜底分支）与批处理
  （`batch.py:159-160`）都汇到它——改一处全覆盖。
- `pd.read_csv` 默认 `header=0` **硬编码第一行为表头**。winwert 类文件的后果：
  第一行横幅被当通道名；第二行真表头被 `to_numeric(errors='coerce')` 变 NaN
  后被 `.dropna()` 连行清掉。
- 编码试错 `['utf-8','gbk','latin1']` 无 `utf-8-sig`（Excel 常见 BOM）。
- 单位恒空 `{}`（`loader.py:591`）；时间列/fs 识别在下游
  `FileData._TIME_NAMES`（`file_data.py:12-14`, `:96-106`），表头找对即自动工作。
- 仓库已有按内容嗅探范式：`sniff_head_hdf`（`io/head_hdf.py:12-14`，读前 4096
  字节找标记）+ `_kv` 小写归一化（`:56`）——直接模板。
- 仓库/testdoc 内**没有**真实多行表头样例——fixture 用合成，留真实样例回归位。

## 目标

1. `load_csv` 自动识别真实表头行：已知格式规则表（winwert 等）优先，
   通用启发式兜底。
2. 顺带：单位行解析进 units dict、`utf-8-sig` 编码、小数逗号（德系导出常见
   `1,23` + 分号分隔）支持。
3. 规整 CSV（第一行即表头）**行为零变化**——现有测试
   `tests/test_batch_loader_dispatch.py:34-42` 原样通过。

## 非目标

- Excel（`load_excel` 有同样缺陷，本轮不动——单独小波）。
- 导入预览对话框（启发式置信度低时让用户手点表头行）——二期，等真实样例
  暴露启发式覆盖不了的格式再做。
- 扩展名分派层改动（`.csv` 已正确路由；`_load_one` else 兜底语义不变）。

## 设计

### 新模块 `mf4_analyzer/io/csv_format.py`

纯函数、无 Qt、无 pandas（文本进、布局出），与 `head_hdf.py` 并列。

```python
@dataclass(frozen=True)
class CsvLayout:
    header_row: int          # 0-based 行号：通道名行
    units_row: int | None    # 0-based 行号：单位行（表头之下、数据之上）
    data_row: int            # 0-based 行号：首个数据行
    sep: str                 # ',' / ';' / '\t'
    encoding: str
    decimal: str             # '.' 或 ','
    known_format: str | None # 命中的规则名，如 "winwert"；启发式命中则 None

    @property
    def is_trivial(self) -> bool: ...  # header 0 / 无单位行 / 点小数

def sniff_csv_layout(path, *, max_lines: int = 10) -> CsvLayout | None
```

返回 `None` 或 `is_trivial` → 调用方走**原封不动的 legacy 路径**（现有
enc×sep 试错循环），保证规整 CSV 字节级同行为。

### 识别算法（前 max_lines 行）

1. **读行**：编码依次试 `utf-8-sig, utf-8, gbk, latin1`。
2. **定分隔符**：对 `, ; \t` 各自用 `csv.reader` 切前 N 行，取"多数行列数一致
   且 >1"的分隔符；都不满足 → None。
3. **已知格式规则表**（数据驱动，一行一格式）：

   ```python
   _KNOWN_FORMAT_RULES = (
       # (名字, predicate(小写行列表), 表头行号)
       ("winwert", lambda lower: "winwert" in lower[0], 1),
   )
   ```

   命中 → 表头定死，向下解析 units_row / data_row。
4. **通用启发式**：
   - `data_row` = 首个"数值单元格占比 ≥60% 且 ≥2 格"的行（数值判定同时试
     点小数与逗号小数）。
   - `data_row == 0` 或找不到 → 返回 None（headerless/垃圾 → legacy 定夺）。
   - 候选表头 = data_row 上方、列数与数据行一致（±1）的非数值行；横幅行
     （单格长文本）天然被列数过滤掉。
   - 候选仅 1 行 → 即表头。候选 ≥2 行且紧邻数据的那行"像单位"（≥50% 非空格
     为 ≤6 字符或 `[...]` 包裹，如 `[s]` `rpm` `Nm`）→ 上一候选为表头、
     紧邻行为 units_row；否则紧邻行即表头。
5. **小数逗号**：数据行多数单元格匹配 `^-?\d+,\d*$` → `decimal=','`（此时
   分隔符必非逗号）。

### `load_csv` 接线（`loader.py`）

```python
@staticmethod
def load_csv(fp):
    layout = None
    try:
        layout = sniff_csv_layout(fp)
    except Exception:
        layout = None   # 嗅探失败绝不能让原本能读的文件变不能读
    if layout is not None and not layout.is_trivial:
        return DataLoader._load_csv_with_layout(fp, layout)
    ... 现有 12 行原样 ...
```

`_load_csv_with_layout`：`pd.read_csv(fp, encoding=..., sep=...,
skiprows=[表头前所有行 + units_row], header=0, decimal=...)`；
单位行用 `csv.reader` 手工切，`units = dict(zip(表头格, 单位格))`（去空）；
数值化 + `dropna/interpolate` 清洗与 legacy 一致；返回 `(df, channels, units)`
三元组（与 MF4/Excel 同构）。

错误语义不变：完全解析失败仍抛 `ValueError("Cannot parse CSV")`
（`loader.py:588`）——`_load_one` 的 else 兜底依赖它。

## 验收标准

1. 合成 winwert 样例（第一行 `WinWert ...` 横幅、第二行通道名）→ 通道名正确、
   数据行数正确、第一行横幅不进数据。
2. 表头在第 3/4 行的合成样例（多行横幅）→ 启发式正确识别。
3. 表头+单位行样例 → units dict 填充（`Time→s`、`EngSpd→rpm` 级别）。
4. 分号分隔 + 逗号小数（德系）样例 → 数值正确解析。
5. `utf-8-sig` BOM 样例 → 首列通道名无 `﻿` 污染。
6. 规整 CSV：`load_csv` 结果与改动前**逐值相等**；
   `tests/test_batch_loader_dispatch.py` 不改一字通过。
7. 垃圾输入（二进制/空文件）→ 仍抛 `ValueError("Cannot parse CSV")`。
8. 真实样例回归位：`tests/fixtures/csv_formats/` 目录 + 参数化测试自动吃目录内
   `*.csv`（目录空则 0 收集）；用户后续放入真实 winwert 导出即成回归用例。
9. 时间列/fs：布局识别后的 DataFrame 列名进入 `FileData` 现有 `_TIME_NAMES`
   逻辑，无需改 `file_data.py`（用含 `Time` 列的样例断言 fs 推断正确）。

## 风险

- **启发式误判规整文件**：`is_trivial` 短路 + legacy 路径兜底，误判面收敛为
  "非平凡布局才走新路径"。
- **winwert 真实文件与描述不符**（分隔符/单位行/编码未知）：规则表一行即可调；
  真实样例进 fixtures 目录后立即变回归。
- **未知扩展名走 else 兜底进 load_csv**：嗅探全程 try/except 包裹，失败即
  legacy，行为不劣化。
