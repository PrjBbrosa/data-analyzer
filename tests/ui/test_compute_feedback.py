from mf4_analyzer.ui.compute_feedback import ComputeOutcome, summarize_compute


def test_busy():
    assert summarize_compute(ComputeOutcome(), busy=True, section_label="时间-阶次") == (
        "info",
        "时间-阶次进行中，请稍候…",
    )


def test_nothing_to_do_returns_none():
    assert summarize_compute(ComputeOutcome()) is None


def test_all_cached():
    assert summarize_compute(ComputeOutcome(cached=3)) == (
        "info",
        "已用缓存结果（参数未变）· 3 图",
    )


def test_all_computed():
    assert summarize_compute(ComputeOutcome(computed=2), section_label="FFT") == (
        "success",
        "FFT完成 · 2 图",
    )


def test_mixed_computed_and_cached_counts_as_rendered_success():
    assert summarize_compute(
        ComputeOutcome(computed=1, cached=2), section_label="FFT-vs-Time"
    ) == ("success", "FFT-vs-Time完成 · 3 图")


def test_all_skipped_groups_reasons_by_first_seen_order():
    assert summarize_compute(
        ComputeOutcome(skipped=["信号过短", "缺转速", "信号过短"])
    ) == ("warning", "无可计算的图：2 个信号过短、1 个缺转速")


def test_partial_skip():
    assert summarize_compute(
        ComputeOutcome(computed=1, cached=1, skipped=["信号过短"])
    ) == ("warning", "2 图已出 · 1 图跳过（1 个信号过短）")


def test_all_failed():
    assert summarize_compute(ComputeOutcome(failed=2), section_label="FFT") == (
        "error",
        "FFT失败：2 个图计算出错",
    )


def test_partial_failure():
    assert summarize_compute(
        ComputeOutcome(computed=1, failed=2), section_label="FFT"
    ) == ("warning", "1 图已出 · 2 个出错")
