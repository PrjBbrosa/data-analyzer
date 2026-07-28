# 批处理 Phase 3：导出质量与运行运维 Implementation Plan

> 前置：Phase 1/2 acceptance 全 PASS。renderer、core/manifest、drawer 三条 lane 按接口串行汇合；不允许多个 agent 同时修改 `batch.py`、`batch_render.py` 或 drawer 汇合文件。

> 执行状态（2026-07-28）：IMPLEMENTED；O1–O8、O10 PASS，O9 PARTIAL。正常取消、writer exception、manifest-proven resume 已通过；真实进程被强制终止后遗留的 reservation 采用显式检查/安全释放，不做可能误删其他进程产物的 TTL/PID 自动回收。

## Goal

交付精确高清/矢量输出、版本化 manifest、可控冲突、manifest-proven resume 与失败重试。

## Task 0 — Freeze output and manifest schema

- [x] 冻结 `BatchOutput` 新字段、默认值、image format/size/conflict/resume 枚举。
- [x] 冻结 manifest schema v1、task status 与 fingerprint/checksum 规则。
- [x] 为旧 preset 迁移写红测；对照 O1–O10 建 checklist。

## Task 1 — HD raster renderer

**Owner:** renderer agent；独占 `batch_render.py` 与 renderer tests。

- [x] 参数化红测 1920×1080、2560×1440、3840×2160、custom 的实际 PNG 尺寸。
- [x] DPI metadata 与像素尺寸分开设置；加入总像素/尺寸 guard。
- [x] 在 4K 下避免不必要 RGBA 副本，使用现有 matrix payload。
- [x] 零/常量/单 frame 极端图继续通过 Phase 1 regressions。

## Task 2 — SVG and PDF

**Owner:** 同一 renderer agent，Task 1 绿后继续。

- [x] 红测 SVG XML 可解析、文本/axis 元素存在且不是唯一 base64 PNG。
- [x] 红测 PDF 页数、MediaBox、非空内容。
- [x] 实现 format dispatcher；保留 GUI-free worker boundary。
- [x] heatmap 允许 rasterized artist，但 titles/axes/curves 保持矢量。

## Task 3 — Figure labeling

- [x] 为 FFT、FFT-time、Order、Time 各写 label snapshot/semantic tests。
- [x] title/subtitle/axis/legend 写入 source/group/channel/unit/method 和 effective facts。
- [x] dB label 只调用 shared formatter；Linear 不显示 reference。
- [x] 长标题 layout 测试保证 plot bounds 非零。

## Task 4 — BatchOutput migration and renderer integration

**Owner:** core agent；renderer API 冻结后独占 `batch.py`/preset IO。

- [x] 扩展 dataclass 与 JSON migration；旧 JSON 读取保持兼容。
- [x] runner 按 image_format/size/dpi 调 renderer，`BatchItemResult` 记录 artifact facts。
- [x] data-only/image-only/both 的 artifact count 与 task status 正确。

## Task 5 — Conflict reservation and atomic artifact set

**Files:** pure output helper + `batch.py` + tests.

- [x] 为 error/skip/overwrite/auto_number 写存在文件红测。
- [x] 实现 task-level coordinated basename reservation；data/image 使用同 suffix。
- [x] 全部格式继续 temp + atomic replace；overwrite 在成功前保留旧 final。
- [x] 模拟 write/render exception，断言无新 final 半文件且旧文件仍完整。

## Task 6 — Manifest v1

**Owner:** signal/core agent；TDD-first。

**Files:**

- Create: `mf4_analyzer/batch_manifest.py`
- Modify: `mf4_analyzer/batch.py`
- Tests: new `tests/test_batch_manifest.py`

- [x] schema/summary/task required fields 红测。
- [x] 实现 run/task recorder、requested/effective facts、streaming SHA-256。
- [x] 运行中写 `.partial` journal，terminal 原子写 final JSON。
- [x] done/failed/cancelled/skipped/resumed counts 从 entries 推导，避免双重计数源。

## Task 7 — Resume and retry

- [x] 红测 recipe/source/task/checksum 任一不匹配都重新运行。
- [x] 完整匹配的 done task 标 resumed，不 load/compute/render。
- [x] retry failed scope 只含 failed/cancelled；recipe 修改产生新 run 提示。
- [x] 模拟取消/writer exception 后从 partial/final manifest 恢复；硬进程终止后的残留 reservation 保持显式运维边界。

## Task 8 — Output operations UI

**Owner:** `pyqt-ui-engineer`；core public contract 绿后独占 drawer files。

**Files:**

- Modify: `ui/drawers/batch/output_panel.py`
- Modify: `ui/drawers/batch/sheet.py`
- Modify: `ui/drawers/batch/task_list.py`
- Modify: `ui/drawers/batch/runner_thread.py` only if public arguments change
- Tests: corresponding UI tests

- [x] Image format、size preset/custom、DPI、conflict、manifest get/apply round-trip。
- [x] 运行预览显示 task/artifact/conflict facts；估算明确标注。
- [x] 增加恢复 manifest、仅重试失败操作；运行期间 controls 锁定，`QThread.finished` 仍是解锁权威。
- [x] task list 支持 skipped/resumed/cancelled，unexpected worker error 不显示 done。

## Task 9 — Artifact and visual proof

- [x] 生成 1080p/4K PNG、SVG、PDF、manifest 样例到 `.state/batch-export-proof/`。
- [x] 用 Pillow/系统工具或等价 parser 验证 PNG；XML parser 验 SVG；PDF parser 验页数/尺寸。
- [x] 生成 BatchSheet offscreen 截图，确认 custom 控件与三列布局无裁切。
- [x] 完成 macOS Cocoa 前台 Retina 截图检查；与 parser/offscreen 证据分开记录。

## Task 10 — Final gate

- [x] 跑 Phase 3 focused command，再跑全部 batch/import/source tests。
- [x] 执行 4K image-only memory probe，确认没有回退到 long dataframe/pivot。
- [x] 取消/writer exception/resume 实物 probe；核对 manifest summary、checksums 和路径。
- [x] `git diff --check`，grep Qt-free boundary 和重复 extension/preset definitions。
- [x] 主 agent 对照 O1–O10 逐项 PASS/PARTIAL/FAIL；前台证据与 parser/offscreen 证据分开报告。

## Execution Record — 2026-07-28

- Core/source/renderer focused suite：`328 passed in 19.21s`。
- Batch UI 全组：`145 passed in 30.05s`；Phase 3 selected UI：`74 passed in 17.84s`。
- Source/import suite（排除与本变更无关的旧 rail contract 测试）：`121 passed, 1 skipped in 53.32s`。
- P0/P1 review regression：`15 passed in 2.79s`。
- 实物：1080p/4K PNG、SVG、PDF、CJK PNG、terminal manifest、resume/tamper-recompute run 均位于 `.state/batch-export-proof/`。
- 4K image-only probe：3840×2160，约 4.06 s，max RSS 351,305,728 bytes；对照 1080p max RSS 210,944,000 bytes。该证据证明当前路径保持 bounded/lazy，并非对底层 allocator “仅一份 RGBA”作形式化证明。

## Acceptance Result

| ID | 结果 | 证据/边界 |
| --- | --- | --- |
| O1 | PASS | PNG 实际像素和 DPI metadata 由 Pillow 解码验证 |
| O2 | PASS | SVG XML、PDF MediaBox/单页由独立 parser 验证 |
| O3 | PASS | 四方法 facts/label、effective NFFT、CJK fallback 回归通过 |
| O4 | PASS | error/skip/overwrite/auto_number 均有冲突测试 |
| O5 | PASS | 协调 suffix、temp+replace、外部替换所有权保护通过 |
| O6 | PASS | strict schema、derived summary、streaming checksum 通过 |
| O7 | PASS | recipe/task/source/checksum 全匹配才 resumed；tamper 会重算 |
| O8 | PASS | retry scope 仅 failed/cancelled，运行时状态不进入 preset |
| O9 | PARTIAL | 正常 cancel/writer exception/UI 解锁通过；硬杀进程的 stale reservation 需显式检查/安全释放，未做不安全自动回收 |
| O10 | PASS | file-major 单来源 lazy cache、image-only matrix 路径和 4K 实测通过 |

## Stop Conditions

- PNG 像素尺寸与 UI 选择不一致：不得宣称高清完成。
- resume 仅凭同名文件跳过：不得启用 UI 的“恢复”按钮。
- manifest 与 artifacts 不是原子/一致集合：不得把 run 状态标 completed。
