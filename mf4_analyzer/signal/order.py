"""OrderAnalyzer: order tracking against a tach/RPM reference."""
import numpy as np


class OrderAnalyzer:
    @staticmethod
    def compute_order_spectrum_time_based(sig, rpm, t, fs, max_ord=20, order_res=0.1, time_res=0.05, nfft=1024,
                                          progress_callback=None):
        """时间-阶次谱，优化版本"""
        orders = np.arange(order_res, max_ord + order_res, order_res)
        seg_sz = nfft
        hop = max(int(fs * time_res), 1)
        n_segments = max((len(sig) - seg_sz) // hop, 1)

        # 预计算窗函数
        window = np.hanning(seg_sz)

        tb, om = [], []
        for idx, i in enumerate(range(0, len(sig) - seg_sz, hop)):
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, n_segments)

            seg = sig[i:i + seg_sz]
            seg_rpm = np.mean(rpm[i:i + seg_sz])
            tb.append(t[i + seg_sz // 2] if t is not None else i / fs)

            # FFT
            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            # 提取各阶次能量
            oa = np.zeros(len(orders))
            freq_per_order = abs(seg_rpm) / 60.0
            if freq_per_order > 0:
                for j, o in enumerate(orders):
                    of = o * freq_per_order
                    if 0 < of < fs / 2:
                        bw = max(order_res * freq_per_order * 0.5, freq[1] - freq[0] if len(freq) > 1 else 1)
                        m = (freq >= of - bw) & (freq <= of + bw)
                        if np.any(m):
                            oa[j] = np.sqrt(np.sum(amp[m] ** 2))
            om.append(oa)

        if progress_callback:
            progress_callback(n_segments, n_segments)

        return np.array(tb), orders, np.array(om)

    @staticmethod
    def compute_order_spectrum(sig, rpm, fs, max_ord=20, rpm_res=10, order_res=0.25, nfft=1024, progress_callback=None):
        """转速-阶次谱，优化版本"""
        rpm_bins = np.arange(np.min(rpm), np.max(rpm) + rpm_res, rpm_res)
        orders = np.arange(order_res, max_ord + order_res, order_res)
        om = np.zeros((len(rpm_bins), len(orders)))
        cm = np.zeros_like(om)

        seg_sz = nfft
        hop = seg_sz // 4  # 75%重叠
        window = np.hanning(seg_sz)
        n_segments = max((len(sig) - seg_sz) // hop, 1)

        for idx, i in enumerate(range(0, len(sig) - seg_sz, hop)):
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, n_segments)

            seg = sig[i:i + seg_sz]
            sr = np.mean(rpm[i:i + seg_sz])
            ri = np.argmin(np.abs(rpm_bins - sr))
            if ri >= len(rpm_bins): continue

            # FFT
            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            freq_per_order = abs(sr) / 60.0
            if freq_per_order > 0:
                for j, o in enumerate(orders):
                    of = o * freq_per_order
                    bw = order_res * freq_per_order * 0.5
                    m = (freq >= of - bw) & (freq <= of + bw)
                    if np.any(m):
                        om[ri, j] += np.sqrt(np.mean(amp[m] ** 2))
                        cm[ri, j] += 1

        if progress_callback:
            progress_callback(n_segments, n_segments)

        cm[cm == 0] = 1
        return orders, rpm_bins, om / cm

    @staticmethod
    def extract_order_track(sig, rpm, fs, target, nfft=1024):
        """单阶次跟踪"""
        seg_sz = nfft
        hop = seg_sz // 4
        window = np.hanning(seg_sz)
        rt, oa = [], []

        for i in range(0, len(sig) - seg_sz, hop):
            seg = sig[i:i + seg_sz]
            sr = np.mean(rpm[i:i + seg_sz])

            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            of = target * abs(sr) / 60.0
            bw = 0.25 * abs(sr) / 60.0
            m = (freq >= of - bw) & (freq <= of + bw)
            rt.append(sr)
            oa.append(np.sqrt(np.mean(amp[m] ** 2)) if np.any(m) else 0)

        return np.array(rt), np.array(oa)
