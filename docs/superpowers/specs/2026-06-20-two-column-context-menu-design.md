# 图表右键菜单两列面板 + 第三槽自定义动作按钮 — Design Spec

- 初稿日期：2026-06-20（两列面板）
- 修订日期：2026-06-27（第三槽：pan 快捷键 → 自定义动作按钮，整段重写）
- 状态：两列四行（鼠标/查看/范围/网格）**已实现并合并**；本次新增 = 鼠标行**第三槽自定义动作按钮**，待实现。
- 范围：pyqtgraph 图表右键菜单（TimeDomain subplot/overlay、FFT line/time preview、FFT-vs-Time heatmap、Order heatmap、analysis split pane）和对应 HTML 原型。

## 1. Decision

图表右键菜单已经是一个**两列 inline panel**（`_PgContextInlinePanel`，左操作列 / 右弱说明列），五行：鼠标、查看、X范围、Y范围、网格。这部分已落地，不在本次改动范围内。

本次只改**鼠标行的第三个槽位**：

```text
[框选] [平移] [自定义▾]    鼠标
[Y适应] [全图]            查看
[0.0] — [1.0]            X范围
[-1.0] — [1.0]           Y范围
[X] [Y]                  网格
```

鼠标行三槽固定为：左 `框选`(zoom)、中 `平移`(pan)、右 `自定义动作按钮`。

`框选` / `平移` 是一对**互斥鼠标模式**；第三槽是一个**可绑定单个"执行型"动作的即点即走快捷按钮**，与 zoom/pan 平级但语义不同。它让用户把一个高频动作（默认"复制为图片"）放到右键后最顺手的位置，并可随时换绑成池子里的其它动作。

> 本次明确**废弃**上一版修订（2026-06-26）里把第三槽当作「pan 键盘快捷键自定义入口」的整套设计，以及配套的 hints shortcut resolver / QShortcut 重绑 / QInputDialog 录入。原因见该设计的审查结论：键盘快捷键覆盖会引入「改键后 QShortcut 不重绑」「跨注册表冲突检测不全」「菜单内弹模态框」等硬伤，且与用户真实意图（可切换的动作按钮）不符。

## 2. Product Rules

### 2.1 两列语义（已实现，保留）

- 左列是操作区（按钮、输入框、chip）；右列是弱化说明标签（`鼠标`/`查看`/`X范围`/`Y范围`/`网格`），不可点击、不抢视觉权重、无竖分割线。

### 2.2 鼠标行文案与槽位

- 左槽 `框选`、中槽 `平移` 沿用现有图标按钮（`mdi.magnify-plus-outline` / `mdi.cursor-move`），tooltip 保留完整语义。
- 右槽 = 自定义动作按钮：未绑定显示 `+`；绑定后显示该动作的图标，右下角带一个 `▾` 换绑角标。

### 2.3 范围显示规则（已实现，保留）

- X/Y 范围行显示当前真实 `viewRange()`，不固定显示「自动」；合法 min/max 用 `padding=0` 应用，非法输入恢复原值。`Y适应`/`全图` 走现有 handler。

### 2.4 网格规则（已实现，保留）

- 网格 X/Y 为两个 checkable chip；`allow_y_grid=False` 时 Y chip disabled；应用走 `show_major_grid_left_bottom_only(..., alpha=0.28)`，不点亮 top/right grid。

### 2.5 鼠标模式规则（保留 zoom/pan，删除 pan 快捷键自定义）

- 鼠标行 zoom/pan 继续由 toolbar controller 驱动：优先 `set_mouse_mode_broadcast(mode)`，回退 `set_zoom_mode()` / `set_pan_mode()`；`current_mouse_mode()==''` 时两者都不高亮；分屏 peer 广播、防递归、shared toolbar 高亮刷新语义不变。
- **本次删除**：pan 键盘快捷键的「默认值 + 用户覆盖 + 冲突检查 + 重置」整套逻辑，以及 `hints.py` 的 shortcut override resolver。鼠标行不再承载任何键盘快捷键编辑。

### 2.6 自定义动作按钮规则（本次新增核心）

**动作类型**

- 第三槽只能绑定**执行型动作**：点一下就执行完的一次性操作。不收模式型（游标关/单/双、分屏⇄叠加、标注开关）和需要持续高亮态的动作——这些是 Non-Goal，留 v2。

**v1 动作池（4 个，附 handler 来源）**

| action id | 文案 | 图标(qta) | handler 来源 | 接线状态 |
|---|---|---|---|---|
| `copy_image` | 复制为图片 | `mdi.content-copy` | card `copy_image_requested` → `ChartStack._copy_card_image` | **需新增注入** |
| `back` | 上一步视图 | `mdi.arrow-left` | `controller.back()`（PgNavigationToolbar:513） | 现成（同 controller） |
| `forward` | 下一步视图 | `mdi.arrow-right` | `controller.forward()`（:524） | 现成 |
| `export` | 导出/保存图片 | `mdi.content-save-outline` | `controller.save_figure()`（:628） | 现成 |

- **刻意排除** `home` / `view_all`（全图）/ `y_fit`（Y适应）：这三个面板的「查看」行右侧已经有了，放进池子重复无增量。池子只保留**面板外、真正有增量**的执行型动作。
- 图标 qta 名实现时可对齐 toolbar 上同动作已用的图标以保持一致。

**交互**

- **点主体** = 执行当前绑定动作，随后关闭菜单（走现有 `_run_handler(close=True)` 模式，context_menu.py:476/601）。
- **点 ▾ 角标** = 在 ▾ 下方弹出一个**无边框 `Qt.Popup` 浮窗**列表（**不走 `QMenu`、不弹模态对话框**）；列表每行一个动作，当前绑定项打勾，不可用项 disabled。（注:就地 inline 展开经真机验证会被 `QMenu` 裁剪、不重绘,故采用 §4 的 popup 备选。）
- **在列表里点一项** = 立即改绑 + 持久化 + 收起列表；菜单保持打开，让用户能立刻点主体执行或继续别的操作。
- **fallback 态**（`QSettings` 缺失/非法时）= 整钮显示 `+`，点击直接展开动作列表选一个绑定。v1 动作列表只含 4 个绑定项，**不提供主动「清空/无」入口**——正常使用第三槽始终绑着某个动作（默认 `copy_image`），`+` 仅作异常兜底。

**作用域 / 默认 / 空态 / 持久化**

- 绑定**全局一份**，所有 pyqtgraph 图表共享（4 个动作都是通用导航/输出动作）。
- 出厂默认绑定 = `copy_image`（高频、面板外、降低发现门槛）。
- 持久化：`QSettings` key `chartContext/customAction`，值为 action id 字符串；空字符串/缺失视为「未绑定」→ 显示 `+`。
- 复用现有 `QSettings()` 全局配置（org/app 已由主窗设定，见 main_window/_project_io_mixin.py:261 `QSettings("MF4Analyzer","DataAnalyzer")`）。

**可用性 / disabled**

- 绑定的动作在当前图表/上下文不适用时（对应 handler 未注入，如未注册 controller 的图表上的 `back`/`forward`/`export`），第三槽 **disabled** 但**位置保留、不隐藏**（复用 overlay 下 Y网格 chip 的 disable 模式）。
- 因为默认绑定 `copy_image` 需要注入，**所有走 `redesign_pg_context_menu` 的调用点都必须注入 copy handler**，否则默认动作在该图表恒 disabled。这是硬性接线要求（见 §6 验收）。

**视觉区分（关键：别让人误以为是模式）**

- 第三槽**不进** zoom/pan 的 `QButtonGroup`（context_menu.py:431），**不做** checked 持久高亮，只做 hover/按下反馈。
- 通过 `▾` 角标 + 动作图标，与 zoom/pan 的纯图标互斥按钮在视觉上区分开。

### 2.7 复用范围规则（保留）

- 第三槽与整个 inline panel 都是通用图表能力，统一走 `_PgContextInlinePanel` / `redesign_pg_context_menu`，禁止在某个 canvas 内复制独立布局。必须覆盖 §范围 列出的每个 pane 及后续新增 pyqtgraph chart。

## 3. Visual Spec

### 3.1 复用已实现 token

- 沿用现有两列面板 token（菜单宽度、`10px` padding、行高 `_INLINE_CONTROL_HEIGHT`、三轨列宽、右说明列 `#94a3b8`/字重 600、圆角 7-8px）。本次不调整四行的尺寸。

### 3.2 第三槽几何

- 第三槽按钮：`32 x _INLINE_CONTROL_HEIGHT`，与 zoom/pan 同尺寸，落在鼠标行右轨。
- `▾` 角标：贴按钮右下，小尺寸（约 10px），不撑大按钮；点击命中区可略大于视觉尺寸以便点中。
- 未绑定 `+`：字号/字重醒目，居中。
- 动作图标：18px，与 zoom/pan 图标一致。

### 3.3 换绑列表

- 换绑浮窗列表：每行 `≥28px`，左图标 + 中文案，当前项高亮/打勾。
- 列表背景/圆角复用面板内层 QSS 风格（透明外壳 + 内层承载，避免 `WA_TranslucentBackground` 让 QSS 失效——见 §4）。
- disabled 行文字弱化（`#b8c2d0`），不可点。

### 3.4 Interaction Feel

- 展开/收起列表时面板高度变化应平滑、不闪烁；菜单整体高度增长可接受，但收起后恢复原高度。

## 4. Architecture

在 `mf4_analyzer/ui/pg_canvas/context_menu.py` 内实现，复用现有 `_PgContextInlinePanel`：

**动作注册表（新增）**

- 模块级注册表 `_CUSTOM_ACTION_ORDER` / `_LABELS` / `_ICONS` + `_resolve_custom_action(...)`，定义 v1 的 4 个执行型动作。
- 一个解析层：`redesign_pg_context_menu` 调用时，根据传入的 `controller` + 各 handler，把「当前上下文实际可用」的 action 集合算出来（哪些有 handler、哪些 disabled）。

**第三槽组件（新增）**

- `_PgCustomActionButton(QWidget)`：主体按钮 + `▾` 角标 + 就地展开的动作列表；负责读/写 `QSettings`、渲染当前绑定、disabled 态、换绑列表的展开/收起。
  - **展开方案（真机已定）**：就地 inline 展开经真机验证会被 `QMenu` 裁剪、不重绘,故采用**无边框 `Qt.Popup` 浮窗**——`host.setParent(panel, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)`,锚在 `▾` 下方;内层 `QFrame#pgContextActionListCard` 承白底圆角,避 `WA_TranslucentBackground` 让 QSS 失效的坑。host 虽是独立窗口但 QObject 仍挂在 panel 下(可 findChild/受 QSS)。
- 透明背景遵循项目铁律：外层 `WA_TranslucentBackground`，换绑列表的卡片背景由**内层子 widget 的 QSS** 承载（参照 quickref_panel 的「外透明 / 内 QFrame 承 QSS」模式），或 `paintEvent` 兜底，避免灰底/QSS 失效。
- 持久化 helper：`_load_custom_action()` / `_save_custom_action(action_id)`，读写 `chartContext/customAction`。

**`redesign_pg_context_menu` 签名扩展**

- 新增参数 `copy_image_handler=None`（其余动作经现有 `controller` / `view_all_handler` / `y_autofit_handler` 取得）。
- `_build_mouse_row` 把第三槽从「空占位」改为 `_PgCustomActionButton`，放在 col 2；pan 仍在 col 1（已是中槽）。

**调用点接线**

- `canvas._redesign_context_menu_for_viewbox`（canvas.py:1244）注入 `copy_image_handler`。copy handler 由 card/stack 注入到 canvas（canvas 不直接持有 card），具体注入路径在 plan 中确定；要求覆盖 time/FFT/heatmap/analysis 所有 card。

**不新增**

- 不新增 `hints.py` 的 shortcut resolver；不动 `chart_stack/_helpers.py` 的 nav QShortcut 安装；不新增数值算法。

## 5. Non-Goals

- 不做模式型动作（游标关/单/双、分屏⇄叠加、标注开关）的绑定 → v2。
- 不做「复制游标值」→ v2（需新写剪贴板 handler + 处理游标未开态）。
- 不做面板型动作（刻度密度、图表选项）的绑定。
- 不引入键盘快捷键覆盖 / QShortcut 重绑 / 冲突检测。
- 不改数值算法、不改 chart toolbar 布局、不改 inspector、不改已实现的四行行为与尺寸。
- 不做「每图表类型各绑一份」——v1 全局一份。

## 6. Acceptance Criteria

- [ ] 鼠标行三槽为：左 `框选`、中 `平移`、右 自定义动作按钮；pan 在中槽。
- [ ] 第三槽**不在** zoom/pan 的 `QButtonGroup` 内，且不显示 checked 持久高亮。
- [ ] 出厂默认绑定为 `copy_image`，首次打开第三槽显示「复制为图片」图标可点。
- [ ] 点主体执行当前绑定动作并关闭菜单；动作真实生效（如 copy 真把图片放进剪贴板）。
- [ ] 点 `▾` 弹出无边框 `Qt.Popup` 浮窗列表，**不**产生新的 `QMenu` 或模态对话框。
- [ ] 列表含 4 个动作，当前绑定项打勾；不可用动作 disabled。
- [ ] 在列表里选另一动作后：第三槽立即改绑、`QSettings` `chartContext/customAction` 写入对应 id、列表收起、菜单保持打开。
- [ ] 重开菜单/重启应用后绑定保持（读 `QSettings`）。
- [ ] 绑定动作在当前图表不适用时第三槽 disabled 且位置保留。
- [ ] 所有走 `redesign_pg_context_menu` 的图表都注入了 copy handler（默认动作不应在任何标准图表上恒 disabled）。
- [ ] 第三槽与换绑列表背景透明无灰底、圆角正确（真机/objc 验证，非仅单测）。
- [ ] 已实现的四行（查看/范围/网格行为、translucent、no native shadow、tooltip 契约）不回归。

## 7. Test Requirements

- `tests/ui/test_pg_timedomain_canvas.py`
  - 鼠标行槽位顺序：zoom / pan / 自定义；pan 在中槽。
  - 第三槽 objectName 稳定（如 `pgContextCustomActionButton`）、不在 zoom/pan 的 button group、无 checked 高亮。
  - 默认绑定 = `copy_image`；点主体调用注入的 copy_image_handler 且关菜单。
  - 点 `▾` 后存在动作列表 widget（`Qt.Popup`,QObject 仍挂 panel 下可 findChild），且菜单 actions 未新增 `QMenu`/无模态。
  - 选另一动作后 `QSettings` 写入对应 id、第三槽图标改变、列表收起、菜单未关。
  - 不可用动作（构造缺 handler 的场景）在列表中 disabled。
  - 已有四行结构/行为测试保持通过。
- `tests/ui/test_pg_line_canvas.py`
  - FFT line / time preview 的右键菜单使用同一第三槽；默认 copy_image 可点。
- `tests/ui/test_pg_heatmap_canvas.py`
  - FFT-vs-Time / Order heatmap 的右键菜单使用同一第三槽；未注册 controller 时 `export` 等在列表 disabled，但 `copy_image`（已注入）可用。
- `tests/ui/`（持久化）
  - 用临时 `QSettings`（IniFormat + 临时路径）或 monkeypatch 隔离，断言 `chartContext/customAction` 读写，**不污染真实用户配置**。
- 原型 `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`
  - 鼠标行第三槽更新为 `[自定义▾]`，并演示就地展开的动作列表；移除旧的「自定义平移快捷键 `+`」语义。
- 真机/offscreen 渲染验证
  - 右键各 section 确认第三槽渲染、▾ 命中、列表透明无灰底、换绑后图标更新（不靠「属性设上了 + 单测过」下结论）。

## 8. 后续（v2，记录不实现）

- 模式型动作绑定（游标/分屏）：需第三槽支持「当前态显示 + 循环切换」语义。
- 复制游标值：需新 handler + 游标态联动。
- 发现性：v1 落地后走 `/update-hints`，评估为「▾ 可换绑」加 footer hint + quickref 条目。
