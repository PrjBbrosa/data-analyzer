# UltraView P3 画布交互验收

- 日期：2026-08-14
- 分支：`codex/ultraview-p1-p2`
- 实现收口：Task 9 `84e38391`；本文为 Task 10
- Spec：`docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
- Plan：`docs/analyzer/plans/2026-08-14-ultraview-p3-canvas-interaction-implementation.md`
- 产品版本：`mf4_analyzer/app_meta.py` `APP_VERSION` = **v7.9.9**（本包不升版）

offscreen 只当排版/契约草稿。UV-P3-A07 / A08 的帧时与 pinch 到达率**未仪器化**，
不以 offscreen 数字替代 Cocoa。

## 里程碑

| 里程碑 | 状态 | 证据 |
|---|---|---|
| P3-0 遗留 | **完成** | `fc87da9a`；digest characterization、destroyed 重连、影子缓存、扩容回填 |
| P3-1 直接操纵 | **完成** | `docs/analyzer/verify/2026-08-14-ultraview-p3-1-direct-manip.md`；操作者 Cocoa 确认 |
| P3-2 视口变换 | **完成**（操作者确认，无仪器化帧时） | 本文件 + `docs/analyzer/verify/2026-08-14-ultraview-zoom-spike.md` |

## 实现提交（Task 0–9）

| Task | 提交 |
|---|---|
| 0 spike 脚本 | `d7e1d687` |
| 1 P3-0 遗留 | `fc87da9a` |
| 2 直接操纵移动 | `b01f96af` |
| 3 resize handle | `623e829e` |
| 4 替换环 / 模板拖卡 | `c940d542` |
| 5 框选与组平移 | `28f91422` |
| 6 发现性面 | `526c9302`（当时 Cocoa 未测，不宣告 P3-1） |
| 7 zoom/pan 核心 | `f7567344` |
| 8 fit / LOD / zoom-to-card | `ecf6780a` |
| 9 FOCUS + viewport 持久化 | `84e38391` |

## 产品裁决落地

| 裁决 | 落地 |
|---|---|
| D1 模板+自由网格；拖=移动；占用槽=交换 | 保留；布局路径离开 QDrag |
| D2 viewport 持久化、digest 外 | payload `viewport: {zoom, center_x, center_y}`；`board_identity_payload` 不含它 |
| D3 库/托盘悬停 ≥0.6s 替换环 | 保留 QDrag 跨容器 |
| D4 `set_layout` 托盘回填 + toast | P3-0 已收口 |

**整板概览保留**：fit 档位不能替代 overview 点卡片跳转（Task 8 验证后按 plan 保留）。
FocusLayer 仍为「临时放大」/ Enter 兼容路径，验收后再单独裁撤。

## Offscreen 契约（不可替代真机）

命令前缀：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

| 项 | 结果 | 备注 |
|---|---|---|
| Task 8 收尾（12 文件组 + capture + viewport + hints/help + 四棘轮） | **422 passed** | 2026-08-14 |
| Task 9 收尾（同上，不含 hints/help） | **352 passed** | 2026-08-14 |
| 四棘轮（state ownership / backref / lambda / import boundary） | **PASS** | 含在上述命令 |
| UV-P3-A01…A05 直接操纵 | **PASS** | 真实鼠标事件，见 P3-1 verify |
| UV-P3-A06 zoom-at-cursor / clamp / fit / 100% | **PASS**（offscreen） | 真机见下表 |
| UV-P3-A09 LOD 滞回 | **PASS** | 60%/40% + 滞回 |
| UV-P3-A10 FOCUS tier | **PASS** | 超 0.75× 升 FOCUS；离开降回；`MAX_PREVIEW_PIXELS` 不破 |
| UV-P3-A11 viewport 往返 | **PASS** | 缺省容忍、非法 clamp+warning、passthrough、digest 外 |
| UV-P3-A12 零计算探针 | **PASS** | `test_ultraview_job_isolation.py` / probes 含在 12 文件组 |
| UV-P3-A13 扩容回填 | **PASS** | P3-0 |
| UV-P3-A14 digest characterization | **PASS** | 禁 `in {"fresh","stale","missing"}` 放宽写法 |
| UV-P3-A15 无 Alt+拖文案 | **PASS** | hints / quickref / help |

## 真机 Cocoa

操作者于 2026-08-14 在前景 TraceLab 确认缩放、平移、pinch 与 P3-1 手势仍可用。
**未写入** `max_frame_ms` / `frames_over_33ms` / `pinch_events`。

| 项 | 结果 |
|---|---|
| UV-P3-A07 24 卡连续缩放/平移 | **OK**（操作者确认；无仪器化帧时） |
| UV-P3-A08 pinch / 双指平移 | **OK**（操作者确认；无仪器化到达率） |
| Retina 缓冲复用、无整板 ARGB | **OK**（操作者确认观感；offscreen 有缓冲复用断言） |

## 版本扇出

本包**不发版、不改** `APP_VERSION`。未碰 README / help `meta.version` / Windows 构建脚本。
`docs/analyzer/specs|plans|acquisition/` 历史文档保持当时状态。

## 未做（明确非目标）

- 模板改 auto-layout、分页 PNG、P2-B、QGraphicsView 重宿主
- 任何再计算
- FocusLayer 裁撤（保留到本验收之后）
- 仪器化 Cocoa 帧时探针合入产品路径
