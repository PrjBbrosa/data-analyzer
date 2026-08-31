# 游标显示修复与关闭全清会话重置实施计划

- 日期：2026-08-31
- 状态：已实施（offscreen 契约绿；T3/T6 Cocoa 真机未验）
- 实施基线：`main@a9667968`
- 对应规格：[`2026-08-31-cursor-display-followup-spec.md`](../specs/2026-08-31-cursor-display-followup-spec.md)
- 验证范围声明：本计划各 Task 只跑自己的 owner 聚焦用例 + 所列边界护栏；
  **不安排全量基线**（非发版/跨边界重构）。真机（Cocoa 前台）证据仅
  T3/T6 需要，其余 offscreen 即可。

## 任务依赖

```
T0（红测确认，只读）
T1（fid 泄漏）──┐
T2（投影密度）──┼─→ T5（单管线 + DTO 归位）─→ T8（杂项清理）
T3（弹层透明）  │
T4（紧凑工具栏）┘
T6（Custom-X 性能缓存）    独立
T7（关闭全清会话复位）      独立
```

T1–T4 相互独立可并行；T5 依赖 T1/T2 定稿后的投影行为；T6、T7 与其余
任务无共享文件冲突（T6 动 `pg_canvas/cursor.py` 的缓存段，与 T1 的
标签段不同函数，先后合入即可）。

---

## T0 基线确认（只读，无生产改动）

在 `a9667968` 上复跑并记录：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_cursor_display_settings.py tests/test_custom_x_paths.py \
  tests/ui/test_custom_x_cursor_contract.py tests/ui/test_chart_stack.py -q
```

已知结论（2026-08-31 本机）：`test_time_card_settings_button_stays_beside_
cursor_segment_and_emits_options` 红（F1），其余绿。该红测归 T4 所有，
其它 Task 见到它红不计入自己头上。

## T1 消除 fid 泄漏，来源标签单点解析（R1，spec §3.1）

**改动**
- 新建单点解析函数（建议放 `chart_stack/_helpers.py` 或随 T5 的中立
  模块）：`resolve_cursor_source_label(display_name, identity, fid_resolver)`，
  按 spec §3.1 顺序解析；`ChartStack` 构造时把 `fid → short_name` 解析器
  注入画布（经既有 setter 面，不让 `pg_canvas` 反查 `MainWindow`）。
- 删除 `pg_canvas/cursor.py` 与 `chart_stack/stack.py` 里两份
  `_cursor_identity_labels`，改调单点函数。
- 实现「参与游标结果的来源数 ≤ 1 时 visible face 不出前缀」（D1，推荐值）。

**owner 测试**
- 新增：identity 为 `("f0", ch)` 时任何 visible/tooltip 文本不含 `f0`，
  显示 `short_name`；无解析器且显示名无前缀时不显示来源；双文件重名
  通道 tooltip 仍可区分（沿用既有 duplicate-identity 用例扩展）。
- 回归：`tests/ui/test_cursor_display_settings.py`（除 F1 红测节点）、
  `tests/ui/test_chart_stack.py` 游标簇。

**护栏**：`test_pg_canvas_backref_invariants.py`（删方法要同步收缩
`_delegate_names` 声明，只减不加）。

## T2 恢复 mini/full 投影密度差异（R2/R3/R4，spec §3.2）

**改动**
- `cursor_display._time_rows` / `_custom_rows` / `_block_html` /
  `render_cursor_presentation` 按 spec §3.2 表格重排四个场景的
  visible 行；single 与 dual-mini 折叠为单行（`●` 色点承载通道色）。
- mini 丢弃的信息全量保留进 tooltip（现有 `_tooltip` 已做，验证不回退）。

**owner 测试**
- 新增机械护栏：对非空 blocks 的同一输入，`mini=True` 与 `mini=False`
  的 HTML **不得相等**（每个 `(cursor_mode, x_mode)` 组合各一条）——这是
  R2 的防复发测试。
- 新增：单游标 full 每通道恰一行（HTML `<tr>` 计数）；dual mini 每
  时间轴通道恰一行；32 组合矩阵沿用上游规格测试并更新期望。
- 回归：`tests/ui/test_cursor_display_settings.py` 全文件、
  `tests/ui/test_plot_helpers.py`。
- 文档面：若 hints/quickref 描述受影响，同步 `ui/hints.py` +
  `ui/quickref.py`（owner：`test_hints.py` / `test_quickref.py`）。

## T3 弹层不透明底板（R5，spec §3.3）

**改动**
- `CursorDisplayPopover` 补 `paintEvent`：抗锯齿圆角矩形，底色
  `QColor(255,255,255,248)` 级、边框 `#d8e0eb`，参数对齐 QSS 声明；
  QSS 保留。

**owner 测试**
- offscreen：`paintEvent` 渲到 `QImage` 后中心像素非透明（alpha ≥ 245）
  且非网格灰（能抓「底板没画」这一类回归）。
- **真机验收**：macOS 前台打开弹层截图，确认不透字；证据归档
  `docs/analyzer/verify/`。offscreen 通过不得写成视觉验收通过（Gotchas）。

## T4 紧凑工具栏按钮可见性（F1，spec §3.4）

> **已被取代（2026-08-31 晚）**：用户追加报告紧凑重排导致按钮**错位**，
> 并决策工具栏改为横向滑动。本任务的「修重排」方案废弃，F1 红测的
> owner 归属转移到
> [`2026-08-31-cursor-display-followup-2-plan.md`](2026-08-31-cursor-display-followup-2-plan.md)
> 的 **C6**（滑动工具栏 + 废除重排）。不要按下述原方案实施。

**改动**
- 根因排查 `_sync_responsive_toolbar` / `_prioritize_time_controls`：
  确认 500 px 下按钮不可见是 QToolBar overflow 吞掉末位 action、还是
  重排后 action 未恢复可见。修代码使现有红测变绿，**不放宽断言**。
- 补紧凑↔常规往返三次的顺序/可见性幂等测试。

**owner 测试**
- `test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options`
  （现红转绿）+ 新增幂等测试。
- 回归：`tests/ui/test_chart_stack.py` 工具栏簇。

## T5 单管线渲染 + DTO 归位（F2/F4，spec §3.5/§3.7）

**改动**
- `ChartStack._on_cursor_info` / `_on_dual_cursor_info`：live 画布来源
  只更新 primary 行与可见性，不再写 detail；detail 渲染统一走
  `_refresh_cursor_projection`。无 rows 信号的兼容来源保留现有完整
  fallback（以「source 是否为受管画布」判定，不猜信号有无）。
- DTO（Options/Branch/Channel/Row/Block/Presentation）迁
  `ui/cursor_display_model.py`；`chart_stack/cursor_display.py` re-export；
  `pg_canvas/cursor.py` 改 import 中立模块。
- 顺带删 `ChartStack.closeEvent` 死代码（其清理职责由既有
  `clear_cursor_pill` 调用点覆盖，删除前核对无其它触发路径）。

**owner 测试**
- 计数断言：单游标一次 move → `set_display_projection` 恰一次、
  `set_single_detail_html` 零次；双游标同理。
- 兼容 seam：只发 `cursor_info` 的模拟来源仍能出 detail（既有
  compatibility 用例保留）。
- 回归：`tests/ui/test_chart_stack.py` 全文件、
  `tests/ui/test_cursor_display_settings.py`。

**护栏**：`test_import_boundaries.py` · `test_batch_render_import_boundary.py`
（迁移不得把 `ui` 拉进中立面）· `test_no_lambda_signal_connections.py`
（改接线只准用 partial/bound method）。

## T6 Custom-X 单游标路径缓存与向量化插值（F3，spec §3.6）

**改动**
- `pg_canvas/cursor.py`：`(data_id, channel)` 键的路径分析 memo，失效
  挂既有 `invalidate_monotonicity_cache` / 数据重建入口（核对全部失效
  调用点：文件关闭、range filter、通道重载）。
- `signal/custom_x_paths.py`：拆出「分析」与「取值」两步公开 API
  （`sample_custom_x_cursor` 保留原签名与语义，内部委托）；
  `_sample_path_contribution` 改 `searchsorted`（降序 leg 先翻转），
  逐点语义等价。
- `signal/` 保持无状态：缓存只在 UI 侧。

**owner 测试**
- `tests/test_custom_x_paths.py` 全量保留（数值等价护栏）+ 新增：
  searchsorted 路径与旧逐段插值在随机往返序列上逐点一致；端点、
  重复 X、非有限值分支不变。
- 缓存：命中不重跑分析（计数 mock）、三类失效点各一条。
- 真机标定：500k×4 拖动每 move 取值 ≤ 5 ms，读数记
  `docs/analyzer/verify/`；offscreen 只做数量级冒烟。

**护栏**：`test_signal_no_gui_import.py`。

## T7 关闭全清会话复位事务（R6，spec §3.8）

**改动**
- `_present_after_sources_closed` 增加 files-empty 分支调用单点复位
  helper（归属 `_project_io_mixin` 或协作对象，不新增跨文件散写）：
  View manager 复位（范围按 D2 决策）、`_custom_xaxis.clear()` +
  Inspector 回 time、时间范围/滤波回默认、`clear_cursor_pill`。
- 防重入：项目加载/恢复过程中的中间清空不触发（实施时确认现有
  `_applying_view` 或项目恢复 in-progress 守卫可复用，不新造标志则已，
  要造则进 `_state_holders`）。

**owner 测试**
- 全链：开两文件 → 设 Custom-X（PER_SOURCE_NAME）→ 逐个/批量全关 →
  断言 View 数回默认、`inspector.top.xaxis_mode() == 'time'`、标签空、
  时间范围默认 → 再开文件绘图 → 断言时间轴自动排序。
- 反例：只关其中一个文件不触发复位（PER_SOURCE_NAME 保活语义不变）；
  项目加载路径不触发复位（回归 `tests/ui/test_project_session.py` 相关簇）。

**护栏**：`test_main_window_state_ownership.py`（棘轮只准缩小）。

## T8 杂项清理（F5，依赖 T1/T2/T5 落定）

- `cursor_display._tooltip` 分支识别改用结构化分支标记（不再
  `startswith("X")`，覆盖 `全程`）；
- popover `_deferred_refit` 去掉 248 px 强制最小高（note 隐藏时按
  sizeHint 收紧）；
- custom-X 单游标 X 值精度与双游标 primary 行一致（沿用现有 X 轴上下
  文精度，不固定 `:.1f`）；
- `_emit_single_cursor_html` plain-dict fallback 的 hidden 键域统一
  （composite 与 display 名不混用）。

**owner 测试**：各项一条聚焦断言，挂 `tests/ui/test_cursor_display_settings.py`
或 `tests/ui/test_pg_timedomain_canvas.py` 既有簇。

---

## 收尾

- 全部 Task 合入后跑一遍第 5 节验收清单所列边界门禁（一次即可，不跑
  全量套件）。
- `git diff --check` + 未决标记扫描。
- 如 mini/full 行为描述变化，`/update-hints` 同步两个发现性面。
- 真机证据（T3 截图、T6 读数）归档 `docs/analyzer/verify/` 并在本文件
  「实施结果」节记录测试计数与快照 HEAD——**不得**把 partial 结果记成全绿
  （今日 F1 的教训：验证记录声称全绿但 HEAD 有红测）。

## 实施结果

- 工作区相对 `main@a9667968`，T0–T8 代码已落地，**未提交**（工作区另有无关脏文件：资产删除、`ssh-keygen` 等，未纳入本改动）。
- D1 单来源省略可见前缀、D2 时域+分析分区全复位，均按 spec 推荐执行。
- Offscreen 收尾门禁（2026-08-31，`HEAD a9667968` + 本 followup 脏范围）：
  聚焦 owner + `test_chart_stack` + 第 5 节边界护栏 + paint 计时器哨兵
  **416 passed** / 51.11s；另 `tests/ui/test_plot_helpers.py` **78 passed**。
  `git diff --check` 干净。全量套件未跑（按本计划验证范围）。
- T8 跟进：Custom-X 单游标轴数字改为 `:.4g` 后，legacy 面是 `X=4 mm` 而非
  `X=4.0 mm`，`test_custom_x_cursor_contract` 断言已对齐。
- hints/quickref：footer 与速查补了 mini 收缩描述。
- **不得记成视觉/性能已验收**的两项：
  - T3 macOS 前台弹层截图仍 pending。现有
    `docs/analyzer/verify/2026-08-31-cursor-display-popover-offscreen.png`
    只证明 offscreen `paintEvent` 底板不透明。
  - T6 Cocoa 500k×4 每 move ≤ 5 ms 仍 pending，见
    `docs/analyzer/verify/2026-08-31-custom-x-cursor-cache-cocoa-pending.md`。
