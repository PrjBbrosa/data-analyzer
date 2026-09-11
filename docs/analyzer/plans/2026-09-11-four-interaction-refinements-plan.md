# TraceLab 四项交互优化 Implementation Plan

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐任务实施，默认同一执行者顺序执行。本计划不授权派生 agent。步骤以 checkbox 跟踪；当前仅完成计划，未授权实施本计划的产品改动。

**Goal:** 在现有界面接入通道搜索空态与上下文恢复、Batch 结果详情、三个 Batch 小开关的轻动效，以及 View 底部标记动效。

**Architecture:** 通道树拥有临时筛选快照；BatchSheet 继续拥有运行结果及操作路由，新详情组件只负责展示；PillSwitch / ViewTabBar 复用现有 ValueDriver，先区分直接操作与程序投影，再显式开启生产实例。维持现有状态、信号与数值计算边界。

**Tech Stack:** 当前 PyQt5 / Qt 5、生产 QSS、pytest/pytest-qt、Cocoa 真实渲染。HTML 仅为交互参考，不嵌入应用。

日期：2026-09-11。调查基线：`a8d4b231`；调查时仅有无关未跟踪文件 `ssh-keygen`。状态：**计划完成；实现与原生验收未执行**。

参考：[四项本体 HTML](../ui-prototypes/2026-09-10-native-interaction-context.html)、[源码与原型边界说明](../ui-prototypes/2026-09-10-native-interaction-context-notes.md)。代码比原型具有更高优先级；示例错误、文件和参数不进入产品逻辑。

## 1. 范围和决定

| ID | 本次新增 | 已有能力，只保护不重写 |
|---|---|---|
| S | 无匹配 / 没有已选通道提示、清除筛选、同一上下文恢复展开及滚动 | 原关键字匹配、已选交集、全选/全不、勾选与眼睛显隐、WWT 记录树 |
| B | Batch 底栏“查看详情”，任务原因、警告、产物及配置检查入口 | 三栏布局、50 px 底栏、现有进度、结束提示、运行/中断、输出规则 |
| P | Batch 滤波、图内统计、切片三个 PillSwitch 显式启用 160 ms；程序更新直接定位 | 开关立即提交状态、原参数显隐、关掉保留子参数、运行锁定 |
| V | 时域及分析页的 ViewTabBar 启用 140 ms / 2 px 底部标记 | 增删、命名、重排、管理菜单、紧凑编号、活动 View 可见、上限与最后一个保护 |

- 不重复 400/300 ms 选择背景滑动的现有工作，不改其 token、曲线或 SelectionIndicator。
- 不加入配置草稿/应用改造、参数折叠动效、最近打开弹层、Board/UltraView 页签改造。
- P 只启用三个已演示的 Batch 开关；时域 Inspector 滤波与 FRF 低相干淡化仍按原策略，使用通用 PillSwitch 的程序更新修正，但不自动启用。
- V 覆盖同类时域/分析 View 栏，不将上限硬编码为统一值：时域 24、分析 12，实际取 manager.max_views。
- 不改 DSP、Batch 计算/输出算法、View 恢复 settle、QSettings 或项目 schema；不新增全局动效设置。
- 本次 HTML 下方“当前逻辑”是调查证据，不是完整原生规格。例如 HTML 的立即显示关闭叉、简化输入框不能覆盖原生 hover 保护和配对编辑器。

## 2. 当前接线证据与顺序

| 位置 | 当前代码事实 | 实施影响 |
|---|---|---|
| `ui/widgets/channel_tree.py:_apply_filters` | 匹配后展开容器；没有退出筛选快照恢复 | S 必须以稳定节点身份保存快照，不能只保存文本 |
| `ui/drawers/batch/sheet.py` | `_task_list.hide()`；`_last_result` 由完成回调持有；底栏独立汇总 | B 不能把旧隐藏列表的 tooltip 当作可见交付 |
| `ui/widgets/pill_switch.py` | 默认 POLICY_OFF；`checkStateSet` 与 `nextCheckState` 都调用 `_follow_checked_state` | P 不能只调用 set_motion_policy；需要恢复不动画的合同 |
| `ui/view_tabbar.py:_sync_active` | manager 同步一律传 `interpolate=True` | V 必须区分直接激活与程序 set_active / restore |

以上 `ui/` 路径均相对 `mf4_analyzer/`。

执行顺序：**T0 → T1(S) → T2(P) → T3(V) → T4(B) → T5**。四项各有独立退出条件；B 工作量最大，放在通用控件验证之后。不安排自动拆分代理或跨任务并行写文件。

## 3. T0 — 确认基线与范围

- [ ] 记录当前 HEAD、`git status --short` 和任务相关文件指纹到 `.state/four-interaction-refinements/baseline.json`；保留无关 dirty/untracked。
- [ ] 复核本文件、HTML 说明和相关 lessons：`qt-composite-disabled-cues-follow-effective-state.md`、`view-close-hover-requires-current-reentry.md`、`viewtabbar-managed-overflow-no-native-scroll.md`。
- [ ] 核对四个 owner 是否已被其他任务修改；已实现部分直接验证，不按历史计划重复开发。
- [ ] 每个任务开始时只运行该任务已有 owner 测试；新测试先失败，再实现。T0 不运行全套或整个 `tests/ui`。

统一命令前缀：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q
```

后续命令均接此项目运行前缀。隔离设置沿用项目 fixtures；测试 QWidget 有明确 parent/qtbot 管理，不写真实用户 QSettings。

## 4. T1 — S：搜索空态和恢复上下文

**修改：**

- `mf4_analyzer/ui/widgets/channel_tree.py`：快照、匹配计数、空态、退出筛选恢复。
- `mf4_analyzer/ui/file_navigator.py`：薄转发 `invalidate_channel_filter_context()`。
- `mf4_analyzer/ui/main_window/_view_mixin.py`、`_analysis_mixin.py`：在已有控件投影入口调用失效通知，不新增 MainWindow 状态。
- `tests/ui/test_channel_widget.py`、`test_channel_widget_setters.py`；新增 `tests/ui/test_channel_filter_context.py`。

**操作合同：**

1. `filtering = bool(search.text().strip()) or btn_selected_only.isChecked()`。无筛选→有筛选时只捕获一次；连续打字与已选组合不覆盖原快照。
2. 快照只保存带身份的展开状态、视口顶部可见节点及其偏移、滚动数值回退。节点身份复用 Qt.UserRole 元组与 `_tree_item_for_data`；不保存 QTreeWidgetItem wrapper、不使用通道名键、不恢复勾选/轴组/曲线显隐。
3. 清除输入框只清关键词；空态“清除筛选”同时清关键词与已选；仅当两者都关闭才恢复。恢复发生在取消隐藏、更新树布局之后；用单次排队恢复时校验 generation，禁止旧回调覆盖新筛选。
4. 筛选中用户手动展开/收起只影响筛选期间，退出仍恢复筛选前快照。
5. 同一数据上下文未变时恢复展开和滚动；删文件、换 View、换分析模式、重置项目、重建树或重设附件范围使快照失效。跨上下文保留原有搜索词策略，但不恢复旧树位置；下一次完整退出并重新进入筛选才建立新基线。
6. 0 匹配保留搜索框、操作行和配置条。没有附件继续用现有“当前 View 尚未加入文件”；有附件且已选为零使用“尚未勾选通道”；其余为“没有匹配的通道”。这三个状态不能互相覆盖。
7. 计数区分普通通道和记录曲线；“已选”仅计可勾选通道，WWT 记录曲线保持原例外。记录组标签命中但无叶子时保留当前容器结果，不误判成空树。
8. Esc 在搜索框内有关键字时清词并保持焦点；空关键词时不拦截原有上层 Esc。不改变“全选仅可见通道 / 全不清空全部勾选”的现有语义。

**局部状态契约（新增字段由 ChannelTree 初始化和清理）：**

```python
self._filter_snapshot = None
self._filter_generation = 0
self._filter_restore_pending = False

# FileNavigator 只转发；MainWindow 不存这些字段。
def invalidate_channel_filter_context(self):
    self.channel_list.invalidate_filter_context()
```

`invalidate_filter_context()` 清空 snapshot、增加 generation、取消旧恢复资格；不改变搜索词、勾选或业务信号。在 `_project_view_controls` 投影前、`_project_analysis_attachments` 投影前调用；ChannelTree 自身的附件更改、移除/刷新树和 teardown 同样使快照失效。

- [ ] 用现有 `_add_attached_file` / `_MultiChannelFileData` 夹具添加失败用例：折叠→搜索→继续输入→清除后折叠恢复，且 channels_changed / visibility_changed 未增加。
- [ ] 添加多个同名来源、关键词+已选交集、WWT 记录组、筛选中删除来源、相同附件但不同 View、快速清除后立即重新搜索等用例。
- [ ] 在 `_apply_filters` 既有一次遍历中取得计数与可见结果；避免每个叶节点反向查找全树。不增加隐藏树副本或全应用事件扫描。
- [ ] 接入空态、清除按钮、generation 恢复；分清 `_sync_empty_state` 的“无附件”与“筛选为空”。
- [ ] 执行以下 owner gate；其余原生验证留 T5。

```text
tests/ui/test_channel_filter_context.py
tests/ui/test_channel_widget.py
tests/ui/test_channel_widget_setters.py
```

**退出：** 搜索不改变数据状态；同上下文可恢复，跨上下文不污染；相同文件名/通道名不会混用身份。

## 5. T2 — P：三个 Batch 小开关

**修改：** `mf4_analyzer/ui/widgets/pill_switch.py`；`mf4_analyzer/ui/drawers/batch/filter_panel.py`、`slice_panel.py`、`chart_statistics_panel.py`。

**测试：** `tests/ui/test_pill_switch.py`；新增 `tests/ui/test_batch_switch_motion.py`；复用 `test_batch_slice_panel.py`、`test_batch_chart_statistics.py`、`test_motion_demo.py`。

- [ ] 先写真实父窗口下失败测试，区分 `QTest.mouseClick` / Space / 标签 click 与 `setChecked` / apply_*。程序改变状态仍保留原 toggled 语义，但 driver 必须 inactive；直接用户切换 driver active、checked 立即变化、toggled 仅一次。
- [ ] 重构 PillSwitch 的局部呈现入口：`checkStateSet` 默认 snap；`nextCheckState` 仅允许本次直接切换的最终合法状态跟随动画。`_follow_checked_state` 增加 keyword `animate=False`，唯一 True 来源是当前按钮的直接激活；不由 `isVisible` 猜测用户来源。
- [ ] 用户激活期间同步 `toggled` 订阅者可能回写 checked、禁用或删除控件：预先消费一次激活标记，回写路径保持 snap；finally 清标记，必要时 sip.isdeleted 检查。最终状态被业务校正后不得启动旧目标动画。
- [ ] 为三个生产实例各显式启用 POLICY_LIGHT；通用构造保持 POLICY_OFF，不改 `duration_ms('switch', ...)`、44×24 几何、track/knob token。

```python
# filter_panel.py / slice_panel.py：绑定与默认状态设置完成后
self._enable_switch.set_motion_policy(POLICY_LIGHT)
# chart_statistics_panel.py
self.enabled.set_motion_policy(POLICY_LIGHT)
```

- [ ] EnabledChange 同步颜色、动画和 cursor：有效 enabled 才 PointingHandCursor，祖先锁定时 ArrowCursor；重新启用直接定位真实 checked 值。hide / deleteLater 停止动画。
- [ ] 在真实 BatchSheet 验证：滤波关掉再开启保留截止值；图内统计只在 time；切片只在 fft_time/order_time；导入方案直接定位；lock_editing/unlock_editing 不误触发 changed 或计算。
- [ ] 执行上述 5 个测试文件。新增回归例采用原生 owner，不用 HTML 状态或 monkeypatch `_should_interpolate=True` 代替接入。

**退出：** 状态/参数立即生效；只有用户触发播放 160 ms；恢复、禁用、程序联动不补播。其他 PillSwitch 不被全局开启。

## 6. T3 — V：View 底部细标记

**修改：** `mf4_analyzer/ui/view_tabbar.py`；生产创建点 `mf4_analyzer/ui/chart_stack/stack.py`、`mf4_analyzer/ui/analysis_section_page.py`。

**测试：** `tests/ui/test_view_tabbar.py`、`test_view_tabbar_mount.py`、`test_view_state.py`；新增 `tests/ui/test_view_marker_activation.py`。

- [ ] 先测直接点击现有 View 与 `manager.set_active` 的不同来源；构造时域与分析真实挂载点，不只测试手工开策略的孤立控件。
- [ ] 在 ViewTabBar 中维护一次性用户目标 view_id，不将 tab ordinal/名称当身份。`_on_current_changed` 的直接 UI 路径和 `_on_overflow_switch` 设置目标，已有 `switch_requested` 同步发送；`_sync_active` 仅在确认的 view_id 匹配该目标时传 interpolate=True，并立即消费。业务未接受、修正为其他目标、调用结束或异常均清理，不能残留到后续程序同步。
- [ ] 同布局用户切换允许现有 140 ms；新增/关闭/重排/compact 或 overflow 重排、字体/尺寸/隐藏/失活/恢复均 snap。菜单切换若导致活动页签重新入栏，也按布局变化 snap。
- [ ] 显式在两个生产创建点启用 POLICY_LIGHT；通用 ViewTabBar 默认 Off。Off/Reduced 保留原静态 QSS 标记，不能在恢复静态时出现双下划线。

```python
# ChartStack.attach_view_tabbar 创建 bar 后
bar.set_motion_policy(POLICY_LIGHT)
# AnalysisSectionPage 构造 ViewTabBar 后
self.tabbar.set_motion_policy(POLICY_LIGHT)
```

- [ ] 验证快速来回点击从当前显示位置转向，不排队、不重复激活业务；marker 不拦截 mouse/key，不改 hit rect、卡片尺寸或 canvas。
- [ ] 保护所有现有交互：活动 View 不被隐藏、24/12 上限、最后一个不可单独关闭、关闭全部保留默认 View、全部管理菜单、F2/重排、分屏焦点，以及**切换成当前后鼠标必须离开再进入才出现可用关闭叉**。
- [ ] 执行 4 个 owner gate。不重写 ViewManager；View 恢复仍走既有 settle，不加入动画完成回调。

**退出：** 同布局直接选择只移动 2 px 底标；程序恢复无动画；View 增删管理本身没有新语义。

## 7. T4 — B：底栏展开本次运行详情

这是四项中唯一新增可见结果面板，分为数据投影与界面接线两个步骤，仍由同一执行者整合。

**新增：** `mf4_analyzer/ui/drawers/batch/result_details.py`，放只读结果行投影及 BatchResultDetailsPanel；`tests/ui/test_batch_result_details.py`。

**修改：** `mf4_analyzer/ui/drawers/batch/sheet.py`；若需局部样式，仅改 `mf4_analyzer/ui_kit/style.qss` 的 BatchResultDetails 命名区域。

**复用测试：** `tests/ui/test_batch_smoke.py`、`test_batch_task_list.py`。不修改 batch.py / batch_types.py / reporter 或输出策略。

### B1 — 唯一结果来源与安全定位

- [ ] `BatchRunResult.items` / `render_groups` / `blocked` / `warnings` 是详情事实来源，sheet._last_result 是现有 owner。新组件不发进度、不维护第二份运行状态机、不从旧列表显示文本反解析诊断。
- [ ] 显示冻结的本次结果投影，至少包含如下字段；row_key 使用 (本地本次 generation, task_id)；缺失 task_id 时使用 (generation, item_index)，绝不以文件名、signal 文本聚合。

```python
@dataclass(frozen=True)
class ResultDetailRow:
    row_key: tuple
    file_id: object
    source_identity: str
    file_name: str
    method: str
    signal: str
    input_signal: str
    output_signal: str
    status: str
    message: str
    warnings: tuple[str, ...]
    data_path: str | None
    image_path: str | None
    group_identity: str
```

新增纯投影函数 `project_result_rows(result, *, generation) -> tuple[ResultDetailRow, ...]` 不持有 QWidget，不修改输入 DTO。组件接口 `set_result(result, *, generation)`、`clear()`；发出 `artifactRequested(str)`、`locateRequested(str)`，参数为实际路径或现有定位 kind，sheet 路由执行。

- [ ] 状态分别展示 done、failed、skipped、cancelled、resumed，以及已完成但带警告/降级。未知 status 原样可见；未提供 message 显示“未提供详细原因”，不编造诊断。0 items + blocked/warnings 展示运行级信息；None 结果明确没有可用详情，不残留上次数据。
- [ ] 渲染组失败和组产物独立列出；共享 image_path 只展示其实际产物归属，不统计成每项独立文件。禁止按列表索引猜测 render_groups 与 items 配对，使用 group_identity 与 group_id。
- [ ] 产物入口仅对本结果中存在的路径提供，点击时重新检查存在性；失效则提示“文件已移动或删除”，不猜输出文件名、不扫描目录配对。沿用 `_open_artifact_location`，不自动打开。
- [ ] 复制诊断只复制当前选中结果（状态、来源、输入/输出、原 message、warnings）；使用 QApplication.clipboard，不进行网络或文件写入。
- [ ] 当前 DTO 没有统一结构化 error_kind：**禁止用 PermissionError 等 message 子串自动判定根因并强制路由**。所有结果可提供中性“查看输出目录设置”入口（output）；FRF 行且当前方法仍为 frf、端点身份可核对时提供“检查信号配对”（frf）。未知错误仍能查看/复制原诊断，不把 HTML 固定错误变成分类器。
- [ ] 复用 `_resolve_locate_widget` 和 `_scroll_for_widget`；提取 sheet 内部 `_focus_locate_target(kind)` 供现有 `_on_footer_locate` 与详情共享。详情不得改写当前验证提示的 `_locate_kind`。目标不可见、已销毁、方法已切换时禁用或说明不适用，不自动切方法、不改配对。

### B2 — 面板、结果生命周期、底栏

- [ ] 新增“查看详情”位于现有汇总旁，只有本次完成结果含 item、group、blocked 或 warning 时可用。第一版运行中不提供流式详情；本次线程 finished 后接入结果，与现有 unlock/结束提示/打开目录顺序兼容。
- [ ] 面板作为 BatchSheet 子控件覆盖在底栏上方，不把旧 TaskListWidget 重新加入布局。保持三栏宽度/滚动、footer 50 px 与窗口尺寸；详情内部两列（任务列表/详情正文）各自滚动，高度目标 240 px 且不超过可用工作区 45%。窄窗改上下排列，长 message 自动换行，不裁剪操作按钮。
- [ ] 选择任务才更新右侧内容；默认选首个 failed，其次首个 skipped/warning，再首项。错误红、跳过琥珀、成功绿，状态同时有文字；不靠颜色区分。
- [ ] 新运行开始：隐藏面板、清投影并增加 generation，和 `_last_result = None` 同步；结束：刷新本次投影；关窗：停止组件回调、清理引用。修改配置后旧结果仍标“上次运行结果”，不因重算预览变成新结果；新任务被配置 gate 阻止时保留已有结果并明确它属于上次。
- [ ] Esc 先关闭详情并把焦点交还入口；收起、点击检查入口不关闭 BatchSheet。新的子面板 shortcut 仅在面板可见时生效，不拦截正常 Batch 中断/关闭逻辑。详情不增加自动重试或“只重跑失败”。
- [ ] 写失败测试后实现并运行：真实 sheet 完成回调→入口→逐项原因；相同 basename 不同 file_id；无 task_id；FRF missing pair skipped；分组图片失败；取消；0 items blocked；None；连续两次运行；产物删除；切换方法后配对定位失效；长诊断与 1080×760 几何。

**退出：** 用户能从当前真实底栏看到逐项结果且采取检查动作；进度计数、生成文件、计算调用和配置均未被详情面板改变。

## 8. T5 — 文案、原生检查与收尾

**修改：** `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`。新增实施证据文件 `docs/analyzer/verify/2026-09-11-four-interaction-refinements.md`（实施阶段才创建）。

- [ ] 两份帮助同时补充“清除筛选恢复上下文”和“批处理查看详情/收起/检查入口”；不宣称新重试、恢复任务或新导出规则。已存在 View 和 switch 操作不重新命名。
- [ ] 跑帮助 owner：`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`、`tests/ui/test_quickref_status_hints.py`。
- [ ] 所有任务 owner 通过后一次运行相关边界；只因新改动/失败才重跑。界面全量测试不属于默认门禁。

```text
tests/ui/test_import_boundaries.py
tests/ui/test_main_window_state_ownership.py
tests/ui/test_no_lambda_signal_connections.py
tests/ui/test_qsettings_isolation.py
tests/ui_kit/test_qss_border_shorthand.py
```

- [ ] Cocoa 用当前真实窗口和合成数据完成 S/P/V/B 四项操作，保存前/中/后截图、关键 geometry 与动效短录屏到 `.state/four-interaction-refinements/`；不是用 HTML 或 offscreen 冒充原生。覆盖 1080×760、1440×900、DPR1/2 可用组合；平台不能提供的组合标 UNVERIFIED。
- [ ] 重点比较：搜索清除前后 scroll/展开、三栏与 footer 坐标不跳、小开关 disabled cursor/track、View hit rect/关闭叉、详情长文本/遮挡/焦点返回。P/V 中间帧需实际看到运动，静止后 driver inactive。
- [ ] Windows 100%/150% 缩放只在可用机器验证；否则 Windows gate 明确 UNVERIFIED。此任务不是 release，不要求冻结包，也不跑全套。
- [ ] 报告记录执行时 HEAD 与任务文件指纹、各 owner 命令结果、Cocoa/Windows 分开的 PASS/FAIL/UNVERIFIED，分别回答 S/B/P/V 是否完成。检查运行期间改动；不能拿旧基线总数充当前结果。
- [ ] `git diff --check`、检查 lessons `--status`；仅实际出现可复用缺陷时补 lesson。本次只写计划无需运行 UI 测试。未来实施完成后的 commit/push 依据届时明确发布指令，不把前一轮 demo 的发布指令扩成永久授权。

## 9. 验收矩阵

| 合同 | Owner gate | 原生验收 |
|---|---|---|
| S1 搜索不改 checked / visibility；三类空态正确 | channel_filter_context + channel_widget | 主窗口直接搜索/清除 |
| S2 同名身份、跨 View/删除/排队回调安全 | channel_filter_context + channel_widget_setters | 两 View 及多来源切换 |
| P1 用户160 ms；程序/预设snap；禁用不可点 | pill_switch + batch_switch_motion | 三种真实 Batch 开关/父锁 |
| V1 用户140 ms；结构变化snap；活动 View 可见 | view_marker_activation + view_tabbar_mount | 紧凑/溢出、快速改选 |
| V2 关闭保护和 manager 上限不变 | view_tabbar + view_state | 鼠标重入后关闭、最后一个 |
| B1 真实 item/group/run 结果；不混同名；无虚构诊断 | batch_result_details | 失败/跳过/降级/取消 |
| B2 底栏入口、定位/复制/产物、连续运行生命周期 | batch_smoke + batch_task_list + batch_result_details | 两次运行、长正文、焦点、窄窗 |
| H 帮助和边界 | T5 owner + boundary gates | 文案与实际入口一致 |

当前交付门禁：计划范围、引用、任务接口和验收自检；实现 gate 全部未运行。不把这些 checkbox 勾选为完成。
