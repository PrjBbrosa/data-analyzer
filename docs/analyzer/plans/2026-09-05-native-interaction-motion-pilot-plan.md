# TraceLab 原生交互动效第一轮实施 Plan

日期：2026-09-05 · 修订：R1 · 状态：**文档就绪；以下实施任务均未开始**。

唯一目标合同：[配套 Spec](../specs/2026-09-05-native-interaction-motion-pilot-spec.md)。S01–S07、M01/M02、G0–G6 的含义以该 Spec 为准。

## 1. 实施与授权边界

当前只创建这两份文档，不修改产品代码、测试、工具、设置或版本。用户后续要求按本计划执行时，完成一个原生样板入口和真实页面切换测量；不会自动把动效推广到普通启动路径。

默认一个实施者串行执行。本文不要求创建子 agent、任务或自动化；若用户后续明确要求并行，才按 §2 的不重叠 owner 拆任务，共享策略、样板集成和验收仍由一名协调者持有。

普通产品调用默认关闭新动效；样板显式实例化生产类并启用。S07 只演示轻页面；M01/M02 测量真实页面，二者不得合并叙述为“主界面页面动效已经实现”。

所有未来新增路径在本文明确标为“新增”；未实现前不能执行其示例命令。当前源码中已有的同名模块若在执行时出现，应先核对 owner 和内容，禁止直接覆盖。

## 2. 文件所有者和改动白名单

以下路径均相对仓库根；是否实际修改以最小必要实现为准，不为凑清单创建空模块。

| 责任 | 允许的文件 | 边界 |
| --- | --- | --- |
| 共享策略/驱动 | **新增** `mf4_analyzer/ui_kit/motion.py`；**新增** `tests/ui_kit/test_motion.py` | MotionPolicy、统一时长、可打断值插值；没有全应用调度器或业务状态 |
| S01 按钮 | **新增** `mf4_analyzer/ui_kit/widgets/motion_button.py`；**新增** `tests/ui_kit/test_motion_button.py` | 四种标准角色的样板按钮，保留 QPushButton 行为 |
| S02 开关 | `mf4_analyzer/ui/widgets/pill_switch.py`；`tests/ui/test_pill_switch.py` | 原 painter 与语义；默认关闭 |
| S03 分段 | `mf4_analyzer/ui_kit/widgets/segmented_choice.py`；`tests/ui_kit/test_segmented_choice.py` | combo 为状态 owner，单一选中底板 |
| S04 标签 | `mf4_analyzer/ui/view_tabbar.py`；`tests/ui/test_view_tabbar.py` | 仅装饰标记；不重构 refresh/reorder/overflow |
| S05 折叠 | `mf4_analyzer/ui/inspector_sections/collapsible.py`；**新增** `tests/ui/test_collapsible_motion.py` | body 呈现/焦点；已有 Inspector 合同继续跑 |
| S06 弹层 | `mf4_analyzer/ui/widgets/recent_open_popup.py`；`tests/ui/test_recent_open_popup.py` | 只增加有界入场；原关闭、焦点、定位不变 |
| 宿主与 S07 | **新增** `mf4_analyzer/ui/motion_demo.py`；**新增** `tests/ui/test_motion_demo.py` | 真控件组装、策略选择、轻页面、合成意图日志；无普通启动接入 |
| M01/M02 与采样 | **新增** `scripts/probe_interaction_motion.py`；**新增** `tests/ui/test_interaction_motion_probe.py` | 事件/paint 关联、主窗口夹具和 JSON；产品不依赖脚本 |
| 样式 | `mf4_analyzer/ui_kit/style.qss`，仅实现单一像素 owner 所必需的实例限定选择器 | 不改全局通用尺寸/角色；不每帧设置样式 |
| 报告 | **新增** `docs/analyzer/verify/2026-09-05-native-interaction-motion-pilot.md` | G1–G6 结果及下一轮范围建议 |

`control_style.py` 的现有 token 直接读取，原则上不改。新模块按明确路径导入，无消费者需要就不扩展包 `__init__.py`。`app.py`、MainWindow mixins、ChartStack、side_panels、pg_canvas、signal、Batch、打包和版本文件为本轮禁止改动范围；探针只在自身进程包裹现有入口。

## 3. 依赖和工作量

```text
T0 当前快照、范围与聚焦合同确认
 → T1 策略/生命周期 + 最小宿主
 → T2 按钮、开关、分段
 → T3 View 装饰标记
 → T4 折叠、最近打开、轻页面
 → T5 真实切换与采样工具
 → T6 原生测量、边界验证、报告
```

T5 的指标设计在 T0 冻结，避免做完动画才定义通过标准。T6 基于稳定目标文件快照执行，读取其他任务已有证据时必须核对 source fingerprint 和入口含义。

估算：T0–T1 1–2 人日，T2–T4 3–5 人日，T5 1–2 人日，T6 2–3 人日，合计约 7–12 人日；首个可体验版本约 3–5 人日。双平台环境等待另计，不能为了符合估算省略门禁或扩成全局改造。

## 4. T0 — 冻结真实边界与验证入口

**修改范围：** 本轮 `.state/native-interaction-motion/` 台账；只有合同需要可新增后续任务名下的测试，不改业务实现。

1. 记录 HEAD、分支、git status、目标文件 SHA-256、Qt/PyQt/pyqtgraph、OS、DPR、显示器刷新率。只 fingerprint 真实相关源码，探针输出文件不参与源快照。
2. 重读 §2 owner；核对近期布局工作是否修改了目标弹层。当前工作区有多个在途改动，不能通过 checkout/reset 或全量 staging 清理。
3. 使用 lessons INDEX 选择动效实际相关条目：控件像素验真、View 关闭重新进入、透明 popup 自绘、QSS 测试污染；不整库加载。
4. 记录每个 S 的真实语义入口、信号和几何基线；尤其记录 combo 同步、PillSwitch 的 blockSignals 恢复、View manager active 确认、popup 两层 Esc 和 collapsed body 焦点。
5. 固定 Spec §6 的场景、采样边界、预算和 raw JSON 结构。旧 probe 的 300ms section round-trip 只能作逻辑参考。
6. 为新行为先写针对性失败测试：中间位置存在、打断后从当前值继续、业务信号时点不变、默认关闭路径完全兼容。已经存在的正常行为用 owner 测试冻结，不写仅匹配字符串/常量的测试。

**聚焦基线：** 在每个 owner 任务开始前只运行对应旧测试；T0 不跑 `tests/ui` 或全量。先保存一次结果，未改动同一 owner 时复用，不反复重跑。

**退出：** S01–S07 与 M01/M02 都有明确 owner 和观测点；失败用例针对实际新合同；没有把 offscreen 结果当性能基线。

## 5. T1 — 最小动效基础与隔离宿主

**文件：** motion.py / test_motion.py；motion_demo.py / test_motion_demo.py 的初始化部分。

1. 实现 MotionPolicy、时长表和实例持有的值动画驱动。使用 Qt 既有 QVariantAnimation/QPropertyAnimation 能力，不创建永久 16ms 全局 timer。
2. 支持目标替换、同目标 no-op、同步终点、策略关闭、隐藏和销毁；动画对象有明确 Qt parent。若有延迟回调，用 generation/弱引用校验，测试 deleteLater 和重开。
3. 现有类使用显式 `set_motion_policy` 接口；无策略时没有新活动动画、没有业务信号和布局副作用。策略切换的终点从 widget 真实业务状态读取。
4. 宿主入口只在 main 中建 QApplication、设置临时 INI 路径、应用当前字体/Fusion/QSS；导入无副作用。检查 MainWindow 测量稍后需要的显式组织名/格式设置也能隔离，任何无法隔离的真实 store 访问使探针失败退出。
5. 样板构建三种模式和复位入口；只在当前模式实例上执行动作；暂用空占位区等候 S01–S07 接入，不添加额外产品帮助入口。
6. 生命周期测试人工推进时间；样式测试用现有 fixture 保存/还原 app stylesheet。不得向根 conftest 塞项目 fixtures。

**测试：** 新 test_motion.py（反转、重复目标、减少动效、删除、无残留 timer）；新 test_motion_demo.py（导入副作用、临时设置、策略切换）。

**退出：** 可独立显示空样板；普通控件路径不变；静止时驱动无活动；默认关闭与减少动效终态一致。

## 6. T2 — 三类高频控件

### T2a S01 按钮

- 新 MotionButton 只用于样板；为四个角色准备中文文字和真实图标样本。
- 复用现有 token 与标准按钮尺寸；确定单一 chrome 绘制者，原标签/焦点/默认/禁用表达完整。
- hover 插值，按下立即反馈、释放按表恢复；拖出释放不多发 clicked；不变更 widget 几何。
- 生产 QSS 下比较原 QPushButton 和 motion off/on 的终态、hit rect、sizeHint；AA 边缘允许窄像素容差，不能放宽文字裁切/缺边。

**测试：** 新 test_motion_button.py；`tests/ui_kit/test_control_button_render.py`；触及角色选择器才跑 `tests/ui_kit/test_control_style.py`。

### T2b S02 开关

- 将原 painter 的圆钮位置和轨道颜色接到呈现值，保持 44×24 与原标签点击语义。
- 先验证 blockSignals/setChecked、父 disabled 和隐藏恢复，再加入正常 toggled 动画，避免内部信号被屏蔽后圆钮永远停在旧态。
- 快速反向测试检查当前显示位置连续、真实 checked 立即变化、toggled 次数与无动画一致。

**测试：** `tests/ui/test_pill_switch.py`（增加动效合同，保留原 DPR/渲染测试）。

### T2c S03 分段选择

- 只在启用动效实例隐藏两个按钮的重复选中背景，由一个 input-transparent 底板绘制；底板位置使用按钮实测 rect。
- 保持 combo 权威状态、mutable labels/tooltips 和两条既有同步入口。resize/字体更新/blocked restore 均 snap，不能造成信号回环。
- 底板运动不改布局、按钮分配或隐藏 combo 的 parent 生命周期。

**测试：** `tests/ui_kit/test_segmented_choice.py`，含已有 deferred-delete 所有权和 Inspector 32px 对齐用例。

**T2 退出：** 三类样本可 A/B；确定性 0/25/50/100% 帧与几何、输入通过。此时可以提供首个可体验版本，但继续执行余下已授权任务，不把首个 demo 当作整轮完成。

## 7. T3 — View 装饰标记

**文件：** view_tabbar.py / test_view_tabbar.py；样板组装。

1. 使用真实 ViewManager 和原 ViewTabBar，intent 接到 manager，标记只监听确认后的 active 变化。
2. 在既有标签内部自绘装饰线，无独立输入层；保留当前背景、关闭色块和 split 色。
3. 旧/新标签处于同一稳定可见布局才插值；refresh/reorder/compact/overflow/resize/DPR 变更清理目标并按 view_id 重新定位。
4. 不做 remove/add 动画，不改 _retire_tail_tabs 的索引规则，不在 tabMoved 栈内重建。
5. 测试快速 A→B→C、删除正在标记的 View、manager 尚未确认请求、24/12 上限、窄窗口 overflow、反复 resize。
6. 把 inactive swatch、选中后指针重新进入、重复关闭、拖出取消等旧用例全部保留并在动效实例上补相同语义检查。

**测试：** `tests/ui/test_view_tabbar.py`；`tests/ui/test_view_tabbar_mount.py`。没有修改真实恢复路径时不跑整套 View 切换测试；T5 再覆盖探针入口和相关集成。

**退出：** 标记平滑且没有错 View、隐藏 active、28×28 变化、额外 switch/delete/reorder 信号；默认实例端点仍与旧行为一致。

## 8. T4 — 折叠、弹层和轻页面

### T4a S05 折叠

- 状态/持久化与显示进度分离，注入临时 settings；沿用 persistent/body 分区。
- body 先完成最终宽度布局再做高度裁剪；结束释放临时 min/max 约束。
- 收起时先转移 body 内焦点，再屏蔽其输入；不更改业务字段 enabled 值。快速反转时恢复正确输入访问。
- 内容替换、字体变更、长表单和样板滚动容器都要覆盖；只有样板列局部布局变化，不能连动主窗口 canvas。

**测试：** 新 `tests/ui/test_collapsible_motion.py`；`tests/ui/test_inspector.py -k 'collapsible_param_section or contextual_param_sections'`。PersistentTop 的独立 collapser 不在实施范围。

### T4b S06 最近打开弹层

- 使用真实 RecentEntry 与临时存在/缺失文件夹具；沿用 populate、focus_search、show_at 和原 row delegate。
- 入场使用组件独占的有界内容宿主，不覆盖已有 effect；关闭不做动画。
- 验证初始化焦点、入场中打字、内部 click、Esc 清空后关闭、外点、clear/open/closed 信号次数、再次打开和父销毁。
- 屏边翻转/clamp 或 resize 时停止过渡；按窗口和像素 owner 同时验证最终 rect、圆角和边框。

**测试：** `tests/ui/test_recent_open_popup.py`；如改变到 popup shell helper 才增加该 helper owner gate，原则上不修改共享 shell。

### T4c S07 轻量页面

- 只在 motion_demo 内实现两页宿主，不触及 ChartStack。固定轻内容边界 640×420，页之间保留字段值。
- 目标 state/header 立即更新，只让目标内容淡入；输入中断淡入，旧页不可输入。
- 检查 20 次快速切换、动画中关闭宿主、隐藏重显、减少动效、resize、Tab 焦点，不创建全页截图缓存。

**测试：** 新 `tests/ui/test_motion_demo.py` 的页面与策略用例。

**T4 退出：** S01–S07 全部可体验；off/reduced 和原语义等价；未添加正式设置或主界面动效。

## 9. T5 — 可解释的真实测量

**文件：** 新 probe_interaction_motion.py / test_interaction_motion_probe.py；如需观测点优先包裹现有方法，不改 MainWindow 或渲染器源码。

1. 提供 `samples` 与 `switches` 两个子命令；前者遍历原生样板，后者建立隔离 MainWindow、合成来源和真实 View/FFT 上下文。
2. 探针开始先检查 platform/exposed；Qt offscreen 只允许 `--logic-only` 跑事件/序列化合同，性能字段必须为 null 并带原因。
3. M01 发送真实 tab 输入；M02 发送 Toolbar 对应按钮输入，验证 `_on_mode_changed` 确实运行。记录 entry_kind；归因直调结果另放数组。
4. cached 场景先走正常 FFT 提交/完成一次再采样，缓存 key/当前 View/来源一致；采样期间计算提交次数应为零。初始化耗时单列。
5. 实现 Spec 的事件序号、目标身份、paint 关联、content_ready、stable_paint 和独立心跳；不能把 paintEvent 开始或 Qt 动画 tick 当成已经上屏。
6. 按 Spec §6.2 的 schema_version=1 输出；原始记录包含场景、mode、动作序号、冷暖、时间边界、最终状态、exposed、异常、timeouts、源 fingerprint、OS/runtime/DPR/刷新率及 presentation 可用性。没有终点证据用 null，不填 0；无活动动画不生成虚假的 paint_interval 比较。
7. `samples` 的 A/B 用独立实例按 ABBA 分组串行重放；性能与录屏分开采集，避免截屏自身开销混入 paint/回调测量。
8. warm 5 次预热+40 次测量；cold 5 个独立新进程。使用 Spec 的固定夹具和数组摘要；单次动作/初始化计算各 30s，单组采样 180s 超时，保留部分原始记录并归 UNVERIFIED，不杀其他任务进程。
9. 关闭进程前 teardown widget、drain deferred delete、移除探针 event filters、停止心跳。探针不得打开用户最近项目或保存默认配置。

**确定性测试：** 事件 A/B 交错时结果归属正确；无 paint/exposed/结束信号时指标为空；content_ready 在最终 X/Y 和目标 identity 后；cached 无 compute；异常/源变更使状态 UNVERIFIED；逻辑模式永不输出性能 PASS。

**已有相关门禁：** `tests/ui/test_view_switch_reentrancy.py`、`tests/ui/test_view_switch_integration.py`，只在新探针真实 MainWindow 接线完成后跑一次，冻结其业务边界。无需修改原 `probe_view_switch_quality.py` 和 `benchmark_timedomain_interaction.py`。

**退出：** JSON 边界可信、有原始序列；M01/M02 不绕过实际入口、不夹入人为等待。尚无真机时工具实现可以完成，但 G3/G4 仍 UNVERIFIED。

## 10. T6 — 验证和报告

### 10.1 聚焦测试与边界

各 owner 修改后先跑其任务名下的测试；通过后不无理由重跑。共同边界在 T4/T5 集成稳定后由同一实施者运行一次：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_import_boundaries.py tests/ui/test_no_lambda_signal_connections.py tests/ui/test_qsettings_isolation.py tests/ui_kit/test_qss_border_shorthand.py tests/test_conftest_autouse_scope.py -q
```

按目录分组书写参数，保留仓库根 conftest 的 collector 修复；不通过删 fixture 或更改参数顺序掩盖污染。

本轮不改 MainWindow 状态、signal、Batch、renderer 或 packaging，故其专门边界与全套 UI 不是默认门禁。若实施发现必须越过此范围，先记录具体原因并更新 Spec/Plan 的范围，再运行相应 owner/boundary；不能因方便偷偷扩大实现。

本轮不安排全量 pre-change 或全量 release gate。若用户另要求全量，由一名负责人检查运行中 pytest 及 cwd 后执行；稳定源码指纹前后相同，main suite 与 acquisition_ui 两个新进程顺序跑，绝不重叠。

### 10.2 拟新增入口示例

以下命令只有在 T1/T5 实现后才可用。输出目录由工具创建；当前文档任务不执行。

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m mf4_analyzer.ui.motion_demo
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py samples --output-dir .state/native-interaction-motion/cocoa-samples
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py switches --output-dir .state/native-interaction-motion/cocoa-switches
```

真机测量继承本机原生 Qt platform；启动前若发现环境被设为 offscreen，明确失败并给出原因，不能产出 Cocoa 性能报告。Windows 在仓库根使用其项目 Python 执行同一 `-m` / script 入口及 `--output-dir`，不照搬 POSIX 环境赋值或依赖 zsh。

### 10.3 平台和像素矩阵

| 项目 | 最小覆盖 | 证据 |
| --- | --- | --- |
| 静态几何/像素 | 生产 QSS、DPR 1/2、各终态及中间进度；32/28/24 按钮、44×24 switch | owner widget PNG + rect JSON；允许 AA 细边差异 |
| 窗口尺寸 | 宽松 1200×800 与紧凑 800×600；受 availableGeometry 约束时记录最终大小 | 无 clipping、越屏、不可达控件；关闭控件在屏内 |
| Cocoa 自动 | S01–S07、M01/M02、ABBA、100 次 popup 周期、动画中退出 | 原始 timing/object/RSS 数据及检查结果 |
| Cocoa 前台 | hover/按下/快速反转、View 关闭、折叠焦点、popup 输入/外点、页面切换 | 录屏（可用时）和实际体验记录；自动探针不替代此项 |
| Windows 原生 | 100%/150% 缩放；同一七样本及关键 M 场景 | 字体/几何/焦点/透明效果/动态记录 |
| Windows Full/Lite frozen | 不在本轮样板范围 | 单列 NOT_IN_SCOPE |

没有录屏工具时可以完成自动测量和实际前台操作，把连续录屏字段标 UNVERIFIED；不能用静止截图宣称帧间无闪烁。Windows 不可用时继续完成本地实现与证据，在报告明确 partial，不开启生产默认。

### 10.4 报告最低字段

按 S01–S07、M01/M02 逐行写：实现状态、G1/G2/G3/G4/G5、冷暖/输入分类、预算结果、raw artifact 路径、问题、建议。最后列 G6 推广候选：

- 可推广：合同与已有平台证据满足，列可进入下一轮的组件及条件。
- 需调整：明确哪段动画/哪种布局超预算或体验不佳，给最小修改。
- 待平台：代码与本地通过，平台验收缺失。
- 大数据瓶颈：只写 measured owner 和时间，不在此轮实施渲染优化。

单独记录主观体验尚未由用户评价的项目；这一状态不阻塞报告提交，也不擅自替用户确认风格。推广的具体入口、正式减少动效设置和 hints/quickref 配套属于下一轮。

## 11. 风险、降级与交付纪律

| 风险 | 首轮处理 |
| --- | --- |
| 自绘与 QSS 双重覆盖 | 控制单一像素 owner；实例限定选择器；端点和中间帧截图 |
| 动画结束回调执行旧动作 | finished 不做业务；旧代只可清理自身；重入/删除测试 |
| 折叠每帧推动大画布 | 只在样板列内验证；真实 side panel/ChartStack 不接入 |
| Qt.Popup 淡出延迟焦点/抓取释放 | 首轮只入场；所有退出保持立即关闭 |
| View 动画越过管理器或关闭锁 | 跟随确认的 view_id；布局变化 snap；保留重新进入保护 |
| 测量误把等待/未暴露 paint 当延迟 | 事件序号与真实入口；等待不计入；缺测用 null/UNVERIFIED |
| 全局样式/设置污染 | 入口与测试隔离；恢复 stylesheet；真实 store 前后核查 |
| 在途布局文件漂移 | 实施前后 fingerprint；只改本轮 owner，保留已完成屏幕适配 |

常规降级是停用该样本过渡并保留原交互；不做全局开关、全局 patch 或吞掉编程错误。首轮默认关闭使普通用户启动不受样板影响，但仍须证明默认分支的回归合同。

提交不是本次请求的一部分。后续若要求提交，先审查 changed-file scope，只 stage 本轮相关命名路径，使用 `git diff --check`，不使用 `git add -A`，不把 `.state/`、本机配置或他人改动带入。

## 12. 当前文档任务的完成检查

- [x] 完整通读 Spec 与 Plan，核对 S/M/G、时长、范围、文件所有者、估算一致。
- [x] 核对现有文件和方法真实存在；新增路径标清“新增”，不存在的未来工具不被写成已运行。
- [x] 搜索历史错误假设：Recent popup 800px、全部 View 12 上限、300ms wait 当首帧、全局启用、动画结束提交业务。
- [x] 对两份新文件做相对链接检查与空白检查；核对本次只写了这两份文档。
- [x] 检查 lessons 状态：lesson_required=False；本次没有需新增的重复失败经验，不改全局 memory。

本次是文档新增，不改变可执行行为或既有帮助/版本合同，因此不运行 runtime tests。上述 T0–T6 的测试与平台验收均为后续实施任务，不在本文标成已通过。
