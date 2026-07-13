# 分析编排治理 Phase 1 — 缓存统一与 Job 生命周期 — Design Spec

Date: 2026-07-13
Status: Implemented; verification recorded in the implementation plan Completion Record
Source review: `docs/analyzer/reviews/2026-07-12-current-architecture-assessment.md`
Implementation plan: `docs/analyzer/plans/2026-07-13-analysis-orchestration-governance-implementation.md`

本 spec 承接 2026-07-12 架构评估报告的 AR-01 / AR-02，经 2026-07-13 对工作区
（8f18f480 干净树）的逐条 file:line 核实后成形。报告的证据基本准确；本 spec 对其
方案做了三处修正（见 §2.3），并把范围收敛为一个可独立交付的治理增量。

## 1. Outcome

Phase 1 完成后：

1. FFT-vs-Time 只有一套计算结果缓存（`analysis_caches['fft_time']`），legacy
   `_fft_time_cache` 及其五个配套方法被删除；所有失效路径对称，
   「display-only 改动不重算、compute-input 改动必失效」由测试固定。
2. `_apply_xaxis`（自定义 X 轴）路径的失效不对称被修复：该路径此前只清 legacy
   缓存、不清 `analysis_caches['fft_time']`，而 `do_fft_time` 主查后者
   （`window.py:1865` vs `_fft_time_mixin.py:329`）——疑似现存 stale-hit bug，
   实施第一步用 RED 测试定真伪。
3. FFT-vs-Time 与 Order 两套逐行镜像的 QThread 调度样板
   （`_start_next_*_job` / `_dispatch_*_job` / `_on_*_finished|failed|progress|thread_done`
   + 12 个平铺在 MainWindow 上的线程/队列/进度字段）合并为一个
   `AnalysisJobService`：单实例、按 section 排队、统一取消/进度/关停。
4. 以 FFT-vs-Time 为试点建立第一个不碰 QtWidgets 的 `FftTimeCoordinator`：
   拥有 key 构造、缓存探查、dispatch 决策、pending 簿记和本 section 失效；
   mixin 退化为「widget 参数采集 + 渲染 + toast」。四条路径
   （项目恢复 / 分屏 / 取消 / 缓存命中）有自动验证。
5. 计算结果、渲染视觉、compute cache key 语义零变化：`weighting` 仍是 compute
   输入，`db_reference` / mode / catalog revision 仍是 display-only
   （`_fft_time_mixin.py:57-60` 现契约保持）。

## 2. Evidence And Current State

以下锚点已于 2026-07-13 对 8f18f480 工作树逐条核实。

### 2.1 双缓存（AR-02，核实：准确）

| 事实 | 锚点 |
| --- | --- |
| legacy 存储 + 容量 12 | `window.py:90-91` |
| legacy key（9-tuple）/get/put/clear_for_fid | `_fft_time_mixin.py:90/:116/:125/:133` |
| analysis key（JSON blob，经 `AnalysisResultCache.make_key`） | `_fft_time_mixin.py:55-70` |
| worker 完成同一 result 双写两套缓存 | `_fft_time_mixin.py:780-783` |
| `do_fft_time`：analysis 主查 + legacy 兜底 + 命中回填 | `_fft_time_mixin.py:329-340` |
| `_do_fft_time_single`：legacy 先查、analysis 后查（顺序与主路径相反） | `_fft_time_mixin.py:417-425` |
| close_all 双清 | `_project_io_mixin.py:795/:798-799`（报告引 :779/:782 已漂移） |
| `_apply_xaxis` 仅清 legacy、不清 analysis —— 失效不对称 | `window.py:1865` |
| 其余失效点均走统一入口 `_invalidate_all_analysis_caches_for_fid`，对称 | `window.py:1590/:2498/:2842`、`_project_io_mixin.py:160/:548`、`_fft_time_mixin.py:164-167` |
| 两套 key 字段集相同：`{fid, channel, time_range, fs, nfft, window, overlap, remove_mean, weighting}`；唯一实质差异是 time_range 取值来源（legacy 用 `effective_time_range` :559，analysis 用 `_pane_time_range_for` :68） | `_fft_time_mixin.py:61-70/:104-114` |
| FFT 与 Order 均只用 `AnalysisResultCache`，无第二套 store | `_fft_mixin.py:123/:229`、`_order_mixin.py:271/:329/:751` |
| `AnalysisResultCache` 全部实现仅 41 行（make_key/get/put/invalidate_fid/clear） | `mf4_analyzer/ui/analysis_cache.py` |

### 2.2 三份并存的执行模型（AR-01 的可机械化部分，核实：准确且比报告更重）

| 事实 | 锚点 |
| --- | --- |
| 共享 worker 类，自述为多分析共用而设 | `mf4_analyzer/ui/analysis_worker.py:14` |
| FFT-vs-Time 泵：queue→dispatch→worker→finished/failed/progress→thread_done | `_fft_time_mixin.py:462/:510/:599/:767/:804/:838/:858` |
| Order 泵：与上面逐一镜像 | `_order_mixin.py:406/:445/:748/:775/:795/:815` |
| 普通 FFT 是第三种模型：同步计算、无线程 | `_fft_mixin.py:212` |
| 12 个线程/队列/进度字段平铺在 MainWindow | `window.py:97-98/:106-109/:113-114/:117-120` |
| 关窗清理对两套线程分别手工 cancel/quit/wait/terminate | `window.py:2886-2932` |
| 仓库已有 Qt-free 无 widget 编排器先例（采集侧） | `acquisition_capture/controller.py:29`（`CaptureController`，自述 "Stays Qt-free"） |
| main_window/ 目录无任何非 mixin 编排模块；全仓无 AnalysisSession/Coordinator 类 | 目录清单核实 |

### 2.3 对报告方案的三处修正

1. **AnalysisSession 一步到位有新 God Object 风险。** 报告建议的
   `AnalysisSession`「统一拥有 files、active file、view managers、caches、
   worker/queue」把四类不同风险等级的状态捆进一个对象。核实显示 MainWindow 的
   领域状态天然分为三个正交簇：job 生命周期（12 字段，两套镜像样板，纯机械去
   重）、结果缓存（已有 41 行干净抽象，只是多了一套 store）、文件/视图状态
   （与 navigator、project IO 深度纠缠，搬动风险最高、当下收益最低）。
   **本 spec 采用 services-first**：先抽 JobService 与统一缓存（各自独立可交
   付、有既有测试网），coordinator 只组合服务；「session」若将来需要，是
   façade，不是状态桶。这与仓库已验证的 `CaptureController` + frozen
   `SessionConfig` 范式一致。
2. **AR-02 不只是「未来风险」，已有现存不对称**（`window.py:1865`），修复它是
   Phase 1 的第一个任务，而不是顺带收益。
3. **AR-04（Batch 图片导出适配器）降级为非目标。** 核实结论：Qt 代码 100% 封
   装在 5 个方法约 213 行内（`batch.py:978-1190`），有 `export_image` 开关
   （`:30/:537`）隔离，数值路径与纯数值测试完全不碰 Qt，生产调用点仅 1 处
   （`:565`）。当前无 CLI/CI/服务端消费方，抽取虽低风险但零即时收益；等
   headless 需求真实出现再做（届时按核实清单执行即可，约半天工作量）。

## 3. Goals

### G1 — 单一结果库

FFT-vs-Time 的计算结果只存在于 `analysis_caches['fft_time']`；全仓
grep 不再出现 `_fft_time_cache`（含五个方法与 pending 的 `cache_key` 字段）。

### G2 — 失效对称且单入口

任何使 FFT-vs-Time 结果失效的事件（文件 rebuild、通道编辑、自定义 X 轴、关闭
文件、关闭全部）都经由统一入口作用于唯一 store；不存在只清一套的路径。

### G3 — Job 生命周期唯一实现

「排队、派发、进度、取消、线程回收、关窗清理」只有一份实现；新增第 4 种异步
分析不再复制样板、不再往 MainWindow 添加 `_x_thread/_worker/_queue/_progress_*`
字段簇。

### G4 — 试点验证 coordinator 边界

`FftTimeCoordinator` 不 import QtWidgets、不引用任何 QWidget，可在不构造
MainWindow 的情况下单测；项目恢复 / 分屏 / 取消 / 缓存命中四条路径有自动化证据。

### G5 — 行为零漂移

计算数学、渲染视觉、compute key 字段集、进度 UI 语义、LRU 容量（fft_time=12）
全部不变；现有 `test_cache_key_dataclass_binding` 字段集守卫全程保持绿。

## 4. Non-goals

- 不做 Batch 图片导出适配器（AR-04，降级理由见 §2.3.3；核实产出的抽取清单已
  在 review 记录中，需求出现时直接取用）。
- 不迁移 Order / FFT 到 coordinator（属 Phase 2，等试点验证后再立项）。
- 不动 ViewManager 所有权（AR-03；`stack.py:118-131` 的构造时序耦合留待
  Phase 2 与 Order/FFT 迁移一并处理，本轮只禁止新增直接从 widget 取 manager
  的代码进入 coordinator）。
- 不把普通 FFT 异步化（它保持同步是既有行为，`_fft_mixin.py:212`）。
- 不改 mixin 机制本身，不重命名既有公共方法，不做大规模文件搬迁。
- 不改 compute key 字段集，不把 db_reference/mode/catalog revision 引入 key。
- 不新增第三方依赖。

## 5. Design Contracts

### 5.1 Phase A — 缓存统一（AR-02）

**Key 口径。** 统一使用 `_fft_time_analysis_cache_key`（`_fft_time_mixin.py:55`）
作为唯一 key builder。dispatch 时装入 pending 的 key 与 lookup 时构造的 key 必须
出自同一 builder、同一输入（pane 的 `_pane_time_range_for` 口径）；用测试断言
dispatch-key == lookup-key（扩展既有
`tests/ui/test_task4_cache_invalidation.py:161 TestFallbackKeyAlignsPrimaryKey`）。
legacy 的 `effective_time_range` 口径随 legacy 一并退役；由此损失的「跨口径兜
底命中」是可接受代价（两口径分叉本就意味着 key 语义含混）。

**删除清单（生产代码）。**

| 位置 | 处置 |
| --- | --- |
| `window.py:90-91` 存储+容量 | 删除 |
| `_fft_time_mixin.py:90-145` 五个 legacy 方法 | 删除 |
| `_fft_time_mixin.py:164` 统一入口内 legacy 清理行 | 删除（保留 :166-167 analysis 循环） |
| `_fft_time_mixin.py:331-340` legacy 兜底 + 回填 | 删除（保留 :329 主查） |
| `_fft_time_mixin.py:417/:420` single 路径 legacy 先查 | 删除（保留 :422 analysis 查） |
| `_fft_time_mixin.py:444-450/:580-586` pending `cache_key` 装填 | 移除该字段 |
| `_fft_time_mixin.py:780-781` 双写的 legacy put | 删除（保留 :782-783） |
| `window.py:1773` close-all dispatcher 仅清 legacy | 删除 |
| `_project_io_mixin.py:795` close_all 清 legacy | 删除（:798-799 已覆盖） |

**`_apply_xaxis` 失效修复。** `window.py:1865` 改为经统一入口（或对
`analysis_caches['fft_time']` 的等价 invalidate）。实施顺序强制为：先写复现测
试（自定义 X 轴后触发 `do_fft_time`，断言不得命中旧 analysis 条目）确认真伪；
若 RED 证实 stale-hit，则按 bug 修复记录；若因 key 变化旧条目实际不可达，则
对称化仍需完成（卫生要求），测试改为守卫失效对称性本身。

**测试迁移点。** `tests/test_cache_key_dataclass_binding.py:77`（legacy key 绑定
测试改指 analysis key 或删除，:94 已有 analysis 版）、
`tests/ui/test_task4_cache_invalidation.py:33/:58/:123-134`、
`tests/ui/test_nonuniform_fft_full_flow.py:214/:231/:266/:322`、
`tests/ui/test_compute_progress_integration.py:604/:633/:653`、
`tests/ui/test_main_window_smoke.py:1807/:1968/:2012/:2184/:2231/:2251/:3461`、
`tests/ui/test_analysis_multiview_integration.py:243`、
`tests/ui/test_inspector.py:677`（注释）。断言语义不变，仅把
`_fft_time_cache` / `_fft_time_cache_key` 引用换成
`analysis_caches['fft_time']` / `_fft_time_analysis_cache_key`。

### 5.2 Phase B — `AnalysisJobService`（AR-01 机械部分）

新模块 `mf4_analyzer/ui/analysis_jobs.py`。QObject（可发信号、拥有 QThread），
**零 QtWidgets import**；单实例由 MainWindow 构造持有并在关窗时 `shutdown()`。

**必须保持的语义**（与现行两套泵逐条对应，实现 API 可微调、语义不可变）：

1. **按 section 串行**：每 section 同时至多一个活跃 job，FIFO 队列
   （现 `_fft_time_queue`/`_order_queue`）。
2. **进度 token**：per-section 的 `total_jobs/completed_jobs` 计数与进度信号，
   语义等于现 `_advance_*_progress_job`；`window.py` 的 `_compute_progress`
   显示行为不变（`tests/ui/test_compute_progress_integration.py` 全绿）。
3. **取消**：新请求或显式取消时 `AnalysisComputeWorker.cancel()` + 清本
   section 队列；被取消 job 的结果不得触发 finished 回调。
4. **线程回收**：正常路径 quit()+wait()；关窗路径保留现 terminate 兜底
   （`window.py:2886-2932` 收敛为 `service.shutdown()` 一处）。
5. **回调边界**：service 只发 `finished(section, ctx, result)` /
   `failed(section, ctx, error)` / `progress(section, done, total)`；
   缓存写入与渲染仍由订阅方（Phase C 前是 mixin，之后是 coordinator）完成——
   service 不知道缓存与 canvas 的存在。

FFT-vs-Time 与 Order 两个 section 同轮迁入（这正是去重的意义）；迁移后
MainWindow 上的 12 个字段（§2.2）全部删除。

### 5.3 Phase C — `FftTimeCoordinator` 试点

新模块 `mf4_analyzer/ui/main_window/fft_time_coordinator.py`（非 mixin、非下划
线私有模块——这是 main_window 包里第一个编排层模块，命名刻意区别于 mixin）。

**拥有**：analysis key 构造、缓存探查、dispatch 决策（命中→发渲染事件；未命
中→组 job 提交 JobService）、pending 簿记、本 section 失效入口。
**不拥有**：widget 参数采集（mixin 从 inspector 收集后以 plain dict 传入）、
渲染（coordinator 发事件，mixin 调 canvas）、toast/进度条展示。

**硬边界**：模块内禁止 `QtWidgets` import 与任何 QWidget 引用（QtCore 信号允
许）；用守卫测试机械检查。构造仅需 `AnalysisResultCache` + `AnalysisJobService`
+ key builder 依赖，可在无 MainWindow 环境单测。

**四条验证路径**：

| 路径 | 证据形式 |
| --- | --- |
| 缓存命中 | 命中时零 JobService 提交、发出 render 事件（unit + 既有 smoke `test_fft_time_cache_hit_status`） |
| 取消/被取代 | 新请求取代旧 pending 后，旧结果不落缓存不触发渲染（unit） |
| 分屏 | 两个 pane 不同 time_range 产生不同 key、互不污染（既有 multiview 集成测试保持绿） |
| 项目恢复 | 恢复路径经 coordinator 探缓存，命中零 worker dispatch（既有项目恢复测试保持绿） |

## 6. Migration And Compatibility

- 分阶段独立可交付：Phase A 单独成 PR 意义完整；B 依赖 A（避免 service 还要
  伺候双写）；C 依赖 B。
- 每阶段结束时全部既有守卫（cache-key 字段集绑定、display-only 不变量、统一
  失效入口、compute progress 集成）必须绿；不引入行为开关或过渡兼容层——删
  除 legacy 是原子的，靠测试迁移而非运行时兼容。
- `.tlproj` / preset / QSettings schema 零变化。

## 7. Acceptance Matrix

| ID | 场景 | 证据 |
| --- | --- | --- |
| P1 | `_apply_xaxis` 后 FFT-vs-Time 不命中旧条目 | 新 RED→GREEN 测试（真伪结论记录在案） |
| P2 | 全仓无 `_fft_time_cache` 残留 | `rg -n "_fft_time_cache"` 仅命中历史文档 |
| P3 | dispatch-key == lookup-key（双 pane） | 扩展 `TestFallbackKeyAlignsPrimaryKey` |
| P4 | display-only 改动不重算 / compute 改动必失效 | 既有 smoke `:1807/:3461/:2012` 迁移后保持绿 |
| P5 | LRU 容量与淘汰行为不变（12） | 既有 `:2184` 迁移后保持绿 |
| P6 | 失效单入口对称（rebuild/通道编辑/X 轴/关闭） | `test_task4_cache_invalidation.py` 扩展后全绿 |
| P7 | 两 section 共用一份泵实现；MainWindow 12 字段删除 | JobService 单测 + `rg` 字段审计 |
| P8 | 进度/取消/关窗语义不变 | `test_compute_progress_integration.py` 全绿 + shutdown 单测 |
| P9 | coordinator 无 QtWidgets、可脱离 MainWindow 构造 | import 守卫测试 + coordinator 单测 |
| P10 | 四条路径（命中/取消/分屏/恢复） | §5.3 表内测试各自落名 |
| P11 | compute key 字段集零变化 | `test_cache_key_dataclass_binding.py` 全绿 |

## 8. Definition Of Done

- P1–P11 全部有具名测试或审计输出；
- 计算结果与渲染视觉零变化（无需截图轮，因不触渲染代码；若渲染文件出现 diff
  则越界，停）；
- MainWindow `__init__` 不再含任何 `_fft_time_*` / `_order_*` 线程队列进度字段；
- 新模块（analysis_jobs、fft_time_coordinator）各自单测不依赖 MainWindow 构造；
- 报告的 AR-03/AR-04 处置结论（推迟与降级）连同核实证据记入 review 目录，
  避免下轮重复评估。
