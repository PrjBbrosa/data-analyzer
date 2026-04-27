"""比较不同 nfft 下 order 2 ridge 的清晰度。

每个 FFT 窗 = nfft / fs 秒。窗内 RPM 变化越大，order ridge 越被涂抹。
"""
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asammdf import MDF
from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams

MF4 = "/Users/donghang/Downloads/data analyzer/testdoc/T08_YuanDi_FOC_CurrentMode_0-1-2_Ripple.MF4"
OUT = os.path.join(os.path.dirname(__file__), "_out")
os.makedirs(OUT, exist_ok=True)

mdf = MDF(MF4)
sig = mdf.get("Rte_TAS_mTorsionBarTorque_xds16")
rpmc = mdf.get("Rte_RPS_nRotorSpeed_xds16")
t = sig.timestamps
torque = sig.samples.astype(float)
rpm = rpmc.samples.astype(float)
fs = 1.0 / np.median(np.diff(t))
print(f"fs={fs:.2f} Hz, dur={t[-1]-t[0]:.1f}s")

NFFTS = [1024, 512, 256, 128]

def _to_db(linear, floor_db=-30.0):
    ref = float(np.nanmax(linear))
    if ref <= 0: return np.full_like(linear, floor_db)
    db = 20.0 * np.log10(np.clip(linear, 1e-12, None) / ref)
    return np.clip(db, floor_db, 0.0)

def _floor_subbin(M, orders, fs, nfft, rpm):
    df = fs / nfft
    rpm_max = float(np.max(np.abs(rpm)))
    if rpm_max <= 0: return M, orders
    min_order = max(orders[0], df * 60.0 / rpm_max)
    keep = orders >= min_order
    return M[keep, :], orders[keep]

fig, axes = plt.subplots(len(NFFTS), 1, figsize=(14, 4 * len(NFFTS)))

for i, nfft in enumerate(NFFTS):
    win_s = nfft / fs
    p = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                            order_res=0.05, time_res=0.05)
    res = OrderAnalyzer.compute_time_order_result(torque, rpm, t, p)
    M = res.amplitude.T
    M, orders = _floor_subbin(M, res.orders, fs, nfft, rpm)
    M_db = _to_db(M, floor_db=-30.0)

    ax = axes[i]
    im = ax.imshow(M_db, origin='lower', aspect='auto',
                   extent=[res.times[0], res.times[-1], orders[0], orders[-1]],
                   cmap='turbo', interpolation='bilinear', vmin=-30, vmax=0)
    ax.axhline(y=2.0, color='white', linestyle='--', linewidth=0.8, alpha=0.6)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Order')
    ax.set_title(f"nfft={nfft}  ·  window = {win_s:.2f} s  ·  "
                 f"frames={M.shape[1]}  ·  white dashed = order 2")
    plt.colorbar(im, ax=ax, label='dB')

    # Order 2 column statistics
    o2_idx = int(np.argmin(np.abs(orders - 2.0)))
    o2_col = M[o2_idx, :]
    print(f"nfft={nfft:5d}  win={win_s:5.2f}s  order2: "
          f"mean={o2_col.mean():.4f}  max={o2_col.max():.4f}  "
          f"rms={np.sqrt(np.mean(o2_col**2)):.4f}")

plt.tight_layout()
out = os.path.join(OUT, "nfft_compare.png")
plt.savefig(out, dpi=120, bbox_inches='tight')
print(f"\n[saved] {out}")
