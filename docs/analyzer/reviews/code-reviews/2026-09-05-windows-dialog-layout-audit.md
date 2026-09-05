# Windows 弹窗比例与布局鲁棒性审查

日期：2026-09-05。状态：**分析完成；修复方案待实施；Windows frozen 外观验收 UNVERIFIED**。

本轮只新增审查文档和 `.state/windows-dialog-audit/` 中的临时探针，没有修改产品源码。用户提供的是 macOS 截图，确认异常 Windows 机器使用 **100% 显示缩放**；分辨率、文本辅助缩放、Qt/TraceLab 版本、包类型和 Windows 异常截图尚未知。

## 1. 结论与优先级

最有证据支持的解释是：**Qt 5 的消息框保留平台专属布局，而项目只统一了按钮的 QSS 尺寸，未统一消息框正文、留白与按钮区域的布局。** Windows 100% 也会出现这种比例差异。当前代码已经设置 Fusion，不能把“切换 Fusion”或“关闭高 DPI”当修复。

这解释了现象的方向，尚不能证明用户那份 Windows 包的全部成因。实际发行包的字体、Qt 版本和布局测量仍需要补证。以下 P1 表示满足所列触发条件时核心操作可能不可见/不可达；P2 表示视觉、文字可读性或一般布局缺陷。

| 优先级 | 发现及用户影响 | 定位 | 证据状态 |
|---|---|---|---|
| P1 | 批量预览的警告正文位于滚动区外；警告增多后把整个窗口与底部操作撑出屏幕 | `ui/drawers/batch/preview_dialog.py:79,163` | 当前生产类 + 生产 QSS 离屏复现 |
| P1 | 通道配置管理器最小 940×680，无工作区适配；小工作区无法通过缩小窗口取回全部操作 | `ui/widgets/channel_config_manager.py:204` | 源码 + 离屏几何复现 |
| P1 | 游标显示弹层在锚点下方直接定位，未翻转或裁定工作区；靠屏幕底边时选项不可见 | `ui/chart_stack/cursor_display.py:620,659` | 离屏复现；Windows 平台最终定位待验 |
| P2 | 未保存项目提示只适配按钮，外框仍由 Qt 平台布局收紧，Windows 更显按钮拥挤 | `ui/main_window/_project_io_mixin.py:175`；`ui_kit/style.qss:958` | Qt 官方源码 + 本地布局模型；用户包未复现 |
| P2 | 消息框按钮按调整前字体一次性测宽，之后字体变化会裁切长文字 | `ui_kit/message_box_buttons.py:100` | 12px→24px 字体压力探针及截图复现；不是已证实的用户包触发条件 |
| P2 | 重建时间轴的目标文件名不换行、不限宽；位置 clamp 无法容纳比屏幕还宽的内容 | `ui/drawers/rebuild_time_popover.py:74,126` | 合法长度文件名离屏复现 |
| P2 | 全局 glass tooltip 不换行、不限宽/高；长路径、多选通道摘要会出屏 | `ui_kit/glass_tooltip.py:25,58` | 长路径离屏复现；多行高度为源码风险 |
| P2 | 多个工具窗/弹层仅移动位置、不约束尺寸，或完全没有屏幕边界判断 | 见第 4 节和附录 | 各处源码确认，Windows 实际影响待验 |
| P2 | 按钮颜色角色同时决定高度；同一行“取消”和“确定”可出现 32/36px 高差 | `ui_kit/style.qss:734`；`ui/drawers/rebuild_time_popover.py:87` | 当前生产控件离屏复现 |
| P2 | 现有屏幕适配 helper 的硬最小尺寸可以反向覆盖屏幕上限；跨屏和原生框架适配不统一 | `ui/drawers/batch/_geometry.py:122`；`ui/db_reference_dialog.py:392` | 源码边界缺陷；不等于普通屏幕必现 |

路径均相对 `mf4_analyzer/`。附录提供可点击定位。上述风险不少是跨平台潜在缺陷；Windows 的工作区、字体度量和窗口装饰更容易使它们暴露，并非只能发生在 Windows。

## 2. 为什么这张 macOS 提示看着协调

### 2.1 真正的调用链

`ProjectIOMixin._unsaved_project_prompt_buttons()` 创建普通 `QMessageBox`，分别配置保存/丢弃/取消的语义角色、默认键和 Escape，然后调用 `fit_message_box_buttons_to_text()`。没有给消息框设定统一的正文布局或留白。

全局 QSS 的消息框按钮是 `min-width:52px; min-height:24px; padding:2px 10px`，继承 1px 边框，短按钮实测外框 **74×30 逻辑像素**。QSS 的内容尺寸、padding、border 要分别计算，不能把 52 当作外框宽度。[Qt 样式表盒模型](https://doc.qt.io/qt-5/stylesheet-customizing.html#the-box-model)

`app.py:87` 已设置 Fusion；`style.qss:17` 为控件指定 12px 和平台字体回退列表。macOS 实际回退到 PingFang SC，Windows 通常会命中 Microsoft YaHei，但用户包的实际字体还没有测量。

### 2.2 Fusion 没有消除 Qt 的平台布局分支

Qt 5.15 的 `QMessageBoxPrivate::setupLayout()` 对 macOS 采用更宽的外边距和图标间隔，按钮行只放在文字列下方；非 macOS 的按钮行跨越整个网格，使用样式默认边距。macOS 还单独给正文设置粗体。这些编译期分支不会因为使用 Fusion 自动消失。Qt 最终还通过内部 `updateSize()` 固定消息框尺寸，所以随手调用一次 `resize()` 并不构成可靠布局合同。[Qt 官方 QMessageBox 源码](https://github.com/qt/qtbase/blob/5.15/src/widgets/dialogs/qmessagebox.cpp)

本项目 Fusion 的 `PM_MessageBoxIconSize` 实测 48；官方 Fusion 实现也是 48。不能套用其他基础样式的“Mac 64 / Windows 32”来解释当前应用。[Qt 官方 Fusion 源码](https://github.com/qt/qtbase/blob/5.15/src/widgets/styles/qfusionstyle.cpp)

本地保留同一字体、同一 48px 图标和同一 74×30 按钮，按非 macOS 源码重建网格，宽度从 328 降到 269，按钮尺寸不变。它只证明布局机制能产生“框窄、按钮占比大”，**不是 Windows 运行结果，也不是截图像素的预测值**。真正 macOS Cocoa 的平台主题、按钮排列和原生框架与 offscreen 仍有差别。

### 2.3 100% 的含义

100% 使“用户设置了 150%/200% 显示缩放”这一解释失去依据，但没有排除文本辅助缩放、环境变量覆盖、不同 Qt 构建或字体差异。当前 `app.py:52` 在 QApplication 前启用 Qt 高 DPI，并采用 PassThrough；正常应保留。Qt Widgets 使用设备无关坐标，窗口几何不应再手工乘 DPR，否则会重复缩放。[Qt 5 高 DPI 文档](https://doc.qt.io/archives/qt-5.15/highdpi.html)

Full/Lite 构建脚本都包含同一个 `style.qss`，没有发现独立 Windows 大按钮主题。`requirements.txt:9` 没有固定 PyQt5 版本，因此不能假设本地与用户的包使用相同 Qt。这里只能排除已读脚本中的明显分叉，不能用脚本证明发行包内容一致。

## 3. 可重复的本地证据

临时探针：`.state/windows-dialog-audit/probe.py`。运行环境：macOS Qt **5.15.14**、PyQt **5.15.11**、Fusion、实际应用字体/QSS，`QT_QPA_PLATFORM=offscreen QT_FONT_DPI=96 QT_SCALE_FACTOR=1`，工作区 **800×600**，DPR **1.0**。未点击保存、运行、删除等业务动作。

| 探针 | 实测结果（逻辑像素） | 能证明什么 |
|---|---|---|
| 当前未保存项目 QMessageBox | 客户区 328×105；按钮均 74×30 | 本地真实控件基准，非 Cocoa 截图等价物 |
| 非 macOS 源码布局模型 | 客户区 269×106；按钮仍 74×30 | 更窄布局下按钮占比增大；模型不是 Windows |
| 通道配置管理器 | 1180×680；最小 940×680 | 超过 800×600 工作区，用户无法缩到屏内 |
| 批量预览正常状态 | 752×528 | 原来的初始化 fit 在短内容下有效 |
| 批量预览 30 条不同警告 | 752×706；最小高度 706；按钮 y=658 | 动态正文会重新撑破初始化高度预算 |
| 重建时间轴长文件名 | 816×142 | 64 字符中文/下划线主体加 `.mf4`，UTF-8 180 字节，已足以超出 800 宽工作区 |
| 字体改变后的长按钮 | 按钮宽 161，文字宽 263，sizeHint 宽 285 | 可见裁切；当前一次性 fit 无法保证后续字体变化 |
| 全局长路径 tooltip | 宽 1052，x=4 | clamp 位置仍无法容纳超宽正文 |
| 底边游标设置弹层 | 270×315，y=577 | 底部到 892，越过 600 高工作区 |
| 重建时间轴动作行 | 取消高 32、确定高 36 | 角色与尺寸耦合导致同排不齐 |

探针使用小工作区验证边界，**不声称用户屏幕是 800×600**；长文件名、30 条警告和字体变化都是明示构造的输入。几何 JSON 与截图保留在 `.state/windows-dialog-audit/`。已直接查看长按钮裁切和重建时间轴截图。

现有测试：

```text
tests/ui/test_message_box_buttons.py
tests/ui/test_rebuild_popover_geometry.py
tests/ui/test_batch_preview_dialog.py
20 passed in 1.09s

# acquisition_ui 使用另一个新进程，未混入上面的 UI 进程
tests/acquisition_ui/test_message_box_button_fit.py
4 passed in 0.23s
```

这些测试通过不等于上述缺陷不存在：重建弹层现有几何用例使用短文件名，消息框用例不验证晚到的字体变化和跨平台框体比例，预览用例未拦住无限增长的警告区。未运行全量套件，本次无源码改动，无需全量基线。

## 4. 同类问题的完整静态覆盖与边界

已扫描 `mf4_analyzer/**/*.py` 的直接 Qt 调用：**77 处 QMessageBox（27 处实例构造、50 处静态调用）、5 处 QInputDialog、20 处 QFileDialog、14 个 QDialog 子类、3 处内联 QDialog 构造、12 处显式 Popup/Tool/ToolTip 创建或转为弹层的路径**。另扫描 89 个文件中的 **416 处固定/最小/初始尺寸调用**。这些是审查入口数，**不是缺陷数量**；标准 QMenu/QComboBox 的 Qt 内部窗口不算作这 12 处应用弹层。

### 4.1 需要修复或补齐的具体界面

| 界面 | 当前行为/风险 | 推荐处理 |
|---|---|---|
| 所有应用消息框 | 共用按钮 QSS；静态调用只经过颜色角色 filter，没有统一内容布局。启动期错误框可能尚无完整应用样式 | 应用交互提示分批走统一构建入口；启动失败 fallback 保持低依赖并单独验收 |
| 通道配置管理器 | 默认 1180×680，硬最小 940×680；内部若干固定条带叠加 | 保留常规屏幕默认，工作区不足时降为响应式约束；正文滚动、操作栏留在滚动区外 |
| 配置重命名/导入预览/丢弃修改 | 三处内联 QDialog；导入最小宽 460；没有统一屏幕上限 | 先核对表单与动作合同，再复用共同 fit；输入框与破坏性确认保留各自默认键 |
| 批量预览 | facts、warnings、status 不在图片区滚动容器内；警告无数量上限 | 将可增长的信息放入可滚动正文，必要时独立可滚动详情；保留完整警告，避免截断事实 |
| BatchSheet / UltraViewSheet | 已复用 batch fit，但其 min floor 可覆盖屏幕上限；多屏、显示后尺寸变化尚不统一 | 修复共同几何所有者；UltraView 继续保留 Board 自身的自适应与非模态窗口语义 |
| ChannelEditorDrawer | 高度按 parent.height()-80 且至少 520；showEvent 只移动位置 | 使用目标屏客户区预算约束高度，正文已可滚动；显示后核对原生框架 |
| ExportSheet | 默认 320×400；按 parent 顶部+40 定位，无工作区 clamp | 先 fit，再定位；不能假设主窗口完全在屏内 |
| RebuildTimePopover | 长目标名撑宽；只有位置 clamp；动作行 32/36 高差 | 文件名可换行/中间省略并保留完整可访问文本；限宽后重新算高；同一动作行使用相同 size token |
| QuickRefPanel | 初始 940×660；相对主窗口居中，无尺寸/屏幕位置约束 | 保留内容滚动与搜索结构；小工作区降低窗口目标尺寸，再 clamp |
| CursorDisplayPopover | 直接定位右下方；延迟 refit 后还会重新改变高度 | 每次有效内容 refit 都基于锚点重新确定位置；下方不足先翻上，再限高 |
| 图表刻度密度弹层 | `chart_stack/cards.py:821` 直接 move 到按钮下方 | 使用已有 RenderStylePopover 的锚点生命周期思路和统一几何计算 |
| 右键菜单自定义动作列表 | `pg_canvas/context_menu.py:988` 浮动列表 adjustSize 后直接 move | 约束列表高度、滚动并翻转/限位；保留嵌套 QMenu 的焦点关闭合同 |
| 表达式/参数帮助 ReferenceHelpPopup | 固定宽度、只做位置 clamp，正文未统一限高 | 保留当前帮助卡布局；超高时正文滚动，关闭按钮始终可见 |
| 全局 glass tooltip | 长路径/通道名无宽高上限；翻到上方后也无最终顶部 clamp | 以工作区约束换行、最大高度及最终矩形；大量通道只给摘要，完整列表仍由所属控件提供 |
| PresetHoverCard | 固定宽度，屏边只定位；长内容仍可能超高 | 属轻量提示，使用有界摘要；需完整阅读的内容放到可交互详情 |
| Cockpit SettingsDialog | 最小宽 560，探针最小高 532；仅部分 tab 有滚动 | 把各 tab 的可增长正文纳入滚动预算，统一屏幕 fit，保存栏固定可达 |
| Cockpit ReviewModal | 420×320 最小、560×320 初始；部分内容滚动，无总屏幕约束 | 纳入窗口 fit 回归；当前短内容未发现失调实证 |
| Analyzer/Cockpit 主窗口 | 初始 1450×850 / 1280×760，无显式工作区 fit 路径 | 作为相邻风险验收：小屏启动/跨屏时测量真实窗口，再决定是否加初始 fit，不凭 resize 数字认定实机必越界 |

### 4.2 已有防护，不能重复判为“完全没处理”

- **ChartOptionsDialog**：已有正文滚动、显示后原生框架高度预算和位置 clamp。只需审查窄屏时 minimumWidth 反压上限、首次选屏及屏幕变化，不应重写。
- **DbReferenceDefaultsDialog**：已有屏幕/parent 尺寸约束；但 360×320 floor 可覆盖更小工作区，32px 固定预留也不等于实测原生框架。
- **RecentOpenPopup**：已有目标屏判断、屏幕限宽高、上下翻转、滚动表格。320×220 floor 和固定行高只需在极小工作区/字体压力下补验；保留已接受的常规尺寸与行数。
- **ViewOverflowPopup**：已有字体测宽、省略、滚动、目标屏定位；低于自身宽度/页脚最小尺寸时仍需边界用例。保留 View/+ /溢出按钮交互与几何合同。
- **SignalPickerPopup**：已有可视行数预算、滚动、正文省略、上下翻转、搜索过程稳定尺寸；需补最小高度超过剩余空间的边界。其全量通道 tooltip 受全局 tooltip 缺陷影响。
- **RenderStylePopover**：已有位置 clamp、上下翻转和宿主移动后关闭策略。仅在内容尺寸超过工作区时需要降级，普通短内容不应再加平行实现。
- **UltraView ToolFlyoutSurface**：有 host 内嵌与独立弹层两条语义不同的分支，部分已滚动。内嵌分支必须用 parent 局部坐标；独立分支才用屏幕全局坐标。不可统一成盲目的 screen clamp。
- **紧凑按钮、搜索清除键、圆角下拉框**：QSS 已存在针对 minimum/padding 冲突的专用覆盖。416 个尺寸调用中包含大量合法图标、色块和分隔线，不能批量删除 fixedSize 或全局缩小 QPushButton。

QFileDialog 的 20 处调用保留系统文件选择体验，独立检查 Windows 对话框所有权、显示器及字体；没有证据要求改为自绘。QMenu、下拉列表的长文字、滚动与 QWidgetAction 内容以及圆角透明背景属于冻结包视觉矩阵，不能用离屏通过代替 Windows 验收。

## 5. 推荐的鲁棒修复方案

### 5.1 应用提示框：统一布局所有权，保留系统交互语义

建议在 `ui_kit/` 实现一个小型应用提示框组件，使用 **QDialog + QDialogButtonBox + 自有正文布局**，先迁移未保存项目提示及长动作标签的确认框。它只负责展示和结果返回，不访问 MainWindow/session 状态。这样正文留白、图标列和动作区均由应用控制，避免长期依赖 QMessageBox 的私有网格结构。

本轮是方案，不在未验证前一次性替换 77 处调用。先完成单个示范入口的 Mac/Windows 对照，再按附录把应用交互消息分批迁移。纯启动失败提示作为明确例外保留。QInputDialog 的表单输入与 QFileDialog 不混入这项替换。

组件合同：

1. 标题、正文、图标与按钮间距使用同一套 token；以当前 macOS 已接受的留白为视觉基准。首选宽度是软目标，至少容纳正文/动作需求，但不得压过目标工作区。窄屏允许正文/详情滚动和动作区有序换行；错误详情不能静默丢弃。
2. 用 polish 后的实际字体、`QFontMetrics`、`sizeHint`/`minimumSizeHint` 共同定布局；按钮内容区必须容纳文本和 padding/border。尺寸与 primary/danger 等颜色语义分离，同一行统一高度。保留图标按钮的独立紧凑尺寸。
3. 使用 QDialogButtonBox 保留平台按钮顺序；不要依靠第几个按钮推断结果。保存、丢弃、取消用明确结果标识，保留默认 Save、Escape/关闭=Cancel；保存失败不能被当作用户同意关闭。其他破坏性对话框继续遵守原来的安全默认键。
4. 字体、样式、文本、详情展开变化后做一次合并的重新布局。屏幕变化后更新尺寸预算；防止 LayoutRequest/resize 无限递归，不采用定时轮询。
5. 迁移必须盘点原调用的 standardButton 返回值、自定义按钮身份、modal/nonmodal、`exec_`/`open`、checkbox、详细信息和关闭行为，逐个保持兼容。保留现有测试 monkeypatch seams 或同步更新消费者，不静默改变取消分支。

过渡期保留的 QMessageBox 可修复 `fit_message_box_buttons_to_text()` 的字体时序和几何失效处理，但这只能补文字适配，**不能宣称已统一平台布局**。不采用 monkeypatch 全局 QMessageBox、按 private child objectName 拆内部网格、强制改 Win 按钮顺序或固定一个对话框宽高的方式。

### 5.2 所有窗口：一次完整的“内容→尺寸→位置”计算

把可复用的屏幕预算/矩形计算放在 `ui_kit/` 的一个所有者，现有 Batch helper 保留兼容入口。它只计算/应用几何，不把每个窗口的内容结构和生命周期塞进全局 event filter。

- **选屏**：锚点的全局位置优先；普通对话框使用其父顶层窗口当前屏幕；跨屏后的窗口使用自身当前 screen。最后才回退 primary。注意负坐标屏幕；避免把子控件局部 geometry 当全局位置。
- **预算**：以 `availableGeometry()` 为上限，扣除实际窗口边框和适度安全边距。显示前可用保守估计，显示后排队做一次原生框架校正。固定 72px 预留不是最终真值。
- **约束顺序**：内容超过预算时先换行/省略/滚动，降低布局最小尺寸，最后 fit。不能 `max(minimum, screen_cap)` 再把窗口撑回屏外。不要用 setMaximumSize 掩盖一个更大的 minimumSize。
- **footer**：长正文在滚动区内，操作栏留在外部；窄宽度下动作栏可按语义重新排列。主操作和取消必须可见、可键盘到达，不靠缩小字体凑空间。
- **定位**：得到最终尺寸后先下方、再上方，最后完整矩形 clamp。跨屏、工作区改变、内容增长时重算；Popup 可选择宿主移动后关闭，下次打开重算，避免浮在旧位置。
- **已有用户尺寸**：普通可调整窗口只在溢出或内容约束改变时纠正，不在每个 resize 事件中拉回默认尺寸；内嵌 flyout 使用宿主预算。

### 5.3 字体、DPI、打包

控件尺寸按逻辑像素计算，使用实际字体度量；不手工乘 DPR、不禁用 Qt 高 DPI、不强制所有机器回到 100%。明确支持的普通控件文字尺寸；应用若承诺支持辅助文字放大，必须提供统一字体尺寸策略并验收，不能假设 QSS 12px 自动跟随系统文本设置。

记录现有诊断日志中的实际 Qt/PyQt/PyInstaller 版本、平台插件、style、字体匹配、逻辑 DPI/DPR、目标屏工作区、窗口 frame/client、按钮 rect/content 和相关 QT 环境覆盖；缺少字段时加到现有 diagnostics，一次记录、按变化更新，避免新建日志体系。比较异常包和本地源码运行的同一组字段。

Full/Lite 使用同一份已验证 UI 依赖约束或锁定的构建环境，并记录产物版本与 QSS 校验值。只固定 requirements 中 PyQt5 名称还不足以确认打包进来的 Qt 版本。先查实际 PE DPI manifest / Windows 兼容性覆盖，再决定是否需要变更构建配置，不叠加第二套 Win32 DPI awareness 调用。

`acquisition_ui/__main__.py:97` 的独立演示入口没有 Analyzer 的 `_configure_high_dpi()`；Full 内从 Analyzer 打开 Cockpit 则复用现有 QApplication。两者分开验收，不能将独立 demo 的缺口当作用户 Analyzer 100% 问题的根因。

## 6. 实施顺序与验收门槛

| 阶段 | 所有者/修改范围 | 必须提供的验证 |
|---|---|---|
| A：先收实机证据并冻结合同 | 现有 diagnostics、未保存项目入口、ui_kit 测试 | 同一 Windows 包 100% 的原始截图和几何日志；示范 prompt 的 Save/Discard/Cancel/Enter/Escape/关闭合同；长标签与字体变化失败探针 |
| B：修复可导致操作不可达的窗口 | BatchPreviewDialog、ChannelConfigManagerDialog、CursorDisplayPopover 及共同几何所有者 | 警告 0/1/30/100 条；小工作区与常规工作区；footer 所有按钮完整可见/可点击；原有 focused owner 测试 |
| C：统一提示框并迁移高频确认 | `ui_kit` 和附录中的应用确认调用者 | Mac/Win 同内容、同逻辑字体的视觉对照；1/2/3 个按钮、长中文/英文、详情与模态行为；测试旧返回语义不变 |
| D：补齐其他弹层/帮助/工具窗 | 第 4 节逐项所属模块，保留已有 helper 和受保护结构 | 长文件名/路径、多行、四角、parent 部分离屏、负坐标副屏、窄屏、反复开关/跨屏；无焦点/失活导致误确认 |
| E：冻结包验收 | 单个集成负责人 | Windows Full 与 Lite 同构建快照；Cocoa 回归；确认截图与几何均符合合同 |

应用几何合同：所有受支持屏幕预算内，窗口 frameRect 和动作区可见；按钮文字区域覆盖实际文本需求，禁止文字裁切/重叠；正文长内容完整可访问；同排动作高度一致；危险动作、默认键和取消行为不改变。对极小到连单个控件都容不下的工作区，应明确最低可用预算并提供可用降级，不能让隐藏的常量默默定义支持范围。

推荐矩阵：

- Windows 10/11：先在用户环境 **100%** 验收，再补 125%/150%/200%；覆盖 1280×720、1366×768、1920×1080、4K 中有代表性的组合，不要求全部笛卡尔积。
- 单独覆盖文本放大、可用字体回退、任务栏不同位置、100%↔150% 双屏、负坐标副屏、断开外屏后再打开弹层；普通 Windows Qt 与新鲜 Full/Lite frozen 均需核对，不能互相替代。
- Mac：真实 Cocoa 下截图中的未保存项目提示、长标签、默认/取消和圆角保留；offscreen 仅用于确定性布局测试。
- 聚焦测试按 owner 运行：现有 message_box_buttons、rebuild_popover_geometry/accept_race、batch_preview_dialog、channel_config_manager、dialog_with_handle、recent_open_popup、expression_help_popup；Cockpit 用单独进程运行对应 settings/review/message 测试。新增组件和几何算法增加针对上述失败条件的回归，避免只断言 QSS 字符串。
- 如果迁移涉及共享 UI 导入/打包：运行对应 import boundary、packaging imports、Windows build-script、QSS border shorthand 和无 lambda 连接 ratchet。未修改 DSP 不运行无关数值全量门禁；仅集成/发布里程碑由一个负责人对稳定快照跑全量。

## 7. 范围与证据限制

审查结束时 HEAD 为 `a60da923b864f53cade16d97de2dd17e49cf7a33`。工作区存在另一个任务的 Auto-NFFT 修改、先前 AGENTS.md 修改和既有资产删除，本轮未触碰。此报告描述读取到的当前 UI 源码及临时探针，不为其他任务或整个工作区提供通过结论。

静态扫描覆盖直接调用，不宣称发现所有动态生成、系统原生内部窗口或所有 Windows 专属渲染缺陷。完整入口索引如下，供后续逐项关闭；Windows 用户包的原因确认和修复验收仍为 **UNVERIFIED**。

相关既有 lessons（消息框 content-width、滚动正文/固定操作区、QSS 紧凑按钮优先级、配置管理器高度）已用于审查；本轮未实施修复，未新建重复 lesson。

## 附录 A：直接消息框、输入框和文件选择调用

下表只列调用入口；“调用种类”不代表需要全部自定义重写。

| 定位 | 所属入口 | 调用种类 |
|---|---|---|
| [acquisition_ui/history_tab.py:624](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/history_tab.py:624>) | `HistoryTab._choose_manifest` | `QFileDialog.getOpenFileName` |
| [acquisition_ui/main_window/_connection_mixin.py:248](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py:248>) | `ConnectionMixin._warn_connection_preconditions` | `_QMessageBox` |
| [acquisition_ui/main_window/_settings_mixin.py:273](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:273>) | `SettingsMixin._on_mark_segment` | `QInputDialog.getText` |
| [acquisition_ui/main_window/_settings_mixin.py:447](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:447>) | `SettingsMixin._on_pick_a2l` | `QFileDialog.getOpenFileName` |
| [acquisition_ui/main_window/_settings_mixin.py:561](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:561>) | `SettingsMixin._warn_a2l_load_problems` | `_QMessageBox` |
| [acquisition_ui/main_window/_settings_mixin.py:601](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:601>) | `SettingsMixin._on_pick_output_dir` | `QFileDialog.getExistingDirectory` |
| [acquisition_ui/main_window/_settings_mixin.py:630](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:630>) | `SettingsMixin._show_dropped_frames_prompt` | `_QMessageBox` |
| [acquisition_ui/replay_tab.py:161](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/replay_tab.py:161>) | `ReplayTab._pick_file` | `QFileDialog.getOpenFileName` |
| [acquisition_ui/review_modal.py:407](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/review_modal.py:407>) | `ReviewModal._show_discard_confirm` | `QMessageBox` |
| [acquisition_ui/review_modal.py:597](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/review_modal.py:597>) | `ReviewModal._show_archive_failure` | `QMessageBox` |
| [acquisition_ui/settings_dialog.py:396](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/settings_dialog.py:396>) | `TransportTabWidget._browse_seed_key` | `QFileDialog.getOpenFileName` |
| [acquisition_ui/settings_dialog.py:523](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/settings_dialog.py:523>) | `SettingsDialog._show_test_connection_result` | `QMessageBox` |
| [ui/chart_stack/cards.py:797](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/cards.py:797>) | `_ChartCard._confirm_clear_annotations` | `QMessageBox` |
| [ui/chart_stack/toolbar.py:939](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/toolbar.py:939>) | `PgNavigationToolbar.save_figure` | `_QFileDialog.getSaveFileName` |
| [ui/chart_stack/toolbar.py:961](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/toolbar.py:961>) | `PgNavigationToolbar.save_figure` | `QMessageBox.warning` |
| [ui/chart_stack/ultraview/board_switcher.py:183](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/board_switcher.py:183>) | `BoardSwitcher._on_context_menu` | `QInputDialog.getText` |
| [ui/chart_stack/ultraview/board_switcher.py:188](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/board_switcher.py:188>) | `BoardSwitcher._on_context_menu` | `QMessageBox.question` |
| [ui/chart_stack/ultraview/board_toolbar.py:211](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/board_toolbar.py:211>) | `BoardToolbar._on_free_grid_toggled` | `QMessageBox.question` |
| [ui/chart_stack/ultraview/page.py:1308](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/page.py:1308>) | `UltraViewPage._confirm_leave_free_grid` | `QMessageBox.question` |
| [ui/chart_stack/ultraview/page.py:1708](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/page.py:1708>) | `UltraViewPage._confirm_delete_board` | `QMessageBox.question` |
| [ui/dialogs/channel_editor.py:563](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:563>) | `ChannelEditorDialog._on_export_clicked` | `QMessageBox.information` |
| [ui/dialogs/channel_editor.py:626](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:626>) | `ChannelEditorDialog._create_single` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:725](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:725>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:760](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:760>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:781](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:781>) | `ChannelEditorDialog._create_dual` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:784](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:784>) | `ChannelEditorDialog._create_dual` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:792](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:792>) | `ChannelEditorDialog._create_dual` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:836](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:836>) | `ChannelEditorDialog._remove` | `QMessageBox.information` |
| [ui/dialogs/channel_editor.py:838](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:838>) | `ChannelEditorDialog._remove` | `QMessageBox.question` |
| [ui/dialogs/channel_editor.py:653](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:653>) | `ChannelEditorDialog._create_single` | `QMessageBox.critical` |
| [ui/dialogs/channel_editor.py:730](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:730>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:742](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:742>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:746](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:746>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:754](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:754>) | `ChannelEditorDialog._create_expression` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:757](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:757>) | `ChannelEditorDialog._create_expression` | `QMessageBox.critical` |
| [ui/dialogs/channel_editor.py:827](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:827>) | `ChannelEditorDialog._create_dual` | `QMessageBox.critical` |
| [ui/dialogs/channel_editor.py:647](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:647>) | `ChannelEditorDialog._create_single` | `QMessageBox.warning` |
| [ui/dialogs/channel_editor.py:811](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:811>) | `ChannelEditorDialog._create_dual` | `QMessageBox.warning` |
| [ui/dialogs/chart_options.py:482](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/chart_options.py:482>) | `ChartOptionsDialog.apply_changes` | `QMessageBox.warning` |
| [ui/drawers/batch/input_panel.py:766](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/input_panel.py:766>) | `FileListWidget._open_disk_dialog` | `QFileDialog.getOpenFileNames` |
| [ui/drawers/batch/output_panel.py:928](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/output_panel.py:928>) | `OutputPanel._choose_dir` | `QFileDialog.getExistingDirectory` |
| [ui/drawers/batch/sheet.py:1504](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:1504>) | `BatchSheet._on_import_preset` | `QFileDialog.getOpenFileName` |
| [ui/drawers/batch/sheet.py:1531](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:1531>) | `BatchSheet._on_export_preset` | `QFileDialog.getSaveFileName` |
| [ui/drawers/batch/sheet.py:2245](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2245>) | `BatchSheet._confirm_stop_running_dialog` | `QMessageBox.question` |
| [ui/drawers/batch/sheet.py:2133](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2133>) | `BatchSheet._show_result_toast` | `QMessageBox.information` |
| [ui/drawers/batch/sheet.py:2142](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2142>) | `BatchSheet._show_result_toast` | `QMessageBox.information` |
| [ui/drawers/batch/sheet.py:2150](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2150>) | `BatchSheet._show_result_toast` | `QMessageBox.warning` |
| [ui/drawers/batch/sheet.py:2155](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2155>) | `BatchSheet._show_result_toast` | `QMessageBox.information` |
| [ui/drawers/batch/sheet.py:2162](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:2162>) | `BatchSheet._show_result_toast` | `QMessageBox.warning` |
| [ui/inspector_sections/presets.py:994](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/presets.py:994>) | `PresetBar._rename` | `QInputDialog.getText` |
| [ui/inspector_sections/presets.py:1018](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/presets.py:1018>) | `PresetBar._clear` | `QMessageBox.question` |
| [ui/main_window/_analysis_mixin.py:866](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_analysis_mixin.py:866>) | `AnalysisMixin._ask_use_local_time_range` | `QMessageBox` |
| [ui/main_window/_channel_scope_mixin.py:240](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_channel_scope_mixin.py:240>) | `ChannelScopeMixin._confirm_analysis_detach` | `QMessageBox` |
| [ui/main_window/_channel_scope_mixin.py:387](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_channel_scope_mixin.py:387>) | `ChannelScopeMixin._prompt_channel_config_name` | `QInputDialog.getText` |
| [ui/main_window/_channel_scope_mixin.py:396](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_channel_scope_mixin.py:396>) | `ChannelScopeMixin._confirm_channel_config_overwrite` | `QMessageBox` |
| [ui/main_window/_channel_scope_mixin.py:515](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_channel_scope_mixin.py:515>) | `ChannelScopeMixin._confirm_detach_files` | `QMessageBox` |
| [ui/main_window/_fft_mixin.py:583](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_fft_mixin.py:583>) | `FFTMixin._do_fft_single` | `QMessageBox.critical` |
| [ui/main_window/_fft_mixin.py:428](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_fft_mixin.py:428>) | `FFTMixin.do_fft` | `QMessageBox.critical` |
| [ui/main_window/_order_mixin.py:506](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_order_mixin.py:506>) | `OrderMixin._build_order_job` | `QMessageBox.critical` |
| [ui/main_window/_project_io_mixin.py:177](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:177>) | `ProjectIOMixin._unsaved_project_prompt_buttons` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:236](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:236>) | `ProjectIOMixin.open_files_or_project` | `_QFileDialog.getOpenFileNames` |
| [ui/main_window/_project_io_mixin.py:316](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:316>) | `ProjectIOMixin._confirm_heavy_load` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:511](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:511>) | `ProjectIOMixin.save_project_as_via_dialog` | `QFileDialog.getSaveFileName` |
| [ui/main_window/_project_io_mixin.py:534](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:534>) | `ProjectIOMixin._confirm_degraded_project_save` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:559](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:559>) | `ProjectIOMixin.load_files` | `_QFileDialog.getOpenFileNames` |
| [ui/main_window/_project_io_mixin.py:1661](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1661>) | `ProjectIOMixin._ask_blf_batch_dbc_action` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:1684](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1684>) | `ProjectIOMixin._ask_blf_batch_mismatch_action` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:1748](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1748>) | `ProjectIOMixin._ask_open_blf_dbc_dialog` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:1763](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1763>) | `ProjectIOMixin._ask_blf_dbc_candidate_action` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:1807](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1807>) | `ProjectIOMixin._ask_multiple_blf_dbc_candidates` | `QInputDialog.getItem` |
| [ui/main_window/_project_io_mixin.py:1828](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1828>) | `ProjectIOMixin._ask_blf_dbc_mismatch_action` | `QMessageBox` |
| [ui/main_window/_project_io_mixin.py:1855](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1855>) | `ProjectIOMixin._prompt_blf_dbc` | `_QFileDialog.getOpenFileNames` |
| [ui/main_window/_project_io_mixin.py:251](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:251>) | `ProjectIOMixin._open_paths` | `QMessageBox.warning` |
| [ui/main_window/_project_io_mixin.py:1052](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1052>) | `ProjectIOMixin._load_one_impl` | `QMessageBox.critical` |
| [ui/main_window/_project_io_mixin.py:1054](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1054>) | `ProjectIOMixin._load_one_impl` | `QMessageBox.critical` |
| [ui/main_window/_project_io_mixin.py:2443](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:2443>) | `ProjectIOMixin._open_project_restoring` | `QMessageBox.warning` |
| [ui/main_window/_project_io_mixin.py:819](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:819>) | `ProjectIOMixin._load_one_impl` | `QMessageBox.critical` |
| [ui/main_window/_project_io_mixin.py:1583](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:1583>) | `ProjectIOMixin._load_blf_batch` | `QMessageBox.critical` |
| [ui/main_window/_project_io_mixin.py:2449](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_project_io_mixin.py:2449>) | `ProjectIOMixin._open_project_restoring` | `QMessageBox.warning` |
| [ui/main_window/_view_mixin.py:958](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_view_mixin.py:958>) | `ViewMixin._confirm_view_delete` | `QMessageBox` |
| [ui/main_window/_view_mixin.py:971](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_view_mixin.py:971>) | `ViewMixin._confirm_close_other_views` | `QMessageBox` |
| [ui/main_window/_view_mixin.py:986](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/_view_mixin.py:986>) | `ViewMixin._confirm_close_all_views` | `QMessageBox` |
| [ui/main_window/ultraview_coordinator.py:385](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/ultraview_coordinator.py:385>) | `UltraViewCoordinator.choose_and_export_png` | `QFileDialog.getSaveFileName` |
| [ui/main_window/window.py:3495](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:3495>) | `MainWindow._confirm_global_file_close` | `QMessageBox` |
| [ui/main_window/window.py:3526](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:3526>) | `MainWindow._confirm_global_channel_delete` | `QMessageBox` |
| [ui/main_window/window.py:3786](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:3786>) | `MainWindow._confirm_overlay_risk` | `QMessageBox.question` |
| [ui/main_window/window.py:4734](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4734>) | `MainWindow._do_export_excel` | `QFileDialog.getSaveFileName` |
| [ui/main_window/window.py:4801](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4801>) | `MainWindow._do_export_wwt` | `QFileDialog.getSaveFileName` |
| [ui/main_window/window.py:3457](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:3457>) | `MainWindow._confirm_global_file_close` | `QMessageBox` |
| [ui/main_window/window.py:4794](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4794>) | `MainWindow._do_export_wwt` | `QMessageBox.warning` |
| [ui/main_window/window.py:3298](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:3298>) | `MainWindow.open_acquisition_cockpit` | `QMessageBox.information` |
| [ui/main_window/window.py:4756](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4756>) | `MainWindow._do_export_excel` | `QMessageBox.critical` |
| [ui/main_window/window.py:4839](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4839>) | `MainWindow._do_export_wwt` | `QMessageBox.warning` |
| [ui/main_window/window.py:4841](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:4841>) | `MainWindow._do_export_wwt` | `QMessageBox.critical` |
| [ui/main_window/wwt_import_coordinator.py:313](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/wwt_import_coordinator.py:313>) | `WwtImportCoordinator._ask_layout` | `QMessageBox` |
| [ui/markup/editor.py:406](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/markup/editor.py:406>) | `MarkupEditor._get_save_path` | `QFileDialog.getSaveFileName` |
| [ui/view_tabbar.py:1426](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/view_tabbar.py:1426>) | `ViewTabBar._on_context_menu` | `QMessageBox.question` |
| [ui/widgets/channel_config_manager.py:1372](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:1372>) | `ChannelConfigManagerDialog._open_import_file` | `QFileDialog.getOpenFileName` |
| [ui/widgets/channel_config_manager.py:1378](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:1378>) | `ChannelConfigManagerDialog._save_export_file` | `QFileDialog.getSaveFileName` |
| [ui/widgets/channel_tree.py:2845](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_tree.py:2845>) | `MultiFileChannelWidget._confirm_selected_channel_checks` | `QMessageBox` |
| [ui/widgets/channel_tree.py:3137](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_tree.py:3137>) | `MultiFileChannelWidget._all` | `QMessageBox.question` |
| [ui/widgets/channel_tree.py:2250](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_tree.py:2250>) | `MultiFileChannelWidget._on_item_changed` | `QMessageBox.question` |

## 附录 B：自定义对话框入口

内部 `ChannelEditorDialog` / `ExportDialog` 由 drawer/sheet 承载，不能把内层缺少屏幕 clamp 单独认定为缺陷。`_PlaceholderReviewModal` 是占位实现，不计为已证明生产可达的问题。

| 定位 | 类/入口 |
|---|---|
| [acquisition_ui/main_window/window.py:99](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/window.py:99>) | `_PlaceholderReviewModal` |
| [acquisition_ui/review_modal.py:99](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/review_modal.py:99>) | `ReviewModal` |
| [acquisition_ui/settings_dialog.py:428](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/settings_dialog.py:428>) | `SettingsDialog` |
| [ui/db_reference_dialog.py:192](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/db_reference_dialog.py:192>) | `DbReferenceDefaultsDialog` |
| [ui/dialogs/channel_editor.py:51](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:51>) | `ChannelEditorDialog` |
| [ui/dialogs/chart_options.py:35](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/chart_options.py:35>) | `ChartOptionsDialog` |
| [ui/dialogs/export.py:13](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/export.py:13>) | `ExportDialog` |
| [ui/drawers/batch/preview_dialog.py:53](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/preview_dialog.py:53>) | `BatchPreviewDialog` |
| [ui/drawers/batch/sheet.py:149](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:149>) | `BatchSheet` |
| [ui/drawers/channel_editor_drawer.py:9](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/channel_editor_drawer.py:9>) | `ChannelEditorDrawer` |
| [ui/drawers/export_sheet.py:8](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/export_sheet.py:8>) | `ExportSheet` |
| [ui/drawers/rebuild_time_popover.py:18](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/rebuild_time_popover.py:18>) | `RebuildTimePopover` |
| [ui/drawers/ultraview/sheet.py:31](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/ultraview/sheet.py:31>) | `UltraViewSheet` |
| [ui/widgets/channel_config_manager.py:180](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:180>) | `ChannelConfigManagerDialog` |
| [ui/widgets/channel_config_manager.py:1148](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:1148>) | `ChannelConfigManagerDialog._open_rename_dialog` |
| [ui/widgets/channel_config_manager.py:1268](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:1268>) | `ChannelConfigManagerDialog._build_import_preview_dialog` |
| [ui/widgets/channel_config_manager.py:1416](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:1416>) | `ChannelConfigManagerDialog._confirm_discard_changes` |

## 附录 C：显式弹层创建/转为弹层的入口

QuickRef 的重复 flags 设置不重复计数；Qt 内部创建的菜单/下拉窗口不在此表中。

| 定位 | 所属入口 |
|---|---|
| [ui/chart_stack/cursor_display.py:558](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/cursor_display.py:558>) | `CursorDisplayPopover.__init__` |
| [ui/chart_stack/toolbar.py:26](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/toolbar.py:26>) | `_TickDensityPopover.__init__` |
| [ui/chart_stack/ultraview/author_chrome.py:159](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/author_chrome.py:159>) | `ToolFlyoutSurface.__init__` |
| [ui/drawers/batch/render_style_popover.py:46](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/render_style_popover.py:46>) | `RenderStylePopover.__init__` |
| [ui/drawers/batch/signal_picker.py:295](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/signal_picker.py:295>) | `SignalPickerPopup.__init__` |
| [ui/expression_help.py:202](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/expression_help.py:202>) | `ReferenceHelpPopup.__init__` |
| [ui/inspector_sections/presets.py:44](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/presets.py:44>) | `_PresetHoverCard.__init__` |
| [ui/pg_canvas/context_menu.py:988](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/context_menu.py:988>) | `_PgCustomActionButton._insert_list_into_panel` |
| [ui/quickref_panel.py:410](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/quickref_panel.py:410>) | `QuickRefPanel.__init__` |
| [ui/widgets/recent_open_popup.py:103](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/recent_open_popup.py:103>) | `RecentOpenPopup.__init__` |
| [ui/widgets/view_overflow_popup.py:82](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/view_overflow_popup.py:82>) | `ViewOverflowPopup.__init__` |
| [ui_kit/glass_tooltip.py:19](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui_kit/glass_tooltip.py:19>) | `_GlassTooltipPopup.__init__` |

## 附录 D：尺寸调用扫描分布

这是筛查索引，包含合法图标尺寸、分隔线和初始 resize，不是待删除清单。逐调用原始列表保留于 `.state/windows-dialog-audit/sizes.json`，修复前应重新扫描当前快照。

| 文件（定位首个尺寸调用） | 调用数 |
|---|---|
| [ui/chart_stack/ultraview/author_chrome.py:171](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/author_chrome.py:171>) | 32 |
| [ui/widgets/channel_config_manager.py:77](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_manager.py:77>) | 27 |
| [acquisition_ui/main_window/_toolbar_mixin.py:36](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py:36>) | 16 |
| [ui/chart_stack/ultraview/card_widgets.py:246](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/card_widgets.py:246>) | 13 |
| [ui/inspector_sections/_helpers.py:423](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/_helpers.py:423>) | 13 |
| [ui/toolbar.py:30](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/toolbar.py:30>) | 13 |
| [ui/chart_stack/ultraview/library_widgets.py:104](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/library_widgets.py:104>) | 12 |
| [ui/chart_stack/cards.py:248](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/cards.py:248>) | 11 |
| [ui/chart_stack/ultraview/tool_rail.py:270](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/tool_rail.py:270>) | 11 |
| [ui/drawers/batch/method_buttons.py:54](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/method_buttons.py:54>) | 11 |
| [acquisition_ui/widgets/live_cards.py:717](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/live_cards.py:717>) | 10 |
| [ui/dialogs/channel_editor.py:78](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/channel_editor.py:78>) | 10 |
| [ui/drawers/batch/input_panel.py:216](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/input_panel.py:216>) | 10 |
| [ui/pg_canvas/context_menu.py:528](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/context_menu.py:528>) | 10 |
| [ui/drawers/batch/output_panel.py:225](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/output_panel.py:225>) | 9 |
| [ui/view_tabbar.py:509](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/view_tabbar.py:509>) | 9 |
| [ui/chart_stack/ultraview/chrome_islands.py:60](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/chrome_islands.py:60>) | 8 |
| [ui/drawers/batch/signal_picker.py:93](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/signal_picker.py:93>) | 8 |
| [ui/widgets/channel_config_bar.py:106](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_config_bar.py:106>) | 8 |
| [ui/widgets/view_overflow_popup.py:154](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/view_overflow_popup.py:154>) | 8 |
| [acquisition_ui/widgets/left_pane.py:100](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/left_pane.py:100>) | 7 |
| [ui/file_navigator.py:30](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/file_navigator.py:30>) | 7 |
| [ui/main_window/window.py:168](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/main_window/window.py:168>) | 7 |
| [acquisition_ui/widgets/health_strip.py:88](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/health_strip.py:88>) | 5 |
| [ui/chart_stack/toolbar.py:33](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/toolbar.py:33>) | 5 |
| [ui/chart_stack/ultraview/chrome_popovers.py:350](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/chrome_popovers.py:350>) | 5 |
| [ui/drawers/batch/chart_statistics_panel.py:73](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py:73>) | 5 |
| [ui/drawers/batch/sheet.py:233](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/sheet.py:233>) | 5 |
| [ui/chart_stack/ultraview/viewport_controller.py:584](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/viewport_controller.py:584>) | 4 |
| [ui/compute_progress.py:52](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/compute_progress.py:52>) | 4 |
| [ui/drawers/batch/analysis_panel.py:56](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/analysis_panel.py:56>) | 4 |
| [ui/widgets/recent_open_popup.py:139](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/recent_open_popup.py:139>) | 4 |
| [acquisition_ui/main_window/window.py:171](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window/window.py:171>) | 3 |
| [acquisition_ui/widgets/health_popover.py:126](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/health_popover.py:126>) | 3 |
| [ui/chart_stack/cursor_pill.py:299](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/cursor_pill.py:299>) | 3 |
| [ui/chart_stack/ultraview/free_grid_board.py:195](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/free_grid_board.py:195>) | 3 |
| [ui/chart_stack/ultraview/template_board.py:136](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/template_board.py:136>) | 3 |
| [ui/drawers/batch/pipeline_strip.py:25](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/pipeline_strip.py:25>) | 3 |
| [ui/expression_help.py:214](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/expression_help.py:214>) | 3 |
| [ui/inspector_sections/contextual_frf.py:155](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/contextual_frf.py:155>) | 3 |
| [ui/inspector_sections/presets.py:51](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/presets.py:51>) | 3 |
| [ui/markup/thumbnail.py:47](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/markup/thumbnail.py:47>) | 3 |
| [ui/markup/toolbar.py:72](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/markup/toolbar.py:72>) | 3 |
| [ui/pg_canvas/_split_mixin.py:33](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/_split_mixin.py:33>) | 3 |
| [ui/quickref_panel.py:319](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/quickref_panel.py:319>) | 3 |
| [ui_kit/combo_popup_shell.py:122](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui_kit/combo_popup_shell.py:122>) | 3 |
| [acquisition_ui/review_modal.py:168](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/review_modal.py:168>) | 2 |
| [acquisition_ui/widgets/escalation_bar.py:210](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/escalation_bar.py:210>) | 2 |
| [ui/chart_stack/_helpers.py:209](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/_helpers.py:209>) | 2 |
| [ui/chart_stack/cursor_display.py:566](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/cursor_display.py:566>) | 2 |
| [ui/chart_stack/stack.py:467](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/stack.py:467>) | 2 |
| [ui/chart_stack/ultraview/board_aux_widgets.py:58](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/board_aux_widgets.py:58>) | 2 |
| [ui/chart_stack/ultraview/chrome_common.py:88](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/chrome_common.py:88>) | 2 |
| [ui/chart_stack/ultraview/widgets_common.py:195](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/widgets_common.py:195>) | 2 |
| [ui/db_reference_dialog.py:323](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/db_reference_dialog.py:323>) | 2 |
| [ui/dialogs/chart_options.py:57](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/chart_options.py:57>) | 2 |
| [ui/drawers/batch/frf_pair_editor.py:128](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/frf_pair_editor.py:128>) | 2 |
| [ui/drawers/batch/render_style_popover.py:50](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/render_style_popover.py:50>) | 2 |
| [ui/inspector.py:142](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector.py:142>) | 2 |
| [ui/inspector_sections/contextual_order.py:90](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/contextual_order.py:90>) | 2 |
| [ui/pg_canvas/canvas.py:1550](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/canvas.py:1550>) | 2 |
| [ui/pg_canvas/heatmap_canvas.py:566](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:566>) | 2 |
| [ui/widgets/channel_tree.py:1013](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/channel_tree.py:1013>) | 2 |
| [ui/widgets/db_reference.py:319](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/db_reference.py:319>) | 2 |
| [ui/widgets/ultraview_entry.py:191](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/ultraview_entry.py:191>) | 2 |
| [ui_kit/widgets/search_field.py:41](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui_kit/widgets/search_field.py:41>) | 2 |
| [acquisition_ui/settings_dialog.py:457](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/settings_dialog.py:457>) | 1 |
| [acquisition_ui/widgets/right_panel.py:486](</Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/widgets/right_panel.py:486>) | 1 |
| [batch_render_qt/_builder.py:978](</Users/donghang/Downloads/data analyzer/mf4_analyzer/batch_render_qt/_builder.py:978>) | 1 |
| [ui/analysis_section_page.py:755](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/analysis_section_page.py:755>) | 1 |
| [ui/chart_stack/ultraview/board_toolbar.py:153](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/board_toolbar.py:153>) | 1 |
| [ui/chart_stack/ultraview/hint_bar.py:30](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/chart_stack/ultraview/hint_bar.py:30>) | 1 |
| [ui/dialogs/export.py:17](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/dialogs/export.py:17>) | 1 |
| [ui/drawers/batch/_geometry.py:123](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/_geometry.py:123>) | 1 |
| [ui/drawers/batch/optional_eyebrow.py:36](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/optional_eyebrow.py:36>) | 1 |
| [ui/drawers/batch/preview_dialog.py:92](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/preview_dialog.py:92>) | 1 |
| [ui/drawers/batch/slice_panel.py:89](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/slice_panel.py:89>) | 1 |
| [ui/drawers/batch/task_list.py:99](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/batch/task_list.py:99>) | 1 |
| [ui/drawers/channel_editor_drawer.py:53](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/channel_editor_drawer.py:53>) | 1 |
| [ui/drawers/export_sheet.py:21](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/drawers/export_sheet.py:21>) | 1 |
| [ui/inspector_sections/_effective_facts.py:221](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/_effective_facts.py:221>) | 1 |
| [ui/inspector_sections/contextual_fft.py:90](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/contextual_fft.py:90>) | 1 |
| [ui/inspector_sections/contextual_fft_time.py:134](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/contextual_fft_time.py:134>) | 1 |
| [ui/inspector_sections/persistent_top.py:330](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/inspector_sections/persistent_top.py:330>) | 1 |
| [ui/markup/editor.py:157](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/markup/editor.py:157>) | 1 |
| [ui/pg_canvas/slice_panel.py:489](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/pg_canvas/slice_panel.py:489>) | 1 |
| [ui/side_panels.py:89](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/side_panels.py:89>) | 1 |
| [ui/widgets/pill_switch.py:27](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui/widgets/pill_switch.py:27>) | 1 |
| [ui_kit/widgets/segmented_choice.py:23](</Users/donghang/Downloads/data analyzer/mf4_analyzer/ui_kit/widgets/segmented_choice.py:23>) | 1 |
