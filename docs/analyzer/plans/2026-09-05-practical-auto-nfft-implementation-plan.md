# TraceLab 实用型 Auto-NFFT Implementation Plan

- 日期：2026-09-05
- 修订：R1（2026-09-05 review 修订，与 Spec R1 对齐）
- 状态：READY FOR TASK 0；执行基线核实后进入实现，数值与前台验收尚未完成
- Spec：`docs/analyzer/specs/2026-09-05-practical-auto-nfft-spec.md`
- 目标：普通分段 FFT 在普通采样率和足够数据下优先 4096；FFT-vs-Time 仅为最低 4 个时间帧做必要降级；所有实际参数和降级原因可见且 GUI/Batch 同源
- 本文件只规划实施；当前批次未修改产品代码

## 0. 执行原则与基线

### 0.1 开工前状态

R1 文档修订所依据的当前检查：

- HEAD：`c9438b589b58e3395765b62e33ce5601c189541c`；执行时重新核实分支及 upstream，不沿用旧 ahead 数。
- worktree 有预存 tracked 删除、文档/原型/报告，以及正在修改的 recent-open UI/help/tests；本批只修订这两份未跟踪 Auto-NFFT 文档。
- 有效事实已在 `e72606a3` 落地，`172896e9` 修复空卡片；关联 honesty plan 已提交，但其 DRAFT/未完成文字不能代表当前代码状态。
- 前一轮 review 在该 HEAD 对 adaptive、FFT/spectrogram facts 与 GUI/Batch facts parity 四个文件实跑：`65 passed, 1 warning in 0.45s`。这是旧实现定向证据，不是新策略通过证据。

本轮是 docs-only 修订：验证完整文档、矩阵计算、路径、A1–A13 映射和旧合同残留，不运行产品全套测试。后续实现按各任务的 focused/boundary gates 执行。

执行者必须重新记录 `HEAD` 和 named-path dirty scope；不得还原、删除、格式化或提交任何既有无关工作。提交只使用命名路径，禁止 `git add -A`。

### 0.2 TDD 与数值 owner

- 所有数值改动先写红测；中立 resolver 和 frame counter 由 signal-processing owner 独占。
- GUI、Batch 只能消费中立决策，不复制公式。
- 各 worker 只跑 focused/boundary tests；一个 coordinator 拥有唯一 full-suite gate。
- 实施期间若已有同 checkout 的 full pytest 在运行，等待或复用，不并发启动。
- 依赖固定为 `Task 0 → 1 → 2 → 3 → (4 → 5 与 6) → 7 → 8 → 9 → 10`。Task 2 先冻结 DTO/序列化/签名 API，再开放 GUI/Batch 并行；共享 parity 测试由 Task 8 coordinator 独占，worker 用各自 owner tests。

### 0.3 Acceptance 映射

| Spec | Plan task |
| --- | --- |
| A1 | Task 1（M1–M8/M10、B1–B8）、Task 2/4/6（M9） |
| A2 | Task 1–2 |
| A3 | Task 1–2、Task 5 |
| A4 | Task 4 |
| A5 | Task 1、Task 3 |
| A6 | Task 1–2 |
| A7 | Task 4–6 |
| A8 | Task 4、Task 7 |
| A9 | Task 2、Task 4–6（cache 意图签名与逐项/分组 resume） |
| A10 | Task 4–7 |
| A11 | Task 7 |
| A12 | Task 2–3、Task 8 |
| A13 | Task 9 |

## Task 0 — 冻结合同并消除相邻计划冲突

**Owner:** coordinator；只读检查 + 测试骨架，不改算法。

**Files:**

- Read: `mf4_analyzer/signal/adaptive.py`, `signal/fft.py`, `signal/spectrogram.py`, `signal/frf.py`, `signal/order.py`
- Read: `_fft_mixin.py`, `_fft_time_mixin.py`, contextual FFT sections, `batch_compute.py`, `batch.py`, renderer facts path
- Read: `ui/inspector_sections/_effective_facts.py`, `ui/main_window/_analysis_mixin.py`, `fft_time_coordinator.py`, `batch_manifest.py`, `batch_recipe.py`
- Reconcile: Spec §10.1 与已落地 facts；关联 honesty plan 仅作历史背景，不改写历史计划

- [ ] 记录 HEAD、worktree fingerprint、运行中的 pytest PID/工作目录。
- [ ] 建 A1–A13 checklist；逐条填 owner、红测、停止条件。
- [ ] 核实既有 DTO/builders、共享卡片、代表源发布逻辑及 Batch 序列化路径；按 Spec §10.1 扩展，不创建第二套 facts/UI。
- [ ] 冻结字段映射、reason 顺序、blocked 空值合同、`nfft_facts_signature` 和 `AUTO_NFFT_POLICY_VERSION=2`；保留旧 DTO 构造与 `nfft/df` 属性兼容。
- [ ] 冻结旧 `resolve_order_nfft` characterization 矩阵，再进入 Task 1；本批只新增 resolver，不改变旧 helper 签名/默认值。
- [ ] 枚举逐项/分组 resume 及所有提前返回消费者，指定 Task 6 的共同兼容判定接入点。
- [ ] 记录 M1–M10/B1–B8 可用的旧路径 before 输出；M9 单独走单帧路径。不得把旧输出误当 acceptance。
- [ ] 标记 recent-open 在途修改与 Task 7 的 hints/quickref/help 共享路径；到 Task 7 时串行合并，禁止覆盖他人修改。

**Stop:** facts 批次正在修改相同文件，或当前 source 已偏离 Spec 所引用的语义。先串行合并/重定基线，不在冲突树上并行实现。

## Task 1 — 中立决策对象与候选算法（红测先行）

**Owner:** signal-processing owner；独占 `signal/adaptive.py` 与 `tests/test_signal_adaptive.py`。

**Files:**

- Modify: `mf4_analyzer/signal/adaptive.py`
- Modify: `mf4_analyzer/signal/analysis_defaults.py`
- Modify: `mf4_analyzer/signal/__init__.py`
- Modify: `tests/test_signal_adaptive.py`

- [ ] 先为 Spec M1–M8/M10 与 B1–B8 写参数化红测；断言完整 decision、原因顺序及空值，不把单帧 M9 塞入分段 purpose。
- [ ] 新增冻结 `AutoNfftDecision`，字段和 reason codes 与 Spec §4 完全一致。
- [ ] 新增 purpose-specific resolver，例如 `resolve_auto_nfft(..., purpose=...)`；输入校验保持 fail closed。
- [ ] 实现 4096/10 s 基线、duration target、**请求先应用 64 点下限**、真实样本上限和 purpose-specific Auto ceiling；补 `minimum_nfft_floor`。
- [ ] 实现 `non_tail_frame_count` 与 canonical spectrogram frame count；hop 取整与现有分析器一致。
- [ ] 分段 1D 只根据帧数设置 status/reason，不降 NFFT。
- [ ] FFT-vs-Time 仅在 canonical frames<4 时按 2 的幂下降。
- [ ] 1<=N<64 返回 `insufficient_samples`；N>=64 但时间帧仍不足时返回 `insufficient_time_frames`。blocked 时 effective/df/window/degraded 为 None、frames=0；非法参数抛 ValueError。
- [ ] count 为 O(1)，不构造 starts 数组；共用 owner 提供分析器所需 starts，覆盖 hop 取整、整除与不整除尾部。
- [ ] 保留公共 import；明确旧 `resolve_nfft` 的兼容策略和 deprecation 文档，不复制新产品规则。

**Focused:**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_signal_adaptive.py -q
```

**Stop:** M1–M8/M10、B1–B8 需要特殊测试分支才能成立，数据充足却因目标<64 被 blocked，或 Order tests 因共享 helper 被动改变。

## Task 2 — 冻结真实 frame、facts 迁移与缓存签名边界

**Owner:** signal-processing owner；Task 1 绿后执行。

**Files:**

- Modify: `mf4_analyzer/signal/fft.py`
- Modify: `mf4_analyzer/signal/spectrogram.py`
- Modify: `mf4_analyzer/signal/adaptive.py`（中立签名 helper；与 Task 1 同 owner 串行）
- Tests: `tests/test_fft_amplitude_normalization.py`, `tests/synthetic/test_fft_known_tone.py`, `tests/test_spectrogram.py`；新建 `tests/signal/test_auto_nfft_compute_contract.py`
- Tests: `tests/signal/test_fft_effective_facts.py`, `tests/signal/test_spectrogram_effective_facts.py`, `tests/signal/test_order_effective_facts.py`

- [ ] 让普通平均/峰值保持的帧计数与中立 `non_tail_frame_count` 共用同一整数 hop 规则；不得改变幅值数学、segment 内容或尾帧政策。
- [ ] 让 `SpectrogramAnalyzer._frame_starts` 与中立 canonical counter 共用一个 owner；保留尾部补帧行为。
- [ ] 冻结 Auto blocked decision 转 user/data error 的边界合同，具体 dispatch/preflight 接线由 Task 4–6 实施；分析器仍保持窄输入合同。
- [ ] 为 NFFT=4096 的正弦信号验证频率网格 `df=fs/4096`、峰值 bin 和输出 shape；不以像素截图代替数值测试。
- [ ] 断言 Auto 没有通过零填充满足 4096；`window_s=effective_nfft/fs` 对应真实段样本。
- [ ] 保持 compute-layer 峰值保持与 render-layer `build_peak_trace` 分离。
- [ ] 依 Spec §10.1 扩展现有 DTO/builder：保留 `nfft/df` 构造属性，提供只读 canonical aliases 与 owner 级序列化入口；新字段带兼容默认值，禁止双份实际值状态。
- [ ] FFT/FFT-time 的 shortened 只表达实际点数缩短；统计不足由 status/reasons 表达。单帧/Fixed 不套用 Auto 策略字段或门槛。
- [ ] 实现一个纯数据 `nfft_facts_signature` helper，覆盖 D8 的模式/版本/规范化 t_win_s/目标/请求/实际/样本数/status/degraded/reasons；GUI cache 消费它，不自行拼另一套字段。
- [ ] 锁定 M9：单帧 N=3552，同时补奇数 N=3553，实际 NFFT/df/长度保持一致；不能只从频率数组长度猜奇偶。
- [ ] 按 Spec §7.2 补突发/扫频的帧中心、窗覆盖与 Auto/同点数 Fixed parity；不以少数时间列作为瞬态定位精度证明。
- [ ] 在 Task 3 结束前发布 DTO/serializer/signature API 给 GUI/Batch owners；这些中立文件后续只由 signal owner 修改。

**Focused:**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_fft_amplitude_normalization.py \
  tests/synthetic/test_fft_known_tone.py tests/test_spectrogram.py \
  tests/signal/test_auto_nfft_compute_contract.py \
  tests/signal/test_fft_effective_facts.py \
  tests/signal/test_spectrogram_effective_facts.py \
  tests/signal/test_order_effective_facts.py -q
```

## Task 3 — 保护 Order 与 FRF 独立语义

**Owner:** signal-processing owner；与 Task 2 同一 owner 串行。

**Files:**

- Modify only if required: `mf4_analyzer/signal/adaptive.py`, `signal/order.py`
- Tests: `tests/test_signal_adaptive.py`, `tests/signal/test_order_cot.py`, `tests/signal/test_order_cot_time_grid.py`, `tests/test_frf.py`

- [ ] 复跑 Task 0 已冻结的 `resolve_order_nfft` characterization tests，证明新增 helper 后输出零变化。
- [ ] 证明 M7 低 Fs 时域 FFT 适配与 Order 角域策略互不串扰。
- [ ] 证明 FRF Auto 仍为 `nfft == nperseg`，Manual 的 zero-padding / validation 合同不变。
- [ ] 不把 4096 偏好常量导入 Order/FRF compute path。

**Focused:**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_signal_adaptive.py \
  tests/signal/test_order_cot.py \
  tests/signal/test_order_cot_time_grid.py \
  tests/test_frf.py -q
```

**Stop:** 任一现有 Order/FRF 数值输出、error taxonomy 或 effective facts 变化。

## Task 4 — 普通 FFT GUI 接入

**Owner:** GUI integration owner；Task 1–3 绿后执行，不修改 resolver 数学。

**Files:**

- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`（仅必要的多源 facts 发布/缓存 fallback 接口）
- Modify: `mf4_analyzer/ui/inspector_sections/_effective_facts.py`（展示接入；不修改 Task 2 中立 DTO）
- Tests: `tests/ui/test_main_window_smoke.py`, `tests/ui/test_inspector.py`, `tests/ui/test_analysis_multiview_integration.py`, `tests/ui/test_task4_cache_invalidation.py`, `tests/ui/test_project_session.py`, `tests/test_project_io_analysis_views.py`, `tests/test_analysis_presets.py`

- [ ] `_resolve_fft_effective_params` 消费 `AutoNfftDecision`；单帧分支保持 whole-selection。
- [ ] preview 和真实 compute 使用同一 purpose、Fs、masked sample count、overlap。
- [ ] 结果 cache key 加 Task 2 的 `nfft_facts_signature`；保留 compute fields 与显示字段边界。按 D8，意图不同即失效，不从旧结果借用 facts。
- [ ] 红测覆盖 N=3000、t=1.5→8 s（实际均2048、请求4096→8192）及 Auto↔Fixed 同点数；计算、cache hit、View 切换和 facts 同步必须使用同一个 key builder。
- [ ] 项目/View/预设 round-trip 只保留 Auto 意图；恢复后按当前来源重新解析，不把旧 effective NFFT 变成 Fixed。
- [ ] 多来源逐 source 解析，汇总为 `自动(N)` 或 `自动(lo–hi · 每源)`。
- [ ] 扩展代表源发布路径为每源 facts；混合正常/降级/blocked 与全 blocked 状态都有 source/channel 身份，无数据区分目标与待数据。
- [ ] blocked/notice/warning 映射为明确反馈；不得 broad catch 后回退到旧 NFFT。
- [ ] 计算完成时把 producer-shaped facts 推到既有 facts card；View 切换、来源移除、clear 对称清理。
- [ ] 先更新旧断言（当前 1000 Hz / 60000 样本为 2048）为 Spec M1；新增 M3/M8/单帧回归。

**Focused:**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py tests/ui/test_inspector.py \
  -k 'fft and (nfft or facts)' -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_project_session.py \
  tests/test_project_io_analysis_views.py \
  tests/test_analysis_presets.py -q
```

**Stop:** 多来源不同 Fs 被合并成一个 effective NFFT，或为接线新增 MainWindow 多文件状态写点。

## Task 5 — FFT-vs-Time GUI/worker 接入

**Owner:** FFT-time integration owner；Task 1–4 绿后执行。它与 Task 4 共享 Inspector/facts 和现有测试文件，必须串行，不能用并行修改制造合流冲突。

**Files:**

- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/fft_time_coordinator.py`
- Modify if required: `mf4_analyzer/ui/main_window/_analysis_mixin.py`（接续 Task 4 的 fallback key 接口；串行）
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Tests: `tests/ui/test_main_window_smoke.py`, `tests/ui/test_inspector.py`, `tests/ui/test_nonuniform_fft_full_flow.py`, `tests/ui/test_compute_progress_integration.py`, `tests/ui/test_fft_time_coordinator.py`, `tests/ui/test_task4_cache_invalidation.py`

- [ ] `_resolve_fft_time_effective_params` 消费 purpose=`fft_time` decision；M4–M6 精确成立。
- [ ] Inspector `_nfft_preview` 不再独立 `ceil_pow2`；无数据时显示目标而非伪装实际值。
- [ ] worker job、主 key、coordinator key、fallback key、result facts 使用同一 effective NFFT/签名；不能在 `_fft_time_analysis_cache_key` 中重新组装 params 时丢掉签名。
- [ ] 测试同实际值不同目标、Auto↔Fixed、旧版本失效；cache 命中与 worker miss 都显示本次意图，display-only 变化不误触发重算。
- [ ] 去掉旧 facts 恢复路径中用默认目标窗重建 requested 的推断；旧缓存若无可验证签名，按 miss 重算。
- [ ] 现有 64 MiB amplitude matrix preflight 保持；内存失败仍是可操作 user/data failure。
- [ ] 时间范围 mask 后重新解析；project restore/cache render 不复用旧范围的 decision。
- [ ] 不改变 overlap、remove_mean、window、weighting 或热图 extents。

**Focused:**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py tests/ui/test_inspector.py \
  -k 'fft_time and (nfft or facts)' -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_nonuniform_fft_full_flow.py \
  tests/ui/test_compute_progress_integration.py \
  tests/ui/test_fft_time_coordinator.py \
  tests/ui/test_task4_cache_invalidation.py -q
```

**Stop:** resolver frame count 与 `SpectrogramResult.metadata['frames']` 不一致，或 tail frame 只在一侧存在。

## Task 6 — Batch、manifest 与 renderer 同源

**Owner:** batch core owner；Task 1–3 的中立 API 冻结后执行，可与 Task 4→5 并行；不修改中立 DTO、共享 UI 格式器或 parity 测试文件。

**Files:**

- Modify: `mf4_analyzer/batch_compute.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/batch_manifest.py`（逐项/分组策略版本兼容判定）
- Read: `mf4_analyzer/batch_recipe.py`, `mf4_analyzer/batch_output.py`（确认 recipe 与任务身份仍表示用户意图，不借改 recipe 持久化内部版本）
- Modify if required: `mf4_analyzer/batch_render_qt/_page.py`
- Tests: `tests/test_batch_runner.py`, `tests/test_batch_renderer.py`, `tests/test_batch_manifest.py`, `tests/test_batch_recipe.py`, `tests/ui/test_batch_method_buttons.py`, `tests/ui/test_batch_smoke.py`

- [ ] `resolve_fft_nfft` / `resolve_effective_nfft` 改为消费中立 decision，不复制常量或循环。
- [ ] Batch FFT 与 GUI 对 M1/M3/M7/M8 得到相同 NFFT、frames、status/reasons。
- [ ] Batch FFT-time 与 GUI 对 M4–M6 同值。
- [ ] `effective_params`、manifest、图片 facts 使用 canonical keys；requested auto 与 effective int 分开。
- [ ] FFT/FFT-time 的 raw `asdict(facts)` 输出路径迁移到 Task 2 serializer；现有 legacy 属性只作为兼容读取，不充当第二个 producer authority；Order/FRF 序列化合同不变。
- [ ] renderer 测试用 BatchRunner 真实产出的 mapping，不能手造 `effective_nfft` 别名假绿。
- [ ] sparse recipe 缺省值从 canonical defaults materialize；缺失 Fs/N 事实不得伪造成 0。
- [ ] 按 D11 在 manifest owner 实现共同版本兼容判定；逐项、分组及所有提前返回消费者均接入。依据 canonical requested method/mode 决定适用性，不能让旧 entry 自报 Fixed 绕过检查。
- [ ] 用来源 stat、checksum、recipe 均匹配的真实旧产物证明：版本缺失/旧版/错误类型/bool 均重新计算；当前版本仍可复用。分组中一个相关成员过期即不可复用该旧分组。
- [ ] 旧 manifest 可读且不被原地改写；新结果带 v2 facts；单帧/Fixed/Order/FRF 的旧 resume 合同保持。
- [ ] Batch M9 与 GUI 同值，补奇数单帧；新增 blocked 分段输入的 item status/progress 测试，统一经 `_RunReporter` 记录。

**Focused:**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_batch_runner.py -k 'nfft or effective_facts or resume' -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_batch_renderer.py \
  tests/test_batch_manifest.py \
  tests/test_batch_recipe.py \
  tests/test_batch_run_reporter.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_smoke.py -q
```

**Stop:** GUI/Batch 同一输入输出不同、renderer 显示 requested 而非 actual，或版本不匹配的旧 Auto 产物仍被 resume/提前返回路径复用。

## Task 7 — 用户可见事实、帮助与交互合同

**Owner:** UI/docs owner；Task 4–6 schema 合流后执行。

**Files:**

- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Modify: `mf4_analyzer/ui/inspector_sections/_effective_facts.py`（接续 Task 4；保护四类分析 facts）
- Modify: `mf4_analyzer/ui/hints.py`, `mf4_analyzer/ui/quickref.py`
- Modify: `mf4_analyzer/help/fft-guide.html`, `mf4_analyzer/help/ffttime-guide.html`, `mf4_analyzer/help/TraceLab-使用说明.html`
- Modify: `docs/analyzer/user-guide/user-guide.html`
- Tests: `tests/ui/test_inspector.py`, `tests/ui/test_hints.py`, `tests/ui/test_quickref.py`, `tests/test_help_content.py`

- [ ] facts 按 Spec D10 显示 actual NFFT、bin spacing、window、frames、原因。
- [ ] canonical `nfft_effective/df_hz` 优先，兼容旧 `nfft/df`；M3 只提示统计有限，不再显示“点数已缩短”。显式验证 FRF/Order 原有 labels/warnings 不变。
- [ ] 文案不用“4096 一定可信”；明确低 Fs 例外、短信号限制和零填充边界。
- [ ] 多来源 summary 断言 `lo–hi · 每源`；来源切换后不残留 stale facts。
- [ ] tooltip、hints、quickref、主说明和两份分析指南使用同一术语。
- [ ] 瞬态提示解释实际窗长与时间定位取舍，不把 4 个重叠帧描述为独立观测；Auto 门槛不误套 Fixed。
- [ ] 不重写历史 specs/plans/reports 的旧版本或旧行为记录。

**Focused:**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_inspector.py -k 'nfft or facts' -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_help_content.py -q
```

## Task 8 — 集成与架构门禁

**Owner:** coordinator；所有 lanes 合流后的唯一 owner。

- [ ] 收集 Tasks 1–7 focused 证据；只重跑合流改动影响的 owner tests 或尚未验证的交叉路径，不机械重复所有已完成门禁。
- [ ] coordinator 独占更新并运行 `tests/test_effective_facts_parity.py`：真实 GUI/Batch producer 对 M1–M10 及低 Fs floor、canonical 序列化、mode/status/reasons 一致；FRF/Order 原有 facts 不回归。
- [ ] 运行 FFT/FFT-time/Batch 数值与 parity 组合；M1–M10、B1–B8、D8 cache 和 D11 resume、A1–A12 逐项填证据。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/test_effective_facts_parity.py -q
```

- [ ] 运行 import/state/render guards：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py -q
```

- [ ] `git diff --check`；grep 确认产品路径不再以 `min_frames=24` / `max_window_frac=0.15` 驱动 FFT/FFT-time，Order compatibility 除外。
- [ ] 记录 integration HEAD 与 dirty scope；若 relevant files 在测试中变化，结果标 `UNVERIFIED`。

**Full gate justification:** 此改动跨 signal、GUI worker/cache、Batch、manifest 和 renderer，属于广泛数值边界变更，允许在稳定集成里程碑运行一次 full suite。按仓库规则两进程串行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui -q
```

不得并发，不得因前段通过推断异常退出的整套为 PASS。

## Task 9 — 真实前台与图形验收

**Owner:** coordinator / macOS foreground owner；自动化全绿后执行。

### 9.1 确定性数据

生成或加载三组明确标注的数据：

1. 普通 Fs：1000 Hz、60 s，含 bin-aligned 单频、相邻双频和宽带噪声；
2. 低 Fs：96 Hz、约 52 s，覆盖 M7。
3. Spec §7.2 的 0.25 s 突发与 20→100 Hz 扫频（Fs=1000，N=60000）；保存生成参数、随机种子和真实 onset/扫频公式，分别比较 Auto、Fixed 1024、Fixed 4096。

合成信号只能证明算法/显示，不冒充客户物理结论。若使用客户真实文件，只记录允许公开的 file/source/channel handle。

### 9.2 Cocoa 验收

- [ ] 普通分段 FFT 首次计算摘要为 `自动(4096)`，facts 为 4096 / 0.244140625 Hz / 4.096 s / 实际 frames。
- [ ] 相同数据在 GUI 与 Batch 的曲线频率网格、峰值位置和 facts 一致。
- [ ] 短范围触发 M3/M8 时，曲线仍显示，warning 明确且不遮挡图形。
- [ ] FFT-vs-Time M4/M5 的时间列数与 facts 一致，热图无伪连续或空白覆盖回归。
- [ ] 突发/扫频的实际窗长、hop、帧中心、coverage 与热图坐标一致；并列记录 1024/4096 的时间涂抹，不声称 4.096 s 窗可以精确定位 0.25 s 事件。若不满足目标场景，回到 Spec 修订，禁止暗调参数通过验收。
- [ ] 96 Hz M7 显示“低采样率适配”且实际 256 / 0.375 Hz，不误报必须 4096。
- [ ] 多来源不同 NFFT 的 summary/facts 可读；View 切换、重新计算、项目恢复无 stale 值。
- [ ] 同点数不同请求及 Auto↔Fixed 切换后 facts 更新；混合 blocked 来源仍有明确身份，统计不足不会错误显示“已缩短”。
- [ ] 交互缩放、Home、游标、复制图片和 UltraView capture 不因更密频率数组出现明显卡顿或糊线。

证据分类分开记录：数值测试、offscreen Qt、真实 Cocoa、Batch artifact；不得互相替代。

## Task 10 — 收口、lesson 与交付

- [ ] 检查 `scripts/lessons/check.py --status`。
- [ ] 若本次实现发现新的可复用失败模式（例如 GUI/Batch decision drift 或 frame-count 双权威），按 lessons 流程先写回归测试，再提升短 lesson；仅数值常量变更本身不自动创建 lesson。
- [ ] 更新 Plan 的执行记录和 A1–A13 证据，不把未跑门禁写成 PASS。
- [ ] named-path review/staging；提交中不含 `.state/` 临时记录或现有无关 dirty files。

## 建议提交切分

1. `test(signal): freeze practical auto-nfft decisions`（红测）
2. `feat(signal): prefer practical auto-nfft resolution`
3. `feat(fft): apply source-local auto-nfft decisions`
4. `feat(fft-time): keep useful time frames with 4096 preference`
5. `feat(batch): share auto-nfft decisions and facts`
6. `docs(help): explain effective auto-nfft resolution`

每个提交必须边界清晰、可单独复核；并行 owner 不得共同编辑同一文件。

## 总停止条件

- 为达到 4096 使用零填充，却把 `df` 宣称为物理分辨率提升；
- 普通平均频谱仍为凑 24 帧而降到 512/1024；
- FFT-vs-Time Auto 少于 4 个真实时间帧仍渲染成连续热图；
- GUI、Batch、preview、cache 或 renderer 出现第二套 Auto-NFFT 公式；
- Order/FRF 数值语义被 4096 基线连带改变；
- 请求值、实际值或 reason 只存在于文案，缺少结构化 facts；
- 数据充足但低 Fs/极短目标窗因候选<64 被错误 blocked；
- 同实际 NFFT 的不同意图命中旧 facts，或旧策略 Batch 产物被逐项/分组 resume 复用；
- FRF/Order 共享 facts 展示被本批字段或文案迁移改变；
- relevant source 在验证期间变化，或 full suites 并发/异常退出；
- 为完成本计划扩大 MainWindow state whitelist、放宽 import boundary 或修改既有渲染质量阈值。

## 执行记录（2026-09-05）

- 开工 HEAD：`c9438b58`；会话中 unrelated recent-open 已提交为 `a60da923`。Auto-NFFT 实现未提交，叠在该提交之上。
- Task 0–8 自动化门禁已跑 focused + architecture guards。**未跑**全量双进程 suite，**未跑** Task 9 Cocoa 前台。
- A1–A12：中立 resolver M1–M8/M10/B1–B8、GUI/Batch 接线、D8 cache 签名、D11 resume、facts/help 有测试证据。A13（真实 Cocoa）未验收。
- 产品路径不再用 `min_frames=24` / `max_window_frac=0.15` 驱动 FFT/FFT-time；仅旧 `resolve_nfft`（Order 兼容）保留。
- lesson_required=False；未提升 lesson（帧计数已收口到中立 owner，非常量翻车的新失败模式）。

## R1 文档修订记录（不是实施验收）

- 修复低 Fs 请求缺少 64 点 floor，并增加 B1–B8 与 blocked 原因区分。
- 固定 D8 为携带 facts 的结果缓存加入意图签名；固定 D11 为逐项/分组 resume 检查 Auto 策略版本。
- 对齐已落地 DTO、serializer、共享格式器与 owner tests；M9 单帧验收移出分段 resolver。
- 增加突发/扫频效果验收；实现、全量、Cocoa 与 Batch artifact gates 保持待执行，不以本轮文档检查替代。
- 文档检查：M1–M8、B1–B6 数值探针对照现有 canonical frame starts 通过；A1–A13 映射、引用路径（含一个明确声明的新测试）、代码围栏和旧基线残留检查通过。B7–B8 的产品测试及 M9 接线测试留待实现，不声称新 resolver 已通过测试。
