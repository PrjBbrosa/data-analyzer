"""File lifecycle must leave discarded Python cycles collectable."""
from __future__ import annotations

import gc
import weakref

from mf4_analyzer.ui.main_window import MainWindow


class _CyclicPayload:
    def __init__(self):
        self.self_ref = self
        self.data = bytearray(1024 * 1024)


def _write_csv(path):
    path.write_text("Time,sig\n0,1\n0.1,2\n0.2,3\n", encoding="utf-8")
    return str(path)


def test_load_and_close_leave_cycles_collectable(qapp, qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    keeper = _write_csv(tmp_path / "keeper.csv")
    win.load_file(keeper)
    keeper_id = next(iter(win.files))
    try:
        # Keep another file open: closing one source must not retain every
        # cyclic object that happened to be alive during that file's load.
        for index in range(3):
            payload = _CyclicPayload()
            ref = weakref.ref(payload)
            win.load_file(_write_csv(tmp_path / f"cycle-{index}.csv"))
            fid = next(fid for fid in win.files if fid != keeper_id)
            del payload
            win._close(fid, force=True)
            gc.collect()
            assert keeper_id in win.files
            assert ref() is None, "load froze unreachable cyclic objects"

        payload = _CyclicPayload()
        ref = weakref.ref(payload)
        win.load_file(_write_csv(tmp_path / "last.csv"))
        del payload
        win.close_all(force=True)
        gc.collect()
        assert ref() is None, "close-all refroze cyclic garbage"
    finally:
        # Baseline reproduction freezes the whole test process. Undo it on
        # failure so later tests do not inherit permanent roots.
        gc.unfreeze()
        win.close_all(force=True)
        gc.unfreeze()
        gc.collect()
