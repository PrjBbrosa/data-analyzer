# UltraView Author Chrome 产品修复执行计划

> 日期：2026-08-23
>
> 状态：**REVIEWED / READY FOR AGENT EXECUTION / NOT STARTED**
>
> 决策门：**Laser 视觉方案需用户确认；未确认前 W6 不得实施**
>
> 范围：UltraView 作者工具条、格式选择器、浮层、布局面板、Laser 图标/光标、作者对象缩放光标与相关帮助/验证面
>
> 本次记录：只完成计划审阅与重写；**未执行任何产品源码修改、测试或前台验收**

---

## 0. 审阅结论

原计划覆盖了主要症状，但还不能直接交给执行 Agent。以下缺口已在本版收口：

| 优先级 | 原计划缺口 | 本版处理 |
|---|---|---|
| P1 | FormatButton 的颜色类型靠异常回退猜测；实际 sticky_colors("ink") 会静默回退黄色 | 要求显式 swatch_role 和 Qt-free 解析器，禁止异常猜测 |
| P1 | “选择器与工具条无间距”的根因已与当前代码不符；当前定位已有 6 px 间距 | 改成测试优先的条件修复；生产 QSS 证据不失败就不改定位源码 |
| P1 | 删除 Sticky 形状、Text 链接、Duplicate 时未区分隐藏 UI 与删除持久化能力 | 明确只移除工具条入口；保留旧项目字段、序列化、快捷键和剪贴板能力 |
| P1 | Sticky 正方形吸附没有阈值、解除条件、锚点、预览/提交一致性 | 定义四角、8/12 px 滞回、修饰键旁路、固定对角、预览等于提交 |
| P1 | 游标需求没有统一优先级，容易被 Laser、创建模式、禁放态覆盖 | 定义单一优先级和共享 resize 映射，覆盖 hover、drag、release、模式切换 |
| P1 | Laser 需要产品选择，但原计划没有阻断式人工门 | 增加 G-LASER：先交互式 A/B/C HTML，再由用户明确选型 |
| P2 | 菜单“图形化”没有逐控件契约，容易扩大成主观重绘 | 增加 presentation matrix、宽度范围和不改交互语义约束 |
| P2 | 没有枚举 owner、旧测试冲突、视觉脚本与帮助文案 | 增加 touchpoint、stale-test、hints、quickref、图标和视觉 harness |
| P2 | 验证缺少命令、证据类型、稳定快照和真实 Cocoa 门 | 分成 focused、boundary、artifact、Cocoa 四级 gate，并规定状态上限 |
| P2 | 当前工作树很脏，计划未约束文件归属与集成快照 | 增加 W0 指纹、允许触点清单、逐波提交/回滚和无关文件排除 |

**总判断：** 本版可由一个 Agent 从 W0 开始按顺序执行；到 G-LASER 必须暂停等待用户选择。除该人工产品决策外，不应再依赖执行者自行猜测。

---

## 1. 目标、非目标与完成边界

### 1.1 目标

1. 修复作者格式按钮和颜色选择器的色块语义，包含透明色视觉。
2. 让格式选择菜单按控件角色使用图形预览，并收紧明显过宽的 font/size 菜单。
3. 从选择工具条中移除无产品价值的入口，同时保留项目兼容和快捷操作。
4. Sticky 从角点缩放时稳定吸附正方形，预览与最终模型一致。
5. 修复浮层间距与布局面板右侧留白，但只修改被当前生产样式复现证明有问题的 owner。
6. Mouse 与 Laser 模式下，作者对象八向缩放游标在 hover、drag、release 全生命周期正确。
7. 用用户选定的视觉方案统一 Laser 菜单图标与真实光标，不改变 Laser 的交互语义。

### 1.2 非目标

- 不重构 UltraViewCoordinator、Page 或浮层系统整体架构。
- 不删除旧项目中的 StickyObject.shape 或 TextObject.link 字段，不迁移项目 schema。
- 不删除 Cmd/Ctrl+D、复制/粘贴或对象复制能力；只调整工具条可见入口。
- 不改变 Pointer/Laser 的选择、拖动、缩放、平移和滚轮缩放语义。
- 不增加全屏透明交互层、重复 overlay、raise 或定时 repaint 补丁。
- 不顺带清理工作树中的其他 UltraView 修改、生成物或无关文件。
- 不在用户确认 G-LASER 前擅自选择 Laser 方案。

### 1.3 完成标准

只有同时满足以下条件才可标记 PASS：

- 代码和测试实现本计划逐项契约；
- focused 和 boundary gates 全绿；
- 视觉 harness 生成并通过自动断言；
- 真实 macOS Cocoa、前台 TraceLab 按第 12 节矩阵通过；
- G-LASER 有用户明确选型记录；
- git diff --check 通过，且变更文件均在 W0 清单中。

缺少 Cocoa 前台证据时，最高状态为 PARTIAL / NEEDS FOREGROUND VERIFICATION；不能用 offscreen Qt、源码审查或截图替代。

---

## 2. 当前树事实基线（执行前必须复核）

| 当前事实 | 证据位置 | 执行含义 |
|---|---|---|
| 产品版本来源唯一 | mf4_analyzer/app_meta.py:APP_VERSION | 本任务不做版本变更 |
| FormatButton.paintEvent 先调用 sticky_colors(value) | mf4_analyzer/ui/ultraview/author_chrome.py | ink 会静默成为 Sticky 黄色；不能靠 try/except 区分 |
| sticky_colors 对未知 token 回退黄色 | mf4_analyzer/ui/ultraview/author_style.py | 必须显式传递色块语义 |
| format_picker_rect 当前已有上下 6 px gap | mf4_analyzer/ui/ultraview/author_ui_controller.py | 原计划“无 gap”根因不成立；先补生产 QSS 复现测试 |
| StickyObject.shape 和 TextObject.link 已持久化 | ultraview_core/model.py、author_ops.py | 隐藏入口不得破坏读写兼容 |
| Duplicate 同时有工具条入口和快捷键/剪贴板路径 | author_selection.py、page.py | 只移除工具条入口 |
| 卡片 resize 已有八向 HANDLE_CURSORS 映射 | free_grid_board.py | 作者对象应共享语义，避免第二套漂移 |
| Layout picker 是 2 列固定缩略图，宽度未显式预留 scrollbar | chrome_popovers.py | 修复由 Layout picker 自己拥有，不在 Page 写平台宽度常量 |
| 视觉 harness 已覆盖部分 picker/Laser | tools/verify_ultraview_visuals.py | 扩展现有脚本，不新建第二套 |
| 旧测试锁定 32×32、hotspot (25, 5)、Duplicate 和旧菜单宽度 | tests/ui/test_ultraview_author_*.py | W0 先列明并有意更新，不把预期失败当回归 |

执行者开始时必须记录：

~~~text
HEAD:
branch:
git status --short:
计划内已有脏文件:
计划外已有脏文件:
正在运行的 pytest 进程:
~~~

审阅时 HEAD 为 2feddfa1，但它只是历史记录；执行时必须重新获取。

---

## 3. 执行顺序与依赖

~~~text
W0 盘点与失败契约
 ├─ W1 显式色块语义
 ├─ W2 菜单 presentation matrix
 ├─ W3 工具条瘦身 + Sticky 正方形吸附
 ├─ W4 浮层间距 + Layout 右侧留白
 └─ W5 作者对象 resize 游标
        ↓
G-LASER 交互式 A/B/C 原型 + 用户选择（阻断）
        ↓
W6 Laser 图标/光标实现
        ↓
W7 集成、自动验证与 Cocoa 前台验收
~~~

- W1–W5 可在不等待 Laser 选型时顺序完成。
- 当前文件有用户修改时，必须在其基础上最小编辑；不得恢复、覆盖或格式化无关内容。
- 每一波先写失败测试或确定性 probe，再改 owner；期望变更与实现位于同一波。

---

## 4. W0 — 盘点、工作树隔离与失败契约

### 4.1 产物

创建：

docs/analyzer/verify/2026-08-23-ultraview-author-chrome-product-fixes/inventory.md

至少包含：

1. 执行快照指纹：HEAD、branch、git status --short、相关文件 hash 或 diff 范围。
2. 控件矩阵：对象类型 → 工具条控件 → picker key → presentation role → 数据语义。
3. overlay 矩阵：overlay 类别 → size owner → placement owner → production QSS 路径。
4. cursor 矩阵：模式 → hit target → hover/drag/release cursor → owner。
5. 所有会被本任务有意更新的旧测试断言。
6. 计划内与计划外脏文件清单。

建议检索：

~~~bash
rg -n "FormatChoiceFlyout|format_picker_rect|ToolbarControl|can_duplicate|sticky_shape|link|HANDLE_CURSORS|laser_cursor|ultraview_author_laser|LayoutPicker" mf4_analyzer tests tools docs/analyzer
~~~

### 4.2 允许触点

确认 owner 后可修改以下范围；新增触点必须先回写 inventory 理由：

- mf4_analyzer/ui/ultraview/author_style.py
- mf4_analyzer/ui/ultraview/author_selection.py
- mf4_analyzer/ui/ultraview/author_chrome.py
- mf4_analyzer/ui/ultraview/author_ui_controller.py
- mf4_analyzer/ui/ultraview/author_interaction.py
- mf4_analyzer/ui/ultraview/author_ops.py（仅兼容或提交路径需要时）
- mf4_analyzer/ui/ultraview/free_grid_board.py（只抽取共享 resize 语义时）
- mf4_analyzer/ui/ultraview/chrome_popovers.py
- mf4_analyzer/ui/ultraview/laser_cursor.py
- mf4_analyzer/ui_kit/icons.py
- mf4_analyzer/ui/hints.py
- mf4_analyzer/ui/quickref.py
- 对应 tests/ui、tests/ui_kit focused tests
- tools/verify_ultraview_visuals.py
- 本计划指定的 prototype/verify 文档

明确排除：

- ssh-keygen、ssh-keygen.pub；
- 计划外 .state、截图、缓存和本地运行产物；
- 与本任务无关的现有工作树修改。

### 4.3 W0 Gate

- [ ] inventory 已记录现状矩阵和 owner。
- [ ] 旧断言冲突全部列明。
- [ ] 每个症状有失败测试或确定性 probe；无法先失败的项目写明原因。
- [ ] 未改任何产品行为。

---

## 5. W1 — 显式色块语义与透明色视觉

### 5.1 实现契约

1. 在 UI-neutral 的 style/selection 数据层为颜色控件增加显式 swatch_role，角色至少覆盖 sticky、ink、fill、stroke、text。命名可匹配现有风格，但必须由调用方传入；不得从 token、label 或异常类型猜测。
2. 提供 Qt-free 解析器，输入 swatch_role 和 token，输出可见 RGB/RGBA、是否 transparent，以及必要的前景/边框建议。
3. SelectionToolbar 和 FormatChoiceFlyout 共用同一解析结果与绘制 helper。
4. 禁止先试 sticky_colors、失败后再试 ink_color；禁止未知 token 静默跨 role 涂成黄色；禁止 toolbar 和 picker 各写一套解析。
5. 透明色固定为白色或浅棋盘底、对角红线、可见描边，并有“透明” tooltip/文本；不能只显示为普通白色。
6. 未知 token 使用该 role 的稳定 fallback。若记录诊断，必须使用已有节流路径，不在 paint hot path 制造日志风暴。

### 5.2 测试

- tests/ui/test_ultraview_author_style.py：每个 role 的合法/未知 token、transparent 描述、无 UI import。
- tests/ui/test_ultraview_author_chrome.py：Sticky、ink、fill、stroke、text 当前色块；toolbar 与 picker 一致；transparent 红斜线像素或绘制命令。
- 修改 import seam 时加 tests/ui/test_import_boundaries.py。

### 5.3 W1 Gate

- [ ] ink 不再显示成 Sticky 黄色。
- [ ] 所有颜色入口都有显式 role。
- [ ] toolbar、picker、transparent 像素/语义测试通过。

---

## 6. W2 — Picker presentation matrix 与宽度收敛

不得继续靠 label 是否像字号或字体名推断绘制方式。为每个 picker key 显式映射 presentation role：

| picker key 类别 | presentation | 目标宽度（逻辑 px） | 约束 |
|---|---:|---:|---|
| font | 用候选字体渲染字体名 | 112–120 | fallback 字体可读、不截断 |
| font_size | 数字 + 基准线/字号差异 | 104–120 | 当前项清晰 |
| line_width、stroke_width | 不同粗细线段 | 120–144 | 不只显示数字 |
| dash | 实线/虚线/点线样例 | 120–144 | 与模型值一致 |
| route、head、align | 路径/箭头/对齐 glyph | 120–144 | 保留可访问文本 |
| list、tool | icon + label | 136–168 | icon 来自现有 registry |
| corner | 尖角/圆角轮廓 | 120–144 | 与 corner 值一致 |
| shape | 现有图形宫格 | 208–216 | 只保留仍在产品中的 Shape picker |
| 所有颜色 key | 色块 + 可访问文本 | 依内容 | 复用 W1 |

尺寸 owner 只保留在 FormatChoiceFlyout。展示变化不得改变选择、键盘导航、hover、checked、关闭和 signal payload。文本仍是可访问语义；长中英文 label 不得遮挡 checked 标记；未知 choice 使用稳定文本 fallback。

测试：

- tests/ui/test_ultraview_author_chrome.py：每种 role 的绘制和宽度区间、长 label、fallback font、checked/hover；有意替换旧 font width 152–168 断言。
- tests/test_verify_ultraview_visuals.py：harness 能捕获每类代表性 picker。

### W2 Gate

- [ ] 所有 picker key 都有显式 presentation role。
- [ ] font/size 宽度落入表中范围。
- [ ] 图形预览不改变模型 value 或 signal payload。

---

## 7. W3 — 工具条瘦身与 Sticky 正方形吸附

### 7.1 只移除可见入口

从 selection toolbar 和 More 菜单移除：

- Sticky 的 shape 控件；
- Text 的 link 控件；
- 单选/多选的 duplicate 控件。

必须保留：

- 旧项目 StickyObject.shape、TextObject.link 的反序列化与再次保存；
- 既有 Cmd/Ctrl+D；
- 复制/粘贴、撤销/重做；
- programmatic duplicate 能力和公开兼容 seam；
- 旧对象渲染不因字段存在而报错。

同步更新 mf4_analyzer/ui/hints.py、mf4_analyzer/ui/quickref.py，以及工具条 contract/multiselect 旧断言。不得为了隐藏入口删除模型字段或做 schema migration。

### 7.2 Sticky 正方形吸附

只对单个 Sticky 的四个角点 resize 生效；边中点保持自由宽高。

1. 以固定对角为锚点计算候选 width、height。
2. 阈值使用屏幕逻辑像素，不使用缩放后的 board unit。
3. abs(abs(width) - abs(height)) 小于等于 8 px 时进入 square snap。
4. 已吸附后，差值大于 12 px 才解除，形成滞回。
5. 吸附边长取当前指针位移中较大的绝对分量；保留拖动象限和固定对角。
6. 继续服从最小尺寸、board 边界、网格和 collision 规则。
7. 按住平台主快捷修饰键时临时旁路：macOS Command，其他平台 Control；释放后按当前指针重新评估。
8. 蓝色 preview、size badge、collision feedback 和 release commit 必须使用同一个候选 rect。
9. snap 状态在 release、cancel、selection change、mode change、对象删除和 teardown 时清零。

若统一 resize pipeline 不能同时承载预览和提交，先把候选 rect 计算收敛到 owning helper；不得复制到 overlay。

测试：

- tests/ui/test_ultraview_author_geometry.py：四角、四象限、8/12 px 边界、修饰键旁路、最小尺寸与边界/collision、preview rect 等于 committed rect。
- tests/ui/test_ultraview_author_multiselect.py：toolbar duplicate 消失，快捷键/clipboard duplicate 仍可用，混合选择契约不放宽。
- tests/ui/test_ultraview_author_tools.py：Sticky/Text 入口消失，旧字段 load/save round trip。
- tests/ui/test_hints.py、tests/ui/test_quickref.py：文案与真实入口一致。

### W3 Gate

- [ ] 三个入口不可见，但兼容能力仍通过 round-trip/shortcut tests。
- [ ] Sticky 四角吸附无临界抖动。
- [ ] preview、badge、collision、commit 使用同一个 rect。

---

## 8. W4 — 浮层间距与 Layout 面板右侧留白

### 8.1 Format picker：条件修复

当前 format_picker_rect 已包含 6 px 上下 gap，因此不得先改生产定位代码。先写 production QSS 下的 geometry/pixel probe：

- 下方或翻转到上方时，picker 与 toolbar 的可见外边框最小垂直空隙均大于等于 6 px；
- 阴影或透明 margin 不算可见空隙；
- viewport 边缘 clamp 后不与 toolbar 可见边框重叠。

若 probe 已绿，记录 NO SOURCE CHANGE，只保留回归测试。仅 probe 失败时修改 author_ui_controller.py 的 placement owner，不得在 QSS padding、flyout sizeHint 和 controller 三处重复补偿。

### 8.2 Layout picker

由 chrome_popovers.LayoutPicker 自己保留 scrollbar 空间：

- 使用 QStyle.PM_ScrollBarExtent，不写 macOS 专用魔法宽度；
- 内容右边缘到 scroll viewport 至少 8 px；
- 内容或 scrollbar 到面板可见外框至少 12 px；
- 两列缩略图宽度和间距不缩小；
- 无横向滚动条；
- overlay placement 仍服从 Page 统一 clamp。

不得在 Page._overlay_size 再加 Layout 专用平台常量。

### 8.3 回归矩阵

在 production QSS 下检查 Layout、Template、Overview、Presenter、Share、Settings、Pointer、Draw、Shapes、Text、selection toolbar、format picker、context menu；viewport 使用 800×560、1280×800、1440×900，并覆盖靠左、居中、靠右和上下翻转。

测试：

- tests/ui/test_ultraview_author_chrome.py
- tests/ui/test_ultraview_chrome.py
- tests/ui/test_ultraview_floating_chrome_controller.py
- 必要时增加 production-QSS geometry/pixel test。

### W4 Gate

- [ ] format picker gap 有当前复现证据；已绿则没有无依据源码改动。
- [ ] Layout scrollbar 和内容均有明确右侧留白。
- [ ] 无水平滚动、缩略图缩窄或其他 overlay 尺寸回归。

---

## 9. W5 — 作者对象八向 resize 游标

### 9.1 单一优先级

统一由现有 cursor owner 决策，同一事件只允许最高优先级生效：

1. 平移按下或空间键 pan；
2. 禁止放置或碰撞拒绝；
3. 创建工具专用游标；
4. 正在 drag 的 resize handle；
5. hover 的 resize handle；
6. Laser；
7. Pointer/default。

### 9.2 映射与生命周期

- 作者对象的 N/S、E/W、NE/SW、NW/SE 与 card HANDLE_CURSORS 语义一致。
- 如需共享，抽到最小 owner helper；不要复制第二张常量表。
- Pointer 和 Laser 都在 hover handle 时显示 resize cursor。
- press 后锁定按下 handle，指针离开 handle 仍保持到 release/cancel。
- release 后立即按当前位置重新解析，恢复 hover resize、Laser 或 default。
- selection change、对象删除、页面切换、mode change、leave、teardown 清理锁定态。
- 不用定时器、额外 repaint、raise 或透明 overlay 维持 cursor。

测试：

- tests/ui/test_ultraview_author_tools.py：八个 handle、Pointer/Laser、hover→press→move outside→release、各 reset、pan/forbidden/create 优先级。
- tests/ui/test_ultraview_author_chrome.py：Laser popup 选择不改变 resize 语义。
- 触及 canvas/backref 时加 tests/ui/test_pg_canvas_backref_invariants.py。

### W5 Gate

- [ ] Mouse 和 Laser 均有八向 resize cursor。
- [ ] drag 期间不闪回 Laser/default。
- [ ] 所有退出路径清理 cursor 状态。

---

## 10. G-LASER — 阻断式产品决策门

### 10.1 交互式 A/B/C HTML

创建：

docs/analyzer/ui-prototypes/2026-08-23-ultraview-laser-cursor-options.html

同一页展示三个方案：

- Pointer popup 菜单态：default、hover、selected；
- 真实 cursor 尺寸的 1× 与 2× 预览；
- 浅色画布、深色图表、密集网格背景；
- 中心 hotspot 十字；
- 方案说明和明确 A/B/C 选择按钮；
- 不改变现有页面左上区域和 rail 布局。

| 方案 | 核心直径 | 光晕直径 | 性格 |
|---|---:|---:|---|
| A | 6 px | 14 px | 克制、精确 |
| B | 8 px | 20 px | 平衡，默认推荐 |
| C | 10 px | 26 px | 强可见性 |

所有方案都表达发光圆点或光斑；禁止重新引入箭头、钢笔或斜向光束。

### 10.2 决策规则

- 把 HTML 交给用户并明确询问 A/B/C。
- 用户未选择时保持 BLOCKED ON PRODUCT DECISION。
- 不得因为 B 是推荐项而自动实施 B。
- 将选择结果、日期和用户原话摘要写入 prototype 顶部或同目录 decision note。

---

## 11. W6 — 用户选定的 Laser 图标与真实光标

仅在 G-LASER 通过后执行。

- ui_kit/icons.py 中的 ultraview_author_laser 使用选定的发光圆点视觉。
- laser_cursor.py 使用同一核心/光晕比例，不做另一套插画。
- hotspot 位于视觉中心，并有 1×/2× DPR 测试。
- 保留 cursor cache、screen/DPR change、reset 和 teardown 生命周期。
- Laser 只改变 cursor 外观，不改变选择、拖动、缩放、滚轮和 hit routing。
- Pointer popup 文案、tooltip、quickref/hints 与真实视觉一致。
- 扩展 tools/verify_ultraview_visuals.py；有意替换旧 32×32、(25, 5) 断言。

测试：

- tests/ui/test_ultraview_icons.py
- tests/ui/test_ultraview_author_chrome.py
- tests/ui/test_ultraview_author_tools.py
- tests/ui/test_hints.py
- tests/ui/test_quickref.py
- tests/test_verify_ultraview_visuals.py

### W6 Gate

- [ ] 实现与用户选择完全一致。
- [ ] 菜单图标、真实 cursor、DPR 和 hotspot 一致。
- [ ] Laser 行为仍仅是 cursor 外观变化。

---

## 12. W7 — 自动验证、视觉证据与真实 Cocoa 验收

### 12.1 Focused tests

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_ultraview_author_style.py tests/ui/test_ultraview_author_chrome.py tests/ui/test_ultraview_selection_toolbar_contract.py tests/ui/test_ultraview_author_multiselect.py tests/ui/test_ultraview_author_tools.py tests/ui/test_ultraview_author_geometry.py tests/ui/test_ultraview_sticky_slice.py tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_floating_chrome_controller.py tests/ui/test_ultraview_icons.py tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_verify_ultraview_visuals.py
~~~

按实际触点补 boundary gates：

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py tests/ui_kit/test_qss_border_shorthand.py
~~~

触及 canvas/backref 再加：

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_pg_canvas_backref_invariants.py
~~~

### 12.2 视觉 harness

扩展现有脚本并运行：

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python tools/verify_ultraview_visuals.py --output .state/ultraview-author-chrome-product-fixes
~~~

证据至少包含：

- Sticky、Text、Shape、Draw、Line、Arrow toolbar；
- W1 色块及 transparent；
- W2 每类 picker；
- format picker 上下翻转与边缘 clamp；
- Layout scrollbar 和右侧留白；
- Pointer/Laser 菜单；
- 八向 hover/drag cursor 状态记录。

若脚本尚无 --output，允许为现有 harness 增加等价的确定性输出参数；不得另建重复脚本。

### 12.3 稳定快照与扩大范围

每个测试阶段前后记录 HEAD、git status --short 和计划内文件 diff/hash；测试期间相关文件变化时结果为 UNVERIFIED。

- 默认不先跑 full suite。
- focused/boundary 通过后，可跑 tests/ui/test_ultraview_*.py 作为集成 gate。
- 只有 release/merge acceptance、跨边界大改或用户明确要求时才跑 full suite。
- 如确需 full suite，主 suite 忽略 tests/acquisition_ui，再用新进程顺序运行 acquisition suite；同一稳定里程碑只跑一次。

### 12.4 真实 macOS Cocoa / 前台 TraceLab

启动：

~~~bash
./.venv/bin/python -m mf4_analyzer.app
~~~

分别在全新 board 和 222.tlproj（可用时）执行：

| ID | 验收动作 | 必须观察 |
|---|---|---|
| C01 | Sticky/Draw/Shape/Text 切换颜色 | toolbar 与 picker 一致；ink 不为黄色误判 |
| C02 | 选择透明 fill | 白底红斜线可辨，实际对象透明 |
| C03 | 逐类打开格式 picker | 图形预览正确、宽度合理、文字不截断 |
| C04 | 在 viewport 各边缘打开 picker | 与 toolbar 可见边框始终有至少 6 px 间距 |
| C05 | 打开 Layout 并滚动 | 右侧留白存在、无横向滚动、缩略图未缩窄 |
| C06 | Sticky 四角慢速跨吸附阈值 | 进入/退出稳定，badge/蓝框/落点一致 |
| C07 | Sticky 边中点、修饰键缩放 | 不误吸附；旁路即时生效 |
| C08 | Pointer 下 hover/drag 八个 handle | 方向正确，拖动保持到 release |
| C09 | Laser 下重复 C08 | resize 优先于 Laser，release 后恢复正确 |
| C10 | pan/create/禁止放置与 resize 冲突 | 优先级符合第 9.1 节 |
| C11 | Popup 查看用户选定 Laser | 菜单图标与 cursor 一致，hotspot 在中心 |
| C12 | 快速切页/模式、删对象、关页面 | 无残留 cursor/浮层、闪烁或 chart whiteout |

viewport 至少覆盖 800×560、1280×800、1440×900。记录 PASS/FAIL/UNVERIFIED/UNAVAILABLE 和截图/短视频路径。222.tlproj 不可用时标记 UNAVAILABLE，不能伪造通过。

---

## 13. Git、提交与回滚纪律

- 每波只 stage 该波计划文件、源码、测试和必要文档。
- 提交前执行 git status --short、git diff --check、git diff --name-only --cached。
- 不纳入计划外脏文件，不删除用户现有修改，不 push，除非用户另行要求。
- 推荐提交边界：
  1. W1–W2：color semantics + picker presentation；
  2. W3：toolbar cleanup + sticky snap；
  3. W4–W5：overlay geometry + resize cursor；
  4. W6：approved Laser visuals；
  5. W7：verification docs/harness finalization。
- 某波失败时只撤销该波自有改动，不用 git reset --hard 或 git checkout 清理共享工作树。
- 完成前按 project-lessons 检查是否出现新的重复失败模式；已有 lesson 足够时记录“无新增 lesson”。

---

## 14. Definition of Done

### 产品行为

- [ ] 颜色 role 显式，toolbar/picker 共用解析。
- [ ] transparent 是白底红斜线，不是假白色。
- [ ] picker presentation matrix 全覆盖，font/size 宽度收敛。
- [ ] Sticky shape、Text link、toolbar duplicate 入口已移除。
- [ ] 旧字段、Cmd/Ctrl+D、复制/粘贴和撤销仍兼容。
- [ ] Sticky 四角 square snap 满足阈值、滞回、旁路和 preview=commit。
- [ ] format picker 真实可见 gap 至少 6 px，且无无依据定位改动。
- [ ] Layout 面板有 scrollbar-aware 右侧留白。
- [ ] Pointer/Laser 下八向 resize cursor 和生命周期正确。
- [ ] Laser 有用户明确选型记录，图标、cursor、hotspot、DPR 一致。

### 工程与证据

- [ ] W0 inventory 完整，工作树隔离清晰。
- [ ] focused tests 通过。
- [ ] applicable boundary gates 通过。
- [ ] 视觉 harness 通过并留存 .state 证据。
- [ ] Cocoa C01–C12 通过或如实标记未验证。
- [ ] 测试前后快照稳定。
- [ ] git diff --check 通过。
- [ ] 文档、hints、quickref 与真实入口一致。
- [ ] lesson 状态已检查。

| 缺失项 | 最高可报告状态 |
|---|---|
| G-LASER 未选择 | BLOCKED ON PRODUCT DECISION（仅 W6/W7 Laser 部分） |
| focused/boundary 失败 | FAIL / NEEDS REVISION |
| 只有 offscreen/脚本证据，无 Cocoa | PARTIAL / NEEDS FOREGROUND VERIFICATION |
| 测试期间相关文件变化 | UNVERIFIED |
| 全部 DoD 满足 | PASS / COMPLETE |

---

## 15. 执行 Agent 的首个动作

1. 完整阅读本计划、当前 AGENTS.md、CLAUDE.md 的共享产品约束，以及第 4 节触点的现状 diff。
2. 用 lessons selector 只加载 rounded popup、selection chrome、feedback/cursor 生命周期相关 lesson。
3. 创建 W0 inventory，记录当前工作树指纹并列出旧断言。
4. 从 W1 的失败测试开始；不要从 Laser 绘图或 Page/overlay 大改开始。
5. 完成 W1–W5 后创建 G-LASER HTML，向用户请求 A/B/C 选择并暂停 W6。
6. 得到选择后完成 W6、W7；按第 14 节状态上限汇报，不用测试绿替代 Cocoa 证据。
