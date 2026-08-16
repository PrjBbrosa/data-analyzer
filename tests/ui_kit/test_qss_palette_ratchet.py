"""Distinct 6-digit hex literals in ``style.qss`` — shrink-only ratchet.

Spec: ``docs/analyzer/specs/2026-08-15-qss-consolidation-spec.md`` §3.3.
The ceiling is the template's remaining literal palette after Task 4's
blue-family merge. Token placeholders (``{{CONTROL_*}}``) are not hex;
the rendered stylesheet is out of scope — this ratchet nails drift in
the template, not the substitution pipeline.

Comments are stripped via :func:`tests.ui_kit._qss_parse.strip_qss_comments`
so design-note swatches do not count. 8-digit (``#RRGGBBAA``) and 3-digit
hex are excluded; only isolated 6-digit values participate.

THIS CEILING MAY ONLY SHRINK. A new distinct literal means a colour
escaped the token map; fix the QSS (or add a justified token), do not
raise the number. If a later merge drops the count, lower the ceiling
in the same change.
"""
from __future__ import annotations

import re

from tests.ui_kit._qss_parse import load_style_qss, strip_qss_comments

# The UltraView polish batch pushed this to 261 by hand-picking a slightly
# different grey per site — eleven pale blue-greys and eight mid blue-greys
# nobody can tell apart. 27 of them were collapsed into the most-used spelling
# of their cluster (CIE76 dE <= 1.0, below the just-noticeable difference).
# Three vetoes kept the merge honest, and they are why the number is 234 and
# not lower: literals also spelled in live code or tests (``control_style.py``,
# ``batch_render_qt/_theme.py``, ``analysis_section_page.py``, …) are NOT
# renameable here — rewriting only the stylesheet desynchronizes the two sides,
# so those 19 need a real shared token, not a find-and-replace. Merges onto
# ``#ffffff`` are out because white carries contrast duty sheet-wide, as is any
# pair co-occurring inside one rule block, where the tiny delta is the design
# (fill vs. edge) rather than drift. Net distinct = 234.
# Titanium Amber moves UltraView's former one-off literals into the isolated
# ``ULTRAVIEW_QSS_TOKENS`` map shared by QSS and QPainter.
MAX_DISTINCT_HEX_LITERALS = 212

# Not preceded/followed by another hex digit, so #11223344 is not #112233.
_HEX6_RE = re.compile(r"(?<![0-9a-fA-F])#([0-9a-fA-F]{6})(?![0-9a-fA-F])")


def distinct_qss_hex_literals(text: str | None = None) -> frozenset[str]:
    """Return case-normalized 6-digit hex literals from the QSS template."""
    if text is None:
        text = load_style_qss()
    stripped = strip_qss_comments(text)
    return frozenset(m.group(1).lower() for m in _HEX6_RE.finditer(stripped))


def test_distinct_hex_literals_may_only_shrink():
    found = distinct_qss_hex_literals()
    count = len(found)
    assert count <= MAX_DISTINCT_HEX_LITERALS, (
        f"distinct 6-digit hex literals grew to {count} "
        f"(ceiling {MAX_DISTINCT_HEX_LITERALS}); merge into an existing "
        f"CONTROL_QSS_TOKENS entry or justify a new token — do not raise "
        f"the ceiling. extras sample={sorted(found)[:12]}"
    )
    assert count == MAX_DISTINCT_HEX_LITERALS, (
        f"distinct 6-digit hex literals shrank to {count}; lower "
        f"MAX_DISTINCT_HEX_LITERALS from {MAX_DISTINCT_HEX_LITERALS} "
        "in this test so the ratchet tracks the new floor"
    )
