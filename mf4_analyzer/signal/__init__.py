"""Signal subpackage: numeric analysis (FFT, order, spectrogram, channel math)."""
from .adaptive import (
    assess_speed_for_order,
    ceil_pow2,
    energy_band_fmax,
    order_angle_sample_count,
    resolve_nfft,
    resolve_order_nfft,
    revolutions_from_rpm,
)
from .fft import FFTAnalyzer
from .frf import (
    FrfEffectiveFacts,
    FrfParams,
    FrfResult,
    compute_frf,
    get_frf_window,
    magnitude_db,
    magnitude_linear,
    phase_unwrapped_deg,
    phase_wrapped_deg,
)
from .order import OrderAnalysisParams, OrderAnalyzer, OrderTimeResult
from .channel_math import ChannelMath
from .expression import ExpressionError, evaluate as evaluate_expression
from .expression import referenced_names as expression_names
from .spectrogram import SpectrogramAnalyzer, SpectrogramParams, SpectrogramResult

__all__ = [
    'assess_speed_for_order',
    'ceil_pow2',
    'energy_band_fmax',
    'order_angle_sample_count',
    'resolve_nfft',
    'resolve_order_nfft',
    'revolutions_from_rpm',
    'FFTAnalyzer',
    'FrfEffectiveFacts',
    'FrfParams',
    'FrfResult',
    'compute_frf',
    'get_frf_window',
    'magnitude_db',
    'magnitude_linear',
    'phase_unwrapped_deg',
    'phase_wrapped_deg',
    'OrderAnalyzer',
    'OrderAnalysisParams',
    'OrderTimeResult',
    'ChannelMath',
    'ExpressionError',
    'evaluate_expression',
    'expression_names',
    'SpectrogramAnalyzer',
    'SpectrogramParams',
    'SpectrogramResult',
]
