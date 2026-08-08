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

- [ ] 新子命令构造 4 类 overlay 组合，逐类打印：每线 ink、帧 ink 合计、
  decimation ratio、旧门禁判定、ink 判定、**实测 AA 帧耗时**：
  - A 平滑宽带 ×2（高 ratio / 低 ink）→ 预期旧拦、ink 放行 = **假阳性**
  - B 满幅振荡 ×2，低采样率（低 ratio / 高 ink）→ 预期旧放行、ink 拦
    = **假阴性**
  - C 满幅振荡 ×2，高采样率（双高）→ 两者都拦
  - D 平滑低密度 ×2（双低）→ 两者都放行
- [ ] 真机 Cocoa 跑，JSON 落盘。**A 类的实测 AA 帧耗时是本任务的核心
  数据**：它必须证明「放开是安全的」，否则本任务应当中止而不是硬做。
- [ ] 验收前提：A 类 AA 帧 ≤ 300 ms（与 spec §5 的
  `_BACKSTOP_STEADY_AA_MS` 同量级）。**若 A 类实测超标 → 停止，把数据
  写回本计划并重新设计**（可能结论是：overlay 需要比 subplot 更严的
  ink 常量，而非直接复用）。

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
