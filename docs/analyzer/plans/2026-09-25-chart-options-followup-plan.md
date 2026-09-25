# 图表选项 Follow-up Plan：图例页、跨平台表单、还原操作

日期：2026-09-25。状态：**分析完成，待实施**。

本轮仅分析并创建本文，不修改产品代码或正式测试。开始时工作区已有上一轮图表选项实现及测试的未提交修改，本计划以这些真实文件为诊断对象，不把旧 HEAD 当作当时的产品实现。
开始时 HEAD 为 `a3572d44b0fd8afa217fdbde4d6239e7ca8200d8`；分析期间已有改动被其他操作提交为 `e5866743`（`fix(ui): commit chart options as one reversible change`）。本轮未执行提交。探针前后及文档收尾时，dialog、axis handle、heatmap 三个关键文件的 SHA-256 一致，诊断证据仍对应相同源码。

关联：[上一轮完整审计与优化计划](2026-09-25-chart-options-audit-and-optimization-plan.md)。本文优先调整其中两条设计建议：不再保留三 tab；推荐把“恢复草稿后再次应用”改为清晰的一次性还原操作。旧审计的历史结论和测试数不重写，也不视为当前改动已经验收。

## 1. 决策摘要

| 用户问题 | 当前真实行为 | 推荐方案 |
| --- | --- | --- |
| 图例有什么本质作用？ | 一次性重建当前线条的名称/颜色对照，既不是显示开关，也不是图例外观设置 | 移除整个“图例”tab 及其手动重建入口；保留图中自动图例和时域通道标识 |
| 为什么 Mac 居中且很窄？ | 五个 QFormLayout 没有显式布局策略，采用 macOS 默认居中、不拉伸字段 | 在此对话框统一左上布局、字段拉伸、列对齐；不改系统主题或全局 QSS |
| 恢复打开时设置为什么没用？ | 当前只恢复草稿；而且清掉范围/色阶 dirty，导致再次应用也不能完整恢复 | 保留有用的撤回能力，修复实际缺陷；按钮缩短为“还原”，同一次打开内一键恢复，不要求再点应用 |

以上均为后续实施建议，本轮没有删除标签或改变按钮行为。

## 2. 已确认问题与用途判断

### P2 · 还原后的表单和实际图形不一致

**不是只有“需要再点应用”这个操作门槛，当前确实存在功能缺陷。**

macOS Cocoa + 当前真实 TimeDomain/Heatmap canvas，调用按钮 click 链得到：

| 对象 | 打开时 | 修改并应用 | 点击恢复后的输入框 | 再次应用后的实际图 |
| --- | --- | --- | --- | --- |
| 时域 X 手动范围 | 0…10 | 2…8 | 0…10 | **仍为 2…8** |
| 时域标题 | 空 | Applied title | 空 | 空，标题能恢复 |
| 热图手动色阶 | 0…8 | 1…5 | 0…8 | **仍为 1…5** |
| 热图自动色阶 | 关闭 | 开启 | 关闭 | **实际仍开启** |

根因链：

1. `mf4_analyzer/ui/dialogs/chart_options.py:647` 的 `reset_fields()` 把 `_opened` 写回控件。
2. 此过程处于 `_loading=True`，阻止修改信号记账；结束时又将 `_range_axes_edited` 置空、`_color_policy_dirty` 置 False。
3. `:892` 的 `_commit_range()` 对未标记的轴直接返回；`:938` 的 `_commit_color_policy()` 对未标记色阶直接返回。
4. 标题、网格等通过 `_committed` 差异比较提交，所以部分字段可以恢复，范围/色阶却不行。操作效果不一致。
5. `:956` 的分析范围提交有“无外观差异时重新应用 policy”的特殊分支，可能让某些分析页恰好恢复；不能依赖这个偶然分支实现完整还原。恢复标题等外观时又会跳过它。

现有 `test_chart_options_reset_restores_drafts_without_touching_chart` 等三个 reset 测试全部通过，但只证明未提交草稿可重置，没有验证“应用过→恢复→实际画面/owner 回到打开时”的闭环。

功能价值：同一窗口内尝试多个标题、范围、颜色，点过应用之后，取消不会撤销这些已应用结果；可靠的一键还原能省去手动记住旧值。推荐修好并简化语义，不因为当前实现失效就删除撤回能力。

### P2 · macOS 表单布局依赖平台默认值

位置：`chart_options.py:421`、`:439`、`:472`、`:512`。基础信息、X、Y、曲线、色图共五个 QFormLayout 只设置了 margins/spacing，没有设定 field growth、form alignment 或 label alignment。

实际读取到的默认策略：

| 策略 | macOS 原生样式 | macOS 上加载 Qt Windows 样式的对照 |
| --- | --- | --- |
| FieldGrowthPolicy | FieldsStayAtSizeHint（0） | AllNonFixedFieldsGrow（2） |
| FormAlignment | AlignHCenter + AlignTop（36） | AlignLeft + AlignTop（33） |
| LabelAlignment | AlignRight（2） | AlignLeft（1） |

因此，即使 QLineEdit 自身是 Expanding，表单仍把它限制在 sizeHint。数值输入框的 sizeHint 又随显示数值长度变化，于是最小值很短、长小数更宽、整块表单在卡片中间浮动。这与截图现象一致。

在相同 430 逻辑像素宽窗口内，对一次性诊断 widget 设置显式策略后：

| 字段 | 当前 Mac 宽度 | 显式拉伸后宽度 |
| --- | ---: | ---: |
| 标题 | 124 | 330 |
| X 最小值 | 42 | 318 |
| X 最大值 | 46 | 318 |
| X 标签 | 124 | 318 |
| X 刻度下拉框 | 67 | 318 |

已查看实际 QWidget 渲染图。上表是根因验证，不是最终视觉定稿：标题组与轴组当前标签列宽不同，最终还应统一字段起始列。

Windows 样式对照在本机也直接给出 310 像素宽的数值框，支持“原生布局默认策略不同”的结论；这不是实际 Windows 操作系统/冻结包验收。用户关于 Windows 每行填满的反馈作为需求保留。

### 图例有实际动作，但独立设置页的产品价值很低

当前入口：`chart_options.py:235` 添加 tab，`:403` 创建唯一复选框；提交时调用 `PgAxisHandle.rebuild_legend()`，执行后复选框回到未勾选。
实际探针从没有 LegendItem 的时域图开始，应用后生成 1 项，证明该动作确实执行，不能说它完全没有代码作用。

该动作只是把当前可见线条的名称和颜色列出来；不控制是否显示、不配置位置/字号，也不持久化图例。这种一次性动作被包装成一个复选框和整页设置，用户很难知道它改变了什么。

| 表面 | 已有的识别机制 / 该动作的额外价值 |
| --- | --- |
| 时域单曲线/子图 | 已有轴名称、颜色和需要时的图内通道标签；额外 LegendItem 通常重复信息 |
| 时域共轴 | `canvas.py:4807` / `:4820` 起按成员生成现有通道标识；不能把它和手动 LegendItem 当成同一个 owner |
| 时域叠加副轴 | handle 可能共用一个 PlotItem；重建过程先 clear，再只枚举当前 handle 的曲线，作用范围并不是可靠的“整图图例配置” |
| FFT 主频谱 | `line_canvas.py:406` 已自动 addLegend，`:2175` 创建带名称的曲线；正常显示不依赖用户再点一次重建 |
| FFT 时域预览 | 仍有轴/曲线标识；手动重建不是其正常显示流程的必要步骤 |
| FFT vs Time / Order | `_HeatmapAxisHandle.supports_legend_rebuild()` 返回 False，图例页成为不可用空页 |
| FRF / UltraView | 不因此增加新的图表选项功能，保留各自原有显示/快照机制 |

**推荐删除“图例”tab 与手动重建命令，不删除画布上的正常图例、通道标签、共轴说明或色条。** 不把同一低价值动作移到另一个菜单继续维护。

## 3. 后续设计合同

### A. 两个 tab，所有表单一致排布

- 仅保留“坐标轴”“图形”。移除图例 tab 不影响曲线对象/颜色选择。
- 五个表单在构建时显式设置 `AllNonFixedFieldsGrow`、`AlignLeft | AlignTop`，标签左对齐并与字段垂直对齐。
- 标题、数值、轴标签、下拉框占满可用字段列；颜色行的输入框扩展，“选择”按钮保持自然宽度并靠右。
- 所有组采用统一标签列宽度，以本对话框可见标签的字体测量值为依据；不能给每种输入框写一个孤立固定像素宽度，也不能把 318 当成目标硬编码。
- 统一内边距和字段右边缘；初始/禁用/auto/长小数/科学计数/窗口缩放时保持列稳定。
- 修正只限 ChartOptionsDialog 的布局，优先复用小型局部 form 创建方法；不改 QApplication style，不增加全局 QSS 宽度或 Inspector 的新规则。
- 高度不足仍通过现有纵向滚动访问所有字段，footer 持续可见，不用横向滚动掩盖布局问题。

### B. “还原”的范围与时机

推荐 footer 为 `还原 / 取消 / 应用 / 确定`；保留原有默认按钮规则，不额外添加快捷键。

| 情况 | 点击“还原”的结果 |
| --- | --- |
| 刚打开、没有任何改动 | 按钮禁用，不制造一次无意义提交 |
| 改了输入但尚未应用 | 只还原草稿；canvas 本来就是打开时状态，无需重写 owner |
| 已应用一项或多项修改 | 一次点击恢复打开时的字段、实际图形和相应 owner；不再要求点应用 |
| 应用过，又有非法/未完成草稿 | 丢弃草稿，使用合法的打开快照还原，不被当前非法草稿拦住 |
| 还原后再取消 / 确定 | 保持已还原状态，不偷偷恢复上一次修改 |
| 关闭后重新打开 | 建立新快照；不是跨窗口 Undo，不恢复工厂默认 |

建议 tooltip：“撤销本次打开图表选项后的修改，并立即还原图表。”

这是相对于上一轮方案的明确语义调整，尚未实施。保留“仅恢复草稿、再应用”的替代方案也能修 bug，但仍有用户已经反馈的双步骤困惑；直接移除还原则会丢掉已应用试调的撤回入口，均不推荐。

### C. 还原的实现约束

- 初始化填表与用户触发还原必须分开：当前构造器也调用 `reset_fields()`，不能让构造过程意外执行一次图形回写。
- 不清空 dirty 后期待提交层猜测。根据打开快照与当前已提交值生成明确恢复差异；覆盖 X/Y min/max、auto、scale、Z min/max/auto、标题/标签、网格、全部曲线颜色、cmap。
- 复用既有校验/提交/刷新通路，不建立第二条独立 setter 流；范围一次性结算仍保留 raw X union/envelope flush 合同。
- 当前图表目标使用既有 handle/复合通道身份。草稿中的曲线当前选中索引与颜色意图分开，不误改同名曲线或另一 pane。
- 如 owner 区分“无覆盖，遵循默认”和“显式空标题/标签”，打开快照还要保留这一小段外观意图的存在性；不能仅用 getter 字符串还原出新的显式覆盖。只快照本对话框所拥有的字段，不复制整项目、数据、Qt 对象或计算缓存。
- auto 恢复的是自动策略；相应数值显示从 owner 回读。自动模式的运行时范围允许随合法新数据变化，不要求伪造历史浮点端点。
- 还原后的 `_committed`、草稿、dirty、曾成功提交标记保持一致。曾应用后还原仍应让关闭路径捕获最终状态；不能将整个项目 dirty 标记无条件清零。
- 第一个合法提交和还原必须可被现有 View/Pane 状态路径捕获；打开别的 View、复制、分屏、重新计算/保存重开都不得重新出现已撤回的改动。

## 4. 实施顺序与聚焦门禁

### F1：补真实还原回归，再修恢复提交

所有者：`ui/dialogs/chart_options.py`；若需要还原 owner 的“覆盖存在性”，仅通过其现有外观 API 做小范围延伸，不在 dialog 新增 MainWindow 状态写入。

1. 把本轮探针转换为正式失败回归，断言真实 canvas 和 owner，不只断言输入框。
2. 先保证现有恢复→应用闭环正确，再把用户按钮与初始化填表分开，实现上述一次性还原。
3. 增加无差异禁用状态，统一成功/失败/还原后的状态更新。

必须覆盖：X/Y 单轴和双轴；手动与自动双向；标题和范围同时恢复；Z 数值和 auto；多曲线改色；cmap；重复应用→还原→再编辑；非法草稿；取消/确定；打开时值已是自定义值。

聚焦：`tests/ui/test_dialogs.py`、`tests/ui/test_dialog_with_handle.py`；按确实修改的 seam 选 `tests/ui/test_axis_handle.py`。分析页补 `tests/ui/test_analysis_multiview_integration.py` 的定向 owner 用例；时域补现有 `test_view_appearance_isolation.py` 中当前/非聚焦 pane 路由和重开检查。
退出：表单、图形、持久化意图一致；现有构造/只查看/取消不产生新 mutation；原本通过的精度/科学计数/对数范围约束不回退。

### F2：统一表单几何

所有者：`ui/dialogs/chart_options.py`，最多一个局部表单创建 helper。

先保存当前 Cocoa 渲染基线，再实现显式布局策略与统一列宽；验证所有分组，不能只改截图中的 X 轴。

聚焦：对话框现有适配屏幕/默认按钮用例；增加有意义的几何约束：同组字段左右边缘一致、跨组字段起始列一致、父容器变宽时字段同步变宽、数字位数变化不改变字段宽度、footer 和滚动末端可达。
在 Cocoa 原生样式以及 Qt Windows/Fusion 样式对照运行；后两者不替代真 Windows。
退出：实际运行 widget 的几何和像素符合要求。参考截图中数值框紧贴数值宽度、卡片中间大面积浪费空间的现象消失。

### F3：移除图例页并清理文案

所有者：`ui/dialogs/chart_options.py`、`ui/hints.py`、`ui/quickref.py` 及直接相关测试。

- 删除 tab、checkbox、一次性提交分支、该控件的 capability 锁/初始字段/dirty 判断和 tooltip。
- 删除 `chart_options.legend_once` 等该入口的提示；保留“共轴图例逐行显示”等真实画布能力说明。
- 同步“恢复打开时设置”为新还原合同，不让帮助继续要求二次应用。
- `PgAxisHandle.rebuild_legend()` 属于已有适配器协议，是否有外部调用不能仅从本地 grep 断定；本次可保留不暴露 UI 的兼容方法，不为删除一个 tab 扩大公共接口破坏范围。
- 调整原有对话框快照/标签期望；画布自动图例与多文件同名身份测试继续保留。不要删除测试来掩盖正常图例消失。

聚焦：`tests/ui/test_dialogs.py`、`test_dialog_with_handle.py`、`test_chart_options_capability.py`；FFT 自动图例正常显示/改色，以及时域共轴通道标识做真实对象回归。
退出：仅两个 tab，没有悬空连接/旧帮助入口；原有自动图例和通道标识完整。

### F4：有限的跨平台/全 section 验收

| 场景 | 要求 |
| --- | --- |
| Time 单图、subplot、overlay、双 View 分屏 | 还原只影响明确目标；共享 X/整图标题网格规则不改变 |
| FFT 主频谱与时域预览 | 两套坐标角色正确；主图正常自动图例仍出现 |
| FFT vs Time / Order | 色图、Z auto/手动色阶与 Inspector/Pane 同步还原；无空图例页 |
| FRF / UltraView | 不新增入口；现有不可用说明/源快照能力保持 |
| Cocoa | 430 宽默认窗口与加宽窗口、长标签/长小数、auto 禁用态、两个 tab、滚动底部 |
| 真 Windows Full/Lite | 100%/150%/200% DPI；字段填满、按钮可达、相同还原操作立即反映到图上 |

按变化选择 `test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py` 等边界；没有 QSS 改动就不为此运行 QSS suite，没有新 import seam 就不追加 packaging 大套件。
本 follow-up 不触及数值算法/加载器，不增加全量 pre-change baseline，也不默认再跑整个 UI suite。focused 与相关边界通过后结束；Windows 未运行就明确留为未验收。

## 5. 本轮验证材料与限制

- 临时脚本：`.state/chart-options-followup/probe.py`。运行了原生 Cocoa、Cocoa 上的 Qt Windows 样式对照，两次均 exit 0。
- 数值与恢复证据：`macintosh-results.json`、`windows-results.json`。保存前后源码摘要，三文件未在探针过程中改变。
- 实际渲染：`macintosh-before.png`、`macintosh-proposal.png`，均已检查；proposal 只是一次性 widget 的布局实验，源代码未修改，也不是“两 tab + 新还原按钮”的完成稿。
- 当前恢复测试：`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py -k reset -q` → **3 passed, 56 deselected，exit 0**。证明现有测试没覆盖已应用后的恢复缺口，不证明功能正确。
- 本轮没有实际 Windows 系统/冻结包运行；没有为上一轮实现或新提交 `e5866743` 作全量验收。
- 文档交付只需范围/引用/一致性和 whitespace 检查；本轮运行 probe 与聚焦测试是诊断证据，不是要求以后每次改 plan 都运行产品测试。

本次交付边界：仅新增这份 follow-up plan 与 `.state/` 下诊断材料，保留所有已有产品/测试修改，不提交、不推送。
