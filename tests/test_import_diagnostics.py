from types import SimpleNamespace

from mf4_analyzer.io.import_diagnostics import (
    aggregate_import_diagnostics,
    format_import_summary,
    get_import_diagnostics,
    make_import_issue,
    set_import_diagnostics,
    uncovered_legacy_metadata,
)


def test_unknown_is_distinct_from_verified_complete():
    assert get_import_diagnostics({}) is None
    metadata = {}
    result = set_import_diagnostics(metadata, [], source_kind="wwt", imported_channels=5)
    assert result["state"] == "complete"
    assert get_import_diagnostics(metadata) == result
    assert format_import_summary(metadata) == ""


def test_partial_wins_and_same_label_records_are_not_collapsed():
    metadata = {}
    issues = [make_import_issue("untimed", "缺少时间信息", severity="partial",
                                action="skipped", record_index=i, channel="Same")
              for i in (1, 2)]
    set_import_diagnostics(metadata, issues + [issues[0]], imported_channels=1)
    payload = get_import_diagnostics(metadata)
    assert payload["state"] == "partial"
    assert len(payload["issues"]) == 2
    assert "部分导入" in format_import_summary(metadata)


def test_aggregation_deduplicates_file_issues_without_double_counting():
    metadata = {"source_filename": "file.wwt"}
    issue = make_import_issue("empty_time_record", "1 条空时间轴", record_index=5)
    set_import_diagnostics(metadata, [issue], imported_channels=5)
    aggregate = aggregate_import_diagnostics([metadata, dict(metadata)])
    assert aggregate["counts"] == {"imported_channels": 5}
    assert len(aggregate["issues"]) == 1
    other = {"source_filename": "other.wwt"}
    set_import_diagnostics(other, [issue], imported_channels=3)
    aggregate = aggregate_import_diagnostics([metadata, other, {}])
    assert aggregate["counts"] == {}
    assert len(aggregate["issues"]) == 2
    assert aggregate["unknown_sources"] == 1


def test_payload_does_not_alias_input_or_getter_output():
    issue = make_import_issue("missing", "有缺口", rows=[2, 4])
    metadata = {}
    set_import_diagnostics(metadata, [issue])
    issue["rows"].append(8)
    result = get_import_diagnostics(metadata)
    result["issues"][0]["rows"].append(9)
    assert metadata["import_diagnostics"]["issues"][0]["rows"] == [2, 4]


def test_batch_carries_structured_diagnostics_without_legacy_warnings():
    from mf4_analyzer.batch import _loader_source_diagnostic

    metadata = {}
    set_import_diagnostics(metadata, [make_import_issue(
        "missing", "通道 A 有 1 个缺口", severity="partial", channel="A")])
    diagnostic = _loader_source_diagnostic(SimpleNamespace(source_metadata=metadata))
    assert diagnostic["import_diagnostics"]["state"] == "partial"
    assert any("部分导入" in text for text in diagnostic["warnings"])


def test_batch_keeps_unknown_and_clean_distinct():
    from mf4_analyzer.batch import _loader_source_diagnostic

    assert _loader_source_diagnostic(SimpleNamespace(source_metadata={})) is None
    metadata = {}
    set_import_diagnostics(metadata, [])
    result = _loader_source_diagnostic(SimpleNamespace(source_metadata=metadata))
    assert result["warnings"] == []
    assert result["import_diagnostics"]["state"] == "complete"


def test_partial_import_reaches_batch_manifest_and_resume_without_duplicate_warning(tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.batch_manifest import load_batch_manifest
    from mf4_analyzer.io.file_data import FileData

    data = pd.DataFrame({"Time": np.arange(256) / 100., "good": np.ones(256)})
    path = tmp_path / "source.csv"
    data.to_csv(path, index=False)
    metadata = {"source_kind": "csv"}
    set_import_diagnostics(metadata, [make_import_issue(
        "skipped_channel", "未导入通道 bad", severity="partial", action="skipped",
        channel="bad")], imported_channels=1, skipped_channels=1)
    fd = FileData(path, data, list(data.columns), {}, source_metadata=metadata)
    preset = AnalysisPreset.from_current_single(
        name="partial", method="time", signal=(0, "good"),
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    runner = BatchRunner({0: fd})
    for _ in range(2):
        result = runner.run(preset, tmp_path / "out")
        item = result.items[0]
        assert item.status in {"done", "resumed"}
        assert sum("部分导入" in message for message in item.warnings) == 1
        manifest = load_batch_manifest(result.manifest_path)["entries"][0]
        assert "source_diagnostics" not in manifest["requested_params"]
        facts = manifest["effective_facts"]["source_diagnostics"]
        assert next(iter(facts.values()))["import_diagnostics"]["state"] == "partial"


def test_batch_rejects_gapped_fft_but_keeps_import_facts(tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.batch_manifest import load_batch_manifest
    from mf4_analyzer.io.file_data import FileData

    signal = np.ones(256)
    signal[-1] = np.nan
    data = pd.DataFrame({"Time": np.arange(256) / 100., "A": signal})
    metadata = {}
    set_import_diagnostics(metadata, [make_import_issue(
        "gap", "A 有缺口", severity="partial", channel="A")])
    fd = FileData(tmp_path / "gap.csv", data, list(data.columns), {}, source_metadata=metadata)
    preset = AnalysisPreset.from_current_single(
        name="gap", method="fft", signal=(0, "A"), params={"nfft": 128},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    assert result.items[0].status == "failed"
    assert not result.items[0].data_path
    record = load_batch_manifest(result.manifest_path)["entries"][0]
    payload = next(iter(record["effective_facts"]["source_diagnostics"].values()))
    assert payload["import_diagnostics"]["state"] == "partial"


def test_legacy_facts_are_only_removed_when_physical_issue_covers_them():
    metadata = {"skipped_channels": [{"name": "A", "record_index": 1},
                                      {"name": "A", "record_index": 2}],
                "warnings": ["covered", "independent"]}
    set_import_diagnostics(metadata, [make_import_issue(
        "skip", "covered", action="skipped", channel="A", record_index=1)])
    remaining = uncovered_legacy_metadata(metadata)
    assert remaining["skipped_channels"] == [{"name": "A", "record_index": 2}]
    assert remaining["warnings"] == ["independent"]
    assert len(metadata["skipped_channels"]) == 2
