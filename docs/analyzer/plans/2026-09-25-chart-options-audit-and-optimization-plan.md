# 图表选项全 section 验证与优化计划

日期：2026-09-25。状态：**W1–W3 与对话框侧 W4 已实施。Cocoa 标题几何十轮与 Windows 冻结包 DPI 验收未做。**

验证基线：`a3572d44b0fd8afa217fdbde4d6239e7ca8200d8`，开始时工作区干净。
用户要求先确认标题清空问题，再横展图表选项的所有选项、所有 section，输出优化 plan。
本轮只新增本文；诊断脚本、测量和图片保存在 `.state/chart-options-audit/`，不进入产品或测试源码。

## 1. 结论与证据边界

**标题问题确认存在，并在 macOS Cocoa 的真实 TimeDomain canvas 上复现。**

| 操作 | 标题行最大高度 | 绘图区顶端 Y | 绘图区高度 |
| --- | ---: | ---: | ---: |
| 初始无标题 | 0 | 3 | 304.5 |
| 输入标题并应用 | 30 | 33 | 274.5 |
| 清空标题并应用 | 30 | 33 | 274.5 |

以上单位为 Qt 逻辑像素，同一 900×620 canvas、同一数据与 subplot 布局。
已检查 `cocoa/title-initial.png`、`title-set.png`、`title-cleared.png` 中的实际布局；清空后的空白占位真实存在。
根因是 `PgAxisHandle.set_title()` 把 `""` 原样传入 `PlotItem.setTitle()`。
本机 pyqtgraph 只有 `None` 分支会隐藏标题并把第 0 行高度归零，空字符串仍走 30 高度的显示分支。
而且 `apply_changes()` 每次都会调用 `set_title()`，因此无标题图即使仅应用其他属性也经过这条路径。

证据等级：

- **Cocoa 真实 widget/图像**：标题几何、共用选项对话框三个 tab 的渲染与按钮位置。
- **offscreen MainWindow 集成**：FFT、FFT vs Time、Order 的真实计算/缓存重绘/新 View 路径，FRF 按钮入口。
- **真实 adapter/widget 探针**：网格往返、对数范围、非法输入、色阶、精度、同名图例。
- **源码确认**：子图/副轴/切片的入口能力、状态归属与写入链。
- **未完成的验收**：真实用户数据、所有缩放比例与长文本组合、Windows Full/Lite 冻结包前台，以及修复后的完整矩阵。不能把本轮诊断称作全平台无 bug 验收。

## 2. 问题清单（按风险排序）

### F01 · P1 · 对数坐标范围使用了错误的数值空间

复现：时域 Y 数据为 1…100；选择对数刻度、范围填 1…100，应用后曲线的绘制坐标为 0…2，ViewBox 范围却是 1…100。大量曲线被裁掉或挤到边缘，轴数值不再对应输入的工程量。

位置：`mf4_analyzer/ui/_axis_handle.py:313` 的范围读取/设置；`:335` 的 Y 范围设置；`mf4_analyzer/ui/dialogs/chart_options.py:510`。
`setLogMode()` 会变换线条数据，范围 getter/setter 却直接读写 ViewBox。现有正值对数测试只确认调用 `set_ylim(0.1, 10)`，没有核验实际显示范围。

影响：共用 PgAxisHandle 的时域、FFT 主图/预览；热图还有 F02。不能通过只修改一处通用 getter 的语义直接修复，需要先核对依赖 ViewBox 坐标的现有调用者。

### F02 · P1 · 热图允许对数轴，但 ImageItem 没有对应变换

复现：热图 Y extent 为 1…100，选择对数后 axis 报告 log；图像变换仍是线性 `m22=33`，图像没有 `setLogMode` API。坐标轴解释改变，像素/切片/读数的坐标映射仍在线性空间。

位置：`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:213` 直接继承 PgAxisHandle；`mf4_analyzer/ui/_axis_handle.py:433` 附近的 scale 写入只覆盖轴与支持 log 的曲线对象。

影响：FFT vs Time 和 Order。推荐本次禁用热图 X/Y 对数选项并说明原因；支持非线性热图必须另行设计图像映射、采样、切片、游标和导出，不作为本次顺手扩展。

### F03 · P1 · 仅改标题也会把热图自动色阶改为手动

两个 section 的 MainWindow 集成都复现：初始 `state.params['z_auto']=True`，只编辑标题并应用后变为 `False`。

位置：`chart_options.py:405` 将 `color_auto` 固定读成 False；`:596` 每次应用都重写色阶；`heatmap_canvas.py:196` 的 `set_clim()` 发出 `levels_changed`；`main_window/_analysis_mixin.py:1048` 将该信号按手动拖动色条处理。

“自动色阶”再次打开总是未勾选；即使本次勾选，也只是取当前矩阵 min/max 再发出同一手动信号。UI、Inspector 和 View 参数不一致，后续数据更新不能可靠延续用户的自动意图。

### F04 · P2 · 分析页外观不是完整的 View/Pane 状态

- FFT：设置自定义标题、Y 标签和红色曲线后，缓存重绘使标题隐藏、标签恢复 `Amplitude`、颜色恢复源颜色。
- FFT 新 View：旧标题在画布上是隐藏的，但新对话框仍读出旧标题 `view A title`。
- FFT vs Time / Order：`plasma` 色图在缓存重绘后保留，也残留到新 View；旧标题同样隐藏但被新对话框读出。
- **不能写成“新 View 上一直显示旧标题”**：实测 `titleLabel.isVisible()` 为 False。这里确认的是隐藏文本残留、对话框回读污染，以及色图继续使用旧 canvas 状态。

位置：`line_canvas.py:2179` 附近重写轴标签/曲线，`:3768` 隐藏标题；`heatmap_canvas.py:1264` 重写标签、`:2192` 隐藏标题；`_fft_time_mixin.py:747` 从 canvas 读 cmap；`analysis_view_state.py:234` 的 PaneState 没有这些外观意图。

注意：FFT-time Inspector 的 `cmap` 是固定兼容字段，`contextual_fft_time.py:676` 明确说明实时色图属于图表选项。不能直接拿这个固定字段覆盖实时选择；也不能把裸 canvas 的 `_cmap_name` 当作跨 View 的真值。

时域已有 `ViewState.chart_appearance` 和相关隔离测试，需保留其现有能力，不重写为另一套全局状态。

### F05 · P2 · 清空标题后布局不收回

就是用户报告的问题。位置：`_axis_handle.py:525`、`chart_options.py:452`；pyqtgraph `PlotItem.py:1482`。
既要清理可见性/高度，也要清掉回读文本和正确通知 inside-label 所有者；只调用 `setTitle(None)` 而保留旧 `titleLabel.text`，会重现 F04 的另一半问题。

### F06 · P2 · 同一窗口反复应用网格状态不能往返

复现：初始开启 → 关闭并应用 → 开启并应用，结果为 `True → False → False`。
位置：`chart_options.py:469` 始终与打开时 `_initial['grid']` 比较，第二次回到打开值时跳过写入。重置后再应用也会受影响。

### F07 · P2 · 校验失败仍改图，并覆盖“曾经应用成功”状态

复现：先合法应用，再输入非法对数范围，`was_applied()` 从 True 变 False；失败前标题、scale、标签、颜色等已有写入。
位置：`chart_options.py:452` 到 `:501`；`_axis_interaction.py:8` 依赖 `accepted or dlg.was_applied()`；时域 `canvas.py:3878` 依赖返回值触发 View 同步。

影响：用户取消退出时，先前已成功应用的改动可能不再走应有的外观捕获/项目 dirty 通知；首次失败也可能留下未被记录的局部变更。
当前代码注释是刻意允许部分应用，因此修复需明确调整交互合同，并修改对应测试，不能只换一个布尔变量名。

### F08 · P2 · 非法颜色与非法色阶未得到有效反馈

复现：颜色输入 `not-a-color`，无警告且仍报告 applied；色阶最小 8、最大 2 被接受，最后图像与色条等级变成 `(5, 5)`。
位置：`chart_options.py:599` 静默跳过非法颜色；`:606` 后色阶没有有限值/顺序校验；`heatmap_canvas.py:196` 直接下发范围。

X/Y 范围还需统一处理相等、逆序与非有限值，不能依赖 renderer 的自动纠正作为用户输入合同。

### F09 · P2 · FRF 图表选项按钮没有功能

真实 MainWindow 显示 FRF 页面后，按钮可见且 enabled，`card.open_chart_options()` 返回 False。
位置：`chart_stack/cards.py:311` 无条件创建按钮，`:819` 在没有 opener 时静默返回；`PgFrfCanvas` 没有 `open_chart_options_dialog()`。

本轮推荐先禁用并解释未支持，消除无响应入口。给幅值/相位/相干三张图完整增加图表选项是新功能，单独列入后续，不假装一个主轴 handle 能代表三种量纲。

### F10 · P2 · 六位小数造成无编辑应用也改变范围

复现：原始 X 范围 `1e-8…5e-8`，打开后两个输入框都是 `0.0`；直接应用得到 `-2e-8…2e-8`。
位置：`chart_options.py:333` 的通用 spin 固定六位小数，打开/应用没有保留未编辑的原始值。

影响是小数值轴与色阶的真实性，不只是显示格式；推荐保留原值并支持适合数值尺度的输入格式，不全局改变所有 CompactDoubleSpinBox。

### F11 · P2 · 自动图例按显示名称去重，漏掉不同曲线

复现：两条不同 PlotDataItem 同名 `same`，`get_lines()` 返回 2 条，重建图例只有 1 项。
位置：`_axis_handle.py:636` 使用 `set[str]` 对 label 去重。多文件同名/截断后同名场景违反复合身份合同。

保留重复生成的幂等性，但按曲线/复合身份判重；重名文本应补充来源用于辨识。

## 3. 全选项与全 section 覆盖矩阵

下面的“已验”表示已有源码/测试/探针证据，不表示所有输入组合都通过。

| 选项/动作 | 已核验行为 | 结论与剩余边界 |
| --- | --- | --- |
| 标题 | 空→有→空、inside-label 首次隐藏、分析页重绘/新 View 回读 | F04/F05；纯空白、长标题、连续 10 轮往返列入修复验收 |
| 网格 | 初始读取、首次应用、overlay 保持 X-only、连续反向应用 | F06；保留副轴网格规则 |
| X/Y 最小/最大 | 线性提交、时域 envelope flush、对数正/非正、小数值 | F01/F07/F10；逆序/相等统一显式验证 |
| X/Y 标签 | 首次应用、时域自定义 X 写通、分析页缓存重绘 | 时域隔离现有测试通过；分析页 F04；空标签与单位回退须明确 |
| X/Y 线性/对数 | 时域主/副轴、热图设置、真实曲线坐标 | F01/F02；不能用“控件变成 log”作为正确性证据 |
| X/Y 自动范围 | 字段联动、原始数据全范围、分析 policy 更新 | 现有覆盖通过；需补自动→手动→自动与 scale 联动 |
| 曲线对象 | 当前 handle 的可见曲线枚举、无曲线禁用 | 对象列表以稳定身份绑定；同名显示及切换未应用颜色的草稿体验待改 |
| 颜色输入/选择 | 合法输入、时域轴/徽标/Navigator 同步、非法输入 | F08；原生颜色选择器取消/选择的全平台 UI 验收未跑 |
| 色图 | 支持列表、图像/色条 LUT 同步、分析页缓存/新 View | 单次设置通过；F04 的归属问题 |
| 色阶 min/max | 合法设置、逆序、自动时禁用字段 | F08/F10；常量矩阵和全 non-finite 的边界须补 |
| 自动色阶 | 打开回读、仅改标题、重开、Inspector 写通 | F03，两个热图 section 均已实际复现 |
| 重新生成自动图例 | 重建幂等、同名曲线、热图无曲线 | F11；热图复选框仍 enabled，应说明不适用；“不保存图例”是现有明确合同 |
| 重置 | 恢复打开时字段 | 现有测试通过；按钮语义是恢复打开值，不是工厂默认；多曲线修改的完整草稿尚未维护 |
| 取消 / Esc | 未应用时不提交、已应用结果由返回值通知 | 正常分支已有覆盖；F07 的成功后失败再取消存在缺口 |
| 应用 | 首次设置、连续设置、失败、只改外观 | F03/F06/F07/F10；提交必须保证无关字段不改变 |
| 确定 / Return | 应用后关闭、唯一默认按钮、非法范围不关闭 | 现有测试通过；颜色/色阶错误应纳入统一校验 |

| Section / 子表面 | 当前实际入口 | 验证与设计边界 |
| --- | --- | --- |
| Time 时域 subplot | toolbar / 双击，记住目标 handle | 用户问题 Cocoa 复现；View/分屏/复制/重开既有测试通过 |
| Time 叠加 / 共轴 / 副轴 | 共用对话框 | 副轴 scale、改色、X-only grid 已有覆盖；标题/网格属于 PlotItem，X 为共享轴，Y/曲线属于所选轴，UI 必须标清 |
| FFT 主频谱 | toolbar / 双击 | MainWindow 缓存重绘和新 View 探针确认 F04 |
| FFT 时域预览 | 首条曲线可开完整选项；副曲线走颜色选择器 | `line_canvas.py:4776` 起的分支；不能把主频谱范围 policy 套给预览；本轮未逐项前台操作副曲线 picker |
| FFT vs Time 主热图 | toolbar | 实际计算+缓存+新 View 验证 F03/F04；共用 adapter 确认 F02 |
| Order 主热图 | toolbar | 同样实际计算+缓存+新 View 验证，不只从热图复用作推断 |
| 两种热图的 slice 行 | 没有独立的通用图表选项入口 | 保留现有 slice 控件；主图改动必须保证 slice/色条/读数一致，新增独立编辑器不在本次 |
| FRF 幅值/相位/相干 | 公共 toolbar 有按钮，canvas 无实现 | F09；本次禁用+原因，后续专项设计三轴能力 |
| UltraView | 卡片显示 QImage/来源快照，非独立 AxisHandle 编辑器 | 源 View 外观与快照刷新为边界；不对快照虚构可编辑图轴 |

Batch/采集窗口不属于本次 Analyzer 图表选项的入口；不把它们的专用参数面板混入此次范围。

## 4. 推荐交互与状态合同

1. **明确当前目标**：显示 section、View、pane/子图、轴角色；共享 X、overlay 共享标题/网格应有说明。不能所有无标题图都只显示“当前图”。
2. **空标题无占位**：输入空值是显式删除；空白字符串按空标题处理，回读为 `""`，标题行和 inside-label 对称恢复。
3. **一次应用是一次完整提交**：先校验所有已编辑且适用的字段，再统一写入并刷新。失败保持上一次已提交状态；定位具体字段；成功后失败不能抹掉历史成功标记。
4. **三个状态分开**：打开快照用于重置；当前草稿用于编辑；最近成功提交值用于差异判定。现有“未编辑直接应用会重新应用分析范围 policy”的合同单独保留，不能和外观差异识别共用一个 `_initial` 比较。
5. **重置不直接改图**：恢复打开时草稿，应用/确定后生效；取消仅丢弃尚未提交草稿，保留之前已应用的结果。推荐文案“恢复打开时设置”或给“重置”增加明确提示。
6. **范围字段使用用户工程量**：对数变换仅在清楚的 adapter 边界转换；原始数据/计算参数/显示坐标不能混用。未编辑字段不能因格式化而改值。
7. **自动是策略**：X/Y/Z auto 要读取与提交真实意图；只改标题/标签/颜色不能关掉 auto 或改变用户浏览范围。色阶自动策略继续复用现有 section 的 dB/有效值范围计算，不另写 min/max 算法。
8. **外观归属**：时域延续现有 View 外观 owner。分析页的自定义标题/标签/网格/线色/色图建议由 PaneState 的可序列化外观字段持有；参数范围仍交既有 analysis range owner。热图实时 cmap 不回写固定兼容字段，不落入 preset 计算参数。
9. **能力真实可见**：无曲线则曲线编辑不可用；无线条图例则图例动作不可用；热图对数不可用；FRF 未接入则按钮禁用并给原因。沿用现有“不适用分组保留但禁用”的布局合同，不重新设计整套窗口。
10. **标签与身份分离**：曲线选择/草稿/持久化用复合 source/channel identity；同名图例不能合并。图例仍为一次性重新生成动作，不改变现有不保存合同。

## 5. 方案对比

| 方案 | 范围 | 优点 | 风险/不足 |
| --- | --- | --- | --- |
| A：仅修空标题 | adapter 一处布局修复与回归 | 改动最小，可单独先交付 | 已确认的数值、auto、View 状态问题全部保留，不能算完成本次横展结论 |
| **B：分阶段修共用逻辑，再补分析状态（推荐）** | 按下面 W1–W4，每阶段聚焦 owner | 可验证、可独立回归，维持现有三 tab UI | 分析持久化需认真处理旧项目默认值与 pane 身份 |
| C：重做属性系统并统一所有 canvas | 新通用 schema、FRF 三轴、slice 新入口等 | 长期覆盖面大 | 边界大、引入新 feature 多，不适合稳定版本的此次修复 |

推荐 B。A 可以作为第一笔窄修复，但不是停止条件。FRF 三轴编辑与非线性热图归入独立后续，不在 B 中扩张。

## 6. 分阶段执行计划与退出条件

### W1：共用对话框的可逆提交与标题几何

涉及 owner：`ui/dialogs/chart_options.py`、`ui/_axis_handle.py`、必要时 `_axis_interaction.py`。

- 把标题清空/回读/布局释放修在真实 adapter；保留 title-changed 回调，检查时域 inside-label 恢复。
- 修复网格连续应用；增加最近提交状态与曾成功应用标记，打开快照继续用于重置。
- 校验先于 mutation：合法颜色、有限且 `min < max` 的轴/色阶范围、log 正数约束；错误提示具体到 X/Y/Z/颜色。
- 未修改的原始浮点值原样提交/保留，编辑时允许科学计数或足够精度；仅修改图表选项的输入策略。
- 完成同名图例的 identity 修复；不扩展图例保存/隐藏功能。

先加会失败的聚焦测试，再修。门禁：`tests/ui/test_dialogs.py`、`test_dialog_with_handle.py`、`test_axis_handle.py`、`test_axis_interaction.py`；选跑 `test_view_appearance_isolation.py` 的标题/取消/改色相关用例。
布局证据：Cocoa 标题空→有→空连续 10 轮，子图/overlay/split 各有代表样本；标题行恢复到该模式初始基线，不用硬编码整张图的绝对 Y 值。
退出：F05/F06/F07/F08/F10/F11 对应回归通过，失败不改变图/owner，历史成功不会丢失。

### W2：范围坐标合同与能力约束

涉及 owner：`_axis_handle.py`、`chart_options.py`、`pg_canvas/heatmap_canvas.py`、`chart_stack/cards.py`；必要的 line/canvas adapter 接线。

- 盘点 PgAxisHandle 范围消费者，明确现有 ViewBox 范围与新对话框工程量边界，保留现有公共兼容接口。
- 手动/自动/线性/log 双向测试，既断言输入/回读，也核验曲线坐标、范围与 tick；时域 X 仍走 raw union + owner flush。
- 给热图禁用 log，给 FRF 无实现按钮提供禁用说明；无曲线的图例禁用。能力信息来自持有真实对象的 adapter/canvas，避免在窗口堆 section-name 特判。
- 明确主轴/副轴/共享 X 的目标说明；FFT 预览不继承主频谱 policy。

聚焦门禁：W1 中受影响用例，加 `tests/ui/test_pg_line_canvas.py`、`test_pg_heatmap_canvas.py` 中相关范围用例，以及 `test_pg_timedomain_canvas.py` 的范围/envelope/restore 定向选择。
新 log 用例至少含 0.1…10、1…100、正负混合、无有效正数、切回 linear、overlay 副轴与两 pane。
数值边界需写明 empty、short、non-finite、dtype、shape、X/Y 对齐；不裁短数据掩盖不一致。
退出：F01/F02/F09 回归通过；无纯轴标签变换而数据映射未变的组合。

### W3：分析页外观、色阶策略与 View 隔离

涉及 owner：`analysis_view_state.py`、现有分析协调/渲染路径、`line_canvas.py`、`heatmap_canvas.py`；继续使用时域既有 appearance owner。

- 为分析 Pane 保存明确的用户外观覆盖；默认值缺失表示遵循系统默认，显式空标题表示用户删除，不把二者混成同一状态。
- plot/reset/View restore 顺序：恢复默认投影 → 应用当前 Pane 用户覆盖 → 结算布局一次；不从前一个 View 的残留 Qt 对象读取意图。
- 热图颜色策略读取真实 Z auto；手动等级和自动策略使用不同的提交语义，不能把所有 set_clim 都当用户拖动。保留色条拖动的既有 Inspector 回写和 compare level-lock 规则。
- 实时 cmap 归 Pane 外观，重绘从该 owner 获取；不修改 preset 的固定兼容 cmap 合同。
- 对 FFT 主图与预览分别使用稳定角色标识；线色以复合通道身份持有，重算新建曲线后仍正确应用。
- 验证新 View/复制/View 切换/双 pane 聚焦/关闭/项目保存重开；旧项目没有新增字段时保持现有默认外观。

聚焦门禁：`tests/ui/test_analysis_multiview_integration.py` 的新外观/auto 用例、`test_analysis_view_state.py` 的序列化用例、`test_pg_line_canvas.py` / `test_pg_heatmap_canvas.py` 定向重绘用例、`test_view_appearance_isolation.py` 及 `test_view_appearance_boundary.py`。
退出：F03/F04 回归通过；只改标题时 X/Y/Z 策略与浏览范围不变；新 View 对话框无旧标题/旧 cmap，复制与重开保留当前 View 的意图。

### W4：小幅 UI 清晰度与跨平台验收

- 维持三个 tab 与当前基本布局；补充明确目标、禁用原因、重置语义、颜色合法性反馈。
- 曲线切换维护各对象未提交颜色草稿，重置能恢复打开时涉及的对象；此项属于交互完善，独立用例验证，不混入标题补丁。
- 修复/重命名/新增交互同步 `ui/hints.py`、`ui/quickref.py`；尤其“当前 View”的范围说明与图例一次性动作。
- 检查各 tab 默认/长标题/长通道名、窗口收窄、滚动末端、键盘焦点、默认按钮、Esc、无数据、禁用态。
- Cocoa 实际 widget 核验几何/像素；Windows Full/Lite 冻结包检查 100%/150%/200% DPI 的布局、对话框关闭和绘图区恢复。
- 导出/复制与 UltraView 快照至少各验证一个带标题/清空标题样本；保持源 View 外观归属，不给快照新添可编辑状态。

本轮渲染观察只有小幅清晰度建议：无标题目标都写“当前图”、不适用分组缺少原因、图例页内容少、重置含义不够明确。这些不是已证实的遮挡/圆角缺陷，不能据此做全窗口视觉重做。

## 7. 通用边界门禁与测试预算

- W1/W2 改 signal 连接时跑 `tests/ui/test_no_lambda_signal_connections.py`；改 QSS 才跑 `tests/ui_kit/test_qss_border_shorthand.py`。
- 改 canvas collaborator 声明时跑 `tests/ui/test_pg_canvas_backref_invariants.py`；改跨包依赖跑 `tests/ui/test_import_boundaries.py`。
- W3 改 MainWindow 状态协调必须跑 `tests/ui/test_main_window_state_ownership.py`，不能扩大写入 whitelist。
- 若新增 import seam/序列化类型，再选择 packaging/project-session 对应既有门禁；不默认改版本号。
- 全部阶段均检查 `git diff --check`。owner focused 通过后只扩大到实际受影响边界，不因 UI 文件改动就运行整个 `tests/ui`。
- 不设全量 pre-change baseline。本轮是分析与文档，不需要运行整套运行时测试作为文档门禁；上面的测试是为了验证诊断。
- 若 W3 最终形成跨状态/项目序列化的稳定集成里程碑，可安排一次协调者独占全量验收；先检查 pytest 进程，记录前后 HEAD/dirty fingerprint，主套件 `--ignore=tests/acquisition_ui` 结束后再单独运行 acquisition_ui，不并行。
- 不接受“回归测试只断言内部 setter 被调用”。至少断言真实 curve/image/axis 状态、View owner 与渲染几何三者的一致性。

## 8. 本轮已执行验证与可复查材料

### 现有测试

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_dialogs.py \
  tests/ui/test_dialog_with_handle.py tests/ui/test_axis_handle.py \
  tests/ui/test_view_appearance_isolation.py -q
# 85 passed, 7 warnings，exit 0

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_axis_interaction.py \
  tests/ui/test_recolor_navigator_swatch_sync.py \
  tests/ui/test_analysis_multiview_integration.py \
  -k 'chart_options or recolor or handle' -q
# 8 passed, 94 deselected，exit 0
```

警告为 pyqtgraph/NumPy 的既有 shape deprecation。93 项通过并不覆盖上述所有往返缺陷。

### 临时诊断探针

- `.state/chart-options-audit/probe.py`：分别以 `QT_QPA_PLATFORM=offscreen` 与 `cocoa` 运行，均 exit 0；结果位于对应目录的 `results.json`。
- `.state/chart-options-audit/layout_probe.py`：Cocoa + 产品 QSS，三个 tab 都为 430×571，按钮均在窗口内；坐标轴页可滚动，另两页无需滚动。已查看三个 PNG；另复现同名图例和小数精度问题。
- `.state/chart-options-audit/test_integration_probe.py`：通过 `-p tests.ui.conftest` 加载项目 QSettings 隔离和 Qt teardown；最终 **4 passed，exit 0**。它们断言的是当前缺陷观察，不是修复验收测试。
- 对应 JSON：`fft-integration.json`、`fft_time-integration.json`、`order-integration.json`。记录标题的文本和可见性，防止把隐藏残留误报为可见串图。

复现集成命令：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -p tests.ui.conftest \
  .state/chart-options-audit/test_integration_probe.py -q
```

本轮没有源代码修复、没有提交/推送、没有 Windows 冻结包验收。lesson 状态无待处理 requirement；实施修复时将可复用的往返状态合同配合正式回归测试再评估是否提炼新 lesson。

## 9. 实施记录

诊断之后已按方案 B 落地 W1–W3，以及 W4 里对话框能独立完成的部分：空标题收回、整单校验后再写入、工程量与 ViewBox 分开、热图禁用对数、FRF 按钮禁用并说明原因、分析外观归到 Pane 的 `chart_appearances`。非线性热图和 FRF 三轴编辑仍不在范围内。

尚未做的是 W4 的跨平台验收：Cocoa 上标题空→有→空连续 10 轮，以及 Windows Full/Lite 在 100%/150%/200% DPI 下的对话框与绘图区恢复。offscreen 聚焦测试不能代替这两项。
