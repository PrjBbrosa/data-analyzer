# UltraView 画布创作工具（便签贴纸 + 画笔 + 形状 + 文字）实施 Plan

- 日期：2026-08-19 · 状态：**SUPERSEDED FOR EXECUTION；保留为历史任务/测试清单**
- spec：`docs/analyzer/specs/2026-08-15-ultraview-annotation-notes-arrows-spec.md`
- 范围：一个完整 feature 批次；不是 annotation polish，也不能拆成四套彼此独立的实现
- 当前执行结论：**不得从本 plan Task 0 直接开工；改用 2026-08-20 M0–M8 Plan**

> 当前计划：`docs/analyzer/plans/2026-08-20-ultraview-miro-authoring-completion-plan.md`。
> 本文仍可作为旧风险、owner 和测试候选索引，但其中 rail 结构、当前代码事实与一次性大 feature 批次
> 已过期；执行者必须以当前 checkout 和新 Plan 为准。

## 0. 当前软件状态与计划修正

本 plan 按 2026-08-19 checkout 的真实接缝编写，不能继续沿用旧文档中的历史假设：

| 当前事实 | 对施工的影响 |
|---|---|
| `ULTRAVIEW_SCHEMA = 5`，card grid 已是 2×2 micro-grid 且支持 signed safety bounds | 作者对象坐标以 schema-5 canonical micro-grid 浮点表示；不能按旧 12×48/非负域 clamp |
| Board 已有 flat blank-context menu；右键短按与右键拖动由 `ViewportGestureRouter` / Page 协作 | 创作入口进 rail；不创建第二套右键 owner，不重写现有 menu |
| `UltraViewPage._selected` 与 `FreeGridGesture` 仍以 `UltraViewRef` 为主 | 必须先统一 `BoardItemKey` 选择源，否则 mixed selection、Esc、工具条会漂移 |
| undo 只冻结 `BoardPlacementSnapshot` | stroke 不能塞入全量 snapshot；先建立 patch-based `BoardEditEntry` |
| 2026-08-19 Task 0 审计：Board `passthrough` 在 duplicate 时只浅拷贝嵌套 mapping/list | `author_objects` 不能直接落入现有 passthrough；先以红测修复深度隔离，之后才可通过 D10 |
| `content_bounds()`、Fit、elastic extent、export crop 只看 cards | 作者对象 bounds 必须先进入一个共享 `BoardContentBounds`，否则负坐标内容会被裁 |
| BoardOverview 已能走 compositor projection | author draw 接入 compositor 后 overview 复用，不能另写概览渲染器 |
| `_text_field_has_focus()` / focus guard 只识别 `QLineEdit` | 在加入 QTextEdit 前先抽 `is_text_input_widget()`，覆盖 viewport 后代 |
| 当前 ToolRail 是 panel launcher，且 template/free-grid active chrome 有既有测试 | rail 增 creation section，但 `panel_requested` 与 `tool_requested` 状态机必须分离 |

执行时工作区可能有并行 UltraView 改动。Task 0 记录 HEAD 与 dirty fingerprint；本批只在
相关 owner 稳定后开始，绝不覆盖、revert 或“顺手整理”并行改动。旧文档中的固定 commit、
固定测试 pass 数和“先跑所有 tests/ui”均删除。

## 1. 总体施工策略

依赖链：

`state/history` → `geometry/bounds` → `selection/render shell` →
`rail/tool state` → `sticky+text` / `shape+connector` / `pen` →
`Fit+overview+export` → `docs+Cocoa+integration gate`

实现模块边界：

- `mf4_analyzer/ui/ultraview_state.py`：Qt-free 持久化 DTO、normalization、作者对象 mutation、history DTO。
- `mf4_analyzer/ui/chart_stack/ultraview/author_geometry.py`：Qt-free 映射、bounds、hit、snap、anchor、route、stroke simplification。
- `.../author_tools.py`：transient tool/selection/gesture controller，不持久化数据。
- `.../author_layer.py`：paint-only layer、selection chrome、dirty-region rendering。
- `.../author_widgets.py`：便签与临时文字 editor、浮动工具条/popover。
- `widgets.py` / `page.py` / `chrome.py`：只做宿主接线与现有 owner 迁移；不把上述实现重新堆回大文件。
- `compositor.py`：消费同一 author geometry/style，负责 screen-independent composition。

禁止新增 multi-file MainWindow writes；不把新行为塞进 compatibility facade；不碰 `signal/`
或任何分析计算模块；不新增 broad `except Exception`；不使用 `.connect(lambda ...)`。

## Task 0：硬门、接缝冻结与决策原型

### 0A. 稳定快照与 focused baseline

- [ ] 记录执行时 `git rev-parse HEAD`、`git status --short`、相关文件 hash；确认没有另一个
  full pytest 在同 checkout 运行。若 owner 文件正被并行修改，先协调/等待，不做覆盖式合并。
- [ ] 只跑受影响 focused baseline，不跑通用 `tests/ui`：

  ```bash
  TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    .venv/bin/python -m pytest \
    tests/ui/test_ultraview_state.py \
    tests/ui/test_ultraview_free_grid.py \
    tests/ui/test_ultraview_page.py \
    tests/ui/test_ultraview_viewport_router.py \
    tests/ui/test_ultraview_chrome.py \
    tests/ui/test_ultraview_compositor.py \
    tests/ui/test_ultraview_elastic_workspace.py -q
  ```

- [ ] 若现有 focused 红，记录为 `PRE-EXISTING` 并判定是否阻断本功能；不能把未知红当绿，
  也不能先跑 full suite 寻找“更干净的数字”。

### 0B. 五个硬门

- [ ] **Passthrough 门（当前红，首个修复项）**：2026-08-19 已实测未知 Board 键（模拟嵌套
  `author_objects`）经 load → duplicate Board 后会浅共享内层 mapping/list。先写红测，再修为
  load → clone/无关 mutation → save 深度语义等价，且原输入与原 Board 均不被 alias mutation；
  未通过前后续对象模型暂停。
- [ ] **选择门**：画出 Page、FreeGridGesture、CardContextIsland 当前 selection/clear/Esc
  调用图，确认可迁移到单一 `BoardItemKey` 集合；不允许保留“卡片选择 + 作者选择”两套真相。
- [ ] **边界门**：定位 `content_bounds` → `desired_extent` → `workspace_extent` →
  `content_rect_1x` → `zoom_fit` 以及 compositor crop 的完整链；确认能够注入一个共享 union。
- [ ] **输入门**：验证 `ViewportGestureRouter` 的 CanvasHost scope、右键 deferred pan、text
  focus 与新 interactive siblings 的事件路径；不能让 author widget 绕过 router 生命周期。
- [ ] **History 门**：定位当前 placement undo 的 owner/容量/恢复入口，批准 spec D9 的
  `BoardEditEntry` patch 方案；若真正 owner 不在预期位置，先重写 Task 2 锚点再施工。

### 0C. Miro 决策原型

- [ ] 在独立 UI prototype（非产品路径）渲染：三段 rail、16 色 sticky popover、shape menu、
  draw preset popover、text floating toolbar、mixed-selection toolbar。
- [ ] 用 1280×720 与 1600×1000 两个尺寸验证不遮住 fit-safe stage、popup clamp 和 toolbar
  上/下翻转；深浅主题各一张。用户确认后才进入 Task 4 产品 chrome。
- [ ] 原型只裁决密度、顺序、尺寸和状态；不作为真实手势、Cocoa 或导出证据。

**Task 0 出口**：五门全绿、原型已裁决、owner 文件不再并行变化。任一缺失均为
`BLOCKED`，不能以“实现时再看”跳过。

## Task 1：Qt-free 作者对象模型与持久化

- [ ] 先写 `tests/ui/test_ultraview_author_state.py` 红测：五种 recognized kind、unknown kind、
  duplicate id、NaN/Inf、负坐标 safety bounds、文本/对象/点数上限、结构化 anchor、深度 round-trip。
- [ ] 在 `ultraview_state.py` 增 `BoardPoint` / `BoardBox` / `BoardItemKey` /
  `AnchorTarget` 与 Sticky/Text/Shape/Stroke/Connector DTO；Board 增 additive
  `author_objects`，不 bump schema 5。
- [ ] `_BOARD_PAYLOAD_KEYS`、`_board_payload`、normalize、clone/copy、workspace list payload
  全链路接入；recognized 非法项 warning，unknown mapping 保序透传。
- [ ] 提供 Qt-free mutation：create/update/delete/duplicate/reorder/lock/batch-style；全部返回
  结构化 result/warnings，不自行碰 QWidget 或 workspace dirty。
- [ ] 卡片移到 unplaced/删除时调用纯函数 resolve → detach connector endpoint；确保结构化
  card/author target 不因同名字符串误连。
- [ ] focused gate：author state + 现有 state/preview-sidecar/project-session 序列化测试；
  证明无 author object 的旧 payload 不发生无关 churn。

## Task 2：统一 history、dirty 与文字焦点

- [ ] 先写 `tests/ui/test_ultraview_board_history.py`：create/move/style/text/stroke/Stack/
  eraser/mixed move 各一条 undo；redo 分叉清理；100 条/32 MiB budget；Board 间 history 隔离。
- [ ] 保留 `BoardPlacementSnapshot` 作为 placement patch 的值类型；新增带
  `before_index`/`after_index` 的 `ObjectPatch` 与 `BoardEditEntry`，由现有 per-Board history
  owner 统一 push/undo/redo。没有 index 的 patch 不能正确回放 create/delete/z-order。
- [ ] mixed edit 原子提交：placement before/after + author before/after 同条恢复；失败不能留下
  半套卡片位置或半套 author object。
- [ ] 统一 mutation funnel：成功持久化编辑才 `mark_workspace_mutated`；hover/tool/draft/
  selection/camera 不 dirty；author edit 不 recapture、不改 preview digest。
- [ ] 抽 `is_text_input_widget(widget)`，覆盖 QLineEdit/QTextEdit/QPlainTextEdit 及内部 viewport；
  Page Esc/undo/redo/space/tool shortcuts 全部复用。
- [ ] focused gate：history/state/page focus；再跑 `tests/ui/test_main_window_state_ownership.py`，
  不扩大 whitelist。

## Task 3：Qt-free 几何、bounds 与数值上限

- [ ] 新建 `tests/ui/test_ultraview_author_geometry.py`，先覆盖：0.25 lattice、6 px guide、
  Board↔pixel round-trip、负坐标、shape path bounds、arrowhead inflation、anchor boundary、
  elbow H-V/V-H、segment/stroke hit、lasso center、RDP deterministic output。
- [ ] `author_geometry.py` 不导入 PyQt；点/box/line/path 使用 tuple/dataclass，renderer 负责
  转 QPainterPath。空、1 点、2 点、重复点、non-finite、极端 zoom 都有明确定义。
- [ ] 建立唯一 `board_content_bounds(cards, author_objects, metrics)`；stroke width 与 arrowhead
  向外扩展后 floor/ceil 到 micro-grid，clamp 到 engineering safety bounds 并返回可见 warning。
- [ ] 修改 `elastic_workspace.content_bounds` 调用面，使 signed author bounds 参与 desired extent；
  禁止另加 raw object-count/full-height heuristic。
- [ ] stroke pipeline：screen-distance debounce → RDP → max 2048 points；测试证明相同输入稳定、
  首尾保留、形状误差在 tolerance 内、全板 60,000 点预算可预测。
- [ ] focused gate：author geometry + elastic workspace + free-grid mapping/zoom-anchor tests。

## Task 4：统一选择与 render shell

- [ ] 先写 UI 红测：card/author mixed selection、Shift toggle、marquee、lasso、Esc、空白点击、
  hide/deactivate、locked object、CardContextIsland 与 author toolbar 互斥/共存规则。
- [ ] 引入 `BoardInteractionController`（或扩展现有 owner，但只能一个）：持有 active tool、
  `set[BoardItemKey]`、draft gesture、guide；Page 只消费选择投影和 emitted intent。
- [ ] 将 `UltraViewPage._selected`、FreeGridGesture selection、template selection 的 clear 路径
  收敛为 `clear_board_selection()`；Library row highlight 仍不是 Board selection。
- [ ] 新增 paint-only `AuthorPaintLayer` 与同级 interactive widget host；验证 z-order：cards <
  author < selection/guide/ghost。不要把 child editor 挂进 mouse-transparent parent。
- [ ] author hit-test 逆持久化 z-order；屏幕 hit tolerance 反算 Board 单位。drag move 使用 dirty
  rect union，不每帧 allocate full-board QImage。
- [ ] 通用 toolbar：author lock/duplicate/delete/z-order/align/distribute；混合 Delete 同时走
  card→Unplaced 与 author delete，纯 author 才显示 align/distribute。位置 clamp 到 CanvasHost，
  resize/zoom/selection 后重算。
- [ ] focused gate：author layer/tools + page/free-grid/card-context + viewport router + structure test；
  检查新协作者没有扩大 `_page_of` 私有调用面。

## Task 5：Rail 与 tool 状态机

- [ ] 按 Task 0 原型更新 `ToolRail`：三段顺序、creation buttons、独立 `tool_requested`；
  `panel_requested` 的 checked/open 与 tool active/pinned 不能共用一个 flag。
- [ ] template/presentation/overview 中 creation buttons 可见但 disabled；tooltip 解释原因；
  free-grid 恢复后默认 Select，不偷偷恢复危险的 Eraser/Pen。
- [ ] `V/N/T/P/L/R/O` shortcut 与 one-shot/pin/Esc 状态机；tool active 时中键、Space+左、
  右键 deferred pan 仍工作；右键短按保留既有 card/blank menu。
- [ ] Draw/Sticky/Shapes popover 共用 rounded popup shell（含
  `WA_TranslucentBackground`）；不能仅靠 QSS radius 留矩形 backing。
- [ ] 更新既有 rail order/template-active tests，不通过删除旧断言来“适配”；补小屏 popup
  clamp、keyboard focus、accessible name/tooltip 测试。
- [ ] focused gate：chrome/page/viewport-router/QSS border shorthand/no-lambda。

## Task 6：便签贴纸与文字

### 6A. Sticky

- [ ] 红测：click/drag create、min size、square/wide、16 palette token、auto/fixed font、
  3000 字符、空白自动删除、multi-style、Stack=6 ordinary objects/one undo、LOD 40%。
- [ ] `StickyNoteWidget` 只负责显示/编辑；geometry/style 由 DTO + shared resolver 驱动。
  文字提交、IME、点外/Enter/Tab/Esc 的 commit/cancel 语义逐项覆盖。
- [ ] Stack 只批量创建普通 notes，不新增容器/库存 state；offset 用 Board mapping 从 100% 6 px
  换算，zoom/export 保持相同相对 Board 位置。

### 6B. Text

- [ ] 红测：click auto-width、drag fixed-width、6000 字符、整框 font role/size/B/I/U/
  alignment/list/color/fill/opacity/link、resize wrap、focus guards、undo 边界。
- [ ] 使用临时 `BoardTextEditor(QTextEdit)`；提交后 painter/轻量 label 渲染。格式明确作用整框，
  不依赖 Qt `toHtml()` 作为持久化格式。
- [ ] font resolver 同时供 screen 与 compositor；增加中英文 glyph/ink proof。http/https 校验；
  非 presentation 不因普通选择点击打开外部链接。
- [ ] floating text toolbar 按参考图保留核心项；comments/AI/不可用的 more action 不渲染。
- [ ] focused gate：sticky/text widgets、state/history、CJK render probe、page shortcuts。

## Task 7：形状、连接线与锚定

- [ ] 红测覆盖 9 个菜单项、closed shape path/label、style、straight/elbow/divider、Shift 约束、
  free endpoint、card/note/text/shape anchor、target move/resize/delete、toast once。
- [ ] shape popover 顺序与 spec 一致；闭合 shape 和 block arrow 共用 box/style mutation，
  shape label 复用 Text 的整框级子集但仍是同一 object。
- [ ] connector 创建：两击放置 + 4 边 connection points；auto/N/E/S/W anchor；Cmd/Ctrl
  暂停 snap/anchor；端点拖拽 reattach/detach。
- [ ] elbow 仅 deterministic H-V/V-H + 一个 bias/control；不加入 obstacle graph、curves、
  line jumps。任何后续 route 扩展必须另写 spec。
- [ ] 卡片 move/resize/移入 unplaced 和 author target delete 的 mutation funnel 都调用 endpoint
  resolve/detach；一批 target loss 合并 toast，undo 可恢复锚定关系。
- [ ] focused gate：author geometry/tools/layer、free-grid gesture/state/history、compositor path parity。

## Task 8：画笔、高亮、整笔擦除与 Lasso

- [ ] 红测：mouse/tablet-like samples、3 presets each、pen/highlighter alpha、one stroke one undo、
  cancel/deactivate no commit、RDP cap、total-point cap、whole-stroke eraser、lasso center selection。
- [ ] pointer move 只更新 draft path + dirty rect；release 后才 normalize/create object/push history。
  不能在 move 中 serialize board、mark dirty 或重建所有 cached paths。
- [ ] Pen/Highlighter 每种 3 个 preset；preset 作为每用户 UI 偏好接入现有隔离过的
  QSettings 路径，active subtool/preset 只做会话态；二者都不进 Board/project/history/digest，
  也不新增 MainWindow state。
- [ ] Eraser 只 hit/delete StrokeObject；一次 sweep 内 dedupe object ids，release 一条 undo。
- [ ] Lasso draft 画在 top chrome layer；闭合后只提交 selection，不 dirty、不进 history。
- [ ] QTabletEvent pressure/tilt 明确忽略；Cocoa/Windows 手写笔只做基本 pointer acceptance，
  不把 offscreen mouse test 宣称成 stylus 验收。
- [ ] focused gate：pen/tools/layer/geometry/history + viewport pan coexistence + layer timer/lifecycle。

## Task 9：Fit、elastic extent、overview、presentation 与 export

- [ ] 先写负坐标/author-only Board 红测：Fit content rect、workspace extent、export size/origin、
  1×/2× composed rect、overview projection 均包含 author bounds。
- [ ] `FreeGridBoard.content_rect_1x/content_rect`、Page extent refresh 与 `zoom_fit` 消费共享
  BoardContentBounds；空 card 但有 author content 不走空板 working frame。
- [ ] compositor export crop 按 cards ∪ authors 计算 origin/size；draw 顺序 cards → authors；
  arrowhead/stroke/shape/text/Sticky 的 screen/export style resolver 共用。
- [ ] BoardOverview 走现有 compositor projection，允许低 LOD，但不能漏 author；点击 author
  不需要新增 overview navigation target，点击仍只负责回到相应 Board 区域。
- [ ] presentation 隐藏 handles/guides/toolbars/rail creation active chrome，保留作者内容；
  Cmd/Ctrl+click link 单独做 foreground 安全验证。
- [ ] export guard 将 author-only 超大 signed extent 纳入 edge/pixel cap，错误沿现有
  `ComposeError` 明确上报；不能 allocation failure 后静默降质。
- [ ] deterministic real-render artifact：100% screen geometry → PNG 1× ≤1 px，2× 等比；
  parity 只证明两路一致，另保留 owner-level shape/text/stroke correctness tests。

## Task 10：帮助、性能、边界门与真机收尾

### 10A. 产品帮助与可发现性

- [ ] 同步 `ui/hints.py`、`ui/quickref.py`、UltraView help guide：rail、`V/N/T/P/L/R/O`、
  Cmd/Ctrl 临时关吸附、Alt duplicate、连接点、Stack、Eraser/Lasso、锁定。
- [ ] 明示 V1 精简：整框文字格式、整笔擦除、无 AI/评论/智能路由；避免帮助承诺未实现行为。
- [ ] 更新 narrow-rail / P3 governing docs 的日期批注，只记录新 creation section 与 shared
  selection/bounds 接缝；不改写历史验收结果。

### 10B. Focused boundary gates

依次运行 changed owner tests，再运行适用边界：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_author_state.py \
  tests/ui/test_ultraview_board_history.py \
  tests/ui/test_ultraview_author_geometry.py \
  tests/ui/test_ultraview_author_tools.py \
  tests/ui/test_ultraview_author_layer.py \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_viewport_router.py \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_compositor.py \
  tests/ui/test_ultraview_elastic_workspace.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/test_help_content.py -q
```

### 10C. 性能与 foreground acceptance

- [ ] 真机 Cocoa：4 张 reference workflow 对照截图；rail/popover/toolbar 圆角 backing、层级、
  小窗 clamp、深浅主题、中文 IME、right-pan coexistence。
- [ ] 场景 A：24 cards + 120 mixed objects + 30k points，记录 zoom/pan p50/p95；相对同 Board
  无 author objects 基线 p95 退化 ≤15%。
- [ ] 场景 B：连续 Pen/Highlighter 30 秒，记录 pointer-to-paint latency、dropped samples、
  release simplify time；UI 不冻结，取消/切窗不留半笔。
- [ ] macOS foreground 与 Windows frozen/stylus 是不同证据。没有 fresh Windows Full/Lite
  executable 验收时明确写 `UNVERIFIED`，不能用 source/offscreen 替代。

### 10D. 稳定 integration milestone

- [ ] `git diff --check`；记录 full gate 前后 HEAD + dirty scope，期间相关文件变化则结果为
  `UNVERIFIED`。
- [ ] 仅由一个 coordinator 在稳定 milestone 跑一次 full gate；先检查运行中的 pytest，
  两个 fresh process 串行，绝不并发：

  ```bash
  TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    .venv/bin/python -m pytest --ignore=tests/acquisition_ui
  TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    .venv/bin/python -m pytest tests/acquisition_ui
  ```

- [ ] 异常退出、timeout、SIGSEGV 或被中断均记 `UNVERIFIED`；不从已完成测试数量推断 pass。

## Definition of Done

只有同时满足下列条件才可把本 feature 标记完成：

1. spec §9 十项量化验收全部有对应自动化或 foreground 证据；
2. 四类工具共用同一 selection/history/bounds/render 架构，没有四套平行状态；
3. 既有 card grid、右键平移/menu、Fit、preview digest、零计算合同无回归；
4. 帮助与快捷键同步，V1 精简边界对用户可见；
5. focused + boundary gates 通过，full gate 在稳定快照只跑一次且结果有效；
6. Cocoa foreground 已完成；Windows frozen/stylus 若未完成，发布结论明确保留该缺口。
