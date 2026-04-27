# 工作报告 — 2026-04-27 batch dialog 优化（chip 布局 + RPM 单位 + FFT vs Time）

## 目标

修批处理 dialog 的三个问题：
1. signal picker 选信号越多 dialog 横向越宽
2. RPM 通道无法从下拉列表选择，且没有单位换算
3. 单次模式有的 FFT vs Time 分析在批处理模式里缺失

## 工作流

| 阶段 | 输入 | 产出 | 关键节点 |
|---|---|---|---|
| Plan rev 0 review | 上游 plan 文件 | 6 处问题 | 主 Claude 抓出 eventFilter 装错位置 / setRowVisible 不可用 / 死代码 fallback / 宽度断言假阳性 等 |
| Plan rev 1 | rev 0 + 6 处 fix | 修订后的 plan | 写到 `Rev 1 corrections` 章节 |
| codex spec review (rev1) | rev 1 plan | "needs revision" | 抓出 5 处：rev-1 incomplete x2 + 新 blocking x3（decimals(4) 不够、chip frame sizeHint 不长高、apply_preset 缺 rpm_factor 回填）+ warning x1 + minor x1 |
| Plan rev 2 | rev 1 + 7 处 fix | 修订后的 plan | 写到 `Rev 2 corrections` 章节 |
| codex spec review (rev2) | rev 2 plan | 限额 → fallback `superpowers:code-reviewer` | "approved with minor revisions"，2 处 cosmetic（步骤号 gap + Self-Review type list）inline 修掉 |
| Squad orchestrator (mode: plan) | rev 2 plan | 5 wave 拆分 JSON | W1/W2/W3a/W3b/W4，跨 wave forbidden-symbol 枚举 |
| Squad Phase 2 执行 | 每 wave: dispatch → review gate | 11 commits | 见下表 |
| Squad Phase 3+4 | wave 返回汇总 | rework-detect + state 更新 | 0 跨专家文件交集；`top_level_completions` 22 → 23 |
| Holistic review | 整批 commit | 7 处 finding | 5 处直接 inline 修，2 处留作 follow-up |

## Wave 执行总结

| Wave | Specialist | 文件 | 测试 | Commits |
|---|---|---|---|---|
| W1 | pyqt-ui-engineer | signal_picker.py + style.qss + 1 test | 7 → 15 | `fe00a00` `3b571d7` `2d24214` |
| W2 | pyqt-ui-engineer | input_panel.py + sheet.py + method_buttons.py + 2 tests | 13 → 273 | `05fda72` `35886a5` `971a7b1` |
| W3a | signal-processing-expert | batch.py + 1 test | 350 → 354 | `0a82f85` `c773342` |
| W3b | pyqt-ui-engineer | method_buttons.py + sheet.py + 1 test | 354 → 358 | `4cf1993` |
| W4 | pyqt-ui-engineer | test_batch_smoke.py only | 358 → 359 | `b9926ae` |
| meta | main Claude | docs (rev1/rev2 spec, 4 wave reviews, .state.yml) | — | `3d99adc` |
| cleanup | main Claude (post-squad holistic) | signal_picker + method_buttons + smoke | 359 → 359 | `09dc9d9` |

合计 **12 个 commit**（10 个生产代码 + 1 个 docs + 1 个 cleanup），测试 0 回归。

## 关键技术决策

- **chip 区点击处理：`_ClickableFrame(QFrame)` 子类 + `mousePressEvent` 而不是 `installEventFilter`** —— 父控件的 eventFilter 不接收子控件被消化的事件，filter 在父上装是空操作。
- **`_chip_scroll.setFixedHeight(min(rows, MAX) * ROW_HEIGHT)` 而不是 `setMaximumHeight` 单独设**：`QScrollArea` 不会把内部内容 size 上推到父级 sizeHint，必须显式驱动高度，否则 issue-1 测试假阳性。
- **`_CHIP_ROW_HEIGHT = fontMetrics().height() + 6` 而不是硬编码 26**：跨 macOS / Windows / 高 DPI 不会截断（事后 cleanup 替换）。
- **`takeRow` / `insertRow` 而不是 `setRowVisible`**：PyQt5 5.15.11 不带 `setRowVisible`（Qt 5.15+ 才有），且 `setVisible(False)` 在 QFormLayout 留 blank gap。
- **`QDoubleSpinBox.setDecimals(10)`**：单位常数 `1/6`、`60/(2π)` 是无限小数，4 位十进制 round-trip 误差 1e-4 远超测试 1e-9 容差；10 位 round-trip 误差 ~3e-11。
- **`apply_rpm_factor` ↔ `rpm_params()` 配对**：因为 W2 把 `rpm_factor` 从 `_METHOD_FIELDS` 删了，`_analysis_panel.apply_params` 不再写 spinbox，必须显式补回填路径，否则 preset 导入静默重置。
- **dB 转换是 display-only**：`_write_image` 在 fft_time 分支内 `20*log10(maximum(matrix, eps))`，但 CSV/H5 导出仍是线性 amplitude。
- **64 MB ceiling 走现有 per-task try/except**：`SpectrogramAnalyzer.compute` 抛 `ValueError`，`BatchRunner.run` 既有 wrapper 自动转 per-item `blocked` 项，无需新增 handler。

## 验收

- ✅ 全测试套：359 / 359 pass
- ✅ Cocoa GUI 离线 smoke（W1 之后）：chip 渲染 + sizeHint 增长 + 4 个 user-visible contract 全验证
- ✅ 0 跨专家文件交集（W2/W3b 都改 sheet.py / method_buttons.py 但都是 pyqt-ui-engineer，不触发 rework）
- ✅ Plan 两轮 review 后 approved，每个 wave 独立 review approved

## 留待后续 PR

- 🟡 `apply_rpm_factor` 静默 clamp（preset 里 rpm_factor 超出 spinbox range 时无 warning）
- 🟡 `current_single` 分支的 rpm_factor 回填 round-trip 测试（W2 review 已 flag）
- 🟢 unit-preset tolerance 1e-6 是否与用户预期一致（intended UX，待用户反馈）

## 状态文件

- `docs/lessons-learned/.state.yml`：`top_level_completions: 22 → 23`，`last_prune_at: 21`，gap = 2，未触发 prune（阈值 20）
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-ui-fixes-and-fft-vs-time.md`：squad 拆分审计文件
- `docs/superpowers/reports/2026-04-27-batch-ui-fixes-*.md`：rev1 + rev2 spec review + 4 个 wave review

## 文件改动总览

```
mf4_analyzer/batch.py                            |  59 +++++-
mf4_analyzer/ui/drawers/batch/input_panel.py     | 210 ++++++++++++++++++---
mf4_analyzer/ui/drawers/batch/method_buttons.py  |  43 ++++-
mf4_analyzer/ui/drawers/batch/sheet.py           |  16 ++
mf4_analyzer/ui/drawers/batch/signal_picker.py   | 233 ++++++++++++++++++++++--
mf4_analyzer/ui/style.qss                        |  16 ++
tests/test_batch_runner.py                       |  91 ++++++++-
tests/ui/test_batch_input_panel.py               | 127 +++++++++++++
tests/ui/test_batch_method_buttons.py            |  72 +++++++-
tests/ui/test_batch_signal_picker.py             | 111 +++++++++++
tests/ui/test_batch_smoke.py                     |  50 +++++
```

净增约 **+970 行（生产 + 测试）**，删减约 **-60 行**。

## 同步建议

12 个 commit 都在本地 `main` 分支，未 push 到 `origin/main`。`git status` 显示 `Your branch is ahead of 'origin/main' by 12 commits`，下次 pull/push 由用户决定时机。
