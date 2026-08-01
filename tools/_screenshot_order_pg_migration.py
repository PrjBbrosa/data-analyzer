"""One-shot real-render screenshot of the Order (time-order) heatmap
after the M5 renderer swap (PlotCanvas -> PgHeatmapCanvas).

Developer-only comparison helper: install matplotlib manually when using this
script. Matplotlib is not a TraceLab product runtime or frozen-build dependency.

Boots the full ``MainWindow``, loads a synthetic CSV (rpm ramp +
vibration with strong 1st/2nd order components), switches to Order mode,
drives the COT compute on its worker QThread, waits for completion, and
grabs ``canvas_order.grab_pixmap(scale=2)`` to disk for the P1 visual
acceptance gate (M6).

Unlike the inspector screenshot tool this runs against a REAL Qt
platform (cocoa on macOS) by default so the heatmap, colorbar and turbo
colormap render exactly as the user sees them. Pass
``--platform offscreen`` only as a headless fallback.

Output (default):
    docs/superpowers/verify/p1-order-pg.png

Usage:
    .venv/bin/python tools/_screenshot_order_pg_migration.py
    # headless fallback:
    .venv/bin/python tools/_screenshot_order_pg_migration.py --platform offscreen
    # parity baseline (mpl worktree) reuses the same CSV/params via --out:
    .venv/bin/python tools/_screenshot_order_pg_migration.py --out /tmp/foo.png
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _build_synthetic_csv() -> Path:
    """rpm ramp 600->3600, vib = 1.0*order1 + 0.6*order2 + noise.

    The instantaneous frequency of order k is ``k * rpm / 60`` (Hz); the
    phase is the running integral of 2*pi*f(t) so the 1st/2nd order
    components trace clean rising diagonals on the time-order map.
    """
    fs = 8000.0
    dur = 6.0
    n = int(fs * dur)
    t = np.arange(n, dtype=float) / fs

    rpm = np.linspace(600.0, 3600.0, n)        # ramp
    rps = rpm / 60.0                            # rev/s
    # cumulative shaft angle (revolutions): integral of rps dt
    revs = np.cumsum(rps) / fs
    phase = 2.0 * np.pi * revs                  # 1 rev = 2*pi rad => order 1
    rng = np.random.default_rng(7)
    vib = (
        1.0 * np.sin(phase)                     # order 1
        + 0.6 * np.sin(2.0 * phase)             # order 2
        + 0.05 * rng.standard_normal(n)         # broadband floor
    )

    out = Path(tempfile.gettempdir()) / "_order_pg_synth.csv"
    header = "time,rpm,vib"
    data = np.column_stack([t, rpm, vib])
    np.savetxt(out, data, delimiter=",", header=header, comments="", fmt="%.6g")
    return out


def _select_combo_by_channel(combo, channel_name: str) -> bool:
    """Pick the combo entry whose (fid, ch) data tuple ends with the
    given channel name. Returns True on success."""
    for i in range(combo.count()):
        data = combo.itemData(i)
        if isinstance(data, tuple) and len(data) == 2 and data[1] == channel_name:
            combo.setCurrentIndex(i)
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs" / "superpowers" / "verify" / "p1-order-pg.png"),
    )
    parser.add_argument("--platform", default=None,
                        help="QT_QPA_PLATFORM override (e.g. offscreen)")
    parser.add_argument("--db", action="store_true",
                        help="render in dB amplitude mode (colorbar gets (dB))")
    parser.add_argument("--zfloor", type=float, default=None)
    parser.add_argument("--zceiling", type=float, default=None)
    args = parser.parse_args()

    if args.platform:
        os.environ["QT_QPA_PLATFORM"] = args.platform

    # High-DPI flags must be set before QApplication (mirror app.main).
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    import matplotlib
    matplotlib.use("Qt5Agg", force=True)

    from PyQt5.QtCore import QEventLoop, QTimer
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui import MainWindow
    from mf4_analyzer.ui_kit import (
        setup_chinese_font,
        load_stylesheet,
        install_glass_tooltips,
    )

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)
    install_glass_tooltips(app)

    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    app.processEvents()

    # ---- load synthetic data ----
    csv_path = _build_synthetic_csv()
    win.load_file(str(csv_path))
    app.processEvents()

    # ---- switch to Order mode (drives toolbar + chart_stack + inspector) ----
    win.toolbar._set_mode("order")
    app.processEvents()

    ctx = win.inspector.order_ctx
    if not _select_combo_by_channel(ctx.combo_sig, "vib"):
        print("FAIL: could not select 'vib' as signal", file=sys.stderr)
        return 2
    if not _select_combo_by_channel(ctx.combo_rpm, "rpm"):
        print("FAIL: could not select 'rpm' as rpm", file=sys.stderr)
        return 2

    # Parameters: keep them coarse enough to compute in a couple seconds
    # but fine enough to show the order tracks.
    ctx.set_fs(8000.0)
    params = {
        "max_order": 6,
        "order_res": 0.05,
        "time_res": 0.05,
        "nfft": 4096,
        "amplitude_mode": "Amplitude dB" if args.db else "Amplitude",
        "x_auto": True,
        "y_auto": True,
        "z_auto": args.zfloor is None,
    }
    if args.zfloor is not None:
        params["z_floor"] = float(args.zfloor)
    if args.zceiling is not None:
        params["z_ceiling"] = float(args.zceiling)
    ctx.apply_params(params)
    app.processEvents()

    # ---- compute on the worker QThread, wait for completion ----
    loop = QEventLoop()
    done = {"ok": False}

    orig_finished = win._on_order_finished
    orig_failed = win._on_order_failed

    def on_finished(result, _orig=orig_finished):
        _orig(result)
        done["ok"] = True
        loop.quit()

    def on_failed(message, _orig=orig_failed):
        _orig(message)
        print(f"FAIL: order compute failed: {message}", file=sys.stderr)
        loop.quit()

    win._on_order_finished = on_finished
    win._on_order_failed = on_failed

    # Safety timeout so a stuck worker doesn't hang CI forever.
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(60_000)

    win.do_order_time()
    loop.exec_()
    watchdog.stop()

    if not done["ok"]:
        print("FAIL: order compute did not finish in time", file=sys.stderr)
        return 3

    # Let the render + colorbar settle.
    for _ in range(5):
        app.processEvents()

    canvas = win.canvas_order
    if not canvas.has_result():
        print("FAIL: canvas_order has no result after compute", file=sys.stderr)
        return 4

    pix = canvas.grab_pixmap(scale=2)
    if pix.isNull() or pix.width() < 10 or pix.height() < 10:
        print(f"FAIL: degenerate pixmap {pix.width()}x{pix.height()}", file=sys.stderr)
        return 5

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))

    print(
        f"saved: {out_path}\n"
        f"  pixmap: {pix.width()}x{pix.height()}\n"
        f"  amplitude_mode: {'dB' if args.db else 'linear'}\n"
        f"  z_auto: {params['z_auto']}\n"
        f"  has_result: {canvas.has_result()}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
