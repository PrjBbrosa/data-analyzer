import json
import logging
from pathlib import Path

from PyQt5.QtCore import QSettings

from mf4_analyzer.ui.recent_files import (
    KEY_RECENT_V1,
    RecentEntry,
    RecentFilesStore,
    format_recent_label,
    match_recent_entries,
)


def _store(tmp_path, **kwargs):
    ini = str(tmp_path / "recent.ini")

    def factory():
        return QSettings(ini, QSettings.IniFormat)

    return RecentFilesStore(factory, **kwargs), ini


def test_recent_files_store_does_not_import_main_window_or_ui_kit():
    import ast
    from pathlib import Path as P

    src = P("mf4_analyzer/ui/recent_files.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = (
        "mf4_analyzer.ui.main_window",
        "mf4_analyzer.ui_kit",
        "mf4_analyzer.ui.toolbar",
    )
    violations = [
        name for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, violations


def test_record_file_dedupes_to_top(tmp_path):
    store, _ = _store(tmp_path)
    a = tmp_path / "a.wwt"
    b = tmp_path / "b.mf4"
    store.record_file(a)
    store.record_file(b)
    store.record_file(a)
    names = [Path(entry.path).name for entry in store.entries("file")]
    assert names == ["a.wwt", "b.mf4"]
    assert store.entries("project") == ()


def test_kind_caps_are_independent(tmp_path):
    store, _ = _store(tmp_path, max_files=2, max_projects=1)
    for i in range(3):
        store.record_file(tmp_path / f"f{i}.csv")
        store.record_project(tmp_path / f"p{i}.tlproj")
    files = [Path(entry.path).name for entry in store.entries("file")]
    projects = [Path(entry.path).name for entry in store.entries("project")]
    assert files == ["f2.csv", "f1.csv"]
    assert projects == ["p2.tlproj"]


def test_cap_evicts_oldest_of_that_kind(tmp_path):
    store, _ = _store(tmp_path, max_files=3, max_projects=4)
    for i in range(5):
        store.record_file(tmp_path / f"f{i}.csv")
    names = [Path(entry.path).name for entry in store.entries("file")]
    assert names == ["f4.csv", "f3.csv", "f2.csv"]


def test_remove_and_clear(tmp_path):
    store, _ = _store(tmp_path)
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    proj = tmp_path / "p.tlproj"
    store.record_file(a)
    store.record_file(b)
    store.record_project(proj)
    store.remove(a)
    assert [Path(entry.path).name for entry in store.entries("file")] == ["b.csv"]
    assert len(store.entries("project")) == 1
    store.clear()
    assert store.entries("file") == ()
    assert store.entries("project") == ()


def test_exists_uses_path_exists(tmp_path):
    store, _ = _store(tmp_path)
    present = tmp_path / "here.csv"
    present.write_text("x", encoding="utf-8")
    missing = tmp_path / "gone.csv"
    assert RecentFilesStore.exists(RecentEntry(str(present), "file", "t"))
    assert not RecentFilesStore.exists(RecentEntry(str(missing), "file", "t"))


def test_corrupt_json_returns_empty_and_warns_once(tmp_path, caplog):
    store, ini = _store(tmp_path)
    settings = QSettings(ini, QSettings.IniFormat)
    settings.setValue(KEY_RECENT_V1, "{not json")
    settings.sync()
    with caplog.at_level(logging.WARNING):
        assert store.entries("file") == ()
        assert store.entries("project") == ()
        assert store.entries("file") == ()
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_non_list_and_missing_fields_are_empty(tmp_path, caplog):
    store, ini = _store(tmp_path)
    settings = QSettings(ini, QSettings.IniFormat)
    settings.setValue(KEY_RECENT_V1, json.dumps({"path": "x"}))
    settings.sync()
    with caplog.at_level(logging.WARNING):
        assert store.entries("file") == ()
    store2, ini2 = _store(tmp_path / "b")
    settings2 = QSettings(ini2, QSettings.IniFormat)
    settings2.setValue(
        KEY_RECENT_V1,
        json.dumps([{"path": "/tmp/x.csv", "kind": "file"}]),
    )
    settings2.sync()
    with caplog.at_level(logging.WARNING):
        assert store2.entries("file") == ()


def test_format_recent_label_short_path_has_no_ellipsis():
    label = format_recent_label("/data/run.wwt", home="/no-such-home")
    assert "…" not in label
    assert label == "run.wwt  ·  /data"


def test_format_recent_label_folds_home():
    label = format_recent_label(
        "/Users/me/Documents/EPS/run.wwt",
        home="/Users/me",
    )
    assert label == "run.wwt  ·  ~/Documents/EPS"


def test_format_recent_label_long_dir_gets_middle_ellipsis():
    parent = "/data/" + ("very-long-directory-name/" * 6)
    path = parent + "run.mf4"
    label = format_recent_label(path, home="/no-such-home")
    assert label.startswith("run.mf4  ·  ")
    assert "…" in label
    assert len(label) <= 56


def test_format_recent_label_overlong_filename_is_ellipsized():
    name = ("very-long-channel-export-name" * 3) + ".wwt"
    assert len(name) > 40
    label = format_recent_label(f"/tmp/{name}", home="/no-such-home")
    filename, _sep, parent = label.partition("  ·  ")
    assert "…" in filename
    assert len(filename) == 40
    assert parent == "/tmp"


def test_default_caps_are_forty_files_and_ten_projects(tmp_path):
    store, _ = _store(tmp_path)
    for i in range(45):
        store.record_file(tmp_path / f"f{i:02d}.csv")
    for i in range(12):
        store.record_project(tmp_path / f"p{i:02d}.tlproj")
    assert len(store.entries("file")) == 40
    assert len(store.entries("project")) == 10
    assert len(store.all_entries()) == 50


def test_all_entries_keeps_global_mru_across_kinds(tmp_path):
    store, _ = _store(tmp_path)
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    proj = tmp_path / "p.tlproj"
    store.record_file(a)
    store.record_project(proj)
    store.record_file(b)
    names = [Path(entry.path).name for entry in store.all_entries()]
    assert names == ["b.csv", "p.tlproj", "a.csv"]
    assert [entry.kind for entry in store.all_entries()] == ["file", "project", "file"]


def test_old_v1_payload_reads_without_migration(tmp_path):
    store, ini = _store(tmp_path)
    settings = QSettings(ini, QSettings.IniFormat)
    payload = [
        {
            "path": str(tmp_path / "legacy.mf4"),
            "kind": "file",
            "opened_at": "2026-01-01T00:00:00",
        },
        {
            "path": str(tmp_path / "legacy.tlproj"),
            "kind": "project",
            "opened_at": "2026-01-02T00:00:00",
        },
    ]
    settings.setValue(KEY_RECENT_V1, json.dumps(payload, ensure_ascii=False))
    settings.sync()
    entries = store.all_entries()
    assert [Path(entry.path).name for entry in entries] == [
        "legacy.mf4",
        "legacy.tlproj",
    ]
    assert [entry.kind for entry in entries] == ["file", "project"]


def _match_entry(path, kind="file", opened_at="2026-09-04T12:00:00"):
    return RecentEntry(path=str(path), kind=kind, opened_at=opened_at)


def test_match_lowfri_and_0526_cross_field_tokens():
    home = "/Users/me"
    entries = (
        _match_entry("/Users/me/Downloads/testdoc/LPD02T08_0526/whole ±250deg_LowFri.MF4"),
        _match_entry("/Users/me/Downloads/testdoc/other/whole ±250deg_LowFri.MF4"),
        _match_entry("/Users/me/Downloads/testdoc/LPD02T08_0526/plain.mf4"),
    )
    matches = match_recent_entries(entries, "lowfri 0526", home=home)
    assert [Path(item.entry.path).name for item in matches] == [
        "whole ±250deg_LowFri.MF4",
    ]
    assert Path(matches[0].entry.path).parts[-2] == "LPD02T08_0526"
    assert matches[0].name_spans
    assert matches[0].path_spans


def test_match_w250lf_filename_subsequence():
    entries = (
        _match_entry("/data/whole ±250deg_LowFri.MF4"),
        _match_entry("/data/whole ±90deg_LowFri.MF4"),
        _match_entry("/data/unrelated.mf4"),
    )
    matches = match_recent_entries(entries, "w250lf", home="/no-such-home")
    names = [item.filename for item in matches]
    assert names[0] == "whole ±250deg_LowFri.MF4"
    assert "unrelated.mf4" not in names
    assert matches[0].name_spans


def test_match_p166_tlproj_and_casefold_equivalence():
    home = "/Users/me"
    entries = (
        _match_entry(
            "/Users/me/Documents/TraceLab/Projects/P166/连续转向共振/P166_连续转向共振.tlproj",
            "project",
        ),
        _match_entry("/Users/me/Downloads/testdoc/LPD02T08_0526/whole ±250deg_LowFri.MF4"),
    )
    project_hits = match_recent_entries(entries, "p166 tlproj", home=home)
    assert len(project_hits) == 1
    assert project_hits[0].entry.kind == "project"
    lower = match_recent_entries(entries, "lowfri", home=home)
    upper = match_recent_entries(entries, "LOWFRI", home=home)
    assert [item.entry.path for item in lower] == [item.entry.path for item in upper]


def test_match_nfkc_slash_zero_hits_and_rank_tiers():
    entries = (
        _match_entry("/data/run.mf4"),
        _match_entry("/data/foo\\bar/run.mf4"),
        _match_entry("/tmp/lowfri.mf4"),
        _match_entry("/tmp/lowfri_run.mf4"),
        _match_entry("/tmp/whole_lowfri.mf4"),
    )
    slash_hits = match_recent_entries(entries, "foo/bar", home="/no-such-home")
    assert [item.filename for item in slash_hits] == ["run.mf4"]
    assert "foo" in slash_hits[0].display_parent or "foo" in slash_hits[0].entry.path

    empty = match_recent_entries(entries, "zz-no-match", home="/no-such-home")
    assert empty == ()

    ranked = match_recent_entries(
        entries[2:],
        "lowfri",
        home="/no-such-home",
    )
    names = [item.filename for item in ranked]
    assert names[0] == "lowfri.mf4"
    assert names[1] == "lowfri_run.mf4"
    assert names[2] == "whole_lowfri.mf4"


def test_match_empty_query_keeps_mru_and_hot_path_has_no_io(tmp_path, monkeypatch):
    entries = (
        _match_entry(tmp_path / "b.mf4"),
        _match_entry(tmp_path / "p.tlproj", "project"),
        _match_entry(tmp_path / "a.mf4"),
    )
    matches = match_recent_entries(entries, "   ", home=str(tmp_path))
    assert [Path(item.entry.path).name for item in matches] == [
        "b.mf4",
        "p.tlproj",
        "a.mf4",
    ]
    assert all(item.name_spans == () and item.path_spans == () for item in matches)

    settings_reads = {"n": 0}
    exists_calls = {"n": 0}
    original_value = QSettings.value

    def counting_value(self, *args, **kwargs):
        settings_reads["n"] += 1
        return original_value(self, *args, **kwargs)

    def counting_exists(entry):
        exists_calls["n"] += 1
        return True

    monkeypatch.setattr(QSettings, "value", counting_value)
    monkeypatch.setattr(RecentFilesStore, "exists", staticmethod(counting_exists))
    match_recent_entries(entries, "lowfri 0526", home=str(tmp_path))
    assert settings_reads["n"] == 0
    assert exists_calls["n"] == 0


def test_match_gap_and_mru_tie_break():
    early = _match_entry("/data/w_xx_250_l_f.mf4", opened_at="2026-01-01T00:00:00")
    later = _match_entry("/data/w_250lf.mf4", opened_at="2026-02-01T00:00:00")
    same_gap_a = _match_entry("/data/aaa_lowfri.mf4")
    same_gap_b = _match_entry("/data/bbb_lowfri.mf4")
    compact = match_recent_entries((early, later), "w250lf", home="/data")
    assert compact[0].filename == "w_250lf.mf4"
    tied = match_recent_entries((same_gap_a, same_gap_b), "lowfri", home="/data")
    assert [item.filename for item in tied] == ["aaa_lowfri.mf4", "bbb_lowfri.mf4"]
