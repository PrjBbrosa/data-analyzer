# Custom-X 单游标路径缓存 · Cocoa 标定待测

- 日期：2026-08-31
- 对象：followup spec §3.6 / plan T6（`analyze_custom_x_paths` 画布 memo +
  `_sample_path_contribution` 的 `searchsorted` 插值）
- 平台：本记录只覆盖 offscreen 数值/缓存契约。macOS Cocoa 前景拖动未测。

## 门槛（规格）

500k 点 × 4 通道 Custom-X 单游标，缓存命中路径每 move 取值成本 ≤ 5 ms。
该项必须在真机 Cocoa 前景测，offscreen 只能当数量级冒烟。

## 本次状态

| 项 | 证据类 | 结果 |
|---|---|---|
| 数值等价（旧逐段循环 vs `searchsorted`） | unit | 见 `tests/test_custom_x_paths.py` |
| 缓存命中 / 三类失效 | offscreen Qt | 见 `tests/ui/test_custom_x_path_cache.py` |
| 500k×4 Cocoa 每 move ≤ 5 ms | real macOS Cocoa | **UNVERIFIED / pending** |

不要把 offscreen 微基准读数写成该门槛已通过。
