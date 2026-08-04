# pg_canvas 切片子图独立与同构去重 · 设计(包 C)

- 日期:2026-08-04
- 基线:`main` @ `e385ce5a`(v7.9.3 + 通道表达式功能)。**本文所有行号以此 commit 为准。**
  (由 `6236a5fe` 更新;间隔仅一次 feature 提交 `6bda7ccb`,未触碰 pg_canvas,行号不变。)
- 来源:2026-08-04 全仓复杂度评审(pg_canvas 画布族结构探查)。
- 实施计划:[2026-08-04-pg-canvas-slice-panel-and-dedup-implementation.md](../plans/2026-08-04-pg-canvas-slice-panel-and-dedup-implementation.md)
- **前置:包 B(公共轴层)必须已合并**——本包多处依赖 `analysis_axes.py` 存在。

## 问题与收益

包 B 解决了「工具层住错文件」;本包解决剩下两类结构债:

1. **line/heatmap 双画布的逐字重复**:96 vs 99 个方法中同名 45 对,实测约 237 行
   完全相同(`_remark_item_at_viewport_pos` 44 行 100% 相同)。每条修复要写两遍,
   写漏一边就是不对称 bug。
2. **热图的切片子图与主图纵向耦合**:约 460 行切片逻辑(:1894-2351)+ 15 个
   `_slice_*` 字段散在 `PgHeatmapCanvas` 里,靠 `if self._slice_curve is not None`
   分散守卫。「切片相关」提交全部落在 3021 行的主文件。

## 风险分级(决定执行顺序)

| 子项 | 相似度/边界 | 风险 | 顺序 |
| --- | --- | --- | --- |
| C1 空态提示去重 | 3 对方法 0.78–0.90 相似 | 低 | 1 |
| C2 remark 视口层去重 | 44 行 100% 相同 + `_viewport_pos_to_scene` 5 行相同 | 低 | 2 |
| C3 分栏对齐去重 | 4 对方法 0.51–0.65 相似——**不是逐字相同** | 中 | 3 |
| C4 切片子图独立 widget | 边界清晰但体量大、纯 UI | 中高 | 4 |
| ~~滚轮派发统一~~ | 4 份实现行数 46/85/47/135 差异大 | 高 | **本包不做**(见附录) |

## 设计决策

**D-C1 · 空态提示 → `ui/pg_canvas/empty_hint.py`**

`line_canvas.py:703-758` ↔ `heatmap_canvas.py:1222-1277` 的
`show_empty_hint` / `clear_empty_hint` / `_reposition_empty_hint` 三件套提为共享实现
(建议模块级帮助类 `EmptyHintOverlay`,两画布组合使用;若两边差异行不可调和,
用参数吸收差异,**不许留分叉**)。两画布的公开方法名与签名不变(薄委托)。

**新增测试** `tests/ui/test_empty_hint.py`:parametrize 两个画布——显示后可见且
文本正确;清除后消失;resize 后位置跟随;重复显示不叠加。

**D-C2 · remark 视口层 → 并入既有 `ui/pg_canvas/remarks.py`**

`_remark_item_at_viewport_pos`(`line_canvas.py:2095` ↔ `heatmap_canvas.py:2734`,
100% 相同)与 `_viewport_pos_to_scene` 移为 `remarks.py` 的模块级函数
(显式收 canvas/viewport 参数);两画布保留薄委托方法。

**新增测试**:`tests/ui/test_pg_remarks.py` 目前仅 53 行 2 用例,扩充:
视口坐标命中 remark / 未命中 / 命中重叠时的优先级,parametrize 两画布。

**D-C3 · 分栏对齐 → 扩充既有 `_split_mixin.py`**

`prepare_split_layout_alignment` / `apply_split_layout_alignment` /
`reset_split_layout_alignment` / `_unify_stacked_left_axes`
(`line_canvas.py:1512-1592` ↔ `heatmap_canvas.py:2353-2454`)。相似度 0.51–0.65,
**必须先做差异审计**:逐行 diff 两边实现,把每处差异归类为
(a) 无意漂移——统一到正确的一边,(b) 真实的画布差异——参数/钩子吸收。
审计结论写进实施记录,不允许「看起来差不多就合了」。

守护:`test_stacked_left_axis_metrics.py`(293 行)、`test_subplot_left_axis_metrics.py`、
`test_axis_frame_alignment.py` + 真机分屏截图验收。

**D-C4 · 切片子图 → `ui/pg_canvas/slice_panel.py`**

新 widget 类 `HeatmapSlicePanel`,吸收:

- `_SliceDirToggle`(`heatmap_canvas.py:69-115`);
- 切片行为带(约 :1894-2351):方向切换、索引/量程、拖动、命中、面板定位、
  `_slice_visible_mask`、切片幅值域(dB 域逻辑已在包 B 的 `analysis_axes` /
  `_slice_amp_bounds`);
- `__init__` 中的 `_slice_*` 字段簇(约 :924-959,Task 0 精确盘点)。

**接口面(刻意收窄):** 输入 =(matrix, x_coords, y_coords, 轴标签/单位, 当前方向+索引);
输出 = `sliceMoved` / `sliceDirectionChanged` 信号 + 供主图对齐的几何查询方法。
`PgHeatmapCanvas` 保留全部既有公开方法/属性作为薄委托(外部消费者与测试零改动)。

**分两步走以保谨慎:** 先「类内聚拢」——把散落方法收拢成
`PgHeatmapCanvas` 内一个内部对象 `self._slice_panel`(行为零变化,委托全保留),
跑全量 + 真机验收;再「移出文件」成 `slice_panel.py`。任何一步红了都能小步回退。

**新增测试** `tests/ui/test_slice_panel.py`:方向切换后索引/标签正确;拖动命中
判定;越界索引钳制;`sliceMoved` 信号载荷;与既有 `test_slice_amp_floor_guard.py`
互补而不重复。

## 非目标

- 滚轮派发统一(见附录)。
- `canvas.py`(时域)不在本包范围;`plot_channels`(446 行)明确不动
  ——banner 注明 "frozen by W0 contract tests"。
- 批处理侧切片渲染(`batch_render_qt`)不动;其与 UI 侧的去重属批处理评审第三步。
- 不改任何用户可见行为;完成后 `/update-hints` 无需运行。

## 验收准则

1. 全套画布测试 + characterization 测试失败集与基线一致;四个新增/扩充测试文件全绿。
2. `PgHeatmapCanvas` 减少 ≥ 400 行;line/heatmap 之间逐字重复方法对
   (C1/C2 范围)归零。
3. C3 的差异审计文档存在且每条差异有归类结论。
4. **真机验收(必做,不可用 offscreen 替代):** FFT-Time 与 Order 图各一张,
   开切片(两个方向各试一次,拖动切片线),对照基线截图核对切片行几何、图例、
   幅值范围;分屏模式(C3)折叠/展开/拖动分隔条各一次。
5. 每个子项独立 commit 序列,可单独 revert。

## 附录 · 滚轮派发为什么本包不做

四份实现(`canvas.py:3627` 46 行 / `line_canvas.py:614` 85 行 /
`heatmap_canvas.py:1548` 47 行 / `overlay_axes.py:1317` 135 行)行数差异大,
说明各自积累了真实的分支差异(精密触控板、overlay 命中、分屏路由)。统一它们
需要先给四条路径各写一组 QWheelEvent 合成的接线 characterization 测试
(qtbot 合成事件 → 断言缩放/滚动路由),这本身就是一个独立包的工作量。
CLAUDE.md 也提示 7.9 的触控板缩放对称性是刚交付的行为,现在动它风险收益比不划算。
待画布族稳定后按需立项。
