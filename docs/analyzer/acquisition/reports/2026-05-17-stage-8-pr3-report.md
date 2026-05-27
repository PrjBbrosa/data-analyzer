# Stage 8 PR-3 Report: Vector XCP Cockpit UI

Date: 2026-05-17
Branch: `feat/acquisition`
Verdict: `GREEN_WITH_LIMITS`

## Scope

PR-3 implements the cockpit-facing Vector transport slice from the Stage 8 plan:

- `vector_hw_probe` for Windows Vector driver/app/channel checks and a real XCP CONNECT/DISCONNECT smoke helper.
- `SettingsDialog` Transport tab with Vector app/channel/CAN-FD/bitrate/Seed&Key/timeout fields.
- `Test Connection` flow that runs HW probe first, then XCP probe only when HW is green and A2L IF_DATA is available.
- Toolbar transport chip in `CockpitMainWindow`, including overflow-menu participation and styling.

The real Windows Vector + ECU acceptance remains gated to PR-4 because O-2/O-4 are not available on this macOS host.

## Implementation Evidence

- `mf4_analyzer/acquisition_capture/vector_hw_probe.py:26` lazy-loads Vector `canlib`; `:109` and `:124` lazy-load `can` / `pyxcp`, preserving macOS import safety.
- `mf4_analyzer/acquisition_capture/vector_hw_probe.py:32` centralizes `HwHealth(...)` construction so every path populates `channel_count` and `last_probe_ts`.
- `mf4_analyzer/acquisition_capture/vector_hw_probe.py:130` implements `test_xcp_connection(...)`, including bus-open failure text, CONNECT timeout with `cmd_id`, RESOURCE capture, optional Seed&Key, disconnect, and `bus.shutdown()`.
- `mf4_analyzer/acquisition_capture/health.py:203` lets the default HW probe delegate to `vector_hw_probe(transport)` when transport is bound, while preserving the non-Windows stub.
- `mf4_analyzer/acquisition_capture/health.py:247` adds `HealthAggregator(transport=...)` support for transport-bound probes.
- `mf4_analyzer/acquisition_ui/settings_dialog.py:266` adds `TransportTabWidget`; `:362` round-trips to `TransportConfig`.
- `mf4_analyzer/acquisition_ui/settings_dialog.py:376` disables Test Connection on non-Windows and `:381` disables it without IF_DATA/A2L.
- `mf4_analyzer/acquisition_ui/settings_dialog.py:515` exposes the test seam that runs HW probe before XCP probe.
- `mf4_analyzer/acquisition_ui/main_window.py:342` adds `cockpitTransportStatusChip`; `:485` includes it in toolbar overflow management.
- `mf4_analyzer/acquisition_ui/main_window.py:1421` adds `set_transport(...)`; `:1450` opens Settings directly on the Transport tab.
- `mf4_analyzer/acquisition_ui/main_window.py:1568` caches the first parsed A2L `IF_DATA XCP` block so a Windows Test Connection can enable after an A2L is selected.
- `mf4_analyzer/ui_kit/style.qss:387` styles the configured/unconfigured transport chip states.

## Test Evidence

Red tests observed before implementation:

- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_vector_hw_probe.py -v` failed with missing `mf4_analyzer.acquisition_capture.vector_hw_probe` and missing `HealthAggregator(transport=...)`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_settings_transport_tab.py -v` failed because `SettingsDialog(transport=...)`, patch seams, and Transport tab did not exist.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_main_window_transport_chip.py -v` failed because the chip, `set_transport`, and `initial_tab` settings entry did not exist.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_main_window_transport_chip.py::test_a2l_picker_caches_ifdata_for_transport_dialog -v` failed until `_on_pick_a2l()` cached parsed IF_DATA for Settings.

Green checks after implementation:

- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_vector_hw_probe.py tests/test_acquisition_capture_health.py -v` -> `25 passed`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_settings_transport_tab.py tests/acquisition_ui/test_main_window_transport_chip.py tests/acquisition_ui/test_settings_dialog.py tests/test_vector_hw_probe.py tests/test_acquisition_capture_health.py -v` -> `37 passed`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui -v` -> `145 passed`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_import_boundaries.py tests/test_vector_hw_probe.py tests/test_acquisition_capture_health.py -v` -> `28 passed`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition* tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_daq_session.py tests/test_xcp_auth.py tests/test_vector_xcp_backend.py tests/test_vector_hw_probe.py tests/acquisition_ui tests/ui/test_import_boundaries.py -v` -> `407 passed`.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test` -> exit `0`.
- `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_capture --backend fake --duration 2 --output /tmp/cap.mf4 --signals EngSpdAvg,EngTrqAct,VehSpeedRaw` -> `rx=564 write=564 dropped=0 warnings=0`.

## Plan Sync

The PR-3 plan was corrected where the original snippets drifted from the live codebase:

- UI tests moved from `tests/ui/...` to `tests/acquisition_ui/...`.
- `MainWindow(demo=True)` was corrected to the live `CockpitMainWindow()`.
- Chip lookup was corrected to `QLabel, "cockpitTransportStatusChip"`.
- Chip click path was corrected to `_open_settings_dialog(initial_tab="transport")`.

## Limits / PR-4 Gates

- No real Vector hardware was exercised on this host.
- The Test Connection button correctly stays disabled on macOS; Windows + ECU RESOURCE/latency proof remains PR-4.
- The file picker now caches the first A2L `IF_DATA XCP` block for Settings. Full A2L measurement-pool refresh remains outside this PR-3 slice.
