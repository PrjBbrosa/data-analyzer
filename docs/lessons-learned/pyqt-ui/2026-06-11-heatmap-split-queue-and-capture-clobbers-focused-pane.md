---
role: pyqt-ui
tags: [qthread, worker, queue, sequential, multiview, heatmap, pane, capture, source-routing, cache]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
V7b turned the single-worker ``do_fft_time`` / ``do_order_time`` (which
computed only the focused pane) into a per-section SEQUENTIAL compute
queue so a split 2-pane heatmap computes both panes, each pane rendering
its own ``(fid, ch)`` source onto ``page.pane_canvas(pane_idx)``.

## Lesson
Two coupled traps. (1) A section's sequential job queue must reuse the
SAME single worker/QThread field, not spawn N threads: the head job
dispatches, ``finished`` caches + renders onto the job's stored
``pane_idx`` (NOT the focused pane / pane 0 — that's the load-bearing
correctness), and ``thread.finished -> _on_*_thread_done`` clears the
refs THEN pumps the next job — the ref-clear must precede the next
dispatch or the new job's ``isRunning()`` re-entry guard sees the
just-finished thread and silently drops it. ``closeEvent`` must empty
the queues BEFORE its cooperative ``quit()+wait()`` drain, else the
``thread.finished`` it triggers pumps a NEW worker onto a dying window.
(2) ``do_*`` calls ``_capture_active_analysis_view`` first, and capture
OVERWRITES the FOCUSED pane's source from the inspector's
``current_signal()`` / ``current_rpm()`` — only NON-focused panes keep
their stored sources. So in a split compute the focused pane's source
comes from the inspector echo, not from whatever you set on
``state.panes[focus]``; tests that set ``state.panes[0].sources``
directly get clobbered (Order needs ``rpm_source`` too, and capture sets
it to ``None`` if ``combo_rpm`` is empty → the pane's job is skipped and
the pane shows no result).

## How to apply
When adding a multi-target sequential compute to a single-worker host:
store the render target (``pane_idx``) in the pending dict, render via
``page.pane_canvas(pane_idx)`` in the finished slot, clear thread refs
before pumping the next job, and clear the queue in ``closeEvent``
before draining. When driving a split-pane compute in a test or
restore, wire the FOCUSED pane through the inspector combos
(``_echo_combo_signal(ctx.combo_sig, src)`` and, for Order,
``ctx.combo_rpm``) and set only the non-focused panes on the view state
— or the capture-on-compute step will silently replace the focused
pane's source with the inspector selection. Symptom: "non-focused pane
renders, focused pane is blank / shows the wrong source".
