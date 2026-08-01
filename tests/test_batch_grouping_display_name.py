from __future__ import annotations

import pytest

from mf4_analyzer.batch_grouping import RenderTask, group_render_tasks
from mf4_analyzer.batch_output import TaskOutputIdentity


def _task(source: str, group: str, channel: str, token: str) -> RenderTask:
    return RenderTask(
        source_key=token,
        channel=channel,
        identity=TaskOutputIdentity(
            task_id=f"task-{token}",
            source_identity=source,
            group_identity=group,
            channel_identity=channel,
            stem=f"stem-{token}",
        ),
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("/private/data/road-run.mf4", "road-run.mf4 · raster 7"),
        (r"C:\measurements\road-run.mf4", "road-run.mf4 · raster 7"),
    ),
)
def test_source_group_display_name_is_readable_without_path_or_raw_key(
    source, expected,
):
    group = group_render_tasks(
        (_task(source, "raster 7", "acc", "a"),),
        {"render_group_by": "source", "render_layout": "overlay"},
    )[0]

    assert group.display_name == expected
    assert source not in group.display_name
    assert group.group_key not in group.display_name
    assert group.group_key.startswith("[")


def test_default_source_group_does_not_add_internal_default_label():
    group = group_render_tasks(
        (_task("/data/run.mf4", "default", "acc", "a"),),
        {"render_group_by": "source"},
    )[0]

    assert group.display_name == "run.mf4"


@pytest.mark.parametrize("channel", ('acc[front]",raw', 'speed[rear]'))
def test_channel_group_preserves_legal_channel_text_exactly(channel):
    group = group_render_tasks(
        (
            _task("/data/a.mf4", "default", channel, "a"),
            _task("/data/b.mf4", "default", channel, "b"),
        ),
        {"render_group_by": "channel", "render_layout": "subplot"},
    )[0]

    assert group.display_name == channel
    assert group.group_key == channel
