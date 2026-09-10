# TraceLab 选中背景滑动推广 Implementation Plan

> **For agentic workers:** 执行时使用 `superpowers:executing-plans` 逐任务完成。默认单执行者顺序推进；本计划不授权自动派生 agent。任务以 checkbox 跟踪，只有获得实施授权后勾选。

**Goal:** 在 Spec P1 控件中接入主导航 400 ms、紧凑选择 300 ms 的背景滑动，保留即时业务状态和现有控件几何。

**Architecture:** 扩展现有 ValueDriver 的可选 easing；一个 ui_kit SelectionIndicator 负责背景和几何。原 Toolbar / Batch / combo / chart-card owner 继续拥有真实状态，并在用户激活入口显式控制是否动画。

**Tech Stack:** 当前项目 PyQt5、Qt 5、pytest/pytest-qt、生产 QSS；HTML 仅作曲线参考，不引入 WebView。

日期：2026-09-10。状态：**仅文档，未执行**。合同：[Spec](../specs/2026-09-10-selection-slide-rollout-spec.md)。

## 1. 执行范围和前置条件

- 当前请求只写文档；未来“按 plan 执行”执行 T0–T6 的 P1 范围。热图、View/Board、UltraView 筛选、采集、刻度预设和独立开关均不属于本次实施。
- 不改 DSP、数据、项目 schema、MainWindow 状态簇、图卡绘图/settle 时点；不新增用户偏好入口。不要将旧试验 Spec 的样板任务重做一遍。
- 保留当前在途修改：`ui/compute_progress.py`、`ui/widgets/channel_config_bar.py`、`ui_kit/widgets/searchable_combo.py`、对应 progress 测试、lessons 文件与其他未跟踪文件；实施时重新检查，以上仅调查时点记录。
- 不自动提交/推送，不创建新 worktree 除非确有隔离必要。相同 owner 测试在源码未变化时复用结果，不反复跑基线。

依赖：`T0 → T1 → T2 → T3 → T4 → T5 → T6`。虽然接入区域部分独立，共享呈现接口由同一执行者先冻结。

## 2. 文件归属

| 任务 | 创建/修改 | 职责 |
| --- | --- | --- |
| T1 | 修改 `mf4_analyzer/ui_kit/motion.py`；新建 `mf4_analyzer/ui_kit/widgets/selection_indicator.py` | 新 token、独立曲线、共享呈现 owner |
| T2 | 修改 `mf4_analyzer/ui_kit/widgets/segmented_choice.py` | 迁移已有底板、用户/程序更新区分、保持公开 API |
| T3 | 修改 `mf4_analyzer/ui/toolbar.py`、`mf4_analyzer/ui/drawers/batch/method_buttons.py` 中 MethodButtonGroup | N1/N2 五选一激活与样式 |
| T4 | 修改 Spec B1–B6 所列创建点，含 method_buttons.py 动态参数表单 | 显式开启生产实例；程序联动与恢复归位 |
| T5 | 修改 `mf4_analyzer/ui/chart_stack/cards.py`；必要的组局部规则在 `mf4_analyzer/ui_kit/style.qss` | C1/C2 接入；焦点目标与 toolbar 几何 |
| T6 | 新建 `scripts/probe_selection_slide.py`、`tests/ui/test_selection_slide_probe.py`、验证报告 | 第一批原生证据与门禁归档 |

T1/T2/T3/T5 仅在确实需要抑制双重 checked 背景时修改 style.qss 的对应 owner 规则。共享 helper 不导入 `mf4_analyzer.ui`。现有 `_SelectionPill` 的算法迁移后只保留一个实现；如存在实际私有 seam 消费者，可保留窄 re-export，不复制逻辑。

## 3. T0 — 冻结调查和聚焦基线

- [ ] 运行 `git status --short`、`git branch --show-current`、`git rev-parse HEAD`，记录目标文件 SHA-256 到 `.state/selection-slide-rollout/source-before.json`。排除生成文件，保存相关 dirty diff 作为来源说明。
- [ ] 阅读 Spec 全文、当前 AGENTS、相关 lessons：`qt-composite-disabled-cues-follow-effective-state.md`、`binary-batch-combos-prefer-segmented-choice.md`。不加载整个 lessons corpus。
- [ ] 核对主 Toolbar 的 `_wire/_set_mode`、Batch 的 `_on_button_clicked_from_click/set_method`、combo 的 clicked/currentIndexChanged/sync、图卡的 set_plot_mode/set_cursor_mode 及 `_frequency_cursor_target`。记录用户与程序入口、已有信号次数，尤其同值 Batch 显式 set 仍发 methodChanged。
- [ ] 阅读各任务现有测试，运行该任务将触及的聚焦基线；T0 不跑全套、整个 tests/ui 或原生 GUI。执行环境统一为 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q <本任务测试文件>`。

退出：无未解释的 owner/入口歧义；基线失败先分类为在途问题或本任务问题，不能把已知失败当通过。

## 4. T1 — 可复用底板与独立曲线

**测试：** 修改 `tests/ui_kit/test_motion.py`；新建 `tests/ui_kit/test_selection_indicator.py`。

- [ ] 先写失败测试：新曲线在 25%/50% 时接近 Spec 的位移；普通 driver 默认 OutCubic 不变；二/三/五按钮的中间 rect、无目标、禁用与 deleteLater 合同。使用明确 parent、qtbot，禁止永久 sleep。
- [ ] 为 motion.py 添加下列接口增量；`ValueDriver.__init__(owner, *, on_value=None, easing=None)` 用传入曲线的副本，未传保持原 EASING。

```python
DURATION_MS["selection_navigation"] = 400
DURATION_MS["selection_control"] = 300

def selection_easing():
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(0.22, 0.75), QPointF(0.20, 1.00), QPointF(1.00, 1.00)
    )
    return curve
```

- [ ] 新建不可变 `SelectionIndicatorStyle(fill, border, disabled_fill, disabled_border, radius)` 与 Spec §4 的 `SelectionIndicator` 接口。复用已有底板 painter；host 是 QObject parent，按钮 rect 映射到 host，底板 lower、按钮在上。helper 只接呈现事件，不接业务激活。
- [ ] `follow(button, animate=False)` 验证按钮存活、归属、可见性和 rect；None 隐藏并停止；同目标不重新启动；合法用户目标用 driver.go，其他用 snap。`snap_to_selection` 重新测量最近确认目标。
- [ ] 安装局部几何/生命周期观察：host 与 buttons 的 show/hide/resize/font/enabled/失活、目标 destroyed；映射变化直接定位。单个目标禁用和祖先禁用都使用禁用色，不能只检查 host.isEnabled。
- [ ] 保持普通 driver 和其他动效 token 行为不变，跑 T1 两个测试文件。新增用例至少验证下列曲线约束：

```python
assert selection_easing().valueForProgress(0.25) == pytest.approx(0.735, abs=0.005)
assert selection_easing().valueForProgress(0.50) == pytest.approx(0.937, abs=0.005)
```

退出：R1、R2、R5 共享层通过；静止 driver inactive；没有第二套每帧计时器。

## 5. T2 — SegmentedChoice 接入且只对直接操作动画

**测试：** 修改 `tests/ui_kit/test_segmented_choice.py`；相关诊断兼容 gate 为 `tests/ui/test_motion_demo.py`。保留默认关闭、拒绝非二选一 combo、32px 几何、mutable labels、祖先 disabled、QSettings/stylesheet 清理等现有合同。

- [ ] 先添加失败用例：Light 下点击开启动画，外部 `combo.setCurrentIndex` 即使控件可见也直接归位；应用预设和 blocked sync 不补播；点击触发另一实例更新时另一实例不动画。
- [ ] 迁移 `_SelectionPill` / 底板坐标逻辑到 T1 helper。保留 `bound_combo/buttons/currentIndex/setCurrentIndex/set_motion_policy/sync_from_bound_combo/refresh_from_bound_combo`。不改变原 hidden combo 的 parent 和公开信号。
- [ ] helper 提供只读 `driver()`；SegmentedChoice 的 `_motion_driver` 改为只读转发属性，保持 `motion_demo.py:_sample_active` 的观测有效，不维护第二份 driver 状态。暂时隐藏的有效目标保留引用，重新显示直接定位。
- [ ] 在 `_on_button_clicked` 的当前实例作用域标记直接激活；只让一次相应索引投影使用 animate=True，标记在同步信号重入前消费，并在 finally 清理。后续程序联动采用 animate=False；如果最终 combo 值被业务校正，最终呈现必须跟随校正后的值。
- [ ] `_on_combo_index_changed` 仍立即更新 checked 和原信号，恢复同步走 snap。保证没有 `finished → currentIndexChanged` 或 `finished → 计算` 连接。
- [ ] 启用时只抑制当前组静态 checked chrome；Off/Reduced 完整恢复原样式。调整私有测试观察点到 helper driver，保留原有效断言，不仅删除失败用例。
- [ ] 执行 T2 测试文件及 motion_demo 兼容 gate；T1 仅当共享层发生新修改才重跑。原有“程序 setCurrentIndex 会动画”的测试按新合同拆为“直接按钮激活动画”和“程序同步 snap”，保留信号与生命周期断言。确定性验证模型不等动画的示例：

```python
# 生产实例策略在下一任务接线；这里显式开启以验证组件合同。
choice.set_motion_policy(POLICY_LIGHT)
QTest.mouseClick(choice.buttons()[1], Qt.LeftButton)
assert choice.bound_combo().currentIndex() == 1
assert list(spy) == [[1]]
# 推进动画结束后，业务信号仍只能是同一条。
```

退出：R3/R4/R5 组件层通过；通用构造依然默认 Off；程序同步不再播放选中背景。

## 6. T3 — 主导航与 Batch 方法栏

**文件：** T3 owner；必要的 style.qss 局部选择器。

**测试：** `tests/ui/test_toolbar.py`、`tests/ui/test_toolbar_i18n.py`、`tests/ui/test_toolbar_branding.py`、`tests/ui/test_batch_method_buttons.py`。

- [ ] 先加失败用例：N1/N2 显式 Light，400 ms；五个真实标签/业务 key 保持；用户鼠标与 Batch 方向键动画；程序调用直接定位；重复激活信号不变。
- [ ] 用现有共同宿主和按钮序列创建 SelectionIndicator，传 `selection_navigation`。保留 Toolbar 活动点，Batch 不加新点、下划线或占位。样式端点沿用各 owner，不复制 HTML 配色。
- [ ] 为两个 owner 增加局部 `set_motion_policy`，生产构造显式 Light。用户激活 handler 与程序 setter 分离；旧 `_set_mode(mode)` / `set_method(method)` 调用兼容，程序默认 snap。当前 key 的业务语义仍由旧 setter 决定，不用 helper 去重原业务信号。
- [ ] 动画启动/状态更新留在原事件循环，无 `processEvents`；信号订阅者可能同步触发重布局，最终重新测量并归位，不强行保持旧 rect。
- [ ] 检查宽窗口文字模式→窄窗口图标模式→恢复、中文、字体变化、原间距、tooltip、Tab/focus 和图标命中。修改的连接使用 named slot 或 partial，不增加 `.connect(lambda`。
- [ ] 运行 T3 四个 owner 测试文件。失效时在对应 owner 修复，不扩大 MainWindow state whitelist。

退出：N1/N2 通过；主工具栏重心和高度不变；未启用 View 动效。

## 7. T4 — Inspector 与 Batch 二选一生产覆盖

**修改创建点：**

```text
mf4_analyzer/ui/inspector_sections/contextual_frf.py
mf4_analyzer/ui/inspector_sections/contextual_fft.py
mf4_analyzer/ui/inspector_sections/contextual_fft_time.py
mf4_analyzer/ui/inspector_sections/contextual_order.py
mf4_analyzer/ui/inspector_sections/persistent_top.py
mf4_analyzer/ui/inspector_sections/_helpers.py
mf4_analyzer/ui/drawers/batch/method_buttons.py
mf4_analyzer/ui/drawers/batch/input_panel.py
mf4_analyzer/ui/drawers/batch/slice_panel.py
mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py
```

**测试：** `tests/ui_kit/test_segmented_choice.py`、`tests/ui/test_batch_method_buttons.py`、`tests/ui/test_batch_input_panel.py`、`tests/ui/test_batch_slice_panel.py`、`tests/ui/test_batch_chart_statistics.py`。

- [ ] 扩展已有真实 Inspector factory 参数化测试，B1–B4 按 Spec 实例字段逐项验证策略启用；用真实 Batch owner 覆盖 B5–B6。不能只 grep 创建点推断覆盖完成。
- [ ] 在这些创建点 bind 后显式 `choice.set_motion_policy(POLICY_LIGHT)`；复用现有控件，不修改默认构造、不扫描子树、不改选择值。
- [ ] 测试 B5 的所有字段仅在实际方法可见/有效时可交互。选择“每项单独”后 render_layout 保持值但停止并显示禁用态，恢复分组后仍是原值。
- [ ] 对 FRF 预设、FFT 幅值联动、目标策略、切片维度更名、统计区间程序恢复：验证 payload 一致、原信号次数不增加、非直接操作组无动画。
- [ ] 运行本任务五个测试文件；如果某创建点原 owner 的额外字段恢复边界失败，只增加该 owner 对应聚焦用例，不跑整个 Inspector/UI 目录。

退出：B1–B6 清单逐项齐全；通用组件的默认 Off 及其其他消费者不变。

## 8. T5 — 时域与频率图卡

**文件：** `mf4_analyzer/ui/chart_stack/cards.py`；必要的 style.qss chart-choice 局部规则。

**测试：** 新建 `tests/ui/test_chart_selection_slide.py`；现有 `tests/ui/test_chart_card_construction.py`、`tests/ui/test_chart_stack.py`。

- [ ] 先写失败用例：TimeChartCard 的二选一布局与三选一游标各有独立底板；FrequencyCursorCard/FrfChartCard 三选一；分屏第二目标被聚焦时只改变该目标 canvas，源图卡同步不再发业务信号。
- [ ] 在原 toolbar 共同宿主添加背景 helper，复用原按钮，不改变 QWidgetAction 插入序列、spacer、分隔符或 canvas 尺寸。每组使用 `selection_control`。
- [ ] 用户 clicked 和已有按钮 shortcut 路由动画，外部 `set_plot_mode/set_cursor_mode/sync_frequency_cursor_control` 直接定位。保留 notify=False、同值 no-op 和 target provider 合同；不得把非目标卡状态误当真实选择。
- [ ] 触及的 `.connect(lambda` 改为 named slot/partial，保持 Ctrl+1…5 现有覆盖和 hidden-card 不抢快捷键；不新增键盘操作。
- [ ] 验证窄 toolbar、按钮不可见、卡片切换、焦点变化、祖先 disabled、销毁时活动动画停止；原 hint 刷新次数和图表计算次数不增加。
- [ ] 运行新测试与两个现有 owner 文件；仅当 stack.py 因真实接线需求发生修改时将其纳入修改范围，并记录原因，不能为方便扩大重构。

退出：C1/C2 一致，模型、canvas 目标、shared-toolbar 焦点正确；动画没有进入 pg_canvas 数值/渲染代码。

## 9. T6 — 原生验证、边界与报告

**新文件：** `scripts/probe_selection_slide.py`、`tests/ui/test_selection_slide_probe.py`；报告 `docs/analyzer/verify/2026-09-10-selection-slide-rollout.md`。

- [ ] 探针复用 `scripts/probe_interaction_motion.py` 的隔离设置、合成夹具、观测和 teardown helper，不复制整套基础设施。新 CLI 定义 `--output-dir`、`--logic-only`；默认执行 Spec §5.2 全部 P1 代表场景。导入脚本不得创建 QApplication。动效测量由真实按钮点击/键盘激活进入，不能复用旧探针直调 `_set_mode` 的入口来声称验证用户动画；直调只用于程序恢复无动画对照。
- [ ] logic-only 测试验证场景覆盖、Off/Light 实例策略、信号统计、记录格式、超时失败状态、设置隔离及清理；不把人工推进时钟的数据标为性能。
- [ ] 输出每次原始记录：scene_id、policy、source_fingerprint、target、signal_counts、feedback_paint_ms、animation_end_ms、content_ready_ms、paint_intervals_ms、paint_work_ms、final_state、platform。不可测值为 null 并附原因，不能填 0。
- [ ] 保存生产 QSS 真实底板端点/中间帧及按钮截图，测量 geometry/hit rect、圆角、焦点、禁用、DPR；原生录屏用于动态手感，截图不代替录屏。
- [ ] Cocoa 运行下述**拟新增命令**，确保没有 QT_QPA_PLATFORM=offscreen，窗口实际暴露。按 Spec 5 次预热、40 次有效样本、30/180 s 超时、500 ms 静止观察记录。应用系统环境需要 GUI 权限时按运行环境规则申请。

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_selection_slide.py --output-dir .state/selection-slide-rollout/cocoa
```

- [ ] Windows 使用项目 Python 执行同一脚本，分别 100%/150% 缩放；无可用 Windows 则记录 G4 UNVERIFIED。不得以 Cocoa 或 offscreen 替代。
- [ ] 跑边界命令（owner 测试先通过；以下只跑一次，后续仅新修改/失败才重跑）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py tests/ui/test_qsettings_isolation.py tests/ui_kit/test_qss_border_shorthand.py
```

- [ ] 若 T5 实际触及 canvas/backref/绘图生命周期，再加 `tests/ui/test_pg_canvas_backref_invariants.py` 与 `tests/ui/test_pg_timedomain_canvas.py`；本计划不应修改这些 owner。若新增动态导入影响包装，追加 `tests/test_packaging_imports.py`，并先写明原因。
- [ ] 本任务不要求全套；只有后来明确成为 release/merge gate 或发现测试顺序污染才考虑扩大。需跑全套时先查已有 pytest 进程及工作目录，单协调者、稳定快照，主套与 acquisition_ui 两个新进程顺序执行，绝不重叠。
- [ ] 重录 HEAD、相关 source fingerprint 和 dirty scope；运行期间源码变化则相关性能/验收结果为 UNVERIFIED。报告逐个 P1 ID 和 G1–G6 的 PASS/FAIL/UNVERIFIED，不能仅报一个总测试数。
- [ ] `git diff --check`；检查 lessons `--status`。只有遇到实际可复用失败模式才按项目规则记录 lesson，不为写完文档制造 lesson。用户未授权发布则止于可审阅 patch 和报告。

退出：实现、owner/boundary 证据完整；缺 G3/G4 时明确 `partial`，不得把 UI 手感当已验收。400/300 与曲线若真机需修订，先更新 Spec/Plan 同一合同并记录测量理由，不随意改 token 迎合测试。

## 10. 覆盖映射与文档门禁

| Spec 合同 | 任务 | 证明 |
| --- | --- | --- |
| R1 时间/曲线隔离 | T1 | 曲线采样与旧 driver/token 行为 |
| R2 单底板/几何 | T1/T2/T3/T5/T6 | 2/3/5 项实测 rect、QSS 像素、窄窗口 |
| R3 用户来源/恢复 | T2/T3/T4/T5 | 用户激活有动画，外部/联动/恢复无动画 |
| R4 信号/业务目标 | T2–T5 | 信号 spy、Batch 同值语义、频率焦点目标 |
| R5 打断/生命周期 | T1/T2/T5 | 20 次反向、禁用、隐藏、deleteLater、静止 |
| R6 P1 生产覆盖与默认关闭 | T3/T4/T5 | 真实 owner 实例清单；未纳入组件仍 Off |
| R7 原生与平台证据 | T6 | G2/G3/G4 原始记录、动态观察和报告 |

当前 docs-only 检查：全文复核两文件；校验现有文件路径与两文档链接；所有计划新文件清楚标“新增”；扫描旧业务 key、占位词、全局误启用和 P2 混入；`git diff --check`。未改变可执行行为，不跑产品 runtime 测试。不要勾选 T0–T6，也不创建实施验证报告。
