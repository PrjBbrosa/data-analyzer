"""COT 帧布局守卫：分析支撑点是时间轴上的等距网格，不是角度域等跳的副产品。

背景：旧实现 `hop_angle = round(time_res / dt_angle)` 在**角度域**等跳，帧中心
时间只是副产品。实测 24 kHz / 49.5 s 的真实文件上得到 380 帧、首帧 5.865 s、
帧距在 0.058~0.636 s 之间抖，用户请求「t=10 s 切片」被吸到 10.028 s、请求 2 和 4
双双夹到 5.865 s 合并成一条，而 metadata 又把覆盖区间报成 0→49.49 s，渲染层把
380 列均匀铺满整段录制，x 轴系统性撒谎最多 ±6 s。

现在按 HEAD acoustics ArtemiS SUITE 的 Step Size 语义：支撑点是用户在时间轴上
指定的等距网格（绝对时间的 time_res 整数倍），DFT 窗对称围在每个支撑点两侧，
头尾放不下整窗的部分是真实死区。这些用例守住上述每一条。

全部走合成信号——真实大文件的等价性验证是一次性的，不进套件。
"""
import numpy as np
import pytest

from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def _synth(fs=1000.0, dur=10.0, rpm_const=600.0, order=2.0, amp=1.0, t0=0.0):
    """恒定转速 + 一根纯定阶正弦。t0 让时基不从 0 开始，用来验「绝对整点」。"""
    t = t0 + np.arange(int(fs * dur)) / fs
    rpm = np.full_like(t, float(rpm_const))
    f_order = order * rpm_const / 60.0
    sig = amp * np.sin(2 * np.pi * f_order * (t - t0))
    return t, sig, rpm


def _sweep(fs=1000.0, dur=12.0, rpm_lo=300.0, rpm_hi=1200.0):
    """扫速信号：角度域采样密度沿时间变化，最能戳穿「角度域等跳」。"""
    t = np.arange(int(fs * dur)) / fs
    rpm = rpm_lo + (rpm_hi - rpm_lo) * (t / dur)
    omega = 2 * np.pi * rpm / 60.0
    phase2 = 2 * np.concatenate([[0.0], np.cumsum(omega[:-1]) * (t[1] - t[0])])
    return t, np.sin(phase2), rpm


def _params(**kw):
    base = dict(samples_per_rev=256, nfft=512, max_order=10.0,
                order_res=0.1, time_res=0.1)
    base.update(kw)
    return COTParams(**base)


# ---------------------------------------------------------------------------
# 网格本身
# ---------------------------------------------------------------------------

def test_frame_centers_land_on_absolute_multiples_of_time_res():
    """每个帧中心都是 time_res 的整数倍——锚在绝对时间上，不是相对 t0。"""
    t, sig, rpm = _sweep()
    step = 0.1
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=step))

    ratio = res.times / step
    np.testing.assert_allclose(ratio, np.rint(ratio), atol=1e-9)


def test_grid_is_anchored_to_absolute_time_not_to_t0():
    """时基从 3.317 s 起步时，支撑点仍落在绝对整点上（3.4/3.5/…），
    不是 3.317+k*step。"""
    t, sig, rpm = _synth(dur=8.0, t0=3.317)
    step = 0.1
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=step))

    ratio = res.times / step
    np.testing.assert_allclose(ratio, np.rint(ratio), atol=1e-9)
    # 真的偏移过：首帧不等于 t0 + 半窗那种「相对锚」的结果
    assert res.times[0] > float(t[0])


def test_frame_spacing_is_exactly_time_res():
    """帧距恒等于 time_res——旧实现在扫速下抖到 0.058~0.636 s。"""
    t, sig, rpm = _sweep()
    step = 0.2
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=step))

    assert res.times.size > 5
    spacing = np.diff(res.times)
    np.testing.assert_allclose(spacing, step, rtol=0, atol=1e-9)


@pytest.mark.parametrize("step", [0.05, 0.1, 0.25, 0.5])
def test_first_and_last_support_points_keep_the_window_inside_the_record(step):
    """首帧 ≥ lo_t、末帧 ≤ hi_t：窗必须能对称放下，不补零硬凑。"""
    t, sig, rpm = _sweep()
    nfft = 512
    params = _params(nfft=nfft, time_res=step)
    res = COTOrderAnalyzer.compute(sig, rpm, t, params)

    # 复算可放窗区间（与产品同一定义，但独立算一遍）
    omega = np.abs(rpm) * 2.0 * np.pi / 60.0
    theta = np.concatenate(
        [[0.0], np.cumsum(0.5 * (omega[:-1] + omega[1:]) * np.diff(t))]
    )
    dtheta = 2.0 * np.pi / params.samples_per_rev
    theta_u = np.arange(0.0, float(theta[-1]), dtheta)
    t_u = np.interp(theta_u, theta, t)
    half = nfft // 2
    lo_t = float(t_u[half])
    hi_t = float(t_u[len(t_u) - nfft + half])

    assert res.times[0] >= lo_t - 1e-12
    assert res.times[-1] <= hi_t + 1e-12
    # 而且贴得紧：网格外面再没有能放下窗的整点了
    assert res.times[0] - step < lo_t
    assert res.times[-1] + step > hi_t


def test_smaller_step_is_a_superset_grid():
    """0.1 s 网格的每个点都出现在 0.05 s 网格里——等距网格的必然结果。"""
    t, sig, rpm = _sweep()
    coarse = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=0.1))
    fine = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=0.05))

    for value in coarse.times:
        assert np.min(np.abs(fine.times - value)) < 1e-9


# ---------------------------------------------------------------------------
# 边界与兜底
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0.0, -0.2, float('nan'), float('inf')])
def test_non_positive_or_non_finite_time_res_falls_back_to_default_step(bad):
    """time_res 非有限/非正 → 回退 0.05 s，而不是炸掉或产生 0 帧。"""
    t, sig, rpm = _synth()
    # COTParams 不校验 time_res（历史行为），所以这些值真的会走到 compute 里。
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=bad))

    assert res.metadata['time_step_s'] == pytest.approx(0.05)
    spacing = np.diff(res.times)
    np.testing.assert_allclose(spacing, 0.05, rtol=0, atol=1e-9)


def test_empty_grid_falls_back_to_one_centred_frame():
    """没有整点落进可放窗区间 → 单帧兜底，时间报该帧真实中心。"""
    t, sig, rpm = _synth(dur=6.0)
    nfft = 512
    # 步长比整条可放窗区间还长，且 0 不落在区间里 → 网格必空
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(nfft=nfft, time_res=1e6))

    assert res.metadata['frames'] == 1
    assert res.times.size == 1
    # 真实中心，不是网格整点
    assert res.times[0] % 1e6 != 0.0
    assert float(t[0]) < res.times[0] < float(t[-1])
    assert np.all(np.isfinite(res.amplitude))


def test_one_window_short_signal_still_raises_when_no_window_fits():
    """连一个窗都放不下仍然是 ValueError（原有契约没被兜底吃掉）。"""
    t, sig, rpm = _synth(dur=0.15)   # 600 rpm → 1.5 转，放不下 nfft=512 的 2 转
    with pytest.raises(ValueError, match="revolutions"):
        COTOrderAnalyzer.compute(sig, rpm, t, _params(nfft=512))


def test_low_rpm_duplicate_frames_are_kept_not_deduplicated():
    """低转速段相邻网格点吸到同一角度样本时，重复帧**保留**。

    窗几乎没动、内容相同是诚实的；去重反而会在时间轴上戳出一个洞，
    破坏「等距网格」这条唯一契约。
    """
    fs = 1000.0
    dur = 20.0
    t = np.arange(int(fs * dur)) / fs
    # 中段掉到 20 rpm（仍高于 min_rpm_floor，帧不会被清零）。
    # samples_per_rev=32 时角度域采样间隔 60/(32*20)=93.75 ms > 网格步长 50 ms，
    # 相邻支撑点必然吸到同一个角度样本。
    rpm = np.where((t > 7.0) & (t < 13.0), 20.0, 900.0)
    omega = 2 * np.pi * rpm / 60.0
    phase = 2 * np.concatenate([[0.0], np.cumsum(omega[:-1]) / fs])
    sig = np.sin(phase)

    step = 0.05
    res = COTOrderAnalyzer.compute(
        sig, rpm, t,
        _params(samples_per_rev=32, nfft=64, time_res=step, min_rpm_floor=10.0),
    )

    spacing = np.diff(res.times)
    np.testing.assert_allclose(spacing, step, rtol=0, atol=1e-9)
    # 慢段确实产生了内容完全相同的相邻帧
    identical = [
        i for i in range(res.amplitude.shape[0] - 1)
        if np.array_equal(res.amplitude[i], res.amplitude[i + 1])
    ]
    assert identical, "低转速段应当出现重复帧，用来证明没有做去重"


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

def test_metadata_carries_the_new_grid_keys_and_drops_hop():
    t, sig, rpm = _sweep()
    step = 0.1
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=step))
    md = res.metadata

    assert 'hop' not in md, "'hop' 是角度域等跳的遗物，网格语义下没有意义"
    for key in ('time_step_s', 'first_center', 'last_center',
                'coverage_start', 'coverage_end', 'frames'):
        assert key in md, key

    assert md['time_step_s'] == pytest.approx(step)
    assert md['first_center'] == pytest.approx(float(res.times[0]))
    assert md['last_center'] == pytest.approx(float(res.times[-1]))
    assert md['frames'] == res.times.size == res.amplitude.shape[0]


def test_metadata_coverage_is_the_support_grid_plus_half_a_step():
    """coverage = 支撑点各自的半格，且缩在录制区间内部（半窗死区是真的）。"""
    t, sig, rpm = _sweep()
    step = 0.1
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(time_res=step))
    md = res.metadata

    assert md['coverage_start'] == pytest.approx(md['first_center'] - step / 2.0)
    assert md['coverage_end'] == pytest.approx(md['last_center'] + step / 2.0)
    assert md['coverage_start'] > md['time_start']
    assert md['coverage_end'] < md['time_end']


def test_coverage_no_longer_claims_the_whole_recording():
    """回归守卫：旧实现把 coverage 报成整段录制，x 轴才会撒谎 ±6 s。"""
    t, sig, rpm = _sweep()
    res = COTOrderAnalyzer.compute(sig, rpm, t, _params(nfft=1024, time_res=0.1))
    md = res.metadata

    # 半窗死区在 nfft=1024（4 转）上不可能只有几毫秒
    assert md['coverage_start'] - md['time_start'] > 0.05
    assert md['time_end'] - md['coverage_end'] > 0.05


# ---------------------------------------------------------------------------
# 数值未被动过
# ---------------------------------------------------------------------------

def test_pure_order_amplitude_is_unchanged_by_the_new_layout():
    """合成定阶正弦的绝对幅值仍是 1.0——归一化（/w_sum*2、DC/Nyquist 折半、
    插值到 out_orders）一个字没改。"""
    amp = 1.0
    t, sig, rpm = _synth(dur=10.0, rpm_const=600.0, order=2.0, amp=amp)
    res = COTOrderAnalyzer.compute(
        sig, rpm, t, _params(nfft=1024, order_res=0.05, time_res=0.2)
    )

    o2 = int(np.argmin(np.abs(res.orders - 2.0)))
    peak = res.amplitude[:, o2]
    assert peak.size > 5
    # 窗内恒速恒幅 → 每帧都应该量到 ~1.0
    np.testing.assert_allclose(peak, amp, rtol=0.02)


def test_a_weighting_still_applies_per_frame():
    """A 计权仍按帧内平均转速施加（没有随帧布局改动漂走）。"""
    t, sig, rpm = _synth(dur=10.0, rpm_const=600.0, order=2.0, amp=1.0)
    plain = COTOrderAnalyzer.compute(sig, rpm, t, _params(nfft=1024, time_res=0.2))
    weighted = COTOrderAnalyzer.compute(
        sig, rpm, t, _params(nfft=1024, time_res=0.2, weighting='A')
    )

    np.testing.assert_allclose(plain.times, weighted.times)
    o2 = int(np.argmin(np.abs(plain.orders - 2.0)))
    # 20 Hz 上 A 计权衰减很深，加权后必须显著更小
    assert weighted.amplitude[:, o2].mean() < 0.2 * plain.amplitude[:, o2].mean()
