# UltraView P3-2 zoom spike

- 日期：2026-08-14
- 分支：`codex/ultraview-p1-p2`
- 脚本：`scripts/probe_ultraview_zoom_spike.py`（不合入产品路径）
- Spec：`docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md` §9

## 判据

24 卡连续缩放掉帧（>1 帧 >33ms 持续出现）或 pinch（`QNativeGestureEvent` / `ZoomNativeGesture`）不可靠 → **P3-2 暂停**，P3-0 / P3-1 照常。

offscreen 读数不是 paint 证据，不能替代 Cocoa。

## 插入位（代码审查，不依赖真机）

| 方案 | 做法 | 改动面 |
|---|---|---|
| **A 入参视口（首选）** | `grid_metrics((int(vw*zoom), int(vh*zoom)), placements)`，Board widget 随逻辑尺寸变大，滚动视口不变 | 调用点；`grid_metrics` 签名不动 |
| B 缩放 metrics 字段 | 算出 `GridMetrics` 后再乘 zoom 到 `column_width` / `row_height` / `gutter` / `padding` | 所有消费 metrics 的映射都要知道 zoom |

P3-2 若恢复，采用 **A**：zoom 只改传入 `grid_metrics` 的 viewport，模板模式对 `slot_rects` 的 content 做同样缩放。

## 本次运行

| 项 | 结果 |
|---|---|
| Cocoa 前景 TraceLab | **OK** — 操作者 2026-08-14 确认可用 |
| pinch 到达率 / 增量 | **OK** — 操作者确认 pinch 可靠；未写入仪器化 `pinch_events` |
| 24 卡 Fast 重采样帧时 | **OK** — 操作者确认连续缩放可接受；未写入 `max_frame_ms` |
| offscreen 试跑 | 明确 **不可替代**；未用其数字做 go/no-go |

未记录 `max_frame_ms` / `frames_over_33ms` / `pinch_events` 数值。门控依据是操作者真机确认，不是 offscreen 探针。

## 门控结论

**P3-2 实现已开闸，仪器化真机门仍开。** 插入位仍采用上文方案 **A**（模板）+ 自由网格对 `GridMetrics` 做均匀缩放（`GRID_ROW_HEIGHT` 不随入参视口变化，单靠 A 会只变列宽）。

未回填 `max_frame_ms` / `frames_over_33ms` / `pinch_events` 之前，不得把 P3-2 标为完成。
