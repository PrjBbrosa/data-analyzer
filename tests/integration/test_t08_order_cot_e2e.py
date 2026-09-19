"""T08 whole-file COT second-order neighborhood — explicit real-file input.

Default suite does not depend on this customer MF4. Supply the file via
``TRACELAB_T08_MF4`` or ``TRACELAB_REALFILE_ROOT``. Required real-file gate:
``TRACELAB_REQUIRE_REALFILE=1``.
"""
from __future__ import annotations

import pytest

from tests.realfile_corpus import CorpusSupplyError, resolve_realfile_sample


def _t08_sample():
    try:
        return resolve_realfile_sample("t08-yuandi-foc-ripple")
    except CorpusSupplyError as exc:
        if exc.optional:
            pytest.skip(str(exc))
        pytest.fail(str(exc))


def test_cot_resolves_order_2_on_T08():
    import numpy as np
    from asammdf import MDF
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams

    entry, path = _t08_sample()
    mdf = None
    try:
        mdf = MDF(str(path))
        sig = mdf.get(entry["signal_channel"])
        rpm = mdf.get(entry["rpm_channel"])
        t = sig.timestamps
        p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                      order_res=0.05, time_res=0.05, fs=100.0)
        res = COTOrderAnalyzer.compute(sig.samples.astype(float),
                                       rpm.samples.astype(float), t, p)
    finally:
        if mdf is not None:
            mdf.close()

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o15_idx = int(np.argmin(np.abs(res.orders - 1.5)))
    o25_idx = int(np.argmin(np.abs(res.orders - 2.5)))

    o2 = res.amplitude[:, o2_idx].mean()
    o15 = res.amplitude[:, o15_idx].mean()
    o25 = res.amplitude[:, o25_idx].mean()

    ratio = float(entry["neighbor_ratio"])
    # On T08 the ripple is around order 2; demand order 2 dominate the
    # neighborhood by at least 2x — strict enough to fail if smearing returns.
    assert o2 > ratio * o15, f"order2={o2:.4f} order1.5={o15:.4f} — COT smeared"
    assert o2 > ratio * o25, f"order2={o2:.4f} order2.5={o25:.4f} — COT smeared"
