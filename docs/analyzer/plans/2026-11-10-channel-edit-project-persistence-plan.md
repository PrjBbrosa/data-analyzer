# 通道编辑结果随项目保存：优化计划

- 日期：2026-11-10。
- 状态：**已按本计划实施。** 云端 offscreen 聚焦门禁里的用例全部通过，但进程在解释器退出阶段以 139 退出（基线同样如此），不能记成干净通过，详见 §10；macOS 前台与 Windows 冻结包真机验收未在本环境执行。验收发现见 `docs/analyzer/plans/2026-11-10-channel-edit-persistence-followup-plan.md`；该补丁的 T1–T3 已实施。
- 源码基线：`1e4b25936913f561d0b499bb6e37e238e8c5bcd0`（TraceLab v8.4.6）。实施前重新检查 HEAD 与相关 dirty 范围；下文行号以基线为准，实施时按符号重新定位。
- 授权范围：按本计划实施 T0–T6。不升版本号，不把样点写入项目，不回写源文件。
- 问题：在「通道编辑」里创建派生通道后保存项目，重新打开时这些通道不存在；引用它们的 View 勾选、颜色、分析来源也随之失效，且没有任何提示。
- 推荐路线：**项目里保存「怎么算出来的」（有序编辑配方），打开时在重新加载的源数据上回放**；不把波形数组写进项目。创建与回放走同一个求值函数，回放失败逐条可见。

## 1. 成功标准与范围

实施完成必须满足：

1. 创建派生通道 → 保存 → 关闭 → 重开：通道存在，名称、单位一致，数值与保存前逐点相等（同一源文件、同一构建、同一平台下 `np.array_equal(..., equal_nan=True)`）。
2. 派生通道在通道树里的位置、View 的勾选 / 隐藏 / 颜色 / Y 范围 / 共轴分组、分析 pane 的来源引用，重开后保持。
3. 链式派生（用派生通道再派生）可回放，包括中间通道后来被删掉的情况。
4. 通道编辑里的删除同样回放，重开后的通道集合与保存时一致。
5. 某条配方无法回放（源通道不在了、长度不符、表达式失败）时：这条及依赖它的后续配方被跳过，进入「项目恢复不完整」的既有提示与再次保存确认；不改名、不补零、不猜。
6. `.tlproj` 仍是引用型文件：不含样点数组，体积不随数据长度增长。
7. 通道编辑生效后项目变脏，离开保护能拦住未保存的编辑。
8. 没有通道编辑的项目，写出的文件与现在逐字节一致（仍是 schema 4）；旧项目照常打开。

不在本计划内：把派生数据写回源文件；创建后再修改配方的编辑界面；跨文件（A、B 来自不同逻辑来源）的派生；批处理读取或复用这些配方；通道配置（命名配置）的存储格式；任何一种运算的数值语义改动；版本号升级及其扇出面（归发版任务，见 §9）。

## 2. 当前事实

| 已读源码 | 当前事实 | 对实施的含义 |
| --- | --- | --- |
| `mf4_analyzer/ui/project_io.py:1` 模块说明、`:214` `ProjectFileRef`、`:238` `project_document_to_payload` | 项目只存路径、`fs`、`time_source`、`time_axis_provenance`、`dbc_refs`、`channel_order` 和 View；说明里写明 never parsed data | 保持引用型；新增内容只能是可复现的用户意图 |
| 同文件 `:80` `SCHEMA_VERSION = 4`、`:81` `SUPPORTED_SCHEMA_VERSIONS`、`:341` `load_project_from_json` | 解码按键读取，文件行里的未知键被忽略；版本不在支持集合里才拒绝。引入 schema 4 的提交 `f551a87e` 起解码方式相同 | 只加键不升版本，8.3.0–8.4.6 会静默丢掉配方（见 D4） |
| `mf4_analyzer/ui/main_window/window.py:5042` `_apply_channel_edits` | 只写 `fd.data` / `fd.channels` / `fd.channel_units`，随后刷新缓存、通道树、选择器并重画；不调用 `_note_user_project_mutation` | 数据落点只有内存；编辑当前不算项目修改 |
| 同函数里的 `navigator_order.refresh_channels` 与 `_project_io_mixin.py:2630` | 派生通道**名**已经进了保存的 `channel_order`，数据没有 | 保存的顺序里留着重开后不存在的名字 |
| `mf4_analyzer/ui/navigator_order.py:104` `apply_channel_order` | 恢复顺序时，当前来源里没有的名字直接丢弃 | 回放必须排在恢复顺序之前 |
| `_project_io_mixin.py:2652` `_restore_project_file_refs` | 顺序为：加载 → HDF 采样判定 → 恢复 `fs` / 时间轴 → provenance → `apply_channel_order` | 回放的插入点在 provenance 之后、顺序之前（见 D5） |
| `project_io.py:832` `collect_dropped_time_refs`、`_state_holders.py:212` `ProjectRestoreHealth`、`_project_io_mixin.py:617` `_confirm_degraded_project_save` | 健康报告只统计 **fid 缺失**的引用；fid 在但通道名不在的引用不计入。渲染各处按 `channel not in fd.data.columns` 跳过（如 `window.py:4607`） | 派生通道消失目前完全无提示；失败要接进这套既有健康通道 |
| `mf4_analyzer/ui/dialogs/channel_editor.py:677` `_create_single`、`:923` `_create_dual`、`:869` `_expression_check_finished` | 单通道 6 种运算走 `ChannelMath` 与 `np.abs`；双通道 6 种运算在对话框里直接写 numpy（`A ÷ B` 在 `B == 0` 处取 0）；表达式走 `ExpressionCheckRunner` → `check_channel_expression`。名称、单位规则也在对话框里 | 运算是确定的、参数很少，可以用配方完整描述；但计算逻辑现在散在 UI 层 |
| 同文件 `:81` `new_channels`（名 → (数组, 单位)）、`:82` `removed_channels`（集合）、`:754` `_channel_signal`、`:979` `_remove` | 已暂存的新通道可以作为后续运算的输入；删除会把暂存的新通道弹出；新增与删除之间没有顺序记录 | 对话框需要一份有序的暂存配方，才能表达链式与「先用后删」 |
| `mf4_analyzer/ui/drawers/channel_editor_drawer.py:29` | `applied = pyqtSignal(str, dict, set)`，唯一消费者是 `window.py:5031` | 信号要多带一份配方 |
| `mf4_analyzer/io/file_data.py:253` `FileData`、`:280` `time_axis_provenance` | 来源级事实由 `FileData` 持有，项目按文件行保存并在恢复时写回 | 配方日志照这个先例归 `FileData` 所有，随来源关闭自然消失 |
| `mf4_analyzer/io/blf_format.py:358` `LazyZohFrame` | BLF/ASC 的惰性表实现了 `__setitem__`、`drop(columns=)`、`.columns` | 回放沿用现有写法即可覆盖惰性来源，owner 测试要包含它 |
| `file_data.py:354` `rebuild_time_axis` 的调用点 | 只有文件注册的兼容分支（`_project_io_mixin.py:700`）和项目恢复（`:2711`）；会话中没有交互式重建时间轴 | 依赖时间轴的配方（`d/dt`、`∫dt`、含 `t` 的表达式）在会话内稳定；回放必须排在时间轴恢复之后 |
| `mf4_analyzer/ui/widgets/channel_tree.py:124`、`mf4_analyzer/io/head_hdf.py:282` | `channel_metadata[...]["derived"]` 已被 WWT「Pars 公式通道」计数和 HDF 采样判定使用 | 编辑器派生通道**不要**复用这个键（见 D2） |
| `tests/ui/test_main_window_smoke.py`（6 处）、`tests/ui/test_view_channel_scope.py`（1 处） | 现有用例直接以三个参数调用 `_apply_channel_edits`；多份对话框用例直接读写 `dlg.new_channels` | 保留三参调用与 `new_channels` 这两个测试缝 |
| `docs/analyzer/user-guide/channel-axis-order-guide.html` FAQ Q1 | 写着派生通道关闭文件即丢失，并建议「在批处理里把这套派生写进预设」 | 上线后要改；后半句在 `mf4_analyzer/batch*.py` 里找不到对应实现（只有清单汇总函数 `derive_summary`），一并更正 |

## 3. 设计决定

### D1 存配方，不存数据

项目保存每个逻辑来源的一份**有序编辑日志**，打开时在重新加载的源数据上回放。不采用的方案：

- 把数组写进 `.tlproj`：体积随样点数增长，脏检查的规范化摘要要对整份数据做哈希，并且违背引用型定位。
- 另存一份数据副文件：出现第二份权威数据，源文件更新后副文件过期，还要处理与 JSON 的原子发布顺序。UltraView 预览副文件可以这么做，因为它只是可丢弃的加速层。
- 写回源文件：产品约束禁止。

需要固化数值副本的用户，继续用通道编辑里已有的 Excel / WWT 导出。

### D2 日志内容与归属

日志是 `FileData` 持有的有序列表（`fd.channel_edits`），构造时初始化为空，随来源关闭消失，不需要额外的清理路径。「哪些通道是编辑器派生的」只由日志回答，不往 `channel_metadata` 里再写一份，避免影响 WWT 公式计数和 HDF 采样判定这两个现有消费者。

条目两种，字段都是稳定字符串，不存下拉框序号：

```json
{"op": "derive", "name": "d_dt_speed", "unit": "rpm", "kind": "single", "fn": "derivative", "src": "speed", "param": null}
{"op": "derive", "name": "sum_tq", "unit": "Nm", "kind": "dual", "fn": "add", "a": "tq_a", "b": "tq_b"}
{"op": "derive", "name": "expr_sqrt_A_2_B_2", "unit": "", "kind": "expression", "expr": "sqrt(A^2 + B^2)", "a": "tq_a", "b": "tq_b"}
{"op": "remove", "names": ["tq_b"]}
```

- `fn` 取值：单通道 `derivative` / `integral` / `scale` / `offset` / `moving_avg` / `abs`；双通道 `add` / `sub` / `mul` / `div` / `max` / `min`。
- `name` 与 `unit` 保存创建时已经定下来的最终值。回放不重新跑自动命名，也不重新推导单位。
- `param`：`scale` / `offset` 存浮点；`moving_avg` 存已经过 `max(int(p), 3)` 的窗长；其余为 `null`。
- 表达式保存用户输入的文本（去首尾空白）；`a` / `b` 只在表达式引用到时保存。
- 压缩规则只有一条：删除一个派生通道时，如果日志里没有后续条目用它做输入，就直接删掉它的 `derive` 条目；否则保留 `derive` 并追加 `remove`。删除加载器通道一律追加 `remove`。对当前不存在的名字不记录。

### D3 一个求值函数，创建与回放共用

把现在散在对话框里的计算搬到中立层，对话框改为「先生成配方，再用配方求值」。创建结果与回放结果因此出自同一段代码，不靠事后比对来保证一致。

- `mf4_analyzer/signal/channel_recipe.py`（新增）：条目的数据类与严格校验（字典 ↔ 条目）、`evaluate_derive(entry, time, lookup)`。六种双通道运算移入 `ChannelMath`。纯数值，不引入 PyQt5。
- `mf4_analyzer/io/channel_edit_log.py`（新增）：日志对象（记录、压缩、与 JSON 列表互转）和 `replay(fd, entries)`。回放负责写 `fd.data` / `fd.channels` / `fd.channel_units`，返回逐条结果。`_apply_channel_edits` 里现有的那三步数据写入移到这里，窗口侧只保留缓存失效、View 清理和界面刷新。
- 不在门面或 UI 层留第二份计算。

数值行为保持现状并写进 owner 测试：输出一律 `float64`，长度等于来源行数；`derivative` 少于 2 个样点报错；`integral` 少于 2 个样点返回全零；`moving_avg` 窗长不小于 3，窗长不小于信号长度时返回整段均值；双通道 `div` 在除数为 0 处取 0，而表达式里的除零得到 NaN——这是两条路径现有的差异，保留并注明；非有限输入照常传播；A、B 或时间轴长度不一致时明确报错，不做 `min(len)` 截断；非数值通道报错。

### D4 文件格式：有编辑才升到 schema 5

`ProjectFileRef` 增加 `channel_edits`（列表）。写出时，**只要有任一来源的日志非空，就写 `schema_version: 5`，否则仍写 4**；读取端支持集合加入 5。

理由：只加键不升版本的话，8.3.0–8.4.6 会忽略这个键正常打开——派生通道不见、引用失效，用户在旧版里再保存一次，配方就被永久抹掉，全程无提示。按条件升版本后，旧版对这类项目明确拒绝打开，而不含通道编辑的项目完全不受影响，现有钉住 `schema_version == 4` 的用例也不用改。

已知代价：旧版的拒绝提示文案写死为「工程格式 v4 … 请升级到 v8.3.0 或更高」（`_project_io_mixin.py:2770`），对已经在 8.4.6 上的用户有误导，旧版本无法补救。新版把这条提示改为按 `exc.schema_version` 生成，避免以后重蹈覆辙。

备选是无条件升到 5：实现略简单，但所有新保存的项目旧版都打不开，没有对应收益，不采用。

### D5 恢复顺序

在 `_restore_project_file_refs` 的每个文件行里，时间轴与 provenance 恢复之后、`apply_channel_order` 之前回放日志，然后用 `navigator_order.refresh_channels` 与 `navigator.refresh_file` 把通道集合同步到树，再恢复保存的顺序。这样派生通道名在恢复顺序和后续安装 View 时都已存在。

- 回放整体处在 `ProjectDirtyState.begin_restore()` 之内，不产生用户修改标记，也不弹删除确认。
- 回放里的 `remove` 只改数据，不清理 View：保存下来的 View 在删除当时已经清理过。
- 一个物理文件展开成多个逻辑来源时，日志跟着文件行走，经现有的 `fid_map` 落到对应的新 fid。
- HDF 采样判定仍在回放之前执行，拿到的是未经编辑的加载器元数据，行为不变。
- 界面刷新复用 `_apply_channel_edits` 的同一条通道集合刷新路径，不为恢复另写一套选择器更新。

### D6 回放失败：逐条可见

每条配方回放后得到「已应用」或「已跳过 + 原因」。原因分类：输入通道不存在、输出名已被加载器通道占用、长度不符、时间轴不可用、非数值输入、表达式错误、表达式结果全部无效、依赖的上游配方被跳过、条目无法识别。

- 输出名冲突时跳过，不改名也不覆盖：通道身份是 `(fid, name)`，改名会让保存的引用指向别的东西。
- 被跳过的条目不留在内存日志里，计入 `ProjectRestoreHealth` 的新字段并置 `degraded`；再次保存前走既有的确认框，文案增加「未能重建的派生通道：N」。这与现有「继续保存会固化当前缺失状态」的规则一致。
- View 安装之后，对被跳过的派生通道名调用既有的 `_remove_channels_from_all_time_views` / `_remove_channels_from_all_analysis_views`，把因此失效的引用计入健康报告，避免悬空引用被再次保存。
- 只捕获属于用户 / 数据范畴的异常（`ExpressionError`、配方校验错误、求值里的 `ValueError`）。其他异常照常上抛，不加宽泛的 `except Exception`。对话框 `_create_single` / `_create_dual` 现有的 `except Exception` 在迁移时一并收窄。
- 每条跳过写一条带来源与通道名的日志。

### D7 脏状态

`_apply_channel_edits` 在新增或删除非空时调用一次 `_note_user_project_mutation()`。打开项目后的回放不标脏；无跳过时，重开后重新组装的文档摘要应等于磁盘文件的摘要。

### D8 兼容缝

- `_apply_channel_edits(fid, new_channels, removed_channels, edits=None)`：产品路径始终带 `edits`。不带配方的三参调用继续可用，这样加进来的通道记为「仅本次会话」；保存时如果存在这类通道，写日志，并把警告并进保存结果的那一条 toast（「已保存项目 · N 个通道未随项目保存」）。toast 是单槽，不能另发一条会被结果 toast 顶掉的提示。
- 对话框保留 `new_channels` / `removed_channels`，新增一份平行的有序暂存配方；切换文件时三者一起重置。
- `ChannelEditorDrawer.applied` 增加第四个参数。

## 4. 文件所有权与修改边界

| Owner | 允许的实现工作 | 禁止的扩张 |
| --- | --- | --- |
| `signal/channel_recipe.py`（新增）、`signal/channel_math.py` | 条目、校验、求值；接收从对话框搬来的双通道运算 | 引入 PyQt5 / pandas 依赖；改变任何运算的数值结果 |
| `io/channel_edit_log.py`（新增）、`io/file_data.py` | 日志对象、回放、`FileData.channel_edits` 初始化 | 引入 `ui`；在 `channel_metadata` 里再存一份派生标记 |
| `ui/project_io.py` | `ProjectFileRef.channel_edits`、读写、按条件写版本号 | 在这里做语义校验或求值（条目按原样透传，校验在回放时做） |
| `ui/dialogs/channel_editor.py`、`ui/drawers/channel_editor_drawer.py` | 生成配方、经求值函数计算、有序暂存、信号多带一个参数 | 保留第二份计算；新增 `.connect(lambda`（该文件现有 2 处，棘轮只许缩小） |
| `ui/main_window/window.py` `_apply_channel_edits` | 调用回放 owner、记录日志、标脏；抽出可被恢复路径复用的通道集合刷新 | 新增跨文件写的窗口属性；放宽状态所有权白名单 |
| `ui/main_window/_project_io_mixin.py`、`_state_holders.py` | 保存时写出日志、恢复时回放、健康字段与确认文案、版本拒绝提示 | 重写恢复流程的其他环节；给 `MainWindow` 加裸状态 |
| `ui/hints.py`、`ui/quickref.py`、`docs/analyzer/user-guide/` | 同步「派生通道随项目保存」的说明 | 改历史 spec / plan 使其看似已实现 |

## 5. 执行分步与聚焦门禁

按依赖顺序执行。每步先补测试再改 owner，只跑本步列出的用例；标注「新增」的测试文件当前不存在。命令模板：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本步文件或节点> -q
```

不做改前全量基线。

### T0 冻结现状

- `tests/ui/test_channel_editor_recipes.py`（新增）：对固定输入逐一驱动对话框的 6 种单通道、6 种双通道运算和表达式，断言名称、单位、数值；期望值在用例里用独立的 numpy 表达式写出。覆盖 `B` 含 0、输入含 NaN、窗长小于 3、窗长不小于信号长度、自动命名冲突。这份用例在改动前就应通过，T3 之后必须原样通过。
- `tests/ui/test_project_session.py`：新增「创建派生通道 → 勾选 → 保存 → 重开」用例，当前应失败，T4 之后转绿。同时用一条用例记录现状下悬空引用的实际表现（是否留在 View 状态里、是否被再次保存），作为 D6 清理范围的依据。
- 聚焦基线：上述两个文件的相关节点，加 `tests/signal/test_channel_math.py`、`tests/signal/test_expression.py`、`tests/ui/test_channel_editor_expression.py`。

### T1 中立配方层

- 实现 D2 的条目校验与 D3 的求值函数；双通道运算移入 `ChannelMath`。
- Owner：`tests/signal/test_channel_recipe.py`（新增）——每种 `fn` 的求值、D3 列出的全部边界行为、非法条目被拒绝、字典往返；`tests/signal/test_channel_math.py` 补双通道运算。
- 边界：`tests/test_signal_no_gui_import.py`。

### T2 日志 owner 与项目编解码

- 实现日志对象、压缩规则、`replay` 及逐条结果；`FileData` 初始化日志。实现 D4 的读写与按条件版本号。
- Owner：`tests/test_channel_edit_log.py`（新增）——链式、先用后删、同名重建、D6 的每一种跳过原因、上游跳过向下游传播、`LazyZohFrame` 来源；`tests/test_project_io.py`——带日志往返、无日志时载荷与现在一致且版本为 4、有日志时版本为 5、旧文件缺键读成空列表、版本 6 被拒绝。
- 边界：`tests/test_signal_no_gui_import.py`、`tests/ui/test_import_boundaries.py`；按 `tests/test_batch_render_import_boundary.py` 的子进程写法补一条断言，确认导入这两个新模块不会把 `mf4_analyzer.ui` 带进 `sys.modules`。

### T3 编辑器接线

- 对话框改为经配方求值并维护有序暂存；抽屉信号加参数；`_apply_channel_edits` 改为调用回放 owner、写日志、标脏，并落实 D8。
- Owner：T0 的 `test_channel_editor_recipes.py` 原样通过；`tests/ui/test_channel_editor_expression.py`、`tests/ui/test_channel_expression_check.py`、`tests/ui/test_channel_editor_create_labels.py`；`tests/ui/test_dialogs.py` 与 `tests/ui/test_drawers.py` 的通道编辑节点；`tests/ui/test_main_window_smoke.py` 与 `tests/ui/test_view_channel_scope.py` 里调用 `_apply_channel_edits` 的节点；`tests/ui/test_project_dirty_guard.py` 新增「通道编辑后项目为脏」。
- 边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`。

### T4 保存与恢复接线

- `_assemble_project_document` 写出日志；`_restore_project_file_refs` 按 D5 回放；按 D6 接入健康报告、引用清理与确认文案；修正版本拒绝提示。
- Owner：`tests/ui/test_project_session.py`——§6 验收矩阵的每一行；`tests/ui/test_project_dirty_guard.py`——重开后不脏、摘要与磁盘一致；`tests/test_project_io_analysis_views.py` 的相关节点。
- 边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_import_boundaries.py`。

### T5 可见性与文档

- 通道树叶子的 tooltip（`ui/widgets/channel_tree.py` 的 `_channel_tip`）对编辑器派生通道追加一行配方摘要（如 `d/dt(speed)`、`tq_a + tq_b`、表达式原文），数据来自日志。只改 tooltip 文本，不动 delegate 几何。
- 同步 `ui/hints.py` 与 `ui/quickref.py` 的「通道编辑（派生通道）」分组；更正用户指南 FAQ Q1。
- Owner：`tests/ui/test_hints.py`、`tests/ui/test_quickref.py` 的相关节点；`tests/ui/test_file_navigator.py` 补一个派生通道 tooltip 节点。
- 纯文案部分不需要运行时测试之外的验证；tooltip 在真机上看一次实际显示。

### T6 集成与真机验收

- 集成（一次，顺序执行）：`tests/ui/test_project_session.py`、`tests/ui/test_project_dirty_guard.py`、`tests/test_project_io.py`、`tests/test_channel_edit_log.py`、`tests/signal/test_channel_recipe.py`、`tests/ui/test_channel_editor_recipes.py`，加 T1–T4 列出的边界护栏，最后 `git diff --check`。
- 真机（macOS 前台，Windows 另记）：用一份真实的 EPS 录制文件，创建电机转速的 `d/dt`、方向盘扭矩与电机扭矩的自定义表达式、一条链式派生；勾选绘图、放进一个 FFT View；保存、退出、重开，核对曲线、读数与分析来源。再把源文件换成缺一个输入通道的版本重开，核对提示与再次保存确认。
- 测一次打开耗时：对一份大文件记录「有 / 无配方」两种情况下的项目打开时间，写入执行记录。回放是同步的 numpy 计算；如果它成了打开耗时的主项，另行立项，不在本计划里临时加后台线程。
- 全量套件不属于本计划的常规门禁；仅在合并或发版验收时由一个协调者按仓库规则分两段顺序跑。

## 6. 验收矩阵

| 场景 | 必须观察到的结果 |
| --- | --- |
| 单通道派生 → 保存 → 重开 | 通道存在；名称、单位、数值与保存前一致；树内位置不变 |
| 派生通道被 View 勾选并设了颜色 / Y 范围 → 保存 → 重开 | 勾选、颜色、范围保持，曲线画出 |
| 派生通道作为 FFT / 阶次 / FRF 来源 → 保存 → 重开 | pane 来源保持；数值结果仍需显式点「计算」（既有规则） |
| 用派生通道再派生，然后删掉中间通道 → 保存 → 重开 | 最终通道存在且数值一致；中间通道不出现 |
| 删除一个加载器通道 → 保存 → 重开 | 该通道不出现 |
| 删除后用同名重新派生 → 保存 → 重开 | 该名字对应的是派生结果 |
| 创建后立即删除（无依赖） | 日志里没有这条；保存文件不含它 |
| 一个物理文件展开为多个逻辑来源，只编辑其中一个 | 配方只落在对应来源上 |
| BLF / ASC 惰性来源上的派生 | 回放成功，其他通道不被整体物化 |
| 源文件换成缺少输入通道的版本后重开 | 该条及其下游被跳过；提示「未能重建的派生通道」；引用它们的 View 项被清理并计数；再次保存先确认 |
| 源文件里新出现了与派生通道同名的列 | 派生被跳过并报告；不改名、不覆盖 |
| 表达式在新数据上失败或结果全部无效 | 跳过并报告原因 |
| 通道编辑后未保存就关闭 / 打开别的项目 | 离开保护弹出 |
| 重开一个无跳过的项目后直接关闭 | 不提示保存 |
| 没有任何通道编辑的项目保存 | 文件 `schema_version` 为 4，内容与改动前一致 |
| 含通道编辑的项目 | 文件 `schema_version` 为 5，不含样点数组 |
| 旧项目（没有 `channel_edits` 键）打开 | 行为与现在相同 |
| 版本高于 5 的项目 | 拒绝打开，提示里的版本号来自文件 |
| 不带配方的三参 `_apply_channel_edits` 加入的通道，保存时 | 给出「未随项目保存」警告并写日志 |

## 7. 风险与边界

- **源文件变了**：回放作用在重新加载的数据上，源文件更新后派生值跟着变。这是引用型项目的既有语义，与 View、分析来源一致；配方里不存数据指纹。
- **跨环境的逐位一致**：数值相等只对同一构建、同一平台成立。不同 numpy 版本或平台可能有末位差异，不作为持久化契约。
- **时间轴**：会话中目前没有交互式重建时间轴的入口，所以已物化的 `d/dt` / `∫dt` / 含 `t` 的表达式与配方一致。以后如果加入这类入口，必须同时重算依赖时间轴的派生通道，否则保存前看到的值与重开后的值会不同；这一点写进 `channel_edit_log.py` 的模块说明。
- **多逻辑来源的映射**：恢复按加载顺序把文件行对应到新 fid。源文件的拆分结果变化时，配方可能落到没有对应输入的来源上，表现为「输入通道不存在」的跳过——可见，不会算错。
- **悬空引用的更大范围**：健康报告目前不统计「fid 在、通道名不在」的引用。本计划只处理派生通道被跳过造成的那一部分；源文件自身少了通道的情况是既有缺口，另行处理。
- **批处理**：批处理从磁盘规划与加载，看不到会话里的派生通道，本计划不改变这一点。

## 8. 回退

各步可以独立回退。T1、T2 只新增模块与一个可选键；T3 之后如果回退，T0 的冻结用例保证对话框结果不变。已经写成 schema 5 的项目文件在回退后的构建里会被拒绝打开，所以 T4 合入后不应单独回退读取端。

## 9. 发版时要带上的事项

本计划不升版本号。下次发版时在 changelog 里写明：派生通道随项目保存；含通道编辑的项目需要本版本或更高版本才能打开。版本扇出面按仓库既有清单同步。

## 10. 本轮验证

实施后的聚焦门禁（offscreen Qt，`TMPDIR=/tmp`，仓库 `.venv`）覆盖：

- `tests/ui/test_project_session.py`、`tests/ui/test_project_dirty_guard.py`
- `tests/test_project_io.py`、`tests/test_project_io_analysis_views.py`
- `tests/test_channel_edit_log.py`、`tests/signal/test_channel_recipe.py`、`tests/signal/test_channel_math.py`
- `tests/ui/test_channel_editor_recipes.py` 以及通道编辑表达式、对话框、抽屉、导出、hints、quickref
- `_apply_channel_edits` 的 smoke / view-scope 节点
- 边界：`tests/test_signal_no_gui_import.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`

结果（`689edbc3`，`-X faulthandler`）：`472 passed`，随后解释器退出阶段段错误（`<no Python frame>`），退出码 139。同一份文件清单去掉本次新增的三个测试文件后在父提交 `a8844727` 上是 `440 passed`，同样以 139 退出，所以这个非零退出不是本次改动引入的；但按仓库门禁规则，这次运行不算干净通过。实施当时的那次合并运行是 `1 failed, 471 passed` 后 139 退出，失败用例修好后只重跑了两个节点。`tests/test_packaging_imports.py`、`tests/test_native_import_boundaries.py`、`tests/test_batch_render_import_boundary.py` 事后补跑为 `15 passed, 1 skipped`，退出码 0。

未跑全量套件。第 6 节的真机验收（真实 EPS 录制、打开耗时、macOS 前台、Windows 冻结包）没有在这台 Linux 云端环境执行。版本号未改；下次发版再补 changelog。
