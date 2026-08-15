# UltraView 标注对象（文本便签 + 箭头）Spec

日期：2026-08-15 · 状态：**DRAFT，未授权执行**
配套 plan：`docs/analyzer/plans/2026-08-15-ultraview-annotation-notes-arrows-plan.md`
上游输入：
- `2026-08-14-ultraview-miro-narrow-rail-spec.md`（浮岛/画布结构合同）
- `2026-08-14-ultraview-p3-canvas-interaction-spec.md`（直接操纵状态机、视口变换、D2 视口持久化范式）
- 用户裁决（2026-08-15）：不做无限画布/QGraphicsView 重宿主；标注要「和 Miro 对齐」——
  **细吸附**（不是卡片的整格吸附）、样式、拖动指向（箭头端点锚定对象）。

## 0. 结论

UltraView 的 Board（自由网格模式）增加一层**标注对象**：文本便签（sticky note）
与箭头（connector）。它们是 Board 自身的作者内容，位于卡片之上的独立层，使用
**连续网格坐标 + 细吸附**（1/8 单元格 lattice + 智能对齐参考线），不占网格槽位、
不参与卡片碰撞。箭头端点可锚定到卡片或便签（Miro 自动边界锚），目标移动时箭头
跟随。标注进 Board 持久化（additive 字段）、进每板 undo 栈、进 PNG 导出与演示
模式。只读 / 零计算合同不变：标注不读不写任何源 View 与分析数据。

一句话定位：UltraView 的下游是汇报（演示 + PNG 导出），「在两张卡之间贴一句
结论、画一根指向」是对比工作流的收尾动作，这是本功能唯一服务的场景。

## 1. 为什么现在做

- P3 已交付视口变换与直接操纵，「画布感」到位，但对比结论只能存在用户脑子里
  或导出后进第三方标注工具；单卡截图标注已有 `ui/markup/` 出路，**板级**结论
  没有承载物。
- 窄轨改版后画布是页面主体，加一层轻量标注的边际成本（复用手势状态机、undo、
  持久化、导出管线）是历史最低点；再晚做，viewport / gesture 的接口每动一次
  都要多适配一次。
- 明确不做成通用白板：不加画笔、不加协作、不加无限画布——标注对象是**对比板
  的注释**，不是绘图工具（§2 非目标钉死，防范围爬行）。

## 2. 目标与非目标

### 2.1 目标

1. 便签：创建、移动、8 向 resize、双击改文字（中文 IME 可用）、6 色、删除。
2. 箭头：创建、两端点独立拖动、端点锚定卡片/便签（auto 边界锚）、随目标移动、
   删除；直线 + 实/虚线 + 单/双箭头。
3. 细吸附：1/8 单元格 lattice + 对齐参考线（对象边/中线，捕获 ±6 屏幕 px，
   参考线优先于 lattice），Alt 按住 = 完全自由。**卡片仍走整格**，P3 合同不动。
4. 全链路一致：屏幕（任意 zoom）、minimap 之外的导出 PNG 1×/2×、整板复制、
   演示模式，标注位置与样式一致（同一映射函数）。
5. 持久化 + undo：随项目保存；每板 undo 栈单条原子记录。
6. 状态诚实：锚定目标被移除时端点显式退化为自由点（toast），不静默悬空。

### 2.2 非目标

- 画笔手绘、任意多边形、图片贴纸、连接线文字标签（标签需求用「便签放在线旁」覆盖）。
- 折线/曲线自动路由（V1 直线；避障路由是 Miro 级路由器，成本远超收益）。
- 协作、评论、@（单机桌面软件）。
- 无限画布、QGraphicsView 重宿主（用户裁决 + P3 既有非目标）。
- 模板布局模式下的标注编辑（见 D5）。
- 标注对象间手动 z 序调整（V1 固定：后创建在上）。

## 3. 决策记录（默认裁决，用户可推翻）

| # | 决策 | 裁决 | 理由 |
|---|---|---|---|
| D1 | 坐标系 | **连续网格坐标**：位置/尺寸用浮点 `(column, row)` 网格单位，经现有 `GridMetrics` 映射到像素 | 屏幕 `column_width` 随视口宽变化、导出固定 1600 宽——裸像素坐标会在窗口 resize/导出时相对卡片漂移；网格单位让标注与卡片**同呼吸**，屏幕/导出免费一致 |
| D2 | 吸附粒度 | lattice = **1/8 单元格**（列向 = (column_width+gutter)/8，行向 = (row_height+gutter)/8，导出宽度下 ≈15 px）；参考线捕获 ±6 屏幕 px 且优先于 lattice；Alt 关吸附 | Miro 的手感 = 细网格 + smart guides；1/8 格既够细又保持与卡片格线的整数倍关系，参考线保证「贴着卡边对齐」这类高频意图一步到位 |
| D3 | 箭头锚定 | 端点二态：自由点 `(gx, gy)` 或锚定 `{target, anchor}`；`anchor` 默认 **auto**（连线与目标圆角矩形边界的交点，随两端实时重算），可选强制 N/E/S/W 边中点；目标删除 → 端点退化为最后计算位置的自由点 + toast | auto 边界锚是 Miro 连接线默认；退化而非级联删除，尊重「不静默破坏作者内容」 |
| D4 | 创建入口 | 画布空白右键菜单「添加便签 / 添加箭头」（当前空白无右键菜单，新增）；便签 hover 出 4 边**连接点**，从连接点拖出 = 建箭头并跟手；**卡片不加连接点**（避免与 P3 移动手势/替换意图环抢 hover 面），箭头锚卡片靠拖端点上去 | 左轨不加按钮——轨是面板启动器不是工具选择栏；卡片 hover 面已经很挤（P3 意图环、放大钮） |
| D5 | 布局模式范围 | V1 仅 `free_grid` 模式可见可编辑；模板模式入口禁用 + tooltip「标注在自由网格模式可用」；数据保留不删 | 模板槽位坐标随 ratio/模板切换整体重排，自由点标注无稳定参照；锚定箭头虽可行但半套体验更糟；数据保留保证来回切换无损 |
| D6 | 持久化 | `UltraViewBoardState.annotations` additive 字段，**不 bump** `ULTRAVIEW_SCHEMA`（沿 P3 D2 viewport 范式）；依赖 board 级 `passthrough` 保旧构建 round-trip——plan Task 0 先补 passthrough 保真 characterization，若不成立先修再做本功能 | 标注是作者内容，旧构建重写丢字段不可接受；bump schema 会让旧构建把整个 UltraView 当不透明未来负载（显示为空），代价更大 |
| D7 | 上限 | 每板标注对象 ≤ **50**（便签+箭头合计），便签文本 ≤ **2000 字符**；超限拒绝 + toast | 有界性；50 已远超「对比板注释」的正常密度，防把 Board 当白板用 |
| D8 | digest | 标注**不进** preview digest（不影响任何卡片预览身份/新鲜度），但标注变更走 `mark_workspace_mutated`（要存盘）；不触发任何重抓 | 标注不改变预览内容；B1/B5 教训是视图态不进身份 digest，作者内容同理只关持久化不关身份 |

## 4. 交互规范（normative）

### 4.1 对象与选择

- 标注层在全部卡片**之上**；层内 z 序 = 创建顺序（后建在上）。
- 命中优先级（单一手势状态机内判定，从上到下）：标注选中手柄 > 便签本体 >
  箭头线段（点到线段距离 ≤ 6 屏幕 px）> 卡片 > 空白（框选/平移）。
- 点选：单击选中（显示手柄）；Shift+点 = 加减选；框选 = 卡片与标注**混选**。
- 混合组移动：组内有卡片时整组按卡片的整格 delta 平移（保持相对位置，任一
  成员非法则整组弹回——沿 P3 组语义）；纯标注组走细 lattice。组操作 undo 单条。
- Delete/Backspace 删除选中标注（与卡片混选时也各删各的语义按 P3 现状，卡片
  走「移到未放置」既有语义，标注直接删）；删除可 undo，不弹确认。
- Esc：编辑态 → 退出编辑；有选中 → 清选；否则走既有 Esc 栈。

### 4.2 便签

- 创建：右键「添加便签」→ 在点击处生成默认尺寸便签（2×1.5 单元格）并立即进入
  文字编辑态。
- 编辑：双击进入（内嵌 QTextEdit，中文 IME 正常）；点便签外或 Esc 提交；提交
  = 一条 undo。空文本提交且从未有过内容 → 自动删除该便签（防垃圾对象）。
- 文本：自动换行；字号固定档（内容坐标 12pt，随 zoom 缩放）；超出高度显示
  溢出渐隐 + resize 提示，不滚动。
- resize：8 向手柄，细 lattice 吸附，最小 1×0.75 单元格；Shift = 保持宽高比。
- 颜色：选中态弹 6 色小色板（黄默认 / 灰 / 蓝 / 绿 / 红 / 紫，取
  `ui_kit` 语义色的 pastel 档，融入现有配色而不是照抄 Miro 荧光）；换色一条 undo。
- LOD：zoom < 40% 时只渲染色块（文字反正不可读，Miro 同款行为）；≥40% 全渲染。

### 4.3 箭头

- 创建路径 A：便签 hover 出 4 边连接点，从连接点按下拖出 → 箭头跟手，起点锚
  该便签（auto）；松手在对象上 = 锚定终点，空白 = 自由终点。
- 创建路径 B：右键「添加箭头」→ 进入两击放置（第一击起点、第二击终点，各自
  可落对象或空白；Esc 取消）。
- 端点拖动：选中箭头显示两端点手柄；拖动中悬停卡片/便签时目标描边高亮 =
  「松手即锚定」，空白松手 = 自由点（细 lattice 吸附）。
- 跟随：锚定目标移动/resize 时端点按 D3 auto 规则实时重算；目标进未放置/被
  删除 → 端点退化自由点 + toast「箭头已脱离目标」。
- 样式：线宽 2px（内容坐标，随 zoom 缩放，下限 1 物理 px）；实线/虚线切换；
  单箭头（默认，箭头在终点）/双箭头；颜色同便签 6 色（默认深灰蓝）。样式改动
  入口 = 选中态小工具条（浮岛风格，贴线中点上方）。
- 自由端点最小长度 0.5 单元格，防不可命中的退化线段。

### 4.4 吸附（细则）

- lattice：D2 的 1/8 单元格，作用于便签移动/resize 与箭头自由端点。
- 参考线：拖动中与**视口内**卡片/便签的左右边、水平中线、上下边、垂直中线差
  ≤6 屏幕 px 时显示 1px 参考线并吸上；参考线优先于 lattice；一次最多显示
  水平+垂直各一条（取最近）。
- Alt 按住：lattice 与参考线全关，纯自由（松开恢复）。
- 卡片的移动/resize **完全不变**（整格吸附、碰撞规划、全有全无——P3 硬合同）。

### 4.5 只读面

- 演示模式：标注正常渲染，全部编辑（选择/手柄/连接点/右键）关闭。
- 导出 PNG 1×/2× 与整板复制：标注按导出 `GridMetrics`（1600 宽канон）经同一
  映射渲染进图，位置相对卡片与屏幕一致（±1px @导出坐标）。
- minimap / 整板概览：V1 不画标注（只影响导航，不失真）；plan 验收时若观感
  割裂再补色块级表示。
- 筛选弱化（按轴类型 dim 卡片）不作用于标注。

## 5. 数据模型与持久化

~~~python
# ultraview_state.py（Qt-free）
@dataclass
class NoteAnnotation:
    annotation_id: str          # uuid
    kind: str = "note"
    x: float; y: float          # 连续网格单位（列、行）
    width: float; height: float # 连续网格单位
    text: str = ""
    color: str = "yellow"       # 6 个语义色名，非 hex

@dataclass
class ArrowEndpoint:
    x: float; y: float                  # 自由点坐标；锚定时为最后解算值（退化用）
    target_kind: str | None = None      # None | "card" | "note"
    target_id: str | None = None        # UltraViewRef 序列化 / annotation_id
    anchor: str = "auto"                # auto | n | e | s | w

@dataclass
class ArrowAnnotation:
    annotation_id: str
    kind: str = "arrow"
    start: ArrowEndpoint; end: ArrowEndpoint
    line_style: str = "solid"           # solid | dashed
    heads: str = "end"                  # end | both
    color: str = "ink"

UltraViewBoardState.annotations: list[NoteAnnotation | ArrowAnnotation]
~~~

- 序列化：board payload 增加 `annotations: [...]`（additive，缺省容忍，非法项
  丢弃 + warning 留痕，同现有 `_warn` 范式）；未知 `kind` 保留原字典透传
  （为将来对象类型留门）。
- 兼容：D6——不 bump schema，依赖 board `passthrough` 在旧构建下 round-trip；
  forward-only 的边界（更旧构建重写丢字段）与 viewport 字段一致并文档化。
- 校验：坐标 clamp 进 `MAX_GRID_ROWS`/12 列板域；上限 D7；undo 快照复用每板
  历史既有机制（标注列表进快照）。

## 6. 渲染与实现要点

- **新协作者**：`ui/chart_stack/ultraview/annotations.py`（层 widget + 手势扩展
  挂点），状态经 `_owned_names` 声明归属，不写穿宿主白名单外属性。
- 便签 = 层的子 QWidget（要 IME 文本编辑，必须真 widget）；箭头/参考线/连接点
  = 层的 paintEvent 绘制（复用 ghost_overlay 的透明层范式：
  `WA_TranslucentBackground` + paintEvent 兜底，Gotchas 合规）。
- 输入路由：层本身 `WA_TransparentForMouseEvents`（便签子 widget 除外），箭头
  与手柄命中判定并入 P3 手势状态机（gesture 协作者持有），**不做第二个输入
  owner**、不用 setMask 追矩形。
- 映射纯函数（Qt-free，放 viewport.py 或 annotations 纯函数区）：
  `annotation_rect_px(note, metrics)` · `snap_annotation(value, metrics)` ·
  `auto_anchor_point(rect, toward)` · `segment_hit(p, a, b, tol)`——屏幕、导出、
  测试三方共用**这一份**。
- 性能：拖动便签/端点只 update 层的脏矩形；不在 paint 里每帧新建整板缓冲
  （S5 教训）；24 卡 + 50 标注在真机连续缩放帧率不劣于当前基线。

## 7. 护栏对账

- 只读 / 零计算：标注不触碰源 View、不触发任何分析计算与预览重抓（D8）。
- 状态所有权棘轮 / backref 白名单 / import boundary / `.connect(lambda` 棘轮 /
  QSS border 简写 lint：全部维持。
- 批渲染 parity 思想外推：屏幕与导出共用同一映射函数，验收比「真正必须一致
  的东西」（相对位置、样式），不比字号常量。
- hints / quickref / `help/ultraview-guide.html` 随交互新增全量同步
  （`/update-hints`）；真机 Cocoa 验收强制，offscreen 只当排版草稿。
- 视口/标注均不进 preview digest；标注变更必须 `mark_workspace_mutated`。

## 8. 量化验收

1. 吸附：拖便签步长 = 单元格/8（±0 px，同一 metrics 断言）；参考线捕获阈值
   ±6 屏幕 px，命中时边坐标严格相等。
2. 一致性：同一 Board 屏幕 100% 截帧 vs 导出 PNG 1×，标注中心点映射到导出
   坐标后偏差 ≤1 px；2× 导出等比。
3. 跟随：锚定卡片移动 N 格后箭头端点仍在卡片边界上（边界方程代入 ≤0.5 px）。
4. 退化：删除锚定目标后箭头端点位置 = 删除前最后解算点；toast 出现一次。
5. 持久化：50 对象满载 Board 保存→载入→再保存，字节级往返（passthrough 项
   除外按语义比较）；旧构建（无本功能）载入→改无关字段→保存，标注不丢
   （characterization）。
6. 性能：真机 24 卡 + 50 标注连续缩放 / 拖便签，帧时间不劣于无标注基线 10% 以上。
7. 回归：卡片整格移动/碰撞/替换意图环全套 P3 测试零变化。
