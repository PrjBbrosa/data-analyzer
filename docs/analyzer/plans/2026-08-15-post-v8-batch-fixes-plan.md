# v8 后续批次 review 修复 plan

- 日期:2026-08-15
- 上游 review:`docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md`
  (P0/P1/P2 定性、证据与修法方向均在该文,本文只列执行安排,不重复论证)
- 基线:`main@350969f2`
- 执行方式:六个 Task 各由一个 agent 在独立 worktree 执行(F1/F3 用 opus,
  其余 sonnet),各自成提交;主会话负责合并、全量对账、收尾。

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

- [ ] **P0-1**:发现样本独立预算,按 review §2 修法;discovery 扫描搬进使用分支;
  A/B 场景(30000 帧低频 ID)写成回归用例。
- [ ] §4.1 完整扫描文案:读 `sampling_strategy`,complete 时「完整解码」;
  「完整匹配」改「ID 命中 A/B」。
- [ ] §4.1 取消/截断:`candidate_status` 加 `"incomplete"` 档(排序在 unverified
  与 mismatch 之间、不被 selectable 过滤、独立文案);窗口取消信号接到
  `probe_blf_dbc_frames(cancel_check=...)`。
- [ ] §4.1 LazyZohFrame 重名:重复列名 fail-fast 或自动消歧(`Time` 冲突消歧为
  `<Msg>.Time` 一类),ABC docstring 与实现对齐;重写假绿用例(两份不同数据
  的同名 series)。
- [ ] §4.1 BLF 探测进度分两个子区间,构造完 `BlfDbcProbe` 才 100%。
- [ ] §4.1 杂项:零帧 reason、`is_lazy()` 物化后返回 False、`get_column` 返回
  只读视图或拷贝(与 `__getitem__` 语义拉平)、两处宽泛 except 补
  `logger.warning`。
- [ ] 测试收紧:`test_blf_batch_import.py:317` 陈旧桩补新字段;
  `test_blf_open.py` 末行恒真断言、`test_asc_can_loader.py:302` 逃生口断言改实;
  补一条 >`_PROBE_DECODE_CAP` 的抽样 fixture。
- [ ] 验证:`tests/test_blf_loader.py tests/test_channel_frame.py
  tests/test_blf_dbc_candidates.py tests/test_source_adapters.py
  tests/ui/test_blf_open.py tests/ui/test_blf_batch_import.py` 全绿。

## Task F2(sonnet):ASC 链

**Files**: `io/asc_can_format.py` · `io/loader.py` ·
`ui/main_window/_project_io_mixin.py`(仅载入进度回调区段 ~660-690)· 对应 tests

- [ ] **P1-1**:hint 正则去 `\b` 与 python-can 对齐(或放宽 tokens[3] 判据),
  `TxRq` 触发回退;补 fast/python-can 逐帧一致差分守卫用例。
- [ ] **P1-2**:`_load_one_impl` 进度回调改三参接 phase;`read_asc_outcome` 的
  `warning` 接到用户可见出口——**用 toast**,不用 statusBar.showMessage
  (review P1-5:状态栏已不可视);`test_ui_fallback_reason_is_visible…` 改断
  真实 UI 元素而非 caplog。
- [ ] §4.2 `_emit_progress` 前置 `except AscParseCancelled: raise` 并对其余
  异常 `logger.debug` 留痕;`_emit` 缓存回调形态,消除双调用。
- [ ] §4.2 预检窗口改「至少 N 条数据行」或在 docstring/spec 写死边界,二选一
  (改判据则补头部长注释场景用例)。
- [ ] 验证:`tests/test_asc_can_loader.py tests/ui/test_asc_can_open.py` 全绿。

## Task F3(opus):UltraView 交互核心

**Files**: `ui/chart_stack/ultraview/viewport.py` · `free_grid.py` · `gesture.py` ·
`widgets.py`(dim/文案区段 ~3100-3300)· 对应 spec 措辞 · tests

- [ ] **P1-3**:LOD 迟滞只放宽与当前档相邻的边界;
  `test_lod_state_boundaries…` 改成参数化不变量(任意起始档 × 任意缩放 →
  必须落在静态 band 或相邻迟滞带),覆盖 FULL→0.36-0.399。
- [ ] **P1-4**:搜索预算 per-blocker 或按卡数缩放;`SEARCH_CAP` 独立用户文案
  (「布局搜索超出预算」类);日志提 `warning`;
  `test_plan_layout_24_card_search_is_capped` 补 `assert plan.accepted` 并拉到
  48/60 卡密集场景。
- [ ] **dim 泄漏**(agent 评级 P1):board 维护 `_dimmed_refs` 集合,
  `_update_gesture_at` 增量 dim/undim,`_finish_gesture` 无条件 restore;
  「拖过邻卡放回原格」写成回归用例(断 OpacityEffect 清除)。
- [ ] §4.3 群组越界 ghost:画未 clamp 的刚性平移 + reject 态,不逐张 clamp。
- [ ] §4.3 blocker 落点:**裁决为改 spec 措辞**(D9.3 改「拖拽轴优先」,与
  docstring 一致);displaced 卡完全出视口时 `logger.info` + toast 提示
  (滚动跟随不在本批)。
- [ ] §4.3 死代码簇:删 `plan_boundary_yield`(连同仅存的测试 import)、
  `FEEDBACK_AVOID_BOUNDARY`、`_legal_grid_rect`(测试改断 clamp_rect)、
  重复初始化;`LAYOUT_ARRANGE`/`plan_neighbor_shrink` **保留**但在 free_grid.py
  注明「spec D9.7 预留,UI 整理入口未接」,并在 spec D9.7 标注现状(空实现),
  不在本批接线。
- [ ] 验证:`tests/ui/test_ultraview_free_grid.py test_ultraview_viewport.py
  test_ultraview_page.py test_ultraview_gesture*.py`(以实际文件名为准)全绿。

## Task F4(sonnet):UltraView chrome/浮层

**Files**: `ui/chart_stack/ultraview/floating_layout.py` · `chrome.py` ·
`widgets.py`(chip/LOD 可见性区段 ~1550-1850)· `page.py` · 对应 tests

- [ ] §4.3 rail 分离约束:居中值 clamp 进
  `[board_island.bottom+GAP, status_island.top-GAP-rail_h]`;
  `_assert_non_overlapping` 类断言参数化到矮 stage(高 ~280px)。
- [ ] §4.3 浮层锚点:rail 锚定浮层 y 跟随触发按钮(clamp 进安全区、避开岛)。
- [ ] §4.3 类型 chip:改 QLabel 或 `WA_TransparentForMouseEvents`,去 TabFocus;
  「chip 上 press 能 arm 手势」写成用例。
- [ ] §4.3 overflow 菜单:`WA_DeleteOnClose`(或 exec 后 deleteLater)。
- [ ] §4.3 focusChanged 收窄:只留 `WindowDeactivate`(+hideEvent)取消手势。
- [ ] §4.3 TITLE_ONLY:`_set_image` 加 `lod_visibility(...).preview` 守卫,
  `_set_preview_visible(True)` 时补 `_fit_card_image()`。
- [ ] 验证:`tests/ui/test_ultraview_chrome.py test_ultraview_page.py` 及
  floating_layout 相关用例全绿。真机观感项(浮层锚点、矮 stage)在收尾的
  Cocoa 验收清单里列出,不在 offscreen 下宣告视觉通过。

## Task F5(sonnet):画布空闲质量 + 状态栏消息出口

**Files**: `ui/pg_canvas/quality.py` · `ui/pg_canvas/line_canvas.py` ·
`ui/main_window/window.py` 及消息调用点 · `docs/lessons-learned/…` · 对应 tests

- [ ] **P1-6**:把 `_IdleQualityActivity` 模式移植进 `QualityManager`
  (`_idle_quality_allowed` 的全局 mouseButtons 检查降级为可注入防御 provider,
  本地交互生命周期为主判据);命中闸门时重新武装计时器而不是静默放弃;
  lessons `idle-quality-follows-local-canvas-activity.md` 的 checks 扩到
  quality.py。**不动** ink/AA 常量与 paint 计时兜底;
  `test_frame_paint_backstop_is_installed_on_real_canvas` 必须保持绿。
  逐步替换 test_pg_timedomain_canvas.py 里对 mouseButtons 的 monkeypatch 为
  本地 activity 注入(至少新增路径如此,存量可分步)。
- [ ] §4.4 `last_activity_monotonic` 死字段:删除并修正类 docstring。
- [ ] **P1-5**:全仓审计 `statusBar.showMessage` 调用点并按「错误/失败类 vs
  信息类」分类成清单(落在本 plan 末尾附录);**错误/失败类改走 toast**
  (ASC 回退那一处由 F2 负责,清单里标注即可);信息类维持现状;在
  lessons(新增或扩展 codex-status-hint-button-geometry.md)显式写明
  「showMessage 已是纯逻辑 API,用户可见提示走 toast」。
- [ ] 验证:`tests/ui/test_pg_timedomain_canvas.py test_pg_line_canvas.py
  tests/ui/test_main_window_smoke.py` 全绿。

## Task F6(sonnet):文档与工作区卫生

**Files**: `docs/analyzer/plans/2026-08-15-qss-consolidation-plan.md` ·
`tests/ui_kit/test_qss_duplicate_selectors.py` · `mf4_analyzer/signal/fft.py` ·
`mf4_analyzer/signal/envelope.py` · `docs/lessons-learned/…` · git add

- [ ] QSS plan Task 2/3 复选框补勾(加一行注明「执行时漏勾,2026-08-15 review
  对账后补记」);Task 7 保持未勾(由本批收尾完成)。
- [ ] `test_qss_duplicate_selectors.py:12` docstring 数字 44→45(注明合并副作用)。
- [ ] 「峰值保持」消歧:`compute_peak_hold_fft` 与 `build_peak_trace` 的
  docstring 互相交叉引用并写明「计算层聚合 vs 渲染层降采样」;
  `codex-fft-spectrum-peak-hold.md` lessons 补同一段。
- [ ] pandas 懒加载夹带:在相应 lessons(或新建一条)补记
  `channel_frame.py:87-94` 的动机与安全论证(PyInstaller collect-all 规避)。
- [ ] pin 命名撞车:在 `ViewLibraryPanel._pin` 处加一句注释与
  `set_pinned_refs` 划界(不改名)。
- [ ] `git add docs/analyzer/reviews/2026-08-14-ultraview-floating-ui-review.md`
  入库(连同本批 review/plan 文档一起提交)。
- [ ] 验证:`tests/ui_kit/test_qss_duplicate_selectors.py` 与
  `tests/test_signal_no_gui_import.py` 绿(docstring 改动不碰行为)。

## Task F7(sonnet):既有红修复——batch_render 显示包络四条

**Files**: `mf4_analyzer/batch_render_qt/`(以定位为准)·
`tests/test_batch_render_qt_display_envelope.py`

- [ ] 复现四条失败(HEAD 直接可复现,0.64s):envelope spy 调用 4≠2、subplot
  条 `pixel_width 1818 == 350`。先 `git bisect`(区间 `guideline/followup-f1-f8
  收口点..3b2d8cde`,单测极快)钉出引入提交,再裁决是实现回归还是测试预期该
  跟着产品演进走——**别默认改测试**:该文件属 batch/GUI 渲染一致性护栏族,
  「红了就修代码,不是放宽护栏」;若确是产品有意演进(如 supersampling 双分辨率
  导出),修测试时要在提交信息引用引入提交并说明语义。
- [ ] 验证:`tests/test_batch_render_qt_display_envelope.py` 全绿 +
  `tests/test_batch_qt_render_parity.py` 保持绿。

## 收尾(主会话)

- [ ] 七个 worktree 分支合并到 `claude/post-v8-review-fixes`
  (冲突按「不同区段同文件」预期手工合)。
- [ ] 全量两条命令对账:与 review §6 基线(6891/13/38 + 359)比,判据:
  4 条既有红转绿(F7)、其余失败不得多于 9 条顺序污染集;若污染 9 条在
  完整顺序下复现,逐条记录并开 follow-up(不阻塞本批合入,但要留痕)。
- [ ] review §6 与本文各 Task 复选框回填;Cocoa 真机待验清单
  (浮层锚点、矮 stage rail、QSS 色板归并)汇总给用户。
- [ ] 合入本地 main,不 push(推送由用户决定)。
