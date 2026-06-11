---
role: pyqt-ui
tags: [renderer-swap, matplotlib, pyqtgraph, event-dispatch, test-coupling, contract-test, production-consumers]
created: 2026-05-28
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context

T7 flipped ``ChartStack.canvas_time`` from the matplotlib
``TimeDomainCanvas`` to the pyqtgraph ``TimeDomainCanvasPG``. The
13-test ``test_timedomain_canvas_contract.py`` surface plus 9 other
files in the regression sweep stayed green, but 4 tests in
``test_chart_stack.py`` failed — every one of them drove the canvas
through matplotlib-only APIs (``canvas.callbacks.process``,
``canvas.fig.bbox``, ``ax.get_window_extent``, ``ax.transData``,
``canvas._mouse_button_pressed``, ``canvas.span_selector`` instance
state) rather than through user-facing Qt events.

## Lesson

When migrating a ``FigureCanvas`` widget to a pyqtgraph ``QWidget``,
tests that POST events into ``matplotlib.figure.Figure.canvas.callbacks``
or read ``axes.transData`` / ``fig.bbox`` cannot be made to pass
without re-implementing the matplotlib backend protocol on the new
widget — and re-implementing it defeats the point of the swap.
Contract tests (signal names, channel_data shape, toolbar action keys
+ ordering, exported widget identity) survive cleanly; behavior tests
that fake clicks via the matplotlib dispatcher do not. The honest move
in T7 is to keep those tests visible on the failure list and flag them
for a follow-up that rewrites the simulated events through Qt's native
event system (``QTest.mouseClick``, ``QTest.mouseMove``) instead of
silently editing them in the same task or stubbing dead matplotlib
attributes on the PG canvas to make them stop complaining.

## How to apply

When a UI task says "swap renderer X for renderer Y and keep the
existing test suite green," before doing the swap grep the test files
in the regression sweep for X-specific APIs (matplotlib:
``callbacks\.process``, ``\.transData``, ``\.fig\.bbox``,
``get_window_extent``, ``MouseEvent``; pyqtgraph: ``sigMouseClicked``,
``mapSceneToView``). Each match is a test that will need a Qt-native
rewrite, OR an architectural decision to drop it. Surface that count in
the planning return so the orchestrator can budget a follow-up subtask
instead of treating the renderer swap as a one-shot diff.

Update 2026-06-11 (M5, ``canvas_order`` PlotCanvas→PgHeatmapCanvas):
grep PRODUCTION code for the swapped instance attribute too, not just
tests. The plan named only the instantiation + toolbar branch, but
``grep -n "canvas_order" mf4_analyzer/ui/`` exposed two unguarded
mpl-contract consumers that no test covered:
``MainWindow._update_all_tick_density_pair`` drove
``canvas_order.fig.axes`` + ``draw_idle()`` (AttributeError on every
tick-density change) and ``ChartStack.full_reset_all`` called
``canvas_order.full_reset()`` (absent on the pg canvas → crash on file
close). The audit unit is the canvas's consumed ATTRIBUTE SURFACE
(``\.fig\b``, ``draw_idle``, ``axes_list``, ``full_reset``,
``span_selector``) across the whole package — fix call sites via the
cross-renderer contract (``set_tick_density``) or add the missing
contract method to the new canvas; report both as named deviations.
