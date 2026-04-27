"""FFT 单帧 vs Welch 多帧平均 — 同一个 nfft，看效果差距。"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asammdf import MDF
from mf4_analyzer.signal.fft import FFTAnalyzer, one_sided_amplitude

MF4 = "/Users/donghang/Downloads/data analyzer/testdoc/T08_YuanDi_FOC_CurrentMode_0-1-2_Ripple.MF4"
OUT = os.path.join(os.path.dirname(__file__), "_out")

mdf = MDF(MF4)
sig = mdf.get("Rte_TAS_mTorsionBarTorque_xds16")
t = sig.timestamps
x = sig.samples.astype(float)
fs = 1.0 / np.median(np.diff(t))
print(f"fs={fs:.2f}Hz  N={len(x)}  dur={t[-1]-t[0]:.1f}s")

NFFTS = [4096, 2048, 1024]
fig, axes = plt.subplots(len(NFFTS), 2, figsize=(16, 4.2 * len(NFFTS)))

for row, nfft in enumerate(NFFTS):
    # 单帧（取信号中段一个完整窗）
    if len(x) >= nfft:
        start = (len(x) - nfft) // 2
        seg = x[start:start + nfft]
        f1, a1 = one_sided_amplitude(seg, fs, win='hanning', nfft=nfft)
    else:
        f1, a1 = one_sided_amplitude(x, fs, win='hanning', nfft=nfft)

    # Welch 平均（87.5% overlap）
    f2, a2, _ = FFTAnalyzer.compute_averaged_fft(x, fs, win='hanning',
                                                  nfft=nfft, overlap=0.875)

    # 转 dB（峰值参考）
    ref = max(a1.max(), a2.max(), 1e-12)
    a1_db = 20 * np.log10(np.clip(a1, 1e-12, None) / ref)
    a2_db = 20 * np.log10(np.clip(a2, 1e-12, None) / ref)

    ax = axes[row, 0]
    ax.plot(f1, a1_db, '#dc2626', lw=0.8)
    ax.set_title(f"nfft={nfft}  ·  单帧 FFT  ·  当前 FFT 视图行为", fontsize=10)
    ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Amplitude (dB rel peak)')
    ax.grid(True, alpha=0.25, ls='--'); ax.set_ylim(-80, 5); ax.set_xlim(0, 50)

    ax = axes[row, 1]
    ax.plot(f2, a2_db, '#15803d', lw=0.8)
    ax.set_title(f"nfft={nfft}  ·  Welch 平均（87.5% overlap）  ·  HEAD 风格",
                 fontsize=10)
    ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Amplitude (dB rel peak)')
    ax.grid(True, alpha=0.25, ls='--'); ax.set_ylim(-80, 5); ax.set_xlim(0, 50)

    print(f"nfft={nfft:5d}  single: peak={a1.max():.4f} std(<-30dB)={a1_db[a1_db<-30].std():.2f}dB"
          f"   welch: peak={a2.max():.4f} std(<-30dB)={a2_db[a2_db<-30].std():.2f}dB")

plt.tight_layout()
out = os.path.join(OUT, "fft_welch_compare.png")
plt.savefig(out, dpi=120, bbox_inches='tight')
print(f"[saved] {out}")
