# 分析时间范围意图执行 Plan

日期：2026-09-09
状态：仅完成设计文档，未实施产品改动。
行为合同：[Spec](../specs/2026-09-09-analysis-time-range-intent-spec.md)

## 1. 执行约束

单执行者顺序推进，不要求代理。保留其他工作区修改，不修改 Batch 或数值算法，不自动提交/推送。
本次文档仅查完整性、引用、任务映射及 `git diff --check`；未改可执行行为，无需运行测试。
实现时每步先 focused 红测再修复。统一命令：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <files> -q
```

## 2. 步骤 0：冻结受影响入口与失败场景

Owner：执行者，只读；证据置 `.state/analysis-time-range-intent/`。

- 记录 HEAD、owner 文件 diff 与活动 pytest 进程；不运行全套 baseline。
- 核对 Spec §2、§4 的来源解析、共享时间框、四种 compute 入口、项目恢复和“全部”路径。
- 定位四种分析的实际计算目标列表；尤其单次点击会计算多个 pane 的路径，不能把 focused pane 等同全部目标。
- baseline 仅 `tests/ui/test_analysis_time_range_confirm.py`、`tests/ui/test_analysis_multiview_integration.py` 中时间范围相关用例。
- 用两个不同长度 FileData 构造截图同类复现，不需要原用户文件。确认没有用户编辑也会被旧值比较逻辑认作 draft。

Gate：所有自动写入与用户提交入口列入调用表。新增 explicit span 工具不在本轮；发现额外明确取范围命令时归为直接启用并补调用表。

## 3. 步骤 1：范围状态与来源事实 owner

Owner：拟新增 `mf4_analyzer/ui/main_window/analysis_time_range.py`；`analysis_context.py` 持有一个控制器。`PaneState.time_range` 继续持有 enabled；不新增 View schema。

先建 `tests/ui/test_analysis_time_range_intent.py`，覆盖 full/draft/enabled、来源签名、关闭清理、不可用/无效状态、显示量化容差（R3/R6/R7/R9）。控制器使用数据/回调依赖，不 import MainWindow，不保存 Qt widget。
接入原始时间范围事实：FFT/时频真实 signal axis，FFT 叠加逐源范围及展示外包络；FRF 使用未被 requested range 裁剪的配对来源；Order 使用信号与现有 RPM 可用性检查。完整准备与轻量范围读取保持一个来源 owner，不复制算法。

Focused：新文件、`tests/ui/test_analysis_context.py`、`tests/ui/test_analysis_source_scope.py`。
Boundary：`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`。
Gate：未建立新的跨 mixin 写状态；没有从旧画布或全部文件范围推断当前分析 full。

## 4. 步骤 2：共享控件改为明确事件和静默投影

Owner：`ui/inspector_sections/persistent_top.py`，`ui/main_window/window.py` 范围入口及 `_analysis_mixin.py` 的范围捕获/应用。

- 用户提交编辑独立发信号；程序 set_range_values/set_range_limits、模式搬运、View 恢复不发手动编辑事件。核对 CompactDoubleSpinBox 的编辑提交行为，防止仅失焦生成草稿。
- 为每次用户提交核验当前 pane/source signature；无效输入禁止计算，不能回退旧值。计算按钮按下前先提交编辑，解决 editingFinished 与 clicked 的顺序。
- 切换分析模式/窗格时投影 controller 状态和当前源 full；禁用当前 `_on_fft_preview_range_changed` 的时间框/计算范围回写，但保留相机/预览自身行为。
- 时域 `_sync_time_range_inputs_from_visible_xlim` 仍服务时域；不得污染非活动分析 pane。普通分析画布缩放无论勾选与否均不改变计算范围。
- 分析页“全部”和取消勾选执行明确 full 转换；时域“全部”保持旧语义。FRF `set_range_from_span` 调用保留明确启用入口。

Focused：新 intent tests、`tests/ui/test_analysis_multiview_integration.py` 范围/焦点用例、`tests/ui/test_frf_time_range_surface.py`、`tests/ui/test_xrange_debounce.py`。
Gate：R1/R2/R3/R5/R6。新增跨页事件测试证明视口改变既不触发提示，也不改变已有 enabled 计算窗口。

## 5. 步骤 3：来源生命周期、恢复与范围复核

Owner：`_analysis_mixin.py` 的 source capture/apply、`_frf_mixin.py` 的 pair/source owner、必要的 FFT/时频/阶次来源入口；`analysis_context.py`/新 controller 统一状态规则。

- 使用 pane 实际角色和 `(fid, channel)` 签名；来源变化清未启用草稿。自动重绘、相同来源重排不当作换源。
- 已启用范围保留原请求，越界记需复核，不能 silent clamp。不要为了编辑越界值把输入框先限制到新 source bounds 然后把夹值当用户编辑。
- 删除 View、pane 重排/移除、关闭文件、清项目、teardown 清理对应草稿；复制 View 不复制草稿。活动窗格转换前提交未完成的合法编辑至原窗格，随后投影新窗格。
- 恢复 None 即 full；tuple 恢复后验证。不序列化草稿或运行期 signature；旧非法 tuple 诊断不丢失，必要时在解析处保留错误事实供恢复反馈，不引入新 schema。

Focused：`tests/ui/test_analysis_view_state.py`、`tests/test_project_io_analysis_views.py`、`tests/ui/test_analysis_source_scope.py`、`tests/ui/test_analysis_multiview_integration.py` 和新 intent tests。
Boundary：`tests/ui/test_main_window_state_ownership.py`。
Gate：R6/R7/R10；UI/项目/缓存不存在第二份“生效范围”。若 source scope 没有发生改变不得清用户草稿。

## 6. 步骤 4：真实意图提示与计算事务

Owner：`_analysis_mixin.py::_offer_analysis_time_range_before_compute` / `_ask_use_local_time_range`，四种方法 `do_fft` / `do_fft_time` / `do_order_time` / `do_frf` 的 preflight 衔接。

- 将 `_analysis_time_range_draft_is_local` 的数值启发式替换为 controller 查询，删掉 `_TIME_RANGE_DRAFT_LOCAL_TOL` 的旧 1% 语义；可保留兼容 facade，但不能再读公共 spinbox 猜草稿。
- 明确列出本次所有计算目标，先范围预检和必要的汇总确认，再统一 capture/submit。提示期间来源变化使本次启动失效。
- 用选定范围应用并清草稿；用全时段清冲突窗格状态与旧显示值；取消无任何计算/缓存副作用。默认按钮取消，full 使用正常按钮角色。
- 来源越界复核按 Spec §6；数据格式/对齐错误仍走现有错误路径，不能被 full 选择绕过。
- 自动 restore recompute 不读 draft、不弹框；无效 enabled 阻止对应任务，保留原因。

必须改写旧断言：

| 旧测试/行为 | 新预期 |
| --- | --- |
| `test_draft_is_local_when_unchecked_subset` | 程序设子区间不再足以提示；必须模拟真实用户编辑 |
| `test_offer_full_keeps_unchecked` | 还要断言时间框回 full、草稿清除、再次计算不问 |
| confirm 文件内直接 `set_range_values` 构造用户草稿 | 改用真实提交或 controller 的明确用户事件；保留程序回写不生成草稿的反例 |
| FFT preview zoom 更新 pane range/时间框的旧范围测试 | 改成仅视口变化；已启用范围同样保持 |
| 分析“全部”只看图不解除 enabled 的断言 | 改为回 full；时域对应断言保留 |

Focused：`tests/ui/test_analysis_time_range_confirm.py`、新 intent tests、`tests/ui/test_analysis_multiview_integration.py`、`tests/ui/test_frf_main_window.py` 中范围/preflight 用例。
Gate：R4/R8/R11，含多个 pane 的零部分提交、源变更期间拒绝旧确认、未聚焦 pane 不使用共享编辑框。验证已有有效参数/缓存 key 仍消费 `pane.time_range`，不把草稿值塞入 worker。

## 7. 步骤 5：提示与帮助、实际界面验证

Owner：`persistent_top.py` 的轻量状态呈现、`ui/hints.py`、`ui/quickref.py`，当前帮助中受影响文案。只在必要时局部调整样式。

- 按模式说明“全部”；分析页明确“缩放只查看、手动时间待启用、取消勾选用全时段”。遵守 hints 宽度限制，不堆长句。
- 状态说明使用预留空间，切换 full/draft/error 不推动 Inspector 内容跳变；保留现有控件视觉语言。
- Cocoa 新进程用两份不同长度信号复现：未编辑切源无需确认；真实输入未勾选有一次确认；选 full 后不再问；pan/zoom 无影响；View/pane 切换草稿隔离；已启用范围换到短信号时不能静默裁剪。
- 保存前台截图、实际范围/checkbox/controller/submit 次数对照至 `.state/analysis-time-range-intent/`；不关闭用户未保存会话。

Focused：`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`；改当前帮助 HTML 时加 `tests/test_help_content.py` 相关断言。
Boundary：涉及 signal wiring 运行 `tests/ui/test_no_lambda_signal_connections.py`，涉及 QSS 运行 `tests/ui_kit/test_qss_border_shorthand.py`。
Gate：R12；offscreen 仅证明控件行为，不替代前台证据。

## 8. 完成检查

按 Spec R1–R12 记录 pass/partial/UNKNOWN 与证据路径；缺少原截图事件日志单列，不阻塞通用行为修复。
运行受后续修改影响的 focused 和 boundary 后结束，不为“更全面”重复已通过且代码未变的检查。本轮不要求 full suite；如后续升级为发布/跨边界整合，由一个执行者按仓库规则顺序运行。
检查 git scope、`git diff --check`、相关 lessons 状态。草稿来源与静默投影属于可复用规则时更新对应 lesson，不改历史 spec 伪装此前已正确。
