# 自制热图色表实施与验收

日期：2026-10-08。基线 HEAD：`875221db`，本次未提交。工作区原有热图色阶状态修复、FRF、Windows Lite 等修改已保留；不能把整个 `git diff` 当作本次改动。

## 交付结论

源码功能已完成。时频与时间–阶次默认色表为 `tracelab.head-style.v1`；显式保存的旧色表保留，没有 cmap 的旧状态采用新默认。未知 ID 在 GUI 中显示为不可用占位，暂用 gnuplot2 渲染并记录去重日志；无关编辑和保存不丢原请求。资源损坏不静默降级。

HEAD 的 256 个 RGB 与原 HTML demo 全部一致，哈希 `76035b39ed2f1223139896d983808146d89f21295f0db78a5c20e1057048d79d`；636 条来源 CSV 与 demo 的 raw 数组全部一致。来源等级仍为 **截图重建**，没有取得官方 LUT，官方精确等价为 **UNVERIFIED**。

色表目录、纯数据注册表、共享 Qt 适配、对话框稳定 ID、pane/View 项目恢复、GUI→Batch、目录打包、作者校验和预览工具均已接线。后续同格式色表添加 LUT、catalog 条目和来源说明即可。操作见 [维护说明](../colormaps/README.md)。

## 实际门禁

以下为独立命令结果；有交叠用例，不相加声称总数。运行使用项目 `.venv`，Qt 源码测试使用 offscreen，原生演练另用 Cocoa。

| 层次 | 范围 | 结果 |
| --- | --- | --- |
| 修改前 focused | colormap parity + Batch cmap 子集 | 8 passed, 74 deselected |
| 资源 / adapter | `test_heatmap_colormap_registry.py` + `ui/test_colormap_parity.py` | 60 passed |
| Batch / 打包源码 | heatmap、frozen render smoke、Windows Full/Lite/Modular 脚本四个 owner 文件 | 156 passed, 33 skipped（Windows 专属检查） |
| Batch 边界 | `test_batch_render_import_boundary.py` + `test_packaging_imports.py` | 13 passed, 1 skipped |
| GUI 对话框 / 接线 | dialogs + 新 colormap wiring（不含后加 shown 演练） | 67 passed |
| View/project/Batch 目标 | multiview 中 cmap focused 用例 | 11 passed |
| UI 约束 | state ownership、no-lambda、hints、color coordinator | 78 passed |
| 色阶独立性 | cmap-only、还原与 Batch 有效色阶 focused | 10 passed |
| 呈现 | retained/signature focused | 4 passed |
| Inspector 默认 | 共享默认参数用例 | 1 passed |
| 画布与导入整合 | `ui/test_pg_heatmap_canvas.py`、`ui/test_import_boundaries.py`、`test_signal_no_gui_import.py`、`test_native_import_boundaries.py` | 首次 228 passed, 1 failed；仅旧“默认 gnuplot2”断言失败。改为共享默认后该用例独立 PASS；其余无需重跑 |
| Batch 面板 / recipe | `ui/test_batch_toolbar.py -k colormap_survives` | 4 passed；HEAD/未知 ID × 两种方法，修改 NFFT 后导出重载保留 cmap，指纹对色表变化敏感 |
| 数据驱动扩展 | `test_heatmap_colormap_extension.py` | PASS；临时加第二份 LUT/catalog，在新进程里被 GUI 列表、图像、Batch 解析共同识别 |
| 默认修订 + 扩展 | 上面第二种色表测试 + 新默认单测 | 2 passed |
| Qt 像素 oracle | `ui/test_custom_colormap_pixels.py` | 8 passed；两种 Batch 图 × 四范围，与 GUI 图像、双方色条的 256 个 RGB 及越界端点逐项一致；数组不变 |
| 帮助 / 图像输出 | `test_help_content.py` + 色阶集成的 copy/export focused | 47 passed, 50 deselected；复制使用隔离图像接收器，PNG 和 UltraView 为真实 Qt 输出 |
| 作者预览 | `test_heatmap_colormap_preview.py` | 3 passed；正式数据嵌入、缺省 ID、未知 ID 拒绝写入 |
| 作者 CLI | 全目录 `--print-hashes`；预览生成；生成脚本 `node --check` | PASS；Validated 8 heatmap colormaps |
| Cocoa shown MainWindow | `test_shown_main_window_colormap_apply_restore` | 1 passed；实际 platform=cocoa |
| 文档 / 范围 | 链接与来源数据检查、`git diff --check`、lesson status | PASS；无需新增 lesson |

初次 adapter 测试捕获 native ColorMap 复制后 float/byte 语义改变，已改为保留完整对象语义的独立深复制；native golden 和 Batch 复测通过。未改变 native 原始 LUT。

## Cocoa 与输出的证据边界

Cocoa 演练启动真实 MainWindow、加载生产样式，以合成渐变检查 HEAD。实际点击图形页、应用和还原；通过画布接口切换 10～40、20～50、0～50；检查未知占位及只改标题仍保留 ID。截图已查看，保存在本地 `.state/colormaps-implementation/native-ui-final/test_shown_main_window_colorma0/`：

- `head-main-window.png`
- `head-chart-options.png`
- `unavailable-chart-options.png`

这是原生合成图演练，不是用户真实测量文件的端到端分析。项目重开、split/comparison、GUI→Batch 所有权为 offscreen 集成证据；OS 剪贴板、前台跨 View 操作和真实数据整流程未做原生验收。

Qt 像素测试检查 ImageItem 实际 QImage 和 ColorBarItem 实际 pixmap，预期直接取版本化 RGB，未通过共用 Qt mapper 生成 oracle。样本选择 256 个量化区间中心与上下越界，另由 adapter 测试覆盖样本间连续插值。屏幕缩放后的抗锯齿细节不在逐像素合同内。

Windows Full/Lite/Modular 已完成源码资源收集和预检接线。frozen smoke 源码子进程会校验全部自制 LUT 并生成 8 张 PNG，覆盖缺省 HEAD、显式 gnuplot2 和 turbo；本次 **未构建/启动新 Windows frozen 包**，三种实际包验收均 UNVERIFIED。

生成的单文件作者预览位于 `.state/colormaps-implementation/head-style-v1.html`。数据与 JavaScript 语法通过；本轮未完成浏览器视觉/交互验收。早先本地 file 导航被浏览器安全限制阻止，故未通过其他路径绕过限制；源码和 Qt 验收不代替浏览器验收。

## 计划矩阵结项

- C01～C09、C11、C15：以上列出的源码/offscreen 场景已验证；项目交互等原生范围以以上说明为准。
- C13：固定 v1 哈希、稳定 ID 和重复 ID 拒绝已验证；后续真实 v2 发布仍须比较发布基线，不能仅修改旧文件和旧哈希。
- C10：PNG、隔离复制和 UltraView 路径通过；OS 剪贴板和前台导出操作仍未验证。
- C12：源码 PASS，实际 Windows frozen UNVERIFIED。
- C14：截图重建来源已记录；官方精确匹配 UNVERIFIED。

未运行全量 suite，本次采用各 owner focused + 相关导入/状态边界；未提交、推送、发布或变更产品版本。基线范围、最终相关源码哈希和本地日志保存在 `.state/colormaps-implementation/`。

## 提交前隔离验证与显示名调整

用户随后要求移除产品界面的“截图重建”字样并提交。catalog、提示、速查和用户帮助的显示名统一为 **HEAD 风格**；稳定 ID、256 色 RGB 和元数据来源等级不变。

本记录前述集成结果来自含已有色阶状态修改的工作区。提交仅包含色图相关改动块，其他已有改动保留未暂存；为验证提交可独立使用，在 HEAD 上应用暂存内容，导出隔离目录测试。第一组资源、GUI、Batch、打包源码和帮助门禁 **421 passed, 33 skipped**。路由检查发现后台防串色依赖未提交的控制更新判断，已改为在 Batch 快照入口直接验证 section 和焦点 canvas；修正后隔离目录 focused **19 passed, 114 deselected**，原工作区兼容门禁 **4 passed, 158 deselected**。`git diff --cached --check` 通过。

原有色阶状态集成测试文件及其本轮小幅兼容更新仍保留在工作区，不混入独立色图提交。来源 CSV 统一为 LF，RGB 不变。此次是本地提交，不包含推送或 Windows 发布。
