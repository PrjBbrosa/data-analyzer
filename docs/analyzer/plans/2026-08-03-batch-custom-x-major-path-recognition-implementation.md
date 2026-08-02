# Batch 自定义 X 正反程鲁棒识别 Implementation Plan

- **状态**：待执行（本文件只冻结设计与验证，不修改产品代码）
- **日期**：2026-08-03
- **基线**：`feat/batch-settings-persistence` @ `b1da3cb`，工作区已有未提交的 Batch workflow / 图内统计改动
- **前置**：`2026-08-02-batch-in-chart-statistics-implementation.md` 的图内统计主链已存在；本计划只替换其 §4.3 的方向识别实现
- **范围**：仅 Batch `time + x_source=channel` 的图内统计正反程判定；不增加用户设置、不重写统计 UI/Qt 卡片/renderer

> 用户决定：区间内物理上只有一次去程和一次回程时，即使 X 通道有采样抖动、量化台阶或在区间边界反复进出，也必须生成两条路径统计。只有真正多次、且具有足够位移的正反程才显示 chart-local `ERROR`；不能因为每个相邻 `dx` 的正负变化就拒绝整张图。

---

## 1. Problem statement and verified baseline

现有 `mf4_analyzer/batch_statistics.py::_series_rows()` 的顺序为：

1. 先用 `x_min <= X <= x_max` 筛掉区间外样本；
2. 把剩余样本压缩为一个数组；
3. 用相邻 `dx` 的正/负号形成 `_direction_runs()`；
4. 仅忽略少于两个 edge 的片段；方向段超过两条即写入 `chart_statistics.multiple_x_reversals`。

这两个实现细节共同导致误报：

- 容差是 `1e-9 * scale` 级别的纯浮点比较，不是采样噪声容差；
- 压缩区间 mask 会丢掉采集时间中的“区间外”间隔，把后一次进入区间的点拼到前一次离开区间的点后面；
- 区间边缘的量化抖动会形成 1–3 点碎片，当前“按 edge 数”规则仍会保留许多较长的反向片段。

### 1.1 真实样本证据（只读）

用户截图对应的本地样本为：

```text
testdoc/2024_3_17/SFNS_10_X04-CSER_000009.wwt
X = Rack Travel (mm)
Y = Rack Force (N)
统计区间 = [-20, 20] mm
```

其 35,800 个原始样本中，7,983 个落入区间。严格 mask 后看见 7 个连续碎片；其中只有两条是物理主路径：

| 样本 | 主路径点数 | X 首尾 | 净位移 | `P95(|dx|)` |
| --- | ---: | --- | ---: | ---: |
| SFNS_10 | 3,989 | −19.975 → 19.970 | +39.945 mm | 0.04834 mm |
| SFNS_10 | 3,986 | 19.981 → −19.975 | −39.956 mm | 0.04834 mm |

其余五个碎片各只有 1–3 点，出现在 ±20 mm 的量化边界。当前浮点容差约 `4e-8 mm`，而此数据的 `median(|dx|)=0.01611 mm`、`max(|dx|)=0.10205 mm`；因此当前函数错误地产生 452 个方向段。

这不是“用户设置范围内有 452 次物理往返”，也不能通过把常数从 `1e-9` 调大一点来稳妥修复。

### 1.2 不只针对一组数据的校准集

同一个 tracked-code 工作区的本地 WWT corpus（文件本身被 `.gitignore` 排除，故不作为 CI 必需 fixture）显示不同采样密度下同一物理模式：

| 样本 | `[-20,20]` 内点数 | 有效主路径点数 | `P95(|dx|)` |
| --- | ---: | --- | ---: |
| SFNS_5 | 15,959 | 7,973 / 7,981 | 0.04834 mm |
| SFNS_10 | 7,983 | 3,989 / 3,986 | 0.04834 mm |
| SFNS_20 | 3,991 | 1,996 / 1,995 | 0.05908 mm |
| SFNS_40 | 1,990 | 999 / 991 | 0.08057 mm |

这些数据证明算法必须由本组的 X 采样尺度和所选区间共同自适应；不得把 SFNS_10 上碰巧可行的 `0.10 mm` 写成全局固定阈值。

## 2. Product decisions

### 2.1 什么是“路径”

- **采集段（acquisition segment）**：连续的有限 `(X,Y)` 样本。`NaN`/`Inf` 是硬边界，不能被压缩后跨越拼接。
- **主路径（major leg）**：在完整采集段上，X 已经沿某一方向累计走过足够距离，且随后沿相反方向同样走过足够距离后才确认的物理去程或回程。
- **区间贡献（range contribution）**：同一主路径中所有落入统计区间的原始样本。它可以在边界附近有多个很短的 mask 碎片，但仍只属于同一主路径。
- **有效正反程对**：统计区间内恰好有两条有数据的主路径，方向为 `X↑ → X↓` 或 `X↓ → X↑`。

所有 Max/Min/样本平均仍基于区间贡献中的原始 `(X,Y)`；方向识别可使用死区，但绝不平滑、重采样、排序、去重或改写用于统计的样本。

### 2.2 结果分类

| 区间内主路径 | 图内统计结果 |
| --- | --- |
| 0 条（无区间数据） | 保持现有“无区间数据”语义，不转成运行失败 |
| 1 条 | 一行 `全程` 统计 |
| 2 条且方向相反 | 两行 `X↑` / `X↓` 统计；转折点属于两个闭区间路径的既有规则不变 |
| 2 条但方向相同 | 局部 ERROR：同一统计区间出现两次同向有效访问，不能可靠配对为正反程 |
| 3 条或更多 | 局部 ERROR：区间内出现多次有效 X 路径 |

不同 family 的 overlay 规则不变：同一 pane 内两个不同 family 各自形成有效正反程对，仍显示 `chart_statistics.multiple_hysteresis_overlay`。同一 family 的 original / filtered 继续视为同一物理路径，不得因两个 variant 再报错。

### 2.3 自适应确认死区（固定算法，不暴露 UI）

只对 `x_source="channel"` 启用主路径检测；时间 X 保持单调时间语义，不引入此算法。

对于每个有限采集段，使用同单位的 X 样本计算：

```text
selection_span = custom 时 (x_max - x_min)，full 时 finite-X 的 ptp
q50_step       = median(|diff(X)| > 0)
q95_step       = P95(|diff(X)| > 0)

raw_turn_distance = max(4 * q95_step, 0.005 * selection_span)
turn_distance     = min(raw_turn_distance, 0.10 * selection_span)
min_support       = clamp(ceil(turn_distance / max(q50_step, eps)), 3, 64)
```

说明：

- `4 * q95_step` 覆盖样本量化/抖动而不是用一个与单位无关的浮点 epsilon；
- `0.5% * selection_span` 保证高采样率数据也需要有意义的位移；
- `10% * selection_span` 是上限，避免低采样率的单步移动把确认距离抬到无法识别真正大循环；
- `min_support` 要求反向持续足够采样点，避免一个偶发尖点完成“反转确认”；
- 这些系数必须通过 Task 0 的合成与真实 corpus 验证后一次性冻结。若校准集出现冲突，停止实施并记录偏差，不能对单个截图调参。

该阈值仅决定“是否存在一条不同方向的主路径”；数值统计仍在所有 in-range raw samples 上完成。

### 2.4 状态机与区间裁剪顺序

```text
完整、按采集顺序的有限 X/Y
        │
        ├─ 按 NaN/Inf 切开 acquisition segments
        │
        ├─ 每段用自适应 deadband 确认 major legs
        │     （反向位移 + min_support 后才提交拐点）
        │
        ├─ 对每条 major leg 再应用 [x_min, x_max] 闭区间
        │     （保留该 leg 内所有原始 in-range X/Y）
        │
        ├─ 按区间内有数据的 leg 判定 0 / 1 / X↑+X↓ / ambiguous
        │
        └─ 对每条被接受 leg 计算 Max / Min / Mean / N / marker X
```

关键点：**先在完整采集顺序上找主路径，后裁剪统计区间**。这既不会把区间外的长时间段拼接，也不会把 ±20 mm 边界附近的一两个点误当新路径。

### 2.5 诊断与可追溯性

- 正常两路径不会改变现有卡片、marker、preview/run renderer 契约；预览和正式运行同走 `BatchRunner._build_time_figure_spec()`，天然一致。
- 仍使用既有 `chart_statistics.multiple_x_reversals` warning code，避免扩大 manifest/runner 消费者的 code surface。
- ERROR 文案改为事实性说明，例如：`当前统计区间识别到 4 条有效 X 路径，无法确定唯一升程/回程。` 不再把正常采样噪声描述为“多次反转”。
- `suggestion` 保持“缩小统计区间或拆分数据后重新运行”；不能阻塞 PNG、XLSX、后续 group 或 runner terminal 状态。
- manifest 的 diagnostic 继续记录 code/panel/message；不写入自动 deadband 数值，避免把内部校准细节伪装成用户配置。

## 3. Explicit non-goals

- 不增加“噪声阈值 / 反转阈值”面板控件，不让用户为每一张图调试算法。
- 不按 Y 正负、Y 幅值、曲线颜色或渲染抽稀结果识别路径。
- 不改变 `chart_statistics` recipe schema、fingerprint、preset 兼容或默认关闭行为。
- 不改 `BatchStatisticRow` / `BatchTimeFigureSpec` / Qt statistics card 的公开字段；只有正常 rows 与 diagnostic 出现条件变化。
- 不把多个实际循环自动拆成多张图，也不从 ERROR 自动降级为“把所有路径混在一行平均”。
- 不将 ignored `testdoc/` 文件加入 Git 或作为 CI 唯一依据。

## 4. Implementation tasks

### Task 0 — RED corpus and decision locks

**Files**

- Modify: `tests/test_batch_statistics.py`
- Add optional local proof: `tests/test_batch_statistics_real_wwt.py`

先写失败测试，不改 `mf4_analyzer/batch_statistics.py`：

1. **确定性噪声单循环**：构造 `−83 → 83 → −83` 的 X；在每一步叠加有界、可复现的量化型锯齿噪声。对 `[-20,20]` 统计，必须产生 `X↑`、`X↓` 两行，绝不能报 ERROR。
2. **边界 chatter**：在 ±20 两侧穿插 1–3 点内/外区间接触；结果仍恰好两条主路径，统计样本不跨 Y/X 配对。
3. **两次真实循环**：四条有显著位移的主路径进入同一区间，继续得到 `multiple_x_reversals`，且无 rows。
4. **两次同向访问**：两次 `X↑` 都覆盖区间、回退发生在区间外；得到同一局部 diagnostic，不能伪装成 `X↑/X↓`。
5. **区间隔离**：原始记录可有更多 major legs，但指定区间只被一对相反方向主路径覆盖时正常统计；证明 error 只基于该统计区间。
6. **Y 不变量**：正负混合、双正、双负 Y 使用相同 X 时，legs、N、branch labels 完全一致。
7. **无有效反转 / 平台 / 有限性间断**：平台返回单行；NaN/Inf 分段不被静默拼接；极短边界触点不独立制造多路径。
8. **原始+滤波 variant**：同 family 两个 variant 收到相同 X 路径划分，各自计算其 Y；不会触发 multi-family overlay。

`tests/test_batch_statistics_real_wwt.py` 只在本地 `testdoc/2024_3_17` 文件存在时运行，否则明确 `skip`。它参数化 SFNS_5/10/20/40，从**含有** `Rack Travel/Rack Force` 的 group 读取数据（SFNS_40 有一个只含 `Time/Weg` 的前置 group），固定 `[-20,20] mm`，断言无 diagnostic、恰好 `X↑/X↓` 两行、每条路径覆盖接近全区间。CI 的硬保证来自前述合成 fixtures，而不是 ignored 文件。

### Task 1 — Pure major-leg extractor

**Files**

- Modify: `mf4_analyzer/batch_statistics.py`
- Tests: `tests/test_batch_statistics.py`

以私有 pure helpers 替换 `_direction_runs()` 的相邻符号逻辑：

```python
_acquisition_segments(x, y) -> tuple[_IndexSpan, ...]
_turn_distance(x, selection_span) -> _TurnPolicy
_major_legs(x, policy) -> tuple[_MajorLeg, ...]
_clip_major_leg(leg, x, y, lo, hi) -> _RangeContribution
```

实现约束：

- helpers 只使用 NumPy，线性扫描 `O(n)`，不引入 scipy、滑动窗口全量复制或二次复杂度；
- `_major_legs` 用运行极值和“反向位移 >= turn_distance 且样本支持 >= min_support”确认拐点；未确认的回退继续归入当前 leg；
- 被确认的极值 index 同时属于前后两个 major leg，保留当前闭区间 pivot 计数语义；
- `turn_distance` 计算需跳过零/非有限 `dx`，span 为零或无正步长时稳定退化为单路径，禁止除零；
- x/y 不等长仍维持现有 `StatisticSeriesInput` hard error；不准用 `min(len(x), len(y))`；
- custom range 只在 `_clip_major_leg` 后应用；full range 直接收集整条 leg；
- 统计与 marker 位置用 contribution 的未改写 raw arrays；deadband 结果只存 leg index / direction。

每个 helper 的边界（pivot 是否重复、边界点归属、NaN 断开、选中区间闭区间）都必须由 Task 0 的精确 `N` 和 `argmin_x/argmax_x` 断言冻结。

### Task 2 — Per-series rows and per-pane ambiguity policy

**Files**

- Modify: `mf4_analyzer/batch_statistics.py`
- Tests: `tests/test_batch_statistics.py`

重写 `_series_rows()`：

1. `x_source="time"` 维持一条按现有 display-X 转换后的全程/自定义区间统计；不走 custom-X major-leg 状态机。
2. `x_source="channel"` 获取 full acquisition segments → major legs → in-range contributions。
3. 恰好一条 contribution：使用 `全程`；恰好两个且方向相反：生成既有 `路径 1 · X↑/X↓` 行；其他非空集合返回 reason `multiple_reversals`，不返回可能误导的 rows。
4. per-pane planner 保留现有两个 family 规则与 `blocked_panels` 行为；同 family 的 variant 不重复计作 family。
5. 不改变 `plan_chart_statistics()` 对 disabled、metrics、`display_x()` 和数据类的调用签名，确保 Batch runner / preview / renderer 无 connector 改动。

### Task 3 — Runner, preview and manifest compatibility tests

**Files**

- Modify tests: `tests/test_batch_runner.py`
- Expected production code change: none outside Task 1–2，除非 tests 证明现有 connector 没有将同 family variants 传入同一 planner call

添加/调整 producer-shaped tests：

- 用确定性 noisy custom-X 输入从 `BatchRunner.run()` 构建 `BatchTimeFigureSpec`，断言 `statistics` 是两行而非 diagnostic；
- 对同一输入的 `preview_group()` 与正式 `run()` 断言 diagnostics、row branches、manifest summary 一致；preview 仍不创建 manifest；
- 两个真实 major cycle 的 diagnostic 继续是 `done` group warning，PNG/XLSX 写入且下一 group 继续；
- `filter.show_original + filter.show_filtered` 保留两 variant 的统计 rows，但 overlay policy 不把它们误判成两个 family；
- manifest 断言从“旧的泛化多次反转文案”更新为新事实性文案；code、non-blocking status、row summary schema 均保持。

### Task 4 — Renderer and foreground evidence

**Files**

- Modify only tests if row/diagnostic strings change: `tests/test_batch_render_qt.py`
- No planned renderer code change: `mf4_analyzer/batch_render_qt/_builder.py`

验证 renderer 只消费 producer rows/diagnostics：

- noisy 正反程 payload 显示正常统计卡和橙色 Max / 青绿色 Min marker，不显示红卡；
- 真实 multiple-cycle payload 仍以红色诊断卡整体替换统计数字；
- 1920×1080 / 144 DPI 生成实际 PNG；用同一个本地 WWT 在 Preview dialog 和正式 Batch run 目视确认 `[-20,20]` 出现两行 `X↑/X↓`；
- 记录前台证据和 offscreen evidence 分开，不能以 pytest/离屏 PNG 宣称 Cocoa 前台已验收。

## 5. Verification matrix

| 层级 | 必需证据 |
| --- | --- |
| Pure deterministic | 噪声单循环、boundary chatter、双循环、同向重复、区间隔离、Y 不变量、NaN/平台、variant family |
| Local real data | SFNS_5/10/20/40 的 `Rack Travel` `[-20,20]` 各得到一对路径；记录 sample count / direction / 无 diagnostic |
| Runner | preview/run/manifest 的 row 与 diagnostic 一致；chart warning 不阻塞 |
| Renderer | 正常卡/marker 与 ERROR 卡仍遵循现有 image contract |
| Foreground | BatchSheet 手动范围、Preview、最终 PNG 三者显示同一结果 |

建议执行顺序：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_statistics.py \
  tests/test_batch_runner.py \
  tests/test_batch_render_qt.py \
  tests/ui/test_batch_chart_statistics.py \
  tests/ui/test_batch_smoke.py

# 仅本地样本存在时；skip 不是 CI 成功的替代物
TMPDIR=/tmp PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/test_batch_statistics_real_wwt.py

git diff --check
```

## 6. Acceptance criteria

| ID | Acceptance |
| --- | --- |
| R1 | SFNS_5/10/20/40 在 `[-20,20] mm` 都输出恰好 `X↑/X↓` 两条统计，而非 `multiple_x_reversals` |
| R2 | 采样步进、量化、边界 chatter 与 1–3 点短碎片不会独立制造路径 |
| R3 | 真正两次循环、三条以上有效路径或两次同向有效访问继续显示 chart-local ERROR，且不输出统计数字 |
| R4 | custom range 在 major-leg 识别之后裁剪；区间外间隔、NaN/Inf 均不被拼接成虚假连续路径 |
| R5 | Max/Min/Mean、N、marker X 均取 raw in-range X/Y；方向检测不改统计样本 |
| R6 | original/filtered 保持同一 family，不触发 false overlay diagnostic；不同 family 的现有 overlay rule 不回归 |
| R7 | preview、正式 PNG、manifest 的 rows/diagnostic code/message 一致；diagnostic 仍不阻塞运行 |
| R8 | 默认关闭、time X、recipe/preset/fingerprint、Qt statistics card 视觉和 renderer 公共模型均不产生无关变更 |

## 7. Stop conditions and publication boundary

- 只改变浮点 epsilon、却没有“完整采集段 → major leg → 区间裁剪”顺序：停止。
- 根据 Y 正负、可视化曲线形状或像素抽稀判断正反程：停止。
- 把 `testdoc/` ignored 数据加入 Git，或让可 skip 的真实文件测试成为唯一回归：停止。
- 用此修复吞掉真实 renderer/loader exception，或将 chart-local diagnostic 改为 runner blocked：停止。
- 未经 Task 0 corpus 校准就针对 SFNS_10 硬编码 `0.10 mm`：停止。
- 不自动 commit、push、merge、清理工作区；当前大量未提交改动由既有 Batch 工作流任务所有。

## 8. Execution record（执行时填写）

```text
RED fixtures:
pure planner:
real WWT local corpus:
runner/preview/manifest:
renderer PNG:
foreground Preview/final PNG:
baseline failures:
```
