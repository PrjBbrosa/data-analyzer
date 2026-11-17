# MF4 原生采样提交后收尾 Plan

日期：2026-11-18。状态：**文档就绪，实施待执行；当前产品候选仍有阻断，不切普通打开默认、不发版。**

执行合同：[收尾 Spec](../specs/2026-11-18-mf4-native-completion-spec.md)。Supersedes：[2026-11-17 原生采样 Plan](2026-11-17-mf4-native-sampling-plan.md)的后续派工顺序及状态；继承其 M0–M6 完整交付目标，不重建已实现能力。将[导入恢复补充 Plan](2026-11-17-import-recovery-review-followup-plan.md) H01–H06 的剩余工作并入本计划，避免另起冲突施工；几何/重试合同仍归[导入恢复 Plan](2026-11-17-import-budget-and-dialog-recovery-plan.md)。旧文件保持历史。

本轮只审查并创建新文档，产品/持久测试未修改；没有启动实施agent、提交/推送/发布。下列owner是未来职责划分，不是已派发或已完成的工作。

## 1. 结论、起点与接收账本

native审查基线 `398e16ed6d534f590084c14a50b3905956161ba6`，版本v8.4.8。`c848fdb1..398e16ed`确有且仅有 `63619b1c`、`0bde6286` 两个非merge实现提交；它们已经分别经PR #43/#44合并。文档收尾时合入UltraView PR #41，当时HEAD为 `67c64205ee603587098b4e4dc8faea9831010833`；它未修native缺口，新增几何/测试成果必须保留，证据快照漂移按Spec §2记录。不能将“两次提交”当作两个很小的修改，也不能将它们当作B0–B6全部完成。随后导入恢复followup `2c08c890` 合入，最终基线为 `ad373c7c68a78e06d16b49c2e75d4e380ae21992`。其H01/H02/H04/H05及Batch wrapper修复已经接收，见Spec §2.1；不得重新实施已完成任务。实际范围、来源和当前入口见Spec §1。

| 原阶段 / 缺口 | 接收决定 | 本次后续位置 |
| --- | --- | --- |
| B0证据 | 已有旧反例和新持久测试；本轮早期152/9 focused观察；最新接收followup的183/73定向记录并重跑生产探针，不累加为全套 | C0只补新反例，不跑全套基线 |
| B1 / N01,N09 | 十进制网格、halo、enum共享已有成果；MDF2/3标量和逻辑目录已随followup修复，完整产品链仍缺 | C1，不重写store/transport |
| B2 / N04,N05 | 邻点/时频选区旧反例已修；RPM质量、精度、prepared Fs、DSP边缘/预算仍缺 | C2–C4 |
| B3 / N02 | GUI多处已接通，Runner wrapper已修且本轮复验成功，配对/RPM/Custom-X未完整 | C3/C4 |
| B4 / N03,N06 | offscreen旧反例通过，保持；Cocoa/生命周期/滤波/Pin完整矩阵未验 | C4/C7，不再重做已修renderer |
| B5 / F08,F09,N07,N08,H02–H05 | 项目policy/Replay及滤波helper已有代码，实际产品/数学/资源未完成 | C1接收、C2–C6补余项 |
| B6 / R01,H06 | 无完整平台、性能、稳定集成门禁 | C7唯一联合验收 |
| H01 | followup已清理终态引用、weakref定向通过 | C6保留已有成果，只补共存资源及未覆盖生命周期 |

Spec L01–L11为当前问题清单，旧N/F/H编号保留可追溯映射。已有 `CSER TTR/` 不动；11月17日补充文档现已由followup工作流提交，本轮不改写；执行时重新读当前HEAD/dirty/owner，不按本快照覆盖新改动。

## 2. 文件归属与依赖

集成负责人唯一管理共享合同、入口政策、验收账本和全套。若用户之后要求agent实施，可以按下表分工；没有该实施授权时只读。每位执行者保留其他人的改动，不能通过整文件回退接收成果。

| Owner | 唯一可编辑责任范围 | 冲突交接 |
| --- | --- | --- |
| IO/逻辑数据 | `mf4_analyzer/io/native_signal_store.py`、`signal_access.py`、`file_data.py`、`mdf_reader.py`、`channel_edit_log.py`；必要transport/adapter/预算模块 | C1接收现有read_signal/逻辑DTO与质量语义；C6预算接入时同一owner回收文件 |
| DSP准备 | `mf4_analyzer/analysis_signal_prepare.py`；必要的中立DSP helper | C2接收已修整数精度，维护单/双路质量/滤波/预检；C6接reservation必须串行，不由另一个worker重写 |
| Batch | `mf4_analyzer/batch.py`、`batch_compute.py`、`batch_preprocess.py`、`batch_frf.py`、`batch_export_size.py`、BatchSheet薄接线 | C3复用冻结准备合同；`batch_output.py`归产品导出owner，协议修改交接 |
| GUI分析/画布 | `ui/main_window/`四类分析mixin与coordinator、analysis_context/range、`ui/pg_canvas/`及相关bindings/cursor | C4只修实际缺口；`window.py`的薄接线由集成负责人合入，避免和C5导出冲突 |
| 产品/导出/恢复 | 集成负责人持有 `window.py`、`_project_io_mixin.py`、`import_coordinator.py`、`ui/project_io.py`、编辑器、`batch_output.py`、Replay UI/backend、hints/quickref/帮助 | C4的window接线→C5项目/导出→C6导入生命周期顺序整合；几何/QSS仅经H06新证据才改 |

测试默认随对应owner。`tests/ui/test_native_signal_consumers.py`、`tests/ui/test_mf4_native_product_path.py`、`tests/test_mf4_native_fidelity.py` 由集成负责人唯一编辑，各owner交接用例后串行合入；共同运行不等于共同编辑。

```text
C0 接收与新反例 → C1 已修逻辑/兼容接收 → C2 准备与DSP合同
                                             ├→ C3 Batch真实路径 ─┐
                                             └→ C4 GUI分析/显示 ─┤
                                   → C5 项目/编辑/导出/Replay → C6 资源与热路径
                                   → C7 真实平台/稳定快照/默认及发布决定
```

C3/C4只在C2接口冻结且文件/测试不重叠后可以并行；C1、C2的设计探索可以只读提前进行。H01已有修复与定向证据，不再派同一红测/修复；仅在新生命周期反例成立时由原owner扩展。新发现涉及共享合同则先停止依赖编辑并由集成负责人统一修订，不能各写一套fallback。

## 3. C0：接收并固化当前反例

Owner：集成负责人协调各owner测试。不先改产品、不跑全套基线。

1. 记录HEAD、tracked/untracked、产品与测试hash、现有运行中的任务/pytest及cwd；接收两个commit后的实际证据。沿Spec §2复用同快照结果，版本/源变化后只补受影响项。
2. 将仍失败的L02/L03/L04–L07输入与结果固化为owner红测；L01/L08基础项/L09/H01接收现有持久回归，禁止回退制造红测。临时 `.state/native-followup-20261118/probe.py` 可辅助，但Spec自含输入，不能要求别人持有本机脚本。
3. 反例分层：完整Runner接收(L01)、生产方法/DTO加DSP(L02–L05)、独立频率oracle(L06)、真实xlsx回读(L07)、配方/取数/转换(L08)、真实broker版本对照(L09)。不要把stub host升级为完整MainWindow交互证据。
4. 消费清单搜索必须包含 `fd_or_fail`、frame helper、adapter、callback与wrapper，而不只搜字面 `fd.data`。登记普通/分组Batch、项目policy、Replay UI/API的真实政策，不重复切换已有native入口。
5. 确认N03/N06/十进制Fs/邻点回归仍在，已有绿测不恢复旧代码制造红测。H01复用已完成终态weakref；H06接收已有Cocoa工作窗/真实重试，余下完整生命周期、R01缺样本或平台记UNKNOWN，不妨碍独立修复。

Exit：每个L项有唯一owner、输入、预期、当前证据类别与测试落点。账本初放`.state`，最终验收在 `docs/analyzer/verify/` 写正式记录。无进度百分比替代证据。

## 4. C1：接收已修逻辑取数及MDF版本兼容（L08/H02/H03、L09/H04）

Owner：IO/逻辑数据；编辑器接线由产品owner接收。此阶段以接收为主：followup已实现以下逻辑取数/shape/版本合同，已有 `tests/ui/test_native_derived_followup.py`、`tests/test_native_precision_routes.py` 及reader/读取回归。只补明确缺失边界，不重写已修代码、不重复整组绿测。保留native store、十进制采样和transport。

- 接收并冻结已有“值/实际轴/quality/segment/表示/单位/revision/依赖”的完整逻辑表示；暂存abs继续derivative必须使用原0.25s间隔而非abs值。应用后目录、read_signal、继续派生读取同一逻辑身份；删除/隐藏不从store复活，跨源同名不合并。
- 项目保存只存可复算配方与身份；源变化保持悬挂/未应用。空/单点/短/非有限、失效位、复位和shape冲突沿Spec拒绝或分段，不按较短长度裁切。
- 接收已验证的MDF2.14/3.30/4.10按实际版本解析类型/转换/失效位与读前计费；identity、线性`2*raw+3`，整数/浮点、空/单点/多点经真实broker验证。不删除安全检查、不回退legacy、不为通过抬预算。读取保存文件必须用asammdf返回的实际路径。
- 对已修的N01补必要边界接收：source dtype/ULP、声明与实际冲突、非零/大原点、整数时轴溢出/回退、空/单点不伪造Fs。只修可复现合同缺口，不反复改已通过的正常10/100/1000/1024Hz路径。

Focused：`tests/test_signal_access.py`、`tests/test_native_signal_store.py`、`tests/test_channel_edit_log.py`、`tests/test_mdf_native_reader.py`、`tests/test_mdf_reader_safety.py`、`tests/test_source_adapters.py`；真实broker用 `tests/test_import_transport.py` 及集成owner持有的product_path。编辑器/项目实际链留C5。

Boundary：`tests/test_native_import_boundaries.py`、`tests/test_signal_no_gui_import.py`；修改import seam再加 `tests/test_import_packaging.py`、`tests/test_packaging_imports.py`。Exit：两级/三级派生时间和值正确、应用后可读、各MDF版本raw/physical/quality独立oracle通过、源不变，相关L功能项通过；产品完整链仍不得提前勾选。

## 5. C2：准备层质量、预算、有效Fs与DSP（L04/L05/L06/L08-H05）

Owner：DSP准备。数值修改一律先红测/独立oracle；先冻结Spec §4的具体滤波设计、边缘支持和支持比率，再实现。不要只改 `stopband_db=60` 或扩大容差。

1. 保留已有中立 `numeric_precision.py`、policy `m4-same-axis-2` 与跨率精度拒绝红绿证据，不复制helper。单/双路统一shape、空/短/非有限、时间单调/segment、validity和精度验证；explicit align不能绕过。请求范围和必要halo先确定，合法选段不被段外无效污染。不能精确float64表示的整数在有损转换前拒绝，精确大偶数通过。
2. 预算覆盖双侧、hash/mask、padding/FFT工作区、grid与输出；禁止 `del byte_limit`。先准入再分配，低预算用allocation spy证明滤波/DSP未启动，不用大数组耗尽机器。C6接入应用级reservation前保留同一预检接口。
3. 明确prepared实际Fs及来源Fs字段；向GUI/Batch交接同一DTO，policy_version与cache事实包含新语义/设计。不在消费者各算一套目标Fs。
4. F08按Spec通带/阻带扫频：4000→500Hz的300/510Hz反例必过，新增非有利初相位、通带幅值、2/4/8倍率、短段/非零origin/边缘。F09补H1/H2、多正弦/增益/延迟、两侧高低率互换、范围裁切和不支持组合。不拿GUI/Batch共享同一算法的parity代替独立oracle。
5. legacy用户滤波行为保持；若旧filter达不到新抗混叠合同，在中立准备owner内定义经证明的设计。现有 `batch_preprocess` 与新prepare的顺序/halo差异先证明再统一，不机械去重。

Focused：`tests/test_analysis_signal_prepare.py`、`tests/test_mf4_native_fidelity.py`、`tests/test_frf.py`、`tests/test_frf_scipy_parity.py`、`tests/test_batch_preprocess.py`、`tests/test_db_reference.py`、`tests/test_batch_weighting.py`，只选实际受影响owner；Boundary：`tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py`。

Exit：1字节pair预算拒绝且无重分配、选区内部NaN/失效不再ready、整数精度反例通过、已声明支持范围内F08/F09真实oracle通过。未验证的比率/时移明确unsupported且整体目标差异可见；产品接线仍待C3/C4。

## 6. C3：Batch完整入口与时间关系（L01/L02/L03/L04）

Owner：Batch；复用C1/C2合同，所有任务终态经 `_RunReporter`。

- 接收已修 `_run_sequential` /分组wrapper的 `_source_has_channel`，只补未覆盖resume/probe。直接传已加载native FileData的真实 `BatchRunner.run` 必须成功，不能只测 `_run_one`。路径probe/load的native政策以最终产品计划接线，普通默认在C7前不扩大启用。
- 修正RPM tuple解包；所有RPM选择分支都核对真实时间、quality、单位和覆盖，幅值变化不得改变RPM对齐。含跨源legacy控制，不能继续范围外np.interp端点填充。
- Custom-X不丢 `_x_time`：等长不同/不重叠时钟拒绝或显式对齐；固化L03最新完整Runner已复现的不重叠时钟请求。保留Batch已把失效点转NaN的修复，并验证质量/segment事实不能在适配或float转换中消失；时域原始输出与频谱对Fs/点数要求分开。
- Batch FRF使用prepared实际Fs，包括plan、compute、facts及导出。`original`、`target_fs/decimate`按Spec顺序执行同一准备合同，不仅改事实标签而继续旧采样分支。
- 输出尺寸使用实际通道/任务facts；逻辑拆分source身份、同名通道、取消/失败后继续、输出命名/恢复保持。

Focused：`tests/test_batch_runner.py`、`tests/test_batch_loader_dispatch.py`、`tests/test_batch_time_group_acceptance.py`、`tests/test_batch_export_size.py`、`tests/test_batch_preprocess.py`、`tests/test_batch_frf_pairing.py`、`tests/test_batch_frf_export.py`。Boundary：`tests/test_batch_run_reporter.py`、`tests/test_batch_render_import_boundary.py`；Sheet实际改动再跑 `tests/ui/test_batch_runner_thread.py` 与UI import/ownership。

Exit：普通/分组的time/FFT/Order/FRF及Custom-X请求通过真实Runner，错误输入准确单次失败，parity加绝对oracle成立；不得把blocked/failed当作“安全拒绝所以实现完成”。

## 7. C4：GUI分析、质量和图表闭环（L03/L04/L11；接收N03–N06）

Owner：GUI分析/画布，window薄接线由集成负责人合入。

- Order的neighbor halo携带validity/segment：失效999不得计算；Order-vs-Time、手动RPM、单位/倍率、同/跨源、真实越界分别测试。保留已修邻点结果。
- FRF两种高低率方向从真实按钮到作业完成，窗长/频率轴用目标Fs。把显式“对齐后计算”意图接到真正控件/请求/持久化；未支持组合说明原因，不自动启用。预览、范围编辑和 `materialize=False` 不执行完整滤波/重采样。
- FFT/时频选区、pane缓存、比较B面、源切换/未知Fs的显示事实准确，不沿用上一个通道Fs；统一错误原因，不能吞成源缺失。时间滤波companion保留quality、不跨gap。
- N03/N06原测试不重做算法，补首次/刷新/resize/恢复/隐藏重显/双Y/overlay/重名/滤波/Pin/移除/源关闭的实际路径。Cocoa验证几何/像素，offscreen只证明数据与交互合同。
- 显式计算语义保持：编辑/预览/切View/项目恢复不重新计算，已应用结果按source revision与view/pane归属，不迟到写入。

Focused分owner运行：`tests/ui/test_order_multirate_rpm.py`、`tests/ui/test_fft_time_coordinator.py`、`tests/ui/test_frf_main_window.py`、`tests/ui/test_analysis_time_isolation.py`、`tests/ui/test_analysis_explicit_refresh_contract.py`、`tests/ui/test_analysis_cache_pinning.py`；画布用 `tests/ui/test_pg_cursor_placement.py`、`tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_time_filter_overlay.py`，共享consumer测试由集成负责人补入。

Boundary：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`、实际画布变更的 `tests/ui/test_pg_canvas_backref_invariants.py`。不新增跨mixin状态白名单，不改ink/AA与quiet window门槛。

Exit：实际操作可完成合法FFT/时频/Order/FRF请求、质量错误准确反馈、图表数值与marker正确；尚缺Cocoa/Windows项保持UNKNOWN交C7。

## 8. C5：项目、编辑、导出与Replay（L07/L08/L09/L11）

Owner：产品/导出/恢复；C1逻辑取数和C4 window接线交接后实施。

- 保留已有schema6 policy分派。真实编辑器“暂存多级→应用→勾选/分析→保存→重开→继续派生/导出”验证C1成果；旧schema4/5 legacy复现、显式迁移预览/取消、缺源/源变化/配方失败保持reference-only及可行动状态。
- `_do_export_excel`接到已有可靠中立writer或其最小共用实现，不在window保留第二套精度/分片算法。真实xlsx回读 `2**53+3` 原值（文本），长表混合dtype不先提升浮点；行上限/分片、原record/segment/quality、选定派生与失败通道状态全部覆盖。WWT兼容范围明确拒绝，不能假公共轴。
- Replay UI已经native，修复/验收其现有行为；直接API仍legacy的差异必须成为明确policy而非意外。重复timestamp/单点/多率/失效/复位segment的选择与播放、取消/父关闭经真实UI验证，不只调source_from_native。MDF2/3依赖C1修复。
- hints、quickref及主帮助/相关指南同步真正可用操作与限制；清理源码中“Replay仍legacy”“cross-rate永远unsupported”等过期注释，不改历史文档记录。

Focused：`tests/test_mf4_native_export.py`、`tests/test_channel_edit_log.py`、`tests/ui/test_channel_editor_recipes.py`、`tests/ui/test_channel_editor_export.py`、`tests/ui/test_mf4_native_project_migration.py`、`tests/ui/test_project_session.py`、`tests/ui/test_ultraview_project_session.py`、`tests/test_acquisition_capture_backends.py`、`tests/test_help_content.py`；`tests/acquisition_ui/test_replay_tab.py`单独新进程。Boundary按实际接线选neutral/UI import、ownership、packaging。

Exit：真实保存与回读、逻辑派生重开、Replay各入口政策和segment闭环；没有静默精度损失、漏选通道或共同时轴伪装。保持普通打开默认，C5不授权发布。

## 9. C6：应用级资源、释放和预览成本（L05/L10/H01）

Owner：集成负责人协调同一IO/DSP/产品owner；共享文件串行交接，不另建预算层或重写用户分析缓存。

1. 将C2预检接入既有任务/源生命周期，计入所有存活源、已绑定结果、准备及输出同时量。缓存采用按字节LRU，不靠淘汰绑定结果或raw腾预算；超预算给缩范围/关闭源建议，不截断数据。
2. H01 drain后清理及成功/失败/取消/session失效weakref证据已接收；只对未覆盖的重试放弃/宿主退出/共存任务补回归，bound transform宿主和kwargs大数组须可释放。活动worker与有效重试上下文不提前销毁；完成记录不留大call。关闭宿主后再GC、队列下一请求和退出子进程一并验证。
3. 用调用计数/分配/profile定位 `prepare_signal`整段hash、FRF轻量查询仍DSP、双游标扫描、Replay时钟tuple与GUI导出物化。复用stable revision/索引/切片/worker，不在鼠标或元数据预览中重算完整hash/重采样；必要精度扫描在worker与预算内进行。
4. 20轮导入/关闭、计算/取消、项目替换，强引用/任务/缓存释放和RSS高水位分开判定。此处证明结构与生命周期，真实Cocoa/Windows耗时归C7；小fixture快不等于性能通过。

Focused：`tests/test_import_limits.py`、`tests/test_import_resource_preflight.py`、`tests/test_analysis_signal_prepare.py`、`tests/ui/test_import_coordinator.py`、`tests/ui/test_batch_dbc_parent_close_subprocess.py`、`tests/ui/test_analysis_cache_pinning.py`、`tests/ui/test_timedomain_hotpath_perf.py`；实际Replay接线变更仍独立进程。Boundary复用neutral/UI ownership/import，不新增通用全套。

Exit：资源低预算红测、共存计费、各终态释放及预览不完整DSP通过；真实性能未测项仍UNKNOWN。如果固定预算确实不可达，记录瓶颈和needs revision，不私自提高预算。

## 10. C7：真实平台、恢复余项与唯一联合放行

Owner：唯一集成/全套负责人。前置C1–C6的功能/结构门禁，接收已通过N/F/H，不重复修复。

- 按Spec §6逐项跑真实入口与旧格式/混合来源矩阵；Cocoa时域/游标/计算/项目/取消及原Spec §8性能门槛，record输入、机器、DPR、源码/输出hash及原始时序。不改ink阈值解决性能不达标。
- R01用事故样本固定memory/output、真实adapter→broker→transport→GUI注册、完整目录/逐点oracle、父/worker同时RSS、临时盘和心跳；979/927/84等历史数按物理身份对账，不硬编码数量替代保真。图2缺样本单列UNKNOWN。
- H06接收已有Cocoa短框/Batch/UltraView几何与真实fresh-limits重试；补完整P02父销毁/迟到/队列/状态栏/退出，定位执行记录中的混合Cocoa命令停滞。只有受影响证据需重验，不重复调QSS。Windows新鲜Full/Lite windowed包的导入、Replay适用路径、取消/资源/性能与几何单独验，100%及125%或150%按原恢复合同。
- 最后对包含拟启用点的稳定候选执行唯一集成里程碑全套。先检查pytest进程/cwd及同快照权威结果；主套 `--ignore=tests/acquisition_ui` 完成后，再新进程跑 `tests/acquisition_ui`，不能并发。记录前后HEAD/dirty/hash，漂移/崩溃/中断是UNVERIFIED。不能拿默认关闭的旧快照冒充启用后验收。
- 必需项未通过，不切普通打开/拖入/最近/Batch默认，不做版本发布。已启用的Replay与schema6恢复也必须受测，不能以普通默认legacy证明全产品安全。若用户另定受限交付范围，先列精确文件/行为与兼容/平台证据；不能整树发版后补验收。

Exit：正式验收记录映射L01–L11、继承N01–N09/F01–F12、H01–H06及G/P/E/R/W，所有必需项有PASS证据，无未解决P1/P2。不得用xfail/skip或缺平台当完成；达到适用门禁就结束，不无理由重跑全套。

## 11. 交付和本轮文档检查

实施交付：必要代码、持久红绿回归、独立数值oracle、完整产品路径记录、资源/性能/Cocoa/Windows证据、更新后的用户说明与剩余状态。不按提交数量或阶段名称判断完成；每个提交/交接说明它关闭哪些L/F/H以及哪些仍未验。

开发回退只针对明确启用点/变更单元，保留导入安全、十进制率、halo、质量断线与marker已有修复；不reset工作区、不改源数据、不整批回滚两个提交。关闭native入口不自动消除共享代码回归。

本轮新增且仅新增本Plan与配套Spec，旧文档不改。核对全文、Supersedes链、路径/链接、问题→owner→测试→退出映射，以及新文件 `git diff --no-index --check /dev/null <文件>`；不因文档本身运行测试。Spec记录早期152/9观察、接收的183/73 followup记录及最终HEAD生产探针；来源和快照分开，不累加，不重复已通过的相同owner。检查lesson状态，沿用native安全、gap/identity、真实caller和新日期文档规则，无需重复创建已有教训。
