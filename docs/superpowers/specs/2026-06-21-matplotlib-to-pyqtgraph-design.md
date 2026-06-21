# matplotlib → pyqtgraph 全面替换 设计 (Design Spec)

**日期:** 2026-06-21
**状态:** 待用户评审
**目标读者:** 实现该改动的工程师（pyqt-ui-engineer + signal/batch 经手人）

## 1. 目标

把 `matplotlib` 从项目运行时与依赖中彻底移除，全部出图改走已有的
pyqtgraph 栈。**实时 UI（屏幕上的一切）保持逐像素不变**；唯一可见差异是
**batch 导出的 PNG 图片**会从 matplotlib 观感变为 pyqtgraph 观感（功能、
数据、坐标、标签、colorbar、dB、色阶范围全部保留，仅渲染风格不同）。

回收：matplotlib + 其私有依赖链（fontTools 17.5M、pillow 14.5M、contourpy、
kiwisolver、cycler、pyparsing）≈ **67M**；打包(onedir)体积同步下降。

## 2. ⚠️ 关键保真点：热图色图的运行时 matplotlib 依赖

`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:111 _resolve_colormap` 当前用
`pg.colormap.getFromMatplotlib(name)` 取色图，失败 fallback 到
`pg.colormap.get('viridis')`。**这意味着屏幕上的谱图/阶次热图色图在运行时
就依赖 matplotlib**——裸卸 matplotlib 会让色图从 **turbo 退化成 viridis**，
即一次明显的 UI 变化。这是本计划必须正面解决的命门。

**已验证的解法**：`pg.colormap.get('turbo')` 与 `pg.colormap.get('viridis')`
在当前 pyqtgraph(0.13.x) **原生可用**（`listMaps()` 含 'turbo'，`get` 返回
非 None），无需 matplotlib。色图实际只用到这两个名字（fft_time 已于
2026-06-19 删除可切换控件、固定 turbo；viridis 仅作个别 legacy preset 值）。

**保真要求**：替换 `_resolve_colormap` 后，必须用测试断言 pyqtgraph 原生
turbo/viridis 的 LUT 与 matplotlib 版**逐档一致**（见 §6 测试）。若发现微小
差异，则在仓库内置一份 matplotlib turbo 的 256×4 LUT 数据，由
`pg.ColorMap` 直接构造，保证屏幕色图零变化。

## 3. matplotlib 全量痕迹分类（穷举）

### A. 实时活用（必须替换，影响行为）
| 位置 | 用途 | 处理 |
|---|---|---|
| `heatmap_canvas.py:118` | `getFromMatplotlib` 取色图（**实时 UI**） | 改 `pg.colormap.get`，LUT 等价测试兜底（§2） |
| `dialogs.py:30,921,942,943,957` | `mcolors.to_hex/is_color_like`（取色器） | 换 Qt 原生色串工具，输出 hex 完全一致 |
| `batch.py:724,810,811` | `Figure/tight_layout/savefig`（导出 PNG） | pyqtgraph 离屏导出重写 |
| `app.py:67,69` | `import matplotlib; matplotlib.use("Qt5Agg")` | 删除 |
| `fonts.py:15,16,41,45,49` | matplotlib 中文字体 rcParams | 改为 no-op（Qt 字体另行配置，删此不影响 UI） |

### B. 死分支（运行时不可达，清理）
| 位置 | 说明 |
|---|---|
| `cards.py:9,99` | `NavigationToolbar2QT` import + `else` 分支；实时画布全是 pg 三类，永不进 else |
| `_axis_handle.py` / `_axis_interaction.py` 的 `MplAxisHandle`/`_MplLineHandle`/`make_handle` mpl 分支 | 实时只建 `PgAxisHandle`（line_canvas:1002 等）；mpl 分支仅测试在用 |
| `style.qss:1272-1273` | `NavigationToolbar2QT` 选择器，随 cards 死分支一并失效 |

### C. 仅注释/docstring（不影响功能，顺手更新措辞，非必须）
`_chart_kw.py`、`plot_helpers.py:4`、`canvases.py:3,13,14`、`toolbar.py`、
`window.py:933,940,995`、`heatmap_canvas.py:6` 等——不动代码。

## 4. 架构决策

### 4.1 batch 出图重写（核心工作量）
现状 `BatchRunner._write_image(payload, path, params)`（batch.py:721-814）：
- FFT：`ax.plot` 折线 + xlabel/ylabel + 可选 x/y 范围。
- 谱图：`ax.imshow(turbo, bilinear)` + colorbar + dB(复用
  `SpectrogramAnalyzer.amplitude_to_db`) + 可选 z 范围(vmin/vmax) + x/y 范围。
- 统一 `grid(alpha=0.25, ls='--')` + `tight_layout` + `savefig`。

重写为 pyqtgraph 离屏导出，拆成可测试的三段：
```
_ensure_qapp() -> QApplication
    复用已有 QApplication.instance()；无则按需创建（headless 时配
    QT_QPA_PLATFORM=offscreen）。pyqtgraph 任何 GraphicsItem 都需 QApplication。

_build_export_scene(payload, params) -> (GraphicsLayoutWidget, info: dict)
    构建 PlotItem：
      - FFT: PlotDataItem 折线；setLabel 'bottom'/'left'；setXRange/YRange。
      - 谱图: ImageItem(matrix) + ColorBarItem；setColorMap(pg turbo)；
              dB 经 amplitude_to_db；levels=(z_floor,z_ceiling) 当 not z_auto。
      - showGrid(x=True,y=True,alpha=0.25)。
    info 暴露 {plot_item, image_item, levels, matrix} 供测试断言（替代原来
    对 matplotlib Figure 的 monkeypatch）。

_export_png(widget, path, size=(1120, 630))
    pyqtgraph.exporters.ImageExporter 导出 PNG（8in×4.5in@140dpi≈1120×630）。

_write_image(payload, path, params)  # 对外签名不变
    _ensure_qapp(); w, info = _build_export_scene(...); _export_png(w, path); return path
```
色图复用 §2 的 pyqtgraph 原生 turbo，**绝不重新引入 matplotlib**。

### 4.2 取色器色串工具（dialogs）
新建 `mf4_analyzer/ui/_color_utils.py`：
```python
from PyQt5.QtGui import QColor

def to_hex(c):
    """matplotlib mcolors.to_hex 的等价替代，覆盖实际用到的输入：
    hex/颜色名字符串、(r,g,b[,a]) 0-1 浮点元组。"""
    if isinstance(c, (tuple, list)):
        if all(isinstance(v, float) or 0.0 <= v <= 1.0 for v in c):
            q = QColor.fromRgbF(*[float(v) for v in c[:4]])
        else:
            q = QColor(*[int(v) for v in c[:4]])
    else:
        q = QColor(str(c))
    return q.name()  # '#rrggbb'

def is_color_like(c):
    if isinstance(c, (tuple, list)):
        return 3 <= len(c) <= 4
    return QColor(str(c)).isValid()
```
`dialogs.py` 把 `from matplotlib import colors as mcolors` 换成
`from ._color_utils import to_hex as _to_hex, is_color_like as _is_color_like`，
三处调用相应替换。取色器用户输入恒为字符串(hex/名)，`QColor.name()` 输出
小写 `#rrggbb`，与 mcolors.to_hex 一致（取色器对话框可见行为零变化）。

### 4.3 死分支清理
- `cards.py`：删第 9 行 import 与第 98-99 行 `else: self.toolbar = NavigationToolbar(...)`；
  实时只会进 `PgNavigationToolbar` 分支。若担心防御性，改 `else` 为
  `raise TypeError(f"unsupported canvas: {type(canvas)}")`（永不触发，仅自证不可达）。
- `_axis_handle.py`/`_axis_interaction.py`：删 `MplAxisHandle`、`_MplLineHandle`、
  `make_handle` 的 mpl 分支；`make_handle` 简化为"已是 handle 则透传，否则按 pg 构造"。
  **此项会牵动现有测试**（见 §6），是本计划第二大块。
- `style.qss`：删 `NavigationToolbar2QT#chartToolbar, NavigationToolbar2QT {…}`
  规则块（随 cards 死分支失效）。

### 4.4 字体函数
`setup_chinese_font()`（fonts.py）仅配置 matplotlib rcParams——matplotlib 一走
即无意义。Qt/pyqtgraph 的中文渲染由别处保证（实时 UI 早已正常显示中文）。
改为 no-op（保留函数名与 `__all__`，函数体清空 + 一行注释），`app.py` 调用
保留不动。**对实时 UI 零影响**（Qt 字体不读 matplotlib rcParams）。

## 5. 唯一接受的可见差异（务必让用户知情）

- **batch 导出 PNG 的观感**会变（字体/刻度/colorbar 样式/抗锯齿）。功能完全
  保留：折线/谱图、坐标标签、colorbar、dB 切换、z 范围、turbo、网格。好处是
  导出图从此与屏幕上的 pyqtgraph 谱图风格统一。
- **新约束**：batch 出图从此需要一个 QApplication（matplotlib Agg 不需要）。
  GUI 触发的 batch 天然满足；真无头(CLI/CI)运行需 `QT_QPA_PLATFORM=offscreen`，
  由 `_ensure_qapp()` 兜底。

## 6. 测试影响（关键）

- `tests/test_batch_runner.py`：
  - `test_current_single_fft_preset_exports_image`（断言产出 .png）→ **保持**，新代码仍产 PNG。
  - `test_batch_heatmap_image_applies_xyz_axis_params`（monkeypatch
    `Figure.savefig` 读 `ax.images[0].get_clim()`）→ **改写**为调用
    `_build_export_scene` 并断言 `info['levels'] == (z_floor, z_ceiling)`。
  - `test_batch_heatmap_image_can_render_linear_z_scale`（读 imshow matrix）→
    **改写**为断言 `info['matrix']` 的 linear/dB 取值。
- 色图保真新增 `tests/ui/test_colormap_parity.py`：断言 pg 原生 turbo/viridis
  的 LUT 与"曾经的 matplotlib 版"一致（黄金 LUT 落盘，类比 scipy 方案）。
- `_axis_handle` 相关测试（`tests/ui/test_axis_handle.py`、`test_dialog_with_handle.py`、
  `tests/ui/test_axis_interaction.py`）：删 `MplAxisHandle` 后，**删除/改写**其中
  针对 mpl 分支的用例，仅保留 pg 分支用例。这是清理死代码的连带测试调整。
- `tests/test_signal_no_gui_import.py`：poison `matplotlib.pyplot`——移除后更稳，无需改。

## 7. 受影响文件

改：`batch.py`、`app.py`、`dialogs.py`、`cards.py`、`_axis_handle.py`、
`_axis_interaction.py`、`heatmap_canvas.py`、`ui_kit/fonts.py`、`style.qss`、
`requirements.txt`、`build/spec/MF4DataAnalyzer.spec`（excludes 加 matplotlib 全链）。
新：`ui/_color_utils.py`、`tests/ui/test_colormap_parity.py`、（可选）turbo LUT 数据。
测试改写：`test_batch_runner.py`、`test_axis_handle.py`、`test_dialog_with_handle.py`、
`test_axis_interaction.py`。

## 8. 非目标 (YAGNI)

- 不改任何实时 UI 布局/控件/交互；不改 batch 的导出选项集合。
- 不重写 PgNavigationToolbar（它本就是 pg 实现，名字里有 matplotlib 只是注释）。
- 不为"导出图与旧 matplotlib 像素一致"投入——已明确接受风格切换。

## 9. 验收标准

- [ ] 实时 UI 真机渲染验证（CLAUDE.md 强制）：谱图/阶次热图色图仍是 turbo、
      取色器行为不变、图表工具栏不变——截图/objc 比对，**不得有可见变化**。
- [ ] `tests/ui/test_colormap_parity.py` 证明 turbo/viridis LUT 与 mpl 一致。
- [ ] 全套 `pytest` 绿（含改写后的 batch/axis-handle 测试）。
- [ ] 卸掉 matplotlib 全链后 `pytest` 仍绿、GUI 能启动并正常出谱图。
- [ ] `grep -rn "import matplotlib\|from matplotlib" mf4_analyzer/` 无运行时 import。

## 10. 风险

- **色图 LUT 微差**：若 pg 原生 turbo ≠ mpl turbo，需内置 mpl LUT 数据兜底（§2）。已有应对。
- **axis-handle 死分支牵连测试**：删 MplAxisHandle 可能波及多支测试；按 §6 逐一改写，工作量中等。
- **batch headless QApplication**：离屏导出需 Qt；`_ensure_qapp` 兜底，但若存在纯服务端 batch 调用方需回归确认。
- 工作量：batch 重写 + 色图保真约 1.5 天；死分支与测试清理约 1 天；合计约 2–2.5 天（含真机验证）。
