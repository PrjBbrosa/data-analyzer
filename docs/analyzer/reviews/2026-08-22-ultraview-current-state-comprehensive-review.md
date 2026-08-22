# UltraView 当前代码、UI 与架构综合 Review

- 日期：2026-08-22
- 审查结论：**PARTIAL / NEEDS REVISION**
- 集成裁决：当前功能可继续演进，但当前工作树 **NO-GO 作为稳定发布或架构收口基线**
- 配套 Spec：`docs/analyzer/specs/2026-08-22-ultraview-stability-and-quality-hardening-spec.md`
- 配套 Plan：`docs/analyzer/plans/2026-08-22-ultraview-stability-and-quality-hardening-plan.md`

## 1. 审查范围与证据边界

本次不是只看最后两个 commit，而是覆盖最近几天 UltraView 的主链：

- 提交范围：`36f42b36..1df1714d`，包括 2× micro-grid、作者工具、卡片拖放/缩放反馈、
  Miro 式 rail/flyout/selection chrome、viewport feedback surface，以及蓝色选中态。
- 当前分支：`main`，`HEAD=1df1714d2392a91c658abe0f0e9035cf8d59b024`，相对
  `origin/main` ahead 2。
- 已提交 UltraView/测试范围：64 files，约 `+28010/-818`。
- 当前未提交且与本次相关的范围：11 files，约 `+506/-324`；主要是 Pointer/Laser、图标、弹层、
  hint/quickref 和对应测试。本 review 将它们视为“当前产品状态”，但不把它们误写成已提交事实。
- 未跟踪的 `ssh-keygen` / `ssh-keygen.pub` 与本 review 无关，未读取、未改动。

证据分为四类，互不替代：

1. 源码和 Git 证据；
2. offscreen Qt 聚焦测试与视觉 harness；
3. 真实 macOS Cocoa 前台 TraceLab，加载 `testdoc/222.tlproj`；
4. 明确标记的推断或尚未验收项。

## 2. 执行摘要

UltraView 已经越过 2026-08-19 时“入口有了但纵向行为未闭环”的阶段。当前真实项目中可以看到并操作
View card、Sticky、Shape、选择工具条和格式弹层；拖动 View 后预览没有白屏，蓝色选择框和工具条也能在
release 后恢复。状态 schema、future payload 保留、反馈 surface、pointer coalescing 和 reset/shutdown
路径都有明确 owner 和测试基础。

但当前不能判定为稳定收口，原因不是单纯“还有些 UI 可再打磨”，而是存在三类阻断：

1. 混合选择键盘移动不是一个真正的原子事务；卡片移动被拒绝时，作者对象仍会静默移动。
2. 右下 minimap 只按固定 chrome 布局，不知道当前选择/缩放手柄，真实前台会直接盖住活动卡片及手柄。
3. 约 1280 个聚焦用例中仍有 6 个失败；其中既有真实结构/所有权问题，也有 2× micro-grid 和新 Pointer
   合同落地后未同步的旧测试。红色门禁没有被分类清零之前，不能用“大部分测试通过”代表稳定。

综合判断如下：

| 维度 | 当前判断 | 说明 |
|---|---|---|
| 核心功能 | 可用但非稳定 | 主纵切已工作；混合选择事务仍可部分提交 |
| UI 质量 | 明显提升，仍有遮挡和可访问性缺口 | 蓝色状态、弹层、工具条方向正确；minimap 和 AXPress 未闭环 |
| 状态/持久化 | 基础较稳 | schema 5、deep copy、future payload 和 reset 路径值得保留 |
| 交互/反馈 | 自动化基础较好，Cocoa 证据不完整 | viewport surface 和 coalescing 已落地；stationary hold 矩阵未正式验收 |
| 架构 | 边界存在，但 owner 再次集中 | state Qt-free；Coordinator/Page/Widgets 的职责与隐式协议继续膨胀 |
| 测试可信度 | 当前不合格 | 1274 passed 不能覆盖 6 failed；旧合同和真实回归混在一起 |
| 发布准备度 | NO-GO | 需先完成 P1/P2 hardening 和稳定快照验收 |

## 3. Findings

### [P1] 混合选择 nudge 会在卡片移动被拒绝时仍提交作者对象，破坏单事务语义

**证据**

- `ultraview_coordinator.py:2068-2088` 先构造卡片更新，调用 `set_free_grid_rects()` 后丢弃返回的
  warnings，随后无条件调用 `apply_author_nudge()`。
- `ultraview_state.py:1722-1752` 明确规定多卡更新为原子操作；非法矩形或 collision 会返回 warning，
  且不写入任何卡片位置。
- `test_ultraview_author_multiselect.py:148-173` 的测试 sink 复制了同一模式，也丢弃 warnings；现有用例
  没有覆盖 mixed selection 在边界/collision 被拒绝的路径。
- 确定性 probe：卡片从 `(0,0)` 移到相邻卡片占用区后返回 `grid_collision`，卡片仍在 `(0,0)`，
  同一 intent 中 Sticky 的 `x` 却从 `10.0` 变为 `14.0`，`mutation_changed=True`。

**用户影响**

用户框选 View card 与作者对象后用方向键移动，界面可能只移动其中一部分，但仍形成一条 history。
这会造成选择组“散开”、undo 语义不透明，并让用户误判卡片移动已经成功。

**必须修复**

- mixed nudge/delete 必须先生成一份纯数据 mutation plan，再一次性 commit；任一必需子操作被拒绝时
  全部不写入，并显示一个明确 warning。
- 统一从一个 mutation funnel 写 dirty/history/projection，不允许 coordinator 手工拼两条提交路径。
- 增加 card+author 的 collision、越界、locked、unknown、undo/redo 和 save/reopen 覆盖。

### [P1] Minimap 在真实 Free Grid 中遮住活动卡片、底部信息和 resize handles

**证据**

- 真实 macOS Cocoa、`222.tlproj`：右下 minimap 覆盖 View3 的图表底部和选中 resize handles；它位于
  card 之上，影响内容读取和命中判断。
- `page.py:4854-4870` 的显示条件只检查 free-grid、card 是否存在、panel/presentation 和 scrollbar，
  不检查 active selection、toolbar、handles 或 gesture。
- `page.py:4872-4883` 直接应用 floating layout 的固定位置并 `raise_()`。
- `floating_layout.py:475-493` 始终把 172×112 minimap 放在 navigation island 上方的右下区域；没有
  Board 内容或 selection bounds 输入。
- `page.py:1297-1310` 还把 minimap 放进统一顶层 reassert 列表，因此遮挡不是偶发 z-order 抖动，
  而是当前合同的稳定结果。

**用户影响**

用户无法同时看清/调整落在右下角的卡片；minimap 作为导航辅助反而占据了更高优先级的编辑命中区。

**必须修复**

- 活动拖动/缩放期间 minimap 折叠或隐藏；release 后不得与 selection bounds、handles、selection
  toolbar、format picker 相交。
- 从候选安全角中稳定选位；若所有候选都冲突，则折叠到 navigation overview action，不在内容上硬盖。
- 位置只在 selection、viewport、chrome geometry 或显示状态真正变化时重算，禁止随 pointer move 抖动。

### [P1] 当前 UltraView 聚焦门禁为红，且把产品回归、架构违约和旧夹具混成一组

**执行结果**

```text
6 failed, 1274 passed, 1 skipped, 189 warnings in 173.60s
```

失败分类：

1. `test_ultraview_structure.py::test_model_fields_written_only_in_state_module`
   - `author_edits.py:1202-1205` 的 `_BoardShim` 在 view package 内写入与 state model 同名字段，突破
     shrink-only AST guard。它不是实际 Board 写入，但证明新的 staging DTO 没有遵守既有边界表达。
2. `test_ultraview_structure.py::test_mutations_end_in_funnel`
   - `_on_auto_arrange_free_grid`、`_on_selection_delete`、`_on_selection_nudge` 成为新的 funnel 例外；
     nudge 已对应到上面的真实 partial-commit bug，因此不能扩大白名单解决。
3. `test_ultraview_sticky_slice.py::test_rail_and_sticky_popover_fit_800x560`
   - 用例仍要求 800×560 时 Pointer 不存在，而当前 release rail 明确展示 Pointer；同时视觉 harness
     记录 rail geometry 高 432、`sizeHint` 高 470，说明“显示全部入口”和“intrinsic height 必须相等”
     两个合同已冲突。
4. `test_ultraview_viewport.py::test_zoomed_pixel_map_error_does_not_grow_with_the_cell_index`
   - 断言仍以 1× macro pitch 计算，当前 `GridMetrics.resolution=2`。按 micro pitch 重算后，0/8/16/28/40
     cell 的最大误差分别约为 0.48/0.45/0.40/0.43/0.40 px，说明产品映射没有出现测试报告的
     314.4 px 漂移；这是迁移后旧断言。
5. `test_ultraview_viewport.py::test_legacy_board_viewport_is_ignored_by_payload_legalizer`
   - 用 schema 5 serializer 生成 24-column payload，再把顶层 schema 强改成 3；legalizer 正确把这种
     自相矛盾的输入报告为 `grid_columns_normalized`。使用真实 schema-3 的 12 columns 后 warnings 为空。
6. `test_verify_ultraview_visuals.py::test_ultraview_visual_harness_geometry_and_contact_sheet`
   - narrow rail 仍要求实际高度等于已不可容纳的 `sizeHint`；592 px 高的 Layout panel 被 safe rect
     上下夹紧后，仍要求其中心与 trigger 相差不超过 44 px。当前图像完整、八个模板可见、未盖住 nav，
     但旧中心锚定指标在现有 panel 高度下不可满足。

**用户影响**

门禁红意味着后续提交无法判断自己修了问题还是只改变了噪声；如果直接更新 expected/frozen set，又会
把真实 owner 回退和 mixed-nudge bug合法化。

**必须修复**

- 一项项重建正确合同，不做 blanket snapshot update。
- 结构 guard 只能通过移动 owner/使用明确 neutral DTO 收绿，不扩大 exception whitelist。
- 迁移夹具必须真实表达 schema-3 和 2× micro-grid；视觉合同改为“可见、可达、不裁切、不遮挡、与
  trigger 保持邻接”，不再使用物理上不可满足的中心差。

### [P2] Pointer 的鼠标和键盘入口可用，但原生 Accessibility Press 不会打开弹层

**证据**

- `chrome.py:191-218` 只在自定义 `mouseReleaseEvent` 和 `keyPressEvent` 中 emit
  `menu_requested`。
- `chrome.py:1301-1341` 对 Pointer 刻意不连接标准 `clicked`，其他工具才连接 click handler。
- 现有测试 `test_ultraview_author_chrome.py:696-717` 覆盖实体鼠标位置和 Space 键，没有覆盖
  `QAbstractButton.click()` / AXPress。
- 确定性 probe：对 enabled Pointer 调用 `button.click()` 后
  `qabstractbutton_click_menu_events=[]`。
- 真实 macOS 前台：物理坐标点击会打开 popup；通过 Accessibility element 的 Press 不会打开。

**用户影响**

VoiceOver、Switch Control、部分自动化和系统级“按下按钮”动作看到一个可访问按钮，却无法执行其主要行为。

**必须修复**

- 标准 `clicked`/AXPress 与 mouse/Space/Enter 进入同一个 popup toggle 路径；不得物理点击重复 emit。
- 增加 `button.click()` 和前台 AXPress 验收，保留整块 40/36 px 命中区。

### [P2] 状态边界仍在，但 Coordinator/Page/Widgets 已出现明显的职责再集中和隐式协议扩张

**证据**

- `UltraViewCoordinator` 已达 3876 行、222 个方法；`ultraview_coordinator.py:27-169` 同时导入
  workspace mutators、author edits、history、preview store、card fit、auto-arrange、sidecar、UI
  `LibraryRow` 与 compositor，而文件 docstring 仍把它描述为 capture pipeline。
- `page.py` 4959 行、326 个方法；`widgets.py` 6322 行、418 个方法。行数本身不是错误，但具体 owner
  泄漏已出现：`page.py:4615-4645` 读取 FreeGrid 私有 `_author_geometry_session` 和 toolbar 私有
  `_body_layout`。
- `widgets.py:218-224` 通过 parent chain 搜索 Page；`widgets.py:2463-2510`、`:3070-3100` 通过
  `getattr(parentWidget(), ...)` 形成运行时协议。重命名或换 parent 时没有静态/构造期失败，只有手势路径
  静默退化。
- `test_ultraview_structure.py:1-6` 明确规定结构棘轮只可缩小；当前两项结构测试失败说明新实现没有在
  同一提交中维护这个合同。

**用户影响**

这不是当前立即崩溃的 bug，而是 change amplification 风险：一个 Pointer、selection 或 history 变更会
同时触碰 Page、Widgets、Coordinator 和测试 harness；隐式协议断开时易表现为“按钮还在但手势失效”。

**必须修复**

- 不做大爆炸拆包；按事务 owner 一次抽一个 seam。
- 先抽 mixed selection/history mutation service，再抽 floating chrome/minimap policy，最后再评估 capture
  coordinator 分离。
- Widget 所需 host 能力使用显式小 protocol/callback bundle 注入；保留兼容 facade，不新增 MainWindow writes。

### [P3] 最近提交粒度过大且混入大量视觉证据，降低 review、bisect 与回退质量

**证据**

- `14ef0c17` 一次跨 43 个文件、`+13071/-418`，同时包含产品代码、spec/plan、help、测试、HTML
  prototype 和多张 PNG。
- 后续 chrome 修复仍多次同时修改产品、文档和大量 JPEG/PNG 证据。
- 当前仓库规则要求临时证据优先放 `.state/`，只有需要长期保留的验收记录才进入 Git。

**用户影响**

行为变更与证据资产无法独立回退；reviewer 难以确认一项 bug 是由交互、样式还是文档波引入。

**必须优化**

- 每个提交只包含一个行为 owner、对应 focused tests 和最少必要文档。
- 前台原始截图/录屏默认放 `.state/`；Git 中只保留经过挑选、带 README/结论的 durable evidence。

## 4. 值得保留的实现基础

本 review 不建议重写 UltraView。以下基础已经形成正确方向：

1. `ultraview_state.py:792-824` 的 Board/Workspace DTO 不依赖 Qt，author objects 和 future payload
   均有明确持久化边界。
2. `ultraview_state.py:1001-1019` 对 duplicate Board 做 author objects 与 passthrough deep copy，避免
   Board 间共享嵌套 payload。
3. `ultraview_state.py:2690-2745` 对 schema 1–5 统一迁移，并在 future schema 时保留 opaque payload。
4. `widgets.py:3238-3254` 已把 interaction owner、gesture、viewport feedback surface、latest pointer、
   candidate fingerprint 和 0 ms coalescer 放在同一局部 owner 内。
5. `widgets.py:4689-4868` 区分 ingest/latest sample、flush、viewport reprojection 和 candidate reuse；这比
   继续叠加 repaint/timer 补丁稳定得多。
6. `viewport_feedback.py:113-153` 使用 mouse-transparent、viewport-sized surface，并保存 immutable-ish
   frame/transform/generation 事实。
7. `ultraview_coordinator.py:2759-2815` 对 shutdown 与 project reset 有不同且对称的 timer/hook/store/
   runtime 清理路径。

## 5. UI 前台观察

### 已确认良好

- 蓝色 selected/handle/active-tool 方向一致；普通选中不再与 amber warning 混色。
- Pointer popup 已收窄为两行，Mouse/Laser 文案和 selected row 清楚。
- Sticky/Shape 的 selection toolbar 跟随对象 bounds；Shape format picker 能优先放在选择对象右侧。
- `222.tlproj` 中拖动 View4 后真实 preview 未白屏，release 后蓝框/handles 恢复，并出现重排 toast。
- 左上 Board/全局区域保持原信息架构，没有为了“像 Miro”而改成另一套产品。

### 仍需验收或优化

- minimap 遮挡是已确认前台缺陷。
- Pointer AXPress 是已确认可访问性缺陷。
- Laser 前台截图不能可靠证明 native cursor 外观；自动化只证明 `Qt.BitmapCursor`、32×32 和 hotspot。
  `widgets.py:3129-3164` 目前使用一个全局 32×32 cache，没有 screen/DPR key，2× Retina 和跨屏清晰度
  仍为 **UNKNOWN**。
- move/resize 的 0/100/500/2000 ms stationary hold、edge-pan、collision warning 和 release 矩阵未形成
  可引用的正式 Cocoa pass/fail 记录，因此当前只能写“源码和 offscreen contract 较完整”，不能写
  “前台持续反馈已验收”。

## 6. 验证记录

### 已执行

- 当前树 UltraView 聚焦+边界门禁：

  ```text
  6 failed, 1274 passed, 1 skipped, 189 warnings in 173.60s
  ```

- 前置较小聚焦集合：450 passed in 57.64s；该结果被更大的约 1280-test 结果覆盖，不能用来宣告全绿。
- 确定性 mixed-nudge probe：card 拒绝、author 仍移动，已复现。
- 确定性 Pointer standard-click probe：`button.click()` 不产生 popup event，已复现。
- 2× micro-grid 修正公式 probe：最大误差 < 0.5 px。
- 真实 schema-3 12-column payload probe：warnings 为空。
- offscreen visual harness：生成 23 张截图与 contact sheet；几何断言因 narrow rail/large layout panel 的
  旧指标失败。
- 真实 macOS Cocoa：当前工作树启动 TraceLab，加载 `testdoc/222.tlproj`，检查 Pointer popup、View drag、
  Sticky/Shape selection toolbar、format picker 和 minimap；测试进程已退出。

### 未执行 / 不得冒充已验证

- 未运行项目 full suite；本次是 UltraView 综合 review，且当前 focused gate 已经明确为红。
- 未执行 fresh Windows Full/Lite frozen 验收。
- 未完成 Cocoa stationary-hold 帧矩阵和录屏差分。
- 未保存对 `222.tlproj` 的前台试操作。

## 7. 最终裁决

UltraView 当前不是架构失控到需要重写，也不是 UI 仅差“最后一点 polish”。更准确的状态是：

- **产品纵切已建立，核心方向可保留；**
- **事务原子性、minimap 遮挡、可访问性和测试门禁可信度仍未收口；**
- **Coordinator/Page/Widgets 已接近下一轮变更的风险拐点，需要按 owner 小步抽 seam。**

建议严格按配套 Plan 的顺序推进：先恢复红色门禁的真实含义，再修 mixed transaction 与 minimap，随后
补 AXPress、DPR/Cocoa 证据，最后才做小步架构提取。完成这些门之前，不应继续扩作者工具种类、加入 dark
mode，或用更多 overlay/repaint 补丁处理反馈问题。
