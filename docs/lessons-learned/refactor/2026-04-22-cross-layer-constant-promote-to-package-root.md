---
role: refactor
tags: [layering, constants, dependency-rules, palette]
created: 2026-04-22
updated: 2026-04-22
cause: insight
supersedes: []
---

## Context
A design spec assigned a constant (`FILE_PALETTES`) to a leaf
subpackage (`ui/_palette.py`), but a *lower* layer (`io/file_data.py`,
specifically `FileData.get_color_palette()`) also consumed it. The
lower layer cannot import from the upper layer without violating the
package's dependency rules (`io` and `signal` must not import from
`ui`). The intermediate fix was to inline a duplicate copy into
`io/file_data.py` — which silently desynchronizes if the palette ever
changes.

## Lesson
When a constant is consumed by two layers that the dependency graph
forbids from importing each other, it does NOT belong in either
layer. Promote it to the lowest common ancestor (here, the package
root: `mf4_analyzer/_palette.py`) and have both layers import down,
not sideways. Inlining a copy is acceptable only as a transient
bridge during a multi-phase refactor; never ship it.

## How to apply
Trigger: a spec places a "shared constant" in a subpackage and you
notice a sibling subpackage also reads it. Action: before writing the
subpackage file, walk the dependency rules; if either consumer would
have to import "up" or "sideways", relocate the constant to the
package root with a leading underscore (private) and re-export
nothing from the subpackages.
