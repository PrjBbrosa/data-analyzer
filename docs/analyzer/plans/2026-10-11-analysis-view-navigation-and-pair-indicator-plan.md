# 分析 View 标签导航与并排关系标识优化 Plan

- 日期：2026-10-11，Asia/Shanghai。
- 状态：**修复完成，focused / boundary 与 Cocoa 验收通过**。原用户项目与 Windows frozen 独立标记 UNKNOWN；详见[实施验证](../verify/2026-10-11-analysis-view-navigation-and-pair-indicator.md)。
- 核查基线：`66fba35720f036d2eac6068e9542b2f4577bbad5` + 现有 dirty worktree；预存版本、dB reference、帮助、测试和打包修改均保留。
- 用户场景：View 1 与 View 2 并排；点击 View 2 只聚焦右侧；切 View 3 后 View 1 半色标识消失；再点 View 2 又能正常打开。
- 范围：FFT、时频、阶次、FRF 的跨 View 导航、配对标识与对应状态事务。保留同参数窗格、独立参数、显式计算、共享工具栏和现有项目格式。

## 1. 结论与分级

| ID | 级别 | 已确认问题 | 用户影响 |
| --- | --- | --- | --- |
| N1 | P1 | 标签导航被“当前已显示此 View”条件改写成 pane 焦点切换 | 同一个 View 2 标签因来路不同而执行不同动作，必须绕经 View 3 才能打开 View 2 自己的页面 |
| N2 | P2 | 半色标识读取当前挂载的 peer widget，而非保存的 host→peer 关系 | 离开 View 1 后图标恢复单色，但返回 View 1 又自动并排，界面不能准确表达已保存的关系 |
| N3 | P2 | QTabBar currentIndex 与 manager.active 分离 | View 2 有选中背景、View 1 有活动下划线；菜单与页面仍以 View 1 为 host，用户难以判断当前所处页面 |

N1 是旧交互合同与用户期望冲突，不宜仅称为今天新增代码回归。`git blame` 显示 `_on_analysis_switch` 的 focus 分支来自 `519ca4df2`（2026-10-04）；旧计划还明确要求“点击已显示 B 的标签只转移焦点”。今天 `66fba357` 的 follow-up 保留了该规则，并新增了 N2 的 widget-derived provider。N3 在本轮当前代码与 Cocoa 窗口中确认，未进行首次引入版本的独立二分。

当前检出 Git 历史只看到今天一个聚合提交 `66fba357`，不能据此把用户所说“两波”强行对应为两个已确认提交。

### 1.1 真实点击复现

使用真实 `MainWindow`、生产 QSS、双来源合成 CSV、三个 View，点击真实 QTabBar 标签中心；不直接调用 switch/focus 代替用户点击。探针复用 `tests.conftest` / `tests.ui.conftest` 的 QSettings 隔离与 Qt 清理。结果中的 View 名称仅供报告，运行身份使用 `view_id`。

| 步骤 | manager.active | QTabBar 当前项 | 实际显示 | 焦点 | View 1 保存的关系 | View 1 半色 |
| --- | --- | --- | --- | --- | --- | --- |
| 打开 1→2 | View 1 | View 1 | 1+2 | View 1 | →2 | 有 |
| 点 View 2 | **View 1** | **View 2** | **仍为 1+2** | View 2 | →2 | 有 |
| 点 View 3 | View 3 | View 3 | View 3，peer 已拆卸 | View 3 的普通路径 | **仍→2** | **消失** |
| 再点 View 2 | View 2 | View 2 | View 2 | View 2 的普通路径 | 仍→2 | 无 |
| 返回 View 1 | View 1 | View 1 | 1+2 恢复 | View 1 | →2 | 恢复 |

“实际还是在并排”需分开理解：**配对关系确实还在**；本轮探针中切 View 3 后，屏幕上的 peer 已销毁、`displayed=None`，并未继续显示两列。用户第三张截图也显示 View 3 的单幅主图与切片。若原项目切 View 3 后仍存在可见双列，则是本轮未复现的另一条路径，需以该项目追加诊断，不能把它当作已经证明的布局泄漏。

证据目录：`.state/view-tab-navigation-20261011/`。

- offscreen：`4 passed, 13 warnings in 5.08s`，FFT / 时频 / 阶次 / FRF 均记录相同状态序列。
- Cocoa：`1 passed, 3 deselected in 2.47s`，时频真实标签点击复现；检查 `cocoa-click-B.png` 可见 View 2 背景高亮、View 1 下划线、右侧橙色焦点条；`cocoa-click-C.png` 可见单 View 与消失的半色图标。
- 这些 PASS 表示**当前缺陷行为被稳定记录**，不是修复验收。探针处于未计算空态；不证明已有结果、色阶、游标和异步任务在修复后无回归。
- 用户原项目、用户截图所用运行包、Windows frozen：**UNKNOWN**。未把合成 Cocoa 复现等同于原项目验收。

## 2. 根因与源码证据

行号为本轮核查快照；实施前按符号重新定位。

### N1：导航事件被截获，且存在第二层反向恢复

1. `ui/view_tabbar.py:1383` `_on_current_changed()` 发出 `switch_requested`；`ui/main_window/window.py:1459` 路由到 `_on_analysis_switch()`。
2. `ui/main_window/_analysis_mixin.py:287–302`：当目标已在并排中，调用 `activation_effect()`，得到 `focus` 后仅调用 `focus_comparison()` 并 return。
3. `ui/main_window/analysis_comparison.py:83–88`：只要目标在 displayed host/peer 集合内，就认为是 focus；用户的“打开页面”意图被可见性条件覆盖。
4. `_analysis_mixin.py:2118–2135` 还有第二层：manager 切到当前 peer 时，会聚焦 peer，再把 manager.active 改回 host。**只删第一层分支不能修复。**
5. 点 C 时走 `suspend()`，保留关系但撤下展示；之后点 B 已不命中 focus 拦截，因 B 没有自己的关系而正常显示。

当前时域 `_view_mixin.py:787–804` 的 `_switch_view()` 是捕获旧状态后 `set_active(idx)`，没有相同的“已显示 peer 就改成 focus”分支。这是源码对照，不是本轮完成了时域原生验收。

### N2：关系 owner 正确，投影取错数据层

- 持久意图：`AnalysisComparisonDisplay._relations`，通过 `peer_of(section, host_id)` 查询；`suspend():135–140` 明确保留它。
- 临时展示：`_displayed` / `_focus` / canvas binding，以及 page 的 `_peer_host` / `_host_view_id` / `_peer_view_id`。
- `analysis_section_page.py:1200–1206` `_comparison_partner_index()` 先要求 `_peer_host` 存在，并且 index 等于当前 host，故只能表达屏幕上这一对。
- `hide_comparison_peer():1731–1768` 撤下 peer、清空 page IDs 并刷新图标，provider 随即返回 None；`ViewTabBar._partner_color_for():721` 的绘制本身按 provider 正常工作。
- `test_analysis_comparison_tabs.py::_analysis_bar()` 用自建 relation 字典作为 provider，能正确表达隐藏关系，却绕过了有缺陷的生产 page provider。组件像素测试通过不能证明 MainWindow 接线正确。

### N3：标签选择和页面确认不是同一结果

QTabBar 在 currentChanged 发出前已切到 B；N1 路径没有切 manager，也未恢复 QTabBar。`view_tabbar.py:814` `_confirmed_active_view_id()` 仍读 manager.active，活动 marker 因而停在 A，而 native current-tab 背景停在 B。`mark_comparison_focus()` 更新焦点/按钮/色块，并不解决导航状态分裂。

## 3. 目标交互合同

**标签选择页面，图面点击选择操作焦点，半色表示保存的并排关系。** 不新增第三套 selected-view 状态，不借本轮重构整个 View 系统。

| 用户动作 / 场景 | 目标行为 |
| --- | --- |
| A→B 并排中点击 B 标签 | 打开 B 自己的页面；B 无关系时显示 B，B→C 时显示 B+C。A→B 关系保留 |
| A→B 并排中点击右侧图面 / 切片 / FRF 子图 | 保持 A 页面，焦点切 B；Inspector 和共享动作指向 B，标签选择仍为 A |
| 点击 A 标签 | 回到 A 页面，恢复 A→B；重复点击已活动 A 不重建画布、不额外提交 DSP，保留图面焦点 |
| 从 A→B 切 C，再回 B | 与直接点 B 完全同义；不依赖是否先经过第三个 View |
| A→B 未显示在屏幕上 | A 仍为 A/B 半色；B 若无自己的关系则为纯色 |
| A→B、B→C 同时存在 | A 显示 A/B 半色，B 显示 B/C 半色；打开 B 只展示 B+C，不递归展开 C 的关系 |
| 显式存在 A→B、B→A | 各 host 只展示一层自己的关系，不因点击而新增反向关系，也不递归 |
| 切页面 / 切模块 | 暂停展示与解除临时绑定，保留关系与联动设置；恢复按目标 View 身份解析 |
| 显式“结束 View 对比” | 删除当前展示 host 的关系，恢复该 host 普通页面；对应图标恢复纯色，View/结果不删除 |
| 删除 peer / host、项目替换 | 清理所有无效关系、绑定与标识，不留下幽灵半色或失效 Qt wrapper |

稳定投影完成后 `QTabBar.currentIndex == manager.active`，活动 marker 也指向同一 View。图面焦点单独由 `(section, view_id, pane_index)` 和现有焦点条 / Inspector 标题表达。

半色不意味着“此刻屏幕正在显示并排”，它表示“打开这个 View 会带上此 peer”。可复用现有 tooltip 说明 `View 1 · 与 View 2 并排`，不加额外工具栏或覆盖画布。仅存在关系变更才按既有 dirty 语义处理；导航本身不伪造关系修改。

## 4. 状态事务与实现边界

导航顺序必须是：

1. 验证目标的稳定 `view_id`，提交旧焦点编辑器的有效输入，捕获旧焦点及必要的可见 pane 状态。
2. 若离开当前 host，调用保留关系的 suspend 路径，解绑临时联动和 canvas target，拆卸 peer；不要误用会删除关系的 `close()`。
3. 激活目标 View，投影其参数、来源、时间和已接受结果；不因导航发起 DSP。
4. 查询目标自己的 host→peer 关系，仅挂载这一层；重新建立 canvas target，投影焦点/Inspector/共享按钮。
5. 用已确认的 manager.active 同步 native current、marker 与溢出列表；所有 host 的色块从关系 owner 读取。

实施时以现有 `_capture_active_analysis_view`、`_suspend_comparison_display`、`_on_analysis_view_switched`、`_restore_remembered_comparison` 为边界，避免捕获两遍、先清 binding 后再猜旧参数目标、或依赖 signal 重入回滚。程序化 `set_active()` 与标签路径都须满足同一合同；`open_comparison()` 从非活动 host 启动时不能被新的导航逻辑错误 suspend。保留/收窄 `hold_switch` 的必要范围，不能机械删除所有 guard。

| Owner | 改动责任 | 禁止扩张 |
| --- | --- | --- |
| `_analysis_mixin.py` | 区分显式导航与画布 focus，消除两层 peer 导航拦截，保留捕获和恢复事务 | 不复制算法，不新增多个 MainWindow 状态字段 |
| `analysis_comparison.py` | 继续独占 relations / displayed / focus / bindings；检查 `activation_effect` 是否退役或限定用途 | 不存 tab index，不给 `ViewManager._split_pairs` 写第二份关系 |
| `analysis_section_page.py` + `window.py` 既有接线 | 给 page/tabbar 注入只读关系解析器，按任意 host ID 查询 owner；明确关系变更/项目恢复/删除后的刷新 | 不从可见 widgets 反推持久关系，不缓存一份 relation dict |
| `view_tabbar.py` | 仅在必要时补确认后的选择同步、关系 tooltip；复用现有 swatch / overflow / marker | 不把整条 tab 当 peer 焦点指示器，不靠手动画死图标解决 N2 |
| hints / quickref / 帮助 | 明确新导航语义；同步四分析指南与用户指南中受影响段落 | 不改版本号，不覆盖已有并行文案修改 |

刷新是只读投影，不引起 `switch_requested`、计算或 dirty 回写。多个关系的改色、重命名、重排、删除都从稳定 ID 重新解析；窄窗 overflow 和正常标签使用同一个 provider。

## 5. 实施任务与门禁

按 T0→T1→T2→T3 顺序实施；任务共享导航/关系边界，不安排并行 agent 或默认全套测试。

### T0：将用户点击序列固化为失败回归

- [x] 记录实施时 HEAD、dirty 范围及相关源指纹。新增 `tests/ui/test_analysis_view_navigation_contract.py`，正式使用 UI fixtures；`.state` 探针仅用于本轮诊断。
- [x] 四模块真实 QTest 点击 A→B 中的 B，断言 B 成为 active、A→B 被保留、屏幕显示 B 自己的关系、current/marker 一致。修复前 N1/N3 应失败。
- [x] 真实 MainWindow 中切 C 后检查 A 的 partner provider、主标签与 overflow 色块；不能用测试自建关系字典代替生产 provider。修复前 N2 应失败。
- [x] 加图面点击正对照：仍聚焦 B，active/current 均留 A；未提交输入写回旧目标。
- [x] 更新 `test_analysis_view_comparison.py::test_relation_survives_rename_and_ends_when_the_peer_is_deleted` 中旧“点 peer 仍 active=host”期望，保留 rename/reorder/delete 和不产生反向关系断言。

Focused：仅上述新增节点及变更的既有节点。完成门：失败来自 N1/N2/N3，而非 fixture、数据或控件未布局。不跑全仓 baseline。

### T1：统一导航入口与状态交接

- [x] 按 §4 修复两层拦截；追踪标签、overflow、View 快捷键及直接 manager 激活路径，确保入口一致。
- [x] 增加 A→B→C→B→A、A→B/B→C、双向显式关系、同 host 重入、非活动 host 开始并排测试。
- [x] 保留旧焦点 pending input、参数/来源/范围/手动色阶、游标和已接受结果；导航/恢复 zero DSP；迟到任务只写原 View，不劫持当前 Inspector。
- [x] 同参数窗格 1+1、1+2、2+1、2+2 不被误当成跨 View 页面；至少覆盖 peer 有两个 pane 且第二 pane 聚焦时离开的捕获。

Focused：新 navigation contract、`test_analysis_view_comparison.py`、`test_analysis_view_comparison_regressions.py`、`test_analysis_comparison_state_contract.py` 与 `test_analysis_explicit_refresh_contract.py` 的受影响节点。Boundary：`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`。完成门：真实标签导航一致，真实图面焦点独立，未提交输入/后台结果不串写。

### T2：按持久关系投影全部标签

- [x] 替换 page 的 live-widget provider，接入 comparison owner 的只读 `peer_of()`；provider 初始化和 reset 对称。
- [x] 对关系 begin/replace/close/forget/restore 与 manager rename/color/reorder/delete 建立完整刷新，暂停展示不会消除半色。
- [x] 真实 page + manager + owner 集成测试覆盖 inactive host、多个关系、peer 自有关系、删除与项目恢复；保留 existing swatch 单元测试。
- [x] DPR 1/2 检查实际色块两半像素、current/marker 几何；窄窗 overflow 选 B 与普通标签同义，重排后按 ID 找到新 index。

Focused：新 navigation contract、`test_analysis_comparison_tabs.py`、`test_view_tabbar.py` / `test_view_tabbar_mount.py` 受影响节点；`tests/test_project_io_analysis_views.py` 与 `test_project_session.py::test_project_restores_analysis_comparison_by_view_id`。若新增 QSS 才运行 border/radius gate，方案本身不要求改 QSS。

完成门：离开 A 图标仍表达 A→B；结束/删除才清除；正常标签与 overflow 的显示和动作一致；不新增项目 schema。

### T3：文档、原生验收与交付

- [x] 更新 hints / quickref、四分析指南和用户指南的相关描述；搜索“点击已显示”“只转移焦点”等旧约定。历史文档保留，当前帮助不能继续教旧行为。
- [x] 有实际计算结果的 Cocoa 窗口走用户完整序列，使用不同来源/参数/颜色；截图证明 B 被打开、A 半色持续存在、点击图面不改活动标签。另验收宽/窄窗与 overflow；手动色阶、范围与游标状态采用既有 focused 合同验证，证据分列。
- [ ] 对原用户项目执行同序列；若无该项目，明确 UNKNOWN，不用合成空态测试代替。
- [ ] Windows fresh Full/Lite frozen 验收单列，未运行就标 UNKNOWN；本计划不自动授权打包发布。
- [x] 审查本轮 diff、引用/文档状态、`git diff --check` 和 lessons status；未 commit/push。

Focused：`test_hints.py`、`test_quickref.py`、`tests/test_help_content.py` 的既有受影响合同。文档自身只做路径/引用/语义/whitespace 检查，不新增镜像文案测试。适用 focused/boundary 通过即收口；仅因新发现跨边界问题、发布/合并要求或用户明确要求才扩展 full gate，并遵守单 coordinator、稳定快照及 acquisition 分进程规则。

## 6. 验收表

| AC | 必须证明的结果 | 当前状态 |
| --- | --- | --- |
| AC1 | A→B 中点 B 直接打开 B，经过 C 与否结果相同；四模块一致 | 已实现；navigation contract / Cocoa |
| AC2 | 点右侧画布只转焦点，host 页面/标签不变；共享动作和参数指向 B | 已验证；详见实施报告 |
| AC3 | 切 C / B / 模块后 A 仍半色；返回 A 恢复 A→B；多个关系各自显示 | 已实现；navigation contract / Cocoa |
| AC4 | current、active、marker 始终一致；普通/快捷键/overflow 导航一致 | 已实现；navigation contract / Cocoa |
| AC5 | 改色/改名/重排/删除/结束/保存重开不留幽灵关系，不改变 schema | 已验证；详见实施报告 |
| AC6 | pending 输入、来源/范围、色阶、游标和结果归属保留；导航不算、不串写 | 已验证；详见实施报告 |
| AC7 | Cocoa 有结果场景、原用户项目、Windows frozen 分别记录 | Cocoa 实际计算与完整切换通过；原项目 / Windows UNKNOWN |

## 7. 与旧合同的关系

本计划已实施，替代以下文档中“点击已显示 peer 标签只聚焦”的导航规则，保留其他结果、参数、持久化、工具栏与 focus 合同：

- [10-04 跨 View 计划](2026-10-04-analysis-view-result-validity-and-cross-view-comparison-plan.md) §7 的点击语义。
- [10-11 一致性 follow-up plan](2026-10-11-analysis-comparison-timedomain-parity-followup-plan.md) T3 的 peer 标签 focus 条款。
- [10-11 follow-up spec](../specs/2026-10-11-analysis-comparison-timedomain-parity-followup-spec.md) 的半色条款补充为“保存的 host 关系”，包括 inactive host；peer 自身若拥有关系，也作为 host 显示自身半色。

[旧实施验证](../verify/2026-10-11-analysis-comparison-timedomain-parity.md) 的历史 PASS 保持原记录，其组件 provider/焦点测试不能作为本次导航与 inactive-host 标识的验收。本次没有修复或关闭旧报告中的其他剩余平台/交互门禁。

## 8. 实施时追加发现 N4

实际计算结果的 Cocoa 验收发现，FFT-time 的 host/peer 画布各自给第一个结果分配相同的 dB memo epoch。peer 的结果转移到 host 画布时，可能误命中 host 原来的矩阵。双画布、不同幅值、float32/float64 的 owner 回归在修复前均失败。

已将 `pg_canvas/heatmap_canvas.py::_result_db_token` 的分配改为进程内统一递增；结果身份仍随结果对象移动，不改 dB 公式、结果形状、dtype 或非有限值处理。新增 owner 测试和缓存/参考值 focused gates，并扩大到 heatmap owner / backref boundary 验证。该范围扩展由真实完整流程中的串图证据触发。

频谱验收最初比较了按画布宽度抽稀后的 PlotDataItem 数组，500/1250 点差异属于显示策略；已改为比较 canvas 保留的完整 `_entries` 数据。未为探针改动频谱抽稀逻辑。
