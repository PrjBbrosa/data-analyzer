# UltraView P2-B 单卡检查能力审计

- 日期：2026-08-14
- 判定：`NO-GO（本轮不实施 live inspection）`
- 范围：P2-B 的单卡可交互 canvas；不影响 P0 已有的静态预览放大。

## 结论

P2-A 的自由网格可以安全交付，因为它只操作 `UltraViewRef`、整数几何和已有
`PreviewStore` 图像。P2-B 不应在当前代码上通过“借用源 canvas”或“按缓存重画”实现。
这两条路径都违反 UltraView 的只读、零计算边界。

| section | 现有可读事实 | 独立 document seam | P2-B 判定 |
|---|---|---|---|
| time | `TimeDomainCanvasPG.plot_channels()` 依赖 live View 配置/源通道 | 无 | NO-GO |
| fft | `PgLineCanvas.plot_spectra()` 有 renderer，但 document 由 cache + ViewState 组装 | 无；现有 `_render_analysis_view_from_cache()` 会参与 restore | NO-GO |
| fft_time / order | `PgHeatmapCanvas.plot_result()` 持有 result，但 display 参数、slice 状态和数据所有权未抽成不可变 document | 无 | NO-GO |
| frf | `PgFrfCanvas.set_result()` 需要 result、display params、context | 仅局部，未形成 section-neutral document/lifecycle | NO-GO |

## 阻断证据

1. `mf4_analyzer/ui/main_window/_analysis_mixin.py:_render_analysis_view_from_cache()` 对
   `_analysis_restore_pending` 会安排重算；项目刚重开时调用它违反“检查不可补算”。
2. 当前 renderer 的输入由源 View 的 active/focused pane、live widget 状态和 cache 共同
   拼装；不存在按 `(section, view_id)` 只读取得的 immutable `InspectionDocument`。
3. 将现有 `PgLineCanvas` / `PgHeatmapCanvas` / `PgFrfCanvas` 直接 reparent 到 Board 会使
   source View 生命周期和工具窗关闭路径不再可证明安全。

## 当前产品行为

- 卡片“临时放大”继续显示已有 QImage，任何 section 可用，不调用分析计算。
- 需要 pan/zoom/cursor 或修改参数时，用户点击“打开原 View”。
- P2-A 自由网格、布局、导出、minimap、保存/恢复不以 inspection 为依赖。

## P2-A Remainder 欠账（本轮不实施，记录在案）

下列 P2-A 项未做，也不是 P2-B 的 blocker。产品继续用现有入口，不假装已交付：

1. **A04 ghost / resize handle**：没有 drag pixmap、overlay、角点 handle；resize 只有 Alt+Shift 拖与键盘。
2. **A05 同尺寸 swap**：碰撞即拒绝并 toast，不会把两张同尺寸卡对调。
3. **A15 分页 PNG**：导出有 `MAX_EXPORT_EDGE` / `MAX_EXPORT_PIXELS` 前置拒绝；不做分页 PNG。
4. **A17 24 图 benchmark**：无 Cocoa 真机 JSON；offscreen 不代替。
5. **A16 零计算探针扩展**：Board 增删改排已纳入 job isolation；更长 50 次 lifecycle 未加。
6. **A18 帮助页**：`ultraview-guide.html` 已补 Board / 自由网格 / 12 列 / 24 卡；不写 sidecar 实现细节。

## §11 兼容轴 guide 裁剪

P2 spec §11 的 inspection 兼容轴 guide（`plot_content_rect_norm` / `x_transform`）
随 P2-B 一并 NO-GO。sidecar `SIDECAR_FORMAT` 仍为 1，不写入这些字段。
当前没有 live inspection，因此没有 guide 可禁用。

## 后续重新开启 P2-B 的前置条件

1. 新增 Qt-free / immutable `InspectionDocument`，必须由稳定 `(section, view_id)` 取得；
2. 各 section presenter 只能消费该 document，不能调用 cache restore、`do_*` 或 source
   QWidget；
3. 新建单 session 生命周期测试：Board 切换、项目重开、源删除、关闭工具窗和延迟回调；
4. 对新开项目且 `_analysis_restore_pending` 非空的全 section 场景，证明零 job/零 cache 写；
5. document 不可用时，明确禁用并显示“仅有图片预览；打开原 View 进行交互”。
