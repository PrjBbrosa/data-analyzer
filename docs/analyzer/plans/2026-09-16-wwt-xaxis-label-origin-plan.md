# WWT 版式横坐标标签来源修复计划

- 日期：2026-09-16
- 状态：**已实施**（offscreen owner 通过；Cocoa/Windows 前台 **UNVERIFIED**）。
- 分析基线：HEAD `0bcac91e`；实施时 HEAD `a58f8c01`。仅修改 importer 与下列测试/lesson，未覆盖页面切换或 FFT 游标在途改动。
- 目标：**新导入 WWT 版式的 ordinary 通道 X 标题，第一次切到「自动(时间)」即清空自动标题草稿，应用后显示真实时间轴；手写标题仍保留。**
- 合同：[优化鲁棒性 spec R07 / A12–A13](../specs/2026-09-12-optimization-robustness-spec.md)；其中 T6 是对应实施任务编号，不是本 spec 的章节名。

### 实施台账

产品改动：`mf4_analyzer/ui/wwt_view_import.py:_x_axis_opts` 的 ordinary 通道分支写入 `label_origin=LABEL_ORIGIN_AUTO`。time fallback 仍无该字段。旧项目显式 `user` 不迁移。

T0 红证据（修复前）：`label_origin` 为 `user`，`test_ordinary_x_axis_opts_mark_layout_title_auto_even_when_it_differs` 等 7 条 proposal 断言失败。

Owner gate（项目 venv / offscreen）：`tests/ui/test_wwt_view_import.py`、`tests/ui/test_wwt_import_flow.py`、`tests/ui/test_time_channel_drop.py`、`tests/ui/test_time_xaxis.py` 共 **84 passed**；另跑项目节点：

- `tests/ui/test_wwt_import_flow.py::test_wwt_layout_import_first_time_switch_clears_auto_draft_then_apply_uses_time`
- `tests/ui/test_wwt_import_flow.py::test_wwt_imported_auto_label_becomes_user_after_edit_and_survives_time_switch[Manual title]`
- `tests/ui/test_wwt_import_flow.py::test_wwt_imported_auto_label_becomes_user_after_edit_and_survives_time_switch[ChanX]`
- `tests/ui/test_wwt_import_flow.py::test_wwt_imported_auto_label_becomes_user_after_edit_and_survives_time_switch[WinA [mm]]`
- `tests/ui/test_wwt_import_flow.py::test_wwt_unapplied_time_draft_does_not_commit_when_switching_views`
- `tests/ui/test_wwt_import_flow.py::test_wwt_mixed_exact_binding_keeps_curve_x_when_view_applies_time`
- `tests/ui/test_wwt_import_flow.py::test_wwt_record_only_view_keeps_curve_bound_readonly_controls`
- `tests/ui/test_project_session.py::test_project_roundtrip_keeps_wwt_auto_xaxis_label_origin`
- `tests/ui/test_project_session.py::test_project_roundtrip_keeps_wwt_user_xaxis_label_origin`
- `tests/ui/test_project_session.py::test_project_roundtrip_keeps_same_text_user_xaxis_label_origin`

`git diff --check` 通过。lesson：`docs/lessons-learned/layout-derived-x-titles-are-auto-origin.md`。Cocoa 前台客户样例未跑，标 **UNVERIFIED**。

## 1. 审查结论与原计划缺口

单点修改 `_x_axis_opts` 的方向正确、范围较小，当前恢复/apply/persistence 链能够传递 `label_origin`。不需要改 Inspector 清空判定或新增来源状态。但原计划存在以下缺口：

| 级别 | 缺口及影响 | 修订 |
|---|---|---|
| P2 | 没有说明旧项目。原导入已经把错误的 `user` 显式保存；仅修新导入不会修复历史 View。 | 明确新导入边界，不按名称猜测并迁移旧 user；历史恢复单列限制。 |
| P2 | “图和轴标题都回到时间轴”未区分 ordinary 与 exact binding；混合 View 仍可能含曲线自带 X。 | 仅 ordinary 曲线服从全局 X；exact binding 完整保留，不承诺整张混合图全变时间轴。 |
| P2 | 只验 Inspector 标志/全局 spec，不能证明真实恢复、应用、曲线数据与轴标签一致；现有 `_stub_wwt_ui` 会屏蔽 `plot_time` 和 `_apply_active_view`。 | 添加真实导入/恢复/按钮 apply 的定向回归，不用该助手屏蔽目标链路；补持久状态、数据和绘制标签断言。 |
| P2 | 只运行通用手写标题测试，没有证明 WWT auto 经用户编辑后能转 user 并在 View/project 往返保留。 | 增加 WWT 专属 textEdited 覆盖及 auto/user round-trip。 |
| P3 | “实施时只碰本计划文件”与实施代码步骤矛盾；前台验收被写成除非再要求才做。 | 区分本次文档修订与后续实施授权；前台验证纳入实施门，无法执行时明确 UNVERIFIED。 |

修复可实现，未发现需要扩大到 Inspector/数据算法的必然条件。不能保证绝对零 bug；以下回归和视觉门用于约束已识别风险，不把计划完成当修复验收。

## 2. 当前根因和本次验证

1. `ui/wwt_view_import.py:_x_axis_opts` 为 ordinary 通道构造 `CustomXAxisSpec`，没有传 `label_origin`，默认是 `user`。
2. `to_axis_opts()` 已显式写出 `label_origin=user`，不是单纯缺字段；老项目恢复会尊重这个值。缺字段时若版式标题与 channel 不同，兼容推断也会得到 user。
3. `_restore_view_axis_opts` / `_sync_inspector_to_xaxis_spec` 按 `spec.label_origin` 投影 `_xlabel_auto_from_channel`。
4. `persistent_top.py:_sync_xlabel_for_xaxis_mode` 仅在该标志为真时清空标签。再选一次指定通道会重新生成标签并标 auto，解释了来回切换后似乎恢复的现象。
5. 标签来源不参与数据源匹配。`PER_SOURCE_NAME`、`source_fid=None` 和 ordinary/exact 分类必须保持。

本次审查用 `tests/_helpers/wwt_factory.py:multi_window_overlap_and_formula` 生成文件，在隔离 QSettings 的 offscreen MainWindow 中，仅替换确认对话框为接受，实际执行 `_load_one`、恢复和 `btn_apply_xaxis.click()`。随后在进程内模拟 `_x_axis_opts` 只给 channel 分支增加 auto，未修改产品文件：

| 阶段 | 当前行为 | 模拟单字段修正 |
|---|---|---|
| 导入首个 ordinary View | `WinA [mm]` / user | `WinA [mm]` / auto |
| ViewState 字典往返 | 保留 user | 保留 auto |
| 第一次切 time，尚未应用 | 旧标题仍在；实际 spec 仍 channel | 草稿为空；实际 spec 仍 channel |
| 点击应用 | time，label=`WinA [mm]` | time，label 为空，活动 View 持久状态同步 |

此证据确认主链路可行，不代替正式失败/通过测试；尚未在本次审查测量图上标签像素、项目文件重开、混合曲线、Cocoa 或 Windows。

## 3. 产品与兼容决定

| 场景 | 合同 |
|---|---|
| 新导入 ordinary 通道 X | WWT 窗口 X 标题视为随来源的自动投影，标 auto；指定通道模式仍显示原版式标题和单位，不改为裸通道名。 |
| 首次切「自动(时间)」 | 清空输入框并露出现有 `Time (s)` 占位符，不把占位符写入持久标签。 |
| 草稿未应用 | 当前已应用 spec、View axis_opts、曲线 X 和图上标题不变；既有草稿交互信号保持，不新增 live replot。 |
| 点击「应用」 | ordinary 曲线按原时间数据绘制，View X spec 为 time/空标签，图上为真实默认时间轴标题；原 source-change 范围/缓存处理按现有代码执行，不要求错误地保留旧通道 X 范围。 |
| 导入后用户编辑标题 | `textEdited` 转 user；任意标题、与通道同名、与版式标题同名均是 user。用户清空也尊重既有合同，不反推来源。 |
| 保存/切 View/重开 | 新 auto 与 user 显式保真，版式标题原文保真；不得在 capture/restore 按文本重新推断。 |
| 混合 ordinary + exact bindings | 只有 ordinary 曲线使用 View-wide X。曲线自带的精确 X/Y 与绑定身份不变，不强行改成 time。 |
| 全部曲线自带 X | 保留只读来源投影及禁用控制；不改 time fallback 标签，不因本修复解除绑定或启用按钮。 |
| 已保存旧 View/项目 | 显式 user 保持 user；缺 origin 的旧 payload 沿用 `from_axis_opts` 推断。此修复不自动修复历史误标。 |

旧状态中的误标 user 与用户实际手写无法可靠区分，**不能无损自动迁移全部旧项目**。需要新行为时可重新导入版式创建 View；不得自动覆盖旧 View 的人工修改。若要求修复现有项目，另行设计用户明确选择的转换，不按 View 名、标题或 WWT 文件后缀猜测。

## 4. 最小实现与非目标

产品 owner：`mf4_analyzer/ui/wwt_view_import.py`。

- 从 `ui/time_xaxis.py` 显式导入 `LABEL_ORIGIN_AUTO`，仅在 `_x_axis_opts` 的 ordinary channel 分支构造 `CustomXAxisSpec` 时传入该常量。
- 保留 channel/resolver/fid/label 其余内容、time fallback、proposal 顺序、颜色、Y 轴分组、范围、附件、checked 和 exact bindings。`label_origin` 是已有字段，不新增 schema/version。
- 不修改 `persistent_top.py`、`_apply_xaxis`、`from_axis_opts` 的历史推断、拖放路径和曲线绑定算法，不把 CustomXAxisSpec 全局默认改 auto。
- 不改 DSP/采样/时间轴生成、settle/ink/AA、提示文案或 live apply；不重写历史 WWT spec。
- 若定向证据发现恢复链丢来源，先定位具体 owner 并补红测试，再修订本计划范围；不得为了满足期望扩大字符串猜测或重写 UI。

这是来源元数据修复，没有新增/移除/重命名交互，不要求修改 hints/quickref；若实施中改变用户交互语义，则重新评估文案和范围。

## 5. 测试与执行步骤

### T0：冻结来源语义并建立红证据

- 记录 HEAD/相关文件哈希；确认 `wwt_view_import.py` 及必要测试没有其他任务冲突。先运行新增失败节点及受影响 owner，禁止通用 full-suite baseline。
- 合成 fixture 必须包含 **标题不同于通道名且带单位** 的 ordinary View，例如 `WinA [mm]` / `ChanX`。核心测试不依赖 gitignored `testdoc/` 客户文件。
- 当前代码必须在“导入 origin auto / 首次清草稿”的新断言上失败；不能先修改预期把旧行为当成通过。

### T1：单点修复及 proposal 合同

- 修改 §4 的唯一产品 owner。
- `tests/ui/test_wwt_view_import.py`：三处既有等值断言按测试名称/构造定位，显式期望 auto，不依赖当前行号。
- 同时验证 ordinary-only、混合 exact、cross-source exact 和纯 record-backed：除 ordinary X 的 origin 外，其余 proposal 字段/绑定保持；time fallback 不新增 auto。
- 不改正向/负向来源匹配预期，不放宽 resolver、fid、curve_bindings 断言。

### T2：真实 UI 与数据闭环

在 `tests/ui/test_wwt_import_flow.py` 增加集中定向回归，必要时复用已存在的合成工厂：

1. 接受导入后原活动 View 真实恢复：标题是版式原文、来源 auto；不把 `_stub_wwt_ui` 屏蔽掉的恢复当成已执行。只 stub 交互确认；若确需短暂屏蔽自动恢复，必须恢复真实方法并明确调用，然后才开始断言。
2. 首次切 time：输入为空、占位符正确；已应用 spec、View axis_opts 和绘图数据尚未改变。至少一个用例走真实分段按钮事件，其余可用 setter。
3. 点击真实应用按钮：spec 与活动 View axis_opts 均为 time/空标签；ordinary 曲线 X 使用源 time 数组，图上默认 X 标签正确。不要只断言 `_custom_xaxis_spec.mode`。数组比较使用 owner 原始 payload/现有数据接口，不拿抽点显示数组长度冒充源数据。
4. 导入后人工编辑标题，覆盖异名/通道同名/版式标题同名：走 `textEdited`（至少一个 QTest 键盘编辑），确认 user；应用、切回 time 后标题保留。
5. 混合 View 应用 time 时，ordinary 与 exact 的预期分别断言，后者 X/Y/ref/binding_id 保持；纯曲线自带 View 控制仍只读。
6. 原标题含单位或为空的边界：明确 import 原文与既有空标题 channel fallback，不新增单位推断或字符串裁剪。

Qt 控件必须显式归属，隔离 QSettings；结束时清理 timer/窗口/deferred deletes，避免本地配置或 teardown 污染。

### T3：View / 项目持久化与既有合同

- 在上述 WWT 流程中执行 View A→B→A，证明版式标题及 auto 保真；应用为 user 后同样不串来源。覆盖未应用草稿离开时沿用既有 capture applied-state 行为，不把 draft 意外写回。
- `tests/ui/test_project_session.py` 只增加/选取 xaxis 相关节点：新 WWT auto 经过真实 project save/load 后仍 auto，首次切 time 清空；WWT user 后保存/重开仍保留。复用既有项目 helper，不能仅用 ViewState.to_dict/from_dict 代替真实重开门。
- `tests/ui/test_time_xaxis.py` 和已有项目 user/legacy 节点保护显式 user、缺字段推断及历史 EXACT_SOURCE。不修改兼容预期以“自动修好”旧项目。
- `tests/ui/test_time_channel_drop.py` 原有 auto 首次清空、手写保留、同名手写为 user 条目继续通过；无需重写拖放功能。

### T4：验证和结论

基本 owner gate（使用项目 runtime）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_wwt_view_import.py \
  tests/ui/test_wwt_import_flow.py \
  tests/ui/test_time_channel_drop.py \
  tests/ui/test_time_xaxis.py
```

追加 T3 新增的项目 round-trip 节点及既有 `test_project_roundtrip_keeps_same_text_user_xaxis_label_origin`；实施时记录实际 node IDs，先确认收集，0 selected 不算通过。若只修改预定 importer，不加无关 renderer/import 全门；涉及新的边界再说明理由补测。不跑全量或整个 tests/ui。

Cocoa 前台用合成 WWT 确认：导入标题不丢、首次切 time 草稿清空、应用后时间轴数据/标签正确、手写保留；有原始客户样例时另列 smoke，不作为可移植核心测试依赖。客户数据、offscreen、Cocoa、Windows 分别记录；环境缺失写 UNVERIFIED，不要求再次授权才能执行已在范围内的验证。

完成条件：新导入 ordinary 场景闭环通过、auto/user 往返保真、exact bindings 与旧项目合同不退化，相关测试通过、`git diff --check` 通过、lesson status 已检查。视觉未验证时明确保留该门，不能只凭状态断言称用户原场景彻底解决。

## 6. 本次文档修订交付

本次只修订本文。已阅读 importer、CustomXAxisSpec、Inspector 同步、apply/restore、View capture 及对应 owner 测试；完成隔离进程的真实导入/按钮应用可行性探针。未修改产品代码，未运行或宣称修复后的正式测试通过；文档检查包括引用、范围和空白。实施是否完成以后续证据为准。
