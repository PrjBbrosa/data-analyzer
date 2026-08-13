# 切片合并后代码审查 · 修复设计

- 日期：2026-08-04
- 基线：`main` @ `28370b1`（v7.9.2 + 切片导出合并 + 设为左轴修复）。**本文所有行号以此 commit 为准。**
- 来源：对 `d142457..HEAD` 的四路代码审查（批处理核心 / Qt 渲染导出 / 批处理 UI 接线 /
  主窗口与时域修复），每条中等以上发现都在本机（macOS）复核过：或有可运行的复现脚本，
  或有 1920×1080 真渲染截图。
- 实施计划：[2026-08-04-post-slice-merge-review-fixes-implementation.md](../plans/2026-08-04-post-slice-merge-review-fixes-implementation.md)

## 审查总评

合并整体质量高：**接线全部干净**（connect 都在 `__init__`，列表重建只连新行，lambda 用默认参
数绑定），切片数学与渲染器逐点一致并有测试钉死，向后兼容（旧 preset 迁移告警、指纹稳定、
切片关闭字节一致）扎实。`设为左轴` 修复（d60cdea）正确且最小，边界（无焦点、View 删除、
信号移除、旧工程加载）全部安全。

但存在 **6 个中等问题**（2 个直接影响真机导出效果）和一批低优先级打磨项，本文逐条给出
根因与设计决策。

## ⚠️ 两台验证机的字体差异（读懂 R2 的前提）

| 机器 | 字体环境 | 后果 |
| --- | --- | --- |
| Windows 验收机 | Qt 缺字体，offscreen 渲空白 | 依赖字体度量的分支走 fallback，`test_slice_row_never_narrows_the_main_left_axis` 等 2 条**绿** |
| 本机 macOS | PingFang SC，12pt 行高 23.78px | 同 2 条测试**红**（复现 100%），且真机导出效果偏离设计 |

合并说明里「full suite identical failure sets, +172 new passing」是 Windows 机的结论；
**在 macOS 上该合并自带 2 条新失败**，不是环境噪音，是真缺陷（见 R2）。
执行者不要把它们当既有失败跳过。

---

## 组 R · 导出渲染（真机可见，P0）

### R1 · 切片行开启时，主图底部轴标题被切片行顶框线穿过

**证据**（本机 1920×1080 真渲染，fft_time + slice time [5,15,25]）：
标题 "Time (s)" 场景矩形下沿 733.5px，切片行 ViewBox 上沿 722.7px，
重叠 ≈ 11px，框线从文字中间划过。截图已确认。

**根因**：[`_builder.py:2025`](../../../mf4_analyzer/batch_render_qt/_builder.py#L2025)
附近 `build_heatmap` 注册 `_space_bottom_axis_label` 的额外下移（机制在 `:192-222`），
其正当性依赖「标题可以悬垂进页脚上方的空白带」——只对**页面最底部面板**成立。
注册时机早于「本页要加切片行」这一事实,于是标题悬进了切片行的绘图区。

现有 `adjacent_text_overlaps()` 测不出：它只比文字对文字,而切片行顶轴
`showValues=False`、不贡献文字矩形。

**D-R1**：当 `plan.enabled` 时，主热力图行**不做悬垂**——通过增大该 bottom 轴的
高度把标题空间「买」出来（参照 `_add_time_panel` 的 `if bottom:` 门控模式），
而不是向下越界。切片关闭路径一个字节都不许变（有逐字节 parity 测试保护）。

**验收**：几何断言「标题矩形 ∩ 切片行 ViewBox 顶缘 = 空」进测试；真机渲染复验标题下方
留白干净。

### R2 · 轴宽 pin 与刻度密度依赖机器字体度量,与 pyqtgraph 绘制度量不一致

两条红测试同根源,但要修的是两个点:

**R2a · 左轴宽度 pin 偏窄。**
[`_left_axis_width_for_ticks`](../../../mf4_analyzer/batch_render_qt/_builder.py#L567)
用 `QFontMetricsF.boundingRect` 量刻度串,而 pyqtgraph 的自然宽度来自绘制时度量;
PingFang SC 下两者差 ~3.4px。实测:同一份刻度,不开切片的自然宽度 71.35px,
开切片后被 [`align()`](../../../mf4_analyzer/batch_render_qt/_builder.py#L668)
pin 到 67.975px——**pin 比自然值窄**,正是
`test_slice_row_never_narrows_the_main_left_axis` 要防的回归(轴标题贴近数字)。

**D-R2a**:`align()` 里的目标宽度改为
`max(按刻度串度量的宽度, axis.width() 当前值)` ——
度量值兜「从未绘制/刚换刻度串」的下限(docstring 里 30px/57.4px 的病因),
`axis.width()` 兜「绘制度量比 QFontMetricsF 宽」的上限;pin 只往宽走、不往窄走,
多次 align 单调收敛,不会振荡。代价是刻度串换短后可能略宽,一次性导出可接受。

**R2b · 刻度被过度 coarsen,轴端点脱离刻度网格。**
[`_labels_fit`](../../../mf4_analyzer/batch_render_qt/_builder.py#L1147) 对纵轴按
`metrics.height() + 4` 计每标签需求。PingFang SC 12pt 的 `height()` = 23.78px
(含大 leading),10 个标签需 277.8px > 轴高 260.8px → coarsen 成步长 5 的 8 个刻度;
而 viewRange 仍是 [-36, 0],下端点 -36 落不到任何刻度上,违背 D19
(「端点取整到 nice step、刻度贴曲线」)。Windows fallback 字体行高小,不触发。

**D-R2b**:纵轴 fit 判定改用 `ascent() + descent()`(不含 leading)+ 既有 4px 间距;
且度量字体与轴实际安装的 `style['tickFont']` 保持一致(现在
[`_apply_tick_density`](../../../mf4_analyzer/batch_render_qt/_builder.py#L1083)
用 `chart_font(theme.axis_font_pt)` 重建字体,与
`_left_axis_width_for_ticks` 的 tickFont 优先逻辑不统一——统一成后者)。
PingFang 下 10 标签 ≈ 200px < 260.8px,恢复步长 4,两台机器行为一致。

**D-R2b-防御(可选,P2)**:若未来某字体仍触发 coarsen,当前实现会让轴端点脱格。
彻底解法是 coarsen 后按**最终步长**把范围端点向外重取整——但
`_apply_tick_density` 的 docstring 承诺「手动输入的范围保持精确边界」,
所以这条只允许作用于**切片幅值轴这类自动推导范围**,不许碰手动范围。
本轮可只留 TODO + 测试注记,不强制实施。

**验收**:两条红测试转绿(macOS + Windows 双机),`test_batch_render_qt*` 全量、
切片关闭逐字节 parity 不回归。

### R3 · clamp 警告的数据范围没滤 NaN(P2)

[`_builder.py:2249-2253`](../../../mf4_analyzer/batch_render_qt/_builder.py#L2249) 用
`np.min/np.max` 算坐标范围拼进「超出数据范围 [lo, hi]」文案,而
`plan_heatmap_slice` 的 clamp 决策只看有限值;坐标向量里有一个 NaN,导出的警告就是
`[nan, nan]` + NumPy RuntimeWarning。
[`batch.py` 工作簿路径](../../../mf4_analyzer/batch.py#L4200)同一写法,同样要改。

**D-R3**:换 `np.nanmin/np.nanmax`,或直接复用 `plan_heatmap_slice` 内部已算好的
有限边界(后者更好——一处真相)。

---

## 组 P · 切片面板与批处理面板(状态与跟手,P0/P1)

### P1 · 应用不带 slice 的 preset 清空用户已填的切片配置(P0)

[`slice_panel.py:207-218`](../../../mf4_analyzer/ui/drawers/batch/slice_panel.py#L207)
`apply_params` 缺 `slice` 键时:轴重置到 0、位置清空、开关关闭。而
[`normalize_batch_params`](../../../mf4_analyzer/batch_recipe.py#L409) 会把关闭态的
slice 整个 pop 掉 → **绝大多数 preset 都不带该键**;
[`analysis_panel.py:402-405`](../../../mf4_analyzer/ui/drawers/batch/analysis_panel.py#L402)
又对任何方法都无条件转发 `_slice.apply_params`。
用户场景:填好 `5, 15, 25` → 应用任意时域/FFT preset → 回到时频方法,位置没了。

同一批提交刚在
[`chart_statistics_panel.py:208-219`](../../../mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py#L208)
修了同款 bug(缺键只关开关、保留已填范围,注释里点名了这个模式),切片面板漏了。

**D-P1**:照抄该模式——缺键时仅 `setChecked(False)` + `_sync_enabled()`,
轴与位置文本不动。既有测试
`test_slice_panel_apply_params_none_slice_resets_to_disabled` 只钉开关状态,不冲突;
新增测试钉「字段保留」。

### P2 · apply_params 无信号阻塞,一次导入连发多次全量重算(P1)

`slice_panel.apply_params` 里 `setCurrentIndex / setText / setChecked` 各自触发
`changed` → `AnalysisPanel.paramsChanged` →
[`BatchSheet._recompute_pipeline_status`](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L512);
[`chart_statistics_panel.py:220-228`](../../../mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py#L220)
同病。中间状态是半应用的,状态条会闪过瞬时 warn。
同期代码里已有正确示范:
[`output_panel.apply_open_folder_after_run`](../../../mf4_analyzer/ui/drawers/batch/output_panel.py#L886)
用了 `QSignalBlocker`。

**D-P2**:两处 `apply_params` 全程 `QSignalBlocker`,收尾统一发一次 `changed`。

### P3 · 每次重算跑两遍校验 + 一次输出规划;位置输入逐键触发(P1,跟手核心)

一次 `_recompute_pipeline_status`:
[`preflight_issues()` 直调一次](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L553)、
[`is_runnable()` 内部又调一次](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L1293),
外加 [`preview_outputs` 规划](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L607)
(含对输出目录逐 artifact `exists()`)。而
[`slice_panel.py:119-120`](../../../mf4_analyzer/ui/drawers/batch/slice_panel.py#L119)
把 `textChanged` 直连 `changed`——输 `5, 15, 25` 九个按键 = 9×(2 校验 + 1 规划 + N stat),
全在 UI 线程。这是切片提交引入的**第一个自由文本字段**落在规划最重的时频路径上;
网络输出目录下会显著不跟手。

**D-P3a**:`_recompute_pipeline_status` 的触发统一经过一只 ~200ms 单发 `QTimer`
(restart 式合并;`__init__` 末尾的种子调用保持直调,Run 按钮首帧状态不变)。
**D-P3b**:重算内部只跑一遍 `preflight_issues()`:把结果传给可运行判定
(新增 `is_runnable(issues=...)` 参数或抽内部 helper),外部 API 行为不变。

### P4 · 固定频率轴负位置的报错落不到字段(P2)

[`positions_error()`](../../../mf4_analyzer/ui/drawers/batch/slice_panel.py#L177)
不查负数;[`validate_recipe` 查](../../../mf4_analyzer/batch_validation.py#L405)但发的
字段是 `"slice"`,而 sheet 的两张消息映射表
([`sheet.py:82-93`](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L82) 与 `:118-125`)
只认 `"slice_positions"` → 用户只看到笼统的「参数待完善/请检查分析参数」。

**D-P4**:`positions_error()` 增加轴感知负数检查(轴为 y 时拒负,文案指向位置字段);
同时把 `"slice"` 补进两张映射表兜底。

### P5 · 摘要计数不去重不封顶(P2)

[`_refresh_summary`](../../../mf4_analyzer/ui/drawers/batch/slice_panel.py#L143) 数
原始解析值:`15, 5, 15` 显示「3 处」,归一化后实际导出 2 处;5 个值也照数,
与 Run 被拦截的状态矛盾。**D-P5**:按去重后数量计,并 clamp 到 `_MAX_POSITIONS`。

### P6 · 信号选择器禁用态残留可点击暗示(P2)

5a93b3a 的禁用皮肤灰了边框/填充/摘要,但触发器保留 `Qt.PointingHandCursor`
(Qt 对 disabled widget 依然显示其 cursor),`_ArrowButton` 箭头也没变灰
([`signal_picker.py:229`](../../../mf4_analyzer/ui/drawers/batch/signal_picker.py#L229)、
`:261-270`)。**D-P6**:`_apply_trigger_style` 禁用分支里重置 cursor、箭头随皮肤变灰。

---

## 组 C · 批处理核心(GUI-free 层,P1)

### C1 · 校验与归一化对「字符串数字位置」意见不一 → headless 静默丢切片(P1)

已复现:`{"slice": {"enabled": True, "positions": ["1.5", "2.5"]}}` 走 fft_time——
[`validate_recipe`](../../../mf4_analyzer/batch_validation.py#L395) 经
[`_finite_number`](../../../mf4_analyzer/batch_validation.py#L33) 接受字符串,零告警;
[`normalize_batch_params`](../../../mf4_analyzer/batch_recipe.py#L350) 只认 int/float,
归一化后 `positions: []` → `plan.enabled = False` → run 顺利「done」,
没有切片曲线、没有任何警告。`BatchRunner.run` 校验的是 raw params、执行的是
normalized params,分歧就在这条缝里。GUI 路径不受影响(面板只产 float)。

**D-C1**:**收紧校验**——`validate_recipe` 的位置检查镜像归一化的类型过滤
(非 int/float 即 `invalid_slice_positions`,文案说明「必须是数字,不接受字符串」)。
不选「归一化端做字符串强转」:接受类型的单一真相应当在归一化层,校验层只应更严不应更宽,
且手写 JSON 作者应得到早期明确报错而非静默宽容。

### C2 · data-only 导出无条件把整套 Qt 拉进 GUI-free 进程(P1)

[`_slice_workbook_factory`](../../../mf4_analyzer/batch.py#L4189) 在判断
`plan.enabled` **之前**就调
[`_load_slice_render_contract()`](../../../mf4_analyzer/batch.py#L111)——
后者 import `batch_render_qt._builder`,实测拉入 ~169 个 PyQt5/pyqtgraph 模块。
该函数 docstring 自己承诺「只在真的要写切片工作簿时才 import」,与实现矛盾。
所有时频/阶次的 data-only 批处理(不出图、没开切片)都白付这笔 import 与内存。

**D-C2**:factory 开头先查参数——`slice` 键缺失或 `enabled` 非真即 `return None`,
之后才允许加载 contract。归一化已保证「键只在启用时幸存」,这个守卫是廉价且充分的。
配一条子进程测试:data-only fft_time 导出路径全程 `sys.modules` 无 `PyQt5.*`
(仿照 `tests/test_signal_no_gui_import.py` 的投毒法)。

### C3 · NaN 位置穿过归一化,指纹对输入顺序敏感(P2)

[`batch_recipe.py:350-358`](../../../mf4_analyzer/batch_recipe.py#L350):NaN 过
isinstance 过滤,`dict.fromkeys` 视不同 NaN 对象为不同键,`sorted()` 含 NaN 时依赖
输入顺序——已复现 `[nan, 5.0]` 与 `[5.0, nan]` 指纹不同,违背代码内 D7 注释
(「fingerprint 必须对输入顺序不敏感」)。校验会拦住这种 recipe 落地执行,
影响限于无效 recipe 的任务身份稳定性。
**D-C3**:归一化的 slice 分支滤掉非有限值(渲染端 `_slice_positions` 已是这么做的)。

### C4 · order_time 无 RPM 前置校验被删后,headless 名称猜测静默扩权(P2)

`missing_rpm_channel` 校验随手动 RPM 一起删了;headless/API 调用没配 RPM 通道时,
兜底是 [`_guess_rpm_channel`](../../../mf4_analyzer/batch.py#L5171)
按名称含 `rpm/speed/tach` 猜——EPS 数据里 `WheelSpeed` 之类通道会被静默拿去当阶次基准,
用户毫无提示(GUI 有 [`sheet.py:1340-1349`](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L1340)
强制,不受影响)。猜测逻辑是既有的,但删掉手动 RPM 后暴露面变大:
旧手动 preset 迁移后第一次就走进这条路。

**D-C4**:命中猜测时对每个 item 发一条 warning 进 `warnings_out`,
点名猜中的通道名(「未指定转速通道,已按名称匹配使用 X——请确认」)。
不改成硬性报错:会破坏既有 headless 流程,且 GUI 路径本就不可达。

---

## 组 M · 主窗口与杂项(P2)

### M1 · 手动 RPM 提示 toast 被模态批处理面板完全遮住

[`window.py:3290-3296`](../../../mf4_analyzer/ui/main_window/window.py#L3290) 在
`dlg.exec_()` 前发主窗口 toast,而 `BatchSheet` 是盖在主窗口上的 ~1080×760 模态框,
5 秒 toast 用户根本看不见。**D-M1**:把这条通知搬进 sheet 内部
(RPM 通道行旁的状态注记,或管线状态条),删掉主窗口 toast。

### M2 · 旧阶次 preset 缺 `window` 键时静默继承当前窗函数

[`contextual_order.py:532-533`](../../../mf4_analyzer/ui/inspector_sections/contextual_order.py#L532)
与 `:771-772` 都是 `if 'window' in d` 才动 combo——本版本之前保存的所有阶次
preset/视图状态都没有该键,应用后会用**当前选中**的窗函数计算;而历史行为是固定
hanning([`_order_mixin.py:247/447`](../../../mf4_analyzer/ui/main_window/_order_mixin.py#L247)
的 `p.get('window', 'hanning')`)。用户先点了 flattop 内置预设、再应用旧 preset,
结果就和以前所有版本不同,且无提示。
**D-M2**:阶次面板的两条应用路径把缺键视为 `'hanning'`(阶次是特例:
**没有任何**历史载荷带这个键;fft/fft_time 不受影响,不要动)。

### M3 · 代表来源提示按 `" · "` 解析 display_name,通道分组下产出误导文案

[`sheet.py:1544-1563`](../../../mf4_analyzer/ui/drawers/batch/sheet.py#L1544)
split 显示名取「文件名」——`group_by="channel"` 时显示名是通道名,toast 变成
「代表来源 <通道名>」;文件名自带 `" · "` 也会碎。仅影响 toast 文案。
**D-M3**:从组成员的 `source_key` 推导,不解析显示串。

### M4 · 发现性面未同步本轮新交互

quickref 的「导出切片」行没提「最多 4 个位置 / 仅时频·阶次」约束;
「完成后打开输出文件夹」开关及其偏好持久化完全没进 hints/quickref。
**D-M4**:走项目命令 `/update-hints` 同步两个面,不手改。

### M5 ·(可选)fft_time 预设分支与 order 分支的归一化不对称

[`window.py` order 分支](../../../mf4_analyzer/ui/main_window/window.py#L3403)过
`normalize_batch_params`,fft_time 分支(`:3371-3389`)不过。今天无用户可见差异
(runner 在展开/执行时统一再归一化),纯一致性。**D-M5**:补齐 fft_time 分支同样调用;
若执行时发现有指纹或测试影响则放弃,保持现状并留注释。

---

## 优先级与验收总表

| 项 | 级别 | 用户可见性 | 验收信号 |
| --- | --- | --- | --- |
| R1 标题穿线 | P0 | 每张开切片的导出图 | 新几何测试 + 真机截图 |
| R2 字体度量 | P0 | macOS 导出轴宽/刻度 | 2 条红测试双机转绿 |
| P1 状态清空 | P0 | 应用 preset 即触发 | 新字段保留测试 |
| P2/P3 跟手 | P1 | 大配置 + 慢目录 | 计数型测试(见计划)|
| C1 校验分歧 | P1 | headless/JSON 作者 | 新校验拒绝测试 |
| C2 Qt import | P1 | headless 资源占用 | 子进程无 Qt 测试 |
| R3/C3/C4/P4/P5/P6/M1-M5 | P2 | 边角 | 各配 1 条测试或 /update-hints |

**全局约束**(执行者必读):

1. 切片**关闭**路径的 PNG/CSV 逐字节 parity 是既有回归保护,任何渲染改动不得破坏。
2. `batch*.py` 保持 GUI-free:Qt 只允许函数内局部 import(C2 正是在收紧这条边界)。
3. 渲染/视觉类修复,offscreen 只算排版草稿,**必须真机复验**(CLAUDE.md Gotchas)。
4. 阶次分析领域是 EPS:转速=电机转速,文案不得出现 engine 措辞。
