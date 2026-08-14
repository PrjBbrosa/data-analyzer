"""BLF (.blf) UI dispatch — ``_load_one`` must route .blf to ``load_blf`` and
honor DBC selection/reuse. A2L is never touched."""
import pytest

can = pytest.importorskip("can", reason="python-can not installed (win32-gated)")
cantools = pytest.importorskip("cantools", reason="cantools not installed")

from tests._helpers.blf_factory import (  # noqa: E402
    engine_payload,
    make_can_frames,
    make_sampled_can_frames,
    write_engine_only_dbc,
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


def test_validated_dbc_survives_a_large_log_with_a_rare_matched_id(
    qapp, tmp_path,
):
    """P0-1 downstream: a project-restored DBC binding must not be dropped.

    ``_validated_blf_dbc_paths`` returned ``None`` for this shape, which
    silently discarded the DBC binding on project restore and made batch
    intake raise "CAN 日志与所选 DBC 不匹配".
    """
    from mf4_analyzer.ui.main_window import MainWindow

    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    frames = make_can_frames([
        (1, 0x777, b"\x00"),
        (1, 0x123, engine_payload()),
        (29_998, 0x777, b"\x00"),
    ])

    window = MainWindow()
    validated = window._validated_blf_dbc_paths(
        tmp_path / "sample.blf", [str(dbc)], frames=frames,
    )

    assert validated == [str(dbc)]


def test_format_blf_dbc_candidate_uses_sample_copy_not_fake_exact_frames(
    qapp, tmp_path,
):
    """§4.1: a full scan must not be labelled a sample, and the two
    different "match" numbers must not share one word."""
    import re
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.ui.main_window import MainWindow

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)
    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])
    window = MainWindow()
    text = window._format_blf_dbc_candidate({
        "paths": [str(dbc)],
        "probe": probe,
    })

    assert re.search(r"帧\s+\d+/\d+", text) is None
    # 10 frames is far below the decode cap: this really was a full decode.
    assert probe.sampling_strategy == "complete"
    assert "完整解码" in text
    assert "抽样解码" not in text
    # matched_frame_count counts ID hits, not decode successes.
    assert "ID 命中" in text
    assert "完整匹配" not in text


def test_format_blf_dbc_candidate_says_sampled_when_the_scan_was_sampled(
    qapp, tmp_path,
):
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.ui.main_window import MainWindow

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    frames = make_sampled_can_frames()
    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])
    window = MainWindow()
    text = window._format_blf_dbc_candidate({
        "paths": [str(dbc)],
        "probe": probe,
    })

    assert probe.sampling_strategy != "complete"
    assert "抽样解码" in text
    assert "完整解码" not in text


def test_incomplete_candidate_is_selectable_and_says_probe_did_not_finish(
    qapp, tmp_path, monkeypatch,
):
    """§4.1: a cancelled probe must not be presented (or filtered) as a
    mismatch — the user still has to be able to pick that DBC."""
    from mf4_analyzer.blf_dbc_candidates import candidate_status
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window import _project_io_mixin as project_io_mixin

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    frames = make_can_frames([(20_000, 0x123, engine_payload())])
    probe = DataLoader.probe_blf_dbc_frames(
        frames, [str(dbc)], cancel_check=lambda: True,
    )
    assert probe.sampling_complete is False

    window = MainWindow()
    window._candidate_blf_dbc_paths = lambda _path: [[str(dbc)]]
    monkeypatch.setattr(
        project_io_mixin.DataLoader,
        "probe_blf_dbc_frames",
        staticmethod(lambda *_args, **_kwargs: probe),
    )

    candidates = window._probe_blf_dbc_candidates(
        tmp_path / "sample.blf", frames=frames,
    )

    assert len(candidates) == 1, "incomplete must survive the selectable filter"
    assert candidate_status(candidates[0]) == "incomplete"
    text = window._format_blf_dbc_candidate(candidates[0])
    assert "未完成" in text
    assert "不匹配" not in text
    assert "已取消" in text


def test_candidate_probe_hands_the_loader_a_live_cancel_check(
    qapp, tmp_path, monkeypatch,
):
    """§4.1: closing the window mid-probe must actually stop the probe."""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window import _project_io_mixin as project_io_mixin

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    seen = {}

    def probe_frames(_frames, paths, *, cancel_check=None, **_kwargs):
        seen["cancel_check"] = cancel_check
        seen["before"] = cancel_check()
        window.close()
        seen["after"] = cancel_check()
        return None

    monkeypatch.setattr(
        project_io_mixin.DataLoader,
        "probe_blf_dbc_frames",
        staticmethod(probe_frames),
    )
    window = MainWindow()
    window.show()
    window._candidate_blf_dbc_paths = lambda _path: [[str(dbc)]]
    window._probe_blf_dbc_candidates(
        tmp_path / "sample.blf",
        frames=make_can_frames([(4, 0x123, engine_payload())]),
    )

    assert callable(seen["cancel_check"])
    assert seen["before"] is False
    assert seen["after"] is True


def test_top3_probes_all_candidates_and_selects_better_second(
    qapp, tmp_path, monkeypatch,
):
    import re
    from mf4_analyzer.blf_dbc_candidates import candidate_status
    from mf4_analyzer.io.blf_format import BlfDbcProbe
    from mf4_analyzer.ui.main_window import _project_io_mixin as project_io_mixin

    subject = object.__new__(project_io_mixin.ProjectIOMixin)
    dbcs = []
    for name in ("first.dbc", "better.dbc", "third.dbc"):
        path = tmp_path / name
        path.touch()
        dbcs.append(str(path))
    subject._candidate_blf_dbc_paths = lambda _path: [[path] for path in dbcs]
    monkeypatch.setattr(
        project_io_mixin,
        "load_dbc_frame_ids",
        lambda paths: {1, 2, 3},
        raising=False,
    )
    probes = []

    def stub_probe(dbc_path, *, matched_frames, decoded, signals, matched_ids):
        """Real BlfDbcProbe: a new probe field cannot silently default here."""
        return BlfDbcProbe(
            dbc_paths=(dbc_path,),
            total_frame_count=1000,
            total_frame_id_count=3,
            matched_frame_count=matched_frames,
            matched_frame_id_count=matched_ids,
            decode_sample_count=100,
            sampled_matched_frame_count=decoded,
            decoded_sample_count=decoded,
            signal_names=signals,
            sampling_strategy="stratified_front_mid_tail",
            sampling_complete=True,
        )

    def probe_frames(_frames, paths, **_kwargs):
        probes.append(tuple(paths))
        if paths[0] == dbcs[0]:
            return stub_probe(
                paths[0], matched_frames=800, decoded=85,
                signals=("a", "b"), matched_ids=3,
            )
        if paths[0] == dbcs[1]:
            return stub_probe(
                paths[0], matched_frames=950, decoded=99,
                signals=("a", "b", "c"), matched_ids=3,
            )
        return stub_probe(
            paths[0], matched_frames=200, decoded=20,
            signals=("a",), matched_ids=1,
        )

    monkeypatch.setattr(
        project_io_mixin.DataLoader,
        "probe_blf_dbc_frames",
        staticmethod(probe_frames),
    )
    frames = [(float(index), 1, b"\x00") for index in range(6)]
    candidates = subject._probe_blf_dbc_candidates(
        tmp_path / "sample.blf", frames=frames,
    )

    assert len(probes) == 3
    assert candidate_status(candidates[0]) == "strong"
    assert candidates[0]["paths"][0] == dbcs[1]
    text = subject._format_blf_dbc_candidate(candidates[0])
    # A stratified probe must say so, name the ID-hit line for what it is,
    # and never print a bare "帧 n/m" that reads as an exact decode count.
    assert "抽样解码 99/100 (99%)" in text
    assert "ID 命中 950/1000" in text
    assert "完整解码" not in text
    assert re.search(r"帧\s+\d+/\d+", text) is None
