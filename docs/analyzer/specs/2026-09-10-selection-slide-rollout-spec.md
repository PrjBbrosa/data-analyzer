# TraceLab 选中背景滑动推广 Spec

日期：2026-09-10。状态：**设计文档；未实施，原生手感与平台验收 UNVERIFIED**。

配套：[执行 Plan](../plans/2026-09-10-selection-slide-rollout-plan.md)；[HTML 手感原型](../ui-prototypes/2026-09-10-button-slide-transition.html)。

## 1. 目标、授权与依据

用户认可选中背景在固定按钮之间滑动的方向，认为约 400 ms 的手感可以接受，要求分析全局适用位置并编写 spec/plan。当前仅授权文档；未来“按 plan 执行”涵盖本文 P1 第一批，不自动包括 P2 候选、发布、提交或推送。

目标：保持已有按钮尺寸、文字、图标、焦点和状态语义，以一块移动背景表达互斥选择；主导航使用 400 ms，紧凑参数使用 300 ms。业务状态立即生效，动画完成不参与业务决策。

依据分类：

- 用户反馈：HTML 方向认可，偏好约 400 ms；并非 Qt 真机验收。
- 当前源码：调查 HEAD `a1c4ab74f92031d234d610689df68ec820a42c4d`，工作区包含其他在途修改；实施前重新记录 HEAD 与相关文件指纹。
- 现有基础：`ui_kit/motion.py` 已有 `MotionPolicy`、`ValueDriver`，`segment=160`、默认 `OutCubic`；缺省策略关闭。`SegmentedChoice` 已有输入透明底板，但仅支持两个选项。
- 历史 [试验 Spec](2026-09-05-native-interaction-motion-pilot-spec.md)、[验证报告](../verify/2026-09-05-native-interaction-motion-pilot.md) 解释默认关闭的来历；其 Cocoa/Windows 尚未验证，历史通过数不能作为本次通过数。
- 本文对 P1 的时长、曲线、显式生产启用、程序更新直接定位作出新合同。旧文档保留原日期和历史状态；其他试验动效不随本次改动。

## 2. 范围清单

下文代码路径以仓库根为基准。P1 是实施完成范围；P2 只记录设计方向，不是本 Plan 的隐藏任务。

### 2.1 P1 第一批

| ID | 产品位置及选项 | 文件 / owner | 时长 |
| --- | --- | --- | ---: |
| N1 | 主工具栏五种分析模式 | `mf4_analyzer/ui/toolbar.py:Toolbar` | 400 ms |
| N2 | Batch 五种分析方法 | `mf4_analyzer/ui/drawers/batch/method_buttons.py:MethodButtonGroup` | 400 ms |
| B1 | FRF：H1/H2、NFFT 自动/手动、dB/线性、对数/线性、展开/±180° | `mf4_analyzer/ui/inspector_sections/contextual_frf.py` | 300 ms |
| B2 | FFT：Linear/dB、None/A | `mf4_analyzer/ui/inspector_sections/contextual_fft.py` | 300 ms |
| B3 | 时频：None/A；阶次：转速通道/手动 RPM、None/A；共用幅值单位 | `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`、`contextual_order.py`、`_helpers.py` 中的 `SegmentedChoice` 创建点 | 300 ms |
| B4 | 时域横轴时间/通道 | `mf4_analyzer/ui/inspector_sections/persistent_top.py:choice_xaxis` | 300 ms |
| B5 | Batch 二选一参数：estimator、nfft_mode、weighting、magnitude_scale、frequency_scale、phase_mode、render_layout、x_source、x_origin | `mf4_analyzer/ui/drawers/batch/method_buttons.py:_BINARY_CHOICE_FIELDS` 与动态表单 | 300 ms |
| B6 | Batch 共有/按来源可用；固定时间/固定频率；统计区间自动/手动 | `mf4_analyzer/ui/drawers/batch/input_panel.py`、`slice_panel.py`、`chart_statistics_panel.py` | 300 ms |
| C1 | 时域图卡：分屏/叠加；游标关/单游标/双游标 | `mf4_analyzer/ui/chart_stack/cards.py:TimeChartCard` | 300 ms |
| C2 | 频率图卡：游标关/单游标/双游标，含 FRF 与分屏焦点目标 | `mf4_analyzer/ui/chart_stack/cards.py:FrequencyCursorCard` | 300 ms |

保持当前选项顺序、业务 key、标签与 tooltip。主工具栏 `order` 与 Batch `order_time` 不统一改名。B3 不改变计权或幅值定义；隐藏 combo 继续拥有状态。

### 2.2 P2 候选与不适用清单

| 位置 / 文件 | 设计判断 | 纳入条件 |
| --- | --- | --- |
| 热图 X/Y 切片，`ui/pg_canvas/slice_panel.py:_SliceDirToggle` | 300 ms，适合 | 单独验证 canvas backref、切片状态与实际狭窄几何 |
| UltraView 轴类别筛选，`ui/chart_stack/ultraview/compare_rail.py` | 300 ms 竖向背景，可选 | 确认筛选后弹层可见性、纵向轨道及焦点 |
| View 与 Board 标签，`ui/view_tabbar.py`、`ui/chart_stack/ultraview/board_switcher.py` | 建议 240–280 ms 细标记，不套整块背景 | 保留稳定 identity、重排、关闭、overflow；P1 不启用已有 View 标记 |
| 图形设置的坐标轴/图形/图例，`ui/dialogs/chart_options.py` | 可用细标记 | 独立评估原生 tab 样式，无页面滑动 |
| 图卡 / Batch 刻度密度预设，`ui/chart_stack/toolbar.py`、`ui/drawers/batch/render_style_popover.py` | 可以用 300 ms | 手动值不匹配任何预设时隐藏底板；允许零选中 |
| 采集模式、回放倍速，`acquisition_ui/main_window/_toolbar_mixin.py`、`acquisition_ui/replay_tab.py` | 模式 400 ms、倍速 300 ms | 后续独立范围及独立 acquisition 测试进程 |
| Batch 分组预览卡 / 分析预设卡，`ui/drawers/batch/method_buttons.py`、`analysis_panel.py` | 保留卡片选中边框 | 不将真实三张分组卡替换成 HTML 的简化二选一 |
| UltraView 布局缩略图、颜色格、创作工具和侧栏按钮 | 不整组套用 | 网格空间、独立开关、弹层开合与互斥模式不同 |
| 独立 PillSwitch、复选框、显示/隐藏工具、展开收起 | 不属于同一选中背景 | 小开关继续沿用原策略和 160 ms；不跟随新时长 |
| 保存/运行/导出/删除/取消、选完关闭的菜单 | 不适用 | 保留即时动作，不延迟关窗等待动画 |

路径在本表的简写均相对于 `mf4_analyzer/`。全局一致指同类控件的反馈一致，不是所有可点击元素使用相同动画。

## 3. 动效合同

### 3.1 固定参数

| 配置 | 值 | 消费者 |
| --- | --- | --- |
| 新 token `selection_navigation` | 400 ms | N1、N2 |
| 新 token `selection_control` | 300 ms | B1–B6、C1–C2 |
| 新选中背景曲线 | `cubic-bezier(0.22, 0.75, 0.20, 1.00)` | 仅本次选中背景 |
| Off / Reduced | 0 ms，直接终态 | 同一实例显式策略 |

共享时长仍由 `ui_kit/motion.py` 唯一持有。不修改旧 `segment` token、全局 `EASING`、switch、view_marker、hover、折叠、页面或弹层时长；旧 token 可保留兼容，但本次底板改用新 token。

新曲线用 Qt 5 `QEasingCurve.BezierSpline`、`addCubicBezierSegment` 构造，不用 `OutCubic` 冒充。400 ms 时理论位移：100 ms 约 73.5%，200 ms 约 93.7%，300 ms 约 98.9%；此为曲线计算，不是绘制性能。容许值插值舍入，终态必须精确到目标 QRect。

文字、图标和 checked 状态立即变化；只有背景位置及必要宽度插值。背景不回弹、不越界，不增加下划线或第二个选中点；已有主导航活动点保留语义与位置。无距离自适应时长、随机时长、按下缩放或内容页面过渡。

### 3.2 单一像素与几何 owner

- 每个互斥组恰好一块底板；保留原按钮、原 QButtonGroup / 状态模型。底板透明于鼠标、无焦点，在文字图标之下。
- 使用按钮实际 `geometry()`；跨父级时映射到共同宿主坐标。不假定均分、不按索引乘固定宽度。按钮布局及命中 rect 不随动画改变。
- 主工具栏图标模式、Batch 固定间隔、图卡 toolbar QWidgetAction 宿主、字体/DPR/宽度变化均先测量再定位。不为底板重排工具栏。
- 只有启用底板的组抑制静态 checked 背景；关闭/减少动效恢复原端点样式。hover、pressed、disabled、focus 不能盖出第二块选中底板。
- 颜色、圆角、边框来自现有 owner / CONTROL_COLORS。禁止每帧修改 QSS、polish 全应用、重设布局或强制 processEvents。

### 3.3 触发、恢复与生命周期

| 事件 | 业务语义 | 视觉行为 |
| --- | --- | --- |
| 用户点击、现有键盘激活 / 快捷键 | 原 owner 执行一次；在原时点提交和发信号 | 从当前显示位置走到最终合法选项 |
| 重复点击当前选项 | 保留原 owner 信号合同 | 不重启动画；Batch 的 methodActivated 仍按原规则发出 |
| 动画途中改选 | 新真实状态立即生效 | 旧动画中断，从显示中的 rect 转向；不排队 |
| 外部 setter、combo 程序更新、预设应用、View / 项目恢复 | 业务信号保持原约定，不新增信号 | 直接定位；不整屏播放参数恢复动画 |
| 信号阻塞后同步 / mutable labels 刷新 | 使用现有显式 sync / refresh | 停止并取真实终点 |
| 同一调用栈引起其他控件联动 | 联动仍由业务 owner 决定 | 只有直接操作的组动，联动控件直接定位 |
| 显示、隐藏、resize、字体/DPR、窗口失活 | 不更改选项 | 停止并定位；再次显示不补播 |
| 自身或祖先禁用、单个选中按钮禁用 | 保留合法状态，阻止原本不可用操作 | 停止，显示对应禁用端点；不得恢复明亮白底或可点击提示 |
| 设置 Off / Reduced | 不发业务信号 | 停止并恢复静态端点 |
| 目标移除、owner 关闭 / deleteLater | 不修改业务 state | 清空/隐藏底板并释放动画；无失效 wrapper 回调 |

外部 setter 不添加必需位置参数，公共调用保持兼容。用户来源只在当前组的显式激活处理期间识别，并在重入或异常时清除；不增加 MainWindow 全局“正在用户切换”状态。不要通过窗口是否可见、鼠标当前位置或任意 combo 信号猜测来源。

N1 跟随 Toolbar 已确定模式；N2 保留 `methodChanged` 与 `methodActivated` 区别。C2 跟随 `_frequency_cursor_target()` 指向的真实目标，UI 同步不能再次修改 canvas；焦点目标变化直接归位。动画 finished 只结束呈现，绝不提交计算、恢复视图或改变 dirty 状态。

## 4. 实现边界与接口

### 4.1 共享驱动

在 `ValueDriver` 构造接口增加可选 keyword `easing=None`，默认仍为原 `EASING`；传入新曲线的选中背景 driver 才改变行为。复用已有 go / snap / clock / 当前值打断逻辑，不再创建第二套 timer 或动画框架。

新增 `mf4_analyzer/ui_kit/widgets/selection_indicator.py`，只负责共享底板、实测矩形、插值及生命周期。现有 SegmentedChoice 的底板行为迁入这个 owner，避免为二选一、五选一、图卡各复制算法。

拟定接口（新增，不代表当前已有）：

```python
SelectionIndicator(host, *, buttons, duration_name, style)
indicator.set_motion_policy(policy)
indicator.follow(button, *, animate=False)  # None 表示无合法目标，隐藏
indicator.snap_to_selection()              # 使用最近已确认目标重新测量
indicator.driver()                         # 只读观测已有 ValueDriver；可为 None
```

`style` 使用同模块不可变 `SelectionIndicatorStyle`，字段为 `fill`、`border`、`disabled_fill`、`disabled_border`、`radius`；由各 owner 的现有样式值构造，不引入第二套配色常量。`buttons` 为现有按钮的固定序列，校验共同 host 后按目标按钮映射坐标。helper 不接 clicked、不发业务信号、不创建 QButtonGroup、不读取 combo、不写 checked。

helper 的最近目标引用只用于呈现；绑定 `destroyed` 清理并检查 `sip.isdeleted()`。目标有效但暂时隐藏时仍保存其引用并停止/隐藏底板，重新显示后测量终点，不补播；目标移除或销毁才清引用。公共事件过滤仅用于几何/禁用/隐藏/销毁，不消费键盘或鼠标。原 SegmentedChoice 的公开 API 保持；私有实现迁移时调整相应测试观察点，不删除生命周期和像素断言。现有 `ui/motion_demo.py:_sample_active` 会读取 `_motion_driver`，SegmentedChoice 保留只读转发属性返回 helper.driver()，不另存第二个 driver。

### 4.2 显式启用策略

- 通用 `SegmentedChoice()` 和 `resolve_policy(None)` 继续默认关闭。
- 在 B1–B6 列出的实际创建点显式传 `POLICY_LIGHT`，N1/N2/C1/C2 的局部呈现 owner 显式启用同一策略。禁止 QApplication 全树扫描、全局 QWidget 注册表或修改所有 QPushButton。
- 已有 `set_motion_policy` 保留；新接入 owner 提供同名局部入口供测试和原生探针对照。所有入口均只是本实例策略，不写项目、预设或 QSettings。
- 本轮不新增偏好页面、OS 设置订阅或环境变量。Reduced 是可调用的实例合同，不宣称已自动跟随操作系统；正式用户偏好与系统接线列入后续范围。
- 不新增业务入口、命名或快捷键，本轮无需修改 `ui/hints.py` / `ui/quickref.py`；若实施改变其中任何一项，必须同时更新这两个文件及相关测试，不能偷偷扩大范围。

## 5. 验证与完成标准

需求 ID：R1=时长/曲线隔离；R2=单底板/几何；R3=用户来源与恢复；R4=信号/目标正确；R5=打断/生命周期；R6=覆盖范围与默认策略；R7=真实渲染及性能证据。

### 5.1 确定性合同

测试人工推进动画时间，检查 0/25/50/100% 位置、20 次快速反向后终态、相同目标不重启、业务信号次数、程序恢复无活动动画。覆盖 2/3/5 个不等宽按钮、键盘与 Ctrl+1…5 原入口、父级禁用、单按钮禁用、visible/hidden restore、字体、resize、deleteLater、Off/Reduced。

生产 QSS 比较按钮布局 / sizeHint / 实际 hit rect、端点、中间帧、焦点、禁用颜色及角像素；DPR 1/2 或平台可提供的等价缩放分别记录。静止后观察 500 ms，组件自有 driver inactive、自发更新 0；系统 expose 重绘不计入。不能只检查 QSS 字符串或父窗口截图。

### 5.2 原生 Cocoa 与 Windows

使用真实控件和生产 QSS，不把 HTML 当原生验收。场景至少包含 N1 空数据/缓存 FFT、N2 切换方法、B1 相位切换和应用预设、B5 每项单独导致布局禁用、C1 有数据布局与游标切换、C2 分屏焦点目标。

每场景 Off/Light 使用相同数据，预热 5 次、记录 40 次交替操作；单独记录首次访问。保存 HEAD、目标源码指纹、Qt/PyQt、OS、DPR、刷新率、业务信号计数、首个反馈 paint、动画结束、内容就绪、动画期间实际 paint 间隔和局部 paint 工作耗时。300/400 ms 候选不通过额外 sleep 或延迟业务伪造。

候选轻场景门槛：首次反馈 paint p95 ≤50 ms；局部 paint 工作 p95 ≤4 ms；输入回调相对 Off 的 p95 增量 ≤2 ms；60 Hz 参考下实际 paint 间隔 p95 ≤20 ms。阈值是设计目标，未测不是通过；高刷新率要同时记录帧预算。重计算场景另报 GUI 阻塞，不以拖慢逻辑或改 DSP/AA/settle 阈值掩盖卡顿。

探针动作 30 s、单场景 180 s 超时；保存部分记录并判 UNVERIFIED。Off 与 Light 的状态、信号、几何硬合同必须一致，异常退出不是 pass。

| Gate | 内容 | 当前状态 |
| --- | --- | --- |
| G0 | 两文档范围、路径、接口、覆盖映射与 diff 检查 | PASS：全文自检、现有引用及空白检查；不代表实施通过 |
| G1 | R1–R6 确定性 owner 测试 | 未实施 |
| G2 | 生产 QSS 真正底板/按钮像素及几何 | 未实施 |
| G3 | Cocoa 原生真实路径、40 次样本与动态观察 | UNVERIFIED |
| G4 | Windows 源码运行 100%/150%，焦点、禁用、缩放与动态 | UNVERIFIED |
| G5 | 相关 import / QSS / lambda / state / timer 边界 | 未实施 |
| G6 | 验证报告，按 P1 ID 和平台给结论 | 未实施 |

缺原生平台可完成实现和自动化检查，但只能交付 `partial`，不能声称全面验收；本 Plan 不包含发行包，Windows 冻结包为 NOT_IN_SCOPE。真实卡顿若需改变分析或渲染管线，记录 measured owner 和另案建议，不在此计划自动扩张。

## 6. 交付

实施阶段交付 P1 代码、测试、原生探针，以及新报告 `docs/analyzer/verify/2026-09-10-selection-slide-rollout.md`。原始 JSON、PNG、录屏、临时设置放 `.state/selection-slide-rollout/`，不自动提交。

本次只交付 Spec / Plan，不改 HTML 默认值、不改源代码、不运行产品测试、不写验证报告冒充执行完成。
