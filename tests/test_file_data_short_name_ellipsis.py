"""Unit tests for the middle-ellipsis short_name formatter (Task 2).

User request (verbatim): "你按照稳健的方式优化吧，长文件中间可以省略号".

``middle_ellipsis`` replaces the old head-truncation (``stem[:18]``) that
collapsed two long filenames sharing a >=18-char common prefix to the SAME
label. The middle-ellipsis form keeps the differentiating TAIL, so distinct
files stay visually distinct. Channel IDENTITY is the composite (data_id, name)
key on the canvas, so the label is display-only and any residual collision here
is cosmetic, not a data-loss bug.

Boundary coverage (per task brief): exactly-at-budget, just-over, with/without
suffix, unicode-safe.
"""

import numpy as np
import pandas as pd

from mf4_analyzer.io.file_data import (
    FileData,
    middle_ellipsis,
    _SHORT_NAME_BUDGET,
    _SHORT_NAME_BUDGET_WITH_SUFFIX,
)


# -- the formatter in isolation ------------------------------------------


def test_short_name_returned_byte_identical_when_within_budget():
    s = "short"
    assert middle_ellipsis(s, 18) == "short"
    # No ellipsis is introduced when not needed.
    assert "…" not in middle_ellipsis(s, 18)


def test_exactly_at_budget_is_unchanged():
    s = "a" * 18  # len == budget
    out = middle_ellipsis(s, 18)
    assert out == s
    assert "…" not in out
    assert len(out) == 18


def test_just_over_budget_gets_middle_ellipsis():
    s = "a" * 19  # one over
    out = middle_ellipsis(s, 18)
    assert "…" in out
    assert len(out) == 18  # exactly budget code points
    assert out.startswith("a")
    assert out.endswith("a")


def test_middle_ellipsis_preserves_head_and_differentiating_tail():
    s = "measurement_run_2026_alpha_final"  # 32 chars
    out = middle_ellipsis(s, 18)
    assert len(out) == 18
    head, _, tail = out.partition("…")
    # Head is the leading prefix; tail is the differentiating suffix.
    assert s.startswith(head)
    assert s.endswith(tail)
    assert tail, "the differentiating tail must be preserved"
    # Tail gets the extra char when (budget-1) is odd (favors disambiguation).
    assert len(tail) >= len(head)


def test_two_long_common_prefix_names_now_differ():
    """The whole point: two names that head-truncation collapsed must now
    produce DISTINCT middle-ellipsis labels."""
    a = "measurement_run_2026_alpha"
    b = "measurement_run_2026_bravo"
    assert a[:18] == b[:18]  # head-truncation would have collided
    assert middle_ellipsis(a, 18) != middle_ellipsis(b, 18)


def test_unicode_safe_counts_code_points_not_bytes():
    # 24 CJK code points (each multi-byte in UTF-8); budget 18 code points.
    s = "测量数据运行二零二六年阿尔法版本最终结果数据流通道一"
    assert len(s) > 18
    out = middle_ellipsis(s, 18)
    assert len(out) == 18  # counted by code point, never split mid-codepoint
    assert "…" in out
    # Round-trips through UTF-8 cleanly (no surrogate / partial-codepoint).
    assert out.encode("utf-8").decode("utf-8") == out


def test_tiny_budget_degrades_to_head_cut():
    s = "abcdefgh"
    # budget < 3 can't hold head+…+tail; degrade to head cut, no ellipsis.
    assert middle_ellipsis(s, 2) == "ab"
    assert "…" not in middle_ellipsis(s, 2)


def test_empty_and_none_budget_are_safe():
    assert middle_ellipsis("", 18) == ""
    assert middle_ellipsis("anything", None) == "anything"


# -- wired into FileData.short_name --------------------------------------


def _fd(stem, *, label_suffix=""):
    df = pd.DataFrame({"time": np.linspace(0, 1, 4), "sig": np.zeros(4)})
    return FileData(
        f"{stem}.csv", df, ["time", "sig"], {"sig": "u"},
        label_suffix=label_suffix,
    )


def test_filedata_short_name_uses_middle_ellipsis_when_over_budget():
    fd = _fd("measurement_run_2026_alpha_final")
    assert "…" in fd.short_name
    assert len(fd.short_name) == _SHORT_NAME_BUDGET
    # The prefixed channel label (display only) carries the elided form.
    assert "…" in fd.get_prefixed_channel("sig")


def test_filedata_short_name_unchanged_for_normal_names():
    fd = _fd("engine_test")
    assert fd.short_name == "engine_test"
    assert "…" not in fd.short_name


def test_filedata_two_long_common_prefix_files_get_distinct_labels():
    fd_a = _fd("measurement_run_2026_alpha")
    fd_b = _fd("measurement_run_2026_bravo")
    assert fd_a.short_name != fd_b.short_name
    assert fd_a.get_prefixed_channel("sig") != fd_b.get_prefixed_channel("sig")


def test_filedata_label_suffix_applies_to_elided_base():
    fd = _fd("measurement_run_2026_alpha_final", label_suffix="v2")
    # Base is elided within the with-suffix budget, suffix appended verbatim.
    assert fd.short_name.endswith(" ·v2")
    base = fd.short_name[: -len(" ·v2")]
    assert "…" in base
    assert len(base) == _SHORT_NAME_BUDGET_WITH_SUFFIX


def test_filedata_label_suffix_short_base_not_elided():
    fd = _fd("engine", label_suffix="v2")
    assert fd.short_name == "engine ·v2"
    assert "…" not in fd.short_name
