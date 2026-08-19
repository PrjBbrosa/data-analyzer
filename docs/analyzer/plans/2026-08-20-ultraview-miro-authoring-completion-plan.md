# UltraView Miro 式作者工具完整实施 Plan

- 日期：2026-08-20
- 状态：**M8 PARTIAL**（docs/help 已对齐；focused+boundary offscreen；COCOA UNVERIFIED；WINDOWS FROZEN UNVERIFIED；full suite NOT RUN）
- 体验 Spec：`../specs/2026-08-20-ultraview-miro-authoring-experience-spec.md`
- 数据/行为基线：`../specs/2026-08-15-ultraview-annotation-notes-arrows-spec.md`
- 恢复 Plan：`2026-08-19-ultraview-recovery-interaction-resize-autofit-plan.md`
- 开写基线：`a4035287`（Select+Sticky）+ `03d42d97`（Card Fit）；那是当时起点，不是现在的产品入口
- 当前 release 入口：Select / Sticky / Text / Shapes / Connector / Draw（含 Eraser/Lasso）；混装 rail 保留

> 2026-08-20 M8 supersession：作者工具已按 M0–M7 纵切接入 release。下文 M1–M6 里「仍只有 Select+Sticky / 其余隐藏」是当时波次出口，不是现在的产品文案。当前用户可见合同见 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py` 与 `mf4_analyzer/help/ultraview-guide.html`。Cocoa、Windows frozen 与全量套件仍 UNVERIFIED。

> 本 Plan 回答 recovery plan 里缺失的“后续到底怎么做”。它不授权本次 review 修改产品源码。
> 每波是一个能被用户完整使用的纵向切片；不能把所有按钮先放出来，再等待以后接功能。

## 0. 总结与依赖

### 0.1 当前资产

| 已有 | 当前可复用程度 | 禁止误判 |
|---|---|---|
| `BoardInteractionController` | 可作为唯一 tool/selection/draft owner | 目前 draft/create 只完整支持 Sticky |
| Author DTO/parser/normalizer | 已覆盖 Sticky/Text/Shape/Stroke/Connector | DTO 存在不等于编辑事务完成 |
| `author_geometry.py` | 已有基础映射/bounds/hit/simplify | 每个新对象仍需 owner-level correctness tests |
| `author_render.py` / layer / export | 已能消费多种对象 | 仍需真实 style parity、LOD、negative bounds 证据 |
| `BoardTextEditor` | 可复用 CJK/长度/focus 基础 | Page/coordinator 尚未交付 Text 纵切 |
| `ShapePopover` / `DrawPopover` / `TextFormattingToolbar` | 仅 scaffold/isolated chrome | 旧 QMenu/混合 rail 视觉不满足新 Spec，不能直接 release |
| Select + Sticky | 当前 release 纵切 | 尚待 R5 Cocoa/Windows 完整验收 |

### 0.2 执行图

```text
R5 Cocoa 收口（至少确认 Select+Sticky 与 resize 当前真实状态）
  -> M0 新 Miro-parity 决策 prototype / 用户视觉签字
  -> M1 Chrome IA 重构 + Sticky 迁移（release 仍只有 Select+Sticky）
  -> M2 Text 完整纵切
  -> M3 Shape 完整纵切
  -> M4 Connector 完整纵切
  -> M5 Pen + Highlighter 完整纵切
  -> M6 Eraser + Lasso 完整纵切
  -> M7 通用多选/格式/arrange 收口
  -> M8 集成、性能、文档、Cocoa/Windows 发布门
```

M0 之前不改产品 chrome；M1 之前不展示 Text/Shape/Connector/Draw；每一波只解锁自己完成的入口。

### 0.3 不允许的执行方式

- 不把 `RELEASE_AUTHOR_TOOLS` 一次改成全量；
- 不在 `chrome.py` 继续堆全部作者 UI；
- 不给每个工具新建一个 selection/tool/draft store；
- 不复制 bounds/style/render 逻辑到 Page、overview 和 compositor；
- 不以大范围 QSS 调色代替信息架构调整；
- 不在 dirty resize/ghost 工作同时跑 full suite 并把结果当稳定集成门；
- 不把 offscreen、HTML prototype、Cocoa、Windows frozen 证据互相替代。

## 1. 所有权与目标模块

### 1.1 预期模块边界

| 模块 | 责任 |
|---|---|
| `author_tools.py` | session-only active tool、selection、draft、gesture transaction；不画 UI |
| `author_geometry.py` | Qt-free map/snap/hit/route/simplify/bounds |
| `author_style.py` | 语义 palette/font/line/stroke resolver |
| `author_render.py` | screen/compositor 共用的 author draw primitives |
| `author_layer.py` | paint-only author/draft/selection/guide layer |
| `author_widgets.py` | Sticky editor、Text/shape-label 临时 editor |
| **新 `author_chrome.py`** | CreatorRail、ToolFlyoutSurface、SelectionToolbar 及 typed intents |
| **新 `author_edits.py`**（若审计确认需要） | Qt-free create/update/delete/style/reorder patch，避免 coordinator 按 kind 膨胀 |
| `chrome.py` | Board/Global/Navigation/Status 既有 chrome；兼容 re-export，不承载新工具内部实现 |
| `page.py` | 组合、坐标路由、focus/overlay lifecycle；不直接改持久化 Board state |
| `ultraview_coordinator.py` | mutation funnel/history/dirty/save projection；不拥有 widget session state |

`author_chrome.py` 是否最终拆出以 Task M1.1 的调用图为准；如果没有保留公开 import 的安全方案，
则先保持兼容 re-export，再逐个迁移，不能做一次大搬家。

### 1.2 Shared guards

任何新工具都必须复用：

- `BoardInteractionController.selection`；
- `BoardItemKey` / `AnchorTarget`；
- `is_text_input_widget()` 或等价的 editor focus guard；
- Board mutation funnel 和同一 history owner；
- `BoardContentBounds`；
- existing viewport router 的 Space/中键/右键平移；
- `FloatingChrome`/透明圆角 shell 的既有实现；
- diagnostics throttling 和具体异常分类。

## M0 — 重新做可决策的 Miro-parity prototype

### 目标

先把“界面和 Miro 差远了”变成可确认的产品结构，不在 PyQt 里盲调 QSS。

### 产物

- 新 `docs/analyzer/ui-prototypes/2026-08-20-ultraview-miro-authoring-experience-prototype.html`；
- 1280×720 和 800×560 **light** 两张 deterministic screenshot（不做 dark）；
- 一张 current app 对照图；
- 一张状态板：idle / hover / active / flyout / selected / editing / drawing / compact overflow；
- prototype 顶部明确 `DECISION PROTOTYPE — NOT PRODUCT EVIDENCE`。

### Task M0.1：基线截图

- [ ] 在当前 HEAD + 当前 dirty fingerprint 上启动真实 TraceLab；记录版本、主题、DPR、窗口尺寸；
- [ ] 打开只读 `testdoc/1.tlproj` 或副本；不得保存原 fixture；
- [ ] 拍 Select、Sticky flyout、选中 card、800×560 compact 四个真实状态；
- [ ] 记录 R5 中仍未解决的 resize/ghost/白底，不把新 prototype 当修复证据。

### Task M0.2：prototype 必备交互

- [x] 左轨保留 Library / Free Grid / Layout / Filter / 作者工具 / Unplaced / Sync；作者工具插在 Filter 与 Unplaced 之间；
- [x] Board Island 保持板名 + 切换 + 新建 Board，不加 `+ View`；
- [x] Unplaced/Stale 继续用 rail badge，不改成左下 status chip；
- [x] click active Sticky/Shape/Draw 打开 anchored flyout；
- [x] 点击 Text/Shape/Connector/Stroke 对象切换 typed selection toolbar；
- [x] 800×560 selection toolbar 使用 overflow，不换行；rail 不截断；
- [x] 只做 light；active tool 与 panelOpen 视觉正交，无钛蓝-琥珀渐变；
- [x] 展示 Signal Spine，但不得让每个工具图标使用分析分类色。

### Task M0.3：签字门

用户结论（2026-08-20）：

1. rail 保留全部 — ACCEPTED（拒绝 creator-only 搬家）；
2. 左上保持现状 — ACCEPTED（拒绝 `+ View`）；
3. selection toolbar — ACCEPTED；
4. Shape/Draw flyout — ACCEPTED；
5. 不需要 dark — ACCEPTED；
6. compact — ACCEPTED。

修订后的 prototype/Spec 已写入上述决定。M1 不得再把 rail 入口迁走。M0 是 docs-only，不跑 runtime tests。

### 出口

用户明确接受一个方向；否则 Plan 保持 `BLOCKED AT M0`，不把个人审美推到产品源码。

## M1 — 在现有混装 rail 上落地工具状态、flyout 与 Sticky 工具条

### 目标

不搬家固定 chrome。此波完成后功能仍只有 Select+Sticky，但 active tool / panel / flyout / selection
toolbar 达到新 Spec，800×560 overflow 可用。

### 所有权

- `floating_layout.py`
- `chrome.py` + 新/拆分 `author_chrome.py`
- `page.py`
- `ui_kit/style.qss`
- focused chrome/layout/visible-action tests

### Task M1.1：冻结现状与兼容面

- [ ] 记录 HEAD/dirty fingerprint；若 resize/ghost 三个未提交文件仍在，协调稳定后再开始 M1；
- [ ] `rg` 所有 `ToolRail`、`ShapePopover`、`DrawPopover`、`TextFormattingToolbar` import/call/test seam；
- [ ] 红测 public import/re-export、no dead visible action、800×560 geometry、tab/focus order；
- [ ] 红测 panel vs active-tool 正交状态，避免 `panelOpen`/`modeActive`/tool active 混淆；
- [ ] 冻结 existing Select+Sticky create/edit/undo/save/reopen 事务。

### Task M1.2：拆分 chrome

- [ ] 将 creator-only controls 放入 `author_chrome.py` 或等价 owning module；
- [ ] `chrome.py` 保留兼容 re-export，避免测试/消费者突然断裂；
- [ ] 新 `ToolFlyoutSurface(QFrame)`：统一圆角 shell、anchor、focus、Esc、outside click、compact clamp；
- [ ] 新 `SelectionToolbar(QFrame)` 基础壳：typed sections、overflow、Signal Spine、drag hide/release settle；
- [ ] 禁止用 platform `QMenu` 承载 Shape/Draw/Text 主格式 UI；普通 More actions 可以继续 QMenu。

### Task M1.3：保持固定 chrome，只扩创作段

- [ ] rail 顺序保持 Library / Free Grid / Layout / Filter / 创作段 / Unplaced / Sync；
- [ ] 创作段 release 仍只构造 Select + Sticky；Text/Shape/Connector/Draw 不出现；
- [ ] Board Island 不改：板名 + 切换 + 新建 Board；
- [ ] Unplaced/Sync 留在 rail，badge 非零才显示；
- [ ] 更新 `floating_layout.py`：12 入口（未来）与当前 8 入口都能在 800×560 完整显示，target 可收到 32 px；
- [ ] 800×560 Global Island overflow；toolbar 不换行。

### Task M1.4：视觉 token

- [ ] 引入 light-only `uvx.*` chrome tokens，映射现有 theme token；
- [ ] active tool 去掉钛蓝-琥珀 gradient，使用 selection wash + 左 bar；
- [ ] panelOpen / Free Grid mode 用中性填充，不得复用 tool active；
- [ ] surface 96–100% opaque；保留 rounded transparent shell，移除不产生真实 blur 的“假玻璃”层；
- [ ] rail 56 px 宽、36×36 target（compact 32）、20 px icon；
- [ ] light contrast 检查；Cocoa corner pixels/hover/active screenshot。不做 dark 变体验收。

### Task M1.5：Sticky 迁移

- [ ] 4×4 palette 改为 `ToolFlyoutSurface`；真实 swatch、选中 ring、pin；
- [ ] 第二次点 Sticky 打开 flyout且工具仍 active；outside click 只关 flyout；
- [ ] Sticky selection toolbar：palette/shape/font size/align/lock/more；
- [ ] 原 create/edit/undo/save/reopen 事务不回归；
- [ ] Release rail 仍只显示 Select + Sticky。

### Focused gates

- `tests/ui/test_ultraview_chrome.py`
- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_visible_actions.py`
- `tests/ui/test_ultraview_sticky_slice.py`
- `tests/ui/test_ultraview_author_integration.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_mode_integration.py`
- `tests/ui/test_qss_border_shorthand.py`
- `tests/ui/test_no_lambda_signal_connections.py`

### Cocoa gate

1280×720 / 800×560 light：完整混装 rail、Board Island、Sticky flyout、selection toolbar、Fit safe rect、
圆角四角像素。Select/Sticky 完成 click/drag/edit/undo/save/reopen；resize/ghost 不得因 chrome 改动回归。

### 出口

新骨架被真实 app 采用，功能仍只有完整 Select+Sticky，无死入口；否则回滚 M1 视觉结构，不进入 Text。

## M2 — Text 完整纵向切片

### 目标

交付 `T` → 创建/拖宽 → CJK 编辑 → 格式 → selection/move/resize → undo/redo → save/reopen → export。

### 所有权

- `author_tools.py`：Text draft/edit lifecycle
- `author_widgets.py`：`BoardTextEditor`
- `author_chrome.py`：Text creator + toolbar
- `author_style.py` / `author_render.py`
- `page.py`：editor geometry/focus/intent routing
- coordinator/mutation helper：typed create/update/history

### Task M2.1：先写红测

- [ ] `T` focus guard；QLineEdit/QTextEdit/QPlainTextEdit 及 viewport 后代不抢 shortcut；
- [ ] click default box、drag width、negative coordinates、safety clamp；
- [ ] empty cancel = 0 object/0 history；non-empty commit = 1 object/1 history；
- [ ] IME preedit/commit、Enter、Esc、focus-out、Board switch、window deactivate；
- [ ] 6000/6001 字符；invalid link；font role fallback；
- [ ] move/resize/style 各一条 history；save→reopen→export parity；
- [ ] presentation/overview/template 不创建且不残留 editor。

### Task M2.2：intent 与 mutation

- [ ] 将 Sticky-only intent 扩成 typed create/update，不用 `kind` + 任意 dict 静默分发；
- [ ] mutation helper 返回 object patch + warning，不直接 emit UI toast；
- [ ] coordinator 只负责应用 patch/history/dirty/refresh；
- [ ] programming error 传播，非法用户输入返回具名 validation；
- [ ] author edit 不 recapture、不改 digest。

### Task M2.3：编辑器与 toolbar

- [ ] 单击/拖拽创建后立即挂直接 sibling editor；
- [ ] editor geometry 随 zoom/scroll，但不在每个 pointer frame 重建；
- [ ] Text toolbar 40 px 单行：font/size/B/I/U/align/list/text/fill/link/lock/overflow；
- [ ] compact 低优先级入 overflow；editing 时 Board shortcuts 让给 editor；
- [ ] 退出 editor 后用 painter/轻量 text 渲染，不保留大量 QTextEdit。

### Task M2.4：发布面

- [ ] 只在全部 gate 通过后将 Text 加入 release rail；
- [ ] `hints.py`、`quickref.py`、UltraView guide 加 `T`、整框格式和 IME 说明；
- [ ] tooltip/accessibleName/shortcut 同步；无“部分格式”假承诺。

### Focused/boundary gates

- 新 `tests/ui/test_ultraview_author_text_slice.py`
- `test_ultraview_author_state.py`
- `test_ultraview_author_geometry.py`
- `test_ultraview_author_style.py`
- `test_ultraview_author_render.py`
- `test_ultraview_author_export.py`
- `test_ultraview_author_tools.py`
- `test_ultraview_page.py`
- `test_ultraview_viewport.py`
- `test_main_window_state_ownership.py`
- `test_no_lambda_signal_connections.py`

### Cocoa gate

中文/英文/emoji 输入；拖宽换行；格式；Cmd+Z 在 editor 内、commit 后 Board undo；缩放/平移中 editor 不漂；
800×560 toolbar overflow；保存副本并重开；PNG 对比。

### 出口

Text 完整事务全部通过后才显示；任一保存、IME、undo、export 断链则保持隐藏。

## M3 — Shape 完整纵向切片

### 目标

交付 5 个闭合形状，不把 connector 混入同一状态机。

### Task M3.1：红测

- [ ] Rectangle/Rounded Rectangle/Oval/Diamond/Triangle click + drag；
- [ ] Shift 比例、Alt 中心、Cmd/Ctrl disable snap、negative/safety bounds；
- [ ] 8 handles resize、move、copy、delete、lock、z-order；
- [ ] fill/stroke/width/dash/corner/switch type；不适用控件不出现；
- [ ] shape label IME/edit/empty/6000 boundary；label 不生成 Text 子对象；
- [ ] create/edit/style/reorder/save/reopen/export/overview/fit 各自一致。

### Task M3.2：flyout 与 draft

- [ ] Shape flyout 5 个视觉 cell，不用文本 QMenu 列表；
- [ ] 选择 cell 立即 arm，click/drag draft 由 author layer 画，不生成 QWidget；
- [ ] release 一次 create patch；one-shot 回 Select；pin 才连续；
- [ ] hit/selection handles 走共用 author geometry。

### Task M3.3：selection toolbar

- [ ] type/fill/stroke/width-style/corner/text/lock/more；
- [ ] switch type 保留 box/text/style/anchors；
- [ ] 多选同类 shape 支持共同 style；混合值显示 `—`，不伪造默认值；
- [ ] drag 中 toolbar 隐藏，release 后一次定位。

### 发布面

- [ ] 通过后 release rail 加 Shape；Connector/Draw 仍隐藏；
- [ ] 更新 hints/quickref/guide，只列 5 个真实 shape。

### Focused gates

- 新 `test_ultraview_author_shape_slice.py`
- author state/geometry/style/render/layer/export/tools/page
- compositor/overview/elastic workspace/visible actions
- qss border/no-lambda/state-ownership boundaries

### Cocoa gate

五形状 × light/dark；拖拽/resize 无闪；shape label CJK；toolbar clamp；Fit/overview/PNG 包含负坐标 shape。

### 出口

五形状全部纵切完成，不能只凭 `ShapeObject` render 或 flyout screenshot 解锁按钮。

## M4 — Connector 完整纵向切片

### 目标

交付 free line、arrow、elbow arrow 和 card/author anchors 的完整目标生命周期。

### Task M4.1：几何红测

- [ ] free-free、card-free、author-free、card-author、author-author endpoints；
- [ ] auto/N/E/S/W anchor；move/resize 后仍在轮廓；
- [ ] Shift H/V/45°；Cmd/Ctrl disable snap；
- [ ] deterministic H-V/V-H 与 elbow control；相同输入完全相同 path；
- [ ] target delete/Unplaced 固化最后点且 toast 一次；同名 display label 不误连；
- [ ] line/stroke width/arrowhead 纳入 hit/bounds/fit/export。

### Task M4.2：交互与 toolbar

- [ ] 独立 Connector rail button，`L` 激活最近 type；
- [ ] free 两击/drag 和四边 anchor drag 共用一个 draft state machine；
- [ ] endpoint/control handles 高于 object hit；Esc/Board switch/window deactivate 清 draft；
- [ ] toolbar：route、start/end head、color、width、dash、label、lock/more；
- [ ] double-click line 编辑单 label；editor/focus/history 复用 Text 子集。

### Task M4.3：mutation funnel

- [ ] card move/resize、author move/resize、target delete/Unplaced 都通过一个 endpoint re-resolve hook；
- [ ] mixed mutation 是一条原子 history；失败不能留下半移动 target/半更新 connector；
- [ ] no obstacle routing/curve/multi-bend/line-jump placeholder。

### 发布面与 gates

- [ ] 通过后加 Connector + `L`；Draw 仍隐藏；
- 新 `test_ultraview_author_connector_slice.py`；
- author geometry/state/render/layer/export/tools/page；
- free-grid gesture/history/coordinator/compositor/overview/elastic workspace；
- main-window state ownership/import boundaries/no-lambda。

### Cocoa gate

从 card/note/text/shape 四种目标拉线；移动/resize/删除/Unplaced；endpoint 重接；toolbar；save/reopen；PNG。

### 出口

连接不丢 identity、不漂 anchor、目标删除可恢复；否则 rail 保持隐藏。

## M5 — Pen + Highlighter 完整纵向切片

### 目标

先交付可靠连续画线和高亮，不把 Eraser/Lasso 一起塞进第一波 Draw。

### Task M5.1：确定性算法红测

- [ ] 0/1/2 点、重复点、短线、非有限值、负坐标、超 safety bounds；
- [ ] 1.5 screen px filter 在 zoom/DPR 下反算一致；
- [ ] RDP 对相同输入稳定；≤2048 points；
- [ ] Pen/Highlighter bounds 含 cap/width；screen/export path parity ≤1 px；
- [ ] 全板 60k points cap；拒绝/截断策略具名且不产生半 history。

### Task M5.2：draft hot path

- [ ] QMouseEvent/QTabletEvent 归一为普通 pointer sample；V1 忽略 pressure/tilt；
- [ ] draft path 使用增量 dirty rect；不重建整板 QImage、不 relayout editor、不跑 card planner；
- [ ] pointer up 一次 simplify + create patch + history；cancel 0 mutation；
- [ ] Space/中键/右键 Pan 暂停 draw sample，松开恢复 cursor；
- [ ] Board switch/deactivate/destroy 停 timer/signal/draft。

### Task M5.3：Draw flyout/presets

- [ ] `QFrame` flyout，不用 Pen→Preset 二级 QMenu；
- [ ] Pen/Highlighter 各 3 preset，真实宽度/颜色 preview；
- [ ] preset 写隔离 QSettings，不进 Board/project/history；
- [ ] tool/preset 状态清楚；active Draw rail icon 投影当前 subtool；
- [ ] Eraser/Lasso 在此波 flyout 内不构造，不能出现灰按钮。

### 发布面与 gates

- [ ] 通过后 release rail 加 Draw；flyout 只显示 Pen/Highlighter；
- 新 `test_ultraview_author_draw_slice.py`（pen/highlighter 部分）；
- author geometry/style/state/render/layer/export/tools/page；
- QSettings isolation、paint timer backstop、no-lambda、visible actions。

### Cocoa benchmark

- 24 cards + 120 authors + 30k points；Pen/Highlighter 各连续 30 s；
- pointer-to-draft-paint p95 ≤16.7 ms、max ≤33 ms；
- 无断线、blank frame、timer backlog、stuck cursor；
- 与无 author 基线 pan/zoom p95 退化 ≤15%。

### 出口

绘制手感和性能同时通过；Qt 算法 benchmark 或离屏 paint 不替代 Cocoa timeline。

## M6 — Eraser + Lasso 完整纵向切片

### 目标

补齐 Draw 工具组的删除与自由选择，保持 V1 复杂度可控。

### Task M6.1：Eraser

- [ ] stroke hit corridor 与 zoom/DPR 无关；只命中 persisted stroke；
- [ ] 一次 sweep 删除多 stroke = 一条 history；撤销恢复原 z-order/points/style；
- [ ] locked stroke 不删除；card/sticky/text/shape/connector 不删除；
- [ ] 快速 crossing 不因 sample 稀疏漏掉；用 segment corridor，不只测试采样点；
- [ ] full-board point index 若需要，owner 在 author geometry/index，不在 Page 新建 cache 真相；
- [ ] 不做 precision split，不展示 precision eraser 入口。

### Task M6.2：Lasso

- [ ] 闭合/未闭合/自交/短 path/Esc；
- [ ] card + author 中心点规则；locked object 不进入 move selection；
- [ ] Shift additive；普通完成替换 selection；
- [ ] lasso path 只 transient paint，完成后自动回 Select；
- [ ] selection 不 dirty、不存盘、不进 history。

### 发布面与 gates

- [ ] Draw flyout 解锁 Eraser/Lasso；tooltip 明示“整笔擦除”；
- 扩展 `test_ultraview_author_draw_slice.py`；
- author tools/geometry/layer/state/history/page/free-grid/visible-actions；
- Cocoa 用鼠标/触控板/可用时 stylus 验证连续 sweep 和 lasso。

### 出口

Draw flyout 四项全部可用，无不可实现的 precision/pressure 暗示。

## M7 — 通用 selection、批量格式与 arrange 收口

### 目标

把每个工具的局部工具条收敛成一致对象系统，避免 5 套不同的 selection 行为。

### Task M7.1：多选与 toolbar capability resolver

- [ ] 用 typed capability resolver 计算 toolbar controls，不在 Page 写按 kind 的散乱 if/else；
- [ ] homogeneous/mixed/indeterminate 状态；
- [ ] card+author 只显示安全共同动作；
- [ ] author align left/center/right/top/middle/bottom、horizontal/vertical distribute；
- [ ] duplicate/lock/unlock/z-order/delete；
- [ ] locked 和 unknown author object 明确规则；unknown 不编辑、不丢失。

### Task M7.2：原子 history

- [ ] batch style、align、distribute、z-order、mixed move/delete 各一条 history；
- [ ] card delete 仍是 Unplaced，author delete 仍是真删除；同一 mixed action 原子恢复；
- [ ] 失败不留半状态；32 MiB/100 entry history budget 可观测。

### Task M7.3：键盘与剪贴板

- [ ] Cmd/Ctrl+D、C/V、Delete/Backspace、arrow nudge、Shift nudge；
- [ ] editor focus 时快捷键不被 Board 抢走；
- [ ] copy/paste author 使用 typed payload，不复用 display label identity；
- [ ] 跨 Board paste 生成新 object ids，connector 内部 target remap；外部 target 退化 free point。

### Gates

- 新 `test_ultraview_author_multiselect.py`
- author state/tools/geometry/history/page/coordinator
- card gesture/free-grid/placement history
- main-window ownership/import boundaries/no-lambda

### 出口

所有对象使用一个 selection truth、一个 toolbar capability resolver、一个 history funnel。

## M8 — 集成、性能、文档与发布门

### 目标

证明完整作者体验在真实项目、真实窗口和平台上可发布，而不是“每个组件测试都绿”。

### Task M8.1：端到端 fixture

构建本地 deterministic Board 副本：

- 24 cards；
- 24 Sticky、24 Text、24 Shape、12 Connector、36 Stroke；
- 30,000 points；
- 正/负坐标、locked、mixed selection、target lost、unknown author；
- light/dark、1280×720/800×560、DPR1/DPR2。

不得把生成的项目/截图直接加入 Git，除非单独批准 durable evidence；本地证据放 `.state/`。

### Task M8.2：E2E 用户脚本

- [ ] Add View → Sticky → Text → Shape → Connector → Pen → Highlighter → Eraser → Lasso；
- [ ] 每类 move/resize/style/lock/copy/delete/undo/redo；
- [ ] save→close→reopen；Board duplicate；project duplicate；
- [ ] Fit/Overview/Presentation；PNG 1×/2×、copy board；
- [ ] Board switch/editor active/window deactivate；
- [ ] 800×560 overflow/flyout clamp；
- [ ] no visible+enabled dead action。

### Task M8.3：focused/boundary gate

先跑全部 author owner tests，再跑：

- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_free_grid.py`
- `tests/ui/test_ultraview_placement_history.py`
- `tests/ui/test_ultraview_elastic_workspace.py`
- `tests/ui/test_ultraview_compositor.py`
- `tests/ui/test_ultraview_mode_integration.py`
- `tests/ui/test_ultraview_viewport.py`
- `tests/ui/test_ultraview_visible_actions.py`
- `tests/ui/test_qss_border_shorthand.py`
- `tests/ui/test_no_lambda_signal_connections.py`
- `tests/ui/test_main_window_state_ownership.py`
- `tests/ui/test_import_boundaries.py`
- `tests/test_packaging_imports.py`

命令使用项目 runtime：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest <focused files>
```

### Task M8.4：full gate 所有权

只有稳定 integration milestone 才跑一次 full suite。先确认无同 checkout pytest，记录 HEAD + dirty scope；
source 在运行中改变则结果 `UNVERIFIED`。按仓库约束分两进程且不得并行：

1. main suite `--ignore=tests/acquisition_ui`；
2. `tests/acquisition_ui`。

### Task M8.5：视觉/性能/平台

- [ ] macOS Cocoa：两尺寸、两主题、DPR、IME、trackpad、全部工具 E2E；
- [ ] frame timeline：resize、shape resize、pen/highlighter、pan/zoom；
- [ ] screenshot 自动 compare：rail/flyout/toolbar/corners/overflow；
- [ ] Windows source/packaging checks；
- [ ] fresh Windows Full/Lite frozen executable：mouse/stylus ordinary path、Ctrl shortcuts、save/reopen/export；
- [ ] Windows 未跑时明确 `WINDOWS FROZEN UNVERIFIED`，不能用 macOS 代替。

### Task M8.6：文档

- [x] `ui/hints.py`；
- [x] `ui/quickref.py`；
- [x] `help/ultraview-guide.html`；
- [x] shortcut、one-shot/pin、整框文字格式、整笔擦除、connector 简化边界；
- [x] 删除/改写任何仍说“只有 Select+Sticky”的当前基线文案；
- [x] 历史 dated review/spec 不改造成伪当前证据，只加清晰 supersession 指向。

### 最终出口

只有以下全为真才可 `ACCEPTED`：

- M0–M7 每波出口有测试、截图、用户手势和项目 round-trip 证据；
- creator rail 无 dead affordance；
- 24 cards/120 authors/30k points 达到性能预算；
- Cocoa 真机通过；
- Windows frozen 通过，或发布结论明确限定为 macOS-only 未验收；
- docs/help 与 release 入口一致；
- `git diff --check` 通过、无无关 dirty 文件进入提交。

## 2. 推荐提交边界

每个波至少一个独立提交；避免一个提交同时做 chrome 重构和新工具算法：

1. `docs(ultraview): approve Miro authoring experience direction`
2. `refactor(ultraview): separate creator rail and author chrome`
3. `feat(ultraview): add complete text authoring slice`
4. `feat(ultraview): add complete shape authoring slice`
5. `feat(ultraview): add anchored connector slice`
6. `feat(ultraview): add pen and highlighter slice`
7. `feat(ultraview): add stroke eraser and lasso`
8. `feat(ultraview): complete author multi-selection tools`
9. `docs(ultraview): close authoring acceptance evidence`

提交前只 stage 该波 owner/test/docs；当前工作树中的 `ssh-keygen*` 和任何无关 dirty 文件不得进入。

## 3. 回退策略

- M1 失败：恢复旧 tool/panel 视觉，保留 current Select+Sticky 与现有 rail 分区；不删除 author state；
- M2–M6 任一工具失败：从 `RELEASE_AUTHOR_TOOLS` 隐藏该工具，保留 unknown/recognized payload round-trip；
- 性能失败：先关闭该工具 release 入口，保留数据 load/render；不得通过降低 card preview 清晰度掩盖；
- save/history 失败：整波 NO-GO；不得以“新项目可用”绕过旧项目/duplicate/reopen；
- Cocoa/Windows 未验证：保留证据等级，不能把 offscreen green 改写成平台接受。

## 4. 执行状态表

| 波 | 状态 | Release 变化 | 当前阻塞 |
|---|---|---|---|
| R5 | PARTIAL | Select+Sticky 已在 release | Cocoa resize/visual/perf 与 Windows 仍需当前快照复核 |
| M0 | DIRECTION ACCEPTED WITH AMENDMENTS | 无 | rail 保留全部、左上现状、light-only；等修订截图确认后进 M1 |
| M1 | FOCUSED GATES GREEN | 混装 rail 保留，仍 Select+Sticky | Cocoa 未跑；可进 M2 红测 |
| M2 | FOCUSED GATES GREEN | + Text | Cocoa 未跑；Shape/Draw 仍隐藏 |
| M3 | FOCUSED GATES GREEN | + Shape | Cocoa 未跑；Connector/Draw 仍隐藏 |
| M4 | FOCUSED GATES GREEN | + Connector | Cocoa 未跑；Draw 仍隐藏 |
| M5 | FOCUSED GATES GREEN | + Draw/Pen/Highlighter | Cocoa 画线预算未跑；Eraser/Lasso 仍隐藏 |
| M6 | FOCUSED GATES GREEN | + Eraser/Lasso | Cocoa 手势未跑 |
| M7 | FOCUSED GATES GREEN | 通用多选/arrange | Cocoa 未跑 |
| M8 | PARTIAL：docs/help 已对齐；focused+boundary offscreen | 作者工具文档与 release 入口一致 | COCOA UNVERIFIED；WINDOWS FROZEN UNVERIFIED；full suite NOT RUN because worktree is dirty with parallel R5 ghost files |
