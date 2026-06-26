# GPU 加速「曲线消失」问题报告与处理

日期：2026-06-24
范围：时域图「GPU 加速」开关；TraceLab v7.2；macOS。

## 1. 现象

在 macOS 上勾选「GPU 加速」后：

- canvas 上的曲线**直接全部消失**（坐标轴、图例、网格仍在）。
- 重新点「绘图」**也画不出来**（普通曲线、滤波曲线都没有）。
- **只有关闭 GPU 加速**，曲线才回来。

演进过程中症状逐步加重：最早是「拖动时整片消失」，后来「静止只有曲线不显示」，再后来「一开关就消失、重绘能救回」，最终变成「重绘也救不回，只能关 GPU」。

## 2. 排查

「GPU 加速」的实现只有**一条路**：viewport 级 `GraphicsView.useOpenGL(True)`——pyqtgraph 把整块 viewport 换成 `QOpenGLWidget`。经全链路核查（`canvas.py` / `renderer.py` / `quality.py` / `inspector.py` / `window.py`）确认：

- 全仓**没有** `pg.setConfigOption('useOpenGL')`、**没有**逐曲线 `useOpenGL=True`。pyqtgraph 的 GL 快路也必须依赖 GL viewport，**没有「不换 viewport 还能 GL 加速曲线」的干净退路**。
- 共有 **3 个 viewport 切换点**：`_apply_gpu_viewport`（用户开关，协议完整）、`grab_pixmap` 导出时切 CPU→切回 GL（renderer.py，协议缺失，但只在导出时触发，非本症状）。
- 已针对性修过 3 个正交病因：拖动消失（`FullViewportUpdate`）、静止消失（曲线 `DeviceCoordinateCache` 在 GL 上不合成 → 切 GL 时清 `NoCache`）、开关消失（`useOpenGL` 内部 `setViewport` 换 viewport，旧曲线 item 不在新 GL 上重渲染 → 开关后 `plot_time()` 重建）。

## 3. 真因

3 个病因全修后真机仍「开 GPU 全消失、**连重绘都救不回**」，且开关后自动重绘反而把「手动重绘能救」退化成「都救不回」。

判定：**`QOpenGLWidget` 作为 `QGraphicsView` 的 viewport，在 macOS 上不可靠地合成曲线 `QGraphicsItem`**——曲线整体画不出（轴/图例是另一套绘制所以还在），无论是切换前的旧 item 还是重建的新 item。这是**平台级失败**，不是某个逻辑漏步，再补 viewport 切换协议也救不回。

佐证：同源已累计 **6 类显示 bug**——拖动消失 / 静止消失 / 开关消失 / 导出全白（`grab()` 读不到 GL framebuffer）/ 线宽被拍平 / 现在全程消失。viewport-GL 是 macOS 上的**正确性负债**。

## 4. 决策

在 macOS 上拿「正确性」换「速度」，而这速度在该平台根本没兑现。时域真正的性能瓶颈是 CPU 光栅，已由 **CPU 抽稀 + 密集通道封顶 + 窄 Y 竖线墙守卫** 承担（均已合并、正确）。

**决策：macOS 上平台级关闭 GPU 加速；其它平台（Windows 真机 GL 有效）保留。**

## 5. 实现

| 层 | 改动 | 作用 |
|---|---|---|
| `canvas.py` | `_GPU_RENDER_PLATFORM_OK = sys.platform != "darwin"`；`set_gpu_render` 把请求 clamp 成 `on and _GPU_RENDER_PLATFORM_OK` | **单一收口**：持久化设置 / 误触 / 启动恢复都进不了 GL |
| `inspector.py` | `_GPU_RENDER_UI_SUPPORTED`；GPU 开关行 `setVisible(mode=='time' and _GPU_RENDER_UI_SUPPORTED)` | macOS 隐藏开关行 |
| 其它平台 | 机制完整保留，未删 | Windows 仍可用 GL |

## 6. 验证

- 新增/更新测试：平台兜底（macOS 强制 CPU、`useOpenGL` 永不调用）、inspector macOS 隐藏开关、原 GL 机制测试 monkeypatch 强制「支持」以继续覆盖非 macOS 路径。
- `test_inspector.py` + `test_gpu_render_toggle.py`：199 passed。
- 全量回归：见提交（零回归）。

⚠️ 真实 GL 帧缓冲无头环境抓不到（`grab()` 对 GL 返回纯白），像素级渲染由真机确认。本决策不依赖 GL 渲染——它直接**不进 GL**，所以 macOS 上曲线必然走 CPU 正常显示。

## 7. 遗留 / 后续

- **需重启应用**：源码改动，重启后 macOS 自动走 CPU、开关隐藏，曲线正常。当前持久化的 `render/use_opengl=True` 会被 canvas 兜底 clamp 成 CPU，无需手动清。
- **非 macOS 的 `grab_pixmap` 协议缺口**（renderer.py 切回 GL 后未重设 update mode / 未重绘）是一个独立的、仅 Windows + GPU 开 + 导出时才触发的潜在 bug，本次未动（超出 macOS 关闭范围）；若 Windows 上启用 GPU 后导出异常，再处理。
- 若未来要让 macOS 真正用上 GPU 曲线加速，需换架构（如独立 `GLViewWidget` / 逐曲线 GL path），工作量大，且仍需真机验证。
