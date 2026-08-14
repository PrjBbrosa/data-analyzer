"""CANoe ASC CAN-log sniffing, frame reading, and BLF-facade dispatch."""
from __future__ import annotations

import logging

import pytest

pytest.importorskip("can", reason="python-can not installed (win32-gated)")
pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.io.asc_can_format import (
    _read_asc_frames,
    _read_asc_frames_python_can,
    sniff_canoe_asc,
)
from mf4_analyzer.io.loader import NO_CAN_FRAMES_MESSAGE, DataLoader
from tests._helpers.blf_factory import (
    write_sample_asc,
    write_sample_blf,
    write_two_message_dbc,
)

_ASC_HEADER = (
    "date Mon Jan 01 12:00:00 PM 2024\n"
    "base hex timestamps absolute\n"
    "no internal events logged\n"
    "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024\n"
)


def _classic_line(timestamp, *, arb_id=0x123, dtype="d"):
    return (
        f"   {timestamp:.6f} 1  {arb_id:03X}             "
        f"Rx   {dtype} 8  01 02 03 04 05 06 07 08\n"
    )


def _write_asc(path, body_lines):
    path.write_text(
        _ASC_HEADER + "".join(body_lines) + "End TriggerBlock\n",
        encoding="ascii",
    )
    return path


def _write_early_unsupported_asc(path):
    return _write_asc(path, [_classic_line(1.0, dtype="x")])


def _write_late_unsupported_asc(path, *, classic_before=800, classic_after=20):
    lines = [
        _classic_line(1.0 + index * 0.01, dtype="d")
        for index in range(classic_before)
    ]
    lines.append(_classic_line(1.0 + classic_before * 0.01, dtype="x"))
    lines.extend(
        _classic_line(1.0 + (classic_before + 1 + index) * 0.01, dtype="d")
        for index in range(classic_after)
    )
    return _write_asc(path, lines)


def _progress_percents(progress):
    return [100.0 * current / max(1, total) for current, total, *_rest in progress]


def test_sniff_canoe_asc_true_for_sample(tmp_path):
    path = write_sample_asc(tmp_path / "log.asc", n=3)
    assert sniff_canoe_asc(path) is True


def test_sniff_canoe_asc_false_for_tabular_and_edge_cases(tmp_path):
    table = tmp_path / "table.asc"
    table.write_text("Time\tSpeed\n0.0\t10\n0.1\t11\n", encoding="utf-8")
    empty = tmp_path / "empty.asc"
    empty.write_text("", encoding="utf-8")

    assert sniff_canoe_asc(table) is False
    assert sniff_canoe_asc(empty) is False
    assert sniff_canoe_asc(tmp_path / "missing.asc") is False


def test_read_asc_frames_skips_sv_and_preserves_order(tmp_path):
    path = write_sample_asc(tmp_path / "log.asc", n=5, dt=0.1, t_start=1.0)
    frames = _read_asc_frames(path)

    assert len(frames) == 10
    assert frames[0][0] == pytest.approx(1.0)
    assert frames[0][1] == 0x123
    assert frames[1][0] == pytest.approx(1.05)
    assert frames[1][1] == 0x100
    assert len(frames[0][2]) == 8


def test_read_blf_frames_dispatches_asc_and_matches_blf_decode(tmp_path):
    n = 5
    asc = write_sample_asc(tmp_path / "log.asc", n=n, dt=0.1, t_start=1.0)
    blf = write_sample_blf(tmp_path / "log.blf", n=n, dt=0.1, t_start=1.0)
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")

    asc_frames = DataLoader.read_blf_frames(asc)
    blf_frames = DataLoader.read_blf_frames(blf)
    assert len(asc_frames) == len(blf_frames) == n * 2
    # BLFReader normalizes container time to the first frame; ASCReader keeps
    # the written absolute measurement time. Compare relative deltas + payload.
    asc_t0 = asc_frames[0][0]
    blf_t0 = blf_frames[0][0]
    for (at, aid, adata), (bt, bid, bdata) in zip(asc_frames, blf_frames):
        assert (at - asc_t0) == pytest.approx(bt - blf_t0)
        assert aid == bid
        assert adata == bdata

    asc_data, asc_chs, _asc_units = DataLoader.load_blf_frames(
        asc_frames, dbc_paths=[str(dbc)],
    )
    blf_data, blf_chs, _blf_units = DataLoader.load_blf_frames(
        blf_frames, dbc_paths=[str(dbc)],
    )
    assert set(asc_chs) >= {"Time", "EngineSpeed", "Throttle", "Speed"}
    assert set(asc_chs) == set(blf_chs)
    assert float(asc_data["Time"].iloc[0]) == pytest.approx(0.0)
    for name in ("EngineSpeed", "Throttle", "Speed"):
        assert list(asc_data[name]) == pytest.approx(list(blf_data[name]))


def test_empty_canoe_asc_raises_shared_sentinel(tmp_path):
    path = tmp_path / "empty_log.asc"
    path.write_text(
        "date Mon Jan 01 12:00:00 PM 2024\n"
        "base hex timestamps absolute\n"
        "no internal events logged\n"
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024\n"
        "End TriggerBlock\n",
        encoding="ascii",
    )
    assert sniff_canoe_asc(path) is True
    with pytest.raises(ValueError, match=NO_CAN_FRAMES_MESSAGE):
        DataLoader.read_blf_frames(path)


def test_read_asc_frames_classic_log_skips_python_can_reader(tmp_path, monkeypatch):
    path = write_sample_asc(tmp_path / "log.asc", n=5)

    def boom(*_args, **_kwargs):
        raise AssertionError("ASCReader should not run on classic CANoe ASC")

    monkeypatch.setattr("can.io.ASCReader", boom)
    frames = _read_asc_frames(path)
    assert len(frames) == 10
    assert frames[0][1] == 0x123


def test_read_asc_frames_falls_back_when_classic_dtype_is_unknown(tmp_path, monkeypatch):
    path = tmp_path / "odd.asc"
    path.write_text(
        "date Mon Jan 01 12:00:00 PM 2024\n"
        "base hex timestamps absolute\n"
        "no internal events logged\n"
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024\n"
        "   1.000000 1  123             Rx   x 8  01 02 03 04 05 06 07 08\n"
        "End TriggerBlock\n",
        encoding="ascii",
    )
    called = []
    real = _read_asc_frames_python_can

    def wrapped(fp, progress_callback=None, **kwargs):
        called.append(1)
        return real(fp, progress_callback=progress_callback, **kwargs)

    monkeypatch.setattr(
        "mf4_analyzer.io.asc_can_format._read_asc_frames_python_can", wrapped,
    )
    frames = _read_asc_frames(path)
    assert called == [1]
    assert len(frames) == 1
    assert frames[0][1] == 0x123
    assert frames[0][2] == bytes(range(1, 9))


def test_read_asc_frames_matches_python_can_for_fd_and_extended(tmp_path):
    import can
    from can.io import ASCReader, ASCWriter

    path = tmp_path / "mix.asc"
    writer = ASCWriter(str(path))
    try:
        writer.on_message_received(can.Message(
            arbitration_id=0x123, is_extended_id=False, is_fd=False,
            data=bytes(range(8)), timestamp=1.0, is_rx=True,
        ))
        writer.on_message_received(can.Message(
            arbitration_id=0x1ABCDEF, is_extended_id=True, is_fd=True,
            data=bytes(range(16)), timestamp=1.1, is_rx=True,
        ))
    finally:
        writer.stop()

    fast = _read_asc_frames(path)
    reader = ASCReader(str(path))
    try:
        expected = [
            (float(msg.timestamp), int(msg.arbitration_id), bytes(msg.data))
            for msg in reader
            if not msg.is_error_frame and not msg.is_remote_frame
        ]
    finally:
        stop = getattr(reader, "stop", None)
        if callable(stop):
            stop()
    assert len(fast) == len(expected) == 2
    for (at, aid, adata), (bt, bid, bdata) in zip(fast, expected):
        assert at == pytest.approx(bt)
        assert aid == bid
        assert adata == bdata


def test_read_asc_frames_matches_python_can_for_txrq(tmp_path):
    """P1-1: a `TxRq` direction field must not be silently dropped.

    `TxRq` used to fail the hint regex's trailing ``\\b`` (no word boundary
    between "Tx" and "Rq"), so the line was neither parsed as data nor
    recognized as "looks like a frame we can't parse" — it just vanished
    from the fast path with no fallback and no trace. python-can's own
    ``ASC_MESSAGE_REGEX`` has no such anchor: it matches a `TxRq` line via
    the `Tx` alternative (``re.match`` doesn't require consuming the rest of
    the token) and decodes it as an ordinary non-remote, non-error frame.
    """
    from can.io import ASCReader

    path = tmp_path / "txrq.asc"
    path.write_text(
        "date Mon Jan 01 12:00:00 PM 2024\n"
        "base hex timestamps absolute\n"
        "no internal events logged\n"
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024\n"
        "   1.000000 1  123             Rx   d 8  01 02 03 04 05 06 07 08\n"
        "   1.010000 1  456             TxRq d 8  11 12 13 14 15 16 17 18\n"
        "End TriggerBlock\n",
        encoding="ascii",
    )

    fast = _read_asc_frames(path)

    reader = ASCReader(str(path))
    try:
        expected = [
            (float(msg.timestamp), int(msg.arbitration_id), bytes(msg.data))
            for msg in reader
            if not msg.is_error_frame and not msg.is_remote_frame
        ]
    finally:
        stop = getattr(reader, "stop", None)
        if callable(stop):
            stop()

    assert len(fast) == len(expected) == 2
    for (at, aid, adata), (bt, bid, bdata) in zip(fast, expected):
        assert at == pytest.approx(bt)
        assert aid == bid
        assert adata == bdata


def test_preflight_unsupported_syntax_skips_full_fast_scan(tmp_path, monkeypatch):
    from mf4_analyzer.io.asc_can_format import (
        ASC_BACKEND_PYTHON_CAN,
        AscFallbackReason,
        read_asc_outcome,
    )

    path = _write_early_unsupported_asc(tmp_path / "early.asc")
    fast_calls = []

    def boom(*_args, **_kwargs):
        fast_calls.append(1)
        raise AssertionError("fast parser must not scan a preflight-rejected ASC")

    monkeypatch.setattr(
        "mf4_analyzer.io.asc_can_format._read_asc_frames_fast", boom,
    )
    outcome = read_asc_outcome(path)
    assert fast_calls == []
    assert outcome.backend == ASC_BACKEND_PYTHON_CAN
    assert outcome.fallback_reason is AscFallbackReason.UNSUPPORTED_SYNTAX
    assert 0 < outcome.bytes_consumed_before_fallback <= 8192
    assert len(outcome.frames) == 1
    assert outcome.frames[0][1] == 0x123


def test_preflight_requires_data_lines_not_just_header_noise(tmp_path):
    """§4.2: a header thick with comments must not exhaust the scan window
    before a single data line has been examined.

    Under the old "64 lines of any kind" budget, a header long enough to
    fill the window on its own made the preflight declare ``supported=True``
    by default — without ever having looked at real payload — and the
    genuinely unsupported line right after the header only surfaced once
    the (much more expensive) full fast scan reached it. The fix counts the
    window in actual data lines, so header/comment noise stays free and the
    scan reaches the first data line regardless of how much header precedes
    it.
    """
    from mf4_analyzer.io.asc_can_format import AscFallbackReason, _preflight_asc_format

    lines = [
        "date Mon Jan 01 12:00:00 PM 2024",
        "base hex timestamps absolute",
        "no internal events logged",
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024",
    ]
    # 80 short comment lines: more than the historical 64-line budget, but
    # still well under both the normal 8 KiB and the widened header-safety
    # byte ceilings.
    lines += [f"// setup note {i}" for i in range(80)]
    lines.append(_classic_line(1.0, dtype="x"))  # unsupported dtype
    lines.append("End TriggerBlock")
    path = tmp_path / "long_header.asc"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

    result = _preflight_asc_format(path)
    assert result.supported is False
    assert result.reason is AscFallbackReason.UNSUPPORTED_SYNTAX


def test_preflight_still_passes_small_files_with_few_data_lines(tmp_path):
    """Guard against over-correcting: files far short of the historical
    64-line budget (the vast majority of the existing test fixtures) must
    still preflight as supported once fully examined, not be held to an
    artificial minimum they can never reach."""
    from mf4_analyzer.io.asc_can_format import _preflight_asc_format

    path = write_sample_asc(tmp_path / "small.asc", n=3)
    result = _preflight_asc_format(path)
    assert result.supported is True
    assert result.reason is None


def test_late_fallback_progress_is_monotonically_non_decreasing(tmp_path):
    path = _write_late_unsupported_asc(tmp_path / "late.asc")
    progress = []

    def capture(current, total, phase=None):
        progress.append((current, total, phase))

    frames = _read_asc_frames(path, progress_callback=capture)
    assert len(frames) == 821
    percents = _progress_percents(progress)
    assert percents, "expected progress while falling back mid-file"
    assert percents == sorted(percents)
    assert percents[0] == 0
    # A late fallback used to restart python-can at 0% after the fast scan
    # had already advanced. Any regression would show up as a drop here.
    for earlier, later in zip(percents, percents[1:]):
        assert later >= earlier
    assert max(percents[:-1]) > 10, "fast scan should have advanced before fallback"


def test_fallback_does_not_emit_100_until_result_is_delivered(tmp_path, monkeypatch):
    path = _write_late_unsupported_asc(tmp_path / "late.asc")
    progress = []
    snapshot_at_fallback = []
    real = _read_asc_frames_python_can

    def wrapped(fp, progress_callback=None, **kwargs):
        snapshot_at_fallback.extend(list(progress))
        return real(fp, progress_callback=progress_callback, **kwargs)

    monkeypatch.setattr(
        "mf4_analyzer.io.asc_can_format._read_asc_frames_python_can", wrapped,
    )
    frames = _read_asc_frames(
        path,
        progress_callback=lambda current, total, phase=None: progress.append(
            (current, total)
        ),
    )
    assert frames
    assert snapshot_at_fallback, "python-can fallback should have run"
    assert all(current < total for current, total in snapshot_at_fallback)
    assert progress[-1][0] == progress[-1][1]


def test_cancel_does_not_emit_success_100(tmp_path):
    from mf4_analyzer.io.asc_can_format import AscParseCancelled

    path = _write_asc(
        tmp_path / "busy.asc",
        [_classic_line(1.0 + index * 0.01) for index in range(200)],
    )
    progress = []
    polls = 0

    def cancel_check():
        nonlocal polls
        polls += 1
        return polls >= 3

    with pytest.raises(AscParseCancelled):
        _read_asc_frames(
            path,
            progress_callback=lambda current, total, phase=None: progress.append(
                (current, total)
            ),
            cancel_check=cancel_check,
        )
    assert polls >= 3
    assert progress == [] or all(current < total for current, total in progress)


def test_asc_parse_outcome_records_backend_reason_and_bytes(tmp_path):
    from mf4_analyzer.io.asc_can_format import (
        ASC_BACKEND_FAST,
        ASC_BACKEND_PYTHON_CAN,
        AscFallbackReason,
        read_asc_outcome,
    )

    classic = write_sample_asc(tmp_path / "classic.asc", n=5)
    fast_outcome = read_asc_outcome(classic)
    assert fast_outcome.backend == ASC_BACKEND_FAST
    assert fast_outcome.fallback_reason is None
    assert fast_outcome.bytes_consumed_before_fallback == 0
    assert fast_outcome.cancelled is False
    assert fast_outcome.frame_count == 10
    assert fast_outcome.warning is None

    early = _write_early_unsupported_asc(tmp_path / "early.asc")
    early_outcome = read_asc_outcome(early)
    assert early_outcome.backend == ASC_BACKEND_PYTHON_CAN
    assert early_outcome.fallback_reason is AscFallbackReason.UNSUPPORTED_SYNTAX
    assert 0 < early_outcome.bytes_consumed_before_fallback <= 8192
    assert early_outcome.frame_count == 1
    assert early_outcome.warning
    assert early_outcome.diagnostic_context["fallback_reason"] == (
        AscFallbackReason.UNSUPPORTED_SYNTAX.value
    )

    late = _write_late_unsupported_asc(tmp_path / "late.asc")
    late_outcome = read_asc_outcome(late)
    assert late_outcome.backend == ASC_BACKEND_PYTHON_CAN
    assert late_outcome.fallback_reason is AscFallbackReason.UNSUPPORTED_SYNTAX
    assert late_outcome.bytes_consumed_before_fallback > 8192
    assert late_outcome.frame_count == 821


def test_asc_progress_phases_distinguish_fast_and_compat_retry(tmp_path):
    from mf4_analyzer.io.asc_can_format import ASC_PHASE_FALLBACK, ASC_PHASE_FAST

    fast_phases = []
    _read_asc_frames(
        write_sample_asc(tmp_path / "classic.asc", n=5),
        progress_callback=lambda current, total, phase=None: fast_phases.append(phase),
    )
    assert ASC_PHASE_FAST in fast_phases
    assert ASC_PHASE_FALLBACK not in fast_phases

    fallback_phases = []
    _read_asc_frames(
        _write_early_unsupported_asc(tmp_path / "early.asc"),
        progress_callback=lambda current, total, phase=None: fallback_phases.append(
            phase
        ),
    )
    assert ASC_PHASE_FALLBACK in fallback_phases


def test_fallback_reason_diagnostics_are_throttled(tmp_path, caplog, monkeypatch):
    from collections import OrderedDict

    from mf4_analyzer import diagnostics
    from mf4_analyzer.io.asc_can_format import AscFallbackReason, read_asc_outcome

    monkeypatch.setattr(diagnostics, "WINDOW", 60.0)
    monkeypatch.setattr(diagnostics, "BURST", 3)
    monkeypatch.setattr(diagnostics, "_THROTTLE_STATE", OrderedDict())
    path = _write_early_unsupported_asc(tmp_path / "early.asc")
    logger_name = "mf4_analyzer.io.asc_can_format"
    caplog.set_level(logging.WARNING, logger=logger_name)

    for _ in range(10):
        read_asc_outcome(path)

    records = [
        record
        for record in caplog.records
        if record.name == logger_name
        and (
            "兼容解析重试" in record.getMessage()
            or "unsupported_syntax" in record.getMessage()
        )
    ]
    assert records, "fallback must be visible in diagnostics"
    assert any(
        AscFallbackReason.UNSUPPORTED_SYNTAX.value in record.getMessage()
        for record in records
    )
    assert len(records) <= diagnostics.BURST


def test_progress_callback_internal_typeerror_is_not_retried_with_fewer_args(
    tmp_path,
):
    """§4.2: a bug *inside* a 3-arg callback must not be misdiagnosed as
    "wrong arity" and retried with two args.

    The coordinator used to probe call shape by actually invoking the
    callback and inspecting which exception came back; any ``TypeError``
    raised from inside a working 3-arg callback (unrelated to argument
    count) triggered a second, duplicate call with two args — running the
    callback's side effects twice for one logical progress tick. The fix
    probes the callback's signature once up front instead of by calling it.
    """
    path = write_sample_asc(tmp_path / "log.asc", n=5)

    reference_ticks = []
    _read_asc_frames(
        path,
        progress_callback=lambda current, total, phase=None: reference_ticks.append(1),
    )

    calls = []

    def flaky(current, total, phase=None):
        calls.append((current, total, phase))
        raise TypeError("boom: unrelated bug inside the callback, not an arity issue")

    frames = _read_asc_frames(path, progress_callback=flaky)
    assert len(frames) == 10
    assert len(calls) == len(reference_ticks), (
        "each progress tick must invoke the callback exactly once; a doubled "
        "count means an internal TypeError was misdiagnosed as wrong arity"
    )


def test_emit_progress_propagates_cancellation_not_swallowed():
    """§4.2: ``AscParseCancelled`` raised from inside a progress callback
    must propagate through the shared ``_emit_progress`` helper.

    The old bare ``except Exception: pass`` was a dead safety net that
    silently ate the cancellation (per-line ``cancel_check`` happened to
    cover for it elsewhere, but this path should not have swallowed it
    either — a lost cancellation signal here is not observable).
    """
    from mf4_analyzer.io.asc_can_format import AscParseCancelled
    from mf4_analyzer.io.blf_format import _emit_progress

    def cancelling_callback(current, total):
        raise AscParseCancelled()

    with pytest.raises(AscParseCancelled):
        _emit_progress(cancelling_callback, 1, 10)


def test_emit_progress_logs_other_callback_failures_instead_of_silence(
    caplog,
):
    """Non-cancellation callback failures stay non-fatal but must leave a
    debug trace instead of a bare ``pass`` (repo-wide "宽泛 except 必须留痕"
    discipline)."""
    import logging as _logging

    from mf4_analyzer.io.blf_format import _emit_progress

    def boom(current, total):
        raise ValueError("unrelated callback bug")

    caplog.set_level(_logging.DEBUG, logger="mf4_analyzer.io.blf_format")
    _emit_progress(boom, 1, 10)  # must not raise
    assert any(
        "progress callback raised" in record.getMessage()
        for record in caplog.records
    )


def test_read_asc_frames_reports_warning_via_callback_on_fallback(tmp_path):
    """P1-2: the fallback warning must reach an explicit ``warning_callback``
    exit, not just ``logger.warning`` — production code has no other way to
    recover ``AscParseOutcome.warning`` through the ``_read_asc_frames`` /
    ``DataLoader.read_blf_frames`` facade, which only ever returned frames.
    """
    path = _write_early_unsupported_asc(tmp_path / "early.asc")
    warnings = []
    frames = _read_asc_frames(path, warning_callback=warnings.append)
    assert len(frames) == 1
    assert warnings == ["不支持的 ASC 语法，已切换到兼容解析重试"]


def test_read_asc_frames_warning_callback_silent_on_fast_path(tmp_path):
    path = write_sample_asc(tmp_path / "log.asc", n=3)
    warnings = []
    _read_asc_frames(path, warning_callback=warnings.append)
    assert warnings == []


def test_read_blf_frames_forwards_warning_callback_for_asc_only(tmp_path):
    asc = _write_early_unsupported_asc(tmp_path / "early.asc")
    blf = write_sample_blf(tmp_path / "log.blf", n=3)

    asc_warnings = []
    DataLoader.read_blf_frames(asc, warning_callback=asc_warnings.append)
    assert asc_warnings

    blf_warnings = []
    DataLoader.read_blf_frames(blf, warning_callback=blf_warnings.append)
    assert blf_warnings == []
