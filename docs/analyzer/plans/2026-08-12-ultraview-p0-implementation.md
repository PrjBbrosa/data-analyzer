# UltraView P0 实施计划

**关联 spec**：
`docs/analyzer/specs/2026-08-12-ultraview-p0-spec.md`

**输入证据**：

- `docs/analyzer/reviews/2026-08-12-ultraview-product-technical-report.md`
- `docs/analyzer/reviews/2026-08-12-ultraview-report-claude-review.md`
- `docs/analyzer/ui-prototypes/2026-08-12-ultraview-interactive-demo.html`

**编写基线**：HEAD `3678227b`，TraceLab v7.9.9。本文没有假定该基线的历史全量
pass 数；Task 0 必须在实际实施 worktree 中重新记录起点。

---

## 0. 执行总则

### 0.1 目标与完成定义

本计划只实现 spec 的 P0。完成不是“第六页能打开”，而是同时满足：

1. `UV-A01…UV-A34` 有测试或明确的前景证据；
2. Claude F1～F10 的修正全部落地；
3. 完整 UltraView 操作序列的三层计算探针为 0，restore pending 与源状态不变；
4. 项目顶层 schema 仍为 2，UltraView 保存时不写未知 `current_mode`；
5. offscreen、真实 Cocoa 和未执行的 Windows gate 被分开报告。

### 0.2 环境与工作区纪律

- 使用仓库 venv 的绝对路径：
  `"/Users/donghang/Downloads/data analyzer/.venv/bin/python"`。
- Qt 测试统一前缀：
  `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。
- 动手前记录 `git status --short --branch`、`git log -1 --format=%H` 和相关聚焦测试；
  当前 worktree 已存在与 UltraView 报告/原型及其他任务有关的未提交文件，执行者不得
  清理、覆盖或把无关文件带入提交。
- 每个 Task 先写或打开一个能在旧实现上失败的聚焦断言，再实现到绿；新模块可以先
  建最小可导入 skeleton，避免把 `ModuleNotFoundError` 当成行为红测。
- 不放宽以下棘轮：`test_main_window_state_ownership.py`、import boundaries、
  pg_canvas backref、packaging imports、Qt ownership/lifetime。
- UI 截图先做 offscreen 草图，最终必须用真实 macOS Cocoa；Windows frozen 若没有
  实机，只能标 `UNVERIFIED`。
- 每个 Task 独立 review/commit；若多人并行，严格按本文 file ownership 分配，
  不让两个执行者同时修改 `window.py`、`stack.py`、`project_io.py` 或
  `ui_kit/style.qss`。

### 0.3 推荐依赖顺序

```text
Task 0 基线
  └─ Task 1 纯状态 / digest / codec
      ├─ Task 2 图像工具 / PreviewStore
      │   └─ Task 3 抓图与发布管线
      └─ Task 4 布局 / Page / 卡片 / 托盘
          └──────────────┐
Task 3 ──────────────────┼─ Task 5 第六模式与产品编排
                         ├─ Task 6 项目持久化
                         └─ Task 7 导出 / 演示
                              └─ Task 8 帮助与发现性
                                   └─ Task 9 综合门禁
```

Task 2 与 Task 4 在 Task 1 完成后可并行，但合并前必须先统一 `PreviewRecord` 和
Page-facing API。Task 3、5、6 都会触及 coordinator/MainWindow 集成，按顺序执行。

## Task 0：基线、现状探针与实现工作台

**Owner**：集成/验证；只建测试夹具和 `.state/` 证据，不改产品行为。

**Files**：

- `.state/ultraview-p0/`（不提交）
- `tests/ui/ultraview_fakes.py`（仅当两个以上测试文件确实共享夹具时创建）
- 不修改现有产品模块

### 0.1 起点记录

- [ ] 记录 HEAD、branch、dirty files；确认实现基线是 `3678227b` 或其后代。
- [ ] 运行并记录当前 gate：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_toolbar.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_side_panel_widgets.py \
  tests/ui/test_view_manager.py \
  tests/test_project_io.py \
  tests/ui/test_project_session.py \
  tests/ui/test_main_window_state_ownership.py
```

- [ ] 用现有真实 widgets 记录 1100、1280、1600 px 顶栏 `sizeHint/geometry` 和截图，
  证明第六按钮加入前的空间预算；不凭 QSS 常量直接决定压缩策略。
- [ ] 记录普通 DPI 和当前 Retina 屏上 `grab()` 的 logical/raw 尺寸与 DPR；该记录只
  是 Task 2 的前置证据，不是 UltraView 已通过。

### 0.2 预先冻结的探针

- [ ] 写一个局部 test helper，可分别统计：四个 `do_*`、`submit/submit_batch`、
  `_store_analysis_result` 新 key 写入和 `_analysis_restore_pending` 快照；此时只验证
  helper 对显式调用能计数，不提前伪造不存在的 UltraView 操作。
- [ ] 写 `snapshot_source_state(window)` helper，覆盖五个 ViewManager 的 `to_dict()`、
  active index、analysis pin slots、cache keys；保留 composite identity，不用 `dict()`
  转换 `_ChannelKeyDict`。

**Exit gate**：起点测试和证据已记录；若有预存失败，单独列出，后续不得算作回归或
擅自修复。

---

## Task 1：Qt-free 状态、合法化、布局操作与 digest

**Owner**：状态/序列化。

**Files**：

- 新增 `mf4_analyzer/ui/ultraview_state.py`
- 新增 `tests/ui/test_ultraview_state.py`
- 此 Task 不导入 QWidget、MainWindow、ChartStack 或计算模块

**验收 ID**：UV-A01～A05、A10、A25、A27 的纯状态部分。

### 1.1 RED

- [ ] 先建最小可导入 skeleton，再写失败断言：非法 `order_time`、空 view_id、重复 ref、
  重复 slot、未知 layout、非法 ratio、托盘去重。
- [ ] 写纯状态转移矩阵：
  - 大→小模板的 overflow 顺序；
  - 满板添加进入托盘；
  - replace 把旧 ref 放进托盘；
  - slot↔slot 交换；tray→slot 替换；
  - `move_to_unplaced` 与 `remove_from_board` 的语义不同；
  - orphaned ref 在 round-trip 后仍保留。
- [ ] 写 digest 测试：规范 JSON 与 dict key 顺序无关；改名/颜色不变；源/params/range/
  filter/data/markup/result generation 任一变化会变；不可序列化值明确失败而非随机 repr。
- [ ] 写轴一致性测试：结构化 axis kind、单位标准化、范围 abs+rel tolerance。

### 1.2 GREEN

- [ ] 实现 `SOURCE_SECTIONS`、section 中文标签、`UltraViewRef`、`CardPlacement`、
  `UltraViewBoardState` 和 `PreviewMeta`（不含 QImage）。
- [ ] 实现 `normalize_board_payload()`；返回 `(state, warnings)`，不静默丢非法项。
- [ ] 实现具名状态操作，Page/Inspector 不直接改 list：
  `add_ref / replace_slot / swap_slots / set_layout / set_ratio /
  move_to_unplaced / remove_ref / rebind_ref`。
- [ ] 默认 Board：唯一 UUID、名称“全局对比”、`hero_left_4`、ratio 0.67、空 placements/
  unplaced。
- [ ] 实现 `presentation_digest(payload)`：`digest_schema=1`、稳定 JSON、SHA-256；
  这里只处理调用方给出的轻量 payload，不触碰大数组。
- [ ] 实现 `derive_preview_status(ref_exists, image_valid, captured_digest,
  current_digest)`；不可得 current digest 不得 fresh。
- [ ] 实现 `axis_consistency_facts(records)`，不从人类字符串或 HTML 原型的 Set 比较。

### 1.3 验证

```bash
PYTHONPATH=. "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_main_window_state_ownership.py
```

**Exit gate**：状态模块无 Qt/MainWindow import；所有 Board mutation 只有一份语义实现；
spec 的状态转移和 warning 行为全部有表驱动测试。

---

## Task 2：共享 DPR helper 与 PreviewStore

**Owner**：UI 图像基础/ChartStack。

**Files**：

- 新增 `mf4_analyzer/ui/image_utils.py`
- 新增 `mf4_analyzer/ui/chart_stack/ultraview/__init__.py`
- 新增 `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`
- 修改 `mf4_analyzer/ui/chart_stack/_helpers.py`
- 修改 `mf4_analyzer/ui/analysis_section_page.py`
- 修改 `mf4_analyzer/ui/markup/editor.py`
- 新增 `tests/ui/test_image_utils.py`
- 新增 `tests/ui/test_ultraview_preview_store.py`
- 更新现有图片复制/combined pixmap 聚焦测试

**验收 ID**：UV-A04、A16、A18、A29、A31。

### 2.1 RED

- [ ] 构造 DPR 1.0/2.0 QPixmap，断言归一化后的 QImage `devicePixelRatio==1` 且 raw
  width/height 不丢失。
- [ ] `None`、null、1×1、7×100、100×7 全部拒绝；8×8 是最小有效边界。
- [ ] 超 1600 raw edge 入库会等比降采样；像素预算按 raw `w*h`，不是 logical size。
- [ ] 六个 placed/pinned 图优先保留；unplaced/recent 按 LRU 淘汰；淘汰后 record 元数据
  仍存在且状态为 missing。
- [ ] pinned 图总量超 16M pixels 时按比例收缩而不是突破预算。
- [ ] 删除 ref、clear、QObject owner destroyed 后没有残留 QPixmap/QTimer/信号引用。

### 2.2 GREEN

- [ ] 抽取唯一公开 helper：`pixmap_as_device_pixel_image(pixmap) -> QImage | None`；
  让三个现有调用方委托它，保留原兼容 export 名，避免一次无关 API 迁移。
- [ ] helper 只负责 DPR/format 规范化；有效尺寸、降采样和预算归 PreviewStore。
- [ ] `PreviewRecord` 包含 ref、QImage、captured digest/time、axis metadata、title/source
  snapshot 和最后访问序号；status 仍按 Task 1 纯函数派生。
- [ ] `PreviewStore.publish()` 在 GUI 线程断言、尺寸判废、raw edge 限制和预算收缩后
  原子替换旧 record；失败不覆盖最后有效图。
- [ ] 对 placed refs 提供 `set_pinned_refs()`；只保存 ref set，不保存 QWidget。
- [ ] 暴露只读统计：records/images/raw_pixels/estimated_bytes/evictions/rejections。
- [ ] QImage→QPixmap 只在 Page 显示层、GUI 线程按需创建，不在 Store 常驻双份像素。

### 2.3 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_image_utils.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_chart_stack.py -k "copy or combined or pixmap" \
  tests/ui/test_analysis_section_page.py
```

若 `tests/ui/test_analysis_section_page.py` 不存在，改跑拥有该页面现有覆盖的
`tests/ui/test_chart_stack.py` 与对应 heatmap/line/FRF tests；实施者不得因为文件名
不符跳过 combined pixmap 回归。

**Exit gate**：仓库不出现第四份 DPR normalize 实现；Store 的 raw pixel 预算和
判废边界有精确测试。

---

## Task 3：presentation payload、稳定抓图与预览发布

**Owner**：MainWindow coordinator + 各 canvas 的最小展示接口。

**Files**：

- 新增 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 修改 `mf4_analyzer/ui/main_window/_state_holders.py`（仅在需要具名 holder 时）
- 修改 `mf4_analyzer/ui/main_window/window.py`（初始化/teardown 一次性接线）
- 修改 `mf4_analyzer/ui/main_window/_view_mixin.py`
- 修改 `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- 修改 `_fft_mixin.py`、`_fft_time_mixin.py`、`_frf_mixin.py`、`_order_mixin.py`
  的**实际绘制完成侧**，不改数值算法
- 修改 `mf4_analyzer/ui/pg_canvas/annotations.py`、`remarks.py` 及 line/heatmap/FRF
  canvas 的最小 `markup_revision`/capture-overlay 接口
- 新增 `tests/ui/test_ultraview_capture.py`
- 扩展各真实 canvas owner 测试

**验收 ID**：UV-A05、A13～A18、A21、A22、A29。

### 3.1 RED：payload 与 stale

- [ ] 时域 payload 覆盖 checked/hidden/colors/mode/ranges/axis/filter/data/markup；
  derived channel add、replace、delete 均改变 digest，未变化数据重复取值保持稳定。
- [ ] 分析 payload 覆盖 panes/roles/params/compare/ranges/真实 pin key/result generation/
  markup；cache key 相同但强制结果重写仍改变 generation。
- [ ] 移动瞬态 cursor/hover 不改变 digest，抓图中也不可见；添加/移动/删除持久 remark
  会推进 revision。

### 3.2 RED：时域切换与 split

- [ ] 给 canvas 绑定 ref A，调用 `_render_view_to_canvas(B, canvas, ...)`，断言 A 在覆盖前
  被提名抓取，B 不在 defer-first-frame 空数组阶段被发布。
- [ ] 同 View `_replot_canvas_for_view` 不把旧 frame 写入另一个 ref。
- [ ] `split_active()==True` 时 primary/secondary 分别发布两个 time refs；False 时隐藏
  secondary 从不 grab。
- [ ] unstable（quality 非 green、dense 非 green、interaction 非 idle、refresh pending）
  跳过且保留旧图；禁止 sleep/轮询。

### 3.3 RED：分析绘制时序

- [ ] FFT 同步计算路径在 `_plot_fft_entries` 返回后 queued 抓取，而不是只监控
  AnalysisJobService。
- [ ] FFTTime/Order/FRF 的 cache-hit 和 worker-complete 都在实际 plot/set_result 之后
  queued 抓取；inactive view completion 只缓存，不抓当前别人的 canvas。
- [ ] heatmap 的二次 layout 尚未 settle 时不发布；`layout_geometry_changed` debounce 后
  再等待一轮事件循环才 grab。
- [ ] Analysis split 组合 `pane_count()==1/2` 的可见 pane；隐藏第二 pane 不进入组合。
- [ ] 相同 `(ref,digest)` 连续信号只 grab 一次；queued 期间切 ref/改 digest 则丢帧。

### 3.4 GREEN

- [ ] `UltraViewCoordinator` 负责 canvas→ref binding、capture queue、dedupe、payload
  provider、Store publish 和 teardown；MainWindow 不新增多个可变 dict。
- [ ] 对时域在 `_render_view_to_canvas` 覆盖前调用 `offer_capture_bound_canvas(canvas)`；
  coordinator 自己判断是否真正切 ref。
- [ ] 进入/离开模式、源“加入总览”和分析绘制完成都调用同一个
  `request_capture(ref, canvas_or_page, reason)`，不复制稳定判断。
- [ ] 稳定策略按 canvas 能力分支；`quality_status_changed` 只做重新评估触发，不直接
  代表 post-paint。
- [ ] `QTimer.singleShot(0, ...)` 只保存稳定 ref/digest/weak canvas handle；执行前用
  `sip.isdeleted()`、visibility、binding 和 digest 复检。
- [ ] capture context manager 隐藏 transient overlay 并在 finally 恢复；markup revision
  由现有 annotation owner 推进，不在 coordinator 猜测鼠标事件。
- [ ] `_store_analysis_result` 唯一漏斗通知 coordinator result generation；只有新 key 或
  同 key 换成不同 result 对象时推进，同 key/同对象 cache-hit 不推进。通知不得调用
  capture、render 或 job，只使下次按需 digest 可见变化。
- [ ] 所有警告走已有 diagnostics throttling，包含 ref/reason/canvas type。

### 3.5 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_pg_timedomain_canvas.py -k "quality or defer or split or remark" \
  tests/ui/test_pg_line_canvas.py -k "quality or remark or pixmap" \
  tests/ui/test_pg_heatmap_canvas.py -k "layout_geometry or remark or pixmap" \
  tests/ui/test_frf_canvas.py -k "remark or pixmap" \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py
```

**Exit gate**：能用真实 time-line/line/heatmap/FRF canvas 证明非空有效抓图；不存在
“切到带 xlim 新 View 后立刻抓白图”的路径；没有新增 post-paint 热路径逻辑。

---

## Task 4：布局几何、UltraViewPage、卡片、View 库和托盘

**Owner**：ChartStack UI。

**Files**：

- 新增 `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`
- 新增 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 新增 `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- 修改 `mf4_analyzer/ui/chart_stack/ultraview/__init__.py`
- 修改 `mf4_analyzer/ui_kit/style.qss`（只增加 UltraView-owned selectors）
- 新增 `tests/ui/test_ultraview_layouts.py`
- 新增 `tests/ui/test_ultraview_page.py`

**验收 ID**：UV-A02、A03、A06～A12、A33 的 offscreen 部分。

### 4.1 RED：纯几何

- [ ] 六个 layout_id 在 1600×900 和给定 content rect 中输出正确 slot 数、唯一 ID、
  无交叠、全部在边界内、最小 gutter 一致。
- [ ] ratio 只影响 hero 模板；0.40/0.67/0.80 边界稳定；屏上和 export 调同一函数。
- [ ] 1280×800 与 1600×900 下卡片 chrome 最小高度不被整体 scale 掉。

### 4.2 RED：Page 行为

- [ ] View 库按五 section 分组、搜索和完整 tooltip；重复 ref 添加只定位。
- [ ] 空槽 add、行按钮、拖入、Inspector-like signal 四条路径发出同一 typed intent。
- [ ] 满板添加、缩容、替换都进入托盘；托盘标题常驻且第一次溢出展开。
- [ ] 拖拽在 dropEvent 内复制 `section/view_id` 字符串；测试销毁原 QMimeData 后 queued
  mutation 仍安全。
- [ ] 四态卡片、selected、dimmed、orphaned replacement-armed 的 visual property 和
  accessibleName 可观察。
- [ ] 右键菜单、双击、键盘、非拖拽按钮发出相同意图；Page 不直接导航 MainWindow。
- [ ] 焦点层 raw 100% cap；底部“打开原 View”是真按钮；Esc 关闭。
- [ ] comparison filter 只影响 opacity，BoardState 序列化不变。

### 4.3 GREEN

- [ ] `layouts.py` 只依赖 QtCore geometry 或纯 tuple，不导入 QWidget/MainWindow。
- [ ] `UltraViewPage` 内部为 `[ViewLibraryPanel | BoardColumn]`；BoardGrid 使用 QWidget/
  layouts，不引入 QGraphicsScene/QGraphicsProxyWidget。
- [ ] ViewLibrary 接受 coordinator 提供的不可变 row models，不直接读取 MainWindow。
- [ ] CardWidget 只读取 PreviewRecord/placement/meta，向上发 typed intent；不调用源 View。
- [ ] QDrag MIME type 固定为 `application/x-tracelab-ultraview-ref+json`，payload 仅
  section/view_id；解析必须走 Task 1 validator。
- [ ] UnplacedTray 用滚动内容承载任意数量 ref；image 已淘汰时仍显示 metadata/missing。
- [ ] 页面顶部不显示 `0 JOBS`，状态栏也不注入常驻零计算文案；missing 卡片保留一次
  解释文案。
- [ ] QSS 使用现有 Precision Light token/圆角/边框观感；不复制 live chart-card QSS
  中依赖 canvas toolbar 的选择器。

### 4.4 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_page.py
```

若通用 drag lifetime 文件不存在，将该回归留在 `test_ultraview_page.py`，不为文件名
机械新建重复夹具。

**Exit gate**：独立 Page harness 能完成 HTML 原型的核心动作，但没有 demo 状态按钮、
board zoom、0-jobs 徽标、PDF/SVG 或假图表。

---

## Task 5：第六模式、Inspector、侧栏状态与“加入总览”入口

**Owner**：MainWindow/模式集成。该 Task 是扇出高风险点，必须单 owner 串行修改。

**Files**：

- 修改 `mf4_analyzer/ui/chart_stack/_helpers.py`
- 修改 `mf4_analyzer/ui/chart_stack/stack.py`
- 修改 `mf4_analyzer/ui/toolbar.py`
- 修改 `mf4_analyzer/ui_kit/icons.py`
- 修改 `mf4_analyzer/ui_kit/style.qss`
- 新增 `mf4_analyzer/ui/inspector_sections/contextual_ultraview.py`
- 修改 `mf4_analyzer/ui/inspector.py`
- 修改 `mf4_analyzer/ui/main_window/window.py`
- 修改 `mf4_analyzer/ui/main_window/_view_mixin.py`
- 修改 `mf4_analyzer/ui/side_panels.py`
- 修改 `mf4_analyzer/ui/view_tabbar.py`
- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 新增 `tests/ui/test_ultraview_mode_integration.py`
- 新增 `tests/ui/test_ultraview_job_isolation.py`
- 更新现有 toolbar/chart_stack/inspector/side-panel/view-tab tests

**验收 ID**：UV-A07、A09、A11、A12、A19～A24。

### 5.1 RED：第六模式扇出

- [ ] `ChartStack.stack.count()==6`，index↔mode round-trip 含 `ultraview`；
  `hint_bar_for_mode("ultraview")` 不抛 KeyError。
- [ ] Toolbar `总览` 按钮点击/程序化设置/active dot/signal 正确，style/icon 存在。
- [ ] MainWindow `_on_mode_changed` 有显式 UltraView 第三分支，不保留/改写上一个
  Navigator projection；进入/退出只调用 coordinator 产品动作。
- [ ] Inspector UltraView context 显示，shared range group 隐藏且不被错误 reparent；
  切回五个源 mode 后原路径恢复。
- [ ] `_all_cards/mark_discovered/set_annotation_enabled/copy image` 不把 UltraView 当
  live chart card，也不因第六页抛异常。
- [ ] `_visible_view_tabbar()` 在 UltraView 返回 None；Alt+1…9 不触发时域/分析切换。

### 5.2 RED：侧栏与入口

- [ ] `SidePanelController` 的公开 persistent snapshot/hide/restore 能恢复 HIDDEN/PINNED
  与 remembered width；PEEK 规范化为 HIDDEN；不直接写私有 state。
- [ ] 进入 UltraView 自动隐藏 global left nav，退出恢复；UltraView 顶栏 nav toggle 只
  控制页内 library。
- [ ] presentation 隐藏/恢复 global right inspector；退出时不把用户原本隐藏的面板
  强行打开。
- [ ] ViewTabBar 当前/非当前 View 的“加入总览”携带稳定 section/view_id；当前 View
  可尝试抓图，非当前 View 不切换、不 render。
- [ ] MainWindow teardown 后 toolbar/page/tabbar 信号不再回调已删除 coordinator。

### 5.3 RED：零计算第一道完整序列

- [ ] 使用 Task 0 三层探针覆盖当前已完成的 UltraView 操作：进入、添加、换布局、
  拖拽/按钮换位、ratio、过滤、焦点层、退出。
- [ ] `do_* == 0`、`submit/submit_batch == 0`、`_store_analysis_result` 新写入为 0、
  `_analysis_restore_pending` 与源 manager/cache/pin/active 快照不变。
- [ ] 单独测试“打开原 View”只导航到正确 section/view_id；它不属于零计算序列。

### 5.4 GREEN

- [ ] ChartStack 构造并注册 UltraViewPage；page 提供自己的 hint bar，不伪装成 card。
- [ ] Toolbar 新增 `btn_mode_ultraview`、`mode_ultraview()` icon、segment QSS、mapping 和
  active dot；用户文案固定“总览”。
- [ ] 1100 px 真实 geometry 若完整标签失败，实现基于 center budget/sizeHint 的统一
  六按钮 icon-only 紧凑态；1600 px 恢复文字。不得抬高窗口最小宽度。
- [ ] `UltraViewContextual` 只接收 selection/BoardState，发 state intents；不 import
  MainWindow、不访问源 manager。
- [ ] `Inspector._place_range_group_for_mode` 增加明确 third branch：UltraView 隐藏 shared
  range/filter card；未知 mode 防御回 time。
- [ ] `SidePanelController` 增加窄 public API，例如
  `snapshot_persistent_state / set_persistent_state / restore_persistent_state`；实现继续走
  现有 effect/Qt ownership，不让 coordinator reparent panel。
- [ ] coordinator 记录 `last_source_mode`、进入/退出 side-panel snapshot、library toggle
  routing、ViewTabBar intent 和 source navigation。
- [ ] source navigation 使用 manager 的稳定 view_id 搜索；找不到时转 replacement，不用
  保存下标。

### 5.5 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_side_panel_widgets.py \
  tests/ui/test_view_manager.py \
  tests/ui/test_main_window_smoke.py -k "mode or panel or shortcut" \
  tests/ui/test_main_window_state_ownership.py
```

**Exit gate**：六 mode 的硬映射不再漏项；在 1100 px 有 geometry 断言和截图；完整
非导出 UltraView 序列的三层零计算探针全绿。

---

## Task 6：`.tlproj` 增量字段、current_mode 防御与恢复

**Owner**：project_io/项目恢复；不得与 Task 5 并行修改模式恢复路径。

**Files**：

- 修改 `mf4_analyzer/ui/project_io.py`
- 修改 `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 修改 `mf4_analyzer/ui/chart_stack/stack.py`（仅未知 mode 防御，若 Task 5 未完成）
- 修改 `mf4_analyzer/ui/inspector.py`（同上）
- 修改 `tests/test_project_io.py`
- 修改 `tests/ui/test_project_session.py`
- 扩展 `tests/ui/test_ultraview_job_isolation.py`

**验收 ID**：UV-A02、A03、A21、A25～A28。

### 6.1 RED：纯项目 IO

- [ ] 断言 `SCHEMA_VERSION == 2`，保存含 UltraView 的项目仍写 2。
- [ ] 旧 v1/v2 项目没有 `ultraview` 时加载默认空 Board，不影响 files/views/filter。
- [ ] Board placements/unplaced/name/layout/ratio/display flags round-trip；selected/filter/
  presentation/QImage/digest 不在 JSON。
- [ ] `ProjectDocument` 旧位置参数构造不因新字段插入错位。
- [ ] 未知 current_mode 在 load 后为 time；未知 UltraView nested schema 只降级 Board，
  不拒绝整个项目。
- [ ] 非法 section/重复 ref/重复 slot/未知 layout/非法 ratio 产生 warnings 并按 spec
  合法化；合法缺失 ref 仍保留。

### 6.2 RED：MainWindow save/open

- [ ] 当前 mode=ultraview、last_source_mode=fft 时，JSON `current_mode=="fft"`；重新打开
  落在 FFT，Board 已恢复但不自动进入总览。
- [ ] 在 UltraView 保存前只捕获 last source mode 的当前可见 View；不得把 UltraView
  当 time 或 analysis manager 捕获、不得触发 render/job。
- [ ] Board ref 能随现有 View restore 的稳定 view_id 解析；源 View 缺失时 orphaned；
  fid remap 不改变 ViewRef。
- [ ] open/save 操作前后 `_analysis_restore_pending` 的既有语义不被 UltraView 消费。
- [ ] 模拟旧版 reader（忽略未知顶层字段、只识别五 mode）可读新 JSON；再用不包含
  UltraView 字段的 ProjectDocument 保存，显式证明字段会丢失而不会崩溃。

### 6.3 GREEN

- [ ] `ProjectDocument.ultraview` 追加到末尾；save 仅在有 Board state 时写合法 dict；
  load 用 `.get` 并把 warning 暴露给 MainWindow 可见/日志路径。
- [ ] 不改 `SUPPORTED_SCHEMA_VERSIONS={1,2}`；不增加顶层 v3。
- [ ] MainWindow 保存 mode 由 coordinator `project_source_mode()` 决定；加载 mode 已经过
  whitelist，不把 `ultraview` 喂给旧硬映射。
- [ ] 恢复 Board 在源 managers/view IDs 就绪之后进行；PreviewStore 像素为空，所以
  refs 派生 missing/orphaned，不伪造 preview。
- [ ] degraded source restore 与 UltraView orphan warning 各自可观察，不覆盖现有
  `ProjectRestoreHealth` 语义。

### 6.4 验证

```bash
PYTHONPATH=. "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/test_project_io.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_project_session.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_main_window_state_ownership.py
```

**Exit gate**：一个保存于 UltraView 的新项目能被“旧五 mode reader”读取现有部分；
当前应用重开时落在 last source mode；顶层 schema 未变。

---

## Task 7：离屏整板合成、复制、PNG 与演示模式

**Owner**：ChartStack export/presentation。

**Files**：

- 新增 `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`
- 修改 `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 修改 `mf4_analyzer/ui/inspector_sections/contextual_ultraview.py`
- 新增 `tests/ui/test_ultraview_export.py`
- 扩展 `tests/ui/test_ultraview_job_isolation.py`

**验收 ID**：UV-A09、A11、A19～A22、A30、A31、A33。

### 7.1 RED：compositor

- [ ] 1× 输出恰为 1600×900，2× 恰为 3200×1800；两者 layout rect 按同一几何函数
  等比；DPR 为 1.0。
- [ ] 输出包含 Board 名、所有 placed slot、标题/source/status；不含页内 library、右
  Inspector、托盘、当前滚动位置和 comparison dim 瞬态。
- [ ] fresh/stale/orphaned 的旧图可见且状态带正确；missing 是明确占位。
- [ ] 2× 不调用任何 canvas grab/render/job；卡图不超过 raw 100% 插值放大。
- [ ] null allocation、save false、不可写路径均返回结构化失败并触发 toast/warning；
  不产生空文件/1×1。
- [ ] 复制整板图与 PNG 的像素 hash（排除元数据）一致；单卡复制来自同一 record。

### 7.2 RED：演示与 Esc

- [ ] 进入 presentation 前 snapshot 页内 library、右 panel HIDDEN/PINNED、tray 展开态；
  退出精确恢复。
- [ ] Esc 优先级按 focus → replacement → presentation → popup；每次只消费一层。
- [ ] 演示/导出前后 BoardState 与源 manager 状态不变。

### 7.3 GREEN

- [ ] compositor 接受 immutable BoardState + PreviewRecords + scale，不接受 MainWindow/
  QWidget；所有 QPainter/QImage 创建在 GUI 线程。
- [ ] Page 的复制/导出 intent 交给 coordinator；文件对话框只负责选择路径，真正绘制
  由 compositor 单入口。
- [ ] 2× chrome/vector primitives 以 2× 绘制；卡图按 raw 像素 contain-fit，不为了
  填满而超 100% 放大。
- [ ] presentation 通过 SidePanelController public API 控制 global right，不直接
  `setVisible` 导致 controller state desync。
- [ ] 把 Task 5 的零计算序列扩展到 presentation、复制、PNG、save，三层探针仍为 0。

### 7.4 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_side_panel_widgets.py
```

**Exit gate**：PNG/clipboard 是完整 Board；失败可见；完整 P0 操作序列的三层计算探针
与源状态快照全绿。

---

## Task 8：帮助、hints、quickref、截图工具与打包面

**Owner**：产品文档/发现性。

**Files**：

- 修改 `mf4_analyzer/ui/hints.py`
- 修改 `mf4_analyzer/ui/quickref.py`
- 修改 `mf4_analyzer/help/__init__.py`
- 新增 `mf4_analyzer/help/ultraview-guide.html`
- 修改 `tools/gen_help_screenshots.py`
- 修改 `tests/ui/test_hints.py`
- 修改 `tests/ui/test_quickref.py`
- 修改 `tests/test_gen_help_screenshots.py`
- 修改现有 help/packaging tests（按仓库真实文件定位）

**验收 ID**：UV-A23、A32。

### 8.1 文案决策

- [ ] QuickRef 组标题由“五个分析模式”改为“分析与总览”，其中仍有五个分析方法行，
  另加“总览：并排查看已有 View，不会计算”一行；不要把 UltraView 称为算法。
- [ ] 新 guide 说明：添加、托盘、四态、打开来源、导出、零后台计算边界和项目重开
  missing 语义；不展示已删除的 board zoom、PDF/SVG、0-jobs 常驻 UI。
- [ ] hints 同步“加入总览”、卡片菜单、临时放大、打开来源、托盘；不新增未登记快捷键。
- [ ] Help mapping 登记 `ultraview`，Inspector 帮助链接不 fallback 到 manual。

### 8.2 测试与打包

- [ ] 更新 exact five-mode tests 为“五分析 + 一总览”的明确契约，而不是简单把数字 5
  替成 6。
- [ ] `PANEL_MODES`/截图工具加入 UltraView，现有四分析精确 tuple 测试同步改成契约
  测试；截图工具能找到第六 page/context。
- [ ] 打包资源测试证明 `ultraview-guide.html` 随 help tree 出货；不新增 QWebEngine。
- [ ] `ui/hints.py` 和 `ui/quickref.py` 同步完成，满足项目交互发现性契约。

### 8.3 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_gen_help_screenshots.py \
  tests/test_packaging_imports.py
```

另运行仓库中真实 help-path/packaging-data tests；若文件名与上面不同，用 `rg` 找消费
`_GUIDE_FILES` 和 help datas 的测试，不得只测 Python import。

**Exit gate**：用户能从顶栏、源 View 菜单、QuickRef、Inspector help 四个发现面理解
UltraView；所有文案与 P0 实际行为一致。

---

## Task 9：综合回归、视觉、性能与交付报告

**Owner**：集成/验证；此 Task 不再顺手加功能。

**Files**：

- 可新增 `docs/analyzer/verify/YYYY-MM-DD-ultraview-p0-verification.md`
- 新增 `tools/verify_ultraview_visuals.py`
- 新增 `tests/test_verify_ultraview_visuals.py`
- 自动截图和像素 diff 证据放 `.state/ultraview-p0/`；除非任务另有要求，不提交生成图
- 只修复 UltraView 引入的回归，不处理无关 baseline debt

**验收 ID**：UV-A01～A34 全量映射。

### 9.1 静态与架构门禁

- [ ] `git diff --check`；审查 changed-file scope，无无关格式化。
- [ ] `ultraview_state.py` 无 Qt/MainWindow import；`chart_stack/ultraview` 不导入数值
  算法；coordinator 不把状态散写到多个 mixin。
- [ ] 运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui/test_pg_canvas_backref_invariants.py
```

### 9.2 UltraView 聚焦套件

- [ ] 一次运行全部 `test_ultraview_*.py` 和被修改的既有 owner tests；禁止用不同 pytest
  命令拆开来掩盖 fixture/order 问题。
- [ ] 再用参数顺序交错一次 UI/non-UI UltraView tests，确认 repo-root conftest 的 fixture
  closure 没有失效。
- [ ] 零计算完整序列输出四类计数和 source snapshot diff，不能只报告 “test passed”。

### 9.3 自动真实渲染对比

- [ ] 生成固定 seed 的四态 × 关键 layout × 1280×800/1600×900 截图；用自动像素/
  geometry 比较汇总，不把几十张图交给用户逐张看。
- [ ] `tools/verify_ultraview_visuals.py` 输出截图 manifest、geometry/pixel assertions、
  单张 contact sheet 和可选 approved-baseline diff；首次验收没有 approved baseline 时，
  必须依赖明确的 geometry/pixel 规则 + Cocoa contact sheet，不得把“没有 diff”写成通过。
- [ ] 必检画面：默认 hero、6-grid、非空托盘、selected、stale、missing、orphaned、
  replacement-armed、focus、presentation、1100 px 顶栏 full/compact、Inspector。
- [ ] 对比 HTML 原型时只核对已保留的交互和层级，不把 demo-only SVG、状态模拟按钮、
  board zoom、0-jobs 徽标当成 parity 目标。

### 9.4 内存与响应探针

- [ ] 6 个 1600-edge preview 入库、切模板 100 次、焦点开关 50 次、1×/2× 导出各 10
  次；断言 Store 从不超过 16M raw pixels，eviction 可观测，退出后清零。
- [ ] 记录而非先写死时间阈值：进入 UltraView、6 图布局切换、2× 合成的 p50/p95 和
  主线程最长停顿；若出现肉眼卡顿，再以数据补性能阈值，不在本计划凭空承诺毫秒数。
- [ ] 验证 2× 导出没有第二套 QPixmap 常驻或近 4× 无界峰值。

### 9.5 真机门禁

- [ ] macOS Cocoa 前景：Retina 下检查卡片清晰度、圆角边界、标题/状态不遮图、拖放、
  焦点层、左导航恢复、右 Inspector 演示恢复、clipboard 和 PNG。
- [ ] 普通 DPI 若当前无设备，用可控 DPR probe 只能标“模拟通过”，不能冒充真机。
- [ ] Windows Full/Lite frozen：若无出货包和机器，明确 `UNVERIFIED`；源级 packaging
  tests 不能替代。

### 9.6 全套回归

按仓库约定分两个新进程：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  "/Users/donghang/Downloads/data analyzer/.venv/bin/python" -m pytest -q \
  tests/acquisition_ui
```

异常退出、segfault、timeout 或中断均记 `UNVERIFIED`，不从先完成的用例推断通过。

### 9.7 最终验收矩阵

验证报告必须逐项列：

| 列 | 内容 |
|---|---|
| Acceptance ID | `UV-A01…UV-A34` |
| 证据类型 | unit / offscreen Qt / rendered diff / Cocoa / source-only / Windows frozen |
| 命令或动作 | 精确命令、脚本或手工步骤 |
| 结果 | PASS / FAIL / UNVERIFIED |
| 证据位置 | test 名、日志或截图路径 |
| 备注 | baseline、已知限制或与 spec 的偏差 |

**Exit gate**：34 个 ID 无遗漏；任何未通过项都保留 `UNVERIFIED/FAIL`，不得用“总体
正常”覆盖。

---

## 10. Acceptance ID → Task/Test 一一映射

实施中可调整具体 test function 名，但必须同步修改本表和 spec ID，不能只保留范围式
“已覆盖”声明。

| ID | 主 Task | 自动化/证据入口 |
|---|---:|---|
| UV-A01 | 1 | `test_ultraview_state.py::test_ref_accepts_only_gui_sections_and_stable_id` |
| UV-A02 | 1/4 | `test_ultraview_state.py::test_capacity_operations_preserve_every_ref_in_tray` |
| UV-A03 | 1/6 | `test_ultraview_state.py::test_orphan_rebind_uses_replace_flow` + project round-trip |
| UV-A04 | 1/2 | `test_ultraview_preview_store.py::test_status_is_derived_and_never_optimistically_fresh` |
| UV-A05 | 1/3 | `test_ultraview_capture.py::test_presentation_digest_pixel_affecting_field_matrix` |
| UV-A06 | 4 | `test_ultraview_layouts.py::test_all_templates_fit_without_overlap_at_supported_sizes` |
| UV-A07 | 4/5 | `test_ultraview_mode_integration.py::test_page_library_and_global_navigator_are_reversible` |
| UV-A08 | 4/6 | `test_ultraview_page.py::test_overflow_tray_is_visible_and_persisted` |
| UV-A09 | 4/7 | `test_ultraview_page.py::test_menu_inspector_focus_and_source_intents_have_parity` |
| UV-A10 | 1/4 | `test_ultraview_page.py::test_compare_filter_and_structured_axis_warnings_do_not_mutate_board` |
| UV-A11 | 5/7 | `test_ultraview_mode_integration.py::test_presentation_and_escape_restore_panel_state` |
| UV-A12 | 4/5 | `test_ultraview_mode_integration.py::test_alt_digits_are_noop_and_buttons_cover_drag_actions` |
| UV-A13 | 3 | `test_ultraview_capture.py::test_time_switch_captures_old_binding_before_deferred_render` |
| UV-A14 | 3 | `test_ultraview_capture.py::test_each_capture_trigger_obeys_canvas_stability_contract` |
| UV-A15 | 3 | `test_ultraview_capture.py::test_time_split_is_two_refs_and_analysis_split_is_one_composite` |
| UV-A16 | 2/3 | `test_ultraview_preview_store.py::test_dpr_normalization_and_minimum_valid_dimensions` |
| UV-A17 | 3 | `test_ultraview_capture.py::test_transient_overlays_hidden_but_markup_revision_is_captured` |
| UV-A18 | 3 | `test_ultraview_capture.py::test_capture_dedupes_and_rejects_late_binding_or_digest` |
| UV-A19 | 5/7 | `test_ultraview_job_isolation.py::test_complete_board_sequence_calls_no_compute_entrypoint` |
| UV-A20 | 5/7 | `test_ultraview_job_isolation.py::test_complete_board_sequence_has_no_submit_or_cache_write` |
| UV-A21 | 5/6/7 | `test_ultraview_job_isolation.py::test_complete_board_sequence_preserves_source_state` |
| UV-A22 | 3/5 | `test_ultraview_job_isolation.py::test_preview_path_never_calls_restore_or_source_replot` |
| UV-A23 | 5/8 | `test_ultraview_mode_integration.py::test_all_six_mode_fanout_surfaces_are_registered` |
| UV-A24 | 0/5 | `test_toolbar.py::test_six_modes_fit_at_1100_or_use_uniform_compact_mode` + screenshots |
| UV-A25 | 6 | `test_project_io.py::test_ultraview_is_additive_under_top_level_schema_two` |
| UV-A26 | 6 | `test_project_session.py::test_ultraview_save_reopens_in_last_source_mode_and_unknown_falls_back` |
| UV-A27 | 1/6 | `test_project_io.py::test_ultraview_payload_degrades_with_warnings_and_keeps_orphans` |
| UV-A28 | 6 | `test_project_io.py::test_legacy_reader_accepts_new_file_and_resave_drops_unknown_field` |
| UV-A29 | 2/9 | `test_ultraview_preview_store.py::test_raw_pixel_budget_lru_stats_and_symmetric_clear` |
| UV-A30 | 7 | `test_ultraview_export.py::test_clipboard_and_png_share_complete_fixed_board_compositor` |
| UV-A31 | 7 | `test_ultraview_export.py::test_two_x_export_never_regrabs_computes_or_upscales_card_raw_pixels` |
| UV-A32 | 8 | hints/quickref/help path/screenshot mode/packaging resource tests |
| UV-A33 | 9 | `test_verify_ultraview_visuals.py` + visual script manifest/contact sheet/diff |
| UV-A34 | 9 | verification report Cocoa checklist with screenshot evidence; Windows separately marked |

---

## 11. 建议提交边界

1. `feat(ultraview): add board state and digest contracts`
2. `feat(ultraview): add DPR-normalized preview store`
3. `feat(ultraview): capture stable visible view previews`
4. `feat(ultraview): add widget board page and overflow tray`
5. `feat(ultraview): integrate sixth mode and source navigation`
6. `feat(project): persist ultraview board without schema bump`
7. `feat(ultraview): add deterministic board image export`
8. `docs(ui): add ultraview help and discovery surfaces`

每次提交只 stage 对应 Task 文件。若 Task 5 因 `ui_kit/style.qss`/`stack.py` 与别的任务冲突，
先重放并重新跑本 Task gate，不通过 `git checkout --` 或 broad reset 覆盖别人的修改。

## 12. 实施暂停与变更控制

遇到以下情况停止当前 Task，先回 spec/计划更新决策：

- 为获得预览必须调用隐藏 View 重绘或 cache restore；
- 现有 canvas 无法在不改数值算法的前提下给出稳定有效像素；
- 1100 px 即使统一 icon-only 仍无法容纳顶栏；
- 六个 placed preview 在 16M raw pixel 预算内明显不可读；
- 项目兼容必须升顶层 schema 才能正确表达；
- 实现需要把全局 Navigator 改成 QStackedWidget；
- MainWindow state ownership ratchet 需要扩大 whitelist；
- P0 想加入 sidecar、PDF、自由画布、超过 6 图或 live canvas。

这些都属于产品/架构边界变化，不能由执行者在实现中静默决定。
