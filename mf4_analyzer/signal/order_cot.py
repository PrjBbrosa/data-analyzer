"""Computed Order Tracking (COT) — angle-domain order analysis.

Pipeline:
    1. abs_rpm = |RPM(t)|; omega(t) = abs_rpm * 2*pi / 60      (rad/s)
    2. theta(t) = integral of omega(t) dt                      (cumulative angle, rad)
    3. resample s(t) onto uniform-d_theta grid s(theta)        (np.interp)
    4. windowed FFT of s(theta) per-frame -> orders direct
       (bin k -> k * samples_per_rev / nfft)

帧布局（ArtemiS Step Size 语义）：
    分析支撑点是**时间轴上的等距网格**（绝对时间的 time_res 整数倍），DFT 窗
    对称地围在每个支撑点两侧。窗放不下的头尾是真实物理死区，不补零硬凑。
    ——对齐 HEAD acoustics ArtemiS SUITE《Order analysis in ArtemiS SUITE》
    (Application Note 08/16) 里 "Order Spectrum vs. Time" 的 Step Size 定义。

Edge cases:
    - RPM=0 segments collapse theta -> degenerate interp. We zero out frames
      whose mean |RPM| < min_rpm_floor.
    - Forward/reverse rotation aliased onto same orders by |RPM|.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .fft import get_analysis_window
from .weighting import _validate_weighting, a_weighting_gain_linear


@dataclass(frozen=True)
class COTParams:
    samples_per_rev: int = 256
    nfft: int = 1024
    window: str = 'hanning'
    max_order: float = 20.0
    order_res: float = 0.05
    # 支撑点步长（秒），ArtemiS 的 Step Size 语义：分析点落在绝对时间的
    # time_res 整数倍上，不是 FFT 帧推进的副产品。
    time_res: float = 0.05
    # Source sample rate carried through for preset/result/cache identity.  The
    # COT math below works on the provided time vector and angle-domain grid, so
    # ``compute`` intentionally does not read fs directly.
    fs: float = 0.0
    min_rpm_floor: float = 10.0  # frames whose mean |rpm| below this are zeroed
    weighting: str = 'None'

    def __post_init__(self):
        if self.samples_per_rev <= 0:
            raise ValueError("samples_per_rev must be > 0")
        if self.nfft <= 0:
            raise ValueError("nfft must be > 0")
        if self.max_order <= 0:
            raise ValueError("max_order must be > 0")
        if self.order_res <= 0:
            raise ValueError("order_res must be > 0")
        _validate_weighting(self.weighting)


@dataclass
class COTResult:
    times: np.ndarray             # frame center times in seconds
    orders: np.ndarray            # order axis (interpolated to user grid)
    amplitude: np.ndarray         # shape (frames, orders)
    params: COTParams
    metadata: dict = field(default_factory=dict)


class COTOrderAnalyzer:
    @staticmethod
    def _validate(sig, rpm, t):
        sig = np.asarray(sig, dtype=float)
        rpm = np.asarray(rpm, dtype=float)
        t = np.asarray(t, dtype=float)
        if sig.ndim != 1 or rpm.ndim != 1 or t.ndim != 1:
            raise ValueError("sig, rpm, t must be 1-D")
        if not (len(sig) == len(rpm) == len(t)):
            raise ValueError(
                f"length mismatch: sig={len(sig)} rpm={len(rpm)} t={len(t)}"
            )
        if len(sig) < 16:
            raise ValueError("signal too short")
        if np.any(np.diff(t) <= 0):
            raise ValueError("time vector must be strictly monotonically increasing")
        return sig, rpm, t

    @staticmethod
    def compute(sig, rpm, t, params: COTParams,
                progress_callback=None, cancel_token=None) -> COTResult:
        sig, rpm, t = COTOrderAnalyzer._validate(sig, rpm, t)
        weighting = _validate_weighting(params.weighting)

        abs_rpm = np.abs(rpm)
        omega = abs_rpm * 2.0 * np.pi / 60.0           # rad/s
        # cumulative angle via trapezoidal integration
        dt = np.diff(t)
        # midpoint-trapezoid: theta_i = theta_{i-1} + (omega_{i-1} + omega_i)/2 * dt_{i-1}
        theta = np.zeros_like(t)
        theta[1:] = np.cumsum(0.5 * (omega[:-1] + omega[1:]) * dt)
        theta_max = float(theta[-1])

        if theta_max <= 0:
            raise ValueError(
                "RPM is zero throughout the signal — COT cannot resolve orders"
            )

        # uniform angle grid
        dtheta = 2.0 * np.pi / params.samples_per_rev
        theta_uniform = np.arange(0.0, theta_max, dtheta)
        if len(theta_uniform) < params.nfft:
            raise ValueError(
                f"signal covers only {theta_max / (2*np.pi):.2f} revolutions; "
                f"need at least {params.nfft / params.samples_per_rev:.2f} "
                f"for nfft={params.nfft}"
            )

        # angle-domain signal
        s_theta = np.interp(theta_uniform, theta, sig)

        # angle-domain time map: t_uniform = interp(theta_uniform, theta, t)
        t_uniform = np.interp(theta_uniform, theta, t)
        rpm_uniform = np.interp(theta_uniform, theta, abs_rpm)

        # ------------------------------------------------------------------
        # 帧布局：时间轴上的等距支撑网格（不是角度域等跳）
        # ------------------------------------------------------------------
        # 旧实现在角度域按固定 hop 推进，帧中心时间只是副产品——RPM 一变，
        # 帧距就在 0.058~0.636 s 之间乱抖，用户请求「t=10 s 切片」会被吸到
        # 10.028 s，而 metadata 又把覆盖区间报成整段录制，x 轴系统性撒谎最
        # 多 ±6 s。现在按 ArtemiS 的 Step Size 语义反过来做：先在时间轴上
        # 定死等距支撑点，再去角度域找对称围住它的窗。
        nfft = int(params.nfft)
        n_angle = len(t_uniform)
        half = nfft // 2

        # 支撑点步长。非有限或非正数（老预设 / 手搓 recipe 传 0、NaN）时回退
        # 到 COTParams 的默认 0.05 s，而不是让 arange 炸掉。
        step = float(params.time_res)
        if not np.isfinite(step) or step <= 0.0:
            step = 0.05

        # 能把整窗对称放下的时间范围：窗中心最早只能到第 half 个角度样本，
        # 最晚只能到最后一个合法起点 (n_angle - nfft) 再加 half。头尾放不下
        # 整窗的部分是真实死区，不补零硬凑。
        lo_t = float(t_uniform[half])
        hi_t = float(t_uniform[n_angle - nfft + half])

        # 防御：网格再密也不可能比角度域采样更细——相邻支撑点会落到同一个
        # 角度样本，除了吃内存不产生任何新信息。把 step 抬到「支撑点数不超过
        # 可能的帧起点数」这条线上，正好等于旧实现 hop 被夹到 1 时的帧数上限。
        # 正常参数下这个下限是微秒量级，完全不会生效（time_res=1e-9 这种
        # 极端入参才会）。
        max_points = max(n_angle - nfft + 1, 1)
        span_t = hi_t - lo_t
        if span_t > 0.0:
            step = max(step, span_t / max_points)

        # 支撑点锚在**绝对时间**的整数倍上（k*step），不是相对 t0 ——用户请求
        # 「5 s」时心智模型就是绝对整点，吸附/切片都按这个来。
        k_lo = int(np.ceil(lo_t / step))
        k_hi = int(np.floor(hi_t / step))
        if k_hi >= k_lo:
            grid = np.arange(k_lo, k_hi + 1, dtype=float) * step
            # 支撑点 → 角度域样本下标：t_uniform 单调，直接反查再取整。
            # clip 只防浮点取整越界，不用来做任何语义上的夹取。
            center_idx = np.rint(
                np.interp(grid, t_uniform, np.arange(n_angle, dtype=float))
            ).astype(int)
            starts = np.clip(center_idx - half, 0, n_angle - nfft)
            # 上报**网格整点值**而不是最近样本的真实时刻：实测二者最大差
            # 14.66 ms，相对 32 转（≈11 s）的窗完全可忽略，而「分析点即网格点」
            # 才是用户和切片规划共同依赖的语义。
            times_arr = grid.astype(float)
        else:
            # 信号只够放一两个窗、没有任何整点落进 [lo_t, hi_t]：兜底居中放
            # 一帧，此时时间报该帧的真实中心（没有网格可对齐）。
            start0 = (n_angle - nfft) // 2
            starts = np.array([start0], dtype=int)
            times_arr = np.array([float(t_uniform[start0 + half])], dtype=float)
            # 兜底帧的覆盖宽度取「请求步长」和「这一帧真实窗长」里更小的那个：
            # time_res=100 s 打在 10 s 文件上时，±step/2 会把 x 轴撑到几百秒，
            # 又是一次 x 轴撒谎。单帧诚实的覆盖就是它自己那个窗。
            window_span = float(t_uniform[start0 + nfft - 1] - t_uniform[start0])
            if window_span > 0.0:
                step = min(step, window_span)

        n_frames = len(starts)
        if n_frames == 0:
            raise ValueError("not enough angle-domain samples for one frame")

        w = get_analysis_window(params.window, nfft)
        w_sum = float(np.sum(w))

        # raw bin-orders: bin k -> k * samples_per_rev / nfft
        raw_orders = np.arange(nfft // 2 + 1) * (params.samples_per_rev / nfft)

        # user-facing order grid (dropping below first raw order, capped at max_order)
        out_orders = np.arange(params.order_res,
                               params.max_order + params.order_res * 0.5,
                               params.order_res)
        amp_matrix = np.zeros((n_frames, len(out_orders)), dtype=float)

        def _check_cancel():
            # Mirrors spectrogram.py / order.py: poll once per frame (NOT
            # inside the FFT hot path); '... computation cancelled' is the
            # message family the UI failure handlers recognise.
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")

        for idx, start in enumerate(starts):
            _check_cancel()
            frame = s_theta[start:start + nfft]
            mean_rpm_frame = float(np.mean(rpm_uniform[start:start + nfft]))

            if mean_rpm_frame < params.min_rpm_floor:
                # zero-out low-RPM frames; angle integration unreliable
                continue

            spec = np.fft.rfft((frame - frame.mean()) * w)
            amp_raw = np.abs(spec) / w_sum * 2.0
            amp_raw[0] /= 2.0
            if (nfft % 2) == 0:
                amp_raw[-1] /= 2.0

            # interpolate raw_orders -> out_orders
            amp_matrix[idx, :] = np.interp(out_orders, raw_orders, amp_raw,
                                           left=0.0, right=0.0)
            if weighting == 'A' and mean_rpm_frame > 0.0:
                freqs_hz = out_orders * mean_rpm_frame / 60.0
                amp_matrix[idx, :] *= a_weighting_gain_linear(freqs_hz)

            if progress_callback is not None:
                progress_callback(idx + 1, n_frames)

        if progress_callback is not None:
            progress_callback(n_frames, n_frames)

        return COTResult(
            times=times_arr,
            orders=out_orders,
            amplitude=amp_matrix,
            params=params,
            metadata={
                'frames': n_frames,
                # 实际生效的支撑点步长（可能被上面的下限抬过）
                'time_step_s': float(step),
                'first_center': float(times_arr[0]),
                'last_center': float(times_arr[-1]),
                'samples_per_rev': params.samples_per_rev,
                'theta_max_rev': theta_max / (2 * np.pi),
                'angle_samples': len(s_theta),
                # 覆盖区间 = 支撑点各自的半格，即渲染层每列像素真正代表的时间
                # 范围。以前报的是整段窗覆盖（首帧左沿→末帧右沿），x 轴会把
                # 帧均匀铺满一个比实际分析区间宽得多的范围。
                'coverage_start': float(times_arr[0]) - float(step) / 2.0,
                'coverage_end': float(times_arr[-1]) + float(step) / 2.0,
                'time_start': float(t[0]),
                'time_end': float(t[-1]),
                'window_samples': nfft,
            },
        )
