# Pin / View 结构治理 · 设计

- 日期：2026-09-19。状态：**设计提案；未实施，未做运行时验收**。
- 结论：**有必要，但不是按行数大拆，也不能原样执行旧 T9 的五类清单。** 分为职责拆分、画布外观 API 收口、事件去重三个可独立验收的包。
- 基线 HEAD：`c75c47e3cba6e41fd5208affaa966f972336b434`，非干净树。检查时 controller/overlay/state 与 Pin 测试已有他人未提交修改。本文代码事实来自该工作树，不能当作 HEAD 的已提交行为。
- 实施计划：[对应 plan](../plans/2026-09-19-pin-view-structure-governance-implementation.md)。来源：[加固计划 T9](../plans/2026-09-19-view-isolation-and-pinned-cursor-hardening-plan.md)。
- 产品交互优先级：[底部 Pin 与闪退计划](../plans/2026-09-19-pin-bottom-handles-and-crash-fix-plan.md) 高于旧自动弹出/标签置顶方案。结构治理不得改回旧交互。
- 参考 2026-08-04 的 [机械拆分设计](2026-08-04-ui-mechanical-splits-design.md) 与 [状态所有权设计](2026-08-04-main-window-state-ownership-design.md)：继承兼容面清查、先冻结行为、显式依赖、单一状态归属；不继承历史的每任务全 UI suite、自动提交或回滚要求。

## 1. 复核结果：什么仍有必要

以下是源码证据，不是新测得的性能数字；行号会随正在推进的 Pin 改动变化，执行以符号重定位。

| 优先级 / 项 | 当前证据 | 判断与影响 |
| --- | --- | --- |
| P2 · 控制器职责混合 | `pinned_cursor_controller.py:123` 的 `_OwnerState` 同时放 collection、samples、pills、axis_labels、timer、连接；`:431` 路由、`:499` 捕获、`:856` 求值、`:986` 投影、`:1293` 清理同属一个类 | 改输入会触及投影与销毁，单测常需完整 ChartStack；底部拖动再叠加后回归面更大。值得按状态和副作用边界拆，不设行数 KPI |
| P2 · 外观逻辑越界 | `_view_mixin.py:219`、`:300`、`:393`、`:401`、`:439`、`:493`、`:526` 读取 `_companion_source/_channel_lines/_channel_data_id/_x_master_handle/_overlay_mode/_primary_xaxis_ax/_inside_label_*` | MainWindow 既解释用户意图又解释画布内部结构；画布结构变化会牵动 View 保存/恢复。应由画布公开外观能力承接 |
| P2 · 身份恢复仍依赖显示值 | `_resolve_companion_source_key` 末尾用显示前缀猜源；`_appearance_key_for_handle` 用 binding_id 或 display_name 匹配 | 不能把猜测原封不动包装成“公开 API 就安全”。精确身份链需要单独用例；同名歧义是风险，本文未重现一个新的产品错配事故 |
| P3 · 重复样式刷新 | `stack.py:2395` 的 structured update 调 `set_pin_role` 和 `set_live_hint`；`cursor_pill.py:548–584` 两者都进入 `_sync_pin_chrome`，无条件 unpolish/polish | 普通一次更新会走两次样式刷新，即使角色/提示没变。调用链确定，实际耗时/帧率收益 UNKNOWN |
| P3 · resize 重排无合并 | `stack.py:2762` resize / splitter → `_reposition_pill` → controller `reflow_visible:398`；后者不使用 `_sync_pill_safe_rect` 的 changed 返回，每张已有 projection 都 reflow | 对 N 个面板重复 QTextDocument 排版；值得合并与按变化跳过，但必须保证最终几何、捕获和销毁时序 |

### 1.1 旧建议必须修正

1. **不建 PinUndoStack。** 旧文同一份计划 D2 已删除撤销关闭；当前类只有 `unpin_record/close_record`，旧分节注释仍写 undo 不代表存在该功能。取消固定保留编号不是撤销栈。
2. **PinSampleEvaluator 不整体 Qt-free。** `_evaluate*` 调画布采样接口；`_axis_compatible/_canvas_generations/_bound_identity_keys` 读取 Qt host 状态。只有显式参数驱动的 reconcile、identity、status 派生能进入中立模块。
3. **F-V2-5 不能按“仍然只取首个 fid”重报。** 当前代码已检查 fid + binding_id/display，且 `test_view_appearance_isolation.py:451` 有同 fid 两个不同显示名的回归用例。此处保留修复，补同名/绑定身份边界；不把历史测试状态当当前通过证据。
4. hover 问题目前的直接 owner 是 `CursorPill._sync_pin_chrome`，不是把 `stack.py` 两行 QSS 删掉即可。resize 的数据重算合并 timer 也不能冒充几何排版合并。
5. 本文不是 flash/crash 修复替代品。工作树已有 `viewport.mapFrom(canvas, ...)` 修正，但其验收归底部 Pin 计划；不能因看到 patch 就宣布闪退已解决。

### 1.2 执行先后

先完成正在进行的底部 Pin/原生崩溃修复并形成稳定验收快照，再对同一基线做结构治理。不得两份计划同时修改 controller/overlay/state。若产品计划未做完，本计划可评审，但不开始搬迁；不把结构重构变成紧急修复的前置。

## 2. 目标、非目标与成功尺度

目标：持久化写入和通知只有一个出口；原始输入、求值、控件生命周期有明确 owner；View 外观不窥探画布私有属性；不变的 chrome/几何不重复做昂贵工作。

不做：撤销关闭、全局新快捷键、DSP/采样算法、FFT 吸附/FRF 相位语义改变、MainWindow 全面拆分、通用插件/消息总线、版本或工程 schema 升级、批处理架构调整、无关异常清理。

纯搬迁部分要求产品行为、持久化 payload、信号次数/顺序、capture 内容保持。身份歧义去除与事件合并属于**明确的行为边界优化**，单独先红后绿，不能以“机械搬迁”掩盖。

## 3. 包 A：协调器 + 四个协作者

### 3.1 目标分工（拟新增名称，非当前接口）

| 单元 / 文件 | 拥有什么 | 不得做什么 |
| --- | --- | --- |
| 保留 `chart_stack/pinned_cursor_controller.py` / `PinnedCursorController` | 公共兼容入口、owner 绑定表、已提交 collection/facts/availability、revision、canvas 连接与数据重投影 timer；单一提交/意图通知 | 不再实现 QTextDocument/卡片/标签布局；不实现原始 Qt 键鼠过滤细节 |
| `chart_stack/pinning/key_router.py` / `PinKeyRouter` | 唯一 app filter 的安装/卸载、P 仲裁、上下文排除、指针命中；返回只读命中结果 | 不 bind canvas、不铸 scope、不直接改 collection、不采样或建面板 |
| `chart_stack/pinning/commands.py` / `PinCommands` | 新建/去重/unpin/close/展开/微调请求；已落地拖动事务的开始/预览/提交/取消临时状态 | 不直接写持久集合、不发第二次 intent_changed、不持有另一套 samples/pills |
| `chart_stack/pinning/sampling.py` / `PinSampleEvaluator` | GUI 线程上的 canvas facts 适配、坐标域/代际读取、已有采样接口调用；无长期缓存 | 不做插值/FFT 重算、不操作 QWidget、不格式化 HTML；不能声称整个模块 Qt-free |
| `chart_stack/pinning/presentation.py` / `PinPanelProjector` | 每 owner 的 pills/labels、投影/高亮/anchor 应用、布局 timer 与布局指纹、控件连接和销毁 | 不改持久化 intent；用户动作向协调者发命令；不采样；不拥有 canvas overlay 的图元生命周期 |

纯函数放 `ui/pinned_cursor_facts.py`：从 `_reconcile_sample/_binding_key/_key_in/_identity_key/_hidden_channel_row/_sample_has_*` 中迁移真正无 GUI 的部分；使用现有 `pinned_cursor_state` 与 `cursor_display_model` DTO。它不是第六个有状态服务。`pinning/__init__.py` 保持轻量，不借包导入把画布全部拉进中立层。

```
Qt 输入 → KeyRouter / Pn 控件 → Controller → Commands
                                  │           │ 返回命令结果
                                  ├─ Sampling → 中立 facts 规则
                                  ├─ 唯一提交与 revision/通知
                                  └─ Projector → pill/label + 既有 canvas overlay
```

### 3.2 数据和生命周期合同

- owner binding key 继续校验真实 canvas 身份；异步目标带 scope/binding generation，不只用 `id(canvas)`。不为拆分另造一套 UUID。
- collection 仍由 View/Pane bridge 保存恢复，运行时绑定副本由 controller 管理；协作者只读快照或返回结果。禁止把同一可变 `_OwnerState` 整个交给四方任意写。
- controller 保留 reserved intent/ordinal、live suppression 的唯一状态；Commands 通过命令结果请求更新。Projector 独占控件表；其只读查询供现有捕获入口使用。
- `commit_user_change`（拟接口）是唯一运行时用户提交出口；preview/cancel/reproject/install 不误发通知。保留已验收的先后顺序，不在搬迁时擅自把反馈、live 交接、采样、投影重新排序。
- hide/unbind/clear/session replace/close：先使 token 失效、取消手势与待处理 timer，再断连接、清 overlay 回调和控件；QObject parent 明确。clear 与 unbind 保持原来“是否仍绑定画布”的区别。
- Router 可作为 controller 的 QObject 子对象；全局 filter 只装一个。不要同时让 façade 和 Router 各装一份。pill 的 Enter/Leave/Focus 局部处理交给 Projector，不加入全局 MouseMove。
- Projector 没有权力将空间不足改写为用户收起。`panel_expanded`、full/mini、暂不可绘制三维仍按产品计划独立。

### 3.3 依赖与兼容面

- 不把整个 MainWindow/controller/ChartStack 传给新协作者让其随便访问私有方法。使用最小显式依赖/窄 Protocol：取当前模式和安全区、live snapshot/交接、只读 facts、提交 callback；生产适配集中在现有 owner。不要构建可配置服务容器。
- Sampling 的 Qt 适配可以持有当前 canvas，但不得反向 import controller/stack/MainWindow。中立 facts 不 import `plot_helpers` 若会传递引入 Qt；其身份解析若需迁移，迁走原 helper 并留显式兼容出口，不能复制计算。
- `PinnedCursorController`、状态常量、`pin_feedback_level` 保留原 import 路径；ChartStack 公共 pin 方法、bridge、UltraView/capture、反馈信号签名不变。
- 当前测试直接写 `_last_mouse_global`，conftest 按 controller 类型与 `_application_filter_installed` 计数。保留转发 property / 显式诊断查询，**使哨兵仍能看到 Router 的真实安装状态**；不得出现“controller 标志 False，Router 泄漏但测试绿”。
- Task 0 清查 private test seams、monkeypatch globals 和内部静态自引用。纯 re-export 不保证晚绑定 patch 生效；对确需改测试目标的项逐条记录新旧语义。产品接口不迁移；实现细节测试可转向新 owner，但必须保留原行为断言。
- HTML/坐标文本格式化移到现有 `chart_stack/cursor_display.py`，仍保持来源身份与显示名分离、现有 full/mini 与通道颜色。不要再造 renderer。

## 4. 包 B：画布外观公开边界与精确身份

### 4.1 两层职责不能混合

MainWindow 保留“哪一个 View、哪个 intent 字段、何时 dirty、是否更新共享 Inspector”；canvas 负责“这个 handle/curve 对应哪个稳定目标、怎么作用于轴与内部标签”。公开 API 不接受 MainWindow、ViewState 或 files；不返回 `_ChannelKeyDict`/可变内部映射。

拟公开面由 `TimeDomainCanvasPG` 薄委托，实现在 `pg_canvas/appearance.py` 协作者。目标/快照 DTO 放 Qt-free 的 `ui/chart_appearance_model.py`，不用当前 handle/display label 当持久化键：

| 拟能力 | 输入 → 输出 / 副作用 |
| --- | --- |
| `appearance_target_for_handle(handle)` | 返回 group/channel/binding 的明确身份或 unavailable；优先级与现有共轴语义一致 |
| `companion_source_key(curve_key)` | 当前复合 curve key → 原始 `(fid, channel)`，来自绑定映射而非显示前缀 |
| `snapshot_chart_appearance(handle)` | 同时提供 target、实际共享 X scale、该轴 title/y label/y scale/grid/xlabel 与 owns_xlabel；只读 |
| `apply_chart_appearance(resolved_specs)` | 对明确 target 施加已有 setter 语义、内部标签显隐及范围修复；不触发用户修改信号 |
| `repair_chart_appearance_ranges(resolved_specs)` | View restore 最终范围阶段使用；不得暗中重复 settle/改变 ink quiet window |

以上为设计接口，可按既有返回类型微调名称，不得退化为 `get_private_attr(name)`。共享 `appearance_group/channel/binding_key` 编码继续复用现有 codec helper，UI-neutral DTO 不反向依赖 Qt。

### 4.2 身份传递是必要的小范围前置

当前 `time_curve_bindings.py:770` 只给 row meta 写 axis_group，record-only 行名可为 display_name；`canvas.py:889` 解析行时没有保留稳定 appearance binding 身份。因此**仅移动 `_appearance_key_for_handle` 不足以兑现精确匹配**。

- 在已有第八项 row metadata 中传递可选稳定 appearance reference：普通通道原始 `(fid, channel)`、record-only 的 `binding_id`、伴随曲线的精确源引用。不改变前七项、不改 X/Y 数组、顺序或数值算法。
- 沿实际生产 row builder（包括普通/滤波路径和 `resolve_time_curve_bindings`）到 canvas bind 边界传递。重建与 `try_apply_selection_delta/_selection_rows` 都同步该映射，不能只有冷绘制正确；映射在 `chart_rebuilt` 消费前就绪。
- 映射随画布 bind/clear/删除同步，不保存到工程、不做 MainWindow 镜像缓存；新状态由 appearance 协作者初始化和 reset，并纳入 `_owned_names`。
- 对旧 6/7 项行保持能绘图。能唯一证实身份才允许持久化外观；不能证实则返回 unavailable 并走已有可观测诊断，不猜第一个 fid/显示前缀。不因单条外观身份缺失禁用整张图。
- 现有 recolor 信号若只带 data_id/name，先在画布侧唯一解析；重名无法唯一解析时必须从真实 line 命中处传递精确引用（可新增有名 typed signal，同时保留旧兼容信号）。MainWindow 只连接一种写入路径，避免同次动作写两次；不通过随便挑一个匹配凑结果。
- 同 fid + 同 display 的两个 record-only binding 若现有 curve storage 已在绘制前合并，则记录为独立身份建模阻塞；不得偷偷重构全画布 key schema。该案例的最低安全合同是“不可误写另一个目标”；是否扩展为完整同名绘制支持需另行范围决策。

### 4.3 迁移门槛

先做公开 façade + parity，再迁移 `_view_mixin` 七个外观方法；歧义行为变更用独立红测。最后该外观调用链不得再读上述私有字段或基于显示前缀猜源。其他 `_view_mixin` 功能不扩大整改。

同 fid 不同 binding、同名不同 fid、共轴优先级、隐藏原始只留 companion、无数据/旧行、secondary 非聚焦改色、保存重开、增量与冷重建等价必须覆盖。未知/歧义不能以空 key 静默冒充成功。

## 5. 包 C：chrome 幂等与几何事件合并

### 5.1 Chrome 更新只依赖变化

`CursorPill` 内拆清“角色样式”和“提示文本/按钮几何”。相同 role/hint 不重复 setProperty、polish 或文本写入；角色真实变化才做必要的 style 刷新。样式/字体/DPR 变化仍能正确重建，不用永久缓存挡掉主题更新。

验收按**调用次数和渲染结果**：首次设角色后，100 次相同 structured update 额外 role polish 为 0；hint 改文字不重刷无关 pin 样式；live↔pinned、full↔mini、隐藏/重显后动作角落和 tooltip 一致。不承诺未经测量的提速百分比。

### 5.2 几何合并不合并数据采样

- resize/splitter 多次请求，由 Projector 的单个 QObject-owned single-shot timer 合并为下一事件轮的最终安全区更新。首轮可用 0ms，不宣称它等于显示器一帧；若多轮事件仍过量，先测量再提出节流窗口。
- controller 现有数据重采样 timer 和 canvas overlay 现有几何合并各有职责，不把三者串成互相触发的重排环。geometry-only 路径不能重新 `_evaluate_intent`。
- 以实际 safe size、内容/投影 revision、full/mini、字体/DPR/样式 revision 判断是否需要 QTextDocument 重排。仅 safe origin 改变可重新定位/引线，但不重复排字；内容变化也不能因同样宽高而被漏掉。
- 用户收起的卡不重排；awaiting_space 的已请求展开卡在空间恢复时需重试。保留完整行和真实 painted document 的几何合同。
- 减小窗口时可立即隐藏或约束旧越界卡；下一事件轮完成最终排版，不能用粗缩放文字冒充可读。
- 建立 `flush_layout(owner)` 稳定出口给复制/合图/UltraView：消费最终 geometry，取消重复 pending，同一 generation 只布局一次，不采样、不 dirty。拖动预览期间捕获仍服从产品计划的延后合同。
- flush/layout callback 防重入：本轮只处理一次，期间新请求留下一轮；hide/close/session replace 取消旧 token 和 timer，不能迟到回调复活旧卡。

## 6. 必须维持的系统合同

- 复合身份、scope/record ID/编号、旧工程兼容、非勾选状态不删意图、未知 fid 丢弃及反馈不变。
- P 路由继续支持树焦点，不抢文本输入/模态/UltraView/FFT preview；不换 QShortcut。
- 默认收起、独立多开、拖动候选→一次提交/取消、full/mini、截图无多余栏均以底部 Pin 计划验收快照为准。
- `_CanvasBackref` 声明、MainWindow 状态所有权、import/lambda/QSS 棘轮不放宽。中立 facts/DTO 的子进程 Qt 投毒必须通过。
- 新协作者必须能由轻量 fake ports 独立测试；外部 façade 仍有真实 ChartStack 集成测试，不能全换成 mock 后失去接线覆盖。

## 7. 验收与证据状态

完成标准不是五个文件，而是：唯一集合写入/通知出口、无双 filter、Projector 独占控件及布局 timer、纯规则无 Qt、外观链私有读归零、稳定身份不猜测、相同输入无多余 chrome/reflow、最终捕获与像素等价。

本次只做源码/历史文档/调用点检查；没有运行 Qt、Cocoa 性能或 Windows frozen。实施时 focused → boundary → 稳定集成顺序及具体测试见 plan。性能数据需相同数据/窗口/Pin 数的前后台区分记录；offscreen 调用次数不是 Cocoa 帧耗时。

基线辅助 blob（`git hash-object`，仅表示检查时文件内容）：

| 文件 | blob |
| --- | --- |
| `pinned_cursor_controller.py` | `fee155fbc074f6036f5cff04240f7ff627a0f2a9` |
| `_view_mixin.py` | `908c942eaf2c85da022c71240873877a2296913d` |
| `stack.py` | `4fed197fa62ac27389e5715a23196554b60e95ab` |
| `cursor_pill.py` | `8e843466f40283e98739ab5aa2579b41874b936d` |

执行前重新记录完整 HEAD、dirty 与相关文件 hash；这些旧 hash 不是后续实现验收快照。

收尾复查发现并行进行的产品工作已继续修改 controller（blob `fb8e5672a1682cb52fc9754ccbb2a00b9e1492c3`）和 pill（`4297fa1d37e5ec25b4f4336dad8a2b395eeaa4bf`），新增独立展开逻辑及鼠标事件处理；本任务未触碰这些文件。此时 `_sync_pin_chrome` 仍无条件 polish，`reflow_visible` 已跳过用户收起卡，但对展开卡仍无条件 reflow，结构混合仍在。上述定位表和首轮 blob 保留为检查时证据，不能声称整轮对稳定工作树完成了运行时审查；计划 T0 必须重验最终产品快照。
