# FRF 实施后独立 Review 与优化计划

日期：2026-08-09

状态：**Review 已完成；优化任务待实施**

Review 对象：`codex/frf-system-identification` @ `61053293`
（`c1bea5fa` feat(frf): add system identification and batch analysis +
`61053293` fix(frf): align analysis canvas and inspector；后者即首轮 review 期间
观察到的在途 UI 精修，已提交）

关联文档：
- Spec：`docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`
- 原实施计划：`docs/analyzer/plans/2026-08-08-system-identification-frf-and-batch-implementation.md`
  （其 Completion Record 为实施者自报；本文所有结论为独立复验）

## 1. Review 总结论

实现质量整体很高，spec 的关键合同（含 2026-08-09 review 修订吸收的三条：
`nperseg < 2` 阻断 + `Σw² > 0`、coordinator per-pane 替换语义、CSV/XLSX 同列契约）
全部落地。独立复验未发现数值错误或身份/方向类缺陷。

发现 **1 个已复现的 UI bug、2 个 spec 呈现缺口、1 个效率取舍、2 个待收尾的发布
gate**，见 §3 任务列表（O0 的红测试已随 `61053293` 一并修复，保留为记录）。

### 1.1 第二个提交 `61053293` 的复核（fix(frf): align analysis canvas and inspector）

该提交即首轮 review 期间观察到的在途精修（13 文件，+707/−108），内容：

- 新增 `ui/pg_canvas/frf_plot_host.py`（`FrfStackedPlotHost`）：FRF 三行图复用共享
  分析画布骨架——`_make_analysis_plot` 框轴、`_ModifierWheelViewBox`、
  `pin_left_axes_to_common_width` 轴宽对齐、上两行保留 1px 底框（修掉 `hideAxis`
  吃掉边框的可见回归）。消除了「第二套 canvas 实现」的分叉风险，方向正确；
- Inspector 重构为三卡片：`frfSignalCard`（输入/输出 + 被辨识系统流向图 + 交换 +
  范围）→ `frfParamsCard`（辨识参数 header + 预设条 + 估计/分段 + validation +
  计算频响/在时域查看按钮）→ `frfDisplayCard`（显示与可信度），加
  `frfContextTitle` 标题，与目标原型对齐；QSS 补齐对应样式与 `segment="frf"`；
- `tests/ui/test_surface_layering.py` 正则同步加入 `segment="frf"`（即 O0 修复，
  本机独立复验 14 passed）。

**O1/O2/O5 在 `61053293` 上逐项重验，全部仍然成立**：log 轴 20–80 Hz 缩放实测仍
`[[], []]` 零刻度；`rg` 确认 warnings/事实区仍零呈现；游标实测输出
`|H|=-0.97579` 仍无单位。O3/O4/O6/O7 不受该提交影响（O4 的 as-built 顺序描述
已按新卡片结构更新）。

## 2. 独立复验证据（非自报）

### 2.1 数值核心（`signal/frf.py`，逐行审读）

- `Pxy = conj(X)·Y` 方向、`H1 = Pxy/Pxx`、`H2 = Pyy/conj(Pxy)`、
  `γ² = |Pxy|²/(Pxx·Pyy)` 全部正确；coherence 用 reference 归一化后再除，
  数值稳定且代数上与定义严格一致。
- density scale `1/(fs·Σw²·segments)`、单边倍增仅 interior（DC 与偶数 NFFT 的
  Nyquist 不乘 2）、periodic 窗 `symmetric(n+1)[:-1]`（n=1 特判 `[1.]`，与 SciPy
  `fftbins=True` 语义一致）——全部符合 spec §6。
- flattop 五项系数与 SciPy 完全一致；kaiser β=14 显式固定。
- review 修订的硬合同已实现：`plan_frf_request` 阻断 `nperseg < 2`；
  `window_energy <= 0` 显式 raise（frf.py:444）。
- 溢出处理 fail-closed：累加溢出 raise、per-bin transfer 溢出标 invalid 并告警。
- unwrap 按连续有限段分别执行，不跨 NaN gap。
- SciPy parity 在本机**真实执行**（scipy 1.18.0，23 条 parity 用例全绿，非 skip）。

### 2.2 编排与身份

- `FrfCoordinator`：per-pane generation 记账，从不调用 section 级
  `cancel/replace`（frf_coordinator.py:104-109 `replace=False`），跨 pane 并发不
  互相取消；stale completion 不写 cache、不渲染——spec §8.4 修订版语义完整落地。
- `FrfAnalysisResultCache`：方向性双端 key、任一 fid 失效清条目、compute params
  canonical JSON blob。
- `batch_frf.resolve_frf_tasks`：no-load、稳定展开序（pair-rule → output →
  source）、去重、common/available policy、unknown inventory → estimated 警告。
- `prepare_frf_task`（batch_compute.py）：单一 mask 同时应用 t/x/y、拒绝
  generated 时间轴、抖动校验、无 min-length 截短、调用唯一 `compute_frf()`。
- 身份有方向（`build_frf_task_output_identity`）；manifest `frf_pair`、
  recipe `SUPPORTED_RECIPE_METHODS`/字段白名单/双 fingerprint 齐备。
- Batch 侧正确传播 `result.warnings` 到 item warnings。

### 2.3 UI 面

- 五模式等宽中文名（toolbar + Batch method buttons）+ tooltip 技术名 ✓；
  hints/quickref 已更新为「五个分析模式」并覆盖 FRF 交互与 custom-X 限制 ✓。
- `PgFrfCanvas` 三联图共享 X、log 模式仅绘制层隐藏 DC、低相干淡化不删点、
  singleton 点兜底、游标贯穿三图 ✓。
- 时域关联：custom-X 阻断文案精确、关联 View 删除/切 custom-X 对称解除、
  pan/zoom 只标 stale 不自动计算 ✓。
- 「在时域查看」：signature 精确复用、不覆盖无关 View、12 上限 toast、
  composite key 不折叠同名 ✓（_frf_mixin.py:810-892）。
- Batch pair editor、三种图片组织（每对一张/按来源叠加/按输入·输出对叠加）、
  预设（稳健 2.0s/50%、低频 8.0s/75%、快速 0.5s/50%）✓。

### 2.4 测试与护栏（本机独立运行）

| 套件 | 结果 |
| --- | --- |
| FRF 专项 8 个文件（含 canvas/coordinator/main_window/batch） | **211 passed** |
| 架构护栏 gates（import boundary/state ownership/backref/reporter 等 8 文件） | **41 passed, 1 skipped** |
| SciPy parity | **23 passed（scipy 1.18.0 真实执行）** |
| 主套件（--ignore=tests/acquisition_ui）@ `61053293` | **5684 passed, 9 skipped, 0 failed**（387.3 s） |
| tests/acquisition_ui（单独进程） | **355 passed**（8.5 s，与基线一致） |
| `test_surface_layering` @ `61053293`（O0 复验） | **14 passed** |

## 3. 优化任务

按“先修 bug、再补 spec 缺口、后做取舍与收尾”排序。每个任务
RED → 最小 GREEN → focused regression。

### Task O0 —（已解决）在途 QSS 改动一度打红 `test_surface_layering`

**记录**：首轮 review 的全量套件采样到未提交中间态——`style.qss` 已加
`segment="frf"` 选择器而 `test_surface_layering` 的四段正则未同步，出现 1 条
提交态不存在的失败。**`61053293` 已把 `segment="frf"` 加入正则并随 QSS 一并提交；
本机独立复验 `tests/ui/test_surface_layering.py` 14 passed。** 无遗留动作；
保留本条作为“失败要先分提交态/在途态再归因”的记录。

### Task O1 — log 频率轴在十进位内部缩放时刻度全部消失（bug，已复现）

**现象**（offscreen 实测复现）：FRF 处于 log 频率模式时，把 X 轴缩放到不跨越任何
十进位整数的区间（如 20–80 Hz），`_sync_frequency_ticks` 的
`range(ceil(lo), floor(hi)+1)` 为空 → `setTicks([[], []])` → 底轴**零刻度零标签**。

**同源缺陷**：`batch_render_qt/_builder.py:1129-1143` 使用完全相同的十进位 pin
逻辑；Batch 数据整体跨度不足一个十进位时（窄带 FRF）同样会输出无刻度的 PNG。

**Files**
- Modify: `mf4_analyzer/render_profile.py`（新增 UI 中立纯函数，建议
  `log_frequency_tick_levels(lo_log, hi_log)`：十进位 ≥2 个时返回十进位主刻度；
  不足时降级为 1-2-5 mantissa 刻度（20/30/50/70 …），保证任意有限区间至少 2 个
  主刻度）
- Modify: `mf4_analyzer/ui/pg_canvas/frf_canvas.py::_sync_frequency_ticks`
- Modify: `mf4_analyzer/batch_render_qt/_builder.py`（1129-1143 分支改调同一纯函数）
- Modify: `tests/ui/test_frf_canvas.py`、`tests/test_batch_render_qt_frf.py`
- 纯函数单测可放 `tests/`（不依赖 Qt）

**RED**
- 纯函数：`(log10(20), log10(80))` 返回非空且含 20/30/50/70 类刻度；
  跨多个十进位时仍只有十进位主刻度（保持现有稀疏风格）；
- canvas：`set_xlim(20, 80)` 后底轴 `_tickLevels` 非空；
- batch renderer：窄带 spec（数据 20–80 Hz + log X）构建后底轴刻度非空。

**注意**：两侧共用同一纯函数正是仓库「批处理/GUI 渲染一致性」护栏的既有范式；
不要在两侧各写一份。`render_profile.py` 是 UI 中立层，`batch_render_qt` 引用它
不违反 `test_batch_render_import_boundary`（实施时以该护栏测试为准）。
`61053293` 的 `FrfStackedPlotHost` 重构不影响本任务落点：`_sync_frequency_ticks`
仍在 `frf_canvas.py` 且十进位逻辑原样保留（已在该提交 HEAD 上用 offscreen Qt
重新复现 `set_xlim(20, 80) → [[], []]`）。

**验证**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_frf_canvas.py tests/test_batch_render_qt_frf.py \
  tests/test_batch_render_import_boundary.py tests/test_batch_qt_render_parity.py
```
另需真机（Cocoa 前台）截一张 20–80 Hz 缩放图存 `.state/frf-render-evidence/`。

### Task O2 — 单次 UI 完全未呈现 FrfResult.warnings + 缺常驻有效事实区（spec 缺口）

**现象**：`rg "\.warnings" _frf_mixin.py contextual_frf.py frf_canvas.py` 零命中。
「只有 2–3 段，统计稳定性较低」「N 个 bin 因零激励无效」等可计算告警在单次分析里
**完全不可见**；有效事实只有一条转瞬即逝的状态栏消息（`频响完成 · N 段 · df X Hz`，
_frf_mixin.py:637-640）。spec §5.3 第 8 项要求 Inspector 常驻显示
实际 Fs / 频率分辨率 / 完整段数 / 有效时间范围 / 时间抖动 / 告警；§13 要求可计算
告警进入「事实区/状态栏」。Batch 侧已正确落 warnings，仅单次 UI 缺失。

**Files**
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_frf.py`
  （`61053293` 后为三卡片结构：`frfSignalCard → frfParamsCard → frfDisplayCard`。
  事实区建议放 `frfDisplayCard` 之后新增第四卡片 `frfFactsCard`，或挂在
  `frfDisplayCard` 尾部，复用 `_make_group_header("有效事实")` 既有头部范式与
  QSS 卡片样式（style.qss 已有 frf 卡片选择器组，追加一项即可）；提供
  `set_effective_facts(facts_text, warnings) / clear_effective_facts()`；
  告警行用警示色，复用 ui_kit 既有样式，勿新造颜色常量）
- Modify: `mf4_analyzer/ui/main_window/_frf_mixin.py`
  （`_on_frf_render_requested` 填充事实区（含 cache hit 路径）；
  `_dirty_frf_pane`/pane 切换/清空时同步清除或标注“已过期”；
  split 双 pane 时跟随 focused pane）
- Modify: `tests/ui/test_inspector.py`、`tests/ui/test_frf_main_window.py`

**RED**
- 2 段计算完成后，低段数告警文本在 Inspector 可见且**持续存在**（非 toast）；
- 事实区含 Fs、df、段数、有效时间范围、max jitter、invalid bins；
- display-only 修改后事实区不变、不清空；
- compute 参数修改 → 事实区标注过期或清空，与 pane stale 状态一致；
- 切换 focused pane 事实区跟随；cache hit 渲染同样填充。

**验证**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_inspector.py tests/ui/test_frf_main_window.py
```

### Task O3 — 同 pane 替换旧任务的条件式取消（效率）

**现象**：coordinator 永远 `replace=False` 且从不取消。同 pane 重复点击「计算频响」
时，被替换的旧任务会**完整跑完再被抑制**：长任务（低频预设 + 大数据）场景下浪费
一整次计算，且新任务在 FIFO 里排队等待，用户看到的“正在计算”时长翻倍。
spec §8.4 明确允许：“仅当 section 内除发起 pane 外没有 pending/在途任务时，才允许
使用 service 级 replace/cancel”。当前实现只取了保守分支。

**Files**
- Modify: `mf4_analyzer/ui/main_window/frf_coordinator.py`
  （`request()` 内：`_begin_pane_request` 丢弃同 pane pending 后，若 `_pending`
  已为空（即无其他 pane 的在途/排队任务），改为 `submit(..., replace=True)`，
  借 service 的 generation 取消机制立刻中止在跑的旧计算；否则维持现状）
- Modify: `tests/ui/test_frf_coordinator.py`
- Modify（如进度 token 断言受影响）: `tests/ui/test_compute_progress_integration.py`

**RED**
- 单 pane 场景：第二次 request 时 fake service 收到 `replace=True`（或
  `cancel('frf')` 一次），旧 job 的完成回调不落 cache、不渲染；
- 跨 pane 场景：pane B request 时 service **未**收到任何 cancel/replace，
  pane A 任务完成后照常 put/render（现有用例保持绿）；
- replace 后进度 token 生命周期正确（无孤儿 token / 无负计数）。

**注意**：`AnalysisJobService.cancel` 会重置该 section 的 total/completed 进度并
worker.cancel()；`compute_frf` 的 `cancel_check` 逐段响应，中止延迟 ≤ 一段。
若实施中发现进度 token 交互复杂度超出收益，允许降级为“只取消排队未启动的旧任务”，
但必须在本文追记取舍理由。

### Task O4 — Inspector 分区顺序与 spec §5.3 的偏差（文档决策）

**现象**：spec §5.3 规定顺序为 预设 → 通道映射 → 分析范围 → 估计器 → 分段 →
显示 → 按钮 → 有效事实；`61053293` 后的 as-built 顺序为 **标题 →
frfSignalCard（通道映射 + 流向图 + 分析范围）→ frfParamsCard（预设条 + 估计与
分段 + validation + 计算频响/在时域查看按钮）→ frfDisplayCard（显示与可信度）**
（与 `.state` 原型一致，而非 spec；且按钮位于显示卡之前，与 spec 第 6/7 项顺序
相反）。交互上“先选通道、再挑预设”更贴近实际流程，真机截图布局无问题。

**建议**：保留实现顺序，修订 spec §5.3 为 as-built（在 §5.3 加一行说明该顺序为
最终定版，替代原列表顺序）；同时把 O2 的事实区补到该描述中。不改代码。
若产品侧坚持 spec 原顺序，则改为 UI 任务并同步截图证据。

**Files**：`docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`

### Task O5 — 游标读数与 dB 模式的单位歧义（polish）

**现象**：`set_cursor_frequency` 输出固定 `|H|={value:.5g}`
（frf_canvas.py:520-524）。dB 模式下该值是 dB 数，读数卡却无单位标注；线性模式下
又是倍率。截图确认读数卡同时展示相位（deg）与相干，唯独幅值缺单位。

**Fix**：按当前 `magnitude_scale` 输出 `|H|=-3.02 dB` 或 `|H|=0.707`（线性时可带
ratio 单位标签，复用 `_ratio_unit_label()`）。

**Files**：`mf4_analyzer/ui/pg_canvas/frf_canvas.py`、`tests/ui/test_frf_canvas.py`

**RED**：dB 模式游标文本含 `dB`；线性模式不含 `dB` 且值为线性倍率。

### Task O6 — 发布 gates 收尾（V2/V3，不可跳过）

实施者 Completion Record 自认：
- macOS foreground **PARTIAL**：未完整执行 保存/重开项目（含 FRF View 恢复重算）、
  长任务取消、关闭窗口线程残留检查；
- Windows Full/Lite frozen：**UNKNOWN/UNVERIFIED**（仅 source-level 测试）。

**要求**
1. macOS foreground 补测清单（真实 TraceLab，前台）：
   - 建 2 个 FRF View（含 split、不同 pair/range）→ 保存 `.tlproj` → 重开 →
     断言 mode/pair/range 恢复且首次渲染经 coordinator 重算；
   - 低频预设 + 大数据长任务 → 取消 → 无 stale 渲染、无 Qt 线程告警；
   - 计算中直接关窗 → 进程干净退出（`AnalysisJobService.shutdown` 路径）；
   - 证据（截图 + observed facts）存 `.state/frf-render-evidence/`，按既有
     automate-visual-acceptance 约定自动比对，不留人工清单。
2. Windows frozen：在 fresh Full/Lite EXE 上执行 app 启动、FRF guide 打开、单次
   FRF、Batch FRF CSV+PNG+manifest、Unicode 命名、取消/关闭。执行前发布状态保持
   `NO-GO/UNKNOWN`；执行后在原实施计划 Completion Record 追记结果。

### Task O7 —（可选）`grab_pixmap` 放大质量

`PgFrfCanvas.grab_pixmap(scale=2)` 用 `QPixmap.scaled` 平滑放大截图，放大产物是
插值模糊图而非真 2x 渲染。先核对其他 canvas 的复制图片约定：若既有实现按
devicePixelRatio 真渲染，则对齐；若同为 scaled 放大，则维持现状并删除本任务。
不值得为此单独引入新渲染路径。

## 4. 独立复验运行记录

（review 当日在本机 darwin / `.venv` 实测；与自报 Completion Record 交叉对照）

```text
—— 首轮（@ c1bea5fa + 在途未提交改动的混合快照）——
FRF 专项（8 文件）：211 passed, 201 warnings, 6.28s
架构护栏 gates（8 文件）：41 passed, 1 skipped, 3.49s
SciPy parity：23 passed（scipy 1.18.0，真实执行非 skip）
主套件：5677 passed, 1 failed, 9 skipped（449.64s）
  唯一失败 = test_surface_layering::test_surface_mode_buttons_use_readable_centered_type
  归因：在途 QSS 改动（segment="frf"）与测试正则不同步（见 O0）
tests/acquisition_ui：355 passed（8.46s，与 CLAUDE.md 基线一致）

—— 第二轮（@ 61053293，干净提交态）——
主套件 --ignore=tests/acquisition_ui：5684 passed, 9 skipped, 0 failed（387.28s）
test_surface_layering：14 passed（O0 已修复并复验）
log 轴缩放 bug 复现：set_xlim(20, 80) → ticks [[], []]（仍存在，O1 维持有效）
游标读数复验：`|H|=-0.97579` 无单位（仍存在，O5 维持有效）
warnings/事实区 rg 复验：零命中（仍缺失，O2 维持有效）
```

## 4.1 实施完成记录（2026-08-09，O1–O5）

O1/O2/O3 由三个串行 agent 在主工作区实施（各自 RED→GREEN，互不触碰对方文件），
O4/O5 分别为文档修订与随 O1 完成；全部改动**未提交**，留在工作区待用户按任务分拆
提交。逐项记录：

**O1（log 轴刻度，已修复）**：新增 `render_profile.log_frequency_tick_levels`
纯函数（十进位 ≥2 → 保持稀疏十进位；否则 1-2-5 → 1..9 mantissa → nice-step →
边界值五级降级，任意有限区间 ≥2 主刻度，非法输入返回 `[]` 由调用方保持原刻度），
`frf_canvas._sync_frequency_ticks` 与 `_builder.py` frf log 轴分支共用之（渲染
一致性范式）。新增 `tests/test_render_profile.py`（20 例，含子进程无 GUI 探针）+
canvas 4 例 + builder 1 例；既有稀疏十进位钉子用例原样绿。真实布局核验：
`generateDrawSpecs` 实测 620/900px 最坏 5-6 标签无重叠。独立复验：
`set_xlim(20, 80)` → 刻度 [20, 50]。

**O2（有效事实区 + warnings，已实现）**：`contextual_frf` 新增第四卡片
`frfFactsCard`（`_make_group_header("有效事实")`；facts 六行 = 实际 Fs/df/完整
段数/有效时间范围/最大相对抖动/无效频点；warnings 复用既有 amber 样式；
`set_effective_facts / clear_effective_facts / mark_effective_facts_stale`，
stale = 降灰 + 「（已过期）」前缀且保留旧值）。mixin 侧：`_on_frf_render_requested`
单点填充（worker 完成与 cache hit 同路径）；`_dirty_frf_pane` 标 stale；focus
跟随挂在既有 `AnalysisSectionPage.focus_changed → _apply_frf_sources` 路径，
数据源取 FRF result cache（不摸 canvas 私有字段、不加 PaneState 派生字段、
状态所有权棘轮零扩大）。QSS 复用既有颜色值，零新常量。新增 11 例 + 调整 2 例；
真实 Cocoa 渲染验收三种状态（fresh/stale/empty）截图确认。已知取舍：warnings
原文为英文（与 Batch 预览对话框既有先例一致，避免翻译映射静默吞掉未来新告警）；
`_on_frf_failed` 保留 stale 事实不清空（用户仍可参考上次数值）。

**O3（条件式取消，已实现，未降级）**：`request()` 的 replace 判据 =
`_pending` 为空 **且** `is_running('frf')`（相对计划原判据加了 `is_running` 腿：
排除冷 section 首次请求发无意义 cancel，并保住既有「默认追加」契约用例；该腿
不收窄任何真实收益场景）。验证链：被取消任务经 `cancel_check` 走 failed 路径 →
service generation 检查拦截迟到信号 → `_take_current_pending` 兜底；进度 token
无孤儿/无负计数（真 service 用例断言 `progress_counts == (1,1)`）。
`test_frf_coordinator.py` +8 例（含真 `AnalysisJobService` + 真线程抢占用例，
单跑 ×5 无 flake）；1 例改名翻转断言（原断言钉的正是被本任务改掉的行为，
抑制类断言逐字保留）。spec §8.4 已追加 as-built 说明。

**O4（spec §5.3 as-built，已完成）**：§5.3 重写为 61053293 后的卡片结构
（标题 → frfSignalCard → frfParamsCard → frfDisplayCard → 有效事实区），
注明定版理由与真机验收。

**O5（游标单位，已修复）**：dB 模式 `|H|=… dB`；线性模式输出线性倍率（独立复验
换算正确：-0.97579 dB ↔ 0.89374）。

**未做**：O6（发布 gates：macOS foreground 补测清单 + Windows frozen）仍开放，
维持 NO-GO；O7（grab_pixmap）未动。

**提交切分建议**（改动全部在工作区，未提交）：
1. O1+O5：render_profile.py、frf_canvas.py、_builder.py、test_render_profile.py、
   test_frf_canvas.py、test_batch_render_qt_frf.py；
2. O2：contextual_frf.py、_frf_mixin.py、style.qss、test_inspector.py、
   test_frf_main_window.py；
3. O3：frf_coordinator.py、test_frf_coordinator.py；
4. 文档（O4 + spec §8.4 as-built + 本文）：两份 spec/plan 修订与本记录。

## 4.2 收尾总验证（2026-08-09，O1–O5 全部落地后）

```text
主套件 --ignore=tests/acquisition_ui：5728 passed, 9 skipped, 0 failed（419.89s）
  （对比 61053293 基线 5684：净增 44 条新测试，零回归）
tests/acquisition_ui（单独进程）：355 passed（8.57s）
架构护栏 gates（8 文件）：41 passed, 1 skipped（3.82s）
git diff --check：干净
工作区：15 个未提交路径（O1–O5 改动 + 两份 spec/plan 文档 + 本文 + 真机验收截图），
  未 commit，待用户按 §4.1 提交切分落库
```

## 5. 实施顺序与 gate

0. O0 已随 `61053293` 落地，无动作；O1/O2/O5 实施前照例 `git status` 确认无新的
   并行在途改动（见 §1.1 教训），避免交叉编辑；
1. O1（bug）→ O2（spec 缺口）为第一批；每个独立提交；
2. O3 单独提交（涉及并发语义，review 必须含跨 pane 用例 diff）；
3. O4 文档决策随第一批一起走；O5 随手；
4. O6 是发布前置 gate，与代码任务并行推进；
5. 完成后跑一次 §4 同款全量两进程套件 + 护栏 gates，追记数字。

回退：O1/O2/O5 均为局部可独立回退；O3 回退即恢复 `replace=False` 常量行为。
