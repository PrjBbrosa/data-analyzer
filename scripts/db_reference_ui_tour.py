"""Scripted end-to-end tour of the dB-reference default system (Task 10).

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
section 17. Plan: ``docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md``
Task 10 / Step 10.1-10.3.

Drives a REAL ``MainWindow`` with synthetic ``FileData`` (explicit channel
metadata, never a real MF4/HDF file) and an ISOLATED temporary ``QSettings``
INI (never the developer's real MF4Analyzer/DataAnalyzer store) through the
nine spec §17.3 rendered states, saving one PNG per state and running the
Step 10.2 structural/geometry assertions.

Offscreen by default; ``--onscreen`` uses the real screen (macOS on-screen
gate, mandatory per CLAUDE.md's 验真机渲染 rule -- offscreen green alone does
not prove the visual contract).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _isolate_qsettings(tmp_dir: Path) -> None:
    """Redirect every ``_preset_settings()`` factory (and any bare
    ``QSettings()``) to a throwaway INI under ``tmp_dir`` -- mirrors
    ``tests/ui/conftest.py::_isolate_qsettings`` exactly (same modules, same
    ``setDefaultFormat``/``setPath`` diversion) so this script can NEVER
    touch the developer's real MF4Analyzer/DataAnalyzer store, including the
    dB-reference catalog (``MainWindow._db_reference_settings`` resolves
    ``_preset_settings`` from ``inspector_sections._helpers`` at call time,
    so patching the module attribute here is picked up live)."""
    from PyQt5.QtCore import QSettings
    import mf4_analyzer.ui.inspector_sections as _pkg
    import mf4_analyzer.ui.inspector_sections._helpers as _helpers_mod
    import mf4_analyzer.ui.inspector_sections.collapsible as _collapsible_mod
    import mf4_analyzer.ui.inspector_sections.presets as _presets_mod
    import mf4_analyzer.ui.inspector_sections.persistent_top as _persistent_top_mod

    ini = str(tmp_dir / "qsettings.ini")

    def _temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for mod in (_pkg, _helpers_mod, _collapsible_mod, _presets_mod, _persistent_top_mod):
        if hasattr(mod, "_preset_settings"):
            mod._preset_settings = _temp_settings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_dir))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_dir))


def _write_synthetic_csv(path: Path) -> None:
    """One synthetic file covering every unit the spec resolver table names
    (Pa / m/s² / m/s / N) plus a strictly-positive rpm-like base channel for
    Order (EPS/rotating-machinery convention: the order base is the MOTOR's
    own rotational speed, never an "engine" name -- see lessons-learned
    project-eps-order-domain). No channel is named/shaped for audio, so
    ``is_audio_source()`` stays False and never injects an A-weighting
    default that would fight this script's own weighting choices."""
    import numpy as np
    import pandas as pd

    fs = 2000.0
    n = 4000  # 2.0s
    t = np.arange(n) / fs
    df = pd.DataFrame({
        "time": t,
        # acceleration, m/s^2 -- system catalog default is 1e-6 (A1/state 1).
        "MOTOR_Y_ACC": 3.0 * np.sin(2 * np.pi * 80 * t),
        # velocity, m/s -- system catalog default is 1e-9 (mixed overlay, state 4).
        "BEARING_VEL": 0.015 * np.sin(2 * np.pi * 45 * t),
        # sound pressure, Pa -- system catalog default is 2e-5 == "20 µPa" (state 3/5).
        "MIC_PRESSURE": 0.3 * np.sin(2 * np.pi * 300 * t),
        # force, N -- system catalog default is 1e-6 (state 6, Order).
        "MOUNT_FORCE": 15.0 + 4.0 * np.cos(2 * np.pi * 60 * t),
        # rpm-like Order base: strictly positive, slow-varying.
        "MOTOR_RPM": 1500.0 + 250.0 * np.sin(2 * np.pi * 1.5 * t),
    })
    df.to_csv(path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="dB-reference UI tour")
    parser.add_argument(
        "--assert", dest="do_assert", action="store_true",
        help="validate Step 10.2 invariants and exit 1 on failure",
    )
    parser.add_argument("--shots", type=Path, default=None, help="screenshot dir")
    parser.add_argument(
        "--onscreen", action="store_true",
        help="use the real screen instead of offscreen (macOS gate)",
    )
    args = parser.parse_args()

    if not args.onscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("TMPDIR", "/tmp")

    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    tmp_root = Path(tempfile.mkdtemp(prefix="db_reference_tour_"))

    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    _isolate_qsettings(tmp_root)

    from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font

    setup_chinese_font()
    try:
        from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
        apply_global_chart_font(app)
    except Exception as exc:  # noqa: BLE001 - tour should still expose failures
        print(f"[tour] chart font setup failed: {exc!r}")
    try:
        load_stylesheet(app)
    except Exception as exc:  # noqa: BLE001
        print(f"[tour] stylesheet load failed: {exc!r}")

    from mf4_analyzer import db_reference
    from mf4_analyzer.ui.db_reference_dialog import DbReferenceDefaultsDialog
    from mf4_analyzer.ui.main_window import MainWindow

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        tag = "PASS" if cond else "FAIL"
        print(f"[assert] {tag} {msg}")
        if not cond:
            failures.append(msg)

    def shot(widget, name: str) -> None:
        if args.shots is None:
            return
        pm = widget.grab()
        pm.save(str(args.shots / f"{name}.png"))
        print(f"[shot] {name} {pm.width()}x{pm.height()}")

    def pump(ms: int = 30) -> None:
        deadline = time.monotonic() + ms / 1000.0
        while time.monotonic() < deadline:
            app.processEvents()

    def wait_until(cond, timeout_s: float = 15.0, label: str = "") -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        print(f"[tour] wait_until TIMED OUT: {label}")
        return False

    def check_object_names_once(scope, names) -> None:
        # findChildren needs a QObject-derived base filter; QWidget covers
        # every dbReference* object in this widget family.
        from PyQt5.QtWidgets import QWidget
        for name in names:
            matches = scope.findChildren(QWidget, name)
            check(
                len(matches) == 1,
                f"object-name '{name}' exists exactly once under "
                f"{scope.objectName() or type(scope).__name__} (found {len(matches)})",
            )

    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    pump(50)

    # -- Load one synthetic file, then stamp explicit channel metadata ------
    csv_path = tmp_root / "db_reference_tour.csv"
    _write_synthetic_csv(csv_path)
    window._load_one(str(csv_path))
    pump(50)
    check(len(window.files) == 1, f"synthetic file loaded ({len(window.files)} files)")
    fid = next(iter(window.files.keys()))
    fd = window.files[fid]
    fd.channel_metadata = {
        "MOTOR_Y_ACC": {"quantity": "acceleration", "unit": "m/s²"},
        "BEARING_VEL": {"quantity": "velocity", "unit": "m/s"},
        "MIC_PRESSURE": {"quantity": "sound pressure", "unit": "Pa"},
        "MOUNT_FORCE": {"quantity": "force", "unit": "N"},
        "MOTOR_RPM": {"quantity": "rotational speed", "unit": "rpm"},
    }

    _COMPOUND_NAMES = (
        "dbReferenceControl", "dbReferenceEditor", "dbReferenceManageButton",
        "dbReferenceModeBadge", "dbReferenceSourceLabel",
    )
    _DIALOG_SINGLETON_NAMES = (
        "dbReferenceDialogTitle", "dbReferenceDialogSubtitle",
        "dbReferenceDialogClose", "dbReferenceDialogTable", "dbReferenceDialogError",
    )

    def assert_compound_geometry(ctx, tag: str) -> None:
        """Shared Step 10.2 geometry proof, run against the LIVE, embedded
        production widget (not a standalone Contextual) so QScrollArea/
        splitter chrome is part of the proof."""
        control = ctx.db_reference_control
        control.refresh_geometry()
        pump(10)
        check_object_names_once(ctx, _COMPOUND_NAMES)
        btn = control.manage_button
        editor_h = control.editor.height()
        check(
            editor_h > 0 and btn.height() == editor_h and btn.width() == btn.height(),
            f"{tag}: manage button square + editor-matched height "
            f"(editor_h={editor_h}, btn={btn.width()}x{btn.height()})",
        )
        top_left = control.mapTo(ctx, control.rect().topLeft())
        content_rect = ctx.rect()
        control_rect_in_ctx = control.rect().translated(top_left)
        check(
            content_rect.contains(control_rect_in_ctx),
            f"{tag}: compound rect {control_rect_in_ctx} inside Inspector "
            f"content rect {content_rect}",
        )
        check(
            content_rect.contains(control.badge.geometry().translated(top_left)),
            f"{tag}: badge rect fully contained (no clip)",
        )
        source_text = control.source_label.text()
        check(
            "\n" not in source_text,
            f"{tag}: source line stays single-line ({source_text!r})",
        )
        editor_text = control.editor.lineEdit().text()
        expected_editor_text = db_reference.format_reference_editor(control.editor.value())
        check(
            editor_text == expected_editor_text and len(editor_text) >= 3,
            f"{tag}: scientific editor text not elided into an unusable token "
            f"({editor_text!r} == {expected_editor_text!r})",
        )

    # ======================================================================
    # State 1 -- FFT Auto + system acceleration reference
    # ======================================================================
    window.toolbar._set_mode("fft")
    pump(30)
    ctx_fft = window.inspector.fft_ctx
    # The "谱参数" params section (which HOSTS the compound dB-reference row)
    # defaults COLLAPSED (tests/ui/conftest.py's isolate-qsettings docstring
    # documents this same default-collapsed contract). A collapsed section's
    # body stays hidden/unlaid-out (Qt leaves it at its raw default 640x480
    # size), so expand it FIRST -- this is also exactly what a real user
    # does to see the control, not a test-only workaround.
    ctx_fft._fft_section.set_expanded(True)
    pump(30)
    window.navigator.set_checked_channels([(fid, "MOTOR_Y_ACC")])
    window._echo_combo_signal(ctx_fft.combo_sig, (fid, "MOTOR_Y_ACC"))
    # ``_echo_combo_signal`` only fires the compound control's Auto refresh
    # via Qt's currentIndexChanged, which is a no-op if the combo already
    # happened to sit on this index (e.g. the first-loaded channel). Call
    # the SAME production resolve entry point the signal handler calls, so
    # the compound control's displayed value/badge/source-line are always
    # exercised through the real pipeline regardless of combo start state.
    window._resolve_and_apply_db_reference("fft")
    pump(30)
    ctx_fft.combo_amp_y.setCurrentText("dB")
    ctx_fft.combo_weighting.setCurrentText("None")
    window.do_fft()
    pump(50)

    canvas_fft = window.chart_stack.page_fft.pane_canvas(0)
    control_fft = ctx_fft.db_reference_control
    check(control_fft.mode() == "auto", "state1: fresh FFT view defaults Auto")
    check(
        math.isclose(control_fft.editor.value(), 1e-6, rel_tol=1e-9),
        f"state1: Auto resolves system acceleration default (got {control_fft.editor.value()!r})",
    )
    check(
        "系统默认" in control_fft.full_source_text(),
        f"state1: source line names 系统默认 ({control_fft.full_source_text()!r})",
    )
    expected_axis_1 = "Amplitude (dB re 1×10⁻⁶ m/s²)"
    check(
        canvas_fft._plot_amp.getAxis("left").labelText == expected_axis_1,
        f"state1: FFT axis literal ({canvas_fft._plot_amp.getAxis('left').labelText!r})",
    )
    assert_compound_geometry(ctx_fft, "state1")
    shot(window, "01-fft-auto-system-acceleration")

    # ======================================================================
    # State 2 -- FFT Manual + amber M badge
    # ======================================================================
    editor = control_fft.editor
    editor.lineEdit().selectAll()
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    QTest.keyClicks(editor.lineEdit(), "2.5e-6")
    QTest.keyClick(editor, Qt.Key_Return)
    pump(30)
    check(control_fft.mode() == "manual", "state2: editor commit flips Auto -> Manual")
    check(control_fft.badge.text() == "M", "state2: badge shows M")
    check(control_fft.badge.property("mode") == "manual", "state2: badge property mode=manual")
    window.do_fft()
    pump(30)
    shot(window, "02-fft-manual-amber-m")

    # ======================================================================
    # State 3 -- FFT dBA axis (sound pressure, A-weighted)
    # ======================================================================
    control_fft.set_mode("auto")  # back to Auto for the MIC channel's own resolution
    window.navigator.set_checked_channels([(fid, "MIC_PRESSURE")])
    window._echo_combo_signal(ctx_fft.combo_sig, (fid, "MIC_PRESSURE"))
    window._resolve_and_apply_db_reference("fft")
    ctx_fft.combo_weighting.setCurrentText("A")
    pump(30)
    window.do_fft()
    pump(50)
    expected_axis_3 = "Sound pressure (dBA re 20 µPa)"
    got_axis_3 = canvas_fft._plot_amp.getAxis("left").labelText
    check(got_axis_3 == expected_axis_3, f"state3: dBA axis literal ({got_axis_3!r})")
    shot(window, "03-fft-dba-axis")

    # ======================================================================
    # State 4 -- FFT mixed-reference overlay (per-curve)
    # ======================================================================
    ctx_fft.combo_weighting.setCurrentText("None")
    window.navigator.set_checked_channels([
        (fid, "MOTOR_Y_ACC"), (fid, "BEARING_VEL"),
    ])
    window._echo_combo_signal(ctx_fft.combo_sig, (fid, "MOTOR_Y_ACC"))
    pump(30)
    window.do_fft()
    pump(50)
    expected_axis_4 = "Amplitude (dB · per-curve reference)"
    got_axis_4 = canvas_fft._plot_amp.getAxis("left").labelText
    check(got_axis_4 == expected_axis_4, f"state4: mixed axis literal ({got_axis_4!r})")
    check(len(canvas_fft._entries) == 2, "state4: two overlay entries")
    if len(canvas_fft._entries) == 2:
        e0, e1 = canvas_fft._entries
        check(
            e0["legend_label"] != e1["legend_label"],
            "state4: each curve discloses its OWN per-curve reference",
        )
    shot(window, "04-fft-mixed-per-curve")

    # ======================================================================
    # State 5 -- FFT-vs-Time dBA colorbar + slice
    # ======================================================================
    window.toolbar._set_mode("fft_time")
    pump(30)
    ctx_ft = window.inspector.fft_time_ctx
    ctx_ft._tf_section.set_expanded(True)
    pump(30)
    window._echo_combo_signal(ctx_ft.combo_sig, (fid, "MIC_PRESSURE"))
    window._resolve_and_apply_db_reference("fft_time")
    ctx_ft.combo_weighting.setCurrentText("A")
    i = ctx_ft.combo_nfft.findText("512")
    if i >= 0:
        ctx_ft.combo_nfft.setCurrentIndex(i)
    pump(30)
    window.do_fft_time()
    wait_until(
        lambda: not window._analysis_jobs.is_running("fft_time"),
        label="fft_time compute",
    )
    canvas_ft = window.chart_stack.page_fft_time.pane_canvas(0)
    check(canvas_ft.has_result(), "state5: FFT-vs-Time has a result")
    resolution_ft = window._resolve_db_reference_for_source("fft_time", (fid, "MIC_PRESSURE"))
    expected_ft = db_reference.format_amplitude_label(
        resolution_ft, weighting="A", output_scale="db")
    check(expected_ft == "Sound pressure (dBA re 20 µPa)", f"state5: expected literal ({expected_ft!r})")
    got_cbar = canvas_ft._cbar.getAxis("left").labelText if canvas_ft._cbar is not None else None
    got_slice = canvas_ft._slice_plot.getAxis("left").labelText
    check(got_cbar == expected_ft, f"state5: colorbar label matches ({got_cbar!r})")
    check(got_slice == expected_ft, f"state5: slice axis label matches ({got_slice!r})")
    assert_compound_geometry(ctx_ft, "state5")
    shot(window, "05-fft-time-dba-colorbar-slice")

    # ======================================================================
    # State 6 -- Order dB colorbar + slice
    # ======================================================================
    window.toolbar._set_mode("order")
    pump(30)
    ctx_order = window.inspector.order_ctx
    ctx_order._order_section.set_expanded(True)
    pump(30)
    window._echo_combo_signal(ctx_order.combo_sig, (fid, "MOUNT_FORCE"))
    window._echo_combo_signal(ctx_order.combo_rpm, (fid, "MOTOR_RPM"))
    window._resolve_and_apply_db_reference("order")
    ctx_order.combo_weighting.setCurrentText("None")
    pump(30)
    window.do_order_time()
    wait_until(
        lambda: not window._analysis_jobs.is_running("order"),
        timeout_s=20.0, label="order compute",
    )
    canvas_order = window.chart_stack.page_order.pane_canvas(0)
    check(canvas_order.has_result(), "state6: Order has a result")
    resolution_order = window._resolve_db_reference_for_source("order", (fid, "MOUNT_FORCE"))
    expected_order = db_reference.format_amplitude_label(
        resolution_order, weighting="None", output_scale="db")
    check(
        expected_order == "Amplitude (dB re 1×10⁻⁶ N)",
        f"state6: expected literal ({expected_order!r})",
    )
    got_cbar_o = canvas_order._cbar.getAxis("left").labelText if canvas_order._cbar is not None else None
    got_slice_o = canvas_order._slice_plot.getAxis("left").labelText
    check(got_cbar_o == expected_order, f"state6: colorbar label matches ({got_cbar_o!r})")
    check(got_slice_o == expected_order, f"state6: slice axis label matches ({got_slice_o!r})")
    assert_compound_geometry(ctx_order, "state6")
    shot(window, "06-order-db-colorbar-slice")

    # ======================================================================
    # State 7 -- Defaults dialog factory state
    # ======================================================================
    dlg = DbReferenceDefaultsDialog(
        window, window.db_reference_store,
        current_mode=ctx_order.db_reference_control.mode(),
        current_effective_summary=ctx_order.db_reference_control.full_source_text(),
    )
    dlg.show()
    pump(30)
    check_object_names_once(dlg, _DIALOG_SINGLETON_NAMES)
    screen = dlg.screen() if hasattr(dlg, "screen") else app.primaryScreen()
    avail = (screen or app.primaryScreen()).availableGeometry()
    check(
        dlg.width() <= avail.width() and dlg.height() <= avail.height(),
        f"state7: dialog fits available screen (dlg={dlg.width()}x{dlg.height()}, "
        f"avail={avail.width()}x{avail.height()})",
    )
    check(
        dlg._btn_save.isVisible() and dlg.table.isVisible(),
        "state7: footer/table visible in factory state",
    )
    check(
        dlg.table.rowCount() == len(db_reference.FACTORY_CATALOG_V1),
        f"state7: factory row count ({dlg.table.rowCount()})",
    )
    check(not dlg._error_label.isVisible(), "state7: no error banner in factory state")
    shot(dlg, "07-dialog-factory-state")

    # ======================================================================
    # State 8 -- Defaults dialog edited/error state
    # ======================================================================
    idx = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "force.si")
    dlg._reference_editors[idx].setValue(-1.0)
    pump(10)
    dlg._btn_save.click()
    pump(30)
    check(dlg.result() != 1, "state8: invalid save does not accept the dialog")
    check(dlg._error_label.isVisible(), "state8: error banner visible")
    check(bool(dlg._error_label.text()), "state8: error banner has text")
    check(idx in dlg._row_errors, "state8: offending row flagged inline")
    shot(dlg, "08-dialog-edited-error-state")
    dlg._reference_editors[idx].setValue(1e-6)  # leave the working copy valid
    dlg.reject()
    pump(20)

    # ======================================================================
    # State 9 -- narrow app width / 288-320px Inspector
    # ======================================================================
    window.resize(960, 700)
    pump(50)
    win_w = window.width()
    insp_w = window.inspector.width()
    check(
        288 <= insp_w <= 320,
        f"state9: Inspector stays within 288-320px at app width={win_w} "
        f"(inspector={insp_w})",
    )
    if win_w != 960:
        print(
            f"[tour] state9 note: MainWindow.setMinimumSize floors the app "
            f"at {win_w}px (pre-existing red line, not touched by this "
            f"task) -- the achieved narrow width is {win_w}px, not the "
            f"literal 960px; Inspector width is still verified in range."
        )
    assert_compound_geometry(ctx_order, "state9")
    shot(window, "09-narrow-app-inspector")

    window.close()
    app.processEvents()

    if args.do_assert and failures:
        print(f"[tour] {len(failures)} invariant(s) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("[tour] all invariants passed" if args.do_assert else "[tour] done")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
