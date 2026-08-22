# UltraView 稳定性、UI 质量与架构收口 Spec

- 日期：2026-08-22
- 状态：**PARTIAL / IMPLEMENTED OFFSCREEN**
- 基线：执行时 `HEAD=b71a118d`（原 review 基线 `1df1714d` 之上另有无关 commit），加 Pointer/Laser 与本 hardening 未提交工作树
- Cocoa AXPress / hold 矩阵 / Laser 原生 1×2×、full suite、Windows frozen：`UNVERIFIED` / `UNAVAILABLE`
- 来源：`docs/analyzer/reviews/2026-08-22-ultraview-current-state-comprehensive-review.md`
- 目标：在不扩产品表面的前提下，把当前 UltraView 从“可用但门禁红”收口到可稳定集成、可继续演进的基线

## 1. 范围

本 Spec 覆盖：

1. mixed card+author selection 的 nudge/delete/history 原子性；
2. minimap、selection toolbar、format picker 与固定 chrome 的遮挡关系；
3. Pointer 的 mouse/keyboard/Accessibility Press 一致性；
4. 800×560 compact rail 和大尺寸 panel 的可达/锚定合同；
5. move/resize viewport feedback 的正式 Cocoa 验收；
6. Laser cursor 的 Retina/DPR 与跨屏生命周期；
7. Coordinator/Page/Widgets 的小步 seam hardening；
8. 2× micro-grid、legacy schema 和 visual harness 门禁可信度。

## 2. 非目标

- 不增加新的作者工具、shape 类型或格式项。
- 不改左上 Board/全局区域，不重排现有 rail 信息架构。
- 不做 dark mode。
- 不修改 UltraView schema，除非后续独立 spec 明确授权。
- 不把 transient feedback、cursor、selection、timer 或 minimap 位置写入项目。
- 不引入全屏透明交互 overlay。
- 不重写 Page/Widgets/Coordinator；每次只移动一个已冻结行为 owner。
- 不用阈值抠图处理 preview 白底，不改变分析计算或源 View。

## 3. 设计原则

### 3.1 一个用户 intent 只能有一个提交结果

同一个 gesture/keyboard intent 涉及 card 与 author object 时，必须先得到完整计划，再整体接受或拒绝。
“card 不动、author 动了”或“一部分 card 动、一部分留在原处”均为合同违约。

### 3.2 编辑命中优先于导航辅助

优先级从高到低：active editor > pointer feedback/resize handles > selection toolbar/format picker > card 内容 >
minimap >装饰。低优先级 surface 不得遮挡高优先级命中区域。

### 3.3 可访问动作与视觉动作是同一个入口

Pointer tile 对 mouse release、Space、Enter、`QAbstractButton.click()` 和 macOS AXPress 的结果一致；
不得为不同输入维护独立状态机。

### 3.4 测试要表达当前产品语义，而不是迁移前常量

schema fixture 必须是真实历史 payload；micro-grid 断言使用 logical resolution；视觉断言关注用户可达性和
遮挡，不使用当前几何无法满足的理想中心值。

## 4. 功能合同

### UV-HARD-01：Mixed selection mutation 必须原子提交

1. 输入由 `card_refs`、`author_ids`、operation、delta/options 构成，不直接携带 QWidget。
2. owner 先构造 `SelectionMutationPlan`（名称可调整），至少包含：
   - placement before/after；
   - author patches；
   - warnings/reject reason；
   - affected ids；
   - history label。
3. plan 阶段不得修改 live Board。
4. 任一 required card update 非法、越界或 collision：
   - card 与 author 均不写入；
   - 不增加 undo/redo；
   - 不标 dirty；
   - 显示一次明确 warning。
5. locked/unknown author object 的语义必须显式：
   - locked/unknown 不移动；
   - 若产品决定“可移动项仍继续”，plan 必须在预览和 toast 中准确报告 affected count；
   - 不得静默把整个 mixed selection 当成全部成功。
6. 成功时只生成一条 `BoardEditEntry`，一次写入、一次 dirty、一次 projection refresh。
7. undo/redo 必须完整恢复 card placements、author patches、connector endpoints 和 selection 可见状态。
8. delete 与 nudge 共用同一个事务框架；auto-arrange 也必须进入既有 grid commit funnel，不新增例外。

### UV-HARD-02：Minimap 必须避让活动编辑区域

1. 默认尺寸仍为 172×112；默认候选仍可优先右下，不改变整体视觉方向。
2. 避让输入至少包括：
   - active card/author selection bounds，外扩 handle/hit margin；
   - selection toolbar；
   - active format picker/author flyout；
   - Board/Global/Status/Navigation islands 与 rail；
   - text/sticky editor；
   - viewport feedback surface 的活动 target rect。
3. 活动 move/resize/author geometry gesture 期间 minimap 必须隐藏或折叠到 overview action。
4. release 后按稳定顺序尝试安全候选：右下、右上、其余不改变左上产品 chrome 的候选；如果都冲突，折叠。
5. 同一 selection/viewport/chrome fingerprint 下位置不变化；pointer move 不触发候选切换。
6. minimap 不得覆盖 selection handles、toolbar 或 editor 的可点击像素。
7. panel 打开、presentation、overview、Board 切换、project reset 后没有残留 minimap。

### UV-HARD-03：Pointer tile 全输入路径一致

1. 40 px desktop / 36 px compact 的整个 tile 都打开或关闭 Pointer popup。
2. 以下输入只进入一个 toggle handler：
   - 左键任意点；
   - Space/Return/Enter；
   - `QAbstractButton.click()`；
   - macOS Accessibility Press。
3. 一次物理点击只 emit 一次；标准 `clicked` 接入后不得与自定义 release 双发。
4. 打开 popup 不切换 Mouse/Laser，不清 selection，不创建 history，不改变 zoom。
5. accessible name、role、enabled/selected/open 状态与可见 UI 一致。
6. popup 继续由 CanvasHost 托管，不退回 native blocking `QMenu`。

### UV-HARD-04：Compact rail 与大型 panel 使用可满足的几何合同

1. 800×560 必须保留当前 release rail 全部入口，包括 Pointer；不得通过再次隐藏 Pointer收绿。
2. 所有可见按钮 hit rect 完整位于 rail 内，顶部/底部不裁切，badge 不盖住相邻按钮。
3. rail 可以在可用 band 内压缩 group gap/divider clear；测试不得强制 actual height 等于无法容纳的
   unconstrained `sizeHint`。
4. Layout panel 八个模板均可见/可滚动到、可命中，panel 位于 rail 右侧、safe rect 内，不盖 Navigation。
5. panel 高度被 safe rect clamp 时，锚定合同改为：trigger center 落在 panel 的可见纵向 span 内，或 panel
   最近边与 trigger 保持明确邻接；不要求不可实现的 center-to-center 误差。
6. 800×560、1280×720、1440×900 均有 deterministic geometry facts 和 contact sheet。

### UV-HARD-05：Move/resize 持续反馈保持单 surface、单最新样本语义

1. FreeGrid 瞬态反馈继续使用 viewport-sized `ViewportFeedbackSurface`；不得把 FreeGrid 接回
   Board-sized `GhostOverlay`。
2. pointer sample、gesture lifetime、feedback frame 分离；stationary hold 不重复 planner/submission。
3. 只在真实 viewport transform 变化时 reproject：scroll、extent/origin、zoom、viewport resize。
4. 相同 candidate fingerprint 不重建 frame，不重采样 ghost，不增加 paint storm。
5. move/resize 的蓝色 target、handles、size badge 在按住 0/100/500/2000 ms 时持续可见，直到 release/cancel。
6. warning target 用 amber；普通 selected/current/panel/tool 状态保持 blue。
7. release/cancel/project reset/Board switch 后 timer、mouse grab、surface frame 和 dimming 对称清除。

### UV-HARD-06：Laser cursor 必须按 screen/DPR 生成和失效

1. Laser 只替换 cursor appearance；selection、drag、resize、zoom、history 与 Mouse 完全一致。
2. cursor cache key 至少包含 logical size、effective DPR 和 palette/version；不得只保留一个进程级 32×32 cache。
3. Retina backing pixmap 使用正确 `devicePixelRatio`，hotspot 以 logical coordinates 稳定映射到激光点。
4. screen/DPR change、窗口跨屏、离开 FreeGrid、presentation、reset/shutdown 时重新应用或清除 cursor。
5. offscreen 只证明 shape/pixmap/hotspot；最终清晰度必须由真实 Cocoa 1×/2×（如可用）截图或观察记录验收。

### UV-HARD-07：按 owner 小步收口架构

1. `ultraview_state.py` 继续 Qt-free；mutation planning/DTO 不放入 compatibility facade。
2. author staging 不在 view module 写入与 Board model 同名字段；使用 neutral projection DTO 或纯参数函数。
3. Coordinator 中所有 Board mutation 最终进入已声明 funnel；结构测试 frozen exception set 不扩大。
4. 第一优先 seam：`SelectionMutationService`（纯计划 + 单 commit）。
5. 第二优先 seam：`FloatingChromePolicy`（minimap/panel/toolbar collision facts；Qt-free geometry 优先）。
6. 第三优先 seam：从 `UltraViewCoordinator` 分离 capture/sidecar 与 workspace edit/history，但一次只移动一个
   call graph；保留现有 public imports/signals。
7. Card widget 不继续新增 `getattr(parentWidget(), ...)`；新能力通过显式 callback bundle 或小 protocol 注入。
8. 不新增 MainWindow 多文件 state writes；`test_main_window_state_ownership.py` 不扩白名单。

### UV-HARD-08：恢复门禁可信度

1. micro-grid exact-map 测试使用 `(column_width + gutter) / resolution`，仍覆盖负 origin 和 0/8/16/28/40。
2. legacy schema-3 fixture 明确写 `columns=12`；另设 inconsistent-schema 用例断言 normalization warning。
3. structure guard 通过 owner 修复收绿，不加入 `_on_selection_nudge/delete/auto_arrange` 例外。
4. narrow rail 测试断言全部入口可见/可达；不再断言 Pointer 为 `None`。
5. visual harness 记录 minimap 与 selection/handles 的 intersection facts。
6. Layout panel 使用邻接/可达合同；snapshot update 只能在几何事实通过后进行。
7. 所有 red test 必须有分类说明：product fix、test-contract correction 或 accepted platform limitation；不存在
   “先跳过/xfail 再说”。

## 5. 状态与持久化不变量

- Board schema 保持 5；Pointer mode、selection、minimap placement、feedback frame 不持久化。
- future opaque payload 在只打开/保存时保持不变；显式 workspace mutation 后才退出 opaque passthrough。
- duplicate Board 对 author objects/passthrough 深拷贝。
- mixed transaction 只产生一条 history，history byte budget 和 reset 语义沿用现有 owner。
- project reset 保留 live source canvas hooks 的既有防重复语义；shutdown 最终断开并清理全部 hook/timer/store。

## 6. 验收矩阵

| ID | 场景 | 自动化 | Cocoa 前台 |
|---|---|---|---|
| UV-A01 | card+author nudge 成功 | 单条 history、全体移动、undo/redo | 蓝框/对象同步移动 |
| UV-A02 | mixed nudge collision/越界 | 全体不变、warning、无 history | 一次 warning，无部分移动 |
| UV-A03 | mixed delete + connector | endpoint/placement/undo 一致 | 删除/撤销视觉一致 |
| UV-A04 | minimap 与右下选择冲突 | intersection 为 false 或 folded | handles/toolbars 不被盖住 |
| UV-A05 | Pointer mouse/key/click/AXPress | 每路径一次 menu event | VoiceOver/AXPress 打开同一 popup |
| UV-A06 | compact 800×560 | 全入口 rect 在 rail 内 | 无裁切、popup 可用 |
| UV-A07 | Layout panel 1280×800 | 八项、safe、adjacent、no-nav-overlap | 大 panel 仍能理解来源 |
| UV-A08 | move hold 0/100/500/2000 ms | planner/present 计数稳定 | target/handles 全程可见 |
| UV-A09 | resize+collision+edge-pan | frame/reproject/release 对称 | 蓝/amber 正确、无白屏 |
| UV-A10 | Laser DPR/screen change | cache key/hotspot/clear | native cursor 清晰且不改交互 |
| UV-A11 | schema 1–5/future | migration/roundtrip/opaque | 不需要视觉替代 |
| UV-A12 | reset/shutdown | timer/hook/cursor/surface 清空 | 重开无残留状态 |

## 7. 完成定义

只有全部满足以下条件，当前 hardening 才能标记为完成：

1. Review 中三个 P1 均关闭，并有对应回归测试；
2. 当前 6 个失败被逐项修复或以正确合同替换，UltraView focused/boundary gate 全绿；
3. Pointer AXPress 与 minimap 前台缺陷通过真实 Cocoa 验收；
4. move/resize stationary-hold 矩阵形成可引用 pass/fail 记录；
5. structure frozen sets 不扩大，MainWindow ownership whitelist 不扩大；
6. 没有新增 broad exception、silent fallback、持久化 transient state 或 full-screen interaction overlay；
7. 稳定 source snapshot 上完成一次集成 gate；若进入 release，再按项目规则执行一次 full suite 和独立
   acquisition_ui，且记录前后 HEAD/dirty fingerprint；
8. fresh Windows frozen 未执行时必须明确标记 `UNVERIFIED`，不得由 source/offscreen 代替。
