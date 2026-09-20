# 时间范围双选项与数值联动优化计划

- 日期：2026-09-20。
- 状态：**设计与源码 review 完成；待实施。本文不是产品实现或原生 UI 验收报告。**
- 基线：`b1bc412be17742f0e7dd8c7329660607480710c4`；本轮只新增本文，未修改产品源码。
- 用户确认的方向：**全时段 / 指定范围**；保留现有开始/结束单行；全时段下不可手动输入，但仍保留图形及其他功能对时间值的联动。
- 原型：[最小改动 demo](../ui-prototypes/2026-09-20-time-range-segment-minimal.html)。本次要求覆盖原型中的两处简化：**不采用分开的开始/结束标签行；全时段的数值不是固定不变的全文件首尾。**
- 范围：时域、FFT、FFT vs Time、Order、FRF 的共享时间范围区及相关消费/恢复链路。Cursor CAA、进度条、导航区最小宽度属于其他计划。

## 1. 最终界面与语义

沿用当前卡片、单行数值、滤波位置和底部执行按钮，仅替换原勾选框与右侧“全部”所在的一行：

```text
时间范围                 （分析页沿用“分析时间”）
         [ 全时段 | 指定范围 ]
开始:    [ 0.0 s ]  — 结束 [ 43.061 s ]
```

1. 双选项表示**下次绘图/计算采用什么范围**，不用“自动 / 手动”文案。
2. 开始、结束及两个输入框始终在同一行。保持现有 `_pair_field`、标签列和左右等宽关系；不新增说明卡片、第二套数值、应用按钮。
3. **全时段**：两个输入框只读，仍可选中复制、接收程序回写。全时段计算不受这两个显示值裁剪。
4. **指定范围**：输入框可编辑；合法提交后的数值就是下一次执行的请求范围，无须再勾选。点击既有“绘图”或各分析页的计算入口才执行。
5. 切换选项只改变范围意图，不顺带 Home、重绘时域数据或提交分析任务。必要的参数显示、有效性提示、已有预览刷新可以进行，但不得冒充新计算结果。
6. 图形 Home/查看全图仍由既有图形入口承担，恢复当前已绘制数据的视图范围。它与“下次使用全时段数据”是两个独立动作。

这是最小 UI 改动，但不是简单替换控件皮肤：当前 checkbox 在时域还会立即重绘，需要在它所属的事件链路中拆开执行动作。

## 2. Review 结论与证据

以下行号对应上述基线；实施时优先按符号定位。

| 级别 | 已确认事实 / 风险 | 当前源码证据 | 计划要求 |
| --- | --- | --- | --- |
| P1，必须保留 | 未勾选时，时域视窗变化仍回写起止时间；不能把“只读”做成冻结数值 | `ui/main_window/window.py:2437` 两个 canvas 回调；`:2453` `_sync_time_range_inputs_from_visible_xlim`；`:2474` `set_range_values` | 保留回写与焦点路由；限制用户输入，不屏蔽程序更新 |
| P1，必须分清 | 全时段显示值可以是局部视窗，但绘图缓存/裁剪以范围启用状态为准 | `window.py:4160`；全时段 `cur_range_state=(False,)` | 禁止仅凭显示值变窄就改成局部计算或频繁使缓存失效 |
| P1，需调整 | 时域 checkbox 切换会捕获 View 并立即 `_replot_canvas_for_view` | `window.py:2676` `_on_time_range_enabled_changed` | 改为范围配置；既有绘图入口负责执行，保留 Custom-X 草稿保护 |
| P1，必须隔离 | 同一个范围 widget 在五个 section 之间移动；分析页另有 View/pane/source 级状态 | `ui/inspector.py:369`；`persistent_top.py:909`；`_analysis_mixin.py:1626`、`:1872` | 显示双选项不能新建五份互相争写的全局范围；恢复不得发用户信号 |
| P1，必须保留 | Custom-X 的图形横轴可能是角度/力矩等单位，不能回写秒数 | `window.py:2462` CHANNEL_MODE guard；时域绘图的物理时间 mask | 原 guard 保留；指定范围仍按采集时间筛选样本，再绘制工程量 X |
| P1，必须保留 | 分析 source-full、显式范围、未提交编辑/错误草稿是不同状态 | `analysis_time_range.py:395` controller；`_analysis_mixin.py:1707` flush、`:1750` enable | 不把 readonly、未启用和无效输入混成“默认全时段” |
| P2，需迁移 | 原“全部”在时域是 Home；在分析页是清除范围并投影来源 full，FFT 另重置预览/频谱视图 | `window.py:2637` `_on_time_range_max_requested` | 双选项不得直接绑定这条复合命令；保留实际 Home 能力 |
| P2，必须保留 | Excel/WWT 通过各自 `use_range` 读取这两个数值，并非只读全局范围开关 | `window.py:5014`、`:5059` | 不删除 `range_values()`，不擅自让主面板全时段覆盖导出对话框选择 |
| P2，需防回归 | 程序投影会更新 committed 值并清理输入修订记录 | `persistent_top.py:878` `set_range_values`、`:938` `set_range_limits` | 真实输入与图形投影必须分路；不能把回写伪装成用户编辑，也不能在键入一半时无声覆盖 |

根本问题是现有一组控件承担了三件事：**范围意图、联动数值显示、执行入口**，而“全部”和 checkbox 的动作不对称。方案统一前两者的呈现，并把执行留给原按钮；保留数值本身的消费者。

需要纠正对“全部”的概括：当前代码中时域该按钮直接执行的是恢复已绘制数据视图，不是直接调用 `plot_time()`；立即重新裁剪绘制在 checkbox 切换链路。用户看到的“一次操作连带更新图形”现象需要消除，但不能据此把两个 owner 混在一起改。

## 3. 三类范围事实及唯一所有者

| 事实 | 含义 | 所有者 / 存储 | 不可混用 |
| --- | --- | --- | --- |
| 执行范围意图 | 下次用全时段，或明确的 `(start,end)` | 时域 View `axis_opts.range_filter`；分析 `PaneState.time_range`，由 `AnalysisContext` / `AnalysisTimeRangeController` 协调 | 全时段仍为 enabled=false / time_range=None，不写成显示首尾 tuple |
| 面板显示值 | 当前有效上下文允许显示的物理时间；时域可来自当前焦点视窗 | 既有 `PersistentTop` 数值投影，来源由所属 section 决定 | 不能仅凭显示值推断用户选择、构造分析 draft 或提交计算 |
| 已绘图/已计算结果 | 当前画面实际使用的数据与参数 | 既有 canvas 数据、分析结果/cache/effective facts | 改参数后不得把旧结果标成新范围已生效 |

不新增全局 range manager，不在各 mixin 分散新增 flag。优先使用既有 View、pane、输入 revision 和 effective-facts 生命周期；若确需“待绘图”标记，放在既有范围/结果 owner 内，必须说明清除、关闭及恢复行为。

### 一个必须通过的例子

来源是 0–43.061 s，模式为全时段，用户把时域图缩放到 12–18 s：

1. 单行输入框显示 **12 s — 18 s**，保持只读，双选项仍为全时段。
2. 点击“绘图”使用来源的全时段数据；不会因为输入框显示 12–18 s 就裁剪数据。是否保留既有相机视窗沿用绘图合同，不能把“使用全数据”强制等同于 Home。
3. 切到“指定范围”时，以当前有效、同一上下文的显示范围 12–18 s 为初值；框变为可编辑，暂不重绘。
4. 点击“绘图”后才使用 12–18 s 的数据。
5. 回到“全时段”只取消下次执行的范围限制，显示继续按时域视窗联动；下一次绘图恢复全数据，Home 仍单独可用。

利用现有 tooltip 解释：“全时段使用当前来源的完整数据；这里的起止值仍随当前时域视窗变化，切到指定范围时采用。”分析页按其真实来源改写，不给所有页面套“随视窗变化”。不要为这句话新增固定行；分析页原有状态行保持原高度。

## 4. 五个 section 的联动合同

| Section | 全时段数值来源 | 保留的图形/来源联动 | 指定范围取值与执行 | 不允许的串写 |
| --- | --- | --- | --- | --- |
| 时域，时间 X | 初始化/无有效视窗时取当前有效数据；有图后取焦点 canvas 的可见时间窗口 | 主/副画布缩放、平移、Home、焦点切换与 View 恢复后的合法投影 | 首次选择采用当前有效窗口；手动编辑或既有图形回写更新请求；点击绘图应用 | 未聚焦画布不得覆盖；不能用无关最长加载文件替代已绘制上下文 |
| 时域，Custom-X | 既有物理时间范围或当前来源的物理时间边界 | 来源与 View 恢复照常；不从工程量 X 轴推算秒 | 时间 mask 先作用于采集时间与配对数组，再画 Custom-X | 不可拿角度、力矩等 xlim 写起止秒数；范围切换不得提交尚未应用的 X 轴下拉草稿 |
| FFT | 当前 pane 参与分析的来源时间边界；叠加保留逐来源覆盖事实 | 更换来源、切 pane/View、恢复项目时重新投影；现有时间预览按范围展示 | 来源 full 与显式 span 沿用 controller；点击 FFT 计算执行 | **当前 FFT 时间预览 pan/zoom 仅操作相机，不回写起止或创建 draft**；频谱 Hz 轴更不能写秒 |
| FFT vs Time | 当前 pane 信号的物理时间边界 | 来源/View/pane 投影；热图与切片已有视窗联动继续保留 | 同一 pane 范围送入 STFT 任务与 cache key；点击计算执行 | 热图缩放不自动改计算范围；时间切片与频率轴区间不冒充输入时间范围 |
| Order | 当前信号物理时间边界；RPM 来源是对齐约束 | 信号、RPM 来源/模式变化参与 signature 和校验；热图/切片联动保留 | 同一物理时间范围用于信号/RPM 对齐与计算；点击计算执行 | 不把阶次/RPM 坐标写成秒；不把 signal-full 偷缩成 RPM 交集来掩盖覆盖不足 |
| FRF | 当前输入/输出的共同物理时间范围；不相关文件不参与 | I/O 更换、交换、pane/View 恢复更新范围有效性 | 显式范围对 time/input/output 使用同一物理 mask，保留原校验顺序；点击计算执行 | 幅频、相位、相干图的 Hz 视窗不回写秒；无共同区间不能伪装可用 full |

这里“共享双选项”不等于新增“所有图形缩放都联动输入框”。当前已经确认时域有该回写；FFT 预览已有专门防误写合同，本轮保留它。后续若明确需要 FFT 预览提供范围，必须定义独立的显式选取动作，不能偷偷接回 pan/zoom。

FFT vs Time / Order 热图现有 `sigRangeChanged → _sync_slice_to_heatmap_view` 是**显示切片联动**，应原样保护，不能为了区分执行范围而断开。当前热图测试还明确：手动频率参数建立初始视窗后，后续缩放和 Home 继续更新切片（`test_manual_panel_freq_range_follows_heatmap_y_zoom`）。保留当前行为；旧 lesson 中“manual panel range 优先、不随缩放”的描述已经落后于源码，不能据此回退。

## 5. 完整事件与输入规则

| 事件 | 数值处理 | 意图与执行 |
| --- | --- | --- |
| 选择当前已选项 | 不改值 | 不重复 emit、不创建任务 |
| 全时段 → 指定范围 | 时域采用合法的当前时间投影；分析采用当前 pane 的精确 source bounds / 既有合法范围，避免用显示舍入值覆盖精确模型 | 写本上下文显式请求，开放编辑；不绘图、不 Home、不计算 |
| 指定范围 → 全时段 | 时域重新投影焦点可见时间；分析投影当前来源 full | 清本上下文显式范围与暂存编辑，readonly；不重绘/计算，不暗中恢复旧局部草稿 |
| 全时段下程序回写 | 允许 `set_range_values`、范围限制更新、来源/View 投影 | 不改变 mode、不发 range_edited、不产生 controller draft |
| 指定范围下合法编辑 | 沿用 raw text / revision / flush 机制 | 更新本上下文请求；不自动计算 |
| 指定范围下无效输入 | 保留原始错误和可修正文本，现有状态提示说明 | 不回退全时段、不取旧合法值计算、不静默钳成一个可用区间 |
| 图形回写遇到尚未提交的人工编辑 | 普通视窗更新先让当前人工编辑完成，不覆盖半输入文本；结束后由所属上下文决定下一次投影 | 不排队跨 pane 的旧回写；不将程序 `setValue` 当真实键入 |
| 点执行时输入框尚有焦点 | 先同步 flush 最后一次输入；再检查来源、范围和全部目标 pane | 通过后提交一次，失败则保持现有结果和可修正状态 |
| 换来源 / pane / View / section | 先保存离开上下文的编辑，再静默投影进入上下文；来源失效按已有 signature 合同处理 | 不能借共有 widget 把 A pane 值写进 B；不额外触发任务 |
| 空数据 / 不可用来源 | 无效状态明确；沿用当前 0.0/0.0 空态，但不得显示为可执行的有效范围 | 禁止执行，无任务、无虚构时间轴；恢复数据时重新投影 |

### 只读方式

- 用 `QAbstractSpinBox.setReadOnly(True)` 限制两只已有 spinbox，而不是隐藏字段、换成静态标签、关闭 group 或阻断更新信号源。
- 覆盖键入、粘贴、方向键、滚轮、鼠标 step 操作；仍能复制数值、看到正常 tooltip，程序写值仍可更新画面。实际 Qt 行为以探针验证，不靠假设。
- 两种模式尺寸完全一致；只读态用轻微底色/边框差异提示，文字保持清楚，不能呈现为“此处已失效”。不改全局 `CompactDoubleSpinBox` 行为影响其他数值输入。
- full 程序投影保持静默；将参数提交信号与显示更新信号分清，不能通过解绑图形信号实现只读。
- 时间必须有限且 start < end；非零/负起点按真实时间轴处理，不擅自以 0 作全部数据的下界。覆盖不足及部分叠加来源仍按既有校验报告。
- 全时段切入指定范围时，如来源本身不可用，阻止选中并给出现有错误提示；若来源存在但初始统一 span 对部分来源覆盖不足，保留“指定范围”及错误供用户修正，禁算，不能视觉显示指定而模型默认为 full。
- 不强行增加输入框 Enter 直接计算：沿用应用既有快捷键路由，保证失焦/Enter 提交不会使下方按钮又提交第二次。demo 的键盘简化不是新增产品合同。

## 6. 其他消费者与持久化

### 6.1 显示值仍是有用途的值

- **Excel / WWT 导出**：保留导出对话框自己的 `use_range` 语义。用户在全时段浏览中缩放到局部后，仍可在导出对话框明确选择该显示范围。测试同时覆盖 `use_range=True/False`，不随主范围控件只读而消失。
- **Batch 参数种子**：`window.py:5373–5477` 各 section 只在范围启用时传 `time_range`。保持全时段不给 Batch 注入局部视窗；不将 Batch 所有文件绑定到当前活动文件的显示首尾。
- **FFT 自动参数/预览、STFT、Order/RPM、FRF**：继续使用现有 pane/context 的有效范围。与共享 UI 相连的兼容 fallback 必须检查 section 与目标 pane，不能增加以 `None` 意味“不知道，于是读其他 pane UI”的分支。
- **缓存和结果**：全时段的显示回写不是数据裁剪变化。显式范围变化使下一次正确失效；已有有效结果提示按当前 owner 标记待更新，不把修改参数等同于已计算。
- **图内统计、切片、轴显示范围**：保持各自范围 owner，复核其输入是已绘数据、视窗还是独立参数。Batch 图内统计 `ChartStatisticsPanel` 的“自动 / 手动”是真实统计区间模式，与本次时间输入双选项语义不同；不一并改名、改绑定或强行套共享状态。

### 6.2 数据格式与恢复不改语义

1. 时域继续存 `axis_opts.range_filter.enabled/start/end`；全时段下 start/end 可保存显示信息，但 enabled=false 时不得参与过滤。相机范围独立恢复。
2. 分析继续用 `PaneState.time_range=None` 表示 full，tuple 表示显式请求；不序列化 UI readonly、source signature、草稿、旧视窗回调。
3. 恢复时从原模型推导分段选中与 readonly，先恢复上下文再静默投影。不能只恢复颜色而忘记编辑权限，也不能触发绘图两次。
4. 旧 full 项目正常恢复 full，不因旧 start/end 与源不同自动变指定；旧显式范围维持指定及原精度。
5. 无效旧 tuple 和覆盖失效继续报告错误，不降级为 full。关闭最后文件、删除 View、撤掉第二 pane 时清理对应上下文，不留下控件选中残影。
6. 有效的新 full 模式不再产生“未勾选但手动改了值”的正常路径。不过既有 controller 草稿、程序兼容入口、无效旧状态和多 pane 冲突仍要处理；**不能整段删掉计算前 flush / 全目标原子校验 / 取消不提交合同**。

## 7. 实现边界与调用迁移

### 控件层

Owner：`ui/inspector_sections/persistent_top.py`。使用已有 `ui_kit/widgets/segmented_choice.py` 的 `SegmentedChoice`，视觉与现有双选项一致，不引入新组件库。

该组件目前绑定一个两项 QComboBox；旧范围入口使用 QCheckBox，不能直接 `.bind(chk_range)`。建议采用项目现有桥接形式：保留 `chk_range` 作为迁移期布尔兼容入口并隐藏，分段绑定隐藏 combo；**checkbox 是兼容期模式真值，combo 只投影**。用户分段动作经一个 handler 写 checkbox 一次；checkbox 的状态变化投影 combo 并更新 readonly。所有静默恢复走统一 setter，该 setter 显式同步三者，不能依赖被 `blockSignals` 屏蔽的回调。

`range_enabled()`、`range_values()`、`set_range_values()`、`set_range_limits()`、`set_range_from_span()` 维持清晰可用的 API。UI 没有新的产品持久化枚举；full/selected 只在控件内映射 False/True。不复制一套 `_selected_range` 全局状态。

迁移应搜索全部 `chk_range` 直接读写，尤其：

- `PersistentTop.checkout_range_for_mode` / `set_range_from_span`；
- `_analysis_mixin._set_top_range_enabled_silently` / `_project_top_from_time_range_intent`；
- `_view_mixin` 的时域 restore；
- `_project_io_mixin` 的空项目 reset；
- `window.py` 信号连接和用户切换 handler。

兼容入口可以暂留，但旧“全部”不再显示；其 handler 中可复用的 Home 与 full-conversion 能力按真实调用保留或分别转接，先查消费者，不能直接删除整条链。

### 应用层

- `window.py` / `_view_mixin.py`：范围配置不再立刻 replot；保持 `_capture_range_change_into_view` 对未应用 Custom-X 的保护，绘图按钮读取目标 View 的新范围；更新“点击 checkbox 立即裁剪”的旧测试合同。
- `_analysis_mixin.py` / `analysis_time_range.py`：沿用 controller 与 pane 所有权；合法 selector 请求、无效选定输入、source-full 投影有明确转换。移除范围切换附带的 Home；FFT 预览必要刷新不等于运行 FFT。
- `inspector.py`：继续移动同一个 range group，进入每个 section 时同步只读与选中；不复制各 section 数值框。
- `AnalysisContext`、`fft_time_coordinator.py` 与各分析 mixin：只在现有边界核查/修正误读 UI 的路径；本计划不改 DSP、不改采样率推导、不重构任务调度。
- 热图/切片、导出、Batch 主要作为回归边界。未发现违约不编辑其实现。

## 8. 分步实施与聚焦验收

按顺序执行，禁止为了控件替换启动大规模 MainWindow 重构。

### T0：冻结当前合同，先补针对性失败用例

记录 HEAD、相关 dirty 范围和本计划的既有测试结果。新增只读但可程序更新、切换不计算、五 section 恢复一致的用例；更新已明确改变的“切换立即重绘”和“全部按钮位置”断言。不运行泛化的全量基线。

### T1：共享双选项、只读与单行布局

修改控件 owner、统一模式 setter、现有样式及恢复调用；两项互斥且重复选择无操作。保持起止一行与原标签/单位，正常只读文字、复制与 tooltip。

聚焦：`tests/ui/test_inspector.py` 中单行、重挂载、等宽、程序 setRange 静默相关用例；`tests/ui_kit/test_segmented_choice.py`；`tests/ui/test_inspector_width_cap.py`、`test_inspector_first_show_layout.py` 中实际涉及的布局用例。

### T2：时域范围配置与执行拆开

保留完整的焦点视窗 → 显示值路径；明确指定模式下人工编辑优先级；从切换 handler 去掉立即 replot 和 Home，保留 View 参数写入与 X 轴草稿隔离。点击绘图一次才真正更新数据。保护来源变更、分屏焦点与缓存状态。

聚焦：`tests/ui/test_main_window_smoke.py` 中未勾选视窗回写、范围切换、Custom-X mask 与草稿保留；`test_view_bridge.py`、`test_view_switch_integration.py`、`test_split_routing.py` 对应范围/焦点用例。新增 0–43.061 / 12–18 的端到端数据断言，不只看字段值。

### T3：四个分析 section 统一呈现与不同来源策略

接入现有 controller、mode checkout、pane restore、计算 preflight。全时段静默更新来源值；不把 FFT 预览、频谱与热图摄像机变成计算选择器。保持 invalid / unavailable 可解释且禁算；来源切换不无声夹断用户范围。

聚焦：`test_analysis_time_range_intent.py`、`test_analysis_time_range_confirm.py`、`test_frf_time_range_surface.py`；`test_analysis_scope_and_xframe.py`、`test_analysis_multiview_integration.py` 中相关 case；FFT vs Time/Order/FRF 的现有 range/cache owner 测试。修改数值算法不在本任务范围。

### T4：外围消费者、持久化和说明

覆盖 Excel/WWT 自有 use_range、Batch 范围种子、项目 round trip、无效/空数据恢复；热图切片五个现有联动测试作为保护。同步 `ui/hints.py`、`ui/quickref.py` 和确实描述旧交互的当前用户指南，不重写历史 demo/历史计划。

聚焦：已有导出与 Batch 参数接线测试；`test_analysis_view_bridge.py`、`test_analysis_view_state.py`；热图 `test_x_slice_follows_live_heatmap_y_zoom`、`test_y_slice_follows_live_heatmap_x_zoom`、`test_home_restores_slice_to_full_heatmap_extents`、`test_shift_wheel_on_map_refreshes_x_slice`、`test_manual_panel_freq_range_follows_heatmap_y_zoom`。消费者缺少 coverage 时补确定性 spy/参数断言，不运行大型真实导出替代接线测试。

### T5：边界门与原生界面验收

- 根据实际变更运行 `test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`；若修改 QSS，运行 `tests/ui_kit/test_qss_border_shorthand.py`；涉及 import 时跑 `test_import_boundaries.py`。没有改 canvas backref / renderer / DSP 就不把它们的全部测试列成必跑。
- Qt offscreen 验证 readonly 下键入/粘贴/键盘步进/滚轮不修改值，程序投影可修改；restore 不发用户信号；所有 section 在现有最窄允许宽度仍单行、等宽、文字不裁切。
- 真实 macOS Cocoa 实测当前 inspector 最小宽度、默认宽度、较长与负数时间值、高 DPI：分段完整、标签和单位不挤压、只读态清晰；用真实 widget geometry 与截图验收，不能把 HTML 当 Qt 证据。
- 操作链：加载 → 全时段缩放 → 切指定 → 编辑 → 绘图 → 切 full → 再绘图 → Home → 分屏换焦点 → 四分析页切换 → 来源更换 → 保存重开 → 关闭最后文件。
- 若本次发布覆盖 Windows，单列原生 Windows 验收；未运行明确标 UNVERIFIED，不以 macOS/offscreen 代替。
- 稳定变更只跑适用的聚焦与边界门。仅在发布/合并合同明确需要全套时运行一次，并遵守 acquisition_ui 独立顺序进程规则。

## 9. 最终验收清单

| 场景 | 必须观察到的结果 |
| --- | --- |
| 全时段，时域缩到局部 | 数字跟随，框只读，选中仍 full；没有执行任务或产生分析草稿 |
| full → 指定 | 显示窗口成为合法初值，允许编辑；原图数据未提前重算 |
| 修改范围后立即点绘图 | 最后未失焦输入被读取；仅执行一次，数据确实按范围裁剪 |
| 指定 → full | 不清空联动值、不附带 Home；下次执行使用全数据 |
| 全时段手动修改尝试 | 输入/粘贴/滚轮/步进均不能改值；复制和程序更新正常 |
| 图形事件与半输入文本相遇 | 人工编辑不被无声覆盖，旧事件不穿越 pane/View |
| 五个 section 来回切 | 单行布局不变，选中/readonly/值与当前 owner 一致，无其他页写回 |
| FFT 预览 / 各频率或阶次轴缩放 | 原显示联动保留，不生成意外的秒数范围或分析任务 |
| FRF/Order 来源覆盖不满足 | 可修正的明确错误，不能靠 full、夹断或 UI 舍入掩盖 |
| 两源叠加 / 无关长文件加载 | 使用当前来源事实，显示包络不伪装所有源都连续覆盖 |
| full + 导出局部 | 导出对话框 use_range=true 仍采用合法显示范围；false 仍导出全量 |
| 保存与重开 | full / 显式范围原义不变，View/pane 隔离，source/draft 不额外持久化 |

## 10. 本次 review 已运行的验证

环境：项目 `.venv/bin/python`，`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。以下 15 个现有测试一次运行：**15 passed, 30 warnings in 3.07s**。warnings 为 pyqtgraph 在 NumPy 2.5 的 shape 赋值弃用提示。

```text
tests/ui/test_main_window_smoke.py
  test_time_range_fields_track_current_visible_xlim_when_unchecked
  test_checking_time_range_uses_current_visible_xlim_without_manual_entry
  test_time_range_toggle_preserves_unapplied_xaxis_channel_draft
  test_custom_xaxis_time_range_filters_by_file_time_axis
tests/ui/test_inspector.py
  test_persistent_top_range_share_one_form_row
  test_analysis_modes_embed_time_range_in_input_card
  test_fft_preview_zoom_does_not_update_pane_time_range_when_checked
  test_max_range_button_uses_plotted_not_longest_loaded
tests/ui/test_analysis_time_range_intent.py
  test_programmatic_set_range_values_does_not_apply_user_edit
  test_pane_switch_projects_incoming_and_keeps_outgoing_draft
  test_loading_unrelated_longer_file_does_not_change_current_pane_full
  test_frf_common_range_uses_untrimmed_axes
  test_order_full_bounds_are_signal_axis_not_rpm_intersection
  test_serialized_views_omit_drafts_and_signatures
tests/ui/test_frf_time_range_surface.py
  test_frf_compute_reads_the_same_pane_range_shown_in_the_inspector
```

收尾检查发现其他工作正在修改 Cursor 显示及相关 tests、hints/quickref；本轮未触碰这些改动。实施 T4 时合并当前说明内容，不覆盖并发成果。HEAD 未变化，时间范围 owner 文件仍无 tracked diff；上述结果仅对应本轮实际完成的 focused run，不宣称整个工作区已验收。

这些结果证明当前需保留的部分合同，不证明新双选项/只读/延迟执行已实现。特别是当前“勾选立即裁剪”的通过用例在 T2 必须改为“选择后未绘制，点击绘图再裁剪”。本轮未做原生前台 UI 验收、Windows 验收或全量测试；文档新增不需要全套运行。

参考 lessons：`codex-time-range-preserve-xaxis-draft`、`fft-preview-zoom-no-auto-arm-time-range`、`analysis-compute-confirm-unchecked-local-range`、`time-range-all-uses-plotted-extent`、`pyqt-ui/2026-05-26-custom-x-time-range-filter`、`frf-range-mask-before-data-validation`、`pyqt-ui/2026-08-15-heatmap-slice-follows-live-view`。其中旧 checkbox 即时重绘、uncheck 附带预览 Home 的触发方式按本次用户确认的配置/执行分离调整；数据归属、物理时间及防误提交规则继续保留。
