# Batch 自定义 X 正反程鲁棒识别 Implementation Plan

- **状态**：待执行（本文件只冻结设计与验证，不修改产品代码）
- **日期**：2026-08-03（§2.3 系数已于 2026-08-03 完成校准并冻结，见 §2.6）
- **基线**：`main` @ `5b4ccd1`（`merge: batch preview and chart statistics`）。计划早期版本写的
  `feat/batch-settings-persistence` @ `b1da3cb` + 未提交改动已经合并进来，不要再按那个状态取基线。
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

这些数据证明算法必须由本组的 X 采样尺度自适应；不得把 SFNS_10 上碰巧可行的 `0.10 mm` 写成全局固定阈值。
**但自适应的依据只能是数据本身，不能是用户所选区间**——理由见 §2.3 的 note。

### 1.3 精确基线（执行前必须复现这张表）

`plan_chart_statistics()` 在 `main` @ `5b4ccd1` 上对本地语料的实际输出：

| 样本 | `custom [-20,20]` | `full` |
| --- | --- | --- |
| SFNS_5 | `multiple_x_reversals` | `multiple_x_reversals` |
| SFNS_10 | `multiple_x_reversals` | `multiple_x_reversals` |
| SFNS_20 | `multiple_x_reversals` | `multiple_x_reversals` |
| SFNS_40 | **已经正确输出两行 `X↑`/`X↓`** | `multiple_x_reversals` |

两个必须记住的事实：

1. **SFNS_40 的 `[-20,20]` 今天就是绿的**（旧算法在该样本上只得到 2 个 direction run）。它在本计划里是
   **回归护栏**，不是修复目标；真正红的是 SFNS_5 / SFNS_10 / SFNS_20。
2. **`full` 模式四个样本全红**。`range_mode` 的默认值就是 `full`（`batch_recipe.py` 的
   `_STATISTICS_DEFAULTS`，UI 上对应「自动」档），因此 `full` 与 `custom` 必须同为一等验收对象。
   只验 `[-20,20]` 会漏掉默认路径。

## 2. Product decisions

### 2.1 什么是“路径”

- **采集段（acquisition segment）**：连续的有限 `(X,Y)` 样本。`NaN`/`Inf` 是硬边界，不能被压缩后跨越拼接。
- **主路径（major leg）**：在完整采集段上，X 已经沿某一方向累计走过足够距离，且随后沿相反方向同样走过足够距离后才确认的物理去程或回程。
  **一条 leg 自身的净行程也必须 `>= turn_distance`**，否则它不是主路径，只是采集头尾或拐点附近的残渣，
  必须被合并掉（§2.3 步骤 3）。
- **区间贡献（range contribution）**：同一主路径中所有落入统计区间的原始样本。它可以在边界附近有多个很短的 mask 碎片，但仍只属于同一主路径。
- **有效贡献（major contribution）**：规模足以代表一条物理路径的区间贡献（门槛见 §2.3 步骤 4）。
  只有有效贡献参与 §2.2 的 0/1/2/多 计数；规模不足的贡献是**别的**物理路径擦到了区间边界，直接丢弃，
  既不出行也不制造 ERROR。
- **有效正反程对**：统计区间内恰好有两条有效贡献，方向为 `X↑ → X↓` 或 `X↓ → X↑`。

所有 Max/Min/样本平均仍基于区间贡献中的原始 `(X,Y)`；方向识别可使用死区，但绝不平滑、重采样、排序、去重或改写用于统计的样本。

### 2.2 结果分类

| 区间贡献 | 有效贡献 | 图内统计结果 |
| --- | --- | --- |
| 0 条 | 0 条 | 保持现有“无区间数据”语义，不转成运行失败 |
| >= 1 条 | **0 条** | 一行 `全程`，样本为所有区间贡献的并集 |
| — | 1 条 | 一行 `全程` 统计 |
| — | 2 条且方向相反 | 两行 `X↑` / `X↓` 统计；转折点属于两个闭区间路径的既有规则不变 |
| — | 2 条但方向相同 | 局部 ERROR：同一统计区间出现两次同向有效访问，不能可靠配对为正反程 |
| — | 3 条或更多 | 局部 ERROR：区间内出现多次有效 X 路径 |

第二行是**必须的**退化分支，不是可选优化：当用户把统计区间收得很窄、区间内只剩几十个点时，
所有贡献都会低于 §2.3 步骤 4 的门槛。此时正确语义是“数据少”而不是“无数据”，更不是“多路径”。
现有用例 `test_custom_interval_keeps_order_and_reports_empty_branch`（区间内仅 1 个样本，
期望一行 `全程`、`sample_count == 1`）就走这条分支——门槛只用于**路径计数消歧**，
绝不能用来把唯一的一份数据判没。

不同 family 的 overlay 规则不变：同一 pane 内两个不同 family 各自形成有效正反程对，仍显示 `chart_statistics.multiple_hysteresis_overlay`。同一 family 的 original / filtered 继续视为同一物理路径，不得因两个 variant 再报错。

### 2.3 自适应确认死区（固定算法，不暴露 UI）

只对 `x_source="channel"` 启用主路径检测；时间 X 保持单调时间语义，不引入此算法。

#### 步骤 1 — 阈值（只看数据，不看用户区间）

对于每个有限采集段，使用同单位的 X 样本计算：

```text
data_span  = 该采集段 finite X 的 ptp        # 数据属性，与 range_mode / x_min / x_max 无关
q50_step   = median(|diff(X)| > 0)
q95_step   = P95(|diff(X)| > 0)

turn_distance = min(max(4 * q95_step, 0.005 * data_span), 0.10 * data_span)
min_support   = clamp(ceil(turn_distance / max(q50_step, eps)), 3, 64)
```

- `4 * q95_step` 覆盖样本量化/抖动而不是用一个与单位无关的浮点 epsilon；
- `0.5% * data_span` 保证高采样率数据也需要有意义的位移；
- `10% * data_span` 是上限，避免低采样率的单步移动把确认距离抬到无法识别真正大循环。

> **note（这条是硬约束，别退回旧写法）**：span 项**必须**取采集段自身的 ptp，
> **不得**取 `selection_span = x_max - x_min`。用选区做尺度会同时踩两个坑：
> (a) 上限 `10% * selection_span` 会把 `turn_distance` 压到 `4 * q95_step` 噪声地板**以下**——
> 实测 SFNS_10 取换向点附近的 `[81.7, 82.7]` 时 `turn` 被压到 0.10 < `4*q95` = 0.215，
> leg 数从 3 炸到 5、区间内 4 条 → 假 ERROR；而 ERROR 的 `suggestion` 恰恰是「请缩小统计区间」，
> 用户照做只会更糟。(b) 它让主路径识别依赖用户区间，直接违反 §2.4 自己定的
> 「先在完整采集顺序上找主路径，后裁剪统计区间」。解耦之后 `turn_distance` 对同一文件是常数，
> 换任何统计区间都不改变 leg 划分。

#### 步骤 2 — 拐点确认（`min_support` 的计数口径写死）

维护当前方向的 running extremum。对每个样本：刷新极值则计数清零；否则计数 +1，
并在**反向位移 `>= turn_distance`** 且**计数 `>= min_support`** 时提交拐点。

```text
rev_count := 自 running extremum 以来经过的样本数（期间的正向抖动同样计入，不清零）
```

> **note**：`rev_count` **不是**「连续严格反向的 `dx` 个数」。两种读法在真实数据上结论不同——
> 按「连续反向步」读，噪声会不断重置计数，SFNS_5 会塌成 1 条 leg、输出一行 `全程`（错）；
> 按上面写死的读法，SFNS_5/10/20/40 全部得到正确的两条主路径。实现和评审都以此为准。

该口径实测可挡住尖点：`turn_distance` 之上的单点 / 3 点 / 10 点尖刺都不会制造 leg（`min_support` 量级 20~39）。

#### 步骤 3 — 主路径合并（缺了这步 `full` 模式必然假 ERROR）

状态机产出的 leg 序列里，**首条、末条以及拐点附近的残渣 leg 都可能行程不足**——
首条 leg 的方向由开头两个样本（噪声）决定后即被无条件提交，中间 leg 也可能在
「反向不足 `turn_distance` 就再次折返」时被切出来。因此必须迭代合并：

```text
while 存在 leg 满足 |X[end] - X[start]| < turn_distance:
    若前后两条同向 -> 三条合并为一条
    否则若是首条   -> 并入后一条
    否则           -> 并入前一条
合并完成后，每条 leg 的方向按其净位移的符号重定
```

不做这步的实测后果（`full` 模式，四个样本全中）：

```text
SFNS_10 full: leg1 dir=-1 N=307 净位移 -0.500 mm   ← turn_distance = 0.830 mm，行程不足
              leg2 dir=+1 N=17537 净位移 +166.069
              leg3 dir=-1 N=17958 净位移 -166.004
              -> 3 条 in-range -> ERROR
SFNS_40 full: leg1 N=66 净位移 -0.188 mm，同样 -> ERROR
```

合并后四个样本的 `full` 与 `custom` 均为 2 条 leg。合并循环的迭代次数受 leg 数约束，
实测真实语料合并前 <= 4 条，代价可忽略。

#### 步骤 4 — 有效贡献门槛（缺了这步边界擦碰仍会假 ERROR）

对每条 leg 裁剪出区间贡献后，**只有同时满足**下面两条的贡献才参与 §2.2 的计数：

```text
贡献样本数     >= min_support
贡献 X 行程    >= 0.5 * max(本区间所有贡献的 X 行程)
```

行程门槛用**相对本区间最大贡献**的比例而非绝对值，这样窄区间也能自适应：
`[-0.25, 0.25]` 上两条主路径的贡献行程都是 0.483 mm，彼此都过 `0.5 * 0.483` 的门槛。

不做这步的实测后果——单次循环前加一段只探进 **0.005 mm（2 个采样点）** 的预热小动作：

```text
擦入 0.5mm(40 点) / 0.05mm(4 点) / 0.005mm(2 点) -> 4 条 in-range 贡献 -> 全部 ERROR
```

§6 的 R2 只保护「同一条 leg 内部的边界碎片」，保护不了「另一条 leg 擦到边界」。
真实台架记录在主行程前后带对中/预压动作是常态，这步不能省。

门槛全部落空时走 §2.2 的退化分支（一行 `全程`），不得判成「无区间数据」。

#### 边界与退化

- 无正步长 / `data_span == 0`（恒定 X）：跳过检测，整段视为单路径，**但仍要走区间裁剪**——
  区间内有数据就出一行 `全程`，没有才是「无区间数据」。禁止除零。
- 该阈值仅决定“是否存在一条不同方向的主路径”；数值统计仍在所有 in-range raw samples 上完成。

### 2.4 状态机与区间裁剪顺序

```text
完整、按采集顺序的有限 X/Y
        │
        ├─ 按 NaN/Inf 切开 acquisition segments
        │
        ├─ 每段按 §2.3 步骤 1 算 turn_distance / min_support
        │     （只用该段的 X 数据；与 range_mode、x_min、x_max 无关）
        │
        ├─ §2.3 步骤 2：反向位移 + min_support 确认拐点 -> raw legs
        │
        ├─ §2.3 步骤 3：合并行程 < turn_distance 的 leg -> major legs
        │     （首/末/中间残渣都要合并；漏掉这步 full 模式必假 ERROR）
        │
        ├─ 对每条 major leg 再应用 [x_min, x_max] 闭区间
        │     （保留该 leg 内所有原始 in-range X/Y）
        │
        ├─ §2.3 步骤 4：按样本数 + 相对行程筛出「有效贡献」
        │
        ├─ 按有效贡献数判定 0 / 退化全程 / 1 / X↑+X↓ / ambiguous（§2.2 表）
        │
        └─ 对每条被接受贡献计算 Max / Min / Mean / N / marker X
```

关键点：**先在完整采集顺序上找主路径，后裁剪统计区间**。这既不会把区间外的长时间段拼接，也不会把 ±20 mm 边界附近的一两个点误当新路径。

推论（用来自检实现是否跑偏）：**同一个文件、同一条通道，换任何统计区间都不应改变 major leg 的划分**。
若发现改 `x_min/x_max` 会让 leg 数变化，说明阈值又被选区污染了，回到 §2.3 步骤 1 的 note。

### 2.5 诊断与可追溯性

- 正常两路径不会改变现有卡片、marker、preview/run renderer 契约；预览和正式运行同走 `BatchRunner._build_time_figure_spec()`，天然一致。
- 仍使用既有 `chart_statistics.multiple_x_reversals` warning code，避免扩大 manifest/runner 消费者的 code surface。
- ERROR 文案改为事实性说明，例如：`当前统计区间识别到 4 条有效 X 路径，无法确定唯一升程/回程。` 不再把正常采样噪声描述为“多次反转”。
- `suggestion` 保持“缩小统计区间或拆分数据后重新运行”。这条建议只在 §2.3 步骤 1 的解耦到位后才成立——
  阈值一旦依赖选区，缩小区间反而更容易触发 ERROR（见该 note 的实测）。
- diagnostic 不能阻塞 PNG、XLSX、后续 group 或 runner terminal 状态。
- manifest 的 diagnostic 继续记录 code/panel/message；不写入自动 deadband 数值，避免把内部校准细节伪装成用户配置。

### 2.6 短序列语义（产品决定，会改既有测试）

`min_support` 的下限是 3，加上 `turn_distance` 的位移要求，**总点数低于约 7 的序列不做正反程拆分**，
退化为一行 `全程`。这是有意的：真实工程测量的一次去程不可能只有两三个采样点，
放宽下限等于把噪声尖点重新变成合法拐点。

代价是 `tests/test_batch_statistics.py` 里两个用 5 点 `[0, 1, 2, 1, 0]` 的既有用例会变红，
**必须在 Task 0 里连同 RED fixture 一起改掉，不是「顺手改绿」**：

| 用例 | 现状 | 新算法下 | 处理 |
| --- | --- | --- | --- |
| `test_single_hysteresis_splits_by_x_direction_regardless_of_y_sign` | 断言 `["X↑","X↓"]`、`[3, 3]` | 1 条 leg → 一行 `全程` | fixture 换 7 点 `[0,1,2,3,2,1,0]`，断言改 `[4, 4]` |
| `test_multiple_families_or_multiple_reversals_replace_pane_statistics`（overlay 部分） | 两条 5 点曲线 → `multiple_hysteresis_overlay` | 两条都 `hysteresis=False` → 无 diagnostic | 同样换 7 点 fixture，断言不变 |

实测 7 点三角波是最短可识别长度（`turn=0.300`、`min_support=3`，得到 `+1/N=4` 与 `-1/N=4`，
拐点按既有闭区间规则同属两条路径）。另外两个用例不受影响：

- `test_plateau_and_single_edge_noise_do_not_create_multiple_reversal_error`（8 点，回退 0.1 < `turn` 0.5）→ 仍 `全程` ✓
- `test_custom_interval_keeps_order_and_reports_empty_branch`（区间内 1 点）→ 走 §2.2 退化分支，仍 `全程` / `sample_count == 1` ✓
- `tests/test_batch_runner.py` 的 13 点双循环 fixture → 合并后仍 4 条 leg → 仍 `multiple_x_reversals` ✓
  （因此 Task 3 “无产品代码改动”的判断成立）

### 2.7 已冻结的校准结果（2026-08-03）

§2.3 的系数已按本节表格一次性冻结，实现时不得再对单个样本调参。原型验证覆盖：

| 场景 | 结果 |
| --- | --- |
| SFNS_5/10/20/40 × `custom [-20,20]` | 全部恰好 2 条反向有效贡献 |
| SFNS_5/10/20/40 × `full` | 全部恰好 2 条反向有效贡献 |
| SFNS_10 × `[-5,5] / [-2,2] / [-1,1] / [-0.5,0.5] / [-0.25,0.25]` | 全部 2 条；`turn_distance` 恒为 0.830 mm（与选区无关） |
| SFNS_10 × 换向点附近 `[62.7,82.7] … [81.7,82.7]` | 全部 2 条（旧公式在最窄一档假 ERROR） |
| 合成噪声单循环 + 单点/3 点/10 点尖刺 | 全部 2 条 |
| 合成预热擦入 0.5 / 0.05 / 0.005 mm | 全部 2 条 |
| 合成两次真实循环 | ERROR（4 条） |
| 合成两次同向访问 `[21,29]` | ERROR（3 条，方向 `+ − +`） |
| 单向去程 / 上升后平台 / 恒定 X(full) | 一行 `全程` |
| 完全在区间外 / 恒定 X 且区间外 | 无区间数据 |

性能（纯 Python 单次线性扫描 + 合并循环）：35,800 点 0.005 s、500,000 点 0.074 s、
2,000,000 点 0.293 s。无需为向量化扭曲实现。

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
   （构造提示：`−30→30 → 30→25 → 25→−30 → −30→30`，统计区间取 `[21, 29]`。
   直接写「两条完整跨区间的 `X↑` 而中间回退不进区间」是几何上不可能的——连续 X 的回退必然穿过区间。）
5. **区间隔离**：原始记录可有更多 major legs，但指定区间只被一对相反方向主路径覆盖时正常统计；证明 error 只基于该统计区间。
6. **Y 不变量**：正负混合、双正、双负 Y 使用相同 X 时，legs、N、branch labels 完全一致。
7. **无有效反转 / 平台 / 有限性间断**：平台返回单行；NaN/Inf 分段不被静默拼接；极短边界触点不独立制造多路径。
8. **原始+滤波 variant**：同 family 两个 variant 收到相同 X 路径划分，各自计算其 Y；不会触发 multi-family overlay。
9. **`full` 模式头尾残渣（守 §2.3 步骤 3）**：在完整单循环前面接一段行程远小于 `turn_distance`
   的起步抖动（如 300 点、净位移 0.5 mm，量程 166 mm）。`range_mode="full"` 必须仍得两行，
   不得因为第一条 leg 被无条件提交而报 ERROR。**这是四个真实样本 `full` 模式全红的直接原因，
   不能只靠可 skip 的真实文件测试兜底。**
10. **区间边界擦碰（守 §2.3 步骤 4）**：单循环之前插入一段只探进区间 2 个采样点（约 0.005 mm）
    的预热小动作。必须仍得两行；把该动作放大到明确的主路径规模后才转 ERROR。
11. **阈值与选区解耦（守 §2.3 步骤 1 的 note）**：同一条噪声 X 分别用
    `full`、宽区间、窄区间、贴近换向点的窄区间统计，断言 major leg **划分完全相同**，
    只有 in-range 的 `N` 随区间变化。这条是防止未来有人把 `data_span` 改回 `selection_span` 的锁。
12. **短序列退化（守 §2.6）**：7 点三角波得两行、5 点 `[0,1,2,1,0]` 得一行 `全程`；
    同时按 §2.6 表格更新 `test_single_hysteresis_splits_by_x_direction_regardless_of_y_sign`
    与 overlay 用例的 fixture 和断言。

`tests/test_batch_statistics_real_wwt.py` 只在本地 `testdoc/2024_3_17` 文件存在时运行，否则明确 `skip`。它参数化 SFNS_5/10/20/40，从**含有** `Rack Travel/Rack Force` 的 group 读取数据（SFNS_40 有一个只含 `Time/Weg` 的前置 group），固定 `[-20,20] mm`，断言无 diagnostic、恰好 `X↑/X↓` 两行、每条路径覆盖接近全区间。CI 的硬保证来自前述合成 fixtures，而不是 ignored 文件。

### Task 1 — Pure major-leg extractor

**Files**

- Modify: `mf4_analyzer/batch_statistics.py`
- Tests: `tests/test_batch_statistics.py`

以私有 pure helpers 替换 `_direction_runs()` 的相邻符号逻辑：

```python
_acquisition_segments(x, y)            -> tuple[_IndexSpan, ...]
_turn_policy(x)                        -> _TurnPolicy | None   # 注意：不接收 selection_span
_raw_legs(x, policy)                   -> list[_MajorLeg]      # §2.3 步骤 2
_merge_short_legs(legs, x, policy)     -> tuple[_MajorLeg, ...] # §2.3 步骤 3
_clip_major_leg(leg, x, y, lo, hi)     -> _RangeContribution
_major_contributions(contribs, policy) -> tuple[_RangeContribution, ...] # §2.3 步骤 4
```

实现约束：

- `_turn_policy` **不接收统计区间参数**。签名里出现 `lo/hi/selection_span` 即为实现跑偏，
  §2.3 步骤 1 的 note 说明了原因；
- 允许**一次** Python 层线性扫描实现 `_raw_legs` 的状态机——它无法自然向量化，
  实测 2,000,000 点 0.293 s，不构成瓶颈。不引入 scipy、滑动窗口全量复制或二次复杂度；
- `_raw_legs` 用运行极值和“反向位移 >= turn_distance 且样本支持 >= min_support”确认拐点；未确认的回退继续归入当前 leg。
  `rev_count` 按 §2.3 步骤 2 的 note 计数（自极值起的样本数，正向抖动不清零）；
- `_merge_short_legs` 迭代到不动点，首条/末条/中间残渣一视同仁；合并后按净位移重定方向；
- 被确认的极值 index 同时属于前后两个 major leg，保留当前闭区间 pivot 计数语义；
- `_turn_policy` 计算需跳过零/非有限 `dx`，`data_span` 为零或无正步长时返回 `None`，
  调用方退化为单路径**但仍走区间裁剪**（§2.3 边界与退化），禁止除零；
- x/y 不等长仍维持现有 `StatisticSeriesInput` hard error；不准用 `min(len(x), len(y))`；
- custom range 只在 `_clip_major_leg` 后应用；full range 直接收集整条 leg；
- 统计与 marker 位置用 contribution 的未改写 raw arrays；deadband 结果只存 leg index / direction。

每个 helper 的边界（pivot 是否重复、边界点归属、NaN 断开、选中区间闭区间）都必须由 Task 0 的精确 `N` 和 `argmin_x/argmax_x` 断言冻结。

### Task 2 — Per-series rows and per-pane ambiguity policy

**Files**

- Modify: `mf4_analyzer/batch_statistics.py`
- Tests: `tests/test_batch_statistics.py`

重写 `_series_rows()`：

0. `_series_rows()` 需要新增 `x_source` 形参（现在只有 `mode/lo/hi`）。它是私有函数，
   `plan_chart_statistics()` 已持有 `x_source`，**公开签名不变**。
1. `x_source="time"` 维持一条按现有 display-X 转换后的全程/自定义区间统计；不走 custom-X major-leg 状态机。
2. `x_source="channel"` 获取 full acquisition segments → raw legs → 合并 → in-range contributions → 有效贡献筛选。
3. 严格按 §2.2 的表分派：无贡献 → 无区间数据；有贡献但无有效贡献 → 一行 `全程`（样本取所有贡献的并集）；
   恰好一条有效贡献 → `全程`；恰好两条且方向相反 → 既有 `路径 1 · X↑/X↓` 行；
   其余 → reason `multiple_reversals`，不返回可能误导的 rows。
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
- 1920×1080 / 144 DPI 生成实际 PNG；用同一个本地 WWT 在 Preview dialog 和正式 Batch run 目视确认
  `[-20,20]` **与默认「自动」（`full`）两档**都出现两行 `X↑/X↓`；
- 记录前台证据和 offscreen evidence 分开，不能以 pytest/离屏 PNG 宣称 Cocoa 前台已验收。

## 5. Verification matrix

| 层级 | 必需证据 |
| --- | --- |
| Baseline | 动手前先复现 §1.3 那张表（含 SFNS_40 `custom` 已绿、四个样本 `full` 全红），并记下 `tests/ui/` 的既有失败数 |
| Pure deterministic | 噪声单循环、boundary chatter、双循环、同向重复、区间隔离、Y 不变量、NaN/平台、variant family、**full 模式头尾残渣、区间擦碰、阈值与选区解耦、短序列退化** |
| Local real data | SFNS_5/10/20/40 的 `Rack Travel` 在 **`[-20,20]` 与 `full` 两种 range_mode** 下各得到一对路径；记录 sample count / direction / 无 diagnostic |
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
| R1 | SFNS_5/10/20/40 在 `[-20,20] mm` **和 `range_mode="full"`** 下都输出恰好 `X↑/X↓` 两条统计，而非 `multiple_x_reversals`（SFNS_40 的 `custom` 一档是回归护栏，基线已绿，见 §1.3） |
| R2 | 采样步进、量化、边界 chatter 与 1–3 点短碎片不会独立制造路径——**无论这些点属于当前主路径还是属于另一条只擦到区间边界的 leg** |
| R3 | 真正两次循环、三条以上有效路径或两次同向有效访问继续显示 chart-local ERROR，且不输出统计数字 |
| R4 | custom range 在 major-leg 识别之后裁剪；区间外间隔、NaN/Inf 均不被拼接成虚假连续路径 |
| R5 | Max/Min/Mean、N、marker X 均取 raw in-range X/Y；方向检测不改统计样本 |
| R6 | original/filtered 保持同一 family，不触发 false overlay diagnostic；不同 family 的现有 overlay rule 不回归 |
| R7 | preview、正式 PNG、manifest 的 rows/diagnostic code/message 一致；diagnostic 仍不阻塞运行 |
| R8 | 默认关闭、time X、recipe/preset/fingerprint、Qt statistics card 视觉和 renderer 公共模型均不产生无关变更。**唯一允许的既有测试改动是 §2.6 表格里那两个 5 点 fixture** |
| R9 | 同一文件同一通道，`full` / 宽区间 / 窄区间 / 换向点窄区间给出**完全相同**的 major leg 划分；只有 in-range `N` 随区间变化 |
| R10 | 统计区间收窄到区间内只剩少量样本时，输出一行 `全程`，不得退化成「无区间数据」或 ERROR |

## 7. Stop conditions and publication boundary

- 只改变浮点 epsilon、却没有“完整采集段 → major leg → 区间裁剪”顺序：停止。
- 根据 Y 正负、可视化曲线形状或像素抽稀判断正反程：停止。
- 把 `testdoc/` ignored 数据加入 Git，或让可 skip 的真实文件测试成为唯一回归：停止。
- 用此修复吞掉真实 renderer/loader exception，或将 chart-local diagnostic 改为 runner blocked：停止。
- 未经 Task 0 corpus 校准就针对 SFNS_10 硬编码 `0.10 mm`：停止。
- **只在 `custom [-20,20]` 上验收、没有跑 `range_mode="full"`：停止**（默认档就是 `full`，且基线四个样本全红）。
- **`turn_distance` 的任何一项依赖 `x_min`/`x_max`/`selection_span`：停止**（违反 §2.3 步骤 1 的 note 与 R9）。
- **跳过 §2.3 步骤 3（leg 合并）或步骤 4（有效贡献门槛）：停止**——两者各自对应一类已实测的假 ERROR，不是可选优化。
- **把 §2.6 之外的既有测试改绿以适配新实现：停止**。既有断言变红说明产品语义变了，先回来更新本文件的产品决定。
- 不自动 commit、push、merge、清理工作区；当前大量未提交改动由既有 Batch 工作流任务所有。

## 8. 参考实现（已通过 §2.7 全部校准场景）

以下骨架是 §2.3 四个步骤的可运行形态，用来消除文字歧义（尤其 `rev_count` 口径与合并循环），
不是最终代码——落地时按 Task 1 的 helper 划分、命名与 dataclass 约定重写。

```python
def _turn_policy(x):                                   # 步骤 1：只看数据
    steps = np.abs(np.diff(x))
    steps = steps[steps > 0]
    data_span = float(np.ptp(x)) if x.size else 0.0
    if steps.size == 0 or not np.isfinite(data_span) or data_span <= 0:
        return None                                    # 调用方退化为单路径 + 区间裁剪
    q50 = float(np.median(steps))
    q95 = float(np.percentile(steps, 95))
    turn = min(max(4.0 * q95, 0.005 * data_span), 0.10 * data_span)
    support = int(min(64, max(3, math.ceil(turn / max(q50, 1e-12)))))
    return turn, support


def _raw_legs(x, turn, support):                       # 步骤 2
    legs, start, direction = [], 0, 0
    ext_i, ext_v, rev = 0, x[0], 0
    for i in range(1, x.size):
        v = x[i]
        if direction == 0:
            if v != ext_v:
                direction, ext_i, ext_v, rev = (1 if v > ext_v else -1), i, v, 0
            continue
        if direction * (v - ext_v) > 0:                # 刷新极值
            ext_i, ext_v, rev = i, v, 0
            continue
        rev += 1                                       # 正向抖动同样计入，不清零
        if direction * (ext_v - v) >= turn and rev >= support:
            legs.append([start, ext_i, direction])
            start, direction = ext_i, -direction       # pivot 同属前后两条 leg
            ext_i, ext_v, rev = i, v, 0
    legs.append([start, x.size - 1, direction])
    return legs


def _merge_short_legs(legs, x, turn):                  # 步骤 3
    changed = True
    while changed and len(legs) > 1:
        changed = False
        for i, (s, e, _d) in enumerate(tuple(legs)):
            if abs(x[e] - x[s]) >= turn:
                continue
            if 0 < i < len(legs) - 1 and legs[i - 1][2] == legs[i + 1][2]:
                legs[i - 1][1] = legs[i + 1][1]
                del legs[i:i + 2]
            elif i == 0:
                legs[1][0] = legs[0][0]
                del legs[0]
            else:
                legs[i - 1][1] = legs[i][1]
                del legs[i]
            changed = True
            break
    for leg in legs:                                   # 合并后按净位移重定方向
        leg[2] = 1 if x[leg[1]] >= x[leg[0]] else -1
    return legs


def _major_contributions(contribs, support):           # 步骤 4
    if not contribs:
        return []
    floor = 0.5 * max(item.travel for item in contribs)
    return [item for item in contribs
            if item.count >= support and item.travel >= floor]
```

调用方按 §2.2 分派；注意 `_major_contributions` 返回空但 `contribs` 非空时走退化分支
（合并所有 `contribs` 出一行 `全程`），不是「无区间数据」。

## 9. Execution record（执行时填写）

```text
baseline (§1.3 表 + tests/ui 既有失败数):
RED fixtures:
pure planner:
real WWT local corpus (custom [-20,20]):
real WWT local corpus (full):
阈值与选区解耦 (R9):
窄区间退化 (R10):
runner/preview/manifest:
renderer PNG:
foreground Preview/final PNG:
```
