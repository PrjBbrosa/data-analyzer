"""Compatibility exports for the standalone batch renderer font helpers."""
from __future__ import annotations

from mf4_analyzer.qt_chart_fonts import (
    CJK_CONTRACT_TEXT,
    CJK_FONT_CANDIDATES,
    apply_axis_font,
    chart_font,
    header_ink_proof,
    resolve_cjk_font,
    supports_contract_text,
)


__all__ = [
    "CJK_CONTRACT_TEXT",
    "CJK_FONT_CANDIDATES",
    "apply_axis_font",
    "chart_font",
    "header_ink_proof",
    "resolve_cjk_font",
    "supports_contract_text",
]
