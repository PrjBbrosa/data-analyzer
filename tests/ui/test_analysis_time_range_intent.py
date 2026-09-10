"""Focused tests for analysis time-range intent (Step 1).

No MainWindow. The controller is a data + callback collaborator; full
bounds come from an injected provider or from FileData.time_array first/last.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.ui.main_window.analysis_context import AnalysisContext
from mf4_analyzer.ui.main_window.analysis_time_range import (
    AnalysisTimeRangeController,
    SourceBounds,
    axis_extent,
    axis_facts_from_files,
    bounds_from_axes,
    display_ranges_equal,
    make_source_signature,
    order_rpm_alignment_hook,
    validate_requested_span,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT / "mf4_analyzer" / "ui" / "main_window" / "analysis_time_range.py"
)

SIG_A = ("sig-a",)
SIG_B = ("sig-b",)
FULL = (0.0, 55.29)
PANE = ("fft", "view-a", 0)


def _imports_of(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    ]


def _bounds(display, per_source=None, status="ok", notes=(), errors=()):
    return SourceBounds(
        status=status,
        display_range=display,
        per_source=dict(per_source or {}),
        notes=tuple(notes),
        errors=tuple(errors),
    )


def _controller(display=FULL, per_source=None, status="ok"):
    holder = {
        "bounds": _bounds(
            display,
            per_source if per_source is not None else {("f1", "sig"): display},
            status=status,
        )
    }

    def provider(_section, _view_id, _pane_index):
        return holder["bounds"]

    ctrl = AnalysisTimeRangeController(bounds_provider=provider)
    ctrl._bounds_holder = holder  # test seam: swap live source facts
    return ctrl


def _intent(ctrl, enabled_range=None, source_signature=SIG_A, pane=PANE):
    return ctrl.intent_for(
        *pane, enabled_range=enabled_range, source_signature=source_signature,
    )


# -- import / layering -------------------------------------------------------

def test_intent_module_and_tests_need_no_main_window_or_qt():
    test_imports = _imports_of(Path(__file__))
    assert not [line for line in test_imports if "MainWindow" in line]
    assert not [line for line in test_imports if "main_window.window" in line]
    assert not [line for line in test_imports if line.endswith("import main_window")]
    assert not [line for line in test_imports if "PyQt5" in line]

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("PyQt5", "mf4_analyzer.ui.main_window.window", "MainWindow")
    assert not [
        name
        for name in imported
        if any(name == item or name.startswith(item + ".") for item in forbidden)
        or name.endswith("window")
    ]


# -- full / draft / enabled / programmatic -----------------------------------

def test_fresh_pane_is_full_and_programmatic_span_is_not_a_draft():
    ctrl = _controller()
    intent = _intent(ctrl)
    assert intent.kind == "full"
    assert intent.range is None
    assert intent.display_range == FULL
    assert intent.draft is None
    assert ctrl.draft_for(*PANE) is None


def test_apply_user_edit_creates_draft_when_span_differs_from_full():
    ctrl = _controller()
    returned = ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    assert returned.kind == "draft"
    draft = ctrl.draft_for(*PANE)
    assert draft is not None
    assert draft.range == (10.0, 20.0)
    assert draft.source_signature == SIG_A
    assert draft.origin == "user_edit"
    intent = _intent(ctrl)
    assert intent.kind == "draft"
    assert intent.range == (10.0, 20.0)
    assert intent.draft is draft


def test_user_edit_equal_to_full_within_display_tol_stays_full():
    ctrl = _controller()
    # 3-decimal spinbox quantization: 0.0004 s < 0.0005 s endpoint tol.
    intent = ctrl.apply_user_edit(*PANE, (0.0, 55.2904), SIG_A)
    assert intent.kind == "full"
    assert ctrl.draft_for(*PANE) is None


def test_one_hour_minus_one_second_is_still_a_local_draft():
    hour = (0.0, 3600.0)
    ctrl = _controller(display=hour, per_source={("f1", "sig"): hour})
    intent = ctrl.apply_user_edit(*PANE, (0.0, 3599.0), SIG_A)
    assert intent.kind == "draft"
    assert intent.range == (0.0, 3599.0)
    # Old 1% rule would swallow 36 s; 1 s must remain local.
    assert not display_ranges_equal((0.0, 3599.0), hour)


def test_display_tolerance_rejects_one_millisecond_beyond_half_ms():
    ctrl = _controller(display=(0.0, 10.0), per_source={("f1", "sig"): (0.0, 10.0)})
    assert ctrl.apply_user_edit(*PANE, (0.0, 10.0004), SIG_A).kind == "full"
    assert ctrl.apply_user_edit(*PANE, (0.0, 10.001), SIG_A).kind == "draft"


def test_note_enabled_clears_draft_and_reports_enabled():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    noted = ctrl.note_enabled(*PANE, (10.0, 20.0), SIG_A)
    assert noted.kind == "enabled"
    assert noted.range == (10.0, 20.0)
    assert ctrl.draft_for(*PANE) is None
    intent = _intent(ctrl, enabled_range=(10.0, 20.0))
    assert intent.kind == "enabled"
    assert intent.range == (10.0, 20.0)
    assert intent.needs_review is False


def test_convert_to_full_clears_draft_and_review():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    ctrl.on_source_signature_changed(
        *PANE, SIG_B, enabled_range=(10.0, 20.0),
    )
    cleared = ctrl.convert_to_full(*PANE)
    assert cleared.kind == "full"
    assert ctrl.draft_for(*PANE) is None
    assert _intent(ctrl).needs_review is False


def test_clear_draft_returns_full_when_nothing_is_enabled():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (1.0, 2.0), SIG_A)
    ctrl.clear_draft(*PANE)
    assert _intent(ctrl).kind == "full"
    assert ctrl.draft_for(*PANE) is None


# -- invalid / unavailable (must not become full via normalize) ---------------

def test_invalid_draft_is_not_normalized_to_full():
    ctrl = _controller()
    inverted = (20.0, 10.0)
    assert AnalysisContext.normalize_time_range(inverted) is None
    intent = ctrl.apply_user_edit(*PANE, inverted, SIG_A)
    assert intent.kind == "invalid"
    draft = ctrl.draft_for(*PANE)
    assert draft is not None
    assert draft.range == inverted
    assert _intent(ctrl).kind == "invalid"


@pytest.mark.parametrize(
    "span",
    [
        (float("nan"), 1.0),
        (0.0, float("inf")),
        (3.0, 3.0),
        ("a", "b"),
        (1.0,),
    ],
)
def test_nonfinite_or_unparseable_edit_is_invalid_not_full(span):
    ctrl = _controller()
    assert AnalysisContext.normalize_time_range(span) is None
    intent = ctrl.apply_user_edit(*PANE, span, SIG_A)
    assert intent.kind == "invalid"
    assert _intent(ctrl).kind != "full"


def test_none_span_is_invalid_draft_without_forged_range():
    ctrl = _controller()
    intent = ctrl.apply_user_edit(*PANE, None, SIG_A)
    assert intent.kind == "invalid"
    assert intent.range is None
    draft = ctrl.draft_for(*PANE)
    assert draft is not None
    assert draft.valid is False
    assert draft.range is None


def test_invalid_draft_is_visible_over_enabled_range():
    ctrl = _controller()
    ctrl.note_enabled(*PANE, (0.0, 10.0), SIG_A)
    intent = ctrl.apply_user_edit(*PANE, None, SIG_A)
    assert intent.kind == "invalid"
    assert _intent(ctrl, enabled_range=(0.0, 10.0)).kind == "invalid"


def test_invalid_enabled_is_not_silently_full():
    ctrl = _controller()
    bad = (5.0, 1.0)
    assert AnalysisContext.normalize_time_range(bad) is None
    noted = ctrl.note_enabled(*PANE, bad, SIG_A)
    assert noted.kind == "invalid"
    intent = _intent(ctrl, enabled_range=bad)
    assert intent.kind == "invalid"
    assert intent.range == bad


def test_missing_source_is_unavailable_and_does_not_reuse_prior_display():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    ctrl._bounds_holder["bounds"] = _bounds(
        None, {}, status="unavailable", errors=("missing:('f1', 'sig')",),
    )
    intent = _intent(ctrl)
    assert intent.kind == "unavailable"
    assert intent.display_range is None


# -- source signatures -------------------------------------------------------

def _axis_fact(t0, t1, n, *, source_token="fd", axis_revision=1, axis_token="ax"):
    """Fakes must supply tokens explicitly; no silent 0/False padding."""
    return (float(t0), float(t1), int(n), source_token, axis_revision, axis_token)


def test_source_signature_ignores_source_list_order():
    facts = {
        ("f1", "a"): _axis_fact(0.0, 10.0, 100, source_token="a", axis_token="ta"),
        ("f2", "b"): _axis_fact(0.0, 12.0, 120, source_token="b", axis_token="tb"),
    }
    left = make_source_signature(
        "fft", sources=[("f2", "b"), ("f1", "a")], axis_facts=facts,
    )
    right = make_source_signature(
        "fft", sources=[("f1", "a"), ("f2", "b")], axis_facts=facts,
    )
    assert left == right


def test_source_signature_changes_with_channel_axis_or_frf_direction():
    facts_short = {("f1", "sig"): _axis_fact(0.0, 10.0, 100)}
    facts_long = {("f1", "sig"): _axis_fact(0.0, 20.0, 200)}
    assert make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts=facts_short,
    ) != make_source_signature(
        "fft", sources=[("f1", "other")], axis_facts=facts_short,
    )
    assert make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts=facts_short,
    ) != make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts=facts_long,
    )
    io_facts = {
        ("f1", "in"): _axis_fact(0.0, 10.0, 100, source_token="in", axis_token="tin"),
        ("f1", "out"): _axis_fact(0.0, 10.0, 100, source_token="out", axis_token="tout"),
    }
    assert make_source_signature(
        "frf",
        input_source=("f1", "in"),
        output_source=("f1", "out"),
        axis_facts=io_facts,
    ) != make_source_signature(
        "frf",
        input_source=("f1", "out"),
        output_source=("f1", "in"),
        axis_facts=io_facts,
    )


def test_order_signature_includes_rpm_mode_and_source():
    facts = {("f1", "sig"): _axis_fact(0.0, 10.0, 100)}
    channel = make_source_signature(
        "order",
        sources=[("f1", "sig")],
        rpm_mode="channel",
        rpm_source=("f1", "rpm"),
        axis_facts=facts,
    )
    manual = make_source_signature(
        "order",
        sources=[("f1", "sig")],
        rpm_mode="manual",
        rpm_source=None,
        axis_facts=facts,
    )
    other_rpm = make_source_signature(
        "order",
        sources=[("f1", "sig")],
        rpm_mode="channel",
        rpm_source=("f1", "rpm2"),
        axis_facts=facts,
    )
    assert channel != manual
    assert channel != other_rpm


def test_same_extent_axis_revision_or_instance_changes_signature():
    base = _axis_fact(0.0, 10.0, 100, source_token="fd-a", axis_revision=1, axis_token="ax-1")
    same_extent = _axis_fact(0.0, 10.0, 100, source_token="fd-a", axis_revision=2, axis_token="ax-1")
    replaced_axis = _axis_fact(0.0, 10.0, 100, source_token="fd-a", axis_revision=1, axis_token="ax-2")
    replaced_source = _axis_fact(0.0, 10.0, 100, source_token="fd-b", axis_revision=1, axis_token="ax-1")
    left = make_source_signature("fft", sources=[("f1", "sig")], axis_facts={("f1", "sig"): base})
    assert left != make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts={("f1", "sig"): same_extent},
    )
    assert left != make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts={("f1", "sig"): replaced_axis},
    )
    assert left != make_source_signature(
        "fft", sources=[("f1", "sig")], axis_facts={("f1", "sig"): replaced_source},
    )


def test_axis_facts_require_explicit_tokens_and_do_not_pad():
    with pytest.raises(ValueError, match="explicit"):
        make_source_signature(
            "fft",
            sources=[("f1", "sig")],
            axis_facts={("f1", "sig"): (0.0, 10.0, 100)},
        )
    with pytest.raises(ValueError, match="explicit"):
        make_source_signature(
            "fft",
            sources=[("f1", "sig")],
            axis_facts={
                ("f1", "sig"): {"t0": 0.0, "t1": 10.0, "n": 100},
            },
        )


def test_validate_requested_span_is_shared_for_draft_and_enabled():
    per_source = {("f1", "sig"): (0.0, 10.0)}
    covered = validate_requested_span(per_source, (2.0, 4.0))
    assert covered.ok is True
    assert covered.reason == "ok"
    assert covered.span == (2.0, 4.0)

    outside = validate_requested_span(per_source, (20.0, 30.0))
    assert outside.ok is False
    assert outside.reason == "uncovered"
    assert outside.span == (20.0, 30.0)
    assert outside.errors

    partial = validate_requested_span(per_source, (5.0, 15.0))
    assert partial.ok is False
    assert partial.reason == "uncovered"

    inverted = validate_requested_span(per_source, (8.0, 2.0))
    assert inverted.ok is False
    assert inverted.reason == "unordered"
    assert inverted.span == (8.0, 2.0)

    missing = validate_requested_span({}, (2.0, 4.0), bounds_status="unavailable")
    assert missing.ok is False
    assert missing.reason == "unavailable"

    overlay = {
        ("f1", "a"): (0.0, 10.0),
        ("f2", "b"): (20.0, 30.0),
    }
    envelope_local = validate_requested_span(overlay, (8.0, 22.0))
    assert envelope_local.ok is False
    assert envelope_local.reason == "uncovered"


def test_draft_out_of_coverage_keeps_parse_valid_and_reports_errors():
    ctrl = _controller(
        display=(0.0, 10.0), per_source={("f1", "sig"): (0.0, 10.0)},
    )
    intent = ctrl.apply_user_edit(*PANE, (20.0, 30.0), SIG_A)
    assert intent.kind == "draft"
    draft = ctrl.draft_for(*PANE)
    assert draft is not None
    assert draft.valid is True
    assert draft.range == (20.0, 30.0)
    assert intent.errors
    assert any("cover" in str(err) for err in intent.errors)


def test_axis_facts_from_files_record_explicit_none_not_zero():
    class _Bare:
        def __init__(self, axis):
            self.time_array = np.asarray(axis, dtype=float)

    class _Complete:
        def __init__(self, axis):
            self.time_array = np.asarray(axis, dtype=float)
            self.time_axis_revision = 4
            self.source_instance_token = "token-a"

    bare = _Bare([0.0, 10.0])
    complete = _Complete([0.0, 10.0])
    facts = axis_facts_from_files(
        {"bare": bare, "full": complete},
        [("bare", "sig"), ("full", "sig")],
    )
    bare_fact = facts[("bare", "sig")]
    full_fact = facts[("full", "sig")]
    assert bare_fact[0] == 0.0
    assert bare_fact[1] == 10.0
    assert bare_fact[2] == 2
    assert bare_fact[3] == id(bare)
    assert bare_fact[4] is None
    assert bare_fact[4] is not False
    assert bare_fact[4] != 0
    assert bare_fact[5] == id(bare.time_array)
    assert full_fact[3] == "token-a"
    assert full_fact[4] == 4
    assert full_fact[5] == id(complete.time_array)


def test_same_signature_does_not_clear_draft():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    ctrl.on_source_signature_changed(*PANE, SIG_A)
    assert ctrl.draft_for(*PANE) is not None
    assert _intent(ctrl).kind == "draft"


def test_signature_change_discards_draft_and_does_not_revive_on_return():
    ctrl = _controller()
    ctrl.apply_user_edit(*PANE, (10.0, 20.0), SIG_A)
    changed = ctrl.on_source_signature_changed(*PANE, SIG_B)
    assert changed.kind == "full"
    assert ctrl.draft_for(*PANE) is None
    ctrl.on_source_signature_changed(*PANE, SIG_A)
    assert ctrl.draft_for(*PANE) is None
    assert _intent(ctrl).kind == "full"


def test_enabled_out_of_coverage_needs_review_without_clamping():
    ctrl = _controller()
    ctrl.note_enabled(*PANE, (10.0, 20.0), SIG_A)
    ctrl._bounds_holder["bounds"] = _bounds(
        (0.0, 5.0), {("f2", "sig"): (0.0, 5.0)},
    )
    changed = ctrl.on_source_signature_changed(
        *PANE, SIG_B, enabled_range=(10.0, 20.0),
    )
    assert changed.kind == "enabled"
    assert changed.needs_review is True
    assert changed.range == (10.0, 20.0)
    later = _intent(ctrl, enabled_range=(10.0, 20.0), source_signature=SIG_B)
    assert later.needs_review is True
    assert later.range == (10.0, 20.0)


def test_enabled_still_covered_by_new_source_stays_quiet():
    ctrl = _controller()
    ctrl.note_enabled(*PANE, (10.0, 20.0), SIG_A)
    ctrl._bounds_holder["bounds"] = _bounds(
        (0.0, 80.0), {("f2", "sig"): (0.0, 80.0)},
    )
    changed = ctrl.on_source_signature_changed(
        *PANE, SIG_B, enabled_range=(10.0, 20.0),
    )
    assert changed.needs_review is False
    assert changed.range == (10.0, 20.0)


def test_overlay_gap_does_not_count_as_coverage():
    """Envelope 0–30 must not hide a 12–18 window that no source covers."""
    ctrl = AnalysisTimeRangeController(
        bounds_provider=lambda *_: _bounds(
            (0.0, 30.0),
            {("f1", "a"): (0.0, 10.0), ("f2", "b"): (20.0, 30.0)},
            notes=("各信号使用自身全时段",),
        )
    )
    changed = ctrl.on_source_signature_changed(
        *PANE, SIG_B, enabled_range=(12.0, 18.0),
    )
    assert changed.needs_review is True
    assert changed.range == (12.0, 18.0)


# -- lifecycle isolation -----------------------------------------------------

def test_drafts_are_isolated_by_section_view_and_pane():
    ctrl = _controller()
    ctrl.apply_user_edit("fft", "view-a", 0, (1.0, 2.0), SIG_A)
    ctrl.apply_user_edit("fft", "view-a", 1, (3.0, 4.0), SIG_A)
    ctrl.apply_user_edit("fft", "view-b", 0, (5.0, 6.0), SIG_A)
    ctrl.apply_user_edit("order", "view-a", 0, (7.0, 8.0), SIG_A)
    assert ctrl.draft_for("fft", "view-a", 0).range == (1.0, 2.0)
    assert ctrl.draft_for("fft", "view-a", 1).range == (3.0, 4.0)
    assert ctrl.draft_for("fft", "view-b", 0).range == (5.0, 6.0)
    assert ctrl.draft_for("order", "view-a", 0).range == (7.0, 8.0)


def test_copy_view_does_not_copy_drafts():
    ctrl = _controller()
    ctrl.apply_user_edit("fft", "original", 0, (1.0, 2.0), SIG_A)
    assert ctrl.draft_for("fft", "copy", 0) is None
    assert ctrl.intent_for("fft", "copy", 0).kind == "full"


def test_clear_pane_view_and_all():
    ctrl = _controller()
    ctrl.apply_user_edit("fft", "v1", 0, (1.0, 2.0), SIG_A)
    ctrl.apply_user_edit("fft", "v1", 1, (3.0, 4.0), SIG_A)
    ctrl.apply_user_edit("fft", "v2", 0, (5.0, 6.0), SIG_A)
    ctrl.apply_user_edit("order", "v1", 0, (7.0, 8.0), SIG_A)
    ctrl.clear_pane("fft", "v1", 0)
    assert ctrl.draft_for("fft", "v1", 0) is None
    assert ctrl.draft_for("fft", "v1", 1) is not None
    ctrl.clear_view("fft", "v1")
    assert ctrl.draft_for("fft", "v1", 1) is None
    assert ctrl.draft_for("fft", "v2", 0) is not None
    ctrl.clear_all()
    assert ctrl.draft_for("fft", "v2", 0) is None
    assert ctrl.draft_for("order", "v1", 0) is None


# -- physical bounds from time axes ------------------------------------------

def test_axis_extent_keeps_nonzero_and_negative_t0():
    assert axis_extent(None) is None
    assert axis_extent(np.array([])) is None
    assert axis_extent(np.array([3.5])) == (3.5, 3.5)
    assert axis_extent(np.array([4.0, 5.0, 6.0])) == (4.0, 6.0)
    assert axis_extent(np.array([-2.0, -1.0, 0.5])) == (-2.0, 0.5)


def test_fft_overlay_keeps_per_source_ranges_and_envelope():
    bounds = bounds_from_axes(
        "fft",
        (
            (("f1", "a"), np.array([0.0, 10.0])),
            (("f2", "b"), np.array([5.0, 20.0])),
        ),
    )
    assert bounds.status == "ok"
    assert bounds.display_range == (0.0, 20.0)
    assert bounds.per_source[("f1", "a")] == (0.0, 10.0)
    assert bounds.per_source[("f2", "b")] == (5.0, 20.0)
    assert "各信号使用自身全时段" in bounds.notes


def test_partial_overlay_marks_missing_source_instead_of_claiming_all():
    bounds = bounds_from_axes(
        "fft",
        (
            (("f1", "a"), np.array([0.0, 10.0])),
            (("f2", "b"), None),
        ),
    )
    assert bounds.status == "partial"
    assert bounds.status != "ok"
    assert bounds.per_source[("f2", "b")] is None
    assert bounds.errors
    assert any("f2" in str(err) for err in bounds.errors)


def test_frf_common_range_uses_untrimmed_axes():
    bounds = bounds_from_axes(
        "frf",
        (
            (("f1", "in"), np.linspace(0.0, 10.0, 11)),
            (("f1", "out"), np.linspace(2.0, 12.0, 11)),
        ),
    )
    assert bounds.status == "ok"
    assert bounds.display_range == pytest.approx((2.0, 10.0))
    assert bounds.per_source[("f1", "in")] == pytest.approx((0.0, 10.0))
    assert bounds.per_source[("f1", "out")] == pytest.approx((2.0, 12.0))


def test_order_full_bounds_are_signal_axis_not_rpm_intersection():
    signal = np.array([0.0, 10.0])
    rpm = np.array([2.0, 8.0])
    bounds = bounds_from_axes("order", ((("f1", "sig"), signal),))
    assert bounds.display_range == (0.0, 10.0)
    assert order_rpm_alignment_hook(rpm, bounds.display_range) is None
    assert bounds.display_range != (2.0, 8.0)


def test_empty_axis_is_unavailable():
    bounds = bounds_from_axes("fft_time", ((("f1", "sig"), np.array([])),))
    assert bounds.status == "unavailable"
    assert bounds.display_range is None


# -- AnalysisContext wiring --------------------------------------------------

class _Editor:
    def value(self):
        return 1.0


class _DbControl:
    def __init__(self):
        self.editor = _Editor()

    def mode(self):
        return "auto"


class _SectionCtx:
    def __init__(self):
        self.db_reference_control = _DbControl()


class _Inspector:
    def __init__(self):
        self.fft_ctx = _SectionCtx()
        self.fft_time_ctx = _SectionCtx()
        self.frf_ctx = _SectionCtx()
        self.order_ctx = _SectionCtx()


class _Page:
    def focused_index(self):
        return 0


class _ChartStack:
    def __init__(self):
        self.page_fft = _Page()
        self.page_fft_time = _Page()
        self.page_frf = _Page()
        self.page_order = _Page()


class _FileData:
    def __init__(self, time_array, *, time_axis_revision=1, source_instance_token=None):
        self.time_array = np.asarray(time_array, dtype=float)
        self.time_axis_revision = int(time_axis_revision)
        self.source_instance_token = (
            source_instance_token if source_instance_token is not None else object()
        )


class _Pane:
    def __init__(
        self,
        sources=None,
        time_range=None,
        input_source=None,
        output_source=None,
        rpm_source=None,
    ):
        self.sources = list(sources or [])
        self.time_range = time_range
        self.input_source = input_source
        self.output_source = output_source
        self.rpm_source = rpm_source


class _View:
    def __init__(self, view_id, panes):
        self.view_id = view_id
        self.panes = list(panes)


class _Manager:
    def __init__(self, views):
        self.views = list(views)
        self.active = 0

    def get(self, idx):
        return self.views[idx]


class _Store:
    def snapshot(self):
        from mf4_analyzer.ui.db_reference_settings import DbReferenceCatalogSnapshot
        from mf4_analyzer import db_reference

        return DbReferenceCatalogSnapshot(
            system_catalog=db_reference.FACTORY_CATALOG_V1,
            user_catalog=(),
            prefer_channel_metadata=True,
            revision=1,
        )


def _context(files, managers):
    return AnalysisContext(
        inspector=_Inspector(),
        chart_stack=_ChartStack(),
        analysis_managers=managers,
        db_reference_store=_Store(),
        files_provider=lambda: files,
    )


def test_context_holds_one_controller_and_reads_pane_file_not_longest():
    files = {
        "short": _FileData([0.0, 10.0]),
        "long": _FileData([0.0, 99.0]),
    }
    pane = _Pane(sources=[("short", "sig")])
    managers = {
        "fft": _Manager([_View("view-short", [pane])]),
        "fft_time": _Manager([_View("other", [_Pane()])]),
        "frf": _Manager([_View("other", [_Pane()])]),
        "order": _Manager([_View("other", [_Pane()])]),
    }
    ctx = _context(files, managers)
    assert isinstance(ctx.time_range, AnalysisTimeRangeController)
    assert ctx.time_range is ctx.time_range
    bounds = ctx.source_bounds_for("fft", "view-short", 0)
    assert bounds.display_range == (0.0, 10.0)
    assert bounds.per_source[("short", "sig")] == (0.0, 10.0)
    missing = ctx.source_bounds_for("fft", "no-such-view", 0)
    assert missing.status == "unavailable"


# -- Step 2: shared Inspector widget + silent projection ---------------------

def _emit_spin_text_edited(spin, text=None):
    edit = spin.lineEdit()
    if edit is None:
        return
    if text is not None:
        edit.setText(text)
    edit.textEdited.emit(edit.text())


def _user_commit_range(top, lo, hi):
    """Simulate a typed start/end commit without going through set_range_values."""
    top.spin_start.setValue(float(lo))
    top.spin_end.setValue(float(hi))
    _emit_spin_text_edited(top.spin_start)
    _emit_spin_text_edited(top.spin_end)
    return top.flush_pending_range_edit(emit=True)


def test_range_edited_emits_only_for_real_user_commits(qapp):
    from mf4_analyzer.ui.inspector_sections.persistent_top import PersistentTop

    top = PersistentTop()
    seen = []
    top.range_edited.connect(lambda lo, hi: seen.append((lo, hi)))

    top.set_range_values(1.0, 2.0)
    top.set_range_limits(0.0, 10.0)
    top.checkout_range_for_mode("fft")
    top.set_range_from_span(3.0, 4.0)
    assert seen == []
    assert top.range_values() == (3.0, 4.0)
    assert top.range_enabled() is True

    top.chk_range.setChecked(False)
    top.set_range_values(0.0, 10.0)
    top.spin_start.editingFinished.emit()
    top.spin_end.editingFinished.emit()
    assert seen == []

    pending = _user_commit_range(top, 1.25, 8.5)
    assert pending == pytest.approx((1.25, 8.5))
    assert seen == [pytest.approx((1.25, 8.5))]


def test_flush_pending_range_edit_commits_line_edit_before_compute(qapp):
    from mf4_analyzer.ui.inspector_sections.persistent_top import PersistentTop

    top = PersistentTop()
    top.set_range_values(0.0, 1.0)
    seen = []
    top.range_edited.connect(lambda lo, hi: seen.append((lo, hi)))
    _emit_spin_text_edited(top.spin_end, "2.500")
    pending = top.flush_pending_range_edit(emit=True)
    assert top.spin_end.value() == pytest.approx(2.5)
    assert pending == pytest.approx((0.0, 2.5))
    assert seen == [pytest.approx((0.0, 2.5))]
    assert top.flush_pending_range_edit(emit=True) is None


def test_query_range_edit_distinguishes_unchanged_valid_and_invalid(qapp):
    from mf4_analyzer.ui.inspector_sections.persistent_top import (
        PersistentTop,
        RangeEditQuery,
    )

    top = PersistentTop()
    top.set_range_values(0.0, 10.0)
    query = top.query_range_edit()
    assert query.status == RangeEditQuery.UNCHANGED
    assert query.span is None

    _emit_spin_text_edited(top.spin_start, "2.0")
    _emit_spin_text_edited(top.spin_end, "4.0")
    query = top.query_range_edit()
    assert query.status == RangeEditQuery.VALID_EDIT
    assert query.span == pytest.approx((2.0, 4.0))
    revision = query.revision
    assert revision > 0

    top.set_range_values(0.0, 10.0)
    _emit_spin_text_edited(top.spin_start, "-")
    query = top.query_range_edit()
    assert query.status == RangeEditQuery.INVALID_EDIT
    assert query.span is None
    assert query.revision != revision
    assert "-" in query.start_text


def test_flush_same_revision_is_idempotent_and_unedited_focus_out_is_quiet(qapp):
    from mf4_analyzer.ui.inspector_sections.persistent_top import PersistentTop

    top = PersistentTop()
    seen = []
    invalid = []
    top.range_edited.connect(lambda lo, hi: seen.append((lo, hi)))
    top.range_edit_invalid.connect(lambda: invalid.append(True))
    top.set_range_values(0.0, 10.0)
    top.spin_start.editingFinished.emit()
    top.spin_end.editingFinished.emit()
    assert seen == []
    assert invalid == []
    assert top.query_range_edit().status == "unchanged"

    _emit_spin_text_edited(top.spin_end, "2.500")
    first = top.flush_pending_range_edit(emit=True)
    second = top.flush_pending_range_edit(emit=True)
    assert first == pytest.approx((0.0, 2.5))
    assert second is None
    assert seen == [pytest.approx((0.0, 2.5))]
    assert invalid == []

    _emit_spin_text_edited(top.spin_start, "-")
    assert top.flush_pending_range_edit(emit=True) is None
    assert top.flush_pending_range_edit(emit=True) is None
    assert invalid == [True]
    assert "-" in top.spin_start.lineEdit().text()
    assert not top.spin_start.hasAcceptableInput()


def test_programmatic_set_range_values_does_not_apply_user_edit(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("fft")
    win.inspector.set_mode("fft")
    calls = []
    real = win._analysis_context.time_range.apply_user_edit

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    win._analysis_context.time_range.apply_user_edit = spy
    win.inspector.top.set_range_values(1.0, 2.0)
    win.inspector.top.set_range_limits(0.0, 10.0)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert calls == []
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_apply_none_projects_source_display_range_not_stale_spin(qapp, qtbot):
    import pandas as pd

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    stale = np.linspace(0.0, 43.061, 431)
    live = np.linspace(0.0, 55.29, 553)
    win.files["stale"] = FileData(
        "stale.csv",
        pd.DataFrame({"sig": np.sin(stale)}),
        ["sig"],
        {},
        fs=10.0,
    )
    win.files["stale"].time_array = stale
    win.files["live"] = FileData(
        "live.csv",
        pd.DataFrame({"sig": np.sin(live)}),
        ["sig"],
        {},
        fs=10.0,
    )
    win.files["live"].time_array = live
    win.toolbar._set_mode("fft")
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [("live", "sig")]
    state.panes[0].time_range = None
    top = win.inspector.top
    top.set_range_limits(0.0, 43.061)
    top.set_range_values(0.0, 43.061)
    win._apply_analysis_time_range("fft", state)
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((0.0, 55.29), abs=1e-6)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_fft_preview_pan_does_not_create_draft_or_change_enabled(qapp, qtbot):
    import pandas as pd

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    time = np.linspace(0.0, 2.0, 200)
    win.files["src"] = FileData(
        "src.csv",
        pd.DataFrame({"sig": np.sin(time)}),
        ["sig"],
        {},
        fs=100.0,
    )
    win.files["src"].time_array = time
    win.toolbar._set_mode("fft")
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [("src", "sig")]
    top = win.inspector.top
    top.set_range_from_span(0.2, 0.8)
    win._capture_analysis_time_range("fft", state, pane_idx=0)
    assert state.panes[0].time_range == pytest.approx((0.2, 0.8))

    calls = []
    real = win._analysis_context.time_range.apply_user_edit

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    win._analysis_context.time_range.apply_user_edit = spy
    handled = win._on_fft_preview_range_changed(0, 0.4, 1.1)
    assert handled is True
    assert calls == []
    assert top.range_values() == pytest.approx((0.2, 0.8))
    assert state.panes[0].time_range == pytest.approx((0.2, 0.8))
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_pane_switch_projects_incoming_and_keeps_outgoing_draft(qapp, qtbot):
    import pandas as pd

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    time = np.linspace(0.0, 10.0, 100)
    win.files["src"] = FileData(
        "src.csv",
        pd.DataFrame({"sig": np.sin(time)}),
        ["sig"],
        {},
        fs=10.0,
    )
    win.files["src"].time_array = time
    win.toolbar._set_mode("fft")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("fft", ["src"])
    win.navigator.set_checked_channels([("src", "sig")])
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [("src", "sig")]
    state.panes[1].sources = [("src", "sig")]
    state.panes[0].time_range = None
    state.panes[1].time_range = None
    # This test owns time-range isolation; keep pane sources from being
    # rewritten by an empty navigator during focus capture.
    win._capture_analysis_sources = lambda *args, **kwargs: None
    page.set_focused_index(0)
    win._apply_analysis_time_range("fft", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ).range == pytest.approx((1.0, 2.0))

    page.set_focused_index(1)
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 10.0))
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 1
    ) is None
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ).range == pytest.approx((1.0, 2.0))

    page.set_focused_index(0)
    assert win.inspector.top.range_values() == pytest.approx((1.0, 2.0))
    assert win.inspector.top.range_enabled() is False


# -- Step 3: source lifecycle, restore, range review -------------------------

def _forbid_time_range_confirm(win, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("picking sources must not open the confirm dialog")

    monkeypatch.setattr(win, "_ask_use_local_time_range", boom)


def _register_span(win, name, duration, *, n=None, channel="sig"):
    import pandas as pd

    count = n if n is not None else max(int(duration * 10) + 1, 2)
    time = np.linspace(0.0, float(duration), count)
    frame = pd.DataFrame({channel: np.sin(time)})
    before = set(win.files)
    fd = win._register_file_data(
        f"{name}.csv",
        frame,
        [channel],
        {},
        fs=float(count - 1) / float(duration),
    )
    fd.time_array = time
    fid = next(item for item in win.files if item not in before)
    return fid, time


def _enter_fft(win, fids):
    win.toolbar._set_mode("fft")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("fft", list(fids))
    mgr = win.analysis_managers["fft"]
    win._project_analysis_attachments("fft", mgr.get(mgr.active))


def _tick_fft_sources(win, keys):
    win.navigator.set_checked_channels(list(keys))
    win._ch_changed()


def test_register_file_data_does_not_write_analysis_spin_end(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.toolbar._set_mode("fft")
    top = win.inspector.top
    before = top.range_values()
    _register_span(win, "first", 43.061, n=431)
    assert top.range_values() == pytest.approx(before)
    assert top.range_values() != pytest.approx((0.0, 43.061))
    assert top.spin_end.maximum() >= 43.061 - 1e-6


def test_two_filedata_no_user_edit_follows_new_source_full(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    short_fid, _short = _register_span(win, "short", 10.0, n=101)
    long_fid, _long = _register_span(win, "long", 55.29, n=553)
    _enter_fft(win, [short_fid, long_fid])
    _tick_fft_sources(win, [(short_fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    top = win.inspector.top
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((0.0, 10.0), abs=1e-6)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None

    _tick_fft_sources(win, [(long_fid, "sig")])
    assert top.range_enabled() is False
    assert top.range_values() == pytest.approx((0.0, 55.29), abs=1e-6)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None
    assert state.panes[0].time_range is None


def test_loading_unrelated_longer_file_does_not_change_current_pane_full(
    qapp, qtbot, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    short_fid, _short = _register_span(win, "short", 10.0, n=101)
    _enter_fft(win, [short_fid])
    _tick_fft_sources(win, [(short_fid, "sig")])
    top = win.inspector.top
    assert top.range_values() == pytest.approx((0.0, 10.0), abs=1e-6)
    _register_span(win, "unrelated", 99.0, n=991)
    assert top.range_values() == pytest.approx((0.0, 10.0), abs=1e-6)
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_draft_cleared_on_channel_replace_but_not_on_reorder(
    qapp, qtbot, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid_a, _ta = _register_span(win, "a", 10.0, n=101, channel="sig")
    fid_b, _tb = _register_span(win, "b", 12.0, n=121, channel="sig")
    _enter_fft(win, [fid_a, fid_b])
    _tick_fft_sources(win, [(fid_a, "sig"), (fid_b, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    ctrl = win._analysis_context.time_range
    assert ctrl.draft_for("fft", state.view_id, 0).range == pytest.approx((1.0, 2.0))

    _tick_fft_sources(win, [(fid_b, "sig"), (fid_a, "sig")])
    assert ctrl.draft_for("fft", state.view_id, 0) is not None
    assert ctrl.draft_for("fft", state.view_id, 0).range == pytest.approx((1.0, 2.0))

    _tick_fft_sources(win, [(fid_b, "sig")])
    assert ctrl.draft_for("fft", state.view_id, 0) is None
    assert win.inspector.top.range_values() == pytest.approx((0.0, 12.0), abs=1e-6)


def test_enabled_out_of_range_flagged_not_clamped(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    long_fid, _long = _register_span(win, "long", 30.0, n=301)
    short_fid, _short = _register_span(win, "short", 5.0, n=51)
    _enter_fft(win, [long_fid, short_fid])
    _tick_fft_sources(win, [(long_fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win.inspector.top.set_range_from_span(10.0, 20.0)
    win._capture_analysis_time_range("fft", state, pane_idx=0)
    assert state.panes[0].time_range == pytest.approx((10.0, 20.0))

    _tick_fft_sources(win, [(short_fid, "sig")])
    intent = win._analysis_context.time_range.intent_for(
        "fft", state.view_id, 0, enabled_range=state.panes[0].time_range,
    )
    assert state.panes[0].time_range == pytest.approx((10.0, 20.0))
    assert intent.kind == "enabled"
    assert intent.needs_review is True
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((10.0, 20.0))


def test_duplicate_view_copies_enabled_range_not_draft(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    original = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", original.view_id, 0
    ) is not None
    win._on_analysis_duplicate("fft", 0)
    copied = mgr.get(mgr.active)
    assert copied.view_id != original.view_id
    assert copied.panes[0].time_range is None
    assert win._analysis_context.time_range.draft_for(
        "fft", copied.view_id, 0
    ) is None
    assert win._analysis_context.time_range.draft_for(
        "fft", original.view_id, 0
    ) is not None

    mgr.set_active(0)
    original = mgr.get(0)
    win.inspector.top.set_range_from_span(3.0, 4.0)
    win._capture_analysis_time_range("fft", original, pane_idx=0)
    assert original.panes[0].time_range == pytest.approx((3.0, 4.0))
    win._on_analysis_duplicate("fft", 0)
    enabled_copy = mgr.get(mgr.active)
    assert enabled_copy.panes[0].time_range == pytest.approx((3.0, 4.0))
    assert win._analysis_context.time_range.draft_for(
        "fft", enabled_copy.view_id, 0
    ) is None


def test_close_view_and_clear_project_drops_drafts(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    first = mgr.get(0)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", first.view_id, 0
    ) is not None
    mgr.new_view()
    win._on_analysis_delete("fft", 0)
    assert win._analysis_context.time_range.draft_for(
        "fft", first.view_id, 0
    ) is None

    state = mgr.get(mgr.active)
    _tick_fft_sources(win, [(fid, "sig")])
    _user_commit_range(win.inspector.top, 2.0, 3.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None
    win.close()
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_split_clear_drops_second_pane_draft(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    page = win.chart_stack.page_fft
    page.set_focused_index(1)
    _tick_fft_sources(win, [(fid, "sig")])
    _user_commit_range(win.inspector.top, 1.5, 2.5)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 1
    ) is not None
    win._on_analysis_split("fft", False)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 1
    ) is None


def test_restored_none_projects_source_full(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fid, "sig")]
    state.panes[0].time_range = None
    win.inspector.top.set_range_values(0.0, 43.061)
    win._apply_analysis_time_range("fft", state)
    assert state.panes[0].time_range is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 10.0), abs=1e-6)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_corrupt_restored_tuple_stays_invalid_not_full(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fid, "sig")]
    inverted = (8.0, 2.0)
    state.panes[0].time_range = inverted
    win._apply_analysis_time_range("fft", state)
    assert state.panes[0].time_range == inverted
    intent = win._analysis_context.time_range.intent_for(
        "fft", state.view_id, 0, enabled_range=inverted,
    )
    assert intent.kind == "invalid"
    assert intent.kind != "full"


def test_same_extent_axis_replacement_invalidates_signature(qapp, qtbot):
    """Migrated review probe: (t0, t1, n) alone must not keep the signature."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    before = win._analysis_source_signature_for_pane("fft", pane, state)
    axis = win.files[fid].time_array.copy()
    axis[1] += 0.001
    win.files[fid].time_array = axis
    after = win._analysis_source_signature_for_pane("fft", pane, state)
    assert before != after


def test_source_instance_replacement_changes_signature(qapp, qtbot):
    import pandas as pd

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    fid, time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    before = win._analysis_source_signature_for_pane("fft", pane, state)
    replacement = FileData(
        "src.csv",
        pd.DataFrame({"sig": np.sin(time)}),
        ["sig"],
        {},
        fs=10.0,
    )
    replacement.time_array = np.asarray(time, dtype=float).copy()
    win.files[fid] = replacement
    after = win._analysis_source_signature_for_pane("fft", pane, state)
    assert before != after
    payload = state.to_dict()
    assert "time_axis_revision" not in payload
    assert "source_instance_token" not in payload["panes"][0]
    assert "source_signature" not in payload["panes"][0]


def test_serialized_views_omit_drafts_and_signatures(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    payload = state.to_dict()
    pane = payload["panes"][0]
    assert pane["time_range"] is None
    assert "draft" not in pane
    assert "source_signature" not in pane
    assert "needs_review" not in pane
    assert payload["schema"] == 9


def test_frf_input_output_swap_is_signature_change(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101, channel="in")
    import pandas as pd

    out_t = np.linspace(0.0, 10.0, 101)
    before = set(win.files)
    fd = win._register_file_data(
        "out.csv",
        pd.DataFrame({"out": np.cos(out_t)}),
        ["out"],
        {},
        fs=10.0,
    )
    fd.time_array = out_t
    out_fid = next(item for item in win.files if item not in before)
    win.toolbar._set_mode("frf")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("frf", [fid, out_fid])
    mgr = win.analysis_managers["frf"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    pane.input_source = (fid, "in")
    pane.output_source = (out_fid, "out")
    win._apply_analysis_time_range("frf", state)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is not None
    win._on_frf_pair_changed((out_fid, "out"), (fid, "in"))
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is None
    assert win.inspector.top.range_values() == pytest.approx((0.0, 10.0), abs=1e-6)


def test_order_rpm_change_is_signature_change(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101, channel="sig")
    import pandas as pd

    rpm_t = np.linspace(0.0, 10.0, 101)
    before = set(win.files)
    fd = win._register_file_data(
        "rpm.csv",
        pd.DataFrame({"rpm": np.ones_like(rpm_t), "rpm2": np.ones_like(rpm_t) * 2}),
        ["rpm", "rpm2"],
        {},
        fs=10.0,
    )
    fd.time_array = rpm_t
    rpm_fid = next(item for item in win.files if item not in before)
    win.toolbar._set_mode("order")
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach("order", [fid, rpm_fid])
    win._refresh_analysis_candidates("order")
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fid, "sig"))
    win._echo_combo_signal(ctx.combo_rpm, (rpm_fid, "rpm"))
    mgr = win.analysis_managers["order"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "order", state.view_id, 0
    ) is not None
    win._echo_combo_signal(ctx.combo_rpm, (rpm_fid, "rpm2"))
    assert win._analysis_context.time_range.draft_for(
        "order", state.view_id, 0
    ) is None
    ctx.set_rpm_mode("manual")
    win._on_analysis_compute_params_changed("order", ctx.compute_params())
    assert win._analysis_context.time_range.draft_for(
        "order", state.view_id, 0
    ) is None


def test_file_close_dropping_fid_invalidates_draft(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    keep_fid, _keep = _register_span(win, "keep", 10.0, n=101)
    drop_fid, _drop = _register_span(win, "drop", 8.0, n=81)
    _enter_fft(win, [keep_fid, drop_fid])
    _tick_fft_sources(win, [(drop_fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None
    win._close(keep_fid, force=True)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is not None
    win._close(drop_fid, force=True)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


def test_empty_workspace_reset_clears_all_drafts(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _forbid_time_range_confirm(win, monkeypatch)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    _user_commit_range(win.inspector.top, 1.0, 2.0)
    win._close(fid, force=True)
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0
    ) is None


# -- Step 4: compute preflight uses controller drafts, not spin heuristics --

def test_offer_uses_controller_draft_not_programmatic_spin(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_span(win, "src", 10.0, n=101)
    _enter_fft(win, [fid])
    _tick_fft_sources(win, [(fid, "sig")])
    top = win.inspector.top
    top.set_range_values(0.0, 10.0)
    asked = []
    monkeypatch.setattr(
        win,
        "_ask_use_local_time_range",
        lambda *a, **k: asked.append(True) or "cancel",
    )
    assert win._offer_analysis_time_range_before_compute("fft") is True
    assert asked == []
    _user_commit_range(top, 2.0, 4.0)
    assert win._offer_analysis_time_range_before_compute("fft") is False
    assert asked == [True]


# -- Step 5: reserved-height Inspector status + mode-specific 「全部」 --

def test_range_intent_status_row_height_is_stable(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections.persistent_top import PersistentTop

    top = PersistentTop()
    qtbot.addWidget(top)
    top.checkout_range_for_mode("fft")
    top.show()
    qtbot.waitExposed(top)
    qapp.processEvents()

    assert top.btn_range_max.toolTip() == PersistentTop._ANALYSIS_RANGE_MAX_TIP
    assert "草稿" in top.btn_range_max.toolTip()
    assert top._range_status_host.isVisible()

    host_heights = []
    group_heights = []
    texts = {}
    for kind in ("full", "draft", "invalid"):
        top.set_range_intent_status(kind)
        qapp.processEvents()
        top._range_group.adjustSize()
        host_heights.append(top._range_status_host.height())
        group_heights.append(top._range_group.height())
        texts[kind] = top.range_intent_status_text()

    assert texts["full"] == ""
    assert texts["draft"] == "范围已调整，尚未启用"
    assert texts["invalid"] == "范围无效，无法用于计算"
    assert host_heights[0] > 0
    assert len(set(host_heights)) == 1
    assert len(set(group_heights)) == 1

    top.checkout_range_for_mode("time")
    assert top.btn_range_max.toolTip() == PersistentTop._TIME_RANGE_MAX_TIP
    assert not top._range_status_host.isVisible()


def test_project_top_from_intent_drives_status_text(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window.analysis_time_range import TimeRangeIntent

    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("fft")
    win.inspector.set_mode("fft")
    top = win.inspector.top
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(kind="draft", range=(1.0, 2.0), display_range=(0.0, 10.0)),
    )
    assert top.range_intent_status_text() == "范围已调整，尚未启用"
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(kind="full", display_range=(0.0, 10.0)),
    )
    assert top.range_intent_status_text() == ""
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(kind="invalid", range=(2.0, 1.0)),
    )
    assert top.range_intent_status_text() == "范围无效，无法用于计算"
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(
            kind="enabled",
            range=(1.0, 2.0),
            display_range=(0.0, 10.0),
            needs_review=True,
        ),
    )
    assert top.range_intent_status_text() == "已启用范围需要复核"
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(
            kind="full",
            display_range=(0.0, 10.0),
            notes=("各信号使用自身全时段",),
        ),
    )
    assert top.range_intent_status_text() == "各信号使用自身全时段"
    win._project_top_from_time_range_intent(
        "fft",
        TimeRangeIntent(kind="unavailable", errors=("missing source",)),
    )
    assert top.range_intent_status_text() == "当前没有可用时间范围"
