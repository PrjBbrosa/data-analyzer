# 顶部图表工具栏跨 Section 一致性修复计划

日期：2026-09-26

状态：**计划完成，修复尚未实施**

核查基线：`main@7afa55afccbd014c3f2e6d0933fa1706ed687bc8`，核查时工作树干净。

## 1. 目标与范围

修复本轮 review 确认的六个问题，使时域、频谱、时频、阶次和频响顶部图表工具栏的操作目标、状态反馈、历史导航和图片导出符合统一约定。

本次交付仅为计划文档。后续实施按本文任务顺序推进；不要求多 agent 并行。共享文件由同一实施者顺序修改，避免 toolbar、card 和 page 接线互相覆盖。

范围包括 `ui/chart_stack/`、`ui/analysis_section_page.py`、必要的 canvas 视口接口及 MainWindow 既有状态投影接线。窗口最上层的打开、保存项目、批处理和 Section 切换栏未发现本轮需要修复的问题，只保留相关回归。数值算法、文件格式、版本号和持久化 schema 不在本次修改范围。

### 1.1 已确认问题

| ID | 优先级 | 影响范围 | 当前证据 | 修复任务 |
| --- | --- | --- | --- | --- |
| R1 | P1 | 五个 section 的分屏标注操作 | 右侧聚焦，点击共享标注按钮，五类画布状态均为左开右关；时频/阶次清除确认后标注数由 `[1,1]` 变成 `[0,1]` | T1 |
| R2 | P2 | 时频、阶次历史导航 | 手势后监听数为 0、快照为空、历史栈为空，启用的 Back 按钮无效 | T4 |
| R3 | P2 | 频谱、时频、阶次、频响的分屏鼠标模式 | 右侧右键选择缩放后两侧模式为 `[pan, zoom]`，共享工具栏仍高亮平移；时域对照为 `[zoom, zoom]` | T2 |
| R4 | P2 | 时域多来源同名通道 | 两条独立通道只产生一个显示名快照条目，恢复只修改最后一个通道的 Y 范围 | T3 |
| R5 | P2 | 时域单窗格保存图片 | 同一画面，复制含浮动游标读数，保存遗漏；已生成并检查实际 PNG | T5 |
| R6 | P2 | 采用公共历史管理的画布 | 首次缩放后在 180 ms 合并窗口内 Back 无效；提交历史后才可返回 | T3 |

源码依据：

- `mf4_analyzer/ui/chart_stack/cards.py`：`_build_toolbar`、`set_annotation_enabled`、`clear_annotations`；标注直接操作 `self.canvas`。
- `mf4_analyzer/ui/analysis_section_page.py`：`_configure_shared_toolbar`、`_peer_toolbars`；当前只为主 toolbar 设置 peer provider。
- `mf4_analyzer/ui/chart_stack/toolbar.py`：`_snapshot_view`、`_restore_view`、`back`、`forward`、`save_figure`；显示名键、待提交定时器及截图回退路径分别对应 R4、R6、R5。
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`：已有 `capture_xy_viewport`、`restore_xy_viewport` 和 `viewport_action_committed`，但未接入公共 toolbar 历史。
- `mf4_analyzer/ui/main_window/_analysis_mixin.py`：`_on_analysis_viewport_intent` 仅接受 `user` / `home`；恢复历史需遵守此接口，不能直接发明新的 action 字符串。

本地证据位于 `.state/toolbar-review-20260926/`：`probe.py`、`probe.log`、`copied.png`、`saved.png`。这些为隔离 Qt 探针和生成图片，不是前台平台验收；临时证据不提交 Git。后续回归测试应独立构造数据，不依赖该目录。

本轮已运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_analysis_section_page.py tests/ui/test_chart_stack.py -q -k 'toolbar or annotation or shared or history or home or mouse_mode'
```

结果：**75 passed，163 deselected，7.62 s，退出码 0**。它说明已有门禁通过，不代表六个新场景已覆盖或已修复。

## 2. 行为约定

### 2.1 操作作用域

| 功能 | 单窗格 | 分屏 | 状态归属 |
| --- | --- | --- | --- |
| 重置视图 Home | 当前画布 | 当前焦点画布；既有联动缩放按原规则传播 | canvas 视口与既有 View 状态 |
| 标注开关、清除标注 | 当前画布 | 当前焦点画布，另一侧不变 | 目标 card/canvas；工具栏显示其状态 |
| 图表选项 | 当前画布 | 当前焦点画布，保留现有 provider | canvas/既有 appearance 状态 |
| 平移、框选模式 | 当前画布 | 同 section 的可见两侧同步；右键、按钮、快捷键一致 | 各 toolbar 的现有 mode；page/stack 负责传播 |
| Back / Forward | 当前画布历史 | 保留现有共享按钮向可见两侧分别导航的行为；没有可用历史的一侧不动 | 各 toolbar 的进程内历史 |
| 保存图片、复制图片 | 当前画布及其可见游标附属元素 | 两侧完整合成；各侧读数、固定游标标签只落在所属一侧 | ChartStack 现有 presentation capture 路径 |
| 游标模式、刻度密度 | 保留当前产品规则 | 保留当前产品规则 | 既有 owner |

鼠标模式同步与“联动缩放”是两个维度：选择平移/框选工具会同步，是否同步实际坐标范围仍由既有联动开关决定。隐藏 section 和已退出分屏的隐藏 canvas 不属于广播目标。

### 2.2 必须保持的边界

1. 工具栏只投影目标状态。图表操作目标由 `ChartStack` / `AnalysisSectionPage` 提供，不从控件标题、当前绘制文本或 MainWindow 零散字段猜测。
2. 程序化恢复与用户点击分开：直接调用某 card 的局部 setter 仍作用于该 card；共享按钮入口才解析焦点。避免恢复非焦点窗格时被再次转发。
3. 历史归 `PgNavigationToolbar`，不写入项目文件、preset 或 QSettings。历史记录使用真实通道身份或稳定的画布轴身份。
4. 热力图历史只包含主图 X/Y，恢复后同步切片显示；不纳入色阶、矩阵、切片选择、计算参数或分析数据。
5. 频谱/频响既有频率单位与 log 坐标转换保持原接口；不得以通用 ViewBox 数值替代 FRF 的 Hz 历史语义。
6. 一个用户操作只提交一次业务状态。同步按钮、历史回放和 peer 更新不得递归广播或再次生成同一历史条目。
7. 使用现有弱引用接线和 Qt 生命周期规则；重复分屏、销毁右侧窗格、关闭项目后不得保留失效 wrapper、信号连接或待处理定时器。
8. 保留文件对话框 monkeypatch seam、公共导出接口和 standalone toolbar 的正常抓图能力。

## 3. 实施任务

顺序：**T0 → T1 → T2 → T3 → T4 → T5 → T6**。T4 依赖 T3 的历史提交规则，其余按优先级顺序执行。每项先新增能在原实现失败的测试，再修改产品代码。

### T0 — 固定执行基线与失败证据

产物：新增 `tests/ui/test_toolbar_section_contract.py`，集中放五个 section 的参数化接线回归；扩展各 owner 的既有测试。

- [ ] 记录执行时 HEAD、dirty 文件范围；当前 review 结果仅对上述基线成立。有新增改动时先确认相关 owner，保留其他任务修改。
- [ ] 将 R1–R6 探针转为断言“正确行为”的独立测试。使用真实 ChartStack/card/canvas 和合成小数据；只替换文件对话框、清除确认等外部交互。
- [ ] 先运行新增 node，记录每项预期失败及实际原因。测试失败不能来自 fixture 缺失、Qt teardown 或数据构造错误。
- [ ] 使用 `tests/ui` 的隔离 QSettings、显式 widget ownership 和 deferred-delete 清理。避免从 `.state` 绕过 UI fixtures 运行正式 pytest。
- [ ] 复用已有 75 项结果作为 review 证据；实施前仅补受影响 owner 的必要 baseline，不启动全套测试。

### T1 — 标注与清除跟随焦点（R1）

主要文件：`chart_stack/cards.py`、`chart_stack/stack.py`、`analysis_section_page.py`。必要时调整 `main_window/window.py` 的 FFT Inspector 标注接线。

- [ ] 为共享标注交互提供一个目标 card 解析入口，复用图表选项/频率游标的 provider 方式；单窗格默认自身，分屏由 page/stack 返回当前焦点 card。
- [ ] 保留 `set_annotation_enabled` 的局部设置能力。按钮点击通过专用处理函数解析目标，再调用目标局部 setter；避免 provider 互相转发。
- [ ] 共享按钮的 checked、图标、提示在焦点切换、进入/退出分屏、目标程序化更新后读取目标实际状态。只同步外观，不额外发出用户变更信号。
- [ ] 清除按钮解析并固定目标，再读取目标标注数、确认并清除。同一次确认始终作用于同一目标；确认期间目标销毁或所属 View 已变化时取消，不清除新目标。
- [ ] FFT Inspector 的标注入口与共享按钮作用到同一焦点画布；更新回显时屏蔽递归信号。保持现有参数/项目字段含义，不新增标注模式持久化字段。
- [ ] 验证正确画布的 markup revision、dirty 和 View 标注 capture/restore 路径。清除后切走/切回或保存/重开不得恢复已清除标注，另一侧数据保持不变。

回归：五个 section，左右焦点分别测试开/关、空标注清除、取消、确认；真实标注验证两侧数量。新增跨 section 用例放 `test_toolbar_section_contract.py`；运行 `test_chart_stack.py` 标注相关 node、`test_split_focus_routing.py` 和 `test_analysis_view_bridge.py` 相关 capture/restore node。若调整项目交互接线，补 `test_project_session.py` 中对应标注往返用例。

### T2 — 分屏鼠标模式双向同步（R3）

主要文件：`analysis_section_page.py`、`chart_stack/toolbar.py`；`chart_stack/stack.py` 的时域实现作为行为对照。

- [ ] 为分析页面每个存活 toolbar 配置“除自身外的可见同页 peers”，不是仅从左侧返回右侧。新建右侧窗格时明确继承共享工具模式。
- [ ] 用户入口调用广播 setter，peer 使用局部 setter；一次传播不改变焦点，不传播到其他 section。
- [ ] 由 page 同步共享工具栏高亮，覆盖右侧右键、右侧快捷键、程序化恢复及焦点切换。保留当前 idle / pan / zoom 的切换含义，不顺带重设计鼠标工具。
- [ ] 重复进入分屏不重复连接；退出分屏/删除右侧后清理引用和信号。历史 Back/Forward 的原有 peer 作用域不被此修复改变。

回归：五个 section × 左右入口，调用真实右键菜单按钮及 QAction；检查两个 ViewBox 模式、两个 toolbar mode、共享高亮、焦点身份和信号次数。覆盖联动开/关、重建/重绘、退出后重进、后台 section 不变。运行 `test_chart_stack.py` 的 mouse-mode/broadcast 相关 node、`test_pg_line_canvas.py::test_menu_pan_button_calls_broadcast`、`test_analysis_section_page.py` 的 split/focus 相关 node。

### T3 — 历史身份与立即导航（R4、R6）

主要文件：`chart_stack/toolbar.py`；必要的局部接口只放所属 canvas。

- [ ] 时域快照遍历 `_ChannelKeyDict.composite_items()`，保存和恢复都用复合键；普通 mapping 的频谱/FRF 轴键继续沿用。不得经过显示名再解析回通道。
- [ ] 遗留显示名兼容仅在唯一匹配时允许；重复标签不猜测、不误改另一来源。历史本身不持久化，无需项目 schema 迁移。
- [ ] 增加单一 pending-history 提交流程：Back、Forward、Home 在改变历史指针/视口前停止 timer 并提交当前手势一次。连续相同快照去重，保留 32 条上限和新手势截断 redo 的行为。
- [ ] Back 后不允许旧 timer 再把已恢复范围追加为新手势。Home 提交动作前的 pending 范围和动作后的目标范围各一次，随后 Back 可回到 Home 前。
- [ ] 合并 timer 保持 180 ms；测试通过显式触发 pending/timeout 验证，不依赖缩短 timer 或 sleep。
- [ ] 历史恢复守卫在异常路径对称释放。监听重绑不重复连接，同数据重建继续可恢复；清空/销毁时停止 pending timer，防止旧数据范围在新内容上提交。
- [ ] 对 View 切换期间 pending timer 做边界测试：提交或丢弃必须发生在旧画布内容替换前。仅补必要取消/重绑，不扩展为持久化的每 View 历史系统。

回归：同名不同来源两条曲线、不同 Y 量级、通道重排/移除、重建；首次手势立即 Back、连续两次手势立即 Back、Back→Forward、Back 后新手势、pending→Home→Back、清空/销毁。运行 `test_pg_multifile_samename_curves.py`、`test_chart_stack.py` 的历史/Home node、`test_pg_line_canvas.py` 的 FFT 历史 node、`test_frf_canvas.py::test_frf_canvas_toolbar_history_round_trips_log_ranges_in_hz`。

### T4 — 接通热力图历史（R2）

主要文件：`pg_canvas/heatmap_canvas.py`、`chart_stack/toolbar.py`、`chart_stack/cards.py`。按实际状态写回需要，局部调整 `_analysis_mixin.py` 既有接线。

- [ ] 优先复用 `capture_xy_viewport` / `restore_xy_viewport`。公共 toolbar 在快照/恢复边界支持这一小型 canvas 能力；不为热力图伪造通道名称或复制一套历史管理器。
- [ ] 在有效数据和最终绘图区范围就绪后建立基线；空图不造历史。接通原生拖动、框选及 Ctrl/Shift 滚轮事件，不能只测直接调用 `_commit_pending_view`。
- [ ] 选择一个历史捕获信号入口。热力图已有 `viewport_action_committed`，优先复用其用户动作；若保留 ViewBox 手势监听，必须证明同一动作不会从两条路径重复入栈。
- [ ] 恢复调用 `restore_xy_viewport`，保证切片随主图范围同步，色阶和分析结果不变。历史导航作为用户操作，通过既有 `user` 语义提交变化轴；程序化项目恢复保持静默，不能发送不受支持的 `history` action。
- [ ] 不用 `home` 语义标记普通历史恢复，避免把用户范围变成自动范围；历史捕获守卫覆盖状态通知，防止回放再次入栈。
- [ ] Back/Forward 可用状态按有效历史更新。待提交的真实手势也必须允许 Back；共享按钮按可见 peers 是否至少有一个可导航目标决定启用。没有历史的 peer 仍 no-op。
- [ ] 保留共享历史按钮对两侧的既有作用域；联动开/关分别验证最终范围及状态，不让依次恢复的第二个窗格反向覆盖正确结果。若发现相互覆盖，按一次共享导航批次提交最终范围，仍由 toolbar/page 现有 owner 管理。

回归：时频/阶次、空图/有图、X/Y 独立操作、带切片、Home 往返、刷新同结果、切换数据、分屏联动开/关、离开 section 返回、保存重开后的最终范围。运行 `test_pg_heatmap_canvas.py` 的新增历史、手势、Home、slice node；`test_analysis_viewport_cold_restore.py`、`test_analysis_section_page.py` 相关 node，以及新增跨 section 合同测试。

### T5 — 保存与复制统一图像合成（R5）

主要文件：`chart_stack/stack.py`、`chart_stack/toolbar.py`；需要时调整 `analysis_section_page.py` 的现有 grab 接线。

- [ ] 由 ChartStack 提供同一展示图像捕获入口供显式保存和复制使用：时域分屏复用 `_combined_split_pixmap`，单窗格复用 `grab_presentation_pixmap`，分析页面复用现有 combined capture。
- [ ] save provider 返回含 live pill、固定游标面板和 Pn 标签的最终图像；`PgNavigationToolbar` 只负责选择路径与编码落盘，不再自行遗漏外层 UI。
- [ ] 保持默认 HiDPI 倍率、DPR 归一化、两侧间距和各侧归属。热力图切片面板继续包含在图片中。
- [ ] 显式保存与复制同样取消过渡遮罩、完成 pending pin layout 后抓真实内容；UltraView 自动预览的捕获策略保留。
- [ ] 没有 provider 的 standalone toolbar 可保留直接 canvas 抓图。已配置合成 provider 却失败时明确反馈，不静默保存一张缺读数的降级图片。取消对话框不抓图、不落盘；保存失败维持可观察提示。
- [ ] 保持 `mf4_analyzer.ui.chart_stack.QFileDialog` monkeypatch seam，避免测试换路径后绕开真实保存代码。

回归：五个 section 的单/双窗格；重点覆盖时域、FFT、FRF 的 live/pinned chrome，时频/阶次的切片面板。固定状态与几何后，PNG 保存结果应与复制所产 QPixmap 像素一致；另用已知颜色区域验证读数确实存在，不能只证明两条路径同样遗漏。JPEG 检查尺寸和区域内容，不作无损像素比较。

门禁：`test_chart_stack.py` 的 copy/save node、`test_pinned_cursor_capture.py`、`test_pg_heatmap_canvas.py::test_grab_pixmap_includes_slice_info_panel`、`test_chart_stack.py::test_analysis_copy_image_includes_slice_panel`。

### T6 — 集成、交互说明与平台验收

- [ ] 按 §2 作用域逐项核对按钮、右键菜单、快捷键、Inspector 回显；更新 `ui/hints.py` 和 `ui/quickref.py` 中受影响说明：标注/清除作用于焦点、模式同步、历史作用域、导出包含可见读数。沿用现有文案入口，不新增无关控件。
- [ ] 顺序场景：时域→频谱→时频→阶次→频响→时域；每页完成分屏、右侧操作、焦点切回、退出/重进分屏。检查后台画布不被操作、隐藏窗格不被广播、共享按钮状态准确。
- [ ] 新增窗格销毁和重建回归，排查重复信号、已销毁 Qt wrapper、停止后仍提交的 timer。
- [ ] 在生产 QSS/字体、隔离 QSettings 下做真实 Cocoa 探针：五类 section 各检查左右焦点标注、高亮、实际鼠标操作、立即返回和 PNG 结果。日志与截图写 `.state/toolbar-section-fix/`。
- [ ] Windows 冻结包前台检查右键、快捷键、标注确认和保存图片；只有实际重建并运行的新包才可计为通过。未执行时明确标记 UNKNOWN，不以 offscreen 或源码检查替代。
- [ ] 记录 R1–R6 各自测试 node、结果、当前 HEAD 和 dirty 范围。检查 lesson 状态；已有身份/焦点/图像合成教训足以覆盖时引用即可，新发现可重复的独立模式再按仓库流程归纳。

## 4. 验证策略与完成条件

### 4.1 运行方式

owner 测试统一使用项目运行时：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <该任务新增 node 与相关 owner node> -q
```

每项任务完成后运行自己的新增 node 和上述 owner 门禁。最终集成只运行尚未覆盖或后续改动影响的相关组合，不重复跑已通过且依赖未变的测试，不运行全部 `tests/ui` 或默认全套。

适用边界门禁：

| 实际修改 | 必需门禁 |
| --- | --- |
| 新增/调整 Qt 信号连接 | `tests/ui/test_no_lambda_signal_connections.py` |
| chart_stack、analysis page、canvas 接口/导入 | `tests/ui/test_import_boundaries.py` |
| 增加/调整时域 canvas collaborator 属性 | `tests/ui/test_pg_canvas_backref_invariants.py` |
| MainWindow 接线或状态写回 | `tests/ui/test_main_window_state_ownership.py` |
| 改动样式/控件外观规则 | `tests/ui_kit/test_qss_border_shorthand.py`，并补实际像素检查 |
| 所有任务 | `git diff --check`、改动范围检查 |

本计划无数值算法和中立层变更，不默认执行 DSP/Batch 数值或全量 packaging suite。若实施时发现需要跨越这些边界，先记录原因和新增验证范围。

### 4.2 完成清单

- [ ] R1：正确目标的标注开关、清除、确认与状态往返，另一侧保持不变。
- [ ] R2：时频/阶次真实手势可 Back/Forward，空图与不可用按钮反馈正确，切片/保存状态一致。
- [ ] R3：五个 section 的左右入口、共享高亮和 ViewBox 模式一致，广播无递归或跨 section 污染。
- [ ] R4：同名不同来源历史完整保留，恢复不串通道，FFT/FRF 原有坐标语义通过回归。
- [ ] R5：相同展示状态下保存/复制产物一致，读数与标签通过独立像素检查。
- [ ] R6：pending 手势立即导航正确，timer 不破坏 redo，Home 往返与清空生命周期通过。
- [ ] 相关 owner/边界测试通过；真实 Cocoa 与 Windows frozen 分别填写 PASS / FAIL / UNKNOWN。

交付分开报告“代码与 offscreen 回归完成”和“平台前台验收”。存在未运行的平台门禁时，可以提交明确标记 partial 的修复结果，不宣称跨平台验收完成。

## 5. 本次文档交付验证

仅新增本计划；核对当前源码、既有测试 node、相关 lessons 和本轮探针结果。检查路径、任务依赖、六项问题映射与 `git diff --check`。本次没有可执行行为变化，无需重新运行 runtime suite；§1 的 75 项结果来自前一轮 review。
