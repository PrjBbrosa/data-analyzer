# PyQtGraph TimeDomain Auto Idle AA 设计

日期：2026-05-30
分支：`plan/pyqtgraph-timedomain-migration`
上游可行性报告：[`docs/analyzer/reviews/2026-05-30-pyqtgraph-realtime-aa-feasibility.md`](../../analyzer/reviews/2026-05-30-pyqtgraph-realtime-aa-feasibility.md)
关联性能回归修复：[`docs/superpowers/plans/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md`](../plans/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md)

## 背景

复制/保存图明显比实时窗口细腻，因为高质量渲染被**刻意隔离在导出期间**：
`grab_pixmap()` 进入 `_curves_antialiased()` 上下文，把每条 `PlotCurveItem.opts["antialias"]`
临时设为 `True`，退出即还原（`mf4_analyzer/ui/pg_canvases.py:3329-3361`、`:3363-3406`）。
实时路径则刻意保持 AA off：曲线创建不传 `antialias=True`（`pg_canvases.py:1299-1303`），
回归测试 `test_curves_are_not_antialiased_for_pan_perf` 明确要求交互曲线 AA off
（`tests/ui/test_pg_timedomain_canvas.py:3372-3391`）。这条 AA-off 保护线是
2026-05-29 性能回归修复的核心结论之一：`antialias=True` 是 pan 卡顿三大新增成本之首。

**目标：** 在不动这条性能保护线的前提下，让用户**停手后**看到的静态画面恢复到接近导出的细腻度——
即 **Auto Idle AA**：任意交互期间曲线 AA off，最后一次交互稳定 150ms 后单次开启 AA 并重绘一次。

### 关键渲染机制（已核实，决定方案正确性）

1. `draw_idle()` 实为 `self._glw.update()`（`pg_canvases.py:1723-1735`），即"标脏整个场景下一帧重绘"。
   pyqtgraph 在 `paint()` 时读 `opts["antialias"]`，所以 **AA 状态是"黏"的**：设一次 on 后所有重绘都按 on
   画，直到下一次交互把它设回 off。→ 离散操作（pan/zoom/wheel/overlay/Home）只会得到**一次**"变细腻"跳变，
   不会反复横跳。
2. `_glw.update()` **不会**调用 `_refresh_visible_data()`（envelope + `setData` 的昂贵路径，
   `pg_canvases.py:2577-2623`）。后者只由 40ms `_refresh_timer` 触发。因此切 AA 时
   "只改 opts + `_glw.update()`"既能让 AA 生效、又不会重推数据、不破坏 envelope 缓存。
3. 所有 X 范围变化（pan / 框选 / 滚轮缩放 / Home / Back / Forward）都汇聚到单一入口
   `_on_xrange_changed()`（`pg_canvases.py:2465-2485`），它启动 40ms debounce 的 `_refresh_timer`。
   → 这是关 AA 的**单一 chokepoint**。
4. overlay 通道 Y 拖动改的是 Y 范围，**不经过** `_on_xrange_changed`，由
   `_handle_overlay_mouse_press/release` 维护 `_overlay_dragging` 标志
   （`pg_canvases.py:2020-2077`，`_overlay_dragging` 定义于 `:861`）。→ 需要独立接 AA 关/调度。
5. 游标 hover 每 33ms 节流后调 `draw_idle()`（`pg_canvases.py:1814-1842`）。hover 只移动游标竖线，
   不改曲线几何，但 `_glw.update()` 会连曲线一起重栅格化。

## 与可行性报告的差异（本设计的三处修订）

可行性报告整体结论（Auto Idle AA 可行、全局 AA 不可行）予以采纳。以下三点是基于渲染机制核实后的**修订**，
直接决定"会不会闪屏"：

| # | 报告原方案 | 本设计修订 | 理由 |
|---|---|---|---|
| 1 | 游标移动期间曲线 AA 强制 off，停 200ms 后再 on | **游标移动不触碰曲线 AA**（默认 Strategy A）；仅当实测 hover+AA 帧成本超标时，改用 `DeviceCoordinateCache`（Strategy B），仍不关 AA | 游标是"扫-停-读"的连续操作。若每次移动关 AA、停下开 AA，曲线会在糙↔细之间反复跳 = 真闪屏。hover 不改曲线几何，且无 `setData`/label 重排（与 pan 卡顿成因不同），AA-on 的 hover 重绘很可能可接受——**先测再定**，不预设关 AA |
| 2 | 线宽 1.4–1.5 放在第二阶段 | **线宽 1.7→1.5 与 idle-AA 同期做**（`_overlay_default_lw`，`pg_canvases.py:832`） | AA off 时 1.7px 取整成 ~2px 硬块、on 时渲成 ~1px+半透明，off→on 同时变细变瘦，跳变幅度比"单纯磨边"大。先把两态视觉粗细拉近，跳变才不突兀，直接降低感知"闪一下"的强度 |
| 3 | 密度门控用单一阈值 | 密度门控用**滞回双阈值**（on 阈值 < off 阈值） | 单一 cutoff 在用户缓慢缩放、密度恰好卡在阈值附近时会反复 on/off = 又一种闪。滞回避免边界抖动 |

## 锁定决策

| 决策 | 内容 |
|---|---|
| 总体方案 | Auto Idle AA（交互 off / 停手 150ms 后单次 on）。**不做**全局永久 AA、**不做** OpenGL backend、**不做** idle cached pixmap overlay |
| 关 AA chokepoint | `_on_xrange_changed()` 顶部（覆盖 pan/框选/滚轮/Home/Back/Forward）+ overlay Y-drag press |
| 开 AA 时机 | 最后一次 range 变化稳定后 150ms 单次 timer，且通过门控才开 |
| 开 AA 门控 | 鼠标无按键 + 非 overlay 拖动 + 密度未超阈值（滞回） |
| 游标 | 默认不触碰曲线 AA（Strategy A）；实测超标才上 `DeviceCoordinateCache`（Strategy B） |
| 线宽 | `_overlay_default_lw` 1.7 → 1.5，与 idle-AA 同期 |
| 导出 | `_curves_antialiased()` 维持"存原值/退出还原原值"语义不变，导出不依赖也不破坏实时 AA 状态 |
| 数据/坐标 | 不改 envelope、不改 sibling 坐标同步、不改 setData、不改 ViewBox mouse mode |

## 设计

### A. 曲线 AA 状态 helper

复用 `_collect_curve_items()`（`pg_canvases.py:3325-3327`，从 scene 收集 `pg.PlotCurveItem`，
与导出路径同一集合）。新增一个**持久态** setter（区别于 `_curves_antialiased()` 这个上下文管理器）：

```python
def _set_curves_antialias(self, on: bool) -> int:
    """Set opts['antialias'] on every curve. Does NOT repaint or setData.
    Returns the number of curves touched. Mirrors the opt that
    _curves_antialiased() / grab_pixmap() flip for export, so live idle
    AA and export AA read/write the same PlotCurveItem.opts['antialias']."""
```

### B. Auto Idle AA 状态机

新增局部状态（不引入新的数据结构开销）：

- `self._idle_aa_on: bool`（实时曲线当前 AA 态，初始 `False`）
- `self._idle_aa_timer: QTimer`（单次，150ms，复用现有 `QTimer` import @ `:66`）

三个方法：

- `disable_interactive_quality()`：交互开始/range 变化/overlay 拖动/replot 调用。
  若 `_idle_aa_on` 为 True，则 `_set_curves_antialias(False)` + `self._glw.update()` + `_idle_aa_on=False`，
  并 `stop()` idle timer。**幂等且极廉价**（无 setData）。
- `schedule_idle_quality()`：每次交互稳定后调用，`(re)start` 150ms 单次 timer。
- `try_enable_idle_quality()`（timer 的 timeout 槽）：门控全通过才
  `_set_curves_antialias(True)` + `self._glw.update()` + `_idle_aa_on=True`。门控：
  - `QApplication.mouseButtons() == Qt.NoButton`（鼠标无按键——pan/框选/拖动中必为按下）
  - `not self._overlay_dragging`
  - 密度门控（见 F）通过
  - 任一不满足：不开 AA（不重新自动排期，下一次交互结束会再调 `schedule_idle_quality()`）

### C. 接入点

| 接入点 | 调用 | 说明 |
|---|---|---|
| `_on_xrange_changed()` 顶部（`:2465`，在 `_refresh_pending` 早返回**之前**） | `disable_interactive_quality()` | 单一 chokepoint，覆盖 pan/框选/滚轮/Home/Back/Forward。幂等所以可在每次 range 变化无条件调 |
| `_refresh_visible_data()` 末尾（`:2623` 后） | `schedule_idle_quality()` | 数据稳定后排期 idle |
| `_handle_overlay_mouse_press()`（`:2020`，开始 Y-drag 处） | `disable_interactive_quality()` | Y-drag 不经 X-range chokepoint，需独立接 |
| `_handle_overlay_mouse_release()`（`:2070`） | `schedule_idle_quality()` | drag 结束后排期 |
| `_handle_wheel_dispatch()`（`:2926`） | `disable_interactive_quality()` + `schedule_idle_quality()` | Ctrl wheel 会触发 X-range chokepoint，但 Shift/plain wheel 只改 Y range；滚轮入口需覆盖三种 wheel，避免 Y-only 交互以 AA-on 重绘 |
| 通用 `MouseButtonRelease`（`eventFilter`） | `schedule_idle_quality()` | 普通 pan/rect zoom 可能在鼠标仍按下时让 idle timer 到期并被 gate 拒绝；release 后重新排 idle，overlay release 仍走 overlay 专用路径 |
| `plot_channels()` 开始与末尾（`:911`） | `disable_interactive_quality()` | rebuild 开始先取消 stale idle timer；fresh build 结束后曲线保持 AA off，保证新建曲线默认 off（现有 `test_curves_are_not_antialiased_for_pan_perf` 仍绿） |
| `plot_channels_preserving_xlim()`（`:1228`） | 不在末尾额外 `disable_interactive_quality()` | 该函数先 `plot_channels()` 再 `_restore_primary_xlim()`；restore 会触发 `_flush_pending_refresh()` 并由 `_refresh_visible_data()` 排 idle timer，末尾再 disable 会误停刚排好的 idle upgrade |

滚轮不是全部都能由 `_on_xrange_changed` 覆盖：Ctrl wheel 改 X range，Shift/plain wheel 只改 Y range。
因此 `_handle_wheel_dispatch` 自身也必须进入 interactive/off，然后在成功处理后重新排 idle。

### D. 游标策略（measured）

**Strategy A（默认）：游标移动不触碰曲线 AA。** `_handle_cursor_mouse_move`（`:1814`）保持原样，
不调 `disable_interactive_quality()`。AA 态由上一次 idle/交互决定并保持"黏"。效果：hover 读值时曲线
保持当前态（多为细腻），无糙↔细横跳，**零闪烁**。

唯一风险：`draw_idle()`→`_glw.update()` 在 AA on 时每 33ms 把曲线连带 AA 重栅格化。
**策略：A 默认先上，不靠离屏 benchmark 预判**——离屏 Qt 计时不代表真机渲染，本仓库铁律是
渲染流畅/闪烁只认真机。A→B 的决策放在真机验收（plan Task 9 step 4.4）：真机扫游标时若曲线
肉眼糙↔细闪、或扫动发粘/掉帧 → 才上 Strategy B；否则保留 A。离屏探针仅作可选的非权威提示。

**Strategy B（仅当 A 实测超标才启用）：`DeviceCoordinateCache`。** idle AA 开启时对曲线 item
`setCacheMode(QGraphicsItem.DeviceCoordinateCache)`，使 hover 重绘贴缓存位图而非重栅格化；
`disable_interactive_quality()` 时 `setCacheMode(NoCache)`（range/几何变化必须失效缓存，否则平移会糊）。
仍不关 AA，仍不闪。

### E. 线宽协同

`_overlay_default_lw = 1.7`（`pg_canvases.py:832`）→ `1.5`。纯视觉改动，缩小 off↔on 两态的视觉粗细差。
实现时同步更新旧视觉样式断言：原测试只要求线宽 `>= 1.6`，新设计应断言默认笔宽为 `1.5`。
最终以真机肉眼验收（off 不过粗、on 不过虚）。

### F. 密度门控（滞回）

度量：当前每条曲线 envelope 后的点数（`PlotCurveItem` 的 xData 长度）。阈值（初始，待真机调）：

- `_AA_DENSITY_ON = 4000`：开 AA 要求**每条**曲线点数 ≤ 4000
- `_AA_DENSITY_OFF = 6000`：已 on 时点数升过 6000 才在下次判定回到"拒绝"

实现：`try_enable_idle_quality()` 用 `_AA_DENSITY_ON` 判定开；记录上次决定，缓慢缩放穿越区间时用
两阈值避免边界 on/off 抖动。若任一曲线数据无法读取，密度门控 fail-closed，保持 AA off。注：envelope
通常把可见点压到接近像素列宽（~1500px→min/max ~3000 点），故绝大多数曲线可获 AA，仅在降采样关闭、
数据远密于像素或曲线状态不可判定时拒绝。

### G. 导出兼容

`_curves_antialiased()`（`:3329-3361`）保持不变：进入存当前值、退出还原当前值。
若 idle AA 已 on，prev=True，退出还原 True，不会被强制改回 off。idle AA 只是普通实时态，
导出路径既不依赖也不破坏它。

## 测试（TDD）

沿用 `tests/ui/test_pg_timedomain_canvas.py` 的离屏 Qt 模式。QTimer 异步不便等待，测试**直接调槽**
（`try_enable_idle_quality()`）触发，参照现有用 `_flush_pending_refresh()` 直驱的写法。

- `_set_curves_antialias(True/False)` 正确读写每条曲线 opts，不触发 setData。
- idle 槽通过门控时曲线 AA → on。
- range 变化（`set_xlim` + `_flush_pending_refresh`）后曲线 AA 立即 off。
- 鼠标按下时 idle 槽到期**不**开 AA（monkeypatch `QApplication.mouseButtons` 返回 LeftButton）。
- 鼠标按住导致 idle 槽被拒绝后，普通 `MouseButtonRelease` 会重新排 idle timer。
- `_overlay_dragging=True` 时 idle 槽到期**不**开 AA。
- Shift/plain wheel 这种 Y-only 滚轮交互也会立即 AA off，并在成功处理后排 idle。
- 游标高频移动（Strategy A）期间曲线 AA 态不被 move 改写（不出现反复切换）。
- 密度超 `_AA_DENSITY_ON` 或曲线数据不可读时 idle 槽到期**不**开 AA；滞回：on 阈值 ≠ off 阈值。
- replot 后曲线 AA off（保留并复用现有 `test_curves_are_not_antialiased_for_pan_perf` 语义）。
- `grab_pixmap()` 在实时 AA on 与 off 两种初始态下都能还原原值（扩展现有
  `test_grab_pixmap_restores_curve_antialias` @ `:1021`）。

## 范围外

- 全局永久 AA、OpenGL/全局渲染 backend、idle cached pixmap overlay。
- 不改 envelope、坐标同步、setData、ViewBox mouse mode。
- 不调 hit-test 半径、选中样式、grid、label（线宽是唯一视觉协同项）。
- 频域/阶次等数值路径。

## 验收标准

- 平移/框选/滚轮/overlay-Y 拖动过程中曲线 AA 恒为 off，手感不回退到历史卡顿。
- 停手 ~150–200ms 后静态曲线变细腻，且**只跳一次**、稳定不回弹。
- 游标移动期间无糙↔细横跳、无卡顿；鼠标静止时画面保持细腻（Strategy A）。
- 框选矩形不闪、不丢、不被 idle timer 干扰。
- 缓慢缩放穿越密度阈值时不出现 on/off 抖动（滞回生效）。
- 复制/保存仍高质量，且不会把实时 AA 状态永久改坏。
- 现有性能 marker（`tests/perf/test_timedomain_pan_perf.py`）p95 不劣化。
- 真机验证（必做）：4–5 通道（如 `tiaodamping`），分别验 subplot/overlay/单游标/双游标/框选/拖动/滚轮/复制，
  留两张截图（交互中 AA off、停手后 AA on）。

## 风险

- **最大风险在交互门控**：必须确保框选/拖动/overlay/游标连续操作期间不被 idle repaint 插入。
  Strategy A 把游标这块从"易闪区"直接移除（不触碰 AA），是本设计相对报告最重要的降风险动作。
- Strategy A 实测失败时落到 Strategy B；B 的 `DeviceCoordinateCache` 必须在几何变化时失效，否则 pan 会糊。
- 三个 timer（idle 150ms / 可见数据 40ms / 历史 debounce 180ms）次序：Home/Back 会"40ms 数据落定→150ms 后 AA on"
  两段式，属可接受范围，验收时确认无明显二次跳动。
