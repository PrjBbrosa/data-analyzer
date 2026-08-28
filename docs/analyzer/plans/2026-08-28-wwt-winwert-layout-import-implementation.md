# WWT WinWert 原生排版导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打开带 WinWert 显示状态的 WWT 时，安全恢复计算通道和逐曲线 XY 关系，按显示块创建普通时域 View，并把原生相对排版批量投影到 UltraView。

**Architecture:** `mf4_analyzer/io` 一次解析正文、公式和全部 `DatenFenste2`，输出 Qt 无关的 `WwtDocument`；UI-neutral 翻译器把 record identity 映射为复合 fid/channel 或只读 WWT record 引用，再生成标准 `ViewState`。一个专用 MainWindow 协调器拥有确认与批量提交事务；现有 pyqtgraph Canvas 和 UltraView 只消费通用曲线/布局 DTO，不导入 WWT 格式模块。

**Tech Stack:** Python 3、dataclasses、Python `ast`、NumPy、pandas、PyQt5、pyqtgraph、pytest/pytest-qt、TraceLab View/UltraView state contracts。

**Spec:** `docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md`

## Global Constraints

- 图形语义一致：View 数量、可见曲线、逐曲线 X/Y、轴范围/标签/刻度、网格、颜色、Line 和线宽一致；TraceLab chrome、字体与抗锯齿不仿制 WinWert。
- `mf4_analyzer/io` 不得导入 `mf4_analyzer.ui`、Qt、`MainWindow` 或 renderer。
- 禁止 `eval`、`exec`、字符串 NumExpr、假时间轴、假采样率、插值、重采样和 `min(len(x), len(y))` 静默截断。
- `Pars` 第一阶段只接受 `+ - * /`、一元正负、括号、数值常量、`abs()` 和 0 基 `kN` record 引用。
- UCAN 字面契约：21 records、4 个成功公式、7 displays、6 个独立 rect；普通 View 保留 7 个，UltraView 为 6 placed + 第 7 unplaced。
- 时域 View ceiling 使用 `ui/view_state.py:MAX_VIEWS`，当前值为 12；不得再写一个数字 12 作为业务 cap。
- `ViewState`、colors、ranges、bindings、项目 remap 和 close cleanup 均使用复合 fid/channel 或 fid/record identity；显示名称不是身份。
- 初始空白 View 最多复用一个；已有非空 View 不覆盖；cap 截断必须在确认框和 toast 中可见。
- 一个导入事务只绘制第一个新 View；不得轮流激活所有 View 生成 UltraView preview。
- UltraView 批量加入必须一次 history/dirty/refresh；不得循环调用私有 `_apply_add_ref()`。
- 实施时保留当前 dirty worktree，尤其是 `hints.py`、`quickref.py`、`window.py` 的用户改动；不得 checkout、revert 或覆盖。
- Qt 测试/探针隔离 QSettings；合成 drag/drop event 必须让 `QMimeData` 与 event 同寿命。
- 全套 gate 仅在稳定集成快照运行一次；main suite 与 `tests/acquisition_ui` 使用两个新鲜、顺序进程，不并发。

---

## File Structure

| 文件 | 责任 |
| --- | --- |
| `mf4_analyzer/io/wwt_document.py`（新增） | WWT record 目录、正文一次解析、全部显示块 DTO、只读 record store、`WwtDocument/WwtLoadResult` |
| `mf4_analyzer/io/wwt_formula.py`（新增） | 安全 AST 校验、依赖图、cycle/axis/shape 校验、公式向量求值 |
| `mf4_analyzer/io/wwt_format.py` | 保留 `load_wwt_groups()` 兼容门面，复用 document parser/materializer，不再复制 parser |
| `mf4_analyzer/io/wwt_display.py` | 多 trailer 枚举、窗口 rect/line width 与完整 row facts 解码；既有写路径不变 |
| `mf4_analyzer/io/loader.py` | 暴露 `DataLoader.load_wwt_document()`；`load_wwt()` 保持 groups 返回 |
| `mf4_analyzer/ui/time_curve_bindings.py`（新增） | 通用 `TimeDataRef/TimeCurveBinding`、JSON、fid remap、runtime resolver |
| `mf4_analyzer/ui/wwt_view_import.py`（新增） | Qt-free registered-record map、轴槽规划、`WwtViewProposal` 和 ViewState 翻译 |
| `mf4_analyzer/ui/view_state.py` | 可选 `curve_bindings` 字段和批量 ViewManager 提交 seam |
| `mf4_analyzer/ui/project_io.py` | binding 两端 fid remap、dropped refs 诊断 |
| `mf4_analyzer/ui/main_window/analysis_source_scope.py` | file close 前索引隐藏 binding refs |
| `mf4_analyzer/ui/main_window/_channel_scope_mixin.py` | file/channel 删除时对称过滤 binding |
| `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`（新增） | 确认框、blank/cap 决策、View 批量 commit、首 View render、UltraView handoff |
| `mf4_analyzer/ui/main_window/_project_io_mixin.py` | WWT 分支登记 result/fids 并调用 coordinator；非 WWT 路径不改 |
| `mf4_analyzer/ui/main_window/window.py` | 初始化 `WwtImportCoordinator`；既有 time payload 方法只薄委托 binding helper，不放新 WWT 算法 |
| `mf4_analyzer/ui/main_window/_view_mixin.py` | render 时把 state bindings 交给 payload builder；保持 restore settlement 顺序 |
| `mf4_analyzer/ui/pg_canvas/native_axes.py`（新增） | native major/unlabeled-grid tick facts 与 mm→logical-px 纯 helpers |
| `mf4_analyzer/ui/pg_canvas/tick_density.py` | native tick mode/用户 density override 入口；现有 adaptive path 不回归 |
| `mf4_analyzer/ui/pg_canvas/canvas.py`、`renderer.py` | 消费通用 row meta 的 axis id、tick facts、per-curve pen width |
| `mf4_analyzer/ultraview_core/native_layout.py`（新增） | Qt-free `NativeLayoutRect`→GridRect 归一化、exact overlap→unplaced plan |
| `mf4_analyzer/ultraview_core/board_ops.py` | 一次性应用 native layout plan 的纯 Board mutation |
| `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py` | 单事务 commit/history/refresh owner |
| `mf4_analyzer/ui/main_window/ultraview_coordinator.py` | public `add_time_views_from_native_layout(...)` façade |
| `mf4_analyzer/ui/hints.py`、`quickref.py` | 用户发现性文案；在现有 dirty edits 上最小合并 |
| `tests/test_wwt_document.py`（新增） | 真实 record/display/formula 字面契约与合成错误路径 |
| `tests/test_wwt_display.py` | 多 trailer、rect、line width、block bounds |
| `tests/ui/test_time_curve_bindings.py`（新增） | binding JSON/remap/resolution/shape 错误 |
| `tests/ui/test_wwt_view_import.py`（新增） | 三真实文件的 Qt-free View proposal 契约 |
| `tests/ui/test_wwt_import_flow.py`（新增） | Accept/Reject/blank/cap/project-restore/单 render 事务 |
| `tests/ui/test_ultraview_native_layout.py`（新增） | 6 placed + 1 unplaced、GridRect 字面值、一次 mutation |

---

### Task 1: 冻结 WWT record 与多显示块字面事实

**Files:**
- Create: `tests/test_wwt_document.py`
- Modify: `tests/test_wwt_display.py`
- Create: `mf4_analyzer/io/wwt_document.py`
- Modify: `mf4_analyzer/io/wwt_display.py`

**Interfaces:**
- Consumes: existing `_cstr`, WWT header/record offsets from `wwt_format.py`; existing `read_curve()` field semantics from `wwt_display.py`.
- Produces: `WwtRecord`, `WwtWindowRectMm`, `WwtCurveDisplay`, `WwtDisplayWindow`, `WwtDocument`, `parse_wwt_document(fp)`, `find_trailers(data)`.

- [ ] **Step 1: Record the scoped pre-change fingerprint and focused baseline**

Run in PowerShell:

```powershell
git rev-parse HEAD
git status --short
.\.venv\Scripts\python.exe -m pytest tests/test_wwt_format.py tests/test_wwt_display.py -q
```

Expected: record live stdout; do not require a full-suite baseline. If an existing focused test is red, stop and classify it before changing production code.

- [ ] **Step 2: Write failing real-file tests for all trailers and geometry**

Add assertions with the exact sample path and values:

```python
UCAN = _ROOT / "testdoc" / "WWT" / "UCAN-b6_P779_0007.wwt"

def test_ucan_record_catalog_and_all_display_windows():
    doc = parse_wwt_document(UCAN)
    assert len(doc.records) == 21
    assert [record.index for record in doc.records] == list(range(21))
    assert len(doc.windows) == 7
    assert [window.rect_mm for window in doc.windows] == [
        WwtWindowRectMm(25.0, 65.0, 100.0, 60.0),
        WwtWindowRectMm(41.0, 138.2, 90.0, 60.0),
        WwtWindowRectMm(147.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(215.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(147.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
    ]
    assert [window.line_width_mm for window in doc.windows] == [0.2] * 7
```

Also assert `find_trailers()` returns 7 strictly increasing offsets and the first six differences are exactly 6114 bytes.

- [ ] **Step 3: Run the new tests and verify the missing API failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wwt_document.py tests/test_wwt_display.py -q
```

Expected: FAIL during import because `parse_wwt_document`, DTOs, or `find_trailers` do not exist. A pass caused by skipping the real sample is not a valid red gate; the repository contains this file.

- [ ] **Step 4: Implement immutable record/display DTOs and one-pass record scanning**

Create shapes with exact fields:

```python
@dataclass(frozen=True)
class WwtRecord:
    index: int
    tag: str
    declared_n: int
    name: str
    unit: str
    scale_a: float
    offset_c: float
    axis_record: int | None
    values: np.ndarray | None
    formula: str | None

@dataclass(frozen=True)
class WwtWindowRectMm:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class WwtDocument:
    path: Path
    version: str
    records: tuple[WwtRecord, ...]
    groups: tuple[dict, ...]
    windows: tuple[WwtDisplayWindow, ...]
    diagnostics: tuple[str, ...]
```

Move the scanning implementation from `load_wwt_groups()` rather than copying it. Numeric record values remain physical values (`raw.astype(float64) * a + c`) and are marked read-only with `array.setflags(write=False)`. `Pars` stores formula bytes and no invented values.

- [ ] **Step 5: Implement bounded multi-trailer/window decoding**

Add constants and conversion:

```python
LINE_WIDTH_OFF = 13
WINDOW_RECT_OFF = 31
WINDOW_UNIT_SCALE = 20.0

def decode_window_rect(data: bytes, trailer: int) -> WwtWindowRectMm:
    left, top, right, bottom = struct.unpack_from("<hhhh", data, trailer + WINDOW_RECT_OFF)
    return WwtWindowRectMm(
        left / WINDOW_UNIT_SCALE,
        -bottom / WINDOW_UNIT_SCALE,
        (right - left) / WINDOW_UNIT_SCALE,
        (top - bottom) / WINDOW_UNIT_SCALE,
    )
```

`find_trailers()` must validate `table_end = marker + CURVE_BASE + count*CURVE_STRIDE` against the next marker/EOF. A bad block appends a diagnostic and parsing continues at the next marker; it does not discard body groups.

- [ ] **Step 6: Run parser/display tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wwt_document.py tests/test_wwt_display.py tests/test_wwt_format.py -q
```

Expected: PASS; existing WWT physical scaling tests remain unchanged.

- [ ] **Step 7: Commit the parser slice**

```powershell
git add mf4_analyzer/io/wwt_document.py mf4_analyzer/io/wwt_display.py tests/test_wwt_document.py tests/test_wwt_display.py
git commit -m "feat(wwt): parse record catalog and all display windows"
```

---

### Task 2: 安全物化 `Pars` 计算通道

**Files:**
- Create: `mf4_analyzer/io/wwt_formula.py`
- Modify: `mf4_analyzer/io/wwt_document.py`
- Modify: `mf4_analyzer/io/wwt_format.py`
- Modify: `mf4_analyzer/io/loader.py`
- Modify: `tests/test_wwt_document.py`
- Modify: `tests/test_wwt_format.py`

**Interfaces:**
- Consumes: `WwtDocument.records`, record `axis_record`, immutable physical arrays from Task 1.
- Produces: `FormulaResult`, `WwtFormulaError(code, record_index, detail)`, `evaluate_wwt_formulas(records, *, strict=False)`, `load_wwt_document(fp) -> WwtLoadResult`, `DataLoader.load_wwt_document(fp)`.

- [ ] **Step 1: Write failing tests for the four literal formulas**

```python
def test_ucan_pars_formulas_materialize_on_operand_axis():
    loaded = load_wwt_document(UCAN)
    records = {record.index: record for record in loaded.document.records}
    expected = {
        4: -(records[7].values - (-records[13].values)),
        5: -(records[7].values - (-records[15].values)),
        11: np.abs(records[8].values),
        12: records[14].values + records[16].values,
    }
    assert all(records[index].tag == "Pars" for index in expected)
    for record_index, values in expected.items():
        got = records[record_index].values
        assert got.shape == (15274,)
        np.testing.assert_allclose(got, values, rtol=0.0, atol=0.0)
    assert records[4].declared_n == 50000
```

Assert formula strings exactly match the four literals in the spec and derived channel metadata includes `derived=True`, `record_index`, `formula`, and `formula_refs`.

- [ ] **Step 2: Write failing safety/shape tests with synthetic records**

Cover exact codes:

```python
@pytest.mark.parametrize(("formula", "code"), [
    ("__import__('os')", "unsupported_formula"),
    ("k1.attr", "unsupported_formula"),
    ("k999 + 1", "missing_formula_ref"),
])
def test_formula_rejects_unsafe_or_missing_refs(formula, code):
    records = (
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, np.ones(3), None),
        WwtRecord(2, "Pars", 3, "Derived", "", 1.0, 0.0, None, None, formula),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == code
```

Add separate `formula_cycle`, `formula_axis_mismatch`, `formula_shape_mismatch`, and `formula_no_finite_values` cases. The shape test must prove no prefix truncation occurred.

- [ ] **Step 3: Run the formula tests and verify red**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wwt_document.py -k "pars or formula" -q
```

Expected: FAIL because evaluator/materialization APIs are absent.

- [ ] **Step 4: Implement the AST whitelist without string execution**

Use an explicit recursive evaluator:

```python
_BIN_OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide}
_UNARY_OPS = {ast.UAdd: lambda value: value, ast.USub: np.negative}

def _record_ref(node: ast.Name) -> int:
    if not re.fullmatch(r"k\d+", node.id):
        raise WwtFormulaError("unsupported_formula", -1, node.id)
    return int(node.id[1:])
```

Validate every node before evaluating. Only `abs(expr)` with no keywords is accepted. Do not retain a callable namespace and do not call `compile()`.

- [ ] **Step 5: Implement dependency memoization and acquisition-cohort guards**

For each formula record:

```text
visiting add(index)
→ recursively resolve every kN
→ require one axis_record across array leaves
→ require exactly one one-dimensional length
→ evaluate under numpy errstate
→ require output.ndim == 1 and output length unchanged
→ cache immutable float64 output
→ visiting remove(index)
```

On failure, preserve the raw `Pars` record and add a structured diagnostic; do not abort unrelated formulas or original groups.

- [ ] **Step 6: Materialize successful formulas into the owning group**

Use `axis_record` to choose a group, append derived columns in WWT record order, and reuse existing duplicate-name disambiguation. For UCAN the main 15274-point group must include all four successful formulas. Update old exact channel-list tests to include only the now-proven derived names; keep unsupported `Pars` in `skipped_channels`.

Expose:

```python
@dataclass(frozen=True)
class WwtLoadResult:
    groups: tuple[dict, ...]
    document: WwtDocument

def load_wwt_document(fp: str | Path) -> WwtLoadResult: ...
def load_wwt_groups(fp: str | Path) -> list[dict]:
    return list(load_wwt_document(fp).groups)
```

- [ ] **Step 7: Add a static no-eval guard and run the IO suite**

```python
def test_wwt_formula_module_never_uses_eval_or_exec():
    tree = ast.parse(Path(wwt_formula.__file__).read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not ({"eval", "exec", "compile"} & called)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wwt_document.py tests/test_wwt_format.py tests/test_batch_runner.py -k "wwt or formula" -q
```

Expected: PASS; live counts are authoritative.

- [ ] **Step 8: Commit the formula slice**

```powershell
git add mf4_analyzer/io/wwt_formula.py mf4_analyzer/io/wwt_document.py mf4_analyzer/io/wwt_format.py mf4_analyzer/io/loader.py tests/test_wwt_document.py tests/test_wwt_format.py
git commit -m "feat(wwt): safely materialize WinWert formula channels"
```

---

### Task 3: 增加通用逐曲线数据绑定与持久化

**Files:**
- Create: `mf4_analyzer/ui/time_curve_bindings.py`
- Modify: `mf4_analyzer/ui/view_state.py`
- Modify: `mf4_analyzer/ui/project_io.py`
- Modify: `mf4_analyzer/ui/main_window/analysis_source_scope.py`
- Modify: `mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- Create: `tests/ui/test_time_curve_bindings.py`
- Modify: `tests/ui/test_project_session.py`

**Interfaces:**
- Consumes: `FileData.data`, `FileData.source_metadata["wwt_record_store"]`, project `fid_map`.
- Produces: `TimeDataRef`, `TimeCurveBinding`, `resolve_time_data_ref(ref, files)`, `remap_curve_bindings(bindings, fid_map)`, `filter_curve_bindings(bindings, *, removed_fids=(), removed_channels=())`, optional `ViewState.curve_bindings`.

- [ ] **Step 1: Write failing serialization and resolver tests**

Create channel and WWT-record refs:

```python
channel_ref = TimeDataRef(kind="channel", fid="f1", channel="Rack Force")
record_ref = TimeDataRef(kind="wwt_record", fid="f1", record_index=17)
binding = TimeCurveBinding(
    binding_id="window-6-record-18",
    y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=18),
    x_ref=record_ref,
    display_name="Rack Force [KN]",
    unit="KN",
    color="#000080",
    axis_id="window-6-axis-18",
    y_range=(0.0, 18.0),
    y_tick_interval=1.0,
    y_grid_interval=None,
    line_width_mm=0.2,
    line_style="line",
)
assert TimeCurveBinding.from_dict(binding.to_dict()) == binding
```

Assert resolver returns exact arrays, rejects missing owner/channel/record and length mismatch with `TimePlotIssue` codes; do not assert a shortened output.

- [ ] **Step 2: Run focused tests and verify red**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests/ui/test_time_curve_bindings.py -q
```

Expected: FAIL on missing module/API.

- [ ] **Step 3: Implement validated dataclasses and runtime resolution**

Implement `__post_init__` invariants exactly:

```python
if self.kind == "channel" and (not self.fid or not self.channel or self.record_index is not None):
    raise ValueError("channel ref requires fid/channel only")
if self.kind == "wwt_record" and (not self.fid or self.record_index is None or self.channel is not None):
    raise ValueError("wwt_record ref requires fid/record_index only")
```

`resolve_time_data_ref()` returns a one-dimensional numpy view plus source facts. For `wwt_record`, read only the owner FileData metadata store; never generate `FileData.time_array`.

- [ ] **Step 4: Add `ViewState.curve_bindings` with backward-compatible JSON**

Append the field after existing positional fields:

```python
curve_bindings: list[TimeCurveBinding] = field(default_factory=list)
```

`to_dict()` emits a list of dicts; `from_dict()` treats a missing field as `[]` and drops malformed items into the existing project warning path rather than crashing the entire project.

- [ ] **Step 5: Implement project remap and lifecycle indexing**

`remap_curve_bindings()` must map both `x_ref.fid` and `y_ref.fid`; if either fid is absent, drop the whole binding and let `collect_dropped_time_refs()` report `(view_id, fid, "binding:x"|"binding:y")`.

Extend:

- `analysis_source_scope._append_time_persisted_uses()` with roles `curve_x` and `curve_y`;
- `_filter_time_view_state_for_removed_fids()` to remove bindings touching removed fids;
- `_filter_time_view_state_for_removed_channels()` to remove channel-kind refs touching deleted channels while keeping unrelated WWT-record refs.

- [ ] **Step 6: Run binding/project/ownership tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_time_curve_bindings.py tests/ui/test_project_session.py tests/ui/test_main_window_state_ownership.py -q
```

Expected: PASS. Do not widen the state-ownership whitelist; move writes into the new binding helpers/coordinator if the ratchet fails.

- [ ] **Step 7: Commit the binding slice**

```powershell
git add mf4_analyzer/ui/time_curve_bindings.py mf4_analyzer/ui/view_state.py mf4_analyzer/ui/project_io.py mf4_analyzer/ui/main_window/analysis_source_scope.py mf4_analyzer/ui/main_window/_channel_scope_mixin.py tests/ui/test_time_curve_bindings.py tests/ui/test_project_session.py
git commit -m "feat(time): persist per-curve XY bindings"
```

---

### Task 4: 把 WWT 显示窗口翻译为 View 提案

**Files:**
- Create: `mf4_analyzer/ui/wwt_view_import.py`
- Create: `tests/ui/test_wwt_view_import.py`

**Interfaces:**
- Consumes: `WwtLoadResult`, registered `(fid, group)` sequence, `TimeCurveBinding`, `ViewState`.
- Produces: `RegisteredWwtSources`, `WwtViewProposal`, `build_registered_record_map(...)`, `build_wwt_view_proposals(...)`.

Test helper contract in this task:

```python
def proposals_for(filename: str) -> list[WwtViewProposal]:
    loaded = load_wwt_document(_ROOT / "testdoc" / "WWT" / filename)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    return build_wwt_view_proposals(loaded.document, registered)
```

`register_groups_for_test()` assigns deterministic `f1`, `f2`, ... in group order and builds
`RegisteredWwtSources` exclusively from each group's `channel_metadata.record_index`; it does not instantiate Qt widgets.

- [ ] **Step 1: Write the SFNS and YP failing proposal tests**

Assert the literal contracts:

```python
def test_yp_proposal_keeps_tolerance_and_measurement_with_distinct_x_refs():
    proposals = proposals_for("YP_SS_P779_0007.wwt")
    assert len(proposals) == 1
    view = proposals[0].state
    assert view.xlim == (-720.0, 720.0)
    assert view.plot_mode == "overlay"
    by_name = {binding.display_name: binding for binding in view.curve_bindings}
    assert by_name["Tol_oben [mm]"].color == "#ff0000"
    assert by_name["Tol_oben [mm]"].x_ref.record_index == 3
    assert by_name["Druckstückspiel [mm]"].x_ref.channel == "Lenkwinkel"
    assert by_name["Tol_oben [mm]"].axis_id == by_name["Druckstückspiel [mm]"].axis_id
```

For SFNS assert X `Rack Travel`, `(-100,100)`, X tick 10; Y `Rack Force`, `(-1500,1500)`, Y tick 500/grid 100, deep blue.

- [ ] **Step 2: Write the UCAN failing proposal test**

Assert 7 proposal names/order, all four computed channels are channel-kind refs, and records 17–20 remain WWT-record refs. Assert every proposal retains its literal `rect_mm` and `line_width_mm=0.2`.

- [ ] **Step 3: Run tests and verify red**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_view_import.py -q
```

Expected: FAIL because translator APIs are absent.

- [ ] **Step 4: Build record identity mapping from metadata, never labels**

Define:

```python
@dataclass(frozen=True)
class RegisteredWwtSources:
    owner_fid: str
    fids: tuple[str, ...]
    record_channels: Mapping[int, tuple[str, str]]

@dataclass(frozen=True)
class WwtViewProposal:
    window_index: int
    rect_mm: WwtWindowRectMm
    state: ViewState
    warnings: tuple[str, ...]
```

Walk each group channel metadata `record_index` after registration. A duplicate record index is a programming/data error and produces one explicit diagnostic; no display-label lookup fallback.

- [ ] **Step 5: Implement visible/selected axis-slot planning**

Algorithm:

```text
visible rows in record order
→ selected+visible rows create explicit axis owners
→ each unselected visible row matches an owner by normalized unit + exact lo/hi/tick/grid
→ no match creates its own hidden-label axis and warning
```

Use stable ids `window-{window_index}-axis-{owner_record}` and binding ids
`window-{window_index}-record-{record_index}`. Row `x_curve` wins; `global_x` is fallback only.

- [ ] **Step 6: Construct complete ViewState proposals**

Populate name, attachments, checked, colors, overlay mode, xlim, ylims, `axis_opts["native_ticks"]`, and ordered bindings. Normal visible Y records appear in both `checked` and binding; auxiliary records only in binding. Store the read-only record store in the owner group's source metadata before proposal resolution.

- [ ] **Step 7: Run proposal and neutral import tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_view_import.py tests/ui/test_time_curve_bindings.py tests/ui/test_import_boundaries.py tests/test_native_import_boundaries.py -q
```

Expected: PASS; importing `mf4_analyzer.io.wwt_document` must not import Qt/UI.

- [ ] **Step 8: Commit the translator slice**

```powershell
git add mf4_analyzer/ui/wwt_view_import.py tests/ui/test_wwt_view_import.py
git commit -m "feat(wwt): translate WinWert windows into time views"
```

---

### Task 5: 渲染逐曲线 X、原生轴和物理线宽

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/native_axes.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_view_mixin.py`
- Modify: `mf4_analyzer/ui/pg_canvas/tick_density.py`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`
- Modify: `tests/ui/test_main_window_smoke.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Create: `tests/ui/test_wwt_native_render.py`

**Interfaces:**
- Consumes: active `ViewState.curve_bindings`, `resolve_time_data_ref`, row meta `axis_id/native_ticks/line_width_mm`.
- Produces: `native_tick_levels(lo, hi, major, grid)`, `line_width_px(mm, logical_dpi)`, binding-aware `TimePlotBuildResult` rows.

- [ ] **Step 1: Write pure tick/width failing tests**

```python
def test_native_tick_levels_label_major_and_leave_grid_unlabelled():
    levels = native_tick_levels(-720.0, 720.0, 120.0, 60.0)
    assert [value for value, _ in levels.major] == list(np.arange(-720.0, 721.0, 120.0))
    assert all(label for _, label in levels.major)
    assert [value for value, label in levels.grid if not label][:3] == [-660.0, -540.0, -420.0]
    assert not ({value for value, _ in levels.major} & {value for value, _ in levels.grid})

def test_line_width_mm_uses_logical_dpi_and_minimum_visible_width():
    assert line_width_px(0.2, 96.0) == 1.0
    assert line_width_px(0.5, 96.0) == pytest.approx(1.8897637795)
```

Also test the 2000-grid cap returns a structured adaptive fallback.

- [ ] **Step 2: Write binding-aware payload failures**

Construct a YP View and assert two rows have different X arrays/lengths but both render; construct an explicit mismatch and assert one `unaligned` issue with the original lengths. Prohibit any assertion accepting a common prefix.

- [ ] **Step 3: Run the new render tests and verify red**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_native_render.py tests/ui/test_pg_timedomain_canvas.py -k "native or binding" -q
```

Expected: FAIL on missing helpers/row meta behavior.

- [ ] **Step 4: Implement native tick facts without `setTickSpacing(major, minor)`**

`native_tick_levels()` computes finite values with integer index bounds (`ceil(lo/step)` through `floor(hi/step)`) to avoid accumulation drift. Apply:

```python
axis.setStyle(maxTickLevel=1)
axis.setTicks([levels.major, levels.grid])
```

Grid labels are `""`. On user tick-density changes clear the active View's `native_ticks` then call the existing adaptive controller. Preserve the current test that `_tickSpacing is None`.

- [ ] **Step 5: Extend time payload assembly via a helper, not a second builder**

Add a small helper in `time_curve_bindings.py` that returns resolved rows and issues; `_build_time_plot_data()` merges it with normal checked channels in binding order. A normal checked channel represented by a binding is emitted once, not once from checked and again from binding. User-added checked channels absent from the imported bindings append in Navigator order.

For standalone XY record refs, do not apply acquisition time mask. Add `native_xy_full_range=True` to row metadata so diagnostics and UltraView digest remain truthful.

- [ ] **Step 6: Feed generic axis/pen facts into Canvas collaborators**

Use row metadata:

```python
{
    "axis_group": binding.axis_id,
    "native_axis": {"range": binding.y_range, "major": binding.y_tick_interval, "grid": binding.y_grid_interval},
    "line_width_mm": binding.line_width_mm,
}
```

Renderer converts mm with the canvas/widget logical DPI at pen creation time. Do not mutate global default pens or render-quality ink thresholds.

- [ ] **Step 7: Preserve the one-settle View restore order**

Keep `_render_view_to_canvas` order exactly:

```python
canvas.restore_visible_xlim(state.xlim, flush=False)
canvas.restore_visible_ylims(state.ylims)
canvas.settle_view_restore()
```

Add a regression test that a WWT View invokes settle once after final X/Y geometry and does not rewrite the 150 ms interactive idle timer.

- [ ] **Step 8: Run focused renderer/boundary gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_native_render.py tests/ui/test_main_window_smoke.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py -q
```

Expected: PASS. If `_CanvasBackref` invariants fail, declare new collaborator ownership/delegation accurately; do not add undeclared host writes.

- [ ] **Step 9: Commit the render slice**

```powershell
git add mf4_analyzer/ui/pg_canvas/native_axes.py mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/main_window/_view_mixin.py mf4_analyzer/ui/pg_canvas/tick_density.py mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/renderer.py tests/ui/test_main_window_smoke.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_wwt_native_render.py
git commit -m "feat(time): render native per-curve axes and widths"
```

---

### Task 6: 实现打开确认与原子 View 创建

**Files:**
- Create: `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- Modify: `mf4_analyzer/ui/view_state.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Create: `tests/ui/test_wwt_import_flow.py`
- Modify: `tests/ui/test_drop_import.py`
- Modify: `tests/ui/test_project_session.py`

**Interfaces:**
- Consumes: `WwtLoadResult`, registered fids, `build_wwt_view_proposals`, `ViewManager`, `_restoring_project`.
- Produces: `ViewManager.insert_states(states, *, reuse_blank, active_offset)`, `WwtImportCoordinator.offer_layout(...) -> WwtImportOutcome`.

- [ ] **Step 1: Write failing Accept/Reject/restore tests**

Test exact outcomes:

```text
Accept UCAN → 7 normal Views, first active, plot_time called once
Reject UCAN → data/derived channels loaded, View count unchanged
dialog close → same as Reject
_restoring_project=True → no dialog and no generated View
```

Patch the coordinator dialog seam, not global `QMessageBox.question`, so button roles and exact copy remain testable.

- [ ] **Step 2: Write failing blank/cap tests**

- untouched initial View is replaced by proposal 1 and six states append;
- a View with attachments, checked, bindings, remarks, cursor, non-default axis or ranges is not blank;
- with only 3 available slots, informative text says `检测到 7 个，可创建 3 个`, exactly 3 are committed, and toast reports `已生成 3/7 个 WinWert View`.

- [ ] **Step 3: Run flow tests and verify red**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_import_flow.py tests/ui/test_drop_import.py -q
```

Expected: FAIL on missing coordinator/batch insertion.

- [ ] **Step 4: Add one-emission ViewManager batch insertion**

Implement a method that validates capacity before mutating, optionally replaces index 0 only when a passed pure predicate says it is blank, appends remaining states, emits `views_changed` once, then changes active once. Return inserted indexes; `-1` is not used for partial results.

- [ ] **Step 5: Implement the coordinator and exact dialog copy**

`WwtImportCoordinator` owns:

```python
@dataclass(frozen=True)
class WwtImportOutcome:
    detected: int
    created: int
    view_ids: tuple[str, ...]
    warnings: tuple[str, ...]
```

For UCAN, body text must include 7 windows, 4 formulas, and the 6/7 exact-overlap warning. Default AcceptRole text is `按 WinWert 排版并绘图`; RejectRole is `仅加载数据`. Use `fit_message_box_buttons_to_text()`.

- [ ] **Step 6: Wire the existing WWT load branch without a second file read**

Replace only the `.wwt` branch with:

```text
result = DataLoader.load_wwt_document(fp)
register result.groups while collecting new fids
attach the shared immutable record store to registered FileData metadata
if not _restoring_project: coordinator.offer_layout(result.document, fids)
```

Keep `_load_one`'s existing finally/auto-attach behavior and diagnostics. Non-WWT branches remain byte-for-byte outside formatting context.

- [ ] **Step 7: Keep drag tests safe and prove all entry points converge**

Add file-picker/drop/public `load_file()` tests that reach the same WWT coordinator seam. Synthetic helpers must retain MIME:

```python
event = QDropEvent(..., mime, ...)
event._mime_ref = mime
return event
```

- [ ] **Step 8: Run flow/project/state gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_wwt_import_flow.py tests/ui/test_drop_import.py tests/ui/test_project_session.py tests/ui/test_main_window_state_ownership.py -q
```

Expected: PASS; no project-restore prompt and no QSettings leakage.

- [ ] **Step 9: Commit the import transaction slice**

```powershell
git add mf4_analyzer/ui/main_window/wwt_import_coordinator.py mf4_analyzer/ui/view_state.py mf4_analyzer/ui/main_window/_project_io_mixin.py mf4_analyzer/ui/main_window/window.py tests/ui/test_wwt_import_flow.py tests/ui/test_drop_import.py tests/ui/test_project_session.py
git commit -m "feat(wwt): create native views after import confirmation"
```

---

### Task 7: 批量投影 WinWert 矩形到 UltraView

**Files:**
- Create: `mf4_analyzer/ultraview_core/native_layout.py`
- Modify: `mf4_analyzer/ultraview_core/board_ops.py`
- Modify: `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- Modify: `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- Create: `tests/ui/test_ultraview_native_layout.py`
- Modify: `tests/ui/test_ultraview_project_session.py`
- Modify: `tests/ui/test_ultraview_structure.py`

**Interfaces:**
- Consumes: ordered `(UltraViewRef, NativeLayoutRect)` items, active free-grid Board, existing grid constants/legalizer/history funnel；import coordinator 从 WWT mm DTO 显式转换，不让 UltraView core 导入 WWT IO。
- Produces: `NativeLayoutPlan`, `plan_native_layout(items)`, `apply_native_layout(board, plan)`, public `add_time_views_from_native_layout(items)`.

- [ ] **Step 1: Write the pure UCAN layout failing test with literal GridRects**

Using the spec mm rects and edge quantization, assert:

```python
assert plan.placed == (
    (refs[0], GridRect(0, 0, 10, 6)),
    (refs[1], GridRect(2, 8, 9, 6)),
    (refs[2], GridRect(12, 0, 5, 6)),
    (refs[3], GridRect(19, 0, 5, 6)),
    (refs[4], GridRect(12, 8, 5, 6)),
    (refs[5], GridRect(19, 8, 5, 6)),
)
assert plan.unplaced == (refs[6],)
assert plan.warnings == ("exact_overlap: 7 -> 6",)
```

This uses one scale `GRID_COLUMNS / 240.5 mm`, translates by `(left=25, top=2.5)`, rounds edges, then subtracts edges for span.

- [ ] **Step 2: Write collision/cap/transaction failures**

Cover existing board members, quantized partial collision, placed cap 24, membership cap 200, and duplicate ref. Assert a seven-item import creates one history entry, calls mark-dirty once, and refreshes projection once.

- [ ] **Step 3: Run UltraView native layout tests and verify red**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests/ui/test_ultraview_native_layout.py -q
```

Expected: FAIL on missing plan/API.

- [ ] **Step 4: Implement Qt-free edge normalization and exact-overlap detection**

Define:

```python
@dataclass(frozen=True)
class NativeLayoutRect:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class NativeLayoutPlan:
    placed: tuple[tuple[UltraViewRef, GridRect], ...]
    unplaced: tuple[UltraViewRef, ...]
    warnings: tuple[str, ...]
```

Compare original rect edges with absolute tolerance `1e-6`. Use the first exact duplicate as placed owner; later duplicate goes unplaced. Validate finite positive width/height before computing bounds.

- [ ] **Step 5: Apply the plan through one Board mutation**

`apply_native_layout()` checks membership/placed caps, adds valid `FreeGridPlacement`s in input order, adds remainder to `unplaced`, and returns warnings. It must not mark dirty or refresh; WorkspaceController owns those side effects once after commit.

- [ ] **Step 6: Add one public coordinator façade**

Expose:

```python
def add_time_views_from_native_layout(
    self,
    items: Sequence[tuple[str, NativeLayoutRect]],
) -> tuple[str, ...]:
    """Add stable time view ids to the active Board in one mutation."""
```

The façade constructs `UltraViewRef("time", view_id)` and delegates. Do not import `WwtDocument`; only the neutral rect shape/protocol crosses the seam.

- [ ] **Step 7: Prove persistence and structure guards**

Save/reopen a workspace containing the 6 literal GridRects and one unplaced ref; assert identical refs/rects/order. `test_ultraview_structure.py` must pass without widening frozen mutation exceptions.

- [ ] **Step 8: Run focused UltraView gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_ultraview_native_layout.py tests/ui/test_ultraview_project_session.py tests/ui/test_ultraview_board_history.py tests/ui/test_ultraview_placement_history.py tests/ui/test_ultraview_structure.py -q
```

Expected: PASS; one batch mutation and one projection refresh.

- [ ] **Step 9: Commit the UltraView slice**

```powershell
git add mf4_analyzer/ultraview_core/native_layout.py mf4_analyzer/ultraview_core/board_ops.py mf4_analyzer/ui/main_window/ultraview_workspace_controller.py mf4_analyzer/ui/main_window/ultraview_coordinator.py tests/ui/test_ultraview_native_layout.py tests/ui/test_ultraview_project_session.py tests/ui/test_ultraview_structure.py
git commit -m "feat(ultraview): project WinWert native window layouts"
```

---

### Task 8: 用户文案、确定性证据与集成验收

**Files:**
- Modify: `mf4_analyzer/ui/hints.py`
- Modify: `mf4_analyzer/ui/quickref.py`
- Modify: `tests/ui/test_hints.py`
- Modify: `tests/ui/test_quickref.py`
- Create: `scripts/probe_wwt_native_import.py`
- Create: `tests/test_probe_wwt_native_import.py`
- Modify: `docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md` only if implementation facts require an explicitly reviewed correction
- Modify: `docs/analyzer/plans/2026-08-28-wwt-winwert-layout-import-implementation.md` to record executed gates/status

**Interfaces:**
- Consumes: completed parser/View/UltraView public seams.
- Produces: accurate user discovery copy, deterministic JSON/PNG evidence under `.state` at runtime, final verification record.

- [ ] **Step 1: Merge help copy without overwriting the dirty worktree**

Before editing:

```powershell
git diff -- mf4_analyzer/ui/hints.py mf4_analyzer/ui/quickref.py tests/ui/test_hints.py tests/ui/test_quickref.py
```

Add one hint and one quick-reference entry that say WWT can restore WinWert Views, computed channels and UltraView layout. Copy must also say unsupported formulas/display options produce warnings; do not claim pixel identity or universal WinWert compatibility.

- [ ] **Step 2: Write copy tests first, then make the minimal merge**

Tests assert the released strings contain `WWT`, `WinWert`, `View`, and `UltraView`, and do not contain `像素级一致` or `全部公式`. Run them red before editing production copy.

- [ ] **Step 3: Create a read-only deterministic probe**

`scripts/probe_wwt_native_import.py` accepts one WWT path and `--output-dir`; it emits:

```text
document.json  records/windows/formulas/diagnostics
views.json     proposal names/bindings/ranges/ticks/colors
board.json     placed GridRects/unplaced refs
active.png     active TraceLab canvas render
```

Default output dir must be rejected; caller supplies an explicit `.state/wwt-native-import-*` path. The probe uses a temporary INI QSettings store before creating the app and never changes real `MF4Analyzer/DataAnalyzer` keys.

- [ ] **Step 4: Test the probe contract and QSettings isolation**

Test JSON literal values for SFNS/YP/UCAN and assert the probe code either injects a temp INI settings object or redirects the exact organization/application factory before widget creation. Check:

```powershell
rg -n "QSettings|set_expanded|setChecked|sync\(" scripts/probe_wwt_native_import.py tests/test_probe_wwt_native_import.py
```

- [ ] **Step 5: Run all focused owner and boundary gates**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
$env:TMPDIR = "$PWD\.tmp-pytest\wwt-native"
$env:MPLCONFIGDIR = "$PWD\.tmp-pytest\wwt-native\mpl"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_wwt_document.py `
  tests/test_wwt_format.py `
  tests/test_wwt_display.py `
  tests/ui/test_time_curve_bindings.py `
  tests/ui/test_wwt_view_import.py `
  tests/ui/test_wwt_native_render.py `
  tests/ui/test_wwt_import_flow.py `
  tests/ui/test_ultraview_native_layout.py `
  tests/ui/test_project_session.py `
  tests/ui/test_ultraview_project_session.py `
  tests/ui/test_pg_timedomain_canvas.py `
  tests/ui/test_pg_canvas_backref_invariants.py `
  tests/ui/test_import_boundaries.py `
  tests/ui/test_main_window_state_ownership.py `
  tests/ui/test_no_lambda_signal_connections.py `
  tests/ui_kit/test_qss_border_shorthand.py `
  tests/test_signal_no_gui_import.py `
  tests/test_native_import_boundaries.py `
  tests/test_packaging_imports.py `
  tests/ui/test_hints.py `
  tests/ui/test_quickref.py -q
```

Expected: PASS with live counts; crash, timeout or interruption is `UNVERIFIED`.

- [ ] **Step 6: Generate and automatically verify deterministic artifacts**

```powershell
$out = ".state\wwt-native-import-2026-08-28"
.\.venv\Scripts\python.exe scripts\probe_wwt_native_import.py testdoc\WWT\SFNS_10_P779_0007.wwt --output-dir "$out\sfns"
.\.venv\Scripts\python.exe scripts\probe_wwt_native_import.py testdoc\WWT\YP_SS_P779_0007.wwt --output-dir "$out\yp"
.\.venv\Scripts\python.exe scripts\probe_wwt_native_import.py testdoc\WWT\UCAN-b6_P779_0007.wwt --output-dir "$out\ucan"
.\.venv\Scripts\python.exe -m pytest tests/test_probe_wwt_native_import.py -q
```

Artifacts stay under `.state` and are not added to Git.

- [ ] **Step 7: Run one stable full-suite gate in two sequential processes**

First record stability and ensure no other pytest is running in this checkout:

```powershell
git rev-parse HEAD
git status --short
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pytest' } | Select-Object ProcessId, CommandLine
```

If clear, run sequentially:

```powershell
.\.venv\Scripts\python.exe -m pytest --ignore=tests/acquisition_ui -q
.\.venv\Scripts\python.exe -m pytest tests/acquisition_ui -q
```

Then record `git rev-parse HEAD` and `git status --short` again. If relevant files changed during either process, label the full result `UNVERIFIED` and do not rerun until the next stable integration milestone.

- [ ] **Step 8: Run final static/document checks and lesson status**

```powershell
git diff --check
rg -n "T[B]D|T[O]DO|im[p]lement later|fi[l]l in details" docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md docs/analyzer/plans/2026-08-28-wwt-winwert-layout-import-implementation.md
rg -n "eval\(|exec\(|min\(len\(x\), len\(y\)\)" mf4_analyzer/io/wwt_formula.py mf4_analyzer/ui/time_curve_bindings.py
.\.venv\Scripts\python.exe scripts\lessons\check.py --status
```

Expected: no placeholder/unsafe implementation hits; lesson gate not required unless implementation uncovered a new durable failure pattern.

- [ ] **Step 9: Perform foreground acceptance and record unavailable gates honestly**

Open the three real WWT files in the normal TraceLab app and verify the running widget path, dialog copy, View count, SFNS/YP curves and UCAN 6-card layout + unplaced seventh card. Record Windows frozen/macOS Cocoa checks as `UNVERIFIED` when those environments were not actually run.

- [ ] **Step 10: Commit copy, probe and verification record**

```powershell
git add mf4_analyzer/ui/hints.py mf4_analyzer/ui/quickref.py tests/ui/test_hints.py tests/ui/test_quickref.py scripts/probe_wwt_native_import.py tests/test_probe_wwt_native_import.py docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md docs/analyzer/plans/2026-08-28-wwt-winwert-layout-import-implementation.md
git commit -m "docs(wwt): publish native layout import guidance"
```

---

## Self-Review Checklist

- [ ] Every spec requirement maps to Tasks 1–8; no runtime behavior is left only in prose.
- [ ] Exact identifiers are consistent: `WwtDocument`, `WwtLoadResult`, `TimeDataRef`, `TimeCurveBinding`, `WwtViewProposal`, `WwtImportCoordinator`, `NativeLayoutRect`, `NativeLayoutPlan`.
- [ ] UCAN literal evidence appears in parser, formula, proposal and UltraView tests: 21 / 4 / 7 / 6+1.
- [ ] YP distinct X refs (`Tol_x` vs `Lenkwinkel`) are asserted; SFNS axes/ticks are asserted.
- [ ] No task introduces a fake time axis for records 17–20.
- [ ] No task puts WWT implementation in `window.py`, `batch_render.py`, `ui/canvases.py` or another compatibility facade.
- [ ] View/project/close cleanup covers both binding ends and missing owners.
- [ ] Native ticks do not regress the existing `setTickSpacing`/minor-label protection.
- [ ] UltraView batch mutation produces one history/refresh and does not expand mutation-funnel exceptions.
- [ ] QSettings and QMimeData lifetime lessons are explicit in the relevant test/probe tasks.
- [ ] Focused tests precede the one stable full gate; acquisition UI is sequential and separate.

## Execution Handoff

Plan implementation should start in an isolated Codex worktree created with `superpowers:using-git-worktrees`, while preserving the current checkout's user-owned dirty changes. Use `superpowers:subagent-driven-development` for task-by-task execution with review between tasks, or `superpowers:executing-plans` for inline checkpointed execution.
