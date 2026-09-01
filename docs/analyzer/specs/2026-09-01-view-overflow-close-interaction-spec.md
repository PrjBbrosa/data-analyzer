# View 快速关闭与溢出面板交互 Spec

- 日期：2026-09-01
- 状态：DESIGN APPROVED / READY FOR IMPLEMENTATION
- 冻结分析基线：`f07b6a7c`
- 配套计划：
  [`2026-09-01-view-overflow-close-interaction-plan.md`](../plans/2026-09-01-view-overflow-close-interaction-plan.md)
- 视觉参考：
  [`2026-09-01-view-overflow-close-panel.html`](../ui-prototypes/2026-09-01-view-overflow-close-panel.html)
- 适用范围：共享 `ViewTabBar`，即时域与各分析分区的 View 栏

## 0. 决策结论

本功能是对现有 View 栏的**增量增强**，不重定义现有 View 操作：

1. View 标签已有的色标槽位在悬停时原位显示 `×`；`×` 必须在原槽位内水平、
   垂直居中，不增加任何标签宽度或额外像素占位。
2. 只有色标/`×` 命中区触发关闭。标签其余区域继续保持：单击切换 View、
   双击重命名、拖拽排序、右键打开既有菜单。
3. 点击现有 `»N` 溢出入口后，展开“全部 View”面板；每行可单独关闭，底部提供
   “关闭其他”和“关闭全部”。不增加第二个全局入口。
4. 底栏色标 `×` 与右键删除继续发出既有 `delete_requested`，因此时域的既有确认、
   分析 View 的既有清理逻辑和“至少保留一个 View”约束都不变。
5. `»N` 面板是整理台：行内 `×` 直接关闭该项、面板保持打开并重投影列表；不弹
   时域单删确认。批量关闭必须是一笔原子事务：一次确认、一次 owner mutation、
   一次最终投影。“关闭其他”保留当前 View；“关闭全部”结束后保留一个重置的空白 View。

HTML 仅用于确认布局、状态和视觉节奏。其中演示性的 toast/撤销以及网页像素值不是
Qt 产品合同；实际实现以本 Spec 和现有 owner 语义为准。

## 1. 已验证的当前行为

| 当前合同 | 代码 owner | 本功能要求 |
| --- | --- | --- |
| 标签单击通过 `currentChanged` 发出 `switch_requested(index)` | `ui/view_tabbar.py` | 原样保留 |
| 标签双击通过 `tabBarDoubleClicked` 进入 inline rename | `ui/view_tabbar.py` | 原样保留，关闭命中区不得进入此路径 |
| 标签拖拽通过 `tabMoved` 发出 reorder intent | `ui/view_tabbar.py` | 原样保留，关闭命中区不得启动拖拽 |
| 色标由 12 × 12 logical icon pixmap 绘制，merge host 可显示双颜色 | `ui/view_tabbar.py` | 共用同一 icon slot，不新增 close widget 宽度 |
| `»N` 当前列出全部 View，选行切换，隐藏标签使用 `setTabVisible()` | `ui/view_tabbar.py` | 保留入口、索引映射、测量式 roomy/compact/overflow 布局 |
| 最后一个 View 的删除被禁止 | `ViewManager.delete_view()` 与 UI | 所有新入口都必须遵守 |
| 时域单删先确认，分析单删同时清理 restore/pin/FRF cache | `_view_mixin.py` / `_analysis_mixin.py` | 新单删只复用既有路径，不复制语义 |
| 右键菜单已有重命名、复制、颜色、split、删除 | `ui/view_tabbar.py` | 菜单名称、顺序和行为不变 |

`QTabBar index == ViewManager index` 是现有隐藏/溢出方案的重要事实，但新 popup
传递跨确认或跨 mutation 的目标时必须使用稳定 `view_id`；显示名和短编号不得作为身份。

## 2. 范围与非目标

### 2.1 本次范围

- 标签色标悬停替换为居中的 `×`，并提供精确关闭命中区。
- 将现有 `»N` 菜单升级为可管理全部 View 的 popup。
- popup 行内单项关闭、关闭其他、关闭全部及批量确认。
- 时域与分析 View 共享同一呈现和意图合同，但各自保留现有删除副作用。
- 同步 View 交互 hints 与 quick reference。
- 覆盖鼠标、键盘、HiDPI、窄宽度、overflow、最后一个 View 和 Qt 生命周期。

### 2.2 明确非目标

- 不改变单击切换、双击重命名、拖拽排序、右键菜单、复制、颜色和 split。
- 不改变 roomy → compact → overflow 的宽度测量规则、View 上限或当前标签可见性。
- 不把关闭按钮放到编号、名称或标签外侧，也不增加 tab close button 列。
- 不增加“关闭后撤销”；HTML 中的 toast/撤销不是本轮功能。
- 不把底栏/右键的单项删除统一成新的确认策略；时域与分析区继续沿用各自当前语义。
  `»N` 面板行内 `×` 是整理入口，直接执行、不叠加单删确认。
- 不允许工作区进入零 View 状态。
- 不改变 View 持久化格式、View 命名规则或 UltraView Board/卡片语义。

## 3. 标签色标原位关闭合同

### 3.1 几何与绘制

1. 正常态继续绘制现有色标，包括 merge host 的双颜色色标。
2. 仅当指针位于某个可关闭标签的**色标槽位**时，该色标原位替换为 `×`；
   悬停标签的名称、编号或空白区域不得显示 `×`。
3. `×` 复用当前 12 × 12 logical icon slot；`QTabBar.iconSize()`、标签 padding、
   `sizeHint()` 与每个 `tabRect()` 的宽度在 normal/hover/pressed 状态完全相同。
4. `×` 的可见 ink bounding box 中心与色标槽位中心对齐。允许因奇偶像素产生不超过
   0.5 logical px 的栅格偏差；不得靠肉眼偏移常量补偿某一 DPR。
5. pixmap 必须 HiDPI-aware；在 DPR 1、2 和 macOS Cocoa 的实际 DPR 下仍居中、清晰。
6. 关闭 hover/pressed 使用现有危险色体系；不得改变 active tab 的背景、下划线或尺寸。
7. 只有一个 View 时保留普通色标，不显示 actionable `×`。

HTML 中较宽的 27 × 17 色块表达“同槽替换”关系，不是 Qt 必须采用的新尺寸。
产品实现继续服从当前 Qt icon slot 的真实测量几何。

### 3.2 命中区

- 命中区等于从当前 style option / tab rect 推导出的真实 icon slot rect，不使用写死的
  toolbar 坐标或网页像素。
- 命中区不得覆盖编号、名称、tab 间隙或相邻标签。
- popup 行末 `×` 是独立明确按钮；“色标替换为 `×`”只适用于底栏 tab。
- 命中测试必须在 resize、compact、active-tab relocation、overflow 后重新基于当前几何计算。

### 3.3 事件优先级（硬合同）

事件按下表路由，关闭槽位优先于 `QTabBar` 默认行为：

| 输入 | 目标 | 唯一结果 | 明确禁止 |
| --- | --- | --- | --- |
| `MouseMove` | 色标槽位 | 仅切换色标/`×` 绘制并显示 tooltip | 不发 signal、不改 current、不重排布局 |
| 左键 press | 可关闭槽位 | 记录 stable `view_id` 的 armed 状态并消费事件 | 不调用 tab 默认 press，不切换、不重命名、不启动拖拽 |
| 左键 release | 同一 View 的同一槽位 | 发出一次既有 `delete_requested(index)` | 不额外发 `switch_requested` |
| 左键 release | 槽位外、目标已移动或失效 | 取消 armed 状态 | 不关闭、不切换、不重排 |
| 双击 | 可关闭槽位 | 消费事件；最多形成一次单删意图 | 不进入 inline rename，不产生双删 |
| 左键单击 | 标签非槽位区域 | 走现有切换路径 | 不关闭 |
| 双击 | 标签非槽位区域 | 走现有 inline rename | 不关闭、不额外切换到别的 View |
| 左键拖动 | 标签非槽位区域 | 走现有 reorder 路径 | 不改变既有 reorder/current 抑制规则 |
| 从 `×` 起拖 | 关闭槽位 | armed 后移出即取消 | 不启动 reorder |
| 右键 | 标签任意区域（含色标） | 走现有 context menu | 不显示/触发快速关闭 |

实现必须在 press/release 两端消费关闭事件，不能只在 click 后补偿已经发生的 View
切换。armed 状态在 tab rebuild、View 删除、popup 关闭、窗口失焦和对象销毁时对称清空。

### 3.4 提示

- 可关闭色标槽位 hover tooltip：`关闭 View「<完整名称>」`
- 唯一 View 的色标 tooltip：`至少保留一个 View`
- compact/overflow 的既有“完整名称”提示继续可用；关闭提示不得永久覆盖名称发现路径。

## 4. “全部 View”面板

### 4.1 入口与锚定

- 继续使用现有 `»N` 按钮，不增加额外按钮。
- popup 锚定到 `»N` 的下边缘，并按可用屏幕空间向左/向上夹取；不得越出当前屏幕。
- popup 是 parented transient Qt surface；点击外部或按 `Esc` 关闭，并把键盘焦点还给入口。
- popup 打开时按钮保持 expanded/active 状态；关闭或 owner 销毁后状态对称复位。
- popup 高度受屏幕约束，View 列表独立滚动，header/footer 保持可见。
- 面板宽度按名称与 footer 取中间值：短名称不撑满，长名称省略并靠 tooltip
  给全名；footer 两按钮均分该宽度、使用紧凑高度。打开后宽度不随删除收缩。
- 列表始终预留垂直滚动槽，避免滚动条出现/消失时 `×` 列左右跳。
- 行重建后按光标位置恢复 `×` 的 hover 态，连续关闭时不必先移开鼠标。

### 4.2 内容和精确文案

Header：

- 标题：`全部 View`
- 计数：`<N> 个`
- 不放置操作说明或帮助句。行结构（名称切换、行末 `×` 关闭）自行说明。

每行包含现有色标、完整 View 名称、当前 View 标记以及行末 `×`。行主区域单击切换，
行末 `×` 只关闭该行；两者命中区不得重叠。当前 View 使用稳定 `view_id` 判断。
列表区域与 header/footer 用内缩井框分开：井框由列表层自己绘制在左右 8px
边距上（不能画在父 surface 上，否则会被白底子控件盖住）。`×` 的 hover 红底
由关闭按钮自己 paint，不依赖 QSS `:hover`。

Footer：

- 按钮：`关闭其他`
- 按钮：`关闭全部`
- 不放置批量操作说明。确认文案只出现在用户点击批量按钮之后的 dialog 里。

当只有一个 View 时，所有行末关闭、`关闭其他` 与 `关闭全部` 都 disabled，并通过
tooltip/accessible description 说明 `至少保留一个 View`。

### 4.3 行为

- 点击行主区域：复用既有 `switch_requested`，切换成功后关闭 popup。
- 点击行末 `×`：面板保持打开，发出 `overflow_delete_requested(index)`（不走
  底栏 `delete_requested`）。时域 host 跳过单删确认并立即删除；分析 host 复用
  既有单删 cleanup。删除后 popup 按新的 manager 状态重投影行、计数和按钮
  enablement。`Qt.Popup` 不能与 `QMessageBox` 共存，因此这条路径不得再弹单删
  确认。
- 若删除后不再溢出（`»` 隐藏），popup 随入口一起关闭；用户改从底栏继续操作。
- 删除失败或 View 已失效时不做补偿 mutation，面板保持打开。
- 删除当前 View 后新的 current 选择继续由 `ViewManager` 既有规则决定。
- “关闭其他”“关闭全部”仍先关闭 popup，再走既有一次确认。

## 5. 批量关闭语义

### 5.1 关闭其他

确认文案：

- 标题：`关闭其他 <N> 个 View？`
- 正文：`将只保留当前的 View <ordinal>「<完整名称>」。`
- 警示：其他 View 保存的范围、split 和附件关系会一并移除。

确认后以当前 View 的稳定 `view_id` 执行一次原子 retain-only transaction。保留 View
本身及其 `view_id`、名称、颜色、曲线、范围和 split 中仍合法的状态；所有涉及已删除
View 的 split 配对必须由 manager 一次性规范化。当前 View 不得被复制成新对象。

### 5.2 关闭全部

确认文案：

- 标题：`关闭全部 <N> 个 View？`
- 正文：`完成后保留一个已重置的空白 View，工作区不会变成无 View 状态。`
- 警示：全部 View 保存的范围、split 和附件关系会一并移除。

确认后复用 manager 的 single-default reset 语义：生成一个干净默认 View、清空 split
状态并只发布一次最终变化。它不是“保留当前再清内容”，也不是循环调用单删。

### 5.3 原子性与 section cleanup

- cancel：零 mutation、零 render、零 cache cleanup。
- confirm：一次 manager mutation、一次 views-changed/final projection、一次用户反馈。
- 不逐 View 弹确认，不让用户看到中间 current/split 状态。
- 时域 owner 先捕获当前 View 意图再提交；分析 owner 必须对全部 removed `view_id`
  执行与现有单删等价的 pending restore、pin 和 FRF pane cache 清理。
- 任一 cleanup 无法在一次 transaction 中证明等价时，批量功能停线，不以循环单删上线。

## 6. 组件和状态 ownership

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `ViewTabBar` | tab 命中/绘制、popup 开关、发 typed intent | 直接修改 `ViewManager` 或 section cache |
| popup presentation widget | immutable row 投影、键盘焦点、row/bulk intent | import `MainWindow`、以名称为 identity |
| `ViewManager` | retain-only / reset 的原子 View 状态事务 | 逐项 presentation、弹 dialog |
| 时域/分析 host | 确认、capture、section-specific cleanup、最终 render | 复制 tab hit-test 或 popup UI |

底栏色标与右键单项关闭继续使用 `delete_requested(index)`。面板行内关闭使用：

- `overflow_delete_requested(int index)`

批量 intent 为稳定身份：

- `close_others_requested(str keep_view_id)`
- `close_all_requested()`

Popup row DTO 至少包含 `view_id`、完整名称、ordinal、颜色/partner color、是否 current、
是否可关闭。DTO 不携带 QWidget、manager 或可变 View 对象。

新增 mutable UI 状态仅归 `ViewTabBar`/popup 所有，显式初始化，并在 rebuild、hide、
close、destroy 路径对称清理；不得新增跨多个 MainWindow mixin 的隐式状态。

## 7. 键盘、可访问性和视觉合同

- `»N` 可用 Space/Enter 打开；`Esc` 关闭并恢复焦点。
- popup 行支持 Up/Down 导航，Enter/Space 切换；行末关闭按钮可独立 Tab 聚焦并由
  Enter/Space 触发。Delete 键不作为隐藏的批量删除快捷键。
- “关闭其他”“关闭全部”进入正常 tab order，disabled 状态不可触发。
- accessible name 使用完整 View 名称，例如 `关闭 View「Wheel input torque」`。
- `×` 不得只依赖颜色表达危险操作；hover、pressed、focus-visible 均有可辨状态。
- popup 圆角底板必须真实 paint，不只依赖 translucent top-level 的 stylesheet；
  Cocoa 前台截图中不得透出后方曲线或文字。
- 字体缩放、中文/英文名称和 24 个时域 View 下，名称省略但完整 tooltip/accessible name
  可取，footer 不被滚动列表挤出。

## 8. 验收矩阵

### 8.1 不回归硬门禁

- normal → hover → pressed：每个 tab 的 `tabRect().width()` 和 rail 总宽不变。
- 点击非色标区域仍只发一次 switch；双击非色标区域仍只打开一次 rename editor。
- 点击/双击/拖动 `×` 不发 switch、rename、reorder；有效 release 只发一次 delete。
- 右键色标仍出现既有 context menu；原菜单文字和 enablement 不变。
- reorder 后 stable identity、颜色和目标 View 一致；活动标签不会因 hover 或 close press 位移。
- roomy、compact、overflow、10 个普通 View、24 个时域 View 全部遵守相同合同。
- 唯一 View 始终保留色标，所有新关闭动作不可用。

### 8.2 popup 与事务

- popup 列出全部 View，而非仅隐藏 View；当前标记和 `»N` count 与 manager 一致。
- 名称区域切换、行末按钮关闭，不发生 hit-region 穿透。
- 行内 `×` 连续关闭时面板保持打开并刷新列表；时域不弹单删确认。底栏/右键单删
  仍走 section 既有路径：时域确认取消零变化；分析删后 cache 可回收。
- 关闭其他保留精确 current `view_id`，一次 signal/render；关闭全部得到一个干净默认 View。
- cancel、stale `view_id`、popup 外点、Esc、window close、tab rebuild 均无遗留 armed/
  expanded/focus 状态。

### 8.3 视觉证据

- Qt offscreen 图像断言：`×` ink center 与 icon slot center 对齐，误差不超过 0.5 logical px；
  hover 前后 tab geometry 完全一致。
- macOS Cocoa 前台：录制/截图 normal、hover、pressed、popup、confirm 五态；量测 `×`
  居中、底板不透、popup 不越屏。HTML 截图只能作为视觉目标，不能替代 Qt 证据。

## 9. 完成定义

只有同时满足以下条件才可宣称实现完成：

1. 标签关闭只占用现有色标槽位，`×` 居中且无任何布局变化；
2. 单击切换、双击重命名、拖拽排序、右键菜单均由自动化证明不回归；
3. popup 行内关闭与两项批量动作符合本 Spec 文案、确认和原子性；
4. 时域/分析的现有 owner 副作用分别闭环，唯一 View 永不被删除；
5. hints/quickref 同步；offscreen owner/boundary 测试和 Cocoa 前台验收均有证据；
6. 未修改本 Spec 列为非目标的 View 行为、持久化或 UltraView 语义。

