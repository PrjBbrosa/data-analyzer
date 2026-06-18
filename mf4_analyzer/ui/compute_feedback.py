from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ComputeOutcome:
    computed: int = 0
    cached: int = 0
    failed: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def rendered(self) -> int:
        return self.computed + self.cached


def summarize_compute(
    outcome: ComputeOutcome,
    *,
    busy: bool = False,
    section_label: str = "计算",
) -> tuple[str, str] | None:
    if busy:
        return ("info", f"{section_label}进行中，请稍候…")

    rendered = outcome.rendered
    failed = outcome.failed
    skipped = outcome.skipped

    if rendered == 0 and failed == 0 and not skipped:
        return None

    if rendered == 0:
        if failed:
            return ("error", f"{section_label}失败：{failed} 个图计算出错")
        return ("warning", _skip_text(skipped, none_rendered=True))

    if failed == 0 and not skipped:
        if outcome.computed == 0:
            return ("info", f"已用缓存结果（参数未变）· {outcome.cached} 图")
        return ("success", f"{section_label}完成 · {rendered} 图")

    parts = [f"{rendered} 图已出"]
    if skipped:
        parts.append(_skip_text(skipped, none_rendered=False))
    if failed:
        parts.append(f"{failed} 个出错")
    return ("warning", " · ".join(parts))


def _skip_text(skipped: list[str], *, none_rendered: bool) -> str:
    counts = Counter(skipped)
    detail = "、".join(f"{n} 个{reason}" for reason, n in counts.items())
    if none_rendered:
        return f"无可计算的图：{detail}"
    return f"{len(skipped)} 图跳过（{detail}）"
