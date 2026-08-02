# 批处理时域图内统计与滞回容错 Implementation Plan

- **状态**：待执行（本文件仅为计划，未修改产品代码）
- **日期**：2026-08-02
- **执行顺序**：等待 `2026-08-02-batch-workflow-preview-and-run-records-implementation.md` 的 preview/core 接口冻结后执行
- **范围**：Batch 时域线图的区间最大值、最小值、样本平均值及图内标注

> 用户决定：自定义 X 出现同一 X 对应两个 Y 时，需要按滞回路径分别统计；若同一图/同一 pane 出现多个滞回曲线叠加，图仍正常生成并保留曲线，但统计区域显示一个 `ERROR` 并说明原因。该错误不得阻塞其他图片、数据导出或整个 Batch run。

---

## 1. Goal

在 Batch 时域设置下方增加“图内统计”，让用户对指定 X 区间计算：

- 最大值（Max）
- 最小值（Min）
- 样本平均值（Mean）

结果写入导出的图：分屏模式每个 pane 独立显示；叠加模式按曲线颜色汇总。自定义 X 的单个清晰滞回环按采集路径拆成升程/回程，不按 Y 的正负号分类。

统计失败必须是**图内局部诊断**，不是全局 preflight error：可解释的 unsupported/ambiguous 形状生成带 `ERROR` 的有效 PNG，同时继续余下 Batch。

## 2. Scope and non-goals

### In scope

- `method == "time"` 的 line plot。
- X 来源为时间或通道。
- 每项独立、按数据源、按信号三种图片分组。
- 叠加和分屏两种布局。
- 原始/滤波后曲线的独立统计。
- 统计配置进入 preset JSON、recipe fingerprint、manifest requested/effective facts。
- 正式 run 和真实单图 preview 使用同一统计/diagnostic renderer。

### Not in scope

- FFT、FFT vs Time、阶次 heatmap 的统计。
- RMS、积分平均、峰峰值、百分位、cycle counting/rainflow。
- 自动把多滞回叠加改成分屏。
- 因统计不可用而跳过 XLSX、阻塞该来源或停止整个 Batch。
- 将统计结果额外写入 XLSX worksheet；本阶段只要求图内结果和 manifest diagnostic。

## 3. Fixed data contract

### 3.1 Recipe field

在 time params 增加一个嵌套字段，避免扩散多个松散 key：

```python
"chart_statistics": {
    "enabled": False,
    "range_mode": "full",       # full | custom
    "x_min": None,
    "x_max": None,
    "metrics": ["max", "min", "mean"],
}
```

规则：

- 旧 preset 缺少该字段时等价于 disabled，输出字节保持旧行为。
- `custom` 要求有限 `x_min < x_max`；该错误可在运行前验证，因为不依赖来源数据。
- `metrics` 去重并采用 canonical 顺序 `max, min, mean`；至少选择一个。
- `chart_statistics` 只属于 time method；切换到其他方法时不泄漏。
- 字段参与 recipe fingerprint，因为会改变 PNG 内容。

### 3.2 UI

在用户截图红框位置新增独立 `ChartStatisticsPanel`，不要继续把 `DynamicParamForm` 堆成一个超大类。

目标布局：

```text
图内统计                                      [启用]

统计区间       [全范围 ▼]
               或 [X 起点] — [X 终点]

统计项目       ☑ 最大值   ☑ 最小值   ☑ 平均值

自定义 X 提示  同一 X 对应多 Y 时，按升程/回程分别统计
```

- 只在 time method 可见。
- `x_source=time` 时单位显示秒；`x_source=channel` 时跟随选中 X 通道单位。
- 默认关闭，避免现有导出图发生无提示视觉变化。
- 分支拆分是固定正确性规则，不提供“把两条路径直接合并平均”的危险开关。

## 4. Numeric semantics

### 4.1 Authority and processing order

统计输入必须是 `BatchSeries` 中最终可绘制的原始数值：

1. 已完成 time range、finite cleanup、scale/offset、remove mean、sampling 和 filter。
2. 对 original/filtered 同时显示的情形，各自使用对应最终 Y。
3. 统计区间使用与图上完全相同的 display X：时间轴 `x_origin=zero` 时按 renderer 规则减去各 series 的起点，absolute time 保持原值，自定义 X 始终保留物理坐标、不做 `0-1` 归一化。
4. display-X 变换提取为 GUI-free shared helper，统计与 Qt renderer 共用；不能各写一份看似相同的减法。
5. 在 Qt display envelope/抽稀之前计算；屏幕优化不得改变统计值。
6. 不排序 X、不对相同 X 做平均、不使用 `min(len(x), len(y))` 裁剪。
7. X/Y 长度不等仍沿用现有 hard validation；统计不能发明物理对应关系。

### 4.2 Interval and metrics

- `range_mode=full`：使用该 series 的全部有限 `(x, y)`。
- `range_mode=custom`：闭区间 `x_min <= x <= x_max`。
- 先按 display X 应用统计区间，再对区间内仍保持采集顺序的样本检测路径；因此缩小区间可以有意隔离一个滞回环。
- Max/Min：对区间内每条统计路径独立计算；保存值及其原始 X 位置，用于极值标记。
- Mean：算术样本平均，图中明确显示 `Mean(sample)` 或中文“样本平均”，不冒充 X 积分平均。
- 每行同时记录有效样本数 `N`。
- 某条路径区间内 `N=0`：显示 `无区间数据 (N=0)`，不升级为 run error。
- 一正一负、两个都正、两个都负三种 Y 组合必须产生相同的路径拆分；分支身份绝不能由 Y 符号决定。

### 4.3 Single-hysteresis branch detection

按采集顺序分析已经通过统计区间筛选的 display X：

1. 对 finite X 计算 `dx`。
2. 使用确定性容差：先取 `scale = max(1.0, max(abs(finite_x)), ptp(finite_x))`，再取 `tol = max(1e-12, 1e-9 * scale)`；`abs(dx) <= tol` 视为平台点。
3. 平台点归属相邻最近的有效方向，不单独形成 branch。
4. 忽略少于 3 个有限点的孤立方向片段；不得让单点噪声制造滞回分支。
5. 无显著反向：单路径统计。
6. 恰好一次显著反向：拆成 `路径 1 · X↑/X↓` 与 `路径 2 · X↓/X↑`，反向拐点可同时属于两条闭区间路径，Max/Min/Mean 的样本计数规则在测试中冻结。
7. 超过一次显著反向：当前版本视为多循环/路径不明确，生成图内局部 diagnostic，不猜测 cycle。

若数值试验表明上述容差对真实数据不稳，实施者不得直接调常数直到截图“看起来对”；必须加入真实调用路径 fixture，再在本计划中记录偏差决定。

## 5. Multiple-hysteresis rule（用户新增硬约束）

### 5.1 Curve family identity

“多个滞回曲线”按物理任务 family 判断，不按可见 PlotDataItem 数量：

- 同一个 source/signal/task 的 original 与 filtered 是一个 family、两个 variant。
- 不同 source 或不同 target signal 是不同 family。
- `BatchSeries` 增加向后兼容的 `family_key`、`series_key`、`variant`（默认空值），spool 必须完整保存/恢复。

### 5.2 Trigger

仅在 `chart_statistics.enabled=True` 时检查。对每个实际 pane 独立判断：

- 同一 pane 中至少两个不同 family 都被识别为滞回（恰好一次显著反向）；或
- 任一 family 自身出现超过一次显著反向、无法确定唯一升程/回程。

触发后该 pane 不输出任何可能误导的统计数字。

分屏模式下，如果每个 pane 只有一个清晰滞回 family，各 pane 仍正常统计；不能因为整张 PNG 包含多个 pane 就报错。

### 5.3 Chart-local error

曲线、坐标轴、标题、图例继续正常渲染。统计卡位置替换为红色诊断卡：

```text
ERROR · 图内统计未生成
当前图叠加了多个滞回曲线，无法可靠对应升程/回程统计。
请改用“分屏”或“每项独立”后重新运行。
```

多循环单 family 使用：

```text
ERROR · 图内统计未生成
当前曲线检测到多次 X 方向反转，无法确定唯一升程/回程。
请缩小统计区间或拆分数据后重新运行。
```

这是视觉上标为 `ERROR` 的 **chart diagnostic**，但 operational behavior 固定为：

- PNG 正常写入并校验，render group status 保持 `done`（若无其他问题）。
- 对应 data artifact 正常生成。
- diagnostic 写入 render group warning/effective facts，code 分别为：
  - `chart_statistics.multiple_hysteresis_overlay`
  - `chart_statistics.multiple_x_reversals`
- 不向 runner 的 `blocked` 列表追加该 diagnostic。
- 不把 task status 改为 failed/blocked/partial。
- 后续 groups/tasks 继续运行。
- UI 完成状态可显示“完成，N 张图含统计提示”，但不能显示“全部失败”。

## 6. Render contract

新增纯数据模型，Qt builder 只负责画：

```python
BatchStatisticRow(
    series_key, family_key, label, variant, panel,
    branch_label, direction, sample_count,
    x_min, x_max, minimum, maximum, mean,
    argmin_x, argmax_x,
)

BatchChartDiagnostic(
    code, severity="error", title, message, suggestion, panel,
)
```

`BatchTimeFigureSpec` 增加默认空 tuple 的 `statistics` 和 `diagnostics`，保证旧调用者与 tests 构造方式继续有效。

### Display rules

- 分屏：每个 pane 右上角独立统计卡；标题内不重复塞统计文本。
- 叠加且无滞回歧义：一张按 series color 排列的表；行过多时使用固定可读上限并显示 `+N 条`，不得把绘图区挤为零。
- Max/Min：可选中指标时在对应曲线上画同色极值 marker；marker 不是新 legend series。
- Mean：只在卡中显示，不默认画水平线。
- diagnostic 卡在统计卡 z-order 之上，但不能遮住整张图；导出分辨率变化时保持边距。
- 统计卡/diagnostic 纳入 builder 的 text-overlap、ink、CJK 和 SSAA 证据。

## 7. Execution tasks

### Task 0 — Baseline and RED fixture set

**Files**

- Create tests first: `tests/test_batch_statistics.py`
- Later create: `mf4_analyzer/batch_statistics.py`

建立小而可审查的 fixtures：

1. monotonic time/X。
2. 单滞回：一正一负。
3. 单滞回：两支都正。
4. 单滞回：两支都负。
5. 平台点 + 一次反向。
6. 单点方向噪声，不得误判多循环。
7. 多次显著反向。
8. 两个不同 family 滞回叠加。
9. custom interval 只覆盖其中一部分/某支 N=0。

先冻结 branch labels、N、Max/Min/Mean、arg positions 和 diagnostic codes，再写实现。

### Task 1 — Recipe normalization and validation

**Files**

- Modify: `mf4_analyzer/batch_recipe.py`
- Modify: `mf4_analyzer/batch_validation.py`
- Modify: `mf4_analyzer/batch_preset_io.py` only if existing generic serializer is insufficient
- Tests: `tests/test_batch_recipe.py`、`tests/test_batch_validation.py`、`tests/test_batch_preset_io.py`

要求：旧 preset byte behavior、unknown future fields、Mapping/duck object validation 继续成立；full/default config canonical 化后 fingerprint 稳定。

### Task 2 — UI control and round-trip

**Files**

- Create: `mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- Modify only for context wiring if necessary: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: new `tests/ui/test_batch_chart_statistics.py` + `tests/ui/test_batch_smoke.py`

要求：

- get/apply/full-recipe reset/partial patch contracts 明确。
- method/x_source/x_channel 变化时，range 单位和 explanatory note 同步。
- 切到非 time 隐藏但不误写其他 method params。
- compact mode 下不横向溢出；使用现有 scroll pane，不固定一个会剪裁底部动作的面板高度。

### Task 3 — Series identity through spool

**Files**

- Modify: `mf4_analyzer/batch_render_qt/_models.py`
- Modify: `mf4_analyzer/batch_series_spool.py`
- Modify: `mf4_analyzer/batch.py` 的 `_build_time_series` connector
- Tests: `tests/test_batch_series_spool.py`、`tests/test_batch_runner.py`、`tests/test_batch_render_qt.py`

要求：`family_key=task_id`；variant 为 `original/filtered/value`；同名 label 仍能保持不同 series identity。spool metadata round-trip 后 identity 不丢失，mmap close/cleanup 行为不变。

### Task 4 — Pure statistics and diagnostic planner

**Files**

- Create: `mf4_analyzer/batch_statistics.py`
- Tests: `tests/test_batch_statistics.py`

实现分两层：

1. per-series branch/statistics，完全无 Qt。
2. per-pane diagnostic planner，按 family 判断 multiple hysteresis。

结果必须只依赖输入 arrays/config，稳定可 JSON 化；不要在 Qt builder 中重新计算一遍。

### Task 5 — Build figure spec and manifest facts

**Files**

- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/batch_render_qt/_models.py`
- Tests: `tests/test_batch_runner.py`、`tests/test_batch_manifest.py`

在 group spool load 后、构建 figure spec 时运行 pure planner；将 rows/diagnostics 附到 `BatchTimeFigureSpec`。manifest 记录 config、diagnostic code/message、统计成功行摘要；不得把 chart diagnostic 送入 `blocked`。

### Task 6 — Qt annotation rendering

**Files**

- Modify: `mf4_analyzer/batch_render_qt/_builder.py`
- Tests: `tests/test_batch_render_qt.py`、`tests/test_batch_render_qt_display_envelope.py`

先 producer-shaped spec tests，再做像素/文本检查：

- single path card
- two-branch hysteresis card
- overlay table
- max/min marker positions
- multi-hysteresis ERROR card
- subplot pane-local decision
- 1080p/144 DPI 与 SSAA 后文本仍清楚

### Task 7 — Runner non-blocking integration

**Files**

- Modify: `mf4_analyzer/batch.py`
- Modify if summary text needed: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: `tests/test_batch_runner.py`、`tests/ui/test_batch_runner_thread.py`、`tests/ui/test_batch_smoke.py`

关键回归：

- 两个滞回 family overlay → PNG 存在、包含 ERROR 文本、data 存在、group/item/run 不 blocked。
- 同一 run 的下一组仍被执行并生成正常统计图。
- manifest warning 有 code，summary 仍从 terminal task entries 推导。
- 正式 preview 与 run 对同一 representative group 产生相同 diagnostic；preview 不写 manifest。
- 真正 renderer/write/checksum exception 仍按现有 failed/partial/cancelled 规则处理，不能被“统计不阻塞”误吞。

### Task 8 — Visual and real-data acceptance

- 生成 monotonic、单滞回三种符号组合、多滞回 overlay、subplot 分开五类 PNG。
- 用 parser/scene text records 断言数值、ERROR 原因和 suggestion 存在。
- 1080×760、1440×900 前台 Batch UI 查看红框新控件。
- 1920×1080 PNG 原始尺寸查看统计卡、marker、ERROR 卡。
- 使用真实自定义 X 往返数据；记录来源、信号、区间与预期 branch 数。
- 前台 TraceLab、真实 PNG、offscreen/pixel proof 分开报告。

## 8. Verification commands

### Pure numeric first

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_batch_statistics.py \
  tests/test_batch_recipe.py \
  tests/test_batch_validation.py \
  tests/test_batch_series_spool.py
```

### Renderer/core

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_render_qt.py \
  tests/test_batch_render_qt_display_envelope.py \
  tests/test_batch_runner.py \
  tests/test_batch_manifest.py
```

### UI

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_batch_chart_statistics.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_runner_thread.py \
  tests/ui/test_batch_method_buttons.py
```

最后执行相关 Batch gate 和 `git diff --check`；记录基线失败集合，不用一个局部绿测覆盖前台/全组边界。

## 9. Acceptance criteria

| ID | 验收 |
| --- | --- |
| S1 | 默认关闭时旧 preset、recipe、PNG 内容和 task behavior 不变 |
| S2 | time/custom-X UI 可配置 full/custom 区间和 Max/Min/样本平均，配置完整 round-trip |
| S3 | 统计使用最终 raw drawable series、在显示抽稀前计算，且不排序/去重/截断 X/Y |
| S4 | 单滞回恰好拆为两条采集路径；Y 一正一负、都正、都负的结果均不依赖符号 |
| S5 | 多滞回 family 叠加或多次 X 反向时，图内显示有原因和建议的 ERROR，不输出误导统计值 |
| S6 | chart ERROR 不加入 `blocked`，PNG/XLSX 正常生成，其他 group 继续，run 不因统计单独变 partial/blocked |
| S7 | 分屏中每 pane 仅一个滞回 family 时仍分别统计，不因整图有多个 pane 误报 |
| S8 | manifest/preview/run 对 diagnostic code 与图中文字一致，preview 不产生正式 artifact/manifest |
| S9 | 统计卡、marker、ERROR 卡在 1920×1080 和 SSAA 输出中可读，不遮蔽主要曲线区域 |
| S10 | pure numeric、renderer、runner、UI、真实前台/PNG 证据分别完成 |

## 10. Stop conditions

- 实现按 Y 正负号或大小排序区分滞回支路：立即停止。
- 为了统计而排序 X、合并重复 X、裁剪到 `min(len(x), len(y))`：立即停止。
- 多滞回 diagnostic 导致 group/run blocked、跳过 data 或停止后续任务：不允许合入。
- 为“非阻塞”而吞掉普通 `ValueError`、renderer exception、checksum/cancel error：不允许合入。
- 原始/滤波 variant 被错误当成两个独立物理 family，导致单任务误报多滞回：停止验收。
- 统计值来自 display envelope/抽稀数组：停止验收。
- 只有构造数组绿测，没有真实自定义 X 往返 PNG：不得宣称完成。

## 11. Dirty-worktree and publication boundary

- 不修改/删除 `.playwright-cli/*` 既有未跟踪文件。
- 实施时保持两份计划串行；`batch.py` 不允许两个 lane 同时编辑。
- 不自动 commit、push、merge、删分支或清理 worktree；等待用户明确授权。

## 12. Execution record（执行时填写）

```text
baseline SHA:
pure numeric result:
renderer/core result:
UI result:
single-hysteresis positive/negative proof:
single-hysteresis both-positive proof:
single-hysteresis both-negative proof:
multiple-hysteresis non-blocking proof:
1080×760 foreground proof:
1440×900 foreground proof:
1920×1080 PNG proof:
```
