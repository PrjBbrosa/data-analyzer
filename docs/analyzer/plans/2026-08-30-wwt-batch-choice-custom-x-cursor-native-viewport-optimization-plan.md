# WWT 批次选择、Custom X 游标分支统计与原生视口优化计划

- 日期：2026-08-30
- 状态：**PLANNED / 待实施**
- 文档范围：只冻结产品语义、owner、红测、实施顺序与验收；本轮不修改产品代码或测试
- 当前基线：`main@db92d41cace2b4b97fa6a6c8ba7234c085d1722a`，`main...origin/main [ahead 1]`
- 当前 checkout：非干净；原生 range/tick、UltraView Smart Layout 等有并行未提交工作，见 §2.4
- 历史依据（不改写）：
  - [`2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md`](2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md)
  - [`2026-08-03-batch-custom-x-major-path-recognition-implementation.md`](2026-08-03-batch-custom-x-major-path-recognition-implementation.md)
  - [`2026-08-30-wwt-native-axis-range-and-tick-lifecycle-optimization-plan.md`](2026-08-30-wwt-native-axis-range-and-tick-lifecycle-optimization-plan.md)

> 目标是一次解决三个相邻但不同 owner 的问题：同批多 WWT 只询问一次并可把选择应用到本次剩余文件；TimeDomain Custom X 的双游标统计能按物理升程/回程分别计算；WinWert 自动生成的 View 使用文件内原生 X 视口（例如数据约 `-83..83 mm`，图面保持 `-100..100 mm`）。三项功能共享 WWT/TimeDomain 场景，但不得通过一个 MainWindow 散状态或一套模糊启发式耦合在一起。

## 1. 用户结果与明确决策

### 1.1 同批多 WWT：一次选择可应用于本次剩余文件

当一次“打开”或一次拖放包含多个 WWT，首个具有有效 WinWert display/proposal 的 WWT 仍显示现有二选一对话框：

- `按 WinWert 排版并绘图`
- `仅加载数据`

对话框增加一个默认不勾选的复选项：

```text
☐ 对本次剩余 WWT 使用此选择
```

冻结语义：

1. 未勾选：维持当前逐 WWT 询问。
2. 勾选后选择“排版并绘图”：本次打开批次内后续所有**可询问** WWT 自动执行排版、建 View 与投影，不再弹框。
3. 勾选后选择“仅加载数据”：本次打开批次内后续 WWT 只加载 source/record，不建 WinWert View，不再弹框。
4. 作用域仅为当前 `_open_data_paths()` 调用；成功、部分失败、异常、中途 return 后都必须在 `finally` 清空。下一次单独打开必须重新询问。
5. 不写 `QSettings`、project payload、preset 或进程级全局变量。
6. 混合批次中非 WWT 不受影响；没有 display/proposal 的 WWT 不建立、也不消耗“本次后续”决定。
7. 项目恢复继续不弹框；恢复不是一个新的用户打开批次。

推荐内部模型是三态/四态枚举而非多个 bool：

```text
ASK
APPLY_LAYOUT
LOAD_DATA_ONLY
NOT_APPLICABLE
```

对话框返回“本文件选择 + 是否记住本次批次”，批次上下文负责后续复用；`WwtImportOutcome.accepted` 继续表达实际结果，不兼任 UI 决策状态。

### 1.2 Custom X 双游标：每条曲线分别计算升程/回程

当 TimeDomain 横坐标为指定通道（例如 `Rack Travel (mm)`），A/B 游标定义的是 X 区间，不再假装是时间区间：

- 表头显示 `A=-60.0 mm`、`B=-45.0 mm`、`ΔX=15.0 mm`；
- 不显示 `ΔT` 与 `1/ΔT Hz`；
- 每条可见曲线独立按完整采集顺序识别 major legs，再裁剪到 A/B 区间；
- 有唯一一对相反方向路径时，以 `X↑` / `X↓` 两行显示各自 `Min / Max / Avg`；
- 标签按 X 方向，不写死“上方/下方”。滞回曲线可能交叉，几何上方不总等于升程；UI tooltip 可补充“升程/回程”。

第一阶段明确**不**做以下隐含行为：

- 不把 4 个 WWT 文件的 Y 自动平均成一条“总体上支/下支”曲线；
- 不因同名 `Rack Force` 合并复合 source/channel identity；
- 不按 Y 正负、绘制像素或抽稀 envelope 判断分支；
- 不在 Custom X 上继续使用把非单调 X 排序后的单值 `np.interp` 计算旧 `Δ`。

若后续确实需要“4 个文件 → 2 条代表性平均曲线”，另立第二阶段规格，先冻结共同 X 网格、插值方法、覆盖率、缺失区间、离群值、权重与单位兼容；本计划不偷偷代做。

#### Custom X 行合同

| 情况 | 游标统计呈现 |
| --- | --- |
| 唯一 `X↑ + X↓` | 通道标题 + 两个紧凑分支子行；每行 `Min / Max / Avg` |
| 单一有效路径或极短序列 | 一行 `全程`，明确未识别出一对升回程 |
| 区间无实际样本 | 不伪造 0/NaN；显示“区间内无数据”或省略该通道并给出状态 |
| 两次同向有效访问 | 该通道显示可操作诊断，不伪造 `X↑/X↓` |
| 3 条及以上有效路径 | 显示“无法可靠区分升程/回程”，建议缩小区间或拆分记录 |
| NaN/Inf 间断 | 作为 acquisition segment 硬边界，禁止跨段拼接 |

Custom X 第一阶段不显示旧 `△Y(B-A)`：同一个 X 在两条路径上有两个 Y，单值差没有唯一物理含义。只有后续定义并测试“同一分支端点差”后才允许增加 `ΔY↑/ΔY↓`。时间 X 保持现有 A/B/ΔT/1/ΔT 与单行 Min/Max/Avg/△ 合同。

### 1.3 WinWert 原生 X 视口：保留文件定义的呼吸空间

以用户截图对应 SFNS 文件为准：

```text
WWT native X range: -100..100 mm
实际 Rack Travel 数据: 约 -83..83 mm
首次 WinWert View 图面: -100..100 mm
```

这不是通用视觉 padding，而是 WWT 文件自身的显示意图。冻结语义：

1. 有效 native X range 首次绘制时原样恢复，不被 `_preserved_xlim_fits_data()` 因存在留白而降级到数据并集。
2. 普通 View 的 stale-range 防护保持当前语义；不能全局允许任意超出数据范围的 saved xlim。
3. 不用“数据范围 ±10%”重新计算 `-100..100`；必须使用文件提供的精确范围。
4. 用户 pan/zoom 后，当前用户 viewport 成为保存值；切 View、split、项目保存/重开均恢复该用户值，不被原生初始范围反复覆盖。
5. WWT View 的工具栏 Home / 右键“查看全部”回到 native X range；普通 View 的 Home 仍回到已绘制数据并集。
6. 原生 major/grid cadence 始终投影到最终 effective range；range、AxisItem 与 ticks 必须在完整 settle 后一致。
7. A/B 统计只读取真实样本；`-100..-83`、`83..100` 的空白不会参与平均值。

无效 native range 的降级合同：

- 非有限、反向、退化范围：回到数据并集并产生可观察的 WWT issue/warning；
- native range 与实际绑定数据完全无交集：回到数据并集并报告；
- native range 包含或部分覆盖实际数据且结构有效：按可信 WWT viewport 处理，不因存在空白而拒绝；部分覆盖是否允许必须由 synthetic fixture 明确冻结，默认要求至少与数据有非退化交集。

## 2. 已核实基线与根因

### 2.1 WWT 批次选择

- `_open_data_paths()` 在 `mf4_analyzer/ui/main_window/_project_io_mixin.py` 中顺序调用 `_load_one()`；它已经天然定义“一次用户打开批次”的生命周期。
- `WwtImportCoordinator._ask_layout()` 当前只返回 bool，`offer_layout()` 每个文件独立调用，没有 batch decision。
- `仅加载数据` 当前仍完成 source/record 加载；本计划不得把 reject 误改为跳过文件。

### 2.2 Custom X 游标统计

- `mf4_analyzer/ui/pg_canvas/cursor.py::_emit_dual_cursor_html()` 当前无条件显示秒/Hz，并用 `(x>=A)&(x<=B)` 将两条物理路径混成一个 `seg` 后求一次 Min/Max/Mean。
- `mf4_analyzer/ui/plot_helpers.py::_interp_cursor_value()` 遇非单调 X 会排序后 `np.interp`；重复 X 的两条路径被压成不透明的单值语义。
- `mf4_analyzer/batch_statistics.py` 已有并已验证：finite acquisition segments → 自适应 turn policy → raw legs → short-leg merge → range clip → major contribution → `X↑/X↓`。
- Batch 的 pane-level `multiple_hysteresis_overlay` 是 Batch 卡片策略，不应直接套到 TimeDomain 游标。截图中的 4 条可见曲线应各自独立得到两行，而不是整张 pane 被 block。

### 2.3 原生 X viewport

- `build_wwt_view_proposals()` 已把 WWT x row 的 `lo/hi` 写进 `ViewState.xlim`；用户样本实际为 native `-100..100`、数据约 `-83..83`。
- `_render_view_onto_canvas()` 最终通过 `_restore_view_xlim()` 恢复。
- `_restore_view_xlim()` 调用 `_preserved_xlim_fits_data()`；后者要求保存范围基本落在数据并集内，因此合法 native margin 被判为“不属于当前数据”，再调用 `frame_x_to_data()`。
- 当前原生 tick/range 生命周期已在未提交代码中调整。新 viewport intent 必须接入同一个 `plot → restore X/Y → density/native ticks → settle/resize` 事务，而不是绕开它另设一次 post-fix setRange。

### 2.4 当前并行占用与重基线门

截至本计划编写时，以下相关文件已有未提交改动：

- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/native_axes.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/pg_canvas/tick_density.py`
- `mf4_analyzer/ui/view_bridge.py`
- `tests/ui/test_wwt_native_render.py`
- `tests/ui/test_view_bridge.py`

因此 Task 4 在这些改动稳定、提交或明确交接前不得开始。实施者必须重新读取当前文件与既有 `2026-08-30` native plan 的 execution record；不能按本计划写作时的行号套补丁，也不能回退/覆盖现有 dirty。

## 3. 架构与 owner 分工

| 责任 owner | 主要文件 | 明确边界 |
| --- | --- | --- |
| WWT open-batch coordinator | `_project_io_mixin.py`、`wwt_import_coordinator.py` | 只拥有本次打开调用的选择上下文；不持久化 |
| Custom X numeric core | 新建 UI-neutral 模块（建议 `mf4_analyzer/signal/custom_x_paths.py`）与 `batch_statistics.py` | 纯 numpy/数据类；不得 import UI/Qt/Batch runner |
| Cursor projection/UI | `ui/pg_canvas/cursor.py`、`ui/plot_helpers.py`、`ui/chart_stack/cursor_pill.py`、`ui/chart_stack/stack.py` | 消费 numeric DTO；不复制路径算法 |
| X-axis context | `ui/view_state.py` 或小型中性 DTO + MainWindow→canvas 显式接线 | 用复合身份/模式/单位；不从 label 猜 Custom X |
| WWT viewport lifecycle | `wwt_view_import.py`、`_view_mixin.py`、`view_bridge.py`、`pg_canvas` 现有 range owner | 显式 provenance；普通 View stale guard 不变 |
| Docs/acceptance coordinator | `ui/hints.py`、`ui/quickref.py`、用户指南、owner/boundary tests | 只在产品语义稳定后收口；唯一 full-gate owner |

两个建议 DTO：

```text
CursorXAxisContext(mode=time|channel, identity, label, unit)
XViewportIntent(source=wwt_native|user|ordinary, initial_range, home_range)
```

名字可随现有风格调整，但字段语义必须显式、可初始化、可对称 reset。显示名只能用于 UI；Custom X 模式、channel identity 与 viewport provenance 不能由 `Rack Travel` 文案推断。

## 4. 实施波次

依赖关系：

```text
T0 红测/合同冻结
├─ T1 中性 Custom X 主路径核心 → T2 Cursor/UI
├─ T3 WWT 本次批次选择
└─ [等待 native dirty 稳定] → T4 WWT viewport intent
T1..T4 → T5 persistence/docs/integration → T6 verification
```

T1 与 T3 文件 owner 可独立；T2 与 T4 都可能接触 canvas/MainWindow 接线，默认串行。若实施期间仍有其他任务修改 owner 文件，协调者暂停对应波次，不做手工合并猜测。

### Task 0 — 记录 snapshot，先写失败合同

**Owner：** 测试与 fixture；不改产品代码。

1. 记录 `HEAD`、`git status --short`、上述重叠文件 diff fingerprint、当前 pytest 进程。
2. 扩展 `tests/_helpers/wwt_factory.py`：
   - 3 个有 display 的 WWT + 1 个无 display 的 WWT；
   - Custom X `-83→83→-83`，native viewport `-100..100`，Rack Force 有确定性滞回；
   - noisy/chatter、单向、双循环、同向重复、NaN/Inf segment 变体；
   - 两个不同 source 同名 channel，冻结复合 identity 不合并。
3. customer `testdoc/2024_3_17/SFNS_*` 只作存在即运行的 optional smoke；缺失必须 skip，不得 `pytest.fail`。
4. 分别提交/记录三组 RED actual；任何用例若在当前实现已绿，确认它是否真正走生产 seam，不能为了“红”放宽或篡改合同。

**Task 0 必须先红的核心用例：**

- batch choice：勾选后第二、第三个 WWT 不再询问；新批次必须再次询问；当前实现会逐个询问；
- Custom X：A/B header 仍显示秒/Hz、两路径混成一行；
- viewport：proposal 为 `-100..100`，完整 restore 后却是数据并集；
- full restore：settle 后 `ViewState/effective xlim == handle xlim == AxisItem.range` 且 native cadence 覆盖同一范围。

### Task 1 — 提取可复用的 Custom X per-series 核心

**Owner files：**

- Add：`mf4_analyzer/signal/custom_x_paths.py`（最终名称由 neutral package 风格决定）
- Modify：`mf4_analyzer/batch_statistics.py`
- Tests：`tests/test_batch_statistics.py` + 新 core 单测（如拆文件）

**实现：**

1. 从 `batch_statistics.py` 提取 UI-neutral pure helpers/DTO，保留已校准算法：
   - `_acquisition_segments`
   - `_turn_policy`（只看完整 segment 的 data span，不接收 A/B range）
   - `_raw_legs`
   - `_merge_short_legs`
   - clip 与 major contribution 过滤
2. 暴露窄 public seam，例如：

   ```text
   analyze_custom_x_paths(x, y, x_range=None) -> SeriesPathResult
   ```

   结果包含 accepted contributions、direction、raw sample indices/arrays、diagnostic reason；不包含 Qt、颜色、HTML、pane policy。
3. Batch 改为消费该 seam；Batch 公共 DTO、manifest code、renderer 合同保持不变。
4. 加 parity tests：现有 Batch fixtures 在提取前后 rows、N、Min/Max/Mean、argmin/argmax、diagnostics 完全一致。
5. 增加 import-boundary subprocess test，证明中性模块不导入 `mf4_analyzer.ui`、Qt 或 Batch renderer。

**停止规则：** 为避免移动代码而复制第二份算法、把 A/B range 传进 turn policy、或用 Y/像素判断方向时立即停止。

### Task 2 — 显式 X context、Cursor DTO 与紧凑分支 UI

**Owner files：**

- `mf4_analyzer/ui/pg_canvas/cursor.py`
- `mf4_analyzer/ui/plot_helpers.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`（仅初始化/委托/context reset）
- `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- `mf4_analyzer/ui/chart_stack/stack.py`
- 必要的 MainWindow→canvas X context 接线

**步骤：**

1. `plot_channels()` 或显式 setter 接收 `CursorXAxisContext`；Time/Custom X 均由 owner 明确传入。
2. canvas/cursor owner 初始化 context；empty plot、View switch、split canvas rebuild、teardown 对称清理，更新 `_CanvasBackref` owned/delegate 声明。
3. 时间模式保持现有 `_interp_cursor_value()` 与 7-field row 视觉语义。
4. Custom X 模式调用 Task 1 的 pure core，对每个 composite channel 独立规划分支；不对非单调 X 做排序单值插值。
5. 用 dataclass/DTO 替代继续扩展不透明 7 元 tuple，至少表达：channel identity、display label、color、Y unit、X unit、mode、branch、Min/Max/Avg、status。信号仍可传 object，consumer 不再靠 tuple position 猜模式。
6. CursorPill 正常宽度：每通道一块，下面两条 `X↑/X↓` 子行；mini/窄宽度优先保留方向 + Avg，Min/Max 放 tooltip 或展开态，避免 4 文件 × 2 分支把浮层完全遮住图。
7. extreme marker 若继续显示，必须分别来源于各 accepted contribution 的 raw index；不能从合并 seg 找一个全局 Min/Max。若密度过高，第一版可只保留当前通道/hover 分支 marker，但需在测试与文案中明确。

**红/绿测试：**

- `tests/ui/test_pg_timedomain_canvas.py`
  - time X header/rows 完全不变；
  - Custom X 单位为 mm，无秒/Hz；
  - noisy single cycle 恰好两分支，N 与 pure core 一致；
  - 4 条同名不同 source 曲线各自两分支，不坍缩 identity；
  - 单向、空区间、双循环、同向访问、nonfinite gap 诊断；
  - hidden original/filtered 既有可见性合同不回归。
- `tests/ui/test_cursor_pill_formatting.py`：normal/mini/tooltip/单位/长名称。
- `tests/ui/test_chart_stack.py`：primary/secondary canvas 信号路由、View switch 清 stale rows。

### Task 3 — 增加 WWT 本次打开批次选择上下文

**Owner files：**

- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `tests/ui/test_wwt_import_flow.py`
- 必要时独立的 coordinator unit test

**推荐实现：**

1. `_open_data_paths()` 在去重/重载确认完成、实际 load loop 开始前调用 `begin_open_batch()`，在最外层 `finally` 调用 `end_open_batch()`。
2. `WwtImportCoordinator` 持有一个明确初始化的 batch context，或 `_open_data_paths()` 以显式 context 参数传给 load seam；不在多个 MainWindow mixin 写同一状态。
3. `_ask_layout()` 返回 typed decision；只有用户勾选复选框才写入当前 context。
4. 后续 `offer_layout()` 先判断项目恢复、是否有 fids/proposals，再读取 context；`NOT_APPLICABLE` 不改变已记决定。
5. 任何 load failure 仍由现有错误 taxonomy 报告；一个坏 WWT 不清除本次对后续 WWT 的决定，但批次结束必须清除。

**测试矩阵：**

| 场景 | 期望 |
| --- | --- |
| 3 WWT，首个勾选排版 | 1 次对话框，3 个文件均按各自 proposal 建 View/投影 |
| 3 WWT，首个勾选只加载 | 1 次对话框，3 个文件均有 data/record，0 个 WinWert View |
| 首个不勾选、第二个勾选 | 前两次询问，第三个复用第二次选择 |
| WWT + CSV + WWT | CSV 正常加载；决定只影响两个 WWT |
| 无 display WWT + 2 个有效 WWT | 无 display 不建立决定；首个有效 WWT 才询问 |
| 中间 WWT 失败 | 错误可见，后续有效 WWT继续按本批决定 |
| 新一次 open/drop | 决定已清空，重新询问 |
| project restore | 零对话框，按持久状态恢复 |

### Task 4 — 引入可信 WWT viewport intent，并接入 Home/restore

**前置硬门：** §2.4 重叠文件已经稳定，实施者重新取 baseline；现有 native range/tick focused tests 先绿。若仍在变化，暂停本任务。

**Owner files：**

- `mf4_analyzer/ui/wwt_view_import.py`
- `mf4_analyzer/ui/view_state.py` 或独立 viewport DTO owner
- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/view_bridge.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py` 与 toolbar Home 的最小 owner 接线
- `tests/ui/test_wwt_view_import.py`
- `tests/ui/test_wwt_native_render.py`
- `tests/ui/test_view_bridge.py`
- `tests/ui/test_pg_timedomain_canvas.py`

**步骤：**

1. WWT proposal 在已有 `xlim` 之外写入可序列化的 `x_viewport_intent`：source=`wwt_native`、initial/home range、必要的 source/window provenance。它是 viewport 事实，不复用 `native_ticks.x` 充当身份。
2. `_restore_view_xlim(canvas, state.xlim, intent=...)`：
   - ordinary/user viewport 继续走 stale-range predicate；
   - trusted WWT native initial/home range 只要求结构有效且与实际 data union 有非退化交集，允许 margin；
   - 无效 intent 清晰降级并记录 issue。
3. canvas 接收 active home X intent；`reset_view_to_data_extents()` 对 WWT 使用 native home range，对普通 View 使用 data union。View switch/empty/rebuild 对称清理，不能让下一个普通 View继承 `-100..100`。
4. 用户 gesture 完成后由既有 View capture 保存当前 xlim；不要把 intent source 永久改成 user 后丢失 native Home target。建议区分 `current xlim` 与 `home range`，而不是一个字段互相覆盖。
5. project persistence/save-reopen、split secondary、UltraView capture/preview 必须携带 viewport intent；旧项目无该字段时按 ordinary/data-union 兼容，不发明原生范围。
6. 完整 restore 最终只 settle 一次；不得在 settle 后再偷偷 setRange 修正。

**核心 synthetic tests：**

- data `-83..83` + WWT native `-100..100`：proposal、initial render、AxisItem、handle、ViewState 最终一致为 `-100..100`；
- native cadence 在 `-100..100` 上完整投影；
- 手动 zoom 到 `-20..20`，切 View/保存重开仍为 `-20..20`；Home 回 `-100..100`；
- 普通 View Home 回自己的 data union；WWT→ordinary 不遗留 intent；
- split 两 pane 各有独立 home range；
- invalid/nonfinite/inverted/no-overlap native range 降级并有可观察 warning；
- 双游标放在留白区时不产生假样本；跨 `-90..-70` 只统计 `-83..-70` 的实际贡献。

### Task 5 — 集成、持久化与用户说明

1. 检查 `.tlproj` round-trip：batch choice 不入项目；Cursor X context 从 View/plot identity 重建；viewport intent 持久化且旧项目兼容。
2. 检查 split / 24 TimeDomain Views / View reorder / close file / record-only binding；不得用 shortened display label 作 key。
3. 更新 `mf4_analyzer/ui/hints.py` 与 `mf4_analyzer/ui/quickref.py`：
   - WWT 对话框“对本次剩余”范围；
   - Custom X A/B 的 `X↑/X↓` 与错误情形；
   - WWT Home 回原生图面范围。
4. 更新 analyzer 用户指南对应 WWT/双游标章节；不改写历史计划/规格状态伪装为已实现。
5. 若对话框高度在 macOS/Windows 受复选框影响，验证 button text fit 和窄窗口布局，不用固定像素截断文案。

### Task 6 — 协调者集成验证

按 owner 先聚焦、后边界、最后前台。所有实现合并稳定前不跑 full suite。

**Focused：**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_statistics.py \
  tests/ui/test_wwt_view_import.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_wwt_native_render.py \
  tests/ui/test_view_bridge.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_cursor_pill_formatting.py \
  tests/ui/test_chart_stack.py
```

若文件太大，开发中可先跑精确 node id；每个 Task 完成前补齐其 owner 集合。不要把当前历史 pass 数硬编码成验收。

**Boundary：**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py
```

Batch orchestration若未改变，无需扩大到 runner 全套；Task 1 必须跑 Batch statistics/runner 中已有 parity consumer tests。最终执行：

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

**Full gate：** 仅协调者在稳定 snapshot 至多运行一次；先检查同 checkout 无 pytest，记录前后 HEAD/dirty fingerprint。按仓库规则将主套与 `tests/acquisition_ui` 两个新鲜进程串行运行。运行期间相关文件变化、异常退出、超时或崩溃均记 `UNVERIFIED`。

## 5. 真实 Cocoa 前台验收脚本

使用截图中的四个本地样本（存在时）：

- `SFNS_5_X04-CSER_000009.wwt`
- `SFNS_10_X04-CSER_000009.wwt`
- `SFNS_20_X04-CSER_000009.wwt`
- `SFNS_40_X04-CSER_000009.wwt`

### A. 本次批次选择

1. 一次选择 4 个 WWT。
2. 首个对话框勾选“对本次剩余 WWT 使用此选择”，选“排版并绘图”。
3. 确认只出现一次询问，4 文件全部加载，各自 WinWert View/投影计数准确。
4. 关闭并重新一次打开，改选“仅加载数据”；确认仍只问一次、数据树可见、无新 WinWert View。
5. 第三次单独打开一个 WWT，必须再次询问，证明未跨批次记忆。

### B. 原生 X 图面

1. 打开自动生成的 `Rack Travel` View，不点 Fit/Home。
2. X 图面必须为 `-100..100 mm`，实际曲线约占 `-83..83 mm`，左右具有与 WinWert 一致的呼吸空间。
3. 切 4 个 View、开 split、resize、保存项目并重开；范围不漂移，tick cadence 与 final range 一致。
4. 手动 zoom 后切回仍保留 zoom；点击 Home 回 `-100..100`。

### C. Custom X 双游标

1. 每个文件选择 `Rack Travel` 作 X、`Rack Force` 作 Y，并叠加显示。
2. A/B 放在例如 `[-60,-45] mm` 与 `[-20,20] mm` 两档。
3. header 显示 mm 与 ΔX，无 s/Hz。
4. 每条可见曲线各显示一对 `X↑/X↓`；Avg 与 Batch 对同文件/同区间的结果在浮点显示精度内一致。
5. 隐藏一条曲线后对应 block/marker 立即消失；切普通时间 X 后恢复原时间游标合同。
6. 在 `-100..-90` 的纯空白区放 A/B，不得显示虚假平均值。

前台截图、数值 probe、offscreen pytest 与 optional customer smoke 分开记录；任何一类不能代替另一类。Windows frozen executable 未实际验证时明确记 `UNVERIFIED`。

## 6. 停止规则

出现任一项立即暂停对应任务并回报：

1. 需要把 batch choice 写入 QSettings/project，或依赖静默 `getattr(..., False)` 才能工作。
2. 需要新增/扩大跨多个 MainWindow 文件的 mutable state，或扩大 state-ownership whitelist。
3. Cursor 与 Batch 各保留一份 Custom X major-leg 算法。
4. turn policy 依赖 A/B selection span，或 range-first 后再识别方向。
5. 用 Y 正负、几何上/下、曲线颜色、像素或 decimated envelope 判升回程。
6. Custom X 继续用排序后的单值插值给出一个看似确定的 `△`。
7. 未定义共同 X 网格就自动做跨文件总体平均。
8. 通过全局允许 saved xlim 超出 data union 修复 WWT，导致普通 View stale range 防护退化。
9. 用固定百分比 padding 代替 WWT 原生 `-100..100`。
10. viewport 修复在 settle 后第二次 setRange，或 final ViewState/handle/AxisItem/tick range 不一致。
11. 核心测试必须依赖 gitignored customer WWT 才能通过。
12. §2.4 owner 文件仍有并行变化，或 full suite 已在同 checkout 运行。

## 7. 完成定义

- [ ] 三组 Task 0 合同均先红后绿，失败原因与产品问题一致。
- [ ] 同批选择对两种动作都有效，只限本次 open/drop，异常路径也清理。
- [ ] Batch 与 Cursor 共享一个 UI-neutral Custom X 核心；Batch 结果 parity 不变。
- [ ] 时间游标完全保持既有语义；Custom X 使用物理单位、按每曲线显示 `X↑/X↓`。
- [ ] 单向/空区间/多路径/nonfinite 等不伪造统计，诊断可操作。
- [ ] WWT native `-100..100` 经完整 restore/split/project reopen 保持；普通 View 不受影响。
- [ ] 用户 zoom 可持久化，WWT Home 回 native range，留白不参与统计。
- [ ] 复合 source/channel identity、record-only、24 Views、UltraView capture 不回归。
- [ ] `hints.py`、`quickref.py` 与用户指南同步。
- [ ] focused/boundary/full/前台证据按实际状态记录；未跑项明确 `UNVERIFIED`。
- [ ] `git diff --check` 与 lesson status 通过；提交不带入任何无关 dirty/untracked 文件。

## 8. 建议交付切片

为降低回归面，建议分为四个可独立审查的提交，而不是一个大补丁：

1. `refactor(signal): extract shared custom-x path analysis`（纯核心 + Batch parity）
2. `feat(cursor): show custom-x directional statistics`（context/DTO/UI）
3. `feat(wwt): remember layout choice for current open batch`（批次作用域）
4. `fix(wwt): preserve native x viewport intent`（等待原生 tick/range 工作稳定后）

每个切片只 stage 自己的 owner 文件；第 4 个切片不得顺带吸收当前 checkout 中既有的 native tick/Smart Layout dirty。
