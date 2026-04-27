# UI Polish + Order-RPM 链路移除 Design Spec

**Date:** 2026-04-26
**Author:** main Claude
**Status:** revised after codex review (rev 2)
**Trigger:** 用户提供 5 张截图反馈（紧凑化、StatsStrip 范围、预设默认名、删 转速-阶次、坐标轴可发现性 + toolbar 中文化）
**Codex review:** `docs/superpowers/reports/2026-04-26-ui-polish-and-order-rpm-removal-spec-review.md`（rev 1 verdict: needs revision before plan；本文件按 critical + should-fix 项全量回应）
**Related prior specs:**
- `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`
- `docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`
- `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`
- `docs/superpowers/specs/2026-04-23-mac-style-3pane-ui-design.md`

## 0. Supersedes prior spec

本 spec 显式废弃下列在 `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`（以下简称 `canvas-perf`）与 `docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`（以下简称 `batch-preset`）中曾经成立的契约：

- `OrderAnalyzer.compute_rpm_order_result`（删除）— `canvas-perf` §2.1 Included 第 32-34 行 + §4.6 内层向量化
- `OrderAnalyzer.compute_order_spectrum`（删除 — `canvas-perf` §6.1 公共方法保持不变中点名要保留的旧 tuple-API 公共入口；本 spec 与之冲突，以本 spec 为准）
- `OrderRpmResult` dataclass（删除）— `batch-preset` §"Order Analysis" 第 17-33 行
- `OrderAnalysisParams.rpm_res` 字段（删除）
- `MainWindow.do_order_rpm` / `MainWindow._render_order_rpm`（删除）— `canvas-perf` §4.3 OrderWorker 第 132+ 行 + §7 验收 #13 第 530 行 imshow 方向校正
- `BatchRunner._compute_order_rpm_dataframe`、`SUPPORTED_METHODS` 中的 `'order_rpm'`（删除）— `batch-preset` §"Batch Presets" 第 44-49 行
- 所有 `tests/test_order_analysis.py` / `tests/test_batch_runner.py` / `tests/ui/test_order_worker.py` / `tests/ui/test_inspector.py` 中针对上述符号的测试用例（删除）
- `canvas-perf` §2.1 Included 第 33-34 行规定的 `OrderRpmResult.counts` 按帧累加语义、`compute_rpm_order_result` 中 `argmin` 向量化条款全部失效
- `canvas-perf` §8 风险表第 549 行的 "order_rpm 矩阵方向写错" 缓解条款失效（rpm 路径不存在了）

保留：
- `compute_order_spectrum_time_based`（与 rpm-binned 链路无关，是 time-order 的旧 API 入口；本期不动）
- `compute_time_order_result` / `extract_order_track_result` 全链路
- `canvas-perf` §4.1 / §4.2 / §4.4 / §4.5 / §4.6 中与 time-order / order-track 相关的全部条款（PlotCanvas envelope cache、blit cursor、imshow heatmap、order_track 下半幅 RPM 曲线）

## 1. Goal

5 项 UI 收尾改造，加上把"转速-阶次"整条功能链清出仓库（含 `rpm_res` 配置面、`compute_order_spectrum` 旧 facade、batch 的 order_rpm 入口），让交互更紧凑、更可发现，同时去掉一条用户判断已不需要的分析路径。

非目标：
- 不重写 matplotlib NavigationToolbar 后端，仅做表层中文化与瘦身
- 不引入额外的 hover 动画框架
- 不改变现有 chart 的 fft / 时间-阶次 / 阶次跟踪 数据流

## 2. Scope

### 2.1 Included — 5 项需求拆分

#### S1 · 画布紧凑化（4 个 canvas + main_window 中的 fft / track 子图）

**变更点（穷举）：**

| 位置 | 当前 | 改为 |
|---|---|---|
| `mf4_analyzer/ui/canvases.py:1104-1106` SpectrogramCanvas figsize | `(12, 8)` | `(10, 6)` |
| `canvases.py:1205` gridspec hspace | `0.28` | `0.18` |
| `canvases.py:1227` colorbar pad | `0.01` | 不变（已紧凑） |
| `canvases.py:1239-1248` Spectrogram tight_layout | `tight_layout()`（warning suppressed） | 删除该 try；改用显式 `subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST)` **在 `fig.colorbar(...)` 调用之后**（顺序很重要：colorbar 修改 axes 边界后再 adjust） |
| `canvases.py:486` TimeDomain tight_layout | `tight_layout()` | `tight_layout(**CHART_TIGHT_LAYOUT_KW)` |
| `canvases.py:516` TimeDomain overlay tight_layout | `tight_layout()` | 同上 |
| `canvases.py:535` TimeDomain rebuild tight_layout | `tight_layout()` | 同上 |
| `canvases.py:1555` PlotCanvas tight_layout | `tight_layout()` | 同上 |
| `main_window.py:1257` (FFT 渲染) tight_layout | `tight_layout()` | 同上 |
| `main_window.py:1584` (order_track 渲染) tight_layout | `tight_layout()` | 同上 |
| `canvases.py:1434-1436` PlotCanvas figsize | `(20, 12)` | **保持不变** —— 这个 figsize 是逻辑画布单位，实际显示由 Qt widget size 决定；改了反而影响 dpi 计算 |

**新增 module-level 常量（`mf4_analyzer/ui/canvases.py` 顶部）：**

```python
# Tight margins for non-spectrogram canvases. Default tight_layout pad
# is 1.08× font size which is loose for Chinese fonts.
CHART_TIGHT_LAYOUT_KW = dict(pad=0.4, h_pad=0.6, w_pad=0.4)

# Spectrogram has a colorbar on the right; subplots_adjust must run
# AFTER fig.colorbar(...) so colorbar geometry is already in place.
SPECTROGRAM_SUBPLOT_ADJUST = dict(
    left=0.07, right=0.93, top=0.97, bottom=0.09,
)

# Pixel margin around an axes for hit-detection of the axis-edit
# affordance (hover + double-click).
AXIS_HIT_MARGIN_PX = 45
```

**注意 colorbar 与 right 余量：** 上一版 spec 写 `right=0.97`，但 SpectrogramCanvas 在 right 区域有 colorbar；codex review §should-fix-6 提示。改用 `right=0.93` 给 colorbar 留位，必要时再实测调整。

**Y 轴 labelpad 兼容：** TimeDomainCanvas line 478-480 / 507-510 / 531-533 用 `set_ylabel(..., labelpad=12)`，`pad=0.4` 的 tight_layout 仍能容纳（labelpad 是数据坐标外补，与 figure pad 是叠加关系），但 acceptance test 必须断言 ylabel bbox 不与 yticks bbox 重叠。

**S1 Acceptance（每条都对应一个测试）:**

| ID | 断言 | 测试位置 |
|---|---|---|
| S1-T1 | SpectrogramCanvas 渲染后 `fig.subplotpars.right == 0.93 ± 0.005` | `tests/ui/test_canvas_compactness.py::test_spectrogram_subplotpars` |
| S1-T2 | TimeDomain / FFT / order_track 渲染后 `fig.subplotpars.left ≤ 0.10` 且 `top ≥ 0.93` | 同文件，4 个测试 |
| S1-T3 | colorbar.ax bbox 不与 spectrogram axes bbox 重叠 | 同文件 |
| S1-T4 | ylabel render bbox 不与 yticks render bbox 重叠（用 `Text.get_window_extent`） | 同文件 |
| S1-T5 | 4 模式各截一张 PNG 留 `docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/`（**必选**：Wave 3 sign-off 凭证） | 手动 |

#### S2 · StatsStrip 仅 time-domain 显示

- `mf4_analyzer/ui/chart_stack.py:377-379` `stats_strip` 仍挂在 stack 底部
- `set_mode(mode)` 内部新增一行 `self.stats_strip.setVisible(mode == 'time')`
- `set_mode` 已是模式切换的单一入口（codex affirmed §3 — `chart_stack.py` 内部仅 `set_mode` 调 `setCurrentIndex`，外部仅 `main_window.py:371` 经 `set_mode`）
- **构造时也要初始化一次** —— `__init__` 末尾 `self.stats_strip.setVisible(self.current_mode() == 'time')`，避免首次默认 mode 不是 time 时 stats_strip 残留可见

**S2 Acceptance:**

| ID | 断言 | 测试位置 |
|---|---|---|
| S2-T1 | 默认构造后 stats_strip 可见 = (默认 mode == 'time') | `tests/ui/test_chart_stack_stats_visibility.py` |
| S2-T2 | `set_mode('fft' / 'fft_time' / 'order')` 后 `stats_strip.isVisible() is False` | 同文件 |
| S2-T3 | `set_mode('fft')` 再 `set_mode('time')` 后 stats_strip 可见 | 同文件 |
| S2-T4 | 切回 time 模式且调用 `update_stats({})` 时 summary label 显示 "— 无通道 —" | 同文件 |

#### S3 · FFTTimeContextual 预设默认显示名 → 配置1/2/3

- `mf4_analyzer/ui/inspector_sections.py:1542-1548` `_BUILTIN_PRESET_DISPLAY` 改：

```python
_BUILTIN_PRESET_DISPLAY = {
    'diagnostic': '配置1',
    'amplitude_accuracy': '配置2',
    'high_frequency': '配置3',
}
```

- `inspector_sections.py:91-99` 注释里 "诊断模式 / 幅值精度 / 高频细节" 同步改 "配置1 / 配置2 / 配置3"
- `tests/ui/test_inspector.py:683-699` 已 assert 旧名（codex affirmed §4），改为 assert 新名

**S3 Acceptance:**

| ID | 断言 | 测试位置 |
|---|---|---|
| S3-T1 | 新构造的 FFTTimeContextual.preset_bar 三 slot text 为 `配置1 / 配置2 / 配置3` | `tests/ui/test_inspector.py::test_fft_time_preset_bar_default_names` |
| S3-T2 | 右键菜单"重置为默认"后 slot text 仍是新名 | 同文件 |
| S3-T3 | 旧 preset 文件（含 `display_name: '诊断模式'` override）加载后 slot text 仍按 override 显示 | 同文件 |

#### S4 · 删除 转速-阶次 整条链（B2 深度，扩展版）

**移除目标 — 完整列表（按 codex critical-2 + should-fix-1 修订）：**

UI 层 (`mf4_analyzer/ui/`)
- `inspector_sections.py`:
  - `OrderContextual.order_rpm_requested` (line 974) 删
  - `btn_or = QPushButton("转速-阶次")` + `setProperty` + `addWidget` (lines 1069-1072) 删
  - `self.btn_or.clicked.connect(...)` (line 1112) 删
  - `two_btns` HBoxLayout 改为单按钮：`root.addWidget(self.btn_ot)`，并 `self.btn_ot.setMinimumHeight` 与 `btn_ok` 对齐
  - `spin_rpm_res` 整套（lines 1051-1055）删
  - `_collect_preset` 中 `rpm_res=...` (line 1131) 删
  - `_apply_preset` 中 `'rpm_res' in d` 分支 (lines 1145-1146) 删
  - `get_params`（如有）中 `rpm_res=...` (line 1198) 删 —— 这条若仍被 `do_order_time` 间接读到，需要在删之前确认
- `inspector.py`:
  - `order_rpm_requested = pyqtSignal()` (line 43) 删
  - `self.order_ctx.order_rpm_requested.connect(...)` (line 132) 删
- `main_window.py`:
  - `OrderWorker.run` 里 `elif self._kind == 'rpm':` 分支 (lines 124-128) 删 —— **注意：实际字面量是 `'rpm'`，不是 `'rpm_order'`；详见源码 `main_window.py:124`**
  - `do_order_rpm` 整方法 (line 1318+) 删；该方法内调 `self._dispatch_order_worker('rpm', ...)` (line 1341) 一并删
  - `_render_order_rpm` 整方法 (line 1501+) 删
  - `_on_order_result` 里 `elif kind == 'rpm':` 分支 (lines 1455-1456) 删 —— **同样是字面量 `'rpm'`**
  - `_dispatch_order_worker` 函数体内不需要修改（它只是把 `kind` 透传给 worker；`'time'` / `'track'` 都还在用）
  - `self.inspector.order_rpm_requested.connect(...)` (line 304) 删
  - "当前转速-阶次" 字符串 (line 1527) 删
- `drawers/batch_sheet.py`:
  - `combo_method.addItems(["fft", "order_time", "order_rpm", "order_track"])` (line 108) → `["fft", "order_time", "order_track"]`
  - `spin_rpm_res` 整套 (lines 143-146) 删
  - `params['rpm_res']` (line 193) 删

Signal 层 (`mf4_analyzer/signal/`)
- `order.py`:
  - `OrderAnalysisParams.rpm_res` 字段 (line 30) 删
  - `OrderRpmResult` dataclass (line 44+) 删
  - `compute_rpm_order_result` 方法 (line 292+) 删
  - `compute_order_spectrum` legacy facade (line 439+) 删（即使 `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md` §6.1 公共方法保持不变曾要求保留，本 spec §0 已 supersede）
  - `compute_rpm_order_result` 内部所有 `rpm_res` / `rpm_min` / `rpm_max` / `rpm_bins` 局部变量随方法一起删
- `__init__.py`:
  - `from .order import ..., OrderRpmResult, ...` 移除 OrderRpmResult
  - `__all__` 列表里 `'OrderRpmResult'` 删

Batch 层 (`mf4_analyzer/batch.py`)
- `SUPPORTED_METHODS = {'fft', 'order_time', 'order_rpm', 'order_track'}` (line 89) → `{'fft', 'order_time', 'order_track'}`
- `_run_one` 中 `elif method == 'order_rpm':` 分支 (lines 194-196) 删
- `_compute_order_rpm_dataframe` classmethod (line 280+) 整方法删
- `_compute_order_dataframe`（如果它读 `params['rpm_res']`，line 259）改为不读 rpm_res；该参数与 time-order 路径无关
- 核对 `_image_payload_to_csv_dataframe` / `_write_image` 是否对 `'order_rpm'` 有专门分支 —— codex affirmed §7 确认 `_write_image` 走 generic else，不需要专门删除

测试层 (`tests/`)
- `tests/test_order_analysis.py`:
  - `test_rpm_order_counts_are_per_frame_not_per_nonzero` (line 32) 整方法删
  - `test_compute_*` 系列里 `compute_rpm_order_result` baseline 调用（line 71, 194 等）→ 整方法删（这些方法只服务 rpm_order）
  - `test_metadata_records_nyquist_clipped_at_median_rpm_orders` (line 230) 删
- `tests/test_batch_runner.py`:
  - `test_batch_order_rpm_csv_shape` (line 142) 删
- `tests/ui/test_order_worker.py`:
  - `test_render_order_rpm_uses_correct_extent_and_matrix_orientation` (line 136) 整方法删
  - import 行 `OrderRpmResult` 一并清
- `tests/ui/test_inspector.py`:
  - `with qtbot.waitSignal(oc.order_rpm_requested, ...): oc.btn_or.click()` (line 82-83) → 整测试删（如果该测试函数仅服务 rpm，整方法删）
  - 任何 `oc.spin_rpm_res` 引用一并清

**保留：**

- `compute_time_order_result` / `extract_order_track_result` 全部
- `OrderTimeResult` / `OrderTrackResult` dataclass
- `OrderAnalyzer` 类本身
- `compute_order_spectrum_time_based`（与 rpm 无关）
- `_order_amplitudes_batch` / `_order_amplitudes` / `build_envelope`

**S4 Acceptance（统一的 grep 校验）:**

```
$ grep -rn -E "(rpm_order|order_rpm|OrderRpmResult|compute_rpm_order_result|compute_order_spectrum\b|_render_order_rpm|do_order_rpm|order_rpm_requested|btn_or\b|_compute_order_rpm_dataframe|rpm_res|转速-阶次)" mf4_analyzer/ tests/
```
应输出 0 行。任何保留项必须在本 spec 显式列出豁免（目前没有豁免）。

**`'rpm'` 字面量额外校验（避免遗漏 OrderWorker 内部 kind 字面量）：**

```
$ grep -rnE "_kind == 'rpm'|kind == 'rpm'|_dispatch_order_worker\\('rpm'" mf4_analyzer/ui/main_window.py
```
应输出 0 行（`'time'` / `'track'` 仍存在，但 `'rpm'` 必须清干净）。

| ID | 断言 | 测试位置 |
|---|---|---|
| S4-T1 | 上述 grep 0 命中 | CI / 本 spec acceptance |
| S4-T2 | `pytest tests/` 全绿 | CI |
| S4-T3 | 启动 app 进入 `阶次` 模式：UI 仅 `时间-阶次` / `阶次跟踪` / `取消计算` 三个按钮 | 手动 + `tests/ui/test_inspector.py::test_order_contextual_buttons_after_rpm_removal` |

#### S5 · 坐标轴可发现性 + Toolbar 中文化 + 紧凑（4 画布全覆盖）

**A. dblclick → AxisEditDialog（4 画布）**

新建 `mf4_analyzer/ui/_axis_interaction.py`：

```python
"""Pure axis-hit detection + side-effecting axis-edit helper.

Extracted from PlotCanvas so all 4 canvases (TimeDomain, Plot, Spectrogram,
Order) can share the same hover/dblclick affordance.
"""

def find_axis_for_dblclick(fig, x_px, y_px, margin):
    """Pure: return (Axes, 'x'|'y') or (None, None).

    Pixel-based hit test that includes the tick-label gutter region
    (margin px outside the axes bbox) — matches user intuition that
    clicking on the tick numbers also targets the axis.
    """
    # body lifted verbatim from canvases.py:1644-1675; replaces self.fig
    # with explicit fig param.
    ...

def edit_axis_dialog(parent_widget, ax, axis):
    """Side-effecting: open AxisEditDialog modal, apply the user's
    choice to the axes, and return True if the dialog was accepted.

    Caller is responsible for calling canvas.draw_idle() when this
    returns True. (We do not call draw_idle here — the helper does
    not own a canvas reference.)
    """
    # body lifted from canvases.py:1706-1725
    ...
```

**Codex should-fix-2 回应：** `edit_axis_dialog` 显式标注 side-effecting，签名返回 bool。每个 canvas 在调用处自己 `draw_idle()`：

```python
ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, AXIS_HIT_MARGIN_PX)
if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
    self.draw_idle()
return
```

每个 canvas 的 `_on_click` **最前面**插入 dblclick 拦截：
- `TimeDomainCanvas._on_click` (canvases.py:893)
- `SpectrogramCanvas._on_click` (canvases.py:1329)
- `PlotCanvas._on_click` (canvases.py:1677) —— 已有，搬到新模块

**B. Hover 视觉提示（4 画布）— 修订后的优先级表**

**Codex critical-1 回应：** 默认 toolbar mode 是 `'pan'`（chart_stack.py:206-210 默认激活），所以"toolbar.mode != ''" 短路条件会让 hover 永远不触发。改用"actively dragging"判定：

```python
def _on_motion(self, e):
    # ... 已有逻辑
    if self._is_actively_dragging():
        return
    ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, AXIS_HIT_MARGIN_PX)
    if ax is not None:
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("双击编辑坐标轴")
    else:
        self.unsetCursor()  # 让 matplotlib 的 pan/zoom cursor 自己生效
        self.setToolTip("")
```

**`_is_actively_dragging` 定义（每 canvas 单独实现）：**

```python
def _is_actively_dragging(self):
    """True iff a mouse button is currently held down on this canvas."""
    return self._mouse_button_pressed
```

`_mouse_button_pressed` 在 `button_press_event` 置 True，`button_release_event` 置 False（每 canvas 在 `__init__` 末尾连这两个 callback；callback 内不影响其他既有逻辑）。

**修订后的优先级表（codex should-fix-4 回应）：**

| 状态 | 表现 |
|---|---|
| 鼠标按下拖动中（任意按键） | hover 提示完全短路，cursor 由 matplotlib pan/zoom 决定 |
| Pan/Zoom 工具激活但鼠标未按 | hover 提示**正常生效** —— 用户能看到坐标轴可点击 |
| TimeDomain 单/双游标模式 + 鼠标 hover 在轴外 | matplotlib 走自己的 motion 回调（cursor 数值读出），不冲突 |
| TimeDomain 单/双游标模式 + 鼠标 hover 在轴内 | hover 提示生效 + cursor 读出**继续工作**（cursor 显示代码不依赖 cursor shape） |
| TimeDomain SpanSelector 激活 | SpanSelector 自己处理 motion；hover 仍可改 cursor，**但 SpanSelector 在 active span 期间**会被 `_is_actively_dragging` 短路 |
| PlotCanvas remark 模式（`_remark_enabled`） | hover 仅改 cursor + tooltip；不影响左键单击添加 remark（remark 是 button_press 不是 motion） |
| Spectrogram 时间-切片点击模式（_on_click line 1329） | 同上，hover 与 click 不冲突 |
| 窗口外 / e.xdata is None | hover handler 提前返回，不改 cursor |

**`unsetCursor()` 而不是 `setCursor(Qt.ArrowCursor)`：** 让 matplotlib pan/zoom 的内置 cursor（`Qt.OpenHandCursor` for pan, `Qt.CrossCursor` for zoom）能自己接管。

**C. matplotlib NavigationToolbar 中文化 + 紧凑**

新建 `mf4_analyzer/ui/_toolbar_i18n.py`：

```python
"""Chinese tooltip layer for matplotlib NavigationToolbar2QT."""

# Map normalized english action text → (chinese tooltip, retain action?)
_ACTION_TOOLTIPS = {
    'home':     ('重置视图', True),
    'back':     ('上一视图', False),   # 删
    'forward':  ('下一视图', False),   # 删
    'pan':      ('拖动平移（左键拖动）', True),
    'zoom':     ('框选缩放（拖出矩形放大）', True),
    'save':     ('保存图片', True),
    'subplots': ('', False),  # already stripped elsewhere
    'configure subplots': ('', False),
}

def apply_chinese_toolbar_labels(toolbar):
    """Mutate `toolbar`: drop Back/Forward/Subplots actions; replace
    tooltip text on remaining actions; preserve original english key in
    `act.data()` so downstream `_find_action(toolbar, 'save')` etc. keep
    working.
    """
    for act in list(toolbar.actions()):
        key = (act.text() or '').strip().lower()
        if key not in _ACTION_TOOLTIPS:
            continue
        zh_tooltip, retain = _ACTION_TOOLTIPS[key]
        if not retain:
            toolbar.removeAction(act)
            continue
        # Preserve the english key on .data() — _find_action is updated
        # to use act.data() if non-empty, else fall back to act.text().
        act.setData(key)
        act.setToolTip(zh_tooltip)
        # NOTE: do NOT setText("") here — matplotlib's QToolButton uses
        # the text to render fallback when icon is unavailable. Tooltip
        # alone is sufficient for hover; toolbar.setToolButtonStyle(
        # Qt.ToolButtonIconOnly) suppresses text display visually.
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
```

**Codex should-fix-3 回应：** 顺序很重要 —— 在 `_ChartCard.__init__` 里：

1. 先 `_strip_subplots_action(toolbar)`（已有）
2. 再用 `_find_action(toolbar, 'save')` 拿 save action（仍能匹配 — text 还没改）
3. 再 `apply_chinese_toolbar_labels(toolbar)`（这里才改 tooltip + setData + 删 Back/Forward）
4. 之后任何 `_find_action` 调用必须改用 `act.data() == 'save'` 而不是 `text() == 'save'`

**`_find_action` 升级（chart_stack.py:130-134）：**

```python
def _find_action(toolbar, key_lower):
    """Match by act.data() first (i18n-stable), then act.text()."""
    for act in toolbar.actions():
        if act.data() == key_lower or (act.text() or '').strip().lower() == key_lower:
            return act
    return None
```

**Pan/Zoom 钩子（chart_stack.py:201-204）：**

```python
for act in self.toolbar.actions():
    name = act.data() if act.data() else (act.text() or '').strip().lower()
    if name in ('pan', 'zoom'):
        act.triggered.connect(self._on_nav_mode_toggled)
```

**time card segmented buttons 中文化（chart_stack.py:248-289）：**

| 当前 | 改为 |
|---|---|
| `Subplot` | `分屏` |
| `Overlay` | `叠加` |
| `Off` / `Single` / `Dual` | `游标关` / `单游标` / `双游标` |
| `无` / `X` / `Y`（轴锁） | `不锁` / `锁X` / `锁Y` |

**`_TOOL_HINTS` (chart_stack.py:113-117) 调整：**

```python
_TOOL_HINTS = {
    'pan': "<b>移动曲线</b><br>左键拖动平移 · 右键拖动缩放坐标轴",
    'zoom': "<b>框选缩放</b><br>拖动鼠标框选矩形区域放大 · Home 键可复位",
    '': "<b>浏览</b><br>双击坐标轴可设置范围 · 工具栏可启用 平移 / 缩放 / 保存",
}
```

**toolbar 紧凑：**

- `setIconSize(QSize(14, 14))` （原 16×16）
- `style.qss` 末尾追加（codex should-fix-4 提示用双 selector）：

```css
QToolBar#chartToolbar,
QWidget#chartToolbar,
NavigationToolbar2QT#chartToolbar { spacing: 1px; padding: 1px; }
QToolBar#chartToolbar QToolButton,
QWidget#chartToolbar QToolButton { padding: 2px 4px; }
```

**S5 Acceptance（穷举）：**

| ID | 断言 | 测试位置 |
|---|---|---|
| S5-T1 | 4 个 canvas 双击 X 轴弹 AxisEditDialog（monkeypatch exec_ → Accepted，断言 set_xlim 被调用） | `tests/ui/test_axis_interaction.py` |
| S5-T2 | 4 个 canvas 双击 Y 轴同上 | 同文件 |
| S5-T3 | Spectrogram 双击 slice 子图坐标轴也可用 | 同文件 |
| S5-T4 | hover 在轴区域 → cursor 是 PointingHandCursor，tooltip == "双击编辑坐标轴" | 同文件 |
| S5-T5 | hover 离开轴区域 → cursor 复位（unset） | 同文件 |
| S5-T6 | 鼠标按下中 hover 不改 cursor | 同文件 |
| S5-T7 | Pan 模式空闲（默认状态）下 hover 仍生效 | 同文件 |
| S5-T8 | Axis-lock 选中状态下 hover 在轴上仍能改 cursor | 同文件 |
| S5-T9 | TimeDomain dual-cursor 模式 + hover 轴上：cursor 数值读出仍显示 | 同文件 |
| S5-T10 | `apply_chinese_toolbar_labels` 后 Pan/Zoom/Save tooltip 是中文 | `tests/ui/test_toolbar_i18n.py` |
| S5-T11 | `apply_chinese_toolbar_labels` 后 Back/Forward 已 removeAction | 同文件 |
| S5-T12 | `_find_action(toolbar, 'save')` 在 i18n 之后仍能找到 save | 同文件 |
| S5-T13 | time card 上 8 个 segmented buttons 文字全部为新中文 | `tests/ui/test_chart_stack.py` 扩展 |
| S5-T14 | toolbar 加载完成后总高度 ≤ 改造前（基线由现有 test 测一次写常量） | 同文件 |
| S5-T15 | `_TOOL_HINTS['']` 文案包含 "双击坐标轴" | 同文件 |

### 2.2 Excluded

- 双击空白区域 = 重置视图（Home）—— Home 通过 toolbar 按钮触发；按钮 tooltip 也不再提"或双击空白区域"（codex nice-to-have-2 回应）
- toolbar 替换为画面内悬浮工具条（C 方案）
- TimeDomain / Spectrogram 内部其他点击逻辑的重构
- StatsStrip 内容 / 样式重新设计（仅切换可见性）
- PlotCanvas figsize 改动

## 3. Architecture & Data Flow

### 3.1 文件级别影响清单

新增（2 个 module + 4 个测试文件）：
- `mf4_analyzer/ui/_axis_interaction.py`（pure `find_axis_for_dblclick` + side-effecting `edit_axis_dialog`）
- `mf4_analyzer/ui/_toolbar_i18n.py`（`apply_chinese_toolbar_labels` + `_ACTION_TOOLTIPS`）
- `tests/ui/test_axis_interaction.py`
- `tests/ui/test_toolbar_i18n.py`
- `tests/ui/test_chart_stack_stats_visibility.py`
- `tests/ui/test_canvas_compactness.py`

修改：
- `mf4_analyzer/ui/canvases.py`（4 canvas 都接 dblclick + hover；S1 常量 + tight_layout 替换；删 PlotCanvas 老的 `_find_axis_for_dblclick` / `_edit_axis`，改 import 新模块）
- `mf4_analyzer/ui/chart_stack.py`（StatsStrip 显隐、segmented buttons 中文、toolbar 调用 i18n、`_TOOL_HINTS` 文案、`_find_action` 升级）
- `mf4_analyzer/ui/inspector_sections.py`（删 btn_or / order_rpm_requested / spin_rpm_res / `_BUILTIN_PRESET_DISPLAY` 改名）
- `mf4_analyzer/ui/inspector.py`（删 order_rpm_requested 中转）
- `mf4_analyzer/ui/main_window.py`（删 do_order_rpm / _render_order_rpm / OrderWorker 分支 / "当前转速-阶次" / FFT + track tight_layout 替换）
- `mf4_analyzer/ui/drawers/batch_sheet.py`（删 order_rpm 选项 + spin_rpm_res）
- `mf4_analyzer/ui/style.qss`（toolbar spacing / button padding 微调）
- `mf4_analyzer/signal/order.py`（删 OrderRpmResult / compute_rpm_order_result / compute_order_spectrum / OrderAnalysisParams.rpm_res）
- `mf4_analyzer/signal/__init__.py`（删 OrderRpmResult export）
- `mf4_analyzer/batch.py`（删 order_rpm 分支 / _compute_order_rpm_dataframe / params['rpm_res']）
- `tests/test_order_analysis.py`（删 rpm 相关测试）
- `tests/test_batch_runner.py`（删 batch order_rpm 测试）
- `tests/ui/test_order_worker.py`（删 _render_order_rpm 测试 + OrderRpmResult import）
- `tests/ui/test_inspector.py`（删 order_rpm_requested + spin_rpm_res 断言；改 preset display name 断言）

### 3.2 关键数据流

dblclick / hover 都是 matplotlib GUI event，不影响数据流。signal-layer 删除 rpm_order 后，UI / batch / 测试同步删，但 fft / order_time / order_track 完全独立。

## 4. Risks & Mitigations

| 风险 | 缓解 |
|---|---|
| `tight_layout(pad=0.4)` 在某些 fixture 下让 ylabel 撞 ytick label | S1-T4 用 `Text.get_window_extent` 自动断言 bbox 不重叠；若 fail 则把 pad 上调到 0.6 重测（spec 给出 0.4 是 first-best） |
| Spectrogram `right=0.93` 仍让 colorbar tick label 出图边 | S1-T3 自动断言 colorbar.ax bbox 不与 spectrogram axes bbox 重叠；codex should-fix-6 已点出 |
| Hover 在 Pan/Zoom 拖动时 cursor 抖动 | 用 `_is_actively_dragging`（mouse button pressed flag）短路；Pan 默认激活但鼠标未按时 hover **照常生效** —— 这是 codex critical-1 的关键修订点 |
| `_find_action` 升级后 i18n 之前的 `_strip_subplots_action` 调用失效 | i18n 在 `_strip_subplots_action` 之后；strip 仍按 text 匹配（subplots/configure subplots） |
| 删 `compute_order_spectrum` 后下游有第三方代码调用 | 这是私有库；tools/scripts/notebooks 一并 grep，0 命中 |
| `OrderAnalysisParams.rpm_res` 删除影响 `compute_order_spectrum_time_based`（保留项） | 验证：`compute_order_spectrum_time_based` 不读 `rpm_res`（line 423-437 仅用 max_ord/order_res/time_res/nfft）✓ |
| `_BUILTIN_PRESET_DISPLAY` 改名后旧 preset 文件里 `display_name == "诊断模式"` 仍按 override 显示 | 这是 PresetBar 设计行为（override 优先于 builtin）；用户首次"重置为默认"才看新名字 — 不写迁移脚本 |
| Squad wave overlap rework | 按 codex critical-3 改为文件归属切分（详见 §7） |

## 5. Acceptance Checklist（汇总）

- [ ] **S1**: S1-T1 至 S1-T5 全过；4 模式截图归档
- [ ] **S2**: S2-T1 至 S2-T4 全过
- [ ] **S3**: S3-T1 至 S3-T3 全过
- [ ] **S4**: S4-T1（grep 0 命中）+ S4-T2（pytest 全绿）+ S4-T3（UI 手动 + 自动测试）
- [ ] **S5**: S5-T1 至 S5-T15 全过

## 6. Open Questions（已确认）

- ✅ S5 范围：4 画布全部覆盖
- ✅ S4 深度：删整条链（含 `compute_order_spectrum`、`rpm_res` 字段、batch 入口）
- ✅ 历史 spec 不改写：仅在本 spec §0 显式 supersede

## 7. Squad Brief Hint — 修订后的 wave 划分（codex critical-3 回应）

按 **文件归属** 切分，而不是 feature label。文件归属表：

| 文件 / 目录 | 归属 specialist |
|---|---|
| `mf4_analyzer/signal/**` | signal-processing-expert |
| `mf4_analyzer/batch.py` | signal-processing-expert（与 signal 紧耦合） |
| `tests/test_order_analysis.py` | signal-processing-expert |
| `tests/test_batch_runner.py` | signal-processing-expert |
| `mf4_analyzer/ui/**`（含 drawers）| pyqt-ui-engineer |
| `tests/ui/**` | pyqt-ui-engineer |
| `mf4_analyzer/ui/style.qss` | pyqt-ui-engineer |
| 新建 `_axis_interaction.py` / `_toolbar_i18n.py` | pyqt-ui-engineer |

**Wave 划分（每个 wave 之间是顺序，wave 内部并行）：**

**Wave 1（并行 2 specialist，仅做 S4 删除）：**
- W1-A: signal-processing-expert
  - 删 `signal/order.py` 中 OrderRpmResult / compute_rpm_order_result / compute_order_spectrum / OrderAnalysisParams.rpm_res
  - 改 `signal/__init__.py` 移除 OrderRpmResult
  - 改 `batch.py` 删 order_rpm 入口 / _compute_order_rpm_dataframe / params['rpm_res']
  - 删 `tests/test_order_analysis.py` rpm 相关测试
  - 删 `tests/test_batch_runner.py` order_rpm 测试
- W1-B: pyqt-ui-engineer
  - 改 `inspector_sections.py` 删 OrderContextual.btn_or + spin_rpm_res + order_rpm_requested + 相关 preset 字段
  - 改 `inspector.py` 删 order_rpm_requested 中转
  - 改 `main_window.py` 删 do_order_rpm + _render_order_rpm + OrderWorker rpm 分支 + "当前转速-阶次"
  - 改 `drawers/batch_sheet.py` 删 order_rpm 选项 + spin_rpm_res
  - 改 `tests/ui/test_order_worker.py` 删 _render_order_rpm 测试
  - 改 `tests/ui/test_inspector.py` 删 order_rpm_requested + spin_rpm_res 断言

**Wave 1 codex review gate** —— 必须通过 `pytest tests/` + S4-T1 grep 才能进 Wave 2。

**Wave 2（pyqt-ui-engineer 单线，做 S1 + S2 + S3 + S5）：**
- 新增 `_axis_interaction.py` + `_toolbar_i18n.py`
- 改 `canvases.py` 4 canvas dblclick + hover + S1 常量与 tight_layout 替换
- 改 `chart_stack.py` StatsStrip 显隐 + segmented buttons 中文 + toolbar i18n 调用 + `_find_action` 升级 + `_TOOL_HINTS`
- 改 `inspector_sections.py` `_BUILTIN_PRESET_DISPLAY` 改名 + 注释同步
- 改 `main_window.py` FFT + track tight_layout 替换（这条与 W1-B 的 main_window.py 删除是同文件不同行，时间上 W2 在 W1 之后无冲突）
- 改 `style.qss` toolbar 紧凑
- 新增 4 个 test 文件 + 改既有 `test_inspector.py` preset display name 断言

**Wave 2 codex review gate** —— 通过 S1/S2/S3/S5 全部 acceptance test 才能进 Wave 3。

**Wave 3（pyqt-ui-engineer 单线，验收 + 截图）：**
- 4 模式各跑一次 + 截图归档 `docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/`
- 全量 grep S4-T1
- 全量 pytest

**Wave 3 codex review gate** —— 最终 sign-off。

**记忆原则：每个 wave 必须 codex review 通过才能进下一 wave**（`feedback_squad_wave_review.md`）。
