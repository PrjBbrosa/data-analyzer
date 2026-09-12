# 优化鲁棒性实施验证

日期：2026-09-12。实施基线：`d1299597` 加当前工作区候选；初始 scope 已存于
`.state/optimization-robustness-20260912/initial.md`。本记录只描述本次实际结果，
不改写同日 Review 的原始发现。

## 修复状态

|发现/需求|状态|实际落地与证据|
|---|---|---|
|F01 / R01 自动频谱 Y 范围|PASS|`PgLineCanvas` 仅在目标范围精确相同时跳过更新；`test_linear_auto_y_tracks_visible_window_across_scales` 覆盖 `1e-12..1e6`。|
|F02 / R02 树恢复成本|PASS|筛选和 replace restore 建立一次临时复合 identity 索引；快照排除叶节点；500..10000 节点线性计数回归通过。|
|F03 / R03 重入选择态|PASS|Time/Frequency card 均在信号前投影 indicator；同步重定向不再被外层旧目标覆盖。|
|F04 / R04 Batch 诊断|PASS|item、group、run 的 blocked/warning 独立投影，混合结果回归通过。|
|F05 / R05 Batch stale|PARTIAL|真实滤波开关现在经明确 `InputPanel.filterChanged` 用户入口标记旧结果；该入口不把文件 probe/元数据 `changed` 当用户操作。其余既有入口沿用已存在的 user/configuration hooks；未完成逐项人工验收矩阵。|
|F06 / R06 分析范围 restore dirty|PASS|实际改变范围时只提交一次 mutation，重复 restore 为 no-op。|
|F07 / R07 Custom-X 标签|PASS|`CustomXAxisSpec.label_origin` 显式保存 `auto/user`；旧 payload 只在读取缺字段时推断。拖放为 auto，真实 `textEdited` 为 user；同名手写标签经 apply、View/project round-trip、切回 time 保留。|
|G02 / R08 Section 与动效|PASS（逻辑）|320 ms 为当前接受常量，消费者断言同步；reveal/prepared facts/time gate owner 回归通过。|

## 当前验证

- T1 focused：20 passed。
- T2 owner：82 passed。
- T3：12 passed。
- T4 owner：200 passed。
- T5：36 passed。
- T6 View/project family：150 passed。
- T7 Section/motion family：194 passed。
- spectrum/canvas owner family：730 passed，1 deselected。
- 架构边界：45 passed，1 skipped（backref/import/state ownership/lambda/QSettings/QSS/collection）。
- `git diff --check`：通过。

## 性能与平台矩阵

- Cocoa quick spectrum probe：`qt_platform=cocoa`、`comparable_cocoa=true`；自动/手动 Y 与 time-domain correctness 均为 pass。原始 JSON：`.state/optimization-robustness-20260912/spectrum-native/perf.json`。
- 同机 `spectrum-switch` 原生探针出现 `View A` 的 `aa-backstop` red 结果；它不是完整 30-round A/B 性能验收，保留为 G4 PARTIAL，原始 JSON：`.state/optimization-robustness-20260912/view-switch-native/spectrum-switch.json`。
- offscreen quick probe 仅诊断，明确 `comparable_cocoa=false`，不替代原生证据。
- Windows 100%/150%、Full/Lite frozen、完整客户文件五分区矩阵：UNVERIFIED。

## 全量门

主套件以 `pytest --ignore=tests/acquisition_ui -q` 尝试，至 27% 后中断：
`7 failed, 2997 passed, 10 skipped, 3 deselected`（216.22s）。失败涉及 Batch FRF
`output_settings` 未定义、batch render text collision、FFT-time cache-key 字段、帮助导入 ZFD、
及 slice 常量等，均不在本次改动文件内；进程由人工中断，故全量主套件为 UNVERIFIED，未启动
acquisition UI 的第二进程。

未提交或推送。
