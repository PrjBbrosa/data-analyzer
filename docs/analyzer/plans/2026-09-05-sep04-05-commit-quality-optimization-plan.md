# 9 月 4–5 日提交质量 Review 与优化 Plan

日期：2026-09-05。状态：**REVIEW COMPLETE / NEEDS REVISION；优化待执行**。

本轮授权为提交审查和编写计划。未修改产品代码、正式测试、设置或版本，未提交或推送。本计划默认由一个实施者按依赖顺序执行；不创建任务、agent 或自动化。

## 1. Review findings：按严重程度排序

以下原始行号以 `c84360f2` 独立快照为准；收尾新增 `752adaaa` 已增补审查，涉及漂移的行号另行标注。

### R1 · P1 · 共享几何适配把客户区坐标传给顶层窗口 move，实际外框越界

- 引入提交：`6b3105a5`。
- 位置：[dialog_geometry.py](../../../mf4_analyzer/ui_kit/dialog_geometry.py) L517–534，尤其 L531；最新 `752adaaa` 对应 L532–549、关键 L546，仍传入 `client.x/y`；`plan_geometry` 已分别输出 `client` 和 `frame`。
- 触发：带原生标题栏的 QDialog 使用 `fit_window/apply_plan`，首选尺寸达到工作区预算。`resize()` 使用客户区尺寸正确，但顶层 `QWidget.move()` 的定位包含外框，传入 `client.x/y` 会再次叠加装饰偏移。
- 本轮 offscreen 实测：计划外框 `(8,8,784,584)`，实际为 `(10,10,784,584)`，不在 8px 安全区内。
- 本轮原生 Cocoa 实测：工作区注入 `(0,40,800,600)`，真实 frame insets 为 `(0,32,0,0)`；计划外框 `(8,48,784,584)`，实际 `(8,80,784,584)`，向下多偏移 **32 logical px**。在新增 `752adaaa` 快照复跑仍得到相同偏移。这是运行生产几何 helper 的真实 Cocoa QDialog 探针，使用合成工作区；不是完整 TraceLab 前台验收。
- 影响：共享适配的有标题对话框会偏离居中位置，大窗口底部可能侵入 Dock/taskbar 区域。纯 `plan.frame` 的包含断言无法覆盖这个错误；现有 shown-widget 测试把 insets stub 为零，也绕开了关键情况。
- 处置：保留纯规划器；在 Qt 应用层明确区分顶层 frame 定位和 embedded client 定位。以显示后的实际 `frameGeometry()` 验证，不增加固定“再上移 32px”补丁。

### R2 · P2 · 奇数长度平均 FFT 的 NFFT 和 Δf 事实不正确，GUI 与 Batch 都受影响

- 引入提交：`e72606a3`；`e5ec1fa9` 继续沿用该事实入口。
- 位置：[signal/fft.py](../../../mf4_analyzer/signal/fft.py) L170–183、L329–340；[batch_compute.py](../../../mf4_analyzer/batch_compute.py) L726–760；提交版 [_fft_mixin.py](../../../mf4_analyzer/ui/main_window/_fft_mixin.py) L312–329。
- 触发：Fixed NFFT=4096、线性平均、实际信号长度为奇数且小于 4096。Analyzer 合法地 clamp 到真实样本数；facts 却优先用 `2 * len(freq)` 覆盖确切长度。半谱长度不能区分 3552 与 3553。
- 直接调用 Batch producer 的结果：

| Fs | 样本数/实际 NFFT | 报告 NFFT | 频率轴实际间隔 | facts 报告间隔 |
|---:|---:|---:|---:|---:|
| 1000 | 63 | 62 | 15.873015873 | 16.129032258 |
| 1000 | 129 | 128 | 7.751937984 | 7.812500000 |
| 1000 | 3553 | 3552 | 0.281452294 | 0.281531532 |

- 影响：数值谱轴本身正确，但 Inspector、导出事实与实际计算不一致；结果 parity 不能证明共享错误不存在。
- 处置：事实来自计算 owner 的实际 segment/FFT 长度，禁止从频率数组长度逆推不可逆信息。保持现有 tuple 返回兼容，不为此重写算法。
- 在途状态：工作区已有未提交 GUI 修正，在 Welch 分支绕开频率轴推断；共享 builder 和 Batch 尚未因此修复。本计划按提交版记录问题，实施时整合既有修改，不能覆盖或重复造另一份 GUI-only 解决方案。

### R3 · P2 · Fixed 零填充被展示为更长的真实窗口

- 引入提交：`e72606a3`。
- 位置：[signal/fft.py](../../../mf4_analyzer/signal/fft.py) L375–384，`window_s = nfft_actual / fs`；[事实格式器](../../../mf4_analyzer/ui/inspector_sections/_effective_facts.py) L153–166。
- 触发：Fs=1000Hz，真实 1000 点，Fixed NFFT=4096，单帧或峰值保持。现有算法允许零填充，计算行为应保留。
- 本轮 producer 实测：两种模式均报告 `window_s=4.096`；真正参与加窗的数据只有 1000 点，即按 `N/fs` 口径为 **1.0s**。4096 点确实决定 bin 间隔，但不是 4.096s 的真实观测。
- 影响：新增“有效事实”把零填充长度包装成数据窗长，与此次“真实窗口、零填充不增加信息”的目标相悖。
- 处置：明确 `nfft_effective`、真实 `window_samples/window_s` 和 padding 的区别；复用现有 facts DTO 与 canonical 导出，不新增第二套可独立修改的事实模型。FFT/FFT-time 将 Δf 标签限定为“频率 bin 间隔”；Order/FRF 保留各自定义。
- 相关在途小修：工作区已将“Δf 由小值**降为**大值”改为“增至 … Hz”。这是已存在的文案修正，不能算本轮已修复，也不能代替上述事实修正。

### R4 · P2 · FFT-vs-Time 摘要增长撑宽窄 Inspector

- 引入变化：[contextual_fft_time.py](../../../mf4_analyzer/ui/inspector_sections/contextual_fft_time.py) L334–349，`e5ec1fa9` 新增“目标”文案；约束传播点：[collapsible.py](../../../mf4_analyzer/ui/inspector_sections/collapsible.py) L122–129，摘要采用不可收缩的 `QSizePolicy.Minimum`。
- 触发：288px Inspector，无数据 Auto 摘要，展开谱参数。独立进程复测 `test_db_reference_compound_row_precedes_axis_header_and_fits_within_320px` 失败。
- 本轮几何探针：摘要为 `自动(目标 4096) · hanning · 80%`，ctx 实际宽和 minimumSizeHint 均变成 **318px**，dB reference 控件右边到 **305px**，超出 288px 容器合同。
- 基线 `0253cdcc` 同一测试通过；`c84360f2` 在成组测试和单独进程中都失败。缩短摘要可降低 minimumSizeHint，表明 header 的不可收缩文本参与宽度传播；修改后仍须检查真实 Inspector 的其他最小尺寸贡献。
- 影响：窄侧栏出现控件出界或侧栏被迫变宽；如果显示更长的多源/降级摘要，风险更大。
- 处置：给摘要可收缩预算和优先级，必要时省略并提供完整说明；保留 Auto、目标/实际、blocked 等关键含义。不得通过把测试宽度改成 318px 或扩大应用侧栏来消除失败。

### R5 · P2 · 最近文件存在性缓存跨多次打开不刷新

- 引入提交：`a60da923`。
- 位置：[recent_open_popup.py](../../../mf4_analyzer/ui/widgets/recent_open_popup.py) L261–274、L474–482。
- 触发：第一次弹出时文件/挂载目录缺失，随后文件恢复，而 recent 的 path/kind/opened_at 未变化。`populate()` 只在记录集合变化时探测 exists。
- 本轮探针：missing→创建原路径文件→同 entries 再 populate/reset；磁盘 `exists=True`，projection 仍 `False`，`openable_rows=[]`。
- 影响：已恢复的记录在当前应用进程内持续灰显，无法用鼠标或 Enter 打开；反向删除也会保持过时的可用状态。加载层的竞态检查不能使灰显项目恢复可选。
- 处置：存在性快照的生命周期改为“一次打开会话”；每次真正打开做一次刷新，搜索和已打开弹层的纯 refilter 不做文件 I/O。仍保持最多 40 文件+10 项目、单实例和 640px 当前尺寸。

### R6 · P2 · AppMessageDialog 的可选 checkbox 始终隐藏

- 引入提交：`6b3105a5`。
- 位置：[message_dialog.py](../../../mf4_analyzer/ui_kit/message_dialog.py) L278–296。
- 触发：构造时传入非空 `checkbox_text`。父对话框尚未 show，子 checkbox 的 `isVisible()` 自然为 false；L295–296 将这个暂时的祖先不可见状态变成显式 `hide()`。
- 本轮 show 后探针：`parent_visible=True`、`checkbox_visible=False`、`checkbox_hidden=True`。
- 影响范围：新公共组件的已声明功能；当前已迁移的未保存项目提示不含 checkbox，因此不宣称现有保存/取消流程已因此损坏。
- 处置：按明确内容意图判断显示，不用 hidden parent 下的 `isVisible()` 推导永久状态；首帧测量中的标签/图标也按同一原则检查。推广新消息框前补齐此合同。

### R7 · P2 · 动效折叠箭头把 DPR 缩放应用了两次

- 引入提交：`c84360f2`。
- 位置：[collapsible.py](../../../mf4_analyzer/ui/inspector_sections/collapsible.py) L380–396。
- 触发：显式启用折叠动效，DPR>1，中间角度需要自绘 icon。pixmap 已 `setDevicePixelRatio(dpr)`，QPainter 使用逻辑坐标；代码又以物理 `side/2` 平移，并将 span 乘 DPR。
- 本轮实际 raster 探针，45°：DPR1 的非透明边界为 `[2,2,8,8]`；DPR2 的 24×24 图片只剩 `[16,16,23,23]` 右下角残片。DPR1.5 也已触及图片右/下边界。
- 影响：Retina/Windows 缩放下箭头在动画中偏移、放大、裁切，端点切回原生箭头时跳变。动效生产默认关闭，因此这是样板推广门禁，不是要求回滚整个最后提交。
- 处置：物理尺寸仅用于分配 pixmap，painter 全部使用 12px 逻辑坐标；验证中间帧而非只验 0°/90°。

### R8 · P2 · Auto-NFFT 合并没有同步完整的受影响 owner 回归

- 主要关联：`e5ec1fa9`。
- [test_inspector.py](../../../tests/ui/test_inspector.py) L6224 仍要求 `自动(128)`，而现合同正确输出 `自动(1024)`；L6885 仍要求普通 FFT tooltip 包含旧“最少帧数”策略。
- [test_main_window_smoke.py](../../../tests/ui/test_main_window_smoke.py) L3216、L3262 的两个缓存命中测试直接用原始 params 预种 key，缺少本次新增的 `nfft_facts_signature`；实际 compute 候选会 resolve 并加入签名，因此预种的是另一个 key。
- 上述四个用例在基线通过，在 `c84360f2` 失败。这是旧断言/旧生产者形状未迁移的证据，不能据此宣称生产缓存命中必然失败，也不能为迁就旧测试删除新的签名。
- 处置：按真实参数解析/完成结果预种缓存，保留“命中不 preflight、不提交、不重建时间轴”的行为断言；更新旧策略断言为当前规范矩阵。连同 R4 的真实布局失败，受影响 owner 全文件应重新变绿。

## 2. 范围、基线与总体判定

审查时间窗：北京时间 **2026-09-04 00:00 至 2026-09-06 00:00**，当前可见范围止于 9 月 5 日 13:37 的 `752adaaa`；收尾时增补了这笔新提交。分支 `main`。

- 基线：`0253cdcc25734631a5021bb9bbc9a60226a7cad0`。
- 主审查/四组定向测试快照：`c84360f2692ddbbca30f0badf77d4b6f5cff4db3`。
- 增补审查终点：`752adaaa208c49fa031180a1d397884b50d1ef68`；单独导出并运行受影响 owner，未重跑未变化的四组测试。
- 截至主快照共 **17 个提交、246 个文件、31,209 行新增 / 4,565 行删除**；增补后共 **18 个提交、249 个文件、31,313 行新增 / 4,567 行删除**。包含文档、测试和探针，不能把这些行数全解释成产品代码复杂度。
- 使用 `git archive` 按明确 SHA 导出两个终点和基线，测试运行在独立源码快照；解释器复用项目 `.venv/bin/python`。防止工作区已有修改或删除影响提交质量判定。
- 工作区预存内容包括 HDF 解析、FFT 短信号反馈、UltraView capture 修改、资源删除和根目录未跟踪文件。本 review 不把它们记为本批提交缺陷或本轮修复成果。

**总体结论：方向基本正确，核心计算/身份/架构边界有较好的自动化基础，但最终状态尚未达到“受影响回归全绿、有效事实可信、跨平台完成”的交付预期。建议保留设计方向，先做有限硬化，再补平台验收。**

本轮未发现需要立即撤回整批提交的证据，也未发现已证明的数据丢失或核心 Auto-NFFT 数值矩阵错误。这个结论限定于下述审查与验证范围，不表示所有 249 个文件都经过逐行形式证明。

### 各波提交的判断

| 波次 / commits | 本轮重点 | 判定 |
|---|---|---|
| 硬化 `56862a12` | Smart Layout fixed-point/预算保留、locks 持久化、旧布局链路退役、Custom-X 裁剪、View/命令/dirty guard | 方向合理；核心和接线 owner 大部通过。旧验收记录本身含变化中的脏树与平台 UNKNOWN，不能当最终提交全部已验收 |
| 发布 `68504a61` | v8.2.1 版本、帮助截图、Windows 源码合同 | 本轮 help/packaging/build-script checks 通过；未构建 Windows Full/Lite，因此仅确认源码层发布面 |
| 诚实反馈 `e77a39fc`、`47b88240`、`1576cda0`、`a9a2f562`、`0bc7cd54` | salience、preview/anomaly 区分、未知单位不猜推荐、时间轴 provenance | 基本接受，继续保留物理来源与渲染质量分离；没有理由撤回未知单位返回 None 或 provenance chip |
| facts 与跟进 `8eaea89b`、`e72606a3`、`6a9e5ddb`、`172896e9`、`c9438b58` | 居留事实、空卡隐藏、文案/计划 | 值得保留；R2/R3 表明展示事实仍缺绝对正确性检查 |
| 最近打开 `a3a9736e`、`a60da923` | store/search/popup/intents | 架构分层合适；R5 修复状态生命周期。采用当前 640px/46:54，历史 800px 原型不再作为重新设计目标 |
| Auto-NFFT `e5ec1fa9` | 两类 purpose、实际样本/低 Fs 约束、cache signature、manifest resume | resolver 与 Batch 合同较好；R4/R8 说明 UI 集成收口不足，R2/R3 应在共享事实 owner 补齐 |
| 窗口适配 `6b3105a5` | 几何 planner、Qt adapter、消息框与表单 owners | **需优先修 R1**；R6 在进一步迁移前补齐。不能称 Windows 布局问题已全部解决 |
| 动效样板 `c84360f2` | 默认关闭的 MotionPolicy、打断/终态、现有控件接入、demo/probe | 可保留为实验交付；R7 和原生动态门禁关闭前不推广。`8,148` 行新增包含大量 demo/probe/tests/docs，不支持仅凭体积重构或认定架构失控 |
| 增补最后提交 `752adaaa` | parented popup 首次 native handle、show 后重定位，复用共享 helper | 修复方向合理，影响面集中；R1 的标题栏外框偏移与 R5 的存在性缓存仍在。补齐真实 parented 首次/重开路径后再确认前台验收 |

### 已确认的优点与架构选择

1. `signal/adaptive.py` 保留 legacy `resolve_nfft/resolve_order_nfft`，新增 purpose-specific 决策，避免把 4096 全局强加给 Order/FRF。
2. 真实样本约束与 O(1) frame count 共享，FFT-time 的尾帧计数单独建模；本轮矩阵、边界和数值路径测试通过。
3. `batch_manifest.py:auto_nfft_policy_is_current` 根据 requested recipe 判断适用性，并拒绝缺失、bool 或不匹配版本；逐项与分组 resume 均调用该判断。
4. 最近打开的 store/matcher、popup、toolbar 和加载入口没有混成第二套文件加载器；没有必要为了最多 50 条记录引入索引服务。
5. 几何规划和内容布局有明确分工；R1 是 Qt adapter 的具体错误，修复 owner 即可，不需要第三套窗口管理框架。
6. 动效默认关闭、真实业务状态先确定的路线合理。`MotionPolicy/ValueDriver` 不拥有 MainWindow 数据；中立层导入和 MainWindow state ratchet 本轮通过。

## 3. 实际验证结果与证据等级

所有测试命令使用 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.` 和项目解释器。下表四组测试明确对应 `c84360f2`，是互不重叠的定向 gate；没有运行全套或整个 `tests/ui`。

| Gate | 覆盖范围 | 本次结果 |
|---|---|---|
| G-N | Auto resolver/FFT/spectrogram/order facts、parity、Batch manifest/runner/reporter、时间轴、Custom-X、Smart Layout | **1144 passed, 1 warning**, 157.59s |
| G-U | 最近打开、Inspector、折叠/开关/View、dirty guard、provenance、dense raster、几何/message/motion/segmented owners | **594 passed, 3 failed, 1 skipped**, 54.34s |
| G-B | backref/import/state/QSS/signal 棘轮、native/packaging imports、help、Windows build-script 源码 | **103 passed, 2 skipped**, 9.77s |
| G-I | project/analysis views、presets、绑定/reset、UltraView 集成、cursor/Custom-X、桌面命令、配置管理、Batch preview/弹层、MainWindow smoke | **382 passed, 3 failed**, 94.52s |
| 合计 | 上述定向 gate，不含基线对照和重复诊断 | **2223 passed, 6 failed, 3 skipped** |
| G-C | 生产几何 helper + 原生 Cocoa QDialog + 合成小工作区 | **FAIL**，实测外框多下移 32px，R1 |
| diff hygiene | `git diff --check 0253cdcc..c84360f2` | **PASS** |

新增 `752adaaa` 的结果单独记录：

- 定向 owner：`tests/ui/test_recent_open_popup.py`、`tests/ui/test_view_tabbar.py`、`tests/ui/test_batch_output_panel.py`、`tests/ui_kit/test_dialog_geometry.py`；**187 passed, 9.73s**；不与原快照数量相加。
- 原生 Cocoa R1 探针：**FAIL**，计划与实际外框仍相差 32px。该提交修复 native handle 未创建时 parented popup 的定位，不等同于修复带标题栏窗口的 frame/client 坐标。
- 新增 `test_first_show_at_clears_the_anchor_like_the_second_show` 使用 `_make_popup()` 的无 parent 实例；helper 测试有 parent，但只验创建 handle 后的 `.pos()`。还需真实 toolbar-parented popup 在 `show()` 后的外框及锚点回归，纳入 T4。
- `git diff --check 0253cdcc..752adaaa` 报 `tests/ui_kit/test_dialog_geometry.py:287: new blank line at EOF`，为低影响提交卫生问题，随该测试维护清理；原 `c84360f2` 检查仍为 PASS。

六个失败的分类：

- **本时间窗新增：** R4 一个真实布局失败；R8 四个测试合同未迁移。三个 Inspector 失败在 `c84360f2` 独立进程仍复现；基线同三例 `3 passed`。两个 cache 例在基线均通过。
- **基线已存在：** `tests/ui/test_ultraview_project_session.py::test_open_project_cancel_keeps_board`。在基线和 `c84360f2` 都因试图打开不存在的项目报 FileNotFoundError。该测试仍 mock `QMessageBox.question`，而当前取消 seam 是 `_prompt_unsaved_project/confirm_leave_unsaved_project`，且 suite fixture 默认 discard。应维护测试，不把它归咎于这两天的新提交，也不从此失败推导“用户取消会丢 Board”。
- **新增探针发现但上述 owner 测试未报警：** R1/R2/R3/R5/R6/R7。它们尤其说明绿测数量不能替代输入组合、真实 adapter 和中间帧验证。

本地原始证据位于 `.state/review-20260905/`：`numeric-gates.log`、`ui-gates.log`、`boundary-release-gates.log`、`integration-owner-gates.log`、`baseline-inspector.log`、`baseline-integration.log`、`head-inspector-isolated.log`、`probes.jsonl`、`facts-and-width.jsonl`、`cocoa-geometry.log`、`probe.py`、`latest-popup-gates.log`、`latest-cocoa-geometry.log` 和 `final-snapshot.json`。三个源码快照的 tracked blobs 均与各自 Git tree 一致，无运行期间源码漂移。这些是临时证据，默认不加入 Git；本文保留了独立重建失败用例所需的输入和输出。

**仍未验证：** 完整前台 TraceLab 操作矩阵；客户数据上的各分析模式；Cocoa 动效 S01–S07 与 M01/M02 原始测量；Windows 100%/150%、多屏和新鲜 Full/Lite frozen；稳定最终源码的两阶段全量 gate。单个 Cocoa 几何探针不关闭这些项目。

## 4. 更优方案：保留方向，减少补丁分叉

| 议题 | 建议 | 不采用其他方案的原因 |
|---|---|---|
| Auto-NFFT | 保留 segmented/FFT-time 两种目的、低 Fs guard、真实样本约束和当前上限；通过现有突发/扫频验收决定是否调整策略 | 强制所有模式 4096 或恢复统一 24 帧规则都会抹掉已明确的物理差异。仅凭曲线看起来更细不能选择窗长 |
| 有效事实 | 一个实际计算事实入口，GUI/Batch/canonical export 同源；真实 window 与 FFT length 分离 | GUI-only 避免 warning 或改标签无法修好 Batch/manifest。无需另建 AutoNfftFacts 或独立展示缓存 |
| 缓存 | 本轮保留意图签名使缓存失效的保守策略 | 数值缓存与展示 facts 分离可能提高复用，但新增生命周期和失效规则；无实测瓶颈前不扩大本次修复范围 |
| Inspector | 摘要可收缩，优先显示模式/实际值/不可计算状态，详细内容在 facts 或完整提示中 | 再加常驻行、减小全局字号或扩大侧栏会把局部问题转移给画布和整个 UI |
| 几何 | 纯 planner + 正确 Qt adapter + owner 内容滚动，使用实际 frame 验收 | 不逐对话框加 magic offset，不全局改 Qt/DPI/QSS，也不重新写框架 |
| 最近打开 | 每次打开一份磁盘状态快照，会话内纯内存搜索 | 永久缓存会过期；每次按键 stat 会阻塞输入。异步探测仅在网络盘实测证明必要时单独设计 |
| 动效 | 保持默认关闭，补 DPR/生命周期和真实 paint 测量，再逐组件决定推广 | 静态端点正确不代表中间帧正确；QML/Web 重写或全 ChartStack 淡化无当前证据支持 |
| 架构整理 | 仅在修复揭示明确 owner 冲突时移动实现 | `window.py` 或 probe 行数大不是自动重构依据；当前 neutral imports/state 棘轮通过，应优先消除可复现缺陷 |

可选后续性能调查：`_sync_fft_effective_facts` 会重复 fetch/范围筛选，`_effective_facts_health` 会扫描信号并遍历来源。这是源码可见的重复工作，**本轮没有测出性能收益或卡顿阈值**。若客户多源大数据场景确有延迟，再统计调用/分配并复用单次输入上下文；不要现在增加全局健康缓存。

## 5. 优化执行计划

### T0 · 对齐在途修改与复现清单

**Owner：** 实施负责人；范围为 named-path diff、本文状态及失败测试定位。无产品变更。

1. 记录执行时 HEAD、dirty scope，确认 R1–R8 是否仍存在；本文 SHA 是审查快照，不保证未来代码不变。
2. 对比已有 `_fft_mixin.py`、`_effective_facts.py` 短信号修改，保留原工作；HDF、capture、资源删除不并入本计划。
3. 将 R1–R7 的探针转成各 owner 的行为回归；先看到目标断言失败。R8 按当前规范迁移旧合同，不通过删测、改 fixture 全局默认或 xfail 消音。
4. 本阶段不跑全量基线。复用本次证据；只重跑发生漂移或开始修改的 owner。

退出条件：每个发现有“仍存在 / 已被在途修改解决并验证 / 需调整证据”的记录，没有误认未提交成果。

### T1 · 修共享窗口外框定位（R1）

**Owner 文件：** `mf4_analyzer/ui_kit/dialog_geometry.py`；`tests/ui_kit/test_dialog_geometry.py`。具体调用者仅在其独立失败需修时进入白名单。

- 红测覆盖 shown titled dialog 的真实非零 frame insets，以及 frameless、embedded、负坐标和撑满预算的窗口。
- 将 top-level 定位映射到 frame origin；embedded 使用局部坐标。首次隐藏窗口和 show 后校正共用同一约定。
- 连续应用相同计划不得漂移；用户已放大的窗口在仍合法时不恢复默认大小。native frame 未实现时用估计，show 后测量验证。
- **Focused：** `tests/ui_kit/test_dialog_geometry.py`、`tests/ui/test_drawer_screen_fit.py`、`tests/ui/test_tool_window_screen_fit.py`、`tests/ui/test_batch_preview_dialog.py`、`tests/ui/test_channel_config_manager.py`。
- **Boundary：** `tests/ui/test_import_boundaries.py`、`tests/ui_kit/test_qss_border_shorthand.py`；调用 owner 若未改则不扩大其余 suite。
- **Native：** Cocoa 复跑 R1，再验正常/紧凑区；Windows 100% 的真实标题栏、taskbar 工作区和多屏独立记录。

退出条件：规划矩形和真实 frame 都在安全区，嵌入控件没有错误使用全局坐标；不能只验 planner。

### T2 · 统一真实 FFT 事实（R2、R3及相邻文案）

**Owner 文件：** `mf4_analyzer/signal/fft.py`、`mf4_analyzer/batch_compute.py`、`mf4_analyzer/ui/main_window/_fft_mixin.py`、`mf4_analyzer/ui/inspector_sections/_effective_facts.py`；对应 signal、Batch parity/renderer、GUI owner 测试。需要导出额外字段时检查 `batch.py` 的 canonical 消费 seam，不在那里复制计算。

- 红测：Fixed 平均 N=63/64/129/3553，requested=4096；单帧/峰值 N=1000、requested=4096；正常未填充、显式奇数 FFT 长度、Auto whole-selection、Auto segmented。
- 计算 owner 明确实际 FFT 长度和真实加窗样本数，facts 不再使用数组长度推断奇偶。优先在现有 owner 中共享准确解析，保持 supported tuple/API；若需元数据扩展，使用兼容的可选结果信息并同步真实调用者。
- `df_hz=fs/actual_fft_length`；真实 `window_s=window_samples/fs`；零填充可见、不能暗示更多物理信息；无数据/非法 Fs 不生成假 facts。保持 short/empty/non-finite/dtype/shape 行为，禁止为了显示事实修改已接受的幅值算法或截断样本。
- 统一 GUI/Batch canonical shape 和事实语义，FRF/Order 只做不回归。将 FFT/FFT-time 的“频率分辨率 Δf”明确为 bin 间隔；保留当前已存在的“增至”修正。
- **Focused：** `tests/signal/test_fft_effective_facts.py`、`tests/signal/test_auto_nfft_compute_contract.py`、`tests/test_effective_facts_parity.py`、`tests/test_batch_runner.py`、`tests/test_batch_renderer.py`、`tests/ui/test_main_window_smoke.py` 中 FFT owner 用例。
- **Boundary：** `tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`；如改 Batch orchestration，再跑 `tests/test_batch_run_reporter.py`。
- **Artifact：** 用真实 Batch producer 导出短奇数和零填充案例，检查表格轴、实际图片标题/说明、manifest 的事实；不以两份手造 mapping 的相等当证明。

退出条件：R2/R3 数值与 UI/导出一致；新 Auto policy 矩阵和 Order/FRF 不变。

### T3 · 收敛 Inspector 窄宽度与旧回归（R4、R8）

**Owner 文件：** `mf4_analyzer/ui/inspector_sections/collapsible.py`、`contextual_fft.py`、`contextual_fft_time.py`；`tests/ui/test_inspector.py`、`tests/ui/test_main_window_smoke.py`。T2 事实字段定稿后执行。

- 在真实 288/320px Inspector 宿主下检查空态、Auto 目标、实际单值、多源范围、shortened、blocked。摘要有明确可收缩宽度和完整信息访问方式；必要值不静默丢失。
- 保留 dB reference 与坐标设置的顺序和 field cap；不改测试支持宽度。展开/收起和无 facts 隐藏行为保持。
- 两个旧策略断言以当前 spec 数值更新；两个 cache 用例通过真实 resolver 构造预种 key，断言同签名 hit、不同意图 miss、hit 不 preflight/submit/rebuild。
- 顺带维护基线已红的 `test_open_project_cancel_keeps_board`：只改该测试，在正确 seam 注入 cancel，断言项目读取未发生、Board identity/name 保留；不修改全局 discard fixture。
- **Focused：** 完整 `tests/ui/test_inspector.py`、完整 `tests/ui/test_main_window_smoke.py`，以及上述 UltraView 单例；T3 改 shared collapsible 时加 `tests/ui/test_collapsible_motion.py`。
- **Boundary：** `tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_qsettings_isolation.py`。
- **Visual：** 生产 QSS 下测控件外接矩形，Cocoa 前台侧栏缩放；如只做省略，检查完整含义仍可读取。

退出条件：本次六个现有失败均得到正确解释与修正，窄布局没有靠删断言或扩大宽度过关。

### T4 · 最近记录按打开会话刷新存在性（R5）

**Owner 文件：** `mf4_analyzer/ui/widgets/recent_open_popup.py`、`mf4_analyzer/ui/toolbar.py`（仅刷新接线若需要）；`tests/ui/test_recent_open_popup.py`、`tests/ui/test_toolbar.py`。

- 在 `752adaaa` 的既有定位修复上补 toolbar-parented popup 的首次 show/重开外框及 anchor 避让回归，保留 native handle 和 show 后重定位；不误把无 parent 用例当完整生产路径证据。
- 红测 missing→restore 和 exists→delete，保持 MRU payload 完全相同，真正关闭/重开弹层。
- 首次/每次 show 只做一轮 exists；连续搜索、Up/Down、再次聚焦和动效帧不触发 exists/QSettings。show 生命周期由现有 toolbar/popup owner 管理，不新增 MainWindow mutable state。
- 缺失项跳过、打开一次、Esc 两阶段、clear 保持弹层、竞态加载复核继续成立。
- **Focused：** 上述两个 owner 文件和 `tests/ui/test_recent_files_store.py`；**Boundary：** `tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`。
- **Native：** Cocoa 重开恢复文件、首击定位/焦点、外点关闭；Windows 独立验。

退出条件：每次打开显示当前磁盘状态，会话内搜索仍为纯内存；保留 640×700 上限和当前 46/54 列比。

### T5 · 补消息框可选状态合同（R6）

**Owner 文件：** `mf4_analyzer/ui_kit/message_dialog.py`、`tests/ui_kit/test_message_dialog.py`。依赖 T1。

- checkbox 有/无文案、checked/unchecked、父先隐藏后显示、重复打开、长文案/紧凑区均验证。
- 以明确意图/显式 hidden 状态测布局，避免 `isVisible()` 混入父未显示状态。结果提交仍只有一个 owner。
- **Focused：** `tests/ui_kit/test_message_dialog.py`、`tests/ui/test_project_dirty_guard.py`；**Boundary：** `tests/ui/test_import_boundaries.py`。
- Verify 保存/取消/标题栏关闭、非关闭 Action、禁用默认按钮；在动作区内可操作 checkbox，返回状态正确。

退出条件：组件声明的可选能力真实可用。该任务不扩展既有 QMessageBox 迁移；原计划的 Cocoa/Windows 示范门禁通过后，另按已批准范围推进迁移。

### T6 · 修动效 DPI 并保持实验边界（R7）

**Owner 文件：** `mf4_analyzer/ui/inspector_sections/collapsible.py`、`tests/ui/test_collapsible_motion.py`；验收记录按需更新。与 T3 同文件，**T3 后串行执行**。

- pixmap 分配乘 DPR，painter 坐标保持逻辑尺寸；测 DPR=1/1.5/2 和角度 0/22.5/45/67.5/90 的 alpha bounds、中心和裁切。
- 推进真实 animation clock 检查中间帧；快速反转、隐藏、禁用、deleteLater、body 替换后终态与焦点仍正确。不得仅 assert `_arrow_degrees`。
- **Focused：** `tests/ui/test_collapsible_motion.py`、`tests/ui_kit/test_motion.py`、`tests/ui/test_motion_demo.py`，以及 T3 的窄 Inspector 用例；**Boundary：** QSS、无 lambda 和 import 边界。
- **Native：** 按既有 [motion Spec](../specs/2026-09-05-native-interaction-motion-pilot-spec.md) 检查 Cocoa/Windows 100%/150% 动态画面；默认关闭不得更改。

退出条件：中间帧正确且不影响默认路径。M01/M02 性能数字必须来自真实暴露和 paint；不能拿 offscreen 速度推荐全局动效。

### T7 · 稳定集成与平台收口

**Owner：** 同一个实施负责人。依赖 T1–T6；不分派并行 full gates。

1. 每项通过 owner/boundary 后即停止重复验证。集成阶段仅补共享文件和跨 producer→consumer 的必要交叉 gate。
2. 为这一波跨数值事实、UI geometry 和共享组件的**稳定集成里程碑**跑一次全量。启动前检查已有 pytest 进程及 cwd，记录 HEAD 与 dirty-file fingerprint；前后源码必须一致。
3. 两个新鲜进程严格顺序：先 `pytest -q --ignore=tests/acquisition_ui` 完成，再 `pytest -q tests/acquisition_ui`；采用项目 runtime/临时 cache。中断、崩溃或运行中源码改变记 UNVERIFIED。若基线旧失败仍在，单独记录，不能宣称全绿。
4. Cocoa 前台矩阵：窄 Inspector；最近打开首击/重开/Esc/外点；未保存项目 Save/Discard/Cancel；正常和紧凑窗口；Auto-NFFT M1/M7、突发/扫频的实际窗长/时间定位；View controls/overflow 和 cursor pill 基本回归。
5. Windows 原生 100% 必验、150%/多屏和 taskbar 工作区；随后同一稳定源码构建 Full/Lite 验证。缺环境时保持 UNVERIFIED，并将本轮定位为“本地硬化完成、跨平台未验收”，不宣称 release-ready。
6. 在新验证记录中关联准确 SHA 与场景结果；历史 plan/spec 的历史基线保持原样，可追加明确的实施状态链接，不能把原来未执行的 checklist 全部自动打勾。
7. 本批不默认 bump 版本、发布、push 或批量合并。若后续明确准备发行，再按 app_meta/help/launcher/build/tests 版本契约独立收口。

## 6. 最终质量门槛与成本控制

| 层级 | 达标条件 | 本轮 review 时 |
|---|---|---|
| 生产正确性 | R1–R5 关闭；实际数据事实与 GUI/导出一致 | 未达到 |
| 组件与样板完整性 | R6/R7 关闭；仍默认关闭动效 | 未达到 |
| 自动化交付 | R8 的四个旧合同、窄布局及基线取消用例有正确测试；稳定 integration gate 有结论 | 未达到；当前定向 2223/6/3 |
| 跨平台完成 | Cocoa 前台、Windows 原生与 Full/Lite 的适用门禁均有准确快照证据 | UNVERIFIED；Cocoa 几何探针已明确 FAIL |
| 架构收益 | 修复落在现有 owner；无新 UI→DSP 反向依赖、无平行 facts/cache/state owner | 当前基础较好，继续保持 |

优先级顺序为 **T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7**。先解决普遍窗口定位和事实可信度，再处理入口生命周期与实验组件。无需为此启动全仓分解、换 Qt 技术栈或重写分析管线。

本轮文档检查只需核对发现/任务映射、路径、证据和 `git diff --check`；产品测试是 review 取证，不是文档编辑引入的运行时要求。已有 lessons 已覆盖实际 frame/DPR、producer-shaped facts、QSettings 隔离和审查基线问题，不新增重复 lesson。

## 7. 实施状态（2026-09-05）

HEAD 仍为 `752adaaa`。产品修复落在既有 owner，未 bump 版本、未 push。Cocoa/Windows 原生与 Full/Lite 仍为 **UNVERIFIED**。

| Task | Offscreen 结论 |
|---|---|
| T1 R1 | `apply_plan` 顶层窗口按 `plan.frame` 原点 `move`；focused + T1 boundary 绿 |
| T2 R2/R3 | facts 使用计算 owner 的实际 NFFT；`window_s` 按真实加窗样本；FFT/FFT-time 标签为「频率 bin 间隔 Δf」 |
| T3 R4/R8 | 摘要可收缩省略；Inspector/smoke 全文件绿；取消打开项目走 `confirm_leave_unsaved_project` |
| T4 R5 | 存在性按打开会话刷新；toolbar 点击前走 `reset_for_show` |
| T5 R6 | checkbox 按文案意图 / `isHidden()`，不再用未 show 父级的 `isVisible()` |
| T6 R7 | 箭头 pixmap 按 DPR 分配，painter 用 12px 逻辑坐标；动效默认仍关闭 |
| T7 | 主体 `9885 passed / 19 failed / 25 skipped / 10 errors / 3 deselected`（36:33）；`tests/acquisition_ui` 随后 `359 passed`（9.1s）。源码指纹在主体跑前跑后一致 |

T7 红/错分类（不并入本计划、不宣称全绿）：

- 10 个 ERROR：工作区删除了 `assets/wwt/winwert_export_template.wwt`（计划外）
- 分析时间轴在途：`analysis_time_fs` 缓存字段、skip 文案、「时间轴无效」、`_fft_fetch_signal(..., params=)`、hints 超宽、rebuild popover 锚点
- 本批审查窗已有/测试合同未迁：`nfft_facts_signature` 缓存绑定；QSS 棘轮（hex 250>211、facts 卡 f-string objectName、`viewOverflowCloseAll` 重复选择器）；chart toolbar `ToolbarScrollHost`；split cursor pill
- BatchSheet `1080x760` / FRF pair 窄宽：`showEvent` 的 `nudge_into_work_area` 在 offscreen 约 800px 工作区把用户 `resize(1080)` 收进安全区。这是安全区合同，不是把测试改成接受越界宽度；T1 owner 测试已绿

在途 FFT 短信号反馈已整合；HDF、UltraView capture、资源删除未并入。
