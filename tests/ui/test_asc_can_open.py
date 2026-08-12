"""CANoe ASC UI dispatch — same DBC chain as BLF, distinct source_kind."""
from __future__ import annotations

import pytest

pytest.importorskip("can", reason="python-can not installed (win32-gated)")
pytest.importorskip("cantools", reason="cantools not installed")

from tests._helpers.blf_factory import (
    write_sample_asc,
    write_sample_blf,
    write_two_message_dbc,
)


def test_load_one_routes_canoe_asc_with_dbc(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    dbc = write_two_message_dbc(dbc_dir / "bus.dbc")
    asc = write_sample_asc(tmp_path / "log.asc", n=5)

    mw = MainWindow()
    monkeypatch.setattr(
        mw, "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(asc))

    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert "EngineSpeed" in fd.channels
    assert fd.source_metadata["source_kind"] == "canoe_asc"
    assert fd.source_metadata["dbc_paths"]


def test_load_one_cancelled_dbc_leaves_canoe_asc_unopened(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    asc = write_sample_asc(tmp_path / "log.asc", n=3)
    mw = MainWindow()
    monkeypatch.setattr(
        mw, "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [])
    mw._load_one(str(asc))

    assert len(mw.files) == 0


def test_tabular_asc_does_not_enter_can_log_dbc_path(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    table = tmp_path / "table.asc"
    table.write_text("Time\tSpeed\n0.0\t10\n0.1\t11\n", encoding="utf-8")

    mw = MainWindow()
    called = []

    def fail_resolve(*args, **kwargs):
        called.append(True)
        raise AssertionError("tabular .asc must not enter BLF/DBC resolve")

    monkeypatch.setattr(mw, "_resolve_blf_dbc_paths", fail_resolve)
    mw._load_one(str(table))

    assert called == []
    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert fd.source_metadata.get("source_kind") == "ascii"


def test_open_data_paths_mixed_blf_and_canoe_asc_batch(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "a.blf", n=3)
    asc = write_sample_asc(tmp_path / "b.asc", n=3)

    mw = MainWindow()
    monkeypatch.setattr(mw, "_ask_blf_batch_dbc_action", lambda paths: "batch")
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._open_data_paths([str(blf), str(asc)])

    assert len(mw.files) == 2
    kinds = {fd.source_metadata["source_kind"] for fd in mw.files.values()}
    assert kinds == {"blf", "canoe_asc"}


def test_project_roundtrip_restores_canoe_asc_dbc_without_picker(
    qapp, tmp_path, monkeypatch,
):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio

    settings = QSettings(str(tmp_path / "recent-dbc.ini"), QSettings.IniFormat)
    settings.clear()
    monkeypatch.setattr(
        MainWindow,
        "_blf_dbc_settings",
        lambda self: settings,
        raising=False,
    )

    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    dbc = write_two_message_dbc(dbc_dir / "bus.dbc")
    asc = write_sample_asc(tmp_path / "log.asc", n=5)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    monkeypatch.setattr(
        mw,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(asc))
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert doc.files[0].dbc_refs

    settings.clear()
    settings.sync()

    mw2 = MainWindow()
    monkeypatch.setattr(
        mw2,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: False,
        raising=False,
    )

    def fail_if_picker_opens(path):
        raise AssertionError("project DBC binding should load without re-picking")

    monkeypatch.setattr(mw2, "_prompt_blf_dbc", fail_if_picker_opens)
    mw2.open_project(proj)

    assert len(mw2.files) == 1
    fd = next(iter(mw2.files.values()))
    assert "EngineSpeed" in fd.channels
    assert fd.source_metadata["source_kind"] == "canoe_asc"
    assert fd.source_metadata["dbc_paths"] == [str(dbc.resolve())]
