# TraceLab 实用型 Auto-NFFT Spec

- 日期：2026-09-05
- 修订：R1（2026-09-05 review 修订）
- 状态：合同已修订，待按配套 Plan 的 Task 0 核实实施基线；尚未实现
- 适用版本：当前 `main` 后续实现批次；本 Spec 不升版本
- 关联实现计划：`docs/analyzer/plans/2026-09-05-practical-auto-nfft-implementation-plan.md`
- 关联历史计划：`docs/analyzer/plans/2026-09-04-honesty-effective-facts-quick-open-plan.md` 的批次 B（有效事实）；当前 DTO/卡片已落地，本批按 §10.1 扩展现有链路

## 1. Outcome

TraceLab 的自动 FFT 点数应首先满足工程频谱的可读频率分辨率：在普通采样率和足够数据下，分段 FFT 与 FFT-vs-Time **优先使用 4096 点**；数据不足或低采样率下才按明确、可解释的规则适配。

自动算法不能仅返回一个整数。计算完成后必须让用户看到实际 NFFT、频率 bin 间隔、真实窗长、有效帧数及任何降级原因。软件不得用零填充、隐藏降级或模糊的“自动”标签制造虚假的可信感。

本 Spec 所说“可信”限定为：输入事实、算法决策、实际计算参数和用户可见事实一致；不代表软件能在未知传感器、采样、单位、混叠或非平稳输入下保证物理结论正确。

## 2. 当前问题与已核实根因

当前 `mf4_analyzer/signal/adaptive.py:resolve_nfft`：

1. 从 `ceil_pow2(fs × t_win_s)` 起步；
2. 若完整帧少于 24，则不断减半；
3. 若窗口超过总记录的 15%，继续减半；
4. 最后夹在 `[64, 8192]`。

普通 FFT 的线性平均、计算层峰值保持和 FFT-vs-Time 共用这条规则。默认目标窗长为 1.5 s；振动预设为 1.5 s / 50% 重叠。因此 `Fs=1000 Hz` 时初始目标只有 2048，数据再长也不会自动得到 4096；短记录还会被 24 帧和 15% 两道约束降到 1024、512 甚至更低。

已核实的当前结果：

| 输入 | 当前 Auto-NFFT |
| --- | ---: |
| Fs=1000 Hz，60 s，1.5 s，50% | 2048 |
| Fs=1000 Hz，20 s，1.5 s，50% | 1024 |
| Fs=1000 Hz，10 s，1.5 s，50% | 512 |
| Fs=96 Hz，约 52 s，1.5 s，75% | 256 |

问题不是 FFT 数学本身失效，而是自动决策把“多凑平均帧”置于频率分辨率之前，并把 24 帧当成所有分析模式的硬要求。对普通工程频谱，这个取舍过于保守；对 FFT-vs-Time，时间帧数确有必要，但 24 仍过高。

## 3. 范围

### 3.1 本批次包含

- 普通 FFT：线性平均、计算层峰值保持的 Auto-NFFT；
- 普通 FFT：单帧 Auto 的事实显示与短信号提示，计算语义不变；
- FFT-vs-Time Auto-NFFT；
- 上述路径在 Inspector、Analysis View、缓存、项目恢复、Batch、图片/manifest facts 中的一致性；
- 多来源/多 Pane 各自解析和差异显示；
- 帮助、提示、快速参考中的新语义。

### 3.2 本批次不包含

- 不把 FRF 的 Auto-NFFT 改成 4096。FRF 当前 Auto 表示 `nfft == nperseg`，手动增大 NFFT 可能只是零填充；必须保留其独立物理语义。
- 不改变 Order/COT 的 Auto-NFFT。它按角域样本和阶次分辨率决定，4096 与时域频率 FFT 不是同一合同。
- 不改变窗函数、去均值、幅值归一化、A 计权、dB reference、频率自动显示范围或渲染抽稀算法。
- 不用插值或零填充冒充更细的物理频率分辨率。
- 不在本批次新增可调“Auto 算法高级参数”面板；策略常量由测试和实测校准，用户仍可选择固定 NFFT。

## 4. 术语与事实模型

| 术语 | 定义 |
| --- | --- |
| `preferred_nfft` | 产品常规偏好，固定为 4096；不是无条件下限 |
| `duration_target_nfft` | `ceil_pow2(fs × t_win_s)`，表达预设/配方要求的物理窗长 |
| `requested_nfft` | 经过 4096/低 Fs 选择，并应用 64 点下限及 purpose Auto 上限后，Auto 请求的目标点数 |
| `effective_nfft` | 经可用样本和 FFT-vs-Time 帧数约束后真正交给分析器的点数 |
| `df_hz` | 频率 bin 间隔 `fs / effective_nfft`；不得文案化为“窗函数后的绝对可分辨频率” |
| `window_s` | 实际非零填充分析段时长 `effective_nfft / fs` |
| `frames` | 按真实计算路径得到的完整帧/时间帧数量 |
| `degraded` | 可计算时为 `effective_nfft < requested_nfft`；blocked 时为 `None`。统计不足与点数降低分开表达 |

中立层返回冻结的纯数据决策对象，最少包含以下字段。该对象仅服务分段 Auto；单帧 Auto 和 Fixed 由既有分析器/facts builder 表达，不新增虚假的 purpose：

```python
AutoNfftDecision(
    purpose: Literal["fft_segmented", "fft_time"],
    preferred_nfft: int,
    duration_target_nfft: int,
    requested_nfft: int,
    effective_nfft: int | None,
    fs: float,
    n_samples: int,
    overlap: float,
    df_hz: float | None,
    window_s: float | None,
    frames: int,
    degraded: bool | None,
    status: Literal["normal", "notice", "warning", "blocked"],
    reasons: tuple[str, ...],
)
```

固定 reason code：

- `preferred_4096`：应用了常规 4096 基线；
- `duration_target`：显式物理窗长要求高于或替代 4096 基线；
- `low_fs_duration_guard`：4096 会形成过长窗口，按目标窗长适配；
- `minimum_nfft_floor`：目标低于最小分析点数，请求提升至 64，仍须通过真实样本约束；
- `short_record_clamp`：选中数据不足以容纳请求 NFFT；
- `fft_time_frame_guard`：FFT-vs-Time 为获得最低时间帧数而减小；
- `limited_statistics`：普通分段 FFT 的有效段数少于建议值；
- `limited_time_frames`：FFT-vs-Time 时间帧数低于建议值但仍可用；
- `auto_ceiling`：请求超过该 purpose 的 Auto 上限；
- `insufficient_samples`：可用样本不足 64；
- `insufficient_time_frames`：样本至少 64，但最小窗口仍不足 4 个 canonical 时间帧。

reason code 是日志、测试、GUI 与 Batch 的稳定合同；用户文案可本地化，但不得靠解析文案判断状态。

基础原因选择：基线启用且 `duration_target_nfft <= 4096` 时记 `preferred_4096`，否则记 `duration_target`；基线未启用再记 `low_fs_duration_guard`。其余 reason 按上述表顺序去重输出。blocked 时 `effective_nfft/df_hz/window_s/degraded=None`、`frames=0`，表示没有实际结果；不得把失败候选的帧数伪装成已计算事实。

## 5. 产品决策

### D1 — 单帧 FFT 保持“整段就是一帧”

普通 FFT 的 `avg_mode == 单帧` 且 `nfft_mode == auto` 时，`effective_nfft = 选中段样本数`，允许非 2 的幂。不得为了迎合 4096 而截断长记录，也不得把短记录零填充至 4096 后声称物理分辨率提高。

若样本数少于 4096，事实区显示真实点数、`df_hz` 和窗长；这属于输入事实，不自动判为算法错误。

### D2 — 分段 1D FFT 优先频率分辨率，不再为 24 帧降 NFFT

对线性平均和计算层峰值保持：

- 在可用真实样本内选择最大的可行候选；
- 不再因 `frames < 24` 或窗口占记录比例大于 15% 而减半；
- `frames >= 8`：正常；
- `4 <= frames < 8`：`notice`，说明统计段数有限；
- `1 <= frames < 4`：`warning`，明确“仅 N 段，平均/峰值统计有限”；仍允许计算。本策略优先保留较长窗口的频率细节；较短窗口可增加平均段数，但会改变频率与统计稳定性的取舍；
- `frames == 0`：不得进入计算，应为 `blocked`。

普通平均频谱不追加尾部不对齐帧，帧数必须与 `FFTAnalyzer.compute_averaged_fft` / `compute_peak_hold_fft` 的实际循环一致。

### D3 — FFT-vs-Time 保留最小时间帧门槛，但从 24 降为 4

FFT-vs-Time Auto 使用至少 4 个 canonical time frames 作为产品可用性门槛；这不是时间分辨能力或统计独立性的保证，重叠帧不等于独立观测：

- 从请求候选开始；
- 若 canonical frame count `< 4`，逐级减半；
- `frames >= 8`：正常；
- `4 <= frames < 8`：`notice`，显示“时间帧较少”；
- 降到最小候选仍不足 4 帧：`blocked`，不给出只有 1–3 列却看似连续的热图。

此门槛仅约束 Auto，Fixed 的既有可计算合同不变。时间定位还受真实窗长影响，必须通过 §7 的短时突发/扫频验收，不能只凭帧数宣称改善。

帧起点必须复用 `SpectrogramAnalyzer` 的真实规则，包括尾部未对齐时追加最后一帧；Resolver、Preview、Analyzer 和 Batch 不得各算一遍略有不同的帧数。

Auto 不得静默修改用户设置的 overlap。需要更多时间帧时只调整 NFFT，并说明原因。

### D4 — 4096 是普通采样率下的基线，不是低 Fs 的盲目下限

常量：

```text
AUTO_NFFT_PREFERRED = 4096
AUTO_4096_MAX_WINDOW_S = 10.0
AUTO_FFT_SEGMENTED_MAX = 16384
AUTO_FFT_TIME_MAX = 8192
AUTO_FFT_TIME_MIN_FRAMES = 4
AUTO_NOTICE_FRAMES = 8
AUTO_MIN_NFFT = 64
```

只有 `4096 / fs <= 10.0 s` 时，4096 才作为自动基线。该边界使 `Fs >= 409.6 Hz` 的常见工程数据可优先 4096，同时避免 96 Hz 数据仅为点数形成 42.67 s 窗。否则使用 `duration_target_nfft`，并记录 `low_fs_duration_guard`。显式 `t_win_s` 若本身要求更长窗口，仍按该目标计算；10 s 只约束“为了凑到 4096 而额外拉长”，不覆盖用户/预设的明确物理窗长。

因此 `Fs=96 Hz` 时不会仅为达到 4096 而使用 42.67 s 窗；默认 1.5 s 目标仍解析为 256 点、`df=0.375 Hz`。

低 Fs 或极短目标窗使 `duration_target_nfft < 64` 时，请求先提升至 64 并记录 `minimum_nfft_floor`，然后检查真实样本及时间帧数。例如 Fs=10 Hz、N=6000、t=1.5 s 应使用 64 点，不得因目标只有 16 点而 blocked；事实显示真实 6.4 s 窗长。

### D5 — Auto 只使用真实段样本，不以零填充满足 4096

`effective_nfft <= n_samples`。Auto 候选按 2 的幂下降至真实可容纳值。若分段模式可用样本不足 64：

- 分段 1D FFT 与 FFT-vs-Time 返回 `blocked / insufficient_samples`；
- 单帧 FFT 仍按其既有最小输入合同处理。

Manual/Fixed NFFT 的现有行为不在本 Spec 内改变，但 facts 必须区分“请求”和“实际”，包括分析器因短信号发生的 clamp。

### D6 — Purpose-specific 上限

- 分段 1D FFT Auto 上限 16384；普通 FFT 已有 16384 固定选项，1D 输出成本可控。
- FFT-vs-Time Auto 上限保持 8192；二维矩阵、worker 时间和交互成本独立评估后才可提高。
- 上限命中记录 `auto_ceiling`，并显示实际 `df_hz`；不得只显示“自动”。

### D7 — Auto 按 source + pane 解析

一个 View/Pane 内的多条曲线可能来自不同 Fs、不同选中样本数。每个 `(source_id, channel, pane, time_range)` 独立得到 `AutoNfftDecision`，不得用第一条曲线的 NFFT 覆盖其他来源。

折叠摘要规则：

- 所有来源相同：`自动(4096)`；
- 来源不同：`自动(2048–4096 · 每源)`；
- 尚无数据且 Fs 已知：显示按同一候选 helper 得到的目标，如 `自动(目标 4096)`；Fs 未知时只显示 `自动(待数据)`；
- 任一可计算来源 `degraded=True`：摘要追加 `· 有降级`；仅有统计不足等 notice/warning 时追加 `· 有提示`；存在 blocked 来源时显示 `· 有来源不可计算`，保留其身份与原因。各提示可并存，不将统计不足写成“点数已缩短”。

facts 按 composite source/channel 身份列出每源结果和不可计算原因；摘要的数值范围只取可计算来源，全 blocked 时不构造数值范围。不得继续用代表源的 facts 代替其他来源。

### D8 — 意图、有效值和缓存身份分离

- View、项目、预设、Batch recipe 保存用户意图：`nfft_mode=auto`、`t_win_s`、overlap；不得把一次计算得到的 `effective_nfft` 固化为下次的手动值。
- 每次来源、时间范围、Fs、overlap、目标窗或 Auto/Fixed 模式变化后重新解析。
- 现有结果缓存携带 facts，本批保留该结构：key 除 `effective_nfft`、Fs、overlap、window 及既有 compute fields 外，必须加入中立 helper 生成的 `nfft_facts_signature`。签名覆盖 `nfft_mode`、策略版本、规范化 `t_win_s`、duration target、requested/effective NFFT、样本数、status/degraded/reason codes；不得使用本地化文案。单帧/Fixed 使用其实际请求和模式，无关的 Auto 策略字段为 `None`。
- **本批选择意图不同就使结果缓存失效**：即使数值参数相同，也不复用另一请求携带的旧 facts。不新增一套独立数值缓存。主计算、同步 facts、View 恢复及 FFT-time coordinator/fallback key 都必须传递同一签名。
- 常量 `AUTO_NFFT_POLICY_VERSION = 2`；本批分段 Auto 的 manifest 和有效事实记录该版本。版本不能只在 key 外的附加 metadata 中存在。
- 回归例：Fs=1000、N=3000，t=1.5 s 与 t=8 s 的实际值同为 2048，但请求分别为 4096/8192；两次缓存身份和 facts 必须不同。Auto 4096 与 Fixed 4096 同理。显示专属参数仍不进入 compute key。

### D9 — GUI、Batch、导出共用同一决策

Inspector preview、GUI compute、Batch preflight/compute、图片标题和 manifest 均消费同一个中立决策对象或其序列化形式。不得在 UI、`batch_compute.py` 或 renderer 中复制规则。

Canonical facts 至少包含：

```text
nfft_policy_version
nfft_mode
nfft_preferred
nfft_duration_target
nfft_requested
nfft_effective
nfft_status
nfft_degraded
nfft_reason_codes
fs
df_hz
window_s
frames
overlap
n_samples
```

生产者使用 `nfft_effective`；renderer 可兼容读取历史 alias，但测试必须使用生产者真实 shape。

上述字段适用于成功结果；blocked decision 进入结构化错误/反馈，不伪造成功结果。单帧 Auto/Fixed 的策略版本、preferred、duration target 为 `None`，不套用分段 64 点/4 帧门槛。现有 DTO 属性与 canonical 导出键的兼容映射见 §10.1。

### D10 — 用户可见的诚实反馈

计算完成后，FFT 与 FFT-vs-Time 的 facts 区至少显示：

- `实际 Fs`；
- `NFFT：自动 4096` 或 `自动 4096 → 实际 2048`；
- `频率 bin 间隔 Δf`；
- `实际窗长`；
- `完整段数` / `时间帧数`；
- 降级或统计不足原因。

文案必须明确：增大 NFFT 通过更长真实窗口改善 bin 间隔；零填充只增加采样点，不增加输入信息。不得把 `df_hz` 简写成不带限定的“绝对频率分辨率”。

### D11 — Batch 旧策略产物不得通过 resume 绕过新决策

- 复用检查适用于普通分段 FFT Auto 和 FFT-time Auto；根据 canonical requested recipe 判断适用性，不能信任旧 entry 自报的模式。
- 在逐项 `find_resumable_entry`、分组 `find_resumable_group` 及其提前返回/直接恢复消费者中，共用一个中立兼容判定：适用的旧 entry 必须有非布尔整数 `nfft_policy_version == AUTO_NFFT_POLICY_VERSION`，否则视为不可复用并重新计算。分组还须检查所有将复用的成员；拒绝复用后走既有分组重算规则。
- 版本缺失、类型错误或版本不同均不得以相同 recipe fingerprint、source stat、文件 checksum 为由放行。旧 manifest 仍可加载查看，不改写其历史 facts；本次重算产出新版本事实。
- 保留原有来源身份、checksum、输出完整性与取消检查；版本相同只是必要条件。不能只在 manifest writer 记录版本而不检查 reader/resume。
- 单帧 FFT、Fixed、Order、FRF 的既有复用资格不因缺少这项 Auto 版本而变化；recipe/project 继续只持久化用户意图，不写入内部策略版本来冒充用户参数。

## 6. 规范算法

### 6.1 公共候选

```python
duration_target = ceil_pow2(fs * t_win_s)
baseline = 4096 if (4096 / fs) <= 10.0 else 0
raw_requested = max(duration_target, baseline, AUTO_MIN_NFFT)
requested = min(raw_requested, purpose_auto_ceiling)
available = largest_power_of_two_leq(n_samples)
candidate = min(requested, available)
```

若 `max(duration_target, baseline) < AUTO_MIN_NFFT`，记录 `minimum_nfft_floor`。若 `raw_requested > purpose_auto_ceiling`，记录 `auto_ceiling`。若 `candidate < requested`，记录 `short_record_clamp`。若 `candidate < 64`，返回 blocked / `insufficient_samples`。合法正整数输入中，该分支只能由 `n_samples < 64` 触发。

### 6.2 分段 1D FFT

```python
effective = candidate
frames = non_tail_frame_count(n_samples, effective, overlap)
```

不得按帧数继续降低。状态按 D2 判定。

### 6.3 FFT-vs-Time

```python
while candidate >= 64:
    frames = canonical_spectrogram_frame_count(n_samples, candidate, overlap)
    if frames >= 4:
        return decision(candidate, frames)
    candidate //= 2
return blocked
```

整个减半过程只记录一个 `fft_time_frame_guard` reason；最小候选仍不够时追加 `insufficient_time_frames`。用户文案显示最终差值，不堆叠内部循环日志。帧数计数不得构造完整 starts 数组：中立 owner 提供 O(1) count 和同语义的 starts 生成方法，分析器复用后者。

## 7. 基准验收矩阵

以下结果是产品合同，不得用“接近”替代：

| ID | Purpose / 输入 | 期望 |
| --- | --- | --- |
| M1 | segmented FFT；Fs=1000，N=60000，t=1.5 s，50% | NFFT=4096，frames=28，`df=0.244140625 Hz`，normal |
| M2 | segmented FFT；Fs=1000，N=20000，t=1.5 s，50% | NFFT=4096，frames=8，normal |
| M3 | segmented FFT；Fs=1000，N=10000，t=1.5 s，50% | NFFT=4096，frames=3，warning + `limited_statistics`；不得降到 2048/512 |
| M4 | FFT-vs-Time；Fs=1000，N=10000，t=1.5 s，50% | NFFT=4096，canonical frames=4，notice + `limited_time_frames` |
| M5 | FFT-vs-Time；Fs=1000，N=8000，t=1.5 s，50% | 请求 4096 → 实际 2048，canonical frames=7，notice + `fft_time_frame_guard` + `limited_time_frames` |
| M6 | FFT-vs-Time；Fs=1000，N=10000，t=1.5 s，80% | NFFT=4096，canonical frames=9，normal |
| M7 | segmented FFT；Fs=96，N=5002，t=1.5 s，75% | NFFT=256，frames=75，`low_fs_duration_guard`，`df=0.375 Hz`，非 warning |
| M8 | segmented FFT；Fs=1000，N=3000，t=1.5 s，50% | 请求 4096 → 实际 2048，frames=1，warning；不得降到 512 |
| M9 | single-frame FFT；Fs=1000，N=3552 | NFFT=3552，非 2 的幂仍保留；不截断到 4096/2048 |
| M10 | 任一分段 Auto；1<=N<64 | blocked + `insufficient_samples`；不得返回 64 后交给下游失败 |

M1–M8、M10 属于分段 resolver 矩阵；M9 由单帧 analyzer 与 GUI/Batch 接线测试锁定，不传入 `resolve_auto_nfft`。

### 7.1 必补边界矩阵

| ID | 输入 | 期望 |
| --- | --- | --- |
| B1 | Fs=10/20，N=6000，t=1.5 s，50%，两个分段 purpose | requested/effective=64；分别 df=0.15625/0.3125 Hz；普通 FFT 186 段、FFT-time 187 帧；normal，含 `minimum_nfft_floor` 与 `low_fs_duration_guard` |
| B2 | Fs=96，N=5002，t=0.1 s，75%，两个 purpose | requested/effective=64，含 `minimum_nfft_floor`，不 blocked |
| B3 | Fs=1000，t=1.5 s，50%，N=63/64/65 | 普通 FFT：63 blocked，64/65 用 64 点且 1 段 warning；FFT-time：三者均 blocked，原因分别为样本不足/时间帧不足/时间帧不足 |
| B4 | FFT-time；Fs=1000，t=1.5 s，50%，N=128/129 | 128 在最小 64 点时仅 3 帧，blocked；129 用 64 点，有含尾帧的 4 帧，notice |
| B5 | Fs=409.599/409.6，N=60000，t=1.5 s，50% | 两个 purpose 的 requested/effective 分别为 1024/4096；边界采用 <=，不作浮点近似扩大 |
| B6 | Fs=10000，N=1000000，t=4 s，50% | duration target=65536；普通 FFT requested/effective=16384，FFT-time=8192；含 `auto_ceiling`，保留原 duration target 供解释 |
| B7 | Fs/目标窗/overlap 非有限或越界；N 为空、负数、非整数、bool | 明确 ValueError，由调用层转 user/data failure；不得静默取整、默认 Fs 或回退旧 resolver |
| B8 | overlap=0/0.95，整除尾部/不整除尾部、候选恰为 N | count 与真实分析循环一致；tail 不重复，普通 FFT 不补尾帧 |

### 7.2 瞬态与扫频验收

确定性输入：Fs=1000、N=60000；100 Hz 正弦仅在 `[20,20.25)` s 开启，以及 20→100 Hz 的线性扫频（独立通道）。冻结随机噪声种子（若叠加），记录生成参数。

- 数值检查：每帧中心由实际 starts 和 `(nfft-1)/(2*fs)` 算出；与突发区间无交集的窗口不出现突发能量；Auto 与相同 effective NFFT 的 Fixed 分析器输出一致。
- Cocoa 并列观察 Auto 与 Fixed 1024/4096 的窗长、hop、热图位置及时间涂抹，记录差异。验收要求真实时间坐标、facts、提示与输出一致，不能要求 4.096 s 窗精确定位 0.25 s 事件。
- 若该效果不满足目标场景，先修订产品策略及矩阵，再实施；不得暗调窗长、overlap 或渲染插值来隐藏结果。4096/4 帧仍是待实测验收的产品策略。

## 8. 数值与兼容合同

- `fs` 必须有限且大于 0；`n_samples` 为非 bool 整数且大于 0；overlap 有限且在 `[0, 0.95]`；`t_win_s` 有限且大于 0。乘积溢出也须明确拒绝；这些是新 resolver 的合同，不收紧旧公共 helper/Fixed 的输入合同。
- `df_hz` 必须由实际 NFFT 计算，不得由请求值计算。
- 普通平均/峰值保持的 frame count 与其实际 hop 取整完全一致；FFT-vs-Time 与 `_frame_starts` 完全一致。
- 空、短、NaN/Inf 参数返回现有错误分类中的明确 user/data failure，不允许 broad fallback。
- `resolve_order_nfft` 的当前输出矩阵保持不变；现有 96 Hz 低 Fs 案例保持 M7。
- legacy 固定 NFFT 工程/预设/recipe 继续按固定值恢复；Auto 工程恢复后按新策略重算。
- 不把 `_ChannelKeyDict` 或 composite source identity 转成显示名键。

## 9. 性能合同

- Resolver 为纯函数，候选最多按 2 的幂下降，复杂度 O(log N)。
- 普通 1D Auto 上限 16384；FFT-vs-Time 上限 8192。
- FFT-vs-Time 仍受现有 64 MiB amplitude matrix preflight；新算法不得绕开或弱化该门禁。
- 多来源 preview 不读取/复制整列数据，只消费 Fs、选中样本数、overlap 与 purpose。
- 不改变 pyqtgraph 的 peak-trace、AA、ink 或 raster 决策；4096/8192/16384 的显示成本由既有频谱 peak-hold 渲染路径承担。

## 10. 依赖与迁移

### 10.1 现有有效事实链路的兼容迁移

R1 核实基线为 `c9438b589b58e3395765b62e33ce5601c189541c`：`e72606a3` 已引入有效事实，`172896e9` 已修复空卡片；关联计划文字不是当前实现状态的证据。现有 owner：

- `signal/fft.py:FftEffectiveFacts/build_fft_effective_facts`；`signal/spectrogram.py:SpectrogramEffectiveFacts/spectrogram_facts_from_result`。
- `ui/inspector_sections/_effective_facts.py` 格式器和卡片生命周期；各 mixin 发布 facts，FFT 当前仍取代表源，须按 D7 扩展。
- `batch_compute.py` 构造 facts，`batch.py` 组装 effective_params，renderer/manifest 消费映射。

迁移合同：

| 现有字段 | 本批合同 |
| --- | --- |
| `nfft` / `df` | 保留既有 DTO 属性与构造兼容；提供只读 canonical alias `nfft_effective` / `df_hz`，由同一值导出，禁止双份可独立设置的状态 |
| `shortened` | FFT/FFT-time 仅表示实际点数小于请求；统计不足使用 `nfft_status` 和 `nfft_reason_codes`。不得继续因 `<24` 段写 shortened；Order/FRF 原合同保留 |
| 新策略字段 | 以带默认值的扩展字段携带版本、mode、preferred、duration target、status/degraded/reasons；旧调用者仍可构造 DTO，缺失事实不伪造为 0 |
| `asdict(facts)` 导出 | 在各 DTO owner 提供 canonical 序列化入口，GUI 边界测试、Batch 和 manifest 复用；兼容别名若保留，必须由 canonical 值派生 |

共享格式器优先读取 canonical 键，兼容旧属性；FFT/FFT-time 的 bin 间隔及统计提示单独分支，保留 FRF/Order 的既有标签、warnings 和字段。`AutoNfftDecision` 是计算决策，不另建 `AutoNfftFacts` 展示模型。单帧/Fixed 继续使用实际计算结果构造事实。

迁移必跑 `tests/signal/test_fft_effective_facts.py`、`tests/signal/test_spectrogram_effective_facts.py`、`tests/signal/test_order_effective_facts.py`、`tests/test_effective_facts_parity.py` 及 Inspector 的四类 facts 用例；覆盖 DTO 属性、canonical mapping、实际 renderer 输出三层，不能用手造别名替代生产者 shape。

### 10.2 公共 helper 兼容

本批固定采用新增 purpose-specific `resolve_auto_nfft`：产品分段 FFT/FFT-time 迁移过去，旧 `resolve_nfft` 与 `resolve_order_nfft` 保留原有签名、默认值和输出。先冻结现有 Order 参数矩阵，再实施新 helper；不直接修改全局默认。旧 helper 文档注明兼容用途，不移除公共 import。

## 11. Acceptance Criteria

| ID | 验收标准 |
| --- | --- |
| A1 | M1–M8、M10 与 B1–B8 由中立 resolver/frame 测试锁定；M9 由单帧 analyzer 与 GUI/Batch 接线测试锁定 |
| A2 | 分段 1D FFT 不再因 24 帧/15% 规则降级；NFFT=4096 的 M1–M3 成立 |
| A3 | FFT-vs-Time 只在 canonical frames<4 时降级，且 M4–M6 成立 |
| A4 | 单帧 Auto 保留 whole-selection，Manual/Fixed 和 legacy round-trip 不变 |
| A5 | 96 Hz M7 保持物理窗长适配；Order 现有 auto 输出矩阵零变化 |
| A6 | 分段 Auto 不返回大于选中样本数的 NFFT；不足 64 明确 blocked；目标低于 64 而数据充足不误 blocked |
| A7 | GUI preview、compute、cache key、Batch 和 renderer 使用同一 decision/facts shape |
| A8 | 多来源同 Pane 可显示不同 effective NFFT；摘要显示范围/每源而不是伪造单值 |
| A9 | 项目/预设/recipe 只保存 Auto 意图；D8 签名区分同实际值的不同意图；D11 阻止旧策略逐项/分组 resume |
| A10 | facts 显示实际 NFFT、bin 间隔、窗长、帧数和原因；请求值与实际值不混淆 |
| A11 | FFT/FFT-time 帮助、hints、quickref 同步 4096 偏好、低 Fs 例外和零填充边界 |
| A12 | 现有 FFT 数值幅值、窗、计权、dB reference、Order/FRF 计算及 facts 展示和渲染质量门禁不回归 |
| A13 | 真实 Cocoa 用 M1/M7 类数据及 §7.2 突发/扫频验证摘要、facts、时间定位取舍与交互；offscreen 不替代 |

## 12. 完成定义

只有 A1–A13 都有对应证据，才可宣称 Auto-NFFT 改造完成。自动化绿测只能证明决策、数值和接线；真实前台图形是否清晰、事实是否可读必须独立验收。若没有 M1/M7 对应的真实数据，可用确定性生成信号做 Cocoa exercise，但必须标注“合成输入”，不能冒充客户数据结论。
