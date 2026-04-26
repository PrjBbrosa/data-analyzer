# Order Canvas 渲染 / 显示 / 交互 综合诊断报告

**Date:** 2026-04-26
**Author:** main Claude（基于 codex 2026-04-26 order-batch 改动后的源码 review + 性能根因分析）
**Status:** ready for codex review
**Trigger:** 用户报告 order 模式拖动严重卡顿，且自 codex 2026-04-26 改动后希望复盘 order/batch 这一摊代码

## 1. 范围

本报告仅覆盖 **order 分析** 这一条链路，不涉及 time / fft / fft_time。具体范围：

- `mf4_analyzer/signal/order.py`（codex 2026-04-26 重写后的版本）
- `mf4_analyzer/batch.py`（codex 2026-04-26 新增）
- `mf4_analyzer/ui/main_window.py` 中的 `do_order_time` / `do_order_rpm` / `do_order_track` / `_order_progress` / `_get_rpm` / `open_batch` / `_remember_batch_preset` / `_build_current_batch_preset`
- `mf4_analyzer/ui/canvases.py` 中的 `PlotCanvas`（order canvas 实际类型）
- `mf4_analyzer/ui/drawers/batch_sheet.py`（批处理弹窗）
- `mf4_analyzer/signal/__init__.py` 导出
- `tests/test_order_analysis.py` / `tests/test_batch_runner.py`

参考基线文档：

- `docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`（codex 改动的 spec）
- `docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md`（time-domain 已落地的优化方法论）
- `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`（spectrogram canvas 已落地的 imshow 方案）

## 2. 三维度目标定位

用户表述的对标对象 HEAD ArtemiS 在三个维度上提供参照，但本项目 **不复刻其专业功能广度**，只锁定如下三类质量指标：

| 维度 | 期望 | 当前 |
|---|---|---|
| 渲染性能（单帧成本） | 与 FFT vs Time（spectrogram）同档 | 显著更慢（pcolormesh + gouraud） |
| 显示效果（视觉质量） | 与 spectrogram 一致的色阶、动态范围、字体、抗锯齿 | 色阶用 'jet'（不感知均匀），无动态范围控件，gouraud 模糊但无控制 |
| 交互流畅性（操作手感） | 与 time-domain canvas 一致：拖动不卡、缩放跟手、计算不冻 UI | 计算同步阻塞 UI；拖动每帧重渲整张 mesh；无 envelope/blit/xlim debounce |

## 3. 性能根因（按权重，A 最高）

| 编号 | 根因 | 触发位置 | 量级估计 |
|---|---|---|---|
| **A** | `pcolormesh(shading='gouraud')` 是 matplotlib 最慢的 2D 渲染分支：每个 quad 做四顶点颜色插值，且无法走 AGG 的图像快路径 | `main_window.py:1129, 1189` | 200×200 网格单帧 ~80–150 ms（机器实测同等规模 imshow ~3–8 ms） |
| **B** | order canvas 用的是 `PlotCanvas`（`canvases.py:1373`）—— 没有 viewport-aware envelope、没有 xlim listener、没有缓存、没有 blit。`TimeDomainCanvas` 那一整套优化完全没移植过来 | `canvases.py:1373-1585` 整段 | 重绘成本 = 100% 全量重绘 |
| **C** | `do_order_track` 把原始 RPM 数组**整条**直接 plot：`ax2.plot(rpm, '#2ca02c', lw=0.5)`。48 kHz × 5 min 即 14.4M 点直送 1200 px 画布 | `main_window.py:1246` | 单根 Line2D 单帧 ~150–300 ms |
| **D** | order 计算同步运行在 GUI 线程，靠 `QApplication.processEvents()` 救命；FFT vs Time 已经走 `SpectrogramWorker(QThread)`，order 没有照搬 | `main_window.py:1097, 1119, 1180, 1235` | 计算期窗体冻结，拖动事件全部丢 |
| **E** | 每次 plot 都 `clear()` + `add_subplot(1,1,1)` + `colorbar(im, ax=ax)` + `tight_layout()`。axes / colorbar / locator 全部不复用 | `main_window.py:1127-1136, 1187-1196, 1238-1252` | 单次 layout 30–80 ms，每次重计算都吃 |
| **F** | 滚轮节流（`_on_scroll`）只能压住 **频率**，不压 **每帧成本**；底层 `draw_idle()` 仍走全量 path | `canvases.py:1566-1585` | 已有的 50 ms 节流不够 |

## 4. order.py / batch.py codex 改动 review

整体方向我认可——把 order 的 FFT 路径并入 `one_sided_amplitude`，与 FFT / Spectrogram 共享窗函数和归一化，解决了 order/FFT 幅值不可比的老问题。但下面 10 项需要回头补：

### 4.1 ⚠️ 真问题：`compute_rpm_order_result` 的 `counts` 语义可疑

**位置:** `signal/order.py:200, 209`

```python
matrix[ri] += values
counts[ri] += values > 0          # 按"非零"计数，不是按"帧数"
...
amplitude = matrix / safe_counts
```

按 order 维度统计「该 bin 里有多少帧贡献了非零幅值」，再除回去——理论上把零幅值帧从均值分母里剔除，导致均值被系统性高估。对真实信号 `np.interp` 几乎不会精确为零，所以日常感觉不到；但当 `max_order × freq_per_order` 超过 Nyquist 的那些 order 列每帧都塞 0，counts 一直为 0，最终走 `safe_counts=1` 让 `0/1=0` 救回来——两条逻辑混在同一行，意图不清。

**建议:** 改 `counts[ri] += 1`（帧数计数），让语义统一；高于 Nyquist 的 order 列在 `_orders()` 阶段就裁掉。

> **API compatibility note：** `OrderRpmResult.counts` 是 `signal/__init__.py` 导出的公共 API 字段。改语义后，`counts` 形状不变（仍是 `(N_rpm_bins, N_orders)`），但每行所有列的值统一为该 bin 的总帧数（而非按非零次数变化）。任何外部消费方如果做过「按 order 列差异化解读」的统计，会出现行为变化。仓库内目前**无消费方**（grep `\.counts` 仅命中本结构定义和 batch 长表生成）；如果未来引入新消费方，请先看本节。

### 4.2 ⚠️ 真问题：order 计算运行在 GUI 线程

**位置:** `main_window.py:1097, 1119-1124, 1180-1185, 1235-1237`

`do_order_time` / `do_order_rpm` / `do_order_track` 全部同步调用 `OrderAnalyzer.compute_*`，回调里 `QApplication.processEvents()` 强行刷 UI。FFT vs Time 已经在 `SpectrogramWorker(QThread)` 跑了（`main_window.py:29` 起），order 没有照搬。结果是长信号 order 一次，整个窗体冻死直到完成；进度条「跳一下」是 `processEvents` 撞出来的伪流畅。

**建议:** 直接照 `SpectrogramWorker` 抄一份 `OrderWorker(QThread)`，三个 `do_order_*` 改成投递 → 完成回调里 plot。

### 4.3 ⚠️ 真问题：order 热路径每帧重新构造窗

**位置:** `signal/order.py:98-114` → `fft.py:117`

`_order_amplitudes` 每帧调一次 `one_sided_amplitude`，里面 `get_analysis_window(win, n)` 又会调 `scipy.signal.get_window` 现算一次窗。order 一次跑下来通常几百到几千帧，窗长 = nfft 完全不变，窗就被白生成几百到几千次。`compute_averaged_fft` 已经把窗 hoist 到循环外（`fft.py:192`）作为参照。

**建议:** 在 `OrderAnalyzer` 内层循环外预算一次窗，或给 `one_sided_amplitude` 加可选 `window_array=` 参数。

### 4.4 ⚠️ 真问题：order_track 把整条 RPM 直接 plot

见根因 **C**。

### 4.5 ⚠️ 真问题：`_matrix_to_long_dataframe` 用 Python 双循环

**位置:** `batch.py:365-373`

```python
for xi, x in enumerate(x_values):
    for yi, y in enumerate(y_values):
        rows.append((x, y, matrix[xi, yi]))
```

20 k × 200 的 order_time 输出要跑 4 M 次 Python 循环。

**建议:** 一次 vectorize：

```python
xs = np.repeat(x_values, len(y_values))
ys = np.tile(y_values, len(x_values))
return pd.DataFrame({x_name: xs, y_name: ys, 'amplitude': matrix.reshape(-1)})
```

直接把 batch 导出从「秒级」拉回毫秒级。

### 4.6 ⚠️ 真问题：`_compute_fft_dataframe` 把 UI 上 `'自动'` 字符串当 None 传

**位置:** `batch.py:223-228`，配合 `inspector_sections.py:586`

`FFTContextual.combo_nfft` 选项里有 `'自动'` 文本；`_remember_batch_preset` 把当前选项原样塞进 `params['nfft']`。batch 跑 FFT 时 `nfft=params.get('nfft')` 直接传给 `FFTAnalyzer.compute_fft`。`'自动'` 字符串 → `int(nfft)` 抛异常。

**建议:** 在 `_compute_fft_dataframe` 加一行 `'自动' → None` 转换 + `int(...)` 兜底，与 `_order_params()` 行为一致。

### 4.7 中等：`_run_one` 的 Figure 不释放

**位置:** `batch.py:316-348`

每个 batch item 都新建 `Figure(...)`，`savefig` 后既不 `clear()` 也不显式回收。200 文件批处理下峰值内存堆得很高。

**建议:** 在 `try/finally` 中 `fig.clear(); del fig`，或复用同一个 fig 跨迭代。

### 4.8 中等：`AnalysisPreset` `frozen=True` 但内嵌 mutable

**位置:** `batch.py:24, 32, 36`

`dict` 字段不可哈希，preset 不能进 `set` 或当 dict key。当前没人这么用所以无症状，但 `frozen=True` 会让人误以为可哈希；将来要走 LRU 缓存就会炸。

**建议:** 去掉 `frozen=True` 或改用 `MappingProxyType` / `tuple` 表达。

### 4.9 中等：order 测试覆盖太薄

**位置:** `tests/test_order_analysis.py`

整个 order 路径只有一个 27 行的 `extract_order_track` 测试。没有：

- `compute_time_order_result` 在变速 RPM 下定阶幅值正确性
- `compute_rpm_order_result` 的均值聚合（即 4.1 的 counts 语义）
- `cancel_token` / `progress_callback` 路径
- batch 端 order_time / order_rpm 落 csv 的形状

考虑到这正是「一直算不准」的高风险代码，TDD 回归网在这里不应该只有一根线。

### 4.10 小问题集合

- `_matches`（`batch.py:152-163`）先 substring 后 regex，含义无文档；`motor.speed` 这种带正则元字符的"信号名"会意外匹配 `motorXspeed`。
- `compute_rpm_order_result` 用 `np.argmin(np.abs(rpm_bins - rpm_mean))`，每帧 O(N_bins)。直接 `int((rpm_mean - rpm_min) / rpm_res)` + clamp 即可。
- `_remember_batch_preset` 锁存 `(fid, channel)` 元组，文件被关闭后这个元组成悬空引用，下一次 `open_batch` 会拿到不存在的 fid 被 `_expand_tasks` 默默吞掉，无任何用户提示。建议在 `open_batch` 入口校验 preset.signal 仍存在，否则降级到 free_config。

## 5. 与 time-domain Phase 1 优化的差距对照

参照 `2026-04-25-time-domain-plot-performance-report.md`，time-domain 已经落地的优化项目对 order canvas 的覆盖情况：

| time-domain 已有优化 | order canvas 是否覆盖 |
|---|---|
| viewport-aware envelope 下采样（按 canvas 像素宽度） | ❌ 完全没有 |
| xlim 变更监听 + QTimer debounce | ❌ 完全没有 |
| envelope LRU 缓存（quantized xlim key） | ❌ 完全没有 |
| `path.simplify` / `agg.path.chunksize` rcParams | ✅ 全局已开（time canvas 设置） |
| 单调性检测缓存 | N/A（order 不走 custom-x） |
| 复用 axes / Line2D / SpanSelector | ❌ order 每次 `clear()` 重建 |
| 拖动期间 blit 游标，松手 full redraw | ❌ order 无游标 blit |
| tight_layout 频率收敛 | ❌ order 每次 plot 都调 |
| 计算后台线程 | ❌ order 同步阻塞 GUI |

差距是断崖式的。order canvas 几乎没有从 time-domain 的优化里继承任何东西。

## 6. 显示效果 gap

| 项目 | spectrogram canvas | order canvas |
|---|---|---|
| 色阶 | turbo（默认）+ 用户可选；perceptually-uniform | 'jet' 写死，已知不感知均匀 |
| 动态范围 | Auto / 60 dB / 80 dB 三档 | 无控件（只能 colorbar 自动） |
| 抗锯齿 / 插值 | imshow + 'nearest'（清晰）；可改 bilinear | gouraud 强制平滑，无开关 |
| 频率/阶次轴 | 用户可锁定范围 | 无范围控件 |
| 色彩条 | 复用且 `update_normal` 不重建 | 每次 `colorbar(im, ax)` 重建 |
| dB 缓存 | id(result) keyed | 无 dB 模式 |
| 中文字体 | 全局一致 | 全局一致 ✓ |

显示效果 gap 不在于"matplotlib 不行"，而在于 order 这一档**没有把 spectrogram 已经做对的事抄一遍**。

**本次只补哪一档、明确不补哪一档：**

| 项目 | 本次范围 |
|---|---|
| 色阶（默认 turbo + 可选 jet） | ✅ 本次补 |
| imshow + bilinear 抗锯齿 | ✅ 本次补 |
| colorbar 复用 | ✅ 本次补 |
| 中文字体 | ✅（已在位） |
| 动态范围控件（Auto / 60 dB / 80 dB） | ❌ **deferred to next iteration** |
| order 模式的 dB / dB re X 显示 | ❌ **deferred to next iteration** |
| order / RPM 轴范围锁定控件 | ❌ **deferred to next iteration** |
| dB 缓存（id(result) keyed） | ❌ deferred（依赖 dB 模式上线） |

deferred 项的理由：本次目标是"渲染性能 + 视觉清晰度 + 交互流畅性"三件事，引入 dB 模式会牵动 inspector_sections 的控件、`OrderHeatmapResult` 数据契约、 colorbar label 联动、cursor 读数单位等多处级联，对本期范围是过度膨胀。在 spec §11 显式记入 deferred，后续单独立项。

## 7. 数据规模与性能基线（定性）

典型 NVH 场景：

- **小规模**：10 s × 8 kHz = 80 k 样本，nfft=1024，order_res=0.1，max_order=20 → 200 orders × 200 frames = 40 k 网格
- **中规模**：60 s × 24 kHz = 1.44 M 样本 → 200 orders × 1200 frames = 240 k 网格
- **大规模**：300 s × 48 kHz = 14.4 M 样本 → 200 orders × 6000 frames = 1.2 M 网格

中规模场景下：

- pcolormesh+gouraud 单帧渲染 ~50–150 ms → 拖动每秒最多 6–20 帧
- imshow+bilinear 单帧渲染 ~3–8 ms → 拖动稳定 60 fps（受 matplotlib draw 上限制约）

大规模场景下：

- order_track 把 14.4 M 点 plot：单帧 200–500 ms（卡死感）
- envelope 下采样到 ~2400 点：单帧 < 5 ms

## 8. 优先级与建议路线

按 ROI 排序：

| 优先级 | 改动 | 解决根因 / 问题 |
|---|---|---|
| **P0** | order 2D 谱从 `pcolormesh(gouraud)` → `imshow(bilinear)`，复用 axes/colorbar | A, E |
| **P0** | `OrderWorker(QThread)` 接管 `do_order_*` | D |
| **P0** | order 内层循环 hoist 窗 + counts 语义修正 | 4.1, 4.3 |
| **P0** | order_track 下半幅 RPM 复用 envelope（或换 `TimeDomainCanvas`） | C |
| **P1** | `PlotCanvas` 加 xlim listener + debounce + envelope cache + blit 游标 | B, F |
| **P1** | `_matrix_to_long_dataframe` vectorize；`_compute_fft_dataframe` `'自动'` 兜底；Figure 释放 | 4.5, 4.6, 4.7 |
| **P1** | order 测试补全（time/rpm 正确性 + cancel + batch nfft 自动） | 4.9 |
| **P2** | `compute_rpm_order_result` argmin → 算术索引；`_matches` 文档化；preset 失效降级 | 4.10 |
| **未列入** | mip-map 多分辨率、GPU/pyqtgraph 后端、3D waterfall | 留待 future-work |

P0 + P1 是本次 spec 的全部范围。P2 体量小可顺手做。Phase 4（GPU 等）显式不做。

## 9. 验收标准（用户可感知）

1. 中规模数据集（60 s × 24 kHz）下，order 模式拖动 ≥ 30 fps（视觉无卡顿）。
2. order 计算期间窗体不冻结，可继续切换文件 / 调参 / 拖动其它 canvas。
3. order_track 大规模数据集（300 s × 48 kHz）下，下半幅 RPM 拖动 ≥ 30 fps。
4. order 2D 谱视觉清晰度 ≥ 当前 gouraud 版本（不模糊化）。
5. order 重计算同参数命中缓存的话，结果立即出图（< 100 ms）。
6. 所有现有 order / batch 测试继续通过；新增的 counts 语义、time-order 正确性、batch nfft 自动测试通过。
7. batch 200 文件 order_time 顺序处理峰值内存增量 < 200 MB。
8. 既有用户工作流（手动设置 order_res / time_res / max_order / target_order）行为不变。

## 10. 关于"对标 HEAD ArtemiS"的边界

- ✅ **追平**：渲染性能、视觉清晰度（imshow + bilinear + turbo）、交互流畅性
- ⏸ **本次不追、留下次**：order 模式的 dB / dB re X 显示、动态范围控件（Auto / 60 dB / 80 dB）、order / RPM 轴范围锁定控件
- ❌ **永远不追**：3D waterfall、多通道并行、live streaming、专业 PSD/RMS 模式、跨文件比较、acoustic models
- ❌ **永远不追**：自定义 GPU/OpenGL 后端
- ❌ **永远不追**：cross-correlation / coherence / transfer function 等额外算法

本项目体量与定位不支持复刻 HEAD ArtemiS 的功能广度。本次只在它已经定义的「质量基线」上对齐。

---

**结论：** order 这一摊代码本质上是 codex 把数学层重构对了，但完全没碰渲染层和线程层。本次需要把 spectrogram canvas 已经做对的事（imshow + worker 线程 + 复用 axes + dB 缓存）和 time-domain canvas 已经做对的事（envelope + xlim debounce + blit + cache）都"抄"过来，并把数学层的几个真问题（counts 语义、窗 hoist、batch vectorize）一起补掉。
