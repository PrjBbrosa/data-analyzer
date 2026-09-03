"""RED contract: one WinWert layout choice can apply to the rest of this open.

Frozen T3 seam: ``_ask_layout`` will grow a result with ``.accepted`` and
``.apply_to_remaining``. A raw ``bool`` still means ``apply_to_remaining=False``.
``WwtImportOutcome.accepted`` is the actual outcome, not the UI decision.

This module copies a local stub rather than editing ``test_wwt_import_flow.py``.
Drive ``MainWindow._open_data_paths()`` so the batch scope is the production
open/drop call, not a single ``_load_one``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]


class _AskLayoutDecision:
    """Bool-compatible T3 result: ``if _ask_layout():`` still uses ``accepted``.

    Current production ignores ``apply_to_remaining``, so a remembered
    decision still asks every display-bearing WWT — that is the genuine RED.
    """

    def __init__(self, accepted: bool, apply_to_remaining: bool = False):
        self.accepted = bool(accepted)
        self.apply_to_remaining = bool(apply_to_remaining)

    def __bool__(self):
        return self.accepted

    def __repr__(self):
        return (
            f"_AskLayoutDecision(accepted={self.accepted}, "
            f"apply_to_remaining={self.apply_to_remaining})"
        )


def _patch_ultraview_dpr(monkeypatch):
    """Dirty UltraView capture is missing ``_device_pixel_ratio``; tests cannot
    construct MainWindow without this. Product code is out of Task 0 ownership.
    """
    from mf4_analyzer.ui.main_window.ultraview_capture_coordinator import (
        UltraViewCaptureCoordinator,
    )

    monkeypatch.setattr(
        UltraViewCaptureCoordinator,
        "_device_pixel_ratio",
        lambda self: 2.0,
        raising=False,
    )


def _stub_wwt_ui(
    mw,
    monkeypatch,
    *,
    accepted=True,
    apply_to_remaining=False,
    raw_bool=False,
):
    asked = []

    def fake_ask(body, informative=""):
        asked.append((body, informative))
        if raw_bool:
            return bool(accepted)
        return _AskLayoutDecision(accepted, apply_to_remaining)

    monkeypatch.setattr(mw._wwt_import, "_ask_layout", fake_ask)
    monkeypatch.setattr(mw, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: None)
    return asked


def _make_window(qapp, qtbot, monkeypatch, **stub_kwargs):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.show()
    qapp.processEvents()
    asked = _stub_wwt_ui(mw, monkeypatch, **stub_kwargs)
    return mw, asked


def _winwert_view_count(mw) -> int:
    return sum(
        1
        for view in mw.view_manager.views
        if (view.name or "").startswith("WinWert")
    )


def test_remember_layout_asks_once_for_three_display_wwts(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """3 display WWTs + remember layout → one dialog; all three get Views.

    Hits ``_open_data_paths`` → ``begin_open_batch`` / ``coerce_layout_prompt``.
    Currently green on this worktree because T3 already consumes
    ``apply_to_remaining``; the contract is not weakened.
    """
    batch = wwt.batch_choice_set(
        tmp_path, n_display=3, include_no_display=False,
    )
    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=True, apply_to_remaining=True,
    )
    mw._open_data_paths([str(path) for path in batch.ordered_paths])
    qapp.processEvents()

    assert len(asked) == 1, (
        "remembered layout choice must apply to remaining WWTs in this "
        f"_open_data_paths() call; asked {len(asked)} times, want 1"
    )
    assert len(mw.files) == 3
    assert _winwert_view_count(mw) == 3


def test_remember_data_only_asks_once_and_creates_no_winwert_views(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """3 display WWTs + remember data-only → one dialog; sources load, 0 Views.

    Currently green: T3 already applies LOAD_DATA_ONLY to the rest of this
    ``_open_data_paths()`` call. Contract unchanged.
    """
    batch = wwt.batch_choice_set(
        tmp_path, n_display=3, include_no_display=False,
    )
    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=False, apply_to_remaining=True,
    )
    before_views = len(mw.view_manager.views)
    mw._open_data_paths([str(path) for path in batch.ordered_paths])
    qapp.processEvents()

    assert len(asked) == 1, (
        "remembered data-only choice must apply to remaining WWTs; "
        f"asked {len(asked)} times, want 1"
    )
    assert len(mw.files) == 3
    assert _winwert_view_count(mw) == 0
    assert len(mw.view_manager.views) == before_views


def test_new_open_data_paths_asks_again_after_remembered_batch(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """Batch memory is one ``_open_data_paths()`` call; the next open asks again.

    Hits ``end_open_batch()`` in ``_open_data_paths`` finally. Currently green.
    """
    first = wwt.batch_choice_set(
        tmp_path / "first", n_display=3, include_no_display=False,
    )
    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=True, apply_to_remaining=True,
    )
    mw._open_data_paths([str(path) for path in first.ordered_paths])
    qapp.processEvents()
    first_asks = len(asked)

    second = wwt.batch_choice_set(
        tmp_path / "second", n_display=1, include_no_display=False,
    )
    asked.clear()
    mw._open_data_paths([str(path) for path in second.ordered_paths])
    qapp.processEvents()

    assert (first_asks, len(asked)) == (1, 1), (
        "first batch with remember must ask once; a new _open_data_paths() "
        f"must ask again. got first={first_asks}, second={len(asked)}"
    )


def test_no_display_wwt_does_not_count_as_first_ask_source(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """No-display WWT loads data but does not establish or consume the decision.

    Currently green: T3 treats no-proposal WWT as NOT_APPLICABLE.
    """
    batch = wwt.batch_choice_set(
        tmp_path, n_display=2, include_no_display=True, no_display_at=0,
    )
    assert batch.no_display_path is not None
    assert batch.ordered_paths[0] == batch.no_display_path

    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=True, apply_to_remaining=True,
    )
    mw._open_data_paths([str(path) for path in batch.ordered_paths])
    qapp.processEvents()

    assert len(asked) == 1, (
        "no-display WWT must not be the first ask source, and must not "
        "consume a remembered decision; remaining display WWTs share one "
        f"ask. asked {len(asked)} times, want 1"
    )
    assert len(mw.files) >= 3
    assert _winwert_view_count(mw) == 2


def test_raw_bool_true_does_not_remember_for_remaining(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """A raw bool still means apply_to_remaining=False (non-regression)."""
    batch = wwt.batch_choice_set(
        tmp_path, n_display=3, include_no_display=False,
    )
    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=True, raw_bool=True,
    )
    mw._open_data_paths([str(path) for path in batch.ordered_paths])
    qapp.processEvents()

    assert len(asked) == 3
    assert _winwert_view_count(mw) == 3


def test_project_restore_asks_zero_times_via_restoring_project_seam(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """Restore is not a user open batch; dialog must stay at 0.

    Hits the production ``_restoring_project`` / ``offer_layout`` skip in
    ``_load_one``, not a local fake of that flag alone.
    """
    batch = wwt.batch_choice_set(
        tmp_path / "src", n_display=1, include_no_display=False,
    )
    mw, asked = _make_window(
        qapp, qtbot, monkeypatch, accepted=True, apply_to_remaining=False,
    )
    mw._open_data_paths([str(path) for path in batch.ordered_paths])
    qapp.processEvents()
    assert asked, "precondition: first open must offer layout"
    proj = tmp_path / "wwt-batch.tlproj"
    assert mw.save_project(proj) is True

    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.show()
    qapp.processEvents()
    restore_asks = []
    restoring_flags = []

    def fail_if_asked(*_a, **_k):
        restore_asks.append(True)
        pytest.fail("layout dialog must not run during project restore")

    real_load = restored._load_one

    def _load_one_recording(fp, **kwargs):
        restoring_flags.append(bool(getattr(restored, "_restoring_project", False)))
        return real_load(fp, **kwargs)

    monkeypatch.setattr(restored._wwt_import, "_ask_layout", fail_if_asked)
    monkeypatch.setattr(restored, "_load_one", _load_one_recording)
    monkeypatch.setattr(restored, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(restored, "_apply_active_view", lambda *a, **k: None)
    restored.open_project(proj)
    qapp.processEvents()

    assert restore_asks == []
    assert True in restoring_flags, (
        "restore must load WWT while _restoring_project is True so "
        "offer_layout / _ask_layout stay skipped"
    )
    assert restored.files


def test_optional_customer_sfns_batch_skip_if_missing(tmp_path):
    """Customer testdoc SFNS files are optional smoke, never a hard fail."""
    sample_dir = _ROOT / "testdoc" / "2024_3_17"
    matches = sorted(sample_dir.glob("SFNS_*.wwt")) if sample_dir.is_dir() else []
    if len(matches) < 2:
        pytest.skip("customer testdoc/2024_3_17/SFNS_*.wwt missing")
    assert all(path.is_file() for path in matches[:2])
