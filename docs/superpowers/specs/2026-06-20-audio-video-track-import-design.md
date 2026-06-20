# 音视频音轨导入 + A 计权频域分析 — 设计规格

- **日期**：2026-06-20
- **状态**：设计已确认，待写实施计划（writing-plans）
- **范围**：在 MF4 Data Analyzer 中支持 mp4/mp3/mov 等音视频文件的**音轨导入**，并为 FFT / FFT vs Time / Order 三个分析增加 **A 计权（IEC 61672）** 选项；识别到音视频文件时三个默认预设智能带上 A 计权。

---

## 1. 背景与目标

用户需要分析音视频文件**音轨**上的信息（如发动机声、NVH 录音）。核心洞察：

> 音频本质就是高采样率的单（或双）通道时间序列。现有 `FileData`（pandas DataFrame，列=通道，行=采样，标量 `fs`）天然兼容——`fs` 可为任意 float，立体声=两列。频域分析（FFT/阶次/滤波/加窗）可**直接复用**，唯一缺口是声学领域的 **A 计权**。

三个目标：

1. **导入**：把音视频文件的音轨解码为普通信号通道，进入现有 `FileData` 模型。
2. **A 计权**：给 FFT、FFT vs Time（频谱图）、Order（阶次）三个分析各加一个频率加权开关（None / A）。
3. **智能默认**：识别到音视频文件时，三个默认预设（频率优先/均衡/时间优先）的默认加权选择自动为 A 计权，用户可手动关掉。

### 1.1 关键标定限制（已与用户确认）

PCM 音频（来自 mp4/mp3/mov）**没有声压标定**。因此本设计只产出**相对加权频谱**与**相对 dBFS(A)**，**不**产出绝对 dB SPL（如"75 dB(A)"）。v1 不提供标定输入、不提供总声级数字。

---

## 2. 范围

### 2.1 纳入（v1）

- mp4 / mov / mkv / m4v（取音轨）、mp3 / m4a / aac / wav / flac（音频）导入。
- A 计权（仅 A）作为 FFT / FFT vs Time / Order 的可选项。
- 相对加权频谱 / 相对 dBFS(A)。
- 音视频文件智能默认 A 计权（三个预设、三个分析）。
- 短片段全量加载（秒~几分钟），不降采样、不分块。
- 批处理（`batch.py`）同步支持音视频导入。

### 2.2 排除（非目标）

- ❌ 绝对 dB SPL、标定输入、总声级数字。
- ❌ C / Z 计权、心理声学指标（响度/尖锐度/粗糙度）、1/3 倍频程。`weighting` 字段设计为字符串（`'None'`/`'A'`）以便未来零成本扩展 C/Z，但 v1 不实现。
- ❌ 视频画面分析——只取音轨，视频流忽略。
- ❌ 流式/分块加载、音频重采样到统一 fs（保留原生 fs）。

---

## 3. 架构总览

```
[音视频文件] --PyAV解码--> [DataLoader.load_audio_video]
        |                         |
        |                  (df, channels, units, fs, source_metadata{source_kind:'audio'})
        v                         v
   _load_one 分派 ----------> _register_file_data(fs=, source_metadata=)
                                  |
                                  v
                          FileData(fs 显式, is_audio_source()=True)
                                  |
              选中信号 -> _on_inspector_signal_changed
                                  |  (检测 is_audio_source)
                                  v
        三个 contextual 的 weighting 组合框默认置 'A'（智能默认）
                                  |
                   计算 FFT/谱图/阶次 时读 params['weighting']
                                  v
         signal 层挂载 a_weighting_gain_linear(freqs)（dB 转换之前）
                                  |
                                  v
                    相对加权频谱 / 相对 dBFS(A) 显示
```

四个组件：**(A) 音视频导入** · **(B) A 计权数学模块** · **(C) 三分析挂载 A 计权** · **(D) 智能默认**。

---

## 4. 组件 A：音视频音轨导入

### 4.1 依赖：PyAV

`requirements.txt` 新增一行 `av`（PyAV）。理由：

- pip 安装自带预编译 ffmpeg（含解码器），**无需系统装 ffmpeg**，跨平台一致。
- 一个库覆盖全部容器/编码（mp4/mov/mp3/aac/flac/wav…）。
- 成本约 35MB wheel，可接受。
- 备选 `imageio-ffmpeg`（subprocess 调 ffmpeg）更"薄"但需自管进程；`soundfile` 对 mp4/mov 仍需系统 ffmpeg——均不如 PyAV 自洽。

### 4.2 `DataLoader.load_audio_video(fp)`

新增静态方法，文件 `mf4_analyzer/io/loader.py`（与 `load_mf4`/`load_csv`/`load_hdf` 同级，现有方法见 `loader.py:115-276`）。

**签名（返回 5 元组，与 HDF 的富返回同理，而非 csv/mf4 的 3 元组）**：

```python
@staticmethod
def load_audio_video(fp) -> tuple[pd.DataFrame, list[str], dict[str, str], float, dict]:
    """解码音视频文件的音轨为信号通道。
    返回 (data, channels, units, fs, source_metadata)。
    """
```

**实现要点**：

1. 用 `av.open(fp)` 打开容器，取**第一条音频流**（`container.streams.audio[0]`）。无音频流 → 抛 `ValueError("文件不含音轨")`。
2. 逐帧解码，用 `av.AudioResampler` 统一到平面 float32（`format='fltp'`），拼接成 `(n_channels, n_samples)`。
3. `fs = int(stream.rate)`（音频容器头权威记录采样率，**直接信任**，不同于 HEAD-HDF 的采样率歧义）。
4. **通道命名**：mono → `['audio']`；stereo → `['L', 'R']`；>2（如 5.1）→ `['ch0', 'ch1', ...]`。
5. **单位**：全部 `''`（无量纲归一化 PCM，幅值约在 [-1, 1]）。
6. **dtype**：float32 存储（控制内存：5 分钟 48kHz 立体声 float32 ≈ 115MB；float64 会翻倍）。
7. `source_metadata = {'source_kind': 'audio', 'container': <格式>, 'codec': <编码>, 'fs': fs, 'channels': n_channels}`。
8. **全量加载**，不分块（符合"短片段"前提）。

### 4.3 `FileData` 改动

文件 `mf4_analyzer/io/file_data.py`（`class FileData`，`file_data.py:17-34`，现 `__init__(self, fp, df, chs, units, idx=0, *, source_metadata=None, channel_metadata=None, label_suffix="")`，`fs` 默认 1000.0 见 `file_data.py:33`，fs 从时间列中位 dt 推断见 40-44）。

**问题**：音频无时间列，走现有路径会 fallback 到 `fs=1000.0`（错误，音频应为 44100/48000）。

**改动**：

1. `__init__` 增加关键字参数 `fs: float | None = None`。当显式给出（音频路径）时：跳过时间列推断，直接 `self.fs = fs`，`self._time_source = 'audio'`，`time_array = np.arange(n) / fs`。未给出时维持现有行为。
2. 新增方法 `is_audio_source(self) -> bool`：
   ```python
   def is_audio_source(self) -> bool:
       return self.source_metadata.get('source_kind') == 'audio'
   ```
   以**显式标记**为准（比每处重解析扩展名更稳健、可前向兼容），扩展名仅作 loader 内部判定。

### 4.4 UI 文件对话框过滤器 + 分派

文件 `mf4_analyzer/ui/main_window/_project_io_mixin.py`（`ProjectIOMixin`，`open_files_or_project()` 见 24-60，过滤器在 33-34 与 81，`_load_one` 在 123-160，分派 if/elif 在 128-148）。

1. **扩展名过滤器**（33-34、81）：在"所有支持的文件"与分项里加
   `*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac`，并加一项"音视频文件 (*.mp4 *.mov …)"。
2. **`_load_one` 分派**（128-148，现按 `ext.lower()` if/elif，HDF 特殊返回 list）：增加音视频分支：
   ```python
   elif ext in AUDIO_VIDEO_EXTS:
       df, chs, units, fs, smeta = DataLoader.load_audio_video(fp)
       self._register_file_data(fp, df, chs, units, fs=fs, source_metadata=smeta)
   ```
   需确认 `_register_file_data` 接受并透传 `fs`（若不接受则增加该关键字，沿用到 `FileData(fs=...)`）。`AUDIO_VIDEO_EXTS` 常量定义在 `loader.py` 并导入。

### 4.5 `batch.py` 分派修复

文件 `mf4_analyzer/batch.py`（`_default_loader` 在 145-152，**当前硬编码只 `load_mf4`**——既有缺陷，批处理落后 GUI）。

改为按扩展名分派（mf4/mdf/csv/xlsx/xls/hdf/音视频），使音视频在批处理中自动覆盖。BatchRunner 加载在 364-377 走 `self._loader` + `_disk_cache`，分派修好后无需额外改动。

---

## 5. 组件 B：A 计权数学模块

新文件 `mf4_analyzer/signal/weighting.py`（grep 确认全仓**无任何现存加权代码**，全新实现）。

### 5.1 公式（IEC 61672-1 解析式）

```python
R_A(f) = (12194² · f⁴) /
         [ (f² + 20.6²) · √((f² + 107.7²)(f² + 737.9²)) · (f² + 12194²) ]

A(f) [dB] = 20·log10(R_A(f)) − 20·log10(R_A(1000))   # 归一化使 A(1000Hz) = 0
          ≈ 20·log10(R_A(f)) + 2.00            # −20·log10(R_A(1000)) ≈ +2.00 dB
```

极点常数：`f1=20.598997, f2=107.65265, f3=737.86223, f4=12194.217`。
**实现以线性版为准**（`R_A(f)/R_A(1000)`，直接规避上述常数的伪精度）；dB 版仅由线性版取 `20·log10` 得到。

### 5.2 API

```python
def a_weighting_gain_db(freqs: np.ndarray) -> np.ndarray:
    """每频点 A 计权增益（dB），A(1000Hz)=0。f<=0 返回 -inf。向量化。"""

def a_weighting_gain_linear(freqs: np.ndarray) -> np.ndarray:
    """线性乘子 = R_A(f)/R_A(1000) = 10**(dB/20)。f<=0 返回 0。向量化。"""
```

线性版直接 `R_A(f)/R_A(1000)`，避免 -inf 中间值。各分析在**线性幅值**上乘 `a_weighting_gain_linear`。

### 5.3 边界

- **f=0（DC bin）**：线性增益 0 → 置零 DC。DC 无声学意义，符合预期；FFT 相对 dB 会被 clip 到下限。
- **负频**：单边谱不出现；按 0 处理。
- **Nyquist**：普通高频值，无需特判。

### 5.4 TDD 锚点（IEC 61672 标称表，容差 ±0.2 dB）

| f (Hz) | A (dB) | | f (Hz) | A (dB) |
|---|---|---|---|---|
| 10 | −70.4 | | 1000 | **0.0** |
| 20 | −50.5 | | 2000 | +1.2 |
| 50 | −30.2 | | 2500 | **+1.3**（峰）|
| 100 | −19.1 | | 5000 | +0.5 |
| 200 | −10.9 | | 10000 | −2.5 |
| 500 | −3.2 | | 20000 | −9.3 |

额外断言：`a_weighting_gain_linear(1000)==1`（±1e-3）、`a_weighting_gain_linear(0)==0`、向量输入形状一致、单调性（20Hz→1kHz 递增到峰再降）。

---

## 6. 组件 C：三个分析挂载 A 计权

**统一原则**：A 计权在 **signal 层、线性幅值阶段、dB 转换之前**乘上线性增益。dB 显示模式与 Linear 显示模式因此都自然生效。

**架构判定**：FFT 与 Spectrogram **共享** `one_sided_amplitude()`（`fft.py:77-137`），Order 走角域自己的 `np.fft.rfft`（`order_cot.py:156`）**不共享**。因此**不**改底层 primitive `one_sided_amplitude`（freq 恒定、每帧重算浪费；且 Order 是 RPM 相关的逐帧变权无法统一注入），而是**共享数学模块 + 三处各自挂载**。

### 6.1 FFT

- **计算**：`FFTAnalyzer.compute_fft()`（`fft.py:156-173`）、`compute_averaged_fft()`（181-244）、`compute_peak_hold_fft()`（247-280）。
- **挂载**：给这三个方法加 `weighting='None'` 参数；在**最终幅值**返回前乘 `amp *= a_weighting_gain_linear(freq)`。
  - 数学等价性：A 增益是 per-freq 正常数乘子，与线性平均 `mean(c·xᵢ)=c·mean(xᵢ)`、峰值保持 `max(c·xᵢ)=c·max(xᵢ)`（c>0）**可交换**，故对最终幅值乘一次即可，省算力且等价。
- **不**改 `one_sided_amplitude`（否则 spectrogram 会被重复加权）。
- **dB 显示**：`_fft_mixin.py:268-273`，`20*log10(amp/amp.max())`（相对峰归一）。A 计权后归一到 A 加权后的峰——即**相对 A 加权谱**，符合用户需求。
- **UI 传参**：`_do_fft_single()`（`_fft_mixin.py:207-309`）传 `weighting=fft_params.get('weighting','None')`。
- **计算缓存**：`_fft_compute_cache_params()`（`_fft_mixin.py:64-70`）**必须**纳入 `weighting`，否则切换加权不重算。

### 6.2 FFT vs Time（频谱图 / STFT）

- **计算**：`SpectrogramAnalyzer.compute()`（`spectrogram.py:179-321`），帧循环 284-302 每帧调 `one_sided_amplitude()`，幅值矩阵 `amplitude` 形状 `(freq_bins, frames)`，`freq` 轴恒定（296 行算一次）。
- **挂载**：帧循环**之后**（302 行后），按频率行广播到所有时间列：
  ```python
  if params.weighting == 'A':
      amplitude *= a_weighting_gain_linear(freq)[:, np.newaxis]
  ```
- **dataclass**：`SpectrogramParams`（`spectrogram.py:55-69`）加 `weighting: str = 'None'`。
- **dB 显示**：`amplitude_to_db()`（124-151），`20*log10(amp/db_reference)`，A 计权在其之前完成 → 显示 A 加权谱图。
- **UI 传参**：`FFTTimeContextual.get_params()`（`contextual_fft_time.py:419-480`）加 `weighting=...`。

### 6.3 Order（COT 阶次跟踪）— 逐帧变权（本设计最实质点）

**难点**：A 计权按 **Hz** 定义，阶次轴随**转速变**。只有用每帧 `mean_rpm` 把 order 换算成 Hz 才正确。

- **计算**：`COTOrderAnalyzer.compute()`（`order_cot.py:81-189`），角域逐帧 FFT（146-164），`out_orders`（129-135），`mean_rpm_frame` 每帧可得（**149 行**）。
- **挂载**：帧循环内、`amp_matrix[idx,:]` 填充后（164 行附近）：
  ```python
  if params.weighting == 'A' and mean_rpm_frame > 0:
      order_freqs_hz = out_orders * (mean_rpm_frame / 60.0)   # 阶次→Hz @本帧转速
      amp_matrix[idx, :] *= a_weighting_gain_linear(order_freqs_hz)
  ```
- **dataclass**：`COTParams`（`order_cot.py:23-43`）加 `weighting: str = 'None'`。
- **dB 显示**：在 canvas（`_order_mixin.py`），signal 层返回线性，A 计权在其之前 → 显示 A 加权阶次谱。
- **UI 传参**：`OrderContextual.get_params()`（`contextual_order.py:523-545`）/ `current_params()`（554-576）加 `weighting=...`。
- **音频 × Order 的前提**：Order 分析本就需要 RPM 通道；纯音频文件无 RPM 时 Order 本来就跑不了（既有约束），加权无从谈起。典型有效场景：录音（发动机声）+ 同步 tacho 转速通道，跨文件按 `np.interp` 对齐后逐帧 order→Hz→A 加权。智能默认仍会把 Order 的 weighting 组合框置 'A'（与 RPM 是否存在正交）。

### 6.4 UI 控件（三个 contextual 各加一个加权组合框）

每个 contextual 在谱参数组里加：
```python
self.combo_weighting = QComboBox()
self.combo_weighting.addItems(['None', 'A'])
self.combo_weighting.setToolTip('A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL')
fl.addRow("频率加权:", self.combo_weighting)
```
- FFT：`contextual_fft.py`（谱参数组 124-196；`_collect_preset` 370-392；`current_params` 525-530）。
- FFT vs Time：`contextual_fft_time.py`（时频参数组；`_collect_preset` 719+；`get_params` 419-480）。
- Order：`contextual_order.py`（`_collect_preset` 357+；`get_params`/`current_params` 523-576）。

### 6.5 参数/持久化字段汇总

| 分析 | dataclass / params | 加字段 | 缓存键 |
|---|---|---|---|
| FFT | `current_params()` dict | `weighting:'None'\|'A'` | `_fft_compute_cache_params` 须含 |
| FFT vs Time | `SpectrogramParams`(55-69) | `weighting:str='None'` | 经 params 进结果即可 |
| Order | `COTParams`(23-43) | `weighting:str='None'` | 经 params 进结果即可 |

预设持久化：QSettings JSON `{"name":..,"params":{..}}`（`presets.py:424-447`），加 `weighting` 到 params **向后兼容**（旧预设缺该键 → 默认 `'None'`），不进 .tlproj。

---

## 7. 组件 D：智能默认（音视频 → 三预设带 A 计权）

### 7.1 设计原则

`weighting` 作为**正交轴**：预设负责谱参数（窗/nfft/重叠…），**信号源类型**驱动 weighting 默认值。三个内建预设（`torque/vibration/transient`，定义见 `contextual_fft.py:335-348`、`contextual_fft_time.py:630-658`、`contextual_order.py:325-338`）**不**硬编码 weighting，保持机械域调参不变。

### 7.2 规则（明确、无状态、可预测）

> **选中信号时**：若该信号源文件 `is_audio_source()` → 把对应 contextual 的 weighting 组合框置 `'A'`（智能默认）；否则**不动**该组合框（不清零，避免误伤"MF4 里的麦克风通道想手动开 A"的场景）。
> 用户随时可手动覆盖；覆盖保持到**下次选择事件**重评。此行为与现有"推荐角标随选择重评"（`set_recommended`，`presets.py:505-519`）一致。

权衡（明确写出）：重新选中同一音频信号会再次置 'A'，可能覆盖用户刚关掉的设置——这与推荐角标重评同性质，可接受。

### 7.3 接入点

现有 `_on_inspector_signal_changed(mode, data)`（`window.py:1239-1267`，经 `_unit_for_signal` 取单位，当前 `if mode in ('fft','order')` 调 `set_recommended_for_unit`，**未接 fft_time**）。

扩展：
1. 由选中信号的 `(fid, ch)` 取 `FileData`，调 `fd.is_audio_source()`。
2. 为 **三个** contextual（fft / fft_time / order）各设 weighting 默认：
   ```python
   if fd is not None and fd.is_audio_source():
       self.inspector.fft_ctx.set_weighting_default('A')
       self.inspector.fft_time_ctx.set_weighting_default('A')
       self.inspector.order_ctx.set_weighting_default('A')
   ```
3. 各 contextual 实现 `set_weighting_default(mode)`：仅当处于"未被用户本次覆盖"时设 combo（实现取最简：直接 `combo_weighting.setCurrentText(mode)`，配合 7.2 的重评语义）。
4. **fft_time 选择路径**：当前 `_on_inspector_signal_changed` 未覆盖 fft_time（它有自己的 `combo_sig`，`contextual_fft_time.py`）。实施时需定位 fft_time 的信号变更信号并同样接上——此为实现期一处小核对，非设计悬念。

### 7.4 推荐 slot（保持现状）

音频通道单位多为 `''` → 现有 `recommend_preset_for_unit` 回落到 `'vibration'`（均衡，hanning，时频折中），对音频是合理默认。v1 **不**新增第 4 个音频专用预设（用户要求"考虑当前三个默认预设"），只在三者之上叠加 A 计权默认。

---

## 8. 错误处理

| 情况 | 处理 |
|---|---|
| 文件无音轨 | `load_audio_video` 抛 `ValueError("文件不含音轨")`，UI 弹提示，跳过该文件 |
| 解码失败 / 损坏 | 捕获 `av.AVError`，提示文件名 + 原因，跳过 |
| 未装 PyAV | import 失败时给清晰提示"需 `pip install av`"，不崩溃 |
| Order 无 RPM | 既有约束：Order 本就需 RPM；加权随之不生效，沿用现有"无 RPM"提示 |
| `mean_rpm_frame<=0` | 该帧跳过加权（已被 `min_rpm_floor` 过滤，见 `order_cot.py`）|
| 超大音频（>几分钟）| v1 全量加载；超大文件内存压力以 float32 缓解，必要时提示（流式留后续）|

---

## 9. 测试策略（数值改动 TDD-first）

1. **`weighting.py`**（纯数值，TDD）：§5.4 IEC 锚点 ±0.2dB；1kHz=0；DC 线性=0；向量化；单调性。
2. **FFT 加权**：合成 1kHz 正弦 → 加权后峰值相对不变；100Hz 正弦 → 相对 1kHz 衰减 ≈19dB。
3. **Spectrogram 加权**：多频合成 → 验证每频率行按 `a_weighting_gain_linear(freq)` 缩放，时间维一致广播。
4. **Order 加权**：合成信号 + 恒定 RPM → 已知 order→Hz → 验证对应阶次衰减量。
5. **导入**：用 numpy+`wave` 生成小 wav 夹具测 `load_audio_video`（fs/通道/形状）；若 PyAV 可用再测 mp3/mp4 往返；`pytest.importorskip('av')` 守卫。
6. **智能默认**：构造 `source_kind='audio'` 的 FileData → 选中后三个 contextual 的 combo 变 'A'；非音频不变。
7. **持久化**：weighting 经预设 save/load 往返；旧预设（无 weighting）默认 'None'。
8. **批处理**：`batch.py` 分派覆盖音视频扩展名。

回归：现有 164 个 pytest 用例不得回归（机械域预设无 weighting → 默认 'None' → 行为不变）。

---

## 10. 限制与说明

- **相对加权**，非绝对 dB SPL（无标定）。Tooltip / 文档明示。
- FFT 相对 dB 归一到 A 加权后的峰——是相对 A 加权谱，非绝对级。
- Order 加权依赖每帧 `mean_rpm`，转速噪声会传入加权；低转速帧已被 `min_rpm_floor` 过滤。
- 仅取第一条音频流；多音轨 / 环绕声道按序命名导入，不做下混。

---

## 11. 涉及文件清单（实施定位）

**新增**：`mf4_analyzer/signal/weighting.py`、对应 tests。
**修改**：
- `requirements.txt`（+`av`）
- `mf4_analyzer/io/loader.py`（`load_audio_video` + `AUDIO_VIDEO_EXTS`）
- `mf4_analyzer/io/file_data.py`（`fs` 参数 + `is_audio_source`）
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`（过滤器 + `_load_one` 分派）
- `mf4_analyzer/batch.py`（`_default_loader` 分派修复）
- `mf4_analyzer/signal/fft.py`（FFTAnalyzer 三方法 +weighting）
- `mf4_analyzer/signal/spectrogram.py`（`SpectrogramParams` + compute 广播加权）
- `mf4_analyzer/signal/order_cot.py`（`COTParams` + compute 逐帧加权）
- `mf4_analyzer/ui/main_window/_fft_mixin.py`（传参 + 缓存键）
- `mf4_analyzer/ui/inspector_sections/contextual_fft.py` / `contextual_fft_time.py` / `contextual_order.py`（combo + params + `set_weighting_default`）
- `mf4_analyzer/ui/main_window/window.py`（`_on_inspector_signal_changed` 智能默认接入）

---

## 12. 实施顺序建议（供 writing-plans 细化）

1. `weighting.py` + 测试（纯数值，无依赖，先行）。
2. 导入层：loader + FileData + UI 过滤分派 + batch（可与 1 并行）。
3. 三分析挂载（依赖 1）：FFT → Spectrogram → Order（Order 最复杂，最后）。
4. UI 加权控件 + params/缓存（依赖 3）。
5. 智能默认接入（依赖 2 的 `is_audio_source` 与 4 的 `set_weighting_default`）。
6. 持久化 + 回归 + UI 真机验证（截图）。

> 注：实施期若用户以 squad/团队/重构等关键词触发，数值改动（weighting/FFT/Order）须经 `signal-processing-expert` TDD-first，UI 经 `pyqt-ui-engineer`，并验真机渲染（CLAUDE.md 规则）。
