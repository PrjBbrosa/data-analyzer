"""Shrink-only ratchet: ``.connect(lambda …)`` in ui/ + acquisition_ui/.

A ``.connect(lambda …)`` closure that captures ``self`` (or a sibling widget)
is a strong Python reference cycle across the C++/Python boundary. PyQt's
normal signal→slot wiring already ties slot lifetime to the *receiver*
QObject; the lambda form does not. BatchSheet's zombie-wrapper teardown
cluster and the channel-tree paint GC segfault family both feed on this
fuel (see guideline-hardening E7/E8).

This test freezes the remaining file→count map after Task 16 cleaned the
discard-arg emit relays and inspector mode tags. The whitelist may only
**shrink**: every further cleanup deletes entries / lowers counts, and any
newly introduced ``.connect(lambda`` turns the suite red immediately.

Precedent: ``test_main_window_state_ownership.py``.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "mf4_analyzer"
SCAN_ROOTS = (
    PACKAGE_ROOT / "ui",
    PACKAGE_ROOT / "acquisition_ui",
)

# File (relative to mf4_analyzer/) -> count of `.connect(<lambda>)` call sites.
# Measured after Task 16 (E7/E8) cleanup on guideline/task16-e7-e8-e9.
#
# THIS SET MAY ONLY SHRINK. Adding a file or raising a count means a new
# lambda-connected signal escaped the E8 discipline; fix the code, not the
# whitelist.
FROZEN_LAMBDA_CONNECT_COUNTS: dict[str, int] = {
    "acquisition_ui/history_tab.py": 3,
    "acquisition_ui/main_window/_settings_mixin.py": 1,
    "acquisition_ui/main_window/_toolbar_mixin.py": 3,
    "acquisition_ui/replay_tab.py": 1,
    "acquisition_ui/review_modal.py": 1,
    "acquisition_ui/widgets/health_strip.py": 1,
    "acquisition_ui/widgets/left_pane.py": 6,
    "acquisition_ui/widgets/live_cards.py": 3,
    "ui/chart_stack/_helpers.py": 2,
    "ui/chart_stack/cards.py": 7,
    "ui/chart_stack/stack.py": 12,
    "ui/chart_stack/toolbar.py": 6,
    "ui/db_reference_dialog.py": 1,
    "ui/dialogs/channel_editor.py": 2,
    "ui/drawers/batch/analysis_panel.py": 1,
    "ui/drawers/batch/frf_pair_editor.py": 1,
    "ui/drawers/batch/render_style_popover.py": 4,
    "ui/drawers/batch/signal_picker.py": 1,
    "ui/file_navigator.py": 1,
    "ui/inspector_sections/_helpers.py": 1,
    "ui/inspector_sections/persistent_top.py": 2,
    "ui/inspector_sections/presets.py": 2,
    "ui/main_window/_analysis_mixin.py": 1,
    "ui/main_window/_channel_scope_mixin.py": 1,
    "ui/main_window/_view_mixin.py": 2,
    "ui/main_window/window.py": 30,
    "ui/markup/toolbar.py": 3,
    "ui/pg_canvas/context_menu.py": 11,
    "ui/pg_canvas/heatmap_canvas.py": 1,
    "ui/pg_canvas/line_canvas.py": 4,
    "ui/pg_canvas/remarks.py": 1,
    "ui/pg_canvas/slice_panel.py": 1,
    "ui/side_panels.py": 5,
    "ui/toolbar.py": 1,
    "ui/view_tabbar.py": 1,
    "ui/widgets/channel_config_manager.py": 4,
}


def _lambda_connect_counts() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            n = 0
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
                    continue
                if node.args and isinstance(node.args[0], ast.Lambda):
                    n += 1
            if n:
                rel = path.relative_to(PACKAGE_ROOT).as_posix()
                counts[rel] = n
    return dict(counts)


def test_lambda_signal_connections_whitelist_is_shrink_only():
    current = _lambda_connect_counts()
    frozen = dict(FROZEN_LAMBDA_CONNECT_COUNTS)

    new_files = sorted(set(current) - set(frozen))
    assert not new_files, (
        "New .connect(lambda …) sites appeared outside the frozen whitelist; "
        "replace with signal-to-signal / bound method / functools.partial "
        f"(E8). Offenders: {new_files}"
    )

    raised = {
        path: (frozen[path], current[path])
        for path in frozen
        if path in current and current[path] > frozen[path]
    }
    assert not raised, (
        "A frozen file gained .connect(lambda …) sites; fix the code, do not "
        f"widen the whitelist. Raised: {raised}"
    )

    # Files that dropped to zero may leave the map entirely; that is the
    # intended shrink direction. Stale whitelist entries (file gone or
    # count now zero) are reported as soft progress, not failure — but a
    # count that is *lower* while still positive must update the frozen
    # map in the same change so the ratchet actually tightens.
    stale = sorted(
        path for path, n in frozen.items()
        if path not in current or current.get(path, 0) == 0
    )
    lowered = {
        path: (frozen[path], current[path])
        for path in frozen
        if path in current and 0 < current[path] < frozen[path]
    }
    if stale or lowered:
        pytest.fail(
            "Lambda-connect whitelist can shrink further — update "
            f"FROZEN_LAMBDA_CONNECT_COUNTS in this test. "
            f"stale(zero/missing)={stale} lowered={lowered}"
        )


def test_lambda_connect_total_matches_whitelist_sum():
    current = _lambda_connect_counts()
    assert sum(current.values()) == sum(FROZEN_LAMBDA_CONNECT_COUNTS.values())
    assert current == FROZEN_LAMBDA_CONNECT_COUNTS
