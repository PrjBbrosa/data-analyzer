# MainWindow 状态所有权治理 · 实施计划(包 E)

> **For agentic workers:** 这是五包中最需要克制的一包。逐任务执行,每任务独立
> commit + 验证;任何一步把既有测试改红且 30 分钟内定位不到原因 → revert 该任务
> 并停下回报。**禁止超出 spec 范围的"顺手重构"**——本包的成功标准是棘轮白名单
> 缩小,不是行数减少。

**设计文档:** [2026-08-04-main-window-state-ownership-design.md](../specs/2026-08-04-main-window-state-ownership-design.md)
**基线:** `main` @ `e385ce5a`(若前包已合并,Task 0 重定位行号)。
分支:`refactor/main-window-state-ownership`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`
**核心回归集(下称 `CORE`)=** `tests/ui/test_main_window_smoke.py tests/ui/test_analysis_multiview_integration.py tests/ui/test_view_switch_integration.py tests/ui/test_project_session.py tests/ui/test_view_channel_scope.py tests/ui/test_compute_progress_integration.py`
(注意:smoke 4637 行,跑一轮较久;单任务迭代时可先用 `-x -k` 聚焦,任务收尾必跑全集。)

## Task 0: 状态清查 + 锚点核验 + 基线(失配即停)

- [x] **Step 1(状态清查脚本):** 写一次性脚本(放 scratchpad,不入库):AST 扫描
  `mf4_analyzer/ui/main_window/*.py`,输出「属性 → 赋值文件列表」全表。
  确认多文件赋值属性集合与 spec 所列 17 条一致;不一致以实测为准,更新后续任务
  的目标清单并在 `docs/analyzer/verify/main-window-state-inventory.md` 记录全表。
  → **实测 16 条**(spec 的 `view_manager` 是关键字实参误计);目标 16 → 7。
- [x] **Step 2(锚点):** 确认 `window.py:97-100` MRO、`fft_time_coordinator.py`
  与 `AnalysisJobService`(`window.py:116` 附近)存在;grep `AnalysisMixin` 的
  服务方法清单(spec D-E1 七个名字)在 `_analysis_mixin.py` 中的行号,以及
  FFT/Order/FFTTime 三个 mixin 对它们的调用点。→ 全部命中,无需重定位。
- [x] **Step 3(测试 poke 审计):** 对 17 个目标属性逐个
  `grep -rn "<属性名>" tests/`,记录哪些测试直接读/写——这些属性必须留
  property 垫片。结论进 inventory 文档。→ 另发现 3 处 **fake 对象**测试,
  推出「只改写点、不动读点」的迁移手法(inventory §4)。
- [x] **Step 4(基线):** → `2 failed, 2914 passed` (341s)。
  `PYTEST tests/ui/ -q > docs/analyzer/verify/main-window-state-baseline.txt 2>&1 || true`
  (全量,含既有红;后续所有对比以此为准。)

## Task 1: 状态所有权棘轮测试(先立法,后施工)

**Files:** Create `tests/ui/test_main_window_state_ownership.py`

- [x] **Step 1:** 按 spec D-E0 实现(参考
  `tests/ui/test_pg_canvas_backref_invariants.py` 的 AST 手法)。白名单 = Task 0
  Step 1 实测集合,按属性名排序、每条注释「当前赋值文件」。
  → 扫描限定 `MainWindow` + `*Mixin` 类,`FftTimeCoordinator` 等协作类不计入。
- [x] **Step 2:** 基线跑绿,commit。此后每个迁移任务的收尾动作都是「从白名单
  删条目 + 本测试转绿」。→ 16 条白名单,5 passed。

Run: `PYTEST tests/ui/test_main_window_state_ownership.py -q`

## Task 2: `AnalysisContext` 协作对象

**Files:** Create `mf4_analyzer/ui/main_window/analysis_context.py`、
`tests/ui/test_analysis_context.py`;Modify `_analysis_mixin.py`、`window.py`。

- [x] **Step 1(单测先行):** 对七个服务方法先写 `test_analysis_context.py`
  ——**当前先经由 MainWindow 调用**取得基线行为(时间掩码边界、缓存键对
  参数变化的区分度、dB 参考回退链),期望值实测固化。基线跑绿,commit。
- [x] **Step 2:** 创建 `AnalysisContext`(普通类或 QObject,依是否需要信号定,
  参考 `FftTimeCoordinator`):七个方法体**逐字迁入**,`self.<依赖>` 改为构造
  注入的显式字段(inspector / analysis_managers / chart_stack /
  `_analysis_view_cache` 等,以方法体实际触碰为准,逐个列举,禁止整个
  window 注入——那等于没拆)。
- [x] **Step 3:** `window.__init__` 构造 `self._analysis_ctx`;`AnalysisMixin`
  七个方法改一行委托。**调用方(三个分析 mixin)零改动。**
- [x] **Step 4:** `test_analysis_context.py` 改为直接构造 `AnalysisContext`
  (伪造最小依赖),断言与 Step 1 相同的期望值;确认文件内无
  `import MainWindow`。
- [x] **Step 5:** 验证。→ 全量 `tests/ui/` 失败集与基线一致(2 failed, 2960 passed)。

Run: `PYTEST tests/ui/test_analysis_context.py tests/ui/test_main_window_state_ownership.py -q && PYTEST <CORE> -q`

## Task 3: `CustomXAxisState`

**Files:** Modify `window.py`、`_view_mixin.py`;持有者类可放
`ui/main_window/_state_holders.py`(新建,本任务与 Task 4/5 共用);
新增单测并入 `tests/ui/test_main_window_state_ownership.py` 同目录新文件
`tests/ui/test_main_window_state_holders.py`。

- [x] **Step 1:** 定义 `CustomXAxisState`(dataclass:`ch` / `fid` / `spec` /
  `xlabel`,加 `clear()` 与派生查询,以现有用法为准)。单测:设置/清除/
  默认值。
- [x] **Step 2:** 两个文件中对四个属性的全部**写**改经 `window._custom_xaxis`;读点
  一律不动(靠垫片转发,见 inventory §4)。`_apply_xaxis` 例外,见 inventory §4c。
  原文:两个文件中对四个属性的全部读写改经 `window._custom_xaxis`
  (Task 0 inventory 给出精确位置清单);测试 poke 过的属性名留 property 垫片。
- [x] **Step 3:** 白名单删 4 条;验证。→ 16 → 12,CORE 267 passed。

Run: `PYTEST tests/ui/test_main_window_state_holders.py tests/ui/test_main_window_state_ownership.py -q && PYTEST <CORE> -q`
(重点:自定义 X 轴相关用例——`grep -l "custom_x\|xaxis" tests/ui/` 找到的文件全跑。)

## Task 4: View 焦点状态归位

**Files:** Modify `window.py`、`_view_mixin.py`;可能 Modify `ui/view_state.py`。

- [x] **Step 1(决策步):** 读 `view_manager`(`ui/view_state.py`)现状,判断
  `_primary/_secondary/_focused_view_idx` 并入它是否自然(它是否已管理 View
  生命周期与索引)。**把决策与理由写进 inventory 文档**;不自然则用
  `_state_holders.py` 的 `ViewFocusState`。
  → **决定不并入 `ViewManager`**,改用 `ViewFocusState`;三条理由见 inventory §4d。
- [x] **Step 2:** 迁移**写**点 + 垫片(同 Task 3 手法);白名单删 3 条。→ 12 → 9。
- [x] **Step 3:** 验证,重点分屏/焦点/12-View 相关:→ 78 passed;CORE 267 passed。
  **真机抽查改为交人工清单**(见最终报告),本 agent 不启动 GUI。
  `PYTEST tests/ui/test_view_switch_integration.py tests/ui/test_view_channel_scope.py tests/ui/test_main_window_state_ownership.py -q && PYTEST <CORE> -q`
  注意 CLAUDE.md:View 溢出/tab 压缩/拖拽重排是产品约束,真机抽查一次。

## Task 5: 进度令牌与恢复守卫

**Files:** Modify `window.py`、`_order_mixin.py`、`_fft_time_mixin.py`、
`_project_io_mixin.py`、`_channel_scope_mixin.py`。

- [ ] **Step 1:** `_analysis_progress_tokens` 三处赋值收进 `AnalysisJobService`
  (它已存在,加最小接口:发放/失效/查询令牌);两个分析 mixin 改调服务方法。
  白名单删 1 条。
- [ ] **Step 2:** `_restoring_project`:归 `ProjectIOMixin` 单独持有(或 guard
  对象),`_channel_scope_mixin` 改为只读查询。白名单删 1 条。
- [ ] **Step 3:** 验证:
  `PYTEST tests/ui/test_compute_progress_integration.py tests/ui/test_project_session.py tests/ui/test_main_window_state_ownership.py -q && PYTEST <CORE> -q`

## Task 6: 剩余多文件属性逐条处置 + 收尾

- [ ] **Step 1:** 白名单剩余条目(约 8 条:`_active`、`_fc`、`files`、
  `_project_path`、`_blf_dbc_history`、`view_manager`、`_analysis_restore_pending`、
  `_applying_analysis_view`,以实测为准)逐条写处置结论:本包迁移 / 留待时域
  抽取时处理 / 属合理共享(说明为何)。**目标 ≤8 条,不强求归零**。
- [ ] **Step 2:** `PYTEST tests/ui/ -q` 全量,对比 Task 0 基线,差异为空
  (新增测试除外)。
- [ ] **Step 3:** 真机验收:spec 验收第 4 条的完整操作链,逐步核对。
- [ ] **Step 4:** PR 描述:inventory 全表、白名单变化(17 → N)、垫片清单、
  Task 4 决策记录;并注明「时域模块抽取的启动条件已/未达成」。

## 明确禁止

- 禁止抽取时域绘图(spec D-E3);禁止取消 mixin 或改 MRO;禁止拆 `_connect`。
- 禁止把整个 `window` 对象注入 `AnalysisContext`。
- 禁止删除 `__init__.py` 的 monkeypatch 锚点或改测试的 patch 路径(垫片方案
  已保证零测试改动;个别确需改动的,逐条列入 PR 描述)。
