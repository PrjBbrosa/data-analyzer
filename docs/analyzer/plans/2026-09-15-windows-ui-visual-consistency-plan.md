# Windows 打包界面可见性与跨平台一致性优化计划

日期：2026-09-15。状态：**计划就绪，产品修改待执行；Windows 实际包验收未完成**。

## 1. 目标、依据与范围

修复通道树选中后展开箭头消失的问题，消除关键图标依赖运行环境而缺失的失败路径，并针对 macOS / Windows 的颜色、字体与缩放差异建立可重复验收。关键操作应清晰可辨、文字不裁切、布局不跳动；不要求两个系统的字体抗锯齿逐像素相同。

本轮用户授权为编写计划，不包含产品实现、构建、发布或提交。后续按本计划执行时采用单协调者、顺序推进；不要求子代理。

分析基线为 `f28f5820`。分析时已有未跟踪文件 `docs/analyzer/reviews/2026-09-15-interaction-smoothness-audit.md` 与 `ssh-keygen`，均与本计划无关。实施前重新检查 HEAD 和工作区；历史结果不能代替新快照的验收。

### 已确认与待验证事实

| 分类 | 事实与来源 | 结论边界 |
| --- | --- | --- |
| 已确认源码缺口 | `ui/widgets/channel_tree.py:_CheckTolerantTree.__init__` 仅在 `sys.platform == "darwin"` 时开启 `_repaint_selected_expander`；`drawBranches` 对其他平台不补画父节点箭头 | Windows 没有获得现有深色矢量箭头修复 |
| 已确认绘制机制 | `ui_kit/style.qss` 的 `QTreeWidget#channelTree::branch:selected` 只定义背景；Qt 的 `PE_IndicatorBranch` 遇到可绘制 QSS 分支规则后不再调用默认分支绘制 | 该问题可表现为箭头完全没有绘制，不仅是对比度低 |
| 已完成局部探针 | macOS offscreen，Qt 5.15.14 / PyQt 5.15.11，DPR=1，生产 `MultiFileChannelWidget` 加载实际 QSS：补画开关开启时，展开/收起各检测到 28 个深色像素；关闭后选中区域只有 `#b7d3f2`，深色像素为 0 | 验证了绘制路径差异；不是 Windows 源码运行或 frozen 验收 |
| 已完成因果对照 | 仅在探针内移除选中分支背景规则后，默认箭头恢复，但分支背景变为 `#308cc6` | 不能直接删除规则作为完整修复，否则破坏连续选中底色 |
| 已确认风险路径 | `ui_kit/stylesheet.py:load_stylesheet` 在图标缓存生成异常后继续加载缺图样式；`ui_kit/icons.py:ensure_icon_cache` 未检查 `QPixmap.save()` 的布尔返回值 | 存在箭头/勾号缺失路径；没有证据表明用户的 Windows 包触发了它 |
| 已确认环境差异来源 | 应用已设置 Fusion；控件字体按系统字体回退；部分图标固定 2x，部分按 DPR 生成；PyQt5 未锁定，两个 Windows 脚本会升级 qtawesome | 属于横向检查对象，不能直接计为 Windows 故障数量 |

源码位置均以仓库根下 `mf4_analyzer/` 为前缀。Qt 机制参考：[Qt 5.15 QStyleSheetStyle 分支绘制](https://github.com/qt/qtbase/blob/5.15/src/widgets/styles/qstylesheetstyle.cpp#L4265)。局部探针图片在 `.state/windows-style-audit/`，是可丢弃本机证据，执行阶段须补齐可重放脚本和 JSON。

### 本轮边界

- 必做：通道树跨平台箭头、关键 QSS 图标缺失保护、定向横向检查、Windows 源码与 Full/Lite 实际包对照。
- 证据触发后修改：Inspector 折叠箭头、菜单/列表选中色、字体导致的局部裁切、分数缩放或跨屏图标问题。
- 保持已有 Fusion、浅色主题、选中底色及尺寸体系。复用 `control_style.py`、`layout_diagnostics.py` 和现有弹窗外壳；不建立第二套主题或日志系统。
- 不进行全局换字体、Qt 主版本升级、DSP/图表算法修改、MainWindow 状态重构、持久化格式变更或历史对话框迁移。新字体打包与全局视觉重设计属于后续独立任务。
- 本计划只调整绘制与健壮性，不增删或重命名交互。若实现需要改变用户操作或提示含义，须先写明范围，并同步 `ui/hints.py`、`ui/quickref.py`。

## 2. 视觉与行为契约

| 编号 | 验收要求 |
| --- | --- |
| V1 | 所有支持展开的 file/source/raster/record-group 父节点，展开/收起、选中/未选中、窗口激活/失焦时均有可辨方向指示；叶节点不出现假箭头 |
| V2 | 箭头使用同一矢量几何和状态颜色规则，主路径无 Darwin-only 补丁；绘制不改变 Qt 的缩进、点击热区、键盘左右键、拖动与复选框行为 |
| V3 | 选中行主体、分支槽和末列动作底色连续为 `#b7d3f2`；不引入每格圆角、圆形箭头底座或脱离行体的动作胶囊 |
| V4 | 图标缓存不可写、图片保存失败或缓存损坏时，下拉箭头与勾号仍有可读资源；异常进入现有日志，不以未替换占位符完成启动 |
| V5 | 新增正常可操作指示图形的实体颜色与实际底色对比度至少 3:1；抗锯齿边缘不要求每个像素达到该值。禁用态使用独立状态规则并能与可操作态区分，不强制套用正常态阈值 |
| V6 | 两个平台中英文/长通道名不越界，保留当前省略和完整 tooltip 语义；图标在 100%/125%/150%/200% 下不消失或裁边，跨屏后尺寸与清晰度保持有效 |
| V7 | 检查不改变用户实际 QSettings、最近打开记录或项目内容；临时文件、截图和探针证据放 `.state/`，不默认加入 Git |

## 3. 实施任务

### T0 — 固定复现与环境证据

**产出：** 可重放探针（拟新增 `scripts/probe_ui_visual_consistency.py`）、证据 JSON 与截图；先不改产品行为。

1. 复用生产控件、正式 QSS 和最小合成数据，生成多层 file/source/raster、记录分组、普通通道叶节点。用结构化身份定位，不能依赖显示名称。
2. 在修复前用实例绘制开关复现当前补画/默认路径。修复后用同一状态集验证新的公共路径，不为了测试继续保留平台分支。
3. 每个状态记录控件/箭头槽矩形、实际 DPR、颜色与像素区域，保留完整控件图和局部裁剪图。像素坐标必须从逻辑坐标转换，不能把 DPR=1 的坐标直接用于 Retina。
4. 复用 `ui_kit/layout_diagnostics.py` 收集 Qt/PyQt、QSS 标识、样式和屏幕信息；补充实际控件 `QFontInfo` 解析字体、Qt/qtawesome/PyInstaller 分发版本、平台、frozen 状态、构建 flavor/提交标识。未知项记 UNKNOWN，不能用请求字体代替实际字体。
5. Windows 对照使用同一提交、同一虚拟环境分别源码启动和构建 EXE，记录包内实际版本；先确定差异发生在操作系统、依赖版本还是冻结资源层。构建环境暂不可用时继续 T1/T2 的本机工作，Windows 行保留 UNKNOWN。

**验证：** 对影响 owner 运行 T1 列出的现有选中行测试；运行探针并确认“补画关闭时箭头缺失”的前置红证据。无需前置全量套件。

### T1 — 通道树统一绘制（优先交付）

**文件 owner：** `ui/widgets/channel_tree.py`、必要的 `ui_kit/style.qss` 局部规则、`tests/ui/test_channel_widget.py`。

1. 先增加非 Darwin 路径回归，覆盖展开/收起和多层父节点。不能仅在 macOS 默认实例上运行原可见性测试；不能用关闭缺失箭头检查、放宽阈值的方法让测试变绿。
2. 将现有箭头矢量绘制收敛为所有平台、选中与未选中状态共用的 owner 内部函数。正常状态采用现有深色 `#334155`；禁用状态单独派生。移除 `_repaint_selected_expander` 的平台开关及“其他平台保留原生 glyph”的陈旧分支/注释。
3. 明确父节点箭头槽的背景与图形绘制顺序。接管槽时覆盖旧原生箭头，避免双箭头；背景取当前行状态，选中态沿用 `_ChannelLeafDelegate.SELECTED_BG`。不误覆盖叶节点轴组徽标、记录绑定行或更深层缩进区域。
4. 复用 Qt 提供的分支矩形与方向信息定位当前节点槽，保留当前 LTR 外观；若支持 RTL，则按方向映射，不能只固定右边缘。不得调用 `QMacStyle.drawPrimitive`。
5. 对正常颜色做对比度检查；像素测试同时确认图形存在、展开方向不同、包围盒在槽内及连续选中底色，避免“找到任意一个深色像素就通过”。

**聚焦门禁：** `tests/ui/test_channel_widget.py`（优先三项现有选中行渲染用例与新用例，再运行该 owner 文件）、`tests/ui/test_file_navigator.py`；修改 QSS 后运行 `tests/ui_kit/test_qss_border_shorthand.py` 和 `tests/ui_kit/test_stylesheet_parses.py`。macOS Cocoa 原生 show/render 加正式 TraceLab 前台检查；Windows 结果独立记录。

### T2 — 关键图标资源失败保护

**文件 owner：** `ui_kit/icons.py`、`ui_kit/stylesheet.py`；拟新增 `tests/ui_kit/test_icon_cache.py`。若增加兜底资源，放应用已有图标资源树并同步实际使用的打包入口。

1. 保留正常缓存命中路径与现有视觉。对 `save() == False`、非空但不可解码 PNG、目录/写入权限异常分别建立故障注入测试。只捕获已知资源/IO失败，不把任意编程错误改成静默降级。
2. 为实际 QSS 消费的下拉箭头和复选框勾号准备随包的只读 PNG 兜底，覆盖正常、hover/按下（实际使用时）、禁用与已选禁用。以现有图标定义为生成来源，附可重复生成方式；不要手工另画第二套不同形状。
3. 每个图标独立选择有效缓存或随包资源。兜底不依赖运行时字体导入成功或另一个可写目录；路径沿用 Windows 正斜杠规范化，覆盖中文/空格目录。异常使用现有 diagnostics，限定频率并标明资源阶段。
4. 检查最终样式所有实际使用的 `ICON_*` 地址均可解码、图形非空；不能以“QSS 能解析”作为图标存在证明。兜底资源也缺失属于发布资源错误，应明确报错并使 smoke 失败，不能记录成正常启动。
5. Full/Lite 及仓库实际维护的 spec 数据收集保持一致。先定位现有图标资源收集目录，再决定是否需要新 add-data，避免重复打包。正常启动不得强制重写健康缓存。

**聚焦门禁：** 新增图标缓存故障注入/实际图片解码与控件渲染测试；`tests/ui_kit/test_control_style.py`、`tests/ui_kit/test_stylesheet_parses.py`；资源/构建入口变化后运行 `tests/test_packaging_imports.py`、`tests/test_windows_runtime_dependencies.py`。Windows EXE 分别验证首次启动、正常缓存复用、故障注入的不可写缓存和损坏缓存；测试只在隔离目录内改变权限/内容。

### T3 — 横向验证，失败才局部修复

T1/T2 成为稳定快照后，按下表顺序扩大检查。每项记录 PASS/FAIL/UNKNOWN、环境与失败状态；通过项不重写。发现问题后先补定向红证据，再改对应 owner。

| 对象与 owner | 检查重点 | 失败后允许的最小修复与测试 |
| --- | --- | --- |
| Inspector：`ui/inspector_sections/collapsible.py`、`persistent_top.py` | 收起/展开端点和中间帧、禁用/hover、分数 DPR；检查原生箭头与动画自绘的衔接 | 在本组件统一箭头来源；保持动画时长、快速反转、焦点转移及设置提交语义。`tests/ui/test_collapsible_motion.py`、`tests/ui/test_inspector.py`；内部 arrowType 断言可随绘制迁移改为实际状态/图像契约，不删除行为覆盖 |
| 菜单和下拉：`ui_kit/menus.py`、`combo_popup_shell.py` 与实际调用者 | 子菜单箭头、菜单勾选、hover/禁用、弹层四角与遮挡 | 保留共享透明外壳，只修失败调用者或子控件颜色。`tests/ui/test_qmenu_density.py`、`tests/ui/test_combo_popup_shell.py`；复用 `scripts/probe_signal_picker_popup_shell.py` 的真实桌面证据方法 |
| 通道导出列表和 Batch 结果列表：`ui/dialogs/channel_editor.py`、`ui/drawers/batch/result_details.py` | 浅背景配深色选中文字；激活、失焦、禁用状态 | 保留已有 palette 修复，在失败 owner 补齐缺失 color group；不全局强制所有 HighlightedText 为黑色。`tests/ui/test_channel_editor_export.py`、`tests/ui/test_batch_result_details.py` 中相关用例 |
| 通道树、Inspector、菜单与下拉的文字 | 实际中文/英文混排，长通道名、Pts 数值、有效字体与文字包围盒 | 先查 polish 后 fontMetrics 与 contentsRect，在失败控件修测宽/高度。保持全局字体候选及字号，禁止用全局字体替换掩盖局部裁切 |
| 上述控件与图标 | 100%/125%/150%/200%，不同缩放屏幕间移动 | 先证明显著裁边或重采样损失，再在 owning icon/控件按当前 DPR 生成或选择资源并刷新。若新增事件监听，必须可合并、正确解除连接，不引入逐 paint 重建缓存。复用 `tests/ui/test_color_swatch_hidpi.py` 的 DPR 用例方式 |

**边界门禁：** QSS 变更运行上述 QSS 两项；共享 UI helper 新依赖运行 `tests/ui/test_import_boundaries.py`；新增信号接线运行 `tests/ui/test_no_lambda_signal_connections.py`；只有确实改变 main-window 写入边界时才运行 `tests/ui/test_main_window_state_ownership.py`，不得扩大白名单。此范围不触及 DSP/pg_canvas/Batch runner，不机械运行其无关门禁。

### T4 — 固定可复现的 Windows UI 构建基线

**文件 owner：** `tools/build_windows_folder.ps1`、`tools/build_windows_folder_lite.ps1`、必要的 UI 构建约束文件、对应打包测试。

1. 根据 T0 的 Windows 实际环境记录选择候选 PyQt5/Qt、qtawesome、PyInstaller 组合，T5 通过后才将其确认为已验收基线。不把本机 Mac 的 Qt 版本直接当成 Windows pin，也不在计划里虚构尚未获取的版本号。
2. 将候选组合写入一个共享 Windows UI 构建约束来源，两个脚本的依赖安装均应用它；取消绕过约束的无界 `--upgrade qtawesome`，`-SkipInstall` 等复用环境路径也须校验实际版本。避免每个脚本维护不同版本常量。
3. 约束仅针对本任务验证过的 UI/打包链，不全量重锁科学计算/采集依赖。复用既有 frozen-import 合约工具，不能改变其 importer/native 依赖职责。
4. 输出构建证据清单：提交与工作区指纹、产品版本、flavor、依赖版本、QSS/图标资源摘要。清单供诊断与验收，不写入用户项目状态。

**聚焦门禁：** `tests/test_packaging_imports.py`、`tests/test_windows_runtime_dependencies.py`，新增约束被 Full/Lite 安装与复用环境共同执行的测试；按该约束干净构建一次 Full/Lite，再执行 T5。仅当 T5 失败需要更改版本或产品代码时，才重建并重验受影响场景；同一未变更产物不重复验收。不得用旧版本包的截图代表新包。

### T5 — 最终实机验收与交付

使用 T0 同一状态集、合成数据与视图几何，验证以下矩阵。所有环境都要真实显示控件；截图需记录其物理像素与逻辑尺寸，禁止缩放图片后比较全图逐像素误差。

| 环境 | 必要检查 | 完成状态 |
| --- | --- | --- |
| 本机 offscreen | 红绿回归、颜色/像素/几何与图标故障注入，DPR=1/1.25/1.5/2 | 待执行，不能代替桌面结果 |
| macOS Cocoa + 正式 TraceLab | 生产树与 Inspector 交互、菜单状态、实际字体与前台外观；可用屏幕的原生 DPR | 待执行 |
| Windows 同环境源码运行 | 100%/125%/150%/200% 的关键控件矩阵，普通/选中/失焦/禁用 | UNKNOWN |
| Windows Full frozen | 同上；额外首次启动、缓存异常、随包资源读取与启动日志 | UNKNOWN |
| Windows Lite frozen | 同上，独立证据，不能复用 Full 结论 | UNKNOWN |
| Windows 跨缩放屏幕 | 拖动前后箭头清晰度、尺寸、字体和弹层定位 | UNKNOWN；缺少硬件时明确保留 |

- 自动比较同一环境的关键图形位置、颜色、连续背景和文字边界；跨平台比较契约而非抗锯齿全图相等。方向、对比度、图形面积与槽内包围盒共同判定，不只检查 QIcon 非空。
- Windows 弹层外角使用真实桌面 `QScreen.grabWindow(0)`：窗口置顶、确认无遮挡的宿主参考像素，按 `frameGeometry()` 和 DPR 取样；`widget.grab()` 不能证明桌面合成后的透明角。
- 将失败修复后的矩阵更新到同一最终快照。记录命令、退出码、HEAD/工作区指纹、环境 JSON、截图和失败原因；崩溃/超时/中断标为 UNVERIFIED。
- 没有真实 Windows 运行结果时，可报告“源码修复与本机验证完成，Windows 未验收”，但不能将本计划整体标记完成。无需让用户逐张筛图，先自动汇总失败项。

## 4. 执行与验证纪律

依赖顺序：T0 → T1 → T2 → T3 → T4 → T5。T5 出现失败时回到实际责任任务修复，再更新受影响证据。T1 可以先形成独立可审阅补丁，不必等待字体或多屏问题全部确定。

测试使用项目运行时，例如：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_channel_widget.py tests/ui/test_file_navigator.py
```

测试文件按目录分组，保留根 `conftest.py` 的 fixture 修复。QSS/palette 修改的测试须恢复应用状态；所有 widgets 明确归属并排空 deferred deletes；probe/测试注入独立 QSettings 与缓存目录。不得向开发者真实设置存储写入测试值。

本任务默认只跑 owner 与相关边界门禁。只有最终实际发布或广泛共享变更产生明确集成风险时才安排一次全量门禁，先说明理由并检查同 checkout 是否已有 pytest 全量进程。由同一协调者在稳定快照上顺序运行主套件（排除 `tests/acquisition_ui`）与 acquisition_ui；记录前后指纹，不并发、不重复已通过的稳定快照全量结果。

实施前按需加载已有 lessons：`codex-channel-tree-selection-color-has-multiple-painters`、`codex-channel-tree-selected-fill-must-stay-rectangular`、`qt-lifecycle-toast-and-macstyle-expander`，以及 Windows 弹层像素采样经验。完成前检查 lesson 状态；复用已记录规则，没有新规律时不重复新增 lesson。

## 5. 完成与本次文档门禁

实现完成要求：V1–V7 与实际触发的 T3 修复均有对应证据；关键资源异常不再产生不可见操作；Full/Lite 可复现构建且分别通过验收。未执行的平台、缩放或硬件场景保留 UNKNOWN，不以发布、测试数量或 Mac 截图代替。

交付实现时提供简短摘要、变更文件范围、聚焦测试结果、跨平台验收表和剩余门禁。当前计划不授权自动 bump、commit、push 或发布。

**本次仅编写计划：** 检查全文的范围、引用、文件与符号存在性、T0–T5 依赖、证据状态和 `git diff --check`。不修改产品代码、不运行产品测试，也不将本次文档检查记录为上述实施任务通过。
