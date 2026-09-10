# 最近两天 UI 与操作逻辑提交 Review

日期：2026-09-10。结论：**needs revision**。局部渲染、几何与导入修复已有有效证据；时间范围和预设状态链仍有功能缺口，尚不满足整体完成条件。

本次只做 review、诊断探针和优化文档，没有修改产品代码、提交或推送。

配套文档：[优化 Spec](../specs/2026-09-10-ui-interaction-hardening-spec.md)、[执行 Plan](../plans/2026-09-10-ui-interaction-hardening-plan.md)。Finding ID、需求 ID 和任务 ID 在三份文档中对应。

## 1. 严重度排序的发现

以下代码行号全部以 `29ab049c5932a5fb17b4478cb8fa8b0fb3cd6043` 为准。当前工作区有未提交改动，特别是 `presets.py`，不能拿当前行号替代提交行号。

### F01 · P1 · 非法时间输入可能被接受，或静默变成全时段

**来源**：`29ab049c`；已复现。

**位置**：`mf4_analyzer/ui/inspector_sections/persistent_top.py:597–614`；`mf4_analyzer/ui/main_window/_analysis_mixin.py:1122–1145,1161–1169,1399–1423`。

三个入口使用不同的“有效”定义：

1. 输入框文本为 Qt intermediate 状态 `-` 时，`flush_pending_range_edit()` 先执行 `interpretText()`，输入回到旧数值，计算前检查随后返回允许。用户输入的非法文本没有成为可解释的阻断条件。
2. 来源为 0–10 s，用户填写 8→2 s 后勾选启用，`_enable_focused_analysis_time_range()` 跳过非法草稿并采用来源全范围，最终 `pane.time_range == (0, 10)`。
3. 同一来源填写 20–30 s，草稿通过排序/有限值检查，被列为可选局部范围；选择局部后 preflight 返回 True。`enabled_covers_sources()` 用于已启用范围检查，却没有用于草稿提交。

**影响**：用户以为使用了自己的输入，实际可能使用旧值/全时段，或者将无法覆盖当前来源的区间交给后续分析。并不据此断言所有后续 worker 都会算错；确认的是提交边界没有保证其承诺。

**根因**：输入文本有效、数值区间有效、当前目标来源可计算是三个条件，现有接线把它们部分合并了。确认分支又在逐 pane 修改后才检查下一项，缺少统一的预验证事务。

**更优解**：在现有时间范围 controller 中定义同一验证结果；先保留并验证原始输入，再校验当前来源覆盖，最后一次提交全部目标 pane。非法输入不能自动解释为“全部”。见 R01/R02、T1/T2。

### F02 · P1 · 没有编辑，捕获 View 也会降低启用范围的精度

**来源**：`29ab049c`；已复现。

**位置**：`mf4_analyzer/ui/main_window/_analysis_mixin.py:1425–1450`，尤其 `top.range_values()` 回写 `pane.time_range`。

来源末点为 `10.00049` s。勾选来源全范围时，模型保存 `(0, 10.00049)`；未发生任何编辑，仅调用 View 捕获，值变成 `(0, 10.0)`。显示精度被写回计算区间。

**影响**：切换/保存时参数可能悄悄改变；按精确上界截取的后续计算可能丢掉末尾样本。当前探针证明模型精度变化，未以所有 DSP 输出变化作为已完成证据。

**根因**：虽然新增了用户编辑事件，旧的“控件值是保存真相”路径仍保留。程序投影与用户提交尚未真正分开。

**更优解**：capture 只 flush 尚未提交的真实编辑；无编辑时直接保留模型原值，不能通过多增加显示小数位修复。见 R03、T1。

### F03 · P1 · 只改变预设基准时，项目离开保护看不到未保存变化

**来源**：`0161fbe0` 新增持久化基准与既有 dirty guard 的接缝；已复现。

**位置**：`mf4_analyzer/ui/inspector_sections/presets.py:832–842`；`mf4_analyzer/ui/analysis_view_bridge.py:42–46`；`mf4_analyzer/ui/main_window/_analysis_mixin.py:554–588`；`mf4_analyzer/ui/main_window/_project_io_mixin.py:134–158`。

复现：加载预设 1→保存项目→把相同参数写入自定义槽 4→加载槽 4。控件基准已是 slot 4，但 `_project_session_is_dirty()` 仍为 False。

**影响**：用户改变了应该随 View 保存的预设来源，却可能直接关闭而不获保存提示；再次打开仍是旧基准。若显式保存或切 View，bridge 可以捕获基准，这不等于离开保护已接通。

**根因**：基准提交仅发生在 PresetBar 内部；现有参数变化回调只同步 `state.params`。参数相同的基准切换不会产生参数差异事件；离开检查的只读实时快照覆盖 Time View，不覆盖该分析基准。

**更优解**：成功的预设事务产生明确的提交事件，现有 analysis owner 立即同步完整 params 与 baseline，再标记一次用户变更。不能靠假参数变化触发 dirty，也不能等保存时补抓。见 R07、T4。

### F08 · P1（验证门禁）· ZFD 新测试依赖未跟踪的本机取证目录

**来源**：`ec4b9a5b`；干净提交快照中已复现。

**位置**：`tests/test_zfd_format.py:29,333–359`。

`test_zfd_a4_real_samples_match_step0_profile` 无条件读取 `.state/zfd-robustness/samples.json`，缺失直接 fail。此文件及所需真实样本并不随提交快照提供。正常新 checkout 无法重现该测试的绿色状态。

补充六个本机样本及 manifest 后，该测试通过（1 passed）；这说明本机样本 gate 可跑通，**没有消除测试供应链缺口**。该测试主要检查数量、时间、通道和单位，不足以单独证明全部数值样本零回归。

**更优解**：把可再分发的小型合成 fixture 留在仓库；真实样本由明确的 corpus job/参数提供，用受控 manifest 和文件摘要校验。普通套件无 corpus 时明确跳过可选真实样本；必需 corpus 的 job 缺样本必须失败。不得把强制本机依赖简单改成无条件 skip。见 R10、T7。

### F04 · P2 · 保留手动坐标后，比较基准也被改成了保留值

**来源**：`0161fbe0`；已复现；旧 spec 自身也有歧义。

**位置**：`mf4_analyzer/ui/inspector_sections/presets.py:819–842`；旧 [预设 Spec](../specs/2026-09-09-preset-baseline-and-axis-preservation-spec.md) §4.1、§5.2、§10、A4/A7。

手动 X=1–5，加载内置预设并选择保留坐标，手动轴确实保住了，但 `_commit_loaded_slot()` 将合并后的当前值采为基准，`axes_differ` 为 False。与目标预设不同的坐标没有黄点，后续当前槽重应用也可能被判为无操作。

**根因**：目标预设意图与最终应用结果共用一个 snapshot。旧 spec 一处规定应用后实测快照，另一处又要求保留轴后与目标快照比较，两个表述需要先统一。

**更优解**：保留一个完整的、按现有参数语义解析后的“目标基准”，另有合并保留坐标后的实际结果。内置补丁未拥有的字段继承原值；补丁拥有但用户保留的轴仍相对目标产生差异。不通过临时应用两次来得到目标。见 R05、T3。

### F05 · P2 · 恢复 View 后，同名预设槽更新失去可检测性

**来源**：`0161fbe0`；已复现。

**位置**：`mf4_analyzer/ui/inspector_sections/presets.py:762–774`。

加载槽后保留旧 baseline，保持名称不变重写槽内 window；恢复旧 baseline 前 `_slot_source_changed()` 为 True，调用 bridge 使用的 `set_baseline(old)` 后变成 False。

**根因**：恢复时从当前全局槽读取 payload，当作当初加载的 payload。持久化了比较参数，却没有持久化加载来源的版本证据。

**影响**：“槽位已更新”提示消失，再点击同槽可能 no-op，用户不能按预期加载新内容。

**更优解**：在嵌套基准 schema 中保存加载时 source payload；当前槽只用于比较。旧版本没有此证据时标记未知，不能以当前槽反填历史。见 R06、T3。

### F06 · P2 · 时间范围用户事件没有完成状态提示投影

**来源**：`29ab049c`；已复现。

**位置**：`mf4_analyzer/ui/main_window/window.py:2304–2312`；`_analysis_mixin.py:1322–1369`。

真实范围编辑信号提交 2–4 s 后，控制器已有 draft，但 `range_intent_status_text()` 仍为空。`_on_user_range_committed()` 丢弃返回 intent，没有更新状态提示。`_project_top_from_time_range_intent()` 另只投影 kind，没有使用 `needs_review/errors/notes` 的完整语义。

**影响**：新增加的“范围已调整，尚未启用”说明在关键用户路径缺席。单独调用标签 helper 的绿测无法证明实际交互接线。

**更优解**：用户编辑、勾选、来源变化、View 恢复和 compute choice 每次状态落定后，通过同一个 projection 更新提示与操作可用性；程序投影保持静默。见 R04、T1/T2。

### F07 · P2 · 来源签名不足以识别时间轴修订

**来源**：`29ab049c`；已复现签名缺口，具体客户触发频率未知。

**位置**：`mf4_analyzer/ui/main_window/_analysis_mixin.py:1261–1278`；`mf4_analyzer/ui/main_window/analysis_time_range.py:140–182`。

保持 fid、通道、首尾时间和点数不变，只替换时间轴并改变内部一点，签名不变。现有 `FileData.rebuild_time_axis()` 也是实际时间轴写入边界，见 `mf4_analyzer/io/file_data.py:283–307`。

**根因**：轴摘要 `(t0,t1,n)` 被当成修订身份。它能检测范围和点数变化，不能证明仍是同一数据版本。

**更优解**：签名使用运行期来源实例/时间轴修订令牌；已有写入 owner 负责更新。来源排序保持无关，FRF 输入输出角色保持有向；不在每次输入时哈希整个大数组。见 R04、T2。

### F09 · P2 · Batch 分组卡图片数使用了错误的笛卡尔积假设

**来源**：横展确认的历史问题；`formula_text` 的乘法可追溯至 `85054ceb0`（2026-08-02），不是本轮新引入。

**位置**：`mf4_analyzer/ui/drawers/batch/method_buttons.py:288–295`；`sheet.py:1113–1115`。

两个逻辑来源分别有 A/B、A/C，选择 B/C 并采用 available-per-source，dry-run 规划只有 2 个有效输出；卡片显示 `2 × 2 → 4 张`。

**根因**：展示层按来源和信号数量重新推算规划结果，忽略逻辑来源的稀疏通道集合。Run preview 已有正确事实，卡片没有接到它。

**更优解**：卡片投影同一次中性 planner 的有效配对/分组数；unknown/pending 时显示待确定。FRF 按有效输入输出对计数，不套普通信号公式。见 R08、T5。

### F10 · P2 · 禁用反馈修复没有覆盖自绘卡片

**来源**：`8ff5c632` 的横展遗漏；`SegmentedChoice` 本身已修复。

**位置**：`mf4_analyzer/ui/drawers/batch/analysis_panel.py:81–105`；`method_buttons.py:470–514`。

`_PresetCard` 的标题颜色只看 checked，不看 effective enabled。禁用且选中时，offscreen 探针仍找到 92 个正常蓝色像素；新的 Cocoa 探针找到 258 个。`_GroupingCard` 的圆点、标题和公式也有同类硬编码绘制路径，尚未逐项做 Cocoa 像素验收。

**影响**：按钮行为虽被锁住，外观仍像可操作。祖先禁用、子控件自绘、恢复业务适用性之间没有完整契约。

**更优解**：使用共享控件颜色和 effective enabled 计算标题/选中/禁用绘制；保留 checked 和用户值。按业务适用性与运行锁分别恢复，不能 indiscriminately `setEnabled(True)`。见 R09、T6。

### F11 · P2 · Batch 默认方法、历史文档和测试前提未同步

**来源**：本轮 method-first 修改后的契约漂移。

**位置**：`mf4_analyzer/ui/drawers/batch/sheet.py:570`；[method-first Plan](../plans/2026-09-09-batch-method-first-guidance-plan.md) §1；`tests/ui/test_batch_smoke.py`、`test_batch_review_regressions.py`。

Sheet 当前默认 time，旧 plan 仍描述保留 FFT 默认；六个失败断言依赖 FFT，其中五个旧 smoke 在显式选择 FFT 的诊断包装下全部通过。第六个 lock case 的失败是预期 fft、实际 time，不能据此说运行锁失效。

**判断**：这是默认值及测试场景前提未统一的确定问题；现有证据不足以断言“默认 time 未获授权”。不应为了绿测擅自改回 FFT。

**更优解**：本轮优化建议保留当前 time 默认；需要 FFT 的场景自行选择方法，独立测试默认值和真正的锁定不变性。旧设计保留历史，新 spec 明示决策。见 R11、T5。

## 2. 对用户五项问题的直接回答

| 问题 | 判断 | 依据 |
| --- | --- | --- |
| 执行是否到位 | **partial** | 新 helper/controller 和大量局部测试到位，F01–F08 表明用户事件→模型→保存/计算/提示链没有全部闭合。 |
| 是否分析到根因，有更优解 | **部分到根因** | 轴标签固定 gutter、Cocoa palette、hover 翻转、首显布局都指向实际 owner；时间范围仍保留旧 capture 回写，预设把目标与结果混用。优先补已有 owner 的边界，不再堆入口补丁。 |
| 根因能否横展 | **能，已有复现** | 投影当意图：F02/F06；新持久化状态未入 dirty：F03；不完整身份：F05/F07；展示重新推算：F09；只修标准控件、漏自绘：F10。相同风格不能证明所有代码或作者都有问题。 |
| 接线是否到位 | **未全部到位** | range status 丢返回值、preset baseline 无立即同步事件、grouping 没接 planner、draft 验证没接 coverage。 |
| 其他方面 | **验证可信度需要收口** | F08 是干净 checkout gate 缺陷；默认方法漂移影响回归意义；Cocoa 与 offscreen 结论必须分开，真实客户长 ZFD 和 Windows frozen 验收仍未知。 |

共同改进方式是明确一次状态提交的 owner、输入来源、最终事实及消费者。没有证据支持重写 MainWindow、引入新全局状态框架或把所有控件拆解重做。

## 3. 审查范围及逐提交覆盖

窗口取 `2026-09-08 00:00:00 +0800` 至本次 HEAD，兼顾“最近两天”的自然日理解；实际最早提交是 09-09，09-08 无提交。共 14 条，含 1 条 merge；13 条非 merge。审查了 11 份直接相关的原 spec/plan 全文，并核对实现、消费者和测试。

| 提交 | 内容 | 当前判断 |
| --- | --- | --- |
| `29ab049c` | 分析时间范围意图 | needs revision：F01/F02/F06/F07；新 controller 方向正确，入口/回写未收口。 |
| `404be139` | 坐标轴 gutter 与边缘标签 | 已检查 owner、共享 helper、导出路径；本次相关测试通过。完整前台跨缩放验收未做。 |
| `0dc7a75f` | Batch 首显 geometry settlement | 聚焦首显测试通过；先前 Cocoa 5 方法×3 尺寸取证仅作为历史支持，不替代当前全矩阵。 |
| `8ff5c632` | 不适用控件禁用、保值 | 标准 segmented/output 路径测试通过；自绘横展 F10。 |
| `ec4b9a5b` | ZFD 长记录和声明时间轴 | 合成和现有加载边界通过；F08；原始长客户文件缺失，支持 profile 外不承诺。 |
| `0161fbe0` | 预设基准、差异和保留坐标 | needs revision：F03/F04/F05；兼容比较与轴归一化已有基础。 |
| `f705ead9` | Batch 引导、最近文件、紧凑布局 | 已查 intake/source 行、引导与阶段反馈；现有聚焦测试通过；额外异步来源矩阵见 §7。 |
| `168e2574` | hover 避开触发行 | 聚焦几何测试通过；未发现确定回归。 |
| `ad2765f5` | 屏幕边缘 hover 闪烁 | 先水平夹取再翻转的根因处理合理；聚焦测试通过。 |
| `8ca2e8f3` | 合并远端与 method-first | 检查 first-parent 实际差异，包含日期过滤未直接列出的通道导出列表 palette/QSS 修复；补跑 export 测试通过。 |
| `b748e449` | method-first、运行态控制、8.2.3 | 已查方法挂载、run lock、help/build 表面；F11。F09 属继承的旧计数问题。 |
| `04f2a1c0` | 删除两张旧截图 | 文档/资源范围；无运行逻辑改变。 |
| `a6eb86ac` | 工作约定、UI 原型 | 仅文档与原型，不能作为产品效果验收。 |
| `ae3a2821` | method-first 设计 plan | 已按实际实现反查；历史默认表述与实现分叉，见 F11。 |

五组原设计覆盖：时间范围、预设基准、控件适用性、坐标轴标签、ZFD；另读 method-first plan。原文中“尚未实现/待验收”不自动等同于当前仍未实现；也不改写旧文件伪造历史完成状态。

## 4. 接线矩阵

| 入口 | 现有主路径 | 结果 | 后续验收重点 |
| --- | --- | --- | --- |
| 手动范围编辑 | PersistentTop → window → time-range controller | 状态有更新，提示缺投影；非法文本可能先回退 | 真实键盘/失焦/Compute 顺序与任务提交次数。 |
| 范围启用 checkbox | `_enable_focused_analysis_time_range` → PaneState | 非法草稿可变 full | 分离无草稿与非法草稿；拒绝静默 fallback。 |
| 切 View / 保存范围 | capture → spin → PaneState | 无编辑仍损精度 | 投影不产生提交；精确 tuple 不变。 |
| 局部范围计算确认 | conflicts → choice → pane writes → worker | draft 缺 coverage；提交非全目标预验证 | 全部目标先验证，cancel 零写入、零任务。 |
| 预设加载 | prepare → apply → baseline → parameter callbacks | params 路径已有；baseline-only dirty 缺失 | 提交后完整 View 状态一次同步。 |
| View 恢复基准 | persisted baseline → set_baseline → 当前槽 | 历史 source payload 被当前槽覆盖 | 源版本未知与已更新必须可区分。 |
| Batch 预览/运行数量 | 中性 planner → preview/run | 正确路径已有 | 让卡片复用结果；FRF/稀疏逻辑源同事实。 |
| Batch 禁用/恢复 | applicability + ancestor run lock → widget | 标准控件较完整；自绘 active ink 遗留 | 直接禁用、祖先禁用、取消/失败/成功解锁。 |
| 轴标签与 Batch 导出 | 中性 metrics → GUI/Qt renderer | 当前边界/渲染 tests 通过 | Cocoa 重绘后字形像素、导出 artifact；不得只看 width。 |
| ZFD 到 FileData/Batch | parser → metadata → source adapters | 当前支持 profile 合成/本机样本通过 | 独立 corpus gate、客户长样本、数值而非仅 parity。 |

## 5. 本次验证结果与解释

### 5.1 快照与隔离

运行于 `git archive HEAD` 建立的 `.state/review-20260910/snapshot/`，使用项目 `.venv`，没有混入用户工作区的未提交修复。测试后逐 blob 检查 **2634 个跟踪文件，0 个与 HEAD 不符**，记录见 `.state/review-20260910/snapshot-audit.json`。

常规命令前缀：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest`。命令 cwd 为上述 snapshot；Qt 设置使用项目测试隔离 fixture。

### 5.2 当前提交的现有测试

| 组 | 实际结果 | 解释 |
| --- | --- | --- |
| UI focused，18 个文件 | **482 passed, 8 failed, 99 warnings，45.71 s** | 六项默认 FFT 前提漂移；一项窄列标题预算；一项 offscreen 屏幕夹取与 1080 预期冲突。 |
| Renderer/IO/版本帮助，14 个文件 | **368 passed, 1 failed, 3 skipped, 2 warnings，7.68 s** | 唯一失败为 F08 的本机 manifest 依赖；没有把缺数据算作 parser 错误。 |
| 架构、轴布局与隔离，14 个文件 | **80 passed, 1 skipped，11.53 s** | import、backref、state ownership、lambda、QSS、QSettings、conftest 与共享轴边界。 |
| 合并带入修改及生命周期，3 个文件 | **72 passed, 70 warnings，10.71 s** | channel export、batch toolbar、project dirty guard 现有场景。F03 的新场景不在其中。 |
| 补供六个本机样本后的 ZFD A4 | **1 passed，0.26 s** | 单独跑该 case；属于有 corpus 的额外验证，不改变干净 checkout 失败结论。 |

上述不是全套测试，未执行 main/acquisition 全量门禁。`DeprecationWarning` 主要来自 pyqtgraph/NumPy；本次未据此启动无关依赖升级。

### 5.3 独立诊断探针

只在临时快照中新增 `.state/review-20260910/snapshot/tests/ui/test_review_20260910_gaps.py`，以真实 owner/helper 构造所述边界，按期望正确行为断言：

- 八项初始探针均红：保留轴差异、槽位重写恢复、真实编辑提示、非法草稿勾选、越界草稿提交、intermediate 文本、同首尾轴修订、无编辑精度。
- 横展补充三项均红：稀疏来源卡片数、禁用卡片像素、baseline-only dirty。
- 五个旧 smoke 加入显式 FFT 前提后通过，用于归因；这是诊断包装，尚未修正仓库测试。

其中“目标基准应保留”的断言依据旧 spec 的 A4/A7，而不是所有旧文字已无歧义；新 spec 已统一该选择。探针不代替用户完整前台操作，也没有被加入产品提交。

### 5.4 新 Cocoa 检查

首次受限进程在创建 QApplication 时退出 134，未执行产品断言，记录为环境启动失败，不是产品崩溃结论。允许图形会话访问后，使用同一隔离 snapshot 重试三项：**2 passed, 1 failed，1.50 s**。

- 窄列预设标题检查通过；offscreen 中的 61<62 px 不能直接作为 Cocoa 界面裁切结论。
- 1080×760 Batch 窗口检查通过；offscreen 780 px 来自小屏幕夹取前提，不应删掉生产屏幕保护来修测试。
- 禁用预设卡正常蓝色像素检查失败，确认 F10；258 个精确 active-blue 像素。

这是独立的真实 Cocoa 控件测试。未操作用户正在使用的 TraceLab 会话；不是全应用前台五方法 walkthrough，也不是 Windows native/frozen 证据。

日志在 `.state/review-20260910/`：`focused-ui.log`、`focused-render-io.log`、`boundaries.log`、`focused-lifecycle-merge.log`、`gap-probes.log`、`horizontal-probes.log`、`followup-probes.log`、`zfd-local-samples.log`、`cocoa-controls.log`、`cocoa-controls-retry.log`。这些是本机取证，不能成为新测试必须读取的 fixture。

## 6. 已认可的根因处理与不建议的改法

1. **轴 gutter**：按最终 tick 文本需求统一宽度再 retick，比释放宽度后立刻读旧 `axis.width()` 更合理。ColorBar 有显式重测路径。维持中性 metrics owner，不把逻辑复制进 facade。
2. **hover 边缘**：先夹取水平位置再判断翻转、按触发整行避让，处理的是布局/触发链。没有证据需要换掉整个 hover 系统。
3. **Batch 首显**：先 settle 内部 LayoutRequest，再应用 scroll policy，定位到首显路径。当前无必要把它扩成全局反复 `processEvents()`。
4. **通道导出列表**：Cocoa selected text 的 palette 与 viewport 同步处理，超越仅调 QSS 的局限；本次对应测试通过。
5. **ZFD**：记录长度、边界与声明时间基准检查是有效改进；支持的是明确 profile，不能扩写成所有 ZFD 变体均支持。
6. **不建议**：通过更多 decimals 掩盖 F02、所有信号都接 paramsChanged 掩盖 F03/F06、卡片另算一套规划修 F09、扩大固定高度/缩小字体掩盖不同 QPA 的测试前提。

## 7. 尚未证实的问题与有边界的横展任务

以下不计入已确认缺陷数量；plan 必须先取证再决定是否改：

| 项目 | 当前证据与限制 | 允许的下一步 |
| --- | --- | --- |
| 引导把程序变化当用户配置 | `sheet.py:598–609` 的通用 changed 信号接 `_on_user_configuration`；异步 source/schema 更新是否走到它，尚无失败复现 | 覆盖 probe 成功/失败、导入 preset、恢复 preferences 的真实回调，验证首次引导与用户操作 origin。 |
| 单分析 Linear 模式 dB 管理操作 | Batch 已统一适用性，单分析表面需要区分“编辑当前有效参数”与“管理参考目录” | 建立逐控件动作表；管理目录可能仍合理可用，不因关键词相同一律禁用。 |
| 新 helper 中宽泛异常降级 | `_collect_safe()`、axis metrics best-effort 等可把程序错误变为缺数据/静默失败 | 只审查本轮新增或直接触及分支，区分 expected Qt teardown 与 programming error，注入故障确认可观察性。 |
| 完整首显/缩放/边缘视觉矩阵 | 有历史 Cocoa 记录与本次局部 Cocoa 结果，缺当前全矩阵 | 稳定实现后一次矩阵验收，记录 frame/client、DPR、字体、真实像素。 |
| 原始客户长 ZFD | 当前无法取得最初问题文件；六个本机样本不足以代替 | 保持 UNKNOWN；获得文件后独立 corpus 验证计数/时间/单位/值。 |
| Windows Full/Lite frozen | 本次只做源码 packaging/help 检查 | 在实际新冻结包验证，未执行前保持 UNKNOWN。 |

## 8. 建议实施顺序与完成定义

优先顺序：**时间范围输入与精度 → 预设事务及 dirty → 来源修订/提示 → Batch 事实与禁用 → 测试供应及平台验收**。具体依赖以配套 plan 为准；ZFD fixture 修复可独立实施。

完成不是“本次发现全部写进测试”而已：每个 R 需求必须同时有 owner、真实入口验证、持久化/生命周期验证（适用时）以及用户反馈。P1 不留静默 fallback；已确认 P2 不以历史绿测关闭。疑似项先验证，证据不支持则明确关闭，不借横展做广泛重构。

当前未提交的进度标签 indent、自绘预设差异点、searchable combo 文案等改动属于用户已有工作，均保留；不能把它们算入本次提交 review 的修复结果。实施前应重新检查并协调这些文件，避免覆盖。

本次 lesson 状态为 `lesson_required: False`。已使用的既有 projection/Qt geometry/证据隔离规则覆盖这些模式；此次交付中不改动用户已脏的 lessons index。实施阶段由真实回归测试闭合后，再判断是否需要补充一条尚未覆盖的 durable lesson。
