"""Signal subpackage: numeric analysis (FFT, order, spectrogram, channel math)."""
from .adaptive import (
    assess_speed_for_order,
    ceil_pow2,
    energy_band_fmax,
    resolve_nfft,
    resolve_order_nfft,
)
from .fft import FFTAnalyzer
from .order import OrderAnalysisParams, OrderAnalyzer, OrderTimeResult
from .channel_math import ChannelMath
from .spectrogram import SpectrogramAnalyzer, SpectrogramParams, SpectrogramResult

__all__ = [
    'assess_speed_for_order',
    'ceil_pow2',
    'energy_band_fmax',
    'resolve_nfft',
    'resolve_order_nfft',
    'FFTAnalyzer',
    'OrderAnalyzer',
    'OrderAnalysisParams',
    'OrderTimeResult',
    'ChannelMath',
    'SpectrogramAnalyzer',
    'SpectrogramParams',
    'SpectrogramResult',
]
