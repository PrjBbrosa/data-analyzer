# 标注小修 + 多通道性能 + 工具栏激活底色 设计

日期：2026-05-31
分支：`plan/pyqtgraph-timedomain-migration`
配套实施计划：`docs/superpowers/plans/2026-05-31-polish-perf-toolbar-plan.md`

本设计覆盖三块**相互独立**的子系统改动，可分别落地、分别验证：

- **A. 标注编辑器小修**（`mf4_analyzer/ui/markup/editor.py`）——上一轮 codex review 暴露的两处小问题。
- **B. 多通道性能**（`mf4_analyzer/ui/pg_canvases.py`）——复制图片卡 + 游标卡，均为主线程同步重活随通道数放大。
- **C. 工具栏激活态底色**（`mf4_analyzer/ui/chart_stack.py` + `mf4_analyzer/ui_kit/style.qss`）——nav 按钮激活只染图标色、丢了底色。

> 三块互不依赖，codex 可任意顺序执行；每块各自带离屏单测 + 真机验证。

---

## A. 标注编辑器小修

### A1 现状

上一轮 codex 已完整实现「二次修改打磨 + 工具栏二级菜单」，`test_markup_editor.py` + `test_copy_thumbnail.py` 56 项全绿，质量良好。review 仅发现两处小问题：

1. **画笔路径的缩放手柄基准错误**（`editor.py:1303-1329` `_drag_scale_handle` 非 group 分支）：
   ```python
   origin = item.mapToScene(QPointF(0, 0))
   ...
   candidates.append((point.x() - origin.x()) / rect.right())
   candidates.append((point.y() - origin.y()) / rect.bottom())
   ```
   文字 item 本地坐标从 (0,0) 起算、`origin == 文字左上角`，缩放正确；但**画笔 `QGraphicsPathItem` 的本地坐标 = 绘制时的绝对场景坐标**（`add_path_item` 用场景坐标建 path、item pos 默认 (0,0)，见 `_create_preview:431` / `add_path_item:581`），其 `boundingRect` 远离原点。于是 `setScale` 围绕 item 原点 (0,0) 缩放、再除以 `rect.right()/bottom()`（绝对坐标），画笔会「一边缩一边往场景左上角 (0,0) 飞」，不跟手。序号 group 走的是中心缩放分支（`:1307-1318`）、正常；只有画笔 path 这一类错。

2. **死代码**：`MarkupEditor._arrow_head(self, rect)`（`editor.py:1628-1648`）是旧实现遗留，箭头自带 `_ArrowAnnotationItem._arrow_head`（`:205`），这个无人调用；`QGraphicsPolygonItem` 的 import（`editor.py:29`）也已无引用。

### A2 设计

1. **画笔路径缩放改为以自身 bbox 左上角为基准**（与文字一致的「左上锚点」语义）：把非 group 分支的 `origin` 改成 path 自身 boundingRect 左上角映射到场景的点，scale 用「光标到左上角的距离 / bbox 宽高」，并设 `setTransformOriginPoint(rect.topLeft())` 让 `setScale` 也围绕左上角。这样拖右下手柄时左上角不动、跟手缩放。
   - 注意：`_geometry_snapshot`/`_restore_geometry` 的 path 走 `"scale"` 分支（`:1351/1367`），只存 `item.scale()` + `pos`，不存 transformOrigin。改动须保证 undo 还原后视觉一致——把 `setTransformOriginPoint` 设为 path 的 bbox 左上角（一个稳定值，不随 scale 变），restore 时一并复原 origin 或保证 origin 在 add 时即固定。最简实现：在 `add_path_item` 里建好就 `setTransformOriginPoint(path.boundingRect().topLeft())`，缩放分支只 `setScale`，origin 恒定，snapshot 无需扩展。
2. **删死代码**：移除 `MarkupEditor._arrow_head`（`:1628-1648`）与未用的 `QGraphicsPolygonItem` import（`:29`）。

### A3 范围外
- 不动序号/文字/矩形/线/箭头已正常的手柄逻辑；不动撤销栈、命中、二级菜单。

---

## B. 多通道性能：复制图片卡 + 游标卡

### B1 现状（均已对照代码核实）

时域画布已迁 pyqtgraph，活跃文件 `pg_canvases.py`。两条路径把随**通道数**线性放大的重活同步压在 UI 主线程：

**B1.1 复制图片（"转圈很久"，最近回归）**
- 链路：图卡复制按钮 → `ChartStack._copy_card_image` → `_grab_pixmap_hidpi(canvas)` → 时域 pyqtgraph 卡走 `canvas.grab_pixmap(scale=2.0)`（`pg_canvases.py:3779`）。
- `grab_pixmap` **无条件** `with self._curves_antialiased():`（`:3812`，定义 `:3745-3777`）给**每条曲线**强开 `opts["antialias"]=True`，随后 `_grab_widget_scaled`（`:3831`）`widget.grab()`（`:3846`）触发整图同步重栅格化，再 `base.scaled(w*2, h*2, …, Qt.SmoothTransformation)`（`:3859`，上限 `_HIDPI_MAX_WIDTH=2560`，`:259`）。
- **为什么随通道数放大**：多通道叠图时，idle-AA 已按密度预算 `_idle_aa_density_ok()`（`:3666`，overlay 用「所有曲线点数之和」为 metric、超 `_AA_OVERLAY_SEGMENT_OFF` 就关 AA）把 AA **关掉**以保持流畅；但复制时 `_curves_antialiased()` 把 AA **强行开回所有曲线** → `widget.grab()` 把所有叠图曲线带 AA 重栅格化一遍（overlay 模式明确不启用 DeviceCoordinateCache，`:3647`）= O(总点数) 的重活。这正是 commit `c08bf734`（"AA exports"）引入的回归：在它之前复制是一次廉价 `widget.grab()`、不强制 AA、无 2× 放大。

**B1.2 游标（"点选择游标卡"）**
- `_handle_cursor_mouse_move`（`pg_canvases.py:1982`，33ms 节流 `:1995`）在 dual 模式每个悬停帧调 `self._emit_dual_cursor_html()`（`:2003`）。
- `_emit_dual_cursor_html`（`:3208-3247`）对**每个通道**在**原始全分辨率数组**上做 `m=(tf>=xlo)&(tf<=xhi)` 全量布尔掩码（`:3231`）+ `np.min/np.max/np.mean(seg)`（`:3241-3243`）+ 两次 `_interp_cursor_value`（`:3236`）= **O(通道数 × 采样点) / 每帧**。
- **关键事实**：`_emit_dual_cursor_html` 只依赖 `self._ax/self._bx`，**完全不依赖 hover 的 x**，且已在落点处理 `_handle_cursor_mouse_press`（`:2038`）调用过。悬停时 A/B 没变 → 每帧重算结果完全相同 → **纯浪费**。
- 此外每个悬停帧末尾 `self.draw_idle()`（`:2010`）整图重绘（overlay 无缓存），这部分随通道数放大但属移动游标线的固有开销。

### B2 设计

**B2.1 复制：按密度自适应，AA 只在「划算」时强开**

复制不应强制把已被密度预算关掉的 AA 开回去。新增一个**不改 hysteresis 状态**的纯判定 `_export_aa_affordable() -> bool`（复用 `_idle_aa_density_ok` 的 metric 口径：overlay=所有曲线点数之和，subplot/single=各行点数和的最大值；与 `_AA_*_SEGMENT_OFF` 比较），`grab_pixmap` 据此分支：
- **划算**（点数在预算内，通常少通道）：保持现状——`with self._curves_antialiased(): _grab_widget_scaled(target, eff_scale)`，2× 高清 + AA，crisp 不变。
- **不划算**（多通道、超预算）：**跳过 `_curves_antialiased()`**（用当前屏上的渲染态，即所见即所得），抓图所见即所得；2× 缩放可一并降级为 1×（`eff_scale=1.0`）以彻底去掉大图平滑缩放的固定开销。这把多通道复制还原到接近 `c08bf734` 之前的廉价 `widget.grab()`，恢复「丝滑」。

> 取舍说明：此方案只在「本就会卡」的多通道场景降级清晰度（降到与屏幕一致），少通道场景的 2×+AA crisp 复制保持不变——不需要用户在「快」和「清晰」之间二选一。若后续想更激进（永远走廉价 grab、AA 只留给「保存图片」），可把 `_export_aa_affordable` 恒返回 False，改动点单一。
> `_export_aa_affordable` **必须不触碰** `_idle_aa_density_allowed`/`_idle_aa_density_seeded`（那是 idle-AA 的 hysteresis 状态），即重新算 metric、只读不写，避免与 idle-AA 决策互相干扰。

**B2.2 游标：悬停不再重算与 hover 无关的 dual 统计**

`_handle_cursor_mouse_move` 的 dual 分支（`pg_canvases.py:1998-2003`）**移除 `self._emit_dual_cursor_html()` 调用**，只保留移动虚线 hover_items（`_set_cursor_items_pos`）+ `draw_idle()`。dual 读数（A/B、ΔT、各通道 min/max/mean/Δ）仍由落点处理 `_handle_cursor_mouse_press`（`:2038`）在 A/B 变化时发出——输出零变化，但每帧的 O(通道×采样) numpy 全没了。
- single 分支不动（`_emit_single_cursor_html(x)` 依赖 x、且只是 O(通道) 的 searchsorted，便宜）。
- 每帧 `draw_idle()` 的整图重绘是移动游标线的固有成本，本轮不动（属可接受残余；真要再优化是另一档 pyqtgraph 缓存课题，风险高，不纳入）。

### B3 范围外
- 不改抓图入口 `_copy_card_image`/`_grab_pixmap_hidpi`、不改 CursorPill 合成、不改剪贴板发布管道与缩略图。
- 不改 idle-AA 的 hysteresis 阈值与 `_idle_aa_density_ok` 行为本身。
- 不引入 worker 线程（QPixmap/`widget.grab()` 必须主线程；本方案靠「少干活」而非「挪线程」解决）。

---

## C. 工具栏激活态底色（matplotlib / pyqtgraph nav 按钮）

### C1 现状（已核实）
- nav 工具栏（matplotlib `NavigationToolbar` 或 pyqtgraph `PgNavigationToolbar`，objectName `chartToolbar`）的按钮在 `chart_stack.py:804-807` 仅 `setFixedSize(32,32)`，**未设 role、未按激活态设底色**。
- 激活态（pan/zoom）目前**只靠 `_apply_mdi_icons(toolbar, active_key=key)`（`:257-265`，由 `_refresh_hint:1075` 调）把激活键的图标染成 `_ICON_ACTIVE`、其余 `_ICON_COLOR`**（`:264`）——只有图标变色。
- 全局 QSS 有 `QToolButton:checked { background-color:#e8efff; border-color:#1769e0; }`（`ui_kit/style.qss:237-242`，经 `app.py:83 load_stylesheet` 应用），但 nav 按钮没进 checked/active 态，故底色不触发 → 用户看到的「只有图标有颜色、不直观」。

### C2 设计

让激活的 nav 按钮显式获得底色，**不依赖 matplotlib/pyqtgraph 各自的 checked 内部逻辑**（两种 toolbar 实现不同，统一走属性最稳）：

1. 在 `_apply_mdi_icons`（`chart_stack.py:257-265`）已有的「遍历 actions、知道 active_key」循环内，对带 MDI 图标的 nav 按钮经 `toolbar.widgetForAction(act)` 取 `QToolButton`，设动态属性 `btn.setProperty("navActive", key == active_key)`，再 `btn.style().unpolish(btn); btn.style().polish(btn)` 触发重绘。非 QToolButton（分隔符/locLabel）跳过。
2. `ui_kit/style.qss` 增一条作用域规则：
   ```css
   #chartToolbar QToolButton[navActive="true"] {
       background-color: #e8efff;
       border: 1px solid #1769e0;
   }
   ```
   作用域限定 `#chartToolbar`，不影响其它 QToolButton；激活态同时有「蓝底 + 蓝边 + 图标变蓝」，直观。

> 覆盖范围：`_refresh_hint`（pan/zoom 切换）与初始 `_apply_mdi_icons(self.toolbar, active_key='pan')`（`:823`）都会刷新属性；matplotlib 卡与 pyqtgraph 时域卡共用 `_apply_mdi_icons`，两者一并修复。
> 其它已是 checkable 的按钮（标注开关 `_annotation_btn:987`、分屏/叠加、游标 off/single/dual）已能命中 `:checked` 底色，不在本次改动内。

### C3 范围外
- 不改 nav 的鼠标模式状态机（`_current_mode_key`/`_on_nav_mode_toggled`）、不改图标染色逻辑本身（底色是叠加，不替换图标变色）。
- 不动 segment 切换条（time/fft/order）等已有 `:checked` 样式的控件。

---

## 验收标准（本仓库铁律：只认真机渲染/截图，不认「属性设上了 + 单测过」）

- **A**：编辑器里画一段画笔曲线 → 选中 → 拖右下手柄，缩放跟手、左上角不漂移；undo 能还原；其余工具回归正常。
- **B 复制**：时域叠加多通道（≥6 条）→ 点「复制为图片」**不再转圈/秒回**，外部粘贴得到的图与屏幕一致（多通道下不再 2×/AA）；少通道时复制仍是 2× crisp。
- **B 游标**：多通道时进入双游标、移动鼠标悬停**不再卡顿**；A/B 落点的读数（ΔT、各通道 min/max/mean）与改动前一致。
- **C**：matplotlib 卡（FFT/阶次/FFT-vs-Time）与时域卡点 pan/zoom，激活按钮显示**蓝底 + 蓝边**，切换/退出时底色正确跟随；其它按钮 hover/pressed/checked 表现不变。
