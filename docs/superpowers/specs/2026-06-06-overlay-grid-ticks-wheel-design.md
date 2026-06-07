# 叠加模式：网格/刻度统一 + 纵向滚轮纠偏 — 设计

- 日期：2026-06-06
- 范围：`mf4_analyzer/ui/pg_canvases.py`（叠加渲染主体）、`mf4_analyzer/ui/chart_stack.py`（无选中提示）
- 状态：已与用户确认设计，待写实现 plan

## 1. 背景与问题

时域叠加模式（overlay）当前的纵向坐标体系由两套**互不通信**的机制拼成，导致两个可见缺陷。

叠加模式的实际结构（`pg_canvases.py`）：

- **X 主轴 ViewBox**：Y 锁定在 `[0,1]`，承载等距网格线。`_build_overlay_y_grid`（`pg_canvases.py:2043`）在 `k/_N_OVERLAY_DIVISIONS`（k=1..N−1）处放 `InfiniteLine`；`_N_OVERLAY_DIVISIONS=8` 写死于 `pg_canvases.py:160`。X 主轴是**唯一接管鼠标**的 ViewBox。
- **每通道一条独立 aux ViewBox + 独立 AxisItem**（通道1 左轴、通道2+ 右轴，`_add_overlay_axis_handle`，`pg_canvases.py:1439`）。各 aux ViewBox 有自己的数据 Y 范围（`get_ylim/set_ylim` 可用），并 `setMouseEnabled(x=False, y=False)`（`pg_canvases.py:1512`）——不抓鼠标。

### 问题 A — 网格密度与通道刻度对不齐

1. 网格 = **写死 8 格**，inspector 的 Y 刻度密度控件（`spin_yt`，范围 3–20、默认 6，`inspector_sections.py:1518`；信号 `tick_density_changed(int,int)`）**管不到它**。
2. 每通道轴刻度由 pyqtgraph 按各自数据范围算的"漂亮数字"，落点与 `k/8` 网格线**毫无关系**。

结果：8 条均匀网格线 + 各通道落在无关位置的刻度，永远对不齐，且调密度只动其一。

### 问题 B — 无选中时 shift+滚轮把网格缩没（真 bug）

`_handle_wheel_dispatch`（`pg_canvases.py:3782`）算目标轴：

```python
target = self._axis_handle_for_view_box(view_box) or self._primary_xaxis_ax
```

`_axis_handle_for_view_box`（`pg_canvases.py:3155`）**只在 `axes_list` 里找**，而 X 主轴不在 `axes_list`。因鼠标恒落在 X 主轴上，这里恒返回 `None` → 回退到 `_primary_xaxis_ax`，叠加模式下它正是 **X 主轴 handle**（`pg_canvases.py:1308`）。于是 `shift` 分支 `target.set_ylim(...)` **缩放本应锁死在 `[0,1]` 的网格坐标系** → k/N 网格线被压扁/移出 → "网格缩到没有"。

同源隐性 bug：无修饰键的普通滚轮（pan Y）平移的也是 `[0,1]` 网格窗口。叠加模式下整条**纵向**滚轮链路都打错目标，从没落到任何通道；只有 Ctrl+滚轮（缩放 X 时间轴）是对的，因 X 确实共享。

## 2. 目标 / 非目标

**目标**

1. 叠加模式下网格线与每个通道的刻度**天然重合**，且刻度标签是规整数。
2. 网格密度（分格数 N）由 inspector 的 Y 密度控件驱动，可调；默认比现状更密。
3. 纵向滚轮（shift 缩放 / 普通平移）在叠加模式作用于**选中通道**，X 主轴 `[0,1]` 永不被动；无选中时不响应并给一行提示。

**非目标**

- 不改 subplot / 单图模式的刻度算法与滚轮行为（保持现有自适应）；唯一外溢是 `spin_yt` 默认值 6→8（见组件 A），不动其算法。
- 不改 Ctrl+滚轮（缩放共享 X 时间轴）。
- 不改 FFT / 阶次等其他 canvas。
- 不引入新的 inspector 控件（复用既有 Y 密度 `spin_yt`）。

## 3. 设计

### 组件 A — 网格与刻度统一到「整步长 graticule」

核心思想：不让数据范围去等分屏幕（那样刻度值是任意小数），而是**每格选一个整步长（nice number），让网格线天然落在整数上**，数据被整刻度框住（允许少量留白）。多通道共享同一组 `k/N` 屏幕网格线，每个通道各自挑整步长，使其整数刻度全部钉在这组共享网格线上。

**整步长序列（细序列，限制留白）**

```python
_NICE_STEP_MANTISSAS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]  # × 10^k
```

**整步长选择**

```python
def _nice_per_div(raw):
    # raw > 0；返回 ≥ raw 的最小 nice number
    if not (raw > 0) or not math.isfinite(raw):
        return None
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    mant = raw / base
    for s in _NICE_STEP_MANTISSAS:
        if s >= mant - 1e-9:
            return s * base
    return 10.0 * base
```

**把任意目标窗口框成「整步长 + 网格对齐」**

给定目标窗口 `[lo, hi]` 与分格数 `N`，返回 `(bottom, top, ticks)`：

```python
def _frame_to_nice(lo, hi, N):
    span = hi - lo
    if not (span > 0):                      # 退化（平信号）：以 |中值| 或 1.0 造一个跨度
        c = (lo + hi) / 2.0
        span = max(abs(c), 1.0)
        lo, hi = c - span / 2.0, c + span / 2.0
    # 用 N-1 作分母：可证明 bottom 对齐到 per_div 网格后窗口必含 [lo,hi]
    per_div = _nice_per_div(span / (N - 1))
    bottom = math.floor(lo / per_div) * per_div     # ≤ lo，落在 per_div 整网格
    top = bottom + N * per_div                      # ≥ hi（由 per_div ≥ span/(N-1) 保证）
    ticks = [bottom + k * per_div for k in range(N + 1)]
    return bottom, top, ticks
```

含纳性证明：`top − hi = bottom + N·per_div − hi ≥ (lo − per_div) + N·per_div − hi = −span + (N−1)·per_div ≥ 0`（因 `per_div ≥ span/(N−1)`）。`bottom ≤ lo` 由 `floor` 保证。又因 `bottom` 是 `per_div` 的整数倍，所有 tick 都是 `per_div` 的整数倍 → 标签规整。

**应用点**

- `_N_OVERLAY_DIVISIONS=8` 常量 → 改为实例属性 `self._overlay_divisions`，**N 恒等于 inspector 的 `y_n`**（无偏移），初值 8。
- **为保证「控件数字 == 网格格数」一致**：把 `inspector_sections.py:1520` 的 `spin_yt` 默认值 **6 → 8**。否则首帧（用户尚未拨动控件）会出现控件显示 6、网格却 8 格的矛盾。这是本设计对 subplot 的唯一外溢——subplot 的 Y 主刻度默认数量随之 6→8，属良性轻微变化，刻意保留以维持单旋钮一致性。
- 新增 `_repin_overlay_channel_ticks()`：遍历 `axes_list` 每个通道 handle，取当前 `ylo,hi = handle.get_ylim()`，`bottom, top, ticks = _frame_to_nice(ylo, hi, N)`，`handle.set_ylim(bottom, top)` 并对其 AxisItem `setTicks([[(v, _fmt_tick(v)) for v in ticks], []])`。在「build 后 / 密度变更后 / 选中通道 Y 变更后（滚轮·拖拽 snap）」调用。
- `_build_overlay_y_grid` 改用 `self._overlay_divisions`，InfiniteLine 仍在 `k/N`（k=1..N−1，共 N−1 条内部线）。最上/最下两条 tick（k=0、k=N）落在绘图区上下边框处，由轴框充当最外网格，不额外画 InfiniteLine。
- `set_tick_density(x, y)`（`pg_canvases.py:2812`）：叠加模式下 `self._overlay_divisions = clamp(int(y),3,20)`，随后 `_build_overlay_y_grid()` 重建 + `_repin_overlay_channel_ticks()`，并**跳过**通用的 `_apply_tick_density_to_all_axes` 的逐轴 Y 密度路径（否则 pyqtgraph 自适应 Y 刻度会盖掉我们显式 `setTicks` 的整步长刻度）；X 刻度仍走 `_apply_target_x_ticks_to_all_axes`。subplot/单图完全保持现有逻辑不变。

留白预期：分母 N−1 引入约 `1/(N−1)`（N=8 时 ~14%）基础留白，叠加 nice 向上取整的余量；**典型填充 ≥ ~80%，最坏 ~70%**。要更紧/更密就把 inspector Y 密度往上拨（N 增大，基础留白随之缩小）。

### 组件 B — 纵向滚轮纠偏（X 主轴 [0,1] 永不被动）

改 `_handle_wheel_dispatch`（`pg_canvases.py:3782`）：在叠加分支里，纵向操作的目标**只能是选中通道的 aux 轴**，绝不回退到 X 主轴。

```text
叠加模式：
  Ctrl + 滚轮            → 缩放 X（共享时间轴）：维持现状，始终可用
  Shift + 滚轮（缩 Y）    → 选中通道存在 → 缩放该通道 Y（每格步长沿 nice 序列跳一档），
                            re-frame + 重钉刻度；X 主轴不动
                          → 无选中     → 不响应，发提示信号（见组件 C）
  普通滚轮（平移 Y）       → 选中通道存在 → 平移该通道 Y（一档一格，沿 per_div 步进），
                            re-frame + 重钉刻度；X 主轴不动
                          → 无选中     → 不响应，发提示信号
subplot / 单图：维持现状（target = 当前轴）。
```

落地：

- 叠加分支用 `self._selected_overlay_channel` / `_selected_overlay_axes()`（`pg_canvases.py:3763`）取目标，**不再**经 `_axis_handle_for_view_box(...) or _primary_xaxis_ax`。
- Shift 缩放：取当前 `lo,hi`，绕 `y_pos` 按 `factor`（现有 0.85 / 1/0.85）算新窗口，`_frame_to_nice` 重框，`set_ylim` + 重钉刻度。
- 普通平移：`per_div = (hi-lo)/N`，`set_ylim(lo + step*per_div, hi + step*per_div)`（一格/档），重钉刻度。
- 无选中：`return True`（吞掉事件，防止落回基类去缩放 X 主轴），并 `self.overlay_y_needs_selection.emit()`（新增信号）触发提示。

X 稳定性：所有纵向变更只动 aux 轴 `set_ylim`，与现有 `_apply_overlay_y_drag_at` 注释（`pg_canvases.py:3749-3754`）一致——aux 轴的 Y 改动不会扰动共享 X。

### 组件 C — 「先选通道」提示

- 在 `TimeDomainCanvasPG` 新增信号 `overlay_y_needs_selection = pyqtSignal()`，无选中纵向滚轮时发射（去抖，下文）。
- `_ChartCard` 连接该信号到新增槽 `flash_hint(text)`：把一行提示写入既有上下文提示条 `_hint_context`（`chart_stack.py:976` / `_set_context_hint`，`chart_stack.py:1169`），并启一个 ~2.5s 的 QTimer，到点后 `_set_context_hint(reset=True)` 还原轮播提示。提示文案：`先选中一个通道，再用 Shift+滚轮缩放纵向`。
- 去抖：canvas 侧对连续滚轮只发一次（记 `_last_overlay_hint_ts` 间隔门限，或 card 侧 timer 复位即可），避免刷屏。

## 4. 受影响代码清单

| 文件:符号 | 改动 |
| --- | --- |
| `pg_canvases.py:160` `_N_OVERLAY_DIVISIONS` | 删常量，改实例属性 `_overlay_divisions`（默认 8） |
| `pg_canvases.py` 新增 `_nice_per_div` / `_frame_to_nice` / `_fmt_tick`（模块级） | nice 步长与框定 |
| `pg_canvases.py` 新增 `_repin_overlay_channel_ticks` | 重钉各通道刻度到 k/N 网格 |
| `pg_canvases.py:2043` `_build_overlay_y_grid` | 用 `_overlay_divisions` |
| `pg_canvases.py:2812` `set_tick_density` | 叠加分支驱动 `_overlay_divisions` + 重建/重钉 |
| `pg_canvases.py:1287/1321` build 收尾 | 调 `_repin_overlay_channel_ticks` |
| `pg_canvases.py:3782` `_handle_wheel_dispatch` | 叠加纵向分支重写，新增信号发射 |
| `pg_canvases.py:2085` `_snap_overlay_channel_to_grid` | 松手吸附改为 `_frame_to_nice` + 重钉 |
| `pg_canvases.py:913` 信号区 | 新增 `overlay_y_needs_selection` |
| `inspector_sections.py:1520` `spin_yt.setValue` | 默认 6 → 8（保持控件数字与网格格数一致） |
| `chart_stack.py` `_ChartCard` | 连接信号 + `flash_hint(text)` |

## 5. 测试

**单测（headless，pyqtgraph 离屏）**

1. **刻度与网格重合**：叠加 N 格下，某通道 `_repin` 后，其 AxisItem ticks 的位置（值映射回 `[0,1]` 屏幕分数）== `k/N`（k=0..N），逐一相等（容差 1e−6）。
2. **标签规整**：框定后所有 tick 值都是 `per_div` 的整数倍；`per_div` 的尾数 ∈ `_NICE_STEP_MANTISSAS`。
3. **含纳性**：`_frame_to_nice(lo,hi,N)` 的 `[bottom,top] ⊇ [lo,hi]`，覆盖正/负/跨零/平信号/大小量级若干用例。
4. **无选中 shift+滚轮不动网格**：未选中时 `_handle_wheel_dispatch(modifiers=Shift)` 后，X 主轴 handle 的 `get_ylim()` 仍严格 `(0.0, 1.0)`；返回 `True`（已吞）；`overlay_y_needs_selection` 被发射一次。
5. **有选中 shift+滚轮只动该通道**：选中通道后 shift+滚轮，仅该通道 ylim 改变，其他通道与 X 范围不变（复用现有 X 稳定断言模式，参照 `tests/ui/test_pg_timedomain_canvas.py` / `tests/ui/test_chart_stack.py`）。
6. **密度联动**：`set_tick_density(_, y)` 改变 → 网格线数（`_overlay_grid_lines` 长度 == N−1）与每通道 tick 数（== N+1）同步变化。

**真机视觉验证（遵循"UI 必须看真实渲染"）**

- 叠加 2–3 通道，截图确认：网格线与左/右各通道刻度对齐、标签规整、填充不空旷。
- 无选中时画面内 shift+滚轮：网格不变 + 提示条出现"先选中一个通道…"。
- 选中某通道后 shift/普通滚轮：仅该通道纵向缩放/平移，刻度随之重钉且仍对齐网格。
- 拨动 inspector Y 密度：网格与刻度同步增减。

## 6. 风险与缓解

- **R1 离屏 ViewBox 几何退化**：`_frame_to_nice` 不依赖场景几何（纯数据坐标算），但 `_snap_overlay_channel_to_grid` 的 scene 映射在零尺寸时需保持现有静默 no-op 守卫（`pg_canvases.py:2118-2124`）。
- **R2 大/小量级标签过长**：`enableAutoSIPrefix(False)` 已设（`pg_canvases.py:1479`）；`_fmt_tick` 用紧凑格式（整数无小数、必要时科学记数），避免轴列变宽挤压。
- **R3 与现有 X 稳定测试冲突**：纵向只动 aux 轴，不碰 X；运行既有 `tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_chart_stack.py` 确认无回归。
- **R4 提示刷屏**：去抖（timer 复位 / 时间门限）。
- **R5 N 边界**：`spin_yt` 最小 3 → N−1≥2，`_frame_to_nice` 分母安全；代码侧仍 `clamp(y,3,20)`。
