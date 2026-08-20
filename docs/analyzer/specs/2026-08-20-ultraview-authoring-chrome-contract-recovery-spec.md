# UltraView 作者工具 Chrome 合同恢复 Spec

- 日期：2026-08-20
- 状态：**CODE COMPLETE / FOREGROUND UNVERIFIED**
- 触发 Review：本日对 `a4d6c904..14ef0c17`（7 个作者工具提交）的源码级评审，结论 NO-GO
- 前置评审：`docs/analyzer/reviews/2026-08-19-ultraview-two-wave-regression-review.md`
- 体验基线：`2026-08-20-ultraview-miro-authoring-experience-spec.md`（其 §4–§7 合同仍有效，
  本 Spec 不改写它，只把「HEAD 实现与该合同的偏差」定为必须闭合的缺陷）
- 恢复基线：`2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`（R1 dead-affordance
  禁令与 R2 完成状态枚举在本 Spec 全文适用）
- 配套 Plan：`../plans/2026-08-20-ultraview-authoring-chrome-contract-recovery-plan.md`

## 0. 产品结论与为什么现在做

`14ef0c17` 把 Text / Shape / Connector / Draw 一次性接入 release rail，并在体验 Spec 顶部加
「M8 supersession」把 M0–M7 标记为已落地。但对照已签字的 08-20 prototype 与体验 Spec 逐条核查
HEAD 源码，**用户第一眼看到的 chrome 合同并没有落地**：

1. 选择工具条不跟随选区，钉死在画布顶部（体验 Spec §7.2 被违反）；
2. 选中卡片后工具条的主要按钮是空壳（08-19 Review 的 P0「断路入口」在新表面复发）；
3. Signal Spine 对所有卡片显示 `FFT`（体验 Spec §3.2 的唯一签名元素做错了）；
4. Select 工具点不中 Connector / Stroke，命中逻辑被 Page 旁路（恢复 Spec I1 单一 owner 被架空）。

这些不是打磨问题，是「测试绿 ≠ 界面可用」第三次复发：切片测试证明 intent 能 commit，
不证明 chrome 像 prototype。因此本 Spec 的范围**只有可见行为与命中路由**，不新增任何工具、
对象类型或视觉主题。

### 量化收益

- 消除 1 个 P0 + 6 个 P1 的确定性主路径缺陷（见 §1），全部可从「打开 UltraView → 选中一张卡」
  的 10 秒操作内复现；
- `page.py` 从 5711 行止涨并回落（W4 拆出指针路由后目标 ≤ 4700 行）；
- 新增的 chrome 几何断言把「工具条钉死 / flyout 空盒」这类回归从人工走查变成常驻聚焦测试。

## 1. 缺陷清单（本 Spec 的完成定义 = 全部闭合）

行号为 `14ef0c17` 快照；实施时以符号定位，不依赖行号。

| # | 级别 | 缺陷 | 证据 |
|---|---|---|---|
| D1 | P0 | 选择工具条钉死在 `y=56`、水平居中，不跟随 selection bounds，拖动中也不隐藏 | `page.py:5394-5402` |
| D2 | P1 | 卡片选择工具条 `open / sync / fit` 无 handler；`duplicate` 只走 author ids；卡片单选时 `delete` 无行为 | `page.py:4920-4976` · `page.py:5070-5108` |
| D3 | P1 | Signal Spine 对 card kind 固定显示 `FFT`，不读 `axis_kind` | `author_selection.py:69-77` |
| D4 | P1 | `SelectionToolbar.more_requested` 从未被 connect，`⋯` 是死入口；Delete 反而是常驻宽按钮 | `author_chrome.py:726,755`；`page.py:638` 只连了 `format_requested` |
| D5 | P1 | `_author_keys_at` 只认 `.box`，Connector/Stroke 点不中；Connector 靠 Page `eventFilter` 旁路命中，会在 Select 下偷走卡片点击 | `widgets.py:5159-5184` · `page.py:4478-4544` |
| D6 | P1 | 格式控件是静默枚举轮询（`next(enum)`），无色板/线宽选择器 | `page.py` 各 `_next_*_format` 消费路径 |
| D7 | P1 | `ToolFlyoutSurface.sizeHint` 写死 248×220，所有 flyout 带大块空白 | `author_chrome.py:71-72` |
| D8 | P1 | `panelOpen` / `modeActive` 的 hover 仍是钛蓝实心 + 白字，与 active tool 左条语义冲突（体验 Spec §6.1 禁止） | `style.qss:4672-4705` |
| D9 | P2 | 磨砂只改壳 alpha，预览 QImage 不透明白底仍在（08-19 Review P1 未闭合） | `ultraview_style.py:23` + 抓图路径 |
| D10 | P2 | `page.py` 单提交 +2186 行，Text/Shape/Connector/Draw 指针路由全堆在 Page `eventFilter`，单一交互 owner 名存实亡 | `page.py` 现 5711 行 |

## 2. 发布入口合同

### E1. Release rail 回收

在 D5（统一命中）闭合前，`RELEASE_AUTHOR_TOOLS` 回收到
`Select / Sticky / Text / Shapes`。Connector 与 Draw 的入口、快捷键、hints/quickref/help 条目
同步隐藏（沿用恢复 Spec R1：不保留「disabled + 即将推出」的假入口）。

- 隐藏必须走既有 `visible_author_tools` 通道，不删除已实现的 state/render/edits 代码；
- `ui/hints.py`、`ui/quickref.py`、`help/ultraview-guide.html` 与三者的契约测试
  （`test_hints.py` / `test_quickref.py` / `test_help_content.py`）同波同步；
- 已存项目里的 Connector/Stroke 对象**仍然渲染、仍可被删除**（经 selection toolbar 的通用动作），
  只是不能新建——不得让隐藏入口变成孤儿数据。

### E2. 状态枚举

沿用恢复 Spec R2。本 Spec 各波在 Cocoa 前台证据齐全前最高只能标
`CODE COMPLETE / FOREGROUND UNVERIFIED`。

## 3. 选择工具条合同（闭合 D1 / D2 / D3 / D4）

### T1. 定位

- 优先放在 selection bounds 上方 8 px；上方空间不足放下方 8 px；
- X 方向 clamp 到 stage safe rect（左缘避开 rail，右缘留 12 px）；
- 拖动 / resize / draft 进行中隐藏，release 后一次性重新定位（不逐帧跟随）；
- selection bounds 的来源：card 选择用 card widget geometry 的并集；author 选择用
  `author_content_bounds` 映射到像素；混选取两者并集；
- compact（Page 宽 < 900）行为保持既有 `set_compact` 溢出规则，不换行。

### T2. Signal Spine

- card 单选/多选同 kind：显示该卡 `axis_kind` 映射的大写标签
  `TIME / FFT / TF / FRF / ORDER`，色条用对应分析分类色（`ultraview_style.py` 的
  `time/fft/fft_time/frf/order`）；
- card 多选混 kind：显示 `CARD`，色条用 selection blue；
- author 对象：维持现状（`NOTE/TEXT/SHAPE/LINE/INK`，selection blue）；
- `resolve_selection_capabilities` 必须接收 axis kind 输入（由 Page 提供
  ref→axis_kind 映射），不得在 Qt-free 层猜测。

### T3. 卡片动作接线

card kind 的工具条控件全部接到 Page 既有信号，不新造第二条路径：

| 控件 | 行为 |
|---|---|
| 打开源 | `open_source_requested.emit(section, view_id)` |
| 同步 | `sync_requested.emit(section, view_id)` |
| 聚焦 | `_on_focus(section, view_id)`（现有 FocusLayer 路径） |
| Card Fit | `free_grid_autofit_requested.emit(section, view_id)`；模板布局下不显示 |
| 复制图 | `copy_card_image_requested.emit(section, view_id)` |
| 复制（duplicate） | card 无 duplicate 语义：card 单选时不显示该控件（capabilities 层修 `can_duplicate`），而不是显示后无行为 |
| 删除 | 单卡 = `remove_ref_requested`；混选维持 `SelectionDeleteIntent` |

多卡选择时 open/focus 不显示（无明确目标），sync 可对全部选中卡逐个发射。

### T4. More 与 Delete

- `more_requested` 接到一个锚定在 `⋯` 按钮下方的圆角菜单（复用
  `apply_rounded_menu_chrome`），内容 = 低优先级动作（Delete、z-order、对齐/分布在 compact
  下的溢出项）；
- Delete 从常驻宽按钮移入 More 菜单与键盘（体验 Spec §7.2「Delete 放 More 和键盘」）；
- 新增信号连接一律 bound method / `functools.partial`（`.connect(lambda` 棘轮只许缩小）。

### T5. Flyout 尺寸

- 删除 `ToolFlyoutSurface.sizeHint` 的固定 248×220；`popup()` 的 `adjustSize()` 按内容收紧；
- 每个具体 flyout 若需要最小宽度，在自己类内声明（Sticky 248 px、其余 284 px，
  与体验 Spec §5.3 一致），高度永远由内容决定。

## 4. 命中与路由合同（闭合 D5 / D10）

### H1. 单一命中入口

`FreeGridBoard.classify_press` 是**唯一**的 press 分类入口，覆盖全部五类 author 对象：

- box 类（Sticky/Text/Shape）：现有 box 命中；
- Connector：复用 `hit_connector` / `hit_connector_handle`（几何已在
  `author_geometry.py`，只是没进 `_author_keys_at`）；
- Stroke：复用 `stroke_hit_record`；
- 命中优先级维持恢复 Spec I3：editor → handle/anchor → author 逆 z → card → blank。

### H2. Page eventFilter 收缩

Page 的 `_handle_{text,shape,connector,draw}_board_event` 只允许在
「对应 tool 处于 armed」或「存在同 tool 的活跃 draft/geometry session」时拦截事件；
Select 工具下的对象选择（含 Connector/Stroke 单击、双击进 editor）必须走 H1 的分类结果，
不得再各自 `_connector_at` 抢先返回 True。

验收判据：Select 下单击一条穿过卡片的 Connector 选中 Connector；单击卡片未被线覆盖的区域
选中卡片——两个断言进同一个聚焦测试。

### H3. 双击分派

双击 author 对象按 kind 进入对应 editor（Sticky→sticky note、Text→text editor、
Shape→shape 内文字、Connector→label 编辑）。`FreeGridBoard.mouseDoubleClickEvent`
现在一律 `_begin_sticky_edit` 的行为废除。

### H4. Page 减脂方向

D10 的结构性修复（W4）：draft/geometry session 的状态迁入
`BoardInteractionController`，Page 侧收敛为一个薄的 pointer router（按 H2 的 armed 规则分派）。
本 Spec 不规定文件切分细节，但规定两条不变量：

- `page.py` 行数在 W4 出口 ≤ 4700 且此后作为 review 关注项不再回涨；
- 不新建第二个 selection/tool/draft 状态源（状态所有权棘轮照常看守）。

## 5. 格式控件合同（闭合 D6）

- 色板、线宽、形状类型、线型从「点击轮询下一个枚举值」改为「点击弹出选择器」；
- 选择器**复用**已有 flyout 部件（Sticky 色板网格、Shape cell 网格、Draw preset 行），
  锚定在工具条对应按钮下方，不新造平行控件；
- B/I/U、锁定等布尔控件保持 checkable 点击切换；
- 混选（`mixed` / `card_author`）只保留移动 / 复制 / 锁定 / 删除，去掉批量 style 轮询；
- `chrome.py` 中未接线的 `TextFormattingToolbar` 删除（scaffold 已被
  `SelectionToolbar` 的 text kind 取代，留着只会误导后续实现）。

## 6. Chrome 状态视觉合同（闭合 D8）

- `panelOpen` / `modeActive` 的 hover/pressed 不得使用品牌色实心填充 + 白字；
  改为中性 wash（`UV_SURFACE_SOFT` 级）+ 边框加深，保持与 idle hover 同族；
- active tool 的「selection wash + 2 px 左条」是唯一的强状态视觉，专属创作段；
- `UV_RAIL_ACTIVE_START/END` 渐变 token 若无剩余消费者则一并删除；
- QSS 改动过 `test_qss_border_shorthand.py` 白名单（只许缩小）。

## 7. 明确的非目标

- 不新增工具、对象类型、shape pack、dark 主题；
- 不处理 D9 的预览白底（那是 capture/render profile 层问题，另立 spec；本轮只禁止
  再叠加透明壳实验）；
- 不动 Card Fit solver、resize 帧合并、elastic workspace（08-19 恢复线已覆盖）;
- 不做 Cocoa 帧级性能测量（W5 只做前台视觉走查 + 截图对照）；
- 不改 `ultraview_state.py` 的持久化 schema。

## 8. 验收证据分级

沿用仓库既有分级，互不替代：

1. **聚焦 offscreen 测试**：每个缺陷至少一条以其复现路径命名的用例（见 Plan 各 Task）；
2. **offscreen 截图对照**：Page 级渲染 vs `2026-08-20-ultraview-miro-authoring` 决策截图的
   结构对照（工具条位置、flyout 收紧、Spine 文案），存
   `docs/analyzer/verify/2026-08-20-ultraview-chrome-recovery/`；
3. **Cocoa 前台走查**（W5）：真实 TraceLab + `testdoc/1.tlproj`，五张状态图
   （Select / Sticky flyout / 选中卡片工具条 / 选中形状工具条 / 800×560 compact）；
4. Windows frozen 不在本 Spec 范围，发版前按发布门另行执行。

offscreen 通过 + Cocoa 未跑 = `CODE COMPLETE / FOREGROUND UNVERIFIED`，不得写 Implemented。
