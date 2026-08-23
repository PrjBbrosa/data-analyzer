# UltraView Hardening 后续架构优化 Plan

- 日期：2026-08-22
- 状态：**PROPOSED / BLOCKED BY HARDENING COMPLETION**
- 对应 Spec：`docs/analyzer/specs/2026-08-22-ultraview-post-hardening-architecture-optimization-spec.md`
- 前置 Plan：`docs/analyzer/plans/2026-08-22-ultraview-stability-and-quality-hardening-plan.md`
- 执行目标：在 hardening 的功能和门禁基线稳定后，以兼容 façade 和 characterization tests 保护行为，依次拆解 View modules、Page、FreeGrid、Coordinator 和 Qt-free core。

## 0. 执行裁决、硬前置与并行边界

### 0.1 当前不得开始源码迁移

本计划写作时 hardening 已有 agent 执行。该 agent 正在修改 Page/Widgets/Chrome/author/tests 等本计划热点，
所以当前阶段只允许创建本 Plan/Spec，不允许并行实施 Wave 1–6。

开始架构实施前，执行者必须确认：

1. hardening agent 已完成或明确移交；
2. hardening Plan §9 全部关闭；
3. UltraView focused/boundary gate 在稳定 snapshot 上全绿；
4. 真实 Cocoa hardening 验收有明确 pass/fail，不能用“曾手测”代替；
5. 当前 checkout 没有另一进程正在修改相同 owner，也没有重叠 full pytest；
6. 当前 working tree 的用户改动已经按 owner 列表登记并保护；
7. 新建架构专用分支，建议 `codex/ultraview-post-hardening-architecture`；除非用户另有指示，不 push。

任一条件不满足，状态保持 `BLOCKED BY HARDENING COMPLETION`，不得以“先做纯移动”绕过。

### 0.2 不重复 Hardening 输出

Task 0 必须检查 hardening 最终实现：

- 若已有 `SelectionMutationService`，Workspace wave 直接接管/复用；
- 若已有 `FloatingChromePolicy`，Page wave 只迁移 owner 与 wiring；
- 若已有 capture coordinator/facts seam，不创建第二套同义类；
- 若 hardening 调整了 Page/Widgets/Coordinator 的 public surface，以下 inventory 以新 HEAD 重算；
- 若 hardening 未完成某项产品修复，先回 hardening Plan 关闭，不在架构 commit 中夹带修复。

### 0.3 顺序与依赖

```text
Task 0  hardening 完成门禁 + 重新锚定
  ↓
Task 1  冻结 public surface、import graph、行为和性能计数
  ↓
Wave 1  Chrome/Widgets class-family 机械拆包
  ↓
Wave 2  UltraViewPage controller extraction
  ↓
Wave 3  FreeGrid feedback/pointer/author owner extraction
  ↓
Wave 4  Coordinator → Workspace + Capture services
  ↓
Wave 5  Qt-free core/state 分层 + import cycle 消除
  ↓
Wave 6  私有协议清零、性能/生命周期/Cocoa/集成验收
```

Wave 2–5 不并行。它们修改同一 signal graph 和生命周期链，并行只会让 parity 证据失真。

## 1. Task 0 — Hardening 完成门禁与执行基线重锚

### 1.1 读取和核对

完整读取：

- hardening Review/Spec/Plan；
- hardening verification 或最终 agent handoff；
- 本 Spec/Plan；
- 当前 `AGENTS.md`、`CLAUDE.md` 中共享架构语义；
- `docs/lessons-learned/INDEX.md` 中与本次 wave 直接相关的 lessons；
- 当前 UltraView source、tests 和所有 compatibility consumers。

### 1.2 记录可复现基线

记录：

```bash
git rev-parse HEAD
git branch --show-current
git status --short --branch
rg -n '^APP_VERSION' mf4_analyzer/app_meta.py
```

并记录：

- macOS/CPU、Python、Qt、PyQt、pyqtgraph；
- UltraView relevant dirty diff hash；
- Page/Widgets/Coordinator/state 行数、class/method/signal/field writer 统计脚本和原始输出；
- `git log --since` 的相关 owner 变更热度；
- 运行中的 pytest 进程与 cwd；
- hardening focused result、Cocoa result 和未执行平台。

本文 `1df1714d...` 只作分析来源，不能复制成 execution baseline。

### 1.3 GO/NO-GO

GO 必须同时满足：

- hardening 关闭且没有活跃重叠 agent；
- current focused/boundary gate 正常结束且全绿；
- source snapshot 在测试前后没有变化；
- 预先存在的 dirty paths 已列明；
- 本计划要迁移的 public seam 已从当前 HEAD 提取。

否则记录 `BLOCKED BY HARDENING` 或 `UNVERIFIED SNAPSHOT` 并停止。

**Task 0 不修改产品代码，不创建提交。**

## 2. Task 1 — 先冻结架构与行为，再移动文件

### 2.1 Public surface inventory

新增一份机器可读 inventory（建议 `.state/ultraview-architecture/baseline.json`，不默认入 Git），包含：

- `widgets.py` / `chrome.py` / `ui.ultraview_state` 的 exported names；
- `UltraViewPage` signals/public methods/properties；
- `UltraViewCoordinator` 的 MainWindow/page public seam；
- tests/packaging/scripts 的 imports 和 monkeypatch targets；
- objectName/accessibility/QSS selectors；
- `_page_of`、private `getattr`、model writers、state mutators、signal connections；
- internal import graph 和强连通分量。

对需要长期守护的内容写入 `tests/ui/test_ultraview_structure.py` 或新的
`tests/ui/test_ultraview_compatibility.py`，不要把整个临时 JSON snapshot 固化进 Git。

### 2.2 Characterization tests

在任何迁移前补齐：

1. compatibility imports/type identity；
2. Page signal name/signature 与 coordinator connection count；
3. Page `show/hide/reset/Board switch/presentation` 的 controller lifecycle 顺序；
4. widget objectName、accessibleName、focus、mouse/key activation；
5. projection refresh count、Board switch count；
6. move/resize hold 的 planner/present/paint/reproject count；
7. Pointer routing hit priority、single emit、cancel；
8. capture stability/digest/overlay/cursor composition facts；
9. workspace reset/shutdown timer/hook/store ledger；
10. schema 1–5/future payload 和 project/sidecar round-trip。

Characterization 断言当前 hardening 后的正确产品语义，不冻结已知 bug。

### 2.3 边界 RED

为目标结构增加当前应失败的 guard，但不要一次要求所有 wave 同时通过。每条 guard 按对应 wave 激活：

- façade exports parity；
- view no MainWindow/coordinator import；
- Page no private child access；
- Coordinator no host private access；
- core no Qt/UI import；
- no internal import cycle；
- parent-chain capability surface shrink-only。

**Exit gate**：行为和 public seam 可机器比较；每个后续 wave 有精确 owner tests，不依赖人工“看起来没变”。

**建议提交**：`test(ultraview): freeze post-hardening architecture seams`

## 3. Wave 1 — Chrome/Widgets 机械拆包

本 Wave 只移动完整 class-family 和其私有 helper；不改算法、signal、QSS、geometry 或可见行为。

### Task 1.1：拆 `chrome.py`

建议目标：

- `tool_rail.py`：ToolRail、Pointer tile 与 rail-local helper；
- `chrome_islands.py`：Global/Board/Status/Navigation islands；
- `chrome_popovers.py`：Board/Layout/Card context popovers；
- `chrome_common.py`：只被以上多方共享的 presentation helper；
- `chrome.py`：兼容 re-export façade。

步骤：

1. 一次移动一个 class-family；
2. 原 `chrome.py` 立即 re-export；
3. consumer 暂不批量改 import，先证明旧路径工作；
4. 运行 class-family owner tests；
5. 检查 QSS selector/objectName/sizeHint/accessibility parity；
6. 每个 family 独立提交和回退。

### Task 1.2：拆 `widgets.py` 的低风险 families

先移动：

- `library_widgets.py`：Library/Tray/rows/sections；
- `card_widgets.py`：UltraViewCard、FreeGridCard 及 card-local presentation；
- `template_board.py`：BoardGrid/template-only projection；
- `board_aux_widgets.py`：Minimap/Overview/Focus/empty state。

暂不改变 `FreeGridBoard` 内部职责；可以最后整体移动到 `free_grid_board.py`，但不在本 Wave 抽 feedback
或 pointer state。

### Task 1.3：处理 helper 和 import cycles

- helper 只放到实际 owner；至少两个 family 共享且纯粹时才进入明确 common module；
- 禁止创建泛化 `utils.py` 垃圾抽屉；
- 禁止为绕过循环使用新的函数内 lazy import，发现循环就记录到 Wave 5；
- `widgets.py` 保持旧 import 和 monkeypatch seam。

### Wave 1 验证

聚焦：

- `tests/ui/test_ultraview_chrome.py`
- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_free_grid.py`
- `tests/ui/test_ultraview_structure.py`
- `tests/ui/test_import_boundaries.py`
- `tests/ui/test_no_lambda_signal_connections.py`
- `tests/ui_kit/test_qss_border_shorthand.py`

再运行 compatibility/import subprocess。由于本 Wave 是机械迁移，出现视觉或手势差异即回退当前 family，
不在同一提交顺手修行为。

**建议提交序列**：

1. `refactor(ultraview): split chrome class families behind facade`
2. `refactor(ultraview): split library and card widgets behind facade`
3. `refactor(ultraview): isolate template and auxiliary board widgets`
4. `refactor(ultraview): move free grid host behind widgets facade`

## 4. Wave 2 — `UltraViewPage` 收缩为 Composition Façade

### Task 2.1：提取纯 projection builder

目标模块：`page_projection.py`。

输入使用不可变 facts：Board snapshot、PreviewRecord/status/exists、Library rows、selection/presentation flags；
输出 CardViewModels、tray/template/free-grid projection 和显式 diff/fingerprint。

规则：

- 不接收 Page/QWidget/MainWindow；
- 不写 Board；
- 不持有 timer；
- 相同输入结果确定；
- Page 仍负责把 projection 应用到 widgets。

先跑 projection parity 与 refresh-count tests，再迁移一个 projection subtree。

### Task 2.2：提取 FloatingChromeController

若 hardening 已有 `FloatingChromePolicy`，本任务只增加 controller owner：

- 收集公开 `interaction_facts()`、`layout_hint()`、selection bounds、stage/safe rect；
- 调用 pure policy；
- 应用 geometry/visibility/stacking；
- 拥有最小必要的 fingerprint/coalescing；
- Page 不再读取 `_author_geometry_session`、`_body_layout`。

Minimap、selection toolbar、format picker 和 rail/panel 合同必须与 hardening 完全相同。

### Task 2.3：提取 ViewportController

迁移：

- BoardViewport/camera；
- zoom/pan/pinch/scroll mapping；
- edge-pan velocity 与 viewport-change notification；
- initial fit/Board switch settle；
- viewport persistence payload signal；
- hide/reset/cancel。

保留现有 `viewport_router.py` 和 hardening feedback seam；不重新实现坐标数学。

### Task 2.4：提取 Context/Author UI controllers

分别处理：

- board/card context menu 和 visible-action facts；
- ToolRail/popup/format-picker 的 UI 状态投影；
- author interaction controller 的信号桥接。

Author session mutable state仍由 `BoardInteractionController` 拥有；Page controller 只负责 UI bridge。

### Task 2.5：收口 Page wiring

- 将 156 处左右的 signal connections 按 owner 移入具名 `_connect_*` 或 controller `connect()`；
- 每个 controller 提供幂等 `connect/disconnect/reset/shutdown`；
- 禁止 `.connect(lambda)`；
- Page 保留 public signals/methods，委托到 owner；
- 删除旧实现前用 spy 证明一次输入只触发一次 action/projection。

### Wave 2 出口

- Page 无 Board mutator、MainWindow/coordinator 引用和 private child read；
- public API/signals/imports parity；
- Page lifecycle tests 和 foreground rail/panel/minimap/selection 行为不变；
- 没有第二份 camera/chrome/selection state。

**建议提交序列**：每个 Task 一个提交，不把四个 controller 合并成一个大 commit。

## 5. Wave 3 — FreeGrid、Feedback、Pointer 与 Author Owner 拆分

### Task 3.1：提取 `FreeGridFeedbackController`

先冻结 hardening 后的 feedback counters/frame facts，然后整体迁移：

- latest pointer；
- coalescer；
- candidate fingerprint；
- feedback frame/generation；
- viewport-change reprojection；
- surface present/clear；
- release/cancel/reset cleanup。

`FreeGridBoard` 提供公开 card/ghost source 和 coordinate facts；controller 不读取 host 私有字段。Page 只接收
gesture lifetime/viewport-change signals，不拥有 feedback timer。

RED/GREEN 必须覆盖 move 与 resize：0/100/500/2000 ms、collision、edge-pan、cover/uncover、release、Esc、
Board switch、project reset。

### Task 3.2：将 `BoardPointerMixin` 迁为 `PointerRouter`

1. 冻结当前 mouse/key/native/accessibility input matrix；
2. 定义 `PointerHitFacts` 与确定优先级；
3. Page 组合 router，不再通过多继承获得 pointer 行为；
4. Router 调用显式 card/author/viewport ports；
5. Mouse/Laser 只在 cursor provider 上不同；
6. 删除 mixin 前保留旧 API adapter，确保单 emit 和 cancel parity。

停止条件：若新 router 需要 full-screen transparent input widget、全局 event filter 扩到 Board 外，或复制现有
gesture state，停止并修设计。

### Task 3.3：提取 `FreeGridAuthorController`

迁移 author hit/geometry/editor bridge，但不拆 `BoardInteractionController` 的 session state：

- Card/author 共用坐标映射；
- selection bounds/capabilities 通过 facts；
- editor/IME 最高优先；
- connector/stroke/shape/text/sticky 行为 parity；
- lost targets、locked/unknown objects 和 history 语义不变。

### Task 3.4：收缩 `FreeGridBoard`

最终 FreeGridBoard 只负责：

- QWidget child ownership；
- card/author layer projection；
- local coordinate/hit facts；
- paint/event forwarding 到显式 controllers；
- view-local signal surface。

不得继续拥有第二份 history、pointer sample、feedback frame、edge timer 或 author session。

### Wave 3 验证

聚焦 owner tests：

- feedback pipeline/gesture preview/coalesce；
- board hit routing/card actions/free-grid；
- author tools/integration/geometry/selection/multiselect/slices；
- viewport/router；
- lifecycle/reset/project session；
- structure/import/no-lambda。

随后运行真实 Cocoa：click、move、resize、collision、edge-pan、Sticky/Text/Shape/Pen、Mouse/Laser、editor/IME。

## 6. Wave 4 — Coordinator 分成 Workspace 与 Capture Services

### Task 4.1：提取 WorkspaceController

若 hardening 已存在 mutation service，直接作为 WorkspaceController 的 collaborator。迁移一个 call graph：

- workspace/active Board；
- Board CRUD/reorder/select；
- placement/author/mixed mutation funnel；
- history/dirty/layout revision；
- auto-arrange/card fit intent orchestration；
- immutable projection snapshot 发布。

Coordinator façade 先委托旧 public methods；MainWindow connection 不一次性重写。

### Task 4.2：定义公开 `PresentationCaptureFacts`

在改 CaptureCoordinator 前，先为每种 chart host 增加显式事实 seam/adapter：

- visible/sized；
- real-result presence；
- quality settled；
- interaction/refresh idle；
- cursor/overlay composition；
- source revision/digest leaves。

为 Time/FFT/FFT-Time/Order/FRF 和 fake/unsupported host 写 owner tests。未知/可选能力必须有结构化降级和节流
warning；不允许把原私有 `getattr` 列表挪到新文件冒充解耦。

### Task 4.3：提取 CaptureCoordinator

整体迁移：

- PreviewStore；
- bindings/hooks；
- capture queue/timers；
- idle/focus recapture；
- digest/revision；
- presentation runtime ledger；
- sidecar load/save；
- reset/shutdown capture cleanup。

输入只接受 refs、workspace membership snapshot、capture facts 和明确 commands；不得调用 Board mutator。

### Task 4.4：收口兼容 Aggregator

`UltraViewCoordinator` 保留：

- MainWindow integration 入口；
- Page/workspace/capture service 的一次性 wiring；
- 旧 public method/property 的委托；
- 顶层 shutdown/reset 顺序。

不保留算法、私有 host 探测或第二份 workspace/store/timer。

### Wave 4 出口

- Workspace 与 Capture 互不读取对方私有字段；
- Coordinator 不直接组合 mutation 或 capture stability；
- Page public seam 不扩大；
- project/save-as/sidecar/fresh-stale/sync/export/reset/shutdown parity；
- MainWindow state ownership whitelist 不扩大。

## 7. Wave 5 — Qt-free Core 分层和 Import Cycle 消除

本 Wave 最后执行，因为 `ui.ultraview_state` fan-in 最高。每个步骤保留 re-export，不批量重写所有 consumers。

### Task 5.1：先拆 `grid_geometry`

- 将 `GridMetrics`、rect↔pixel、overlap/containment 等中立 primitives 移到 Qt-free owner；
- `free_grid.py` 和 `card_fit.py` 单向依赖它；
- 删除 `free_grid.py` 内对 `card_fit` 的函数级 lazy import 或重定向兼容 wrapper；
- 用 Card Fit、viewport exact-map、collision/avoidance parity 证明没有算法变化。

### Task 5.2：拆 model

移动 identity、Board/Workspace、author DTO 和稳定 constants；保持 dataclass fields、frozen/order/equality/hash、
repr/payload semantics。`ui.ultraview_state` 立即 re-export。

### Task 5.3：拆 operations

依次移动：

- Board/workspace CRUD 与 layout/placement operations；
- author operations/reconcile；
- selection mutation pure planning；
- presentation/filter/digest facts。

一个 operation family 一个提交；不在移动时重写算法。

### Task 5.4：拆 serialization

最后移动 schema legalize/migration、future passthrough、payload codec。必须运行：

- schema 1–5 round-trip；
- future opaque untouched save；
- explicit mutation exits passthrough；
- deep-copy isolation；
- hostile/invalid payload warning taxonomy；
- project save/open/Save As/sidecar descriptor。

### Task 5.5：逐步迁移 imports

- 新代码使用 `ultraview_core`；
- 旧 consumer 可继续用 `ui.ultraview_state`；
- packaging/tests/scripts/import subprocess 一起更新；
- façade 清理只删除无用内部 import，不删除支持的 alias。

### Wave 5 出口

- core subprocess import 不加载 Qt/UI；
- internal import graph 无循环；
- public identity/schema/payload parity；
- no duplicated calculation；
- `ui.ultraview_state` 只剩兼容 re-export/必要文档。

## 8. Wave 6 — 协议清零、性能、生命周期与集成验收

### Task 6.1：清除遗留隐式协议

逐项证明归零或最小化：

- Page/Coordinator 的 required private `getattr`；
- widget parent-chain Page 能力发现；
- duplicate signal wiring；
- duplicated timers/latest-pointer/frame/camera state；
- compatibility façade 中的业务实现；
- internal import cycles；
- obsolete lazy imports 和 dead adapters。

不得为了指标归零删除有用错误日志或兼容 seam。

### Task 6.2：结构与边界 gate

至少执行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_structure.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

根据最终模块补 core no-GUI、compatibility exports、cycle 和 capture-facts tests。任何 frozen whitelist 扩大都
必须先修 Spec，默认判定为架构回退。

### Task 6.3：UltraView focused owner gate

在 source snapshot 稳定后运行一次完整 UltraView focused gate。运行前后记录：

- HEAD；
- relevant dirty paths/hash；
- Python/Qt/PyQt/pyqtgraph；
- pytest process/cwd；
- exit code/pass/fail/skip/warnings/duration。

运行期间相关文件变化则结果为 `UNVERIFIED`，不得作为验收。

### Task 6.4：性能与生命周期

对比 Task 1 baseline：

- Board switch/full projection 次数；
- signal connection 数与重复 emit；
- move/resize planner/present/paint/reproject；
- capture queue/digest/idle timer；
- 12/24 cards 与 20 Boards/60 refs 的 switch p50/p95、RSS/PreviewStore residency；
- reset/shutdown/hide/reopen 的 live timer/hook/grab/cursor/surface。

出现未解释退化就定位到最小 wave 并回退，不通过扩大阈值收绿。

### Task 6.5：真实 Cocoa 验收

使用项目真实入口与 `testdoc/222.tlproj`，至少覆盖：

1. 800×560、1280×720、1440×900；
2. Board CRUD/switch/template/free-grid；
3. Library drag/drop、card click/context/focus/sync/export；
4. move/resize/collision/edge-pan 的 0/100/500/2000 ms hold；
5. Pointer popup mouse/key/AXPress，Mouse/Laser parity；
6. Sticky/Text/Shape/Pen、selection toolbar、format picker、editor/IME；
7. minimap/overview/presentation；
8. project save/reopen/reset/shutdown/tool-window reopen；
9. chart preview 无白屏、feedback 无双闪、主 Analyzer 不被工具窗点击抢前台。

### Task 6.6：Full gate 条件

只有准备 merge/release 或本次跨边界重构需要 integration acceptance 时执行一次：

1. 主 suite 新进程运行，`--ignore=tests/acquisition_ui`；
2. 主 suite 完成后再单独运行 `tests/acquisition_ui`；
3. 两进程不得并发；
4. abnormal exit/crash/timeout/source drift 均为 `UNVERIFIED`；
5. fresh Windows Full/Lite frozen 与 Cocoa/source/offscreen 独立报告。

## 9. 每个 Task 的标准执行模板

每个非纯文档 Task 都必须按以下顺序：

1. 记录 owner、文件、public seam、current call graph；
2. 写或确认能够失败的 boundary/characterization test；
3. 只迁移一个 owner；
4. 运行 owner tests；
5. 运行适用 boundary gates；
6. `git diff --check`；
7. 检查没有用户无关 dirty files 被 stage；
8. UI owner 变化时跑对应真实 foreground gesture；
9. 提交一个可独立回退的 scope；
10. 记录下一 Task 的新 HEAD 和 remaining private/parent-chain surface。

机械文件移动与行为修复不能放在同一提交。若迁移暴露产品 bug，先回退或单独建立 bug task/test，再继续。

## 10. 停止条件与回退策略

出现以下任一情况立即停止当前 Wave：

- hardening 行为或 focused gate 回归；
- 需要修改 project schema/sidecar format/public identity；
- 需要扩大 structure/MainWindow ownership/no-lambda whitelist；
- 出现第二份 mutable state、timer、history、capture store 或 feedback frame；
- 需要 broad exception/silent fallback；
- 机械迁移导致 QSS/objectName/accessibility/foreground 变化；
- 测试运行中 source snapshot 变化；
- 另一 agent 开始修改同一 owner；
- Cocoa 反馈/命中/工具窗前台行为不能由当前 tests 解释。

回退当前最小 owner commit，保留已通过的前置 waves；不要用跨 wave 临时 adapter 堆叠掩盖问题。

## 11. 文档、证据和提交纪律

- 更新本 Plan/Spec 的状态时记录真实 HEAD 和验证结果，不覆盖历史基线文字。
- 临时 inventory、AST 输出、benchmark、原始截图/录屏放 `.state/ultraview-architecture/`。
- 只有需要长期保留的代表性 evidence 入 `docs/analyzer/verify/`，并附平台、HEAD、命令和结论。
- 每个 commit 只 stage 本 Task-owned files；保留用户其他 dirty/untracked files。
- 不把大量 PNG/JPEG、产品行为、机械移动和文档状态更新混在同一 commit。
- 不 push，除非用户明确要求。

## 12. 完成检查表

- [ ] hardening 已完成并有稳定 current evidence
- [ ] execution baseline 重新锚定，不使用本文 dirty 分析快照冒充验收
- [ ] public imports/signals/objectName/QSS/accessibility/monkeypatch seams 已冻结
- [ ] `chrome.py` / `widgets.py` 成为兼容 façade，class families 已独立
- [ ] `UltraViewPage` 只做 composition/public QWidget lifecycle
- [ ] projection/viewport/floating chrome/context/author UI 各有一个 owner
- [ ] FreeGrid feedback 的 latest pointer/frame/timer/reprojection 只有一个 owner
- [ ] `BoardPointerMixin` 已由显式 PointerRouter 取代，命中优先级和 Mouse/Laser parity 保持
- [ ] author interaction 仍只有一个 session owner
- [ ] Workspace 与 Capture services 已分离
- [ ] capture 通过 typed public facts，不探测 chart host 私有字段
- [ ] `ultraview_core` Qt-free，schema/identity/deep-copy/future payload 保持
- [ ] `free_grid ↔ card_fit` 循环已消除
- [ ] Page/Coordinator/widget parent-chain/private required protocols 已清零或经 Spec 明示
- [ ] structure/import/MainWindow ownership/no-lambda/QSS gate 全绿且 whitelist 未扩大
- [ ] projection/feedback/capture/performance/lifecycle 无未解释退化
- [ ] UltraView focused gate 在稳定 source snapshot 上全绿
- [ ] Cocoa gesture/UI 矩阵通过
- [ ] full suite/Windows frozen 未执行时明确标记 `UNVERIFIED`
- [ ] 每个 wave 有独立提交、验证和回退点，无临时双实现残留

完成前状态保持 **PARTIAL / IN PROGRESS**，不得仅因大文件行数下降就宣称架构稳定。

---

## Addendum — 2026-08-23 follow-up execution (do not rewrite history above)

This document keeps its original `PROPOSED / BLOCKED BY HARDENING COMPLETION` proposal text. Execution after the local architecture merge lives in:

`docs/analyzer/plans/2026-08-22-ultraview-architecture-and-quality-followup-plan.md`

Four states that must not be collapsed:

| State | Meaning | 2026-08-23 |
|---|---|---|
| Local merge | Architecture split landed on local `main` | Yes (`2feddfa17e2494d2551b6dd755aa5240e64c36da` plus follow-up working tree) |
| Remote publish | `origin/main` contains the work | No; local `main` was already ahead 36, no push without explicit authorization |
| Offscreen green | Focused/boundary/full automated gates on a stable snapshot | Functional follow-up and owner-state seam implemented; compatibility method façade remains partial; see the follow-up Plan for candidate gate results |
| Cocoa acceptance | Real macOS foreground gesture/pixel/lifecycle matrix | `UNVERIFIED` on this candidate |
| Windows frozen | Full/Lite frozen executables | `UNVERIFIED` |

The historical checklist above is not retroactively ticked. Use the follow-up Plan §5 as the current remaining-work source of truth.
