# 测试目标、质量与执行效率优化计划

- 日期：2026-09-19。状态：**已完成两轮范围审查并补充计划，待执行；不实施测试或产品修改**。全目录静态筛查、重点节点人工审查、错误注入、运行验收是不同证据，不能合并称为全仓逐条审计完成。
- 审查基线：`4eda2e908907e563df27862903e058ef07427397`，叠加正在变化的 dirty worktree。本文行号是审查时定位，执行前按符号复核；尤其不得覆盖当前 `tests/ui/conftest.py` 的 PinKeyRouter 改动。
- 收尾时其他任务已将 HEAD 推进到 `fb27087f409ef484b3aadc30f5fc5219e9d0ed67`（包含 Pin 协调拆分及旧测试计划入库）。本文不是这一新快照的运行验收；已检查 runner 文件未有未提交修改，执行仍须重新核对相关指纹。
- 承接：[测试基础设施横向审查与优化计划](2026-09-19-test-infrastructure-hardening-plan.md)。旧计划保留为历史记录，本文补充其未完成项及业务测试质量、精准选测，不重新执行已通过且未变化的任务。
- 用户约束：测试目的、功能和必要覆盖不得精简删除；可以并行审查，实施必须有明确文件归属。此次用户明确要求只 review、写 plan。

## 1. 结论与已完成范围

**之前优化过部分基础设施，但没有完成“其余测试全部优化”。** `4eda2e90` 修改了 38 个文件，包含设置隔离、DeferredDelete 清理、可取消弹窗 timer、Batch worker 收尾、部分 subprocess timeout、样式/Qt message handler 恢复，以及外层 watchdog。旧计划标题下仍写“修复待实施”，不能据这句判断当前代码没有实施；同样，存在提交也不代表旧计划 T0–T7 全部验收。

本机旧证据 `.state/test-runs/20260919T134606-pid19734/` 记录了 **61 passed, 2 skipped in 11.59s**，run.json 为 PASS，前后内容指纹一致，但其 HEAD 是 `c75c47e3` 加当时 dirty 内容。它只证明当时该组基础设施节点通过，**不是本轮当前树验收，也不是全部测试优化成果**。

本轮静态盘点：548 个 `test_*.py` 文件、9306 个测试函数定义；其中 `tests/ui` 为 333 个文件、6559 个定义。这是 AST 定义计数，**不是 pytest 参数展开后的 item 数量**。审查覆盖 runner/fixtures/执行策略及各目录代表性用例，没有逐条审完这 9306 个定义。

检查时，同 checkout 已有 PID 29590 运行 `pytest --ignore=tests/acquisition_ui -q` 约 29 分钟，CPU 约 98%，RSS 约 1.2 GB。仅凭此不能判定死锁或归因于 GC/QSS；本轮没有干预该进程，没有另跑全套，也没有在竞争负载下测提速比例。

## 2. 按严重程度排列的发现

| ID / 优先级 | 证据与实际影响 | 证据等级 |
| --- | --- | --- |
| R01 / P1 | `scripts/run_test_gate.py:525` 父进程退出即跳过进程组清理；`:552` 的升级 KILL 也只看父进程；`:767` 又必须等输出 EOF。后代继承 stdout 并继续存活时，hard deadline 后仍可能无法退出。 | **独立进程探针确认清理缺口，循环源码确认挂住路径**。探针返回 `parent_returncode=0, actions=[], child_alive_after_watchdog_cleanup=True`；finally 已清理探针自己的专属组。没有复现整套 pytest 卡死。 |
| R02 / P2 | runner `:89` 只记录 outcome/duration，不即时保存失败 traceback；前项失败、后项卡住时无法从 events 得到原始失败原因。setup fail/skip 后 teardown 开始也未完整记录；`:483` 诊断没有 Python 栈。 | **源码确认**；当前四个 runner 自测未覆盖这些组合。 |
| R03 / P2 | runner `:897–916` 快照不可用时 `source_snapshot_matches=None` 仍可能返回 PASS；`:307–380` 的 ps/lsof 预检跳过未知 cwd，只匹配根目录且无锁。 | **源码确认的证据与互斥缺口**；未复现并发双 gate。 |
| R04 / P2 | `pytest.ini:7` 默认 `not slow`；runner `:1002–1004` 的 full-suite 继承它。现有入口没有 owner 选测映射或选中/未选中清单，难以回答“本改动为什么跑这些”。 | **配置与入口确认**。排除 slow 是既有策略，不是本轮发现的新增回归；默认全套不能代表专项全验收。 |
| R05 / P2 | `test_main_window_state_ownership.py:44`、`test_no_lambda_signal_connections.py:17` 是纯源码检查，却继承 `tests/ui/conftest.py:163,410,432` 的 qapp、ChartStack、MainWindow 相关 autouse。`:116,482` 仍有两次 GC，`:136` 全堆扫描；`:147` 容许一个 filter 存活。 | **成本路径及判据确认**；没有计量耗时占比，不能称为数小时慢跑的已证根因。 |
| R06 / P2 | `tests/acquisition_ui/conftest.py:23–41` 没有主 UI 的生命周期/模态保护。`test_config_path_persistence.py:98` 的 restart 路径调度旧窗口 deleteLater 后马上创建新窗口，未证明旧 owner 已销毁。 | **源码确认的隔离覆盖差异**；实际跨项污染/崩溃待最小复现。兄弟目录已受 `tests/conftest.py` 的外观隔离，不能说完全没有隔离。 |
| R07 / P2 | `tests/acquisition_ui/test_status_bar_text.py:226–238::test_idle_polling_does_not_fill_ring` sleep 后 poll 20 次只检查 ring 为空；不处理任何样本也能满足断言。 | **断言盲区确认**；尚未做错误注入。对应产品路径为 `_polling_mixin.py:132–146`。 |
| R08 / P2 | `tests/test_filters.py:63–68` 的 multirate 只检查两种 fs 下 100 Hz 通带 `std > 0.6`，不足以识别错误固定 fs。`tests/integration/test_head_hdf_realfile.py:15–23` 声称全 NaN 组应丢、量级合理，却未断言该组缺失，幅值只检查大于零。 | **测试目标与 oracle 不匹配**；不是已发现滤波器或 loader 产品 bug。 |
| R09 / P2 | `tests/test_spectrogram.py:158–168` 用两个 500 万点数组测试内存拒绝，输入本体约 80 MB；`signal/spectrogram.py:369,449` 已有可注入的输出预算及分配前检查。 | **可缩小准备成本并增强预算边界的具体机会**；尚未计时。 |
| R10 / P2 | `tests/integration/test_t08_order_cot_e2e.py:5,13` 写死机器路径并未显式关闭 MDF；HDF realfile `:8` 由 `/tmp/head_sample.hdf` 是否存在决定是否读取大样本。 | **源码确认**；执行范围取决于本机残留，资源收尾和真实样本验收口径不明确。 |
| R11 / 待计量 | `test_ultraview_mode_integration.py:796,830` 固定等待加多段手写轮询；`test_inspector_first_show_layout.py:67,126,141` 等待布局。可能改为实际完成条件。 | **候选**；不能机械替换验证 quiet-window 的时间等待。 |

## 3. 不减目标、不减功能的执行合同

1. 每个改动用例登记：原 nodeid、原保护目标/故障、输入场景、关键断言、改后 nodeid、执行 gate、验证证据。测试迁移或拆分必须有逐项映射，不能只用“总数差不多”证明覆盖未减。
2. 不删除用例来缩短时间；不扩大 skip/xfail/slow、不放宽容差、不移除异常路径或参数组合。若重组共享准备，保持每个原场景的独立断言及可定位失败。
3. 默认快速反馈是**选择与本次改动相关的验证范围**；完整集成集合仍然保留。focused PASS 不能替代全套、真实样本、真实性能、Cocoa 或 Windows frozen 结果。
4. 正确性 oracle 尽量采用解析值、明确状态/资源变化、独立参考；不调用被测 helper 生成相同答案。挑已发现盲区做少量错误注入，不建设全仓 mutation 平台。
5. 不共享可变的 session MainWindow/canvas 来省初始化，不删 paint pin、GC 或 filter 守卫换速度，不以每项新进程掩盖同进程污染，不默认开启 UI xdist。
6. 正向异步完成可改为有 deadline 的信号/条件等待；“在一段时间内没有触发”不能替换成立即为真的 waitUntil。保留 150 ms settle、真实 Qt timer 和渲染集成合同。
7. 真实样本缺失可以让可选本地检查明确 skip，但需要它的验收必须标未完成；不能把它转成永不执行的 slow 项。未知失败保留 UNKNOWN，不先调期望值。

## 4. 实施任务与聚焦门禁

### T0 — 建立覆盖账本和小范围成本基线

**Owner：协调者；归属：** 新建覆盖映射/执行说明，临时证据放 `.state/test-quality/`。不先改测试。

- [ ] 接续旧计划，逐项标记已实施、部分实施、待执行，引用当前代码和对应日志；不根据历史勾选推断已通过。
- [ ] 记录 HEAD、相关内容指纹、运行环境、正在运行的 pytest 及 cwd。当前并发实现稳定前不启动集成 gate；不终止他人进程。
- [ ] 对本计划目标生成实际 collection inventory，包含 nodeid、静态 markers 和 collection 阶段 skip；参数展开数与 AST 定义数分列。先 collect-only，不执行全量；fixture/test-body 动态 skip 原因随后续实际 gate 补录，不能声称 collect-only 已获取全部原因。
- [ ] 为 R05/R09/R11 选择短序列，分 setup/call/teardown 汇总累计成本、p50/p95、对象基线；相同环境/负载下重复少量轮次。读取现有 events 时注明快照，不能跨版本直接比较。
- [ ] 制作逐目标覆盖账本，至少覆盖本文 R01–R11 对应合同；不要求为全仓立即写 9306 行人工说明。

**Gate：** 路径/nodeid 有效、旧新目标映射可审查、计时包含 fixture 成本。此任务以盘点和短序列为主，不需要 pre-change full suite。

### T1 — 修复 watchdog 的有界退出和证据真实性（R01–R03）

**Owner：runner agent；归属：** `scripts/run_test_gate.py`、`tests/test_run_test_gate.py`。先修此项，后续测试才使用它。

- [ ] 在临时小项目补先红回归：父先退出子继续；父响应 TERM、子忽略 TERM；后代持有 stdout；CPU 循环；teardown 卡住；用户中断。自测再有独立外层 deadline，不能让被测 runner 成为自己唯一的限时器。
- [ ] 用本次启动的明确进程组/树身份负责清理；父退出不能当作全部后代退出。为输出 reader/EOF 收尾设独立上限；即使无法彻底清理，也须有限退出并标 UNVERIFIED、保留残留证据。禁止按进程名批量 kill，禁止杀其他会话。
- [ ] POSIX 与 Windows 分别定义所有权/清理实现及自测；Windows 未运行时明确待验收，不能凭 POSIX probe 宣称跨平台通过。
- [ ] 失败 report 立即落盘 nodeid/phase/longrepr/captured output；保留“第一项失败、第二项挂住”的首项原因。修正 setup fail/skip 后 teardown 状态，增加 collection 阶段记录；栈转储与终止职责分开。
- [ ] 快照无法获取不能生成“稳定源码已验收”的 PASS；保留实际 pytest 结果，同时将总体证据标 UNVERIFIED。覆盖源码变更、Git 失败和两阶段状态合成。
- [ ] 记录现有 ps/lsof 预检对未知 cwd、子目录和竞争启动的边界；本轮依靠唯一协调者避免重叠。runner checkout 互斥锁列为后续独立候选，若实施须覆盖竞争启动/异常释放；它也不能控制外部直接 pytest，不将该扩展作为本轮提速前置条件。

**Gate：** `tests/test_run_test_gate.py` 的临时项目/专属进程树测试；正常、FAIL、UNVERIFIED、清理和日志均可判定，预检边界写明。不为测试 runner 启动仓库全套。

### T2 — 精准选测与完整验收的明确路由（R04）

**Owner：协调者；归属：** `scripts/test_gate_routes.json`、`scripts/select_test_gate.py`、`tests/test_test_gate_selection.py`（拟建）及执行说明。runner 保持执行职责，避免把所有映射硬塞入 runner。

- [ ] 第一版只映射高频且已确认的 owner：signal/filter/spectrogram、IO/真实文件、Batch、Pin/View/canvas、acquisition、UI kit。显式 source owner → owner tests + 适用 boundary，不靠文件名前缀或 import 图推定全部语义关系。
- [ ] 同时支持指定变更文件、当前 tracked/untracked diff、删除/rename；选测自身测试变更也必须被选中。输出每个测试被选中的原因、未映射路径、建议补充 gate；未知路径不能静默返回“充分覆盖”。
- [ ] shared helper/conftest/pytest 配置变更标宽影响：先跑其基础设施回归，再按实际影响要求稳定集成 gate。没有映射时由协调者检查所属模块并补映射，不随意默认全部或空集合。
- [ ] 提供只输出命令和选择账本的 dry-run。实际节点须 collection 校验；保留根 collector identity 修复和 re-entry 回归，不靠固定参数顺序规避 fixture 缺失。
- [ ] 所有原用例保留在明确验收集合中；默认主套件与 acquisition 仍是串行 fresh 进程。单独报告 slow、真实文件、native/frozen 的适用性、命令与完成状态。
- [ ] 从既有 events 生成慢节点/fixture 阶段汇总，优先定位累计高成本及随轮次增长；超时预算按类别和冷启动证据设置，不能以一律缩短预算冒充提速。

**Gate：** resolver 的合成路径用例覆盖新增/删除/rename/共享fixture/未知路径/跨模块组合；选中节点真实存在；对选定历史改动核对必需 owner/boundary 不漏。`tests/test_conftest_autouse_scope.py` 保留。此任务不跑全套来验证路由器。

| 执行层 | 何时执行 | 覆盖与结果口径 |
| --- | --- | --- |
| focused | 日常每次相关修改 | owner + 明确边界，给选择原因；只对选中范围声称通过 |
| 默认完整集成 | 稳定里程碑、跨目录 fixture、合并/发布要求 | 保留全部默认项；主套件结束后 acquisition 单独进程，唯一协调者执行一次 |
| slow / 实测性能 | 对应性能改动、既定性能验收 | 保留全部既有 slow 场景；显式 `-m slow`，记录环境与数值；调用次数类性能合同仍默认运行 |
| real-file / 平台专项 | 对应格式/算法改动及需该能力的发布验收 | 明确样本身份与平台；缺资源即该项未验收，不把 focused/default PASS 扩大解释 |

### T3 — 降低 fixture 固定成本，保留生命周期防线（R05）

**Owner：fixture agent；归属：** `tests/conftest.py`、`tests/ui/conftest.py`、相关基础设施回归。对共享 conftest 必须独占编辑，等待 Pin/View 任务交接。

- [ ] 先比较纯静态节点与真实 UI 节点的 fixture closure/phase 成本；纯检查用明确分类或窄目录组织避免无关 qapp/ChartStack 成本。若迁移路径，逐项更新 gate/消费者，不留失效命令。
- [ ] `tests/conftest.py` 当前 autouse 会主动 import Qt（`:57`）；如优化中立路径，必须保留“测试 body 首次创建 app”外观恢复回归，不能仅检查 `sys.modules` 后忽略后续创建。
- [ ] GC 合并/跟踪范围缩小必须依据对象生命周期和计时；保留 pin → 合法清理 → DeferredDelete → 外观恢复的实际顺序证据。registry 方案须与全扫描交叉核验，不能只测 registry 自身。
- [ ] filter 判据明确合法长寿命 baseline 和本 item owned 差集，保留 Router/façade 一致性；不能简单把允许数从 1 改 0 而误伤合法 session 对象。

**Gate：** `test_qt_fixture_lifecycle.py`、`test_app_style_isolation.py`、`test_qsettings_isolation.py`、collector re-entry；原静态 ratchet 文件；Pin lifecycle 的真实 filter 节点。短混合序列验证成功/失败 teardown、合法 session 对象、对象数不随轮次增长及同条件阶段成本。不得只凭测试总时长下降合并。

### T4 — 兄弟目录资源收尾、确定性等待和有效断言（R06/R07/R11）

**Owner：UI 测试 agent；归属：** `tests/acquisition_ui/conftest.py`、上述 acquisition/UI layout/integration 用例及必要的低层 helper。`tests/ui/conftest.py` 仍归 T3，不并行修改。

- [ ] 建立 acquisition/ui_kit/GUI tools 的 QWidget、timer、worker、modal、style 保护矩阵。只共用低层 owned-object 工具，不把主程序 ChartStack/MainWindow autouse 全部套入兄弟目录。
- [ ] restart 测试证明旧窗口及 owned producer 已销毁再启动新窗口，保留同文件磁盘持久化 round-trip；通过跨 item 最小 pytest 子工程验证成功/异常路径和合法 session owner。
- [ ] idle polling 使用确定样本/可控 clock；同时断言样本已处理、cards 收到数据、ring 不增长。无样本、丢弃投递、错误写 ring 三类错误必须至少各有一个判别。保留真实 FakeBackend 的独立 owner/integration 覆盖。
- [ ] 只替换等待正向完成的固定 sleep/手写轮询，给出 timeout 时最后状态；Inspector 首次布局仍走真实 show/QSS/singleShot，不强制 layout 来绕过首次展示缺陷。
- [ ] 明确保留 `test_ultraview_feedback_pipeline.py:113–181` 静止期间不重复 present，以及 `test_pg_timedomain_canvas.py:6182–6494` quiet-window 合同。已有有界 `_pump` 只补诊断，不为换写法重构。

**Gate：** `test_status_bar_text.py::test_idle_polling_does_not_fill_ring`、`test_config_path_persistence.py` 对应 restart 节点；`test_ultraview_mode_integration.py` 受改节点、`test_inspector_first_show_layout.py`。涉及 fixture 才追加该目录生命周期回归；acquisition 与主 UI 不混成同一进程。

### T5 — 数值测试提高判别力并缩小无关准备（R08/R09）

**Owner：数值测试 agent；归属：** `tests/test_filters.py`、`tests/test_spectrogram.py`；**不改产品数值算法**。

- [ ] multirate 保留两种真实 fs、通带保护，增加物理截止附近与阻带增益；oracle 来自解析滤波响应，明确有限采样/边缘裁剪的容差依据。固定 fs、直接返回原数据两个局部错误注入必须被捕获。
- [ ] spectrogram 用小输入验证预计输出字节数的预算 `required-1 / required / required+1`；保留默认 64 MB 拒绝合同，可用高 overlap/明确帧数构造远小于 500 万点的越界请求。拒绝应发生在 FFT/大矩阵分配之前。
- [ ] 以受控 spy/替身保证删除预算 guard 的错误注入不会真的导致大分配；`>` 改 `>=` 必须被相等边界捕获。预期帧数/字节数独立推导，避免复制实现自证。
- [ ] 输入缩小前列出保留的 empty/short/nonfinite/dtype/shape/time-alignment 场景，不能因提速遗漏数值边界或改变误差标准。已有精确小样本 FRF 测试无需统一重写。

**Gate：** `tests/test_filters.py`、`tests/test_spectrogram.py`，选定错误注入先红后恢复原实现通过；记录准备内存及阶段耗时。未改产品代码不额外跑全部 signal/GUI suite。

### T6 — 真实文件验收可移植、可追溯（R08/R10）

**Owner：IO 测试 agent；归属：** 两个 `tests/integration/` 文件、窄样本配置/fixture、相关执行说明。与 T5 文件不重叠。

- [ ] 真实文件路径显式输入，记录格式、身份/指纹与适用场景，移除默认机器绝对路径和 `/tmp` 隐式触发；保持原始 COT 整文件二阶邻域判据。MDF 正常/异常均显式 close。
- [ ] HDF 增加全 NaN 组缺失断言；真实幅值/单位 oracle 需先核验样本基准窗口，不能猜常数。样本不可得时此部分保持未验收，不能把正数断言包装为量级正确。
- [ ] 关联已有 `test_head_hdf_loader.py:50–85,238–257` 的分组/NaN/RPM/calibration oracle、`tests/signal/test_order_cot.py` 合成 owner；它们默认必跑且不依赖客户文件。
- [ ] 提供 real-file gate 的明确执行入口和验收负责人/触发条件；配置缺失/错误路径/正确样本分别有明确结果。需要真实样本的 gate 缺数据不能报整体 PASS。

**Gate：** `tests/test_head_hdf.py`、`tests/test_head_hdf_loader.py`、样本调度/资源收尾回归；真实文件 gate 在样本齐全时单独运行。不能用合成结果冒充真实文件通过。

### T7 — 集成验收与可量化交付

**Owner：主协调者，唯一 full-gate owner。**

- [ ] 对照 T0 覆盖账本，所有原目标、关键断言、参数场景均有对应节点和可执行 gate；迁移节点更新全部引用，skip/xfail/slow 清单没有为了提速扩大。
- [ ] T1–T6 focused/boundary 完成后冻结相关源码快照。若实施涉及跨目录 fixture，跑一次默认主套件，再用独立 fresh 进程串行跑 acquisition；先检查正在运行的 pytest，不重叠、不反复重跑同一稳定快照。
- [ ] 使用 T1 修复后的 watchdog；源变化、中断、崩溃、超时、关键快照无法验证均标 UNVERIFIED，不能从已完成的点数推算通过。
- [ ] 对应性能/真实文件/平台专项分别报告。没有采样文件或 Windows/Cocoa 环境时如实保留未验收门禁；本计划本身不触发所有平台全验收。
- [ ] 报告同条件短序列的 setup/call/teardown 累计成本与 p50/p95、对象残留、峰值内存、失败定位信息、前后选择集合。耗时目标在 T0 后制定；不预先承诺“几小时降几分钟”。
- [ ] `git diff --check`、路径/节点/执行说明检查、lesson status。只提交本计划授权的文件（另获提交要求时），不带入 Pin/View 等工作区改动。

## 5. 并行与停止边界

本次 review 已由三个只读 agent 分别审查 runner/路由、UI/fixture、数值/IO，主协调者整合。实施建议顺序为 **T0 → T1 →（T2、T3、T5、T6 按可用槽位排队并行）→ T4 共享 helper 集成 → T7**。T4 的独立用例可提前进行，但 fixture 集成必须等 T3 合同确定。最多使用可用 agent 数，不为凑并行让同一文件多 owner。

协调者拥有配置、路由、覆盖账本与全套 gate；runner agent、fixture agent、数值/IO/UI agent 各自只改分配路径、只跑 focused。共享文件改动串行交接，所有 worker 保留他人修改。并行审查/实施不等于并行执行多个全套 pytest。

发现产品线程、数值算法或渲染本身缺陷时，保留最小失败用例和产品 owner，另立产品修复项；不在测试 fixture 中补偿产品错误。生命周期优化重新触发 native crash 时停止该优化路径，保留证据，不删除触发测试或延长 sleep 继续。

## 6. 第一轮交付与未验证项

第一轮仅新增本文；未改 tests、runner、产品源码、pytest 配置或旧计划。完成源码/提交/既有日志审查、AST 静态盘点，以及 R01 的独立自有进程探针。第一轮没有运行当前树 focused/full suite，没有当前树全绿结论，没有提速比例，没有全仓断言审计完成声明。第二轮新增证据见下文，不回写成第一轮结果。

执行时遵循 project-lessons 的相关隔离/模态/合成样本经验；历史 lesson 的固定文件顺序规避与当前 AGENTS 的 collector 修复合同不一致时，采用当前 AGENTS。已有共享 lesson 状态为 `lesson_required=True`、reason=`test infrastructure hardening introduced no recurring lesson candidate`，本轮未覆盖、清除或推广他人状态；待原任务 owner 处理。本文为 docs-only 交付，验证范围是路径、证据等级、任务归属、覆盖保留合同和 whitespace，不需要为计划文字启动运行时套件。

## 7. 第二轮补审：剩余分区与测试是否真正能报错

补审基线为 `fb27087f409ef484b3aadc30f5fc5219e9d0ed67`，开始和探针后 tracked worktree 均无修改；仍有其他任务的未跟踪文档和文件。开始时未发现正在运行的 pytest；本轮没有发起全套。三个只读 agent 分别负责 Batch/导出/打包、数值/IO、采集/硬件，协调者检查 UI/UI kit、全仓结构筛查和计划整合。

文档收尾时，其他任务开始修改 Pin controller/presentation/overlay 及 `test_pinned_cursor_geometry.py`、`test_pinned_cursor_interaction.py`。已确认这些是并发修改并予以保留；上述盘点数量、Pin 行号和探针结论属于采样时快照，不能视为这些后续改动的验收，执行 U1 前重新定位对应测试符号。

### 7.1 审查范围账本

全仓 548 个 `test_*.py` 均经过 AST 解析和风险模式筛查（定义、重复命名、等待、宽异常、skip/xfail 等）。下表是文件/函数定义数，**不等于所有断言已经人工确认或 pytest items 已经执行**。筛查没有命中不表示文件没有问题；命中也不自动算缺陷。

| 分区 | 文件 / 测试函数定义 | 本轮深入范围与保留结论 |
| --- | --- | --- |
| 根 `tests/` | 144 / 2059 | 数值/IO 分区、Batch/导出/Windows 脚本、采集/Vector/CLI；重点节点列于 R12–R22。未把源字符串 packaging gate 当作 frozen 运行证据。 |
| `tests/ui/` | 333 / 6559 | 条件断言、宽异常、跳过、无显式 assert、重复定义、真实/模拟 DPI、Pin tick、FFT 面板、多选编辑、静态 ratchet fixture 成本。无 assert 命中中包含合法的信号/异常/helper 验证，不机械补 assert。 |
| `tests/ui_kit/` | 21 / 216 | 控件像素/圆角、DPI、layout diagnostics、motion/selection；真实像素/动画分阶段合同保留，不因测试多而折叠为 QSS 文本检查。 |
| `tests/acquisition_ui/` | 34 / 356 | 生命周期、demo 子进程、ReviewModal、录制与交接；与根目录采集相关文件一起审查。 |
| `tests/signal/` | 11 / 110 | FFT 平均帧、channel math、auto NFFT、数值独立 oracle；保留已有解析值与 dtype/shape 边界。 |
| `tests/integration/` | 2 / 2 | 延续 R10，补充真实样本明确执行/资源关闭要求；不重复运行客户文件。 |
| `tests/synthetic/` | 2 / 2 | 随数值/IO 分区检查；不把合成用例等同于真实样本验收。 |
| `tests/perf/` | 1 / 2 | 延续已审的 opt-in pan/envelope 性能合同；未运行大规模 benchmark，未改 slow 策略。 |

全仓同一 Python scope 的重复测试定义筛查发现一处，见 R22。跨测试模块 helper 依赖也应纳入 T2：例如 `tests/ui/test_ultraview_author_multiselect.py:69` 从 `tests/ui/test_ultraview_page.py` 引入 `_Harness`，修改后者可能影响其他测试文件，不能只选择被改文件本身。

### 7.2 新增发现（与 R01–R11 合并使用）

| ID / 优先级 | 证据、保护目标与缺口 | 确认范围 |
| --- | --- | --- |
| R12 / P2，局部 P3 | `tests/ui/test_ultraview_author_multiselect.py:391` 的 `... == 'left' or before_order` 因非空列表而放行错误置底；`:532` 只要求颜色集合变化，不能证明所有选中对象都变橙色。`tests/test_batch_renderer.py:180` 用大写 `NFFT=auto` 搜索 `text.lower()`，负断言恒真。`tests/test_zfd_format.py:189` 的 `or True` 恒真。 | **置底空操作错误注入仍 PASS**；其余表达式源码确认。ZFD 同节点后续完整数组/长度 oracle 很强，不能说其 32-bit count 总体防护失效；该子项 P3。 |
| R13 / P2 | `tests/test_signal_adaptive.py:637–649` 验证 helper 帧数/数组长度，未验证 FFT 实际参与平均的帧；`tests/test_audio_loader.py:42–59,77–91` 仅元数据/长度，未验证音频值；`tests/test_batch_weighting.py:29–49` 只检查低频变小，全零也成立；`tests/test_wwt_export.py::test_cleanroom_auto_resamples_uneven_time_axis` 只查时间轴/summary，漏 Y 值。 | **独立限时探针确认**：不算 FFT 返回同形全零、mono/stereo 静音、A weighting 全零、WWT 重采样全零，对应原测试体均仍 PASS。它们不是完整 fixture 或产品正确性验收。 |
| R14 / P2 | `tests/test_order_analysis.py:101–109` 名为“首批后取消”，实际第二次 token 检查发生在首批计算前；`:125–131` 进度只检查有回调及终值。`:60–85` 内存测试注释帧数与实际 hop 不符，预算随 batch cap 浮动，单点峰值不能证明总帧数增长时内存不线性增长；tracemalloc 异常时未 finally 恢复。 | **取消路径 spy 确认已完成 FFT batch 数为 0**；内存准备/收尾源码确认，未跑大数组 benchmark。按 cap 比例设预算本身可合法，不能把它夸成固定内存上限证明。 |
| R15 / P2 | `tests/test_channel_frame.py:14–15` 的模块级 CAN/cantools skip 会屏蔽无 CAN 前提的 `:218` 中立导入边界；`tests/ui/test_smart_default_weighting.py:139–144` 仍按“API 尚未合入”跳过现已存在的产品接口；`tests/test_batch_weighting.py:42–44` 将包含 weighting 的 TypeError 转为旧集成期 xfail。 | **源码确认**；Batch TypeError 错误注入实际被降级为 xfail。合法第三方依赖缺失仍可 skip，已完成产品 API 消失/出错应失败。 |
| R16 / P2 | `tests/ui/test_fft_cursor_layout.py:232–249,262–263` 允许 awaiting_space 直接 return，无法证明本应有空间的场景显示了面板；`test_pinned_cursor_geometry.py:492,521–523` 保存 ticks 却只检查后续非空，未比较“刻度未改”。`tests/acquisition_ui/test_review_handoff.py:654` 用 `isVisible() or result()==0`，错误 reject 后仍可能满足“仍打开”。 | **真实 Qt fixture 下强制 awaiting_space=True，50 通道几何节点仍 1 passed**。tick/archive 是源码盲区；save-only 另有 `test_review_handoff.py:887–908` 强可见性 guard，不能宣称所有关闭路径都无保护。 |
| R17 / P2 | `tests/test_vector_xcp_backend.py:183–200,234–269,284–300,314–344` start→assert→stop，失败跳过 stop；`tests/test_batch_render_qt.py:1087,1121,1166,1265` 的 daemon worker 超时直接 fail，未以 finally 保证收尾，GUI processEvents 阻塞也不受循环内 deadline 控制。 | **Vector fake 探针确认**：断言失败时 thread_alive=True/runtime_closed=False，探针 finally stop 后 False/True。Batch 异常残留是源码风险，未故意挂住 Qt dispatch。 |
| R18 / P2 | `tests/acquisition_ui/conftest.py:30–35` 仅 patch 当前解释器 Path.home；`test_demo_smoke.py:24–35` 子进程未隔离用户路径，模块入口会构造窗口并沿 `window.py:177,377`、`thresholds.py:139–155` 读取真实用户配置。 | **调用链源码确认**，未启动此 child、未读写开发者设置。父进程 monkeypatch 不跨 subprocess。 |
| R19 / P2 | `tests/test_vector_xcp_backend.py:128–135` 的 non-Windows 拒绝测试没固定平台，在 Windows 落入 requires ifdata 的不同异常；`tests/ui/test_ultraview_card_actions.py:237–250` 尝试 QWindow.setDevicePixelRatio，宽异常转 skip。当前 PyQt5 的 QWindow 没有此方法，故无法通过该方式验证 DPR2。 | **平台 fake 探针确认 ValueError 分支**；本机运行时 `hasattr(QWindow, 'setDevicePixelRatio') == False`。未做 Windows/native DPI 验收。 |
| R20 / P2 | `tests/test_acquisition_capture_backends.py:123` 是 `A or not A`，后续只检查当前模块文本，不能证明传递/动态导入安全。`tests/acquisition_ui/test_review_handoff.py:67–81` 的“一秒 fake”连续 poll 而不推进时间，`:177–201` 只检查 missing names，可能零样本满足。 | **源码确认**；现有 static native import guard 不能替代 runtime 禁导入探针；channel schema 不等于已录到数据。对应 T4 的场景建立与 T2 的边界选测。 |
| R21 / 待计量 | `tests/test_frozen_batch_render_smoke.py:26–65,95–170,173–219` 重复生成同一组 6 PNG；`tests/test_verify_ultraview_visuals.py:92–126,146–159,185–201` 多次完整 generate（工具至少 20 个 required shots）；`tests/test_batch_time_group_acceptance.py:25–27` 的 manifest 拒绝场景反复先跑真实 CSV/PNG 生成。 | **重复准备源码确认**，尚未测收益。可共享释放 Qt owner 后的只读产物/事实，损坏场景另复制；入口、public renderer、验证器、布局操作、group mode/resume 与 fresh-process 合同仍分别保留，不合成一个无法定位的大测试。 |
| R23 / P2 | `tests/test_wwt_export.py:24–27` 的 autouse 在 trailer 缺失时跳过整个文件，连 `:205–209` 专门验证缺 trailer 报错的节点也不执行；相关 trailer/template 是受版本管理资源。 | **源码与 tracked asset 归属确认**。仓库资源破损不能被视为普通可选环境缺失；本轮未删除或改动资源来复现。 |
| R22 / P3 | `tests/ui/test_selection_slide_probe.py:299,404` 两次同名 test 函数，后定义覆盖前定义；内容目前相同。 | **全仓同 scope AST 筛查确认**。当前没有丢失独特断言，但定义计数不等于执行数，未来编辑第一处不会生效。 |

R10 的范围另外扩到 `tests/test_mat_format.py:16–21,35–83` 的客户 MAT 正常路径，以及 `tests/test_wwt_format.py:143–156,272–283` 的本机目录/glob：是否有样本以及新增多少 `.wwt` 会改变默认测试工作量。保留真实锚点，同时把普通数值/时间轴 oracle 做成可移植合成输入；既有 `tests/zfd_corpus.py` 的样本 manifest/hash/required 规则可以参考，不再造一个大框架。

### 7.3 补充执行任务：并入 T0–T6，全部在 T7 前完成

以下均是**后续实施项**，本轮没有执行修复。原 owner/gate 保留，新增路径按表分配，不能因此扩大为整目录回归。

“全部在 T7 前完成”包含候选项的证据判定：R21 等待计量机会必须先测量，若收益不足或会破坏隔离，记录保持现状的理由即可，不强制为凑优化改动而共享 fixture 或重构工具。

| 子任务 / 接入原任务 | 文件 owner 与实施要求 | 保留目标的精确验收 |
| --- | --- | --- |
| U1 断言逻辑与场景建立 → T4 | UI agent：`test_ultraview_author_multiselect.py`、`test_fft_cursor_layout.py`、`test_pinned_cursor_geometry.py`；采集 agent：`test_review_handoff.py`。先断言输入/控件/数据实际进入目标场景，再检查输出。 | 置底前后完整 ID 序列、每个对象橙色及单条 history；充足空间必须可见，空间不足独立验证不显示及恢复；tick 比较稳定布局下实际文本/位置；archive 后真实可见/可点击且无 rejected。空操作、始终 awaiting、部分对象未改色、archive 后 reject 均须失败。 |
| U2 数值输出 oracle → T5/T6 | 数值 agent：`test_signal_adaptive.py`；IO agent：`test_audio_loader.py`、`test_wwt_export.py`；Batch agent：`test_batch_weighting.py`。各文件只有一个 owner。 | 平均 FFT 用不同帧幅值/窗口起点证明每帧参与且尾帧规则正确；WAV 按 PCM16 量化误差及精确帧数验证声道值/身份，编码器延迟另管；A 加权同时检查低频响应与 1kHz 非零/参考增益；WWT 用独立插值期望验证真实写读后的 Y，不能以产品 resampler 生成期望。 |
| U3 取消、进度、内存观测 → T5 | 数值 agent 独占 `tests/test_order_analysis.py`。保留早期取消，新增已完成 batch 后取消；小 cap/多批小输入检验进度和后续批。tracemalloc 进入前状态与异常后恢复明确。 | spy 至少一批完成，再取消且不再处理后续批，不发伪完成进度；两个总帧数下最大批规模/增长关系正确。原高 NFFT/大输入实测节点保留，输入规模不得悄悄缩水。固定 cap/绝对预算若是产品合同，应独立基准，不能跟被测 cap 一起漂移。 |
| U4 skip、导入与收集完整性 → T2/T5/T6 | IO agent：`test_channel_frame.py`、`test_wwt_export.py` 的资产 fixture（与 U2 同 owner）；UI agent：`test_smart_default_weighting.py`、`test_selection_slide_probe.py`；Batch agent：`test_batch_weighting.py`、`test_batch_renderer.py`；采集 agent：`test_acquisition_capture_backends.py`。 | 中立导入节点在模拟缺 CAN/cantools 环境仍被收集执行；真正依赖 BLF 的节点保留明确 skip。已存在产品 API 的缺失/TypeError 必须失败。tracked WWT 资源缺失明确 fail，独立输入校验/缺资源错误路径仍执行；用替身路径模拟，不删除真实资产。fresh 子进程禁止指定 optional imports，直接/传递错误导入均可判别。修正 NFFT 大小写负断言，重复命名消除遮蔽并保留原可执行合同；不能把相同断言多跑一遍算新增覆盖。 |
| U5 异常路径资源与子进程隔离 → T3/T4 | 采集 agent：`test_vector_xcp_backend.py`、`tests/acquisition_ui/test_demo_smoke.py` 及窄 helper；Batch agent：`test_batch_render_qt.py`。共享 conftest 仍由 fixture agent 统一接入。 | start 前注册 function-scope finalizer；断言失败/超时后线程、runtime、补丁生命周期收束，再执行一个后续节点证明无污染。无法协作停止的 dispatch 故障用独立有外层限时的进程，禁止 terminate QThread。demo child 用临时 config/cache/home 解析路径；空/合法/损坏临时配置三种入口仍跑，不能读取真实 store 做验证。 |
| U6 平台与实际 DPR → T4/T6 | 采集 agent：Vector 平台节点；UI agent：`test_ultraview_card_actions.py`。固定 non-Windows 分支输入，同时保留 Windows fake runtime 正常路径。DPR 必须在 fresh QApplication 前配置，读取实际值。 | darwin/linux 拒绝路径和 win32 fake 支持路径分别执行，不加 Windows skip。DPR1/DPR2 子进程确证实际 ratio，再核对控件几何/像素；若平台不支持标该专项未验收，不捕获所有异常当环境问题。现有 pixmap DPR 单测保留，不能代替真实控件路径。 |
| U7 确定样本与录制往返 → T4 | 采集 agent：Review handoff helper、capture backend/controller 对应 clock 节点。用确定 clock 定义“一秒”的样本数/时间点；UI-only 检查可用不可变输入，真实录制链路继续真实 writer/MF4/loader。 | 断言 rx/write count、每通道非空、明确时间范围；no-op poll/空写必须失败。保留 CLI fake→真实 MF4、UI record→stop→review 的真实计时器端到端合同；不是全改 fake clock。 |
| U8 准备成本与样本集合 → T0/T6 | Batch agent：`test_frozen_batch_render_smoke.py`、`test_verify_ultraview_visuals.py`、`test_batch_time_group_acceptance.py`；IO agent：MAT/WWT corpus 节点；协调者更新选择账本。 | 先测准备成本，再复用不可变产物；manifest 每项 deep copy，损坏文件用独立目录副本并正确重绑定绝对路径、checksum/mtime。保留全部 PNG 类型、shots、布局操作、group modes、deleted-image resume、入口/验证器/中文墨迹 oracle；public renderer monkeypatch 与需 fresh init 的节点独立。只读事实共享前释放 Qt owner，不跨运行缓存。真实样本 manifest 覆盖原场景，额外语料显式探索，不让 glob 改变默认门禁。 |

R12 的 ZFD 字节字段子项由 IO agent 接入 T6：按格式已知 offset 验证 4 字节 count 与 payload 边界；保留原 65535/65536/65537/131072 参数及 3,608,000 点长记录。现有数组/长度强 oracle 不能被新的静态字节检查替换。

**聚焦 gate 补充清单：**

- U1：上述多选、FFT 三个几何节点、Pin tick 节点、archive/save-only reachability；仅跑对应节点及其错误注入，正常/缺空间两种场景分清。
- U2：`test_non_tail_count_matches_averaged_fft_loop`、auto NFFT 的相邻计算合同、audio mono/stereo、Batch weighting、WWT uneven-time round-trip。保留已有单位/dB reference/错误输入节点。
- U3：order cancel/progress/memory 对应节点及 tracing 异常恢复探针；大输入节点只在该 owner 合适的稳定阶段执行一次，不为每次调整小 oracle 重跑。
- U4：原 ChannelFrame/import/weighting/static ratchet 节点，加小型“依赖缺失但中立节点仍执行”的 collection/运行子工程；不卸载本机依赖。WWT 资源存在/受控缺失时分别核验资产合同与 missing-trailer 节点，输入错误检查不被连带 skip。ZFD 仍执行上述原参数化节点。
- U5：Vector fake 生命周期和失败 teardown 子工程；四个 Batch GUI dispatch 节点及受限故障进程；demo child 的路径证明。只有触及共享 fixture 时才补 collector/settings/lifetime 守卫。
- U6/U7：Vector non-Windows 拒绝、Windows fake runtime；真实 ratio 验证后的 card center 节点；expected channels、record-stop-review、CLI MF4 round-trip。
- U8：上述三个产物文件原节点及全部 manifest mutation 场景，MAT 数值/时间轴与 WWT corpus 映射；确认单节点/有意义反序仍可独立准备且无数据污染。source smoke 既然硬断言 offscreen，其 child 环境就须显式指定 offscreen，不能用 setdefault 继承 cocoa 后自相矛盾。Cocoa/Windows 专项另行保留；若确需工具新增窄 scenario 入口，单列工具 owner 和原完整矩阵回归，不顺手改造 harness。

**T2 路由补充合同：** 测试模块自身被其他测试导入为 helper 时，改动该模块须纳入受影响 consumers，支持多层 test-helper 引用，不能只选被改 `test_*.py`。先明确现有真实依赖及映射，不因 163 条跨测试 import 命中就批量拆所有 helper。相同源扫描/只读解析结果只有在冻结相关文件指纹且不跨 monkeypatch/mutation 场景时才能复用；禁止缓存过期源码让 ratchet 假绿。

### 7.4 本轮实际验证与未验证边界

1. **错误注入识别力证据：** z-order 置底空操作直接测试体仍通过；FFT 面板强制 awaiting_space 的真实 Qt/pytest 单节点结果为 `1 passed, 2 warnings in 1.64s`（40 秒外层上限）。这个 PASS 是测试盲区的证据，不能写成面板几何验收通过。
2. **其他 agent 的独立限时探针：** 平均 FFT 不计算、audio mono/stereo 全零、Batch weighting 全零、WWT 重采样全零、额外 NFFT=auto 文案均未被对应原测试体发现；weighting TypeError 变 xfail；order 取消时已完成 batch 数 0。均在独立进程/内存替换中完成，未修改源文件；直接调用测试体不等同于完整 fixture 验收。
3. **资源/平台证据：** Vector fake 的断言失败后线程仍活/runtime 未关，finally 清理后均恢复；模拟 win32 时原 non-Windows 用例落入 ValueError。没有加载 native runtime 或访问硬件。QWindow API 查询确认当前无 setDevicePixelRatio 方法；未声称已验证实际 DPR2。
4. **小型阶段观测：** `test_multi_file_state_matches_frozen_whitelist`、`test_ratchet_rejects_a_newly_escaped_attribute`、`test_lambda_connect_total_matches_whitelist_sum` 经 fresh pytest（35 秒外层上限）为 `3 passed in 1.50s`。三项都存在 qapp，继承 `_restore_app_style_after_test`、modal、settings、ChartStack 和 MainWindow 相关 fixture。合计 setup 0.3441s、call 1.0342s、teardown 0.0868s；单项 teardown 约 0.028–0.030s。**单次观测不是受控前后性能对比，不能外推到全套或声称所有慢跑来自 GC；本组 call 扫描本身也有明显成本。**
5. **保留的优质用例：** 小型解析 FRF、seeded SciPy parity、channel math 的数值/dtype/shape、ZFD 全数组/整数边界、Qt 真实像素/中文墨迹检查均有独立目标；不为了统一形式或缩短报表删改。

本轮补充了 12 组新发现（R12–R23）及 U1–U8，合并后共 23 组发现。完成的是全目录风险模式筛查和所列重点节点审查/探针；**未完成全仓 9306 个函数的逐条语义审计、未运行全套、未做优化后的时间对比，也没有平台全验收结论**。例如大型 `test_batch_runner.py`、manifest/recipe/output/SSAA 文件中未列明的节点仅做风险筛查，不能写成逐项语义审查通过。这些限制不阻止按上述明确 owner 实施已确认问题；不能在计划状态里把它们勾成已完成。

本轮只更新本文，未修改测试、产品代码、运行器或 pytest 配置；未干预其他任务、未提交。文档检查包括引用/节点有效性、任务归属和覆盖保留合同、`git diff --check`。共享 lesson 要求仍保持原状态；这次发现按现有隔离/断言/生命周期约定处理，没有另造 lesson 或覆盖他人状态。
