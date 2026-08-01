"""Tests for ``TaskListWidget`` (W6 §3.5).

The widget renders a collapsible header + body of per-task rows driven by
``BatchProgressEvent`` instances. It emits no signals — pure read-only
view.
"""

import pytest


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


@pytest.mark.parametrize(
    ("group_by", "artifact_count"),
    (("none", 8), ("source", 6), ("channel", 6)),
)
def test_apply_dry_run_uses_exact_optional_artifact_count(
    qtbot, group_by, artifact_count,
):
    """Grouped previews change output count without collapsing task rows."""
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget

    w = TaskListWidget()
    qtbot.addWidget(w)
    tasks = [
        (source, channel, "time")
        for source in ("a.csv", "b.csv")
        for channel in ("speed", "accel")
    ]

    w.apply_dry_run(
        tasks, outputs_per_task=2, artifact_count=artifact_count,
    )

    assert w.row_count() == 4
    assert str(artifact_count) in w.header_text()
    assert group_by in {"none", "source", "channel"}


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


def test_empty_task_list_hides_body_and_populated_body_is_height_capped(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget

    w = TaskListWidget()
    qtbot.addWidget(w)
    w.show()

    assert not w._body.isVisible()
    assert not w._toggle_btn.isEnabled()

    w.apply_dry_run(
        [(f"{index}.mf4", "sig", "fft") for index in range(20)],
        outputs_per_task=1,
    )

    assert w._body.isVisible()
    assert w._toggle_btn.isEnabled()
    assert w._body.maximumHeight() == 120


def test_skipped_resumed_cancelled_are_terminal_progress_states(qtbot):
    from mf4_analyzer.batch import BatchProgressEvent
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget

    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run(
        [(f"{i}.mf4", "sig", "fft") for i in range(3)],
        outputs_per_task=1,
    )
    w.on_run_started()

    w.on_event(BatchProgressEvent(
        kind="task_skipped", task_index=1, total=3, message="existing",
    ))
    w.on_event(BatchProgressEvent(
        kind="task_resumed", task_index=2, total=3, message="checksum ok",
    ))
    w.on_event(BatchProgressEvent(
        kind="task_cancelled", task_index=3, total=3, message="cancelled",
    ))

    assert [w.row_icon(i) for i in range(3)] == ["↷", "↻", "—"]
    assert w.progress_value() == 100
    assert "3/3" in w.header_text()
    assert "existing" in w.row_tooltip(0)
    assert "checksum" in w.row_tooltip(1)


def test_unexpected_finish_never_marks_running_row_done(qtbot):
    from mf4_analyzer.batch import BatchProgressEvent, BatchRunResult
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget

    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft")], outputs_per_task=1)
    w.on_run_started()
    w.on_event(BatchProgressEvent(
        kind="task_started", task_index=1, total=1,
    ))

    w.on_run_finished(BatchRunResult(
        status="blocked", blocked=["runner crashed: boom"],
    ))

    assert w.row_icon(0) == "✗"
    assert "boom" in w.row_tooltip(0)
    assert w.row_icon(0) != "✓"
    assert w.progress_value() == 100


def test_artifact_open_request_requires_explicit_row_activation(qtbot):
    from mf4_analyzer.batch import BatchProgressEvent
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget

    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft")], outputs_per_task=2)
    requested = []
    w.artifactOpenRequested.connect(requested.append)
    w.on_event(BatchProgressEvent(
        kind="task_done", task_index=1, total=1,
        data_path="/tmp/out.csv", image_path="/tmp/out.png",
    ))

    assert requested == []
    assert w.row_artifact_paths(0) == ("/tmp/out.csv", "/tmp/out.png")

    w._body.itemDoubleClicked.emit(w._body.item(0))

    assert requested == ["/tmp/out.png"]
