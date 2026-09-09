# 预设基准、差异色标与坐标保留交互 Spec

日期：2026-09-09
状态：设计完成（含 2026-09-09 工作区代码冻结的字段/回写证据）。本文不代表当前产品已满足全部规则。
配套：[执行 Plan](../plans/2026-09-09-preset-baseline-and-axis-preservation-plan.md)

本次文档修订相对初稿：补齐 `_collect_preset` 分类表、别名与单位兼容矩阵；把画布回写从 UNKNOWN 收成明确边界；冻结槽身份、schema 与必须改写的旧 reverse-match 测试。产品代码仍按 Plan 执行，本文不授权开工。

## 1. 目标与设计决策

用户从「均衡」等内置预设出发调整坐标或分析参数后，仍能知道当前基于哪个预设。
切换预设时允许仅本次保留手动坐标。按钮高亮、色点、悬浮卡片、确认框和 View 恢复必须表达同一份状态。

- 蓝色高亮表示「当前调整基准」，不再表示「所有参数完全匹配」。
- 坐标差异用琥珀色色点，分析参数差异用紫色色点。色点无文字。
- 保留现有面板样式；只给悬浮卡片「状态判断」内对应状态项加同色细边框。
- 手动调整不自动切换到「自定义」，也不自动认领另一个恰好匹配的预设。
- 「自定义」是可保存/加载的用户槽，不是所有未匹配状态的集合。
- 重复点击当前预设统一为重新应用；完全一致且槽未更新时是无副作用操作。
- 取消切换必须保持原参数、基准、高亮、推荐标识、结果状态全部不变。

## 2. 范围

首期完整适用于 FFT、FFT vs Time、Order 的内置预设和已保存自定义槽。
FRF 共享基准与参数色点规则，但无坐标范围预设字段，不新增坐标保留提示。

明确不做：

- Batch 配置、时域 View、数值算法、预设信号匹配、自动执行计算。
- 把画布相机视口（`PaneState.xlim` / `ylim`）写进 Inspector 轴控件。
- 改公共 `preset_params_match` 的旧调用语义。
- 升产品版本或改 dated 历史文档。

比较与基准快照只走 Contextual 的 `_collect_preset()`，禁止拿 `current_params()` / `compute_params()` / `display_params()` 与预设补丁直接互比：后三者含信号、Fs、加权、`nfft_effective`，且 overlap / nfft 形状与预设补丁不同。

## 3. 现状证据（2026-09-09 工作区）

含前序未提交修改，不能等同于 HEAD。行号会漂移，以符号为准。

| 文件 / 符号 | 已确认现状 | 目标差异 |
| --- | --- | --- |
| `PresetBar._matching_slot`、`sync_match` | 无完全匹配就点亮槽 4「自定义」 | 高亮按 View 基准；未匹配不高亮任何槽 |
| `_prepare_user_preset`、`_confirm_axis_preservation` | 已有本次保留/使用预设/取消；取消后仍 `sync_match()`；保留后若合并轴则再 reverse-match | 合入原子切换；取消零写入；保留后目标槽仍是基准 |
| `_on_left_click` | 再点当前内置槽走 `_restore_default_params` | 再点统一重新应用；恢复默认改显式菜单 |
| `_PresetHoverCard._status_specs` | 按原始键 ∩ 当前值比较 | 与按钮和确认框共用归一化差异 |
| `AnalysisViewState` | schema 8；无基准字段 | 可选 `preset_baseline`；嵌套 schema 9 |
| `analysis_view_bridge.capture_params_to_state` / `apply_params_from_state` | 只搬 `params` | 同步基准，恢复后一次投影 |
| `preset_params_match` | 比较交集；空交集为真 | 不可用作新基准推断的充分证据 |
| `set_custom_active` | 已定义，生产路径无调用 | 不得再作为未匹配状态的汇 | 

仓库内没有已提交的纯色点 HTML 原型。视觉合同以 §8 为准。

## 4. 状态模型与所有权

### 4.1 View 基准

`AnalysisViewState.preset_baseline` 为可选字段，由当前分析 View 持有。Contextual / `PresetBar` 只投影这份状态，不另建全局权威。禁止新增跨 mixin 的 `MainWindow` 写入。

建议 JSON：

```json
{
  "version": 1,
  "kind": "fft",
  "slot": 2,
  "display_name": "均衡",
  "params": {}
}
```

| 字段 | 规则 |
| --- | --- |
| `version` | 基准结构版本，独立于 `APP_VERSION` 与 View schema。当前为 `1`。 |
| `kind` | PresetBar 命名空间：`fft` / `fft_time` / `order` / `frf`。Order 目录方法名是 `order_time`，查 catalog 时映射，不把 `order_time` 写入基准。 |
| `slot` | 稳定整数身份：内置 1–3，自定义 4。不以显示名作身份。 |
| `display_name` | 加载成功时的显示名快照，供卡片使用。 |
| `params` | 加载成功后立刻 `_collect_preset()` 的深拷贝，即完整目标意图；不含信号、Fs、运行结果、色点 flags。 |

持久化 params 是来源证据，不是派生缓存。色点、diff flags、弹窗选择不能落盘。
每个 View 独立。`ViewManager.duplicate` 已走 `from_dict(to_dict())`，基准必须进入 `to_dict` 并深拷贝，禁止共享可变字典。
`ViewManager._make` 的新 View 没有基准。PresetBar 经 Contextual 读写基准；bridge 在 capture/apply 时复制。

### 4.2 槽位后来变化

差异对比加载时的快照，不因为别处重写预设而移动比较基准。
槽内容或名称改变时，原 View 仍保留原来源快照；卡片标明「基准快照，槽位已更新」。
再次点击该槽则加载当前槽位内容，成功后更新基准。
槽被清空时，原来源仍保留但不高亮空槽；卡片/摘要显示「原基准已不可用」，不得伪装成当前自定义槽。
此状态不阻止加载其他预设。保存当前到槽位成功后，该槽成为新基准。

### 4.3 无基准与旧项目

旧项目缺少该字段时：只有规范化后的完整可比字段全部匹配才允许推断基准；多个匹配按槽序 1→4 取最小。
无法证明匹配时不高亮任何槽，显示「未关联预设」；不得猜测上一次使用的预设，也不得点亮空的自定义槽。
新字段损坏、`kind` 与当前 section 不符、`slot` 非法：按无基准处理，并用该模块 `logger.warning` 留下可观察记录。不吞编程错误。
新 View 不继承前一个 View 的基准或角标。
空白 View 走 `reset_to_defaults` 时套用构造默认参数，但清空基准——即便 FRF 构造默认恰好等于「稳健」，也不因此高亮稳健。

## 5. 单一比较面与字段分类

单一分类/归一化实现同时服务按钮、卡片、切换冲突和旧项目推断。实现放在 `mf4_analyzer/ui/inspector_sections/preset_state.py`（无 Qt 控件）。`presets.py` 只消费，不复制第二套 compare。

分类结果只有三类：坐标 / 参数 / 不参与。未知且未列入退休别名的键不得静默视为一致：计入参数差异并打日志，提示需要补映射。

### 5.1 规范轴与别名

规范坐标键：`x_auto, x_min, x_max, y_auto, y_min, y_max, z_auto, z_floor, z_ceiling`。

| 旧键 | 规范键 | 出现处 |
| --- | --- | --- |
| `autoscale` | `x_auto` | FFT `_collect_preset` 仍双写 |
| `freq_auto` | `y_auto` | FFT vs Time |
| `freq_min` / `freq_max` | `y_min` / `y_max` | FFT vs Time |
| `dynamic == "Auto"` | `z_auto=true` | FFT vs Time |
| `dynamic == "N dB"` | `z_auto=false`, `z_floor=-N`, `z_ceiling=0` | FFT vs Time |

同一意图只计一次。旧轴别名不算参数差异。Order 无这些别名。

### 5.2 有效值

1. 自动轴只比较 `auto=true`，忽略未启用的上下限。
2. 手动轴比较 `auto=false` 与两个有效边界。
3. 自动 NFFT 比较 `nfft_mode=auto`（及控件「自动」请求），不比较 `nfft_effective` / `nfft_preview` / 解析出的整数。
4. 固定 NFFT 比较模式与用户指定值。FFT/Order/FFT-Time 的 collect 里 `nfft` 是控件文本；FRF collect 里 `nfft` 在 auto 时为 `None`。
5. `db_reference_mode=auto` 不比较上次解析的 `db_reference`；manual 比较模式与用户指定值。
6. 数值复用 `_PRESET_MATCH_REL_TOL` / `_PRESET_MATCH_ABS_TOL`（1e-9）；布尔只比布尔；枚举/字符串精确匹配。
7. 部分预设补丁先按现有 `_apply_preset` 语义应用，再用应用后的 `_collect_preset()` 建立基准。禁止把「缺字段」直接判成一致。
8. 内建目录是补丁，不是完整状态。RPM、dB 参考、未出现在补丁里的轴值：应用后以面板实测为准进入快照。

### 5.3 FFT（`kind=fft`，`_collect_preset`）

| 分类 | 键 |
| --- | --- |
| 参数 | `window`, `nfft`/`nfft_mode`, `t_win_s`, `overlap`（百分数）, `avg_mode`, `avg_overlap`, `amp_y`, `db_reference_mode`, 手动时的 `db_reference` |
| 坐标 | `x_*`, `y_*`（`autoscale` 映射到 `x_auto`） |
| 不参与 | `remark`；信号选择；`fs`；加权；`nfft_effective`；缓存/计算状态；荐角标 |

### 5.4 FFT vs Time（`kind=fft_time`）

| 分类 | 键 |
| --- | --- |
| 参数 | `window`, `nfft`/`nfft_mode`, `t_win_s`, `overlap`（百分数）, `amplitude_mode`（`Amplitude dB` / `Amplitude`）, `db_reference_mode`, 手动时的 `db_reference` |
| 坐标 | `x_*`, `y_*`（含 `freq_*` 别名）, `z_auto`/`z_floor`/`z_ceiling`（含 `dynamic` 别名） |
| 不参与 | `cmap`（面板固定 `_FIXED_CMAP`）；硬编码 `remove_mean=True`；加权；`fs`；信号；`nfft_effective`/`nfft_preview` |

`current_params()` 的 `amplitude_mode` 是小写 `amplitude_db`/`amplitude`，**不得**拿来和 `_collect_preset` / 内建补丁互比。

### 5.5 Order（`kind=order`；catalog 方法 `order_time`）

| 分类 | 键 |
| --- | --- |
| 参数 | `max_order`, `order_res`, `time_res`, `window`, `nfft`/`nfft_mode`, `amplitude_mode`, `samples_per_rev`, `rpm_factor`, `rpm_mode`, `manual_rpm`, `db_reference_mode`, 手动时的 `db_reference` |
| 坐标 | `x_*`, `y_*`, `z_*` |
| 不参与 | 加权；`fs`；信号；`nfft_effective`/`nfft_preview` |

内建补丁不含 RPM。加载内置不改 RPM；基准快照保留当时面板 RPM，之后改 RPM 记参数差异。

### 5.6 FRF（`kind=frf`；`_collect_preset` = `current_params()`）

| 分类 | 键 |
| --- | --- |
| 参数 | `estimator`, `window`, `t_win_s`, `overlap`（分数 0–1）, `nfft_mode`, `nfft`, `magnitude_scale`, `frequency_scale`, `phase_mode`, `coherence_threshold`, `fade_low_coherence` |
| 坐标 | 无。不弹坐标保留框，不画黄点。 |
| 不参与 | 硬编码 `periodic_window`/`detrend`；输入输出信号；时间范围组 |

### 5.7 悬停比较

- 当前基准槽：当前 `_collect_preset()` vs 基准快照。
- 其他槽：当前值 vs 该槽有效载荷（override 否则 builtin）经同一套归一化后**该槽实际拥有的可比键**。槽未声明的键既不当一致也不当差异。
- 空自定义槽无载荷，不显示虚假「一致」。

## 6. 单位兼容矩阵

幅值单位或 dB 参考意图变化时，旧幅值数字不能沿用。不在本任务做数值换算。

| 方法 | 幅值意图键 | 不兼容轴 | 仍可保留 |
| --- | --- | --- | --- |
| FFT | `amp_y`；`db_reference_mode`；manual 的 `db_reference` | Y | X |
| FFT vs Time / Order | `amplitude_mode`；同上 dB 参考 | Z | X、Y |
| FRF | 无轴 | — | — |

「使用预设范围」采用目标预设自身范围。旧预设省略幅值范围且切换单位时，两条应用路径都必须给出目标单位的安全自动范围，不能留下旧单位的手动值。现成路径：`contextual_fft._on_amp_y_unit_changed` 与 `_axis_defaults.z_range_for`。
只有不兼容轴而没有可保留轴时，禁用「保留手动范围」，默认聚焦「使用预设范围」；仍允许取消。

冲突判定只看当前手动轴，且目标应用会改变其有效范围或让其变回自动。所有轴自动、目标不改有效范围、只改未启用数值时不弹窗。构造默认值恰为手动范围也按手动范围保护。

## 7. 画布回写边界（已取证，不再是 UNKNOWN）

黄点只认 Inspector 面板坐标，即以 `_collect_preset()` 的规范轴键为准。

| 路径 | 代码 | 是否算面板手动范围 |
| --- | --- | --- |
| 用户改 Inspector 轴开关/上下限 | 各 Contextual 轴控件 | 是 |
| 热图 colorbar 拖动 / 双击恢复 | `_analysis_mixin._on_analysis_levels_dragged` → `ctx.apply_params({z_auto: False, z_floor, z_ceiling})` 并 `_sync_active_analysis_params` | 是（时频/阶次 Z） |
| 画布平移、滚轮、框选缩放 | `viewport_intent_committed` → `_commit_analysis_pane_viewport` 只写 `pane.xlim`/`ylim` | 否。相机视口与预设轴分离；本任务不打通 |
| FFT 时域预览范围 | `_on_fft_preview_range_changed` | 否。那是分析时间预览，不是预设 X |
| FRF 面板 | 无轴 spin，无 colorbar echo | 无黄点、无保留框 |

发现回写缺口时先记入 Plan 执行记录，不把本任务扩大成相机状态重构。colorbar 回写后必须刷新黄点，且不得 reverse-match 到自定义。

## 8. 视觉契约

- 仅当前基准槽蓝色高亮（沿用 `QPushButton[role="preset-load"][applied="true"]`）。
- 黄点/紫点都在按钮内部右上角；默认直径 7 逻辑像素、间距 4 像素，紫左黄右。
- 同时有两类差异显示两点，不用第三种混合色，不加「轴/参」文字角标。
- 没有差异不显示色点。改回基准有效值，对应色点立刻消失。
- 悬浮卡片保留「分析参数 / 坐标轴快照 / 状态判断」。前两块展示**被悬停槽或基准**的快照，不能混入当前值仍称快照。分析参数芯片键表与 §5 对齐，补 `t_win_s` / `nfft_mode` / dB 参考；不把不参与字段画进快照。
- 状态项保留「一致 / 有差异」文字；仅差异项使用对应细边框。主体文字、蓝色数值和分组外框保持现状。不要复用 `presetChip[warn="true"]` 那一套单色 warn 来区分两类差异。
- 琥珀色参考 `#e8ae48`，紫色参考 `#a28acb`；落地前核对现有主题与真实 Qt 观感。QSS 状态规则禁止 `border:` 简写（`tests/ui_kit/test_qss_border_shorthand.py`）。
- 悬停非基准槽仍可看该槽与当前值的比较，但它不会获得当前基准色点或高亮。
- 「基准快照，槽位已更新」/「原基准已不可用」/「未关联预设」只在实际出现时显示。
- 当前基准槽隐藏推荐角标（`presetRecommendBadge` 现位于右上 `width-4, 2`，会与色点抢角）；其他推荐槽沿用现有样式。
- 不加全局大图例。`accessibleName` / `accessibleDescription` 含基准名及两类差异。卡片文本保证不只靠颜色辨认。

## 9. 用户动作状态机

| 动作 | 参数结果 | 基准结果 | 提示 |
| --- | --- | --- | --- |
| 点击不同内置/已保存槽 | 应用目标，可能合并保留范围 | 成功后切到目标快照 | 存在手动范围冲突才询问 |
| 点击带差异的当前槽 | 重新应用当前槽内容 | 成功后更新基准快照 | 同上 |
| 点击完全一致且槽未更新的当前槽 | 不变 | 不变 | 不弹、不重算、不恢复默认 |
| 修改参数/坐标（含 colorbar 回写） | 按现有控件语义生效 | 保持原基准 | 仅刷新色点/状态 |
| 修改后恰好匹配其他槽 | 正常生效 | 仍保持原基准 | 不自动跳槽 |
| 点击空自定义槽 | 进入现有保存流程 | 保存成功后认领该槽 | 保存取消则全部不变 |
| 右键保存当前到槽 | 写入当前用户意图 | 保存成功认领该槽，无差异 | 保留现有覆盖确认语义 |
| 右键「重置此槽为内置」 | 不修改当前参数 | 当前 View 保留原基准快照 | 仅更新槽内容；与恢复面板默认分开 |
| 显式「恢复面板默认参数」 | 应用 `_default_params`（构造时 `_collect_preset()`；FRF 现为稳健补丁） | 成功后清空基准 | 同样检查手动范围冲突；文案不得谎称切换到某槽 |
| 切换 View / 打开项目 | 恢复保存的参数与基准 | 恢复对应 View | 不弹询问 |

菜单现文案「重置为默认」改为「重置此槽为内置」，并新增「恢复面板默认参数」。二者不得并存为同义项。
以上替代当前「第二次点击恢复默认」。必须同步 hints / quickref 与旧测试，不能两种规则并存。

内置显示名：FFT/时频/阶次为 频率 / 均衡 / 时间（catalog `torque`/`vibration`/`transient`）。FRF 为 稳健 / 低频 / 快速。自定义槽恒为槽 4，显示名可被用户重命名，身份仍是 4。

## 10. 坐标保留与事务

### 10.1 确认框

标题「切换预设」；正文「切换预设时保留手动坐标范围？」；列出实际冲突轴。
说明「其余参数按新预设更新；本次选择仅对这次切换有效」。
恢复面板默认操作改为「恢复默认参数」，不能谎称切换到某槽。

- **保留手动范围**（默认按钮）：保留当前兼容手动轴的 `auto=false` 与范围；其他参数应用目标。不兼容幅值轴转自动，正文明确列出。
- **使用预设范围**：完整应用目标范围。
- **取消 / Esc / 关闭**：完全不修改任何业务状态。

不增加「记住选择」，不自动触发计算。保留后目标槽成为基准，黄点由当前值与目标快照差异决定；不是只要点过保留就强制亮黄点。

现实现取消分支调用 `sync_match()`，会把高亮推到自定义——必须删除这条副作用。
现实现保留后若 `params != requested` 再 `sync_match()`，同样会丢掉目标槽高亮——必须改为提交目标基准后一次投影。

### 10.2 原子提交

先读取当前与目标快照 → 归一化并验证 → 确认 → 构建最终参数 → 一次应用 → 成功后提交基准 → 一次刷新色点和结果有效性。
确认之前不得先亮目标按钮；取消不得调用会重新认领其他预设的 reverse match。
应用异常不得留下半套控件或新基准；预检避免可预知失败，异常时恢复原参数/基准，保持错误可观察，不吞掉编程错误。
用户加载走现有 `_apply_preset` 的 compute/display 分流；View/项目 restore 走 `apply_params`（不发射计算、不弹框）。
快照捕获/恢复不发计算请求，不扩大现有 `_applying_preset` 之外的跨模块写入。
`presets.py` 里已有的 `.connect(lambda …)` 不得再增加；若改动那两处连接，改 `functools.partial`。

## 11. 持久化

- `AnalysisViewState._SCHEMA`：8 → 9。新字段按存在与否迁移，缺省 = 无基准。
- `.tlproj` 顶层 schema 不变。`project_io` 把 `analysis_views[].views[]` 当 `to_dict()` 不透明字典搬运，因此必须在 `AnalysisViewState.to_dict` / `from_dict` 读写 `preset_baseline`。
- 基准不得进入 DSP / cache key / `compute_params`。
- 旧测试里写死 `payload["schema"] == 8` 的断言随 schema 更新：`tests/ui/test_analysis_view_state.py`、`tests/test_project_io_analysis_views.py`、`tests/ui/test_analysis_source_scope.py`。

## 12. 帮助表面

用户可见交互有增删改，必须同步：

- `mf4_analyzer/ui/hints.py`：`preset.keep_manual_axes`、`preset.right_click`；按需增加基准/色点发现提示。
- `mf4_analyzer/ui/quickref.py`：删除「再次点击当前预设恢复默认」，改为重新应用 + 右键恢复面板默认。
- 应用内帮助：仅当现有「智能预设」页声称高亮即完全匹配或二次点击恢复默认时才改 `mf4_analyzer/help/TraceLab-使用说明.html`。四个分析指南目前只说「挑预设」，不强制改。

不宣称「高亮即完全匹配」。

## 13. 验收案例

A1 均衡加载后只调轴：均衡高亮、黄点、参数一致、坐标有差异。
A2 只调分析参数：均衡高亮、紫点；两类都调显示双点。
A3 逐项改回：相应点消失；自动模式的隐藏上下限变化不亮点。
A4 均衡→频率，保留手动轴：频率高亮，坐标不同才黄点；无意外紫点。
A5 同一操作选使用预设：完整目标，差异归零；下一次冲突重新询问。
A6 取消、Esc、关闭：参数、基准、推荐标记、缓存有效性和计算请求数全部不变。
A7 再点带色点基准：重新应用；再点完全一致基准：无操作。
A8 恢复面板默认与重置槽位是两个独立动作，后者不动当前坐标。
A9 自定义保存/加载/取消/清空与槽被别处重写：按第 4、9 节执行。
A10 View A/B 各有不同基准及范围；切换、复制、项目往返后独立恢复；新/旧 View 不串状态。
A11 单位切换只保留兼容轴；部分旧预设不会把旧单位的手动范围留到新单位。
A12 归一化覆盖别名、数值容差、Auto NFFT、自动 dB 参考、未知字段和空交集。
A13 FRF 基准/参数色点可用，不出现虚假的 XYZ 保留提示。
A14 Cocoa 实际按钮、卡片、确认框在窄 Inspector 与高缩放下不裁字、不遮挡；Windows 单列验证。
A15 colorbar 拖成手动 Z：基准不变、黄点亮、不跳到自定义。画布平移不产生黄点。

## 14. 必须改写的旧断言

这些测试把「未匹配 → 自定义高亮」或「二次点击恢复默认」当成合同，实现时改期望，不得靠固定 fixture 续命：

- `tests/ui/test_inspector.py`：`test_fft_builtin_preset_second_click_restores_defaults`、`test_order_builtin_preset_second_click_restores_defaults`、`test_fft_time_builtin_preset_second_click_restores_defaults`、`test_fft_manual_edits_land_on_the_matching_builtin_preset_name`、`test_fft_edit_away_from_a_preset_and_back_restores_its_name`、`test_frf_parameter_returning_to_a_builtin_relights_it`、`test_view_restore_payload_names_the_matching_slot`、`test_view_restore_of_an_unnamed_state_falls_to_the_custom_slot`、`test_saving_current_params_to_a_slot_lights_it_and_refreshes_the_cache`、`test_slot_payload_cache_follows_the_shared_slot_bus`、`test_reverse_match_prefers_the_selected_slot_then_the_lowest`、`test_reverse_match_ignores_slots_that_describe_another_panel`、`test_reverse_match_does_not_disturb_the_unit_recommendation_badge`、`test_preset_hover_card_status_agrees_with_the_highlighted_slot`
- `tests/ui/test_preset_axis_preservation.py`：保留后 `_selected_slot == _matching_slot()` 这条会把 reverse-match 钉死，必须改成「目标槽保持基准 + 黄点」
- `tests/ui/test_quickref.py`：若手势文案变更

`preset_value_matches` / `preset_params_match` 的容差测试保留。`tests/ui/test_task6_preset_guard.py` 的加权不参与规则保留。

## 15. 仍开放、但不阻塞设计

- 琥珀色/紫色在真实 Cocoa / Windows Qt 上的最终观感：实现步骤 4 用截图校准，允许微调到主题，不允许改成第三种语义。
- Windows 冻结包视觉：无环境则记 UNKNOWN，不用 Cocoa 代替。
- 若步骤 0 对照发现 `_collect_preset` 键集已漂移：先改本文分类表，再写代码。
