---
role: refactor
tags: [arch][dead-code][test-blast-radius][matplotlib][renderer-swap][canvases]
created: 2026-06-18
updated: 2026-06-18
cause: insight
supersedes: []
---

## Context

Retiring `TimeDomainCanvas`/`PlotCanvas` (1791-line `canvases.py`) after the
pyqtgraph swap required touching 11 test files — far more than the 3 listed in
the task brief.  The brief named `test_canvases.py`, `test_axis_interaction.py`,
`test_timedomain_pan_perf.py`, and `test_canvases_envelope.py`.  The actual
blast radius also included `test_canvas_compactness.py`, `test_dialogs.py`,
`test_envelope.py`, `test_pg_timedomain_canvas.py` (2 parity tests),
`test_timedomain_canvas_contract.py`, and `test_xlim_refresh.py`.

## Lesson

A `grep -rn "ClassName" tests/` over ALL test files — not just the ones the
plan mentions — must precede any class deletion.  Source-inspection tests
(`inspect.getsource(canvases)`) also break silently: they scan the module body
and assert call-site patterns that disappear with the class.  Both flavors
appear only from a grep, not from reading the test files named in the plan.

## How to apply

Before deleting a class (or retiring a module's class bodies), run
`grep -rn "ClassName\|inspect.getsource.*module_name" tests/` across the full
test tree, not the abbreviated list in the plan.  Any hit is a file that needs
surgery or deletion; add them to the commit pathspec explicitly.
