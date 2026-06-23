---
role: pyqt-ui
tags: [pyqtgraph, overlay, pan, mouse-press, y-drag, modifier, alt-option, pick-radius, hidden-curve, isvisible, eventfilter, companion, time-domain]
created: 2026-06-23
updated: 2026-06-23
cause: bug
supersedes: []
---

# 叠加模式下"逐通道 Y-drag"无条件抢占 Pan：改为 Alt/Option 修饰键 + 命中表排除隐藏曲线

## Context
叠加(overlay)时域里，用户点 Pan 按钮再拖动，结果不是平移而是**单独上下移动一条曲线**、
且 Pan 按钮的激活态被取消；**滤波后更明显**。这不是 Pan 坏了，而是 overlay 的"逐通道
Y-drag"手势把左键 press 抢占了。

## Lesson

### 病根 (三条事实叠加)
1. **press 抢占无视 Pan 工具**：`OverlayAxisManager._handle_overlay_mouse_press` 在 canvas
   `eventFilter` 的 MouseButtonPress 里**排第一**。它只对 **RectMode(框选缩放)** 让路
   (`_press_view_box_in_rect_mode`→return False)；其余一律：命中 `pick_radius_px=12` 内最近
   曲线→`select_overlay_channel`+`_begin_overlay_y_drag_at`+`return True` 吃掉事件。
   **PanMode 不在豁免里**——所以 press 根本到不了 pyqtgraph 的 X-master pan，Pan 工具在
   overlay 下永远不平移，只移动单曲线。
2. **选择会主动关掉 Pan 按钮**：`cards._on_overlay_channel_selected` 选中通道时
   `if mode=='pan': self.toolbar.pan()` 把工具栏切到 idle（防"下一次空白点被 pan 吃掉、
   无法取消选择"）。于是"拖一下→选中→Pan 激活被取消"。
3. **滤波放大命中概率**：能 pan 与否全看那 12px 命中是否落空（落空才 return False 放行给
   pan）。滤波让命中几乎必然：①命中表 `_channel_lines` 同含 primary+companion→曲线数翻倍；
   ②`_select_overlay_channel_from_scene_pos` 用 `pdi.getData()`，**隐藏曲线数据仍在→仍是
   命中目标**（显示原始 OFF 的隐藏原始照样被选中）；③[[2026-06-22-companion-curve-shares-source-axis-not-new-row]]
   follow-up #3 的可见性修复让滤波曲线**各自贴满整个子图高度**→铺满绘图区→点哪都在 12px 内。
   正常曲线候选少、留白多→偶尔落空→还能 pan，所以"没这么敏感"。
   注意：拖动幅度本身 `shift=-dy_px·量程/高度` 是 **1:1 像素**，量程窄反而数据位移更小——
   "敏感"指的是**几乎必被抢成 Y-drag**，不是位移变大。

### 解法 (方案2：修饰键 opt-in + 可见性排除)
- **逐通道 Y-drag 改为 Alt(Option)+拖动**：`_handle_overlay_mouse_press` 顶部
  `if not (event.modifiers() & Qt.AltModifier): return False`。裸左键拖动一路放行给 ViewBox
  (PanMode→X 平移 / RectMode→框选)。Pan 在 overlay 下恢复可用，且裸 press 不再触发选择→不再
  关 Pan 按钮（idle 仍是 PanMode，裸拖动照样平移）。
- **命中表排除隐藏曲线**(两种显示情况都"排除另外一个")：`_select_overlay_channel_from_scene_pos`
  循环里 `if not pdi.isVisible(): continue`。显示原始 OFF→排除原始；显示滤波 OFF→排除 companion。
- **共享轴拖动目标解析到可见 companion**：companion 与 primary 同 ViewBox，轴属于 primary。
  轴 gutter press 用新 `_visible_channel_name_for_handle(handle)`（返回该 handle 上第一条
  `isVisible()` 的通道）而非 `_channel_name_for_handle`，否则显示原始 OFF 时会去选隐藏 primary。
- **提示更新**：hint `overlay.drag_y` 改成"拖动平移时间轴 · Option/Alt+拖曲线 → 单独调该通道 Y 轴"。

### 验证铁律
靠**机制断言**锁定，别靠离屏模拟 pan（合成 QMouseEvent 在 offscreen 不一定真触发
ViewBox.mouseDragEvent）：裸 PanMode press→`_handle_overlay_mouse_press` 返回 False+未选中；
Alt press→返回 True+`dragging is True`+选中可见通道；Alt press 落在隐藏曲线→`selected != 隐藏名`；
overlay+companion+显示原始 OFF→`_visible_channel_name_for_handle` 返回 companion ∈ `_companion_names`。

## How to apply
pyqtgraph 自定义左键手势若放在 `eventFilter` press 最前并 `return True`，等于**默认抢占所有
左键拖动**——必须留一条"放行给 ViewBox"的路（最稳是改成修饰键 opt-in，而不是靠"命中落空"
这种几何脆弱的隐式放行）。任何"按数据找最近曲线"的命中表都要先 `isVisible()` 过滤，否则隐藏
但数据还在的曲线会变成幽灵命中目标。承接 [[2026-06-22-companion-curve-shares-source-axis-not-new-row]]
（可见性贴满高度正是把这条隐式放行路彻底堵死的放大器）。
