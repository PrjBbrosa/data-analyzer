---
id: pyqt-ui/2026-07-30-canvas-backref-write-through-needs-explicit-whitelist
status: active
owners: [codex]
keywords: [pyqtgraph, canvas-backref, state-ownership, ast, invariant, write-through]
paths: [mf4_analyzer/ui/pg_canvas]
checks: [EXPECTED_WRITE_THROUGH]
tests: [tests/ui/test_pg_canvas_backref_invariants.py]
---

# Canvas backref write-through needs an explicit whitelist

Trigger: A collaborator delegates unknown attribute reads/writes to a shared
canvas, or a refactor adds a new `self.<name> = ...` assignment to such a class.

Past failure: Ownerless flags and manager state silently landed on the canvas,
so dead state looked live and a manager's `_artist` storage location depended
on delegation side effects instead of an ownership declaration.

Rule: Declare every manager-owned and delegated name, and enforce the remaining
canvas write-through set with an AST whitelist. The invariant must fail for an
unknown collaborator class and for any new undeclared assignment.

Verification: Run
`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_canvas_backref_invariants.py -q`;
temporarily adding `self._probe = 1` must fail naming `_probe`, then be reverted.
