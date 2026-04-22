"""ChannelMath: arithmetic between channels (add/sub/mul/div)."""
import numpy as np


class ChannelMath:
    @staticmethod
    def derivative(t, sig): return np.gradient(sig, t)

    @staticmethod
    def integral(t, sig):
        r = np.zeros_like(sig);
        r[1:] = np.cumsum(0.5 * (sig[1:] + sig[:-1]) * np.diff(t));
        return r

    @staticmethod
    def scale(sig, f): return sig * f

    @staticmethod
    def offset(sig, v): return sig + v

    @staticmethod
    def moving_avg(sig, ws=50): return np.convolve(sig, np.ones(ws) / ws, mode='same')
