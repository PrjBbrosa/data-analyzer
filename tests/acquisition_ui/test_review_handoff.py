"""Review modal + Analyzer handoff — Stage 5.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§State Machine `ReviewModal`, §Architecture Contract / Analyzer Handoff,
§Persistence Contract `Relationship to manifest.json`.

Plan: Stage 5 ``test_review_handoff.py`` — proves Cockpit handoff calls
``MainWindow.load_file`` ONLY after finalized save/archive completes;
pins the four review-modal actions; and pins ``expected_channels`` via a
1-second fake recording with three measurements (``test_expected_channels``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.acquisition.manifest import (
    Mf4DatasetEntry,
    load_manifest,
    sha256_file,
)
from mf4_analyzer.acquisition.preflight import analyze_mf4
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
    SessionSummary,
)
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.review_modal import (
    ACTION_DISCARD,
    ACTION_OPEN_ANALYZER,
    ACTION_SAVE_AND_ARCHIVE,
    ACTION_SAVE_ONLY,
    AUTO_STOP_BANNER_TEXT,
    ReviewContext,
    ReviewModal,
    run_stop_flush_finalize,
)
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    HealthyPredicateResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_one_second_fake(tmp_path: Path, *, signals=None) -> CaptureController:
    """Drive a short fake recording and return the controller pre-stop."""
    selected = signals or (
        SelectedMeasurement(name="EngSpd"),
        SelectedMeasurement(name="Throttle"),
        SelectedMeasurement(name="Steering"),
    )
    cfg = SessionConfig(output_mf4=tmp_path / "rec.mf4", selected=selected)
    backend = FakeRecorderBackend(samples_per_second=20.0)
    ctrl = CaptureController(cfg, backend)
    ctrl.start()
    # Drive enough poll steps to put samples through the writer.
    for _ in range(10):
        ctrl.poll_step()
    return ctrl


def _finalize_and_make_context(
    tmp_path: Path,
    *,
    manifest_path: Path | None = None,
    auto_stop: bool = False,
) -> ReviewContext:
    """Run the canonical stop/flush/finalize, then build a ReviewContext."""
    ctrl = _run_one_second_fake(tmp_path)
    result = run_stop_flush_finalize(
        controller=ctrl,
        expected_channels=tuple(m.name for m in ctrl.config.selected),
    )
    if auto_stop:
        result.summary.auto_stop = True
    return ReviewContext(
        mf4_path=Path(result.summary.output_mf4),
        sidecar_path=result.sidecar_path,
        summary=result.summary,
        preflight=result.preflight,
        preflight_sidecar_path=result.preflight_sidecar_path,
        expected_channels=tuple(m.name for m in ctrl.config.selected),
        manifest_path=manifest_path,
    )


# ---------------------------------------------------------------------------
# expected_channels — the contract pinned by the brief
# ---------------------------------------------------------------------------


def test_expected_channels(tmp_path):
    """A 1-second fake recording with three measurements MUST produce a
    preflight result whose ``missing_channels == ()``.

    Spec §Architecture Contract: Cockpit passes ``expected_channels =
    tuple(m.name for m in selected)`` verbatim to ``analyze_mf4(...)``;
    the writer's channel-naming contract guarantees the names round-trip.
    """
    selected = (
        SelectedMeasurement(name="EngSpd"),
        SelectedMeasurement(name="Throttle"),
        SelectedMeasurement(name="Steering"),
    )
    ctrl = _run_one_second_fake(tmp_path, signals=selected)
    result = run_stop_flush_finalize(
        controller=ctrl,
        expected_channels=tuple(m.name for m in selected),
    )
    assert result.preflight.missing_channels == ()
    # And the underlying analyze_mf4 call agrees when invoked fresh.
    fresh = analyze_mf4(
        ctrl.config.output_mf4,
        expected_channels=tuple(m.name for m in selected),
    )
    assert fresh.missing_channels == ()


# ---------------------------------------------------------------------------
# Review modal action set (the four spec actions)
# ---------------------------------------------------------------------------


def test_review_modal_has_four_actions(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    try:
        # All four buttons exist with the verbatim spec strings.
        labels = [
            modal._btn_discard.text(),
            modal._btn_save_only.text(),
            modal._btn_archive.text(),
            modal._btn_open_analyzer.text(),
        ]
        assert labels == [
            ACTION_DISCARD,
            ACTION_SAVE_ONLY,
            ACTION_SAVE_AND_ARCHIVE,
            ACTION_OPEN_ANALYZER,
        ]
    finally:
        modal.done(0)


# ---------------------------------------------------------------------------
# Auto-stop banner — surfaces when summary.auto_stop is True
# ---------------------------------------------------------------------------


def test_auto_stop_banner_shows_when_summary_flagged(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path, auto_stop=True)
    modal = ReviewModal(ctx)
    try:
        assert modal._auto_stop_banner is not None
        assert modal._auto_stop_banner.text() == AUTO_STOP_BANNER_TEXT
    finally:
        modal.done(0)


def test_auto_stop_banner_hidden_when_summary_clean(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path, auto_stop=False)
    modal = ReviewModal(ctx)
    try:
        assert modal._auto_stop_banner is None
    finally:
        modal.done(0)


# ---------------------------------------------------------------------------
# 在 Analyzer 打开 — disabled until finalized save/archive
# ---------------------------------------------------------------------------


def test_open_analyzer_button_disabled_before_save_or_archive(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    try:
        # Save/archive haven't fired yet — the button must be disabled.
        assert modal.is_open_in_analyzer_enabled() is False
    finally:
        modal.done(0)


def test_open_analyzer_button_enabled_after_save_only(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    try:
        # CR3 fix: ``仅保存文件`` no longer auto-closes the modal — it
        # flips ``_save_ok`` synchronously and refreshes button state.
        # The Analyzer-open action MUST now be reachable through the
        # real action call (no backdoor).
        modal.do_save_only()
        assert modal.save_ok is True
        assert modal.is_open_in_analyzer_enabled() is True
    finally:
        if modal.isVisible():
            modal.done(0)


# ---------------------------------------------------------------------------
# 丢弃 — deletes the file and disables 在 Analyzer 打开
# ---------------------------------------------------------------------------


def test_discard_removes_mf4_and_sidecars(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    assert ctx.mf4_path.exists()
    assert ctx.sidecar_path.exists()
    assert ctx.preflight_sidecar_path.exists()
    modal = ReviewModal(ctx)
    try:
        modal.do_discard()
    finally:
        if modal.isVisible():
            modal.done(0)
    assert not ctx.mf4_path.exists()
    assert not ctx.sidecar_path.exists()
    assert not ctx.preflight_sidecar_path.exists()
    assert modal.chosen_action == ACTION_DISCARD
    assert modal.discarded is True
    # 在 Analyzer 打开 must be disabled after discard, even though save_ok
    # would otherwise enable it.
    modal._save_ok = True
    modal._refresh_action_enabled()
    assert modal.is_open_in_analyzer_enabled() is False


# ---------------------------------------------------------------------------
# 仅保存文件 — keeps the MF4 + sidecar, marks save_ok
# ---------------------------------------------------------------------------


def test_save_only_keeps_files(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    try:
        modal.do_save_only()
    finally:
        if modal.isVisible():
            modal.done(0)
    assert ctx.mf4_path.exists()
    assert ctx.sidecar_path.exists()
    assert modal.chosen_action == ACTION_SAVE_ONLY
    assert modal.save_ok is True


# ---------------------------------------------------------------------------
# 保存并归档 — appends manifest entry, computes SHA, marks archive_ok
# ---------------------------------------------------------------------------


def test_archive_appends_manifest_entry(qapp, tmp_path):
    manifest_path = tmp_path / "manifest.json"
    ctx = _finalize_and_make_context(tmp_path, manifest_path=manifest_path)
    modal = ReviewModal(ctx)
    try:
        modal.do_archive()
    finally:
        if modal.isVisible():
            modal.done(0)
    assert modal.chosen_action == ACTION_SAVE_AND_ARCHIVE
    assert modal.archive_ok is True
    # Manifest exists and loads via the existing helper.
    assert manifest_path.exists()
    entries = load_manifest(manifest_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.path == str(ctx.mf4_path)
    assert "acquisition_cockpit" in entry.sets
    # expected_channels is populated from the recording selection.
    assert entry.expected_channels == ctx.expected_channels
    # SHA-256 was computed during archive write.
    assert entry.sha256 == sha256_file(ctx.mf4_path)
    # MF4 still exists.
    assert ctx.mf4_path.exists()


def test_run_stop_flush_finalize_preserves_selected_names(qapp, tmp_path):
    """CR3 finding 4 — Part A.

    The stop/flush/finalize sequence MUST stash the *selected*
    measurement names on its result so Cockpit can use them when
    building ``ReviewContext.expected_channels``. Using
    ``PreflightResult.channels`` instead silently truncates the manifest
    contract whenever the writer drops a channel.
    """
    selected = (
        SelectedMeasurement(name="EngSpd"),
        SelectedMeasurement(name="Throttle"),
        SelectedMeasurement(name="Steering"),
    )
    ctrl = _run_one_second_fake(tmp_path, signals=selected)
    expected = tuple(m.name for m in selected)
    result = run_stop_flush_finalize(controller=ctrl, expected_channels=expected)
    # The selected tuple is preserved verbatim on the result.
    assert result.selected_measurement_names == expected


def test_cockpit_archive_preserves_selected_names_on_dropped_channel(
    qapp, tmp_path
):
    """CR3 finding 4 — Part B.

    Drive Cockpit through a real recording → stop, then SIMULATE the
    writer dropping a channel by patching the stop result's preflight to
    a truncated channel tuple. The manifest entry MUST still record the
    full SELECTED expected_channels tuple, and preflight.missing_channels
    must surface the dropped one. Otherwise preflight can never detect
    "missing channel" on a future replay of the same manifest entry.
    """
    import dataclasses

    from mf4_analyzer.acquisition_ui.state import CockpitState

    manifest_path = tmp_path / "manifest.json"
    window = CockpitMainWindow()
    try:
        selected_names = ("EngSpd", "Throttle", "Steering")
        selected = tuple(SelectedMeasurement(name=n) for n in selected_names)
        ctrl = _run_one_second_fake(tmp_path, signals=selected)
        window.set_capture_controller(ctrl)
        window.set_manifest_target(manifest_path)
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        window.state_machine.request_start_recording()

        # Run stop. The left pane selection is empty here, but
        # request_stop_and_review reads it directly — so we seed the
        # window's last stop result via run_stop_flush_finalize directly
        # and then re-open the modal through the public path.
        result = run_stop_flush_finalize(
            controller=ctrl, expected_channels=selected_names
        )
        # Now simulate the writer dropping "Steering" by truncating the
        # preflight's channels/missing_channels fields.
        truncated_preflight = dataclasses.replace(
            result.preflight,
            channels=("EngSpd", "Throttle"),
            missing_channels=("Steering",),
        )
        window._last_stop_result = dataclasses.replace(
            result,
            preflight=truncated_preflight,
            selected_measurement_names=selected_names,
        )
        # Drive the state machine to REVIEW_MODAL and open the modal.
        window._state_machine.state = CockpitState.REVIEW_MODAL
        window._open_review_modal()
        modal = window.review_modal
        assert isinstance(modal, ReviewModal)
        # ReviewContext.expected_channels MUST be the full SELECTED set,
        # NOT the truncated written-channel set.
        assert modal.context.expected_channels == selected_names
        assert modal.context.preflight.missing_channels == ("Steering",)
        # Drive archive — manifest entry must record all three names.
        modal.do_archive()
        assert modal.archive_ok is True
        entries = load_manifest(manifest_path)
        assert len(entries) == 1
        assert tuple(entries[0].expected_channels) == selected_names
    finally:
        if window.review_modal is not None:
            window.review_modal.done(0)
            qapp.processEvents()
        window.close()


def test_archive_failure_does_not_corrupt_mf4(qapp, tmp_path):
    """Manifest write failure leaves the MF4 saved (NEVER corrupted) and
    the modal surfaces the failure separately."""
    ctx = _finalize_and_make_context(tmp_path)
    # Point manifest at a directory we'll make read-only so the write
    # fails. We use an injected writer that raises to avoid platform-
    # specific permission-bit behaviour.
    modal = ReviewModal(ctx)
    try:
        def _raise(_ctx):
            raise RuntimeError("simulated archive failure")

        modal._archive_writer = _raise
        modal.do_archive()
    finally:
        if modal.isVisible():
            modal.done(0)
    # Archive failed.
    assert modal.archive_ok is False
    # But MF4 is still saved.
    assert ctx.mf4_path.exists()
    # And save_ok was still flipped (the file is finalized).
    assert modal.save_ok is True


# ---------------------------------------------------------------------------
# 在 Analyzer 打开 — Cockpit handoff calls MainWindow.load_file only
# after finalized save/archive
# ---------------------------------------------------------------------------


def test_open_in_analyzer_emits_signal_only_after_save(qapp, tmp_path):
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    fired: list[str] = []
    modal.analyzer_open_requested.connect(lambda p: fired.append(p))
    try:
        # Before save: action is gated.
        modal.do_open_in_analyzer()
        assert fired == []  # signal must NOT have fired
        # CR3 fix: drive the real save action — it must NOT close the
        # modal, leaving 在 Analyzer 打开 reachable.
        modal.do_save_only()
        assert modal.is_open_in_analyzer_enabled() is True
        modal.do_open_in_analyzer()
        assert fired == [str(ctx.mf4_path)]
    finally:
        if modal.isVisible():
            modal.done(0)


def test_cockpit_routes_open_in_analyzer_to_load_file(qapp, tmp_path):
    """End-to-end: cockpit's ``在 Analyzer 打开`` signal bridges to the
    Analyzer's public ``load_file`` method. We inject a sink so the test
    doesn't need to build a real Analyzer window.

    CR3 fix: this exercises the *real* user flow — call ``do_save_only``
    (modal stays open), then ``do_open_in_analyzer`` (modal closes and
    the spy receives the path). No ``_save_ok`` backdoor.
    """
    window = CockpitMainWindow()
    try:
        # Walk to Recording → run real stop sequence.
        ctrl = _run_one_second_fake(tmp_path)
        window.set_capture_controller(ctrl)
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        window.state_machine.request_start_recording()
        # Inject a spy handoff so we don't open a real Analyzer.
        load_calls: list[str] = []
        window.set_analyzer_handoff(lambda p: load_calls.append(p))
        # Trigger Stop → ReviewModal.
        window.request_stop_and_review()
        modal = window.review_modal
        assert isinstance(modal, ReviewModal)
        ctx_mf4 = Path(modal.context.mf4_path)
        # Real-flow Step 1: 仅保存文件 — modal MUST stay open.
        modal.do_save_only()
        assert modal.isVisible() or modal.result() == 0, (
            "save-only must not auto-close the modal (CR3 finding 6)"
        )
        assert modal.is_open_in_analyzer_enabled() is True
        # Real-flow Step 2: 在 Analyzer 打开 — fires handoff and closes.
        modal.do_open_in_analyzer()
        qapp.processEvents()
        assert load_calls == [str(ctx_mf4)]
        assert ctx_mf4.exists()
    finally:
        if window.review_modal is not None:
            window.review_modal.done(0)
            qapp.processEvents()
        window.close()


def test_cockpit_archive_then_open_in_analyzer_real_flow(qapp, tmp_path):
    """Same real-flow contract for the archive path: ``保存并归档``
    must leave the modal open so the now-enabled ``在 Analyzer 打开``
    button can route to ``MainWindow.load_file``. CR3 finding 6.
    """
    window = CockpitMainWindow()
    try:
        ctrl = _run_one_second_fake(tmp_path)
        window.set_capture_controller(ctrl)
        window.set_manifest_target(tmp_path / "manifest.json")
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        window.state_machine.request_start_recording()
        load_calls: list[str] = []
        window.set_analyzer_handoff(lambda p: load_calls.append(p))
        window.request_stop_and_review()
        modal = window.review_modal
        assert isinstance(modal, ReviewModal)
        ctx_mf4 = Path(modal.context.mf4_path)
        # Drive archive — must succeed and stay open.
        modal.do_archive()
        assert modal.archive_ok is True
        assert modal.isVisible() or modal.result() == 0, (
            "archive success must not auto-close the modal (CR3 finding 6)"
        )
        assert modal.is_open_in_analyzer_enabled() is True
        # Then click the Analyzer button.
        modal.do_open_in_analyzer()
        qapp.processEvents()
        assert load_calls == [str(ctx_mf4)]
    finally:
        if window.review_modal is not None:
            window.review_modal.done(0)
            qapp.processEvents()
        window.close()


def test_cockpit_does_not_route_open_in_analyzer_before_save(qapp, tmp_path):
    """If the user clicks 在 Analyzer 打开 before saving, the cockpit
    must NOT call ``MainWindow.load_file``. The signal is gated by the
    button's enabled state — the action is a no-op."""
    window = CockpitMainWindow()
    try:
        ctrl = _run_one_second_fake(tmp_path)
        window.set_capture_controller(ctrl)
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        window.state_machine.request_start_recording()
        load_calls: list[str] = []
        window.set_analyzer_handoff(lambda p: load_calls.append(p))
        window.request_stop_and_review()
        modal = window.review_modal
        assert isinstance(modal, ReviewModal)
        # Click 在 Analyzer 打开 BEFORE save/archive. The action is gated.
        modal.do_open_in_analyzer()
        qapp.processEvents()
        assert load_calls == []
    finally:
        if window.review_modal is not None:
            window.review_modal.done(0)
            qapp.processEvents()
        window.close()


# ---------------------------------------------------------------------------
# Idempotency guard (lesson 2026-04-26-popover-accept-deactivate-race)
# ---------------------------------------------------------------------------


def test_review_modal_accept_idempotent(qapp, tmp_path):
    """Double ``accept()`` must not regress to Rejected."""
    ctx = _finalize_and_make_context(tmp_path)
    modal = ReviewModal(ctx)
    # Drive a real save so 在 Analyzer 打开 is reachable, then accept
    # via the Analyzer route (no backdoor).
    modal.do_save_only()
    modal.accept()
    # Second accept: must not change state / does not raise.
    modal.accept()
    # Calling reject() AFTER accept() must also be a no-op (the
    # _is_closing guard catches it).
    modal.reject()
    # Result should still be Accepted.
    from PyQt5.QtWidgets import QDialog
    assert modal.result() == QDialog.Accepted


# ---------------------------------------------------------------------------
# MainWindow.load_file — Analyzer-side handoff method
# ---------------------------------------------------------------------------


def test_analyzer_main_window_has_public_load_file(qapp):
    """The Analyzer ``MainWindow`` must expose ``load_file(path)`` as a
    public method (Stage 5 plan requirement)."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert callable(getattr(win, "load_file", None))
        # Signature accepts both str and Path; we don't actually invoke
        # the loader (no MF4 on disk in this test). The smoke test
        # `tests/ui/test_main_window_smoke.py` already covers the
        # private _load_one body.
    finally:
        win.close()


def test_analyzer_load_file_delegates_to_load_one(qapp, monkeypatch):
    """``MainWindow.load_file`` delegates to the private ``_load_one``
    flow — the only Analyzer-side modification authorized by Stage 5.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    try:
        captured: list[str] = []
        monkeypatch.setattr(
            win, "_load_one", lambda fp: captured.append(fp)
        )
        win.load_file("/tmp/some.mf4")
        assert captured == ["/tmp/some.mf4"]
        # Also accepts a Path.
        win.load_file(Path("/tmp/another.mf4"))
        assert captured[-1] == "/tmp/another.mf4"
    finally:
        win.close()
