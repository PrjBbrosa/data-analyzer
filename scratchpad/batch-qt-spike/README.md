# Batch 0 Qt Render Spike

该目录是 `2026-08-01-batch-qt-render-migration` 的隔离可行性证据，不是产品实现。
原型只读调用现有 `TimeDomainCanvasPG`、`PgLineCanvas`、`PgHeatmapCanvas` 作为
reference；未修改产品源码。

## 运行命令

完整 offscreen 矩阵：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  '/Users/donghang/Downloads/data analyzer/.venv/bin/python' \
  scratchpad/batch-qt-spike/gate0.py --mode full
```

HiDPI（DPR=2）像素几何：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 \
  MPLCONFIGDIR=/tmp PYTHONPATH=. \
  '/Users/donghang/Downloads/data analyzer/.venv/bin/python' \
  scratchpad/batch-qt-spike/gate0.py --mode hidpi
```

macOS native Qt platform：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=cocoa MPLCONFIGDIR=/tmp PYTHONPATH=. \
  '/Users/donghang/Downloads/data analyzer/.venv/bin/python' \
  scratchpad/batch-qt-spike/gate0.py --mode cocoa
```

## Gate 结果

最终 Gate 0：**PASS**。

- 1920×1080 三主题像素尺寸、144 DPI pHYs 与 PNG text metadata 回读通过。
- DPR=2 offscreen 和 DPR=2 cocoa 均保持精确 1920×1080。
- time 双 Y、8-panel subplot、FFT、非对称 2×3 heatmap 使用同 payload 生成
  batch/reference/PlotItem scene crop/contact sheet。
- time 双 Y 不再手写显示范围：batch 使用 pyqtgraph auto-range padding 后复用现有
  `_frame_to_nice` 10 分格语义；batch/reference 的 X/Y 数值在绝对容差 `1e-9` 下
  相等（X `[0,10]`，Acceleration Y `[-1,1]`，Speed Y `[1320,1720]`）。
- heatmap 与真实 single-file 默认保持同一 `bilinear` smooth transform、row-major
  matrix、extent、turbo LUT 和 `[0, 1]` levels。
- 所有 prototype PlotItem 均关闭 auto button、menu、mouse、frame、scrollbar、focus；
  输出没有主界面导航、toolbar 或 status chrome。
- `PingFang SC` 覆盖契约文本 `单帧振动加速度` 全字形；标题/空标题差异 3313 pixels。
- worker→GUI BlockingQueuedConnection、异常回传、模态对话框可达、退出 fail-fast
  全部通过。
- 1080p（每类 20 次，含 build/layout、QImage render、cleanup、lossless PNG encode）
  p95：双 Y 435.08 ms、8-panel 240.60 ms、heatmap 105.29 ms，均低于 500 ms。
- 20 个连续 worker 渲染请求下，50 ms heartbeat 最大间隙 110.77 ms，超过
  100 ms 次数 7，低于 200 ms 预算。
- 4K 单次：双 Y 1267.95 ms、8-panel 646.15 ms、heatmap 345.34 ms；进程 peak RSS
  由 1,566,588,928 增至 1,835,581,440 bytes，峰值增量 268,992,512 bytes。

最终 offscreen evidence 生成于 `2026-08-01T14:54:33.497934+00:00`，对应工作树
commit `612bdd595bdfcecd41a7bedab1259f5c7f1d9383`。

机器证据见 `evidence.json`；DPR/cocoa 证据见 `hidpi-evidence.json`、
`cocoa-evidence.json`；目视签字见 `visual-review.md`。

## 证据边界

本 Spike 放行 Batch 2 的 Qt renderer 实施，不代表最终发布验收。macOS cocoa 证明的
是 native platform + `WA_DontShowOnScreen` 构建/渲染路径；正式批处理的前台交互、
Windows native/offscreen 冻结包以及最终协调 agent 的独立重跑仍按 Spec 后续 Gate
执行。
