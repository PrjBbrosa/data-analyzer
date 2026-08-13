"""UltraView operations must not compute, submit jobs, or write new cache keys."""
from __future__ import annotations

from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import UltraViewRef, membership_set
from tests.ui.ultraview_fakes import ComputeProbe, snapshot_source_state


def _source_identity(snap):
    managers = snap["managers"]
    return {
        "view_ids": {section: payload["view_ids"] for section, payload in managers.items()},
        "active": snap["active_indices"],
        "pins": snap["pins"],
        "cache_keys": snap["cache_keys"],
        "restore_pending": snap["restore_pending"],
        "attached": {
            section: tuple(
                tuple(view["payload"].get("attached_file_ids") or ())
                for view in payload["views"]
            )
            for section, payload in managers.items()
        },
        "checked": {
            section: tuple(
                tuple(
                    tuple(item) if isinstance(item, list) else item
                    for item in (view["payload"].get("checked") or view["payload"].get("panes") or ())
                )
                for view in payload["views"]
            )
            for section, payload in managers.items()
        },
    }


def test_ultraview_board_sequence_does_not_compute_or_mutate_sources(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    probe = ComputeProbe().install(win)
    before = snapshot_source_state(win)

    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv = win._ultraview

    win.toolbar.btn_mode_ultraview.click()
    QCoreApplication.processEvents()
    after_enter = snapshot_source_state(win)
    uv.add_from_source_tab("time", time_id)
    uv.add_from_source_tab("fft", fft_id)
    uv._on_layout("grid_2x2")
    uv._on_layout("hero_left_4")
    uv._on_ratio_nudge(1)
    uv._on_swap_slots("primary", "aux_0")
    uv._on_compare_filter("time")
    uv._on_focus("time", time_id)
    win.chart_stack.page_ultraview.show_focus("time", time_id)
    after_ops = snapshot_source_state(win)
    win.toolbar.btn_mode_time.click()
    QCoreApplication.processEvents()
    after_exit = snapshot_source_state(win)

    try:
        assert probe.compute_total == 0
        assert probe.job_total == 0
        assert probe.store_new_key_writes == 0
        assert probe.restore_pending_unchanged(win)
        assert _source_identity(after_enter) == _source_identity(before)
        assert after_ops == after_enter
        assert _source_identity(after_exit) == _source_identity(before)
        assert UltraViewRef("time", time_id) in membership_set(uv.board)
        assert UltraViewRef("fft", fft_id) in membership_set(uv.board)
    finally:
        probe.restore()
