# 时域 AA 墨水量预算实施计划

**设计**：`docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md`
（先读 spec，本文只写执行序，不复述依据）。

**Goal:** 满屏振荡曲线在 Y 自适应后，拖动/缩放帧 ≤30 ms，空闲平滑升级
走光栅缓存（≤500 ms 一次性），向量 AA 永不进入秒级帧；平滑曲线行为不变。

**Architecture:** 数据流不变（channel_data → positions_envelope →
PlotDataItem.setData / dense_raster）。新增一个纯函数 ink 指标 +
canvas 持有的 per-line ink 状态，替换 wall 守卫触发条件、并联进 AA
闸门、扩展 dense_raster 准入，最后加 paint 计时兜底。

**Tech Stack:** Python 3.12，PyQt5，pyqtgraph，numpy，pytest-qt，
仓库 venv `.venv/bin/python`；Qt 用例 `TMPDIR=/tmp
QT_QPA_PLATFORM=offscreen PYTHONPATH=.`；**性能验收必须真机 Cocoa**
（offscreen 只当排版草稿——CLAUDE.md Gotchas）。

**基线纪律：** 动手前先跑
`.venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py -q`
记录当前失败数（2026-08-08 主体基线 3 failed / 5124 passed，见
CLAUDE.md），别把既有红算到本改动头上。

---

## File Structure

- Modify `mf4_analyzer/render_profile.py` — 新增纯函数
  `envelope_ink_dev_px()`（UI-neutral，禁 PyQt import）。
- Modify `mf4_analyzer/ui/pg_canvas/renderer.py` — ink 计算与降桶；
  删除 `_is_y_overflow_wall` / `_wall_capped_width` /
  `_WALL_OVERFLOW_RATIO_K` / `_WALL_BUCKET_BUDGET`；新常量。
- Modify `mf4_analyzer/ui/pg_canvas/canvas.py` — `_line_ink_state` /
  `_frame_ink_high` 状态、`_raster_backend_eligible()` 谓词、
  paint 计时与 AA 签名闩锁状态。
- Modify `mf4_analyzer/ui/pg_canvas/quality.py` — AA 闸门 ink 判据 +
  闩锁检查 + `_export_aa_affordable`。
- Modify `mf4_analyzer/ui/pg_canvas/dense_raster.py` — 准入谓词接线、
  内存帽 16→36 MiB / 64→96 MiB。
- Add `scripts/probe_aa_ink_budget.py` — 四合一真机探针（Y 扫描 /
  分桶扫描 / AA 帧 / 光栅 build）。
- Modify `tests/ui/test_pg_timedomain_canvas.py`、
  `tests/ui/test_pg_canvas_backref_invariants.py`、
  `tests/ui/test_pg_dense_raster.py`（若无则建）。

每个 Task 内先写红测再实现（TDD）；只跑对应子目录，收尾 Task 7 跑全量。

---

### Task 0: 收编真机探针脚本

**Files:** Add `scripts/probe_aa_ink_budget.py`

- [ ] 把本次调查的四个 scratchpad 脚本合并为一个带子命令的探针：
  `--sweep-y`（ratio 0.05→9.8 扫描）、`--sweep-buckets`、`--aa-frame`
  （首帧/稳态 AA 计时）、`--raster-build`。合成信号、画布尺寸、输出
  列格式照抄本次调查（spec §1/§3 的表要能直接复跑出来）。
- [ ] 跑一遍，输出与 spec 基线数字同量级（±30%，机器态漂移可接受），
  结果存 `--json-out` 供 Task 7 对照。
- [ ] 脚本头注释写清「真机 Cocoa 跑，offscreen 数字无效」。

### Task 1: ink 纯函数

**Files:** Modify `mf4_analyzer/render_profile.py`；
Test `tests/ui/test_pg_timedomain_canvas.py`（新 `TestEnvelopeInk`）

- [x] 红测：
  - 平线 → 0；单点/空数组 → 0；`y_span<=0`（含 NaN/inf）→ 0（哨兵，
    与旧 `_is_y_overflow_wall` 的防御语义一致）；
  - NaN 段跳过且不传染（`[0, nan, 5]` 只计有限相邻对）；
  - 每步 `|Δy|` 被 clip 到 `y_span`（一根满高竖线贡献恰好
    `row_height×dpr`，不多计屏外部分）；
  - 线性：振幅×2（clip 内）→ ink×2；`dpr` ×2 → ink×2；
  - 锚点回归：spec §3.2 的合成振荡 envelope → ink ≈ 2042k×dpr（±5%）。
- [x] 实现 `envelope_ink_dev_px(env_s, y_span, row_height_px, dpr)`：
  掩码 diff + clip + sum，无循环。`tests/test_signal_no_gui_import.py`
  的投毒边界不涉及本模块，但保持 render_profile 无 PyQt import。
- [x] `pytest tests/ui/test_pg_timedomain_canvas.py -q -k Ink` 绿。

### Task 2: renderer 集成 —— ink 降桶取代 wall 守卫

**Files:** Modify `renderer.py`、`canvas.py`；
Test `test_pg_timedomain_canvas.py`、`test_pg_canvas_backref_invariants.py`

- [ ] 红测（改写 `TestWallGuard` → `TestInkBudget`，语义映射见 spec §7.3）：
  - 窄 Y（旧 wall 场景，ratio 100）：仍降桶、仍标高 ink —— 行为不回退；
  - **新增核心用例**：振荡数据 + `fit_y_to_visible_x()`（ratio≈1.0）→
    显示点数 ≤ `2×capped_width+4`、`_frame_ink_high is True`；
  - 平滑正弦 + Y 贴合 → 不降桶不标高（保留原
    `test_fitting_window_full_resolution_no_cap` 主体，fixture 本就
    平滑）；平线窄 Y → 永不触发（原语义保留）；
  - 缓存命中帧保持上次 ink 状态（照抄现 wall 的 cache-hit 用例结构）；
  - 变异测试固化：`INK_OFF_BUDGET` 调大 10× → 降桶用例红；
    `_INK_MIN_BUCKETS` 改 1 → 轮廓下限用例红（写成两条守卫用例，
    断言常量本身的数量级区间）。
- [ ] 实现：
  - `_refresh_visible_data` 中 envelope 后调 `envelope_ink_dev_px`
    （`row_height` 取该 axis viewbox sceneBoundingRect 高，`dpr` 取
    `_glw.devicePixelRatioF()`）；超 `INK_OFF_BUDGET` 按 spec §4.1
    公式二次 envelope（照抄现 wall 二次调用结构）；
  - 状态改名并**删除**旧面：`_line_wall_state`→`_line_ink_state`
    （存 `(ink_dev_px, high)`），`_y_overflow_wall_active`→
    `_frame_ink_high`；删 `_is_y_overflow_wall` / `_wall_capped_width` /
    两个 `_WALL_*` 常量及 renderer `_delegate_names` 对应项；
    backref invariants 清单同步。
  - subplot 密集帽 / overlay 帽调用序**一行不动**。
- [ ] `pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py -q` 与基线差 = 0 新红。

### Task 3: AA 闸门与导出

**Files:** Modify `quality.py`；Test `test_pg_timedomain_canvas.py`

- [ ] 红测：
  - 高 ink 帧 `_idle_aa_density_ok() is False`（复用 Task 2 的
    fit-Y 振荡 fixture；这是对 spec §1.3「三场景全 allow」的直接反转）；
  - 双阈值滞回：ink 从高降到 ON/OFF 之间不翻转，低于 ON 才放行；
  - `_export_aa_affordable` 高 ink → False（修导出冻结）；
  - 平滑对照（ink≈145k dev）→ 仍 allow（不许回归今日行为）；
  - 光栅覆盖的线不计入帧 ink 合计（覆盖后 AA 应可为其余低 ink 线开启）。
- [ ] 实现：`_idle_aa_density_ok` 在现 `_y_overflow_wall_active` 检查位
  换成 ink 判据（读 `_line_ink_state` 求和，排除 raster-covered），
  与现点数双阈值 AND；`_export_aa_affordable` 同判据。
- [ ] 子目录绿。

### Task 4: 光栅准入扩展 + 内存帽

**Files:** Modify `canvas.py`、`dense_raster.py`、`renderer.py`、
`quality.py`；Test `tests/ui/test_pg_dense_raster.py`

- [ ] 红测：
  - `_raster_backend_eligible`: dense_discrete → True；general+高 ink
    → True；general+低 ink → False；进入/退出滞回（边界来回不抖）；
  - 高 ink general 线 settle 后拿到 `DenseRasterEntry`、native pen 被
    抑制、质量点进入 dense-raster 绿态；ink 回落（Y 放宽）→ entry
    移除、pen 恢复（复用现 dense 用例结构）；
  - interactive 跳过路径对 ink 准入线同样生效（transform-only，
    held pan 零 setData——benchmark 的 `held_pan_setdata_count`
    契约不许破）；
  - 内存帽：1600×950@dpr2 整行（18.9 MiB）**必须被接受**；
    构造超 36 MiB 的假尺寸 → 拒收且回退原生非 AA（红点），
    不碰向量 AA；全局 96 MiB 峰值核算用例。
  - 变异测试：帽改回 16 MiB → 整行接受用例红。
- [ ] 实现：谓词放 canvas（读 `_channel_render_profiles` +
  `_line_ink_state`），spec §4.3 列出的五个消费者全部改走谓词；
  `DEFAULT_MAX_ITEM_BYTES = 36 MiB`、`DEFAULT_MAX_GLOBAL_BYTES = 96 MiB`
  （常量注释写平铺论证）。
- [ ] `pytest tests/ui/test_pg_dense_raster.py tests/ui/test_pg_timedomain_canvas.py -q` 绿。

### Task 5: 实测兜底（paint 计时 + 签名闩锁）

**Files:** Modify `canvas.py`、`quality.py`；
Test `test_pg_timedomain_canvas.py`

- [ ] 红测（计时源打桩，不依赖真实帧耗时）：
  - 首 AA 帧超 `BACKSTOP_FIRST_AA_MS` → AA 立即关、当前签名入黑名单、
    同签名 `try_enable_idle_quality` 不再开 AA；
  - 签名变化（改 xlim / 改通道集）→ 重新武装；
  - 黑名单 LRU 上限 32，第 33 条挤掉最旧；
  - 稳态 EMA 超 `BACKSTOP_STEADY_AA_MS` → 同处置；
  - 正常帧（桩值 5 ms）→ 永不闩锁（零行为变化）。
- [ ] 实现：常驻轻量版 `__class__` swap paint 计时（照
  `_perf_probe.install_paint_probe` 的实现要点，含幂等标记；
  `clear()`/重建画布时的 timer 世代纪律照抄 dense_raster 的
  sender-identity 模式）；签名 = quantized xlim key + y_key +
  通道集指纹 + pixel_width；闩锁检查挂在 `_idle_quality_allowed`。
- [ ] 子目录绿。

### Task 6: 真机验收（Cocoa）

**Files:** 无产品代码改动；跑 Task 0 探针

- [ ] `scripts/probe_aa_ink_budget.py --sweep-y`：全 ratio 带（含 1.0）
  拖动 p50 ≤ 30 ms；
- [ ] `--aa-frame`：振荡 + Y fit 场景向量 AA 不触发，空闲升级走光栅，
  升级总耗时 ≤ 500 ms；平滑对照 AA 照常开启、指标不劣于 spec 基线；
- [ ] 缩放（wheel-zoom settle 路径）p50 ≤ 30 ms（spec §1 的 127 ms 项）；
- [ ] `scripts/benchmark_timedomain_interaction.py --assert-standards`
  全绿（COCOA_LIMITS_MS 不放宽，`held_pan_setdata_count == 0` 契约在）；
- [ ] 若常量需微调：改 spec §5 表 + 对应守卫用例同步，一次 commit。

### Task 7: 收尾

- [ ] 全量：`--ignore=tests/acquisition_ui` 跑主体 + 单独跑
  `tests/acquisition_ui`（CLAUDE.md 交错 segfault 纪律），对照基线
  失败数，新红清零；
- [ ] `pytest -m slow` 里时域相关 perf 用例过一遍；
- [ ] spec 头部补「Implementation note (measured)」段：真机验收数字表
  （沿用 2026-06-22 spec 的先例格式）；
- [ ] `/update-hints` 检查：本改动无 UI 交互增删（质量点语义不变），
  预期不用动，确认后记录；
- [ ] Windows RC 打包等价环境复标定 §5 常量（`--hdf` 真数据 +
  probe 脚本），未复标定前本分支不进 release 包。

---

## 风险与回退

- **ink 二次 envelope 的额外成本**：只在超预算帧发生，且桶数已被降到
  ~几百，numpy 毫秒级；探针 `--sweep-buckets` 直接覆盖。
- **光栅↔向量抖动**：准入滞回 + AA 滞回同边界（spec §5），Task 4 有
  专用往返用例。
- **`__class__` swap 与画布重建**：幂等标记 + 世代检查；若 Task 5 在
  真机出现不可解释的崩溃/泄漏，兜底层可独立摘除（谓词、闸门、降桶
  不依赖它），其余四层已把已知形态全部覆盖。
- **回退单位**：每个 Task 一个独立 commit，任意层可单独 revert；
  Task 2 删除旧 wall 面是唯一破坏性步骤，其 commit message 需列出
  被删符号清单。
