"""BLF (.blf) UI dispatch — ``_load_one`` must route .blf to ``load_blf`` and
honor the chained DBC picker (skipping it opens raw bytes). A2L is never
touched."""
import pytest

can = pytest.importorskip("can", reason="python-can not installed (win32-gated)")
cantools = pytest.importorskip("cantools", reason="cantools not installed")

from tests._helpers.blf_factory import (  # noqa: E402
    write_raw_blf,
    write_sample_blf,
    write_two_message_dbc,
)


def test_load_one_routes_blf_with_dbc(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    mw = MainWindow()
    # stub the chained DBC dialog: pick our DBC
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(blf))

    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert "EngineSpeed" in fd.channels
    assert "Speed" in fd.channels


def test_load_one_routes_blf_raw_when_dbc_skipped(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    blf = write_raw_blf(tmp_path / "raw.blf")

    mw = MainWindow()
    # user cancels the DBC dialog -> [] -> raw byte channels
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [])
    mw._load_one(str(blf))

    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert any(c.startswith("0x1F3.byte") for c in fd.channels)
