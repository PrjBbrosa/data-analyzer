"""Tests for tolerant comma-separated list parsing."""
from __future__ import annotations

import pytest

from mf4_analyzer.list_text import split_list_text


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("", []),
        (None, []),
        ("  ", []),
        ("5, 15, 25", ["5", "15", "25"]),
        ("5，15，25", ["5", "15", "25"]),
        ("5、15、25", ["5", "15", "25"]),
        ("5;15；25", ["5", "15", "25"]),
        ("5， 15, 25", ["5", "15", "25"]),
        ("5,", ["5", ""]),
        (",5", ["", "5"]),
        ("Nm，deg/s、rpm", ["Nm", "deg/s", "rpm"]),
    ),
)
def test_split_list_text_accepts_ascii_and_chinese_separators(text, expected):
    assert split_list_text(text) == expected
