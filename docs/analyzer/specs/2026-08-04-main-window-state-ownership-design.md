# MainWindow 状态所有权治理 · 设计(包 E)

- 日期:2026-08-04
- 基线:`main` @ `e385ce5a`(v7.9.3 + 通道表达式功能)。**本文所有行号以此 commit 为准。**
  (由 `6236a5fe` 更新;间隔仅一次 feature 提交 `6bda7ccb`,未触碰 main_window,行号不变。)
- 来源:2026-08-04 全仓复杂度评审(main_window mixin 组装深度探查)。
- 实施计划:[2026-08-04-main-window-state-ownership-implementation.md](../plans/2026-08-04-main-window-state-ownership-implementation.md)
- 前置:无硬前置;但建议在包 A–D 中至少一包完成后再做(先建立手感)。
- **定位:五包中问题最深、最需要克制的一包。本包刻意只做地基,不做大搬迁。**

## 问题本质

`ui/main_window/` 的 8-mixin 拆分(`window.py:97-100` 的 MRO)是**名义拆分**:
方法搬进了 8 个文件,但状态没有跟着走。评审实测(实施计划 Task 0 会重新推导核实):

- 全类约 **70 个实例属性**,其中 **62 个在 `window.py` 赋值**;`_fft_mixin` 拥有
  0 个自有状态,纯读他人。
- **17 个属性在多个文件被赋值**(最危险的一类):`_custom_xaxis_ch/_fid/_spec` +
  `_custom_xlabel`(window + `_view_mixin`)、`_primary/_secondary/_focused_view_idx`
  (window + `_view_mixin`)、`_analysis_progress_tokens`(window + `_order_mixin` +
  `_fft_time_mixin`,**三处**)、`_restoring_project`(`_project_io_mixin` +
  `_channel_scope_mixin`,两个 mixin 之间)等。
- 跨文件调用双向(window→mixin 110 次,mixin→window 82 次);`AnalysisMixin`
  被 FFT/Order/FFTTime 三个 mixin 调用 36 次——它事实上是服务层,却靠 MRO 混入。
- 无任何 `Protocol`/`TYPE_CHECKING` 契约;142 个 UI 测试文件中 0 个按 mixin 测试,
  全部经由完整 `MainWindow()`(267 次实例化)。
- 后果:近两月 71 次 window.py 提交中 **42% 同时改了目录内 ≥2 个文件**——文件边界
  没有收住任何改动。

**因此本包的目标不是「把 window.py 变小」,而是「让状态各有其主」。**
衡量指标:多文件赋值属性数 **17 → ≤8**;这个指标由一条常驻测试机械看守(D-E0)。

## 设计决策

**D-E0 · 状态所有权棘轮测试(本包的核心交付,先于一切改动)**

仓库已有先例:`tests/ui/test_pg_canvas_backref_invariants.py` 用 AST 断言协作者的
写穿集合等于白名单。仿此新增 `tests/ui/test_main_window_state_ownership.py`:

- AST 扫描 `mf4_analyzer/ui/main_window/*.py`,收集每个文件中 `self.X = ...` /
  `self.X: T = ...` 赋值的属性名(含增强赋值);
- 断言「在 ≥2 个文件被赋值的属性集合」**恰好等于**冻结白名单(基线上实测生成);
- 白名单只允许缩小:后续每完成一簇迁移,从白名单删除对应条目——**新增多文件
  赋值属性会立即红**,这就是防止回潮的棘轮。

**D-E1 · `AnalysisMixin` 的服务面 → 显式协作对象 `AnalysisContext`**

目录里已有正确形态的先例:`fft_time_coordinator.py:38` 的
`FftTimeCoordinator(QObject)`。新建 `ui/main_window/analysis_context.py`:

- 迁入被跨 mixin 调用的服务方法(评审实测清单,Task 0 重推导:
  `_mask_time_range`、`_pane_time_range_for`、`_analysis_cache_key`、
  `_resolve_db_reference_for_source`、`_emit_compute_feedback`、`_analysis_page`、
  `_capture_active_analysis_view`);
- `MainWindow.__init__` 构造 `self._analysis_ctx = AnalysisContext(...)`,依赖
  (inspector / analysis_managers / chart_stack 等)**构造时显式注入**,不再经
  `self` 命名空间隐式获取;
- `AnalysisMixin` 原方法全部变一行委托——**MRO 不变、调用方零改动**。
  是否最终取消该 mixin,留待后续单独决策,本包不做;
- 收益立现:`AnalysisContext` 的纯逻辑(时间范围掩码、缓存键、dB 参考解析)
  第一次能**脱离 MainWindow 单测**。

**D-E2 · 三簇多文件赋值状态 → 命名持有者**

| 簇 | 属性 | 归宿 |
| --- | --- | --- |
| 自定义 X 轴 | `_custom_xaxis_ch/_fid/_spec`、`_custom_xlabel` | 新 dataclass `CustomXAxisState`,单实例挂 window,读写两文件全部改经它 |
| View 焦点 | `_primary_view_idx`、`_secondary_view_idx`、`_focused_view_idx` | 优先并入既有 `view_manager`;不合适则独立 `ViewFocusState`(Task 0 依据 view_manager 现状定夺,结论记档) |
| 进度令牌 | `_analysis_progress_tokens`(三处赋值) | 并入既有 `AnalysisJobService`(`window.py:116`) |
| 恢复守卫 | `_restoring_project`(两个 mixin 间) | 显式 guard 对象(或 `ProjectIOMixin` 单独持有 + 只读查询方法) |

**兼容策略(硬约束):** 测试可能直接 poke 这些属性(`window._custom_xaxis_ch = ...`)。
Task 0 必须 grep 测试对每个目标属性的直接访问;有访问的属性在 `MainWindow` 上保留
**property 读写垫片**(转发到持有者),测试零改动。垫片带注释标记为兼容层。

**D-E3 · 显式不做(留待后续独立立项)**

- **时域模块抽取**(`_plot_time_on_canvas` 333 行 + `_build_time_plot_data` 261 行,
  `window.py:2519-3159`):这是最终目标,但它触碰的共享状态最多,必须等 D-E1/D-E2
  落地、棘轮白名单显著缩小后另行立 spec。本包结束时若白名单 ≤8,即视为达到
  该后续工作的启动条件。
- 不取消任何 mixin、不改 MRO、不拆 `_connect`(297 行)——拆 `_connect` 只是把
  一个长方法变一组长方法,接线应随状态迁移逐步跟走。
- 不动 `__init__.py` 的 monkeypatch 锚点(33 行注释写明是测试套件契约)。

## 新增测试汇总

1. `tests/ui/test_main_window_state_ownership.py`(D-E0 棘轮)。
2. `tests/ui/test_analysis_context.py`:`AnalysisContext` 纯逻辑直接单测
   (时间范围掩码边界、缓存键稳定性与区分度、dB 参考解析回退链),
   **不构造 MainWindow**。
3. 三簇持有者各配最小单测(状态转移与默认值;`CustomXAxisState` 的
   设置/清除/标签派生)。

## 验收准则

1. 棘轮测试落地且白名单从基线 17 条降到 **≤8 条**;每条删除都有对应迁移 commit。
2. `tests/ui/` 全量失败集与基线一致(`main` 上既有 `test_split_*` 红除外);
   `test_main_window_smoke.py`、`test_analysis_multiview_integration.py`、
   `test_view_switch_integration.py`、`test_project_session.py`、
   `test_view_channel_scope.py`、`test_compute_progress_integration.py` 重点核对。
3. 新增测试全绿;`AnalysisContext` 单测不 import `MainWindow`。
4. **真机验收:** 打开数据 → 时域出图 → 设自定义 X 轴 → 分屏 → 切焦点 View →
   跑一次 FFT / Order / FFT-Time(观察进度反馈)→ 保存工程 → 重开工程还原。
   每步行为与基线一致。
5. window.py 行数**不作为**验收指标(见「问题本质」);允许因垫片小幅上升。
