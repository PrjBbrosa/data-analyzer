# 分析参数面精简实施计划

日期：2026-08-09

状态：**已实施；真机前台视觉验收待单独执行**

Spec：`docs/analyzer/specs/2026-08-09-analysis-parameter-surface-simplification-spec.md`

被修订的 spec：`docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`
（§5.3 / §5.4 / §6.3 / §6.4 / §8.2 / §9.1 / §9.2 / §10.2 / §17 已加定版说明）

前置：`docs/analyzer/plans/2026-08-09-frf-interaction-and-axis-polish-implementation.md`
已 Implemented；其 D1 为本次要移除的三个控件写了 tooltip，实施时一并回收对应文案条目。

## 0. 动手前

- 记下当前基线，别把既有失败算到本次改动头上。CLAUDE.md 记录的基线（`3fd691a8` / v7.9.5）：
  主体 **5258 passed / 9 skipped / 0 failed**，`tests/acquisition_ui` 单独 **355 passed**。
  本次改动前先复跑一次确认仍然如此。
- 工作区目前有 Codex 的在途改动（36 项 modified + 若干 untracked）。开工前后各做一次
  `git status` 对账；测试红了先分清是"提交态"还是"在途态"。
- 全量必须分两条命令跑（`--ignore=tests/acquisition_ui` + 单独跑该目录），否则会在
  acquisition_ui 段 segfault。

## 1. 任务

### Task 1 — 守卫测试先行（红）

新增 `tests/ui/test_parameter_surface_simplification.py`，覆盖 spec §7 的 A1–A4、A10：

- `FrfContextual` 不再有 `chk_periodic` / `chk_detrend` / `combo_range_mode`；
- `FftTimeContextual` 不再有 `chk_remove_mean`；
- `_METHOD_FIELDS["frf"]` 不含 `periodic_window` / `detrend`，`["fft_time"]` 不含
  `remove_mean`；`_labels` 中三个键一并消失；
- `FrfContextual.compute_params()` / `_collect_preset()` 恒含
  `periodic_window=True, detrend="constant"`；`FftTimeContextual.get_params()` /
  `_collect_preset()` 恒含 `remove_mean=True`（预设切换、项目恢复后仍然如此）；
- `PaneState` 实例化后 `source_time_view_id` 恒为 `None`；`FrfMixin` 不再定义
  `_frf_requested_range` / `_on_frf_source_time_xrange_changed` /
  `_invalidate_frf_time_view_link`。

同时新增 `tests/ui/test_frf_time_range_surface.py` 覆盖 A6–A8，其中 A7 是 spec §3.2 三条
背离的**回归守卫**，必须逐条断言"屏幕上的起止值 == 实际参与计算的范围"：

```text
不勾选            → pane.time_range is None
勾选 + 手填       → pane.time_range == top.range_values()
勾选 + 最大        → pane.time_range == 数据整段范围
点 取时域范围      → top.range_values() == 时域 committed visible range 且已勾选
点 取时域范围 后再缩放时域 → pane.time_range 不变，且 pane 不被标 stale
custom-X 时域 View → 取时域范围 按钮 disabled，tooltip 为 spec §9.2 的原句
```

### Task 2 — 移除三个开关（单次 + 批处理）

单次：

- `ui/inspector_sections/contextual_frf.py`：删 `chk_periodic`、`chk_detrend` 及其
  `compute_form.addRow`、`_wire` 里的 toggled 连接、`_FRF_TOOLTIPS` 的 `periodic` /
  `detrend` 两条；`_collect_preset` / `_apply_preset` / compute params 出口改为写死常量
  （**不要**改成"读一个隐藏 widget"——隐藏控件是第二真相源）；
- `ui/inspector_sections/contextual_fft_time.py`：删 `chk_remove_mean` 及其 addRow、
  `_on_preset_param_changed` 连接；两处参数出口（`get_params()`、`_collect_preset()`）
  改为写死 `remove_mean=True`，两处恢复分支（`apply_params()`、`_apply_preset_values()`
  里的 `if 'remove_mean' in d`）改为静默忽略。

批处理：

- `ui/drawers/batch/method_buttons.py`：`_METHOD_FIELDS` 的 `frf` 去 `periodic_window` /
  `detrend`、`fft_time` 去 `remove_mean`；删 `_w_periodic_window` / `_w_detrend` /
  `_w_remove_mean` 三个 widget、`_widgets` 登记、`_labels` 三个键、
  `params()` 与 `set_params()` 的对应分支。`set_params()` 收到这三个键时**静默忽略**
  （老预设/老配方会带着它们进来，不能 KeyError）。

**不改**：`signal/frf.py`、`signal/spectrogram.py`、`batch_recipe.py`、
`batch_compute.py`、`analysis_presets.py`（预设继续显式携带这三个字段值）。

### Task 3 — FRF 时间范围收敛

`ui/inspector_sections/contextual_frf.py`：

- 删 `combo_range_mode`、`range_mode_changed` 信号、`range_mode()` / `set_range_mode()`；
- `time_range_layout()` 保留（共享组仍嵌在信号映射卡里）。

`ui/inspector_sections/persistent_top.py`：

- 新增 `btn_range_from_time`（`取时域范围`）与信号 `range_from_time_requested`，放进
  `_chk_range_host` 那一行、`最大` 旁边；
- 新增 `set_range_from_time_visible(bool)`，由 `inspector._place_range_group_for_mode`
  在 mode == `'frf'` 时置 True、其余置 False。

`ui/main_window/_frf_mixin.py`：

- 删 `_frf_requested_range`、`_capture_frf_time_range`、`_apply_frf_time_range`、
  `_on_frf_range_mode_changed`、`_on_frf_manual_time_range_edited`、
  `_on_frf_source_time_xrange_changed`、`_invalidate_frf_time_view_link`；
- `_frf_prepare_pair_samples` 改为调用 `_pane_time_range_for('frf')`（与其它 section 同源）；
- 新增 `_on_frf_range_from_time_requested()`：取
  `_current_physical_time_view_range()` 的范围 → `top.set_range_from_span(*rng)`；
  custom-X 时按钮本就 disabled，这里保留一次防御性 `FrfPreflightError` 处理。

`ui/main_window/_analysis_mixin.py`：

- `_capture_analysis_time_range` / `_apply_analysis_time_range` 里的
  `if section == 'frf':` 特判删除，FRF 落到通用分支。

`ui/main_window/window.py`：

- 删 `frf_ctx.range_mode_changed` 与 `spin_start/spin_end.valueChanged` 到
  `_on_frf_manual_time_range_edited` 的三处连接、`canvas_time.xrange_changed` 上那条
  `_on_frf_source_time_xrange_changed` lambda；
- 接 `top.range_from_time_requested`。

**顺带修掉的老坑**：`_on_time_range_enabled_changed`（`window.py:1834`）在非 time mode 下
会用时域画布 xlim 覆盖 spinbox。收敛后 FRF 与其它 section 走同一条路，该覆盖对 FRF 依然
不该发生——在该函数入口加 `if self.chart_stack.current_mode() != 'time': 只做 capture 与
per-mode 记录，不做 xlim 回填`，并为此单独加一条测试。这条修复对 FFT/时频/阶次同样生效
（它们今天有一样的问题，只是没人报）。

### Task 4 — 项目/预设兼容

- `ui/analysis_view_state.py` 或对应 `from_dict`：`params["range_mode"]` 按 spec §4 D4 折叠
  表转换，转换后不再写回；未知值按 `full`；
- `PaneState.source_time_view_id` 字段保留（读），`to_dict` 不再写；
- `tests/ui/test_project_session.py` 加一条：schema 里带 `range_mode=current_time` +
  `source_time_view_id` 的老工程，打开后勾选态与起止秒正确，且再次保存不含这两个键。

### Task 5 — 文档与帮助页

- `mf4_analyzer/help/frf-guide.html`：删"分析范围"三选说明与周期窗/去趋势条目，改写为
  `分析时间` + `取时域范围`；
- `mf4_analyzer/help/fft-guide.html` / 时频相关章节：删"去均值"开关说明；
- `mf4_analyzer/help/TraceLab-使用说明.html`：同步 changelog 新增条目；
- `docs/analyzer/user-guide/user-guide.html`：同步；
- **不动** `docs/analyzer/specs|plans|acquisition/` 下的其它历史文档。

版本号是否要升由收尾时统一判断；若升，按 CLAUDE.md 的扇出面清单同步 7 处 + 3 个测试契约。

### Task 6 — 验证

Focused：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_parameter_surface_simplification.py tests/ui/test_frf_time_range_surface.py tests/ui/test_frf_main_window.py tests/ui/test_project_session.py tests/test_batch_recipe.py tests/test_batch_runner.py -q
```

架构 gates（必须全绿，红了修代码不放宽护栏）：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_state_ownership.py tests/ui/test_import_boundaries.py tests/test_signal_no_gui_import.py tests/test_batch_render_import_boundary.py tests/test_help_content.py -q
```

> 状态所有权棘轮是 **shrink-only**：本次删掉 `_frf_mixin` 的多个写点后，白名单只会更小，
> 不允许出现新增项。

全量（两条命令）：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest --ignore=tests/acquisition_ui -q
```

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui -q
```

真机视觉验收（spec §7 A11，**不可用 offscreen 代替**）：真实 macOS 前台启动 TraceLab，
截图 FRF 与时频 Inspector，确认无残留空行/错位，`取时域范围` 与 `最大` 同排对齐，
并按"两侧渲染对比 + 哈希"的既有做法留证据，不要把人工清单丢给用户。

## 2. 明确不做

- 不改任何数值算法与窗函数生成；
- 不删 DTO / 配方 / 持久化字段（只删 UI 入口）；
- 不新增"高级参数"折叠区；
- 不动 FFT 1D 与阶次已有的硬编码；
- 不顺手重构共享 `分析时间` 组的其它行为（`最大` 按钮、FFT 画布拖选回填保持原样）；
- 不把 offscreen 绿测写成视觉验收通过。

## 3. 建议提交切分

1. `test(ui): pin analysis parameter surface and frf time range contracts`（红）
2. `refactor(ui): drop periodic-window and detrend switches from analysis panels`
3. `refactor(frf): fold analysis range into the shared time range group`
4. `fix(ui): stop non-time modes from overwriting the range spinboxes`
5. `docs(help): describe the simplified analysis parameter surface`

每个提交都必须可运行，且不得带入工作区中与本计划无关的 Codex 在途改动。

## 4. 执行记录（2026-08-09）

- Task 1–4 已完成：三个 UI 开关及 FRF 的旧范围链接均已移除；FRF 使用共享
  `分析时间` 组，`取时域范围` 只做一次性填充。老项目会迁移为显式秒范围，二次保存
  不再写 `range_mode` 或 `source_time_view_id`。
- Task 5 已完成：FRF 指南、主使用说明、用户指南、提示和快速参考已同步；未做版本号
  升级，因为这不是一次发布请求，应用版本仍以 `app_meta.py` 的 `v7.9.5` 为准。
- A1–A10 的 offscreen/自动化验证已通过；主套件
  `5824 passed, 9 skipped, 3 deselected`，采集 UI 独立套件 `355 passed`。
- A11 未执行：尚未在真实 macOS 前台 TraceLab 中采集 FRF/时频 Inspector 的像素或截图
  证据。offscreen 测试不能代替该门禁。
