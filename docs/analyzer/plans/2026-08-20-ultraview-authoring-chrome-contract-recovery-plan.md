# UltraView 作者工具 Chrome 合同恢复 Plan

- 日期：2026-08-20
- 状态：**CODE COMPLETE / FOREGROUND UNVERIFIED**
- Spec：`../specs/2026-08-20-ultraview-authoring-chrome-contract-recovery-spec.md`
- 体验合同：`../specs/2026-08-20-ultraview-miro-authoring-experience-spec.md` §4–§7
- 前置评审：`../reviews/2026-08-19-ultraview-two-wave-regression-review.md`
- 施工基线：`14ef0c17`（branch `codex/ultraview-authoring-tools`）

> 每一波是一个可被用户完整感知的纵向修复；出口以「缺陷编号闭合 + owner 测试 + 截图证据」
> 计，不以「代码写了」计。W1 是本 Plan 的最小可交付切口：单独完成即可消掉
> 「UI 全错」观感的大部分来源。

## 0. 总结与依赖

### 0.1 缺陷 → 波次映射

| Spec 缺陷 | 波次 |
|---|---|
| D1 工具条钉死 | W1 |
| D2 卡片按钮空壳 | W1 |
| D3 Spine 恒 FFT | W1 |
| D4 More 死入口 / Delete 常驻 | W1 |
| D7 flyout 空盒 | W1 |
| D5 命中漏 Connector/Stroke + Page 抢事件 | W2 |
| D6 格式轮询 | W3 |
| D8 QSS 状态混色 | W3 |
| D10 page.py 膨胀 | W4 |
| D9 预览白底 | 非目标（另立 spec） |

### 0.2 执行图

```text
W0 冻结 + 入口回收（含 hints/quickref/help 扇出）
  -> W1 选择工具条合同（D1/D2/D3/D4/D7）
  -> W2 统一命中路由（D5）——过门后才讨论 Connector/Draw 入口恢复
  -> W3 格式选择器 + QSS 状态收敛（D6/D8）
  -> W4 page.py 指针路由拆出（D10）
  -> W5 Cocoa 前台走查门
```

W1 依赖 W0（入口集合先定下来，工具条才知道要为哪些 kind 服务）；W3 依赖 W1
（选择器锚定在工具条按钮上）；W4 依赖 W2（路由统一后才能整体搬迁）；W5 收尾。

### 0.3 不允许的执行方式

- 不新增工具、对象类型、QSS 主题实验；
- 不跑全量套件（本 Plan 全程属聚焦修复，不是发版/合并验收；见 CLAUDE.md 测试门禁）；
- 不在 Task 0 写「先跑全量拿基线」；改前基线 = 各 Task 的 owner 用例；
- 新信号连接不使用 lambda（`test_no_lambda_signal_connections.py` 棘轮只许缩小）；
- 不把 offscreen 截图写成 Cocoa 视觉验收；
- 不为绕过护栏放宽任何白名单（状态所有权 / backref / QSS border 简写）。

### 0.4 共用验证门（每波出口都跑）

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py -q
```

QSS 改动波（W3）追加 `tests/ui_kit/test_qss_border_shorthand.py`；
入口/文案改动波（W0）追加 `tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_help_content.py`。

## W0 — 冻结与入口回收

### 目标

停止表面扩张；把未过命中门的 Connector / Draw 从 release rail 收回（Spec E1），
用户可见合同（hints / quickref / help）同步。

### Task 0.1 回收 release 入口

- [ ] `chrome.py` 的 `RELEASE_AUTHOR_TOOLS` 收为 `select / sticky / text / shapes`；
- [ ] 对应快捷键 guard（`_on_connector_tool_shortcut` / `_on_draw_tool_shortcut` 已按
      `visible_author_tools` 判断，确认无残留旁路）；
- [ ] 已存项目中的 Connector/Stroke 对象仍渲染、仍可经通用动作删除（写一条回归用例钉住）。

### Task 0.2 用户可见合同扇出

- [ ] `ui/hints.py`、`ui/quickref.py` 移除 connector/draw 的创建入口条目
      （保留「已有对象可选中/删除」的说明）；
- [ ] `help/ultraview-guide.html` 同步；
- [ ] 更新三份契约测试的期望集合。

### Owner 测试

- `tests/ui/test_ultraview_author_chrome.py`（rail 可见集合）
- `tests/ui/test_hints.py` / `test_quickref.py` / `tests/test_help_content.py`
- 新增：`tests/ui/test_ultraview_page.py` 里一条「隐藏入口不孤儿化已存对象」用例

### 出口

release rail 与文档三面一致；无 dead affordance；docs-only 部分无需 runtime 测试的理由已在
本 Task 写明（纯文案行由契约测试看守）。

## W1 — 选择工具条合同（最小可交付切口）

### 目标

闭合 D1 / D2 / D3 / D4 / D7。用户选中任何东西时，看到的是一条贴着选区、按钮全部有行为、
类型标签正确的上下文工具条。

### 所有权

- `page.py`（`_refresh_author_toolbar` 定位逻辑、card 动作分派）
- `author_selection.py`（capabilities：axis kind 输入、card 控件集合、`can_duplicate` 修正）
- `author_chrome.py`（`SelectionToolbar` More 菜单、`ToolFlyoutSurface` sizeHint 删除）

### Task 1.1 定位（D1，Spec T1）

- [ ] `_refresh_author_toolbar` 计算 selection bounds（card geometry 并集 / author bounds
      像素映射 / 混选并集），上方 8 px 优先、下方兜底、X clamp；
- [ ] 拖动 / draft / geometry session 期间隐藏（现有 gesture 判断扩展到 author session）；
- [ ] owner 用例断言：同一对象在画布上、下两个位置选中时工具条 y **不相等**且随 bounds 移动
      （直接杀死 `y=56` 常数）。

### Task 1.2 Signal Spine（D3，Spec T2）

- [ ] `resolve_selection_capabilities` 增加 `axis_kinds` 输入（Page 提供 ref→axis_kind）；
- [ ] card 同 kind → `TIME/FFT/TF/FRF/ORDER` + 分类色；混 kind → `CARD` + selection blue；
- [ ] owner 用例：时域卡选中 Spine 为 `TIME`，不是 `FFT`。

### Task 1.3 卡片动作接线（D2，Spec T3）

- [ ] open / sync / focus / fit / copy image 接到 Page 既有信号（bound method）；
- [ ] capabilities 层修 `can_duplicate`：card-only 选择不出 duplicate 控件；
- [ ] 单卡 delete 走 `remove_ref_requested`；多卡时 open/focus 不出现；
- [ ] owner 用例：card 单选下逐个点击工具条按钮，断言对应信号 payload。

### Task 1.4 More 菜单与 Delete 收纳（D4，Spec T4）

- [ ] `more_requested` 接锚定圆角菜单（`apply_rounded_menu_chrome`），Delete/z-order/
      compact 溢出项入内；
- [ ] Delete 移出常驻控件；键盘路径不变；
- [ ] owner 用例：More 菜单弹出且含 Delete；常驻控件集合里无 delete key。

### Task 1.5 Flyout 收紧（D7，Spec T5）

- [ ] 删 `ToolFlyoutSurface.sizeHint`；最小宽度下放到具体 flyout；
- [ ] owner 用例：Sticky flyout 高度 < 220（按内容），Shape flyout 无底部空白带
      （高度与 inner layout sizeHint 差 ≤ 边距）。

### Task 1.6 offscreen 截图对照

- [ ] Page 级渲染四张：选中卡片、选中形状、Sticky flyout、800×560 compact；
- [ ] 与 `docs/analyzer/ui-prototypes/screenshots/2026-08-20-ultraview-miro-authoring/`
      的决策截图做结构对照，结论与图存
      `docs/analyzer/verify/2026-08-20-ultraview-chrome-recovery/`。

### Owner 测试

- 新文件 `tests/ui/test_ultraview_selection_toolbar_contract.py`（Task 1.1–1.5 用例聚在一处）
- 既有 `tests/ui/test_ultraview_author_multiselect.py`（capabilities 变更回归）

### 出口

D1/D2/D3/D4/D7 全闭合；截图对照入库；状态最高 `CODE COMPLETE / FOREGROUND UNVERIFIED`。

## W2 — 统一命中路由

### 目标

闭合 D5。`classify_press` 覆盖五类对象；Page eventFilter 只在 armed/draft 时拦截；
Select 下 Connector 不偷卡片点击。

### Task 2.1 命中集成（Spec H1）

- [ ] `_author_keys_at` 扩展为逐对象按类型命中：box 类走现有矩形，Connector 走
      `hit_connector`，Stroke 走 `stroke_hit_record`；保持逆 z 顺序；
- [ ] 双击按 kind 分派 editor（Spec H3），废除一律 `_begin_sticky_edit`。

### Task 2.2 eventFilter 收缩（Spec H2）

- [ ] 四个 `_handle_*_board_event` 加 armed/draft 前置守卫；Select 下的对象选择统一走
      classify 结果；
- [ ] owner 用例（对照判据）：Connector 穿过卡片时，点线选线、点卡选卡，两断言同用例；
- [ ] Stroke 在 Select 下可单击选中并出现 INK 工具条。

### Owner 测试

- `tests/ui/test_ultraview_author_connector_slice.py` / `test_ultraview_author_draw_slice.py`
  （既有事务回归）
- 新增命中用例进 `tests/ui/test_ultraview_page.py` 或独立
  `test_ultraview_board_hit_routing.py`

### 出口

D5 闭合。**此门通过后**才允许讨论把 Connector / Draw 恢复进 release rail
（恢复本身连同 hints/help 扇出作为独立小波，套用 W0 的清单反向执行）。

## W3 — 格式选择器与 QSS 状态收敛

### 目标

闭合 D6 / D8。格式控件点开是选择器；panel/mode 状态不再与 active tool 抢视觉。

### Task 3.1 选择器复用（Spec §5）

- [ ] 色板 / 线宽 / 形状类型 / 线型点击弹出锚定 flyout（复用 Sticky 网格、Shape cell、
      Draw preset 行）；布尔控件维持 checkable；
- [ ] 删除各 `_next_*_format` 中被选择器取代的轮询分支；保留纯函数部分给选择器复用；
- [ ] 混选去掉批量 style 轮询，只留移动/复制/锁定/删除；
- [ ] 删除 `chrome.py` 的 `TextFormattingToolbar` 及其引用。

### Task 3.2 QSS 状态收敛（Spec §6）

- [ ] `panelOpen` / `modeActive` hover/pressed 改中性 wash + 边框加深；
- [ ] 清理无消费者的 `UV_RAIL_ACTIVE_START/END`；
- [ ] `tests/ui_kit/test_ultraview_style.py` 更新 token 断言；
      `tests/ui_kit/test_qss_border_shorthand.py` 白名单不放宽。

### Owner 测试

- `tests/ui/test_ultraview_selection_toolbar_contract.py`（选择器弹出与应用）
- `tests/ui/test_ultraview_author_shape_slice.py` / `test_ultraview_author_text_slice.py`
  （格式应用后对象字段回归）
- `tests/ui_kit/test_ultraview_style.py` + border 简写 lint

### 出口

D6/D8 闭合；点击「填充」出现色板而非静默换色。

## W4 — page.py 指针路由拆出

### 目标

闭合 D10。draft/geometry session 状态迁入 `BoardInteractionController`；Page 收敛为组合 +
薄路由；`page.py` ≤ 4700 行。

### Task 4.1 迁移

- [ ] `_text/_shape/_connector/_draw_geometry_session` 与 draft 更新逻辑迁入 controller
      （或其同文件协作对象），Page 保留信号发射与 overlay 调用；
- [ ] 迁移是搬家不是重写：每步用既有 slice 测试冻结行为，先绿后搬；
- [ ] 不新建第二个状态源（`test_main_window_state_ownership.py` 与 backref 护栏照常）。

### Owner 测试

- 全部 `tests/ui/test_ultraview_author_*_slice.py`（行为冻结）
- `tests/ui/test_ultraview_gesture_preview.py` / `test_ultraview_gesture_coalesce.py`
  （卡片手势不受牵连）

### 出口

行为零变化（slice 测试全绿）；`page.py` 行数达标并在 review 记录中留数。

## W5 — Cocoa 前台走查门

### 目标

把 W0–W4 的结果从 `CODE COMPLETE / FOREGROUND UNVERIFIED` 推进到
`ACCEPTED ON macOS / WINDOWS UNVERIFIED`。

### Task 5.1 前台证据

- [ ] 真实 TraceLab + `testdoc/1.tlproj`（只读副本，不保存原 fixture）；
- [ ] 五张状态图：Select / Sticky flyout / 选中卡片工具条 / 选中形状工具条 / 800×560 compact；
- [ ] 对照 2026-08-20 决策 prototype 逐面记录符合/偏差，存
      `docs/analyzer/verify/2026-08-20-ultraview-chrome-recovery/cocoa.md`；
- [ ] 顺手核记 08-19 恢复线遗留项（resize ghost、白底）当前真实状态，只记录不施工。

### 出口

五张图 + 走查记录入库；偏差项回填 Spec 缺陷表或明确移交后续 spec。
Windows frozen 明确标注 UNVERIFIED，由发布门另行收口。

## 附：波次状态跟踪

| 波 | 状态 |
|---|---|
| W0 | CODE COMPLETE / FOREGROUND UNVERIFIED |
| W1 | CODE COMPLETE / FOREGROUND UNVERIFIED |
| W2 | CODE COMPLETE / FOREGROUND UNVERIFIED |
| W3 | CODE COMPLETE / FOREGROUND UNVERIFIED |
| W4 | CODE COMPLETE / FOREGROUND UNVERIFIED（`page.py` 4558 行 ≤ 4700） |
| W5 | FOREGROUND UNVERIFIED |
