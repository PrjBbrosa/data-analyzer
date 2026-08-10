# FRF 非均匀真实时间轴 — 自动恢复规格

日期：2026-08-10

状态：**设计定稿（自动重建）；待实施/实施中**

实施计划：`docs/analyzer/plans/2026-08-10-frf-nonuniform-time-axis-recovery-implementation.md`

修订对象：
- `docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md` §1 / §6.2
- Batch FFT-vs-Time：`uniform_time_axis_for_spectrogram`

触发证据：`testdoc/DaXiaoQiu.MF4` 真实时间戳相对抖动 ≫ `1e-3`，FRF 拒算；
用户要求**不要手动选 Fs**，按工业惯例自动均匀化后再算。

## 1. 结论

- **`compute_frf` 数值核心仍 fail-closed**：不接受非均匀轴、不在核心内插值。
- **GUI / Batch 适配器自动恢复**：检测到选中范围内相对抖动超限时，按中位 dt 建议
  Fs 执行 `arange(n)/Fs` 均匀化，**不弹窗、不要求用户选 Fs**，然后继续计算。
- 恢复必须可审计：GUI toast/statusBar；Batch item/result warning。

产品对齐 MATLAB：`resample`/`(0:n-1)/Fs` → `tfestimate`，但把「承认名义 Fs」做成
默认自动步骤，而不是让用户点弹层。

## 2. 目标

1. 点「计算频响」遇到不均匀真实轴 → 自动重建 → 自动算完（或报其它真实错误）。
2. Batch 同行为，带 warning，不因 jitter 整条失败。
3. 仅对**选中时间范围内**的不均匀触发；范围外抖动仍忽略（保持既有 mask 语义）。
4. 禁止 generated / 缺失时间轴仍硬失败。
5. 抖动阈值不变：`DEFAULT_TIME_JITTER_TOLERANCE=1e-3`。

## 3. 非目标

- 不弹 `RebuildTimePopover` 作为主路径（频谱面板手动重建仍可独立存在，非本需求）。
- 不在 `signal/frf.py` 放宽容差或插值。
- 不从 MF4 原生多速率 group 重新 raster。
- 不要求用户确认 Fs。

## 4. 产品决策

### D1 — 自动重建语义

```text
fs' = suggested_fs_from_time_axis(t)   # 中位正 dt
t'  = arange(len(t)) / fs'
```

- GUI：写回该逻辑来源的 `FileData.rebuild_time_axis(fs')`（`_time_source='manual'`），
  并 `_invalidate_all_analysis_caches_for_fid` + 刷新时域范围上限。
- Batch：优先 **task-local** 替换 `time`/`fs`，不强制写回共享 `FileData`；warning 记录
  原 `relative_jitter` 与采用的 `Fs`。

### D2 — 触发时机

在应用共用物理时间 mask **之后**、最终均匀性校验失败时触发（或等价：校验前检测选中
段不均匀则先重建再校验）。保证「范围外抖动不触发」合同。

每个 prepare/candidate 构建路径最多自动重建 **一次**；重建后仍不匀则 raise（防御）。

### D3 — 文案

| 场景 | 级别 | 文案 |
| --- | --- | --- |
| GUI 自动重建 | warning toast | `时间轴不均匀（相对抖动≈X），已按 Fs≈Y Hz 自动重建为均匀网格并继续计算。` |
| GUI statusBar | — | `频响 · 已自动重建时间轴 · Fs=…` |
| Batch warning | 写入结果 | `时间轴已按建议 Fs 自动重建为均匀网格（relative_jitter=… → Fs=…）` |

### D4 — 与「不得静默重采样」

澄清为：禁止在无提示的数值核心内重采样。适配器自动重建 + toast/warning 视为
**默认可审计恢复**，符合本次用户要求与 MATLAB 默认脚本习惯。

## 5. 验收

1. `DaXiaoQiu.MF4` + TAS/Motor torque：一点计算即可出 FRF（或段数等非抖动错误）。
2. 无重建 Fs 弹窗。
3. 选中范围外抖动仍可算；选中范围内抖动自动重建后可算。
4. `compute_frf` 单测仍拒非均匀输入。
5. Batch 抖动夹具成功且含 warning。
