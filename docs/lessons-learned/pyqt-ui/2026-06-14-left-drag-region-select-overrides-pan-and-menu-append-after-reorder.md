---
role: pyqt-ui
tags: [pyqtgraph, viewbox, mousedragevent, linearregionitem, frame-select, context-menu, reorder, dual-emit, sigrangechangedmanually]
created: 2026-06-14
updated: 2026-06-14
cause: insight
supersedes: []
---

## Context
FFT R3: repurpose the time-preview's LEFT-drag from pan to a
``LinearRegionItem`` frame-select that drives the existing
``time_preview_range_changed`` signal, and add a 右键「清除选区」 entry — all on
``PgLineCanvas._plot_time`` whose menu is reshaped by
``redesign_pg_context_menu``.

## Lesson
Override ``ViewBox.mouseDragEvent`` (subclass of ``_ModifierWheelViewBox``) and
on ``LeftButton`` + ``axis is None`` call ``ev.accept()`` + ``mapToView`` +
build the region and **return without** ``super()`` — that alone kills the pan;
all other buttons/axis-drags must fall through to ``super()`` or box-zoom,
Ctrl/Shift wheel-zoom and the right-click menu (all inherited) go inert. Two
non-obvious couplings: (1) the swap silently makes left-drag stop emitting
``sigRangeChangedManually``, so the range now reaches main_window via a DUAL
path — programmatic pan/wheel → ``viewRange()`` → ``_emit_time_preview_range``,
vs drag → region → ``select_time_region`` emit — and tests that synthesize
``sigRangeChangedManually.emit`` keep working because they bypass the drag. (2)
``redesign_pg_context_menu`` runs ``_reorder_top_level_actions`` over a FIXED
whitelist; a custom action must be appended AFTER that call returns (un-listed
actions land at the bottom) — appending inside/before gets reshuffled or
dropped. Keep the region OUT of ``grab_pixmap`` by transient
``setVisible(False)``/restore in a try/finally.

## How to apply
When converting a pyqtgraph left-drag to a region/lasso/frame-select: subclass
the existing owner-aware ViewBox, override ``mouseDragEvent`` (return early on
the target button, ``super()`` otherwise), and swap ONLY that one plot's
``viewBox=`` — the inherited signal wiring (sigResized/sigXRangeChanged/
sigRangeChangedManually/raiseContextMenu) survives untouched. For a menu entry
on a redesigned pg menu, append the ``QAction`` after the redesign call, not
inside it. Verify with a live ``build_region_from_data`` drive (region visible,
X range unchanged, range signal fired) and saved PNGs of selected/cleared.
