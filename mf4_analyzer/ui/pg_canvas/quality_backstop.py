"""Measured-AA-frame latch: the state machine behind the frame backstop.

Extracted from ``quality.QualityManager`` (spec
``docs/analyzer/specs/2026-08-15-view-switch-quality-settlement-spec.md`` §3.3).
Everything upstream of this layer — the ink metric, the AA band, the raster
admission — is a PREDICTION. This is the layer that measures what actually
happened, so a prediction that was wrong costs at most ONE bad frame per view
signature instead of repeating every time the idle timer fires.

It is deliberately **pure Python**: no Qt import, no canvas back-reference, no
timers. The scene mutation a trip implies (turning AA back off) must be
deferred out of ``paintEvent``, and that deferral is Qt work — it stays with
the caller (``QualityManager.backstop_timer``). What lives here is the
arithmetic and the bookkeeping, which is safe to run inside a paint.

Two containers, one invariant. A view signature that measured UNAFFORDABLE goes
into ``blacklist`` (negative memory: never pay that frame again). A view whose
first AA frame measured CHEAP goes into ``memo`` (positive memory: the next
visit can go straight to AA instead of waiting out a quiet window). A trip
moves a key from the second to the first, so a key is in at most one of them.
Both are LRU-bounded: unbounded per-view state on a long-lived UI object is a
leak.

The reason this is a shared class rather than three inlined copies: the
time-domain canvas, ``PgLineCanvas`` and ``PgFrfCanvas`` all need the same
calibrated ceilings and the same latch semantics. Three hand-written copies of
a calibrated state machine is exactly what CLAUDE.md and AGENTS.md forbid.
"""

from __future__ import annotations

from collections import OrderedDict


class AaFrameLatch:
    """Per-session AA frame measurement with negative + positive memory.

    Parameters mirror the calibrated constants in ``quality.py`` (spec
    2026-08-08 §5); they are passed in rather than imported so each canvas
    family can carry its own calibration without a second implementation:

    * ``first_ms`` — ceiling for the FIRST frame of a session, which
      legitimately carries one-off costs (device-coordinate cache build).
    * ``steady_ms`` — ceiling for the EMA of every subsequent frame.
    * ``ema_alpha`` — weight of each new frame in that EMA. The first steady
      sample seeds the EMA directly, so one catastrophic frame trips at once
      while one mildly slow frame is averaged down instead of latching on
      noise.
    * ``max_entries`` — LRU cap shared by the blacklist and the memo.

    Session shape: ``open()`` … ``note_frame()`` × N … ``close()``. Frames
    offered outside a session are ignored, so a non-AA frame interleaved by the
    widget toolkit can never be miscounted as "the first AA frame". A trip ends
    the session too (the caller's deferred disable is still in flight and must
    not be raised twice).
    """

    __slots__ = (
        "first_ms",
        "steady_ms",
        "ema_alpha",
        "max_entries",
        "epoch",
        "frames",
        "ema",
        "signature",
        "reason",
        "blacklist",
        "memo",
        "session_open",
        "memo_key",
    )

    def __init__(self, first_ms, steady_ms, ema_alpha, max_entries):
        self.first_ms = float(first_ms)
        self.steady_ms = float(steady_ms)
        self.ema_alpha = float(ema_alpha)
        self.max_entries = int(max_entries)
        # epoch identifies ONE session. It is bumped on open AND on close,
        # which is what lets a trip queued against "the session I measured" be
        # distinguished from some later session by the caller.
        self.epoch = 0
        self.frames = 0
        self.ema = None
        self.signature = None
        self.reason = None
        self.session_open = False
        self.memo_key = None
        self.blacklist = OrderedDict()
        self.memo = OrderedDict()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def open(self, signature, memo_key=None) -> int:
        """Start measuring a session for ``signature``; return the new epoch.

        ``memo_key`` is the key the first frame's cost is remembered under. It
        is separate from ``signature`` because the memo answers a slightly
        narrower question ("how many ms did this cost HERE") and therefore
        carries the device pixel ratio too, while ``signature`` is the
        2026-08-08 §4.4 four-input identity that must stay untouched.
        """
        self.epoch = int(self.epoch) + 1
        self.frames = 0
        self.ema = None
        self.signature = signature
        self.memo_key = memo_key
        self.session_open = True
        return self.epoch

    def close(self) -> int:
        """End the session and void any trip still queued against it."""
        self.epoch = int(self.epoch) + 1
        self.frames = 0
        self.ema = None
        self.signature = None
        self.memo_key = None
        self.session_open = False
        return self.epoch

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    def note_frame(self, frame_ms):
        """Feed one measured frame; return ``(reason, measured_ms)`` on a trip.

        Called from inside ``paintEvent`` on the caller's side, so the healthy
        path is float arithmetic and one attribute store — no logging, no
        allocation, no container growth. ``None`` means "nothing to do".
        """
        if not self.session_open:
            return None
        try:
            measured_ms = float(frame_ms)
        except (TypeError, ValueError):
            return None
        self.frames += 1
        if self.frames == 1:
            key = self.memo_key
            if key is not None:
                self._remember(key, measured_ms)
            if measured_ms > self.first_ms:
                return self._trip("first-aa-frame", measured_ms)
            return None
        previous = self.ema
        if previous is None:
            ema = measured_ms
        else:
            alpha = self.ema_alpha
            ema = alpha * measured_ms + (1.0 - alpha) * float(previous)
        self.ema = ema
        if ema > self.steady_ms:
            return self._trip("steady-aa-ema", ema)
        return None

    def _trip(self, reason: str, measured_ms: float):
        """Latch the current signature out of AA. Pure bookkeeping."""
        # End the session FIRST: further frames must not re-trip while the
        # caller's deferred disable is still in flight.
        self.session_open = False
        self.reason = (str(reason), float(measured_ms))
        key = self.memo_key
        if key is not None:
            # The positive memory for this view is now known to be wrong (or
            # to have gone stale); leaving it would re-enable AA on a view that
            # just measured unaffordable.
            self.memo.pop(key, None)
        signature = self.signature
        if signature is not None:
            blacklist = self.blacklist
            if signature in blacklist:
                blacklist.move_to_end(signature)
            else:
                blacklist[signature] = str(reason)
                while len(blacklist) > self.max_entries:
                    blacklist.popitem(last=False)
        return self.reason

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def blocked(self, signature) -> bool:
        """Whether ``signature`` already paid its one bad AA frame.

        A hit refreshes LRU recency: a view the user keeps returning to must
        not be evicted by the views they visited once.
        """
        blacklist = self.blacklist
        if not blacklist or signature is None:
            return False
        if signature not in blacklist:
            return False
        blacklist.move_to_end(signature)
        return True

    def memo_lookup(self, key):
        """Last measured FIRST-frame cost in ms for ``key``, or ``None``.

        Like ``blocked``, a hit refreshes recency: reading a memo is the use
        that keeps it alive.
        """
        memo = self.memo
        if not memo or key is None:
            return None
        value = memo.get(key)
        if value is None:
            return None
        memo.move_to_end(key)
        return value

    def _remember(self, key, measured_ms: float) -> None:
        memo = self.memo
        if key in memo:
            memo.move_to_end(key)
        memo[key] = measured_ms
        while len(memo) > self.max_entries:
            memo.popitem(last=False)


__all__ = ["AaFrameLatch"]
