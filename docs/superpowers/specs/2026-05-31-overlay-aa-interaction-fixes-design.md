# 叠加模式 抗锯齿 / 交互 Bug 修复设计

日期：2026-05-31
分支：`plan/pyqtgraph-timedomain-migration`
上游设计：[`2026-05-30-pyqtgraph-timedomain-auto-idle-aa-design.md`](2026-05-30-pyqtgraph-timedomain-auto-idle-aa-design.md)
目标文件：`mf4_analyzer/ui/pg_canvases.py`（时域画布，pyqtgraph 后端）

## 背景

Auto Idle AA（交互期 AA off / 停手 150ms 后过密度门再开 AA）上线后，用户在**叠加模式**报告 4 类问题。
逐条做了根因核实（读 `pg_canvases.py` + pyqtgraph 0.14 源码 `ViewBox.mouseDragEvent`），结论如下。

### 根因核实（决定方案正确性）

1. **框选橡皮筋拖动期间不触发任何 range 变化。** `ViewBox.mouseDragEvent`
   （`.venv/.../pyqtgraph/graphicsItems/ViewBox/ViewBox.py:1352-1363`）在 `RectMode` 下，
   拖动中只调 `updateScaleBox()` 画橡皮筋，**仅在 `ev.isFinish()`** 才 `showAxRect()` 改范围。
   → 整段框选拖动**不经过** `_on_xrange_changed()`（`pg_canvases.py:2510`，关 AA 的唯一 chokepoint），
   所以**框选全程 AA 维持原状**；若框选前处于静止 AA-on，则橡皮筋每帧把全部曲线按 AA 重栅格化。
   这是上游设计 §C/§61「`_on_xrange_changed` 覆盖框选」假设的**漏洞**：它只在松手那一刻覆盖，
   拖动过程没覆盖。→ 直接造成 **问题 3（框选/拖动卡死）** 与 **问题 4b（框选不丝滑）**。
   （对比：`PanMode` 在每次拖动都 `translateBy()`+`sigRangeChangedManually.emit`，
   `ViewBox.py:1374-1375` → 平移每帧都关 AA，平移本身不背锅。）

2. **叠加左键按下被 overlay 选择 handler 抢走。** `eventFilter` 在 `MouseButtonPress` 先调
   `_handle_overlay_mouse_press()`（`pg_canvases.py:2307`），命中曲线 `_overlay_pick_radius_px`(=12px)
   内即 `return True` **吃掉事件**，ViewBox 收不到按下 → 框选橡皮筋根本起不来，反而进入 Y 拖动。
   且该 handler **不查当前鼠标模式**。→ **问题 4a（框选容易误触曲线）**。

3. **密度门阈值低于宽窗口下的包络点数，且有冷启动死区。** 阈值写死
   `_AA_DENSITY_ON=4000 / _AA_DENSITY_OFF=6000`（`pg_canvases.py:780-781`）。
   `positions_envelope` 输出 ≈ `2×绘图区像素宽`（`_envelope_cutils.py:233-251`，压成 `pixel_width`
   个 min/max 桶）。上游设计 §F 自己按「~1500px → ~3000 点」估算，但**窗口最大化 / 4K / Retina**
   下绘图区宽过 ~3000px → 包络 >6000 点 → 密度门 `_idle_aa_density_ok()`（`:3438`）永久判 False。
   且 hysteresis 在 `(4000, 6000]` 死区**保持旧值**，旧值初始为 False（`:782`），首次落在死区就**卡死在不开**。
   → **问题 1（缩放后 AA 不开）**。另：`resizeEvent`（`:3345`）改完窗口既不重算包络也不重排 idle AA。

4. **密度门按「单条最密曲线」放行，叠加成本却是「同一 ViewBox 上所有曲线之和」。**
   `_idle_aa_density_ok()` 取 `max_points`（`:3440-3448`）。叠加把 N 条曲线画在**同一 ViewBox、同一脏区**，
   开 AA 后每次 `draw_idle()`/`_glw.update()`（游标 hover 每 33ms 一次）都把 N 条曲线**整体重栅格化**；
   分开（subplot）模式每条在独立行/独立脏区，局部重绘只碰一条。→ **问题 2（叠加 AA 明显比分开慢）**。
   这正是上游设计 §D 预留的 Strategy B（`DeviceCoordinateCache`）要解决的场景，当时「实测超标才上」，
   现在用户报告即为实测超标。

## 锁定决策

| 决策 | 内容 | 理由 |
|---|---|---|
| 不推翻 Auto Idle AA | 沿用「交互 off / 停手开 AA」模型，只补它的漏洞 | 包络已把每条曲线点数钉在 ~2×像素宽，架构本身正确，无需换全局 AA / OpenGL / downsample 重构 |
| 框选与曲线选择分模式 | **框选(zoom)模式**：左键一律走橡皮筋框选，overlay press 让路；**平移(pan)模式**：保留就近选曲线 + Y 拖动 | 符合工具栏两态直觉，彻底消除「框选误触曲线」，零修饰键负担 |
| 框选拖动接 AA 钩子 | 在 ViewBox 子类 `mouseDragEvent` 的 RectMode 左键 `isStart` 关 AA | 补 `_on_xrange_changed` 只覆盖松手、不覆盖拖动的漏洞 |
| 密度门改「每 ViewBox 绘制点之和」+ 宽度无关预算 + 修死区 | 度量改 sum/ViewBox，阈值放宽到单曲线在最大化窗口仍可开 AA；首判用 OFF 阈值播种避免卡死 | 单条曲线 AA 成本有界且可接受（上游 3000 点已验流畅），叠加多条才需抑制 |
| 叠加 idle AA 上 `DeviceCoordinateCache` | 开 idle AA 时给曲线 item 设 DeviceCoordinateCache，关 AA / 几何变化时设 NoCache | 让 hover/游标重绘**贴缓存位图**而非重栅格化全部叠加曲线，直击「叠加 AA 慢」 |
| resize settle 后重排 | `resizeEvent` debounce 后 `schedule_idle_quality()`（+ 触发一次包络重算以匹配新宽度） | 缩放后 AA 能自行恢复 |
| 不动的东西 | envelope 算法、sibling 坐标同步、setData、导出 `_curves_antialiased()` 语义、频域/阶次数值路径 | 与上游 §范围外一致 |

## 设计

### Fix A — 框选模式让路（问题 4a）

`_handle_overlay_mouse_press()`（`pg_canvases.py:2062`）开头增加模式判定：解析按点所在 ViewBox，
若 `vb.state['mouseMode'] == pg.ViewBox.RectMode`（=1，已核实 `ViewBox.py:100`）→ **`return False`**，
让事件落到 pyqtgraph，橡皮筋正常起手。仅在 `PanMode`(=3) 下保留现有「就近选曲线 + 开 Y 拖动」。
（实现可直接读 ViewBox 的 `state['mouseMode']`，无需依赖 mouse-mode controller，降耦合。）

游标模式仍优先（`_cursor_visible` 时本 handler 早返回，维持 `canvases.py:853` 语义不变）。

### Fix B — 框选拖动关 AA（问题 3 / 4b）

在 `_ModifierWheelViewBox`（`pg_canvases.py:593`）覆盖 `mouseDragEvent(self, ev, axis=None)`：

```
owner = self._owner_canvas
if owner is not None and ev.button() == Qt.LeftButton \
        and self.state.get('mouseMode') == pg.ViewBox.RectMode and axis is None:
    if ev.isStart():
        owner.disable_interactive_quality()   # 橡皮筋开始 → AA off，停 idle timer
# 始终交给基类完成橡皮筋/缩放本身
super().mouseDragEvent(ev, axis=axis)
```

松手（`isFinish`）由基类 `showAxRect → setRange → sigXRangeChanged → _on_xrange_changed`
已有的 disable + 40ms 刷新 + `schedule_idle_quality` 链路覆盖，无需在子类重复排期。
拖动中鼠标按住，idle gate 的 `mouseButtons() != NoButton` 本就拒绝开 AA，故 `isStart` 关一次即足够。

### Fix C — 密度门重做（问题 1 + 给问题 2 兜底）

改 `_idle_aa_density_ok()`（`pg_canvases.py:3438`）：

1. **度量改为「每个 ViewBox 上曲线绘制点之和」的最大值**：按 `view_box` 分组 `_collect_curve_items()`
   读 `getData()` 长度求和，取各 ViewBox 之最大。subplot 模式每 VB 一条 ≈ 单曲线点数；
   叠加模式共享 VB ≈ N×单曲线点数。这才是单帧真实重栅格化成本。
2. **阈值放宽且与窗口宽度无关**：新增 `_AA_SEGMENT_ON` / `_AA_SEGMENT_OFF`（初值待真机调，
   建议 ON≈12000 / OFF≈16000）。使**单条曲线在最大化/4K 窗口（~6000 点）始终可开 AA**（修问题 1），
   而 4~5 条密集叠加曲线之和超预算时优雅回落 AA-off（给问题 2 兜底，配合 Fix D）。
3. **修冷启动死区**：首次判定（及 resize/rebuild 复位后）用单阈值 `OFF` 播种 `_idle_aa_density_allowed`
   （`metric <= OFF` 即 True），之后才进入 ON/OFF 滞回；任一曲线 `getData()` 不可读时 fail-closed（保持现状）。

`resizeEvent`（`:3345`）末尾：在现有 label 重排后，**debounce 触发一次包络重算 + `schedule_idle_quality()`**
（复用 `_refresh_timer` 风格的 40ms 单次，避免连续拖拽边框时狂算），使缩放结束后 AA 能按新宽度自行恢复。

### Fix D — 叠加 idle AA 用 DeviceCoordinateCache（问题 2）

落地上游设计 §D Strategy B：

- `try_enable_idle_quality()`（`:3414`）成功开 AA 后，对 `_collect_curve_items()` 的 item
  `setCacheMode(QGraphicsItem.DeviceCoordinateCache)`。此后游标 hover / `draw_idle()` 的
  `_glw.update()` 重绘**贴设备坐标缓存位图**，不再重栅格化全部叠加 AA 曲线。
- `disable_interactive_quality()`（`:3392`）关 AA 时同步 `setCacheMode(QGraphicsItem.NoCache)`
  ——**任何 range/几何变化必须使缓存失效**，否则平移/缩放会糊。
- 缓存失效的关键边界（range 变化、resize、replot）都已汇聚到 `disable_interactive_quality()` /
  rebuild 路径，复用即可。

> 取舍：若真机验收发现仅 Fix C 的 sum 预算就让叠加 AA 流畅（如常用通道数 ≤3），Fix D 可降级为
> 仅在叠加且曲线数超阈值时启用，避免给 subplot 单曲线引入无谓缓存位图开销。最终以真机帧率/肉眼为准。

## 测试（TDD，沿用 `tests/ui/test_pg_timedomain_canvas.py` 离屏模式，QTimer 直调槽）

新增 / 调整：
- **Fix A**：ViewBox `state['mouseMode']=RectMode` 时 `_handle_overlay_mouse_press` 返回 False（不选曲线、不开 Y 拖动）；`PanMode` 时维持现有选择+拖动行为。
- **Fix B**：构造 RectMode 的 `isStart` 拖动事件 → `disable_interactive_quality` 被调（AA→off、idle timer 停）；非 RectMode（PanMode）不额外触发。
- **Fix C**：叠加 N 条曲线时密度度量为**和**而非 max；单条 6000 点（模拟最大化）首判即可开 AA（死区不再卡 False）；sum 超 OFF 预算时拒绝；`getData` 不可读 fail-closed；ON≠OFF 滞回不抖。`resizeEvent` 后 idle timer 被重排。
- **Fix D**：开 idle AA 后曲线 item `cacheMode == DeviceCoordinateCache`；`disable_interactive_quality` 后回到 `NoCache`。
- **回归保护**：`test_curves_are_not_antialiased_for_pan_perf`、现有 idle-AA / 导出 `grab_pixmap` 还原、`tests/perf/test_timedomain_pan_perf.py` p95 全部不劣化（密度阈值放宽不改交互期 AA-off 这条线）。

## 范围外

- 全局永久 AA、OpenGL backend、idle cached pixmap overlay（同上游）。
- envelope 算法、坐标同步、setData、hit-test 半径/选中样式、grid/label、频域阶次数值路径。
- hit-test 逐点 `mapViewToScene` Python 循环（`:2014`）的向量化：已识别为额外低优项，**本轮不做**，
  仅在真机按下仍发涩时再单列任务。

## 验收标准（必做真机验证，按本仓库铁律：只认真机渲染/截图，不认「属性设上了+单测过」）

用 4–5 通道数据（如 `tiaodamping`），分别在 subplot / overlay 下验：
- **问题 1**：把窗口最大化 / 高 DPI 显示器全屏 → 停手 ~150ms 后曲线仍变细腻（AA 开）；缩放窗口大小后 AA 能自行恢复。留「小窗 AA 开」「最大化 AA 开」两张截图对比。
- **问题 2**：overlay 下 4–5 条曲线开 AA 后，移动游标 / hover 不卡、帧率与 subplot 同场景相当（不再「明显慢」）。
- **问题 3**：overlay 下连续平移、连续框选不卡死；框选橡皮筋拖动期间曲线为 AA-off（流畅）。
- **问题 4a**：框选(zoom)模式下，起手紧贴某条曲线也能正常拉出框选矩形，不被「选中+Y 拖动」抢走；平移模式下贴曲线仍可选中。
- **问题 4b**：框选橡皮筋拖动丝滑、不闪、不掉帧。
- 交互期（平移/框选/滚轮/overlay-Y 拖动）曲线 AA 恒 off；停手只跳一次、不回弹（上游验收线不回退）。
- 复制/保存仍高质量。

## 风险

- **Fix B 的子类 `mouseDragEvent` 覆盖**必须始终 `super()`，否则框选/平移本身失效；只在 RectMode+左键+`axis is None` 时插钩，其余分支（右键缩放、单轴拖动）保持原样。
- **Fix D 的 DeviceCoordinateCache 必须在几何变化时失效**（NoCache），否则 pan/zoom 会糊——失效点全部收敛在 `disable_interactive_quality()`，确保它在所有 range/resize/replot 前被调到。
- **密度阈值是真机可调参数**：ON/OFF 初值仅为起点，验收时按实测帧率微调；放宽阈值不得让交互期 AA 偷偷打开（交互期 gate 由 `mouseButtons`/`_overlay_dragging` 把守，与阈值正交）。
- 三 timer（idle 150ms / 数据 40ms / 历史 debounce 180ms）次序与上游一致，resize 新增的 debounce 重算需确认不与 idle timer 互相打架（resize 结束 → 数据落定 → idle 开 AA，两段式可接受）。
