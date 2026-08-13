# UltraView P0 产品与技术规格

- 日期：2026-08-12
- 状态：**READY FOR IMPLEMENTATION**
- 产品：TraceLab v7.9.9
- 代码证据基线：`3678227b`
- 配套实施计划：
  `docs/analyzer/plans/2026-08-12-ultraview-p0-implementation.md`
- 上游产品/技术报告：
  `docs/analyzer/reviews/2026-08-12-ultraview-product-technical-report.md`
- Claude 评审：
  `docs/analyzer/reviews/2026-08-12-ultraview-report-claude-review.md`
- 交互方向原型：
  `docs/analyzer/ui-prototypes/2026-08-12-ultraview-interactive-demo.html`

## 0. 结论与文档效力

UltraView P0 可以由当前 **PyQt5 + pyqtgraph** 技术栈实现。它不是第六套分析
算法，而是五个既有源工作区之上的一个**只读快照 Board**：引用已有 View，展示
最近一次有效预览，完成 2～6 图的全局比较、临时放大和整板导出；UltraView 自身
不计算、不补算、不改变源 View。

本 spec 接受 Claude 评审的 F1～F10，并覆盖上游 DRAFT 报告中与下列事项冲突的
旧决策：

| 主题 | 本 spec 的最终决定 |
|---|---|
| 零计算证明 | 同时探测四个计算入口、任务提交入口和分析缓存写入漏斗 |
| 抓图完成点 | P0 不假设存在 post-paint 信号；按源画布类型使用稳定判据和 queued capture |
| 项目兼容 | 顶层 `SCHEMA_VERSION` 保持 2；`current_mode` 永不保存 `ultraview` |
| View 库 | 放在 `UltraViewPage` 页内，不把全局 Navigator 改成模式栈 |
| Board 实现 | QWidget 卡片网格，不使用 QGraphicsScene/QGraphicsItem |
| 屏上缩放 | 删除 70%～125% 整板缩放；响应式网格始终适应可用空间 |
| 导出 | P0 只做复制整板图和 PNG 1×/2×；不做 PDF/SVG |
| 零任务文案 | 不显示常驻 `0 JOBS`；零计算由测试守护 |
| 溢出 | 缩容、替换、满板添加统一进入未放置托盘 |

评审闭环索引：

| Claude finding | 本 spec 验收 | 实施计划主 Task |
|---|---|---:|
| F1 零计算探针 | UV-A19～A22 | 5、7 |
| F2 稳定抓图/空白帧 | UV-A13～A18 | 3 |
| F3 项目双向兼容 | UV-A25～A28 | 6 |
| F4 页内 View 库 | UV-A07、A11 | 4、5 |
| F5 第六模式扇出 | UV-A23、A24、A32 | 5、8 |
| F6 digest 遗漏 | UV-A05、A17、A18 | 1、3 |
| F7 Retina/内存 | UV-A16、A29、A31 | 2、7 |
| F8 1×1/split 生命周期 | UV-A15、A16 | 2、3 |
| F9 section 词汇 | UV-A01、A27 | 1、6 |
| F10 QWidget/托盘/UI 收窄 | UV-A02、A06、A08～A12、A30 | 4、7 |

若本 spec、上游 DRAFT 报告和 HTML 原型之间存在冲突，以本 spec 为准。HTML 只
证明交互方向，不证明 PyQt 实现、渲染完成时机、性能或项目兼容性。

## 1. 用户问题、目标与成功定义

### 1.1 用户问题

当前一次只能看一个 View，或左右分屏比较两个图。对四个以上工况、测试位置或跨
分析域证据进行比较时，用户需要频繁切换模式和 View，难以保留全局上下文，也容易
记错图的来源与状态。

### 1.2 一句话目标

用户能把时域、频谱、时频、FRF、阶次中的已有 View 放入一张可保存布局、可导出
整板图的总览 Board，一次观察 2～6 张图，并能明确知道每张图来自哪里、是否最新。

### 1.3 五项产品承诺

1. **只读投影**：Board 卡片只引用源 View，不拥有第二份分析参数或数值结果。
2. **零隐式计算**：总览内的浏览、组织、比较和导出不提交任何分析任务。
3. **身份稳定**：引用以 `(section, view_id)` 标识，不以名称或列表下标标识。
4. **状态诚实**：没有有效像素时显示 `missing`；源变化后保留旧图并显示 `stale`；
   View 删除后保留槽位并显示 `orphaned`。
5. **可回到来源**：需要游标、缩放、参数编辑或重算时，用户回到原 View 操作。

### 1.4 P0 成功定义

- 在一个 Board 中完成 2、4、6 图比较，不再依赖频繁模式切换；
- Board 的布局、引用和未放置项随 `.tlproj` 保存/恢复；
- P0 操作序列的三层计算探针全部为 0，恢复待处理集合不变；
- Retina、普通 DPI、最小窗口宽度下都没有伪成功预览、按钮裁切或不可读卡片；
- 整板复制/PNG 导出包含完整布局，不只导出当前可见 viewport。

## 2. P0 范围与非目标

### 2.1 P0 包含

- 顶部第六入口 `总览`（内部 mode token 为 `ultraview`）；
- 每项目一个 Board；
- 页内 View 库，按五个源 section 分组并支持搜索；
- 从 View 库和源 View 的“加入总览”动作添加引用；
- 2/4/6 图模板、主图比例、拖拽/按钮换位；
- 常驻可见的未放置托盘；
- `fresh / stale / missing / orphaned` 四态；
- 对比轨道、量纲不一致和 X 范围不一致提示；
- 卡片右键菜单、只读临时放大、打开原 View、重新绑定；
- 第五个 UltraView Inspector context；
- 演示模式、复制整板图、PNG 1×/2×；
- 增量项目字段、兼容防御、帮助页、hints 和 quickref；
- 零计算、DPR/尺寸、内存、持久化、模式扇出的自动化门禁。

### 2.2 P0 明确不做

- 不在 Board 中运行 FFT、FFT vs Time、FRF、Order 或时域重绘；
- 不调用 `_render_analysis_view_from_cache()` 补预览；
- 不创建 4～6 套常驻 live pyqtgraph canvas；
- 不把源 QWidget reparent 到 UltraView；
- 不允许在卡片中编辑游标、坐标、参数、过滤器或标注；
- 不做自由无限画布、自由缩放、pan、任意尺寸卡片；
- 不做 PDF、SVG、矢量曲线承诺；
- 不把预览像素写入 `.tlproj`；
- 不把全局左侧栏改造成 QStackedWidget；
- 不全局收敛仓库中散落的五 section 字面量；
- 不新增 post-paint signal，不修改交互热路径；
- 不实现从数值 cache 独立重建预览，也不实现单卡 live 化。

## 3. 术语、身份与状态所有权

### 3.1 section 词汇

UltraView 只接受 GUI 源工作区词汇：

```python
SOURCE_SECTIONS = ("time", "fft", "fft_time", "frf", "order")
```

Batch/preset 的 `order_time` 不是合法 `ViewRef.section`。P0 在
`mf4_analyzer/ui/ultraview_state.py` 内以这一常量作为 UltraView 自己的单一来源；
不借机重构其他模块的 section 集合。

### 3.2 三类对象

| 对象 | 责任 | 生命周期 | 是否含 Qt 像素 |
|---|---|---|---|
| `UltraViewRef` | 指向一个源 View | 项目级，可持久化 | 否 |
| `UltraViewBoardState` | 布局、卡片顺序、托盘和显示选项 | 项目级，可持久化 | 否 |
| `PreviewRecord` | 某次成功抓图的图像和捕获元数据 | 进程/会话级 | 是，`QImage` |

### 3.3 身份与不变量

```python
@dataclass(frozen=True, order=True)
class UltraViewRef:
    section: str
    view_id: str

@dataclass
class CardPlacement:
    slot_id: str
    ref: UltraViewRef

@dataclass
class UltraViewBoardState:
    board_id: str
    name: str
    layout_id: str
    primary_ratio: float
    placements: list[CardPlacement]
    unplaced: list[UltraViewRef]
    show_titles: bool = True
    show_sources: bool = True
```

必须满足：

- `section` 必须属于 `SOURCE_SECTIONS`，`view_id` 必须是非空字符串；
- `placements + unplaced` 中同一个 ref 最多出现一次；
- `slot_id` 必须属于当前模板，且每个槽位最多一个 ref；
- 名称、tab color 和 View 下标只用于显示，不参与身份；
- Board 引用数不设人为上限；屏上最多放置 6 项，其余可留在滚动托盘；
- 删除源 View 不删除 Board ref，只改变派生状态；
- 清项目、关闭窗口时对称清理 PreviewStore、延迟任务和信号连接。

### 3.4 owner

- `ultraview_state.py`：Qt-free DTO、合法化、序列化和 digest 纯函数；
- `ui/chart_stack/ultraview/`：Page、卡片、View 库、托盘、布局几何、离屏合成、
  PreviewStore；
- `ui/main_window/ultraview_coordinator.py`：唯一的产品编排 owner，拥有当前 Board、
  PreviewStore、`last_source_mode`、canvas→ref 绑定、抓图调度、导航和侧栏快照；
- `MainWindow` 只持有一个 coordinator 引用，不新增跨 mixin 的裸状态簇；
- Inspector context 只编辑 `UltraViewBoardState`，不持有源 View 状态副本。

## 4. Board、页面和交互规格

### 4.1 页面结构

UltraView 是 `ChartStack` 的第六页，内部使用普通 QWidget 布局：

```text
UltraViewPage
├── ViewLibraryPanel（页内左栏，默认约 224 px，可收起）
└── BoardColumn
    ├── BoardToolbar（名称、布局、添加、复制、导出、演示）
    ├── CompareRail（全部 / 时间 / 频率 / 时频 / 阶次）
    ├── BoardGrid（QWidget 卡片网格）
    └── UnplacedTray（标题条常驻，内容可折叠）

MainWindow 外部右侧：既有全局 Inspector 的 UltraView context
```

进入 UltraView 时，全局 FileNavigator 自动收起；其进入前持久状态在 coordinator
中保存，退出 UltraView 时恢复。若进入时是瞬态 `PEEK`，按 `HIDDEN` 恢复，不恢复
悬浮态。全局右 Inspector 维持用户进入前的开/关状态。

UltraView 模式中，顶栏左侧“导航面板”按钮改为收起/展开**页内 View 库**，不改变
全局 Navigator 的保存状态。离开 UltraView 后按钮恢复控制全局 Navigator。

### 4.2 View 库

- 按 `SOURCE_SECTIONS` 分组显示所有 manager 中的 View；
- 行内容：section、颜色点、完整名称、当前四态、是否已在 Board；
- 搜索匹配 section 中文/英文、View 全名和来源摘要；
- 单击行只选择，不切换源工作区；
- `+` 按钮或拖到空槽/卡片执行添加/替换；
- 同一 ref 已在 Board 时不重复添加，改为定位并选中现有卡片；
- `missing` View 允许加入；无效 section/ref 不进入状态；
- orphaned 卡片的“重新绑定”进入 replacement-armed 状态并聚焦 View 库，下一次
  添加/拖入替换该卡；Esc 取消，不弹独立选择器对话框。

源工作区的共享 `ViewTabBar` 右键菜单新增“加入总览”：

- 当前可见 View：先按稳定契约尝试抓图，再加入/定位；
- 非当前 View：只加入引用，不后台切换或渲染，通常先显示 `missing`；
- 时域 split 中按被右击的 View ref；分析区按该 section 的 View ref，预览语义仍是
  整个 Analysis View（单 pane 或双 pane 合成），不是单独 pane ref。

### 4.3 模板与比例

| `layout_id` | 槽位数 | 产品名称 |
|---|---:|---|
| `split_horizontal` | 2 | 左右双图 |
| `split_vertical` | 2 | 上下双图 |
| `grid_2x2` | 4 | 2 × 2 |
| `hero_left_4` | 4 | 左主图 + 3 辅图（默认） |
| `hero_top_4` | 4 | 上主图 + 3 辅图 |
| `grid_3x2` | 6 | 3 × 2 |

- 默认 `primary_ratio = 0.67`；合法范围 `[0.40, 0.80]`；按钮步长 `0.05`；
- 等分模板保留 ratio 值但不使用，切回主图模板时恢复；
- `layouts.py` 是纯几何函数，同一模板/ratio 同时驱动屏上 geometry 和导出 geometry；
- 屏上 Board 始终适应可用 viewport，不提供整板 zoom/pan 控件；
- 卡片 chrome 不随 Board 整体缩小，文字始终使用正常 UI 字号；
- 拖拽只交换/替换 slot，不持久化任意像素坐标；
- 每个拖放处理必须在 `dropEvent` 内立即物化 MIME 数据，不把 `QMimeData` 留给
  queued callback。

### 4.4 容量与未放置托盘

所有“容量驱动的移位”使用同一状态操作：

- 从大模板切到小模板：超出新容量的 ref 按原槽位顺序进入托盘；
- 满板继续添加：新 ref 进入托盘，不拒绝、不丢失；
- 用新 ref 替换已占用卡片：旧 ref 进入托盘；
- 从托盘拖到已占用槽：旧 ref 回托盘，新 ref 入槽；
- 已放置 ref 拖到另一个已放置 ref：交换槽位，不进托盘；
- 托盘标题条始终可见；第一次产生溢出或恢复出非空托盘时自动展开；
- `移到未放置` 只取消 placement，仍保留 Board membership；
- `从总览移除` 才从 placements/unplaced 中彻底删除 ref。

### 4.5 卡片、选择与菜单

每张卡片至少显示：View 颜色点、完整名称、section 标签、来源摘要、轴类别/单位/
范围、状态标记、预览图、临时放大和打开原 View入口。

卡片右键菜单固定包含：

1. 打开原 View；
2. 临时放大；
3. 替换；
4. 移到未放置；
5. 从总览移除；
6. 复制本卡图像。

Inspector 提供相同的非拖拽路径：前移、后移、移到槽位、设为主图、比例 ±5%、
替换、移到未放置、从总览移除。Tab 键可遍历库、卡片、托盘和 Inspector 操作；
拖拽不是任何关键动作的唯一入口。

### 4.6 对比轨道与一致性提示

- `全部 / 时间轴 / 频率轴 / 时频轴 / 阶次轴` 只改变非目标卡片透明度，不删除、
  重排或改变 BoardState；该临时过滤不持久化；
- `axis_kind` 使用结构化枚举，不从标题文本猜测；FRF 和 FFT 均属于 frequency；
- 同 axis kind 的非空标准化 `x_unit` 超过一种时显示“量纲不一致”；
- axis kind 与 unit 相同，但有限 `x_range` 的端点差异超过
  `abs_tol=1e-9 + rel_tol=1e-6 * max(|a|, |b|)` 时显示“X 范围不一致”；
- 提示只防止误读，不自动同步范围，不宣称跨域可以数值比较。

### 4.7 临时放大、打开来源和快捷键

- 双击卡片或点击放大按钮打开只读焦点层；默认 fit，缩放上限为存储 raw 像素的
  100%，不把低分辨率预览放大成伪清晰；
- 焦点层底部必须有可点击的“打开原 View”按钮；
- 打开原 View 后，coordinator 先切换到 ref.section，再按稳定 `view_id` 定位；
- 打开来源是 UltraView 的导航边界。进入源工作区后发生的项目恢复重算属于源工作区，
  不清空或消费 `_analysis_restore_pending` 以替 UltraView 补图；
- orphaned 不执行跳转，改为进入重新绑定流程；
- UltraView 中 `Alt+1…9` 明确 no-op，不得落入时域 View 切换；
- Esc 优先级：焦点层 → replacement-armed → 演示模式 → 普通弹出菜单。

### 4.8 演示模式

演示模式临时隐藏：页内 View 库、全局右 Inspector、Board 编辑控件和托盘内容；
保留 Board 名、状态和退出入口。coordinator 记录进入前的页内库开关、Inspector 的
持久状态和托盘展开状态，退出时精确恢复。演示状态不持久化。

## 5. 四态投影模型

`PreviewRecord.status` 不是可写字段，按以下优先级派生：

1. ref 不再能从对应 manager 解析：`orphaned`；
2. 无 image、image 已被淘汰或图像不满足有效尺寸：`missing`；
3. 当前 presentation digest 可得且等于 `captured_digest`：`fresh`；
4. 其余情况：`stale`。

| 状态 | 图像行为 | 文案/动作 |
|---|---|---|
| fresh | 正常显示 | 放大 / 打开原 View |
| stale | 保留上次有效图，不伪造新图 | `源已变化` / 打开原 View |
| missing | 不绘制假数据 | `尚无可用结果，UltraView 不会后台计算` |
| orphaned | 有旧图则保留并覆盖删除提示 | 重新绑定 / 从总览移除 |

View 改名和 tab color 改变只刷新卡片 chrome，不应把图像标 stale。无法计算当前
digest 时不得乐观判 fresh：有旧图判 stale，无图判 missing。

## 6. Presentation digest 契约

### 6.1 总则

- digest 按需计算：捕获时保存一份，Board 显示/刷新状态时重新计算；
- 不为每条编辑路径新增第二套推送式 source revision；
- 使用带 `digest_schema=1` 的规范 JSON（key 排序、稳定 tuple/list 编码）和 SHA-256；
- 禁止使用 Python 随机 hash；禁止为求 digest 全量 hash 大数组；
- digest 构建失败可记录节流 warning，但不能把预览标 fresh。

### 6.2 时域 payload

必须包含：

- `attached_file_ids / checked / hidden_channels / colors / plot_mode`；
- `xlim / ylims / overlay_primary / axis_opts`；
- 项目级 filter payload：`enabled / spec / show_original / show_filtered`；
- 已绘 X 和 Y 通道的 resolved-data signature，复用
  `render_profile.source_revision_for()` 或同一已解析数据签名；它必须对未变化数组稳定，
  并覆盖派生通道的新增、替换和删除；
- 画布 markup revision。

排除 `name / tab_color / view_id / 当前列表下标 / 当前选中状态`。抓图上下文会隐藏
瞬态 cursor/hover item，因此游标位置和 `cursor_mode` 不进入 digest。

### 6.3 分析 payload

必须包含：

- `panes` 的 sources、rpm/input/output role、time/effective range、X/Y ranges；
- `params`（计算参数和显示参数）、`compare`、pane structure；
- 每个 pane 当前绑定的真实 cache key；
- 通过 `_store_analysis_result` 唯一写入漏斗维护的 result generation；只有 cache
  binding 新增，或同 key 绑定到不同 result 对象时推进；同 key/同对象的 cache-hit
  回写不推进，避免无图像变化却瞬时 stale；
- 画布 markup revision。

排除 View 名称、tab color、View 下标、瞬态 cursor/hover 位置。`weighting`、
`db_reference`、`db_reference_mode` 已由 params 覆盖，不另建平行字段。

### 6.4 markup 与 transient overlay

- 各 canvas 的标注 owner 暴露单调递增的 `markup_revision`；add、move、remove、clear
  都必须推进；空操作不推进；
- 抓图使用可逆 context manager 暂时隐藏 hover、crosshair、cursor readout、选择框等
  瞬态 item，并在异常时通过 `finally` 恢复；
- 用户创建的持久点标注仍保留在像素里，并由 markup revision 参与 stale 判定。

## 7. 预览产生与稳定性契约

### 7.1 只抓当前真实可见画布

P0 不遍历非活动 View 重画，只在以下时机产生 capture candidate：

1. 时域 `_render_view_to_canvas()` 将把某 canvas 从旧 ref 切到新 ref 的入口处，
   先抓旧 ref；coordinator 的 canvas→ref 绑定区分真正切换与同 View replot；
2. 分析 View/模式离开前，抓当前可见 Analysis View；
3. 进入 UltraView 前，抓当前可见 View；时域 split 分别抓两个 View，Analysis View
   始终按当前 1/2 pane 合成抓一张；
4. 源 View 的“加入总览”动作；
5. 分析结果已实际绘制到可见 canvas 后；cache/store 在前、plot 在后，capture 不能
   直接挂在 `_store_analysis_result` 的写入时刻；
6. 源工作区发生只改显示的可见 replot 后。

同一个 `(ref, digest)` 的 queued capture 只保留一个。晚到 capture 发布前重新核对
ref、digest 和 canvas 绑定；不一致则丢弃，不把旧帧标 fresh。

### 7.2 时域安全挂点

时域带 `xlim` 的 View 切换会以 `defer_first_frame=True` 暂时绑定空数组。因此：

- 切换时只能在 `_render_view_to_canvas()` 覆盖旧 scene **之前**捕获旧 View；
- 不允许“切到新 View 后立即 grab”作为新 View 的预览；
- 同 View `_replot_canvas_for_view()` 不得把旧 frame 写入新 ref；
- 新 View 只有在后续可见稳定事件或离开时才可产生预览。

### 7.3 稳定判据

抓取前先要求 widget 可见、尺寸有效，并按能力检查：

- `TimeDomainCanvasPG`：`quality_status().state == green`；dense raster status 为 green；
  `_interaction_state == "idle"`；`not _refresh_pending`；
- `PgLineCanvas`：`quality_status().state == green`，并应用其存在的 idle/pending 判据；
- heatmap/FRF：目标 section 没有对应运行 job、canvas 可见且尺寸有效；在实际 plot 后
  至少等待一轮事件循环；heatmap 以 `layout_geometry_changed` 做 debounce，再 queued
  一轮抓图；
- 进入 UltraView 前若当前画布不稳定，直接跳过并保留旧预览，不轮询、不 sleep、
  不为了抓图阻塞模式切换。

`quality_status_changed` 不是 post-paint 信号，不能单独作为“像素已完成”的证据。
P0 不新增 post-paint 信号；此能力进入 P1。

### 7.4 split 与尺寸判废

- 时域只有 `chart_stack.split_active()` 为真时才抓 secondary；隐藏的旧 secondary
  widget 不得抓取；
- 时域 split 的两个 View 产生两个 `PreviewRecord`，不合成一个 ref；
- Analysis View 的双 pane 产生一个组合预览，合成前只遍历 `pane_count()` 的可见 pane；
- `None`、null image、`width < 8` 或 `height < 8` 全部判失败；1×1 fallback 不得入库；
- 抓图失败：已有有效图则保持并判 stale；没有图则 missing；记录带 section/view_id/
  canvas 类型的节流 warning。

## 8. PreviewStore、DPR 与内存规格

### 8.1 像素格式

- QWidget/QPixmap 抓取和 QPixmap 创建只在 GUI 线程；
- DPR 归一化使用一个共享 helper，不新增第四份 `_pixmap_as_device_pixels`；
- Store 最终持有 DPR=1.0 的 `QImage`，其 width/height 是 raw device pixels；
- 入库统一为可预测的 32-bit 图像格式，内存按 `width * height * 4` 加固定记录开销
  统计，不按逻辑尺寸估算。

### 8.2 P0 默认预算

- `MAX_PREVIEW_RAW_EDGE = 1600`：入库时等比降采样，指 raw pixels；
- `MAX_PREVIEW_PIXELS = 16_000_000`：约 61 MiB RGBA payload；
- 最多 6 个已放置 ref 的图像为 pinned；未放置和最近访问预览按 LRU 淘汰；
- 淘汰 image 不删除 Board ref 和元数据，卡片转为 missing；
- 若 pinned 图像仍超预算，继续按比例降采样直到满足预算，不突破上限；
- Store 暴露当前图像数、raw pixel 数、估算字节和 eviction 次数供测试/诊断，
  但这些统计不写入项目。

### 8.3 焦点与导出分辨率

- 焦点层最多按 raw 100% 显示；不足视口时 fit-down；
- 导出不重新抓源 canvas，不因 2× 重新提交渲染；
- 2× 只把 Board chrome 和版面按 2× 绘制，卡片图使用 Store 中 raw pixels；不足
  目标区域时居中/留白或至多 100% 显示，不无条件二次插值放大。

## 9. 零计算与零源状态写入契约

### 9.1 UltraView 内允许

- 解析 managers 中的 ref 和显示元数据；
- 按需计算轻量 presentation digest；
- 读取 PreviewStore 的 QImage；
- 选择、拖拽、布局、ratio、托盘、过滤、演示、复制和 PNG 合成；
- 序列化/反序列化 UltraViewBoardState；
- 抓取**已经可见且稳定**的源 canvas。

### 9.2 UltraView 内禁止

- 调用 `do_fft / do_fft_time / do_frf / do_order_time`；
- 调用 `AnalysisJobService.submit / submit_batch`；
- 产生 `_store_analysis_result` 新写入；
- 调用 `_render_analysis_view_from_cache()`、`_apply_active_analysis_context()`、
  `_plot_time_on_canvas()` 或任何“为了补预览”的源重绘；
- 修改 `_analysis_restore_pending`；
- 修改源 View 的 params、panes、checked、colors、range、filter、cache key、pin 或 active；
- 通过 Navigator projection 暗中改源选择。

### 9.3 自动化证明

同一个真实 MainWindow 序列执行：进入 UltraView → 添加 fresh/missing ref → 满板入托盘
→ 2/4/6 模板切换 → 拖拽/按钮换位 → ratio → comparison filter → 焦点层开关 →
演示开关 → 复制/PNG → 保存项目 → 退出 UltraView。

序列前后必须断言：

1. 四个 `do_*` 入口调用数为 0；
2. `submit + submit_batch` 调用数为 0；
3. `_store_analysis_result` 的新 key 写入数为 0；
4. `_analysis_restore_pending` 集合 byte-for-byte 不变；
5. 五个 manager 的源 View 序列化快照、cache key/pin 集合和 active index 不变。

“打开原 View”单独测试导航正确性，不混入上述计数序列；切入源工作区后的既有恢复
重算按源工作区语义判断。

## 10. 模式接入与全局 UI 扇出

### 10.1 必须登记的运行面

- `chart_stack/_helpers.py`：`_MODE_TO_INDEX / _INDEX_TO_MODE`；
- `chart_stack/stack.py`：第六页、`hint_bar_for_mode`、`set_mode/current_mode`、
  `_all_cards`、`mark_discovered`、`set_annotation_enabled`、图片复制分支；
- `toolbar.py`：按钮、signal 注释、mode mapping、active dot、窄宽策略；
- `ui_kit/style.qss` 与 `ui_kit/icons.py`：`segment="ultraview"` 和
  `mode_ultraview()`；
- `inspector.py`：第五 context、`set_mode`、range group 第三路径、help guide；
- `window.py`：`_on_mode_changed` 第三分支、status hint bar、
  `_visible_view_tabbar`、panel toggle 路由；
- `_view_mixin.py`：UltraView 下 Alt+N no-op；
- `_project_io_mixin.py`：保存前捕获第三分支、Board 保存/恢复、source mode 映射；
- `help/__init__.py`、`ultraview-guide.html`、`hints.py`、`quickref.py`、
  `tools/gen_help_screenshots.py`。

UltraViewPage 必须提供可被 MainWindow status bar 搬运的 hint bar，避免
`hint_bar_for_mode()` 的 KeyError。

### 10.2 顶栏 1100 px 契约

- 用户可见名称固定为 `总览`，tooltip 为 `总览（UltraView）`；
- 在 MainWindow 最小宽度 1100 px 下，六个 mode 按钮、左右主要动作和 logo 都不得
  裁切、重叠或把 mode zone 推出可见范围；
- 实施先用真实 `sizeHint/geometry` 和截图证明。如果完整中文标签在 1100 px 失败，
  进入**统一紧凑态**：六个 mode 按钮同时保留 icon、隐藏文字并保留 tooltip；不能
  只压缩总览按钮，也不能直接提高 MainWindow 最小宽度；
- 是否紧凑按实际可用 center budget 与 sizeHint 判断，不复用 chart-card 的
  `_TOOLBAR_COMPACT_WIDTH` 魔数。

### 10.3 Inspector 第三路径

UltraView 不是 time，也不是 analysis manager：

- `Inspector.set_mode("ultraview")` 显示 `UltraViewContextual`；
- shared time range/filter card 和 analysis time-range reparent 路径都隐藏；
- 不把 range group reparent 到任一分析 context；退出 UltraView 时由目标源 mode 的
  既有路径重新安放；
- 未来未知 mode 在 loader/stack/Inspector 防御性回退到 time，不允许硬下标崩溃。

## 11. 项目保存与双向兼容

### 11.1 JSON 形状

顶层仍为 `schema_version: 2`，只增加可选字段：

```json
{
  "schema_version": 2,
  "current_mode": "fft",
  "ultraview": {
    "schema": 1,
    "board": {
      "board_id": "board-uuid",
      "name": "整车问题总览",
      "layout_id": "hero_left_4",
      "primary_ratio": 0.67,
      "show_titles": true,
      "show_sources": true,
      "placements": [
        {"slot_id": "primary", "section": "time", "view_id": "view-uuid"}
      ],
      "unplaced": []
    }
  }
}
```

`ProjectDocument` 的 `ultraview: dict | None = None` 追加在 dataclass 末尾以保护旧位置
参数调用。读取用 `raw.get("ultraview")`，没有字段时创建默认空 Board。

### 11.2 current_mode

- coordinator 初始化 `last_source_mode = "time"`；
- 每次进入合法 source mode 更新它；进入 `ultraview` 不更新；
- 保存时若当前为 `ultraview`，`current_mode` 写 `last_source_mode`；否则写当前源 mode；
- loader 将不属于 `SOURCE_SECTIONS` 的 `current_mode` 降级为 `time`；
- `ChartStack.set_mode` 和 `Inspector.set_mode` 对未来未知 mode 做同样防御，不再硬下标；
- 项目重开总是先落到源工作区，不自动进入全 missing Board。

### 11.3 合法化与退化

- 未知 `ultraview.schema`：保留项目其他内容，UltraView 降级为空 Board并给 warning；
- 未知 layout：改为 `hero_left_4`；非法 ratio clamp 到 `[0.40, 0.80]`；
- 非法 section/空 view_id/重复 ref/重复 slot：保留第一个合法值，丢弃后续并记录 warning；
- 合法 ref 找不到源 View：恢复为 orphaned，不删除；
- 不保存 selected card、comparison filter、焦点层、演示态、侧栏态、QImage、cache、
  digest 或运行统计；
- 旧应用打开新项目：因为顶层仍是 v2 且 `current_mode` 是旧版已知值，能打开；旧应用
  再保存会静默丢弃 `ultraview` 字段，这是 P0 明确接受的向后写回代价。

## 12. 整板复制与 PNG 导出

- `layouts.py` 以 `BASE_BOARD_SIZE = 1600 × 900` 计算固定版面；1× 输出该尺寸，
  2× 输出 3200 × 1800；
- 屏上和导出共用模板、ratio、padding 和 slot 顺序，不共用 QWidget screenshot；
- 离屏 `QPainter` 绘制 Board 名、卡片 chrome、来源摘要、状态和所有 slot；
- 导出完整 Board，不受当前滚动位置、页内库、Inspector、托盘展开或 comparison filter
  的瞬态状态影响；未放置托盘不进入整板图；
- fresh/stale/orphaned 的有效旧图按状态输出；missing 输出明确占位，不伪造曲线；
- 复制整板图与 PNG 使用同一个 compositor；单卡复制使用 Store 中同一 QImage；
- 图片分配/保存失败必须 toast + warning，不得静默产生 1×1 或空文件；
- gutter 使用 UltraView 自己的布局常量，不复用现有两条 split 合成路径中不一致的
  4×scale/8px 规则。

## 13. 最终成品效果

用户点击顶栏“总览”后，全局文件/通道导航收起，中央出现一个带页内 View 库的
UltraView 页面，右侧仍是 Inspector。默认 Board 为“左主图 + 3 辅图”，每张卡片
保留源 View 名称、颜色、来源、轴信息和清晰状态。用户可以从库添加，也可以在源
View 的右键菜单中“加入总览”；布局装满时新项进入底部托盘，不丢失。

用户切换 2/4/6 图模板、调整主图比例、按轴类别弱化无关卡片，双击某卡进行只读
核对，需要修改或重算时点击“打开原 View”。整个 Board 阶段不产生分析任务。
最后可复制或导出一张固定版面的完整 PNG，用于评审、汇报或问题记录。

## 14. 验收契约

以下 ID 是实施 plan、测试名和最终验收报告的共同索引；实现不得只写“基本完成”。

### 14.1 身份与状态

- **UV-A01**：`UltraViewRef` 只接受五个 GUI section 和非空稳定 `view_id`。
- **UV-A02**：Board 内 ref 唯一；模板缩容、替换、满板添加不丢 ref，统一入托盘。
- **UV-A03**：源 View 删除后卡片保持槽位并变 orphaned；重新绑定复用 replacement flow。
- **UV-A04**：四态严格按 ref/image/digest 派生；digest 不可得时不判 fresh。
- **UV-A05**：改名/颜色不 stale；源、参数、范围、filter、数据、markup、结果变化会 stale。

### 14.2 页面与交互

- **UV-A06**：六个固定模板和 ratio 规则确定；屏上 QWidget 网格始终适应 viewport。
- **UV-A07**：页内 View 库可搜索、添加、定位重复项；全局 Navigator 进入/退出可逆。
- **UV-A08**：托盘标题常驻，溢出自动展开，拖拽与按钮路径等价并可持久化。
- **UV-A09**：卡片右键菜单、Inspector 操作、焦点层和“打开原 View”均可用。
- **UV-A10**：comparison filter 不改布局；单位/范围提示基于结构化元数据。
- **UV-A11**：演示模式和 Esc 优先级正确，退出后恢复页内库/Inspector/托盘状态。
- **UV-A12**：UltraView 下 Alt+N no-op；关键动作不以拖拽为唯一入口。

### 14.3 预览正确性

- **UV-A13**：时域 View 切换只在覆盖前抓旧 ref，同 View replot 不串槽。
- **UV-A14**：进入 UltraView、源动作和分析绘制后只在稳定判据满足时抓图。
- **UV-A15**：time split 分别抓两个 ref；Analysis split 只合成可见 pane 为一个 ref。
- **UV-A16**：DPR 统一到 1.0 raw QImage；null 或任一边 <8 的图绝不入库。
- **UV-A17**：瞬态 cursor/hover 不进图；持久 markup 进图并推进 digest。
- **UV-A18**：相同 `(ref,digest)` 防抖；晚到帧的 ref/digest/binding 不匹配即丢弃。

### 14.4 零计算与源隔离

- **UV-A19**：四个 `do_*` 入口在完整 UltraView 操作序列中调用数为 0。
- **UV-A20**：`submit/submit_batch` 调用数和 `_store_analysis_result` 新写入数均为 0。
- **UV-A21**：`_analysis_restore_pending`、源 View 快照、cache/pin 和 active index 不变。
- **UV-A22**：UltraView 不调用 cache restore/源 replot 补图；打开来源后的行为归源工作区。

### 14.5 模式与项目兼容

- **UV-A23**：ChartStack、Toolbar、Inspector、Window route、hint bar、view shortcut 全部识别第六页。
- **UV-A24**：1100 px 顶栏六 mode 无裁切/重叠；若需要紧凑，六个按钮统一 icon-only。
- **UV-A25**：顶层 schema 保持 2；`ultraview` 增量 round-trip；旧项目缺字段可打开。
- **UV-A26**：保存 UltraView 时 `current_mode` 为最后 source mode；未知 mode 加载回 time。
- **UV-A27**：合法缺失 ref 恢复 orphaned；非法 layout/ratio/ref/重复项按规格退化并 warning。
- **UV-A28**：旧版可读取新项目的现有部分；旧版再保存丢 UltraView 是已记录的接受限制。

### 14.6 导出、内存与帮助

- **UV-A29**：Store raw edge/pixel budget、pinned/LRU、统计和生命周期清理均有测试。
- **UV-A30**：复制与 PNG 1×/2×走同一离屏 compositor，输出完整 1600×900 基准版面。
- **UV-A31**：2× 不重抓、不计算、不把卡图超过 raw 100% 插值放大；失败用户可见。
- **UV-A32**：hints、quickref、UltraView guide、帮助截图模式和打包资源同步。
- **UV-A33**：1280×800、1600×900、Retina/普通 DPI 的四态/演示自动截图可比较。
- **UV-A34**：macOS Cocoa 前景确认圆角、间距、拖拽、焦点层、侧栏恢复和导出观感；
  offscreen 测试不能替代该门禁。

## 15. 分期边界

### P1（有 P0 使用证据后）

1. 可选 preview sidecar（优先级 P1-1），解决项目重开后全 missing；
2. 节流 post-paint signal（P1-2），替代 P0 的能力判据/queued capture；
3. 只读 cache-result 独立 renderer，cache miss 仍不计算；
4. 超过 6 图、自由网格或多 Board，必须以真实使用数据证明需求。

### P2

一次只允许一个卡片临时 live 化；其余仍是 QImage。不得把六个 live canvas 常驻，
不得把源 QWidget reparent 到 Board。

## 16. 当前证据边界

本 spec 已对当前源码中的 mode 硬映射、项目 v2 白名单、时域 deferred first frame、
分析缓存写入漏斗、SidePanelController 静态绑定、DPR helper 重复和 split 生命周期做
了源码核对。尚未证明：

- 1100 px 顶栏是否实际必须进入 icon-only 紧凑态；
- 16M raw pixel 预算在典型 6 图数据上的真实峰值和响应时间；
- macOS Retina、普通 DPI 与 Windows frozen 包的最终视觉；
- 用户实际使用后是否需要 sidecar、超过 6 图或单卡 live 化。

因此当前结论是 **GO for P0 implementation**，不是功能已经完成，也不是前景/Windows
验收已经通过。
