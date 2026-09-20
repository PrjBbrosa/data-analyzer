# Follow-up：弹出菜单后的图标状态残留与左栏最小宽度

- 日期：2026-09-20。
- 输入：用户四张截图；图 1 文件区“⋮”操作后仍带高亮，鼠标扫过消失；图 2–3 窄栏中下拉箭头被“应用”遮住；图 4“编辑通道”文字裁切。
- 状态：**已按 F0–F3 实施**（popup-trigger helper、左栏 300/320 宽度合同、focused 回归）。Cocoa 自然手势与 Windows 现场路径仍待用户环境验收。
- 基线：`24b45a94435049809f7035f12c5fbbb9663a7884` 的当前工作区，已有其他任务未提交的 Cursor、进度及测试修改；不将这些修改归为本次交付。
- 关联：[CAA 控件计划](2026-09-20-cursor-controls-caa-implementation-plan.md)、[进度及 Pin 投影计划](2026-09-20-progress-and-cursor-projection-hardening-plan.md)。本文件补充通用弹出层触发按钮及 navigator 几何边界，不取代上述计划。

## 1. 结论与优先级

| 优先级 | 问题 | 结论及证据等级 |
| --- | --- | --- |
| P1 | 配置下拉箭头被遮挡、编辑入口裁切 | **已确认**：允许的侧栏最小宽度小于其必需内容宽度，真实 FileNavigator + 生产 QSS 在 offscreen/Cocoa 均复现 |
| P2 | “⋮”菜单关闭后看起来还按着 | **已确认一条同构路径**：popup 关闭后按钮仍保留 hover，既非 pressed 也非 checked；offscreen 复现，Cocoa 本次注入手势未复现，用户现场路径仍需验收 |
| P2 | 以前修过，为什么仍有 | **已确认覆盖缺口**：之前修复仅在 Cursor 设置弹窗的局部回调中；文件区入口没有接入。现有窄栏测试只检查纵向对齐，未检查横向遮挡 |

本轮不能断言某个近期提交重新引入了图 1：已找到的是“同类问题的修复未覆盖所有入口”，没有完成能指认引入提交的现场复现或 bisect。宽度也不是下拉箭头资源丢失，不能靠改图标、抬高 z-order 或缩小字体解决。

## 2. 图标残留：hover 生命周期漏收尾

### 2.1 当前调用链与定向复现

- `mf4_analyzer/ui/file_navigator.py:446` 创建 `_btn_kebab`，它是非 checkable 的普通 `QToolButton`，`role="icon"`。
- 同文件 `:1095` `_open_kebab` 创建菜单，`:1100` 调用 `menu.exec_()`；返回后仅分发动作，没有校正触发按钮的鼠标状态。
- `mf4_analyzer/ui_kit/style.qss:1049` 一组 `role="icon":hover` 规则提供浅蓝底和边框；pressed 与 checked 是另外的规则。

使用真实 FileNavigator 和共享 stylesheet，模拟“移入 ⋮ → 点击打开 QMenu → popup 期间将指针移至右侧区域 → 关闭菜单”，读取：

| 时点（offscreen） | 指针确实在按钮内 | underMouse | isDown | isChecked |
| --- | --- | --- | --- | --- |
| 打开前悬停 | true | true | false | false |
| 菜单关闭，指针已在外 | **false** | **true** | false | false |
| 再扫入、移出 | false | false | false | false |

这解释了“像是点击态，但扫一下就消失”：Qt popup 抢占鼠标事件期间，触发按钮未获得与实际指针位置一致的 Leave/hover 收尾；样式继续按旧状态绘制。只调用 `setDown(False)` 对此路径没有作用。

**原生限制**：同一脚本在 Cocoa 中菜单关闭后的 underMouse 为 false，没有复现这条残留。该差异说明实际退出方式/事件顺序重要，不能把 offscreen 结果冒充用户当前平台验收。需覆盖选中动作、Esc、外部点击、菜单触发后继续弹确认框、窗口失焦等路径；目前未证明所有路径都坏。

### 2.2 之前修复为何没有覆盖这里

本地历史提交 `541f46f0`（2026-08-31，`fix(ui): complete cursor display followup`）引入的修复仍在：

`mf4_analyzer/ui/chart_stack/cards.py:1547` 的 `_on_cursor_display_popover_visibility_changed` 在弹窗隐藏时，先以 `QCursor.pos()` 映射到按钮检查真实位置；若确实在外，清除 `WA_UnderMouse`，重新 polish 并 update；还检查了 Qt 对象是否已销毁。

但该方法属于 **Cursor 设置按钮**，文件区 `_open_kebab`、相邻 `_open_follow_menu` 没有调用它。`ui_kit/menus.py::apply_rounded_menu_chrome` 目前只负责菜单外壳与子菜单圆角，也没有触发按钮参数。统一了菜单外观，不等于统一了关闭后触发器状态。

因此不应删掉既有修复或用全局 `:hover { background: transparent }` 掩盖。需要提取“小范围、可绑定触发器的关闭收尾”，让同类入口共享行为。

### 2.3 状态恢复必须保留的区别

- **hover**：由真实指针位置决定；指针仍在按钮上时保留正常 hover，不为了截图统一清空。
- **pressed/down**：由仍在进行的按压/抓取决定；只有确认交互已结束才重置，不能打断下一次按压。
- **checked/active**：业务状态，不是残留。尤其相邻链条按钮 `autoAttachFiles` 通过 `active="true/false"` 表达跟随设置，其高亮可能本来就应保留。
- **focus**：键盘交互需要的焦点反馈，不能一律 `clearFocus()` 或改 `NoFocus`。鼠标与键盘关闭路径分别验收。
- **菜单仍打开/嵌套弹窗**：子菜单隐藏不代表顶层菜单结束；动作打开确认框时也不能把焦点强行拉回旧按钮。

## 3. 窄栏遮挡：父级宽度合同已经小于子控件需求

### 3.1 根因与实测数据

当前 `main_window/window.py:495` 显式设置 navigator 最小宽度 **220px**，`:485` 初始分配是 **250px**。与此同时：

- `widgets/channel_config_bar.py:128–169`：保存 64、应用 64、combo 最小 132、两处间距各 6，底部行至少 **272px**。
- `widgets/channel_tree.py:953`：左右边距各 8；FileNavigator 自身左右边距各 3。该行要求整个侧栏至少 **272 + 16 + 6 = 294px**。
- 顶部“全选/全不/已选/编辑通道”也有自己的字体、图标和间距需求；“编辑通道”在当前生产样式下 minimumSizeHint 为 **90px**。
- FileNavigator 的 `minimumSizeHint().width()` 实测已经是 **294px**，但父级写入的显式 220px 下限允许 splitter 继续压缩；不能只相信 layout 已提供 sizeHint 就认为安全。

使用真实 navigator、水平 splitter 和生产样式，offscreen/Cocoa 两种后端得到一致几何（均为逻辑像素）：

| 实际 navigator 宽 | 底部行可用宽 | combo 宽 | 应用与下拉箭头相交 | 编辑通道实际宽 / 需求 |
| --- | --- | --- | --- | --- |
| 220 | 198 | 132 | **是** | **45 / 90** |
| 249 | 227 | 132 | **是** | **71 / 90** |
| 287 | 265 | 132 | 否，但仍不足以容纳完整行及间距 | 90 / 90 |
| 299 | 277 | 137 | 否 | 90 / 90 |
| 319 | 297 | 157 | 否 | 90 / 90 |

请求宽度与实际宽度可能相差 1px，表中使用实际 geometry，避免把 `setSizes()` 的比例请求当作实际分配。

在 220px 下，combo 的箭头区域位于底部行 `x=176..198`，应用按钮位于 `x=136..199`；这不是文字省略，而是两个控件实际区域重叠。顶部则是布局把编辑按钮压到 45px，图标和汉字共同被裁切。截图两处问题来自同一个父容器预算失配。

### 3.2 最小宽度定案

**展开的左侧 navigator 最小宽度设为 300 逻辑像素；初始/默认展开宽度采用 320 逻辑像素。** 300 是当前完整需求 294 的取整下限，不承诺任意字体环境固定 300 都够。

运行时规则：

```text
W_min = max(300, 当前生产样式下 navigator 的完整最小内容宽度)
W_default = max(320, W_min)
W_restore = max(历史展开宽度, W_min)
```

- 最小内容宽度取标题行、配置行及其他不可裁切行的最大需求，再计入实际容器边距/边框；由 FileNavigator/其子布局统一提供。不能把 294 当作第二套永久常量，也不能把 margins 重复相加。
- 测量需在 polish 后进行，Font/Style/DPR 或内容结构变化时更新；更新应合并，避免 LayoutRequest→setMinimumWidth→LayoutRequest 循环。
- `minimumWidth` 约束 **展开态**。完整收起仍允许 0 宽和现有边缘条；不出现 1..W_min-1 的半截面板。
- 默认 splitter 大小、SidePanelController 的 remembered/default width、恢复旧项目/会话、展开/固定和 **PEEK 浮出面板**共用该下限；不是只改 window.py 的 220。
- `side_panels.py::_position_overlay` 当前依赖 remembered width 与 peek_width，未显式纳入 panel minimumWidth；现有左栏 peek 下限来自右侧 Inspector 宽度，不能继续用左右视觉对称代替内容需求。
- 正常空间不足时优先沿用现有侧栏收起机制，保持图表最小宽度，不通过裁切编辑/下拉入口补偿。若 host 连最小 peek 宽度也容不下，需在现有 side-panel 状态机内明确拒绝该次 peek/保持收起，不能让宽 panel 超出 overlay 后被截掉。
- 搜索占位文字或长配置名可按可用宽度正常省略，但箭头、保存/应用和编辑通道完整可见可点。不要求最小宽度下整句 placeholder 全部显示。
- 这里规定的是 **左侧栏**宽度；主窗口当前 1100px 最小宽度先保持。验证三栏/边缘条/字体实际总预算，只有测得总预算不足才调整主窗口下限，不因侧栏问题盲目扩大整窗。

## 4. 横向排查清单：按机制覆盖，不把所有高亮都当 bug

| 入口家族 | 当前证据 | Follow-up 范围 |
| --- | --- | --- |
| FileNavigator 文件 ⋮、跟随链条菜单 | 两个手动 `exec_` 入口无共同触发器收尾；⋮ 已有 offscreen 复现 | 首批接入；链条 active 高亮不可被清除 |
| 顶部保存分裂按钮 | `toolbar.py::_open_save_menu` 用异步 `popup` | 验证实际触发按钮而非整个 host；异步关闭使用同一收尾合同 |
| Cursor 设置及新 CAA 编号菜单 | 设置按钮已有局部修复；CAA 菜单仍在实施计划中 | 保留既有行为并复用低层 helper；CAA 首次落地即覆盖关闭路径 |
| 图表工具条弹出设置、Inspector 预设/帮助浮层 | QMenu、Qt.Popup 等生命周期不同 | 按真实 trigger→popup→dismiss 调用链建清单；只接入确有同类机制者 |
| UltraView 卡片/Board 菜单 | 部分 `popup`；`page.py::_restore_menu_trigger` 目前只负责恢复焦点 | 检查 mouse hover 和键盘焦点各自职责；保留独立窗口、卡片业务选择和嵌套菜单行为 |
| 右键背景菜单、树菜单 | 通常没有按钮 trigger | 不硬造触发按钮，不改正常 selection 或背景 hover |
| Combo、InstantPopup 原生按钮 | 原生控件具有自己的事件收尾 | 先验证，不批量重写原生弹出机制；与配置行本体重叠分开诊断 |
| 通用 checked、分段按钮、Pn 三态、跟随 active | 都可能有合法持续高亮 | 作为误伤回归；不能被“清理全局状态”清掉 |
| 左侧 dock/peek/restore 与同类固定行 | 已确认左栏多入口宽度不统一 | 同一宽度合同贯穿全部入口；右侧 Inspector/Batch 仅发现相同预算冲突才另列修复 |

“全局横展”交付应为有 owner、退出路径、验证结论的入口清单；不是把一个 QApplication 级过滤器强装到所有按钮，也不是此次重构所有 UI。

## 5. 实施任务及验收门

### F0 — 固化两个真实失败，补齐现场退出路径

- 将本轮 hover 探针转为 focused 回归：菜单打开时指针离开，关闭后无需额外 mouseMove 即恢复；同时断言真实位置、underMouse、down/checked 与生产 QSS 像素。禁止只手工置 false 后断言自身。
- 窄栏回归使用完整 FileNavigator + 水平 splitter，不直接给 config bar 一个足够宽的独立 host。覆盖 220/250 的旧失败、300 下限、320 默认、宽→窄→恢复，以及 100%/150%/200% 逻辑/设备像素区分。
- 首先断言 sibling 几何不相交、箭头 subControlRect 全部可见且命中属于 combo、编辑图标+文字在内容框内；不能只看按钮 `isVisible()`。
- 原生记录菜单选项、Esc、外点、确认框、失焦、指针停留在 trigger 内外；Cocoa 当前未复现图 1 的分支保持未验证，不用 sleep 强行通过。

**Owner tests**：`tests/ui/test_file_navigator.py`、`tests/ui/test_channel_config_bar.py`；原生证据留 `.state/`。

### F1 — 统一有触发按钮的 popup 关闭收尾

- 在现有 `ui_kit` 低层增加或扩展一个可复用 helper，显式绑定 trigger 与 popup；不让低层 import MainWindow 或业务 UI。`menus.py` 可连接生命周期，但圆角外观函数不应暗中清业务状态。
- 同步 `exec_`、异步 `popup`、自定义 Qt.Popup 的关闭均按同一“实际指针位置 + 交互已结束”合同处理。`aboutToHide` 期间原生 grab 可能尚未释放，必要时排队一次到关闭完成；带 Qt 生命周期及本次打开标记，避免旧回调清掉马上重开的菜单状态。
- 先接 FileNavigator 和保存菜单；既有 Cursor 回调迁移时保持行为 parity。其余清单逐项取证接入，不能用静态搜索存在 `QMenu` 就宣告通过。
- 不清 checked/active、不强抢焦点、不向按钮发送 synthetic click；必要的 repolish/update 仅针对实际变化的 trigger。
- 菜单复用不能重复 connect；trigger/menu 销毁后回调安全退出。临时菜单及时释放，不因每次打开绑定累积长期对象或回调。

**Focused**：file_navigator、toolbar 的相应测试；新增低层 popup-trigger 用例；现有 Cursor popover 测试与跟随 active 渲染测试。**Boundary**：`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`；改 QSS 才加 `tests/ui_kit/test_qss_border_shorthand.py`。

### F2 — 左栏统一实测下限

- FileNavigator 提供一个明确最小宽度来源；保留子控件的固定宽/最小宽以及 combo stretch。按第 3.2 节设置 300 下限、320 默认。
- `main_window/window.py` 用该值取代孤立 220/250；`SidePanelController` 在 dock/peek/restore 对当前 panel 的宽度限制取值，不新增跨 MainWindow 状态字段。
- 恢复旧 220/250/288 宽度时钳制展开值，保留 hidden/pinned 意图；配置文件不需 schema 迁移。收起阈值与 0 宽行为保留。
- 测试字体/样式变化与首帧布局，避免“拖一下才恢复”；从 parent size hint 追到实际 geometry，完整验证顶部与底部两行。

**Focused**：`tests/ui/test_channel_config_bar.py`、`tests/ui/test_file_navigator.py`、`tests/ui/test_side_panel_widgets.py`；只有状态机 reducer 发生改动才加 `test_side_panel_reducer.py`。接线改动运行现有 MainWindow 相关布局测试；不因 window.py 变更就通跑全部 UI。

### F3 — 收口与防止再次漏覆盖

- 在稳定的相关文件快照上运行一次适用整合门，复用同指纹已通过结果。不得与其他任务在同一 checkout 重叠启动全量测试。
- 验收：关闭菜单后不移动鼠标也正确；合法 active/checked/focus 保留；所有展开途径不少于 W_min；“编辑通道”和下拉箭头完整可点击；收起与 peek 不退化。
- Cocoa 自然手势与 Windows 环境分别记录。offscreen、原生注入探针、用户原场景、截图重渲染是不同证据。
- 如更改用户操作入口或提示，同步 `ui/hints.py` 与 `ui/quickref.py`；本方案原则上保留操作语义，单纯修复悬停/布局不需重写无关文案。

## 6. 本轮执行结果与现有测试盲区

本地诊断文件：`.state/2026-09-20-button-rail-followup/probe.py`、`offscreen.log`、`cocoa.log`，以及 `nav-220.png`、`nav-300.png`、`nav-320.png`。后一次 Cocoa 运行覆盖了同名截图；日志分别保留。截图为控件 grab，不能替代现场自然显示验收。两次探针正常退出。

运行两个现有相关测试：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_channel_config_bar.py::test_config_bar_top_aligns_with_view_rail_in_navigator_width_host \
  tests/ui/test_file_navigator.py::test_follow_link_active_chrome_survives_hover_and_idle_stays_plain -q
```

结果：**2 passed in 0.88s**。这不是修复验收：前者把 navigator 固定为 250px，但只检查顶部/中线等纵向关系；本轮已经证明该宽度横向重叠。后者检查链条按钮 active/idle 与 hover 的配色，未覆盖 ⋮ 菜单关闭后的 stale hover。缺失的是正确的行为断言，而非再多跑一次同样测试。

参考已有 lessons：`codex-channel-config-host-geometry-render.md`、`codex-stateful-icon-button-active-qss.md`。本轮将其要求转入具体失败探针和实施门，不重复新建同内容 lesson。文档交付检查链接、路径及 `git diff --check`；产品实施仍待后续指令。
