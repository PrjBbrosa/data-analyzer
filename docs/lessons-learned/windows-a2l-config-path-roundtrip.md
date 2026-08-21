---
id: windows-a2l-config-path-roundtrip
status: active
owners: [codex]
keywords: [acquisition, a2l, yaml, windows, config, path, persistence]
paths:
  - mf4_analyzer/acquisition_capture/config_store.py
  - tests/test_acquisition_config_store.py
  - tests/acquisition_ui/test_config_path_persistence.py
checks:
  - "QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_acquisition_config_store.py tests/acquisition_ui/test_config_path_persistence.py -q"
tests:
  - tests/test_acquisition_config_store.py::test_save_a2l_path_round_trips_windows_backslashes_without_doubling
  - tests/test_acquisition_config_store.py::test_load_config_decodes_legacy_escaped_windows_a2l_path
---

# Windows A2L Config Paths Round Trip

Trigger: Changing Acquisition config scalar encoding, parsing, or persisted A2L
path handling.

Past failure: The writer doubled every backslash in a Windows A2L path while
the custom YAML reader only removed quote delimiters. Restarting the Cockpit
therefore rehydrated a path with doubled separators and treated the last A2L
as missing. A follow-up review found that the comment scanner also mistook a
``#`` after an escaped legacy double quote for a real comment.

Rule: Config scalar encoding and parsing must be paired. Write new strings as
YAML single-quoted scalars (doubling apostrophes) so Windows separators remain
literal; retain decoding for the legacy double-quoted backslash and quote
escapes already written to user config files. Legacy double-quote comment
scanning must honor escaped quotes before looking for ``#``.

Verification: Run the focused config-store and Cockpit persistence tests with
an ordinary Windows path, a path containing an apostrophe, and a legacy
double-quoted escaped path, including an escaped quote immediately before
``#``.
