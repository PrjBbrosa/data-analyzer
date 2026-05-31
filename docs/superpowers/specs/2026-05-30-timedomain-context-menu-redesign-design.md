# TimeDomain 右键菜单重设计 + 复制/导出高清化

日期：2026-05-30
分支：`plan/pyqtgraph-timedomain-migration`
原型参考：[`docs/analyzer/ui-prototypes/2026-05-29-timedomain-context-menu-options.html`](../../analyzer/ui-prototypes/2026-05-29-timedomain-context-menu-options.html)（方案 A）

## 背景

当前 TimeDomain 画布的右键菜单是 **pyqtgraph 原生 ViewBox/PlotItem 菜单 + 一层中文 i18n**
（工作树未提交：`pg_canvases.py` 的 `_PG_CONTEXT_ACTIONS` / `_PG_CONTEXT_WIDGETS` /
`_localize_pg_context_menu()` / `_ModifierWheelViewBox.raiseContextMenu()`，约 +145 行）。
整套菜单不是为"看 MF4 时域信号"挑选过的，存在三类问题：

1. **大量项目与顶部工具栏重复**（查看全部=Home、鼠标模式=平移/框选、导出≈保存/复制）。
2. **高级/危险项混在主菜单**（变换/FFT/dy-dx/去均值、降采样、平均/透明度/点、关联轴）——
   FFT/变换尤其危险：会就地改变曲线含义，且应用已有专门的频域路径。
3. **说明 tooltip 浮在二级表单正上方挡住输入框**（`setToolTipsVisible(True)` @ `pg_canvases.py:166`）。

## 锁定决策（用户三轮确认）

| 决策 | 内容 |
|---|---|
| 整体风格 | 按原型**方案 A**（常用优先、浅色、圆角） |
| 高级功能 | **默认不显示，且不做折叠层**——直接从菜单移除，不保留三级 drawer |
| 导出图像菜单项 | **移除**（不在右键菜单出现；存图/复制走顶部工具栏） |
| 底部固定说明区 | **暂时不用**——因此浮动 tooltip 也一并关掉（顺带修掉遮挡 bug） |
| 鼠标操作 | **保留**，但**必须与顶部工具栏的平移/框选状态联动**，单一数据源、不冲突 |
| 实现机制 | **改造 + 美化原生 QMenu**（不自绘 popup）。底部 inline help 已砍，自绘的最大理由消失；原生路径更快更稳 |
| 新增：复制/导出高清 | 顶部工具栏的"复制为图片""保存图片"按更高分辨率渲染，接近 matplotlib 的清晰度；**但限定倍率保证快**，不拖慢使用 |

## 设计

### A. 右键菜单结构（保留原生 QMenu，做项目增删 + 重排 + QSS 美化）

一级菜单（仅保留用户能理解的动作）：

- **查看全部** — 回到数据全集（复用现有 `reset_view_to_data_extents`）
- **X 轴范围 ▸** — 二级复用 pyqtgraph 原生坐标轴表单：手动 min/max、自动 %、鼠标交互
- **Y 轴范围 ▸** — 同上
- **鼠标操作 ▸**（或一级动作）— 平移模式 / 框选缩放；**用工具栏的词汇命名**（不用"三键/单键"黑话），
  且选择项与工具栏状态双向同步
- **网格 ▸** — 显示 X 网格 / 显示 Y 网格

从菜单**移除**（不折叠、不保留）：

- 绘图选项 → 变换（Log X/Y、dy/dx、Y vs Y'、功率谱 FFT、去均值）
- 绘图选项 → 降采样 / 仅可见范围 / 最大曲线数 / 平均
- 绘图选项 → 透明度、点显示
- 坐标轴 → 关联坐标轴（Link Axis）、反转坐标轴（Invert，低频）
- 导出...（Export Dialog）

实现要点：在 pyqtgraph 生成菜单后，对 `vb.menu` / `pi.ctrlMenu` / `scene().contextMenu`
的 QAction 做**裁剪 + 重排**（移除上面列出的 action，把"网格"从 Plot Options 提升到一级），
而不是仅做翻译。保留并复用现有 i18n 字典中仍出现的条目翻译。

### B. tooltip 遮挡修复

关闭右键菜单的 action tooltip（`setToolTipsVisible(False)`，且不再给 action `setToolTip`）。
既满足"不用底部说明区"，又消除浮动 tooltip 挡住二级表单的 bug。

### C. 样式（方案 A 浅色观感）

在 `style.qss` 针对 `#pgContextMenu` 应用方案 A 的浅色主题（白底、浅边、行高、选中态浅蓝）。
圆角沿用现有 `WA_TranslucentBackground`（`pg_canvases.py:167`）+ QSS `border-radius`；
已知局限：原生 QMenu 外壳圆角在部分平台可能不彻底，接受此代价（用户已同意走原生路径）。

### D. 鼠标操作与工具栏联动

工具栏已有 pan/zoom 状态机（`PgNavigationToolbar`，`apply_current_mouse_mode` 经
`register_replot_callback` 重应用到重建后的 ViewBox，`chart_stack.py:678-685`）。
右键菜单的"鼠标操作"选择项必须：(1) 调用工具栏同一个 mode 设置入口而非各自为政；
(2) 打开菜单时勾选态反映当前工具栏状态。**单一数据源**，避免菜单与工具栏显示不一致。

### E. 复制/导出高清化（顶部工具栏）

现状均按屏幕像素抓图：
- 保存：`chart_stack.py:636 save_figure` → `canvas.grab_pixmap()` → `self.grab()`
- 复制：`chart_stack.py:1255` → `canvas.grab()`（并合成游标药丸 @ `:1271-1275`）

改为按**更高 scale 渲染场景**（pyqtgraph `exporters.ImageExporter` 设目标宽度，或放大 grab），
得到与屏幕 DPI 无关的清晰位图（matplotlib 当年清晰即因按 figure DPI 渲染）。约束：

- **限定倍率/目标尺寸**（约 2x，或目标宽 ~1920–2560px 封顶），保证导出快、不拖慢使用。
- 复制路径仍需合成游标药丸，药丸位置/尺寸按 scale 同步缩放。
- 保留 `grab_pixmap` 的退化 1×1 兜底与 `isNull()` 守卫
  （遵守 lesson `2026-04-25-tightbbox-survives-offscreen-qt`）。

## 测试（TDD）

沿用现有 `tests/ui/test_pg_timedomain_canvas.py`、`tests/ui/test_chart_stack.py` 的离屏 Qt 模式：

- 菜单结构：断言重排后一级菜单只含约定项、被移除项确实不在菜单中。
- tooltip：断言 `toolTipsVisible()` 为 False / action 无 tooltip。
- 鼠标操作联动：切换菜单项后工具栏 mode 状态同步（反之亦然）。
- 高清导出：断言 `grab_pixmap(scale)` 返回位图尺寸按倍率放大（几何断言，不比像素）。

## 范围外

- 不引入自绘 QFrame/QWidget popup。
- 不动频域/阶次分析等数值路径。
- 不做底部 inline help / 命令面板（方案 C）。
