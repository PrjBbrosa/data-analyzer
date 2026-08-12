# Guideline 驱动的全局加固 —— 设计 spec

- 日期：2026-08-12
- 依据：`docs/analyzer/reviews/2026-08-12-optimization-commit-pattern-review.md`
  （近一周 57 条小修的 8 类疏漏模式 + 五路横扫的 ~60 条隐患，编号 A/B/C/D/E 系列
  沿用该文档 §4）
- 配套 plan：`docs/analyzer/plans/2026-08-12-guideline-hardening-plan.md`
- 基线 HEAD：`cf530b92`（v7.9.9，主体 6048 passed / 11 skipped 全绿，
  `tests/acquisition_ui` 单独 355 passed）

## 1. 为什么现在做

1. **同型 bug 正在批量复发**。本周修的每一类小点，横扫都找到了 3~10 个还没爆的
   同型实例：「全部」的作用域 bug 刚在时域修完，时频/阶次/FRF 三个分区还躺着
   完全相同的三份（A2）；「未记录 ink 当零」刚修完，补测函数自己的 except 又在
   返回 0（B3）；预览 warnings 出口刚修完，Run 结果面板还是零出口（D1）。
   不趁模式清晰时一次收掉，就是等它们逐个变成用户回执。
2. **有三条已确认的数据损坏路径**（A1 写坏工程文件、A3 每次重开丢 Y 缩放、
   A4 时间轴错 1000×），和一条安全网整体失效（B1：防 65.9 s 帧的 backstop
   自身静默不存在）。
3. **修复成本正处于最低点**。每条隐患都有 文件:行 + 现状摘录 + 触发场景，
   且大多数修法已有本仓先例可照抄（mode 守卫照 `_project_io_mixin.py:1449`、
   toast 聚合照 `_close_files`、WeakMethod 照 `sheet.py:642`、
   诊断出口照 HDF `dropped_channels`）。

## 2. 量化收益

- 消除 3 条数据损坏路径 + 1 条安全网失效（P0 全部）。
- G2 类：产品常量的独立声明数从 ~30 处收敛到个位数收口点；
  verify 工具族「参照侧字面量」清零（该模式已两次让守卫复述被守卫方的错误）。
- G7 类：6 条「生产了却没人渲染」的诊断载荷全部接通 UI；5 处 str(exc) 文本
  分派改结构化。
- 生命周期：跨 C++/Python 引用环从 ~40 处降到 0（30 lambda + 9 bound-method
  存储），直接降低「GC 在 paint 内部回收 widget」段错误族的燃料。
- 新增 3 道机械护栏（§4），把三类高频模式从「靠 review 记得」变成「红了就修」。

## 3. 设计决策（按主题）

各主题的具体文件清单、修法细节、测试要求在 plan 的对应 Task 里；本节只记
**方向性决策与理由**，执行中如需偏离，先回本节补记再动。

### 3.1 作用域与状态（A1/A2/A3/A7/A8）

- **A1 修在函数内部而不是调用点**：`_capture_focused_view` 开头加
  `if self.chart_stack.current_mode() != 'time': return`。理由：三个出口同根因，
  逐调用点补判断会重演「修了踩到的那一处」；且与 `_sync_active_analysis_params:263`
  的守卫形状对称。
- **A2 的正确作用域**是当前分析 View 的数据范围：给 `PgHeatmapCanvas`/`PgFrfCanvas`
  补最小的「已绘数据 X 范围」getter（与 `get_data_x_union` 同契约），
  `_plotted_time_extent` 的回退链插在 `_time_data_extent()` 之前。**不要**把
  回退链里的全局兜底删掉——空画布时它仍是合法答案。
- **A3 三张表一起补**：`remap_view_fids` 重映射 ylims key、
  `_filter_time_view_state_for_removed_fids` 清孤儿、恢复侧 `_coerce_pair`
  补 isfinite + 相对容差校验（B6 一并修，判据用既有
  `ui_kit/ticks_math._DEGENERATE_SPAN_RATIO`，不要再发明一个阈值）。
- **A7 只挡渲染不挡缓存**：结果回调里比对 `ctx['view_id']` 与当前 active view_id，
  不一致时**只跳过绘制**（缓存/pin 照存——那部分本来就是对的），切回时
  `_render_analysis_view_from_cache` 自然接管。
- **A8 守卫加在入口**：`_apply_audio_weighting_default` 开头判
  `_applying_analysis_view` 早退。**产品语义不变**：加载音频文件时的默认 A 计权
  照常生效（那条路径不在 apply 区间内）。

### 3.2 未知≠零 与退化输入（B1-B5、A4、A5）

- **B1**：消费 `install_frame_paint_timer` 返回值；安装失败走 `logger.warning`
  留痕（批处理内核「吞掉的基础设施失败必须留痕」的既有纪律延伸到渲染层），并加
  哨兵测试直接断言真 canvas 上计时器已装上（G7：静默失效的机制欠一个哨兵）。
- **B2/B3 的失败语义是「未知」而不是 0，也不是永久拒绝**：
  - `_line_ink_now` 测量失败返回 `None`；调用方对 None 的处理是**本帧不给 AA
    放行**（保守方向），但**不写入** `_line_ink_state`（下一帧重测）。
  - renderer 侧 `get_ylim()` 失败时**跳过记录**（保留旧记录或无记录），
    绝不把 0.0 写进状态表。
  - 教训边界：`0c07517a` 试过「无记录一律拒绝」导致 34 条用例转红——失败路径
    必须只覆盖真正的异常，不能把首帧正常路径卷进来。
- **B4 哨兵桶分离**：退化/非有限的 `y_span` 用独立哨兵（如 `None` 或
  `-(1 << 30)`），不与 `log2(1.0)=0` 的合法桶共用。
- **B5**：`_finite_data_bounds`/`_slice_autorange` 引入相对容差（复用
  `_DEGENERATE_SPAN_RATIO` 语义）；全非有限时**不发明 0..1**，返回哨兵由调用方
  按「无数据」分支处理。
- **A4 ZFD**：`dt` 接受区间放宽为「有限且 `0 < dt <= 3600`」（1 小时上限护住
  真离谱值）；落回 1 kHz 估算时 `fs_estimated` 必须有 UI 出口（§3.4）。
- **A5 HDF**：`ch order`/`nbr of scans` 缺失时报**头部级**错误（指明缺哪一行），
  不再放任 demux 跳过后逐通道报 "no samples"；factor 走默认值时记 warning 进
  `source_metadata` 并随 §3.4 出口显示。

### 3.3 真值收口（C 系列）

- **收口点选择**：Qt-free 的跨侧常量进 `qt_analysis_shared.py`（已是中立宿主）；
  纯数值/策略常量若与 Qt 无关可进 `render_profile.py`（已有先例
  `log_frequency_tick_levels`）。**不新建**第三个常量模块，避免「收口点本身分裂」。
- **verify 工具原则**（C2/C3）：参照值一律从产品/case 回读，禁止字面量重声明。
  frozen smoke 的 turbo 端点改为运行时从 `pg.colormap.get("turbo")` 取
  （道具常量由测试自己钉死是对的——`cmap="turbo"` 参数保留，但 RGB 期望必须回读）；
  另补一条用**出货默认 gnuplot2**（本地 LUT 路径）的冻结断言。
- **C5 权威裁决**：`_render_in_db`（经 `batch_render_qt/contract.py` 导出）是唯一
  实现，`batch_output_scale` 改为委托调用——`batch.py:155` 的注释已经这么声称了，
  让代码兑现注释。`amplitude_axis` 腿保留（它是新增能力不是漂移方向）。
- **C7 字号**：`qt_chart_fonts` 增加具名 `CHART_FONT_PT = 9.0`，三个签名默认与
  三处量测点全部引用它；「量测字号==渲染字号」从巧合变成引用同一符号。
- **C9/C10 方言统一**：`amplitude_mode` 判据与 overlap 归一化各收成一个共享
  helper（放 `batch_compute.py` 或 `qt_analysis_shared.py`，按现有 import 方向定），
  三处方言/三套实现全部改调用。Order 缺省不一致是**产品行为差异**，
  默认对齐到 GUI 侧（dB）——批处理导出应与单文件所见一致（parity 精神）。
- **C11 范围控制**：`coherence_threshold`、窗函数默认与候选顺序收成具名常量
  （建议就近放 `signal/` 侧不可行——signal 禁 GUI import 但常量无 GUI 依赖，
  可放 `signal/analysis_defaults.py` 供两侧 import；若嫌新文件，退而放
  `qt_analysis_shared.py` 并在 docstring 记录）。**只收敛声明，不改任何默认值**。

### 3.4 诊断出口（D1-D4、A6）

- **模板**：HDF `dropped_channels` → `format_dropped_channels_notice` → toast
  是唯一走通的链路，其余格式照抄：WWT `skipped_channels`、MAT `skipped_vars`、
  ZFD `fs_estimated`（文案必须含「估算」字样）、TDMS 跳过（先补载荷再接出口）、
  三处重名去重（记入 metadata + 单条汇总提示）。
- **D1 Run 出口**：`_show_result_toast` 与 `task_list` 行 tooltip 补 warnings
  渲染；warnings 多于 3 条时折叠为「N 条警告，详见 manifest」。**单点经
  `_RunReporter` 的既有纪律不动**——这是消费端补渲染，不新增 emit 路径。
- **D2**：诊断结构 `{code,message,suggestion}` 完整下传，UI 渲染 message +
  suggestion；humanizer 正则不改（机器串本就不该到它手里）。
- **A6**：`uniform_time_axis_for_spectrogram` 返回值加 warnings 通道，重建时
  产出与 FRF 同格式的审计警告；改写后的 fs 回写 `effective_params`。
- **D10 通道编辑器**：按 BatchSheet 先例自持 toast（`isVisible()` 时 own toast、
  关闭后回落 parent）；`_on_export_clicked` 的 emit/accept 顺序不动（导出期间
  抽屉保持打开是刻意交互），statusBar 消息在模态期间改为随 toast 一并自持展示。
- **D11 结构化分派**：FRF cancelled/overflow 改自定义异常类型（`signal/frf.py`
  抛、`batch_compute.py` 按类型接）；`FrfPreflightError` 加 `code` 字段，
  `_frf_mixin.py:413` 按 code 分派；`_project_io_mixin.py:408` 的 TypeError 措辞
  探测改 `inspect.signature` 预检。`NO_CAN_FRAMES_MESSAGE` 模式是范本。

### 3.5 文案对齐（D5-D9）

- **原则**：文案描述**本实现**的行为，不描述通用领域直觉；FRF 组
  （`contextual_frf.py:44-62`）是逐条核实过的标准，照它重写。
- **D5 需产品裁决**（见 §5）：FFT「重叠」控件当前对频谱零影响。默认方案是
  **文案与摘要如实化**（说明仅在平均模式下经 `avg_overlap` 生效/或标注为显示
  参数），不擅自接线或删控件。
- **D6/D7**：重写「自动 NFFT」与 `order_res`/NFFT 两组 tooltip，写清条件
  （单帧=整段；自动下 `order_res` 反向驱动 nfft；手动 NFFT 下 `order_res`
  只是插值网格）。
- **D8/D9**：frf-guide 行标签改「自动重建」；placeholder 去掉 ` s` 后缀，
  错误文案补「不要带单位」。注意 `help/` 内容改动要跑
  `tests/test_help_content.py` 契约。

### 3.6 Qt 物理层与生命周期（E 系列）

- **E1/E2**：`::item:selected` 补自身圆角（`父radius − border-width` 规则）；
  9 处 `border:` 简写改 `border-color:`（团队既定约定），两处覆盖全集的死代码
  radius 顺手清理。**新增机械护栏**：lint 测试扫描 `style.qss`——凡状态选择器
  （含 `:hover/:checked/:disabled/[attr=]`）的规则块内出现 `border:` 简写且
  基线块声明过 `border-radius`，即红。白名单起点为空。
- **E3**：13 个按钮补 `fit_message_box_buttons_to_text`。
- **E5**：文件名/来源文本改 `ElideMiddle`（tooltip 已有，保留）。
- **E6**：Toast 让位从「构造时一次性魔法数」改为「显示时从真实邻居高度派生」
  （主窗按底部 chrome 实高求和；sheet 在 `_present_footer` 变更时重派生；
  markup 编辑器按自身 toolbar 实高）。
- **E7/E8**：30 处 lambda 改信号对信号直连或 bound method；9 处 bound-method
  存储改 `WeakMethod`（把 `sheet.py` 的 `_weak_bound` 上提为共享工具，建议放
  `ui_kit/` 或 `mf4_analyzer/qt_lifecycle.py`）。**新增机械护栏**：AST 棘轮测试
  冻结 `ui/`+`acquisition_ui/` 下 `.connect(lambda` 的 文件→数量 白名单，
  shrink-only（照 `test_main_window_state_ownership.py` 范式）。
- **E9**：`searchable_combo` 的 `_highlight_char_indexes`/`_split_combo_label`
  按 `(text, query)` 缓存，QFont/QColor 提为类属性，`casefold()` 移出循环。
  **不要**试图靠减分配来防 GC 段错误（triage 文档明令），这是纯性能修理；
  GC 安全靠 E7/E8 消环。

## 4. 新增机械护栏汇总

| 护栏 | 形式 | 看守的模式 |
| --- | --- | --- |
| QSS 状态规则 border 简写 lint | `tests/ui_kit/` 新测试，白名单空起点 | G7（静默清零 radius） |
| `.connect(lambda` 棘轮 | AST 扫描 + shrink-only 白名单 | G2/生命周期（引用环） |
| paint 计时器哨兵 | 真 canvas 上断言 backstop 已装 | G7（安全网自身失效） |
| verify 工具回读原则 | parity/frozen 各补「期望值来源于产品回读」断言或注释契约 | G2（守卫复述错误） |

护栏红了就修代码，不放宽护栏——与既有棘轮同纪律。

## 5. 需产品裁决项（执行前问 owner，不要自作主张）

1. **D5**：FFT「重叠」旋钮——接线到 `avg_overlap`、删除、还是文案如实化？
   （plan 默认按文案如实化执行，其余两项涉及功能增删。）
2. **C13**：批处理切片色 `#dc2626` 与画布 `#e03131`——对齐色值（动 ΔE 调色成果）
   还是改 docstring 承认分叉？（plan 默认改 docstring。）
3. **批处理 tick density 默认**与交互侧是否统一（`4eb00502` 注释留的未决口）——
   本次不动，仅记录。
4. **E5 文件列表 ElideMiddle** 会改变文件名显示习惯——默认执行，若 owner 在意
   观感可回退单条。

## 6. 明确的非目标

- 不改任何 ink/AA 常量的**数值**（它们是真机标定值，spec §5 流程管着）。
- 不放宽任何性能门禁与既有测试断言。
- 不动 `signal/` 数值算法本体（COT/FFT/FRF 的历史兼容边界维持）。
- 不实现 Stage 2 unresolved/relink、不动 View 上限、不新增用户可见功能
  （诊断出口的 toast/tooltip 不算新功能，算修复静默丢失）。
- 不动 `tests/ui/conftest.py` 的 pin 逻辑与仓库根 `conftest.py`。
