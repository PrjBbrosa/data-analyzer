from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

import mf4_analyzer.batch_manifest as manifest_module
from mf4_analyzer.batch_manifest import (
    BatchManifestRecorder,
    GroupMemberResumeFact,
    ManifestRecipeMismatch,
    ManifestValidationError,
    RetryScope,
    artifact_facts,
    auto_nfft_policy_is_current,
    derive_summary,
    find_resumable_entry,
    find_resumable_group,
    load_batch_manifest,
    retry_failed_scope,
    source_file_facts,
)
from mf4_analyzer.signal.analysis_defaults import AUTO_NFFT_POLICY_VERSION


def _done_entry(source_path, artifact_path):
    source = source_file_facts(source_path, source_identity=str(source_path.resolve()))
    return {
        "task_id": "task-1",
        "source_id": "source-1",
        "source": {
            **source,
            "group_identity": "group-a",
            "display_name": "measurement",
        },
        "channel": "sig",
        "channel_unit": "m/s²",
        "method": "fft",
        "requested_params": {"nfft": 64},
        "effective_facts": {"fs": 1024.0, "nfft_effective": 64},
        "status": "done",
        "message": "",
        "warnings": [],
        "started_at": "2026-07-28T10:00:00Z",
        "finished_at": "2026-07-28T10:00:01Z",
        "artifacts": {
            "data": artifact_facts(
                artifact_path, kind="data", artifact_format="csv",
            ),
        },
    }


def _task_entry(status, *, source_id="source-1", channel="sig", method="fft"):
    return {
        "task_id": f"task-{source_id}",
        "source_id": source_id,
        "source": {
            "identity": f"identity-{source_id}",
            "path": None,
            "size": None,
            "mtime_ns": None,
        },
        "channel": channel,
        "channel_unit": "",
        "method": method,
        "requested_params": {},
        "effective_facts": {},
        "status": status,
        "message": "",
        "warnings": [],
        "started_at": None,
        "finished_at": "2026-07-28T10:00:01Z",
        "artifacts": {},
    }


def _manifest(entries, *, recipe_fingerprint="recipe-1", run_status="done"):
    return {
        "schema_version": 1,
        "run_id": "run-valid",
        "created_at": "2026-07-28T10:00:00Z",
        "finished_at": (
            None if run_status == "running" else "2026-07-28T10:00:01Z"
        ),
        "app_version": "v-test",
        "preset_name": "preset",
        "normalized_recipe": {"method": "fft", "params": {}},
        "recipe_fingerprint": recipe_fingerprint,
        "requested_output_settings": {},
        "summary": derive_summary(entries),
        "run_status": run_status,
        "blocked_reasons": [],
        "entries": entries,
    }


def _group_entry(image_path, members, *, status="done", degraded_reason=""):
    return {
        "group_id": "group-1",
        "stem": "time__source-a",
        "group_by": "source",
        "layout": "overlay",
        "members": [
            {"task_id": task_id, "source": dict(source)}
            for task_id, source in members
        ],
        "requested_outputs": {"image": "png"},
        "effective_outputs": {"image": "png"},
        "degraded_reason": degraded_reason,
        "status": status,
        "message": "",
        "warnings": [],
        "artifact": artifact_facts(
            image_path, kind="image", artifact_format="png",
        ) if image_path is not None else None,
    }


def _recorder(tmp_path, *, run_id="run-groups"):
    return BatchManifestRecorder(
        tmp_path,
        preset_name="time groups",
        normalized_recipe={"method": "time", "params": {}},
        recipe_fingerprint="recipe-1",
        requested_outputs={"export_data": True, "export_image": True},
        app_version="v-test",
        run_id=run_id,
    )


def test_summary_is_derived_only_from_terminal_task_entries():
    entries = [
        {"status": "done"},
        {"status": "failed"},
        {"status": "cancelled"},
        {"status": "skipped"},
        {"status": "resumed"},
        {"status": "done"},
    ]

    assert derive_summary(entries) == {
        "done": 2,
        "failed": 1,
        "cancelled": 1,
        "skipped": 1,
        "resumed": 1,
        "total": 6,
    }


def test_default_manifest_has_no_render_groups_and_unchanged_summary_shape(
    tmp_path,
):
    recorder = _recorder(tmp_path, run_id="run-default-shape")

    partial = json.loads(recorder.start().read_text(encoding="utf-8"))
    final = load_batch_manifest(recorder.finish(run_status="done"))

    expected_summary = {
        "done": 0,
        "failed": 0,
        "cancelled": 0,
        "skipped": 0,
        "resumed": 0,
        "total": 0,
    }
    assert partial["summary"] == expected_summary
    assert final["summary"] == expected_summary
    assert "render_groups" not in partial
    assert "render_groups" not in final
    assert "image_count" not in partial
    assert "image_count" not in final


def test_group_upsert_is_visible_in_partial_journal_immediately(tmp_path):
    recorder = _recorder(tmp_path, run_id="run-group-journal")
    source = {
        "identity": "source-a",
        "path": str(tmp_path / "source.csv"),
        "size": 12,
        "mtime_ns": 34,
    }
    group = _group_entry(None, [("task-a", source)], status="running")

    written_path = recorder.upsert_render_group(group)

    assert written_path == recorder.partial_path
    partial = load_batch_manifest(recorder.partial_path)
    assert partial["render_groups"] == [group]


def test_group_upsert_replaces_instead_of_duplicating(tmp_path):
    recorder = _recorder(tmp_path, run_id="run-group-upsert")
    source = {
        "identity": "source-a",
        "path": None,
        "size": 12,
        "mtime_ns": 34,
    }
    running = _group_entry(None, [("task-a", source)], status="running")
    failed = dict(running, status="failed", message="render failed")

    recorder.upsert_render_group(running)
    recorder.upsert_render_group(failed)

    partial = json.loads(recorder.partial_path.read_text(encoding="utf-8"))
    assert partial["render_groups"] == [failed]
    final = load_batch_manifest(recorder.finish(run_status="partial"))
    assert final["render_groups"] == [failed]


def test_task_upsert_replaces_instead_of_duplicating_and_record_is_alias(
    tmp_path,
):
    recorder = _recorder(tmp_path, run_id="run-task-upsert")
    running = _task_entry("failed")
    replacement = dict(running, message="latest failure")

    recorder.record(running)
    recorder.upsert_task(replacement)

    partial = json.loads(recorder.partial_path.read_text(encoding="utf-8"))
    assert partial["entries"] == [replacement]


def test_old_manifest_without_render_groups_still_loads():
    old_manifest = _manifest([_task_entry("done")])

    loaded = load_batch_manifest(old_manifest)

    assert loaded == old_manifest
    assert "render_groups" not in loaded


def test_frf_manifest_entry_requires_and_preserves_directional_pair():
    entry = _task_entry("done", channel="response / command", method="frf")
    entry["frf_pair"] = {
        "input": {"channel": "command", "unit": "V"},
        "output": {"channel": "response", "unit": "N"},
    }

    loaded = load_batch_manifest(_manifest([entry]))

    assert loaded["entries"][0]["frf_pair"] == entry["frf_pair"]


@pytest.mark.parametrize(
    "pair",
    (
        None,
        {},
        {"input": {"channel": "", "unit": "V"}, "output": {"channel": "y", "unit": "N"}},
        {"input": {"channel": "x", "unit": 1}, "output": {"channel": "y", "unit": "N"}},
    ),
)
def test_frf_manifest_entry_rejects_missing_or_malformed_pair(pair):
    entry = _task_entry("done", channel="response / command", method="frf")
    if pair is not None:
        entry["frf_pair"] = pair

    with pytest.raises(ManifestValidationError, match="frf_pair"):
        load_batch_manifest(_manifest([entry]))


def test_manifest_recorder_writes_partial_then_terminal_v1_atomically(tmp_path):
    source_path = tmp_path / "source.csv"
    source_path.write_text("source", encoding="utf-8")
    artifact_path = tmp_path / "result.csv"
    artifact_path.write_text("frequency,amplitude\n1,2\n", encoding="utf-8")
    recorder = BatchManifestRecorder(
        tmp_path,
        preset_name="FFT batch",
        normalized_recipe={"method": "fft", "params": {"nfft": 64}},
        recipe_fingerprint="recipe-1",
        requested_outputs={"export_data": True, "export_image": False},
        app_version="v-test",
        run_id="run-1",
    )

    recorder.start()
    assert recorder.partial_path.exists()
    recorder.record(_done_entry(source_path, artifact_path))
    final_path = recorder.finish(run_status="done", blocked_reasons=[])

    assert final_path.name == "batch-manifest__run-1.json"
    assert not recorder.partial_path.exists()
    assert not list(tmp_path.glob(".batch-manifest__run-1.*"))
    manifest = load_batch_manifest(final_path)
    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "run-1"
    assert manifest["app_version"] == "v-test"
    assert manifest["preset_name"] == "FFT batch"
    assert manifest["recipe_fingerprint"] == "recipe-1"
    assert manifest["run_status"] == "done"
    assert manifest["summary"]["done"] == 1
    entry = manifest["entries"][0]
    assert entry["source"]["size"] == source_path.stat().st_size
    assert entry["artifacts"]["data"]["size"] == artifact_path.stat().st_size
    assert entry["artifacts"]["data"]["sha256"] == hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()


def test_manifest_serializes_nonfinite_values_as_strict_json_markers(tmp_path):
    recorder = BatchManifestRecorder(
        tmp_path,
        preset_name="invalid recipe",
        normalized_recipe={
            "method": "fft",
            "params": {"db_reference": float("nan")},
        },
        recipe_fingerprint="recipe-invalid",
        requested_outputs={"image_dpi": float("inf")},
        run_id="run-nonfinite",
    )
    recorder.record({
        "task_id": "invalid",
        "status": "failed",
        "effective_facts": {"fs": float("-inf")},
    })

    final_path = recorder.finish(run_status="blocked")
    manifest = json.loads(
        final_path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            AssertionError(f"non-standard JSON constant: {value}")
        ),
    )

    assert manifest["normalized_recipe"]["params"]["db_reference"] == {
        "__nonfinite_float__": "nan",
    }
    assert manifest["requested_output_settings"]["image_dpi"] == {
        "__nonfinite_float__": "+inf",
    }
    assert manifest["entries"][0]["effective_facts"]["fs"] == {
        "__nonfinite_float__": "-inf",
    }


def test_manifest_accepts_additive_time_axis_effective_facts(tmp_path):
    source_path = tmp_path / "source.csv"
    artifact_path = tmp_path / "out.csv"
    source_path.write_text("time,sig\n0,1\n", encoding="utf-8")
    artifact_path.write_text("frequency_hz,amplitude\n0,1\n", encoding="utf-8")
    entry = _done_entry(source_path, artifact_path)
    entry["effective_facts"]["time_axis"] = {
        "reason": "auto_nonuniform",
        "method": "median_dt",
        "original_fs": 500.0,
        "original_time_source": "column",
        "estimated_fs": 498.0,
        "relative_jitter": 0.2,
        "dt_min": 0.0016,
        "dt_max": 0.0024,
        "n_samples": 128,
        "applied_at": "2026-09-04T00:00:00.000Z",
    }
    recorder = BatchManifestRecorder(
        tmp_path,
        preset_name="FFT batch",
        normalized_recipe={"method": "fft_time", "params": {}},
        recipe_fingerprint="recipe-time-axis",
        requested_outputs={},
        run_id="run-time-axis",
        app_version="v-test",
    )
    recorder.start()
    recorder.record(entry)
    final_path = recorder.finish(run_status="done", blocked_reasons=[])
    manifest = load_batch_manifest(final_path)
    facts = manifest["entries"][0]["effective_facts"]["time_axis"]
    assert facts["reason"] == "auto_nonuniform"
    assert facts["method"] == "median_dt"
    assert facts["estimated_fs"] == pytest.approx(498.0)


def test_manifest_finish_on_cancel_keeps_completed_and_cancelled_facts(tmp_path):
    recorder = BatchManifestRecorder(
        tmp_path,
        preset_name="cancelled",
        normalized_recipe={"method": "fft", "params": {}},
        recipe_fingerprint="recipe-cancel",
        requested_outputs={},
        run_id="run-cancel",
    )
    recorder.start()
    recorder.record({"task_id": "a", "status": "done"})
    recorder.record({"task_id": "b", "status": "cancelled"})

    final_path = recorder.finish(
        run_status="cancelled", blocked_reasons=["operator cancelled"],
    )

    manifest = json.loads(final_path.read_text(encoding="utf-8"))
    assert manifest["summary"]["done"] == 1
    assert manifest["summary"]["cancelled"] == 1
    assert manifest["run_status"] == "cancelled"
    assert manifest["blocked_reasons"] == ["operator cancelled"]


def test_resume_requires_recipe_task_source_stat_and_artifact_checksum(tmp_path):
    source_path = tmp_path / "source.csv"
    source_path.write_text("source-v1", encoding="utf-8")
    artifact_path = tmp_path / "result.csv"
    artifact_path.write_text("result-v1", encoding="utf-8")
    entry = _done_entry(source_path, artifact_path)
    manifest = _manifest([entry])
    current_source = source_file_facts(
        source_path, source_identity=str(source_path.resolve()),
    )
    required = {"data": "csv"}

    assert find_resumable_entry(
        manifest,
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=current_source,
        required_artifacts=required,
    ) is entry

    for changed in (
        {"recipe_fingerprint": "recipe-2"},
        {"task_id": "task-2"},
        {"source_id": "source-2"},
        {"source_identity": str(tmp_path / "other.csv")},
    ):
        kwargs = {
            "recipe_fingerprint": "recipe-1",
            "task_id": "task-1",
            "source_id": "source-1",
            "source_identity": str(source_path.resolve()),
            "source_stat": current_source,
            "required_artifacts": required,
        }
        kwargs.update(changed)
        assert find_resumable_entry(manifest, **kwargs) is None

    stale_stat = dict(current_source, size=current_source["size"] + 1)
    assert find_resumable_entry(
        manifest,
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=stale_stat,
        required_artifacts=required,
    ) is None

    artifact_path.write_text("tampered", encoding="utf-8")
    assert find_resumable_entry(
        manifest,
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=current_source,
        required_artifacts=required,
    ) is None


def test_resume_rejects_degraded_entry_even_if_artifacts_later_appear(tmp_path):
    source_path = tmp_path / "source.csv"
    source_path.write_text("source-v1", encoding="utf-8")
    data_path = tmp_path / "result.csv"
    data_path.write_text("result-v1", encoding="utf-8")
    image_path = tmp_path / "result.pdf"
    image_path.write_bytes(b"%PDF-1.4 fake")
    entry = _done_entry(source_path, data_path)
    entry.update({
        "requested_outputs": {"data": "csv", "image": "pdf"},
        "effective_outputs": {"data": "csv"},
        "degraded_reason": "图片/PDF 导出后端不可用，本次仅导出数据文件",
    })
    entry["artifacts"]["image"] = artifact_facts(
        image_path, kind="image", artifact_format="pdf",
    )
    manifest = _manifest([entry])

    matched = find_resumable_entry(
        manifest,
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=source_file_facts(
            source_path, source_identity=str(source_path.resolve()),
        ),
        required_artifacts={"data": "csv", "image": "pdf"},
    )

    assert matched is None


def test_resume_rejects_missing_checksum_even_when_same_named_file_exists(tmp_path):
    source_path = tmp_path / "source.csv"
    source_path.write_text("source", encoding="utf-8")
    artifact_path = tmp_path / "same-name.csv"
    artifact_path.write_text("artifact", encoding="utf-8")
    entry = _done_entry(source_path, artifact_path)
    entry["artifacts"]["data"].pop("sha256")
    manifest = _manifest([entry])

    assert find_resumable_entry(
        manifest,
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=source_file_facts(
            source_path, source_identity=str(source_path.resolve()),
        ),
        required_artifacts={"data": "csv"},
    ) is None


def test_resumable_group_requires_done_status_and_complete_members(tmp_path):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source_a = {
        "identity": "source-a",
        "path": str(tmp_path / "a.csv"),
        "size": 10,
        "mtime_ns": 100,
    }
    source_b = {
        "identity": "source-b",
        "path": str(tmp_path / "b.csv"),
        "size": 20,
        "mtime_ns": 200,
    }
    group = _group_entry(
        image_path,
        [("task-a", source_a), ("task-b", source_b)],
    )
    manifest = dict(
        _manifest([_task_entry("done")]),
        render_groups=[group],
    )
    members = (
        GroupMemberResumeFact("task-a", source_a),
        GroupMemberResumeFact("task-b", source_b),
    )

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
    ) is group

    for changed_members in (
        members[:1],
        tuple(reversed(members)),
        (
            GroupMemberResumeFact("task-a", source_a),
            GroupMemberResumeFact("task-c", source_b),
        ),
    ):
        assert find_resumable_group(
            manifest,
            recipe_fingerprint="recipe-1",
            group_id="group-1",
            members=changed_members,
            image_format="png",
        ) is None

    pending_manifest = deepcopy(manifest)
    pending_manifest["render_groups"][0]["status"] = "pending"
    assert find_resumable_group(
        pending_manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
    ) is None


@pytest.mark.parametrize("prior_requested", ("png", "pdf", "svg"))
def test_group_resume_accepts_legacy_requested_format_only_when_effective_is_png(
    tmp_path, prior_requested,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete png artifact")
    source = {
        "identity": "source-a",
        "path": str(tmp_path / "a.csv"),
        "size": 10,
        "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    group["requested_outputs"]["image"] = prior_requested
    manifest = dict(_manifest([]), render_groups=[group])

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", source)],
        image_format="png",
    ) is group


@pytest.mark.parametrize("bad_effective", ("pdf", "svg", ""))
def test_group_resume_rejects_non_png_effective_format(tmp_path, bad_effective):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete png artifact")
    source = {
        "identity": "source-a", "path": None, "size": 10, "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    group["effective_outputs"]["image"] = bad_effective
    manifest = dict(_manifest([]), render_groups=[group])

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", source)],
        image_format="png",
    ) is None


@pytest.mark.parametrize(
    ("artifact_suffix", "artifact_format"),
    ((".pdf", "png"), (".svg", "png"), (".png", "pdf"), (".png", "svg")),
)
def test_group_resume_rejects_legacy_vector_artifact_as_png(
    tmp_path, artifact_suffix, artifact_format,
):
    image_path = tmp_path / f"group{artifact_suffix}"
    image_path.write_bytes(b"legacy vector artifact")
    source = {
        "identity": "source-a", "path": None, "size": 10, "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    group["requested_outputs"]["image"] = "pdf"
    group["artifact"] = artifact_facts(
        image_path, kind="image", artifact_format=artifact_format,
    )
    manifest = dict(_manifest([]), render_groups=[group])

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", source)],
        image_format="png",
    ) is None


def test_resumable_group_rejects_changed_member_source_stat(tmp_path):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source = {
        "identity": "source-a",
        "path": str(tmp_path / "a.csv"),
        "size": 10,
        "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    manifest = dict(_manifest([]), render_groups=[group])

    for changed_source in (
        dict(source, identity="source-b"),
        dict(source, size=11),
        dict(source, mtime_ns=101),
    ):
        assert find_resumable_group(
            manifest,
            recipe_fingerprint="recipe-1",
            group_id="group-1",
            members=[GroupMemberResumeFact("task-a", changed_source)],
            image_format="png",
        ) is None


def test_resumable_group_rejects_bad_image_checksum(tmp_path):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"original image")
    source = {
        "identity": "source-a",
        "path": None,
        "size": 10,
        "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    manifest = dict(_manifest([]), render_groups=[group])
    members = [GroupMemberResumeFact("task-a", source)]

    image_path.write_bytes(b"tampered image")

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
    ) is None

    incomplete = deepcopy(manifest)
    incomplete["render_groups"][0]["artifact"]["checksum_status"] = "cancelled"
    incomplete["render_groups"][0]["artifact"]["sha256"] = hashlib.sha256(
        image_path.read_bytes()
    ).hexdigest()
    incomplete["render_groups"][0]["artifact"]["size"] = image_path.stat().st_size
    assert find_resumable_group(
        incomplete,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
    ) is None


def test_partial_and_degraded_groups_are_not_resumable(tmp_path):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"partial image")
    source = {
        "identity": "source-a",
        "path": None,
        "size": 10,
        "mtime_ns": 100,
    }
    members = [GroupMemberResumeFact("task-a", source)]

    for status, degraded_reason in (
        ("partial", ""),
        ("degraded", "backend unavailable"),
        ("done", "backend unavailable"),
    ):
        group = _group_entry(
            image_path,
            [("task-a", source)],
            status=status,
            degraded_reason=degraded_reason,
        )
        manifest = dict(_manifest([]), render_groups=[group])
        assert find_resumable_group(
            manifest,
            recipe_fingerprint="recipe-1",
            group_id="group-1",
            members=members,
            image_format="png",
        ) is None


@pytest.mark.parametrize("missing_field", ("size", "mtime_ns"))
def test_render_group_loader_rejects_missing_required_source_fact(
    tmp_path,
    missing_field,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source = {
        "identity": "source-a",
        "path": None,
        "size": None,
        "mtime_ns": None,
    }
    group = _group_entry(image_path, [("task-a", source)])
    group["members"][0]["source"].pop(missing_field)
    manifest = dict(_manifest([]), render_groups=[group])

    with pytest.raises(
        ManifestValidationError,
        match=rf"render_groups\.0\.members\.0\.source\.{missing_field}",
    ):
        load_batch_manifest(manifest)


@pytest.mark.parametrize("missing_field", ("size", "mtime_ns"))
def test_group_resume_defends_against_missing_source_fact_after_validation(
    tmp_path,
    monkeypatch,
    missing_field,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    current_source = {
        "identity": "source-a",
        "path": None,
        "size": None,
        "mtime_ns": None,
    }
    group = _group_entry(image_path, [("task-a", current_source)])
    group["members"][0]["source"].pop(missing_field)
    manifest = dict(_manifest([]), render_groups=[group])
    monkeypatch.setattr(
        manifest_module,
        "load_batch_manifest",
        lambda unused_manifest: manifest,
    )

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", current_source)],
        image_format="png",
    ) is None


@pytest.mark.parametrize(
    ("field", "stored_value", "current_value"),
    (
        ("identity", "", "source-a"),
        ("identity", 42, "source-a"),
        ("size", True, 1),
        ("size", 1.0, 1),
        ("size", "1", 1),
        ("mtime_ns", True, 1),
        ("mtime_ns", 1.0, 1),
        ("mtime_ns", "1", 1),
    ),
)
def test_direct_group_resume_rejects_invalid_stored_source_facts(
    tmp_path,
    monkeypatch,
    field,
    stored_value,
    current_value,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    stored_source = {
        "identity": "source-a",
        "path": None,
        "size": 1,
        "mtime_ns": 1,
    }
    current_source = dict(stored_source)
    stored_source[field] = stored_value
    current_source[field] = current_value
    group = _group_entry(image_path, [("task-a", stored_source)])
    manifest = dict(_manifest([]), render_groups=[group])
    monkeypatch.setattr(
        manifest_module,
        "load_batch_manifest",
        lambda unused_manifest: manifest,
    )

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", current_source)],
        image_format="png",
    ) is None


@pytest.mark.parametrize(
    ("field", "current_value", "stored_value"),
    (
        ("identity", "", "source-a"),
        ("identity", 42, "source-a"),
        ("size", True, 1),
        ("size", 1.0, 1),
        ("size", "1", 1),
        ("mtime_ns", True, 1),
        ("mtime_ns", 1.0, 1),
        ("mtime_ns", "1", 1),
    ),
)
def test_direct_group_resume_rejects_invalid_current_source_facts(
    tmp_path,
    monkeypatch,
    field,
    current_value,
    stored_value,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    stored_source = {
        "identity": "source-a",
        "path": None,
        "size": 1,
        "mtime_ns": 1,
    }
    current_source = dict(stored_source)
    stored_source[field] = stored_value
    current_source[field] = current_value
    group = _group_entry(image_path, [("task-a", stored_source)])
    manifest = dict(_manifest([]), render_groups=[group])
    monkeypatch.setattr(
        manifest_module,
        "load_batch_manifest",
        lambda unused_manifest: manifest,
    )

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", current_source)],
        image_format="png",
    ) is None


@pytest.mark.parametrize("missing_field", ("size", "mtime_ns"))
def test_direct_group_resume_rejects_missing_current_source_fact(
    tmp_path,
    monkeypatch,
    missing_field,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    stored_source = {
        "identity": "source-a",
        "path": None,
        "size": None,
        "mtime_ns": None,
    }
    current_source = dict(stored_source)
    current_source.pop(missing_field)
    group = _group_entry(image_path, [("task-a", stored_source)])
    manifest = dict(_manifest([]), render_groups=[group])
    monkeypatch.setattr(
        manifest_module,
        "load_batch_manifest",
        lambda unused_manifest: manifest,
    )

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", current_source)],
        image_format="png",
    ) is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("identity", None),
        ("identity", 42),
        ("size", "10"),
        ("size", 10.0),
        ("size", True),
        ("mtime_ns", "100"),
        ("mtime_ns", 100.0),
        ("mtime_ns", False),
    ),
)
def test_render_group_loader_rejects_wrong_source_fact_type(
    tmp_path,
    field,
    bad_value,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source = {
        "identity": "source-a",
        "path": None,
        "size": 10,
        "mtime_ns": 100,
    }
    source[field] = bad_value
    manifest = dict(
        _manifest([]),
        render_groups=[_group_entry(image_path, [("task-a", source)])],
    )

    with pytest.raises(
        ManifestValidationError,
        match=rf"render_groups\.0\.members\.0\.source\.{field}",
    ):
        load_batch_manifest(manifest)


def test_resumable_group_rechecks_cancel_after_successful_checksum(
    tmp_path,
    monkeypatch,
):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source = {
        "identity": "source-a",
        "path": None,
        "size": 10,
        "mtime_ns": 100,
    }
    group = _group_entry(image_path, [("task-a", source)])
    manifest = dict(_manifest([]), render_groups=[group])

    class CancelAfterChecksum:
        cancelled = False

        def is_set(self):
            return self.cancelled

    cancel_token = CancelAfterChecksum()

    def checksum_then_cancel(path, *, cancel_token=None, chunk_size=None):
        cancel_token.cancelled = True
        return hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr(manifest_module, "sha256_file", checksum_then_cancel)

    assert find_resumable_group(
        manifest,
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=[GroupMemberResumeFact("task-a", source)],
        image_format="png",
        cancel_token=cancel_token,
    ) is None


def test_retry_failed_scope_only_returns_failed_and_cancelled_for_same_recipe():
    manifest = _manifest([
        _task_entry("done", source_id="a"),
        _task_entry("failed", source_id="b"),
        _task_entry("cancelled", source_id="c"),
        _task_entry("skipped", source_id="d"),
        _task_entry("resumed", source_id="e"),
    ])

    scope = retry_failed_scope(manifest, recipe_fingerprint="recipe-1")

    assert isinstance(scope, RetryScope)
    assert scope.task_keys == frozenset({
        ("b", "sig", "fft"),
        ("c", "sig", "fft"),
    })
    assert scope.group_ids == frozenset()
    with pytest.raises(ManifestRecipeMismatch):
        retry_failed_scope(manifest, recipe_fingerprint="changed")


def test_retry_scope_includes_failed_group_and_all_member_task_keys():
    failed_b = _task_entry("failed", source_id="b", method="time")
    cancelled_c = _task_entry("cancelled", source_id="c", method="time")
    group = {
        "group_id": "group-failed",
        "stem": "time__source-a",
        "group_by": "source",
        "layout": "overlay",
        "members": [
            {"task_id": failed_b["task_id"], "source": failed_b["source"]},
            {"task_id": cancelled_c["task_id"], "source": cancelled_c["source"]},
        ],
        "requested_outputs": {"image": "png"},
        "effective_outputs": {},
        "degraded_reason": "",
        "status": "failed",
        "message": "render failed",
        "warnings": [],
        "artifact": None,
    }
    manifest = dict(
        _manifest([failed_b, cancelled_c]),
        render_groups=[group],
    )

    scope = retry_failed_scope(manifest, recipe_fingerprint="recipe-1")

    assert scope == RetryScope(
        task_keys=frozenset({
            ("b", "sig", "time"),
            ("c", "sig", "time"),
        }),
        group_ids=frozenset({"group-failed"}),
    )


def test_retry_scope_group_expansion_does_not_mark_healthy_data_retryable(
    tmp_path,
):
    failed = _task_entry("failed", source_id="failed", method="time")
    healthy = _task_entry("done", source_id="healthy", method="time")
    image_path = tmp_path / "complete-group.png"
    image_path.write_bytes(b"complete group")
    group = {
        "group_id": "group-partial",
        "stem": "time__source-a",
        "group_by": "source",
        "layout": "overlay",
        "members": [
            {"task_id": failed["task_id"], "source": failed["source"]},
            {"task_id": healthy["task_id"], "source": healthy["source"]},
        ],
        "requested_outputs": {"image": "png"},
        "effective_outputs": {"image": "png"},
        "degraded_reason": "",
        "status": "done",
        "message": "",
        "warnings": [],
        "artifact": artifact_facts(
            image_path, kind="image", artifact_format="png",
        ),
    }
    manifest = dict(_manifest([failed, healthy]), render_groups=[group])

    scope = retry_failed_scope(manifest, recipe_fingerprint="recipe-1")

    assert scope.task_keys == frozenset({("failed", "sig", "time")})
    assert scope.group_ids == frozenset({"group-partial"})
    assert ("healthy", "sig", "time") not in scope.task_keys


def test_load_batch_manifest_rejects_unknown_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_batch_manifest(path)


@pytest.mark.parametrize(
    ("mutation", "field"),
    (
        (lambda raw: raw.pop("recipe_fingerprint"), "recipe_fingerprint"),
        (lambda raw: raw.__setitem__("entries", ["not-an-entry"]), "entries.0"),
        (
            lambda raw: raw["entries"][0].pop("task_id"),
            "entries.0.task_id",
        ),
        (
            lambda raw: raw["entries"][0].__setitem__("status", "blocked"),
            "entries.0.status",
        ),
        (
            lambda raw: raw["entries"][0]["source"].pop("identity"),
            "entries.0.source.identity",
        ),
        (
            lambda raw: raw["entries"][0]["artifacts"].__setitem__(
                "data", "not-an-object",
            ),
            "entries.0.artifacts.data",
        ),
        (
            lambda raw: raw["summary"].__setitem__("done", 99),
            "summary",
        ),
    ),
)
def test_strict_manifest_loader_fails_closed_with_field_path(mutation, field):
    raw = _manifest([_task_entry("done")])
    mutation(raw)

    with pytest.raises(ValueError, match=field.replace(".", r"\.")):
        load_batch_manifest(raw)


def test_strict_manifest_loader_accepts_running_partial_schema(tmp_path):
    recorder = BatchManifestRecorder(
        tmp_path,
        preset_name="partial",
        normalized_recipe={"method": "fft", "params": {}},
        recipe_fingerprint="recipe-partial",
        requested_outputs={},
        run_id="run-partial",
    )
    recorder.start()
    recorder.record(_task_entry("cancelled"))

    manifest = load_batch_manifest(recorder.partial_path)

    assert manifest["run_status"] == "running"
    assert manifest["finished_at"] is None
    assert manifest["summary"]["cancelled"] == 1


_SEGMENTED_AUTO_PARAMS = {
    "nfft": None,
    "nfft_mode": "auto",
    "avg_mode": "线性平均",
    "t_win_s": 1.5,
    "avg_overlap": 50,
}
_FFT_TIME_AUTO_PARAMS = {
    "nfft": None,
    "nfft_mode": "auto",
    "t_win_s": 1.5,
    "overlap": 0.5,
}


def test_auto_nfft_policy_is_current_uses_requested_recipe_not_entry_mode():
    entry = {
        "effective_facts": {"nfft_policy_version": AUTO_NFFT_POLICY_VERSION},
        "method": "fft",
        "requested_params": {"nfft": 64, "nfft_mode": "fixed"},
    }
    assert auto_nfft_policy_is_current(
        entry, requested_params=_SEGMENTED_AUTO_PARAMS, method="fft",
    ) is True
    stale = {
        "effective_facts": {"nfft_mode": "fixed"},
        "method": "fft",
    }
    assert auto_nfft_policy_is_current(
        stale, requested_params=_SEGMENTED_AUTO_PARAMS, method="fft",
    ) is False
    assert auto_nfft_policy_is_current(
        stale, requested_params={"nfft": 64}, method="fft",
    ) is True
    assert auto_nfft_policy_is_current(
        stale, requested_params={"nfft": None, "nfft_mode": "auto"}, method="fft",
    ) is True
    assert auto_nfft_policy_is_current(
        stale,
        requested_params=_FFT_TIME_AUTO_PARAMS,
        method="fft_time",
    ) is False
    assert auto_nfft_policy_is_current(
        stale, requested_params=_SEGMENTED_AUTO_PARAMS, method="order_time",
    ) is True
    assert auto_nfft_policy_is_current(
        stale, requested_params=_SEGMENTED_AUTO_PARAMS, method="frf",
    ) is True


@pytest.mark.parametrize("version", (None, 1, True, "2", 1.0))
def test_find_resumable_entry_rejects_stale_auto_nfft_policy(
    tmp_path, version,
):
    source_path = tmp_path / "source.csv"
    source_path.write_text("source-v1", encoding="utf-8")
    artifact_path = tmp_path / "result.csv"
    artifact_path.write_text("result-v1", encoding="utf-8")
    entry = _done_entry(source_path, artifact_path)
    entry["requested_params"] = dict(_SEGMENTED_AUTO_PARAMS)
    if version is None:
        entry["effective_facts"].pop("nfft_policy_version", None)
    else:
        entry["effective_facts"]["nfft_policy_version"] = version
    manifest = _manifest([entry])
    kwargs = dict(
        recipe_fingerprint="recipe-1",
        task_id="task-1",
        source_id="source-1",
        source_identity=str(source_path.resolve()),
        source_stat=source_file_facts(
            source_path, source_identity=str(source_path.resolve()),
        ),
        required_artifacts={"data": "csv"},
        requested_params=_SEGMENTED_AUTO_PARAMS,
        method="fft",
    )
    assert find_resumable_entry(manifest, **kwargs) is None

    entry["effective_facts"]["nfft_policy_version"] = AUTO_NFFT_POLICY_VERSION
    assert find_resumable_entry(_manifest([entry]), **kwargs) is entry


def test_find_resumable_group_rejects_one_stale_auto_nfft_member(tmp_path):
    image_path = tmp_path / "group.png"
    image_path.write_bytes(b"complete group image")
    source_a = {
        "identity": "source-a",
        "path": str(tmp_path / "a.csv"),
        "size": 10,
        "mtime_ns": 100,
    }
    source_b = {
        "identity": "source-b",
        "path": str(tmp_path / "b.csv"),
        "size": 20,
        "mtime_ns": 200,
    }
    current_a = _task_entry("done", source_id="a")
    current_a["task_id"] = "task-a"
    current_a["effective_facts"] = {
        "nfft_policy_version": AUTO_NFFT_POLICY_VERSION,
    }
    stale_b = _task_entry("done", source_id="b")
    stale_b["task_id"] = "task-b"
    stale_b["effective_facts"] = {}
    group = _group_entry(
        image_path,
        [("task-a", source_a), ("task-b", source_b)],
    )
    manifest = dict(
        _manifest([current_a, stale_b]),
        render_groups=[group],
    )
    members = (
        GroupMemberResumeFact("task-a", source_a),
        GroupMemberResumeFact("task-b", source_b),
    )
    kwargs = dict(
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
        requested_params=_FFT_TIME_AUTO_PARAMS,
        method="fft_time",
    )
    assert find_resumable_group(manifest, **kwargs) is None

    stale_b["effective_facts"]["nfft_policy_version"] = AUTO_NFFT_POLICY_VERSION
    assert find_resumable_group(
        dict(_manifest([current_a, stale_b]), render_groups=[group]),
        **kwargs,
    ) is group

    assert find_resumable_group(
        dict(_manifest([current_a, stale_b]), render_groups=[group]),
        recipe_fingerprint="recipe-1",
        group_id="group-1",
        members=members,
        image_format="png",
    ) is group
