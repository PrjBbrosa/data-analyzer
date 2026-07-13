# 分析编排治理 Phase 1 — Implementation Plan

Date: 2026-07-13
Spec: `docs/analyzer/specs/2026-07-13-analysis-orchestration-governance-spec.md`
Source review: `docs/analyzer/reviews/2026-07-12-current-architecture-assessment.md`

## Goal

按依赖顺序完成三个阶段：A）FFT-vs-Time 缓存统一 + `_apply_xaxis` 失效不对称修
复；B）抽出 `AnalysisJobService` 合并 FFT-vs-Time / Order 两套镜像 QThread 泵；
C）`FftTimeCoordinator` 试点。行为零漂移：计算数学、渲染视觉、compute key 字段
集、进度语义、LRU 容量全部不变。

## Global Constraints

- 实施前完整读 spec；spec §5.1 删除清单与 §2 锚点为准，行号如有漂移以符号名
  定位。
- 每个任务先补失败测试，确认失败原因正是缺失/待删的契约，再动实现。
- 不新增第三方依赖；不改 `.tlproj`/preset/QSettings schema。
- `weighting` 必须留在 compute key；`db_reference`/mode/catalog revision 必须
  留在 key 外（`test_cache_key_dataclass_binding.py` 全程不许红）。
- 渲染文件（`pg_canvas/`、`heatmap_canvas.py`、`line_canvas.py`）出现 diff 即
  越界，停下重审。
- 不自动 commit/push/merge；等待用户明确授权。
- 项目位于 `~/Downloads`（TCC 红线）：pytest 一律前台跑、不用
  run_in_background 跑全量；子 agent 执行时同样禁止后台全量 pytest。
- 统一测试命令前缀：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ... -q
```

## Task 0 — Baseline 与工作区保护

**Files**：只读。

### Step 0.1 — 范围确认

```bash
git status --short --branch
git diff --stat
```

预期：干净树（或仅本 spec/plan/review 文档）。有其他未提交改动则先上报，不吸收。

### Step 0.2 — Baseline focused suite

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_cache_key_dataclass_binding.py \
  tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_analysis_cache.py \
  tests/ui/test_compute_progress_integration.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_nonuniform_fft_full_flow.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py -k "fft_time" -q
```

记录精确基线数。既有失败（如 manual-order-rpm 线的 cache-key 漂移旧失败）单独
记录隔离，不并入本轮范围。

## Task 1 — `_apply_xaxis` 失效不对称：定真伪并修复（spec P1/P6）

**Files**

- Modify: `mf4_analyzer/ui/main_window/window.py`（`_apply_xaxis`，锚点 :1865 附近）
- Modify: `tests/ui/test_task4_cache_invalidation.py`

### Step 1.1 — RED 复现测试

```python
def test_apply_custom_xaxis_invalidates_fft_time_analysis_cache(qtbot): ...
```

流程：载入合成数据 → `do_fft_time` 落缓存 → 应用自定义 X 轴 → 再次
`do_fft_time`，断言不命中旧 analysis 条目（以 dispatch 计数或 cache get 探针
证明）。先在未修复代码上跑：

- RED（命中旧条目）→ 确认为真 stale-hit bug，按 bug 记录；
- GREEN（key 变化使旧条目不可达）→ 改写测试为守卫「该路径必须经统一入口对称
  失效」，仍继续 Step 1.2（卫生要求）。

**把真伪结论如实写进本 plan 的 Completion Record，不允许含糊。**

### Step 1.2 — 修复

`window.py:1865` 的 legacy-only 清理改为经统一入口
`_invalidate_all_analysis_caches_for_fid`（或对 `analysis_caches['fft_time']`
的等价 invalidate，与该路径的失效范围语义匹配——若该路径本意只失效
fft_time，则显式注明为 section 级失效并留注释说明为何不走全 section 入口）。

### Step 1.3 — GREEN

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_task4_cache_invalidation.py -q
```

## Task 2 — Key 口径统一与 dispatch/lookup 一致性（spec P3）

**Files**

- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- Modify: `tests/ui/test_task4_cache_invalidation.py`

### Step 2.1 — 失败测试

扩展 `TestFallbackKeyAlignsPrimaryKey`（:161）：

```python
def test_fft_time_dispatch_key_equals_lookup_key_for_each_pane(qtbot): ...
def test_fft_time_single_path_uses_same_key_builder_as_main_path(qtbot): ...
```

断言：`do_fft_time`（:329）、`_do_fft_time_single`（:422）与 dispatch 时装入
pending 的 analysis key 全部出自 `_fft_time_analysis_cache_key`、同一
`_pane_time_range_for` 口径；双 pane 各自 key 不同且稳定。

### Step 2.2 — 实现

审计并归一三处 key 构造调用点的输入；`effective_time_range`（:559）不再参与
key（它随 legacy 退役），仅继续作为计算输入传给 worker。

### Step 2.3 — GREEN + 回归

上述文件 + `tests/ui/test_main_window_smoke.py -k "fft_time_cache"`。

## Task 3 — 删除 legacy `_fft_time_cache`（spec P2/P4/P5）

**Files**

- Modify: `mf4_analyzer/ui/main_window/window.py`（:90-91、:1773）
- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`（:90-145、:164、:331-340、:417/:420、:444-450、:580-586、:780-781）
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`（:795）
- Modify tests: `tests/test_cache_key_dataclass_binding.py:77`、
  `tests/ui/test_task4_cache_invalidation.py:33/:58/:123-134`、
  `tests/ui/test_nonuniform_fft_full_flow.py:214/:231/:266/:322`、
  `tests/ui/test_compute_progress_integration.py:604/:633/:653`、
  `tests/ui/test_main_window_smoke.py:34/:1807/:1968-2044/:2184-2266/:3461-3482`、
  `tests/ui/test_analysis_multiview_integration.py:243`、
  `tests/ui/test_inspector.py:677`（注释）

### Step 3.1 — 先迁测试（断言语义不变）

把上述测试中 `_fft_time_cache` / `_fft_time_cache_key` / `_fft_time_cache_get`
引用换成 `analysis_caches['fft_time']` / `_fft_time_analysis_cache_key`。
`test_fft_time_key_field_set_equals_spectrogram_params`（:77，legacy key ↔
SpectrogramParams 绑定）删除——:94 的 analysis 版已覆盖同一守卫。此步跑测试
预期 FAIL（生产代码还在双写，部分探针断言双份存在）——逐条确认失败原因是
「legacy 仍存在」而非误删断言。

### Step 3.2 — 按 spec §5.1 删除清单执行

逐项删除；`_fft_time_pending` 移除 `cache_key` 字段后核对所有读方。

### Step 3.3 — GREEN + 审计

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_cache_key_dataclass_binding.py tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_analysis_cache.py tests/ui/test_nonuniform_fft_full_flow.py \
  tests/ui/test_compute_progress_integration.py tests/ui/test_analysis_multiview_integration.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py -k "fft_time" -q
rg -n "_fft_time_cache" mf4_analyzer tests
```

`rg` 预期：生产代码零命中；tests 中仅允许注释/文档性残留（逐条说明）。

## Task 4 — 抽出 `AnalysisJobService`（spec P7/P8）

**Files**

- Create: `mf4_analyzer/ui/analysis_jobs.py`
- Create: `tests/ui/test_analysis_jobs.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`（:97-98/:106-109/:113-114/:117-120 字段删除；:2886-2932 关窗收敛）
- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`（:462/:510/:599/:767/:804/:838/:858 泵方法迁出）
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`（:406/:445/:748/:775/:795/:815 同上）
- Modify: `tests/ui/test_compute_progress_integration.py`（monkeypatch 点随泵迁移调整，断言语义不变）

### Step 4.1 — 失败的 service 单测（无 MainWindow）

```python
def test_service_runs_jobs_fifo_one_active_per_section(qtbot): ...
def test_service_parallel_sections_do_not_block_each_other(qtbot): ...
def test_service_progress_counts_match_total_and_completed(qtbot): ...
def test_cancel_clears_section_queue_and_suppresses_finished(qtbot): ...
def test_superseding_request_cancels_active_worker(qtbot): ...
def test_shutdown_joins_threads_with_terminate_fallback(qtbot): ...
def test_service_module_has_no_qtwidgets_import(): ...
def test_failed_job_emits_failed_not_finished(qtbot): ...
```

### Step 4.2 — 实现 service

QObject + QThread + 复用 `AnalysisComputeWorker`（`analysis_worker.py:14`）。
语义逐条对照 spec §5.2 的 5 点；service 不 import 缓存与 canvas。信号：
`finished(str, object, object)` / `failed(str, object, object)` /
`progress(str, int, int)`。

### Step 4.3 — 双 section 接线迁移

fft_time 与 order 同轮切换到 service：mixin 的 `_dispatch_*_job` 变为「组
job → service.submit」，`_on_*_finished` 变为 service 信号的槽（保留缓存写入
+ 渲染 + 泵下一个由 service 内部完成）。删除 MainWindow 12 字段与两套泵方法；
`window.py:2886-2932` 收敛为 `self._analysis_jobs.shutdown()`。

### Step 4.4 — GREEN

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_analysis_jobs.py tests/ui/test_compute_progress_integration.py \
  tests/ui/test_task4_cache_invalidation.py tests/ui/test_analysis_multiview_integration.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py -k "fft_time or order" -q
rg -n "_fft_time_thread|_fft_time_worker|_fft_time_queue|_fft_time_progress|_order_thread|_order_worker|_order_queue|_order_progress" mf4_analyzer
```

`rg` 预期零命中（或仅 service 内部私有命名，逐条说明）。

## Task 5 — `FftTimeCoordinator` 试点（spec P9/P10）

**Files**

- Create: `mf4_analyzer/ui/main_window/fft_time_coordinator.py`
- Create: `tests/ui/test_fft_time_coordinator.py`
- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`（编排逻辑迁出，
  留 widget 参数采集 + 渲染 + toast）
- Modify: `mf4_analyzer/ui/main_window/window.py`（构造注入 cache + service）

### Step 5.1 — 失败的 coordinator 单测（无 MainWindow）

```python
def test_coordinator_module_has_no_qtwidgets_import(): ...
def test_cache_hit_emits_render_event_and_submits_nothing(): ...
def test_cache_miss_submits_job_and_puts_result_on_finish(): ...
def test_superseded_pending_result_is_dropped_not_cached(): ...
def test_two_panes_produce_distinct_keys_and_do_not_cross_pollute(): ...
def test_invalidate_fid_delegates_to_single_store(): ...
```

依赖以 `AnalysisResultCache` 真实实例 + JobService 假体（或真实 service +
即时 job）注入。

### Step 5.2 — 实现与接线

coordinator 拥有 key 构造/缓存探查/dispatch 决策/pending 簿记/本 section 失效
（spec §5.3）；mixin 的 `do_fft_time`/`_do_fft_time_single` 缩为「采参 →
coordinator.request → 事件驱动渲染」。

### Step 5.3 — 四路径回归

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_fft_time_coordinator.py tests/ui/test_analysis_jobs.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_compute_progress_integration.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py -k "fft_time" -q
```

项目恢复路径额外跑 `tests/test_project_io_analysis_views.py`。

## Task 6 — 终局回归、审计与交接

### Step 6.1 — Focused full suite

Task 0 基线全集 + 新增三个测试文件，前台一次跑完，记录精确计数对比基线
（允许差异 = 本轮新增/迁移测试，逐条列出）。

### Step 6.2 — 字面审计

```bash
rg -n "_fft_time_cache|_fft_time_thread|_order_thread|_fft_time_queue|_order_queue" mf4_analyzer
rg -n "QtWidgets|QWidget" mf4_analyzer/ui/analysis_jobs.py mf4_analyzer/ui/main_window/fft_time_coordinator.py
git diff --stat -- mf4_analyzer/ui/pg_canvas mf4_analyzer/ui/pg_canvases.py
```

第三条预期空输出（渲染零 diff 红线）。

### Step 6.3 — Completion Record

只在实施后追加：精确 pytest 计数、Task 1 真伪结论、`rg` 审计输出、遗留项
（Order/FFT coordinator 迁移与 AR-03 归 Phase 2）。

## Execution Order And Stop Gates

```text
Task 0 → Task 1（失效修复）→ Task 2（key 口径）→ Task 3(删 legacy)
       → Task 4（JobService）→ Task 5（coordinator 试点）→ Task 6（回归审计）
```

Task 1–3（Phase A）可独立收口为一次交付；Task 4（Phase B）、Task 5（Phase C）
各自独立收口。

遇下列任一情况停下修复再继续：

- 迁移后本应命中的缓存开始重算（key 口径回归）；
- display-only 改动触发 worker dispatch，或 compute 改动不失效；
- 取消后旧 job 结果仍落缓存或触发渲染；
- 关窗后仍有存活 QThread（wait 超时走 terminate 以外的路径）；
- `test_cache_key_dataclass_binding.py` 任一守卫变红；
- 渲染文件出现 diff；
- coordinator 或 service 模块 import 到 QtWidgets；
- 任何测试迁移改变了断言语义而不仅是引用路径。

## Acceptance Coverage Map

| Spec ID | 任务 | 字面证据 |
| --- | --- | --- |
| P1 | Task 1 | `test_apply_custom_xaxis_invalidates_fft_time_analysis_cache` + 真伪结论 |
| P2 | Task 3 | Step 3.3 `rg` 零命中输出 |
| P3 | Task 2 | dispatch==lookup key 双测试 |
| P4/P5 | Task 3 | 迁移后 smoke `:1807/:3461/:2012/:2184` 系列保持绿 |
| P6 | Tasks 1,3 | `test_task4_cache_invalidation.py` 扩展后全绿 |
| P7 | Task 4 | service 单测 + Step 4.4 字段 `rg` 审计 |
| P8 | Task 4 | `test_compute_progress_integration.py` 全绿 + shutdown 单测 |
| P9 | Task 5 | no-QtWidgets 守卫 + 无 MainWindow 单测 |
| P10 | Task 5 | 四路径测试各自落名 |
| P11 | Tasks 2–5 | `test_cache_key_dataclass_binding.py` 全程绿 |

## Definition Of Executable

所有引用符号在实施前重查一遍（行号允许漂移、符号必须存在）；Tasks 0–6 的字面
测试与 gates 完整保留。本 plan 不自行授权实施、commit、push 或 merge；执行在
用户明确要求后开始。

## Completion Record — 2026-07-13

### Task 1 truth conclusion

`_apply_xaxis` 的失效不对称为**真实 stale-hit bug**：新增复现测试在旧代码上
得到 `1 failed, 10 passed`，旧的 `analysis_caches['fft_time']` 条目仍可达。修复后
该路径只清 FFT-vs-Time 的唯一 store（不误清 FFT / Order），目标测试得到
`11 passed in 0.42s`。

### Final foreground verification

- Task 0 原始 focused baseline：`119 passed, 25 warnings in 8.50s`。
- Task 6 focused full suite（Task 0 集合 + service / coordinator / project-IO 覆盖）：
  `146 passed, 25 warnings in 8.44s`。相对基线的 `+27` 是 10 个 JobService 单测、
  9 个 Coordinator 单测、6 个 project-IO analysis-view 测试和既有集合内净增 2 个
  回归测试。
- Task 6 FFT-vs-Time smoke：`31 passed, 69 deselected in 2.05s`。
- Task 4 顺序前台再验证：focused `113 passed, 25 warnings in 7.83s`；
  `-k "fft_time or order"` smoke `42 passed, 57 deselected in 2.74s`。
  一次错误的并行 Qt pytest 输出已废弃，未作为验收证据。

### Literal audits

- `rg -n "_fft_time_cache|_fft_time_thread|_fft_time_worker|_fft_time_queue|_fft_time_progress|_order_thread|_order_worker|_order_queue|_order_progress|_fft_time_pending|_start_next_fft_time_job|_dispatch_fft_time_job|_on_fft_time_thread_done|_start_next_order_job|_dispatch_order_job|_on_order_thread_done" mf4_analyzer tests`：零输出。
- `rg -n "QtWidgets|QWidget|MainWindow" mf4_analyzer/ui/analysis_jobs.py mf4_analyzer/ui/main_window/fft_time_coordinator.py`：零输出。
- `git diff --stat -- mf4_analyzer/ui/pg_canvas mf4_analyzer/ui/pg_canvases.py`：空输出。
- `git diff --check` 与新模块 `py_compile`：通过。

### Residual scope

- Phase 2 再评估 / 迁移 Order 与普通 FFT 的 coordinator 边界，以及 AR-03
  ViewManager 所有权；本轮未搬动它们。
- AR-04 Batch 图片导出适配器仍按 Spec 降级为非目标。
- 未新增窗口级“显式取消”控件；Service 已提供 cancel / replace 语义，后续若接入
  该 UI 入口，应同时定义进度 token 的取消收口行为。
