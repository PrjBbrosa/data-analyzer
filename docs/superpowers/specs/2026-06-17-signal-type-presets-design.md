# 按信号类型的三套分析预设 + 单位自动推荐 — Spec

日期：2026-06-17
状态：已分析（参数经 `signal-processing-expert` 校核，见 §1；交互/单位通路经代码核验，见 §4）
配套 plan：`docs/superpowers/plans/2026-06-17-signal-type-presets.md`

## 0. 范围

三个分析视图的"预设配置"栏（`mf4_analyzer/ui/inspector_sections.py` 的 `PresetBar`，三槽位）：

1. **FFT-1D**（`kind='fft'`，PresetBar 构造在 ~2024）——目前 legacy 模式，三槽空。
2. **FFT 时频图**（`kind='fft_time'`，内置预设 `_BUILTIN_PRESETS` 在 ~3263-3299；改造前 display 名=配置1/2/3）——已是 builtin-aware 模式，但预设与信号类型无关。
3. **阶次**（`kind='order'`，PresetBar 构造在 ~2408）——目前 legacy 模式，三槽空。

用户诉求：把"当前 FFT 和 order 的三个默认配置"精细化，**按时域信号的物理类型**区分，三套覆盖约 90% 机械/动力总成台架工况；并希望按通道单位/幅值自动判别。

不涉及：信号处理算法本身（`signal/fft.py`、`signal/order_cot.py`、`signal/spectrogram.py` 不动）。

## 1. 根因与已确认事实（signal-processing-expert 校核，不要推翻）

### F1 幅值范围 ≠ FFT/阶次参数的决定因素

- **时域幅值量级/动态范围**决定的是**幅值轴**：单位、线性 vs dB、动态范围（dB 跨度）。
- **window / nfft / overlap / max_order / 分辨率**由**频率内容**与**稳态/瞬态**决定，与幅值无关。
- 因此用户"按幅值区分"的直觉，正确的落点是：**幅值/单位作为"这是哪类信号"的识别线索**，再由信号类型一次性带出整套参数（频域分辨率 + 幅值轴）。这是本设计的核心框架。

### F2 三视图预设形状不同（字段名/文案是硬约束，写错会被 `findText` 静默丢弃）

- **FFT-1D 预设无 `remove_mean` 字段**；形状为 `window/nfft/overlap/avg_mode/avg_overlap/amp_y`（`_collect_preset` ~2095-2111）。"去均值"复选框只存在于 FFT 时频图。
- **FFT-1D 幅值轴字段是 `amp_y`，取值英文 `'Linear'`/`'dB'`**（不是中文"线性"）。
- **平均模式 combo 文案是 `单帧 / 线性平均 / 峰值保持`**（用"线性平均"，不是"平均"）。
- **阶次预设无 `window` 字段**——COT 路径内部固定 hanning。
- FFT-1D `overlap` 上限 90%；阶次 `nfft` 下拉 {512,1024,2048,4096,8192}、`max_order` 1–100、`order_res`/`time_res` 0.01–1.0、`samples_per_rev` 64–2048。

### F3 扭矩类用 flattop（而非 hanning）

- `flattop` 已支持（`combo_win`），且 `one_sided_amplitude` 已做相干增益归一化 → flattop 幅值读数正确。
- 扭矩类"线性幅值 + 低频峰值精读"：flattop 扫顶幅值误差 <0.01 dB（hanning 最差约 -1.4 dB）。代价是主瓣更宽（≈3.8 bin vs hanning ≈1.5 bin）→ 频率分辨率变差；但在 nfft=4096、能量集中在 0–200 Hz 的低频场景分辨率富余，权衡值得。FFT-1D 与时频图扭矩类都用 flattop。

### F4 启停类 FFT-1D 用峰值保持

- run-up / coast-down 是非平稳扫频；线性平均会把扫过各频率的瞬态能量抹平、压低真实峰值。峰值保持对每个频率取多帧最大值，正是捕捉瞬态峰值所需。

### F5 阶次"原生分辨率 = samples_per_rev / nfft"，order_res 细于原生只是插值假象

- `order_cot.py:122` 原生分辨率 = `samples_per_rev/nfft`；`order_res`（125 行）只把幅值插值到更细网格，细于原生 = 纯插值、不增加真实分辨率。
- 据此：**振动类阶次 nfft=4096**（原生 512/4096=0.125 ≈ order_res 0.10，真实可达）；**启停类 order_res=0.25**（= 原生 256/1024，保留小 nfft 利时间定位、不报假分辨率）。

### F6 `time_res` 当前在 COT 路径未生效

- `order_cot.py:112` 帧 hop 硬编码为 75% 重叠，三套 `time_res`（0.10/0.05/0.02）仅存预设、**不影响计算**。本批按"前向兼容存值"处理；要让启停 0.02s 真正生效需改 COT hop 计算（**另一任务**，见 §6 风险）。

### F7 阶次域奈奎斯特（samples_per_rev ≥ 2×max_order）三套均满足

- 扭矩 256≥40、振动 512≥100、启停 256≥60。无需修正。

### F8 时频内置助手 z_floor 限制

- `_builtin_preset_full_params`（~3332-3334）仅区分 `'60 dB'` 否则一律 floor=-80；对本设计取值 {Auto, 60 dB, 80 dB} 已正确（80→-80✓、60→-60✓、Auto→z_auto）。为稳健，顺手把它泛化为解析任意 `'NN dB' → floor=-NN`。

### F9 单位匹配用精确匹配（非子串）

- 子串匹配会让 `g` 命中 `kg`/`deg`、`Pa` 命中 `kPa`。必须归一化后**精确**匹配别名集。`mm`/`µm`（位移）归扭矩类但有歧义（可手动切换）。无法识别 → 兜底**振动类**。

## 2. 目标 / 非目标

**目标**
- G1：三个视图共用同一套三个内置预设，显示名统一为 **扭矩类 / 振动类 / 启停类**（显示顺序 1/2/3；`PresetBar.SLOTS` 是 1-based，代码和测试不要写 0-based 槽位）。
- G2：参数按 §3 定稿落地（频域分辨率 + 幅值轴随类型固定；字段名/文案符合 F2，不会 `findText` 失配）。
- G3：打开/切换通道时，按其单位自动高亮推荐的那一套（绿色"★推荐"），仍可手动选其它槽；单位无法识别兜底振动类。
- G4：补回归测试钉死 F2/F5/F7/F9 的不变量。

**非目标**
- 不改任何信号处理算法（`signal/` 不动）。
- 不在本批把 `time_res` 接进 COT（F6，另立任务）。
- 不做"按实测幅值自适应幅值轴数值"的自动量程（仅按类型固定幅值轴；后续可叠加）。
- 不改 PresetBar 的保存/重置/改名既有交互，只新增"推荐高亮"。

## 3. 三套预设定稿（signal-processing-expert 校核值，照搬）

> 落地前对每个视图 Read 对应 `_collect_preset` 复核字段集合，只放该视图真实存在的键（F2）。

**FFT-1D**（`window / nfft / overlap / amp_y / avg_mode / avg_overlap`，无 remove_mean）

| 预设 | window | nfft | overlap | amp_y | avg_mode | avg_overlap |
|---|---|---|---|---|---|---|
| 扭矩类 | flattop | 4096 | 75 | Linear | 线性平均 | 75 |
| 振动类 | hanning | 2048 | 50 | dB | 线性平均 | 50 |
| 启停类 | hanning | 1024 | 75 | dB | 峰值保持 | 75 |

**FFT 时频**（沿用现有紧凑形状 `window / nfft / overlap / amplitude_mode / dynamic / cmap`）

| 预设 | window | nfft | overlap | amplitude_mode | dynamic | cmap |
|---|---|---|---|---|---|---|
| 扭矩类 | flattop | 2048 | 75 | Amplitude | Auto | viridis |
| 振动类 | hanning | 2048 | 50 | Amplitude dB | 80 dB | turbo |
| 启停类 | hanning | 1024 | 75 | Amplitude dB | 60 dB | turbo |

**阶次**（`max_order / order_res / time_res / nfft / samples_per_rev / amplitude_mode`，无 window）

| 预设 | max_order | order_res | time_res | nfft | samples_per_rev | amplitude_mode |
|---|---|---|---|---|---|---|
| 扭矩类 | 20 | 0.05 | 0.10 | 4096 | 256 | Amplitude |
| 振动类 | 50 | 0.10 | 0.05 | 4096 | 512 | Amplitude dB |
| 启停类 | 30 | 0.25 | 0.02 | 1024 | 256 | Amplitude dB |

## 4. 单位 → 推荐预设映射

模块级辅助（放 `inspector_sections.py` 顶部附近，三视图共用）：

```
def recommend_preset_for_unit(unit: str) -> str:   # 'torque' | 'vibration' | 'transient'
```

- 归一化：去空格、转小写、上标 `²` 等价 `^2`/`2`（`m/s² == m/s^2 == m/s2`）。
- **精确**匹配别名集（F9）：
  - torque：`nm n·m n.m n*m mnm knm cnm bar mbar kpa mpa hpa pa psi ° deg mm µm um %`
  - vibration：`g mg m/s² m/s^2 m/s2 mm/s mm/s² mm/s^2 µm/s um/s in/s`
  - transient：（无单位映射，靠手动）
- 兜底：无匹配 → `'vibration'`。

类型 → `PresetBar` slot：扭矩=1 / 振动=2 / 启停=3（1-based）。如果测试需要列表下标，可另行做 0-based 列表，但传给 `PresetBar.set_recommended` 的必须是 1/2/3。

## 5. 自动高亮接线

- `PresetBar.set_recommended(slot: int | None)`：给该槽加"推荐"高亮（清其它槽）；`None` 清空。用 QSS property + `unpolish/polish` 切换，复用 `_PresetHoverCard` 绿色调（`#047857` / `#e9f9f1`），**不**用 setStyleSheet 覆盖主题。
- 每个 contextual 视图加 `set_recommended_for_unit(unit)`：`unit is None` 表示当前选择被清空 → `self.preset_bar.set_recommended(None)`；其它字符串（包括 `''` 空单位、未知单位）调 `recommend_preset_for_unit` → slot → `self.preset_bar.set_recommended(slot)`，因此空/未知单位会兜底高亮振动类。
- `main_window.py` 在既有信号切换 handler 接（无需新信号）：
  - `_on_inspector_signal_changed`（~2063，fft/order）：解析 `(fid, ch)` → `unit = fd.channel_units.get(ch,'')` → 对 `fft_ctx`、`order_ctx` 调 `set_recommended_for_unit(unit)`。
  - `_on_fft_time_signal_changed`（~2080）：同理对时频 ctx 调。
  - payload 为 None（清空选择）→ `set_recommended_for_unit(None)` → 清空推荐高亮；若 payload 存在但单位缺失/空字符串 → 兜底振动类。
  - `signal_changed` 注释为 emits `(fid, ch)` or None（inspector_sections.py:1854），执行时按真实形状取值。

## 6. 风险

- **R-time_res（F6）**：本批 `time_res` 不生效是已知现状，用户若期望启停 0.02s 真正细化时间定位会落空——文档/提示需说明，或后续单开任务把 `time_res` 接进 `order_cot` 的 hop 计算。
- **R-振动阶次数据量**：振动阶次 nfft=4096、samples_per_rev=512 → 每帧需 4096/512=8 转；慢扫/短记录下单帧覆盖转数偏多、帧数变少。若实测不合适，回退方案 = nfft=2048 + order_res=0.25（诚实显示原生分辨率）。
- **R-单位脏数据**：真实 MDF 单位字符串可能含怪字符/大小写/别名遗漏 → 归一化要鲁棒；遗漏只导致兜底振动类（不致命），但应保留手动覆盖。
- **R-rework**：signal-processing-expert 仅校核未改码（files_changed=[]）；落地全在 `inspector_sections.py` + `main_window.py`，由 pyqt-ui-engineer 单独承担，无跨专家同文件改写。
