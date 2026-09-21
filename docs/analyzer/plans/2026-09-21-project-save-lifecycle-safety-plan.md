# 项目保存与会话生命周期安全优化计划

- 日期：2026-09-21。
- 状态：**计划已编写，待实施；不是产品修复或原生 UI 验收报告。**
- 源码基线：`5d7868f1961f580263e7ae4ef85a994bfeab6edb`。实施前重新检查 HEAD 和相关 dirty 范围。
- 授权范围：本轮只写计划，不修改项目保存行为。此前 Lite 日志脚本、测试和 lesson 的未提交修改不属于本计划。
- 问题：用户清空全部文件后认为已开始新任务，但原项目保存路径仍有效；导入另一组数据后点击保存，会覆盖原项目。
- 推荐路线：**明确项目关闭／新建事务，先保护旧内容再清空，完成后解除保存路径绑定；显示当前保存归属。** 不采用“变化百分比”作为主保护机制。

## 1. 成功标准与范围

第一阶段交付必须满足：

1. 通过产品“关闭项目／新建项目”离开 A 后，加载 B 的数据并按保存，只能先进入另存为；未经用户选取目标，不写 A。
2. 任何关闭／新建确认都发生在文件、View、分析来源、UltraView 被清理之前。选择保存时保存的是清理前的完整会话。
3. 取消确认、取消另存为、保存失败，均保留旧会话及其保存绑定；确认取消不提前清理缓存、Board 或分析任务。
4. 没有数据文件的已绑定项目仍可以关闭；用户明确选择保留空项目后，保存与另存为仍可用。
5. 正常编辑同一项目时保存仍直接写当前项目，不为每次保存增加弹窗。
6. 项目打开、缺失来源恢复、物理文件的多逻辑来源、分析恢复队列、UltraView 和程序内部清理不被误当成用户“关闭项目”。

第一阶段包括生命周期入口、最后来源移除分支、状态解绑、保存归属显示、帮助和回归验证。第二阶段单独交付覆盖前备份／恢复；见第 8 节，不能用“已有原子写入”冒充历史恢复。

本计划不改 DSP、数据导入格式、采集生命周期、Batch 计算、项目文件 schema，不增加自动保存，不引入多窗口项目管理，不做 MainWindow 广泛拆分。不实施“文件变化超过百分之多少”提示，也不把文件打开默认改成替换：数据文件仍追加，`.tlproj` 仍走项目替换。

## 2. 当前事实与实现风险

下列路径相对仓库根；行号以基线为准，实施时按符号重新定位。

| 已读源码 | 当前事实 | 实施要求 |
| --- | --- | --- |
| `mf4_analyzer/ui/main_window/_project_io_mixin.py:532`，`save_project_via_dialog` | `_project_path` 非空即保存原路径 | 生命周期完成后必须解除绑定；不能仅修改提示文案 |
| 同文件 `:2588`，`close_all` | 清来源、分析缓存、Board，但不清保存路径；无文件时提前返回 | 保留内部卸载语义；新增产品级关闭事务，覆盖“已经为空”的情况 |
| 同文件 `:1952`，`_reset_empty_workspace_session` | 重置 View、范围、滤波、游标；有恢复 guard；部分被 Board 引用的 View ID 会保留 | 此处不能无条件绑定“结束项目”，不能破坏内部恢复与显式保留空项目 |
| 同文件 `:2385`，`_open_project_restoring` | 在 `_restoring_project` 内调用 `close_all(force=True)` | 内部清理不得弹关闭提示，也不得重置恢复 guard 的深度 |
| 同文件 `:235`，`confirm_leave_unsaved_project` | 已有 Save／Discard／Cancel 与保存失败转取消逻辑 | 复用保存和离开结果；按操作上下文提供文案，不再造第二套 dirty 算法 |
| `mf4_analyzer/ui/main_window/project_dirty.py` | holder 有 `path`、`saved_digest`、revision、guard；已有 `clear()` | 解绑两个现有路径表示，并清理保存基线；避免只清 `_project_path` 后 digest 又用 holder.path |
| `mf4_analyzer/ui/main_window/window.py:2987`，`_close_files` | 物理文件组先聚合依赖，再逐 logical fid 关闭 | 最后来源判定在整组预检完成后、任何移除前进行；整组只确认一次 |
| 同文件 `:3048`，`_on_close_all_requested` | 导航入口直接调用 `close_all()` | 改路由到产品级项目关闭，不在 navigator 存项目状态 |
| `mf4_analyzer/ui/file_navigator.py:1152` | 菜单为“全部关闭…”，仅有 rows 时启用 | 改成明确项目命令；空项目也要有可达关闭入口 |
| `mf4_analyzer/ui/toolbar.py:741`，`set_enabled_for_mode` | 保存控件只按 `has_file` 启用 | 保存能力必须与项目绑定／可持久化内容一致；QAction 和按钮使用同一判定 |
| `mf4_analyzer/ui/command_registry.py`、`main_window/command_coordinator.py` | 已有全局命令元数据和 QAction owner，无新建／关闭项目命令 | 在这套入口扩展，保留单一 QAction；不另写快捷键路由 |
| `tests/ui/test_open_and_save_entry.py` | 明确不创建顶层 QMenuBar | 沿用紧凑工具栏的下拉入口，不新增传统菜单栏 |
| `mf4_analyzer/ui/project_io.py:304`，`_write_text_atomic` | 临时文件 fsync 后原子 replace，没有历史备份 | 保留原子写入；其作用是防半写，不是防误覆盖 |
| `mf4_analyzer/ui/chart_stack/ultraview/preview_sidecar.py` | 成功写 sidecar 后会清理旧 generation | 第二阶段必须在副文件被替换／清理前取得旧快照；单独备份 JSON 不够 |

## 3. 确定的交互方案

### 3.1 项目命令与界面入口

- 保存主按钮保持“保存”，原箭头改为“项目操作”，下拉提供“另存为…”、“新建项目…”、“关闭项目…”，用分隔线区分保存和离开操作。
- “新建项目…”的说明为“结束当前项目，开始新的分析”；“关闭项目…”结束当前会话后保持应用窗口打开。两者共享关闭事务，最终均是未命名的空工作区；新建可将焦点交给既有打开入口，不自动弹文件选择窗口。
- 导航原“全部关闭…”改为“关闭项目…”，明确同时清除当前项目的 View、分析与 Board；该命令不再暗示只是移除文件。
- 下拉和导航复用同一个命令及 enabled 状态。绑定项目即使零文件也能关闭；全新、无可持久化内容的空工作区关闭为禁用，新建为幂等操作。
- 项目下拉必须独立于保存主按钮启用：即使保存被禁用，箭头仍可展开并使用新建。不得继续整体禁用 `_save_split`，否则空工作区会失去项目入口。
- 第一阶段不为新建／关闭增加默认快捷键，避免占用现有图表／View 键位；保留保存／另存为既有平台快捷键。未来增加时必须经 command registry 和冲突检查。

### 3.2 明确关闭／新建时的确认

已保存且无修改：直接完成关闭；用户已点击明确命名的关闭命令，不重复要求确认。

有未保存修改（包括未命名会话）：显示项目名和操作后果，提供：

- **保存并关闭**：先调用统一保存入口；首次保存进入另存为。只有成功才能清理。
- **不保存并关闭**：保留磁盘原文件，丢弃当前内存修改，再关闭。
- **取消**：保持当前会话。

取消为默认／Esc／关闭对话框的结果。对“新建项目…”可显示“保存并新建／不保存并新建／取消”，结果仍映射到相同的离开协议。

一个离开动作只有一个 dirty 确认。实际执行清理时不再弹“来源仍被 View 引用”的第二个确认；第一次对话框已经说明将结束整个项目。取消另存为、恢复不完整警告中的取消、权限／磁盘写入错误都终止关闭，并给出原有可操作错误反馈。

### 3.3 移除最后一个数据来源

“移除项目内文件”仍是独立动作。对于整次请求会让 logical source 集合变空的操作，在任何移除之前统一询问：

| 清理前状态 | 按钮 |
| --- | --- |
| 已绑定且无未保存修改 | 关闭项目／仅移除文件，保留项目／取消 |
| 存在未保存内容 | 保存并关闭项目／不保存并关闭项目／仅移除文件，保留项目／取消 |
| 未命名、无需要保护的内容 | 沿用一次文件依赖确认；移除后仍为未命名工作区 |

- 对话框同时说明受影响的 View／分析来源，替代原依赖确认；不能先弹依赖确认、再弹最后来源确认、最后又弹 dirty 确认。
- 所有最后来源对话框均以取消为默认，Esc／关闭对话框也取消，不把关闭项目作为默认回车动作。
- “保留项目”明确说明：已绑定时后续保存仍写当前项目，未命名时仍需首次另存为。此分支只做原有文件移除和来源失效处理，不清项目绑定、不清 saved digest；移除应成为一次可检测的持久化修改。
- “保留项目”不承诺保留旧数值结果或全部布局：既有来源清理与空工作区 reset 合同继续生效；UltraView 对失效引用的语义沿用原移除路径。
- 关闭项目分支调用同一产品事务并传递已完成的确认结果，不能再次询问保存。只有已确认该次请求的内部调用才能跳过确认。
- 按整组唯一 fid 集合与当前文件集合判断“最后一组”；不用卡片数、文件名或 `len(files) == 1` 判断。一物理 HDF 对应多个 logical source 时同样只确认一次。
- 程序恢复过程中短暂出现零来源，不触发该流程。删除最后一个通道、取消勾选全部通道、关闭最后一个 View，也不等于关闭项目。

### 3.4 保存归属与可用性

- 工具栏保存区旁提供紧凑项目名，长名省略、hover 展示完整路径；未绑定显示“未命名项目”。窗口标题也带项目名，保留 `app_meta.WINDOW_TITLE` 的品牌／版本来源。
- 星号只反映可持久化修改。使用现有 dirty holder 的事件与对账，不能在 paint、hover、每帧相机变化时组装完整项目／计算 digest。
- 保存 tooltip 显示当前目标，或“首次保存请选择项目位置”；另存为成功才切换归属，取消／失败保持原归属。
- 绑定项目，即便零来源也允许保存；未命名但有 Board、非默认 View 或其他可持久化内容也允许保存；全新默认空工作区可禁用保存。
- 保存可用性由项目 owner 的统一能力投影提供给 QAction、toolbar；不要在控件里各自检查 `has_file`，也不要从标签文字反推路径。
- “另存为”若选择已有文件，保留明确覆盖确认。关闭 A 后首次保存默认建议新名称，不预填 A 为待覆盖目标；仍允许用户明确选择已有 A 并确认覆盖。

## 4. 状态模型与事务顺序

状态名称用于说明与测试，不要求额外持久化枚举：未命名空工作区、未命名有内容、绑定项目（clean／dirty，允许零来源）、内部恢复中。dirty、文件数量、项目绑定是三个不同维度。

成功关闭的顺序：

1. 产品入口做只读预检：目标 fid 集合、项目绑定、未保存内容、当前恢复／关闭 guard。
2. 完成必要的保存／放弃／取消决策。保存读取清理前全部内容；取消到此返回。
3. 提交会话结束：先让旧会话的延迟回调和分析恢复工作失效，再通过各 owner 清理来源、View／pane、缓存、范围、游标、图形和 Board。
4. 明确重置 UltraView project state，包括零来源但 Board 仍有内容的情况；不能依赖 `close_all()` 的非空分支恰好执行。
5. 在产品级事务内解除 `_project_path`，清空 `ProjectDirtyState` 的 path／digest／revision，并恢复 clean 基线；同一事务清理 restore-health。只在适用的非恢复边界使用 holder.clear，不能在内部 begin_restore/end_restore 中清掉深度。
6. 最后投影未命名状态、动作可用性和默认空视图。新导入的数据不能继承旧的保存路径、pending restore 或 Board 回调。

实现约束：

- 在 `ProjectIOMixin` 内建立明确的产品方法（建议 `close_project`、`new_project`，目前为计划新增 API）；复用现有协作者。`close_all(force=True)`、`_close`、空 workspace reset 保持内部清理用途，不无条件承担项目生命周期。
- `_project_path` 的生命周期写入集中在已有 project I/O owner；holder 的内部状态通过其方法更新。第一阶段不顺手迁移全部路径读者，但必须测试两种现有表示在保存、打开、关闭后同步。
- 如需会话切换重入标记，放在现有 owner 并显式初始化，finally 对称释放；不能借用永久 teardown 标记导致窗口关闭项目后无法继续使用。
- `_analysis_restore_pending`、恢复计时器、FFT-Time／FRF coordinator、TimeRender pending switch、UltraView sidecar／capture 等按已有 owner 的失效协议处理。用旧回调晚到的测试证明不会重建旧内容；不在每个 mixin 散加 flag。
- 用户取消发生在破坏性清理之前，可严格保证内存状态不变。提交清理后若出现程序错误，应保留异常／诊断并禁止继续写入不确定旧目标，不能吞异常或谎称事务已完整回滚；不为此扩展成任意 UI 深拷贝事务系统。
- 保留 recent files、全局偏好、预设与采集窗口自身状态；不把新建项目做成清空 QSettings。独立 Batch 任务的快照不归此事务，不能直接复用应用退出的全部 teardown。

## 5. 文件所有权与修改边界

| Owner | 允许的实现工作 | 禁止的扩张 |
| --- | --- | --- |
| `ui/main_window/_project_io_mixin.py` | 生命周期产品入口、确认顺序、路径解绑与保存投影协调 | 顺便重写导入器或项目恢复算法 |
| `ui/main_window/project_dirty.py` | 复用 clear／guard／saved baseline；必要的明确会话状态 API | 第二套 digest、跨文件散写 dirty |
| `ui/main_window/window.py` | 导航与组关闭路由、已有 collaborator 的必要接线 | 新增跨 mixin 状态集群、扩大状态所有权白名单 |
| `ui/command_registry.py`、`main_window/command_coordinator.py` | 新命令元数据、单一 QAction 与入口投影 | 控件各自注册重复快捷键 |
| `ui/toolbar.py`、`ui/file_navigator.py` | 菜单文案、项目名展示、从 owner 接收可用状态 | 读取／修改 MainWindow 会话内部状态 |
| `ui_kit/message_dialog.py` | 复用既有消息对话框，加入适当上下文与按钮布局 | 另建一套对话框风格 |
| `ui/hints.py`、`ui/quickref.py`、相关现行帮助 | 同步命令名称、保存／关闭差异和快捷键事实 | 修改历史计划使其看似已实现 |
| `ui/project_io.py`、UltraView sidecar owner | 第一阶段作为原子保存和恢复的回归边界；第二阶段才按备份设计扩展 | 第一阶段混入历史版本存储系统 |

## 6. 执行分步与聚焦门禁

按依赖顺序执行，不默认分派子代理。每步先补可观察行为测试，再改 owner；只跑本步受影响的用例。未来新增的测试文件在下面明确标注为“新增目标”，不冒充现有文件。

### T0：冻结路径绑定与失败行为

- 记录实施时 HEAD、相关 dirty scope；保留 Lite 日志等无关修改。
- 在 `tests/ui/test_project_session.py`、`test_project_dirty_guard.py`、`test_session_reset_on_last_close.py` 添加回归：A 保存后关闭再导入 B，保存必须走另存为；用磁盘字节／hash 证明 A 未改变，不能只断言 `_project_path is None`。
- 加入取消、另存为取消、写入失败下来源／View／Board／两个路径表示不变的快照断言。
- 聚焦基线：以上文件的相关保存、关闭、恢复用例，加 `tests/ui/test_open_and_save_entry.py`。不做通用全量 pre-change baseline。

### T1：产品级关闭／新建事务

- 实现第 4 节协议，覆盖有来源、零来源、Board-only、clean 和 dirty 会话。
- 保留内部 `close_all` 被项目恢复复用的行为，清空旧恢复 pending 与 owner-held 延迟工作。
- 聚焦：T0 用例；`tests/ui/test_ultraview_project_session.py` 对应关闭／新建场景；`tests/ui/test_project_session.py` 中打开多个分析 View 与缺失文件恢复场景。
- 边界：`tests/ui/test_main_window_state_ownership.py`，不放宽 ratchet。

### T2：导航／最后来源分流

- 迁移“全部关闭…”入口，组关闭在移除前只做一次预检和确认，接入显式保留空项目。
- 覆盖 `_close` 的单来源入口和 `_close_files` 的物理文件分组入口，不依赖 UI 恰好总走其中之一。
- 聚焦：`tests/ui/test_analysis_source_scope.py`、`test_file_navigator.py`、`test_session_reset_on_last_close.py` 中相关关闭用例，及 `test_project_session.py` 的多 logical source 场景。
- 验收：一组取消不移除任何 fid；关闭最后一组不会 N 次提示；非最后来源移除仍沿用原依赖确认。

### T3：命令、归属显示、空项目保存能力

- 修改现有项目下拉与导航命令；统一 QAction 和按钮状态；保存／另存为成功后及关闭后刷新项目名和路径 tooltip。
- 必须包含明确保留空项目后的保存／重开，以及文件均缺失但仍绑定项目时的关闭。
- 聚焦：`tests/ui/test_open_and_save_entry.py`、`test_standard_desktop_interactions.py`、`test_toolbar.py`、`test_toolbar_branding.py`、`test_project_dirty_guard.py` 相关用例。
- 边界：`tests/ui/test_no_lambda_signal_connections.py`；若改 QSS，跑 `tests/ui_kit/test_qss_border_shorthand.py`。
- 不新增顶层 QMenuBar；旧窗口标题测试按新的项目名合同更新，仍从 app_meta 获取品牌版本。

### T4：帮助、集成与原生验收

- 同步 `ui/hints.py`、`ui/quickref.py`；更新 `mf4_analyzer/help/` 和 `docs/analyzer/user-guide/user-guide.html` 中实际包含保存／关闭交互的现行段落。
- 聚焦帮助：`tests/ui/test_hints.py`、`test_quickref.py`、`test_quickref_panel.py` 相关用例；若改帮助 deck，则跑现有 `tests/test_help_content.py` 的适用合同。
- 集成：`tests/ui/test_project_session.py`、`test_project_dirty_guard.py`、`test_open_and_save_entry.py`、`test_session_reset_on_last_close.py`、`test_ultraview_project_session.py`；持久化边界 `tests/test_project_io.py`、`tests/test_project_io_analysis_views.py`。
- 运行时命令模板：`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本步文件或节点>`。参数按目录分组，保留仓库 fixture 收集约定。
- 原生 macOS 与 Windows 分别检查：长中文项目名、窄窗口、100%／高 DPI、四按钮确认、Esc／点 X、快捷键保存、关闭后重开、任务结果晚到。检查真实控件几何和渲染，不以 QSS token 或 offscreen 代替原生验收。
- 实现阶段相关 focused／boundary 通过后完成该里程碑；除非用于合并／发布或发现跨测试污染，不额外启动全量 suite。确需全量时仅一个协调者运行，遵守主 suite 与 acquisition_ui 两个顺序进程及稳定快照要求。

## 7. 必须覆盖的验收矩阵

| 场景 | 必须观察到的结果 |
| --- | --- |
| 保存 A → 关闭项目 → 导入 B → 保存 | 首次另存为；取消选择后 A 字节不变，B 仍在内存 |
| A dirty → 保存并关闭 | 磁盘 A 包含清理前全部来源／View／Board，随后空工作区无绑定 |
| A dirty → 不保存并关闭 | A 字节不变，旧数据和所有延迟工作退出当前会话 |
| 离开确认取消／保存对话框取消／写入失败 | 不清来源、Board、View 或绑定；失败保留 dirty 并可重试 |
| A 仅一张物理卡片但多个 logical fid | 整组一次确认，取消全部保留，确认后无遗漏来源 |
| 最后一组 → 仅移除文件，保留项目 | A 仍显示为归属且 dirty；保存可用，重开得到显式空来源状态 |
| 已绑定 A、当前零来源／所有源文件缺失 | “关闭项目”仍可用；清除 Board 和绑定，不因 close_all early return 遗漏 |
| 未命名但有 Board／自定义 View | 离开保护有效；保存进入另存为，不因没有文件禁用 |
| 打开 B 的内部清理暂时零来源 | 不出现最后来源／关闭项目提示；恢复完绑定 B，guard 对称释放 |
| 关闭后旧计算／restore／sidecar 回调到达 | 不补回旧曲线、来源、Board、dirty 或旧路径 |
| 另存为 C 成功／取消／失败 | 仅成功后切换路径、saved baseline、标题和后续保存目标 |
| 删除通道、关闭 View、切换分析 section | 不解绑项目、不误触发项目离开确认 |
| 清空后明确选择原有 A 作为另存为目标 | 必须保留覆盖确认；用户显式确认的覆盖仍允许 |
| 降级恢复后保存 | 原有恢复不完整警告保留；其取消同样阻止关闭 |

## 8. 第二阶段：覆盖前备份与恢复（单独里程碑）

本阶段是对误覆盖的恢复能力，不是第一阶段生命周期修复的替代；不能宣称仅第一阶段通过就已具备备份恢复。

建议合同：

1. 只有目标已存在且内容确实将改变时生成覆盖前快照；包括另存为覆盖已有文件。首次保存和内容相同的重复保存不制造历史。
2. 快照包含旧 `.tlproj`、原保存目录信息、它引用的有效 UltraView 预览 archive 及 manifest；不复制原始大数据文件。备份 UI 明示原始数据仍为外部引用。
3. 捕获旧快照必须在 `save_preview_sidecar()` 写新 generation／清旧 archive **之前**。快照先用临时目录构建，完整发布后才能覆盖目标；禁止先替换再备份。
4. 备份写入失败时停止本次覆盖、保留旧项目并提供另存为；不默默取消备份继续覆盖。未使用备份的第一次保存仍按原子写入处理。
5. 在项目旁的专用 history 目录存快照，manifest 记录版本、原路径、时间、校验值和拥有的文件；默认保留最近 5 个已完成快照。清理仅针对 manifest 证明由该机制创建的历史；失败快照不得顶掉最后可恢复版本。
6. 通过项目下拉的“恢复备份…”选择历史，默认恢复为一个新项目，不立即覆盖当前原文件。恢复解析以原保存目录为数据引用基准，输出到新目标时重写相对引用和 sidecar descriptor；不得把嵌套 history 目录误当作原数据根目录。
7. 第一阶段不新增 backup 模块；第二阶段建议将文件快照／恢复放在中性的 `mf4_analyzer/ui/project_backup.py`（新增目标，须保持不导入 MainWindow），项目 I/O owner 编排时序，UltraView owner 提供已有 descriptor/archive 校验能力。
8. 聚焦测试新增目标 `tests/test_project_backup.py`，配合 `tests/test_project_io.py`、`tests/ui/test_ultraview_preview_sidecar.py`、`tests/ui/test_project_dirty_guard.py`；覆盖磁盘错误、原 JSON／sidecar 保全、跨目录恢复、保留数、旧坏 descriptor 和首次保存不备份。UI 入口另做原生检查。

该阶段实施前应补齐 snapshot manifest 和恢复路径的具体接口设计并 review；不要在第一阶段顺带实现半成品 `.bak`。备份规模较大时的交互阻塞与磁盘占用作为该阶段明确测量项，不用未经测量的后台线程绕过 Qt／会话所有权。

## 9. 参考与本轮文档验证

交互参考：

- [Audacity File Menu](https://manual.audacityteam.org/man/file_menu.html)：新建、导入、关闭项目分别存在，关闭处理未保存内容。
- [VS Code Multi-root Workspaces](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces)：移除文件夹和关闭工作区是独立动作。

这些资料支持“内容移除与项目结束需要清楚区分”，并不证明成熟软件普遍在移除最后一个文件时自动关闭项目。本计划的最后来源提示是针对 TraceLab 当前误操作链路的产品选择。

本轮按 project-lessons 检查了 [程序投影不等于用户意图](../../lessons-learned/programmatic-view-projection-is-not-user-intent.md) 和 [项目打开重算全部分析 View](../../lessons-learned/project-open-recomputes-every-analysis-view.md)。它们约束恢复／清理边界，不代表本计划已经实现。

本轮只新增本计划，验证文件／符号引用、状态转换、取消与失败顺序、测试路径和 `git diff --check`；不运行 runtime suite，因为没有改变可执行行为。所有 T0–T4、第二阶段及原生验收仍是待执行任务。
