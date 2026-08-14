# TraceLab v8 稳健性硬化与 UltraView 精致化实施计划

- 状态：Draft / ready for execution
- 日期：2026-08-14
- 基线：`main@3b2d8cde`
- 规格：`docs/analyzer/specs/2026-08-14-v8-review-hardening-and-ultraview-polish-spec.md`
- 原则：按 owner 小步提交；先写失败测试/确定性 probe，再改实现；各 milestone 可独立回退

## 1. 实施顺序

本计划分为五批，不能合成一次大改：

1. CAN 数据可信度：DBC 抽样语义、候选排序、BLF frame 公共契约。
2. ASC 稳健性：预检、fallback outcome、单调进度。
3. UltraView 信息层级：三级 LOD、类型标签、minimap、状态与动作分层。
4. UltraView 操作手感：纯碰撞 planner、完整 ghost、尺寸保持、原子 undo。
5. 渲染稳定与发布：空闲质量确定性、帮助/lessons、全套与平台验收。

Milestone 1 会改变公共数据契约，Milestone 3/4 会改变用户交互规则，必须分别形成清晰提交和证据。

## 2. 开工前基线

### 2.1 工作区保护

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
git diff --stat
```

当前已知以下并行文件不属于本计划，除非用户另行指定，否则不编辑、不暂存、不提交：

- `docs/analyzer/reviews/2026-08-14-ultraview-floating-ui-review.md`
- `docs/analyzer/ui-prototypes/2026-08-14-ultraview-control-alignment-options.html`

新出现的 dirty 文件先确认来源；不得用 reset/checkout 清理他人修改。建议工作分支：`codex/v8-hardening-ultraview-polish`。

### 2.2 Pre-change 测试

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_blf_loader.py tests/test_blf_dbc_candidates.py \
  tests/test_source_adapters.py tests/test_asc_can_loader.py \
  tests/ui/test_blf_open.py tests/ui/test_asc_can_open.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_floating_layout.py tests/ui/test_pg_line_canvas.py -q
```

已有失败必须记录完整 node id、异常、重复性和退出码，不得混入本轮 GREEN 结论。每个提交前检查 `git diff --cached --check` 与 `git diff --cached --stat`。

## 3. Batch A — CAN 数据可信度

### Task 1：冻结 DBC 抽样与排序失败用例

**文件所有权**

- `tests/test_blf_loader.py`
- `tests/test_blf_dbc_candidates.py`
- `tests/ui/test_blf_open.py`
- `tests/_helpers/blf_factory.py`

**先写 RED**

1. 前 8192 帧全可解码、后段全失败：不得把线性外推标为精确帧数。
2. 前、中、尾命中率不同：统计样本必须覆盖三个区域。
3. 为覆盖 frame ID 额外取到的 discovery 首帧不能进入统计分母。
4. top-3 第一候选先达到 sampled-strong、第二候选实际更优：三者仍全部被 probe，最终第二候选胜出。
5. 取消、截断、损坏尾部：estimate 为空且原因明确。
6. UI 显示“抽样解码”，测试拒绝伪精确“帧 estimated/total”。

测试应在旧实现上因目标缺陷失败，而非 fixture 无效。不得为构造 exact count 额外执行全量 DBC decode。

**验收映射**：`V8H-A01`–`A04`

### Task 2：实现 DBC probe 的事实/样本分离

**文件所有权**

- 主 owner：`mf4_analyzer/io/blf_format.py`
- 排序：`mf4_analyzer/blf_dbc_candidates.py`
- UI 协调：`mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 适配：`mf4_analyzer/io/source_adapters.py`
- 测试：Task 1 文件、`tests/test_source_adapters.py`

**步骤**

1. `BlfDbcProbe` 增加 exact、sample、derived、sampling diagnostic 字段。
2. discovery sample 与 statistical sample 拆成不同对象/帮助函数，不共享隐式计数器。
3. 统计样本用确定性分层位置覆盖前、中、尾，继续受固定预算约束。
4. 移除 `_scale_probe_count()` 的伪精确用途；兼容字段只能明确标记 estimate/deprecated。
5. 结构预筛最多 3 个候选，除 cancel 外全部按相同策略 probe，删除 sampled-strong early break。
6. 排序使用可比较的 exact coverage/sample ratio，最后以结构分、路径和文件名稳定 tie-break。
7. UI 分为“完整匹配”和“抽样解码”模板；样本不足/取消/回退均带原因。
8. 迁移全部 `BlfDbcProbe(...)` 构造点；必需状态不用 `getattr(..., False)` 静默补齐。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_blf_loader.py tests/test_blf_dbc_candidates.py \
  tests/test_source_adapters.py tests/ui/test_blf_open.py \
  tests/ui/test_batch_blf_dbc_context.py tests/ui/test_blf_batch_import.py -q
```

在同一大 BLF 上记录旧/新 wall time、峰值内存、采样数和取消响应。若时间超过 baseline 20%，先排查重复 I/O/decode；禁止用全量 decode 换“精确率”。

**推荐提交**：`fix(can): separate exact and sampled dbc probe evidence`

### Task 3：建立 ChannelFrame 契约并迁移 BLF

**文件所有权**

- 新 owner：`mf4_analyzer/io/channel_frame.py`
- `mf4_analyzer/io/blf_format.py`
- `mf4_analyzer/io/loader.py`
- `mf4_analyzer/io/source_adapters.py`
- `mf4_analyzer/io/file_data.py`
- `tests/test_blf_loader.py`、`tests/test_source_adapters.py`
- 建议新增 `tests/test_channel_frame.py`

**先写 RED**

1. `load_blf()` 返回显式 `ChannelFrame` protocol/ABC。
2. 只访问一列时未访问列的 ZOH 物化计数为 0。
3. `to_pandas()` 后与小数据既有结果在时间对齐、列顺序、dtype 上等价。
4. `drop_columns()` 只做列操作；行 drop/未知 pandas kwargs 明确报不支持。
5. 重复显示名不经普通 `dict(...)` 折叠复合身份。
6. 空、单点、非有限和不同时间起点行为固定。

**步骤**

1. 从真实消费者提取最小协议，不以 pandas 全 API 为模板。
2. 定义 `ChannelFrame`、能力检测、列操作和显式 materialization；模块保持 UI-neutral/import-safe。
3. 让当前惰性实现实现契约，删除会静默成功的伪 pandas 行为。
4. `DataLoader.load_blf()` 的类型、docstring、错误信息改成 ChannelFrame。
5. 新增 `load_blf_dataframe()`（或规格批准的同义显式 API），只在调用方主动选择时物化。
6. 迁移 SourceAdapter/FileData 和真实消费者；不得用 `__getattr__` 全量透传补洞。
7. 若保留 `LazyZohFrame` 导入，做薄兼容别名并加测试，不复制实现。
8. 增加 subprocess import-boundary 证据，防止 neutral layer 导入 UI/renderer。

若发现某消费者依赖未列入协议的 pandas 行语义，先记录调用点，再选择显式物化或扩展协议；默认路径若变成全表物化，本任务不得完成。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_channel_frame.py tests/test_blf_loader.py tests/test_source_adapters.py \
  tests/ui/test_blf_open.py tests/ui/test_import_boundaries.py \
  tests/test_native_import_boundaries.py tests/test_packaging_imports.py -q
```

若新增测试文件最终改名，以实际文件为准，执行记录必须保存最终命令。

**推荐提交**：`refactor(io): make lazy blf channel-frame contract explicit`

## 4. Batch B — ASC 回退与进度

### Task 4：预检、结果对象与单调进度

**文件所有权**

- 主 owner：`mf4_analyzer/io/asc_can_format.py`
- 加载协调：`mf4_analyzer/io/loader.py`
- `tests/test_asc_can_loader.py`
- `tests/ui/test_asc_can_open.py`

Task 3 和 Task 4 都写 `loader.py`，必须串行执行。

**先写 RED**

1. 有界前缀即可识别不支持语法时，不做 fast 全扫，直接进入 python-can。
2. 中后段 late fallback 时，外部 progress 序列单调不减。
3. fallback/取消不提前发成功 100。
4. outcome 含 backend、fallback reason、回退前读取字节。
5. UI 区分“快速解析”和“兼容解析重试”，诊断有原因且经过节流。

**步骤**

1. 提取有界 `_preflight_asc_format()`，只判断支持性，不复制完整 parser。
2. 定义 `AscParseOutcome` 与有限枚举 fallback reason。
3. 单一 progress coordinator 映射 preflight/fast/fallback/finalize，维护 high-water mark。
4. early fallback 直达 python-can；late fallback 从 high-water 继续或进入 indeterminate 阶段。
5. 格式不兼容可回退，编程错误和未知异常继续传播。
6. UI/Batch 复用同一 outcome，不增加第二套进度 emit/record。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/test_asc_can_loader.py tests/ui/test_asc_can_open.py -q
```

**推荐提交**：`fix(asc): keep fallback progress monotonic and observable`

## 5. Batch C — UltraView 信息层级

### Task 5：补齐三级 LOD 与持久类型标签

**文件所有权**

- 阈值：`mf4_analyzer/ui/chart_stack/ultraview/viewport.py`
- Card：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 编排：`mf4_analyzer/ui/chart_stack/ultraview/page.py`
- 测试：`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_page.py`、`tests/test_verify_ultraview_visuals.py`

**先写 RED**

- 60/59、40/39 的状态边界固定。
- 55% 隐藏 footer，保留 preview/type/trust。
- 35% 隐藏 body/footer/正文动作且无空 backing area。
- 三种 LOD 的逻辑 geometry、选择/拖拽命中和持久化不变。
- `View 1` 等通用标题在 55%/35% 仍能识别分析类型。
- 切换 LOD 不创建分析 job、不改变 digest。

**步骤**

1. 定义唯一 LOD enum/predicate owner，Page 传状态，Card 只负责呈现。
2. 把 title/type/trust/preview/footer/action visibility 写成明确状态表。
3. header 加紧凑类型 chip；极窄时退化为带 tooltip 的图标。
4. 保持 selection/drag handles、tab order、accessible name。
5. 视觉 probe 覆盖 100%、55%、35% 和四个临界点。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_icons.py tests/test_verify_ultraview_visuals.py -q
```

自动截图矩阵：800/1280/1440 × 100/55/35。offscreen 只证明状态/几何，真实 Cocoa 在 Task 10 验收。

**推荐提交**：`fix(ultraview): complete card lod and persistent type cues`

### Task 6：整理 minimap、模式/面板状态与上下文动作

**文件所有权**

- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- `mf4_analyzer/ui/chart_stack/ultraview/floating_layout.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 对应 chrome/floating/page tests

Task 5/6 同写 `page.py`、`widgets.py`，不得并行落代码。

**先写 RED**

- free-grid + board fit 隐藏 minimap；出现 scroll range 后显示；恢复 fit 后隐藏；template 始终隐藏。
- `modeActive=true, panelOpen=false/true` 有不同属性和样式；关闭 panel 不改 mode。
- 常驻动作只保留打开/定位、条件同步、聚焦、更多；原能力仍从 More/右键可达。
- stale 才占用同步位；800 px 无覆盖；icon-only 均有 tooltip/accessible name。

**步骤**

1. Minimap 条件读取真实 scroll range/content extent，用现有合并刷新响应 resize/zoom/layout。
2. 控件拆出 `modeActive` 和 `panelOpen` 属性并统一 QSS。
3. context actions 分 primary/overflow，只移动 command 入口，不删除能力。
4. 检查 800/1280/1440 下 status、导航、minimap、context island。
5. 入口或名称改变时同步 hints/quickref/help。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_floating_layout.py \
  tests/ui/test_ultraview_page.py tests/ui/test_ultraview_icons.py \
  tests/ui/test_hints.py tests/ui/test_quickref.py -q
```

**推荐提交**：`polish(ultraview): clarify chrome state and contextual controls`

## 6. Batch D — UltraView 操作手感

### Task 7：纯碰撞 planner、完整 ghost、原子提交

**文件所有权**

- 规划：`mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- 手势：`mf4_analyzer/ui/chart_stack/ultraview/gesture.py`
- ghost：`mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py`
- Card：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 提交/undo：`mf4_analyzer/ui/chart_stack/ultraview/page.py`
- 测试：`tests/ui/test_ultraview_free_grid.py`、`tests/ui/test_ultraview_page.py`、必要时新增 planner test

先冻结纯 DTO：

```text
LayoutPlan
  accepted: bool
  reason: enum | None
  mover_before / mover_after
  displaced_before_after: ordered collection
  operation: move | resize | arrange
  based_on_layout_revision
```

Planner 只接收 board bounds、占位、mover、目标和 operation，返回确定性 plan；不直接写 widget、signal 或 undo。

**先写 RED**

1. move 后 mover/blocker 的全部 span 不变。
2. resize 后只有 mover span 改变，blocker 只能平移。
3. 边缘无合法位置时拒绝，不扩大 mover、不缩邻卡。
4. 同一输入返回相同 displacement 顺序。
5. ghost geometry 与最终提交完全一致。
6. release 只产生一个 undo command，Undo/Redo 原子恢复。
7. Esc、失焦、reject 不提交，undo 长度不变。
8. routine collision 不创建/调用 `QMessageBox`。
9. 24 卡稠密场景搜索有上限，不在 mouse-move 做无界工作。

**步骤**

1. 从现有 grow/shrink/auto-avoid 分支提取纯 planner，先复用合法平移策略。
2. 为 move/resize/arrange 设置允许变化集合，并用断言保护 span 不变量。
3. 删除 routine drop modal，改为 status feedback。
4. ghost 接收完整 plan，显示 mover 和所有 displaced 卡片；reject 同时用图标/轮廓表达。
5. release 前校验 layout revision；stale plan 重算或拒绝。
6. 一次性写 geometry 和一个 undo command；release 后不得二次跳位。
7. 缩邻卡/边缘扩展仅属于显式 arrange；若本批不提供 arrange UI，则停用旧隐式行为。
8. planner 诊断节流，不能在每个 mouse move 打日志。

**性能门禁**

- 5 卡 ghost 无肉眼跳帧。
- 24 卡记录 planner p50/p95；超过交互预算时合并 move 更新或沿用最后合法 plan，不阻塞 GUI 线程。
- 最终 geometry 必须等于 release 前最后一帧 ghost。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_project_session.py -q
```

实现落地并有回归证据后，更新/取代两条旧 lesson：

- `docs/lessons-learned/pyqt-ui/2026-08-14-ultraview-edge-shrinks-neighbors.md`
- `docs/lessons-learned/pyqt-ui/2026-08-14-ultraview-overlap-asks-auto-avoid.md`

保留历史失败背景；新规则说明 direct manipulation 与显式 arrange 的边界。

**推荐提交**：`feat(ultraview): preview atomic size-preserving collision plans`

## 7. Batch E — 渲染稳定、文档与发布

### Task 8：空闲质量判定脱离全局鼠标偶发状态

**文件所有权**

- `mf4_analyzer/ui/pg_canvas/line_canvas.py` 或其现有 quality collaborator
- `tests/ui/test_pg_line_canvas.py`
- `tests/ui/test_pg_canvas_backref_invariants.py`

**先写 RED**

- 画布无 active gesture、但模拟其他窗口全局 mouse press 时，idle repin 仍有界完成。
- 画布 press 后 pending、release 后恢复；wheel/gesture 延后但不永久阻塞。
- provider 异常可观察，不吞 timer 编程错误。
- 目标测试重复 20 次无状态泄漏。

**步骤**

1. 追踪所有 activity 入口和 timer owner，保持一个可变状态 owner。
2. 用画布 press/move/release/wheel/gesture 生命周期驱动 activity。
3. `QApplication.mouseButtons()` 如保留，只能封装为可注入 defensive provider。
4. destroyed/clear 时停止 timer/signals，检查 Qt wrapper 生命周期。
5. `_CanvasBackref` owned/delegate names 如变化，同步 invariant test，不做未声明写入。

**GREEN**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_pg_canvas_backref_invariants.py -q
```

最终 node id 确定后另做 20 次窄循环；执行记录写真实 node id，禁止保留占位符后声称完成。

**推荐提交**：`fix(canvas): make idle quality follow local interaction state`

### Task 9：帮助、QuickRef、hints、lessons 与 diff hygiene

**文件所有权**

- `mf4_analyzer/help/ultraview-guide.html`
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- 对应测试
- Task 7 指定的两条 lessons
- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py` 当前 EOF whitespace，仅作窄修复

**内容**

- 帮助准确说明三级 LOD、完整 ghost、尺寸保持、reject、Undo 和 minimap 条件。
- QuickRef/hints 同步移动或新增的动作，不发明快捷键。
- 说明普通 move/resize 与显式 arrange 的区别。
- 更新旧碰撞 lessons，将新约束标为 current rule。
- 全仓搜索旧文案：伪精确帧数、低于 40% 只隐藏 footer、普通碰撞弹框、边缘自动长大。

**检查**

```bash
rg -n "抽样解码|仅标题|自动避让|智能整理|minimap|Ctrl\+Z" \
  mf4_analyzer docs/analyzer docs/lessons-learned tests

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_hints.py tests/ui/test_quickref.py \
  tests/ui/test_quickref_panel.py tests/test_verify_ultraview_visuals.py -q

git diff --check
```

**推荐提交**：`docs(ultraview): align help and lessons with direct manipulation`

### Task 10：分层验证与平台验收

#### 10.1 Owner 与架构门禁

先完成 Tasks 1–9 的 focused tests，再运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/test_conftest_autouse_scope.py tests/ui/test_qsettings_isolation.py -q
```

若 BLF/ASC 触及 Batch orchestration，再运行 `tests/test_batch_run_reporter.py`。Crash、timeout、异常退出全部记为 `UNVERIFIED`，不能根据退出前 passed 数推断成功。

#### 10.2 Full suite 两个 fresh process

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

记录两个命令的退出码、passed/failed/skipped 和耗时，不引用历史数字代替当前结果。

#### 10.3 真实 macOS Cocoa

用真实 `testdoc` MF4/HDF 和可复现 CAN fixture 验收：

1. 5 卡：template/free-grid、100/55/35、move/resize/reject/undo。
2. 24 卡：连续拖动、planner p95、minimap fit/scroll、Board 切换。
3. 800/1280/1440：type chip、chrome、context、tooltip、键盘焦点。
4. 圆角/backing rectangle：四角像素、popover、reject ghost。
5. freshness：stale/missing/loading/fresh 不与 type/active 混淆。
6. CAN：抽样文案、ASC fallback、取消和最终结果。

截图/日志放 `.state/`，除非用户要求 durable evidence，否则不入 Git。Cocoa 与 offscreen 证据分开陈述。

#### 10.4 Windows 发布门禁

只有准备发布 Windows 包时作为 blocker：

- Full/Lite 新 frozen executable 分别启动；
- 打开 MF4/BLF/ASC，验证 DBC candidate/progress；
- 执行 UltraView move/resize/undo/LOD/minimap；
- 打开主帮助和 UltraView guide；
- 检查 hidden-import/runtime import。

无法访问 Windows 时必须写“Windows frozen acceptance 未执行”，不能以源码/packaging tests 代替。

#### 10.5 Git 收口

```bash
git status --short
git diff --check
git diff --stat
git diff --name-only
git log --oneline --decorate -n 12
```

确认并行未跟踪文档、截图、缓存、QSettings、`.state` 证据未混入；每个提交只有一个行为 owner；规格验收项记录真实结果与未运行项。

## 8. 依赖与停止条件

```text
Task 1 RED -> Task 2 DBC model -> Task 3 ChannelFrame
Task 3 -> Task 4 ASC                 (共享 loader.py，串行)
Task 5 LOD -> Task 6 chrome          (共享 page.py/widgets.py，串行)
Task 6 -> Task 7 collision planner   (共享 page.py/widgets.py，串行)
Task 8 canvas quality                (独立 owner)
Tasks 2-8 -> Task 9 docs -> Task 10 full/platform gates
```

停止并重新评审的条件：

- 新抽样需要全量 DBC decode 才能满足测试；
- ChannelFrame 迁移让默认路径全表物化或破坏重复通道身份；
- planner 必须缩卡/扩卡才能完成普通 move；
- 24 卡 planner 无法限制 GUI-thread 工作量；
- 新状态需要跨多个 MainWindow mixin 写入或扩大 state-ownership whitelist；
- full suite 出现 Qt crash/顺序敏感失败，不能靠 fixed order、sleep 或 xfail 掩盖。

## 9. 风险与回退

| 风险 | 预防 | 可接受回退 |
| --- | --- | --- |
| DBC 分层样本不稳定 | 固定位置和 tie-break | 回退旧候选顺序，但保留 honest sample 文案，不恢复伪精确值 |
| 遗漏 pandas consumer | trace 调用点、能力测试 | 单个 consumer 显式 `load_blf_dataframe()`，不恢复伪 facade |
| ASC 映射影响两条链 | 单一 coordinator/outcome | fallback 阶段改 indeterminate，不允许进度倒退 |
| 24 卡 planner 超预算 | 纯函数 benchmark、合并更新 | 拒绝该落点，不回退 modal/隐式缩卡 |
| LOD 影响可达性 | geometry/focus tests | 回退隐藏粒度，不回退类型和 trust 持续可见 |
| QSS 圆角回归 | border gate + Cocoa 像素 | 回退 style token，不回退状态属性分离 |
| Qt teardown 异常 | 两进程 suite | 标记 UNVERIFIED 并查 ownership/fixture，不固定顺序 |

## 10. 规格追踪矩阵

| 规格验收 | 实施任务 | 主要证据 |
| --- | --- | --- |
| `V8H-A01`–`A04` | Tasks 1–2 | BLF 分布 fixture、candidate probe 次数、UI 文案测试 |
| `V8H-A05`–`A06` | Task 3 | ChannelFrame 单测、惰性物化计数、pandas parity、import boundary |
| `V8H-A07` | Task 4 | early/late fallback progress 序列与 outcome 断言 |
| `V8H-A08`–`A09` | Task 5 | LOD 临界点属性/geometry 测试与截图矩阵 |
| `V8H-A10`–`A11` | Task 6 | scroll-range、mode/panel 状态与 QSS 测试 |
| `V8H-A12`–`A15` | Task 7 | 纯 planner 不变量、ghost parity、reject、undo 测试 |
| `V8H-A16` | Tasks 6、9 | command 可达性、tooltip/accessibility、help/QuickRef |
| `V8H-A17` | Task 8 | local activity/provider 测试与 20 次窄重复 |
| `V8H-A18` | Tasks 3、5、7 | identity/digest/PreviewStore/project-session 回归 |
| `V8H-A19` | Tasks 5、6、10 | 800/1280/1440 × 100/55/35 截图矩阵 |
| `V8H-A20` | Task 10 | 5/24 卡真实 Cocoa 记录 |
| `V8H-A21` | Task 10 | focused、boundary、full two-process exits |
| `V8H-A22` | Task 10 | Windows Full/Lite frozen acceptance 或明确 blocker |
| `V8H-A23` | Tasks 9–10 | `git diff --check` 与最终 staged scope |

## 11. 完成清单

- [ ] DBC exact/sample/estimate 分开，UI 无伪精确帧数
- [ ] top-3 全部探测，cancel 外无 sampled-strong early break
- [ ] ChannelFrame、显式 pandas、惰性列访问通过
- [ ] ASC early/late fallback 单调且原因可观察
- [ ] 三级 LOD/type chip 在 100/55/35 正确
- [ ] Minimap 只在真实 scroll range 出现
- [ ] `modeActive` 与 `panelOpen` 分离
- [ ] 普通 move/resize 尺寸不变量成立、无 modal
- [ ] 完整 ghost、reject、单 command Undo/Redo 成立
- [ ] context actions 完整可达且 800 px 无覆盖
- [ ] idle-quality 不依赖全局鼠标瞬时状态
- [ ] help、hints、quickref、lessons 同步
- [ ] focused、boundary、full two-process gates 完成
- [ ] 5/24 卡真实 Cocoa 验收完成
- [ ] Windows Full/Lite frozen 验收完成或列为 blocker
- [ ] `git diff --check` 通过且无无关文件进入提交
