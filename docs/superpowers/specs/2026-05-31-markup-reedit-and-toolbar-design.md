# 标注编辑器：二次修改交互打磨 + 工具栏重做 设计

日期：2026-05-31
分支：`plan/pyqtgraph-timedomain-migration`
前置：`docs/superpowers/specs/2026-05-31-copy-annotation-editor-design.md`（原始设计）、
`docs/superpowers/plans/2026-05-31-copy-annotation-editor-implementation.md`（原始实施计划，含未兑现的 Task 3.5）
目标文件：`mf4_analyzer/ui/markup/editor.py`（唯一改动源）、`tests/ui/test_markup_editor.py`
工具栏方案预览：`docs/analyzer/ui-prototypes/2026-05-31-markup-toolbar-options.html`

## 背景与诉求

截图标注编辑器（`mf4_analyzer/ui/markup/editor.py`，1224 行）基本功能已落地：8 个工具、裁剪、撤销重做骨架、复制/保存出口。
但用户反馈**「针对标注内容的二次修改还差远了」**，并举例：

> 画了一条线，不切到「选择」工具就选不中它。这么 low 的设定怎么可以？应该不管在哪个工具下都能选中元素，选中后能做对应操作。

以及**「顶部 UI 和图标太 low，颜色选择和线宽占位置，要收进二级菜单」**。

本设计**不新增工具/能力**（不做马赛克/模糊/橡皮/取色/贴图/历史，沿用原 spec P2 范围外约定），只把**现有交互**打磨成顺手的「选中 → 二次修改」闭环，并重做工具栏布局。

## 现状核实（决定方案落点，全部对照 `editor.py` 行号）

### 选中相关

1. **「任意工具下点中元素即可拖动」其实已写，但只对矩形有效。** `mousePressEvent`（`:169-209`）在工具分支前先查
   `markup_item_at`（`:182-190`），命中走 `_begin_move`；测试 `test_existing_item_can_be_dragged_even_when_draw_tool_is_active`
   （`test_markup_editor.py:247-257`）锁了这条路。但 `markup_item_at`（`:815-822`）用 `scene.items(point)`，靠每个 item
   的 `shape()` 命中——矩形 `shape()` 是整块面积好点，**线只有 4px 宽的细缝、缩放后屏幕不足 1px，几乎点不中**。

2. **箭头 `shape()` 是 bug——零面积。** `_ArrowAnnotationItem.shape()`（`:95-101`）变量名叫 `stroker` 却从未真正
   stroke，返回的是一条数学零宽度线，`contains(point)` 几乎恒 False；箭头头部 polygon 也没并进 shape。**箭头在任何工具
   （含选择工具）下都基本点不中。**

3. **细元素唯一可靠选法是橡皮筋框选，而框选只在选择工具开。** `set_tool` 里 `RubberBandDrag` 仅当 `tool=="select"`
   （`:715-716`）。于是直接点细线大概率落空 → 画线工具里落空就**又画一条新线**，选择工具里落空就清空选区。这就是用户
   体感「不切到选择工具就选不中线」的真正机制。

4. **选中后没有手柄 = 不能改形状（除非选择工具）。** `refresh_handles`（`:884-892`）开头 `if self._tool != "select": return`
   （`:889-890`）。即便在画线工具里选中了元素、能拖动，也画不出手柄 → 移动可以、改尺寸/端点不行。

5. **画笔路径 / 序号组没有任何手柄，永远改不了形。** `_add_handles_for_item`（`:912-936`）只覆盖矩形/线/箭头/文字；
   `QGraphicsPathItem`（画笔）和 `QGraphicsItemGroup`（序号）没有手柄，也没有选中态视觉回显。

6. **切工具不清选区，导致「隐形选中」误伤。** `set_tool`（`:711-720`）不清选区。在选择工具选中矩形 → 切画线工具
   （手柄消失但矩形仍 `isSelected()`）→ 点个颜色想画新线 → `set_color`（`:699-703`）遍历 `selected_markup_items`
   把**看不见的选中矩形也改色了**。

7. **无 hover / resize 光标，选中态视觉弱。** `setMouseTracking(True)` 开了（`:166-167`），但 `mouseMoveEvent`
   非拖拽时直接 `super()`（`:239-241`），鼠标移到元素/手柄上光标不变 → 用户看不出哪儿可抓。选中反馈不统一：矩形/线/
   文字靠 Qt 默认淡虚线框、箭头靠自己 paint 的白方块（`:109-114`）。

8. **文字二次编辑也要切工具。** 重编辑已有文字只有在「文字」工具单击触发 `focus_text_item`（`:182-186, 468-476`）；
   选择工具下双击文字无效（`mouseDoubleClickEvent` 只处理裁剪 `:291-296`）。

### 撤销相关（最严重）

9. **几乎所有「改」类操作都绕过 undo 栈。** 全编辑器只有两个 `QUndoCommand`：`_AddItemCommand`、`_CropCommand`
   （`:46-78`）。其余全是直接改 item：

   | 操作 | 代码 | 进 undo 栈？ |
   |---|---|---|
   | 删除选中 | `delete_selected_annotations`（`:789-793`，直接 `removeItem`） | ❌ |
   | 拖动移动 | `_begin_move`/`setPos`（`:211-238`） | ❌ |
   | 方向键微调 | `move_selection_by`（`:784-787`） | ❌ |
   | 拉手柄改尺寸/端点 | `drag_handle` 系列（`:863-999`） | ❌ |
   | 改颜色/粗细 | `set_color`/`set_stroke_width`（`:699-709`） | ❌ |
   | 粘贴 | `paste_annotations`（`:800-813`） | ❌ |

   这点尤其讽刺：原 spec 第 53、131 行**明确决定「不放删除按钮，误操作靠撤销/重做兜」**——但删除恰恰不可撤销，
   整个「靠 undo 兜」的设计前提是空的。二次修改时手一抖，`Ctrl+Z` 不会还原刚才的改动，反而去撤销更早的「创建」。
   原实施计划 Task 3.5 Step 4 写了「Add undo commands for add/delete/move/style/crop」，**但代码并未落地**。

### 工具栏相关

10. **顶栏一行平铺 10 个常驻样式按钮。** `_build_toolbar`（`:564-677`）：6 个颜色 `QToolButton`（`:576-593`）+ 4 个线宽
    `QToolButton`（`:595-605`）+ 8 个工具 + 关闭/撤销/重做/保存/完成复制。颜色线宽吃掉约一半横向空间，且当前色/当前
    线宽无回显（看不出选了哪个）。这是用户说「占位、low」的来源。测试 `test_style_controls_are_compact_not_placeholder_buttons`
    （`test_markup_editor.py:219-231`）只约束样式按钮「紧凑、无文字」，**不约束其必须常驻**——收进二级菜单不破坏该测试语义
    （但需同步更新断言，见测试章）。

## 设计

### A — 统一「任意工具下可选中并二次修改」（对应现状 1-8）

**A1 加粗命中区（解决 1/2/3）。** 让直接点击在任意工具下都能抓住细元素：

- 修 `_ArrowAnnotationItem.shape()`：用 `QPainterPathStroker`（`setWidth(max(self._pen.widthF()+? , _HIT_TOLERANCE))`）
  把直线段 stroke 成有宽度的 path，并 `addPolygon(self._arrow_head())` 把箭头头部并进去。`_HIT_TOLERANCE` 取 12（场景单位）。
- `markup_item_at(point)`：从「点命中」改为「小邻域命中」。先按原 `scene.items(point)` 精确查；若无命中，再用以 `point`
  为中心、边长 `2*tol` 的 `QRectF` 调 `scene.items(rect, Qt.IntersectsItemShape, Qt.DescendingOrder)` 取最上一个非背景/
  非手柄/非裁剪 item。`tol` 随缩放归一为屏幕约 8px：`tol = 8.0 / max(self._zoom, 0.1)`。这样线/箭头无需逐类型改 shape 也能点中，
  且大元素行为不变（精确命中优先）。

**A2 任意工具都画手柄 + 选中即给反馈（解决 4/5）。** 重写 `refresh_handles`（`:884-892`）：
- 裁剪态保持原特例（crop 工具 + `_crop_item` → `_add_crop_handles`）。
- 去掉 `if self._tool != "select": return` 早退；改为：**只要有选中标注，就为其画手柄**（不分工具）。
- `_add_handles_for_item` 增补：画笔 `QGraphicsPathItem`、序号 `QGraphicsItemGroup` 各加 1 个右下角缩放手柄
  （role=`"scale"`，复用文字 scale 思路：`item.setScale(...)`）；让所有元素都至少有「选中可见 + 可缩放」。
- 选中态视觉统一：对**没有几何手柄**的情况无需额外处理（现已有手柄即反馈）；保留 Qt 默认选中虚线即可，不再单独造高亮。

**A3 拖手柄在任意工具生效。** `mousePressEvent` 已先于工具分支查 `handle_at`（`:176-180`），A2 让手柄在任意工具存在后，
  缩放/端点编辑自动在任意工具可用，无需再改 press 逻辑。

**A4 切工具的选区策略（解决 6）。** A2 让选中在任意工具都有可见手柄，「隐形选中」已消除（用户看得到选中）。再补一条
  顺手规则：**在非选择/非裁剪工具下，于空白处按下开始画新形状前，先 `clear_selection()`**（在 `mousePressEvent` 进入绘制分支
  `:206-209` 之前调用）——保证「开始画新的」语义干净，避免旧选中残留被样式键误改。

**A5 hover / resize 光标（解决 7）。** `mouseMoveEvent` 非拖拽分支（`:239-241`）改为根据光标下内容设视口光标：
  - 命中手柄 → 按 role 映射缩放光标：角 `tl/tr/bl/br`→`SizeFDiag/SizeBDiag`，边 `top/bottom`→`SizeVer`、`left/right`→`SizeHor`，
    端点 `p1/p2`/`scale`→`SizeAllCursor`。
  - 命中标注 item → `SizeAllCursor`（可移动）。
  - 空白：选择工具 → `ArrowCursor`；绘图工具 → `CrossCursor`。
  统一封装为 `_cursor_for(point)`，在 `mouseMoveEvent` 与拖拽结束后调用 `self.viewport().setCursor(...)`。

**A6 文字双击进编辑（解决 8）。** `mouseDoubleClickEvent`（`:291-296`）裁剪分支之外，增补：若 `markup_item_at(point)`
  是 `QGraphicsTextItem`，调 `focus_text_item(item)`。保留文字工具单击行为不变。

### B — 二次修改全部可撤销（对应现状 9，最高优先级）

引入「交互即时改、手势结束时落一条命令」的标准模式：拖动/缩放时照旧 live 改 item 给反馈，**鼠标释放或按键时把
（before→after）封成 `QUndoCommand` push**；命令 `redo()` 应用 after（幂等，因为已 live 改到位）、`undo()` 应用 before。

新增命令类（放在 `_CropCommand` 之后）：

- `_MoveCommand(moves)`：`moves = [(item, QPointF old, QPointF new), ...]`。`redo` setPos(new)、`undo` setPos(old)。
  用于：拖动移动（`mouseReleaseEvent` 的 move 分支 `:256-261` 处，用 `_move_positions` 记录的 old vs 释放时的 new）、
  方向键 `move_selection_by`（每次按键 push 一条；可选 `mergeWith` 合并连续同向移动，非必需）。
- `_GeometryCommand(item, before, after)`：`before/after` 由 `_geometry_snapshot(item)` 产出的不可变快照
  （rect→`("rect", QRectF, QPointF pos)`；line→`("line", QLineF, pos)`；arrow→`("arrow", start, end, pos)`；
  text/path/group→`("scale", float, pos)`）。`redo`/`undo` 经 `_restore_geometry(item, snap)` 还原。
  在 `mousePressEvent` 命中手柄时（`:176-180`）记 `self._resize_before = self._geometry_snapshot(handle._target)`；
  `mouseReleaseEvent` 手柄分支（`:251-255`）push `_GeometryCommand(target, before, after)`。
- `_DeleteCommand(scene, items)`：`redo` 对每个 `removeItem`、`undo` 对每个 `addItem`。改写
  `delete_selected_annotations`（`:789-793`）改为 push 本命令。
- `_StyleCommand(entries)`：`entries = [(item, (QColor,int) before, (QColor,int) after), ...]`，经
  `_apply_style_to(item, color, width)` 应用。`set_color`/`set_stroke_width`（`:699-709`）改为：先收集选中项当前样式，
  改全局样式后对选中项 push 一条 `_StyleCommand`（无选中则只改全局，不 push）。需把 `_apply_style`（`:750-766`）重构出
  显式参数版 `_apply_style_to(item, color, width)`，原 `_apply_style(item)` 转调它。
- 粘贴用宏：`paste_annotations`（`:800-813`）外层包 `self._undo_stack.beginMacro("粘贴标注") ... endMacro()`，内部
  `_deserialize_item` 仍走 `add_*` → `_AddItemCommand`，于是一次粘贴 = 一步撤销。

辅助方法：`_geometry_snapshot(item)`、`_restore_geometry(item, snap)`、`_apply_style_to(item, color, width)`。

> 一致性铁律：所有改变 scene 状态的交互（增/删/移/改形/改样式/粘贴/裁剪）都必须经 `_undo_stack`，
> 这样原 spec「不放删除按钮、误操作靠撤销兜」的前提才成立。

### C — 工具栏重做（对应现状 10）

把 6 色 + 4 线宽（10 个常驻 `QToolButton`）收进二级菜单。三个候选见
`docs/analyzer/ui-prototypes/2026-05-31-markup-toolbar-options.html`：

| 方案 | 顶栏样式入口 | 二级菜单 | 取舍 |
|---|---|---|---|
| **A（推荐）** | 1 个「样式 ▾」键，键面回显当前色 + 当前线宽 | 一个 popover 含颜色 swatch + 线宽 chip | 顶栏最省、状态一眼可见、改动量最小 |
| B | 颜色键 + 线宽键，各自回显 | 两个小 popover | 贴近 PPT 习惯，但占 2 键、改样式要点两次 |
| C | 无样式键，纯工具 + 动作 | 选中绘图工具/选中元素时下方滑出 contextual 样式条 | 顶栏最极简，但多一条会显隐的第二行、改动最大 |

**用户已确认方案 A**，按此落地。A 的实现：
- 新增 `_build_style_popover() -> QWidget`（或用 `QMenu` + `QWidgetAction` 承载一个含 swatch/chip 的小面板），由顶栏的
  `QToolButton#markupStyleButton`（`setPopupMode(QToolButton.InstantPopup)`）触发。
- 样式键键面用 `_style_button_icon(color, width)` 动态绘制：左一个当前色圆点 + 右一段当前线宽横线（改色/改粗细后重绘）。
- popover 内：6 个颜色 swatch（当前色高亮环）、4 个线宽 chip（当前档高亮），点选即调 `set_color`/`set_stroke_width` 并重绘键面。
- 图标统一描边风、分组加分隔（视觉层面在 QSS/构建顺序处理；「完成复制」保持蓝色主按钮 `:663-674` 不变）。

> 保留 `set_color(QColor)` / `set_stroke_width(int)` 公共方法签名不变（被测试 `test_style_controls_apply_to_new_and_selected_items`
> `:200-217` 依赖），只改「触发它们的 UI 控件」从常驻按钮变为 popover 内控件。

## 测试（离屏 `QT_QPA_PLATFORM=offscreen`，沿用 `tests/ui` 风格）

新增 / 改动 `tests/ui/test_markup_editor.py`：

- **任意工具选中细元素**：`add_line_item` 后 `set_tool("arrow")`，在线附近（非精确像素，偏移 ≤6px）点击 → 该 line `isSelected()`，
  且 markup 数量未增（没误画新元素）。箭头同理：`add_arrow_item` 后点箭头身/头附近能选中。
- **任意工具显示手柄**：选中 rect 后 `set_tool("pen")` → `editor._handles` 非空（不再依赖 select 工具）。
- **画笔/序号有缩放手柄**：`add_path_item`/`add_number_item` 选中后 `_handles` 含 role=`"scale"` 的手柄，drag 后 `item.scale()` 变化。
- **可撤销：删除**：选中后 `delete_selected_annotations` → 数量减 1；`_undo_stack.undo()` → 数量恢复、item 回到 scene。
- **可撤销：移动**：拖动/`move_selection_by` 改 pos 后 `undo()` → pos 还原。
- **可撤销：改尺寸**：经 `drag_handle` 改 rect 后 `undo()` → rect 还原（断言 `item.rect()` 等于改前）。
- **可撤销：改样式**：选中后 `set_color`/`set_stroke_width` → `undo()` 还原 pen 颜色/宽度。
- **可撤销：粘贴**：copy+paste 后数量 +1，`undo()` 一步退回（断言一次 undo 即恢复，验证宏生效）。
- **切工具清旧选**：选中 rect，`set_tool("rect")` 后于空白拖出新矩形 → 旧 rect `isSelected()` 为 False。
- **文字双击重编辑**：`add_text_item` 后非文字工具下双击该文字 → `hasFocus()` 且未新增文字 item。
- **工具栏样式入口**：存在 `markupStyleButton`（方案 A）；颜色/线宽控件不再是顶栏常驻 `QToolButton`，但仍能经 popover 调到
  `set_color`/`set_stroke_width`（更新 `test_style_controls_are_compact_not_placeholder_buttons` 的断言到新结构）。
- **回归**：`set_color`/`set_stroke_width` 对「新建 + 已选」仍生效（`:200-217` 保持绿）；裁剪/渲染尺寸/完成回调等既有用例不破。

## 范围外（沿用原 spec，不扩）

- 不新增工具或能力：马赛克/高斯模糊/橡皮/取色器/贴图 pin/截图历史/旋转/OCR/上传分享一律不做。
- 不动复制发布管道（`MainWindow._publish_copied_pixmap`）、缩略图、出口 2（FFT-vs-Time 检查器）、CursorPill 合成、裁剪坐标语义。
- 不动 `set_color`/`set_stroke_width`/`apply_crop_rect`/`render_result`/`finish_and_copy` 等公共契约签名。

## 验收标准（本仓库铁律：只认真机渲染/截图，不认「属性设上了 + 单测过」）

逐项真机验证（启动 app → 复制一张图 → 点缩略图开编辑器）：
- 画一条线/一个箭头，**不切工具**，直接在它附近点一下就能选中并出现手柄；拖端点能改形。
- 选中任意元素后：`Delete` 删除，`Ctrl+Z` 能还原；拖动后 `Ctrl+Z` 还原位置；拉手柄改尺寸后 `Ctrl+Z` 还原尺寸；改色/改粗细后
  `Ctrl+Z` 还原样式；粘贴后 `Ctrl+Z` 一步退回。
- 鼠标移到元素显示移动光标、移到手柄显示对应缩放光标、空白处绘图工具显示十字。
- 选择工具下双击已有文字可直接重新编辑。
- 顶栏不再平铺颜色/线宽，改为样式入口（方案 A：一个「样式」键，键面回显当前色 + 线宽；点开可改）；图标利落、分组清晰、
  「完成复制」蓝色主按钮醒目。
- 回归：原有画/选/删/裁剪/复制/保存/完成复制全部照常；颜色粗细对新建和已选元素仍生效。
