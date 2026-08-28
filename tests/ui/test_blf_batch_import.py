"""One-event BLF batch import: DBC scope and one-read decode guarantees."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QMessageBox, QPushButton

pytest.importorskip("can", reason="python-can not installed (win32-gated)")
pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.io import DataLoader
from mf4_analyzer.io.blf_format import BlfDbcProbe
from tests._helpers.blf_factory import write_raw_blf, write_sample_blf, write_two_message_dbc


def _prepare_batch(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    first = write_sample_blf(tmp_path / "first.blf", n=5)
    second = write_sample_blf(tmp_path / "second.blf", n=5, t_start=3.0)
    return dbc, first, second


def _capture_message_box_button_layout(qapp, captured):
    """Measure a dialog's styled button geometry without showing it.

    The Windows Qt ``offscreen`` plugin can access-violate when a
    ``QMessageBox`` is shown and its event loop is pumped.  Polishing and
    sizing still exercise the real QSS and button-box layout without entering
    that native presentation path.
    """

    def capture(box):
        box.ensurePolished()
        box.adjustSize()
        qapp.processEvents()
        captured.update({
            button.text(): (
                button.fontMetrics().horizontalAdvance(button.text()),
                button.width(),
            )
            for button in box.buttons()
            if isinstance(button, QPushButton)
        })
        return 0

    return capture


def test_batch_dbc_is_confirmed_once_and_each_blf_is_read_once(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc, first, second = _prepare_batch(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_ask_blf_batch_dbc_action", lambda paths: "batch")
    monkeypatch.setattr(window, "_prompt_blf_dbc", lambda path: [str(dbc)])

    original_read = DataLoader.read_blf_frames
    reads = []

    def count_reads(path, **_kwargs):
        reads.append(str(path))
        return original_read(path)

    monkeypatch.setattr(DataLoader, "read_blf_frames", staticmethod(count_reads))
    monkeypatch.setattr(
        DataLoader,
        "load_blf",
        staticmethod(lambda *args, **kwargs: pytest.fail("batch must decode supplied frames")),
    )

    window._open_paths([str(first), str(second)])

    assert len(window.files) == 2
    assert reads == [str(first), str(second)]
    assert all("EngineSpeed" in fd.channels for fd in window.files.values())


def test_later_drop_starts_a_fresh_batch_dbc_decision(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc, first, second = _prepare_batch(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    confirmations = []
    picks = []
    monkeypatch.setattr(
        window,
        "_ask_blf_batch_dbc_action",
        lambda paths: confirmations.append(tuple(paths)) or "batch",
    )
    monkeypatch.setattr(
        window,
        "_prompt_blf_dbc",
        lambda path: picks.append(path) or [str(dbc)],
    )

    window._open_paths([str(first), str(second)])
    window._open_paths([str(first), str(second)])

    assert len(confirmations) == 2
    assert len(picks) == 2
    assert len(window.files) == 4


def test_batch_dbc_mismatch_can_skip_without_decoding_wrong_file(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    dbc, matching, _unused = _prepare_batch(tmp_path)
    unmatched = write_raw_blf(tmp_path / "unmatched.blf")
    window = MainWindow()
    qtbot.addWidget(window)
    mismatches = []
    monkeypatch.setattr(window, "_ask_blf_batch_dbc_action", lambda paths: "batch")
    monkeypatch.setattr(window, "_prompt_blf_dbc", lambda path: [str(dbc)])
    monkeypatch.setattr(
        window,
        "_ask_blf_batch_mismatch_action",
        lambda *args, **kwargs: mismatches.append(args[0]) or "skip",
    )

    window._open_paths([str(matching), str(unmatched)])

    assert len(window.files) == 1
    assert mismatches == [unmatched]


def test_batch_dbc_dialog_actions_fit_without_text_elision(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    load_stylesheet(qapp)
    window = MainWindow()
    qtbot.addWidget(window)
    captured = {}

    monkeypatch.setattr(
        QMessageBox, "exec_", _capture_message_box_button_layout(qapp, captured),
    )

    assert window._ask_blf_batch_dbc_action(["a.blf", "b.blf"]) == "cancel"
    assert set(captured) == {"统一选择 DBC", "逐个选择", "取消"}
    assert all(
        text_width + 28 <= button_width
        for text_width, button_width in captured.values()
    )


def test_batch_dbc_mismatch_actions_fit_without_text_elision(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    load_stylesheet(qapp)
    window = MainWindow()
    qtbot.addWidget(window)
    captured = {}

    monkeypatch.setattr(
        QMessageBox, "exec_", _capture_message_box_button_layout(qapp, captured),
    )

    assert window._ask_blf_batch_mismatch_action(
        Path("unmatched.blf"), ["bus.dbc"], 2,
    ) == "cancel"
    assert set(captured) == {"重选当前及后续 DBC", "跳过此文件", "停止剩余导入"}
    assert all(
        text_width + 28 <= button_width
        for text_width, button_width in captured.values()
    )


def test_last_batch_mismatch_mentions_only_current_file(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    captured = {}

    def capture(box):
        box.ensurePolished()
        box.adjustSize()
        qapp.processEvents()
        captured["informative"] = box.informativeText()
        captured["buttons"] = {
            button.text() for button in box.buttons()
            if isinstance(button, QPushButton)
        }
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", capture)

    assert window._ask_blf_batch_mismatch_action(
        Path("last.blf"), ["bus.dbc"], 0,
    ) == "cancel"
    assert "后续" not in captured["informative"]
    assert "0 个" not in captured["informative"]
    assert "重选当前 DBC" in captured["buttons"]


def test_mixed_import_registers_in_original_order_with_one_shared_dbc_choice(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    paths = [
        tmp_path / "a.csv",
        tmp_path / "b.blf",
        tmp_path / "c.csv",
        tmp_path / "d.blf",
    ]
    for path in paths:
        path.touch()
    window = MainWindow()
    qtbot.addWidget(window)
    loaded = []
    prompts = []
    monkeypatch.setattr(window, "_ask_blf_batch_dbc_action", lambda _paths: "batch")
    monkeypatch.setattr(
        window,
        "_prompt_blf_dbc",
        lambda path: prompts.append(path) or [str(tmp_path / "bus.dbc")],
    )
    monkeypatch.setattr(
        DataLoader,
        "read_blf_frames",
        staticmethod(lambda *_args, **_kwargs: [(0.0, 1, b"\x00")]),
    )
    monkeypatch.setattr(
        DataLoader,
        "probe_blf_dbc_frames",
        staticmethod(lambda *_args, **_kwargs: SimpleNamespace(is_match=True)),
    )
    monkeypatch.setattr(
        window,
        "_load_one",
        lambda path, **_kwargs: loaded.append(str(path)),
    )

    window._open_data_paths([str(path) for path in paths])

    assert loaded == [str(path) for path in paths]
    assert prompts == [paths[1]]


def test_import_transaction_deduplicates_normalized_paths_with_feedback(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    original = tmp_path / "source.csv"
    original.touch()
    # ``realpath`` must collapse a lexical alias without requiring Windows
    # symlink-creation privilege (often unavailable in CI and user sessions).
    alias = tmp_path / "normalization-probe" / ".." / original.name
    window = MainWindow()
    qtbot.addWidget(window)
    loaded = []
    notices = []
    monkeypatch.setattr(
        window,
        "_load_one",
        lambda path, **_kwargs: loaded.append(str(path)),
    )
    monkeypatch.setattr(
        window,
        "toast",
        lambda message, level="info": notices.append((message, level)),
    )

    window._open_data_paths([str(original), str(alias), str(original.resolve())])

    assert loaded == [str(original)]
    assert any("跳过 2 个重复文件" in message for message, _level in notices)


def test_history_deduplication_keeps_most_recent_display_order(tmp_path):
    from mf4_analyzer.ui.main_window import _project_io_mixin as project_io_mixin

    first = tmp_path / "first.dbc"
    second = tmp_path / "second.dbc"
    first.touch()
    second.touch()
    subject = object.__new__(project_io_mixin.ProjectIOMixin)

    history = subject._clean_blf_dbc_history(
        [[str(first), str(second)], [str(second), str(first)]]
    )

    assert history == [[str(second.resolve()), str(first.resolve())]]


def test_candidate_probe_deduplicates_sets_and_leaves_overflow_unverified(
    tmp_path, monkeypatch,
):
    from mf4_analyzer.blf_dbc_candidates import candidate_status
    from mf4_analyzer.ui.main_window import _project_io_mixin as project_io_mixin

    subject = object.__new__(project_io_mixin.ProjectIOMixin)
    dbcs = []
    for index in range(1, 7):
        dbc = tmp_path / f"bus-{index}.dbc"
        dbc.touch()
        dbcs.append(str(dbc))
    candidate_sets = [
        [dbcs[0], dbcs[1]],
        [dbcs[1], dbcs[0]],
        [dbcs[2]],
        [dbcs[3]],
        [dbcs[4]],
        [dbcs[5]],
    ]
    subject._candidate_blf_dbc_paths = lambda _path: candidate_sets

    frame_id_by_path = {
        path: {index}
        for index, path in enumerate(dbcs, 1)
    }
    monkeypatch.setattr(
        project_io_mixin,
        "load_dbc_frame_ids",
        lambda paths: set().union(*(frame_id_by_path[path] for path in paths)),
        raising=False,
    )
    probes = []

    def probe_frames(_frames, paths, **_kwargs):
        probes.append(tuple(paths))
        # Real BlfDbcProbe rather than a hand-rolled namespace: the stub used
        # to carry retired fields (decoded_frame_count / decoded_frame_ratio)
        # and miss every sampling field, so it could not catch copy or status
        # changes that read them.
        return BlfDbcProbe(
            dbc_paths=tuple(paths),
            total_frame_count=6,
            total_frame_id_count=6,
            matched_frame_count=1,
            matched_frame_id_count=1,
            decode_sample_count=4,
            sampled_matched_frame_count=1,
            decoded_sample_count=1,
            signal_names=("value",),
            sampling_strategy="complete",
            sampling_complete=True,
        )

    monkeypatch.setattr(
        project_io_mixin.DataLoader,
        "probe_blf_dbc_frames",
        staticmethod(probe_frames),
    )
    frames = [(float(index), index, b"\x00") for index in range(1, 7)]

    candidates = subject._probe_blf_dbc_candidates(
        tmp_path / "sample.blf", frames=frames,
    )

    assert len(probes) == 3
    assert len(candidates) == 5
    assert sum(candidate_status(candidate) == "unverified" for candidate in candidates) == 2
    assert sum(candidate_status(candidate) == "weak" for candidate in candidates) == 3
    identities = [candidate["identity"] for candidate in candidates]
    assert len(identities) == len(set(identities))
    assert any(
        "未校验" in subject._format_blf_dbc_candidate(candidate)
        for candidate in candidates
        if candidate_status(candidate) == "unverified"
    )
    probed_text = next(
        subject._format_blf_dbc_candidate(candidate)
        for candidate in candidates
        if candidate_status(candidate) == "weak"
    )
    assert "弱匹配" in probed_text
    assert "完整解码 1/4 (25%)" in probed_text
