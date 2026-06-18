# UI-redesign / optimize verbs miss the squad trigger keyword set

**Date:** 2026-05-30 (updated 2026-06-18)
**Tag:** cause: routing · roster-gap · trigger-keywords
**Run:** 2026-05-30 TimeDomain right-click menu redesign + hi-DPI copy/save;
2026-05-31 overlay AA / interaction bug-fix (spec→实现)
**Specialist:** pyqt-ui-engineer (S1, S2)
**Overlapping files:** n/a (routing lesson, not a rework lesson)

## What happened

The user asked to redesign the TimeDomain right-click context menu (按方案 A
重设计、移除高级项、tooltip 关掉、鼠标操作与工具栏联动) plus a hi-DPI
copy/export addition. This is a substantive multi-part `.py` UI change that
clearly belongs to the squad (`pyqt-ui-engineer`), yet the user's message
contained **none** of the CLAUDE.md squad trigger tokens:

`agent`, `squad`, `团队`, `分工`, `重构`, `refactor`, `多专家`, `multi-agent`

The phrasing was 重设计 / redesign / 菜单改造 / 高清化 — all genuine
code-change verbs, none in the trigger set. `重构` (refactor) did NOT
substring-match `重设计` (redesign).

Main Claude invoked the CLAUDE.md **"Missed triggers"** clause: it judged
the message should have been routed, ran the runbook anyway, and noted the
missed keyword to the orchestrator. The run completed cleanly (2 serialized
pyqt-ui-engineer subtasks, 611→619 ui tests green).

## Why the trigger set missed it

The trigger list is built from *collaboration-shape* words (`squad`,
`分工`, `多专家`) and one *work-type* word (`重构`/`refactor`). But most
real UI work arrives as a *task verb* — 重设计/redesign, 改造/rework,
重做/redo, 美化/restyle, 优化界面 — and as a feature add (新增需求). None
of those are in the set, so a large class of legitimately squad-worthy UI
tasks rely entirely on the "Missed triggers" safety net rather than the
keyword fast-path.

**2026-05-31 reinforcement (bug-fix / spec→实现 phrasing):** the overlay
AA / interaction run arrived as two triggerless messages — (1) a bug
report ("当前叠加模式还有挺多问题和 bug … 让我整体评估") and (2) the
actionable go-ahead "你写好 spec 开始优化吧". The operative verbs were
评估 (evaluate) and 优化 (optimize); again **zero** keyword hits, and the
*actionable* second message ("start optimizing") is even more keyword-bare
than the first. Two new task-verb classes confirmed missing from the set:
**bug-fix reports** and **优化/optimize**, plus the **spec→实现 hand-off**
pattern where the implementation-trigger message carries no work-type noun.
Routed correctly via the Missed-triggers clause; one bundled
pyqt-ui-engineer task (4 fixes, single file).

## Preventative guidance

1. **Keep leaning on the "Missed triggers" clause** — it worked here.
   Substantive `.py` changes should be routed even with zero keyword hits.
2. **Consider widening the trigger set** with UI-redesign task verbs:
   `重设计` / `redesign` / `改造` / `美化` / `restyle`. Trade-off: these are
   higher-frequency words and risk over-routing conversational Q&A, so the
   out-of-scope precedence rule (`how`/`what` + pure Q&A stays direct) must
   still win. Recommend adding them only if missed-trigger routing proves
   unreliable in practice.
3. The reliable signal is not the keyword but the **act**: does the message
   ask for `.py` source edits? If yes and it's not the escape hatch
   (`skip squad:` / `直接改：`), route.

**2026-06-18 third occurrence (退役 matplot + EF 优化):** the user request
"退役 matplot 然后进行 EF的优化" contained 优化 but none of the trigger
tokens. The main clause "退役 matplot" (retire matplotlib) and "EF的优化"
(phase E/F refactor) are large multi-file structural refactors on a live
branch. Routed correctly via Missed-triggers. Confirms "优化" recurs as a
non-trigger verb for substantial source changes.

## Action items applied to this run

- Routed via Missed-triggers; orchestrator informed of the missed keyword.
- No rework lesson: S1 and S2 share files but are the **same** expert
  (pyqt-ui-engineer) run serially — rework detection only fires across
  *different* experts, so same-expert serial overlap is by design.
