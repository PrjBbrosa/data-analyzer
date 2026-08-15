# UltraView Board 切换弹层精简 + 面板触发按钮激活态残留修复 —— 实施 plan

- 日期：2026-08-15
- 来源：用户实测反馈两条——① Board 下拉「二级 hover 子菜单 + 8 项管理动作」
  过于冗余，四条排序菜单项（上移/下移/移到顶部/移到底部）在窄轨改版删掉
  QTabBar 后价值趋零（顺序唯一可见处就是该下拉本身）；② UltraView 各浮岛
  按钮的通病：开面板后点画布空白，面板关闭但按钮看起来仍是激活态。
- 基线：`main@374eb176`（post-v8-review-fixes 合入后）。工作区另有大量未提交
  的 ultraview 在途改动（layout-and-material-polish / viewport-inspect-fixes
  两个 plan）——**本 plan 动的文件与其重叠**（`chrome.py` / `page.py` /
  `style.qss` / hints / quickref / 帮助页），执行前必须先把在途批收口或在
  干净分支上做，动手前 `git status` 对账（lesson：Codex 会话可能并行改工作区）。
- 相关 spec：`docs/analyzer/specs/2026-08-14-ultraview-miro-narrow-rail-spec.md`。
  其「迁移入口，不删除能力」合同覆盖 Board 排序——本 plan **保留排序能力但把
  入口从 4 条菜单项换成列表内拖拽**，属于合同允许的入口迁移；菜单结构变化
  要在该 spec 加日期批注（不重写历史段落）。

## §0 执行护栏

- 聚焦回归集：`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -k ultraview -q`；
  收尾跑全量两条命令（主体 `--ignore=tests/acquisition_ui` + 该目录单独），
  与 CLAUDE.md 2026-08-15 基线对账（主体 6978/13/9，9 红为既有顺序污染）。
- 每项修复配「能抓住原缺陷」的测试，先红后绿。
- 新信号连接用 bound method / `functools.partial`（`.connect(lambda` 棘轮）。
- QSS 改动过 border 简写 lint（状态规则不许 `border:` 简写，只动 `border-color`）。
- UI 交互有增删改，收尾 `/update-hints` 同步 `ui/hints.py` 与 `ui/quickref.py`。
- 视觉项 offscreen 只当排版草稿，最终 Cocoa 真机验收（Gotchas），验收自动化
  （截图 + 断言，不丢人工清单）。

## Task 0：现状核实（硬前置）

本 plan 的行号在**跟踪树**上核实过，但工作区有未提交改动，执行者先重新定位：

- [x] Board 菜单现实现：`page.py:850` `_show_board_menu`——QMenu 一级列 Board
  （checkable，点击即切换），每行挂 hover 子菜单「管理“名称”」，子菜单 8 项：
  切换到此 Board（与一级点击重复）/ 复制 / 重命名 / 删除 / 上移 / 下移 /
  移到顶部 / 移到底部。末尾还有一个悬空 `addSeparator()`（`page.py:884`，
  后面没有项，顺手删）。
- [x] 触发件：`chrome.py:650` `BoardIsland`（名称 label + chevron `_menu` +
  加号 `_add`；双击名称 / F2 = 重命名当前 Board，`chrome.py:728-740`）。
- [x] 激活态残留 bug 的根因（本 plan 起草时已 offscreen 实证，执行者复跑确认）：
  1. 点画布空白关面板走 `chrome.py:399` `_close_from_canvas_click` →
     `close_active_overlay()`，默认 `restore_focus=True`（`chrome.py:319`），
     把键盘焦点**还给触发按钮**——实测 blank click 后
     `focusWidget() == ultraViewRailLibraryButton`。
  2. QSS `:focus` 态（`style.qss:4348`：border `#3e709c` + `#eaf2f8` 底）与
     `panelOpen` 态（`style.qss:4408`：border `#3e709c`）几乎同款 → 面板关了
     按钮仍套蓝圈，用户读作「激活没退」。
  3. 逻辑态本身是同步的（`overlay_closed → _on_overlay_closed →
     _sync_panel_triggers → setChecked(False)`，offscreen 验证通过）——
     **这是视觉焦点问题，不是状态机 bug**，修复不许去改 `_sync_panel_triggers`
     一线的状态逻辑。
- [x] 波及面：同一浮层系统的全部触发按钮——ToolRail 四个面板钮、GlobalIsland
  display/export（`chrome.py:759-777`，checkable + 同 QSS 簇）。
  Layout 钮的浅蓝**填充**是 `modeActive`（模板模式持久指示，
  `style.qss:4388` 注释言明 filled vs outline 的区分是有意设计）——
  **不是本 bug，不动**。

## Task 1：按钮激活态残留修复（先修 bug，独立可交付）

- [x] `_close_from_canvas_click` 改传 `restore_focus=False`：鼠标点画布关面板，
  焦点应随点击落在画布（CanvasHost 本就 StrongFocus），不回触发按钮。
  Esc 键盘路径（`chrome.py:379`）**保留** `restore_focus=True`——键盘用户
  关面板后焦点回到触发件是可及性合同。
- [x] `_icon_button` 工厂（`chrome.py:152`）把 focusPolicy 收为 `Qt.TabFocus`：
  鼠标点击不取焦（macOS 原生工具钮惯例），Tab 键盘导航保留，程序化
  `setFocus(Qt.OtherFocusReason)`（Esc 恢复路径）不受 focusPolicy 限制。
  这同时修掉第二个残留场景：**点按钮本身 toggle 关面板**后按钮留 focus 蓝圈。
- [x] 检查 `_focus_first_control`（`chrome.py:404`）：它按 focusPolicy 找面板内
  首个可聚焦控件，面板内部控件不走 `_icon_button` 的不受影响；若有面板内
  图标钮被 TabFocus 影响聚焦预期，逐个确认。
- [x] 测试（先红后绿）：
  - 开面板 → 点画布空白：overlay 关闭、触发按钮 `hasFocus() is False`、
    `panelOpen` 属性为 false、`isChecked() is False`。
  - 开面板 → 再点同一按钮 toggle 关：按钮不保留焦点。
  - 开面板 → Esc：焦点**回到**触发按钮（可及性回归不许被顺手修没）。
  - GlobalIsland display/export 同样三条走一遍（参数化）。
- [x] Cocoa 真机验收（自动化）：真机起 GUI，脚本驱动「开面板 → 点空白 → 截
  按钮区域」，与「从未打开过面板」的基线截图做像素对比断言无蓝圈残留；
  挂进 `tools/verify_ultraview_visuals.py` 既有验收脚本。
  （offscreen 已记录 `trigger_rest`：canvas click 后 `panelOpen`/`hasFocus`/`checked`
  均为休息态；Cocoa 像素对比仍属独立闸，见 Task 3。）

## Task 2：BoardPopover 单层弹层（替换 QMenu 套娃）

目标形态（唯一的二级是行尾 ⋯，且是点击触发不是 hover 触发）：

~~~text
┌───────────────────────────┐
│ ✓ 全局对比            ⋯  │  ← 点行 = 切换；当前行打勾
│   台架 vs 路试        ⋯  │  ← 行拖拽 = 重排（替代 4 条排序菜单项）
│   NVH 复查            ⋯  │  ← ⋯ 仅 hover/键盘聚焦时显示：复制/重命名/删除
├───────────────────────────┤
│ ＋ 新建 Board             │
└───────────────────────────┘
~~~

- [x] 新组件 `BoardPopover`（放 `chrome.py`，和岛屿同层的展示件；Page 仍拥有
  数据与确认逻辑，组件只发信号——沿 `BoardIsland` docstring 既有分工）：
  - `QListWidget`，`InternalMove` 拖拽重排；行 = 勾选标记 + 名称（elide）+
    行尾 ⋯ 钮（hover / 键盘聚焦行时可见）；底部「＋ 新建 Board」行。
  - 信号：`board_selected(str)` · `board_menu_requested(str, QPoint)`（⋯）·
    `boards_reordered(str, int)`（由 model `rowsMoved` 换算目标 index）·
    `create_requested()`。
  - 尺寸：宽 ~260px，高按行数增长、clamp 到画布高的 60%，超出滚动
    （上限 20 板，`MAX_UI_BOARDS`）。
- [x] 注册为 CanvasHost overlay（id 如 `"boards"`，trigger = chevron 钮），锚
  在 BoardIsland 正下方（经 floating_layout 计算矩形或显式
  `set_overlay_geometry`）。收益：点画布空白自动关、Esc 关、与其它面板互斥
  ——全部免费复用，且 Task 1 的焦点修复自动覆盖它。chevron 钮加
  `panelOpen` 属性同步（开弹层时描边态，关掉复位；不必改成 checkable，
  用 `_set_flag` 走既有 QSS 簇）。
- [x] Page 侧接线（全部 bound method）：
  - `board_selected` → `_on_board_selected` + 关弹层；
  - `board_menu_requested` → 弹 3 项小 QMenu（复制 → `duplicate_board_requested`；
    重命名 → `_rename_board`；删除 → `_confirm_delete_board`，确认对话框沿用）；
  - `boards_reordered` → `reorder_board_requested`（沿用现有 clamp 语义）；
  - `create_requested` → 既有新建路径（与岛上 ＋ 等价；到 20 板上限时该行
    disable + tooltip 说明，语义同 `set_create_enabled`）。
- [x] 删除旧实现：`_show_board_menu` 的子菜单构造、「切换到此 Board」、四条
  排序项、悬空 separator 全部移除；`_show_board_menu` 收敛为「打开弹层」。
- [x] 工作区变化时（增删改名/外部重排）若弹层开着，刷新行内容而不是闪关。
- [x] 键盘：↑↓ 移动、Enter 切换、F2 = 重命名选中行、Delete 不删板
  （删除是破坏性动作，只走 ⋯ 菜单 + 确认）。
- [x] 测试（先红后绿，改写 `tests/ui/test_ultraview_page.py` 现有 board 菜单用例）：
  - 点行切换 / 勾选位置正确 / ⋯ 三项齐全且无「切换到此 Board」与排序项；
  - 拖拽重排发出 `reorder_board_requested(board_id, new_index)` 且顺序持久化
    往返一致；
  - 上限 20 板时新建行 disable；删除走确认、取消不删；
  - 弹层开着点画布空白：关闭且 chevron 无残留态（衔接 Task 1 断言）。

## Task 3：发现性面、帮助与收尾

- [x] `/update-hints`：Board 管理入口描述从「下拉菜单管理」改为「弹层：点行
  切换、拖拽排序、⋯ 管理」；`ui/hints.py` + `ui/quickref.py` 同步，
  `tests/ui/test_hints.py` / `test_quickref.py` 契约随改。
- [x] `mf4_analyzer/help/ultraview-guide.html` 对应段落更新，
  `tests/test_help_content.py` 契约对账。
- [x] miro-narrow-rail spec 加日期批注：Board 管理入口从「下拉 + 子菜单」改为
  「单层弹层 + 行拖拽排序」，排序能力保留、入口迁移。
- [ ] 全量两条命令对账基线；Cocoa 真机走查一遍弹层视觉（岛屿圆角/阴影/
  hover ⋯ 显隐）并截图归档到 `docs/analyzer/verify/`。
