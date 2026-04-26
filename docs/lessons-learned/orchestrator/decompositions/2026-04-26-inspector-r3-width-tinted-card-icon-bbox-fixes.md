---
date: 2026-04-26
slug: inspector-r3-width-tinted-card-icon-bbox-fixes
mode: plan
top_level_request: |
  R3 紧凑化交付后用户截图反馈三处不一致：
  (a) 点击"使用范围"会让 Inspector pane 视觉变宽（数字输入框无上限拉伸）
  (b) 三个 contextual 内的"分析信号 / 信号源" QFrame 出现白底叠在 tinted contextual card 上
  (c) "重置时间轴"按钮和 file_navigator 关闭/kebab 按钮外框过大（icon 16px 但外框 ~30px）
  并要求"全局优化"。
missed_keyword_routing: true
missed_keyword_note: |
  本消息没有 agent/squad/团队/分工/重构/refactor/多专家/multi-agent 关键词，但属于上一轮 R3 紧凑化交付后的
  UI 视觉一致性修正（Inspector + file_navigator），按 CLAUDE.md "Missed triggers" 强制路由。
  待沉淀的 orchestrator 经验："用户用截图 + 紧凑化 R# 上下文继续提问 UI 不一致问题时，应触发 squad"。
---

# Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| inspector-width-tinted-icon-fixes (fix-1..fix-5 全部一次性落地) | pyqt-ui-engineer | — | 全部改动落在 `inspector_sections.py` / `inspector.py` / `style.qss` / `main_window.py` / `file_navigator.py` + `tests/ui/` + `docs/lessons-learned/`，是 QSS + QFrame + QSizePolicy + QPushButton 外框尺寸的纯 UI 视觉修正。无 signal-processing 或 refactor 维度。单专家串行 TDD 即可，无内部依赖切分必要（拆分反而会触发 same-file 并行碰撞，参见 orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md）。 |

## Rationale for single-specialist bundling

- fix-1（content max-width / 左对齐）、fix-3（数字输入框宽度收紧）、fix-5（splitter 默认尺寸）三者协同决定 Inspector 在
  splitter 拉宽场景下的视觉稳定性，必须由同一双手在同一轮 TDD 里推进，否则只做一半就会出现"窄端 OK 宽端崩"。
- fix-2（QFrame#fftSignalCard 等的 QSS 兜底或 WA_StyledBackground 移除）和 fix-4（btn_rebuild + file_navigator 图标按钮外框收紧 +
  `QPushButton[role="tool"]` padding 收紧）虽然主题不同，但都集中在 inspector_sections.py / style.qss / file_navigator.py，
  与 fix-1/3/5 共享文件 (`style.qss` 和 `inspector_sections.py`)，必须串行同一专家避免 git add 并行碰撞。
- 不切分 signal-processing-expert，因为没有任何算法/IO/数学路径变化。
- 不切分 refactor-architect，因为无 module 重组、无 import 边界调整。

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol（特别是 merge-on-conflict 写入顺序）。
- `docs/lessons-learned/LESSONS.md` — 索引扫描，确认 pyqt-ui section 下与 layout / inspector / responsive-pane 相关条目。
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — "responsive 缺陷应在容器层面解决"。本轮明确补充 Wide-pane verification。
- `docs/lessons-learned/pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md` — R3 引入 _make_group_header 的来源；本轮要补它没说"WA_StyledBackground 必须配 QSS 规则"这一硬伤。
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — 要求 specialist 返回 symbols_touched + contracts_preserved，本轮 brief 显式要求。

## Hard constraints carried into brief

- 不动 mf4_analyzer/signal/ / io/ / batch.py / canvases.py。
- 不改对外 signal / 公开方法 / 公开 attr 名（与 R3 一致）。
- 不改色板（#1769e0 primary / #eef4ff fft tint / #fff5e8 order tint 等）。
- 不改 primary 按钮 role 样式。
- TDD 红→实现→绿；fix-1..fix-5 各自至少一条断言。
- pyqt-ui specialist 返回必须含 `symbols_touched` 与 `contracts_preserved`（应对 silent-boundary-leak lesson）。
- 完成后写 `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`，并修订
  `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` 文末加 "Wide-pane verification" 段。
