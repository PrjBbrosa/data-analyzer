from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from mf4_analyzer.batch_manifest import (
    BatchManifestRecorder,
    ManifestRecipeMismatch,
    artifact_facts,
    derive_summary,
    find_resumable_entry,
    load_batch_manifest,
    retry_failed_scope,
    source_file_facts,
)


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
        "source": {"identity": f"identity-{source_id}"},
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


def test_retry_failed_scope_only_returns_failed_and_cancelled_for_same_recipe():
    manifest = _manifest([
        _task_entry("done", source_id="a"),
        _task_entry("failed", source_id="b"),
        _task_entry("cancelled", source_id="c"),
        _task_entry("skipped", source_id="d"),
        _task_entry("resumed", source_id="e"),
    ])

    assert retry_failed_scope(manifest, recipe_fingerprint="recipe-1") == {
        ("b", "sig", "fft"),
        ("c", "sig", "fft"),
    }
    with pytest.raises(ManifestRecipeMismatch):
        retry_failed_scope(manifest, recipe_fingerprint="changed")


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
