"""D-I: freeze long-lived objects after a load; unfreeze only when none remain."""
from __future__ import annotations

import gc

from mf4_analyzer.ui.main_window import MainWindow


def _write_csv(path):
    path.write_text("Time,sig\n0,1\n0.1,2\n0.2,3\n", encoding="utf-8")
    return str(path)


def test_load_freezes_once_per_batch_and_unfreeze_waits_for_empty_workspace(
    qapp, qtbot, tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(gc, "unfreeze", lambda: calls.append("unfreeze"))

    win = MainWindow()
    qtbot.addWidget(win)
    assert calls == []

    # Closing an already-empty workspace must not unfreeze startup objects.
    win.close_all(force=True)
    assert calls == []

    win._open_data_paths([
        _write_csv(tmp_path / "a.csv"),
        _write_csv(tmp_path / "b.csv"),
    ])
    assert len(win.files) == 2
    assert calls == ["freeze"]

    fid_a, fid_b = list(win.files)
    win._close(fid_a, force=True)
    assert fid_b in win.files
    assert "unfreeze" not in calls
    assert calls == ["freeze"]

    win._close(fid_b, force=True)
    assert win.files == {}
    assert calls == ["freeze", "unfreeze", "freeze"]

    # Group close (notify=False) still refreezes once, on the last source.
    calls.clear()
    win._open_data_paths([
        _write_csv(tmp_path / "c.csv"),
        _write_csv(tmp_path / "d.csv"),
    ])
    assert calls == ["freeze"]
    group = list(win.files)
    win._close(group[0], force=True, notify=False)
    assert len(win.files) == 1
    assert calls == ["freeze"]
    win._close(group[1], force=True, notify=False)
    assert win.files == {}
    assert calls == ["freeze", "unfreeze", "freeze"]

    calls.clear()
    win.load_file(_write_csv(tmp_path / "e.csv"))
    assert len(win.files) == 1
    assert calls == ["freeze"]
    win.close_all(force=True)
    assert win.files == {}
    assert calls == ["freeze", "unfreeze", "freeze"]
