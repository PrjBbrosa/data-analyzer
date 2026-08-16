"""QSS ``#objectName`` liveness ratchet — shrink-only.

Spec: ``docs/analyzer/specs/2026-08-15-qss-consolidation-spec.md`` §3.2 / §5.1.
Parser pitfalls live in ``tests/ui_kit/_qss_parse.py`` (shared with Task 5).

Inventory vs spec §5.2 (HEAD ``3971d5a3``, ``style.qss`` 4581 lines / 432
ids; spec counted a dirty UltraView workspace at 4671 / 443):

* **A (0 remaining)**: Task 2 deleted the 28 confirmed-dead selectors.
  ``channelDeleteList`` was comment-only; that retired comment is gone too.
* **B (0)**: ``frfSegmentChoice`` QSS and the ``test_selection_signature.py``
  family row were deleted together in Task 3 (retired from production in
  ``79588591``).
* **C (0 of 9)**: spec's UltraView migration names are **already absent**
  from ``style.qss`` (pruned by ``3971d5a3`` / UltraView A edge-rhythm;
  see ``docs/analyzer/plans/2026-08-14-ultraview-a-edge-rhythm-implementation.md``).
  ``MIGRATION_OBJECT_NAMES`` is therefore empty. None of the nine is a
  production hit either, so they are not re-homed onto DYNAMIC/QT_INTERNAL.
* **DYNAMIC (4)** + **QT_INTERNAL (1)**: standing false positives of the
  literal scan.

Whitelist may only shrink. A newly dead name, a whitelist name that is
now live in production, or a whitelist name gone from ``style.qss``, all
fail this module.
"""
from __future__ import annotations

from pathlib import Path

from tests.ui_kit._qss_parse import (
    REPO_ROOT,
    collect_production_string_literals,
    dead_qss_object_names,
    extract_qss_object_names,
    iter_python_string_literals,
    load_style_qss,
    mask_qss_url_and_gradient_parens,
    neutralize_qss_tokens,
    normalize_selector,
    prepare_qss_selector_text,
    split_selector_list,
    strip_qss_comments,
)

# ---------------------------------------------------------------------------
# Standing segments (spec §3.2)
# ---------------------------------------------------------------------------

# Qt writes this on every QScrollArea viewport; product code never does.
QT_INTERNAL_OBJECT_NAMES: frozenset[str] = frozenset(
    {
        "qt_scrollarea_viewport",
    }
)

# f-string construction — the assembled id is never a Python string literal.
# Sites pinned to this HEAD; ``test_dynamic_construction_sites_match_this_head``
# re-reads the lines so a move updates the comment rather than going stale.
DYNAMIC_OBJECT_NAMES: frozenset[str] = frozenset(
    {
        # contextual_frf.py:479 ``f"{role}Dot"`` with role ``frfInput`` / ``frfOutput``
        # (call sites :195 / :198). Spec inventory cited :479; unchanged here.
        "frfInputDot",
        "frfOutputDot",
        # ultraview/chrome.py:494 ``f"ultraViewRail{short_name}Button"``
        # and :506 ``f"ultraViewRail{short_name}Badge"``, short_name ``Unplaced``
        # from ``_PANEL_SPECS`` (:452). SyncAll is a literal objectName, not
        # this f-string path.
        "ultraViewRailUnplacedButton",
        "ultraViewRailUnplacedBadge",
    }
)

# spec §5.2 C-class 9 names (ultraViewBoardColumn, ultraViewPopover,
# ultraViewFilterPopover, ultraViewLibraryPopover, ultraViewUnplacedPopover,
# ultraViewUnplacedBadge, ultraViewFilterWarning, ultraViewNavigationZoomLabel,
# ultraViewStatusIslandText) plus the UltraView A plan. Already gone from
# this HEAD's style.qss — do not list them (they are not dead *selectors*).
MIGRATION_OBJECT_NAMES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Temporary confirmed-dead names (Task 2 / Task 3 shrink these)
# ---------------------------------------------------------------------------

# A-class (spec §5.2). Task 2 emptied this set; channelDeleteList was
# comment-only and that comment is gone too.
CONFIRMED_DEAD_A_OBJECT_NAMES: frozenset[str] = frozenset()

# B-class emptied in Task 3: QSS blocks + selection-signature row removed together.
CONFIRMED_DEAD_B_OBJECT_NAMES: frozenset[str] = frozenset()

ALLOWED_DEAD_OBJECT_NAMES: frozenset[str] = (
    QT_INTERNAL_OBJECT_NAMES
    | DYNAMIC_OBJECT_NAMES
    | MIGRATION_OBJECT_NAMES
    | CONFIRMED_DEAD_A_OBJECT_NAMES
    | CONFIRMED_DEAD_B_OBJECT_NAMES
)


def test_dead_object_names_match_shrink_only_whitelist():
    dead = dead_qss_object_names()
    unexpected = sorted(dead - ALLOWED_DEAD_OBJECT_NAMES)
    stale = sorted(ALLOWED_DEAD_OBJECT_NAMES - dead)
    assert unexpected == [], (
        "new dead QSS objectName(s) are not on the whitelist — classify "
        f"them (or restore the production setObjectName): {unexpected}"
    )
    assert stale == [], (
        "ALLOWED_DEAD_OBJECT_NAMES has stale entries — the name is now a "
        "production string literal or is gone from style.qss; shrink the "
        f"whitelist, do not keep ghosts: {stale}"
    )


def test_prefixed_live_names_do_not_keep_retired_prefixes_alive():
    """Word-boundary extract + exact literal set: chartHint ⊄ chartHintBar."""
    names = extract_qss_object_names()
    literals = collect_production_string_literals()
    assert "chartHintBar" in names and "chartHintBar" in literals
    assert "chartHint" not in names and "chartHint" not in literals
    assert "channelConfigManagerHtml" in names
    assert "channelConfigManagerHtml" in literals
    assert "channelConfigManager" not in names
    assert "channelConfigManager" not in literals


def test_retired_channel_delete_list_is_gone():
    """spec §5.2 listed channelDeleteList; Task 2 removed the retired comment."""
    qss = load_style_qss()
    assert "channelDeleteList" not in qss
    assert "channelDeleteList" not in extract_qss_object_names(qss)


def test_retired_frf_segment_choice_is_gone_from_qss_and_production():
    """B-class: production retired in 79588591; Task 3 deleted QSS + test row."""
    literals = collect_production_string_literals()
    names = extract_qss_object_names()
    assert "frfSegmentChoice" not in literals
    assert "frfSegmentChoice" not in names
    qss = load_style_qss()
    assert "frfSegmentChoice" not in qss
    assert 'role="frf-segment"' not in qss


def test_dynamic_construction_sites_are_still_present():
    """f-string objectNames are invisible to the literal scan — pin the sites.

    Pin the *construction site*, not its line number. An earlier version
    asserted ``... in chrome[524]``, which made every edit above that line a
    red test and had already been hand-re-pinned once; a site moving down a
    file is not a defect, a site disappearing is. Searching the whole file
    keeps the guarantee and drops the churn.
    """
    frf = (
        REPO_ROOT
        / "mf4_analyzer"
        / "ui"
        / "inspector_sections"
        / "contextual_frf.py"
    ).read_text(encoding="utf-8")
    chrome = (
        REPO_ROOT
        / "mf4_analyzer"
        / "ui"
        / "chart_stack"
        / "ultraview"
        / "chrome.py"
    ).read_text(encoding="utf-8")
    for needle in (
        'dot.setObjectName(f"{role}Dot")',
        '"frfInput"',
        '"frfOutput"',
    ):
        assert needle in frf, f"retired FRF construction site: {needle}"
    for needle in (
        'object_name=f"ultraViewRail{short_name}Button"',
        'badge.setObjectName(f"ultraViewRail{short_name}Badge")',
        '"Unplaced"',
    ):
        assert needle in chrome, f"retired UltraView chrome site: {needle}"


def test_extract_does_not_swallow_prefixes():
    text = (
        "QLabel#chartHintBar { color: blue; }\n"
        "QLabel#chartHint { color: red; }\n"
        "QDialog#channelConfigManagerHtml { }\n"
        "QDialog#channelConfigManager { }\n"
    )
    assert extract_qss_object_names(text) == {
        "chartHintBar",
        "chartHint",
        "channelConfigManagerHtml",
        "channelConfigManager",
    }


def test_hex_color_tokens_are_not_object_names():
    text = (
        "QLabel { color: #1769e0; background: #fff; border-color: #11223344; }\n"
        "QLabel#versionTag { color: #111827; }\n"
    )
    assert extract_qss_object_names(text) == {"versionTag"}


def test_unbalanced_token_braces_do_not_drop_later_object_names():
    """Brace-pair parsers skip the rest of the sheet after ``{{TOKEN}``."""
    text = (
        "QLabel#frfSegmentChoice { color: {{CONTROL_ACCENT}; }\n"
        "QLabel#chartHint { color: red; }\n"
    )
    assert extract_qss_object_names(text) == {"frfSegmentChoice", "chartHint"}


def test_string_literals_cover_setobjectname_but_not_fstring_assembly():
    source = (
        "w.setObjectName('ultraViewToolRail')\n"
        'dot.setObjectName(f"{role}Dot")\n'
    )
    literals = set(iter_python_string_literals(source))
    assert "ultraViewToolRail" in literals
    assert "Dot" in literals
    assert "frfInputDot" not in literals


def test_selector_helpers_mask_gradients_and_normalize():
    raw = """
    QPushButton {
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #ffffff, stop: 1 #eef2f7
        );
        image: url("{{ICON_COMBO_DOWN_REST}}");
    }
    QLabel#chartHint,   QLabel#chartHintBar {
        color: red;
    }
    """
    stripped = strip_qss_comments(raw)
    neutralized = neutralize_qss_tokens(stripped)
    assert "{{" not in neutralized
    masked = mask_qss_url_and_gradient_parens(neutralized)
    assert "stop:" not in masked
    assert "url(" not in masked
    assert "__MASKED_CALL__" in masked
    prepared = prepare_qss_selector_text(raw)
    assert "stop:" not in prepared
    assert split_selector_list("QLabel#chartHint,   QLabel#chartHintBar") == [
        "QLabel#chartHint",
        "QLabel#chartHintBar",
    ]
    assert normalize_selector("  QLabel#chartHint   QPushButton  ") == (
        "QLabel#chartHint QPushButton"
    )


def test_helper_module_stays_qt_free():
    source = Path(__file__).with_name("_qss_parse.py").read_text(encoding="utf-8")
    assert "PyQt" not in source
    assert "qtpy" not in source.lower()
    assert "matplotlib" not in source.lower()
