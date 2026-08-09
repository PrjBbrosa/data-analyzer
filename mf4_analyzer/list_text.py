"""Helpers for user-typed comma-separated lists.

Chinese IME often inserts full-width ``，`` / ``、`` (or ``；``) instead of
ASCII ``,``. Parsing accepts those separators; stored/exported values stay
ASCII-normalized via the caller's float/format path.
"""
from __future__ import annotations

import re

# ASCII comma/semicolon plus the common Chinese punctuation users type with
# an IME while filling numeric or alias lists.
_LIST_SEP_RE = re.compile(r"[,，、;；]+")


def split_list_text(text: str | None) -> list[str]:
    """Split ``text`` on ASCII/Chinese commas and semicolons.

    Empty input yields ``[]``. Consecutive separators collapse; a trailing
    separator still leaves a trailing empty token so callers can reject
    ``"5,"`` as incomplete rather than silently accepting ``[5]``.
    """
    raw = "" if text is None else str(text).strip()
    if not raw:
        return []
    return [part.strip() for part in _LIST_SEP_RE.split(raw)]
