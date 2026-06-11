---
role: pyqt-ui
tags: [pyqtgraph, heatmap, colorbar, setlevels, levels-changed, multiview, compare-toggle, edge-signal, blocksignals, write-back, inspector-echo, dual-path]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
V8 added a "lock color levels" compare option to the split heatmap
panes plus two toggle buttons (联动缩放 / 锁定色阶). A user dragging one
pane's colorbar had to (a) drive the sibling pane's image to the same
range AND (b) echo the dragged range into the inspector's Z spinboxes —
two consumers of the SAME `levels_changed` signal owned by two different
layers.

## Lesson
Two coupled traps. (1) Split the level-lock responsibilities by layer to
keep them from fighting: the PAGE owns canvas↔canvas sync
(`_on_locked_levels_changed` mirrors a drag onto every pane's `_img` +
`_cbar`), and MAIN_WINDOW owns canvas→inspector echo
(`levels_changed` → `apply_params({z_auto:False, z_floor, z_ceiling})`).
Because `ColorBarItem.setLevels` is SILENT (pg 0.14.0; only interactive
region drags emit), the page's propagation MUST still wrap the sibling
`setLevels` in `blockSignals(True/False)` — not because today's pg
re-emits, but so the mirror write can never become a phantom drag that
re-enters the lock loop. The inspector echo must gate on
`pane_idx == page.focused_index()` (the inspector mirrors the focused
pane only), or a background pane's lock-propagated drag double-writes the
Z controls. pg signals expose no "is connected?" query, so re-locking
must `disconnect` (guarded by `try/except TypeError` for not-connected)
BEFORE `connect`, or repeated locks multi-connect and one drag fires
propagation N times. (2) A toggle button's `toggled(bool)` is a TRUE
edge; do NOT reuse a pre-existing non-edge signal (here `link_toggled`,
which `set_linked` fires on EVERY apply incl. programmatic). State→button
seeding (`sync_compare_buttons` reading `state.compare`) must run under a
`_suppress_compare_edge` guard so the resulting `setChecked` edges are
swallowed and never write the value straight back — otherwise the
write-back loop (button→state→view-switch reads state→re-seeds button)
oscillates. A button that must produce a first-click edge has to START in
the OPPOSITE of the value the test/user toggles to (e.g. 联动缩放 default
ON so the first user `setChecked(False)` is a real edge).

## How to apply
When one pg signal feeds both a sibling-canvas mirror and an inspector
echo: assign the canvas↔canvas sync to the container widget and the
canvas→inspector echo to the host, gate the echo on focused-pane, and
`blockSignals` every programmatic `setLevels`/`setLevels`-like mirror
even though the setter is silent today. For any compare/lock toggle:
emit a NEW edge signal off `toggled(bool)` (never a non-edge legacy
signal), seed state→button under a suppress flag, and verify the toggle
fires exactly one edge per click (count the handler, not the final value
— an idempotent mirror write hides multi-connect). Test a colorbar drag
by `setLevels((lo,hi))` then `sigLevelsChanged.emit(cbar)` (M2: setLevels
alone emits nothing); `_img.getLevels()` returns an ndarray in pg 0.14.0,
so unpack to scalars before `== (approx, approx)` or the bare assert
raises ambiguous-truth.
