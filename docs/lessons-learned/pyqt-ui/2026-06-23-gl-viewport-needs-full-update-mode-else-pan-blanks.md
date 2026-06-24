---
role: pyqt-ui
tags: [pyqtgraph, opengl, useopengl, viewport, setviewport, fullviewportupdate, qopenglwidget, devicecoordinatecache, cache-mode, pan, gpu, repaint, blank-on-drag, blank-static, blank-on-toggle, replot]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

## Context
「GPU 加速」开关走 `GraphicsView.useOpenGL(True)`（pyqtgraph 0.14 把 viewport 换成
`GraphicsViewGLWidget` —— 一个裸 `QOpenGLWidget` 子类）。曲线在 GL 下消失有**三个独立
病因**：(1) 拖动时整片消失、松手才回；(2) 静止就只有曲线不显示（轴/图例/标签都在）；
(3) **一开关 GPU 当场全消失，pan/缩放救不回、只有重新「绘图」才回来**。

## Lesson
**病因 1（拖动消失，update mode）**：`QOpenGLWidget` 默认 `NoPartialUpdate`，GL 后缓冲
每帧不保留；而 pyqtgraph 的 `GraphicsView` 构造时设 `MinimalViewportUpdate`（只重绘脏
矩形）。两者叠加：拖动每个 move tick 只把脏带画进一块「不保留上一帧」的 GL buffer，脏带
以外曲线全被清空 → 拖动整片消失；任何全量重绘（松手 setData / resize / expose）才带回。
`useOpenGL()` 只换 viewport、不动 update mode。

**病因 2（静止只有曲线不显示，item 缓存）**：空闲抗锯齿那条 Fix D 给曲线设
`QGraphicsItem.DeviceCoordinateCache`（subplot 提速 15-30×）。该缓存把每条曲线渲染到
**离屏 raster 像素图**，而这种像素图在 `QOpenGLWidget` viewport 上**不合成**（多数驱动
如此）→ 缓存过的曲线整条消失，而没缓存的轴/图例照常画。「只有曲线不见、轴还在」就是它的
指纹。注意这两个病因正交：update mode 救不了缓存问题，反之亦然，要分别修。

**病因 3（一开关就全消失，stale items 不在新 viewport 重渲染）**：`useOpenGL()` 内部是
`setViewport(new GraphicsViewGLWidget())` —— **整块换掉 viewport 控件**。换上来前就已存在于
scene 的曲线 item，在新 GL viewport 上**不会重新渲染**；pan/envelope refresh 复用的是同一批
旧 item（用户实证：开 GPU 当场消失、**pan/缩放救不回**）；唯独 `plot_channels` **重建全新
item** 才画得出（用户实证：重新「绘图」才回来）。这与病因 1/2 又正交：FullViewportUpdate
+ NoCache 都对，旧 item 仍画不出，因为问题是「旧 item 没在新 GL 上下文里重建」。

## How to apply
- **病因 1**：切到 GL 时 `setViewportUpdateMode(FullViewportUpdate)`（GL 全屏重绘正是
  GPU 用武之处，廉价）；切回 CPU 还原 `MinimalViewportUpdate`（保住局部重绘的廉价）。
  `viewportUpdateMode` 是 view 级属性，跨 CPU↔GL viewport 替换（含导出回切）都保留，只在
  toggle 汇聚点（`_apply_gpu_viewport`）设一次即可。
- **病因 2**：GL 激活时**别用** `DeviceCoordinateCache`——空闲 AA 门控加 `not _gpu_render_on`
  条件跳过它，并在切到 GL 时把已设的缓存清回 `NoCache`（门控只防未来、不清已有）。GL 重绘
  本就廉价，缓存对它无收益。CPU 路保留缓存。
- **病因 3**：开关 GPU 后**重绘一次**（`_on_gpu_render_toggled` 在 `set_gpu_render` 之后，
  若已载文件且当前是时域则 `plot_time()`），把曲线在新 viewport 上**重建**——别只靠
  `glw.update()`/envelope refresh（复用旧 item，救不回）。gating 到「有文件 + 时域」即可：
  FFT 模式下切回时域本就会重绘。代价=一次重绘，等价于把用户手动点「绘图」自动化。
- 无头抓不到 GL 帧缓冲（`QWidget.grab()` 对 GL 返回纯白），像素级「曲线显示/拖动不消失」
  必须真机复核；且 GL 在部分驱动 / 远程桌面 / ANGLE(DX11) 下可能根本画不出曲线，软件兜底
  之外要保留 CPU 默认与「关掉 GPU」退路。

## 2026-06-24 收尾 — macOS 上 viewport-GL 根本画不出曲线，决定平台级关闭
病因 1/2/3 全修完后，用户真机仍报「开 GPU 后曲线全消失、**重绘也救不回**、只有关 GPU 才回」。
病因 3 的自动重绘（`_on_gpu_render_toggled` 后 `plot_time()`）反而把「手动重绘能救」退化成「都救
不回」。结合连续 6 类显示 bug（拖动/静止/开关/导出全白/线宽拍平/全程消失）+ Explore 全链路确认
**全仓只有 viewport 级 `useOpenGL`、无 config/逐曲线 GL 退路**，判定：**QOpenGLWidget 当
QGraphicsView 的 viewport 在 macOS 上不可靠地合成曲线 QGraphicsItem**，再修协议步骤也救不回，
属平台级失败。决策（用户拍板「关掉/移除」）：**macOS 上平台级关闭 GPU 加速**——
`canvas._GPU_RENDER_PLATFORM_OK = sys.platform != "darwin"`，`set_gpu_render` 单一收口把
`_gpu_render_requested` clamp 成 `on and _GPU_RENDER_PLATFORM_OK`（持久化设置/误触都进不了 GL）；
inspector `_GPU_RENDER_UI_SUPPORTED` 在 macOS 隐藏开关行。其它平台（Windows 真机 GL 有效）保留。
时域性能继续由 CPU 抽稀 + 密集封顶 + 窄Y竖线墙守卫承担。**教训：viewport-GL 是 macOS 上的
正确性负债，band-aid 修不完；GL 加速若无逐曲线/config 退路，宁可平台级关，别一直补 viewport 切换。**

## 2026-06-24 收尾#2 — Windows **打包版**同病，冻结包也平台级关闭
之前以为「Windows 真机 GL 有效」（上一段第 61 行）。用户真机实测推翻：**源码运行（dev）开 GPU 正常，
PyInstaller 打包后开 GPU 曲线整体消失（轴/图例还在）**，与 macOS 同指纹。诊断按「先量化、别再猜」逐一
排除外因：
- **GL 后端不是病因**：在 `app.py` 加 `_write_gl_diagnostics`（`QOpenGLContext.openGLModuleType()` /
  探针 ctx `isOpenGLES()`，写 `%TEMP%/tracelab_gl_diag.txt`）。打包版实测 `AA_UseDesktopOpenGL: True`、
  `openGLModuleType: LibGL(desktop)`、`isOpenGLES: False`、version 4.6——与 dev **完全相同**的 desktop GL。
  （配套：冻结包里 `app._configure_high_dpi` 强制 `AA_UseDesktopOpenGL`，确保不回退 ANGLE——已生效，仍失效。）
- **UPX 不是病因**：构建脚本每次用 CLI 参数重生成 spec（改 `.spec` 无效，须在 `tools/build_windows_folder.ps1`
  加 `--noupx`）。关掉 UPX 重打后**仍然**曲线消失。
- 结论：后端正确 + 非 UPX + 源码正常/打包失效 ⇒ **QOpenGLWidget viewport 在冻结环境就是不合成曲线
  QGraphicsItem**，和 macOS 同病。决策：**冻结包一并平台级关 GPU**——
  `canvas._GPU_RENDER_PLATFORM_OK = sys.platform != "darwin" and not getattr(sys, "frozen", False)`，
  `inspector._GPU_RENDER_UI_SUPPORTED` 同样加 `not frozen` 隐藏开关；诊断探针改 `TRACELAB_GL_DIAG=1` 按需。
  源码运行（dev）非 macOS 仍保留 GL。**教训追加：viewport-GL 在「打包」这一维度上同样是负债——
  `getattr(sys,'frozen')` 与 `platform=='darwin'` 是同级的「GL 不可信」判据；诊断要量化后端（openGLModuleType/
  isOpenGLES）而不是凭「应该是 desktop」假设，且 spec 是构建脚本生成的、要改脚本参数不是改 .spec。**
