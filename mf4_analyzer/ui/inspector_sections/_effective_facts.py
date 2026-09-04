"""Shared Inspector "有效事实" formatter and card wiring.

Table-driven on field presence so FRF / FFT / spectrogram / order share one
renderer. FRF-only fields keep their historical labels so
``tests/ui/test_inspector.py`` FRF facts assertions stay pinned.
"""
from __future__ import annotations

from collections.abc import Mapping

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout

from ._helpers import _make_group_header


_FACTS_PLACEHOLDER = "尚无计算结果；计算完成后在此显示实际参数。"
_FACTS_STALE_PREFIX = "（已过期）参数已改动，以下为上一次计算的结果"


def _fact(facts, name):
    """Read one field off a frozen facts dataclass or an equivalent mapping."""
    if facts is None:
        return None
    if isinstance(facts, Mapping):
        return facts.get(name)
    return getattr(facts, name, None)


def _fact_number(facts, name, spec):
    value = _fact(facts, name)
    if value is None:
        return None
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return None


def shortened_nfft_warning(facts) -> str | None:
    """Warning line when the run used a shorter NFFT than requested."""
    if not _fact(facts, "shortened"):
        return None
    nfft_req = _fact(facts, "nfft_requested")
    nfft = _fact(facts, "nfft")
    fs = _fact(facts, "fs")
    try:
        requested = int(nfft_req) if nfft_req is not None else None
        actual = int(nfft) if nfft is not None else None
        fs_val = float(fs) if fs is not None else None
    except (TypeError, ValueError):
        return "数据过短：实际参数已缩短"
    if (
        requested is None
        or actual is None
        or requested <= 0
        or actual <= 0
        or actual >= requested
        or fs_val is None
        or not fs_val
    ):
        return "数据过短：实际参数已缩短"
    df_req = fs_val / float(requested)
    df_act = fs_val / float(actual)
    return (
        f"数据过短：请求 NFFT {requested}，仅能提供 {actual}；"
        f"Δf 由 {df_req:g} 降为 {df_act:g}"
    )


def format_effective_facts(facts) -> list[str]:
    """Render resident "有效事实" rows for one completed analysis run.

    Pure, UI-free formatting so adapters hand over the raw dataclass (or any
    mapping with the same field names). Fields a caller cannot supply are
    dropped rather than printed as ``None``.
    """
    if facts is None:
        return []
    rows: list[tuple[str, str]] = []
    fs_text = _fact_number(facts, "fs", "g")
    if fs_text is not None:
        rows.append(("实际 Fs", f"{fs_text} Hz"))

    nfft = _fact(facts, "nfft")
    nfft_req = _fact(facts, "nfft_requested")
    # FRF has ``nfft`` but not ``nfft_requested``; keep its card unchanged.
    if nfft is not None and nfft_req is not None:
        try:
            actual = int(nfft)
            requested = int(nfft_req)
        except (TypeError, ValueError):
            actual = requested = None
        if actual is not None:
            if requested is not None and requested != actual:
                rows.append(("NFFT（请求 → 实际）", f"{requested} → {actual}"))
            else:
                rows.append(("NFFT（请求 → 实际）", f"{actual}"))

    df_text = _fact_number(facts, "df", "g")
    if df_text is not None:
        # FRF tests pin "频率分辨率 df"; FFT / time cards use Δf.
        if _fact(facts, "segments") is not None:
            rows.append(("频率分辨率 df", f"{df_text} Hz"))
        else:
            rows.append(("频率分辨率 Δf", f"{df_text} Hz"))

    window_s = _fact_number(facts, "window_s", "g")
    if window_s is not None:
        rows.append(("窗口时长", f"{window_s} s"))

    segments = _fact(facts, "segments")
    if segments is not None:
        rows.append(("完整段数", f"{int(segments)}"))
    frames = _fact(facts, "frames")
    if frames is not None:
        rows.append(("完整帧数", f"{int(frames)}"))

    hop_s = _fact_number(facts, "hop_s", "g")
    if hop_s is not None:
        rows.append(("帧移", f"{hop_s} s"))

    order_res = _fact(facts, "order_res")
    order_res_req = _fact(facts, "order_res_requested")
    if order_res is not None:
        res_text = format(float(order_res), "g")
        if order_res_req is not None:
            try:
                requested_res = float(order_res_req)
            except (TypeError, ValueError):
                requested_res = float(order_res)
            if requested_res != float(order_res):
                res_text = f"{format(requested_res, 'g')} → {res_text}"
        rows.append(("阶次分辨率", res_text))
    max_order = _fact(facts, "max_order")
    if max_order is not None:
        rows.append(("最大阶次", format(float(max_order), "g")))
    samples_per_rev = _fact(facts, "samples_per_rev")
    if samples_per_rev is not None:
        rows.append(("每转采样", f"{int(samples_per_rev)}"))
    revolutions = _fact(facts, "revolutions")
    if revolutions is not None:
        rows.append(("累计转数", format(float(revolutions), "g")))
    rpm_min = _fact_number(facts, "rpm_min", "g")
    rpm_max = _fact_number(facts, "rpm_max", "g")
    if rpm_min is not None and rpm_max is not None:
        rows.append(("转速范围", f"{rpm_min} – {rpm_max} rpm"))

    start = _fact_number(facts, "time_start", "g")
    end = _fact_number(facts, "time_end", "g")
    if start is not None and end is not None:
        rows.append(("有效时间范围", f"{start} – {end} s"))

    jitter_text = _fact_number(facts, "max_time_jitter", ".3g")
    if jitter_text is None:
        time_axis = _fact(facts, "time_axis")
        if isinstance(time_axis, Mapping):
            jitter_text = _fact_number(time_axis, "relative_jitter", ".3g")
    if jitter_text is not None:
        # Numeric core reports jitter relative to the nominal sample step.
        rows.append(("最大时间抖动", f"{jitter_text}（相对 dt）"))

    invalid_bins = _fact(facts, "invalid_bins")
    if invalid_bins is not None:
        rows.append(("无效频点", f"{int(invalid_bins)} 个"))

    time_axis = _fact(facts, "time_axis")
    if isinstance(time_axis, Mapping) and time_axis.get("reason") == "auto_nonuniform":
        orig = _fact_number(time_axis, "original_fs", "g")
        orig_bit = f"{orig} Hz" if orig is not None else "—"
        rows.append(("时间轴", f"已自动重建（原 Fs {orig_bit}）"))

    health_parts: list[str] = []
    nan_count = _fact(facts, "nan_count")
    if nan_count:
        health_parts.append(f"NaN {int(nan_count)} 个")
    if _fact(facts, "is_constant"):
        health_parts.append("常值")
    if _fact(facts, "fs_conflict"):
        health_parts.append("多源 Fs 冲突")
    if health_parts:
        rows.append(("数据健康", " / ".join(health_parts)))

    return [f"{label}：{value}" for label, value in rows]


def normalize_effective_warnings(warnings) -> list[str]:
    """De-duplicate warning lines, keeping first-appearance order."""
    seen: list[str] = []
    for raw in warnings or ():
        text = str(raw).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def attach_effective_facts_card(
    host,
    root_layout,
    *,
    prefix: str,
    placeholder: str = _FACTS_PLACEHOLDER,
    summary_refresh=None,
):
    """Install a resident facts card and bind the FRF-like API onto ``host``.

    objectNames: ``{prefix}FactsCard``, ``{prefix}FactsPlaceholder``,
    ``{prefix}EffectiveFacts``, ``{prefix}EffectiveWarnings``.
    """
    facts_card = QFrame(host)
    facts_card.setObjectName(f"{prefix}FactsCard")
    facts_layout = QVBoxLayout(facts_card)
    facts_layout.setContentsMargins(11, 8, 11, 10)
    facts_layout.setSpacing(6)
    facts_layout.addWidget(_make_group_header("有效事实", parent=facts_card))
    lbl_placeholder = QLabel(placeholder, facts_card)
    lbl_placeholder.setObjectName(f"{prefix}FactsPlaceholder")
    lbl_placeholder.setWordWrap(True)
    # Inspector stacked pages do not pass height-for-width; pin two lines
    # of placeholder so first-open sizeHint does not collapse the card.
    lbl_placeholder.setMinimumHeight(
        2 * lbl_placeholder.fontMetrics().lineSpacing()
    )
    facts_layout.addWidget(lbl_placeholder)
    lbl_facts = QLabel("", facts_card)
    lbl_facts.setObjectName(f"{prefix}EffectiveFacts")
    lbl_facts.setWordWrap(True)
    lbl_facts.setTextInteractionFlags(
        Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
    )
    lbl_facts.hide()
    facts_layout.addWidget(lbl_facts)
    lbl_warnings = QLabel("", facts_card)
    lbl_warnings.setObjectName(f"{prefix}EffectiveWarnings")
    lbl_warnings.setWordWrap(True)
    lbl_warnings.setProperty("factsRole", "warning")
    lbl_warnings.hide()
    facts_layout.addWidget(lbl_warnings)
    root_layout.addWidget(facts_card)

    host.lbl_facts_placeholder = lbl_placeholder
    host.lbl_effective_facts = lbl_facts
    host.lbl_effective_warnings = lbl_warnings
    host._effective_facts_rows = []
    host._effective_warnings = []
    host._effective_facts_stale = False
    host._facts_shortened = False

    def _refresh_effective_facts() -> None:
        rows = list(host._effective_facts_rows)
        if rows and host._effective_facts_stale:
            rows.insert(0, _FACTS_STALE_PREFIX)
        has_content = bool(rows or host._effective_warnings)
        lbl_facts.setText("\n".join(rows))
        lbl_facts.setVisible(bool(rows))
        lbl_warnings.setText(
            "\n".join(f"• {line}" for line in host._effective_warnings)
        )
        lbl_warnings.setVisible(bool(host._effective_warnings))
        lbl_placeholder.setVisible(not has_content)
        state = "stale" if host._effective_facts_stale else "fresh"
        for widget in (lbl_facts, lbl_warnings, lbl_placeholder):
            if widget.property("factsState") == state:
                continue
            widget.setProperty("factsState", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_effective_facts(facts, warnings=()) -> None:
        if facts is None:
            clear_effective_facts()
            return
        host._effective_facts_rows = format_effective_facts(facts)
        merged = list(normalize_effective_warnings(warnings))
        extra = shortened_nfft_warning(facts)
        if extra and extra not in merged:
            merged.append(extra)
        host._effective_warnings = merged
        host._effective_facts_stale = False
        host._facts_shortened = bool(_fact(facts, "shortened"))
        _refresh_effective_facts()
        if callable(summary_refresh):
            summary_refresh()

    def clear_effective_facts() -> None:
        host._effective_facts_rows = []
        host._effective_warnings = []
        host._effective_facts_stale = False
        host._facts_shortened = False
        _refresh_effective_facts()
        if callable(summary_refresh):
            summary_refresh()

    def mark_effective_facts_stale() -> None:
        if not host._effective_facts_rows and not host._effective_warnings:
            return
        if host._effective_facts_stale:
            return
        host._effective_facts_stale = True
        _refresh_effective_facts()

    def effective_facts_text() -> str:
        return lbl_facts.text()

    def effective_warnings_text() -> str:
        return lbl_warnings.text()

    def effective_facts_is_stale() -> bool:
        return bool(host._effective_facts_stale)

    host.set_effective_facts = set_effective_facts
    host.clear_effective_facts = clear_effective_facts
    host.mark_effective_facts_stale = mark_effective_facts_stale
    host.effective_facts_text = effective_facts_text
    host.effective_warnings_text = effective_warnings_text
    host.effective_facts_is_stale = effective_facts_is_stale
    host._refresh_effective_facts = _refresh_effective_facts
    _refresh_effective_facts()
    return facts_card
