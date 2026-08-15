# View 切换的渲染质量结算（view-switch quality settlement）设计

> 状态：**设计定稿，未实施**。实施计划见
> `docs/analyzer/plans/2026-08-15-view-switch-quality-settlement-plan.md`。
> 探针脚本与**改前**真机基线（`main@380e5ac2`，macOS Cocoa，dpr 2.0，
> 1600×950）见 `docs/analyzer/verify/2026-08-15-view-switch-quality-probes/`
> ——本文所有数字均出自那里，能一键复跑。
>
> 起因是用户观察：「时域单文件每次切换 View 的时候是不是 AA 都要激活一次？
> 包括其他分析区用到 AA 的地方，来回切换都有点卡顿的感觉。」答案是：**是，
> 每次都重来；其中一半是结构性的、便宜且合理，另一半是三处缺陷**——本文
> 只治后者，不动前者。

## 0. 一句话

把「切换 View」从今天的「重建 → 半成品几何上测量 → 等 150 ms → 再判定 → 再画
一帧」改成**一次结算**：几何全部恢复后只刷一遍、只判一次、已知便宜的 View
首帧就是 AA；分析画布的 AA 从切换调用里挪到首帧之后，并像时域一样按 ink 判、
按实测帧兜底。目标不是让 AA 少激活——AA 判定本身 0.1 ms——而是**不做错的、
不做重复的、不让用户等**。

## 1. 问题（实测）

### 1.1 切换到底花在哪（产品路径，8 通道 × 1M 点，warm 中位）

| 场景 | 画布走的路径 | 切换调用 | 其中 |
|---|---|---|---|
| subplot ↔ subplot（全显） | `subplot-object-reuse`（对象复用，不 `clear()`） | **13 ms** | delta 2 ms · restore 1 ms · 控件 2 ms |
| subplot ↔ subplot（含隐藏通道） | 同上 | 13 ms | |
| overlay ↔ overlay | `new-channel` **全量重建** | 26–29 ms | `plot_channels` 13–16 ms |
| subplot ↔ overlay | `plot-mode-changed` 全量重建 | 27–33 ms | |
| 切走前在当前 View 里拨过 | UltraView 离场同步抓图 | +8–11 ms | `grab_pixmap` 5–7 ms |

再往下拆（画布级）：AA 判定调用 **0.1 ms**、ink 现场测量 **0.0 ms**、光栅缓存
flush 4–30 ms、AA 首帧 8 ms、稳态 AA 帧 8 ms。**质量决策不是成本**，重建也
只有十几毫秒。用户感到的「卡」来自下面三处，都不在这些数字里。

### 1.2 缺陷 A：全量重建的回切在 Y 恢复之前测量 ink（正确性）

`_view_mixin._render_view_to_canvas`（`_view_mixin.py:352-367`）的顺序：

```
plot_channels(defer_first_frame=True)   # Y 还是占位区间 [0, 1]
restore_visible_xlim(state.xlim)        # _restore_primary_xlim 内部同步 flush
                                        #   → _refresh_visible_data 在这里按
                                        #     axis.get_ylim() 算 ink（y_span = 1）
restore_visible_ylims(state.ylims)      # Y 到这一步才恢复；不触发重刷
```

ink 是「墨迹量 / y_span × 行高」，y_span 从真实的 ~220 变成占位的 1，于是：

| 场景 | 记录到的 ink | 真值 | 放大 |
|---|---|---|---|
| overlay 2ch，窗口 10%（产品路径实测） | 904 560 / 1 010 681 | ≈4 k | ~215× |
| subplot 8ch 全量重建 | 75 412… | 1 131… | ~67× |
| overlay 2ch，窗口 30% | 2 662 227 | 35 994 | ~74× |

三个后果，全部**不自愈**（事件循环空转 500 ms 仍原样，只有用户再拨一下画布让
range key 变化才重算）：

1. **envelope 分桶被 ink 降桶砍掉**（`renderer.py:655-681`）：绘点 3124 → 1404，
   曲线肉眼可见地变粗糙——这是**视觉回归**，不只是质量点颜色。
2. **AA 拒绝**：质量点红、tooltip「波形填满绘图区，绘制量超预算」——对一条
   0.3 Hz 正弦。这就是用户看到的「切回来 AA 没上」。
3. **误收进光栅准入集**（`_ink_raster_admitted`）：3ch 平滑 1M 点被判成
   `[dense-raster]`，每次切换白建一遍光栅图，向量 AA 永远不开。

**触发条件**：`state.xlim is not None`（切走时一定捕获，`view_bridge.py:126`）
**且**走全量重建的回切——overlay 模式一律全量重建（`new-channel` /
`overlay-topology-change`）；subplot 在通道顺序变化（`subplot-order-change` /
`subplot-insertion-order-change`）、轴分组或「显示原始/滤波」伴随线（复杂拓扑）、
render context 变化（范围/滤波/自定义 X）、两 View 布局不同、经过空 View 之后
（`no-render-model`）也会。subplot 全显、以及只用眼睛图标隐藏部分通道的
来回切走对象复用路径（实测 `subplot-object-reuse`），Y 保留自上次访问，恰好
没事——这解释了为什么问题「时有时无」。

对照实验（8ch，把 Y 恢复挪到 flush 之前）：ink 75 412 → 1 131，AA 关 → 开，
质量点红 → 绿，合计多 5 ms（就是真正把 AA 画出来的钱）。

### 1.3 缺陷 B：把离散渲染事件当成交互来处理（体验）

每次切换，无论复用还是重建，都是：`disable_interactive_quality()`（AA 掉、
`DeviceCoordinateCache` 清）→ 首帧非 AA → 150 ms 空闲计时器
（`quality.py:214`）→ `try_enable_idle_quality()` → AA 帧。150 ms 静默窗口
是给**连续交互**（拖动/滚轮）合并帧用的；View 切换是一次性的离散事件，之后
没有后续输入，这 150 ms 是纯延迟，外加一次肉眼可见的「锯齿→平滑」闪动。
光栅路径同理：`restore_visible_ylims` 把光栅重建推迟到 40 ms 后
（`canvas.py:2177`），中间先画一帧原生非 AA 描边再被光栅替换。

用户描述的「每次切换 AA 都要激活一次」正是这个：**机制上必须重判**（curve
item 被销毁重建、`reset_for_rebuild()` 清零迟滞状态，`quality.py:246-274`），
但**不必等 150 ms、不必先画一帧丑的**。

### 1.4 缺陷 C：分析画布的 AA 在切换调用里同步落地，且闸门不看成本

`PgLineCanvas.plot_spectra`（`line_canvas.py:1162`）和 `_plot_time_preview_entries`
（`line_canvas.py:2065`）以 AA-off 建曲线后 `if self._aa_on: _apply_idle_curve_aa()`
——`_aa_on` 空闲时恒为 True，所以切换的**首帧就是 AA 帧**，切换调用要等它画完。
`PgFrfCanvas` 更直接：曲线构造时 `antialias=True`，**没有任何闸门**。

谱行闸门按**点数**（`_SPECTRUM_AA_SEGMENT_ON/OFF = 5000/8000`），但峰值保持
之后每条曲线固定 ~1365 绘点，成本几乎与点数无关、只与**竖直墨迹**有关——
这正是时域 2026-08-08 spec 已经论证过的结论，`line_canvas` 上还没落实：

| 谱行 3 曲线，绘点固定 4095 | ink | AA 帧 |
|---|---|---|
| 纯噪声底（dB 视图常见） | 617 k | **1 652 ms** |
| 峰/底 = 10 | 212 k | 336 ms |
| 峰/底 = 40 | 67 k | 136 ms |
| 峰/底 = 200 | 20 k | 71 ms |
| 同图 AA 关 | — | 15 ms |

| FRF | AA 帧 | 非 AA 帧 |
|---|---|---|
| 2k bins 干净 | 14 ms | 6 ms |
| 2k bins 噪声相位/相干（低相干带的常态） | **527 ms** | 55 ms |
| 8k bins 噪声 | 2 540 ms | 442 ms |

`plot_spectra` 切换调用：AA 同步开 245 ms（其中首帧 227）vs 不开 25 ms。
ink 对谱行/FRF 是**单调可用**的成本预测量（上表 20k→71、67k→136、212k→336、
617k→1652 ms），但斜率比时域陡（时域带 OFF=300k 对应 ~250 ms；这里 150k 就到
250 ms）——**必须自标定，不能搬时域常量**。

### 1.5 顺带发现（不在本批）

- FRF 画布**没有 envelope 抽取**：32k bins 噪声相位非 AA 帧 4.1 s、AA 11.4 s。
  真实 FRF 通常 ≤4k bins，本批用 ink 闸门 + backstop 挡住 AA 那一半；非 AA
  的 4 s 是另一件事（相位翻转 ±180° 就是最大 ink），另立 spec。
- UltraView 离场抓图是一帧 AA 渲染（`renderer.grab_pixmap` 强制
  `_curves_antialiased`）：典型 5–7 ms，对「平滑对照」（1ch 1M，AA 帧 240 ms）
  会是 240 ms。它是 UltraView 的设计（UV-A18 必须同步抓）；记一笔，不动。
- `_view_signature()`（`quality.py:473-526`）不含 dpr：跨显示器拖窗口后
  黑名单键可能失配。本批 memo 键补 dpr，`_view_signature` 本身不动（它是
  2026-08-08 spec §4.4 定义的四输入）。

## 2. 目标与非目标

**目标**
- **G1 正确**：切换后 ink / envelope 分桶 / AA 判定 / 光栅准入全部按**最终几何**
  结算，与首次访问该 View 的结果一致（ink ±5%，绘点相等）。
- **G2 一次结算**：一次 View 恢复只做一遍 `_refresh_visible_data`（一遍
  envelope + ink）、一次光栅调度、一次质量判定。不再有「先按错的几何算一遍、
  用户动一下再算一遍」。
- **G3 丝滑**：切换调用里没有 AA 帧（时域本来没有；分析画布挪出去）；不再等
  150 ms；回切到**实测便宜**的 View 时首帧就是 AA（零闪动）；已知贵的 View
  不再白付一帧。
- **G4 鲁棒**：预测错了最多付一帧——实测 backstop 从时域扩到 line/frf；记忆
  有界 LRU、键含 dpr；不引入新旋钮（全部是标定值，改前先测）；不改交互路径
  的 150 ms 静默窗、ink 常量、`_view_signature`。

**非目标（明确不做，附理由）**
- 每个 View 各持一份画布实例（widget 换入换出）：内存 ×12，split / 光标 /
  UltraView 绑定全部要重做；而重建实测只有 13–33 ms，收益配不上代价。
- overlay 模式的对象复用（把 `_subplot_retained_*` 那套扩到 aux ViewBox）：
  省的是 13–16 ms 的 `plot_channels`，工程量大，等本批落地后看是否还感知得到。
- 光栅 pixmap 跨重建复用：行高随可见行数变，跨 View 命中率低。
- 分析画布的「首帧即 AA」记忆：先把同步 AA 帧挪走并加闸门；一帧的闪动
  作为后续可选项（§3.3 的 latch 已经把 memo 带上了，接线即可）。
- 时域 `plot_time` 的一般路径（勾选通道等）仍走 150 ms：连续勾选时静默窗
  确有合并价值；本批只把**View 恢复**认定为离散事件。

## 3. 设计

### 3.1 时域：View 恢复是一个事务

**现状**的每一步都各自「顺手」做收尾：`_restore_primary_xlim` 同步 flush、
`restore_visible_ylims` 各自调度光栅、`plot_channels` 尾部再武装 150 ms 计时器
（`canvas.py:1070-1074`）、`_try_apply_subplot_selection_delta` 再来一次
（`canvas.py:1456-1457`）、`_refresh_visible_data` 结尾还有一次
（`renderer.py:765`）。谁都不知道自己是不是最后一步。

**改法**：让 `_render_view_to_canvas` 显式声明「恢复到此结束」，画布在那一刻
统一结算：

```python
# _view_mixin._render_view_to_canvas（改后骨架，其余不变）
rendered = self._plot_time_on_canvas(canvas, ..., defer_first_frame=(state.xlim is not None))
canvas.restore_visible_xlim(state.xlim, flush=False)   # 只设 X，不 flush；标记 _refresh_pending
canvas.restore_visible_ylims(state.ylims)              # 设 Y；新增通道按已恢复的 X 拟合（不依赖 flush）
canvas.set_tick_density(...)
canvas.settle_view_restore()                           # ← 事务收尾，唯一的一次结算
```

```python
# canvas.py
def restore_visible_xlim(self, xlim, *, flush=True): ...
    # flush=False：_restore_primary_xlim 照常 set_xlim / 同步轴 item / 传播到 siblings，
    # 但把同步 flush 换成 self._refresh_pending = True。默认值保持 True，
    # 其他调用方（项目恢复、UltraView、测试）行为一个字节不变。

def settle_view_restore(self):
    """View 恢复事务收尾：最终几何上刷一次、光栅调度一次、质量判一次。"""
    if self._refresh_pending:                       # 首次访问（xlim=None、非 defer）不刷：
        self._flush_pending_refresh()               #   bind envelope 已是首帧，别重复算
    if self._dense_raster.has_dense_candidates():
        self._dense_raster.schedule_rebuild("view-restored", delay_ms=0)
    self._quality.settle_after_discrete_render()    # 见 3.2；必须在 flush 之后
```

为什么这样就对了：
- `_refresh_visible_data` 的 range key 已经折进了量化后的 y_span
  （`renderer.py:576-596`），所以只要 **flush 发生在 Y 恢复之后**，ink、降桶、
  光栅准入、`_line_ink_state` 全部按真实几何算一次——缺陷 A 的三个后果同时消失，
  而且比今天**少算一遍** envelope（今天是错的一遍 + 用户动一下后对的一遍）。
- `restore_visible_ylims` 对没存 ylim 的新增通道用 `_fit_channel_y_to_visible_x`
  拟合，它读的是 `handle.get_xlim()` 与原始 `channel_data`（`canvas.py:2182-2213`），
  不依赖 flush 过的 envelope——这就是为什么可以先 X（不刷）再 Y 再刷。
- `defer_first_frame=True` 时 `plot_channels` 已 `_arm_interaction_settle()`
  （40 ms，`canvas.py:1072-1074`）：即使调用方忘了 `settle_view_restore()`，
  40 ms 后也会按正确几何 settle——**自愈**，只是回到今天的时序，不会更糟。
- 顺序敏感点：`_flush_pending_refresh` 结尾会 `schedule_idle_quality()`（150 ms），
  所以 `settle_after_discrete_render()` 必须在它之后，才能覆盖那次武装。

对象复用路径（subplot 全显）同样受益：delta 里的 `disable_interactive_quality`
仍然需要（行高变了，`DeviceCoordinateCache` 必须清），但它之后的 150 ms 计时器
被 3.2 覆盖。

### 3.2 QualityManager：离散渲染结算 + AA 成本记忆

```python
# quality.py（新增，常量与 backstop 同一节）
_SYNC_AA_MAX_MS = 50.0        # 首帧直接开 AA 的实测成本上限（标定值，§5）
_AA_MEMO_MAX = _BACKSTOP_BLACKLIST_MAX

def settle_after_discrete_render(self):
    """一次 View 恢复的质量结算：不等 150 ms；已知便宜→首帧即 AA；已知贵→不白付。"""
    if self._idle_quality_locally_busy():          # 用户正拖着切（Alt+N）→ 交给正常路径
        self.schedule_idle_quality(); return
    if self._aa_backstop_blocked():                # 黑名单：不武装计时器，不付那一帧
        self.timer.stop(); self._emit_quality_status_changed(); return
    memo = self._aa_memo_lookup()                  # (signature, dpr) → 上次实测 AA 首帧 ms
    if memo is not None and memo <= _SYNC_AA_MAX_MS:
        self.timer.stop()
        self.try_enable_idle_quality()             # 闸门照查；通过就同步开 AA → 首帧即 AA
        return
    self.discrete_timer.start(0)                   # 未知/已知偏贵：下一轮事件循环判，不等 150 ms
    self._emit_quality_status_changed()
```

- **记忆写入**在 `_note_aa_frame` 的首帧分支（`quality.py:580-586`）：
  `aa_frame_memo[(sig, dpr)] = measured_ms`，LRU、上限 `_AA_MEMO_MAX`；backstop
  跳闸时同键从 memo 移除（负面进黑名单，正面出记忆——一个键在两边只能有一个）。
  和黑名单一样，memo **不随 `reset_for_rebuild()` 清空**——重建不改变
  「这个几何的 AA 首帧多少毫秒」这一事实。
- 比较的是**首帧**而不是稳态 EMA：重建后 curve item 是新的，
  `disable_interactive_quality` 也清了 `DeviceCoordinateCache`，切换后第一帧
  一定要付一次 cache 构建（spec 2026-08-08：平滑对照首帧 474 / 稳态 240）。
- 键含 dpr：`_view_signature()` 不动，memo 键 = `(signature, round(dpr, 2))`。
- **`discrete_timer` 是独立的 0 ms 单发 QTimer**，不是 `self.timer.start(0)`：
  `QTimer.start(int)` 会**永久改掉 interval**，之后 `schedule_idle_quality()` 的
  无参 `start()` 就变成 0 ms，交互路径的 150 ms 静默窗静默消失——这是 Qt 陷阱，
  测试要钉住 `timer.interval() == 150` 不变。`reset_for_rebuild` /
  `disable_interactive_quality` 同时 stop 两个计时器。
- 与现有机制的关系：闸门（`_idle_aa_density_ok`）一字不改——memo 命中只是把
  「什么时候判」从 150 ms 后提前到现在；黑名单继续是负面记忆；backstop 继续
  给「memo 过期」（换显示器、笔宽变化）兜底：同步开 AA 后首帧照样被 paint 计时
  器测量，>1000 ms 照样跳闸。

### 3.3 提取 `AaFrameLatch`（backstop 与 memo 的可复用状态机）

`quality.py:541-642` 的 epoch / 首帧-稳态 EMA / 黑名单 LRU / 延迟跳闸是纯
Python 状态机，只在回调处碰 Qt。把它提成 `ui/pg_canvas/quality_backstop.py::
AaFrameLatch`（构造参数：首帧上限、稳态上限、EMA α、LRU 上限；方法
`open(signature)` / `close()` / `note_frame(ms) -> trip | None` / `blocked(signature)` /
`memo_lookup(key)`），`QualityManager` 委托给它，**现有六个属性名
（`aa_backstop_epoch` … `aa_backstop_blacklist`）以 property 保留**，
`TestAaBackstopLatch` 一条不改。`install_frame_paint_timer` 的 owner 协议
放宽为：`owner._aa_backstop_armed` + `owner._note_aa_frame(ms)`（时域画布上转发到
`_quality`），这样 line / frf 画布装同一个 paint 计时器、用同一个 latch。

不这样做的代价是给 line / frf 各手写一份 60 行的「首帧超 1 s 就拉黑」——三份
标定过的状态机，AGENTS.md 与本仓 CLAUDE.md 都不允许（「不要再手写第二份」）。

### 3.4 分析画布：AA 落在首帧之后，按 ink 判，按实测兜底

对 `PgLineCanvas`（谱行 + 时域预览行）与 `PgFrfCanvas`（幅值/相位/相干三行）：

1. **离散武装**：`plot_spectra` / `plot_time_preview` / `set_result` 以 AA-off
   建曲线后，`_aa_on = False` 并 `discrete_timer.start(0)`（同 3.2 的独立 0 ms
   计时器；交互路径 `_aa_idle_timer` 150 ms 不动）。切换调用回到 ~20 ms；AA 帧
   在首帧之后落地。
2. **ink 闸门**：`_enable_idle_quality` 里在既有点数腿之外 **AND** 一条 ink 腿：
   `Σ envelope_ink_dev_px(curve.y, y_span=行 ViewBox 的 y 跨度, row_height_px=行高, dpr)`
   ——谱行对 `_amp_curves`、预览行对 `_time_curves`（各自 aux ViewBox 的 y 跨度）、
   FRF 对三行各自求和。双阈值迟滞，形状与 `_spectrum_aa_allowed` 一致；重建时
   重新播种。**读 y 跨度前先 `vb.updateAutoRange()`**：`enableAutoRange` 是懒
   应用的，0 ms 计时器可能跑在首次 paint 之前，不刷会拿到上一张图的 y 范围。
   常量按 §5 自标定；`quality_status()` 加 `high-ink` 理由分支（tooltip 说清
   「谱线填满绘图区」/「相位翻转填满绘图区」，不要沿用时域「波形」措辞）。
3. **实测兜底**：装 `install_frame_paint_timer`，`_note_aa_frame` 进 latch；跳闸
   → 延迟关 AA + 拉黑该画布的视图签名（谱行：曲线标签集 + 量化 y 跨度 + 行高
   + 像素宽；FRF：三行 y 跨度 + bins 数 + 显示参数）。

时域预览行**先试复用** `_INK_AA_ON/OFF`：它画的就是 `build_envelope` 出来的时
域包络，物理与 TimeDomain overlay 相同；标定探针同时报它的斜率，偏差 >2× 再
分家。

### 3.5 前后对比（一次回切，时域，全量重建路径）

```
今天    plot_channels(defer) ─ restore_x[flush ✗几何] ─ restore_y ─ 首帧(非AA,分桶已砍) ─ 光栅40ms ─ 150ms ─ 判定(✗ink) ─ (用户动一下) ─ 再flush ─ 150ms ─ AA帧
本文    plot_channels(defer) ─ restore_x(不刷) ─ restore_y ─ settle{flush ✓几何 · 光栅0ms · 判定} ─ 首帧(已是AA / 或 0ms 后 AA)
```

分析画布：`plot_spectra{建曲线 + 同步AA} ─ 首帧(AA, 70–1650ms)` →
`plot_spectra{建曲线} ─ 首帧(非AA, ~15ms) ─ 0ms ─ ink闸门 ─ AA帧(≤250ms) / 拒`。

## 4. 机械护栏（新增/更新）

| 守卫 | 位置 | 断言 |
|---|---|---|
| 恢复事务几何一致性 | `tests/ui/test_pg_timedomain_canvas.py::TestViewRestoreSettlement` | `plot_channels(defer)+restore_x(flush=False)+restore_y+settle` 之后每条线的 `_line_ink_state` 与「非 defer 建图 + 同几何」相等（±5%）、绘点相等、`_idle_aa_density_ok()` 相同、`_ink_raster_admitted` 相同 |
| 只结算一次 | 同上 | monkeypatch 计数 `_refresh_visible_data`：整段恢复恰好 1 次；首次访问（xlim=None）0 次 |
| 产品路径回切 | `tests/ui/test_view_switch_integration.py` | overlay 两 View 来回切后 `quality_status()["block_reason"] != "high-ink"` 且绘点等于首访 |
| 离散结算三分支 | `tests/ui/test_pg_timedomain_canvas.py::TestDiscreteSettle` | memo≤50 → 同步 `aa_on`、`timer` 未激活；黑名单 → 两个计时器都未激活；未知 → `discrete_timer` 激活且 `timer.interval()==150` 不变；`_idle_quality_locally_busy` → 走 150 |
| memo 生命周期 | 同上 | 首帧写入、LRU 上限、跳闸移除、`reset_for_rebuild` 不清、键含 dpr |
| latch 提取零回归 | `TestAaBackstopLatch` | 不改一行照过；`test_frame_paint_backstop_is_installed_on_real_canvas` 照过 |
| backref 归属 | `tests/ui/test_pg_canvas_backref_invariants.py` | 新增 `aa_frame_memo` / `discrete_timer` 进 `_owned_names`，写穿白名单不变 |
| line/frf 离散武装 | `tests/ui/test_pg_line_canvas.py` / `test_frf_canvas.py` | `plot_spectra` / `set_result` 返回时曲线 AA 全 off；`discrete_timer` 激活；`_aa_idle_timer.interval()==150` |
| line/frf ink 闸门 | 同上 | 合成噪声底（ink > OFF）→ 拒且 tooltip 含理由；峰主导（ink < ON）→ 开；点数腿仍生效（6 曲线拒） |
| line/frf backstop | 同上 | 喂 `_note_aa_frame(1500)` → AA 关、签名拉黑、再次 `_enable_idle_quality` 被拒 |
| lambda 棘轮 / 状态所有权 / 分层 | 既有 | 不许新增 lambda 连接；不许新增多文件写属性 |

## 5. 标定值（不是旋钮）

| 常量 | 值 | 依据 | 复测 |
|---|---|---|---|
| `_SYNC_AA_MAX_MS` | 50 ms | 首帧多付 ≤50 ms 在「点击→首帧」上不可感知（<100 ms 即时感），且远低于既有 `warm_checkbox_paint_p95=220`；本次实测典型 View 首帧 8–13 ms 命中、平滑对照 474 ms 落到两步路径——正是想要的分流 | `probe_view_switch_aa.py` |
| `_AA_MEMO_MAX` | 32（= 黑名单上限） | 同一理由：远超一次会话访问的签名数，LRU 淘汰 | — |
| 谱行 `_SPECTRUM_INK_AA_ON/OFF` | **95k / 145k**（2026-08-15 真机标定） | 7 点扫描（3 曲线、绘点恒 4095，只改峰底比）：55k→119 ms、120k→216 ms、212k→320 ms、336k→599 ms、520k→1165 ms、617k→1539 ms。近目标段（≤600 ms，n=4）拟合斜率 **1.68 ms/k·dev-px**、截距 9.0 ms，过 250 ms（`_BACKSTOP_STEADY_AA_MS`）于 143k → OFF 145k、ON=OFF×2/3=95k | `probe_view_switch_quality.py analysis-calibrate` |
| FRF 三行 ink 带 | **75k / 115k**（2026-08-15 真机标定） | 9 点扫描（bins 1k/2k/4k × 干净/噪声相位/噪声相干），三行 ink 求和。**不是一条直线**：噪声相位 1.44 ms/k、噪声相干 3.55 ms/k（2.47×，相干行 y 跨度恒钉 [0,1]，满行高笔画比同样 ink 的短笔画贵），故按最保守的全局拟合（3.21 ms/k、截距 −125 ms）取 250 ms 处 117k → OFF 115k、ON 75k | 同上 |
| 预览行 ink 带 | **复用 `_INK_AA_ON/OFF`（200k / 300k）**（2026-08-15 真机实测确认） | 6 点扫描（2/3/4 条包络 × Y 默认/拉窄填满）：31k→26 ms 到 144k→130 ms，拟合斜率 **0.93 ms/k·dev-px**、R²=0.995，对时域带隐含斜率（250 ms ÷ 300k = 0.83）只差 **1.12×** ≤ 2×，独立解出 OFF 275k 也落在 300k 同量级 → 不分家 | 同上 |
| line/frf backstop 上限 | 复用 1000 / 250 ms | 这是用户忍耐上限，不是画布物理 | — |

三行 ink 带的标定机器：macOS 27.0 (Darwin) / arm64 / Cocoa / dpr **2.0** / 画布
1400×900（谱行行高 669 px、预览行每条 131 px、FRF 幅值与相位行 296 px、相干行
255 px）；每档 ≥2 遍、每遍 3 帧取中位，AA 显式开/关而不依赖现有点数闸门；原始散点
与拟合见 `verify/2026-08-15-view-switch-quality-probes/` 的
`results/analysis-ink-calibration.{json,txt}`。两条**留给实施的告诫**：谱行在 ~350k ink
以上转陡（高墨段斜率 3.83 ms/k，全局拟合会把截距压成 −138 ms），所以带只在近目标
段标定、不要拿全局拟合外推；FRF「干净」构形 ink 恒为 2.5k 而帧随 bins 从 8.2 涨到
20.7 ms——**ink 腿必须与点数腿 AND**，单独一条 ink 腿管不住点数。

改任何一项：先改本节，再跑对应探针，再改代码。

## 6. 验收（真机 Cocoa，改后重跑 verify 目录全部探针）

| 项 | 改前 | 目标 |
|---|---|---|
| overlay 2ch 回切记录到的 ink | 904 560 | 与首访相等 ±5%（≈4 k） |
| overlay 2ch 回切绘点 | 1404（被砍） | = 首访（3124） |
| overlay 2ch 回切质量点 | 红「绘制量超预算」 | 绿「抗锯齿已完成」 |
| 3ch 平滑 1M 回切路径 | `[dense-raster]`（误收编） | 向量 AA，`_ink_raster_admitted` 空 |
| 回切到已知便宜 View | 首帧非 AA → 150 ms → AA | **首帧即 AA**（切换后第一个 paint 前 `aa_on==True`），切换调用 ≤40 ms（含 UltraView 离场抓图） |
| 一次恢复的 `_refresh_visible_data` 次数 | 1 + 用户动一下再 1 | 1 |
| `plot_spectra` 切换调用（3 曲线噪声底） | 245 ms | ≤30 ms；AA 帧被 ink 闸门拒（红点有理由） |
| 谱行 峰/底=200 | 71 ms 同步 | 切换 ≤30 ms + 0 ms 后 AA 帧 ≤100 ms |
| FRF 2k 噪声相位 | 527 ms 同步 | 切换 ≤30 ms；AA 拒或 backstop 一帧内拉黑 |
| `benchmark_timedomain_interaction --assert-standards` | 通过 | 通过（**门禁不放宽**） |
| 交互静默窗 | 150 ms | 150 ms（`timer.interval()` 钉住） |

## 7. 风险与回退

- **0 ms 计时器与首次 paint 的先后不保证**：先 paint 则用户看到一帧非 AA 再
  变 AA（今天是 150 ms 后才变，只会更好）；先计时器则首帧即 AA。两种都正确。
- **memo 过期**（换显示器 / 改笔宽）：键含 dpr 挡掉最常见的一种；其余靠
  backstop（首帧 >1000 ms 跳闸），代价一帧，与今天首次访问相同。
- **`flush=False` 调用方忘记 settle**：defer 路径的 40 ms `_arm_interaction_settle`
  自愈到今天的行为；非 defer 路径没有 pending 也就没有欠账。
- **split 双画布**：`_render_view_to_canvas` 对副栏同样走一遍事务，各自 settle。
- **测试假设「切换后是黄点」**：`test_view_switch_integration` 等若断言切换后
  `state=="yellow"`，要按新语义改成「绿或黄」，不是放宽——它们本来断言的是
  「没被错误拒绝」。
- **回退**：`restore_visible_xlim` 默认 `flush=True`、`settle_view_restore` 与
  `settle_after_discrete_render` 是新增入口，`_render_view_to_canvas` 改回三行
  即回到今天；line/frf 的离散武装用一个类常量开关回到同步 AA。

## 8. 与既有文档的关系

- `2026-08-08-timedomain-aa-ink-budget-spec.md`（ink 判据、AA 带、backstop）：
  本文**不改**其任何常量与 `_view_signature`，只是把它的四个消费者从「150 ms
  后」提前到「恢复结束时」，并把 §4.4 的兜底扩到分析画布。那份 spec 里
  「ink 表没记录过的曲线必须当场测量」在本文里变成「恢复结束时表里一定有记录」。
- `2026-07-26-plot-performance-standards.md`：本文新增的「切换调用 ≤40 ms /
  首帧即 AA」不进它的 Cocoa 门禁表（那张表是 TD-HDF-6 场景），以 verify 目录
  的探针 + 本文 §6 作为验收基线；等稳定两个版本再考虑升格。
- CLAUDE.md「机械护栏」：落地后补一条「View 恢复事务只结算一次 +
  `timer.interval()==150` 钉住」。
