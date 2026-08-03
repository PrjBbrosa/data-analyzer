# 批处理真机验收问题 · 实施计划

- 设计：[2026-08-03-batch-acceptance-followup-design.md](../specs/2026-08-03-batch-acceptance-followup-design.md)
- 前序：[切片导出 + 统计标记](../plans/2026-08-03-batch-heatmap-slice-and-stat-marker-implementation.md)（七阶段已落地、未提交）
- 基线：`main` @ `d60cdea` + 切片特性工作区改动

---

## 0. 动手前

**已知的既有失败**（全部在 detached worktree @ `d60cdea` 上逐条确认过，与本轮无关）：

- `tests/ui/test_split_*`（CLAUDE.md 已记录）
- `tests/ui/test_batch_smoke.py::test_time_analysis_form_fits_288px_after_repeated_dependency_toggles`
- `tests/test_batch_runner.py::test_grouped_interleaved_pairs_regroup_by_canonical_physical_source`
- `tests/test_batch_render_qt.py` 三条：`test_eight_subplot_text_geometry_and_shared_x_contract`、
  `test_subplot_export_draws_before_writing_dpi_metadata_and_contains_ticks`、
  `test_cjk_font_support_and_header_ink_proof`
- `tests/test_batch_render_qt_ssaa.py::test_legend_keeps_its_one_to_one_size_through_the_downscale`
- `tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence`（14 例）

后五组同一个根因：本机 Qt 缺字体，offscreen 渲的图没有任何文字，
凡是断言文字墨迹/几何的用例都会红。
（最初这份清单只列了 3 条，F1 的执行者补全了后两组 —— 别再漏。）

**pytest 必须带 `--basetemp`** —— 默认临时目录在这台机器上有 Windows 权限问题，
不带会伪造出十几条 ERROR：

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest <files> -q --basetemp=C:\Users\hang\AppData\Local\Temp\claude\D--Coding-project-data-analyzer\7d1b30ee-c3ec-44b6-811c-610320304137\scratchpad\pytest-followup
```

**本机看不了图**（Qt 缺字体，offscreen 渲出空白）。所有视觉结论只能靠真机复验。

---

## 阶段 F1 · 左轴宽度回归（P0，独立可交付）

**范围**：`mf4_analyzer/batch_render_qt/_builder.py`（只动 `_slice_alignment_callback`
及它需要的新 helper）、`tests/test_batch_render_qt_heatmap.py`。

1. 新增模块级 helper：按**当前刻度串**用 `QFontMetricsF(chart_font(pt))` 算左轴所需宽度
   （最宽刻度串 + tick 长度 + 轴标题高度 + 内边距），不再读 `axis.width()`。
   `AxisItem` 的 `width()` 依赖只在绘制时更新的 `textWidth`，
   而 `_apply_tick_density` 在 `show_and_settle` 末尾才换刻度 —— 这是 57.4 px 的来源。
2. `align()` 用两轴各自的 `needed` 取 max 再 `setWidth`。
3. 确认 `show_and_settle` 里对齐排在 `_apply_tick_density` **之后**；不是就调整顺序。

**测试**
- 同一份数据，切片开 vs 关，断言主图左轴宽度 **开 ≥ 关**（当前 57.4 < 95.4，会红）
- 人为把刻度串换成更长的再跑一次 `align()`，断言宽度随之增大
- 切片关闭时 PNG 与基线**逐字节相同**（既有回归保护，别破坏）

**先在未修复的代码上验证第一条测试是红的**，否则它没有价值。

```powershell
tests\test_batch_render_qt_heatmap.py tests\test_batch_render_qt.py tests\test_batch_qt_render_parity.py
```

---

## 阶段 F2 · 图例宽度与右侧留白（P1）

**范围**：`_builder.py`（图例卡构造 + `position_legend` + 对齐回调的右侧预留）、
`tests/test_batch_render_qt_heatmap.py`。

1. 图例卡宽度改为按内容量：`QFontMetricsF` 量最宽一行（色块 + 文本 + 内边距）与标题取 max，
   替换硬编码的 `content_width=86.0 * scale`。
2. 右侧预留改成 `max(colorbar 右侧总宽, 图例宽 + 间距)`，**两行同时**按此留白，
   保住 F1 之后的对齐。
3. `position_legend` 里对 `ci.contentsMargins().right()` 做夹取，任何情况下不越界。

**测试**：造一个长标签（如 `f=13500.0 Hz` ×4）→ 断言图例卡右边缘 ≤ 页面右边距，
且两行绘图区左右边界仍然相等（F1 的对齐不被 F2 破坏）。

> F1 与 F2 都改 `_builder.py` 的对齐/图例区域，**必须串行**，不要并行。

---

## 阶段 F3 · 多子来源（P0，A1+A2+A3）

三条同根因，一起做。**这是本轮最有价值的一段**。

### F3.1 选择器（A1）

`mf4_analyzer/ui/drawers/batch/input_panel.py`：
- RPM 选择器改为 `set_partially_available(partial, selectable=self.target_policy() == "available_per_source")`，
  与目标信号同一条策略（设计 D-A1）。

`mf4_analyzer/ui/drawers/batch/signal_picker.py`：
- `available` 为空且 `partial` 非空时，在弹层底部现有 "已选 N · 匹配 M" 那一行附近
  加一行说明 + 一个按钮，按下发一个新信号（如 `relaxPolicyRequested`）。
  **选择器自己不改策略** —— 它不拥有那个状态。

`input_panel.py` 接这个信号，把目标策略切到 `available_per_source` 并 `changed.emit()`。
**不要自动切**（设计 D-A2）：那会改变产出集合，必须是用户点的。

### F3.2 预览代表（A2）

`mf4_analyzer/batch.py`：
- `preview_outputs(self, preset, output_dir, *, source_channels=None)`，
  可选参数，默认 `None` → 行为与现在**完全一致**（保护既有调用方与测试）。
- 给了就选第一个「所有成员通道都在其来源的通道集合里」的组，`ordinal` 用真实序号；
  没有合格组时仍回退 `groups[0]`，并在 `BatchRepresentativeGroup` 上带
  `channel_available: bool = True`（新增字段，默认 True 保持向后兼容）。

`sheet.py`：
- `_on_preview_clicked` 传入 `source_channels`（从 `_input_panel._file_list.per_file_channel_sets()`
  与来源 key 组装）。
- `channel_available=False` → toast 文案改成具体原因（设计 D-A4）。

### F3.3 机器串（A3）

`mf4_analyzer/batch_grouping.py`：
- 从 `batch_render_qt/_page.py` 把 `_MACHINE_GROUP_IDENTITIES` /
  `_MACHINE_GROUP_PREFIXES` / `_is_human_group` **移过来**（batch_grouping 是 GUI-free 的）。
- `_source_display_name` 用 `_is_human_group` 替换 `!= "default"`。

`batch_render_qt/_page.py`：
- 改为 `from ..batch_grouping import is_human_group`（公开名去掉下划线），删本地副本。
- 注意 `renderer_import_policy.py` 守着渲染栈的 import 边界，
  `batch_grouping` 是 GUI-free 的，方向正确；跑一次 `test_batch_render_import_boundary.py` 确认。

**测试**
- `preview_outputs` 不传 `source_channels` → 结果与改动前完全一致
- 传了且第一组无该通道 → 选中的组含该通道，`ordinal` 正确
- 都不含 → `channel_available=False`
- `_source_display_name` 滤掉 `unresolved-source:` / `file_id:` / `default`
- **组显示名的变化不改变任何输出文件名**（`identity.stem` 不受影响）——单独一条

```powershell
tests\test_batch_grouping_display_name.py tests\test_batch_output.py tests\test_batch_runner.py tests\test_batch_render_import_boundary.py tests\ui\test_batch_input_panel.py tests\ui\test_batch_signal_picker.py
```

---

## 阶段 F4 · 图内统计（P1）

**范围**：`mf4_analyzer/batch_statistics.py`、`batch_render_qt/_builder.py`
（只动 `_add_time_statistics` 的标题行）、
`ui/drawers/batch/chart_statistics_panel.py`、对应测试。

1. **标题写明模式**（D-D1）。`_add_time_statistics` 现在只显示实际跨度，
   自动与自定义长得一样。改成：
   - 自动：`图内统计  全时段 · 实际 -95.86 ~ 95.51 mm`
   - 自定义：`图内统计  设定 -80 ~ 80 mm · 实际 -79.97 ~ 79.97 mm`

   渲染器需要拿到「请求区间」——它已经从 `self.params["chart_statistics"]` 读 metrics，
   同一处再读 `range_mode` / `x_min` / `x_max` 即可，不用新管道。

2. **堵死静默降级**（D-D2）。`_configuration` 增加「请求 custom 但边界不可用」状态；
   `plan_chart_statistics` 为该 panel 产出 `chart_statistics.custom_range_unavailable`
   诊断且**不出统计行**，与既有 `multiple_x_reversals` 同样 fail-closed。

3. **`apply_params` 不再静默重置区间**（D-D3）。缺 `chart_statistics` 键时
   只把启用态置否，**保留 spinbox 里的数值**。

**测试**
- 自动 / 自定义两种模式的标题文案不同，且都含实际跨度
- custom + 边界为 `None` → 有诊断、无统计行（当前是静默全程，会红）
- `apply_params({})` 之后 `x_min`/`x_max` 数值不变
- 既有的 `multiple_x_reversals` / `multiple_hysteresis_overlay` 行为不变

```powershell
tests\test_batch_statistics.py tests\ui\test_batch_chart_statistics.py tests\test_batch_render_qt.py
```

---

## 阶段 F5 · 移除批处理手动 RPM（P2）

**范围**：`method_buttons.py`、`batch.py`、`batch_validation.py`、`batch_recipe.py`、
`sheet.py`、对应测试。

按设计 §C1 的表逐处清理。**唯一需要动脑的是 D-C1**：

两个字段**不能**直接从 `METHOD_PARAM_FIELDS` 删掉 —— 那样它们会掉出
`KNOWN_PARAM_FIELDS`，被「未知字段原样保留」规则留在 params 里，
而 runner 已不再读它们，变成静默的行为改变。

做法：新增 `_RETIRED_PARAM_FIELDS = frozenset({"rpm_mode", "manual_rpm"})`，
并进 `KNOWN_PARAM_FIELDS`；`normalize_batch_params` 对 `order_time` 无条件 `pop`；
被丢弃的是 `rpm_mode="manual"` 时追加迁移警告，措辞对齐
`_legacy_image_format_warning`：

```
旧预设的手动 RPM 已移除；批处理阶次分析需要指定 RPM 通道。
```

**测试**
- 面板上没有手动 RPM 控件
- 旧 recipe 带 `rpm_mode="manual", manual_rpm=1000` → 归一化后两个键都不在，
  且带迁移警告；fingerprint 与不带这两个键时**相同**
- 无 RPM 通道时仍被既有的「rpm channel is required」拦住

单次分析侧的 RPM 控件**不动** —— 确认 `inspector_sections/` 下没被波及。

---

## 阶段 F6 · 阶次窗函数一致化 + UI 清理（P2）

### F6.1 窗函数（C2）

`mf4_analyzer/analysis_presets.py`：给 `order_time` 三个预设补 `window`——
`torque: "flattop"`、`vibration: "hanning"`、`transient: "hanning"`，
与 `fft` / `fft_time` 一一对齐；同时改掉那条已经过时的注释
（"intentionally do not declare a window"）。

可行性已确认：COT 的窗走 `get_analysis_window`（`order_cot.py:147`），
`fft.py` 支持 flattop，无 scipy 依赖。

**影响要在测试里写明**：`analysis_presets` 由单次分析与批处理共用，
所以单次分析的阶次「频率」预设也会从 hanning 变成 flattop。这是本条的目的。
`window` 本就在 `METHOD_PARAM_FIELDS["order_time"]` 里，
应用该预设后 fingerprint 会变 → 已跑过的阶次输出在 resume 下判为过期，属预期。

### F6.2 UI 清理（C3 / C4）

- `analysis_panel.py`：删掉 `_preset_source_note` 控件本身
  （不要只清空文本，空 QLabel 在紧凑布局里仍占高度）。
- `preview_dialog.py`：`setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)`。
  顺手 grep 仓库里其他自建 `QDialog`，一并处理，别只修一个。

**测试**
- 阶次三个预设的 `window` 值正确；应用「频率」后面板窗函数为 flattop
- `analysis_panel` 里不再有该 note 控件
- 预览对话框的 `windowFlags()` 不含 `WindowContextHelpButtonHint`

```powershell
tests\test_analysis_presets.py tests\ui\test_batch_method_buttons.py tests\ui\test_batch_smoke.py tests\ui\test_batch_compact_contract.py
```

---

## 阶段 F7 · 切片可读性（P2，必须真机迭代）

**范围**：`batch_render_qt/_palette.py`、`_builder.py`（标记线与曲线线宽）。

1. 两套色系按设计 D-B4 重挑（暖 `#dc2626 #ea580c #a16207 #be185d`、
   冷 `#2563eb #0891b2 #4338ca #0f766e`）。
2. 标记线 2.0/3.6 → **2.6 px 彩线 + 5.2 px 白衬**（D-B5）。
3. 曲线数 ≥ 3 时线宽 ×0.85（D-B6）。不要用透明度——白底上会变灰。

**这一阶段的验收只能在真机做**：本机 Qt 缺字体，offscreen 渲的是空白图。
先按上面的数值改，出一张真机图再决定是否继续调。
测试只能守「颜色取自新常量」「线宽随曲线数变化」这类结构性断言。

---

## 串行 / 并行

| 波次 | 阶段 | 可并行？ |
| --- | --- | --- |
| 1 | **F1** | 单独跑 —— F2/F7 都改 `_builder.py` 同一区域 |
| 2 | **F3**（多子来源）+ **F5**（手动 RPM） | 文件集不重叠：`input_panel/signal_picker/batch_grouping/_page` vs `method_buttons/batch_validation/batch_recipe`。**但两者都碰 `batch.py` 与 `sheet.py`** → 仍需串行或明确分区 |
| 3 | **F2** | 依赖 F1 的对齐结果 |
| 4 | **F4**（统计）+ **F6**（预设/UI 清理） | 文件集不重叠 |
| 5 | **F7** | 依赖 F2 的图例宽度，且需真机图 |

> `batch.py` 与 `sheet.py` 在 F3/F5 里都会被碰。若并行，必须把
> `batch.py` 的 `preview_outputs`（F3）与 `_rpm_values`/`rpm_source`（F5）
> 明确划给不同 agent 并写清行号范围；否则**直接串行更省事**。

---

## 收尾

全量套件约 4600 条 / 近 20 分钟：

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest -q --basetemp=C:\Users\hang\AppData\Local\Temp\claude\D--Coding-project-data-analyzer\7d1b30ee-c3ec-44b6-811c-610320304137\scratchpad\pytest-full
```

**真机复验清单**（本机做不了，必须在有字体的环境跑）：

1. 切片图：左轴标题不再压刻度；图例完整不裁；标记线在深底/亮区都能读出颜色；
   三条曲线两两可辨
2. colorbar 标题是否仍压住色标刻度 —— 若仍在，说明是既有缺陷，**单独立项**
3. 多子来源文件：「每来源可用」下目标信号与 RPM 都能选；预览出图
4. 阶次「频率」预设 → 窗函数显示 flattop
5. 图内统计卡标题分得清自动/自定义
6. 各存一份到 `docs/analyzer/reviews/` 作为验收证据

---

## 风险

| 风险 | 应对 |
| --- | --- |
| F1 改完 F2 的图例又把对齐撑坏 | F2 的右侧预留必须**两行同时**加，且 F2 的测试要同时断言「图例不越界」与「两行边界仍相等」 |
| F3.3 移动 `_is_human_group` 触碰渲染栈 import 边界 | `batch_grouping` 是 GUI-free 的，方向正确；跑 `test_batch_render_import_boundary.py` 守住 |
| F3.3 改变组显示名，波及输出文件名 | 输出名走 `identity.stem`，与 `display_name` 无关；单独一条测试锁死 |
| F5 删字段导致旧 recipe 静默变行为 | `_RETIRED_PARAM_FIELDS` + 迁移警告（D-C1），测试覆盖 fingerprint 不变性 |
| F6.1 改变单次分析的既有行为 | 这是刻意的；在发布说明里写明，并让测试显式断言新值而不是"不变" |
| F7 调完仍不好看 | 只能真机迭代；先出一张图再决定，别在 offscreen 上反复猜 |
