# 时域通道拖放与左侧顺序管理 Spec

- 日期：2026-08-18
- 状态：待用户确认后实施
- 基线：`main@8383a7ee`
- 配套计划：
  [`2026-08-18-timedomain-drag-drop-and-navigator-order-implementation.md`](../plans/2026-08-18-timedomain-drag-drop-and-navigator-order-implementation.md)
- 产品范围：TraceLab 时域页、左侧文件卡片、左侧通道树、右侧横坐标设置

## 1. 一句话结论

> 在左侧把通道拖入时域 View 即可加入并绘图；把通道拖到最底部横坐标带即可切换为
> “按各来源匹配同名通道”的自定义横坐标。排序只发生在左侧：拖文件卡片移动整个文件块，
> 拖通道行改变该逻辑源内部顺序；画布内不提供曲线/分屏行拖动。分屏顺序严格投影左侧
> 顺序，横坐标匹配失败只降级对应曲线，不拒绝整个操作。

## 2. 本次收敛后的范围

### 2.1 要做

1. 通道行拖到某个时域 View 的绘图区：加入目标 View 并立即绘图。
2. 通道行拖到时域画布最底部横坐标带：将该通道名设为自定义横坐标，并同步右侧
   “图表设置（横坐标 · 时间范围）”。
3. 左侧文件卡片可上下拖动排序；一个物理文件展开出的多个逻辑源作为一个文件块移动。
4. 左侧通道树中的通道行可上下拖动排序，但只能在同一逻辑源/栅格内移动。
5. 分屏行、叠加绘制顺序、图例顺序统一从左侧文件/通道顺序推导。
6. 多文件使用自定义横坐标时自动在各 Y 通道所属逻辑源中匹配同名 X 通道；缺失或
   不可用的来源按分屏/叠加规则降级。
7. 文件顺序和文件内通道顺序随 `.tlproj` 项目保存与恢复。

### 2.2 明确不做

- 不支持在画布内拖动曲线或分屏行排序。
- 不支持把通道从文件 A 拖进文件 B；跨文件先后关系由文件卡片顺序决定。
- 不支持拖动一个物理文件内部的 raster/逻辑源次序；它继续采用加载器给出的顺序。
- P0 只拖一个通道；蓝色多选仍用于批量勾选/菜单，不把多选集合隐式塞进拖拽负载。
- 不把拖放扩展到频谱、时频、阶次、频响分析画布。
- 不改变时间范围语义，不做跨来源插值、重采样或截短对齐。
- 不把排序写进通道配置 preset；排序属于当前工作区/项目，而不是可跨数据集套用的配置。

## 3. 默认产品决策

### D1 — 排序是工作区级，不是每个 View 各存一套

文件顺序和每个逻辑源内的通道顺序在所有时域 View 中一致。不同 View 仍各自保存文件
附件、勾选通道、隐藏状态、颜色、坐标与范围，但不允许 View 1 和 View 2 对同一文件
显示两套互相矛盾的通道树顺序。

原因：左侧文件卡片是全局已打开文件清单，通道树是焦点 View 在同一个全局通道目录上的
投影。采用工作区级顺序后，“左侧看到的顺序 = 每个时域 View 的绘制顺序”，不需要增加
第二套排序开关或只在特定 View 可见的隐藏状态。

### D2 — 文件块优先，文件内通道其次

有效绘图顺序的唯一算法为：

```text
workspace_file_order
  → 每个物理文件块内部的 logical-source/raster 加载顺序
    → channel_order_by_fid
      → 过滤为当前 View 已勾选且未移除的通道
```

因此：

- 拖文件卡片会把该文件下的全部已选通道作为连续块一起上移/下移；
- 拖通道只改变它在所属逻辑源块内的位置；
- 分屏模式按上述扁平顺序从上到下建行；
- 叠加模式按上述顺序绘制并生成图例；
- 同一通道只出现一次，不因反复拖入 View 而重复。

### D3 — 数据身份与同名匹配分开

- 通道身份始终是复合键 `(fid, raw_channel_name)`；MIME、View 勾选、颜色、Y 范围和
  诊断都携带复合键。
- “同名自动匹配”只用于自定义 X 解析：拿拖入通道的 `raw_channel_name`，到每条 Y
  通道所属的同一 logical source/fid 中查找。
- 不用文件显示名、通道截断文本、单位或前缀字符串作为身份键。
- 一个物理文件即使展开出多个逻辑源，也不能从兄弟 logical source 借 X 数据。

## 4. 当前代码基线与差距

| 能力 | 当前基础 | 需要补齐 |
| --- | --- | --- |
| 文件拖拽 | `_FileRow` 已生成 `INTERNAL_FILE_FIDS_MIME`，通道面板已接收它来加入文件范围 | 文件列表内的 Move drop、插入指示线、文件块顺序状态与项目保序 |
| 通道拖拽 | 通道树有复合 `(fid, channel)` 数据 | `_CheckTolerantTree.mouseMoveEvent` 当前拦截所有左键移动，需增加不破坏拖选保护的显式通道拖动 |
| 通道顺序 | `get_checked_channels()` 按树遍历顺序返回 | `set_checked_channels()` 当前转成 `set`，只恢复勾选成员；需把工作区顺序作为独立权威并重投影树 |
| View 状态 | `ViewState.checked`、`attached_file_ids` 已保序持久化 | 明确其成员语义；绘图顺序统一由工作区顺序排序，不新增第二个 View 内排序字段 |
| 自定义 X | `CustomXAxisSpec(PER_SOURCE_NAME)` 已支持各来源同名解析 | 增加拖放入口，并把 Inspector 与应用事务抽成同一写路径 |
| 部分失败 | `TimePlotBuildResult`、诊断 pill 已支持 `已绘制 N/M` | 分屏需为失败项保留占位行；叠加沿用跳过 + 提示 |
| 分屏/叠加重建 | pyqtgraph 按输入顺序建轴；已有顺序变化全量重建回退 | 排序后受控重建，并恢复 X/Y 范围；不尝试画布内移动轴对象 |
| 主/副 View 路由 | 已有 `focused_canvas()`、`_view_index_for_canvas()` | drop 必须以鼠标所在 card/canvas 为准，先聚焦再写目标 View |

## 5. 交互契约

### 5.1 通道拖动起点

通道拖动只可从通道叶子行的名称/空白正文区域开始：

- 左键位移超过 `QApplication.startDragDistance()` 才启动；普通点击保持原选择行为。
- 复选框区域继续只负责勾选，不启动拖动。
- “显示/隐藏”眼睛列继续只负责显示状态，不启动拖动。
- 文件、source、raster 父节点不作为通道拖动起点。
- `Ctrl+click`、`Shift+click` 和现有蓝色批量选择不变。
- 拖动一个已被多选的通道时，P0 负载仍只有按下的那一个通道。

拖动过程中显示通道色点、完整通道名和来源短名；名称被截断时 tooltip/drag preview
仍显示完整原名。

### 5.2 通道拖入时域 View 绘图区

drop 目标是鼠标实际所在的 `TimeChartCard`：

1. 若处于左右对比，鼠标所在主栏/副栏先成为焦点。
2. 将来源 fid 加入目标 View 的 `attached_file_ids`（已存在则 no-op）。
3. 将复合通道键加入目标 View 的 `checked`（已存在则 no-op）。
4. 目标 View 立即重绘；其他 View 不改。
5. 保留当前可见 X 范围和已有通道 Y 范围；新通道只对自己的 Y 范围做一次当前可见
   X 窗口内的自适应。
6. 若通道已在目标 View 中，接受 drop、聚焦该 View，并给出轻提示，不创建重复曲线。

画布接收区不包含最底部横坐标带；横坐标带优先解释为 §5.3。

### 5.3 通道拖入最底部横坐标带

横坐标 drop zone 使用画布实际最底部可见 AxisItem/标签区域，不写死截图像素。进入时：

- 横坐标带出现蓝色描边/浅底高亮；
- 提示 `设为横坐标：<完整通道名>`；
- 绘图区不同时显示“加入 View”高亮，避免双重语义。

drop 后固定生成：

```text
CustomXAxisSpec(
    mode="channel",
    resolver="per_source_name",
    source_fid=None,
    channel=<raw_channel_name>,
    label=<raw_channel_name>,
)
```

随后执行一个原子事务：

1. 聚焦鼠标所在时域 card，并解析对应 View index。
2. 把右侧横坐标来源切换为“指定通道”。
3. 选择按来源同名匹配的候选项，标签框同步为通道原名；最终坐标标题继续由已有单位
   cohort 逻辑决定。
4. 写入目标 `ViewState.axis_opts.x_axis`。
5. 清理自定义 X 相关 envelope/monotonicity 和 FFT-vs-Time 显示缓存。
6. 因 X 语义改变，目标 View 的 `xlim` 置空并按新 X 数据范围成图；Y 范围按既有规则
   保留/恢复。
7. 展示真实 `successful/attempted` 结果，不因 0/N 或部分失败回滚选择。

Inspector 的“应用”按钮与 drop 必须调用同一个 `apply_time_xaxis_spec(...)` 服务；禁止
为拖放复制 `_apply_xaxis()` 的缓存清理、状态捕获和重绘逻辑。

### 5.4 文件卡片上下排序

- 文件列表 viewport 接收现有文件 MIME；在卡片之间显示一条插入线。
- drop action 为 `Qt.MoveAction`；同一 MIME 拖到通道面板仍保持 `Qt.CopyAction` 加入
  文件范围，两种目标按接收区区分。
- grouped file card 下的全部 fids 原子移动，不拆散、不改变 raster 内部顺序。
- 活动文件、已附加 View、勾选、颜色、过滤、游标和缓存身份均不因排序改变。
- 排序后文件卡片、通道树文件/source 节点与可见时域画布一次性同步；当前可见主/副栏
  都保留 X/Y 范围。
- 把卡片放回原位置为 no-op，不触发重绘或项目脏状态。

### 5.5 通道树内部排序

- 只允许通道叶子在同一个 fid/raster 父节点内移动。
- 拖到另一文件、source、raster 或父节点时显示禁用光标，drop 不改变状态。
- drop 位置有 before/after 插入线；放回原位置为 no-op。
- 搜索非空时仍允许把通道拖到 View/X，但禁用树内排序，避免隐藏行造成不可见跳跃。
- “已选”过滤打开时允许在可见已选通道间排序；被过滤掉的未选通道保持彼此相对顺序。
- 排序后当前可见时域主/副栏按新顺序重建；保留 X 和已有 Y 范围。
- 在分析模式的只读/候选投影中禁用通道树内部排序；工作区文件卡片仍可排序。

## 6. 自定义 X 的匹配与降级

### 6.1 每个目标通道独立解析

对于目标 Y `(fid_y, channel_y)`，只执行：

```text
files[fid_y].data[dragged_raw_channel_name]
```

并复用现有校验：来源存在、通道存在、X/Y 长度一致、时间范围掩码来自
`FileData.time_array`、范围内存在有限 X、单位 cohort 可兼容。禁止：

- 用第一个成功文件的 X 数组给其他文件；
- `min(len(x), len(y))` 静默截断；
- 自动插值、重采样或猜采样率；
- 用显示前缀后的名称匹配原始列名。

### 6.2 分屏模式

每个已选目标通道都占一个有序 slot：

- 成功：正常曲线行。
- 失败：同位置保留占位行，显示来源、目标 Y、所需 X 和原因，例如：
  `yuandi / MotorTorque：无对应横坐标 VehicleSpeed`。
- 占位行不可缩放、无游标读数，但保留与正常行相同的上下节奏；删除/取消勾选该 Y 后
  slot 消失。
- 全部失败时仍显示 N 个占位行和 `0/N` 诊断，而不是空白画布或回到 Time。

占位不仅覆盖 `missing_x_channel`，也覆盖 `unaligned`、`empty_after_time_range`、
`non_finite_x`、`x_unit_incompatible` 等可恢复数据问题，并展示准确原因。

### 6.3 叠加模式

- 不创建失败曲线，也不创建空轴。
- 其余成功曲线继续绘制。
- 诊断 pill 显示 `⚠ 已绘制 N/M · K 条未绘制`，详情按有效绘图顺序列出来源和原因。
- 全部失败时保留自定义 X 选择并显示 0/N 空态；不弹阻塞对话框、不拒绝 drop。

## 7. 状态与持久化契约

### 7.1 单一顺序所有者

新增一个 Qt 无关的 `NavigatorOrderState` 协作者作为唯一顺序所有者：

```text
file_fids: list[str]
channel_order_by_fid: dict[str, list[str]]
```

`FileNavigator` 和通道树只是它的投影/手势入口；MainWindow 只通过明确方法请求排序、
重新投影和重绘，不直接在多个 mixin 写散落列表。

模型规则：

- 注册文件：未知 fid 追加到 `file_fids`；通道按加载器原序初始化。
- 刷新通道：保留仍存在通道的相对顺序，新通道按加载器原序追加，已删除通道移除。
- 关闭文件：对称移除 fid 和对应通道顺序。
- 重复/未知/已删除身份在 restore 时过滤；其余顺序稳定。

### 7.2 `.tlproj` 格式

- `ProjectDocument.files` 的数组顺序继续作为文件顺序权威；保存时按
  `NavigatorOrderState.file_fids` 输出，遗漏的有效 fid 兜底追加。
- `ProjectFileRef` 增加可选 `channel_order: list[str]`。
- 项目 schema 从 2 升到 3，同时继续读取 1/2；旧项目无 `channel_order` 时使用加载器顺序。
- 一个物理文件的多条 logical-source ref 必须连续保存，恢复后重新合并为一个卡片；每条
  logical source 保留各自的 `channel_order`。
- 项目文件缺失时沿用既有 degraded restore；缺失项从顺序中删除，其余相对顺序不变。

`ViewState` 不增加 `plot_order`：

- `checked` 继续保存复合通道成员并保持兼容序列化；
- 运行时在绘图前统一通过 `NavigatorOrderState.order_checked(...)` 排序；
- `colors`、`hidden_channels`、`ylims`、`overlay_primary` 的复合身份不变。

## 8. 拖放负载与 Qt 生命周期

### 8.1 MIME

新增版本化内部通道 MIME，例如：

```json
{
  "version": 1,
  "kind": "channel",
  "fid": "logical-source-id",
  "channel": "raw_channel_name"
}
```

- 不携带 numpy/pandas 数据、文件路径或显示名；接收方用复合键回查当前模型。
- 未知版本、未知 fid、已删除通道、畸形 JSON 一律 ignore，不抛出 Qt virtual。
- 文件 MIME 保持现有兼容格式；file-list 接收方只接受当前已知且同属一个卡片的 fids。

### 8.2 生命周期

- `QDrag` parent 使用稳定的顶层 window/host，不绑定可能在 drop 后重建的 channel item
  或 file row。
- `QDrag.exec_()` 返回前不得 `deleteLater()` 拖动源；树/卡片重投影若会替换源 widget，
  必须等 drag finished 后执行。
- drop 处理只发结构化 intent；状态服务完成校验后再投影，不从 renderer 直接写 MainWindow。
- 合成 `QDragEnterEvent/QDropEvent` 的测试必须保持 `QMimeData` Python 引用与事件同寿命。

## 9. 视觉、反馈与可访问性

| 状态 | 呈现 |
| --- | --- |
| 可加入 View | card/plot viewport 浅蓝描边，提示 `加入 View N` |
| 可设为 X | 最底部横坐标带单独高亮，提示 `设为横坐标：…` |
| 可排序 | 文件/通道目标位置显示 2px 插入线 |
| 禁止跨父节点 | 禁用光标，不显示插入线 |
| drop 成功 | 非阻塞状态提示；不使用确认框 |
| 部分失败 | card 内诊断 pill；分屏另有逐行占位 |

所有 drop zone 设置 accessible name；拖放的等价键盘/菜单入口保留：通道勾选仍可加入曲线，
右侧 Inspector 仍可设置横坐标。排序 P0 可增加右键“上移/下移”作为无鼠标替代，但不新增
多级菜单。

## 10. 验收标准

1. 从通道名称区拖到单 View 绘图区，未选通道立即加入；重复 drop 不重复。
2. 左右对比时，拖到副栏只修改副栏绑定的 View，并同步焦点和右侧 Inspector。
3. 拖到最底部横坐标带后，右侧变为“指定通道”，保存/切 View/重开项目后状态一致。
4. 三个文件含同名 X 时分别使用本来源 X；一个缺失时：分屏保留对应占位行，叠加跳过
   该曲线并显示 N/M；操作不被拒绝。
5. X/Y 长度不一致不截断、不借用其他来源数据，并进入可恢复诊断。
6. 拖文件卡片后，文件卡片、通道树文件块、分屏行和叠加图例按同一顺序变化；grouped
   卡片内部 logical sources 不拆散。
7. 拖通道后只改变同 fid 内顺序；跨父节点 drop 无副作用。
8. 普通点击、复选框、眼睛、Ctrl/Shift 多选和“左键拖动不扩展蓝色选择”合同无回归。
9. 排序/加入通道保留当前 X；已有通道 Y 不被重置，新通道按可见 X 自适应一次。
10. 搜索态不允许内部排序但仍可拖到 View/X；分析投影不允许内部通道排序。
11. `.tlproj` v3 往返保留文件与通道顺序；v1/v2 使用默认加载顺序并正常打开。
12. 真实 macOS 前台完成 channel→plot、channel→X、file reorder、channel reorder 四个原生
    手势；离屏 Qt 测试不能替代该验收。

## 11. 回退策略

- 交互回退：关闭 drop receiver 与内部排序入口，原复选框/Inspector 路径仍完整可用。
- 状态回退：忽略 `channel_order` 即退化为加载顺序；文件数组仍是合法项目文件。
- schema 3 为可选字段增量，旧项目读取不受影响；若实施发现必须写不可逆迁移，停止并
  回到本 Spec 复审，不在实现中临时扩大范围。
