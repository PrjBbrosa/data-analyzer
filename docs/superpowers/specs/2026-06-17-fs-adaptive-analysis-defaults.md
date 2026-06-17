# 分析默认值「随采样率/数据自适应」设计

状态：草案（已与用户对齐 A/B/C + 预设携带 T_win + 扭矩改 dB）
日期：2026-06-17
对应 plan：`docs/superpowers/plans/2026-06-17-fs-adaptive-analysis-defaults.md`
验证数据：`D:\1. work\P779_S92_260616`（7 个 S92 EPS 文件）

## 背景（实测证据）

用上述 7 个真实 MF4 跑了一遍各 section 的默认参数（脱 GUI 调
`signal/fft.py`、`signal/spectrogram.py`）：

- 数据全是 **~92–100 Hz** 的 EPS RTE 信号（Nyquist 仅 ~46–50 Hz），
  27–136 s，14 通道（电机扭矩/转速/转角）。
- **频谱能量几乎全在 0–1 Hz**：95% 能量分别落在 < 0.21 / 0.67 / 1.25 Hz；
  主峰全部 < 1 Hz。
- **时频图默认 nfft=1024** 在 96 Hz 下 = **窗长 10.7 s、时间步 2.1 s，整段
  仅 9–57 帧**（最短文件只有 9 列）→ 时间分辨率太粗；Δf=0.09 Hz 又是对
  0–2 Hz 内容的极度浪费。预设里更狠（nfft 2048/4096 → 窗 21–43 s）。
- **FFT 谱 + 时频图默认频率显示范围 = 0–Nyquist**，能量全挤在最左 ~2–3%，
  看上去就是 0 处一根针。
- **Order/COT 对本数据本质不适用**：电机转速 ±1700 rpm、**符号反转 ~93 次**
  （Center）、**16–29% 时间 |rpm|<50**，角度非单调 + 近零不稳定。

结论：默认值「能算」但「显示不好 / 时频太粗 / 阶次不适用」。本设计让默认
值随 **采样率 fs、数据长度 N、实际能量分布** 自适应。**手动挡一律保留**
（复用现有的「自动」nfft 选项与坐标轴 auto 开关，自适应只是更聪明的默认）。

## A. 频率显示范围自适应（FFT 谱 X 轴 + 时频图频率轴）

仅当对应坐标轴处于 **auto** 时生效；纯显示、不重算、可逆。算完拿到
单边幅值谱后：

```
忽略 DC（freq > 0）
cum = cumsum(amp**2); 归一
f_e = 累计能量到 98% 处的频率
f_max = min(Nyquist, max(f_e * 4.0, 2.0Hz))   # ×4 余量，2Hz 下限防过度放大
f_max = nice_ceil(f_max)                        # 取整到 1/2/5×10ⁿ
显示范围 = [0, f_max]
```

- 本数据 → f98 ≈ 1–1.3 Hz → 显示约 0–5 Hz。
- 宽带/噪声谱 → f_e 接近 Nyquist → 自动退回近全量程，不误伤。
- 纯函数 `energy_band_fmax(freq, amp, *, p=0.98, headroom=4.0, floor_hz=2.0)`
  放 `signal/` 层，单测覆盖（窄带 / 宽带 / 全 DC / 单 bin 边界）。
- 现状：FFT 谱用 `chk_x_auto`+X 范围，时频图用 `chk_y_auto`+频率(Y)范围，
  auto 时 `spin_freq_max==0.0` 哨兵解析为 Nyquist（在 main_window 渲染路径）。
  本特性把该哨兵的「auto 上界」从 Nyquist 改成 `energy_band_fmax(...)`。

## B. nfft 随 fs 自适应（时频图为主，FFT 谱的 Welch 段同理）

核心：**盯目标窗时长 T_win，而不是固定 bin 数**。

```
def resolve_nfft(fs, n_samples, t_win_s, overlap,
                 *, floor=64, ceil=8192, min_frames=24, max_window_frac=0.15):
    nfft = ceil_pow2(fs * t_win_s)           # 1 kHz × 1.5 s => 2048
    while frames(nfft, overlap, n_samples) < min_frames and nfft > floor:
        nfft //= 2
    while nfft > max_window_frac * n_samples and nfft > floor:
        nfft //= 2
    return clamp(nfft, floor, ceil)
```

随 fs 缩放效果：96 Hz × 1.5 s → 128–256；1 kHz × 1.5 s → 2048；5 kHz → 8192 封顶。

- 纯函数 `resolve_nfft` + `ceil_pow2` 放 `signal/` 层，单测覆盖
  （低/高 fs、短记录触发护栏、下限封顶）。
- **FFT-vs-Time 的 `combo_nfft` 增加「自动」项并设为默认**（FFT 谱的
  `combo_nfft` 已有「自动」=整段，保持）。当 nfft==自动 时，**计算时**用
  当前 fs + N + 该 section 的 T_win 解析 nfft。
- 「自动」是**活的**：换 fs 不同的文件直接重算时再适配，不必重点预设。
- 合并段标题摘要显示解析值，如 `自动(256) · hanning · 75%`。
- 裸默认（没点任何预设）也走「自动」，用振动类的 **1.5 s** 作通用 T_win，
  保证默认不再出现 10.7 s 窗。

## 预设携带 T_win（替换写死 nfft）+ 扭矩改 dB

三类预设的 nfft 现在写死（FFT: 4096/2048/1024；Order: 4096/4096/1024），
改成存**目标窗时长 T_win**，由 `resolve_nfft` 在应用/计算时按 fs 解析。
相对的长/中/短关系保留、但不再被采样率绑死：

| 预设 | 窗函数 | T_win（→自动nfft） | 重叠 | 幅值轴 | 平均模式 |
|---|---|---|---|---|---|
| 扭矩类 | flattop | ~2.5 s（长） | 75% | **dB（由 Linear 改）** | 线性平均 |
| 振动类 | hanning | ~1.5 s（中） | 50% | dB | 线性平均 |
| 启停类 | hanning | ~0.6 s（短） | 75% | dB | 峰值保持 |

- **三类的区分点**变为：窗函数（flattop/hanning）+ 窗长（长/中/短）+
  平均模式（线性平均/峰值保持）+ 重叠。幅值轴统一 dB。
- **扭矩类幅值统一改 dB**：FFT 谱 `amp_y='dB'`；FFT-vs-Time 与 Order 预设里
  扭矩的 `amplitude_mode` 由 `'Amplitude'` 改 `'Amplitude dB'`。
- 预设存储 schema 增加 `t_win_s`（保留 `nfft` 字段可空/为 '自动' 以兼容旧
  存档；读到旧的固定 nfft 仍照旧应用，不破坏已保存的用户预设）。
- **Order 的 nfft 是角度域采样数**（与 fs×时间 无关），**不套 T_win**；
  Order 预设只改扭矩幅值为 dB，nfft 维持现状（且 Order 对本数据不适用，
  优先级低）。
- 摘要解析后显示，如 `自动·扭矩(256) · flattop · 75%`。

## C. 阶次「不适用」识别

阶次无法靠调参救，只能识别 + 提示（不阻塞）：

```
def assess_speed_for_order(rpm):
    peak = max(|rpm|)
    near0 = mean(|rpm| < max(50.0, 0.05*peak))
    flips = 符号反转次数(sign(rpm) 的跳变)
    if flips > 3 or near0 > 0.2:
        return (False, "转速反向/近零，阶次分析可能无意义；"
                       "请选单向稳定的转速段，或改用 FFT / 时频图")
    return (True, "")
```

- 纯函数放 `signal/order*.py` 或 `signal/` 层，单测覆盖。
- 接到 `OrderContextual`：选定转速/tacho 通道后（或点「时间-阶次」前）评估，
  **非阻塞提示**（复用现有 `acknowledged`/toast 或面板内联 label）。
  **暂不置灰**计算按钮（后续要再加）。
- 本批转向数据 → 全部触发提示。

## 非目标 / Out of scope

- 不改各分析的数值算法本身（FFT / STFT / COT 内核不动）。
- 不动时域 section。
- 不重构刚完成的合并段结构；本特性往里填默认值/摘要解析。
- 不强制阶次禁用（仅提示）。

## 验收标准

- A：FFT 谱与时频图在 auto 频率轴下，默认显示范围按能量收窄（本数据 ≈ 0–5 Hz），
  宽带数据退回近 Nyquist；手填范围不受影响。
- B：时频图 nfft 默认「自动」，96 Hz 数据解析到 128–256（窗 1–3 s、帧数 ≥ ~24）；
  1 kHz 解析到 2048；摘要显示解析值；换文件自动再适配。
- 预设：三类按 T_win 解析 nfft、相对长/中/短关系正确；扭矩幅值为 dB；
  旧存档预设仍可加载。
- C：转速反向/近零的数据触发提示；单向稳定转速不触发。
- 纯函数（energy_band_fmax / resolve_nfft / assess_speed_for_order）有单测；
  既有 inspector / main_window 测试不回归。
- 用 `D:\1. work\P779_S92_260616` 复跑验证脚本，确认显示效果改善。
