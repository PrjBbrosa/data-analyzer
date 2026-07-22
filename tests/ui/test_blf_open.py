"""BLF (.blf) UI dispatch — ``_load_one`` must route .blf to ``load_blf`` and
honor DBC selection/reuse. A2L is never touched."""
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

    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    dbc = write_two_message_dbc(dbc_dir / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    mw = MainWindow()
    # stub the chained DBC dialog: pick our DBC
    monkeypatch.setattr(
        mw, "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(blf))

    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert "EngineSpeed" in fd.channels
    assert "Speed" in fd.channels


def test_load_one_cancelled_dbc_selection_leaves_blf_unopened(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    blf = write_raw_blf(tmp_path / "raw.blf")

    mw = MainWindow()
    monkeypatch.setattr(
        mw, "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [])
    mw._load_one(str(blf))

    assert len(mw.files) == 0


def test_dbc_picker_title_says_cancel_does_not_open_file(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    import mf4_analyzer.ui.main_window as main_window_package

    captured = {}

    class FakeFileDialog:
        @staticmethod
        def getOpenFileNames(_parent, title, _start, _filter):
            captured["title"] = title
            return [], ""

    monkeypatch.setattr(main_window_package, "QFileDialog", FakeFileDialog)
    window = MainWindow()

    assert window._prompt_blf_dbc(tmp_path / "sample.blf") == []
    assert "取消则不打开" in captured["title"]
    assert "原始字节" not in captured["title"]


def test_load_one_reuses_matching_session_dbc_after_confirmation(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    dbc = write_two_message_dbc(dbc_dir / "bus.dbc")
    blf1 = write_sample_blf(tmp_path / "log1.blf", n=5)
    blf2 = write_sample_blf(tmp_path / "log2.blf", n=5, t_start=3.0)

    mw = MainWindow()
    monkeypatch.setattr(
        mw, "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(blf1))
    assert len(mw.files) == 1

    monkeypatch.setattr(
        mw,
        "_ask_blf_dbc_candidate_action",
        lambda path, candidate: "use",
        raising=False,
    )

    def fail_if_picker_opens(path):
        raise AssertionError("matching remembered DBC should be confirmed, not re-picked")

    monkeypatch.setattr(mw, "_prompt_blf_dbc", fail_if_picker_opens)
    mw._load_one(str(blf2))

    assert len(mw.files) == 2
    assert all("EngineSpeed" in fd.channels for fd in mw.files.values())


def test_load_one_reuses_persisted_recent_dbc_after_restart(qapp, tmp_path, monkeypatch):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.main_window import MainWindow

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
    blf1 = write_sample_blf(tmp_path / "log1.blf", n=5)
    blf2 = write_sample_blf(tmp_path / "log2.blf", n=5, t_start=3.0)

    mw = MainWindow()
    monkeypatch.setattr(
        mw,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(blf1))
    assert len(mw.files) == 1

    mw2 = MainWindow()
    monkeypatch.setattr(
        mw2,
        "_ask_blf_dbc_candidate_action",
        lambda path, candidate: "use",
        raising=False,
    )
    monkeypatch.setattr(
        mw2,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: False,
        raising=False,
    )

    def fail_if_picker_opens(path):
        raise AssertionError("persisted matching DBC should be confirmed, not re-picked")

    monkeypatch.setattr(mw2, "_prompt_blf_dbc", fail_if_picker_opens)
    mw2._load_one(str(blf2))

    assert len(mw2.files) == 1
    fd = next(iter(mw2.files.values()))
    assert "EngineSpeed" in fd.channels
