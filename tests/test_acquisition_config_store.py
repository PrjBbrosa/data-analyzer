"""Tests for ``mf4_analyzer.acquisition_capture.config_store``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Persistence Contract.

Pinned behavior:
- 4-step lookup: CLI flag → A2L dir → project root → in-memory default.
- ``pinned`` flag — True when a real file was found, False when default.
- ``acquisition_config.yaml`` uses UTF-8 (Chinese channel names allowed).
- ``version: 1`` validation; unknown top-level keys raise a clear error.
- ``~/.acquisition-cockpit/recent.json`` pruning by ``max_age_days``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.config_store import (
    CONFIG_VERSION,
    ConfigStore,
    ConfigSchemaError,
    load_or_default,
    save_a2l_path,
    write_recent,
    read_recent,
)


# ---------------------------------------------------------------------------
# 4-step lookup order.
# ---------------------------------------------------------------------------


def _write_min_config(path: Path, marker: str) -> None:
    path.write_text(
        f"""version: 1
a2l_path: "{marker}"
favorites: []
selected: []
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {{}}
""",
        encoding="utf-8",
    )


def test_step1_cli_flag_wins(tmp_path):
    cli_cfg = tmp_path / "cli.yaml"
    a2l_dir = tmp_path / "a2l_dir"
    a2l_dir.mkdir()
    project_root = tmp_path / "proj"
    project_root.mkdir()

    _write_min_config(cli_cfg, "cli-marker")
    _write_min_config(a2l_dir / "acquisition_config.yaml", "a2l-marker")
    _write_min_config(project_root / "acquisition_config.yaml", "project-marker")

    store = load_or_default(
        project_root=project_root,
        a2l_dir=a2l_dir,
        cli_config_path=cli_cfg,
    )
    assert store.pinned is True
    assert store.a2l_path == "cli-marker"
    assert store.source_path == cli_cfg.resolve()


def test_step2_a2l_dir_used_when_no_cli(tmp_path):
    a2l_dir = tmp_path / "a2l_dir"
    a2l_dir.mkdir()
    project_root = tmp_path / "proj"
    project_root.mkdir()

    _write_min_config(a2l_dir / "acquisition_config.yaml", "a2l-marker")
    _write_min_config(project_root / "acquisition_config.yaml", "project-marker")

    store = load_or_default(
        project_root=project_root,
        a2l_dir=a2l_dir,
        cli_config_path=None,
    )
    assert store.pinned is True
    assert store.a2l_path == "a2l-marker"


def test_step3_project_root_used_when_no_a2l(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _write_min_config(project_root / "acquisition_config.yaml", "project-marker")

    store = load_or_default(
        project_root=project_root,
        a2l_dir=None,
        cli_config_path=None,
    )
    assert store.pinned is True
    assert store.a2l_path == "project-marker"


def test_step4_in_memory_default_when_nothing_found(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    store = load_or_default(
        project_root=project_root,
        a2l_dir=None,
        cli_config_path=None,
    )
    assert store.pinned is False
    assert store.source_path is None
    assert store.version == CONFIG_VERSION
    # in-memory default is empty selection/favorites
    assert store.selected == []
    assert store.favorites == []


# ---------------------------------------------------------------------------
# UTF-8 round-trip with Chinese characters.
# ---------------------------------------------------------------------------


def test_utf8_roundtrip_with_chinese(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        """version: 1
a2l_path: "configs/a2l/转速.a2l"
favorites:
  - name: 转速平均
    address_hex: "0x40000000"
selected:
  - name: 转速平均
    raster: event_10ms
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {}
""",
        encoding="utf-8",
    )
    store = load_or_default(
        project_root=tmp_path,
        a2l_dir=None,
        cli_config_path=cfg,
    )
    assert store.pinned is True
    assert store.a2l_path == "configs/a2l/转速.a2l"
    assert store.favorites[0]["name"] == "转速平均"
    assert store.selected[0]["name"] == "转速平均"


# ---------------------------------------------------------------------------
# Schema validation.
# ---------------------------------------------------------------------------


def test_future_version_rejected(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        """version: 3
a2l_path: "x"
favorites: []
selected: []
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigSchemaError, match="version"):
        load_or_default(project_root=tmp_path, cli_config_path=cfg)


def test_unknown_top_level_key_rejected(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        """version: 1
a2l_path: "x"
favorites: []
selected: []
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {}
mystery_key: 42
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigSchemaError, match="mystery_key"):
        load_or_default(project_root=tmp_path, cli_config_path=cfg)


# ---------------------------------------------------------------------------
# Recent (per-user) — pruning by max_age_days.
# ---------------------------------------------------------------------------


def test_recent_prunes_entries_older_than_max_age_days(tmp_path):
    recent_path = tmp_path / "recent.json"
    payload = {
        "version": 1,
        "max_age_days": 14,
        "max_entries": 50,
        "entries": [
            # 30 days ago — must be pruned
            {"name": "OldSignal", "added_ts": 1_000_000.0, "a2l_path": "x"},
            # near-now — kept
            {"name": "NewSignal", "added_ts": 2_000_000_000.0, "a2l_path": "x"},
        ],
    }
    recent_path.write_text(json.dumps(payload), encoding="utf-8")

    # write_recent prunes on write
    write_recent(
        recent_path,
        new_entry={"name": "JustNow", "added_ts": 2_000_000_001.0, "a2l_path": "y"},
        now_ts=2_000_000_005.0,
    )
    after = json.loads(recent_path.read_text(encoding="utf-8"))
    names = {e["name"] for e in after["entries"]}
    assert "OldSignal" not in names
    assert "NewSignal" in names
    assert "JustNow" in names


def test_recent_round_trip_utf8_chinese(tmp_path):
    recent_path = tmp_path / "recent.json"
    write_recent(
        recent_path,
        new_entry={"name": "转速", "added_ts": 2_000_000_000.0, "a2l_path": "x"},
        now_ts=2_000_000_001.0,
    )
    raw = recent_path.read_bytes()
    # bytes contain UTF-8 encoded Chinese, not escaped \\uXXXX
    assert "转速".encode("utf-8") in raw
    parsed = read_recent(recent_path)
    assert parsed["entries"][0]["name"] == "转速"


def test_recent_caps_max_entries(tmp_path):
    """Entries beyond max_entries are dropped (oldest first)."""
    recent_path = tmp_path / "recent.json"
    # Seed with 50 entries
    payload = {
        "version": 1,
        "max_age_days": 14,
        "max_entries": 3,  # tighter cap so test is fast
        "entries": [
            {"name": f"Sig{i}", "added_ts": 2_000_000_000.0 + i, "a2l_path": "x"}
            for i in range(3)
        ],
    }
    recent_path.write_text(json.dumps(payload), encoding="utf-8")
    write_recent(
        recent_path,
        new_entry={"name": "NewOne", "added_ts": 2_000_000_010.0, "a2l_path": "x"},
        now_ts=2_000_000_011.0,
    )
    after = json.loads(recent_path.read_text(encoding="utf-8"))
    assert len(after["entries"]) <= 3
    assert any(e["name"] == "NewOne" for e in after["entries"])
    # Oldest (Sig0) should be evicted
    assert not any(e["name"] == "Sig0" for e in after["entries"])


def test_save_a2l_path_round_trip(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    save_a2l_path(tmp_path / "demo.a2l", config_path=cfg)
    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == str(tmp_path / "demo.a2l")
    assert store.pinned is True


def test_save_a2l_path_round_trips_windows_backslashes_without_doubling(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    expected = r"C:\measurements\demo.a2l"

    save_a2l_path(expected, config_path=cfg)

    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == expected


def test_save_a2l_path_round_trips_windows_path_with_apostrophe(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    expected = r"C:\O'Brien\demo.a2l"

    save_a2l_path(expected, config_path=cfg)

    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == expected


def test_load_config_decodes_legacy_escaped_windows_a2l_path(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        'version: 2\n'
        'a2l_path: "C:\\\\measurements\\\\demo.a2l"\n',
        encoding="utf-8",
    )

    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == r"C:\measurements\demo.a2l"


def test_load_config_keeps_hash_after_legacy_escaped_quote(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        'version: 2\n'
        'a2l_path: "C:\\\\measurements\\\\tag\\"#2.a2l"\n',
        encoding="utf-8",
    )

    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == r'C:\measurements\tag"#2.a2l'


def test_save_a2l_path_preserves_existing_transport(tmp_path):
    from mf4_analyzer.acquisition_capture.config_store import save_transport
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    cfg = tmp_path / "acquisition_config.yaml"
    save_transport(TransportConfig(channel=1), config_path=cfg)
    save_a2l_path(tmp_path / "demo.a2l", config_path=cfg)
    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.transport.channel == 1
    assert store.a2l_path == str(tmp_path / "demo.a2l")
