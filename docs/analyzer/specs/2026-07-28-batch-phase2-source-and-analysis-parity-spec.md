# 批处理 Phase 2：来源与分析能力对齐 Spec

- 日期：2026-07-28
- 状态：已实施；P1–P10 PASS
- 前置门：Phase 1 C1–C10 全部通过
- 关联：dB reference 的 Auto=per source、Manual=per View/recipe；线性数据导出不转 dB

## 1. Outcome

本阶段解决“批处理能打开什么、能配置什么、和单次分析是否同一套语义”的问题。完成后，主窗口宣称支持的文件类型应通过同一 adapter 进入批处理；FFT、FFT-vs-Time、Order 与 TimeDomain 的常用参数、内置预设和 dB reference 不再只存在于单次分析面板。

## 2. Source adapter

### 2.1 One registry

新增纯 Python `SourceAdapterRegistry`，同时服务：

- 主窗口文件筛选器/拖放能力声明；
- batch 磁盘选择器；
- batch metadata probe；
- batch 真正加载；
- frozen/package dependency smoke。

每个 adapter 描述：扩展名、显示名称、可用性/缺失依赖、probe、load，以及是否可能返回多个 logical source。UI 不再手写 `MF4 files (*.mf4)`，`BatchRunner._default_loader()` 不再使用一个不完整的 extension if/else 副本。

### 2.2 Required format coverage

| Family | Extensions | Contract |
| --- | --- | --- |
| MDF | `.mf4`, `.mdf` | 保留物理 occurrence 去重和 channel metadata |
| CAN | `.blf` | 只有具备当前 DBC/decoder context 时才声明“信号级可批处理”；无 DBC 时显示明确受限状态，不把 raw frames 假装成 decoded signals |
| Measurement | `.tdms`, `.hdf`, `.wwt`, `.zfd`, `.mat` | 支持一个文件返回多个 logical source/group |
| Tabular | `.csv`, `.fdc`, `.asc`, `.xls`, `.xlsx` | 使用现有 DataLoader 语义，保留单位和推导 Fs |
| Media | 现有 audio/video extensions | 保留媒体 source metadata 与采样率 |

格式支持是“registry 中 adapter 可用 + probe/load focused test 通过”，不能只靠文件对话框显示扩展名判定。

### 2.3 Multi-source identity

probe 与 load 使用两个相关但职责不同的纯数据结构：

```python
SourceDescriptor(
    source_id: str,
    source_path: str,
    group_id: str,
    display_name: str,
    channel_names: tuple[str, ...],
    units: Mapping[str, str],
    fs: float | None,
    metadata: Mapping[str, object],
)
```

`SourceDescriptor` 不持有 DataFrame/样本数组。真正加载统一返回：

```python
LoadedSource(
    source_id: str,
    source_path: str,
    group_id: str,
    display_name: str,
    file_data: FileData,
    metadata: Mapping[str, object],
)
```

- `source_id` 在同一文件内容/组不变时稳定，至少含 canonical path 与 group identity 的 hash。
- batch file rows 的 key 是 `source_id`，不再是 path。一个 HDF path 的多个 group 必须同时出现。
- 已加载来源与磁盘 probe 来源使用同一 identity；相同物理 occurrence 只出现一次，不同 group 不合并。
- `AnalysisPreset` 的 runtime scope 使用 `source_ids/source_paths` 兼容层；旧 `file_ids/file_paths` 继续迁移。
- group identity 不得只使用可能重复的显示 label：WWT 至少含 `(n, dt, t0)`，ZFD 含 count/dt，MAT 含 length，HDF 含 raster factor；浮点 identity 使用稳定的精确表示。

### 2.4 Probe and load consistency

probe 只读取通道/组/单位/时长/Fs 等轻量 metadata，不构造完整 DataFrame；真正 run 再惰性 load。probe 与 load 必须共享 adapter 和 identity helper，避免“UI 显示可用，runner 却走 MDF loader”。

当前只有 MDF 具备真正 metadata-only probe；其他格式不得把 full load 冒充轻量 probe。实现可先给 adapter 标记 `probe_cost="full"` 并在后台执行，但 Phase 2 完成前 required family 必须有诚实的 cost/status，不能阻塞 UI 主线程。

### 2.5 Declared-support gaps

- `.xls` 不能继续借用 openpyxl：实现需加入并冻结 `xlrd` runtime dependency，按扩展名选择 engine；若依赖不可用，registry 必须显示 unavailable，不能声称已支持。
- TDMS 当前 loader 会把 groups 拉平；Phase 2 若将 TDMS group 暴露为 logical source，需要新增 group-aware adapter，不能仅包装现有 3-tuple 后宣称 multi-group。
- MDF 当前 loader 只返回单位。若 batch Auto reference 需要 quantity/channel reference metadata，adapter/probe 必须显式提取并传给 `FileData.channel_metadata`，不能推测。

## 3. Target expansion policies

批处理提供两种明确策略：

- `common`（默认）：仅显示所有选中 source 都存在的信号；任务为 source × selected common signals。
- `available_per_source`：显示 union，并对每个 source 只生成实际存在的 selected signals；不把缺失组合先生成再大量标红失败。

从当前时域填入的 exact pairs 使用第三种内部策略 `exact_pairs`，只运行用户实际选择的 `(source_id, channel)`；UI 不必把它作为常规下拉项。

RPM 解析遵循同一 source identity：

- Channel 模式默认在目标 source 内找 RPM。
- 显式 cross-source RPM 必须引用稳定 source_id + channel，并验证时间轴可对齐。
- Manual 模式使用 recipe 中 `manual_rpm`，不伪造 rpm channel。

## 4. Shared presets

### 4.1 Single definition

将内置预设参数提取为无 Qt、无 widget 的 shared catalog；单次 Inspector 与 BatchSheet 都从这一份定义加载。不得在 batch 复制另一套数值。

Batch UI 至少提供：

- `频率`
- `均衡`
- `时间`
- `自定义`

“自定义”表示用户编辑后的 recipe，不是第四份硬编码默认。预设只改它声明的分析参数；不重置当前 source scope、输出目录、冲突策略，也不改写没有声明的 dB reference mode/value。

### 4.2 Method applicability

- FFT、FFT-vs-Time、Order 使用各自的 shared provider。
- TimeDomain 当前单次 Inspector 没有既有预设可提取；本阶段新增的“时间”预设必须先定义在 shared provider，再由 TimeContextual 与 BatchSheet 同源消费。它只配置 `time_preprocess`；频率/均衡在时域 disabled，不得套用 FFT 参数或伪称为旧行为迁移。
- 应用预设不启动 batch run，也不触发主窗口分析 compute。

## 5. Analysis controls

### 5.1 Common spectral controls

FFT / FFT-vs-Time / Order 均暴露并完整 round-trip：

- window：包含主分析支持的全部值（包括 flat-top，若 canonical helper 支持）；
- NFFT mode：Auto / Fixed；Auto 可由 `t_win_s` 或算法默认解析，不能固化为 1024；
- weighting：与主面板同源选项；
- amplitude mode：Linear / dB（对 heatmap 为 color scale）；
- dB reference：Auto / Manual + scientific value；
- 频率/时间/阶次与色阶手动范围。

Order 的既有单次内置预设不声明 `window`，但 COT 纯算法本身已支持 `COTParams.window`。本阶段为 Order 新增 window 控件时保持算法既有默认 `hanning`；shared signal-type preset 对该字段采用 partial apply（不改写用户当前 window），不得为三个旧 preset 发明新的 window 数值。

FFT 另提供 averaging mode、average overlap、amplitude definition；FFT-vs-Time 提供 window overlap、remove mean；Order 提供 RPM mode、manual RPM、samples per revolution、order/time resolution。

FFT `amplitude_definition` 使用 `native | peak | rms`：`native` 保持历史算法语义（单帧/峰值保持为 peak，线性平均为 RMS）；显式 Peak/RMS 在算法线性幅值层按 `√2` 转换。旧 recipe 与三个内置 preset 不声明该字段，迁移后等价于 `native`。

### 5.2 dB reference UI and preview

用户明确要求 batch 内可设置 reference，因此本阶段扩展旧“只继承 preset”的限制：

- Batch 使用同一个 `DbReferenceControl` 交互语义，但其状态属于当前 batch recipe。
- Auto 对每个目标 source/channel 独立解析；Manual 对整份 recipe 使用同一个值。
- 在运行前提供只读 effective preview：按 reference value/source 分组展示，例如“12 个目标：10×system acceleration，2×metadata”。不强行在窄三列中列出所有通道。
- weighting 为 A 时标签仍通过 shared formatter 生成 `dBA re ...`；不得把 A weighting 误说成绝对声压级。
- reference 与 mode 只进入 render/display signature，不进入 FFT/Spectrogram/Order compute key，不改变 CSV/XLSX 线性值。

## 6. TimeDomain settings

当前 `time` 方法的空参数面板改为有意义的预处理 recipe。固定顺序：

```text
time range
→ finite cleanup
→ scale/offset
→ remove mean
→ resample or decimate
→ filter
→ time export or spectral/order analysis
```

参数 schema：

```json
"time_preprocess": {
  "scale": 1.0,
  "offset": 0.0,
  "remove_mean": false,
  "sample_mode": "original",
  "target_fs": null,
  "decimation_factor": 1
}
```

- `sample_mode`: `original | target_fs | decimate`。
- target Fs 必须正且不高于无法证明安全的上采样边界；默认只允许降采样。需要上采样时另行设计。
- decimate factor 为正整数并使用抗混叠路径，不能简单切片。
- filter 沿用现有 `params["filter"]`；Nyquist clamp 记录 requested/effective 值和 warning。
- scale/offset 与 remove mean 的顺序锁定，测试以该顺序为准。
- 对 FFT/FFT-time/Order，用户可选择启用同一预处理；默认保持现有行为。

## 7. UI layout

保持现有 INPUT / ANALYSIS / OUTPUT 三列，不扩成新的顶层窗口：

- INPUT：文件/组、target policy、目标信号、RPM、时间范围、预处理。
- ANALYSIS：方法、内置预设、方法参数。
- OUTPUT：数据/图片、轴与 amplitude/dB reference、effective preview。

复杂参数用折叠区，不通过无限增高破坏 1080×760 的基本可用性。新增控件必须有 get/apply round-trip 和 288–320 px 列宽下的几何测试。

## 8. Error semantics

- dependency 缺失：source row 显示 unavailable + 原因；不在 run 时才统一报“读取失败”。
- BLF 无 DBC：标为“需要 DBC 解码”，不能列空信号后仍允许运行。
- source/group probe 成功但 load 失败：该 source 的 tasks failed，其他 source 继续。
- `available_per_source` 中某信号在零 source 可用：preflight blocked。
- cross-source RPM 时间基不兼容：具体 task failed，message 包含两个 source identity。

## 9. Non-goals

- 不做多任务并行和 GPU batch compute。
- 不在本阶段实现 SVG/PDF、4K、manifest/resume；见 Phase 3。
- 不重新定义主分析算法或内置 preset 数值；只提取复用。
- 不自动猜测 BLF 的 DBC。

## 10. Acceptance Criteria

| ID | 验收 |
| --- | --- |
| P1 | batch file dialog 的格式来自 shared registry，与主入口支持声明一致 |
| P2 | 每个 required family 至少有 dispatch/probe focused test；缺依赖有明确状态 |
| P3 | 一个多 group 文件可同时选择、显示、运行并输出互不碰撞的多个 source |
| P4 | MDF physical occurrence 不重复，不同 group 不误合并 |
| P5 | `common` 与 `available_per_source` 的 task 集符合定义，exact pairs 不扩成笛卡尔积 |
| P6 | 三个内置 preset 与单次分析使用同一 provider，应用不改 dB state 或 runtime scope |
| P7 | FFT/FFT-time/Order 的 NFFT/weighting/amplitude/dB/RPM 关键字段 UI round-trip |
| P8 | Auto reference per target preview 与实际 `BatchItemResult` resolution 分组一致 |
| P9 | TimeDomain scale/offset/remove mean/resample/decimate/filter 的顺序与有效 Fs 有数值测试 |
| P10 | 线性 CSV/XLSX 不受 dB reference 影响，render label 与交互式 formatter 一致 |

## 11. Verification

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_loader_dispatch.py \
  tests/test_batch_runner.py \
  tests/test_batch_preset_io.py \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_smoke.py
```

另需对仓库可用 fixture 做至少一个多 group 加载/导出 probe，并生成 BatchSheet offscreen 截图，确认三列在目标尺寸内可操作。真实前台 GUI 验收与 offscreen 测试分开报告。

## 12. Implementation Result — 2026-07-28

P1–P10 全部 PASS。shared source registry 覆盖 22 个扩展并通过真实 HDF multi-group probe；内置/自定义 preset、Time 预处理、FFT/FFT-time/Order 参数、Auto/Manual dB reference 与 effective preview 已接入同一生产契约。验收包括 source/import `121 passed, 1 skipped`、Batch UI 与 inspector focused suites，以及 1080×760 offscreen/Cocoa 分层视觉证据。
