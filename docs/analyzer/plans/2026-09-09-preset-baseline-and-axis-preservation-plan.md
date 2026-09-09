# 预设基准与坐标保留执行 Plan

日期：2026-09-09
状态：文档已完成；产品实现未开始。本次仅文档，不授权扩大到产品代码。
唯一产品合同：[Spec](../specs/2026-09-09-preset-baseline-and-axis-preservation-spec.md)

本次文档修订相对初稿：步骤 0 从「重新摸字段」改为对照 Spec 已冻结的分类表/回写边界做漂移检查；点名必须改写的 reverse-match 旧测试；补齐 schema 9、帮助表面与精确 pytest 命令。前序确认框实现仍是可复用草稿，不是本方案完成证明。

## 1. 执行原则与完成标准

按 Spec A1–A15 收口。保留工作区里无关的 Batch、搜索提示、QSS 等改动；只修改本任务必要片段，不全量覆盖文件。
默认单一执行者顺序完成；本文不要求子代理或并发 full suite。
本轮文档 gate：全文一致性、引用/路径、任务覆盖、`git diff --check`；没有可执行变更，不运行 runtime suite。

实现阶段验证命令（各步骤 focused 套用）::

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <files> -q
```

先 `pgrep -fl pytest`，同一 checkout 不并行第二套。不做全量 baseline。

## 2. 步骤与文件所有权

### 步骤 0：对照冻结证据，确认无漂移

Owner：执行者。不先重构 PresetBar。

Spec 第 5–7、11、14 节已冻结 2026-09-09 工作区证据。本步只确认代码未漂移，不重新发明分类表。

核对清单：

1. 四个 Contextual 的 `_collect_preset` / `_apply_preset` / `apply_params` / `reset_to_defaults` 键集仍与 Spec §5 一致。Order 的 PresetBar `kind` 仍是 `order`，catalog 方法仍是 `order_time`。
2. 回写路径仍是：colorbar → `_on_analysis_levels_dragged`；相机 → `pane.xlim`/`ylim`；二者未打通。
3. 项目外层仍经 `AnalysisViewState.to_dict` 进入 `analysis_views`；顶层 `.tlproj` schema 不必动。
4. Spec §14 列出的旧测试仍存在且仍编码 reverse-match / 二次点击恢复默认。

有漂移：先改 Spec 分类表，再进入步骤 1。需要扩大到相机写 Inspector 时先记录阻塞，不悄悄扩 scope。

Focused（只在怀疑漂移时跑，默认可读代码对照）::

- `tests/ui/test_preset_axis_preservation.py`
- `tests/ui/test_preset_bar_lifecycle.py`
- `tests/ui/test_analysis_view_bridge.py`

Gate：Spec 第 15 节无新的 UNKNOWN；字段表仍能在当前符号上对上。没有确认表不能开始步骤 1。

### 步骤 1：统一有效值差异与基准合同

Owner：执行者。新增 `mf4_analyzer/ui/inspector_sections/preset_state.py`：UI 包内、无 Qt 控件、不 import `MainWindow`。精确文件名可随现有结构调整，但只保留一个分类和归一化实现。
修改 `presets.py` 消费该 owner，不复制第二套 compare 到卡片。
不改变公共 `preset_params_match` 的旧调用语义。

先写 `tests/ui/test_preset_state.py`：A1–A3、A12、A15 的纯计算部分、FRF 无轴、旧别名、空交集不为真、部分 payload、单位兼容、容差、未知键失败闭合。
再实现完整目标意图、基准快照、双 diff flags。

Gate：按钮、卡片、冲突共用结果；不比较缓存/信号/Fs/`nfft_effective`；不把轴别名算进参数；不把 `_collect_preset` 与 `current_params` 混比。

### 步骤 2：View 级来源持久化

Owner：执行者。`analysis_view_state.py`、`analysis_view_bridge.py`。外层 `project_io.py` 只在 `to_dict` 已写入新键时自然搬运；不要在 mixin 里再拆一份基准。

- `_SCHEMA` 8→9；可选 `preset_baseline`；构造位置兼容；旧文件缺字段 = 无基准。
- capture/apply 同步基准；恢复参数时暂停中间高亮，再一次投影最终状态。
- 新 View 清空；复制深拷贝；旧项目仅完整可比匹配才推断；槽改变保留加载快照。
- 禁止把 UI metadata 塞进 DSP params；色点和本次确认选择不落盘。

先增加 A9、A10 测试，再改代码。
同步改写写死 `schema == 8` 的：`tests/ui/test_analysis_view_state.py`、`tests/test_project_io_analysis_views.py`、`tests/ui/test_analysis_source_scope.py`。

Focused：上述文件 + `tests/ui/test_analysis_view_bridge.py`；外层行为变化时加 `tests/ui/test_project_session.py` 中分析 View 保存/加载相关用例。
Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_import_boundaries.py`。
Gate：A/B View、复制、新建、关闭恢复与项目往返证据齐全；无新增跨 mixin 写入。

### 步骤 3：用户应用事务与确认框

Owner：执行者。`presets.py`，必要时只加 Contextual 原子 apply 的薄封装，不把比较逻辑搬回四个面板。

前序 `_confirm_axis_preservation` / `_prepare_user_preset` / `tests/ui/test_preset_axis_preservation.py` 可复用对话框铬和「本次有效」语义，但必须改掉：

- 取消后的 `sync_match()`；
- 保留后因 `params != requested` 再次 reverse-match；
- 二次点击恢复默认。

本步行为：

- 替换全量 reverse-match 认领为基准投影；保存/加载成功才提交新基准。
- 不同槽与相同槽用同一应用路径；一致且槽未变化时无操作。
- 保留/使用预设/取消统一走 Spec 第 10 节，确认前无状态写入。
- 不兼容轴明确提示；无可保留轴时禁用保留；旧预设缺轴字段也安全处理。
- 取消不 resync 到其他槽；失败恢复原状态并保留诊断。
- 菜单：「重置此槽为内置」与「恢复面板默认参数」。
- colorbar 回写后只刷新色点，不认领自定义。

扩展 `tests/ui/test_preset_axis_preservation.py`：A4–A8、A11、A15、零计算发射、失败回滚、取消推荐标识保留。
按 Spec §14 改写 `tests/ui/test_inspector.py` 整簇 reverse-match / 二次点击断言：未匹配 = 无 `applied` 槽，不是槽 4；二次点击 = 重新应用。
Focused：上述 + `tests/ui/test_task6_preset_guard.py` + `tests/ui/test_preset_bar_lifecycle.py`。
Gate：项目/View restore 不弹框；本次选择不被记住；预设存储不因保留轴而改变。

### 步骤 4：纯色点、状态细边框与帮助

Owner：执行者。`presets.py` 按钮/hover card、`mf4_analyzer/ui_kit/style.qss` 局部状态样式、`ui/hints.py`、`ui/quickref.py`。帮助 HTML 仅在现文案与 Spec 冲突时改。

- 内置和自定义基准保持蓝色高亮；7px 圆点与状态项同色，紫左黄右。
- 不更改分析参数/轴快照分组外框颜色；仅状态项细边框有差异色。
- 推荐角标、窄面板、双点、键盘焦点、hover 生命周期、字体回退均检查。基准槽隐藏荐角标。
- 卡片显示不可用基准/更新基准时不制造错误高亮。
- 帮助准确解释基准、颜色、再次点击和两种重置。

Focused：拟新增 `tests/ui/test_preset_difference_render.py`，现有 `tests/ui/test_preset_bar_lifecycle.py`、`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`。改帮助 HTML 时加 `tests/test_help_content.py` 相关断言。
Boundary：`tests/ui_kit/test_qss_border_shorthand.py`、`tests/ui/test_no_lambda_signal_connections.py`。
Cocoa：隔离 QSettings（现成 `tests/ui/conftest.py` autouse；额外探针不得写真实 `MF4Analyzer/DataAnalyzer`）。真实 preset widget 显示后截图，核验按钮内双点、状态边框、确认按钮完整文字；正常和窄面板、100% 和高缩放。证据放 `.state/`，不提交。
Windows：实际 Qt/冻结包另列 gate，无环境则 UNKNOWN，不用 Cocoa 代替。
Gate：A14 及纯色点视觉方向。

### 步骤 5：整合验收与范围审查

Owner：同一执行者，唯一整合 gate owner。

逐条记录 A1–A15 的代码、测试和平台证据；只重跑后续修改影响的 focused tests。
复核所有「不再高亮自定义 / 再次点击恢复默认 / 参数一致即高亮」旧断言与帮助。
运行 `git diff --check`、相关文件 diff 审查；保留其他任务改动。
本计划不默认要求全套 pytest；仅在跨边界问题或发布/合并验收另有要求时扩展，并先记录原因。
若批准全套：先 `pgrep -fl pytest`，记录 `HEAD` 与脏文件范围，main（`--ignore=tests/acquisition_ui`）与 `tests/acquisition_ui` 顺序运行，不并发。相关文件在跑中被改过则结果 `UNVERIFIED`。
最终报告明确：完成条目、剩余 UNKNOWN、真实 Cocoa 与 Windows 的分别状态，不引用旧通过数作本轮验收。

## 3. 风险和针对性门槛

| 风险 | 控制 |
| --- | --- |
| 有效范围以外的值产生假黄点 | 自动轴隐藏值变动测试 |
| 保留坐标后出现假紫点 | legacy alias 与完整目标意图测试；禁止混用 `current_params` |
| 基准被其他 View/全局槽改写 | View 快照持久化和跨 View 试验 |
| 取消对参数无影响但高亮变化 | 将基准、推荐、信号计数纳入取消快照；取消路径零 `sync_match` |
| 颜色提示暗示需重新计算 | 维持既有 compute/display 分流 |
| 单位变化保留旧数值 | Spec §6 矩阵 + 缺字段旧预设案例 |
| 弹窗按钮裁切/推荐角标覆盖色点 | ensurePolished 后测量与 Cocoa 实际截图；基准槽隐藏荐 |
| 现有代码继续强制自定义高亮 | Spec §14 全表改写；审查 `sync_match` / `set_custom_active` |
| colorbar 回写跳槽 | A15；`apply_params` 不再 reverse-match |
| 把相机视口当成面板轴 | Spec §7；步骤 0 漂移检查 |
| 新增 `.connect(lambda` | shrink-only 棘轮；改连接用 `partial` |
| QSS `border:` 打掉 radius | `test_qss_border_shorthand.py` |

## 4. 执行记录（待填写）

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 0 字段/回写/序列化边界 | 文档已冻结；实现前对照 | Spec §5–7、11、14；不以历史推断代替当前符号 |
| 1 差异 owner | 未执行 | — |
| 2 View 基准 | 未执行 | — |
| 3 应用事务 | 未执行 | 仅有前序局部确认框实现 |
| 4 色点/状态样式 | 未执行 | 视觉合同在 Spec §8；仓库无已提交纯色点原型 |
| 5 A1–A15 收口 | 未执行 | — |

文档阶段检查：全文读取、相对链接与现有 owner/test 路径核对、冲突规则搜索、`git diff --check`。
未运行 runtime tests：本轮仅修订 spec/plan，无可执行改动。
