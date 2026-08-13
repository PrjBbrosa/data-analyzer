"""UltraView operations must not compute, submit jobs, or write new cache keys."""
from __future__ import annotations

from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import UltraViewRef, membership_set
from tests.ui.ultraview_fakes import ComputeProbe, snapshot_source_state
from tests.ui.test_ultraview_preview_store import _image, _meta


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

    win.chart_stack.ultraview_entry.click()
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


def test_full_ultraview_export_sequence_stays_zero_compute(qapp, qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    probe = ComputeProbe().install(win)
    before = snapshot_source_state(win)
    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv = win._ultraview
    time_ref = UltraViewRef("time", time_id)
    win.open_ultraview()
    QCoreApplication.processEvents()
    uv.add_from_source_tab("time", time_id)
    uv.add_from_source_tab("fft", fft_id)
    uv._on_layout("grid_2x2")
    uv._on_layout("hero_left_4")
    uv._on_ratio_nudge(1)
    uv._on_swap_slots("primary", "aux_0")
    uv._on_compare_filter("time")
    uv.store.publish(
        time_ref, _image(32, 24), digest="seq", meta=_meta(time_ref, title="T")
    )
    uv._on_focus("time", time_id)
    uv._on_presentation(True)
    uv.copy_card_to_clipboard(time_ref)
    uv.copy_board_to_clipboard()
    uv.export_png_to_path(tmp_path / "uv-1x.png", scale=1)
    uv.export_png_to_path(tmp_path / "uv-2x.png", scale=2)
    uv._on_presentation(False)
    win.save_project(tmp_path / "uv.tlproj")
    win.toolbar.btn_mode_time.click()
    QCoreApplication.processEvents()
    after = snapshot_source_state(win)
    try:
        assert probe.compute_total == 0
        assert probe.job_total == 0
        assert probe.store_new_key_writes == 0
        assert probe.restore_pending_unchanged(win)
        assert _source_identity(after) == _source_identity(before)
        assert (tmp_path / "uv-1x.png").exists()
        assert (tmp_path / "uv-2x.png").exists()
    finally:
        probe.restore()


def test_inactive_worker_completion_does_not_capture_active_canvas(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    fft = win.analysis_managers["fft"]
    idx_b = fft.new_view()
    other_id = str(fft.get(idx_b).view_id)
    calls = []
    uv.request_capture = lambda *a, **k: calls.append("capture")
    uv.request_visible_section_capture = lambda *a, **k: calls.append("visible")
    key = ("fft", "inactive-key")
    uv.notify_result_stored("fft", other_id, 0, key, object())
    assert calls == []
    assert uv.result_generation_for("fft", other_id, 0, key) == 1
