# 两波审查问题优化计划

日期：2026-09-16。状态：**待执行**。依据：[审查报告](../reviews/2026-09-16-two-wave-review.md)。基线为 `b0b3fcf7`，另有本轮 8.2.5 版本与文档同步。

## 目标与范围

修复 5 项已确认问题：旧图覆盖下的输入错位、字体故障兜底缺口、快速重定向画面跳变、None 候选反复重建、lambda 边界失败。按单协调者顺序实施；本计划本身不表示这些修复已完成。

保留数值、复合来源身份、View/Pane 参数、缓存 pin、坐标恢复、150 ms quiet timer、300 ms/0 px 视觉参数及现有导出语义。FFT/时频/阶次/FRF 和双 Pane 不扩大动效启用范围。版本已同步，本计划不再重复 bump，也不自动提交或发布。

## T0 — 固定待修快照与红证据

Owner：审查探针、对应 owner 的测试文件；临时证据放 `.state/review-825/` 或新的关联目录。

1. 检查当前 HEAD 和 dirty scope，确认两个提交及版本同步仍在；保留其他改动。
2. 将审查探针中的 F1–F4 最小复现转为 owner 测试，先确认失败；F5 已有确定性失败用例，无需另造测试。
3. 明确 Qt 对象所有权、隔离 QSettings/图标缓存、关闭计时器和 deferred deletes；Cocoa 像素与 offscreen 断言分别记录。

门：只跑新增红测试和 F5 的现有边界测试；不做通用全量基线。文档本身只查链接、引用、范围和 `git diff --check`，无额外 runtime gate。

## T1 — 图面输入与呈现失效（F1，优先）

Owner：`mf4_analyzer/ui/chart_stack/page_transition.py`、`stack.py`；已有 View/画布 owner 仅提供必要失效通知，禁止新增跨 mixin 状态簇。

1. 呈现 owner 区分目标未完成自然 paint、目标已就绪与空闲。现有 `is_pending()` 在 arm_target 后为 False，不能拿它直接作为“已就绪”判断。
2. pending 时仅限制被覆盖的图面输入；View/Section 导航、取消、窗口关闭继续工作。不要保存并重放过期鼠标事件。
3. ready 后首次图面输入先撤层、释放暂存图像，再让原事件处理一次。覆盖单/双游标、标注、拖动/滚轮以及有焦点时的键盘图面操作；不能拦截整窗快捷键。
4. 目标 View 被删除或替换、切分区、来源变化或重绘、窗口隐藏/失活、resize/DPR 变化时让旧呈现失效。复用原业务信号与 canvas generation；呈现 finished 不提交业务。
5. 清理自然 paint 的临时连接和 UltraView deferred capture；避免已取消 token 被迟到回执重新启用。

聚焦门：`tests/ui/test_page_transition.py`、`test_page_transition_integration.py`、`test_view_switch_reentrancy.py`、`test_split_routing.py`、`test_ultraview_capture.py` 的受影响节点。新测试必须使用实际命中控件和完整输入序列，不能只检查透明属性。

边界门：`test_main_window_state_ownership.py`、`test_pg_canvas_backref_invariants.py`（若触及 collaborator）、`test_no_lambda_signal_connections.py`。真实 Cocoa 验证旧图覆盖时无错图取点、ready 后原事件恰好一次。

验收：所有输入命中当前可读图面；合法业务提交次数与 Off 一致；取消后暂存字节和临时等待连接归零；程序恢复保持直接终态。

## T2 — 快速重定向保留真实可见图面（F3）

Owner：同一 `PageTransitionController` / `ChartStack`；依赖 T1 的失效和输入状态。

1. 单图片 + 实时目标路径中，新的 source 必须含用户实际看到的 A/B 完整合成。审查 `begin_page_transition` 已取得的端点是否可直接使用，禁止再次选用仅含透明 A 的 overlay snapshot。
2. 首选复用一次合格捕获；若不能满足成本或目标有效性，则取消到真实终态，不能引入每帧抓图或固定延迟 ready。
3. 保持重定向后的 source 不作为 B 的忠实 UltraView 预览；仅直接离开端点可复用，混合图必须走原有正确捕获路径。
4. 覆盖真实生产调用 `accept_target(token)` 不传 pixmap 的路径，以及空目标、反向和连续重定向；双图片测试作为补充。

聚焦门：`test_page_transition.py`、`test_page_transition_integration.py`、`test_ultraview_capture.py` 相关节点。用不同颜色/图案 A/B/C 验证重定向第一帧与前帧连续，并验证最终图面是 C。

原生门：Cocoa 20 次连点/反向，记录自然 paint、捕获次数与成本、暂存峰值和结束释放。禁止把单张 retained bytes 当作包含临时副本的峰值内存。

验收：无 B 分量突然丢失，无 A/C 提前混合；最多一组过渡，无排队和稳态自发刷新。

## T3 — 补齐已知字体资源故障兜底（F2）

Owner：`mf4_analyzer/ui_kit/icons.py`，必要时 `stylesheet.py`；沿用现有随包资源与 diagnostics。

1. 新增 Qt 字体注册返回 -1、字体资源文件读取失败的故障注入；使用隔离空缓存并验证 14 个兜底资源有效。
2. 在 qtawesome 生成边界捕获准确的已知字体/IO异常，逐项回退到有效 PNG 并节流记录。未知图标名/程序错误、缺失随包资源仍应显式失败。
3. 健康缓存仍不重写；现有缓存不可写、保存 False、损坏 PNG 路径继续通过。
4. 样式实际渲染下拉箭头和勾号；另列其他直接 qtawesome 控件的启动限制，不把 QSS helper 的恢复能力扩大描述为全局无字体运行保证。

聚焦门：`tests/ui_kit/test_icon_cache.py`、`test_stylesheet_parses.py`；`tests/test_packaging_imports.py`、`test_windows_runtime_dependencies.py`。仅当资源/打包代码变化时额外跑相关 build-script 节点。

验收：已知字体加载失败时 QSS 安装得到有效 PNG 路径；编程错误不被吞；Windows Full/Lite 的故障注入独立验收。

## T4 — 按 Qt 语义比较候选角色（F4）

Owner：`mf4_analyzer/ui_kit/widgets/searchable_combo.py`；FRF/Order 保留来源投影职责。

1. 对 None/无效 QVariant 采用与 Qt model 一致的表示；同时覆盖空字符串 tooltip 等 Qt 不存储的值，避免比较模型永远不会持有的 role。
2. 保留候选顺序、复合身份、显示文本及额外有效 role 的变化检测；不要去掉所有 role 检查来换取 no-op。
3. FRF 输入/输出与 Order RPM 相同列表刷新不 clear/add，但仍应用各目标 View 的选中状态；None 与缺失来源占位都要 round-trip。

聚焦门：`tests/ui/test_searchable_combo.py`、`test_analysis_source_scope.py`、`test_frf_main_window.py`、`test_analysis_multiview_integration.py` 的候选/来源节点。

验收：第二次相同完整列表替换返回 False、无 rowsRemoved/rowsInserted；合法变化重建一次；popup 搜索、选中和来源身份正确，无 phantom 默认来源或计算提交。

## T5 — 修复信号接线并集成验收（F5）

Owner：`mf4_analyzer/ui/chart_stack/stack.py`；同一协调者汇总验收。

1. 用兼容信号参数的绑定方法替换新增 lambda，保留取消后的 ready fence 清理；不提高 shrink-only 白名单。
2. 运行两项 `tests/ui/test_no_lambda_signal_connections.py`，以及 T1/T2 相关关闭/取消用例。
3. T1–T4 完成后对最终稳定快照执行受影响 owner 与相应边界门一次；同一未变更的通过用例不反复运行。
4. 核对 8.2.5 版本、帮助更新、Windows Full/Lite 默认名和项目元数据测试。新交互文案如有变化，同步 `ui/hints.py`、`ui/quickref.py`。
5. macOS Cocoa 前台和 Windows 源码/Full/Lite 分开验收；100/125/150/200% 与跨屏、大小数据分别记录。没有平台/负载证据时收紧该路径准入或标 UNKNOWN，不能仅凭 `section == time` 推广已有小样本测量。
6. 只有最终发布/合并验收确有需要才安排一次完整 gate：先查同 checkout 的 pytest，固定前后源码指纹，主套件排除 `tests/acquisition_ui` 后顺序另跑 acquisition_ui；禁止并发全量。

## 完成标准

- F1–F5 均有修复前失败、修复后通过的定向证据，原行为/边界门无新增失败。
- 页面过渡输入、重定向、失效、自然 paint 与 UltraView 捕获形成闭合测试；数值/范围/来源不因动效改变。
- 版本与文档一致；最终报告逐项标明已修、已测、平台 UNKNOWN，不能把版本同步叫作无 bug 发布。
- 检查 lesson status；优先复用既有输入/Qt 生命周期/资源异常规则，有新的耐久规律才追加 lesson。`git diff --check` 通过，临时探针与图片留 `.state/`。
