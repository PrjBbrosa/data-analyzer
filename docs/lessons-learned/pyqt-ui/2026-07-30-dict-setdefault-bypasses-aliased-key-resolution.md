---
id: pyqt-ui/2026-07-30-dict-setdefault-bypasses-aliased-key-resolution
status: active
owners: [codex]
keywords: [dict-subclass, setdefault, key-alias, phantom-key, composite-key]
paths: [mf4_analyzer/ui/pg_canvas/_shared.py]
checks: [composite_items, as_composite_dict]
tests: [tests/ui/test_pg_channel_key_dict.py]
---

# `dict.setdefault` bypasses aliased-key resolution in a dict subclass

Trigger: A `dict` subclass aliases multiple external keys to one or more stored
keys and overrides reads such as `__contains__`, `__getitem__`, or `get`.

Past failure: Calling inherited `setdefault` with a display label bypassed
`_ChannelKeyDict`'s alias resolution, inserted a bare-name phantom entry, and
made that entry mask both real composite-key channels on later reads.

Rule: Audit the whole mutating surface of an aliased-key mapping. Implement
`setdefault`, `update`, `copy`, deletion, and pop through the class's own
resolution/storage primitives; provide an explicit lossless conversion for
callers that need stored identity.

Verification: Run
`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_channel_key_dict.py -q`
and assert no bare display key is stored after `setdefault` on a collision.
