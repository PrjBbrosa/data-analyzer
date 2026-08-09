# 系统辨识 FRF 与 Batch FRF — 实施计划

日期：2026-08-08

状态：**已实施（source/offscreen gates 完成；macOS foreground 部分验证；Windows frozen 未验证）**

Spec：`docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`

设计基线：`main@4b216e5a`

## 1. Goal

按测试先行顺序，把 FRF 做成 TraceLab 正式的第五种分析：NumPy-only 的 H1/H2、
幅频/相频/相干性，单次三联图、物理 TimeDomain 范围关联和 Batch 一输入多输出任务。
实现必须满足 spec 的同源同时间基准、复合身份、可复现输出和依赖方向要求。

## 2. 实施总约束

- 实施前完整读取 spec；发现需要改变 estimator、对齐、Batch pair、输出列或时域关联
  语义时，先修订 spec 并重新过 review gate，不在代码中临场发明。
- 每个行为任务按 `RED → 最小 GREEN → focused regression` 执行；数值变化强制 TDD。
- 运行时只用 NumPy；SciPy 只允许出现在 `pytest.importorskip` reference tests。
- 不跨逻辑来源配对，不隐式重采样/插值/截短，不用合成时间网格。
- 不复用/改义现有 `AnalysisPreset.target_pairs`。
- 不复制 GUI QThread pump；FRF 必须走 `AnalysisJobService`。
- 不复制 Batch progress/result 路径；FRF 必须走 `_RunReporter`。
- 不在 `window.py` 新增跨多文件写入的 FRF 状态簇；状态归 View、cache、coordinator。
- 新 canvas 实现在 `ui/pg_canvas/frf_canvas.py`，不放进 compatibility façade。
- 新 DSP 实现在 `signal/frf.py`，不放进 `batch.py` 或 UI mixin。
- 只修改任务列出的 owner；出现无关 dirty changes 时保留并隔离，不吸收、不回退。
- 不自动 commit/push/merge/release；完成后等待用户授权。
- Qt 测试使用项目 runtime 和可写临时目录：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen \
PYTHONPATH=. .venv/bin/python -m pytest ... -q
```

## 3. 分阶段交付与 review gates

| Gate | 完成范围 | 允许进入下一阶段的条件 |
| --- | --- | --- |
| G0 | baseline | 工作区范围明确、相关既有测试基线已记录 |
| G1 | 数值核心 | N1–N9 通过，NumPy-only/import boundary 通过 |
| G2 | 单次分析骨架 | cache/coordinator/canvas/view/project focused tests 通过 |
| G3 | TimeDomain 关联 | custom-X 与 dedicated-view 合同通过，未连续重算 |
| G4 | Batch 计算输出 | pair resolver、identity、runner、CSV/PNG/manifest 通过 |
| G5 | 产品完整性 | help/hints/quickref、offscreen render、边界套件通过 |
| G6 | 发布验收 | foreground macOS 与 fresh Windows Full/Lite 分级记录 |

G1 完成后先做一次数值 review；G3 完成后做一次单次 GUI review；G4 完成后做一次 Batch
identity/output review。review 未通过时不继续堆后续 UI。

## Task 0 — Baseline、范围保护与可执行性复核

**Files：只读；只在实施记录中写结果。**

### Step 0.1 — 确认 checkout 与 dirty scope

```bash
git status --short --branch
git rev-parse --short HEAD
git diff --stat
git ls-files --others --exclude-standard
```

预期基线是 `main@4b216e5a`、相对 `origin/main` ahead 1。本地实际状态如已变化，以 live
结果为准并记录；不得为“恢复基线”执行 reset/checkout。

### Step 0.2 — 重新核对 spec 的真实符号

```bash
rg -n "_MODE_TO_INDEX|analysis_managers|analysis_caches|SUPPORTED_METHODS" \
  mf4_analyzer/ui mf4_analyzer/batch.py
rg -n "target_pairs|SCHEMA_VERSION|build_task_output_identity|_RunReporter" \
  mf4_analyzer tests
rg -n "FFT vs Time|四个分析模式|SUPPORTED_ANALYSIS_METHODS" \
  mf4_analyzer tests
```

如果当前结构已漂移，先更新计划中的文件/符号；禁止把 compatibility façade 当新 owner。

### Step 0.3 — 相关 baseline tests

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q \
  tests/test_analysis_presets.py \
  tests/test_batch_recipe.py \
  tests/test_batch_preset_io.py \
  tests/test_batch_output.py \
  tests/test_batch_validation.py \
  tests/test_batch_runner.py \
  tests/test_batch_render_qt.py \
  tests/test_batch_run_reporter.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_project_session.py
```

记录精确 pass/fail/skip。既有失败保持独立，不能以“看起来无关”直接忽略；确认它是否
阻断本功能 owner。

### Gate G0

- [x] live HEAD、dirty scope、baseline 结果有记录；
- [x] spec/plan 符号仍存在或计划已修订；
- [x] 无产品文件在 Task 1 前被修改。

## Task 1 — NumPy FRF 数值核心（spec N1–N9）

**Files**

- Create: `mf4_analyzer/signal/frf.py`
- Modify: `mf4_analyzer/signal/__init__.py`（仅必要公共 re-export）
- Create: `tests/test_frf.py`
- Create: `tests/test_frf_scipy_parity.py`
- Modify: `tests/test_signal_no_gui_import.py`

### Step 1.1 — RED：DTO 与输入边界

先写失败测试：

- `FrfParams` 默认值和拒绝非法 estimator/window/overlap/NFFT；
- input/output 的 empty、2D、bool、complex、NaN/Inf、不同长度；
- invalid/non-finite Fs；
- 时间严格递增、uniformity、两端逐点一致；
- `t_win_s` 过短导致 `nperseg < 2` 时阻断；periodic 窗全零（`Σw² = 0`，
  `nperseg = 1` 必然触发）不得进入 scale 除法；
- requested segment 只能得到 0/1 个完整段时失败，2–3 段告警；
- result arrays 一维等长，dtype 为 float64/complex128。

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_frf.py \
  -k "params or input_contract or timebase or segment_count" -q
```

确认 RED 原因是模块/行为缺失，而不是测试 fixture 错误。

### Step 1.2 — RED：公式与物理方向

新增失败用例：

- explicit 4/8-point DFT 手算 `Pxx/Pyy/Pxy`；
- even/odd NFFT 的 DC/interior/Nyquist 单边倍增；
- `y=2x` → H1=2、0°；
- `y=-x` → magnitude=1、相位为 ±180°；
- `y[n]=x[n-d]` → 相位斜率为负，量值对应 `d/fs`；
- H1/H2 方向正确；
- zero excitation 无 Inf，invalid mask/warning 正确；
- 输入/输出整体按 `1e-12` 与 `1e12` 缩放时，有效 mask、H 与 coherence 在浮点容差内
  保持不变，证明近零判据不含绝对工程量 floor；
- valid coherence 在 `[0,1]`；
- unwrap 不跨 NaN gap。

### Step 1.3 — 实现最小数学核心

在 `signal/frf.py` 实现：

1. frozen `FrfParams/FrfEffectiveFacts/FrfResult`；
2. `get_frf_window(..., periodic=True)`；
3. 输入/timebase/preflight validator；
4. full-segment start resolver；
5. bounded-block PSD/CSD accumulator；
6. H1/H2/coherence/invalid-bin mask；
7. display derivation helpers（linear/dB/wrapped/unwrapped）；
8. cancel/progress callbacks。

实现注意：

- `Pxy = conj(X)*Y`；
- periodic Hann 用 `np.hanning(n+1)[:-1]`；
- 临时 block 预算 ≤64 MiB，不一次 stack 全部段；
- noverlap 采用 floor；尾部不用；
- display helper 不修改 raw result；
- `FrfEffectiveFacts` 只含数值事实，不含 channel identity/unit；生产 adapter 以后负责成对
  传真实 time arrays 并组装身份/单位 metadata；
- 没有 `except Exception: pass`。

### Step 1.4 — SciPy reference 与 golden vectors

`tests/test_frf_scipy_parity.py`：

```python
scipy_signal = pytest.importorskip("scipy.signal")
window = get_frf_window(...)
# welch/csd 均显式传 window/nperseg/noverlap/nfft/detrend/scaling/return_onesided
```

分别比 `Pxx/Pyy/Pxy/H1/H2/coherence`，建议有效 bins 用
`rtol=1e-10, atol=1e-12`；invalid mask 单独比较。添加 seeded deterministic vectors；将一组
不依赖 SciPy 的预期值固化进 `tests/test_frf.py`。

### Step 1.5 — Import boundary

扩展 subprocess 测试，断言 import 后 `sys.modules` 无：

```text
scipy
PyQt5
matplotlib.pyplot
mf4_analyzer.ui
```

### Step 1.6 — Focused GREEN

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_frf.py \
  tests/test_frf_scipy_parity.py \
  tests/test_signal_no_gui_import.py
```

### Gate G1

- [x] 手算、物理、golden 和 SciPy parity 全绿；
- [x] reference tests 明确报告 SciPy installed 或 skipped；
- [x] 无 SciPy/Qt/matplotlib runtime import；
- [x] 数值 review 确认 `Pxy`、单边 scale、short-data 和 invalid-bin 语义。

## Task 2 — FRF cache、coordinator 与异步生命周期

**Files**

- Modify: `mf4_analyzer/ui/analysis_cache.py`
- Create: `mf4_analyzer/ui/main_window/frf_coordinator.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`（仅构造/注入/统一失效接入）
- Modify: `mf4_analyzer/ui/analysis_worker.py`（若现 worker 需要 neutral callable adapter）
- Create: `tests/ui/test_frf_coordinator.py`
- Modify: `tests/ui/test_analysis_cache.py`（若实际文件名不同，在 Task 0 修正）
- Modify: `tests/ui/test_compute_progress_integration.py`
- Modify: `tests/ui/test_task4_cache_invalidation.py`
- Modify: `tests/ui/test_main_window_state_ownership.py`

### Step 2.1 — RED：双端 cache key

测试 `FrfCacheKey/FrfAnalysisResultCache`：

- input/output 互换得到不同 key；
- compute param 改变得到不同 key；
- display-only 改变得到相同 key；
- time range 改变得到不同 key；
- input 或 output fid invalidation 都清条目；
- LRU capacity=12；
- 同名通道但不同 fid 不碰撞。

### Step 2.2 — RED：coordinator 四条路径

用 fake cache/job service，不构造 MainWindow：

- cache hit：零 submit，发 ready result；
- miss：提交 section=`frf` 且 context 含同一个 key；
- stale completion：pair/params 已改变的旧结果不 put、不 render；
- 缺稳定 View/pane identity 明确失败；同 `pane_idx`、不同持久化 `view_id` 的请求互不
  作废；禁止只用 `view_idx`/`pane_idx`；
- cancel/replace：同 pane 旧 job 被取代；
- 同 pane“取代”首版只做 per-pane generation stale suppression，旧任务不会抢占取消；
- 跨 pane 请求共存：pane A 在途时 pane B 发起新请求，A 的任务不被取消、完成后照常
  put/render（`AnalysisJobService.cancel/replace` 是 section 级整段作废，禁止用它
  实现 pane 替换；同 section 仍按 FIFO 串行，不宣称真正并发）；
- display-only redraw：零 submit；
- preflight error：不 submit，返回结构化 issue。

### Step 2.3 — 实现 owner

- 在 `analysis_cache.py` 增加专用 cache/key，不破坏现 `AnalysisResultCache.make_key()`；
- `frf_coordinator.py` 不 import QtWidgets/MainWindow；
- `window.py` 仅构造 cache/coordinator 并注入 existing services；
- 把 FRF cache 放进统一 close/rebuild/channel-edit invalidation；
- 不新增 `_frf_thread/_frf_queue/_frf_worker`；
- coordinator 对 `frf` 一律普通入队，不调用 service `cancel/replace`；
- 若 `AnalysisComputeWorker` 已支持 callable，则不改；只有明确接口缺口才做最小 adapter。
- 保持现有 worker 字符串 failure signal 兼容，但在 worker seam 补 traceback logging；FRF
  mixin 不得再加一层 broad catch。

### Step 2.4 — Progress/cancel/state ownership gates

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_frf_coordinator.py \
  tests/ui/test_compute_progress_integration.py \
  tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_main_window_state_ownership.py
```

若 state-ownership ratchet 需要扩大 whitelist，判为设计失败；把状态移回 coordinator/holder。

## Task 3 — 专用 `PgFrfCanvas` 三联图

**Files**

- Create: `mf4_analyzer/ui/pg_canvas/frf_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/__init__.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`（仅必要兼容 re-export）
- Create: `tests/ui/test_pg_frf_canvas.py`
- Modify: `tests/ui/test_empty_hint.py`（仅共享契约参数化）

### Step 3.1 — RED：画布纯展示合同

构造合成 `FrfResult`，覆盖：

- 三个 plot 的存在、顺序和共享 frequency X；
- dB/linear、wrapped/unwrapped、log/linear 切换；
- log 模式仅隐藏 DC，不改变 result 长度；
- coherence `[0,1]` 与 threshold line；
- 低相干淡化不删除 curve points；
- NaN gap 不连接；
- 跨三图 cursor 同频并给出四项读数；
- set/get xlim、empty hint、clear/full reset；
- resize 后布局无重叠、底部只显示一个 frequency axis。

### Step 3.2 — 最小实现

实现 `PgFrfCanvas`，复用现有 pyqtgraph theme/font/cursor/empty-hint helper，禁止复制
TimeDomain renderer 或在 host façade 写实现。建议公开最小 API：

```python
set_result(result, display_params, context)
set_display_params(params)
set_xlim(xmin, xmax)
get_xlim()
show_empty_hint(text)
clear()
```

若复用 shared helper 需更改 `_CanvasBackref`，同时更新 owned/delegate declarations 和
`tests/ui/test_pg_canvas_backref_invariants.py`；不要以 undeclared writes 绕过。

### Step 3.3 — Render probe

写 deterministic offscreen probe（脚本放 `scripts/` 还是测试 helper 由实施 review 决定，
临时输出放 `.state/`），至少生成：

- dB/log/unwrapped；
- linear/linear/wrapped；
- 低相干淡化和 NaN gap。

自动比较尺寸、panel bounds、axis labels、非空像素和基准差异；不让用户逐图肉眼找。

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_frf_canvas.py \
  tests/ui/test_empty_hint.py \
  tests/ui/test_pg_canvas_backref_invariants.py
```

## Task 4 — Toolbar、ChartStack、Inspector、预设与统一命名

**Files**

- Modify: `mf4_analyzer/ui/toolbar.py`
- Modify: `mf4_analyzer/ui/chart_stack/_helpers.py`
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Modify: `mf4_analyzer/ui/inspector.py`
- Add in owning inspector package if split is warranted:
  `mf4_analyzer/ui/inspector_sections/frf.py`
- Modify: `mf4_analyzer/analysis_presets.py`
- Modify: `tests/ui/test_toolbar.py`
- Modify: `tests/ui/test_toolbar_i18n.py`
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `tests/ui/test_inspector.py`
- Modify: `tests/test_analysis_presets.py`

### Step 4.1 — RED：五模式名称与 route 一致

测试：

- toolbar labels 精确为 `时域/频谱/时频/频响/阶次`；
- keys 精确为 `time/fft/fft_time/frf/order`；
- mode buttons exclusive，`current_mode/_set_mode/set_enabled_for_mode` 支持 frf；
- mode segment 在项目最小宽度下不截断；
- ChartStack/Inspector 对同一 key 有 page/context；
- `full_reset_all` 清 FRF；
- tooltip 仍含 FFT/FRF 技术名。

### Step 4.2 — RED：FrfContextual

测试控件和信号：

- input/output 用 composite key，不接受 display-only name；
- 同一通道阻断；swap 精确互换 role；
- shared time-range group reparent 后状态不丢；
- estimator/window/segment/overlap/NFFT/detrend 生成 compute params；
- display controls 生成 display params；
- 内建三预设和自定义态；
- `计算频响`、`在时域查看` 信号；
- effective facts/validation message 可见。

### Step 4.3 — 实现

- 新增 FRF icon（如现 Icons 无合适项，在 `ui_kit/icons.py` 增加一项，禁止引入外部资产
  依赖）；
- `ChartStack` 创建 `AnalysisSectionPage` + FRF card 和 manager；
- Inspector 增加 `FrfContextual`，复用 shared range layout；
- analysis preset catalog 加 method=`frf` 专属显示名/patch；
- 只改可见名，内部 keys 不重命名。

### Step 4.4 — Focused tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_toolbar.py \
  tests/ui/test_toolbar_i18n.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/test_analysis_presets.py
```

## Task 5 — Analysis View、项目持久化与 MainWindow 编排接线

**Files**

- Modify: `mf4_analyzer/ui/analysis_view_state.py`
- Modify: `mf4_analyzer/ui/project_io.py`
- Modify: `mf4_analyzer/ui/main_window/analysis_context.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Create: `mf4_analyzer/ui/main_window/_frf_mixin.py`（仅 widget glue；若现 owner 更适合则扩展它）
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `tests/test_project_io.py`
- Modify: `tests/test_project_io_analysis_views.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/ui/test_project_session.py`
- Modify: `tests/ui/test_main_window_state_ownership.py`

### Step 5.1 — RED：role state 与 schema 3

测试：

- `PaneState(input_source, output_source)` round-trip；
- `AnalysisViewState.view_id` round-trip；旧 payload 生成，duplicate 生成新 id，reorder 保持；
- FRF 不把两端复制到 `sources`；
- FRF `ylims={magnitude, phase, coherence}` round-trip；legacy `ylim` 行为不变；
- schema 2 old blob 加载为两端 None；
- duplicate/split 复制 pair 但后续编辑互不污染；
- remap fids 对 input/output 对称；
- `ViewState.view_id` 持久稳定，旧项目缺失时生成；duplicate 生成新 id，reorder 不改变；
- 文件关闭后只清关联 pane；同名不同 fid 不误清；
- view limit 使用 analysis `MAX_VIEWS=6`，不是 TimeDomain 12。

### Step 5.2 — RED：项目恢复

流程测试：

1. 建两 FRF views，含 split、不同 pair/time range/display params；
2. 保存 `.tlproj`；
3. 重开并映射新 fid；
4. 断言 toolbar/chart/inspector 全为 frf；
5. 断言项目不含 numeric result；
6. 首次 render 经 coordinator 重算；缺来源时显示可操作提示；
7. 取消 restore job 后不落 stale result。

### Step 5.3 — 实现 glue

- `AnalysisViewState._SCHEMA = 3`，field-presence tolerant read；
- project restore 的 source-bearing predicate 按 section 识别 `sources` 或 FRF
  `input_source/output_source`，否则 FRF 重开后永远不会进入 recompute queue；
- `AnalysisContext` 注册 FRF page/context/time range，不调用 db-reference resolver；
- `_frf_mixin.py` 只做控件采集、coordinator 调用、canvas render、toast；
- `_on_mode_changed` 进入 frf 时安排 restore/ready render；
- current mode restore 继续调用 `toolbar._set_mode()`；
- `analysis_caches` 与 manager reset/clear/close 路径包含 frf；
- 所有 mutable state 有显式 init/reset owner。

### Step 5.4 — Focused GREEN

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_project_io.py \
  tests/test_project_io_analysis_views.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_project_session.py \
  tests/ui/test_main_window_state_ownership.py
```

## Task 6 — TimeDomain 物理范围关联与回看

**Files**

- Modify owning time-view state/bridge files discovered at Task 0, expected:
  `mf4_analyzer/ui/view_state.py`, `mf4_analyzer/ui/view_bridge.py`
- Modify: `mf4_analyzer/ui/main_window/_frf_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`（仅 mode/view action wiring）
- Create: `tests/ui/test_frf_time_domain_link.py`
- Modify: `tests/ui/test_project_session.py`

### Step 6.1 — RED：范围快照

测试：

- physical-time View 的 committed x-range 能形成 seconds snapshot；
- custom-X View 禁止关联，错误消息精确说明不能把 custom X 当秒；
- range 与 pair source 无交集时阻断；
- 时域连续 pan/zoom 只更新 committed revision/标 stale，FRF submit count 保持 0；
- 点击计算才使用新 range；
- snapshot/project round-trip 不保存 transient cache/job/widget。
- settled range 监听只接 `xrange_changed(float, float)`；不得用高频且混有 Y/restore 事件的
  `visible_range_changed`，不得新增 quiet timer；
- linked FRF pane 保存稳定 source `view_id` + range snapshot，reorder 后仍能识别；

### Step 6.2 — RED：`在时域查看`

测试：

- 创建 dedicated `频响 · output/input` TimeDomain View；
- 只含准确两端 composite keys，X source=time，xlim=effective range；
- 同 signature 再点复用，不重复建 View；
- 不覆盖当前无关 View；
- 同名跨 fid 不折叠；
- 达 12 View 上限时提示并保持原状态；
- 来源关闭后 dedicated View 对称清理。

### Step 6.3 — 实现 owner-held association

优先把 association 作为 FRF pane params/state 的可持久化用户意图，并由既有 time view
manager 提供 committed-range snapshot；不要新增跨 mixin 的散落字段。dedicated View
signature 如需运行时 index，应由 view manager/holder 拥有并在 clear/restore 重建。

### Step 6.4 — Gate G3

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_frf_time_domain_link.py \
  tests/ui/test_project_session.py \
  tests/ui/test_main_window_state_ownership.py
```

- [x] custom-X 不能泄漏为秒；
- [x] pan/zoom burst 零自动 FRF submit；
- [x] dedicated View 非破坏性且身份精确。

## Task 7 — Batch contracts、recipe、preset 与 pair resolver

**Files**

- Modify: `mf4_analyzer/batch_types.py`
- Modify: `mf4_analyzer/batch_recipe.py`
- Modify: `mf4_analyzer/batch_preset_io.py`
- Create or extend neutral owner: `mf4_analyzer/batch_validation.py`
- Prefer Create: `mf4_analyzer/batch_frf.py`（pair rule normalization/resolution；GUI-free）
- Modify: `mf4_analyzer/batch.py`（re-export/dispatcher seam only at this task）
- Modify: `tests/test_batch_preset_dataclass.py`
- Modify: `tests/test_batch_recipe.py`
- Modify: `tests/test_batch_preset_io.py`
- Modify: `tests/test_batch_validation.py`
- Create: `tests/test_batch_frf_pairing.py`
- Modify: `tests/test_native_import_boundaries.py`

### Step 7.1 — RED：portable/runtime 分层

测试：

- `FrfPairRule` 拒绝空 input、空 outputs、self pair、duplicate outputs；
- `ResolvedFrfTask` 含 source/input/output，方向稳定；
- resolved task 同时含 canonical group identity；resolver 返回独立 immutable
  `FrfExecutionPlan`；
- `AnalysisPreset.free_config(method='frf', frf_pair_rules=...)`；
- preset JSON 只写 rules，不写 execution plan/resolved tasks/source ids/paths；
- v1 old preset round-trip 不变；method frf v1 additive field 正常；
- `target_pairs` 老语义和全部既有 tests 不变。

### Step 7.2 — RED：normalizer 字段归属

测试：

- FRF compute/render fields 保留并 canonicalize；
- `weighting/db_reference/rpm/slice/custom-X` 已知异方法字段移除；
- unknown future fields round-trip；
- pair rule 顺序和 output 顺序按用户意图持久化；
- compute fingerprint 排除 coherence threshold 等 display-only 字段；
- render/output fingerprint 包含会改变图片字节的字段。

### Step 7.3 — RED：resolver 与 policy

metadata-only fixtures 覆盖：

- common：任一 selected source 缺 pair 时返回 blocking issues；
- available_per_source：只展开完整 pair，并为每个缺失形成 warning/skip fact；
- split physical file 的多个 logical sources 通道集合可不相同；
- locator/group descriptor 在 identity planning 前绑定；
- stable expansion order；重复 rule 去重；
- preview/run 得到相同 resolved tasks；
- no-load preview tripwire：不得调用 full source loader。
- preview 只能报告 metadata 级 estimated issues，不能声称真实 time arrays/Fs/段数已验证；

### Step 7.4 — 实现

- `batch_frf.py` 只依赖 neutral contracts/descriptors；
- resolved plan 不回写 mutable preset；
- `BatchRunner.SUPPORTED_METHODS` 加 `frf`，但 `_expand_tasks` 的单 channel contract 不强行
  扭曲；为 FRF 提供明确 `_expand_frf_tasks`/resolver seam；
- recipe `_PRESET_FIELDS` 加新字段，`batch_recipe.SUPPORTED_RECIPE_METHODS` 同步加
  `frf`，runtime 字段仍不进 portable serialization；
- validation issues field 使用 `frf_pair_rules/input_channel/output_channels/timebase/segments`，
  供 UI 精准定位。

### Step 7.5 — Focused GREEN

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_batch_preset_dataclass.py \
  tests/test_batch_recipe.py \
  tests/test_batch_preset_io.py \
  tests/test_batch_validation.py \
  tests/test_batch_frf_pairing.py \
  tests/test_native_import_boundaries.py
```

## Task 8 — Batch FRF UI 与 no-load 预览

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Prefer Create: `mf4_analyzer/ui/drawers/batch/frf_pair_editor.py`
- Modify: `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/ui/drawers/batch/pipeline_strip.py`（仅 issue summary 如需要）
- Modify: `tests/ui/test_batch_method_buttons.py`
- Modify: `tests/ui/test_batch_input_panel.py`
- Create: `tests/ui/test_batch_frf_pair_editor.py`
- Modify: `tests/ui/test_batch_output_panel.py`
- Modify: `tests/ui/test_batch_smoke.py`

### Step 8.1 — RED：五个等宽方法按钮

- labels 精确 `时域/频谱/时频/频响/阶次`；
- keys `time/fft/fft_time/frf/order_time`；
- 最窄 Batch 宽度不截断；不再为 `FFT vs Time` 单独压缩字体；
- `_METHOD_FIELDS` 和 sheet `_METHOD_LABELS` 注册 frf。

### Step 8.2 — RED：pair editor

- 一个 input + 多个 explicit outputs；
- 新增/删除 pair group；
- self/duplicate/empty 实时 validation；
- 使用 composite source/channel presentation，不以短 label 存身份；
- common/available policy 切换；
- probe loading/pending/error state 与 method 切换一致；
- 离开 frf 再返回不丢用户配置；
- preset apply/export/import round-trip；
- hidden fields 不参与当前 recipe。

### Step 8.3 — RED：输出预览

- task/data/image group/conflict count；
- stem 显示 `output-over-input`；
- no-load preview loader tripwire；
- representative preview 只选一个 resolved FRF task；
- invalid pair 时 pipeline strip 定位输入阶段，不显示模糊“参数待完善”。

### Step 8.4 — 实现并验证

`FrfPairEditor` 自己拥有局部 widget state，只向 sheet 发 immutable rules；不要直接访问
MainWindow session state。InputPanel 负责组合和 source inventory injection。

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_frf_pair_editor.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_smoke.py
```

## Task 9 — Batch compute、task identity、runner 与 reporter

**Files**

- Modify: `mf4_analyzer/batch_compute.py`
- Modify: `mf4_analyzer/batch_output.py`
- Modify: `mf4_analyzer/batch_grouping.py`
- Modify: `mf4_analyzer/batch_types.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/batch_manifest.py`
- Modify: `tests/test_batch_output.py`
- Modify: `tests/test_batch_grouping_display_name.py`
- Modify: `tests/test_batch_runner.py`
- Modify: `tests/test_batch_run_reporter.py`
- Modify: `tests/test_batch_manifest.py`
- Modify: `tests/test_batch_source_integration.py`

### Step 9.1 — RED：FRF identity

测试：

- source/group/input/output/method/normalized recipe 任一 compute identity 变化 → task id 变化；
- 身份明确分层：compute fingerprint 排除 display-only；coordinated task/artifact id 包含所有
  会改变 CSV/XLSX/PNG 任一请求字节的 recipe/output fields；render group id 含 pair-aware
  members + render params；
- input/output 交换 → task id 变化；
- display name 相同、composite identity 不同 → 不碰撞；
- readable stem 符合 `source__output-over-input__frf__hash`；
- filesystem unsafe Unicode 安全处理；
-现有 single-channel identity tests 原样绿；
- complete artifact set reservation 与 rollback/race tests 覆盖 CSV+PNG。

优先新增 `build_frf_task_output_identity()`，由 `TaskOutputIdentity` additive fields 表达两端；
不要把 JSON pair 塞进可读 channel string 再依赖解析。

同步把 `batch_grouping.RenderTask/_member_identity/group_render_tasks` 和
`GroupOutputIdentity/build_group_output_identity` 扩为 pair-aware；现有 single-channel
三元 member identity 保持兼容。不得把现 `task_id` 称为 pure compute identity。

### Step 9.2 — RED：compute adapter

- 从 LoadedSource 按 composite key 取 input/output 与真实 time；
- 同一 mask 应用两端；
- 不同长度/time/Fs 明确失败；
- 调用唯一 `compute_frf()`；
- 输出 `TaskComputeResult` 和 spool refs 含 raw complex/coherence；
- cancel 在段 block 间响应；
- source split/lazy load 保留 logical identity。
- 正式顺序为 metadata plan → full load + data preflight（尚不写出）→ 最终 task universe
  reservation → compute/write/publish；不能在无样本 preview 中伪造 timebase proof。

### Step 9.3 — RED：runner/reporter/manifest

- 每个 resolved pair 只触发一次 `_RunReporter.started/done/failed/cancelled`；
- `BatchItemResult.input_signal/output_signal` 正确，legacy `signal` 为 pair label；
- item warnings/effective facts 完整；
- manifest v1 non-FRF entries 仍加载；FRF entry 必须有合法 `frf_pair`；
- resume/retry 用 task id/checksum/recipe，不能只靠 `channel`；
- unexpected ImportError 和 programming errors 传播；
- recognized optional renderer failure 只按现有 taxonomy degrade。

### Step 9.4 — 最小 runner 分支

- `batch.py` 分支只负责 load→adapter→report/output orchestration；
- 数学、pair normalization、CSV bytes、Qt render 不回流进 runner；
- 所有结果落 `_RunReporter`，禁止第二段手写 event/record；
- unresolved source identity 在正式任务规划前由 descriptor 修正，不能用 readable suffix
  冒充 canonical group identity。

### Step 9.5 — Focused GREEN

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_batch_output.py \
  tests/test_batch_runner.py -k "frf or identity or reporter or cancel or resume" \
  tests/test_batch_run_reporter.py \
  tests/test_batch_manifest.py \
  tests/test_batch_source_integration.py
```

然后完整运行 `tests/test_batch_runner.py`，因为 dispatcher/expansion 是高扇出 owner。

## Task 10 — FRF CSV、spool、Qt Batch 三联图与 grouped render

**Files**

- Modify: `mf4_analyzer/batch_render_models.py`
- Modify: `mf4_analyzer/batch_series_spool.py`（若现 spool 不支持 complex；保持 neutral）
- Modify: `mf4_analyzer/batch_output.py`
- Modify: `mf4_analyzer/batch_render_qt/_builder.py`
- Modify: `mf4_analyzer/batch_render_qt/_page.py`
- Modify: `mf4_analyzer/batch_render_qt/contract.py`（仅 kind/DTO contract）
- Modify: `mf4_analyzer/batch_render_qt/_models.py`（只 re-export）
- Create: `tests/test_batch_frf_export.py`
- Create: `tests/test_batch_render_qt_frf.py`
- Modify: `tests/test_batch_qt_render_parity.py`
- Modify: `tests/test_batch_render_import_boundary.py`
- Modify: `tests/test_batch_heatmap_producer_contract.py`（仅防误归类守卫如需要）

### Step 10.1 — RED：DTO 和 CSV

- DTO arrays 一维等长，frequency 严格递增，transfer complex；
- 数据表固定 12 列及顺序（CSV/XLSX 经同一 `batch_output.write_dataframe` 列契约）；
- real/imag 可重建 transfer；
- wrapped/unwrapped/coherence 与核心一致；
- log X/threshold/fade 不过滤 DC/低相干行；
- unit/effective facts 在 metadata/manifest；
- empty/invalid arrays fail closed。

若现 spool 只支持 real series，可分别 spool transfer real/imag；不要把 complex 转字符串。

### Step 10.2 — RED：单对三联图

断言：

- kind=`frf` 通过 contract；
- 三 panel 共享 X，标题/labels/units 正确；
- H1/H2、window、NFFT、segments、Fs 进入 facts；
- curve 颜色跨三 panel 一致；
- coherence threshold 和 low-coherence fade；
- log X 不绘 DC 但构建不报错；
- 1920×1080/white/dpi/line width 等现 output settings 生效。

### Step 10.3 — RED：grouped render identity/semantics

- `none`：一 task 一 image；
- `source`：同源一输入多输出；
- `channel`：同名 input/output pair 跨 source；
- member tuple 含 source/group/input/output，且由 neutral `batch_grouping.py` 提供；Qt builder
  不从可读 pair label 反向解析身份；
- 成员顺序不改变 group id；成员集合改变必须改变；
- 超过可读上限时按现 renderer 的分页/限制策略明确处理，不静默漏线；
- preview 与 run 使用同 builder，像素 parity 在容差内。

### Step 10.4 — 实现与 render evidence

`batch_render_models.py` 保持无 Qt；`_builder.py` 添加 frf 分支，不改变 time/fft/heatmap
既有分支。生成 deterministic PNG 到 `.state/frf-render-evidence/`，自动比较：

- single pair；
- one input → 3 outputs grouped by source；
- same pair across 3 sources；
- low-coherence/NaN case。

报告 layout bounds、pixel dimensions、non-white bbox、perceptual/pixel delta；不要要求用户
逐张打开。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q \
  tests/test_batch_frf_export.py \
  tests/test_batch_render_qt_frf.py \
  tests/test_batch_qt_render_parity.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_batch_render_qt.py
```

### Gate G4

- [x] pair resolver → compute → spool → CSV/PNG → manifest 端到端；
- [x] `_RunReporter` 测试证明单一记录路径；
- [x] preview/run task/group identity 相同；
- [x] existing four methods 无输出漂移。

## Task 11 — 帮助、Hints、QuickRef、打包与用户说明

**Files**

- Modify: `mf4_analyzer/ui/hints.py`
- Modify: `mf4_analyzer/ui/quickref.py`
- Modify: `mf4_analyzer/help/__init__.py`
- Create: `mf4_analyzer/help/frf-guide.html`
- Modify: `mf4_analyzer/help/assets/deck.css`（只在 FRF 需要且保持共享时）
- Modify user manual/published guide only where current architecture requires:
  `mf4_analyzer/help/TraceLab-使用说明.html`,
  `docs/analyzer/user-guide/user-guide.html`
- Modify PyInstaller/spec data or hidden-import owners discovered at Task 0
- Modify: `tests/ui/test_quickref.py`
- Modify: `tests/test_help_content.py`
- Modify: `tests/test_packaging_imports.py`
- Modify: `tests/test_windows_build_script.py`（仅若 bundle list 有显式断言）

### Step 11.1 — RED：用户文案

- QuickRef title 从“四个分析模式”变“五个分析模式”；
- rows 使用统一可见名并解释 `频响（FRF）`；
- Batch QuickRef 增加输入/输出配对、common/available 和输出组织；
- Hints 覆盖 FRF 游标、相干性阈值、在时域查看/custom-X 限制；
- hint width/ship state/shortcut registry 既有守卫全绿；
- guide map `guide_path('frf')` 指向存在文件；
- frozen datas 包含 FRF guide。

### Step 11.2 — 编写 guide

至少包括：

- 输入/输出方向与 H1/H2；
- 为什么要看 coherence；
- 窗长/重叠/频率分辨率/段数；
- dB 是传递比，不是绝对声学 reference；
- 时域范围关联与 custom-X 限制；
- Batch 一输入多输出、缺通道 policy、CSV 列；
- NumPy-only 与 SciPy parity 的准确边界；
- 常见失败的可操作修复。

不改历史 dated specs/plans 的版本文字；未要求 release bump 时不改 `APP_VERSION`。

### Step 11.3 — 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_quickref.py \
  tests/test_help_content.py \
  tests/test_packaging_imports.py \
  tests/test_windows_build_script.py
```

## Task 12 — 集成、边界、真实渲染与发布级验收

**Files**

- Tests/evidence only；只修复本功能暴露的 owner 问题，不做顺带 refactor。

### Step 12.1 — 功能组合套件

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q \
  tests/test_frf.py \
  tests/test_frf_scipy_parity.py \
  tests/ui/test_frf_coordinator.py \
  tests/ui/test_pg_frf_canvas.py \
  tests/ui/test_frf_time_domain_link.py \
  tests/test_batch_frf_pairing.py \
  tests/test_batch_frf_export.py \
  tests/test_batch_render_qt_frf.py
```

### Step 12.2 — 架构边界 gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/test_batch_run_reporter.py
```

### Step 12.3 — Existing owner regressions

完整运行这些 owner，而不是只用 `-k frf`：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q \
  tests/test_batch_recipe.py \
  tests/test_batch_preset_io.py \
  tests/test_batch_output.py \
  tests/test_batch_validation.py \
  tests/test_batch_runner.py \
  tests/test_batch_manifest.py \
  tests/test_batch_render_qt.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_project_session.py
```

### Step 12.4 — Full suite（两进程）

按仓库 Qt teardown 契约：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
.venv/bin/python -m pytest -q tests/acquisition_ui
```

异常退出、超时、中断或 segfault 都是 `UNVERIFIED`，不能用已跑过的局部数量推断通过。

### Step 12.5 — real-render 自动比较

以 1600×1000 目标稿为布局参考，运行真实 Qt widget path：

- 单次：empty、ready H1、H2、低相干、split；
- Batch：pair editor、common missing、preview、三种 render grouping；
- 自动输出几何/像素差异摘要和少量代表截图到 `.state/`；
- 原型与运行 App 冲突时，以本 spec + 真实 App 交互为准，记录差异决定。

offscreen 只证明布局/渲染路径，不替代 foreground。

### Step 12.6 — macOS foreground

用真实 TraceLab：

1. 选择输入/输出，跑纯增益/延迟/实测数据；
2. 频率游标跨三图；
3. 修改 display-only 不重算；修改窗长标 stale 并重算；
4. 时域 physical range → FRF；custom X 阻断；FRF → dedicated time view；
5. 保存/重开项目；
6. Batch pair group → preview → run → 检查代表 CSV/PNG/manifest；
7. 取消长任务、关闭窗口，确认线程无残留/Qt warning。

记录真实屏幕证据与 observed facts；不把 prototype 或 offscreen 写成 foreground pass。

### Step 12.7 — Windows frozen gate

若本次交付包含 release：在 fresh Windows Full/Lite EXE 各执行：

- app import/start；
- FRF guide 打开；
- 单次 FRF；
- Batch FRF CSV+PNG+manifest；
- Unicode channel/file stem；
- cancel/close。

只有 source-level packaging tests 时，Windows frozen 必须标 `UNKNOWN/UNVERIFIED`。

### Step 12.8 — Hygiene 与 lessons

```bash
git status --short --branch
git diff --stat
git diff --check
rg -n "min\(len\(|np\.arange\(.*\/.*fs|scipy|matplotlib\.pyplot" \
  mf4_analyzer/signal/frf.py mf4_analyzer/batch_compute.py \
  mf4_analyzer/ui/main_window/frf_coordinator.py
/usr/bin/python3 scripts/lessons/check.py --status
```

如果出现重复 failure pattern、回归测试封住此前漏项或形成新的 durable convention，按
project-lessons 流程 promote；否则记录“不需要新增 lesson”的具体理由。

## 4. 验收追踪表

实施者在执行时填写，不得预先打勾：

| Spec IDs | Owner task | Evidence status |
| --- | --- | --- |
| N1–N9 | Task 1 | [x] 108 个 numeric/SciPy focused tests；广域 FRF/Batch 组合 837 passed |
| U1–U4 | Tasks 2–4 | [x] cache/coordinator/canvas/worker/MainWindow 回归通过 |
| U5–U6 | Task 5 | [x] schema 3、双端持久化、三个 Y range 与 restore 回归通过 |
| T1–T3 | Task 6 | [x] 双真实时间轴、stable view identity、snapshot/effective range 回归通过 |
| B1–B4 | Tasks 7–8 | [x] portable pair rules、ordered resolver、recipe/fingerprint 回归通过 |
| B5、A2 | Task 9 | [x] typed preflight、reservation cleanup、reporter/manifest/resume 回归通过 |
| B6–B8 | Task 10 | [x] 单对/source/channel render、单位、NaN/low-coherence、singleton 回归通过 |
| D1 | Task 11 | [x] help/hints/quickref/user guide/Windows source packaging 检查通过 |
| A1、A3 | Tasks 2/7/12 | [x] import/state ownership/reporter boundary 41 passed, 1 skipped |
| V1 | Task 12.5 | [x] 4 张生产路径 PNG + geometry/pixel/identity/target 结构摘要 |
| V2 | Task 12.6 | [~] PARTIAL：真实 Cocoa MainWindow 单次 FRF 与 BatchRunner 产物通过；未完整跑保存/重开/长任务取消清单 |
| V3 | Task 12.7 | [?] UNKNOWN：未在 fresh Windows Full/Lite frozen EXE 上执行 |

## 5. Completion Record 模板

实施完成后在本节追加，不改写原始计划任务：

```text
实施日期：
分支 / HEAD：
变更文件：
数值 review 结论：
单次 GUI review 结论：
Batch identity/output review 结论：
Focused tests：
Boundary gates：
Main suite：
Acquisition UI suite：
Offscreen real-render：
macOS foreground：
Windows Full/Lite frozen：
git diff --check：
Lessons status：
未验证项 / 风险：
```

### 2026-08-09 完成记录

```text
实施日期：2026-08-08 至 2026-08-09
分支 / HEAD：codex/frf-system-identification / 456ae86d（FRF 变更仍为未提交 worktree diff）
变更文件：git status 108 个路径（产品、测试、spec/plan、lessons）
数值 review 结论：NumPy-only H1/H2/Pxx/Pyy/Pxy/coherence 通过手算、golden、六窗 SciPy fftbins parity、尺度同构与极端溢出回收测试
单次 GUI review 结论：五模式中文统一，FRF 三联图/三 Y range/游标/双端单位/稳定 Time View 关联/项目恢复通过 focused 回归
Batch identity/output review 结论：方向 pair identity、metadata→data preflight→reservation→publish、CSV/PNG/manifest、none/source/channel grouping 与 preview/run 同源通过
Focused tests：FRF/Batch core 837 passed；Batch UI 230 passed；Inspector/FRF canvas/toolbar/chart stack 361 passed；renderer edge 33 passed
Boundary gates：41 passed, 1 skipped
Main suite：5675 passed, 9 skipped, 3 deselected, exit 0（399.42 s）
Acquisition UI suite：355 passed, exit 0（8.11 s）
Offscreen real-render：.state/frf-render-evidence/summary.json；4 张 960×640 生产路径 PNG，含三 panel bounds、producer identity、pixel delta 与 1600×1000 目标结构比较
macOS foreground：PARTIAL；真实 MainWindow ready=True, segments=11, df=1 Hz, invalid=0；真实 BatchRunner 3 tasks/1 group/3 CSV/1 PNG/manifest 通过
Windows Full/Lite frozen：UNKNOWN/UNVERIFIED；仅 source-level hidden-import/help/package 测试通过
git diff --check：通过
Lessons status：lesson_required=False；新增 range-before-validation/stable-restore/button-height lessons，并扩展既有 NaN-gap/singleton lesson
未验证项 / 风险：fresh Windows Full/Lite frozen EXE；macOS 未完整跑保存/重开、长任务取消和关闭线程检查清单；macOS 缺失 Microsoft YaHei 仅触发 Qt 字体别名性能 warning
```

## 6. 回退策略

按依赖层分开回退，禁止留下“UI 可选但 runner 不支持”或“preset 可保存但不能恢复”的
半启用状态：

1. 数值层若 parity 未过，停止在 G1，不注册任何 UI/Batch method；
2. 单次 UI 未过时，`frf` mode registration、page、inspector、project fields 作为一个原子
   feature slice 回退，保留已验证但未暴露的 neutral core 需重新获得用户确认；
3. Batch 未过时，`SUPPORTED_METHODS/recipe/preset/UI/runner/render` 的 FRF 注册必须原子回退，
   不得只隐藏按钮；
4. grouped render 有问题可暂时把 FRF 可见选项收敛为“每对一张”，但必须同步 spec、preset
   validator 和 QuickRef，不能静默忽略已保存 grouping；
5. Windows frozen 未验证不要求回退已通过的 source/offscreen 代码，但发布状态必须保持
   `NO-GO/UNKNOWN`，不得宣称 release complete。
