---
role: pyqt-ui
tags: [qss, dynamic-property, border, focus, wa-styledbackground, padding, contentsmargins, unpolish, verify-pixels, splitter]
created: 2026-06-04
updated: 2026-06-04
cause: insight
supersedes: []
---

## Context

Side-by-side compare (P2 Task 9 Step 5) needed the focused time card to grow
a primary-blue accent border via a dynamic property selector
``QWidget#chartCard[focused="true"] { border: 2px solid #2563eb; }``. The
``setProperty("focused", True)`` + ``unpolish/polish`` flip worked (the
property read back correctly), but a real-window ``card.grab()`` pixel probe
showed the card edge was **still pure white** in both focused and unfocused
states — the accent never rendered.

## Lesson

A QSS *border* on a plain ``QWidget`` whose layout uses
``setContentsMargins(0,0,0,0)`` is effectively invisible for two compounding
reasons: (1) without ``setAttribute(Qt.WA_StyledBackground, True)`` Qt only
paints the rounded corners of the border, leaving the straight edges
un-bordered; and (2) even once the flag is set, the margin-0 child widgets
(toolbar/canvas) paint right over the 2px border ring. The border only becomes
visible when you BOTH enable ``WA_StyledBackground`` AND add QSS ``padding``
(e.g. ``padding: 2px``) on the focused rule — QSS padding insets the layout's
content rect so children no longer overpaint the border. A dynamic-property
flip plus a unit test asserting ``property("focused") is True`` will pass while
nothing renders; only a per-card ``grab().toImage()`` pixel sample (scan a
column a few px in from the edge, accounting for HiDPI 2× and the rounded
corner offset) proves the accent actually paints and moves between panes.

## How to apply

When adding a property-keyed border/accent (focus ring, selection outline) to a
container that holds margin-0 children: pair the ``[prop="true"]`` QSS border
rule with (a) ``WA_StyledBackground`` on the container and (b) a small QSS
``padding`` on the same rule so children stop overpainting it. Then VERIFY with
a real-window ``grab()`` and sample pixels just inside the edge at vertical
center — do not trust ``property(...)`` read-back or an offscreen unit test;
those mask the no-render case entirely. Sample away from ``x=0`` (rounded
corners + HiDPI scaling leave the extreme edge transparent/white).
