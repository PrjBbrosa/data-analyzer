import os
import numpy as np
import pytest

T08 = "/Users/donghang/Downloads/data analyzer/testdoc/T08_YuanDi_FOC_CurrentMode_0-1-2_Ripple.MF4"


@pytest.mark.skipif(not os.path.exists(T08), reason="T08 reference file missing")
def test_cot_resolves_order_2_on_T08():
    from asammdf import MDF
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams

    mdf = MDF(T08)
    sig = mdf.get('Rte_TAS_mTorsionBarTorque_xds16')
    rpm = mdf.get('Rte_RPS_nRotorSpeed_xds16')
    t = sig.timestamps
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.05, fs=100.0)
    res = COTOrderAnalyzer.compute(sig.samples.astype(float),
                                    rpm.samples.astype(float), t, p)

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o15_idx = int(np.argmin(np.abs(res.orders - 1.5)))
    o25_idx = int(np.argmin(np.abs(res.orders - 2.5)))

    o2 = res.amplitude[:, o2_idx].mean()
    o15 = res.amplitude[:, o15_idx].mean()
    o25 = res.amplitude[:, o25_idx].mean()

    # On T08 the ripple is around order 2; demand order 2 dominate the
    # neighborhood by at least 2x — strict enough to fail if smearing returns.
    assert o2 > 2.0 * o15, f"order2={o2:.4f} order1.5={o15:.4f} — COT smeared"
    assert o2 > 2.0 * o25, f"order2={o2:.4f} order2.5={o25:.4f} — COT smeared"
