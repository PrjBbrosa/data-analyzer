# UltraView 窗口 / 交互与图片标注编辑器加固设计

> 状态：**设计稿，未实施。** 实施计划见
> `docs/analyzer/plans/2026-11-13-ultraview-window-and-markup-interaction-hardening-plan.md`。
> 问题、数字和证据等级全部出自
> `docs/analyzer/reviews/2026-11-13-ultraview-and-markup-interaction-review.md`（下称「报告」，
> 发现编号 W-* / U-* / M-*）。
>
> 编写基线：`0614559a`（v8.4.7）。报告没有任何 Windows 真机或 Cocoa 证据；本文里的耗时
> 目标都是 offscreen CPU 代理下的初始工程目标，验收以 plan 的真机测量为准。
>
> 起因是用户反馈：Windows 下 UltraView 打开成一个 mini 缩略窗口；UltraView 和「图片标注」
> 很多操作不跟手，希望对标 Snipaste。

## 0. 一句话

**窗口不能小到不可用，按下去的操作要落在用户指的那个东西上，拖动时东西要跟着手走。**
本设计做三件事：给工具窗口的尺寸加三道下限和一次显示后校验，让 mini 窗口无论由什么触发
都不会出现；修掉 UltraView 里失焦清理、滚轮、手柄、自由对象选择这几处逻辑缺陷，并把
拖动反馈改成「本体连续跟手 + 落点按栅格吸附」；把标注编辑器的按下分派、Esc、平移、
预览改成确定的规则，再按 Snipaste 的差距补工具。

## 1. 问题（摘要）

| 编号 | 现象 | 根因（一句话） | 报告位置 |
|---|---|---|---|
| P-1 | UltraView 打开成 160×160 的 mini 窗口 | 规划器与窗口都没有下限，一次退化规划就落到 Qt 的默认初始尺寸；Windows 触发条件未知 | W-1、W-2 |
| P-2 | 工具窗口还原、再次打开、销毁时行为不稳 | nudge 对每次显示都执行；最小化后再打开不还原；不经 close 销毁会带走 Board page | W-3、W-4、W-5、W-6 |
| P-3 | 按住 Space 切走窗口后，左键拖动一直是平移 | 失焦清理写在收不到事件的 `changeEvent` 里 | U-1、U-2、U-15 |
| P-4 | Shift+滚轮整页跳 | 路由器只接管 Ctrl / Meta+滚轮 | U-3 |
| P-5 | 缩放手柄光标不更新、手柄点不中 | 悬停只在卡片 1 px 边框上解析；可见手柄一半在命中带外 | U-4、U-5 |
| P-6 | 卡片、自由对象拖动不跟手 | 本体不动，反馈按栅格量化 | U-6、U-8 |
| P-7 | 自由对象不能框选、不能成组拖、笔迹和连线拖不动 | 选择手势只为卡片和单个盒状对象实现 | U-7、U-9、U-14 |
| P-8 | 缩放、平移、画笔在内容多时变慢 | 每个事件做全量工作；画布范围只在停手后扩展；笔迹每帧全量重投影 | U-10、U-11、U-12 |
| P-9 | 丢失 release 后手势残留 | 移动处理不检查按键状态 | U-13 |
| P-10 | 标注：想画却拖走了别的标注 | 按下先做命中再分派工具；空心形状内部算命中 | M-1 |
| P-11 | 标注：Esc 丢失全部工作 | Esc 直接 `close()`，没有脏状态确认 | M-2 |
| P-12 | 标注：不能平移，缩放锚点漂 | 没有平移手势 | M-3 |
| P-13 | 标注：选择、提示、手柄、预览、按钮状态的一批不一致 | 见报告 | M-4 … M-10 |
| P-14 | 标注：窗口固定尺寸、关闭不销毁、可重复打开 | 没走共享几何，没有生命周期 owner | M-11、M-12 |
| P-15 | 标注：对标 Snipaste 的工具和键盘差距 | 未实现 | 报告 §5 |

## 2. 目标与非目标

### 2.1 目标

1. **工具窗口不可能以不可用尺寸出现。** 任何规划输入下，UltraView / Batch / 标注窗口显示
   后的客户区都不小于各自的可用下限；发生过回退或自愈时有日志说明原因。
2. **失焦即清理。** UltraView 窗口失去激活后，没有残留的 Space、平移、拖动、框选状态。
3. **按下即所指。** 光标形状与按下后实际发生的操作一致；可见手柄的每个像素都能点中。
4. **拖动连续跟手。** 卡片和自由对象在拖动中有一个逐像素跟随指针的本体或幽灵；栅格吸附
   只体现在落点提示和松手结果上。
5. **选择模型一致。** 卡片与自由对象都能框选；多选后可以成组移动；所有自由对象类型都
   可以移动或给出不能移动的可见原因。
6. **每个输入事件的工作量有界。** 缩放、平移、画笔在 24 张卡 / 200 条笔迹下不随内容量
   线性变慢。
7. **标注编辑器的操作是确定的。** 绘制类工具按下必然开始新标注；Esc 不会无确认丢失工作；
   可以平移；预览就是成品的样子。
8. **键盘提示只有一个来源。** 工具提示里的快捷键与实际处理的按键来自同一张表。

### 2.2 初始工程目标（待 plan Task 0 校准，不是承诺）

| 指标 | 现状（报告，代理读数） | 初始目标 |
|---|---|---|
| 工具窗口显示后客户区 | 可为 160×160 | ≥ `min(内容最小尺寸, 可信工作区预算)`，且任一维 ≥ 200 |
| Ctrl+滚轮单事件处理，24 卡，缩放 0.8 / 2.5 | 11.2 / 29.9 ms | ≤ 6 / ≤ 12 ms |
| 缩放停手结算的单次阻塞，24 卡 | 34 ms | ≤ 16 ms |
| 24 张大预览连续缩放的最差单帧 | 199 ms | ≤ 33 ms |
| 画笔工具单次绘制，200 条 ×280 点 | 约 120 ms | ≤ 8 ms（已提交笔迹走缓存） |
| 卡片幽灵与指针的距离（阈值之后） | 最大 25 px、平均 12.5 px | ≤ 1 px |
| 连续平移撞墙 | 约 1010 px 处停住 | 不撞墙 |
| 笔迹 / 连线拾取容差随缩放变化 | 4 → 29 px / 8 → 52 px | 各缩放下相同（±1 px） |
| 标注缩放锚点漂移（未被滚动范围钳制时） | 4 格约 9 px | 每格 ≤ 1 px |

代理读数只用来判断方向；Windows 真机的预算在 Task 0 测完后写回本表，校准要记录硬件和
原因，不能在不达标后放宽。

### 2.3 非目标

- 不重新设计 UltraView 的栅格模型、智能布局、多 Board、View 库和导出。
- 不改变卡片移动 / 缩放的提交语义（仍吸附整格、仍走现有 planner 与冲突规则）。
- 不做卡片与自由对象混合选择的成组移动（本轮只做各自成组）。
- 不把 `content_minimum` 改回可以突破工作区预算的硬 floor。小屏幕上窗口仍然先服从
  工作区（2026-09-05 spec 的 C04 不变）。
- 标注编辑器不做文字旋转、橡皮擦（对象模型下选中后删除即可）、跨会话的颜色记忆。
- 不改 `CLAUDE.md` / `AGENTS.md` 的护栏语义，不改版本号。

## 3. 设计

### 3.1 D-W1 · 工具窗口尺寸的三道下限与显示后校验（解决 P-1）

**Owner：** `ui_kit/dialog_geometry.py`（规划与应用）、`ui/drawers/batch/_geometry.py`
（工具窗口入口）、`ui/drawers/ultraview/sheet.py` 与 `BatchSheet`（窗口自身）。

**为什么是三道：** 触发条件未知，所以不能只堵一个入口。每一道独立成立，任一道生效都
不会出现 mini 窗口。

1. **规划输入：不可信的工作区不参与规划。** `resolve_available_rect` 拿到的
   `availableGeometry()` 若宽 < 320 或高 < 240（逻辑像素），视为不可信，依次回退到
   该屏幕的 `geometry()`、主屏的 `availableGeometry()`、现有的 1920×1080 常量，并记
   一条 warning（含屏幕名、几何、DPR）。阈值取在 2026-09-05 spec 承诺的最小验收工作区
   （800×600、960×540）之下，不影响任何真实小屏。
   纯函数 `client_budget` / `constrain_client_size` / `plan_geometry` **不变**，现有合同
   测试（预算不为负、内容最小尺寸不突破预算）原样保留。
2. **应用步骤：拒绝退化规划。** `apply_plan` 对「带标题栏的顶层窗口」，若规划客户区
   任一维 < 200，就不调用 `resize`，保持当前尺寸，返回 `False` 并记 warning（含规划的
   全部输入）。`_shrink_unaccounted_frame` 的收缩目标同样不低于这个值。无边框窗口、
   popover、内嵌浮层不受影响（它们合法地可以很小）。
3. **窗口自身：设置最小尺寸。** `fit_dialog_to_available_screen` 在规划成功后调用
   `setMinimumSize(min(min_w, client.w), min(min_h, client.h))`；规划被第 2 步拒绝时，
   直接 `resize(min_w, min_h)` 并设同样的最小尺寸。这样 Qt 在原生创建时即使遇到 0 尺寸，
   也会用 `minimumSize` 而不是默认的 160（报告 §2.1 已在 Wine 下验证该行为），用户也
   不能把窗口拖到比内容最小尺寸更小。
4. **显示后校验一次。** 工具窗口首次显示后的下一轮事件循环，比较实际客户区与最小尺寸；
   不满足时重新 `fit` 一次并记 `tool-window-geometry-recovered`（含环境事实）。每次
   显示最多重试一次，不循环。

**合同：** 新常量只有两个（不可信工作区阈值 320×240、退化客户区阈值 200），放在
`dialog_geometry.py`，不是可调旋钮。`BatchSheet` 与 UltraView 走同一个入口，同时获得
这四条。

### 3.2 D-W2 · 显示、还原与销毁（解决 P-2）

**Owner：** `sheet.py`、`batch/_geometry.py`、`dialog_geometry.py::frame_insets_of`、
`ui/main_window/window.py` 的工具窗口句柄管理。

1. **nudge 只在该做的时候做。** `showEvent` 里只对非 spontaneous 的显示执行
   `nudge_into_work_area`，且窗口处于最大化 / 最小化 / 全屏时跳过。屏幕变化由
   `windowHandle().screenChanged` 触发一次「只纠正越界」的 nudge。
2. **再次打开要还原。** `present_independent_tool_window` 在 show / raise / activate 之前
   清掉 `Qt.WindowMinimized`，保留最大化状态。
3. **窗框估算按平台。** 隐藏窗口的窗框估算值按平台取值；Windows 的数值由 Task 0 在真机
   上测出后写入（现有 (1, 28, 1, 1) 明显小于 Windows 实际）。能读到
   `windowHandle().frameMargins()` 时优先用实测值（现有逻辑保留）。
4. **page 在任何销毁路径上都归还。** `UltraViewSheet` 提供幂等的 `release_page()`，
   `closeEvent`、`done` 和 `event()` 里的 `QEvent.DeferredDelete` 都调用它；
   `_alive_tool_dialog` 在 `deleteLater` 之前先调用。`_restore_page` 归还失败（stack 已
   销毁）时记 warning，不再静默返回。

**合同：** page 的归属在任何时刻只有一个（stack 或某个存活的 sheet）；不新增
`MainWindow` 多文件写入属性。

### 3.3 D-W3 · 可追溯的几何诊断（服务 P-1 的真机定位）

**Owner：** `ui_kit/layout_diagnostics.py`（复用现有 `TRACELAB_LAYOUT_DIAGNOSTICS=1` 与
`mf4_analyzer.diagnostics` logger）。

工具窗口每次规划输出一条结构化记录：全部屏幕的 `geometry` / `availableGeometry` / DPR、
目标屏幕的选择依据、窗框（估算或实测）、预算、规划的 client / frame，以及构造结束、
`showEvent` 进入与返回、首次显示后四个时刻的实际尺寸。开关关闭时只输出 D-W1 的
warning。记录不含用户文档内容，冻结包里同样可用。

### 3.4 D-U1 · 失焦清理走真实事件路径（解决 P-3）

**Owner：** `ui/chart_stack/ultraview/page.py`、`viewport_router.py`、`viewport_controller.py`。

1. 清理集中到一个函数，由 `event()` 里已有的 `WindowDeactivate` 分支调用：提交或取消
   文字编辑、取消各类草稿（现有）、`_cancel_board_gestures()`、隐藏视口提示、
   `note_space(False)`、恢复光标。
2. 路由器在 page 可见期间保持安装，但「是否生效」的判定加上「所在窗口是激活窗口」。
3. 删除 `changeEvent` 里的 `WindowActivate` / `WindowDeactivate` 分支，并修正
   `_on_app_focus_changed` 的注释。
4. 报告 U-15 的另外 3 处同类写法一并改到 `event()`。

**合同：** 以 `QApplication.sendEvent(widget, QEvent(QEvent.WindowDeactivate))` 驱动的测试
看守；`tests/ui/test_ultraview_page.py` 里直接调 `changeEvent` 的假阳性用例改成同样的
投递方式。新增一条源码扫描护栏：`mf4_analyzer/` 内任何 `changeEvent` 函数体不得比较
`QEvent.WindowActivate` / `QEvent.WindowDeactivate`。

### 3.5 D-U2 · 滚轮语义（解决 P-4）

**Owner：** `viewport_router.py`（接管）、`viewport_controller.py`（执行）。

| 输入 | 行为 |
|---|---|
| 滚轮 | 纵向滚动（现状保留） |
| Shift+滚轮 | 横向滚动，步长与纵向相同 |
| Ctrl / Meta+滚轮 | 以指针为锚缩放（现状保留） |
| 触控板像素增量（无 Ctrl） | 按像素双向滚动 |

Shift+滚轮由路由器接管，不再落到滚动条的翻页行为。

### 3.6 D-U3 · 手柄与悬停光标（解决 P-5）

**Owner：** `free_grid.py`（命中几何）、`free_grid_board.py`（悬停解析与光标）、
`ghost_overlay.py`（手柄绘制）。

1. **悬停在 Board 一处解析。** 无按键的指针移动无论落在卡片的哪个子控件上，都交给
   Board 用 Board 坐标解析悬停目标并设置光标；指针离开时复位。复用现有
   `BoardViewportRouter`，不新增第二个应用级事件过滤器。
2. **光标是纯函数。** 光标 =（悬停目标，当前工具，是否有手势锁定）的函数，只在一处设置。
3. **命中带以边缘为中心。** 选中卡片的命中带在边缘内外各 6 px，角点 14×14 px；可见的
   6×6 手柄以边缘为中心绘制，整个落在命中带内。卡片边长小于 48 px 时内侧带宽收缩到
   边长的 1/4（不小于 4 px），外侧保持 6 px。
4. 选中卡片外侧 6 px 内的按下优先解释为缩放，不开始框选。

### 3.7 D-U4 · 卡片拖动的两层反馈（解决 P-6 的卡片部分）

**Owner：** `free_grid_feedback.py`、`gesture.py`、`ghost_overlay.py`。

- **跟手层：** 卡片快照幽灵逐像素跟随指针，保持按下点在卡片内的相对位置。越过拖动阈值
  时幽灵从「按下位置 + 已移动量」开始，阈值内的位移不丢。
- **落点层：** 目标格的轮廓按栅格吸附并着色（合法蓝 / 非法红），被挤开卡片的预览不变。
- 提交语义、planner 调用条件、overlay 脏区规则沿用
  `2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`；幽灵只多了位置更新，
  不重新生成图像。

这把实现拉回 `2026-08-14-ultraview-p3-canvas-interaction-spec.md` 的「ghost 跟手 + 目标格
实时高亮」，并保留 2026-08-22 计划要求的「越过阈值第一帧同步出现落点反馈」。

### 3.8 D-U5 · 自由对象的选择与移动（解决 P-6 的自由对象部分与 P-7）

**Owner：** `free_grid_author_controller.py`、`author_tools.py`（选择集）、`gesture.py`
（框选）、`author_layer.py`（预览绘制）、`ui/main_window/ultraview_coordinator.py`
（成批提交）。

1. **框选包含自由对象。** 框选矩形按与卡片相同的相交规则选中自由对象；Shift 为追加。
2. **成组移动。** 按在已选中的对象上（无 Shift）保持当前多选并移动整组；按在未选中的
   对象上先单选再移动。几何会话持有对象 id 列表与各自的初始几何。一次成组移动提交为
   一个撤销步。
3. **所有类型可移动。** 笔迹主体拖动 = 平移全部点；两端都未吸附的连线主体拖动 = 整体
   平移；有吸附端点的连线拖主体时不移动，并通过现有的作者反馈通道给出原因。
4. **本体跟手。** 拖动中对象本体按连续的预览几何绘制（绘制层接收一份临时的
   `对象 id → 预览几何` 覆盖），不量化；吸附只在松手提交时发生，拖动中同时显示吸附后
   的落点轮廓。
5. **拾取容差用屏幕像素。** 笔迹为 `max(6, 屏幕线宽 / 2 + 4)` px，连线为 8 px，与缩放
   无关。
6. **小文字框的手柄。** 盒子小于两倍手柄命中带时，角点手柄画在盒子外侧。

**合同：** 身份一律用对象 id；选择集只由 `author_tools.py` 的交互状态持有；不新增第二份
选择状态。卡片 + 自由对象的混合成组移动不在本轮（§2.3）。

### 3.9 D-U6 · 每个输入事件的工作量有界（解决 P-8）

**Owner：** `viewport_controller.py`、`page.py`（LOD 外观）、`free_grid_board.py`
（度量同步）、`author_layer.py` / `author_render.py`（笔迹绘制）。

1. **缩放事件只做几何。** 一个滚轮事件内 `_sync_metrics` 最多一次；`persist()` 与
   `camera_settled` 只在停手结算时各一次。实施前先盘点 `camera_settled` 的消费者
   （当前是 `ultraview_coordinator.py:754` → 截图协调器），需要逐事件相机状态的消费者
   改接轻量通知。
2. **LOD 外观按档位变化更新。** `_apply_lod_chrome` 只在 LOD 档位变化时执行，或只处理
   新进入视口的卡片。
3. **预览图延后重采样。** 手势期间用已有位图做快速缩放绘制；停手后只对可见卡片重新
   采样，超过单帧预算时分帧完成。
4. **平移时扩展画布。** 视口距离画布边界不足一个视口时即时扩展范围（按距离节流），
   保持原点稳定；沿用现有的 scroll / extent / origin 事务。
5. **笔迹绘制缓存。** 已提交笔迹绘制到一层缓存，键为（自由对象 revision、缩放、原点、
   视口尺寸）；在画的笔迹只增量绘制新线段的脏区。缩放手势期间复用缩放后的缓存，停手
   重建。

**合同：** 不降低停手后的画质；不引入固定延时。真机验证沿用并扩展
`scripts/probe_ultraview_zoom_spike.py`。

### 3.10 D-U7 · 手势对丢失 release 的健壮性（解决 P-9）

**Owner：** `gesture.py`、`viewport_controller.py`、`card_widgets.py`、`pointer_router.py`。

每个手势的移动处理先检查 `event.buttons()`：发起手势的按键已不在按下状态时，取消手势
（不提交）。`QEvent.UngrabMouse` 与窗口失焦同样取消。左键手势进行中按下右键 = 取消当前
手势。报告 U-13 只有合成事件证据，实施前先用真输入复现一次。

### 3.11 D-M1 · 标注：按下分派规则（解决 P-10 与 M-4、M-6）

**Owner：** `ui/markup/view.py`（分派）、`ui/markup/editor.py`（命中）。

| 当前工具 | 按在当前活动项的手柄上 | 按在标注的可见笔画上 | 按在空心形状内部 | 按在空白处 |
|---|---|---|---|---|
| 选择 | 调整大小 | 选中并移动 | 该形状已选中则移动，否则当作空白 | 开始框选（Shift 追加） |
| 箭头 / 直线 / 矩形 / 画笔 / 序号 | 调整大小 | 开始画新的 | 开始画新的 | 开始画新的 |
| 文字 | 调整大小 | 按在文字上 = 编辑它；其余 = 新建文字 | 新建文字 | 新建文字 |
| 裁剪 | 调整裁剪框 | 开始新的裁剪框 | 开始新的裁剪框 | 开始新的裁剪框 |

- **活动项：** 绘制类工具刚画完的那一项自动成为活动项（选中并显示手柄），工具不切换。
  下一次按下只要不在它的手柄上，就开始画新的。右键单击或 Esc 结束活动项。
- 空心形状（矩形、后续的椭圆）的命中只算笔画加容差，不算内部。

### 3.12 D-M2 · 标注：Esc、关闭与完成（解决 P-11）

**Owner：** `ui/markup/editor.py`。

- **Esc 逐级退出：** 正在画的草稿 → 取消草稿；文字编辑中 → 退出编辑；有裁剪框 → 取消
  裁剪；有选择或活动项 → 清除；以上都没有 → 请求关闭。
- **请求关闭**（Esc 的最后一级、标题栏关闭、工具栏关闭按钮）：撤销栈不是干净状态时
  弹确认，三个动作「完成复制」「放弃」「取消」；干净时直接关闭。「完成复制」和「保存」
  成功后把撤销栈标记为干净。
- **键盘：** Ctrl+Enter = 完成复制；Ctrl+S = 保存。单独的 Enter 仍只确认裁剪（现有代码
  注释说明这是为了避免误触，保留）。

### 3.13 D-M3 · 标注：缩放与平移（解决 P-12）

**Owner：** `ui/markup/view.py`。

| 输入 | 行为 |
|---|---|
| 滚轮、Ctrl+滚轮 | 以指针为锚缩放（现状保留） |
| 中键拖动、Space+左键拖动 | 平移，指针与内容 1:1 |
| 触控板像素增量（无 Ctrl） | 平移 |
| Shift+滚轮 | 横向平移 |

缩放锚点：未被滚动范围钳制时，同一场景点缩放前后的屏幕位置偏差每格 ≤ 1 px。报告里
测到的漂移是从「适应窗口」状态起滚的，可能有一部分来自没有滚动余量时的钳制，实施时
先区分这两种情况。

### 3.14 D-M4 · 标注：提示、手柄、预览、按钮状态与样式（解决 P-13）

**Owner：** `ui/markup/toolbar.py`、`editor.py`、`view.py`、`handles.py`、`ui_kit/style.qss`。

1. **快捷键单一来源。** 一张 `(工具 id, 按键, 标签)` 表同时供工具提示和 `keyPressEvent`
   使用。
2. **手柄屏幕尺寸恒定。** 手柄在任何缩放下都是 9×9 屏幕像素；命中容差不变。
3. **预览即成品。** 预览用与成品相同的图元类型和样式（实线、箭头头部、同线宽同颜色）；
   虚线只用于裁剪框和框选框。画笔预览按新增线段增量更新。
4. **选中与悬停可区分。** 选中 = 实心强调色底，悬停 = 浅色底。遵守 QSS border 简写护栏。
5. **线宽与颜色。** 线宽限制在 1–24；调色板末尾加「更多颜色…」，打开带透明度的颜色
   选择器，本次会话内记住最近用过的颜色。

### 3.15 D-M5 · 标注：窗口与生命周期（解决 P-14）

**Owner：** `ui/markup/editor.py`、`ui/main_window/window.py`（`_open_markup_editor`）。

1. **窗口尺寸走共享规划器。** 偏好客户区 = 图片 100% 尺寸 + 工具栏等固定部分，按工作区
   预算收缩，内容最小尺寸 720×480；同样获得 D-W1 的下限。
2. **初始缩放不放大。** 初始缩放 = `min(1.0, 适应窗口的缩放)`。
3. **关闭即销毁。** 设置 `WA_DeleteOnClose`；`MainWindow` 持有的句柄在 `destroyed` 时
   清空，复用前检查 `sip.isdeleted()`。
4. **同时只有一个编辑器。** 已有编辑器打开时再次进入：先走 D-M2 的请求关闭流程（有未
   完成的标注要确认），再打开新的。

**合同：** `_markup_editor` 仍只在一个文件里被赋值，状态所有权棘轮的白名单不扩大。

### 3.16 D-M6 · 标注：对标 Snipaste 的工具补齐（解决 P-15，第二阶段）

**Owner：** `ui/markup/`（`items.py`、`commands.py`、`serialization.py`、`thumbnail.py`、
`toolbar.py`）。在 D-M1 … D-M5 落地并验收之后再做。

| 工具 | 说明 |
|---|---|
| 椭圆 | 与矩形同构；Shift 画正圆 |
| 马克笔 | 半透明粗线，线宽独立于画笔 |
| 马赛克 / 模糊 | 矩形区域；导出时作用于底图对应区域，编辑中实时预览 |

每个新工具都要同时具备撤销命令、序列化、缩略图绘制和快捷键表条目。Shift 约束
（`view.py:261` 已有分支）先按 Snipaste 文档逐项核对，再决定是否补齐。落地前在真实
Snipaste 上核对手感，文档描述不能当作验收依据。

## 4. 机械护栏（新增 / 更新）

| 护栏 | 位置 | 内容 |
|---|---|---|
| 不可信工作区回退 | `tests/ui_kit/test_dialog_geometry.py` | 给定 0×0、10×10、319×239 的可用矩形，规划改用回退矩形并留日志；320×240 及以上不触发 |
| 退化规划不应用 | 同上 | 带标题栏的顶层窗口不会被 `apply_plan` 缩到任一维 < 200；popover / 内嵌浮层不受限 |
| 既有合同不动 | 同上 | `test_client_budget_never_negative_on_empty_or_tiny_work_area`、`test_constrain_does_not_use_max_of_floor_and_cap` 不改 |
| 工具窗口最小尺寸 | `tests/ui/test_tool_window_screen_fit.py` | UltraView / Batch 显示后 `minimumSize` 非零；强制退化输入下客户区仍 ≥ 下限；spontaneous 显示不触发 nudge；最小化后再打开会还原 |
| page 归还 | `tests/ui/test_ultraview_mode_integration.py` | sheet 经 close、done、`deleteLater` 三条路径销毁后，page 都存活且回到 stack |
| 失焦事件路径 | `tests/ui/test_ultraview_page.py` 等 | 用 `sendEvent` 投递 `WindowDeactivate`；源码扫描禁止在 `changeEvent` 里比较 `WindowActivate` / `WindowDeactivate` |
| 快捷键单一来源 | `tests/ui/test_markup_toolbar_wiring.py` | 每个工具的提示按键 == 实际切换到该工具的按键 |
| 按下分派 | `tests/ui/test_markup_editor.py` | §3.11 的表逐格断言，用视口坐标的真实鼠标事件驱动 |
| Esc 不丢工作 | 同上 | 脏状态下 Esc 到最后一级必须出现确认；选「取消」后标注仍在 |

所有既有护栏（状态所有权棘轮、`.connect(lambda` 棘轮、UI 三层分层、QSS border 简写、
画布 backref 不变量）保持，不扩大白名单。

## 5. 需要用户确认的产品决策

以下各项本文给了默认方案；用户有不同意见时先改本节再实施。

| 编号 | 决策 | 默认方案 | 备选 |
|---|---|---|---|
| Q-1 | 标注编辑器里滚轮的含义 | 保持缩放，线宽用 `[` / `]` | 按 Snipaste：滚轮调线宽，Ctrl+滚轮缩放 |
| Q-2 | 标注「完成复制」的键盘入口 | Ctrl+Enter | 按 Snipaste：单独 Enter |
| Q-3 | 卡片拖动的跟手层 | 幽灵逐像素跟手，落点轮廓吸附 | 保持现状（只有吸附后的幽灵） |
| Q-4 | 自由对象松手是否吸附 | 保持 0.25 单位吸附，拖动中连续 | 取消吸附，完全自由定位 |
| Q-5 | 有吸附端点的连线拖主体 | 不移动并提示 | 拖动时解除吸附 |
| Q-6 | 第二阶段新工具的范围 | 椭圆、马克笔、马赛克 / 模糊 | 只做椭圆与马克笔 |

## 6. 验收

| 门 | 内容 | 证据等级 |
|---|---|---|
| G1 | 各 Task 的 owner 用例与边界护栏 | offscreen |
| G2 | 真输入交互探针：U-1、U-3、U-4、U-6、U-7、U-8、M-1 … M-6 的复现步骤在改后全部不再复现 | X11 真输入或 Cocoa |
| G3 | Windows 源码运行：UltraView / Batch / 标注窗口在 100% 与 125% 缩放、单屏与双屏（不同缩放）、父窗口正常 / 最大化、打开 → 最小化 → 再打开、休眠唤醒后打开，各 20 次，窗口尺寸都不小于下限；诊断日志无 `recovered` 以外的异常 | Windows 真机 |
| G4 | Windows 上 24 卡缩放、平移、卡片拖动、画笔的帧时间达到 §2.2 校准后的预算 | Windows 真机 |
| G5 | 新鲜 Windows Full / Lite 冻结包重复 G3 的打开矩阵 | Windows frozen |
| G6 | 用户确认 mini 窗口不再出现，并提供一次 Task 0 的诊断日志 | 用户环境 |

G1 不能替代 G2 … G6；G3 / G4 未做时如实记为 `UNVERIFIED`。交互改动要同步
`ui/hints.py` 与 `ui/quickref.py`。

## 7. 风险与回退

| 风险 | 缓解 |
|---|---|
| mini 窗口的 Windows 触发条件始终找不到 | D-W1 的四条都不依赖触发条件；D-W3 的日志在用户机器上常开一段时间即可定位 |
| 不可信工作区阈值误伤真实的极小屏幕 | 阈值低于已承诺的最小验收工作区；回退只换输入矩形，不改变「窗框不出工作区」的规则 |
| `setMinimumSize` 与 `_release_size_conflicts` 互相覆盖 | 最小尺寸在规划应用之后设置，值不超过规划客户区；用例覆盖二次 fit |
| 幽灵逐像素跟手增加绘制成本 | 只移动已缓存的位图；沿用现有脏区规则；真机帧时间进 G4 |
| 自由对象预览覆盖与提交结果不一致 | 预览与提交共用同一个几何计算函数，测试断言松手后的几何等于吸附函数对最后预览的结果 |
| 标注按下规则改变老用户习惯（在标注上直接拖动） | 选择工具下行为不变；绘制工具下刚画完的活动项仍可直接调整 |
| 缩放事件精简后漏掉某个依赖 `camera_settled` 的消费者 | 实施前盘点消费者并逐个定迁移方式 |

每个 D-* 独立提交、独立可回退；D-W1 可以先于其余全部单独发布。

## 8. 与既有文档的关系

- `2026-09-05-cross-platform-dialog-layout-spec.md`：C04（先内容最小尺寸，再按工作区约束，
  窗框不出工作区）保持。本文在它之上补充「不可信工作区」和「退化规划」两条规则，并把
  该 spec 至今 `UNVERIFIED` 的 G4 / G5 里与工具窗口相关的部分纳入本文的 G3 / G5。
- `2026-08-14-ultraview-p3-canvas-interaction-spec.md`：D-U4 恢复其「ghost 跟手」。
- `2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md` 与
  `2026-08-22-ultraview-move-resize-feedback-pipeline-recovery-plan.md`：帧合并、脏区、
  「一个清晰幽灵 + 稳定轮廓」、阈值后第一帧同步出现落点反馈的规则保持。
- `2026-08-16-view-markup-and-cursor-persistence-spec.md`、
  `2026-08-04-chartstack-markup-slimming-design.md`：标注的持久化与模块划分不变；D-M6 的
  新工具必须接入现有序列化。
- 历史文档不回改。
