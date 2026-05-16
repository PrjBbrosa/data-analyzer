---
date: 2026-05-16
slug: acquisition-ui-overflow
mode: plan
source_user_request: |
  你详细列好 plan 和 spec 然后安排 agent 同步执行。
  (acquisition_ui overflow/scroll P0-P1 fixes on feat/acquisition.)
scope_root: mf4_analyzer/acquisition_ui/
tests_root: tests/acquisition_ui/
forbidden_paths:
  - mf4_analyzer/acquisition_capture/   # 核心采集逻辑禁止改动
---

## Confirmed defects (file:line evidence, from prior-turn analysis)

| ID | Defect | Source | Severity |
|---|---|---|---|
| P0-1 | LiveCardGrid 用 QVBoxLayout 无 QScrollArea；Sparkline `setMinimumHeight(36)` 不可压缩；≥6-7 channel 顶出窗口 | widgets/live_cards.py:341-347, 89 | P0 (user 主诉) |
| P0-2 | ReviewModal 无 QScrollArea/无 setMinimumSize/无 setSizeGripEnabled；pf_label 单 QLabel `", ".join(missing_channels)` 撑出屏幕 | review_modal.py:145-205, 180-187 | P0 |
| P1-1 | RightPanel `setFixedWidth(300)` 三页面无 scroll；IdlePreflightPage 5 metric section 在低分辨率被截 | widgets/right_panel.py:455-465 | P1 |
| P1-2 | 工具栏 QFrame+QHBoxLayout（非 QToolBar）无 ▾ 溢出菜单；选择器 setFixedWidth；MainWindow resize(1280,760) 无 minimumSize | main_window.py:298-388, 174 | P1 |
| P2-1 | HistoryTab filter_row + _tag_row 无 wrap/scroll；累计 20+ tags 溢出 | history_tab.py:485-511 | P2 (deferred per user verbal) |

Out-of-scope for this wave (user verbal P2/P3):
- LeftPane 二级 chip 行
- ReplayTab transport row 8 按钮挤压
- 字符 elide / FixedWidth 字符截断治理
- QMessageBox.open() 模态语义复核
- 颜色 token 治理

`history_tab.py` is mentioned in the defect list as P2-1 but the user
verbally moved it out of this batch; we document it but do NOT include
in subtasks.

## Specialist routing decision

All in-scope defects are **container-level Qt surface fixes** (QScrollArea
wrapping, setMinimum/MaximumSize, QToolBar refactor, QDialog resize/scroll).
Per orchestrator roster:

- "PyQt, widget, dialog, canvas, toolbar, layout, ..., QFrame" →
  `pyqt-ui-engineer`.
- Surface-vs-computation rule applies: even though "RightPanel" and
  "Recorder" exist in the broader package, the work here is layout
  containers, not capture algorithm changes.
- Per `pyqt-ui/2026-04-24-responsive-pane-containers.md`: prefer
  container-level scroll/splitter/stretch fixes BEFORE changing
  control semantics — exact pattern match.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S0-SPEC — write spec doc `docs/analyzer/acquisition/specs/2026-05-16-acquisition-ui-overflow-spec.md` enumerating P0-1/P0-2/P1-1/P1-2 user stories + per-panel scroll/min-size/resize contracts + regression test requirements (channel counts, missing_channels count, narrow-window widths to test) | pyqt-ui-engineer | [] | Spec is UI contract authoring; pyqt-ui-engineer owns Qt surface contracts. Docs-only artifact under `docs/analyzer/acquisition/specs/`. No `.py` edits. |
| S0-PLAN — write plan doc `docs/analyzer/acquisition/plans/2026-05-16-acquisition-ui-overflow-implementation.md` with stage list, file-touch matrix, TDD red→green order, depends-on graph for S1-S4 below, manual `--demo` verification checklist | pyqt-ui-engineer | [S0-SPEC] | Plan flows from spec; same author keeps contract↔stage mapping coherent. Docs-only artifact. Uses `superpowers:writing-plans` skill. |
| S1-LIVECARDS — wrap `LiveCardGrid` in `QScrollArea` (vertical only, horizontal off, widgetResizable=True); set sensible `setMinimumHeight` on the scroll viewport (e.g. 240px) and let inner QVBoxLayout grow naturally; verify `Sparkline.setMinimumHeight(36)` still respected; replay_tab.py:142 reuses LiveCardGrid → no extra change needed there; add TDD test `tests/acquisition_ui/test_live_cards.py` red-first: insert 20 channels, assert outer widget's `sizeHint().height()` does NOT grow unboundedly AND inner scroll area's `verticalScrollBar().isVisible()` becomes True after `widget.resize(..., 400)` | pyqt-ui-engineer | [S0-PLAN] | P0-1; single file (`widgets/live_cards.py`) + single test file. No overlap with S2/S3/S4. |
| S2-REVIEWMODAL — wrap `ReviewModal` body in `QScrollArea`; call `setSizeGripEnabled(True)` and `setMinimumSize(420, 320)`; rewrite `pf_label` rendering so `missing_channels` becomes either a `QListWidget` (preferred) or a `QLabel` inside a max-height scroll viewport; add `tests/acquisition_ui/test_review_handoff.py` red-first case: 100 missing channels keep dialog size capped at screen height and the body scrollbar appears | pyqt-ui-engineer | [S0-PLAN] | P0-2; single file (`review_modal.py`) + extension of existing `test_review_handoff.py`. Cites `pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md` (modal reachability discipline — do not regress the gated `在 Analyzer 打开` button). |
| S3-RIGHTPANEL — replace `setFixedWidth(300)` with `setMinimumWidth(280) + setMaximumWidth(360)`; wrap each of the three pages (IdlePreflightPage / RecordingHealthPage / ErrorPage) in a `QScrollArea` with the body widget left-anchored and capped at `setMaximumWidth(<form_natural_width>)` per `pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`; verify visibility-toggle on metric rows does NOT change apparent pane width (wide-pane axis from `pyqt-ui/2026-04-24-responsive-pane-containers.md`); add `tests/acquisition_ui/test_right_panel.py` cases: (a) tall IdlePreflightPage with all 5 metric sections expanded shows vertical scrollbar at viewport_h=400; (b) panel width stays in [280, 360] at outer widths 200, 600, 1500 | pyqt-ui-engineer | [S0-PLAN] | P1-1; single file (`widgets/right_panel.py`) + extension of existing `test_right_panel.py`. No overlap with S1/S2/S4. |
| S4-TOOLBAR — refactor `main_window.py` top toolbar from raw `QFrame + QHBoxLayout` to a `QToolBar` (or keep QFrame + add a `[≡] overflow` button that opens a `QMenu` mirroring hidden actions when width < threshold); replace `setFixedWidth` on selectors with `setMinimumWidth + setMaximumWidth + QSizePolicy.Preferred`; set `MainWindow.setMinimumSize(960, 600)` at line 174 area; add `tests/acquisition_ui/test_visual_shell.py` red-first cases: (a) at outer width 800px no toolbar child overflows the right edge OR overflow `[≡]` button is visible with all hidden actions enumerated in its menu; (b) `MainWindow.minimumSize() == (960, 600)` | pyqt-ui-engineer | [S0-PLAN] | P1-2; single file (`main_window.py`) + extension of existing `test_visual_shell.py`. Touches the `MainWindow` Cockpit shell ONLY in its toolbar slice — must NOT regress `MainWindow.load_file(path)` public wrapper from Stage 5 prior wave; brief enumerates forbidden symbols below. |
| S5-VERIFY — run `python -m pytest tests/acquisition_ui/ -q`; run `python -m mf4_analyzer.acquisition_ui --demo` headlessly under `QT_QPA_PLATFORM=offscreen` and assert no exceptions for 60 s with ≥6 fake channels driven; collect pass/fail summary and any new lesson candidates; this is the green-gate after S1-S4 | pyqt-ui-engineer | [S1-LIVECARDS, S2-REVIEWMODAL, S3-RIGHTPANEL, S4-TOOLBAR] | Final regression gate. Owned by pyqt-ui-engineer because the verifier needs to interpret Qt failures. |

## Parallelism & serialization rules

- **S0-SPEC → S0-PLAN**: serial — plan depends on spec contracts.
- **S0-PLAN → {S1-LIVECARDS, S2-REVIEWMODAL, S3-RIGHTPANEL, S4-TOOLBAR}**:
  parallel fan-out. File-touch verification per
  `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`:
  - S1 owns: `widgets/live_cards.py`, `tests/acquisition_ui/test_live_cards.py`
  - S2 owns: `review_modal.py`, `tests/acquisition_ui/test_review_handoff.py`
  - S3 owns: `widgets/right_panel.py`, `tests/acquisition_ui/test_right_panel.py`
  - S4 owns: `main_window.py`, `tests/acquisition_ui/test_visual_shell.py`
  → **disjoint primary files AND disjoint test files**. Safe to dispatch
  in one parallel block. No shared `conftest.py` mutation required (each
  test uses existing fixtures).
- **{S1, S2, S3, S4} → S5-VERIFY**: serial join — verify is the green
  gate after all four land.
- Same-expert serialization: even though all subtasks dispatch to
  `pyqt-ui-engineer`, the disjoint-file rule from
  `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  is the only constraint, and it is satisfied.

## Boundary discipline (forbidden symbols / files per subtask)

- **All S1-S4 forbidden:**
  - Any file under `mf4_analyzer/acquisition_capture/`
  - `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
  - `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
  - `mf4_analyzer/acquisition_ui/widgets/live_downsampler.py`
  - `mf4_analyzer/acquisition_ui/replay_tab.py` (LiveCardGrid reuse must
    take effect via S1 changes alone — do NOT edit replay_tab to wrap
    a second scroll area)
  - `mf4_analyzer/acquisition_ui/history_tab.py` (explicit P2 deferral)
- **S4-TOOLBAR additional forbidden:** must NOT modify
  `MainWindow.load_file(path)` public wrapper (Stage 5 contract from
  prior wave); must NOT touch the four-state machine transitions; brief
  must enumerate the forbidden methods explicitly per
  `orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`.
- Every specialist return must include `symbols_touched` (per
  `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`)
  so main Claude can grep the forbidden list before S5-VERIFY.

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — `top_level_completions=38`, `last_prune_at=21`; gap=17, still below 20-threshold; no prune dispatch this run.
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — orchestrator plans, main Claude dispatches.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — disjoint-file verification for the S1‖S2‖S3‖S4 parallel fan-out.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — require `symbols_touched` in every specialist return.
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — enumerate forbidden methods per brief when same file is touched (S4 main_window.py).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — fold mechanical edits (e.g. minimumSize on MainWindow ctor) into the body author's brief, do not split across specialists.
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — container-level scroll/splitter/stretch BEFORE changing control semantics; wide-pane verification at 3 widths. Cited in S3 and S1 briefs.
- `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md` — cap scroll body width + left-anchor + tool-button QSS escape. Cited in S3 brief.
- `docs/lessons-learned/pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md` — ReviewModal must keep gated "在 Analyzer 打开" button reachable; resize/scroll changes must not regress this contract. Cited in S2 brief.
- `docs/lessons-learned/pyqt-ui/2026-04-27-modal-from-qthread-finished-segfaults-offscreen.md` — modal `isVisible()` gating; cited in S2 brief.

## Skills hand-off notes

- **`superpowers:writing-plans`** — S0-PLAN specialist MUST invoke this
  skill; the plan will drive 4 parallel specialist dispatches, which
  exceeds the orchestrator's >3-dispatch threshold for plan authoring.
- **TDD discipline** — S1/S2/S3/S4 briefs each specify red-first test
  cases; specialist must write the failing test FIRST, run pytest to
  confirm red, then implement the container fix to green.
- **`superpowers:requesting-code-review`** — NOT requested by user this
  wave; user asked for "同步执行" (synchronous execution = parallel), not
  for codex review checkpoints. Document this absence in the audit.
- **`superpowers:brainstorming`** — not invoked: defect list is
  unambiguous and routing is unambiguous. No clarification gate needed.

## Cadence

- `top_level_completions = 38`, `last_prune_at = 21`, gap = 17 (< 20).
  Main Claude increments on completion; no prune dispatch needed at
  end of this run unless gap hits ≥ 20 (becomes 39 → still < 20 gap +
  21 = 41 threshold). No prune flag.

## Notes

- The user's message contains no squad-keyword (no `agent`, `squad`,
  `refactor`, `团队`, `分工`, `多专家`, `multi-agent`). However the
  invocation explicitly says "安排 agent 同步执行" — `agent` substring
  match → routed correctly. No missed-trigger lesson needed.
- All 6 subtasks dispatch to `pyqt-ui-engineer`. The user's "同步执行"
  request is honored by parallelizing the S1-S4 fan-out in one message
  block; serial constraints (S0-SPEC → S0-PLAN → fan-out → S5-VERIFY)
  are unavoidable due to data dependencies.
- No `.py` source changes by the orchestrator. All four code subtasks
  flow through `pyqt-ui-engineer`.
