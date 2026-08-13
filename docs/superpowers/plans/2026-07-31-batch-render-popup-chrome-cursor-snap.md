# 批处理渲染后端 / 圆角浮层黑边 / 游标吸附 — 优化计划

> **执行者须知：** 步骤用 `- [ ]` 复选框跟踪。本计划来自 2026-07-31 的只读代码
> 调查，**未改动任何产品源码**。三个问题彼此独立，可以分别派工；Issue A 是
> 出货阻断项，优先级最高。

**基线 commit：** `f6ab485`（`docs: record TraceLab 7.9 Windows acceptance`）
**证据来源：** 用户截图（`dist/TraceLab7.9` 冻结包实跑）+ 源码走查
**调查范围：** `mf4_analyzer/batch*.py`、`tools/build_windows_folder*.ps1`、
`mf4_analyzer/ui/drawers/batch/signal_picker.py`、`mf4_analyzer/ui/pg_canvas/cursor.py`

---

## 0. 结论先行

| # | 问题 | 根因 | 性质 |
|---|---|---|---|
| A | 批处理报 `No module named 'matplotlib'` | `batch_render.py` 顶层依赖 matplotlib，但 matplotlib 既不在 `requirements.txt`，又被两个 Windows 打包脚本 `--exclude-module` 显式排除 | **出货阻断**：冻结包的图片/PDF 导出 100% 不可用 |
| B | 下拉浮层有黑边 | `SignalPickerPopup` 是全项目**唯一**一个设了 `WA_TranslucentBackground` 却**没有**配 `FramelessWindowHint \| NoDropShadowWindowHint` 的顶层弹窗；原生方形阴影/边框透过圆角漏出 | 视觉缺陷，已有现成范式可套 |
| C | 游标不吸附真实数据点 | 游标线画在鼠标原始连续 x 上；单游标读数用 `searchsorted`（向上取整、不是最近）；双游标 Δ 用**线性插值**给出数据里根本不存在的值 | 数据可信度问题，会误导用户 |

三个问题有一条共同的元根因：**已有的防护契约存在覆盖盲区**——
A 的冻结依赖契约只扫 `mf4_analyzer/io/`；B 的浮层外壳只自动覆盖 `QComboBox`；
C 的最近点吸附只在 FFT/阶次画布实现了、时域画布没有。修复时必须一并把
"护栏" 扩到盲区，否则下一次照样复发。

---

## Issue A — 批处理 `No module named 'matplotlib'`

### A.1 事实链（全部有源码锚点）

1. `mf4_analyzer/batch_render.py:16-22` 在**模块顶层**导入 matplotlib：
   ```python
   import matplotlib as mpl
   from matplotlib import font_manager, ft2font
   from matplotlib.backends.backend_agg import FigureCanvasAgg
   from matplotlib.figure import Figure
   from matplotlib.text import Text
   ```
2. `requirements.txt` **没有** matplotlib（第 1-27 行逐行确认）。
3. `tools/build_windows_folder.ps1:292` 和 `tools/build_windows_folder_lite.ps1:206`
   都写着 `"--exclude-module", "matplotlib"`，注释是
   *"TraceLab no longer uses matplotlib"* —— **这个前提是错的**，
   `batch_render.py` 仍然是纯 matplotlib 实现。
4. 实测冻结包：`dist/TraceLab7.9/_internal` 下 `find -iname "*matplotlib*"`
   **零命中**，整包 666 MB。
5. 触发路径：`batch.py:1630`
   `from .batch_render import BatchRenderContext, BatchRenderOptions`
   位于 `if preset.outputs.export_image:` 分支内 → 用户勾选了「图片 / PDF」
   就必然走到 → `ImportError`。
6. 错误被 `batch.py:944` 的 `except Exception` 捕获，原样拼成
   `f"{fname}:{signal_name}: {exc}"`；三个任务全失败 →
   `batch.py:965-968` 判定 `status='blocked'` →
   `ui/drawers/batch/sheet.py:1074` 弹出截图里那个对话框。

### A.2 为什么测试没拦住 —— 这是**测试主动锁死了错误状态**

`tests/test_windows_build_script.py:156`：

```python
assert '"--exclude-module", "matplotlib"' in full_build
```

这条断言把「排除 matplotlib」写成了契约。同一个文件 147-152 行对 scipy/h5py
做的却是**反向**断言（`not in` + 必须在 requirements）。也就是说
matplotlib 被当成了"已退休"的历史包袱，而实际上它是 batch 导出的运行时依赖。

同时 `mf4_analyzer/io/runtime_dependencies.py:185-193` 的懒导入扫描器
**只扫 `mf4_analyzer/io/` 目录**：

```python
lazy_modules = lazy_import_dependency_roots(
    Path(requirements_path).parent / "mf4_analyzer" / "io"
)
```

`batch_render.py` 在包根目录，天然在扫描范围外。

> 这与 `docs/lessons-learned/codex-frozen-import-dependency-contract.md` 记录的
> scipy/`.mat` 事故是**同一个 failure mode**：
> *"The source could read MAT files, but the frozen EXE could only show the
> misleading 'install scipy' message."* 当时的修复只把护栏建在了 `io/`。

### A.3 附带缺陷：图片后端故障连带炸掉 CSV

用户勾选了「数据文件 + 图片」，`3 任务 · 6 输出`，实际产出 **0 个文件**。
原因：`batch.py:1630` 的 import 发生在 `atomic_write_set`（1682 行附近）
**之前**，异常抛出时数据写入器根本没被调用。CSV 导出不需要 matplotlib，
却被图片依赖拖死。

同时错误文案是裸的 Python 异常字符串。用户看到 `No module named 'matplotlib'`
无法判断该做什么——这正是上面那条 lesson 说的 *"misleading message"*。

### A.4 方案

**Track A（立刻做，出货阻断）：把 matplotlib 恢复为申明的运行时依赖。**

体积代价实测：matplotlib 31.9 MB；PIL 16 MB **已在包内**（`_internal/PIL`）；
kiwisolver 0.2 MB + pyparsing 1.0 MB。净增约 **+33 MB / 666 MB ≈ 5%**。
用 5% 体积换回一个完全不可用的出货功能，是明确划算的。

**Track A+（推荐，替代 Track B 的绝大部分价值）：留着 matplotlib，只把配色改成
和应用内画布一致。** 详见 §A.8。关键洞察：**"看起来像同一个产品"取决于样式常量，
不取决于渲染后端**。批处理输出现在是深色、应用内是白色，这个差距用
`batch_render.py` 里 ~10 行常量就能抹平，不需要动后端、不碰线程、不推翻架构契约。

**Track B（移植到 Qt，见 §A.7）：降级为可选。** 只有当你需要
"回收 33 MB" 或 "像素级完全一致" 时才值得投那几周。

### A.5 任务

- [ ] **A-1** `requirements.txt` 加 `matplotlib`，注释写明用途
      （*batch image/PDF export — `mf4_analyzer/batch_render.py`*）。
- [ ] **A-2** 删除两个打包脚本的 `"--exclude-module", "matplotlib"`
      （`build_windows_folder.ps1:292`、`build_windows_folder_lite.ps1:206`），
      并订正上方那句已失效的注释。
- [ ] **A-3** **反转 `tests/test_windows_build_script.py:156` 的断言**：
      改成两个脚本都 `'"--exclude-module", "matplotlib"' not in text`，
      且 `"matplotlib" in requirements`——与 147-152 行的 scipy/h5py 写法对齐。
- [ ] **A-4** **补护栏（关键，防复发）**：把 matplotlib 登记进
      `mf4_analyzer/io/runtime_dependencies.py` 的依赖契约。
      现有 `FrozenImportDependency` 以"文件扩展名"为键，matplotlib 不属于导入器；
      两个选项，**推荐 (b)**：
      - (a) 复用 `FROZEN_IMPORT_DEPENDENCIES`，`extensions=()`，`purpose="batch image/PDF export"`；
      - (b) **新增一张 `EXPORT_RUNTIME_DEPENDENCIES` 表**，语义是"非导入器的运行时依赖"，
        与导入器表分开，但共用 `validate_windows_packaging_contract` 的
        requirements 检查 + `--exclude-module` 反向检查。
- [ ] **A-5** **扩大懒导入扫描范围**：`validate_windows_packaging_contract`
      当前只扫 `mf4_analyzer/io`（185-193 行）。扩到至少
      `mf4_analyzer/`（顶层 `batch*.py`）。注意扫描器目前只看**函数内**的
      import（`lazy_import_dependency_roots` 的 docstring 明说顶层 import
      对 PyInstaller 静态图可见）——但**顶层 import 遇到 `--exclude-module` 一样死**，
      所以本次还要加一条**独立检查**：任何被 `--exclude-module` 的包，
      不得出现在 `mf4_analyzer/**/*.py` 的任何 import 中（顶层或函数内）。
      这条检查才是真正能拦住这次事故的那条。
- [ ] **A-6** **解耦数据导出与图片后端**（`batch.py:1620-1690`）：
      把 `from .batch_render import ...` 提到任务开始处做一次**可用性探测**，
      渲染后端不可用时——
      - 数据导出照常写盘（不再 0 输出）；
      - 该任务标 `partial` 而非 `failed`；
      - `warnings` 里记一条产品化文案，例如
        `图片/PDF 导出后端不可用（缺少 matplotlib），本次仅导出数据文件`。
- [ ] **A-7** **产品化错误文案**：`batch.py:944` 目前直接拼 `str(exc)`。
      对 `ImportError`/`ModuleNotFoundError` 单独映射成可行动文案，
      不要把裸异常抛给终端用户。
- [ ] **A-8** 重新出 Windows 包，实机跑一遍用户截图里的同一批任务
      （3 文件 × `EpsDrvrSteerTq`，CSV + PDF），确认 6 个输出全部落盘。

### A.6 同类问题排查（本次一并做）

- [ ] **A-9** 全仓审计"源码用了、但打包排除了"的包。命令：
      ```bash
      grep -rn '"--exclude-module"' tools/build_windows_folder*.ps1
      ```
      逐个拿到被排除的模块名，再 `grep -rn "^import <mod>\|^from <mod>" mf4_analyzer/`
      反查。**已知需要重点确认的**：`scipy`（lite 版排除了
      `scipy.signal`/`scipy.fft` 等 10 个子模块，见
      `runtime_dependencies.py:92-103`——确认 `mf4_analyzer/signal/` 没有任何路径
      依赖这些子模块）、`pyxcp`/`pya2l`（lite 版排除，确认采集入口确实是惰性且有 guard）。
- [ ] **A-10** 确认 `tools/*.py` 里那几个 matplotlib 脚本
      （`fft_welch_compare.py`、`order_nfft_compare.py`、`order_render_compare.py`、
      `_screenshot_order_pg_migration.py`）是纯开发工具、不进包——是的话
      在 A-9 的审计报告里标注为"已知豁免"，避免下次误判。

---

## A.7 Track B 可行性专章 — matplotlib → Qt 能不能做到"和 timedomain plot 一样"

**结论：技术上能做，但不是换后端那么简单——它要反转一条被测试钉死的架构边界，
并且必须绕开一个线程亲和性硬约束。周级工作量，需要先做 spike 验证。**

### A.7.1 三个硬约束（都有源码锚点）

**约束 1 — 现有测试明确禁止 batch_render 碰 Qt。**
`tests/test_batch_renderer.py:639-646`：

```python
def test_renderer_source_is_gui_framework_free():
    source = inspect.getsource(renderer)
    for forbidden in ("PyQt", "pyqtgraph", "QApplication", "QWidget", "QPixmap"):
        assert forbidden not in source
```

这是**有意设计的边界**，不是疏漏。Track B 等于推翻它——推翻可以，但必须
明确知道自己在推翻什么，并给出替代的安全保证（见约束 2）。

**约束 2 — 批处理跑在工作线程，不是 GUI 线程。**
`ui/drawers/batch/runner_thread.py:17` `class BatchRunnerThread(QThread)`。
Qt 的线程规则决定了可用/不可用的 API：

| API | 工作线程可用？ |
|---|---|
| `QWidget` / `QWidget.grab()` / `QPixmap` | ❌ 仅 GUI 线程 |
| `QImage` + `QPainter` | ✅ |
| `QPdfWriter` / `QSvgGenerator`（QPaintDevice） | ✅ |
| `QGraphicsScene.render()` | ⚠️ reentrant，非 thread-safe；须全程限定在单线程内 |

**直接后果**：现成的离屏导出 `ui/pg_canvas/renderer.py:827 grab_pixmap()`
走的是 `QWidget.grab()` → 返回 `QPixmap`（见 836-841 行注释），
**在批处理线程里不能用**。不能指望"复用已有的复制为图片路径"。

**约束 3 — 矢量输出会退化。**
当前支持 png/svg/pdf 三种（`batch_image_options.py:8`），matplotlib 的
PDF/SVG 是**真矢量**。用户截图里选的正是 PDF。任何走 widget grab 的方案
只能得到"位图套在 PDF 壳里"，打印质量是实打实的回归。
只有 `QGraphicsScene → QPainter → QPdfWriter` 这条路能保住矢量。

### A.7.2 一个用户可能没注意到的事实：现在的批处理输出是**深色**的

| 表面 | 背景色 | 锚点 |
|---|---|---|
| 批处理导出图 | `#101418`（深色）+ `#e6edf3` 标签 + `#6b7785` 轴线 | `batch_render.py:146`、`_style_axis` 224-232 |
| 应用内时域画布 | `#ffffff` | `canvas.py:303` |
| 应用内 FFT 画布 | `#ffffff` | `line_canvas.py:165` |
| 应用内热图画布 | `#ffffff` | `heatmap_canvas.py:824` |

所以"效果和 timedomain plot 相同"**不只是换渲染后端，还包含深色→浅色的
视觉改版**。这其实是好消息：不需要去像素级复刻旧输出，可以直接以应用内画布
为准绳。

### A.7.3 三个方案

| 方案 | 做法 | 视觉parity | 矢量 PDF | UI 不卡 | 风险 |
|---|---|---|---|---|---|
| **1. 回 GUI 线程渲染** | 工作线程算完 payload，marshal 回 GUI 线程用真画布 `grab_pixmap` | ✅ 天然一致（同一批类） | ❌ 位图 | ❌ 批量任务会冻住 UI | 低 |
| **2. 工作线程内裸 `QGraphicsScene`**（推荐） | pyqtgraph 的 `PlotItem`/`PlotDataItem`/`ImageItem`/`AxisItem` 都是 QGraphicsItem，放进**不带 QGraphicsView** 的 scene，`scene.render(painter)` 分别打到 `QImage`/`QSvgGenerator`/`QPdfWriter` | ✅ 复用 pg 的轴/刻度/曲线机制 | ✅ | ✅ | **中**——需 spike 验证 scene 在工作线程的稳定性 |
| **3. 独立渲染子进程** | 常驻子进程 + offscreen `QApplication`，可用真画布 widget | ✅ | ✅ | ✅ | 中——冻结包里的子进程拉起 + payload IPC |

**方案 1 不推荐**：同时丢矢量和响应性，只换来"实现简单"。

**推荐路线：先做方案 2 的 spike；spike 失败则退方案 3。**
项目已有子进程探针的先例（`tools/build_windows_folder.ps1` 的
`--acquisition-runtime-smoke` 子进程链），方案 3 不是从零开始。

### A.7.4 移植面清单（不能漏的）

- 四种 kind：`time` / `fft` / `fft_time` / `order_time`（`batch_render.py:33`）。
  应用内已各有对应画布：`canvas.py` / `line_canvas.py` / `heatmap_canvas.py`。
- 热图：matplotlib `imshow` + `figure.colorbar`（`batch_render.py:331,348`）
  → pg `ImageItem` + `ColorBarItem`。`heatmap_canvas.py:842` 已有
  `_SmoothImageItem`（"honors mpl-style interpolation hints"），可直接借。
  **colormap 必须过 `tests/ui/test_colormap_parity.py`。**
- **CJK 字体覆盖**：`batch_render.py:34-55` 的 `_CJK_FONT_CANDIDATES` +
  `_font_file_supports_contract`（真的去验字形覆盖，不是只按名字挑）。
  Qt 侧要用 `QFontDatabase` 重建等价逻辑。
  见 `docs/lessons-learned/batch-render-cjk-glyph-coverage.md`——**这条曾经出过事故**。
- **PDF 元数据**：`_render_metadata`（`batch_render.py:684`）。
  `QPdfWriter` 的 setter 比 matplotlib 少，可能丢字段——**需提前确认哪些留不住**。
- facts 页脚 `_apply_figure_context`（521 行）、dB 参考标签、坐标轴范围
  `_apply_axis_limits`（510 行）。
- **防漂移**：必须抽一个共享 style 模块（笔色/网格 alpha/刻度密度/字体），
  让实时画布和批处理渲染器**消费同一份**，否则两个表面必然再次分叉——
  这正是当前深色/浅色分叉的成因。

### A.7.5 Track B 任务（独立立项，不进本轮）

- [ ] **B0-1** **Spike（先做这个，再决定要不要立项）**：写一个 ~100 行的脚本，
      在 `QThread` 里建裸 `QGraphicsScene` + 一个 pg `PlotItem`，
      分别 render 到 `QImage` / `QPdfWriter`，Windows + macOS 各跑 500 次。
      **判据**：无崩溃、无 Qt 线程警告、PDF 是矢量（能选中文字/放大不糊）。
- [ ] **B0-2** spike 通过 → 写 design spec（`docs/superpowers/specs/`），
      含共享 style 模块的接口、PDF 元数据取舍、CJK 字体策略。
- [ ] **B0-3** spike 失败 → 改评估方案 3（子进程），重跑 B0-1 判据。
- [ ] **B0-4** 实施后更新 `tests/test_batch_renderer.py:639` 的架构契约测试：
      从"禁止 Qt"改成"禁止 `QWidget`/`QPixmap`/`QApplication`（线程不安全的那些），
      允许 `QImage`/`QPainter`/`QGraphicsScene`"——**边界要收窄、不能直接删掉**。
- [ ] **B0-5** Track B 落地并验收后，才把 matplotlib 从 `requirements.txt`
      和依赖契约里移除，回收那 33 MB。

---

## A.8 Track A+ — 留 matplotlib，只改配色（推荐路线）

### A.8.1 为什么这条路更划算

把两个被混在一起的目标拆开：

| 目标 | Track A（打包 matplotlib） | Track A+（再改配色） | Track B（Qt 移植） |
|---|---|---|---|
| 批处理能出图 | ✅ 4 处改动 | ✅ | ✅ |
| 输出看起来像 timedomain | ❌ 仍是深色 | ✅ **~10 行常量** | ✅ |
| 像素级完全一致 | ❌ | ❌ | ✅ |
| 回收 33 MB | ❌ | ❌ | ✅ |
| 工作量 | 小时级 | **天级** | **周级** |
| 风险 | 无 | 无 | 线程安全 + 架构契约 + 矢量 PDF |

**"效果和 timedomain plot 相同"这个诉求，90% 落在配色/字体/网格这些样式常量上，
不落在渲染引擎上。** matplotlib 完全画得出白底、同色板、同网格密度的图。
拿不到的只是"和 pyqtgraph 逐像素相同"（抗锯齿算法、刻度选择算法、
字体栅格化都不一样）——但那从来不是产品诉求。

### A.8.2 差距清单（全部有锚点，逐项可改）

| 元素 | 应用内画布 | 批处理当前 | 锚点 |
|---|---|---|---|
| 背景 | `#ffffff` | `#101418` | `canvas.py:303` vs `batch_render.py:146` |
| 轴线 | `#9ca3af` w=1.0 | `#6b7785` | `_axis_handle.py:12-13` vs `batch_render.py:229-230` |
| 刻度文字 | 随主题（浅色底深字） | `#d9e1e8` | `batch_render.py:226` |
| 轴标签 | 同上 | `#e6edf3` | `batch_render.py:227-228` |
| 网格 | alpha `0.28` | `#708090` alpha 0.25 w 0.7 | `canvas.py:880` vs `batch_render.py:231` |
| 曲线配色 | `_PALETTE` 12 色 Open Color，**按通道分配并存进 `ViewState.colors`** | mpl 默认色循环；FFT 写死 `#f2f5f7` | `view_state.py:25` vs `batch_render.py:283` |
| 热图 colorbar | 走 colormap parity | `#e6edf3`/`#d9e1e8`/`#6b7785` | `batch_render.py:349-351` |

**最有价值的一项是曲线配色**：应用内每个通道的颜色是用户可见、可改、
并且**存档在 `ViewState.colors` 里**的。批处理现在完全不读它，用 matplotlib
默认色循环——所以同一个通道在应用里是蓝的、导出的图里可能是橙的。
这比深浅色更容易让人对不上号。

### A.8.3 任务

- [ ] **A+1** 抽 `mf4_analyzer/ui/chart_style.py`（或放 `ui_kit/`）作为
      **唯一样式真相源**：背景、轴线色/宽、网格 alpha、`_PALETTE`、字体族。
      `_axis_handle.py`、`canvas.py`、`view_state.py` 改为从这里取；
      `batch_render.py` **也从这里取**。
      —— 这一步是防止两个表面再次分叉的结构性护栏，**不能省**。
- [ ] **A+2** 改 `batch_render.py:146` figure facecolor +
      `_style_axis`（224-232）全套配色为浅色主题。
- [ ] **A+3** `_render_time`（234-262）按通道从 `_PALETTE` 取色，
      并支持从 `BatchRenderContext` 传入 `ViewState.colors` 的实际分配，
      让导出图与应用内**同一通道同一颜色**。
- [ ] **A+4** `_render_fft`（283 行写死的 `#f2f5f7`）同样改为走色板。
- [ ] **A+5** 热图 colorbar 配色（349-351）改浅色；
      **`tests/ui/test_colormap_parity.py` 必须仍绿**。
- [ ] **A+6** 更新 `tests/test_batch_renderer.py` 中所有断言了深色值的用例。
- [ ] **A+7** 视觉验收：同一个通道，应用内截图 vs 批处理导出图并排比对，
      确认背景/轴/网格/曲线色一致。**这是人眼判据，不是单测判据。**

### A.8.4 Track A+ 之后 Track B 还剩什么

只剩两件事：**回收 33 MB**，和**像素级一致**。
如果这两件对产品都不关键，**Track B 可以直接不做**。

---

## Issue B — 下拉浮层黑边

### B.1 根因

`mf4_analyzer/ui/drawers/batch/signal_picker.py:186-196`：

```python
self._popup = QFrame(self, Qt.Popup)              # ← 只有 Qt.Popup
self._popup.setAttribute(Qt.WA_TranslucentBackground, True)
self._popup.setFrameShape(QFrame.StyledPanel)     # ← 原生 style 会画 panel 边框
self._popup.setStyleSheet(
    "#SignalPickerPopup {background:#fff; border:1px solid #cbd5e1;"
    " border-radius:8px;}"
)
```

三个叠加因素：

1. **缺 `Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint`。**
   Windows 下 `Qt.Popup` 顶层窗口带原生投影/边框；配上
   `WA_TranslucentBackground` 后，圆角半径之外那圈本该透明的区域被原生
   chrome 画成不透明黑色——就是截图里那个方形黑边。
2. **`QFrame.StyledPanel`** 让原生 style 在 QSS 之外**另外**画一层 panel 边框，
   与 `combo_popup_shell.py` 注释里记录的
   *"`QComboBoxPrivateContainer` still paints a 1px square frame in its own
   paintEvent (via the style, independent of `frameShape`)"* 是同一类。
3. `WA_TranslucentBackground` 单独使用不够——这正是 `CLAUDE.md` Gotchas 里
   那条 *"`WA_TranslucentBackground` 会让本体 QSS 失效 → 需 `paintEvent`
   或内部子 widget 兜底"*。

### B.2 关键证据：它是全项目唯一的例外

`grep -rn "Qt\.Popup|Qt\.ToolTip|FramelessWindowHint" mf4_analyzer` 结果，
**其它每一个**顶层浮层都配齐了那两个 flag：

| 文件 | flags |
|---|---|
| `ui/chart_stack/toolbar.py:25` | `Qt.Popup \| Frameless \| NoDropShadow` |
| `ui/pg_canvas/context_menu.py:869` | `Qt.Popup \| Frameless \| NoDropShadow` |
| `ui/pg_canvas/context_menu.py:291` | `Frameless \| ...` |
| `ui/drawers/rebuild_time_popover.py:26` | `Qt.Dialog \| Frameless \| NoDropShadow` |
| `ui/inspector_sections/presets.py:43` | `Qt.ToolTip \| Frameless \| NoDropShadow` |
| `ui/quickref_panel.py:407,657` | `Qt.Tool \| Frameless \| NoDropShadow` |
| `ui/markup/editor.py:450`、`ui/widgets/__init__.py:1184` | `Frameless \| ...` |
| `ui_kit/menus.py:12`、`ui_kit/combo_popup_shell.py:15` | `Frameless \| NoDropShadow` |
| **`ui/drawers/batch/signal_picker.py:186`** | **仅 `Qt.Popup`** ← 唯一例外 |

`docs/lessons-learned/codex-rounded-qt-popups-need-translucent-shell.md` 已经把
规则写死了，并明确指出："combo 由事件过滤器统一兜底，但**新的 popup 类型**
（自定义 `QMenu`、`Qt.Popup` `QWidget`、frameless `QDialog`）仍需手工套外壳。"
`SignalPickerPopup` 就是漏网的那个自定义 `Qt.Popup` QWidget。

### B.3 同类问题（一并处理）

- `ui_kit/glass_tooltip.py:18` — `Qt.ToolTip | Qt.FramelessWindowHint`，
  **缺 `NoDropShadowWindowHint`**。全应用 tooltip 都走它，Windows 下
  `Qt.ToolTip` 同样有原生投影窗口类。列为次要嫌疑，需实机截图确认。
- 同一份 lesson 结尾自己留了个 TODO：
  *"the type-ahead completer popup of editable combos (`SearchableComboBox`)
  is a separate top-level surface not yet covered"* —
  `ui_kit/widgets/searchable_combo.py` 的 completer popup 仍未覆盖。
  注意 `combo_popup_shell.py:141-151` 的 `_popup_views()` **已经**把
  `completer().popup()` 收进来了，但只有当 completer 在
  `prepare_combo_popup` 触发时刻已存在才生效——需要验证时序。

### B.4 方案

在 `ui_kit/` 提炼一个**公共外壳函数**，让"新 popup 类型"不再靠人记：

```python
# mf4_analyzer/ui_kit/popup_shell.py（新建，或并入 combo_popup_shell.py）
POPUP_SHELL_FLAGS = Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint

def apply_rounded_popup_shell(widget, *, base_flags=Qt.Popup):
    """给自定义圆角浮层套统一外壳：无边框 + 无原生投影 + 透明底。"""
```

`combo_popup_shell._SHELL_FLAGS`、`ui_kit/menus.py` 的
`apply_rounded_menu_chrome()` 都改为引用同一个常量，避免三份复制。

### B.5 任务

- [ ] **B-1** 新建 `mf4_analyzer/ui_kit/popup_shell.py`（或扩展
      `combo_popup_shell.py`）导出 `POPUP_SHELL_FLAGS` +
      `apply_rounded_popup_shell()`。让 `combo_popup_shell._SHELL_FLAGS`
      与 `ui_kit/menus.py` 复用同一常量。
- [ ] **B-2** 修 `signal_picker.py:186-196`：
      `QFrame(self, Qt.Popup | POPUP_SHELL_FLAGS)`；
      `setFrameShape(QFrame.NoFrame)`（去掉 `StyledPanel`）；
      保留现有 `#SignalPickerPopup` 圆角 QSS 作为可见内表面。
- [ ] **B-3** 实机截图确认 `glass_tooltip.py:18` 是否同样漏黑边；
      是则补 `NoDropShadowWindowHint`。**不要凭代码相似性直接改**——
      `Qt.ToolTip` 与 `Qt.Popup` 的原生窗口类不同，先看再改。
- [ ] **B-4** 验证 `SearchableComboBox` completer popup 的时序覆盖，
      补上 lesson 里留的 TODO。
- [ ] **B-5** 回归测试：`tests/ui/test_combo_popup_shell.py` 加一条
      **flag 断言**覆盖 `SignalPickerPopup`（`windowFlags()` 含两个 hint、
      `frameShape() == NoFrame`）。
- [ ] **B-6** **实机像素验证**（`CLAUDE.md` 硬性要求）：Windows 上真跑
      批处理对话框、展开信号下拉，截图确认圆角外无黑边。
      **属性断言通过 ≠ 修好**——这条在 lesson 里被专门点名过。

---

## Issue C — 游标不吸附到最近真实数据点

### C.1 现状：三处各不相同、互相矛盾

**(1) 游标线画在鼠标原始连续坐标上——完全不吸附。**
`ui/pg_canvas/cursor.py:360-372`：

```python
data_pos = handle.view_box.mapSceneToView(scene_pos)
x = float(data_pos.x())      # 像素反投影出的连续 x，与采样点无关
```

单游标 `cursor.py:394-400`、双游标 `cursor.py:412-428` 都直接用这个 `x`
定位 `InfiniteLine`，并把它当 A/B 存进 `self._ax` / `self._bx`。

**(2) 单游标读数用 `searchsorted`——向上取整，不是最近点。**
`cursor.py:555`：

```python
idx = min(np.searchsorted(tf, x), len(sf) - 1)
```

`np.searchsorted` 默认 `side='left'`，返回**第一个 ≥ x 的下标**，
即永远向**右**取整。最大误差是一整个采样间隔，且**系统性偏向一侧**。
正确的最近点要比较 `tf[idx-1]` 与 `tf[idx]`。
同时第 549 行显示的是 `t={x:.4f}s`——**原始鼠标 x**，与实际取值的
`tf[idx]` 不是同一个时刻。用户看到的时间戳和幅值来自两个不同的时刻。

**(3) 双游标 Δ 用线性插值——报的是数据里不存在的值。**
`cursor.py:605-607` → `plot_helpers.py:135-150`：

```python
delta = _interp_cursor_value(tf, sf, self._bx) - _interp_cursor_value(tf, sf, self._ax)
# _interp_cursor_value 内部：return float(np.interp(float(x), t, sig))
```

对振动/扭矩这类信号，两点之间线性插值出来的数值是**虚构的**。
这是用户说的"误导"最严重的一处。

**(4) 内部已经自相矛盾。** 同一个函数里，双游标的极值标记
（`cursor.py:595-603`）用的是 `tf[min_idx]` / `sf[min_idx]`——**真实采样点**，
而游标线本身却在采样点之间。绿点/红点落在曲线上，游标线落在两点之间。

**(5) 窗口统计不稳定。** `cursor.py:586` 的 `m = (tf >= xlo) & (tf <= xhi)`
用的是原始连续边界，鼠标挪 1 px 就可能纳入/剔除一个采样点，
Min/Max/Avg 会跳变。

### C.2 反证：FFT/阶次画布**已经**做对了

`ui/pg_canvas/line_canvas.py:1719-1734`：

```python
idx = int(np.argmin(np.abs(freq_arr - freq)))    # 真·最近点
rows.append((label, float(freq_arr[idx]), float(amp_arr[idx])))
#                   ^^^^^^^^^^^^^^^^^^^ 报的是吸附后的 x
```

所以**时域画布是全项目唯一没做最近点吸附的画布**，而且 line_canvas
连"报吸附后的 x"这一点都做对了。这既是佐证，也是现成的参考实现。

### C.3 设计（需要用户拍板的点已标出）

**C.3.1 吸附锚点通道 —— 多通道叠加时吸附到谁？**

时域可叠加多个采样率不同的通道，"最近的数据点"因此有歧义。方案：

> 在**可见**通道中，取"最近采样点到鼠标的**像素** x 距离"最小的那个通道
> 作为锚点通道，把游标吸附到它的那个采样点时刻 `t_snap`。

用像素距离而非数据单位距离，才对混合采样率/混合量纲成立。
其余通道的读数各自取**自己**离 `t_snap` 最近的采样点
（即 line_canvas 的 `readout_at` 语义）——这样**每一个显示出来的数字
都是真实测量值**，不存在插值虚构。

必须排除隐藏通道：`cursor.py:521-545` 的 `_hidden_channel_names()`
已有现成逻辑，直接复用。

**C.3.2 吸附半径 —— 【已定】无半径，永远吸附**

**决策（2026-07-31，用户确认）：不设 pick radius，无论多远都吸附到最近采样点；
读数里不得出现"无采样点"之类的提示。** 任何时刻显示出来的数字都必须是真实
测量值，不存在"这里没有点"这种状态。

实现上这反而更简单：`snap_cursor_x` 不需要距离阈值分支，永远返回
`(t_snap, anchor_channel)`。

> 行为说明（不是反对意见，只是要知情）：对采样稀疏的事件型通道（比如某个
> 只在特定条件下发的 CAN 信号），如果鼠标停在一段很长的数据空洞中间，
> 游标线会明显跳到远处那个采样点上。这是"永远吸附"的必然表现，按决策执行。

**C.3.3 开关策略 —— 【已定】默认开、持久化、可关**

- **默认开启**，并**持久化**（QSettings）——用户重启后仍然是开。
- **保留关闭入口**：在游标模式分段控件（`ui/chart_stack/cards.py:914`
  `游标关 / 单游标 / 双游标`）的右键菜单，以及图表选项对话框里，
  挂一个 `游标吸附到数据点` 勾选项。
- 额外提供 **Alt 临时关闭**（按住期间自由定位），不改变持久化设置。

**C.3.4 每通道取值语义 —— 需要确认的一个专业细节**

锚点通道定了 `t_snap` 之后，其余通道取自己**最近**的采样点。但测量工具领域
对**异步/事件型**通道（CAN 报文）通常用的是另一套：**sample-and-hold
（取 `t_snap` 之前最后一个采样点，零阶保持）**——因为 CAN 信号在两条报文之间
物理上就是保持前值不变，取"最近"可能取到一个当时还没发出来的未来值。

有意思的是，当前代码的 `searchsorted(side='left')` 取的恰恰是**下一个**采样点，
即 ZOH 的反面——两头都不占。

建议：**先统一实现"最近"**（符合本次决策、语义简单一致），把 ZOH 作为
后续可选项。若要区分，需要通道级的"连续采样 vs 事件采样"元数据，
`fd.channel_metadata` 是否携带这个信息需要另行确认。

**C.3.5 性能红线**

鼠标移动已限流 30 Hz（`cursor.py:386-389`，33 ms）。
**不能**用 `np.argmin(np.abs(tf - x))`——那是 O(n)，千万级采样点每次移动
全数组扫描会卡死。必须走 `np.searchsorted`（O(log n)）+ 比较左右两个邻居。
非单调时间轴才回退 `argmin`；单调性判定复用已有的
`canvas.py:366` `_channel_is_monotonic` / `overlay_axes.py:313`
`_cached_is_monotonic`，不要另建缓存。

**C.3.6 必须对全量序列吸附，不能对抽稀后的曲线吸附**

`renderer.py` 为渲染做了 bucket 抽稀，`pdi.getData()` 返回的是抽稀结果。
吸附必须读 `self.channel_data`（`cursor.py:551` 确认持有完整 `tf`/`sf`），
否则会吸到"屏幕上的点"而不是"真实数据点"，问题更隐蔽。

### C.3.7 行业惯例参考 —— 游标读数应该读真实数据点吗？

**是的。这是测量/分析工具领域的主流约定，本次决策与之一致。**

| 工具 | 默认行为 |
|---|---|
| MATLAB `datacursormode` | 默认 **Snap to Data Vertex**（吸附到数据顶点）；`Interpolate` 是需要显式打开的选项 |
| NI DIAdem | 游标模式区分 **free / snap to points**，数据读取默认吸附 |
| Origin / Igor Pro | **Data Reader** 工具吸附数据点；读自由坐标是**另一个**工具（Screen Reader），两者不混用 |
| Vector CANape / vSignalyzer、ETAS INCA-MDA | 测量游标落在真实采样上（异步通道走 sample-and-hold） |
| 示波器（Tek / Keysight / LeCroy） | 放大到记录内部时游标按采样步进；track 模式把 Y 游标锁在波形上 |
| Plotly / Bokeh hover | `closest` 命中最近数据点并报该点的真实值 |
| matplotlib `mplcursors` | 对线条 artist 默认吸附数据点 |

提炼出来的两条通行规则：

1. **读数报的必须是真实测量值；插值是 opt-in 且必须显式标注。**
   —— 当前双游标 Δ 走 `np.interp`（`cursor.py:605`）静默给出虚构值，
   在这个惯例下是明确错误的。
2. **"读数据"和"读坐标"是两种不同的工具/模式，不该混在一个游标里。**
   —— Origin 把它们做成两个工具，DIAdem 做成两个模式。
   本项目对应的就是 C.3.3 的那个开关：默认"读数据"，可切到"读坐标"。

另外值得注意：**本项目的 FFT/阶次画布本来就是按这个惯例做的**
（`line_canvas.py:1726` 真最近点 + 报吸附后的 x）。所以这次不是引入新范式，
而是**把时域画布拉回项目内已有的、也是行业通行的那条线**。

### C.4 任务

- [ ] **C-1** 在 `plot_helpers.py` 新增
      `nearest_sample_index(t, x, *, is_monotonic=True) -> int`：
      `searchsorted` + 左右邻居比较，非单调回退 `argmin`。
      **TDD**：先写测试覆盖——x 落在两点正中、x 在首点之前、x 在末点之后、
      单点序列、含 NaN、非单调序列。
- [ ] **C-2** 新增 `snap_cursor_x(channel_data, x, *, to_pixels, hidden)`
      实现 C.3.1 的锚点通道选择，**无条件**返回 `(t_snap, anchor_channel)`。
      不设距离阈值（C.3.2 决策）。
- [ ] **C-3** 改 `cursor.py:374-402` `_handle_cursor_mouse_move`：
      单游标线定位到 `t_snap`。
- [ ] **C-4** 改 `cursor.py:404-431` `_handle_cursor_mouse_press`：
      A/B 存 `t_snap`，`InfiniteLine` 也定位到 `t_snap`。
- [ ] **C-5** 改 `cursor.py:547-558` `_emit_single_cursor_html`：
      删掉 `searchsorted` 那行，改用 `nearest_sample_index`；
      **第 549 行的 `t=` 必须显示 `t_snap`（= `tf[idx]`），不是原始 x**。
- [ ] **C-6** 改 `cursor.py:605-607` 双游标 Δ：
      用 `sf[idx_b] - sf[idx_a]`（真实采样值之差）替换
      `_interp_cursor_value`。**逐个核对 `_interp_cursor_value` 的其余调用点**
      （`ui/canvases.py:36,70` 有再导出），决定是保留该函数供别处用、
      还是整体退休。
- [ ] **C-7** 双游标窗口统计（`cursor.py:586`）改用采样对齐边界，
      让 Min/Max/Avg 不再随 1 px 抖动跳变。
- [ ] **C-8** `ΔT`/`1/ΔT`（`cursor.py:569-571`）随之变成采样间隔的整数倍——
      这是**期望行为**，但要在测试里钉死，避免被当成回归。
- [ ] **C-9** UI 开关（C.3.3）：默认开 + QSettings 持久化 + Alt 临时关闭。
      **默认值必须是开**，且升级安装后保持开。
      **落位【已定，2026-07-31 用户指定】**：图表右键面板**第一行（"鼠标"行）
      的 `▾` 下拉里新增一项**——即 `_PgCustomActionButton` 的
      `_CUSTOM_ACTION_LABELS`（`ui/pg_canvas/context_menu.py:117-133`）
      增加 `"cursor_snap": "游标吸附"`，配一个图标
      （建议 `mdi.magnet` 或 `mdi.vector-point`）。
      **设计后果（需一并处理，不是反对意见）**：该下拉当前 4 项
      （复制为图片 / 上一步视图 / 下一步视图 / 导出图片）全是**执行型**动作，
      按钮 docstring 明写 *"runs one bound execute-type action"*
      （`context_menu.py:723`）。游标吸附是**布尔开关**，是这个列表里的第一个
      toggle。因此需要：
      1. `_resolve_custom_action`（152 行）为 `cursor_snap` 返回一个翻转状态的
         callable；
      2. `_refresh_main`（779 行）反映**当前开/关状态**（checked 样式），
         不能像执行型动作那样点完就没有反馈；
      3. `_CUSTOM_ACTION_CONTROLLER_METHODS`（129 行）不适用，
         需要单独的状态读写通道（QSettings + 广播到所有画布）。
- [ ] **C-10** 新建 `tests/ui/test_cursor_snap.py`（当前 `tests/ui/` 下
      **没有任何 cursor 专项测试文件**）。至少覆盖：
      吸附到最近点而非向上取整、报出的 `t` 等于 `tf[idx]`、
      多通道混合采样率的锚点选择、**大数据空洞中间仍然吸附且读数无"无采样点"字样**、
      隐藏通道不参与吸附、Δ 值等于两个真实采样值之差、
      吸附走全量序列而非抽稀序列、开关关闭时回到自由定位。
- [ ] **C-11** 性能回归：`tests/perf/test_timedomain_pan_perf.py` 旁边加一条
      "千万点序列上 100 次吸附"的用例，钉住 O(log n)。
- [ ] **C-12** 更新 `ui/quickref.py` / `ui/hints.py` 的游标说明文案
      （两个文件都提到"游标"），并跑 `update-hints` skill。

### C.5 同类问题

- [ ] **C-13** 检查热图画布（`heatmap_canvas.py`）的游标/切片读数是否有同样的
      连续坐标问题——热图是 2D 网格，"最近真实数据点"语义不同（要吸到 bin
      中心），需单独确认再决定是否纳入。
- [ ] **C-14** `line_canvas.py:1749-1754` `_on_hover` 已经吸附了读数，
      但**没有游标线**。确认这是产品有意为之，还是同一缺陷的另一面。

---

## 执行顺序与依赖

```
A-1 → A-2 → A-3 ─┐
A-4 → A-5 ───────┼→ A-8（实机出包验收）
A-6 → A-7 ───────┘
A-9 / A-10（审计，可并行）

B-1 → B-2 → B-5 → B-6（实机截图）
B-3 / B-4（可并行，B-3 需先看后改）

C-1 → C-2 → {C-3, C-4, C-5, C-6, C-7} → C-8 → C-10 → C-11
C-9 / C-12（UI 与文档，依赖 C-3..C-7 落地）
C-13 / C-14（调查，可并行）
```

**A 组必须先出货**——它是当前唯一的功能性阻断。B、C 可并行推进。

## 验收标准

| Issue | 通过条件 |
|---|---|
| A | 重新构建的 Windows 冻结包，跑用户截图里同一批任务（3 文件 × `EpsDrvrSteerTq`，CSV + PDF），**6 个输出全部落盘**；`tests/test_windows_build_script.py` 全绿且断言方向已反转；A-5 的新检查能在人为重新加回 `--exclude-module matplotlib` 时**失败** |
| B | Windows 实机截图：批处理信号下拉展开后圆角外**无黑边**；`tests/ui/test_combo_popup_shell.py` 新断言绿 |
| C | `tests/ui/test_cursor_snap.py` 全绿；实机拖动游标可见**吸附到曲线上的点**；读数 `t` 与幅值来自同一采样点；双游标 Δ 等于两个真实采样值之差；千万点序列上无卡顿 |

## 需要沉淀的 lessons

- [ ] **L-1** `docs/lessons-learned/` — 冻结依赖契约的**覆盖范围**必须等于
      "所有会被打包的源码"，不能只是 `mf4_analyzer/io/`；
      并且**排除清单必须与源码 import 做反向交叉校验**。
      与 `codex-frozen-import-dependency-contract.md` 交叉引用（同一 failure mode 第二次发生）。
- [ ] **L-2** 更新 `codex-rounded-qt-popups-need-translucent-shell.md`：
      把 `SignalPickerPopup` 记为该 lesson 写下**之后**仍然复发的实例，
      并记录已提炼公共 `apply_rounded_popup_shell()`。
- [ ] **L-3** 新 lesson — 游标/读数类 UI **只能显示真实测量值**；
      需要插值时必须显式标注。记录 `searchsorted` 默认 `side='left'`
      不等于"最近点"这个具体陷阱。

## 已决事项（2026-07-31 用户确认，不再重议）

1. **游标吸附默认开启并持久化，但保留可关闭的设置入口**（C.3.3）。
2. **不设吸附半径，无论多远都吸附；读数不得提示"无采样点"**（C.3.2）。
3. **Track B（Qt 移植）的目标是"效果与 timedomain plot 一致"** ——
   含深色→浅色改版，见 A.7.2。

## 未决问题（需用户确认）

1. **Track B 还做不做？**（A.8.4）Track A+ 落地后，Qt 移植只剩
   "回收 33 MB" 和 "像素级一致" 两个理由。如果这两个都不关键 →
   **建议直接不做**，B0-1 spike 也可以省掉。
2. **异步通道的取值语义**（C.3.4）：先统一用"最近采样点"；
   是否要为事件型 CAN 通道单独做 sample-and-hold，以及 `fd.channel_metadata`
   是否携带"连续/事件"的区分信息，需另行确认。
3. **A+3 的颜色来源**：批处理导出要不要真的读当前 View 的
   `ViewState.colors`（用户手动改过的颜色）？还是只按 `_PALETTE` 顺序分配就够？
   前者更一致，但需要把颜色分配传进 `BatchRenderContext`。
