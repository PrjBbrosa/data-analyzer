"""Structural guard (措施 A): the analysis cache keys are mechanically bound
to their compute-parameter dataclasses.

The root failure these tests prevent: a *compute* parameter that lives on the
frozen dataclass (the single authority for what the analyzer actually reads)
but is forgotten in the cache key — so changing it silently reuses a stale
result computed with the old value. The dual failure is a *display* parameter
(e.g. ``db_reference``) leaking INTO the dataclass / cache key, forcing a
recompute that produces a byte-identical result.

Strategy
--------
For FFT-vs-Time (:class:`SpectrogramParams`) and Order (:class:`COTParams`):

1. Take the dataclass field set via :func:`dataclasses.fields`.
2. Extract the set of parameter names the cache-key function *registers* by
   parsing its source for ``params.get('NAME'...)`` / ``p.get('NAME'...)`` /
   ``params['NAME']`` accesses (the key functions are pure dict readers).
3. Assert ``dataclass_fields == registered_compute_fields`` after removing a
   small, explicitly-justified exemption set on each side (external input
   dimensions that are not dataclass fields, and dataclass fields that are
   fixed constants the UI never varies).

Adding a field to a dataclass without adding it to the key (or to the
documented exemption set) turns these RED, which is the whole point: the key
can never silently drift out of sync with the compute contract again.
"""
from __future__ import annotations

import dataclasses
import inspect
import re

from mf4_analyzer.signal.spectrogram import SpectrogramParams
from mf4_analyzer.signal.order_cot import COTParams
from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin
from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin
from mf4_analyzer.ui.main_window._order_mixin import OrderMixin


# Matches reads on the params argument ONLY (named ``params`` or ``p`` in the
# key functions): params.get('name'...), p.get('name'...), params['name'],
# p['name']. Restricting the receiver to params/p avoids false positives from
# unrelated subscripts such as ``self.analysis_caches['fft_time']``.
_GET = re.compile(r"""\b(?:params|p)\.get\(\s*['"]([a-zA-Z_][\w]*)['"]""")
_SUB = re.compile(r"""\b(?:params|p)\[\s*['"]([a-zA-Z_][\w]*)['"]\s*\]""")


def _registered_keys(func):
    """Return the set of string param names a pure dict-reading key function
    pulls from its params argument (via ``.get('x')`` or ``['x']``)."""
    src = inspect.getsource(func)
    names = set(_GET.findall(src)) | set(_SUB.findall(src))
    return names


def _dataclass_fields(dc):
    return {f.name for f in dataclasses.fields(dc)}


# ---------------------------------------------------------------------------
# FFT-vs-Time : SpectrogramParams  <->  _fft_time_analysis_cache_key
# ---------------------------------------------------------------------------
# The analysis-cache key tuple also carries three EXTERNAL dimensions that are not (and
# must not be) SpectrogramParams fields — they identify the source signal /
# slice, not the spectrogram math:
_FFT_TIME_EXTERNAL = {
    'fid',          # which file
    'channel',      # which channel
    'time_range',   # selected time window mask
    # nfft_effective is the RESOLVED nfft (auto -> int); it is read as the
    # key's nfft value and maps onto the dataclass 'nfft' field.
    'nfft_effective',
}


def test_fft_time_analysis_key_field_set_equals_spectrogram_params():
    """Same binding for the AnalysisResultCache key (primary path used on view
    switch). It must register the same compute fields as the dataclass."""
    dc = _dataclass_fields(SpectrogramParams)
    registered = _registered_keys(FFTTimeMixin._fft_time_analysis_cache_key)
    compute_fields = registered - _FFT_TIME_EXTERNAL
    compute_fields.add('nfft')
    compute_fields -= {'nfft_effective'}
    assert compute_fields == dc, (
        "FFT-vs-Time analysis cache key drifted from SpectrogramParams.\n"
        f"  dataclass only: {sorted(dc - compute_fields)}\n"
        f"  key only:       {sorted(compute_fields - dc)}"
    )


# ---------------------------------------------------------------------------
# Order : COTParams  <->  _order_compute_cache_params
# ---------------------------------------------------------------------------
# External input dimensions registered in the key that are NOT COTParams
# fields (they describe inputs upstream of the spectrogram math):
_ORDER_KEY_EXTERNAL = {
    'rpm_source',      # which rpm channel(s)
    'time_range',      # selected time window
    'rpm_factor',      # scales the rpm INPUT array before compute (not a field)
    'rpm_mode',        # selects rpm input construction upstream of COTParams
    'manual_rpm',      # constant rpm input value when rpm_mode == manual
    'nfft_mode',       # auto/fixed resolution mode; drives nfft_effective
    'nfft_effective',  # resolved nfft -> maps onto COTParams.nfft
    'nfft_preview',    # last-resort nfft fallback for the key -> COTParams.nfft
}
# COTParams fields that are intentionally NOT in the key, each justified:
_ORDER_FIELD_EXEMPT = {
    # min_rpm_floor is never surfaced in the inspector and never passed when
    # the UI builds COTParams (mf4_analyzer/ui/main_window/_order_mixin.py
    # always uses the dataclass default 10.0), so it is a fixed constant, not
    # a user-tunable dimension. If the UI ever exposes it, drop it from this
    # set and register it in _order_compute_cache_params (this test will then
    # force the change).
    'min_rpm_floor',
}


def test_order_key_field_set_equals_cot_params():
    dc = _dataclass_fields(COTParams)
    registered = _registered_keys(OrderMixin._order_compute_cache_params)
    compute_fields = registered - _ORDER_KEY_EXTERNAL
    compute_fields.add('nfft')               # registered via nfft_effective fallback
    compute_fields -= {'nfft_effective'}
    dc_keyable = dc - _ORDER_FIELD_EXEMPT
    assert compute_fields == dc_keyable, (
        "Order cache key drifted from COTParams.\n"
        f"  dataclass (keyable) only: {sorted(dc_keyable - compute_fields)}\n"
        f"  key only:                 {sorted(compute_fields - dc_keyable)}\n"
        "Add the new COTParams field to _order_compute_cache_params, or add it "
        "to _ORDER_FIELD_EXEMPT with a justification if the UI never varies it."
    )


def test_min_rpm_floor_is_a_fixed_default_in_the_ui_path():
    """Pin the justification for exempting min_rpm_floor: the UI's COTParams
    construction must not pass it, so it stays the dataclass default. If a
    future change starts varying it, this guard fails and forces it into the
    cache key.

    The assertion is scoped to COTParams(...) call-sites (kwarg form), NOT the
    entire source, so that comments/docstrings that mention min_rpm_floor do
    not cause a false positive.
    """
    src = inspect.getsource(OrderMixin)
    # Match any COTParams( ... ) constructor call that passes min_rpm_floor as
    # a keyword argument.  We search for "COTParams(" followed (possibly across
    # whitespace/continuations) by "min_rpm_floor=", using re.DOTALL so that
    # multi-line constructor calls are found.
    pattern = re.compile(
        r'COTParams\s*\([^)]*min_rpm_floor\s*=',
        re.DOTALL,
    )
    match = pattern.search(src)
    assert match is None, (
        "A COTParams() constructor call in OrderMixin now passes min_rpm_floor "
        "as a keyword argument.  It must be registered in "
        "_order_compute_cache_params and removed from _ORDER_FIELD_EXEMPT so "
        "varying it invalidates the cache correctly."
    )


# ---------------------------------------------------------------------------
# No display-only parameter may leak into a compute dataclass.
# ---------------------------------------------------------------------------
_DISPLAY_ONLY = {'db_reference', 'cmap', 'amplitude_mode', 'dynamic',
                 'freq_auto', 'freq_min', 'freq_max',
                 'z_auto', 'z_floor', 'z_ceiling',
                 'x_auto', 'x_min', 'x_max', 'y_auto', 'y_min', 'y_max',
                 'interp'}


def test_no_display_param_on_compute_dataclasses():
    for dc in (SpectrogramParams, COTParams):
        leaked = _dataclass_fields(dc) & _DISPLAY_ONLY
        assert not leaked, (
            f"{dc.__name__} carries display-only field(s) {sorted(leaked)} — "
            "display params belong in the render signature / plot kwargs, not "
            "the compute contract (they would force needless recomputes)."
        )


def test_spectrogram_params_every_field_is_consumed_by_compute():
    """Each SpectrogramParams field must be read by SpectrogramAnalyzer.compute.

    Source-introspection: the compute() body must reference ``params.<field>``.
    A field with no consumer is a display-only leak masquerading as a compute
    input. (All six current fields — fs, nfft, window, overlap, remove_mean,
    weighting — are genuinely read by compute, so this is a clean equality.)
    """
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
    src = inspect.getsource(SpectrogramAnalyzer.compute)
    for name in _dataclass_fields(SpectrogramParams):
        assert f'params.{name}' in src, (
            f"SpectrogramParams.{name} is never read by compute() — it is not "
            "a real compute input and must not live on the dataclass."
        )


# Explicit COTParams consumption map (updated by Task 5: time_res is now
# genuinely read by compute() to derive the angle-domain hop).
_COT_CONSUMED_BY_COMPUTE = {
    'samples_per_rev',  # order_cot.py: dtheta, raw_orders
    'nfft',             # frame length
    'window',           # get_analysis_window(params.window, nfft)
    'max_order',        # out_orders grid upper bound
    'order_res',        # out_orders grid step
    'weighting',        # _validate_weighting + a-weighting gain
    'min_rpm_floor',    # per-frame rpm gate (params.min_rpm_floor)
    'time_res',         # hop_angle = round(time_res / dt_angle); wired by Task 5
}
# Not consumed by compute (do NOT assert as consumed):
#   - fs: source sample-rate, carried through for batch-preset capture only;
#     compute works in the angle domain and never reads it.
_COT_NOT_CONSUMED = {'fs'}


def test_cot_consumption_map_partitions_every_field():
    """The consumption map + the not-consumed set must together cover every
    COTParams field exactly. If a field is added to the dataclass, this fails
    until it is classified (consumed vs. carry-through), preventing a silent
    new field that is neither keyed nor accounted for."""
    dc = _dataclass_fields(COTParams)
    classified = _COT_CONSUMED_BY_COMPUTE | _COT_NOT_CONSUMED
    assert classified == dc, (
        "COTParams field set changed; classify the new/removed field in "
        "_COT_CONSUMED_BY_COMPUTE or _COT_NOT_CONSUMED.\n"
        f"  unclassified: {sorted(dc - classified)}\n"
        f"  stale:        {sorted(classified - dc)}"
    )


def test_cot_consumed_fields_are_actually_read_by_compute():
    """Every field we CLAIM is consumed must really be referenced by compute —
    the map cannot lie."""
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer
    src = inspect.getsource(COTOrderAnalyzer.compute)
    for name in _COT_CONSUMED_BY_COMPUTE:
        assert f'params.{name}' in src, (
            f"_COT_CONSUMED_BY_COMPUTE claims {name} is read by compute, but "
            f"'params.{name}' does not appear in its source."
        )


# ---------------------------------------------------------------------------
# FFT : dB-reference-defaults Task 6 (spec §16) — db_reference /
# db_reference_mode / catalog revision are display-only and must never leak
# into _fft_compute_cache_params's OUTPUT, even when the upstream fft_params
# dict (current_params()) carries them (it always does). This is a black-box
# behavioral guard rather than the source-introspection _registered_keys
# helper above: _fft_compute_cache_params reads its argument via the local
# name ``fft_params`` (not ``params``/``p``), so the regex would silently
# match nothing and the guard would be vacuously true either way.
# ---------------------------------------------------------------------------

def test_db_reference_mode_and_catalog_revision_stay_out_of_compute_cache_key():
    fft_params = {
        'window': 'hann', 'nfft': 4096, 'nfft_effective': 4096, 'fs': 1000.0,
        'avg_mode': '单帧', 'avg_overlap': 50, 'weighting': 'A',
        'db_reference': 5e-6, 'db_reference_mode': 'auto',
        'db_reference_revision': 3, 'catalog_revision': 3,
    }
    out = FFTMixin._fft_compute_cache_params(fft_params)
    leaked = {
        'db_reference', 'db_reference_mode',
        'db_reference_revision', 'catalog_revision',
    } & out.keys()
    assert not leaked, (
        f"FFT compute cache-key params leaked display-only field(s) {sorted(leaked)} "
        "— db_reference/db_reference_mode/catalog revision belong in the render "
        "signature (_fft_render_signature), never the compute cache key."
    )
