#!/usr/bin/env python3
"""真机计时：分析画布（PgLineCanvas 谱行 / PgFrfCanvas）AA 帧成本 vs ink。

同样 4095 个谱线绘点，只改「竖直墨迹量」（噪声底占纵轴比例），量 AA 帧；
用 render_profile.envelope_ink_dev_px 对谱行算 ink，与时域 AA 带
（_INK_AA_ON/_INK_AA_OFF）并排——看 ink 是否能作为分析画布的成本预测量，
以及时域带是否可以直接搬用（结论：单调可预测、斜率更陡、需自标定）。

FRF：干净 / 噪声相位相干 各档 bins 数，AA 帧 vs 非 AA 帧。

真机 Cocoa 跑；offscreen 数字无效。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _warm(app, widget):
    widget.show(); widget.raise_(); widget.activateWindow()
    for _ in range(80):
        app.processEvents(); time.sleep(0.01)


def _frame_ms(canvas, n=3):
    import numpy as np
    ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        canvas._glw.scene().update(); canvas._glw.viewport().repaint()
        ms.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(ms))


def spectrum_cases(app):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
    from mf4_analyzer.render_profile import envelope_ink_dev_px
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_ON, _INK_AA_OFF

    c = PgLineCanvas(); c.resize(1400, 900); _warm(app, c)
    rng = np.random.default_rng(7)
    freq = np.linspace(0, 2000, 65536); t = np.linspace(0, 10, 40000)
    noise = np.abs(rng.standard_normal(65536))
    peak = 200.0 * np.exp(-((freq - 300.0) ** 2) / 40.0)
    dpr = c._glw.devicePixelRatioF()
    print(f"== PgLineCanvas 谱行：同 4095 绘点，只改竖直墨迹 (band ON={_INK_AA_ON/1000:.0f}k OFF={_INK_AA_OFF/1000:.0f}k) ==")

    def case(msg, gain, ncurves=3):
        entries = [{
            "label": f"ch{i}", "color": "#1769e0", "freq": freq,
            "amp": noise * (1 + 0.1 * i) + peak * gain,
            "time": t, "signal": 40 * np.sin(2 * np.pi * (3 + i) * t),
        } for i in range(ncurves)]
        c._aa_on = True
        c.plot_spectra(entries, xlim=(0, 2000), amp_label="A", title="t")
        app.processEvents()
        ylo, yhi = c._plot_amp.vb.viewRange()[1]; yspan = abs(yhi - ylo)
        h = c._plot_amp.vb.sceneBoundingRect().height()
        ink = sum(envelope_ink_dev_px(cv.getData()[1], y_span=yspan,
                                      row_height_px=h, dpr=dpr)
                  for cv in c._amp_curves)
        pts = sum(len(cv.getData()[0]) for cv in c._amp_curves)
        aa = all(bool(cv.opts.get("antialias")) for cv in c._amp_curves)
        ms = _frame_ms(c)
        verdict = ("ALLOW" if ink <= _INK_AA_ON else
                   ("BLOCK" if ink > _INK_AA_OFF else "band"))
        print(f"  {msg:<22} 曲线={ncurves} 绘点={pts:5d} 点数闸门放行AA={aa!s:<5} "
              f"yspan={yspan:8.2f} ink={ink/1000:8.1f}k 时域带={verdict:<5} "
              f"帧中位={ms:8.1f} ms")

    case("纯噪声底", 0.0)
    case("峰/底=10", 0.05)
    case("峰/底=40", 0.2)
    case("峰/底=200", 1.0)
    case("峰/底=200 · 1 条", 1.0, 1)
    case("纯噪声底 · 1 条", 0.0, 1)
    case("纯噪声底 · 6 条", 0.0, 6)
    c._aa_on = False
    entries = [{"label": "x", "color": "#1769e0", "freq": freq, "amp": noise,
                "time": t, "signal": np.sin(t)} for _ in range(3)]
    c.plot_spectra(entries, xlim=(0, 2000), amp_label="A", title="t")
    app.processEvents()
    print(f"  {'AA 关 · 纯噪声底 (对照)':<22} 帧中位={_frame_ms(c):8.1f} ms")
    c.close(); app.processEvents()


def frf_cases(app):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    c = PgFrfCanvas(); c.resize(1400, 900); _warm(app, c)
    rng = np.random.default_rng(3)

    def res(nbins, noisy):
        f = np.linspace(0, 1000, nbins)
        H = 1.0 / (1 - (f / 120) ** 2 + 1j * 0.05 * (f / 120))
        if noisy:
            H = H * (1 + 0.6 * rng.standard_normal(nbins)) \
                * np.exp(1j * rng.standard_normal(nbins) * 1.5)
        coh = np.clip(0.9 - 0.5 * rng.random(nbins) * noisy, 0, 1)
        return SimpleNamespace(
            frequencies=f, transfer=H.astype(complex), coherence=coh,
            effective=SimpleNamespace(fs=2000.0, df=f[1] - f[0], segments=8),
            warnings=(),
        )

    print("== PgFrfCanvas：AA 帧 vs 非 AA 帧 ==")
    for nbins, noisy, label in ((2049, 0, "2k bins 干净"),
                                (2049, 1, "2k bins 噪声相位/相干"),
                                (8193, 1, "8k bins 噪声"),
                                (32769, 1, "32k bins 噪声")):
        c.set_result(res(nbins, noisy), {"frequency_scale": "linear"}, {})
        app.processEvents()
        aa_ms = _frame_ms(c)
        c.disable_interactive_quality(); app.processEvents()
        off_ms = _frame_ms(c)
        c._enable_idle_quality()
        print(f"  {label:<20} AA帧中位={aa_ms:8.1f} ms   非AA帧={off_ms:7.1f} ms")
    c.close(); app.processEvents()


def main():
    app = _qapp()
    print(f"platform={app.platformName()}")
    spectrum_cases(app)
    frf_cases(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
