# UltraView Miro 对标操作与 UI 恢复 Spec

- 日期：2026-08-20
- 状态：**READY FOR REVIEW — DOCS ONLY；未授权修改产品源码**
- 配套 Plan：`../plans/2026-08-20-ultraview-miro-operation-ui-restoration-plan.md`
- 视觉/交互基线：`../ui-prototypes/2026-08-19-ultraview-authoring-tools-prototype.html`
- 数据与对象基线：`2026-08-15-ultraview-annotation-notes-arrows-spec.md`
- 当前施工基线：branch `codex/ultraview-authoring-tools`，HEAD `14ef0c17`

## Supersedes

本文只在**操作逻辑和 UI chrome**范围内取代以下文档中的冲突结论：

- `2026-08-20-ultraview-miro-authoring-experience-spec.md` 中将 08-19 HTML 判为 rejected、
  将 Connector 拆成独立 rail 入口、给 Card 显示 selection toolbar、取消既有渐变的部分；
- `2026-08-20-ultraview-authoring-chrome-contract-recovery-spec.md` 中 T2/T3 的 Card toolbar、
  §6 删除 active gradient token 的部分；
- 对应 Plan 中任何继续实现上述冲突方向的 Task。

以下合同继续有效，不在本文重写：对象 DTO、identity、history、save/reopen、Fit/overview/export、
micro-grid、resize/ghost、preview capture、性能预算和错误分类。

> 这不是重新发明 UltraView。本文只恢复已认可的 08-19 HTML 操作节奏、已存在的 Card hover
> 操作和 `c80f46e0` 的钛蓝琥珀按钮状态，并把 Miro 参考图翻译成可验收的 PyQt 界面合同。

## 0. 本轮七条硬裁决

| 编号 | 裁决 | 验收含义 |
|---|---|---|
| U1 | 有子选项的左侧工具，**单击即弹出贴着按钮的选项层** | Sticky / Shapes / Draw 不再点击后只切状态或弹空壳 |
| U2 | **单击作者元素后**显示该元素的上下文属性栏 | 属性栏跟随对象，不常驻、不钉死、不跨对象显示 |
| U3 | UI **图标优先、少文字** | 属性动作不用“类型/填充/描边/线宽/锁定”等文字按钮墙 |
| U4 | 恢复 UltraView 已定的**钛蓝→琥珀渐变状态** | 以 `c80f46e0` 为最后正常基线，不设计第三套颜色逻辑 |
| U5 | View/Card 恢复**鼠标经过时右上角图标** | Card 不再进入作者属性栏；既有 hover/focus/常驻偏好是唯一入口 |
| U6 | 08-19 HTML 恢复为**操作与视觉参考基线** | 08-20 offscreen 结果不能再作为已认可目标 |
| U7 | 已定的 UltraView 面板内容不变 | 不删除、不改名、不迁移 Board / Library / Layout / Filter / Unplaced / Sync / Global / Nav 的功能 |

任一实现若违反 U1–U7，即使 focused tests 绿色，也不能进入前台验收。

## 1. 事实基线与当前偏差

### 1.1 已认可 HTML 的实际行为

已在本地浏览器实际操作 08-19 HTML，而不是只读源码：

- 点击 `N`：在按钮右侧出现 4×4、16 色便签色板，底部为 `Stack` 连续放置；
- 点击 `S`：出现线、箭头、折线箭头、块箭头和基础形状的同层清单；
- 点击 `P`：出现 Pen / Highlighter / 整笔 Eraser、三档线宽和颜色；
- 点击 `T`：进入文字创建/选择语义，选中文字对象时显示贴着对象的格式栏；
- creator rail 只决定“接下来在画布上做什么”，对象格式不塞回 rail；
- View 卡片仍保留自己的标题、类型与右上角动作，不借作者属性栏管理。

浏览器量取的主要几何是：

| 部件 | 08-19 HTML 实际值 | 本文产品目标 |
|---|---:|---:|
| creator rail | 64 px 宽 / 15 px radius | desktop 64 px；compact 52 px |
| rail tool | 50×46 px / 10 px radius | desktop 46×46；compact 40×40 |
| Sticky flyout | 262×350 px / 16 px radius | 260–272 px 宽；按内容高 |
| Sticky swatch | 53×53 px | 48–52 px，4×4 |
| Stack action | 236×37 px / 9 px radius | 满宽 36–40 px 高 |
| Text toolbar | 501×48 px / 12 px radius | 单行 48 px；按能力收缩 |
| toolbar control | 38 px 高 | 36–38 px hit target |

这些尺寸是方向基线，不要求机械复制 HTML 的 demo 外壳；PyQt 最终以真实 stage safe rect 和
800×560 可用性为准。

### 1.2 当前产品证据

当前 offscreen 证据显示：

- `selected-card-toolbar.png` 给 View/Card 加了一条 `TIME / 打开源 / 同步 / 聚焦 / Card Fit /
  复制图 / …` 的大文字栏；Card 自己右上角同时仍有图标，形成重复入口；
- `selected-shape-toolbar.png` 用 `SHAPE / 类型 / 填充 / 描边 / 线宽 / 线型 / 圆角 / 文字 /
  复制 / 锁定 / …` 占满一整行，而且位置可落到窗口底部；
- `sticky-flyout.png` 是 28 px 小色块 + “固定连续创建”文字按钮，密度和认可 HTML/Miro 都不一致；
- 当前 `SelectionToolbar` 为每个控制创建文字 `QToolButton`，问题不是字体微调，而是呈现模型错误。

证据路径：

- `../verify/2026-08-20-ultraview-chrome-recovery/selected-card-toolbar.png`
- `../verify/2026-08-20-ultraview-chrome-recovery/selected-shape-toolbar.png`
- `../verify/2026-08-20-ultraview-chrome-recovery/sticky-flyout.png`

### 1.3 源码与提交证据

- `widgets.py:1757-1838` 的 `_CardActionBar` 已有 Open / Focus / Fit / Remove / More 图标；
- `widgets.py:2045-2065` 已有 hover / focus / “常驻显示卡片操作”投影；
- `widgets.py:2335-2366` 已有 enter/leave/focus 生命周期，因此恢复 Card 行为不是新造组件；
- `page.py:4206-4267` 把 Card 和 author selection 一起送进 `_selection_toolbar`，这是需要切断的
  错误投影；
- `author_chrome.py:821-1058` 以文字创建属性按钮，是“属性栏都是文字”的直接来源；
- `c80f46e0 fix(ultraview): unify active panel gradients` 定义的最后正常 token 为
  `#3C8495 → #F0A44C`，hover 为 `#2F7181`；
- `14ef0c17` 将 `modeActive`、`panelOpen`、两者组合和 empty CTA 改为 tint/solid；当前未提交样式
  又准备删除 `UV_RAIL_ACTIVE_*` token。本文明确停止该方向。

## 2. 范围和不改范围

### 2.1 本文允许改

- 左侧 rail 中作者工具的图标、分组、active 状态和 anchored flyout；
- 作者对象选中后的上下文属性栏；
- Card/View 的 hover action projection；
- UltraView rail/global/presentation 的既有渐变状态恢复；
- 1280×720 与 800×560 的 chrome 几何、clamp、overflow；
- 对应 hints、quickref、help 和 focused tests。

### 2.2 本文禁止改

- Board Island 的板名、切换、新建内容；
- View Library 的来源、分组、拖放和 Add/Remove 语义；
- Free Grid、Layout、Filter、Unplaced、Sync 的功能与顺序；
- Global Island 的 Display / Export / Presentation 功能；
- Navigation Island 的 overview、zoom、Fit、1:1；
- Card 的标题、类型 chip、source/status/footer、preview 内容；
- author object DTO、schema、history、save/reopen、export、overview、Fit；
- Connector/Stroke 等已经保存的对象类型和数据；
- 任何 Analyzer compute、源 View 参数或 preview recapture 逻辑。

“S 中合并形状与连接线入口”只改变访问组织，不删除 Connector 能力、快捷键或持久化对象。

## 3. 体验方向

### 3.1 一句话

**左边选工具，旁边选变体，画布上选对象，旁边改属性。**

用户不需要先理解 Page、capability resolver 或对象类型。每一层只做一件事：

```text
左 rail                 贴 rail 的 flyout                 贴对象的属性栏
┌────┐                  ┌──────────────┐                  ┌───────────────┐
│ N  │ -- 单击 -------> │ 16 色 + Stack │ -- 创建/选中 --> │ 色块  对齐  锁 │
│ T  │ -- 激活文字 -------------------------------------> │ 字体 14 B …   │
│ S  │ -- 单击 -------> │ 线/箭头/形状  │ -- 创建/选中 --> │ ◇  ●  ━  ⌜  … │
│ P  │ -- 单击 -------> │ 笔/高亮/擦/套索│ -- 创建/选中 --> │ ✎  ●  ━  🔒  …│
└────┘                  └──────────────┘                  └───────────────┘

View/Card：hover -> 卡片右上角原有图标；不进入作者属性栏。
```

### 3.2 唯一品牌签名

UltraView 的唯一高识别品牌动作是**钛蓝→琥珀 active/panel 渐变**。不再用 `TIME / FFT / SHAPE /
INK` 等大写文字作为第二个“签名元素”。分析类型已经存在于 Card type chip；作者对象用首图标即可识别。

属性栏、flyout 和 rail shell 本身保持安静：白/浅钛 surface、细边框、克制阴影。大胆只花在已定的
渐变状态上，避免每个控件都抢注意力。

## 4. 左侧工具与 flyout 操作合同

### 4.1 rail 固定内容与作者段

现有板级入口保留原顺序。作者段只调整入口组织：

1. Select — `V`
2. Sticky — `N`
3. Text — `T`
4. Shapes & Connectors — `S`（含 `L` 直线/箭头快捷路径）
5. Draw — `P`（Pen / Highlighter / whole-stroke Eraser / Lasso）

不再在 rail 上为 Connector 再占一个永久按钮。`L` 仍可直接激活最近使用的线型，也可从 `S`
flyout 选择；已有 connector 功能和对象完全保留。

作者按钮只显示图标。快捷键进入 tooltip，例如“形状与连接线 (S)”，不在 46 px 按钮里常驻字母。

### 4.2 哪些按钮弹选项

| 入口 | 单击行为 | 例外/原因 |
|---|---|---|
| Select | 激活选择；关闭作者 flyout | 没有可选变体，不弹空层 |
| Sticky | 激活并打开 Sticky palette | 必须先看见颜色/Stack |
| Text | 激活文字创建 | 没有创建前必选项，不弹空层；属性在对象被选中/编辑后出现 |
| Shapes | 激活最近使用项并打开 Shapes flyout | 同层选择线、箭头和形状 |
| Draw | 激活最近使用项并打开 Draw flyout | 选择笔/高亮/擦除/套索、宽度、颜色 |
| 既有 panel 按钮 | 保持现有 panel 内容并打开 | Library/Layout/Filter 等不迁移、不改内容 |

原则是“有选项就弹，无选项不造空盒”，不是机械要求每个按钮都弹相同面板。

### 4.3 通用 flyout 生命周期

- flyout 左缘与 rail 右缘间距 8 px；优先让 flyout 顶部与触发按钮顶部对齐；
- 上下越界时整体 clamp 到 stage safe rect，不能覆盖底部 Navigation Island；
- 同时只允许一个作者 flyout；打开新的会关闭旧的；
- 第二次点 active 工具只切换 flyout 开/关，不取消 active tool；
- 点击 flyout 内选项：更新当前变体；one-shot 工具保留到成功创建；连续工具保持 active；
- 点击画布空白只关闭 flyout，不自动取消当前工具；
- `Esc` 顺序：editor → draft → flyout → active tool 回 Select；
- Board switch、Overview、Presentation、Template mode：关闭 flyout、取消 draft、回 Select；
- flyout 是非模态 `QFrame`，不得退回平台 `QMenu` 文本长列表；
- shell 使用 `Qt.WA_TranslucentBackground` + 内层圆角 surface，四角不能出现矩形 backing。

### 4.4 Sticky flyout

- 260–272 px 宽，12 px 内距，16 px radius；
- 4×4 的 16 色 swatch；每块 48–52 px，8 px 间距；
- swatch 不显示颜色名字；tooltip/accessibility 提供名字；
- 当前色用 2 px selection ring + 2 px 内白间隔，不用文字“已选择”；
- 底部只保留一枚满宽 `Stack` action，图标 + 最多“Stack”一个短词；
- 不加入 Miro 的 Generate/AI；不改变现有 Sticky palette token 或保存字段；
- 选色后进入单次放置；Stack 进入连续放置；成功创建后单次模式回 Select。

### 4.5 Shapes & Connectors flyout

flyout 参考用户 Miro 图 #3 和认可 HTML：同一层完成“画什么”的选择，不进二级菜单。

第一组（连接）：Line、Arrow、Elbow Arrow；Block Arrow 只有在当前 renderer/DTO 已完整支持时才显示，
否则不放假入口。

第二组（闭合形状）：Rectangle、Rounded Rectangle、Oval、Rhombus、Triangle。

- 每行 = 20–24 px 真实图标 + 最多 4 个汉字的名称 + 右侧快捷键；
- 不显示解释句、“简化”“更多形状”“即将推出”；
- 选中项使用浅蓝 wash，整个 flyout 仍是中性 surface；
- 形状和 connector 的状态机仍分开，只共享入口 surface；
- 选择后 one-shot；pin/双击工具可连续创建；
- `L/R/O` 等快捷键可以直达，但 tooltip/quickref 必须与真实能力一致。

### 4.6 Draw flyout

参考用户 Miro 图 #1：工具选择靠图标和真实笔触预览，不靠多段说明文字。

- 第一行：Pen、Highlighter、Eraser、Lasso 四枚 40–44 px 图标；
- 第二行：细/中/粗三枚真实线宽 preview，不写“线宽 1/2/4”；
- 第三行：5–8 个圆形颜色 swatch；
- Eraser tooltip 明确“整笔擦除”，但 flyout 不常驻“不做像素擦除”的解释句；
- Lasso 只选择，不 dirty；完成后回 Select；
- Pen/Highlighter/Eraser 持续 active，直到 `V` / `Esc` / 切换工具；
- 不增加 pressure、precision eraser、AI cleanup 等未实现能力。

## 5. 作者对象上下文属性栏

### 5.1 出现条件

- 单击一个 author object 后出现；
- 同类多选时出现可共同编辑的属性；
- 异类 author 多选时只显示共同动作；
- selection 中只要包含 View/Card，作者属性栏就隐藏；
- 未选对象、仅框选空白、Overview、Presentation、Template mode 时隐藏；
- 拖动/resize/draft 期间隐藏，release 后只重新定位一次；
- editor 正在输入时保留与该 editor 有关的格式，不抢 IME/快捷键。

### 5.2 几何

- 高 48 px，4 px 内距，12 px radius；
- 控件高 38 px，图标 20–22 px；
- 默认位于 selection bounds 上方 8 px；上方不足时放下方 8 px；
- X 方向 clamp 到 stage safe rect，左边避开 rail 12 px，右边留 12 px；
- 工具条宽度按该对象真实能力收缩，不设置无意义的 220 px 最小宽；
- 800×560 保持单行；低优先级动作进入 `⋯`，不换行、不落到窗口底边之外；
- 不使用 `y=56`、固定窗口底部或 page 中心作为正常定位。

### 5.3 图标优先规则

属性栏里只允许三类可见文字：

1. 用户正在编辑的真实值：字体名、字号 `14`、zoom/数值；
2. 文本格式的传统单字符图标：`B / I / U`；
3. 无成熟图标且不显示会误操作的极短值，最长 4 个汉字，并需单独评审。

禁止常驻文字按钮：`TIME`、`FFT`、`SHAPE`、`INK`、`类型`、`填充`、`描边`、`线宽`、
`线型`、`圆角`、`文字`、`复制`、`锁定`、`打开源`、`同步`、`聚焦`、`Card Fit`。

所有 icon-only 控件必须有中文 tooltip、accessibleName 和 keyboard focus ring。

### 5.4 各元素属性矩阵

| 元素 | 左到右主控件 | `⋯` 中的低频动作 |
|---|---|---|
| Sticky | sticky shape icon、palette swatch、字号值、align icon、lock icon | Duplicate、Delete、z-order |
| Text | `T` icon、字体名、字号、B/I/U、align、list、link、text color、fill、lock | Duplicate、Delete、z-order |
| Shape | shape preview、fill swatch、stroke swatch、width preview、dash icon、corner icon、text icon、lock | Duplicate、Delete、z-order |
| Connector | route icon、start/end head icons、color swatch、width preview、dash icon、label icon、lock | Duplicate、Delete、z-order |
| Stroke | pen/highlighter icon、color dot、width preview、lock | Duplicate、Delete、z-order |
| 同类多选 | 共同值；不一致显示空心/斜杠 indeterminate 图形 | align、distribute、Delete |
| 异类 author | move/duplicate/lock 的图标；不显示危险的批量 style | align/distribute/Delete（仅能力允许） |

属性按钮点击若存在多个值，必须打开对应的小型 anchored chooser，不得“每点一次轮询下一个值”。

## 6. View/Card 恢复合同

### 6.1 默认行为

View/Card 不是作者元素，不显示 Selection Toolbar。单击仍可选择/移动/多选卡片，但属性栏保持隐藏。

鼠标进入 Card 或 Card 获得键盘焦点时，右上角显示既有 `_CardActionBar`：

1. Open source
2. Focus
3. Card Fit（仅 Free Grid；compact 时可收进 More）
4. Remove from Board
5. More

全部为图标，解释只在 tooltip。Stale 时既有 Sync 状态入口继续按当前卡片合同显示，不迁入属性栏。

### 6.2 常驻偏好与 compact

- 默认 `show_card_actions=false`：只在 hover/focus 出现；
- 用户已有“常驻显示卡片操作”偏好时始终显示；本文不删、不改名该偏好；
- TITLE_ONLY / 窄 Card 优先隐藏 Fit，再由 More 收纳低频动作；Open / Focus / Remove / More 不重叠；
- Presentation 模式隐藏 action bar；
- 从 action button 移出时，焦点仍在按钮内则不能突然关闭；
- 不新增第二套 Card action signal；继续使用 Card/Page 既有信号。

### 6.3 混合选择

Card + author 混选只保留 selection outline 和键盘允许的共同移动/删除语义，不显示作者属性栏，
也不显示 Card 属性栏。用户需要改作者格式时，应先形成纯 author selection。

## 7. 视觉系统

### 7.1 色彩角色

继续使用 `ultraview_style.py` 的 Titanium Amber，不引入平行 `uvx.*` palette：

| 角色 | 值 | 用途 |
|---|---:|---|
| surface | `#FFFEFD` / 既有半透明 surface | rail、flyout、toolbar |
| ink | `#183039` | 主图标/文本 |
| muted | `#66787E` | 次级图标/shortcut |
| selection | `#4262FF` | author active、selection、handle、focus |
| active start | `#3C8495` | 既有 panel/mode gradient 起点 |
| active end | `#F0A44C` | 既有 panel/mode gradient 终点 |
| active hover | `#2F7181` | active hover/pressed |
| warning/danger | 既有 token | 只表达状态/危险，不参与普通 active |

### 7.2 渐变状态矩阵

必须按最后正常基线 `c80f46e0` 恢复，不靠近似色：

| 控件状态 | 背景 | 图标/文字 |
|---|---|---|
| 普通 idle | transparent | muted |
| 普通 hover | surface tint | brand deep |
| author tool active | `#EEF1FF` selection wash + 2 px blue indicator | `#4262FF` |
| `modeActive=true` | `#3C8495 → #F0A44C` | white |
| `panelOpen=true` | `#3C8495 → #F0A44C` | white |
| mode + panel | 同一渐变，不叠第二层 | white |
| 上述 hover/pressed | `#2F7181` | white |
| empty View Library CTA | `#24697C → #E58F32` | white |
| Presentation exit island | 继续 `#24697C → #E58F32` | white |

这里故意把“作者鼠标工具 active”和“既有 panel/mode active”分开：前者沿用 Miro 的蓝色选择语法，
后者恢复 UltraView 已定的钛蓝琥珀品牌语法。不得再把 panelOpen 改成中性 wash，也不得把所有 author
工具都刷成渐变。

### 7.3 surface、图标和文字

- rail desktop 64 px、compact 52 px；desktop target 46×46、compact 40×40；
- rail icon 22 px，2–2.2 px 统一 stroke；不得混用 Unicode 方块、文字缩写和不同重量图标；
- flyout 16 px radius；toolbar 12 px；tool 10 px；
- surface 使用 96–100% opaque 或项目既有透明 material，不新增 macOS-only blur 依赖；
- 阴影只一层，建议 `0 8 24 rgba(24,48,57,.14)` 等效值；不做大面积光晕；
- UI 字体继续项目 CJK fallback；快捷键只在 tooltip/菜单右侧；
- 主要可点击目标 desktop ≥40 px，compact 不低于 36 px；
- color swatch、line width preview、shape preview 必须画真实结果，不用文字代替。

## 8. 键盘、焦点和可访问性

- `V/N/T/S/P/L` 在非文本输入焦点下可用；
- editor/IME composition 期间 Board 不拦截字母、Enter、Esc、Cmd/Ctrl；
- `Tab` 能进入当前可见 action；隐藏的 Card action 不留幽灵焦点；
- icon-only button 必须有 tooltip + accessibleName；
- focus 用 2 px selection ring，不能只改颜色；
- Reduce Motion 下 flyout/toolbar 直接出现；普通模式最多 100–120 ms opacity/4 px translate；
- light 普通文字对比 ≥4.5:1，图标/边界 ≥3:1；
- tooltip 自动向画布内侧翻转，不越过窗口。

## 9. 状态机

| 当前状态 | 事件 | 下一状态 | 可见 UI |
|---|---|---|---|
| Select | 点 N/S/P | 工具 active + flyout open | rail active blue + anchored flyout |
| flyout open | 选变体 | 工具 armed | flyout 可关闭；cursor/active 保持 |
| one-shot armed | 成功创建 | Select + new object selected | 新对象属性栏出现 |
| one-shot armed | Esc | Select | flyout/draft/属性栏按 selection 状态收敛 |
| Draw active | pointer up | Draw active + Stroke selected/可继续画 | flyout 关；必要时显示 Stroke 属性栏 |
| 任意工具 | 点 author object | Select + author selected | 对应 icon-first 属性栏 |
| 任意工具 | hover Card | 状态不变 | Card 右上角原有图标出现 |
| Card selected | click / keyboard | Card selected | selection outline；无属性栏 |
| author dragging | move | gesture active | 属性栏隐藏 |
| author release | release settle | author selected | 属性栏按最终 bounds 定位一次 |

## 10. 验收场景

### A1 — Sticky

点 `N` → 右侧出现 4×4 大色块 → 选颜色 → 点击画布创建 → 自动回 Select → 单击便签 →
只出现 icon/swatch 属性栏。过程中没有“固定连续创建”大段文字；Stack 可用且不改 palette 数据。

### A2 — Shape / Connector

点 `S` → 同层看到 line/arrow/elbow 与基础闭合形状 → 选 Rectangle 并拖拽创建 → 单击后属性栏
显示真实 shape/fill/stroke/width/dash/corner 图形；再按 `L` 可直接拉线。无独立 Connector rail 占位，
无功能损失。

### A3 — Text

点 `T` → 点击/拖宽 → CJK 输入 → 退出编辑 → 单击文本 → 48 px 单行工具条贴在文本上方；
可见文字只含字体、字号和 B/I/U，其他是图标/色块；compact 使用 `⋯`。

### A4 — Draw

点 `P` → 图标选择 Pen/Highlighter/Eraser/Lasso → 真实线宽 preview → 颜色 swatch → 连续绘制；
`Esc` 回 Select；选中 stroke 后用图标栏改笔种/颜色/宽度。Eraser 不出现像素擦除假能力。

### A5 — View/Card

空闲时 Card 无大属性栏 → 鼠标移入时右上角图标出现 → Open/Focus/Fit/Remove/More 各执行既有路径
→ 鼠标移出后隐藏；打开“常驻显示卡片操作”后持续显示。单击 Card 仍无作者属性栏。

### A6 — 渐变

依次打开 Library、Layout/Filter、Free Grid 或其他既有 mode、empty-board CTA、Presentation：
`modeActive/panelOpen` 回到钛蓝→琥珀，hover/pressed 为深钛蓝；author active 保持蓝色 wash。截图中
不能再出现全部 active 都是浅灰/浅蓝的扁平状态。

### A7 — 窗口与边界

1280×720 和 800×560 下：rail 内容完整、flyout 不越界、属性栏不换行、View hover 图标不重叠、
圆角四角没有矩形 backing。DPR 1×/2× 分别截图。

### A8 — 不改内容

Board / Library / Layout / Filter / Unplaced / Sync / Global / Nav 的入口数量、名称、命令 payload、
面板字段与顺序相对施工前完全一致。Connector/Stroke 旧项目保存重开不丢对象。

## 11. Definition of Done

必须同时满足：

1. U1–U7 全部通过；
2. accepted 08-19 HTML 的 N/S/P/T 关键手势在真实 PyQt 路径可复现；
3. View/Card 无 selection property toolbar，hover action 是唯一主入口；
4. 作者属性栏 icon-first，禁止词清单无残留可见文案；
5. `UV_RAIL_ACTIVE_START/END/HOVER` token 与对应 selector 有自动化护栏；
6. 既有面板内容和数据合同零变化；
7. focused/boundary tests 通过；
8. 1280×720 与 800×560 的 Cocoa 前台截图逐面与 08-19 HTML/Miro 参考对照通过；
9. Windows frozen 若未跑，必须明确 `WINDOWS UNVERIFIED`，不能写完成；
10. offscreen、HTML、Cocoa 和 Windows 证据分开记录，不互相替代。

## 12. 明确非目标

- 不复制 Miro 的 AI Generate、评论、协作、reaction、frame、diagram packs；
- 不重做 UltraView 既有 panel 内容；
- 不调整 Card preview 白底、capture profile、Card Fit solver 或 resize ghost；
- 不新增 dark 主题方向；
- 不新增对象 schema 或计算能力；
- 不用“更像 Miro”为理由引入大面积 blur、动画或通用白板功能。
