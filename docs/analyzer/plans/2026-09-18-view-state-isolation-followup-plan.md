# View 状态隔离 Followup Plan

- 日期：2026-09-18
- 基线：`d75a5c11`，产品源码无本轮修改；现存无关未跟踪文件不纳入范围。
- 状态：DRAFT，待实施；本文件不表示产品修复或平台验收已经完成。
- 来源：同文件不同 View 无法独立共轴的排查及后续横向检查。
- 目标：同一文件在 A/B View 中具有独立、可保存和恢复的绘图意图；切换、复制、分屏、重开项目后保持一致。

## 1. 已知事实与范围

| ID | 事实与证据 | 本计划处理 |
|---|---|---|
| V01 | `ui/widgets/channel_tree.py:merge_axis_group` 将普通共轴写入会话 `_axis_groups`；`ui/view_bridge.py:capture_axis_opts` 仅捕获恢复映射。Qt 控件探针已验证 A 合并、恢复 B 后仍共轴，B 拆分后 A 无法恢复。 | 第一轮：普通与导入共轴统一进入 View 所有权。 |
| V02 | `ui/main_window/_project_io_mixin.py:_project_filter_payload` 保存项目级滤波；`window.py:_build_time_plot_data` 读取共享面板。 | 第一轮：时域滤波意图按 View 保存，面板仅投影当前目标。生产切换红测尚待补齐。 |
| V03 | `view_bridge.py:_capture_colors` 只保存已勾选颜色；`channel_tree.py:set_channel_colors` 合并旧值。Qt 控件探针已验证 A 未勾选通道的颜色快照为空，恢复后继承 B 的蓝色。 | 第一轮：保留本 View 的显式颜色覆盖，恢复缺省项不继承其他 View。 |
| V04 | `ui/dialogs/chart_options.py` 的标题、轴标签、scale、grid 等直接修改 handle；时域 View 快照没有完整对应字段。各项在重绘、切换中的具体表现尚未逐项实测。 | 第二轮：先生产路径复现，再补齐确认缺失的局部设置。 |

证据修正：图表选项普通通道改色已有 `PgTimeDomainCanvas._sync_pg_channel_color` → `channel_color_changed` → `_ViewMixin._on_canvas_channel_color_changed` 回写通路，不能认定所有改色只留在画布。应复用此通路，验证目标 View 与未勾选颜色隔离；派生滤波曲线等无普通通道身份的外观另行核查。

## 2. 状态归属合同

- `ViewState` 是时域用户意图的唯一持久所有者；Navigator、Inspector、canvas 都是投影。复用现有 bridge 和 View 应用事务，不另建跨 mixin 状态簇。
- 共轴使用现有 `axis_opts.channel_axis_groups` 与复合通道键。组 ID 是 View 内关系身份；保留 WWT opaque ID 与 record-only binding 的关系。单成员是否有效由实际绑定关系决定，不能统一按普通通道数量裁剪。
- 滤波采用 View 内结构化字段，包含 enabled、现有 `FilterSpec` 序列化值、show_original、show_filtered。禁用时仍保留该 View 参数；默认关闭。不得保存滤波结果、worker 或缓存，不更改 DSP。
- `colors` 保存本 View 显式通道颜色覆盖，取消勾选不删除；恢复时未覆盖通道回到稳定默认色，不读取上一个 View 的颜色。删除文件/通道按既有身份清理，单纯取消勾选不清理。
- 当前 `set_channel_colors` 同时承担增量改色。不得直接把其全部调用改成替换语义；为 View 完整投影明确区分“替换覆盖集”和“增量编辑”，核查所有消费者。
- 分屏写入对象由现有绑定的 `(view_id, state, canvas)` 确定；不能把 primary、active tab 和 focused pane 默认视为同一目标。后台重绘、UltraView 捕获不能借用当前聚焦面板的滤波值。
- 已有范围、备注、游标、Custom-X、附件、隐藏通道与 curve binding 状态沿用原所有者。

排除项：工作区文件/通道排序、全局游标统计项偏好、主题与窗口布局、文件原始数据/单位/采样率/通道定义、Batch 算法、分析参数模型重构、版本发布。独立子图排序属于另一个产品变更，不随本轮实施。

## 3. 第一轮：共轴、滤波与颜色

按顺序实施，共享合同与集成由同一执行者负责；本计划不要求多 agent。

### T0 — 补齐失败用例与消费者清单

- 在实际 ChannelTree + View bridge、MainWindow 切换路径建立 A/B 用例，不能仅使用赋值式 fake setter 证明隔离。
- 建立同文件同通道、跨文件同名通道、取消勾选/眼睛隐藏、新建/复制/关闭/重新打开 View 用例。
- 追踪滤波面板信号、`_plot_time_on_canvas`、绘图数据构建、项目装配/恢复、dirty digest、UltraView 缓存指纹；记录哪些路径隐式读取当前 UI。
- 重点核查 `ultraview_capture_coordinator.py:_filter_payload`：当前读取项目级 getter，迁移后应取所请求 View 的快照。
- 仅运行受影响的既有 focused baseline，不启动全量 suite。

### T1 — 共轴统一

- Owner：`view_state.py`、`view_bridge.py`、`widgets/channel_tree.py`，必要的调用整合在 `_view_mixin.py`。
- 普通 merge/split 更新当前 View 的关系投影；切换空 View 必须清除旧关系。捕获、复制与 JSON round-trip 使用同一份映射。
- 删除或退役会话共轴写路径，保留需要的公开接口；不能长期双写两份真值。
- 保留 WWT 导入组、普通与导入混合合并、拆分/恢复及 record-only 成员语义。
- Gate：`test_channel_axis_groups.py`、`test_view_state.py`、`test_view_bridge.py`、`test_subplot_shared_axis.py`、`test_view_switch_integration.py` 中相关用例。

### T2 — 时域滤波归属与旧项目迁移

- Owner：View 数据/bridge、现有滤波面板、`window.py`、`_view_mixin.py`、`_project_io_mixin.py`、`ui/project_io.py`；UltraView 仅修改现有捕获 owner 的取值/指纹路径。
- 捕获完整滤波意图；恢复控件时阻断编辑信号，随后由现有 View 恢复事务统一绘图，避免每个 setter 触发一次计算。
- 绘图和缓存指纹显式使用目标 View 的有效滤波配置；A 编辑不能使 B 的图像/预览换成 A 配置。原始/滤波显示开关仍复用现有轻量切换能力。
- 旧项目缺少 View 滤波字段时，从旧顶层 `filter` 为各旧时域 View 生成独立副本，保持原有共享设置的视觉含义；已有 View 字段优先。旧值缺失则采用关闭默认值，不能继承当前控件。
- 当前项目 codec 为 schema 3。由于旧应用无法正确表达不同 View 的滤波，实施时升级 codec 为 schema 4 并继续读取 1–3；新写入以 View 字段为准，旧顶层字段只作为兼容输入。同步受影响的 codec/文档契约，避免两份权威。
- 新建空 View 使用默认配置；复制 View 深复制意图；打开新项目与关闭全部对称清理。dirty digest、保存后 clean baseline 与重开项目须覆盖新字段。
- Gate：`test_time_filter_overlay.py`、`test_view_state.py`、`test_view_bridge.py`、`test_view_switch_integration.py`、`test_project_session.py`；补选现有 project codec 与 UltraView capture focused 用例，依据实际消费者清单执行。

### T3 — 颜色完整投影

- Owner：`widgets/channel_tree.py`、`view_bridge.py` 及 `_view_mixin.py` 现有改色回写。
- 分离增量编辑和完整 View 恢复语义；保留未勾选通道的显式颜色，不把所有工作区通道的临时颜色复制进每个 View。
- 普通图表选项改色复用现有信号，验证实际画布对应 View；同名跨文件通道不得串色。
- 无覆盖值时使用现有稳定默认色规则；旧项目已有颜色作为显式覆盖，无字段时不得借用上一个 View。
- Gate：`test_channel_widget_setters.py`、`test_channel_axis_groups.py`、`test_view_bridge.py`、`test_view_switch_integration.py`、`test_view_channel_scope.py` 及实际改色信号相关 owner 用例。

## 4. 第二轮：图表局部设置

第二轮以第一轮通过为前置；以下为候选范围，不把源码缺字段直接当作所有功能均已复现失败。

1. 用真实图表选项入口逐项检查：图标题、X/Y 标签、线性/对数、网格、图例、普通/派生曲线改色。覆盖原地重绘、A→B→A、分屏焦点、复制、项目保存/重开；记录现有可用回写，删除不成立的缺陷项。
2. 对确认需持久化的时域项，设计 View 内局部外观覆盖。普通通道用复合身份，共轴用组身份，record-only 用已有 binding 身份；不能按子图序号或展示名称键控。定义合并、拆分、通道删除后的覆盖继承规则后再写实现。
3. Inspector Custom-X 标签与图表选项 X 标签不得产生双重真值：时间 View 的 X 语义由现有 CustomXAxisSpec 管理；局部 Y 标签/图标题才作为外观覆盖。范围继续由既有 xlim/ylims 管理，不复制第二套范围。
4. 对数模式必须与实际数据变换、range 恢复、ticks 和游标数值一致；顺序为数据/坐标模式建立后恢复范围，再走既有 settle。仅恢复文字或 checkbox 不算完成。
5. 分析画布的色图、色阶、参数和视口另有 AnalysisViewState/PaneState 所有者。本轮只核查边界并报告缺口，不把分析参数塞入时域 View；若需修改分析产品行为，另写有 owner 的任务后实施。

Owner：`dialogs/chart_options.py`、`_axis_handle.py`、`pg_canvas` 实际 owning collaborator、View bridge/状态及调用协调。Facade 不新增实现。Gate：`test_dialogs.py`、`test_axis_handle.py`、`test_view_bridge.py`、`test_view_switch_integration.py`，以及按实际涉及项选择的 canvas owner 测试。

## 5. 集成与验收

每轮完成后逐项打勾；不得用另一类证据代替。

- [ ] A/B 同文件：共轴关系、滤波配置、颜色按目标 View 恢复；B 编辑后 A 重绘结果不变。
- [ ] 分屏：交替聚焦两侧编辑，左右图、控件、保存目标一致；非聚焦画布重绘不读取聚焦 View 设置。
- [ ] 新建为空默认，复制后互不影响；取消勾选再选、隐藏再显示保留应保留的意图。
- [ ] WWT/record-only 共轴关系不退化，同名跨文件身份独立。
- [ ] 旧项目迁移、新项目 round-trip、save→clean→edit→dirty→save→reopen 正确。
- [ ] UltraView 目标指纹包含相关 View 意图；已缓存和冷重绘结果一致，另一 View 编辑不污染目标内容。
- [ ] 第一轮真实 offscreen 渲染比较共轴布局、滤波曲线与颜色；第二轮逐项比较外观与实际轴值。
- [ ] 真实 macOS Cocoa 前台执行 A/B、分屏、图表选项和重开项目流程，记录截图/几何及数值证据。
- [ ] Windows source 检查与 Windows Full/Lite frozen/DPI 前台验收单独记录；未执行则标为 UNVERIFIED。

先 owner focused tests，再按改动运行边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；改动 pg_canvas collaborator 时加 `test_pg_canvas_backref_invariants.py`，改变依赖时加对应 import boundary，改变 QSS 时加 border shorthand gate。不因 UI 文件改动运行整个 tests/ui。

默认测试入口：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本任务选择的测试> -q`。Qt 探针隔离 QSettings；证据放 `.state/`。

本 followup 不要求全量 suite；若后续合并/发布要求全量，由集成执行者对稳定快照执行一次，先查运行中的 pytest，主 suite 与 acquisition_ui 使用两个顺序进程，记录前后 HEAD/dirty 范围。

## 6. 文档与完成定义

- 用户可见语义变化同步 `ui/hints.py`、`ui/quickref.py` 和相关帮助说明，明确共轴/滤波/颜色作用于当前 View；不新增未实现操作说明。
- 每轮记录实际变更、focused gate、渲染证据、平台未验收项；第二轮未做不能将整份计划标为 IMPLEMENTED。
- 本次仅交付计划：核对路径/符号、范围、证据等级与 `git diff --check` 即可，不运行产品测试。实施阶段先补失败用例再修复；按 lessons gate 判断是否需要沉淀复发模式。
