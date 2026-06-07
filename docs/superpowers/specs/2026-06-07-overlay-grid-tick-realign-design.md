# 叠加模式：网格/刻度对齐修复（切换 + Y 自适应）— 设计

- 日期：2026-06-07
- 作者：Hang（与 Claude 根因分析后落地）
- 范围：`mf4_analyzer/ui/pg_canvases.py`（叠加渲染主体）、`tests/ui/test_overlay_grid_ticks.py`（回归）
- 状态：设计/计划待实施（本文已按当前仓库代码校准）

> 关联前序设计：`2026-06-06-overlay-grid-ticks-wheel-design.md`（网格/刻度统一 + 滚轮纠偏）确立了"k/N graticule + 每通道 aux ViewBox 框进网格"的体系；本 spec 修复该体系在**两条改写路径**上失守导致的对不齐。

---

## 1. 背景：叠加模式的对齐不变量

时域叠加（overlay）的纵向坐标由三层拼成（`pg_canvases.py`）：

- **X 主轴 ViewBox**（`_x_master_handle`）：Y 锁死 `[0,1]`，承载 `n-1` 条等距水平 `InfiniteLine` 作为**共享网格**（`_build_overlay_y_grid`，2515）。X 主轴**不挂任何通道曲线**，是唯一接管鼠标的面。
- **每通道一条独立 aux ViewBox + 独立 AxisItem**（`_add_overlay_axis_handle`，1880）。aux ViewBox 经 `scene().addItem` 直接加进**场景**（1898），**不进 Qt 布局**——其几何只能靠 `aux_vb.setGeometry(rect)` 手动设置（`_sync_overlay_aux_viewboxes`，4219）。
- **网格密度 `n`**：`_overlay_divisions`（3–20，默认 8），由 inspector 的 Y 密度控件驱动。

**对齐成立需同时满足三条：**

1. **几何一致**：每条 aux ViewBox 的屏幕矩形 == X 主轴 ViewBox 的屏幕矩形。
2. **范围整齐**：每个通道的 Y 范围是 `_frame_to_nice(lo, hi, n)` 算出的"整齐 n 等分框 `[bottom, top]`"。
3. **刻度钉死**：该通道的 `AxisItem.setTicks` 钉在那 `n+1` 个等分值上。

满足后，通道刻度落在屏幕 `k/n` 处，与固定网格线天然重合。

**既有路径都正确维护了这套不变量**：构建 `_repin_overlay_channel_ticks`(2565)、拖动吸附 `_snap_overlay_channel_to_grid`(2592) / `_animate_overlay_snap`、框选缩放 `_apply_overlay_box_zoom_y`(2709)、改密度 `set_tick_density`(3863) 都走了 `_frame_to_nice` + `setTicks`。

---

## 2. 问题与根因

### 问题 #3（确诊，代码级铁证）— 「Y 轴自适应」后刻度与网格错位

右键「Y 轴自适应」→ `fit_y_to_visible_x`(2395)。它对每个通道做的是：

```python
handle.set_ylim(lo - pad, hi + pad)   # 2454：原始数据 min/max + 5% pad
```

**它没调 `_frame_to_nice`，也没重钉刻度**——这是 `_frame_to_nice` 的四个调用点（2575/2761/4881/4910）里唯一漏掉的 Y 改写路径。

后果：通道 Y 变成任意 `[lo-pad, hi+pad]`，破坏不变量 #2；之前钉死的刻度随范围漂移、不再落在 `k/n`，破坏 #1 的视觉重合 → **刻度与固定网格线错位**。对照框选缩放 `_apply_overlay_box_zoom_y`(2758-2767)：同样改通道 Y，但它走了 `_frame_to_nice` + `set_ylim(bottom,top)` + `setTicks`，所以对齐。

> **根因**：`fit_y_to_visible_x` 在叠加模式下绕过了 graticule 重框，留下未对齐的范围/刻度。

### 问题 #2（时序，需用调用顺序测试锁住）— 分叠切换瞬间网格/坐标轴歪

切换模式 = `plot_channels` 整图重建（`_build`）。重建里几何同步发生在：

```
1688  _sync_overlay_aux_viewboxes()    # 把 X 主轴当前 sceneBoundingRect 复制给各 aux VB
1689  _connect_overlay_view_sync()     # 之后只挂 sigResized 兜底
...
1692  _apply_tick_density_to_all_axes()
1694  _repin_overlay_channel_ticks()
1699  _unify_subplot_left_axis_widths()
```

致命点：
- 第 1688 行同步发生在 tick-density 应用、overlay 刻度重 pin、bottom/left axis 几何整理之前；此时读到的是"当前" `sceneBoundingRect()`，但还没有一个显式的 build 末尾 layout settle 合同。
- `_unify_subplot_left_axis_widths` 在当前 overlay 路径会因 `_subplot_label_specs` 为空而早退；因此它**不是**本问题的直接证据。真正需要修的是：overlay aux 是 scene item，不能依赖早期同步或后续 `sigResized` 自愈，必须在 build 尾部显式 settle 后同步一次。
- 兜底只有 `sigResized`（4252）；`resizeEvent`(5356) 与 `_on_resize_settled`(5388) **都没有**调 `_sync_overlay_aux_viewboxes`。

结果：网格画在 X 主轴上几何始终正确，但通道曲线/右轴在 aux VB 上，aux 几何对不上 X 主轴 → 曲线坐不到网格上、右轴刻度与曲线错位 = "切换瞬间歪了"。

> **根因**：aux ViewBox 几何同步在 `_build` 中过早执行，且缺少"全部 axis/tick 几何操作完成后，强制 GraphicsLayout settle，再按 X-master 最终 rect 同步 aux"这个明确合同；唯一兜底 `sigResized` 不覆盖首帧和 resize-settle。
>
> 本仓库经验 `docs/lessons-learned/codex-pg-subplot-layout-settle.md` 记录的正是同一类故障，其既定修法即"在改 AxisItem 几何的晚期操作后，强制 GraphicsLayout `invalidate()` + `activate()`，再判定首帧几何对齐"。

---

## 3. 目标 / 非目标

**目标**

1. 分叠切换（subplot↔overlay、overlay→overlay）后，**首帧**每条 aux ViewBox 几何即与 X 主轴一致（不靠后续事件 pass 自愈）。
2. 「Y 轴自适应」后，叠加模式下每通道刻度仍落在 `k/n` 网格线上、标签是规整数。
3. 窗口 resize 稳定后，aux 几何可靠重同步（补 `sigResized` 之外的兜底）。

**非目标**

- **问题 #1（抗锯齿"有时"失效）不在本 spec 范围**。经核实它是 `_idle_aa_density_ok`(5530) 的**故意密度门控**：叠加度量 = 全部曲线绘制点数之和，预算 `ON=5000 / OFF=7000`（206 行）；密集多通道叠加超预算 → AA 被关，是 CPU 光栅性能权衡，非 bug。是否放宽预算/换渲染策略另议。
- 不改网格密度模型、不改 `_frame_to_nice` 数值算法、不动鼠标/滚轮链路。
- 不重构 `_unify_*` 既有 subplot 路径。

---

## 4. 设计

### 4.1 修复 #3 — `fit_y_to_visible_x` 末尾在叠加模式重框

`fit_y_to_visible_x`(2395) 的逐通道 `set_ylim` 循环**保持不变**（它先把每个通道拟合到可见窗口的真实数据 min/max+pad，这是"自适应"语义所需）。在 `self.draw_idle()` 之前、叠加模式下追加一次 `self._repin_overlay_channel_ticks()`：

- `_repin_overlay_channel_ticks`(2565) 读每个 handle 的**当前** ylim → `_frame_to_nice` 框成整齐 n 等分 → `set_ylim(bottom, top)` → `setTicks(k/n 值)`。
- 即把刚才的"原始拟合范围"再规整到 graticule，恢复不变量 #2 #3。
- 复用既有、已被测试覆盖的代码路径，与 `set_tick_density`(3863-3866) 同款，零新算法、低风险。
- subplot/single 模式不调用（保持原始拟合，无 graticule）。

网格本身固定在 `k/n` 不随通道范围变，无需重建，故只需重 pin 刻度/范围。

### 4.2 修复 #2 — aux 几何同步挪到 `_build` 真正末尾 + 强制 settle

**(a) 抽取 settle 辅助（DRY）**：新增 `_settle_layout()`，封装既有重复出现的
`self._glw.ci.layout.invalidate(); self._glw.ci.layout.activate()`（try/except 包裹）。
新调用点复用它；为控制风险，**不改动** 5296/5347 两处既有 subplot 调用（可作为后续清理）。

**(b) 几何同步移到 `_build` 末尾**：
- 第 1688 行的 `_sync_overlay_aux_viewboxes()` 删除（`_connect_overlay_view_sync()` 保留在原处——它只连信号、依赖的 `_primary_xaxis_ax`/`_overlay_aux_viewboxes` 此刻已就绪）。
- 在 `_build` 最末尾、`_apply_tick_density_to_all_axes()` / `_repin_overlay_channel_ticks()` / `_unify_subplot_*()` **之后**、`_run_replot_callbacks()`(1704) **之前**，叠加模式下追加：
  ```python
  if self._overlay_mode:
      self._settle_layout()              # 强制布局 pass，X 主轴拿到最终几何
      self._sync_overlay_aux_viewboxes() # 按最终几何对齐所有 aux
  ```
  放在 `_run_replot_callbacks` 之前，使回调（重置工具栏 pan/zoom 交互态）看到正确几何。

**(c) resize 兜底**：在 `_on_resize_settled`(5388) 内、`_apply_target_x_ticks_to_all_axes` 一带，叠加模式下追加 `self._sync_overlay_aux_viewboxes()`，使窗口缩放稳定后 aux 几何可靠重同步（`sigResized` 仍保留为实时兜底）。

`_sync_overlay_aux_viewboxes`(4219) 本体**不改**（保持只读 rect + setGeometry），避免在 `sigResized` 处理器内 `invalidate/activate` 引发重入。强制 settle 只在 `_build` 末尾与 resize-settle 这两个**布局 pass 之外**的时机做。

---

## 5. 验证（先证伪假设，再判修复）

按系统化调试，#2 属时序假设，回归测试既是证据也是护栏。

- **#2 调用顺序合同（先红后绿）**（`test_overlay_build_syncs_aux_after_tick_density_layout_work`）：monkeypatch `_apply_tick_density_to_all_axes` 设置 `density_applied=True`，monkeypatch `_sync_overlay_aux_viewboxes` 记录调用时该 flag。当前代码只记录 `[False]` → FAIL；修复后早期 sync 删除、末尾 settle+sync 记录 `[True]` → PASS。这个测试比像素差异更稳定，因为 offscreen 下当前代码可能已经落在 1px 容差内。
- **#2 几何 smoke**（`test_overlay_switch_aux_viewboxes_match_xmaster_after_build`）：subplot 建图 + `processEvents` → 切 overlay → 断言每条 aux ViewBox 的 `sceneBoundingRect()` 与 X 主轴在 1px 内一致。该用例验证最终行为，但不要求修复前必红。
- **#2 resize 兜底**（`test_overlay_resize_resyncs_aux_viewboxes`）：overlay 建图稳定 → `canvas.resize(...)` → 直接调 `canvas._on_resize_settled()` → 断言 aux 与 X 主轴几何一致。
- **#3 自适应后对齐**（`test_fit_y_to_visible_x_keeps_overlay_ticks_on_grid`）：overlay 建图 → `fit_y_to_visible_x()` → 断言每通道 major 刻度的 `(value-lo)/(hi-lo)` 序列 ≈ `[k/n]`。当前代码会复用旧 ticks 配新 ylim，fraction 偏到 `0..1` 之外，能稳定先红；修复后镜像 `test_each_channel_ticks_align_to_divisions`(140)。
- **#3 不污染 subplot**（`test_fit_y_to_visible_x_subplot_unchanged`）：subplot 模式 `fit_y_to_visible_x` 行为与现状一致（不调 graticule 重 pin）。

全部用 `tests/ui/test_pg_timedomain_canvas.py::_pg_canvas` 夹具与 offscreen Qt；命令用 `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`。

---

## 6. 风险

- **几何在 offscreen 下可读性**：`_pg_canvas` 已 show+resize+processEvents，既有测试用 `mapViewToScene`/几何均成立。强制 `activate()` 后 `sceneBoundingRect()` 有效。
- **重入**：强制 settle 仅在布局 pass 之外调用；`_sync_overlay_aux_viewboxes` 本体不触发 settle，`sigResized` 兜底不会递归。
- **行为面**：#3 改后"Y 自适应"会把数据范围微扩到下一个 nice 边界（与框选缩放一致的取整观感），符合叠加 graticule 既定风格。

---

## 7. 实施约束

属 UI 子系统改动 → 按 `CLAUDE.md` 走 squad runbook，由 **pyqt-ui-engineer** 实施；TDD（先红后绿），改完按"Verify UI visually"经验做一次真机/截图复核切换与自适应两条路径。
