# 时域渲染「墨水量预算」治理设计（AA 触发边界 + 满高竖线墙统一机制）

> **Implementation note (2026-08-08, measured)：已按计划 Task 0–6 实施完毕**
> （分支 `fix/aa-ink-budget`，Task 0/1/2/3/4/5 各一 commit + 组合语义修复
> `7884b574`）。真机 Cocoa（dpr 2.0，1600×950）验收实测 vs 本文基线：
>
> | 验收项 | 治理前（§1） | 治理后 | 判定 |
> |---|---|---|---|
> | 1ch 振荡+Y fit 空闲升级帧 | 首帧 124.6 s / 稳态 62.4 s | **8.6 ms**（光栅覆盖，向量 AA 未触发） | ✅ |
> | 6ch 振荡最坏 AA 帧 | 7.2 s | 34.7 ms（ink 闸门 block） | ✅ |
> | 拖动 p50，全 ratio 带含 1.0 峰值 | 峰值 106 ms | **5.2–9.6 ms** | ✅ ≤30 |
> | 缩放 settle p50 | 127 ms | 33.6 ms | ⚠️ 超目标 12%，见下 |
> | 平滑对照（ink 72.7k） | AA 240–474 ms | AA 照常开启，238.8 ms | ✅ 零回归 |
> | `benchmark_timedomain_interaction --assert-standards` | — | 通过（门禁未放宽） | ✅ |
>
> 三点实施期修订（均不改本文机制结论）：
> 1. **§4.2 与 §4.3 的组合语义**：高 ink 线一旦被光栅 entry 覆盖，即从
>    AA 求和中剔除且不进 native-AA 集——此时闸门放行是**设计正确**（被
>    覆盖曲线不再走向量描边）；「高 ink 拒 AA」只对未覆盖构形成立。
>    契约见 `TestInkBudget` 三条双分支用例（`7884b574`）。
> 2. **缩放 settle 33.6 ms** 是「每个滚轮刻度强制走 settle + 被覆盖线
>    光栅重建」的最坏口径；产品滚轮路径 settle 每手势只落一次（coarse
>    通道在持手势期间为 transform-only）。判定为可接受，目标数字不改。
> 3. **6ch 密集堆叠**的行 ink（~208k dev/行）低于光栅准入带（300k），
>    维持原生非 AA 路径——subplot 密集帽（§1.2 表第二行）已把它压在
>    35 ms 帧内，闸门 block 挡掉了 7.2 s 的 AA 帧，无需光栅接管。
>
> 单行光栅 entry 实测 24.18 MiB（offscreen dpr1 @1920×900）——旧 16 MiB
> 帽确实拒收，§4.3 的 36 MiB 重标是准入前提。Windows 复标定（§7.4）仍
> 未做，进 release 前必须完成。
>
> 状态：~~设计定稿，未实施~~ → **已实施，待 Windows 复标定**。实施计划见
> `docs/analyzer/plans/2026-08-08-timedomain-aa-ink-budget-implementation.md`。
> 分支：`fix/aa-ink-budget`。
>
> 本文所有数字均为 2026-08-08 真机实测（macOS Cocoa，dpr=2.0，画布
> 1600×950，subplot 模式，合成信号 1M 点 @20 kHz：
> `100·sin(2π·2300t) + 8·sin(2π·0.7t)`，幅值 ±108；产品
> `fit_y_to_visible_x()` 实际给出 ylim=±118.8——与现场报告的
> 「±100 来回跳、Y fit 到 ±120」一致）。复测脚本随实施计划固化进
> `scripts/`。

## 1. 问题

满屏堆叠振荡的曲线（每个像素列的 min/max 对被画成贯穿整行的竖线）在
Y 自适应之后，缩放和拖动全面卡顿。实测三个独立的成本出口：

1. **交互帧（AA-off）**：拖动 p50 67 ms、缩放 p50 127 ms —— 显示点数
   与平滑对照组完全相同（3104），帧成本差 18×。
2. **空闲 AA 升级帧**：松手 150 ms 后 `try_enable_idle_quality` 自动开
   向量 AA，该帧实测 **124 s**（首帧）/ **63 s**（DeviceCoordinateCache
   后续帧）。6 通道堆叠为 7.2 s / 3.6 s。三个场景闸门判定均为 allow。
3. **导出路径**：`_export_aa_affordable` 用同一点数指标 → 复制/保存图片
   在此视图下强制 AA，同样冻结数十秒。

### 1.1 成本的真实自变量

固定数据只扫 Y 窗口（`ratio = data_span / y_span`，同一条曲线、同样的
显示点数，纯 repaint 计时）：

| ratio | 0.05 | 0.43 | 0.68 | 0.94 | **1.00** | 1.04 | 1.14 | 1.27 | 2.40 | 4.00 | 9.82 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 拖动 p50 (ms) | 9.7 | 3.9 | 50.5 | 100 | **106** | 109 | 57.5 | 3.6 | 3.7 | 4.0 | 3.9 |
| 现 wall 守卫 | n | n | n | n | n | n | n | n | n | n | Y |

成本 ≈ **每帧要画的竖直墨水像素总长**（笔画根数 × 每根的可见高度）。
昂贵带在 0.5 ≲ ratio ≲ 1.2，**峰值精确落在 ratio=1.0，即 Y 自适应的
定义输出**；越过 ~1.27 后曲线被视口裁掉，成本塌回 4 ms。

### 1.2 三道现有防线为什么全漏

| 防线 | 触发条件 | 为什么漏 |
|---|---|---|
| 通用 wall 守卫（`_is_y_overflow_wall`, K=4.0） | `data_span/y_span > 4` | 方向反了：守「数据溢出窗口」，峰值在「数据刚好填满」（ratio≈1），且 ratio>4 区间实测已只有 4 ms |
| subplot 密集分桶帽（`_SUBPLOT_DENSE_*`） | ≥2 条密集通道 | 单通道拿不到降桶；实测 6ch（866 点/行）反而比 1ch（3104 点/行）快 |
| dense_discrete 光栅缓存 | 整数小值域（unique≤512） | 模拟量信号 `strategy=general`、`approx_unique=8192`，永远进不来 |

### 1.3 AA 闸门的指标失效

`_idle_aa_density_ok` / `_export_aa_affordable` 用**显示点数**做代理，
隐含「AA 成本 ≈ 点数 × 常数」。实测该"常数"浮动 15 倍：

| 场景 | 点数 | AA-off 帧 | AA-on 帧 | 放大倍数 |
|---|---|---|---|---|
| 1ch 平滑（对照） | 3104 | 3.8 ms | 240 ms | 63× |
| 6ch 满屏振荡 | 866/行 | 35 ms | 3.6 s | 102× |
| 1ch 满屏振荡 + Y fit | 3104 | 67 ms | **63 s** | **934×** |

点数在「墨水长度」这个维度上是盲的，修阈值救不了，必须换指标。

## 2. 设计目标（用户约束的转译）

1. **最坏情况有界**：任何单帧不得超过预算——包括预测失误的那一帧
   （不能用「先试一帧 AA 再决定」，因为第一帧就是 124 s）。
2. **不能因为怕卡就永久关闭**：高成本形态也必须有一条「变平滑」的
   升级路径，只是不能走向量 AA。
3. **系统性**：一个物理量管所有决策点，未来的未知形态由实测兜底
   接住，而不是每次再加一个特判。

## 3. 统一指标：墨水量 ink

### 3.1 定义

对 envelope 输出（min/max 时序对）逐线计算：

```
ink_dev_px = Σ_i  min(|Δy_i|, y_span) / y_span × row_height_px × dpr
```

即这条线本帧真正要画的**竖直墨水长度（设备像素）**。`Δy` 取
`np.diff(env_s)`（NaN 段用掩码跳过，保持断线语义）；水平分量
≈ pixel_width，相对可忽略。计算点在 `_refresh_visible_data` 内
envelope 之后——min/max 已在手，O(显示点数) 一次 `diff`，**近零成本**
（现 wall 守卫在同位置已有同量级的 min/max 读取）。

每线的 `y_span` 取**它自己所属 axis** 的当前 ylim（subplot 各行独立；
overlay 共享绘制矩形，逐线算完求和）。

### 3.2 实测验证（该指标必须能线性预测成本，否则不采用）

| 场景 | ink（逻辑 px） | AA-off 帧 | 向量 AA 帧 | 非 AA 光栅 build |
|---|---|---|---|---|
| 1ch 平滑 | 72.7k | 3.8 ms | 240 ms | 2.3 ms |
| 6ch 振荡（行高 120） | 306k/行 | 35 ms | 3.6 s | 6.3 ms/行 |
| 1ch 振荡 + Y fit | **2042k** | 67 ms | **63 s** | **43.4 ms** |

- AA-off 成本 ≈ **33 ns/逻辑px**（dpr=2）。独立交叉验证：按此模型预测
  「降桶至 350 → ink≈461k → 15.2 ms」，与独立实测的 17.0 ms 吻合；
  分桶扫描 1550/1200/800/500/350 桶 → 64/51/35/23/17 ms，线性成立。
- 三类场景在 ink 轴上分得开（72.7k vs 306k vs 2042k），有充分的
  判决余量。
- 现有三道防线全部退化为 ink 超预算的特例；ratio≈1.0 盲区自动覆盖，
  因为 ink 在那里恰好最大。

### 3.3 一个关键的语义改进

ratio 指标区分不了「贴合窗口的平滑曲线」（必须保满分辨率）和「贴合
窗口的实心色带」（降桶无视觉损失）——这正是现契约用例
`test_fitting_window_full_resolution_no_cap` 想保护的东西和本 bug 的
冲突点。**ink 天然区分两者**：平滑贴合 72.7k（不触发），振荡贴合
2042k（触发）。所以旧契约不必推翻，只需按 ink 分裂成两条：低 ink
贴合保满分辨率（原语义保留），高 ink 贴合降桶（新增）。

## 4. 机制：三个消费者 + 一道实测兜底

### 4.1 交互路径（AA-off）：ink 驱动降桶（替换 wall 守卫触发条件）

`_refresh_visible_data` 中，envelope 生成后算 ink；
`ink > INK_OFF_BUDGET` 时按线性比例降桶重算一次（复用现 wall 守卫的
「二次 `positions_envelope`」模式，只在超预算时付费）：

```
capped_width = clamp(int(width × INK_OFF_BUDGET / ink),
                     _INK_MIN_BUCKETS, width)
```

- `_is_y_overflow_wall` / `_WALL_OVERFLOW_RATIO_K` / `_WALL_BUCKET_BUDGET`
  及 `_line_wall_state` / `_y_overflow_wall_active` 被 ink 版本
  （`_line_ink_state` / `_frame_ink_high`）**取代并删除**——保留两套
  只会留下第二真相源。
- per-line 缓存命中帧沿用现 wall 模式：range-key 命中时读上次的
  ink 状态，不重算（y_key 已在 range key 里，纯 Y 变化会失效缓存）。
- subplot 密集帽（≥2 通道）与 overlay 通道数帽**保留不动**——它们管
  的是"多行合计"预算，与单行 ink 正交，且已有各自的实测契约。

预期效果（按 §3.2 线性模型 + 实测锚点）：ratio 1.0 的拖动帧
106 ms → ~20 ms；settle 帧 128 ms → ~25 ms。

### 4.2 向量 AA 闸门：按 ink 判（含导出路径）

`_idle_aa_density_ok` 在现有判序里**新增一道 ink 闸**（不动现有点数
双阈值——它管的"点太多"仍是真约束，两者是 AND 关系）：

- 帧 ink 合计（只累加将走原生向量路径的线，光栅覆盖的线不计入）
  `> INK_AA_OFF` → 拒绝 AA；`< INK_AA_ON` 才允许（双阈值滞回，
  防边界振荡）。
- `_export_aa_affordable` 加同一判据 → 修复复制/保存图片的冻结。

### 4.3 高 ink 的升级路径：光栅缓存准入扩展（「不能一直关」的答案）

dense_raster 的偏移多遍非 AA build 就是现成的「平滑但成本有界」通道：
同一几何 **43 ms vs 向量 AA 124 s**，成本上界 ≈ 常数× 非 AA 帧，
线性于 ink，永不爆炸。

- 准入从「`strategy == dense_discrete`」扩展为共享谓词
  `_raster_backend_eligible(ck)` ＝ dense_discrete **或**该线 ink 高
  （带进入/退出滞回，防光栅↔向量在边界抖动）。谓词落一处，
  以下消费者全部改走它：`dense_raster._dense_visible_keys` /
  `refresh_all`、renderer 的 interactive 跳过路径与
  `update_channel` 调用、`quality._raster_covered_curve_items` /
  `_high_raster_cost_status`。
- 绿/黄/红状态机、挂起/重建计时器、pen 抑制、日志语义全部复用；
  质量点 tooltip 文案不变（"高分辨率缓存"对用户语义相同）。
- **内存帽必须调整**：1ch 整行 1600×950@dpr2 的图是 **18.9 MiB，
  超过现 `DEFAULT_MAX_ITEM_BYTES = 16 MiB`**，不调则这条路对最需要
  它的场景直接拒收。依据「subplot 行平铺视口 → 全部行的图合计
  ≈ 视口设备像素 × 4B」（1920×1080@dpr2 ≈ 33 MiB）：
  `DEFAULT_MAX_ITEM_BYTES` 16→**36 MiB**，`DEFAULT_MAX_GLOBAL_BYTES`
  64→**96 MiB**（容纳 build 期 QImage+QPixmap 2× 峰值）。
  被拒时行为不变：留在原生非 AA（红点），不是回退向量 AA。

### 4.4 实测兜底：帧时计量 + 签名闩锁（接住未来的未知形态）

以上都是预测。给时域画布 viewport 装**常驻轻量 paint 计时**
（`_perf_probe.install_paint_probe` 的 `__class__` swap 已验证可行，
常态开销两次 `perf_counter`）：

- AA 升级后的首帧 > `BACKSTOP_FIRST_AA_MS`，或后续 AA 帧 EMA >
  `BACKSTOP_STEADY_AA_MS` → 立即 `disable_interactive_quality()` 并把
  当前**视图签名**（quantized xlim + y_key + 通道集指纹 + pixel_width）
  记入有界黑名单（LRU，上限 32 条）。
- 同一签名不再重试 AA；签名变化（用户缩放/换通道/改窗口）即自动
  重新武装。**同一状态最多付一次坏帧**，且不会永久锁死。

### 4.5 最坏情况核算

| 失败模式 | 被谁接住 | 上界 |
|---|---|---|
| 已知高 ink 几何交互 | §4.1 降桶 | ~20-25 ms/帧 |
| 已知高 ink 几何的平滑度 | §4.3 光栅 build（settle 后台语义、generation 可取消） | ~50 ms/行，一次性 |
| 预测失误的未知几何 | §4.4 闩锁 | 一次坏帧/签名，随后光栅路径接管 |
| 光栅被内存帽拒收 | 原生非 AA + 红点 | 交互帧仍被 §4.1 兜住 |

没有任何路径能反复进入秒级帧。

## 5. 常量（起始值，实施时按 §7 方法标定后固化）

ink 一律以**设备像素**计（`× dpr`），跨机器可比：

| 常量 | 起始值 | 依据 |
|---|---|---|
| `INK_OFF_BUDGET` | 1.2M dev px | ≈20 ms 交互帧（33 ns/逻辑px @dpr2 → ~16.5 ns/dev px） |
| `_INK_MIN_BUCKETS` | 350 | 沿用 `_SUBPLOT_DENSE_MIN_BUCKETS` 的轮廓保真下限；实测 350 桶=17 ms |
| `INK_AA_ON` / `INK_AA_OFF` | 200k / 300k dev px | 平滑对照 145k dev（AA 240 ms，今日可接受行为，必须继续放行）；6ch 振荡 612k/行、1ch 振荡 4.1M（必须拦） |
| 光栅准入 进入/退出 | 与 `INK_AA_OFF` / `INK_AA_ON` 同值 | AA 拒绝的线正是需要光栅升级的线，同一边界防抖 |
| `BACKSTOP_FIRST_AA_MS` | 1000 | 平滑对照首帧 474 ms（含 cache 构建）必须放行；1 s 以上属于事故 |
| `BACKSTOP_STEADY_AA_MS` | 250（EMA） | 平滑对照稳态 240 ms 恰好放行；持续高于此值说明预测失效 |

## 6. 范围外 + 放弃的替代方案

- **范围外**：FFT/order line_canvas（独立 AA 预算体系）、heatmap、批处理
  Qt 渲染（离线、无交互帧约束）。overlay 只换 AA 闸门指标，分桶帽保留。
- **OpenGL viewport**：pyqtgraph 该路径质量/兼容性差，macOS 已弃用
  OpenGL，不进。
- **纯反应式（先试一帧 AA 再决定）**：第一帧即 124 s，违反目标 1。
- **对高密度永久关 AA / 调低点数阈值**：违反目标 2，且 §1.3 证明点数
  轴上根本没有能分开 63× 与 934× 的阈值。
- **Y-clip 显示裁剪**：2026-06-22 设计已实测无效（在屏笔画本来就是
  满高，Qt 已裁掉屏外段），不复议。

## 7. 验证与契约

1. **每个新常量做变异测试**（改常量 → 对应用例变红 → 还原），证据
   固化为守卫用例——沿用 render-parity 的流程惯例。
2. 复现脚本收编为 `scripts/probe_aa_ink_budget.py`（Y 扫描 / 分桶扫描 /
   AA 帧计量 / 光栅 build 计量四合一），真机 Cocoa 跑，验收线：
   - ratio 扫描全带（含 1.0）拖动 p50 ≤ 30 ms；
   - 高 ink 场景空闲升级走光栅，向量 AA 不触发；升级总耗时 ≤ 500 ms；
   - 平滑对照组各指标不劣于本文基线（72.7k ink 场景 AA 照常开启）；
   - `scripts/benchmark_timedomain_interaction.py --assert-standards`
     现有门禁全绿（COCOA_LIMITS_MS 不放宽）。
3. **现存契约用例的处置**（见 §3.3）：
   - `TestWallGuard` 系列（`_is_y_overflow_wall` 纯函数用例 +
     `test_narrow_y_caps_points_and_flags_wall` 等端到端）→ 改写为
     ink 语义（窄 Y 下 ink 仍高 → 仍降桶仍关 AA，行为不回退；
     平线 ink≈0 → 永不触发，语义保留）。
   - `test_fitting_window_full_resolution_no_cap` → 分裂：低 ink 贴合
     保满分辨率（fixture 本来就是平滑正弦，原用例基本原样保留）+
     新增高 ink 贴合降桶用例。
   - `tests/ui/test_pg_canvas_backref_invariants.py` 中涉及
     `_y_overflow_wall_active` / wall 委托名的清单同步改名。
4. Windows 真机（RC 打包等价环境）复标定 §5 常量后方可进 release——
   33 ns/px 是 Cocoa dpr2 的系数，Windows dpr1 另测。
