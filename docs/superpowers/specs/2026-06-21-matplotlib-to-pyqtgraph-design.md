# matplotlib -> pyqtgraph 全面替换设计 (Design Spec)

**日期:** 2026-06-21
**状态:** 执行版（Codex review 后修订）
**目标读者:** 执行 agent、review agent、pyqt-ui-engineer、batch/signal 经手人

## 1. 目标与硬边界

把 `matplotlib` 从项目运行时与必需依赖中彻底移除，所有运行时出图改走已有
pyqtgraph 栈。

硬边界：

- **实时 UI 和按钮接口保持一致**：工具栏、按钮顺序、action key、tooltip、快捷键、
  `chartToolbar` objectName、ChartOptionsDialog 行为、右键菜单和底部提示不得顺手调整。
- **屏幕热图色图保持一致**：FFT-vs-Time / Order 仍使用 turbo；`viridis` 只作为 legacy
  preset / fallback 值保留；未知色图仍 fallback 到 viridis。
- **batch 导出 PNG 唯一允许的可见差异是渲染风格**：字体、刻度、colorbar 外观、抗锯齿可从
  matplotlib 风格变为 pyqtgraph 风格；数据、坐标、标签、dB 转换、z 范围、网格、
  turbo 色图语义必须保留。
- **batch 热图仍固定 turbo**：当前 `BatchRunner._write_image` 硬编码 `cmap='turbo'`，本迁移
  不得开始读取历史 preset 中的 `cmap` 参数，否则属于未授权行为变化。
- `mf4_analyzer.signal` 仍不得 import `PyQt5` / `matplotlib.pyplot`。

预计体积收益来自移除 `matplotlib` 及其仅为 matplotlib 服务的依赖链。`pyparsing`、
`PIL/Pillow` 这类包是否卸载必须以当前依赖图和 tools scope 为准；例如
`tools/build_icons.py` 仍使用 `PIL.Image`，它不是运行时入口，但不能在文档里误写成
“项目全局无需 PIL”。

## 2. 当前证据

### 2.1 运行时 matplotlib import

必须替换或删除：

| 位置 | 当前用途 | 处理 |
|---|---|---|
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:_resolve_colormap` | `pg.colormap.getFromMatplotlib(name)` | 改 `pg.colormap.get(name)`，黄金 LUT 守卫 |
| `mf4_analyzer/ui/dialogs.py` | `matplotlib.colors.to_hex/is_color_like` | 改 Qt 原生 `_color_utils` |
| `mf4_analyzer/batch.py:_write_image` | `Figure/tight_layout/savefig` | pyqtgraph 离屏导出 |
| `mf4_analyzer/app.py` | `matplotlib.use("Qt5Agg")` | 删除 |
| `mf4_analyzer/ui_kit/fonts.py` | matplotlib rcParams 中文字体 | 保留函数名，改 no-op |
| `mf4_analyzer/ui/chart_stack/cards.py` | `NavigationToolbar2QT` fallback | 删除 fallback，未知 canvas 明确报错 |

### 2.2 死分支与测试专用 matplotlib

当前运行时 `_ChartCard` 只由以下 canvas 构造：

- `TimeDomainCanvasPG`
- `PgLineCanvas`
- `PgHeatmapCanvas`

因此 `cards.py` 的 matplotlib toolbar fallback 可以删除，但测试也要同步改：

- `tests/ui/test_toolbar_i18n.py` 必须改为用 `PgNavigationToolbar`，继续验证
  `apply_chinese_toolbar_labels()` 对 `home/back/forward/pan/zoom/save` 的 action data
  和中文 tooltip 保持一致。
- `tests/ui/test_surface_layering.py` 不能再断言 `NavigationToolbar2QT` 选择器存在；
  应断言 `QToolBar#chartToolbar` / `QWidget#chartToolbar` 块仍透明、无边框、无 radius。
- `mf4_analyzer/ui/_toolbar_i18n.py` 的 docstring 可改为泛化的 toolbar i18n，但函数行为和
  action data 不变。

`MplAxisHandle` / `_MplLineHandle` / `_axis_interaction` 的 matplotlib Axes 分支也属于退役
分支。删除它们时，以下测试不能只删断言，必须改成覆盖 pyqtgraph handle 等价行为：

- `tests/ui/test_axis_handle.py`
- `tests/ui/test_dialog_with_handle.py`
- `tests/ui/test_axis_interaction.py`
- `tests/ui/test_dialogs.py`

### 2.3 已验证色图事实

本地 `.venv` 探针结果：

- `pyqtgraph 0.14.0`
- `pg.colormap.get('turbo')` / `pg.colormap.get('viridis')` 原生存在
- 两者 `getLookupTable(0.0, 1.0, 256, alpha=True)` 与
  `pg.colormap.getFromMatplotlib(name)` 完全一致（`array_equal=True`）

因此迁移可以使用 pyqtgraph 原生 turbo/viridis，并把黄金 LUT 落盘，保证卸载 matplotlib
后仍有机械守卫。

## 3. 架构决策

### 3.1 色图 resolver

`_resolve_colormap(name)` 改为：

- 优先 `pg.colormap.get(name)`。
- 仅把当前运行时需要守卫的 `turbo` / `viridis` 纳入黄金 LUT。
- 如果 pyqtgraph 原生 LUT 与黄金 LUT 不一致，则用 `pg.ColorMap(pos, color)` 从黄金 LUT
  构造。
- 未知或不可用色图 fallback 到 `viridis`。
- 迁移结束后 runtime grep 不允许出现 `getFromMatplotlib`。

### 3.2 Qt 原生色串工具

新增 `mf4_analyzer/ui/_color_utils.py`：

- `to_hex(c) -> "#rrggbb"`
- `is_color_like(c) -> bool`

覆盖运行时实际输入：hex 字符串、Qt 支持的颜色名、0-1 float RGB(A) 元组、0-255 int
RGB(A) 元组。`QColor.name()` 输出小写 `#rrggbb`，保持取色器用户可见行为。

### 3.3 Batch pyqtgraph 离屏导出

`BatchRunner._write_image(payload, path, params)` 对外签名不变，内部拆成：

- `_ensure_qapp()`
- `_extract_matrix(data) -> (render_matrix, x_extent, y_extent, x_label, y_label)`
- `_build_export_scene(payload, params) -> (GraphicsLayoutWidget, info)`
- `_export_png(widget, path) -> Path`

矩阵约定必须写死：

- `_Spectro2D.matrix` 是 x-major，shape `(len(x), len(y))`。
- `_extract_matrix(_Spectro2D)` 返回 `render_matrix = matrix.T`，shape `(len(y), len(x))`，
  与旧 matplotlib `imshow(matrix, extent=[x0,x1,y0,y1], origin='lower')` 的输入形状一致。
- `_extract_matrix(legacy DataFrame)` 返回 pivot matrix，shape `(len(y), len(x))`。
- `_build_export_scene` 传给 `pg.ImageItem(render_matrix)`，并用相同 x/y extent。
- `info` 至少暴露 `plot_item`、`image_item`、`levels`、`matrix`、`x_range`、`y_range`、
  `colorbar_label`、`colormap_name`，用于测试替代 matplotlib monkeypatch。

Batch 热图色图固定 turbo；不要读取 `params['cmap']`。如未来要开放 batch cmap，那是单独功能。

### 3.4 UI / 按钮接口冻结

实现 agent 不允许调整以下接口，除非测试因删除 matplotlib 需要把测试对象从 mpl toolbar/axes
换成 pg toolbar/handle：

- `PgNavigationToolbar` action data keys: `home`, `back`, `forward`, `pan`, `zoom`, `save`。
- `_ChartCard` 自定义按钮：图表选项、复制、标注、清空标注、定位/密度相关控件。
- `chartToolbar` objectName 与 QSS 透明/无边框/紧凑 spacing。
- `ChartOptionsDialog` 面向用户的 tab、中文标签、颜色输入、应用/重置/关闭逻辑。
- `edit_chart_options_dialog(parent_widget, handle)` 返回 accepted/applied 布尔语义。

## 4. 测试影响

必须新增或改写：

- `tests/ui/test_colormap_parity.py`：生成/校验 `tests/data/colormap_golden.npz`。
- `tests/ui/test_color_utils.py`：覆盖 `_color_utils`。
- `tests/test_batch_runner.py`：移除 `Figure.savefig` monkeypatch；改测 `_build_export_scene`
  的 `levels`、`matrix`、`x_range`、`y_range`、`colorbar_label`、非空 PNG。
- `tests/test_db_conversion_convergence.py`：继续证明 batch dB path 调用
  `SpectrogramAnalyzer.amplitude_to_db`。
- `tests/ui/test_axis_handle.py`、`tests/ui/test_dialog_with_handle.py`、
  `tests/ui/test_axis_interaction.py`、`tests/ui/test_dialogs.py`：删除 raw matplotlib Axes
  覆盖，改用 `TimeDomainCanvasPG` / `PgLineCanvas` / `PgHeatmapCanvas` 暴露的 `PgAxisHandle`。
- `tests/ui/test_toolbar_i18n.py`：用 `PgNavigationToolbar` 测 action data 和 tooltip。
- `tests/ui/test_surface_layering.py`：更新 chart toolbar QSS contract，不再要求
  `NavigationToolbar2QT`。
- `tests/ui/test_plot_helpers.py`：`_set_series_ylabel` 若只服务退役 matplotlib Axes，可删除对应
  matplotlib 测试或迁移为纯 fake Axes；不要让测试继续要求 matplotlib。
- `tests/perf/test_timedomain_pan_perf.py`：移除 matplotlib warmup；如 offscreen PG 初始化仍需
  warmup，应改成 Qt/pyqtgraph 原生 warmup。
- `tests/test_signal_no_gui_import.py`：保留 poison `matplotlib.pyplot` 的防线。

## 5. 受影响文件

代码：

- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- `mf4_analyzer/ui/_color_utils.py`（新）
- `mf4_analyzer/ui/dialogs.py`
- `mf4_analyzer/batch.py`
- `mf4_analyzer/ui/chart_stack/cards.py`
- `mf4_analyzer/ui/_axis_handle.py`
- `mf4_analyzer/ui/_axis_interaction.py`
- `mf4_analyzer/ui/_toolbar_i18n.py`
- `mf4_analyzer/ui_kit/fonts.py`
- `mf4_analyzer/ui_kit/__init__.py`（docstring only）
- `mf4_analyzer/app.py`
- `mf4_analyzer/ui_kit/style.qss`
- `requirements.txt`
- `build/spec/MF4DataAnalyzer.spec`

测试：

- `tests/ui/test_colormap_parity.py`（新）
- `tests/data/colormap_golden.npz`（新）
- `tests/ui/test_color_utils.py`（新）
- `tests/test_batch_runner.py`
- `tests/test_db_conversion_convergence.py`
- `tests/ui/test_axis_handle.py`
- `tests/ui/test_dialog_with_handle.py`
- `tests/ui/test_axis_interaction.py`
- `tests/ui/test_dialogs.py`
- `tests/ui/test_toolbar_i18n.py`
- `tests/ui/test_surface_layering.py`
- `tests/ui/test_plot_helpers.py`
- `tests/perf/test_timedomain_pan_perf.py`

## 6. 验收标准

- `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest ...`
  运行所有相关 focused tests 通过。
- `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest -q`
  全套通过。
- 卸载/隔离 matplotlib 链后，全套通过；`test_colormap_parity` 走黄金值分支。
- `rg -n "^\s*(from matplotlib|import matplotlib)|getFromMatplotlib|mcolors|NavigationToolbar2QT|MplAxisHandle|_MplLineHandle" mf4_analyzer tests | rg -v "tests/test_signal_no_gui_import.py|tests/ui/test_colormap_parity.py"`
  无运行时/测试强依赖残留。允许的两类测试字符串只有：
  `tests/test_signal_no_gui_import.py` 的 poison `matplotlib.pyplot` 防线，以及
  `tests/ui/test_colormap_parity.py` 的 `getFromMatplotlib` 负向断言。
- 真机 GUI 验证：FFT、FFT-vs-Time、Order、TimeDomain 工具栏、图表选项、取色器、中文显示、
  热图 turbo 观感无变化。
- Batch 导出验证：FFT PNG 与热图 PNG 均非空，尺寸固定；热图坐标、colorbar label、dB/linear、
  z range、turbo 保持语义。

## 7. 风险与应对

- **测试面漏改**：本 spec 把 previously missed tests 列入必改清单，执行 agent 不得只改
  plan 原先列出的三四个测试。
- **batch 行为漂移**：禁止读取 `params['cmap']` 改变 batch 热图色图；必须保持 turbo。
- **Qt offscreen 导出差异**：用非空 PNG / 固定尺寸测试兜底，人工查看 batch 示例图。
- **UI 按钮接口漂移**：toolbar/i18n/surface/dialog focused tests 必跑，真机再验。
- **Pillow / pyparsing scope**：只在确认无运行时和必需工具依赖后才从卸载命令或打包 excludes 中处理。
