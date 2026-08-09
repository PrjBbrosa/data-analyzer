# 分析参数面精简 spec（单次 + 批处理）

日期：2026-08-09

状态：**已实施；A11 macOS 前台视觉验收待单独执行**

关联文档：

- `docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`
  （本文修订其 §5.3 / §5.4 / §6.3 / §9.2 / §17，修订点在 §8 逐条列出）
- `docs/analyzer/plans/2026-08-09-frf-interaction-and-axis-polish-implementation.md`
  （已实施；其 D1 给本文要移除的三个控件写了 tooltip，实施本文时一并回收）
- `docs/analyzer/plans/2026-08-09-analysis-parameter-surface-simplification-implementation.md`
  （本文的实施计划）

## 1. 结论

从单次分析与批处理的参数面上移除三个**用户不该拨、拨了只会更差**的开关，并把
FRF 的时间范围收敛为其余三个分析 section 已经在用的同一套控件：

| 控件 | 现状 | 目标 |
| --- | --- | --- |
| `周期窗`（FRF） | Inspector + Batch 各一个复选框 | 从两处 UI 移除；core 默认 `periodic_window=True` 不变 |
| `每段去均值`（FRF） | Inspector 复选框 + Batch 下拉 | 从两处 UI 移除；core 默认 `detrend="constant"` 不变 |
| `去均值`（时频） | Inspector + Batch 各一个复选框 | 从两处 UI 移除；core 默认 `remove_mean=True` 不变 |
| `分析范围`（FRF） | 三选下拉 + 共享时间范围组 | 删下拉；沿用共享组的 `使用选定时间范围` + 起止秒；`使用当前时域范围` 降级为填充按钮 |

**不删数值能力，只删界面入口。** `FrfParams` / `SpectrogramParams` 的字段、
`batch_recipe.py` 的字段白名单、manifest 与有效事实里的记录全部保持不变，老配方与
老项目继续按其显式值执行（§4 D4）。

## 2. 为什么现在做

三个开关的共同问题不是"多了一个选项"，而是**默认值以外的取值没有能站住的工程场景，
而错误取值会安静地产生错误读数**。这一点此前没有被量化过，本次实测补齐（§3.1）。

`分析范围` 的问题不同：它与共享时间范围组语义重叠，两者叠在一起产生了三处**屏幕显示
与实际计算不一致**的行为（§3.2）。这类不一致比多一个控件危险得多——用户按屏幕上的
数字写报告，而计算用的是另一组数。

量化收益：

- 单次 FRF Inspector 少 3 个控件（周期窗、去趋势、分析范围下拉），时频 Inspector 少 1 个；
  Batch 参数网格 FRF 少 2 项、时频少 1 项；
- `_frf_mixin.py` 中 `source_time_view_id` 快照溯源与其 4 条 preflight 分支
  （`_frf_requested_range` 约 35 行 + `_on_frf_range_mode_changed` 的 `current_time` 分支 +
  `_on_frf_source_time_xrange_changed` + `_invalidate_frf_time_view_link`）可整体退休，
  FRF 的时间范围改走与 FFT/时频/阶次同一条 `_capture_analysis_time_range` 路径；
- 四个分析 section 的时间范围交互从"三种写法"收敛为一种。

## 3. 当前事实（本机实测，2026-08-09）

### 3.1 三个开关关掉之后会发生什么

测量条件：`fs = 1000 Hz`；FRF 用 30 s 白噪声激励 + 二阶对象（`fn = 25 Hz`、`ζ = 0.05`、
静态增益 1.0），`t_win = 2 s`、`overlap = 50%`、hanning、比较带 0.5–200 Hz；时频用 20 s
的 `37 Hz 正弦 + 0.2 白噪声`，`nfft = 1024`、`overlap = 50%`、hanning。

**周期窗**（`periodic_window=False` vs `True`）：

```text
max |Δ|H||  = 7.4e-04 dB
max |Δphase| = 5.5e-03 °
```

加上 `x + 50` / `y + 3` 的直流偏置后，上述两个数**完全不变**。根因：两种窗只差
`symmetric(n+1)[:-1]` 的一个样本（`n = 2000` 时窗数组最大差 `1.2e-3`，`Σw²` 相对差
`5e-4`），且 x、y 用同一个窗、`H = Pxy/Pxx` 是比值，共模部分基本抵消。

旁证：`scipy.signal.welch/csd` 只有 `fftbins=True`，不提供该开关；
`analysis_presets.py` 三套 FRF 内建预设全部 `periodic_window=True`。

**FRF 去趋势**（`detrend="none"` vs `"constant"`）：

```text
无偏置：          max |Δ|H|| = 0.054 dB           ← 去均值几乎不动真实低频内容
x+50 / y+3 偏置： max |Δ|H|| = 24.5 dB            ← 低频被偏置比污染
                  DC/首频点 |H|: constant 1.037（真值 1.0，对）
                                 none     0.060 = 3/50（读的是两路偏置之比，错）
                  相干 @bin1:    constant 0.993 → none 0.9997
```

最后一行是关键：关掉去趋势后**相干反而升高**，因为恒定偏置是完美相干的。可信度指示会
给出更漂亮但完全错误的读数，用户没有任何提示可以察觉。

反向担心（"去均值会削掉真实的低频/静态增益"）不成立：每段减均值只归零该段的 0 频分量，
Hann 主瓣以外几乎不受影响；无偏置时全带最大差 0.054 dB，且 DC 频点用 `constant` 反而给出
了正确的静态增益。

**时频去均值**（`remove_mean=False` vs `True`）：

```text
DC = 0：  513 行中 2 行偏差 >1 dB（每段样本均值本就不为零）
DC = 5：  8 行，影响到 11.7 Hz
DC = 50： 19 行，影响到 30.3 Hz，最大 142 dB；DC 行 -52.5 dB → +34.0 dB
自动色阶（99 分位 + 30 dB 固定跨度）只移动约 2 dB —— 不是整图变黑，而是低频那一段读的
是 DC 泄漏而不是信号
```

**内部不一致**：同一个 App 里 FFT 1D（`signal/fft.py:200`）与阶次（`signal/order.py:123`）
早已把 `remove_mean=True` 硬编码、面板上没有开关（`contextual_fft.py:445` 的注释专门写了
这条），只有时频与 FRF 给了开关，且三处措辞各不相同（`去均值` / `每段去均值` / `去趋势`）。
这个分歧没有物理依据，是历史演进。

### 3.2 `分析范围` 与共享时间范围组的重叠

`使用选定时间范围` 复选框 + 起止秒 + `最大` 是**四个 section 共用的同一个 widget 实例**，
由 `inspector._place_range_group_for_mode` 在切模式时 reparent，嵌入时标题改为 `分析时间`
（`persistent_top.py:328`）。语义对照：

| FRF 下拉 | 共享组的等价操作 | 已有实现 |
| --- | --- | --- |
| 全范围 | 不勾 | `_analysis_mixin.py:313-318`（不勾 → `pane.time_range = None`） |
| 手动范围 | 勾 + 手填秒数 | 同上 |
| （无对应） | 勾 + `最大` = 整段数据 | `window.py:1799` |
| 使用当前时域范围 | 频谱模式已有画布拖选回填（时频/阶次没有） | `window.py:1771` |

下拉唯一多出来的是 `使用当前时域范围` 的**隐藏快照 + 溯源**（记 `pane.source_time_view_id`，
时域 View 被删或切成 custom X 时给出"请重新关联"的 4 条 preflight 报错，
`_frf_mixin.py:393-429`）。这套溯源存在的唯一理由，是快照对用户不可见。

**三处已复现的显示/计算背离**（offscreen 探针，FRF mode + 已选 pair）：

```text
手动范围 + 勾选复选框：   屏幕起止 0.25–0.75 → 被改写成 1.0–1.5（时域画布可见 xlim）
                          实际计算仍用 0.25–0.75
使用当前时域范围：        屏幕显示 0.25–0.75，实际计算 2.0–3.0（隐藏快照）
全范围：                  屏幕显示 0.25–0.75 且可编辑，实际计算 None
```

根因：`chk_range.toggled` 接的是 `_on_time_range_enabled_changed`
（`window.py:1834`），它取 `chart_stack.focused_canvas()`，而该方法
（`chart_stack/stack.py:396`）**永远返回时域卡片**。于是在 FRF 面板里点这个框，实际
是在操作时域 View：改写起止数字、写回时域 View 状态、重绘时域画布。而 FRF 的取值分支
`_frf_requested_range` 从头到尾不读 `range_enabled()`。

代码库其实已经知道这条路有害：`window.py:1800-1807` 的注释写着
`_on_time_range_enabled_changed`"会用画布当前可见 xlim 覆盖 spinbox，正是我们要避免的"，
`最大` 按钮是特意绕开它写的——只是 FRF 面板里那个复选框没绕。

另外，原 spec 自身对该控件的形态就不自洽：§5.3 要求三选下拉，而 §9.2 通篇称它为
**按钮**（"若当前 TimeDomain 使用 custom X，按钮禁用并显示…"）。本文按 §9.2 的形态定版。

## 4. 产品决策

### D1 — `周期窗` 退出 UI，语义固定为 periodic

`FrfContextual.chk_periodic` 与 Batch 参数网格的 `periodic_window` 控件移除。
`FrfParams.periodic_window` 字段、默认 `True`、`get_frf_window(..., periodic=)` 参数、
`FrfEffectiveFacts.periodic_window` 的记录全部保留。

理由：§3.1 实测差异 7.4e-04 dB / 5.5e-03°，低于任何可读阈值；参考实现不提供该开关；
出厂预设无一例外。

### D2 — `每段去均值` / `去均值` 退出 UI，语义固定为开

`FrfContextual.chk_detrend`、Batch 的 `detrend` 下拉、`FftTimeContextual.chk_remove_mean`、
Batch 的 `remove_mean` 复选框移除。`FrfParams.detrend`（默认 `"constant"`）与
`SpectrogramParams.remove_mean`（默认 `True`）保留。

理由：§3.1 实测"关掉"在有偏置时产生 24.5 dB / 142 dB 量级的错误读数，且相干指示反向变好、
无法自查；而"开着"对真实低频内容的代价是 0.054 dB。FFT 1D 与阶次早已硬编码为开，本决策把
四个分析模式统一到同一语义。

**不设"高级参数"折叠区**：把一个不该拨的旋钮换个地方藏着，只是把解释成本转嫁给帮助页，
不解决任何问题。需要非默认值的场景（复现外部工具、回归对照）走批处理配方，那条路本来就在。

### D3 — FRF 时间范围收敛为共享控件

`FrfContextual.combo_range_mode` 移除。FRF 的时间范围与 FFT / 时频 / 阶次完全一致：

- **不勾** `使用选定时间范围` ⇒ 全量不裁（`pane.time_range = None`）；
- **勾** ⇒ 按起止秒裁剪；
- `最大` 按钮填整段数据范围并勾选（沿用现有行为）；
- 新增 `取时域范围` 按钮，与 `最大` 同排，只在 FRF 嵌入态可见：把当前时域 View 的
  committed visible range 一次性**写进起止输入框并勾选**。写入即完成，之后不再关联。

由此：

- `_frf_requested_range` / `_capture_frf_time_range` / `_apply_frf_time_range` 的 FRF 专用
  分支退休，改走 `_capture_analysis_time_range` / `_apply_analysis_time_range` 的通用分支；
- `PaneState.source_time_view_id`、`_on_frf_source_time_xrange_changed`、
  `_invalidate_frf_time_view_link` 及其 4 条"请重新关联"报错全部退休；
- §3.2 的三处显示/计算背离随之消失——起止输入框成为**唯一真相源**。

`取时域范围` 的可用性合同（继承 §9.2 的启用条件，但改为按钮自身的即时反馈）：

- 当前时域 View 的 X source 不是物理 time ⇒ 按钮禁用，tooltip 说明
  "当前时域横轴不是物理时间，无法作为 FRF 时间范围；请切回时间轴或手动输入秒范围。"；
- 取不到有限、递增的 committed visible range ⇒ 按钮禁用；
- 取到之后时域再缩放**不再**标记 FRF pane stale：快照就是输入框里的数字，用户要更新就再点
  一次。这比原先"承诺不联动、却又在源变化时标 stale"更自洽。

**明确保留**：`在时域查看`（§9.3）不受影响；它关联的是 pair 与有效时间范围，与本决策正交。

### D4 — 老配方与老项目的兼容规则

- **批处理配方**：`batch_recipe.py` 的字段白名单、类型归一化、round-trip 全部不变。
  配方里显式写着 `periodic_window: false` / `detrend: none` / `remove_mean: false` 时
  **照旧执行**，不强制回默认。理由：配方是显式意图，强制回默认会让"打开老配方结果变了"，
  比缺一个 UI 入口糟糕得多；实际取值本来就记录在 manifest 与有效事实里。
- **UI 新写出的配方/预设**继续显式写入默认值（不是省略字段），保证可复现性与
  fingerprint 稳定。
- **老项目（analysis view）**：`params["range_mode"]` 在恢复时按下表折叠，折叠结果写回
  `chk_range` + 起止输入框，不再保留 `range_mode` 字段：

  | 老值 | 恢复行为 |
  | --- | --- |
  | `full` / 缺失 | 不勾选，起止不变 |
  | `manual` | 勾选，起止 = `pane.time_range` |
  | `current_time` | 勾选，起止 = `pane.time_range`（把隐藏快照**显式化**）；丢弃 `source_time_view_id` |

  这条迁移是单向的：老项目能打开，新项目不再写 `range_mode`；`from_dict` 遇到未知的
  `range_mode` 值按 `full` 处理，不报错。

## 5. 目标状态：各面板可见字段

### 5.1 单次分析 Inspector

| Section | 移除 | 保留（不变） |
| --- | --- | --- |
| 频谱 | — | 无 `remove_mean` 入口（本来就没有） |
| 时频 | `去均值` | FFT 点数、窗函数、重叠、频率加权 |
| 频响 | `窗语义/周期窗`、`去趋势/每段去均值`、`分析范围` | 估计器、窗函数、段长、重叠率、NFFT 模式/NFFT |
| 阶次 | — | 无 `remove_mean` 入口（本来就没有） |

四个 section 的 `分析时间` 组保持同一实例、同一行为；FRF 嵌入态多一个 `取时域范围` 按钮。

### 5.2 Batch 参数网格（`_METHOD_FIELDS`）

```text
fft_time: window, nfft_mode, nfft, t_win_s, overlap, weighting        （去掉 remove_mean）
frf:      estimator, window, t_win_s, overlap, nfft_mode, nfft,
          magnitude_scale, frequency_scale, phase_mode,
          coherence_threshold, fade_low_coherence                      （去掉 periodic_window, detrend）
```

`_labels` 中对应的三个中文标签一并删除；`METHOD_PARAM_FIELDS`、
`FRF_COMPUTE_PARAM_FIELDS`、`_BOOL_PARAM_FIELDS`、`_NORMALIZED_ENUM_PARAM_FIELDS`
**不动**（D4）。

### 5.3 有效事实与 manifest

不变。`FrfEffectiveFacts` 继续携带 `window` / `periodic_window` / `detrend`；批处理 manifest
继续记录实际取值。UI 上无入口不等于不可观测——这正是"移除入口"与"移除能力"的区别。

## 6. 非目标

- 不改任何数值算法：`compute_frf`、`SpectrogramAnalyzer.compute`、窗函数生成、单边缩放
  一律不动；
- 不改 `在时域查看`、FRF 游标、网格与坐标轴（那是 2026-08-09 交互精修 plan 的范围）；
- 不改 FFT 1D 与阶次的既有硬编码；
- 不新增"高级参数"折叠区（D2 已说明理由）；
- 不删除任何 DTO 字段、配方字段或持久化字段；
- 不把 offscreen 绿测当作视觉验收。

## 7. 验收矩阵

| # | 断言 | 方式 |
| --- | --- | --- |
| A1 | `FrfContextual` 不再有 `chk_periodic` / `chk_detrend` / `combo_range_mode` 属性 | 单元测试（属性缺失） |
| A2 | `FftTimeContextual` 不再有 `chk_remove_mean` | 单元测试 |
| A3 | `_METHOD_FIELDS["frf"]` 不含 `periodic_window`/`detrend`；`["fft_time"]` 不含 `remove_mean` | 单元测试 |
| A4 | UI 发出的 FRF compute params 恒为 `periodic_window=True, detrend="constant"`；时频恒为 `remove_mean=True` | 单元测试 |
| A5 | 显式写 `detrend: none` 的配方仍按 `none` 执行，且 manifest 记录 `none` | 批处理测试 |
| A6 | FRF 不勾 ⇒ `pane.time_range is None`；勾 ⇒ 等于起止输入框 | UI 测试 |
| A7 | 起止输入框与实际计算范围在三种操作下一致（§3.2 三条背离的回归守卫） | UI 测试 |
| A8 | `取时域范围` 在 custom-X 时域 View 下禁用并给出说明 | UI 测试 |
| A9 | 老项目 `range_mode=current_time` 恢复后勾选且起止 = 原快照 | 项目会话测试 |
| A10 | `PaneState` 不再写 `source_time_view_id`；`_frf_requested_range` 已删除 | AST/属性测试 |
| A11 | 真机前台：FRF 与时频 Inspector 无残留空行/错位，`取时域范围` 与 `最大` 同排对齐 | macOS 前台截图（不可用 offscreen 代替） |

## 8. 对 2026-08-08 FRF spec 的修订

以下修订以**追加带日期的定版说明**的形式落在原文各节，不改写历史结论：

| 节 | 原文 | 修订 |
| --- | --- | --- |
| §5.3 第 2 项 | "`分析范围`（全范围 / 使用当前时域范围 / 手动范围）与时间范围控件" | 改为共享 `分析时间` 组（`使用选定时间范围` + 起止秒 + `最大` + `取时域范围`），无下拉 |
| §5.3 第 3 项 | "…窗口与周期语义…NFFT、每段去均值…" | 删除"周期语义"与"每段去均值"两项 |
| §5.4 | "三套内建预设共同默认：periodic Hann、每段去均值…" | 保留（仍是事实），追加"该两项不再有 UI 入口" |
| §6.3 | "首版只提供 constant detrend（开/关）" | 改为"constant detrend 固定开启，不提供 UI 开关，配方可显式覆盖" |
| §6.4 | "默认 `periodic Hann`" | 保留，追加"周期性不再是 UI 可选项" |
| §9.2 | `使用当前时域范围` 全节 | 改为 `取时域范围` 按钮：一次性填充，不保留 `view_id` 溯源，不再标记 stale |
| §17 | "单次稿：`分析范围` 画成单个'使用选定时间范围'复选框，spec §5.3 要求三选" | 追加：2026-08-09 复核后回到原型的单复选框形态，三选下拉作废 |

§8.2 的 `PaneState.source_time_view_id` 字段说明同步标注为"2026-08-09 起不再写入；
`from_dict` 保留读取以兼容老项目"。
