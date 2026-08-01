---
id: producer-result-contract-mock-consumers
status: active
owners: [codex]
keywords: [producer-contract, test-fake, directed-suite, TimePlotBuildResult]
paths: [mf4_analyzer/ui/main_window/window.py, tests/ui/test_compute_progress_integration.py, tests/ui/test_main_window_overlay_risk.py, docs/superpowers/plans/*]
checks: ["rg -n '_build_time_plot_data' tests"]
tests: [tests/ui/test_compute_progress_integration.py, tests/ui/test_main_window_overlay_risk.py]
---

# Producer Result Contracts Include Mock Consumers

Trigger: Changing a shared producer from a primitive payload such as a list or
tuple to a structured result object, especially when tests monkeypatch that
producer.

Past failure: `_build_time_plot_data()` changed from a list to
`TimePlotBuildResult`, but two tests still returned list fakes. The feature's
directed plan omitted those consumer files, so their AttributeErrors survived
the initial implementation verification.

Rule: When a producer return contract changes, search all production and test
callers plus monkeypatch targets for the exact producer symbol. Update every
fake to construct the authoritative result type, and include those consumer
files in the directed plan rather than adding compatibility code for stale
test doubles.

Verification: Grep all `_build_time_plot_data` consumers, then run the focused
compute-progress and overlay-risk files together; both must pass with
`TimePlotBuildResult` fakes.
