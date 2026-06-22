---
role: pyqt-ui
tags: [pyqtgraph, perf, narrow-y, raster-fill, time-domain, envelope, y-autorange, set-ylim, wall-guard, taxonomy, map, diagnosis]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

# 时域「满高竖线墙」: 系统性病根 / 触发分类 / 两层解法 (MAP)

## Context
pyqtgraph 时域渲染的「满高竖线墙」不是某个功能的孤立 bug，而是一个**系统性性能陷阱**：
一条密集(高采样率/宽带)曲线被画在**远小于其数据幅值的 Y 视窗**里时，min/max envelope
的每个 X 像素桶都贯穿整块画布高度 → 每列一根全高 AA 竖线 → 光栅 fill 成本爆炸
(Windows 真机十几秒)。本条是把多个触发口、病根与解法串起来的「地图」，细节见末尾各 lesson。
触发实例最早由滤波叠加暴露(小幅滤波线把共轴 Y 拉窄→原始撞墙)，但全局排查证明远不止此处。

## Lesson

### 病根 (两条结构事实)
1. **渲染热路径完全无 Y 感知**：`signal/_envelope_cutils.positions_envelope` 只吃 `xlim`+
   `pixel_width`(无 Y 参数)；`renderer._refresh_visible_data` 在 `setData(env_t,env_s)`
   前后**从不读 Y range**。所以"数据幅值 vs 视窗"无处被检查——墙必然形成且无人兜底。
2. **放大器**：时域轴默认 Y-autorange=ON，但**任何一次 `set_ylim`→`setYRange` 都永久关闭
   该轴 Y-autorange**(全仓 `disableAutoRange` 出现 0 次)。一旦窄 Y 被设上就**冻住**，
   后续 X-zoom 的 setData 不再重算 Y → 墙状态被锁死。

### 触发分类 (修法取决于"Y 窄是不是用户意图")
- **A 类 = Y 本不该窄 (根治 autorange，不是渲染层)**：小幅附加曲线(滤波 companion，未来
  stats/channel-math 同理)绑到大幅 primary 的同一 ViewBox，默认 autorange 按其小范围定了
  Y → primary 撞墙。**根治 = 把该轴 Y pin 到 PRIMARY raw extent + 在 Home/fit 循环里跳过
  companion**(否则 Home 后收成 ±0.025)。
- **A 残留 = 用户在别处设的窄 Y 被重新施加到一次全新密集重绘**：`restore_visible_ylims`
  跨切 view/分屏/改勾选/改时间范围；overlay `_repin_overlay_channel_ticks` 重锁当前 ylim。
  **这些 Y 是用户真实意图，不该改写语义**——只需性能兜底。
- **B 类 = 用户主动缩窄 Y 看细节**：滚轮 Shift+Y / box-zoom Y / overlay 拖拽 snap。墙在
  视觉上本就该存在，**只能缓解性能**。

### 两层架构性解法
1. **唯一系统性兜底点 = 渲染层守卫**(覆盖 A残留 + 全部 B 的**性能**)：所有触发路径最终都汇到
   `_refresh_visible_data` 那一次 `setData`。在此加"数据 extent vs Y 视窗"守卫：`data_span`
   从 envelope min/max **免费**得到、`y_span` 取 `get_ylim()`，`data_span/y_span>K(=4)` 即
   墙工况 → 封顶桶数(只降)+硬关 AA。**纯 display-only**：不改 Y/autorange/数据，只减竖线。
   两个坑：①y_span 必须**追加**进 refresh range key(否则纯 Y 变化命中缓存、守卫 no-op)；
   ②缓存命中要 OR 回 per-line wall 状态(否则 idle-AA 在墙上重新开)。
2. **靶向 autorange 根治**(只在 Y 真错处，即 A 类)：companion 那处已修。**别去"纠正"
   A 残留/B 的窄 Y**——那是用户意图，改了就是回归。
3. 第一道减桶仍是**静态密度**(overlay 通道数 / subplot decimation)——墙守卫叠在其上(只降不升)。

### 诊断铁律
**窄 Y 临时墙帧是 Windows 事件循环时序特有**：Mac(offscreen 与 cocoa)采样 paint 时 Y 往往
已是 primary 并集，**抓不到 paint-ms 差**。锁定修复靠**机制断言**(轴 `autoRange[1] is False`、
墙工况 displayed-pts 被封顶、`_idle_aa_density_ok() is False`)+ Mac 可复现的 Home 收窄回归，
真机 paint-ms 用保留的 `TRACELAB_PERF` 探针在 Windows 复测。**别信 Mac offscreen 的 paint 计时**
(grab() settle 后是缓存 blit ≈1ms，掩盖真墙；真重帧在事件循环后延后触发，须计 viewport.repaint())。

## How to apply
时域密集渲染卡顿，先问一句：**"这条曲线的数据幅值是不是远超它当前 Y 窗口?"** 是→就是墙。
然后判 A/B：**Y 是用户故意设的吗?** 是(B/A残留)→靠渲染层守卫兜性能、别动 Y；否(A)→去
autorange 来源(谁把 Y 定窄了)根治。**永远别把 Y-clip 当性能解**(实测 no-op：clip 数据空间
不减屏内全高竖线)。**永远别用 Mac offscreen paint 计时判这个问题**。细节实现见:
[[2026-06-22-companion-curve-shares-source-axis-not-new-row]](A 类根治+同轴虚线)、
[[2026-06-23-y-overflow-wall-guard-needs-y-in-range-key-and-cache-hit-state]](系统兜底守卫)、
[[2026-06-22-narrow-y-overlay-cost-is-stroke-count-not-data]](overlay 静态减桶)、
[[2026-06-23-subplot-dense-cap-must-hit-initial-bind-not-just-refresh]](subplot 静态减桶+首帧bind)、
[[2026-06-23-paintevent-hook-needs-class-level-override]](真机 paint 计时探针)。
