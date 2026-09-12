# Cursor 表格对齐与受限宽度规格

- 日期：2026-09-12
- 状态：修订实施规格；全模式排版修复进行中，平台验收独立记录。
- 用户方向：认可 HTML 对齐表格与受限宽度；最新授权为针对三张实机缺陷图全局分析并安排 agent 修复。
- 当前代码快照：`82948f02`；行号为本次阅读定位，实施前以符号复核。
- 当前实施计划：[全模式排版修复计划](../plans/2026-09-12-cursor-rendering-parity-repair-plan.md)；[前次计划](../plans/2026-09-12-cursor-table-readability-plan.md) 为历史执行记录。
- 设计输入：[三方案 HTML](../ui-prototypes/2026-09-12-cursor-readability-options.html)。其 A 方案的 `min-width:720px`、横向滚动、hover title 和 B 默认推荐文案均不构成本规格的产品决策；该原型是历史讨论输入，尚未更新为本规格。

## 1. 目标与范围

让时间轴及 Custom-X 的单/双游标 full/mini 面板成为可对齐比较的读数表，同时控制对图面的遮挡。**宽度由所属图区域和字体度量决定，不能由最长通道名无限撑开。**

本轮范围覆盖结构化时域 Time-X/Custom-X × single/dual × full/mini 全八种组合，以及所属分屏边界。单游标显示当前值；双游标 full 显示已开启统计列，mini 保留 Δ → Avg → Max → Min 优先级。Custom-X 每条真实方向独立成行；诊断、全程和缺失值纳入共享网格。FFT/FRF legacy formatter、Batch、DSP、采样、极值计算、项目 schema 不扩展。

不新增自动隐藏统计项、自动切 mini、横向滚动条、列拖拽、排序、筛选、独立详情窗口或 hover 读数。用户主动点击 `− / +` 才改变 full / mini 意图。

## 2. 当前事实、风险与历史文档边界

| 证据 | 当前事实 | 本次设计含义 |
|---|---|---|
| `mf4_analyzer/ui/chart_stack/cursor_display.py:342` `_block_html`；`:432` `render_cursor_presentation` | 每个通道分别生成 table，循环拼接；标签与带单位的值交替输出 | 各通道无法共享列宽；需一个表格布局计划，而不是继续逐通道调整 padding |
| `mf4_analyzer/ui/chart_stack/cursor_pill.py:544` `reflow_to_parent` | 先尝试无上限 natural，再以父容器 safe rect 约束；constrained 时以整通道截断高度 | 必须先算宽度预算再生成最终布局；不能渲染超宽内容后仅 resize 外框 |
| `mf4_analyzer/ui/chart_stack/stack.py:293`、`:982` | 主、次 pill 都挂在 `self.stack` 下 | 父 widget 宽度不等于各自画布宽度，分屏需要坐标映射后的独立边界 |
| `mf4_analyzer/ui/chart_stack/stack.py:1900` `_reposition_one_pill` | 默认锚定所属 canvas 右上角，但 clamp 仍使用 pill 的父级 safe rect | 锚点正确不代表尺寸预算正确；二者必须使用同一个所属 pane 的 safe rect |
| `mf4_analyzer/ui/chart_stack/cursor_pill.py:338` `set_primary` | primary 有独立 setText / adjustSize 路径 | 只限 detail 不足以约束 A/B/ΔT/1/ΔT 总宽度 |
| `tests/ui/test_cursor_display_settings.py:591`；`mf4_analyzer/ui/quickref.py:409` | 读数面板明确不附加内容 tooltip；projection.tooltip 只是保留的完整文本数据 | 禁止用恢复 hover tooltip 解决长名称或高度溢出 |
| `mf4_analyzer/ui/cursor_display_model.py:13`；`tests/ui/test_cursor_display_settings.py:72` | 六个全局布尔设置、64 组合；四个值字段顺序为 Min / Max / Avg / Δ | 不能沿用早期五开关、32 组合、Δ 必须显示的旧要求 |

上述为初始分析时的历史源码定位；修复前的新探针及缺陷证据见当前修复计划，完成结果见验证记录。用户截图证明原显示难读，但不能据截图像素推导 Qt 逻辑像素上限或 DPI。HTML 浏览器验证也不能替代 Cocoa / Windows 验收。

历史参考：[最初显示规格](2026-08-31-cursor-display-settings-spec.md)、[follow-up 规格](2026-08-31-cursor-display-followup-spec.md)。本规格替代其结构化时域游标的逐通道表格与宽度规则；与现行源码冲突的旧 tooltip、五开关、Δ 常驻描述不沿用。其余既有行为由当前 owner 测试保护。

## 3. 阅读层级与字段语义

### R1 共用表格

- 所有可见通道共用同一组列宽。宽布局列为 `信号 / 单位 | Min | Max | Avg | Δ`，表头只出现一次。值开关关闭后实际删除相应列，不占空白列。
- 通道顺序保持输入的绘图贡献顺序；不按数值、颜色或名称重新排序。
- 名称左对齐；数值右对齐，采用项目已有可用的等宽数字字体。负号、指数、零和缺失符号完整显示。不要为追求相同小数位新增补零或改变 `.4g` 精度。
- 名称和数值用深色；曲线色用于名称旁的小色标，Δ 用字重或淡背景强调，不默认红涨绿跌。名称不再整行高饱和色，单位和表头次一级，但必须在真实底板上读清。
- 沿用现有 QSS 字体级别作为起点，不因容器变窄自动缩小字号。浅色分隔线明确通道边界；不增加每行卡片阴影。
- 本轮保持产品列标签 `Δ`，不把 HTML 的 `ΔY` 文案自动推广至所有游标模式。

### R2 数值与单位

- Min / Max / Avg / Δ 使用已计算的投影结果；展示层不求差、不重新统计、不从四舍五入后的字符串还原浮点数。
- 单位移到同一通道的名称区域，每个通道只显示一次；不能放在全表表头，因为各通道单位可能不同。
- 必须从结构化 `unit_suffix` 传递单位。禁止从 `"0.04102 U_Nm"` 用正则/空格切分推测单位；单位可能包含空格或特殊字符。
- 空单位保持空，不补 `Nm`、`N` 或“无量纲”；不做 `U_Nm → Nm` 美化转换。缺失数值仍为 `—`，不是 0。
- 全部四个值开关关闭时显示名称列表与原 primary，不生成空数据表头。两项极值点开关不改变表格、尺寸、模式或锚点。
- 示例截图中的值按原样作为视觉 fixture；不由这些舍入值检验或修正 Δ，也不虚构配套真实波形。

## 4. 宽度预算与布局降级

### R3 先确定所属图区域

将所属 canvas 的可见 widget 矩形映射到 pill 父级坐标，与父级内容矩形相交，再向内缩 8 个 Qt 逻辑像素，得到 `pane_safe_rect`。此矩形不以整屏宽度、主窗口宽度、截图像素或另一个 pane 的宽度替代。

- 主、次 pane 分别求值；拖动和弹层避让也不得越过各自边界。
- 使用 canvas widget 区域，不直接把 ViewBox 的数据视口误当同一坐标系。
- 首次 show 前无有效 canvas 几何时可暂不显示，等待既有布局完成事件重新测量；不能先显示跨 pane 的宽面板。
- 独立测试或兼容调用没有所属 canvas 时，保留父级内容区域 inset 8 的退路。退路不掩盖已知 canvas 映射失败。

### R4 宽度预算

所有结构化模式使用所属 pane 的安全区域。单位为 Qt 逻辑像素：

```text
Wpreferred = min(Wsafe, 640, max(360, floor(0.60 × Wsafe)))
Whard = min(Wsafe, 640)
```

360 不是 minimumWidth；窄 pane 严格服从 Wsafe。60% 是优先预算；若横向表格能在 Whard 内完整显示，允许超过 Wpreferred 以保留同行。外框按内容实际所需收缩，不无条件填满 640。full/mini 都服从同一硬边界。

### R5 按实际内容选择三种结构

1. **横向表格优先**：`信号/单位 | 方向（Custom-X） | 指标列`。短名称按实际宽度加间距，不设置 200 px 名称最小宽；长名列最多约 200–260 px，最多两行后中间省略。短名 L/R/MOTOR X/Y 在能放下时，名称与值必须在同一行。
2. **分组表格**：只有完整横向确实放不下时，名称/单位独占行，数值仍共用列宽。方向属于每条真实分支行，不伪造、不合并。名称不能扩大数值网格。
3. **紧凑分组**：数值列仍放不下时按原序每行最多两项 `标签 值`；必要时一项一行。对应槽位仍对齐。

单游标 full 是名称/单位与当前值，mini 隐去名称保留色点、方向（若有）、值/单位。双游标 mini 保留名称、方向和一个优先指标。无开启统计项时保留身份/真实分支/诊断，不显示空数值表头。

诊断行在所属通道的指标范围内跨列显示。首通道是诊断、后通道有方向值，或同通道同时有诊断与真实分支时，都不能退出共享表格。`全程`按 DTO 原标签显示，缺失为 `—`，不能用字符串前缀猜测是否分支。

所有结构包括真实字体、字重、色点、单位、cell padding、边框及文档边距。布局必须测量实际绘制的文档；禁止用可换行的独立 QTextDocument 为实际 nowrap QLabel 证明不裁切。若改用薄 QTextDocument 绘制控件，sizeHint、高度和 paint 必须使用同一文档。

布局层只传原始文本行 tuple；renderer 逐行 escape 一次，使用受控 `<br>`。禁止把已转义 HTML 作为纯文本再次 escape。

### R6 名称、单位与极端宽度

- 名称在预算内优先按实际字体度量换行，最多两行后才中间省略。单位作为辅助文本可独立换行；绝不把长单位截成另一种单位。
- 单来源按当前规则省略来源前缀；多来源保留可辨识的来源文本和通道文本，不从显示文本反查数据。不得显示内部 `f0/f1`。
- 相同颜色不能作为唯一身份提示。多来源同名 fixture 必须能看出来源差异；公共长前缀导致可见标签碰撞时优先保留真实来源的差异片段。极端情况下无法兼顾全名与宽度，仍保持复合身份和完整 projection 文本，不声称 UI 已能阅读全名。
- 不恢复 hover tooltip。既有 `projection.tooltip` 保留完整名称/数值供兼容与测试使用，它不等于用户可访问的详情入口。本期仍存在长名称省略后不能在 pill 内查看全名的限制；新增显式详情入口属于后续单独设计，不是本次验收依赖。
- 单项完整数字在一项一行模式仍无法容纳时，该通道不显示部分读数，计入整块省略摘要；单位可按自身辅助行换行。若 primary 与摘要合计仍放不下，则仅显示 `空间不足` 状态；这条短状态本身也放不下时隐藏浮层。上述顺序固定，不截断半个数字、侵入另一 pane、缩小字体或保留过期值；恢复有效尺寸后自动恢复用户原 full/mini 意图。

### R7 Primary 同样服从预算

- A、B、ΔT、1/ΔT 保持现行显示值、符号、精度与存在条件，零区间不凭空增加 Hz。
- 完整 label/value 片段作为换行单位。预算不足先将 A/B 与 ΔT/1/ΔT 分两行，再按单片段换行；切勿保留 detail 限宽却让 primary 撑开外框。
- 在展示 owner 处理受控格式的片段布局；复用现有格式化/分隔契约，不读 HTML 重新计算时间差，不以任意正则解析未知 legacy 文本。
- `set_primary` 先到、结构化 rows 后到的正常事件顺序也必须保持预算，不短暂露出超宽中间态；右上 `−/+` 的占位纳入第一行计算。

### R8 稳定性、缩放与高度

- 同一组通道/字段/字体/宿主尺寸下，鼠标移动只更新值，不反复变换列宽和表格结构。按当前 `.4g` 格式度量符号、小数、指数所需的安全宽度；遇超出预留的实际字符串只允许必要增长，同一结构周期内不随下一个短值收缩。
- 布局预算/字体/DPI/通道集合/字段开关/full-mini/X 模式变化时重新测量。Qt 逻辑尺寸不能手动再乘 DPR；100%/150%/200% 字体与显示缩放分开验证。
- 隐藏、clear、退出 split、View 恢复和所属来源失效时，新建的测量或结构状态对称清理。只缓存原始尺寸/字符串等展示数据，不持久化 widget 或 process-local cache。
- 高度继承整通道块保留和 `+N channels` 摘要；按最终布局计算能容纳的通道数，表头和 primary/摘要均计入。不得截掉通道的一半；零通道时不留孤立统计表头。
- 没有增加竖向滚动或完整详情入口；`+N channels` 仍只是省略摘要，不伪装为可点按钮。后续窗口变高可恢复完整块。
- 默认贴所属图区域右上；用户拖动后保存 top/right，内容变化只在所属 safe rect 内 clamp。弹层避让与恢复不累积漂移；空间确实无法避让时记录为待解决的碰撞，不声称成功。

## 5. 实现归属与兼容边界

| Owner | 责任 |
|---|---|
| `ui/cursor_display_model.py` | 保留中立 DTO；若需要，末尾追加有默认值的纯展示字段，如不含单位的格式化文本、原单位；不导入 Qt、chart-stack 或 MainWindow |
| `ui/chart_stack/cursor_display.py` | 已计算结果到单表投影；统一字段顺序、HTML 转义、单位来源、精度和无值状态；现行 public exports 保留 |
| `ui/chart_stack/cursor_table_layout.py` | 仅承载有界表格布局选择和列宽计算，输入为宿主预算/字体度量后的数字及展示信息，输出布局计划；不管 Qt 生命周期或分析计算 |
| `ui/chart_stack/cursor_pill.py` | 实际字体测量、一次应用布局、primary 预算、外框绘制、锚点、临时布局状态与清理 |
| `ui/chart_stack/stack.py` | 解析所属 card/canvas、映射 pane safe rect，沿现有 `_update_pill_content` 入口更新；split resize 后触发布局，不写 MainWindow 状态 |
| `ui/hints.py`、`ui/quickref.py` | 同步“表格随可用宽度分行、− 收 mini、无 hover tooltip”的产品说明 |

- 不能把已拼接 unit 的 `CursorDisplayRow.value` 改成裸数字而破坏旧投影。附加字段保留旧构造/值格式语义；旧调用未提供新字段时走既有兼容格式，不猜测单位。
- 全部八种结构化时域模式进入新表格渲染；FFT/FRF legacy 保留。Custom-X 的 `X↑ / X↓` 不合并，mini 优先级仍为 `Δ → Avg → Max → Min`。
- 保持 managed rows 单管线：每次 move 一次 `set_display_projection`，不额外触发 legacy detail。区分“一次投影更新”和内部 size 测量；不得通过多次实际 `setText + layout.activate` 遍历通道来选择宽度。
- 不新增对 `signal/`、`pg_canvas` 的展示依赖，不改兼容 facade、不改 DSP、不重算 delta。
- 新表格必须在 PyQt5 富文本真实能力内实现；不能把浏览器 CSS grid / flex / sticky 直接照搬成 Qt 方案。优先单个 QTextDocument/table 的确定列宽路径，若 QLabel 不满足列宽控制则在同一 presentation owner 内使用薄绘制控件，先补真实渲染证据再改实现选择。
- 新的边界状态传递必须兼容 snapshot/restore；历史纯文本/频谱格式冻结测试不应被这次表格重排顺带重写。

## 6. 验收合同

| ID | 场景与可验证结果 |
|---|---|
| A01 | 截图四通道及短名称 fixture，P=1200/900/800/560/500/360：外框不超 Whard / pane_safe_rect；短名称在可容纳时同行；无水平滚动，无被截的可见数值 |
| A02 | 分组模式所有通道同指标右边缘相差不超过 1 逻辑像素；紧凑模式对应槽位也保持同一右边缘。检查实际文本布局/渲染坐标，不仅查 HTML 字符串 |
| A03 | 0/1/4/12/50 通道；不同单位、无单位、长单位、极长名称、重复名称/不同来源、`<>&` 字符；身份不合并，单位不伪造，无注入和孤立空格列 |
| A04 | 64 设置组合保持正确性；四值开关全部关闭仍有名称/primary，point bits 变化不改变布局；缺失值为 —，负数/指数没有剪裁 |
| A05 | 260×72、500×180 等低高度宿主：整块截断，正确 +N；没有半个通道或空表头；零尺寸/不可见恢复不保留错误布局 |
| A06 | primary 先到/rows 后到、切 full/mini、用户拖动、弹层开关、View 恢复、clear：无超宽闪烁、右边缘漂移或 stale 状态；正常 900 px 单游标的单次 `_apply_display_projection` 计数护栏不放宽 |
| A07 | 左右非等宽、上下分屏及分割条拖动：各 pill 用各自的 canvas safe rect；仅重排不重新采样、重做 DSP 或串改另一 pane 的结果 |
| A08 | 同一个布局周期连续 100 次值更新（0/负号/跨数量级/科学计数）：列位置稳定；在格式包络内不重复测全表/应用多次布局。记录单更新成本；本规格不捏造通用 ms 门槛 |
| A09 | 全八种结构化模式、FFT/FRF legacy、复制图像/UltraView presentation capture、透明圆角、无内容 tooltip 的既有合同保持 |
| A10 | offscreen 几何/像素检查、真实 macOS Cocoa 前台、Windows 100%/150%/200% 各记独立状态。HTML 通过不能填写 Qt PASS；Windows 缺席时写 UNKNOWN，不声称跨平台完成 |

最低真实视觉矩阵：截图四通道 × 宽图/560 窄图/非等宽 split；再补一组长名称 + 混合单位 + 缺失值，以及收起/恢复和弹层避让。截图应包含实际 TraceLab 画布，验证面板遮挡、字重和圆角像素；Qt 离屏导出的孤立面板是辅助证据。

## 7. 状态与证据

本规格已修订此前“只 Time-X dual full / 永远 grouped”的错误限制。当前修复按三张用户截图和八模式矩阵执行，具体 agent 状态、失败回归、真实渲染和未完成平台门槛见[修复计划](../plans/2026-09-12-cursor-rendering-parity-repair-plan.md)与验证记录。旧 HTML 仅是视觉方向；Qt 生产 QSS、实际绘制和前台证据分别验收。Windows 未运行时保持 UNKNOWN，不以 macOS 或 offscreen 替代。
