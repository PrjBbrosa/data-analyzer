# UltraView P2-A 验收记录（2026-08-14）

- 日期：2026-08-14
- 对象：P2-A 受控自由网格（P2-B live inspection 仍为 NO-GO）
- 平台：macOS Darwin 27，offscreen Qt
- 关联：`docs/analyzer/reviews/2026-08-14-ultraview-p2b-inspection-capability-audit.md`

## 1. 已自动化

| 项 | 结果 | 说明 |
|---|---|---|
| 自由网格存盘 `layout_id`/`primary_ratio` | 见 state 往返 + `test_free_grid_project_roundtrip_keeps_layout_id_and_placements` | 关自由网格不再掉回 hero_left_4 |
| `clamp_rect` / `_grid_at` | 见 free_grid + page 测试 | origin+span 落在 12 列 / 48 行内 |
| 尺寸预设碰撞 toast | 见 export/coordinator 测试 | 不再静默 no-op |
| undo 失配清栈 | 见对应测试 | 不把失配条目压回栈 |
| Alt 方向键真实 `keyPressEvent` | `test_free_grid_alt_arrow_uses_real_key_event` | 不再只 emit 信号绕过 widget |
| 短板导出裁尾白 | compositor + `export_grid_metrics` | 屏幕仍垫 viewport；导出 `min_visible_rows=1` |
| 整板概览复用 `compose_board` | page/overview | 隐藏时不合成；同 Board 刷新不关概览 |
| GridMetrics 合同 | spec §4.2 / §8.1 已回写 | 96×88、屏幕 6 行地板 |

## 2. 明确欠账（与 p2b audit 一致）

ghost/resize handle、同尺寸 swap、分页 PNG、24 图 Cocoa benchmark、50 次 lifecycle 加压：未做。
§11 guide 元数据未写入 sidecar format 1。

## 3. 未跑层

Cocoa 前景手势、Retina 导出、Windows frozen：**UNVERIFIED**。
