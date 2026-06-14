---
role: pyqt-ui
tags: [renderer-swap, matplotlib, pyqtgraph, event-dispatch, test-coupling, contract-test, production-consumers, toolbar-branch-flip]
created: 2026-05-28
updated: 2026-06-14
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

Update 2026-06-11 (M6 visual gate): a consumer can FAIL SILENTLY rather
than crash. ``PgNavigationToolbar`` (the shim attached to every pg
canvas) walks ``canvas.axes_list`` / ``canvas._channel_lines`` /
``reset_view_to_data_extents`` — all of which exist on
``TimeDomainCanvasPG`` but NOT on ``PgHeatmapCanvas``. Because every
access is ``getattr(..., None)``-guarded, the toolbar's
home/back/forward/pan/zoom buttons became inert on the order heatmap
with no traceback (measured: ``_view_boxes()`` returned ``[]`` and
``home()`` left a zoomed view unchanged). No unit test caught it — the
gap only shows under a live click. The fix is the same contract-method
move: add ``reset_view_to_data_extents`` to the new canvas (``home()``
already prefers it) rather than special-casing the toolbar. When grepping
the swapped instance attribute, treat ``getattr``-guarded reads as
deviations too: a guard prevents a crash but also hides a dead feature,
so exercise the toolbar buttons on the live canvas, not just the render
path.

Update 2026-06-11 (M11, ``canvas_fft`` PlotCanvas→PgLineCanvas, plan-1
closing gate): the FFT canvas was a ``FigureCanvas``, so it took
``_ChartCard``'s ``else`` toolbar branch (matplotlib ``NavigationToolbar``,
whose home/pan/zoom drive mpl axes natively). Adding ``PgLineCanvas`` to
the ``isinstance(canvas, (TimeDomainCanvasPG, PgHeatmapCanvas, ...))``
branch flips it to ``PgNavigationToolbar`` — so the swap doesn't just lose
the old toolbar's behavior, it ROUTES THROUGH a different toolbar whose
``_view_boxes`` walks ``canvas.axes_list`` → ``ax.view_box``. PgLineCanvas
has no ``axes_list`` (it has two FIXED PlotItems, not dynamic per-channel
axes), so pan/box-zoom mode was a silent no-op and Home was inert — same
M6 failure, new trigger. Fix: expose ``axes_list`` as static one-shim-per-
plot (``_AxisShim.view_box``; no replot re-bind needed since the plots
never rebuild) AND add ``reset_view_to_data_extents`` (Home restores the
last ``plot_spectra`` xlim + manual/auto Y). Also: the FFT card's 图表选项
button silently no-ops in production because PgLineCanvas (like
PgHeatmapCanvas) has no ``open_chart_options_dialog`` — only
TimeDomainCanvasPG does; this matches the established order/fft-time
precedent, not a new regression, but note it. Test coupling this round was
``win.canvas_fft.fig.axes`` + ``ax.get_ylabel()`` / ``ax.get_xlim()`` in
two render tests — rewrite to ``canvas._plot_amp.getAxis('left').labelText``
and ``plot.vb.viewRange()`` (the pg analogues), don't stub ``fig`` on the
pg widget.

Update 2026-06-14 (FFT view-history C, ``PgLineCanvas`` back/forward): the
attribute audit must include the card-side REGISTRATION GATE, not only the
attributes the toolbar reads. ``register_replot_callback`` is never read by
``PgNavigationToolbar`` — but ``_ChartCard`` gates BOTH
``register(toolbar.apply_current_mouse_mode)`` AND
``register(toolbar.rebind_history_capture)`` on
``callable(getattr(canvas, 'register_replot_callback', None))``
(chart_stack.py:1134-1141). So a pg canvas that already has ``axes_list`` +
``_channel_lines`` + ``reset_view_to_data_extents`` STILL has silently-dead
back/forward (history never seeds a baseline, ``sigRangeChangedManually`` is
never bound) AND a mouse mode that silently resets after every replot, purely
because the callback method is absent and the whole ``if callable(register):``
block is skipped. Fix: add ``register_replot_callback``/``_run_replot_callbacks``
and CALL ``_run_replot_callbacks()`` at the tail of every rebuild entry point
(``plot_spectra``/``plot_time_preview``/``full_reset``) — registration alone is
inert without the per-rebuild fire. Also, history snapshot/restore reads
``canvas._channel_lines`` as ``{name: (handle, _)}`` where ``handle`` needs
``get_xlim/set_xlim/get_ylim/set_ylim`` — a fixed-PlotItem canvas can satisfy
this with a one-time ``_HistoryHandle(vb, with_y=...)`` shell (no per-rebuild
re-bind, the PlotItems never rebuild), and the time-preview handle's
``set_ylim`` must be a NO-OP so a history restore only rewinds X (its Y is
auto-framed to a graticule and a Y restore would fight that). Drive the LIVE
toolbar: build ``PgNavigationToolbar(canvas)``, register the two callbacks as
the card does, ``plot_spectra``, assert ``_view_stack`` seeded, pan a vb,
``_commit_pending_view``, then ``back()``/``forward()`` and assert the X range
actually moved — a code-review of "the method exists now" does not prove the
gate opened.

Update 2026-06-11 (heatmap pan/box-zoom parity, closing the M6 partial
fix): M6 gave ``PgHeatmapCanvas`` only ``reset_view_to_data_extents``
(Home) and NEVER added ``axes_list`` — so the heatmap was a HALF-FIXED
canvas: Home worked while pan/box-zoom stayed silently dead in BOTH the
Order (``with_slice=False``) and FFT-vs-Time (``with_slice=True``)
production sections. Runtime proof: after ``toolbar.set_zoom_mode()`` the
main ``_plot.vb.state['mouseMode']`` was still PanMode(3), box-zoom was a
no-op, ``_view_boxes()`` returned ``[]`` and ``_primary_view_box()`` was
``None``. The lesson within the lesson: "Home works" does NOT imply the
toolbar is wired — Home reads ``reset_view_to_data_extents`` while
pan/zoom read ``axes_list``; they are INDEPENDENT contract surfaces, so
verify each button class separately on the live canvas. Fix is identical
to M11: expose ``axes_list`` as one static ``_AxisShim(self._plot.vb)``.
Decision on the FFT-vs-Time slice row: EXCLUDE it from ``axes_list``. The
slice ViewBox is a separate, click-driven auxiliary readout whose X axis
is Frequency (Hz) and is NOT XLinked to the heatmap's Time axis (verified:
``slice.vb.linkedView(0) is not main.vb``), so a box-zoom rectangle
dragged on the time×freq map is meaningless against the slice's
freq×amplitude axes, and ``_set_all_mouse_modes``/history would conflate
two unrelated coordinate systems. The ``_AxisShim`` is a private copy
(``__slots__``) rather than a cross-import — ``line_canvas`` already
imports ``_tick_counts_to_density`` from ``heatmap_canvas``, so a reverse
import would cycle (future cleanup: hoist both shims to ``_shared``).
