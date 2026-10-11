# 分析模块对比视图 Follow-up Plan

- 日期：2026-10-11（Asia/Shanghai）。
- 状态：**核心修复已实施；综合验收 PARTIAL，用户原场景与 Windows frozen 尚未验证。**
- 规范：[Follow-up Spec](../specs/2026-10-11-analysis-comparison-timedomain-parity-followup-spec.md)。
- 诊断基线：`4667dd06c98d624b6d5e5663eeb69e4b8911e60e` 加当前工作区已有改动；诊断阶段只新增文档与 `.state`；实施阶段修改清单与独立证据见验证报告。
- 目标：四分析模块达到时域的对比使用方式——完整独立的 View、一个共享工具栏、准确焦点与右键、半色标签和无重复 chrome 的图面。
- 执行方式：按用户最新授权分三路并行：page/card 共享动作、tabbar 颜色与菜单、MainWindow 参数/右键；主执行者负责 stack/Inspector/帮助和集成。文件所有权互斥，共享接口先约定，任务依赖仍保持；不安排默认全套 baseline，不改 DSP、采样率、版本号或历史文档状态。

## 1. 修复前诊断交付

| 项目 | 当前结果 |
| --- | --- |
| F1 重复 toolbar / hint | 四模块均复现；截图检查可见，影响图面高度和对齐 |
| F2 共享操作错侧 | peer 点击聚焦后，Home 调用 host；共享标注真实状态 `[True, False]` |
| F3 模式/历史目标枚举 | Zoom 后 `[zoom, pan]`；历史遗漏从相同 peer 枚举链推导，待补真实步进用例 |
| F4/F5 颜色 | host partner color=None；peer 焦点使用 host 红色，时域使用 peer 绿色 |
| F6 card 枚举 | peer 不在 stack._all_cards；需按消费者逐个关闭缺口 |
| U1 参数不独立 | View 内 panes 共享 params 是现存设计；跨 View 点击并修改窗函数已证明独立，其他字段仍须矩阵验证 |
| U2 右键无响应 | 普通模式四模块均可弹菜单；标注模式空白右键被删除手势消费。用户实际路径仍需定位 |

现有 comparison 回归 `40 passed, 221 warnings in 8.16s`。生产样式观察探针 offscreen `5 passed, 8 warnings in 6.02s`；独立 Cocoa `5 passed, 8 warnings in 7.03s`。观察通过只表示采集完成，**不是修复通过**。完整位置、原理和证据边界见 spec §1。

最终稳定 focused 集成 **252 passed**；生产 Cocoa 四模块真实计算/导出/窄窗 **4 passed**；输入与 bridge Cocoa **58 passed**；Pin最终 Cocoa **4 passed**。这些独立运行有覆盖交集，不相加为总数。

未勾选的复合验收项表示仍有未覆盖子项，具体已完成部分与剩余条件见验证报告；不将本轮源码修复宣称为全平台发布验收。

## 2. T0 — 将发现冻结为真实入口回归

依赖：无。目标：确认当前实施快照及具体失败；不重跑已经稳定且未受新增修改影响的绿测。

- [ ] 记录当前 HEAD、dirty 文件清单和相关 owner/tests 指纹；保留已有版本、FRF、色阶与帮助改动。查清用户实际使用的入口、点击区域和标注模式；没有补充时同时覆盖两种入口，U2 保留 UNKNOWN。
- [x] 在新增 `tests/ui/test_analysis_comparison_interaction_contract.py` 将 F1–F5 观察值改为正确行为断言：只一排 toolbar、Home/标注目标 peer、两侧 Zoom 一致、host 半色/peer 色条正确。
- [x] 复用既有 `tests/ui` fixture，真实 MainWindow + 合成双来源 + 不同参数/颜色，进入模块并完成懒创建。按 Qt ownership 清理，不从临时目录绕过 QSettings fixture。
- [x] 使用真实 viewport press/release、QAction/按钮和 combo 信号，不仅直接调用 focus 方法；Home 可局部 spy 验证目标，另以真实相机变化证明效果。
- [x] 建立 U1 两条对照：旧窗格共享参数；独立 View 修改窗函数仅 B 改变。右键分别覆盖主图/切片/FRF 三行、标注开/关、标签菜单，并检查菜单动作能执行。
- [x] 记录历史两个对齐 node 的当前结果；仅在可重现且属本次 pane 布局范围时纳入 T4，不用旧数值当当前失败。

Owner：新测试文件及现有 `test_analysis_view_comparison_regressions.py` 的小范围扩展；不改产品。Focused：仅新增 node 与需要复现的 `test_analysis_section_page.py` 对齐 node。完成门：失败原因是目标缺陷，非数据/fixture/定时等待/Qt teardown；已有可用路径作为正对照保留。

## 3. T1 — 统一 card 接入和操作目标（F1/F2/F3/F6）

依赖：T0。Owner：`analysis_section_page.py`、`chart_stack/stack.py`；只有 provider 边界不足时才局部修改 `chart_stack/cards.py` / `toolbar.py`。

- [x] 在 page 建立清晰的 focused card、全部可见 cards 与指定 View cards 接口，兼容已有 host-only getter。解析完整 View/pane 身份，不再分别维护 nav/annotation/options 三套目标条件。
- [x] 主侧第二 pane 和 peer 全部 panes 使用同一小范围 card 接入/拆除流程：隐藏内部 toolbar、设置 provider、连接 highlight、继承当前工具模式、抑制通用提示带。
- [ ] Home、annotation、clear、options、frequency cursor 的共享入口都解析焦点；焦点切换及时刷新 checked/highlight/可用状态。保留程序化 local setter，不使后台 restore 被重定向到焦点。
- [ ] 模式双向传播覆盖 host↔peer 和 2×2；工具广播只面向当前同 section 的可见 cards。Back/Forward 复用已有 history group，各自历史不混合；验证手势后立即 Back、无历史一侧、pending timer、开启轴联动时恢复。
- [x] 分别审查 `_all_cards()` 的消费者：全局刻度回显等纳入 peer；只捕获 host/单 View 的消费者继续显式限定，不通过改变 `peek_cards()` 默认范围一刀切。
- [x] 清除对话框在打开时固定 target/token；关闭、替换、切 View 后不能误清新的目标。
- [x] 退出对比、删除 peer、窗口 teardown 时停止并解绑属于该 card 的 timer/signal；不销毁共享 toolbar，不改变结果 cache pin 所有权。

Focused：新交互合同 tests；`tests/ui/test_toolbar_section_contract.py` 的 annotation/mouse/history/export 相关 node；`tests/ui/test_analysis_section_page.py`；`tests/ui/test_split_focus_routing.py` 的时域对照。Boundary：`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`。如果涉及 MainWindow 才追加 ownership gate。

完成门：AC1/AC2；四模块 peer 真实操作改变自身、另一侧不变；模式统一但参数不串；无图内额外 toolbar。不能只隐藏重复栏就交付。

## 4. T2 — 独立参数入口、焦点事务与右键闭环（U1/U2）

依赖：T1。Owner：`analysis_section_page.py`、`view_tabbar.py`、`_analysis_mixin.py` 既有目标/捕获函数；仅在新增失败证明必要时改各 section owner。

- [x] 主菜单明确独立 View 对比；旧“添加对比窗格”改为“添加同参数窗格”，说明共享算法参数、独立来源/时间。保留旧 project schema 和数据，不静默搬移到新 View。
- [x] 保证菜单中添加/关闭内部 pane 明确带目标 View；目前 host-only 入口不得在 peer 焦点下用模糊“当前”描述。保持与既有动态 pane 回归兼容。
- [x] 焦点切换统一执行旧目标输入 flush/capture→新 target→控件/facts/按钮投影；旧目标与新目标的 View id 不因同 pane index 混同。
- [ ] 各模块至少覆盖一个计算参数和一个显示参数，再补专项：FFT weighting/dB reference；FFT-time 段长/overlap、色图/手动色阶；Order 算法/RPM 来源和阶次范围；FRF estimator/I-O、幅值/相位/相干显示。来源使用 `(fid, channel)`。
- [ ] 预设直接编辑/应用/恢复、范围 full/custom、失焦未提交输入与真实 save/reopen 独立；display-only 改动不提交 DSP，旧完成不能覆盖新请求或另一侧 facts。
- [x] 普通右键从真实 viewport 进入，检查打开及执行目标，不仅调用 `raiseContextMenu()`。修复焦点/模式回显后重测用户路径；若仍失败，记录 filter、overlay、popup、异常链证据再修 owning boundary。
- [ ] 标注开/关、右键删除命中/空白、Escape 退出按 spec 分支验证。未证实用户路径时，不把已知标注手势直接当成回归 bug；不借机改变时域全局手势。
- [x] 清楚显示 Inspector 当前 View/pane；复用上下文标题，不另加数据画布工具排。

Focused：新交互合同与两个现有 comparison 文件；`tests/ui/test_analysis_view_bridge.py`、`tests/ui/test_analysis_source_scope.py` 中相关节点；真实保存用 `tests/ui/test_project_session.py` 对比相关节点；参数专项仅跑触及的 owner。Boundary：`tests/ui/test_main_window_state_ownership.py`、信号连接 gate。完成门：AC3/AC4；U1 两种语义可辨，跨 View 参数矩阵独立；U2 逐入口填 PASS/FAIL/UNKNOWN，不能一项通过覆盖所有菜单。

## 5. T3 — 标签半色、焦点颜色与管理状态（F4/F5）

依赖：T1/T2 的稳定目标接口。Owner：`view_tabbar.py`、`analysis_section_page.py`、`analysis_comparison.py` 与现有关系变化接线。

- [x] 为分析 tabbar 注入只读 host→peer/焦点投影，复用时域 `_paint_tab_swatch()`。不要把分析关系同时写入 ViewManager._split_pairs。
- [x] host 色块左 host/右 peer；peer 本身实色；焦点条从所属 View 取色。展示关系、悬停、active host 与实际 focus 分开处理。
- [x] 开始/结束/恢复/替换对比，以及任一侧改色、改名、重排、删除后刷新标签与溢出列表；关系解析用 view_id。
- [x] 点击已显示 peer 标签只转焦点，不制造反向关系；结束对比恢复 host 投影，不串参数。不能因半色实现而改变这些既有行为。
- [x] DPR 1/2、不同 View 色、窄窗口、溢出情况下用实际渲染检查两半颜色、3 px 焦点条及无边框缩进。

Focused：`tests/ui/test_view_tabbar.py`、`tests/ui/test_view_tabbar_mount.py` 相关 node、新合同 tests、comparison 关系恢复 tests。Boundary：若改 QSS 跑 `tests/ui_kit/test_qss_border_shorthand.py`；必要 MainWindow 接线跑 ownership。完成门：AC5，source getter 与像素均证明正确，不能只有“存在 partner_color 字段”。

## 6. T4 — 布局、生命周期、导出与后台横展

依赖：T1–T3。Owner：既有 page/stack/comparison owner；新增失败归入对应局部模块，不进行广泛重构。

- [ ] 四模块×1+1、1+2、2+1、2+2，宽窗/窄窗/展开/返回/用户拖动比例；删除重复 chrome 后检查主图、FFT 预览、热图切片、FRF 三行实际几何。
- [x] 两个历史对齐缺口只有 T0 在当前树复现才修；记录它们与额外 toolbar 引起的错位是否同因。修 owning layout，不放宽误差或固定窗口尺寸遮盖问题。
- [ ] 反复开关、替换 peer、host/peer 重新增删 pane、View 删除/重排、源卸载、关闭全部、项目替换，检验 binding/连接/定时器/Qt wrapper 清理。
- [x] 阻塞或迟到的任务仍归 dispatch View/pane，完成不得改变当前 Inspector/facts；两侧均有缓存时切焦点/对比开关不重算。
- [x] FFT/FRF 共享游标控制、真实 P 键的 peer 来源归属、close/reopen 保留记录已验证；修复新 peer canvas 首次挂载未恢复记录。常规缓存重画保留未捕获的 live pin，不重建 pin 系统。像素与长期生命周期限制见验证报告。
- [ ] 共享 Save/Copy 同一组合范围且无工具栏；真实文件和剪贴图路径用固定数据/几何比较像素并检查已知读数区域。单 View/UltraView 抓图不得混 peer；不同 pane 数目不丢图。
- [x] 跨 View 轴/色阶默认关闭；兼容时联动、尺度/参考值改变时解除，保留旧修复，尤其不碰工作区正在进行的手动色阶意图方案。

Focused：comparison 两文件、新合同 tests；`test_pinned_cursor_interaction.py` / `test_pinned_cursor_lifecycle.py` / `test_pinned_cursor_capture.py` 的对比相关节点；`test_analysis_section_page.py` 的布局节点；实际改动涉及颜色才跑 `test_heatmap_color_state_integration.py` 对应节点。Boundary：按修改范围触发 import/ownership/lambda；只有动 pg_canvas host collaborator 才跑 `test_pg_canvas_backref_invariants.py`。

完成门：AC6/AC7；测试失败逐项归因，既有未修问题保持可见，不以 skip/xfail 或扩大 whitelist 关闭。

## 7. T5 — 帮助、原生验收与交付

依赖：T1–T4。

- [x] 同步 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`；必要时同步四分析指南和用户指南相关交互段落。说明独立 View 对比、旧同参数窗格、焦点目标与工具模式/轴联动差异，不改版本号。
- [ ] 在生产字体/QSS 的 Cocoa 原生窗口使用实际有结果数据做交互：A/B 参数明显不同；两侧轮流焦点→调参/显示→Home/标注/清除→右键→游标→复制保存→结束/重开→项目重开。
- [ ] 对照时域完整走同类步骤。截图/几何证明只有一排共享 toolbar、半色标签、焦点颜色正确及无错位；本轮空态/合成观察截图不能替代此验收。
- [ ] 用户实际报错项目和步骤独立验收；未取得就标 UNKNOWN，不把合成 Cocoa 写成用户原场景已修。
- [ ] Windows 使用重新构建的目标 Full/Lite frozen 包做前台操作验证；未跑则明确 UNKNOWN。源码 import/build 检查不替代包内右键和布局验证。
- [x] 对 AC1–AC8 填测试节点、数据、HEAD/dirty 指纹和平台结果；输出当前修复结果、残留失败、未运行 gate。
- [x] `git diff --check`，范围审查，lesson status；不提交其他会话的修改。用户未请求 commit/push 时不执行。

Focused：`tests/ui/test_hints.py`、`tests/test_help_content.py` 相关合同与本波实际影响节点。文案检查不新增镜像措辞测试。

## 8. 验证成本与执行规则

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本任务新增或受影响的 owner nodes> -q
```

- 每个任务先跑新增失败节点，再跑该 owner 的相关既有节点，最后跑适用 boundary。依赖未变且已经通过的门禁不重复跑。
- 正式新测试放 `tests/ui/`；本轮 `.state` 观察探针仅作诊断参考，不作为永久测试依赖，不提交截图/日志。
- 不默认运行全量 `tests/ui` 或全仓。本 follow-up 在已有 owner 内接线修复时，focused + boundary + 原生即可；只有实际扩大成跨状态/持久化架构变更、发布/合并验收或用户明确要求，才重新说明 full gate 的必要性。
- 若 full gate 被触发，由主执行者独占；先检查运行中的 pytest 及 cwd，保存前后 HEAD 与源指纹；主套件 `--ignore=tests/acquisition_ui` 完成后另进程顺序运行 acquisition UI。源码期间变化、超时、崩溃均标 UNVERIFIED。
- Cocoa、用户原场景、Windows frozen 各自独立；可以提交明确标记 partial 的修复，但不能把未运行平台写成已完成。

## 9. 追踪矩阵与完成定义

| 发现 | 实施任务 | 验收 |
| --- | --- | --- |
| F1 重复 chrome | T1、T4 | AC1、AC6 |
| F2 操作错侧 | T1、T2 | AC2、AC3 |
| F3 广播/历史遗漏 | T1、T4 | AC2、AC6 |
| F4 半色标签 | T3 | AC5 |
| F5 焦点颜色 | T3 | AC5 |
| F6 可见 card 枚举 | T1、T4 | AC6、AC7 |
| U1 参数语义和字段矩阵 | T2 | AC3 |
| U2 右键用户路径 | T0、T2、T5 | AC4、AC8 |

代码完成要求 F1–F6 对应正确行为断言通过、U1 合同清楚且数据不串写、U2 普通路径和标注分支有真实事件证据；用户报告尚未完整复现时明确列剩余条件。产品验收还要求 AC8 的平台状态真实填写。不得用此前 40 项通过或新观察探针的 `5 passed` 代替修复验收。

执行结果：[实施验证](../verify/2026-10-11-analysis-comparison-timedomain-parity.md)。文档自身只做路径、引用、状态一致性与 whitespace 检查；产品代码运行 focused/boundary 和 Cocoa 验收，未运行全套。新增编辑器提交及延迟显示刷新 lesson；既有 pane-local sources 和视觉验证规则继续适用。
