# TimeDomain 每数据源自定义横坐标与部分绘制优化计划

**状态：** 已经 Claude + Codex 双重审查并完成源码实施与 offscreen 定向验证；实现提交
`4db876b` 已在批处理提交 `26e422b` 之上合入本地 `main`（merge `4d88457`）。真实
macOS 前台验收仍待执行。全仓 pytest 已尝试，但被既有 Qt delegate 生命周期
SIGSEGV 中止，不能标记为全量绿色。

**范围：** 仅前台 TimeDomain 的自定义横坐标、分屏/叠加绘制、状态保存与图内诊断。另一
session 负责的下拉搜索、导出白底、导出设置折叠（原需求 1–3）已经在 `26e422b`
完成；本计划不重复实现、不改动 Batch 的任何代码，只把该提交作为集成与回归基线。
（注意：Batch 的现有策略并非“所有 source
共同具备 X 通道”——它已按名逐 source 解析，详见文末「风险与非目标」的修正条目。）

## 要解决的行为

当前 `_apply_xaxis()` 选中一个 `(fid, channel)` 后，把这个文件的 X 数组强加给所有已勾选曲线，并在任一文件长度不同的时候 toast 后整体中止。`_build_time_plot_data()` 又会在个别长度不同时静默退回 time，导致“应用时拒绝”和“构图时退回”两套语义并存。

目标是把“选择横坐标通道”解释为一个**逻辑通道名**：每个参与绘图的数据源都从自己的数据中寻找同名通道，并为自己的目标信号生成一对 `(x_i, y_i)`。不同文件的样本数不同本身不是错误。

特别是用户确认的叠加语义如下：

```text
文件 A：x_A[500], y_A[500]
文件 B：x_B[300], y_B[300]
                 ↓
叠加图：同一条物理 X 坐标轴，分别绘制 (x_A, y_A) 与 (x_B, y_B)
      X 可视范围 = 两条成功曲线有限 X 值的并集
```

这不是把两条曲线按索引对齐，也不是把 X 归一化为 0–1；因此 A/B 的长度不同仍能正确叠加。现有 `TimeDomainCanvasPG.plot_channels()` / overlay axis 已按每条曲线接收独立 `t, sig`，可承载这一渲染合同。

## 固定设计合同

1. **解析范围。** 新选中的“通道横坐标”保存为 `resolver=per_source_name, channel=<name>`；每次绘图只针对当前 checked 曲线的 source 解析。下拉项展示可用覆盖度（例如 `RackPos · 3/4 个数据可用`），部分可用仍可选。
2. **逐 source 对齐。** 成功条件是该 source 有同名 X 通道、X/Y 一维且等长、过滤后的共同 mask 后仍有有限样本。绝不为凑长度截断为 `min(len(x), len(y))`，也不把另一文件的 X 数组借给它。
3. **时间范围不变。** Inspector 的起止范围永远按每个 source 的 `FileData.time_array` 掩码；随后把同一 mask 应用于该 source 的 X/Y。这保证自定义 X 只是显示坐标而非采集时间语义。
4. **叠加正确性。** overlay 使用每条成功曲线自己的 `(x_i, y_i)`，共享 X master 的范围取所有成功曲线的 X 并集。平移、缩放、自动 Home 和 envelope 也使用这个并集；保留现有 overlay 的独立 Y 轴、网格和鼠标合同。
5. **X 单位——只做规范化相等，本次不做任何换算。** 判定复用既有的
   `mf4_analyzer/db_reference.normalize_unit`（`db_reference.py:153-172`）：它已明确
   写死「只做 canonical 形式相等、永不做换算」（`g` 不塌到 `kg`，`Pa` 不塌到 `kPa`），
   项目里也**不存在**任何单位换算表。因此本次的兼容判据就是
   `normalize_unit(u_a) == normalize_unit(u_b)`，不引入换算规则；需要换算时另开需求。
   空单位是事实、不是通配（沿用 `ui/drawers/batch/sheet.py:646` 的既有约定）：
   `("", "rpm")` 视为不兼容，不得被当成统一 rpm。不兼容的 source 标为
   `x_unit_incompatible` 并不绘制。图标题只显示成功共同单位，单位 metadata 优先、
   `channel_units` 兜底，且不重复加后缀。
   多个 ready source 先按 normalized unit 分组，选择成员最多的一组作为可绘制
   cohort；数量相同时按 checked source 的稳定顺序取第一组，其余标为
   `x_unit_incompatible`。这样 partial 结果确定且尽量保留更多曲线，不因遍历顺序漂移。
6. **部分成功而非报错。** 有些 source 缺通道、空、X/Y 无法对齐、单位不兼容或范围内无点时，其余曲线照常画。图卡固定状态区显示一次汇总，例如“已绘制 3/5 条；2 条未绘制”，可展开查看 source/通道/原因；全部失败则用现有空图提示呈现汇总。避免逐条 toast、弹窗和“看似成功但回退到 time”的混乱。
7. **同一 FileData 内真正不等长的未来数据。** 当前 loader 通常已将列插值到共同 DataFrame 时间轴。若后续导入模型暴露原始每通道时间戳，只有在可取得该通道自己的时间基准时才可做显式时间重采样/配对；本次不以静默截断替代它，先标为 `unaligned`。
8. **兼容持久化。** 已保存 View 中旧 `fid + channel` 表示的是“精确来源”，恢复时默认 `resolver=exact_source`，不改变历史图。新的 UI 选择才写 `per_source_name`；time range 的 draft/apply 边界仍保持原样。旧模式的绘图公式固定为：

   ```text
   exact_source:
       x = files[spec.source_fid].data[spec.channel]
       每条目标 Y 都继续与这一份 x 配对；等长才绘制，不等长标 unaligned
   ```

   即使另一个文件也有不同内容的同名 X，也不能在恢复旧 View 时自动改用它。

9. **选择载荷形状必须先定死（本计划的枢纽）。** 当前有三处硬编码 `(fid, ch)` 二元组：
   `xaxis_channel_data()` 直接返回 `currentData()`（`persistent_top.py:361`）、
   `_sync_xlabel_from_channel` 硬解包 `_, ch = data`（`persistent_top.py:333`）、
   View 恢复用 `combo.itemData(i) == (target_fid, target_channel)` 匹配
   （`_view_mixin.py:384`）。本计划既要按名聚合、又要保留旧 exact-source 可选，
   等于同一个 combo 内存在两种 itemData。**固定为一个带 tag 的三元组**：

   ```python
   ("per_source_name", None, channel)   # 新 UI 选择
   ("exact_source",    fid,  channel)   # 仅用于旧 state 兼容显示/恢复
   ```

   三处解包同步改为按 tag 分发；`set_xaxis_candidates()` 的 docstring
   （`persistent_top.py:370-371`，现写 `(fid, ch)`）一并更新。任何步骤开始写码前，
   这个形状不得再各自发挥。

10. **候选生命周期。** 覆盖度分母先取 checked 曲线的唯一 source；没有 checked 时回退
    当前 View attached sources，再回退全部 loaded sources，保留“先选 X、再选 Y”的工作流。
    每次候选刷新都重新注入当前已 apply/restored 且仍可定位的
    `("exact_source", fid, channel)` 项，不能在文件加载或通道编辑后把 legacy selection
    从 combo 中冲掉。`per_source_name` 即使当前没有 provider 也保留 applied spec 并显示
    0/N 与图内诊断，不静默回退 time。

11. **序列化不变量。** 所有 writer/reader 使用同一张表；未知 resolver 或残缺 payload
    确定降级到 time，不允许各入口自行猜测：

    | mode | resolver | fid | channel |
    | --- | --- | --- | --- |
    | `time` | `None` | `None` | `None` |
    | `channel` | `per_source_name` | `None` | 必填 |
    | `channel` | `exact_source` | 必填 | 必填 |
    | legacy `channel` | 缺失 | 必填 | 必填；读取为 `exact_source` |

## 现状基线（已核对代码，避免重复劳动）

以下几点**已经是现状**，实施时是“保持不变”而不是新增，别再造一遍：

- 时间范围掩码已按每个 source 自己的 `fd.time_array` 生成（`window.py:2782`），
  合同 3 无需改动语义。
- `_cached_is_monotonic(data_id, name, t_arr)`（`overlay_axes.py:488`）本来就逐曲线，
  不存在“复用另一 source 结论”的问题。
- `_set_xrange_to_data_union()`（`window` 侧调用见 `canvas.py:1001`、`2315`）已实现
  Home/框选取并集，合同 4 的“并集”在 canvas 层是现成的，步骤 4 基本无需碰
  `canvas.py` 的 range 逻辑。
- `plot_channels` 的行已经自带 `(name, visible, t, sig, color, unit, data_id)`
  （`canvas.py:596-614`），渲染合同可直接承载逐曲线 X。
- FFT / Order / analysis section 页面不直接读取逐 source X payload；但既有 lesson 与
  回归要求 Apply 时清实际 `analysis_caches['fft_time']`。保持这个既有失效合同，不借机
  扩大 analysis 计算逻辑。

需要真正改的是 payload 组装层与选择/持久化层，不是渲染层。

## 实施步骤

### 1. 先以回归测试冻结新合同（RED）

**文件：** `tests/ui/test_main_window_smoke.py`、`tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_view_bridge.py`。

**另外这些现存测试会因合同 9 的形状变更而失败，必须一并迁移（原清单遗漏）：**

- `tests/ui/test_view_switch_integration.py:247` — 断言 `currentData() == (fid, "speed")`。
- `tests/ui/test_inspector.py:37,52` — 直接构造 `(text, (fid, ch))` 候选喂给
  `set_xaxis_candidates`。
- `tests/ui/test_task4_cache_invalidation.py:73,104` — 伪造 `xaxis_channel_data()`
  返回二元组，并断言 `(mw._custom_xaxis_fid, mw._custom_xaxis_ch) == ("f1", "custom_x")`；
  步骤 3 收敛为 `CustomXAxisSpec` 后此断言需改为读 spec。
- `tests/ui/test_main_window_smoke.py:1121` — 靠“最后一个候选来自文件 2”的下标算术
  选通道；按名聚合后该下标语义消失。
- `tests/ui/test_main_window_smoke.py:1198` — 断言候选显示文本逐文件带 `[短名]` 前缀；
  聚合后显示文案改为带覆盖度（合同 1），断言需同步。
- `tests/ui/test_main_window_smoke.py:951,1009,1070,1222` — 直接按 `(fid, channel)`
  查找候选，必须迁移到带 resolver tag 的载荷。

- 将 `test_custom_xaxis_length_mismatch_warns` 替换为逐 source 行为测试：两文件同名 `angle`、长度 500/300，各自 X/Y 均正确进入 payload，不能调用 `toast`，也不能有一条退回 time。
- 增加分屏测试：两条不等长 source 都有独立曲线，分别保持其本身 X 值。
- 增加叠加测试：长度不同但单位一致时，两条曲线在同一 X master 中出现，X 可见范围等于二者 X 域并集；断言没有按数组索引拼接或 0–1 归一化。
- 增加 partial 测试：5 条中缺 X、X/Y 不齐、范围为空各一条时，剩余曲线仍绘制，状态区给出稳定、可读的 `3/5` 和原因；全失败走空图提示。
- 保留并扩展现有 time-range 测试：`time=0..9, custom_x=100..109, range=2..4` 必须得到 X `102..104`；对两个 source 分别断言。
- 增加单位测试：规范化后相等（如 `m/s²` 与 `m/s^2`）可共享；需要数值换算但
  canonical 不同（如 `deg/rad`、`g/m/s²`）仍不兼容；最大 unit cohort 可绘制，其他
  source 有诊断；标题只添加一次 canonical unit。
- 增加 view-state 迁移测试：没有 `resolver` 的旧 state 恢复 exact source；新 state 保存/恢复 per-source-name；切换 range 不提交未 apply 的 X draft。
- 增加候选生命周期测试：无 checked 时仍可选择逻辑 X；legacy exact 经文件加载、
  通道编辑刷新仍保持；旧 A/angle + B/Y 恢复后 B 必须继续使用 A/angle。

### 2. 提取无 Qt 的逐 source X 解析器

**文件：** 新建 `mf4_analyzer/ui/time_xaxis.py`；调用点
`mf4_analyzer/ui/main_window/window.py`；**以及
`mf4_analyzer/ui/inspector_sections/persistent_top.py`**——它是候选/选择契约的真正
owner（`set_xaxis_candidates` / `xaxis_channel_data` / `_sync_xlabel_from_channel`），
合同 9 的形状变更落在这里，原计划只在步骤 3 含糊提到「相关 Inspector top 控件」，
必须提到本步骤作为明确文件。

- 定义不可变的 `CustomXAxisSpec`（`mode`, `resolver`, `channel`, `source_fid`, `label`）和 `CustomXResolution`（`ready`, `x_values`, `unit`, `issue_code`, `detail`）。解析器输入 source、目标信号和 spec，输出一条明确结果，不读取 Qt widget、不调用 toast。
- `per_source_name` 从当前 `fid` 中查 `<channel>`；`exact_source` 只用于旧 state 兼容。二者均必须验证 X/Y 对等长及数值有效性。
- **本阶段不改 Batch。** 在 `time_xaxis.py` 提取前台共用的
  `channel_metadata.unit → channel_units` helper，仅让 TimeDomain 的 resolver 与
  `_time_axis_label` 复用。`batch.py` 的重复 helper 由另一个 session/后续重构处理，
  不在本任务制造交叉修改。
- 兼容判定按合同 5 调用 `db_reference.normalize_unit` 做规范化相等，**不实现换算**。
  空单位不视为通配。
- 让 `_build_xaxis_candidates()` 按 channel 名聚合并根据当前 checked source 生成覆盖度，不再把 `(fid, ch)` 当新选择的唯一语义。仍保留把旧 exact-source 值显示在 combo 的兼容路径。

### 3. 改造 apply、持久化与缓存失效

**文件：** `mf4_analyzer/ui/main_window/window.py`、`mf4_analyzer/ui/view_bridge.py`、
`mf4_analyzer/ui/main_window/_view_mixin.py`、`mf4_analyzer/ui/project_io.py`、
`mf4_analyzer/ui/main_window/_channel_scope_mixin.py`、
`mf4_analyzer/ui/inspector_sections/persistent_top.py` 及 view-state tests。

> X-axis 载荷一共有**四**处 owner，原计划只点了两处，四处必须同批改：
> `capture_axis_opts()`（`view_bridge.py:16-41`）、`_restore_view_axis_opts()`
> （`_view_mixin.py:350-419`）、`_applied_xaxis_opts()`（`_view_mixin.py:426-439`）、
> `remap_view_fids` 的 x_axis 分支（`project_io.py:227-238`）。

- 将 `_custom_xaxis_fid/_custom_xaxis_ch` 的内部读取收敛为 `CustomXAxisSpec`；可短期保留旧字段作为 exact-source state adapter，但禁止再以“所有 checked 文件长度相同”作 apply 前置条件。
- 新 selection 写 `resolver=per_source_name`，旧 payload 无 resolver 时读取成 `exact_source`。校验改为“至少有一个 checked source 可解析”；一个也没有时不画假 time 图，而显示确定的空图原因。
- `capture_axis_opts()` 和 restore 路径读写 `resolver`，并保持 label、range draft、切 View 的现有行为。
- `_channel_scope_mixin.py` 的文件/通道删除必须按 resolver 分流：exact-source 的来源
  被删时保持既有降级；per-source-name 删除单个 provider（甚至暂时删除全部 provider）
  仍保留逻辑 spec，由覆盖度和图内诊断反映当前可用性。
- **存盘工程的 fid 重映射必须区分 resolver。** `project_io.py:227-238` 现在会把
  `axis_opts["x_axis"]["fid"]` 按 `fid_map` 重映射，映射不到就整体打回
  `mode: "time"`。`per_source_name` 下 fid 无意义：capture 必须写 `fid: None`，
  且 remap 分支要先判 `resolver`——`per_source_name` 原样透传、绝不因 fid 缺失
  降级为 time；`exact_source` 保持现有重映射与降级行为。若执行时图省事给
  `per_source_name` 留一个 fid「提示」，换机器打开工程会静默丢掉自定义 X。
  为此在 `tests/ui/` 增加一条 project 往返测试（新旧两种 resolver 各一条）。
- 当 spec 的语义变化时，更新 `render_context_key` 并清理现有 envelope、monotonicity
  与实际 `analysis_caches['fft_time']`。canvas 既有 composite identity 保持不变；除非
  RED 测试证明有缺口，不重写 renderer 内部 cache key。

### 4. 让构图 payload 按每条曲线携带自己的 X

**文件：** `mf4_analyzer/ui/main_window/window.py`、必要时 `mf4_analyzer/ui/pg_canvas/canvas.py` 和 `mf4_analyzer/ui/pg_canvas/overlay_axes.py`。

- 删除 `_plot_time_on_canvas()` 的单一 `custom_x` 共享数组；在 `_build_time_plot_data()` 的 checked-loop 内调用解析器，并把该 source 的成功 X 与 signal 一起经过相同的 time-range mask、finite mask 和显示/滤波路径。
- `_build_time_plot_data()` 返回明确的 `TimePlotBuildResult`：`rows`、`issues`、
  `attempted_channel_keys`、`successful_channel_keys`。计数单位是唯一
  `(fid, target_channel)`，filtered companion 不增加成功数，hidden checked 单独表达且
  不算 X 解析失败；delta 快路径只接收 `result.rows`，状态栏与图卡 pill 都从同一个
  `successful_channel_keys` 读取，并且 delta 成功时也刷新 diagnostics。
- 保持现有信号处理语义：先按 acquisition time 裁剪并完成数字滤波，再将 finite-X mask
  同步应用于原始/滤波 Y，避免先删除 X 非有限点导致滤波采样间隔发生隐式变化。
- 每一行仍传入 stable composite `data_id + channel`，保持 overlay 既有的同名跨文件身份隔离；不得降级成 bare channel key。
- 分屏：每个成功 payload 独立 subplot，仍使用既有精确 X range 同步机制。
- 叠加：使用现有一个 X-master + 每槽独立 Y-axis 的模型，逐条绑定自己的 `t_arr, sig_arr`；全局 X range 取可画数据并集。非单调 X（如角度回环）按各自 X 数组判定，不能复用另一个 source 的 monotonicity 结论。
- 不改变 overlay X-master 的固定 `[0,1]` Y-grid、Y 轴滚轮/拖拽和 box zoom 的合同。
- **状态栏文案要跟着改。** `window.py:2651-2654` 现在打印
  `绘制: {len(checked)}/{len(all_checked)} 通道，N 文件`，分子取的是**勾选数**而非
  成功绘制数。出现部分失败时它会和步骤 5 的「已绘制 3/5」互相矛盾；改为读同一份
  解析结果，两处数字同源。
- `try_apply_selection_delta` 的快路径（`window.py:2589-2598`）拿的是已组装好的
  `data`，因此诊断汇总在 `data` 组装处一次算出即可，delta 与全量重建两条路径共用；
  不需要在 delta 分支里另写一套。

### 5. 加入低打扰、可追溯的图内诊断

**文件：** `mf4_analyzer/ui/chart_stack/cards.py`（或现有 chart card 状态区的真实 owner）、`mf4_analyzer/ui/main_window/window.py`、相关 widget tests。

- 定义 `TimePlotIssue` 到视图渲染结果的单向数据流：`source label`、目标信号、X 通道、机器 code 与本地化文案；渲染层不自行猜测原因。
- 在图卡 chrome（而非会随 pan/zoom 移动的 plot scene）放一个可隐藏的 warning pill/详情入口。部分成功时显示已绘制数和未绘制数；点击才展开逐条列表。全成功不占空间。
- **落位不能和既有指示器打架。** 图卡已有 `_QualityStatusIndicator`，由
  `_position_quality_indicator()` 钉在 canvas 右下角 `margin=6`
  （`cards.py:328-375`、`_position_*` 一族）。新 pill 若沿用同一角会重叠。先定一个角
  （建议左下，或与 quality 指示器共用一条底部 chrome 行并排布局），并把
  `resizeEvent` / `_schedule_*_position` 的排队-定位模式照抄一遍，包括那个
  `RuntimeError` 吞异常的 teardown 保护。
- **全失败统一走 `show_empty_hint()` + diagnostics pill。** 替换当前空数据分支的
  `clear()` + `_warn_action_blocked` 组合；主动 Apply 也不再额外 toast。全部隐藏仍保留
  既有“当前均已隐藏”提示，不能误报成 X 解析失败。
- `missing_x_channel`、`unaligned`、`x_unit_incompatible`、`empty_after_time_range` 和 `non_finite_x` 分别有行动化文案。避免每条 toast；只有用户主动 Apply 且一个 source 都不能解析时也仍只给图内摘要，不恢复到 time。

### 6. 回归、性能与前台验收

- 先运行步骤 1 新增的定向 pytest，确认旧实现因全局长度检查或 time fallback 失败；再实现到 GREEN。
- 运行：

  实施阶段曾固定在隔离 worktree 运行；在 `4d88457` 合入后，最终集成验证固定在主
  checkout `/Users/donghang/Downloads/data analyzer` 运行，以同时覆盖 `26e422b` 与
  `4db876b`。解释器使用主 checkout 的 `.venv`，以 `PYTHONPATH=.` 加载当前 `main`：

  原命令的 `-k 'custom_xaxis or time_range'` 只筛 smoke 一个文件，**跑不到**
  `test_inspector.py` / `test_view_switch_integration.py` /
  `test_task4_cache_invalidation.py` 这三个必然被合同 9 打破的文件。改为整文件跑：

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest \
    tests/ui/test_time_xaxis.py \
    tests/ui/test_main_window_smoke.py \
    tests/ui/test_pg_timedomain_canvas.py \
    tests/ui/test_view_bridge.py \
    tests/ui/test_inspector.py \
    tests/ui/test_view_switch_integration.py \
    tests/ui/test_task4_cache_invalidation.py \
    tests/ui/test_project_session.py \
    tests/ui/test_compute_progress_integration.py \
    tests/ui/test_main_window_overlay_risk.py \
    tests/ui/test_view_state.py \
    tests/ui/test_view_channel_scope.py \
    tests/ui/test_time_filter_overlay.py \
    tests/ui/test_split_focus_routing.py \
    tests/ui/test_timedomain_hotpath_perf.py -q
  ```

  `tests/test_project_io.py` 必须独立运行；不要把根目录测试插入上述 UI invocation，
  否则后续 UI 文件不会获得其目录级 fixture，产生与产品行为无关的 collection/setup
  errors：

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest \
    tests/test_project_io.py -q
  ```

  另运行 `26e422b` 的 Batch 保护集，确认 custom-X 合并没有破坏搜索/输出面板、图片背景、
  线宽、preset/recipe/validation/render/runner 合同：

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest \
    tests/ui/test_batch_signal_picker.py \
    tests/ui/test_batch_output_panel.py \
    tests/ui/test_batch_smoke.py -q
  ```

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest \
    tests/test_batch_preset_io.py \
    tests/test_batch_recipe.py \
    tests/test_batch_validation.py \
    tests/test_batch_renderer.py \
    tests/test_batch_runner.py -q
  ```

  全量 `pytest -q` 作为诊断尝试，不作为唯一绿色门禁：本仓已知会在 Qt delegate
  生命周期路径触发 SIGSEGV，必须把 directed/custom-X、Batch 保护集与前台验收结果
  分开记录，不能以全量中止抹掉已完成的定向证据，也不能把中止写成 PASS。

- 运行 `git diff --check`，并在同一 X spec 重复 Apply、切换分屏/叠加、切 View 后确认 cache 无陈旧曲线或跨文件同名串扰。
- macOS 前台人工验收（不能由 offscreen pytest 替代）：加载两个同名 X 通道、500/300 样本的真实文件；先分屏再叠加，确认两条线在实际 `deg`/等价单位横坐标上重合/错开均合理、可平移缩放、Home 取并集；再移除一文件的 X 通道，确认另一条仍在且图卡说明原因；最后保存/重开 View 验证新旧 state 各自语义。

## 验收表

| 场景 | 期望结果 |
| --- | --- |
| 两文件同名 X，长度不同，分屏 | 两个 panel 都绘制，各自使用本文件的 X。 |
| 两文件同名 X，长度不同，叠加 | 两条曲线在同一物理 X 坐标轴叠加，X 范围为并集；不归一化、不按索引配对。 |
| 部分文件缺 X | 可画部分继续画；图卡汇总未画数与原因。 |
| 同一 source X/Y 真不等长且无通道时间戳 | 该条跳过并说明无法对齐；不截断、不伪造。 |
| 时间范围已开启 | 所有 source 均按各自 acquisition time 过滤，X 仅随同一 mask 裁剪。 |
| X 单位不兼容 | 不在同一共享 X 轴悄悄叠加；显示具体 source 原因。 |
| 历史 View | 继续使用历史的精确 source X；不因升级变成同名自动解析。 |
| X 单位一空一有（`""` vs `rpm`） | 判为不兼容，不叠加；不得当成统一 rpm。 |
| 存盘工程重开（fid 重新分配） | `per_source_name` 原样保留；`exact_source` 沿用现有重映射/降级。 |
| 部分失败时的两处计数 | 状态栏与图卡 pill 的「已绘制 N」同源、数字一致。 |

## 风险与非目标

- 当前 FileData 以共同 DataFrame 时间轴为主；若用户所说“同文件内长度不一致”来自 loader 之前的原始记录层，需先扩展数据模型暴露每通道 timestamps。这是独立数据导入设计，不能在 UI 层用截断掩盖。
- 本计划不承诺把任意不同物理量（例如角度与时间）转换后叠加；按合同 5，只有
  `normalize_unit` 规范化后完全相等的 X 单位可共用坐标轴，本次不实现任何换算。
- **修正原判断：这套逐 source 解析方向不是新发明，batch 已经在跑。** 原文写“不更改
  batch 的严格 common-X 预检 …… 前台合同不能直接复制过去”，与代码不符：
  `batch.py:3673-3679` 就是拿 `x_channel` 字符串对**每个** `fd.data.columns` 逐 source
  解析、每条 series 自带 `x_unit`；`preset.target_policy` 已支持
  `available_per_source`（`batch.py:2713`）；混合 X 单位的拒绝规则在
  `batch_render.py:366-368`（`mixed x units` 直接 raise）；空单位是事实的约定在
  `ui/drawers/batch/sheet.py:646`。所以正确姿势是**让 TimeDomain 对齐 batch 已上线并
  验证过的合同**（尤其单位判定与 per-source 解析），而不是并行造第二套。
  仍然不改的是 batch 侧的 UI 与失败策略：batch 面向可复现批量输出，遇到不兼容直接
  raise 让任务失败；前台改为部分成功 + 图内诊断。前台额外使用 `normalize_unit`
  做 canonical 文本相等，而 batch renderer 当前仍按原始 unit 字符串判重；本任务不改
  batch，也不把两者描述成完全相同的单位实现。

## 实施结果（2026-08-01）

- 集成基线已从计划时的 `07c73e5` 更新为已完成的 Batch 提交 `26e422b`；custom-X
  实现提交为 `4db876b`，本地 `main` 合并提交为 `4d88457`。两条 ancestry 检查均通过，
  且 custom-X 提交没有改动 Batch 源码或其测试文件。
- 新增无 Qt 的 `time_xaxis.py`，统一 resolver、旧 View 迁移、单位 cohort 与逐 source
  失败事实；Inspector、View/project remap、文件/通道删除均使用同一序列化合同。
- TimeDomain payload 已改为逐目标 source 解析自己的 X/Y；500/300 样本在 subplot
  与 overlay 中都保留独立 X，overlay 可视范围由成功曲线的 X 域并集得到，不归一化、
  不按索引拼接。
- 单位 cohort 在 acquisition-time range 与 finite-X 资格确认后再选择；`None`、已知空
  单位 `""`、已知非空单位三态保持分离。部分/全部失败使用图卡左下诊断 pill 与空图
  提示，不逐条 toast，也不退回 time。
- 独立复审关闭了 2 个 P1 与 2 个测试缺口，复审结论 PASS、无新增 P0/P1；未修改
  Batch，也未触碰由另一 session 负责的需求 1–3。
- 合并后复审再次确认 `26e422b` 与 `4db876b` 的文件交集为 0、无 P0/P1；其唯一 P2
  是 all-failed Apply 后仍显示“横坐标已更新”成功 toast。该提示冲突已用 RED-first
  回归修正；同时把仍返回旧 list fake 的 compute-progress / overlay-risk consumer
  迁移到 `TimePlotBuildResult`，并补进 directed suite。
- 合并后复验：custom-X resolver/绘图/state/project/consumer 共 `85 passed`；
  `26e422b` Batch UI + preset/recipe/validation/renderer/runner 保护集共
  `457 passed`。合计 `542 passed`，`py_compile`、`git diff --check`、ancestry 与 lesson
  gate 均通过。
- 验证：custom-X/state 定向 `39 passed`；project I/O `15 passed`；关键复审闭环
  `14 passed`；计划列出的 UI 整组 `831 passed, 1 deselected, 20 failed`，其中 2 个
  FFT dB-reference 与 18 个 split-focus 失败已在干净 HEAD 小范围复现，属于既有基线。
  全仓 pytest 到 54% 时在 `db_reference_dialog.py:117` 访问已删除的
  `ScientificReferenceSpinBox` 后 SIGSEGV（exit 139），因此全量结果保持
  **UNVERIFIED**。`py_compile`、`git diff --check` 与 lesson gate 均通过。
- macOS 前台验收已启动但不能标记 PASS：TraceLab v7.9 正常启动，系统文件选择器确认
  第一份真实 MF4 后主进程 SIGSEGV。Crash report：
  `~/Library/Logs/DiagnosticReports/Python-2026-08-01-213130.ips`，faulting main-thread
  栈位于 `sipQGraphicsWidget::resizeEvent` / `QGraphicsGridLayout::setGeometry` /
  `QGraphicsView::resizeEvent`。崩溃发生在选择 custom-X 之前，因此当前只能说明前台
  验收被既有 Qt/pyqtgraph 几何生命周期问题阻断，不能据此否定或确认屏幕交互合同。
