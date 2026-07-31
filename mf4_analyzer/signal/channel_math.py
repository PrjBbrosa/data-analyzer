"""ChannelMath: arithmetic between channels (add/sub/mul/div)."""
import numpy as np


class ChannelMath:
    @staticmethod
    def derivative(t, sig):
        sig = np.asarray(sig, dtype=float)
        if sig.size < 2:
            raise ValueError("derivative requires at least two samples")
        return np.gradient(sig, np.asarray(t, dtype=float))

    @staticmethod
    def integral(t, sig):
        sig = np.asarray(sig, dtype=float)
        r = np.zeros(sig.shape, dtype=float)
        if sig.size < 2:
            return r
        t = np.asarray(t, dtype=float)
        r[1:] = np.cumsum(0.5 * (sig[1:] + sig[:-1]) * np.diff(t))
        return r

    @staticmethod
    def scale(sig, f): return sig * f

    @staticmethod
    def offset(sig, v): return sig + v

    @staticmethod
    def moving_avg(sig, ws=50):
        sig = np.asarray(sig, dtype=float)
        if sig.size == 0:
            return sig.copy()
        ws = max(1, int(ws))
        if ws >= sig.size:
            # A full/oversized smoothing request means one whole-signal mean.
            # ``convolve(..., mode='same')`` would zero-pad and taper the edges.
            return np.full(sig.shape, sig.mean(), dtype=float)
        return np.convolve(sig, np.ones(ws) / ws, mode='same')
