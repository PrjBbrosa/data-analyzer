# 批处理真机验收问题 · 设计

- 日期：2026-08-03（切片特性真机验收后的第二轮）
- 前序：[切片导出 + 统计标记设计](2026-08-03-batch-heatmap-slice-and-stat-marker-design.md)（v3）
- 基线：`main` @ `d60cdea` + 切片特性七个阶段（工作区未提交）

真机验收暴露 9 个问题。**其中 3 个是同一个根因**，3 个是切片特性引入的新回归，
其余是既有的 UI/预设问题。本文按根因分组，不按报告顺序。

> **验证条件的限制**：本机 Qt 缺字体（`QFontDatabase: Cannot find font directory`），
> offscreen 渲出来是空白图。所有渲染类结论都是「代码 + 度量」推断，
> **视觉结论以真机截图为准**，修完必须回真机复验。

---

## 组 A · 一个文件裂成多个子来源

### A0 现象与根因

`_loaded_groups`（[source_adapters.py:496](../../../mf4_analyzer/io/source_adapters.py#L496)）允许
一个物理文件返回**多个 `LoadedSource`**，各带自己的 `group_id` 与 `label_suffix`
（典型触发：HDF 内部按采样率分组）。批处理把它们当成**互相独立的来源**，
于是同一个通道在「4 个子来源」里只出现在其中 2 个。

这一条派生出三个互不相似的用户可见故障：

| 报告 | 表现 |
| --- | --- |
| A1 | 信号选择器 18 项全灰，选不动 |
| A2 | 点预览显示无法预览 |
| A3 | 预览标题出现 `unresolved-source:hdf:3af2470a39ba076234c87567` |

### A1 · 选择器全灰

`_refresh_signal_universe`（[input_panel.py:1003](../../../mf4_analyzer/ui/drawers/batch/input_panel.py#L1003)）
把「不在所有来源里」的通道归入 `partial`；
`_rebuild_list`（[signal_picker.py:693](../../../mf4_analyzer/ui/drawers/batch/signal_picker.py#L693)）
对 partial 项做 `setEnabled(False)` + 清 `Qt.ItemIsEnabled`。
截图里每项后缀 `(1/2)` 就是这个。

两处具体缺陷：

1. **没有任何解释**。用户看到「匹配 18」却一个都点不了，屏幕上没有一个字说明原因，
   也没告诉他「每来源可用」策略就能解开。
2. **RPM 通道选择器永远解不开**。目标信号至少在
   `selectable=self.target_policy() == "available_per_source"` 下能解禁，
   而 RPM 那一行调 `set_partially_available(partial)` **不传 `selectable`**
   （[input_panel.py:1027](../../../mf4_analyzer/ui/drawers/batch/input_panel.py#L1027)），
   恒为不可选。这与 runner 的能力矛盾：`_rpm_values`
   （[batch.py:4989](../../../mf4_analyzer/batch.py#L4989)）明确支持跨来源 RPM
   —— 另一个来源的 RPM 通道会按时基 `np.interp` 到目标来源上。

**D-A1 · RPM 选择器与目标信号共用同一条策略。**
`set_partially_available(partial, selectable=self.target_policy() == "available_per_source")`。
理由：两者的可用性语义相同，"部分来源才有" 在 per-source 策略下本就是允许的。

**D-A2 · 无可选项时，选择器弹层内给出成因与出口。**
当 `available` 为空且 `partial` 非空时，在弹层底部（现有 "已选 N · 匹配 M" 那一行附近）
显示一行说明 + 一个直接切换策略的按钮：

```
18 个通道只存在于部分来源，「所有来源共有」策略下不可选
                                        [ 改用「按来源可用」]
```

不自动切换策略 —— 那会改变产出集合，必须是用户的显式动作。

> **2026-08-03 实施期修正两处文案**：
> 按钮原写「每来源可用」，但下拉里的真实条目是**「按来源可用」** ——
> 按钮指向一个不存在的选项比文档不一致更糟，以真实 UI 为准。
> 说明行原想写「该文件按采样率拆成了 N 个子来源」，但选择器手里只有
> `"(1/4)"` 这种标签串，要得到 N 得去解析它；改成点明**当前拦路的策略**
> （选择器确实知道这个）。子来源数量放在预览的提示里 ——
> 那里 `sheet` 能诚实地数出来。

### A2 · 预览取第一组

`preview_outputs` 无条件 `representative = groups[0]`
（[batch.py:722](../../../mf4_analyzer/batch.py#L722)），不判断这一组的来源里
到底有没有用户选中的通道。第一个子来源没有 → 预览空。

规划阶段刻意 no-load，所以 `batch.py` 自己拿不到通道清单 ——
但**探针数据在 UI 里是现成的**（`per_file_channel_sets()`）。

**D-A3 · 让调用方把已知的「来源→通道集合」喂给规划器。**

```python
def preview_outputs(self, preset, output_dir, *, source_channels=None): ...
```

`source_channels: Mapping[source_key, frozenset[str]] | None`。
给了就选**第一个所有成员通道都可用的组**，并把 `ordinal` 设成它的真实序号；
一个都不合格时仍回退 `groups[0]`，但在 `BatchRepresentativeGroup` 上标一个
`channel_available: bool = True/False`，让 UI 能说清楚。

参数可选 = GUI-free 契约不变，既有调用方与测试不受影响。

**D-A4 · 预览失败要说明原因。**
`channel_available=False` 时，预览对话框的提示从「预览不可用」改成
「代表来源 <name> 不含所选通道；该文件按采样率拆成了 N 个子来源」。
沉默的失败是这次验收里重复出现的模式（另见 D1、D-D1）。

### A3 · 机器串泄漏

同一个概念有**两套过滤规则**：

| 面 | 规则 | 结果 |
| --- | --- | --- |
| 图表标题 | `_page._is_human_group`，滤掉 `default` / `unresolved-source:` / `file_id:` | 干净 |
| 预览对话框 / 组显示名 | `batch_grouping._source_display_name`（[batch_grouping.py:75](../../../mf4_analyzer/batch_grouping.py#L75)），**只滤 `default`** | 泄漏 |

commit `ae6982d`（strip machine tokens from export chrome）只修了图表那一侧。

**D-A5 · 收敛成一个事实源。**
把 `_MACHINE_GROUP_IDENTITIES` / `_MACHINE_GROUP_PREFIXES` / `_is_human_group`
移到 GUI-free 的 `batch_grouping.py`，`_page.py` 改为 import。
`_source_display_name` 用它替换现在的 `!= "default"` 判断。

**影响面**：`RenderGroup.display_name` 只喂 UI 文本（预览对话框、任务列表），
输出文件名走 `identity.stem`，**产物字节不受影响**。需要一条测试守住这一点。

---

## 组 B · 切片渲染回归（本次特性引入）

### B1 · 左轴标题压住刻度

**实测**（同一份数据、同一份参数，只切换切片开关）：

| | 主图左轴宽度 |
| --- | --- |
| 切片关 | **95.4 px** |
| 切片开 | **57.4 px** |

`_slice_alignment_callback`（[_builder.py:457](../../../mf4_analyzer/batch_render_qt/_builder.py#L457)）
的做法是 `setWidth(None)` → `activate()` → 取两轴 `width()` 的 max → `setWidth(target)`。

问题出在 `width()` 的来源：pyqtgraph 的 `AxisItem._updateWidth()` 依赖
`self.textWidth`，而 `textWidth` **只在绘制时**（`generateDrawSpecs`）更新。
`_apply_tick_density` 又在 `show_and_settle` 末尾才把最终刻度串 `setTicks()` 进去。
于是 align 量到的是**上一次绘制的旧刻度**的宽度，钉死之后再也不会重新变宽。

**D-B1 · 不依赖 `axis.width()`，直接按刻度串量。**

```python
metrics = QFontMetricsF(chart_font(self.theme.axis_font_pt))
needed = max(metrics.width(text) for _v, text in current_tick_labels(axis))
needed += tick_length + label_height + padding
```

用两轴各自算出的 `needed` 取 max 再钉。这样与「什么时候绘制过」无关。

**D-B2 · 对齐必须排在 `_apply_tick_density` 之后。**
`show_and_settle` 里确定顺序，并加一条测试：刻度串换成更长的之后再跑对齐，
左轴宽度必须 ≥ 最长刻度串所需宽度。

**待真机确认**：colorbar 标题压住色标刻度看着是同一类问题，但 colorbar 不经过对齐
回调，**很可能是既有缺陷**。修 B1 之后回真机看它是否还在；还在就单独立项。

### B2 · 图例被裁

图例卡宽度是**硬编码**的 `content_width=86.0 * scale`
（[_builder.py:1971](../../../mf4_analyzer/batch_render_qt/_builder.py#L1971)），
定位又是贴 colorbar 左边缘、不检查页面右边界
（[_builder.py:1990](../../../mf4_analyzer/batch_render_qt/_builder.py#L1990)）。
`1500.0 Hz` 加色块加内边距放不下 86 px，于是溢出被页面裁掉。

**D-B3 · 图例按内容量宽，并让它参与右侧留白的决定。**

1. 用 `QFontMetricsF` 量出最宽一行（色块 + 文本 + 内边距）与标题，取 max 作为卡宽。
2. 右侧预留宽度改成 `max(colorbar 右侧总宽, 图例宽 + 间距)`；
   **两行同时**按这个值留白，对齐不被破坏。
3. 卡片位置再对页面右边距做一次夹取，任何情况下不越过 `ci.contentsMargins().right()`。

代价是图例较宽时主图会略窄一点 —— 这比裁掉文字好，且只在长标签时发生。

### B3 · 切片曲线与标记线不清晰

三个叠加因素，都属实：

1. **配色相近**。冷色系 `#2563eb`(蓝) 与 `#4f46e5`(靛) 色相差太小，
   截图里两条几乎分不出。
2. **白底衬压过彩线**。标记线是 3.6 px 白 + 2.0 px 彩，两侧各留 0.8 px 白边；
   在 turbo 深底上整体读作一条白线，颜色信息丢失。
3. **三条噪声曲线挤在一个 322 px 面板里**，本身就密。

**D-B4 · 两套色系各自重挑，保证同族内可辨。**
约束条件：同族 4 色两两之间在感知色差上要能区分，且都要能压住 turbo。
候选（待真机确认）：

| 族 | 顺序 |
| --- | --- |
| 暖（固定时间） | `#dc2626` `#ea580c` `#a16207` `#be185d` |
| 冷（固定 Y） | `#2563eb` `#0891b2` `#4338ca` `#0f766e` |

**D-B5 · 标记线加粗彩线、加宽白衬的比例。**
2.0/3.6 → **2.6 px 彩线 + 5.2 px 白衬**（两侧各 1.3 px 白）。
彩线占比从 56% 提到 50% 但绝对宽度增加 30%，颜色能读出来。
这是本轮最需要真机迭代的一处，先按此改，看图再调。

**D-B6 · 曲线数 ≥ 3 时线宽降一档。**
`options.line_width * 0.85`，减轻拥挤。不用透明度 —— 白底上会变灰、更难认。

---

## 组 C · 既有 UI / 预设

### C1 · 移除批处理的手动 RPM

**范围**：仅批处理。单次分析侧的 RPM 控件不动。

涉及面：

| 层 | 位置 |
| --- | --- |
| UI | `method_buttons.py`：`_FIELDS["order_time"]` 去掉 `rpm_mode`/`manual_rpm`；删两个控件、`_sync_rpm_mode`、标签、get/apply 分支 |
| runner | `batch.py:3787`（`rpm_source` 的 manual 分支）、`batch.py:4989`（`_rpm_values` 的 manual 分支） |
| 校验 | `batch_validation.py:445`（`invalid_manual_rpm`）、`:543`（`effective_rpm`） |
| recipe | `batch_recipe.py`：`METHOD_PARAM_FIELDS["order_time"]` 与 `_FLOAT_PARAM_FIELDS` |
| sheet | `sheet.py:84`/`:124` 的错误文案、`:1342` 的 RPM 必需性判断 |

**D-C1 · 旧 recipe 里的 `rpm_mode`/`manual_rpm` 要显式丢弃并告警，不能当未知字段留着。**
若直接从 `METHOD_PARAM_FIELDS` 删掉，它们会掉出 `KNOWN_PARAM_FIELDS`，
`normalize_batch_params` 的「未知字段原样保留」规则反而会把它们**留在 params 里**，
而 runner 已经不再读 —— 变成静默的行为改变。

做法：两个字段**保留在 `KNOWN_PARAM_FIELDS`**（用一个 `_RETIRED_PARAM_FIELDS` 集合），
归一化时对 `order_time` 无条件 `pop`；若被丢弃的是 `rpm_mode="manual"`，
追加迁移警告，措辞对齐既有的 `_legacy_image_format_warning`：

```
旧预设的手动 RPM 已移除；批处理阶次分析需要指定 RPM 通道。
```

之后若没有 RPM 通道/信号，既有的「rpm channel is required」错误自然会拦住。

### C2 · 阶次窗函数一致化

**现状**：`analysis_presets._PATCHES["order_time"]` 的三个预设**都不声明 `window`**
（[analysis_presets.py:96](../../../mf4_analyzer/analysis_presets.py#L96)），
注释写「COT 保留自己的 hanning 默认，partial apply 不动实时窗」。
而 `fft` / `fft_time` 的「频率」预设是 `flattop`。
所以在阶次下选「频率」，窗仍是 hanning。

**D-C2 · 三个阶次预设补齐 `window`，与另外两个方法一一对齐。**

| 预设 | fft / fft_time | order_time（改后） |
| --- | --- | --- |
| 频率 (torque) | `flattop` | **`flattop`** |
| 均衡 (vibration) | `hanning` | **`hanning`** |
| 时间 (transient) | `hanning` | **`hanning`** |

可行性已确认：COT 的窗来自 `get_analysis_window`
（[order_cot.py:147](../../../mf4_analyzer/signal/order_cot.py#L147)），
`fft.py` 支持 `flattop`，无 scipy 依赖。

理由：flattop 换的是「幅值准确度」，阶次分析同样关心离散阶次的幅值准确度，
原注释里「COT 有自己的默认」并不构成不给预设声明窗的理由。

**影响**：`analysis_presets` 由单次分析与批处理共用，所以**单次分析的阶次「频率」预设
也会从 hanning 变成 flattop**。这是本条的目的（一致），但要在发布说明里写清楚。
`window` 本来就在 `METHOD_PARAM_FIELDS["order_time"]` 里，
所以应用该预设后 fingerprint 会变 —— 已跑过的阶次输出在 resume 下会被判为过期，属预期。

### C3 · 移除预设来源提示

`analysis_panel.py:281` 的 `_preset_source_note`
（`"频率" 来自单文件 fft 预设槽 1；这里不维护第二份名称。`）删除。
标题旁已有「与单次分析同步」徽章表达同一件事，这行是冗余。

**D-C3** · 连同 `_preset_source_note` 控件一起删，不要只清空文本 —— 留一个空 QLabel
会在紧凑布局里继续占高度。

### C4 · 预览对话框的 `?` 按钮

运行时实测 `windowFlags() & Qt.WindowContextHelpButtonHint == True`
—— Windows 给 `QDialog` 的默认按钮，`preview_dialog.py` 没有清除。它不接任何行为。

**D-C4** · `setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)`。
仓库里其他自建对话框应一并检查，避免只修一个。

---

## 组 D · 图内统计

### D1 · 设定了 ±80 mm，产出却是全程

**已复现的机制**（直接调 `plan_chart_statistics`）：

| 配置 | 实际统计区间 | 最小值 | N |
| --- | --- | --- | --- |
| `range_mode="full"` | `[-95.86, 95.51]` | **-2771**（边缘瞬态） | 6000 |
| `range_mode="custom"`, `±80` | `[-79.97, 79.97]` | 780 | 5015 |
| `range_mode="custom"`, 边界为 `None` | `[-95.86, 95.51]` | **-2771** | 6000 |

第 1 行与第 3 行都精确复现了截图 A。**裁剪逻辑本身是对的**；
问题在于两条静默路径：

- `_configuration`（[batch_statistics.py:112](../../../mf4_analyzer/batch_statistics.py#L112)）
  在 custom 但边界缺失时返回 `(True, "custom", None, None)`，
  `_series_rows` 随即当作全程，**不产生任何 diagnostic**。
- 卡片标题显示的是**实际用到的数据跨度**，不是**请求的区间**。
  `-95.86 ~ 95.51 mm` 既可能是「自动，数据就这么宽」，也可能是
  「设了 ±80 但没生效」——**两种情况长得一模一样**。

> 注：`batch_validation` 已经会拦 `custom` + 非有限边界（`invalid_range`），
> 所以第 3 行走不到真实运行。这意味着截图 A 那次实际上是
> **`range_mode="full"`（自动勾着）**。但无论上游为何，
> 「看不出自己处在哪个模式」才是让这个问题留到验收阶段的原因。

**D-D1 · 卡片标题必须写明模式，而不只是数据跨度。**

```
图内统计  全时段 · 实际 -95.86 ~ 95.51 mm
图内统计  设定 -80 ~ 80 mm · 实际 -79.97 ~ 79.97 mm
```

自动时写「全时段」，自定义时写「设定 a ~ b」，两种都跟上实际跨度。
截图 A 若如此显示，一眼就能看出是自动模式。

**D-D2 · 堵死静默降级。**
`_configuration` 增加一个「请求 custom 但边界不可用」的返回状态，
`plan_chart_statistics` 为该 panel 产出
`chart_statistics.custom_range_unavailable` 诊断并**不出统计行**
（与既有的 `multiple_x_reversals` 同样 fail-closed），
而不是悄悄按全程算。诊断会经 `spec.diagnostics` 画成红卡，
并由 `batch.py:3477` 汇入任务 warnings。

**D-D3 · `apply_params` 缺 `chart_statistics` 键时不要静默重置。**
`ChartStatisticsPanel.apply_params` 在 params 不含该键时会把卡片恢复成
「关闭 + 自动」（[chart_statistics_panel.py:168](../../../mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py#L168)）。
配合我们自己的归一化规则（未启用即从 params 移除），
一次「关闭→再打开」就会丢掉用户填过的区间。
改为：缺键时**保留当前区间数值**，只把启用态置为关闭。

---

## 优先级

| 级别 | 条目 | 理由 |
| --- | --- | --- |
| P0 | B1 | 本次引入的回归，让每张切片图都不能看 |
| P0 | A1 / A2 / A3 | 同一根因，直接堵死用户的真实工况 |
| P1 | D1 | 静默出错，且已经导致一次错误的分析结果 |
| P1 | B2 | 本次引入，图例被裁 |
| P2 | B3 | 本次引入，可读性；需真机迭代 |
| P2 | C1 / C2 / C3 / C4 | 既有问题，行为明确，风险低 |

---

## 验收

**组 A**
1. 一个 HDF 拆成 4 个子来源、通道只在 2 个里 → 「每来源可用」策略下目标信号与 RPM 通道**都能选**
2. 「所有来源共有」策略下全灰时，弹层给出成因说明 + 切换按钮
3. 预览选中的代表组含所选通道；都不含时给出具体原因而非「预览不可用」
4. 预览标题不出现 `unresolved-source:` / `file_id:` / `default`
5. 组显示名的变化不影响任何输出文件名或产物字节

**组 B**
6. 切片开启时主图左轴宽度 ≥ 切片关闭时的宽度（当前 57.4 vs 95.4）
7. 刻度串换长后重跑对齐，左轴仍能容纳最长刻度串
8. 图例整体落在页面右边距内，最长标签不被裁
9. 真机：标记线在 turbo 深底与亮区都能看出颜色；三条切片曲线两两可辨

**组 C**
10. 批处理阶次面板无手动 RPM；旧 recipe 带 `rpm_mode="manual"` → 被丢弃 + 迁移警告
11. 阶次「频率」预设应用后窗函数为 flattop，与 FFT / FFT-vs-Time 一致
12. 预设来源提示行消失且不占高度；预览对话框无 `?` 按钮

**组 D**
13. 卡片标题在自动/自定义两种模式下文案不同，且都带实际跨度
14. custom + 边界不可用 → 红色诊断卡 + 无统计行 + warning，**不再静默按全程算**
15. 关闭再打开图内统计，之前填的区间数值仍在
