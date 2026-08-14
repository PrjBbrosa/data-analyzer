# v8 后续批次 review 修复 plan

- 日期:2026-08-15
- 上游 review:`docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md`
  (P0/P1/P2 定性、证据与修法方向均在该文,本文只列执行安排,不重复论证)
- 基线:`main@350969f2`
- 执行方式:七个 Task 各由一个 agent 在独立 worktree 执行(F1/F3 用 opus,
  其余 sonnet),各自成提交;主会话负责合并、全量对账、收尾。
- 状态:**已完成**(2026-08-15)。执行旁注:七分支合入
  `claude/post-v8-review-fixes`,全量对账主体 **6978 passed / 9 failed /
  13 skipped**(基线 6891/13/38;F7 四条既有红全部转绿,9 红与基线顺序污染集
  逐条同名,零新增失败,净增 87 条用例)、`tests/acquisition_ui` 359 passed。
  9 条顺序污染在完整顺序下稳定复现、单跑全绿,是既有测试隔离债,
  已在 review §6 留痕,后续单独治理。Cocoa 真机待验清单见 review §7 旁注。

## §0 执行护栏(每个 Task 通用)

- worktree 内验证一律用主仓的绝对 venv 路径:
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest …`
  (在 worktree 根目录下执行,PYTHONPATH=. 指向 worktree)。
- 开工先 `git rev-parse HEAD` 确认基于 `350969f2`;不是就先 ff 对齐再动。
- 只跑聚焦测试,不跑全量(主会话收尾统一跑)。
- 禁区:根 conftest pin、状态所有权/backref/lambda/QSS 各棘轮白名单只许缩小、
  ink/AA 标定常量、性能门禁上限、`{{TOKEN}}` 模板机制。新增信号连接用
  bound method / partial,不用 lambda。宽泛 `except Exception` 必须留痕。
- 每个发现的修复配一条**能抓住原缺陷**的测试(先红后绿;review 里点名的假绿
  用例按其修法收紧)。
- 提交信息引用 review 的发现编号(如 `P0-1`、`§4.3 dim 泄漏`)。

## Task F1(opus):BLF/DBC 数据链

**Files**: `io/blf_format.py` · `io/blf_dbc_candidates.py` · `io/channel_frame.py` ·
`ui/main_window/_project_io_mixin.py`(仅候选状态/文案区段 ~1000-1080)· 对应 tests

- [x] **P0-1**:发现样本独立预算,按 review §2 修法;discovery 扫描搬进使用分支;
  A/B 场景(30000 帧低频 ID)写成回归用例。
- [x] §4.1 完整扫描文案:读 `sampling_strategy`,complete 时「完整解码」;
  「完整匹配」改「ID 命中 A/B」。
- [x] §4.1 取消/截断:`candidate_status` 加 `"incomplete"` 档(排序在 unverified
  与 mismatch 之间、不被 selectable 过滤、独立文案);窗口取消信号接到
  `probe_blf_dbc_frames(cancel_check=...)`。
- [x] §4.1 LazyZohFrame 重名:重复列名 fail-fast 或自动消歧(`Time` 冲突消歧为
  `<Msg>.Time` 一类),ABC docstring 与实现对齐;重写假绿用例(两份不同数据
  的同名 series)。
- [x] §4.1 BLF 探测进度分两个子区间,构造完 `BlfDbcProbe` 才 100%。
- [x] §4.1 杂项:零帧 reason、`is_lazy()` 物化后返回 False、`get_column` 返回
  只读视图或拷贝(与 `__getitem__` 语义拉平)、两处宽泛 except 补
  `logger.warning`。
- [x] 测试收紧:`test_blf_batch_import.py:317` 陈旧桩补新字段;
  `test_blf_open.py` 末行恒真断言、`test_asc_can_loader.py:302` 逃生口断言改实;
  补一条 >`_PROBE_DECODE_CAP` 的抽样 fixture。
- [x] 验证:`tests/test_blf_loader.py tests/test_channel_frame.py
  tests/test_blf_dbc_candidates.py tests/test_source_adapters.py
  tests/ui/test_blf_open.py tests/ui/test_blf_batch_import.py` 全绿。

## Task F2(sonnet):ASC 链

**Files**: `io/asc_can_format.py` · `io/loader.py` ·
`ui/main_window/_project_io_mixin.py`(仅载入进度回调区段 ~660-690)· 对应 tests

- [x] **P1-1**:hint 正则去 `\b` 与 python-can 对齐(或放宽 tokens[3] 判据),
  `TxRq` 触发回退;补 fast/python-can 逐帧一致差分守卫用例。
- [x] **P1-2**:`_load_one_impl` 进度回调改三参接 phase;`read_asc_outcome` 的
  `warning` 接到用户可见出口——**用 toast**,不用 statusBar.showMessage
  (review P1-5:状态栏已不可视);`test_ui_fallback_reason_is_visible…` 改断
  真实 UI 元素而非 caplog。
- [x] §4.2 `_emit_progress` 前置 `except AscParseCancelled: raise` 并对其余
  异常 `logger.debug` 留痕;`_emit` 缓存回调形态,消除双调用。
- [x] §4.2 预检窗口改「至少 N 条数据行」或在 docstring/spec 写死边界,二选一
  (改判据则补头部长注释场景用例)。
- [x] 验证:`tests/test_asc_can_loader.py tests/ui/test_asc_can_open.py` 全绿。

## Task F3(opus):UltraView 交互核心

**Files**: `ui/chart_stack/ultraview/viewport.py` · `free_grid.py` · `gesture.py` ·
`widgets.py`(dim/文案区段 ~3100-3300)· 对应 spec 措辞 · tests

- [x] **P1-3**:LOD 迟滞只放宽与当前档相邻的边界;
  `test_lod_state_boundaries…` 改成参数化不变量(任意起始档 × 任意缩放 →
  必须落在静态 band 或相邻迟滞带),覆盖 FULL→0.36-0.399。
- [x] **P1-4**:搜索预算 per-blocker 或按卡数缩放;`SEARCH_CAP` 独立用户文案
  (「布局搜索超出预算」类);日志提 `warning`;
  `test_plan_layout_24_card_search_is_capped` 补 `assert plan.accepted` 并拉到
  48/60 卡密集场景。
- [x] **dim 泄漏**(agent 评级 P1):board 维护 `_dimmed_refs` 集合,
  `_update_gesture_at` 增量 dim/undim,`_finish_gesture` 无条件 restore;
  「拖过邻卡放回原格」写成回归用例(断 OpacityEffect 清除)。
- [x] §4.3 群组越界 ghost:画未 clamp 的刚性平移 + reject 态,不逐张 clamp。
- [x] §4.3 blocker 落点:**裁决为改 spec 措辞**(D9.3 改「拖拽轴优先」,与
  docstring 一致);displaced 卡完全出视口时 `logger.info` + toast 提示
  (滚动跟随不在本批)。
- [x] §4.3 死代码簇:删 `plan_boundary_yield`(连同仅存的测试 import)、
  `FEEDBACK_AVOID_BOUNDARY`、`_legal_grid_rect`(测试改断 clamp_rect)、
  重复初始化;`LAYOUT_ARRANGE`/`plan_neighbor_shrink` **保留**但在 free_grid.py
  注明「spec D9.7 预留,UI 整理入口未接」,并在 spec D9.7 标注现状(空实现),
  不在本批接线。
- [x] 验证:`tests/ui/test_ultraview_free_grid.py test_ultraview_viewport.py
  test_ultraview_page.py test_ultraview_gesture*.py`(以实际文件名为准)全绿。

## Task F4(sonnet):UltraView chrome/浮层

**Files**: `ui/chart_stack/ultraview/floating_layout.py` · `chrome.py` ·
`widgets.py`(chip/LOD 可见性区段 ~1550-1850)· `page.py` · 对应 tests

- [x] §4.3 rail 分离约束:居中值 clamp 进
  `[board_island.bottom+GAP, status_island.top-GAP-rail_h]`;
  `_assert_non_overlapping` 类断言参数化到矮 stage(高 ~280px)。
- [x] §4.3 浮层锚点:rail 锚定浮层 y 跟随触发按钮(clamp 进安全区、避开岛)。
- [x] §4.3 类型 chip:改 QLabel 或 `WA_TransparentForMouseEvents`,去 TabFocus;
  「chip 上 press 能 arm 手势」写成用例。
- [x] §4.3 overflow 菜单:`WA_DeleteOnClose`(或 exec 后 deleteLater)。
- [x] §4.3 focusChanged 收窄:只留 `WindowDeactivate`(+hideEvent)取消手势。
- [x] §4.3 TITLE_ONLY:`_set_image` 加 `lod_visibility(...).preview` 守卫,
  `_set_preview_visible(True)` 时补 `_fit_card_image()`。
- [x] 验证:`tests/ui/test_ultraview_chrome.py test_ultraview_page.py` 及
  floating_layout 相关用例全绿。真机观感项(浮层锚点、矮 stage)在收尾的
  Cocoa 验收清单里列出,不在 offscreen 下宣告视觉通过。

## Task F5(sonnet):画布空闲质量 + 状态栏消息出口

**Files**: `ui/pg_canvas/quality.py` · `ui/pg_canvas/line_canvas.py` ·
`ui/main_window/window.py` 及消息调用点 · `docs/lessons-learned/…` · 对应 tests

- [x] **P1-6**:把 `_IdleQualityActivity` 模式移植进 `QualityManager`
  (`_idle_quality_allowed` 的全局 mouseButtons 检查降级为可注入防御 provider,
  本地交互生命周期为主判据);命中闸门时重新武装计时器而不是静默放弃;
  lessons `idle-quality-follows-local-canvas-activity.md` 的 checks 扩到
  quality.py。**不动** ink/AA 常量与 paint 计时兜底;
  `test_frame_paint_backstop_is_installed_on_real_canvas` 必须保持绿。
  逐步替换 test_pg_timedomain_canvas.py 里对 mouseButtons 的 monkeypatch 为
  本地 activity 注入(至少新增路径如此,存量可分步)。
  **落地**:`quality.py` 新增 `_idle_quality_locally_busy()`(判据复用既有
  `_interaction_depth` / `_overlay_axes.dragging`,与 line_canvas 的
  `is_busy()` 同构)+ `_probe_idle_mouse_buttons_provider()`(仅探测/记录失败,
  从不据此拦截,provider 经 `_mouse_buttons_provider`(新增 `_owned_names`)
  可注入);`try_enable_idle_quality()` 命中「本地忙」时改为
  `schedule_idle_quality()` 重新武装而非裸 `return`。新增/重写用例:
  `test_idle_slot_completes_despite_foreign_global_mouse_down`(外部窗口按住
  鼠标不再拦截)、`test_idle_slot_blocked_while_local_interaction_depth_busy`
  (本地 activity 注入,不再靠 mouseButtons monkeypatch)、
  `test_idle_quality_mouse_buttons_provider_exception_is_logged`、
  `test_locally_busy_idle_check_rearms_the_timer`(替换旧的
  `test_mouse_release_rearms_after_blocked_idle_timeout`,后者断言的正是被
  修复的旧行为)、`test_mouse_release_event_rearms_idle_timer`(保留
  eventFilter release→rearm 机制的既有覆盖)。
- [x] §4.4 `last_activity_monotonic` 死字段:删除并修正类 docstring。
  **落地**:`line_canvas.py::_IdleQualityActivity` 删掉该字段(从未被读取,
  仅 `time.monotonic()` 空转写入),`_touch()` 连带其调用点一并删除
  (`note_move`/`note_pulse` 改为显式 no-op 并在 docstring 说明:idle 计时器
  的 delay/rearm 完全靠调用点显式重排,不靠时间戳);`line_canvas.py` 头部
  `import time` 随之移除(不再被使用)。
- [x] **P1-5**:全仓审计 `statusBar.showMessage` 调用点并按「错误/失败类 vs
  信息类」分类成清单(落在本 plan 末尾附录);**错误/失败类改走 toast**
  (ASC 回退那一处由 F2 负责,清单里标注即可);信息类维持现状;在
  lessons(新增或扩展 codex-status-hint-button-geometry.md)显式写明
  「showMessage 已是纯逻辑 API,用户可见提示走 toast」。
  **落地**:审计结果见文末附录——51 处里 26 处已经与相邻 `self.toast(...)`
  成对出现(横跨 info/success/warning/error 各级别),25 处纯信息类且现状
  维持;**逐处核实后未发现遗漏未接 toast 的错误/失败类调用点**,因此本 Task
  未新增任何 toast 调用。为把这条不变量钉成机械护栏(防后人删掉 toast 调用
  却不删 statusBar 那行,又变回 P1-5 的哑巴状态),新增三条回归用例
  (`tests/ui/test_main_window_smoke.py`):
  `test_order_job_failed_routes_to_toast_and_status_bar`、
  `test_frf_failed_routes_to_toast_and_status_bar`、
  `test_fft_time_failed_routes_to_toast_and_status_bar`——分别断言
  `_on_order_job_failed` / `_on_frf_failed` / `_on_fft_time_failed`
  仍然把 `self.toast(msg, "error")` 与 `statusBar.showMessage(...)` 成对调用;
  已实测:临时删掉 `_on_order_job_failed` 里的 `self.toast(msg, "error")`
  会让对应新用例失败(`assert False`),证明测试真的钉住了这条行为,而不是
  空断言。lessons 扩到 `codex-status-hint-button-geometry.md`(新增 addendum
  段落,见该文件)。
- [x] 验证:`tests/ui/test_pg_timedomain_canvas.py test_pg_line_canvas.py
  tests/ui/test_main_window_smoke.py` 全绿。
  **实测**(worktree `agent-aa61881476c96fbf8`):720 passed / 4 skipped /
  1 deselected / 0 failed(76s)。另单独确认
  `tests/ui/test_pg_canvas_backref_invariants.py`(3 passed,
  `_mouse_buttons_provider` 落进 `QualityManager._owned_names` 未触发
  write-through 泄漏)与
  `test_pg_timedomain_canvas.py::test_frame_paint_backstop_is_installed_on_real_canvas`
  (1 passed)保持绿。

## Task F6(sonnet):文档与工作区卫生

**Files**: `docs/analyzer/plans/2026-08-15-qss-consolidation-plan.md` ·
`tests/ui_kit/test_qss_duplicate_selectors.py` · `mf4_analyzer/signal/fft.py` ·
`mf4_analyzer/signal/envelope.py` · `docs/lessons-learned/…` · git add

- [x] QSS plan Task 2/3 复选框补勾(加一行注明「执行时漏勾,2026-08-15 review
  对账后补记」);Task 7 保持未勾(由本批收尾完成)。
- [x] `test_qss_duplicate_selectors.py:12` docstring 数字 44→45(注明合并副作用)。
- [x] 「峰值保持」消歧:`compute_peak_hold_fft` 与 `build_peak_trace` 的
  docstring 互相交叉引用并写明「计算层聚合 vs 渲染层降采样」;
  `codex-fft-spectrum-peak-hold.md` lessons 补同一段。
- [x] pandas 懒加载夹带:在相应 lessons(或新建一条)补记
  `channel_frame.py:87-94` 的动机与安全论证(PyInstaller collect-all 规避)。
- [x] pin 命名撞车:在 `ViewLibraryPanel._pin` 处加一句注释与
  `set_pinned_refs` 划界(不改名)。
- [x] `git add docs/analyzer/reviews/2026-08-14-ultraview-floating-ui-review.md`
  入库(连同本批 review/plan 文档一起提交)。
- [x] 验证:`tests/ui_kit/test_qss_duplicate_selectors.py` 与
  `tests/test_signal_no_gui_import.py` 绿(docstring 改动不碰行为)。

## Task F7(sonnet):既有红修复——batch_render 显示包络四条

**Files**: `mf4_analyzer/batch_render_qt/`(以定位为准)·
`tests/test_batch_render_qt_display_envelope.py`

- [x] 复现四条失败(HEAD 直接可复现,0.64s):envelope spy 调用 4≠2、subplot
  条 `pixel_width 1818 == 350`。先 `git bisect`(区间 `guideline/followup-f1-f8
  收口点..3b2d8cde`,单测极快)钉出引入提交,再裁决是实现回归还是测试预期该
  跟着产品演进走——**别默认改测试**:该文件属 batch/GUI 渲染一致性护栏族,
  「红了就修代码,不是放宽护栏」;若确是产品有意演进(如 supersampling 双分辨率
  导出),修测试时要在提交信息引用引入提交并说明语义。
- [x] 验证:`tests/test_batch_render_qt_display_envelope.py` 全绿 +
  `tests/test_batch_qt_render_parity.py` 保持绿。

## 收尾(主会话)

- [x] 七个 worktree 分支合并到 `claude/post-v8-review-fixes`
  (冲突按「不同区段同文件」预期手工合)。
- [x] 全量两条命令对账:与 review §6 基线(6891/13/38 + 359)比,判据:
  4 条既有红转绿(F7)、其余失败不得多于 9 条顺序污染集;若污染 9 条在
  完整顺序下复现,逐条记录并开 follow-up(不阻塞本批合入,但要留痕)。
- [x] review §6 与本文各 Task 复选框回填;Cocoa 真机待验清单
  (浮层锚点、矮 stage rail、QSS 色板归并)汇总给用户。
- [x] 合入本地 main,不 push(推送由用户决定)。

## 附录:showMessage 调用点分类(F5 产出)

2026-08-15,F5 全仓 grep `self.statusBar.showMessage(...)`(analyzer 主窗口的
`SurfaceStatusBar`,P1-5 指出其 `showMessage()` 恒调
`super().showMessage("", 0)`,不绘制任何文字,见
`ui/main_window/window.py:113-126`),命中 **51 处**,全部落在
`mf4_analyzer/ui/main_window/` 下的 7 个文件:`window.py` ·
`_analysis_mixin.py` · `_fft_mixin.py` · `_fft_time_mixin.py` ·
`_frf_mixin.py` · `_order_mixin.py` · `_project_io_mixin.py`。

**范围说明**:`mf4_analyzer/acquisition_ui/main_window/*.py` 另有约 30 处
`self._status.showMessage(...)`。那是一个真实、会绘制的 `QStatusBar`
(`acquisition_ui/main_window/window.py:343: self._status = QStatusBar(self)`),
**不是** `SurfaceStatusBar`,不受 P1-5 描述的「恒不可视」缺陷影响,因此不计入
本次分类,也不需要 toast 化。

**方法**:逐处读上下文(前后约 10-15 行),检查同一函数体内是否已有
`self.toast(...)` 相邻调用(成对出现即视为「已覆盖」);再按文案语义把
**未配 toast** 的一侧分「错误/失败类」与「信息类」。

**结论**:51 处中 **26 处已经与 `self.toast(...)` 成对调用**(覆盖
info/success/warning/error 各级别),**25 处是纯信息类且从未配 toast、也不
需要配**(进度提示、就绪态提示、成功摘要、用户主动取消的确认性文案——空态
在画布上已有可见的视觉反馈,如 `show_empty_hint`)。逐处核实后
**没有发现任何「错误/失败类但尚未接 toast」的调用点**——review §3 P1-5 举例
的四类(FFT 峰值读数、保存/关闭、游标重置、错误提示)在本次复核时确认均已
在更早的「V8 minor:非模态 toast 替代 QMessageBox.critical」系列改动中补上
了 toast。`SurfaceStatusBar` 本身确实不可视,但用户可感知的错误/失败路径
早已绕过它。因此 **本 Task 未新增任何 toast 调用**;为了不让这条不变量
将来悄悄失守,已补三条回归用例(见上方 Task F5 checklist 的「落地」记录)。

### 分类清单

| 文件 | 行号 | 分类 | 状态 |
| --- | --- | --- | --- |
| `_analysis_mixin.py` | 99 | 通用反馈(含 error) | 已配 toast(L98,`_emit_compute_feedback` 按 `level` 统一路由) |
| `_analysis_mixin.py` | 1156 | 信息类(就绪态提示) | 维持现状 |
| `_fft_mixin.py` | 412 | 信息类(计算中进度) | 维持现状 |
| `_fft_mixin.py` | 483 | 信息类(峰值读数) | 已配 toast(L484,success) |
| `_fft_time_mixin.py` | 419 | 信息类(计算中进度) | 维持现状 |
| `_fft_time_mixin.py` | 661 | 信息类(缓存命中结果) | 维持现状 |
| `_fft_time_mixin.py` | 666 | 信息类(完成摘要) | 维持现状 |
| `_fft_time_mixin.py` | 703 | 错误类 | 已配 toast(L702,error,`outcome is None` 时) |
| `_frf_mixin.py` | 314 | 警告类(非均匀时间轴自动重建) | 已配 toast(L312,warning) |
| `_frf_mixin.py` | 718 | 信息类(完成摘要) | 维持现状 |
| `_frf_mixin.py` | 735 | 错误类 | 已配 toast(L736,error) |
| `_frf_mixin.py` | 792 | 信息类(就绪态提示) | 维持现状 |
| `_order_mixin.py` | 280 | 警告类(转速不适用) | 已配 toast(L279,warning) |
| `_order_mixin.py` | 429 | 信息类(计算中进度) | 维持现状 |
| `_order_mixin.py` | 717 | 信息类(完成摘要) | 已配 toast(L720,success,`emit_feedback` 时) |
| `_order_mixin.py` | 771 | 错误类 | 已配 toast(L770,error,`outcome is None` 时) |
| `_project_io_mixin.py` | 227 | 信息类(用户取消加载) | 已配 toast(L228,info) |
| `_project_io_mixin.py` | 341 | 信息类(批量加载完成) | 已配 toast(L344,success) |
| `_project_io_mixin.py` | 629 | 信息类(`announce_loaded` 通用出口) | 已配 toast(L630,success) |
| `_project_io_mixin.py` | 633 | 信息类(加载中进度) | 维持现状 |
| `_project_io_mixin.py` | 705 | 信息类(用户取消 BLF/ASC) | 维持现状 |
| `_project_io_mixin.py` | 1244 | 信息类(用户取消批量导入) | 维持现状 |
| `_project_io_mixin.py` | 1249 | 信息类(用户取消批量导入) | 维持现状 |
| `_project_io_mixin.py` | 1350 | 信息类(用户中止批量导入摘要) | 维持现状 |
| `_project_io_mixin.py` | 1355 | 信息类(批量导入完成摘要) | 维持现状 |
| `_project_io_mixin.py` | 1615 | 信息类(关闭文件摘要) | 已配 toast(L1616,info) |
| `_project_io_mixin.py` | 1700 | 信息类(保存项目成功) | 已配 toast(L1701,success) |
| `_project_io_mixin.py` | 1898 | 错误类(项目打开后渲染恢复失败) | 已配 toast(L1900,warning) |
| `_project_io_mixin.py` | 1906 | 信息类(打开项目成功,1898 的happy-path 分支) | 维持现状 |
| `_project_io_mixin.py` | 2002 | 信息类(关闭全部) | 已配 toast(L2003,info) |
| `window.py` | 520 | 信息类(初始 "Ready") | 维持现状 |
| `window.py` | 919 | 信息类(`_status_message` 通用底层 helper) | 维持现状(通用工具,非错误专属) |
| `window.py` | 923 | 警告类(`_warn_action_blocked`) | 已配 toast(L924,warning) |
| `window.py` | 936 | 信息类(复制成功) | 已配 toast(L937,success) |
| `window.py` | 946 | 信息类(复制含标注成功) | 已配 toast(L947,success) |
| `window.py` | 2446 | 信息类(时间轴重建成功) | 已配 toast(L2449,success) |
| `window.py` | 2687 | 信息类(关闭多个来源摘要) | 已配 toast(L2690,info) |
| `window.py` | 2911 | 信息类(横坐标已更新) | 已配 toast(L2913,success,条件性) |
| `window.py` | 2933 | 信息类(游标已重置) | 已配 toast(L2934,info) |
| `window.py` | 2983 | 信息类(空态"未加载文件") | 维持现状 |
| `window.py` | 2989 | 信息类(文件摘要) | 维持现状 |
| `window.py` | 3208 | 信息类(聚焦视图提示) | 维持现状 |
| `window.py` | 3479 | 信息类(空态提示;user_initiated 分支已由 L3481 `_warn_action_blocked` 覆盖) | 维持现状 |
| `window.py` | 3535 | 信息类(用户在风险确认对话框取消后的摘要) | 维持现状 |
| `window.py` | 3618 | 信息类(全部隐藏摘要;画布已有可见空态提示) | 维持现状 |
| `window.py` | 3679 | 信息类(0/N 绘制摘要;画布已有可见空态提示) | 维持现状 |
| `window.py` | 3775 | 信息类(绘制结果摘要) | 维持现状 |
| `window.py` | 4750 | 警告类(时间轴非均匀,无法重建) | 已配 toast(L4749,warning) |
| `window.py` | 4755 | 警告类(时间轴非均匀,文件对象不支持) | 已配 toast(L4754,warning) |
| `window.py` | 4800 | 信息类(自动重建完成) | 已配 toast(L4803,success) |
| `window.py` | 4879 | 信息类(复制成功) | 已配 toast(L4880,success) |

**已跳过 / 不在本清单内的一处**:review P1-2 点名的 ASC 回退原因
(`ASC_PHASE_FALLBACK` / `"兼容解析重试"`,`io/asc_can_format.py:39,291,294`)
目前在生产代码里**没有任何消费方**——它还没有走到任何
`statusBar.showMessage` 调用点,所以不在上表 51 行之内。该出口由 **Task F2**
负责接线(P1-2:接三参回调、用 toast 呈现,不用 statusBar.showMessage),此处
仅作标注,F5 未改动 `io/asc_can_format.py` 或 ASC 载入路径。
