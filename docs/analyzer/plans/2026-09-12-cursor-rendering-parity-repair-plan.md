# Cursor 全模式排版修复计划

- 日期：2026-09-12；状态：实现与本地集成完成；原工程前台及 Windows 平台门槛仍 UNKNOWN，见第 6 节。
- 授权：用户提供三张实机缺陷截图，要求全局分析、写 plan 并安排 agent 执行；包含源代码修复与必要验证，不包含提交/推送。
- 基线：`82948f02` + 前次 agent 的未提交改动；14 个相关文件的修复前副本及 SHA256 已保存至 `.state/cursor-table-audit/before/`。不回滚已有功能，不触碰无关 `ssh-keygen`。
- 本计划的产品合同取代 [原 spec](../specs/2026-09-12-cursor-table-readability-spec.md) 中“仅 Time-X dual full”“完整形态始终 grouped”的限制；旧 [plan](2026-09-12-cursor-table-readability-plan.md) 的完成状态仅描述前次执行，不代表本轮验收。
- 视觉方向：[四状态示图](../ui-prototypes/2026-09-12-cursor-final-states.html)。实际 Qt 和用户截图优先；不照搬 CSS，不把 HTML 的字体像素当作原生校准。

## 1. 全局结论与缺陷优先级

| 编号 | 级别 | 根因及定位（修复前） | 用户后果 |
|---|---|---|---|
| F1 | P1 | `cursor_pill.py:_fit_name_html/_fit_name_lines` 与 `cursor_display.py:_render_shared_table` 的边界传递已转义 HTML，renderer 再转义；普通字重度量和实际 600 字重/色点/单位占用也不一致 | 名称未按真实占用收束，挤宽表格，最右统计值被截 |
| F2 | P1 | `cursor_pill.py:_measure_html` 使用带 textWidth 的 QTextDocument；实际 `_apply_table_html` 设置 QLabel wordWrap=False。`test_cursor_table_geometry.py:doc_blocks` 又用强制 textWidth 的另一个文档作验收 | 测试文档看似在界内，实际 QWidget 的文字仍越界；外框 clamp 不能证明值完整 |
| F3 | P2 | `cursor_table_layout.py:choose_table_layout` 不再返回 horizontal，所有常规尺寸一律 grouped；验证还固定断言 grouped | 短名 L/R/MOTOR X/Y 也强制分两行，与 A 示图不一致 |
| F4 | P1 | `cursor_display.py:build_cursor_presentation/render_cursor_presentation` 和 `cursor_pill.py:reflow_to_parent` 双重限定 Time-X dual full，Custom-X 缺结构化 table rows | 诊断行、X↑/X↓ 分支继续旧彩色独立表格，无统一边界与列宽 |
| F5 | P2 | 旧验证未加载完整 production QSS，主要 fixture 使用短名；无前台验收却修改 spec 为“grouped 唯一完整形态” | 测试保护了实现形状，未保护示图要求；平台 UNKNOWN 没有阻止视觉偏离 |

修复前聚焦基线：`test_cursor_table_layout.py + test_cursor_table_geometry.py + test_cursor_single_pipeline.py`：**47 passed, 16 warnings**。这是旧测试在缺陷存在时仍通过的证据，不是修复结果。

## 2. 本轮展示合同

### C1 覆盖面

时域结构化 rows 的 Time-X/Custom-X × single/dual × full/mini 八种组合均采用同一可测的表格展示边界。FFT/FRF 的 legacy formatter 不改计算/输出语义，但回归共享容器的宽度和清理。

| 模式 | full | mini |
|---|---|---|
| Time-X single | 名称 + 当前值/单位，同一逻辑行 | 色点 + 当前值/单位，同一逻辑行 |
| Time-X dual | 名称/单位 + Min/Max/Avg/Δ（仅开启列） | 名称 + 一个优先指标/单位，优先 Δ，其次 Avg/Max/Min |
| Custom-X single | 名称/单位 + 方向 + 当前值，各真实分支有一条值行 | 色点 + 方向 + 当前值，保持每条真实分支 |
| Custom-X dual | 名称/单位 + 方向 + 开启统计列，各真实分支独立对齐 | 名称 + 方向 + 优先指标/单位，保持每条真实分支 |

状态/无数据/全程/缺失分支也是表格内容：诊断在所属通道的跨指标列单元格内显示；`—` 为缺失数值，不捏造零或不存在的方向。全程标签按原 DTO 值展示，不靠 `startswith('X')` 判断。整通道截断时其全部分支和诊断一起保留或一起省略。

### C2 宽度和结构

- 所属 pane safe rect 仍为 canvas 映射相交后内缩 8 px。绝对上限 `min(640, Wsafe)` 保留；原 `60% / 360` 作为首选预算，不作为必须拆行的强制阈值。
- **横向优先**：按实际名称/来源/单位和启用列度量选择；短名的信号列按实际宽度加必要间距，不强迫 200 px 最小值。若完整横向表能在绝对上限内放下，允许超过首选比例预算以保留同一行；外框只取实际所需宽。
- 长名的信号列最多分配约 200–260 px，最多两行后省略，不能无限挤压数值。横向确实放不下才使用共享数值网格的分组结构；仍不足才两项/一项一行。不能用“永远 grouped”替代适配。
- 单位放在所属名称辅助区，或 single/mini 数值旁；单位有单独原始字段，禁止解析已拼接值来猜单位。现有精度、正负号、指数、六项设置和 delta 算法保持。
- 留出真实 cell padding、边框、色点、字重、document margin、QLabel content/indent 和 toggle 的占用；文字不能贴边或压进相邻行。名称和数值用深色，色点保留曲线色，次级表头可读；不额外添加全局颜色含义。
- 原 QSS/字号为起点，不通过整体缩小字体隐藏缺陷。基础字号/DPI/font key 进入测量状态失效条件；同一结构周期内数值列不随正负或科学计数变化反复缩放。

### C3 单一转义与同一测量对象

- 布局层传递原始纯文本行 tuple；renderer 逐行 escape 一次，再以受控 `<br>` 拼接。不得混用 plain header override 与已转义 HTML。
- 测量和实际绘制必须使用同一文档配置/字号/字重/wrap/边距。不接受“另外造一个可自动换行的文档”作为实际 QLabel 无裁切证明。
- 测试必须覆盖 production QSS 下真实 widget 渲染，比较实际内容边缘与可见区域；必要时使 detail 使用薄 QTextDocument 绘制控件，测量和 paint 直接共享该 document。优先最小修复，不另建大型通用表格框架。
- primary A/B/ΔT/1/ΔT 与 Custom-X A/B/ΔX 同样受预算约束；不改变已计算文本，不拆数字，按整字段换行；primary 与 rows 分批到达不能闪出超宽旧内容。
- 不恢复读数 hover tooltip，不增加全量详情窗口；full/mini 必须真实不同且 `−/+` 能恢复原意图。新 transient 布局状态不持久化，clear/restore/split 对称处理。

## 3. Agent 分工与共享接口

父协调者负责：规格/计划、集成、生产 QSS 与真实 Cocoa/前台探针、跨模块回归、lesson 收尾。所有 agent 保留他人变更，只跑各自 focused 测试，不运行完整 suite。

### W1：投影与全模式 renderer

- 独占：`ui/cursor_display_model.py`、`ui/chart_stack/cursor_display.py`、`tests/ui/test_cursor_display_settings.py`；允许新增 `tests/ui/test_cursor_table_modes.py`。
- 新增兼容有默认值的中立 `CursorTableRow`：`branch_label: str`、`metric_texts: tuple[str, ...]`、`diagnostic: str`。`CursorDisplayBlock.table_rows` 仍按一个 composite channel 容纳多行；旧 `visible_rows/tooltip_rows/metric_texts` 接口保留。所有模式填原始 `unit_text`。
- `CursorPresentation.metric_labels` 反映当前展示列：single 的当前值、dual full 开启列、dual mini 优先列。未开启任何统计项时仍保留 identity/branch/diagnostic，不造空值。
- renderer 统一所有 structured modes；Custom-X 独立方向列（或窄布局分支前缀）及诊断跨列。允许新增 `header_lines` 纯文本接口，保留旧 `header_overrides` 兼容并明确互斥优先。
- 与 W2 共享既有 TableLayoutPlan，新增字段只能采用有默认值的兼容扩展。branch 占用预算由 W2 明确传递；renderer 不做字体测量。
- 聚焦门禁：模式矩阵、64 设置组合、source labels、缺失/诊断/全程/特殊字符/单位、单次转义；不得改 DSP。

### W2：实际字体布局与 pill

- 独占：`ui/chart_stack/cursor_table_layout.py`、`ui/chart_stack/cursor_pill.py`、`tests/ui/test_cursor_table_layout.py`、`tests/ui/test_cursor_table_geometry.py`。
- 恢复 horizontal 可达；信号列用实际测量，数值列/方向列明确占位；若所有值列过宽采取分组/紧凑，不只缩外框。
- 用 W1 的 table_rows 扫描值宽与分支；全部 structured modes 进入统一 budget 渲染。mini/name hidden、identity-only、诊断-only 都显式处理。
- 修复转义、字重、单位/色点、wrap/indent/文档边距差异，测量最终实际渲染对象。保留单次 projection/legacy接口、snapshot和safe rect合同。
- 聚焦门禁：三张截图 fixture、真实 QSS，短名横向同行、长名无 clipped ink、Custom-X诊断/分支、全8组合、0/负数/指数、窄高度、primary先到、100次更新。

### P：父协调者集成与证明

- 独占：spec/plan/verify、`hints.py`/`quickref.py`；必要的 `stack.py`/`_view_mixin.py` 修补只在复现集成缺陷后修改，不回滚旧修复。
- 在 agent 修改前保存基线；在整合后阅读 diff，检查源数据与数值算法未变化，导入/所有权方向未扩大。
- 生产 QSS + 实际 CursorPill/ChartStack 的 screenshot 1长名、screenshot 2短名、screenshot 3诊断/双方向分别真实渲染；再覆盖 full/mini 与 single。原始探针/PNG/几何留 `.state/cursor-table-audit/`。
- 修订前次验证记录：旧 pass 是历史基线，新 FAIL/修复结果/平台未知分列；不能把新截图当原始客户文件已完全验证。

## 4. 执行顺序与验收

1. **分析/冻结（已完成）**：保存 dirty 基线，读取实际源码/示图/三张缺陷图，旧 focused 基线 47 passed；记录计划后再派发实现。
2. **并行 owner 修复**：W1/W2 先落失败测试再修；共享 DTO/参数契约在派发时冻结，任何变动即时通知协调者。允许依赖接口落地后再跑集成测试，不放宽断言临时糊绿。
3. **父协调者集成**：W1/W2 完成后集中运行 layout/geometry/modes/settings/single/source/formatting；split/pill/capture针对节点；hints/quickref；import/state ownership/no-lambda及相关像素门禁。
4. **真实渲染**：至少 500/800/1200 逻辑宽、production QSS、不同字体/缩放，记录实际 text bounds、外框、安全区域与列位置。短名宽场景必须同一数据行；长名末列完整；Custom-X 诊断和值在同一表格边界。
5. **前台检查**：启动独立验证实例或独立探针，不擅自关闭用户的当前工程。使用 Computer Use 查看新代码实际窗口；若无法验证用户已加载数据，则明确区分“真实 QWidget/Cocoa 已验”与“原工程重载未验”。Windows 缺环境保持 UNKNOWN。
6. **收尾**：更新文案/spec/plan/verify，执行 diff --check、lesson 检查；只报告本轮实际通过证据。无发布授权不 commit/push。

## 5. 必须阻止再漏的检查

- 不能仅断言 `QTextDocument.size().width() <= setTextWidth(...)`；该条件可由测试自身设定满足。
- 不把“所有值列X对齐”当成“内容完整”，还需可见区域 containment/像素或同文档 glyph bounds；列整体在屏外也可能彼此对齐。
- 禁止断言宽窗口必为 grouped；改为短名同行、长名按实测降级、数值完整的用户合同。
- 不用只含 `CenterFeelTorque` 的短名替代 `Rte_*_xds16` 原始长度；特殊字符、括号、空格、单位和分支标签须真实进测试。
- 不把首个 healthy channel 作为全表模式判断依据：诊断-only 通道在前、healthy branch在后也须正确。
- full suite 非本轮默认门禁；若出现顺序污染等具体问题才说明理由扩展。异常退出/timeout 均标 UNVERIFIED。

## 6. 当前状态

- W1：完成全模式 DTO/renderer，并修复零可见通道的孤立表头。
- W2：完成共享测绘文档、横向适配、两行名称、primary/legacy 切换和空间不足边界；P 完成生产 QSS + Cocoa ChartStack 渲染，集成结果见[验证记录](../verify/2026-09-12-cursor-rendering-parity-repair.md)。
- 前次工程的未提交修复保留；原数学行为、QSettings、工程数据、已有用户布局均不作为排版修复的可牺牲项。

- 最终冻结源码门禁：owner 97 passed；父协调者几何/游标/分屏/复制集成143 passed。Cocoa DPR2三类fixture及八模式实际渲染通过；用户原工程未重载，Windows未运行。
