# UltraView Miro 对标操作与 UI 恢复 Plan

- 日期：2026-08-20
- 状态：**READY FOR REVIEW — DOCS ONLY；本 Plan 不授权本轮修改产品源码**
- Spec：`../specs/2026-08-20-ultraview-miro-operation-ui-restoration-spec.md`
- 认可原型：`../ui-prototypes/2026-08-19-ultraview-authoring-tools-prototype.html`
- 当前分支/HEAD：`codex/ultraview-authoring-tools` / `14ef0c17`
- 最后正常渐变基线：`c80f46e0`

## Supersedes

本 Plan 取代以下旧执行方向中与新 Spec 冲突的部分：

- `2026-08-20-ultraview-miro-authoring-completion-plan.md` 的 Card selection toolbar、独立 Connector
  rail、去渐变 chrome 和以 08-20 prototype 为视觉门的 Task；
- `2026-08-20-ultraview-authoring-chrome-contract-recovery-plan.md` 的 W1 Card toolbar、W3 删除
  `UV_RAIL_ACTIVE_*` token 和继续使用文字属性栏的 Task。

旧文档保留为历史证据，不原地改写。后续执行必须引用**本文准确路径**，不能从旧 W1/W3 继续施工。

## 0. 结果目标与实施原则

### 0.1 最终结果

完成后用户应得到：

1. 左侧有子选项的工具一按就弹选项；
2. author object 一点就出现贴着对象的 icon-first 属性栏；
3. View/Card 不再出现大属性栏，恢复 hover 右上角图标；
4. UltraView 既有 panel/mode 恢复钛蓝→琥珀渐变；
5. 08-19 HTML 的 N/S/P/T 操作节奏在真实 PyQt 中成立；
6. 已定 Board / Library / Layout / Filter / Unplaced / Sync / Global / Nav 内容零变化。

### 0.2 核心执行顺序

```text
W0 冻结事实与防误改护栏
  -> W1 View/Card hover 恢复（先去掉最刺眼的错误投影）
  -> W2 钛蓝琥珀渐变恢复
  -> W3 rail + anchored flyout 对齐 08-19 HTML
  -> W4 author 属性栏 icon-first 重构
  -> W5 compact / focus / rounded surface 收口
  -> W6 集成、文案、Cocoa、Windows 发布门
```

W1/W2 是可独立交付的恢复波；W3/W4 是体验主波；W5/W6 是验收收口。任何波都不得顺手修改
Card preview、resize、Fit、数据 schema 或既有 panel 内容。

### 0.3 工作树纪律

当前 checkout 已有大量未提交的 UltraView authoring/chrome 改动和验证文件。实施前必须：

- 记录 `git rev-parse HEAD`、`git status --short` 和相关文件 hash；
- 确认现有未提交改动的 owner，不能覆盖、回退或把它们误算成本 Plan 产出；
- 如果相关源码仍在变化，W0 只写红测/差异清单，不启动视觉施工；
- 每波只 stage 本波明确文件；不碰 `ssh-keygen`、`ssh-keygen.pub` 等无关文件；
- full suite 只由稳定 integration milestone 的单一协调者执行一次；各波只跑 focused/boundary gates。

## 1. 文件所有权与允许触点

| 文件/模块 | 本 Plan 的责任 | 禁止扩张 |
|---|---|---|
| `ui/chart_stack/ultraview/widgets.py` | Card hover action 显隐/compact/focus 回归 | 不改 preview/capture/resize/ghost |
| `ui/chart_stack/ultraview/page.py` | Card 排除、author toolbar 显隐/定位、flyout 路由 | 不新增第二个 selection/tool owner |
| `ui/chart_stack/ultraview/chrome.py` | 现有 panel rail 投影、兼容 re-export | 不改 Board/Library/Layout/Filter 内容 |
| `ui/chart_stack/ultraview/author_chrome.py` | author flyout、icon-first toolbar | 不拥有 state/history |
| `ui/chart_stack/ultraview/author_selection.py` | author-only capability 与 icon intent | 不把 Card 再格式化 |
| `ui_kit/ultraview_style.py` | 恢复已定 active tokens | 不建第二套 palette |
| `ui_kit/style.qss` | 渐变、surface、icon/hover/focus 状态 | 不做全局 QSS 重排 |
| `ui/hints.py` / `ui/quickref.py` / help | 只同步真实发布入口 | 不承诺未实现功能 |
| tests | 每条用户手势的回归门 | 不用类存在/emit 代替端到端行为 |

Connector/Stroke 等 author DTO、render、save、history 模块原则上不改；若入口合并需要 typed intent，
只改最小路由，不重写算法。

## W0 — 冻结事实、建立失败护栏

### 目标

把用户的 6 条问题变成会失败的自动化/截图清单，避免下一波再次以“样式看起来差不多”收尾。

### Task 0.1 记录施工快照

- [ ] 记录 HEAD、dirty fingerprint、分支和 Python/Qt/DPR；
- [ ] 归档当前四张 offscreen 证据：selected Card、selected Shape、Sticky flyout、800×560；
- [ ] 只读浏览 08-19 HTML，记录 N/S/P/T 四个状态的 screenshot 和几何；
- [ ] 建立“面板内容不改”清单：rail 既有 panel 顺序、各 panel action id、Board/Global/Nav action；
- [ ] 记录 Card action bar 的五个 action 和“常驻显示卡片操作”当前偏好投影。

### Task 0.2 先写失败测试

新增或调整以下 owner 测试，改前应至少覆盖失败路径：

1. `test_card_selection_does_not_show_author_property_toolbar`
2. `test_card_hover_reveals_existing_action_bar_and_leave_hides_it`
3. `test_card_action_preference_keeps_hover_bar_visible`
4. `test_author_selection_shows_toolbar_near_bounds`
5. `test_toolbar_contains_no_forbidden_word_labels`
6. `test_sticky_click_opens_anchored_large_swatch_flyout`
7. `test_shapes_click_opens_combined_shape_connector_flyout`
8. `test_draw_click_opens_icon_preset_flyout`
9. `test_panel_and_mode_states_keep_titanium_amber_gradient_tokens`
10. `test_existing_panel_action_inventory_is_unchanged`

测试不得只检查类名或 signal emit。Card hover 要用真实 enter/leave/focus 路径；toolbar 要断言真实 geometry、
button text/icon/accessibility；flyout 要断言 trigger-relative geometry。

### Task 0.3 禁止词与 action inventory

- [ ] 为 selection toolbar 建立可见文字禁止词集合：`TIME/FFT/SHAPE/INK/类型/填充/描边/线宽/线型/
      圆角/文字/复制/锁定/打开源/同步/聚焦/Card Fit`；
- [ ] 允许字体名、字号、B/I/U 与极短真实值；
- [ ] 对现有 Board/Library/Layout/Filter/Unplaced/Sync/Global/Nav action key 建立 shrink-only inventory；
- [ ] Connector/Stroke old project fixture 保存重开，保证入口重组不孤儿化对象。

### 证据与出口

- docs-only 快照无需 runtime pass，但测试文件一旦加入必须展示预期红；
- 用户问题 U1–U7 每条都有 test/screenshot 对应项；
- 相关源码仍被并发修改时状态写 `BLOCKED FOR SOURCE FREEZE`，不进入 W1。

## W1 — View/Card hover 行为恢复

### 目标

最先移除当前最明显的错误：Card 上方大文字 toolbar。恢复已经存在的右上角 hover icon 作为唯一 Card
操作入口，不重写 Card action bar。

### Task 1.1 切断 Card → author toolbar 投影

- [ ] `_refresh_author_toolbar()` 遇到 `caps.kind == "card"` 直接隐藏；
- [ ] selection 含 Card 的 `card_author` 同样隐藏 author toolbar；
- [ ] `author_selection.py` 不再为 Card 生成 visible toolbar controls；若能力仍用于键盘/selection，改为
      non-visual capability，不删除 selection identity；
- [ ] 删除/停止 Card Signal Spine、`TIME/FFT/TF/FRF/ORDER` 的 toolbar 投影；
- [ ] 不删除 Card selection outline、move、多选、keyboard 语义。

### Task 1.2 恢复并冻结 `_CardActionBar`

- [ ] 保留现有 Open / Focus / Fit / Remove / More 五个 action；
- [ ] hover、card focus、action-button focus、常驻偏好四种 reveal 条件都可见；
- [ ] leave 但焦点仍在 action button 时不隐藏；
- [ ] compact 优先收 Fit，不允许按钮重叠；
- [ ] Presentation 隐藏；Stale Sync 走既有路径；
- [ ] action 继续发射现有 Card/Page signals，不复用 SelectionToolbar 的第二套 signal。

### Task 1.3 Card 前台检查

- [ ] 真实 Card 默认 idle 截图；
- [ ] hover 截图；
- [ ] 常驻偏好截图；
- [ ] 窄 Card/TITLE_ONLY 截图；
- [ ] 逐个点击 Open / Focus / Fit / Remove / More；Remove 使用测试副本，不能保存原 fixture。

### Owner tests

- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_card.py` 或现有 Card owner 文件
- `tests/ui/test_ultraview_selection_toolbar_contract.py`
- `tests/ui/test_ultraview_author_multiselect.py`
- `tests/ui/test_ultraview_visible_actions.py`

### 出口

Card 单击/多选从不显示 author toolbar；hover/focus/常驻偏好是唯一 Card action UI；五个 action 全部走既有
信号。最高状态 `CODE COMPLETE / COCOA UNVERIFIED`，直到前台跑完。

## W2 — 钛蓝琥珀渐变恢复

### 目标

精确恢复 `c80f46e0` 已定的 active panel/mode 状态，不做新的调色实验。

### Task 2.1 恢复 token

- [ ] `ULTRAVIEW_QSS_TOKENS` 重新导出：
  - `UV_RAIL_ACTIVE_START = #3C8495`
  - `UV_RAIL_ACTIVE_END = #F0A44C`
  - `UV_RAIL_ACTIVE_HOVER = #2F7181`
- [ ] token 只从 `ULTRAVIEW_TITANIUM` 映射，不在 QSS 写第二份 hex；
- [ ] 更新 `tests/ui_kit/test_ultraview_style.py`，精确断言三 token 和消费者存在。

### Task 2.2 恢复 selector 状态矩阵

- [ ] `modeActive=true` 恢复 start→end + white glyph；
- [ ] `panelOpen=true` 恢复同一 gradient + white glyph；
- [ ] mode+panel 组合只画同一 gradient；
- [ ] hover/pressed 恢复 `UV_RAIL_ACTIVE_HOVER`；
- [ ] empty View Library CTA 恢复 `UV_BRAND → UV_AMBER`；
- [ ] Presentation exit island 保持 `UV_BRAND → UV_AMBER`；
- [ ] author `[active=true]` 保持 selection blue wash，不误刷渐变；
- [ ] Board selector作为导航 menu-open 继续 quiet outlined，不被全局 selector 吞掉。

### Task 2.3 rendered pixel test

- [ ] 不只做字符串测试；构造 idle/hover/modeActive/panelOpen/combined/emptyCta/presentation/author-active
      状态板；
- [ ] 抽取中心/两端像素，证明 start/end 不同且 author active 仍为蓝 wash；
- [ ] 1×/2× DPR 检查白 glyph 对比和圆角 backing；
- [ ] QSS 不使用 `border:` 伪状态 shorthand 破坏 radius。

### Owner/boundary tests

- `tests/ui_kit/test_ultraview_style.py`
- `tests/ui/test_ultraview_chrome.py`
- `tests/ui/test_ultraview_mode_integration.py`
- `tests/ui_kit/test_qss_border_shorthand.py`
- `tests/ui_kit/test_qss_duplicate_selectors.py`

### 出口

已定 panel/mode/CTA/presentation 渐变全部恢复；author active 仍与 panel active 语义分离；Cocoa 状态板与
`c80f46e0` 对照无回退。

## W3 — rail 与 anchored flyout 对齐认可 HTML

### 目标

让左侧作者工具真正遵循“点按钮就看到选项”，并把当前小色块/文字说明面板改成认可 HTML/Miro 的
icon/preset 选择层。既有 panel 内容完全不动。

### Task 3.1 rail 尺寸与分组

- [ ] desktop rail 64 px、author target 46×46、icon 22 px；
- [ ] compact rail 52 px、target 40×40、icon 20 px；
- [ ] 作者入口投影为 Select / Sticky / Text / Shapes / Draw；
- [ ] Connector 从 rail 独立占位合并进 Shapes flyout，`L` 快捷键保留；
- [ ] existing panel entry 顺序/action key 不变；
- [ ] shortcut 只放 tooltip，不在按钮常驻 V/N/T/S/P 字母；
- [ ] icon registry 中每枚 icon 非 null、相同 stroke/visual box；不混 Unicode 占位符。

### Task 3.2 通用 flyout owner

- [ ] 复用/收敛 `ToolFlyoutSurface`，统一 8 px anchor gap、stage clamp、outside click、Esc、focus；
- [ ] one active flyout；打开新工具关闭旧工具；
- [ ] 第二次点 active 只开关 flyout，不取消 tool；
- [ ] 删除固定空白高度，按内容 `adjustSize()`；
- [ ] shell `WA_TranslucentBackground` + inner surface；
- [ ] 800×560 高度超限时内部 scroll，不裁切 rail/nav。

### Task 3.3 Sticky flyout

- [ ] 4×4、16 色，48–52 px swatch，8 px gap；
- [ ] 选中 ring 与 tooltip/accessibility；
- [ ] 底部满宽 icon + `Stack`；去掉“固定连续创建”长按钮；
- [ ] 选色 one-shot，Stack continuous；palette token 和保存字段不变；
- [ ] 对照用户 Miro 图 #2 与 08-19 HTML screenshot。

### Task 3.4 Shapes & Connectors flyout

- [ ] 一层列出 Line/Arrow/Elbow + Rectangle/Rounded Rectangle/Oval/Rhombus/Triangle；
- [ ] Block Arrow 仅在完整纵切已存在时显示；否则隐藏，不做 dead action；
- [ ] icon + 短名称 + 右侧 shortcut；无说明段、无 More Shapes 假入口；
- [ ] 选择 line/shape 分派到既有 typed tool，不复制 state machine；
- [ ] `S` 打开 flyout，`L` 直达最近 connector；
- [ ] 旧 connector object render/select/delete/save/reopen 不受入口合并影响。

### Task 3.5 Draw flyout

- [ ] Pen/Highlighter/Eraser/Lasso 第一行 icon cells；
- [ ] 三档真实 width preview；
- [ ] 颜色圆形 swatches；
- [ ] 删除常驻“不做像素擦除”等解释段，只留 tooltip；
- [ ] Pen/Highlighter/Eraser continuous；Lasso 完成回 Select；
- [ ] QSettings preset 仍不进 project/history。

### Owner tests

- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_author_tools.py`
- `tests/ui/test_ultraview_author_integration.py`
- `tests/ui/test_ultraview_author_connector_slice.py`
- `tests/ui/test_ultraview_author_draw_slice.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_no_lambda_signal_connections.py`

### Cocoa gate

1280×720 与 800×560 各抓 Sticky / Shapes / Draw 三张；逐项记录 rail anchor、尺寸、色块、图标、
圆角、文字密度。截图对照对象是 08-19 HTML 和用户 Miro 图，不是 08-20 offscreen prototype。

### 出口

N/S/P 单击都立即出现正确选项；V/T 不弹空壳；既有 panel 内容/action inventory 零差异；无 dead entry。

## W4 — author 属性栏 icon-first 重构

### 目标

把当前文字按钮墙改成与用户 Miro 图 #4 同类的图标化上下文工具条，并只对 author object 生效。

### Task 4.1 capability 仅描述语义，不提供 UI 文案

- [ ] `SelectionCapabilities` 输出 control key、value、icon role、checkable/mixed/enabled；
- [ ] UI label 只用于 tooltip/accessibility，不作为默认 button text；
- [ ] card/card_author 不生成 visible author toolbar；
- [ ] 同类 author 多选计算共同值；异类只保留共同 action；
- [ ] formatter chooser 使用真实 value，不再调用 `_next_*` 轮询枚举。

### Task 4.2 icon-first control factory

- [ ] 建立一个 typed icon control factory：icon、swatch、line preview、shape preview、short value；
- [ ] 普通 target 36–38 px；toolbar 高 48 px；
- [ ] 字体名/字号和 B/I/U 是明确例外；
- [ ] fill/stroke/color 是 swatch，width/dash 是真实 line preview，lock/duplicate/delete 是 icon；
- [ ] 禁止词自动化测试必须通过；
- [ ] `⋯` 使用锚定圆角菜单，只容纳低频动作/compact overflow。

### Task 4.3 按元素实现

- [ ] Sticky：shape / palette / font size / align / lock；
- [ ] Text：T / font / size / B/I/U / align / list / link / text color / fill / lock；
- [ ] Shape：shape / fill / stroke / width / dash / corner / text / lock；
- [ ] Connector：route / heads / color / width / dash / label / lock；
- [ ] Stroke：tool / color / width / lock；
- [ ] mixed author：只显示安全共同动作，indeterminate 用图形，不用 `—` 冒充值。

### Task 4.4 chooser

- [ ] 点击 shape/fill/stroke/width/dash/corner/route/head/color/tool 打开相邻的小 chooser；
- [ ] chooser 复用 W3 的 palette/shape/preset primitives，不建第二套样式；
- [ ] outside click 关 chooser但不清 selection；
- [ ] apply 一次产生一条现有 history；
- [ ] bool 控件（B/I/U/lock）可直接 toggle；
- [ ] editor/IME focus guard 不回归。

### Task 4.5 定位与 gesture settle

- [ ] bounds 上方 8 px，空间不足下方；X clamp；
- [ ] 去掉 normal path 的 `y=56` 和固定中心 fallback；
- [ ] selection bounds 不可用时隐藏，不把 toolbar 钉在页面上；
- [ ] drag/resize/draft 期间隐藏，release 后一次定位；
- [ ] 800×560 单行，wide/低频 action 进入 More；
- [ ] Card action hover 不影响 author toolbar geometry。

### Owner tests

- `tests/ui/test_ultraview_selection_toolbar_contract.py`
- `tests/ui/test_ultraview_author_multiselect.py`
- `tests/ui/test_ultraview_author_text_slice.py`
- `tests/ui/test_ultraview_author_shape_slice.py`
- `tests/ui/test_ultraview_author_connector_slice.py`
- `tests/ui/test_ultraview_author_draw_slice.py`
- `tests/ui/test_ultraview_board_hit_routing.py`
- `tests/ui/test_ultraview_page.py`

### Cocoa gate

Sticky/Text/Shape/Connector/Stroke 各选一个；截图测 toolbar 与 bounds 间距、控件高度、禁止词、chooser、
compact overflow。真实点击每个 icon，不能只看静态截图。

### 出口

纯 author selection 才显示工具条；Card 永不显示；每个控件用 icon/swatch/value 表意且行为真实；禁止词
为零；chooser 替代轮询。

## W5 — compact、焦点、圆角与视觉收口

### 目标

在不改功能内容的前提下，把 1280×720 和 800×560 的几何、keyboard、backing pixels 收到发布质量。

### Task 5.1 compact 几何

- [ ] 800×560 rail 全量可见，不隐藏已有 panel；
- [ ] target 40×40，分隔/间距允许压缩但不小于 2 px；
- [ ] flyout 上下 clamp，必要时内容 scroll；
- [ ] toolbar 单行，More 可访问；
- [ ] View/Card 右上角 action 不压住 title/status；
- [ ] Global/Nav 现有 overflow 行为不变。

### Task 5.2 focus/keyboard

- [ ] V/N/T/S/P/L 不抢 text editor；
- [ ] Tab 只进入 visible action；
- [ ] flyout/chooser Esc 层级正确；
- [ ] focus ring 2 px；
- [ ] Card hover bar 由键盘 focus 揭示并能完整操作；
- [ ] no-lambda ratchet 不增长。

### Task 5.3 rounded material

- [ ] rail/flyout/toolbar inner surface 与 translucent shell 分离；
- [ ] 四角像素在 1×/2× 不出现矩形底；
- [ ] QSS pseudo-state 不用 border shorthand 清掉 radius；
- [ ] shadow 只一层；无大面积 opacity effect/blur；
- [ ] Titanium gradient 只在 Spec 状态矩阵出现，不污染 author active/swatch。

### Boundary gates

- `tests/ui_kit/test_qss_border_shorthand.py`
- `tests/ui_kit/test_ultraview_style.py`
- `tests/ui/test_no_lambda_signal_connections.py`
- `tests/ui/test_main_window_state_ownership.py`
- `tests/ui/test_import_boundaries.py`
- `tests/ui/test_ultraview_mode_integration.py`

### 出口

两档窗口、两档 DPR 的静态与交互截图通过；keyboard 可用；圆角无 backing；没有修改既有 panel action。

## W6 — 集成、文档与平台门

### Task 6.1 focused integration

按顺序运行，不一开始跑 full suite：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/ui/test_ultraview_board_hit_routing.py \
  tests/ui/test_ultraview_author_chrome.py \
  tests/ui/test_ultraview_author_tools.py \
  tests/ui/test_ultraview_author_text_slice.py \
  tests/ui/test_ultraview_author_shape_slice.py \
  tests/ui/test_ultraview_author_connector_slice.py \
  tests/ui/test_ultraview_author_draw_slice.py \
  tests/ui/test_ultraview_author_multiselect.py \
  tests/ui/test_ultraview_page.py -q
```

随后跑边界：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui_kit/test_ultraview_style.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_help_content.py -q
```

实际测试文件名以执行时 checkout 为准；不存在的 planned test 必须先创建，不能从命令中悄悄删除。

### Task 6.2 用户可见文案

- [ ] `hints.py` / `quickref.py` / UltraView guide 同步 V/N/T/S/P/L 的真实入口；
- [ ] 明确 S 中含连接线，P 中含擦除/套索；
- [ ] View 操作描述为 hover 右上角图标/常驻偏好，不描述 Card property toolbar；
- [ ] 不在界面加解释段；详细说明只进 guide/tooltip；
- [ ] 不改 Board/Library/Layout/Filter/Unplaced/Sync/Global/Nav 名称。

### Task 6.3 Cocoa 前台验收

用真实 TraceLab 和 `testdoc/1.tlproj` 的只读副本：

1. 1280×720：idle、panel gradient、Sticky flyout、Shapes flyout、Draw flyout；
2. Text/Shape/Connector/Stroke 属性栏；
3. Card idle/hover/focus/常驻偏好；
4. 800×560：rail、flyout clamp、toolbar More、Card compact；
5. DPR 1×/2× 圆角和 gradient；
6. N/S/P/T/V/L 真实手势；
7. undo/redo、save copy、reopen、overview/export 不回归。

对照表必须逐项写“符合/偏差”，对象是：

- 08-19 accepted HTML；
- 用户 Miro 参考图 #1–#4；
- `c80f46e0` gradient；
- 本 Spec A1–A8。

不得用 08-20 offscreen prototype 替代本轮基线。

### Task 6.4 Windows 与 full suite

- [ ] Windows Full/Lite frozen 验证 flyout、font fallback、Ctrl 快捷键、DPI、rounded corners；
- [ ] 若发版/合并门要求 full suite，先确认没有其他 pytest；
- [ ] 在稳定 source snapshot 记录 before/after HEAD + dirty fingerprint；
- [ ] main suite 与 `tests/acquisition_ui` 分两个新进程顺序跑，不并发；
- [ ] 相关文件在运行中变化则结果标 `UNVERIFIED`；
- [ ] 没跑 Windows/full suite 就明确写未验收，不能用 focused count 代替。

### 出口

- Cocoa 手势和截图全部通过；
- focused/boundary gate 绿色；
- panel action inventory 零差异；
- 文案只描述真实能力；
- Windows/full suite 的状态诚实记录。

## 2. 验收矩阵

| 用户问题 | 代码门 | 视觉门 | 失败判据 |
|---|---|---|---|
| 左按钮弹选项 | N/S/P anchored flyout tests | 三张 flyout Cocoa 图 | click 后只变 active、空盒、二级长菜单 |
| 元素属性栏 | author-only capability + bounds tests | 五类 author toolbar 图 | Card 也显示、固定 y、拖动中抖 |
| 少文字/图标 | forbidden-word + non-null icon tests | toolbar 密度对照 | 文字按钮墙、Unicode 占位、无 tooltip |
| 渐变恢复 | token/selector/pixel tests | state board | tint/solid 代替 gradient、token 被删 |
| View 恢复 hover | enter/leave/focus/preference tests | idle/hover/compact 图 | Card 大 toolbar、重复 action、hover 无图标 |
| 对齐 HTML/Miro | N/S/P/T scenario tests | 08-19/Miro 对照表 | 只对 08-20 自产 prototype 对照 |
| 面板内容不改 | action inventory | before/after rail/panel 图 | 删除、改名、迁移既有功能 |

## 3. 回滚与风险控制

### 3.1 可独立回滚边界

- W1 只切 Card projection，失败可恢复 projection 而不动 author data；
- W2 只恢复已知 token/selector，失败可按 `c80f46e0` 精确对照；
- W3 入口合并只改 chrome/typed dispatch，不删除 Connector/Draw implementation；
- W4 保持 capability keys/history mutation，不改 object schema；
- W5 只做 geometry/QSS/focus；
- 每波单独 commit，禁止把 W1–W5 压成一个难以回滚的大提交。

### 3.2 主要风险

| 风险 | 预防 |
|---|---|
| 合并 S/L 后旧 Connector 入口丢失 | 保留 `L` shortcut、typed tool、save fixture、visible-action tests |
| Card hover 与 selection gesture 冲突 | action button hit 优先；Card body 仍进入 selection/move |
| icon-only 降低可发现性 | tooltip + accessibleName + QuickRef；真实图标而非晦涩符号 |
| 800×560 rail 放不下 | compact 40 px target、2 px gap、flyout scroll；不隐藏既有 panel |
| QSS gradient 破坏 radius | 禁止伪状态 border shorthand；rendered corner pixels |
| dirty worktree 覆盖他人改动 | W0 fingerprint + ownership；相关文件变化即暂停集成 |
| offscreen 看起来对，Cocoa 仍差 | W1–W5 都保留真实前台出口，不等到最后才看图 |

## 4. Definition of Done

本 Plan 完成的必要条件：

- [ ] Spec U1–U7 和 A1–A8 全部有证据；
- [ ] View/Card 只使用原 hover/focus/常驻 action bar；
- [ ] author toolbar icon-first、贴 bounds、无禁止词；
- [ ] N/S/P anchored flyout 与 08-19 HTML 操作一致；
- [ ] Titanium Amber gradient 与 `c80f46e0` 一致；
- [ ] Board/Library/Layout/Filter/Unplaced/Sync/Global/Nav inventory 零变化；
- [ ] focused + boundary gates 绿色；
- [ ] Cocoa 1280×720、800×560、DPR 1×/2× 通过；
- [ ] Windows frozen/full suite 状态明确；
- [ ] `git diff --check` 通过；
- [ ] 只提交本 Plan 范围文件，不夹带工作树其他改动。
