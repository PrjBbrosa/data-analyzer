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

    @staticmethod
    def add(a, b):
        return np.asarray(a, dtype=float) + np.asarray(b, dtype=float)

    @staticmethod
    def sub(a, b):
        return np.asarray(a, dtype=float) - np.asarray(b, dtype=float)

    @staticmethod
    def mul(a, b):
        return np.asarray(a, dtype=float) * np.asarray(b, dtype=float)

    @staticmethod
    def div(a, b):
        left = np.asarray(a, dtype=float)
        right = np.asarray(b, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(right != 0, left / right, 0.0)

    @staticmethod
    def maximum(a, b):
        return np.maximum(np.asarray(a, dtype=float), np.asarray(b, dtype=float))

    @staticmethod
    def minimum(a, b):
        return np.minimum(np.asarray(a, dtype=float), np.asarray(b, dtype=float))
