# View 切换渲染质量结算实施计划

**设计**：`docs/analyzer/specs/2026-08-15-view-switch-quality-settlement-spec.md`
（先读 spec，本文只写执行序，不复述依据）。
**改前基线与探针**：`docs/analyzer/verify/2026-08-15-view-switch-quality-probes/`
（`main@380e5ac2`，真机 Cocoa）。

**Goal:** 切 View 是一次结算：几何全部恢复后只刷一遍、只判一次；回切到实测
便宜的 View 首帧即 AA；分析画布的 AA 帧离开切换调用、按 ink 判、按实测兜底。
不改交互路径的 150 ms 静默窗、不改时域 ink 常量、不改 `_view_signature`、
不放宽任何门禁。

**Architecture:** 时域侧新增两个画布入口（`restore_visible_xlim(flush=)` +
`settle_view_restore()`）和一个 QualityManager 入口（`settle_after_discrete_render()`
+ 有界 AA 首帧记忆），`_render_view_to_canvas` 改四行接线；把 backstop 状态机提成
`AaFrameLatch` 让 line / frf 画布复用；line / frf 加离散武装 + ink 闸门 + latch。

**Tech Stack:** Python 3.12，PyQt5，pyqtgraph，numpy，pytest-qt，仓库 venv
`.venv/bin/python`；Qt 用例 `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`；
**性能与视觉验收必须真机 Cocoa**（offscreen 只当逻辑草稿——CLAUDE.md Gotchas）。

**基线纪律：** 动手前先跑
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_pg_line_canvas.py tests/ui/test_frf_canvas.py tests/ui/test_view_switch_integration.py
```
记下失败数（CLAUDE.md 2026-08-15 基线：主体 6978 passed / 9 failed 均为顺序污染，
子集单跑应全绿）。别把既有红算到本改动头上。

**并行执行提示：** 若用 worktree agent 分 Task，prompt 里写死期望 HEAD 并要求
`git merge --ff-only` 补齐，venv 用**绝对路径** `<repo>/.venv/bin/python`
（`.venv` 不在 worktree 里）。Task 1 / 2 可并行（不同文件），Task 3 依赖 1+2，
Task 5 / 6 依赖 2 + 4，Task 4 只依赖 Task 0。

---

## File Structure

- Modify `mf4_analyzer/ui/pg_canvas/canvas.py` — `restore_visible_xlim(xlim, *, flush=True)`、
  `_restore_primary_xlim(xlim, *, flush=True)`、新增 `settle_view_restore()`。
- Modify `mf4_analyzer/ui/main_window/_view_mixin.py` — `_render_view_to_canvas`
  改用事务顺序（4 行）。
- Add `mf4_analyzer/ui/pg_canvas/quality_backstop.py` — `AaFrameLatch`
  （epoch / 首帧-稳态 EMA / 黑名单 LRU / 首帧 memo LRU；纯 Python，无 Qt import）。
- Modify `mf4_analyzer/ui/pg_canvas/quality.py` — 委托 latch（六个属性以 property
  保留）、`install_frame_paint_timer` owner 协议放宽、新增 `discrete_timer` /
  `aa_frame_memo` / `settle_after_discrete_render()` / `_SYNC_AA_MAX_MS` / `_AA_MEMO_MAX`。
- Modify `mf4_analyzer/ui/pg_canvas/line_canvas.py` — 离散武装、谱行/预览行 ink
  闸门、latch + paint 计时器、`quality_status()` 新理由分支、常量
  `_SPECTRUM_INK_AA_ON/OFF`。
- Modify `mf4_analyzer/ui/pg_canvas/frf_canvas.py` — 同上（三行 ink 求和）。
- Add `scripts/probe_view_switch_quality.py` — verify 目录六个探针合并为带子命令的
  正式探针（`--json-out`）。
- Modify `docs/analyzer/verify/2026-08-15-view-switch-quality-probes/README.md` —
  改后读数表；`probes/` 保留为历史快照并注明已被 `scripts/` 版本取代。
- Modify tests：`tests/ui/test_pg_timedomain_canvas.py`、
  `tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_view_switch_integration.py`、
  `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_frf_canvas.py`；
  Add `tests/ui/test_pg_quality_backstop.py`（latch 纯逻辑）。

每个 Task 先写红测再实现（TDD）；只跑对应文件，收尾 Task 8 跑全量两条命令。

---

### Task 0: 探针收编为正式脚本 + 复核基线

**Files:** Add `scripts/probe_view_switch_quality.py`；Modify verify README。

- [ ] 把 `verify/…/probes/` 六个脚本合并为一个 argparse 探针，子命令：
  `time-mainwindow`（产品路径四场景）、`time-canvas`（画布级两后端）、
  `ylim-order`（A/B）、`stale-ink`（三后果）、`analysis-frames`（谱行 ink vs 帧 +
  FRF）、`spectrum-switch`（`plot_spectra` 切换调用）。合成信号、画布尺寸、输出列
  照抄（spec §1 各表要能直接复跑出来）；统一 `--json-out`；docstring 写清
  「真机 Cocoa 跑，offscreen 数字无效」；`_settle` / `_wait_exposed` 复用
  `scripts/probe_aa_ink_budget.py` 的写法（曝光等待 + 可疑帧标记）。
- [ ] 用新脚本各跑一遍，数字与 verify `results/` 同量级（±30%），确认没抄错。
- [ ] verify README 加一行：正式入口已迁到 `scripts/`，`probes/` 是当时快照。

**Done:** 六个子命令跑通；README 更新。

---

### Task 1: 时域 View 恢复事务

**Files:** `canvas.py`、`_view_mixin.py`、`tests/ui/test_pg_timedomain_canvas.py`、
`tests/ui/test_view_switch_integration.py`。

- [ ] 红测 `TestViewRestoreSettlement`（新 class）：
  1. `test_settle_measures_ink_at_final_geometry`：真机无关，offscreen 可跑。
     A 组：`plot_channels(defer=False)` + `restore_visible_xlim` + flush → 记
     `_line_ink_state` / 绘点 / `_idle_aa_density_ok()` / `_ink_raster_admitted`；
     B 组：`plot_channels(defer=True)` + `restore_visible_xlim(flush=False)` +
     `restore_visible_ylims(A 组 ylims)` + `settle_view_restore()`。断言 B 的
     ink 与 A 相等（±5%）、绘点相等、AA 判定相同、光栅收编集相同。
     用 spec §1.2 的 overlay 2ch/1M/0.5 Hz 构形（改前会看到 2.66M vs 36k）。
  2. `test_settle_refreshes_exactly_once`：monkeypatch 计数 `_refresh_visible_data`；
     整段事务恰好 1 次；`xlim=None` 首访路径 0 次。
  3. `test_restore_xlim_flush_false_marks_pending_and_default_unchanged`：
     `flush=False` 不调 `_flush_pending_refresh` 且 `_refresh_pending is True`；
     默认参数行为与改前逐字节相同（既有用例即是守卫）。
  4. `test_settle_without_pending_is_noop`：无 pending 时不刷、不调度光栅
     （`has_dense_candidates()` False 时）。
- [ ] 实现 `canvas.py`：`restore_visible_xlim(xlim, *, flush=True)` →
  `_restore_primary_xlim(xlim, flush=flush)`；`flush=False` 分支把同步 flush 换成
  `self._refresh_pending = True`；新增 `settle_view_restore()`（spec §3.1 骨架，
  **flush 在前、`_quality.settle_after_discrete_render()` 在后**——Task 3 前先调
  `schedule_idle_quality()` 占位，Task 3 替换）。
- [ ] 实现 `_view_mixin._render_view_to_canvas`：`restore_visible_xlim(state.xlim, flush=False)`
  → `restore_visible_ylims` → `set_tick_density` → `canvas.settle_view_restore()`；
  放在 `try` 内 `set_tick_density` 之后。副栏（split）同一函数自然覆盖。
- [ ] 红测 `test_view_switch_integration.py::test_overlay_round_trip_keeps_ink_and_buckets`：
  MainWindow + `_register_file_data` 装 2ch 1M（照 verify 探针），overlay，
  两 View 各设 xlim，来回切两轮；断言回切后 `quality_status().get("block_reason") != "high-ink"`、
  绘点 == 首访、`_ink_raster_admitted` 为空。跑之前确认该文件里没有断言
  「切换后必须黄点」的用例（有则按 spec §7 改成「非 high-ink 红」）。
- [ ] `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_pg_timedomain_canvas.py tests/ui/test_view_switch_integration.py`

**Done:** 四条新测 + 集成测绿；既有用例失败数不增。

---

### Task 2: 提取 `AaFrameLatch`

**Files:** Add `quality_backstop.py`；Modify `quality.py`；Add
`tests/ui/test_pg_quality_backstop.py`；`test_pg_canvas_backref_invariants.py`。

- [ ] 红测 `test_pg_quality_backstop.py`（纯逻辑，无 Qt）：`open(sig)` 后
  `note_frame(1200)` 首帧 → 返回 `("first-aa-frame", 1200)` 且 `blocked(sig)`；
  首帧 100 后 `note_frame(300)` → EMA 200 不跳、再 `note_frame(600)` → 400 跳
  `steady-aa-ema`；`close()` 后 `note_frame` 返回 None；黑名单 LRU 上限与
  `move_to_end`；首帧 memo：`note_frame` 首帧写 `memo[key]`、跳闸删 memo、
  LRU 上限；`open` 时的 epoch 递增可读。
- [ ] 实现 `AaFrameLatch(first_ms, steady_ms, ema_alpha, max_entries)`：状态
  `epoch / frames / ema / signature / blacklist(OrderedDict) / memo(OrderedDict)`；
  方法 `open(signature, memo_key=None)`、`close()`、`note_frame(ms) -> tuple|None`、
  `blocked(signature) -> bool`（含 `move_to_end`）、`memo_lookup(key)`、
  `reason`。**不 import PyQt5**（可被 `test_signal_no_gui_import` 风格的守卫扫）。
- [ ] `QualityManager` 委托：`self.latch = AaFrameLatch(_BACKSTOP_FIRST_AA_MS, …)`；
  `aa_backstop_epoch / aa_epoch_frames / aa_frame_ema / aa_backstop_signature /
  aa_backstop_reason / aa_backstop_blacklist` 六个名字改为 property 读写
  latch；`_open_aa_backstop_epoch` / `_close_aa_backstop_epoch` / `_note_aa_frame` /
  `_trip_aa_backstop` / `_aa_backstop_blocked` 改为调 latch，跳闸后仍由 manager
  做「延迟 0 ms 关 AA + epoch 校验」（Qt 部分留在 manager）。
- [ ] `install_frame_paint_timer`：paint 计时器改调 `owner._note_aa_frame(frame_ms)`
  （若 owner 有该方法），否则回退 `owner._quality._note_aa_frame`；时域画布加
  一行转发 `_note_aa_frame = lambda… `**不许 lambda**——写成 bound method。
- [ ] `_owned_names` 加 `latch`；`test_pg_canvas_backref_invariants` 写穿白名单
  **不变**（`_aa_backstop_armed` 仍是唯一写穿）。
- [ ] `TestAaBackstopLatch` **一行不改**照过；
  `test_frame_paint_backstop_is_installed_on_real_canvas` 照过。
- [ ] `… -m pytest -q tests/ui/test_pg_quality_backstop.py tests/ui/test_pg_timedomain_canvas.py -k "Backstop or paint" tests/ui/test_pg_canvas_backref_invariants.py`

**Done:** latch 单测绿；既有 backstop 用例零改动零红。

---

### Task 3: 离散渲染结算 + AA 首帧记忆

**Files:** `quality.py`、`canvas.py`（`settle_view_restore` 换调用）、
`tests/ui/test_pg_timedomain_canvas.py`、`test_pg_canvas_backref_invariants.py`。

- [ ] 红测 `TestDiscreteSettle`：
  1. `test_memo_hit_enables_aa_synchronously`：预置 `latch.memo[(sig, dpr)] = 12.0`
     → `settle_after_discrete_render()` 后 `aa_on is True`、`timer.isActive() is False`、
     `discrete_timer.isActive() is False`。
  2. `test_blacklisted_signature_arms_nothing`：黑名单命中 → 两计时器皆不激活、
     `aa_on False`、状态已发射。
  3. `test_unknown_signature_arms_zero_delay_timer_and_keeps_interval`：
     `discrete_timer.isActive()`、`discrete_timer.interval() == 0`、
     **`timer.interval() == 150`**（QTimer.start(int) 陷阱守卫）；处理事件后
     `aa_on` 按闸门结果。
  4. `test_locally_busy_falls_back_to_quiet_window`：`_interaction_depth=1` →
     `timer.isActive()`（150）。
  5. `test_memo_written_on_first_aa_frame_and_removed_on_trip`：`_note_aa_frame(20)`
     写 memo；`_note_aa_frame(1500)`（新 epoch 首帧）→ memo 删、黑名单加。
  6. `test_memo_key_includes_dpr`、`test_memo_survives_reset_for_rebuild`、
     `test_memo_bounded_lru`。
  7. `test_reset_and_disable_stop_discrete_timer`。
- [ ] 实现：常量 `_SYNC_AA_MAX_MS = 50.0`、`_AA_MEMO_MAX = _BACKSTOP_BLACKLIST_MAX`
  （放 backstop 常量段，注释写清是标定值、复测脚本、为什么比较首帧）；
  `self.discrete_timer = QTimer(canvas)` 单发、`timeout → try_enable_idle_quality`；
  `_owned_names` 加 `discrete_timer`；`_aa_memo_key()` = `(self._view_signature(), round(dpr, 2))`
  或 None；`_note_aa_frame` 首帧分支写 memo（经 latch）；
  `settle_after_discrete_render()` 按 spec §3.2；`reset_for_rebuild` /
  `disable_interactive_quality` 同时 stop `discrete_timer`。
- [ ] `canvas.settle_view_restore()` 把 Task 1 的占位换成
  `self._quality.settle_after_discrete_render()`。
- [ ] `… -m pytest -q tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_view_switch_integration.py`

**Done:** 七条新测绿；`timer.interval()==150` 有守卫。

---

### Task 4: 真机标定分析画布 ink 带（Cocoa）

**Files:** `scripts/probe_view_switch_quality.py`（`analysis-frames` 子命令扩展）；
spec §5 表回填。

- [ ] `analysis-frames` 扩成扫描：谱行固定 3 曲线、峰/底 ∈ {∞(纯噪声), 50, 20,
  10, 5, 2, 1}，每档报 `ink` 与 AA 帧中位；预览行同样扫（叠加 2/3/4 条时域
  包络、Y 拉窄到填满）；FRF 三行扫 bins ∈ {1k, 2k, 4k} × {干净, 噪声相位, 噪声
  相干}。输出 ink→ms 散点与线性拟合斜率。
- [ ] 取 **OFF = 拟合到 250 ms（`_BACKSTOP_STEADY_AA_MS`）的 ink**、ON = OFF×2/3
  （与时域 200k/300k 同比例）。预览行若斜率与时域带偏差 ≤2× 则复用
  `_INK_AA_ON/OFF`，否则单列。
- [ ] 数字回填 spec §5（把「暂定」改成实测值 + 日期 + 机器），JSON 存
  verify `results/analysis-ink-calibration.json`。

**Done:** spec §5 三行常量有实测依据；JSON 入库。

---

### Task 5: `PgLineCanvas` — 离散武装 + ink 闸门 + latch

**Files:** `line_canvas.py`、`tests/ui/test_pg_line_canvas.py`。

- [ ] 红测：
  1. `test_plot_spectra_returns_with_aa_off_and_discrete_timer_armed`：调用返回时
     `_amp_curves` / `_time_curves` 全 `antialias False`、`_aa_on False`、
     `_discrete_aa_timer.isActive()`、`_aa_idle_timer.interval() == 150`。
  2. `test_spectrum_ink_gate_blocks_noise_floor_and_allows_peaks`：合成
     纯噪声底 3 曲线（ink > OFF）→ 处理事件后 AA 仍 off、
     `quality_status()["block_reason"] == "high-ink"`、tooltip 含「谱线填满」；
     峰主导（ink < ON）→ AA on、green。**用例里先 `vb.updateAutoRange()` 再读**。
  3. `test_point_budget_leg_still_ands`：6 曲线（>8000 点）→ 拒，理由仍是点数。
  4. `test_time_preview_ink_gate`：预览行同法。
  5. `test_backstop_trips_and_blacklists_spectrum_signature`：
     `_note_aa_frame(1500)` → 延迟关 AA、`_latch.blocked(sig)`、再武装被拒。
  6. `test_interactive_path_unchanged`：`_on_interactive_range_changed` 仍走
     150 ms 计时器。
- [ ] 实现：`_discrete_aa_timer`（0 ms 单发，独立于 `_aa_idle_timer`）；
  `plot_spectra` / `plot_time_preview` / `_plot_time_preview_entries` 结尾
  `_aa_on=False` + `_discrete_aa_timer.start()`（删掉同步 `_apply_idle_curve_aa`
  分支）；`_spectrum_ink_total()` / `_time_preview_ink_total()`（读前
  `updateAutoRange()`）；`_spectrum_aa_allowed` / `_time_preview_aa_allowed`
  各 AND 一条 ink 迟滞腿（`_SPECTRUM_INK_AA_ON/OFF` 取 Task 4 值；预览行按
  Task 4 结论）；`_reset_spectrum_aa_density_gate` 同时重播种 ink 腿；
  `install_frame_paint_timer(self)` + `_note_aa_frame` → `AaFrameLatch`
  （首帧 1000 / 稳态 250 / α 0.5 / 32），跳闸 → 0 ms 延迟 `disable_interactive_quality`
  + epoch 校验；`_spectrum_view_signature()`；`quality_status()` 加 `high-ink`
  分支（措辞：谱行「谱线填满绘图区，绘制量超预算」/ 预览「波形填满绘图区」）。
- [ ] `… -m pytest -q tests/ui/test_pg_line_canvas.py tests/ui/test_fft_*.py`（后者
  若有断言「plot_spectra 后即 AA on」的用例，按 spec §7 改为「处理事件后」）。

**Done:** 六条新测绿；既有 line canvas 用例失败数不增。

---

### Task 6: `PgFrfCanvas` — 同 Task 5

**Files:** `frf_canvas.py`、`tests/ui/test_frf_canvas.py`。

- [ ] 红测（对应 Task 5 的 1/2/5/6）：`set_result` 返回时曲线 AA off +
  `_discrete_aa_timer` 激活；噪声相位 2k bins（ink > OFF）→ 拒 + 理由「相位翻转
  填满绘图区」；干净 2k → 开；`_note_aa_frame(1500)` → 拉黑；交互路径 150 不变。
- [ ] 实现：曲线构造改 `antialias=False`（`_set_curve_aa` 已能整体开关）；
  `_frf_ink_total()` 三行求和（幅值/相位/相干各自 ViewBox y 跨度、行高；先
  `updateAutoRange()`）；ink 迟滞腿常量取 Task 4；latch + paint 计时器；
  `quality_status()`（若无则新增最小版本供质量点消费，形状同 line_canvas）。
- [ ] `… -m pytest -q tests/ui/test_frf_canvas.py tests/ui/test_frf_main_window.py`

**Done:** 新测绿；既有 FRF 用例失败数不增。

---

### Task 7: 真机验收（Cocoa）

- [ ] 重跑 `scripts/probe_view_switch_quality.py` 全部子命令，`--json-out` 到
  verify `results/after-*.json`；对照 spec §6 表逐项打勾；README 补「改后」列。
- [ ] `scripts/benchmark_timedomain_interaction.py --assert-standards` 通过（门禁
  不改）；`scripts/probe_aa_ink_budget.py aa-frame` 平滑对照仍是 AA 照常开
  （零回归）。
- [ ] 手感复核（不能替代上面的数字，但要做）：真机开一份多通道文件，建 overlay
  与 subplot 各两个 View 来回切、切到 FFT/FRF 再切回；确认没有「切回来锯齿、
  拨一下才平滑」，分析区切换不再顿。
- [ ] 把 spec 顶部状态改为「已实施」，加实施注记表（照 2026-08-08 spec 的样式：
  验收项 / 改前 / 改后 / 判定）。

**Done:** §6 全部 ✅ 或有说明的 ⚠️；实施注记写入 spec。

---

### Task 8: 收尾

- [ ] 全量两条命令：`--ignore=tests/acquisition_ui` 跑主体，另起一条单跑
  `tests/acquisition_ui`；对照 CLAUDE.md 当前基线，新增红为零。
- [ ] CLAUDE.md「机械护栏」加一条：「View 恢复事务只结算一次（`TestViewRestoreSettlement`）
  + 交互静默窗 `timer.interval()==150` 钉住（`TestDiscreteSettle`）+
  分析画布 AA 不在切换调用里同步落地」。AGENTS.md 若有对应 Verification Gates
  段落，同步一句（两份文件描述同一护栏）。
- [ ] `docs/analyzer/README.md` 不需要改（Routing 按目录）；本 plan 与 spec 状态
  更新；verify README 指向 `scripts/` 正式探针。
- [ ] 提交粒度：Task 0 / 1 / 2 / 3 / (4+5) / 6 / 7 各一 commit，信息里引用 spec 节号。

---

## 风险与回退

- **Qt 计时器 interval 陷阱**（`QTimer.start(int)` 永久改 interval）：设计上用独立
  0 ms 计时器规避，Task 3 / 5 / 6 各有 `interval()==150` 守卫。
- **0 ms 计时器与首次 paint 顺序**：两种顺序都正确（spec §7），验收看的是
  `aa_on` 在 settle 返回时的值与首帧计时，不依赖顺序。
- **`enableAutoRange` 懒应用**：ink 读 y 跨度前 `updateAutoRange()`；测试用例
  显式覆盖「先 autoRange 后读」。
- **memo 过期**：键含 dpr；其余靠 backstop（一帧）。
- **既有测试断言「切换后黄点」/「plot_spectra 后即 AA」**：改语义不放宽（spec §7）。
- **回退路径**：`restore_visible_xlim` 默认 `flush=True`；`settle_*` 为新增入口；
  `_render_view_to_canvas` 改回三行即今天行为；line / frf 的离散武装留类常量开关。
- **Windows 复标定**：Task 4 数字是 Cocoa 的；与 2026-08-08 spec §7.4 一样，
  release 前在 Windows 参考机复跑 `analysis-frames`，必要时按平台分常量。
