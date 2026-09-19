# P 键固定游标与独立读数面板实施计划

- 日期：2026-09-18。
- 状态：待实施。本文是实施契约；本次仅编写计划，不修改产品代码。
- 分析基线：HEAD `71060bf6` 与当前工作区。View、工程保存、UltraView 等已有未提交改动；实施时重新核对，不能覆盖或回退这些改动。
- 交互基准：[P 键固定 HTML Demo](../ui-prototypes/2026-09-17-pinned-cursor-demo.html)。它证明交互方向，不证明 Qt 行为、数值算法或工程恢复已经实现。
- 执行方式：按依赖顺序推进，不要求并行 agent。完成本文全部范围才能称为功能交付。

## 1. 产品目标与固定决策

鼠标在图中找到位置，直接按 **P**，留下这一位置的独立读数面板。继续移动鼠标查看其他位置，再按 P 可继续固定。无需先单击锁定单游标，无需把鼠标移到面板点击图钉，无需“留作对照”或固定组切换列表。

固定面板沿用现有 CursorPill 外观、full/mini 排版与拖动方式，放在所属绘图区内，不增加侧栏或底部常驻面板。每条固定记录具有稳定的 P 编号、面板、轴边标签和淡虚线；这些是同一条记录的不同展示，必须一起更新或删除。

### 1.1 范围

| 纳入本次实施 | 范围边界 |
|---|---|
| 时域单/双游标 | Time-X、Custom-X；subplot、overlay、共轴；主/副分屏 View |
| FFT 单/双游标 | 频谱视口、各分析 pane；不把下方时域预览当作频率取点区 |
| FRF 单/双游标 | 幅值、相位、相干三图共用频率，线性/对数频率轴 |
| 面板 | 活动/固定，full/mini，拖动、收起、展开、取消固定、关闭、空间不足、隐藏/恢复 |
| 生命周期 | View/pane 隔离、切页、重绘、数据重算、来源关闭、工程保存/恢复、复制 View |
| 输出 | 复制图片、分屏合图、UltraView 捕获与展示刷新 |
| 不新增 P 固定的界面 | FFT-vs-Time/Order 热图及其切片、UltraView 静态卡片/Laser/绘图、图片标注编辑器；覆盖不抢键和不串状态的回归 |

不修改 DSP、采样/插值规则、Custom-X 分支判定、FFT 吸附算法、FRF 相位差定义。无需产品版本升级或顺带重构分析体系。

### 1.2 “固定”的含义

- 固定**数据坐标、所属图表与通道集合**；拖动面板只改变摆放位置。
- 在同一有效数据版本下，读数保持不变；鼠标移动、缩放、平移、切换单/双/关均不改写它。
- 滤波、分析参数、源数据等改变后，在相同物理位置重新求值。这时显式进入“更新中”，不能继续把旧数值当作新曲线读数。本文不提供跨计算版本的历史数值快照功能。
- 持久化可复现的固定意图，不保存 HTML、控件、数组、截图、派生数值或运行时缓存。

## 2. 已核实的代码边界

以下以本次读取的当前代码为准，历史计划中的“待实施”不能代替现状。

| 文件 / 符号 | 现状与实施要求 |
|---|---|
| `ui/pg_canvas/cursor.py:CursorController._handle_cursor_mouse_move` | 时域单游标随移动更新，现有 33 ms 节流；P 不能只复制可能滞后一帧的面板。 |
| 同文件 `_handle_cursor_mouse_press` / `snapshot_placement` | 双游标由点击 A/B 放置；持久化仅有 A/B 坐标，没有多个 pin。 |
| `ui/cursor_display_model.py` | 已有 Qt-free 的时域、FFT 读数与 presentation DTO；新事实和固定意图沿用这一分层。 |
| `ui/chart_stack/stack.py:_cursor_snapshot` / `_refresh_cursor_projection` | 当前缓存按 canvas，时域/FFT走结构化投影；固定记录不能复用同一个可变“当前读数”槽。 |
| 同文件 `_cursor_source_on_screen` / `_pill_for_canvas` | 存在可见 section 门控及主/副 pill 路由；不能让隐藏分析 canvas 清空当前面板。 |
| `ui/chart_stack/cursor_pill.py` | 已有 full/mini、safe rect、真实 QTextDocument 测量、空间不足和用户拖动锚点；没有固定记录管理。`snapshot()` 是展示快照，不是 pin 的数据模型。 |
| `ui/pg_canvas/line_canvas.py` | FFT 已有 `FrequencyCursorChannel`、`frequency_cursor_host_rect()`；频谱区域排除时域预览。 |
| `ui/pg_canvas/frf_canvas.py:set_cursor_frequency` / `set_dual_cursor_frequencies` | FRF 读数主要通过格式化文本发送，包含真实吸附频率、幅值/相位/相干以及 B−A；需先补结构化事实出口，禁止解析 HTML 获取数据。 |
| `ui/view_state.py` / `ui/analysis_view_state.py` | 时域 View、分析 Pane 已持有 cursor mode/placement；多个 pin 的可保存意图分别由这些状态持有。 |
| `ui/view_bridge.py` / `ui/analysis_view_bridge.py` | 既有 capture/apply 边界；pin 加在同一事务内，不增加第二套恢复流程。 |
| `ui/view_overlay_state.py:normalize_cursor_placement` | 当前 placement 不随 off 丢失，只记录双游标坐标；新增字段不能改变这一兼容语义。 |
| `ui/analysis_section_page.py:grab_combined_pixmap` / `stack.py:grab_presentation_pixmap` | 单图、时域分屏、分析合图有不同捕获路径，必须逐个覆盖多个 pill 的合成。 |
| `ui/main_window/ultraview_capture_coordinator.py:_cursor_payload` | 捕获摘要区分临时 hover 与已放置双游标；pin 是稳定内容，需进入现有摘要与失效机制。 |
| `ui/chart_stack/ultraview/page.py` / `ui/markup/editor.py` | P 已分别用于绘图/画笔。固定快捷键必须受图表上下文约束，不能注册一个无条件全窗口 P。 |

参考约束：[FFT 共享布局计划](2026-09-16-fft-cursor-shared-layout-optimization-plan.md)、[游标表格规格](../specs/2026-09-12-cursor-table-readability-spec.md)。复用其已核实有效的布局/身份边界；本文新增固定游标行为。

## 3. 快捷键与采集事务

### 3.1 P 的生效条件

1. 无 Ctrl/Meta/Alt 修饰的 P/p，忽略自动重复；长按只执行一次。
2. 当前窗口处于前台，鼠标命中可交互、可见、完成绑定的时域/FFT/FRF 数据视口；目标是鼠标所在 pane，不是最后焦点所在 pane。
3. 输入框、可编辑表格、输入法组合输入、搜索、模态对话框、弹出菜单、标注编辑器、UltraView 绘图上下文优先，不拦截其按键。鼠标停在图上但键盘正在文本输入时也不能 pin。
4. 鼠标位于轴标签、图例、工具栏、面板、FFT 时域预览或不可见 canvas 时不采集旧读数。不得为了触发 P 而要求用户先点击抢焦点。
5. 平移、框选、缩放手势、面板拖动、双游标端点拖动、页面过渡及未完成 View 绑定期间不创建 pin；手势结束后可正常操作。
6. off、空数据、结果尚未就绪不创建记录、不增加编号。双游标仅 A 时提示“先放置 B，再按 P 固定”；其他失败提示使用现有提示位置，不弹对话框。

由一个 owner 路由按键；不得同时注册 QAction、QShortcut 和 eventFilter 三条会重复触发的路径。根据 Qt `ShortcutOverride`/KeyPress 实际行为实现并测试仲裁，不吞掉不属于该上下文的 P。

### 3.2 从输入到显示的一次提交

`P → 命中所属 owner → 读取当前物理坐标 / A-B → 获取该数据版本的完整事实 → 校验 → 创建记录 → 同批投影面板、标签和线`

- 单游标：在按键时重新映射当前鼠标坐标，绕过 hover 节流完成一次精确采集；同帧 primary、rows、marker 必须使用同一坐标和数据版本。
- 双游标：固定已放置的 A/B，而不是按 P 时鼠标下面的第三个位置。
- 通过现有数值 owner 获取事实。不能从格式化文本反算坐标，也不能临时修改全局 A/B、发信号再恢复来模拟某个 pin 的求值。
- 为事实携带 owner identity、绑定 generation、数据 revision。异步完成时核对三者；旧 View 或旧计算结果到达不能覆盖新记录。
- 失败时整个事务无副作用；不得出现“有 P3 标签、无 P3 面板”或反向情况。
- 相同 owner、同数据版本、同模式、同轴上下文、同通道绑定与同有效坐标的重复 P：高亮已有记录，不再创建。不能根据显示到三位小数后的文字判断相同位置。
- 单游标固定后当前候选被消费，待下一次有效移动再显示新的活动面板；重复按 P 不复制同一记录。已有固定面板留在原位。
- 双游标固定后隐藏本次活动面板但保留既有 A/B 放置意图与点击顺序；下一次 A/B 实际更新才重新显示活动面板。未改端点再次 P 只定位原记录。pin 不能偷偷重置既有双游标放置规则。

### 3.3 提示

- 可用单游标面板标题内常驻轻量 `P 固定`；双游标完整时为 `P 固定此组`，仅 A 时显示原有放置 B 提示。
- 空间不足或面板暂时不显示时，同一提示也能从既有底部 hint/quickref 获知，不增加工具栏行。
- 成功时使用短提示 `P3 已固定 · t=…` 或带真实 X/f 单位的等价文字。
- 活动面板不再提供需要鼠标移过去的“Pin 当前值”按钮，避免重新引入位置漂移链路。

## 4. 模式与数值契约

| 模式 / 状态 | P 行为 | 固定内容与坐标 |
|---|---|---|
| off | 不创建；已有 pin 保留 | off 只关闭活动游标 |
| Time-X single | 固定按键时所在 X | 真实时间坐标及各通道已有单点读数；不新增“最近点”算法替代现有取样 |
| Time-X dual：未放 A / 仅 A | 不创建 | 不从 hover 补 B |
| Time-X dual：A/B 完整 | 固定整组 | A、B、带符号 ΔT、已有 1/ΔT 规则；Min/Max/Avg/Δ 由既有 owner 输出 |
| Custom-X single | 固定指定 X | 保留 X 通道复合身份、单位、X↑/X↓ 分支与诊断；不可把 X 数字当作秒 |
| Custom-X dual | A/B 完整后固定 | 保留现有 ΔX 及各分支 B−A 语义、物理路径和端点越界诊断；不跨不连续支路补值 |
| FFT single | 固定有效吸附频率 | 频率用既有首曲线吸附策略；各曲线独立网格取值/相对首曲线差值保持既有语义 |
| FFT dual | 固定 A/B 吸附频率 | full 保留 A、B、Δ=B−A；mini 保留既有 Δ 投影；不得伪装成区间 Min/Max/Avg |
| FRF single | 在任一三图按 P | 同一频率下的幅值、相位、相干；一张面板、三图位置联动 |
| FRF dual | 固定已选整组 | A/B、Δf、Δ幅值/Δ相位/Δ相干；相位差保持既有定义，不新增角度环绕修正 |
| FRF 对数 X | 保存 Hz | 投影时使用现有 Hz↔view-X 转换，禁止把 log10(f) 写入记录 |
| 部分通道无值 / 诊断 | 其余有效时允许固定 | 缺失保留 `—` 和诊断，不伪造 0；Custom-X 明确诊断也可作为可读结果保留 |
| 完全无结果 / 无可解释通道 | 不创建 | 清理旧候选，避免按 P 固定上一个结果 |

A=B 是完整端点的一种情况：遵循现有读数合同，Δ=0，不能显示无穷倒数；不沿用 Demo 的“一律禁止 A=B”简化。A>B 不交换端点以抹掉差值符号；区间统计的范围排序仍由原 owner 处理。

默认要求“按 P 前活动读数”和“按 P 后固定读数”在相同有效坐标与数据版本下逐字段一致，允许 P 修正因 33 ms hover 节流尚未显示的最新鼠标位置，但必须原子刷新活动值再固定，不能线在新点、值在旧点。

## 5. 面板状态机

用独立维度表达状态，避免一个布尔值同时表示模式、显示与有效性：

- 数据角色：`live / pinned`。
- 读数模式：`single / dual`（off 属于活动工具状态，不是 pin 的模式）。
- 用户展示意图：`full / mini`。
- 运行时可用性：`ready / pending / unavailable / incompatible_axis`。
- 显示条件：当前 owner 可见、几何已就绪、空间足够；不持久化临时隐藏状态。

| 操作 / 事件 | 活动面板 | 既有固定面板 |
|---|---|---|
| P 成功 | 当前候选消费，下一次有效更新再出现 | 新面板保留本次 full/mini 和位置；其他面板不动 |
| full → mini / mini → full | 只改当前面板 | 只改这一张；保持右边缘/顶部并在 safe rect 内重排 |
| 拖标题 | 改摆放位置 | 不改变 X、A/B、读数或淡线；已拖面板不因下一次 P 自动重排 |
| 单 ↔ 双 ↔ 关 | 沿用当前工具行为 | pin 创建时的模式和内容不变；关也不隐藏 pins |
| 取消固定（蓝色图钉） | 接替当前临时候选，恢复对应 single/dual 模式 | 移除该记录的淡线与底部标签，其余 pins 不受影响；该面板原位变为活动面板 |
| 取消固定后继续操作 | 不在点击瞬间跳到鼠标下方；single 下一次有效移动才跟随，dual 下一次正常放置才更新 | 再次 P 可以沿用这次被取回的编号；若放弃该候选则不把编号分配给别的记录 |
| × 关闭 | 无影响 | 删除该 pin 的模型意图、面板、标记；不更改工具模式或其他记录 |
| 撤销关闭 | 无影响 | 现有提示位置提供一次“撤销关闭”，恢复同一编号/坐标/full-mini/锚点；跨 owner 或数据生命周期变化后旧撤销失效 |
| 关闭设置 popover / Esc | 按既有规则处理 | 不等同于删除 pin；不得附带清空 |
| 宿主隐藏或未布局 | 隐藏并等待 | 保留记录，暂停呈现；恢复时按有效几何投影 |
| 空间不足 | 保留既有降级规则 | 保留 full/mini 意图；依次使用受限表格、完整通道块 +N、空间不足状态；极小宿主可暂时隐藏控件，不删除 pin |

mini 保留色点、值、单位及必要分支/状态，不恢复已被用户要求隐藏的通道名。full 恢复名称。Min/Max/Avg/Δ 全关闭时按现有 identity/诊断投影处理，不能把“没有显示数值字段”误判为没有数据。

全局时域显示选项仍只作用时域：固定记录保留完整事实，选项变化只重新投影字段/极值点。FFT/FRF 不继承时域区间统计选项。每张面板的 full/mini 独立，不能由活动面板 toggle 批量改写。

## 6. 位置标记、拥挤与几何

1. 每条记录使用稳定 UUID 作为身份，P1/P2 是所属 View 或 analysis pane 内的展示序号。删除不重编号、不补洞；新编号单调增加，工程重开保持。不同 pane 可各有 P1，命中与提示始终带 owner，不能全局按文本 P1 查找。
2. single 在对应底部 X 轴附近常驻 Pn；dual 在两个端点显示 Pn·A / Pn·B，A=B 时可合为 Pn·A/B。面板标题保持同编号和完整坐标/单位。
3. 时域多子图/共轴在对应共享 X 域的图内绘制淡虚线；FFT 只在频谱区画，FRF 三图都画。双游标保留 A/B 可区分性。基准采用约 1 个逻辑像素、低对比虚线，具体透明度通过真实 Qt 像素验收确定。
4. 悬停或键盘聚焦面板/标签时，同时高亮这一记录的面板边框、标签、线和对应点；离开后恢复淡色。点击标签只置顶/定位对应面板，不修改 X、不偷偷改变缩放、不进入组切换模式。
5. 标签属于专用装饰层，不改真实轴刻度算法、不伪装成新的数值刻度，不遮挡轴标题和数字。数据线位置永远精确；标签避让时必须有细引线指向真实位置。
6. 相邻标签使用稳定排序和有限轴边空间排布，缩放/平移只重投影。极密区域允许紧凑 `P3–P7`/`+N` 簇标签并在悬停时临时展开该位置的编号，点击具体编号只置顶面板；这不是固定组管理列表。不能无限向左挤出界，不能用覆盖数字的方式宣称全部可见。
7. 点移出当前 X 可视范围：保留面板，标明“视野外”；轴边用带方向的边缘标记区分真实坐标标签，不能把数据线 clamp 到边界冒充取点位置。dual 仅一个端点可见时单独处理各端点。
8. 面板复用现有 safe rect。FFT 排除时域预览；FRF 使用明确的三图宿主区域；分屏不能跨 pane。无有效 geometry 时等待，不能退回整个 ChartStack。
9. pin 交接不跳位：标题动作区提前预留 P 提示与固定按钮所需尺寸。首次固定沿用当前面板锚点；因边界需要重排时保持右边/顶部语义。不能像 HTML 简化实现那样靠不同角色的自然宽度造成无解释位移。
10. 新活动面板优先放在不覆盖已有面板的位置；无空白区域时做有界错位，让标题仍可访问，接受用户主动叠放。不自动收起旧面板、不改变其 full/mini。放置求解只在新增/宿主几何变化时运行，不能每次 mousemove 扫描曲线或重排全部面板。
11. pinned 极值点遵循现有时域 point options，从固定记录的事实投影；共轴各成员的极值不能丢失。默认低对比、悬停突出，不能因为 pin 多而静默关闭用户选项。
12. 同时测试 1/2/8/20 个 pin；不因 Demo 只有两张而设置产品上限。极窄空间的降级必须保留可发现的编号/状态；不承诺任意数量都能同时完全展开。

## 7. View、数据与持久化生命周期

### 7.1 所有权

- 可保存意图唯一持有者：时域 `ViewState`；分析 `PaneState`。它们不保存 QWidget/pyqtgraph Item。
- 新的 `PinnedCursorController` 由 ChartStack 持有，绑定当前可见 owner 的状态对象/明确记录接口，负责创建/删除、候选事务、面板/标记投影、运行时结果缓存与失效。
- controller 不另养一份持久化列表。bridge 的 capture/apply 是与 owner 模型交接的唯一边界；对同一集合不允许 MainWindow、canvas、ChartStack 各写一遍。
- canvas 只负责领域事实和数据↔视口变换；返回不可变 DTO，不读 MainWindow session。renderer/marker 层不重新计算数据。
- owner identity 用稳定 View ID、固定集合的 `scope_id` 和领域组成，运行时 canvas 绑定另有 generation。当前 `PaneState` 没有独立 pane ID，因此由新增集合持有稳定 `scope_id`，随所属 PaneState 移动/恢复，不要求改造整个分析 pane 身份体系；不能只用临时 pane 索引或 QObject 地址识别异步回调目标。

### 7.2 拟新增的中立模型（命名为计划接口，不代表当前已有）

`ui/pinned_cursor_state.py`：

- `PinnedCursorIntent`：record UUID、display ordinal、single/dual、time/channel/frequency 域、有限物理 X 或 A/B、Custom-X 来源/通道身份、单位上下文、捕获时通道/curve binding 集合、full/mini、用户锚点。
- 通道身份保留 `(fid, channel)`，同一通道不同可见曲线绑定需要额外 binding identity；来源短名、legend、颜色和 P 编号均不得作为身份。
- FFT/FRF 记录必要的参考/响应/曲线语义身份；相同名称的不同计算角色不能合并。
- `PinnedCursorCollection`：version、scope_id、records、next ordinal。scope_id 为稳定 UUID；旧工程首次创建空集合时生成，序列化后保持；复制 owner 时更换。默认空；归一化检查 UUID/序号唯一、有限数字、合法模式和端点数量，布尔值不能当坐标。
- 位置保存相对于所属 safe rect 的锚点/归一化偏移；窗口变化时 clamp/reflow。不要持久化绝对屏幕坐标或 DPR。

运行时 `PinnedCursorSample`（可放在 `cursor_display_model.py`）：包含上述 identity、完整结构化读数、极值事实、实际有效采样坐标、revision/generation、明确诊断。它是结果缓存，不写工程；full/mini 与字段选项从该结果构建投影。

### 7.3 事件处理表

| 事件 | 固定意图 | 面板、值与标记 |
|---|---|---|
| 平移/缩放/窗口、DPI、字体变化 | 不改坐标 | 只重投影/重排，不做数据重算 |
| 切 View/分析页/pane focus | 留在原 owner | 隐藏旧 owner、绑定新 owner；返回后恢复，绝不把旧 P1 带到新 View |
| 打开/关闭分屏 | 保留对应 View 的记录 | 创建/销毁相应 GUI 投影；关闭分屏不是删除该 View 的 pins |
| 显示/隐藏某通道、增减可见绑定 | 捕获时集合不自动扩张 | 新通道不偷偷加入旧 pin；隐藏通道显示“已隐藏”状态并隐藏其点，保留原身份以便恢复；其值不继续伪装成当前可见曲线读数 |
| 删除绑定/来源关闭 | 显式删除的引用从记录集合移除；全无引用则删除该记录 | 混合来源记录仅移除对应行；不得按同名通道替换。关闭最后文件清空所有相关 pins/缓存/撤销，不动全局显示偏好 |
| 滤波、源数据重载、FFT/FRF 参数变化 | 保留物理位置和语义身份 | revision 失效，进入 pending，结果就绪后一次重采样/投影；失效期间不显示旧数值为当前值 |
| 重算失败/范围内不再有数据 | 不自动吸附到新数据边界 | unavailable + 诊断；允许关闭/收起，数据恢复后可重新求值 |
| 改 X 轴模式/Custom-X 通道或单位不兼容 | 保留原轴上下文 | incompatible_axis；隐藏不适用的线/轴标签，面板紧凑提示“X 轴已更改”；切回匹配轴后恢复。不能把秒或另一个通道值映射到新轴 |
| 仅线性/对数显示变换 | 物理坐标不变 | 在合法域内重新投影，非正频率在 log 域显示不可用，不能造一个正值 |
| 复制 View/pane | 深复制意图 | 新 owner、新 scope_id/record UUID，允许沿用局部 P 序号；控件与结果缓存不共享 |
| 删除 View/pane、新建工程、关闭全部 | 删除该 owner 意图 | 停止信号/计时器，释放 GUI items、缓存和未完成任务；旧回调不得复活记录 |
| Home / Fit / 自动适配 | 保留 pins | 这些是 viewport 操作，不是“清空固定位置” |
| 旧的“清除活动游标位置” | 只按原合同清 A/B | 不能因为复用 `reset_cursor_state()` 而批量删除 pins；数据清空则走明确生命周期方法 |

### 7.4 工程保存与恢复

- 在 `ViewState` / `PaneState` 添加可选 `pinned_cursors`，旧工程缺失即空。不向 QSettings 或 preset 写具体 pins。
- 项目外层 `project_io.SCHEMA_VERSION` 当前为 4，沿用可选字段兼容，不仅为该新增字段改外层容器。分析内部 `_SCHEMA` 当前为 10，计划推进为 11，并更新明确断言和迁移测试；旧 schema 仍可读。实施前若其他工作已推进版本，使用届时下一版本，不覆盖并行变更。
- 在 `project_io.py` 的 fid 重映射路径补 pin 中所有来源、Custom-X 和分析角色引用。工程源暂缺时保留不可用意图/诊断，不能误绑同名来源；这不同于用户显式关闭文件后的清理。
- 解析坏记录逐项丢弃并可诊断，未知 pin payload version 明确跳过提示，不猜读。不得让一个坏 pin 导致整个项目打不开。
- 恢复顺序：绑定 owner → 恢复数据/轴/范围/模式 → 安装固定意图 → 数据与最终几何就绪 → 投影一次。禁止从临时 canvas 的旧 pill HTML 恢复。
- 运行时数据版本不写入工程；重开后从重新加载的数据求值，结果未到前保持 pending。恢复不能启动重复 FFT/FRF 计算；复用现有分析恢复与结果就绪事件。
- 用户新增/删除/取消固定/拖动结束/full-mini 修改标记工程脏；hover、高亮、自动 clamp、pending 与数据重算不伪装成用户编辑。关闭撤销恢复模型变更，不把自动重排位置覆盖用户锚点。

## 8. 捕获、复制与 UltraView

- 复制图片包括当前 owner 的所有可见固定面板、标签和淡线；保持可见 z-order、full/mini 和不可用提示。活动游标是否进入某捕获场景继续遵守现有规则。
- ChartStack pill 在 canvas 外作为浮层存在，不能只调用 canvas.grab。把当前单 pill 合成入口扩成所属 owner 的面板集合，逐项按真实坐标/DPR 合成一次。
- 时域分屏和分析多 pane 合图分别验证：不漏副 pane、不重复合成、不把主 pane 的 P1 画到副 pane。
- UltraView 捕获中 pins 是稳定内容，不能被 `hide_transient_overlays` 隐掉。摘要加入 pin 意图修订、有效结果修订、full/mini 与展示位置；hover 高亮不纳入持久内容摘要。
- 沿用现有每 ref 的 idle 合并、runtime ledger、隐藏/解绑事实与抓取重试，不新增定时截图循环，不在每次鼠标移动时刷新 Board。
- UltraView 静态卡片与 Laser 不接受此 P 固定；Board 原有 P 绘图保持。若现有“临时检查”打开真实图表，只有命中该真实图表时走本计划规则。

## 9. 文件责任划分

表中“新增”均是拟建文件，实施时沿当前包边界创建，不向 facade 塞实现。

| owner / 文件 | 责任 |
|---|---|
| 新增 `ui/pinned_cursor_state.py` | Qt-free pin 意图、规范化、身份/序号、序列化和 remap helper |
| `ui/cursor_display_model.py` | 原子读数 facts；必要的 FRF 中立 DTO；不得导入 Qt |
| `ui/pg_canvas/cursor.py` | 时域/Custom-X 同步取点与无副作用固定位置求值；复用原算法/缓存 |
| `ui/pg_canvas/line_canvas.py` / `frf_canvas.py` | 频谱/FRF 事实、采样坐标、绘图区与频率变换接口；必要的布局通知 |
| 新增 `ui/chart_stack/pinned_cursor_controller.py` | 快捷键路由、事务、状态绑定、结果缓存、面板集合与失效；无 DSP |
| 新增 `ui/pg_canvas/pinned_cursor_overlay.py` | 所属画布的线、点、标签几何和命中；只接收中立事实/意图 |
| `ui/chart_stack/cursor_pill.py` / `cursor_display.py` | pin 标题/动作区、独立 full/mini、FRF 投影及真实文档布局；复用 table planner |
| `ui/chart_stack/stack.py` | 持有 controller、可见 owner 绑定、统一内容/几何入口和多面板合成；不扩散新的状态字典 |
| `ui/view_state.py` / `analysis_view_state.py` | 持有 pin 意图；默认、复制、清空、序列化 |
| `ui/view_bridge.py` / `analysis_view_bridge.py` / `project_io.py` | capture/apply、来源映射、恢复事务与工程兼容 |
| `ui/main_window/_view_mixin.py` / `_frf_mixin.py` / `_analysis_mixin.py` / `_project_io_mixin.py` | 仅在已有生命周期边界调用 owner；不增加 MainWindow 可变状态簇 |
| `ui/analysis_section_page.py` | pane 路由/销毁、分析合图的固定浮层合成 |
| `ui/main_window/ultraview_capture_coordinator.py` / `ui/ultraview_capture_facts.py` | 固定内容摘要、ledger 与捕获事实；与工作区现有改动衔接 |
| `ui/hints.py` / `ui/quickref.py` | P 的范围、双游标未就绪提示、P 标签、full/mini/off 与取消固定行为 |

若 pg_canvas 通过 `_CanvasBackref` 代理新增协作者，声明准确的 `_owned_names` / `_delegate_names`，清理路径对称；不在 `ui/pg_canvases.py` compatibility facade 实现功能。优先复用当前 revision/失效来源，只在 owner 现有信号确实缺失时补窄接口。

## 10. 分阶段实施与验证

### Task 0：锁定当前接口与失败用例

- 核对 HEAD/dirty、当前 schema、实际命令路由，记录并行改动；定位每个 owner 的绑定、数据就绪、失效和销毁信号。
- 建立可复现 Qt 用例：鼠标移动后立即 P（小于 33 ms）、未点击获得焦点仍能 P、双游标仅 A、分屏焦点与鼠标在不同 pane、文本输入与 UltraView P 冲突。
- 冻结 Time-X/Custom-X/FFT/FRF 的原始读数，作为固定前后同值的 oracle；不在测试里复制另一套算法。
- focused baseline 只运行受影响游标/状态测试，不先跑全量。

### Task 1：中立意图与原子事实

- 创建模型及归一化；接入现有数值 owner 的完整事实查询，FRF 补具名事实与纯投影。
- pin 的读取不能改变活动游标状态、发出跨 owner UI 事件或启动分析计算。
- 测试新增 `tests/test_pinned_cursor_state.py`、`tests/ui/test_pinned_cursor_facts.py`：finite/缺失、复合身份、重复坐标判定、A=B/A>B、分支诊断、频率吸附与 log round-trip、不可变快照。
- owner 回归：`test_pg_cursor_placement.py`、`test_custom_x_cursor_contract.py`、`test_pg_line_canvas.py`、`test_frf_canvas.py` 的相关类/节点。

### Task 2：P 路由与多面板交接

- 单一 controller 接入 ChartStack，完成 P 上下文规则、连续 pin、取消固定、删除/撤销和编号。
- 复用 CursorPill 展示与几何 seam，预留动作区；full/mini 独立、活动与固定互不覆盖内容。
- 新增 `tests/ui/test_pinned_cursor_interaction.py` 与 `test_pinned_cursor_panels.py`，覆盖实际 Qt key/mouse 事件、双触发、自动重复、IME、拖动中 P、隐藏 owner、延迟旧结果。
- 回归 `test_cursor_single_pipeline.py`、`test_cursor_table_modes.py`、`test_cursor_pill_formatting.py`、`test_chart_stack.py` 的对应内容/切换节点。

### Task 3：持久标签、淡线与布局

- 实现 markers，处理子图/overlay/FRF 多图、轴区边界、遮挡、相邻/同坐标/极密聚合及视野外状态。
- 几何统一 scene → viewport → canvas → stack，使用逻辑像素；重排与捕获只在输出边界处理 DPR。
- 新增 `tests/ui/test_pinned_cursor_geometry.py`：真实绘制文档、字形与控件边界、标签 hit rect、不遮刻度、从一张到 20 张、host pending、小窗口、拖动后 expand、popover 避让/恢复。
- 回归 `test_cursor_table_geometry.py`、`test_fft_cursor_layout.py`、`test_split_layout_alignment.py`，共轴极值覆盖 `test_pg_cursor_placement.py` 对应回归。

### Task 4：状态绑定、失效与工程 round-trip

- 接入 View/Pane 可保存字段与 bridge，完成 §7 所有事件；重算后结果原子替换，旧 generation 丢弃。
- 接入工程脏标记、复制、fid remap 和部分来源缺失；项目内只持久化意图。
- 新增 `tests/ui/test_pinned_cursor_lifecycle.py`；扩展 `test_view_state.py`、`test_analysis_view_state.py`、`test_analysis_view_bridge.py`、`test_project_session.py`、`tests/test_project_io.py`、`tests/test_project_io_analysis_views.py` 中关联节点。
- 分屏路由用 `test_split_routing.py`、`test_split_per_pane_controls.py`、`test_split_focus_routing.py`；最后文件关闭用 `test_session_reset_on_last_close.py`。

### Task 5：捕获与 UltraView

- 所有图片输出统一按 owner 合成 pins，扩展捕获 facts 和摘要，保持 idle 合并与 Board P 语义。
- 新增 `tests/ui/test_pinned_cursor_capture.py`；扩展 `test_chart_stack.py` 中 copy/presentation 节点、`test_ultraview_capture.py`、`test_ultraview_capture_facts.py` 的 pin 分支。
- 对比“屏幕有线有数值”和“导出图有线有数值”，不能只断言 pixmap 非空。

### Task 6：提示、集成、平台验收

- 同步 hints/quickref 和相应现有帮助说明，不新增独立管理面板。
- 运行 `test_hints.py`、`test_quickref_status_hints.py` 相关节点和 §11 矩阵；新增测试文件不得只检查文案存在。
- 跑适用边界门槛，整理 macOS Cocoa 与 Windows 的独立结论、性能证据、剩余缺口。
- 所有必需模式接通前只报告分阶段完成，不将 Time-X 单游标成功表述为整个 cursor 功能完成。

## 11. 交付验收矩阵

每个编号至少对应一个确定性测试/探针或明确的人工平台验收记录；纯代码阅读不能代替行为证据。对 HTML 未涉及的工程恢复、数据失效、FRF 与 P 键冲突，本文规则是拟实施决策，不宣称已获得真实程序验收。

| ID | 场景 | 验收条件 |
|---|---|---|
| A01 | 鼠标停点，无先前点击，按 P | 正确图表位置原子固定，指针未移到面板；提示可见 |
| A02 | 小于 hover 节流间隔连续移动后按 P | 固定最新物理坐标，line/header/rows 同一版本 |
| A03 | P 长按、同点重按、两点格式化同文 | 不重复触发；真正不同点不被误合并 |
| A04 | 时域 2 X 模式 × single/dual × full/mini | 八种组合字段/颜色/单位/分支一致；固定后活动变化不污染 |
| A05 | dual 无 A、仅 A、完整、A=B、A>B | 完整性判断正确；差值/倒数及诊断不改语义 |
| A06 | FFT single/dual × full/mini，多曲线独立网格 | 吸附、原有差值正确；预览区不能 pin，面板不越频谱边界 |
| A07 | FRF single/dual × full/mini × linear/log | 三图同频率、字段/Δ 正确；Hz 持久化，不把频率映射到时间 |
| A08 | off、空数据、pending、诊断、所有值字段关闭 | 不固定旧值；off 保留 pins；诊断与字段隐藏可区分 |
| A09 | full/mini、拖动、关闭/撤销、取消固定再 P | 只作用目标记录；编号/线/标签与面板同步，无位置漂移 |
| A10 | 1/2/8/20 pins，密集/同 X、长名/单位、极小宿主 | 不裁半个数值；标签可发现；不改真实刻度；空间恢复后恢复用户意图 |
| A11 | subplot/overlay/共轴、主副分屏、分析双 pane | owner 隔离、各成员 extrema 不漏、隐藏源事件不清当前读数 |
| A12 | 焦点在 A、鼠标在 B；输入、IME、popover、拖拽 | 只合法上下文触发；不抢文本/UltraView/标注的 P |
| A13 | 缩放/平移、离屏端点、DPI、字体、窗口 resize | 物理坐标不变；线/标签映射准确，面板安全区正确 |
| A14 | 滤波/重算、改 X、隐藏/关闭来源、晚到结果 | pending/incompatible/unavailable 明确；无旧值冒充新值、无跨身份复用 |
| A15 | 新/切/复制/删除 View、分屏退出、工程重开 | 无串页；默认空、深复制、序号稳定；旧工程兼容 |
| A16 | 坏 payload、来源缺失、fid 重映射、schema 迁移 | 局部降级且可诊断，不丢整工程，不猜测身份 |
| A17 | 单图/分屏/分析合图、UltraView 捕获/解绑 | 同 owner 全部固定内容合成一次，DPR 对齐、稳定 pin 不被当 transient |
| A18 | 20 pins 下持续移动、缩放、反复切 View/销毁 | 移动不重算所有 pins，无逐帧重建控件，无悬空 Qt item/累积连接 |

### 11.1 性能与平台证据

- 记录 0/1/8/20 pins、相同数据/窗口下 hover 和 P 提交耗时 p50/p95、布局重排次数、固定结果求值次数。持续移动只更新活动候选；固定结果求值次数应为 0，除非数据 revision 改变。
- 正常数据下 P 的可见响应目标为下一次 GUI 绘制，不人为加 debounce。重数据若必须异步则立即给 pending，完成时间据实记录，不通过复制旧数值伪装即时响应。
- 使用生产 ChartStack/QSS/QTextDocument 渲染；测量和绘制必须是同一份文档。检查标题、P 提示、按钮、单位、负号、指数、分支诊断及最后一列像素。
- macOS Cocoa 前台检验实际键鼠链路、窗口焦点、popover、拖动/缩放、页面过渡；Windows 100%/150%/200% 单独验收。无相应环境标记 UNKNOWN，不能用 HTML 或 offscreen PASS 替代。

### 11.2 测试执行规则

- 使用项目 runtime：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <focused nodes>`；独立探针也隔离 QSettings。
- 按 Task 运行其 owner tests，只有修改/失败/新风险才扩展或复跑；执行前从现有文件选择准确 node ID，不照抄历史通过数量。
- 集成边界按实际修改运行：`tests/ui/test_import_boundaries.py`、`test_pg_canvas_backref_invariants.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`；布局动作区同时跑 `tests/ui_kit/test_qss_border_shorthand.py`；新的中立模块用独立进程证明导入不拉入 Qt。
- 若新增模块影响打包发现，跑 `tests/test_packaging_imports.py` / `tests/test_native_import_boundaries.py` 的对应门槛；不把 unrelated DSP/Batch 套件作为例行全跑项目。
- 本方案同时跨状态持久化、共享 UI 和捕获，最终稳定集成点安排一次 full gate，由实施协调者唯一执行。先检查没有别的 full pytest 正在该 checkout 运行；记录 HEAD 与相关 dirty 指纹；主套件 `--ignore=tests/acquisition_ui` 完成后，另进程顺序运行 acquisition_ui。两者不能并行，异常退出记 UNVERIFIED。途中相关源码变化则结果不算该最终快照验收。
- 最后检查 `git diff --check`、改动范围与 lesson status，记录失败/未跑门槛；不以“多数测试已通过”掩盖待完成模式。

## 12. 本次计划的交付边界

本次只交付本文件。已读取当前模式/布局/状态/捕获 owner 及相关 lessons；计划中的新模块、接口、迁移和测试尚未实现，也未声称前台或 Windows 验收通过。

本次检查文档引用、现有文件/符号、章节内模式与状态一致性、工作区范围及 diff 空白错误，不需要执行 runtime suite。原 HTML Demo 保持现状；其 FRF、工程持久化、键盘冲突、密集标签和数据失效等不足由本文明确补齐，不视作已完成产品功能。
