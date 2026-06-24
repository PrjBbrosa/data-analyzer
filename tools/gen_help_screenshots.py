"""Regenerate the four help-guide panel screenshots (time / fft / fft_time /
order) by booting the real MainWindow, loading synthetic data, driving each
mode to a populated state, and grabbing the whole window at 2x.

Outputs to a STAGING dir (output/help-shots/) by default — review the PNGs,
then re-run with --promote to copy them over mf4_analyzer/help/assets/. The
guides' numbered pins are tied to UI element positions, so after promoting
NEW screenshots you must re-check the pin left/top% in each *-guide.html.

Renders against a REAL Qt platform (cocoa on macOS) by default so the panels
look exactly as the user sees them. --platform offscreen is a headless
fallback for layout/draft ONLY (offscreen != real render; do not treat an
offscreen image as visually verified).

Window geometry is FIXED (1280x820) so pin coordinates stay stable across
regenerations; only move pins when a UI control actually relocates.

Usage:
    .venv/bin/python tools/gen_help_screenshots.py                 # all 4 -> staging
    .venv/bin/python tools/gen_help_screenshots.py --only time
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
STAGING_DIR = REPO_ROOT / "output" / "help-shots"
ASSETS_DIR = REPO_ROOT / "mf4_analyzer" / "help" / "assets"
WIN_W, WIN_H = 1280, 820
GRAB_SCALE = 2


def build_synthetic_csv() -> Path:
    """rpm ramp 600->3600 + vib (order1+order2) + a torque channel."""
    fs = 8000.0
    dur = 6.0
    n = int(fs * dur)
    t = np.arange(n, dtype=float) / fs
    rpm = np.linspace(600.0, 3600.0, n)
    revs = np.cumsum(rpm / 60.0) / fs
    phase = 2.0 * np.pi * revs
    rng = np.random.default_rng(7)
    vib = 1.0 * np.sin(phase) + 0.6 * np.sin(2.0 * phase) + 0.05 * rng.standard_normal(n)
    torque = 8.0 + 2.0 * np.sin(2.0 * np.pi * 0.5 * t) + 0.02 * rng.standard_normal(n)
    out = Path(tempfile.gettempdir()) / "_help_shots_synth.csv"
    data = np.column_stack([t, rpm, vib, torque])
    np.savetxt(out, data, delimiter=",", header="time,rpm,vib,torque",
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


def _wait(trigger, finished_attr, failed_attr, win, timeout_ms=60_000) -> bool:
    """Drive a worker-backed compute and block until finished/failed/timeout."""
    from PyQt5.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    done = {"ok": False}
    orig_fin = getattr(win, finished_attr)
    orig_fail = getattr(win, failed_attr)

    def on_fin(result, _o=orig_fin):
        _o(result)
        done["ok"] = True
        loop.quit()

    def on_fail(msg, _o=orig_fail):
        _o(msg)
        loop.quit()

    setattr(win, finished_attr, on_fin)
    setattr(win, failed_attr, on_fail)
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(loop.quit)
    wd.start(timeout_ms)
    trigger()
    loop.exec_()
    wd.stop()
    setattr(win, finished_attr, orig_fin)
    setattr(win, failed_attr, orig_fail)
    return done["ok"]


def _drive_mode(win, app, mode: str) -> None:
    win.toolbar._set_mode(mode)
    app.processEvents()
    if mode == "time":
        _check_channels(win, {"vib", "torque"})
        app.processEvents()
        return
    if mode == "fft":
        _select_combo_by_channel(win.inspector.fft_ctx.combo_sig, "vib")
        app.processEvents()
        win.do_fft()  # FFT renders synchronously
        for _ in range(5):
            app.processEvents()
        return
    if mode == "fft_time":
        _select_combo_by_channel(win.inspector.fft_time_ctx.combo_sig, "vib")
        app.processEvents()
        _wait(lambda: win.do_fft_time(force=True),
              "_on_fft_time_finished", "_on_fft_time_failed", win)
        for _ in range(5):
            app.processEvents()
        return
    if mode == "order":
        ctx = win.inspector.order_ctx
        _select_combo_by_channel(ctx.combo_sig, "vib")
        _select_combo_by_channel(ctx.combo_rpm, "rpm")
        ctx.set_fs(8000.0)
        ctx.apply_params({"max_order": 6, "order_res": 0.05, "time_res": 0.05,
                          "nfft": 4096, "amplitude_mode": "Amplitude",
                          "x_auto": True, "y_auto": True, "z_auto": True})
        app.processEvents()
        _wait(win.do_order_time,
              "_on_order_finished", "_on_order_failed", win)
        for _ in range(5):
            app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default=None,
                        help="QT_QPA_PLATFORM override (e.g. offscreen)")
    parser.add_argument("--only", choices=PANEL_MODES, default=None)
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

    win = MainWindow()
    win.resize(WIN_W, WIN_H)
    win.show()
    app.processEvents()
    win.load_file(str(build_synthetic_csv()))
    app.processEvents()

    modes = (args.only,) if args.only else PANEL_MODES
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for mode in modes:
        _drive_mode(win, app, mode)
        pix = win.grab()
        if GRAB_SCALE != 1:
            pix = pix.scaled(WIN_W * GRAB_SCALE, WIN_H * GRAB_SCALE)
        out = STAGING_DIR / PANEL_FILES[mode]
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
