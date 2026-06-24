# 时域多分辨率 min/max 金字塔（mip pyramid）设计

- **日期：** 2026-06-24
- **状态：** 设计（待批准后执行；本文件不含实现）
- **目标问题：** 大 HDF（多通道 × 数百万点 @48kHz+）时域 pan/zoom 卡顿。
- **关联：** profiling 实测（见下）；既有 envelope/桶守卫机制
  `mf4_analyzer/ui/pg_canvas/renderer.py`、`mf4_analyzer/signal/_envelope_cutils.py`
  `positions_envelope`；不解决的部分见 §7。

---

## 1. 背景与实测瓶颈（2026-06-24 profile，真实文件 8 通道）

文件 `testdoc/2023-10-31_347#_C0203_running_1.hdf`，group 0 = 48kHz，每通道
**3,160,960 点 / 65.85s**，8 条 dense 通道，canvas 1400×800（`pixel_width≈1309`）。
同步 `viewport.repaint()` 计时（非 grab 缓存 blit）：

| 操作 | subplot 单帧 | 拆分 |
|---|---:|---|
| 缩小看全程 pan（最卡） | ~78 ms | **envelope 63 ms (~80%)** + paint 15 ms |
| 放大 1s 窄窗 pan | ~25 ms | envelope 8 ms + paint 18 ms |
| 缩放 per-step | ~51 ms | envelope 36 ms + paint 15 ms |
| 首帧 paint | 13 ms（subplot）/ 36 ms（overlay） | — |

`positions_envelope` 单通道（pw=1400）：
- **全量窗（可见 3,160,960 样本）：8.99 ms**
- 1s 窄窗（可见 48,000 样本）：**0.24 ms**
- 比值 **38×**，可见样本比 **66×** → **成本 ~线性于「当前可见源样本数」**。

**根因**：现在每个 pan/zoom tick 都对**每条可见通道**在**当前可见窗口**上重算
min/max envelope（`renderer._refresh_visible_data` → `positions_envelope`）。窗口
越宽（缩得越小），扫描的源样本越多，8 通道叠加 → 缩小看全程时每帧 ~63ms 全花在
envelope 重扫上。range-key 一变（pan 改 xlim）即重算，无跨帧复用。

---

## 2. 目标 / 非目标

**目标：**
- 把 pan/zoom 帧的 envelope 成本从 **O(可见源样本)** 降到 **O(像素≈桶数)**，
  使其与文件大小、缩放级别**基本无关**。
- 缩小看全程 pan：envelope 63ms → **个位数 ms**；缩放 36ms → **个位数 ms**；
  全帧 78ms → **~20ms 量级**（剩 paint）。
- 首帧 bind（`plot_channels` 内首次全量 envelope）也受益。
- **数值结果与现有 envelope 像素级等价**（min/max 包络，不丢可见特征）。

**非目标（金字塔不碰，见 §7）：**
- paint 光栅墙（竖线根数 = pixel_width，由现有 overlay/subplot/wall 桶守卫管）。
- 滤波 `filters.apply` 的 8.6s（数值算法，另案，见 §7.2）。
- load I/O（parse_head_hdf 361ms）、plot_channels 建轴成本。

---

## 3. 设计概述：每通道 min/max 金字塔

对每条通道的源信号 `sig`（配套时间轴 `t`），载入后预计算一组**逐层降采样的
min/max 对**：

```
level 0:  原始 sig（N 点）                      —— 不存，直接用源数组
level 1:  每 F 个样本一个 (min,max)  → 2·ceil(N/F)
level 2:  每 F^2 个样本一个 (min,max) → 2·ceil(N/F^2)
...
level L:  直到该层点数 <= 某阈值（如 2·pixel_width_max，~4096）
```

- **降采样因子 F**：建议 8（每层缩 8×）。L = ceil(log_F(N / 阈值))，对 3.16M、
  阈值 4096、F=8 → L≈4 层。
- **每层存什么**：`level_min[k]`、`level_max[k]`（float32 即可，见 §6 内存），
  以及该层每桶对应的**代表时间**（或由层步长 + t0 推出，均匀采样时无需存 t）。
- **金字塔的桶是「源样本下标」对齐的**（每 F^k 个源样本一桶），与「当前视图像素
  桶」不同；查询时做一次映射（§4）。

### 3.1 单调/均匀时间轴的前提
- 时域时间轴**单调递增**（`_channel_is_monotonic` 已缓存）。金字塔层按**源下标**
  分桶（等样本数），查询时用时间→下标的二分（均匀采样可直接算下标）。
- 非单调 / 含 NaN gap 的通道：**不建金字塔**，回退现有 `positions_envelope`
  全扫（这些是少数且现有路径已正确处理 NaN 断点）。是「保守红线」：金字塔只服务
  能安全降采样的规整通道。

---

## 4. 查询：给定 (xlim, pixel_width) 取 envelope

替换/前置于 `positions_envelope` 的热路径：

1. 由 `xlim` + 时间轴算出可见源下标范围 `[i0, i1)`（均匀采样：除法；一般单调：
   二分，O(log N)）。
2. 选层：要让「该层落在可见范围内的桶数」≥ 目标桶数（≈ `effective_width`，即
   现有 `_effective_pixel_width` 算出的值）。即选最粗的、桶密度仍 ≥ 像素密度的层
   `k`，使 `(i1-i0)/F^k >= effective_width`。这样每像素列至少覆盖一桶，**不丢特征**。
3. 在该层的 `[i0/F^k, i1/F^k)` 切片上，做**第二次**「层桶 → 像素桶」的 min/max
   归并（把 ~effective_width×O(1) 个层桶聚合到 effective_width 个像素桶）。这一步
   扫描的是**层桶数（≈几千）**，不是源样本数（百万）。
4. 输出与现有 `positions_envelope` 同形（`env_t, env_s`，每像素桶一对 min/max
   交错），交给现有 `_build_painter_path` / `setData`，**下游零改动**。

**复杂度**：步骤 1 O(log N)，步骤 3 O(可见层桶数 ≈ F × effective_width)。与源
样本数 N 无关 → 即「窄窗 0.24ms」的量级推广到全量窗。

### 4.1 与现有桶守卫的关系
- `_effective_pixel_width`（overlay 按曲线数封顶 / subplot dense 封顶）、窄Y竖线墙
  守卫 `_is_y_overflow_wall` + `_WALL_BUCKET_BUDGET`：**全部保留**。金字塔只改
  「如何快速得到 envelope」，最终桶数仍由这些守卫决定（paint 墙仍归它们管）。
- 金字塔查询的目标桶数 = 守卫算出的 `effective_width`（含 wall-capped 后的值）。

---

## 5. 集成点（代码层面，待执行时落地）

- **构建**：在通道数据进入 canvas 后（`plot_channels` bind 时，或更早在加载/组装
  阶段）为每条规整通道建金字塔。**建议放后台线程异步建**（见 §8），首帧可先用
  现有全扫、金字塔就绪后接管。
- **存储**：挂在 canvas 的按通道结构上（与 `channel_data` 同 `_ChannelKeyDict`
  复合键，键 = (data_id, name)），如 `self._channel_pyramid[ck] = Pyramid(...)`。
  随 `clear()` / 重新 `plot_channels` 失效重建。
- **查询接入**：`renderer._refresh_visible_data` 调 `positions_envelope` 处，改为
  「有金字塔且通道规整 → 走金字塔查询；否则回退 `positions_envelope`」。
  保留 `_legacy_positions_envelope` monkeypatch seam（测试用）。
- **数值核心**：金字塔的构建与「层桶→像素桶」归并是纯 numpy/数值，建议放
  `mf4_analyzer/signal/`（如 `signal/_minmax_pyramid.py`），由 signal 专家 TDD 实现；
  canvas/renderer 的接入由 pyqt-ui 专家做。

---

## 6. 内存

- 每加一层增加约 `2N/F^{k}` 个值。几何级数总和 ≈ `2N/(F-1)`（F=8 → ≈ 0.29N）。
  即金字塔总点数 ≈ 0.29 × 源点数。
- float32 存：3.16M 源 → ~0.9M 金字塔值 × 4B ≈ **3.6 MB/通道**，8 通道 ≈ **29 MB**。
  可接受（源数据本身 8×3.16M×8B≈190MB）。
- 用 float32 而非 float64：min/max 包络仅用于像素级显示，float32 精度足够；显式
  记此权衡（与现有 envelope 的 float64 输出在像素级不可分辨）。

---

## 7. 金字塔**不**解决的（必须并行/另案处理）

### 7.1 paint 光栅墙
窄窗 paint 18~23ms、overlay 首帧 36ms：屏内竖线根数决定，已由 overlay/subplot/
窄Y墙桶守卫单独压制。金字塔不改桶数上限，故不减 paint。**保持现状**。

### 7.2 ⚠️ 滤波 apply ~8.6s（8 通道）—— 最大单点，强烈建议另案先修
profile 实测：`signal/filters.apply` 对 3.16M 点做 odd-reflection pad 到
`N = n0 + 2·(n0//10) ≈ 3.79M`（**非 2 的幂**），`np.fft.rfft(xp)` 落进 numpy
混合基 / Bluestein 慢路径 → **单通道 1080ms、8 通道 ~8.6s**。这是「滤波 ON 一开卡
十几秒」的最大真凶，**金字塔零帮助**。
**修法（廉价高 ROI）**：把 pad 后长度对齐到 `scipy.fft.next_fast_len(N)` 或 2 的幂
（多 pad 一点到 fast length，FFT 后裁回），让 rfft 走快路径。属 `filters.apply`
函数体（数值算法）→ signal 专家。预估单通道 1080ms → 百 ms 量级。
> 这条不在金字塔范围内，但对用户「滤波太卡」的体感影响**比金字塔更直接**，建议优先。

### 7.3 一次性成本
load 361ms + plot_channels 建轴 ~450ms：一次性，异步加载（§8）可改善体感，非金字塔本职。

---

## 8. 可选增强（同主题，可纳入或拆分）

- **B2 交互降分辨率**：拖动中查询更粗一层、空闲补全（接现有 idle-AA 门控）。金字塔
  让「取更粗层」近乎免费，与之天然契合。
- **B3 异步加载 + 后台建金字塔**：加载/建塔放 QThread，UI 先响应；金字塔就绪前用
  现有全扫兜底。改善「打开卡 UI」。

---

## 9. 正确性与测试策略（详见配套 plan）

- **像素级等价**：对同一 (xlim, effective_width)，金字塔 envelope 与现有
  `positions_envelope` 的输出在**每像素桶 min/max 上一致**（金字塔的层桶是源桶的
  超集聚合，min/max 单调可合并 → 严格 ≥/≤ 不丢极值；选层保证桶密度 ≥ 像素密度）。
  用合成信号（含尖峰/单点极值）断言两者逐桶 min/max 相等或金字塔包络 ⊇ 真实极值。
- **回退路径**：非单调 / NaN-gap 通道走旧路，单测覆盖。
- **perf 回归**（`@pytest.mark.slow`）：全量窗 envelope 查询单帧 ms 显著低于全扫
  （用 §1 的对照量级断言比值）。
- **不变量**：桶守卫（overlay/subplot/wall）算出的最终桶数不被金字塔改变。

---

## 10. 风险

- 选层/映射 off-by-one 导致丢极值 → 由「桶密度 ≥ 像素密度 + min/max 单调合并」+
  逐桶等价测试守住。
- 非均匀但单调时间轴的下标映射成本（二分）→ O(log N)，可忽略；非单调直接回退。
- 内存（§6 已估，~29MB/8通道，可接受）。
- 构建时机：同步建会把成本搬到「打开」→ 用异步（§8）或仅在首次 pan 时惰性建。
