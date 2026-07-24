"""Regenerate the four help-guide panel screenshots (time / fft / fft_time /
order) by booting the real MainWindow, loading synthetic data, driving each
mode to a populated state, and grabbing the whole window at 2x.

Outputs to a STAGING dir (output/help-shots/) by default — review the PNGs,
then re-run with --promote to copy them over mf4_analyzer/help/assets/. The
guides' numbered pins are tied to UI element positions, so after promoting
NEW screenshots you must re-check the pin left/top% in each *-guide.html.

The ``imports`` shot loads checked-in real WWT, ZFD and MAT samples.  It is
used by the software manual as visual evidence that the current build opens
those formats; unlike the four analysis panels, it is not a synthetic-data
demonstration.

Renders against a REAL Qt platform (cocoa on macOS) by default so the panels
look exactly as the user sees them. --platform offscreen is a headless
fallback for layout/draft ONLY (offscreen != real render; do not treat an
offscreen image as visually verified).

Window geometry is FIXED at 1640x1010 to MATCH the shipped assets' framing
(the original *-panel.png are 1640x1010, EPS-domain data: 方向盘扭矩 / 电机转速).
Matching the original logical layout keeps the guides' numbered pins valid —
they point at chrome (mode tabs / toolbar / channel list / View tabs) whose
positions don't move. Still give the rendered guide a browser eyeball after
promoting; only nudge pins if a control actually relocated.

Usage:
    .venv/bin/python tools/gen_help_screenshots.py                 # all 4 -> staging
    .venv/bin/python tools/gen_help_screenshots.py --only time
    .venv/bin/python tools/gen_help_screenshots.py --only imports
    .venv/bin/python tools/gen_help_screenshots.py --platform offscreen
    .venv/bin/python tools/gen_help_screenshots.py --promote       # copy staging -> assets
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PANEL_MODES = ("time", "fft", "fft_time", "order")
PANEL_FILES = {
    "time": "time-panel.png",
    "fft": "fft-panel.png",
    "fft_time": "ffttime-panel.png",
    "order": "order-panel.png",
}
EXTRA_SHOTS = ("imports",)
EXTRA_FILES = {"imports": "imports-panel.png"}
STAGING_DIR = REPO_ROOT / "output" / "help-shots"
ASSETS_DIR = REPO_ROOT / "mf4_analyzer" / "help" / "assets"
# Match the shipped assets exactly (1640x1010): scale grab to logical size so
# pins (which are % of the image) line up with the original framing.
WIN_W, WIN_H = 1640, 1010
GRAB_SCALE = 1

# EPS-domain channel names (matches how the shipped *-panel.png were made and
# the project's EPS convention: order base = 电机转速). 信号 = 方向盘扭矩.
CH_RPM = "电机转速"
CH_SIGNAL = "方向盘扭矩"
CH_TORQUE = "电机扭矩"

IMPORT_SAMPLES = (
    REPO_ROOT / "testdoc" / "wwt" / "NLTNP_000089.wwt",
    REPO_ROOT / "testdoc" / "wwt" / "end of travel_1.zfd",
    REPO_ROOT / "testdoc" / "175rpm_-45deg-270tighten.mat",
)


def _install_isolated_qsettings(settings_dir: Path) -> None:
    """Divert screenshot-only UI persistence away from the user's settings.

    The live Inspector imports ``_preset_settings`` into several modules, so
    changing ``QSettings.setPath`` alone is insufficient for the explicit
    ``QSettings(org, app)`` store.  Keep this list aligned with the UI test
    fixture in ``tests/ui/conftest.py``.
    """
    from PyQt5.QtCore import QSettings
    import mf4_analyzer.ui.inspector_sections as package
    import mf4_analyzer.ui.inspector_sections._helpers as helpers
    import mf4_analyzer.ui.inspector_sections.collapsible as collapsible
    import mf4_analyzer.ui.inspector_sections.presets as presets
    import mf4_analyzer.ui.inspector_sections.persistent_top as persistent_top

    ini = str(settings_dir / "qsettings.ini")

    def temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for module in (package, helpers, collapsible, presets, persistent_top):
        if hasattr(module, "_preset_settings"):
            setattr(module, "_preset_settings", temp_settings)

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_dir))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(settings_dir))


def build_synthetic_csv() -> Path:
    """电机转速 ramp 600->3600 + 方向盘扭矩 (order1+order2) + 电机扭矩 channel."""
    fs = 8000.0
    dur = 6.0
    n = int(fs * dur)
    t = np.arange(n, dtype=float) / fs
    rpm = np.linspace(600.0, 3600.0, n)
    revs = np.cumsum(rpm / 60.0) / fs
    phase = 2.0 * np.pi * revs
    rng = np.random.default_rng(7)
    signal = 1.0 * np.sin(phase) + 0.6 * np.sin(2.0 * phase) + 0.05 * rng.standard_normal(n)
    torque = 8.0 + 2.0 * np.sin(2.0 * np.pi * 0.5 * t) + 0.02 * rng.standard_normal(n)
    out = Path(tempfile.gettempdir()) / "_eps_demo.csv"
    data = np.column_stack([t, rpm, signal, torque])
    np.savetxt(out, data, delimiter=",",
               header=f"time,{CH_RPM},{CH_SIGNAL},{CH_TORQUE}",
               comments="", fmt="%.6g")
    return out


def _select_combo_by_channel(combo, channel_name: str) -> bool:
    for i in range(combo.count()):
        data = combo.itemData(i)
        if isinstance(data, tuple) and len(data) == 2 and data[1] == channel_name:
            combo.setCurrentIndex(i)
            return True
    return False


def _check_channels(win, names) -> None:
    """Tick the named channel leaves in the left MultiFileChannelWidget tree."""
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    widget = win.findChild(MultiFileChannelWidget)
    if widget is None:
        return
    tree = widget.tree
    for top in range(tree.topLevelItemCount()):
        file_node = tree.topLevelItem(top)
        for i in range(file_node.childCount()):
            leaf = file_node.child(i)
            if leaf.text(0) in names:
                leaf.setCheckState(0, Qt.Checked)


def _wait_for_analysis(trigger, section: str, win, timeout_ms=60_000) -> bool:
    """Run one section and wait for current ``AnalysisJobService`` cleanup."""
    from PyQt5.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    state = {"failed": "", "timed_out": False}

    def on_failed(failed_section, _ctx, message):
        if failed_section == section:
            state["failed"] = str(message)

    def poll():
        if not win._analysis_jobs.is_running(section):
            loop.quit()

    win._analysis_jobs.failed.connect(on_failed)
    poller = QTimer()
    poller.timeout.connect(poll)
    poller.start(20)
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(lambda: (state.__setitem__("timed_out", True), loop.quit()))
    wd.start(timeout_ms)
    trigger()
    poll()
    if win._analysis_jobs.is_running(section):
        loop.exec_()
    poller.stop()
    wd.stop()
    win._analysis_jobs.failed.disconnect(on_failed)
    if state["failed"]:
        print(f"FAIL: {section} analysis: {state['failed']}", file=sys.stderr)
    return not state["timed_out"] and not state["failed"]


def _drive_imports(win, app) -> None:
    """Load three real v7.8 measurement formats and show one WWT curve."""
    from PyQt5.QtCore import QEventLoop, QTimer

    missing = [str(path) for path in IMPORT_SAMPLES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing import screenshot samples: {missing}")
    for path in IMPORT_SAMPLES:
        win.load_file(str(path))
        app.processEvents()
        # Let the real proxy/source models finish one file before the next
        # source-model reset.  This keeps the captured navigator stable and
        # avoids masking a mid-update model behind a successful grab.
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec_()
    _check_channels(win, {"Steering torque"})
    app.processEvents()


def _drive_mode(win, app, mode: str) -> None:
    win.toolbar._set_mode(mode)
    app.processEvents()
    if mode == "time":
        _check_channels(win, {CH_SIGNAL, CH_TORQUE})
        app.processEvents()
        return
    if mode == "fft":
        _select_combo_by_channel(win.inspector.fft_ctx.combo_sig, CH_SIGNAL)
        app.processEvents()
        win.do_fft()  # FFT renders synchronously
        for _ in range(5):
            app.processEvents()
        return
    if mode == "fft_time":
        _select_combo_by_channel(win.inspector.fft_time_ctx.combo_sig, CH_SIGNAL)
        app.processEvents()
        if not _wait_for_analysis(
                lambda: win.do_fft_time(force=True), "fft_time", win):
            raise RuntimeError("FFT-vs-Time render did not complete")
        for _ in range(5):
            app.processEvents()
        if not win.chart_stack.page_fft_time.pane_canvas(0).has_result():
            raise RuntimeError("FFT-vs-Time completed without a rendered result")
        return
    if mode == "order":
        ctx = win.inspector.order_ctx
        _select_combo_by_channel(ctx.combo_sig, CH_SIGNAL)
        _select_combo_by_channel(ctx.combo_rpm, CH_RPM)
        ctx.set_fs(8000.0)
        ctx.apply_params({"max_order": 6, "order_res": 0.05, "time_res": 0.05,
                          "nfft": 4096, "amplitude_mode": "Amplitude",
                          "x_auto": True, "y_auto": True, "z_auto": True})
        app.processEvents()
        if not _wait_for_analysis(win.do_order_time, "order", win):
            raise RuntimeError("Order render did not complete")
        for _ in range(5):
            app.processEvents()
        if not win.chart_stack.page_order.pane_canvas(0).has_result():
            raise RuntimeError("Order completed without a rendered result")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default=None,
                        help="QT_QPA_PLATFORM override (e.g. offscreen)")
    parser.add_argument("--only", choices=PANEL_MODES + EXTRA_SHOTS, default=None)
    parser.add_argument("--promote", action="store_true",
                        help="copy staging PNGs over help/assets after review")
    args = parser.parse_args()

    if args.platform:
        os.environ["QT_QPA_PLATFORM"] = args.platform
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui import MainWindow
    from mf4_analyzer.ui_kit import (setup_chinese_font, load_stylesheet,
                                     install_glass_tooltips)

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)
    install_glass_tooltips(app)

    settings_tmp = tempfile.TemporaryDirectory(prefix="tracelab-help-qsettings-")
    _install_isolated_qsettings(Path(settings_tmp.name))

    win = MainWindow()
    win.resize(WIN_W, WIN_H)
    win.show()
    app.processEvents()

    if args.only == "imports":
        _drive_imports(win, app)
        modes = EXTRA_SHOTS
    else:
        win.load_file(str(build_synthetic_csv()))
        app.processEvents()
        modes = (args.only,) if args.only else PANEL_MODES
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for mode in modes:
        if mode in PANEL_MODES:
            _drive_mode(win, app, mode)
        pix = win.grab()
        if GRAB_SCALE != 1:
            pix = pix.scaled(WIN_W * GRAB_SCALE, WIN_H * GRAB_SCALE)
        out = STAGING_DIR / (PANEL_FILES | EXTRA_FILES)[mode]
        if pix.isNull() or pix.width() < 10:
            print(f"FAIL: degenerate pixmap for {mode}", file=sys.stderr)
            return 2
        pix.save(str(out))
        saved.append(out)
        print(f"saved staging: {out} ({pix.width()}x{pix.height()})")

    if args.promote:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for src in saved:
            dst = ASSETS_DIR / src.name
            shutil.copy2(src, dst)
            print(f"promoted: {dst}")

    win.close()
    app.processEvents()
    settings_tmp.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
