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


@pytest.mark.parametrize(
    "machine_group",
    (
        "default",
        "unresolved-source:hdf:3af2470a39ba076234c87567",
        "file_id:17",
    ),
)
def test_machine_group_identities_never_reach_a_display_name(machine_group):
    """The runner's own placeholders are not names a reader should ever see.

    ``ae6982d`` stripped them from chart titles only; the preview dialog kept
    showing ``unresolved-source:hdf:3af2470…`` because this side filtered
    ``default`` alone.
    """

    group = group_render_tasks(
        (_task("/data/run.mf4", machine_group, "acc", "a"),),
        {"render_group_by": "source"},
    )[0]

    assert group.display_name == "run.mf4"
    assert machine_group not in group.display_name


@pytest.mark.parametrize(
    ("group_identity", "expected_stem"),
    (
        ("default", "run__time__c46b6d7c"),
        (
            "unresolved-source:hdf:3af2470a39ba076234c87567",
            "run__unresolved-source_hdf_3af2470a39ba076234c87567"
            "__time__c34b68e1",
        ),
        ("file_id:17", "run__file_id_17__time__2c6745f6"),
        ("raster 7", "run__raster_7__time__5f06e7fc"),
    ),
)
def test_display_name_filtering_does_not_change_any_output_stem(
    group_identity, expected_stem,
):
    """Output file names come from ``identity.stem``, never ``display_name``.

    Guards the D-A5 blast radius directly: hiding machine tokens from the
    reader must not move a single produced byte, so these stems are pinned
    literally — including the ones that still carry the machine token, which
    is the pre-existing on-disk contract.
    """

    group = group_render_tasks(
        (_task("/data/run.mf4", group_identity, "acc", "a"),),
        {"render_group_by": "source", "render_layout": "overlay"},
    )[0]

    assert group.identity.stem == expected_stem


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
