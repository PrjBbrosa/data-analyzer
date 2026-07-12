---
role: pyqt-ui
tags: [contentsmargins, overhang, badge, alignment-datum, form-column, db-reference, geometry]
created: 2026-07-13
updated: 2026-07-13
cause: insight
supersedes: []
---

## Context

`DbReferenceControl` reserved room for a corner-overhang mode badge via
`outer.setContentsMargins(0, 0, _BADGE_MARGIN, _BADGE_MARGIN)` (right AND
bottom, both `_BADGE_OVERHANG + 2`). The compound root's own right edge is
the value `_fit_field(align_right=True)` lines up with the sibling
`频率加权`/`幅值轴` combo fields above it in the same `QFormLayout` column. A
same-magnitude right margin on both the badge's reservation AND the
column-alignment edge silently pushed the manage BUTTON 8px left of that
shared column edge — so the (inset, unremarkable) badge ended up sitting
flush with the column while the button users actually look at/click read as
wrongly offset. Offscreen geometry tests never caught this because they only
asserted badge containment, never button-vs-sibling-field alignment.

## Lesson

When a corner-overhang decoration (badge/dot) and a sibling widget's
alignment datum (a shared form-column edge, a toolbar's right edge, etc.)
land on the SAME side of a container, do not reserve overhang margin on that
side — the reservation margin and the alignment datum compete for the same
pixels, and the datum silently loses. The visually secondary element (the
overhang decoration) must be the one that gives way: keep it flush with (or
inset within) the primary element's own edge on the datum side, and reserve
overhang margin ONLY on the orthogonal side(s) where no external alignment
contract exists.

## How to apply

Before adding `setContentsMargins`/`setViewportMargins` to reserve room for
an overhanging corner badge on a widget that itself must align (flush right,
flush bottom, etc.) with an EXTERNAL sibling (shared form column, docked
toolbar edge, splitter pane edge): identify which side(s) carry that
alignment contract, zero the reservation on those side(s), and encode the
contract with a geometry test asserting the PRIMARY widget's edge (not the
badge's) equals the container's content edge on that side (`abs`-tolerance
`mapTo`-based check, not just `rect().contains(badge_rect)`).
