# 分析 View 文件/通道来源隔离与可撤回试运行 Spec

- 日期：2026-08-10
- 状态：已按本轮产品决策定版，等待按配套 plan 实施试运行
- 基线：`main` @ `1617b2d0f18205298d3468c2acb291c7938365d8`
- 配套计划：
  [`2026-08-10-analysis-view-source-isolation-pilot-implementation.md`](../plans/2026-08-10-analysis-view-source-isolation-pilot-implementation.md)
- 事实审查：
  [`2026-08-10-analysis-view-channel-inspector-inheritance-review.html`](../reviews/2026-08-10-analysis-view-channel-inspector-inheritance-review.html)
- 历史前置：
  `docs/superpowers/specs/2026-06-10-analysis-multiview-pyqtgraph-design.md`、
  `docs/superpowers/specs/2026-07-20-view-file-attachment-and-channel-config-design.md`

## 1. 一句话结论

采用统一的状态模型：

> **文件数据全局只加载一份；每个分析类型下的每个 View 独立保存已加入文件；每个
> Pane 独立保存通道来源。新建为空，切换恢复，复制才继承，局部移出不级联。**

本次先实现可撤回的 Stage 1 试运行：完成 View 隔离、投影一致性和依赖保护；暂不在
第一阶段引入“关闭文件后仍持久保存不可用来源并自动重连”的宽 schema。Stage 1 对
存在依赖的全局关闭默认阻止，并允许用户明确选择级联移除，从而先验证主交互模型，
不发生静默数据丢失。

## 2. 为什么需要调整

### 2.1 用户确认的产品模型

“文件 × View × 分析”表示独立的**关联关系**，不是复制文件数据。若有 6 个文件、
每种分析 6 个 View、5 种分析，则最多存在 `6 × 6 × 5 = 180` 条文件与上下文的加入
关系；文件数组仍只有全局一份。

当前真实上限是：时域最多 12 个 View，FFT / 时频 / FRF / 阶次各最多 6 个。因此
当前最多是 36 个 View 容器；公式不依赖上限是否统一。

### 2.2 当前代码事实

1. `ViewState.attached_file_ids` 已经实现时域 View 级文件加入关系
   （`ui/view_state.py`、`ui/main_window/_channel_scope_mixin.py`）。
2. `AnalysisViewState` 已按 `Section → View → Pane → Source` 保存参数和 Pane 来源，
   但没有分析 View 自己的 `attached_file_ids`
   （`ui/analysis_view_state.py:47-64, 117-136`）。
3. `_analysis_scope_fids()` 仍以当前焦点时域 View 的 `attached_file_ids` 作为所有分析
   picker 的候选范围（`ui/main_window/window.py:2465-2499`）。
4. `_update_combos()` 为四种分析构造同一份候选列表，无法表达各 section / View 的
   独立文件范围。
5. FFT 使用左侧 navigator 的勾选作为 Pane 来源；时频、FRF、阶次在 Inspector
   选择来源。同一组左侧控件因此有多个状态主人。
6. 模式切换只 capture outgoing 状态、切页面和 Inspector，没有完整 apply 目标 active
   View；返回时域也没有强制恢复时域 View 投影
   （`ui/main_window/window.py:1468-1495`）。
7. 空分析 View 的 `params == {}`，而 `apply_params_from_state()` 对空字典 no-op，导致
   新 View 继续显示上一 View 参数（`ui/analysis_view_bridge.py:10-16`）。
8. 全局关闭文件当前会清理所有时域 View 和所有分析 View 中的该 fid
   （`ui/main_window/_project_io_mixin.py:1215-1242`、
   `_channel_scope_mixin.py:345-403`）。
9. 项目恢复 remap 遇到缺失 fid 时会直接丢弃对应分析来源
   （`ui/project_io.py:268-298`）。

所以当前并非单纯文案问题：时域加入关系、分析来源和 live 控件会通过候选刷新互相
影响，局部操作可能在后续 capture 时变成持久状态变化。

## 3. 目标

### G1 — 五种模式统一为“当前上下文”

任何时刻只有一个当前上下文：

```text
当前模式 → 当前 View → 当前焦点 Pane → 当前来源角色
```

左侧通道树、底部 View、画布与右侧 Inspector 必须同时投影该上下文。

### G2 — 每个 View 独立拥有文件范围

- 时域 View：继续使用 `ViewState.attached_file_ids`。
- 分析 View：新增 `AnalysisViewState.attached_file_ids`。
- 一个 View 的加入/移出不修改其他 View，包括同 section 的其他 View、其他分析
  section，以及时域 View。

### G3 — 来源按 Pane 独立

- FFT：`PaneState.sources` 可含多个 overlay 来源。
- 时频：`PaneState.sources` 最多一个。
- 阶次：一个 signal 来源 + 可选 `rpm_source`。
- FRF：`input_source` + `output_source`，仍必须属于同一 logical source。
- 每个来源的 fid 必须属于其父 `AnalysisViewState.attached_file_ids`。

### G4 — 新建、切换、复制语义互斥

- `+`：完整空白；不继承文件、来源、参数草稿、范围、结果或分屏。
- 切换：恢复目标对象自己的状态。
- 复制：显式复制文件、来源、参数、范围、分屏和比较设置，生成新 `view_id`。
- 模式切换：只切换到目标 section 的 active View，不继承 outgoing section。

### G5 — 删除作用域明确且不静默级联

- “从当前 View 移出”：只作用于当前 View。
- “从当前分析 View 移除来源”：只作用于当前 Pane/角色。
- “关闭文件”：全局动作，必须先汇总所有依赖；有依赖时默认取消。

### G6 — 可撤回试运行

Stage 1 使用可向后忽略的嵌套字段，不提升项目顶层 schema；实施拆成独立 checkpoint
commit。若试运行 NO-GO，可回退代码且旧程序仍能读取项目中的既有分析来源。

## 4. 非目标

- 不复制 `FileData`、DataFrame、numpy 数组或分析结果到每个 View。
- 不改变 FFT、时频、FRF、阶次数值算法和 Batch 行为。
- 不改变当前 View 上限（时域 12、分析各 6）。
- Stage 1 不实现文件关闭后的持久 unresolved source、自动重连或手动路径替换。
- Stage 1 不改变“新文件自动加入”偏好；它继续只加入当前焦点时域 View。
- 不让新分析 View 自动继承当前时域 View 文件；如需相同配置，使用复制 View，后续
  可另立显式“从时域 View 加入文件范围”功能。
- 不把切换 View 变成自动计算；仍只恢复缓存或显示“点击计算”。
- 不把 display label、短文件名或通道 tooltip 当成身份。

## 5. 术语与状态所有权

| 名称 | 含义 | 所有者 |
| --- | --- | --- |
| 全局文件仓库 | 当前进程已经加载的 logical sources | `MainWindow.files` |
| View 文件范围 | 当前 View 可浏览、可选择的文件 | 每个 `ViewState` / `AnalysisViewState.attached_file_ids` |
| Pane 来源 | 实际进入计算的通道及角色 | `PaneState` |
| 候选通道 | 当前 View 已加入文件中的可用信号通道 | section-aware candidate builder |
| 当前投影 | 左栏、画布、View 标签、Inspector 正在表达的对象 | active mode/View/focused Pane |
| 全局关闭 | 从 `MainWindow.files` 卸载数据 | Project/session owner |
| 局部移出 | 删除一条 View→file 关联 | 当前 View owner |

Stage 1 持久化继续使用现有复合来源身份：View 文件范围保存运行时 `fid`，项目保存/恢复
通过既有映射重建；通道来源使用 `(fid, channel)`。两者都不得退化为 display label、短文件
名或 tooltip。一个物理文件扩展成多个 raster/group 时，每个 logical source 独立参与加入、
来源和依赖统计。Stage 2 如实现跨路径自动重连，才必须接入 neutral stable logical-source
identity，不能把本阶段的运行时 `fid` 当成长期稳定 ID。

## 6. 目标状态模型

### 6.1 `AnalysisViewState`

Stage 1 增加：

```python
@dataclass
class AnalysisViewState:
    name: str
    tab_color: str
    panes: list[PaneState] = field(default_factory=lambda: [PaneState()])
    params: dict[str, Any] = field(default_factory=dict)
    compare: dict[str, bool] = ...
    view_id: str = ...
    attached_file_ids: list[str] = field(default_factory=list)
```

为保留既有 positional constructor 兼容性，新字段追加在所有现有字段之后，不插入
`panes`、`params` 或 `view_id` 之前。列表顺序是用户把文件加入该 View 的顺序，也是左侧
文件父节点的稳定顺序。

### 6.2 不变量

对每个分析 View：

```text
pane.sources[*].fid ⊆ attached_file_ids
pane.rpm_source.fid ⊆ attached_file_ids
pane.input_source.fid ⊆ attached_file_ids
pane.output_source.fid ⊆ attached_file_ids
```

另有：

- FFT 允许每 Pane 多来源；其他单信号分析每 Pane 至多一个 signal。
- FRF input/output 不能是同一通道，且必须来自同一 logical source。
- `attached_file_ids` 去重并保持顺序。
- 只有 state owner 可以修改 state；控件刷新不是用户意图，不能反写 state。

### 6.3 不新增第二份通道身份

Stage 1 继续使用现有 `PaneState` 角色字段，不增加平行的 selected-channel map。
`attached_file_ids` 是候选范围，`PaneState` 是计算意图，两者职责不同，不构成重复真相。

## 7. 左侧通道树的模式合同

| 模式 | 左侧文件范围 | 通道勾选含义 | 文件 `×` |
| --- | --- | --- | --- |
| 时域 | 当前时域 View attached | 当前时域 View 绘制通道 | 移出当前时域 View |
| FFT | 当前 FFT View attached | 当前焦点 Pane 的 overlay 来源 | 移出当前 FFT View |
| 时频 | 当前时频 View attached | 不可勾；来源在 Inspector | 移出当前时频 View |
| FRF | 当前 FRF View attached | 不可勾；输入/输出在 Inspector | 移出当前 FRF View |
| 阶次 | 当前阶次 View attached | 不可勾；信号/RPM 在 Inspector | 移出当前阶次 View |

左栏标题或空态必须显示当前所有者，例如：

- `时域 · View 2 文件范围`
- `频谱 · View 1 来源`
- `时频 · View 3 可用通道`

不得在非时域模式继续显示时域 View 的勾选高亮。眼睛只属于时域；文件移出是单独
动作语义，列标题不得继续用含混的“显示”。

## 8. Inspector 继承合同

### 8.1 新建分析 View

新 View 应立即显示：

- `attached_file_ids == []`；
- 一个空 Pane；
- 所有来源角色为空；
- 时间范围关闭且无范围值意图；
- 参数控件恢复该 section 的产品默认值；
- 空画布提示“先从上方文件区加入文件”；
- 不复用上一 View 的结果缓存显示。

`params == {}` 可以继续作为“使用产品默认值”的序列化表示，但 apply 必须显式调用
contextual 的 reset/default API，不能 no-op。

### 8.2 切换已有 View

按固定顺序执行：

1. capture outgoing 当前 View/Pane；
2. 切 active identity；
3. 投影目标 `attached_file_ids`；
4. 构造该 section 自己的候选；
5. apply Pane 结构、来源、View 参数、Pane 范围和游标；
6. 从缓存渲染；缓存缺失只提示计算，不自动计算。

### 8.3 切换分析模式

离开时只 capture 当前可见 section；进入时完整 apply 目标 section 的 active View。
目标已有状态就恢复；目标是初始空 View 就保持空。不得读取 outgoing Inspector 数值
作为目标默认值。

### 8.4 切换 Pane

只 capture 前一焦点 Pane 的来源/范围/游标，随后 apply 新焦点 Pane。View 级 params 和
attached files 不因 Pane 切换改变。

### 8.5 返回时域

必须重新投影焦点时域 View 的 attached、checked、hidden、颜色、轴和范围。FFT 的左侧
overlay 勾选不能写回时域 View。

## 9. 操作转移矩阵

| 操作 | 文件范围 | 来源 | 参数/范围 | 计算/缓存 |
| --- | --- | --- | --- | --- |
| 打开文件 | 进入全局仓库；按既有偏好可自动加入焦点时域 View | 不自动选择 | 不变 | 不计算 |
| 新建 View `+` | 空 | 空 | 默认/空 | 空画布 |
| 复制 View | 拷贝 | 拷贝 | 拷贝 | 可复用相同 cache key，但不自动计算 |
| 切换 View | 恢复目标 | 恢复目标 | 恢复目标 | 缓存命中即画，否则提示 |
| 切换模式 | 恢复目标 active View | 恢复目标 | 恢复目标 | 不自动计算 |
| 拖文件到左栏 | 只追加到当前 active View | 不自动选择 | 不变 | 不计算 |
| 从当前 View 移出文件 | 只删当前 View 关系 | 清理该 View 内依赖角色 | 其他状态保留 | 不做全局 cache 失效 |
| 从当前 Pane 移除来源 | 文件仍 attached | 只清当前角色 | 不变 | 当前 Pane 清图；cache 可保留 |
| 全局关闭文件 | Stage 1 先依赖 preflight | 见 §11 | cache 失效 | 取消 in-flight |
| 删除通道 | Stage 1 先依赖 preflight | 见 §11 | cache 失效 | 取消相关 in-flight |

## 10. 局部移出的精确行为

### 10.1 时域 View

沿用现有原子清理：当前 View 的 attached、checked、hidden、颜色、overlay primary 和
该文件的 exact-source X 轴引用。不得调用分析 View 清理函数，不得让分析 picker 随
当前时域 View 改变。

### 10.2 分析 View

从当前分析 View 移出文件前，统计该 View 内受影响角色：

- FFT：受影响 overlay 曲线数；
- 时频：受影响 Pane 数；
- 阶次：signal / RPM 角色数；
- FRF：pair 数。

无来源依赖时直接移出；有依赖时默认取消并显示明确范围：

> 从“频谱 · View 2”移出 Run_B，将清空 2 个 Pane 来源；其他 View 不受影响。

确认后只过滤当前 `AnalysisViewState`：

- FFT 删除该 fid 的 overlay entries；
- 时频清空对应 Pane signal；
- 阶次分别清空匹配的 signal / RPM；
- FRF 任一端命中时清空该 Pane 的完整 pair，避免保留不可计算半对；
- 当前 View 重新投影并清理对应画布；
- 不调用 `_invalidate_all_analysis_caches_for_fid()`，因为其他 View 仍可能使用该 fid。

## 11. 全局关闭与通道删除

### 11.1 Stage 1 依赖保护

新增一个无副作用 dependency preflight，按 stable view identity 汇总：

```text
Time View attachments / checked
Analysis section + view_id + pane_idx + role + channel
```

全局关闭无依赖文件时直接关闭。有依赖时使用一次确认：

> Run_B 被 2 个时域 View、4 个分析 View（7 个来源角色）使用。

按钮：

- `取消`（默认）；
- `关闭并从所有 View 移除`（明确的全局级联动作）。

确认级联后才执行现有 per-fid cache/in-flight invalidation、所有 View 引用清理和
`FileData` 卸载。不得先修改任何 View 再询问。

`关闭全部`先做一次总依赖汇总，不逐文件连续弹窗；其确认是全局动作。

### 11.2 删除派生通道

通道编辑器删除通道也属于全局 source-universe 变化。应用前展示受影响 View/Pane；
取消则不修改 DataFrame、View 或 cache。确认后按通道复合身份清理所有引用并失效
相关缓存。

### 11.3 Stage 2 最终目标

试运行通过后另立 schema gate，把“关闭并删除”扩展成：

- `关闭但保留 View 配置`；
- persisted `SourceRef` 保存 stable logical source locator + channel；
- View 显示“来源不可用”，禁止计算；
- 重新加载唯一匹配 logical source 后自动重连；
- 来源内容变化后旧缓存不得恢复，必须重新计算。

Stage 2 不在本轮试运行实现，防止一次同时验证交互模型和宽身份迁移。

## 12. 候选刷新合同

当前 `_update_combos()` 的共享列表改为 section-aware refresh：

```text
refresh(section)
  → section.active AnalysisViewState.attached_file_ids
  → still-loaded logical sources
  → that section's signal/role candidates
```

- 切分析 View、分析 attach/detach：只刷新对应 section。
- 文件加载/全局关闭/通道编辑：刷新所有 section，但每个 section 使用自己的 active
  View 范围。
- 切时域 View：不得改变分析候选。
- refresh 必须 block UI signals，且不得 capture 到任何 `PaneState`。
- saved source 暂时不在 live candidate 时，state 保持不变；Stage 1 正常路径通过关闭
  preflight 避免这种状态。防御路径显示“来源不可用”，不能自动写空。

## 13. 持久化与迁移

### 13.1 Stage 1 schema

- `AnalysisViewState._SCHEMA`：`6 → 7`。
- `to_dict()` 新增 `attached_file_ids`。
- 项目顶层 `SCHEMA_VERSION` 保持 2；旧程序忽略分析 View 的未知嵌套字段。
- 新项目/新 View 显式保存 `attached_file_ids: []`。

### 13.2 老项目迁移

旧分析 View 没有 `attached_file_ids` 时，按 Pane 顺序收集仍能 remap 的 source fids：

1. `sources`；
2. `rpm_source`；
3. `input_source`；
4. `output_source`；
5. 首次出现去重，保持顺序。

不得迁移成所有全局文件，因为那会把旧项目从“只保存实际来源”放大成未知候选范围。
旧空 View 的 union 为空，恢复后仍为空。

字段存在且为 `[]` 表示用户明确保存的空分析 View，不执行兼容补全。

### 13.3 缺失项目文件的 Stage 1 边界

当前项目 remap 会丢弃缺失 fid。Stage 1 必须至少：

- 在打开完成时报告“跳过了多少分析 View/Pane 来源”；
- 标记本次恢复为 degraded；
- 再次保存项目前默认阻止，并提示“保存会固化缺失来源”；
- 用户明确确认后才允许覆盖原项目。

完整 unresolved 保存与 relink 属于 Stage 2。

## 14. 缓存与异步任务

- View switch / mode switch / local detach 不做全局 per-fid cache invalidation。
- 全局文件关闭、通道删除、时间轴重建等数据变化继续失效所有相关 section cache。
- 正在运行的任务以 `(section, view_id, pane_idx)` 绑定；结果返回前复核 stable identity
  和 source 仍属于该 View。
- inactive/non-focused `PaneState` 是事实源；异步回调不得从当前 Inspector/navigator
  重新读取来源。
- 项目恢复的 deferred compute 继续以 `view_id` 为键，不使用可变 tab index。

## 15. 用户操作顺序

推荐主路径：

1. 打开文件，进入上方全局文件仓库；
2. 选择分析类型；
3. 选择已有 View，或点击 `+` 创建空白 View；
4. 从上方把所需文件拖入当前 View；
5. 聚焦 Pane；
6. FFT 在左侧选择 overlay，其他分析在 Inspector 选择角色来源；
7. 设置参数与时间范围；
8. 点击计算；
9. 需要相同实验条件时使用“复制 View”，需要隔离实验时使用 `+`。

不要求先在时域加入同一文件；时域检查波形是推荐步骤，不是分析来源有效性的前置
条件。

## 16. 可预见后果与缓解

| 后果 | 风险 | 缓解 |
| --- | --- | --- |
| 每种分析需要单独加入文件 | 初次操作步数增加 | 空态给出拖入指引；复制 View 保留完整配置；后续评估显式“从时域导入范围” |
| 同名 View 在不同分析下仍是不同对象 | 用户误认为共享 | 左栏显示 section + View 名；帮助页明确“同名不等于同一 View” |
| 每 section 候选不同 | picker 刷新复杂度上升 | section-aware 单入口；只刷新受影响 section |
| FFT 不再借用时域勾选 | 旧习惯改变 | FFT 左栏仍可多选，但明确标注“频谱来源” |
| 局部 detach 后当前图消失 | 用户可能以为全局删除 | 确认文案写明“其他 View 不受影响”；上方文件仍存在 |
| 全局关闭增加确认 | 高频关闭操作多一步 | 仅有依赖时确认；无依赖直接关闭；关闭全部只汇总一次 |
| 老项目分析 attachment 不完整 | 无法恢复历史候选但未选通道 | 从已保存来源推导，保持可复现意图；不猜测所有文件 |
| 多文件/多通道刷新变慢 | 左栏和 combo 卡顿 | 按 section 增量刷新、保留搜索；试运行设性能 NO-GO 门槛 |
| Stage 1 尚无 unresolved relink | 缺失文件恢复仍有限 | degraded-save guard；Stage 2 单独验收后再放开 |

## 17. Stage 1 试运行边界

### 17.1 试运行数据

- 至少 3 个文件，其中一个物理文件产生多个 logical sources；
- 两个时域 View；
- 四种分析各至少两个 View；
- FFT 两 Pane overlay、时频两 Pane、阶次 signal+RPM、FRF input/output；
- 一个含大量通道的真实工程，用于候选刷新性能。

### 17.2 GO 条件

1. 连续切换模式/View/Pane 50 次，无任何来源、attached、范围或参数被无操作改写。
2. 从一个时域 View 移出文件，不改变任何分析 View，也不改变另一个时域 View。
3. 从一个分析 View 移出文件，只清理该 View 的依赖。
4. 四种分析新 View 都是空 attached、空来源、默认参数。
5. 切回已有 View 精确恢复；切换本身不提交 compute job。
6. 项目 round-trip 保留每 section / View / Pane 的 attachment 和来源。
7. 全局关闭依赖 preflight 的数量、作用域和默认取消正确。
8. 当前文件规模下，等量候选刷新 p95 不超过基线的 1.25 倍，且不出现可感知冻结。
9. 自动化门禁通过；真实 macOS TraceLab 前台操作顺序和空态可理解。

### 17.3 NO-GO 条件

- 任一候选刷新或模式切换把非当前 state 写空；
- FFT 勾选污染时域 View；
- inactive section / Pane 在保存项目时被 live 控件覆盖；
- 局部 detach 失效其他 View 的 cache 或来源；
- 全局关闭在无完整依赖摘要时继续；
- 项目保存/恢复发生静默来源丢失；
- 大通道文件使左栏或 Inspector 进入不可接受的同步卡顿；
- 只能靠用户记忆模式例外才能正确操作。

任一 NO-GO 触发即停止扩大试运行，保留证据并回退到前一 checkpoint，不用文案掩盖
状态错误。

## 18. 验收矩阵

| ID | 断言 | 证据 |
| --- | --- | --- |
| A1 | 新 `AnalysisViewState.attached_file_ids == []`，round-trip 保序 | state 单测 |
| A2 | schema 6 老 View 从 Pane 来源推导 attachment；显式空不补全 | migration 单测 |
| A3 | 每 section 的 picker 只读取自己的 active View attachment | integration 测试 |
| A4 | 时域 View 切换/detach 不刷新或改写分析来源 | integration 测试 |
| A5 | FFT navigator capture 只写当前 FFT Pane，不写 Time View | owner/projection 测试 |
| A6 | 时频/FRF/阶次左栏勾选不可编辑，Inspector role 是唯一入口 | widget + integration 测试 |
| A7 | 四种分析 `+` 均为空且 Inspector 默认一致 | 参数/来源测试 |
| A8 | Duplicate 完整复制 attachment/source/params/range/panes，`view_id` 新建 | state + UI 测试 |
| A9 | 模式、View、Pane 切换 restore 精确且不自动计算 | integration 测试 |
| A10 | 局部分析 detach 只清当前 View；共享 cache 不失效 | dependency/cache 测试 |
| A11 | 全局关闭 preflight 默认取消；明确级联才清全局引用/cache | close-flow 测试 |
| A12 | 通道删除遵守相同依赖合同 | channel editor 测试 |
| A13 | 项目 round-trip 保存所有 section/View/Pane attachment/source | project 测试 |
| A14 | missing project source 进入 degraded-save guard | project 测试 |
| A15 | deferred restore/reorder 仍按 `view_id` + `pane_idx` | async restore 测试 |
| A16 | quickref/hints 与新语义同步 | 文案测试/人工复核 |
| A17 | 3 文件 × 多 View × 5 模式真实前台走查通过 | macOS 前台证据 |
| A18 | 大候选性能不越过 GO 门槛 | 确定性 benchmark |

## 19. 已确认决策

1. 文件数据全局共享，View 只保存关系，不复制数据。
2. 时域和四种分析的 View 都独立拥有文件加入范围。
3. 新建 View 的文件、来源均为空；复制 View 才继承。
4. 切换分析/已有 View 恢复目标自己的状态，不强制清空已配置目标。
5. 一个 View 局部移出文件不影响任何其他 View。
6. 分析来源不再以当前时域 View 为有效性前提。
7. Stage 1 对依赖中的全局关闭默认阻止，不静默清空。
8. Stage 2 再实现 unresolved source 持久化与重连。
9. 自动加入偏好在试运行中仍只作用于时域。
10. 试运行先验证状态正确性，再决定是否增加“一键从时域导入文件范围”等提效入口。
