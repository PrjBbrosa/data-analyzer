---
role: signal-processing
tags: [io, encoding, windows, json, cjk, locale]
created: 2026-04-27
updated: 2026-04-27
cause: insight
supersedes: []
---

## Context
`batch_preset_io.save_preset_to_json` used `Path.write_text(json.dumps(..., ensure_ascii=False))` and
`Path.read_text()` with no `encoding=` argument. On Windows the default text encoding is the system
locale (cp936/gbk/cp1252), so a preset whose `name`, `target_signals`, or `params` keys contain
Chinese characters (routine in this project — the entire UI is Chinese, channels like `转速`/`振动`
are everywhere) was silently transcoded through cp936 on write and on read, producing invalid UTF-8
on disk and corrupting round-trips.

## Lesson
`json.dumps(..., ensure_ascii=False)` and the file-write encoding are coupled: `ensure_ascii=False`
emits raw non-ASCII codepoints into the *string*, but those codepoints are still subject to the file
codec when `Path.write_text` (or `open(... 'w')`) encodes the string to bytes. If the file codec is
not UTF-8, the result is either `UnicodeEncodeError` or mojibake — and the read side, defaulting to
the same locale codec, will silently "round-trip" garbage. `ensure_ascii=False` is a UTF-8-only
choice; pair it with `encoding="utf-8"` on every text I/O call.

## How to apply
Whenever you write or read text that may contain non-ASCII (CJK channel names, accented Latin,
emoji) — presets, configs, log files, exported CSVs with Chinese headers — pass `encoding="utf-8"`
explicitly to `Path.write_text` / `Path.read_text` / `open()`. Do not rely on platform default. If
the JSON producer uses `ensure_ascii=False`, treat that as a hard signal that the file write must
also be `encoding="utf-8"`; reviewers should grep for `ensure_ascii=False` and confirm a paired
`encoding="utf-8"` on the same statement.
