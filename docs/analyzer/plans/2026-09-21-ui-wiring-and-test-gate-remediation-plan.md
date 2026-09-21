# 9 月 20–21 日提交复审：UI 接线与测试门禁修复计划

- 日期：2026-09-21。
- 状态：**计划已编写，修复尚未实施**。本次交付仅编写、提交和推送本文件。
- 审查范围：`82871903..3fdc4a05`，共 8 个提交；源码基线为 `3fdc4a057f4275e4fc7351e77bdfba638e5d77d7`。
- 目标：关闭 7 项已确认问题，恢复 UI 操作对象的正确归属及测试结果可信度，补齐能拦住相同回归的行为验证。
- 非目标：新增 Cursor 功能、改变时间范围产品语义、重构 Pin 架构、调整 DSP、升级版本或重写历史计划。
- 关联：[时间范围计划](2026-09-20-time-range-segment-and-linked-projection-plan.md)、[菜单和侧栏计划](2026-09-20-popup-trigger-and-navigator-width-followup.md)、[进度和 Pin 投影计划](2026-09-20-progress-and-cursor-projection-hardening-plan.md)。这些是背景材料；完成状态以当前源码和本计划的新验证为准。

## 1. 问题与证据台账

行号对应上述源码基线，实施时按符号重新定位。下表记录本次 review 的证据，不表示修复已完成。

| ID | 优先级 | 引入提交 / 定位 | 已确认问题及证据 |
| --- | --- | --- | --- |
| R1 | P1 | `f4105684`；`tests/conftest.py:117–128`，`pytest_runtest_teardown` | 没有 QApplication/style baseline 时，`finally` 中的 `return` 吞掉 teardown 异常。真实 pytest 内存收集探针强制抛出清理断言后，仍输出 `1 passed`、退出码 0。 |
| R2 | P1 | `df2c6fc0`；`scripts/run_test_gate.py:889–891`、`:956–962` | Windows Job 已空时回退进程快照；快照函数无条件返回根 PID。空快照、空 Job、`poll()==0` 的确定性 WinAPI 替身仍返回存活记录，导致正常退出被标记为残留、`UNVERIFIED`，阻断后续 phase。Windows 原生尚未验证。 |
| R3 | P2 | `24b45a94`；`ui/chart_stack/stack.py:2482–2486`，`_on_primary_live_pin_requested` | 主读数 P 按钮使用最后更新的 `_active_cursor_card`。真实分屏按钮探针中，左读数 0.2s、右读数 0.8s，点击左 P 后左侧记录为空、右侧新增 0.8s。 |
| R4 | P2 | `24b45a94`；`ui/chart_stack/pinned_cursor_controller.py:1523–1545`，`_current_live_x` | FFT 单游标只更新 `_cursor_lines`，未更新 A/B placement；新按钮路径错误依赖 placement 快照。真实按钮探针显示 50 Hz，但 snapshot/current X 为 None，点击后 records=0。未据此判定 FRF 存在同样缺陷。 |
| R5 | P2 | `5a6443a9`；`ui/side_panels.py:383–396` | PEEK 把历史展开宽度当作必要宽度。真实控件探针记住 1298px，窗口收窄至 1100px 后，虽面板最低仅需 288px，悬停仍保持 HIDDEN。 |
| R6 | P2 | `df2c6fc0`；`scripts/select_test_gate.py:407–411`，`_acceptance_command` | 额外 gate 的解释器路径未引用。当前含空格的仓库路径生成的 real-file 命令被拆成 `/Users/donghang/Downloads/data`，不是可执行文件。 |
| R7 | P2 | `3fdc4a05`；`ui/chart_stack/cursor_pill.py:853`；`tests/ui/test_chart_stack.py:796–797` | 标题控件改为中心对齐，旧测试仍断言顶边相同，实际 `4 != 6`。这是测试同步遗漏；不应为通过旧断言而回退产品的中心对齐。 |

产品源码路径省略的统一前缀是 `mf4_analyzer/`。R3、R4、R5 已有 offscreen 行为证据；它们不依赖截图主观判断。

### 当前验证的边界

| 已完成的 review 验证 | 输出 / 限制 |
| --- | --- |
| 进度、侧栏、菜单、ChartStack 等相关 UI 测试 | 331 passed、3 failed。失败包括 R7 和下述两项历史 mock 问题。 |
| 时间范围、相关恢复、帮助及接线 | 193 passed，未确认本次新增缺陷。 |
| Pin panels / interaction / lifecycle | 73 passed；两条按钮缺陷另由探针复现。更宽的九文件游标测试运行中止，记为 UNVERIFIED。 |
| 测试基础设施、数值/IO/采集等相关测试 | 461 passed、18 skipped、60 deselected。跳过项不是通过。 |
| Cocoa 原生 Qt 的进度文案、侧栏几何 | 5 passed；不是 Pin 自然鼠标拖动或 Windows 验收。 |

这些组可能有重复覆盖，不相加宣称独立用例总数；R1 修复前的通过输出不能证明 teardown 正常。没有本基线的完整全套通过证据。

两项历史失败单独登记：`test_compute_progress_integration.py::test_fft_multi_source_progress_wraps_cache_misses_only` 的 fetch mock 不接受既有 `params` 参数；`::test_order_job_closure_passes_progress_callback_and_cancel_token` 的 fake result 不满足既有 effective dataclass 合同。对应产品调用在 2026-09-05 已存在，不算本次新增产品缺陷。T6 只维护这些测试替身，不改算法。

## 2. 成功标准和实施约束

1. 测试 body、fixture finalizer、Qt teardown 出错均保留失败状态；style 恢复和对象清理仍在既定顺序执行。
2. Windows 正常退出报告成功；真实残留子进程才触发清理；枚举失败保持可观测，不能当作成功证明。只清理 runner 所有的进程。
3. 点击某一 live 读数面板的 P，只固定该面板所属 canvas 的可见读数，不能被另一 pane 的最后一次更新或焦点覆盖。
4. FFT 首次单游标、移动后的单游标及 dual→single 切换后均固定当前物理 Hz；无有效读数时不创建记录，不使用旧 A/B 或按钮坐标替代。
5. 左栏缩窗后的 PEEK 在空间足够容纳最小内容宽度时可用；空间确实不足时保持 HIDDEN。暂时缩小的 PEEK 不覆盖用户原有的 dock 宽度偏好。
6. 生成的额外 gate 命令与主 focused 命令遵循同一 shell/引用约定；含空格路径能够作为一个解释器参数执行。
7. 中心对齐测试验证实际中心、间距和边界；保留非重叠、可点击及文字不裁切的检查。

在现有 owner 内做最小修改。沿用 composite identity、Pin UUID/编号、placement 与 presentation 的职责划分、`_CanvasBackref` 合同及既有 Qt 生命周期。不得用新增全局 last-cursor 状态、解析 HTML 数值、扩大 ratchet 白名单、`xfail`、忽略 teardown 错误或增加 sleep 绕过问题。

## 3. 任务拆分

### T0 — 锁定实施快照和验证入口

- 记录实施时 HEAD、工作区范围及正在运行的 pytest 进程；若源码已变，先确认 R1–R7 是否仍可重现。
- 保留无关变更。本计划编写时已有：修改的 `docs/analyzer/user-guide/user-guide.html`、未跟踪的 CAA 计划及原型、`ssh-keygen`；均不属于本计划发布范围。
- 将 review 的内联复现转为下面 owner 内的回归测试，每项先观察预期失败再修复。不要从历史通过数量推断当前基线。
- **验证**：Git 范围、具体 owner 测试的失败原因、测试入口可用性。此阶段不跑通用的预修改全套基线。

### T1 — 修复 teardown 假通过（R1，其他可信验收的前置）

- **Owner**：`tests/conftest.py`；回归优先放入 `tests/ui/test_app_style_isolation.py`，复用已有隔离子进程测试方式。
- 消除 `finally` 中会覆盖在途异常的提前返回；以条件分支实现无需恢复时的 no-op，保留 hook 原返回值及异常传播。
- 无 Qt/no baseline 路径必须通过真实 pytest 子进程验证：测试 body 通过、finalizer 或内层 teardown 故意失败，外部断言非零退出和 teardown ERROR。仅测试 generator 不足以代替 hook 集成。
- 增加有 QApplication/baseline 的对照：清理失败仍可见；正常清理保持成功，style/font/palette 能恢复。外层测试自身不能依赖被测 hook 才能发现子进程异常。
- **Focused**：`tests/ui/test_app_style_isolation.py`、`tests/ui/test_qt_fixture_lifecycle.py`。
- **Boundary**：`tests/test_conftest_autouse_scope.py`、`tests/ui/test_qsettings_isolation.py`。不改变根目录 `conftest.py` 的 collector 身份修复。
- **完成证据**：无 Qt 和有 Qt 两条强制清理失败都变为非零退出；正常对照与隔离检查通过后，才接受后续任务的正式验收结果。

### T2 — 修复 Windows 退出识别（R2）

- **Owner**：`scripts/run_test_gate.py`、`tests/test_run_test_gate.py`。
- 枚举结果以实际快照或有效 Job 的进程成员为准，不能仅凭记录过 root PID 就判定其仍活着。父进程退出但子进程仍存在的场景仍需沿拥有关系发现并清理。
- 覆盖正常空 Job/空快照、根 PID 不存在但子进程仍在、根进程仍在、无法获得 Job 的 fallback。检查 WinAPI 调用和失败分支，不能把枚举失败转换为可靠的“没有残留”。
- 增加 runner 层的两阶段对照：第一阶段正常退出后继续第二阶段；另一个对照保留真实子进程，应触发有界清理并准确记录状态。禁止按进程名全局结束 Python。
- **Focused**：`tests/test_run_test_gate.py` 中 Windows 枚举/清理、正常 phase、父退出子存活、超时/中断、状态合成相关用例；新增空 Job 回归。
- **Boundary**：同文件 POSIX 所有权清理及无关进程存活用例，确保共享调度没有退化。
- **平台门**：确定性 WinAPI 替身验证控制流；Windows 原生另跑正常完成、父退出子残留及超时回收。无 Windows 环境时保留该门为 UNVERIFIED，不将 mock 结果命名为跨平台验收。

### T3 — 修复额外 gate 命令引用（R6）

- **Owner**：`scripts/select_test_gate.py`、`tests/test_test_gate_selection.py`。
- 统一主 focused 命令和额外 gate 的引用约定，在 token 边界引用解释器及节点，不对完成的整条命令重复包裹。保留模板固定参数语义。
- 使用含空格的临时仓库/解释器路径，走 `select_gate()` 的真实路由，检查 real-file、native、frozen、full-integration 模板中的解释器不被截断。按工具声明的 shell 约定检查，不将 POSIX quoting 宣称为 cmd.exe quoting。
- **Focused**：`tests/test_test_gate_selection.py`；包括当前仓库对应的 `mf4_analyzer/io/loader.py` 路由、参数 round-trip，以及用无害替身可执行文件验证 argv。
- **Boundary**：确认 selector 仍为 dry-run、节点和附加 gate 选择不变；不执行完整 real-file/native/frozen 套件来验证字符串引用。

### T4 — 修复 P 按钮的画布归属和 FFT 读数来源（R3、R4）

- **Owner**：`ui/chart_stack/stack.py`、`ui/chart_stack/pinned_cursor_controller.py`；必要的查询接口由 `ui/pg_canvas/line_canvas.py` 拥有。测试放入 `tests/ui/test_pinned_cursor_panels.py` / `test_pinned_cursor_interaction.py`。
- 先建立真实双 canvas 回归：左右不同读数，右侧最后更新，真实点击左 P；断言左侧新增正确 x、右侧记录和 live 状态不变。反向再测，不能只 spy `pin_live_readout()` 被调用。
- 按 pill 实际归属选择 canvas。处理共享主 pill 在不同 section 的合法复用、进入/退出 split 及 View/pane 切换；避免为了修复时域而一律写死 `canvas_time`。
- FFT 当前单游标读数应由 canvas 的既有真实状态查询得到，或提供一个窄的只读 owner 接口；不把双游标 A/B placement 假装成当前 hover，不从 UI HTML 提取数值，不引入第二个可漂移缓存。
- FFT 回归从新 canvas 的第一条有效单游标开始，覆盖首次 50 Hz、再次移动、dual→single、清空/无结果、频率线性/对数坐标。断言记录中是实际物理 Hz、属于正确 pane；按键 P 与按钮 P 的既有差异不能被意外改写。
- 时域 Time-X/Custom-X、双游标 consume/保留 placement、独立 Pin 面板及 FRF 走既有合同做针对性回归。FRF 作为相邻检查，不预先扩大为待修产品缺陷。
- **Focused**：`tests/ui/test_pinned_cursor_panels.py`、`tests/ui/test_pinned_cursor_interaction.py`、`tests/ui/test_pinned_cursor_lifecycle.py`；若新增 FFT canvas 接口，追加 `tests/ui/test_pg_line_canvas.py` 中对应 cursor 用例。相邻 FRF 合同选取 `tests/ui/test_frf_canvas.py` 的 cursor 用例，不运行无关分析测试。
- **Boundary**：`tests/ui/test_pinned_cursor_architecture.py`、`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_no_lambda_signal_connections.py`；若改动模块依赖，追加 `tests/ui/test_import_boundaries.py`。
- **原生门**：Cocoa 前台左右交替 hover→点击 P、FFT 首次单游标→点击 P、dual→single→再次固定；核对读数、目标 pane、Pin 线和 live 消费结果。offscreen 点击成功不替代此门。

### T5 — 修复侧栏缩窗后的 PEEK（R5）

- **Owner**：`ui/side_panels.py`、`tests/ui/test_side_panel_widgets.py`。复用 FileNavigator 的 `expanded_minimum_width()`，不新增第二套内容宽度常量。
- 区分用户记忆的 dock 宽度、当前 host 可容纳宽度和 panel 最小/最大宽度。PEEK 的实际宽度在可用区间内夹取；只有最小内容宽度加 strip 都放不下时才拒绝展开。
- `_peek_can_fit()` 与 `_position_overlay()` 使用一致的预算，覆盖 PEEK 中继续缩窗、空间重新变大和恢复历史会话；不以临时 PEEK 宽度覆盖 remembered dock 偏好。
- **Focused**：`tests/ui/test_side_panel_widgets.py`；新增“宽 dock→收起→缩窗→hover”及“PEEK 中缩窗”回归，断言 overlay 在 host 内、panel 不小于内容下限、真实空间不足时正确收起。
- **Boundary**：`tests/ui/test_channel_config_bar.py` 的 navigator 完整行几何用例、`tests/ui/test_inspector_width_cap.py`；保持右侧 Inspector 上限、收起 0 宽、strip 点击固定行为。
- **原生门**：Cocoa 生产 QSS 下执行缩窗/悬停/固定，检查配置箭头、编辑按钮及左右边缘条可见且可点击。

### T6 — 对齐几何回归并维护历史测试替身（R7 与两项历史失败）

- **Owner**：`tests/ui/test_chart_stack.py`、`tests/ui/test_compute_progress_integration.py`。不为旧断言修改产品布局，也不修改 FFT/Order 产品算法。
- 将 full/mini 的顶边相等断言更新为实际纵向中心相等，使用已有几何测试约定中的像素取整容差；保留关闭按钮右边距、横向间距、非重叠等有效断言。
- 保留/复用 `tests/ui/test_cursor_table_geometry.py` 的生产 QSS 几何检查。需要像素容差时给出逻辑像素或设备像素含义，不用扩大容差掩盖错位。
- 两项历史 mock 单独修正：fetch 接受并验证真实调用的 `params`；Order fake result 提供实际合同要求的 effective dataclass。继续验证 cache miss 才计算、progress callback 和 cancel token 传递，不改为宽松成功断言。
- **Focused**：`tests/ui/test_chart_stack.py::test_cursor_pill_pinned_close_packs_toggle_immediately_to_its_left`、`tests/ui/test_cursor_table_geometry.py` 的标题控件几何用例、`tests/ui/test_compute_progress_integration.py`。
- **Boundary**：这些仅为测试修正，复用 T1 的 fixture/隔离门；若未改 QSS 或产品依赖，不额外添加无关运行时门。

### T7 — 集成验收与完成记录

- **Owner**：协调者。整合 T1–T6 的实际 diff、各项原失败→修复通过证据和平台结果，更新本计划状态及 R1–R7 台账。
- 先通过各 owner 的 focused/boundary 门；不把中止的九文件游标运行当作已通过，也不因历史统计较大就复用为新源码的通过证明。
- 本次实施改变共享 conftest 和跨平台 runner，属于跨测试边界的稳定集成里程碑，因此需要一次完整集成门。T1/T2 完成后才用修复后的 runner 执行；worker 不启动全套。
- 开跑前检查 pytest 进程及 cwd，记录 HEAD 和脏文件内容指纹；结束后再次核对。相关源码中途变更、崩溃、超时或中断均标为 UNVERIFIED。
- 严格使用两个全新、顺序的 pytest 进程：先主套件 `--ignore=tests/acquisition_ui`，完成后单独执行 `tests/acquisition_ui`；不同时运行，不绕过失败继续宣称整体通过。记录 runner 的真实命令和 pytest.ini 中生效的过滤条件。
- 完整门只在这一稳定里程碑运行一次。出现新修改/失败且确需重跑时，先记原因；不得用反复全套掩盖未定位的问题。
- 单列 Cocoa 原生结果、Windows runner 原生结果和未运行项。当前没有发布构建变更，不要求本计划制作 Windows Full/Lite 冻结包，也不声称完成冻结包验收。
- 若有新发现，按“本次回归 / 历史问题 / 平台未验证”登记；不得通过 skip/xfail 或降低断言让已知失败变绿。

## 4. 执行顺序与可选并行

顺序依赖：`T0 → T1 → (T2、T3、T4、T5、T6) → T7`。T1 前可以准备其他任务的失败复现，但修复后的正式验收须在 T1 通过后执行。

后续如采用并行 agent，按文件所有权分组，禁止交叉修改：

| 分工 | 任务 / 文件边界 |
| --- | --- |
| 协调者 | T0、T1、T6、T7；共享 fixture、ChartStack 旧断言、progress 历史 mocks、集成及唯一全套门 |
| Windows runner worker | T2 的 runner 和对应测试 |
| Selector worker | T3 的 selector 和对应测试 |
| Pin worker | T4 的 stack/controller/必要的 FFT canvas 接口和 Pin owner 测试；不改 T6 的测试文件 |
| Side-panel worker | T5 的 side_panels 和其测试 |

不要求同时启动所有 worker；按可用并发安排。共享方法合同由协调者确认，各 worker 保留别人的改动，只跑自己的 focused/boundary 门。计划本身不启动实施 agent。

## 5. 验证与交付约定

Qt focused 命令统一使用项目 runtime，例如：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本任务明确的测试文件或节点> -q
```

原生 Cocoa 检查另用 `QT_QPA_PLATFORM=cocoa`，先保证 QSettings 隔离；保留屏幕/交互证据与 offscreen 证据的区别。命令中的占位节点须在实施时替换为实际任务节点，不将此示例视为已执行命令。

实施提交可按 T1、T2、T3、T4、T5、T6 分成可审阅的小提交，每个提交只包含该任务源码与回归测试。所有提交前检查分支、文件范围及 `git diff --check`；不带入本任务外的用户文件。

完成记录至少包含：每个 R 的修复提交、回归测试及原失败原因、focused 输出、完整门前后源码快照、Cocoa/Windows 状态、残余问题。R1–R7 全关闭且适用验收门通过，才标记“实施完成”；平台门未跑应标记“代码修复完成，平台验收未完成”。

**当前文档发布门**：核对 7 项映射、依赖和文件路径，通读全稿，检查相对链接及 `git diff --check`，仅 stage 本文件后 commit/push 并核对远端提交。当前没有可执行行为变更，不运行 runtime 测试或全套；上一轮 review 输出只作为计划输入。
