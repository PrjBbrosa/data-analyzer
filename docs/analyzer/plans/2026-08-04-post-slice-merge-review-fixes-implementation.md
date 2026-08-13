# 切片合并后代码审查 · 实施计划

- 设计：[2026-08-04-post-slice-merge-review-fixes-design.md](2026-08-04-post-slice-merge-review-fixes-design.md)
- 基线：`main` @ `28370b1`（v7.9.2 + 切片导出合并 + 设为左轴修复）。本文行号以此 commit 为准，
  每处都已在工作区核对过。
- 执行顺序（按「改动小 × 收益直接」排）：
  **R1 → P1 → R2 → C2 → P2/P3 → C1 → 收尾批（R3/C3/C4/P4/P5/P6/M1-M5）→ 全量回归**
- 阶段之间可独立提交；每个阶段自带回滚边界（见各阶段「范围」）。

---

## 0. 动手前（必读，两条是本轮特有的坑）

### 0.1 既有失败基线

这台 Windows 机器上干净 `main` 就红的用例（`docs` 已记录、上一轮逐条确认过）：

- `tests/ui/test_split_*`（CLAUDE.md 已记录，`canvas_time.get_visible_xlim()` 返回 `None`）
- `tests/ui/test_batch_smoke.py::test_time_analysis_form_fits_288px_after_repeated_dependency_toggles`
- `tests/test_batch_runner.py::test_grouped_interleaved_pairs_regroup_by_canonical_physical_source`
- `tests/test_batch_render_qt.py` 三条（`test_eight_subplot_text_geometry_and_shared_x_contract`、
  `test_subplot_export_draws_before_writing_dpi_metadata_and_contains_ticks`、
  `test_cjk_font_support_and_header_ink_proof`）
- `tests/test_batch_render_qt_ssaa.py::test_legend_keeps_its_one_to_one_size_through_the_downscale`
- `tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence`（14 例）
- `tests/ui/test_batch_input_panel.py` 四条 probe 生命周期
- `tests/ui/test_batch_signal_picker.py` 两条省略号

后几组同一个根因：**本机 Qt 缺字体**，offscreen 渲出来的图没有任何文字，断言文字墨迹/几何的用例必红。

pytest 必须带 `--basetemp`（默认临时目录有 Windows 权限问题，不带会伪造出十几条 ERROR）：

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest tests\test_batch_render_qt_heatmap.py -q --basetemp=C:\Users\hang\AppData\Local\Temp\claude\D--Coding-project-data-analyzer\slice-fixes
```

### 0.2 ⚠️ R2 的两条「红测试」在本机是**绿**的 —— 不能当验收信号

设计里写的
`test_slice_row_never_narrows_the_main_left_axis`（`tests/test_batch_render_qt_heatmap.py:699`）
与 `test_slice_amplitude_axis_ends_on_whole_nice_steps`（同文件 `:850`）
只在 macOS（PingFang SC，行高 23.78px）红；本机 fallback 字体行高小，**修复前后都绿**。

执行者不要因此认为「已经修好了」。R2 的两步各自必须补一条**字体无关**的回归测试
（做法见阶段 3），并且**先在未修改的代码上验证新测试是红的**，否则这一阶段没有任何本机验收信号。
原有两条测试仍要跑，只是它们的绿在本机不构成证据 —— 真正的双机确认留给 macOS 复验。

### 0.3 视觉结论一律回真机

本机渲不出文字，`offscreen` 只算排版草稿。R1 的「标题下方留白干净」、P6 的禁用皮肤，
本机只能给几何断言，视觉验收必须回 macOS 截图（CLAUDE.md Gotchas）。

### 0.4 全局约束（每个阶段都适用）

1. 切片**关闭**路径的 PNG/CSV 逐字节 parity 是既有回归保护
   （`test_slice_disabled_png_is_byte_identical_to_no_slice_field`），任何渲染改动不得破坏。
2. `batch*.py` 保持 GUI-free，Qt 只允许函数内局部 import（C2 正是在收紧这条边界）。
3. 阶次领域是 EPS：转速 = 电机转速，文案不得出现 engine 措辞。

---

## 阶段 1 · R1：切片行顶框线穿过主图底部轴标题（P0）

**范围**：`mf4_analyzer/batch_render_qt/_builder.py`（`_space_bottom_axis_label` +
`_register_bottom_label_spacing` + `build_heatmap` 的注册时机）、
`tests/test_batch_render_qt_heatmap.py`。

**根因**：`build_heatmap` 在 `_builder.py:2025` 注册底部标题下移，
而 `plan = plan_heatmap_slice(...)` 要到 `:2091` 才算出来 ——
注册时还不知道这一页下面会不会加切片行，于是标题按「页面最底部面板可以悬垂」的前提
悬进了切片行的绘图区。

### 步骤

1. `plan_heatmap_slice(x_values, y_values, self.params)` 上移到 `plot` 创建之前
   （它只依赖 `x_values` / `y_values` / `self.params`，无副作用），
   `self.slice_plan = plan` 一并上移；原 `:2091-2097` 处只留 `if not plan.enabled:` 的早退分支。
2. `_space_bottom_axis_label(plot, font_pt, *, overhang=True)` 增加一个关键字参数，
   `_register_bottom_label_spacing(plot, *, overhang=True)` 透传：
   - `overhang=True`（现状，所有非切片路径）：一个字节都不变 —— `setPos(base_y + nudge + extra)`。
   - `overhang=False`（主热力图 + 切片行开启）：把 `extra` 买成轴高度，
     标题回到 pyqtgraph 自己的锚点，不越出轴矩形。
   ```python
   state = {"base": None}

   def reposition(*_args) -> None:
       if not axis.isVisible() or not str(axis.labelText or "").strip():
           return
       if not overhang:
           if state["base"] is None:
               state["base"] = float(axis.height())
           axis.setHeight(state["base"] + extra)   # 幂等：base 只取一次
       rect = label.boundingRect()
       base_y = float(axis.size().height() - rect.height())
       offset = _PG_AXIS_LABEL_NUDGE_PX if not overhang else _PG_AXIS_LABEL_NUDGE_PX + extra
       label.setPos(label.pos().x(), base_y + offset)
   ```
3. `build_heatmap` 里主图那次注册改为 `self._register_bottom_label_spacing(plot, overhang=not plan.enabled)`；
   切片行自己那次（`:2136`）保持 `overhang=True` —— 它才是页面最底部面板。
4. 给这个 `reposition` 挂 `reposition.runs_after_tick_density = True`
   （与 `_slice_alignment_callback` 同款），保证它在刻度串定稿后用最终高度再跑一遍。
   注意 `_register_bottom_label_spacing` 目前把回调塞进 `self.layout_callbacks`，
   `show_and_settle` 的二次回合只跑带标记的回调 —— 加了标记就自动被覆盖。

**若 `setHeight` 冻结轴高导致 `settle_subplot_layout` / SSAA 比例出问题**（`_space_bottom_axis_label`
的 docstring 点名了这个风险），退路是不动轴、改在两行之间插空：
`self.widget.ci.layout.setRowSpacing(3, extra)`，仅在 `plan.enabled` 时调用。
几何断言相同，先试加高、失败再换，不要两个都上。

### 测试（`tests/test_batch_render_qt_heatmap.py`）

- `test_slice_row_top_never_crosses_the_main_bottom_axis_title`：
  开切片，断言 `主图 bottom 轴 label 的 sceneBoundingRect().bottom() <= slice_plot.vb.sceneBoundingRect().top() + 0.5`，
  并同时断言标题矩形落在自己 axis 的 `sceneBoundingRect()` 内（后者是真正的不变量）。
- 字体无关补强：把 label 字体临时放大（`label.setFont(chart_font(20))`）后重跑该回调，
  断言两条不等式仍成立 —— 本机缺字体时标题矩形偏小，不放大可能空过。
- 回归保护：`test_slice_disabled_png_is_byte_identical_to_no_slice_field` 必须仍绿。

```powershell
tests\test_batch_render_qt_heatmap.py tests\test_batch_render_qt.py tests\test_batch_render_qt_ssaa.py
```

**真机复验项**：1920×1080 开切片导出一张，确认 "Time (s)" 下方留白干净、框线不穿字。

---

## 阶段 2 · P1：应用不带 slice 的 preset 清空用户已填配置（P0）

**范围**：`mf4_analyzer/ui/drawers/batch/slice_panel.py:207-218`、
`tests/ui/test_batch_slice_panel.py`。

**根因**：`normalize_batch_params`（`batch_recipe.py:409-413`）会把关闭态的 slice 整个 pop 掉，
所以绝大多数 preset 不带该键；而 `apply_params` 把「缺键」当成「重置」。
同一批提交已在 `chart_statistics_panel.py:208-219` 用正确写法修过同款 bug。

### 步骤

照抄 `chart_statistics_panel` 的模式，缺键时只关开关、不动字段：

```python
def apply_params(self, params: dict | None) -> None:
    raw = (params or {}).get("slice")
    if raw is None:
        # 归一化会把关闭态的 slice 整个 pop 掉，所以「缺键」只意味着这份
        # preset 没开切片，不意味着用户填的维度/位置该被丢掉。
        self._enable_switch.setChecked(False)
        self._sync_enabled()
        return
    value = dict(raw)
    ...
```

（`QSignalBlocker` 的包裹放在阶段 5 一起做，避免这一阶段同时改两件事。）

### 测试

- 新增 `test_slice_panel_apply_params_without_slice_key_keeps_axis_and_positions`：
  填好 `axis=y` + `"5, 15, 25"` → `apply_params({"window": "hanning"})` →
  断言开关关闭、`_axis_combo.currentData() == "y"`、`_positions_edit.text()` 原样保留。
- 既有 `test_slice_panel_apply_params_none_slice_resets_to_disabled`（`:180`）只钉开关状态，
  按现状应仍绿；若它顺带断言了字段被清，改测试（设计已裁定字段保留是正确行为）。

```powershell
tests\ui\test_batch_slice_panel.py tests\ui\test_batch_chart_statistics.py
```

---

## 阶段 3 · R2：轴宽 pin 与刻度密度依赖机器字体（P0）

**范围**：`_builder.py` 的 `_slice_alignment_callback.align`（`:668`）、
`_labels_fit`（`:1147`）、`_apply_tick_density`（`:1083`）、
`tests/test_batch_render_qt_heatmap.py`。

> 先读 0.2：本机两条现成测试都是绿的，本阶段的验收信号来自**新加的注入式测试**。

### 3a · 左轴宽度 pin 只许往宽走

`align()` 的目标宽度改为「度量值」与「当前 `axis.width()`」的较大者：

```python
target = max(
    max(_left_axis_width_for_ticks(axis), float(axis.width()))
    for axis in left_axes
)
```

- 度量值兜「从未绘制 / 刚换刻度串」的下限（docstring 里 30px / 57.4px 的病因）。
- `axis.width()` 兜「绘制度量比 `QFontMetricsF` 宽」的上限（PingFang 下差 ~3.4px）。
- pin 单调不减 → 多次 `align` 收敛不振荡；代价是刻度串变短后可能略宽，一次性导出可接受。
  在 `align` 的 docstring 里补一句说明这个取舍。

**注入式回归测试**（本机可红可绿，与字体无关）：

```python
def test_slice_alignment_never_pins_narrower_than_the_axis_already_is(qapp, monkeypatch):
    # 模拟 macOS：QFontMetricsF 量出来比 pyqtgraph 绘制时窄
    real = _builder._left_axis_width_for_ticks
    monkeypatch.setattr(_builder, "_left_axis_width_for_ticks", lambda ax: real(ax) - 6.0)
    ...  # 建带切片的场景，断言主图左轴宽度 >= 不开切片时的自然宽度
```

修复前这条必红，修复后转绿。既有 `test_slice_alignment_measures_the_ticks_that_are_actually_installed`
（断言刻度串变长时 pin 跟着变宽）必须仍绿 —— 单调向宽不影响它。

### 3b · 纵轴 fit 判定改用 ascent+descent，度量字体与轴一致

1. 抽一个模块级 helper（`_left_axis_width_for_ticks` 里那段 tickFont 优先逻辑就是它）：
   ```python
   def _axis_tick_font(axis, fallback_pt: float):
       font = axis.style.get("tickFont")
       if font is None:
           label_item = getattr(axis, "label", None)
           font = label_item.font() if label_item is not None else chart_font(fallback_pt)
       return font
   ```
   `_left_axis_width_for_ticks` 改用它，消掉两处不一致。
2. `_apply_tick_density` 不再在循环外建一个 `QFontMetricsF(chart_font(theme.axis_font_pt))`，
   改为每根轴 `QFontMetricsF(_axis_tick_font(axis, self.theme.axis_font_pt))`。
3. `_labels_fit` 纵轴分支：`needed = metrics.ascent() + metrics.descent() + 4.0`
   （去掉 leading），横轴分支不动。

**影响面提醒**：`_labels_fit` 是全页面共用的，`needed` 变小 → coarsen 更不容易触发 →
某些页面刻度可能变密。这会动到断言刻度值的用例，本机 `_tickLevels` 断言集中在
`tests/test_batch_render_qt_heatmap.py`（其余 `_tickLevels` 断言都在实时画布，不走 `_builder`）。
跑完对照，凡是刻度数变化的用例逐条判断是「修好了」还是「回归」，别无脑改期望值。

**注入式回归测试**：直接单测 `_labels_fit`，喂一个 `height()` 远大于 `ascent()+descent()` 的
桩 metrics（`SimpleNamespace(height=lambda: 24.0, ascent=lambda: 12.0, descent=lambda: 4.0, width=...)`），
断言 10 个标签在 260px 轴上判定为 fit。修复前必红。

### 3c · 可选防御（P2，本轮只留 TODO）

coarsen 之后按**最终步长**把范围端点向外重取整 —— 只允许作用于切片幅值轴这类
**自动推导**的范围，不许碰手动范围（`_apply_tick_density` 的 docstring 承诺手动范围保持精确边界）。
本轮不实施，在 `_fit_axis_ticks` 上方留 TODO + 指向本文。

```powershell
tests\test_batch_render_qt_heatmap.py tests\test_batch_render_qt.py tests\test_batch_render_qt_ssaa.py tests\test_batch_renderer.py
```

**真机复验项**：macOS 上跑原两条测试转绿，并导出一张开切片的图确认幅值轴回到步长 4 的 10 个刻度、
端点 -36 落在刻度上。

---

## 阶段 4 · C2：data-only 导出不再无条件拉入 Qt（P1）

**范围**：`mf4_analyzer/batch.py:4189`、新测试文件或
`tests/test_batch_render_import_boundary.py`。

### 步骤

`_slice_workbook_factory` 开头先查参数，再决定要不要加载 contract：

```python
raw_slice = params.get('slice') if isinstance(params, Mapping) else None
if not isinstance(raw_slice, Mapping) or not raw_slice.get('enabled', False):
    # 归一化保证「键只在启用时幸存」，所以这个守卫既廉价又充分；
    # contract 会 import batch_render_qt._builder（~169 个 PyQt5/pyqtgraph 模块）。
    return None
contract = _load_slice_render_contract()
```

顺带把 `_load_slice_render_contract` docstring 里那句「只在真的要写切片工作簿时才 import」
的承诺与实现对齐（现在才真正成立）。

### 测试

仿 `tests/test_signal_no_gui_import.py` 的投毒法，新增子进程测试：
子进程里先 `sys.modules['PyQt5'] = None`，再构造 `BatchRunner` 并调用
`_slice_workbook_factory`（不带 slice 的 fft_time data-only 参数），
断言返回 `None` 且进程不崩、`sys.modules` 里没有任何 `PyQt5.*`。
放 `tests/test_batch_render_import_boundary.py`（它已有 subprocess 骨架）。

投毒是关键：不投毒的话本机装了 PyQt5，测试只能数模块数，容易失真。

```powershell
tests\test_batch_render_import_boundary.py tests\test_batch_slice_export.py tests\test_batch_runner.py
```

---

## 阶段 5 · P2/P3：跟手（信号阻塞 + 防抖 + 单次校验，P1）

**范围**：`slice_panel.py`、`chart_statistics_panel.py`、
`ui/drawers/batch/sheet.py`、受影响的 batch UI 测试。

### 5a · `apply_params` 全程 QSignalBlocker（P2 项）

`slice_panel.apply_params` 与 `chart_statistics_panel.apply_params`（`:208-228`）
全程 `QSignalBlocker`，收尾统一发一次 `changed`。
同期 `output_panel.apply_open_folder_after_run`（`:886`）就是正确示范。

```python
blockers = [QSignalBlocker(w) for w in (self._axis_combo, self._positions_edit, self._enable_switch)]
try:
    ...  # 原逻辑
finally:
    del blockers
self.changed.emit()
```

注意链路：`slice.changed → AnalysisPanel._on_params_changed → paramsChanged →
BatchSheet._recompute_pipeline_status`。改完是「一次 apply = 一次 changed」，
不是零次 —— `AnalysisPanel.apply_params` 依次调三个子面板，别让状态条彻底不更新。

### 5b · `_recompute_pipeline_status` 走 ~150ms 单发定时器（P3a）

1. `__init__` 里建 `self._recompute_timer = QTimer(self)`，`setSingleShot(True)`，
   `setInterval(_PIPELINE_RECOMPUTE_DEBOUNCE_MS)`（模块级常量，建议 150），
   `timeout.connect(self._recompute_pipeline_status)`。
2. 新增 `def _schedule_pipeline_recompute(self): self._recompute_timer.start()`（restart 式合并）。
3. 把**信号驱动**的触发点全部改指向 scheduler：`sheet.py:363`、`:365`、`:368`、`:377`、`:380`、
   `:510`、`:822`、`:902`、`:915`、`:946`、`:1062`。
4. `__init__` 末尾的种子调用（`:411`）**保持直调** —— Run 按钮首帧状态不能延后。
5. `_recompute_pipeline_status` 开头 `self._recompute_timer.stop()`，
   保证「显式直调」立刻生效且不会被随后的 timeout 重复跑一遍。

**测试迁移（必须做，否则会伪造一批红）**：
`tests/ui/test_batch_*.py` 里有 81 处 `qtbot.wait(...)`，
其中 `qtbot.wait(20)` 之后立刻断言 `strip.cards[i].stage_status` 或 `_btn_run.isEnabled()`
的（如 `tests/ui/test_batch_input_panel.py:407`、`:426`）会因为 150ms > 20ms 而红。
逐条改成 `qtbot.waitUntil(lambda: ..., timeout=1000)`，
**不要**把防抖间隔调到 20ms 以下去迁就测试 —— 那样就不防抖了。
已经显式调 `sheet._recompute_pipeline_status()` 的用例（如
`tests/ui/test_batch_slice_panel.py:300`）不受影响，这也是新测试推荐的写法。

### 5c · 一次重算只跑一遍校验（P3b）

`is_runnable` 增加可选入参，外部 API 行为不变：

```python
def is_runnable(self, *, issues: tuple[ValidationIssue, ...] | None = None) -> bool:
    ...
    if (self.preflight_issues() if issues is None else issues):
        return False
    return True
```

`_recompute_pipeline_status`（`:636`）改成 `runnable = self.is_runnable(issues=preflight_issues)`，
复用 `:553` 已经算好的那份。其他调用点（`:1479`、`:1569`、`:1655`、`:1851-1852`）不传参，
行为与今天完全一致。

### 测试

- 新增计数型测试：monkeypatch `BatchSheet.preflight_issues` 计数，
  调一次 `_recompute_pipeline_status()`，断言只被调用 **1** 次（今天是 2 次）。
- 新增防抖测试：连续 `setText` 九次（模拟输入 `5, 15, 25`），
  统计 `_recompute_pipeline_status` 实际执行次数 ≤ 2，且 `waitUntil` 后状态正确。
- 新增 `apply_params` 单次通知测试：`changed` / `paramsChanged` 各只发一次。

```powershell
tests\ui\test_batch_slice_panel.py tests\ui\test_batch_input_panel.py tests\ui\test_batch_smoke.py tests\ui\test_batch_chart_statistics.py tests\ui\test_batch_compact_contract.py tests\ui\test_batch_method_buttons.py tests\ui\test_batch_output_panel.py
```

---

## 阶段 6 · C1：收紧位置类型校验，堵住 headless 静默丢切片（P1）

**范围**：`mf4_analyzer/batch_validation.py:395-404`、`tests/test_batch_validation.py`。

**根因**：`validate_recipe` 经 `_finite_number`（`:33`，先 `float(value)` 再判有限）接受字符串，
而 `normalize_batch_params`（`batch_recipe.py:350-353`）只认 `int/float` ——
`positions: ["1.5", "2.5"]` 零告警通过校验，归一化后变成空表，
`plan.enabled = False`，run 顺利「done」，没有切片曲线也没有警告。

### 步骤

位置检查镜像归一化的类型过滤（**只许更严，不许更宽**）：

```python
def _slice_position_number(value: Any) -> bool:
    # 与 normalize_batch_params 的过滤逐字对齐：接受类型的单一真相在归一化层。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))
```

`valid_positions` 改用它；文案改成
`"slice positions must be a list of finite numbers (strings are not accepted)"`。
`invalid_slice_positions` 这个 code 保持不变（sheet 的映射表按 field 走，不按 code）。

不选「归一化端做字符串强转」：手写 JSON 的作者应当拿到明确早报错，而不是静默宽容。

### 测试

- `positions: ["1.5", "2.5"]` → 断言产出 `invalid_slice_positions`。
- `positions: [1.5, 2]`（含 int）→ 断言仍然合法。
- `positions: [True]` → 断言被拒（bool 不是数字）。
- 端到端：同一份 recipe 过 `validate_recipe` 与 `normalize_batch_params`，
  断言「校验通过 ⟹ 归一化后位置非空」（这条不变量正是本 bug 的缝）。

```powershell
tests\test_batch_validation.py tests\test_batch_recipe.py tests\test_batch_slice_export.py
```

---

## 阶段 7 · 收尾批（P2，可并成一次提交）

按依赖度分组，组内互不干扰。

### 7a · 渲染与核心

| 项 | 位置 | 做法 |
| --- | --- | --- |
| R3 | `_builder.py:2249-2253`、`batch.py:4204-4209` | `np.min/np.max` → 复用 `plan_heatmap_slice` 已算好的有限边界（一处真相）；拿不到就退 `np.nanmin/np.nanmax`。测试：坐标里塞一个 NaN，断言警告文案不含 `nan` 且无 RuntimeWarning。 |
| C3 | `batch_recipe.py:350-353` | 过滤非有限值（`math.isfinite`，渲染端 `_slice_positions` 已是这么做）。测试：`[nan, 5.0]` 与 `[5.0, nan]` 归一化结果与 fingerprint 相同（D7 要求对输入顺序不敏感）。 |
| C4 | `batch.py:3839`、`:5081`、`_guess_rpm_channel`（`:5171`） | 命中名称猜测时，对每个 item 往 `warnings_out` 发一条：`未指定转速通道，已按名称匹配使用 <通道名> —— 请确认`。不改成硬错（会破坏既有 headless 流程；GUI 路径有 `sheet.py:1340-1349` 强制，本就不可达）。文案说「转速/电机转速」，**不许出现 engine**。测试：headless 跑一份没配 RPM 的 order_time，断言 warning 里点名了猜中的通道。 |

### 7b · 批处理面板

| 项 | 位置 | 做法 |
| --- | --- | --- |
| P4 | `slice_panel.py:177-194`、`sheet.py:82-93` 与 `:117-124` | `positions_error()` 增加轴感知负数检查（轴为 `y` 时拒负，文案指向位置字段）；同时把 `"slice"` 补进两张映射表（与 `"slice_positions"` 同文案），兜住 `validate_recipe` 用 `"slice"` 作 field 的那几条。 |
| P5 | `slice_panel.py:143-149` | 计数改为 `min(len(dict.fromkeys(self._parse_positions())), _MAX_POSITIONS)`。测试：`15, 5, 15` 显示「2 处」。 |
| P6 | `signal_picker.py` `_apply_trigger_style` 的禁用分支、`_ArrowButton` 绘制 | 禁用时 `self._trigger.setCursor(Qt.ArrowCursor)`（启用分支恢复 `PointingHandCursor`），箭头颜色随 `isEnabled()` 变灰。测试只能钉 cursor 与画笔颜色；**观感回真机**。 |
| M3 | `sheet.py:1544-1565` | 首选零 dataclass 改动：仅当 `group.group_by == "source"` 时才做 basename 拆分与兄弟计数，其余分组方式直接给不带 detail 的文案（`display_name` 在 `group_by="channel"` 下是通道名，拆出来必然误导）。要精确文案再给 `BatchRepresentativeGroup`（`batch.py:218`）加一个带默认值的 `source_basename` 字段。 |

### 7c · 主窗口与发现性

| 项 | 位置 | 做法 |
| --- | --- | --- |
| M1 | `window.py:3290-3296` + `BatchSheet` | 删掉 `dlg.exec_()` 之前那条主窗口 toast（被 ~1080×760 模态面板完全遮住），改为 `BatchSheet.set_handoff_notice(text)`：sheet 内部在 RPM 通道行旁挂一行注记 label（不要写进 `strip`，会被下一次重算覆盖）。测试：断言 toast 不再发出、注记文本可见。 |
| M2 | `contextual_order.py:532-533` 与 `:771-772` | `if 'window' in d` → `self._apply_window_value(d.get('window', 'hanning'))`。**只动阶次面板**（没有任何历史阶次载荷带这个键；fft/fft_time 不要碰）。测试：先选 flattop，再应用一份不带 `window` 的旧 preset，断言 combo 回到 hanning。 |
| M5 | `window.py:3371-3389` | fft_time 分支补 `normalize_batch_params`，与 order 分支（`:3403` 之后）对称。若发现指纹或测试受影响则**放弃**，保持现状并留一行注释说明为什么不对齐。 |
| M4 | `ui/hints.py` + `ui/quickref.py` | 走项目命令 `/update-hints` 同步：「导出切片」补上「最多 4 个位置 / 仅时频·阶次」，「完成后打开输出文件夹」开关及其偏好持久化补进两个面。**不要手改**。 |

```powershell
tests\test_batch_render_qt_heatmap.py tests\test_batch_recipe.py tests\test_batch_runner.py tests\ui\test_batch_slice_panel.py tests\ui\test_batch_signal_picker.py tests\ui\test_main_window_smoke.py tests\ui\test_inspector.py tests\ui\test_hints.py
```

---

## 阶段 8 · 全量回归与交付

1. 全量跑一次（约 20 分钟，`pytest.ini` 默认 `-m "not slow"`）：
   ```powershell
   $env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python.exe -m pytest -q --basetemp=C:\Users\hang\AppData\Local\Temp\claude\D--Coding-project-data-analyzer\slice-fixes-full
   ```
2. 与 0.1 的基线**逐条对比**，只允许「基线红」这一个来源的失败；新红一条都不许留。
3. 结论写法要诚实：本机跑出来的是 **Windows 结论**，
   R1/R2/P6 的视觉与字体结论必须标注「待 macOS 复验」，不要重复上一轮
   「full suite identical failure sets」被跨机推翻的写法。
4. 真机（macOS）复验清单：
   - R1：开切片导出，标题下方留白干净、切片行框线不穿字。
   - R2：`test_slice_row_never_narrows_the_main_left_axis` 与
     `test_slice_amplitude_axis_ends_on_whole_nice_steps` 转绿；导出图幅值轴步长 4、端点在刻度上。
   - P6：信号选择器禁用态无手型光标、箭头变灰。
   - M1：批处理面板内能看到手动 RPM 的注记。

---

## 验收总表

| 项 | 阶段 | 级别 | 本机可验收信号 | 需真机复验 |
| --- | --- | --- | --- | --- |
| R1 标题穿线 | 1 | P0 | 新几何断言（含放大字体的字体无关补强） | 是（截图） |
| R2a 轴宽 pin | 3 | P0 | 新注入式测试（monkeypatch 度量函数） | 是（原测试双机转绿） |
| R2b 刻度 coarsen | 3 | P0 | `_labels_fit` 桩 metrics 单测 | 是 |
| P1 状态清空 | 2 | P0 | 新字段保留测试 | 否 |
| P2/P3 跟手 | 5 | P1 | 计数型测试（校验 1 次、九次输入 ≤2 次重算） | 否 |
| C1 校验分歧 | 6 | P1 | 新拒绝测试 + 「校验通过 ⟹ 归一化非空」不变量 | 否 |
| C2 Qt import | 4 | P1 | 投毒子进程测试 | 否 |
| R3/C3/C4 | 7a | P2 | 各 1 条测试 | 否 |
| P4/P5/P6/M3 | 7b | P2 | 各 1 条测试 | P6 是 |
| M1/M2/M5 | 7c | P2 | 各 1 条测试 | M1 是 |
| M4 发现性面 | 7c | P2 | `/update-hints` 产出 | 否 |
