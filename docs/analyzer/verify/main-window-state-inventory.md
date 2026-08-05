# MainWindow 状态所有权 · 清查表(包 E · Task 0)

- 日期:2026-08-06
- 基线:`main` @ `b886a30e`(spec/plan 写的 `e385ce5a` 与之只差 docs 提交,
  `mf4_analyzer/` 产品代码零差异,行号锚点直接可用)。
- 分支:`refactor/main-window-state-ownership`
- 方法:一次性 AST 脚本扫描 `mf4_analyzer/ui/main_window/*.py`(脚本按计划要求
  放 scratchpad,不入库)。

## 0. 「写」的判定口径(棘轮测试同款)

本清查与 `tests/ui/test_main_window_state_ownership.py` 使用**同一口径**。
对 `self.X`,以下算一次「写」:

| 形态 | 算写? | 理由 |
| --- | --- | --- |
| `self.X = v` / `self.X: T = v` / `self.X += v` | 是 | 直接重绑定 |
| `for self.X in ...` / `with ... as self.X` / `(self.X := v)` | 是 | 同上,只是语法糖 |
| `self.X[k] = v` / `del self.X[k]` | **是** | X 是**裸容器**(dict/list),条目写入等于
  在无主状态上直接改;spec D-E2 点名的 `_analysis_progress_tokens` 正属此类 |
| `self.X.field = v` | **否** | X 是**具名持有者对象**,写入经它自己的类型化接口——
  这正是本包要达成的目标形态,而不是要消灭的形态 |
| `self.X.method(...)` | 否 | 方法调用,持有者自己维护不变量 |
| `f(X=v)` 关键字实参 | 否 | 不是赋值(见下方 `view_manager` 纠正) |

> 这条口径把「裸容器散写」和「持有者受控写」区分开。本包的迁移动作就是把前者
> 转成后者,因此棘轮下降是**真实的所有权转移**,不是计数游戏。

## 1. 与 spec 所列 17 条的差异(以实测为准)

spec「问题本质」称 17 条多文件赋值属性。**实测 16 条。**

差异唯一来源:`view_manager`。评审把 `_project_io_mixin.py:1258` 的
`view_manager=vm` 计成了赋值,但那是 `pio.ProjectDocument(...)` 的**关键字实参**,
不是对 `self.view_manager` 的写。全仓 `self.view_manager = ...` 只有
`window.py:266` 一处。

**结论:基线白名单 = 16 条**,后续任务目标清单据此更新
(计划 Task 6 的「约 8 条」相应变成 **7 条**)。其余 16 条与 spec 描述逐条吻合,
计划的任务切分不受影响。

其他实测数据与 spec 一致:
- `window.py` 赋值 62 个属性(spec:62)。
- MainWindow 全类 70 个实例属性(76 减去 `fft_time_coordinator.py` 自有的 6 个,
  后者是独立协作类)。
- `_fft_mixin.py` 自有状态 0 个,纯读他人(spec 同)。

## 2. 各文件写入规模

| 文件 | 行数 | 写到的属性数 | 写次数 |
| --- | ---: | ---: | ---: |
| `window.py` | 3629 | 62 | 96 |
| `_view_mixin.py` | 510 | 9 | 24 |
| `_project_io_mixin.py` | 1478 | 8 | 15 |
| `fft_time_coordinator.py` | 245 | 6 | 10 |
| `_order_mixin.py` | 736 | 2 | 7 |
| `_fft_time_mixin.py` | 628 | 2 | 7 |
| `_channel_scope_mixin.py` | 412 | 2 | 2 |
| `_analysis_mixin.py` | 879 | 1 | 2 |
| `_drop_import_mixin.py` | 132 | 1 | 2 |
| `_fft_mixin.py` | 417 | **0** | 0 |
| `__init__.py` / `_sentinel.py` | 33 / 13 | 0 | 0 |

## 3. 基线白名单全表(16 条)+ 测试 poke 审计 + 处置

「测试直接访问」列的统计范围是整个 `tests/` 树;**写**指 `X.attr = ...` 或
`X.attr[...] = ...`,**读**指其余 `.attr` 访问。有访问 → 迁移后必须留 property 垫片。

| # | 属性 | 赋值文件(次数) | 测试写 | 测试读 | 归宿 | 任务 |
| --- | --- | --- | ---: | ---: | --- | --- |
| 1 | `_custom_xaxis_ch` | `_view_mixin`(3)、`window`(5) | 9 | 6 | `CustomXAxisState` | T3 |
| 2 | `_custom_xaxis_fid` | `_view_mixin`(3)、`window`(5) | 9 | 6 | `CustomXAxisState` | T3 |
| 3 | `_custom_xaxis_spec` | `_view_mixin`(3)、`window`(4) | 15 | 10 | `CustomXAxisState` | T3 |
| 4 | `_custom_xlabel` | `_view_mixin`(2)、`window`(4) | 9 | 3 | `CustomXAxisState` | T3 |
| 5 | `_focused_view_idx` | `_view_mixin`(5)、`window`(3) | 0 | 3 | View 焦点持有者 | T4 |
| 6 | `_primary_view_idx` | `_view_mixin`(1)、`window`(1) | 0 | 6 | View 焦点持有者 | T4 |
| 7 | `_secondary_view_idx` | `_view_mixin`(2)、`window`(1) | 0 | 4 | View 焦点持有者 | T4 |
| 8 | `_analysis_progress_tokens` | `_fft_time_mixin`(1)、`_order_mixin`(1)、`window`(1) | 12 | 12 | `AnalysisJobService` | T5 |
| 9 | `_restoring_project` | `_channel_scope_mixin`(1)、`_project_io_mixin`(2) | 0 | 0 | `ProjectIOMixin` 单独持有 | T5 |
| 10 | `_active` | `_project_io_mixin`(3)、`window`(2) | 1 | 0 | 见 §5 处置 | T6 |
| 11 | `_analysis_restore_pending` | `_project_io_mixin`(1)、`window`(1) | 0 | 0 | 见 §5 处置 | T6 |
| 12 | `_applying_analysis_view` | `_analysis_mixin`(2)、`window`(1) | 0 | 0 | 见 §5 处置 | T6 |
| 13 | `_blf_dbc_history` | `_project_io_mixin`(1)、`window`(2) | 0 | 0 | 见 §5 处置 | T6 |
| 14 | `_fc` | `_project_io_mixin`(1 augassign)、`window`(1) | 0 | 0 | 见 §5 处置 | T6 |
| 15 | `_project_path` | `_project_io_mixin`(2)、`window`(1) | 0 | 4 | 见 §5 处置 | T6 |
| 16 | `files` | `_project_io_mixin`(3:1 赋值 + 2 `del`)、`window`(1) | 41 | 209 | 见 §5 处置 | T6 |

**预期棘轮轨迹:** 16 →(T3 −4)12 →(T4 −3)9 →(T5 −2)7。目标 ≤8,达成。

## 4. 迁移的硬约束:假对象(fake)测试

多处测试**不构造 MainWindow**,而是把真实 MainWindow 方法绑到
`SimpleNamespace` / 自定义假类上,假对象只带**裸属性**:

| 测试 | 假对象 | 带的裸属性 | 跑的真实代码 |
| --- | --- | --- | --- |
| `tests/ui/test_view_bridge.py::_Window` | 自定义类 | `_custom_xaxis_spec/_fid/_ch`、`_custom_xlabel` | `ui/view_bridge.py::capture_view` |
| `tests/ui/test_timedomain_hotpath_perf.py` | `SimpleNamespace` | `_custom_xaxis_fid/_ch`、`_custom_xlabel` | `window.py::_plot_time_on_canvas` / `_build_time_plot_data` |
| `tests/ui/test_task4_cache_invalidation.py` | 自定义类 | `_analysis_progress_tokens`、`_analysis_jobs` | `_fft_time_mixin` 的部分路径 |

**由此推出本包的迁移手法(关键决策):**

- **只改「写」点,不动「读」点。** 棘轮只数写;而 property 垫片让所有
  `self._custom_xaxis_ch` 形式的**读**在真 MainWindow 上自动转发到持有者,
  在假对象上仍命中裸属性。两边都不破。
- 反过来若把读点也改成 `self._custom_xaxis.ch`,上表的假对象立刻 `AttributeError`
  ——而 `_plot_time_on_canvas` 恰恰是 spec D-E3 **明令本包不许碰**的时域绘图代码。
  「只改写点」既满足棘轮,又天然守住了 D-E3 的边界。
- `ui/view_bridge.py` 用 `getattr(window, "_custom_xaxis_spec", None)` 形式读,
  垫片同样覆盖;且该文件在 `main_window/` 之外,不受棘轮扫描。

## 4b. Task 2 决策:`AnalysisContext` 只收 D-E1 七法中的四法

计划写「七个方法体逐字迁入」。实测后**迁入 4 个、留下 3 个**,理由逐条如下。
判据是「该方法的依赖能否表达为具名协作者」——能,就迁;需要注入一把
window 方法回调,就等于变相注入整个 window(计划明令禁止),不迁。

**迁入(8 个成员,含 4 个支撑用的私有 helper):**

| `AnalysisContext` 成员 | 原名 | 依赖(构造注入) |
| --- | --- | --- |
| `section_ctx` | `_analysis_ctx` | `inspector` |
| `page` | `_analysis_page` | `chart_stack` |
| `section_uses_time_range` | `_analysis_section_uses_time_range` | 无(纯函数) |
| `normalize_time_range` | `_normalize_analysis_time_range` | 无(纯函数) |
| `mask_time_range` | `_mask_time_range` | 无(纯函数) |
| `pane_time_range_for` | `_pane_time_range_for` | `analysis_managers` + `chart_stack` |
| `channel_reference_facts` | `_channel_reference_facts` | `files_provider` |
| `resolve_db_reference_for_source` | `_resolve_db_reference_for_source` | `inspector` + `db_reference_store` + 上一行 |

`files` 用**零参 provider** 注入而非直接传映射:该属性会被重新绑定
(工程开/关,以及 `tests/ui/test_inspector.py` 里的 `win.files = {}`),
直接持有引用会拿到过期字典。其余四个协作者在 `__init__` 里只赋值一次,直接传引用。

**留在 `AnalysisMixin`(逐条理由):**

1. `_analysis_cache_key` —— 依赖闭包穿透到三个分区 mixin 自有的算法
   (`_fft_analysis_cache_key`、`_order_effective_params_for_source`、
   `_fft_time_effective_params_for_source`……),迁入需注入约 7 个 window 绑定
   callable。**更硬的约束:** `tests/ui/test_task4_cache_invalidation.py` 建了
   `class _StubMW(FFTTimeMixin, AnalysisMixin)`,靠**覆写** `_pane_time_range_for`
   来驱动 `_analysis_cache_key` 的回退分支——它依赖普通 `self.` 分派,
   迁进协作对象就直接失效。
2. `_capture_active_analysis_view` —— 转调 `_capture_analysis_sources`,后者读
   `_opening_project`(window 自有守卫)并调 `_sync_fft_source_summary`
   (window 的 UI 更新方法)。属编排,不属可复用逻辑。
3. `_emit_compute_feedback` —— 只是把 `summarize_compute` 的结果打到
   `toast` + `statusBar` 两个 window UI 出口。纯表现层管道,迁入只会多两个
   注入回调,换不到任何可测性(`summarize_compute` 本身已可单测)。

**兑现的收益:** `tests/ui/test_analysis_context.py` 41 条用例**不构造
MainWindow、不需要 Qt**,0.82 s 跑完(经 MainWindow 时是 2.87 s)。
spec 点名的三项纯逻辑里,时间范围掩码与 dB 参考解析已脱离 MainWindow;
缓存键因上述测试契约留在原处。

## 5. Task 6 剩余条目逐条处置结论

由 Task 6 填写。

## 5b. `tests/ui/` 基线失败集(Task 0 Step 4)

全量:`2 failed, 2914 passed, 1 deselected in 341.55s`
(完整输出见 `main-window-state-baseline.txt`)

1. `tests/ui/test_batch_runner_thread.py::test_sheet_preview_and_result_share_channel_metadata_reference`
2. `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_and_custom_action`

两条都与 `main_window/` 状态无关(一条批处理 runner、一条提示排序)。

> 注:CLAUDE.md 里「`main` 上 `tests/ui/` 有一批 `test_split_*` 红」的说法在本基线上
> **已不成立**——`test_split_*` 全绿。该条 Gotcha 已过期,后续以本文件记录的
> 两条为准。

## 6. 锚点核验(Task 0 Step 2)

全部命中,无需重定位:

| 锚点 | spec/plan 说法 | 实测 | 结论 |
| --- | --- | --- | --- |
| MainWindow MRO | `window.py:97-100` | `window.py:97-100`,8 mixin + `QMainWindow` | ✓ |
| `AnalysisJobService` | `window.py:116` 附近 | `window.py:115-116` | ✓ |
| `FftTimeCoordinator` | `fft_time_coordinator.py:38` | 存在 | ✓ |
| `_analysis_page` | D-E1 七法之一 | `_analysis_mixin.py:64` | ✓ |
| `_emit_compute_feedback` | 同上 | `_analysis_mixin.py:71` | ✓ |
| `_capture_active_analysis_view` | 同上 | `_analysis_mixin.py:159` | ✓ |
| `_mask_time_range` | 同上 | `_analysis_mixin.py:271` | ✓ |
| `_pane_time_range_for` | 同上 | `_analysis_mixin.py:323` | ✓ |
| `_analysis_cache_key` | 同上 | `_analysis_mixin.py:470` | ✓ |
| `_resolve_db_reference_for_source` | 同上 | `_analysis_mixin.py:703` | ✓ |

七个服务方法的跨 mixin 调用点(spec 称 36 次):

| 方法 | `_fft_mixin` | `_order_mixin` | `_fft_time_mixin` | `_project_io_mixin` | `window.py` |
| --- | --- | --- | --- | --- | --- |
| `_analysis_page` | — | 326, 381, 692 | 214, 290, 560 | — | — |
| `_emit_compute_feedback` | 292 | 317, 366, 407 | 205, 271, 341 | — | — |
| `_capture_active_analysis_view` | 224 | 313 | 203 | 1227 | 1132, 1362 |
| `_mask_time_range` | 187 | 44, 86 | 81, 157, 303, 391 | — | 995 |
| `_pane_time_range_for` | 242 | 413 | 57, 233, 314 | — | — |
| `_analysis_cache_key` | — | 345 | — | — | 1109 |
| `_resolve_db_reference_for_source` | 371 | 498 | 446 | — | 1053, 1171 |
