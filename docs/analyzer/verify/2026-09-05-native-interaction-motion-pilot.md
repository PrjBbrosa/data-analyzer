# TraceLab 原生交互动效第一轮验证报告

日期：2026-09-05 · 对应 Spec / Plan：`2026-09-05-native-interaction-motion-pilot-*`。

普通启动路径未改。动效默认关闭，只在 `python -m mf4_analyzer.ui.motion_demo` 显式打开。冻结包：`NOT_IN_SCOPE`。

## 环境

| 项 | 值 |
| --- | --- |
| HEAD at T0 | `e5ec1fa9a52f6316fe14f0c1af24dc2e9d1e7c0e` |
| OS | macOS 27.0 arm64 |
| Qt / PyQt / pyqtgraph | 5.15.14 / 5.15.11 / 0.14.0 |
| Offscreen gate | 2026-09-05 coordinator batch：**104 passed**（owner + demo + T5 logic-only + T6 边界） |
| Cocoa / Windows 原生 | **UNVERIFIED** |

## 逐项

| ID | 实现 | G1 | G2 | G3 | G4 | G5 | 预算 / 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 MotionButton | 新样板类，默认关闭 | PASS | partial（offscreen 端点） | UNVERIFIED | UNVERIFIED | PASS | 未改生产 QPushButton |
| S02 PillSwitch | `set_motion_policy`，默认关闭 | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 44×24 保留 |
| S03 SegmentedChoice | 单一底板，combo 仍是状态 owner | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 32px 行高保留 |
| S04 ViewTabBar | 2px 标记，跟确认后的 `view_id` | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 未改 refresh/reorder/overflow |
| S05 折叠 | 意图立即写入；高度/箭头只呈现 | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 注入临时 INI |
| S06 最近打开 | 只入场、关闭立即；宽 640 | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 打开/清除只记样板日志 |
| S07 轻页面 | demo 内双页淡入 | PASS | partial | UNVERIFIED | UNVERIFIED | PASS | 不接 ChartStack |
| M01 View 切换 | 探针 tab 点击入口 | PASS（logic-only） | n/a | UNVERIFIED | UNVERIFIED | PASS | 无性能数字 |
| M02 分区切换 | Toolbar `_set_mode` → `_on_mode_changed` | PASS（logic-only） | n/a | UNVERIFIED | UNVERIFIED | PASS | cached 提交次数 0 |

共享 `ValueDriver` 复用后会把 `currentTime` 留在终点，已在 `motion.py` 归零。

## G6 推广候选

- **待平台：** S01–S07 代码与 offscreen 合同已齐，缺 Cocoa 前台与 Windows 100%/150% 动态验收。
- **可进入下一轮的条件：** 真机 `samples` / `switches` 原始 JSON 齐，且轻场景 feedback_paint p95 与静止后无残留定时器满足 Spec §6.3。
- **大数据瓶颈：** 本轮不承诺 M01-dense 时限；只在 Cocoa 探针后写 measured owner。
- **主观手感：** 尚未由用户评价，不阻塞本报告，也不擅自确认风格。

## 真机命令（未执行）

不要设置 `QT_QPA_PLATFORM=offscreen`。

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m mf4_analyzer.ui.motion_demo
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py samples --output-dir .state/native-interaction-motion/cocoa-samples
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py switches --output-dir .state/native-interaction-motion/cocoa-switches
```

Windows 用仓库根的项目 Python 跑同一入口，不照搬 POSIX 环境赋值。
