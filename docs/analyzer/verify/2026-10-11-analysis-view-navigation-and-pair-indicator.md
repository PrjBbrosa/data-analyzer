# 分析 View 导航与并排图标实施验证

- 日期：2026-10-11。
- 结论：**本地源码修复完成，相关自动化及 macOS Cocoa 验收通过**。原用户项目、原运行包与新 Windows frozen 为 **UNKNOWN**，不等同于发布验收。
- 对应[实施计划](../plans/2026-10-11-analysis-view-navigation-and-pair-indicator-plan.md)。
- HEAD：`66fba35720f036d2eac6068e9542b2f4577bbad5`；在既有 dirty worktree 上实施，未提交、未推送、未打包。
- 本地证据根目录：`.state/view-tab-navigation-implementation-20261011/`。原始日志、截图、指纹留在此目录，不纳入 Git。

## 1. 修复结果

**标签切页面、图面切焦点、半色表示保存的配对关系。**

| 操作 | 修复后观察与断言 |
| --- | --- |
| View 1→View 2 并排，点 View 2 标签 | 直接打开 View 2 自己的页面；manager active、标签背景与活动 marker 均为 View 2 |
| 接着点 View 3，再点 View 2 | 依次打开各自页面，与直接点 View 2 行为一致 |
| 离开 View 1 | View 1 半色标识保留，表示其保存的 1→2 关系 |
| 回到 View 1 | 恢复 1+2，并保留各自已计算结果；导航不触发 DSP |
| 在 1+2 中点击右侧图面 | 焦点与 Inspector 指向 View 2，活动页面和标签仍为 View 1 |
| View 2 自有 2→3 或显式 2→1 | 打开 View 2 时仅展示其一层关系；不递归、不隐式新增反向关系 |
| 结束对比、删除相关 View | 清除对应关系和半色；改名、改色、重排、切模块、保存重开按稳定 View ID 保持关系 |
| 窄窗 overflow | 真实菜单点击打开目标页面，和普通标签一致；半色使用同一关系投影 |

这里的“并排仍在”指保存的关系仍在。切到无配对的 View 3 时 peer widget 被撤下，屏幕恢复该 View 自己的页面。

## 2. 代码变更

- `mf4_analyzer/ui/main_window/_analysis_mixin.py::_on_analysis_switch` / `_on_analysis_view_switched`：删除标签转 focus 和 manager 回弹 host 两层拦截。先捕获旧焦点编辑状态，再暂停展示，保留关系后导航。非活动 host 开始并排也捕获旧状态。
- `mf4_analyzer/ui/analysis_section_page.py::_comparison_partner_index`：读取注入的 `comparison.peer_of()`，不再依赖当前 peer widget。`window.py` 接入现有 owner；关系变更及项目恢复刷新展示。没有新增关系字典或项目 schema。
- `analysis_comparison.py::activation_effect`：保留兼容方法，页面激活统一返回 `switch`。
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py::_result_db_token`：实际计算验收额外发现两个画布的本地 epoch 均可能为 1；peer 结果转移到 host 后误命中旧 dB 矩阵。改为进程内统一递增身份，结果 token 继续随对象移动。未改变 dB 算法、dtype、形状或非有限值策略。
- 新增 `tests/ui/test_analysis_view_navigation_contract.py`；更新旧 peer 标签断言；新增 float32/float64 双画布交换结果的缓存回归。
- 同步 `ui/hints.py`、`ui/quickref.py`、四分析指南和用户指南相关段落。已有版本、dB reference、打包和其他帮助修改保留。

## 3. 验证记录

以下是分阶段结果，不能相加为唯一测试数。未跑全仓 suite；本任务使用相关 owner、状态边界和原生流程门禁。

| 阶段 / 日志 | 命令结果 | 说明 |
| --- | --- | --- |
| 修复前 `red.log` | **35 failed, 3 passed, 91 warnings in 33.76s** | 原始 38 项导航断言复现标签拦截、选择分裂、inactive 半色缺失 |
| `green-2.log` | **46 passed, 204 warnings in 56.32s** | offscreen；补足 pending 编辑、窄窗和项目生命周期后 46 项全部通过 |
| `owner-gates.log` | **263 passed, 474 warnings in 49.29s** | 并排 owner / 状态 / 显式计算 / tabs / 项目恢复 / 色阶集成；在追加 heatmap cache 修复之前完成 |
| `heatmap-red.log` | **2 failed in 0.87s** | 两个 dtype 均复现不同画布 token 碰撞 |
| `heatmap-green.log` | **11 passed, 206 deselected in 0.88s** | 修复后 dB memo、参考值、手动色阶相关 owner 节点通过 |
| `native/workflow-final.log` | **4 passed, 24 warnings in 15.10s** | 最终核心源码；FFT / 时频 / 阶次 / FRF 各一个真实计算后的 Cocoa 完整流程 |
| `cocoa-navigation.log` | **46 passed, 208 warnings in 68.01s** | 最终核心源码；完整导航合同在 Cocoa 再验收 |
| `final-boundaries.log` | **1 failed, 400 passed, 2 warnings in 11.12s** | 唯一失败是新增 hint 超出 18 单位长度上限；其他 owner / boundary 全部通过 |
| `hints-final.log` | **49 passed in 0.83s** | 仅缩短该 hint 后，完整 hint owner 复验通过；没有为文案重复运行其他 400 项 |

`green-1.log` 中两项失败来自 2+2 布局将非活动 tab 收入 overflow 后，探针仍直接点击隐藏标签。已让探针按实际可见性使用真实 overflow 菜单，没有为探针调整产品布局。

### 3.1 自动化覆盖范围

新增 46 项覆盖四模块的 1+1 / 1+2 / 2+1 / 2+2、右侧第二 pane 聚焦、重复点 host、A→B→C→B→A、非活动 host 开始并排、peer 自有关系与反向关系、直接 manager 激活、未提交 peer 输入、改色/改名/重排/删除/结束、切模块、保存重开、DPR 1/2 半色色块像素与真实 overflow 点击。

快捷键覆盖的是生产快捷键连接的 `_switch_view_for_active_section()` dispatcher，**未单独证明操作系统真实键盘事件投递**。普通标签、图面与 overflow 使用 QTest 的真实 widget 点击。

263 项 owner 组包含：

```text
tests/ui/test_analysis_view_comparison.py
tests/ui/test_analysis_view_comparison_regressions.py
tests/ui/test_analysis_comparison_state_contract.py
tests/ui/test_analysis_explicit_refresh_contract.py
tests/ui/test_analysis_comparison_tabs.py
tests/ui/test_view_tabbar.py
tests/ui/test_view_tabbar_mount.py
tests/ui/test_project_session.py::test_project_restores_analysis_comparison_by_view_id
tests/ui/test_heatmap_color_state_integration.py::test_comparison_focus_rebind_and_exit_keep_each_owners_levels
tests/ui/test_heatmap_color_state_integration.py::test_manual_color_request_survives_twenty_view_roundtrips
```

最后 boundary 组包含：

```text
tests/ui/test_pg_heatmap_canvas.py
tests/ui/test_pg_canvas_backref_invariants.py
tests/ui/test_main_window_state_ownership.py
tests/ui/test_no_lambda_signal_connections.py
tests/ui/test_import_boundaries.py
tests/ui/test_hints.py
tests/ui/test_quickref.py
tests/test_help_content.py
tests/test_project_io_analysis_views.py
```

offscreen 命令统一使用 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`，测试使用项目 QSettings 隔离与 Qt 清理 fixtures。Cocoa 进程使用 `QT_QPA_PLATFORM=cocoa`，同样隔离设置。

### 3.2 实际计算后的 Cocoa 流程

使用真实 MainWindow、Fusion、生产 QSS / 中文字体、两份合成来源 CSV，分别完成三个 View 的实际计算，再执行 **1+2 → 2 → 3 → 2 → 1+2 → 右侧图面聚焦 → 窄窗菜单打开 2**。每一步检查 active/current/marker、peer 生命周期、持久半色，比较保存的完整结果数组 hash；计算后启用 spy，导航期间 DSP 调用数为 0。

FFT 比较 canvas 保留的完整 `_entries`，FRF 比较 transfer，时频/阶次比较实际显示 dB 矩阵。最初 FFT 探针比较抽稀后的 PlotDataItem，画布宽度改变产生 500/1250 点差异；这不是产品缺陷，已纠正验证口径。时频矩阵串图则是真实缓存缺陷，已用正式双画布回归保护。

证据位于 `native/`：各模块 `*-0-View 1.png` 到 `*-4-View 1.png`、`*-focus-peer.png`、`*-narrow-B.png` 及各模块 JSON 状态序列。已人工查看时频 View 2、View 3、右侧聚焦截图，确认单页布局、持续半色和独立焦点条。截图来自本次启动的 Cocoa 测试窗口，不是用户先前运行进程的截图。

手动色阶、范围、游标、后台结果归属主要由既有 owner / regression 测试提供证据；没有把它们全部声称为原项目逐项人工验收。

## 4. 范围与剩余门禁

- 初始范围保存在 `status-before.txt` / `preexisting.patch`；最终源码指纹保存在 `source-final.json` / `source-after.json`。最后 boundary 后仅修改短 hint 文案并复验，其他记录的 Python 源码与测试指纹不变。
- 文档路径与引用、`git diff --check` 已检查。两条可复用 lesson 已落盘：`comparison-tabs-project-remembered-relations`、`result-cache-tokens-must-be-unique-across-canvases`；lessons 状态 `lesson_required: False`。
- **原用户 `.tlproj`：UNKNOWN**，本轮未获得项目路径；合成来源可证明交互及缓存回归，不覆盖该项目独有状态。
- **用户原运行包 / fresh Windows Full、Lite frozen：UNKNOWN**；未重启用户原进程，未构建或发布安装包。
- 本轮没有修改数值分析算法、项目格式、版本号或 QSS。当前源码重启后生效；已运行的旧进程不会自动加载这些修改。

## 5. 后续 8.4.4 提交前验证（2026-10-12）

用户随后授权将版本更新为 8.4.4 并 commit / push。本节记录该发布提交的验证，前文“未提交、未改版本”描述的是修复完成时的状态。

- 同步应用元数据、README/current baseline、主帮助与六份指南、用户指南、Windows Full/Lite/Modular 构建默认版本及 launcher，更新现有版本合同测试；更新记录日期沿用本次准备开始的 2026-10-11。
- 提交范围为 View 修复、回归、相关文档及 8.4.4 发布面。此前未提交的 Nm 默认参考值、UNC 构建修复和 8.4.3 更新草稿保留在工作区；共享文件按内容暂存，不混入这些改动。
- 从暂存区导出独立快照，核对其文件与 Git index 一致后验证。新进程 release contracts：**90 passed, 12 skipped in 1.36s**；新进程 View regressions：**363 passed, 310 warnings in 80.42s**。
- release contracts 包含 help content、Windows build script、packaging imports、help browser open，以及 project session 的版本常量/窗口标题节点。View regressions 包含新增 navigation contract、analysis view comparison、heatmap canvas、hints、quickref，以及 project session 的按 ID 恢复并排节点。
- 最初包含整份 project session 的组合运行进入 UI 阶段后明显变慢，被主动中断，退出码 143，标为 **UNVERIFIED**；中断过程的 Qt 异常记录不归为产品回归，也不从已完成进度推断整组通过。上面两个独立新进程提供最终相关门禁，未宣称整份 project session 或 full suite 通过。
- 浏览器检查暂存快照的主帮助封面及更新历史，确认 8.4.4、日期、三个修复条目正常显示。`git diff --cached --check` 通过；原用户项目与 Windows frozen 验收边界维持前文状态。
- 本地证据：`.state/release-8.4.4/` 下的 `manifest.json`、`staged.patch`、`release-contracts.log`、`view-regressions.log` 与被中断的 `staged-focused.log`。验证用临时源码快照用后清理，不提交生成产物。
