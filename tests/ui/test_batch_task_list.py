"""Tests for ``TaskListWidget`` (W6 §3.5).

The widget renders a collapsible header + body of per-task rows driven by
``BatchProgressEvent`` instances. It emits no signals — pure read-only
view.
"""


def test_apply_dry_run_renders_rows(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"), ("b.mf4", "sig", "fft")],
                    outputs_per_task=2)
    assert w.row_count() == 2
    assert w.row_icon(0) == "⏸"
    # Header (idle): "▾ 2 任务待执行 · 4 输出"
    assert "2 任务" in w.header_text()
    assert "4 输出" in w.header_text()


def test_on_event_updates_icons_and_progress(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    from mf4_analyzer.batch import BatchProgressEvent
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"), ("b.mf4", "sig", "fft")],
                    outputs_per_task=1)
    w.on_run_started()
    w.on_event(BatchProgressEvent(
        kind="task_started", task_index=1, total=2,
        file_name="a.mf4", signal="sig", method="fft"))
    assert w.row_icon(0) == "⟳"
    # Header (running): includes "进度 0/2" before first done
    assert "0/2" in w.header_text() or "0 / 2" in w.header_text()
    w.on_event(BatchProgressEvent(
        kind="task_done", task_index=1, total=2,
        file_name="a.mf4", signal="sig", method="fft"))
    assert w.row_icon(0) == "✓"
    assert "1/2" in w.header_text() or "1 / 2" in w.header_text()
    # Progress bar value matches
    assert w.progress_value() == 50  # 1/2 * 100


def test_on_event_failed_and_cancelled_icons(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    from mf4_analyzer.batch import BatchProgressEvent
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"),
                     ("b.mf4", "sig", "fft"),
                     ("c.mf4", "sig", "fft")], outputs_per_task=1)
    w.on_event(BatchProgressEvent(
        kind="task_failed", task_index=1, total=3,
        file_name="a.mf4", signal="sig", method="fft",
        error="missing signal: sig"))
    assert w.row_icon(0) == "✗"
    assert "missing" in w.row_tooltip(0).lower()
    w.on_event(BatchProgressEvent(
        kind="task_cancelled", task_index=2, total=3,
        file_name="b.mf4", signal="sig", method="fft"))
    assert w.row_icon(1) == "—"


def test_collapse_toggle(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft")], outputs_per_task=1)
    assert w.is_expanded() is True   # Default expanded
    w.toggle_collapse()
    assert w.is_expanded() is False
    # Body widget hidden when collapsed
    assert not w._body.isVisible()
