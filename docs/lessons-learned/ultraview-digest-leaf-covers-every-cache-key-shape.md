---
id: ultraview-digest-leaf-covers-every-cache-key-shape
status: active
owners: [codex, claude]
keywords: [ultraview, digest, cache-key, FrfCacheKey, dataclass, AnalysisPinBook, throttled, logging]
paths:
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/analysis_cache.py
  - mf4_analyzer/ui/ultraview_state.py
  - tests/ui/test_ultraview_capture.py
checks:
  - rg -n "_digest_leaf|_digest_key|_pane_cache_keys" mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - rg -n "class .*CacheKey|def make_key" mf4_analyzer/ui/analysis_cache.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_capture.py -q -k "dataclass or digest_failure or no_result_skip or pin_set_order"
---

# UltraView Digest Leaves Cover Every Cache-Key Shape

Trigger: Changing `_digest_leaf` / `_digest_key` / `_pane_cache_keys`, adding a
section to `SOURCE_SECTIONS`, or introducing a new analysis cache-key type in
`ui/analysis_cache.py`.

Past failure: `_digest_leaf` normalized scalars, tuples, and lists, then ended
in a bare `return value` for anything else. Most sections key their cache with a
plain tuple, but FRF uses a frozen dataclass (`FrfCacheKey`), which sailed
through that fallthrough and reached `presentation_digest` as an unserializable
leaf. `current_digest_for` caught the `TypeError` and returned `None` — and
`request_capture` returns early on a `None` digest, so **every FRF View that had
actually computed a result could never capture a preview**. The card stayed
missing while the log repeated `presentation digest failed` with no clue which
leaf was at fault, because the exception text was swallowed. The same review
found `_pane_cache_keys` returning `list(pin_set)`: pin slots are `set`s, so a
multi-source FFT pane produced a different `cache_keys` ordering in every
process (string hashing is salted per run) and its persisted digest could not
match after a restart.

Rule: Digest normalization must be **total over the shapes cache keys actually
take** — extend `_digest_leaf` when a new key type appears, and tag the encoding
with the class name so a dataclass cannot alias a plain mapping of the same
shape. Never coerce an unknown leaf with `str()`/`repr()`: a default `repr`
carries the object address and would make the digest differ every run. Anything
genuinely unknown keeps falling through to `_canonical_json_value`, which stays
the single authority on what is digest-stable. Whatever feeds the digest must be
ordered deterministically before it gets there — a `set` never reaches it
unsorted. When a digest attempt fails, log the exception; a bare "digest failed"
is not a diagnosis. And keep log levels honest: an uncomputed View is expected
state (`_CAPTURE_SKIP_LEVELS`), while a fault such as `digest-unavailable` or
`grab-invalid` stays a warning — see
[UltraView Time Capture Uses Plotted Ink And Stable Digest](ultraview-time-capture-ink-and-stable-digest.md).

Verification: `test_frf_dataclass_cache_key_still_yields_a_digest`,
`test_dataclass_leaf_does_not_collide_with_a_plain_mapping`,
`test_digest_failure_names_the_offending_value`,
`test_multi_source_pane_digest_is_stable_against_pin_set_order`, and
`test_no_result_skip_is_not_logged_as_a_warning` in
`tests/ui/test_ultraview_capture.py`.
