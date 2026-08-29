# WWT 导入保真回归修复与 UltraView 投影加固 Spec

- 日期：2026-08-29
- 状态：已实施（`wwt-hardening-int` @ `14ce32bc`）
- 基线：`main@4247fb78`
- 配套计划：
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md`](../plans/2026-08-29-wwt-import-fidelity-and-projection-hardening-plan.md)
- 前置规格（产品合同不变，本文是第二轮加固）：
  [`2026-08-28-wwt-winwert-layout-import-spec.md`](2026-08-28-wwt-winwert-layout-import-spec.md)
  （原合同 §1–§16 与加固合同 §17 继续有效）
- 审查范围：`1cb54cac..4247fb78` 全部 9 个提交，重点为 `4247fb78`
  （squash 合入 `9efb35d8`…`5e46059a`）落地后的当前行为

## 1. 一句话结论

> `4247fb78` 修复了 record store 所有权、claimed 语义、诊断分级和 tick 防护，
> 但同时**无文档背书地砍掉了 record-only 评价/XY 曲线的渲染与 WinWert 颜色**，
> 造成真实客户文件里整窗、整曲线静默消失（YP 红色公差线不画，U-Can 7 窗只出
> 5 View、9 窗只出 3 View），且用户得不到任何提示；UltraView 投影在非空看板、
> template 看板和 cap 边界上会产生非法重叠、静默丢卡和越界 membership，
> 保存重开后布局漂移。本轮修复恢复原规格的图形语义合同、把所有丢弃变为可观察
> 降级，并补齐投影与 IO 解析的边界防线。

判定依据：原规格 §1「曲线、逐曲线 X/Y 关系、……颜色……保持 WinWert 图形语义」、
D5/D6/D7、§7.2「curve_bindings = 所有 visible rows 的有序绑定，**包括未
materialized 的评价线/XY 记录**」、§14.2「YP proposal 同时包含红色 `Tol_oben`
和深蓝 `Druckstückspiel`」、§11「所有 recoverable fallback 必须可观察」，以及
§17.3 自己的表述「record-only Y……可见性仍由导入时的 binding 决定」。当前实现
与上述每一条冲突，且 `4247fb78` 的提交说明、spec §17、lessons 均未记录该收窄
是有意的产品决策。

## 2. 实测证据（2026-08-29，本机真实样本 + 合成复现）

### 2.1 真实样本：record-only Y 被静默丢弃

`testdoc/WWT`（gitignored，本机存在）四个样本经
`load_wwt_document → build_wwt_view_proposals` 实测：

| 样本 | windows | proposals | 丢失内容 |
| --- | ---: | ---: | --- |
| `YP_SS_000089.wwt` | 1 | 1 | 窗口保留，但 `Tol_oben`（record #1，Real，record-only）整条不画；只剩 `Druckstückspiel` |
| `NLTNP_000089.wwt` | 1 | 1 | 4 条可见 Y 只画 2 条；`y_pos`/`y_speed`（record-only）丢弃 |
| `U-Can_D6-CSER double_00479.wwt` | 7 | 5 | 窗 6/7（Rack Force 对称/迟滞 XY，records #18/#19）整窗消失 |
| `U-Can_EO3_000089.wwt` | 9 | 3 | 窗 3/5/6/9（record-only Y）整窗消失；窗 4/8 无可见 Y（合法跳过） |

三重静默：`build_wwt_view_proposals` 的 record-only `continue`
（`mf4_analyzer/ui/wwt_view_import.py:275`）不产生任何 warning；整窗丢弃的
`if not visible: continue` 同样无诊断；确认框文案「检测到 N 个 WinWert 数据窗口」
的 N 取 `len(proposals)` 而非文件实际窗口数，用户从头到尾不知道有东西被丢。

关键事实：绑定解析层 `bound_time_plot_rows()` **仍完整支持** record-only Y
（`tests/ui/test_time_curve_bindings.py::test_record_only_y_plots_without_checked_identity`
在守护），record store 也已由加载层附着。断点只在提案翻译层一处。

### 2.2 合成复现：共享轴 native tick 事实被先到者抢占

`build_wwt_view_proposals` 里 `native_y` 的 `if/elif` 两个分支代码完全相同
（`wwt_view_import.py:340-353`），实际语义是「该轴第一条 visible 行赢」。实测：
未选中评价线（tick=0/grid=0）按 D6 并入 owner 轴且排在 owner 之前时，
`native_ticks["y"]` 记录的是 `major: 0.0, grid: 0.0`——owner 的 `0.05/0.05`
主刻度/网格被静默丢弃，整轴退回自适应刻度。这正是 YP 场景（`Tol_oben` 与
`Druckstückspiel` 共轴）。

### 2.3 View 恢复路径：轴与 tick 事实按位置 zip 配对

`_view_mixin.py` 的 native tick 应用把
`y_axes = axes_list + _overlay_aux_axes` 与
`y_specs = native_ticks["y"].values()` 按**位置** `zip` 配对，没有 axis_id 身份。
一旦某条 channel-backed 绑定未产生 row（用户取消勾选、解析失败），实际创建的
轴数少于 spec 数，配对整体错位——刻度可能应用到错误的轴上。

### 2.4 UltraView 投影（实测，非静态推断）

1. **非空 free-grid 看板**：`apply_native_layout` 对既有卡片零碰撞检查，投影卡
   直接压在既有卡上（产品其他入口对同样重叠一律 `grid_collision` 拒绝）；
   保存后重开时 `serialization` 把碰撞卡降级进未放置区——**保存的布局 ≠ 重开
   看到的布局**。
2. **template 模式看板**：直接翻转 `layout_mode`，既有 `placements` 卡片成为
   孤儿，membership 静默丢失；正确迁移函数 `template_to_free_grid()` 就在同文件
   却未被复用。
3. **membership cap**：placed 循环触顶后仍 `_append_unplaced` 且不扣减，实测
   202/200；载入侧按 200 硬截断，重开后超出的 ref 消失。同函数 unplaced 循环
   与 `add_ref` 都是「warning 后拒绝」，三处语义不一致。
4. **无效 rect（零宽/零高/NaN/inf）**：混入时对应 ref 被过滤后彻底消失——不进
   placed、不进 unplaced、无 warning；而「全部无效」时又会进 unplaced，可证
   「进 unplaced」才是本意。`decode_window_rect` 对几何零校验，`right == left`
   的畸形显示块可从真实文件一路到达此处。
5. **原始码外泄**：`_toast_grid_warnings` 的映射表不认识本路径产出的
   `exact_overlap` / `quantized_collision` / `placed_limit` / `duplicate_ref`，
   兜底直接把原始码弹给用户——UCAN 标准样例每次导入都会弹一条
   `exact_overlap: 7 -> 6` 黄 toast，与 `wwt_import_coordinator` 自己的
   `_SILENT_CODES`（「确认框已解释，不再黄条」）直接矛盾。
6. `WwtImportOutcome` 的 overlap 文案硬编码「1 个重叠窗口」，与传入的
   `overlap_count` 无关；确认框也只报第一对重叠。
7. 协调器丢弃 `add_time_views_from_native_layout(...)` 的返回值，投影侧
   warnings 不进入 import summary。

### 2.5 IO 解析防线缺口

1. **P2**：`Zeit` 记录无数据区（`dlen=0`），其 u32 声明点数绕过文件大小校验，
   损坏头部可触发 `np.arange(n)` 约 17–34 GB 分配（`MemoryError` 或换页卡死），
   而重同步路径明明有 `n < 50_000_000` 的界。
2. `-1e300` pen-up 哨兵在**缩放后**检测；`Real` 记录一旦带非单位 scale 即漏检，
   巨值进曲线打爆量程。
3. 公式部分非有限（除零 inf/NaN）静默物化，违反原 spec §5.2 第 5 条
   「保留并产生 warning」。
4. `Pars` 公式按 256 字节硬截断且不要求 NUL 终止；超长公式可截成「白名单合法
   但引用错误记录」的表达式，静默产出错误数据。
5. 物化成功但 cohort 是辅助短块的 `Pars` 从三类诊断出口（通道/auxiliary/
   diagnostics）全部消失。
6. 公式 cohort 判据用 `axis_record` 严格相等，而分组层按 `(n, dt, t0)` 合并
   多个 Zeit 块——跨同参数块的公式被 `formula_axis_mismatch` 误拒（保守误杀）。
7. `evaluate_wwt_formulas(strict=False)` 的 `_as_1d` 抛裸 `ValueError`，
   可绕过「只捕 `WwtFormulaError`」的合同（公开 API 缝隙，parse 路径不可达）。

### 2.6 其他接线与卫生

1. `meta["native_axis"]`（每绑定 y 范围/tick/grid）与
   `meta["native_xy_full_range"]` 产出后**全仓库无消费者**：前者是死数据，
   后者违反原 spec §7.3「在诊断详情标记」。
2. `window.py` 取 active view 与 `canvas.py` 取 logical DPI 各有一处新增的
   宽泛 `except Exception`，违反 AGENTS.md Robustness Rules。
3. `apply_native_layout_plan` 返回值是「board 上全部 time 卡」而非「本次放置」，
   已冻结进公共方法清单但语义失真（当前无生产消费者）。
4. 范围外附带：`ultraview_workspace_controller.py:1172` 引用未定义的
   `logger`（`aeaf04f1` 引入，先于本审查范围），`rename_board` 带 warning 时
   必然 `NameError`。

### 2.7 测试盲区汇总

- 提案层：record-only Y 的行为被新测试**反向钉死**（`drops_record_only`、
  `omit_record_only_y_window` 等），修复时这些测试要按新合同反转。
- 渲染层：native tick 的轴配对在「部分绑定未渲染」下无覆盖；toast 文案无断言。
- UltraView：非空/template 看板投影、两个 cap 触顶、`quantized_collision`、
  无效 rect 去向全部零覆盖；端到端投影在 flow/session 测试里被
  `lambda items: ()` stub 且不捕获 items。
- IO：巨大 `Zeit n`、IO 层 `unknown_record`、load 路径公式失败端到端降级、
  AST 白名单逐类参数化（Subscript/Lambda/keyword/Pow/comprehension/字符串）、
  哨兵×scale、部分非有限、Pars 重名改名、`parse_wwt_document` store 附着、
  尾块 `count==0 / >4096` 边界。

## 3. 范围

### 3.1 要做

1. 恢复 record-only 评价/XY 曲线的绑定生成与渲染（提案层接回既有绑定能力），
   保持「不晋升 Navigator 通道、不参与 checked 门控、不伪造时间轴」。
2. 一切窗口/曲线丢弃变为可观察：稳定 code + 确认框如实计数。
3. 恢复 WinWert 颜色语义（细则见 D3）。
4. 共享轴 native tick 事实归 selected owner；View 恢复按 axis_id 配对轴与
   tick 事实。
5. UltraView 投影五项加固：既有卡碰撞、template 迁移、membership cap 不变量、
   无效 rect 去向、warning 出口翻译与单点化。
6. IO 防线：`Zeit n` 上限、哨兵缩放前检测、公式 NUL 终止要求、部分非有限
   warning、`_as_1d` 异常类型、辅助 cohort Pars 可见性、公式 cohort 判据对齐
   分组键。
7. 清理：消费或删除死 meta、收窄两处 `except Exception`、修正
   `apply_native_layout_plan` 返回值语义、补 `logger`。
8. 补齐 §2.7 列出的测试盲区；反转与新合同冲突的既有测试。

### 3.2 明确不做

- 不扩展 WinWert 公式语法、LOG/Factor/Move 支持范围（继续按原 spec §11 降级）。
- 不新增 record-only 曲线的 Navigator 开关 UI（可见性仍由导入时 binding 决定，
  与 §17.3 一致）。
- 不改 ink/AA/raster 阈值、150 ms idle timer、View restore 顺序。
- 不改 UltraView 微网格 schema、GRID_* 常量与归一化算法（已验证与 spec 字面
  一致）。
- 不把客户 WWT 提交进仓库；真实样本继续只作 skip-guarded smoke。
- 不重做 `_ChannelKeyDict`、claimed/successful 语义（已验证正确）。

## 4. 决策

### D1 — record-only Y 是绑定曲线，不是 Navigator 通道

恢复原 spec §7.2：所有 visible 行（含未物化的评价线/XY 记录）都生成
`TimeCurveBinding`。record-only Y 的 `y_ref.kind="wwt_record"`：

- 不进 `ViewState.checked`、不进 `ylims`（无 Navigator 身份），可见性由绑定
  存在与否决定（§17.3 原文）；
- 轴规划继续走 D6（selected owner / 单位+范围完全匹配并轴 / 否则独立隐藏轴 +
  `hidden_axis`），record-only 行同样参与；
- 渲染走既有 `bound_time_plot_rows()` record 路径（无 checked 门控、无
  acquisition mask、`native_xy_full_range`），该路径已有测试。

`4247fb78` 引入的三条保护性质**保持不变**：record-only 记录不生成 FileData、
不触发 1000 Hz 假时间轴、失败绑定不回落普通 Time-Y。

### D2 — 丢弃必须可观察，确认框如实计数

- 新稳定 code：`dropped_curve`（单条 Y 无法成为绑定且非既有 code 覆盖）与
  `dropped_window`（结构合法窗口最终未生成 View）。`unknown_record` 等既有
  code 语义不变。
- D1 落地后 record-only 不再是丢弃理由；`dropped_*` 只覆盖真实降级
  （unknown record、全行不可解析等）。
- 确认框「检测到 N 个」中的 N = 文件中结构合法且含可见曲线的窗口数；若
  proposals < N，正文注明差额与原因归类。空窗口（无 visible Y）不计入 N，
  与原 spec §11「空窗口不生成」一致。

### D3 — WinWert 颜色是导入时的初始色，不是全局皮肤

验收对象回到原 spec §14.4「RGB」与 §2.1「红色 `Tol_oben` 与深蓝测量曲线」：

- record-only 行：`binding.color` 恢复保存 `#rrggbb`（WinWert sRGB 转换），
  渲染直接使用——红色公差线由此成立；
- channel-backed 行：`binding.color` 同样保存 WinWert RGB，并把该色种子进
  **该 View 自己的** `ViewState.colors`（per-view 字段）；运行时
  `channel_colors` 覆盖逻辑保持——用户之后在 Navigator 改色仍然生效并随
  View 持久化；
- 约束：种子只写导入创建的新 View 的 colors map，不改其他 View、不改任何
  全局默认色。若实施中证明 View colors 投影会污染全局 swatch（`4247fb78`
  注释声称但未给证据），以实测证据为准记录偏差并至少保住 record-only 侧的
  WinWert 颜色，同时把该证据写回本节。
- 实施证据（T3，`b228c746`）：**没有污染**，D3 全文落地、无偏差。
  `view_bridge.apply_controls_from_state` → `navigator.set_channel_colors`
  是既有的 per-view merge overlay，不改 `FILE_PALETTES`、不写其他
  `ViewState`。隔离测试
  `tests/ui/test_view_channel_scope.py::test_wwt_view_color_seed_does_not_pollute_other_views`
  证明：导入并 apply 含 WinWert RGB 的新 View 后，既有非 WWT View 的
  `colors` 不变；切回该 View 恢复其颜色；CSV-only 通道不被重着色。
  YP smoke：`Tol_oben` `#ff0000`，`Druckstückspiel` `#000080`。

### D4 — native tick 事实归 owner，配对按身份不按位置

- `native_y[axis_id]` 的 tick/grid/lo/hi 一律取该轴 **selected owner 行**；
  非 owner 行永远不写（删除现在完全相同的 if/elif 分支）。
- View 恢复路径改为按 `axis_id` 配对：native_ticks 的 y 表以 axis_id 为键，
  轴创建侧（overlay 轴槽已有 axis_group=axis_id）暴露 axis_id → AxisItem 的
  查找，不再 `zip`。任一侧缺失该 axis_id 时该轴走 adaptive，不错位、不半应用
  （与 §17.5 all-or-nothing 一致）。
- `meta["native_axis"]` 若在本轮内无消费者则删除；`native_xy_full_range`
  接入 View plot issue 详情（原 spec §7.3），或同样删除并改由绑定 kind 推导，
  二选一，不留死数据。

### D5 — UltraView 投影与产品其余入口同一套不变量

1. `apply_native_layout` 对 `board.free_grid` 既有卡做碰撞检查，冲突项与 plan
   内量化碰撞同语义（进 unplaced + warning），不重排既有卡。
2. template 模式看板先走既有 `template_to_free_grid(board)` 迁移，再投影；
   不翻 mode 丢卡。
3. membership 触顶：warning 后 `continue` 不加入，与 unplaced 循环、`add_ref`
   对齐；任何路径不得使 membership > 200。
4. 无效 rect 的 ref 进 unplaced + `invalid_rect` warning，与「全部无效」分支
   一致。
5. warning 出口单点化：投影 warnings 经返回值交 `WwtImportCoordinator` 并入
   import summary（`_SILENT_CODES` 规则对其生效）；
   `apply_native_layout_plan` 不再直接 toast 本路径的原始码。placed 触顶复用
   既有 `grid_full` 文案或补映射。overlap 文案使用真实计数。
6. `apply_native_layout_plan` 返回本次实际放置的 ref 集合。

### D6 — IO 解析先证明边界再分配

1. `Zeit` 物化前校验声明点数（复用重同步的 50M 界或按剩余文件字节推界），
   超限按既有截断错误处理——与 §17.5「先计数再枚举」同一原则。
2. 哨兵检测移到缩放前 raw 域：`raw == -1e300` → NaN → 再缩放。
3. `Pars` 公式仅在截断窗口内出现 NUL 终止时接受；否则 `formula=None` +
   `unsupported_formula`。
4. 公式结果部分非有限：物化成功 + 追加
   `formula_nonfinite_values: record N: 有限数/总数` 诊断。
5. `_as_1d` 改抛 `WwtFormulaError`，`strict=False` 合同封闭。
6. 辅助 cohort 的已物化 `Pars` 进 `wwt_auxiliary_records`（retained 类），
   不再从全部出口消失。
7. 公式 cohort 判据放宽为与分组键一致的 `(declared_n, dt, t0)` 三元组相等。

### D7 — 测试以合成夹具钉合同，真实样本只作 smoke

延续 §17.6：`tests/_helpers/wwt_factory.py` 扩展/复用三类 profile 覆盖新合同
（record-only Y 渲染、共享轴 owner tick、无效 rect、cap 边界、巨大 Zeit n、
哨兵×scale 等）；`testdoc/WWT` 字面断言全部 skip-guarded。与新合同冲突的既有
测试（§2.7 第一条）按新合同反转，不得并存两套断言。

## 5. 错误与降级表（增补，其余沿用原 spec §11 与 §17.4）

| 条件 | 数据 | View | 用户可见结果 |
| --- | --- | --- | --- |
| 窗口含 record-only Y | 正常加载 | 生成绑定并渲染（D1） | 无提示（正常功能） |
| 单条 Y 确实无法成为绑定 | 正常加载 | 跳过该曲线 | `dropped_curve` 汇总一次 |
| 结构合法窗口最终未生成 View | 正常加载 | 不生成 | `dropped_window` 汇总 + 确认框差额 |
| 投影与既有卡碰撞 | 不变 | View 保留 | 该 ref 进未放置区，汇总一次 |
| template 看板投影 | 不变 | View 保留 | 既有卡迁移保留，无丢失 |
| membership/placed cap | 不变 | View 保留 | 拒绝加入 + 中文 cap 文案一次 |
| 无效窗口 rect | 正常加载 | View 保留 | ref 进未放置区 + `invalid_rect` |
| 损坏 Zeit 声明点数 | 该文件报截断错误 | 不生成 | 与既有截断文案一致，不吃内存 |
| 公式部分非有限 | 物化 | 正常 | `formula_nonfinite_values` 一次 |
| 公式无 NUL 终止 | 原始通道加载 | 依赖曲线按既有降级 | `unsupported_formula` |

## 6. 验收矩阵

### 6.1 合成夹具（核心合同，干净 checkout 可跑）

- record-only tolerance profile：proposal 含 record-only 绑定；渲染 rows 含
  该曲线且颜色为 WinWert RGB；不在 checked/ylims；取消勾选 channel-backed Y
  不影响 record-only 行。
- 共享轴 profile（评价线先于 owner）：`native_y` 事实 = owner 的 tick/grid。
- 部分绑定未渲染时 native tick 按 axis_id 命中正确轴，缺失轴走 adaptive。
- UltraView：非空看板、template 看板、200/24 cap 恰好与超一、混入无效 rect、
  quantized_collision——每项断言 membership 不变量、unplaced 去向、warning
  code 与一次 history/refresh；投影集成测试不 stub 真实 seam（lesson
  `codex-wwt-ultraview-real-boundary-test`）。
- 巨大 Zeit n 夹具：拒绝且峰值内存有界；哨兵×scale 夹具：NaN 保留。
- import summary：`dropped_*` 各出现一次、原始码不外泄（断言 toast 文案）。

### 6.2 真实样本（skip-guarded smoke）

- `YP_SS_000089.wwt`：1 View、2 条曲线（`Tol_oben` 红 + `Druckstückspiel`），
  共轴 `0..0.2`，native 主刻度 0.05。
- `U-Can_D6-CSER double_00479.wwt`：7 proposals；6 placed + 1 unplaced。
- `U-Can_EO3_000089.wwt`：7 proposals（9 窗减 2 个空窗）；空窗不计入
  确认框 N。
- `NLTNP_000089.wwt`：1 View、4 条曲线。

### 6.3 门禁

聚焦 owner 测试 + 既有边界门禁（state ownership、backref、import boundaries、
signal no-GUI、batch render boundary、no-lambda、QSS）。全套与真实前台六项
按 CLAUDE.md 门禁规则由集成里程碑统一执行一次；上一轮的 UNVERIFIED 状态
（主套 segfault、前台未跑）不得由本轮继承为「已通过」。

## 7. 完成定义

1. §6.1 合成合同全绿，与旧合同冲突的测试已反转、无并存断言。
2. 本机真实样本 smoke 达到 §6.2 字面值。
3. UltraView 投影五项不变量成立，membership 任何路径 ≤ 200，保存/重开布局
   一致。
4. 所有新增降级都有稳定 code 且只报一次；确认框计数与文件事实一致。
5. 死 meta 清理完成；两处宽泛 `except Exception` 收窄；`git diff --check` 通过。
6. 原 spec §14.4 前台验收（SFNS/YP/UCAN 真机）执行或显式记 `UNVERIFIED`。
