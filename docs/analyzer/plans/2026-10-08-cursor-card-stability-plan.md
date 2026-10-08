# 游标卡片连续交互稳定性优化计划

状态：已完成实现与本地验收（原工程手势和 Windows 验收未执行）。授权：用户要求写 plan 并安排 agent 同步执行优化。

## 问题与证据

原生 Cocoa 生产控件复现：P3 的时间从 31.5810s 到 31.5925s，标题宽度从 102.73 到 105.02，跨过 103 的内容宽度，卡片由 123×114 变成 123×131。正文数值保持不变仍反复跳变。实际 ChartStack 实时游标宽度 182↔185。矮窗格还会因标题换行改变可见通道数量。记录在 `.state/cursor-height-analysis/`。

既有 focused tests 774 passed，但没有检查上述连续交替输入的几何稳定性。本任务不运行全量基线。

## 成功标准

1. 同一游标/显示模式/通道配置/宿主几何下，截图两个时间值反复更新不改变卡片尺寸、标题行数或可见通道数量；实时单游标不左右往返伸缩。
2. Pn 与数值/完整、关闭按钮布局明确，标题数值完整、可读且不与控件重叠。测量和绘制使用同一生产文档配置。
3. 普通读数仍实时更新。遇到更宽坐标或真正新增的分支/诊断内容，可有必要的有界扩张；随后短值或内容减少不反复缩回。不能用旧读数、裁切数字或虚构分支换取稳定。
4. 稳定尺寸状态是每张卡片独有的短期展示状态；模式、字段、通道、字体/DPI、宿主可用区域发生结构变化时重建；clear/teardown 对称清理；不存入工程意图或全局设置。
5. 矮窗格保持真实内容和明确省略反馈，不因普通标题数字变化反复增删正文行。所有卡片必须留在所属画布安全区域。
6. 固定卡片内容更新完成后再协调锚点、避让与连接线。保护用户放置位置、底边锚定、分屏和多 Pin 行为。
7. 既有单次结构化 projection 路径、数值精度、DSP 算法、原始数据、设置语义保持不变。

## 实施方案

### A. 卡片排版与瞬态尺寸状态

Owner：agent `cursor_layout`。

- 文件：`ui/chart_stack/cursor_pill.py`；必要的私有布局辅助文件；`tests/ui/test_cursor_table_geometry.py`；新增 `tests/ui/test_cursor_layout_stability.py`。
- 先补截图时间值交替更新的失败用例，再实现。
- Pinned 标题明确预留 Pn 和操作控件空间。坐标行按稳定预算排布，不用每帧文本宽度决定 Pn 是否独占一行。
- 标题、卡片外框和正文高度预算采用每结构周期的有界保留机制；仅使用等宽字体不足以处理符号、位数、指数和字段出现/消失。
- 分离稳定结构标识与随采样改变的分支/诊断细节；保留必要的显示空间但不保留过期读数。注意现有表格数值 envelope 的正确行为。
- 保持紧凑布局，禁止通过一律使用最大宽度/固定巨大高度掩盖问题。
- Focused：新增稳定性测试 + cursor_table_geometry / cursor_table_modes / cursor_pill_formatting。

### B. 更新事务、定位与连接线

Owner：agent `cursor_placement`。

- 文件：`ui/chart_stack/stack.py`、`ui/chart_stack/pinning/presentation.py`；新增 `tests/ui/test_cursor_placement_stability.py`。
- 先确认真实调用路径，补更新后锚点和连接线几何探针/测试。
- 如中间 resize/move 导致多次连接线发布，只在内容更新事务最终几何上同步；范围限定在 owning presenter，不添加第二套持久状态。
- 修复任何实证确认的坐标/避让重复结算问题；没有证据的推测不做重构。
- 不编辑 cursor_pill.py；若需要小接口，先告知协调者和 A。
- Focused：placement 新测试 + pinned_cursor_geometry / pinned_cursor_panels / cursor_single_pipeline；边界：no_lambda_signal_connections。

### C. 跨模式验证与原生证据

Owner：agent `cursor_validation`。

- 文件：新增 `tests/ui/test_cursor_content_stability.py`；`.state/cursor-stability/` 下专用验证脚本/证据。
- 覆盖 Time/Custom-X/FFT/FRF、single/dual、mini/full、符号与指数、A=B、分支与诊断切换、短 safe rect，以及合理的设置结构切换。
- 先建可复现失败探针；A 完成后验证实际 painted document 几何，不用独立文档的理想尺寸代替。
- 原生 Cocoa 验证截图值序列和真实 ChartStack 信号链；记录尺寸、可见条目和位置。原工程/Windows 未执行必须明确标注。
- 不修改产品代码；将发现及时交给 A/B，避免重复实现。

### 协调者

- 管理公共约束与跨 agent 接口；任何文件只有一个写入 owner。
- 保留工作区已有版本、Nm、FRF、Windows 脚本等无关修改；不 commit/push。
- 更新本计划状态、必要的 hints/quickref 用户说明。
- 所有 workers 仅跑各自 focused gates，不运行 full suite。
- 集成后由协调者运行必要的 focused 联合检查与 `git diff --check`，避免重复运行不变的通过测试。
- 检查 lessons 状态；本次若建立新的连续几何验收约束，记录短 lesson。

## 验收边界

- 必须：生产 QSS 下真实 QTextDocument glyph bounds、连续序列稳定性、native Cocoa 卡片与 ChartStack 截图/几何证据。
- 有关边界：`tests/ui/test_no_lambda_signal_connections.py`；若新模块改变依赖则补 import-boundary。不涉及 canvas collaborator 所有权或 DSP，不扩展无关门禁。
- 不宣称：Windows 冻结包或用户原工程手势验收。只有真实执行后才能标为通过。

## 执行记录

- 已完成分析阶段：原生复现与 774 项既有 focused tests。
- A/B/C：已并行派发，文件所有权互不重叠。
- A 已实现：结构周期保留标题/分支列/外框尺寸，Pn 与操作控件固定首行；标题按数字形状预留宽度，真实文本不变。原生检查捕获并修复 QLabel 内容区裁切；首帧布局前 polish 卡片自身，避免首次 show 的字体变化误清空保留尺寸。
- B 已完成：实证修复多 Pin 旧占位、更新中间连接线发布，以及 display-only 更新丢失 bottom anchor。新增 4 项回归；focused + restore/pending/transition 指定门禁 96 passed。
- C 已补 46 项跨模式/空内容/结构 reset/首次显示回归；原生 32 种生产文档组合及实际 Time 信号链 4 种组合通过；首次长内容→短→长→短保持 151×146，首次字体初始化问题已关闭。


## 最终集成结果

- 产品改动仅 `cursor_pill.py` 与 `pinning/presentation.py`；无 DSP、工程 schema 或设置语义改动。没有新增/删除/改名交互，不需改变 hints/quickref 的操作说明。
- 新增回归 56 项：layout 6、content 46、placement 4。
- 集成检查：985 passed、1 failed。失败用例为既有 FRF log-frequency 键盘微调测试，在改前 HEAD 两个产品模块的导入基线中同样失败：已有 FRF source-pair 校验要求完整 input/output context，旧夹具仍为空 context/单一绑定。
- 仅补齐该旧用例的真实 input/output 来源和角色，保留 ready 与下一频点 100 Hz 断言；单独补测 1 passed。合计 986 个相关用例通过；没有将第一轮含失败的运行记成全绿，也没有为它改动产品逻辑。
- 集成期间所改两个产品模块及三个新测试文件的 SHA256 未变化。日志：`.state/cursor-stability/integration.log`、`frf-interaction-head.log`、`frf-interaction-fixture-fixed.log`。
- 最终协调者 Cocoa 重跑：32 production-document sequences、4 actual Time canvas signal-chain sequences 通过。原始截图值从第一帧起固定 138×114，读数继续更新；真实双游标 A/B/ΔT/1/ΔT 全部可见。
- 原生边界另覆盖短 host、分支、诊断、指数变化；证据：`.state/cursor-stability/native-final.log`、`native-content.json`、`fixed-p3-0.png`、`fixed-p3-1.png`、`chartstack-dual-mini.png`、`initial-show-after.json`。
- `git diff --check` 通过。连续几何验收 lesson 已通过项目工具入库。
- 未执行 full suite、用户原工程拖动回放或 Windows 冻结包验收；未 commit/push。已有 Nm、8.4.3、FRF、构建脚本等无关修改保留。
