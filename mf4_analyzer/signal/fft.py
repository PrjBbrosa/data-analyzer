"""FFTAnalyzer: windowed FFT with amplitude normalization."""
import numpy as np


class FFTAnalyzer:
    """Static methods for FFT, PSD, and averaged-FFT (Welch) computations on time-domain signals.

    Provides `compute_fft`, `compute_psd`, `compute_averaged_fft`, and `get_window` for spectral analysis.
    """

    @staticmethod
    def get_window(name, n):
        wins = {
            'hanning': np.hanning, 'hamming': np.hamming, 'blackman': np.blackman,
            'bartlett': np.bartlett, 'kaiser': lambda n: np.kaiser(n, 14),
            'flattop': lambda n: np.ones(n) * 0.21557895 - 0.41663158 * np.cos(
                2 * np.pi * np.arange(n) / (n - 1)) + 0.277263158 * np.cos(
                4 * np.pi * np.arange(n) / (n - 1)) - 0.083578947 * np.cos(
                6 * np.pi * np.arange(n) / (n - 1)) + 0.006947368 * np.cos(8 * np.pi * np.arange(n) / (n - 1))
        }
        return wins.get(name, np.hanning)(n)

    @staticmethod
    def compute_fft(sig, fs, win='hanning', nfft=None):
        n = len(sig)
        if nfft is None or nfft <= 0:
            nfft = n
        w = FFTAnalyzer.get_window(win, n)
        sig = sig - np.mean(sig)
        # 零填充到nfft
        if nfft > n:
            sig_padded = np.zeros(nfft)
            sig_padded[:n] = sig * w
        else:
            sig_padded = sig * w
            nfft = n
        fft_r = np.fft.fft(sig_padded)
        nh = nfft // 2
        freq = np.fft.fftfreq(nfft, 1 / fs)[:nh]
        amp = 2 * np.abs(fft_r[:nh]) / n / np.mean(w)
        return freq, amp

    @staticmethod
    def compute_psd(sig, fs, win='hanning', nfft=None):
        f, a = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
        return f, a ** 2

    @staticmethod
    def compute_averaged_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5):
        """计算平均FFT (Welch方法)"""
        n = len(sig)
        hop = int(nfft * (1 - overlap))
        if hop <= 0: hop = nfft // 2
        n_segments = max((n - nfft) // hop + 1, 1)

        w = FFTAnalyzer.get_window(win, nfft)
        w_sum = np.sum(w)

        freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
        psd_sum = np.zeros(nfft // 2)

        for i in range(n_segments):
            start = i * hop
            end = start + nfft
            if end > n: break
            seg = sig[start:end] - np.mean(sig[start:end])
            fft_r = np.fft.fft(seg * w)
            psd_sum += np.abs(fft_r[:nfft // 2]) ** 2

        psd = psd_sum / n_segments / (w_sum ** 2) * 2
        amp = np.sqrt(psd)
        return freq, amp, psd
