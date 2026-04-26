---
date: 2026-04-26
top_level_request_summary: |
  紧凑化 Inspector 表单：用户接受了"紧凑化方案"中编号为 1/2/5（实际对应文中
  标注的【1】同行并排双控件、【2】条件可见 hide-not-disable、【3】行间距收紧 →
  本会话用户口径将其归为 1+2+5 三组改动）。所有改动局限于
  mf4_analyzer/ui/inspector_sections.py 与 mf4_analyzer/ui/style.qss。
  用户明确要求 TDD：先红再绿，先 tests/ui/test_inspector.py 增加 visibility
  覆盖。同时要求保持 Inspector 对外契约（getter/setter/signal/payload 名称、
  style.qss 颜色与主按钮 role）不变。
---

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| compact-inspector-forms | pyqt-ui-engineer | (none) | 纯 PyQt 表单/布局改动（QFormLayout、QHBoxLayout、setRowVisible、setSpacing、QSS 间距）+ TDD 在 tests/ui/test_inspector.py 验证 visibility——完全落在 pyqt-ui-engineer 的 surface 工作面，且不涉及任何 FFT/loader/数学计算或包级 refactor，故单子任务即可承载。 |

## Why single-specialist (no split)

- 三组改动【1/2/3】全部触及同一文件 `inspector_sections.py`（局部还会触及
  `style.qss` 中的间距相关规则），如果切片到不同 specialist，会触发
  `2026-04-22-move-then-tighten-causes-cross-specialist-rework` 中描述的
  cross-specialist 同文件 rework 风险，并在 aggregate 阶段被
  `2026-04-25-silent-boundary-leak-bypasses-rework-detection` 标记。
- 三组改动语义高度耦合（同行并排 + 条件可见 + 行间距），都只为达成"紧凑化
  Inspector"这一目标，应作为一个 atomic 任务。
- 没有任何 surface 关键词与 computation 关键词冲突——纯 UI 表面（widget/
  layout/spacing/visibility/QSS）。

## Lessons consulted (read in step 4)

- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
  （明确要求 narrow-pane 类问题先用 container/scroll/splitter 解决再动 form
  语义；本任务不属于 narrow-pane 反馈，是 form 内部紧凑化，但提醒 specialist
  不要顺手把 row 改成 vertical block，仍保留 QFormLayout 行结构）
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
  （支撑"单 specialist 完成"的决定）
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  （要求 specialist 返回 symbols_touched，让 reviewer 能 grep 确认未触及对外
  契约符号）

## Notes for main Claude

- 这是一次单 dispatch，不需要 parallel 协调，也没有 depends_on 链。
- specialist 返回后 main Claude 跑 rework 检测：files_changed 仅
  `inspector_sections.py`（可能含 `style.qss`、`tests/ui/test_inspector.py`），
  不与任何前序 subtask 重叠 → 不应触发 rework lesson。
- 完成（done/partial）后正常 +1 `top_level_completions`；当前 state 中
  completions=7，last_prune_at=0，距离 20 阈值还有 12 次，无需触发 prune。
