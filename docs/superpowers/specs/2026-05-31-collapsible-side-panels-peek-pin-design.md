# 可折叠侧栏 · 浮条召回 (peek/pin) · 工具栏简化 — 设计 spec

- 日期: 2026-05-31
- 分支: `plan/pyqtgraph-timedomain-migration`
- 状态: 待 review

## 1. 目标与动机

当前主窗口是横向三栏 `QSplitter`：navigator(左) | chart_stack(中) | inspector(右)，
见 `mf4_analyzer/ui/main_window.py:133-163`。左栏被钉死——`setMinimumWidth(220)`、
`setStretchFactor(0,0)`、`setCollapsible(0,False)`——既不能拖塌也不让出宽度，
长期吃掉 canvas 宽度。inspector 虽可隐藏，但隐藏后**只能靠工具栏按钮找回**
(`set_inspector_visible` 把槽收到 0，`main_window.py:221-229`)，边缘没有任何召回线索。

用户的真实工作流：**通道需要频繁添加/勾选，顶部文件列表很少碰**。所以诉求是
"想隐藏侧栏拿回 canvas，但不能因此牺牲高频的通道操作"。

本设计引入 IDE 通用的 **peek(悬停预览) / pin(单击钉住)** 双态模型，让两侧侧栏
(navigator + inspector) 都可折叠，折叠后留一条淡"浮条"作为就地召回入口；同时
**删除工具栏的面板开关按钮**(浮条取而代之)，并把 **Cockpit 按钮移到右段**腾出的位置。

## 2. 范围

### In scope
- navigator(左) 与 inspector(右) 均可折叠，三态：HIDDEN / PEEK / PINNED。
- 折叠侧出现一条 ~12px 的淡"浮条"(hint strip)，仅在该侧折叠时可见、展开时零占位。
- PEEK：hover 浮条 → 面板以**子控件浮层**滑出覆盖在 canvas 上(不挤压 canvas)，
  鼠标移出后延时自动收回，延时窗口内移回则取消收回。
- PIN：单击浮条 → 面板**停靠**回 splitter、像现在一样挤压 canvas，停住直到手动拖塌。
- HIDE：拖动 splitter 把手到边即折叠(无独立按钮)。
- 删除工具栏 `btn_inspector` 及其信号链；不新增 navigator 按钮。
- 把 `btn_acquisition_cockpit` 从工具栏左段移到右段(原 inspector 按钮槽位)。

### Out of scope (v1)
- 折叠状态跨会话持久化(不碰 `config_store`)。以后想要再加。
- 面板表头收起箭头(`‹`/`›`)。先纯靠拖拽收起；真觉得不直观再追加。
- 把 navigator 内部"文件区/通道区"做进一步折叠或重排(本次只整栏折叠)。
- Cockpit 窗口本身的形态变化(它仍是独立窗口，见 [[project-cockpit-ui-design]])，
  本次只移动它的**工具栏按钮位置**。

## 3. 状态机(每一侧独立)

```
                 hover 浮条 (≥150ms)
   ┌────────┐ ───────────────────────▶ ┌────────┐
   │ HIDDEN │                           │  PEEK  │
   │(浮条)   │ ◀─────────────────────── │(浮层)   │
   └────────┘   鼠标移出浮层∪浮条 >600ms  └────────┘
       ▲ │                                  │
       │ │ 单击浮条                          │ 单击浮条
拖把手到边 │ └──────────────┐                 │
(width≤阈值)│                ▼                 ▼
   ┌─────────────────────────────────────────────┐
   │                  PINNED (停靠)                │
   │        面板在 splitter 内、挤压 canvas         │
   └─────────────────────────────────────────────┘
```

- **HIDDEN**：splitter 该槽宽=0、面板 `setVisible(False)`；该侧浮条可见。
  - hover 浮条 → PEEK；单击浮条 → PINNED。
- **PEEK**：面板被 reparent 进一个浮层容器，浮在 canvas 之上(不改 canvas 宽度)，
  宽度 = 记忆停靠宽度 + ~24px("比实际宽点")。浮条仍在。
  - 鼠标位于 (浮层 ∪ 浮条) 内 → 保持；移出 → 启动 ~600ms 单次计时；
    计时内移回 → 取消；计时到 → 收回 HIDDEN。
  - 单击浮条 → PINNED(取消计时、reparent 回 splitter)。
- **PINNED**：面板回到 splitter，恢复记忆宽度、挤压 canvas，常驻。
  - 把 splitter 把手拖到边(该侧宽 ≤ 折叠阈值，建议 24px)→ HIDDEN。

并发：两侧可各自独立处于任意态(分居左右边，浮层不冲突)。

## 4. 架构与组件

### 4.1 新增：浮条 + 浮层控制器

建议新增模块 `mf4_analyzer/ui/side_panels.py`，包含：

- `SidePanelStrip(QFrame)`：~12px 竖条，`objectName="sidePanelStrip"`，
  `property("side", "left"|"right")`。
  - `enterEvent` → 发 `peek_requested(side)`(经短延时去抖，见 §6)。
  - `mousePressEvent(Left)` → 发 `pin_requested(side)`。
  - 内含一个朝内的小箭头(`‹`/`›`)；hover 提亮。
- `SidePanelController(QObject)`：持有每侧状态、计时器、记忆宽度、浮层容器引用，
  实现 §3 状态机。**纯逻辑可独立测试**(状态转移函数不依赖事件循环，见 §7)。
- `PeekOverlay(QWidget)`：浮层容器，**parent = 中央 widget**(非顶层窗口)，
  `raise_()` 到顶层 z-序。`enterEvent`/`leaveEvent` 驱动收回计时的取消/启动。

> **macOS 渲染红线**：浮层**必须是子控件**，绝不能是独立的 frameless 顶层窗口——
> 否则 macOS 会糊上原生方角阴影。本项目刚为此打过仗
> (commit `44786538` "kill macOS native square shadow on context menus")。
> 圆角/描边沿用现有 popup 风格(commit `c08bf734` "round menus/popups")，走 QSS。

### 4.2 改造：`main_window.py`

- 用一层 `QHBoxLayout` 包住现有 `splitter`：`[left_strip, splitter, right_strip]`，
  替换 `root.addWidget(splitter, ...)`(`main_window.py:163`)。两条 strip 初始隐藏。
- `setCollapsible(0, True)` 与 `setCollapsible(2, True)`(当前为 False，
  `main_window.py:156-158`)，保留中栏 `setCollapsible(1, False)`。
- 监听 `splitter.splitterMoved` → 某侧宽 ≤ 折叠阈值则进 HIDDEN。
- **泛化** `set_inspector_visible`(`main_window.py:195-231`) 为对两侧通用的
  show/hide(复用其"记忆恢复宽度 `_inspector_restore_width`、按 chart minWidth 兜底"
  的算术，`main_window.py:206-223`)，左侧加对应的 `_navigator_restore_width`。
- 实例化 `SidePanelController`，把 strip/overlay/splitter/两个面板交给它托管。
- `resizeEvent` / `moveEvent` / `splitterMoved` 触发浮层与浮条重定位——复用现有
  Toast 的 `resizeEvent` 重定位范式(`main_window.py:190-193`)；确保 Toast 仍在
  浮层之上(Toast 是瞬时通知，z-序最高)。

### 4.3 改造：`toolbar.py`

- 删除：`btn_inspector` 及其构造(`toolbar.py:41-45`)、`inspector_visibility_changed`
  信号(`:18`)、`_on_inspector_clicked`(`:175-177`)、`set_inspector_visible`(`:179-186`)、
  右段 `right.addWidget(self.btn_inspector)`(`:103`)、`_wire` 中的连接(`:144`)。
- 不新增 navigator 按钮。
- 把 `btn_acquisition_cockpit`(`:38-40`)从左段(`:66-73`)移到右段(`right` 布局，
  `:99-103`)，占掉原 inspector 按钮位置。
- 居中不受影响：右段靠 `_right_widget` 镜像 `_left_widget` 宽度保持模式段居中
  (`:105-136`)；右段内容从 inspector 换成 Cockpit 即可，镜像逻辑不变。

### 4.4 改造：`main_window._connect`

- 删除 `self.toolbar.inspector_visibility_changed.connect(self.set_inspector_visible)`
  (`main_window.py:240`)。
- `btn_acquisition_cockpit` 的 `acquisition_cockpit_requested` 连接保持不变(`:239`)。

### 4.5 改造：QSS 模板

- 在 `style.qss`(经 `ui_kit/stylesheet.py:load_stylesheet` 加载)新增
  `#sidePanelStrip`(默认淡、hover 提亮)与 `PeekOverlay`(圆角、轻描边、阴影沿用
  popup 风格)的样式。

### 4.6 面板侧(基本不动)

- `FileNavigator`(`file_navigator.py`)与 `Inspector`(`inspector.py`)只需被 reparent，
  内部不改。inspector 已有宽度约束(`setMinimumWidth(maximumWidth())`,
  `main_window.py:162`)，浮层里用显式 `setGeometry` 控制尺寸，不受其 min 约束影响。
  可选：各暴露一个 `preferred_dock_width()` 给控制器算浮层宽度。

## 5. 数据流

```
Strip.enterEvent ─(150ms 去抖)─▶ Controller.start_peek(side)
        │                             └▶ reparent 面板→PeekOverlay; 定位; show; raise_
Strip.mousePressEvent ───────────▶ Controller.pin(side)
        │                             └▶ 取消计时; reparent 面板→splitter; 恢复宽度; 隐藏 strip
PeekOverlay.leaveEvent ──────────▶ Controller.schedule_collapse(side)  # 启动 600ms
PeekOverlay.enterEvent ──────────▶ Controller.cancel_collapse(side)
QTimer.timeout ──────────────────▶ Controller.collapse(side)           # →HIDDEN
splitter.splitterMoved ──────────▶ Controller.on_splitter_moved()      # 宽≤阈值→HIDDEN
MainWindow.resize/move/splitterMoved ─▶ Controller.reposition()
```

reparent 不影响已连接的 signal/slot——浮层内勾通道照常触发
`channels_changed → replot`(`main_window.py:250` 链路不变)。

## 6. 关键参数(默认值，可逐条调)

| 参数 | 默认 | 说明 |
|------|------|------|
| hover 打开延时 | 150ms | 防止扫过浮条就误弹 |
| 移出自动收回延时 | 600ms | 移出 (浮层∪浮条) 后开始计时；再入即取消 |
| 浮层宽度 | 记忆停靠宽度 + 24px | "比实际宽点" |
| 折叠阈值 | 24px | `splitterMoved` 后该侧宽 ≤ 此值视为折叠 |
| 浮条宽度 | 12px | 折叠侧贴边竖条 |
| 启动态 | 两侧均 PINNED(停靠) | 维持现状(`setSizes([250,900,360])`,`:145`) |

## 7. 边界情况与错误处理

- **PEEK 时弹出通道右键菜单**(`primary_channel_requested` 来自通道树菜单)：
  鼠标移到菜单上会触发浮层 `leaveEvent` → 误收回。**收回计时 timeout 时检查
  `QApplication.activePopupWidget()`/菜单可见，则暂停(重排计时)**，避免误收。
- **PEEK→PIN 竞态**：单击浮条时若收回计时在跑，先 `stop()` 再 reparent，避免
  reparent 完成后 timeout 又把面板收回。
- **拖塌到边 vs 中栏最小宽**：collapse 时按 `chart_stack.minimumWidth()`(400,
  `:161`) 兜底，确保不把中栏压到非法宽度。
- **窗口缩放/移动时浮层错位**：所有 reposition 入口统一走 `Controller.reposition()`；
  PEEK 中缩放窗口要实时跟随边缘。
- **两侧同时 PEEK**：允许；分居左右，浮层互不重叠。
- **空文件态**：navigator 仍可折叠/召回，通道树为空但不报错。
- **Toast z-序**：Toast 显示时需在浮层之上(`toast()` 内 `raise_()`)。

## 8. 测试策略

仓库已有离屏 Qt 测试 harness：`tests/ui/conftest.py`(`QT_QPA_PLATFORM=offscreen`、
`qapp` 会话级 fixture、qtbot 可用)。

- **状态机单测(无事件循环)**：把 `SidePanelController` 的转移写成纯函数式
  (输入当前态+事件→新态+副作用描述)，直接断言 HIDDEN↔PEEK↔PINNED 全部转移，
  含"移出再移回取消收回""菜单打开暂停收回"的逻辑分支。TDD 先行。
- **widget 测**(qtbot + offscreen)：
  - 折叠某侧后对应 strip `isVisible()` 为真、展开时为假、零占位。
  - 单击 strip → 面板 reparent 回 splitter、该槽宽 = 记忆宽度。
  - hover strip → 浮层出现并 reparent 了真实面板；`channels_changed` 仍连通。
  - 计时类用 qtbot 等待或可注入的计时器(便于断言不靠真实墙钟)。
  - 删除 `btn_inspector` 后工具栏不再有该按钮、信号不存在；Cockpit 按钮在右段。
- **真实渲染验证(必须)**：macOS 实机截图核对浮条"淡"的观感、浮层无原生方角阴影、
  圆角/描边与现有 popup 一致。遵循 [[feedback-verify-ui-visually]]——不靠"属性设上了
  +单测过"就判定修好。

## 9. 实施顺序(供 plan 参考)

1. 抽出并 TDD `SidePanelController` 纯状态机。
2. `SidePanelStrip` + `PeekOverlay` 控件 + QSS 样式。
3. `main_window` 接线：包 strip、泛化 show/hide、splitterMoved、reposition、reparent。
4. `toolbar` 删 inspector 按钮链 + Cockpit 移位；`_connect` 同步。
5. widget 测 + macOS 截图验证。

## 10. 风险

- 主要硬骨头：PEEK 浮层 + reparent + 自动收计时这套交互，时序与 z-序/定位边角多。
- macOS 原生渲染(方角阴影)是已知地雷，靠"浮层=子控件"规避，且必须实机验证。
- reparent 真实面板进/出 splitter：需妥善管理 splitter 子控件索引(insertWidget(0/末位))
  与 `setVisible`，避免残留空槽。
