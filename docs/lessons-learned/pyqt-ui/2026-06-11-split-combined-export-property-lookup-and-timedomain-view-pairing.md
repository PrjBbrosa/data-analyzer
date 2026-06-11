---
role: pyqt-ui
tags: [export, grab-pixmap, combined-split, multiview, property-vs-method, view-pairing, time-domain, verify-ui-visually, copy-image, page-for-mode]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
V11 added ``AnalysisSectionPage.grab_combined_pixmap`` and wired the
analysis cards' ``copy_image_requested`` so a SPLIT analysis section
(fft/fft_time/order) exports both panes composited side-by-side, parallel
to the time-domain ``chart_stack._combined_split_pixmap`` branch. The
closing P4 gate also smoke-tested the (untouched) time-domain split.

## Lesson
Two traps a unit test of the page-in-isolation cannot catch — only a live
copy-button click on the wired host exposed them. (1) ``ChartStack``
exposes the per-section page lookup as a ``@property``
(``page_for_mode`` RETURNS a dict), not a method. Wiring the analysis
copy branch as ``self.page_for_mode().get(mode)`` raised
``TypeError: 'dict' object is not callable`` ONLY at the live
``_copy_card_image`` dispatch; every ``grab_combined_pixmap`` unit test
passed because they call the page directly and never touch the host's
property. Grep the accessor's ``def``/``@property`` before calling — do
not assume ``foo_for_x`` is a method. (2) The time-domain split is a
view-PAIRING: the secondary pane renders a DIFFERENT view's channels
(``_on_view_split(other_idx)`` → ``_render_view_to_canvas(other_idx,
secondary_canvas())``), NOT a duplicate of the active channels. A
verification harness that drives ``cs.enter_split()`` + ``plot_time()``
leaves the secondary canvas with ZERO channel lines and grabs a
FALSE-BLANK split screenshot — which is a harness bug, not a regression.
The real user path is ``view_tabbar.split_requested.emit(other_view_idx)``
after seeding View 2 with its own channels. Trusting the blank pixmap as a
"red-line regression" would have wrongly BLOCKED the gate; trusting the
structural ``split_active()==True`` PASS without re-grabbing the actual
panes would have wrongly passed a blank. The honest check grabs each pane
canvas and asserts ``non_white_fraction > 0`` on BOTH (verify-ui-visually).

## How to apply
When wiring a host-level copy/export branch onto a child container's grab
helper: grep the host accessor (``def`` vs ``@property``) and call it with
the right syntax; cover the branch with a LIVE host dispatch
(``_copy_card_image(card)``), not just a child-in-isolation unit test —
the property-vs-method shape mismatch is invisible to the latter. When
visually verifying a "split" feature whose two panes show DIFFERENT
content sources (view-pairing, not channel-duplication), drive the
documented pairing signal and re-grab EACH pane's canvas asserting
non-white content on both; a blank secondary almost always means the
harness used the wrong split entry point, so re-drive before declaring a
regression.
