# 时域图 GPU 加速开关 — 设计

- 日期：2026-06-06
- 范围：时域画布 `TimeDomainCanvasPG` 的渲染后端开关（CPU 软件光栅 ↔ OpenGL viewport），右侧 Inspector 放置开关，状态持久化，GPU 下导出修正
- 状态：设计草案，待用户 review 后再进入实现
- 前置背景：本次卡顿根因调查（见 §1、§2）；记忆 `project-timedomain-perf-raster-bound`

## 1. 背景

用户反馈：打开 testdoc 里 ~1.9MB 的文件（如 `tiaofri.MF4`，26 通道、单通道 ~35k 点、99Hz），开四五个通道后卡顿；并自行定位到「在 5K Studio Display 全屏后才卡，窗口占 1/4 屏时不卡」。

这把问题从「数据量大」彻底排除，指向「随屏幕分辨率/窗口尺寸增长的每帧渲染成本」。

## 2. 当前证据与根因

### 2.1 数据量不是瓶颈，包络抽稀已最优

- `pg_canvases.py:3787` 热路径 `_refresh_visible_data` 调 `positions_envelope`，把每条曲线压到「≈2× 绘图区像素宽」的点数。实测该步 5 通道 **0.2ms/帧**，可忽略。
- `pg_canvases.py:3782` 已有 `_last_range_key` 区间键门控，相同 xlim 不重算。

### 2.2 渲染走 Qt 软件光栅（CPU），无 GPU

- `pg_canvases.py:1045` `self._glw = pg.GraphicsLayoutWidget(self)`，全仓库未设 `useOpenGL`/`enableExperimental`，即默认 CPU 光栅。
- 每帧成本 ≈ 绘制线段数（∝ 像素宽 × 通道数）+ 离屏缓冲填充面积（∝ 宽 × 高 × dpr²）。

### 2.3 高 DPI 放大了缓冲填充成本

- `app.py:47-61` 开启 High-DPI：`QT_ENABLE_HIGHDPI_SCALING=1`、`AA_EnableHighDpiScaling`、`HighDpiScaleFactorRoundingPolicy=PassThrough`。
- 5K Studio Display 全屏时 `devicePixelRatio=2`，离屏缓冲为物理 5120×2880，比 1/4 窗口约 3.5× 像素面积。
- 跨平台同理：Windows 高分屏 + 系统缩放（PassThrough 不取整）同样产生 dpr² 放大，非 macOS 专属。

### 2.4 真机实测（grab，全屏 2560×1400 逻辑，dpr=2，overlay）

| 通道数 | 现状每帧 |
|---|---|
| 5 | 36.9ms（~27fps，已卡） |
| 10 | 99.1ms |
| 20 | 346.4ms（~3fps，冻结） |

成本随通道数**超线性**：overlay 下每曲线各占一个铺满绘图区的 aux ViewBox（`pg_canvases.py:3491` `_sync_overlay_aux_viewboxes`），N 条 ~57MB 全尺寸图层 CPU 合成。

### 2.5 「封顶像素宽」方案（Plan A）实测无效，已否决

把 `_current_pixel_width`（`pg_canvases.py:3745`）封顶到 1200：5 通道仅省 13%（37→32ms），10 通道 6%，20 通道 -3%。它碰不到 dpr² 填充与通道数这两条主轴。

### 2.6 只有时域图可上 GPU

- `main_window.py:203-206`：`canvas_time` 是 pyqtgraph（`TimeDomainCanvasPG`），`canvas_fft`/`canvas_order`/`canvas_fft_time` 均为 matplotlib（`canvases.py:10` `FigureCanvasQTAgg`）。OpenGL 对 matplotlib 不适用。
- 故 GPU 开关**只作用于 `canvas_time`**，由架构决定。

### 2.7 GL 路线选型（实测）

- **PyOpenGL 未安装**（实测 `import OpenGL` 失败）→ pyqtgraph 逐曲线 raw GL 路（`PlotCurveItem.paintGL`，需 PyOpenGL，`enableExperimental`）不可用。
- 该 raw GL 路才是「线宽被钳 1px、虚线变实线」的来源。
- **GL viewport 路**（`GraphicsView.useOpenGL(True)`）用 Qt 的 GPU 画引擎，**仍走 QPainter 语义**，线宽/虚线/抗锯齿与 CPU 一致。
- 实测：开 `useOpenGL` 后 viewport 变 `GraphicsViewGLWidget`，grab 中位 17ms（含 GPU→CPU 读回，偏高）vs CPU 37ms —— GL viewport 路既提速、又不碰 raw GL 的毛病。

## 3. 目标

1. 给时域图一个**用户可控、默认关、状态持久化**的「GPU 加速」开关。
2. 开启后渲染后端切到 **OpenGL viewport 路（A）**，把每帧光栅化甩给 GPU，解决全屏/高分屏/多通道卡顿。
3. 不引入新依赖（不装 PyOpenGL）、不破坏导出、视觉与 CPU 对齐。
4. **不做**卡顿自动检测、**不做**发现提示（按用户决定，最简方案）。

## 4. 非目标

- 不改 matplotlib 画布（FFT/阶次/FFT vs Time）。
- 不做 raw GL 逐曲线加速、不做卡顿实时监控、不做线宽以外的视觉重构。
- 不改包络抽稀/区间键门控等现有热路径逻辑。

## 5. 设计

### 5.1 渲染后端开关（`pg_canvases.TimeDomainCanvasPG`）

新增 `set_gpu_render(on: bool)`：

- 分离两层状态：
  - `self._gpu_render_requested`：用户/持久化期望值。
  - `self._gpu_render_on`：当前 viewport 是否已实际切到 GL（导出路径只看这个 applied 状态）。
- 调 `self._glw.useOpenGL(bool(on))` 切换 viewport（CPU raster ↔ GL），成功后才更新 `self._gpu_render_on`。
- `useOpenGL()` 会替换 `GraphicsLayoutWidget.viewport()`；切换后必须重装 viewport 事件过滤器：
  - 抽 `_install_viewport_event_filter()`，记录 `self._gpu_viewport_filter_target`；
  - 对旧 viewport 尝试 `removeEventFilter(self)`；
  - 对当前 viewport 执行 `setMouseTracking(True)` + `installEventFilter(self)`。
  这条保护双击图表选项、overlay 选择/Y 拖拽、游标点击/移动/释放等现有交互入口。
- 切换后触发一次重绘：优先 `_flush_pending_refresh()`，再 `draw_idle()` / `_glw.update()`，确保新 viewport 有内容。
- **幂等 + 异常安全**：重复设同值是 no-op；任何异常被吞掉并记录，绝不崩。若实时切换失败，保留 `self._gpu_render_requested=True`、`self._gpu_render_on=False`；在 `plot_channels()` rebuild 末尾重试 `_apply_gpu_viewport()`，这才是真正的「下次绘图重试」。
- 只走 A 路：**不**设 `enableExperimental`、**不**依赖 PyOpenGL。

### 5.2 MSAA 抗锯齿（`app.py`）

启动时、创建 QApplication 的 GL 上下文前，设默认 surface format：

```python
fmt = QSurfaceFormat(); fmt.setSamples(4); QSurfaceFormat.setDefaultFormat(fmt)
```

放在 `app.py` 现有 High-DPI 配置块（47-61 行附近），**在 `QApplication(sys.argv)`（78 行）之前**。让 GL viewport 拿到多重采样 AA，线条质量与 CPU 对齐或更好。CPU 模式不受影响。

### 5.3 开关 UI 与持久化

- **位置**：右侧 `Inspector`（`inspector.py:40`）。在 `body_lay` 中 `contextual_stack`（`inspector.py:109`）之后、`addStretch(1)`（`inspector.py:110`）之前插入开关 → 落在右下角空白区，且因挂在 Inspector 自身布局（非按模式切换的 stack），**所有模式常驻可见**。
- **控件**：`QCheckBox`，文案「GPU 加速（时域图）」，tooltip：「大图/多通道/高分屏卡顿时开启；导出仍正常，渲染与 CPU 一致」。
- **持久化**：`QSettings("MF4Analyzer", "DataAnalyzer")` 键 `render/use_opengl`（bool，默认 `False`）。不要用裸 `QSettings()`，因为当前 `app.py` 没有全局设置 org/app，裸 settings 会落到 Python 默认命名空间。
- **数据流**：勾选 → `MainWindow.set_gpu_render(on)`：写显式 namespace 的 `QSettings` → 调 `canvas_time.set_gpu_render(on)`。启动时 `MainWindow` 读同一个 namespace，在首次绘图前同步勾选态并应用到画布。

### 5.4 导出修正（必修）

实测：GPU 开启后 `grab_pixmap`（`pg_canvases.py:4937`，复用于复制/保存图）抓出**全白空图**（`QWidget.grab()` 抓不到 GL 帧缓冲；grabFramebuffer 在无头环境也实测返回空白，不可靠）。

做法：`grab_pixmap`（及 `_grab_widget_scaled`，`pg_canvases.py:5002`）开头若 `self._gpu_render_on`，通过同一个 `_apply_gpu_viewport()` **临时切回 CPU 光栅** → 走现有 `grab()` 路径 → **再切回 GPU**。导出是一次性操作，这点切换开销无所谓，且复用已验证可用的 CPU 抓图路径，比赌 grabFramebuffer 稳。需保证 try/finally 恢复 `self._gpu_render_requested` 与 applied viewport，并在每次 OFF/ON 后重装 viewport event filter。

### 5.5 默认与行为边界

- 默认 **关**（保守，无感用户不受任何 GL 副作用波及）。
- 开关全局生效、跨会话持久。
- AA 门控那套（`pg_canvases.py:4783` `_idle_quality_allowed` 等）在 GL viewport 下作用于 `opts['antialias']`，对 GL 渲染基本无影响，**保持原样休眠，不删**（零风险）。

## 6. 风险与处置

| 风险 | 处置 |
|---|---|
| `useOpenGL` 替换 viewport 后丢事件过滤器 | `_install_viewport_event_filter()` 在初始化、GPU ON/OFF、导出 CPU 回切/恢复后都执行；自动测双击/游标/overlay 至少覆盖一个事件入口，真机冒烟覆盖全部 |
| 实时 `useOpenGL` 切换在个别驱动残留/失效 | 记录 requested/applied 分离状态；失败时不把 `_gpu_render_on` 置真，在下一次 `plot_channels()` rebuild 末尾重试；OFF→ON→OFF 往返在实现期真机验不崩、不漏 |
| GL 视觉与 CPU 不一致（线宽强调/虚线光标） | 选 A 路 + MSAA，逻辑上对齐；**像素级一致必须真机 app 复核**（无头抓不到 GL，见 §7） |
| macOS OpenGL 已弃用 | 当前可用，仅 deprecation 警告；保留 CPU 默认与回退 |
| Windows GL 驱动差异 | 实现期在 Windows 高分屏复验 |
| QSurfaceFormat 设置时机晚于 GL 上下文创建 | 必须在 `QApplication` 构造前 `setDefaultFormat`；加注释锁定顺序 |
| GPU 偏好写到错误 settings namespace | helper 统一用 `QSettings("MF4Analyzer", "DataAnalyzer")`；测试断言 helper 的 org/app 而不是裸 `QSettings()` |

## 7. 测试

### 7.1 单元/集成（offscreen 可跑）
- `set_gpu_render(True/False)` 幂等、异常安全、不崩。
- `useOpenGL` 失败时 `requested=True`、`_gpu_render_on=False`；下一次 `_apply_gpu_viewport()` / `plot_channels()` 能重试。
- GPU ON/OFF 后 `self._gpu_viewport_filter_target is self._glw.viewport()`；至少一个 viewport 事件（如 double-click）仍进入 `eventFilter`。
- `QSettings("MF4Analyzer", "DataAnalyzer")` `render/use_opengl` 往返；启动时勾选态与持久值一致。
- GPU 开启时 `grab_pixmap()` 经 §5.4 CPU 回切后返回**非空白**图（不是 1×1 fallback，采样非白/非透明像素 > 阈值）。
- 切换后 `self._gpu_render_requested` 与 `self._gpu_render_on` 标志语义正确。

### 7.2 真机冒烟（必做，遵循「UI 必须验真实渲染」）
- 5K 全屏，时域图 5/10/20 通道，开/关 GPU 各截图：
  - 线宽强调（选中加粗/弱化变细）、虚线光标、整体渲染与 CPU 一致；
  - 导出/复制图非空白；
  - GPU ON/OFF 后双击图表选项、游标点击/移动、overlay 选择/Y 拖拽仍响应（证明新 viewport event filter 已恢复）；
  - 主观帧顺滑度明显改善（对照 §2.4 的 37/99/346ms）。

## 8. 涉及文件

- `mf4_analyzer/ui/pg_canvases.py`：`set_gpu_render`、`_apply_gpu_viewport`、`_install_viewport_event_filter`、`_gpu_render_requested`/`_gpu_render_on`、`grab_pixmap`/`_grab_widget_scaled` 导出回切。
- `mf4_analyzer/app.py`：MSAA 默认 surface format。
- `mf4_analyzer/ui/inspector.py`：开关控件入 `body_lay`。
- `mf4_analyzer/ui/main_window.py`：`set_gpu_render` 入口、启动读 `QSettings` 同步。
- 测试：`tests/ui/` 新增开关/持久化/导出单测。
