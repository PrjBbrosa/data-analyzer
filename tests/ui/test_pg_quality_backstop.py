"""Pure-logic contract for ``AaFrameLatch`` (spec 2026-08-15 §3.3).

The latch is the measured-frame state machine that used to live inline in
``QualityManager``: epoch bookkeeping, first-frame vs steady-EMA ceilings, the
bounded blacklist and the first-frame cost memo. It was extracted so the
analysis canvases (``PgLineCanvas`` / ``PgFrfCanvas``) can reuse ONE calibrated
state machine instead of growing a third hand-written copy.

Everything here is plain Python — no Qt, no canvas, no event loop. The Qt half
of a trip (deferring the AA disable out of ``paintEvent``, epoch-checking the
queued timer) stays in ``QualityManager`` and is covered by
``tests/ui/test_pg_timedomain_canvas.py::TestAaBackstopLatch``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.pg_canvas.quality_backstop import AaFrameLatch


FIRST_MS = 1000.0
STEADY_MS = 250.0
ALPHA = 0.5
MAX_ENTRIES = 4


def _latch(**overrides):
    kwargs = {
        "first_ms": FIRST_MS,
        "steady_ms": STEADY_MS,
        "ema_alpha": ALPHA,
        "max_entries": MAX_ENTRIES,
    }
    kwargs.update(overrides)
    return AaFrameLatch(**kwargs)


class TestSessionLifecycle:
    def test_open_and_close_each_bump_the_epoch(self):
        """The epoch is what lets a queued trip tell "the session I measured"
        from "some later session", so both ends of a session move it."""
        latch = _latch()
        assert latch.epoch == 0

        latch.open(("sig", 1))
        assert latch.epoch == 1
        assert latch.signature == ("sig", 1)

        latch.close()
        assert latch.epoch == 2
        assert latch.signature is None

    def test_open_resets_per_session_counters(self):
        latch = _latch()
        latch.open(("sig", 1))
        latch.note_frame(5.0)
        latch.note_frame(100.0)
        assert latch.frames == 2
        assert latch.ema == pytest.approx(100.0)

        latch.open(("sig", 2))
        assert latch.frames == 0
        assert latch.ema is None

    def test_note_frame_after_close_returns_none(self):
        """A closed latch measures nothing: frames painted outside an AA
        session must never be attributed to one."""
        latch = _latch()
        latch.open(("sig", 1))
        latch.close()

        assert latch.note_frame(9_000.0) is None
        assert latch.frames == 0
        assert latch.blacklist == {}

    def test_note_frame_before_any_open_returns_none(self):
        latch = _latch()
        assert latch.note_frame(9_000.0) is None
        assert latch.blacklist == {}

    def test_non_numeric_frame_is_ignored(self):
        latch = _latch()
        latch.open(("sig", 1))

        assert latch.note_frame(None) is None
        assert latch.note_frame("slow") is None
        assert latch.frames == 0


class TestFirstFrameCeiling:
    def test_first_frame_over_ceiling_trips_and_blacklists(self):
        latch = _latch()
        latch.open(("sig", 1))

        trip = latch.note_frame(FIRST_MS + 1.0)

        assert trip == ("first-aa-frame", pytest.approx(FIRST_MS + 1.0))
        assert latch.reason == ("first-aa-frame", pytest.approx(FIRST_MS + 1.0))
        assert ("sig", 1) in latch.blacklist

    def test_first_frame_under_ceiling_does_not_trip(self):
        """The first frame legitimately carries the one-off device-coordinate
        cache build, so it is judged against the HIGHER ceiling only."""
        latch = _latch()
        latch.open(("sig", 1))

        assert latch.note_frame(FIRST_MS - 1.0) is None
        assert latch.ema is None, "the first frame must not seed the steady EMA"
        assert latch.blacklist == {}

    def test_trip_disarms_the_session_until_reopened(self):
        """Further frames of a tripped session must not re-trip while the
        caller's deferred disable is still in flight."""
        latch = _latch()
        latch.open(("sig", 1))
        assert latch.note_frame(5_000.0) is not None

        assert latch.note_frame(5_000.0) is None
        assert len(latch.blacklist) == 1

        latch.open(("sig", 1))
        assert latch.note_frame(5_000.0) is not None


class TestSteadyEma:
    def test_first_steady_sample_seeds_the_ema(self):
        latch = _latch()
        latch.open(("sig", 1))
        latch.note_frame(5.0)

        assert latch.note_frame(100.0) is None
        assert latch.ema == pytest.approx(100.0)

    def test_single_mild_outlier_is_absorbed_then_a_sustained_one_trips(self):
        """Why an EMA and not a per-frame comparison: 5 / 100 / 300 averages to
        200 ms and passes; a further 600 ms frame lands on 400 ms and trips."""
        latch = _latch()
        latch.open(("sig", 1))
        latch.note_frame(5.0)
        latch.note_frame(100.0)

        assert latch.note_frame(300.0) is None
        assert latch.ema == pytest.approx(200.0)
        assert latch.blacklist == {}

        trip = latch.note_frame(600.0)

        assert trip == ("steady-aa-ema", pytest.approx(400.0))
        assert latch.ema == pytest.approx(400.0)
        assert ("sig", 1) in latch.blacklist

    def test_healthy_frames_never_trip(self):
        latch = _latch()
        latch.open(("sig", 1))
        for _ in range(200):
            assert latch.note_frame(5.0) is None
        assert latch.ema == pytest.approx(5.0)
        assert latch.blacklist == {}


class TestBlacklist:
    def test_blocked_is_false_for_unknown_and_none_signatures(self):
        latch = _latch()
        assert latch.blocked(("sig", 1)) is False
        assert latch.blocked(None) is False

        latch.open(("sig", 1))
        latch.note_frame(5_000.0)

        assert latch.blocked(("sig", 1)) is True
        assert latch.blocked(("sig", 2)) is False
        assert latch.blocked(None) is False

    def test_blacklist_is_lru_bounded(self):
        latch = _latch()
        for index in range(MAX_ENTRIES + 1):
            latch.open(("sig", index))
            latch.note_frame(5_000.0)

        assert len(latch.blacklist) == MAX_ENTRIES
        assert ("sig", 0) not in latch.blacklist, "the oldest entry is evicted"
        assert ("sig", MAX_ENTRIES) in latch.blacklist

    def test_blocked_hit_refreshes_lru_recency(self):
        """A signature the user keeps returning to must not be evicted by the
        signatures they visited once."""
        latch = _latch()
        for index in range(MAX_ENTRIES):
            latch.open(("sig", index))
            latch.note_frame(5_000.0)

        assert latch.blocked(("sig", 0)) is True  # touches the oldest entry

        latch.open(("sig", 99))
        latch.note_frame(5_000.0)

        assert ("sig", 0) in latch.blacklist
        assert ("sig", 1) not in latch.blacklist

    def test_retripping_a_known_signature_refreshes_recency(self):
        latch = _latch()
        for index in range(MAX_ENTRIES):
            latch.open(("sig", index))
            latch.note_frame(5_000.0)

        latch.open(("sig", 0))
        latch.note_frame(5_000.0)
        latch.open(("sig", 99))
        latch.note_frame(5_000.0)

        assert len(latch.blacklist) == MAX_ENTRIES
        assert ("sig", 0) in latch.blacklist
        assert ("sig", 1) not in latch.blacklist


class TestFirstFrameMemo:
    """The memo is the POSITIVE counterpart of the blacklist: what a view's
    first AA frame actually cost, so a cheap view can go straight to AA on the
    next visit instead of waiting out a quiet window. A key is in at most one
    of the two containers.
    """

    def test_first_frame_writes_the_memo(self):
        latch = _latch()
        latch.open(("sig", 1), memo_key=("sig", 1, 2.0))

        latch.note_frame(12.0)

        assert latch.memo_lookup(("sig", 1, 2.0)) == pytest.approx(12.0)

    def test_only_the_first_frame_writes_the_memo(self):
        latch = _latch()
        latch.open(("sig", 1), memo_key=("sig", 1, 2.0))
        latch.note_frame(12.0)
        latch.note_frame(200.0)   # steady frame, under the steady ceiling

        assert latch.memo_lookup(("sig", 1, 2.0)) == pytest.approx(12.0)

    def test_memo_lookup_misses_return_none(self):
        latch = _latch()
        assert latch.memo_lookup(("sig", 1, 2.0)) is None
        assert latch.memo_lookup(None) is None

    def test_open_without_memo_key_writes_nothing(self):
        latch = _latch()
        latch.open(("sig", 1))
        latch.note_frame(12.0)

        assert latch.memo == {}

    def test_trip_removes_the_memo_entry(self):
        """A view that tripped is a blacklist fact, not a memo fact — leaving
        the stale "it was cheap once" reading would re-enable AA on it."""
        latch = _latch()
        key = ("sig", 1, 2.0)
        latch.open(("sig", 1), memo_key=key)
        latch.note_frame(12.0)
        assert latch.memo_lookup(key) is not None

        latch.open(("sig", 1), memo_key=key)
        latch.note_frame(5_000.0)

        assert latch.memo_lookup(key) is None
        assert ("sig", 1) in latch.blacklist

    def test_steady_trip_also_removes_the_memo_entry(self):
        latch = _latch()
        key = ("sig", 1, 2.0)
        latch.open(("sig", 1), memo_key=key)
        latch.note_frame(12.0)
        latch.note_frame(600.0)
        latch.note_frame(600.0)

        assert latch.reason[0] == "steady-aa-ema"
        assert latch.memo_lookup(key) is None

    def test_memo_is_lru_bounded(self):
        latch = _latch()
        for index in range(MAX_ENTRIES + 1):
            latch.open(("sig", index), memo_key=("sig", index, 2.0))
            latch.note_frame(12.0)

        assert len(latch.memo) == MAX_ENTRIES
        assert latch.memo_lookup(("sig", 0, 2.0)) is None
        assert latch.memo_lookup(("sig", MAX_ENTRIES, 2.0)) is not None

    def test_memo_lookup_refreshes_lru_recency(self):
        latch = _latch()
        for index in range(MAX_ENTRIES):
            latch.open(("sig", index), memo_key=("sig", index, 2.0))
            latch.note_frame(12.0)

        assert latch.memo_lookup(("sig", 0, 2.0)) is not None

        latch.open(("sig", 99), memo_key=("sig", 99, 2.0))
        latch.note_frame(12.0)

        assert latch.memo_lookup(("sig", 0, 2.0)) is not None
        assert latch.memo_lookup(("sig", 1, 2.0)) is None

    def test_memo_survives_close(self):
        """Closing a session ends a measurement, it does not change the fact
        that this geometry's first AA frame cost what it cost."""
        latch = _latch()
        key = ("sig", 1, 2.0)
        latch.open(("sig", 1), memo_key=key)
        latch.note_frame(12.0)
        latch.close()

        assert latch.memo_lookup(key) == pytest.approx(12.0)


class TestNoQtDependency:
    def test_module_imports_no_gui_toolkit(self):
        """The latch is reused by canvases that must stay importable without a
        running Qt app; keeping it Qt-free is what makes it a pure state
        machine rather than a second widget.
        """
        source_path = (
            Path(__file__).resolve().parents[2]
            / "mf4_analyzer" / "ui" / "pg_canvas" / "quality_backstop.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert "PyQt5" not in imported
        assert "pyqtgraph" not in imported
