# Order Canvas 渲染 / 显示 / 交互 改造 Design Spec

**Date:** 2026-04-26
**Author:** main Claude
**Status:** ready for codex review
**Related report:** `docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md`
**Related prior specs:** `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`、`docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`
**Related prior plans:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`
**Related prior reports:** `docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md`

## 1. Goal

把 order 模式（时间-阶次谱、转速-阶次谱、阶次跟踪）这一摊代码的 **渲染性能 / 显示效果 / 交互流畅性** 推到与同仓库内 spectrogram canvas、time-domain canvas 同档的水平。同时修复 codex 2026-04-26 改动里数学和工程层面遗留的真问题。

非目标：复刻 HEAD ArtemiS 的专业功能广度（3D waterfall、多通道、live、acoustic models 等一律不做）。

## 2. Scope

### 2.1 Included

**渲染层（matplotlib）：**

- order 2D 谱（time-order / rpm-order）从 `pcolormesh(shading='gouraud')` 切到 `imshow(interpolation='bilinear', aspect='auto', origin='lower', extent=...)`。
- 复用 axes / image / colorbar：第二次按相同维度计算时走 `im.set_data` + `set_clim` + `cbar.update_normal`，不再 `clear()` + `add_subplot`。
- order_track 下半幅 RPM 曲线接入 viewport-aware envelope 下采样（不引入新 canvas，逻辑直接搬到调用 plot 之前）。
- `PlotCanvas` 升级：xlim listener + QTimer debounce、bucket-quantized envelope LRU cache、blit 游标背景（与 `TimeDomainCanvas` 现有实现保持代码风格一致）。
- order canvas 引入轻量 dB 显示模式（可选，与 spectrogram 一致），由 inspector 控件驱动；初版色阶仍用 'turbo'，但可在 inspector 的高级参数里切换到 'jet'。

**计算层（signal/order.py）：**

- `OrderAnalyzer._order_amplitudes` 接受外部预算窗，循环外预算一次。
- `compute_time_order_result` / `compute_rpm_order_result` / `extract_order_track_result` 三条路径在内层循环外把 `get_analysis_window(window, nfft)` 算好传入。
- `compute_rpm_order_result` 中的 `counts` 语义改为按帧数累加（`counts[ri] += 1`），`safe_counts = np.maximum(counts, 1)`；高于 Nyquist 的 order 列**保留在 `orders` 数组里**（保持向后兼容形状）但在 `_order_amplitudes_batch` 内通过 `valid_orders_mask` 过滤，对应列恒为 0，counts 仍按帧数累加；同时在 `OrderRpmResult.metadata` 与 `OrderTimeResult.metadata` 加 `nyquist_clipped: int` 标注被裁掉的 order 列数。
- `compute_rpm_order_result` 中 RPM-bin 索引**保留 `np.argmin` 语义**，但向量化为单次 broadcast：`np.argmin(np.abs(rpm_means[:, None] - rpm_bins[None, :]), axis=1)`。**理由：**算术索引 (`int(x+0.5)` 取上 vs `argmin` 平局取下) 在半-bin 边界、`rpm_min` 附近、`rpm_res` 不能整除区间时与 `argmin` 不等价；保留 `argmin` 免疫这些边界，向量化后单次成本与算术索引同量级（每帧 < 1 µs）。
- `_order_amplitudes` 内层向量化为新静态方法 `_order_amplitudes_batch(frames, rpm_means, fs, orders, nfft, window_array)`：把所有 frame stack 成 `(N_frames, nfft)`，一次 `np.fft.rfft(... axis=1)`，再用矩阵化 interp 取阶次幅值。**stacking 必须按 chunk 进行**，由模块常量 `_ORDER_BATCH_FRAMES = 256` 控制（`signal/order.py` 顶部），不允许一次 stack 全部 frames。
- **doubling 严格照搬 `signal/fft.py:one_sided_amplitude`：** `if amps.shape[1] > 2: nfft 偶数 → amps[:, 1:-1] *= 2.0; nfft 奇数 → amps[:, 1:] *= 2.0`，`shape[1] == 2`（即 `nfft <= 2`，含 `nfft == 3` 这种 size-2 边界）保持不动。**禁止**自创 doubling 规则，必须与 `one_sided_amplitude` 的 if/elif 分支一一对齐。
- 保留旧的 per-frame `_order_amplitudes` 静态方法**作为测试 baseline**（不再被生产代码调用，但被 `tests/test_order_analysis.py` 用作"向量化等价性"测试的独立基准——避免 baseline 与被测代码同源同 bug）。

**线程层（main_window）：**

- 新增 `OrderWorker(QThread)`，与现有 `SpectrogramWorker` 同结构（构造接收 `kind, sig, rpm, t, params, generation`；emit `result_ready(result, kind, generation)` / `failed(str, generation)` / `progress(int, int)`）。
- `do_order_time` / `do_order_rpm` / `do_order_track` 改成投递 → `result_ready` 回调里 plot。
- 进度条由 worker `progress` 信号驱动，不再 `QApplication.processEvents()`。
- worker 支持取消：在 inspector 上加一个「取消」按钮（与现有 spectrogram 取消一致）。
- **Generation token 反 stale：** `MainWindow._order_generation: int` 单调递增；每次 `_dispatch_order_worker` 启动新 worker 时 `+= 1` 并把当前值传进 worker；`_on_order_result` / `_on_order_failed` / `_on_order_progress` 收到信号时比对 `generation == self._order_generation`，不匹配直接丢弃。这条机制独立于 `cancel()` + `wait()` 的成功与否。
- **MainWindow.closeEvent：** 新增 `closeEvent` 钩子，对 `_order_worker` 与已有的 spectrogram worker 都执行 `cancel(); wait(2000)`；超时 `terminate(); wait(500)`；最后 `super().closeEvent(event)`。
- **`_dispatch_order_worker` 的 wait fallback：** `wait(2000)` 返回值被显式检查；返回 `False` 时 `terminate(); wait(500)` 兜底；旧 worker 在被替换前显式 `disconnect` 所有信号，避免 stale `result_ready` 撞上新 worker 信号。

**Batch 层（batch.py）：**

- `_matrix_to_long_dataframe` 一次 vectorize（`np.repeat` + `np.tile` + `reshape(-1)`）。
- `_compute_fft_dataframe` 加入 `'自动' → None` + `int(...)` 兜底。
- `_run_one` 在 try/finally 里 `fig.clear(); plt.close(fig)`（如未导入 pyplot，则 `del fig` + 显式 GC 一次）。
- `AnalysisPreset` 去掉 `frozen=True`，或改成存放 `tuple` 化的 params；本次选择「去掉 frozen」以最小侵入。
- `BatchRunner._matches` 注释里说明 substring + regex 双模式语义；行为不变。
- `MainWindow.open_batch` 入口校验 `_last_batch_preset.signal` 仍存在，否则降级到 free_config 并 toast 提示。

**测试层：**

- `tests/test_order_analysis.py` 增补：
  - `compute_time_order_result` 在恒速 RPM 下定阶幅值正确性
  - `compute_rpm_order_result` 在多 bin 的均值聚合正确性（直接验证 4.1 counts 语义）
  - `cancel_token` 路径
  - `progress_callback` 路径
- `tests/test_batch_runner.py` 增补：
  - `'自动'` nfft 兜底
  - 失效 preset 降级行为（main_window 层在 UI test 覆盖）
  - 长表 vectorize 形状正确性
- `tests/ui/` 增补：
  - `OrderWorker` 烟雾测试（与 `SpectrogramWorker` 测试同模板）
  - `PlotCanvas` xlim listener / envelope cache 单元测试

### 2.2 Excluded

- mip-map 多分辨率预计算（留待长录数据 future-work）
- pyqtgraph / OpenGL 后端切换
- 3D waterfall、多通道、live streaming
- order 模式自身的 PSD / RMS / dB re X 高级模式
- order canvas 的双游标 / span selector（time-domain 专属）
- batch 的多线程 / 多进程并行（顺序处理已能满足规模）

## 3. Existing Baseline

代码现状（详见 review report §3、§5）：

- `mf4_analyzer/signal/order.py`（codex 2026-04-26 重写）：FFT 路径已并入 `one_sided_amplitude`，dataclass 化，但内层循环未 hoist 窗，counts 语义有歧义，全部同步。
- `mf4_analyzer/batch.py`（codex 2026-04-26 新增）：API 整体合理，但长表生成、Figure 释放、`'自动'` 兜底有真坑。
- `mf4_analyzer/ui/main_window.py:1099, 1159, 1219`：`do_order_*` 同步调用，无 worker。
- `mf4_analyzer/ui/canvases.py:1373` `PlotCanvas`：无 xlim listener、无 envelope、无 blit、无缓存。
- `mf4_analyzer/ui/canvases.py:149` `TimeDomainCanvas`：viewport-aware envelope + xlim debounce + envelope LRU cache + blit 游标全部在位，可作参考实现。
- `mf4_analyzer/ui/canvases.py:1018` `SpectrogramCanvas`：imshow + 复用 axes + colorbar reuse + dB cache 全部在位，可作 2D 渲染的参考实现。
- `mf4_analyzer/ui/main_window.py:29` `SpectrogramWorker(QThread)`：worker 模板。

## 4. Design Decisions

### 4.1 2D 谱：imshow 而非 pcolormesh

**原因：** order 谱的 time / rpm 轴和 order 轴本来就是均匀网格（`np.arange` 生成），`pcolormesh` 的"非规则网格"通用性根本用不上。`imshow` 在均匀网格下与 pcolormesh 在视觉上不可分辨，但单帧渲染快 10–50 倍，且天然可走 `set_data` 复用 axes。

**API 形态：**

```python
self._im = ax.imshow(
    matrix,                       # (Y_bins, X_bins)，注意 imshow 的 (rows, cols)
    origin='lower',
    aspect='auto',
    extent=[x_min, x_max, y_min, y_max],
    cmap=cmap,                    # 默认 'turbo'
    interpolation='bilinear',     # 比 'nearest' 略柔和，与 gouraud 视觉接近但远快
    vmin=vmin,
    vmax=vmax,
)
```

**注意：** 矩阵布局必须从 order.py 返回的 `(N_x, N_orders)` 转置为 imshow 期待的 `(N_orders, N_x)`。在 `do_order_time` 是 `om.T`，在 `do_order_rpm` 是 `om.T`（原本 pcolormesh 也已 `.T` 处理）。

### 4.2 复用 axes / image / colorbar

参照 `SpectrogramCanvas.plot_result`（`canvases.py:1136` 起）已经验证过的模板。新方法 `PlotCanvas.plot_or_update_heatmap(...)` 实现：

```python
def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                           x_label, y_label, title, cmap='turbo',
                           interp='bilinear', vmin=None, vmax=None,
                           cbar_label='Amplitude'):
    """如果当前 figure 结构与新数据兼容，则原地更新 image/colorbar；
    否则重建 axes（与 SpectrogramCanvas 同模式）。"""
```

兼容判定：当前是否有 `self._heatmap_ax` 且只有 1 个 axes（不是 order_track 的 2-subplot 结构）。

### 4.3 OrderWorker 与 SpectrogramWorker 同结构 + Generation Token

```python
class OrderWorker(QThread):
    # 三个信号都带 generation：MainWindow 比对当前 generation 决定是否消费
    result_ready = pyqtSignal(object, str, int)   # (result, kind, generation)
    failed = pyqtSignal(str, int)                  # (message, generation)
    progress = pyqtSignal(int, int, int)           # (current, total, generation)

    def __init__(self, kind, sig, rpm, t, params, generation, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._sig = sig
        self._rpm = rpm
        self._t = t
        self._params = params
        self._generation = int(generation)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from ..signal import OrderAnalyzer
        gen = self._generation
        try:
            cb_progress = lambda i, n: self.progress.emit(i, n, gen)
            cb_cancel = lambda: self._cancelled
            if self._kind == 'time':
                r = OrderAnalyzer.compute_time_order_result(
                    self._sig, self._rpm, self._t, self._params,
                    progress_callback=cb_progress, cancel_token=cb_cancel,
                )
            elif self._kind == 'rpm':
                r = OrderAnalyzer.compute_rpm_order_result(
                    self._sig, self._rpm, self._params,
                    progress_callback=cb_progress, cancel_token=cb_cancel,
                )
            elif self._kind == 'track':
                r = OrderAnalyzer.extract_order_track_result(
                    self._sig, self._rpm, self._params,
                    progress_callback=cb_progress, cancel_token=cb_cancel,
                )
            else:
                raise ValueError(f"unknown kind: {self._kind}")
            if self._cancelled:
                return                       # 取消后不发 result，让 MainWindow 看 generation 也丢
            self.result_ready.emit(r, self._kind, gen)
        except RuntimeError as e:
            if 'cancel' in str(e).lower():
                return
            self.failed.emit(str(e), gen)
        except Exception as e:
            self.failed.emit(str(e), gen)
```

**MainWindow 侧的 dispatcher 与 lifecycle:**

```python
def _dispatch_order_worker(self, kind, sig, rpm, t, params, *, status_msg):
    self._order_generation = getattr(self, '_order_generation', 0) + 1
    gen = self._order_generation

    # 1. 取消并断开旧 worker（如还在跑）
    old = getattr(self, '_order_worker', None)
    if old is not None and old.isRunning():
        try:
            old.result_ready.disconnect()
            old.failed.disconnect()
            old.progress.disconnect()
        except TypeError:
            pass
        old.cancel()
        if not old.wait(2000):
            old.terminate()
            old.wait(500)

    # 2. 创建新 worker，挂接信号
    worker = OrderWorker(kind, sig, rpm, t, params, generation=gen, parent=self)
    worker.progress.connect(self._on_order_progress)
    worker.result_ready.connect(self._on_order_result)
    worker.failed.connect(self._on_order_failed)
    self._order_worker = worker
    self.statusBar.showMessage(status_msg)
    self.inspector.order_ctx.set_progress("0%")
    self.inspector.order_ctx.btn_cancel.setEnabled(True)
    worker.start()

def _on_order_progress(self, current, total, generation):
    if generation != getattr(self, '_order_generation', -1):
        return
    if total > 0:
        self.inspector.order_ctx.set_progress(f"{int(current/total*100)}%")

def _on_order_result(self, result, kind, generation):
    if generation != getattr(self, '_order_generation', -1):
        return
    self.inspector.order_ctx.set_progress("")
    self.inspector.order_ctx.btn_cancel.setEnabled(False)
    if kind == 'time':
        self._render_order_time(result)
    elif kind == 'rpm':
        self._render_order_rpm(result)
    elif kind == 'track':
        self._render_order_track(result)

def _on_order_failed(self, msg, generation):
    if generation != getattr(self, '_order_generation', -1):
        return
    self.inspector.order_ctx.set_progress("")
    self.inspector.order_ctx.btn_cancel.setEnabled(False)
    QMessageBox.critical(self, "错误", msg)

def closeEvent(self, event):
    """窗口关闭：取消所有 worker，不让 parented QThread 在 running 时被 GC。"""
    for attr in ('_order_worker', '_spectrogram_worker'):
        worker = getattr(self, attr, None)
        if worker is not None and worker.isRunning():
            try:
                worker.result_ready.disconnect()
                worker.failed.disconnect()
                worker.progress.disconnect()
            except (TypeError, AttributeError):
                pass
            worker.cancel() if hasattr(worker, 'cancel') else None
            if not worker.wait(2000):
                worker.terminate()
                worker.wait(500)
    super().closeEvent(event)
```

### 4.4 PlotCanvas 升级（xlim debounce + envelope cache + blit）

**直接照搬 `TimeDomainCanvas` 的实现风格**，不引入新 canvas 类型，避免大幅重构 `chart_stack.py` 的 mode-to-index 映射。

新增方法：

```python
def _connect_xlim_listener(self, ax):
    """与 TimeDomainCanvas._connect_xlim_listener 同实现"""

def _on_xlim_changed(self, _ax):
    """与 TimeDomainCanvas._on_xlim_changed 同实现，
    但触发的 refresh 方法是 PlotCanvas._refresh_visible_heatmap"""

def _refresh_visible_heatmap(self):
    """对当前 imshow image 的 extent 做 set_xlim/set_ylim 拉伸即可，
    数据本身不需要重切——imshow 内部按需采样。"""
```

**关键差异**：time-domain 的 envelope 是对 1D 折线做的；order 2D 谱不需要重切数据，只需要在 zoom 时不要触发全图 redraw。所以 PlotCanvas 的 xlim listener 主要价值是：

1. 让 zoom/pan 期间走 `draw_idle` 而非 `draw`
2. 给 order_track 的下半幅 1D 折线接入 envelope（等同 TimeDomainCanvas 的优化）

### 4.5 order_track 下半幅 envelope

`do_order_track` 当前直接 `ax2.plot(rpm, ...)`。改造为：

```python
# 复用 TimeDomainCanvas 的 envelope 逻辑（提取为 module-level helper）
from .canvases import build_envelope
xs, ys = build_envelope(
    np.arange(len(rpm), dtype=float), rpm,
    xlim=None, pixel_width=self.canvas_order.width(),
)
ax2.plot(xs, ys, '#2ca02c', lw=0.8)
```

`build_envelope` 是从 `TimeDomainCanvas._envelope` 抽出的纯函数版本（无 self），同时被 TimeDomainCanvas 内部和这里复用。

### 4.6 order.py 内层向量化

```python
# signal/order.py 顶部模块常量（位于 import 之后）
_ORDER_BATCH_FRAMES = 256

@staticmethod
def _order_amplitudes_batch(frames, rpm_means, fs, orders, nfft, window_array):
    """frames: (N_frames, nfft) — 未 demean，由本函数内部去均值。
    rpm_means: (N_frames,)
    返回: (N_frames, N_orders)

    Doubling 严格照搬 fft.py:one_sided_amplitude 的分支语义。
    """
    work = frames - frames.mean(axis=1, keepdims=True)
    windowed = work * window_array
    spectra = np.fft.rfft(windowed, n=nfft, axis=1)
    win_mean = float(np.mean(window_array))
    amps = np.abs(spectra) / nfft / win_mean
    # —— 严格对齐 one_sided_amplitude.size 分支 ——
    if amps.shape[1] > 2:
        if nfft % 2 == 0:
            amps[:, 1:-1] *= 2.0
        else:
            amps[:, 1:] *= 2.0
    elif amps.shape[1] == 2:
        # nfft <= 2：DC + Nyquist，都不 doubling，与 one_sided_amplitude 对齐
        pass

    freq = np.fft.rfftfreq(nfft, 1.0 / fs)
    freq_per_order = np.abs(rpm_means) / 60.0   # (N_frames,)
    out = np.zeros((len(rpm_means), len(orders)), dtype=float)
    for i, fpo in enumerate(freq_per_order):
        if fpo <= 0 or not np.isfinite(fpo):
            continue
        order_freq = orders * fpo
        valid = (order_freq > 0) & (order_freq <= freq[-1])
        if np.any(valid):
            out[i, valid] = np.interp(order_freq[valid], freq, amps[i])
    return out
```

frames 矩阵**必须按 chunk** stack（不允许一次 stack 全部 frames）：

```python
window_array = get_analysis_window(params.window, nfft)   # 循环外预算一次

for batch_start in range(0, total, _ORDER_BATCH_FRAMES):
    if cancel_token is not None and cancel_token():
        raise RuntimeError("order computation cancelled")
    batch_end = min(batch_start + _ORDER_BATCH_FRAMES, total)
    chunk_starts = starts[batch_start:batch_end]
    frames = np.stack([sig[s:s+nfft] for s in chunk_starts], axis=0)
    rpm_means = np.array(
        [float(np.nanmean(rpm[s:s+nfft])) for s in chunk_starts],
        dtype=float,
    )
    matrix[batch_start:batch_end] = OrderAnalyzer._order_amplitudes_batch(
        frames, rpm_means, fs, orders, nfft, window_array,
    )
    if progress_callback:
        progress_callback(batch_end, total)
```

**内存占用模型：**

- chunk frames 峰值：`_ORDER_BATCH_FRAMES × nfft × 8B`
  - 默认 (256 × 1024 × 8) = 2 MB
  - 高 nfft (256 × 4096 × 8) = 8 MB
  - 极端 nfft (256 × 16384 × 8) = 32 MB
- 输出 matrix 峰值：`N_total_frames × N_orders × 8B`，与 chunk 无关
- 中规模典型场景 (N_frames=1200, N_orders=200) 输出矩阵 ~2 MB

如果 plan 落地后实测峰值不可接受，可在 spec 后续版本引入「chunked write」（输出分块落 mmap），但当前不强制。

**保留旧 per-frame `_order_amplitudes` 静态方法**，标注 "test baseline only"，不再在生产代码路径调用。这是为了让向量化等价性测试有独立基准（避免 baseline 与被测代码同源同 bug）。

### 4.7 显示效果（本期范围）

| 项目 | 本期决策 | 原因 |
|---|---|---|
| 默认 colormap | `turbo`（与 spectrogram 一致；inspector 已有的 cmap 选项保持，可切 'jet'） | 与 spectrogram 一致即可 |
| 插值 | `bilinear`（视觉柔和，远快于 gouraud） | 详见 spec §4.1 |
| `vmin / vmax` | `vmin=nanmin(z), vmax=nanmax(z)` | 与现有行为一致，不引入新控件 |
| 颜色条 | 复用 + `update_normal`，不重建 | 详见 §4.2 |
| 字体 | 沿用全局 `_fonts.py` 配置 | 已在位 |
| 边框 / 网格 | 沿用 `_apply_axes_style` | 已在位 |
| 动态范围控件（Auto / 60 dB / 80 dB） | ⏸ **deferred 到下一期** | 见 §11 |
| order 模式 dB / dB re X 显示 | ⏸ **deferred 到下一期** | 见 §11 |
| order / RPM 轴范围锁定控件 | ⏸ **deferred 到下一期** | 见 §11 |
| dB 缓存 | ⏸ **deferred**（依赖 dB 模式上线） | 见 §11 |

color map 切换沿用 inspector 现有的 cmap 选项（如果 `OrderContextual` 还没有，留作 deferred）；本期目标只确保 `turbo` 默认 + 后续可扩展。

## 5. 模块边界（避免 squad 跨专家撞车）

按 squad orchestrator 经验（`docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`、`2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`）锁定边界：

| 文件 | 唯一负责的专家 |
|---|---|
| `mf4_analyzer/signal/order.py` | signal-processing-expert |
| `mf4_analyzer/batch.py` | signal-processing-expert |
| `tests/test_order_analysis.py` | signal-processing-expert |
| `tests/test_batch_runner.py` | signal-processing-expert |
| `mf4_analyzer/ui/canvases.py` | pyqt-ui-engineer（含 envelope helper 抽出） |
| `mf4_analyzer/ui/main_window.py` | pyqt-ui-engineer |
| `tests/ui/*` 中本次新增项 | pyqt-ui-engineer |

`mf4_analyzer/signal/__init__.py` 如果需要新增导出（例如 `OrderHeatmapResult`），由 signal-processing-expert 负责。

## 6. API 契约

### 6.1 `OrderAnalyzer` 公共方法保持不变

`compute_order_spectrum_time_based` / `compute_order_spectrum` / `extract_order_track` 三个 legacy tuple-returning API 必须继续工作（`main_window.py` 外没有其他调用方，但保留契约以防回归）。

### 6.2 新增 `PlotCanvas.plot_or_update_heatmap`

```python
def plot_or_update_heatmap(
    self,
    *,
    matrix: np.ndarray,           # shape (N_y, N_x)
    x_extent: tuple[float, float],
    y_extent: tuple[float, float],
    x_label: str,
    y_label: str,
    title: str,
    cmap: str = 'turbo',
    interp: str = 'bilinear',
    vmin: float | None = None,
    vmax: float | None = None,
    cbar_label: str = 'Amplitude',
) -> None: ...
```

**兼容判定（共四条都成立才走 set_data 路径，否则 clear+rebuild）：**

1. `self._heatmap_ax is not None` 且 `self._heatmap_im is not None` 且 `self._heatmap_cbar is not None`
2. `self._heatmap_ax in self.fig.axes`
3. `len(self.fig.axes) == 2`（heatmap axes + colorbar axes）
4. `existing_im.get_array().shape == matrix.shape`（shape 一致才能走 `set_data`；不一致显式 fall back）

第 4 条是 codex review 提出的：matplotlib `AxesImage.set_data` 虽然支持 shape 变化，但行为有限制，本 spec 选择"shape 不一致就 clear+rebuild"以保守。

### 6.3 `OrderWorker` 见 §4.3

`OrderWorker` 信号签名：`result_ready(object result, str kind, int generation)` / `failed(str message, int generation)` / `progress(int current, int total, int generation)`。MainWindow 必须比对 `generation == self._order_generation`，不匹配直接丢弃。

### 6.4 module-level `build_envelope`

```python
def build_envelope(
    t: np.ndarray, sig: np.ndarray,
    *, xlim: tuple[float, float] | None,
    pixel_width: int,
    is_monotonic: bool | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Pure 函数版本的 viewport-aware envelope 下采样。
    与 TimeDomainCanvas._envelope 行为完全一致；TimeDomainCanvas 内部
    应改为 thin wrapper 调这个函数。"""
```

## 7. 验收标准（可测量）

| # | 标准 | 验收方式 |
|---|---|---|
| 1 | 中规模 (60 s × 24 kHz, nfft=1024, order_res=0.1) order 模式拖动 ≥ 30 fps | 🧪 手动烟雾 + 屏幕录制 |
| 2 | order 计算运行期间窗体不冻结（可切换 canvas / 调参 / 拖其它图） | 🧪 手动烟雾 |
| 3 | order_track 大规模 (300 s × 48 kHz) 下半幅 RPM 拖动 ≥ 30 fps | 🧪 手动烟雾 |
| 4 | order 2D 谱视觉清晰度 ≥ 当前 gouraud 版本 | 🧪 手动 before/after 截图对比 + 用户签字 |
| 5 | 同参数二次计算命中缓存出图 < 100 ms | ⏸ deferred（依赖 `_order_result_cache` 落地） |
| 6 | 既有 `tests/test_order_analysis.py` + `tests/test_batch_runner.py` 全部通过 | ✅ 自动 (pytest) |
| 7 | 新增 7 项算法/向量化等价/counts/cancel/progress/Nyquist 裁剪测试通过 | ✅ 自动 (pytest) |
| 8 | 新增 4 项 UI/worker 测试通过（envelope helper、heatmap reuse、worker cancel、stale preset） | ✅ 自动 (pytest) |
| 9 | batch 200 文件 order_time 顺序处理峰值内存增量 < 200 MB | ✅ 自动 (`tracemalloc` step in plan) |
| 10 | Inspector / Toolbar 上现有的所有 order 控件行为不变 | 🧪 手动烟雾 |
| 11 | 同 nfft 下 `_order_amplitudes_batch` 与旧 per-frame `_order_amplitudes` 数值完全一致（rtol=1e-9） | ✅ 自动 (pytest) |
| 12 | RPM-bin 索引向量化结果与旧 `argmin` 逐帧实现完全一致（含半-bin 边界、`rpm_min` / `rpm_max` 处的 tie） | ✅ 自动 (pytest) |
| 13 | order_rpm 模式下 imshow 视觉与旧 `pcolormesh(ords, rb, om, shading='gouraud')` 的轴语义一致（x=order, y=rpm） | 🧪 手动截图对比 + ✅ 自动单元测试断言 extent / 矩阵方向 |
| 14 | MainWindow 关闭时若 order/spectrogram worker 仍在跑，能正常退出不报 QThread destroyed warning | ✅ 自动 (pytest UI smoke) |
| 15 | 快速 3 次连点 do_order_time 不出现 stale `result_ready` 渲染 | ✅ 自动 (generation token 单元测试) |

图例：✅ = 自动测试覆盖；🧪 = 手动烟雾；⏸ = 本期不验收。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| imshow 在非均匀 RPM bin 下视觉失真 | RPM bin 用 `np.arange(rpm_min, rpm_max+rpm_res/2, rpm_res)` 已经是均匀的；如果未来引入对数 bin，此 spec 假设破产，要回退到 pcolormesh 分支。在 `plot_or_update_heatmap` 加 docstring 注明这一假设。 |
| OrderWorker 未及时取消 | `cancel_token` 在每个 `_ORDER_BATCH_FRAMES` chunk 边界 + chunk 内 frames stack 之前 + FFT batch 之前共 3 处检查；`wait(2000)` 超时显式 `terminate(); wait(500)`（lessons-learned `2026-04-25-qthread-wait-deadlocks-queued-quit.md`）。 |
| Stale worker 结果撞上新 worker | Generation token 模式（§4.3）：每个信号回调入口比对 `generation == self._order_generation`，不匹配直接 `return`，独立于 cancel 是否成功。 |
| MainWindow 关闭时 worker 仍在跑 → QThread destroyed warning / crash | 新增 `closeEvent`（§4.3）显式 cancel + wait + terminate 兜底，对 order/spectrogram worker 都做。 |
| 内层 vectorize 的内存峰值 | chunked 强制（§4.6 `_ORDER_BATCH_FRAMES = 256`），中规模 chunk frames < 10 MB；plan 内 tracemalloc step 验证。 |
| `_order_amplitudes_batch` doubling 与 `one_sided_amplitude` 漂移 | spec §4.6 明确强制照搬 if/elif 分支；plan 等价性测试用旧 per-frame `_order_amplitudes` 作独立 baseline。 |
| `build_envelope` 抽函数后 TimeDomainCanvas 行为漂移 | TDD：在重构前确保 `tests/ui/test_envelope.py` + `tests/ui/test_xlim_refresh.py` 全绿；重构后必须再跑一次。 |
| `frozen=False` 后 AnalysisPreset 被意外 mutate | 加单元测试覆盖 `dataclasses.replace(preset, outputs=...)` 仍能工作；docstring 注明"按值传递，请勿原地修改字段"。 |
| 算术索引边界与 `argmin` 行为漂移 | 本期不引入算术索引，保留 `argmin` 语义但向量化为 broadcast；plan 加边界等价性测试覆盖半-bin / `rpm_min` / `rpm_max` / 非整除 `rpm_res`。 |
| order_rpm 矩阵方向写错 | spec §6.2 第 4 条 + plan T5 `_render_order_rpm` 显式选择 "matrix=result.amplitude (不转置), x_extent=orders, y_extent=rpm_bins"；附自动单元测试断言 extent 与矩阵 shape 对应关系。 |

## 9. 不破坏的假设

- `mf4_analyzer/signal/__init__.py` 已导出的所有符号继续存在。
- `OrderAnalysisParams` 字段名不变。
- `OrderRpmResult.counts` 字段形状不变（仍是 `(N_rpm_bins, N_orders)`），但**语义改变**为按帧数累加；详见 review report §4.1 的 API compatibility note。
- `BatchRunner.run` 签名不变。
- `MainWindow.do_order_time/rpm/track` 方法名继续存在（只改实现）。
- `MainWindow` 现在新增 `closeEvent`（之前没有）；其它 lifecycle 方法不变。
- inspector 上的 order 控件 ID 不变；新增 `OrderContextual.btn_cancel` 和 `cancel_requested` 信号属于增量。
- chart_stack 的 mode-to-index 映射 (`time=0, fft=1, fft_time=2, order=3`) 不变。

## 10. Open Questions（已在 codex round 1 review 中处理）

1. 是否需要在本 spec 内引入 order 模式的 dB 显示？→ **决议：不引入**，移入 §11 Deferred。
2. `build_envelope` 抽出后，是否同步把 `SpectrogramCanvas` 的"hover bounds clamp"也抽成 helper？→ **决议：不抽**，避免范围漂移。
3. `OrderWorker` 是否需要支持「同参数复用上次结果」的内部缓存？→ **决议：不实现**，移入 §11 Deferred（`_order_result_cache`）。
4. `imshow(interp='bilinear')` vs `'nearest'` 默认值选哪个？→ **决议：`'bilinear'`**，并在 plan 加 gouraud vs bilinear 截图对比 step。
5. Inspector 是否需要加「取消计算」按钮？→ **决议：是**，已在 §4.3 + plan T6 落实。
6. RPM-bin 索引用算术 vs `argmin`？→ **决议：保留 `argmin`** 但向量化为 broadcast（避免边界等价性问题）。

## 11. Deferred to Next Iteration

以下功能本期**显式不做**，留待下一期（不阻塞本 spec 落地）：

| 功能 | 原因 |
|---|---|
| order 模式 dB / dB re X 显示 | 牵动 inspector 控件 + `OrderHeatmapResult` 数据契约 + colorbar label + cursor 单位 4 处级联，过度膨胀本期范围 |
| 动态范围控件（Auto / 60 dB / 80 dB） | 依赖 dB 模式上线 |
| order / RPM 轴范围锁定控件 | 需要 inspector 新增控件群，与本期"不改 UI"原则冲突 |
| `_order_result_cache`（同参复用） | 验收标准 §7-5 已 deferred；落地价值低于 worker + imshow + envelope 三件套 |
| Mip-map 多分辨率预计算 | 仅长录数据 (≥ 5 min @ 48 kHz) 才有显著收益；本期 imshow + chunked compute 已能覆盖典型场景 |
| pyqtgraph / OpenGL 后端切换 | 体量过大，且 matplotlib + imshow 已能达到 ≥ 30 fps 验收标准 |
| 3D waterfall / 多通道 / live streaming | 永久 out of scope（report §10） |

---

**结论：** 本 spec 范围聚焦 order 这一摊代码的"渲染 / 显示 / 交互"三维质量提升，不扩展功能广度。所有改动都有现成的同仓库参考实现（spectrogram canvas 的 imshow、time-domain canvas 的 envelope/blit、SpectrogramWorker 的线程模板）；落地难度可控，风险来自（a）counts 语义的回归测试覆盖、（b）vectorize 后的内存峰值、（c）`build_envelope` 抽出对 TimeDomainCanvas 的影响、（d）generation token / closeEvent 对现有 spectrogram worker 的兼容性——后者必须在 plan T5 显式回归。
