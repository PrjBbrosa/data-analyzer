# BLF / DBC 导入与 CRC 时间域交互性能 — Product / Engineering Spec

日期：2026-07-23
状态：Draft for implementation
依据：`docs/analyzer/reviews/2026-07-23-recent-blf-dbc-channel-ui-review.md`

## 1. Outcome

本规格把近期 BLF / DBC / 通道 UI 审查中的遗留问题与 `EPS_CRC1` 的持续卡顿合并为一套可验收的优化契约。完成后应满足：

1. 同一次打开或拖放动作中的多个 BLF 可以统一选择 DBC，但该选择绝不跨到下一次导入动作；
2. DBC 候选发现和校验不会长期占用 GUI 主线程，也不会因同一组 DBC 的路径顺序不同而重复逐帧扫描；
3. 文件进度反映实际阶段，原始 BLF、候选 probe 和 decode 不再固定停在 40% 或 50% 后跳完；
4. 勾选、取消勾选单个通道时保留未变化的绘图对象，不再无条件重建整个时间域画布；
5. CRC、滚动计数器及相似高变化离散信号在首次显示和缩放窗口中使用稳定的显示策略；
6. 平移过程中优先复用现有曲线几何，仅在交互结束后对最新窗口做一次高质量 `setData()`；
7. 原始数组、游标读数、统计、过滤和导出始终使用完整数据，显示降采样不得修改分析结果；
8. 当前已修正的通道行对齐、配置栏高度/宽度和 DBC 对话框文字不得回归。

## 2. Evidence And Current State

### 2.1 真实 CRC 样本

本轮使用用户提供的真实文件只读复核：

- BLF：`testdoc/blf/20251203 - EPSc对比EPSdp log/T1EJ Sine/0kph-100-6.blf`
- DBC：`testdoc/blf/T1TP_2503.DBC`
- 通道：`EPS_CRC1`

当前机器、项目 `.venv` 的结果：

| 指标 | 实测 |
|---|---:|
| BLF 大小 | 1,984,688 bytes |
| CAN 帧 | 44,207 |
| 解码行数 | 5,727 |
| 解码信号 | 143 |
| `EPS_CRC1` 离散值 | 256（0–255） |
| 读取 BLF | 约 128–137 ms |
| DBC decode | 约 197–202 ms |
| 单通道 `plot_channels()` 返回 | 约 47–55 ms |

结论：该问题不是“文件过大”或“点数过多”。加载和解码总计约 0.34 秒，卡顿热点在绘图对象重建与交互重绘。

### 2.2 首次勾选热点

对单个真实 `EPS_CRC1` 的 `plot_channels()` profile 显示：

- 总计约 55 ms；
- `_add_plot_item()` 约 43 ms；
- 其中 pyqtgraph `PlotItem` / `ViewBox` / context menu 与图标初始化约 20–40 ms；
- 首帧 envelope 构建执行两次，合计约 8 ms；
- `_ch_changed()` 会进入 `_replot_canvas_for_view()`，最终对当前选择集合执行完整 `plot_channels()`。

因此，勾选一个通道会让未变化的 PlotItem、ViewBox、轴、曲线与菜单一起重建。CRC 的 envelope 增加了成本，但不是首次勾选的唯一主因。

### 2.3 平移热点

当前生产契约是：每个不同可见窗口都要计算 envelope，并调用真实 `PlotDataItem.setData()`。40 ms refresh timer 只合并事件，没有取消这一行为。

真实 CRC 离屏拆分测量：

| 路径 | 平均耗时 / 行为 |
|---|---:|
| envelope 数值计算 | 约 0.005 ms |
| `setData()` Python 调用 | 约 0.037 ms |
| `setData()` 后强制 grab 绘制 | 约 4.37 ms |
| 仅 ViewBox transform 的中间帧 | 约 0.76 ms |
| 拖动结束后单次 settle refresh | 约 0.83 ms + 单次约 4.17 ms 绘制 |

离屏结果不能替代 Retina/macOS 或 Windows 前台实测，但它确认了因果关系：慢的不是 envelope 算法本身，而是每次 `setData()` 使 pyqtgraph/Qt 曲线几何缓存失效，随后必须重新生成并光栅化路径。中间帧只做坐标变换时，强制绘制成本降低约 82%。

### 2.4 CRC 策略窗口不稳定

当前 `high_variation_bucket_width()` 根据“当前 envelope 中大跳变的比例”判断是否使用 350 桶上限：

- 全范围初始 envelope：2,862 点，大跳变比例约 70.5%，触发 350 桶，最终约 714 个显示点；
- 约 16 秒平移窗口：1,600 个可见点，大跳变比例约 44.9%，低于 50% 阈值，不触发上限；
- 同一窗口若先按 350 桶生成 envelope，大跳变比例又约为 70.3%。

这证明分类结果受到“先用什么桶宽生成 envelope”的影响。同一通道会在全范围与局部窗口之间切换策略，局部平移时显示点反而从约 714 增至约 1,600。

### 2.5 Post-implementation correction: AA is the dominant CRC cost

用户前台复测指出卡顿与抗锯齿工作状态直接相关。随后对同一真实
`EPS_CRC1` 做纯 ViewBox transform + Qt grab 隔离测量：

| 绘制状态 | 平均 | P95 / 最坏 |
|---|---:|---:|
| AA off + NoCache | 2.23 ms | 约 2.42 ms |
| AA on + NoCache | 1,044 ms | 约 1,091 / 1,100 ms |
| AA on + DeviceCoordinateCache | 302 ms | 约 395 / 1,014 ms |

AA 切换动作本身约 0.003 ms，慢的是后续 Qt 对密集离散折线的抗锯齿
光栅化。原 gate 只看到 cap 后约 714 个 displayed points，小于 subplot
12,000 点预算，因而在 idle 150 ms 后错误重开 AA。结论修正为：
`setData()`/buffer 是必要的次级优化；dense-discrete AA 错误放行是本真实
fixture 的主因。

### 2.6 Native AA cannot meet both fidelity and frame budget

同一真实 fixture 的后续扫描证明，继续降低 bucket 数也不是可接受的
答案：直接 Qt AA 需降至约 32 个显示点才接近 33 ms，此时每个
bucket 横跨约 3.6 s，会生成不存在的长连线。屏幕空间 RDP 在
1/2/4 px 容差下仍保留约 1,846/1,129/685 点，不能进入帧预算。

可行方向是保留 native AA hard gate，但为 `dense_discrete` 提供
“视觉平滑栅格层”：settled 后以高分辨率透明 `QImage` 绘制当前
buffer envelope，下采样后以 data-coordinate pixmap 附着到原 ViewBox。
交互期间只 transform 该位图，安静窗口后重生成。这是视觉
AA 等效路径，不得宣称 Qt native AA 已开启。

### 2.7 其他审查遗留

本规格同时继承审查报告的发布阻断项：

- DBC 历史候选最多 20 组，身份仍受路径顺序影响；
- 全候选 probe 为 `候选数 × 全部帧数`，且发生在 GUI 主线程；
- 相关回归仍有 12 个失败，不能以专项 86 个用例通过替代；
- raw BLF assemble、候选 probe 的进度权重不真实；
- 混合格式导入可能改变输入顺序；
- 最后一个 BLF 不匹配时的“当前及后续 0 个”文案错误；
- 配置管理器尚未区分 `None` 与显式空选择。

## 3. Goals

### G1 — 交互先响应，最终帧再精化

鼠标拖动期间不为每个 range event 重建曲线数据。画布先用现有几何完成 ViewBox transform；交互停止后，仅对最新 viewport 进行一次高质量 refresh。

### G2 — 显示策略稳定且与通道名无关

是否采用高变化离散显示策略由原始信号特征和显示密度决定，并按数据 revision 缓存。不得因通道名包含 `CRC`、文件是 BLF，或当前窗口先前使用了不同桶宽而改变。

`dense_discrete` 必须独立于 displayed point count 硬拒绝 idle AA 和 export
临时 AA；普通 smooth 低密度曲线继续允许 idle AA。

single/subplot 的 `dense_discrete` 在资源预算允许时使用视觉平滑
栅格层；绘制失败、超过内存上限或模式不支持时，回退到已验证的
native-AA-off PlotDataItem，不得回退到卡顿的 native AA。
混合 subplot 中，已被 ready raster 替代的 dense PDI 不参与 native-AA
密度与开关；普通 smooth 曲线仍可独立进入 idle/export AA。任一
dense raster 未 ready 或回退时，high-raster-cost 仍硬阻断整个场景开启 AA。

### G3 — 勾选只修改必要对象

当 mode、轴分组和绘图参数不变时，通道选择变化使用 delta 更新：新增、移除或显隐对应 line/axis；未变化的 PlotItem、ViewBox、PDI、范围和缓存保持身份不变。

### G4 — DBC 校验有界、可取消、可理解

候选去重，低成本预筛与完整 probe 分层；耗时工作不阻塞 GUI，用户能看到候选状态并取消。本次选择只作用于本次导入事务。

### G5 — 进度真实而不假精确

已知总量的阶段显示确定型进度；无法获得细粒度总量的阶段显示不确定态和明确阶段名。百分比单调递增，完成只能在数据登记/首帧真正完成后发生。

### G6 — 证据闭环

纯逻辑测试、Qt 离屏几何/行为测试、真实 BLF 探针与前台实机交互分别记录，不互相替代。

## 4. Non-goals

- 不改变 DBC 解码结果、零阶保持语义或共享 `Time` 轴模型；
- 不对原始 CRC 数据做平滑、插值或永久抽样；
- 不在本阶段替换 pyqtgraph 或引入 GPU 渲染框架；
- 不承诺进度条是剩余时间 ETA；
- 不把一个导入动作选中的 DBC 记为下一次动作的默认统一选择；
- 不以后台线程包装所有工作作为性能答案：Qt item 创建、`setData()` 和 paint 仍必须在 GUI 线程完成；
- 不在本规格中重新设计已经验收的通道树和配置栏视觉样式。

## 5. Import Transaction And DBC Scope

### 5.1 Import transaction

每次以下任一用户动作创建一个新的 `ImportTransaction`：

- 点击“打开”并确认一组文件；
- 一次拖放事件中的全部文件；
- 由项目内部显式发起的一次批量导入调用。

事务至少携带：

```text
transaction_id
ordered_inputs
blf_inputs
dbc_policy = undecided | per_file | shared_for_remaining
shared_dbc_set
cancel_token
progress_ledger
```

事务结束、取消或失败后，`dbc_policy` 和 `shared_dbc_set` 立即失效。下一次导入必须重新确认。

### 5.2 Ordered inputs

`ordered_inputs` 是用户输入顺序的唯一事实。BLF 可以共享 DBC 策略与候选索引，但不得通过“先处理全部 BLF”改变登记顺序。

重复路径必须有明确策略：同一事务内按规范化绝对路径去重，并在状态栏说明跳过数量；不得用 dict 最后一次覆盖来悄悄改变进度映射。

### 5.3 Batch DBC decision

当事务包含至少两个 BLF 时，对话框提供：

- `逐个选择`：每个 BLF 独立确认；
- `取消`：终止本次事务，不登记尚未处理的文件；
- `统一选择 DBC`：选择一次并应用到本事务当前及后续 BLF。

按钮必须使用完整文字，依据 `sizeHint()` 加统一 padding；不得用固定窄宽度截断。共享 DBC 在某个文件不匹配时，提供：

- 为当前文件重选，并应用到后续 `N` 个 BLF；
- 仅跳过当前文件；
- 停止本次导入。

当 `N == 0` 时，文案只写“为当前文件重选”，不得出现“当前及后续 0 个”。

## 6. DBC Candidate Pipeline

### 6.1 Canonical identity

候选 DBC 集合的身份是规范化绝对路径的无序集合。身份计算应处理 `realpath`、平台大小写规则与重复路径；UI 显示顺序独立保存，优先保持用户最近选择顺序。

以下两组必须视为同一候选：

```text
[T1TP_2503.DBC, TestRunOutput(1).dbc]
[TestRunOutput(1).dbc, T1TP_2503.DBC]
```

### 6.2 Two-stage matching

候选匹配分两层：

1. **结构预筛**：读取 DBC 的 arbitration ID 集合，与读取 BLF 时顺带得到的 CAN ID 计数表比较；复杂度与唯一 ID 数有关，不逐帧 decode；
2. **完整 probe**：只对预筛得分最高的有限候选执行现有 decode probe。

默认自动完整 probe 上限为 3 组。该值必须是一个有名称、可测试的策略常量，而不是散落的 magic number。

### 6.3 Ranking and early completion

排序至少考虑：

1. 完整 probe 的 strong / weak；
2. 可解码帧覆盖率；
3. 解码信号数；
4. 最近成功使用时间；
5. 结构预筛分数。

找到明显 strong 的首选项后可以结束自动 probe。未自动 probe 的候选仍可显示为“未校验”；用户主动展开或选择时再后台校验。不得把未校验项伪装成不匹配。

### 6.4 Threading and cancellation

- 文件读取可以复用现有 worker/导入协调器；
- DBC parse、结构预筛和完整 probe 在非 GUI 线程运行；
- GUI 更新通过 signal/slot 返回；
- 每个结果携带 `transaction_id` 与 generation，过期结果必须丢弃；
- 取消后不再登记文件，不再弹出属于旧事务的对话框；
- GUI 线程连续不可响应区间目标小于 50 ms。

## 7. Progress Contract

### 7.1 Progress ledger

进度不再由调用层手写固定 40% / 10% / 50%。每个事务建立阶段账本：

```text
read_blf_bytes
index_can_ids
probe_candidate_frames × candidates_actually_probed
decode_frames
assemble_output_rows_or_signals
register_file
first_plot_prepare
first_plot_bind
first_plot_paint
```

只有实际发生的阶段进入总工作量。候选数变化时，账本可以扩展总量，但已显示百分比不得倒退。

### 7.2 Determinate vs indeterminate

- 可以获得 bytes、frames、rows 或 channel count 时使用确定型进度；
- 第三方库不提供细粒度回调时使用不确定型动画，并显示“读取 BLF”“校验 DBC”“组装原始字节通道”等阶段名；
- 不允许在仍进行超过 500 ms 的工作时长期显示固定 40% 或 50%；
- 100% 只在最终对象登记完成或绘图首帧完成后显示。

### 7.3 Raw BLF

`_raw_blf_channels()` 必须接受 progress callback，在 payload 拆分和共享时间轴组装过程中按已处理 frames / IDs / channels 推进，或明确进入不确定态。不得从读取阶段约 40% 直接跳到完成。

## 8. Time-domain Render Architecture

### 8.1 Render states

时间域画布显式区分：

- `idle`：没有交互，显示 settled viewport 数据；
- `interactive`：鼠标平移/缩放正在进行；
- `settling`：最后一次范围变化后等待安静窗口；
- `rebuilding`：选择、mode 或数据 revision 引起结构变化。

默认 settle debounce 为 100 ms，可在 80–120 ms 内经真实交互基准调整。40 ms timer 可以保留用于 UI 合并，但不得继续把每个 distinct window 转换成一次 `setData()`。

### 8.2 Interactive path

进入 `interactive` 后：

1. 关闭抗锯齿并保留现有低质量策略；
2. 冻结非必要的 axis retick、stats、range listener 广播；
3. 让 ViewBox 对已有 PDI 几何做 transform；
4. 当前 viewport 仍位于已绑定的 buffer window 内时，禁止 `setData()`；
5. 仅当 viewport 离开 buffer 且出现明显空白风险时，最多按 10 Hz 更新一次 coarse buffer；
6. 每次新 range event 只更新“最新目标范围”，旧 refresh 不排队。

### 8.3 Settled path

交互结束或 100 ms 内没有新 range event 后：

1. 读取最新而不是最早的目标范围；
2. 生成覆盖 viewport 左右各 25% 余量的 buffer envelope；
3. 每条可见曲线最多执行一次 `setData()`；
4. 一次性更新 axis ticks、visible range signal、cursor 与必要 stats；
5. 若 generation 已过期，结果不进入 Qt item；
6. 通过质量门禁后恢复 idle 抗锯齿。

对于 `dense_discrete` single/subplot，第 6 步改为原子替换最新的
高分辨率平滑位图，原 PlotDataItem 仅作为生成中/失败时的非 AA
回退。旧 generation、旧 viewport、旧 DPR、旧颜色或旧 data revision
结果不得进入场景。

### 8.4 Stable render profile

每个 `(data_id, channel, data_revision)` 计算一次 `RenderProfile`，输入必须来自原始数组，而不是当前 envelope。至少记录：

```text
source_length
finite_count
monotonic_time
approx_unique_count
transition_fraction
normalized_step_quantiles
discrete_small_domain
```

策略至少包含：

- `general`：沿用通用 viewport envelope；
- `dense_discrete`：CRC、rolling counter、高频离散状态类；
- `overflow_wall`：数据 Y span 远大于当前可见 Y span。

`dense_discrete` 的初始 bind 和所有 viewport 使用同一 profile，不得随当前窗口的 envelope 判定在 capped / uncapped 之间抖动。现有 350 bucket budget 可作为 settled 默认上限；interactive coarse budget 不得更高。精确值通过视觉误差和帧耗时测试校准。

AA affordability 不得只使用 cap 后点数。任一可见 `dense_discrete` profile
都视为 high-raster-cost：idle timer 不开启曲线 AA，复制/保存也不临时强开
AA；质量状态必须显示具体阻断原因和通道名。

视觉平滑层 ready 时，质量状态应为 green，提示“平滑曲线已完成
（高分辨率缓存）”；生成中为 yellow；只有回退时才保留 red 及
high-raster-cost 原因。状态文案不得把栅格平滑误报为 native AA。

### 8.5 Single-pass envelope

先从 `RenderProfile` 选择有效 bucket width，再执行一次 envelope。禁止当前“先按完整宽度生成 → 根据结果分类 → 再按 350 生成”的双 pass。

通用信号若只有 viewport 才能判断的 `overflow_wall`，允许一次有证据的重算，但应记录 telemetry；不得把 CRC 常规路径建立在重复计算上。

### 8.6 Display cache

缓存键至少包含：

```text
data_id, channel, data_revision, render_profile,
buffer_window_or_tile, bucket_width, y_overflow_key, mode
```

缓存必须有容量上限和 LRU 淘汰，不可随平移窗口无限增长。数据过滤、companion 变化、自定义 X、mode、DPR 或数据 revision 改变时只失效相关项。

栅格缓存键还须包含 ViewBox 的 X/Y data rect、输出像素尺寸、DPR、
颜色/线宽和可见性 revision。位图物理分辨率为
`logical_size × max(2, DPR)`：DPR1 获得真正 2×，DPR2 不得再创建 4×
临时图并调用 `QImage.scaled(SmoothTransformation)`。单项上限 16 MiB，
全局上限 64 MiB；超限时回退非 AA 曲线。`QImage` 可在无 GUI 对象的工作路径中构建，
`QPixmap`/`QGraphicsPixmapItem` 的创建、替换和销毁必须留在 GUI 线程。
原 PDI 保留数据边界和业务可见性，不能通过隐藏整个 PDI 代替光栅；
应仅在 raster ready 后抑制 vector pen，并在 `setData`/改色后重新同步。

对于大型通道，可在后续阶段引入多分辨率 min/max pyramid；真实 `EPS_CRC1` 的数值 envelope 只有微秒级，不得把 worker/pyramid 作为本轮首要修复。

## 9. Channel Selection Delta Contract

### 9.1 Selection diff

`_ch_changed()` 必须先比较前后 render model：

```text
added_channels
removed_channels
visibility_changes
unchanged_channels
structural_changes
```

当 mode、轴分组、自定义 X、过滤和 source revision 未改变时：

- 新增：只创建新曲线及必要轴；
- 删除：只移除对应 item，并清理该通道缓存；
- 显隐：只切换 item visibility；
- 未变化项：PDI、ViewBox、轴对象身份保持不变；
- X/Y 范围、游标和已存在通道的显示缓存保持不变。

### 9.2 Structural rebuild

只有以下情况允许完整 rebuild：

- overlay / subplot 模式切换；
- 轴分组拓扑变化无法增量表达；
- 自定义 X、过滤结果或数据 revision 改变；
- View 恢复的 render model 与现有画布不兼容；
- 明确的恢复/容错路径。

完整 rebuild 必须在性能日志中给出 reason，不得用“selection changed”无条件清空所有 envelope/cache。

### 9.3 Statistics

勾选变化时，首帧绘图优先于非可见统计。统计可以复用缓存或在首帧后计算，但显示值必须最终一致；禁止在 GUI 主线程为每次 checkbox toggle 重算全部已选通道的完整统计。

## 10. Data Fidelity And Interaction Correctness

- `channel_data` 继续持有完整原始数组；
- cursor、双游标差值、极值、统计、FFT、过滤和导出读取原始数组或明确的分析结果，不读取显示 envelope；
- settled envelope 必须保留每个 bucket 的 min/max 和时间顺序，不漏掉可见尖峰；
- 点击 Home、程序化 `set_xlim()`、项目恢复和导出截图必须有确定的 settled refresh，不得永远停留在拖动预览；
- 两个文件同名通道继续使用 composite key，缓存不得交叉污染；
- split View 的交互状态、range generation 与 selection delta 彼此独立。

## 11. Telemetry And Diagnostics

扩展现有 `TRACELAB_PERF` 探针，但默认关闭且近似零开销。一次交互输出聚合摘要而不是逐帧刷日志：

```text
interaction_id / canvas_id
range_events
transform_only_frames
coarse_setdata_calls
settled_setdata_calls
envelope_ms_total / max
setdata_ms_total / max
paint_ms_total / p95 / max
displayed_points_before / after
render_profile
full_rebuild_reason
```

DBC 导入摘要至少包括：候选集合数、去重数、结构预筛数、完整 probe 数、strong/weak、各阶段耗时、取消/过期结果数量。

## 12. UI Regression Contract

本轮性能修改不得破坏：

- 通道行 checkbox、色标、文字、Pts 和眼睛的固定列锚点；
- 选中背景只改变颜色，不改变内容几何；
- 配置栏“保存 / 选配置… / 应用”渲染高度一致；
- 保存和应用保持窄宽度，中间下拉框获得剩余宽度；
- DBC 批量对话框完整显示三个动作文字；
- 对话框在 macOS 与 Windows 的默认按钮、Esc 和关闭语义一致。

## 13. Acceptance Matrix

### A. CRC / time-domain interaction

真实 fixture 与同形合成 fixture 均需满足：

1. `EPS_CRC1` 的 `RenderProfile` 在全范围和 16 秒窗口中均为同一策略；
2. 初始 bind 每条曲线只执行一次 envelope；
3. 1 秒连续拖动、至少 20 个 range event：buffer 未越界时 `setData()` 为 0；越界 coarse 更新不超过 10 次；settle 后对最新范围恰好 1 次；
4. 当前基准的 transform-only 中间帧优势必须保留：离屏 P95 至少比“每帧 setData”路径降低 50%；
5. 目标机器前台拖动无大于 100 ms 的 GUI stall，输入响应 P95 小于 50 ms；
6. 单通道 warm checkbox delta P95 小于 30 ms；完整结构 rebuild 必须有明确原因；
7. settled 显示保留每个 bucket min/max，cursor/stat/export 与原始 5,727 点一致；
8. DPR 1×/2×、single/subplot/split View 的平滑层通过；overlay 若本轮
   不启用，必须显式回退且不得开启 native AA。
9. 真实 `EPS_CRC1` native idle/export AA 均保持关闭；平滑栅格 ready
   后 transform repaint P95 小于 16 ms，包含 envelope、轴更新和栅格替换的
   完整 settle P95 小于 25 ms；
   普通 smooth 低密度曲线的 idle AA 回归通过。
10. 真实 fixture 产出 non-AA fallback 与平滑栅格的离屏对比图；
    缓存层的 data-coordinate 反向映射误差接近浮点精度，cursor/
    stats/export 仍与原始 5,727 点一致。
11. 混合 subplot 中 dense 曲线使用 raster 且 native AA 为 off，
    general smooth 曲线 idle/export AA 为 on；交互期间 smooth AA 关闭，
    settle 后恢复。dense 缓存回退时两者均不得开启 AA。

绝对前台指标必须在 macOS Retina 与一台 Windows 目标机实测。离屏通过只能作为行为与相对性能证据。

### B. DBC / import

1. 路径顺序相反的同一 DBC 集合只 probe 一次；
2. 自动完整 probe 不超过策略上限 3；
3. 27 MB / 611,013 帧 fixture 的 probe 不阻塞 GUI，期间窗口可移动、可取消；
4. mixed input 登记顺序与用户输入顺序一致；
5. 新导入事务重新确认 DBC，不继承上一次 shared policy；
6. mismatch `N == 0` 文案正确；
7. raw BLF assemble、candidate probe、decode 均有真实阶段反馈；
8. 过期 worker 结果不弹窗、不登记文件。

### C. Regression and visual

1. 审查报告中的 12 个相关回归失败全部关闭；
2. BLF / DBC / progress / channel widget / file navigator / pg canvas / hotpath 相关测试 0 failures；
3. 通道树、配置栏、DBC 对话框分别生成 Qt 离屏截图并做几何断言；
4. macOS 前台至少复核：批量导入、统一 DBC、CRC 勾选、连续拖动、取消勾选；
5. Windows 前台至少复核文字裁切、DPR 和 CRC 拖动。

## 14. Rollout And Fallback

- 分主题提交，不把 DBC、进度、通道 UI 与 render architecture 混成一个不可回滚提交；
- 新交互 renderer 在首个阶段保留一个开发期 fallback 开关，用于 A/B 测量；发布前决定是否移除；
- 若 delta selection 发现不兼容状态，允许记录 reason 后退回完整 rebuild，但不能静默长期走 fallback；
- worker 失败时显示可理解错误，并允许用户手动选择 DBC；不得在 GUI 线程同步重试全部候选；
- 任何性能优化若改变 cursor/stat/export 结果，必须回滚，不以帧率换分析正确性。

## 15. Definition Of Done

以下全部满足才可将本规格标为完成：

- 验收矩阵 A/B/C 有对应自动化或实机证据；
- 相关测试 0 failures，现有 12 个失败不再作为“旧测试”遗留；
- 真实 `EPS_CRC1` 的首次勾选和拖动日志证明没有逐 range `setData()`；
- 真实 27 MB BLF 证明 DBC probe 不阻塞 GUI，候选已去重且有界；
- 进度阶段与完成时点符合实际工作；
- 视觉几何离屏通过，关键交互有 macOS 前台证据，Windows 验证结果明确；
- 文档、用户帮助和必要的 lessons 已同步；
- 工作树按主题形成可独立回滚的提交，未夹带无关修改。
