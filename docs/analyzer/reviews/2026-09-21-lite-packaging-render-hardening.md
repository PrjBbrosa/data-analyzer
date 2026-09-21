# Lite 打包与导出渲染加固 — 源码实施记录

- 日期：2026-09-21。
- 计划：`docs/analyzer/plans/2026-09-21-lite-packaging-render-hardening-plan.md`
- 基线 HEAD：`5d7868f1961f580263e7ae4ef85a994bfeab6edb`
- 判定：**源码 Task 1–4 已实施；Lite 冻结验收与发布均为 NO-GO。** 本记录不是 Windows 包通过证明。

## 判定

| 检查 | 状态 | 说明 |
| --- | --- | --- |
| F3 像素所有权 | PASS（源码） | `_pixel_rgb_array` 返回自有 RGB 拷贝；空图 `ValueError` |
| F1 离屏可绘制字体 | PASS（macOS 源码）；Windows 冻结 UNVERIFIED | `ensure_app` 一次性加载可绘制 CJK 文件；本机 91 通过 |
| F2 导出 vs 屏幕 DPI | PASS（macOS 源码 + Cocoa） | 96 DPI 参考点大小；96/144/192 最大漂移 0.313 px；Cocoa `platformName==cocoa` |
| F4 布局门禁 | PASS（源码负例） | 重叠刻度 / 缺标题图例 / 非 PNG 均失败 |
| F5 Lite 导入接线 | PASS（脚本合同）；冻结 UNVERIFIED | prune 后独立跑 offscreen / windows / 四类导入 |
| `git diff --check`（本计划文件） | PASS | 无空白错误 |
| Windows Lite 新包 offscreen/windows/导入/DPI 矩阵 | UNVERIFIED | 本机是 macOS；工作树同时有项目保存等无关脏文件，未锁定快照、未重建 EXE |
| 虚拟机前台桌面 | UNVERIFIED | 未跑 |
| 原生 x64 Windows | UNVERIFIED | 不得用 ARM VM 或本机 macOS 替代 |
| Full 冻结 | UNVERIFIED | 本 Lite 任务不能代证 |
| 全量 pytest | 未跑 | 计划仅在发布/合并验收时跑；本轮不是 |

## 本计划源码范围

- `mf4_analyzer/batch_render_qt/_dispatch.py` `_theme.py` `_page.py` `_builder.py`
- `mf4_analyzer/qt_chart_fonts.py`、`mf4_analyzer/batch_render_smoke.py`
- `tools/verify_frozen_batch_render.py`、`tools/verify_lite_importer_runtime.py`、`tools/build_windows_folder_lite.ps1`
- `tests/test_batch_render_qt.py`、`tests/batch_render_export_dpi_child.py`、`tests/test_frozen_batch_render_smoke.py`、`tests/test_windows_build_script.py`、`tests/test_importer_runtime_smoke.py`

未改：`CHART_FONT_PT`、`_export.py` 先画后写 DPI、`_fonts.py` / `batch_render.py` 兼容层、版本号、`CLAUDE.md`、DSP、采集、项目保存。保留既有 PowerShell argv / native stderr 修复。

## 工作树边界

下列脏文件**不属于**本计划，不得并进同一冻结快照或同一提交：项目保存相关 UI/测试、`ssh-keygen`（私钥）、toolbar/help/user-guide、其它 lesson。Task 5 在这些文件仍在变时不得开始构建。

## 本机已跑门禁（均非冻结 EXE）

- `tests/test_frozen_batch_render_smoke.py`：Task 1 后 16 passed；Task 4 后随布局负例一并绿。
- Task 2：`tests/test_batch_render_qt.py` + frozen smoke + import boundary，91 passed。
- Task 3：batch_render_qt + SSAA + heatmap + FRF + import boundary + frozen smoke，217 passed；另一次 Cocoa 子进程。
- Task 4：frozen smoke + windows build script + importer + runtime deps + packaging + import boundary，71 passed / 12 skipped（Windows PS 5.1 原生）。

大体积 PNG、DPI JSON、构建日志在 `.state/lite-packaging-render-hardening/` 与既有 `.state/lite-review-20260921/`，不入库。

## 剩余 Windows 命令（Task 5）

在**仅含本计划改动**的稳定快照上，用常规 Lite 入口构建（环境已齐可用 `-SkipInstall`），然后在同一裁剪后 EXE 上跑 offscreen、windows、四类导入、DPI 矩阵；再在正常用户桌面做前台打开 / 导入 / 图表 / 一次 Batch 导出。原生 x64 未跑时继续标 UNVERIFIED。
