# UltraView 自适应智能排版与 Fit Spec

- 日期：2026-08-30
- 状态：设计完成，待实施
- 设计基线：`main` @ `db92d41cace2b4b97fa6a6c8ba7234c085d1722a`
- 配套计划：
  [`2026-08-30-ultraview-adaptive-smart-layout-and-fit-plan.md`](../plans/2026-08-30-ultraview-adaptive-smart-layout-and-fit-plan.md)
- 适用范围：UltraView Free Grid、WWT 多 View 投影、自动排版、卡片 Fit、Board Fit、预览 settle
- 证据等级：源码与确定性 probe 已核对；用户截图已核对；macOS Cocoa 前台与 Windows frozen 仍为 **UNVERIFIED**

## 1. 一句话结论

UltraView 不再把“保留 WWT 毫米宽度、逐卡等预览、固定 span 做 first-fit”误当成智能排版；新的默认行为是一笔**稳定、可撤销、可解释的整体布局事务**：先理解来源中的阅读顺序和卡片真实读图区，再联合决定卡片大小与位置，最后只做一次镜头 Fit。

产品只向用户暴露三个有意义的意图——**智能均衡、保留层级、等大网格**；复杂度留在确定性 solver 里，不把十几个权重甩给用户。

## 2. 本规格覆盖与继承关系

本规格仅覆盖下列旧行为：

- WWT 原生毫米几何到 UltraView 卡片几何的换算；
- WWT 预览到达后的整组延迟 Fit；
- Free Grid 的“自动排版”语义；
- Card Fit、Smart Layout、Compact Arrange、Board Fit 之间的边界；
- 完全重叠窗口的重定位顺序；
- 布局可读性、稳定性与前台验收标准。

以下既有契约继续有效，不在本规格中重写：

- 单 View 不自动建 Board，多 View 分配专属/空 Board；
- Board 命名、容量、原子提交和 stable `UltraViewRef`；
- 时域最多 24 Views，分析区仍最多 12 Views；
- WWT 曲线、范围、颜色、复合 source/channel identity；
- 用户保存后的 Free Grid 几何、项目恢复和普通手动编辑。

与本规格冲突时，以下旧文档的“native 几何、宽度 rank、延迟逐组 Fit、固定 span 自动排版”条款由本规格取代；其余条款保留：

- `2026-08-28-wwt-winwert-layout-import-spec.md`
- `2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md`
- `2026-08-29-wwt-timedomain-plot-and-ultraview-reflow-plan.md`

## 3. 已确认的问题，不把推断冒充事实

### 3.1 源码事实

1. `ultraview_core/native_layout.py` 用 `GRID_MIN_COLUMN_WIDTH=96` 构造 canonical metrics；Free Grid 屏幕/导出用 1600px Board metrics。同一个 `GridRect` 在规划与真实绘制时不是同一个外框。
2. native group fit 以 `height = source_width × preview_aspect_h / preview_aspect_w` 求外框高度，没有扣掉 header、footer 和 image padding；它匹配的是卡片外框，不是实际 plot reading box。
3. `plan_auto_arrange()` 明确保留每张卡的 `column_span/row_span`，只按当前行列顺序 first-fit。因此它能消空洞，不能修复错误大小与错误比例。
4. WWT group fit 在只拿到部分 preview aspect 时就执行，后续每张 preview 到达都会再次规划。中间布局依赖 preview 到达时序。
5. 完全重叠项走 Manhattan 最近空位；同距时优先更小的 `(row, column)`，所以后出现窗口可能向上插入，破坏源阅读顺序。
6. `zoom_fit()` 正确地按卡片 union 做 Board Fit。它是相机操作，无法修复上游过宽、过高、空耗严重的内容 union。
7. `preview_reading_box()` 使用真实 capture aspect 且不拉伸，但默认不放大低分辨率缓存图；错误的卡片比例会直接变成大块 letterbox/pillarbox。

### 3.2 真实样本与截图证据

本机 U-Can WWT 有 7 个窗口，原始宽度为 `100 / 90 / 50 / 50 / 50 / 50 / 50 mm`。当前算法在统一 16:9 preview 模拟下得到约：

- View 1：`774×338 px`；
- View 2：`708×338 px`；
- View 3–7：约 `381×188 px`；
- 实际 plot reading box 的未利用面积约为 `32%–45%`；
- 内容 union 约 `1560×738 px`，对 `1200×750 px` 可用区的 Board Fit 约 `0.738`。

这与截图里的 `72%`、一张超大卡、数张过小卡、大空洞和 View 7 浮在中间相符。结论是：**Board Fit 数学没有明显失效；它在忠实地缩放一份质量较差的上游布局。**

### 3.3 测试事实

当前相关聚焦测试通过，但它们主要证明：不重叠、undo 可用、DPR 已归一化、auto arrange 保持 span。它们没有证明：

- 图是否够大、卡片之间是否失衡；
- preview 是否充分占满 reading box；
- WWT 阅读顺序是否稳定；
- preview 任意到达顺序是否得到相同布局；
- 用户拖动后是否会被晚到的自动任务覆盖。

因此“测试绿”与“排版好用”目前是两个不同结论。

## 4. 产品目标

### G1 — 看起来像同一个系统做出的整体决定

卡片大小、卡片位置、Board 占用和相机 Fit 必须共同求解。不得再由三条互不知道彼此的链路各做一半决定。

### G2 — 灵活，但不漂

允许宽图、竖图、缺失预览、不同数量 View、用户锁定和 WWT 层级；相同 facts + 已冻结 policy 必须得到逐字相同的 `GridRect` 集合，与异步到达顺序和求解期间的 resize 事件无关。用户在另一种窗口比例下显式重排时，`target_viewport` 变化属于新的 policy 输入。

### G3 — 可读性优先于来源毫米

WWT 的窗口位置是阅读拓扑证据，窗口大小是弱 salience 证据，不是 UltraView 中永久的 2:1 或 4:1 面积命令。普通卡不能仅因来源宽度成为“霸屏 hero”。

### G4 — 用户意图强于自动化

用户移动、缩放、锁定或选择模式后，后台 preview 不得把卡片挪回去。无法满足锁定约束时，整笔操作拒绝，不做半套布局。

### G5 — 24 Views 时优雅降级

不承诺把 24 张图强塞进单屏仍然可读。优先提供可滚动的紧凑工作面、稳定层级和一键聚焦；只有用户明确选择“等大/紧凑”时才进一步压缩。

## 5. 非目标

- 不新增 WWT 专用 Canvas 或复制 preview bitmap 到项目 JSON。
- 不改变图表数据、坐标轴范围、曲线颜色、分析计算或 source identity。
- 不把 Smart Layout 做成自由浮点像素布局；最终仍提交现有 `GridRect`。
- 不让 Board Fit 隐式移动或缩放卡片。
- 不把 Card Fit 改成全 Board 全局重排。
- 不在本波次重写 Template Layout、作者对象或 Board schema。

## 6. 四个动作必须说人话

| 动作 | 是否改卡片大小 | 是否改卡片位置 | 是否改相机 | 语义 |
| --- | --- | --- | --- | --- |
| **智能排版** | 是 | 是 | 完成后一次 | 按当前策略重新求解整个可操作集合 |
| **紧凑排列** | 否 | 是 | 完成后一次 | 保持 span，只消除空洞；即现有 first-fit 能力的新名字 |
| **按原图比例** | 仅目标卡 | 必要时局部避碰 | 否 | chrome-aware 的局部 Card Fit，保持当前阅读尺度 |
| **适应内容** | 否 | 否 | 是 | 只把当前卡片 union 放进可用 viewport |

不得再用“Auto Fit”同时指代卡片改形、整组排版和相机适应。

## 7. 用户可选策略：少而有用

### 7.1 默认：智能均衡 `balanced`

- 同一语义层级的卡片优先获得接近的 reading-box 面积；
- 来源宽度只作为弱提示，普通卡 reading-box 面积比默认不超过 `1.35`；
- 宽图/竖图可以通过不同 span 匹配真实 aspect，但不能仅靠来源毫米成为 hero；
- 优先减少空耗、保持源行序和形成紧凑的视觉块。

这是 WWT 自动导入与 Board“智能排版”的默认模式。

### 7.2 保留层级 `preserve_salience`

- 保留来源中的大/中/小相对层级；
- salience 经过压缩映射，不直接复制毫米面积；
- 普通卡 reading-box 面积比上限为 `1.80`；
- 只有用户显式标记 priority/hero 的卡片可以超过该上限。

适合来源布局本身包含明确主图与辅图的场景。

### 7.3 等大网格 `equal_grid`

- 同类卡使用同一 reading-box 目标面积；
- 只因 capture aspect 选择横向或纵向的相邻 span；
- 不保留来源大小层级，但保留稳定阅读顺序。

适合批量对比。

### 7.4 设置面

Board 设置只暴露：

- 排版策略：`智能均衡 / 保留层级 / 等大网格`；
- 密度：`自动 / 舒适 / 紧凑`；
- `重排时保留我锁定的卡片`，默认开启。

不暴露拓扑权重、空白权重、搜索深度等内部旋钮。选择只影响下一次命令或下一次 WWT 导入；真正持久化的是最终 `GridRect`，重开项目不自动重排。

## 8. 中立数据合同

新增 Qt-free owner：`mf4_analyzer/ultraview_core/smart_layout.py`。

```python
@dataclass(frozen=True)
class SmartLayoutPolicy:
    mode: Literal["balanced", "preserve_salience", "equal_grid"]
    density: Literal["auto", "comfortable", "compact"]
    target_viewport: tuple[int, int]
    preserve_locked: bool = True

@dataclass(frozen=True)
class SmartCardFact:
    ref: UltraViewRef
    source_order: int
    source_row: int | None
    source_column: int | None
    source_salience: float | None
    preview_aspect: float | None
    preview_confidence: Literal["captured", "host-estimate", "fallback"]
    current_rect: GridRect | None
    locked_rect: GridRect | None

@dataclass(frozen=True)
class SmartLayoutResult:
    accepted: bool
    placements: tuple[tuple[UltraViewRef, GridRect], ...]
    reason: str | None
    diagnostics: tuple[str, ...]
    search_visits: int
    used_fallback: bool
```

约束：

- DTO 不引用 Qt、MainWindow、widget 或 PreviewStore；
- `ref` 是唯一身份，显示名不得参与 key 或 tie-break；
- preview aspect 是逻辑像素比例，调用前必须完成 DPR 归一化；
- `target_viewport` 是命令触发时冻结的 chrome-clear 逻辑像素尺寸；它可以让显式重排适配窄/宽窗口，但求解期间不得跟随 resize 事件漂移；
- 所有集合在进入 solver 前按稳定身份和 `source_order` 冻结。

## 9. 唯一几何真相

### D1 — planner 与 renderer 共用一份 1× metrics

`ultraview_core/grid_geometry.py` 提供 neutral canonical screen/export metrics。`native_layout.py`、`smart_layout.py`、Free Grid screen 与 compositor export 都从该 owner 获取 pitch。

禁止保留“native 96px 列宽、screen 1600px Board 列宽”两套 1× 解释。

### D2 — 适配对象是 inner reading box

候选 `GridRect` 必须先通过统一函数换算为：

```text
outer card rect
  - header 34px
  - footer 24px
  - image padding 8px × 2
= inner reading box
```

评分使用 preview contain 后的实际 image rect，而不是 `outer_width / outer_height`。

### D3 — capture aspect 缺失是“低置信事实”，不是异常值

- 已捕获：使用逻辑像素 aspect；
- 未捕获但 live capture host 尺寸有效：冻结其逻辑 aspect，并标记 `host-estimate`；
- 非有限、零宽高或无 host：使用 neutral fallback `16:9`，标记 `fallback` 并记录 diagnostic；
- `target_viewport` 非法时使用 canonical `1600×900`，而不是读取求解过程中变化的窗口尺寸；
- solver 对占位 aspect 仍必须确定性，不得返回 NaN 或依赖 mapping 遍历顺序。

## 10. WWT：保留拓扑，不复制桌面尺寸

### D4 — 来源行序是结构，毫米大小是提示

从 WWT rect 提取：

- `source_order`：文件出现顺序；
- `source_row`：按纵向重叠带生成的稳定行；
- `source_column`：同一行按 X、再按 source order；
- `source_salience`：来源面积对中位面积的压缩值，`clamp(exp(0.35 × ln(area / median_area)), 0.75, 1.80)`。

`balanced` 主要保留前三项；`preserve_salience` 才使用压缩后的 salience。不得再用 `GRID_COLUMNS / max_row_mm` 直接把最宽来源卡扩成满行。

### D5 — 行聚类不能链式吞并

旧 `_cluster_rows()` 的“只要与当前 band 有纵向重叠就合并”会被桥接矩形链式吞并。新适配器以稳定中心线/重叠比例聚类，并在歧义时优先 `source_order`，输出可测试的 row graph；无论输入 mapping 顺序如何都一致。

### D6 — 完全重叠是 source stack，不是随机碰撞

完全重叠项继承被覆盖窗口的 `source_row`，按 source order 插到该行已知最后成员之后。若当前行放不下，进入紧邻的 continuation row；禁止 Manhattan tie 把它插到上方空洞。

U-Can 的 View 7 必须跟随 View 6 的阅读组，不得浮到两排之间。

## 11. Smart Layout 求解器

### 11.1 两阶段，不用一个神秘总分

第一阶段是 hard constraints，任何一条失败都拒绝候选：

1. ref 唯一、rect 合法、无重叠、在 safety bounds 内；
2. locked rect 原样保留；
3. 2–8 卡在 `comfortable/auto` 下达到最小 inner reading box `240×135 logical px`；
4. 9–12 卡的 auto 目标不低于 `200×112 logical px`；
5. 13–24 卡允许滚动工作面，auto 目标不低于 `176×99 logical px`，不以“单屏全放下”为硬约束；
6. source order 不得发生逆序；continuation row 仍紧邻所属 row。

第二阶段按**字典序 score vector**选择，不把不可读性与空白简单相加抵消：

1. 按冻结 `target_viewport` 预计 Board Fit 后的 reading-box deficit，越小越好；
2. topology 行断裂数与 continuation 数，越少越好；
3. reading-box 面积偏离当前密度目标的总量，防止无意义地把所有卡放大；
4. contain 后 unused-area ratio；
5. card union 的空白率和 viewport aspect 偏差；
6. 与策略 salience 目标的偏差；
7. 与当前几何的总移动量；
8. 最终序列化 rect，作为稳定 tie-break。

### 11.2 有限候选与确定性预算

- 每张卡最多生成 6 个相邻 span 候选；
- row-break/skyline 使用固定遍历顺序；
- 2–24 卡最多扩展 4096 个状态；
- 超预算先减少 salience 候选，再降级为确定性 equal-grid row pack；
- fallback 仍须满足 hard constraints；否则返回 `no_legal_layout`，不做部分提交。

测试断言 `search_visits` 上限，不用易受机器负载影响的毫秒阈值作为 CI 主合同。

### 11.3 版面质量指标

```text
reading_fill = rendered_preview_area / inner_reading_box_area
board_fill   = sum(outer_card_area) / card_union_bounding_box_area
size_ratio   = max(ordinary_reading_area) / min(ordinary_reading_area)
```

`captured` preview 的 `reading_fill` 默认目标 `>= 0.82`。无法满足时，solver 必须在 diagnostics 中说明是锁定、极端 aspect、密度还是 safety bound 导致。

## 12. 异步预览：只允许一次可见 settle

### D7 — import 先提交 membership，不逐张改几何

WWT 导入事务先创建 Board membership 和一份稳定 provisional layout；它使用 source facts + 冻结的 host-estimate/fallback aspect。provisional layout 可以直接显示，但不会随着每张 preview 到达反复重排。若 preview 在 Board 首帧前已齐，用户只看到 final layout；否则 provisional 到 final 也必须是一次整板原子替换，中间不做 Board Fit。

### D8 — settle 条件

整组 Smart Layout 在以下任一条件满足时计算一次：

- 所有可捕获卡片 aspect 已到达；或
- 最后一个 aspect 事件后安静 `250 ms`，且至少有一个 captured aspect；或
- 从注册起到 `1200 ms` deadline。

这些是首版产品常量，必须用 fake clock 测试；Cocoa probe 可校准数值，但不能改变“安静窗 + deadline + 单次提交”语义。

### D9 — settle 后不自动改几何

settle 完成后：

- 晚到 preview 只更新图像质量与缓存；
- 不再次运行 solver；
- 用户可显式点“智能排版”重新求解；
- 用户在 settle 前 move/resize/lock 任一卡，取消该组自动 settle；Board 保留 provisional/current geometry。

因此结果不依赖 capture 完成顺序，用户也不会看到卡片自己跳第二次、第三次。

## 13. Preview 分辨率与 Fit

### D10 — 不因 no-upscale 把大卡误判成该缩小

延续现有 Card Fit lesson：Card Fit 是围绕当前阅读尺度的局部 hug，不在整个 Board 搜“最小 unused area”，也不因缓存图较小而把大卡压成缩略图。

### D11 — 目标卡需要更大图时请求重抓

如果目标 inner reading box 任一边超过缓存逻辑像素 `1.25×`：

- capture coordinator 把该 ref 标记为 `resolution_stale`；
- 在真实 View 可驻留时按目标 logical size × DPR 重抓；
- 重抓只替换 preview，不触发布局；
- 无法重抓时保持 no-upscale，并显示质量诊断，不做模糊强放大。

TimeDomain 的“有内容”继续按 plotted channel/dense-raster 合同判断，不得回退为仅看 native curve count。

## 14. 用户手动意图与锁定

### D12 — 锁定分两层

- 显式 lock：用户从卡片菜单锁定，后续 Smart Layout 保留 rect；
- 隐式 touch：本次 pending settle 注册后，用户 move/resize 的卡片使整组自动 settle 失效，但不永久锁定。

显式“智能排版”时，用户可选择保留 locked cards；默认保留。若剩余卡无法绕开锁定卡合法排布，操作整体拒绝并提示“锁定卡片占用空间，未改变布局”。

### D13 — 不新增 MainWindow 散状态

pending group、quiet timer、deadline、captured aspects 与 touched revision 由现有 UltraView workspace controller 的明确 holder 所有，在 Board 删除、workspace clear、项目恢复、窗口销毁时对称清理。

## 15. 事务、Undo 与持久化

- 一次 Smart Layout = 一次 geometry snapshot、一次 history、一次 dirty、一次 refresh、一次 Board Fit；
- reject = 零 mutation、零 history、零相机变化；
- WWT provisional + settle 在用户看来仍是一笔导入操作，Undo 一次回到导入前；
- 用户在 provisional 与 settle 之间编辑，则导入 history 封口并取消 settle，禁止篡改已存在 undo step；
- 项目只保存最终 `GridRect`。重开项目不按当前 preview 或窗口宽度重新排版；
- 策略偏好可保存在 QSettings，但不得成为项目恢复的隐藏前提。

## 16. Board Fit 与 LOD

### D14 — Board Fit 仍只负责相机

Smart Layout 接受后调用一次现有 `zoom_fit()`；它不参与 solver mutation，也不成为 geometry 的隐式输入。

### D15 — “全放进来”不等于“全部可读”

- 2–8 卡：目标是 Smart Layout 后 Board Fit 仍处于 full-preview LOD；
- 9–12 卡：允许 compact chrome，但 preview 必须可辨认；
- 13–24 卡：允许 Board Fit 给出总览，日常阅读依靠滚动/双击聚焦；不得为了让 zoom 数字变大而违反最小 1× reading-box。

## 17. 降级与错误表

| 条件 | 行为 | 用户可见性 |
| --- | --- | --- |
| preview 全部缺失 | 冻结 host-estimate；无 host 时用 16:9 fallback 做确定性 provisional；deadline 后不再自动改 | 静默；卡片可正常等待预览 |
| 单个 preview 非有限/零尺寸 | 该卡降级到冻结 host-estimate 或 16:9 fallback | diagnostic log，不卡住整组 |
| locked cards 无合法解 | 整笔拒绝，保留原布局 | 可行动提示：解锁或改用紧凑排列 |
| 搜索超预算 | 确定性 equal-grid fallback | diagnostic `search_budget_fallback` |
| fallback 仍无合法解 | 零 mutation | 提示保留现状，可减少卡片或解锁 |
| late preview | 更新图像，不改几何 | 无跳动；必要时显示质量状态 |
| Board 被删除/切换/恢复 | 取消 pending timer 和 group | 静默，禁止写入 stale Board |
| layout revision 已变化 | 取消自动 settle | 静默，尊重用户编辑 |
| 24 placed cap 到达 | 沿用既有 unplaced/提示合同 | 不静默丢失 View |

## 18. U-Can 字面验收

在合成 fixture 与本机真实 U-Can optional smoke 中：

1. 7 个 View 全部 placed；View 7 跟随 View 6 所在阅读组，不得成为两组之间的孤立浮动行；若需要 continuation row，它必须紧贴下组且保持组内顺序；
2. 源拓扑稳定为两组：上组 `1,3,4`，下组 `2,5,6,7`；solver 可在组内换成相邻 continuation row，但不得逆序；
3. `balanced` 下 ordinary reading-area ratio `<= 1.35`，没有仅因 `100mm` 宽度出现的霸屏卡；
4. captured preview 的 `reading_fill >= 0.82`；
5. 对 `1200×750 logical px` chrome-clear viewport，最终 Board Fit `>= 0.85` 且处于 full-preview LOD；
6. 7 个 aspect 的所有测试排列顺序得到完全相同的最终 `GridRect`；
7. settle 后再到达任意 preview，layout revision、history 数与相机不变；
8. 用户在 settle 前移动任一卡，自动 settle 取消，用户 rect 保留；
9. Undo 一次回到导入前/排版前，Redo 一次恢复完整结果；
10. 保存重开后的 rect 逐项相同，不因屏幕宽度、DPR 或缓存 preview 尺寸漂移。

若真实样本缺失，1–10 的 synthetic owner tests 仍必须运行；真实 `testdoc/` 只能作为 optional smoke，不能成为唯一回归保护。

## 19. 通用验收矩阵

| 维度 | 必测集合 |
| --- | --- |
| 数量 | 2、3、4、7、8、9、12、13、24 |
| aspect | 1:1、4:3、16:9、9:16、超宽、超高、缺失、非法 |
| topology | 单行、多行、错列、完全重叠、部分重叠、桥接矩形 |
| 策略 | balanced、preserve_salience、equal_grid |
| 密度 | auto、comfortable、compact |
| 用户状态 | 无锁、单锁、多锁、settle 前 move、settle 后 move |
| 异步 | 正序、逆序、随机排列、部分缺失、deadline 后 late arrival |
| 显示 | DPR 1/2、窄/宽 viewport、screen/export 同 GridRect |
| 生命周期 | Board switch/delete、workspace clear、project restore、window destroy |

必须逐项断言：合法、无重叠、确定性、hard constraints、search cap、事务副作用和可解释 diagnostic。

## 20. 前台质量门禁

离屏与单元测试不能关闭视觉验收。实施完成后至少保留三类证据：

1. **确定性 geometry artifact**：U-Can 与 2/4/8/12/24 合成矩阵的 rect/score JSON；
2. **macOS Cocoa 前台**：U-Can Board 在 100% 与 Board Fit 下的整页截图，测量 card/reading rect、空白率、LOD 和卡片顺序；
3. **Windows Full/Lite frozen**：至少完成 WWT 导入、Smart Layout、Undo/Redo、保存重开与 DPR 外观 smoke。

Cocoa 与 Windows 没跑时必须写 `UNVERIFIED`，不得用 offscreen 绿灯代替。

## 21. Definition of Done

只有同时满足以下条件才算完成：

- 四个动作的产品语义和文案不再混淆；
- import、手动 Smart Layout 共用同一 neutral solver；
- planner 与 renderer 只有一份 canonical 1× metrics；
- U-Can 与通用 2–24 矩阵满足确定性和可读性合同；
- 异步 settle 只产生一次可见布局提交；
- 用户手动意图、Undo、保存恢复、Board 生命周期均闭环；
- `ui/hints.py` 与 `ui/quickref.py` 同步新动作语义；
- owner tests、边界门禁、稳定 milestone 全量门禁按计划通过；
- Cocoa/Windows 未执行项被如实标为 `UNVERIFIED`。
