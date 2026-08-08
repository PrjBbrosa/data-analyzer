# Overlay 密度门禁迁移到 ink 判据 —— 独立任务计划

**关联**：`docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md`
（ink 指标定义 §3、AA 闸门 §4.2、常量标定 §5）。本任务是该 spec §1.2
「三道防线」清点里**最后一条尚未迁移**的旧判据，独立于 `fix/aa-ink-budget`
的 Task 0–7 之外，故单开一个计划。

**建议分支**：`fix/overlay-density-ink`（从 `fix/aa-ink-budget` 合入 main
之后再起，避免与已完成工作的合并冲突）。

---

## 背景：为什么它还留着旧判据

`quality._overlay_density_pressure_status()`（[quality.py:768](../../../mf4_analyzer/ui/pg_canvas/quality.py)）
是 overlay 模式专用的 AA 拦截门，判据至今是**原始采样密度**：

```
源点数 / 像素宽 >= _SUBPLOT_DENSE_DECIMATION (8.0)   且这样的曲线 >= 2 条
```

它产出用户可见的红灯 tooltip「抗锯齿未激活：叠加高密度曲线达到性能门禁」。

`fix/aa-ink-budget` 分支**有意没动它**：那次治理的红线是「一个物理量管
所有决策点」，但 overlay 门禁的迁移会改变一个**独立的用户可见行为面**
（哪些叠加图能开 AA），把它混进同一批改动会让 ink 机制本身的验收失去
干净的对照。现已确认 ink 机制在 subplot / overlay 两侧都工作正常
（overlay 高 ink 帧走 `block_reason: "high-ink"` 分支），迁移条件成熟。

### 旧判据的两个盲区（与 spec §1.3 同源）

1. **假阳性（该开不开）**：两条 129.5 kHz 但**平滑**的宽带通道叠加，
   decimation ratio 远超 8 → 拦截。可它们的 ink 可能只有几十 k，AA
   完全负担得起。用户白白失去平滑曲线。
2. **假阴性（该关不关）**：两条采样率不高但**满幅振荡**的通道叠加
   （ratio < 8 → 不拦截），ink 却可能上百万。此时唯一兜住它的是
   `fix/aa-ink-budget` 新加的 ink 闸——**旧门禁在这里毫无贡献**，
   它的存在只剩假阳性成本。

即：这道门现在既拦错人、又漏真凶，而真凶已由 ink 闸拦下。

---

## 目标

用 ink 判据取代 overlay 密度门禁，使 overlay 与 subplot 在**同一个物理量、
同一组常量**上做 AA 决策；不得放宽任何已验收的性能门禁。

**非目标**（明确排除，避免范围蔓延）：
- 不动 `_effective_pixel_width` 的 overlay 分桶帽
  （`_OVERLAY_BUCKET_BUDGET_MULT` 那套）——那是**降桶**预算，与 AA
  **闸门**正交，且有自己的实测契约（2026-06-22 spec）。
- 不动 `_AA_OVERLAY_SEGMENT_ON/OFF` 点数双阈值——「点太多」仍是真实
  且正交的约束（spec §4.2 已论证 AND 关系）。
- 不动 subplot 侧任何判据。

---

## 关键风险：这是**放宽**方向的改动

与 Task 0–7 全是收紧不同，本任务会让**一部分今天被拦截的 overlay 图
重新获得 AA**（上述假阳性 1）。所以验收的重心不是「更快」，而是
**「放开之后没有任何一类 overlay 图掉进秒级帧」**。

必须在真机上把「被放开的那一类」实测一遍，而不是只测「继续被拦的」。

---

## 任务

### Task 1: 量化现状 —— 旧判据与 ink 判据的分歧集

**Files:** Modify `scripts/probe_aa_ink_budget.py`（加 `overlay-gate` 子命令）

- [x] 新子命令构造 4 类 overlay 组合，逐类打印：每线 ink、帧 ink 合计、
  decimation ratio、旧门禁判定、ink 判定、**实测 AA 帧耗时**：
  - A 平滑宽带 ×2（高 ratio / 低 ink）→ 预期旧拦、ink 放行 = **假阳性**
  - B 满幅振荡 ×2，低采样率（低 ratio / 高 ink）→ 预期旧放行、ink 拦
    = **假阴性**
  - C 满幅振荡 ×2，高采样率（双高）→ 两者都拦
  - D 平滑低密度 ×2（双低）→ 两者都放行
- [x] 真机 Cocoa 跑，JSON 落盘。**A 类的实测 AA 帧耗时是本任务的核心
  数据**：它必须证明「放开是安全的」，否则本任务应当中止而不是硬做。
- [x] 验收前提：A 类 AA 帧 ≤ 300 ms（与 spec §5 的
  `_BACKSTOP_STEADY_AA_MS` 同量级）。**若 A 类实测超标 → 停止，把数据
  写回本计划并重新设计**（可能结论是：overlay 需要比 subplot 更严的
  ink 常量，而非直接复用）。

#### 实测（2026-08-08，真机 Cocoa，dpr 2.0，画布 1600×950，overlay，每类 2 遍）

`scripts/probe_aa_ink_budget.py overlay-gate --repeats 2`。每类 2 条通道、
幅值 ±100，测前统一 `fit_y_to_visible_x()` + `_flush_pending_refresh()`
（ylim 一律 ±125，pixel_width 1511）。两遍差异见「一致性」列。

| 类 | 源点/线 | ratio | 每线 ink (dev px) | 帧 ink | 旧门禁 | ink 判定 | AA-off 帧 | AA-on 首帧 | AA-on 稳态 | 一致性 |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** 假阳性 | 1M @20 kHz，0.56/0.73 Hz 平滑 | 661.8 | 81.4k / 106.1k | **187.5k** | **拦** | **放行** | 4.5 ms | 204.1 / 205.4 ms | **203.5 / 204.5 ms** | 0.5% |
| **B** 假阴性 | 10k @200 Hz，97/94 Hz 满幅 | **6.6** | 3120.0k / 2992.5k | 6112.5k | **放行** | **拦** | 49.0 ms | 29812 / 29822 ms | 29810 / 29771 ms | 0.1% |
| **C** 双高 | 1M @20 kHz，2300/2437 Hz 满幅 | 661.8 | 3053.0k / 3266.6k | 6319.6k | 拦 | 拦 | 36.0 ms | 18560 / 18563 ms | 18559 / 18555 ms | 0.03% |
| **D** 双低 | 10k @200 Hz，0.56/0.73 Hz 平滑 | 6.6 | 81.4k / 106.1k | **187.4k** | 放行 | 放行 | 4.6 ms | 178.1 / 178.7 ms | 180.0 / 179.9 ms | 0.05% |
| A2 补充 | 1M @20 kHz，0.25/0.33 Hz 平滑 | 661.8 | 36.3k / 48.0k | 84.3k | 拦 | 放行 | 3.4 ms | 53.6 / 53.1 ms | 54.4 / 52.9 ms | 2.8% |

A / D / A2 的 AA 是**经门禁真实开启**的（模拟 Task 2 删除旧门禁后）；
B / C 门禁拒绝，AA 由探针强制打开，用来记录「被拦下的成本」。
10 次 run 全部 `window_exposed=True`、零 suspect、`aa_actually_on_during_frames=True`。
JSON：`overlay-gate-baseline.json`（探针 `--json-out`）。

**判决：go。** A 类稳态 AA 帧最大 **204.5 ms ≤ 300 ms**，两遍差 0.5%，
首帧 205.4 ms 也远低于 `_BACKSTOP_FIRST_AA_MS` (1000)。Task 2 按原设计实施。

**A vs D 是本次最强证据**：两者波形完全相同、帧 ink 几乎一致
（187.5k vs 187.4k）、AA 成本同量级（204 vs 179 ms），**唯一差别是源采样
点数**（1M vs 10k）——旧门禁却一个拦一个放。同样的真实成本、相反的判决，
这是「旧判据量错了轴」的直接实证，而不再只是推理。

**B 反过来印证假阴性**：它是全部五组里**最贵**的一组（29.8 s/帧，比 1M 点的
C 还贵 60%），而旧门禁**放行**它（ratio 6.6 < 8）。今天真正拦住 B 的是 ink 闸
（`block_reason: "high-ink"`），旧门禁在这里零贡献——与 §「旧判据的两个盲区」
的推断一致。A / A2 今天的 `block_reason` 正是待删的 `"overlay-density-pressure"`，
B / C 为 `"high-ink"`，Task 2 的 reason 契约前提成立。

**fixture 标定说明（与本计划初稿参数不同，必须记一笔）**：初稿给平滑组的
1.0 / 1.3 Hz **落不进预期象限**——实测帧 ink 334.2k，已超 `_INK_AA_OFF`
(300k)，ink 闸同样拒绝，即在那组参数下 A（假阳性）与 D（双低）都不存在。
ink 线性于**显示到的周期数**（f × 时长），故两组平滑信号一并降频到
0.56 / 0.73 Hz，使帧 ink 落在 `_INK_AA_ON` (200k) 正下方 ≈187k。这是**刻意
取放开区间的上边界**而非舒适区：迁移放开的正是帧 ink 通过闸门的那些 overlay，
它能交给用户的最贵 AA 帧就在带边上。A2（84.3k）是补充的带内点，用来给出
成本-ink 斜率（84.3k→53 ms，187.5k→204 ms，约 1.6 ns/dev px，与 spec §3.2
的量级一致），若判决为 no-go 可据此定 overlay 专属常量带。**没有为了让
A 类耗时达标而降 ink**：降频是象限定义强制的（334k 本就被 ink 闸拦下）。

**推翻计划背景里的一处措辞**：§「旧判据的两个盲区」说假阳性组「ink 可能只有
几十 k」。实测放开区间比这窄——上限就是 ink 闸本身（200k/300k dev px），
且带边（187k）的 AA 帧已到 204 ms。放开是安全的，但可放开的余地没有背景
段落暗示的那么宽。

**顺带观察到 spec §4.4 兜底闩锁在真实渲染下跳闸一次**（B 类第 2 遍：
`backstop_reason = ["first-aa-frame", 60209.1]`）——此前只在打桩用例里验证过。
**但这条证据有一处对不上，不要当成干净的确认**：同一遍里探针自己计的首个
AA 帧是 29821.9 ms，且 B 类的 AA 是**强制**打开的（探针刻意不调
`_open_aa_backstop_epoch`，以免计时中的帧被闩锁中途关掉），按设计
`_note_aa_frame` 应当因未 armed 直接返回。所以那个 60209 ms 帧不是探针计时的
两帧之一（数值≈两帧之和），arm 来源也未查明——最可能是 `processEvents()`
期间空闲计时器重入了 `try_enable_idle_quality`。两遍 B 的耗时差 <0.2%
（29812/29810 vs 29822/29771），所以**它没有污染本表任何数字**；但「闩锁在
真机生效」这一条要等 Task 3 用 A 类（经门禁真实开启、epoch 真实 armed 的
路径）复现后才算数。

### Task 2: 迁移判据

**Files:** Modify `mf4_analyzer/ui/pg_canvas/quality.py`；
Test `tests/ui/test_pg_timedomain_canvas.py`

- [ ] 红测先行：
  - A 类组合 → `_idle_aa_density_ok()` 为 True（今天是 False，这是**行为
    变更**，用例要写明这是有意放开并引用 Task 1 的实测数字）；
  - B 类 → False（由 ink 闸拦下，与旧门禁无关）；
  - C/D → 与今天一致（无行为变化）；
  - `quality_status()` 的 `block_reason` 在 overlay 高 ink 时为
    `"high-ink"`，且 `"overlay-density-pressure"` 这个 reason **不再产生**；
  - 导出路径 `_export_aa_affordable` 同步（它也调 pressure）。
- [ ] 实现：
  - `_overlay_density_pressure_status()` 及其两个调用点删除；
  - `quality_status()` 的 `pressure["blocked"]` 分支与 tooltip
    「抗锯齿未激活：叠加高密度曲线达到性能门禁」一并删除；
  - `_SUBPLOT_DENSE_DECIMATION` 在 quality.py 的 import 若因此零消费者
    则删除（renderer 侧的降桶用法保留不动）。
- [ ] **文档扇出**：该 tooltip 若出现在 `mf4_analyzer/help/` 或
  `docs/analyzer/user-guide/` 中，同步更新（先 `grep -rn "叠加高密度"`）。

### Task 3: 真机验收

- [ ] `probe_aa_ink_budget.py overlay-gate` 迁移前后对比：A 类放开后
  AA 帧 ≤300 ms；B/C 类仍被拦；D 类不变。
- [ ] `benchmark_timedomain_interaction.py --assert-standards` 全绿
  （COCOA_LIMITS_MS 不放宽）。
- [ ] 补一条 overlay 专项：6~8 条通道叠加 + Y 自适应，确认无秒级帧。
- [ ] **兜底闩锁余量核对（Task 1 实测暴露）**：A 类稳态 204.5 ms 距
  `_BACKSTOP_STEADY_AA_MS` (250) 只剩 45.5 ms（≈18%）。本机通过，但更慢的
  机器上 A 类会**例行触发 §4.4 闩锁**。行为仍安全（一个签名只付一次坏帧后
  闩住），但用户看到的是「AA 闪一下就关」。验收时要明确区分「AA 稳定开启」
  与「开了又被闩掉」，别把后者当通过；`overlay-gate` 的
  `backstop_reason` / `aa_engaged_via_gate` 字段就是这个判据。
- [ ] **Windows 复标定清单追加一项**（spec §7.4 至今未做）：dpr=1 的
  Windows 上重跑 `overlay-gate`，确认 A 类稳态仍 ≤300 ms **且**与
  `_BACKSTOP_STEADY_AA_MS` 留有余量。ink 以设备像素计，dpr 1 的帧 ink 约为
  本次的一半，但 ns/dev px 系数是 Cocoa 标的——两个方向都可能，必须实测，
  不得按比例外推。若 Windows 上 A 类逼近或越过 250 ms，结论回到「overlay
  需要更严的专属 ink 常量带」，即本计划「回退」段的分支。

### Task 4: 收尾

- [ ] 全量双段跑法（主体 `--ignore=tests/acquisition_ui` + 单独跑
  `tests/acquisition_ui`），对照基线零新红。
- [ ] spec §1.2 的「三道防线」表加一行迁移注记；本计划补实测数字。
- [ ] `/update-hints` 检查：本任务**确实删除了一种用户可见的红灯理由**，
  与 `fix/aa-ink-budget` 不同，需要确认 `ui/hints.py` / `ui/quickref.py`
  是否提及该门禁。

---

## 回退

单一 commit 即可回退（判据删除 + 用例）。若 Task 1 的 A 类实测不达标，
本任务**不应实施**——结论改为「overlay 保留一道更严的 ink 常量带」，
届时改本计划 Task 2 为「overlay 专用 ink 常量」而非「删除门禁」。
