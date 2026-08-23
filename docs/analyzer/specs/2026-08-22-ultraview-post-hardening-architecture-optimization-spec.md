# UltraView Hardening 后续架构优化 Spec

- 日期：2026-08-22
- 状态：**PROPOSED / BLOCKED BY HARDENING COMPLETION**
- 配套 Plan：`docs/analyzer/plans/2026-08-22-ultraview-post-hardening-architecture-optimization-plan.md`
- 前置 Hardening Spec：`docs/analyzer/specs/2026-08-22-ultraview-stability-and-quality-hardening-spec.md`
- 前置 Hardening Plan：`docs/analyzer/plans/2026-08-22-ultraview-stability-and-quality-hardening-plan.md`
- 来源 Review：`docs/analyzer/reviews/2026-08-22-ultraview-current-state-comprehensive-review.md`
- 目标：在 hardening 已经恢复功能与门禁可信度之后，按明确 owner 拆解 UltraView 的高耦合热点，降低后续变更放大、隐式协议和生命周期回归风险，同时保持现有产品行为、项目格式和公开导入兼容。

## 0. 与正在执行的 Hardening 的关系

本 Spec 是 **hardening 之后** 的独立架构阶段，不是 hardening 的替代方案，也不与正在执行的 agent
争抢同一批源文件。

在以下条件全部满足前，本 Spec 保持 `BLOCKED BY HARDENING COMPLETION`：

1. hardening Plan §9 完成检查表已经按当前源码逐项关闭；
2. mixed selection、minimap、Pointer Accessibility、compact rail、feedback、Laser DPR 的产品合同已经稳定；
3. hardening 中历史六个红测试已经逐项关闭或用正确合同替换；
4. `tests/ui/test_ultraview_structure.py` 的 frozen set 没有通过扩大白名单收绿；
5. hardening agent 已停止修改本 Spec 涉及的 owner，且存在一个稳定、可记录的 source snapshot；
6. 若 hardening 已经提取 `SelectionMutationService`、`FloatingChromePolicy` 或 capture seam，架构阶段直接复用，不创建同义第二实现。

本 Spec 不修改 hardening 文档的历史状态。开始实施时必须新建 execution baseline，不得继续使用本文的
分析快照作为通过证据。

## 1. 分析基线与证据边界

### 1.1 当前分析快照

- Git：`main@1df1714d2392a91c658abe0f0e9035cf8d59b024`，相对 `origin/main` ahead 2；
- 产品版本：`mf4_analyzer/app_meta.py:APP_VERSION = "v8.0.1"`；
- 运行时：Python 3.12.14、Qt 5.15.14、PyQt 5.15.11、pyqtgraph 0.14.0；
- 平台：macOS 27.0 arm64；
- 相关 dirty diff SHA-256：`f1f6f7813cc3b0cfff48bd32c042312c332de4e12920fddfa750a828e8a568d9`；
- 该 dirty worktree 包含正在执行的 Pointer/Laser/hardening 相关工作，因此本文数字是架构分析输入，
  **不是未来实施基线**。

### 1.2 当前热点实测

| Owner | 当前行数 | 当前形态 | 架构判断 |
|---|---:|---|---|
| `chart_stack/ultraview/widgets.py` | 6322 | 24 个类；Library、Card、Template、FreeGrid、Minimap、Overview 混装 | 必须拆模块；FreeGrid 需进一步拆 owner |
| `chart_stack/ultraview/page.py` | 4959 | `UltraViewPage` 约 326 方法、42 个 signals、约 425 行构造 | 必须从行为中心收缩为 composition façade |
| `main_window/ultraview_coordinator.py` | 3876 | workspace mutation/history 与 capture/digest/sidecar 混合 | 必须拆服务，保留兼容 aggregator |
| `ui/ultraview_state.py` | 2894 | model、Board ops、author codec/ops、serialization/presentation 混合 | 应拆，但高 fan-in，必须后置并保留 façade |
| `chart_stack/ultraview/chrome.py` | 2788 | rail、islands、popover、navigation、context 混装 | 适合先做低风险 class-family 机械拆包 |
| `chart_stack/ultraview/author_chrome.py` | 1941 | 多类 author UI | 可按 flyout/selection/editor chrome 后置拆分 |
| `chart_stack/ultraview/author_tools.py` | 1508 | `BoardInteractionController` 统一持有 tool/draft/selection session | 暂保单 owner，只抽纯计算和显式 facts |
| `chart_stack/ultraview/board_pointer.py` | 1507 | 一个 mixin 承担多工具 pointer routing | 高风险；先冻结路由优先级，再迁到 controller |

行数只用于定位热点，不是完成标准。真正的拆分依据是状态生命周期、变更原因和依赖方向。

### 1.3 已确认的具体耦合

1. `UltraViewPage` 读取 FreeGrid/toolbar 私有字段，存在静默协议：
   `_author_geometry_session`、`_body_layout`。
2. `UltraViewCoordinator` 通过 `_cursor`、`_dense_raster`、`_interaction_state`、
   `_refresh_pending`、`_aa_idle_timer` 等私有字段判断 capture 稳定性。
3. widget 仍存在 parent-chain `_page_of()` / `getattr(parentWidget(), ...)` 能力发现。
4. `free_grid.py` 与 `card_fit.py` 通过 lazy import 构成双向依赖。
5. Page 构造和 signal wiring 过于集中，任何 chrome/author/viewport 变化都会扩大 review 与 teardown
   风险。
6. `ultraview_state.py` 当前 Qt-free 且是高 fan-in 稳定边界；过早拆分会制造全仓 import churn。

## 2. 目标与非目标

### 2.1 目标

1. 让 `UltraViewPage` 只负责 QWidget 生命周期、公开 signals/API、子 owner 组合与转发。
2. 让 FreeGrid 的 card host、pointer routing、feedback、author geometry 各有清晰且唯一的状态 owner。
3. 将 workspace/history 与 capture/digest/sidecar 从 `UltraViewCoordinator` 分离。
4. 用显式小 protocol / immutable facts 替代跨 owner 私有字段和 parent-chain 能力发现。
5. 将 Qt-free domain core 分成 model、operations、serialization、presentation/geometry，同时保留旧导入。
6. 消除 `free_grid ↔ card_fit` 循环和新增的内部循环。
7. 让每个迁移波可以独立测试、提交、回退，不依赖最终“大整理”才能运行。
8. 保持现有 foreground UI、项目 round-trip、capture/sidecar、undo/redo 和工具窗行为不变。

### 2.2 非目标

- 不新增或删除产品功能、作者工具、shape 类型、格式项或 Board 菜单动作。
- 不改变用户已确认的 rail、compact、左上角、蓝色选中态和无 dark mode 方向。
- 不改变 UltraView project schema、sidecar format 或 `UltraViewRef(section, view_id)` 身份。
- 不借重构调整几何常量、视觉 token、交互延迟、碰撞策略或 Card Fit 算法。
- 不重写 UltraView，不引入第二套状态树、事件总线、依赖注入框架或全屏透明 interaction overlay。
- 不以“目标行数”为由拆分内聚的 session owner。
- 不在 compatibility façade 中继续添加新行为。
- 不在每个 wave 运行 full suite；只在稳定 integration milestone 执行一次合规 full gate。

## 3. 目标架构与依赖方向

### 3.1 目标层次

```text
mf4_analyzer/ultraview_core/                 Qt-free domain core
├── model.py                                 identity / Board / Workspace / author DTO
├── board_ops.py                             Board/workspace pure operations and validation
├── author_ops.py                            author serialization/mutation/reconcile
├── serialization.py                         schema legalize/round-trip/future passthrough
├── presentation.py                          digest/filter/presentation facts
└── grid_geometry.py                         GridMetrics/rect transforms/overlap primitives

mf4_analyzer/ui/chart_stack/ultraview/       View and page controllers
├── page.py                                  public QWidget composition façade
├── page_projection.py                       CardViewModel/library/status projection
├── viewport_controller.py                   camera/zoom/pan/edge-pan/settlement
├── floating_chrome_controller.py            rail/panel/minimap/toolbar facts and placement
├── board_context_controller.py              board/card context and visible actions
├── pointer_router.py                        pointer event priority and dispatch
├── free_grid_board.py                       FreeGrid QWidget host and child ownership
├── free_grid_feedback_controller.py         latest pointer/frame/coalescer/reprojection
├── free_grid_author_controller.py           author hit/geometry/editor session bridge
├── library_widgets.py                       library/tray presentation
├── card_widgets.py                          UltraViewCard/FreeGridCard presentation
├── template_board.py                        template BoardGrid presentation
├── board_aux_widgets.py                     minimap/overview/focus auxiliary widgets
├── tool_rail.py                              ToolRail and pointer tile
├── chrome_islands.py                        global/board/status/navigation islands
├── chrome_popovers.py                       Board/Layout/Card context popovers
├── widgets.py                               compatibility re-export façade
└── chrome.py                                compatibility re-export façade

mf4_analyzer/ui/main_window/                  Product orchestration services
├── ultraview_workspace_controller.py        workspace intents/history/dirty/Board lifecycle
├── ultraview_capture_coordinator.py          PreviewStore/capture/digest/timers/sidecar
├── ultraview_capture_facts.py                typed public chart-host capture facts/adapters
└── ultraview_coordinator.py                  compatibility aggregator and MainWindow seam

mf4_analyzer/ui/ultraview_state.py            compatibility re-export façade
```

文件名可在 Task 0 根据 hardening 最终树做小幅调整，但 owner 和依赖方向不得被合并回大文件。

### 3.2 允许的依赖方向

```text
ultraview_core
    ↑
view widgets / pure layout helpers
    ↑
page and board controllers
    ↑
UltraViewPage composition façade
    ↑
workspace/capture coordinators
    ↑
MainWindow integration
```

附加规则：

- `ultraview_core` 不 import `mf4_analyzer.ui`、Qt、MainWindow 或 renderer；
- view widgets 不 import MainWindow/coordinator，也不反向查找它们；
- controllers 可以持有显式 View port，但不得通过 `getattr(..., "_private")` 探测能力；
- workspace controller 不 import capture internals；capture coordinator 不调用 Board mutator；
- compositor/capture 接收 immutable snapshot/facts，不接收 live MainWindow 或 `UltraViewPage`；
- compatibility façade 只允许 re-export、类型别名和必要的 deprecation 注释，不成为新实现 owner。

## 4. 架构合同

### UV-ARCH-01：Hardening 输出是不可回退前置

1. mixed selection 的单事务语义、Pointer/Laser 语义、minimap 避让、feedback 单 surface/latest sample、
   compact rail 和 schema/micro-grid 合同必须保持。
2. 架构迁移不得恢复旧测试期望、扩大 structure whitelist 或绕过 hardening service。
3. hardening 已提供的 service/policy 必须被复用；若其边界不满足本 Spec，先写差异 review，再扩展同一
   owner，不新建平行实现。

### UV-ARCH-02：公开兼容 façade 保持稳定

1. Task 0 冻结 `widgets.py`、`chrome.py`、`ui.ultraview_state` 和 `ultraview_coordinator` 当前支持的
   imports、classes、constants、signals、public methods 与 monkeypatch seams。
2. 迁移后旧 import path 继续工作；类型 identity 在调用方依赖时保持一致。
3. façade 不复制实现、不创建第二份 mutable state、不吞 import/programming errors。
4. 删除兼容 alias 必须另立 migration spec，不属于本计划。

### UV-ARCH-03：Page 是 composition root，不是第二个状态 owner

1. `UltraViewPage` 保留 QWidget 生命周期、公开 signal/API 和 owner wiring。
2. Board/workspace mutation、history、capture、digest、sidecar 不进入 Page。
3. projection、viewport、floating chrome、context、author UI 的 mutable state 各有一个 controller owner。
4. Page 不读取 child 私有属性；child 通过显式 facts、signal 或 public method 报告状态。
5. Page 不新增 `getattr(..., default)` 形式的必需状态 guard。
6. Page reset/hide/show/close 对每个 controller 调用显式且幂等的生命周期方法。

### UV-ARCH-04：View widget 只拥有呈现和局部 Qt 生命周期

1. `UltraViewCard`、Library、Template Board、Minimap、Popover 等 widget 只维护呈现所需状态。
2. widget 不写 Board/Workspace，不创建 history，不决定 dirty。
3. widget 不通过 parent chain 发现 Page 能力；新能力通过构造注入的小 callback bundle、signal 或 protocol。
4. class-family 迁移不改变 objectName、accessibleName、signal signature、focus policy、mouse acceptance、
   z-order 或 QSS selector。
5. `widgets.py` / `chrome.py` façade 不拥有 parentless timer、QPixmap cache 或 native handle。

### UV-ARCH-05：FreeGrid feedback 只有一个生命周期 owner

`FreeGridFeedbackController` 必须统一拥有或显式协调：

- gesture id/lifetime；
- latest pointer sample；
- 0 ms coalescer 与 edge-pan reprojection request；
- candidate fingerprint；
- immutable feedback frame/generation；
- viewport-sized surface present/clear；
- mouse grab 与 release/cancel/reset cleanup。

相同 candidate 不重新 plan/present；只有真实 viewport transform 变化才 reproject。Card host、PointerRouter
或 Page 不得各自维护第二份 latest-pointer/timer/frame 状态。

### UV-ARCH-06：Pointer routing 有确定优先级和单一入口

1. 优先级固定为 active editor/IME → resize/geometry handle → active creation tool → selection/card hit →
   viewport pan/zoom → empty canvas。
2. Mouse 与 Laser 共用完全相同的 dispatch，只允许 cursor appearance 不同。
3. PointerRouter 接受结构化 hit facts，不依赖 widget 私有字段或透明全屏 overlay。
4. press/move/release/cancel 必须由同一 session owner 配对；WindowDeactivate、hide、Board switch、reset
   均能取消。
5. 迁移前后每种输入只能触发一次 action/signal/history。

### UV-ARCH-07：Author interaction 保持一个 session owner

1. `BoardInteractionController` 的 active tool、draft、selection、clipboard 和 format defaults 不因拆文件
   被分散到多个可写 owner。
2. 可提取 pure reducer、capability、format DTO 和 geometry facts；session mutation 仍从单入口执行。
3. author objects 与 Cards 继续共享 Board 坐标链、selection/history owner 和 compositor crop。
4. text/sticky editor、IME、locked/unknown object、connector endpoint 语义保持。

### UV-ARCH-08：Workspace 与 Capture 分离

`UltraViewWorkspaceController` 负责：

- workspace/active Board；
- typed intents 和 mutation funnel；
- placement/author history；
- dirty/layout revision；
- Board create/duplicate/rename/delete/reorder/select；
- projection snapshot 发布。

`UltraViewCaptureCoordinator` 负责：

- PreviewStore residency；
- source binding/hooks；
- stability/digest/capture queue；
- idle/focus capture timers；
- preview sidecar load/save；
- presentation runtime ledger；
- shutdown/reset 的 capture 资源清理。

两者只通过 typed snapshot/events 协作。Capture 不调用 Board mutator；Workspace 不读取 QImage、renderer
或 chart host 私有对象。

### UV-ARCH-09：Chart capture 使用显式 facts seam

1. chart host 或其 adapter 提供 `PresentationCaptureFacts`（名称可调整），至少表达：
   visibility/size、result presence、quality state、interaction/refresh state、cursor/overlay composition facts、
   source revision。
2. Coordinator 不再探测 `_cursor`、`_dense_raster`、`_interaction_state`、`_refresh_pending`、
   `_aa_idle_timer` 等私有字段。
3. 可选能力缺失必须按识别出的 host/section 显式降级并节流记录；编程错误和无关 `ImportError` 传播。
4. capture facts 是瞬态快照，不进入项目、preset 或 Board state。
5. 新 analysis canvas 接入时只新增 adapter/公开实现，不修改 Coordinator 的私有字段清单。

### UV-ARCH-10：Qt-free Core 后置迁移且保持 schema/identity

1. `UltraViewRef(section, view_id)`、Board/Workspace/author DTO 的语义和 equality/hash 不变。
2. Board 仍只拥有 refs/layout/author/presentation intent；像素仍由 workspace-level PreviewStore 共享。
3. schema 1–5 migration、future opaque passthrough、deep-copy isolation 和 sidecar descriptor 保持字节/语义
   等价。
4. 先移动 pure implementation，再让 `ui.ultraview_state` re-export；不一次性改完所有 consumers。
5. `grid_geometry` 成为 `free_grid` 与 `card_fit` 的共同中立依赖，消除双向 import。
6. core import subprocess 不得加载 PyQt、pyqtgraph、MainWindow 或 compositor。

### UV-ARCH-11：Mutable state 与生命周期可审计

1. 每个新增 mutable field 在 owner 构造中显式初始化。
2. transient state 在 clear/reset/Board switch/hide/shutdown 中按产品语义对称处理。
3. timer、signal、mouse grab、native cursor、cached Qt wrapper 在 owner 消失前停止或断开。
4. cached QObject/QWidget wrapper 通过 `destroyed` 清理，并在复用前检查存活。
5. 不增加 broad `except Exception: pass`；recoverable fallback 通过日志、warning/result 或 UI 可观察。

### UV-ARCH-12：性能不能因“更多对象层”退化

1. Board switch、projection refresh、pointer move、feedback present、idle capture 的关键计数在迁移前后保持
   或下降。
2. 不因 controller 拆分增加第二次 full projection、重复 signal connection、重复 timer 或重复 pixmap scale。
3. stationary pointer 500/2000 ms 仍保持 hardening 的 zero-extra-plan/present 合同。
4. 12/24 cards、20 Boards/60 refs 的内存 residency 与 switch p50/p95 不得出现未解释退化。
5. 性能判断使用计数和重复测量，不使用单次 offscreen wall-time 作为 Cocoa 流畅度证明。

### UV-ARCH-13：结构测试是 shrink-only ratchet

至少覆盖：

- core no-Qt/no-UI import；
- view no state mutator/MainWindow/coordinator import；
- coordinator 不访问 Page/host 私有面；
- compatibility exports parity；
- no internal import cycles；
- model writes only in core owner；
- mutation ends in one funnel；
- `page_of` surface 继续缩小到零或已注释的最小集合；
- no new MainWindow state writes；
- no new `.connect(lambda`；
- floating geometry 仍由单一 owner 提供。

现有 whitelist 只能缩小。发现现有 AST false positive 时用 neutral DTO/更准确 guard 修复，不通过加入新业务
方法名放行。

### UV-ARCH-14：每个 Wave 独立可回退

1. class/file 机械迁移与行为调整分开提交。
2. 一个提交只迁移一个 owner/call graph，并带对应 characterization/parity tests。
3. 旧 façade 在 consumer 全部迁移前保留。
4. 任一提交回退后仓库仍可 import、启动和运行上一波 tests。
5. 原始 Cocoa 截图/录屏默认放 `.state/`；durable evidence 经筛选并带结论后单独入库。

## 5. 状态、持久化和用户行为不变量

- `UltraViewRef` 继续是唯一 source/View 身份；显示名不成为 key。
- PreviewStore 继续跨 Boards 共享同一 ref 的像素，不按 membership 复制 QImage。
- Board schema、future payload、sidecar generation/hash/security、Save As 语义不变。
- selection、Pointer/Laser、cursor、feedback frame、timer、minimap placement 和 transient flyout 不持久化。
- duplicate Board 对 author objects/future payload 深拷贝，不共享嵌套 mutable payload。
- move/resize/collision/author geometry 的 preview 与最终 commit 使用相同坐标和 plan facts。
- undo/redo 每个用户 intent 仍是一条 history，不因 service 边界拆分为多条。
- UltraView 仍为独立非模态工具窗；不得恢复 MainWindow transient parent 或 Return 默认关闭行为。
- 打开/切换/导出 UltraView 不触发分析计算、隐藏 View 重算或项目恢复 job。

## 6. 验收矩阵

| ID | 架构场景 | 自动化验收 | 前台/运行验收 |
|---|---|---|---|
| UV-ARCH-A01 | compatibility imports | 旧路径/类型 identity/public exports parity | 不需要视觉替代 |
| UV-ARCH-A02 | Page composition | 无私有 child 访问、无 state mutator、signals parity | 全入口和弹层行为不变 |
| UV-ARCH-A03 | widget class-family 迁移 | objectName/signal/focus/QSS contract parity | 800×560/1280×720 无视觉漂移 |
| UV-ARCH-A04 | PointerRouter 迁移 | hit priority、单 emit、cancel、Mouse/Laser parity | card/author/empty/pan 路由正确 |
| UV-ARCH-A05 | feedback owner 迁移 | hold/reproject/release counters 与 frame parity | 蓝/amber frame 全程可见、无白屏 |
| UV-ARCH-A06 | author session 边界 | draft/selection/editor/connector/locked parity | Sticky/Text/Shape/Pen 操作不变 |
| UV-ARCH-A07 | workspace service | mutation/history/dirty/projection 单漏斗 | Board CRUD、undo/redo 无变化 |
| UV-ARCH-A08 | capture service | digest/stability/timer/sidecar/reset parity | fresh/stale/sync/export 无变化 |
| UV-ARCH-A09 | capture facts seam | fake hosts + real canvas adapters；无私有探测 | cursor/overlay 抓图内容一致 |
| UV-ARCH-A10 | core split | schema 1–5/future/deep-copy/identity/import boundary | save/reopen 同项目一致 |
| UV-ARCH-A11 | grid cycle removal | import graph无环，Card Fit/geometry parity | add/drag/resize/fit 结果一致 |
| UV-ARCH-A12 | lifecycle | reset/shutdown/hide/reopen 无 timer/hook/grab 泄漏 | 工具窗重开无残留、主窗不抢前台 |
| UV-ARCH-A13 | performance | projection/planner/present/capture 计数不增；benchmark 无未解释退化 | 12/24 cards foreground 手势无退化 |
| UV-ARCH-A14 | integration | focused/boundary gate stable snapshot 全绿 | Cocoa gesture matrix 通过 |

## 7. 完成定义

只有以下条件全部满足，本架构优化才可标记 `IMPLEMENTED`：

1. hardening 已有独立完成证据，本阶段没有修改或伪造其历史状态；
2. `UltraViewPage`、FreeGrid feedback、Pointer routing、workspace、capture、core 各有一个可指认 owner；
3. `widgets.py`、`chrome.py`、`ui.ultraview_state.py`、`ultraview_coordinator.py` 的兼容 façade 不包含新业务实现；
4. Page/Coordinator/widget 间的必需私有字段和 parent-chain 能力发现归零；若保留例外，必须在 Spec 修订中逐条说明并有失败可观察性；
5. `free_grid ↔ card_fit` 循环消失，core import 不加载 GUI；
6. mutation、capture、feedback、projection 和 lifecycle 的 owner tests/parity tests 全绿；
7. structure/import/MainWindow ownership/no-lambda/QSS boundary gate 全绿且 whitelist 未扩大；
8. 稳定 source snapshot 上完成 UltraView focused gate，运行前后 HEAD/dirty fingerprint 一致；
9. Page/FreeGrid/Pointer/Chrome 迁移后完成真实 Cocoa gesture/UI 矩阵；
10. merge/release 需要时按项目规则只执行一次 full suite，并顺序独立运行 `tests/acquisition_ui`；
11. Windows frozen 未执行时明确标记 `UNVERIFIED`，不得由 source/offscreen/Cocoa 代替；
12. 每个 wave 都存在独立提交和可验证回退点，没有依赖最终清理才能运行的临时双实现。

---

## Addendum — 2026-08-23 follow-up execution (do not rewrite history above)

This Spec keeps its original `PROPOSED / BLOCKED BY HARDENING COMPLETION` proposal semantics. It is not re-labeled `IMPLEMENTED`.

Current execution source of truth:

`docs/analyzer/plans/2026-08-22-ultraview-architecture-and-quality-followup-plan.md`

Status classes (must stay distinct):

- **Local merge**: architecture owners already landed locally; functional follow-up and owner-state containment are complete, while the compatibility method façade remains a shrink-only partial seam.
- **Remote publish**: not implied by local merge; requires an explicit push authorization.
- **Offscreen green**: automated Qt-offscreen evidence only.
- **Cocoa acceptance**: real macOS foreground matrix; remains `UNVERIFIED` until recorded against the same candidate snapshot.
- **Windows frozen**: remains `UNVERIFIED` until a frozen Full/Lite run exists.
