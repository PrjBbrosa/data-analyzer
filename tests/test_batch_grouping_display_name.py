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


def _frf_task(source, group, input_channel, output_channel, token):
    pair_label = f"{output_channel} / {input_channel}"
    return RenderTask(
        source_key=token,
        channel=pair_label,
        input_channel=input_channel,
        output_channel=output_channel,
        identity=TaskOutputIdentity(
            task_id=f"task-{token}",
            source_identity=source,
            group_identity=group,
            channel_identity=pair_label,
            stem=f"stem-{token}",
            input_channel_identity=input_channel,
            output_channel_identity=output_channel,
        ),
    )


def test_frf_source_grouping_means_same_source_and_input_multiple_outputs():
    groups = group_render_tasks(
        (
            _frf_task("/data/a.mf4", "g", "cmd", "actual", "a1"),
            _frf_task("/data/a.mf4", "g", "cmd", "angle", "a2"),
            _frf_task("/data/a.mf4", "g", "other", "actual", "a3"),
        ),
        {"render_group_by": "source", "frequency_scale": "log"},
    )

    assert [len(group.members) for group in groups] == [2, 1]
    assert {member.input_channel for member in groups[0].members} == {"cmd"}
    assert all(len(member.identity.input_channel_identity) > 0 for group in groups for member in group.members)


def test_frf_channel_grouping_means_same_directional_pair_across_sources():
    groups = group_render_tasks(
        (
            _frf_task("/data/a.mf4", "g1", "cmd", "actual", "a"),
            _frf_task("/data/b.mf4", "g2", "cmd", "actual", "b"),
            _frf_task("/data/b.mf4", "g2", "actual", "cmd", "reverse"),
        ),
        {"render_group_by": "channel", "phase_mode": "unwrapped"},
    )

    assert sorted(len(group.members) for group in groups) == [1, 2]
    paired = next(group for group in groups if len(group.members) == 2)
    assert {(member.input_channel, member.output_channel) for member in paired.members} == {
        ("cmd", "actual"),
    }
    assert all(len(member) == 4 for member in paired.identity.members)


def test_frf_render_group_identity_includes_render_params_not_member_order():
    tasks = (
        _frf_task("/data/a.mf4", "g1", "cmd", "actual", "a"),
        _frf_task("/data/b.mf4", "g2", "cmd", "actual", "b"),
    )
    first = group_render_tasks(
        tasks,
        {"render_group_by": "channel", "coherence_threshold": 0.8},
    )[0]
    reversed_group = group_render_tasks(
        tuple(reversed(tasks)),
        {"render_group_by": "channel", "coherence_threshold": 0.8},
    )[0]
    changed = group_render_tasks(
        tasks,
        {"render_group_by": "channel", "coherence_threshold": 0.5},
    )[0]

    assert first.identity == reversed_group.identity
    assert first.identity.group_id != changed.identity.group_id


def test_frf_render_group_identity_includes_output_byte_settings():
    tasks = (
        _frf_task("/data/a.mf4", "g1", "cmd", "actual", "a"),
        _frf_task("/data/b.mf4", "g2", "cmd", "actual", "b"),
    )
    first = group_render_tasks(
        tasks,
        {"render_group_by": "channel"},
        outputs={"image_width": 1920, "image_dpi": 144},
    )[0]
    changed = group_render_tasks(
        tasks,
        {"render_group_by": "channel"},
        outputs={"image_width": 2560, "image_dpi": 144},
    )[0]

    assert first.identity.group_id != changed.identity.group_id


def test_render_group_rejects_mixed_single_channel_and_frf_tasks():
    with pytest.raises(ValueError, match="cannot mix"):
        group_render_tasks(
            (
                _task("/data/a.mf4", "default", "acc", "single"),
                _frf_task("/data/a.mf4", "default", "cmd", "acc", "pair"),
            ),
            {"render_group_by": "none"},
        )


def test_render_task_derives_pair_only_from_matching_identity():
    identity = _frf_task(
        "/data/a.mf4", "default", "cmd", "acc", "pair",
    ).identity
    derived = RenderTask(source_key="a", channel="acc / cmd", identity=identity)
    assert (derived.input_channel, derived.output_channel) == ("cmd", "acc")
    with pytest.raises(ValueError, match="do not match"):
        RenderTask(
            source_key="a",
            channel="acc / other",
            identity=identity,
            input_channel="other",
            output_channel="acc",
        )
