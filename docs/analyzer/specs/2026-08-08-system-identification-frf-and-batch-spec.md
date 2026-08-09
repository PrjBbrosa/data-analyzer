# 系统辨识 FRF 与 Batch FRF — 产品与技术规格

日期：2026-08-08

状态：**设计定稿，未实施**

实施计划：`docs/analyzer/plans/2026-08-08-system-identification-frf-and-batch-implementation.md`

基线：`main@4b216e5a`（本地比 `origin/main` ahead 1；本 spec 不处理该 Git 状态）

目标版本：首版功能；是否随发布升版由后续 release 任务决定，本设计不修改 `APP_VERSION`

## 1. 结论

TraceLab 增加一个独立的「频响」分析模式，计算单输入单输出的频率响应函数
（Frequency Response Function，FRF），同时输出：

1. 复数传递函数 `H(f)`；
2. 幅频：线性倍率与 `20·log10(|H|)`；
3. 相频：包裹相位与展开相位；
4. 幅值平方相干性 `γ²(f)`；
5. 可审计的 `Pxx/Pyy/Pxy`、有效采样率、窗长、段数、时间范围和告警。

运行时数值核心只依赖 NumPy。正确性不以“看起来相似”为准，而以明确的 Welch/CSD
定义、显式窗口数组、手算小向量、固定 golden vectors 和可选 SciPy 参考对照共同证明。
只要参数和边界条件一致，NumPy 结果应在浮点误差内与 SciPy 的
`welch/csd/coherence` 组合比肩；不承诺与 SciPy 不同版本的隐式默认值自动一致。

该能力同时进入：

- 单次分析：顶部第五个模式、独立三联图、Inspector 输入/输出映射和分析 View；
- TimeDomain：关联物理时间范围，并可将计算使用的输入/输出对送回时域复核；
- Batch：一输入对多个输出的配对组、SISO 任务展开、预览、导出、图片和 manifest。

首版以正确性优先：每个 FRF 任务的输入、输出必须来自同一个逻辑来源，并共享同一条
真实物理时间轴和采样率。不得用 `min(len(x), len(y))`、合成时间网格、静默插值或
静默重采样掩盖不兼容数据。

## 2. 当前架构证据与扩展位置

本文以当前 checkout 为准；下列符号是实施锚点，行号漂移时以符号名定位。

| 领域 | 当前事实 | FRF 扩展方向 |
| --- | --- | --- |
| 顶部模式 | `ui/toolbar.py:Toolbar` 只有 `time/fft/fft_time/order`，标签中英混排 | 新增 `frf`，可见名统一为五个双字中文名 |
| 页面路由 | `ui/chart_stack/_helpers.py:_MODE_TO_INDEX` 与 `ChartStack` 只有四页 | 新增独立 FRF analysis page，不塞入 FFT 页 |
| Inspector | `ui/inspector.py` 有 FFT、FFT Time、Order contextual widgets | 新增 `FrfContextual`，复用共享时间范围区的移动契约 |
| 多 View | `analysis_view_state.py:PaneState` 只有无角色 `sources` 和 `rpm_source` | 增加显式 `input_source/output_source`，不以列表顺序表达角色 |
| 异步计算 | `ui/analysis_jobs.py:AnalysisJobService` 已按 section 管理队列/取消/线程 | 直接注册 `frf`；禁止复制一套 QThread pump |
| 缓存 | `AnalysisResultCache.make_key(fid, channel, params)` 是单通道键 | 增加双端 FRF key/cache，任一 fid 失效都清条目 |
| 数值层 | `signal/fft.py` 的窗函数明确为 symmetric | FRF 新模块显式定义 periodic 窗，避免默认语义漂移 |
| Batch 方法 | Runner、recipe、UI 和 renderer 只支持四种方法 | 全链路新增内部键 `frf` |
| Batch 选择 | `target_pairs` 当前含义是 `(source, channel)` | 不复用；新增 portable pair rule 与 runtime resolved pair |
| Batch 身份 | `TaskOutputIdentity` 只有一个 `channel_identity` | canonical identity 纳入输入和输出两端 |
| Batch render | `batch_render_models.py` 为 GUI-free DTO，Qt builder 支持四种 kind | 新增 FRF 三联图 DTO 和 Qt renderer 分支 |
| 帮助入口 | `help._GUIDE_FILES`、`ui/hints.py`、`ui/quickref.py` 是用户交互文档面 | 同步增加 FRF 并把“四个分析模式”改为“五个” |

## 3. 目标

### G1 — 数值结果可定义、可复核

- H1/H2、谱方向、缩放、窗口周期性、相位和相干性有唯一公式；
- 同参数下 NumPy 与 SciPy reference 在浮点误差内一致；
- 非有限值、短数据、零激励、非均匀时间和取消都有显式结果；
- 原始复数结果不因显示选项而丢失。

### G2 — 单次分析是正式的第五种分析

- 顶部显示 `时域 / 频谱 / 时频 / 频响 / 阶次`；
- FRF 有独立 View、分屏、缓存、项目恢复和帮助入口；
- Inspector 明确选择输入与输出，不从通道勾选顺序猜角色。

### G3 — 时域关联保持物理意义

- FRF 可使用 TimeDomain 已提交的物理时间范围；
- 时间轴与频率轴绝不直接联动；
- 自定义 X 轴不能冒充秒；
- 用户能从 FRF 回到准确的输入/输出时域波形和同一有效时间范围。

### G4 — Batch 可复现且不误配

- 配置层表达“一输入 → 多输出”，运行层展开为独立 SISO tasks；
- preview 与 run 使用同一组复合身份；
- 数据、图片、任务 id、重试和 manifest 都能区分输入与输出；
- 不把逻辑来源 id 等运行时身份写入 portable preset。

### G5 — 不破坏现有依赖方向

- `signal/frf.py`、`batch_compute.py`、`batch_types.py`、
  `batch_render_models.py` 不 import UI/MainWindow/Qt renderer；
- 不新增 SciPy 运行依赖，不把 matplotlib 带回运行时；
- FRF 复用 `AnalysisJobService` 和 `_RunReporter`，不产生第二套生命周期所有者。

## 4. 非目标

首版明确不做：

- MIMO 矩阵 FRF、模态参数拟合、极点/零点辨识、状态空间辨识；
- 跨逻辑来源自动配对；
- 不同设备时钟自动同步、漂移校正或相位校正；
- 隐式重采样、隐式截短、用索引位置代替时间戳；
- 自动识别并移除纯延迟；首版始终保留系统真实延迟；
- 相干性阈值删除频点或篡改原始传递函数；
- 实时采集中的在线 FRF；
- Batch 中任意输入集合 × 任意输出集合的隐式笛卡尔积；
- 新增 PDF/SVG 输出格式；沿用当前 Batch PNG/数据输出能力；
- 因本功能单独进行产品版本升级、提交、推送或发布。

## 5. 用户可见命名与信息架构

### 5.1 顶部模式

| 内部 key | 顶部可见名 | Tooltip / 页面标题中的技术名 |
| --- | --- | --- |
| `time` | 时域 | 时域（Time Domain） |
| `fft` | 频谱 | 频谱（FFT） |
| `fft_time` | 时频 | 时频（FFT vs Time） |
| `frf` | 频响 | 频响（FRF / 系统辨识） |
| `order` / Batch `order_time` | 阶次 | 阶次（Order） |

原则：顶部和 Batch 方法按钮只使用等长中文业务名；`FFT`、`FRF` 等标准术语保留在
tooltip、Inspector 组标题、导出报告、帮助文档和数据列中。内部 key 不因显示名变化
而迁移，现有 preset 与项目文件保持兼容。

### 5.2 单次 FRF 页面

中心区为三个纵向共享频率 X 轴的图：

1. 幅值：默认 dB，可切线性；
2. 相位：默认展开相位，可切包裹相位；
3. 相干性：固定范围 `[0, 1]`，显示阈值线。

共同交互：

- 一个频率游标贯穿三图；读数卡同时显示 `f/|H|/phase/coherence`；
- 三图只共享 frequency X，不与 TimeDomain 的 X 轴同步；
- log-frequency 模式只在绘制层隐藏 `f <= 0`，原始结果和 CSV 保留 DC；
- 低于相干性阈值的幅相曲线可淡化，但不能删除数据点；
- 空态依次为“请选择输入和输出”“参数已变化，点击计算”“正在计算”“计算失败”；
- 每个 pane 首版只显示一对输入/输出；比较多对使用 analysis split 或多个 View，
  不在一个 pane 内隐式 overlay。

### 5.3 Inspector 目标布局

（2026-08-09 定版：按 `61053293` 实施后的 as-built 卡片结构描述，替代本节最初的
八项线性列表；“先选通道、再挑预设”更贴近实际操作流，经真机截图验收。）

由上至下：

1. 标题 `系统辨识 · 频响（FRF）`；
2. 信号映射卡（`frfSignalCard`）：输入、被辨识系统流向图、输出、交换按钮、
   `分析范围`（全范围 / 使用当前时域范围 / 手动范围）与时间范围控件；
3. 辨识参数卡（`frfParamsCard`）：预设条（稳健 / 低频 / 快速 / 自定义）、
   `估计器` H1/H2、窗口与周期语义、段长秒数、重叠率、NFFT、每段去均值、
   validation 提示、主按钮 `计算频响`、次按钮 `在时域查看`；
4. 显示卡（`frfDisplayCard`）：幅值 dB/线性、频率 log/linear、相位展开/包裹、
   相干阈值、低相干淡化；
5. 有效事实区：实际 Fs、频率分辨率、完整段数、有效时间范围、时间抖动和告警
   （含 `FrfResult.warnings`，须常驻可见而非仅 toast/状态栏）。

输入/输出控件显示 `来源名 · 通道名 [单位]`，内部值始终为 `(fid, channel)`。
同名通道不得以 display name 作身份。

### 5.4 内建预设

FRF 拥有方法专属 display names；不得把现有 FFT/时频/阶次的全局“频率/均衡/时间”
名称整体改掉。

| 名称 | estimator | `t_win_s` | overlap | 典型用途 |
| --- | --- | ---: | ---: | --- |
| 稳健（默认） | H1 | 2.0 s | 50% | 通用、输出噪声占主导 |
| 低频 | H1 | 8.0 s | 75% | 提高低频分辨率，要求更长记录 |
| 快速 | H1 | 0.5 s | 50% | 短记录/快速检查，频率分辨率较低 |
| 自定义 | 用户值 | 用户值 | 用户值 | 任一字段偏离内建值后进入 |

三套内建预设共同默认：periodic Hann、每段去均值、自动 NFFT=`nperseg`、dB、log
频率、展开相位、相干阈值 0.8、低相干淡化开启、保留系统延迟。

## 6. 数值定义

### 6.1 术语与方向

- 输入信号：`x(t)`；输出信号：`y(t)`；
- `X_k(f)`、`Y_k(f)`：第 `k` 个完整段加窗后的单边 FFT；
- 交叉谱方向固定为 `Pxy = E[conj(X) · Y]`；
- 因而纯增益 `y = a·x` 得到 `H1 = a`，不能出现共轭或相位符号反向。

估计器：

```text
H1(f) = Pxy(f) / Pxx(f)
H2(f) = Pyy(f) / Pyx(f) = Pyy(f) / conj(Pxy(f))
γ²(f) = |Pxy(f)|² / (Pxx(f) · Pyy(f))
```

H1 适合输出侧噪声占主导的常见测量；H2 作为用户显式选择，适合输入侧噪声占主导的
假设。UI 和报告必须显示实际 estimator，不能只显示“FRF”。

### 6.2 输入合同

计算入口接收：

```python
compute_frf(
    input_values,
    output_values,
    *,
    fs,
    params: FrfParams,
    input_time=None,
    output_time=None,
    cancel_check=None,
    progress=None,
) -> FrfResult
```

硬合同：

- `input_values/output_values` 为实数、一维、非 bool；内部转 `float64`；
- 两端应用同一物理时间范围后必须等长且样本一一对应；
- 提供时间数组时，两者同为 `float64` 一维、严格递增、等长，且在容差内逐点一致；
- `fs` 必须来自文件元数据或用户已确认的重建结果，不得推测；
- 时间间隔按当前统一采样校验容差检查（首版复用 `signal/spectrogram.py` 的
  `DEFAULT_TIME_JITTER_TOLERANCE=1e-3` 相对抖动口径，同包 import 不新增依赖），
  记录实测最大抖动；
- 非均匀或两端时刻不一致时阻断并提示显式重建/对齐，不在 FRF 内修复；
- 时间范围为半开语义还是闭区间必须复用现有 shared preprocess 的既有选择口径；
  输入和输出只允许应用同一个 mask。

异常输入：

| 情形 | 行为 |
| --- | --- |
| 空数组、二维数组、complex、bool | `ValueError`，消息指出 input/output 与原因 |
| 输入输出长度不同 | 阻断；禁止截到较短长度 |
| NaN/Inf | 阻断并报告第一批非有限样本数量；首版不插值 |
| `fs <= 0` 或非有限 | 阻断 |
| 非严格递增/非均匀时间 | 阻断并给出实测抖动 |
| 输入与输出时间不一致 | 阻断并给出最大时差 |
| 输入与输出是同一通道 | UI/Batch validation 阻断，避免无意义任务 |

### 6.3 分段合同

- `nperseg = round(fs * t_win_s)`；`t_win_s > 0`；
- `nperseg < 2` 时阻断（“窗长过短，段长不足 2 个样本”）。该下界是硬合同：
  periodic 窗在 `nperseg = 1` 时整段为零（`Σw² = 0`），§6.5 的
  `scale = 1/(fs·Σw²)` 会除零；且 `nperseg = 1` 会让“完整段数 ≥ 2”失去把关意义
  （每个样本都是一个完整段，结果只剩 DC 一个 bin）。实现进入 scale 计算前必须
  校验 `Σw² > 0`；
- `noverlap = floor(overlap * nperseg)`，`0 <= overlap < 1`；
- `hop = nperseg - noverlap`；
- 段起点严格为 `0, hop, 2·hop, ...`，只使用完整段；尾部不补零、不追加半段；
- 自动 NFFT 时 `nfft = nperseg`；手动时 `nfft >= nperseg`；
- 有效完整段数 `< 2` 时阻断：“平均段不足 2，请缩短窗长或扩大时间范围”；
- 有效段数 `2–3` 可算但产生“统计稳定性较低”告警；
- 不为满足段数静默缩短用户选择的窗长；有效参数必须和 requested 参数并列记录。

每段默认减去自身均值：

```text
x'_k = x_k - mean(x_k)
y'_k = y_k - mean(y_k)
```

首版只提供 constant detrend（开/关），不提供线性 detrend。

### 6.4 窗函数

默认 `periodic Hann`：

```python
w = np.hanning(nperseg + 1)[:-1]
```

该语义与当前 `signal/fft.py:get_analysis_window()` 的 symmetric 窗不同。FRF 不得
直接复用一个未声明周期性的窗口结果。若支持 hamming/blackman/bartlett/kaiser/
flattop，则每一种都必须在 `get_frf_window(name, nperseg, periodic=True)` 中定义并有
显式数组测试；不能依赖 SciPy 的默认 `get_window`。

首版可见列表与现有分析保持一致，固定为
`hanning/hamming/blackman/bartlett/kaiser/flattop`；`hann` 仅作为
`hanning` 的兼容 alias。六项统一按 symmetric generator 的 `nperseg + 1` 长度生成后
去掉最后一点；Kaiser 固定 `beta=14`，flattop 复用现有五项系数。每项都必须与 SciPy
`get_window(..., fftbins=True)` 的显式数组对照；未完成定义的项不能出现在 UI。

### 6.5 Welch PSD/CSD 与单边缩放

对每个完整段：

```text
X_k = rfft(x'_k · w, nfft)
Y_k = rfft(y'_k · w, nfft)
scale = 1 / (fs · Σ w²)

Pxx = mean(conj(X_k) · X_k) · scale
Pyy = mean(conj(Y_k) · Y_k) · scale
Pxy = mean(conj(X_k) · Y_k) · scale
```

转换为单边密度时：

- DC 不乘 2；
- 偶数 NFFT 的 Nyquist 不乘 2；
- 其余正频率 bin 的 `Pxx/Pyy/Pxy` 同时乘 2；
- `frequencies = np.fft.rfftfreq(nfft, d=1/fs)`。

虽然 H1/H2 中共同 scale 多数会抵消，仍必须正确保存 `Pxx/Pyy/Pxy`，因为它们用于
相干性、诊断和 SciPy parity。

实现不得一次堆叠无限多段。使用 bounded block 或逐段累加，临时复数数组预算默认不
超过 64 MiB；累加器为 `complex128/float64`。每个 block 检查 cancel，进度按已处理
完整段数节流上报。

### 6.6 分母、零激励与浮点边界

- `Pxx/Pyy` 计算后取实部，并允许清除仅由舍入产生的极小负值；
- H1 分母为 `Pxx`，H2 分母为 `conj(Pxy)`，coherence 分母为 `Pxx·Pyy`；
- 近零判据必须对工程量缩放保持不变，禁止使用 `max(reference, 1)` 这类带绝对单位的
  floor。`Pxx/Pyy` 分别以自身有限最大值为 reference，H2 的 `|Pxy|` 以自身有限最大值
  为 reference，阈值为 `factor · eps · reference`；`factor` 是算法常量并由测试固定。
  coherence 先按 `Pxx/Pyy/Pxy` 各自 reference 归一化后再做比值，避免谱量很小/很大时
  product underflow/overflow；输入、输出同时乘 `1e-12` 或 `1e12` 时，有效 H/coherence
  mask 与数值必须在浮点容差内不变；
- 分母无效的 bin 输出 `H=NaN+1j·NaN`、`coherence=NaN`，记录 invalid-bin 数量；
- 不能静默产生 Inf；
- 有效 coherence 因舍入略超 `[0,1]` 时 clip 到 `[0,1]`，原始超差超过容差则告警。

### 6.7 派生显示量

```text
magnitude_linear = abs(H)
magnitude_db = 20 · log10(max(abs(H), tiny))
phase_wrapped_deg = angle(H, deg=True)
phase_unwrapped_deg = rad2deg(unwrap(angle(H)))
```

- `tiny` 只用于有效的零幅值转 dB floor；无效 bin 继续是 NaN；
- unwrap 按连续有限区段分别执行，不跨 NaN gap；
- 相干性阈值是 display-only；不得改变 `H`、phase 或导出行；
- FRF dB reference 固定为 1 ratio-unit，不能进入现有绝对 `db_reference` catalog；
- 单位显示为 `output_unit / input_unit`。输入输出同单位时仍显示 ratio，可在标签上简写
  为 `1`，但 manifest 保留原始单位；
- 首版 `保留系统延迟=True` 且不可关闭。自动 delay fit/removal 延期。

### 6.8 参数与结果 DTO

建议放在 `mf4_analyzer/signal/frf.py`：

```python
@dataclass(frozen=True)
class FrfParams:
    estimator: Literal["h1", "h2"] = "h1"
    t_win_s: float = 2.0
    overlap: float = 0.5
    nfft_mode: Literal["auto", "manual"] = "auto"
    nfft: int | None = None
    window: str = "hanning"
    periodic_window: bool = True
    detrend: Literal["constant", "none"] = "constant"

@dataclass(frozen=True)
class FrfResult:
    frequencies: np.ndarray
    transfer: np.ndarray
    pxx: np.ndarray
    pyy: np.ndarray
    pxy: np.ndarray
    coherence: np.ndarray
    effective: FrfEffectiveFacts
    warnings: tuple[str, ...] = ()
```

`FrfEffectiveFacts` 只承载数学层事实：requested/effective segment length、NFFT、
overlap samples、hop、完整段数、Fs、`df`、时间范围、样本数、窗口语义、detrend、
时间抖动和 invalid-bin 数。channel identity 与输入/输出单位由 GUI/Batch adapter 的
context/manifest 组装，不进入 core DTO。`input_time/output_time` 在 core 可选，以支持已知
同步的合成向量测试；生产 GUI/Batch adapter 必须成对传入真实时间轴。所有数组一维、
等长；频率与谱数组为只读或调用方视为不可变。

显示参数不放进 `FrfParams`：`magnitude_scale/frequency_scale/phase_mode/
coherence_threshold/fade_low_coherence` 属于 view params，但从 compute fingerprint 排除。

## 7. NumPy 与 SciPy 对等验证

### 7.1 边界定义

“比肩 SciPy”指：双方使用完全相同的输入、`fs`、显式 window array、`nperseg`、
`noverlap`、`nfft`、detrend、单边和 density scaling 后，NumPy 的
`Pxx/Pyy/Pxy/H1/H2/coherence` 在浮点容差内一致。

不包含：

- 跟随 SciPy 版本变化的默认窗口；
- SciPy 对短数据自动缩窗等隐式策略；
- 不同 NaN policy、不同 detrend 默认值或不同 CSD 方向之间的“自动兼容”。

### 7.2 证据层级

1. **公式级测试**：极小数组用显式 DFT/逐段循环手算，不依赖 SciPy；
2. **golden vectors**：提交固定输入和固定输出摘要/数组，运行环境无 SciPy 也能验证；
3. **可选 reference tests**：`pytest.importorskip("scipy.signal")`，显式传 window 数组，
   建议 `rtol=1e-10, atol=1e-12`，无效 bin 单独比 mask；
4. **物理行为**：纯增益 2、符号反转、已知整数采样延迟、seeded LTI+噪声；
5. **属性**：coherence 有效值位于 `[0,1]`，H1 的纯增益相位方向正确，display-only
   参数不改变原始结果。

SciPy 仅允许存在于测试依赖/开发环境。`tests/test_signal_no_gui_import.py` 和新增 subprocess
守卫必须证明 import `mf4_analyzer.signal.frf` 不会导入 SciPy、Qt 或 matplotlib。

## 8. 单次分析状态与编排

### 8.1 mode 与页面

- 单次内部 mode：`frf`；
- `Toolbar.mode_changed`、`_MODE_TO_INDEX`、`ChartStack.page_for_mode()`、
  `Inspector.set_mode()`、帮助 guide map 同步注册；
- `ChartStack.analysis_managers['frf']` 使用现有 analysis `MAX_VIEWS=6`；
- 页面使用专用 `PgFrfCanvas`，实现放在 `ui/pg_canvas/frf_canvas.py`；不得把实现放进
  `ui/pg_canvases.py` compatibility façade；
- canvas 包含三个 PlotItem，共享频率 ViewBox X 范围，支持 empty/error/progress overlay、
  游标、范围恢复和导出截图所需的稳定 API。

### 8.2 PaneState 与项目持久化

`PaneState` 新增：

```python
input_source: ChannelKey | None = None
output_source: ChannelKey | None = None
ylims: dict[str, tuple[float, float]] = field(default_factory=dict)
source_time_view_id: str | None = None
```

FRF 的 canonical role 只来自这两个字段；不得同时复制进 `sources` 形成第二真相源。
其他分析继续使用 `sources`，Order 继续使用 `rpm_source`。FRF 的 `ylims` keys 固定为
`magnitude/phase/coherence`，旧的单值 `ylim` 保持兼容；共享 frequency X 继续使用 `xlim`。
TimeDomain view 增加持久化稳定字符串 `view_id`；duplicate 必须生成新 id，reorder/delete
不得改变其余 id，旧项目缺字段时生成。`AnalysisViewState` 同样增加 additive `view_id`，
供 FRF coordinator 以 `(view_id, pane_idx)` 隔离同一 section 下不同 View 的 pane；不得用
会随 reorder 变化的 `view_idx`、单独 `pane_idx` 或进程对象地址冒充稳定 pane identity。

序列化：

- nested analysis view schema `2 → 3`；
- `to_dict/from_dict` 加 `input_source/output_source`；
- 旧 view 无字段时 role/link 得到 `None`、`ylims={}`，无需猜测迁移；
- `project_io.remap_analysis_view_fids()` 同时 remap 两端；
- 关闭文件、rebuild、clear 和 project restore 对两端对称处理；
- 保存数值结果仍不是项目职责：重开后按 pair + params 重新计算；
- `current_mode='frf'` 的恢复仍必须经 `toolbar._set_mode()`，保持 Toolbar/ChartStack/
  Inspector 一致。

### 8.3 双端缓存

新增 `FrfCacheKey` / `FrfAnalysisResultCache`，建议仍归
`ui/analysis_cache.py`：

```text
(
  input_fid, input_channel,
  output_fid, output_channel,
  effective_time_range,
  canonical_compute_params_blob
)
```

约束：

- display-only 字段不进 key；
- 输入/输出方向不可交换；
- 任一 fid invalidation 都删除关联条目；
- capacity 首版 12；
- lookup、dispatch context 和 completed put 使用同一个 key builder；
- 文件 rebuild/通道编辑/关闭文件/关闭全部均走现有统一 cache invalidation 入口；
- cache 不以 channel display name 或可读 pair label 为身份。

### 8.4 FrfCoordinator

新增 `ui/main_window/frf_coordinator.py`，边界参考现有 `FftTimeCoordinator`：

**拥有**：preflight、pair key、cache lookup、job context、stale-result 抑制、cache put、
dirty 状态和 result event。

**不拥有**：QWidget 值采集、canvas 绘制、toast、文件数据本体、项目 IO。

`AnalysisJobService` 是唯一线程所有者。FRF 使用 section=`frf` 提交任务；计算循环
响应 cancel。不得在 MainWindow 新增 `_frf_thread/_frf_worker/_frf_queue` 等状态簇。

替换语义必须按 pane 记账，不能照抄 FftTimeCoordinator：service 层的
`cancel(section)`/`replace=True` 是 section 级（generation 递增 + 整段队列作废），
`FftTimeCoordinator.request_batch(replace=True)` 也会清空全部 pending——它可以这样做
是因为 fft_time 每次请求都把所有可见 pane 重新覆盖成一个 batch。FRF 的计算是
per-pane 手动触发，单击「计算频响」只提交当前 pane，因此：

- 同 pane 新请求：作废该 pane 的旧 pending context，旧结果不得写 cache 或渲染；
- coordinator candidate 必须带持久化 `AnalysisViewState.view_id` 或显式可哈希
  `pane_key`；缺失稳定 identity 时 fail closed；
- 跨 pane 请求共存：当前 service 在同一个 `frf` section 内仍是 FIFO 串行，不承诺真正
  并发；pane B 的新请求不得取消 pane A 的在途任务，也不得作废其 pending；
- 首版 coordinator 一律普通入队并依赖 per-pane generation 抑制同 pane 旧结果，不调用
  service 级 `replace=True`/`cancel(section)`。旧计算不会被抢占，只是完成后不落缓存、
  不渲染；selective cancellation 属于后续独立的 service 能力。
- （2026-08-09 as-built，优化 Task O3 已取代上一条的“一律普通入队”）条件式取消已
  实现：`request()` 丢弃发起 pane 自己的旧 pending 后，当且仅当 `_pending` 为空
  **且** `is_running('frf')` 为真（确实存在可取消的物理旧任务）时以 `replace=True`
  提交，立即抢占同 pane 的在途旧计算；否则维持普通入队 + per-pane 抑制。跨 pane
  存在任何 pending 时永不触发 section 级取消。被取消任务经 `cancel_check` 走
  failed 路径，service 的 generation 检查拦下迟到信号，coordinator
  `_take_current_pending` 兜底。

### 8.5 参数变更与重算

- compute 参数、pair 或有效时间范围变化：pane 标记“参数已变化，需重新计算”；
- display-only 参数变化：从缓存的 complex result 即时重绘，不派发 job；
- TimeDomain 每个 pan/zoom 事件不得触发 FRF 计算；
- 已关联的 TimeDomain 在一次 committed range change 后，只把 FRF 标记 stale；用户点击
  `计算频响` 后才重算；
- View 切换、split、duplicate、restore 的 stale/ready 状态由 view state + cache 决定，
  不用 silent `getattr(..., False)` 补默认。

## 9. TimeDomain 关联合同

### 9.1 关联的是什么

只关联：

- 输入/输出复合 channel identity；
- 物理时间范围 `(t_start_s, t_end_s)`；
- 来源 TimeDomain 的稳定 `ViewState.view_id` 与本次物理范围快照。

绝不关联：TimeDomain X ViewBox 与 FRF frequency ViewBox。秒和 Hz 量纲不同。

### 9.2 `使用当前时域范围`

启用条件：

- 当前 TimeDomain view 的 X source 是物理 time；
- 可得到有限、递增的 committed visible range；
- 该范围与 FRF pair 所在逻辑来源的真实时间范围有非空交集。

行为：

- 捕获物理时间范围快照，经过 shared preprocess 对输入输出应用同一 mask；
- 保留来源 `view_id` 与范围快照；
- 后续时域拖动不自动计算；
- 原 view 切到 custom X 后，关联失效并提示重新选择范围，不把 custom-X 数值当秒。

范围变动监听使用 TimeDomain canvas 已有的 settled `xrange_changed(float, float)`；禁止监听
包含频繁 Y/restore 事件的 `visible_range_changed`，也不新增第二套 quiet timer。若同
`view_id` 的 settled physical xlim 与保存快照不同，只标记关联 FRF pane stale，不自动
提交计算。

若当前 TimeDomain 使用 custom X，按钮禁用并显示：
“当前时域横轴不是物理时间，无法作为 FRF 时间范围；请切回时间轴或手动输入秒范围。”

### 9.3 `在时域查看`

该动作不覆盖用户已有的无关时域 View：

1. 查找已有 signature=`(input key, output key, effective time range)` 的 FRF 专用时域 View；
2. 有则复用；无则创建 `频响 · <output>/<input>` View；
3. 只加入准确的输入/输出两通道，使用物理 time X，应用 FRF 的有效时间范围；
4. 切到 `time` mode，并保持 pair 颜色/图例可辨；
5. 若 TimeDomain 已到 12 View 上限，则不覆盖现有 View，提示用户先关闭一个 View。

该 dedicated View 使用 composite identities，不能因同名通道折叠；来源关闭时按现有 View
清理契约处理。

## 10. Batch FRF 配置接口

### 10.1 配对模型

必须区分 portable 用户意图与 runtime identity。

建议在 `batch_types.py` 增加：

```python
@dataclass(frozen=True)
class FrfPairRule:
    input_channel: str
    output_channels: tuple[str, ...]

@dataclass(frozen=True)
class ResolvedFrfTask:
    source_id: object
    group_identity: str
    input_channel: str
    output_channel: str

@dataclass(frozen=True)
class FrfExecutionPlan:
    tasks: tuple[ResolvedFrfTask, ...]
    issues: tuple[object, ...] = ()
    estimated: bool = True
```

`AnalysisPreset` 增加：

```python
frf_pair_rules: tuple[FrfPairRule, ...] = ()  # portable only
```

禁止复用 `target_pairs`：它当前的稳定含义是 `(source, channel)`，改义会破坏已有 Batch
调用者和 lessons 中的 preview/run identity 契约。resolved tasks 由 resolver 作为独立
immutable execution plan 返回，不能长期写回 mutable preset 形成第二真相源。

### 10.2 Batch UI

InputPanel 在 method=`frf` 时把普通“目标信号”区切换为“输入 / 输出配对”：

- 每个配对组选择一个输入；
- 输出为显式多选；
- `+ 添加配对组` 支持不同输入；
- 输入不能出现在自身输出集合；
- 相同 `(input, output)` 去重并在 UI 标识；
- 显示每个来源可解析任务数、缺失输入、缺失输出；
- 默认 `target_policy='common'`：所选每个逻辑来源都必须具有完整 pair；
- 可选 `available_per_source`：仅在同一来源内两端都存在时展开，并把缺失记为明确
  warning/skip 统计；不得静默消失。

AnalysisPanel 显示 FRF 参数；OutputPanel 显示：

- 数据列预览；
- 图片组织：`每对一张`（默认）、`按来源叠加`、`按输入/输出对叠加`；
- 文件名预览：`source__output-over-input__frf__hash`；
- 预计 task / data artifact / image group / conflict 数量。

Batch 方法按钮同样显示：`时域 / 频谱 / 时频 / 频响 / 阶次`，保持等宽。

### 10.3 preset 持久化

`batch_preset_io.py` 继续写 portable schema v1 的 additive 字段：

```json
{
  "schema_version": 1,
  "method": "frf",
  "frf_pair_rules": [
    {"input_channel": "TorqueCmd", "output_channels": ["Torque", "Angle"]}
  ]
}
```

- `resolved_frf_tasks`、source ids、paths、logical-source identity 和 probe cache 不持久化；
- 老 preset 没有 `frf_pair_rules` 时行为不变；
- 老程序读取 method=`frf` 会按当前 unsupported-method 路径跳过，不误当 FFT；
- FRF 不持久化现有 `db_reference` 字段；若导入手写值，normalizer 丢弃并给 warning，
  防止绝对 reference 被误解为传递比 reference。

### 10.4 task 展开与 preflight

运行顺序：

1. 绑定 physical locator、logical source descriptor 和 group identity；
2. 用 metadata-cost channel inventory 解析 pair rules；
3. 生成稳定、有序但可能标 `estimated` 的 `FrfExecutionPlan`；
4. 正式 run 执行 full load，并在尚未写出时对真实 time arrays、Fs、范围和段数做 data
   preflight；
5. 以最终 effective task universe/identity 一次性预留该 run 的完整 artifact set；
6. 计算、写出、checksum、publish。

展开顺序固定为：用户 pair-rule 顺序 → output 顺序 → selected logical-source 顺序；任务 id
不依赖枚举顺序。preview 与 run 共用 resolver，不各写一套。

`preview_outputs()` 不加载数据，只用已探测 descriptors；缺 descriptor 时返回 estimated 并
显示未知项，绝不升级到 full-cost load。preview 不能声称真实 timebase/Fs/段数已验证。
代表性图片预览只加载被明确选中的一个 representative task，并走与 run 相同的
data-preflight/compute/render path。

### 10.5 Batch validation

每个 task 必须：

- input/output 在同一个 logical source；
- 两通道都存在且不同；
- 两端真实 time arrays 等长、逐点一致、uniform，并得到同一 Fs；
- 应用同一 time range 后至少有 2 个完整段；
- 参数满足 §6；
- 输出路径和 task identity 已解析。

用户/数据问题进入明确 item status：`failed` 或 policy 允许时的 `skipped`，消息包含来源、
input、output 和修复建议。程序错误、非预期 ImportError 和 renderer bug 继续抛出，不降级
成“某个通道失败”。

## 11. Batch 计算、身份、导出与渲染

### 11.1 计算归属

- `signal/frf.py`：唯一数学实现；
- `batch_compute.py`：把 LoadedSource + pair + recipe 转换为核心输入并调用数学实现；
- GUI coordinator 也调用同一核心，不复制公式；
- `batch.py` 只编排；所有进度与 result record 继续经 `_RunReporter`。

### 11.2 task identity

FRF 身份分三层：

1. `compute_fingerprint`：只含输入/输出复合身份和 compute params，排除 display-only，
   用于计算结果复用；
2. `task/artifact_id`：沿用现有 CSV/XLSX+PNG coordinated reservation，包含所有会改变
   任一请求产物字节的 recipe/output fields；
3. `render_group_id`：成员集合（含 pair direction）+ render params。

coordinated task/artifact fingerprint 至少包含：

```text
source_identity
group_identity
input_channel_identity
output_channel_identity
method = frf
normalized_compute_recipe
```

输入/输出有方向，`A→B` 与 `B→A` 必须得到不同 task/artifact id。display-only 选项不进入
`compute_fingerprint`，但只要会改变同一次 coordinated artifact set 中的 PNG 字节，就必须
进入 `task/artifact_id` 和相应 `render_group_id`。除非未来把数据/图片 reservation 与 stem
彻底拆分，否则数据文件名随这类输出 recipe 变化是可接受的；不得把现 `task_id` 称为
pure compute identity。

`TaskOutputIdentity` 可 additive 增加 `input_channel_identity/output_channel_identity`，或新增
`build_frf_task_output_identity()`；现有 `build_task_output_identity()` 行为和公共 import 保持。

可读 stem：

```text
<source>[__<group>]__<output>-over-<input>__frf__<task_id[:8]>
```

可读 stem 只用于展示；碰撞、重试和 resume 都以 canonical id 与 checksum 为准。写出前一次
预留 CSV+PNG+manifest 所需完整集合，沿用现有 atomic publish/rollback。

### 11.3 BatchItemResult 与 manifest

`BatchItemResult` additive 增加：

```python
input_signal: str = ""
output_signal: str = ""
```

FRF item 的 legacy `signal` 填可读 pair label `<output> / <input>`，以保持现有任务列表和
progress UI 可用；身份逻辑不得反向解析该字符串。

manifest schema v1 保留，FRF entry 添加可选结构：

```json
"frf_pair": {
  "input": {"channel": "...", "unit": "..."},
  "output": {"channel": "...", "unit": "..."}
}
```

同时保留现有 required `channel`，其值为 pair label。loader 对 method=`frf` 校验
`frf_pair`；非 FRF entry 完全不受影响。resume matching 使用 `task_id + source identity +
recipe fingerprint + checksum`，不靠 pair label。

`effective_facts` 增加 estimator、actual Fs、nperseg/nfft、segments、overlap samples、df、
time range、jitter、invalid bins 和窗口周期性。

### 11.4 数据输出

每个 SISO task 一份数据表（沿用现有 Batch 数据格式选择：CSV/XLSX 走同一
`write_dataframe` 列契约），固定列：

```text
frequency_hz
transfer_real
transfer_imag
magnitude_linear
magnitude_db
phase_deg_wrapped
phase_deg_unwrapped
coherence
pxx
pyy
pxy_real
pxy_imag
```

列顺序稳定。文件/manifest metadata 保存 input/output name、unit、source/group identity 和
effective facts。相干阈值、淡化和 log X 不过滤数据行。非有限数沿用现有严格 JSON/CSV
约定，不用字符串伪造可计算数字。

### 11.5 render DTO 与图片

在 `batch_render_models.py` 增加 GUI-free DTO，例如：

```python
@dataclass(frozen=True)
class BatchFrfSeries:
    frequency_hz: np.ndarray
    transfer: np.ndarray
    coherence: np.ndarray
    label: str
    input_unit: str = ""
    output_unit: str = ""

@dataclass(frozen=True)
class BatchFrfFigureSpec:
    series: tuple[BatchFrfSeries, ...]
    magnitude_scale: str = "db"
    frequency_scale: str = "log"
    phase_mode: str = "unwrapped"
    coherence_threshold: float = 0.8
```

构造时验证数组一维等长、频率单调、transfer complex、coherence shape；不 import Qt。

`batch_grouping.py:RenderTask/_member_identity/group_render_tasks` 与
`batch_output.py:GroupOutputIdentity/build_group_output_identity` 同步扩展 pair-aware identity，
由 GUI-free Batch identity owner 完成；Qt renderer 只消费定稿 DTO，不能从可读 label 反推
input/output。Qt renderer 新增 kind=`frf` 三联图：

- 标题显示来源和 `output / input`；
- 页脚 effective facts 包括 H1/H2、window、NFFT、segments、Fs；
- 三图共享 X，颜色在同一页按 series 一致；
- 相干阈值线和低相干淡化与单次 canvas 语义一致；
- `none`：一对一页；`source`：同一来源的多输出叠加；`channel`：同名 pair 跨来源叠加；
- grouped page 的成员 identity 是 `(source, group, input, output)`，不是单 channel；
- 不增加 matplotlib runtime dependency。

## 12. 参数归属与 recipe normalization

`batch_recipe.py` 增加 method=`frf` 的字段白名单。

**Compute fields**：

```text
time_range, fs,
estimator, window, periodic_window,
t_win_s, overlap, nfft_mode, nfft, detrend
```

**Render/output fingerprint fields**：

```text
magnitude_scale, frequency_scale, phase_mode,
coherence_threshold, fade_low_coherence,
x/y ranges, tick density, font scale, render_group_by
```

**明确排除**：`weighting`、`db_reference`、`db_reference_mode`、Order RPM fields、heatmap
slice fields、time custom-X fields。方法切换时已知但不归 FRF 的字段按现有 normalizer 契约
丢弃；未知未来字段继续 round-trip。

GUI cache fingerprint 只使用 compute fields；Batch normalized recipe 必须包含所有会改变数据
或输出字节的字段，以保证 resume 和冲突判定正确。

## 13. 错误、告警与可观测性

| 级别 | 例子 | 单次 UI | Batch |
| --- | --- | --- | --- |
| 阻断 | 来源不同、时间不一致、Fs 不一致、完整段不足 2 | 不派发，字段旁说明 + toast | item failed / preflight issue |
| 可计算告警 | 只有 2–3 段、很多 zero-excitation bins、时间抖动接近容差 | 图仍显示，事实区/状态栏告警 | item done + warnings |
| display warning | log X 隐藏 DC、低相干淡化 | 图例/tooltip | report facts |
| 基础设施失败 | 输出 reservation/publish、可识别 optional renderer 缺失 | 日志 + 可操作提示 | degraded/failed，遵循现 taxonomy |
| 编程错误 | shape contract bug、非预期 ImportError、Qt thread violation | 沿用共享 worker 限制：在 worker seam 记录 traceback 并发出失败；FRF 外层不得再 broad-catch | Batch 传播，不伪装数据失败 |

进度：GUI 以已完成段/总段映射到现有 AnalysisJobService；Batch 任务内计算进度可更新当前
task message，但 task start/done/failed/cancelled 的单一记录者仍是 `_RunReporter`。
`AnalysisComputeWorker` 捕获异常并发字符串是现有全分析共享的兼容限制，本功能不单独改成
typed selective propagation；但 worker 必须记录 traceback，使失败保持可观测。

## 14. 兼容与迁移

- 现有内部 keys `fft/fft_time/order_time` 不改；只增加 `frf`；
- 顶部和 Batch 可见标签改名不迁移 preset/project；
- `AnalysisViewState` schema bump 是 additive，旧项目正常加载；
- batch preset schema v1 additive 字段，旧 preset 正常加载；
- manifest v1 保留 required fields，FRF 使用 method-gated additive `frf_pair`；
- `target_pairs` 语义不改；现有 `signal/target_signals` 路径不改；
- `BatchItemResult.signal` 与旧公共 import 保留；
- `batch.py` 继续 re-export batch contracts；
- `ui/pg_canvases.py`、`batch_render.py` façade 只做必要 re-export，不承载新实现；
- Windows hidden imports、help datas 和 packaging tests 增加新模块/guide；
- 本功能不要求修改历史 spec/plan/acquisition records 的版本文字。

## 15. 验收矩阵

| ID | 场景 | 必须证据 |
| --- | --- | --- |
| N1 | 纯增益 `y=2x` | H1 幅值 2、0°、高相干；unit test |
| N2 | `y=-x` | 幅值 1、±180°；相位方向 unit test |
| N3 | 已知整数采样延迟 | 线性相位斜率符号/量值正确；unit test |
| N4 | H1/H2 + seeded noise | 与定义和 SciPy reference 一致 |
| N5 | PSD/CSD scale | 手算 DFT + explicit SciPy window parity |
| N6 | zero excitation | 无 Inf；NaN mask + invalid-bin warning |
| N7 | short/nonfinite/shape/dtype | §6.2/6.3 每一分支有测试 |
| N8 | multirate/unaligned time | 明确阻断，无 min-length/静默插值 |
| N9 | NumPy-only import | subprocess 不导入 SciPy/Qt/matplotlib |
| U1 | 五个模式名 | Toolbar/Batch labels 全中文等长，内部 key 不变 |
| U2 | FRF 三联图 | 共享 frequency X、游标、dB/phase/coherence 切换 |
| U3 | display-only change | 零 worker dispatch，原始 complex result 不变 |
| U4 | compute change | pane stale，点击计算后新 key/job/result |
| U5 | analysis View | create/duplicate/split/delete/limit/restore 全覆盖 |
| U6 | project restore | pair remap、mode 同步、重算、缺来源提示 |
| T1 | 使用当前时域范围 | 物理 time 有效；custom X 禁用并说明 |
| T2 | 时域范围变动 | 只标 stale，不随 pan 连续计算 |
| T3 | 在时域查看 | dedicated View 精确 pair/range，不覆盖无关 View |
| B1 | 一输入多输出 | 按规则稳定展开 SISO tasks，无隐式笛卡尔积 |
| B2 | source/channel 缺失 policy | common 阻断；available 明确 skip/warning |
| B3 | preview/run identity | descriptors 绑定后 task/group ids 完全相同 |
| B4 | portable preset | 不含 source ids/paths/resolved tasks |
| B5 | output identity | input/output 方向、source/group/recipe 全入 hash |
| B6 | 数据表 | 固定 12 列（CSV/XLSX 同契约）、raw bins 不因 display filter 丢失 |
| B7 | PNG | 三联图单对与两种 grouped render deterministic |
| B8 | manifest/resume | frf_pair 可审计；checksum/id 严格匹配 |
| A1 | import boundaries | neutral modules 无 UI/Qt renderer/SciPy import |
| A2 | orchestration ownership | GUI 复用 AnalysisJobService；Batch 复用 `_RunReporter` |
| A3 | source identity | 同名通道/分裂来源不折叠，任一 fid cache invalidation 对称 |
| D1 | help/hints/quickref | 五模式和 FRF 交互同步，guide 可在 frozen 路径解析 |
| V1 | offscreen real render | 单次/Batch 目标分辨率自动截图与目标稿差异报告 |
| V2 | macOS foreground | 实际 TraceLab 配对、计算、切换、时域回看人工/自动证据 |
| V3 | Windows frozen | Full/Lite 新鲜 EXE 的 import、帮助、Batch FRF 验收；未跑必须标 UNKNOWN |

## 16. Definition of Done

- N1–N9、U1–U6、T1–T3、B1–B8、A1–A3、D1 都有具名自动测试；
- GUI 与 Batch 调用同一个 `signal/frf.py` 数学实现；
- 无 SciPy/matplotlib 新运行依赖，无新 QThread pump，无第二个 Batch reporter；
- 不存在 `min(len(input), len(output))`、synthesized time 或 silent resample；
- preset/project/manifest 的新增身份字段按本文迁移并有旧数据回归；
- 单次和 Batch real-render 自动对比，不要求用户逐张人工找差异；
- macOS foreground 与 Windows frozen 状态分级报告，未执行的 gate 明确 `UNVERIFIED/UNKNOWN`；
- `git diff --check`、相关 import boundaries、state ownership 和 Batch reporter gates 全绿；
- 实施完成前不得把本 spec 状态改成 Implemented。

## 17. 已确认的设计稿证据

设计阶段已有两张 1600×1000 HTML 目标稿：

- `.state/system-identification-ui-prototype/index.html`：单次 FRF 三联图与 Inspector；
- `.state/system-identification-ui-prototype/batch-frf.html`：Batch 配对组、五方法与输出组织。

两者浏览器实际渲染时 console 为 0 error / 0 warning。它们只证明布局方向和信息层级，
不证明 PyQt/pyqtgraph 前台实现、数值正确性或 Windows frozen 可用；实施时以本 spec 的
产品合同为准，并用真实 Qt widget path 重新生成证据。

已知的原型 ↔ spec 偏差（实施时以 spec 为准，不得照抄原型）：

- 单次稿：`分析范围` 画成单个“使用选定时间范围”复选框，spec §5.3 要求
  全范围 / 使用当前时域范围 / 手动范围三选；`在时域查看` 次按钮缺失（原型只有画布
  上方的“时域预览”入口，位置与 §5.3 不同）；estimator 只展示了 H1 选中态，H2 必须
  按 §5.3 可选并可见；通道映射控件未按“来源名 · 通道名 [单位]”展示。
- Batch 稿：图片组织只画了“每对一图 / 按来源叠加”两项，缺 §10.2 的
  “按输入/输出对叠加”；出现 spec 未定义的“平均模式”下拉——首版不实现，平均方式
  固定为 Welch 线性平均；数据列预览与 §11.4 的 12 列不一致（缺
  `pxy_real/pxy_imag`，phase 未区分 wrapped/unwrapped）；“数据文件 XLSX”只是当前
  数据格式选择的一个示例，实际沿用现有 Batch CSV/XLSX 选项。
