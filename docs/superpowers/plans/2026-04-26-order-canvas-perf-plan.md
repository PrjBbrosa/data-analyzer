# Order Canvas 渲染 / 显示 / 交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **本仓库走 squad runbook**：每个 Task 标注的 `expert` 字段决定该任务由哪个 specialist 接手；main Claude 是唯一 dispatcher。

**Goal:** 把 order 模式的渲染性能、显示效果、交互流畅性推到与 spectrogram canvas / time-domain canvas 同档；同时修掉 codex 2026-04-26 改动里数学和工程层面的真问题。

**Architecture:** 计算层 hoist 窗 + 向量化内层 FFT + 修正 counts 语义；线程层引入 `OrderWorker(QThread)` 摆脱 GUI 阻塞；渲染层把 `pcolormesh(gouraud)` 切换到 `imshow(bilinear)`、复用 axes/colorbar；交互层把 `TimeDomainCanvas` 已有的 envelope / xlim debounce / blit 三件套抽出 module-level helper 同时供 `PlotCanvas` 和 order_track 下半幅复用。

**Tech Stack:** PyQt5、matplotlib、numpy、scipy、pandas、pytest、pytest-qt。

---

## Reference Documents

- 诊断报告：`docs/superpowers/reports/2026-04-26-order-canvas-perf-review.md`
- 设计 spec：`docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`
- codex 改动 spec：`docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`
- 同档参考实现：
  - spectrogram canvas: `mf4_analyzer/ui/canvases.py:1018-1370`
  - SpectrogramWorker: `mf4_analyzer/ui/main_window.py:29-110`
  - time-domain envelope/cache/blit: `mf4_analyzer/ui/canvases.py:149-1015`
  - time-domain perf 方法论：`docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md`
- squad runbook：`CLAUDE.md` "Squad runbook (four phases)"

## File Map

| 文件 | 操作 | 任务 | Owner |
|---|---|---|---|
| `mf4_analyzer/signal/order.py` | Modify | T1 | signal-processing-expert |
| `mf4_analyzer/batch.py` | Modify | T2 | signal-processing-expert |
| `tests/test_order_analysis.py` | Modify | T1, T3 | signal-processing-expert |
| `tests/test_batch_runner.py` | Modify | T2, T3 | signal-processing-expert |
| `mf4_analyzer/ui/canvases.py` | Modify | T4 | pyqt-ui-engineer |
| `tests/ui/test_canvases_envelope.py` | Create | T4 | pyqt-ui-engineer |
| `mf4_analyzer/ui/main_window.py` | Modify | T5, T6 | pyqt-ui-engineer |
| `tests/ui/test_order_worker.py` | Create | T5 | pyqt-ui-engineer |
| `mf4_analyzer/ui/inspector_sections.py` | Modify | T6 | pyqt-ui-engineer |
| `tests/ui/test_order_smoke.py` | Create | T6 | pyqt-ui-engineer |

## Dependency Graph

```
T1 ──┬── T3 (signal tests)
T2 ──┘
T4 ───── T5 ───── T6
T1 ──────┘
```

- T1 / T2 / T4 互不冲突，**可并行**。
- T3 依赖 T1 + T2 同时落地。
- T5 依赖 T1（用到 vectorized order API）+ T4（用到 `plot_or_update_heatmap` / `build_envelope`）。
- T6 依赖 T5（最终集成）。

---

## Task 1 — signal/order.py 数学层修正与向量化

**Owner:** signal-processing-expert
**Files:**
- Modify: `mf4_analyzer/signal/order.py`
- Test: `tests/test_order_analysis.py`

- [ ] **Step 1: 写失败测试 — counts 语义按帧数**

在 `tests/test_order_analysis.py` 末尾追加。**关键：** 用 `OrderAnalyzer._frame_starts` 算真实帧数（`hop = nfft // 4`），构造能区分新旧两种语义的信号。

```python
def test_rpm_order_counts_are_per_frame_not_per_nonzero():
    """compute_rpm_order_result 的 counts 应按帧数累加，而非按非零幅值次数。

    构造原理：
    - 恒速 rpm → 所有帧落入同一个 rpm_bin
    - 信号是「每隔 hop 个 sample 才有一段 tone」的稀疏脉冲序列
    - 这样 ~半数 frame 是几乎全零（amp ≈ 0），~半数 frame 有 tone
    - 旧语义 (`counts += values > 0`)：只计有 tone 的帧 → counts ≈ N_with_tone
    - 新语义 (`counts += 1`)：所有帧都计 → counts == N_total_frames
    - 两者数值显著不同，可区分
    """
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    fs = 1024.0
    nfft = 512
    rpm_const = 600.0
    rpm_res = 10.0

    # 构造稀疏脉冲：偶数帧有 50 Hz 正弦，奇数帧全零
    hop = nfft // 4
    n_frames_target = 12
    n = nfft + hop * (n_frames_target - 1)
    rpm = np.full(n, rpm_const)
    sig = np.zeros(n)
    starts = OrderAnalyzer._frame_starts(n, nfft, hop)
    expected_frames = len(starts)
    for i, s in enumerate(starts):
        if i % 2 == 0:
            t_local = np.arange(nfft) / fs
            sig[s:s+nfft] += 0.5 * np.sin(2 * np.pi * 50.0 * t_local)

    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, rpm_res=rpm_res)
    result = OrderAnalyzer.compute_rpm_order_result(sig, rpm, params)

    # 1) 找到含有 tone 的 bin（恒速下应该只有一个 bin 非空）
    populated_bin = int(np.argmax(result.counts.sum(axis=1)))
    # 2) 该 bin 的 counts 必须等于真实总帧数（按帧数累加），而非约半数（按非零累加）
    #    在每个 order 列上都应一致
    assert np.all(result.counts[populated_bin] == expected_frames), (
        f"counts must be per-frame; expected {expected_frames}, "
        f"got distribution {np.unique(result.counts[populated_bin])}"
    )
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "/Users/donghang/Downloads/data analyzer"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_rpm_order_counts_are_per_frame_not_per_nonzero -v
```

预期：FAIL（旧实现 counts ≈ expected_frames / 2）。

- [ ] **Step 3: 修正 counts 语义**

`mf4_analyzer/signal/order.py` 中 `compute_rpm_order_result`（约 200 行附近）：

```python
            matrix[ri] += values
            counts[ri] += 1                      # ← 原 counts[ri] += values > 0
            ...
        if progress_callback:
            progress_callback(total, total)
        safe_counts = np.maximum(counts, 1)      # ← 原 safe_counts = counts.copy(); safe_counts[safe_counts==0]=1
        return OrderRpmResult(
            orders=orders,
            rpm_bins=rpm_bins,
            amplitude=matrix / safe_counts,
            counts=counts,
            params=params,
            metadata={'frames': total, 'hop': hop, 'nyquist_clipped': 0},
        )
```

注意：`counts` 现在是 `(N_rpm_bins, N_orders)`，每行所有列的值相同（按帧数）；NumPy 会把 `+= 1` 广播到整行。`metadata` 多加 `nyquist_clipped` 字段，初始填 0，后续 step 9-10 会写入真实裁剪数。

- [ ] **Step 4: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_rpm_order_counts_are_per_frame_not_per_nonzero -v
```

预期：PASS。

- [ ] **Step 5: 写测试 — RPM-bin 索引向量化与 argmin 等价（含边界）**

**决策：** 不引入算术索引，保留 `np.argmin` 语义，向量化为 broadcast。本 step 加多组边界测试，证明向量化路径与逐帧 `argmin` 完全等价。

```python
def test_rpm_bin_index_vectorized_matches_argmin_at_boundaries():
    """rpm_bin 索引向量化 (broadcast argmin) 必须与逐帧 argmin 完全等价，
    含半-bin tie / rpm_min 边界 / rpm_max 边界 / rpm_res 不能整除区间。"""
    rpm_min, rpm_max, rpm_res = 600.0, 3550.0, 100.0   # 区间 2950 不能被 100 整除
    rpm_bins = np.arange(rpm_min, rpm_max + rpm_res * 0.5, rpm_res)
    # 构造一组刁钻的 rpm_means
    rpm_means = np.array([
        rpm_min,                       # 紧贴左边界
        rpm_min - 5,                   # 略低于左边界
        rpm_max,                       # 紧贴右边界
        rpm_max + 5,                   # 略高于右边界
        rpm_min + rpm_res * 0.5,       # 完美半-bin tie（argmin 取小）
        rpm_min + rpm_res * 0.5 + 1e-9,
        rpm_min + rpm_res * 0.5 - 1e-9,
        rpm_min + rpm_res * 1.5,       # 第二个半-bin tie
        rpm_min + 1234.5,              # 区间内任意点
    ])
    # 逐帧 argmin（reference）
    expected = np.array([
        int(np.argmin(np.abs(rpm_bins - x))) for x in rpm_means
    ])
    # 向量化 broadcast argmin（候选实现）
    diffs = np.abs(rpm_means[:, None] - rpm_bins[None, :])
    actual = np.argmin(diffs, axis=1)
    np.testing.assert_array_equal(actual, expected)
```

- [ ] **Step 6: 跑测试 — 该测试验证候选向量化算法本身**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_rpm_bin_index_vectorized_matches_argmin_at_boundaries -v
```

预期：PASS（这是纯算法测试，与 `OrderAnalyzer` 实现无关）。

- [ ] **Step 7: 在 `compute_rpm_order_result` 内层使用 broadcast argmin**

后续 Step 12 重写 `compute_rpm_order_result` 时把内层的 `int(np.argmin(np.abs(rpm_bins - rpm_mean)))` 替换为：

```python
ri_array = np.argmin(
    np.abs(rpm_means[:, None] - rpm_bins[None, :]),
    axis=1,
)   # shape (N_frames_in_chunk,)
```

并在 chunked 循环里用 `ri_array` 做 fancy indexing。**禁止**用 `int((x - rpm_min) / rpm_res + 0.5)` 算术索引（边界等价性已在 Step 5 排除）。

- [ ] **Step 8: 写测试 — time-order 在恒速 RPM 下定阶幅值**

```python
def test_time_order_recovers_target_order_amplitude():
    """compute_time_order_result 在恒速 RPM 下应能恢复目标 order 的幅值。"""
    fs = 2048.0
    nfft = 2048
    n = nfft * 5
    rpm_const = 1800.0
    rpm = np.full(n, rpm_const)
    target_order = 3.0
    freq = target_order * rpm_const / 60.0
    amp = 1.7
    t = np.arange(n, dtype=float) / fs
    sig = amp * np.sin(2 * np.pi * freq * t)

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.1)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    # 找到 target_order 对应的列
    j = int(np.argmin(np.abs(result.orders - target_order)))
    recovered = np.median(result.amplitude[:, j])
    assert np.isclose(recovered, amp, rtol=0.05), (
        f"target order amplitude {recovered}, expected {amp}"
    )
```

- [ ] **Step 9: 跑测试确认通过（counts/argmin 修正后应自动通过）**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py -v
```

预期：全部 PASS。

- [ ] **Step 10: 引入向量化窗 hoist —— 写性能/正确性双测**

```python
def test_time_order_vectorized_matches_loop():
    """向量化路径应与 per-frame 实现产出完全一致的结果。"""
    fs = 1024.0
    nfft = 512
    n = nfft * 4
    rng = np.random.default_rng(42)
    sig = rng.standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.05)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    # 抽 3 帧手算 baseline
    from mf4_analyzer.signal.fft import one_sided_amplitude
    orders = OrderAnalyzer._orders(params.max_order, params.order_res)
    hop = max(int(fs * params.time_res), 1)
    starts = list(range(0, n - nfft + 1, hop))
    for idx in [0, len(starts) // 2, len(starts) - 1]:
        s = starts[idx]
        rpm_mean = float(np.nanmean(rpm[s:s+nfft]))
        baseline = OrderAnalyzer._order_amplitudes(
            sig[s:s+nfft], rpm_mean, fs, orders, nfft, params.window
        )
        np.testing.assert_allclose(result.amplitude[idx], baseline, rtol=1e-9)
```

- [ ] **Step 11: 跑测试确认当前 per-frame 实现通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_time_order_vectorized_matches_loop -v
```

预期：PASS（这一步先验证 baseline 测试本身是对的，然后再做向量化重构）。

- [ ] **Step 12: 实现向量化内层 + 窗 hoist + Nyquist 裁剪 + 模块常量**

`mf4_analyzer/signal/order.py` 顶部新增模块常量（在 `import` 之后、`@dataclass` 之前）：

```python
# Chunk size for vectorized FFT batching. Bounded to keep
# peak frame-stack memory (BATCH * nfft * 8B) within ~32 MB at extreme nfft.
_ORDER_BATCH_FRAMES = 256
```

在 `OrderAnalyzer` 内新增 `_order_amplitudes_batch`（**doubling 严格照搬 `signal/fft.py:one_sided_amplitude` 的 if/elif 分支语义**）。**保留旧 `_order_amplitudes` 静态方法**——它不再被生产代码调用，仅作为测试 baseline，避免向量化 baseline 与被测代码同源同 bug。

```python
    @staticmethod
    def _order_amplitudes_batch(frames, rpm_means, fs, orders, nfft, window_array):
        """frames: (N_frames, nfft)，未 demean，由本函数内部去均值。
        rpm_means: (N_frames,) RPM mean per frame。
        返回: (N_frames, N_orders)。

        Doubling 与 fft.py:one_sided_amplitude 逐分支对齐：
          - amps.shape[1] > 2 + nfft 偶数: amps[:, 1:-1] *= 2.0
          - amps.shape[1] > 2 + nfft 奇数: amps[:, 1:]   *= 2.0
          - amps.shape[1] == 2: 不动（与 size==2 分支对齐）

        不在本函数内做 Nyquist clipping —— 高于 Nyquist 的 order 列由调用方
        在 valid_orders_mask 上处理（保持本函数纯数值、可作 batch 单元测试）。
        """
        work = frames - frames.mean(axis=1, keepdims=True)
        windowed = work * window_array
        spectra = np.fft.rfft(windowed, n=nfft, axis=1)
        win_mean = float(np.mean(window_array))
        amps = np.abs(spectra) / nfft / win_mean
        if amps.shape[1] > 2:
            if nfft % 2 == 0:
                amps[:, 1:-1] *= 2.0
            else:
                amps[:, 1:] *= 2.0
        elif amps.shape[1] == 2:
            pass   # nfft <= 2: DC + Nyquist，不 doubling

        freq = np.fft.rfftfreq(nfft, 1.0 / fs)
        freq_per_order = np.abs(rpm_means) / 60.0
        out = np.zeros((len(rpm_means), len(orders)), dtype=float)
        for i, fpo in enumerate(freq_per_order):
            if fpo <= 0 or not np.isfinite(fpo):
                continue
            order_freq = orders * fpo
            valid = (order_freq > 0) & (order_freq <= freq[-1])
            if np.any(valid):
                out[i, valid] = np.interp(order_freq[valid], freq, amps[i])
        return out

    # —— 注：旧 _order_amplitudes 保留不动，仅作 test baseline ——
```

把 `compute_time_order_result` 重写为 chunked 版（cancel 在 3 处检查：chunk 边界 / stack frames 之前 / FFT batch 之前——后两处通过把 cancel check 放在 stack/batch 调用前实现）：

```python
    @staticmethod
    def compute_time_order_result(sig, rpm, t, params, progress_callback=None, cancel_token=None):
        sig, rpm, fs, nfft = OrderAnalyzer._validate_common(sig, rpm, params.fs, params.nfft)
        orders = OrderAnalyzer._orders(params.max_order, params.order_res)
        hop = max(int(fs * float(params.time_res)), 1)
        starts = OrderAnalyzer._frame_starts(len(sig), nfft, hop)
        total = len(starts)
        if total == 0:
            raise ValueError("no complete order-analysis frames")

        from .fft import get_analysis_window
        window_array = get_analysis_window(params.window, nfft)

        # Nyquist clipping mask: which order columns are reachable
        # at the median rpm? 仅用于 metadata 标注，不裁剪 orders 数组。
        median_rpm = float(np.nanmedian(rpm))
        median_fpo = abs(median_rpm) / 60.0
        nyq = fs * 0.5
        if median_fpo > 0:
            nyquist_clipped = int(np.sum(orders * median_fpo > nyq))
        else:
            nyquist_clipped = 0

        t_arr = None if t is None else OrderAnalyzer._as_float_vector('time', t)
        if t_arr is not None and len(t_arr) != len(sig):
            raise ValueError(f"time and signal length mismatch: {len(t_arr)} vs {len(sig)}")

        times = np.zeros(total, dtype=float)
        matrix = np.zeros((total, len(orders)), dtype=float)

        def _check_cancel():
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")

        for batch_start in range(0, total, _ORDER_BATCH_FRAMES):
            _check_cancel()                           # cancel check #1: chunk 边界
            batch_end = min(batch_start + _ORDER_BATCH_FRAMES, total)
            chunk_starts = starts[batch_start:batch_end]

            _check_cancel()                           # cancel check #2: stack 之前
            frames = np.stack([sig[s:s+nfft] for s in chunk_starts], axis=0)
            rpm_means = np.array(
                [float(np.nanmean(rpm[s:s+nfft])) for s in chunk_starts],
                dtype=float,
            )
            if t_arr is not None:
                times[batch_start:batch_end] = np.array(
                    [float(t_arr[s + nfft // 2]) for s in chunk_starts]
                )
            else:
                times[batch_start:batch_end] = np.array(
                    [(s + nfft / 2.0) / fs for s in chunk_starts]
                )

            _check_cancel()                           # cancel check #3: FFT 之前
            matrix[batch_start:batch_end] = OrderAnalyzer._order_amplitudes_batch(
                frames, rpm_means, fs, orders, nfft, window_array,
            )
            if progress_callback:
                progress_callback(batch_end, total)

        return OrderTimeResult(
            times=times,
            orders=orders,
            amplitude=matrix,
            params=params,
            metadata={'frames': total, 'hop': hop, 'nyquist_clipped': nyquist_clipped},
        )
```

`compute_rpm_order_result` 同样改造：

- 顶部预算 `window_array`
- 外层按 `_ORDER_BATCH_FRAMES` chunk
- 内层用 broadcast argmin 算 `ri_array = np.argmin(np.abs(rpm_means[:, None] - rpm_bins[None, :]), axis=1)`
- 调 `_order_amplitudes_batch` 拿到 `(BATCH, N_orders)` 的 `values_batch`
- 写回：循环 `for i, ri in enumerate(ri_array): matrix[ri] += values_batch[i]; counts[ri] += 1`（`np.add.at` 也可，注意 counts 要 broadcast `+=1`）
- `cancel` 检查 3 处同上
- metadata 加 `nyquist_clipped`（同上策略）

`extract_order_track_result` 改造：

- 顶部预算 `window_array`
- 外层按 `_ORDER_BATCH_FRAMES` chunk
- 调 `_order_amplitudes_batch(..., orders=np.array([params.target_order]))`，直接拿一列
- cancel 检查 3 处同上
- metadata 加 `nyquist_clipped`

**实现验收：**

- 所有现有测试 PASS
- counts 测试 (Step 1-4) 已通过
- argmin 边界等价测试 (Step 5-7) 已通过
- 新增 vectorize-vs-loop 等价性测试 PASS（本任务 Step 10-11）

- [ ] **Step 13: 跑全套 order 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py -v
```

预期：所有 PASS。

- [ ] **Step 14: 跑 signal 烟雾**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_signal_no_gui_import.py tests/test_fft_amplitude_normalization.py tests/test_spectrogram.py -v
```

预期：全部 PASS（确认本任务没影响其它 signal 模块）。

- [ ] **Step 15: 增强等价性测试 — 全帧 + 三种 result 类型**

Step 10 的等价性测试只比 3 帧 + 只比 time-order。补一个全覆盖版本：

```python
def test_vectorized_paths_match_loop_for_all_results():
    """compute_time/rpm_order_result 与 extract_order_track_result 都必须
    与逐帧 _order_amplitudes 完全一致（rtol=1e-9）。"""
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    fs = 1024.0
    nfft = 512
    n = nfft * 6 + 100
    rng = np.random.default_rng(7)
    sig = rng.standard_normal(n)
    rpm = np.linspace(600.0, 2400.0, n)
    t = np.arange(n, dtype=float) / fs

    # === time-order ===
    p_time = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)
    r_time = OrderAnalyzer.compute_time_order_result(sig, rpm, t, p_time)
    orders = OrderAnalyzer._orders(p_time.max_order, p_time.order_res)
    hop = max(int(fs * p_time.time_res), 1)
    starts = OrderAnalyzer._frame_starts(n, nfft, hop)
    expected_full = np.zeros((len(starts), len(orders)))
    for i, s in enumerate(starts):
        rpm_mean = float(np.nanmean(rpm[s:s+nfft]))
        expected_full[i] = OrderAnalyzer._order_amplitudes(
            sig[s:s+nfft], rpm_mean, fs, orders, nfft, p_time.window
        )
    np.testing.assert_allclose(r_time.amplitude, expected_full, rtol=1e-9)

    # === order-track ===
    p_track = OrderAnalysisParams(fs=fs, nfft=nfft, target_order=2.5)
    r_track = OrderAnalyzer.extract_order_track_result(sig, rpm, p_track)
    track_orders = np.array([p_track.target_order])
    hop_track = max(nfft // 4, 1)
    starts_track = OrderAnalyzer._frame_starts(n, nfft, hop_track)
    expected_track = np.zeros(len(starts_track))
    for i, s in enumerate(starts_track):
        rpm_mean = float(np.nanmean(rpm[s:s+nfft]))
        expected_track[i] = OrderAnalyzer._order_amplitudes(
            sig[s:s+nfft], rpm_mean, fs, track_orders, nfft, p_track.window
        )[0]
    np.testing.assert_allclose(r_track.amplitude, expected_track, rtol=1e-9)
```

- [ ] **Step 16: 跑测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_vectorized_paths_match_loop_for_all_results -v
```

预期：PASS。

- [ ] **Step 17: 写测试 — Nyquist 裁剪 metadata 标注**

```python
def test_metadata_records_nyquist_clipped_orders():
    """高 max_order × 低 RPM 场景下，metadata 应标注被裁剪的 order 列数。"""
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    fs = 1024.0           # Nyquist = 512 Hz
    nfft = 1024
    n = nfft * 4
    rpm = np.full(n, 600.0)   # rpm/60 = 10 Hz
    sig = np.random.default_rng(0).standard_normal(n)
    t = np.arange(n, dtype=float) / fs
    # max_order = 100 → 最大 freq = 100 * 10 = 1000 Hz > Nyquist 512 Hz
    # → 约 ((100 - 51.2) / 0.5) ≈ 97 个 order 列被裁
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=100.0,
                                  order_res=0.5, time_res=0.1)
    r = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    assert 'nyquist_clipped' in r.metadata
    assert r.metadata['nyquist_clipped'] > 0
    # 裁剪列对应的 amplitude 必须是 0
    median_fpo = 600.0 / 60.0
    nyq = fs * 0.5
    clipped_mask = r.orders * median_fpo > nyq
    assert np.allclose(r.amplitude[:, clipped_mask], 0.0)
```

- [ ] **Step 18: 跑测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_metadata_records_nyquist_clipped_orders -v
```

预期：PASS（Step 12 已经把 metadata['nyquist_clipped'] 写入；amplitude 已经因为 `valid` mask 自然为 0）。

- [ ] **Step 19: 内存 profile — 极端 nfft 下的 chunk frames 峰值**

`tests/test_order_analysis.py` 追加：

```python
def test_order_compute_memory_within_chunk_budget():
    """高 nfft 下 chunk frames 峰值应受 _ORDER_BATCH_FRAMES 限制，不随 N_total_frames 线性增长。"""
    import tracemalloc
    from mf4_analyzer.signal.order import (
        OrderAnalyzer, OrderAnalysisParams, _ORDER_BATCH_FRAMES,
    )
    fs = 4096.0
    nfft = 4096
    # 1500 frames @ nfft=4096：未 chunk 时 frame stack 峰值 ~50 MB；
    # chunk 后峰值应受 (_ORDER_BATCH_FRAMES * nfft * 8B) ≈ 8 MB 控制
    n = nfft + (nfft // 4) * 1500
    rpm = np.linspace(600.0, 3000.0, n)
    sig = np.random.default_rng(0).standard_normal(n).astype(np.float32).astype(float)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    tracemalloc.start()
    OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # chunk_frames 上界 ~8 MB；加上 spectra/输出 matrix/numpy overhead 留 4× headroom
    chunk_budget_mb = (_ORDER_BATCH_FRAMES * nfft * 8) / (1024 * 1024)
    assert peak < chunk_budget_mb * 4 * 1024 * 1024, (
        f"peak {peak / 1024 / 1024:.1f} MB > 4× chunk budget {chunk_budget_mb:.1f} MB"
    )
```

- [ ] **Step 20: 跑测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py::test_order_compute_memory_within_chunk_budget -v
```

预期：PASS。如果 FAIL，说明实现没有按 `_ORDER_BATCH_FRAMES` chunk 真正分块（可能写成了一次性 stack）；回到 Step 12 检查。

- [ ] **Step 21: Commit / 修改清单**

```bash
# 如果在 git 下
git add mf4_analyzer/signal/order.py tests/test_order_analysis.py
git commit -m "fix(order): per-frame counts + vectorize chunked + nyquist mask"
```

修改清单：

- `mf4_analyzer/signal/order.py`：新增 `_ORDER_BATCH_FRAMES = 256` 模块常量；新增 `_order_amplitudes_batch` 静态方法；保留 `_order_amplitudes` 作 baseline；重写 `compute_time_order_result` / `compute_rpm_order_result` / `extract_order_track_result` 走 chunked + window hoist；`compute_rpm_order_result` 内 `counts += 1` + `safe_counts = np.maximum(counts, 1)` + broadcast argmin；三个 result 的 `metadata` 都加 `nyquist_clipped` 字段。
- `tests/test_order_analysis.py`：新增 7 个测试（counts、broadcast argmin 边界等价、target order 幅值恢复、vectorize-vs-loop 全帧三类型、Nyquist metadata、memory budget；不含 cancel / progress 在 T3）。

---

## Task 2 — batch.py 工程层修正

**Owner:** signal-processing-expert
**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: 写失败测试 — `'自动'` nfft 兜底**

在 `tests/test_batch_runner.py` 追加：

```python
def test_current_single_fft_preset_handles_auto_nfft(tmp_path):
    """preset 中 nfft='自动' 应被当作 None 处理（与 inspector 控件一致）。"""
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="auto nfft",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": "自动"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].data_path is not None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_current_single_fft_preset_handles_auto_nfft -v
```

预期：FAIL（`int('自动')` ValueError）。

- [ ] **Step 3: 在 `_compute_fft_dataframe` 加兜底**

```python
    @staticmethod
    def _compute_fft_dataframe(sig, fs, params):
        nfft_raw = params.get('nfft')
        if isinstance(nfft_raw, str):
            nfft = None if nfft_raw.strip() in ('', '自动', 'auto') else int(nfft_raw)
        elif nfft_raw is None or nfft_raw <= 0:
            nfft = None
        else:
            nfft = int(nfft_raw)
        freq, amp = FFTAnalyzer.compute_fft(
            sig,
            fs,
            win=params.get('window', params.get('win', 'hanning')),
            nfft=nfft,
        )
        return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})
```

- [ ] **Step 4: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_current_single_fft_preset_handles_auto_nfft -v
```

预期：PASS。

- [ ] **Step 5: 写测试 — 长表 vectorize 形状**

```python
def test_matrix_to_long_dataframe_vectorize_shape(tmp_path):
    from mf4_analyzer.batch import _matrix_to_long_dataframe
    x = np.arange(5, dtype=float)
    y = np.arange(3, dtype=float) * 0.1
    matrix = np.arange(15, dtype=float).reshape(5, 3)
    df = _matrix_to_long_dataframe(x, y, matrix, x_name='time', y_name='order')
    assert len(df) == 15
    assert list(df.columns) == ['time', 'order', 'amplitude']
    # 前三行：x=0, y∈{0, 0.1, 0.2}
    assert df.iloc[0]['time'] == 0.0
    assert df.iloc[2]['amplitude'] == 2.0
    # 第 4 行：x=1, y=0
    assert df.iloc[3]['time'] == 1.0
    assert df.iloc[3]['amplitude'] == 3.0
```

- [ ] **Step 6: vectorize `_matrix_to_long_dataframe`**

```python
def _matrix_to_long_dataframe(x_values, y_values, matrix, x_name, y_name):
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (len(x_values), len(y_values)):
        raise ValueError(
            f"matrix shape {matrix.shape} does not match "
            f"({len(x_values)}, {len(y_values)})"
        )
    xs = np.repeat(x_values, len(y_values))
    ys = np.tile(y_values, len(x_values))
    return pd.DataFrame({x_name: xs, y_name: ys, 'amplitude': matrix.reshape(-1)})
```

- [ ] **Step 7: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py -v
```

预期：全部 PASS。

- [ ] **Step 8: Figure 释放 + frozen 移除**

`AnalysisPreset` 改为 `@dataclass(frozen=False)`（删掉 `frozen=True`）；保留所有字段和 default。

`BatchRunner._write_image` 末尾改为 try/finally 释放：

```python
    @staticmethod
    def _write_image(payload, path):
        kind, df = payload
        from matplotlib.figure import Figure
        fig = Figure(figsize=(8, 4.5), dpi=140)
        try:
            ax = fig.subplots()
            if kind == 'fft':
                ax.plot(df['frequency_hz'], df['amplitude'], lw=1.0)
                ax.set_xlabel('Frequency (Hz)')
                ax.set_ylabel('Amplitude')
            elif kind == 'order_track':
                ax.plot(df['rpm'], df['amplitude'], lw=1.0)
                ax.set_xlabel('RPM')
                ax.set_ylabel('Amplitude')
            else:
                pivot = df.pivot(index=df.columns[1], columns=df.columns[0], values='amplitude')
                im = ax.imshow(
                    pivot.to_numpy(),
                    aspect='auto',
                    origin='lower',
                    extent=[
                        float(pivot.columns.min()),
                        float(pivot.columns.max()),
                        float(pivot.index.min()),
                        float(pivot.index.max()),
                    ],
                    interpolation='bilinear',
                    cmap='turbo',
                )
                ax.set_xlabel(df.columns[0])
                ax.set_ylabel(df.columns[1])
                fig.colorbar(im, ax=ax, label='Amplitude')
            ax.grid(True, alpha=0.25, ls='--')
            fig.tight_layout()
            fig.savefig(path)
        finally:
            fig.clear()
        return path
```

注意 `imshow` 替代了 batch image 路径里的 `imshow(extent=...)`，cmap 改 'turbo' 与 spec 一致。

- [ ] **Step 9: 跑全套 batch 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py -v
```

预期：全部 PASS。

- [ ] **Step 10: 写测试 — frozen 移除后 dataclasses.replace 仍工作**

```python
def test_analysis_preset_replace_after_frozen_removed(tmp_path):
    """`AnalysisPreset` 去 frozen 后，`dataclasses.replace` 必须继续工作
    （`BatchSheet.get_preset` 依赖此行为）。"""
    from dataclasses import replace
    fd = _make_file(tmp_path)
    p = AnalysisPreset.from_current_single(
        name="orig", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    p2 = replace(p, outputs=BatchOutput(export_data=False, export_image=True))
    assert p2.outputs.export_image is True
    assert p2.outputs.export_data is False
    assert p2.name == "orig"
    assert p.outputs.export_data is True   # 原 preset 不被修改
```

- [ ] **Step 11: 给 `_matches` 加 docstring 说明 substring + regex 双模式**

`mf4_analyzer/batch.py` `BatchRunner._matches`（约 152-163 行）：

```python
    @staticmethod
    def _matches(channel, pattern):
        """通道名匹配规则：

        - 空 pattern → 匹配所有通道
        - pattern 大小写不敏感地包含在 channel 中（substring） → 匹配
        - 否则按 pattern 当正则解析（IGNORECASE，re.search 半匹配） → 匹配

        **注意：** substring 优先级高于 regex。所以包含正则元字符
        （如 ``motor.speed``）的字面量信号名会先按 substring 匹配；
        若 substring 未命中，``.`` 才被解释为"任意字符"，可能产生
        意料之外的命中（如匹配到 ``motorXspeed``）。需要严格字面量
        匹配的调用方应自行做 `re.escape(pattern)`。
        """
        if not pattern:
            return True
        ...
```

实现保持不变，仅加 docstring。

- [ ] **Step 12: 跑全套 batch 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py -v
```

预期：全部 PASS。

- [ ] **Step 13: 修改清单**

- `mf4_analyzer/batch.py`：`_compute_fft_dataframe` 加兜底；`_matrix_to_long_dataframe` vectorize；`_write_image` try/finally + cmap='turbo' + interp='bilinear'；`AnalysisPreset` 去掉 `frozen=True`；`_matches` 加 docstring。
- `tests/test_batch_runner.py`：新增 3 个测试（auto nfft 兜底、长表 vectorize 形状、`replace` 兼容性）。

---

## Task 3 — order/batch 测试覆盖补全

**Owner:** signal-processing-expert
**Files:**
- Modify: `tests/test_order_analysis.py`
- Modify: `tests/test_batch_runner.py`

- [ ] **Step 1: 写测试 — cancel_token 路径**

```python
def test_compute_time_order_result_respects_cancel_token():
    fs = 1024.0
    nfft = 256
    n = nfft * 100
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.01)

    state = {'count': 0}
    def cancel_after_first_batch():
        state['count'] += 1
        return state['count'] >= 2

    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        OrderAnalyzer.compute_time_order_result(
            sig, rpm, t, params, cancel_token=cancel_after_first_batch
        )
```

- [ ] **Step 2: 写测试 — progress_callback**

```python
def test_compute_time_order_result_calls_progress():
    fs = 1024.0
    nfft = 256
    n = nfft * 50
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    calls = []
    def cb(cur, tot):
        calls.append((cur, tot))

    OrderAnalyzer.compute_time_order_result(sig, rpm, t, params, progress_callback=cb)
    assert len(calls) >= 1
    assert calls[-1][0] == calls[-1][1]   # 末尾 cur == total
```

- [ ] **Step 3: 写测试 — batch order_time/order_rpm 形状**

```python
def test_batch_order_time_csv_shape(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="order time batch",
        method="order_time",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "nfft": 512, "max_order": 5.0,
                "order_res": 0.5, "time_res": 0.05},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["time_s", "order", "amplitude"]
    assert len(df) > 0


def test_batch_order_rpm_csv_shape(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="order rpm batch",
        method="order_rpm",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "nfft": 512, "max_order": 5.0,
                "order_res": 0.5, "rpm_res": 100.0},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["rpm", "order", "amplitude"]
```

- [ ] **Step 4: 跑全套 signal/batch 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_order_analysis.py tests/test_batch_runner.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 修改清单**

- `tests/test_order_analysis.py`：新增 cancel_token / progress_callback 两个测试。
- `tests/test_batch_runner.py`：新增 order_time / order_rpm csv 形状两个测试。

---

## Task 4 — canvases.py 抽出 envelope helper + PlotCanvas heatmap 升级

**Owner:** pyqt-ui-engineer
**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`
- Create: `tests/ui/test_canvases_envelope.py`

- [ ] **Step 1: 写失败测试 — module-level `build_envelope` 存在且行为与 TimeDomainCanvas 一致**

`tests/ui/test_canvases_envelope.py`:

```python
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from mf4_analyzer.ui import canvases as cv


def test_build_envelope_is_module_level():
    assert hasattr(cv, 'build_envelope'), "build_envelope must be module-level"


def test_build_envelope_matches_timedomain_envelope_behaviour(qtbot):
    canvas = cv.TimeDomainCanvas()
    qtbot.addWidget(canvas)
    n = 100_000
    t = np.linspace(0.0, 10.0, n)
    sig = np.sin(2 * np.pi * 1.0 * t) + 0.1 * np.random.default_rng(0).standard_normal(n)
    xs1, ys1 = canvas._envelope(t, sig, xlim=(2.0, 8.0), pixel_width=800)
    xs2, ys2 = cv.build_envelope(t, sig, xlim=(2.0, 8.0), pixel_width=800)
    np.testing.assert_array_equal(xs1, xs2)
    np.testing.assert_array_equal(ys1, ys2)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_canvases_envelope.py -v
```

预期：FAIL（`build_envelope` 不存在）。

- [ ] **Step 3: 把 `TimeDomainCanvas._envelope` 抽成 module-level**

在 `canvases.py` `TimeDomainCanvas` 类定义之前新增：

```python
def build_envelope(t, sig, *, xlim, pixel_width, is_monotonic=None):
    """Pure 函数版本的 viewport-aware envelope 下采样。
    与 TimeDomainCanvas._envelope 行为完全一致。
    """
    # ↓ 把 TimeDomainCanvas._envelope 当前实现整体复制过来（替换 self.* 为参数）
    ...
```

`TimeDomainCanvas._envelope` 改为 thin wrapper：

```python
    def _envelope(self, t, sig, xlim, pixel_width, *, is_monotonic=None):
        return build_envelope(t, sig, xlim=xlim, pixel_width=pixel_width,
                               is_monotonic=is_monotonic)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_canvases_envelope.py -v
```

预期：PASS。

- [ ] **Step 5: 跑现有 time-domain 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/ -v
```

预期：所有现有 UI 测试 PASS（确认 envelope 抽出未破坏 TimeDomainCanvas）。

- [ ] **Step 6: 写测试 — `PlotCanvas.plot_or_update_heatmap` 复用 + shape 变化 + track→heatmap 切换**

```python
def test_plot_canvas_heatmap_reuses_artists_on_compatible_call(qtbot):
    """同 shape 二次调用必须复用 _heatmap_ax / _heatmap_im / _heatmap_cbar，
    不只看 fig.axes[0] 的 id（colorbar 会插轴影响顺序）。"""
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    matrix1 = np.random.default_rng(0).random((20, 30))
    canvas.plot_or_update_heatmap(
        matrix=matrix1, x_extent=(0, 10), y_extent=(0, 5),
        x_label='Time', y_label='Order', title='t1',
    )
    ax_obj_1 = canvas._heatmap_ax
    im_obj_1 = canvas._heatmap_im
    cbar_ax_1 = canvas._heatmap_cbar.ax
    n_axes_1 = len(canvas.fig.axes)

    matrix2 = np.random.default_rng(1).random((20, 30))   # 同 shape
    canvas.plot_or_update_heatmap(
        matrix=matrix2, x_extent=(0, 10), y_extent=(0, 5),
        x_label='Time', y_label='Order', title='t2',
    )
    assert canvas._heatmap_ax is ax_obj_1, "heatmap axes object must be reused"
    assert canvas._heatmap_im is im_obj_1, "imshow artist must be reused"
    assert canvas._heatmap_cbar.ax is cbar_ax_1, "colorbar axes must be reused"
    assert len(canvas.fig.axes) == n_axes_1, "axes count should not grow"


def test_plot_canvas_heatmap_rebuilds_on_shape_change(qtbot):
    """matrix shape 变化时必须 fall back 到 clear+rebuild，不能 crash 也不能用 set_data。"""
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(
        matrix=np.zeros((20, 30)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='small',
    )
    im_obj_1 = canvas._heatmap_im
    canvas.plot_or_update_heatmap(
        matrix=np.zeros((50, 80)),                       # 不同 shape
        x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='big',
    )
    assert canvas._heatmap_im is not im_obj_1, "shape change must rebuild imshow artist"
    assert canvas._heatmap_im.get_array().shape == (50, 80)


def test_plot_canvas_heatmap_to_track_to_heatmap_no_colorbar_ghost(qtbot):
    """heatmap → 用户切到 order_track（非 heatmap 路径，调 clear() + 2 subplots）
    → 再回 heatmap：不应留 colorbar 残影。"""
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(
        matrix=np.ones((10, 15)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='heatmap',
    )
    assert len(canvas.fig.axes) == 2   # heatmap + colorbar

    # 模拟 track 渲染：clear + 2 subplots（与 do_order_track 行为一致）
    canvas.clear()
    canvas.fig.add_subplot(2, 1, 1).plot([1, 2, 3])
    canvas.fig.add_subplot(2, 1, 2).plot([3, 2, 1])
    assert canvas._heatmap_ax is None
    assert canvas._heatmap_im is None
    assert canvas._heatmap_cbar is None

    # 再回 heatmap
    canvas.plot_or_update_heatmap(
        matrix=np.ones((10, 15)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='heatmap2',
    )
    assert len(canvas.fig.axes) == 2   # heatmap + colorbar，不应该是 3+
    assert canvas._heatmap_cbar is not None
```

- [ ] **Step 7: 实现 `plot_or_update_heatmap`**

在 `PlotCanvas` 中新增。**兼容判定必须满足全部 4 条**（spec §6.2）才走 `set_data` 路径，否则 clear+rebuild：

```python
    def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                                x_label, y_label, title,
                                cmap='turbo', interp='bilinear',
                                vmin=None, vmax=None,
                                cbar_label='Amplitude'):
        """绘制 2D 谱；同结构二次调用走 set_data 复用 axes/colorbar/imshow。

        约定：matrix 形状为 (N_y, N_x)，与 imshow 一致。
        x/y_extent 是 (min, max)。

        非均匀网格警告：本方法假设 X 和 Y 轴都是均匀网格（imshow 的硬约束）。
        如果未来引入对数 RPM bin 等非均匀场景，必须回退到 pcolormesh 分支
        或独立 canvas，不应直接调本方法。
        """
        m = np.asarray(matrix, dtype=float)
        if vmin is None:
            vmin = float(np.nanmin(m))
        if vmax is None:
            vmax = float(np.nanmax(m))

        existing_ax = getattr(self, '_heatmap_ax', None)
        existing_im = getattr(self, '_heatmap_im', None)
        existing_cbar = getattr(self, '_heatmap_cbar', None)
        # 4 条都成立才复用：
        #   1. 三个 handle 都存在
        #   2. heatmap axes 仍在 figure 中
        #   3. figure 只含 heatmap + colorbar 共 2 个 axes
        #   4. 旧 imshow 的数据 shape 与新 matrix 一致（set_data 才能安全调）
        compatible = (
            existing_ax is not None
            and existing_im is not None
            and existing_cbar is not None
            and existing_ax in self.fig.axes
            and len(self.fig.axes) == 2
            and existing_im.get_array().shape == m.shape
        )
        if compatible:
            existing_im.set_data(m)
            existing_im.set_extent([x_extent[0], x_extent[1],
                                    y_extent[0], y_extent[1]])
            existing_im.set_cmap(cmap)
            existing_im.set_interpolation(interp)
            existing_im.set_clim(vmin, vmax)
            existing_ax.set_xlim(x_extent)
            existing_ax.set_ylim(y_extent)
            existing_ax.set_xlabel(x_label)
            existing_ax.set_ylabel(y_label)
            existing_ax.set_title(title)
            if existing_cbar is not None:
                existing_cbar.update_normal(existing_im)
                existing_cbar.set_label(cbar_label)
            self.draw_idle()
            return

        self.clear()
        ax = self.fig.add_subplot(1, 1, 1)
        im = ax.imshow(
            m, origin='lower', aspect='auto',
            extent=[x_extent[0], x_extent[1], y_extent[0], y_extent[1]],
            cmap=cmap, interpolation=interp,
            vmin=vmin, vmax=vmax,
        )
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        cbar = self.fig.colorbar(im, ax=ax, label=cbar_label)
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self._heatmap_ax = ax
        self._heatmap_im = im
        self._heatmap_cbar = cbar
        self.draw_idle()
```

注意 `clear()` 末尾要把 `_heatmap_*` 属性置 None：

```python
    def clear(self):
        self._remarks = []
        self._line_data = {}
        self._heatmap_ax = None
        self._heatmap_im = None
        self._heatmap_cbar = None
        self.fig.clear()
        self.fig.set_facecolor(CHART_FACE)
```

- [ ] **Step 8: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_canvases_envelope.py -v
```

预期：PASS。

- [ ] **Step 9: 跑现有 UI 测试确认无回归**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/ -v
```

预期：全部 PASS。

- [ ] **Step 10: 修改清单**

- `mf4_analyzer/ui/canvases.py`：新增 module-level `build_envelope`；`TimeDomainCanvas._envelope` 改 thin wrapper；`PlotCanvas.clear` 重置 `_heatmap_*`；`PlotCanvas.plot_or_update_heatmap` 新增。
- `tests/ui/test_canvases_envelope.py`：新建（3 个测试）。

---

## Task 5 — main_window.py 引入 OrderWorker、order_track envelope、do_order_* 重构

**Owner:** pyqt-ui-engineer
**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Create: `tests/ui/test_order_worker.py`

- [ ] **Step 1: 写失败测试 — `OrderWorker` 类存在且 emit `result_ready`**

`tests/ui/test_order_worker.py`:

```python
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PyQt5.QtCore import QEventLoop, QTimer

from mf4_analyzer.signal.order import OrderAnalysisParams


def test_order_worker_emits_result_with_generation(qtbot):
    """OrderWorker 应在完成时 emit (result, kind, generation)。"""
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 512
    n = nfft * 4
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2 * np.pi * 50.0 * t)
    rpm = np.full(n, 1500.0)
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    GEN = 42
    worker = OrderWorker('time', sig, rpm, t, params, generation=GEN)
    results = []
    failures = []
    worker.result_ready.connect(
        lambda r, kind, gen: results.append((r, kind, gen))
    )
    worker.failed.connect(lambda msg, gen: failures.append((msg, gen)))

    worker.start()
    qtbot.waitUntil(lambda: bool(results) or bool(failures), timeout=5000)
    worker.wait(2000)

    assert not failures, f"unexpected failure: {failures}"
    assert len(results) == 1
    r, kind, gen = results[0]
    assert gen == GEN
    assert kind == 'time'
    assert hasattr(r, 'amplitude')


def test_order_worker_cancel_before_run_yields_no_result(qtbot):
    """先 cancel 再 start：worker 必须不发任何 result_ready，且 wait 内停。

    用 cancel 在 start 之前调，避免主线程 wait 阻塞导致 QTimer 无法 fire 的不确定性。
    （codex review D14：QTimer.singleShot(50, cancel) 后立即 wait 会吞 timer。）
    """
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 256
    n = nfft * 600   # 帧数足够多，让任何一帧走到也能在 chunk 边界 cancel
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    worker = OrderWorker('time', sig, rpm, t, params, generation=1)
    results = []
    failures = []
    worker.result_ready.connect(lambda *a: results.append(a))
    worker.failed.connect(lambda *a: failures.append(a))

    # 关键：cancel 设在 start 之前（worker.run 的第一个 cancel check 就会触发）
    worker.cancel()
    worker.start()
    assert worker.wait(5000), "worker did not finish within 5 s"
    assert not worker.isRunning()
    # 已 cancel，不应有任何 result/failure
    assert results == [], f"unexpected result after pre-cancel: {results}"
    assert failures == [], f"unexpected failure after pre-cancel: {failures}"


def test_order_worker_mid_run_cancel_via_event_loop(qtbot):
    """模拟 dispatcher 真实场景：worker 跑起来后通过 qtbot.waitSignal + cancel 截停。

    用 qtbot.waitUntil 驱动事件循环，避免 wait() 阻塞主循环。
    """
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 256
    n = nfft * 600
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    worker = OrderWorker('time', sig, rpm, t, params, generation=2)
    progress_seen = []
    worker.progress.connect(lambda c, tt, g: progress_seen.append(c))

    worker.start()
    # 等收到至少 1 次 progress（说明 worker 已进入循环）
    qtbot.waitUntil(lambda: len(progress_seen) > 0, timeout=3000)
    worker.cancel()
    # 用 wait 等 worker 自然退出（cancel 会让 _check_cancel 抛异常）
    assert worker.wait(5000), "worker did not honor cancel within 5 s"


def test_order_worker_stale_generation_is_ignored(qtbot):
    """生产场景：MainWindow generation token 必须能让 stale worker 的 result 被丢弃。
    本测试只验证信号签名带 generation；MainWindow 端的丢弃在 T6 测试。"""
    from mf4_analyzer.ui.main_window import OrderWorker
    import inspect
    # 反射验证三个信号都带 generation 参数
    sig = OrderWorker.result_ready
    failed_sig = OrderWorker.failed
    progress_sig = OrderWorker.progress
    # PyQt5 signal 没有公开签名，最起码确认 emit 时传 3 个参数不报错（间接验证）
    fs = 1024.0
    nfft = 256
    n = nfft * 4
    sig_data = np.zeros(n)
    rpm_data = np.full(n, 1500.0)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)
    w = OrderWorker('time', sig_data, rpm_data, t, params, generation=99)
    received = []
    w.result_ready.connect(lambda r, k, g: received.append((k, g)))
    w.start()
    qtbot.waitUntil(lambda: bool(received), timeout=5000)
    w.wait(2000)
    assert received[0] == ('time', 99)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_worker.py -v
```

预期：FAIL（`OrderWorker` 不存在）。

- [ ] **Step 3: 实现 `OrderWorker`（带 generation token）**

在 `mf4_analyzer/ui/main_window.py` 中 `SpectrogramWorker` 之后追加（spec §4.3 完整实现）：

```python
class OrderWorker(QThread):
    """Run OrderAnalyzer.compute_* on a worker QThread.

    三个信号都带 generation：MainWindow 用 generation token 模式判定是否
    采纳本次结果，独立于 cancel 是否成功——见 spec §4.3。
    """
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
                return
            self.result_ready.emit(r, self._kind, gen)
        except RuntimeError as e:
            if 'cancel' in str(e).lower():
                return
            self.failed.emit(str(e), gen)
        except Exception as e:
            self.failed.emit(str(e), gen)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_worker.py -v
```

预期：PASS。

- [ ] **Step 5: 重构 `do_order_time` 走 worker + plot_or_update_heatmap**

替换 `MainWindow.do_order_time`：

```python
    def do_order_time(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100:
            self.toast("请选择有效信号", "warning")
            return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t, sig = t[m], sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None:
            return
        fs = self.inspector.order_ctx.fs()
        op = self.inspector.order_ctx.get_params()
        from ..signal.order import OrderAnalysisParams
        params = OrderAnalysisParams(
            fs=fs,
            nfft=int(op['nfft']),
            window=op.get('window', 'hanning'),
            max_order=float(op['max_order']),
            order_res=float(op['order_res']),
            time_res=float(op['time_res']),
        )
        self._dispatch_order_worker('time', sig, rpm, t, params,
                                     status_msg='计算时间-阶次谱...')

    def _dispatch_order_worker(self, kind, sig, rpm, t, params, *, status_msg):
        # 1. generation token 单调递增；旧 worker 的 stale 信号会被丢
        self._order_generation = getattr(self, '_order_generation', 0) + 1
        gen = self._order_generation

        # 2. 取消并断开旧 worker（如还在跑）
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
                # wait 超时 → 强制 terminate；500ms 后认为已退出
                old.terminate()
                old.wait(500)

        # 3. 创建新 worker，挂接信号
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
            return                # stale；丢弃
        if total > 0:
            self.inspector.order_ctx.set_progress(f"{int(current/total*100)}%")

    def _on_order_failed(self, msg, generation):
        if generation != getattr(self, '_order_generation', -1):
            return                # stale；丢弃
        self.inspector.order_ctx.set_progress("")
        self.inspector.order_ctx.btn_cancel.setEnabled(False)
        QMessageBox.critical(self, "错误", msg)

    def _on_order_result(self, result, kind, generation):
        if generation != getattr(self, '_order_generation', -1):
            return                # stale；丢弃
        self.inspector.order_ctx.set_progress("")
        self.inspector.order_ctx.btn_cancel.setEnabled(False)
        if kind == 'time':
            self._render_order_time(result)
        elif kind == 'rpm':
            self._render_order_rpm(result)
        elif kind == 'track':
            self._render_order_track(result)

    def closeEvent(self, event):
        """窗口关闭：取消所有 worker，避免 parented QThread running 时被销毁。"""
        for attr in ('_order_worker', '_spectrogram_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                try:
                    worker.result_ready.disconnect()
                    worker.failed.disconnect()
                    worker.progress.disconnect()
                except (TypeError, AttributeError):
                    pass
                if hasattr(worker, 'cancel'):
                    worker.cancel()
                if not worker.wait(2000):
                    worker.terminate()
                    worker.wait(500)
        super().closeEvent(event)
```

> **注意：** `closeEvent` 中处理的 `_spectrogram_worker` 名称必须与 `do_fft_time` 实际持有的 worker 属性名一致。executor 在落地前应 grep `main_window.py` 中 spectrogram worker 的实际属性名（可能是 `self._spec_worker` 或 `self._fft_time_worker`），按真实名称替换。

`_render_order_time` 走新 heatmap API：

```python
    def _render_order_time(self, result):
        title = f"时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} (分辨率:{result.params.order_res})"
        self.canvas_order.plot_or_update_heatmap(
            matrix=result.amplitude.T,                        # (N_orders, N_times)
            x_extent=(float(result.times[0]), float(result.times[-1])),
            y_extent=(float(result.orders[0]), float(result.orders[-1])),
            x_label='Time (s)',
            y_label='Order',
            title=title,
            cmap='turbo',
            interp='bilinear',
            cbar_label='Amplitude',
        )
        xt, yt = self.inspector.top.tick_density()
        self.canvas_order.set_tick_density(xt, yt)
        self._remember_batch_preset(
            "当前时间-阶次", "order_time",
            self.inspector.order_ctx.current_signal(),
            {
                'fs': result.params.fs,
                'nfft': result.params.nfft,
                'max_order': result.params.max_order,
                'order_res': result.params.order_res,
                'time_res': result.params.time_res,
                'rpm_factor': self.inspector.order_ctx.rpm_factor(),
            },
            rpm_signal=self.inspector.order_ctx.current_rpm(),
        )
        self.statusBar.showMessage(
            f'完成 | {len(result.times)} 时间点 × {len(result.orders)} 阶次'
        )
        self.toast(f"时间-阶次谱完成 · {len(result.times)} × {len(result.orders)}", "success")
```

- [ ] **Step 6: 同样改造 `do_order_rpm` / `_render_order_rpm`**

```python
    def do_order_rpm(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100:
            self.toast("请选择有效信号", "warning")
            return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None:
            return
        fs = self.inspector.order_ctx.fs()
        op = self.inspector.order_ctx.get_params()
        from ..signal.order import OrderAnalysisParams
        params = OrderAnalysisParams(
            fs=fs,
            nfft=int(op['nfft']),
            window=op.get('window', 'hanning'),
            max_order=float(op['max_order']),
            order_res=float(op['order_res']),
            rpm_res=float(op['rpm_res']),
        )
        self._dispatch_order_worker('rpm', sig, rpm, None, params,
                                     status_msg='计算转速-阶次谱...')

    def _render_order_rpm(self, result):
        title = (f"转速-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} "
                  f"(阶次分辨率:{result.params.order_res}, RPM分辨率:{result.params.rpm_res})")
        # ⚠️ B6 修正：原 pcolormesh(ords, rb, om) 是 x=order, y=rpm，
        # om.shape = (N_rpm_bins, N_orders)。imshow 期望 matrix.shape = (rows, cols) = (Y, X)，
        # 即 (N_rpm_bins, N_orders)。所以 matrix 直接传 result.amplitude（不转置），
        # x_extent 配 orders，y_extent 配 rpm_bins。
        # 严禁 .T + 同时交换 extent —— 那是 codex round-1 review 拦下的双反转 bug。
        self.canvas_order.plot_or_update_heatmap(
            matrix=result.amplitude,                          # (N_rpm_bins, N_orders)
            x_extent=(float(result.orders[0]), float(result.orders[-1])),
            y_extent=(float(result.rpm_bins[0]), float(result.rpm_bins[-1])),
            x_label='Order',
            y_label='RPM',
            title=title,
            cmap='turbo',
            interp='bilinear',
            cbar_label='Amplitude',
        )
        xt, yt = self.inspector.top.tick_density()
        self.canvas_order.set_tick_density(xt, yt)
        self._remember_batch_preset(
            "当前转速-阶次", "order_rpm",
            self.inspector.order_ctx.current_signal(),
            {
                'fs': result.params.fs,
                'nfft': result.params.nfft,
                'max_order': result.params.max_order,
                'order_res': result.params.order_res,
                'rpm_res': result.params.rpm_res,
                'rpm_factor': self.inspector.order_ctx.rpm_factor(),
            },
            rpm_signal=self.inspector.order_ctx.current_rpm(),
        )
        self.statusBar.showMessage(
            f'转速-阶次谱完成 | {len(result.rpm_bins)} RPM × {len(result.orders)} 阶次'
        )
        self.toast(
            f"转速-阶次谱完成 · {len(result.rpm_bins)} × {len(result.orders)}",
            "success",
        )
```

注意：order_rpm 的矩阵形状 `result.amplitude` 是 `(N_rpm_bins, N_orders)`（详见 `signal/order.py:206`），所以 `.T` 后是 `(N_orders, N_rpm_bins)`，正好对应 imshow 的 (Y_orders, X_rpm_bins)。x_extent=order, y_extent=rpm。

- [ ] **Step 7: 改造 `do_order_track` 走 worker + envelope**

```python
    def do_order_track(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100:
            self.toast("请选择有效信号", "warning")
            return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None:
            return
        fs = self.inspector.order_ctx.fs()
        to = self.inspector.order_ctx.target_order()
        op = self.inspector.order_ctx.get_params()
        from ..signal.order import OrderAnalysisParams
        params = OrderAnalysisParams(
            fs=fs,
            nfft=int(op['nfft']),
            target_order=float(to),
        )
        self._dispatch_order_worker('track', sig, rpm, None, params,
                                     status_msg=f'跟踪阶次 {to}...')
        # 把 rpm 缓存起来供 _render_order_track 用
        self._order_track_pending_rpm = rpm

    def _render_order_track(self, result):
        from .canvases import build_envelope
        # track 视图是 2-subplot 结构，不与 heatmap 兼容；强制重建
        self.canvas_order.clear()
        ax1 = self.canvas_order.fig.add_subplot(2, 1, 1)
        ax1.plot(result.rpm, result.amplitude, '#1f77b4', lw=1)
        ax1.set_xlabel('RPM')
        ax1.set_ylabel('Amplitude', labelpad=10)
        ax1.set_title(
            f'阶次 {result.params.target_order} 跟踪 - '
            f'{self.inspector.order_ctx.combo_sig.currentText()}'
        )
        ax1.grid(True, alpha=0.25, ls='--')

        ax2 = self.canvas_order.fig.add_subplot(2, 1, 2)
        rpm = getattr(self, '_order_track_pending_rpm', None)
        if rpm is None:
            rpm = result.rpm
        # envelope 下采样：x 是样本索引
        xs_idx = np.arange(len(rpm), dtype=float)
        pixel_width = max(self.canvas_order.width(), 600)
        xs, ys = build_envelope(xs_idx, rpm, xlim=None,
                                 pixel_width=pixel_width, is_monotonic=True)
        ax2.plot(xs, ys, '#2ca02c', lw=0.8)
        ax2.set_xlabel('Sample')
        ax2.set_ylabel('RPM')
        ax2.set_title('转速曲线')
        ax2.grid(True, alpha=0.25, ls='--')

        try:
            self.canvas_order.fig.tight_layout()
        except Exception:
            pass
        xt, yt = self.inspector.top.tick_density()
        self.canvas_order.set_tick_density(xt, yt)
        self.canvas_order.draw_idle()

        # 注意：track 走非 heatmap 路径，下次切到 heatmap 会自动重建
        self.canvas_order._heatmap_ax = None
        self.canvas_order._heatmap_im = None
        self.canvas_order._heatmap_cbar = None

        self._remember_batch_preset(
            "当前阶次跟踪", "order_track",
            self.inspector.order_ctx.current_signal(),
            {
                'fs': result.params.fs,
                'nfft': result.params.nfft,
                'target_order': result.params.target_order,
                'rpm_factor': self.inspector.order_ctx.rpm_factor(),
            },
            rpm_signal=self.inspector.order_ctx.current_rpm(),
        )
        self.statusBar.showMessage(f'阶次 {result.params.target_order} 跟踪完成')
        self.toast(f"阶次 {result.params.target_order} 跟踪完成", "success")
```

- [ ] **Step 8: 删除旧的 `_order_progress` 方法（已被 worker 信号取代）**

`_order_progress` 不再被调用，可删除。`_on_order_progress` 已在 dispatcher 引入。

落地后 grep 验证无残留：

```bash
grep -n "_order_progress\|QApplication.processEvents" "mf4_analyzer/ui/main_window.py" | grep -v "_on_order_progress"
```

预期：仅可能命中 `do_fft_time` 等其它路径（不是 order）；不应再有 `def _order_progress` 或 order 路径里的 `processEvents()`。

- [ ] **Step 9: 写测试 — `_render_order_rpm` 矩阵方向（B6 断言）**

`tests/ui/test_order_worker.py` 追加：

```python
def test_render_order_rpm_uses_correct_extent_and_matrix_orientation(qtbot, tmp_path):
    """B6 回归：order_rpm 的 imshow 必须 x=order, y=rpm，
    matrix 不转置（与原 pcolormesh(ords, rb, om) 视觉等价）。"""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.signal.order import OrderRpmResult, OrderAnalysisParams
    win = MainWindow()
    qtbot.addWidget(win)
    # 构造一个 result，shape (3 rpm_bins, 5 orders)，每行值递增 → 易看出方向
    result = OrderRpmResult(
        orders=np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        rpm_bins=np.array([600.0, 1200.0, 1800.0]),
        amplitude=np.array([
            [0.1, 0.2, 0.3, 0.4, 0.5],   # rpm=600 行
            [1.1, 1.2, 1.3, 1.4, 1.5],   # rpm=1200 行
            [2.1, 2.2, 2.3, 2.4, 2.5],   # rpm=1800 行
        ]),
        counts=np.zeros((3, 5)),
        params=OrderAnalysisParams(fs=1024.0, nfft=512, max_order=5.0,
                                     order_res=1.0, rpm_res=600.0),
    )
    win._render_order_rpm(result)
    im = win.canvas_order._heatmap_im
    # x 轴 extent = order
    assert im.get_extent()[0] == 1.0 and im.get_extent()[1] == 5.0
    # y 轴 extent = rpm
    assert im.get_extent()[2] == 600.0 and im.get_extent()[3] == 1800.0
    # matrix shape = (N_rpm_bins, N_orders) = (3, 5)
    assert im.get_array().shape == (3, 5)
    # 第一行（rpm=600）应该数值最小（0.1-0.5）
    np.testing.assert_allclose(im.get_array()[0], [0.1, 0.2, 0.3, 0.4, 0.5])
```

- [ ] **Step 10: 写测试 — closeEvent 不崩 + 取消所有 worker**

```python
def test_main_window_close_event_cancels_running_order_worker(qtbot):
    """若 order worker 仍在跑，closeEvent 必须能正常取消并退出，不留 QThread destroyed warning。"""
    import warnings
    from mf4_analyzer.ui.main_window import MainWindow, OrderWorker
    from mf4_analyzer.signal.order import OrderAnalysisParams
    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1024.0
    nfft = 256
    n = nfft * 800
    sig = np.zeros(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    # 直接走 dispatcher 投递长任务
    win._dispatch_order_worker('time', sig, rpm, t, params,
                                status_msg='测试取消')
    qtbot.waitUntil(lambda: win._order_worker.isRunning(), timeout=2000)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        win.close()
        # close 后 worker 应该已不在跑
        assert not win._order_worker.isRunning()
        thread_warnings = [w for w in caught
                            if 'QThread' in str(w.message) or 'destroyed' in str(w.message)]
        assert not thread_warnings, f"unexpected QThread warnings: {thread_warnings}"
```

- [ ] **Step 11: 写测试 — 快速连点 stale generation 被丢弃**

```python
def test_rapid_redispatch_drops_stale_generation(qtbot):
    """连续 dispatch 三次：只有最新 generation 的 result 应到 _on_order_result。"""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.signal.order import OrderAnalysisParams
    win = MainWindow()
    qtbot.addWidget(win)

    rendered_kinds = []
    orig_render_time = win._render_order_time
    win._render_order_time = lambda result: rendered_kinds.append(('time', result))

    fs = 1024.0
    nfft = 256
    n = nfft * 50
    sig = np.zeros(n)
    rpm = np.full(n, 1500.0)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    # 连续 dispatch 三次（dispatcher 自带 cancel + wait + terminate fallback）
    for _ in range(3):
        win._dispatch_order_worker('time', sig, rpm, t, params,
                                    status_msg='rapid')
    final_gen = win._order_generation
    qtbot.waitUntil(lambda: not win._order_worker.isRunning(), timeout=10000)
    qtbot.wait(200)   # 让信号 deliver

    # 至多 1 次（最新 generation）—— stale 的 result 必须被 drop
    assert len(rendered_kinds) <= 1
    assert win._order_generation == final_gen
```

- [ ] **Step 12: 跑新增三个测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_worker.py -v
```

预期：全部 PASS。

- [ ] **Step 13: 跑全套 UI 测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/ -v
```

预期：所有 PASS（确认 closeEvent 没有破坏其它 UI 测试）。

- [ ] **Step 14: 跑全套测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
```

预期：全部 PASS。

- [ ] **Step 15: 修改清单**

- `mf4_analyzer/ui/main_window.py`：新增 `OrderWorker` 类（带 generation token）；新增 `_dispatch_order_worker`（generation 自增 + 旧 worker disconnect + cancel + wait + terminate fallback）/ `_on_order_progress` / `_on_order_failed` / `_on_order_result`（三者都比对 generation）；新增 `_render_order_time` / `_render_order_rpm`（**matrix 不转置 + x=order y=rpm**）/ `_render_order_track`；新增 `closeEvent` 取消所有 worker；重写 `do_order_time` / `do_order_rpm` / `do_order_track`；删除 `_order_progress`。
- `tests/ui/test_order_worker.py`：新建（5 个测试 — pre-cancel、mid-run cancel via event loop、generation 签名、`_render_order_rpm` B6 断言、closeEvent 取消、stale generation 丢弃）。

---

## Task 6 — 取消按钮、失效 preset 降级、手动烟雾验证

**Owner:** pyqt-ui-engineer
**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Create: `tests/ui/test_order_smoke.py`

- [ ] **Step 1: 写失败测试 — `OrderContextual` 暴露 cancel 信号**

`tests/ui/test_order_smoke.py`:

```python
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest


def test_order_contextual_exposes_cancel_signal(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    w = OrderContextual()
    qtbot.addWidget(w)
    assert hasattr(w, 'cancel_requested')


def test_open_batch_drops_stale_preset_signal(qtbot, monkeypatch):
    """如果 _last_batch_preset.signal 引用的 fid 已不在 self.files，
    open_batch 必须把传给 BatchSheet 的 current_preset 设为 None
    并 toast 提示用户（codex round-1 D13/F19）。"""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.batch import AnalysisPreset
    win = MainWindow()
    qtbot.addWidget(win)
    # MainWindow 至少需要 1 个文件，open_batch 才不会被 "请先加载文件" 拦下；
    # 我们 monkeypatch self.files 让 open_batch 能往下走。
    win.files[0] = object()    # fake fd，仅用于绕过 if not self.files

    win._last_batch_preset = AnalysisPreset.from_current_single(
        name="stale", method="fft", signal=(99999, "nope"),
        params={"fs": 1024.0, "nfft": 1024},
    )

    captured = {}

    class FakeSheet:
        def __init__(self, parent, files, current_preset=None):
            captured['current_preset'] = current_preset
            captured['files'] = files
        def exec_(self):
            return 0   # 用户取消，避免后续 BatchRunner.run

    toast_msgs = []
    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.batch_sheet.BatchSheet', FakeSheet,
    )
    monkeypatch.setattr(win, 'toast', lambda msg, kind='info': toast_msgs.append((kind, msg)))

    win.open_batch()

    # current_preset 必须被显式置为 None（而不是把 stale 对象传给 BatchSheet）
    assert captured['current_preset'] is None, (
        f"stale preset must not be forwarded to BatchSheet; "
        f"got {captured.get('current_preset')}"
    )
    # 用户必须收到提示
    assert any('失效' in msg or 'stale' in msg.lower()
               for kind, msg in toast_msgs), (
        f"expected stale-preset toast, got {toast_msgs}"
    )
```

- [ ] **Step 2: 跑测试确认失败**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_smoke.py -v
```

预期：FAIL（`cancel_requested` 不存在）。

- [ ] **Step 3: `OrderContextual` 加 cancel 按钮**

`mf4_analyzer/ui/inspector_sections.py` 中 `OrderContextual` 类（约第 635 行起）：

```python
    cancel_requested = pyqtSignal()
```

在 `__init__` 末尾加：

```python
        self.btn_cancel = QPushButton("取消计算", self)
        self.btn_cancel.setObjectName("orderCancelBtn")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_requested)
        # 加到现有布局末尾（具体 layout 名称按当前实现填）
```

- [ ] **Step 4: `MainWindow` 接 cancel 信号**

```python
        self.inspector.order_ctx.cancel_requested.connect(self._cancel_order_compute)

    def _cancel_order_compute(self):
        if getattr(self, '_order_worker', None) is not None and self._order_worker.isRunning():
            self._order_worker.cancel()
            self.statusBar.showMessage('阶次计算已取消')
            self.inspector.order_ctx.set_progress("")
```

`_dispatch_order_worker` 里 worker 启动时 `self.inspector.order_ctx.btn_cancel.setEnabled(True)`，`_on_order_result` / `_on_order_failed` 里 `setEnabled(False)`。

- [ ] **Step 5: `open_batch` 入口校验 stale preset**

`MainWindow.open_batch` 开头加：

```python
        current_preset = self._last_batch_preset or self._build_current_batch_preset()
        if current_preset is not None and current_preset.source == 'current_single':
            sig = current_preset.signal
            if sig is None or sig[0] not in self.files:
                self.toast("当前单次预设已失效，请改用自由配置", "warning")
                current_preset = None
```

- [ ] **Step 6: 跑测试确认通过**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_smoke.py -v
```

预期：PASS。

- [ ] **Step 7: 跑全套测试**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
```

预期：全部 PASS。

- [ ] **Step 8: 手动烟雾测试 + Gouraud vs Bilinear 视觉对比清单（人工执行）**

写一份手动测试 checklist 到 `docs/superpowers/reports/2026-04-26-order-perf-manual-smoke.md`，包含两组：

```markdown
# Order Perf 手动烟雾测试清单

数据集：`testdoc/` 下任意 ≥ 60 s 的 MF4。

## A. 行为烟雾

- [ ] 切到 order 模式
- [ ] 选信号 + RPM 通道，按「时间-阶次谱」
- [ ] 计算期间窗体不冻结：尝试切到 time / fft 模式 → 应正常切换
- [ ] 计算期间按「取消计算」→ statusBar 显示「阶次计算已取消」
- [ ] 计算完成后，pan/zoom order 谱：视觉无卡顿（30+ fps 主观感受）
- [ ] 切「转速-阶次谱」按钮再算一次：复用 axes，不闪
- [ ] 切「阶次跟踪」按钮：下半幅 RPM 拖动无卡顿
- [ ] 关闭主窗口（计算未结束时）：无 QThread destroyed warning
- [ ] open 批处理 → 把刚才的 order_time 当 preset 跑：导出图视觉与画布一致

## B. Gouraud vs Bilinear 视觉对比（codex round-1 F21）

在切到 imshow 之前，跑一次 order_time，截图保存为 `gouraud-baseline.png`。
切完后，用同样数据集 / 同样参数再跑一次，截图保存为 `bilinear-current.png`。

- [ ] 两张图横向并排放，肉眼对比
- [ ] 色阶位置一致，无明显平移
- [ ] 高峰位置不模糊化（bilinear 不应让窄峰变宽）
- [ ] 低幅区域不出现 banding
- [ ] 用户签字接受（report 末尾追加签字栏）
```

- [ ] **Step 9: 修改清单**

- `mf4_analyzer/ui/inspector_sections.py`：`OrderContextual` 加 `cancel_requested` 信号 + `btn_cancel` 按钮。
- `mf4_analyzer/ui/main_window.py`：连 cancel 信号；`open_batch` 入口加 stale 校验（**必须把 `current_preset` 显式置为 None 后再传给 `BatchSheet`，不只是 `_expand_tasks` 返回 0**）；启动/停止 worker 时切换 `btn_cancel.setEnabled`。
- `tests/ui/test_order_smoke.py`：新建（2 个测试 — `cancel_requested` 信号存在 + `open_batch` 真把 stale preset 置 None 并 toast）。
- `docs/superpowers/reports/2026-04-26-order-perf-manual-smoke.md`：新建（行为烟雾 + Gouraud vs Bilinear 视觉对比 + 用户签字）。

---

## Acceptance Matrix（spec §7 落地映射）

| 验收标准 | 验证方式 | 测试位置 |
|---|---|---|
| 7-1 拖动 ≥ 30 fps（中规模） | 🧪 手动 | `2026-04-26-order-perf-manual-smoke.md` §A |
| 7-2 计算期窗体不冻结 | 🧪 手动 | manual-smoke §A |
| 7-3 order_track 大规模拖动 ≥ 30 fps | 🧪 手动 | manual-smoke §A |
| 7-4 视觉清晰度 ≥ gouraud | 🧪 手动 + 用户签字 | manual-smoke §B |
| 7-5 缓存命中 < 100 ms | ⏸ deferred（依赖 `_order_result_cache`） | — |
| 7-6 既有测试 PASS | ✅ 自动 | `pytest tests -q` |
| 7-7 新增 7 项算法测试 PASS | ✅ 自动 | T1 (counts/argmin 边界/target 幅值/vectorize 全帧/Nyquist metadata/memory budget) + T3 (cancel/progress) |
| 7-8 新增 4 项 UI/worker 测试 PASS | ✅ 自动 | T4 (envelope helper / heatmap reuse + shape change + track-roundtrip) + T5 (worker 5 个) + T6 (smoke 2 个) |
| 7-9 batch 200 文件内存增量 < 200 MB | ✅ 自动 (tracemalloc step) | T1 Step 19-20 |
| 7-10 现有 order 控件行为不变 | 🧪 手动 | manual-smoke §A |
| 7-11 vectorize-vs-loop 数值一致 | ✅ 自动 | T1 Step 15-16 |
| 7-12 RPM-bin 索引 broadcast argmin 边界等价 | ✅ 自动 | T1 Step 5-7 |
| 7-13 order_rpm imshow 轴语义对 | ✅ 自动 + 🧪 手动 | T5 Step 9 (单元测试) + manual-smoke §B |
| 7-14 closeEvent 正常退出无 QThread warning | ✅ 自动 | T5 Step 10 |
| 7-15 stale generation 不渲染 | ✅ 自动 | T5 Step 11 |

## Self-Review Checklist

实施完成后，main Claude 在 aggregate 阶段对照本 plan 自检：

1. **Spec 覆盖**：
   - imshow 切换 ✓ T4 + T5
   - 复用 axes/colorbar/imshow + shape-change rebuild ✓ T4 (`plot_or_update_heatmap` + 4 条兼容判定)
   - OrderWorker + generation token + closeEvent ✓ T5
   - PlotCanvas envelope helper（thin wrapper 模式） ✓ T4
   - order_track envelope ✓ T5
   - counts 语义 + 保留 argmin 向量化 + Nyquist metadata + vectorize + 窗 hoist + chunked + memory profile ✓ T1
   - `'自动'` nfft 兜底 + Figure 释放 + 长表 vectorize + frozen 移除 + `_matches` docstring + `replace` 兼容性测试 ✓ T2
   - 测试覆盖（spec §7 全部 15 条 → acceptance matrix） ✓ T1, T3, T4, T5, T6
   - 取消按钮 + stale preset 真降级（含 BatchSheet monkeypatch） ✓ T6
   - Gouraud vs Bilinear 视觉对比 + 用户签字 ✓ T6 Step 8
   - Deferred 项不在 plan：dB 模式 / 动态范围 / `_order_result_cache` / mip-map ✓

2. **Placeholder 扫描**：grep "TODO|TBD|实现细节|稍后"。本 plan 中所有标"由 specialist 落地"的位置均明确给出 spec 引用 + 行为契约 + 完整代码片段。

3. **类型一致性**：
   - `OrderTimeResult.amplitude` 是 `(N_times, N_orders)`；`_render_order_time` 用 `result.amplitude.T` → `(N_orders, N_times)`，配 x=time / y=order。
   - `OrderRpmResult.amplitude` 是 `(N_rpm_bins, N_orders)`；`_render_order_rpm` **不转置**，直接传 → `(N_rpm_bins, N_orders) = (rows=Y, cols=X)`，配 x=order / y=rpm（B6 修正）。
   - `plot_or_update_heatmap(matrix=...)` 期望 `(N_y, N_x)`，与上两条均一致。
   - `OrderRpmResult.counts` 形状不变 `(N_rpm_bins, N_orders)`，但语义改为帧数；review report §4.1 已加 API compatibility note。
   - `OrderTimeResult.metadata` / `OrderRpmResult.metadata` / `OrderTrackResult.metadata` 都新增 `nyquist_clipped: int` 字段。
   - `OrderWorker` 三个信号都带 `generation: int`；`MainWindow._on_order_*` 三个 slot 都比对 generation。

## Squad Routing Hints

main Claude 在 dispatch 时：

- T1 / T2 / T4 在同一轮并行（不同文件）。
- T3 在 T1+T2 完成后启动。
- T5 在 T1+T4 完成后启动。
- T6 在 T5 完成后启动。

每个 task 完成后，main Claude aggregate 时按 squad runbook 检查 `files_changed` 是否在专家边界内（spec §5）。任何跨边界（例如 signal-processing-expert 改了 `mf4_analyzer/ui/`）必须 flag。

## Execution Handoff

Plan 完成并保存到 `docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md`。

按用户要求，**先送 codex review**，根据 review 反馈修订后再启 squad 执行。

main Claude 应：

1. 把本 plan、对应的 spec 和 report 三份一起发给 codex review。
2. 等 codex review 返回后，根据反馈修订 plan / spec / report。
3. 然后按 squad runbook 进入 Phase 1（plan）→ Phase 2（execute T1-T6）→ Phase 3（aggregate）→ Phase 4（state + 可能的 prune）。
