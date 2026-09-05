# TraceLab 原生交互动效第一轮 Spec

日期：2026-09-05 · 修订：R1 · 状态：**文档就绪，待实施；样板、性能数据及平台验收均未完成**。

配套文件：[实施 Plan](../plans/2026-09-05-native-interaction-motion-pilot-plan.md)。

## 1. 目标与第一轮边界

用户希望按钮、页面切换等操作更顺滑、有连续反馈，并要求先完成详细设计。本轮定义可执行的原生 Qt 样板和真实切换测量，确定后续推广的手感与技术边界。

第一轮有两个交付面：

1. **原生样板**：使用现有生产控件及生产 QSS，比较“当前方式 / 轻动效 / 减少动效”；覆盖按钮、开关、分段选择、View 标记、参数折叠、最近打开弹层和轻量页面过渡。
2. **真实路径测量**：测量现有 MainWindow 的 View 与分区切换，区分输入回调、首次反馈、内容就绪和稳定画面，不在此轮重构切换或渲染管线。

本次用户请求只授权编写本文和 Plan。后续明确要求按 Plan 执行时，实施者可以完成样板、测试、测量和报告，无需逐组件再次确认。样板的审美选择用于决定下一轮推广；没有风格反馈也应完成本轮可自动验证的工作并如实交付。

### 1.1 范围合同

| ID | 第一轮交付 | 激活边界 |
| --- | --- | --- |
| S01 | 普通动作按钮：primary / secondary / quiet / icon 四种代表角色 | 新样板按钮；不全局替换 QPushButton / QToolButton |
| S02 | 现有 PillSwitch 圆钮和轨道过渡 | 现有类增加显式、默认关闭的动效入口 |
| S03 | 现有 SegmentedChoice 选中底板过渡 | 隐藏 QComboBox 继续拥有真实状态 |
| S04 | 现有 ViewTabBar 选中装饰标记过渡 | 仅样板实例开启；标签布局、命中和管理器不变 |
| S05 | 现有 _CollapsibleParamSection 展开/收起 | 样板内真实参数区，隔离设置；不接入整个 Inspector |
| S06 | 现有 RecentOpenPopup 入场过渡 | 使用临时合成记录，open/clear 意图只记录，不打开或清除用户文件 |
| S07 | 一个轻量双页面过渡样板 | 仅样板宿主；不对真实 ChartStack 或图表加动画 |
| M01 | MainWindow 时域 View 切换测量 | 真实信号和恢复路径、合成测量数据 |
| M02 | TimeDomain ↔ FFT 分区切换测量 | 通过真实 Toolbar 模式入口，不绕过 MainWindow 协调 |

非目标：全局启用动效、修改主程序启动行为、增加正式用户偏好入口、窗口/侧栏宽度动画、图表交叉淡化、曲线变形、列表惯性滚动、实时模糊、阴影动画、QML/Web 改写、Qt 升级、数值算法修改、发布版本。

首轮弹层选择 RecentOpenPopup，原因是它有独立的展示/意图边界和现成键盘测试。当前通道编辑、Batch、UltraView 等窗口正在进行布局工作，不把它们并入本轮试验。

### 1.2 判定标准

- “能动”不是验收；必须同时具备连续反馈、正确终态、操作不被动画拖延、稳定几何和可复现证据。
- 样板使用生产类不等于生产默认行为已变；真实分区测量不等于给分区加了动效。
- 原生样板、offscreen 测试、Cocoa 自动探针、前台体验、Windows 原生运行和 Windows 冻结包分别记录。

## 2. 当前源码事实及约束

本次读取基于 `main@e5ec1fa9a52f6316fe14f0c1af24dc2e9d1e7c0e` 加在途工作区；该 HEAD 只标识调查时点，实施前重新记录目标文件指纹。本地库查询：Qt 5.15.14、PyQt 5.15.11、pyqtgraph 0.14.0。以下是源码事实，不是性能实测。

| 已读取 owner | 当前事实 | 设计含义 |
| --- | --- | --- |
| `mf4_analyzer/ui_kit/control_style.py`、`style.qss` | 已有角色、颜色和 24/32/36 高度轨道；按钮主要依赖 QSS 状态切换 | 延续 token 和尺寸，不另建配色/量度体系 |
| `mf4_analyzer/ui/widgets/pill_switch.py:PillSwitch.paintEvent` | 44×24 自绘，圆钮按 isChecked 直接取左右端点 | 在同一个 painter 中插值，不叠第二个轨道 |
| `mf4_analyzer/ui_kit/widgets/segmented_choice.py:SegmentedChoice` | 两个 checkable 按钮映射隐藏 combo；提供显式同步入口 | 动效只是展示，不能增加第二套参数状态 |
| `mf4_analyzer/ui/view_tabbar.py:_ViewTabs / ViewTabBar` | 原生标签绘制后追加色块/关闭图标；refresh 会重建标签；重排中禁止重建 | 动效不绑定易变化的旧 index，不改关闭命中 |
| `mf4_analyzer/ui/inspector_sections/collapsible.py:_sync_expanded` | 立即设置箭头、body 可见性并保存展开意图 | 显示进度不进入 QSettings；展开意图立即确定 |
| `mf4_analyzer/ui/widgets/recent_open_popup.py:show_at` | 先定位再 show/focus，关闭与打开信号已有去重；当前最大宽度常量为 640 | 不用历史 HTML 的 800px 覆盖现有几何 |
| `mf4_analyzer/ui/widgets/toast.py` | 已有 180ms opacity 动画及重入处理 | 作为节奏参考，本轮不修改 Toast |
| `mf4_analyzer/ui/main_window/_view_mixin.py:_render_view_onto_canvas` | 控件恢复→绘图→X/Y 恢复→settle→树投影 | 不把动画 finished 接到恢复或业务提交上 |
| `mf4_analyzer/ui/main_window/window.py:_enter_fft_mode` | signature 未变时复用现有曲线 | 测量冷热路径，禁止把缓存命中和初次构建混为一组 |
| `scripts/probe_view_switch_quality.py:_time_mainwindow_section_round_trip` | 当前只做 ChartStack 切换和固定 300ms settle，源码注明不是性能读数 | 不用该字段声称完整分区切换耗时；新探针走 Toolbar→MainWindow |

现有约束继续成立：View 使用 manager.max_views；当前时域 24、分析 12；View 后接 `+`、管理入口，动作按钮 28×28；active tab 可见；全名 tooltip、重排、重命名、overflow 和关闭指针重新进入规则保留。

相关历史依据只用于解释边界：[控件视觉系统](2026-08-09-global-control-visual-system-spec.md)、[桌面交互合同](2026-09-02-standard-desktop-interaction-contract-spec.md)、[View 恢复结算](2026-08-15-view-switch-quality-settlement-spec.md)。冲突时以当前代码、可执行合同和本轮已明确范围为准，不能把旧文档完成状态当作当前验收。

## 3. 手感、时间与通用行为

### 3.1 第一版固定参数

以下为候选设计值，未经真机标定；调整必须同步本文和 A/B 证据，不能为通过性能门禁临时放宽。

| 效果 | 时长 | 曲线 | 范围 |
| --- | ---: | --- | --- |
| hover 进入 / 离开 | 100 / 80ms | OutCubic | 背景、边框颜色；尺寸不变 |
| 按下 / 释放 | 按下立即 / 80ms | 释放 OutCubic | 当前 press 色；不缩放命中框或移动文字 |
| 开关 | 160ms | OutCubic | 圆钮左右位置、轨道颜色；无越界回弹 |
| 分段底板 | 160ms | OutCubic | 在实际两个按钮 rect 之间移动 |
| View 装饰标记 | 140ms | OutCubic | 标签内部底边 2 个逻辑像素高标记 |
| 折叠展开 / 收起 | 180 / 140ms | OutCubic | body 裁剪高度与箭头旋转 |
| 最近打开入场 | 140ms | OutCubic | 内容 opacity 0→1；窗口外框已在最终位置 |
| 轻量页面入场 | 140ms | OutCubic | 目标轻量内容 opacity 0→1；无双页同时实时绘制 |

不使用 spring、bounce、overshoot。上述时长是插值的墙钟时长，不是为了开始执行动作而设置的延迟。启用某项动效时只更新其像素所有者，禁止每帧拼接/安装 QSS、全局 polish、主动 processEvents 或全窗口 repaint。

### 3.2 激活与所有权

- `MotionPolicy` 为拟新增的不可变策略值，包含 `enabled`、`reduced_motion`；时长表由共享 motion 模块唯一持有。未传策略时等同关闭，不创建活动动画。
- 现有控件通过拟新增的 `set_motion_policy(policy)` 显式启用；保留原构造签名和公共 imports。样板宿主持有选择并逐实例传入，不用父链属性猜测策略。
- “当前方式”：走原绘制/显示路径，无新动画；“轻动效”：启用本表；“减少动效”：保留终态反馈，所有本轮插值归零。减少动效与当前方式在业务、终态外观、尺寸上等价。
- S04 的新增装饰线仅在“轻动效”样板出现；切回当前方式/减少动效时移除，仍由原选中背景表达 active。三种模式的这一视觉差异要在样板说明中写清，不能把新增装饰当作动画性能收益。
- 第一轮模式选择只属于样板，不写用户设置，不自动读取或修改系统设置。后续产品偏好和操作系统减少动效适配另行定义。
- 每个 widget 拥有自身动画/呈现状态；共享模块不拥有全应用控件列表，不读取 MainWindow、文件、项目或分析状态。
- 改策略为关闭/减少动效时，停止进行中的动画，落到当前业务状态对应终点，清理本轮效果；业务信号发射次数为零。

### 3.3 状态与输入合同

| 触发 | 必须行为 |
| --- | --- |
| 鼠标按下 | 立即保持既有 press/release/cancel 语义；不会提前执行 clicked |
| clicked / toggled / currentIndexChanged | 原业务状态及信号在原时点确定；动画只追随已确定状态 |
| 新目标在动画中到达 | 停止旧目标，从当前显示值转向新目标；不排队播放旧动作 |
| 相同目标重复同步 | 不重启动画，不增加业务信号 |
| 外部 setChecked / combo 更新 | 状态立即正确；允许展示追随；blockSignals 的恢复路径必须能显式同步并落到终点 |
| 隐藏页面上的程序恢复 | 直接呈现终态；之后显示不补播历史操作 |
| 禁用、窗口失活、隐藏 | 清 press/hover 瞬态，停止动效并同步合法终态；不在后台跑计时器 |
| owner 销毁/内容替换 | 停止动画、断开所拥有连接；旧回调不能访问删除的 Qt wrapper 或覆盖新目标 |
| 键盘 Tab/Space/Enter/Esc | 保持原 owner 路由、焦点框、默认按钮、IME 与文本输入语义；动画不消费按键 |

业务模型不等待动画，动画 finished 只清理呈现。业务意图不能存进动画队列；延迟回调如确有必要，必须有 owner 生命周期和 generation 校验，不能使用零散 silent getattr 守卫隐藏必需状态。

## 4. 各样板详细合同

### S01 — 动作按钮

拟新增 `MotionButton(QPushButton)`，仅样板创建，不猴子补丁原 Qt 类。覆盖四个标准 role；icon 用只带图标的 QPushButton 样本，第一轮不宣称已支持全部 QToolButton/menu/auto-repeat 专用路径。

复用 CONTROL_COLORS、字体、图标和尺寸；颜色插值位于单一 chrome painter。文字、图标、焦点、默认与 disabled 表达必须完整；不能让 QSS/native 面板和自绘面板重复覆盖。关闭动效时走现有标准按钮路径，启用后的端点与标准按钮同角色一致，允许平台 AA 边缘差异。

32px 普通按钮、28px/24px 紧凑图标代表均纳入比较；hover/press/focus/disabled 不改变 minimumSizeHint、layout rect 或 hit rect。不给危险操作增加炫目反馈，本轮不接入真实删除、保存或计算动作。

### S02 — PillSwitch

仍为 44×24；逻辑 checked 由 QAbstractButton 拥有。只把当前圆钮位置和颜色从二值绘制改为可插值属性。快速开→关→开时无位置跳回起点、无额外 toggled。

标签点击、Space、disabled 父容器、setChecked、blockSignals 后 setChecked 均需覆盖。初始化、隐藏状态恢复、减少动效时直接取终点；不存在“参数已关但最终圆钮停在开”的情形。

### S03 — SegmentedChoice

保留隐藏 combo 的 currentData/currentIndex、mutable labels/tooltips、互斥按钮和现有同步 API。颜色和底板呈现不回写 combo。

轻动效时只有一块移动选中底板，两个按钮不再额外画第二块选中背景；文本及 checked 状态立即更新，底板透明于输入。布局总高保持 32px。参考位置取最终实测按钮 rect，不能写死为父宽一半。

resize、字体变化、标签刷新、隐藏恢复时停止并吸附到真实终点；不在布局事件中连续启动追逐动画。`sync_from_bound_combo()` 在信号被阻塞时能确定性同步终态。

### S04 — ViewTabBar

只在既有选中标签底边内部增加 2px 装饰标记；不替换当前选中背景、色块、split 颜色或关闭图标。运动不能越过可见 strip，也不能覆盖文字；无有效 rect 时直接隐藏标记。

只跟随管理器确认的 active View，以稳定 view_id 定位，不能把未执行的 switch_requested 当作已激活。样板接线为 intent→真实 ViewManager→active_changed，不通过动画修改 manager。

切换且前后标签在同一稳定布局中可见时移动；refresh、增删、重排、compact/overflow 改变、字体/DPR/窗口尺寸变化时直接重新定位。**第一轮不做标签增删收缩或拖拽排序动画。** 为动效不能改写 refresh 或解除重排期间禁止重建的保护。

命中由既有 tab_close_hit_rect 所有。非当前标签色块点击仅切换；成为当前后仍须离开并重新进入色块，才可关闭。装饰层没有鼠标/焦点能力。保留 28×28 动作按钮、顺序、overflow 数量和 manager 上限。

### S05 — 参数折叠

展开意图、按钮 checked 与持久化按既有语义立即确定；高度进度和箭头角度不写设置。样板给 section 注入独立 INI 设置。

展开：body 以目标宽度完成布局后从当前裁剪高度展开。收起：若焦点位于 body，先移到 collapser；立即让 body 退出 Tab/鼠标访问，再播放收起展示。可以使用 bounded body 宿主控制临时交互屏蔽，但不得通过禁用整棵业务控件而改变其持久 enabled 状态。

结束必须释放临时 min/max 高度和输入屏蔽，最终遵守原内容尺寸策略。内容替换、字体/宽度改变、宿主隐藏或缩放变更时停止并按意图完成布局。持久区一直可见；反复展开不能遗留空白或压缩后续字段。

只改变样板内 Inspector 列的局部布局；不改变主窗口分隔器或图表宽高。原生 frame 和 child backing 必须检查圆角/裁剪像素。

### S06 — 最近打开弹层

沿用 RecentOpenPopup 的 populate/reset_for_show/show_at、屏边 clamp、搜索、选中、open/clear/closed 去重和焦点恢复。采用临时目录生成的测试记录；打开意图进入样板日志，不连接生产文件打开函数。

最终窗口 rect 在显示前确定并保持；只在有限内容子树上做一次 opacity 入场，不移动顶层窗口、不改变外框圆角和锚点。效果只能挂在本组件独占且不存在其他 effect 的宿主，不覆盖既有 graphicsEffect；通过普通数据加载与 owner repaint 完成显示，禁止逐帧 raise_。

show 当次即给搜索框焦点。入场期间发生键盘输入或内部点击，先结束入场至可读终态，再把同一个事件交给原 owner 一次，不重放鼠标。Esc、外部点击、open、clear、宿主关闭均按当前路径立即收起，**不等待淡出**。Qt.Popup 退出抓取与焦点合同优先，第一轮不做关闭动画。

重复显示从合法初态开始；resize/clamp 变化时结束动效并重新定位。取消后不得被旧 finished 回调隐藏新打开的弹层。若平台透明效果确实不支持，以可检测的状态报告并直接显示，不能吞掉任意绘制异常。

### S07 — 轻量页面

样板宿主使用两个常驻轻量 QWidget 页面，内容为真实文字/字段控件；标签清晰标示“轻量页面示例”，不得冒充已优化的 TimeDomain/FFT。可视区域不超过 640×420 逻辑像素。

点击后立即改变目标页和标题，旧页隐藏，目标页做一次短淡入；没有旧页快照、双 live chart、全窗口 opacity 或额外截图缓存。输入到达时先结束淡入，保证正在操作的内容可读。快速 A→B→A、父关闭、目标销毁均不留下旧覆盖层。保留目标字段值和正常 Tab 顺序。

实现先留在样板宿主，不提前抽象全应用 AnimatedStack。是否能用于真实图表页由 M01/M02 结果决定，属于后续范围。

## 5. 原生样板宿主

拟新增入口：`python -m mf4_analyzer.ui.motion_demo`。它是显式诊断入口，不改 `mf4_analyzer.app`、普通启动流程、主菜单或发行包。

- 使用当前字体初始化、Fusion/生产 QSS；程序入口调用前先完成临时 QSettings 路径隔离。显式 NativeFormat 或硬编码组织名路径也必须检查，不能只换 applicationName。
- 顶部仅提供“当前方式 / 轻动效 / 减少动效”以及复位；内部采样数据放在可折叠诊断区，不能挤占体验区。
- S01–S07 按实际窗口可用空间排布；窄窗口允许滚动。各模式复用同一套尺寸和内容，不通过不同排版制造视觉优势。
- 单次点击只在对应样本发生真实语义动作，不能为了联动三列额外触发业务；自动 A/B 使用同一场景顺序重放于独立实例。
- 日志记录 sample_id、目标值、业务信号次数与动效状态；默认不记录用户路径或通道内容。关闭后停止所有样板活动动画和测量计时器。
- 测试导入模块不得创建 QApplication、窗口或安装 QSS；入口才做初始化。测试必须还原 QApplication stylesheet，不能污染后续 owner 测试。

## 6. 真实切换测量与性能合同

### 6.1 M01/M02 场景

拟新增 `scripts/probe_interaction_motion.py`，依赖单向为脚本→UI，不让产品控件导入脚本。复用现有探针已证明有用的窗口暴露检查、定时和夹具思路，不复制整个旧脚本，不修改其历史指标含义。

| 场景 | 固定输入及操作 | 结果分类 |
| --- | --- | --- |
| M01-small | 合成 2 通道×10,000 点，明确生成时间轴、单位和 1,000Hz 采样率；相同 subplot 布局两个 View | 首次访问与 warm 切换分别报告 |
| M01-dense | 合成 8 通道×1,000,000 点，明确 20,000Hz；固定随机种子；subplot↔subplot、subplot↔overlay | 保留密度、隐藏通道、最终 X/Y 和曲线 identity 事实 |
| M02-empty | 无数据时 TimeDomain↔FFT | 轻页面骨架与控件投影成本 |
| M02-cached | 使用 M01-small 数据完成一次正常 FFT 计算，待任务真正完成后开始采样；TimeDomain↔FFT | 缓存存在且签名未变；验证无额外计算提交 |

生成的时间轴只属于显式合成夹具，不向真实数据推定采样率。M01 从真实 tab 点击路径采样，M02 从 `Toolbar._set_mode` 的按钮/信号入口进入 `MainWindow._on_mode_changed`。方法直调只用于归因对照，必须标为 `entry_kind=direct_call`，不能混入点击延迟统计。

夹具采用 float64、共享时间轴 `t = arange(n) / fs`；基础信号为第 i 通道的 `sin(2π·(11+7i)·t) + 0.15·sin(2π·(47+3i)·t)`，i 从 0 开始，单位明确为合成 Nm。dense 组再加 `0.02·standard_normal(n)`，使用 `default_rng(20260905)` 按通道顺序生成。记录生成配置和数组摘要；A/B 使用相同数据。只把这些夹具的结论推广到对应条件，不声称代表所有真实 HDF/WWT。

warm 组先执行 5 次预热，再记录至少 40 次交替操作；首次访问采用 5 个新进程，报告原始值/范围，不用 5 个样本声称可靠 p95。两种样板模式按 ABBA 分组交错，串行运行，同一机器、窗口、DPR、前台暴露状态和源指纹。120Hz 设备单独记刷新率，本轮不承诺 120fps。

### 6.2 时间边界与证据含义

| 指标 | 明确定义 |
| --- | --- |
| input_callback_ms | 输入事件进入 owner 到该调用返回；不包含人为 settle wait |
| feedback_paint_ms | 输入进入到第一个实际含目标反馈的 widget paint 完成；使用事件序号/目标身份关联，不能取任意一次 paint |
| content_ready_ms | 目标 View/分区状态、目标内容数据和最终几何恢复已完成；M02 cached 还检查目标缓存与选择一致 |
| stable_paint_ms | content_ready 后最终目标画面第一次 paint 完成；与进度变化中的过渡帧区分 |
| paint_work_ms / paint_interval_ms | 单次实际绘制工作及同一个活动动画内相邻实际 paint 间隔，分别给原始序列、p50/p95/max；不跨静止段合并，不把 QTimer tick 次数当帧数 |
| event_loop_lag_ms | 探针心跳计划时间与真正执行时间之差，独立于动效计时器 |

Qt paint 完成不是操作系统上屏时间。JSON 必须写 `presentation_timestamp_available=false`，除非获得真实 presentation 时间戳；录屏用于检查跳闪/节奏，其采集帧率单独记录。未暴露窗口、没有实际 paint、超时、异常或相关源码运行中变更的场景一律 `UNVERIFIED`。

输出 `schema_version=1`，顶层为 `environment`、`source_snapshot_before/after`、`scenarios`、`errors`；每个 scenario 包含配置、entry_kind、cold/warm、原始 events/paints、派生 statistics、final_state 与 status。窗口/来源/动作 ID 必须可关联。关闭/减少动效没有活动动画时，paint_interval 使用 null 和 `not_applicable`，不能填零帧时间参加“更快”比较。

超时预算为单次动作 30s、单组采样 180s；初始化/首次计算另列，单次预算 30s。触发后保留已经采到的原始记录并停止该场景；性能达标预算和防挂死超时不是同一个标准。

既有 `_time_mainwindow_section_round_trip` 中含 300ms 等待的 ms 值不得导入以上统计。新 probe 不能靠 `sleep(动画时长)`、多次 processEvents 后再取时间伪造首帧边界。自动操作由事件循环安排；静止确认发生在测量边界之后。

### 6.3 第一轮预算与失败处理

| 范围 | 候选预算/硬合同 | 门禁用途 |
| --- | --- | --- |
| S01–S07 无重计算轻场景 | feedback_paint p95 ≤50ms；激活动作不增加等待动画的延迟 | 设计目标，超标需定位 |
| S01–S07 动效期间 | 60Hz 参考下实际 paint_interval p95 ≤20ms；无样板引入的 >50ms 长间隔 | 同时报告设备刷新率及录屏，不用 offscreen 判断 |
| 动效的局部绘制工作 | paint_work p95 ≤4ms；输入回调 p95 相对关闭模式增量 ≤2ms | 若超标检查绘制范围/布局，不调整 DSP 门槛 |
| 静止后 | 所有样板自有动画停止；settle 后观察 500ms，自有定时器触发和动效发起 update 次数为 0 | 硬合同；窗口 expose 的系统 repaint 不计作违规 |
| 隔离与生命周期 | 业务信号次数等价、最终状态正确、无访问已删除 wrapper、无真实设置变更 | 硬合同 |
| M01/M02 | 完整原始测量和正确性事实；第一轮不承诺固定大数据切换时限 | 形成下一轮优先级，不把现有慢帧包装成动效收益 |

本轮不新增页面截图缓存；小弹层 opacity 可能产生的内部合成缓冲按生命周期释放。记录 100 次显示/隐藏后的 RSS 序列与 live QObject/animation 计数；RSS 未立即下降不单独判泄漏，重复增长与存活对象需联合定位。

数字是本轮候选预算，不替换 `render_profile.py`、quality/AA、150ms 交互 quiet window、discrete settle 或历史图表 benchmark 的阈值。表现未达预算时优先缩小重绘范围或取消该样本过渡，报告失败项，不以插入额外等待“修好”测试。

## 7. 验收矩阵

| Gate | 验证内容 | 第一轮当前状态 |
| --- | --- | --- |
| G0 文档 | 范围、引用、owner、合同和 Plan 对应，无实施状态误报 | PASS：已全文复核、校验本地引用与空白 |
| G1 确定性合同 | S01–S07 的输入、信号、终态、打断、减少动效、销毁、默认关闭 | 未实施 |
| G2 像素/几何 | 生产 QSS，DPR 1/2 端点与中间帧；真正像素 owner 的截图 | 未实施 |
| G3 Cocoa 原生 | 样板及 M01/M02 有实际暴露/paint；前台录屏与主观体验另列 | UNVERIFIED |
| G4 Windows 原生 | Windows 10 或 11 源码运行，100%/150% 缩放；弹层/字体/焦点/动态验证 | UNVERIFIED |
| G5 边界与默认行为 | 原 owner 测试、依赖方向、QSS/信号/QSettings 防污染 | 未实施 |
| G6 决策报告 | 每个 S/M 的结论、预算结果、可推广组件及剩余问题 | 未实施 |

必测交互：快速切换 20 次；按下后拖出/释放；父禁用；动画中隐藏、关闭、deleteLater；切换策略；窗口 resize；View overflow 与关闭重入；popup Esc 清空再关闭、外点、输入、重复打开；折叠中焦点与内容替换。

确定性测试通过人工推进 animation currentTime/控制时钟检查 0/25/50/100% 进度，不用任意 sleep 判数值终态。视觉测试同时截真正 self-painted child，不能只截父窗口就推断子层正确。Cocoa/Windows 动态检查不能由静态截图替代。

G1/G2/G5 通过但缺 Windows 时，允许交付“样板实现完成，跨平台验收 partial”，不修改普通生产默认、不宣称全面可推广。冻结包不是首轮交付门禁，状态独立为 `NOT_IN_SCOPE`。

## 8. 不可破坏的工程合同

- ui_kit 不导入 ui/MainWindow/acquisition_ui；真实样板组装放在 ui 层，测量脚本从外部调用。
- 不新增 MainWindow 状态字段或跨 mixin 写入；不移动 DSP，不重新计算 FFT 只为播放动画。
- View 恢复仍在最终几何结算一次；不能让折叠/弹层动效每帧驱动图表质量切换。
- 不改变项目 schema、View/channel/source identity、dirty 状态、最近文件顺序或真实设置。
- 动效连接有明确 owner；不添加新的 `.connect(lambda ...)`，不增加宽泛异常吞噬或每帧日志。
- 生产交互未新增/重命名，第一轮无需改变 `ui/hints.py`、`ui/quickref.py` 的用户文案；后续若加入正式偏好或入口，必须成对更新这两个 owner。
- 与在途弹层布局工作共享文件时，重读最新实现并做最小增量；不回退屏幕适配，不覆盖别人的修改。

## 9. 第一轮输出与推广决策

实施交付包括原生入口、组件与探针代码、聚焦测试，以及 `docs/analyzer/verify/2026-09-05-native-interaction-motion-pilot.md`（实施时新增）的结论报告。PNG、视频、原始 JSON 和临时 INI 放在 `.state/native-interaction-motion/`，默认不提交生成物。

报告逐项使用 `PASS / FAIL / UNVERIFIED / NOT_IN_SCOPE`，同时给：观察到的现象、信号/几何证据、机器与数据条件、候选预算差距、下一步最小动作。不得用一个“整体通过”掩盖平台或真实切换缺测。

需要样板体验后决定的只有风格/推广选择：哪些组件启用、速度是否舒适、哪些页面值得进入下一轮。默认候选就是 §3 的短促轻动效；实施者无需等待这些审美反馈才能完成既定样板与测量。

粗估：第一版可体验样板约 3–5 人日；完整本轮含七类样本、打断/生命周期测试、真实路径探针与双平台记录约 7–12 人日。假设实施者熟悉项目且有可用 Windows 环境；这是工程估算，不是交付日期承诺。全局推广、深层卡顿修复和更换界面技术均不计入。

## 10. 技术参考

- [Qt Animation Framework](https://doc.qt.io/qt-6/animation-overview.html)：属性插值、缓动和动画所有权；这里只使用当前 Qt 5 已具备的 API，不据 Qt 6 文档引入 Qt 6 专有能力。
- [Qt Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html)：QWidget 操作与事件循环所在 GUI 线程的边界。
- [Qt Style Sheets Reference](https://doc.qt.io/qt-6/stylesheet-reference.html)：QSS 负责样式表达；本设计不把网页 CSS transition 当作可直接使用的 Qt 样式属性。
