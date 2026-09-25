---
id: pytest-item-pin-records-release-after-check
status: active
owners: [codex]
keywords: [pytest, pyqt, conftest, gc, pin]
paths: [tests/ui/conftest.py, tests/ui/test_qt_fixture_lifecycle.py]
checks:
  - Clear item-owned pin lists after the filter check and before gc.collect().
  - Keep the check failure, and do not drop session-owned registry objects.
tests:
  - tests/ui/test_qt_fixture_lifecycle.py::test_fixture_teardown_drains_owned_deferred_deletes_in_bounded_child
  - tests/ui/test_qt_fixture_lifecycle.py::test_failed_pin_filter_check_releases_records_and_still_fails
---

# Release Pytest Item Pin Records After The Filter Check

Trigger: Editing UI teardown or pin-filter bookkeeping when deleted Qt wrappers survive the next item.

Past failure: `_pin_owned_routers` and `_pin_owned_controllers` stayed on the
pytest item after teardown. C++ objects were already deleted, but full GC
left the ChartStack, controller, and router alive. The next items kept
walking those wrappers.

Rule: Use the strong lists only for that item's filter judgment. Release them
in a finally so a failed check still drops them and still fails. Then
collect. Session registry objects and QApplication stay.

Verification: `tests/ui/test_qt_fixture_lifecycle.py` child process. On the
old hook the reclaim test still sees 3 owners; after the release it sees none,
while the session router and QApplication remain.
