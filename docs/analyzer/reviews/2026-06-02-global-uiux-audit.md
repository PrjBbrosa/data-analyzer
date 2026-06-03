# 2026-06-02 全局 UI/UX 审计与改进方案

## 结论

当前全局视觉系统已经有清晰基线：`Precision Light` 在 `mf4_analyzer/ui_kit/style.qss:1-23` 定义了三层 surface、单一交互蓝、hairline 边框和 11/12/13px 信息层级。主要问题不是“缺一套风格”，而是风格规则没有被所有弹层、菜单、内联 QSS 和旧 UI 入口一致执行。

优先级最高的是弹出框圆角背后的矩形阴影。审计时发现图片标注编辑器的颜色/线宽菜单只有 `WA_TranslucentBackground`，没有像 pyqtgraph 右键菜单一样补 `FramelessWindowHint | NoDropShadowWindowHint`。Phase A 已经补齐代码与测试；最小 MarkupEditor 实例的真实 macOS 截图未见明显方形阴影，完整 TraceLab 业务流仍待验。

> 2026-06-02 Phase A 执行状态：`markupStyleMenu` 已在 `mf4_analyzer/ui/markup/editor.py` 中追加 `FramelessWindowHint | NoDropShadowWindowHint`；`tests/ui/test_markup_editor.py` 已补 native-shadow flags 断言并通过；真实截图保存在 `/tmp/markup_style_menu_real.png`。

## 审计方法

- 使用 `ui-ux-pro-max` 的规则框架，重点看可访问性、交互反馈、样式一致性、布局密度、弹层/菜单和图表交互。
- 使用项目 lessons：`codex-rounded-qt-popups-need-translucent-shell.md`、`codex-visual-parity-rendered-screenshot.md`、`codex-performance-ui-audit-flow.md`。
- 本轮先完成全局审计和 HTML 说明，再执行 Phase A 的最低风险修复；后续 Phase B/C 暂不展开。

## P0 问题

### P0-1 圆角弹层规则仍不完整

证据：

- 全局 `QMenu` QSS 有 `border-radius: 12px` 和半透明白底：`mf4_analyzer/ui_kit/style.qss:1175-1179`。
- 图片标注编辑器样式菜单在 `mf4_analyzer/ui/markup/editor.py:885-905` 创建 `QMenu#markupStyleMenu`，设了透明背景，并把圆角白底放到内部 `markupStylePanel`。
- 审计时该菜单没有设置 `Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint`；Phase A 已补齐。pyqtgraph 右键菜单 helper 在 `mf4_analyzer/ui/pg_canvases.py:409-429` 也采用 objectName、关闭 tooltip、设置 frameless/no-shadow flags、再设置透明背景的做法。
- 测试审计时不对称：`tests/ui/test_markup_editor.py:293-312` 已在 Phase A 补上 `WA_TranslucentBackground`、`NoDropShadowWindowHint` 和 `FramelessWindowHint`；`tests/ui/test_pg_timedomain_canvas.py:2792-2813` 已经检查 `NoDropShadowWindowHint` 和 `FramelessWindowHint`。

建议：

1. 已修图片标注样式菜单：对 `markupStyleMenu` 增加 `FramelessWindowHint | NoDropShadowWindowHint`，保留透明 menu shell + 内部 panel 的结构。
2. 已给 `tests/ui/test_markup_editor.py` 增加 line-width/style menu 的 native-shadow flag 断言。
3. 已做最小 MarkupEditor 真实 macOS 截图检查；仍需在完整 TraceLab 业务流中复核，因为历史经验显示 offscreen Qt 不会复现真实原生阴影。

### P0-2 全局 QMenu 构造点没有统一 helper

风险点：

- Acquisition toolbar overflow menu：`mf4_analyzer/acquisition_ui/main_window.py:456-458`，模式 submenu：`503-515`。
- Acquisition 左侧测量列表右键：`mf4_analyzer/acquisition_ui/widgets/left_pane.py:293-319`。
- Acquisition 历史表右键：`mf4_analyzer/acquisition_ui/history_tab.py:664-683`。
- 主 Analyzer 通道树右键：`mf4_analyzer/ui/widgets/__init__.py:191-193`。
- 文件导航 kebab 菜单：`mf4_analyzer/ui/file_navigator.py:250-254`。
- Inspector preset 菜单：`mf4_analyzer/ui/inspector_sections.py:773-795`。
- Batch “已加载”菜单：`mf4_analyzer/ui/drawers/batch/input_panel.py:371-390`。

建议：

建立一个项目级弹层 helper，例如 `mf4_analyzer/ui_kit/popup.py`：

- `style_popup_shell(widget, object_name=None, *, transparent=True, suppress_native_shadow=True)`。
- 对 `QMenu` / `Qt.Popup` / frameless `QDialog` 统一处理：保留既有 `Qt.Popup` 行为，追加 `FramelessWindowHint | NoDropShadowWindowHint`，最后设置 `WA_TranslucentBackground`。
- 对 `QDialog` 类型弹层保持“透明外壳 + 内部 `QFrame` 绘制圆角白底”的模式，避免透明 dialog 自己不绘制中心白底。
- 后续所有新增圆角弹层必须走 helper，禁止散落手写 flags。

## P1 问题

### P1-1 内联 QSS 和 raw color 过多，影响全局一致性

证据：

- 全局按钮规则在 `style.qss:219-264` 已经定义 hover/pressed/checked/primary。
- 图片标注编辑器仍有多处内联按钮/面板 QSS，例如 `mf4_analyzer/ui/markup/editor.py:864-884`、`1055-1078`、`1138-1150`。
- 缩略图也整块内联 QSS：`mf4_analyzer/ui/markup/thumbnail.py:72-107`。
- SignalPicker popup 也内联了 display/popup 表面：`mf4_analyzer/ui/drawers/batch/signal_picker.py:114-195`。

建议：

把“可复用视觉语言”迁回 `style.qss` 或 UI kit：`role=tool`、`role=primary`、`popupSurface`、`swatchButton`、`compactIconButton`、`copyThumbnail`。业务代码只设 objectName/property，不重复写颜色和边框。

### P1-2 弹层验证门槛不统一

证据：

- `RebuildTimePopover` 已经采用正确的透明外壳 + 内部 `QFrame` 模式：`mf4_analyzer/ui/drawers/rebuild_time_popover.py:25-60`，测试也断言透明背景、无原生阴影和内部 surface：`tests/ui/test_rebuild_popover_geometry.py:84-100`。
- `SignalPickerPopup` 只断言 `WA_TranslucentBackground`：`tests/ui/test_batch_signal_picker.py:203-214`，当前未断言 native-shadow flags。
- `markupStyleMenu` 测试审计时同样只断言透明背景；Phase A 已补 native-shadow flags 断言。

建议：

把 rounded popup 的测试分成三档：

- 结构档：objectName、inner surface、`WA_StyledBackground`。
- shell 档：`WA_TranslucentBackground`、`FramelessWindowHint`、`NoDropShadowWindowHint`。
- 视觉档：截图/像素 harness 或真实 GUI 检查，特别是 macOS 原生菜单/二级菜单。

### P1-3 控件密度规则需要按“桌面工具”和“触控目标”分层

证据：

- 图片标注编辑器主要 icon 按钮是 44x44，符合较好的可点按面积：`mf4_analyzer/ui/markup/editor.py:856-883`、`916-925`。
- 图表 toolbar 的新增按钮是 32x32：`mf4_analyzer/ui/chart_stack.py:837-849`，这是桌面密集图表工具栏可接受的密度。
- 缩略图关闭按钮只有 22x22：`mf4_analyzer/ui/markup/thumbnail.py:47-50`。
- 折叠侧栏 strip 只有 12px 宽：`mf4_analyzer/ui/side_panels.py:74-84`，作为边缘 rail 可以存在，但需要稳定 hover/click 反馈和真实 GUI 验证。

建议：

规则化：

- 图片编辑器/可重复操作的 icon-only 工具：默认 44x44。
- 图表导航 toolbar：默认 32x32，但必须有 tooltip、active state、shortcut 或明确状态。
- 关闭/危险/小浮层按钮：视觉可以小，但 hit area 不应小于 30x30，必要时扩大透明点击区。
- 侧边 rail：允许 12px，但必须有 cursor、tooltip、hover 反馈和不误触的 delay。

### P1-4 旧入口仍混有 emoji/文本图标，和现有图标系统不一致

证据：

- `ChannelEditorDialog` 里按钮文本仍使用 `✚ 创建`、`🗑 删除`：`mf4_analyzer/ui/dialogs.py:64-102`。
- Acquisition replay 按钮用 `▶ Play` / `⏸ Pause` / `⏹ Stop`：`mf4_analyzer/acquisition_ui/replay_tab.py:110-123`。
- 主 toolbar 已经走 `mf4_analyzer/ui_kit/icons.py` 的图标体系：`mf4_analyzer/ui/toolbar.py:29-57`。

建议：

保留中文业务文本，但把装饰性 emoji 改成 `Icons`/`qtawesome` 统一图标，避免字体 fallback、字重不一致和跨平台缺字。

## P2 改进

1. `SearchableComboBox` / `QComboBox QAbstractItemView` 的 rounded popup 需要纳入弹层检查。当前 `style.qss:176-183` 给了下拉列表圆角，但构造路径 `mf4_analyzer/ui_kit/widgets/searchable_combo.py:240-281` 没有专门 shell 策略；如果实机出现方角，再套同一 popup 规则。
2. 把 raw color 逐步收敛成 `Precision Light` token 注释和 UI kit helper，不在业务模块散落新色值。
3. 图表/Inspector/Batch 三类高密度区域分别建立截图基准：避免“局部控件过宽/过窄”“tooltip 遮挡菜单”“状态只靠颜色”这类回归。

## 建议执行顺序

### Phase A：先修线宽菜单圆角阴影

- 改 `MarkupEditor._build_toolbar` 的 `markupStyleMenu`：增加 native-shadow flags。
- 更新 `test_style_menu_rounding_uses_translucent_background`，同时断言 `FramelessWindowHint` / `NoDropShadowWindowHint`。
- 运行 `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q`。
- 再做一次真实 GUI 检查：打开图片标注编辑器，点“样式（颜色 / 线宽）”，观察圆角外是否还有矩形阴影。

### Phase B：统一 popup/menu helper

- 新增 UI kit helper。
- 先迁移 `markupStyleMenu`、`SignalPickerPopup`、普通 `QMenu` 构造点。
- 给 helper 加一个静态/结构测试：新增圆角 `QMenu` 不能缺 shell flags。

### Phase C：全局视觉规则收敛

- 把内联 QSS 中的通用形态迁回 `style.qss`。
- 旧 emoji 按钮换为统一图标。
- 对 MarkupEditor、Chart toolbar、Side panels、Acquisition toolbar 做一次 screenshot/live pass。

## 新规则草案

- `UI-R1`: 任何圆角 popup/menu/popover 都必须是透明外壳；可见白底放内部 surface。
- `UI-R2`: macOS 顶层 `QMenu` / `Qt.Popup` 若有圆角，必须处理 `FramelessWindowHint | NoDropShadowWindowHint`，不能只靠 QSS `border-radius`。
- `UI-R3`: 弹层视觉问题不能只靠 attribute 测试结案；至少需要结构测试 + 实机截图/像素/现场检查之一。
- `UI-R4`: 业务模块不要新增大段内联 QSS；通用按钮、菜单、浮层、swatch、thumbnail 样式沉到 UI kit。
- `UI-R5`: icon-only 工具默认 44x44；桌面图表 toolbar 可 32x32，但必须有 tooltip、active state 和键盘/菜单替代路径。
- `UI-R6`: TraceLab 是工具型桌面应用，后续 UI prototype/方案必须贴近现有产品界面，不做 demo page 或营销页风格。

## 当前未验证

- 本轮没有打开真实 TraceLab GUI，也没有截图验证线宽菜单。结论基于代码路径、已有 tests 和既有 lessons。
- 普通 `QMenu` 构造点是否都肉眼可见方形阴影，需要 Phase B 后用真实 macOS 菜单逐个抽查。
