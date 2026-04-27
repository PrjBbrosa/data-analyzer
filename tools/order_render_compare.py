"""Order analysis 渲染对比 — 跑真实文件，输出 4 种色阶方案 PNG。

用法: .venv/bin/python tools/order_render_compare.py
输出: tools/_out/order_compare_*.png
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

print("[load] reading MF4 …")
mdf = MDF(MF4)
sig_torque = mdf.get("Rte_TAS_mTorsionBarTorque_xds16")
sig_rpm    = mdf.get("Rte_RPS_nRotorSpeed_xds16")
print(f"  torque: {sig_torque.samples.shape}, rpm: {sig_rpm.samples.shape}")

t       = sig_torque.timestamps
torque  = sig_torque.samples.astype(float)
rpm     = sig_rpm.samples.astype(float)
fs      = 1.0 / np.median(np.diff(t))
print(f"  fs={fs:.3f} Hz, dur={t[-1]-t[0]:.1f} s, |rpm| max={np.max(np.abs(rpm)):.0f}")

# ---- Run analyzer with default params (matches UI) ----
params = OrderAnalysisParams(
    fs=fs, nfft=1024, window='hanning',
    max_order=20.0, order_res=0.1, time_res=0.05,
)
print(f"[compute] order analysis: nfft={params.nfft} max_order={params.max_order} res={params.order_res}")
res = OrderAnalyzer.compute_time_order_result(torque, rpm, t, params)
print(f"  frames={res.amplitude.shape[0]}, orders={res.amplitude.shape[1]}")
print(f"  amplitude min={res.amplitude.min():.4f}, max={res.amplitude.max():.4f}")

# Per-order column means / max for sanity
means = res.amplitude.mean(axis=0)
maxes = res.amplitude.max(axis=0)
top = np.argsort(maxes)[-10:][::-1]
print("  top-10 orders by peak:")
for i in top:
    print(f"    order={res.orders[i]:5.2f}  mean={means[i]:.4f}  max={maxes[i]:.4f}")

# ---- 4 rendering schemes ----
M = res.amplitude.T  # shape (orders, frames) for imshow
extent = [res.times[0], res.times[-1], res.orders[0], res.orders[-1]]

def _render(ax, M, vmin, vmax, title, cmap='turbo', cbar_label='Amplitude'):
    im = ax.imshow(M, origin='lower', aspect='auto', extent=extent,
                   cmap=cmap, interpolation='bilinear',
                   vmin=vmin, vmax=vmax)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Order')
    ax.set_title(title, fontsize=10)
    plt.colorbar(im, ax=ax, label=cbar_label)

# Helper: dB matrix with floor at -dynamic_range
def _to_db(linear, ref=None, floor_db=-50.0):
    if ref is None:
        ref = float(np.nanmax(linear))
    if ref <= 0:
        return np.full_like(linear, floor_db)
    db = 20.0 * np.log10(np.clip(linear, 1e-12, None) / ref)
    return np.clip(db, floor_db, 0.0)

# Helper: drop sub-bin orders (df * 60 / max|rpm|)
def _floor_subbin(matrix, orders, fs, nfft, rpm):
    df = fs / nfft
    rpm_max = float(np.max(np.abs(rpm)))
    if rpm_max <= 0:
        return matrix, orders
    min_order = max(orders[0], df * 60.0 / rpm_max)
    keep = orders >= min_order
    return matrix[keep, :], orders[keep]

M_floored, orders_floored = _floor_subbin(M, res.orders, fs, params.nfft, rpm)
extent_floored = [res.times[0], res.times[-1], orders_floored[0], orders_floored[-1]]

def _save_panel(matrix, ext, vmin, vmax, title, cbar_label, fname, cmap='turbo'):
    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    im = ax.imshow(matrix, origin='lower', aspect='auto', extent=ext,
                   cmap=cmap, interpolation='bilinear', vmin=vmin, vmax=vmax)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Order')
    ax.set_title(title)
    plt.colorbar(im, ax=ax, label=cbar_label)
    plt.tight_layout()
    out_path = os.path.join(OUT, fname)
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f"[saved] {out_path}")

# A. CURRENT: linear, full range, no floor
_save_panel(M, [res.times[0], res.times[-1], res.orders[0], res.orders[-1]],
            float(np.nanmin(M)), float(np.nanmax(M)),
            f"A. CURRENT  (linear, vmax={np.nanmax(M):.2f})  --  pseudo low-order saturates",
            'Amplitude (linear)', "A_current_linear.png")

# B. Floor sub-bin orders + linear
_save_panel(M_floored, extent_floored,
            float(np.nanmin(M_floored)), float(np.nanmax(M_floored)),
            f"B. FLOOR sub-bin (order >= {orders_floored[0]:.2f}) + linear",
            'Amplitude (linear)', "B_floor_linear.png")

# C. dB at 30dB dynamic range
M_db_30 = _to_db(M_floored, floor_db=-30.0)
_save_panel(M_db_30, extent_floored, -30.0, 0.0,
            "C. dB rendering  --  30 dB dynamic range  (RECOMMENDED daily)",
            'Amplitude (dB)', "C_dB_30.png")

# D. dB at 50dB dynamic range
M_db_50 = _to_db(M_floored, floor_db=-50.0)
_save_panel(M_db_50, extent_floored, -50.0, 0.0,
            "D. dB rendering  --  50 dB dynamic range",
            'Amplitude (dB)', "D_dB_50.png")

print("\nAll PNGs in tools/_out/")
