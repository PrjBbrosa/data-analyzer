import json
import logging
from pathlib import Path

from PyQt5.QtCore import QSettings

from mf4_analyzer.ui.recent_files import (
    KEY_RECENT_V1,
    RecentEntry,
    RecentFilesStore,
    format_recent_label,
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
