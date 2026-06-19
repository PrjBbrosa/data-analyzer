# Current Task Plan: TraceLab Porcelain Surface Layering

## Goal

Write complete implementation spec/plan for the approved porcelain tray surface redesign, then dispatch agents to execute the plan safely.

## Phases

- [x] Inspect current repo UI surfaces, QSS selectors, tests, lessons, and prior memory.
- [x] Replace old snow/flush surface spec with porcelain tray + top/bottom white floating bar spec.
- [x] Replace old implementation plan with three-phase agent-executable plan.
- [ ] Dispatch implementation agent for Task 0/1 or first safe code task.
- [ ] Review agent output and run focused verification.
- [ ] Continue sequential task execution until implementation is complete or blocked.

## Active Artifacts

- Spec: `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md`
- Plan: `docs/superpowers/plans/2026-06-19-surface-system-redesign.md`
- Visual reference: `docs/surface-layering-options.html`

## Guardrails

- Do not commit unless the user explicitly asks.
- Do not revert unrelated dirty worktree files.
- Preserve `self.statusBar` as a real `QStatusBar`-compatible object.
- Treat live rendered PyQt screenshots as final truth, not QSS text alone.
